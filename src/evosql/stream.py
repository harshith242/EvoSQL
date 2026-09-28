"""Prequential runner: answer each question with current notes, score it, then (maybe) learn.
Writes one JSONL line per question and resumes from the last line after a crash or rate-limit stop."""
import json
import os
import random
from dataclasses import asdict
from pathlib import Path

import yaml

from evosql.agent import answer, answer_self_consistent
from evosql.bird import exec_match, gold_rows, load_questions, open_db
from evosql.knowledge import Edit, Knowledge
from evosql.learner import Gate, GateConfig, propose
from evosql.llm import LLM, ProviderExhausted


def load_config(path="configs/base.yaml"):
    return yaml.safe_load(Path(path).read_text())


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
    done = len(log_path.read_text().splitlines()) if log_path.exists() else 0
    knowledge = Knowledge.load(notes_path) if notes_path.exists() else Knowledge()

    agent_llm = agent_llm or make_llm(cfg["agent"], cfg["cache_dir"])
    learning = arm.get("learning", False)
    if learning:
        proposer_llm = proposer_llm or make_llm(cfg["proposer"], cfg["cache_dir"])
    hints, max_steps, sc_n = arm.get("hints", False), cfg["max_steps"], arm.get("self_consistency_n")

    def solve(q, k):
        r = answer(agent_llm, db, question_text(q, hints), k, max_steps=max_steps)
        return exec_match(db.path, r.sql, gold_rows(db.path, q))

    gate = None
    if learning:
        gate_cfg = dict(arm["gate"])
        if gate_cfg.get("noise_p") == "calibrated":
            gate_cfg["noise_p"] = json.loads(noise_path(cfg).read_text())["p"]
        gate = Gate(GateConfig(**gate_cfg), solve, db.tables, by_id)

    llms = [agent_llm] + ([proposer_llm] if learning else [])
    snapshot = lambda: [dict(m.usage) for m in llms]
    for step in range(done, end):
        q = order[step]
        u0 = snapshot()
        try:
            if sc_n:
                r = answer_self_consistent(agent_llm, db, question_text(q, hints), knowledge, sc_n, max_steps)
            else:
                r = answer(agent_llm, db, question_text(q, hints), knowledge, max_steps=max_steps)
            gold = gold_rows(db.path, q)
            correct = exec_match(db.path, r.sql, gold)
            rec = {"step": step, "qid": q.qid, "difficulty": q.difficulty, "sql": r.sql, "correct": correct,
                   "agent_error": r.error, "agent_steps": r.steps}
            u1 = snapshot()
            if learning and not correct:
                edit = propose(proposer_llm, db, q.question, r.sql, q.gold_sql, knowledge)
                rec["edit"] = asdict(edit) if edit else None
                if edit is None:
                    rec["decision"], rec["reason"] = "rejected", "proposer_error"
                else:
                    d = gate.accept(edit, q, knowledge, order[:step], step, gold)
                    knowledge = d.knowledge
                    rec["decision"] = "accepted" if d.accepted else "rejected"
                    rec.update(reason=d.reason, gain=d.gain, replay_n=d.replay_n)
            if learning and gate.cfg.prune_every and (step + 1) % gate.cfg.prune_every == 0:
                knowledge, rec["pruned"] = gate.prune(knowledge)
        except ProviderExhausted as e:
            print(f"provider exhausted at step {step}: {e}. Progress saved; rerun the same command later.")
            return False
        u2 = snapshot()
        rec["answer_usage"] = _diff(u1[0], u0[0])
        rec["learn_usage"] = [_diff(a, b) for a, b in zip(u2, u1)]
        rec.update(notes_count=len(knowledge.notes), notes_tokens=knowledge.total_tokens(),
                   models=sorted(set().union(*(m.models_seen for m in llms))))
        with open(log_path, "a") as f:
            f.write(json.dumps(rec) + "\n")
        knowledge.save(notes_path)
        print(f"[{arm_name} o{order_seed}] {step + 1}/{end} q{q.qid} correct={correct} "
              f"notes={len(knowledge.notes)} {rec.get('decision', '')} {rec.get('reason', '')}", flush=True)
    return True


NEUTRAL_NOTE = Edit("add", when="any question", text="Double-check that every column you use exists in the schema.")


def calibrate(cfg, n=20, agent_llm=None):
    """Flip rate p: how often correctness changes when a harmless note is added to the prompt.
    This is the noise the gate faces, since it compares notes vs. notes + one new note."""
    db = open_db(cfg["data_dir"], cfg["db"], with_docs=True)
    order = load_questions(cfg["data_dir"], cfg["db"])
    random.Random(0).shuffle(order)
    agent_llm = agent_llm or make_llm(cfg["agent"], cfg["cache_dir"])
    neutral, _ = Knowledge().apply(NEUTRAL_NOTE, step=-1, qid=-1)
    flips = 0
    for q in order[:n]:
        gold = gold_rows(db.path, q)
        runs = [exec_match(db.path, answer(agent_llm, db, q.question, k, max_steps=cfg["max_steps"]).sql, gold)
                for k in (Knowledge(), neutral)]
        flips += runs[0] != runs[1]
    result = {"p": flips / n, "flips": flips, "n": n}
    noise_path(cfg).parent.mkdir(parents=True, exist_ok=True)
    noise_path(cfg).write_text(json.dumps(result))
    return result
