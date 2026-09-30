import json

from evosql.files import write_atomic
from evosql.probe import ARMS
from evosql.report import consolidation_section, pooled_diff, probe_section, stream_stats
from evosql.stream import consolidation_log


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


def test_probe_table_counts_fixes_and_regressions_against_none(tmp_path):
    def rec(level, *oks):
        return {"id": "p", "db_id": "f1", "level": level, "source_qid": 1,
                "arms": {a: {"ok": ok, "sql": "", "injected": []} for a, ok in zip(ARMS, oks)}}

    # oks are in ARMS order: none, v6_facts, v7_prose, v7_sql, examples
    log = [rec("paraphrase", 0, 0, 1, 1, 1), rec("paraphrase", 1, 1, 0, 1, 1), rec("control", 1, 1, 1, 0, 1)]
    write_atomic(tmp_path / "probe_v7.jsonl", "".join(json.dumps(r) + "\n" for r in log))

    rows = {line.split(" | ")[0].strip("| "): line for line in probe_section(tmp_path) if line.startswith("| ")}

    assert rows["paraphrase"] == "| paraphrase | 1/2 | 1/2 (+0 / -0) | 1/2 (+1 / -1) | 2/2 (+1 / -0) | 2/2 (+1 / -0) |"
    assert rows["control"] == "| control | 1/1 | 1/1 (+0 / -0) | 1/1 (+0 / -0) | 0/1 (+0 / -1) | 1/1 (+0 / -0) |"
    assert rows["all"] == "| all | 2/3 | 2/3 (+0 / -0) | 2/3 (+1 / -1) | 2/3 (+1 / -1) | 3/3 (+1 / -0) |"
    assert "Not run yet" in probe_section(tmp_path / "missing")[-1]


def test_consolidation_section_counts_passes_and_edits(tmp_path):
    edit = {"op": "merge", "ids": ["f1", "f2"], "reason": "same rule", "fact": {"id": "f5"}, "applied": True}
    rejected = {"op": "generalize", "ids": ["f3"], "reason": "wider", "fact": {"id": "f3"}, "applied": False,
                "rejected": "regression on 12"}
    drop = {"op": "drop", "ids": ["f4"], "reason": "wrong", "fact": None, "applied": True}
    log = [{"after_pos": 15, "edits": [edit, rejected, drop], "usage": {"proposer": {}, "precheck": {}}, "jev_usd": 0},
           {"after_pos": 30, "skipped": "budget"}]
    write_atomic(consolidation_log(tmp_path, 0, "f1"), "".join(json.dumps(p) + "\n" for p in log))

    text = "\n".join(consolidation_section(tmp_path, [(0, "f1"), (0, "other")]))

    assert "1 run, 1 skipped" in text
    assert "proposed {'merge': 1, 'generalize': 1, 'drop': 1}" in text
    assert "applied {'merge': 1, 'drop': 1}" in text and "rejected {'generalize': 1}" in text
    assert "merge f1, f2 -> f5: same rule" in text and "drop f4 -> dropped: wrong" in text
    assert "Not run yet" in consolidation_section(tmp_path / "missing", [(0, "f1")])[-1]
