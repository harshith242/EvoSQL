import hashlib
import json

import numpy as np
import pytest

from conftest import RULES, FakeJev, make_db
from evosql.bird import Question
from evosql.facts import Fact
from evosql.probe import check_probe, load_facts, run_items
from evosql.search import examples_notes, similar
from evosql.stream import Answers

GOLD = "SELECT COUNT(*) FROM results WHERE time IS NOT NULL"
FACT = "A driver finished a race when results.time has a value, even when lapped."
SNIPPET = "results.time IS NOT NULL"


class Agent:
    """Right only when the v7 fact or the similar-examples section is in the system prompt; records every prompt."""

    def __init__(self):
        self.usage = {"calls": 0}
        self.prompts = []

    def chat(self, messages, tools=None):
        self.usage["calls"] += 1
        self.prompts.append(messages[0]["content"])
        right = FACT in messages[0]["content"] or "Similar past questions" in messages[0]["content"]
        sql = GOLD if right else "SELECT COUNT(*) FROM results"
        return {"content": None, "reasoning": None, "tool_calls": [
            {"id": "c", "name": "submit", "arguments": json.dumps({"sql": sql})}]}


def embed(texts):
    """Two directions: questions about finishing, and anything else."""
    return np.array([[1.0, 0.1] if "finished" in t else [0.0, 1.0] for t in texts])


def fact(text, sql=None):
    return Fact(id="f1", kind="mapping", subject="results.time", fact=text, applies_to=["finished"],
                learned_from="How many drivers finished race 1?", sql=sql)


def test_every_item_is_answered_in_five_arms_and_only_v7_sql_sees_the_snippet(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)  # gold rows are cached under ./cache
    db = make_db(tmp_path, "f1", "CREATE TABLE results (raceId INTEGER, driverId INTEGER, time TEXT); "
                                 "INSERT INTO results VALUES (1, 1, '1:30'), (1, 2, NULL), (1, 3, '1:31');")
    sql = {"table": "results", "form": "predicate", "sql": SNIPPET}
    with_sql, prose = fact(FACT, sql), fact(FACT)
    memories = {"v6_facts": {"f1": ([fact("Another rule.")], {"f1"})},
                "v7_prose": {"f1": ([prose], {"f1"})}, "v7_sql": {"f1": ([with_sql], {"f1"})}}
    past = {"f1": [Question(1, "f1", "How many drivers finished race 1?", "SELECT 1"),
                   Question(2, "f1", "Who won the Monaco race?", "SELECT 2"),
                   Question(3, "f1", "How many drivers finished race 2?", "SELECT 3")]}
    items = [{"id": "p07", "db_id": "f1", "level": "paraphrase", "source_qid": 1,
              "question": "How many drivers finished race 9?", "gold_sql": GOLD}]

    agent = Agent()
    log = tmp_path / "probe.jsonl"
    run_items(items, {"f1": db}, Answers(agent, 3), FakeJev(lambda state, key: 3.0), embed, memories, past, RULES,
              {"f1": "test"}, log)

    [rec] = [json.loads(line) for line in open(log)]
    assert list(rec["arms"]) == ["none", "v6_facts", "v7_prose", "v7_sql", "examples"]
    assert {arm: a["ok"] for arm, a in rec["arms"].items()} == {
        "none": False, "v6_facts": False, "v7_prose": True, "v7_sql": True, "examples": True}
    assert rec["arms"]["v7_sql"]["injected"] == rec["arms"]["v7_prose"]["injected"] == ["f1"]
    assert (rec["id"], rec["level"], rec["source_qid"]) == ("p07", "paraphrase", 1)

    assert sum(SNIPPET in p for p in agent.prompts) == 1  # only the v7_sql prompt has the snippet
    similar = next(p for p in agent.prompts if "Similar past questions" in p)
    assert "SQL: SELECT 1" in similar and "SQL: SELECT 3" in similar and "SELECT 2" not in similar


def test_examples_are_the_most_similar_past_questions_best_first():
    past = [Question(1, "f1", "Who won the Monaco race?", "SELECT 1"),
            Question(2, "f1", "How many drivers finished race 1?", "SELECT 2")]
    text = examples_notes(similar(embed, "How many drivers finished race 9?", past, 1))
    assert text == "Similar past questions with their correct SQL:\nQ: How many drivers finished race 1?\nSQL: SELECT 2"


def test_load_facts_skips_retired_fills_learned_from_and_lists_proven_ids(tmp_path):
    base = {"kind": "mapping", "subject": "results.time", "applies_to": ["finished"], "probe": None,
            "values": [], "best": 1, "uses": 3}
    saved = [{**base, "id": "f1", "fact": "v6 style", "source_qids": [7], "score": 2, "retired": None},
             {**base, "id": "f2", "fact": "gone", "source_qids": [8], "score": -2, "retired": "score fell to -2"},
             {**base, "id": "f3", "fact": "new", "source_qids": [9], "score": 0, "retired": None,
              "learned_from": "Own question?", "sql": {"table": "results", "form": "predicate", "sql": SNIPPET}}]
    path = tmp_path / "facts.json"
    path.write_text(json.dumps(saved))

    facts, proven_ids = load_facts(path, {7: "Question seven?", 9: "ignored"})

    assert [f.id for f in facts] == ["f1", "f3"]
    assert [f.learned_from for f in facts] == ["Question seven?", "Own question?"]
    assert facts[0].sql is None and facts[1].sql["sql"] == SNIPPET
    assert proven_ids == {"f1"}


def test_a_changed_probe_file_stops_the_run(tmp_path):
    probe = tmp_path / "probe_v7.json"
    probe.write_text("[]")
    manifest = tmp_path / "manifest.json"

    manifest.write_text(json.dumps({"sha256": hashlib.sha256(b"[]").hexdigest()}))
    check_probe(probe)

    manifest.write_text(json.dumps({"sha256": hashlib.sha256(b"[1]").hexdigest()}))
    with pytest.raises(SystemExit, match="frozen"):
        check_probe(probe)
