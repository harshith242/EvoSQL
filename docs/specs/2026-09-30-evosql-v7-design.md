# EvoSQL v7: Better Fact Selection, Consolidated Facts and Verified SQL (Design for Review)

Date: 2026-09-30
Status: draft for review, before implementation. The probe question set is created in a separate session (prompt in `docs/prompts/2026-09-30-probe-v7-prompt.md`); this spec only defines its format and how it is used.
Repo: `evosql/` (v3, v4 and v5 are tagged; v6 is tagged before any v7 change)

## 1. Goal

v7 keeps v6's claim and adds one controlled question:

> **Stream:** in an online stream of questions about one database, where the agent receives the correct SQL after each answer, does a fact memory that is **selected by JEV**, **periodically consolidated** and **carries verified SQL** improve accuracy on later questions compared with the same agent without memory?
>
> **Probe:** when questions related to earlier ones do come back, which memory form transfers best: no memory, v6 facts, v7 facts without SQL, v7 facts with SQL, or similar past examples?

The stream answers "does it help on a realistic stream"; the probe answers "which part helps when knowledge recurs", which v6 could not measure because knowledge rarely recurred.

## 2. Background: what v6 showed

v6 order 0 (221 questions, 4 databases; see `results_v6/`):

- **Small effect:** facts fixed 4 questions and broke 1 against no memory.
- **Answer form:** about 29% of facts-arm misses returned the right values in the wrong form (rounding, extra columns, order, type). Memory is not the fix for these, and v7 does not target them.
- **Coverage is the main limit:** of the real misses, only about 4–6 had a relevant earlier fact that was not injected; about 35 had no relevant earlier fact at all.
- **Retrieval noise:** v6's phrase and similarity rules injected facts on 50 questions, and only 21 of those picks were relevant (blind labels). Two v6 "fixes" came from irrelevant facts, i.e. from a changed prompt, not from knowledge.
- **Narrow wording:** facts were often tied to one question's words ("a set's **Korean** version"), so they did not match related questions ("Italian translation").
- **Gold inconsistency:** some gold SQL disagrees across questions (e.g. what counts as "completion"), which caps any memory.

**Offline JEV check** (`../Jev/fact_eval/report.md`): on all 203 order-0 questions with an earlier fact, graded against blind labels, cutoffs fixed before the run:

| Picker | Precision | Recall | Questions with a wrong pick |
|---|---|---|---|
| v6 rules | 42% | 43% | 29 |
| **JEV 0–3 score ≥ 2.75, top 2** | **81%** | **53%** | **6** |

Related work behind the other two changes (details in the brainstorming notes):
- **Consolidation:** Auto-Dreamer (2026), Dynamic Cheatsheet, A-MEM: a periodic pass with a global view generalizes, merges and prunes memory. ACE: apply small itemized edits instead of rewriting the memory, which erodes detail.
- **Verified SQL:** ProSPy (2026) reuses agent-built views; a 2026 context-layer ablation (arXiv 2609.22259) found content, especially SQL rules, drives most of the gain.

## 3. Testbed

Unchanged from v6: Arcwise-Plat (corrected BIRD Mini-Dev), formula_1 (66), superhero (52), card_games (52), european_football_2 (51), pinned by `data/arcwise/manifest.json`. Agent `deepseek-flash`, thinking off.

**One order only (seed 0).** v6 ran two orders to average over order effects; v7 spends its budget on the probe instead. The online result therefore rests on 4 streams (one per database) and is reported as such.

## 4. The stream

```
for db in databases:                                      # seed 0 order
    memory = empty
    for pos, q in enumerate(shuffled(questions[db], 0), 1):
        none_ok = cached_none_answer(q)                   # replays the v6 cache: no API calls
        picked  = jev_select(memory.active(), q)          # Section 6.1
        fx_ok   = agent(q, picked)                        # replays none when nothing is picked
        memory.credit(picked, fx_ok, none_ok)             # unchanged from v6
        if not fx_ok:
            fact = propose(q, fx_sql, gold_sql)           # Section 6.2, JSON mode
            memory.admit(fact) if checks pass             # Sections 6.3, 6.4
        memory.observe(q, none_ok)
        if pos % 15 == 0: memory.consolidate()            # Section 6.5
    memory.consolidate()                                  # end of stream: the frozen memory for the probe
    save facts
```

**The none arm costs nothing.** Its prompt, tools and model must stay byte-identical to v6, so every none answer is a v6 cache hit. v7 must not change `agent.py`'s `SYSTEM` or `TOOLS`, the value profile or the agent profile.

## 5. Arms (stream)

| Arm | Memory section |
|---|---|
| **none** | empty (replayed from v6) |
| **facts-v7** | up to 2 facts chosen by JEV (Section 6.1), each with its SQL snippet if it has one |

## 6. What changes from v6

### 6.1 Selection by JEV

- **Candidates:** every active (non-retired) fact of the stream, at most about 20 per database, all sent in one call.
- **One fan-out call per question** to OpenRouter's Decisions API, model `typesafe/jev-1.13`:
  - `state`: `{database: "<id> (<one-line description>)", question, facts: {id: {rule, learned_from}}}`, where `rule` is the fact's statement and `learned_from` is the question it was learned from;
  - one `score` question per fact, with 4 levels: unrelated / same topic only / partly applies / directly applies "in the same sense as `learned_from`" (the wording tested offline).
- **Pick:** facts scoring **≥ 2.75**, best first, **at most 2**; v6's slot rule stays (at most one unproven fact, and only alone), so a new fact's credit stays attributable. Ties are broken by memory score.
- **Cache:** JEV replies are cached on disk like LLM replies, keyed by the request body, so a resumed run makes the same picks.
- **Failure:** after retries (429 or 5xx), the run stops the way a budget stop does. It never silently falls back to another selector.
- **Deleted:** v6's phrase path, genericity rule, semantic path and their thresholds.

### 6.2 Structured proposer output (DeepSeek JSON mode)

The proposer call sets `response_format: {"type": "json_object"}` (DeepSeek JSON Output). The prompt contains the word "json" and an example object, as the API requires. An empty reply (a known JSON-mode issue) counts as "no fact" and is logged.

The reply is exactly one of:

```json
{"fact": null}
```

```json
{"fact": {
  "kind": "mapping | encoding | constraint | meaning | grain | relation",
  "subject": "Table.Column or term",
  "statement": "prose, no SQL, under 40 words",
  "applies_to": ["1 to 5 short phrases"],
  "values": [{"table": "T", "column": "C", "value": "stored value"}],
  "snippet": {"table": "T", "form": "predicate | expression", "sql": "SQL on T only"},
  "probe": "SELECT ... | null"
}}
```

- `snippet` may be `null`. It is offered for knowledge that is naturally a condition or a derived value, e.g. `{"table": "status", "form": "predicate", "sql": "status.status = 'Finished'"}`, or an expression that converts a stored `M:SS.mmm` time to seconds.
- `statement` maps to the existing `Fact.fact`; the new optional field is `Fact.sql` (the snippet object).
- `values`, `probe` and `applies_to` keep their v6 meaning. `applies_to` is no longer used for matching; it goes into the fact's rendering and the JEV state.

The consolidation call (6.5) uses the same JSON mode and the same fact object.

### 6.3 Snippet checks (free, no LLM)

A snippet is dropped (the fact is kept without it) unless all of these hold:

1. **One table:** `table` is a real table, and every column in `sql` is a qualified or bare column of that table. Joins stay in prose (`relation` facts).
2. **Grounded in the gold:** every column the snippet uses appears in the question's gold SQL (compared by column name, ignoring aliases).
3. **Runs on its own:** a `predicate` must match at least one row (`SELECT COUNT(*) FROM T WHERE <sql>` > 0); an `expression` must return a non-null value for some row (`SELECT <sql> FROM T WHERE (<sql>) IS NOT NULL LIMIT 1`).
4. **No leakage:** no literal from the question text or the answer rows, except stored codes found in 2+ rows (v6's leakage rule).
5. **Read-only and short:** a single expression, no `;`, no subquery, under 300 characters.

The prose `statement` still must not contain SQL (v6's "contains SQL" check applies to the statement only).

**Rendering in the agent prompt:** `- [kind] subject: statement (SQL on T: <sql>)`.

### 6.4 Pre-check with JEV matching

v6 tried a new fact on up to 2 earlier questions it matched by phrase. v7 matches by JEV instead:

1. Take the **8 earlier questions** most similar to the fact (local embeddings of statement + `learned_from`).
2. **One JEV call** scores the fact against those 8 questions (the same 4-level score, one question per earlier question).
3. Re-answer up to **2** questions scoring ≥ 2.75 with only this fact injected. Any regression (none right, with-fact wrong) rejects the fact; fixes count toward its record. No match means it activates unproven, as in v6.

The budget rule for skipping pre-checks is unchanged.

### 6.5 Consolidation

- **When:** after every 15 stream questions of a database, and once at the end of each stream. The end pass produces the frozen memory used by the probe.
- **Input:** all active facts, each with its score, uses, `learned_from` question and that question's gold SQL.
- **Output (JSON mode):** at most 5 edits:

```json
{"edits": [
  {"op": "generalize | merge | condition | drop", "ids": ["f4"], "reason": "short", "fact": {...} }
]}
```

  - `generalize`: one id; `fact` is the widened fact (e.g. "Korean version" becomes "a translation in any language").
  - `merge`: 2+ ids saying the same thing; `fact` replaces them.
  - `condition`: 2+ ids that conflict; `fact` is one rule stating when each case applies.
  - `drop`: `fact` is null; used for facts that are wrong or only restate docs.
- **Gates for each edit:**
  - the new fact passes all admission checks (6.3 and v6's `check()`);
  - a pre-check on up to 2 of the replaced facts' source questions and up to 2 JEV-matched earlier questions (6.4); a regression rejects the edit.
- **Records:** a generalized fact keeps its id and score; a merged or conditioned fact gets a new id and the highest score and uses of the facts it replaces. The replaced facts are marked `retired: "consolidated into fN"`. Every edit, applied or rejected, is logged.
- **Budget:** consolidation is skipped when the pre-check budget rule says no, and the skip is logged.

### 6.6 Unchanged

Test-then-train loop, learning only from facts-arm failures, one fact per failure, v6's `check()` gates, `merge()` of exact duplicates, credit (+1 / −1 / 0 against none), retirement rules, gold-row cache, answer memo, logs.

## 7. Probe: controlled recurrence

The probe measures transfer when knowledge recurs. It runs **after** the v7 stream, on **frozen** memory; nothing is learned during it.

### 7.1 Question set (created in a separate session)

`data/probe/probe_v7.json`, frozen with a SHA-256 in `data/probe/manifest.json` **before the v7 stream runs**, so it cannot be tailored to v7's facts. Each item:

```json
{"id": "p01", "db_id": "formula_1", "level": "paraphrase | same_quirk | new_surface | control",
 "source_qid": 954, "question": "...", "gold_sql": "...", "knowledge": "one line: the non-obvious knowledge the gold SQL relies on"}
```

30 questions: 8 paraphrase, 8 same_quirk, 8 new_surface, 6 control, spread over the 4 databases. `source_qid` is the stream question it relates to (`null` for controls). The user reviews the set before it is frozen.

### 7.2 Arms (all agent settings as in the stream)

| Arm | Memory |
|---|---|
| `none` | empty |
| `v6_facts` | v6 order-0 facts (non-retired at the end), selected by JEV |
| `v7_prose` | v7 frozen facts with `sql` removed, selected by JEV |
| `v7_sql` | v7 frozen facts with `sql`, selected by JEV |
| `examples` | the 2 most similar stream questions of the database (local embeddings), each with its gold SQL |

All three fact arms use the same JEV selection, so they differ only in memory content.

### 7.3 Scoring

Strict BIRD execution match. Per level and arm: accuracy, and fixes / regressions against `none` as raw counts. With 6–8 questions per level, the probe is a controlled check, not a benchmark, and no p-values are reported.

## 8. Report (`results_v7/summary.md`)

v6's report for one order (per-stream second-half results, direction count out of 4, database bootstrap, leave-one-database-out, learning curve, cost), plus:

- **JEV selection:** facts injected per question, cutoff hits, JEV cost;
- **Consolidation log:** edits proposed, applied and rejected, by type and reason;
- **Snippets:** facts with SQL, snippets dropped by which check, uses;
- **Probe table:** level × arm accuracy, with fixes and regressions against `none`.

## 9. Budget

- `runs_v7/spend.json`, cap **$2.0**, one order (`order_budget_usd: [2.0]`), pre-check reserve $0.10.
- Expected: none arm $0 (cache); facts arm about $0.05; proposer about $0.9 (v6 order 0 was about $1.1 in total); consolidation about $0.2; pre-checks about $0.1; JEV about $0.03. Total about $1.3.
- Probe: about 150 agent runs, about $0.15, same spend file.

## 10. Risks

| Risk | Mitigation |
|---|---|
| JSON mode with thinking on may be rejected or return empty content | A 2-question smoke test first; if rejected, keep thinking on and drop JSON mode (v6 parsing), and log it |
| JEV API outage or rate limits | Retries with backoff, disk cache, hard stop instead of silent fallback |
| Consolidation over-generalizes and breaks questions | Each edit passes checks and a pre-check; rejected edits are logged |
| Snippets copy question-specific SQL | One-table, gold-grounded, no question literals, must run on its own |
| One order: order effects unmeasured | Stated in the report; the probe carries the controlled comparison |
| Changing the none prompt by accident loses the free replay | A test asserts the none-arm messages equal v6's for one question |
| The v6 stream is still running | Tag `v6` first; the running process has already loaded its code |

## 11. Out of scope

- Answer-form fixes (rounding, column order, types) and tolerant scoring.
- Cross-database memory.
- Examples in the stream (examples appear only in the probe).
- A placebo arm (dropped by decision).
- Creating the probe questions (separate session).

## 12. Decisions log

- JEV replaces v6's selection rules (offline eval: precision 81% vs 42%).
- SQL snippets are an optional field on a fact, not a separate memory.
- Proposer and consolidation output use DeepSeek JSON mode with the schemas in 6.2 and 6.5.
- One stream order; the budget goes to the probe.
- Probe: 30 questions, 4 levels, 5 arms; memory frozen from v7 order 0; placebo dropped.
