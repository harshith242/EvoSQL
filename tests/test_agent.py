import json
import sqlite3

import pytest

from evosql.agent import answer, answer_self_consistent
from evosql.bird import open_db
from evosql.knowledge import Edit, Knowledge


def call(name, **args):
    return {"content": None, "tool_calls": [{"id": f"c_{name}", "name": name, "arguments": json.dumps(args)}],
            "model": "fake", "prompt_tokens": 1, "completion_tokens": 1}


def text(content):
    return {"content": content, "tool_calls": [], "model": "fake", "prompt_tokens": 1, "completion_tokens": 1}


class FakeLLM:
    """Replays a scripted list of replies per sample index and records the messages it saw."""

    def __init__(self, scripts):
        self.scripts = {k: list(v) for k, v in scripts.items()}
        self.seen, self.history = [], []

    def chat(self, messages, tools=None, temperature=0.0, sample=0):
        self.seen.append(messages[-1])
        self.history.append([dict(m) for m in messages])
        return self.scripts[sample].pop(0)


@pytest.fixture
def db(tmp_path):
    d = tmp_path / "toy"
    d.mkdir()
    con = sqlite3.connect(d / "toy.sqlite")
    con.execute("CREATE TABLE patient (id INTEGER, sex TEXT)")
    con.executemany("INSERT INTO patient VALUES (?, ?)", [(1, "F"), (2, "M"), (3, "F")])
    con.commit()
    con.close()
    return open_db(tmp_path, "toy", with_docs=False)


def test_tool_result_is_fed_back_then_submit_returns_sql(db):
    llm = FakeLLM({0: [call("run_sql", sql="SELECT COUNT(*) FROM patient"), call("submit", sql="SELECT 3")]})
    result = answer(llm, db, "How many patients?", Knowledge())
    assert result.sql == "SELECT 3" and result.steps == 2
    assert llm.seen[1]["role"] == "tool" and llm.seen[1]["content"] == "3"


def test_json_in_text_is_used_when_model_skips_native_tools(db):
    llm = FakeLLM({0: [text('Sure: {"tool": "submit", "args": {"sql": "SELECT id FROM patient"}}')]})
    assert answer(llm, db, "ids?", Knowledge()).sql == "SELECT id FROM patient"


def test_no_submit_within_step_limit_gives_no_sql(db):
    llm = FakeLLM({0: [text("thinking...")] * 3})
    result = answer(llm, db, "ids?", Knowledge(), max_steps=3)
    assert result.sql is None and result.error
    assert "submit now" in llm.seen[-1]["content"]


def test_self_consistency_picks_most_common_result_not_most_common_sql(db):
    llm = FakeLLM({
        0: [call("submit", sql="SELECT id FROM patient WHERE sex = 'F'")],
        1: [call("submit", sql="SELECT id FROM patient WHERE sex = 'M'")],
        2: [call("submit", sql="SELECT id FROM patient WHERE id IN (1, 3)")],
    })
    result = answer_self_consistent(llm, db, "female ids?", Knowledge(), n=3)
    assert result.sql == "SELECT id FROM patient WHERE sex = 'F'"


def test_non_dict_tool_arguments_do_not_crash_the_run(db):
    bad = call("submit")
    bad["tool_calls"][0]["arguments"] = "null"
    result = answer(FakeLLM({0: [bad]}), db, "ids?", Knowledge())
    assert result.sql is None


def test_thinking_reasoning_is_sent_back_with_the_tool_call(db):
    first = call("run_sql", sql="SELECT 1")
    first["reasoning"] = "count the rows first"
    llm = FakeLLM({0: [first, call("submit", sql="SELECT 1")]})
    answer(llm, db, "q?", Knowledge())
    assistant = [m for m in llm.history[-1] if m["role"] == "assistant"][0]
    assert assistant["reasoning_content"] == "count the rows first"


def test_value_profile_goes_between_schema_and_notes(db):
    db.profile = "Database value profile (computed from the data):\n- patient.sex TEXT: 'F' 2"
    k, _ = Knowledge().apply(Edit("add", when="women", text="use sex = 'F'"), 1, 1)
    llm = FakeLLM({0: [call("submit", sql="SELECT 1")]})
    answer(llm, db, "q?", k)
    system = llm.history[-1][0]["content"]
    assert system.index("CREATE TABLE") < system.index("value profile") < system.index("Learned notes")
