"""v3 learning phase: the proposer turns failed learning questions into typed facts; a candidate knowledge version
is kept only if it beats the current one on the whole learning set; the result is consolidated and frozen.
learn_loop is pure (injected solve/propose/check/consolidate) so it can be tested without an LLM."""
import json
import re
from dataclasses import asdict
from pathlib import Path

from tqdm import tqdm

from evosql.agent import answer
from evosql.bird import exec_match, gold_rows, load_questions, open_db
from evosql.budget import Budget, BudgetExceeded
from evosql.facts import Fact, FactBook, check_fact, columns
from evosql.llm import ProviderExhausted, make_llm
from evosql.split import load_split



def neutral_fact(db):
    """A true but useless fact about this database: its effect on answers measures prompt-perturbation noise."""
    table = db.tables[0]
    column = columns(db, table)[0]
    return {"op": "add", "kind": "meaning", "subject": f"{table}.{column}", "qid": None,
            "fact": f"{table}.{column} is one of the columns of the {table} table."}

PROPOSER_V3 = """You build a knowledge base about ONE SQLite database so that a Text2SQL agent answers future, different questions correctly.
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

CONSOLIDATE_V3 = """Rewrite this knowledge base about ONE SQLite database: merge duplicate facts, remove contradictions (keep the version the data profile supports), one fact per item, same kinds and rules (no SQL, columns as Table.Column, stored values in single quotes). Do not add new information.
Reply with only JSON: {{"facts": [{{"kind": "...", "subject": "...", "fact": "...", "source_qids": [1, 2]}}]}}

Database schema:
{ddl}

{profile}

Current knowledge (JSON):
{facts}"""


def _json(reply):
    match = re.search(r"\{.*\}", reply["content"] or "", re.DOTALL)
    try:
        return json.loads(match.group(0)) if match else None
    except json.JSONDecodeError:
        return None


def propose_facts(llm, db, book, batch):
    """batch: list of (Question, agent_sql). Returns (edits with qid, skips as (qid, reason))."""
    items = "\n\n".join(f"qid {q.qid}\nQuestion: {q.question}\nAgent SQL: {sql or '(none)'}\nCorrect SQL: {q.gold_sql}"
                        for q, sql in batch)
    knowledge = "\n".join(f"{f.id} [{f.kind}] {f.subject}: {f.fact}" for f in book.facts) or "(empty)"
    data = _json(llm.chat([{"role": "user", "content": PROPOSER_V3.format(
        ddl=db.ddl, profile=db.profile, knowledge=knowledge, batch=items)}]))
    edits, skips = [], []
    for item in (data or {}).get("items", []):
        if not isinstance(item, dict):
            continue
        if item.get("skip"):
            skips.append((item.get("qid"), str(item["skip"])))
        for e in item.get("edits") or []:
            ok = isinstance(e, dict) and e.get("op") in ("add", "modify", "delete")
            if ok and (e["op"] == "delete" or all(isinstance(e.get(k), str) and e[k] for k in ("kind", "subject", "fact"))):
                edits.append({**e, "qid": item.get("qid")})
    return edits, skips


def consolidate(llm, db, book):
    facts = json.dumps([{k: v for k, v in asdict(f).items() if k != "id"} for f in book.facts], indent=1)
    data = _json(llm.chat([{"role": "user", "content": CONSOLIDATE_V3.format(ddl=db.ddl, profile=db.profile, facts=facts)}]))
    new = FactBook()
    for f in (data or {}).get("facts", []):
        if isinstance(f, dict) and all(isinstance(f.get(k), str) and f[k] for k in ("kind", "subject", "fact")):
            fact = Fact(f"f{new.next_id}", f["kind"], f["subject"], f["fact"], list(f.get("source_qids") or []))
            if check_fact(fact, db) is None:
                new.facts.append(fact)
                new.next_id += 1
    return new


def learn_loop(learn_qs, solve, propose, check, consolidate, epochs, batch_size, min_gain, log, neutral):
    """Gated, versioned learning; check(edit, batch) -> reason | None. Returns (knowledge, ungated, calibration flips)."""
    score = lambda book: {q.qid: solve(q, book) for q in learn_qs}
    right = lambda scores: sum(scores.values())
    k, version = FactBook(), 0
    scores = score(k)
    neutral = score(k.apply([neutral]))
    flips = sum(scores[q] != neutral[q] for q in scores)
    threshold = max(min_gain, flips)
    log({"event": "calibration", "flips": flips, "threshold": threshold, "right": right(scores)})

    ungated = FactBook()
    for epoch in range(1, epochs + 1):
        failures = [q for q in learn_qs if not scores[q.qid]]
        for i in range(0, len(failures), batch_size):
            batch = [q for q in failures[i:i + batch_size] if not scores[q.qid]]
            if not batch:
                continue
            edits, skips = propose(batch, k)
            kept, dropped = [], []
            for e in edits:
                reason = None if e["op"] == "delete" else check(e, batch)
                (dropped if reason else kept).append({**e, "reason": reason} if reason else e)
            # Ungated keeps every checked fact text once (the proposer may repeat itself across batches and epochs).
            for e in kept:
                if e["op"] != "delete" and (e["subject"], e["fact"]) not in {(f.subject, f.fact) for f in ungated.facts}:
                    ungated = ungated.apply([{**e, "op": "add"}])
            entry = {"event": "batch", "epoch": epoch, "batch": [q.qid for q in batch], "kept": kept,
                     "dropped": dropped, "skips": skips}
            if not kept:
                log({**entry, "decision": "no valid facts"})
                continue
            candidate = k.apply(kept)
            cand_scores = score(candidate)
            net = right(cand_scores) - right(scores)
            fixed = [q.qid for q in batch if cand_scores[q.qid]]
            accepted = net >= threshold and bool(fixed)
            if accepted:
                version += 1
            log({**entry, "net_gain": net, "fixed": fixed, "right": right(cand_scores), "version": version,
                 "decision": "accepted" if accepted else f"rejected (net {net}, need {threshold}, fixed {len(fixed)})",
                 "facts": [asdict(f) for f in candidate.facts] if accepted else None,
                 "next_id": candidate.next_id})
            if accepted:
                k, scores = candidate, cand_scores

    if len(k.facts) > 1:
        merged = consolidate(k)
        merged_scores = score(merged)
        keep = right(merged_scores) >= right(scores)
        log({"event": "consolidation", "before": right(scores), "after": right(merged_scores),
             "facts_before": len(k.facts), "facts_after": len(merged.facts), "kept": keep})
        if keep:
            k = merged
    return k, ungated, flips


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
    v3, out = cfg["v3"], Path(cfg["runs_dir"])
    split = load_split(out / "split.json")
    db = open_db(cfg["data_dir"], cfg["db"], with_docs=True, with_profile=cfg["agent"].get("value_profile", False))
    by_id = {q.qid: q for q in load_questions(cfg["data_dir"], cfg["db"])}
    learn_qs = [by_id[i] for i in split["learn"]]
    agent, proposer = make_llm(cfg["agent"], cfg["cache_dir"]), make_llm(cfg["proposer"], cfg["cache_dir"])
    billed = [(agent, cfg["agent"].get("usd_per_million")), (proposer, cfg["proposer"].get("usd_per_million"))]
    budget = Budget(out / "spend.json", v3["budget_usd"])
    bar = tqdm(desc="learn", unit="run", dynamic_ncols=True)

    sql_memo = {}  # (qid, rendered knowledge) -> SQL, so re-reading an answer does not count its cost twice

    def run(q, book):
        key = (q.qid, book.render())
        if key not in sql_memo:
            try:
                sql_memo[key] = answer(agent, db, q.question, book, max_steps=cfg["max_steps"]).sql
            finally:
                budget.charge(billed)
            bar.update(1)
            bar.set_postfix_str(f"spent ${budget.total:.3f}")
        return sql_memo[key]

    def solve(q, book):
        return exec_match(db.path, run(q, book), gold_rows(db.path, q))

    def propose(batch, book):
        # The agent's SQL under the current knowledge is a cache hit from scoring it.
        sqls = [(q, run(q, book)) for q in batch]
        try:
            return propose_facts(proposer, db, book, sqls)
        finally:
            budget.charge(billed)

    def check(edit, batch):
        # Leakage is checked against every question in the batch: the proposer saw all of their gold SQL.
        fact = Fact("new", edit["kind"], edit["subject"], edit["fact"])
        reasons = [check_fact(fact, db, q.question, q.gold_sql, gold_rows(db.path, q)) for q in batch]
        return next((r for r in reasons if r), None)

    log_path = out / "learn.jsonl"
    log_path.write_text("")

    def log(entry):
        entry["usage"] = {"agent": dict(agent.usage), "proposer": dict(proposer.usage)}
        with open(log_path, "a") as f:
            f.write(json.dumps(entry) + "\n")
        if entry.get("decision", "").startswith("accepted"):
            FactBook([Fact(**f) for f in entry["facts"]], entry["next_id"]).save(out / f"knowledge_v{entry['version']}.json")
        tqdm.write("  " + describe(entry))

    try:
        k, ungated, flips = learn_loop(learn_qs, solve, propose, check, lambda b: consolidate(proposer, db, b),
                                       v3["epochs"], v3["batch_size"], v3["min_gain"], log, neutral_fact(db))
    except (BudgetExceeded, ProviderExhausted) as e:
        bar.close()
        print(f"stopped: {e}. Rerun `learn` later; finished calls replay from cache.")
        return False
    bar.close()
    k.save(out / "knowledge_final.json")
    ungated.save(out / "ungated.json")
    (out / "calibration.json").write_text(json.dumps({"flips": flips, "n": len(learn_qs)}))
    print(f"done: {len(k.facts)} facts kept, {len(ungated.facts)} ungated, spent ${budget.total:.3f} total")
    return True
