import csv
import sqlite3

from evosql.bird import open_db

RULES = {"cutoff": 2.75, "max_facts": 2, "idle_uses": 5, "precheck_pool": 8, "precheck_max": 2}


class FakeJev:
    """Scores every question with score(state, key) and records each call."""

    def __init__(self, score):
        self.score, self.calls = score, []
        self.usage = {"calls": 0, "usd": 0.0}

    def decide(self, state, questions):
        self.calls.append((state, questions))
        return {k: {"type": "score", "score": self.score(state, k)} for k in questions}


def make_db(root, name, script, notes=None):
    """A SQLite database built from a SQL script and opened; notes {table: {column: description}} become CSVs."""
    (root / name).mkdir()
    con = sqlite3.connect(root / name / f"{name}.sqlite")
    con.executescript(script)
    con.close()
    docs = root / f"{name}_docs"
    docs.mkdir()
    for table, columns in (notes or {}).items():
        with open(docs / f"{table}.csv", "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["original_column_name", "column_description", "value_description"])
            writer.writerows([c, d, ""] for c, d in columns.items())
    return open_db(root, name, docs)
