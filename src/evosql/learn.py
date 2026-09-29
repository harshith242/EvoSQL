"""Discovery: one pass in which the proposer turns the docs agent's failures on the discovery set into typed facts.
Checked facts give two sets: single (all, merged) and verified (only bundles that fix their own question when re-answered).
discover_facts is pure so it can be tested without an LLM."""
from collections import Counter
from dataclasses import asdict
from itertools import count

from tqdm import tqdm

from evosql.agent import answer
from evosql.bird import exec_match, execute, gold_rows, quote
from evosql.budget import Budget, BudgetExceeded
from evosql.config import KNOWLEDGE
from evosql.delivery import AllFacts, NoKnowledge
from evosql.facts import Fact, FactBook, check_fact, leaks, merge
from evosql.files import append_jsonl, write_atomic
from evosql.labels import corrected, known_wrong
from evosql.llm import ProviderExhausted, extract_json, make_llm
from evosql.split import load_run

PROPOSER = """You build a knowledge base about ONE SQLite database so that a Text2SQL agent answers future, different questions correctly.
Below are questions the agent got wrong, with its SQL and the correct SQL. For each one, find what the agent did not KNOW about this database and state it as facts, one misconception per fact. Fact kinds (examples use a made-up shop database):
- mapping: what a phrase used in questions means in the data. Example: "shipped orders" means Orders.Status is 'S'; a status named in a question matches Orders.Status exactly, never as a substring.
- encoding: how values are stored. Example: unpaid Orders.Payment is stored as both 'none' and '0'.
- constraint: a range or business rule. Example: an abnormal Orders.Discount includes the boundary: at most 5 or at least 30, not strictly below or above.
- meaning: what a column represents. Example: Orders.Amt is the order total in cents.
- grain: what one row is and how to count entities. Example: one Orders row is one order line; a customer count needs distinct Orders.CustID.
- relation: a join path and its cardinality. Example: Customer 1:N Orders via Customer.ID and Orders.CustID.
Rules:
- Do not restate anything the column docs or the value profile already say (documented ranges, codes, meanings). Write only what they miss: conventions (how ages, dates and counts are computed), stored codes that differ from the documented symbols, what question phrases mean, row grain and join paths.
- State facts about the data, never the SQL fix. Do not write SQL keywords or clauses in a fact.
- A fact must help other questions too; never state this question's answer or copy its wording.
- Name columns as Table.Column and quote stored values in single quotes exactly as they appear in the data; write question phrases in double quotes.
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


PROPOSER_ONE = """You maintain a knowledge base about ONE SQLite database so that a Text2SQL agent answers future, different questions correctly.
Below is one question the agent got wrong, with its SQL and the correct SQL. Find the single most important thing the agent did not KNOW about this database and state it as ONE fact. Fact kinds (examples use a made-up shop database):
- mapping: what a phrase used in questions means in the data. Example: "shipped orders" means Orders.Status is 'S'; a status named in a question matches Orders.Status exactly, never as a substring.
- encoding: how values are stored. Example: unpaid Orders.Payment is stored as both 'none' and '0'.
- constraint: a range or business rule. Example: an abnormal Orders.Discount includes the boundary: at most 5 or at least 30, not strictly below or above.
- meaning: what a column represents. Example: Orders.Amt is the order total in cents.
- grain: what one row is and how to count entities. Example: one Orders row is one order line; a customer count needs distinct Orders.CustID.
- relation: a join path and its cardinality. Example: Customer 1:N Orders via Customer.ID and Orders.CustID.
Rules:
- Do not restate anything the column docs or the value profile already say (documented ranges, codes, meanings). Write only what they miss: conventions (how names, dates and counts are formed), stored codes that differ from what a question says, what question phrases mean, row grain and join paths.
- State a fact about the data, never the SQL fix. Do not write SQL keywords or clauses in the fact.
- The fact must help other questions too; never state this question's answer.
- Name columns as Table.Column. Under 40 words.
- applies_to: 1 to 5 short phrases a future question may use when the fact matters; you may reuse this question's wording (e.g. "full name", "shipped").
- values: every stored value the fact relies on, as {{"table": ..., "column": ..., "value": ...}} exactly as stored; [] if none.
- probe: one read-only SELECT whose result shows evidence for the fact (for a fact that something does not exist, a COUNT(*) query), or null.
- If the correct SQL needs nothing reusable (only this question's own literals), reply {{"fact": null}}.
Reply with only JSON: {{"kind": "mapping | encoding | constraint | meaning | grain | relation", "subject": "Table.Column or term", "fact": "...", "applies_to": ["..."], "values": [], "probe": "SELECT ... or null"}}

Database schema:
{ddl}

{profile}

Current knowledge:
{knowledge}

Failed question:
Question: {question}
Agent SQL: {agent_sql}
Correct SQL: {gold_sql}"""


def _fact_from(d, qids):
    """A Fact from one proposer JSON object, or None when required fields are missing; bad optional fields are cleaned."""
    if not (isinstance(d, dict) and all(isinstance(d.get(k), str) and d[k] for k in ("kind", "subject", "fact"))):
        return None
    phrases = d.get("applies_to") if isinstance(d.get("applies_to"), list) else []
    phrases = [p.strip() for p in phrases if isinstance(p, str) and p.strip()][:5]
    probe = d.get("probe") if isinstance(d.get("probe"), str) else ""
    probe = None if probe.strip().lower() in ("", "null", "none") else probe
    qid = next((i for i in qids if str(i) == str(d.get("qid"))), qids[0])  # a missing or odd qid falls back
    values = d.get("values") if isinstance(d.get("values"), list) else None
    if values is not None:
        values = [v for v in values if isinstance(v, dict) and {"table", "column", "value"} <= set(v)]
    return Fact("", d["kind"], d["subject"], d["fact"], phrases, probe, [qid], values)


def propose_one(llm, db, q, agent_sql, facts):
    """v6: exactly one fact (with structured values) for one failed question, or None."""
    knowledge = "\n".join(f"- [{f.kind}] {f.subject}: {f.fact}" for f in facts) or "(empty)"
    reply = llm.chat([{"role": "user", "content": PROPOSER_ONE.format(
        ddl=db.ddl, profile=db.profile, knowledge=knowledge, question=q.question, agent_sql=agent_sql or "(none)",
        gold_sql=q.gold_sql)}])
    fact = _fact_from(extract_json(reply["content"]), [q.qid])
    if fact is not None and fact.values is None:
        fact.values = []  # v6 facts always use structured values, never quoted-text grounding
    return fact


def leak_exempt(fact, db):
    """Lowercase structured values that may equal an answer: grounded in their column and stored in 2+ rows (codes)."""
    allowed = set()
    for v in fact.values or []:
        table, column, value = v.get("table"), v.get("column"), str(v.get("value"))
        if table in db.tables and column in db.columns[table]:
            literal = "'" + value.replace("'", "''") + "'"
            rows, _ = execute(db.path, f"SELECT COUNT(*) FROM {quote(table)} WHERE CAST({quote(column)} AS TEXT) = {literal}")
            if rows and rows[0][0] >= 2:
                allowed.add(value.strip().lower())
    return allowed


def propose_facts(llm, db, batch, facts):
    """batch: [(Question, agent_sql)]. Returns the proposed facts (id unset, source_qids = [qid])."""
    items = "\n\n".join(f"qid {q.qid}\nQuestion: {q.question}\nAgent SQL: {sql or '(none)'}\nCorrect SQL: {q.gold_sql}"
                        for q, sql in batch)
    knowledge = "\n".join(f"- [{f.kind}] {f.subject}: {f.fact}" for f in facts) or "(empty)"
    data = extract_json(llm.chat([{"role": "user", "content": PROPOSER.format(
        ddl=db.ddl, profile=db.profile, knowledge=knowledge, batch=items)}])["content"])
    qids = [q.qid for q, _ in batch]
    facts = [_fact_from(d, qids) for d in (data.get("facts") or [] if isinstance(data, dict) else [])]
    return [f for f in facts if f is not None]


def check(fact, batch, db, gold):
    """Free checks, then leakage in anything the agent sees, against every question in the batch (all their gold SQL was shown)."""
    reason = check_fact(fact, db)
    if reason:
        return reason
    allowed = leak_exempt(fact, db)
    for q in batch:
        # Trigger phrases may reuse the question's wording; only answer values count as leaks there.
        texts = [(fact.subject, True), (fact.fact, True)] + [(p, False) for p in fact.applies_to]
        for text, wording in texts:
            if leak := leaks(text, q.question, q.gold_sql, gold[q.qid], allowed=allowed, wording=wording):
                return f"leakage: {leak}"
    return None


def discover_facts(qs, db, gold, solve, propose, wrong_label, verify, batch_size, log):
    """solve(q) -> (correct, sql); propose([(q, sql)], facts) -> [Fact]; wrong_label(q) -> bool; verify(q, facts) -> bool.
    Returns (single, verified, conflicts): all checked facts merged, and only those whose source question they fix."""
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
    passed = set()
    for q in failures:
        bundle = [f for f in facts if f.source_qids == [q.qid]]
        if bundle:
            ok = verify(q, bundle)
            passed |= {q.qid} if ok else set()
            log({"event": "verify", "qid": q.qid, "facts": [f.id for f in bundle], "passed": ok})
    single, conflicts = merge(facts, db)
    verified = [f for f in single if set(f.source_qids) & passed]  # a subset of single, as the report assumes
    log({"event": "merge", "before": len(facts), "after": len(single), "conflicts": conflicts,
         "verified": len(verified)})
    return single, verified, conflicts


def describe(entry):
    """One progress line per discovery event."""
    if entry["event"] == "answers":
        return (f"docs right {entry['right']}; {len(entry['failures'])} failures to learn from, "
                f"{len(entry['known_wrong_labels'])} skipped as known-wrong labels")
    if entry["event"] == "batch":
        return f"batch {entry['batch']}: {len(entry['kept'])} facts kept, {len(entry['dropped'])} dropped"
    if entry["event"] == "verify":
        return f"verify q{entry['qid']}: {len(entry['facts'])} facts {'fix it' if entry['passed'] else 'do not fix it'}"
    return (f"merge: {entry['before']} -> {entry['after']} facts (single), {entry['verified']} verified, "
            f"{len(entry['conflicts'])} conflicts")


def discover(cfg):
    """Run discovery with the real LLMs and save one knowledge file per variant. False if stopped by budget or provider."""
    out, parts, db, by_id = load_run(cfg)
    qs = [by_id[i] for i in parts["discovery"]]
    budget = Budget(out / "spend.json", cfg["protocol"]["budget_usd"])
    agent = make_llm(cfg["agent"], cfg["cache_dir"], budget.spend)
    proposer = make_llm(cfg["proposer"], cfg["cache_dir"], budget.spend)
    gold = {q.qid: gold_rows(db.path, q) for q in qs}
    fixes = corrected(cfg["data_dir"], cfg["db"])
    log_path = out / "discover.jsonl"
    write_atomic(log_path, "")
    for name in KNOWLEDGE.values():  # never leave an older run's knowledge next to this log
        (out / name).unlink(missing_ok=True)
    bar = tqdm(desc="discover", unit="run", dynamic_ncols=True)

    def solve(q):
        sql, _ = answer(agent, db, q.question, NoKnowledge(), max_steps=cfg["max_steps"])
        bar.update(1)
        bar.set_postfix_str(f"spent ${budget.total:.3f}")
        return exec_match(db.path, sql, gold[q.qid]), sql

    def verify(q, facts):
        sql, _ = answer(agent, db, q.question, AllFacts(FactBook(facts)), max_steps=cfg["max_steps"])
        bar.update(1)
        return exec_match(db.path, sql, gold[q.qid])

    def log(entry):
        entry["usage"] = {"agent": dict(agent.usage), "proposer": dict(proposer.usage)}  # cumulative
        append_jsonl(log_path, entry)
        tqdm.write("  " + describe(entry))

    try:
        single, verified, _ = discover_facts(qs, db, gold, solve,
                                             lambda batch, known: propose_facts(proposer, db, batch, known),
                                             lambda q: known_wrong(db, q, fixes), verify, cfg["protocol"]["batch_size"], log)
    except (BudgetExceeded, ProviderExhausted) as e:
        print(f"stopped: {e}. To continue, raise protocol.budget_usd (or wait out the provider limit) and rerun "
              f"`discover`; finished calls replay from cache for free.")
        return False
    finally:
        bar.close()
    for variant, facts in (("single", single), ("verified", verified)):
        FactBook(facts).save(out / KNOWLEDGE[variant])
        print(f"{variant}: {len(facts)} facts {dict(Counter(f.kind for f in facts))}")
    print(f"done, spent ${budget.total:.3f} total")
    return True
