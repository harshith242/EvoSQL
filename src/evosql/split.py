"""Learning/test split: a difficulty-stratified sample of questions, halved into learn and test."""
import json
import random
from collections import defaultdict
from pathlib import Path

from evosql.bird import load_questions, open_db
from evosql.files import write_atomic


def make_split(questions, n_learn, n_test, seed):
    assert n_learn == n_test, "alternating assignment keeps the difficulty mix only for equal halves"
    total = n_learn + n_test
    rng = random.Random(seed)
    groups = defaultdict(list)
    for q in sorted(questions, key=lambda q: q.qid):
        groups[q.difficulty].append(q)
    # Largest-remainder allocation keeps each difficulty's share and hits the exact total.
    shares = {d: total * len(qs) / len(questions) for d, qs in groups.items()}
    counts = {d: int(s) for d, s in shares.items()}
    for d in sorted(shares, key=lambda d: shares[d] - counts[d], reverse=True)[: total - sum(counts.values())]:
        counts[d] += 1
    picked = []
    for d in sorted(groups):
        rng.shuffle(groups[d])
        picked += groups[d][: counts[d]]
    # Alternate within the difficulty-sorted sample so both halves keep the mix.
    learn = [q.qid for i, q in enumerate(picked) if i % 2 == 0][:n_learn]
    chosen = set(learn)
    test = [q.qid for q in picked if q.qid not in chosen][:n_test]
    return {"learn": learn, "test": test}


def save_split(path, split):
    write_atomic(path, json.dumps(split, indent=1))


def load_run(cfg):
    """Everything learn, test and analyze share: (runs folder, split, database, questions by qid)."""
    out = Path(cfg["runs_dir"])
    split = json.loads((out / "split.json").read_text())
    db = open_db(cfg["data_dir"], cfg["db"], with_profile=cfg["agent"].get("value_profile", False))
    by_id = {q.qid: q for q in load_questions(cfg["data_dir"], cfg["db"])}
    return out, split, db, by_id
