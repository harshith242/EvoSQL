"""Persisted spend guard: counts real (non-cached) API spend across runs and stops before the cap."""
import json
from pathlib import Path

from evosql.analysis import usd


class BudgetExceeded(Exception):
    pass


class Budget:
    def __init__(self, path, cap_usd):
        self.path, self.cap = Path(path), cap_usd
        self.total = json.loads(self.path.read_text())["usd"] if self.path.exists() else 0.0
        self.seen = {}  # id(llm) -> fresh usd already charged

    def charge(self, llms):
        """llms: list of (LLM, prices). Adds new fresh spend, persists it, raises past the cap."""
        for llm, prices in llms:
            spent = usd(llm.fresh, prices)
            self.total += spent - self.seen.get(id(llm), 0.0)
            self.seen[id(llm)] = spent
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps({"usd": self.total}))
        if self.total > self.cap:
            raise BudgetExceeded(f"spent ${self.total:.3f} of ${self.cap:.2f}")
