from collections import Counter

from evosql.bird import Question
from evosql.split import make_partitions, make_split, pilot_qids

QUESTIONS = [Question(i, "toy", f"q{i}", "SELECT 1", d)
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


def test_partitions_are_disjoint_drop_the_pilot_and_cover_the_rest():
    protocol = {"n_learn": 50, "n_test": 50, "n_pilot": 15, "seed": 0}
    parts = make_partitions(QUESTIONS, protocol)
    split, pilot = make_split(QUESTIONS, 50, 50, 0), pilot_qids(QUESTIONS, 15, 0)
    assert len(pilot) == 15
    assert parts["discovery"] == [q for q in split["learn"] if q not in pilot]
    assert parts["gate"] == [q for q in split["test"] if q not in pilot]
    sets = [set(v) for v in parts.values()]
    assert sum(map(len, sets)) == len(set().union(*sets)) == len(QUESTIONS) - 15
    assert not set().union(*sets) & pilot
