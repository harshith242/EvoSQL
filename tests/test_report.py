from evosql.report import pooled_diff, stream_stats


def recs(pairs, injected=()):
    """Stream records from (none_ok, facts_ok) pairs; `injected` lists positions with a fact in the prompt."""
    return [{"pos": i, "none_ok": n, "facts_ok": f, "injected": ["f1"] if i in injected else [], "memory_size": 1}
            for i, (n, f) in enumerate(pairs, 1)]


def test_second_half_difference_and_direction_ignore_the_cold_start():
    # First half: facts worse (cold start); second half: +2 fixes, -1 regression over 4 questions.
    s = stream_stats(recs([(1, 0), (1, 0), (1, 0), (0, 0), (0, 1), (0, 1), (1, 0), (1, 1)], injected={5, 6, 7}), 0.10)
    assert (s["late_n"], s["fixes_late"], s["regressions_late"]) == (4, 2, 1)
    assert abs(s["diff_late"] - 0.25) < 1e-9 and s["facts_all"] < s["none_all"]
    assert s["injection_rate"] == 0.75 and not s["inert"]
    other = stream_stats(recs([(0, 0)] * 4 + [(1, 0)] * 2 + [(0, 0)] * 2), 0.10)
    assert pooled_diff([s, other]) == (2 - 1 - 2) / 8


def test_rarely_used_memory_is_flagged_inert():
    s = stream_stats(recs([(0, 0)] * 20 + [(0, 1)] + [(0, 0)] * 19, injected={21}), 0.10)
    assert s["injection_rate"] == 0.05 and s["inert"]
