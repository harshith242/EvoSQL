"""BIRD data access: questions, schema, column docs, read-only SQL execution and scoring."""
import csv
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
    difficulty: str


@dataclass
class Database:
    path: Path
    ddl: str
    tables: list
    columns: dict  # table -> column names
    docs: dict  # table -> BIRD column descriptions ("" when the CSV is missing)
    profile: str = ""  # value profile of every column; empty when the profile is off


def quote(name):
    """SQLite identifier quoting."""
    return '"' + name.replace('"', '""') + '"'


def open_db(data_dir, db_id, with_profile=False):
    path = db_path(data_dir, db_id)
    tables = table_names(path)
    columns = {t: [r[1] for r in execute(path, f"PRAGMA table_info({quote(t)})")[0]] for t in tables}
    docs = {t: table_docs(data_dir, db_id, t) for t in tables}
    profile = value_profile(path, tables) if with_profile else ""
    return Database(path, schema_ddl(path), tables, columns, docs, profile)


def _row(path, sql):
    return execute(path, sql)[0][0]


def value_profile(path, tables, max_values=20):
    """One line per column, computed from the data: coded values with counts, numeric/date ranges, null share."""
    lines = ["Database value profile (computed from the data):"]
    for table in tables:
        t = quote(table)
        total = _row(path, f"SELECT COUNT(*) FROM {t}")[0]
        for _, name, col_type, *_ in execute(path, f"PRAGMA table_info({t})")[0]:
            c = quote(name)
            nulls, distinct = _row(path, f"SELECT COUNT(*) - COUNT({c}), COUNT(DISTINCT {c}) FROM {t}")
            share = f"{nulls / total:.0%}" if nulls / total >= 0.005 else "<1%"
            head = f"- {table}.{name} {col_type or 'ANY'}" + (f", {share} null" if total and nulls else "")
            if distinct == 0:
                lines.append(f"{head}: all null")
            elif distinct == total - nulls and distinct > max_values:
                lines.append(f"{head}: unique per row")
            elif distinct <= max_values:
                rows = execute(path, f"SELECT {c}, COUNT(*) FROM {t} WHERE {c} IS NOT NULL GROUP BY {c} ORDER BY 2 DESC")[0]
                lines.append(f"{head}: " + ", ".join(f"{v!r} {n}" for v, n in rows))
            elif col_type.upper() in ("INTEGER", "REAL"):
                low, high = _row(path, f"SELECT MIN({c}), MAX({c}) FROM {t}")
                pick = lambda frac: _row(path, f"SELECT {c} FROM {t} WHERE {c} IS NOT NULL ORDER BY {c} "
                                               f"LIMIT 1 OFFSET {int((total - nulls - 1) * frac)}")[0]
                lines.append(f"{head}, range {low} .. {high}, typical {pick(0.05)} .. {pick(0.95)}")
            else:
                # Dates get their range; free text only its most common values (min/max of text is noise).
                low, high = _row(path, f"SELECT MIN({c}), MAX({c}) FROM {t}")
                span = f", {low!r} .. {high!r}" if col_type.upper() == "DATE" else ""
                top = execute(path, f"SELECT {c}, COUNT(*) FROM {t} WHERE {c} IS NOT NULL GROUP BY {c} ORDER BY 2 DESC LIMIT 5")[0]
                lines.append(f"{head}, {distinct} distinct{span}, most common: " + ", ".join(f"{v!r} {n}" for v, n in top))
    return "\n".join(lines)


def load_questions(data_dir, db_id):
    items = json.loads((Path(data_dir) / "dev.json").read_text())
    return [
        Question(q["question_id"], q["db_id"], q["question"], q["SQL"], q["difficulty"])
        for q in items
        if q["db_id"] == db_id
    ]


def load_hints(data_dir, db_id):
    """{question text: BIRD's hand-written hint}; only the diagnostic hints mode shows them."""
    items = json.loads((Path(data_dir) / "dev.json").read_text())
    return {q["question"]: q["evidence"] for q in items if q["db_id"] == db_id}


def db_path(data_dir, db_id):
    return Path(data_dir) / db_id / f"{db_id}.sqlite"


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


def exec_match(path, pred_sql, gold, timeout=30.0):
    """BIRD execution accuracy: the prediction's result set equals the gold result set."""
    rows, error = execute(path, pred_sql, timeout)
    if error:
        return False
    return set(rows) == set(gold)


def gold_rows(path, q, cache_dir="cache/gold", timeout=120.0):
    cache = Path(cache_dir) / f"{q.db_id}_{q.qid}.json"
    if cache.exists():
        return [tuple(r) for r in json.loads(cache.read_text())]
    rows, error = execute(path, q.gold_sql, timeout)
    if error:
        raise RuntimeError(f"gold SQL failed for question {q.qid}: {error}")
    write_atomic(cache, json.dumps(rows))
    return [tuple(r) for r in rows]


def table_names(path):
    rows, _ = execute(path, "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
    return [r[0] for r in rows]


def schema_ddl(path):
    rows, _ = execute(path, "SELECT sql FROM sqlite_master WHERE type='table' AND sql IS NOT NULL")
    return "\n\n".join(r[0] for r in rows)


def table_docs(data_dir, db_id, table):
    """Column descriptions from BIRD's database_description CSV, one line per column."""
    path = Path(data_dir) / db_id / "database_description" / f"{table}.csv"
    if not path.exists():
        return ""
    text = path.read_bytes().decode("utf-8", errors="replace").lstrip("﻿")
    lines = []
    for row in csv.DictReader(text.splitlines()):
        row = {(k or "").strip(): " ".join((v or "").split()) for k, v in row.items()}
        line = f"- {row.get('original_column_name', '')}: {row.get('column_description', '')}"
        if row.get("value_description"):
            line += f" | values: {row['value_description']}"
        lines.append(line)
    return "\n".join(lines)
