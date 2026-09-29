# EvoSQL v6: A Text-to-SQL Agent That Builds a Memory of Each Database (Design for Review)

Date: 2026-09-29
Status: draft for external review, before implementation. Revision 2 incorporates the first review.
Repo: `evosql/` (v3, v4 and v5 are tagged; this document is self-contained)

## 1. Goal

A normal Text-to-SQL agent treats every question as if it had never seen the database before. EvoSQL tests one precise claim:

> In an online stream of questions about one database, where the agent receives the correct SQL after each answer, does a per-database memory improve accuracy on later questions compared with the same agent without memory?

This is a claim about online improvement within a database. It is not a claim about broad offline generalization.

The claim is tested honestly:
- the same agent and the same questions for every arm;
- memory built only from earlier questions;
- expert-corrected labels;
- two question orders;
- paired statistics;
- a $2 budget for the whole run.

## 2. Background

### 2.1 What earlier versions showed

All numbers are on BIRD dev `thrombosis_prediction`, with `deepseek-flash` as the agent (thinking off). The final set has 59 questions.

| Version | Setup | Result |
|---|---|---|
| v3 | Learn facts on 50 questions with a gated loop, then freeze and test on 50 | Gated facts did worse than no facts (10 vs 12); ungated facts 15 |
| v4 | Single-pass fact discovery; delivery: all facts, retrieved facts, or a search tool | Retrieved facts 15 vs baseline 11 (+4/−0, p = 0.125) |
| v5 | BIRD column descriptions put in the prompt; facts limited to what the docs miss | Baseline rose to **18**; learned facts 17 (+1/−2); question's own hint (ceiling) 26 |

Diagnosis, based on per-question inspection:

1. **The labels were too noisy to learn from.** An annotation-error study measured a 52.8% error rate on BIRD Mini-Dev ([arXiv 2601.08778](https://arxiv.org/abs/2601.08778)); we found 26 more gold-SQL bugs in our database. The agent learned wrong "facts" from wrong labels (e.g. counting lab rows as patients, a wrong albumin range).
2. **The column docs were the real missing knowledge.** They were only reachable through a tool the agent called on 5 of 59 questions. Putting them in the prompt (11 → 18) absorbed most of what learned facts had been adding.
3. **Too little data.** v4's gain of +6.8 points was real in size but not significant at n = 59.
4. **Too many facts injected.** v5 retrieval put about 8.8 facts into each prompt, including irrelevant ones, and its regressions were mostly style flips.
5. **Learn once, then freeze.** The design did not match the idea of an agent that keeps learning as it answers.

### 2.2 Comparison with EvoOntology (arXiv 2609.15779)

EvoOntology evolves a semantic layer (terms, mappings, constraints, evidence) served to a ReAct agent through `browse`/`resolve` tools.

- **Data and setup:** BIRD Mini-Dev (500 questions, 11 databases), split per database into construction and test questions. The ontology is evolved in rounds, with a 70/30 paired validation gate. Scoring is against the official, uncorrected labels.
- **Result for our model:** `DeepSeek-V4-Flash` goes from **33.1% to 39.4% (+6.3)**.
- **Their ablations:** removing the validation gate costs the most (−11.2), and tool-layer evolution contributes more than content alone.

Attributing our shortfall against theirs:

| Factor | Conclusion |
|---|---|
| Low absolute accuracy | **The model**, not our code: their baseline for the same model is 33.1%, ours 30.5% |
| No significant gain | **Sample size**: our v4 effect (+6.8) matched theirs (+6.3), but on 59 questions of one database, versus their multi-database test folds |
| Database choice | thrombosis_prediction is among BIRD's noisiest; noise is concentrated in one database, not averaged over 11 |
| v5 flat result | Our docs-in-prompt baseline absorbs knowledge that their schema and evidence layers supply |
| Missing features | We do no tool-layer or schema evolution and no validated multi-round acceptance. v6 adds an online equivalent of their gate (Step 6) |

Sources: [paper](https://arxiv.org/abs/2609.15779), [code (BIRD benchmark)](https://github.com/ruc-datalab/EvoOntology).

v6 changes course accordingly:
- clean labels;
- docs in every arm;
- a streaming memory;
- very selective retrieval;
- facts judged by their observed effect on later questions;
- a simple memory baseline to beat;
- two orders.

## 3. Testbed

**Arcwise-Plat** is BIRD Mini-Dev with expert corrections to the SQL, the ambiguous questions and hints, and the schema descriptions ([repo](https://github.com/uiuc-kang-lab/text_to_sql_benchmarks), `data/arcwise_plat_full_with_diff.json`). It is the cleanest BIRD variant available, but not an oracle: the project still has open post-release issue reports.

We use the four largest databases, 221 questions in total:

| Database | Questions |
|---|---|
| formula_1 | 66 |
| superhero | 52 |
| card_games | 52 |
| european_football_2 | 51 |

- **Databases:** SQLite files from the BIRD dev download (re-downloaded after confirming URL and size). Column descriptions come from Arcwise's corrected `data/schemas/<db>/database_description/*.csv`.
- **Pinning:** the report records:
  - the Arcwise repository commit;
  - the SHA-256 of the question file;
  - the SHA-256 of each SQLite file and description CSV.

  Upstream corrections made after the pinned commit are not applied during the run. They are listed in the report if known.
- **Score:** execution match against the Arcwise-corrected SQL: the prediction's result set must equal the gold result set.
- **Hints are never shown to the agent.** In real use, a new question arrives without an annotator's hint.

## 4. The stream

Each database is streamed separately, in **two pre-registered random orders (seeds 0 and 1)**. Order decides which lessons come before which questions, so it is part of the treatment, not noise. The memory is reset at the start of each order.

```
for seed in (0, 1):
    for db in databases:
        memory = empty
        for q in shuffled(questions[db], seed):            # position 1..N
            none_ok  = cached_none_answer(q)                # the none arm does not depend on order
            ex_sql   = agent(q, examples(memory, q))
            fx_sql, used = agent(q, facts(memory, q))       # `used` = IDs of the injected facts
            score all three
            reveal gold(q):
                memory.examples.add(q, gold_sql)                          # every question
                memory.credit(used, fx_ok, none_ok)                       # Step 6
                if not fx_ok: memory.facts.learn(q, fx_sql, gold_sql)     # Steps 2-5
```

- **Test, then train:** every question is scored before the memory learns from it.
- **The none arm has no memory**, so its answers are the same in both orders. It runs once.

## 5. Arms

All arms share one agent, tool loop and prompt skeleton. The skeleton is ordered static-first, so the provider's prefix cache serves most tokens:

```
rules | schema | value profile + column descriptions | [memory section] | question
```

| Arm | Memory section |
|---|---|
| **none** (baseline) | empty |
| **examples** (simple memory) | the 3 most similar earlier questions of this database, each with its correct SQL (every earlier question is stored) |
| **facts** (EvoSQL) | at most **2** learned facts, and only those that pass a strict relevance test (Step 7); often none |

The **examples** arm is the practical bar to clear. It learns from every earlier question, while facts learn only from failures. So a facts-vs-examples difference mixes two things: how knowledge is represented, and how much supervision it gets. This is stated as a limitation, not resolved (Section 10).

Every question logs the IDs of the facts or examples that were injected.

## 6. The facts arm, step by step, and why each step should help

### Step 1: Column descriptions in the prompt (all arms)
Each value-profile line ends with the column's description (e.g. `... | creatinine phosphokinase | Normal range: N < 250`).
**Why it helps:** v5 showed the docs hold the thresholds and code meanings that questions depend on. The agent uses them when they are in the prompt, and almost never fetches them through a tool (11 → 18). Putting them in every arm means memory gets credit only for knowledge the docs do not already give.

### Step 2: Learn only from failures
The proposer runs only when the facts arm answered the question wrongly.
**Why it helps:** a failure is direct evidence that knowledge was missing or wrong. It also bounds cost to roughly 40–50% of questions.

### Step 3: Diagnose the misconception
The proposer (`deepseek-flash`, thinking on, effort medium) sees:
- the question;
- the agent's SQL;
- the correct SQL;
- the schema, value profile and column descriptions;
- the current facts.

It writes typed facts, one misconception per fact:
- **Types:** `mapping`, `encoding`, `constraint`, `meaning`, `grain`, `relation`.
- **Each fact carries its applicability conditions:** 1–5 trigger phrases (`applies_to`), which are also used by retrieval.

Its rules:
- state the knowledge, never the SQL fix;
- write only what the docs and profile do not already say;
- make it general enough to help other questions.

**Why it helps:** comparing the wrong and correct SQL isolates the specific gap. A general statement ("a driver's full name is forename plus surname") can transfer to later questions about the same concept, where a copied answer cannot. The gap-only rule keeps the memory small: in v4, 17 of 35 facts only restated the docs.

### Step 4: Free deterministic checks (no LLM)
A fact is dropped if any of these holds:
- it contains SQL;
- it names a column that does not exist;
- a quoted value is not in the data (question wording in quotes is exempt);
- its evidence query fails or returns nothing;
- it only restates a column's documented range (unless it flips the documented direction);
- it leaks the answer: a gold result value, or 5+ words copied from the question.

**Why it helps:** in v3–v5 the invented values, invented columns and memorized answers were caught cheaply by these checks.

**What they cannot do:** they do not prove a fact is true. An evidence query only shows that the named rows exist. Truth and usefulness are judged by Step 6.

### Step 5: Deterministic merge
- Duplicates (same kind, subject and normalised text) are combined, and their source questions are unioned.
- When a phrase maps to two different columns, only the fact supported by more source questions keeps that phrase. On a tie, neither keeps it.
- Every conflict is logged.

**Why it helps:** the memory stays consistent as it grows.

### Step 6: Judge each fact by its effect on later questions, and prune harmful ones
This replaces the earlier "verify on the source question" step, which could pass by chance and dropped facts that were useful but not sufficient alone.

- **Credit rule:** whenever a fact is injected for a later question, compare the facts arm with the none arm on that same question:
  - +1 if facts is right and none is wrong (a fix);
  - −1 if facts is wrong and none is right (a regression);
  - 0 otherwise.

  The credit is recorded for every injected fact (at most 2).
- **Pruning rule (pre-registered):** a fact whose running score reaches **−2** is retired. It is no longer retrieved, but it stays in the log.
- **Timing:** the none answer and the gold are both known only after the question is scored, so pruning affects only later questions. It is test-then-train, with no look-ahead.

**Why it helps:**
- This is an online version of EvoOntology's validation gate, the component their ablation found most important.
- A fact is judged on the questions it actually meets later, not on the question it came from. That is a direct measure of transfer.
- Harmful facts, whether wrong, over-general or distracting, stop being used after a few bad outings.

### Step 7: Retrieve very selectively
Hybrid search ranks facts against the new question: BM25 over trigger phrases and text, plus embedding similarity (local `qwen3-embedding:0.6b`), fused with Reciprocal Rank Fusion.

A fact is **eligible** only if either holds:
- one of its trigger phrases matches the question (keyword match on `applies_to`);
- its embedding similarity is at least 0.6, a stricter threshold than v5's 0.5.

The **top 2** eligible, non-retired facts are injected. No fact type is always included. If nothing is eligible, the memory section is empty.

**Why it helps:**
- v5 injected about 8.8 facts per question, and its regressions were mostly style flips on questions the facts had nothing to do with.
- Grain and relation facts matter only for aggregation and join questions, so they now compete like every other fact.
- A small, precise memory section changes the agent's behaviour only where it should.

### Step 8: Keep learning
Each database's memory grows throughout its stream, and later questions draw on everything learned before them.

**Why it helps:** questions about one database reuse the same tables, codes, conventions and join paths. A lesson learned at position 10 can fix positions 30, 45 and 60. The learning curve (Section 7) tests this: if memory works, the gap over the baseline widens later in the stream.

### Why facts might beat examples, and when they might not
- **Facts can win because:**
  - a fact transfers across questions that look different but share a concept;
  - it carries the reason, not just the SQL;
  - it is short and pruned by its observed effect.
- **Examples can win because:**
  - they need no distillation, so there are no proposer errors;
  - they see every question, not only failures;
  - they are strong when later questions are near-duplicates.

## 7. Evaluation

- **Primary endpoint (pre-registered):** accuracy on the **second half of each database's stream** (position > N/2), **facts vs none**. It is pooled over the four databases and both orders, giving about 220 (order, question) pairs, each paired with the none arm's answer to the same question.
  - **Effect:** the difference in accuracy, with a 95% CI from a bootstrap that resamples questions (clustering the two orders of the same question).
  - **Test:** a paired sign-flip permutation test at the question level.
- **Stratified reporting:** the same numbers per database and per order.
- **Secondary endpoints:**
  - examples vs none;
  - facts vs examples;
  - whole-stream accuracy (this mostly measures the cold start);
  - a learning curve: accuracy per quarter of the stream, per arm and order.
- **Also reported:**
  - cost ($ per correct answer, learning included);
  - latency (p50/p95 API time) and agent turns;
  - injected items per question;
  - memory size over time;
  - facts dropped by each check;
  - retired facts with their credit history;
  - per-fact fixes and regressions;
  - the final facts verbatim;
  - pinned data hashes.
- **Power:** about 220 clustered pairs can detect a gain of roughly 6–8 points. Smaller real effects may not reach significance. The report says so and shows the CIs and the learning curve alongside the p-value.
- **If the budget guard stops the run inside order 1:** only the completed databases are reported, with no primary claim.

## 8. Budget ($2 cap, peak prices, persisted spend guard)

| Item | Estimate |
|---|---|
| none arm, 221 questions, run once | ~$0.27 |
| examples arm, 2 orders × 221 | ~$0.57 |
| facts arm, 2 orders × 221 | ~$0.53 |
| Proposer, ~2 × 90 failures (thinking effort medium) | ~$0.55 |
| **Total** | **~$1.9** |

- **Run order:** order 1 (all arms, all databases) runs before order 2, so a budget stop never leaves order 1 incomplete.
- **Caching:** all LLM replies are cached, so a stopped run resumes and replays cost nothing.

## 9. Risks and mitigations

| Risk | Mitigation |
|---|---|
| Few failures per database (about 20–30), so few facts | Streaming uses every question; the learning curve shows whether the facts help late in the stream |
| Wrong or over-general facts | Checks (Step 4), merge (Step 5), and credit-based pruning on later questions (Step 6); all facts and their credit listed in the report |
| Distraction from injected facts | At most 2 facts, a strict eligibility rule, no always-included types; per-question regressions reported with the injected IDs |
| Order effects | Two pre-registered orders; results stratified by order |
| Credit is noisy with 2 facts sharing one outcome | Small cap; a pruning threshold of −2 rather than −1; credit histories reported |
| The effect is too small to detect | Stated power; CIs and a learning curve alongside the p-value |
| Label residue in Arcwise-Plat | Pinned data; known open issues listed; per-question outputs published for audit |

## 10. Limitations and out of scope

- **Supervision is confounded between facts and examples:** examples learn from every question, facts only from failures. We do not add a failure-only examples arm (budget).
- **Out of scope:**
  - hints of earlier questions as a learning signal (feedback is the correct SQL only);
  - right/wrong-only feedback, or no feedback;
  - other benchmarks;
  - a stronger proposer;
  - tool-layer or schema evolution;
  - tool-based fact search.

## 11. Questions for the reviewer

1. Is the credit rule (a fact scored against the none arm on later questions where it was injected, with retirement at −2) a sound online substitute for a validation gate?
2. Is a top-2 cap, with keyword-or-cosine ≥ 0.6 eligibility, strict enough, or should eligibility also need a score margin over the next candidate?
3. Is pooling two orders with question-clustered inference appropriate for the primary endpoint?
