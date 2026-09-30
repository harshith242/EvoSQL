"""The v7 stream: for each order and database, the none and facts arms answer each question, then the memory learns
from the correct SQL (test, then train). Answers are memoised by prompt within a run and every LLM reply is cached on
disk, so the none arm is shared by both orders and a rerun replays finished work for free and identically."""
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


def usage_since(llm, before):
    return {k: llm.usage[k] - before.get(k, 0) for k in llm.usage}


def add_usage(a, b):
    return {k: a.get(k, 0) + b.get(k, 0) for k in {*a, *b}}


class Answers:
    """Answers memoised by (question, knowledge text); a replay reports no new usage but keeps its API latency."""

    def __init__(self, agent, max_steps):
        self.agent, self.max_steps, self.memo = agent, max_steps, {}

    def get(self, db, q, gold, facts):
        notes = render(facts)
        key = (q.db_id, q.qid, notes)
        if key in self.memo:
            return {**self.memo[key], "usage": {}}
        before = dict(self.agent.usage)
        sql, turns = answer(self.agent, db, q.question, notes, self.max_steps)
        usage = usage_since(self.agent, before)
        self.memo[key] = {"sql": sql, "turns": turns, "ok": exec_match(db.path, sql, gold),
                          "latency_s": usage.get("latency_s", 0.0)}
        return {**self.memo[key], "usage": usage}


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

    def try_fact(f, eq):
        result = answers.get(db, eq, gold_rows(db.path, eq), [f])
        usage["precheck"] = add_usage(usage["precheck"], result["usage"])
        return result["ok"]

    record = memory.admit(fact, try_fact if precheck else None)
    return {**record, "fact": asdict(fact), "snippet": snippet, "usage": usage}


def run_stream(db, order, answers, proposer, memory, can_precheck, log_path, bar=None):
    """One (database, order) stream, one log record per question."""
    write_atomic(log_path, "")
    for pos, q in enumerate(order, 1):
        gold = gold_rows(db.path, q)

        # Both arms answer before anything about q is revealed; with no fact injected, facts replays none.
        none = answers.get(db, q, gold, [])
        picked, _ = memory.select(q.question)
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
            "learning": learning,
        })
        if bar:
            bar.update(1)


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
                    run_stream(db, order, answers, proposer, memory, can_precheck, stream_log(out, seed, db_id), bar)
                write_atomic(facts_file(out, seed, db_id), json.dumps(
                    [{**asdict(f), **memory.state.get(f.id, {})} for f in memory.facts.values()], indent=1))
    except (BudgetExceeded, ProviderExhausted, JevUnavailable) as e:
        print(f"stopped: {e}. Rerun `stream` to continue; finished calls replay from cache for free.")
        return
    print(f"done: logical cost ${logical():.3f}, real spend ${budget.total:.3f}")
