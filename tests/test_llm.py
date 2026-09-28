from types import SimpleNamespace

from evosql.llm import LLM


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
