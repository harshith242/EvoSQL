# EvoSQL

A Text2SQL agent that gets better at **one database** over time by writing short notes from its own mistakes, with a **gate** that only keeps the notes that measurably help. It is compared honestly against a naive "keep anything that fixes it" learner and a baseline that spends the same tokens.

## Why

Self-improving agents (harness self-improvement, evolving tribal knowledge) are a hot topic, but most published gains are single-run and not budget-matched. EvoSQL asks a narrower question with an objective verifier (SQL execution): *does gated learning beat naive learning and simply spending more tokens, once noise is accounted for?*

## How it works

For each question, in a shuffled stream:

1. **Answer** with the current notes (tool loop: describe tables, profile columns, test SQL, submit).
2. **Score** by execution match against the gold SQL. The question is scored *before* anything is learned from it.
3. **Learn** (only when wrong): a proposer model compares the wrong SQL with the gold SQL and drafts one note.
4. **Gate**: the note is kept only if all of these hold:
   - it leaks no answer and stays short;
   - it fixes this question;
   - replaying up to 5 earlier related questions shows it does not break more of them than the calibrated noise band explains.
5. **Prune** every 20 questions: notes whose removal costs nothing are dropped.

The gold SQL stands in for an analyst correcting the agent. BIRD's hand-written hints are hidden, so scores are **not** comparable to the BIRD leaderboard.

## Arms

| Arm | Docs | Learning |
|---|---|---|
| vanilla | no | none |
| docs | BIRD column descriptions | none |
| selfcons | yes | none; majority vote over N samples, N matched to EvoSQL's tokens |
| ratchet | yes | keep any note that fixes the current question |
| **evosql** | yes | gated (replay, noise band, leakage/size checks, cap, pruning) |

## Setup

Requires [uv](https://docs.astral.sh/uv/) and a [DeepSeek](https://platform.deepseek.com) API key. [Ollama](https://ollama.com) is optional, as a free local fallback agent.

```bash
uv sync
python scripts/get_bird.py thrombosis_prediction      # downloads BIRD dev once, keeps one database
echo "DEEPSEEK_API_KEY=..." > .env
uv run python smoke_test.py                           # 2 questions, prints every agent step, cost and cache hits
# optional local fallback:
ollama pull qwen3.5:9b && ollama create qwen3.5-9b-32k -f ollama/qwen3.5-9b-32k.Modelfile
```

## Run

Arms: `vanilla`, `docs`, `ratchet`, `evosql`, `selfcons`, plus `docs_hints` as a reference only. Each one is a YAML file in `configs/arms/`.

Useful flags for `run`:
- `--arm` takes one or more arm names and runs them in the order given.
- `--order` picks question orders (seeds). The default is every order in `configs/base.yaml` for learning arms, and only the first order for non-learning arms, whose answers don't depend on order.
- `--limit N` stops after N questions per order, which is handy for quick checks.

**Step 0: calibrate the noise rate once.** The `evosql` arm needs it and refuses to start without it.

```bash
uv run python -m evosql calibrate --n 20
```

**Test one arm**, e.g. only EvoSQL, as a 5-question check on order 0:

```bash
uv run python -m evosql run --arm evosql --order 0 --limit 5
```

**Run one arm fully** (all orders):

```bash
uv run python -m evosql run --arm evosql
```

**Run all arms.** `selfcons` goes last, because its N comes from EvoSQL's token use. Run `analyze` after `evosql`, copy the printed N into `configs/arms/selfcons.yaml`, then run `selfcons`:

```bash
uv run python -m evosql run --arm vanilla docs ratchet evosql
uv run python -m evosql analyze
uv run python -m evosql run --arm selfcons
```

**Analyze** whatever has run so far. This writes `results/summary.md`, `learning_curve.png` and `notes_growth.png`:

```bash
uv run python -m evosql analyze
```

**Choose the agent model** with `--agent`, placed *before* the command. Profiles live in `configs/base.yaml`:

| Profile | Model | Limits | Output folders |
|---|---|---|---|
| `deepseek` (default) | DeepSeek `deepseek-flash`, thinking on (high) + value profile | pay per token, cents per question | `runs_deepseek_v2/`, `results_deepseek_v2/` |
| `deepseek_v1` | DeepSeek `deepseek-flash`, thinking off, no value profile | first DeepSeek runs, kept for comparison | `runs_deepseek/`, `results_deepseek/` |
| `local` | Ollama `qwen3.5:9b` | free, no limits, slow | `runs/`, `results/` |

The proposer is always `deepseek-flash` with thinking on (one call per wrong answer). The **value profile** is built once from the data before question 1 (plain SQL, no LLM): for every column its null share, its coded values with counts (e.g. `Laboratory.RNP: '0' 72, 'negative' 22, ...`), or its numeric/date range. It sits in every arm's system prompt between the schema and the learned notes, so it is part of the cached prefix. Each profile has its own runs, noise rate and results, so answers from different agent models never mix, and every profile needs its own `calibrate`. Ollama is a manual fallback (`--agent local`), never an automatic switch mid-run. Prompts are ordered static-first (rules, schema, notes, then the question) so DeepSeek's prefix cache serves most input tokens at the cache-hit price; `analyze` reports the hit ratio and $ per correct answer.

Runs are resumable. Every LLM reply is cached under `cache/`, and each arm appends one line per question to `runs/<arm>/<db>/order<k>.jsonl`. If a run stops (Ctrl-C, crash, provider limit), rerun the same command and it continues where it stopped. A later run without `--limit` extends a limited one.

To rerun an arm from scratch, delete its folder under `runs/<arm>/`. Clear `cache/llm/` only if you change the Ollama Modelfile, because cached replies are keyed by the model name, not its weights.

## Results

Results are pending: see `results/summary.md` after a run.
