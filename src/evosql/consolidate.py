"""Consolidation: one call reads all active facts with their source questions and proposes small edits (generalize,
merge, condition, drop); each edit passes the admission checks and a pre-check before the memory applies it."""
from dataclasses import asdict

from evosql.facts import check, check_snippet
from evosql.llm import extract_json
from evosql.proposer import FACT_JSON, FACT_RULES, parse_fact

OPS = {"generalize": (1, 1), "merge": (2, None), "condition": (2, None), "drop": (1, 1)}  # allowed id counts
MAX_EDITS = 5

CONSOLIDATE = """You maintain a knowledge base of facts about ONE SQLite database for a Text2SQL agent.
Below are all current facts, each with its id, record, the question it was learned from and that question's correct SQL. Suggest at most 5 small edits:
- generalize: one fact is worded too narrowly for one question (a specific language, name or value where the rule holds more widely); rewrite it to cover every case the data supports.
- merge: 2 or more facts say the same thing; one fact replaces them.
- condition: 2 or more facts conflict; one fact states when each case applies, as their questions' correct SQL shows.
- drop: a fact is wrong for its own question's correct SQL, or only restates the schema.
Keep good facts unchanged; reply {{"edits": []}} if nothing needs editing.
A new fact follows the same rules as a learned fact.
{rules}
Reply with only a JSON object: {{"edits": [{{"op": "generalize | merge | condition | drop", "ids": ["f1"], "reason": "short", "fact": {fact_json} or null}}]}}

Database schema:
{ddl}

{profile}

Current facts:
{facts}"""


def listing(facts, state, questions):
    """One text block per fact: its record, snippet, source question and that question's correct SQL."""
    blocks = []
    for f in facts:
        s = state[f.id]
        lines = [f"{f.id} (score {s['score']:+d}, uses {s['uses']}) [{f.kind}] {f.subject}: {f.fact}",
                 f"  applies to: {', '.join(f.applies_to)}"]
        if f.sql:
            lines.append(f"  SQL on {f.sql['table']}: {f.sql['sql']}")
        lines.append(f"  learned from: {f.learned_from}")
        source = next((questions[i] for i in f.source_qids if i in questions), None)
        if source:
            lines.append(f"  correct SQL: {source.gold_sql}")
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


def parse_edits(d, active_ids):
    """The usable edits of a reply: known ops and ids, right arity, no fact used twice, a valid fact unless dropping."""
    items = d.get("edits") if isinstance(d, dict) else None
    edits, used = [], set()
    for e in items if isinstance(items, list) else []:
        if len(edits) == MAX_EDITS:
            break
        if not isinstance(e, dict) or e.get("op") not in OPS:
            continue
        ids = e.get("ids") if isinstance(e.get("ids"), list) else []
        ids = list(dict.fromkeys(i for i in ids if isinstance(i, str) and i in active_ids))
        low, high = OPS[e["op"]]
        if not low <= len(ids) <= (high or len(ids)) or used & set(ids):
            continue
        fact = None if e["op"] == "drop" else parse_fact({"fact": e.get("fact")}, 0)
        if e["op"] != "drop" and fact is None:
            continue
        used |= set(ids)
        reason = e["reason"][:200] if isinstance(e.get("reason"), str) else ""
        edits.append({"op": e["op"], "ids": ids, "reason": reason, "fact": fact})
    return edits


def consolidate(llm, memory, gold_of, try_fact):
    """Ask for edits to the active facts, gate each one, apply the ones that pass; returns one record per edit."""
    facts = memory.active()
    if not facts:
        return []
    questions = {q.qid: q for q, _ in memory.history}
    prompt = CONSOLIDATE.format(rules=FACT_RULES, fact_json=FACT_JSON, ddl=memory.db.ddl, profile=memory.db.profile,
                                facts=listing(facts, memory.state, questions))
    reply = llm.chat([{"role": "user", "content": prompt}])

    records = []
    for edit in parse_edits(extract_json(reply["content"]), {f.id for f in facts}):
        new = edit["fact"]
        record = {"op": edit["op"], "ids": edit["ids"], "reason": edit["reason"], "fact": new and asdict(new)}
        if new:
            qids = {i for fid in edit["ids"] for i in memory.facts[fid].source_qids} & questions.keys()
            sources = [questions[i] for i in sorted(qids)]
            rejected = next((r for sq in sources if (r := check(new, memory.db, sq, gold_of(sq)))), None)
            if rejected:
                records.append({**record, "applied": False, "rejected": rejected})
                continue
            if new.sql and all(check_snippet(new.sql, memory.db, sq, gold_of(sq)) for sq in sources):
                new.sql, record["snippet"] = None, "dropped"
        result = memory.apply_edit(edit, try_fact)
        records.append({**record, **result, "fact": new and asdict(new)})
    return records
