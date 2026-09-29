# EvoSQL v4 — Discover, Verify, Deliver (Design Spec)

Date: 2026-09-29
Status: approved design, pre-implementation
Replaces the v3 learning gate. Inputs: the v3 results and `EvoSQL v3 Architecture Review.html`.

## 1. Why v4

v3 test results on 50 held-out questions (thinking off, same agent):

| Arm | Correct | vs docs |
|---|---|---|
| docs (no knowledge) | 12 | – |
| evosql (10 gated facts) | 10 | +1 / −3 |
| ungated (47 checked facts) | 15 | +6 / −3 |

- The learning gate kept facts that did worse than no knowledge, and rejected true facts. For example, "normal glucose is below 180" later fixed a test question. Candidates were generated and scored on the same 50 questions, which is optimistic selection (review: critical).
- Facts were accepted in bundles, and a true fact was rejected when its question had a second error.
- The flat fact kinds could not express row grain or join paths, and a vague "Examination.Diagnosis" fact caused a regression.
- Injecting every fact into every prompt caused style flips on unrelated questions. EvoOntology serves knowledge on demand; its static injection lowered BIRD accuracy for 4 of 6 models.

EvoOntology validates candidates on a separate split (70% build / 30% validation, paired, margin τ). v4 adopts that separation.

## 2. Question sets

The 15 pilot questions (the first 15 of the v1/v2 order) are excluded everywhere.

| Set | Questions | Source | Use |
|---|---|---|---|
| Discovery | 43 | v3 learning set minus pilot | Facts are written from these failures (gold SQL visible) |
| Gate | 46 | v3 test set minus pilot | One-shot safety check of each delivery mode |
| Final | 59 | Never used by any run | The only set behind the result claim |

Saved once as `runs_v4/partitions.json`. The docs answers for discovery and gate are already cached from v3.

## 3. Labels

- Corrected BIRD dev gold SQL from the annotation-error study ([repo](https://github.com/uiuc-kang-lab/text_to_sql_benchmarks), file `data/arcwise_plat_sql_only_with_diff.json`, SQL fixes only). It is downloaded once to `data/corrected/`, after the user confirms the URL and size.
- **Primary score:** official BIRD gold. **Sensitivity score:** the corrected gold where it exists, otherwise official.
- A discovery question whose official gold differs from the corrected gold is not used to write facts. The proposer has no "skip" anymore.

## 4. Knowledge objects

```
Fact {id, kind, subject, fact, applies_to: [phrase], probe: SQL | null, source_qids}
kind ∈ mapping | encoding | constraint | meaning | grain | relation
```

- **grain:** what one row means. Example: "One Laboratory row is one test; a patient count needs distinct Patient.ID."
- **relation:** a join path and its cardinality. Example: "Patient 1:N Laboratory via ID."
- **applies_to:** 1–5 short phrases that trigger the fact, e.g. `["normal platelet", "platelet", "PLT"]`.
- **probe:** optional read-only evidence query. It is never shown to the agent.

### Checks (free, before any use)

A fact is dropped, with the reason logged, if any of these fail:
1. the kind is valid, and `applies_to` is non-empty;
2. the fact text contains no SQL (same rule as v3);
3. it is grounded: every `Table.Column` it names exists, and every quoted value occurs in a named column (v3 rule);
4. if there is a probe, it is a single SELECT that runs read-only within 30 s and returns at least one row;
5. no leakage against any question in its batch: a gold-result value, or a 5-word run copied into the fact text or `applies_to`.

### Deterministic merge

- Duplicates (same kind, normalized subject and fact text) are merged, with their `source_qids` unioned.
- Conflicting mappings (the same normalized `applies_to` phrase mapped to different `Table.Column` targets): the fact with more source questions is kept; on a tie, both are dropped. Every conflict is logged.

## 5. Discovery (no gating)

```
failures = discovery questions the docs agent gets wrong, minus known-wrong labels
for batch in chunks(failures, 5):
    facts += proposer(batch, current facts)   # one misconception per fact
facts = merge(checked(facts))
save runs_v4/knowledge.json
```

A single pass with no accept/reject loop, no noise calibration and no LLM consolidation. The proposer is `deepseek-flash` with thinking on, and its prompt stays database-agnostic.

## 6. Delivery modes (arms)

All arms use the same agent (`deepseek-flash`, thinking off), schema, BIRD docs tool and value profile. Only the knowledge delivery differs.

| Arm | Knowledge the agent gets |
|---|---|
| docs | none |
| all | every fact in the system prompt (v3 style, control) |
| retrieve | per question: the top facts from hybrid search on the question (cap 8) plus every grain and relation fact, in the system prompt |
| tool | a one-line manifest of the subjects that have knowledge, plus a tool `search_knowledge(query)` that returns the top 5 facts from hybrid search, each tagged with how it matched. Tool calls count toward the 8-step limit. |

**Hybrid search** (shared by retrieve and tool, so the two arms differ only in who issues the query):
- **Keyword:** BM25 over each fact's `applies_to` phrases, subject and text. Text is lowercased and split into words, and a light suffix strip is applied (`s`, `es`, `ed`, `ing`).
- **Semantic:** cosine similarity between the query embedding and the fact embeddings (`applies_to` + subject + fact). The embeddings come from local Ollama `qwen3-embedding:0.6b`, are free, and are cached on disk by text hash.
- **Fusion:** Reciprocal Rank Fusion, score = 1/(60 + keyword rank) + 1/(60 + semantic rank). The result is one deduplicated list; ties are broken by fact id.
- **Relevance floor:** a fact is eligible only if its BM25 score is above 0 or its cosine is at least `min_cosine` (config, default 0.5). This avoids returning irrelevant facts to fill the list.
- **Output of the tool:** one list, each fact tagged `keyword`, `semantic` or `keyword + semantic`.

## 7. Gate (one-shot)

- **all**, **retrieve** and **tool** each answer the 46 gate questions once. Docs is cached.
- For each mode, count fixes (right where docs was wrong) and regressions (wrong where docs was right) on official gold.
- **Pass:** fixes ≥ regressions and regressions ≤ 3.
- **The EvoSQL headline arm** is the passing mode with the best net (fixes − regressions); ties go to retrieve, then tool, then all. If no mode passes, the report says so and EvoSQL = docs.
- Nothing is changed after the gate. It only chooses the headline arm.

## 8. Final test

- docs, all, retrieve and tool on the 59 final questions.
- **Primary endpoint (preregistered):** EvoSQL headline arm vs docs, official gold, paired two-sided exact McNemar.
- **Secondary:** every mode vs docs, and every comparison re-scored with corrected gold.

## 9. Metrics

- **Accuracy** with a 95% bootstrap CI, fixes and regressions, and McNemar p against docs.
- **Cost:** discovery $ and test $ per arm; $ per correct answer, with discovery amortized over the final questions for knowledge arms.
- **Latency:** p50 and p95 per question, as the sum of API time for the calls that answered it (the API time is stored in the cache, so replays report the original latency). Agent turns per question.
- **Knowledge use:** facts in the prompt per question (all, retrieve), `search_knowledge` calls and facts returned (tool).
- **Knowledge summary:** facts by kind, checks failed by reason, merge conflicts, and the final facts verbatim.

## 10. Budget

- Cap $2 of real spend, priced at peak rates (an upper bound).
- Estimate: discovery ~$0.05; gate 3 × 46 runs ~$0.25; final 4 × 59 runs ~$0.40. Total ~$0.7.

## 11. Out of scope (possible v5)

- Draft-then-correct mode (Tk-Boost style) and a self-consistency baseline, if budget remains.
- MCP server; LLM-based reranking; shrinking the value profile.
- Other databases; learning without gold SQL.

## 12. Success criteria

- One command sequence (`partition → labels → discover → gate → final → analyze`) runs within $2, resumable and cache-first.
- The report gives the primary endpoint with its CI and p-value, every mode's fixes and regressions, official vs corrected scores, cost, latency, and the facts verbatim, with an honest verdict whatever the outcome.
