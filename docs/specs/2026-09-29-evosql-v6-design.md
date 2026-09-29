# EvoSQL v6: A Text-to-SQL Agent That Builds a Memory of Each Database (Design for Review)

Date: 2026-09-29
Status: draft for external review, before implementation
Repo: `evosql/` (v3, v4 and v5 are tagged; this document is self-contained)

## 1. Goal

A normal Text-to-SQL agent treats every question as if it had never seen the database before. EvoSQL tests a simple idea:

> An agent that answers questions about one database, and after each question learns from the correct answer, should build up knowledge of that database (a memory) and answer later questions better than an agent without memory.

The claim is tested honestly:
- the same agent and the same questions for every arm;
- memory only from past questions;
- corrected labels;
- a paired statistical test;
- a budget of $2 for the whole run.

## 2. What earlier versions showed (why v6 changes course)

All numbers are on BIRD dev `thrombosis_prediction`, with `deepseek-flash` as the agent (thinking off). The final set has 59 questions.

| Version | Setup | Result |
|---|---|---|
| v3 | Learn facts on 50 questions with a gated loop, then freeze and test on 50 | Gated facts did worse than no facts (10 vs 12); ungated facts 15 |
| v4 | Single-pass fact discovery; delivery: all facts, retrieved facts, or a search tool | Retrieved facts 15 vs baseline 11 (+4/−0, p = 0.125) |
| v5 | BIRD column descriptions put in the prompt; facts limited to what the docs miss | Baseline rose to **18**; learned facts 17 (+1/−2); question's own hint (ceiling) 26 |

Diagnosis, based on per-question inspection:

1. **The labels were too noisy to learn from.** An annotation-error study measured a 52.8% error rate on BIRD Mini-Dev ([arXiv 2601.08778](https://arxiv.org/abs/2601.08778)); we found 26 more gold-SQL bugs in our database. The agent learned wrong "facts" from wrong labels (e.g. counting lab rows as patients, a wrong albumin range). Scoring against wrong labels also hides real gains: even with each question's own hint, only 26 of 59 matched.
2. **The column docs were the real missing knowledge.** They were available through a tool that the agent almost never called: 5 of 59 questions. Putting them in the prompt (11 → 18) captured most of what learned facts had been adding.
3. **Too little data for the effect size.** 17 usable failures to learn from, about 4–5 test questions where a learnable convention mattered, and ±2–3 questions of noise.
4. **Learn once, then freeze.** The design did not match the idea of an agent that keeps learning as it answers.

v6 fixes each of these in turn: clean labels, docs in every arm, a streaming memory, and a simple memory baseline to beat.

## 3. Testbed

**Arcwise-Plat** ([repo](https://github.com/uiuc-kang-lab/text_to_sql_benchmarks), `data/arcwise_plat_full_with_diff.json`) is BIRD Mini-Dev with every question reviewed by experts. The SQL, the ambiguous questions and hints, and the schema descriptions are all corrected. It is the cleanest version of BIRD available.

We use the four largest databases, 221 questions in total:

| Database | Questions |
|---|---|
| formula_1 | 66 |
| superhero | 52 |
| card_games | 52 |
| european_football_2 | 51 |

- **Databases:** the SQLite files come from the BIRD dev download (to be re-downloaded after confirming URL and size). The column descriptions are Arcwise's corrected `data/schemas/<db>/database_description/*.csv`.
- **Score:** execution match against the Arcwise-corrected SQL: the prediction's result set must equal the gold result set.
- **Hints are never shown to the agent.** In real use, a new question arrives without an annotator's hint.

## 4. The stream

For each database separately, questions arrive one at a time in a fixed random order (seed 0). All arms see the same order.

```
for q in stream(db):                        # position 1..N
    for arm in (none, examples, facts):
        sql = agent(q, prompt(arm, memory[arm][db]))    # memory holds only earlier questions
        score(sql, gold(q))
    reveal gold(q):
        memory[examples][db].add(q, gold_sql)          # every question
        if facts arm was wrong on q:
            memory[facts][db].learn(q, facts_sql, gold_sql)
```

Every question is scored **before** the memory learns from it: a prequential, test-then-train evaluation. Every question therefore serves as a test question and then as a lesson.

## 5. Arms

All three arms share one agent, tool loop and prompt skeleton, ordered static-first so that the provider's prefix cache serves most tokens:

```
rules | schema | value profile + column descriptions | [memory section] | question
```

| Arm | Memory section |
|---|---|
| **none** (baseline) | empty |
| **examples** (simple memory) | the 3 past questions of this database most similar to q, each with its correct SQL |
| **facts** (EvoSQL) | up to 8 learned facts relevant to q, plus every "grain" and "relation" fact |

The **examples** arm is the bar to clear. If simply recalling similar solved questions does as well, distilled facts are not worth the extra machinery.

## 6. The facts arm, step by step, and why each step should help

### Step 1: Column descriptions in the prompt (all arms)
Each value-profile line ends with the column's description, e.g. `Laboratory.CPK ... | creatinine phosphokinase | Normal range: N < 250`.
**Why it helps:** v5 showed the docs hold the thresholds and code meanings that questions depend on. In the prompt, the agent uses them. Behind a tool, it almost never looked (11 → 18 correct). Including them in every arm also ensures memory is credited only for knowledge the docs do not already give.

### Step 2: Learn only from failures
The proposer runs only when the facts arm answered q wrongly.
**Why it helps:** a failure is direct evidence that some knowledge was missing or wrong. Successes need no lesson. It also bounds cost: about 40–50% of questions, not all of them.

### Step 3: Diagnose the misconception
The proposer (`deepseek-flash`, thinking on) sees:
- the question;
- the agent's SQL;
- the correct SQL;
- the schema, value profile and column descriptions;
- the database's current facts.

It writes typed facts, one misconception per fact. The types are `mapping` (what a phrase means in the data), `encoding`, `constraint`, `meaning`, `grain` (what a row is and how to count) and `relation` (join path). Each fact comes with 1–5 trigger phrases and an optional evidence query. Its instructions:
- state the knowledge, never the SQL fix;
- write only what the docs and profile do not already say;
- make it general enough to help other questions.

**Why it helps:**
- Comparing the wrong and the correct SQL isolates the specific gap: a wrong column, a missed filter value, a counting convention.
- Writing it as a general statement ("a driver's full name is forename plus surname") instead of the answer lets it transfer to later questions about the same concept.
- The gap-only rule keeps the memory small and non-redundant: in v4, 17 of 35 facts only restated the docs.

### Step 4: Free deterministic checks (no LLM, no cost)
A fact is dropped if any of these holds:
- it contains SQL;
- it names a column that does not exist;
- a quoted value is not in the data (question wording in quotes is exempt);
- its evidence query fails or returns nothing;
- it only restates a column's documented range;
- it leaks the answer: a gold result value, or 5+ words copied from the question.

**Why it helps:** in v3–v5 the wrong or hallucinated facts were the ones that caused regressions. These checks catch invented values, invented columns and memorized answers, deterministically.

### Step 5: Verify on the source question
The failed question is re-answered using only its new facts. The facts are kept only if the answer is now correct; otherwise they are discarded.

**Why it helps:**
- It keeps only facts that demonstrably change the agent's behaviour in the right direction. Plausible-sounding facts that do not help are filtered out.
- In v5 this step backfired, because some "correct" answers were label bugs, so verification rewarded facts that reproduced the bugs. With expert-corrected labels, passing verification now means the fact made the answer right.
- Cost is one extra agent run per failure.

### Step 6: Deterministic merge
- Duplicates (same kind, subject and normalised text) are combined, and their source questions are unioned.
- When a phrase maps to two different columns, only the fact supported by more source questions keeps that phrase. On a tie, neither keeps it.
- Every conflict is logged.

**Why it helps:** the memory stays consistent as it grows. Two contradictory facts in the prompt would confuse the agent more than neither.

### Step 7: Retrieve only relevant facts per question
- Hybrid search ranks facts against the new question: BM25 over the trigger phrases and text, plus embedding similarity with local `qwen3-embedding:0.6b`, fused with Reciprocal Rank Fusion. A relevance floor applies.
- The top 8 go into the prompt, plus all grain and relation facts, which apply regardless of wording.

**Why it helps:**
- Injecting every fact caused "style flips" on unrelated questions in v3.
- Retrieval shows the agent only what relates to this question, and keeps the prompt small as the memory grows.
- The grain and relation facts (how rows count, how tables join) are always relevant to aggregation and joins, so they are always included.

### Step 8: Keep learning
The memory for a database grows throughout its stream. Later questions draw on everything learned before them.

**Why it helps:** questions about one database reuse the same concepts: the same tables, codes, naming conventions and join paths. A lesson learned at position 10 can fix positions 30, 45 and 60. The learning curve (Section 7) tests this directly: if memory works, the gap over the baseline should widen over the stream.

### Why facts might beat examples (and when they might not)
- **Facts can win because:**
  - a fact transfers to questions that look different on the surface but share a concept;
  - it carries the reason behind the SQL, not only the SQL;
  - it is short.
- **Examples can win because:**
  - they are exact and need no distillation, so no proposer errors;
  - they work very well when later questions are near-duplicates.

The design reports both against the baseline, and against each other.

## 7. Evaluation

- **Primary endpoint (fixed before running):** accuracy on the second half of each database's stream (position > N/2, 110 questions in total), facts vs none, paired, with an exact McNemar test. By then the memory has seen at least 25 questions.
- **Secondary endpoints:**
  - examples vs none;
  - facts vs examples;
  - whole-stream accuracy;
  - a learning curve: accuracy per quarter of the stream, per arm;
  - per-database results.
- **Also reported:**
  - cost ($ per correct answer, learning cost included);
  - latency (p50/p95 of API time per question) and agent turns;
  - memory size over time;
  - facts dropped by each check;
  - the verification pass rate;
  - the final facts verbatim.
- **Honest power statement:** with about 110 paired questions, the test can detect a gain of roughly 8–10 points. Smaller real effects may show as "not significant". The report says so and shows the learning curve and confidence intervals, not only p-values.

## 8. Budget ($2 cap, peak prices, enforced by a persisted spend guard)

| Item | Estimate |
|---|---|
| 3 arms × 221 questions (about $0.0012 per question per arm, prefix-cache heavy) | ~$0.80 |
| Proposer on ~100 failures of the facts arm (thinking on) | ~$0.45 |
| Verification: one agent run per failure | ~$0.12 |
| **Total** | **~$1.4** |

All LLM replies are cached on disk. A stopped run resumes where it stopped, and replays cost nothing.

## 9. Risks and mitigations

| Risk | Mitigation |
|---|---|
| Few failures per database (about 20–30), so few facts | Streaming uses every question; the learning curve shows whether the facts help late in the stream |
| The proposer writes an over-general or wrong fact | Checks (step 4), verification (step 5) and merge conflicts (step 6); facts listed verbatim in the report for audit |
| Retrieved facts distract on unrelated questions | Relevance floor and cap of 8; regressions vs the baseline reported per question |
| Order effects (one fixed order) | Same order for all arms; a second order is run if the budget allows |
| The effect is too small to detect | Stated power; CIs and a learning curve alongside the p-value |

## 10. Out of scope

- Using past questions' hints as a learning signal: the feedback is the correct SQL only, by design choice.
- Right/wrong-only feedback, or no feedback.
- Other benchmarks and a stronger proposer model.
- Tool-based fact search (the v4 "tool" mode).

## 11. Questions for the reviewer

1. Is second-half accuracy the right primary endpoint for a streaming memory, or should it be whole-stream accuracy?
2. Should the examples arm also add examples only after failures (matched to the facts arm), or store every question, as designed?
3. Is keeping or dropping facts by source-question verification too strict, given that one fact may be necessary but not sufficient?
4. Any concern with a single fixed order per database?
