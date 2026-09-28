"""Prequential runner: answer each question with current notes, score it, then (maybe) learn.
Writes one JSONL line per question and resumes from the last line after a crash or rate-limit stop."""
import json
import os
import random
from dataclasses import asdict
from pathlib import Path

import yaml
from tqdm import tqdm

from evosql.agent import answer, answer_self_consistent
from evosql.bird import exec_match, gold_rows, load_questions, open_db
from evosql.knowledge import Edit, Knowledge
from evosql.learner import Gate, GateConfig, propose
from evosql.llm import LLM, ProviderExhausted


def load_config(path="configs/base.yaml", agent=None):
    """Load settings and resolve the chosen agent profile into cfg["agent"], runs_dir and results_dir."""
    cfg = yaml.safe_load(Path(path).read_text())
    if "agents" in cfg:
        profile = cfg["agents"][agent or cfg["agent_profile"]]
        cfg.update(agent=profile, runs_dir=profile["runs_dir"], results_dir=profile["results_dir"])
    return cfg


def load_arm(name, arms_dir="configs/arms"):
    return yaml.safe_load((Path(arms_dir) / f"{name}.yaml").read_text())


def make_llm(role_cfg, cache_dir):
    key_env = role_cfg.get("api_key_env")
    api_key = os.environ[key_env] if key_env else "local"
    return LLM(role_cfg["model"], role_cfg["base_url"], api_key, cache_dir, options=role_cfg.get("options"))


def noise_path(cfg):
    return Path(cfg["runs_dir"]) / "noise" / f"{cfg['db']}.json"


def question_text(q, hints):
    return f"{q.question}\nHint: {q.evidence}" if hints and q.evidence else q.question


def _diff(after, before):
    return {k: after[k] - before[k] for k in after}


def resume_point(log_path, notes_path):
    """Number of finished steps. Repairs the two ways a kill can leave the log and notes out of sync."""
    lines = log_path.read_text().splitlines() if log_path.exists() else []
    saved = json.loads(notes_path.read_text()).get("done", 0) if notes_path.exists() else 0
    try:
        if lines:
            json.loads(lines[-1])
    except json.JSONDecodeError:
        lines = lines[:-1]  # partial last line from a kill mid-write
    if len(lines) == saved + 1:
        lines = lines[:-1]  # killed after logging a step but before saving its notes: redo that step
    if len(lines) != saved:
        raise RuntimeError(f"{log_path} has {len(lines)} steps but notes say {saved}; fix or delete both files")
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text("".join(line + "\n" for line in lines))
    return saved


def run_arm(cfg, arm_name, order_seed, limit=None, agent_llm=None, proposer_llm=None):
    arm = load_arm(arm_name, cfg.get("arms_dir", "configs/arms"))
    db = open_db(cfg["data_dir"], cfg["db"], with_docs=arm.get("docs", False))
    questions = load_questions(cfg["data_dir"], cfg["db"])
    by_id = {q.qid: q for q in questions}
    order = list(questions)
    random.Random(order_seed).shuffle(order)
    end = len(order) if limit is None else min(limit, len(order))

    out = Path(cfg["runs_dir"]) / arm_name / cfg["db"]
    log_path, notes_path = out / f"order{order_seed}.jsonl", out / f"order{order_seed}.notes.json"
    out.mkdir(parents=True, exist_ok=True)
    done = resume_point(log_path, notes_path)
    knowledge = Knowledge.load(notes_path) if notes_path.exists() else Knowledge()

    agent_llm = agent_llm or make_llm(cfg["agent"], cfg["cache_dir"])
    learning = arm.get("learning", False)
    if learning:
        proposer_llm = proposer_llm or make_llm(cfg["proposer"], cfg["cache_dir"])
    hints, max_steps, sc_n = arm.get("hints", False), cfg["max_steps"], arm.get("self_consistency_n")

    prior = [json.loads(line)["correct"] for line in log_path.read_text().splitlines()] if log_path.exists() else []
    right = sum(prior)
    bar = tqdm(total=end, initial=done, desc=f"{arm_name} order {order_seed}", unit="q", dynamic_ncols=True)

    def status(text):
        bar.set_postfix_str(f"acc {right}/{bar.n} | notes {len(knowledge.notes)}" + (f" | {text}" if text else ""))

    def agent_steps(qid, phase):
        return lambda step, tools: status(f"{phase} q{qid} step {step}: {', '.join(tools) or 'thinking'}")

    def solve(q, k):
        r = answer(agent_llm, db, question_text(q, hints), k, max_steps=max_steps, on_step=agent_steps(q.qid, "re-check"))
        return exec_match(db.path, r.sql, gold_rows(db.path, q))

    gate = None
    if learning:
        gate_cfg = dict(arm["gate"])
        if gate_cfg.get("noise_p") == "calibrated":
            if not noise_path(cfg).exists():
                raise SystemExit(f"{arm_name} needs the noise rate first: run `python -m evosql calibrate`")
            gate_cfg["noise_p"] = json.loads(noise_path(cfg).read_text())["p"]
        gate = Gate(GateConfig(**gate_cfg), solve, db.tables, by_id)

    llms = [agent_llm] + ([proposer_llm] if learning else [])
    snapshot = lambda: [dict(m.usage) for m in llms]
    for step in range(done, end):
        q = order[step]
        u0 = snapshot()
        try:
            if sc_n:
                status(f"q{q.qid} voting over {sc_n} samples")
                r = answer_self_consistent(agent_llm, db, question_text(q, hints), knowledge, sc_n, max_steps)
            else:
                r = answer(agent_llm, db, question_text(q, hints), knowledge, max_steps=max_steps,
                           on_step=agent_steps(q.qid, "answer"))
            gold = gold_rows(db.path, q)
            correct = exec_match(db.path, r.sql, gold)
            rec = {"step": step, "qid": q.qid, "difficulty": q.difficulty, "sql": r.sql, "correct": correct,
                   "agent_error": r.error, "agent_steps": r.steps}
            u1 = snapshot()
            if learning and not correct:
                status(f"q{q.qid} wrong, proposing a note")
                edit = propose(proposer_llm, db, q.question, r.sql, q.gold_sql, knowledge)
                rec["edit"] = asdict(edit) if edit else None
                if edit is None:
                    rec["decision"], rec["reason"] = "rejected", "proposer_error"
                else:
                    d = gate.accept(edit, q, knowledge, order[:step], step, gold)
                    knowledge = d.knowledge
                    rec["decision"] = "accepted" if d.accepted else "rejected"
                    rec.update(reason=d.reason, gain=d.gain, replay_n=d.replay_n, pruned=d.pruned or [])
            if learning and gate.cfg.prune_every and (step + 1) % gate.cfg.prune_every == 0:
                status("pruning notes")
                knowledge, removed = gate.prune(knowledge)
                rec["pruned"] = rec.get("pruned", []) + removed
        except ProviderExhausted as e:
            bar.close()
            print(f"provider exhausted at step {step}: {e}. Progress saved; rerun the same command later.")
            return False
        u2 = snapshot()
        rec["answer_usage"] = _diff(u1[0], u0[0])
        rec["learn_usage"] = [_diff(a, b) for a, b in zip(u2, u1)]
        rec.update(notes_count=len(knowledge.notes), notes_tokens=knowledge.total_tokens(),
                   models=sorted(set().union(*(m.models_seen for m in llms))))
        with open(log_path, "a") as f:
            f.write(json.dumps(rec) + "\n")
        knowledge.save(notes_path, done=step + 1)
        right += correct
        bar.update(1)
        learned = ""
        if rec.get("decision") == "accepted":
            learned = f" | note accepted (net gain {rec['gain']}), {len(knowledge.notes)} notes"
        elif rec.get("decision"):
            learned = f" | note rejected: {rec['reason']}"
        tqdm.write(f"  {step + 1}/{end} q{q.qid} {'right' if correct else 'wrong'}{learned}")
        status("")
    bar.close()
    return True


NEUTRAL_NOTE = Edit("add", when="any question", text="Double-check that every column you use exists in the schema.")


def calibrate(cfg, n=20, agent_llm=None):
    """Flip rate p: how often correctness changes when a harmless note is added (the gate's noise)."""
    db = open_db(cfg["data_dir"], cfg["db"], with_docs=True)
    order = load_questions(cfg["data_dir"], cfg["db"])
    random.Random(0).shuffle(order)
    agent_llm = agent_llm or make_llm(cfg["agent"], cfg["cache_dir"])
    neutral, _ = Knowledge().apply(NEUTRAL_NOTE, step=-1, qid=-1)
    flips = 0
    bar = tqdm(order[:n], desc="calibrate", unit="q", dynamic_ncols=True)
    for q in bar:
        gold = gold_rows(db.path, q)
        runs = []
        for label, k in (("no note", Knowledge()), ("harmless note", neutral)):
            show = lambda step, tools: bar.set_postfix_str(
                f"flips {flips} | q{q.qid} {label}, step {step}: {', '.join(tools) or 'thinking'}")
            runs.append(exec_match(db.path, answer(agent_llm, db, q.question, k, max_steps=cfg["max_steps"],
                                                   on_step=show).sql, gold))
        flips += runs[0] != runs[1]
        mark = lambda ok: "right" if ok else "wrong"
        tqdm.write(f"  q{q.qid}: no note {mark(runs[0])}, harmless note {mark(runs[1])}"
                   f"{'  <- flip' if runs[0] != runs[1] else ''}")
        bar.set_postfix_str(f"flips {flips}")
    bar.close()
    result = {"p": flips / n, "flips": flips, "n": n}
    noise_path(cfg).parent.mkdir(parents=True, exist_ok=True)
    noise_path(cfg).write_text(json.dumps(result))
    return result
