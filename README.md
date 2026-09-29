# EvoSQL

A Text2SQL agent that learns **facts about one database** from its own mistakes: what question phrases mean in the data, how values are encoded, which ranges and rules apply. It keeps only the knowledge that measurably helps, freezes it, and is judged on questions it never learned from, against honest baselines at a matched budget.

## Why

Self-improving agents (harness self-improvement, evolving ontologies and tribal knowledge) are a hot topic, but most published gains are single-run and not budget-matched. EvoSQL asks a narrow question with an objective verifier, SQL execution: *does gated, learned database knowledge beat no knowledge, ungated knowledge, and simply spending the same money on more samples?*

## How it works

1. **Split:** 100 BIRD questions for one database, stratified by difficulty, halved into 50 learning and 50 test questions.
2. **Learn** (learning set only):
   - The agent answers every learning question.
   - A proposer looks at a batch of up to 5 failures (question, agent SQL, gold SQL) and states what the agent did not *know* as typed facts:
     - `mapping`: "admitted to the hospital" means `Patient.Admission` is `'+'`;
     - `constraint`: a normal range or rule;
     - `encoding`: how values are stored;
     - `meaning`: what a column represents.
   - Free checks drop facts that contain SQL, name columns or values that do not exist in the data, or leak an answer.
   - The proposer may skip a question whose gold SQL looks like an annotation error.
3. **Gate:** each batch yields a candidate knowledge version. It is kept only if it beats the current version on the whole learning set by at least `max(2, calibration flips)` and fixes a question in its batch. The calibration measures how many answers flip when a true but useless fact is added.
4. **Consolidate and freeze:** after 2 epochs, duplicates and contradictions are merged (kept only if the learning score does not drop), and the knowledge is frozen.
5. **Test:** every arm answers the same 50 test questions.

| Arm | Knowledge in the prompt | Answers per question |
|---|---|---|
| docs | none (schema + BIRD column docs + value profile only) | 1 |
| evosql | frozen, gated, consolidated facts | 1 |
| ungated | every fact that passed the free checks, no gate | 1 |
| selfcons | none | N (majority of result sets), N matched to evosql's spend including learning |

The agent is a tool loop (describe tables, profile columns, test SQL, submit). Its prompt is ordered static-first (rules, schema, a per-column **value profile** computed from the data, then knowledge, then the question), so the provider's prefix cache serves most input tokens.

**Scoring:** BIRD's hand-written hints are hidden, and answers are scored against BIRD's gold SQL as-is, including questionable annotations. Scores are therefore not comparable to the BIRD leaderboard.

## Setup

Requires [uv](https://docs.astral.sh/uv/) and a [DeepSeek](https://platform.deepseek.com) API key. [Ollama](https://ollama.com) is optional, as a free local agent (`--agent local`).

```bash
uv sync
python scripts/get_bird.py thrombosis_prediction      # downloads BIRD dev once, keeps one database
echo "DEEPSEEK_API_KEY=..." > .env
# optional local agent:
ollama pull qwen3.5:9b && ollama create qwen3.5-9b-32k -f ollama/qwen3.5-9b-32k.Modelfile
```

## Run

```bash
uv run python -m evosql split                               # runs_v3/split.json
uv run python -m evosql learn                               # runs_v3/knowledge_final.json, learn.jsonl
uv run python -m evosql test --arm docs evosql ungated      # frozen test answers
uv run python -m evosql test --arm selfcons                 # after docs and evosql (budget-matched N)
uv run python -m evosql analyze                             # results_v3/summary.md
```

- **Resumable and cheap to rerun:** every LLM reply is cached under `cache/llm/`, so rerunning a command continues where it stopped and replays finished calls for free.
- **Budget:** a spend guard stops cleanly at `v3.budget_usd` ($1) of real API spend.
- **Settings:** in `configs/base.yaml` (agent profiles, proposer, split sizes, epochs, batch size, budget).

The report gives, for each arm:
- test accuracy with a 95% CI, and a McNemar p-value against docs;
- test and learning cost;
- accuracy on test questions that use a column the learned facts are about vs. the rest.

It also covers what was learned, skipped and dropped, and lists the final facts verbatim.

## Pilot history

Earlier streaming pilots (v1/v2, spec `docs/specs/2026-09-28-evosql-design.md`, in git history) learned free-text notes after each question. They showed three problems:
- the notes turned into SQL patches ("use `UN = 29`");
- they copied BIRD annotation errors (counting joined rows as patients);
- the gains were lost in noise.

v3 (`docs/specs/2026-09-29-evosql-v3-design.md`) fixes these with typed, data-checked facts and a learning/test split.

## Results

Results are pending: see `results_v3/summary.md` after a run.
