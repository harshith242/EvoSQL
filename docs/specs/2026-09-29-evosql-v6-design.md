# EvoSQL v6: A Text-to-SQL Agent That Builds a Memory of Each Database (Design for Review)

Date: 2026-09-29
Status: draft for external review, before implementation. Revision 6 incorporates four reviews; the examples arm is dropped for budget.
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
- paired statistics reported per stream, with conservative claims;
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
| Missing features | We do no tool-layer or schema evolution and no validated multi-round acceptance. v6 adds a smaller, gate-like check on past questions before a fact goes live (Step 6), plus online pruning (Step 7). Neither is equivalent to their paired acceptance on a held-out validation split. |

Sources: [paper](https://arxiv.org/abs/2609.15779), [code (BIRD benchmark)](https://github.com/ruc-datalab/EvoOntology).

v6 changes course accordingly:
- clean labels;
- docs in every arm;
- a streaming memory;
- a pre-activation check on past questions;
- very selective, schema-scoped retrieval;
- online pruning of facts that do not help;
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
            fx_sql, used = agent(q, facts(memory, q))       # `used` = IDs of the injected facts (Step 8)
            score both
            reveal gold(q):
                memory.credit(used, fx_ok, none_ok)                       # Step 7: online pruning
                if not fx_ok:
                    candidates = learn(q, fx_sql, gold_sql)               # Steps 2-5
                    memory.facts.activate(precheck(candidates, earlier questions))   # Step 6
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
| **facts** (EvoSQL) | at most **1 unproven** fact, or up to **2** if the second has a positive record; only facts passing the strict, schema-scoped eligibility test (Step 8); often none |

Every question logs the IDs of the facts that were injected.

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

It writes **exactly one fact per failure**, for the most important misconception. A second misconception in the same failure can be learned at its next failure. This caps cost, since checks and pre-checks are charged per fact.
- **Types:** `mapping`, `encoding`, `constraint`, `meaning`, `grain`, `relation`.
- **Each fact carries its applicability conditions:** 1–5 trigger phrases (`applies_to`), which are also used by retrieval. They may reuse the question's own wording.
- **Each fact lists the stored values it relies on** in a structured field, `values: [{table, column, value}]`. Quoted words in the text are not treated as values.
- **Optional evidence query:** it must run and return a result set. For a fact about absence ("there are no X"), the proposer writes a `COUNT(*)` query, which returns a single 0.

Its rules:
- state the knowledge, never the SQL fix;
- write only what the docs and profile do not already say;
- make it general enough to help other questions.

**Why it helps:** comparing the wrong and correct SQL isolates the specific gap. A general statement ("a driver's full name is forename plus surname") can transfer to later questions about the same concept, where a copied answer cannot. The gap-only rule keeps the memory small: in v4, 17 of 35 facts only restated the docs.

### Step 4: Free deterministic checks (no LLM)
A fact is dropped if any of these holds:
- it contains SQL;
- it names a column that does not exist, or names no table or column of the schema at all (a fact must be scoped to part of the schema);
- a value listed in its `values` field does not occur in that table and column (only structured values are checked; quoted text is ignored);
- its evidence query fails to run or returns no result set (`COUNT(*) = 0` is a valid result);
- it only restates a column's documented range (unless it flips the documented direction);
- it leaks the answer:
  - a gold result value, anywhere in the text, trigger phrases or values. **Exception:** a value that is one of the fact's structured `values`, grounded in its declared column, and occurs in at least 2 rows there. That is a reusable code or category (e.g. a status stored as `'DSQ'`), not an entity. Entity IDs, unique values and answer-specific wording are still rejected;
  - or 5+ words copied from the question, checked in the **fact text only**, because trigger phrases are meant to reuse the user's wording.

**Why it helps:** in v3–v5 the invented values, invented columns and memorized answers were caught cheaply by these checks.

**What they cannot do:** they do not prove a fact is true. An evidence query only shows that the named rows exist. Usefulness is checked by Steps 6 and 7.

### Step 5: Deterministic merge
- Duplicates (same kind, subject and normalised text) are combined, and their source questions are unioned.
- When a phrase maps to two different columns, only the fact supported by more source questions keeps that phrase. On a tie, neither keeps it.
- Every conflict is logged.

**Why it helps:** the memory stays consistent as it grows.

### Step 6: Pre-activation check on earlier questions (gate-like)
A new fact does not go live straight away.

- **Find matches:** take up to **2 earlier questions of the same stream** that the fact is eligible for (Step 8 rules). Their gold SQL and the none arm's answers are already known. The source question is not used: passing on it is weak evidence.
- **Re-answer** each of them with **only this fact** injected.
- **Rule:** the fact is **rejected** if it causes any regression (none right, with-fact wrong). Otherwise it activates. Fixes found here count toward its record.
- **No match:** a fact with no eligible earlier question activates as **unproven**, and is treated with extra caution in Steps 7 and 8.

**Why it helps:** this is a paired check against the no-memory answer before any future question is exposed to the fact. It is the closest affordable thing to EvoOntology's acceptance gate. It is weaker, though: it uses at most 2 questions, and they come from the stream's past, not a held-out validation split.

**Cost:** at most 2 agent runs per new fact, with one fact per failure. When an order's budget allocation is nearly used (Section 8), pre-checks are skipped rather than stopping the stream: new facts go live as unproven, and every skip is logged and reported.

### Step 7: Online pruning by observed effect
After each question, every fact that was injected gets credit, compared with the none arm on that same question:
- **+1** if the facts arm is right and none is wrong (a fix);
- **−1** if the facts arm is wrong and none is right (a regression);
- **0** otherwise.

Retirement rules (pre-registered). A retired fact is never retrieved again but stays in the log.
- **A fact that has never reached +1**: retired on its **first regression**.
- **A fact with a positive record** (it has reached +1 at some point): retired when its score falls to **−2**. The perks of a proven fact (sharing the prompt, the semantic path) need a *current* score of at least +1.
- **No effect:** retired after **5 uses with score 0**, so neutral facts stop occupying the slot.

Timing: none's answer and the gold are known only after the question is scored, so pruning affects later questions only (test, then train).

**Why it helps:** it limits damage from facts that slip through Step 6. An unproven fact can harm at most one real question. Because an unproven fact is always alone in the prompt (Step 8), its credit is attributable.

This is **online pruning after use**, not a gate. A proven fact that shares the prompt with another still shares that outcome's credit.

### Step 8: Retrieve very selectively, scoped to the schema
There are two ways a fact can become eligible for a question.

**A. Phrase path (any fact, including unproven):**
1. **Phrase match:** one of its trigger phrases appears in the question as a whole phrase, with word boundaries (e.g. "age" does not match "average").
2. **Genericity:** once at least 8 earlier questions exist in the stream, a trigger phrase that matches more than **25%** of them counts as generic. A generic phrase qualifies only together with a second cue: another non-generic trigger of the same fact, or a word of the fact's table or column *name* in the question (descriptions are too broad for this cue). It is not dropped outright.
3. **Schema scope by kind:**
   - `grain` and `relation` facts also need the question to mention their table or column, by name or by a content word from the column's description;
   - `mapping`, `encoding`, `constraint` and `meaning` facts do not. Their job is to link wording the schema does not contain ("full name") to columns, and Step 4 already requires them to name real columns.

**B. Semantic path (proven facts only, score ≥ +1).** All of these must hold:
- embedding similarity to the question of at least **0.75**;
- a margin of at least **0.05** over the next-best fact;
- the fact's table or column is in the question's schema scope.

This lets a proven fact transfer to new wording ("full name" to "name of the member"). Unproven facts cannot take this path, so their credit stays attributable.

Among eligible, non-retired facts:
- proven facts rank before unproven ones;
- ties are broken by embedding similarity to the question.

Injection:
- **1 unproven fact** at most;
- **a second slot** only for a proven fact;
- nothing if no fact is eligible.

**Why it helps:**
- v5 injected about 8.8 facts per question, and its regressions were mostly style flips on unrelated questions.
- Whole-phrase matching and the two-cue rule for generic phrases stop facts that merely sound related, without making common but useful triggers ("age") unusable.
- Scoping by fact kind keeps mappings usable exactly where they are needed.
- The semantic path gives proven facts the transfer that exact phrases cannot.

### Step 9: Keep learning
Each database's memory grows throughout its stream, and later questions draw on everything learned before them.

**Why it helps:** questions about one database reuse the same tables, codes, conventions and join paths. A lesson learned at position 10 can fix positions 30, 45 and 60. The learning curve (Section 7) tests this: if memory works, the gap over the baseline widens later in the stream.

## 7. Evaluation

The unit of independent evidence is the **stream**: one (database, order) pair, 8 in total.
- **Questions within a stream are not independent:** they share an evolving memory.
- **The two orders of one database are not independent either:** they share the none arm's answers.

The claims are sized accordingly.

- **Primary result (pre-registered):** second-half accuracy (position > N/2), **facts vs none**, reported for **each of the 8 streams**:
  - the difference;
  - its fixes and regressions;
  - its learning curve.

  The headline is the **direction count**: how many of the 8 streams show a positive second-half difference. It comes with the pooled mean difference.
- **Sensitivity analyses:**
  - a bootstrap of the pooled difference that resamples databases, keeping both orders of a database together (they share the none arm);
  - a leave-one-database-out analysis.
- **Injection rate (pre-registered check):** the share of second-half questions with at least one fact injected, per stream. If it is below **10%**, the report states that the facts arm was mostly inert. A null result then means "the memory was rarely used", not "memory does not help".
- **Heuristic statistics, labelled as such:**
  - a question-level paired sign-flip test;
  - a question-clustered bootstrap CI (the two orders of a question form one cluster).

  These ignore sequential dependence within a stream and are **not exact tests**.
- **What the result can and cannot show:** with 8 streams, it can show a consistent late-stream gain. It cannot give a strong frequentist guarantee, or prove that particular facts caused the gain. Per-fact records (Steps 6–7) are descriptive evidence only.
- **Secondary endpoints:**
  - whole-stream accuracy (this mostly measures the cold start);
  - a learning curve per quarter of the stream.
- **Also reported:**
  - cost ($ per correct answer, learning included);
  - latency (p50/p95 of the original API time per answer, also for replayed answers) and agent turns;
  - injected items per question, with their IDs;
  - memory size over time;
  - facts dropped by each check;
  - pre-check results (rejected, activated, unproven);
  - retired facts with the reason and their credit history;
  - the final facts verbatim;
  - pinned data hashes.
- **If the budget guard stops the run inside order 1:** only completed streams are reported, with no primary claim.

## 8. Budget ($2 cap, peak prices, persisted spend guard)

| Item | Estimate |
|---|---|
| none arm, 221 questions, run once (the second order replays it from the LLM cache) | ~$0.27 |
| facts arm, 2 orders × 221 | ~$0.50 |
| Proposer, ~2 × 90 failures, one fact each (thinking effort medium) | ~$0.50 |
| Pre-activation checks, ≤ 2 runs per new fact (≤ 2 × 180 runs; many facts have fewer matches) | ≤ ~$0.45 |
| **Total** | **~$1.7** (a $0.3 margin) |

- **Allocation per order:** order 1 may spend up to **$1.0** (including the none arm), order 2 the rest of the $2 cap. Pre-activation checks are the only optional cost. They are skipped once an order is within $0.10 of its allocation (Step 6), so both orders complete.
- **Run order:** order 1 (all databases) runs before order 2.
- **Caching:** all LLM replies are cached, so a stopped run resumes and replays cost nothing.

## 9. Risks and mitigations

| Risk | Mitigation |
|---|---|
| Few failures per database (about 20–30), so few facts | Streaming uses every question; the learning curve shows whether the facts help late in the stream |
| Wrong or over-general facts | Checks (Step 4), merge (Step 5), a pre-activation check on earlier questions (Step 6), pruning after the first regression for unproven facts (Step 7); all facts and their credit listed in the report |
| Distraction from injected facts | At most 1 unproven fact; whole-phrase matching, the two-cue rule for generic phrases, schema scope for grain/relation facts, and a strict semantic path for proven facts only; per-question regressions reported with the injected IDs |
| Safeguards make the facts arm inert | Scope by fact kind, generic phrases kept with a second cue, a semantic path for proven facts, and the injection-rate check (Section 7) |
| Order effects and few independent streams | Two pre-registered orders; results per stream; conservative claims (Section 7) |
| Credit is shared when 2 facts are injected | Only a proven fact may share the prompt; unproven facts are always alone |
| The effect is too small to detect | Direction count over 8 streams; database-level bootstrap; question-level statistics labelled heuristic |
| Label residue in Arcwise-Plat | Pinned data; known open issues listed; per-question outputs published for audit |

## 10. Limitations and out of scope

- **No example-memory baseline** (storing past questions with their SQL): dropped for budget. v6 shows whether facts help compared with no memory, not whether they beat simpler memory designs.
- **Out of scope:**
  - hints of earlier questions as a learning signal (feedback is the correct SQL only);
  - right/wrong-only feedback, or no feedback;
  - other benchmarks;
  - a stronger proposer;
  - more than two orders (budget);
  - tool-layer or schema evolution;
  - tool-based fact search.

## 11. Resolved review decisions

- **Unmatched new facts go live as one unproven fact.** Their first later recurrence is exactly what an online memory should capture.
- **The safety parameters stay as pre-registered.** The injection-rate check shows whether recall became too low.
