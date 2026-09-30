import hashlib
import json

import numpy as np
import pytest

from conftest import RULES, FakeJev, make_db
from evosql.bird import Question
from evosql.memory import FactMemory
from evosql.notes import Notes
from evosql.stream import Answers, Live, load_testbed, replay_differences, run_stream, update_notes

GOLD = "SELECT COUNT(*) FROM results WHERE time IS NOT NULL"
FACT = "A driver finished a race when results.time has a value, even when lapped."


class Agent:
    """Right only when the learned fact or the similar-examples section is in the system prompt."""

    def __init__(self):
        self.usage = {"calls": 0}
        self.prompts = []
        self.asked = []  # (question, system prompt)

    def chat(self, messages, tools=None):
        self.usage["calls"] += 1
        self.prompts.append(messages[0]["content"])
        self.asked.append((messages[1]["content"], messages[0]["content"]))
        right = FACT in messages[0]["content"] or "Similar past questions" in messages[0]["content"]
        sql = GOLD if right else "SELECT COUNT(*) FROM results"
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


class LiveAgent:
    """The notes-arm agent: right on a question when right(system prompt, question) says so."""

    def __init__(self, right):
        self.usage, self.asked, self.right = {"calls": 0}, [], right

    def chat(self, messages, tools=None):
        self.usage["calls"] += 1
        self.asked.append((messages[1]["content"], messages[0]["content"]))
        sql = GOLD if self.right(messages[0]["content"], messages[1]["content"]) else "SELECT COUNT(*) FROM results"
        return {"content": None, "reasoning": None, "tool_calls": [
            {"id": "c", "name": "submit", "arguments": json.dumps({"sql": sql})}]}


class NotesProposer:
    """Always proposes the same edits."""

    def __init__(self, edits):
        self.usage, self.edits = {"calls": 0}, edits

    def chat(self, messages, tools=None):
        self.usage["calls"] += 1
        return {"content": json.dumps({"edits": self.edits})}


def stream(tmp_path, monkeypatch, can_precheck, live=None):
    monkeypatch.chdir(tmp_path)  # gold rows are cached under ./cache
    db = make_db(tmp_path, "f1", "CREATE TABLE results (raceId INTEGER, driverId INTEGER, time TEXT); "
                                 "INSERT INTO results VALUES (1, 1, '1:30'), (1, 2, NULL), (1, 3, '1:31');")
    order = [Question(i, "f1", f"How many drivers finished race {i}?", GOLD) for i in (1, 2, 3)]
    jev = PricedJev(lambda state, key: 3.0)
    memory = FactMemory(db, jev, lambda texts: np.ones((len(texts), 2)), RULES, "f1 (test)")
    agent = Agent()
    run_stream(db, order, Answers(agent, 3), Proposer(), memory, can_precheck, tmp_path / "log.jsonl",
               tmp_path / "consolidation.jsonl", 2, {1: "A", 2: "B", 3: None}, {3: ["A", "B"]}, 2, live)
    read = lambda name: [json.loads(line) for line in open(tmp_path / name)]
    return read("log.jsonl"), read("consolidation.jsonl"), memory, agent


def test_a_fact_is_learned_after_its_question_and_helps_the_next_one(tmp_path, monkeypatch):
    recs, _, memory, agent = stream(tmp_path, monkeypatch, lambda: True)
    first, second = recs[0], recs[1]
    assert first["injected"] == [] and not first["facts_ok"]  # a question never sees the fact learned from it
    assert first["learning"]["outcome"] == "pre-check unmatched"  # no earlier question to check against
    assert second["injected"] == ["f1"] and second["facts_ok"] and not second["none_ok"]
    assert memory.state["f1"]["score"] == 2  # fixed questions 2 and 3
    # With nothing injected, an arm replays the none arm's answer instead of asking again: 1 + 2 + 2 + 2 calls.
    assert agent.usage["calls"] == 7 and first["usage"]["facts"] == first["usage"]["examples"] == {}


def test_the_examples_arm_shows_earlier_questions_and_never_learns(tmp_path, monkeypatch):
    recs, _, memory, agent = stream(tmp_path, monkeypatch, lambda: True)
    assert [r["examples_ok"] for r in recs] == [False, True, True]  # question 1 replays none
    assert [r["examples_used"] for r in recs] == [[], [1], [1, 2]]
    # Question 3 combines templates A and B, so examples of either count as its own template.
    assert [r["examples_same_template"] for r in recs] == [[], [False], [True, True]]
    assert [r["template"] for r in recs] == ["A", "B", None] and recs[2]["components"] == ["A", "B"]
    assert recs[1]["examples_sql"] == GOLD and recs[0]["examples_sql"] == recs[0]["none_sql"]
    assert all(len(r["turns"]) == len(r["latency_s"]) == 3 for r in recs)
    assert set(recs[1]["usage"]) == {"none", "facts", "examples"} and recs[1]["usage"]["examples"] == {"calls": 1}

    section = next(p for p in agent.prompts if "Similar past questions" in p and "race 2?\nSQL" in p)
    assert "Q: How many drivers finished race 1?\nSQL: " + GOLD in section
    assert memory.state["f1"]["score"] == 2  # the examples arm credits nothing


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


def test_a_score_function_changes_what_is_executed_but_not_the_logged_sql(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    db = make_db(tmp_path, "f1", "CREATE TABLE results (time TEXT); INSERT INTO results VALUES ('1:30'), (NULL);")
    q = Question(1, "f1", "How many drivers finished?", GOLD)

    result = Answers(Agent(), 3, score=lambda sql: GOLD).get(db, q, [(1,)])

    assert result["ok"] and result["sql"] == "SELECT COUNT(*) FROM results"


def first_prompt(agent, n):
    """The system prompt of the first call about question n (the arm's own, before any check)."""
    return next(system for q, system in agent.asked if f"race {n}?" in q)


def notes_stream(tmp_path, monkeypatch, right, text, can_check=lambda: True):
    edits = [{"op": "add", "section": "Traps", "text": text, "evidence": "time IS NOT NULL"}]
    live_agent = LiveAgent(right)
    live = Live(Answers(live_agent, 3), NotesProposer(edits), can_check, {"max_lines": 100, "max_words": 40})
    recs, _, _, agent = stream(tmp_path, monkeypatch, lambda: True, live)
    return recs, live_agent, agent


def test_the_notes_arm_replays_the_examples_prompt_while_the_notes_are_empty(tmp_path, monkeypatch):
    recs, live_agent, agent = notes_stream(tmp_path, monkeypatch, lambda system, q: "race 1?" in q, "Note.")

    assert first_prompt(live_agent, 1) == first_prompt(agent, 1)  # question 1: no examples, no notes
    assert recs[0]["notes_ok"] and recs[0]["notes_update"] is None and recs[0]["notes_lines"] == 0
    examples_prompt = next(system for q, system in agent.asked if "race 2?" in q and "Similar past" in system)
    assert first_prompt(live_agent, 2) == examples_prompt


def test_an_applied_update_shows_up_in_the_next_prompt_and_the_log(tmp_path, monkeypatch):
    recs, live_agent, _ = notes_stream(tmp_path, monkeypatch, lambda system, q: "A finished race" in system,
                                       "A finished race has a time value.")

    update = recs[0]["notes_update"]
    assert not recs[0]["notes_ok"] and update["outcome"] == "applied unchecked" and update["fixes_source"] is True
    assert update["edits"][0]["valid"] and update["edits"][0]["reason"] is None and update["broke"] is None
    assert update["usage"]["proposer"] == {"calls": 1} and update["usage"]["check"] == {"calls": 1}
    assert "## Traps\n- A finished race has a time value." in first_prompt(live_agent, 2)
    assert [r["notes_ok"] for r in recs] == [False, True, True] and [r["notes_lines"] for r in recs] == [0, 3, 3]
    assert all(r["notes_update"] is None for r in recs[1:])
    assert all(len(r["turns"]) == len(r["latency_s"]) == 4 and "notes" in r["usage"] for r in recs)
    assert recs[1]["notes_sql"] == GOLD


def test_an_update_that_breaks_an_earlier_correct_question_is_rejected(tmp_path, monkeypatch):
    # Question 1 is right until the new note appears; question 2 is right only with it.
    right = lambda system, q: ("BREAK" not in system) if "race 1?" in q else ("FIX" in system)
    recs, live_agent, _ = notes_stream(tmp_path, monkeypatch, right, "BREAK and FIX rule.")

    update = recs[1]["notes_update"]
    assert recs[0]["notes_ok"] and not recs[1]["notes_ok"]
    assert update["outcome"] == "rejected: regression" and update["checked"] == [1] and update["broke"] == 1
    assert update["fixes_source"] is True
    assert all(r["notes_lines"] == 0 for r in recs) and "BREAK" not in first_prompt(live_agent, 3)


def test_the_regression_check_is_skipped_near_the_budget_cap(tmp_path, monkeypatch):
    right = lambda system, q: ("BREAK" not in system) if "race 1?" in q else ("FIX" in system)
    recs, _, _ = notes_stream(tmp_path, monkeypatch, right, "BREAK and FIX rule.", can_check=lambda: False)

    assert recs[1]["notes_update"]["outcome"] == "applied unchecked (budget)"
    assert recs[1]["notes_update"]["checked"] == [] and recs[2]["notes_lines"] == 3


def test_update_notes_rejects_a_batch_that_would_overflow_and_drops_invalid_edits(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    db = make_db(tmp_path, "f1", "CREATE TABLE results (time TEXT); INSERT INTO results VALUES ('1:30');")
    q = Question(1, "f1", "How many drivers finished?", GOLD)
    good = {"op": "add", "section": "Traps", "text": "Times can be missing.", "evidence": "time IS NOT NULL"}
    bad = {"op": "add", "section": "Nowhere", "text": "Ignored.", "evidence": "x"}
    args = (db, q, [(1,)], [], "SELECT 1", Notes(), [], NotesProposer([bad, good]), Answers(LiveAgent(bool), 3),
            None, lambda: True)

    notes, log = update_notes(*args, {"max_lines": 2, "max_words": 40})

    assert notes.bullets == [] and log["outcome"] == "rejected: notes full" and log["fixes_source"] is None
    assert [e["valid"] for e in log["edits"]] == [False, True] and "unknown section" in log["edits"][0]["reason"]
    notes, log = update_notes(*args[:7], NotesProposer([bad]), *args[8:], {"max_lines": 2, "max_words": 40})
    assert log["outcome"] == "no valid edits"


def test_replay_differences_names_the_arm_answers_that_changed(tmp_path):
    old = [{"pos": 1, "none_ok": True, "none_sql": "a"}, {"pos": 2, "none_ok": True, "none_sql": "b"}]
    new = [old[0], {**old[1], "none_ok": False}]
    for name, records in (("old", old), ("new", new)):
        (tmp_path / name).write_text("\n".join(json.dumps({"facts_ok": 1, "facts_sql": "", "examples_ok": 1,
                                                          "examples_sql": "", **r}) for r in records))

    assert replay_differences(tmp_path / "old", tmp_path / "old") == ([], 2)
    assert replay_differences(tmp_path / "new", tmp_path / "old") == (["pos 2 none_ok: True became False"], 1)


def test_replay_differences_compares_only_the_arms_the_old_run_has(tmp_path):
    old = {"pos": 1, "none_ok": True, "none_sql": "a", "facts_ok": True, "facts_sql": "b"}  # like v7: no examples
    (tmp_path / "old").write_text(json.dumps(old))
    (tmp_path / "new").write_text(json.dumps({**old, "examples_ok": False, "examples_sql": "c"}))

    assert replay_differences(tmp_path / "new", tmp_path / "old") == ([], 1)


def arcwise_cfg(tmp_path, digest=None):
    """A config for a tiny Arcwise-Plat testbed whose question file is listed out of qid order."""
    make_db(tmp_path, "f1", "CREATE TABLE results (time TEXT);")  # no description CSVs are needed
    items = [{"question_id": i, "db_id": db, "question": f"Q{i}?", "SQL": "SELECT 1"}
             for i, db in ((3, "f1"), (1, "f1"), (2, "other"))]
    path = tmp_path / "questions.json"
    path.write_text(json.dumps(items))
    manifest = {"sha256": {str(path): digest or hashlib.sha256(path.read_bytes()).hexdigest()}}
    (tmp_path / "manifest.json").write_text(json.dumps(manifest))
    return {"data_dir": str(tmp_path), "stream": {"source": "arcwise", "questions": str(path),
                                                  "docs_root": str(tmp_path / "docs"), "databases": {"f1": "test"}}}


def test_the_arcwise_testbed_has_no_templates_no_scoring_and_questions_in_qid_order(tmp_path):
    questions, templates, components, dbs, score = load_testbed(arcwise_cfg(tmp_path))

    assert [q.qid for q in questions] == [1, 3]  # only the configured database, sorted as v7 sorted before shuffling
    assert templates == {} and components == {} and score is None and list(dbs) == ["f1"]


def test_the_arcwise_testbed_stops_when_the_question_file_is_not_the_pinned_one(tmp_path):
    with pytest.raises(SystemExit, match="does not match its manifest"):
        load_testbed(arcwise_cfg(tmp_path, digest="0" * 64))
