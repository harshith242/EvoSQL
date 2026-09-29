# EvoSQL

A Text2SQL agent that learns **facts about one database** from its own mistakes: what question phrases mean in the data, how values are encoded, which ranges apply, what one row is and how tables join. The facts are checked against the data, delivered to the agent in different ways, and judged on questions never used before, against a no-knowledge baseline.

## Why

Self-improving agents (harness self-improvement, evolving ontologies and tribal knowledge) are a hot topic, but most published gains are single-run and not budget-matched. EvoSQL asks a narrow question with an objective verifier, SQL execution: *does verified, learned database knowledge help an agent on unseen questions, and does it matter how the knowledge is delivered (all in the prompt, retrieved per question, or searched by the agent as a tool)?* The evaluation separates discovery, the gate and the final test, and reports noise honestly (paired tests, confidence intervals, corrected labels).

## v5: docs first, learn only the gaps

Spec: `docs/specs/2026-09-29-evosql-v5-design.md`. v4 showed three things:
- **The docs baseline never read the docs.** BIRD's column docs hold the exact normal ranges, but the agent opened them on 5 of 59 questions.
- **Most learned facts restated those docs.**
- **Much of the remaining error is label noise.**

v5 changes the v4 pipeline below in four ways:
- **Docs in the prompt:** every value-profile line ends with the column's BIRD description (e.g. `| creatinine phosphokinase | values: Normal range: N < 250`), for the agent and the proposer.
- **Gap-only discovery:**
  - the proposer is told to write only what the docs miss: conventions such as age = current year minus birth year, boundary inclusivity, exact value matching, stored codes, grain and joins;
  - a free check drops facts that only restate a column's docs.
- **Two fact sets from one run:**
  - `single`: every checked fact;
  - `verified`: only the facts whose own question passes when re-answered with them.
- **Arms:**
  - `docs` and `hints` (docs plus BIRD's hand-written hint for each question, the ceiling);
  - `retrieve@single` and `retrieve@verified`.

  The gate picks between the two retrieve arms.

v5 reuses the v4 final set, which was already seen in the v4 analysis and label review, so every v5 result is labelled **diagnostic**.

**Reviewed labels:** `labels/evosql_fixes.json` holds 26 gold-SQL fixes for this database, each with a reason. Examples: counting lab rows as patients, `OR` without brackets, `SSB = 'negative' OR '0'`, an unquoted date, text-vs-number comparisons. They are layered over the annotation-error study's labels and feed only the corrected score.

## How it works (v4 pipeline, still the core)

Spec: `docs/specs/2026-09-29-evosql-v4-design.md`. One BIRD database (`thrombosis_prediction`, 163 questions), BIRD's hints hidden.

1. **Question sets:** discovery 43, gate 46, final 59. The 15 questions seen by the early pilots are excluded; the final set was never used by any run.
2. **Discover** (one pass, discovery set only):
   - The docs agent answers every discovery question.
   - A proposer looks at batches of up to 5 failures (question, agent SQL, gold SQL) and writes typed facts, one misconception per fact: `mapping`, `encoding`, `constraint`, `meaning`, `grain` (what one row is) and `relation` (join path and cardinality). Each fact has 1-5 trigger phrases (`applies_to`) and an optional evidence query (`probe`).
   - Free checks drop facts that contain SQL, name columns or values that do not exist, have a probe that fails or returns nothing, or leak an answer.
   - A deterministic merge unites duplicates and resolves a phrase mapped to different columns.
   - Questions whose official gold is known to be wrong (from the annotation-error study) are not learned from.
3. **Deliver:** the same agent, with only the knowledge delivery changed:

| Mode | Knowledge the agent gets |
|---|---|
| docs | none (schema + BIRD column docs + value profile only) |
| all | every fact in the system prompt |
| retrieve | per question: the top 8 facts from hybrid search on the question, plus every grain and relation fact |
| tool | a one-line list of subjects with knowledge, plus a `search_knowledge(query)` tool returning the top 5 facts |

   **Hybrid search** (retrieve and tool): BM25 over each fact's phrases, subject and text, plus cosine similarity of local embeddings (`qwen3-embedding:0.6b`), fused with Reciprocal Rank Fusion. A fact that matches neither signal is never returned.
4. **Gate** (one shot, gate set): each knowledge mode passes if fixes >= regressions and regressions <= 3 against docs. The headline mode is the passing mode with the best net; if none passes, the headline is docs.
5. **Final test:** every mode answers the 59 final questions once.

The agent is a tool loop (describe tables, profile columns, test SQL, submit). Its prompt is ordered static-first (rules, schema, a per-column **value profile** computed from the data, then knowledge, then the question), so the provider's prefix cache serves most input tokens.

**Scoring:** the primary score uses BIRD's official gold SQL. A sensitivity score uses the corrected gold SQL from the annotation-error study ([uiuc-kang-lab/text_to_sql_benchmarks](https://github.com/uiuc-kang-lab/text_to_sql_benchmarks)) where it exists. Scores are not comparable to the BIRD leaderboard (hints hidden).

## Setup

Requires [uv](https://docs.astral.sh/uv/), a [DeepSeek](https://platform.deepseek.com) API key and [Ollama](https://ollama.com) (local embeddings for the retrieve and tool modes; optionally a free local agent with `--agent local`).

```bash
uv sync
python scripts/get_bird.py thrombosis_prediction      # downloads BIRD dev once, keeps one database
echo "DEEPSEEK_API_KEY=..." > .env
ollama pull qwen3-embedding:0.6b
# optional local agent:
ollama pull qwen3.5:9b && ollama create qwen3.5-9b-32k -f ollama/qwen3.5-9b-32k.Modelfile
```

## Run

```bash
uv run python -m evosql partition                                  # runs_v5/partitions.json
uv run python -m evosql labels                                     # corrected gold (asks before downloading)
uv run python -m evosql run --set final --arm docs hints           # step 1: how much room is left for learning
uv run python -m evosql discover                                   # runs_v5/knowledge_single.json, knowledge_verified.json
uv run python -m evosql gate                                       # runs_v5/gate.json with the headline arm
uv run python -m evosql run --set final --arm retrieve@single retrieve@verified
uv run python -m evosql analyze                                    # results_v5/summary.md
```

The arms are listed in `protocol.arms`. The v4 pipeline (modes all, retrieve and tool over one fact set) is at git tag `v4`.

- **Resumable and cheap to rerun:** every LLM reply is cached under `cache/llm/` (embeddings under `cache/embed/`), so rerunning a command continues where it stopped and replays finished calls for free.
- **Budget:** a spend guard stops cleanly at `protocol.budget_usd` ($2) of real API spend, priced at peak rates.
- **Settings:** `configs/base.yaml` (agent profiles and column docs, proposer, search, question sets, arms, gate rule, budget).

The report gives the primary endpoint (headline mode vs docs on the final set: difference with a 95% CI and an exact McNemar p-value) and, for every mode, accuracy, fixes and regressions against docs on official and corrected gold, cost, $ per correct answer, latency p50/p95, agent turns and knowledge use. It also lists the gate decision, what discovery kept and dropped, and the facts verbatim.

## Pilot history

Earlier streaming pilots (v1/v2, spec `docs/specs/2026-09-28-evosql-design.md`, in git history) learned free-text notes after each question. They showed three problems:
- the notes turned into SQL patches ("use `UN = 29`");
- they copied BIRD annotation errors (counting joined rows as patients);
- the gains were lost in noise.

v3 (`docs/specs/2026-09-29-evosql-v3-design.md`, git tag `v3`) used typed, data-checked facts, a 50/50 learning/test split and a gate that kept a batch of facts only if it raised the learning-set score. On the 50 test questions: docs 12, gated facts 10 (+1/-3), ungated facts 15 (+6/-3), none significant. The gate was scored on the same questions the facts came from, rejected true facts in bundles, and injecting every fact caused style flips on unrelated questions. v4 separates discovery from the gate, adds grain and relation facts, and delivers knowledge on demand.

## Results

Final set (59 questions, `thrombosis_prediction`, hints hidden unless stated). Corrected gold = the study's fixes plus this repo's reviewed fixes.

| Run | Official | Corrected | Notes |
|---|---|---|---|
| v4 docs (docs behind a tool) | 11 | 18 | the agent almost never opened the docs |
| v4 retrieve (learned facts) | 15 | 24 | +4/−0 vs docs, p = 0.125; mostly facts that restate the docs |
| **v5 docs (docs in the prompt)** | **18** | **30** | +8/−1 vs v4 docs, no learning at all |
| v5 hints (ceiling, diagnostic) | 26 | 41 | BIRD's hand-written hint for each question |

- **What the hints add:** of the 8 questions hints fixes over v5 docs, about 4–5 are learnable conventions (age, boundaries, exact matching). The rest are question-specific, or hints that contradict the docs or a buggy gold.
- **Results pending:** the v5 knowledge arms. See `results_v5/summary.md` after a run.
