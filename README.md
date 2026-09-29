# EvoSQL

A Text-to-SQL agent that builds a **memory of each database** as it answers questions. After each answer it sees the correct SQL, turns its mistakes into short, checked facts about the database, and uses the relevant facts on later questions. The question EvoSQL tests, honestly:

> In an online stream of questions about one database, where the agent receives the correct SQL after each answer, does a per-database fact memory improve accuracy on later questions compared with the same agent without memory?

Spec: `docs/specs/2026-09-29-evosql-v6-design.md`.

## How it works

- **Data:**
  - Arcwise-Plat: BIRD Mini-Dev with expert-corrected SQL, questions and column descriptions ([repo](https://github.com/uiuc-kang-lab/text_to_sql_benchmarks));
  - the 4 largest databases, 221 questions;
  - pinned by commit and SHA-256 hashes in `data/arcwise/manifest.json`.
- **Agent:** a tool loop (describe tables, profile columns, test SQL, submit). The prompt holds the schema and a value profile per column, computed from the data and ending with the column's corrected description. Hints are never shown.
- **Arms:**
  - `none`: no memory;
  - `facts`: the same agent, plus at most 1–2 learned facts in the prompt.
- **Stream:** each database's questions come one at a time, in 2 pre-registered orders. For every question:
  1. both arms answer and are scored;
  2. then the correct SQL is revealed and the memory learns (test, then train).

**How the facts arm learns and uses facts:**

| Step | What happens |
|---|---|
| Learn | When the facts arm fails, the proposer writes one general fact from the question, the wrong SQL and the correct SQL, with trigger phrases and the stored values it relies on. |
| Check | Free checks drop facts that contain SQL, name missing columns or values, only restate the docs, or leak the answer. |
| Pre-check | The new fact is tried alone on up to 2 earlier matching questions, and rejected on any regression. |
| Retrieve | Facts are injected only on a whole-phrase trigger match. A generic phrase needs a second cue; grain and relation facts need the question to mention their table. Proven facts may also match by meaning. An unproven fact always goes alone. |
| Prune | Each use scores +1 or −1 against the no-memory answer. A fact is retired at its first regression while unproven, at −2 once proven, or after 5 uses with no effect. |

**Report:** each (order, database) stream is one unit of evidence. It gives:
- second-half accuracy, facts vs none, per stream;
- a direction count and a stream-level bootstrap;
- question-level statistics, labelled heuristic;
- an injection-rate check (was the memory actually used?);
- a learning curve, cost and latency, and every fact with its score.

## Setup

Requires [uv](https://docs.astral.sh/uv/), a [DeepSeek](https://platform.deepseek.com) API key and [Ollama](https://ollama.com) (local embeddings).

```bash
uv sync
echo "DEEPSEEK_API_KEY=..." > .env
ollama pull qwen3-embedding:0.6b
uv run python scripts/get_v6_data.py      # BIRD dev (~346 MB, once; keeps the 4 databases) + Arcwise-Plat + manifest
```

## Run

```bash
uv run python -m evosql stream     # both orders, all databases; $2 cap; rerun to resume (cached calls are free)
uv run python -m evosql report     # results_v6/summary.md
```

Settings are in `configs/base.yaml`: databases, orders, budget per order, retrieval and pruning thresholds. The optional `--agent local` runs a free local model (`ollama/qwen3.5-9b-32k.Modelfile`).

## History

Earlier versions (git tags `v3`, `v4`, `v5`) learned facts once, froze them and tested on BIRD dev `thrombosis_prediction` (59 final questions):

| Version | Result | Lesson |
|---|---|---|
| v3 | Facts kept by a learning gate did worse than no facts (10 vs 12) | Selecting facts on the same questions they came from is optimistic |
| v4 | Retrieved facts 15 vs no facts 11 (+4/−0, p = 0.125) | A real effect size (+6.8 points), but too few questions to prove it |
| v5 | Column descriptions in the prompt raised the baseline to 18; facts added nothing | The docs held most of the missing knowledge; the labels were noisy (26 gold-SQL fixes needed) |

v6 moves to expert-corrected labels, several databases, an online memory and stricter fact handling. For comparison, EvoOntology (arXiv 2609.15779) reports +6.3 points for the same agent model on BIRD Mini-Dev.

## Results

Pending: see `results_v6/summary.md` after a run.
