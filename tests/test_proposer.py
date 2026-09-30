import json
import pytest

from conftest import make_db
from evosql.bird import Question
from evosql.facts import Fact, check
from evosql.proposer import propose


@pytest.fixture
def db(tmp_path):
    return make_db(tmp_path, "toy", "CREATE TABLE Patient (ID INTEGER, SEX TEXT); "
                                    "INSERT INTO Patient VALUES (1, 'F'), (2, 'M'), (3, 'F');")


class ReplyLLM:
    def __init__(self, reply):
        self.reply = reply
        self.prompts = []

    def chat(self, messages, tools=None):
        self.prompts.append(messages[0]["content"])
        return {"content": self.reply if isinstance(self.reply, str | None) else json.dumps(self.reply)}


def q(qid, text):
    return Question(qid, "toy", text, "SELECT SEX FROM Patient WHERE ID = 1")


FACT = {"kind": "encoding", "subject": "Patient.SEX", "statement": "Men are stored in Patient.SEX.",
        "applies_to": ["men", " "], "values": [{"table": "Patient", "column": "SEX", "value": "M"}, "junk"],
        "probe": "none", "snippet": {"table": "Patient", "form": "predicate", "sql": "Patient.SEX = 'M'"}}


def test_sloppy_proposer_fields_are_cleaned_and_the_snippet_is_parsed(db):
    llm = ReplyLLM({"fact": FACT})
    fact, why = propose(llm, db, q(7, "Men?"), None, [])
    assert why is None and "json" in llm.prompts[0].lower()
    assert (fact.fact, fact.source_qids, fact.applies_to, fact.probe, len(fact.values)) == (
        "Men are stored in Patient.SEX.", [7], ["men"], None, 1)
    assert (fact.sql, fact.learned_from) == (FACT["snippet"], "Men?")
    assert propose(ReplyLLM({"fact": {**FACT, "applies_to": "men"}}), db, q(7, "Men?"), None, [])[0].applies_to == []


def test_a_malformed_snippet_is_dropped_but_the_fact_is_kept(db):
    for bad in ({"table": "Patient", "form": "predicate"}, {"table": "Patient", "form": 1, "sql": "x"}, "SEX = 'M'"):
        fact, _ = propose(ReplyLLM({"fact": {**FACT, "snippet": bad}}), db, q(7, "Men?"), None, [])
        assert fact.sql is None and fact.subject == "Patient.SEX"


def test_an_empty_reply_and_a_null_fact_are_told_apart(db):
    why = "no reusable fact proposed"
    assert propose(ReplyLLM(None), db, q(7, "Men?"), None, []) == (None, "empty reply")
    assert propose(ReplyLLM(""), db, q(7, "Men?"), None, []) == (None, "empty reply")
    assert propose(ReplyLLM({"fact": None}), db, q(7, "Men?"), None, []) == (None, why)
    assert propose(ReplyLLM({"fact": {"kind": "encoding"}}), db, q(7, "Men?"), None, []) == (None, why)


def test_a_code_that_equals_the_answer_is_allowed_but_a_unique_value_is_not(db):
    question = q(2, "Which sex has patient 1?")
    code = Fact("f1", "encoding", "Patient.SEX", "Women are stored as 'F' in Patient.SEX.", ["women", "Which sex has"],
                None, [2], [{"table": "Patient", "column": "SEX", "value": "F"}])
    # 'F' is the answer, but it is a code stored in 2 rows; a trigger phrase may reuse the question's words.
    assert check(code, db, question, [("F",)]) is None
    unique = Fact("f2", "encoding", "Patient.ID", "Patient.ID 2 is the only man.", ["man"], None, [2],
                  [{"table": "Patient", "column": "ID", "value": "2"}])
    assert check(unique, db, question, [(2,)]).startswith("leakage")
