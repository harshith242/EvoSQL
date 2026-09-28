"""OpenAI-compatible chat client (Ollama or Groq) with a disk cache, retry/backoff and usage counters.
Cached replies still count toward usage, so reported cost is the logical cost of the run.
The cache key has no model digest: clear cache/llm after changing an Ollama Modelfile."""
import hashlib
import json
import os
import time
from pathlib import Path

import openai
from tqdm import tqdm

RETRYABLE = (openai.APIConnectionError, openai.APITimeoutError, openai.InternalServerError)
MAX_WAIT = 120  # a longer retry-after means a daily limit: stop and resume later instead of sleeping


class ProviderExhausted(Exception):
    pass


class LLM:
    def __init__(self, model, base_url=None, api_key=None, cache_dir="cache/llm", client=None, max_tries=10, options=None):
        self.model = model
        self.client = client or openai.OpenAI(base_url=base_url, api_key=api_key, max_retries=0, timeout=600)
        self.cache_dir = Path(cache_dir)
        self.max_tries = max_tries
        self.options = options or {}  # extra request params, e.g. {"reasoning_effort": "low"}
        self.usage = {"calls": 0, "cached": 0, "prompt_tokens": 0, "completion_tokens": 0, "provider_cached_tokens": 0}
        self.models_seen = set()  # model ids reported by the provider, to catch silent model swaps

    def chat(self, messages, tools=None, temperature=0.0, sample=0):
        """Return {content, tool_calls: [{id, name, arguments}], model, prompt_tokens, completion_tokens, ...}."""
        payload = [self.model, self.options, messages, tools, temperature, sample]
        key = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
        path = self.cache_dir / key[:2] / f"{key}.json"
        if path.exists():
            reply = json.loads(path.read_text())
            self.usage["cached"] += 1
        else:
            reply = self._call(messages, tools, temperature)
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".tmp")
            tmp.write_text(json.dumps(reply))
            os.replace(tmp, path)  # atomic, so a kill never leaves a truncated cache file
        self.usage["calls"] += 1
        self.usage["prompt_tokens"] += reply["prompt_tokens"]
        self.usage["completion_tokens"] += reply["completion_tokens"]
        self.usage["provider_cached_tokens"] += reply.get("provider_cached_tokens", 0)
        self.models_seen.add(reply["model"])
        return reply

    def _call(self, messages, tools, temperature):
        extra = {"tools": tools, **self.options} if tools else dict(self.options)
        for attempt in range(self.max_tries):
            try:
                resp = self.client.chat.completions.create(
                    model=self.model, messages=messages, temperature=temperature, **extra
                )
            except openai.RateLimitError as e:
                last = e
                wait = float(e.response.headers.get("retry-after") or 2 ** (attempt + 1))
                if wait > MAX_WAIT:
                    raise ProviderExhausted(f"{self.model}: rate limited for {wait:.0f}s (daily limit?)")
                tqdm.write(f"  {self.model}: rate limited, waiting {wait:.0f}s")
                time.sleep(wait)
                continue
            except RETRYABLE as e:
                last = e
                time.sleep(min(2 ** (attempt + 1), 60))
                continue
            msg = resp.choices[0].message
            calls = [{"id": c.id, "name": c.function.name, "arguments": c.function.arguments} for c in msg.tool_calls or []]
            details = getattr(resp.usage, "prompt_tokens_details", None)
            return {
                "content": msg.content,
                "tool_calls": calls,
                "model": resp.model,
                "prompt_tokens": resp.usage.prompt_tokens,
                "completion_tokens": resp.usage.completion_tokens,
                "provider_cached_tokens": (getattr(details, "cached_tokens", 0) or 0) if details else 0,
            }
        raise ProviderExhausted(f"{self.model}: {last}")
