"""v6 stream: for each order and database, the none and facts arms answer each question, then the memory learns from
the correct SQL (test, then train). Every LLM reply and embedding is cached and the stream is deterministic, so
rerunning replays finished work for free; the none arm is shared by both orders through the same cache."""
import json
import random
from dataclasses import asdict
from pathlib import Path

from tqdm import tqdm

from evosql.agent import answer
from evosql.bird import exec_match, gold_rows, load_arcwise, open_db
from evosql.budget import Budget, BudgetExceeded
from evosql.delivery import AllFacts, NoKnowledge
from evosql.facts import FactBook
from evosql.files import append_jsonl, write_atomic
from evosql.learn import check, propose_one
from evosql.llm import ProviderExhausted, make_llm
from evosql.memory import FactMemory
from evosql.search import Embedder

GOLD_CACHE = "cache/gold_arcwise"  # Arcwise gold differs from BIRD's for the same question ids


def _usage_delta(llm, before):
    return {k: llm.usage[k] - before.get(k, 0) for k in llm.usage}


def run_stream(db, questions, seed, agent, proposer, memory, budget, precheck_limit, max_steps, log_path, bar=None):
    """One (database, order) stream. Writes one record per question to log_path; returns the memory."""
    order = sorted(questions, key=lambda q: q.qid)
    random.Random(seed).shuffle(order)
    gold = lambda q: gold_rows(db.path, q, cache_dir=GOLD_CACHE)
    ask = lambda q, knowledge: answer(agent, db, q.question, knowledge, max_steps=max_steps)
    write_atomic(log_path, "")
    earlier = []  # (question, none_ok) in stream order: revealed questions only
    for pos, q in enumerate(order, 1):
        history = [e.question for e, _ in earlier]
        before = dict(agent.usage)
        none_sql, none_turns = ask(q, NoKnowledge())
        none_usage, before = _usage_delta(agent, before), dict(agent.usage)
        picked = memory.select(q.question, history)
        facts_sql, facts_turns = ask(q, AllFacts(FactBook(picked)))
        facts_usage = _usage_delta(agent, before)
        none_ok, facts_ok = exec_match(db.path, none_sql, gold(q)), exec_match(db.path, facts_sql, gold(q))
        # Reveal the correct SQL: credit the injected facts, then learn from a failure of the facts arm.
        memory.credit([f.id for f in picked], facts_ok, none_ok)
        learning = None
        if not facts_ok:
            before_p, before_a = dict(proposer.usage), dict(agent.usage)
            fact = propose_one(proposer, db, q, facts_sql, memory.active())
            reason = "no reusable fact proposed" if fact is None else check(fact, [q], db, {q.qid: gold(q)})
            if reason:
                learning = {"outcome": "dropped", "reason": reason, "fact": fact and asdict(fact)}
            elif budget.total > precheck_limit:
                memory.add(fact, 0)
                learning = {"outcome": "added unproven (pre-check skipped: order budget)", "fact": asdict(fact)}
            else:
                with_fact = lambda f, eq: exec_match(db.path, ask(eq, AllFacts(FactBook([f])))[0], gold(eq))
                result, fixes, checked = memory.precheck(fact, earlier, with_fact)
                if result != "rejected":
                    memory.add(fact, fixes)
                learning = {"outcome": f"pre-check {result}", "fixes": fixes, "checked": checked, "fact": asdict(fact)}
            learning["usage"] = {"proposer": _usage_delta(proposer, before_p), "precheck": _usage_delta(agent, before_a)}
        append_jsonl(log_path, {"pos": pos, "qid": q.qid, "none_ok": none_ok, "facts_ok": facts_ok,
                                "none_sql": none_sql, "facts_sql": facts_sql, "turns": [none_turns, facts_turns],
                                "injected": [f.id for f in picked], "usage": {"none": none_usage, "facts": facts_usage},
                                "learning": learning})
        earlier.append((q, none_ok))
        if bar:
            bar.update(1)
            bar.set_postfix_str(f"spent ${budget.total:.3f}")
    return memory


def run(cfg):
    """All streams, order by order. Returns False if stopped by the budget or the provider."""
    v6, out = cfg["v6"], Path(cfg["runs_dir"])
    questions = load_arcwise(v6["questions"], set(v6["databases"]))
    budget = Budget(out / "spend.json", cfg["protocol"]["budget_usd"])
    agent = make_llm(cfg["agent"], cfg["cache_dir"], budget.spend)
    proposer = make_llm(cfg["proposer"], cfg["cache_dir"], budget.spend)
    embed = Embedder(cfg["search"]["embed_model"], cfg["search"]["embed_url"])
    try:
        for seed, order_budget in zip(v6["seeds"], v6["order_budget_usd"]):
            for db_id in v6["databases"]:
                db = open_db(cfg["data_dir"], db_id, with_profile=True, with_column_docs=True,
                             docs_dir=Path(v6["docs_root"]) / db_id / "database_description")
                qs = [q for q in questions if q.db_id == db_id]
                memory = FactMemory(db, embed, v6["rules"])
                with tqdm(total=len(qs), desc=f"order {seed} {db_id}", unit="q", dynamic_ncols=True) as bar:
                    run_stream(db, qs, seed, agent, proposer, memory, budget, order_budget - v6["precheck_reserve_usd"],
                               cfg["max_steps"], out / f"stream_s{seed}_{db_id}.jsonl", bar)
                write_atomic(out / f"facts_s{seed}_{db_id}.json", json.dumps(
                    [{**asdict(f), **memory.state.get(f.id, {})} for f in memory.facts], indent=1))
    except (BudgetExceeded, ProviderExhausted) as e:
        print(f"stopped: {e}. Rerun `stream` to continue; finished calls replay from cache for free.")
        return False
    print(f"done, spent ${budget.total:.3f} total")
    return True
