"""BIRD data access: questions, schema, column descriptions, value profile, read-only SQL execution and scoring."""
import csv
import hashlib
import json
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path

from evosql.files import write_atomic


@dataclass
class Question:
    qid: int
    db_id: str
    question: str
    gold_sql: str


@dataclass
class Database:
    path: Path
    ddl: str
    tables: list
    columns: dict  # table -> column names
    notes: dict  # table -> {lowercase column: {"name", "description", "values"}} from the description CSVs
    profile: str  # value profile of every column, each line ending with its description


def quote(name):
    """SQLite identifier quoting."""
    return '"' + name.replace('"', '""') + '"'


def literal(value):
    """SQLite string literal."""
    return "'" + str(value).replace("'", "''") + "'"


def load_arcwise(path, db_ids):
    """Questions of the given databases from an Arcwise-Plat file (corrected BIRD Mini-Dev)."""
    items = json.loads(Path(path).read_text())
    return [Question(int(q["question_id"]), q["db_id"], q["question"], q["SQL"]) for q in items if q["db_id"] in db_ids]


def db_path(data_dir, db_id):
    return Path(data_dir) / db_id / f"{db_id}.sqlite"


def open_db(data_dir, db_id, docs_dir):
    """The database with its schema, column descriptions (from docs_dir/<table>.csv) and value profile."""
    path = db_path(data_dir, db_id)
    tables = [r[0] for r in execute(path, "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")[0]]
    columns = {t: [r[1] for r in execute(path, f"PRAGMA table_info({quote(t)})")[0]] for t in tables}
    notes = {t: column_notes(Path(docs_dir) / f"{t}.csv") for t in tables}
    create = execute(path, "SELECT sql FROM sqlite_master WHERE type='table' AND sql IS NOT NULL")[0]
    ddl = "\n\n".join(r[0] for r in create)
    return Database(path, ddl, tables, columns, notes, value_profile(path, tables, notes))


def column_notes(csv_path):
    """{lowercase column: {"name", "description", "values"}} from a BIRD description CSV ({} when it is missing)."""
    if not csv_path.exists():
        return {}
    text = csv_path.read_bytes().decode("utf-8", errors="replace").lstrip("﻿")
    notes = {}
    for row in csv.DictReader(text.splitlines()):
        row = {(k or "").strip(): " ".join((v or "").split()) for k, v in row.items()}
        name = row.get("original_column_name", "")
        notes[name.lower()] = {"name": name, "description": row.get("column_description", ""),
                               "values": row.get("value_description", "")}
    return notes


def note_text(note):
    """One column's description as shown to the agent: "description | values: ..."."""
    return note["description"] + (f" | values: {note['values']}" if note["values"] else "")


def execute(path, sql, timeout=30.0, max_rows=None):
    """Run one statement on a read-only connection. Returns (rows, error)."""
    if not sql:
        return None, "empty SQL"
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    deadline = time.monotonic() + timeout
    # A truthy return from the handler aborts the query with "interrupted".
    con.set_progress_handler(lambda: time.monotonic() > deadline, 10_000)
    try:
        cur = con.execute(sql)
        rows = cur.fetchall() if max_rows is None else cur.fetchmany(max_rows)
        return rows, None
    except Exception as e:  # bad SQL of any kind (syntax, NUL bytes, non-string) is just a failed query
        return None, str(e)
    finally:
        con.close()


def value_count(db, table, column, value):
    """Rows whose column, compared as text, equals the value."""
    sql = f"SELECT COUNT(*) FROM {quote(table)} WHERE CAST({quote(column)} AS TEXT) = {literal(value)}"
    rows, _ = execute(db.path, sql)
    return rows[0][0] if rows else 0


def column_stats(path, table, column):
    """(nulls, distinct, min, max) of one column."""
    t, c = quote(table), quote(column)
    return execute(path, f"SELECT COUNT(*) - COUNT({c}), COUNT(DISTINCT {c}), MIN({c}), MAX({c}) FROM {t}")[0][0]


def top_values(path, table, column, limit=None):
    """[(value, count)] of the non-null values, most common first."""
    t, c = quote(table), quote(column)
    cap = f" LIMIT {limit}" if limit else ""
    return execute(path, f"SELECT {c}, COUNT(*) FROM {t} WHERE {c} IS NOT NULL GROUP BY {c} ORDER BY 2 DESC{cap}")[0]


def value_profile(path, tables, notes, max_values=20):
    """One line per column, computed from the data, ending with the column's description after " | "."""
    lines = ["Database value profile (computed from the data; after | : column docs):"]
    for table in tables:
        total = execute(path, f"SELECT COUNT(*) FROM {quote(table)}")[0][0][0]
        for _, name, col_type, *_ in execute(path, f"PRAGMA table_info({quote(table)})")[0]:
            line = _column_line(path, table, name, (col_type or "ANY").upper(), total, max_values)
            note = notes.get(table, {}).get(name.lower())
            lines.append(line + (f" | {note_text(note)}" if note else ""))
    return "\n".join(lines)


def _column_line(path, table, name, col_type, total, max_values):
    """Coded values with counts, a numeric or date range, or the most common text values, plus the null share."""
    nulls, distinct, low, high = column_stats(path, table, name)
    share = nulls / total if total else 0.0
    head = f"- {table}.{name} {col_type}" + (f", {share:.0%} null" if share >= 0.005 else ", <1% null" if nulls else "")
    listed = lambda rows: ", ".join(f"{v!r} {n}" for v, n in rows)

    if distinct == 0:
        return f"{head}: all null"
    if distinct == total - nulls and distinct > max_values:
        return f"{head}: unique per row"
    if distinct <= max_values:
        return f"{head}: " + listed(top_values(path, table, name))
    if col_type in ("INTEGER", "REAL"):
        c, t = quote(name), quote(table)
        pick = lambda frac: execute(path, f"SELECT {c} FROM {t} WHERE {c} IS NOT NULL ORDER BY {c} "
                                          f"LIMIT 1 OFFSET {int((total - nulls - 1) * frac)}")[0][0][0]
        return f"{head}, range {low} .. {high}, typical {pick(0.05)} .. {pick(0.95)}"
    # Dates get their range; free text only its most common values (min/max of text is noise).
    span = f", {low!r} .. {high!r}" if col_type == "DATE" else ""
    return f"{head}, {distinct} distinct{span}, most common: " + listed(top_values(path, table, name, 5))


def exec_match(path, pred_sql, gold):
    """BIRD execution accuracy: the prediction's result set equals the gold result set."""
    rows, error = execute(path, pred_sql)
    return not error and set(rows) == set(gold)


def gold_rows(path, q, cache_dir="cache/gold"):
    """Result rows of the gold SQL, cached by a hash of the SQL so a relabelled question never reuses rows."""
    key = hashlib.sha256(f"{q.db_id}\n{q.gold_sql}".encode()).hexdigest()[:16]
    cache = Path(cache_dir) / f"{q.db_id}_{q.qid}_{key}.json"
    if cache.exists():
        return [tuple(r) for r in json.loads(cache.read_text())]
    rows, error = execute(path, q.gold_sql, timeout=120.0)
    if error:
        raise RuntimeError(f"gold SQL failed for question {q.qid}: {error}")
    write_atomic(cache, json.dumps(rows))
    return [tuple(r) for r in rows]
