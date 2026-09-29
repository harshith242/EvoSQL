"""v6 report: each (order, database) stream is one unit of evidence. The primary result is second-half accuracy of
facts vs none per stream, the direction count over streams and a stream-level block bootstrap; question-level tests
ignore the sequential dependence within a stream and are labelled heuristic."""
import json
from collections import Counter
from pathlib import Path

import numpy as np

from evosql.files import read_jsonl, write_atomic
from evosql.llm import usd


def stream_stats(recs, inert_below):
    """Second-half and whole-stream results of one stream (records in stream order)."""
    n = len(recs)
    late = [r for r in recs if r["pos"] > n / 2]
    acc = lambda rs, arm: sum(r[f"{arm}_ok"] for r in rs) / len(rs) if rs else 0.0
    quarters = [recs[i * n // 4:(i + 1) * n // 4] for i in range(4)]
    injected = sum(bool(r["injected"]) for r in late) / len(late) if late else 0.0
    return {
        "n": n, "late_n": len(late), "none_late": acc(late, "none"), "facts_late": acc(late, "facts"),
        "diff_late": acc(late, "facts") - acc(late, "none"),
        "fixes_late": sum(r["facts_ok"] and not r["none_ok"] for r in late),
        "regressions_late": sum(r["none_ok"] and not r["facts_ok"] for r in late),
        "none_all": acc(recs, "none"), "facts_all": acc(recs, "facts"),
        "curve": [(round(acc(q, "none"), 2), round(acc(q, "facts"), 2)) for q in quarters],
        "injection_rate": injected, "inert": injected < inert_below,
    }


def pooled_diff(streams):
    """Second-half facts-minus-none accuracy over all pairs of the given streams."""
    pairs = sum(s["late_n"] for s in streams)
    return sum(s["fixes_late"] - s["regressions_late"] for s in streams) / pairs if pairs else 0.0


def block_bootstrap(streams, iters=4000, seed=0):
    """95% CI of the pooled difference, resampling whole streams (the independent units)."""
    rng = np.random.default_rng(seed)
    draws = [pooled_diff([streams[i] for i in rng.integers(0, len(streams), len(streams))]) for _ in range(iters)]
    return float(np.percentile(draws, 2.5)), float(np.percentile(draws, 97.5))


def sign_flip_p(diffs, iters=20000, seed=0):
    """Heuristic two-sided sign-flip test on paired per-question differences (-1, 0, +1)."""
    d = np.asarray([x for x in diffs if x != 0], float)
    if not len(d):
        return 1.0
    rng = np.random.default_rng(seed)
    flips = np.abs((rng.choice([-1, 1], (iters, len(d))) * d).sum(axis=1))
    return float((flips >= abs(d.sum())).mean())


def _usd(usage, prices):
    return usd(usage, prices) if usage else 0.0


def report(cfg):
    sc, out = cfg["stream"], Path(cfg["runs_dir"])
    inert_below = sc["inert_below"]
    agent_p, prop_p = cfg["agent"].get("usd_per_million"), cfg["proposer"].get("usd_per_million")
    names = [(s, db) for s in sc["seeds"] for db in sc["databases"]]
    runs = {k: read_jsonl(out / f"stream_s{k[0]}_{k[1]}.jsonl") for k in names}
    runs = {k: r for k, r in runs.items() if r}
    stats = {k: stream_stats(r, inert_below) for k, r in runs.items()}
    lines = ["# EvoSQL v6 results", "",
             "Online per-database fact memory vs no memory, Arcwise-Plat (corrected BIRD Mini-Dev), gold SQL revealed "
             "after each answer. Each (order, database) stream is one unit of evidence.", ""]
    if len(stats) < len(names):
        lines += [f"**Incomplete:** {len(stats)} of {len(names)} streams have results.", ""]

    lines += ["## Primary: second half of each stream (facts vs none)", "",
              "| Order | Database | Questions (2nd half) | None | Facts | Diff | Fixes / regressions | Injection rate |",
              "|---|---|---|---|---|---|---|---|"]
    for (seed, db), s in stats.items():
        lines.append(f"| {seed} | {db} | {s['late_n']} | {s['none_late']:.3f} | {s['facts_late']:.3f} | "
                     f"{s['diff_late']:+.3f} | +{s['fixes_late']} / -{s['regressions_late']} | "
                     f"{s['injection_rate']:.0%}{' (inert)' if s['inert'] else ''} |")
    streams = list(stats.values())
    if streams:
        up, down = sum(s["diff_late"] > 0 for s in streams), sum(s["diff_late"] < 0 for s in streams)
        lo, hi = block_bootstrap(streams)
        lines += ["", f"- **Direction count:** {up} of {len(streams)} streams positive, {down} negative, "
                      f"{len(streams) - up - down} tied.",
                  f"- **Pooled second-half difference:** {pooled_diff(streams):+.3f} "
                  f"(stream-level block bootstrap 95% CI {lo:+.3f} to {hi:+.3f}).",
                  "- **Leave one database out:** " + ", ".join(
                      f"without {db} {pooled_diff([s for (_, d), s in stats.items() if d != db]):+.3f}"
                      for db in sc["databases"] if any(d == db for _, d in stats)) + "."]
        diffs = [int(r["facts_ok"]) - int(r["none_ok"]) for k, recs in runs.items() for r in recs
                 if r["pos"] > len(recs) / 2]
        lines += [f"- **Heuristic (ignores dependence within a stream, not an exact test):** question-level sign-flip "
                  f"p = {sign_flip_p(diffs):.3f} over {len(diffs)} pairs.",
                  f"- **Injection check:** {sum(s['inert'] for s in streams)} of {len(streams)} streams inert "
                  f"(facts injected on fewer than {inert_below:.0%} of second-half questions). Where the arm is inert, "
                  "a null result means the memory was rarely used, not that memory cannot help."]

    lines += ["", "## Whole stream and learning curve", "",
              "| Order | Database | None (all) | Facts (all) | Quarters none / facts |", "|---|---|---|---|---|"]
    for (seed, db), s in stats.items():
        curve = " · ".join(f"{a:.2f}/{b:.2f}" for a, b in s["curve"])
        lines.append(f"| {seed} | {db} | {s['none_all']:.3f} | {s['facts_all']:.3f} | {curve} |")

    recs = [r for rs in runs.values() for r in rs]
    events = [r["learning"] for r in recs if r["learning"]]
    cost = {"none": sum(_usd(r["usage"]["none"], agent_p) for r in recs),
            "facts": sum(_usd(r["usage"]["facts"], agent_p) for r in recs),
            "proposer": sum(_usd(e["usage"]["proposer"], prop_p) for e in events),
            "pre-check": sum(_usd(e["usage"]["precheck"], agent_p) for e in events)}
    lat = lambda arm: [r["usage"][arm].get("latency_s", 0.0) for r in recs]
    spend = json.loads((out / "spend.json").read_text())["usd"] if (out / "spend.json").exists() else 0.0
    lines += ["", "## Cost, latency, turns", "",
              f"- Logical cost (peak prices; replays counted once per run): " +
              ", ".join(f"{k} ${v:.3f}" for k, v in cost.items()) + f". Real API spend: ${spend:.3f} of "
              f"${sc['budget_usd']:.2f}.",
              f"- Latency p50 / p95 s: none {np.percentile(lat('none') or [0], 50):.1f} / "
              f"{np.percentile(lat('none') or [0], 95):.1f}, facts {np.percentile(lat('facts') or [0], 50):.1f} / "
              f"{np.percentile(lat('facts') or [0], 95):.1f}.",
              f"- Agent turns: none {np.mean([r['turns'][0] for r in recs] or [0]):.1f}, "
              f"facts {np.mean([r['turns'][1] for r in recs] or [0]):.1f}."]

    outcomes = Counter(e["outcome"] if e["outcome"] != "dropped" else "dropped: " + e["reason"].split(":")[0]
                       for e in events)
    lines += ["", "## Learning", "", f"- Learning events: {len(events)}; outcomes: {dict(outcomes)}."]
    for (seed, db) in stats:
        path = out / f"facts_s{seed}_{db}.json"
        facts = json.loads(path.read_text()) if path.exists() else []
        retired = Counter(f["retired"] for f in facts if f.get("retired"))
        lines += ["", f"### Order {seed}, {db}: {len(facts)} facts, retired {dict(retired) or 'none'}", "", "```"]
        lines += [f"{f['id']} score {f.get('score', 0):+d} uses {f.get('uses', 0)}"
                  f"{' RETIRED (' + f['retired'] + ')' if f.get('retired') else ''} [{f['kind']}] {f['subject']}: "
                  f"{f['fact']}  (applies to: {', '.join(f['applies_to'])})" for f in facts] + ["```"]

    manifest = Path(sc["questions"]).parent / "manifest.json"
    if manifest.exists():
        m = json.loads(manifest.read_text())
        lines += ["", "## Pinned data", "", f"- Arcwise commit {m['arcwise_commit']}; questions per database "
                  f"{m['questions_per_db']}; {len(m['sha256'])} files hashed in `{manifest}`."]
    write_atomic(Path(cfg["results_dir"]) / "summary.md", "\n".join(lines) + "\n")
    print("\n".join(lines))
