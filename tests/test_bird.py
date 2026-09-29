import sqlite3

import pytest

from evosql.bird import exec_match, execute


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


def test_value_profile_lists_coded_values_nulls_and_ids(db):
    from evosql.bird import value_profile
    prof = value_profile(db, ["patient"], max_values=2).splitlines()
    assert "- patient.sex TEXT: 'F' 2, 'M' 1" in prof
    age = next(line for line in prof if line.startswith("- patient.age"))
    assert age.startswith("- patient.age INTEGER, 33% null:") and "50 1" in age and "30 1" in age
    assert "- patient.id INTEGER: unique per row" in prof


def test_column_docs_end_each_profile_line_only_when_enabled(db):
    from evosql.bird import value_profile
    docs = {"patient": {"SEX": "sex | values: F: female; M: male", "Age": "age in years"}}
    prof = value_profile(db, ["patient"], max_values=2, docs=docs).splitlines()
    assert "- patient.sex TEXT: 'F' 2, 'M' 1 | sex | values: F: female; M: male" in prof  # doc names match any case
    assert next(line for line in prof if line.startswith("- patient.age")).endswith(" | age in years")
    assert "- patient.id INTEGER: unique per row" in prof  # undocumented column: no note
    assert value_profile(db, ["patient"], max_values=2).splitlines()[0] == "Database value profile (computed from the data):"
