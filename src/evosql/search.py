"""Content words with a light suffix strip, and local Ollama embeddings (OpenAI-compatible endpoint) cached by text."""
import hashlib
import json
import re
from pathlib import Path

import numpy as np
import openai

from evosql.files import write_atomic

STOPWORDS = set("a an and are as at be by did do does for from has have how in is it its of on or that the their them "
                "there these this those to was were what when where which who whose with".split())


def words(text):
    """Lowercased content words with a light suffix strip, so "platelets" matches "platelet"."""
    return [re.sub(r"(?<=\w{3})(ing|ed|s)$", "", w) for w in re.findall(r"\w+", text.lower()) if w not in STOPWORDS]


class Embedder:
    """Local Ollama embeddings, cached in memory and on disk by text hash."""

    def __init__(self, model, base_url, cache_dir="cache/embed"):
        self.model, self.cache_dir, self.memo = model, Path(cache_dir), {}
        self.client = openai.OpenAI(base_url=base_url, api_key="local")

    def __call__(self, texts):
        if all(t in self.memo for t in texts):
            return np.array([self.memo[t] for t in texts])
        paths = [self.cache_dir / f"{hashlib.sha256(f'{self.model}\n{t}'.encode()).hexdigest()}.json" for t in texts]
        missing = {t: p for t, p in zip(texts, paths) if not p.exists()}
        if missing:
            data = self.client.embeddings.create(model=self.model, input=list(missing)).data
            for p, e in zip(missing.values(), data):
                write_atomic(p, json.dumps(e.embedding))
        self.memo.update({t: json.loads(p.read_text()) for t, p in zip(texts, paths)})
        return np.array([self.memo[t] for t in texts])
