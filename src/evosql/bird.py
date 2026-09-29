"""BIRD data access: questions, schema, column docs, read-only SQL execution and scoring."""
import csv
import json
import sqlite3
import time
from dataclasses import dataclass, field
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
    column_notes: dict = field(default_factory=dict)  # table -> {column: docs text}, only when column docs are on


def quote(name):
    """SQLite identifier quoting."""
    return '"' + name.replace('"', '""') + '"'


def open_db(data_dir, db_id, with_profile=False, with_column_docs=False, docs_dir=None):
    """docs_dir: a folder of <table>.csv descriptions to use instead of the database's own (e.g. corrected ones)."""
    path = db_path(data_dir, db_id)
    tables = table_names(path)
    columns = {t: [r[1] for r in execute(path, f"PRAGMA table_info({quote(t)})")[0]] for t in tables}
    docs = {t: table_docs(data_dir, db_id, t, docs_dir) for t in tables}
    notes = {t: column_docs(data_dir, db_id, t, docs_dir) for t in tables} if with_column_docs else None
    profile = value_profile(path, tables, docs=notes) if with_profile else ""
    return Database(path, schema_ddl(path), tables, columns, docs, profile, notes or {})


def _row(path, sql):
    return execute(path, sql)[0][0]


def value_profile(path, tables, max_values=20, docs=None):
    """One line per column, computed from the data: coded values with counts, numeric/date ranges, null share.
    With docs ({table: {column: text}}), each line ends with the column's BIRD description after " | "."""
    lines = ["Database value profile (computed from the data" + ("; after | : column docs):" if docs else "):")]
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
            note = {k.lower(): v for k, v in (docs or {}).get(table, {}).items()}.get(name.lower())
            if note:
                lines[-1] += f" | {note}"
    return "\n".join(lines)


def load_arcwise(path, db_ids):
    """Questions of the given databases from an Arcwise-Plat file (corrected BIRD Mini-Dev)."""
    items = json.loads(Path(path).read_text())
    return [Question(int(q["question_id"]), q["db_id"], q["question"], q["SQL"], q.get("difficulty", "unknown"))
            for q in items if q["db_id"] in db_ids]


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


def column_docs(data_dir, db_id, table, docs_dir=None):
    """{column: "description | values: ..."} from BIRD's database_description CSV ({} when it is missing)."""
    path = Path(docs_dir or Path(data_dir) / db_id / "database_description") / f"{table}.csv"
    if not path.exists():
        return {}
    text = path.read_bytes().decode("utf-8", errors="replace").lstrip("\ufeff")
    docs = {}
    for row in csv.DictReader(text.splitlines()):
        row = {(k or "").strip(): " ".join((v or "").split()) for k, v in row.items()}
        doc = row.get("column_description", "")
        if row.get("value_description"):
            doc += f" | values: {row['value_description']}"
        docs[row.get("original_column_name", "")] = doc
    return docs


def table_docs(data_dir, db_id, table, docs_dir=None):
    """Column descriptions, one line per column (the describe_table tool shows these)."""
    return "\n".join(f"- {c}: {d}" for c, d in column_docs(data_dir, db_id, table, docs_dir).items())
