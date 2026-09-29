"""v6 per-database fact memory: which facts a question may see (phrase path for any fact, semantic path for proven
facts), credit after each answer with retirement rules, and the pre-activation check on earlier questions.
Unproven facts are only ever injected alone, so their credit is attributable."""
import re
from itertools import count

import numpy as np

from evosql.facts import fact_columns, merge
from evosql.search import fact_text, words

STRUCTURAL = ("grain", "relation")  # kinds that must be scoped to the schema the question mentions


def phrase_in(phrase, text):
    """Whole-phrase match with word boundaries: "age" is in "patient age" but not in "average"."""
    return re.search(rf"(?<!\w){re.escape(phrase.lower().strip())}(?!\w)", text.lower()) is not None


def _name_words(name):
    # "fastestLapTime" -> fastest lap time; "first_name" -> first name
    return " ".join(re.findall(r"[A-Z]?[a-z]+|[A-Z]+(?![a-z])|\d+", name))


class FactMemory:
    def __init__(self, db, embed, rules):
        self.db, self.embed, self.rules = db, embed, rules
        self.facts, self.state, self.ids = [], {}, count(1)

    def active(self):
        return [f for f in self.facts if not self.state[f.id]["retired"]]

    def proven(self, fact):
        """A fact is proven once its score has reached +1 (a positive record); it stays proven."""
        return self.state[fact.id]["proven"]

    def in_scope(self, fact, question):
        """The question mentions a table or column the fact names, by name or by a word of that column's description."""
        cols = fact_columns(self.db, fact)
        tables = {t for t in self.db.tables if re.search(rf"\b{re.escape(t.lower())}\b", f"{fact.subject} {fact.fact}".lower())}
        notes = {t: {c.lower(): d for c, d in self.db.column_notes.get(t, {}).items()} for t in self.db.tables}
        text = " ".join([_name_words(t) for t in tables | {t for t, _ in cols}]
                        + [f"{_name_words(c)} {notes[t].get(c.lower(), '').split(' | ')[0]}" for t, c in cols])
        return bool(set(words(question)) & set(words(text)))

    def generic(self, phrase, history):
        r = self.rules
        return len(history) >= r["generic_min_questions"] and \
            sum(phrase_in(phrase, h) for h in history) / len(history) > r["generic_share"]

    def phrase_hit(self, fact, question, history):
        hits = [p for p in fact.applies_to if phrase_in(p, question)]
        if not hits:
            return False
        scope = self.in_scope(fact, question)
        if fact.kind in STRUCTURAL and not scope:
            return False
        # A generic trigger counts only with a second cue: a specific trigger or the fact's schema in the question.
        return scope or any(not self.generic(p, history) for p in hits)

    def semantic_hit(self, question, facts):
        """The single proven fact whose embedding clearly beats every other fact's for this question, if any."""
        r = self.rules
        if not any(self.proven(f) for f in facts):
            return None
        vecs = self.embed([question] + [fact_text(f) for f in facts])
        vecs = vecs / np.linalg.norm(vecs, axis=1, keepdims=True)
        cos = vecs[1:] @ vecs[0]
        order = np.argsort(-cos)
        best = facts[order[0]]
        margin = cos[order[0]] - (cos[order[1]] if len(order) > 1 else 0.0)
        if self.proven(best) and cos[order[0]] >= r["semantic_min"] and margin >= r["semantic_margin"] \
                and self.in_scope(best, question):
            return best
        return None

    def select(self, question, history):
        """Facts to inject: up to 2 proven facts, else at most 1 unproven fact (alone), else none."""
        facts = self.active()
        eligible = [f for f in facts if self.phrase_hit(f, question, history)]
        semantic = self.semantic_hit(question, facts) if facts else None
        if semantic and semantic not in eligible:
            eligible.append(semantic)
        rank = lambda f: (-self.state[f.id]["score"], f.id)
        proven = sorted((f for f in eligible if self.proven(f)), key=rank)
        return proven[:2] if proven else sorted(eligible, key=rank)[:1]

    def credit(self, ids, facts_ok, none_ok):
        """+1 for a fix, -1 for a regression against the none arm on the same question; applies retirement rules."""
        delta = int(facts_ok and not none_ok) - int(none_ok and not facts_ok)
        for fid in ids:
            s = self.state[fid]
            s["score"] += delta
            s["uses"] += 1
            s["proven"] = s["proven"] or s["score"] >= 1
            if delta < 0 and not s["proven"]:
                s["retired"] = "regression while unproven"
            elif s["score"] <= -2:
                s["retired"] = "score fell to -2"
            elif s["score"] == 0 and s["uses"] >= self.rules["idle_uses"]:
                s["retired"] = f"no effect in {s['uses']} uses"

    def precheck(self, fact, earlier, answer_with):
        """Try the fact alone on up to N earlier matching questions (question, none_ok).
        Returns ("rejected" | "passed" | "unmatched", fixes, checked qids)."""
        history = [q.question for q, _ in earlier]
        matched = [(q, ok) for q, ok in earlier if self.phrase_hit(fact, q.question, history)][-self.rules["precheck_max"]:]
        if not matched:
            return "unmatched", 0, []
        fixes = 0
        for q, none_ok in matched:
            ok = answer_with(fact, q)
            if none_ok and not ok:
                return "rejected", fixes, [x.qid for x, _ in matched]
            fixes += int(ok and not none_ok)
        return "passed", fixes, [q.qid for q, _ in matched]

    def add(self, fact, score):
        """Activate a checked fact with a starting score; merge with active facts. Returns the merge conflicts."""
        fact.id = f"f{next(self.ids)}"
        pool = self.active() + [fact]
        merged, conflicts = merge(pool, self.db)
        kept = {f.id for f in merged}
        for f in pool:
            if f.id not in kept and f is not fact:
                self.state[f.id]["retired"] = "removed by a merge conflict"
        if fact.id in kept:
            self.state[fact.id] = {"score": score, "proven": score >= 1, "uses": 0, "retired": None}
        self.facts = [f for f in self.facts if f.id not in kept] + merged
        return conflicts
