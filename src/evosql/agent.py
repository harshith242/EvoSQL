"""Tool-loop Text2SQL agent: inspect tables, profile columns, test queries, then submit one SQL.
Works with native tool calls or, as a fallback, a JSON object in the reply text."""
import json
import re
from collections import Counter
from dataclasses import dataclass

from evosql.bird import execute

SYSTEM = """You are an expert SQLite analyst. Answer the user's question with ONE SQLite query on the database below.
Use the tools to inspect tables, profile columns and test queries. When confident, call submit with the final SQL.
Select exactly the columns the question asks for, nothing extra.
If you cannot call tools natively, reply with only a JSON object like {{"tool": "run_sql", "args": {{"sql": "..."}}}}.

Database schema:
{ddl}

{notes}"""


def _tool(name, description, **params):
    props = {p: {"type": "string", "description": d} for p, d in params.items()}
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {"type": "object", "properties": props, "required": list(params)},
        },
    }


TOOLS = [
    _tool("describe_table", "Show 3 sample rows of a table and its column descriptions.", table="table name"),
    _tool("profile_column", "Null count, distinct count, min/max and top 10 values of a column.", table="table name", column="column name"),
    _tool("run_sql", "Run a read-only SQLite query and see up to 20 rows.", sql="SQLite query"),
    _tool("submit", "Submit the final SQL answer.", sql="final SQLite query"),
]


@dataclass
class AgentResult:
    sql: str
    steps: int
    error: str = None


def _quote(name):
    return '"' + name.replace('"', '""') + '"'


def _format_rows(rows, error):
    if error:
        return f"ERROR: {error}"
    if not rows:
        return "(no rows)"
    lines = [" | ".join(str(v)[:60] for v in r) for r in rows]
    return "\n".join(lines)[:3000]


def run_tool(db, name, args):
    """Execute one tool call and return its text result."""
    if name == "run_sql":
        return _format_rows(*execute(db.path, args.get("sql"), max_rows=20))
    table = args.get("table", "")
    if table not in db.tables:
        return f"ERROR: unknown table {table!r}. Tables: {', '.join(db.tables)}"
    if name == "describe_table":
        sample = _format_rows(*execute(db.path, f"SELECT * FROM {_quote(table)} LIMIT 3"))
        docs = db.docs.get(table, "")
        return f"Sample rows:\n{sample}" + (f"\n\nColumn descriptions:\n{docs}" if docs else "")
    if name == "profile_column":
        t, c = _quote(table), _quote(args.get("column", ""))
        stats = execute(db.path, f"SELECT COUNT(*) - COUNT({c}), COUNT(DISTINCT {c}), MIN({c}), MAX({c}) FROM {t}")
        top = execute(db.path, f"SELECT {c}, COUNT(*) FROM {t} GROUP BY {c} ORDER BY COUNT(*) DESC LIMIT 10")
        return f"nulls | distinct | min | max\n{_format_rows(*stats)}\n\nTop values (value | count):\n{_format_rows(*top)}"
    return f"ERROR: unknown tool {name!r}"


def _parse_json_call(content):
    """Fallback: pull {"tool": ..., "args": {...}} out of plain reply text."""
    match = re.search(r"\{.*\}", content or "", re.DOTALL)
    if not match:
        return None
    try:
        obj = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    if not isinstance(obj, dict) or "tool" not in obj:
        return None
    return {"id": None, "name": obj["tool"], "arguments": json.dumps(obj.get("args", {}))}


def answer(llm, db, question, knowledge, temperature=0.0, sample=0, max_steps=8):
    messages = [
        {"role": "system", "content": SYSTEM.format(ddl=db.ddl, notes=knowledge.render())},
        {"role": "user", "content": question},
    ]
    for step in range(1, max_steps + 1):
        if step == max_steps:
            messages.append({"role": "user", "content": "Last step: call submit now with your best SQL."})
        reply = llm.chat(messages, tools=TOOLS, temperature=temperature, sample=sample)
        calls = reply["tool_calls"]
        if calls:
            messages.append({
                "role": "assistant",
                "content": reply["content"],
                "tool_calls": [
                    {"id": c["id"], "type": "function", "function": {"name": c["name"], "arguments": c["arguments"]}}
                    for c in calls
                ],
            })
        else:
            messages.append({"role": "assistant", "content": reply["content"] or ""})
            fallback = _parse_json_call(reply["content"])
            if not fallback:
                messages.append({"role": "user", "content": "Call a tool (or reply with the JSON object) to continue."})
                continue
            calls = [fallback]

        for call in calls:
            try:
                args = json.loads(call["arguments"] or "{}")
            except json.JSONDecodeError:
                args = {}
            if call["name"] == "submit":
                return AgentResult(args.get("sql"), step)
            result = run_tool(db, call["name"], args)
            if call["id"]:
                messages.append({"role": "tool", "tool_call_id": call["id"], "content": result})
            else:
                messages.append({"role": "user", "content": f"Tool result:\n{result}"})
    return AgentResult(None, max_steps, "no submit within step limit")


def answer_self_consistent(llm, db, question, knowledge, n, max_steps=8):
    """Sample n answers at temperature 0.7 and return the SQL whose result set is most common."""
    results, votes = [], Counter()
    for i in range(n):
        r = answer(llm, db, question, knowledge, temperature=0.7, sample=i, max_steps=max_steps)
        rows, error = execute(db.path, r.sql)
        key = None if error else frozenset(rows)
        results.append((r, key))
        if key is not None:
            votes[key] += 1
    steps = sum(r.steps for r, _ in results)
    if not votes:
        return AgentResult(None, steps, "no sample produced a runnable SQL")
    best = votes.most_common(1)[0][0]
    winner = next(r for r, key in results if key == best)
    return AgentResult(winner.sql, steps)
