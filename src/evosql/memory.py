"""Per-database fact memory for one stream: which facts a question may see, credit and retirement after each answer,
and admission of new facts (pre-check on earlier questions, then merge). It keeps the revealed questions itself;
unproven facts are only ever injected alone, so their credit is attributable."""
import re
from itertools import count

import numpy as np

from evosql.facts import fact_columns, fact_key, fact_tables, merge, phrase_in
from evosql.search import words

STRUCTURAL = ("grain", "relation")  # kinds that must be scoped to the schema the question mentions


def _name_words(name):
    # "fastestLapTime" -> fastest lap time; "first_name" -> first name
    return " ".join(re.findall(r"[A-Z]?[a-z]+|[A-Z]+(?![a-z])|\d+", name))


def fact_text(fact):
    """What a fact is embedded as for semantic matching."""
    return f"{'; '.join(fact.applies_to)}. {fact.subject}: {fact.fact}"


class FactMemory:
    def __init__(self, db, embed, rules):
        self.db, self.embed, self.rules = db, embed, rules
        self.facts, self.state = {}, {}  # id -> Fact (active and retired); id -> {"score", "best", "uses", "retired"}
        self.history = []  # (question, none_ok) of the revealed questions, in stream order
        self.ids = count(1)
        self._scope, self._vectors = {}, {}  # per fact id: (column-name words, description words); unit vector

    def active(self):
        return [f for f in self.facts.values() if not self.state[f.id]["retired"]]

    def proven(self, fact):
        """Proven while its score is at least +1: only then may it share the prompt or match by meaning."""
        return self.state[fact.id]["score"] >= 1

    def observe(self, q, none_ok):
        """Reveal a question: it becomes an earlier question for genericity and pre-checks."""
        self.history.append((q, none_ok))

    def scope(self, fact):
        """(words of the fact's table and column names, words of its columns' descriptions); cached per fact."""
        if fact.id not in self._scope:
            cols = fact_columns(self.db, fact)
            names = [_name_words(t) for t in fact_tables(self.db, fact)] + [_name_words(c) for _, c in cols]
            docs = [self.db.notes[t].get(c.lower(), {}).get("description", "") for t, c in cols]
            self._scope[fact.id] = set(words(" ".join(names))), set(words(" ".join(docs)))
        return self._scope[fact.id]

    def generic(self, phrase):
        r, h = self.rules, self.history
        return len(h) >= r["generic_min_questions"] and \
            sum(phrase_in(phrase, q.question) for q, _ in h) / len(h) > r["generic_share"]

    def phrase_hit(self, fact, question):
        """Phrase path: a whole-phrase trigger match, plus a schema cue for generic triggers and grain/relation."""
        hits = [p for p in fact.applies_to if phrase_in(p, question)]
        if not hits:
            return False
        names, docs = self.scope(fact)
        asked = set(words(question))
        if fact.kind in STRUCTURAL:
            return bool(asked & (names | docs))
        return any(not self.generic(p) for p in hits) or bool(asked & names)

    def similarity(self, question, facts):
        """Cosine similarity of the question to each fact (fact vectors are cached)."""
        for f in facts:
            if f.id not in self._vectors:
                v = self.embed([fact_text(f)])[0]
                self._vectors[f.id] = v / np.linalg.norm(v)
        q = self.embed([question])[0]
        return {f.id: float(self._vectors[f.id] @ q / np.linalg.norm(q)) for f in facts}

    def select(self, question):
        """Facts to inject: up to 2 proven facts, else at most 1 unproven fact (alone), else none."""
        facts = self.active()
        eligible = [f for f in facts if self.phrase_hit(f, question)]
        if not any(self.proven(f) for f in facts) and len(eligible) < 2:
            return eligible

        sim = self.similarity(question, facts)
        # Semantic path, proven facts only: the fact must clearly beat every other and be in the question's scope.
        ranked = sorted(facts, key=lambda f: -sim[f.id])
        best, margin = ranked[0], sim[ranked[0].id] - (sim[ranked[1].id] if len(ranked) > 1 else 0.0)
        in_scope = bool(set(words(question)) & set().union(*self.scope(best)))
        if (self.proven(best) and best not in eligible and sim[best.id] >= self.rules["semantic_min"]
                and margin >= self.rules["semantic_margin"] and in_scope):
            eligible.append(best)

        rank = lambda f: (-self.state[f.id]["score"], -sim[f.id])
        proven = sorted((f for f in eligible if self.proven(f)), key=rank)
        return proven[:2] if proven else sorted(eligible, key=rank)[:1]

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
        """Pre-check on earlier matches (try_fact None skips it), merge the fact in, return the learning record."""
        fact.id = f"f{next(self.ids)}"
        if try_fact is None:
            record, fixes = {"outcome": "added unproven (pre-check skipped: order budget)"}, 0
        else:
            matched = [(q, ok) for q, ok in self.history if self.phrase_hit(fact, q.question)]
            matched = matched[-self.rules["precheck_max"]:]
            record, fixes = {"outcome": "pre-check unmatched" if not matched else "pre-check passed",
                             "checked": [q.qid for q, _ in matched]}, 0
            for q, none_ok in matched:
                ok = try_fact(fact, q)
                if none_ok and not ok:
                    return {**record, "outcome": "pre-check rejected", "fixes": fixes}
                fixes += int(ok and not none_ok)
            record["fixes"] = fixes

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
        for f in merged:  # a merge may change a fact's phrases: recompute its cached scope and vector lazily
            self._scope.pop(f.id, None)
            self._vectors.pop(f.id, None)
        return {**record, "conflicts": conflicts} if conflicts else record
