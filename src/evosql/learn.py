"""Learning phase: the proposer turns failed learning questions into typed facts; a candidate knowledge version
is kept only if it beats the current one on the whole learning set; the result is consolidated and frozen.
learn_loop is pure (injected solve/propose/check/consolidate) so it can be tested without an LLM."""
import json
from dataclasses import asdict

from tqdm import tqdm

from evosql.agent import answer
from evosql.bird import exec_match, gold_rows
from evosql.budget import Budget, BudgetExceeded
from evosql.facts import Fact, FactBook, check_fact, leaks
from evosql.files import append_jsonl, write_atomic
from evosql.llm import ProviderExhausted, extract_json, make_llm
from evosql.split import load_run


def neutral_fact(db):
    """A true but useless fact about this database: its effect on answers measures prompt-perturbation noise."""
    table = db.tables[0]
    column = db.columns[table][0]
    return {"op": "add", "kind": "meaning", "subject": f"{table}.{column}", "qid": None,
            "fact": f"{table}.{column} is one of the columns of the {table} table."}


PROPOSER = """You build a knowledge base about ONE SQLite database so that a Text2SQL agent answers future, different questions correctly.
Below are questions the agent got wrong, with its SQL and the correct SQL. For each one, find what the agent did not KNOW about this database and state it as facts. Fact kinds (examples use a made-up shop database):
- mapping: what a phrase used in questions means in the data. Example: "shipped orders" means Orders.Status is 'S'.
- constraint: a range or business rule. Example: a normal Orders.Discount is at most 30.
- encoding: how values are stored. Example: unpaid Orders.Payment is stored as both 'none' and '0'.
- meaning: what a column represents. Example: Orders.Amt is the order total in cents.
Rules:
- State facts about the data, never the SQL fix. Do not write SQL keywords or clauses.
- A fact must help other questions too; never state this question's answer or copy its wording.
- Name columns as Table.Column and quote stored values in single quotes exactly as they appear in the data.
- One fact per edit, under 40 words.
- If the correct SQL looks like an annotation error rather than knowledge (for example AND/OR precedence without parentheses, or counting duplicated joined rows when the question asks how many distinct entities), return a skip with the reason instead of facts.
- You may modify or delete an existing fact by its id if it is wrong.
Reply with only JSON: {{"items": [{{"qid": 1, "skip": "reason"}}, {{"qid": 2, "edits": [{{"op": "add" | "modify" | "delete", "id": "fact id, for modify/delete", "kind": "mapping | constraint | encoding | meaning", "subject": "Table.Column or term", "fact": "..."}}]}}]}}

Database schema:
{ddl}

{profile}

Current knowledge:
{knowledge}

Failed questions:
{batch}"""

CONSOLIDATE = """Rewrite this knowledge base about ONE SQLite database: merge duplicate facts, remove contradictions (keep the version the data profile supports), one fact per item, same kinds and rules (no SQL, columns as Table.Column, stored values in single quotes). Do not add new information.
Reply with only JSON: {{"facts": [{{"kind": "...", "subject": "...", "fact": "...", "source_qids": [1, 2]}}]}}

Database schema:
{ddl}

{profile}

Current knowledge (JSON):
{facts}"""


def _complete(d):
    return isinstance(d, dict) and all(isinstance(d.get(k), str) and d[k] for k in ("kind", "subject", "fact"))


def propose_facts(llm, db, book, batch):
    """batch: list of (Question, agent_sql). Returns (edits with qid, skips as (qid, reason))."""
    items = "\n\n".join(f"qid {q.qid}\nQuestion: {q.question}\nAgent SQL: {sql or '(none)'}\nCorrect SQL: {q.gold_sql}"
                        for q, sql in batch)
    knowledge = "\n".join(f"{f.id} [{f.kind}] {f.subject}: {f.fact}" for f in book.facts) or "(empty)"
    data = extract_json(llm.chat([{"role": "user", "content": PROPOSER.format(
        ddl=db.ddl, profile=db.profile, knowledge=knowledge, batch=items)}])["content"])
    edits, skips = [], []
    for item in (data or {}).get("items", []):
        if not isinstance(item, dict):
            continue
        if item.get("skip"):
            skips.append((item.get("qid"), str(item["skip"])))
        for e in item.get("edits") or []:
            if isinstance(e, dict) and (e.get("op") == "delete" or e.get("op") in ("add", "modify") and _complete(e)):
                edits.append({**e, "qid": item.get("qid")})
    return edits, skips


def consolidate(llm, db, book):
    facts = json.dumps([{k: v for k, v in asdict(f).items() if k != "id"} for f in book.facts], indent=1)
    reply = llm.chat([{"role": "user", "content": CONSOLIDATE.format(ddl=db.ddl, profile=db.profile, facts=facts)}])
    new = FactBook()
    for f in (extract_json(reply["content"]) or {}).get("facts", []):
        if _complete(f) and check_fact(Fact("new", f["kind"], f["subject"], f["fact"]), db) is None:
            new.add(f["kind"], f["subject"], f["fact"], list(f.get("source_qids") or []))
    return new


def learn_loop(learn_qs, solve, propose, check, consolidate, epochs, batch_size, min_gain, log, neutral):
    """Gated, versioned learning. solve(q, book) -> (correct, sql); propose([(q, sql)], book) -> (edits, skips);
    check(edit, batch) -> reason | None. Returns (knowledge, ungated knowledge, calibration flips)."""
    def score(book, qs=learn_qs):
        return {q.qid: solve(q, book) for q in qs}

    def right(scores):
        return sum(ok for ok, _ in scores.values())

    k, version = FactBook(), 0
    scores = score(k)
    noisy = score(k.apply([neutral]))
    flips = sum(scores[q][0] != noisy[q][0] for q in scores)
    threshold = max(min_gain, flips)
    log({"event": "calibration", "flips": flips, "threshold": threshold, "right": right(scores)})

    ungated, seen = FactBook(), set()
    for epoch in range(1, epochs + 1):
        failures = [q for q in learn_qs if not scores[q.qid][0]]
        for i in range(0, len(failures), batch_size):
            batch = [q for q in failures[i:i + batch_size] if not scores[q.qid][0]]
            if not batch:
                continue
            edits, skips = propose([(q, scores[q.qid][1]) for q in batch], k)
            kept, dropped = [], []
            for e in edits:
                reason = None if e["op"] == "delete" else check(e, batch)
                if reason:
                    dropped.append({**e, "reason": reason})
                else:
                    kept.append(e)
            # Ungated keeps every checked fact text once (the proposer may repeat itself across batches and epochs).
            new = [e for e in kept if e["op"] != "delete" and (e["subject"], e["fact"]) not in seen]
            seen |= {(e["subject"], e["fact"]) for e in new}
            ungated = ungated.apply([{**e, "op": "add"} for e in new])
            entry = {"event": "batch", "epoch": epoch, "batch": [q.qid for q in batch], "kept": kept,
                     "dropped": dropped, "skips": skips}
            if not kept:
                log({**entry, "decision": "no valid facts"})
                continue
            candidate = k.apply(kept)
            # Score the batch first: a candidate that fixes none of it is rejected without scoring the rest.
            cand_scores = score(candidate, batch)
            fixed = [qid for qid, (ok, _) in cand_scores.items() if ok]
            if not fixed:
                log({**entry, "fixed": [], "decision": f"rejected (fixed 0 of {len(batch)})"})
                continue
            cand_scores |= score(candidate, [q for q in learn_qs if q.qid not in cand_scores])
            net = right(cand_scores) - right(scores)
            accepted = net >= threshold
            version += accepted
            log({**entry, "net_gain": net, "fixed": fixed, "right": right(cand_scores), "version": version,
                 "decision": "accepted" if accepted else f"rejected (net {net}, need {threshold})",
                 "facts": [asdict(f) for f in candidate.facts] if accepted else None})
            if accepted:
                k, scores = candidate, cand_scores
    return _consolidate(k, scores, consolidate, score, right, log), ungated, flips


def _consolidate(k, scores, consolidate, score, right, log):
    """Keep the consolidated knowledge only if the learning score does not drop."""
    if len(k.facts) < 2:
        return k
    merged = consolidate(k)
    merged_scores = score(merged)
    keep = right(merged_scores) >= right(scores)
    log({"event": "consolidation", "before": right(scores), "after": right(merged_scores),
         "facts_before": len(k.facts), "facts_after": len(merged.facts), "kept": keep})
    return merged if keep else k


def describe(entry):
    """One progress line per learning event."""
    if entry["event"] == "calibration":
        return f"calibration: {entry['flips']} flips, threshold {entry['threshold']}, {entry['right']} right"
    if entry["event"] == "consolidation":
        return (f"consolidation: {entry['facts_before']} -> {entry['facts_after']} facts, "
                f"right {entry['before']} -> {entry['after']}, kept={entry['kept']}")
    return (f"epoch {entry['epoch']} batch {entry['batch']}: {len(entry['kept'])} facts, {len(entry['dropped'])} dropped, "
            f"{len(entry['skips'])} skipped -> {entry['decision']}")


def run_learn(cfg):
    """Run the learning phase with the real LLMs. Returns False if stopped by budget or provider limits."""
    out, split, db, by_id = load_run(cfg)
    learn_qs = [by_id[i] for i in split["learn"]]
    budget = Budget(out / "spend.json", cfg["protocol"]["budget_usd"])
    agent = make_llm(cfg["agent"], cfg["cache_dir"], budget.spend)
    proposer = make_llm(cfg["proposer"], cfg["cache_dir"], budget.spend)
    gold = {q.qid: gold_rows(db.path, q) for q in learn_qs}
    bar = tqdm(desc="learn", unit="run", dynamic_ncols=True)

    def solve(q, book):
        sql = answer(agent, db, q.question, book, max_steps=cfg["max_steps"])
        bar.update(1)
        bar.set_postfix_str(f"spent ${budget.total:.3f}")
        return exec_match(db.path, sql, gold[q.qid]), sql

    def check(edit, batch):
        # Leakage is checked against every question in the batch: the proposer saw all of their gold SQL.
        reason = check_fact(Fact("new", edit["kind"], edit["subject"], edit["fact"]), db)
        leak = next((r for q in batch if (r := leaks(edit["fact"], q.question, q.gold_sql, gold[q.qid]))), None)
        return reason or (f"leakage: {leak}" if leak else None)

    log_path = out / "learn.jsonl"
    write_atomic(log_path, "")

    def log(entry):
        entry["usage"] = {"agent": dict(agent.usage), "proposer": dict(proposer.usage)}  # cumulative
        append_jsonl(log_path, entry)
        tqdm.write("  " + describe(entry))

    p = cfg["protocol"]
    try:
        k, ungated, flips = learn_loop(learn_qs, solve, lambda batch, book: propose_facts(proposer, db, book, batch),
                                       check, lambda book: consolidate(proposer, db, book),
                                       p["epochs"], p["batch_size"], p["min_gain"], log, neutral_fact(db))
    except (BudgetExceeded, ProviderExhausted) as e:
        print(f"stopped: {e}. Rerun `learn` later; finished calls replay from cache.")
        return False
    finally:
        bar.close()
    k.save(out / "knowledge_final.json")
    ungated.save(out / "ungated.json")
    print(f"done: {len(k.facts)} facts kept, {len(ungated.facts)} ungated, spent ${budget.total:.3f} total")
    return True
