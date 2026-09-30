import csv
import sqlite3

from evosql.bird import open_db

RULES = {"generic_min_questions": 8, "generic_share": 0.25, "semantic_min": 0.75, "semantic_margin": 0.05,
         "idle_uses": 5, "precheck_max": 2}


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
