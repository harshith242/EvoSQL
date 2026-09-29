"""Persisted spend guard: counts real (non-cached) API spend across runs and stops before the cap."""
import json
from pathlib import Path

from evosql.llm import usd


class BudgetExceeded(Exception):
    pass


class Budget:
    def __init__(self, path, cap_usd):
        self.path, self.cap = Path(path), cap_usd
        self.base = json.loads(self.path.read_text())["usd"] if self.path.exists() else 0.0
        self.total = self.base

    def charge(self, llms):
        """llms: list of (LLM, prices). Persists spend so far; raises only when new spend passes the cap."""
        before, self.total = self.total, self.base + sum(usd(llm.fresh, prices) for llm, prices in llms)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps({"usd": self.total}))
        if self.total > before and self.total > self.cap:
            raise BudgetExceeded(f"spent ${self.total:.3f} of ${self.cap:.2f}")
