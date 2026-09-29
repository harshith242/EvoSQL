import json
import sqlite3

import pytest

from evosql.bird import Question
from evosql.evaluate import run_test, selfcons_n, twins, where_columns
from evosql.llm import ProviderExhausted

NAMES = ["ID", "SEX", "UN", "Admission", "Birthday", "CRE"]
GOLD = "SELECT COUNT(*) FROM Patient WHERE SEX = 'F'"


def test_where_columns_finds_filters_not_selected_columns():
    sql = ("SELECT T1.SEX, T2.UN FROM Patient T1 JOIN Laboratory T2 ON T1.ID = T2.ID "
           "WHERE T2.UN = 29 AND T1.Admission = '+' ORDER BY T1.Birthday")
    assert where_columns(sql, NAMES) == {"UN", "Admission"}


def test_twins_are_test_questions_sharing_a_filter_column_with_learning():
    learn = [Question(1, "t", "q", "SELECT ID FROM Laboratory WHERE UN = 29", "simple", "")]
    test = [Question(2, "t", "q", "SELECT SEX FROM Patient T1 JOIN Laboratory T2 WHERE T2.UN > 30", "simple", ""),
            Question(3, "t", "q", "SELECT SEX FROM Laboratory WHERE CRE >= 1.5", "simple", "")]
    assert twins(learn, test, NAMES) == {2}


class FakeAgent:
    """Submits the gold SQL; raises like a provider limit on the given call."""

    def __init__(self, crash_at=None):
        self.calls, self.crash_at = 0, crash_at
        self.usage = {"calls": 0, "prompt_tokens": 0, "completion_tokens": 0}
        self.fresh = {"prompt_tokens": 0, "completion_tokens": 0, "provider_cached_tokens": 0}

    def chat(self, messages, tools=None, temperature=0.0, sample=0):
        self.calls += 1
        if self.calls == self.crash_at:
            raise ProviderExhausted("limit")
        self.usage["calls"] += 1
        return {"content": None, "reasoning": None, "model": "fake", "prompt_tokens": 1, "completion_tokens": 1,
                "tool_calls": [{"id": "c", "name": "submit", "arguments": json.dumps({"sql": GOLD})}]}


@pytest.fixture
def cfg(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)  # gold results cache under ./cache; keep it out of the repo
    (tmp_path / "data" / "toy").mkdir(parents=True)
    con = sqlite3.connect(tmp_path / "data" / "toy" / "toy.sqlite")
    con.execute("CREATE TABLE Patient (ID INTEGER, SEX TEXT)")
    con.executemany("INSERT INTO Patient VALUES (?, ?)", [(1, "F"), (2, "M")])
    con.commit()
    con.close()
    dev = [{"question_id": i, "db_id": "toy", "question": f"women? {i}", "SQL": GOLD, "difficulty": "simple",
            "evidence": ""} for i in range(6)]
    (tmp_path / "data" / "dev.json").write_text(json.dumps(dev))
    (tmp_path / "runs").mkdir()
    (tmp_path / "runs" / "split.json").write_text(json.dumps({"learn": [0, 1, 2], "test": [3, 4, 5]}))
    prices = {"cache_hit": 0.0, "cache_miss": 1.0, "output": 0.0}
    return {"data_dir": str(tmp_path / "data"), "db": "toy", "runs_dir": str(tmp_path / "runs"),
            "cache_dir": str(tmp_path / "cache"), "max_steps": 2,
            "agent": {"usd_per_million": prices}, "proposer": {"usd_per_million": prices},
            "v3": {"n_test": 3, "budget_usd": 1.0, "selfcons_max_n": 5}}


def test_run_test_resumes_without_duplicates(cfg):
    assert run_test(cfg, "docs", agent_llm=FakeAgent(crash_at=2)) is False
    assert run_test(cfg, "docs", agent_llm=FakeAgent())
    lines = [json.loads(line) for line in open(f"{cfg['runs_dir']}/test_docs.jsonl")]
    assert [r["qid"] for r in lines] == [3, 4, 5] and all(r["correct"] for r in lines)


def test_selfcons_n_matches_evosql_spend_per_test_question_and_is_capped(cfg):
    runs = cfg["runs_dir"]
    # docs: 1M prompt tokens per question at $1/M; evosql test the same; learning $6 in total.
    record = lambda qid: json.dumps({"qid": qid, "correct": True, "usage": {"prompt_tokens": 1_000_000}})
    for arm in ("docs", "evosql"):
        open(f"{runs}/test_{arm}.jsonl", "w").write("\n".join(record(q) for q in (3, 4, 5)) + "\n")
    learn = {"usage": {"agent": {"prompt_tokens": 6_000_000}, "proposer": {"prompt_tokens": 0}}}
    open(f"{runs}/learn.jsonl", "w").write(json.dumps(learn) + "\n")
    assert selfcons_n(cfg) == 3  # (6 + 3) / 3 test questions = $3 per question vs docs $1
    learn["usage"]["agent"]["prompt_tokens"] = 60_000_000
    open(f"{runs}/learn.jsonl", "w").write(json.dumps(learn) + "\n")
    assert selfcons_n(cfg) == 5  # capped
