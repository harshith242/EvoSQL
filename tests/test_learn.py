import pytest

from evosql.bird import Question
from evosql.budget import Budget, BudgetExceeded
from evosql.facts import Fact, FactBook
from evosql.learn import learn_loop

QS = [Question(i, "toy", f"question {i}", "SELECT 1", "simple") for i in range(1, 7)]

# Which learning questions are right, given the fact texts in the knowledge.
OUTCOMES = {
    (): {1, 2},
    ("small",): {1, 2, 3},             # net +1: below the threshold of 2
    ("elsewhere",): {1, 2, 5, 6},      # net +2, but proposed for batch [3, 4], which it does not fix
    ("good",): {1, 2, 3, 4},           # net +2 and fixes the batch
    ("good", "helper"): {1, 2, 3, 4},  # two facts, so consolidation has something to merge
    ("merged",): {1, 2, 3},            # consolidation that loses a question
}


def solve(q, book):
    return q.qid in OUTCOMES.get(tuple(sorted(f.fact for f in book.facts)), {1, 2}), f"SQL for {q.qid}"


def proposer(*texts):
    """Returns the given fact texts, one proposal per call, then nothing."""
    queue = list(texts)

    def propose(batch, book):
        if not queue:
            return [], []
        text = queue.pop(0)
        return [{"op": "add", "kind": "meaning", "subject": "T.c", "fact": text, "qid": batch[0][0].qid}], []
    return propose


def run(propose, consolidate=lambda book: book, check=lambda e, q: None, epochs=1):
    log = []
    neutral = {"op": "add", "kind": "meaning", "subject": "T.id", "fact": "T.id is a column.", "qid": None}
    k, ungated, flips = learn_loop(QS, solve, propose, check, consolidate, epochs, batch_size=2, min_gain=2,
                                   log=log.append, neutral=neutral)
    return k, ungated, log


def test_small_gain_and_gain_outside_the_batch_are_rejected():
    # Batches are [3, 4] then [5, 6]; "small" fixes only question 3, outside the second batch.
    k, _, log = run(proposer("elsewhere", "small"))
    decisions = [e["decision"] for e in log if e["event"] == "batch"]
    assert decisions[0] == "rejected (fixed 0 of 2)" and decisions[1] == "rejected (fixed 0 of 2)"
    assert k.facts == []


def test_qualifying_candidate_is_accepted_and_becomes_the_new_version():
    k, _, log = run(proposer("good"))
    assert [f.fact for f in k.facts] == ["good"]
    assert next(e for e in log if e["event"] == "batch")["version"] == 1


def two_facts(batch, book):
    edits = [{"op": "add", "kind": "meaning", "subject": "T.c", "fact": t, "qid": batch[0][0].qid} for t in ("good", "helper")]
    return (edits, []) if not book.facts else ([], [])


def test_consolidation_is_kept_only_if_it_does_not_lower_the_learning_score():
    worse = lambda book: FactBook([Fact("f1", "meaning", "T.c", "merged")])
    k, _, log = run(two_facts, consolidate=worse)
    assert [f.fact for f in k.facts] == ["good", "helper"] and log[-1]["kept"] is False
    same = lambda book: FactBook([Fact("f9", "meaning", "T.c", "good")])
    k, _, log = run(two_facts, consolidate=same)
    assert k.facts[0].id == "f9" and log[-1]["kept"] is True


def test_ungated_keeps_every_checked_fact_even_from_rejected_batches():
    check = lambda e, q: "contains SQL" if e["fact"] == "elsewhere" else None
    k, ungated, log = run(proposer("elsewhere", "small"), check=check)
    assert [f.fact for f in ungated.facts] == ["small"] and log[1]["dropped"][0]["reason"] == "contains SQL"
    _, ungated, _ = run(proposer("small", "small"))
    assert [f.fact for f in ungated.facts] == ["small"]  # a repeated fact is kept once


def test_budget_persists_real_spend_and_stops_past_the_cap(tmp_path):
    budget = Budget(tmp_path / "spend.json", cap_usd=1.0)
    budget.spend(0.4)
    assert Budget(tmp_path / "spend.json", 1.0).total == pytest.approx(0.4)
    with pytest.raises(BudgetExceeded):
        budget.spend(0.7)


def test_proposer_sees_the_sql_the_agent_wrote_for_each_failure():
    seen = []
    def propose(batch, book):
        seen.extend(sql for _, sql in batch)
        return [], []
    run(propose)
    assert seen[:2] == ["SQL for 3", "SQL for 4"]


def test_fixing_a_batch_question_is_not_enough_without_net_gain():
    k, _, log = run(proposer("small"))  # fixes question 3 of batch [3, 4]: net +1, threshold 2
    assert next(e for e in log if e["event"] == "batch")["decision"] == "rejected (net 1, need 2)"
    assert k.facts == []
