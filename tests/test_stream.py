import json
import sqlite3

import numpy as np

from evosql.bird import Question, open_db
from evosql.budget import Budget
from evosql.memory import FactMemory
from evosql.stream import run_stream
from test_memory import RULES

GOLD = "SELECT COUNT(*) FROM results WHERE time IS NOT NULL"
FACT = "A driver finished a race when results.time has a value, even when lapped."


class Agent:
    """Right only when the learned fact is in the system prompt; counts calls."""

    def __init__(self):
        self.usage, self.calls = {"calls": 0}, 0

    def chat(self, messages, tools=None, temperature=0.0, sample=0):
        self.calls += 1
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


def setup(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)  # gold rows are cached under ./cache
    (tmp_path / "f1").mkdir()
    con = sqlite3.connect(tmp_path / "f1" / "f1.sqlite")
    con.execute("CREATE TABLE results (raceId INTEGER, driverId INTEGER, time TEXT)")
    con.executemany("INSERT INTO results VALUES (?, ?, ?)", [(1, 1, "1:30"), (1, 2, None), (1, 3, "1:31")])
    con.commit()
    con.close()
    db = open_db(tmp_path, "f1")
    qs = [Question(i, "f1", f"How many drivers finished race {i}?", GOLD, "simple") for i in (1, 2, 3)]
    return db, qs, FactMemory(db, lambda texts: np.ones((len(texts), 2)), RULES)


def test_a_fact_is_learned_after_its_question_and_helps_the_next_one(tmp_path, monkeypatch):
    db, qs, memory = setup(tmp_path, monkeypatch)
    log = tmp_path / "stream.jsonl"
    run_stream(db, qs, 0, Agent(), Proposer(), memory, Budget(tmp_path / "spend.json", 1.0), 0.9, 3, log)
    recs = [json.loads(line) for line in open(log)]
    first, second = recs[0], recs[1]
    assert first["injected"] == [] and not first["facts_ok"]  # a question never sees the fact learned from it
    assert first["learning"]["outcome"] == "pre-check unmatched"  # no earlier question to check against
    assert second["injected"] == ["f1"] and second["facts_ok"] and not second["none_ok"]
    assert memory.state["f1"]["proven"] and memory.state["f1"]["score"] == 2  # fixed questions 2 and 3


def test_precheck_is_skipped_once_the_order_budget_is_nearly_spent(tmp_path, monkeypatch):
    db, qs, memory = setup(tmp_path, monkeypatch)
    budget = Budget(tmp_path / "spend.json", 5.0)
    budget.total = 0.95  # past this order's pre-check limit of 0.9
    log = tmp_path / "stream.jsonl"
    run_stream(db, qs, 0, Agent(), Proposer(), memory, budget, 0.9, 3, log)
    first = json.loads(open(log).readline())
    assert first["learning"]["outcome"] == "added unproven (pre-check skipped: order budget)"
