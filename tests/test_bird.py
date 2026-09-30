import json
import sqlite3

import pytest

from conftest import make_db
from evosql.bird import exec_match, execute, load_arcwise, value_profile


@pytest.fixture
def db(tmp_path):
    path = tmp_path / "t.sqlite"
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE patient (id INTEGER, sex TEXT, age INTEGER)")
    con.executemany("INSERT INTO patient VALUES (?, ?, ?)", [(1, "F", 30), (2, "M", None), (3, "F", 50)])
    con.commit()
    con.close()
    return path


def test_exec_match_ignores_row_order_and_duplicates(db):
    gold = [(1,), (3,)]
    assert exec_match(db, "SELECT id FROM patient WHERE sex = 'F' ORDER BY id DESC", gold)
    assert exec_match(db, "SELECT p.id FROM patient p, patient q WHERE p.sex = 'F'", gold)


def test_exec_match_null_equals_null_but_wrong_values_fail(db):
    assert exec_match(db, "SELECT age FROM patient WHERE id = 2", [(None,)])
    assert not exec_match(db, "SELECT id FROM patient WHERE sex = 'M'", [(1,), (3,)])
    assert not exec_match(db, "SELECT id, sex FROM patient WHERE sex = 'F'", [(1,), (3,)])


def test_erroring_or_missing_prediction_is_wrong(db):
    assert not exec_match(db, "SELECT nope FROM patient", [(1,)])
    assert not exec_match(db, None, [(1,)])


def test_connection_is_read_only(db):
    rows, error = execute(db, "DELETE FROM patient")
    assert rows is None and "readonly" in error
    assert execute(db, "SELECT COUNT(*) FROM patient")[0] == [(3,)]


def test_slow_query_times_out(db):
    slow = "WITH RECURSIVE c(x) AS (SELECT 1 UNION ALL SELECT x + 1 FROM c) SELECT COUNT(*) FROM c"
    rows, error = execute(db, slow, timeout=0.2)
    assert rows is None and "interrupt" in error


def test_value_profile_lists_values_nulls_ids_and_ends_each_line_with_its_description(tmp_path):
    db = make_db(tmp_path, "toy", "CREATE TABLE patient (id INTEGER, sex TEXT, age INTEGER); "
                                  "INSERT INTO patient VALUES (1, 'F', 30), (2, 'M', NULL), (3, 'F', 50);",
                 notes={"patient": {"SEX": "sex of the patient"}})
    prof = value_profile(db.path, db.tables, db.notes, max_values=2).splitlines()
    assert "- patient.sex TEXT: 'F' 2, 'M' 1 | sex of the patient" in prof  # description names match any case
    age = next(line for line in prof if line.startswith("- patient.age"))
    assert age.startswith("- patient.age INTEGER, 33% null:") and "50 1" in age and "30 1" in age
    assert "- patient.id INTEGER: unique per row" in prof  # undocumented column: no description


def test_load_arcwise_keeps_only_requested_databases(tmp_path):
    path = tmp_path / "plat.json"
    path.write_text(json.dumps([
        {"question_id": "7", "db_id": "formula_1", "question": "q7", "SQL": "SELECT 7"},
        {"question_id": 8, "db_id": "financial", "question": "q8", "SQL": "SELECT 8"},
    ]))
    [only] = load_arcwise(path, {"formula_1"})
    assert (only.qid, only.gold_sql) == (7, "SELECT 7")
