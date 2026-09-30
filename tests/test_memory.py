import numpy as np
import pytest

from conftest import RULES, make_db
from evosql.bird import Question
from evosql.facts import Fact
from evosql.memory import FactMemory



@pytest.fixture
def db(tmp_path):
    return make_db(tmp_path, "f1", """
        CREATE TABLE races (raceId INTEGER, name TEXT, year INTEGER);
        CREATE TABLE results (raceId INTEGER, driverId INTEGER, time TEXT, points REAL);
    """, notes={"results": {"time": "finish time of the driver"}})


def fact(text, subject="results.time", kind="mapping", phrases=("finished",)):
    return Fact("", kind, subject, text, list(phrases), None, [1], [])


def memory(db, embed=None):
    return FactMemory(db, embed or (lambda texts: np.ones((len(texts), 2))), RULES)


def add(memory, new_fact):
    memory.admit(new_fact, lambda _fact, _question: False)
    return new_fact


def test_phrase_path_is_word_bounded_and_structural_facts_need_schema_scope(db):
    m = memory(db)
    add(m, fact("A driver finished when results.time has a value."))
    add(m, fact("Patient age is computed from the birth year in races.year.", "races.year", "meaning", ["age"]))
    add(m, fact("One results row is one driver in one race.", "results", "grain", ["how many drivers"]))

    assert [f.id for f in m.select("Which drivers finished race 5?")] == ["f1"]
    assert m.select("What is the average points?") == []
    assert m.select("How many drivers are there?") == []
    assert [f.id for f in m.select("How many drivers have results in 2009?")] == ["f3"]


def test_generic_trigger_needs_a_second_cue(db):
    m = memory(db)
    add(m, fact("A win means the highest results.points in a race.", "results.points", phrases=["win"]))
    for i in range(8):
        m.observe(Question(i, "f1", f"Which win number {i}?", "SELECT 1"), False)

    assert m.select("Which driver had a win?") == []
    assert [f.id for f in m.select("Which win gave the most points?")] == ["f1"]


def test_unproven_facts_go_alone_and_proven_facts_take_two_slots(db):
    m = memory(db)
    facts = [add(m, fact(f"Finished fact {name} about results.time.")) for name in "abc"]

    assert [f.id for f in m.select("Who finished?")] == ["f1"]
    m.credit([facts[1].id], True, False)
    m.credit([facts[2].id], True, False)
    assert [f.id for f in m.select("Who finished?")] == ["f2", "f3"]


def test_semantic_path_only_for_a_clear_proven_winner_in_scope(db):
    vec = {"q": [1, 0], "a": [1, 0.1], "b": [0, 1]}
    embed = lambda texts: np.array([vec["q"] if t.startswith("Name") else vec["a"] if "full" in t else vec["b"]
                                    for t in texts], float)
    m = memory(db, embed)
    first = add(m, fact("The full name of a driver comes from results.driverId lookups.", "results.driverId",
                        phrases=["full name"]))
    add(m, fact("Points are summed per race in results.points.", "results.points", phrases=["total points"]))

    question = "Name each driver with results in 2010."
    assert m.select(question) == []
    m.credit([first.id], True, False)
    assert [f.id for f in m.select(question)] == ["f1"]
    assert m.select("Name each person.") == []


def test_retirement_rules(db):
    m = memory(db)
    first, second, third = [add(m, fact(f"Finished fact {name} on results.time.")) for name in "xyz"]

    m.credit([first.id], facts_ok=False, none_ok=True)
    assert m.state[first.id]["retired"] == "regression while unproven"
    m.credit([second.id], True, False)
    for _ in range(3):
        m.credit([second.id], False, True)
    assert m.state[second.id]["retired"] == "score fell to -2"
    for _ in range(5):
        m.credit([third.id], True, True)
    assert m.state[third.id]["retired"] == "no effect in 5 uses"


def test_precheck_rejects_on_any_regression_and_counts_fixes(db):
    question = lambda i: Question(i, "f1", f"Which drivers finished race {i}?", "SELECT 1")
    earlier = [(question(1), False), (question(2), True), (question(3), False),
               (Question(4, "f1", "Oldest race?", ""), True)]

    passing = lambda _fact, _question: True
    m = memory(db)
    for q, none_ok in earlier:
        m.observe(q, none_ok)
    result = m.admit(fact("A driver finished when results.time has a value."), passing)
    assert result["outcome"] == "pre-check passed"
    assert result["fixes"] == 1 and result["checked"] == [2, 3]

    m = memory(db)
    for q, none_ok in earlier:
        m.observe(q, none_ok)
    result = m.admit(fact("A driver finished when results.time has a value."), lambda _fact, q: q.qid != 2)
    assert result["outcome"] == "pre-check rejected"

    m = memory(db)
    m.observe(earlier[-1][0], earlier[-1][1])
    result = m.admit(fact("A driver finished when results.time has a value."), passing)
    assert result["outcome"] == "pre-check unmatched"


def test_admit_records_duplicates_and_merge_conflicts(db):
    m = memory(db)
    first = add(m, fact("A driver finished when results.time has a value."))
    assert m.admit(fact("a driver finished when results.time has a value"), None)["merge"] == "merged into f1"
    # "finished" now maps to two columns with equal support: both facts lose it and, left without phrases, drop.
    record = m.admit(fact("A driver finished when results.points is above zero.", "results.points"), None)
    assert record["conflicts"][0]["phrase"] == "finished" and record["merge"].startswith("dropped")
    assert m.state[first.id]["retired"] == "removed by a merge conflict" and m.active() == []
