import numpy as np

from evosql.analysis import bootstrap_ci, correctness_by_order, mcnemar, usd


def test_mcnemar_uses_only_discordant_pairs():
    # 10 pairs where only A is right, 2 where only B is right, 20 ties: exact binomial p(10 of 12) = 0.0386.
    a = [True] * 10 + [False] * 2 + [True] * 10 + [False] * 10
    b = [False] * 10 + [True] * 2 + [True] * 10 + [False] * 10
    assert abs(mcnemar(a, b) - 0.03857) < 1e-4
    assert mcnemar(a, a) == 1.0


def test_bootstrap_ci_brackets_true_accuracy():
    rng = np.random.default_rng(1)
    orders = [rng.random(150) < 0.6 for _ in range(3)]
    lo, hi = bootstrap_ci(orders)
    assert lo < 0.6 < hi and hi - lo < 0.2


def test_non_learning_arm_is_replayed_in_every_order_by_question_id():
    recs = {0: [{"qid": 7, "correct": True}, {"qid": 8, "correct": False}]}
    seqs = correctness_by_order(recs, learning=False, qids_by_order={0: [7, 8], 1: [8, 7]})
    assert seqs == {0: [True, False], 1: [False, True]}


def test_usd_charges_cache_hits_at_the_cheap_rate_and_local_models_nothing():
    prices = {"cache_hit": 0.003, "cache_miss": 0.15, "output": 0.60}
    usage = {"prompt_tokens": 1_000_000, "provider_cached_tokens": 900_000, "completion_tokens": 100_000}
    # 0.9M hits * 0.003 + 0.1M misses * 0.15 + 0.1M output * 0.60 = 0.0027 + 0.015 + 0.06
    assert abs(usd(usage, prices) - 0.0777) < 1e-9
    assert usd(usage, None) == 0.0
