import json
import sqlite3

import pytest

from evosql.bird import Question
from evosql.bird import open_db
import numpy as np

from evosql.evaluate import bootstrap_ci, mcnemar, relevant, run_test, selfcons_n, sql_columns
from evosql.facts import Fact, FactBook
from evosql.llm import ProviderExhausted

NAMES = ["ID", "SEX", "UN", "Admission", "Birthday", "CRE", "Date", "First Date", "Diagnosis", "RA"]
GOLD = "SELECT COUNT(*) FROM Patient WHERE SEX = 'F'"


def test_sql_columns_ignores_values_and_prefers_longer_names():
    sql = "SELECT SEX FROM Patient WHERE Diagnosis = 'RA' AND `First Date` > '1990-01-01' AND T2.UN = 29"
    assert sql_columns(sql, NAMES) == {"SEX", "Diagnosis", "First Date", "UN"}


def test_relevant_marks_test_questions_that_use_a_column_a_fact_is_about(tmp_path):
    d = tmp_path / "toy"
    d.mkdir()
    con = sqlite3.connect(d / "toy.sqlite")
    con.execute("CREATE TABLE Laboratory (ID INTEGER, UN INTEGER, CRE REAL)")
    con.close()
    db = open_db(tmp_path, "toy", with_docs=False)
    book = FactBook([Fact("f1", "constraint", "Laboratory.UN", "Normal is below 30.")])
    test = [Question(2, "t", "q", "SELECT ID FROM Laboratory WHERE UN > 30", "simple", ""),
            Question(3, "t", "q", "SELECT ID FROM Laboratory WHERE CRE >= 1.5", "simple", "")]
    assert relevant(test, book, db) == {2}


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


def test_run_test_resumes_without_duplicates_or_torn_lines(cfg):
    assert run_test(cfg, "docs", agent_llm=FakeAgent(crash_at=2)) is False
    with open(f"{cfg['runs_dir']}/test_docs.jsonl", "a") as f:
        f.write('{"qid": 9, "corr')  # killed mid-write
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
    open(f"{runs}/test_evosql.jsonl", "w").write(record(3) + "\n")
    with pytest.raises(SystemExit):
        selfcons_n(cfg)  # a partial evosql run would understate its cost


def test_mcnemar_uses_only_discordant_pairs():
    # 10 pairs where only A is right, 2 where only B is right, 20 ties: exact binomial p(10 of 12) = 0.0386.
    a = [True] * 10 + [False] * 2 + [True] * 10 + [False] * 10
    b = [False] * 10 + [True] * 2 + [True] * 10 + [False] * 10
    assert abs(mcnemar(a, b) - 0.03857) < 1e-4
    assert mcnemar(a, a) == 1.0


def test_bootstrap_ci_brackets_true_accuracy():
    lo, hi = bootstrap_ci(np.random.default_rng(1).random(200) < 0.6)
    assert lo < 0.6 < hi and hi - lo < 0.2
