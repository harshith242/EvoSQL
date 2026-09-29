# EvoSQL v3 — Learn, Freeze, Test (Design Spec)

Date: 2026-09-29
Status: approved design, pre-implementation
Supersedes the streaming protocol of `2026-09-28-evosql-design.md` as the main result. The streaming runner stays in the repo so the v1/v2 runs remain reproducible.

## 1. Why v3

The v1/v2 pilots (15 streamed questions) showed three problems:

1. **Notes were SQL patches, not knowledge** ("use UN = 29", "don't use DISTINCT"). The gate rewarded fixing *this* question, which patches pass easily.
2. **Notes learned BIRD annotation errors** (counting lab rows for "how many patients", a missing-parentheses bug).
3. **The evidence was noise-dominated.** With thinking on, p = 0.27, and the gate accepted notes with net gain 0. EvoSQL cost 9× docs and gained nothing measurable.

v3 learns knowledge on one set of questions, freezes it, and judges it only on different questions. Patches get no credit there; real knowledge does.

## 2. Setup

| Item | Choice |
|---|---|
| Agent | `deepseek-flash`, thinking **off** (deterministic at temperature 0), prompt = rules + schema + BIRD docs + value profile + knowledge |
| Proposer, consolidator | `deepseek-flash`, thinking on (`reasoning_effort: high`) |
| Questions | 100 of the 163 `thrombosis_prediction` questions, sampled stratified by difficulty (seed 0) |
| Split | 50 learning / 50 test, stratified by difficulty; saved to `split.json` and used by every arm |
| Budget | ~$0.50–0.60 total; hard ceiling $1 |
| Outputs | `runs_v3/` and `results_v3/` (separate from v1/v2) |

## 3. Knowledge format

Knowledge is a list of typed facts, following EvoOntology's term / mapping / constraint / evidence idea:

```
Fact {id, kind: mapping | constraint | encoding | meaning, subject, fact, source_qids}
```

- **mapping:** a question phrase to data, e.g. "admitted to the hospital" means `Admission = '+'`.
- **constraint:** a range or rule, e.g. normal UN is below 30.
- **encoding:** how values are stored, e.g. normal RNP results are stored as both '0' and 'negative'.
- **meaning:** what a column represents, e.g. `aCL IgA` is the anti-cardiolipin antibody concentration used for rankings.
- **subject:** a column (`Table.Column`) or a domain term.

It is rendered in the system prompt grouped by subject, after the value profile:

```
Learned database knowledge:
Patient.Admission
  - [mapping] "admitted to the hospital" means Admission = '+'
Laboratory.UN
  - [constraint] normal is below 30; "borderline of passing" is the top normal value, 29
```

### Checks before any LLM test (free)

A fact is dropped, with the reason logged, if it fails any check:

1. **No SQL.** The fact text contains a SQL clause or keyword (`SELECT`, `FROM`, `WHERE`, `JOIN`, `GROUP BY`, `ORDER BY`, `COUNT(`, `DISTINCT`, `LIMIT`). Column names, operators and values are allowed.
2. **Grounded.** A `Table.Column` subject must exist. Every quoted literal in the fact must occur in that column. If the subject is a term, the literal must occur in some column the fact names.
3. **No leakage.** The fact contains a gold-result value that is not in the gold SQL, or it shares a 5-word run with the question (checked on the fact text only).

## 4. Proposer

- **Input:** static instructions, the fact schema, the DB schema, the value profile and the current knowledge (static first, for prefix-cache hits). Then a batch of up to 5 failed learning questions, each with the question, the agent's SQL and the gold SQL.
- **Task:** "Find the fact about this database that the agent did not know: what a phrase means, how values are encoded, a range or rule, what a column means. State facts about the data, never the SQL fix."
- **Output:** JSON with per question either facts (`add`, `modify` or `delete` by id) or `{"skip": "<reason>"}` when the gold SQL looks like an annotation error. Skips are logged and counted.

## 5. Learning loop

```
K = empty knowledge
calibrate: answer the 50 learning questions with K and with K + one neutral fact; f = number of flips
for epoch in 1..2:
    answer all 50 learning questions with K        # cached while K is unchanged
    failures = wrong questions, in split order
    for batch in chunks(failures, 5):
        facts = proposer(batch, K) -> keep the ones that pass the checks
        if no facts: continue
        candidate = K + facts
        score candidate on all 50 learning questions, paired with K
        accept if net_gain >= max(2, f) and candidate fixes >= 1 question in the batch
        if accepted: K = candidate
C = consolidate(K)        # one call: merge duplicates, resolve contradictions, same fact format, same checks
if score(C) >= score(K) on the learning set: K = C
freeze K
```

- **net_gain** = learning questions right with the candidate − right with K.
- Every candidate version, its facts, its score and its decision is logged to `runs_v3/learn.jsonl`. Every accepted version is saved as `knowledge_vN.json`.

## 6. Test phase

All arms answer the same 50 test questions with the same agent and frozen settings:

| Arm | Knowledge |
|---|---|
| docs | none (baseline) |
| evosql | the frozen, gated, consolidated K |
| ungated | every fact the proposer produced during learning that passed the checks; no gate, no consolidation (ratchet analogue) |
| selfcons | none; majority vote over N samples at temperature 0.7, N = min(5, round(evosql $ per test question incl. amortized learning / docs $ per test question)) |

## 7. Metrics

- Test accuracy per arm, a paired McNemar test against docs, and a bootstrap 95% CI.
- Cost: learning $ and test $; $ per correct test answer (learning amortized over the 50 test questions).
- Knowledge: fact count and tokens, facts by kind, checks failed by reason, skips, and accepted/rejected batches.
- **Twin split:** a test question "has a twin" if its gold SQL filters (in WHERE) on a column that some learning question's gold SQL also filters on. Report test accuracy per arm for twin vs. no-twin questions, to show whether gains come from reusable knowledge or near-repeats.
- Framing: BIRD hints stay hidden, and scores use BIRD gold SQL as-is, questionable annotations included. The README states both.

## 8. Code

- **New:**
  - `split.py`: stratified sample and split.
  - `facts.py`: the `Fact` type, rendering and the checks.
  - `learn.py`: calibration, the learning loop, consolidation.
  - `evaluate.py`: the test arms and v3 analysis.
- **CLI:** `split`, `learn`, `test --arm`, `analyze-v3`.
- **Reused:** `agent.answer` (it accepts any knowledge object with `render()`), `bird` (including the value profile), `llm` (cache, retries, cost), and `analysis.usd`, `mcnemar` and `bootstrap_ci`.
- **Config:** a `v3` section in `configs/base.yaml` (sizes, epochs, batch size, thinking settings, output folders).
- **Tests** (targeted):
  - the checks (SQL detection, grounding, leakage);
  - the stratified split (sizes, difficulty mix, no overlap);
  - the accept rule (a gain below the threshold is rejected; the "fixes a batch question" requirement);
  - consolidation fallback (a lower score keeps K);
  - fact rendering.

  All tests use fake LLMs; no network.

## 9. Success criteria

- One command sequence runs split → learn → test (4 arms) → analyze-v3 within $1, and is resumable and cache-first.
- The report shows test accuracy with CIs for all 4 arms, costs, the knowledge contents and the twin split, with an honest verdict even if EvoSQL does not beat docs.
