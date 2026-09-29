"""Runs and report: any delivery mode answers any question set (official and corrected scoring, latency, knowledge use).
The one-shot gate picks the headline mode on the gate set; analyze compares every mode with docs on the final set."""
import hashlib
import json
from collections import Counter
from pathlib import Path

import numpy as np
from scipy.stats import binomtest
from tqdm import tqdm

from evosql.agent import answer
from evosql.bird import exec_match, gold_rows, load_hints
from evosql.budget import Budget, BudgetExceeded
from evosql.config import KNOWLEDGE, NO_FACTS, split_arm
from evosql.delivery import make_delivery
from evosql.facts import FactBook
from evosql.files import append_jsonl, read_jsonl, write_atomic
from evosql.labels import corrected, corrected_gold
from evosql.llm import ProviderExhausted, make_llm, usd
from evosql.split import load_run

def mcnemar(a, b):
    """Two-sided exact McNemar p-value for paired boolean outcomes."""
    a, b = np.asarray(a, bool), np.asarray(b, bool)
    only_a, only_b = int(np.sum(a & ~b)), int(np.sum(~a & b))
    return binomtest(only_a, only_a + only_b, 0.5).pvalue if only_a + only_b else 1.0


def bootstrap_ci(values, iters=2000, seed=0):
    """95% bootstrap CI of the mean (accuracy for booleans, accuracy difference for paired -1/0/1)."""
    rng, x = np.random.default_rng(seed), np.asarray(values, float)
    means = [x[rng.integers(0, len(x), len(x))].mean() for _ in range(iters)]
    return float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5))


def arm_book(out, arm):
    mode, variant = split_arm(arm)
    if mode in NO_FACTS:
        return FactBook()
    path = Path(out) / KNOWLEDGE[variant]
    if not path.exists():
        raise SystemExit(f"{arm} needs {path}: run `python -m evosql discover` first")
    return FactBook.load(path)


def setup_digest(book, arm, cfg):
    """Id of what an arm's answers depend on: no facts (docs), the facts, plus the search settings (retrieve, tool)."""
    mode = split_arm(arm)[0]
    if mode not in ("retrieve", "tool"):
        return (FactBook() if mode in NO_FACTS else book).digest()
    return hashlib.sha256((book.digest() + json.dumps(cfg["search"], sort_keys=True)).encode()).hexdigest()[:12]


def run_mode(cfg, arm, set_name, agent_llm=None, knowledge=None):
    """Answer every question of a set with one arm; resumes by skipping logged questions."""
    out, parts, db, by_id = load_run(cfg)
    book = arm_book(out, arm)
    knowledge = knowledge or make_delivery(split_arm(arm)[0], book, cfg["search"], load_hints(cfg["data_dir"], cfg["db"]))
    fixes = corrected(cfg["data_dir"], cfg["db"])
    setup = setup_digest(book, arm, cfg)
    log_path = out / f"{set_name}_{arm}.jsonl"
    done = read_jsonl(log_path)
    if done and done[0]["knowledge"] != setup:
        raise SystemExit(f"{log_path.name} was made with different knowledge or search settings; delete it to rerun {arm}")
    write_atomic(log_path, "".join(json.dumps(r) + "\n" for r in done))  # drops a torn last line
    seen, right = {r["qid"] for r in done}, sum(r["correct"] for r in done)
    budget = Budget(out / "spend.json", cfg["protocol"]["budget_usd"])
    agent = agent_llm or make_llm(cfg["agent"], cfg["cache_dir"], budget.spend)
    with tqdm(total=len(parts[set_name]), initial=len(seen), desc=f"{set_name} {arm}", unit="q",
              dynamic_ncols=True) as bar:
        try:
            for qid in parts[set_name]:
                if qid in seen:
                    continue
                q, before = by_id[qid], dict(agent.usage)
                sql, turns = answer(agent, db, q.question, knowledge, max_steps=cfg["max_steps"])
                correct = exec_match(db.path, sql, gold_rows(db.path, q))
                right += correct
                append_jsonl(log_path, {"qid": qid, "difficulty": q.difficulty, "sql": sql, "correct": correct,
                                        "correct_corrected": exec_match(db.path, sql, corrected_gold(db, q, fixes)),
                                        "turns": turns, **knowledge.used, "knowledge": setup,
                                        "usage": {k: agent.usage[k] - before.get(k, 0) for k in agent.usage}})
                bar.update(1)
                bar.set_postfix_str(f"acc {right}/{bar.n} | spent ${budget.total:.3f}")
        except (BudgetExceeded, ProviderExhausted) as e:
            print(f"stopped: {e}. To continue, raise protocol.budget_usd (or wait out the provider limit) "
                  f"and rerun; it resumes.")
            return False
    return True


def load_results(out, set_name, parts, arms):
    """{arm: {qid: record}} for the complete runs of one set."""
    results = {}
    for arm in arms:
        records = {r["qid"]: r for r in read_jsonl(Path(out) / f"{set_name}_{arm}.jsonl")}
        if set(records) >= set(parts[set_name]):
            results[arm] = {q: records[q] for q in parts[set_name]}
    return results


def paired(res, docs, key="correct"):
    """(fixes, regressions) of a mode against docs on the same questions."""
    return (sum(res[q][key] and not docs[q][key] for q in docs), sum(docs[q][key] and not res[q][key] for q in docs))


def gate_decision(results, max_regressions, candidates):
    """Pass: fixes >= regressions and regressions <= max. Headline: passing candidate with the best net (earlier
    candidates win ties), else docs."""
    rows = {}
    for arm in candidates:
        fixes, regressions = paired(results[arm], results["docs"])
        rows[arm] = {"right": sum(r["correct"] for r in results[arm].values()), "fixes": fixes,
                     "regressions": regressions, "pass": fixes >= regressions and regressions <= max_regressions}
    passing = [a for a in candidates if rows[a]["pass"]]
    return rows, max(passing, key=lambda a: rows[a]["fixes"] - rows[a]["regressions"], default="docs")


def gate(cfg):
    """Run docs and every knowledge arm once on the gate set and write gate.json with the headline arm."""
    candidates = [a for a in cfg["protocol"]["arms"] if "@" in a]
    for arm in ("docs", *candidates):
        if not run_mode(cfg, arm, "gate"):
            return False
    out, parts, _, _ = load_run(cfg)
    results = load_results(out, "gate", parts, ["docs", *candidates])
    rows, headline = gate_decision(results, cfg["protocol"]["max_regressions"], candidates)
    docs_right = sum(r["correct"] for r in results["docs"].values())
    setups = {m: r[parts["gate"][0]]["knowledge"] for m, r in results.items()}  # final runs must use the same setups
    write_atomic(out / "gate.json", json.dumps({"docs_right": docs_right, "modes": rows, "headline": headline,
                                                "setups": setups}, indent=1))
    print(f"gate ({len(parts['gate'])} questions, docs right {docs_right}):")
    for mode, row in rows.items():
        print(f"  {mode}: right {row['right']}, +{row['fixes']} / -{row['regressions']}, "
              f"{'pass' if row['pass'] else 'fail'}")
    print(f"headline arm: {headline}")
    return True


def discovery_usd(cfg):
    """Logical cost of discovery (the last discover.jsonl entry carries cumulative usage)."""
    log = read_jsonl(Path(cfg["runs_dir"]) / "discover.jsonl")
    if not log:
        return 0.0
    usage = log[-1]["usage"]
    return usd(usage["agent"], cfg["agent"].get("usd_per_million")) + usd(usage["proposer"], cfg["proposer"].get("usd_per_million"))


def gap_closed(res, docs, hints):
    """(arm - docs) / (hints - docs) in correct answers: the share of the hints ceiling an arm recovers."""
    right = lambda r: sum(x["correct"] for x in r.values())
    return f"{(right(res) - right(docs)) / (right(hints) - right(docs)):.2f}" if hints and right(hints) != right(docs) else "-"


def mode_row(arm, res, docs, hints, cfg, learn_usd):
    """One report table row: accuracy, paired tests against docs (official and corrected), gap closed, cost, latency,
    turns, knowledge use."""
    mode = split_arm(arm)[0]
    qids = list(res)
    ok, ok_c = [res[q]["correct"] for q in qids], [res[q]["correct_corrected"] for q in qids]
    lo, hi = bootstrap_ci(ok)
    vs_docs = "-"
    if arm != "docs":
        fixes, regressions = paired(res, docs)
        fixes_c, regressions_c = paired(res, docs, "correct_corrected")
        p = mcnemar(ok, [docs[q]["correct"] for q in qids])
        p_c = mcnemar(ok_c, [docs[q]["correct_corrected"] for q in qids])
        vs_docs = f"+{fixes}/-{regressions}, p={p:.3f}; corrected +{fixes_c}/-{regressions_c}, p={p_c:.3f}"
    test_usd = sum(usd(r["usage"], cfg["agent"].get("usd_per_million")) for r in res.values())
    spent = test_usd + (learn_usd if mode not in NO_FACTS else 0.0)
    latency = [r["usage"].get("latency_s", 0.0) for r in res.values()]
    use = f"{np.mean([r['facts_in_prompt'] for r in res.values()]):.1f} in prompt"
    if mode == "tool":
        use += (f", {np.mean([r['search_calls'] for r in res.values()]):.1f} searches, "
                f"{np.mean([r['facts_returned'] for r in res.values()]):.1f} facts returned")
    return (f"| {arm} | {sum(ok)}/{len(ok)} = {np.mean(ok):.3f} | {lo:.2f}-{hi:.2f} | {vs_docs} | "
            f"{gap_closed(res, docs, hints)} | {np.mean(ok_c):.3f} | "
            f"{test_usd:.4f} | {spent / max(1, sum(ok)):.4f} | {np.percentile(latency, 50):.1f} / "
            f"{np.percentile(latency, 95):.1f} | {np.mean([r['turns'] for r in res.values()]):.1f} | {use} |")


def analyze(cfg):
    out, parts, db, by_id = load_run(cfg)
    arms = cfg["protocol"]["arms"]
    results = load_results(out, "final", parts, arms)
    fixes = corrected(cfg["data_dir"], cfg["db"])
    for res in results.values():  # rescore on the current corrected labels, so label fixes need no rerun
        for q, r in res.items():
            r["correct_corrected"] = exec_match(db.path, r["sql"], corrected_gold(db, by_id[q], fixes))
    if "docs" not in results:
        raise SystemExit("analyze needs a complete docs run on the final set")
    gate_file = out / "gate.json"
    gated = json.loads(gate_file.read_text()) if gate_file.exists() else None
    headline = gated["headline"] if gated else None
    for arm, res in results.items():
        # The gate chose the headline with one knowledge setup; the final answers must come from that same setup.
        current = setup_digest(arm_book(out, arm), arm, cfg)
        if {r["knowledge"] for r in res.values()} | ({gated["setups"].get(arm, current)} if gated else set()) != {current}:
            raise SystemExit(f"final {arm} answers, gate.json and the knowledge files do not share one knowledge setup")
    learn_usd, docs = discovery_usd(cfg), results["docs"]
    n = len(parts["final"])
    missing = [f"{a}: {len(read_jsonl(out / f'final_{a}.jsonl'))}/{n} answered" for a in arms if a not in results]
    spend_file = out / "spend.json"
    real = json.loads(spend_file.read_text())["usd"] if spend_file.exists() else 0.0
    gate_usd = sum(usd(r["usage"], cfg["agent"].get("usd_per_million"))
                   for a in arms for r in read_jsonl(out / f"gate_{a}.jsonl"))

    lines = ["# EvoSQL results", ""]
    if cfg["protocol"].get("final_reused"):
        lines += ["**Diagnostic:** the final set is reused (seen in the v4 analysis and label review), so these results "
                  "are not a held-out claim.", ""]
    lines += [f"Question sets: discovery {len(parts['discovery'])}, gate {len(parts['gate'])}, final {n}.", ""]
    lines += ["## Primary endpoint (preregistered)", ""]
    if not gated:
        lines.append("No gate.json yet: run `python -m evosql gate` first.")
    elif headline == "docs":
        lines.append("No knowledge arm passed the gate, so the EvoSQL headline arm is docs (no learned knowledge).")
    elif headline not in results:
        lines.append(f"Headline arm {headline!r} has no complete final run yet.")
    else:
        a = [results[headline][q]["correct"] for q in parts["final"]]
        b = [docs[q]["correct"] for q in parts["final"]]
        lo, hi = bootstrap_ci(np.asarray(a, int) - np.asarray(b, int))
        lines.append(f"EvoSQL headline arm **{headline}** vs docs on the final set (official gold): {sum(a)} vs {sum(b)} "
                     f"correct of {n}, difference {(sum(a) - sum(b)) / n:+.3f} (95% CI {lo:+.2f} to {hi:+.2f}), "
                     f"exact McNemar p = {mcnemar(a, b):.3f}.")

    lines += ["", "## Final set, every arm", "",
              "| Arm | Accuracy | 95% CI | vs docs (official; corrected) | Gap closed | Corrected acc | Test $ | $/correct "
              "| Latency p50 / p95 s | Turns | Knowledge use |", "|---|---|---|---|---|---|---|---|---|---|---|"]
    lines += [mode_row(arm, res, docs, results.get("hints"), cfg, learn_usd) for arm, res in results.items()]
    if missing:
        lines.append(f"\nNot reported (incomplete final runs): {'; '.join(missing)}.")
    lines += ["", f"Discovery cost ${learn_usd:.4f} is added to the knowledge arms' $/correct; the gate runs cost "
              f"${gate_usd:.4f}. Real API spend so far: ${real:.3f} of ${cfg['protocol']['budget_usd']:.2f} (peak prices, "
              "cached replies free). Latency is the summed agent API time of the calls that answered a question; local "
              "embedding time (retrieve, tool) is excluded. Gap closed = (arm - docs) / (hints - docs), official gold. Corrected scores use the annotation-error study's gold, "
              "overlaid with this repo's reviewed fixes (labels/evosql_fixes.json), otherwise official."]

    if gated:
        lines += ["", f"## Gate ({len(parts['gate'])} questions, docs right {gated['docs_right']})", "",
                  "| Arm | Right | Fixes | Regressions | Pass |", "|---|---|---|---|---|"]
        lines += [f"| {m} | {r['right']} | {r['fixes']} | {r['regressions']} | {r['pass']} |" for m, r in gated["modes"].items()]
        lines.append(f"\nHeadline arm: {headline} (pass: fixes >= regressions and regressions <= "
                     f"{cfg['protocol']['max_regressions']}; ties go to the arm listed first in protocol.arms).")
        row = gated["modes"].get(headline)
        if row and row["fixes"] == row["regressions"]:
            lines.append("The headline arm had net 0 on the gate: it passed by not hurting, not by helping.")

    log = read_jsonl(out / "discover.jsonl")
    if log:
        answers = log[0]
        dropped = Counter(d["reason"].split(":")[0] for e in log if e["event"] == "batch" for d in e["dropped"])
        conflicts = [c for e in log if e["event"] == "merge" for c in e["conflicts"]]
        verifies = [e for e in log if e["event"] == "verify"]
        lines += ["", "## Knowledge", "",
                  f"- Discovery: docs right {answers['right']} of {len(parts['discovery'])}; learned from "
                  f"{len(answers['failures'])} failures; skipped {len(answers['known_wrong_labels'])} known-wrong labels.",
                  f"- Dropped by checks: {dict(dropped) or 'none'}.",
                  f"- Verification: {sum(e['passed'] for e in verifies)} of {len(verifies)} question bundles fixed their "
                  "own question when re-answered.",
                  f"- Merge conflicts: {len(conflicts)}" + "".join(f"; {c['phrase']!r} kept {c['kept']}" for c in conflicts) + "."]
    books = {v: FactBook.load(out / name, missing_ok=True) for v, name in KNOWLEDGE.items()}
    for variant, book in books.items():
        if book.facts:
            lines.append(f"- {variant}: {len(book.facts)} facts {dict(Counter(f.kind for f in book.facts))}, "
                         f"~{book.total_tokens()} tokens.")
    kept = {(f.kind, f.subject, f.fact) for f in books["verified"].facts}
    if books["single"].facts:
        lines += ["", "Facts (single set; [v] = also in the verified set):", "", "```"]
        lines += [f"{f.id} {'[v]' if (f.kind, f.subject, f.fact) in kept else '   '} [{f.kind}] {f.subject}: {f.fact}  "
                  f"(applies to: {', '.join(f.applies_to)})" for f in books["single"].facts] + ["```"]
    write_atomic(Path(cfg["results_dir"]) / "summary.md", "\n".join(lines) + "\n")
    print("\n".join(lines))
