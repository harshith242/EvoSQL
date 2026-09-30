import numpy as np
import pytest

from conftest import RULES, FakeJev, make_db
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
    return Fact("", kind, subject, text, list(phrases), None, [1], [], learned_from="Who finished race 1?")


def memory(db, score=lambda state, key: 0.0, embed=None, rules=RULES):
    embed = embed or (lambda texts: np.ones((len(texts), 2)))
    return FactMemory(db, FakeJev(score), embed, rules, "f1 (racing)")


def add(memory, new_fact):
    memory.admit(new_fact, lambda _fact, _question: False)
    return new_fact


def by_key(scores):
    """A JEV score function that looks each score up by the question key (a fact or question id)."""
    return lambda state, key: scores[key]


def test_only_facts_at_the_cutoff_are_picked_best_first_and_at_most_two(db):
    m = memory(db, by_key({"f1": 2.5, "f2": 2.75, "f3": 3.0, "f4": 2.9}))
    facts = [add(m, fact(f"Finished fact {name} about results.time.")) for name in "abcd"]
    for f in facts:
        m.credit([f.id], True, False)

    picked, scores = m.select("Who finished?")
    assert [f.id for f in picked] == ["f3", "f4"]
    assert scores == {"f1": 2.5, "f2": 2.75, "f3": 3.0, "f4": 2.9}
    assert m.jev.calls[0][0]["database"] == "f1 (racing)" and len(m.jev.calls) == 1


def test_an_unproven_fact_goes_alone_and_proven_facts_share_the_prompt(db):
    m = memory(db, lambda state, key: 3.0)
    facts = [add(m, fact(f"Finished fact {name} about results.time.")) for name in "abc"]

    assert [f.id for f in m.select("Who finished?")[0]] == ["f1"]
    m.credit([facts[1].id], True, False)
    m.credit([facts[2].id], True, False)
    assert [f.id for f in m.select("Who finished?")[0]] == ["f2", "f3"]


def test_ties_go_to_the_higher_memory_score(db):
    m = memory(db, lambda state, key: 3.0)
    facts = [add(m, fact(f"Finished fact {name} about results.time.")) for name in "abc"]
    for f, delta in zip(facts, (1, 3, 2)):
        for _ in range(delta):
            m.credit([f.id], True, False)

    assert [f.id for f in m.select("Who finished?")[0]] == ["f2", "f3"]


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


def test_matches_are_the_embedding_shortlist_that_jev_scores_at_the_cutoff(db):
    # JEV finds 3.0 for questions 2 and 3, 1.0 for question 1; question 4 is too far to be shortlisted.
    jev_scores = {"q1": 1.0, "q2": 3.0, "q3": 3.0, "q4": 3.0}
    vec = {"Oldest race?": [0, 1]}
    embed = lambda texts: np.array([vec.get(t, [1, 0]) for t in texts], float)
    m = memory(db, by_key(jev_scores), embed, dict(RULES, precheck_pool=3))
    for i, none_ok in [(1, False), (2, True), (3, False)]:
        m.observe(Question(i, "f1", f"Which drivers finished race {i}?", ""), none_ok)
    m.observe(Question(4, "f1", "Oldest race?", ""), True)

    assert [(q.qid, ok) for q, ok in m.matches(fact("A driver finished."))] == [(2, True), (3, False)]
    assert [k for k in m.jev.calls[0][1]] == ["q1", "q2", "q3"]
    assert memory(db).matches(fact("A driver finished.")) == []


def test_precheck_rejects_on_any_regression_and_counts_fixes(db):
    def pairs(m):
        return [(Question(i, "f1", f"Which drivers finished race {i}?", ""), ok) for i, ok in [(2, True), (3, False)]]

    m = memory(db)
    record, fixes = m.precheck(fact("A driver finished."), pairs(m), lambda _fact, _q: True)
    assert record == {"outcome": "pre-check passed", "checked": [2, 3], "fixes": 1} and fixes == 1

    record, _ = m.precheck(fact("A driver finished."), pairs(m), lambda _fact, q: q.qid != 2)
    assert record["outcome"] == "pre-check rejected" and record["fixes"] == 0

    record, _ = m.precheck(fact("A driver finished."), [], lambda _fact, _q: True)
    assert record["outcome"] == "pre-check unmatched"


def test_admit_rejects_a_fact_that_regresses_a_matched_question(db):
    m = memory(db, lambda state, key: 3.0)
    m.observe(Question(1, "f1", "Which drivers finished race 1?", ""), True)

    assert m.admit(fact("A driver finished."), lambda _fact, _q: False)["outcome"] == "pre-check rejected"
    assert m.facts == {}
    assert m.admit(fact("A driver finished."), lambda _fact, _q: True)["outcome"] == "pre-check passed"
    assert m.admit(fact("Another finished."), None)["outcome"] == "added unproven (pre-check skipped: budget)"


def test_admit_records_duplicates_and_merge_conflicts(db):
    m = memory(db)
    first = add(m, fact("A driver finished when results.time has a value."))
    assert m.admit(fact("a driver finished when results.time has a value"), None)["merge"] == "merged into f1"
    # "finished" now maps to two columns with equal support: both facts lose it and, left without phrases, drop.
    record = m.admit(fact("A driver finished when results.points is above zero.", "results.points"), None)
    assert record["conflicts"][0]["phrase"] == "finished" and record["merge"].startswith("dropped")
    assert m.state[first.id]["retired"] == "removed by a merge conflict" and m.active() == []
