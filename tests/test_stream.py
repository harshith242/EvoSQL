import json
import sqlite3

from evosql.llm import ProviderExhausted
from evosql.knowledge import Knowledge
from evosql.stream import resume_point, run_arm

GOLD = "SELECT COUNT(*) FROM patient WHERE sex = 'F'"


def reply(sql):
    return {"content": None, "tool_calls": [{"id": "c1", "name": "submit", "arguments": json.dumps({"sql": sql})}],
            "model": "fake-agent", "prompt_tokens": 10, "completion_tokens": 1}


class FakeAgent:
    """Answers correctly only once a learned note is in the prompt; can crash like a rate-limited provider."""

    def __init__(self, crash_at=None):
        self.calls, self.crash_at = 0, crash_at
        self.usage, self.models_seen = {"calls": 0}, {"fake-agent"}

    def chat(self, messages, tools=None, temperature=0.0, sample=0):
        self.calls += 1
        self.usage["calls"] += 1
        if self.calls == self.crash_at:
            raise ProviderExhausted("daily limit")
        return reply(GOLD if "Learned notes" in messages[0]["content"] else "SELECT 0")


class FakeProposer:
    def __init__(self):
        self.usage, self.models_seen = {"calls": 0}, {"fake-proposer"}

    def chat(self, messages, tools=None, temperature=0.0, sample=0):
        self.usage["calls"] += 1
        note = {"kind": "add", "note_id": None, "when": "counting women", "text": "women are sex = 'F'"}
        return {"content": json.dumps(note), "tool_calls": [], "model": "fake-proposer",
                "prompt_tokens": 10, "completion_tokens": 1}


def setup(tmp_path):
    data = tmp_path / "data"
    (data / "toy").mkdir(parents=True)
    con = sqlite3.connect(data / "toy" / "toy.sqlite")
    con.execute("CREATE TABLE patient (id INTEGER, sex TEXT)")
    con.executemany("INSERT INTO patient VALUES (?, ?)", [(1, "F"), (2, "M"), (3, "F")])
    con.commit()
    con.close()
    dev = [{"question_id": i, "db_id": "toy", "question": f"How many women? v{i}", "SQL": GOLD,
            "difficulty": "simple", "evidence": ""} for i in range(4)]
    (data / "dev.json").write_text(json.dumps(dev))
    arms = tmp_path / "arms"
    arms.mkdir()
    (arms / "ratchet.yaml").write_text(
        "docs: false\nlearning: true\n"
        "gate: {replay_k: 0, noise_p: 0.0, leakage_check: false, token_check: false, cap_tokens: 0, prune_every: 0}\n")
    return {"data_dir": str(data), "db": "toy", "runs_dir": str(tmp_path / "runs"), "arms_dir": str(arms),
            "max_steps": 3}


def test_crash_then_rerun_resumes_without_duplicates_and_keeps_learned_notes(tmp_path):
    cfg = setup(tmp_path)
    # Calls: step 0 answer, gate before, gate after, step 1 answer, step 2 answer -> crash on 5th call.
    finished = run_arm(cfg, "ratchet", 0, agent_llm=FakeAgent(crash_at=5), proposer_llm=FakeProposer())
    assert finished is False

    assert run_arm(cfg, "ratchet", 0, agent_llm=FakeAgent(), proposer_llm=FakeProposer())
    lines = [json.loads(line) for line in (tmp_path / "runs/ratchet/toy/order0.jsonl").read_text().splitlines()]
    assert [r["step"] for r in lines] == [0, 1, 2, 3]
    assert [r["correct"] for r in lines] == [False, True, True, True]
    assert lines[0]["decision"] == "accepted" and lines[-1]["notes_count"] == 1


def test_resume_drops_partial_line_and_redoes_a_step_whose_notes_were_not_saved(tmp_path):
    log, notes = tmp_path / "order0.jsonl", tmp_path / "order0.notes.json"
    Knowledge().save(notes, done=2)
    # Steps 0-2 logged, notes saved only through step 1, then a torn write.
    log.write_text('{"step": 0}\n{"step": 1}\n{"step": 2}\n{"ste')
    assert resume_point(log, notes) == 2
    assert log.read_text() == '{"step": 0}\n{"step": 1}\n'
