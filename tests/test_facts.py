import sqlite3

import pytest

from evosql.bird import open_db
from evosql.facts import Fact, FactBook, check_fact


@pytest.fixture
def db(tmp_path):
    d = tmp_path / "toy"
    d.mkdir()
    con = sqlite3.connect(d / "toy.sqlite")
    con.execute("CREATE TABLE Laboratory (ID INTEGER, RNP TEXT, UN INTEGER)")
    con.executemany("INSERT INTO Laboratory VALUES (?, ?, ?)", [(1, "negative", 29), (2, "0", 40), (3, "16", 12)])
    con.commit()
    con.close()
    return open_db(tmp_path, "toy", with_docs=False)


def fact(text, subject="Laboratory.RNP", kind="encoding"):
    return Fact("f1", kind, subject, text)


def test_sql_is_rejected_but_ordinary_english_passes(db):
    assert check_fact(fact("Use WHERE RNP IN ('0') for normal."), db) == "contains SQL"
    assert check_fact(fact("Normal results come from two codes: '0' and 'negative'."), db) is None


def test_facts_must_name_real_columns_and_values(db):
    assert check_fact(fact("Normal is 'negative'.", subject="Laboratory.RNPX"), db) == "unknown column"
    assert check_fact(fact("Normal is stored as 'neg'."), db).startswith("value not in data")
    assert check_fact(fact("Borderline is 29.", subject="Laboratory.UN", kind="constraint"), db) is None


def test_fact_leaking_the_answer_is_rejected(db):
    q = "How many patients have a normal anti-ribonuclear protein level?"
    reason = check_fact(fact("There are 42 such patients."), db, q, "SELECT COUNT(*) FROM Laboratory", [(42,)])
    assert reason.startswith("leakage")


def test_factbook_edits_and_renders_grouped_by_subject():
    book = FactBook().apply([
        {"op": "add", "kind": "encoding", "subject": "Laboratory.RNP", "fact": "Normal is '0' or 'negative'.", "qid": 1},
        {"op": "add", "kind": "constraint", "subject": "Laboratory.UN", "fact": "Normal is below 30.", "qid": 2},
        {"op": "add", "kind": "meaning", "subject": "Laboratory.RNP", "fact": "Anti-ribonuclear protein.", "qid": 3},
    ])
    book = book.apply([{"op": "modify", "id": "f2", "kind": "constraint", "subject": "Laboratory.UN",
                        "fact": "Normal is below 30; borderline is 29.", "qid": 4},
                       {"op": "delete", "id": "f3"}])
    assert book.render() == ("Learned database knowledge:\nLaboratory.RNP\n  - [encoding] Normal is '0' or 'negative'.\n"
                             "Laboratory.UN\n  - [constraint] Normal is below 30; borderline is 29.")
    assert book.facts[1].source_qids == [2, 4]


def test_apostrophes_and_identifier_quotes_do_not_break_grounding(db):
    assert check_fact(fact("A patient's normal result is stored as 'negative'."), db) is None
    assert check_fact(fact("Normal is 'negative'.", subject="Laboratory.`RNP`"), db) is None
    assert check_fact(fact("Uses count(ID) per patient."), db) == "contains SQL"


def test_single_digit_numeric_answer_is_a_leak(db):
    q = "How many lab results show a high urea nitrogen level?"
    assert check_fact(fact("Exactly 7 results are high.", subject="Laboratory.UN", kind="constraint"),
                      db, q, "SELECT COUNT(*) FROM Laboratory WHERE UN > 30", [(7,)]).startswith("leakage")
