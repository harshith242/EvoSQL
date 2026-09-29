"""Discovery: one pass in which the proposer turns the docs agent's failures on the discovery set into typed facts.
Facts that fail the free checks or leak an answer are dropped with the reason logged; the rest are merged.
No gate, no noise calibration, no LLM consolidation. discover_facts is pure so it can be tested without an LLM."""
from collections import Counter
from dataclasses import asdict
from itertools import count

from tqdm import tqdm

from evosql.agent import answer
from evosql.bird import exec_match, gold_rows
from evosql.budget import Budget, BudgetExceeded
from evosql.delivery import NoKnowledge
from evosql.facts import Fact, FactBook, check_fact, leaks, merge
from evosql.files import append_jsonl, write_atomic
from evosql.labels import corrected, known_wrong
from evosql.llm import ProviderExhausted, extract_json, make_llm
from evosql.split import load_run

PROPOSER = """You build a knowledge base about ONE SQLite database so that a Text2SQL agent answers future, different questions correctly.
Below are questions the agent got wrong, with its SQL and the correct SQL. For each one, find what the agent did not KNOW about this database and state it as facts, one misconception per fact. Fact kinds (examples use a made-up shop database):
- mapping: what a phrase used in questions means in the data. Example: "shipped orders" means Orders.Status is 'S'.
- encoding: how values are stored. Example: unpaid Orders.Payment is stored as both 'none' and '0'.
- constraint: a range or business rule. Example: a normal Orders.Discount is at most 30.
- meaning: what a column represents. Example: Orders.Amt is the order total in cents.
- grain: what one row is and how to count entities. Example: one Orders row is one order line; a customer count needs distinct Orders.CustID.
- relation: a join path and its cardinality. Example: Customer 1:N Orders via Customer.ID and Orders.CustID.
Rules:
- State facts about the data, never the SQL fix. Do not write SQL keywords or clauses in a fact.
- A fact must help other questions too; never state this question's answer or copy its wording.
- Name columns as Table.Column and quote stored values in single quotes exactly as they appear in the data.
- Each fact under 40 words, with applies_to: 1 to 5 short phrases a future question may use when the fact matters (e.g. "shipped", "shipping status").
- probe: one read-only SELECT on this database whose rows show evidence for the fact (e.g. rows with the stored values it names), or null.
- Do not repeat a fact that is already in the current knowledge.
Reply with only JSON: {{"facts": [{{"qid": 1, "kind": "mapping | encoding | constraint | meaning | grain | relation", "subject": "Table.Column or term", "fact": "...", "applies_to": ["..."], "probe": "SELECT ... or null"}}]}}

Database schema:
{ddl}

{profile}

Current knowledge:
{knowledge}

Failed questions:
{batch}"""


def propose_facts(llm, db, batch, facts):
    """batch: [(Question, agent_sql)]. Returns the proposed facts (id unset, source_qids = [qid])."""
    items = "\n\n".join(f"qid {q.qid}\nQuestion: {q.question}\nAgent SQL: {sql or '(none)'}\nCorrect SQL: {q.gold_sql}"
                        for q, sql in batch)
    knowledge = "\n".join(f"- [{f.kind}] {f.subject}: {f.fact}" for f in facts) or "(empty)"
    data = extract_json(llm.chat([{"role": "user", "content": PROPOSER.format(
        ddl=db.ddl, profile=db.profile, knowledge=knowledge, batch=items)}])["content"])
    out = []
    for d in data.get("facts") or [] if isinstance(data, dict) else []:
        if not (isinstance(d, dict) and all(isinstance(d.get(k), str) and d[k] for k in ("kind", "subject", "fact"))):
            continue
        phrases = [p for p in d.get("applies_to") or [] if isinstance(p, str)][:5]
        probe = d["probe"] if isinstance(d.get("probe"), str) and d["probe"].strip().lower() != "null" else None
        out.append(Fact("", d["kind"], d["subject"], d["fact"], phrases, probe, [d.get("qid")]))
    return out


def check(fact, batch, db, gold):
    """Free checks, then leakage against every question in the batch (the proposer saw all of their gold SQL)."""
    reason = check_fact(fact, db)
    if reason:
        return reason
    for q in batch:
        for text in [fact.fact, *fact.applies_to]:
            if leak := leaks(text, q.question, q.gold_sql, gold[q.qid]):
                return f"leakage: {leak}"
    return None


def discover_facts(qs, db, gold, solve, propose, wrong_label, batch_size, log):
    """solve(q) -> (correct, sql); propose([(q, sql)], facts) -> [Fact]; wrong_label(q) -> bool.
    Returns (merged facts, merge conflicts)."""
    answers = {q.qid: solve(q) for q in qs}
    failed = [q for q in qs if not answers[q.qid][0]]
    excluded = [q.qid for q in failed if wrong_label(q)]
    failures = [q for q in failed if q.qid not in excluded]
    log({"event": "answers", "right": len(qs) - len(failed), "failures": [q.qid for q in failures],
         "known_wrong_labels": excluded})
    facts, ids = [], count(1)
    for i in range(0, len(failures), batch_size):
        batch = failures[i:i + batch_size]
        kept, dropped = [], []
        for f in propose([(q, answers[q.qid][1]) for q in batch], facts):
            f.id = f"f{next(ids)}"
            reason = check(f, batch, db, gold)
            if reason:
                dropped.append({**asdict(f), "reason": reason})
            else:
                kept.append(f)
        facts += kept
        log({"event": "batch", "batch": [q.qid for q in batch], "kept": [asdict(f) for f in kept], "dropped": dropped})
    merged, conflicts = merge(facts, db)
    log({"event": "merge", "before": len(facts), "after": len(merged), "conflicts": conflicts})
    return merged, conflicts


def describe(entry):
    """One progress line per discovery event."""
    if entry["event"] == "answers":
        return (f"docs right {entry['right']}; {len(entry['failures'])} failures to learn from, "
                f"{len(entry['known_wrong_labels'])} skipped as known-wrong labels")
    if entry["event"] == "batch":
        return f"batch {entry['batch']}: {len(entry['kept'])} facts kept, {len(entry['dropped'])} dropped"
    return f"merge: {entry['before']} -> {entry['after']} facts, {len(entry['conflicts'])} conflicts"


def discover(cfg):
    """Run discovery with the real LLMs and save runs/knowledge.json. Returns False if stopped by budget or provider."""
    out, parts, db, by_id = load_run(cfg)
    qs = [by_id[i] for i in parts["discovery"]]
    budget = Budget(out / "spend.json", cfg["protocol"]["budget_usd"])
    agent = make_llm(cfg["agent"], cfg["cache_dir"], budget.spend)
    proposer = make_llm(cfg["proposer"], cfg["cache_dir"], budget.spend)
    gold = {q.qid: gold_rows(db.path, q) for q in qs}
    fixes = corrected(cfg["data_dir"], cfg["db"])
    log_path = out / "discover.jsonl"
    write_atomic(log_path, "")
    (out / "knowledge.json").unlink(missing_ok=True)  # never leave an older run's knowledge next to this log
    bar = tqdm(total=len(qs), desc="discover", unit="q", dynamic_ncols=True)

    def solve(q):
        sql, _ = answer(agent, db, q.question, NoKnowledge(), max_steps=cfg["max_steps"])
        bar.update(1)
        bar.set_postfix_str(f"spent ${budget.total:.3f}")
        return exec_match(db.path, sql, gold[q.qid]), sql

    def log(entry):
        entry["usage"] = {"agent": dict(agent.usage), "proposer": dict(proposer.usage)}  # cumulative
        append_jsonl(log_path, entry)
        tqdm.write("  " + describe(entry))

    try:
        facts, _ = discover_facts(qs, db, gold, solve, lambda batch, known: propose_facts(proposer, db, batch, known),
                                  lambda q: known_wrong(db, q, fixes), cfg["protocol"]["batch_size"], log)
    except (BudgetExceeded, ProviderExhausted) as e:
        print(f"stopped: {e}. To continue, raise protocol.budget_usd (or wait out the provider limit) and rerun "
              f"`discover`; finished calls replay from cache for free.")
        return False
    finally:
        bar.close()
    FactBook(facts).save(out / "knowledge.json")
    print(f"done: {len(facts)} facts {dict(Counter(f.kind for f in facts))}, spent ${budget.total:.3f} total")
    return True
