"""The proposer turns one failed question (question, agent SQL, correct SQL) into one general fact about the database."""
from evosql.facts import Fact, render
from evosql.llm import extract_json

FACT_RULES = """Fact kinds (examples use a made-up shop database):
- mapping: what a phrase used in questions means in the data. Example: "shipped orders" means Orders.Status is 'S'; a status named in a question matches Orders.Status exactly, never as a substring.
- encoding: how values are stored. Example: unpaid Orders.Payment is stored as both 'none' and '0'.
- constraint: a range or business rule. Example: an abnormal Orders.Discount includes the boundary: at most 5 or at least 30, not strictly below or above.
- meaning: what a column represents. Example: Orders.Amt is the order total in cents.
- grain: what one row is and how to count entities. Example: one Orders row is one order line; a customer count needs distinct Orders.CustID.
- relation: a join path and its cardinality. Example: Customer 1:N Orders via Customer.ID and Orders.CustID.
Rules:
- Do not restate anything the column docs or the value profile already say (documented ranges, codes, meanings). Write only what they miss: conventions (how names, dates and counts are formed), stored codes that differ from what a question says, what question phrases mean, row grain and join paths.
- State a fact about the data, never the SQL fix. Do not write SQL keywords or clauses in the statement.
- The fact must help other questions too; never state this question's answer.
- Name columns as Table.Column. The statement is under 40 words.
- applies_to: 1 to 5 short phrases a future question may use when the fact matters; you may reuse this question's wording (e.g. "full name", "shipped").
- values: every stored value the fact relies on, as {"table": ..., "column": ..., "value": ...} exactly as stored; [] if none.
- probe: one read-only SELECT whose result shows evidence for the fact (for a fact that something does not exist, a COUNT(*) query), or null.
- snippet: when the knowledge is naturally a condition or a derived value on ONE table, give it as SQL: {"table": "T", "form": "predicate" or "expression", "sql": "..."} using real Table.Column names (no aliases, no joins, no subqueries, no values specific to this question); otherwise null."""

FACT_JSON = """{"kind": "mapping | encoding | constraint | meaning | grain | relation", "subject": "Table.Column or term", "statement": "...", "applies_to": ["..."], "values": [], "probe": "SELECT ... or null", "snippet": {"table": "Orders", "form": "predicate", "sql": "Orders.Status = 'S'"} or null}"""

PROPOSER = """You maintain a knowledge base about ONE SQLite database so that a Text2SQL agent answers future, different questions correctly.
Below is one question the agent got wrong, with its SQL and the correct SQL. Find the single most important thing the agent did not KNOW about this database and state it as ONE fact.
{rules}
Reply with only a JSON object: {{"fact": {fact_json}}}, or {{"fact": null}} if the correct SQL needs nothing reusable (only this question's own literals).

Database schema:
{ddl}

{profile}

Current knowledge:
{knowledge}

Failed question:
Question: {question}
Agent SQL: {agent_sql}
Correct SQL: {gold_sql}"""


def parse_fact(d, qid, question=""):
    """A Fact from the reply object {"fact": {...}} (None when a required field is missing); bad optional fields go."""
    d = d.get("fact") if isinstance(d, dict) else None
    if not (isinstance(d, dict) and all(isinstance(d.get(k), str) and d[k] for k in ("kind", "subject", "statement"))):
        return None
    phrases = d.get("applies_to") if isinstance(d.get("applies_to"), list) else []
    phrases = [p.strip() for p in phrases if isinstance(p, str) and p.strip()][:5]
    values = d.get("values") if isinstance(d.get("values"), list) else []
    values = [v for v in values if isinstance(v, dict) and {"table", "column", "value"} <= set(v)]
    probe = d.get("probe") if isinstance(d.get("probe"), str) else ""
    probe = None if probe.strip().lower() in ("", "null", "none") else probe
    snippet = d.get("snippet")
    keys = ("table", "form", "sql")
    ok = isinstance(snippet, dict) and all(isinstance(snippet.get(k), str) for k in keys)
    snippet = {k: snippet[k] for k in keys} if ok else None
    return Fact("", d["kind"], d["subject"], d["statement"], phrases, probe, [qid], values, snippet, question)


def propose(llm, db, q, agent_sql, facts):
    """(fact, None) for one failed question, or (None, why) when the reply is empty or has nothing reusable."""
    prompt = PROPOSER.format(rules=FACT_RULES, fact_json=FACT_JSON, ddl=db.ddl, profile=db.profile,
                             knowledge=render(facts) or "(empty)", question=q.question,
                             agent_sql=agent_sql or "(none)", gold_sql=q.gold_sql)
    reply = llm.chat([{"role": "user", "content": prompt}])
    if not (reply["content"] or "").strip():
        return None, "empty reply"  # a known JSON-mode issue
    fact = parse_fact(extract_json(reply["content"]), q.qid, q.question)
    return (fact, None) if fact else (None, "no reusable fact proposed")
