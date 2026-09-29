"""OpenAI-compatible chat client (DeepSeek or Ollama) with a disk cache, retry/backoff, usage and spend reporting.
A reply cached by an earlier run counts toward usage (logical cost) once per process, never toward real spend.
The cache key has no model digest: clear cache/llm after changing an Ollama Modelfile."""
import hashlib
import json
import os
import re
import time
from pathlib import Path

import openai
from tqdm import tqdm

from evosql.files import write_atomic

RETRYABLE = (openai.APIConnectionError, openai.APITimeoutError, openai.InternalServerError)
MAX_WAIT = 120  # a longer retry-after means a daily limit: stop and resume later instead of sleeping
TOKENS = ("prompt_tokens", "completion_tokens", "provider_cached_tokens")


class ProviderExhausted(Exception):
    pass


def usd(usage, prices):
    """Dollar cost of a usage record; prices are USD per 1M tokens (missing prices = free, e.g. local)."""
    if not prices:
        return 0.0
    hit = usage.get("provider_cached_tokens", 0)
    miss = usage.get("prompt_tokens", 0) - hit
    return (hit * prices["cache_hit"] + miss * prices["cache_miss"] + usage.get("completion_tokens", 0) * prices["output"]) / 1e6


def extract_json(text):
    """The first {...} object in a reply, or None."""
    match = re.search(r"\{.*\}", text or "", re.DOTALL)
    try:
        return json.loads(match.group(0)) if match else None
    except json.JSONDecodeError:
        return None


def _cache_hit_tokens(usage):
    """Prompt tokens served from the provider's prefix cache (DeepSeek or OpenAI-style field)."""
    hits = getattr(usage, "prompt_cache_hit_tokens", None)
    if hits is None:
        details = getattr(usage, "prompt_tokens_details", None)
        hits = getattr(details, "cached_tokens", 0) if details else 0
    return hits or 0


class LLM:
    def __init__(self, model, base_url=None, api_key=None, cache_dir="cache/llm", client=None, max_tries=10,
                 options=None, prices=None, on_spend=None):
        self.model = model
        self.client = client or openai.OpenAI(base_url=base_url, api_key=api_key, max_retries=0, timeout=600)
        self.cache_dir = Path(cache_dir)
        self.max_tries = max_tries
        self.options = options or {}  # extra request params, e.g. {"reasoning_effort": "low"}
        self.prices, self.on_spend = prices, on_spend  # on_spend(usd) runs after every real (non-cached) call
        self.usage = {"calls": 0, "cached": 0, **dict.fromkeys(TOKENS, 0)}
        self.seen = set()  # cache keys already counted in this process: in-run replays are free

    def chat(self, messages, tools=None, temperature=0.0, sample=0):
        """Return {content, reasoning, tool_calls: [{id, name, arguments}], model, and the TOKENS counts}."""
        payload = [self.model, self.options, messages, tools, temperature, sample]
        key = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
        path = self.cache_dir / key[:2] / f"{key}.json"
        if path.exists():
            reply = json.loads(path.read_text())
            if key in self.seen:
                return reply
            self.usage["cached"] += 1
        else:
            reply = self._call(messages, tools, temperature)
            write_atomic(path, json.dumps(reply))
            if self.on_spend:
                self.on_spend(usd(reply, self.prices))
        self.seen.add(key)
        self.usage["calls"] += 1
        for k in TOKENS:
            self.usage[k] += reply.get(k, 0)
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
            if not getattr(resp, "choices", None):
                # Some providers answer 200 with an error body and no choices when the upstream model fails.
                last = f"empty response: {getattr(resp, 'error', None)}"
                time.sleep(min(2 ** (attempt + 1), 60))
                continue
            msg = resp.choices[0].message
            calls = [{"id": c.id, "name": c.function.name, "arguments": c.function.arguments} for c in msg.tool_calls or []]
            return {
                "content": msg.content,
                "reasoning": getattr(msg, "reasoning_content", None),  # DeepSeek thinking; must be sent back with tools
                "tool_calls": calls,
                "model": resp.model,
                "prompt_tokens": resp.usage.prompt_tokens,
                "completion_tokens": resp.usage.completion_tokens,
                "provider_cached_tokens": _cache_hit_tokens(resp.usage),
            }
        raise ProviderExhausted(f"{self.model}: {last}")


def make_llm(role_cfg, cache_dir, on_spend=None):
    """LLM for a config role (agent profile or proposer); a role without api_key_env is a local server."""
    key_env = role_cfg.get("api_key_env")
    api_key = os.environ[key_env] if key_env else "local"
    return LLM(role_cfg["model"], role_cfg["base_url"], api_key, cache_dir, options=role_cfg.get("options"),
               prices=role_cfg.get("usd_per_million"), on_spend=on_spend)
