from types import SimpleNamespace

import openai
import pytest

from evosql.llm import LLM, ProviderExhausted, usd


class FakeTransport:
    """Stands in for openai.OpenAI; counts how many real API calls are made."""

    def __init__(self):
        self.calls = 0
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    def create(self, **kwargs):
        self.calls += 1
        message = SimpleNamespace(content="SELECT 1", tool_calls=None)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=message)],
            model=kwargs["model"],
            usage=SimpleNamespace(prompt_tokens=100, completion_tokens=10),
        )


def test_repeat_call_is_served_from_cache_but_still_counted(tmp_path):
    transport = FakeTransport()
    llm = LLM("m", cache_dir=tmp_path, client=transport)
    messages = [{"role": "user", "content": "hi"}]
    first = llm.chat(messages)
    second = llm.chat(messages)
    assert first == second and transport.calls == 1
    assert llm.usage == {"calls": 2, "cached": 1, "prompt_tokens": 200, "completion_tokens": 20, "provider_cached_tokens": 0}


def test_different_sample_index_bypasses_cache(tmp_path):
    transport = FakeTransport()
    llm = LLM("m", cache_dir=tmp_path, client=transport)
    messages = [{"role": "user", "content": "hi"}]
    llm.chat(messages, sample=0)
    llm.chat(messages, sample=1)
    assert transport.calls == 2


def rate_limited(retry_after):
    error = openai.RateLimitError.__new__(openai.RateLimitError)
    error.response = SimpleNamespace(headers={"retry-after": str(retry_after)})
    return error


def test_per_minute_limit_is_waited_out_but_daily_limit_stops_the_run(tmp_path, monkeypatch):
    slept = []
    monkeypatch.setattr("evosql.llm.time.sleep", slept.append)
    transport = FakeTransport()
    errors = [rate_limited(3)]
    real_create = transport.create
    transport.chat.completions.create = lambda **kw: (_ for _ in ()).throw(errors.pop()) if errors else real_create(**kw)
    assert LLM("m", cache_dir=tmp_path, client=transport).chat([{"role": "user", "content": "a"}])["content"] == "SELECT 1"
    assert slept == [3.0]

    transport.chat.completions.create = lambda **kw: (_ for _ in ()).throw(rate_limited(3600))
    with pytest.raises(ProviderExhausted):
        LLM("m", cache_dir=tmp_path, client=transport).chat([{"role": "user", "content": "b"}])
    assert slept == [3.0]


def test_response_without_choices_is_retried_then_stops_cleanly(tmp_path, monkeypatch):
    monkeypatch.setattr("evosql.llm.time.sleep", lambda s: None)
    transport = FakeTransport()
    transport.chat.completions.create = lambda **kw: SimpleNamespace(choices=None, error={"message": "upstream failed"})
    with pytest.raises(ProviderExhausted, match="empty response"):
        LLM("m", cache_dir=tmp_path, client=transport, max_tries=3).chat([{"role": "user", "content": "c"}])


def test_usd_charges_cache_hits_at_the_cheap_rate_and_local_models_nothing():
    prices = {"cache_hit": 0.003, "cache_miss": 0.15, "output": 0.60}
    usage = {"prompt_tokens": 1_000_000, "provider_cached_tokens": 900_000, "completion_tokens": 100_000}
    # 0.9M hits * 0.003 + 0.1M misses * 0.15 + 0.1M output * 0.60 = 0.0027 + 0.015 + 0.06
    assert abs(usd(usage, prices) - 0.0777) < 1e-9
    assert usd(usage, None) == 0.0
