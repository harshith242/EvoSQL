import sqlite3

import numpy as np
import pytest

from evosql.bird import Question, open_db
from evosql.facts import Fact
from evosql.memory import FactMemory

RULES = {"generic_min_questions": 8, "generic_share": 0.25, "semantic_min": 0.75, "semantic_margin": 0.05,
         "idle_uses": 5, "precheck_max": 2}


@pytest.fixture
def db(tmp_path):
    d = tmp_path / "f1"
    d.mkdir()
    con = sqlite3.connect(d / "f1.sqlite")
    con.execute("CREATE TABLE races (raceId INTEGER, name TEXT, year INTEGER)")
    con.execute("CREATE TABLE results (raceId INTEGER, driverId INTEGER, time TEXT, points REAL)")
    con.commit()
    con.close()
    db = open_db(tmp_path, "f1")
    db.column_notes = {"results": {"time": "finish time of the driver"}}
    return db


def fact(text, subject="results.time", kind="mapping", phrases=("finished",)):
    return Fact("", kind, subject, text, list(phrases), None, [1], [])


def memory(db, embed=None):
    return FactMemory(db, embed or (lambda texts: np.ones((len(texts), 2))), RULES)


def test_phrase_path_is_word_bounded_and_structural_facts_need_schema_scope(db):
    m = memory(db)
    m.add(fact("A driver finished when results.time has a value."), 0)
    m.add(fact("Patient age is computed from the birth year in races.year.", "races.year", "meaning", ["age"]), 0)
    m.add(fact("One results row is one driver in one race.", "results", "grain", ["how many drivers"]), 0)
    ids = lambda q: [f.id for f in m.select(q, [])]
    assert ids("Which drivers finished race 5?") == ["f1"]
    assert ids("What is the average points?") == []  # "age" is not a word in "average"
    assert ids("How many drivers are there?") == []  # a grain fact needs its table in the question
    assert ids("How many drivers have results in 2009?") == ["f3"]


def test_generic_trigger_needs_a_second_cue(db):
    m = memory(db)
    m.add(fact("A win means the highest results.points in a race.", "results.points", phrases=["win"]), 0)
    history = [f"Which win number {i}?" for i in range(8)]  # "win" is in 100% of earlier questions: generic
    assert m.select("Which driver had a win?", []) != []  # not generic without history
    assert m.select("Which driver had a win?", history) == []
    assert [f.id for f in m.select("Which win gave the most points?", history)] == ["f1"]  # schema cue: points


def test_unproven_facts_go_alone_and_proven_facts_take_two_slots(db):
    m = memory(db)
    for i in range(3):
        m.add(fact(f"Finished fact number {'abc'[i]} about results.time."), 0)
    assert [f.id for f in m.select("Who finished?", [])] == ["f1"]  # unproven: one at most
    m.credit(["f2"], True, False)
    m.credit(["f3"], True, False)
    m.credit(["f2"], True, False)
    assert [f.id for f in m.select("Who finished?", [])] == ["f2", "f3"]  # proven first, up to two


def test_semantic_path_only_for_a_clear_proven_winner_in_scope(db):
    vec = {"q": [1, 0], "a": [1, 0.1], "b": [0, 1]}
    embed = lambda texts: np.array([vec["q"] if t.startswith("Name") else vec["a"] if "full" in t else vec["b"]
                                    for t in texts], float)
    m = memory(db, embed)
    m.add(fact("The full name of a driver comes from results.driverId lookups.", "results.driverId", phrases=["full name"]), 0)
    m.add(fact("Points are summed per race in results.points.", "results.points", phrases=["total points"]), 0)
    question = "Name each driver with results in 2010."
    assert m.select(question, []) == []  # no phrase match, and f1 is not proven yet
    m.credit(["f1"], True, False)
    assert [f.id for f in m.select(question, [])] == ["f1"]
    assert m.select("Name each person.", []) == []  # clear winner, but its table and column are not in the question


def test_retirement_rules(db):
    m = memory(db)
    for i in range(3):
        m.add(fact(f"Finished fact {'xyz'[i]} on results.time."), 0)
    m.credit(["f1"], facts_ok=False, none_ok=True)
    assert m.state["f1"]["retired"] == "regression while unproven"
    m.credit(["f2"], True, False)  # a fix: f2 is proven from now on
    m.credit(["f2"], False, True)
    m.credit(["f2"], False, True)
    assert m.state["f2"]["retired"] is None
    m.credit(["f2"], False, True)
    assert m.state["f2"]["retired"] == "score fell to -2"
    for _ in range(5):
        m.credit(["f3"], True, True)
    assert m.state["f3"]["retired"] == "no effect in 5 uses"


def test_precheck_rejects_on_any_regression_and_counts_fixes(db):
    m = memory(db)
    q = lambda i: Question(i, "f1", f"Which drivers finished race {i}?", "SELECT 1", "simple")
    earlier = [(q(1), False), (q(2), True), (q(3), False), (Question(4, "f1", "Oldest race?", "", "simple"), True)]
    new = fact("A driver finished when results.time has a value.")
    passing = lambda f, eq: True
    assert m.precheck(new, earlier, passing) == ("passed", 1, [2, 3])  # the last 2 matches; q3 fixed, q2 kept
    failing = lambda f, eq: eq.qid != 2
    assert m.precheck(new, earlier, failing)[0] == "rejected"  # q2 was right without the fact
    assert m.precheck(new, earlier[3:], passing) == ("unmatched", 0, [])
