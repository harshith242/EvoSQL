import sqlite3

import pytest

from evosql.bird import open_db
from evosql.facts import Fact, check_fact, leaks, merge


@pytest.fixture
def db(tmp_path):
    d = tmp_path / "toy"
    d.mkdir()
    con = sqlite3.connect(d / "toy.sqlite")
    con.execute("CREATE TABLE Laboratory (ID INTEGER, RNP TEXT, UN INTEGER)")
    con.executemany("INSERT INTO Laboratory VALUES (?, ?, ?)", [(1, "negative", 29), (2, "0", 40), (3, "16", 12)])
    con.commit()
    con.close()
    return open_db(tmp_path, "toy")


def fact(text, subject="Laboratory.RNP", kind="encoding", applies_to=("normal RNP",), probe=None, qids=(1,), id="f1"):
    return Fact(id, kind, subject, text, list(applies_to), probe, list(qids))


def test_sql_is_rejected_but_ordinary_english_passes(db):
    assert check_fact(fact("Use WHERE RNP IN ('0') for normal."), db) == "contains SQL"
    assert check_fact(fact("Normal results come from two codes: '0' and 'negative'."), db) is None


def test_facts_must_name_real_columns_and_values(db):
    assert check_fact(fact("Normal is 'negative'.", subject="Laboratory.RNPX"), db) == "unknown column"
    assert check_fact(fact("Normal is stored as 'neg'."), db).startswith("value not in data")
    assert check_fact(fact("Borderline is 29.", subject="Laboratory.UN", kind="constraint"), db) is None


def test_fact_leaking_the_answer_is_rejected(db):
    q = "How many patients have a normal anti-ribonuclear protein level?"
    assert leaks("There are 42 such patients.", q, "SELECT COUNT(*) FROM Laboratory", [(42,)])


def test_fact_needs_a_trigger_phrase_and_a_probe_with_rows(db):
    assert check_fact(fact("Normal is 'negative'.", applies_to=[]), db) == "no applies_to phrase"
    assert check_fact(fact("Normal is 'negative'.", probe="SELECT 1 FROM Laboratory WHERE RNP = 'negative'"), db) is None
    assert check_fact(fact("Normal is 'negative'.", probe="SELECT 1 FROM Laboratory WHERE RNP = 'neg'"), db) == "probe returned no rows"
    assert check_fact(fact("Normal is 'negative'.", probe="SELECT nope FROM Laboratory"), db).startswith("probe failed")
    assert check_fact(fact("Normal is 'negative'.", probe="DELETE FROM Laboratory"), db) == "probe is not a SELECT"
    assert check_fact(fact("Normal is 'negative'.", probe="SELECT 1; DELETE FROM Laboratory"), db).startswith("probe failed")


def test_merge_unites_duplicates_and_resolves_mapping_conflicts(db):
    same = [fact("Normal is 'negative'.", qids=[1], id="f1"), fact("normal is 'negative'", applies_to=["RNP"], qids=[2], id="f2")]
    merged, conflicts = merge(same, db)
    assert len(merged) == 1 and merged[0].source_qids == [1, 2] and merged[0].applies_to == ["normal RNP", "RNP"]
    # Texts that differ only in a symbolic stored value are different facts, not duplicates.
    plus, minus = fact("Positive is stored as '+'.", id="f1"), fact("Positive is stored as '-'.", qids=[2], id="f2")
    assert len(merge([plus, minus], db)[0]) == 2
    # "urea" mapped to two different columns: the better-supported mapping wins.
    rnp = fact("Urea means Laboratory.RNP.", kind="mapping", applies_to=["urea"], qids=[1], id="f1")
    un = fact("Urea means Laboratory.UN.", subject="Laboratory.UN", kind="mapping", applies_to=["Urea"], qids=[2, 3], id="f2")
    merged, conflicts = merge([rnp, un], db)
    assert [f.id for f in merged] == ["f2"] and conflicts == [{"phrase": "urea", "facts": ["f1", "f2"], "kept": "f2"}]
    # A tie drops both.
    merged, conflicts = merge([rnp, fact(un.fact, un.subject, "mapping", ["urea"], qids=[5], id="f2")], db)
    assert merged == [] and conflicts[0]["kept"] is None
    # A shared generic phrase is taken from both facts; the facts themselves survive on their specific phrases.
    rnp = fact("Normal Laboratory.RNP is 'negative'.", kind="mapping", applies_to=["normal RNP", "normal"], id="f1")
    un = fact("Normal Laboratory.UN is below 30.", "Laboratory.UN", "mapping", ["normal urea", "Normal"], id="f2")
    merged, conflicts = merge([rnp, un], db)
    assert [f.applies_to for f in merged] == [["normal RNP"], ["normal urea"]] and conflicts[0]["phrase"] == "normal"


def test_apostrophes_and_identifier_quotes_do_not_break_grounding(db):
    assert check_fact(fact("A patient's normal result is stored as 'negative'."), db) is None
    assert check_fact(fact("Normal is 'negative'.", subject="Laboratory.`RNP`"), db) is None
    assert check_fact(fact("Uses count(ID) per patient."), db) == "contains SQL"


def test_single_digit_numeric_answer_is_a_leak(db):
    q = "How many lab results show a high urea nitrogen level?"
    assert leaks("Exactly 7 results are high.", q, "SELECT COUNT(*) FROM Laboratory WHERE UN > 30", [(7,)])


def test_facts_that_only_restate_the_column_docs_are_dropped(db):
    db.column_notes = {"Laboratory": {"un": "urea nitrogen | values: Commonsense evidence:Normal range: N < 30"}}
    restated = fact("A normal Laboratory.UN is below 30.", "Laboratory.UN", "constraint")
    assert check_fact(restated, db) == "already in docs"
    boundary = fact("An abnormal Laboratory.UN includes the boundary: 30 or more.", "Laboratory.UN", "constraint")
    new_range = fact("A dangerous Laboratory.UN is above 40.", "Laboratory.UN", "constraint")
    assert check_fact(boundary, db) is None and check_fact(new_range, db) is None
    # Docs with the direction inverted (as BIRD's uric acid docs are): a fact that corrects them is kept.
    db.column_notes = {"Laboratory": {"UN": "urea nitrogen | values: Normal range: N > 30"}}
    assert check_fact(restated, db) is None
    db.column_notes = {}
    assert check_fact(restated, db) is None  # without column docs (v4) nothing counts as restated
