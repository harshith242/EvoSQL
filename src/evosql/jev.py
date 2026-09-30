"""JEV, TypeSafe's decision model on OpenRouter's Decisions API: it scores how directly a fact applies to a question.
Replies are cached on disk by request body, so a rerun is free and identical; spend is reported for real calls only."""
import hashlib
import json
import time
from pathlib import Path

import httpx

from evosql.files import write_atomic
from evosql.llm import ReplayMiss

LEVELS = [
    "Unrelated: the rule is about columns or phrases {question} does not use.",
    "Same topic only: {question} mentions a related entity but asks for a different measure or condition.",
    "Partly applies: {question} uses the rule's concept, but possibly in a different sense.",
    "Directly applies: {question} uses the exact phrase, value or measure the rule defines, in the same sense as "
    "{rule}.learned_from.",
]


class JevUnavailable(Exception):
    pass


class Jev:
    def __init__(self, model, url, api_key, cache_dir="cache/jev", on_spend=None, post=None, max_tries=5,
                 replay_only=False):
        self.model, self.url, self.api_key = model, url, api_key
        self.cache_dir, self.on_spend, self.max_tries = Path(cache_dir), on_spend, max_tries
        self.replay_only = replay_only  # a cache miss raises ReplayMiss instead of calling JEV
        self.post = post or httpx.post
        self.usage = {"calls": 0, "usd": 0.0}

    def decide(self, state, questions):
        """Answers for one request; cached on disk by a hash of the request body, so a rerun is free and identical."""
        body = {"model": self.model, "state": state, "questions": questions}
        key = hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()
        path = self.cache_dir / key[:2] / f"{key}.json"

        if path.exists():
            reply = json.loads(path.read_text())
        else:
            if self.replay_only:
                raise ReplayMiss(f"{self.model}: an old arm needed a new call (cache miss); nothing was spent")
            reply = self._call(body)
            write_atomic(path, json.dumps(reply))
            if self.on_spend:
                self.on_spend(reply["usage"]["cost"])

        self.usage["calls"] += 1
        self.usage["usd"] += reply["usage"]["cost"]
        return reply["answers"]

    def _call(self, body):
        error = None
        for attempt in range(self.max_tries):
            try:
                r = self.post(self.url, json=body, headers={"Authorization": f"Bearer {self.api_key}"}, timeout=90)
            except httpx.HTTPError as e:
                error = e
            else:
                if r.status_code == 200:
                    return r.json()
                if r.status_code != 429 and r.status_code < 500:
                    raise JevUnavailable(f"JEV returned {r.status_code}: {r.text[:200]}")
                error = f"JEV returned {r.status_code}: {r.text[:200]}"
            if attempt < self.max_tries - 1:
                time.sleep(min(2 ** (attempt + 1), 30))
        raise JevUnavailable(f"JEV failed after {self.max_tries} tries: {error}")


def score_question(rule_ref, question_ref):
    """One 0-3 score question: how directly the rule at rule_ref applies to the question at question_ref."""
    return {"type": "score",
            "instructions": f"How directly does the rule in {rule_ref}.rule apply to {question_ref}?",
            "criteria": [level.format(question=question_ref, rule=rule_ref) for level in LEVELS]}


def fact_scores(jev, database, question, facts):
    """{fact id: 0-3 score} for every fact against one question, in one call ({} when there are no facts)."""
    if not facts:
        return {}
    state = {"database": database, "question": question,
             "facts": {f.id: {"rule": f.fact, "learned_from": f.learned_from} for f in facts}}
    asks = {f.id: score_question(f"`facts.{f.id}`", "`question`") for f in facts}
    return {k: a["score"] for k, a in jev.decide(state, asks).items()}


def question_scores(jev, database, fact, questions):
    """{qid: 0-3 score} for one fact against several questions, in one call ({} when there are none)."""
    if not questions:
        return {}
    state = {"database": database, "fact": {"rule": fact.fact, "learned_from": fact.learned_from},
             "questions": {f"q{q.qid}": q.question for q in questions}}
    asks = {f"q{q.qid}": score_question("`fact`", f"`questions.q{q.qid}`") for q in questions}
    answers = jev.decide(state, asks)
    return {q.qid: answers[f"q{q.qid}"]["score"] for q in questions}
