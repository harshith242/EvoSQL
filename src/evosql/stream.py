"""The v7 stream: for one order and each database, the none and facts arms answer each question, the memory learns from
the correct SQL, and it is consolidated every N questions and at the end. Every LLM and JEV reply is cached on disk,
so the none arm replays v6 and a rerun replays finished work for free and identically."""
import hashlib
import json
import os
import random
from dataclasses import asdict
from pathlib import Path

from tqdm import tqdm

from evosql.agent import answer
from evosql.bird import exec_match, gold_rows, load_arcwise, open_db
from evosql.budget import Budget, BudgetExceeded
from evosql.consolidate import consolidate
from evosql.facts import check, check_snippet, render
from evosql.files import append_jsonl, write_atomic
from evosql.jev import Jev, JevUnavailable
from evosql.llm import ProviderExhausted, make_llm, usd
from evosql.memory import FactMemory
from evosql.proposer import propose
from evosql.search import Embedder


def stream_log(out, seed, db_id):
    return Path(out) / f"stream_s{seed}_{db_id}.jsonl"


def facts_file(out, seed, db_id):
    return Path(out) / f"facts_s{seed}_{db_id}.json"


def consolidation_log(out, seed, db_id):
    return Path(out) / f"consolidation_s{seed}_{db_id}.jsonl"


def usage_since(llm, before):
    return {k: llm.usage[k] - before.get(k, 0) for k in llm.usage}


def add_usage(a, b):
    return {k: a.get(k, 0) + b.get(k, 0) for k in {*a, *b}}


class Answers:
    """Answers memoised by (question, knowledge text); a replay reports no new usage but keeps its API latency."""

    def __init__(self, agent, max_steps):
        self.agent, self.max_steps, self.memo = agent, max_steps, {}

    def get(self, db, q, gold, facts=(), notes=None):
        notes = render(facts) if notes is None else notes
        key = (q.db_id, q.qid, notes)
        if key in self.memo:
            return {**self.memo[key], "usage": {}}
        before = dict(self.agent.usage)
        sql, turns = answer(self.agent, db, q.question, notes, self.max_steps)
        usage = usage_since(self.agent, before)
        self.memo[key] = {"sql": sql, "turns": turns, "ok": exec_match(db.path, sql, gold),
                          "latency_s": usage.get("latency_s", 0.0)}
        return {**self.memo[key], "usage": usage}


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


def run_stream(db, order, answers, proposer, memory, can_precheck, log_path, consolidation_path, every, bar=None):
    """One (database, order) stream: one log record per question, a consolidation pass every N and at the end."""
    write_atomic(log_path, "")
    write_atomic(consolidation_path, "")
    for pos, q in enumerate(order, 1):
        jev_before = memory.jev.usage["usd"]
        gold = gold_rows(db.path, q)

        # Both arms answer before anything about q is revealed; with no fact injected, facts replays none.
        none = answers.get(db, q, gold, [])
        picked, scores = memory.select(q.question)
        facts = answers.get(db, q, gold, picked)

        # Reveal the correct answer: credit the injected facts, learn from a failure, then remember q.
        memory.credit([f.id for f in picked], facts["ok"], none["ok"])
        learning = None
        if not facts["ok"]:
            learning = learn(db, q, gold, facts["sql"], answers, proposer, memory, can_precheck())
        memory.observe(q, none["ok"])

        append_jsonl(log_path, {
            "pos": pos, "qid": q.qid, "none_ok": none["ok"], "facts_ok": facts["ok"],
            "none_sql": none["sql"], "facts_sql": facts["sql"], "turns": [none["turns"], facts["turns"]],
            "injected": [f.id for f in picked], "memory_size": len(memory.active()),
            "latency_s": [none["latency_s"], facts["latency_s"]],
            "usage": {"none": none["usage"], "facts": facts["usage"]},
            "learning": learning, "jev_usd": memory.jev.usage["usd"] - jev_before, "jev_scores": scores,
        })
        # The final pass covers the last question, so a multiple of `every` there is not repeated.
        if pos % every == 0 and pos < len(order):
            consolidation_pass(pos, db, answers, proposer, memory, can_precheck, consolidation_path)
        if bar:
            bar.update(1)
    consolidation_pass(len(order), db, answers, proposer, memory, can_precheck, consolidation_path)


def check_pinned(questions_path):
    """Stop if the question file differs from the one pinned in the data manifest."""
    manifest = json.loads((Path(questions_path).parent / "manifest.json").read_text())
    digest = hashlib.sha256(Path(questions_path).read_bytes()).hexdigest()
    if manifest["sha256"].get(str(questions_path)) != digest:
        raise SystemExit(f"{questions_path} does not match its manifest: rerun scripts/get_v6_data.py")


def run(cfg):
    """All streams, order by order; pre-checks stop near each order's allocation of this run's logical spend."""
    sc, out = cfg["stream"], Path(cfg["runs_dir"])
    check_pinned(sc["questions"])
    questions = load_arcwise(sc["questions"], set(sc["databases"]))
    dbs = {d: open_db(cfg["data_dir"], d, Path(sc["docs_root"]) / d / "database_description") for d in sc["databases"]}

    budget = Budget(out / "spend.json", sc["budget_usd"])
    agent = make_llm(cfg["agent"], cfg["cache_dir"], budget.spend)
    proposer = make_llm(cfg["proposer"], cfg["cache_dir"], budget.spend)
    answers = Answers(agent, cfg["max_steps"])
    embed = Embedder(cfg["embed"]["model"], cfg["embed"]["url"])
    jev = Jev(cfg["jev"]["model"], cfg["jev"]["url"], os.environ[cfg["jev"]["api_key_env"]], on_spend=budget.spend)
    logical = lambda: usd(agent.usage, cfg["agent"].get("usd_per_million")) + \
        usd(proposer.usage, cfg["proposer"].get("usd_per_million")) + jev.usage["usd"]

    try:
        for seed, allocation in zip(sc["seeds"], sc["order_budget_usd"]):
            for db_id, db in dbs.items():
                order = sorted((q for q in questions if q.db_id == db_id), key=lambda q: q.qid)
                random.Random(seed).shuffle(order)
                memory = FactMemory(db, jev, embed, sc["rules"], f"{db_id} ({sc['databases'][db_id]})")
                can_precheck = lambda: logical() < allocation - sc["precheck_reserve_usd"]
                with tqdm(total=len(order), desc=f"order {seed} {db_id}", unit="q", dynamic_ncols=True) as bar:
                    run_stream(db, order, answers, proposer, memory, can_precheck, stream_log(out, seed, db_id),
                               consolidation_log(out, seed, db_id), sc["consolidate_every"], bar)
                write_atomic(facts_file(out, seed, db_id), json.dumps(
                    [{**asdict(f), **memory.state.get(f.id, {})} for f in memory.facts.values()], indent=1))
    except (BudgetExceeded, ProviderExhausted, JevUnavailable) as e:
        print(f"stopped: {e}. Rerun `stream` to continue; finished calls replay from cache for free.")
        return
    print(f"done: logical cost ${logical():.3f}, real spend ${budget.total:.3f}")
