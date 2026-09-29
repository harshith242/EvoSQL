"""v3 learning/test split: a difficulty-stratified sample of questions, halved into learn and test."""
import json
import random
from collections import defaultdict
from pathlib import Path


def make_split(questions, n_learn, n_test, seed):
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
    test = [q.qid for q in picked if q.qid not in set(learn)][:n_test]
    return {"learn": learn, "test": test}


def save_split(path, split):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(split, indent=1))


def load_split(path):
    return json.loads(Path(path).read_text())
