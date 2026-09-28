"""BIRD data access: questions, schema, column docs, read-only SQL execution and scoring."""
import csv
import json
import os
import re
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Question:
    qid: int
    db_id: str
    question: str
    gold_sql: str
    difficulty: str
    evidence: str  # BIRD hint; only shown when an arm turns hints on


@dataclass
class Database:
    db_id: str
    path: Path
    ddl: str
    tables: list
    docs: dict  # table -> column descriptions; empty when the arm has no docs


def open_db(data_dir, db_id, with_docs):
    path = db_path(data_dir, db_id)
    tables = table_names(path)
    docs = {t: table_docs(data_dir, db_id, t) for t in tables} if with_docs else {}
    return Database(db_id, path, schema_ddl(path), tables, docs)


def load_questions(data_dir, db_id):
    items = json.loads((Path(data_dir) / "dev.json").read_text())
    return [
        Question(q["question_id"], q["db_id"], q["question"], q["SQL"], q["difficulty"], q["evidence"])
        for q in items
        if q["db_id"] == db_id
    ]


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
    cache.parent.mkdir(parents=True, exist_ok=True)
    tmp = cache.with_suffix(".tmp")
    tmp.write_text(json.dumps(rows))
    os.replace(tmp, cache)  # atomic, so a kill never leaves a truncated cache file
    return [tuple(r) for r in rows]


def table_names(path):
    rows, _ = execute(path, "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
    return [r[0] for r in rows]


def schema_ddl(path):
    rows, _ = execute(path, "SELECT sql FROM sqlite_master WHERE type='table' AND sql IS NOT NULL")
    return "\n\n".join(r[0] for r in rows)


def tables_used(sql, tables):
    return {t for t in tables if re.search(rf"(?<!\w){re.escape(t)}(?!\w)", sql, re.IGNORECASE)}


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
