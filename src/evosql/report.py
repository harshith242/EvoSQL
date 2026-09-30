"""v8 report: second-half results of the facts and examples arms against no memory on one stream, the learning curve,
first occurrences of each template, and examples by template match. Question-level statistics are labelled heuristic."""
import json
from collections import Counter
from pathlib import Path

import numpy as np

from evosql.budget import Budget
from evosql.files import read_jsonl, write_atomic
from evosql.llm import usd
from evosql.probe import ARMS
from evosql.stream import consolidation_log, facts_file, stream_log

LEVELS = ("paraphrase", "same_quirk", "new_surface", "control")


def stream_stats(recs, inert_below, arm="facts"):
    """Second-half and whole-stream results of one complete stream (records in stream order) for an arm vs none."""
    n = len(recs)
    late = [r for r in recs if r["pos"] > n / 2]
    acc = lambda rs, a: sum(r[f"{a}_ok"] for r in rs) / len(rs) if rs else 0.0
    quarters = [recs[i * n // 4:(i + 1) * n // 4] for i in range(4)]

    # Memory in the prompt: injected facts, or the examples shown.
    shown = {"facts": "injected", "examples": "examples_used"}[arm]
    injected = sum(bool(r[shown]) for r in late) / len(late) if late else 0.0
    return {
        "late_n": len(late), "none_late": acc(late, "none"), f"{arm}_late": acc(late, arm),
        "diff_late": acc(late, arm) - acc(late, "none"),
        "fixes_late": sum(r[f"{arm}_ok"] and not r["none_ok"] for r in late),
        "regressions_late": sum(r["none_ok"] and not r[f"{arm}_ok"] for r in late),
        "none_all": acc(recs, "none"), f"{arm}_all": acc(recs, arm),
        "curve": [(acc(q, "none"), acc(q, arm)) for q in quarters],
        "memory": [q[-1]["memory_size"] if q else 0 for q in quarters],
        "injection_rate": injected, "inert": injected < inert_below,
    }


def pooled_diff(streams):
    """Second-half facts-minus-none accuracy over all pairs of the given streams."""
    pairs = sum(s["late_n"] for s in streams)
    return sum(s["fixes_late"] - s["regressions_late"] for s in streams) / pairs if pairs else 0.0


def bootstrap_ci(groups, stat, iters=4000, seed=0):
    """95% CI of stat(items of the resampled groups), resampling whole groups with replacement."""
    rng = np.random.default_rng(seed)
    draws = [stat([x for i in rng.integers(0, len(groups), len(groups)) for x in groups[i]]) for _ in range(iters)]
    return float(np.percentile(draws, 2.5)), float(np.percentile(draws, 97.5))


def sign_flip_p(diffs, iters=20000, seed=0):
    """Heuristic two-sided sign-flip test on paired per-question differences (-1, 0, +1)."""
    d = np.asarray([x for x in diffs if x != 0], float)
    if not len(d):
        return 1.0
    rng = np.random.default_rng(seed)
    flips = np.abs((rng.choice([-1, 1], (iters, len(d))) * d).sum(axis=1))
    return float((flips >= abs(d.sum())).mean())


def primary_section(stats, runs, inert_below, arm="facts"):
    """Per-stream second-half table for one arm vs none, direction count, and the tests that fit the number of databases."""
    shown = {"facts": "facts injected", "examples": "examples shown"}[arm]
    lines = [f"## Primary: second half of each stream ({arm} vs none)", "",
             f"| Order | Database | Questions (2nd half) | None | {arm.title()} | Diff | Fixes / regressions | Injection rate |",
             "|---|---|---|---|---|---|---|---|"]
    for (seed, db), s in stats.items():
        lines.append(f"| {seed} | {db} | {s['late_n']} | {s['none_late']:.3f} | {s[f'{arm}_late']:.3f} | "
                     f"{s['diff_late']:+.3f} | +{s['fixes_late']} / -{s['regressions_late']} | "
                     f"{s['injection_rate']:.0%}{' (inert)' if s['inert'] else ''} |")

    streams = list(stats.values())
    up, down = sum(s["diff_late"] > 0 for s in streams), sum(s["diff_late"] < 0 for s in streams)
    lines += ["", f"- **Direction count:** {up} of {len(streams)} streams positive, {down} negative, "
                  f"{len(streams) - up - down} tied."]

    dbs = list(dict.fromkeys(d for _, d in stats))
    if len(dbs) > 1:
        lo, hi = bootstrap_ci([[s for (_, d), s in stats.items() if d == db] for db in dbs], pooled_diff)
        without = [f"without {db} {pooled_diff([s for (_, d), s in stats.items() if d != db]):+.3f}" for db in dbs]
        lines += [f"- **Pooled second-half difference:** {pooled_diff(streams):+.3f} (95% CI {lo:+.3f} to {hi:+.3f}, "
                  "resampling databases with both orders together).",
                  f"- **Leave one database out:** {', '.join(without)}."]
    else:
        lines += ["- **One database:** question-level counts and the learning curve carry the result."]

    # Heuristic: questions as units, the two orders of a question kept together as one cluster.
    clusters = {}
    for (_, db), recs in runs.items():
        for r in recs:
            if r["pos"] > len(recs) / 2:
                clusters.setdefault((db, r["qid"]), []).append(int(r[f"{arm}_ok"]) - int(r["none_ok"]))
    diffs = list(clusters.values())
    q_lo, q_hi = bootstrap_ci(diffs, lambda xs: float(np.mean(xs)) if xs else 0.0)

    return lines + [
        f"- **Heuristic, not exact (ignores dependence within a stream):** question-level sign-flip "
        f"p = {sign_flip_p([x for d in diffs for x in d]):.3f}; question-clustered 95% CI {q_lo:+.3f} to {q_hi:+.3f}.",
        f"- **Injection check:** {sum(s['inert'] for s in streams)} of {len(streams)} streams inert ({shown} on "
        f"fewer than {inert_below:.0%} of second-half questions). Where the arm is inert, a null result means the "
        "memory was rarely used, not that memory cannot help.",
    ]


def whole_stream_section(stats, arms):
    """Whole-stream accuracies and the quarter-by-quarter learning curve of none and each arm."""
    heads = ["None (all)"] + [f"{a.title()} (all)" for a in arms]
    lines = ["", "## Whole stream, learning curve and memory size", "",
             f"| Order | Database | {' | '.join(heads)} | Quarters {' / '.join(['none', *arms])} | "
             "Active facts at each quarter |", "|---|---|" + "---|" * (len(heads) + 2)]
    for key, first in stats["facts"].items():
        accs = [f"{first['none_all']:.3f}"] + [f"{stats[a][key][f'{a}_all']:.3f}" for a in arms]
        quarters = [(first["curve"][i][0], *(stats[a][key]["curve"][i][1] for a in arms)) for i in range(4)]
        curve = " · ".join("/".join(f"{x:.2f}" for x in q) for q in quarters)
        lines.append(f"| {key[0]} | {key[1]} | {' | '.join(accs)} | {curve} | {' · '.join(map(str, first['memory']))} |")
    return lines


def first_occurrences(recs):
    """The first record of each template, in stream order."""
    seen, firsts = set(), []
    for r in recs:
        if r.get("template") is not None and r["template"] not in seen:
            seen.add(r["template"])
            firsts.append(r)
    return firsts


def first_occurrence_section(complete, arms):
    """Accuracy of each arm on the first question of every template, before any same-template question is revealed."""
    firsts = [r for recs in complete.values() for r in first_occurrences(recs)]
    if not firsts:
        return []

    lines = ["", "## First occurrences", "",
             f"Accuracy on the {len(firsts)} questions that are the first of their template in the stream.", "",
             "| Arm | Correct | Accuracy |", "|---|---|---|"]
    for arm in ("none", *arms):
        correct = sum(r[f"{arm}_ok"] for r in firsts)
        lines.append(f"| {arm} | {correct}/{len(firsts)} | {correct / len(firsts):.3f} |")
    return lines + ["", "The main results include all questions."]


def template_match_split(recs):
    """Examples vs none per group: a shown example had the question's template, only other templates, or none shown."""
    groups = {"same template shown": [], "other templates only": [], "no examples shown": []}
    for r in recs:
        if not r["examples_used"]:
            groups["no examples shown"].append(r)
        elif any(r["examples_same_template"]):
            groups["same template shown"].append(r)
        else:
            groups["other templates only"].append(r)

    return {g: {"n": len(rs), "fixes": sum(r["examples_ok"] and not r["none_ok"] for r in rs),
                "regressions": sum(r["none_ok"] and not r["examples_ok"] for r in rs),
                "none_ok": sum(r["none_ok"] for r in rs), "examples_ok": sum(r["examples_ok"] for r in rs)}
            for g, rs in groups.items()}


def template_match_section(complete):
    """Examples arm fixes and regressions against none, by whether a shown example came from the same template."""
    recs = [r for rs in complete.values() for r in rs]
    lines = ["", "## Examples by template match", "",
             "| Group | Questions | Fixes | Regressions | None accuracy | Examples accuracy |", "|---|---|---|---|---|---|"]
    for group, g in template_match_split(recs).items():
        n = max(1, g["n"])
        lines.append(f"| {group} | {g['n']} | {g['fixes']} | {g['regressions']} | {g['none_ok'] / n:.3f} | "
                     f"{g['examples_ok'] / n:.3f} |")
    return lines


def cost_section(recs, cfg, budget_usd, spend, passes=(), arms=("facts",)):
    """Logical cost per part, $ per correct answer, original API latency and agent turns."""
    agent_p, prop_p = cfg["agent"].get("usd_per_million"), cfg["proposer"].get("usd_per_million")
    events = [r["learning"] for r in recs if r["learning"]]
    cost = {arm: sum(usd(r["usage"][arm], agent_p) for r in recs) for arm in ("none", *arms)}
    cost |= {"proposer": sum(usd(e["usage"]["proposer"], prop_p) for e in events),
             "pre-check": sum(usd(e["usage"]["precheck"], agent_p) for e in events),
             "consolidation proposer": sum(usd(p["usage"]["proposer"], prop_p) for p in passes if "usage" in p),
             "consolidation pre-check": sum(usd(p["usage"]["precheck"], agent_p) for p in passes if "usage" in p),
             "JEV": sum(r.get("jev_usd", 0) for r in recs) + sum(p.get("jev_usd", 0) for p in passes)}
    correct = {arm: max(1, sum(r[f"{arm}_ok"] for r in recs)) for arm in ("none", *arms)}

    # Learning, pre-checks and JEV belong to the facts arm; the examples arm has no learning call.
    totals = {"none": cost["none"], "examples": cost.get("examples", 0.0),
              "facts": sum(v for k, v in cost.items() if k not in ("none", "examples"))}
    per_correct = [f"{arm} ${totals[arm] / correct[arm]:.4f}" + (" (learning included)" if arm == "facts" else "")
                   for arm in ("none", *arms)]

    column = {"none": 0, "facts": 1, "examples": 2}
    latency, turns = [], []
    for arm in ("none", *arms):
        p50, p95 = np.percentile([r["latency_s"][column[arm]] for r in recs] or [0], [50, 95])
        latency.append(f"{arm} {p50:.1f} / {p95:.1f}")
        turns.append(f"{arm} {np.mean([r['turns'][column[arm]] for r in recs] or [0]):.1f}")

    return ["", "## Cost, latency, turns", "",
            "- Logical cost (peak prices; a prompt answered once per run is counted once): "
            + ", ".join(f"{k} ${v:.3f}" for k, v in cost.items()) + ".",
            f"- $ per correct answer: {', '.join(per_correct)}. Real API spend: ${spend:.3f} of ${budget_usd:.2f}.",
            f"- Latency (original API time per answer) p50 / p95 s: {', '.join(latency)}.",
            f"- Agent turns: {', '.join(turns)}."]


def jev_section(complete, cutoff):
    """How many facts JEV let through: questions with a fact, facts per question, cutoff hits and JEV cost."""
    recs = [r for rs in complete.values() for r in rs]
    if not recs:
        return ["", "## JEV selection", "", "Not run yet."]
    scores = [x for r in recs for x in r.get("jev_scores", {}).values()]
    hits = sum(x >= cutoff for x in scores)
    return ["", "## JEV selection", "",
            f"- Questions with at least one injected fact: {sum(bool(r['injected']) for r in recs)} of {len(recs)}; "
            f"mean facts injected per question {np.mean([len(r['injected']) for r in recs]):.2f}.",
            f"- Fact scores at or above the cutoff {cutoff}: {hits} of {len(scores)}.",
            f"- JEV cost in the stream: ${sum(r.get('jev_usd', 0) for r in recs):.4f}."]


def read_consolidation(out, seeds_dbs):
    """{(seed, db): pass records} of the consolidation logs that exist."""
    return {(s, d): read_jsonl(consolidation_log(out, s, d)) for s, d in seeds_dbs}


def consolidation_section(out, seeds_dbs):
    """Passes run and skipped, edits proposed / applied / rejected by op, and the applied edits."""
    passes = {k: ps for k, ps in read_consolidation(out, seeds_dbs).items() if ps}
    if not passes:
        return ["", "## Consolidation", "", "Not run yet."]

    everything = [p for ps in passes.values() for p in ps]
    edits = [(k, e) for k, ps in passes.items() for p in ps for e in p.get("edits", [])]
    applied = [(k, e) for k, e in edits if e["applied"]]
    lines = ["", "## Consolidation", "",
             f"- Passes: {sum('skipped' not in p for p in everything)} run, "
             f"{sum('skipped' in p for p in everything)} skipped for budget.",
             f"- Edits proposed {dict(Counter(e['op'] for _, e in edits))}, applied "
             f"{dict(Counter(e['op'] for _, e in applied))}, rejected "
             f"{dict(Counter(e['op'] for _, e in edits if e.get('rejected')))}.",
             f"- Rejection reasons: {dict(Counter(str(e['rejected']) for _, e in edits if e.get('rejected')))}."]
    for (seed, db), e in applied[:10]:
        target = e["fact"].get("id", "new fact") if e["fact"] else "dropped"
        lines.append(f"- Applied (order {seed}, {db}): {e['op']} {', '.join(e['ids'])} -> {target}: {e['reason']}")
    if len(applied) > 10:
        lines.append(f"- ... and {len(applied) - 10} more applied edits.")
    return lines


def snippet_section(complete, out):
    """Snippets kept or dropped when facts were learned, and how often facts with SQL were injected."""
    events = [r["learning"] for rs in complete.values() for r in rs if r["learning"]]
    if not events:
        return ["", "## Snippets", "", "Not run yet."]

    outcomes = Counter(e["snippet"] for e in events if e.get("snippet") is not None)

    with_sql, total, injections, sql_injections = 0, 0, 0, 0
    for (seed, db), recs in complete.items():
        path = facts_file(out, seed, db)
        facts = json.loads(path.read_text()) if path.exists() else []
        sql_ids = {f["id"] for f in facts if f.get("sql")}
        with_sql, total = with_sql + len(sql_ids), total + len(facts)
        ids = [i for r in recs for i in r["injected"]]
        injections, sql_injections = injections + len(ids), sql_injections + sum(i in sql_ids for i in ids)
    return ["", "## Snippets", "",
            f"- Snippets by outcome: {dict(outcomes) or 'none proposed'}.",
            f"- Facts with SQL in the final facts files: {with_sql} of {total}.",
            f"- Injections of a fact with SQL: {sql_injections} of {injections}."]


def probe_section(out):
    """Level by arm table of correct/n, with fixes and regressions against the none arm."""
    recs = read_jsonl(Path(out) / "probe_v7.jsonl")
    if not recs:
        return ["", "## Probe", "", "Not run yet."]

    lines = ["", "## Probe (frozen memory, level by arm: correct / questions, +fixes / -regressions vs none)", "",
             "| Level | " + " | ".join(ARMS) + " |", "|---|" + "---|" * len(ARMS)]
    for level in (*LEVELS, "all"):
        rows = [r for r in recs if level == "all" or r["level"] == level]
        cells = []
        for arm in ARMS:
            cell = f"{sum(r['arms'][arm]['ok'] for r in rows)}/{len(rows)}"
            if arm != "none":
                fixes = sum(r["arms"][arm]["ok"] and not r["arms"]["none"]["ok"] for r in rows)
                regressions = sum(r["arms"]["none"]["ok"] and not r["arms"][arm]["ok"] for r in rows)
                cell += f" (+{fixes} / -{regressions})"
            cells.append(cell)
        lines.append(f"| {level} | " + " | ".join(cells) + " |")
    return lines + ["", "A controlled check with 6-8 questions per level: raw counts, no p-values."]


def learning_section(complete, out):
    """Learning outcomes, then each stream's facts with score, uses and retirement."""
    events = [r["learning"] for recs in complete.values() for r in recs if r["learning"]]
    outcomes = Counter(e["outcome"] if e["outcome"] != "dropped" else "dropped: " + e["reason"].split(":")[0]
                       for e in events)
    lines = ["", "## Learning", "", f"- Learning events: {len(events)}; outcomes: {dict(outcomes)}."]
    for seed, db in complete:
        path = facts_file(out, seed, db)
        facts = json.loads(path.read_text()) if path.exists() else []
        retired = Counter(f["retired"] for f in facts if f.get("retired"))
        lines += ["", f"### Order {seed}, {db}: {len(facts)} facts, retired {dict(retired) or 'none'}", "", "```"]
        for f in facts:
            state = f" RETIRED ({f['retired']})" if f.get("retired") else ""
            lines.append(f"{f['id']} score {f.get('score', 0):+d} uses {f.get('uses', 0)}{state} [{f['kind']}] "
                         f"{f['subject']}: {f['fact']}  (applies to: {', '.join(f['applies_to'])})")
        lines.append("```")
    return lines


def report(cfg):
    sc, out = cfg["stream"], Path(cfg["runs_dir"])
    sizes = Counter(entry["db_id"] for entry in json.loads(Path(sc["questions"]).read_text()))
    runs = {(s, d): read_jsonl(stream_log(out, s, d)) for s in sc["seeds"] for d in sc["databases"]}
    complete = {k: r for k, r in runs.items() if len(r) == sizes[k[1]]}

    has_examples = any("examples_ok" in r for rs in complete.values() for r in rs)
    arms = ["facts", "examples"] if has_examples else ["facts"]
    stats = {arm: {k: stream_stats(r, sc["inert_below"], arm) for k, r in complete.items()} for arm in arms}

    lines = ["# EvoSQL v8 results", "",
             "Online memory on EHRSQL (MIMIC-IV demo): 119 questions from 17 recurring templates, with the correct SQL "
             "revealed after each answer. Facts (JEV selection, consolidation, SQL snippets, DeepSeek V4 Pro proposer) "
             "and examples (the 2 most similar earlier questions with their correct SQL) are each compared with no "
             "memory.", ""]
    partial = [f"order {s} {d} ({len(r)}/{sizes[d]})" for (s, d), r in runs.items() if r and (s, d) not in complete]
    if partial:
        lines += [f"**Incomplete streams, not analysed:** {', '.join(partial)}.", ""]
    if all((sc["seeds"][0], d) in complete for d in sc["databases"]):
        for arm in arms:
            lines += ([""] if arm != "facts" else []) + primary_section(stats[arm], complete, sc["inert_below"], arm)
    else:
        lines += ["No primary claim: the first order has not completed for every database."]

    lines += whole_stream_section(stats, arms)
    if any(r.get("template") for rs in complete.values() for r in rs):
        lines += first_occurrence_section(complete, arms)
    if has_examples:
        lines += template_match_section(complete)

    seeds_dbs = [(s, d) for s in sc["seeds"] for d in sc["databases"]]
    passes = [p for ps in read_consolidation(out, seeds_dbs).values() for p in ps]
    spend = Budget(out / "spend.json", sc["budget_usd"]).total
    lines += jev_section(complete, sc["rules"]["cutoff"])
    lines += consolidation_section(out, seeds_dbs)
    lines += snippet_section(complete, out)
    if "probe" in cfg:
        lines += probe_section(out)
    lines += cost_section([r for rs in complete.values() for r in rs], cfg, sc["budget_usd"], spend, passes, arms)
    lines += learning_section(complete, out)

    manifest = Path(sc["questions"]).parent / "manifest.json"
    if manifest.exists():
        m = json.loads(manifest.read_text())
        stream = m["stream"]
        lines += ["", "## Pinned data", "", f"`{m['repo']}` at commit `{m['commit']}`. Stream: {stream['questions']} "
                  f"questions from {stream['templates']} templates.", "", "```",
                  f"{stream['sha256'][:16]}  {stream['path']}"]
        lines += [f"{h[:16]}  {p}" for p, h in m["files"].items()] + ["```"]

    write_atomic(Path(cfg["results_dir"]) / "summary.md", "\n".join(lines) + "\n")
    print("\n".join(lines))
