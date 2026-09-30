"""Per-database fact memory for one stream: JEV picks the facts a question sees, credit and retirement follow each
answer, and a new fact is admitted after a pre-check on the earlier questions JEV matches to it, then merged.
Unproven facts are only ever injected alone, so their credit is attributable."""
from itertools import count

import numpy as np

from evosql.facts import fact_key, merge
from evosql.jev import fact_scores, question_scores


def pick(facts, scores, rules, is_proven):
    """Facts scoring at least the cutoff, best first (input order breaks ties), at most max_facts; unproven alone."""
    ranked = sorted((f for f in facts if scores[f.id] >= rules["cutoff"]), key=lambda f: -scores[f.id])
    picked = ranked[:rules["max_facts"]]
    if any(not is_proven(f) for f in picked):
        picked = picked[:1]
    return picked


class FactMemory:
    def __init__(self, db, jev, embed, rules, database):
        self.db, self.jev, self.embed, self.rules, self.database = db, jev, embed, rules, database
        self.facts, self.state = {}, {}  # id -> Fact (active and retired); id -> {"score", "best", "uses", "retired"}
        self.history = []  # (question, none_ok) of the revealed questions, in stream order
        self.ids = count(1)

    def active(self):
        return [f for f in self.facts.values() if not self.state[f.id]["retired"]]

    def proven(self, fact):
        """Proven while its score is at least +1: only then may it share the prompt."""
        return self.state[fact.id]["score"] >= 1

    def observe(self, q, none_ok):
        """Reveal a question: it becomes an earlier question for pre-checks."""
        self.history.append((q, none_ok))

    def select(self, question):
        """(facts to inject, JEV score of every active fact); ties go to the higher memory score."""
        facts = sorted(self.active(), key=lambda f: -self.state[f.id]["score"])
        scores = fact_scores(self.jev, self.database, question, facts)
        return pick(facts, scores, self.rules, self.proven), scores

    def matches(self, fact):
        """Up to precheck_max earlier (question, none_ok) pairs JEV scores at or above the cutoff for this fact."""
        if not self.history:
            return []

        vectors = self.embed([f"{fact.fact} {fact.learned_from}"] + [q.question for q, _ in self.history])
        vectors = vectors / np.linalg.norm(vectors, axis=1, keepdims=True)
        nearest = np.argsort(-(vectors[1:] @ vectors[0]), kind="stable")[:self.rules["precheck_pool"]]
        pool = [self.history[i] for i in nearest]

        scores = question_scores(self.jev, self.database, fact, [q for q, _ in pool])
        hits = [(q, ok) for q, ok in pool if scores[q.qid] >= self.rules["cutoff"]]
        return sorted(hits, key=lambda pair: -scores[pair[0].qid])[:self.rules["precheck_max"]]

    def precheck(self, fact, pairs, try_fact):
        """(record, fixes): re-answer each pair with only this fact; any regression rejects it."""
        outcome = "pre-check passed" if pairs else "pre-check unmatched"
        record = {"outcome": outcome, "checked": [q.qid for q, _ in pairs]}
        fixes = 0
        for q, none_ok in pairs:
            ok = try_fact(fact, q)
            if none_ok and not ok:
                return {**record, "outcome": "pre-check rejected", "fixes": fixes}, fixes
            fixes += int(ok and not none_ok)
        return {**record, "fixes": fixes}, fixes

    def credit(self, ids, facts_ok, none_ok):
        """+1 fix / -1 regression vs the none arm; retire at a regression before any +1, at -2 after, or when idle."""
        delta = int(facts_ok and not none_ok) - int(none_ok and not facts_ok)
        for fid in ids:
            s = self.state[fid]
            s["score"] += delta
            s["uses"] += 1
            s["best"] = max(s["best"], s["score"])
            if delta < 0 and s["best"] < 1:
                s["retired"] = "regression while unproven"
            elif s["score"] <= -2:
                s["retired"] = "score fell to -2"
            elif s["score"] == 0 and s["uses"] >= self.rules["idle_uses"]:
                s["retired"] = f"no effect in {s['uses']} uses"

    def admit(self, fact, try_fact):
        """Pre-check on JEV-matched earlier questions (try_fact None skips it), merge the fact in, return the record."""
        fact.id = f"f{next(self.ids)}"
        if try_fact is None:
            record, fixes = {"outcome": "added unproven (pre-check skipped: budget)"}, 0
        else:
            record, fixes = self.precheck(fact, self.matches(fact), try_fact)
            if record["outcome"] == "pre-check rejected":
                return record

        pool = self.active() + [fact]
        merged, conflicts = merge(pool, self.db)
        kept = {f.id: f for f in merged}
        for f in pool:
            if f.id not in kept and f is not fact:
                self.state[f.id]["retired"] = "removed by a merge conflict"
        self.facts.update(kept)
        if fact.id in kept:
            self.state[fact.id] = {"score": fixes, "best": fixes, "uses": 0, "retired": None}
        else:
            twin = next((f.id for f in merged if fact_key(f) == fact_key(fact)), None)
            record["merge"] = f"merged into {twin}" if twin else "dropped: lost its phrases in a merge conflict"
        return {**record, "conflicts": conflicts} if conflicts else record

    def apply_edit(self, edit, try_fact):
        """Apply one consolidation edit {op, ids, fact}, pre-checked; returns the fields for its log record."""
        old = [self.facts[i] for i in edit["ids"]]
        if edit["op"] == "drop":
            for f in old:
                self.state[f.id]["retired"] = "dropped by consolidation"
            return {"applied": True}

        new = edit["fact"]
        new.learned_from = new.learned_from or old[0].learned_from
        sources = sorted({qid for f in old for qid in f.source_qids})

        # The replaced facts' own questions first, then the earlier questions JEV matches to the new fact.
        pairs = [(q, ok) for q, ok in self.history if q.qid in sources][:self.rules["precheck_max"]]
        seen = {q.qid for q, _ in pairs}
        pairs += [(q, ok) for q, ok in self.matches(new) if q.qid not in seen]
        record, _ = self.precheck(new, pairs, try_fact)
        if record["outcome"] == "pre-check rejected":
            return {"applied": False, **record}

        new.source_qids = sources
        if edit["op"] == "generalize":
            new.id = old[0].id
            self.facts[new.id] = new
        else:
            new.id = f"f{next(self.ids)}"
            self.facts[new.id] = new
            self.state[new.id] = {k: max(self.state[f.id][k] for f in old) for k in ("score", "best", "uses")}
            self.state[new.id]["retired"] = None
            for f in old:
                self.state[f.id]["retired"] = f"consolidated into {new.id}"
        return {"applied": True, "id": new.id, **record}
