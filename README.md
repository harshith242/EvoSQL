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
   - replaying up to 5 earlier related questions shows a net gain above the calibrated noise band.
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

Requires [uv](https://docs.astral.sh/uv/), [Ollama](https://ollama.com) and a free [Groq](https://console.groq.com) API key.

```bash
uv sync
python scripts/get_bird.py thrombosis_prediction      # downloads BIRD dev once, keeps one database
ollama pull qwen3.5:9b && ollama create qwen3.5-9b-32k -f ollama/qwen3.5-9b-32k.Modelfile
echo "GROQ_API_KEY=..." > .env
```

## Run

```bash
uv run python -m evosql calibrate                      # noise flip rate p
uv run python -m evosql run --arm docs --order 0
uv run python -m evosql run --arm evosql               # all orders in configs/base.yaml
uv run python -m evosql analyze                        # results/summary.md + charts
```

Runs are resumable: every LLM reply is cached under `cache/`, and each arm appends one line per question to `runs/<arm>/<db>/order<k>.jsonl`. Rerunning a command continues where it stopped.

## Results

Results are pending: see `results/summary.md` after a run.
