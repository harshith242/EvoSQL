"""Tool-loop Text2SQL agent: inspect tables, profile columns, test queries, then submit one SQL.
The knowledge delivery adds a prompt section and may add tools. Native tool calls or a JSON fallback in the reply text."""
import json

from evosql.bird import execute, quote
from evosql.llm import extract_json

SYSTEM = """You are an expert SQLite analyst. Answer the user's question with ONE SQLite query on the database below.
Use the tools to inspect tables, profile columns and test queries. When confident, call submit with the final SQL.
Select exactly the columns the question asks for, nothing extra.
If you cannot call tools natively, reply with only a JSON object like {{"tool": "run_sql", "args": {{"sql": "..."}}}}.

Database schema:
{ddl}

{profile}{notes}"""


def tool_schema(name, description, **params):
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
    tool_schema("describe_table", "Show 3 sample rows of a table and its column descriptions.", table="table name"),
    tool_schema("profile_column", "Null count, distinct count, min/max and top 10 values of a column.", table="table name", column="column name"),
    tool_schema("run_sql", "Run a read-only SQLite query and see up to 20 rows.", sql="SQLite query"),
    tool_schema("submit", "Submit the final SQL answer.", sql="final SQLite query"),
]


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
    if name not in ("describe_table", "profile_column"):
        return f"ERROR: unknown tool {name!r}. Tools: describe_table, profile_column, run_sql, submit"
    table = args.get("table", "")
    if table not in db.tables:
        return f"ERROR: unknown table {table!r}. Tables: {', '.join(db.tables)}"
    if name == "describe_table":
        sample = _format_rows(*execute(db.path, f"SELECT * FROM {quote(table)} LIMIT 3"))
        docs = db.docs.get(table, "")
        return f"Sample rows:\n{sample}" + (f"\n\nColumn descriptions:\n{docs}" if docs else "")
    column = args.get("column", "")
    # SQLite reads an unknown double-quoted name as a string literal, so check it first.
    if column not in db.columns[table]:
        return f"ERROR: unknown column {column!r} in {table}. Columns: {', '.join(db.columns[table])}"
    t, c = quote(table), quote(column)
    stats = execute(db.path, f"SELECT COUNT(*) - COUNT({c}), COUNT(DISTINCT {c}), MIN({c}), MAX({c}) FROM {t}")
    top = execute(db.path, f"SELECT {c}, COUNT(*) FROM {t} GROUP BY {c} ORDER BY COUNT(*) DESC LIMIT 10")
    return f"nulls | distinct | min | max\n{_format_rows(*stats)}\n\nTop values (value | count):\n{_format_rows(*top)}"


def _parse_json_call(content):
    """Fallback for models without native tool calls: {"tool": ..., "args": {...}} in the reply text."""
    obj = extract_json(content)
    if not isinstance(obj, dict) or "tool" not in obj:
        return None
    args = obj.get("args")
    return {"id": None, "name": obj["tool"], "arguments": json.dumps(args if isinstance(args, dict) else {})}


def answer(llm, db, question, knowledge, temperature=0.0, sample=0, max_steps=8):
    """Run the tool loop; return (submitted SQL or None, agent turns). knowledge is a delivery mode (see delivery.py)."""
    messages = [
        # Static parts first (rules, schema, value profile), then knowledge, so the provider's prefix cache hits.
        {"role": "system", "content": SYSTEM.format(ddl=db.ddl, profile=db.profile + "\n\n" if db.profile else "",
                                                    notes=knowledge.prompt(question))},
        {"role": "user", "content": question},
    ]
    tools = TOOLS + knowledge.tools
    for step in range(1, max_steps + 1):
        if step == max_steps:
            messages.append({"role": "user", "content": "Last step: call submit now with your best SQL."})
        reply = llm.chat(messages, tools=tools, temperature=temperature, sample=sample)
        calls = reply["tool_calls"]
        # With tools, DeepSeek's thinking mode requires every earlier turn's reasoning to be sent back.
        thought = {"reasoning_content": reply["reasoning"]} if reply.get("reasoning") else {}
        if calls:
            messages.append({
                "role": "assistant",
                "content": reply["content"],
                **thought,
                "tool_calls": [
                    {"id": c["id"], "type": "function", "function": {"name": c["name"], "arguments": c["arguments"]}}
                    for c in calls
                ],
            })
        else:
            messages.append({"role": "assistant", "content": reply["content"] or "", **thought})
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
            if not isinstance(args, dict):
                args = {}
            if call["name"] == "submit":
                return args.get("sql"), step
            result = knowledge.call(call["name"], args) or run_tool(db, call["name"], args)
            if call["id"]:
                messages.append({"role": "tool", "tool_call_id": call["id"], "content": result})
            else:
                messages.append({"role": "user", "content": f"Tool result:\n{result}"})
    return None, max_steps
