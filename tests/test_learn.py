import json
import sqlite3

import pytest

from evosql.bird import Question, open_db
from evosql.facts import Fact
from evosql.learn import discover_facts, propose_facts


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


def q(qid, text):
    return Question(qid, "toy", text, "SELECT ID FROM Patient WHERE SEX = 'F'", "simple")


def test_discovery_skips_wrong_labels_drops_bad_facts_and_merges(db):
    qs = [q(1, "Right one?"), q(2, "Which women?"), q(3, "Mislabelled?"), q(4, "Female patient ids?")]
    gold = {x.qid: [(11,), (13,)] for x in qs}
    women = lambda qid: Fact("", "encoding", "Patient.SEX", "Women are stored as 'F'.", ["women"], None, [qid])
    seen, logs = [], []

    def propose(batch, known):
        seen.append(([x.qid for x, _ in batch], len(known)))
        qid = batch[0][0].qid
        return [women(qid), Fact("", "meaning", "Patient.AGE", "Age in years.", ["age"], None, [qid]),
                Fact("", "encoding", "Patient.SEX", "The women are ids 11 and 13.", ["women"], None, [qid])]

    single, verified, conflicts = discover_facts(
        qs, db, gold, solve=lambda x: (x.qid == 1, "SELECT 1"), propose=propose, wrong_label=lambda x: x.qid == 3,
        verify=lambda x, bundle: x.qid == 2, batch_size=1, log=logs.append)
    assert seen == [([2], 0), ([4], 1)]  # q3 never reaches the proposer; later batches see earlier facts
    assert logs[0]["known_wrong_labels"] == [3] and logs[0]["right"] == 1
    reasons = [d["reason"] for d in logs[1]["dropped"]]
    assert reasons == ["unknown column", "leakage: contains answer value '11'"]
    assert len(single) == 1 and single[0].source_qids == [2, 4] and conflicts == []
    # Only q2's bundle fixed q2 when re-answered, so verified keeps its copy of the fact and drops q4's.
    assert [(e["qid"], e["passed"]) for e in logs if e["event"] == "verify"] == [(2, True), (4, False)]
    assert len(verified) == 1 and verified[0].source_qids == [2]


class ReplyLLM:
    def __init__(self, reply):
        self.reply = reply

    def chat(self, messages, tools=None):
        return {"content": json.dumps(self.reply)}


def test_proposer_reply_is_normalized_so_good_facts_survive_sloppy_fields(db):
    batch = [(q(4, "Which women?"), "SELECT 1"), (q(7, "Men?"), None)]
    reply = {"facts": [
        {"qid": "7", "kind": "encoding", "subject": "Patient.SEX", "fact": "Men are 'M'.", "applies_to": ["men", " "], "probe": "none"},
        {"kind": "encoding", "subject": "Patient.SEX", "fact": "Women are 'F'.", "applies_to": "women", "probe": "SELECT 1"},
        {"qid": 4, "kind": "encoding", "subject": "Patient.SEX"},
    ]}
    men, women = propose_facts(ReplyLLM(reply), db, batch, [])
    assert (men.source_qids, men.applies_to, men.probe) == ([7], ["men"], None)
    assert (women.source_qids, women.applies_to, women.probe) == ([4], [], "SELECT 1")  # dropped later: no phrase
