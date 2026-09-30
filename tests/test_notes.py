import json

import pytest

from evosql.bird import Question
from evosql.notes import Notes, apply, propose_edits, validate

Q = Question(1, "d", "How many patients stayed in the ICU?", "SELECT COUNT(DISTINCT subject_id) FROM icustays")
NOTES = Notes([("Traps", "Cancelled rows are kept."), ("Joins and keys", "Join on hadm_id."),
               ("Traps", "Ages are stored in years."), ("Answer shape", "Return one column.")])


def edit(**fields):
    return {"op": "add", "section": "Traps", "text": "Costs are in dollars.", "evidence": "SUM(cost)", **fields}


def test_render_hides_empty_sections_and_orders_by_section():
    assert Notes().render() == "" and Notes().line_count() == 0
    assert NOTES.render() == ("Working notes about this database:\n## Joins and keys\n- Join on hadm_id.\n"
                              "## Answer shape\n- Return one column.\n## Traps\n- Cancelled rows are kept.\n"
                              "- Ages are stored in years.")
    assert NOTES.line_count() == 8 and NOTES.to_markdown() == NOTES.render()


def test_numbered_counts_bullets_in_shown_order():
    assert Notes().numbered() == "(empty)"
    assert "L1: Join on hadm_id." in NOTES.numbered() and "L3: Cancelled rows are kept." in NOTES.numbered()
    assert NOTES.numbered().endswith("L4: Ages are stored in years.")


def test_apply_uses_the_numbering_before_the_batch():
    edits = [{"op": "add", "section": "Time and dates", "text": "Use the fixed now."},
             {"op": "delete", "line": 1},  # "Join on hadm_id."
             {"op": "replace", "line": 3, "text": "Cancelled rows are dropped."}]  # still "Cancelled rows are kept."

    new = apply(NOTES, edits)

    assert new.render().splitlines()[1:] == ["## Time and dates", "- Use the fixed now.", "## Answer shape",
                                             "- Return one column.", "## Traps", "- Cancelled rows are dropped.",
                                             "- Ages are stored in years."]
    assert len(NOTES.bullets) == 4  # the old notes are untouched


@pytest.mark.parametrize("bad, reason", [
    (dict(op="merge"), "unknown op"),
    (dict(section="Misc"), "unknown section"),
    (dict(op="delete", line=9), "no such line"),
    (dict(op="replace", line=0), "no such line"),
    (dict(text="word " * 6), "more than 5 words"),
    (dict(text=" "), "empty text"),
    (dict(evidence=""), "no evidence"),
    (dict(text="The answer is 4242."), "leakage"),
])
def test_validate_rejects_bad_edits(bad, reason):
    assert reason in validate(edit(**bad), NOTES, Q, [(4242,)], 5)


def test_validate_accepts_a_good_edit():
    assert validate(edit(), NOTES, Q, [(4242,)], 5) is None
    assert validate({"op": "delete", "line": 2, "evidence": "not needed"}, NOTES, Q, [(4242,)], 5) is None


class Llm:
    def __init__(self, content):
        self.content, self.prompts = content, []

    def chat(self, messages, tools=None):
        self.prompts.append(messages[0]["content"])
        return {"content": self.content}


class Db:
    ddl, profile = "CREATE TABLE icustays (subject_id INTEGER);", "value profile"


def test_propose_edits_parses_the_reply_and_shows_the_notes_and_examples():
    reply = json.dumps({"edits": [edit(), "junk"]})
    llm = Llm(reply)

    assert propose_edits(llm, Db(), NOTES, Q, [Q], "SELECT 1", 100) == [edit()]
    assert "L1: Join on hadm_id." in llm.prompts[0] and "Agent SQL: SELECT 1" in llm.prompts[0]
    assert "currently has 8" in llm.prompts[0] and "json" in llm.prompts[0].lower()


@pytest.mark.parametrize("content", [None, "no json here", '{"edits": "x"}', '{"other": []}', "{broken"])
def test_propose_edits_returns_nothing_for_a_malformed_reply(content):
    assert propose_edits(Llm(content), Db(), Notes(), Q, [], None, 100) == []
