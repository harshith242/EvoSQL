"""The v9 stream on EHRSQL: the none, facts and examples arms of v8 (replay-only, free) plus a live examples + notes arm
whose working-notes file is edited after each failure and checked against earlier questions. Every reply is cached."""
import hashlib
import json
import os
import random
from dataclasses import asdict, dataclass
from pathlib import Path

from tqdm import tqdm

from evosql.agent import answer
from evosql.bird import exec_match, gold_rows
from evosql.budget import Budget, BudgetExceeded
from evosql.consolidate import consolidate
from evosql.ehrsql import load_stream, open_mimic, score_sql
from evosql.facts import check, check_snippet, render
from evosql.files import append_jsonl, write_atomic
from evosql.jev import Jev, JevUnavailable
from evosql.llm import ProviderExhausted, ReplayMiss, make_llm, usd
from evosql.memory import FactMemory
from evosql.notes import Notes, apply, propose_edits, validate
from evosql.proposer import propose
from evosql.search import Embedder, examples_notes, similar


def stream_log(out, seed, db_id):
    return Path(out) / f"stream_s{seed}_{db_id}.jsonl"


def facts_file(out, seed, db_id):
    return Path(out) / f"facts_s{seed}_{db_id}.json"


def notes_file(out, seed, db_id):
    return Path(out) / f"notes_s{seed}_{db_id}.md"


def consolidation_log(out, seed, db_id):
    return Path(out) / f"consolidation_s{seed}_{db_id}.jsonl"


def usage_since(llm, before):
    return {k: llm.usage[k] - before.get(k, 0) for k in llm.usage}


def add_usage(a, b):
    return {k: a.get(k, 0) + b.get(k, 0) for k in {*a, *b}}


class Answers:
    """Answers memoised by (question, knowledge text); a replay reports no new usage but keeps its API latency."""

    def __init__(self, agent, max_steps, score=None):
        self.agent, self.max_steps, self.memo = agent, max_steps, {}
        self.score = score or (lambda sql: sql)  # e.g. the official post-processing, applied before scoring

    def get(self, db, q, gold, facts=(), notes=None):
        notes = render(facts) if notes is None else notes
        key = (q.db_id, q.qid, notes)
        if key in self.memo:
            return {**self.memo[key], "usage": {}}
        before = dict(self.agent.usage)
        sql, turns = answer(self.agent, db, q.question, notes, self.max_steps)
        usage = usage_since(self.agent, before)
        self.memo[key] = {"sql": sql, "turns": turns, "ok": exec_match(db.path, self.score(sql), gold),
                          "latency_s": usage.get("latency_s", 0.0)}
        return {**self.memo[key], "usage": usage}


@dataclass
class Live:
    """What the notes arm needs beyond the replay-only arms: live answers and proposer, a budget rule, notes limits."""
    answers: Answers
    proposer: object
    can_check: object
    notes_cfg: dict


def notes_text(shown, notes):
    """The agent's knowledge section in the notes arm: the shown examples, then the notes when there are any."""
    return "\n\n".join(t for t in (examples_notes(shown), notes.render()) if t)


def trier(db, answers, usage):
    """try_fact(fact, question) for pre-checks: answers with only that fact and adds the usage to usage["precheck"]."""
    def try_fact(fact, eq):
        result = answers.get(db, eq, gold_rows(db.path, eq), [fact])
        usage["precheck"] = add_usage(usage["precheck"], result["usage"])
        return result["ok"]

    return try_fact


def learn(db, q, gold, facts_sql, answers, proposer, memory, precheck):
    """Propose one fact from a failure of the facts arm, check it, and admit it (with a pre-check if allowed)."""
    before = dict(proposer.usage)
    fact, why = propose(proposer, db, q, facts_sql, memory.active())
    reason = why or check(fact, db, q, gold)
    usage = {"proposer": usage_since(proposer, before), "precheck": {}}
    if reason:
        return {"outcome": "dropped", "reason": reason, "fact": fact and asdict(fact), "usage": usage}

    snippet = None
    if fact.sql:
        snippet = check_snippet(fact.sql, db, q, gold) or "kept"
        if snippet != "kept":
            fact.sql = None

    record = memory.admit(fact, trier(db, answers, usage) if precheck else None)
    return {**record, "fact": asdict(fact), "snippet": snippet, "usage": usage}


def consolidation_pass(pos, db, answers, proposer, memory, can_precheck, path):
    """One consolidation pass after question pos, logged; skipped when the budget rule allows no pre-checks."""
    if not can_precheck():
        append_jsonl(path, {"after_pos": pos, "skipped": "budget"})
        return
    usage = {"proposer": {}, "precheck": {}}
    before, jev_before = dict(proposer.usage), memory.jev.usage["usd"]
    edits = consolidate(proposer, memory, lambda q: gold_rows(db.path, q), trier(db, answers, usage))
    usage["proposer"] = usage_since(proposer, before)
    append_jsonl(path, {"after_pos": pos, "edits": edits, "usage": usage,
                        "jev_usd": memory.jev.usage["usd"] - jev_before})


def update_notes(db, q, gold, shown, agent_sql, notes, past, proposer, answers, embed, can_check, notes_cfg):
    """(notes, log): edits proposed after a failure of q, kept only if they pass the regression check."""
    before = dict(proposer.usage)
    proposed = propose_edits(proposer, db, notes, q, shown, agent_sql, notes_cfg["max_lines"])
    usage = {"proposer": usage_since(proposer, before), "check": {}}
    edits = []
    for e in proposed:
        reason = validate(e, notes, q, gold, notes_cfg["max_words"])
        edits.append({**e, "valid": reason is None, "reason": reason})
    valid = [e for e in edits if e["valid"]]
    log = {"edits": edits, "outcome": None, "checked": [], "broke": None, "fixes_source": None, "usage": usage}

    if not valid:
        log["outcome"] = "no valid edits" if edits else "no edits"
        return notes, log
    draft = apply(notes, valid)
    if draft.line_count() > notes_cfg["max_lines"]:
        log["outcome"] = "rejected: notes full"
        return notes, log

    def reanswer(eq, eq_shown, eq_gold):
        result = answers.get(db, eq, eq_gold, notes=notes_text(eq_shown, draft))
        usage["check"] = add_usage(usage["check"], result["usage"])
        return result["ok"]

    log["fixes_source"] = reanswer(q, shown, gold)  # logged only, never required

    candidates = [p for p in past if p[2]]  # earlier questions the notes arm answered correctly
    if not candidates:
        log["outcome"] = "applied unchecked"
        return draft, log
    if not can_check():
        log["outcome"] = "applied unchecked (budget)"
        return draft, log

    by_qid = {c[0].qid: c for c in candidates}
    nearest = similar(embed, q.question, [c[0] for c in candidates], 1)[0]
    others = [c for c in candidates if c[0].qid != nearest.qid]
    picks = [by_qid[nearest.qid]] + ([random.Random(q.qid).choice(others)] if others else [])
    log["checked"] = [c[0].qid for c in picks]
    wrong = [eq.qid for eq, eq_shown, _ in picks if not reanswer(eq, eq_shown, gold_rows(db.path, eq))]
    if wrong:
        log["outcome"], log["broke"] = "rejected: regression", wrong[0]
        return notes, log
    log["outcome"] = "applied"
    return draft, log


def run_stream(db, order, answers, proposer, memory, can_precheck, log_path, consolidation_path, every, templates,
               components, k_examples, live=None, bar=None):
    """One (database, order) stream: one log record per question, a consolidation pass every N and at the end.
    Returns the final notes (None without a live notes arm)."""
    write_atomic(log_path, "")
    write_atomic(consolidation_path, "")
    notes, notes_past = Notes(), []  # notes_past: (question, examples shown, notes arm correct) so far
    for pos, q in enumerate(order, 1):
        jev_before = memory.jev.usage["usd"]
        gold = gold_rows(db.path, q)

        # All arms answer before anything about q is revealed; with nothing injected, an arm replays none.
        none = answers.get(db, q, gold, [])
        picked, scores = memory.select(q.question)
        facts = answers.get(db, q, gold, picked)
        shown = similar(memory.embed, q.question, [eq for eq, _ in memory.history], k_examples)
        examples = answers.get(db, q, gold, notes=examples_notes(shown))
        if live:  # with empty notes this prompt equals the examples arm's, so it replays that answer
            notes_arm = live.answers.get(db, q, gold, notes=notes_text(shown, notes))

        # Reveal the correct answer: credit the injected facts, learn from a failure, then remember q.
        memory.credit([f.id for f in picked], facts["ok"], none["ok"])
        learning = None
        if not facts["ok"]:
            learning = learn(db, q, gold, facts["sql"], answers, proposer, memory, can_precheck())
        memory.observe(q, none["ok"])
        if live:
            notes_lines, update = notes.line_count(), None
            if not notes_arm["ok"]:
                notes, update = update_notes(db, q, gold, shown, notes_arm["sql"], notes, notes_past, live.proposer,
                                             live.answers, memory.embed, live.can_check, live.notes_cfg)
            notes_past.append((q, shown, notes_arm["ok"]))

        # A combination question's own templates are its two components.
        own = components.get(q.qid) or [templates.get(q.qid)]
        record = {
            "pos": pos, "qid": q.qid, "template": templates.get(q.qid), "components": components.get(q.qid),
            "none_ok": none["ok"], "facts_ok": facts["ok"], "examples_ok": examples["ok"],
            "none_sql": none["sql"], "facts_sql": facts["sql"], "examples_sql": examples["sql"],
            "turns": [none["turns"], facts["turns"], examples["turns"]],
            "injected": [f.id for f in picked], "memory_size": len(memory.active()),
            "examples_used": [eq.qid for eq in shown],
            "examples_same_template": [templates.get(eq.qid) is not None and templates.get(eq.qid) in own
                                       for eq in shown],
            "latency_s": [none["latency_s"], facts["latency_s"], examples["latency_s"]],
            "usage": {"none": none["usage"], "facts": facts["usage"], "examples": examples["usage"]},
            "learning": learning, "jev_usd": memory.jev.usage["usd"] - jev_before, "jev_scores": scores,
        }
        if live:
            record["turns"].append(notes_arm["turns"])
            record["latency_s"].append(notes_arm["latency_s"])
            record["usage"]["notes"] = notes_arm["usage"]
            record |= {"notes_ok": notes_arm["ok"], "notes_sql": notes_arm["sql"], "notes_lines": notes_lines,
                       "notes_update": update}
        append_jsonl(log_path, record)
        # The final pass covers the last question, so a multiple of `every` there is not repeated.
        if pos % every == 0 and pos < len(order):
            consolidation_pass(pos, db, answers, proposer, memory, can_precheck, consolidation_path)
        if bar:
            bar.update(1)
    consolidation_pass(len(order), db, answers, proposer, memory, can_precheck, consolidation_path)
    return notes if live else None


REPLAY_ARMS = [f"{arm}_{k}" for arm in ("none", "facts", "examples") for k in ("ok", "sql")]


def replay_differences(new_path, old_path):
    """(differences of the old arms' answers between two logs, records identical): a replay must equal the old run."""
    read = lambda path: [json.loads(line) for line in Path(path).read_text().splitlines()]
    new, old = read(new_path), read(old_path)
    diffs = [f"pos {o['pos']} {k}: {o[k]!r} became {n.get(k)!r}" for n, o in zip(new, old) for k in REPLAY_ARMS
             if n.get(k) != o[k]]
    diffs += [f"{len(new)} records instead of {len(old)}"] * (len(new) != len(old))
    return diffs, sum(all(n.get(k) == o[k] for k in REPLAY_ARMS) for n, o in zip(new, old))


def run(cfg, replay_check=False):
    """All streams, order by order; the old arms only replay. replay_check runs them alone into <runs_dir>_replay."""
    sc = cfg["stream"]
    out = Path(cfg["runs_dir"] + "_replay" if replay_check else cfg["runs_dir"])
    pinned = json.loads((Path(cfg["data_dir"]) / "manifest.json").read_text())["stream"]["sha256"]
    if pinned != hashlib.sha256(Path(sc["questions"]).read_bytes()).hexdigest():
        raise SystemExit(f"{sc['questions']} does not match its manifest: rerun scripts/get_ehrsql_data.py")
    questions, templates, components = load_stream(sc["questions"])
    dbs = {d: open_mimic(cfg["data_dir"], d) for d in sc["databases"]}

    budget = Budget(out / "spend.json", sc["budget_usd"])
    agent = make_llm(cfg["agent"], cfg["cache_dir"], replay_only=True)
    proposer = make_llm(cfg["proposer"], cfg["cache_dir"], replay_only=True)
    answers = Answers(agent, cfg["max_steps"], score_sql)
    embed = Embedder(cfg["embed"]["model"], cfg["embed"]["url"])
    jev = Jev(cfg["jev"]["model"], cfg["jev"]["url"], os.environ[cfg["jev"]["api_key_env"]], replay_only=True)
    priced = [(agent, cfg["agent"]), (proposer, cfg["proposer"])]
    if not replay_check:
        agent_live = make_llm(cfg["agent"], cfg["cache_dir"], budget.spend)
        notes_proposer = make_llm(cfg["proposer"], cfg["cache_dir"], budget.spend)
        answers_live = Answers(agent_live, cfg["max_steps"], score_sql)
        priced += [(agent_live, cfg["agent"]), (notes_proposer, cfg["proposer"])]
    cost = lambda pairs: sum(usd(llm.usage, role.get("usd_per_million")) for llm, role in pairs)
    logical = lambda: cost(priced) + jev.usage["usd"]

    try:
        for seed, allocation in zip(sc["seeds"], sc["order_budget_usd"]):
            for db_id, db in dbs.items():
                # Template questions in a seeded shuffle, then the combination questions, which come last.
                order = [q for q in questions if q.db_id == db_id and q.qid not in components]
                random.Random(seed).shuffle(order)
                order += [q for q in questions if q.db_id == db_id and q.qid in components]
                memory = FactMemory(db, jev, embed, sc["rules"], f"{db_id} ({sc['databases'][db_id]})")
                # v8 never skipped a pre-check, so the replayed facts arm must not either.
                can_precheck = lambda: True
                live = None if replay_check else Live(
                    answers_live, notes_proposer, lambda: cost(priced[2:]) < allocation - sc["precheck_reserve_usd"],
                    sc["notes"])
                with tqdm(total=len(order), desc=f"order {seed} {db_id}", unit="q", dynamic_ncols=True) as bar:
                    notes = run_stream(db, order, answers, proposer, memory, can_precheck, stream_log(out, seed, db_id),
                                       consolidation_log(out, seed, db_id), sc["consolidate_every"], templates,
                                       components, sc["examples"], live, bar)
                write_atomic(facts_file(out, seed, db_id), json.dumps(
                    [{**asdict(f), **memory.state.get(f.id, {})} for f in memory.facts.values()], indent=1))
                if notes is not None:
                    write_atomic(notes_file(out, seed, db_id), notes.to_markdown())
                if replay_check:
                    diffs, same = replay_differences(stream_log(out, seed, db_id), stream_log("runs_v8", seed, db_id))
                    print(f"replay {'identical' if not diffs else 'DIFFERS'}: {same}/{len(order)}")
                    if diffs:
                        print("\n".join(diffs[:10]))
    except ReplayMiss as e:
        print(f"stopped: {e}")
        return
    except (BudgetExceeded, ProviderExhausted, JevUnavailable) as e:
        print(f"stopped: {e}. Rerun `stream` to continue; finished calls replay from cache for free.")
        return
    print(f"done: logical cost ${logical():.3f}, real spend ${budget.total:.3f}")
