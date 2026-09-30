"""v6 report. Each complete (order, database) stream is one unit of evidence: the primary result is second-half accuracy
of facts vs none per stream, the direction count, and a bootstrap that resamples databases (both orders together).
Question-level statistics ignore the dependence within a stream and are labelled heuristic."""
import json
from collections import Counter
from pathlib import Path

import numpy as np

from evosql.bird import load_arcwise
from evosql.budget import Budget
from evosql.files import read_jsonl, write_atomic
from evosql.llm import usd
from evosql.stream import facts_file, stream_log


def stream_stats(recs, inert_below):
    """Second-half and whole-stream results of one complete stream (records in stream order)."""
    n = len(recs)
    late = [r for r in recs if r["pos"] > n / 2]
    acc = lambda rs, arm: sum(r[f"{arm}_ok"] for r in rs) / len(rs) if rs else 0.0
    quarters = [recs[i * n // 4:(i + 1) * n // 4] for i in range(4)]
    injected = sum(bool(r["injected"]) for r in late) / len(late) if late else 0.0
    return {
        "late_n": len(late), "none_late": acc(late, "none"), "facts_late": acc(late, "facts"),
        "diff_late": acc(late, "facts") - acc(late, "none"),
        "fixes_late": sum(r["facts_ok"] and not r["none_ok"] for r in late),
        "regressions_late": sum(r["none_ok"] and not r["facts_ok"] for r in late),
        "none_all": acc(recs, "none"), "facts_all": acc(recs, "facts"),
        "curve": [(acc(q, "none"), acc(q, "facts")) for q in quarters],
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


def primary_section(stats, runs, inert_below):
    """Per-stream second-half table, direction count, database-level bootstrap and heuristic question-level tests."""
    lines = ["## Primary: second half of each stream (facts vs none)", "",
             "| Order | Database | Questions (2nd half) | None | Facts | Diff | Fixes / regressions | Injection rate |",
             "|---|---|---|---|---|---|---|---|"]
    for (seed, db), s in stats.items():
        lines.append(f"| {seed} | {db} | {s['late_n']} | {s['none_late']:.3f} | {s['facts_late']:.3f} | "
                     f"{s['diff_late']:+.3f} | +{s['fixes_late']} / -{s['regressions_late']} | "
                     f"{s['injection_rate']:.0%}{' (inert)' if s['inert'] else ''} |")

    streams = list(stats.values())
    up, down = sum(s["diff_late"] > 0 for s in streams), sum(s["diff_late"] < 0 for s in streams)
    dbs = list(dict.fromkeys(d for _, d in stats))
    lo, hi = bootstrap_ci([[s for (_, d), s in stats.items() if d == db] for db in dbs], pooled_diff)
    without = [f"without {db} {pooled_diff([s for (_, d), s in stats.items() if d != db]):+.3f}" for db in dbs]

    # Heuristic: questions as units, the two orders of a question kept together as one cluster.
    clusters = {}
    for (_, db), recs in runs.items():
        for r in recs:
            if r["pos"] > len(recs) / 2:
                clusters.setdefault((db, r["qid"]), []).append(int(r["facts_ok"]) - int(r["none_ok"]))
    diffs = list(clusters.values())
    q_lo, q_hi = bootstrap_ci(diffs, lambda xs: float(np.mean(xs)) if xs else 0.0)

    return lines + [
        "",
        f"- **Direction count:** {up} of {len(streams)} streams positive, {down} negative, "
        f"{len(streams) - up - down} tied.",
        f"- **Pooled second-half difference:** {pooled_diff(streams):+.3f} (95% CI {lo:+.3f} to {hi:+.3f}, resampling "
        "databases with both orders together).",
        f"- **Leave one database out:** {', '.join(without)}.",
        f"- **Heuristic, not exact (ignores dependence within a stream):** question-level sign-flip "
        f"p = {sign_flip_p([x for d in diffs for x in d]):.3f}; question-clustered 95% CI {q_lo:+.3f} to {q_hi:+.3f}.",
        f"- **Injection check:** {sum(s['inert'] for s in streams)} of {len(streams)} streams inert (facts injected on "
        f"fewer than {inert_below:.0%} of second-half questions). Where the arm is inert, a null result means the "
        "memory was rarely used, not that memory cannot help.",
    ]


def cost_section(recs, cfg, budget_usd, spend):
    """Logical cost per part, $ per correct answer, original API latency and agent turns."""
    agent_p, prop_p = cfg["agent"].get("usd_per_million"), cfg["proposer"].get("usd_per_million")
    events = [r["learning"] for r in recs if r["learning"]]
    cost = {"none": sum(usd(r["usage"]["none"], agent_p) for r in recs),
            "facts": sum(usd(r["usage"]["facts"], agent_p) for r in recs),
            "proposer": sum(usd(e["usage"]["proposer"], prop_p) for e in events),
            "pre-check": sum(usd(e["usage"]["precheck"], agent_p) for e in events)}
    correct = {arm: max(1, sum(r[f"{arm}_ok"] for r in recs)) for arm in ("none", "facts")}
    facts_total = cost["facts"] + cost["proposer"] + cost["pre-check"]
    p50, p95 = {}, {}
    for i, arm in enumerate(("none", "facts")):
        p50[arm], p95[arm] = np.percentile([r["latency_s"][i] for r in recs] or [0], [50, 95])

    return ["", "## Cost, latency, turns", "",
            "- Logical cost (peak prices; a prompt answered once per run is counted once): "
            + ", ".join(f"{k} ${v:.3f}" for k, v in cost.items()) + ".",
            f"- $ per correct answer: none ${cost['none'] / correct['none']:.4f}, facts (learning included) "
            f"${facts_total / correct['facts']:.4f}. Real API spend: ${spend:.3f} of ${budget_usd:.2f}.",
            f"- Latency (original API time per answer) p50 / p95 s: none {p50['none']:.1f} / {p95['none']:.1f}, "
            f"facts {p50['facts']:.1f} / {p95['facts']:.1f}.",
            f"- Agent turns: none {np.mean([r['turns'][0] for r in recs] or [0]):.1f}, "
            f"facts {np.mean([r['turns'][1] for r in recs] or [0]):.1f}."]


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
    sizes = Counter(q.db_id for q in load_arcwise(sc["questions"], set(sc["databases"])))
    runs = {(s, d): read_jsonl(stream_log(out, s, d)) for s in sc["seeds"] for d in sc["databases"]}
    complete = {k: r for k, r in runs.items() if len(r) == sizes[k[1]]}
    stats = {k: stream_stats(r, sc["inert_below"]) for k, r in complete.items()}

    lines = ["# EvoSQL v6 results", "",
             "Online per-database fact memory vs no memory on Arcwise-Plat (corrected BIRD Mini-Dev), with the correct "
             "SQL revealed after each answer. Each complete (order, database) stream is one unit of evidence.", ""]
    partial = [f"order {s} {d} ({len(r)}/{sizes[d]})" for (s, d), r in runs.items() if r and (s, d) not in complete]
    if partial:
        lines += [f"**Incomplete streams, not analysed:** {', '.join(partial)}.", ""]
    if all((sc["seeds"][0], d) in complete for d in sc["databases"]):
        lines += primary_section(stats, complete, sc["inert_below"])
    else:
        lines += ["No primary claim: the first order has not completed for every database."]

    lines += ["", "## Whole stream, learning curve and memory size", "",
              "| Order | Database | None (all) | Facts (all) | Quarters none / facts | Active facts at each quarter |",
              "|---|---|---|---|---|---|"]
    for (seed, db), s in stats.items():
        curve = " · ".join(f"{a:.2f}/{b:.2f}" for a, b in s["curve"])
        lines.append(f"| {seed} | {db} | {s['none_all']:.3f} | {s['facts_all']:.3f} | {curve} | "
                     f"{' · '.join(map(str, s['memory']))} |")

    spend = Budget(out / "spend.json", sc["budget_usd"]).total
    lines += cost_section([r for rs in complete.values() for r in rs], cfg, sc["budget_usd"], spend)
    lines += learning_section(complete, out)

    manifest = Path(sc["questions"]).parent / "manifest.json"
    if manifest.exists():
        m = json.loads(manifest.read_text())
        lines += ["", "## Pinned data", "", f"Arcwise commit `{m['arcwise_commit']}`; questions per database "
                  f"{m['questions_per_db']}.", "", "```"] + [f"{h[:16]}  {p}" for p, h in m["sha256"].items()] + ["```"]

    write_atomic(Path(cfg["results_dir"]) / "summary.md", "\n".join(lines) + "\n")
    print("\n".join(lines))
