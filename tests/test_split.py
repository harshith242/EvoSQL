from collections import Counter

from evosql.bird import Question
from evosql.split import make_split

QUESTIONS = [Question(i, "toy", f"q{i}", "SELECT 1", d, "")
             for i, d in enumerate(["simple"] * 90 + ["moderate"] * 50 + ["challenging"] * 23)]


def test_split_has_exact_sizes_no_overlap_and_is_deterministic():
    split = make_split(QUESTIONS, 50, 50, seed=0)
    assert len(split["learn"]) == 50 and len(split["test"]) == 50
    assert not set(split["learn"]) & set(split["test"])
    assert split == make_split(QUESTIONS, 50, 50, seed=0)


def test_both_halves_keep_the_difficulty_mix():
    split = make_split(QUESTIONS, 50, 50, seed=0)
    by_id = {q.qid: q.difficulty for q in QUESTIONS}
    for half in ("learn", "test"):
        counts = Counter(by_id[q] for q in split[half])
        # Full dataset shares 90/50/23 of 163, so ~27.6 / 15.3 / 7.1 per half of 50.
        assert abs(counts["simple"] - 27.6) <= 1.5 and abs(counts["moderate"] - 15.3) <= 1.5
        assert abs(counts["challenging"] - 7.1) <= 1.5
