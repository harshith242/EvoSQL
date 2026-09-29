import sqlite3

import pytest

from evosql.bird import Question, open_db
from evosql.facts import Fact
from evosql.learn import discover_facts


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

    facts, conflicts = discover_facts(qs, db, gold, solve=lambda x: (x.qid == 1, "SELECT 1"), propose=propose,
                                      wrong_label=lambda x: x.qid == 3, batch_size=1, log=logs.append)
    assert seen == [([2], 0), ([4], 1)]  # q3 never reaches the proposer; later batches see earlier facts
    assert logs[0]["known_wrong_labels"] == [3] and logs[0]["right"] == 1
    reasons = [d["reason"] for d in logs[1]["dropped"]]
    assert reasons == ["unknown column", "leakage: contains answer value '11'"]
    assert len(facts) == 1 and facts[0].source_qids == [2, 4] and conflicts == []
