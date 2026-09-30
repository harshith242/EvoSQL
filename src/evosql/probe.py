"""The v7 probe answers 30 questions related to earlier stream questions with frozen memory in 5 arms (none, v6 facts,
v7 facts without SQL, v7 facts with SQL, similar past examples); nothing is learned. Facts are picked by JEV like in
the stream, so the fact arms differ only in memory content."""
import hashlib
import json
import os
from dataclasses import replace
from pathlib import Path

import numpy as np

from evosql.bird import Question, gold_rows, load_arcwise, open_db
from evosql.budget import Budget, BudgetExceeded
from evosql.facts import Fact
from evosql.files import append_jsonl, write_atomic
from evosql.jev import Jev, JevUnavailable, fact_scores
from evosql.llm import ProviderExhausted, make_llm
from evosql.memory import pick
from evosql.search import Embedder
from evosql.stream import Answers, facts_file

ARMS = ("none", "v6_facts", "v7_prose", "v7_sql", "examples")


def load_facts(path, question_text):
    """(non-retired facts, ids of proven facts) from a saved facts file; v6 files lack sql and learned_from."""
    facts, proven_ids = [], set()
    for saved in json.loads(Path(path).read_text()):
        if saved["retired"]:
            continue
        fact = Fact(**{k: v for k, v in saved.items() if k in Fact.__dataclass_fields__})
        fact.learned_from = fact.learned_from or question_text[fact.source_qids[0]]
        facts.append(fact)
        if saved["score"] >= 1:
            proven_ids.add(fact.id)
    return facts, proven_ids


def examples(embed, question, past, k=2):
    """Notes text with the k past questions most similar to the question, each with its correct SQL."""
    vectors = embed([question] + [q.question for q in past])
    vectors = vectors / np.linalg.norm(vectors, axis=1, keepdims=True)
    nearest = np.argsort(-(vectors[1:] @ vectors[0]), kind="stable")[:k]

    lines = ["Similar past questions with their correct SQL:"]
    for i in nearest:
        lines += [f"Q: {past[i].question}", f"SQL: {past[i].gold_sql}"]
    return "\n".join(lines)


def run_items(items, dbs, answers, jev, embed, memories, past, rules, descriptions, log_path):
    """Answer every probe item in all arms (none, each fact arm, examples) and log one JSONL line per item."""
    write_atomic(log_path, "")
    for item in items:
        db_id, question = item["db_id"], item["question"]
        db = dbs[db_id]
        q = Question(900000 + int(item["id"][1:]), db_id, question, item["gold_sql"])
        gold = gold_rows(db.path, q)

        arms = {"none": {**answers.get(db, q, gold), "injected": []}}
        for arm, by_db in memories.items():
            facts, proven_ids = by_db[db_id]
            scores = fact_scores(jev, f"{db_id} ({descriptions[db_id]})", question, facts)
            picked = pick(facts, scores, rules, lambda f: f.id in proven_ids)
            arms[arm] = {**answers.get(db, q, gold, picked), "injected": [f.id for f in picked]}
        arms["examples"] = {**answers.get(db, q, gold, notes=examples(embed, question, past[db_id])), "injected": []}

        append_jsonl(log_path, {
            "id": item["id"], "db_id": db_id, "level": item["level"], "source_qid": item["source_qid"],
            "arms": {arm: {k: r[k] for k in ("ok", "sql", "injected")} for arm, r in arms.items()},
        })


def check_probe(path):
    """Stop if the probe file differs from the one frozen in the manifest next to it."""
    manifest = json.loads((Path(path).parent / "manifest.json").read_text())
    if manifest["sha256"] != hashlib.sha256(Path(path).read_bytes()).hexdigest():
        raise SystemExit(f"{path} does not match its manifest: the probe set must stay frozen")


def run_probe(cfg):
    """Answer the frozen probe set with the saved v6 and v7 memory."""
    sc, out = cfg["stream"], Path(cfg["runs_dir"])
    check_probe(cfg["probe"]["questions"])
    items = json.loads(Path(cfg["probe"]["questions"]).read_text())

    questions = load_arcwise(sc["questions"], set(sc["databases"]))
    question_text = {q.qid: q.question for q in questions}
    dbs = {d: open_db(cfg["data_dir"], d, Path(sc["docs_root"]) / d / "database_description") for d in sc["databases"]}

    memories = {"v6_facts": {}, "v7_prose": {}, "v7_sql": {}}
    for db_id in dbs:
        v7_path = facts_file(out, 0, db_id)
        if not v7_path.exists():
            raise SystemExit(f"{v7_path} is missing: run `stream` first")
        facts, proven_ids = load_facts(v7_path, question_text)
        memories["v7_sql"][db_id] = facts, proven_ids
        memories["v7_prose"][db_id] = [replace(f, sql=None) for f in facts], proven_ids
        memories["v6_facts"][db_id] = load_facts(
            Path(cfg["probe"]["v6_runs_dir"]) / f"facts_s0_{db_id}.json", question_text)

    budget = Budget(out / "spend.json", sc["budget_usd"])
    agent = make_llm(cfg["agent"], cfg["cache_dir"], budget.spend)
    answers = Answers(agent, cfg["max_steps"])
    embed = Embedder(cfg["embed"]["model"], cfg["embed"]["url"])
    jev = Jev(cfg["jev"]["model"], cfg["jev"]["url"], os.environ[cfg["jev"]["api_key_env"]], on_spend=budget.spend)
    past = {d: [q for q in questions if q.db_id == d] for d in dbs}

    try:
        run_items(items, dbs, answers, jev, embed, memories, past, sc["rules"], sc["databases"],
                  out / "probe_v7.jsonl")
    except (BudgetExceeded, ProviderExhausted, JevUnavailable) as e:
        print(f"stopped: {e}. Rerun `probe` to continue; finished calls replay from cache for free.")
        return
    print(f"done: real spend ${budget.total:.3f}")
