import pytest

from evosql import jev as jev_module
from evosql.facts import Fact
from evosql.jev import Jev, JevUnavailable, fact_scores
from evosql.llm import ReplayMiss


class Reply:
    def __init__(self, status, body=None):
        self.status_code, self.body, self.text = status, body, "error text"

    def json(self):
        return self.body


def ok(cost=0.01, **answers):
    return Reply(200, {"answers": {k: {"type": "score", "score": v} for k, v in answers.items()},
                       "usage": {"input_tokens": 10, "output_tokens": 2, "cost": cost}})


def make(tmp_path, replies, spend=None):
    calls = []

    def post(url, json, headers, timeout):
        calls.append((url, json, headers))
        return replies.pop(0)

    return Jev("m", "http://jev", "key", tmp_path / "jev", on_spend=spend, post=post, max_tries=3), calls


def test_a_repeated_decide_is_served_from_the_cache(tmp_path):
    spent = []
    jev, calls = make(tmp_path, [ok(0.25, a=3.0)], spent.append)

    assert jev.decide({"s": 1}, {"a": {}}) == jev.decide({"s": 1}, {"a": {}}) == {"a": {"type": "score", "score": 3.0}}
    assert len(calls) == 1 and calls[0][2] == {"Authorization": "Bearer key"}
    assert jev.usage == {"calls": 2, "usd": 0.5} and spent == [0.25]


def test_retries_rate_limits_and_stops_on_other_errors(tmp_path, monkeypatch):
    sleeps = []
    monkeypatch.setattr(jev_module.time, "sleep", sleeps.append)

    jev, calls = make(tmp_path, [Reply(429), ok(a=1.0)])
    assert jev.decide({}, {"a": {}})["a"]["score"] == 1.0
    assert len(calls) == 2 and sleeps == [2]

    jev, calls = make(tmp_path, [Reply(401)])
    with pytest.raises(JevUnavailable):
        jev.decide({}, {"b": {}})
    assert len(calls) == 1

    jev, calls = make(tmp_path, [Reply(503)] * 3)
    with pytest.raises(JevUnavailable):
        jev.decide({}, {"c": {}})
    assert len(calls) == 3


def test_fact_scores_builds_the_validated_wording_and_maps_answers_to_fact_ids(tmp_path):
    jev, calls = make(tmp_path, [ok(f1=3.0, f2=1.0)])
    facts = [Fact("f1", "mapping", "s", "Rule one.", learned_from="Q one?"), Fact("f2", "mapping", "s", "Rule two.")]

    assert fact_scores(jev, "f1 (racing)", "Which drivers finished?", facts) == {"f1": 3.0, "f2": 1.0}
    body = calls[0][1]
    assert body["state"] == {"database": "f1 (racing)", "question": "Which drivers finished?",
                             "facts": {"f1": {"rule": "Rule one.", "learned_from": "Q one?"},
                                       "f2": {"rule": "Rule two.", "learned_from": ""}}}
    ask = body["questions"]["f1"]
    assert ask["instructions"] == "How directly does the rule in `facts.f1`.rule apply to `question`?"
    assert ask["criteria"][-1] == ("Directly applies: `question` uses the exact phrase, value or measure the rule "
                                   "defines, in the same sense as `facts.f1`.learned_from.")
    assert fact_scores(jev, "d", "q", []) == {}


def test_replay_only_replays_a_cached_decide_and_a_miss_raises_without_calling(tmp_path):
    jev, calls = make(tmp_path, [ok(a=3.0)])
    jev.decide({"s": 1}, {"a": {}})

    replay = Jev("m", "http://jev", "key", tmp_path / "jev", post=jev.post, replay_only=True)
    assert replay.decide({"s": 1}, {"a": {}})["a"]["score"] == 3.0
    with pytest.raises(ReplayMiss, match="cache miss"):
        replay.decide({"s": 2}, {"a": {}})
    assert len(calls) == 1
