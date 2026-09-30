"""Tool-loop Text2SQL agent: inspect tables, profile columns, test queries, then submit one SQL.
Learned knowledge is a text section of the system prompt. Native tool calls or a JSON fallback in the reply text."""
from evosql.bird import column_stats, execute, note_text, quote, top_values
from evosql.llm import extract_json

SYSTEM = """You are an expert SQLite analyst. Answer the user's question with ONE SQLite query on the database below.
Use the tools to inspect tables, profile columns and test queries. When confident, call submit with the final SQL.
Select exactly the columns the question asks for, nothing extra.
If you cannot call tools natively, reply with only a JSON object like {{"tool": "run_sql", "args": {{"sql": "..."}}}}.

Database schema:
{ddl}

{profile}{notes}"""


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
    _tool("profile_column", "Null count, distinct count, min/max and top 10 values of a column.",
          table="table name", column="column name"),
    _tool("run_sql", "Run a read-only SQLite query and see up to 20 rows.", sql="SQLite query"),
    _tool("submit", "Submit the final SQL answer.", sql="final SQLite query"),
]


def _format_rows(rows, error=None):
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
        docs = "\n".join(f"- {n['name']}: {note_text(n)}" for n in db.notes[table].values())
        return f"Sample rows:\n{sample}" + (f"\n\nColumn descriptions:\n{docs}" if docs else "")

    column = args.get("column", "")
    # SQLite reads an unknown double-quoted name as a string literal, so check it first.
    if column not in db.columns[table]:
        return f"ERROR: unknown column {column!r} in {table}. Columns: {', '.join(db.columns[table])}"
    stats = _format_rows([column_stats(db.path, table, column)])
    top = _format_rows(top_values(db.path, table, column, 10))
    return f"nulls | distinct | min | max\n{stats}\n\nTop values (value | count):\n{top}"


def _calls(reply):
    """[{id, name, args}] from native tool calls, else from a {"tool", "args"} JSON object in the text (id None)."""
    if reply["tool_calls"]:
        calls = [(c["id"], c["name"], extract_json(c["arguments"])) for c in reply["tool_calls"]]
    else:
        obj = extract_json(reply["content"])
        calls = [(None, obj["tool"], obj.get("args"))] if isinstance(obj, dict) and "tool" in obj else []
    return [{"id": i, "name": n, "args": a if isinstance(a, dict) else {}} for i, n, a in calls]


def answer(llm, db, question, notes="", max_steps=8):
    """Run the tool loop; return (submitted SQL or None, agent turns). notes: learned knowledge for the prompt."""
    # Static parts first (rules, schema, value profile), then knowledge, so the provider's prefix cache hits.
    system = SYSTEM.format(ddl=db.ddl, profile=db.profile + "\n\n", notes=notes)
    messages = [{"role": "system", "content": system}, {"role": "user", "content": question}]

    for step in range(1, max_steps + 1):
        if step == max_steps:
            messages.append({"role": "user", "content": "Last step: call submit now with your best SQL."})
        reply = llm.chat(messages, tools=TOOLS)
        # With tools, DeepSeek's thinking mode requires every earlier turn's reasoning to be sent back.
        thought = {"reasoning_content": reply["reasoning"]} if reply.get("reasoning") else {}
        if reply["tool_calls"]:
            native = [{"id": c["id"], "type": "function", "function": {"name": c["name"], "arguments": c["arguments"]}}
                      for c in reply["tool_calls"]]
            messages.append({"role": "assistant", "content": reply["content"], **thought, "tool_calls": native})
        else:
            messages.append({"role": "assistant", "content": reply["content"] or "", **thought})

        calls = _calls(reply)
        if not calls:
            messages.append({"role": "user", "content": "Call a tool (or reply with the JSON object) to continue."})
            continue
        for call in calls:
            if call["name"] == "submit":
                return call["args"].get("sql"), step
            result = run_tool(db, call["name"], call["args"])
            if call["id"]:
                messages.append({"role": "tool", "tool_call_id": call["id"], "content": result})
            else:
                messages.append({"role": "user", "content": f"Tool result:\n{result}"})
    return None, max_steps
