"""EHRSQL on MIMIC-IV: the frozen question stream, the fixed current time, and the official post-processing of SQL."""
import json
from pathlib import Path

from evosql.bird import Question, open_db
from evosql.ehrsql_postprocess import post_process_sql

NOW = "2100-12-31 23:59:00"
TIME_NOTE = (f"The current time is {NOW}. For \"now\", \"this year\", \"last month\", \"today\" and the like, compute "
             f"from that literal timestamp (e.g. datetime('{NOW}','start of year')); never use current_time, "
             "current_date or 'now'.")


def load_stream(path):
    """(questions in file order, {qid: template}) from a frozen stream file."""
    items = json.loads(Path(path).read_text())
    questions = [Question(i["qid"], i["db_id"], i["question"], i["gold_sql"]) for i in items]
    return questions, {i["qid"]: i["template"] for i in items}


def open_mimic(data_dir, db_id):
    """The database without column docs, whose value profile ends with the note on the current time."""
    db = open_db(data_dir, db_id, Path(data_dir) / db_id / "no_docs")
    db.profile += "\n\n" + TIME_NOTE
    return db


def score_sql(sql):
    """The SQL as the official scorer post-processes it (a missing SQL stays as it is)."""
    return post_process_sql(sql) if isinstance(sql, str) else sql
