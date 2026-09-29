"""Question sets. The v3 split (a difficulty-stratified sample halved into learn and test) becomes v4's discovery and
gate sets, the unused rest is the final set, and the pilot questions seen by the v1/v2 runs are excluded everywhere."""
import json
import random
from collections import defaultdict
from pathlib import Path

from evosql.bird import load_questions, open_db


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


def pilot_qids(questions, n_pilot, seed):
    """The first n_pilot questions of the v1/v2 streaming order."""
    order = [q.qid for q in questions]
    random.Random(seed).shuffle(order)
    return set(order[:n_pilot])


def make_partitions(questions, protocol):
    p = protocol
    split = make_split(questions, p["n_learn"], p["n_test"], p["seed"])
    pilot = pilot_qids(questions, p["n_pilot"], p["seed"])
    used = set(split["learn"]) | set(split["test"])
    rest = sorted(q.qid for q in questions if q.qid not in used)
    keep = lambda qids: [i for i in qids if i not in pilot]
    return {"discovery": keep(split["learn"]), "gate": keep(split["test"]), "final": keep(rest)}


def load_run(cfg):
    """Everything discover, run and analyze share: (runs folder, partitions, database, questions by qid)."""
    out = Path(cfg["runs_dir"])
    parts = json.loads((out / "partitions.json").read_text())
    db = open_db(cfg["data_dir"], cfg["db"], with_profile=cfg["agent"].get("value_profile", False))
    by_id = {q.qid: q for q in load_questions(cfg["data_dir"], cfg["db"])}
    return out, parts, db, by_id
