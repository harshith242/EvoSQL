import json

import numpy as np
import pytest

from conftest import RULES, FakeJev, make_db
from evosql.bird import Question
from evosql.consolidate import consolidate, parse_edits
from evosql.facts import Fact
from evosql.memory import FactMemory

GOLD = "SELECT COUNT(*) FROM results WHERE time IS NOT NULL"


class FakeLLM:
    """Replies with one canned JSON object and records the prompts."""

    def __init__(self, reply):
        self.reply, self.prompts = reply, []

    def chat(self, messages, tools=None):
        self.prompts.append(messages[0]["content"])
        return {"content": json.dumps(self.reply)}


def statement(text, snippet=None):
    return {"kind": "mapping", "subject": "results.time", "statement": text, "applies_to": ["finished"],
            "values": [], "probe": None, "snippet": snippet}


def edit(op, ids, fact=None):
    return {"op": op, "ids": ids, "reason": "test", "fact": fact}


@pytest.fixture
def memory(tmp_path):
    db = make_db(tmp_path, "f1", "CREATE TABLE results (raceId INTEGER, driverId INTEGER, time TEXT); "
                                 "INSERT INTO results VALUES (1, 1, '1:30'), (1, 2, NULL), (1, 3, '1:31');")
    m = FactMemory(db, FakeJev(lambda state, key: 3.0), lambda texts: np.ones((len(texts), 2)), RULES, "f1 (test)")
    for i, none_ok in [(1, True), (2, False), (3, False)]:
        m.observe(Question(i, "f1", f"How many drivers finished race {i}?", GOLD), none_ok)
    return m


def add(memory, text, qid, score):
    fact = Fact("", "mapping", "results.time", text, ["finished"], None, [qid],
                learned_from=f"Who finished race {qid}?")
    memory.admit(fact, None)
    memory.state[fact.id].update(score=score, best=score, uses=score)
    return fact


def run(memory, reply, ok=lambda fact, q: True):
    return consolidate(FakeLLM(reply), memory, lambda q: [(2,)], ok)


def test_generalize_keeps_the_id_and_score_and_replaces_the_text(memory):
    add(memory, "A Korean driver finished when results.time has a value.", 1, 3)
    wider = statement("A driver of any nationality finished when results.time has a value.")

    [record] = run(memory, {"edits": [edit("generalize", ["f1"], wider)]})

    assert record["applied"] and record["id"] == "f1" and record["outcome"] == "pre-check passed"
    assert memory.facts["f1"].fact == wider["statement"] and memory.facts["f1"].source_qids == [1]
    assert memory.state["f1"]["score"] == 3 and memory.facts["f1"].learned_from == "Who finished race 1?"


def test_merge_makes_a_new_fact_with_the_best_score_and_retires_the_old_ones(memory):
    add(memory, "A driver finished when results.time has a value.", 1, 1)
    add(memory, "Finishing means results.time is not empty.", 2, 3)
    merged = statement("A driver finished exactly when results.time is not null.")

    [record] = run(memory, {"edits": [edit("merge", ["f1", "f2"], merged)]})

    assert record["applied"] and record["id"] == "f3" and record["fact"]["id"] == "f3"
    assert memory.state["f3"] == {"score": 3, "best": 3, "uses": 3, "retired": None}
    assert memory.facts["f3"].source_qids == [1, 2]
    assert [memory.state[i]["retired"] for i in ("f1", "f2")] == ["consolidated into f3"] * 2
    assert [f.id for f in memory.active()] == ["f3"]


def test_an_edit_that_regresses_a_question_is_not_applied(memory):
    add(memory, "A Korean driver finished when results.time has a value.", 2, 3)
    wider = statement("A driver finished when results.time has a value.")

    [record] = run(memory, {"edits": [edit("generalize", ["f1"], wider)]}, ok=lambda fact, q: q.qid != 1)

    assert not record["applied"] and record["outcome"] == "pre-check rejected"
    assert memory.facts["f1"].fact.startswith("A Korean") and memory.state["f1"]["retired"] is None


def test_a_new_fact_that_fails_the_admission_checks_is_rejected_and_a_bad_snippet_is_dropped(memory):
    add(memory, "A Korean driver finished when results.time has a value.", 1, 3)
    with_sql = statement("Use WHERE results.time IS NOT NULL to find finishers.")
    [record] = run(memory, {"edits": [edit("generalize", ["f1"], with_sql)]})
    assert record["applied"] is False and record["rejected"] == "contains SQL"

    bad_snippet = {"table": "results", "form": "predicate", "sql": "results.raceId = 1"}  # raceId is not in the gold
    wider = statement("A driver finished when results.time has a value.", bad_snippet)
    [record] = run(memory, {"edits": [edit("generalize", ["f1"], wider)]})
    assert record["applied"] and record["snippet"] == "dropped" and memory.facts["f1"].sql is None


def test_drop_retires_the_fact_and_an_empty_memory_asks_nothing(memory):
    llm = FakeLLM({"edits": []})
    assert consolidate(llm, memory, lambda q: [(2,)], None) == [] and llm.prompts == []

    add(memory, "A Korean driver finished when results.time has a value.", 1, 3)
    [record] = run(memory, {"edits": [edit("drop", ["f1"])]})

    assert record["applied"] and record["fact"] is None
    assert memory.state["f1"]["retired"] == "dropped by consolidation" and memory.active() == []


def test_parse_edits_drops_unknown_ids_wrong_arity_and_reused_ids():
    fact = statement("A driver finished when results.time has a value.")
    reply = {"edits": [
        edit("generalize", ["f9"], fact),  # unknown id leaves no ids
        edit("merge", ["f1"], fact),  # a merge needs 2 ids
        edit("generalize", ["f1", "f2"], fact),  # a generalize takes exactly 1
        edit("merge", ["f1", "f2"], fact),
        edit("drop", ["f2"]),  # f2 is already used
        edit("generalize", ["f3"]),  # no fact
        edit("rename", ["f3"], fact),  # unknown op
        edit("drop", ["f3"]),
    ]}

    edits = parse_edits(reply, {"f1", "f2", "f3"})

    assert [(e["op"], e["ids"]) for e in edits] == [("merge", ["f1", "f2"]), ("drop", ["f3"])]
    assert isinstance(edits[0]["fact"], Fact) and edits[1]["fact"] is None

    ids = [f"f{i}" for i in range(1, 8)]
    assert len(parse_edits({"edits": [edit("drop", [i]) for i in ids]}, set(ids))) == 5  # at most 5 edits
