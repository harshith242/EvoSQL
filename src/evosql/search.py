"""Hybrid fact search: BM25 over each fact's trigger phrases, subject and text, plus cosine similarity of local Ollama
embeddings, fused with Reciprocal Rank Fusion. A fact with BM25 = 0 and cosine < min_cosine is never returned."""
import hashlib
import json
import math
import re
from collections import Counter
from pathlib import Path

import numpy as np
import openai

from evosql.files import write_atomic

RRF_K = 60
STOPWORDS = set("a an and are as at be by did do does for from has have how in is it its of on or that the their them "
                "there these this those to was were what when where which who whose with".split())


def words(text):
    """Lowercased content words with a light suffix strip, so "platelets" matches "platelet"."""
    return [re.sub(r"(?<=\w{3})(ing|ed|s)$", "", w) for w in re.findall(r"\w+", text.lower()) if w not in STOPWORDS]


def bm25(query, docs, k1=1.5, b=0.75):
    """BM25 score of each doc (a word list) for the query words; a word in over half of the docs scores 0."""
    n, avg = len(docs), sum(map(len, docs)) / len(docs) or 1
    df = Counter(w for d in docs for w in set(d))
    scores = []
    for d in docs:
        tf = Counter(d)
        scores.append(sum(max(0.0, math.log((n - df[w] + 0.5) / (df[w] + 0.5))) * tf[w] * (k1 + 1)
                          / (tf[w] + k1 * (1 - b + b * len(d) / avg)) for w in set(query) if w in tf))
    return scores


def fact_text(f):
    return f"{'; '.join(f.applies_to)}. {f.subject}: {f.fact}"


def _unit(vectors):
    return vectors / np.linalg.norm(vectors, axis=1, keepdims=True)


class Embedder:
    """Local Ollama embeddings through its OpenAI-compatible endpoint, cached on disk by text hash."""

    def __init__(self, model, base_url, cache_dir="cache/embed"):
        self.model, self.cache_dir = model, Path(cache_dir)
        self.client = openai.OpenAI(base_url=base_url, api_key="local")

    def __call__(self, texts):
        paths = [self.cache_dir / f"{hashlib.sha256(f'{self.model}\n{t}'.encode()).hexdigest()}.json" for t in texts]
        missing = {t: p for t, p in zip(texts, paths) if not p.exists()}
        if missing:
            data = self.client.embeddings.create(model=self.model, input=list(missing)).data
            for p, e in zip(missing.values(), data):
                write_atomic(p, json.dumps(e.embedding))
        return np.array([json.loads(p.read_text()) for p in paths])


class HybridIndex:
    def __init__(self, facts, embed, min_cosine):
        self.facts, self.embed, self.min_cosine = facts, embed, min_cosine
        self.docs = [words(fact_text(f)) for f in facts]
        self.vectors = _unit(embed([fact_text(f) for f in facts])) if facts else None

    def search(self, text, k):
        """Top k facts as [(fact, how)], how = "keyword", "semantic" or "keyword + semantic"."""
        if not self.facts:
            return []
        keyword = bm25(words(text), self.docs)
        cosine = self.vectors @ _unit(self.embed([text]))[0]
        # Each signal ranks only the facts that pass its own floor; RRF sums 1/(60 + rank) over the lists a fact is in.
        lists = {"keyword": [i for i in range(len(self.facts)) if keyword[i] > 0],
                 "semantic": [i for i in range(len(self.facts)) if cosine[i] >= self.min_cosine]}
        lists["keyword"].sort(key=lambda i: -keyword[i])
        lists["semantic"].sort(key=lambda i: -cosine[i])
        score, how = Counter(), {}
        for name, ranked in lists.items():
            for rank, i in enumerate(ranked, 1):
                score[i] += 1 / (RRF_K + rank)
                how[i] = f"{how[i]} + {name}" if i in how else name
        best = sorted(score, key=lambda i: (-score[i], self.facts[i].id))[:k]
        return [(self.facts[i], how[i]) for i in best]
