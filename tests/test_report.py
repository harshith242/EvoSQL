import json

from evosql.files import write_atomic
from evosql.probe import ARMS
from evosql.report import (consolidation_section, first_occurrences, pooled_diff, probe_section, report,
                           stream_stats, template_match_split)
from evosql.stream import consolidation_log, stream_log


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


def test_examples_arm_injection_rate_counts_questions_with_an_example_shown():
    late = [{"pos": i, "none_ok": 0, "examples_ok": 1, "examples_used": [7] if i in (3, 4) else [], "memory_size": 0}
            for i in range(1, 5)]

    s = stream_stats(late, 0.10, arm="examples")

    assert s["injection_rate"] == 1.0 and s["examples_late"] == 1.0 and s["fixes_late"] == 2 and not s["inert"]


def test_first_occurrences_pick_the_first_record_of_each_template():
    recs = [{"pos": i, "template": t} for i, t in enumerate(["a", "b", "a", None, "c", "b"], 1)]

    assert [r["pos"] for r in first_occurrences(recs)] == [1, 2, 5]


def test_template_match_split_counts_fixes_and_regressions_per_group():
    def rec(none_ok, ex_ok, used, same):
        return {"none_ok": none_ok, "examples_ok": ex_ok, "examples_used": used, "examples_same_template": same}

    recs = [rec(0, 0, [], []),
            rec(0, 1, [1, 2], [True, False]), rec(0, 1, [3, 4], [False, True]), rec(1, 0, [5, 6], [True, True]),
            rec(1, 0, [7, 8], [False, False]), rec(0, 0, [9, 10], [False, False])]

    split = template_match_split(recs)

    assert split["same template shown"] == {"n": 3, "fixes": 2, "regressions": 1, "none_ok": 1, "examples_ok": 2}
    assert split["other templates only"] == {"n": 2, "fixes": 0, "regressions": 1, "none_ok": 1, "examples_ok": 0}
    assert split["no examples shown"] == {"n": 1, "fixes": 0, "regressions": 0, "none_ok": 0, "examples_ok": 0}


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


def test_report_runs_end_to_end_on_a_small_v8_stream(tmp_path):
    usage = {"input": 100, "output": 10}
    stream = [{"qid": i, "db_id": "d", "template": "a" if i < 3 else "b"} for i in range(1, 5)]
    (tmp_path / "stream_v8.json").write_text(json.dumps(stream))
    (tmp_path / "manifest.json").write_text(json.dumps({
        "repo": "r/x", "commit": "abc", "files": {"f.json": "0123456789abcdef" * 4},
        "stream": {"path": "stream_v8.json", "sha256": "f" * 64, "templates": 2, "questions": 4}}))
    log = [{"pos": i, "qid": i, "none_ok": i % 2, "facts_ok": 1, "examples_ok": 1, "injected": [], "memory_size": 0,
            "examples_used": [i - 1] if i > 1 else [], "examples_same_template": [i == 2] if i > 1 else [],
            "template": stream[i - 1]["template"], "turns": [2, 2, 2], "latency_s": [1.0, 1.0, 1.0],
            "usage": {"none": usage, "facts": usage, "examples": usage}, "learning": None, "jev_usd": 0}
           for i in range(1, 5)]
    out = tmp_path / "runs"
    write_atomic(stream_log(out, 0, "d"), "".join(json.dumps(r) + "\n" for r in log))
    price = {"cache_hit": 1, "cache_miss": 1, "output": 1}
    cfg = {"runs_dir": str(out), "results_dir": str(tmp_path / "results"),
           "agent": {"usd_per_million": price}, "proposer": {"usd_per_million": price},
           "stream": {"questions": str(tmp_path / "stream_v8.json"), "databases": {"d": "x"}, "seeds": [0],
                      "inert_below": 0.1, "budget_usd": 3.0, "rules": {"cutoff": 2.75}}}

    report(cfg)

    text = (tmp_path / "results" / "summary.md").read_text()
    for heading in ("# EvoSQL v8 results", "(examples vs none)", "One database", "## First occurrences",
                    "## Examples by template match", "commit `abc`"):
        assert heading in text
    assert "## Probe" not in text
