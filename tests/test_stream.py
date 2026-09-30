import json

import numpy as np

from conftest import RULES, FakeJev, make_db
from evosql.bird import Question
from evosql.memory import FactMemory
from evosql.stream import Answers, run_stream

GOLD = "SELECT COUNT(*) FROM results WHERE time IS NOT NULL"
FACT = "A driver finished a race when results.time has a value, even when lapped."


class Agent:
    """Right only when the learned fact is in the system prompt."""

    def __init__(self):
        self.usage = {"calls": 0}

    def chat(self, messages, tools=None):
        self.usage["calls"] += 1
        sql = GOLD if FACT in messages[0]["content"] else "SELECT COUNT(*) FROM results"
        return {"content": None, "reasoning": None, "tool_calls": [
            {"id": "c", "name": "submit", "arguments": json.dumps({"sql": sql})}]}


class Proposer:
    def __init__(self):
        self.usage = {"calls": 0}

    def chat(self, messages, tools=None):
        self.usage["calls"] += 1
        if "edits" in messages[0]["content"]:  # the consolidation prompt
            return {"content": json.dumps({"edits": []})}
        return {"content": json.dumps({"fact": {"kind": "mapping", "subject": "results.time", "statement": FACT,
                                                "applies_to": ["finished"], "values": [], "probe": None}})}


class PricedJev(FakeJev):
    """A JEV that charges $0.50 per call."""

    def decide(self, state, questions):
        self.usage["usd"] += 0.5
        return super().decide(state, questions)


def stream(tmp_path, monkeypatch, can_precheck):
    monkeypatch.chdir(tmp_path)  # gold rows are cached under ./cache
    db = make_db(tmp_path, "f1", "CREATE TABLE results (raceId INTEGER, driverId INTEGER, time TEXT); "
                                 "INSERT INTO results VALUES (1, 1, '1:30'), (1, 2, NULL), (1, 3, '1:31');")
    order = [Question(i, "f1", f"How many drivers finished race {i}?", GOLD) for i in (1, 2, 3)]
    jev = PricedJev(lambda state, key: 3.0)
    memory = FactMemory(db, jev, lambda texts: np.ones((len(texts), 2)), RULES, "f1 (test)")
    agent = Agent()
    run_stream(db, order, Answers(agent, 3), Proposer(), memory, can_precheck, tmp_path / "log.jsonl",
               tmp_path / "consolidation.jsonl", 2)
    read = lambda name: [json.loads(line) for line in open(tmp_path / name)]
    return read("log.jsonl"), read("consolidation.jsonl"), memory, agent


def test_a_fact_is_learned_after_its_question_and_helps_the_next_one(tmp_path, monkeypatch):
    recs, _, memory, agent = stream(tmp_path, monkeypatch, lambda: True)
    first, second = recs[0], recs[1]
    assert first["injected"] == [] and not first["facts_ok"]  # a question never sees the fact learned from it
    assert first["learning"]["outcome"] == "pre-check unmatched"  # no earlier question to check against
    assert second["injected"] == ["f1"] and second["facts_ok"] and not second["none_ok"]
    assert memory.state["f1"]["score"] == 2  # fixed questions 2 and 3
    # With nothing injected, the facts arm replays the none arm's answer instead of asking again: 1 + 2 + 2 calls.
    assert agent.usage["calls"] == 5 and first["usage"]["facts"] == {}


def test_the_precheck_follows_the_budget_rule_it_is_given(tmp_path, monkeypatch):
    recs, passes, _, _ = stream(tmp_path, monkeypatch, lambda: False)
    assert recs[0]["learning"]["outcome"] == "added unproven (pre-check skipped: budget)"
    assert passes == [{"after_pos": 2, "skipped": "budget"}, {"after_pos": 3, "skipped": "budget"}]


def test_consolidation_runs_every_n_questions_and_once_at_the_end(tmp_path, monkeypatch):
    _, passes, _, _ = stream(tmp_path, monkeypatch, lambda: True)
    assert [p["after_pos"] for p in passes] == [2, 3]
    assert passes[0]["edits"] == [] and passes[0]["usage"]["proposer"] == {"calls": 1} and passes[0]["jev_usd"] == 0


def test_each_question_logs_its_jev_cost_and_scores(tmp_path, monkeypatch):
    recs, _, _, _ = stream(tmp_path, monkeypatch, lambda: True)
    assert [r["jev_usd"] for r in recs] == [0, 0.5, 0.5]  # no fact to score for question 1
    assert [r["jev_scores"] for r in recs] == [{}, {"f1": 3.0}, {"f1": 3.0}]
