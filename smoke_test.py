"""Smoke test: answer the first N questions (docs arm, no notes) with an agent profile and print every step.
Usage: edit PROFILE / N_QUESTIONS below, then `uv run python smoke_test.py`.
Writes nothing to runs/; replies are cached in cache/llm, so rerunning the same questions costs nothing."""
import random
import time

from dotenv import load_dotenv

from evosql.agent import answer
from evosql.analysis import usd
from evosql.bird import exec_match, gold_rows, load_questions, open_db
from evosql.knowledge import Knowledge
from evosql.llm import LLM, ProviderExhausted
from evosql.stream import load_config, make_llm

# Edit these two lines: PROFILE is an agent profile from configs/base.yaml (deepseek, deepseek_v1 or local).
PROFILE = "deepseek"
N_QUESTIONS = 2


class LoggedLLM(LLM):
    """LLM that prints each call's latency, tokens, prefix-cache hits and chosen tool."""

    prices = None

    def chat(self, messages, tools=None, temperature=0.0, sample=0):
        start = time.time()
        reply = super().chat(messages, tools, temperature, sample)
        took = time.time() - start
        cached = " (local cache)" if took < 0.05 else ""
        hits = reply.get("provider_cached_tokens", 0)
        cost = usd(reply, self.prices)
        for call in reply["tool_calls"] or [{"name": "(text reply)", "arguments": reply["content"] or ""}]:
            print(f"      -> {call['name']} {call['arguments'][:100]!r}  [{took:.1f}s{cached}, "
                  f"{reply['prompt_tokens']} in ({hits} cache hit) / {reply['completion_tokens']} out, ${cost:.5f}]",
                  flush=True)
        return reply


def main():
    load_dotenv()
    cfg = load_config(agent=PROFILE)
    base = make_llm(cfg["agent"], cfg["cache_dir"])
    # Same client and options as the real runs, with fewer retries so a stuck provider shows up fast.
    llm = LoggedLLM(base.model, client=base.client, cache_dir=cfg["cache_dir"], max_tries=2, options=base.options)
    llm.prices = cfg["agent"].get("usd_per_million")
    print(f"profile: {PROFILE} | model: {llm.model} | questions: {N_QUESTIONS}", flush=True)

    db = open_db(cfg["data_dir"], cfg["db"], with_docs=True, with_profile=cfg["agent"].get("value_profile", False))
    questions = load_questions(cfg["data_dir"], cfg["db"])
    random.Random(0).shuffle(questions)  # same order 0 as every arm

    right, t0 = 0, time.time()
    for i, q in enumerate(questions[:N_QUESTIONS], 1):
        print(f"\n[{i}/{N_QUESTIONS}] q{q.qid} ({q.difficulty}): {q.question}", flush=True)
        start = time.time()
        show = lambda step, tools: print(f"    step {step}: waiting for model...", flush=True) if not tools else None
        try:
            result = answer(llm, db, q.question, Knowledge(), max_steps=cfg["max_steps"], on_step=show)
        except ProviderExhausted as e:
            print(f"    provider failed: {e}\nStopping. Rerun later; finished calls are cached.")
            break
        ok = exec_match(db.path, result.sql, gold_rows(db.path, q))
        right += ok
        print(f"    => {'RIGHT' if ok else 'WRONG'} in {time.time() - start:.0f}s, {result.steps} steps"
              f"{' (' + result.error + ')' if result.error else ''}", flush=True)
        print(f"    submitted: {result.sql}", flush=True)
        print(f"    gold:      {q.gold_sql}", flush=True)
        print(f"    running: {right}/{i} right, {time.time() - t0:.0f}s total", flush=True)

    u = llm.usage
    hit_ratio = u["provider_cached_tokens"] / u["prompt_tokens"] if u["prompt_tokens"] else 0
    print(f"\nDone: {right} right | {u['calls']} calls ({u['cached']} from local cache) | "
          f"{u['prompt_tokens']} in ({hit_ratio:.0%} prefix-cache hits) / {u['completion_tokens']} out | "
          f"${usd(u, llm.prices):.4f} | {time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()
