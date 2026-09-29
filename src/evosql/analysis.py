"""Turn runs/*.jsonl into learning curves, CIs, paired tests, cost and note-growth numbers.
Non-learning arms answer each question the same way in any order, so their results are replayed in every order."""
import json
import random
from collections import Counter
from pathlib import Path

import matplotlib
import numpy as np
from scipy.stats import binomtest

from evosql.bird import db_path, gold_rows, load_questions
from evosql.knowledge import Edit
from evosql.learner import leaks
from evosql.stream import load_arm as arm_config

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

ARM_ORDER = ["vanilla", "docs", "selfcons", "ratchet", "evosql", "docs_hints"]


def mcnemar(a, b):
    """Two-sided exact McNemar p-value for paired boolean outcomes."""
    a, b = np.asarray(a, bool), np.asarray(b, bool)
    only_a, only_b = int(np.sum(a & ~b)), int(np.sum(~a & b))
    if only_a + only_b == 0:
        return 1.0
    return binomtest(only_a, only_a + only_b, 0.5).pvalue


def bootstrap_ci(sequences, iters=2000, seed=0):
    """95% CI of mean accuracy: resample orders, then questions within each order."""
    rng = np.random.default_rng(seed)
    seqs = [np.asarray(s, float) for s in sequences]
    means = []
    for _ in range(iters):
        picked = [seqs[i] for i in rng.integers(0, len(seqs), len(seqs))]
        means.append(np.mean([s[rng.integers(0, len(s), len(s))].mean() for s in picked]))
    return float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5))


def order_qids(questions, seed):
    order = list(questions)
    random.Random(seed).shuffle(order)
    return [q.qid for q in order]


def load_arm(runs_dir, arm, db):
    """Return {order_seed: [records]} for one arm."""
    out = {}
    for path in sorted((Path(runs_dir) / arm / db).glob("order*.jsonl")):
        out[int(path.stem.removeprefix("order"))] = [json.loads(line) for line in path.read_text().splitlines()]
    return out


def correctness_by_order(records_by_order, learning, qids_by_order):
    """{seed: [bool per step]}. Non-learning arms are re-sequenced into every order by qid."""
    if learning:
        return {s: [r["correct"] for r in recs] for s, recs in records_by_order.items()}
    by_qid = {r["qid"]: r["correct"] for recs in records_by_order.values() for r in recs}
    return {s: [by_qid[q] for q in qids if q in by_qid] for s, qids in qids_by_order.items()}


def tokens(usage):
    return usage.get("prompt_tokens", 0) + usage.get("completion_tokens", 0)


def usd(usage, prices):
    """Dollar cost of one usage record; prices are USD per 1M tokens (missing prices = free, e.g. local)."""
    if not prices:
        return 0.0
    hit = usage.get("provider_cached_tokens", 0)
    miss = usage.get("prompt_tokens", 0) - hit
    return (hit * prices["cache_hit"] + miss * prices["cache_miss"] + usage.get("completion_tokens", 0) * prices["output"]) / 1e6


def cost(records, agent_prices=None, proposer_prices=None):
    answer_tok = sum(tokens(r["answer_usage"]) for r in records)
    learn_tok = sum(tokens(u) for r in records for u in r["learn_usage"])
    calls = sum(r["answer_usage"].get("calls", 0) + sum(u.get("calls", 0) for u in r["learn_usage"]) for r in records)
    n_correct = max(1, sum(r["correct"] for r in records))
    prompt = sum(r["answer_usage"].get("prompt_tokens", 0) for r in records)
    cached = sum(r["answer_usage"].get("provider_cached_tokens", 0) for r in records)
    # learn_usage is [agent, proposer] for learning arms (agent only otherwise).
    spent = sum(usd(r["answer_usage"], agent_prices) for r in records) + sum(
        usd(u, agent_prices if i == 0 else proposer_prices) for r in records for i, u in enumerate(r["learn_usage"]))
    return {"usd_per_q": spent / len(records), "usd_per_correct": spent / n_correct,
            "answer_tokens_per_q": answer_tok / len(records), "learn_tokens_per_q": learn_tok / len(records),
            "tokens_per_correct": (answer_tok + learn_tok) / n_correct, "calls_per_correct": calls / n_correct,
            "prompt_cache_hit": cached / prompt if prompt else 0.0}


def leakage_rate(runs_dir, arm, cfg, by_id):
    total = leaky = 0
    path = db_path(cfg["data_dir"], cfg["db"])
    for notes_file in (Path(runs_dir) / arm / cfg["db"]).glob("order*.notes.json"):
        for n in json.loads(notes_file.read_text())["notes"]:
            q = by_id.get(n["source_qid"])
            if q is None:
                continue
            total += 1
            leaky += bool(leaks(Edit("add", when=n["when"], text=n["text"]), q.question, q.gold_sql, gold_rows(path, q)))
    return leaky / total if total else None


def analyze(cfg):
    out = Path(cfg.get("results_dir", "results"))
    out.mkdir(exist_ok=True)
    runs_dir, db = cfg["runs_dir"], cfg["db"]
    questions = load_questions(cfg["data_dir"], db)
    by_id = {q.qid: q for q in questions}
    qids_by_order = {s: order_qids(questions, s) for s in cfg["orders"]}
    arms = [a for a in ARM_ORDER if (Path(runs_dir) / a / db).exists()]

    seqs, rows, costs, notes, reasons = {}, [], {}, {}, {}
    for arm in arms:
        recs = load_arm(runs_dir, arm, db)
        learning = arm_config(arm, cfg.get("arms_dir", "configs/arms")).get("learning", False)
        seqs[arm] = correctness_by_order(recs, learning, qids_by_order)
        flat = [r for rs in recs.values() for r in rs]
        costs[arm] = cost(flat, cfg["agent"].get("usd_per_million"), cfg["proposer"].get("usd_per_million"))
        if learning:
            notes[arm] = recs
            reasons[arm] = Counter(r.get("reason", "") for r in flat if r.get("decision"))
        if len({tuple(r["models"]) for r in flat}) > 1:
            print(f"WARNING: {arm} saw more than one model id set; check for a silent model change.")

    for arm in arms:
        full = list(seqs[arm].values())
        tail = [s[len(s) * 2 // 3:] for s in full]
        lo, hi = bootstrap_ci(tail)
        rows.append((arm, np.mean([np.mean(s) for s in full]), np.mean([np.mean(s) for s in tail]), lo, hi, len(full)))

    # Paired test of each arm against EvoSQL on the same (order, question) pairs.
    pvals = {}
    if "evosql" in seqs:
        for arm in arms:
            if arm == "evosql":
                continue
            # Step i of order s is the same question in every arm, so outcomes pair up directly.
            a, b = [], []
            for s in set(seqs["evosql"]) & set(seqs[arm]):
                n = min(len(seqs["evosql"][s]), len(seqs[arm][s]))
                a += seqs["evosql"][s][:n]
                b += seqs[arm][s][:n]
            pvals[arm] = mcnemar(a, b)

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 4.5))
    for arm in arms:
        length = min(len(s) for s in seqs[arm].values())
        mat = np.array([s[:length] for s in seqs[arm].values()], float)
        steps = np.arange(1, length + 1)
        ax1.plot(steps, (mat.cumsum(axis=1) / steps).mean(axis=0), label=arm)
        w = min(20, length)  # smoke runs can be shorter than the window
        rolling = np.array([np.convolve(r, np.ones(w) / w, mode="valid") for r in mat]).mean(axis=0)
        ax2.plot(np.arange(w, length + 1), rolling, label=arm)
    ax1.set(title="Cumulative accuracy", xlabel="questions seen", ylabel="accuracy")
    ax2.set(title="Rolling accuracy (last 20 questions)", xlabel="questions seen")
    ax1.legend()
    fig.tight_layout()
    fig.savefig(out / "learning_curve.png", dpi=150)

    if notes:
        fig, ax = plt.subplots(figsize=(6, 4))
        for arm, recs in notes.items():
            length = min(len(r) for r in recs.values())
            ax.plot(np.mean([[x["notes_count"] for x in r[:length]] for r in recs.values()], axis=0), label=arm)
        ax.set(title="Notes kept over time", xlabel="questions seen", ylabel="notes")
        ax.legend()
        fig.tight_layout()
        fig.savefig(out / "notes_growth.png", dpi=150)

    noise = Path(runs_dir) / "noise" / f"{db}.json"
    lines = [f"# EvoSQL results: {db}", ""]
    if noise.exists():
        lines += [f"Noise flip rate p = {json.loads(noise.read_text())['p']:.2f} (adding a harmless note).", ""]
    lines += ["| Arm | Orders | Accuracy (all) | Accuracy (final third) | 95% CI | p vs evosql | Tokens/correct "
              "| Calls/correct | Prompt cache hit | $/question | $/correct |",
              "|---|---|---|---|---|---|---|---|---|---|---|"]
    for arm, acc, tail_acc, lo, hi, n in rows:
        p = f"{pvals[arm]:.3f}" if arm in pvals else "-"
        c = costs[arm]
        lines.append(f"| {arm} | {n} | {acc:.3f} | {tail_acc:.3f} | {lo:.3f}-{hi:.3f} | {p} | "
                     f"{c['tokens_per_correct']:.0f} | {c['calls_per_correct']:.1f} | {c['prompt_cache_hit']:.0%} | "
                     f"{c['usd_per_q']:.4f} | {c['usd_per_correct']:.4f} |")
    for arm, counts in reasons.items():
        lines += ["", f"**{arm} decisions:** " + ", ".join(f"{k}: {v}" for k, v in counts.most_common())]
    if "ratchet" in arms:
        rate = leakage_rate(runs_dir, "ratchet", cfg, by_id)
        lines += ["", f"Ratchet notes flagged by the leakage check: {rate:.0%}" if rate is not None else ""]
    if "evosql" in costs and "docs" in costs:
        per_q = lambda c: c["answer_tokens_per_q"] + c["learn_tokens_per_q"]
        n = max(1, min(7, round(per_q(costs["evosql"]) / per_q(costs["docs"]))))
        lines += ["", f"Budget-matched self-consistency N = {n} (set it in configs/arms/selfcons.yaml)."]
    (out / "summary.md").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))
