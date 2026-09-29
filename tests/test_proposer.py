import json
import sqlite3

import pytest

from evosql.bird import Question, open_db
from evosql.facts import Fact
from evosql.proposer import check, leak_exempt, propose


@pytest.fixture
def db(tmp_path):
    d = tmp_path / "toy"
    d.mkdir()
    con = sqlite3.connect(d / "toy.sqlite")
    con.execute("CREATE TABLE Patient (ID INTEGER, SEX TEXT)")
    con.executemany("INSERT INTO Patient VALUES (?, ?)", [(1, "F"), (2, "M"), (3, "F")])
    con.commit()
    con.close()
    return open_db(tmp_path, "toy")


class ReplyLLM:
    def __init__(self, reply):
        self.reply = reply

    def chat(self, messages, tools=None):
        return {"content": json.dumps(self.reply)}


def q(qid, text):
    return Question(qid, "toy", text, "SELECT SEX FROM Patient WHERE ID = 1", "simple")


def test_sloppy_proposer_fields_are_cleaned_and_a_null_fact_means_nothing_reusable(db):
    reply = {"kind": "encoding", "subject": "Patient.SEX", "fact": "Men are stored in Patient.SEX.",
             "applies_to": ["men", " "], "values": [{"table": "Patient", "column": "SEX", "value": "M"}, "junk"],
             "probe": "none"}
    fact = propose(ReplyLLM(reply), db, q(7, "Men?"), None, [])
    assert (fact.source_qids, fact.applies_to, fact.probe, len(fact.values)) == ([7], ["men"], None, 1)
    assert propose(ReplyLLM({**reply, "applies_to": "men"}), db, q(7, "Men?"), None, []).applies_to == []
    assert propose(ReplyLLM({"fact": None}), db, q(7, "Men?"), None, []) is None


def test_a_code_that_equals_the_answer_is_allowed_but_a_unique_value_is_not(db):
    question = q(2, "Which sex has patient 1?")
    code = Fact("f1", "encoding", "Patient.SEX", "Women are stored as 'F' in Patient.SEX.", ["women", "Which sex has"],
                None, [2], [{"table": "Patient", "column": "SEX", "value": "F"}])
    # 'F' is the answer, but it is a code stored in 2 rows; a trigger phrase may reuse the question's words.
    assert leak_exempt(code, db) == {"f"} and check(code, question, [("F",)], db) is None
    unique = Fact("f2", "encoding", "Patient.ID", "Patient.ID 2 is the only man.", ["man"], None, [2],
                  [{"table": "Patient", "column": "ID", "value": "2"}])
    assert check(unique, question, [(2,)], db).startswith("leakage")
