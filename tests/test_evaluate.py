import json
import sqlite3

import numpy as np
import pytest

from evosql.evaluate import analyze, bootstrap_ci, gate_decision, mcnemar, run_mode
from evosql.facts import Fact, FactBook
from evosql.labels import FILE
from evosql.llm import ProviderExhausted

GOLD = "SELECT COUNT(*) FROM Patient WHERE SEX = 'F'"


class FakeAgent:
    """Submits the given SQL; raises like a provider limit on the given call."""

    def __init__(self, sql=GOLD, crash_at=None):
        self.sql, self.calls, self.crash_at = sql, 0, crash_at
        self.usage = {"calls": 0, "prompt_tokens": 0, "completion_tokens": 0, "latency_s": 0.0}

    def chat(self, messages, tools=None, temperature=0.0, sample=0):
        self.calls += 1
        if self.calls == self.crash_at:
            raise ProviderExhausted("limit")
        self.usage["calls"] += 1
        self.usage["latency_s"] += 2.0
        return {"content": None, "reasoning": None, "model": "fake", "prompt_tokens": 1, "completion_tokens": 1,
                "tool_calls": [{"id": "c", "name": "submit", "arguments": json.dumps({"sql": self.sql})}]}


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
    # The study relabels question 5: under corrected gold, "SELECT 0" is right there.
    (tmp_path / "data" / FILE).parent.mkdir(parents=True)
    (tmp_path / "data" / FILE).write_text(json.dumps([{"question_id": "5", "db_id": "toy", "SQL": "SELECT 0"}]))
    (tmp_path / "runs").mkdir()
    (tmp_path / "runs" / "partitions.json").write_text(json.dumps({"discovery": [0], "gate": [1, 2], "final": [3, 4, 5]}))
    FactBook([Fact("f1", "encoding", "Patient.SEX", "Women are 'F'.", ["women"])]).save(tmp_path / "runs" / "knowledge.json")
    prices = {"cache_hit": 0.0, "cache_miss": 1.0, "output": 0.0}
    return {"data_dir": str(tmp_path / "data"), "db": "toy", "runs_dir": str(tmp_path / "runs"),
            "results_dir": str(tmp_path / "results"), "cache_dir": str(tmp_path / "cache"), "max_steps": 2,
            "agent": {"usd_per_million": prices}, "proposer": {"usd_per_million": prices},
            "protocol": {"budget_usd": 1.0, "max_regressions": 3}, "search": {}}


def test_run_mode_resumes_without_duplicates_or_torn_lines(cfg):
    assert run_mode(cfg, "docs", "final", agent_llm=FakeAgent(crash_at=2)) is False
    with open(f"{cfg['runs_dir']}/final_docs.jsonl", "a") as f:
        f.write('{"qid": 9, "corr')  # killed mid-write
    assert run_mode(cfg, "docs", "final", agent_llm=FakeAgent())
    lines = [json.loads(line) for line in open(f"{cfg['runs_dir']}/final_docs.jsonl")]
    assert [r["qid"] for r in lines] == [3, 4, 5] and all(r["correct"] for r in lines)
    assert [r["correct_corrected"] for r in lines] == [True, True, False]  # q5 is scored on its corrected gold
    open(f"{cfg['runs_dir']}/final_all.jsonl", "w").write(json.dumps({**lines[0], "knowledge": "old"}) + "\n")
    with pytest.raises(SystemExit):
        run_mode(cfg, "all", "final", agent_llm=FakeAgent())  # a log made with other knowledge is never extended


def records(pattern):
    return {q: {"correct": ok} for q, ok in enumerate(pattern)}


def test_gate_passes_modes_within_the_regression_limit_and_breaks_ties_by_order():
    docs = records([1, 1, 1, 1, 0, 0, 0, 0])
    results = {"docs": docs,
               "all": records([0, 0, 0, 0, 1, 1, 1, 1]),  # +4 / -4: fails, too many regressions
               "retrieve": records([1, 1, 1, 0, 1, 0, 0, 0]),  # +1 / -1: passes, net 0
               "tool": records([1, 1, 1, 1, 0, 0, 0, 0])}  # +0 / -0: passes, net 0
    rows, headline = gate_decision(results, max_regressions=3)
    assert (rows["all"]["pass"], rows["retrieve"]["pass"], rows["tool"]["pass"]) == (False, True, True)
    assert headline == "retrieve"  # tie on net: retrieve before tool
    results["tool"] = records([1, 1, 1, 1, 1, 0, 0, 0])
    assert gate_decision(results, max_regressions=3)[1] == "tool"
    results["tool"] = results["retrieve"] = records([0, 0, 1, 1, 0, 0, 0, 0])
    assert gate_decision(results, max_regressions=3)[1] == "docs"  # nothing passes


def test_analyze_reports_the_gate_headline_against_docs_on_the_final_set(cfg):
    run_mode(cfg, "docs", "final", agent_llm=FakeAgent(sql="SELECT 0"))
    run_mode(cfg, "all", "final", agent_llm=FakeAgent())
    gate = {"docs_right": 0, "headline": "all", "modes": {"all": {"right": 2, "fixes": 2, "regressions": 0, "pass": True}}}
    open(f"{cfg['runs_dir']}/gate.json", "w").write(json.dumps(gate))
    analyze(cfg)
    summary = open(f"{cfg['results_dir']}/summary.md").read()
    assert "**all** vs docs on the final set (official gold): 3 vs 0 correct of 3" in summary
    assert "| all | 3/3 = 1.000 |" in summary and "+3/-0, p=0.250 | corrected +2/-1" in summary
    assert "| 2.0 / 2.0 |" in summary  # latency p50 / p95 per question


def test_mcnemar_uses_only_discordant_pairs():
    # 10 pairs where only A is right, 2 where only B is right, 20 ties: exact binomial p(10 of 12) = 0.0386.
    a = [True] * 10 + [False] * 2 + [True] * 10 + [False] * 10
    b = [False] * 10 + [True] * 2 + [True] * 10 + [False] * 10
    assert abs(mcnemar(a, b) - 0.03857) < 1e-4
    assert mcnemar(a, a) == 1.0


def test_bootstrap_ci_brackets_true_accuracy():
    lo, hi = bootstrap_ci(np.random.default_rng(1).random(200) < 0.6)
    assert lo < 0.6 < hi and hi - lo < 0.2
