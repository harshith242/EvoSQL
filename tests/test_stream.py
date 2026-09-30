import json

import numpy as np

from conftest import RULES, make_db
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
        return {"content": json.dumps({"kind": "mapping", "subject": "results.time", "fact": FACT,
                                       "applies_to": ["finished"], "values": [], "probe": None})}


def stream(tmp_path, monkeypatch, can_precheck):
    monkeypatch.chdir(tmp_path)  # gold rows are cached under ./cache
    db = make_db(tmp_path, "f1", "CREATE TABLE results (raceId INTEGER, driverId INTEGER, time TEXT); "
                                 "INSERT INTO results VALUES (1, 1, '1:30'), (1, 2, NULL), (1, 3, '1:31');")
    order = [Question(i, "f1", f"How many drivers finished race {i}?", GOLD) for i in (1, 2, 3)]
    memory = FactMemory(db, lambda texts: np.ones((len(texts), 2)), RULES)
    agent = Agent()
    run_stream(db, order, Answers(agent, 3), Proposer(), memory, can_precheck, tmp_path / "log.jsonl")
    return [json.loads(line) for line in open(tmp_path / "log.jsonl")], memory, agent


def test_a_fact_is_learned_after_its_question_and_helps_the_next_one(tmp_path, monkeypatch):
    recs, memory, agent = stream(tmp_path, monkeypatch, lambda: True)
    first, second = recs[0], recs[1]
    assert first["injected"] == [] and not first["facts_ok"]  # a question never sees the fact learned from it
    assert first["learning"]["outcome"] == "pre-check unmatched"  # no earlier question to check against
    assert second["injected"] == ["f1"] and second["facts_ok"] and not second["none_ok"]
    assert memory.state["f1"]["score"] == 2  # fixed questions 2 and 3
    # With nothing injected, the facts arm replays the none arm's answer instead of asking again: 1 + 2 + 2 calls.
    assert agent.usage["calls"] == 5 and first["usage"]["facts"] == {}


def test_the_precheck_follows_the_budget_rule_it_is_given(tmp_path, monkeypatch):
    recs, _, _ = stream(tmp_path, monkeypatch, lambda: False)
    assert recs[0]["learning"]["outcome"] == "added unproven (pre-check skipped: order budget)"
