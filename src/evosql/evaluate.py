"""v3 test phase and report: every arm answers the same frozen test questions; analyze_v3 compares them
(accuracy, paired tests, cost incl. amortized learning, twin vs no-twin questions, learned knowledge)."""
import json
import re
from collections import Counter
from pathlib import Path

from tqdm import tqdm

from evosql.agent import answer, answer_self_consistent
from evosql.analysis import bootstrap_ci, mcnemar, usd
from evosql.bird import exec_match, gold_rows, load_questions, open_db
from evosql.budget import Budget, BudgetExceeded
from evosql.facts import FactBook, columns
from evosql.llm import ProviderExhausted
from evosql.split import load_split
from evosql.stream import make_llm

ARMS = ("docs", "evosql", "ungated", "selfcons")
KNOWLEDGE_FILE = {"evosql": "knowledge_final.json", "ungated": "ungated.json"}


def read_jsonl(path):
    """Records of a JSONL log; a torn last line (killed mid-write) is ignored."""
    records = []
    for line in Path(path).read_text().splitlines() if Path(path).exists() else []:
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            pass
    return records


def arm_knowledge(out, arm):
    if arm not in KNOWLEDGE_FILE:
        return FactBook()
    path = Path(out) / KNOWLEDGE_FILE[arm]
    if not path.exists():
        raise SystemExit(f"{arm} needs {path.name}: run `python -m evosql learn` first")
    return FactBook.load(path)


def learn_usd(cfg):
    """Logical cost of the learning phase (the last learn.jsonl entry carries cumulative usage)."""
    log = read_jsonl(Path(cfg["runs_dir"]) / "learn.jsonl")
    if not log:
        return 0.0
    usage = log[-1]["usage"]
    return usd(usage["agent"], cfg["agent"].get("usd_per_million")) + usd(usage["proposer"], cfg["proposer"].get("usd_per_million"))


def test_usd(cfg, arm):
    return sum(usd(r["usage"], cfg["agent"].get("usd_per_million")) for r in read_jsonl(Path(cfg["runs_dir"]) / f"test_{arm}.jsonl"))


def selfcons_n(cfg):
    """Samples for self-consistency so it spends about what evosql spends per test question (learning amortized)."""
    out, n_test = Path(cfg["runs_dir"]), cfg["v3"]["n_test"]
    docs = read_jsonl(out / "test_docs.jsonl")
    if not docs or not read_jsonl(out / "test_evosql.jsonl"):
        raise SystemExit("selfcons needs the docs and evosql test runs first")
    docs_per_q = test_usd(cfg, "docs") / len(docs)
    evosql_per_q = (learn_usd(cfg) + test_usd(cfg, "evosql")) / n_test
    return min(cfg["v3"]["selfcons_max_n"], max(1, round(evosql_per_q / docs_per_q))) if docs_per_q else 1


def run_test(cfg, arm, agent_llm=None):
    """Answer every test question with the arm's frozen setup; resumes by skipping logged questions."""
    out = Path(cfg["runs_dir"])
    split = load_split(out / "split.json")
    db = open_db(cfg["data_dir"], cfg["db"], with_docs=True, with_profile=cfg["agent"].get("value_profile", False))
    by_id = {q.qid: q for q in load_questions(cfg["data_dir"], cfg["db"])}
    book = arm_knowledge(out, arm)
    n = selfcons_n(cfg) if arm == "selfcons" else None
    log_path = out / f"test_{arm}.jsonl"
    done = read_jsonl(log_path)
    log_path.write_text("".join(json.dumps(r) + "\n" for r in done))  # drops a torn last line
    seen, right = {r["qid"] for r in done}, sum(r["correct"] for r in done)
    agent = agent_llm or make_llm(cfg["agent"], cfg["cache_dir"])
    budget = Budget(out / "spend.json", cfg["v3"]["budget_usd"])
    bar = tqdm(total=len(split["test"]), initial=len(seen), desc=f"test {arm}", unit="q", dynamic_ncols=True)
    try:
        for qid in split["test"]:
            if qid in seen:
                continue
            q, before = by_id[qid], dict(agent.usage)
            try:
                if n:
                    r = answer_self_consistent(agent, db, q.question, book, n, cfg["max_steps"])
                else:
                    r = answer(agent, db, q.question, book, max_steps=cfg["max_steps"])
            finally:
                budget.charge([(agent, cfg["agent"].get("usd_per_million"))])
            correct = exec_match(db.path, r.sql, gold_rows(db.path, q))
            right += correct
            rec = {"qid": qid, "difficulty": q.difficulty, "sql": r.sql, "correct": correct, "samples": n or 1,
                   "usage": {k: agent.usage[k] - before.get(k, 0) for k in agent.usage}}
            with open(log_path, "a") as f:
                f.write(json.dumps(rec) + "\n")
            bar.update(1)
            bar.set_postfix_str(f"acc {right}/{bar.n} | spent ${budget.total:.3f}")
    except (BudgetExceeded, ProviderExhausted) as e:
        bar.close()
        print(f"stopped: {e}. Rerun the same command later; it resumes.")
        return False
    bar.close()
    return True


def where_columns(sql, names):
    """Column names used in the (first) WHERE clause, i.e. what the question filters on."""
    m = re.search(r"\bWHERE\b(.*?)(\bGROUP\s+BY\b|\bORDER\s+BY\b|\bLIMIT\b|$)", sql, re.IGNORECASE | re.DOTALL)
    if not m:
        return set()
    return {c for c in names if c != "ID" and re.search(rf"(?<!\w){re.escape(c)}(?!\w)", m.group(1))}


def twins(learn_qs, test_qs, names):
    """Test questions that filter on a column some learning question also filters on."""
    learned = set().union(*(where_columns(q.gold_sql, names) for q in learn_qs))
    return {q.qid for q in test_qs if where_columns(q.gold_sql, names) & learned}


def analyze_v3(cfg):
    out, res = Path(cfg["runs_dir"]), Path(cfg["results_dir"])
    res.mkdir(parents=True, exist_ok=True)
    split = load_split(out / "split.json")
    by_id = {q.qid: q for q in load_questions(cfg["data_dir"], cfg["db"])}
    db = open_db(cfg["data_dir"], cfg["db"], with_docs=False)
    names = sorted({c for t in db.tables for c in columns(db, t)})
    twin = twins([by_id[i] for i in split["learn"]], [by_id[i] for i in split["test"]], names)
    results = {a: {r["qid"]: r["correct"] for r in read_jsonl(out / f"test_{a}.jsonl")} for a in ARMS}
    results = {a: r for a, r in results.items() if r}
    learning = learn_usd(cfg)

    lines = ["# EvoSQL v3 results", "", f"Learn {len(split['learn'])} / test {len(split['test'])} questions. "
             f"Test questions with a twin in the learning set: {len(twin)}.", "",
             "| Arm | Answered | Accuracy | 95% CI | p vs docs | Twin acc | No-twin acc | Test $ | Learn $ | $/correct |",
             "|---|---|---|---|---|---|---|---|---|---|"]
    for arm, res_arm in results.items():
        qids = list(res_arm)
        seq = [res_arm[q] for q in qids]
        lo, hi = bootstrap_ci([seq])
        common = [q for q in qids if q in results.get("docs", {})]
        p = f"{mcnemar([res_arm[q] for q in common], [results['docs'][q] for q in common]):.3f}" if arm != "docs" and common else "-"
        acc_on = lambda ids: (f"{sum(res_arm[q] for q in ids) / len(ids):.2f} ({len(ids)})" if ids else "-")
        spent_learn = learning if arm in KNOWLEDGE_FILE else 0.0
        spent_test = test_usd(cfg, arm)
        per_correct = (spent_learn + spent_test) / max(1, sum(seq))
        lines.append(f"| {arm} | {len(qids)} | {sum(seq) / len(seq):.3f} | {lo:.2f}-{hi:.2f} | {p} | "
                     f"{acc_on([q for q in qids if q in twin])} | {acc_on([q for q in qids if q not in twin])} | "
                     f"{spent_test:.4f} | {spent_learn:.4f} | {per_correct:.4f} |")

    log = read_jsonl(out / "learn.jsonl")
    batches = [e for e in log if e["event"] == "batch"]
    calib = next((e for e in log if e["event"] == "calibration"), {})
    consol = next((e for e in log if e["event"] == "consolidation"), None)
    dropped = Counter(d["reason"].split(":")[0] for e in batches for d in e["dropped"])
    skips = [s for e in batches for s in e["skips"]]
    lines += ["", "## Learning", f"- Calibration: {calib.get('flips')} flips from a neutral fact; threshold {calib.get('threshold')}.",
              f"- Batches: {len(batches)}; accepted {sum(e['decision'] == 'accepted' for e in batches)}; "
              f"no valid facts {sum(e['decision'] == 'no valid facts' for e in batches)}.",
              f"- Facts dropped by checks: {dict(dropped) or 'none'}.",
              f"- Skipped as likely gold-SQL errors: {len(skips)}" + (f" (e.g. {skips[0][1]!r})" if skips else "") + "."]
    if consol:
        lines.append(f"- Consolidation: {consol['facts_before']} -> {consol['facts_after']} facts, learning right "
                     f"{consol['before']} -> {consol['after']}, kept: {consol['kept']}.")
    for arm in KNOWLEDGE_FILE:
        path = out / KNOWLEDGE_FILE[arm]
        if path.exists():
            book = FactBook.load(path)
            kinds = dict(Counter(f.kind for f in book.facts))
            lines += ["", f"## {arm} knowledge: {len(book.facts)} facts, ~{book.total_tokens()} tokens, {kinds}", "",
                      "```", book.render() or "(empty)", "```"]
    (res / "summary.md").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))
