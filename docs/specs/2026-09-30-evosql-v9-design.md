# EvoSQL v9: Examples Plus a Working-Memory Notes File (Design and Plan)

Date: 2026-09-30
Status: approved decisions; implement, then wait for the user's go-ahead before the paid run.
Repo: `evosql/` (v8 is tagged `v8` before any v9 change; v8's spec is `2026-09-30-evosql-v8-design.md`)

## 1. Goal

v8 showed that on recurring EHRSQL questions, examples (the 2 most similar earlier questions with their correct SQL) beat learned facts by far: second half 0.83 vs 0.56 (none 0.53). Facts failed because a fact holds one rule while a question needs a whole recipe, and because conventions that apply to almost every question were retrieved, not always shown.

v9 asks:

> Does a small, always-present working-memory notes file about the database, written to cover what the examples did not show, add accuracy on top of examples?

Only one new arm runs (`examples + notes`); a notes-only arm is deferred until more credits are available.

## 2. Testbed and old arms

- The v8 stream unchanged: 127 questions on MIMIC-IV (119 from 17 templates, then 8 combination questions), same order, same agent, same current-time note.
- `none`, `facts` and `examples` run exactly as in v8 and **must replay from the v8 caches** (LLM, JEV, embeddings). They run in **replay-only mode**: a cache miss for any of them stops the run with an error instead of making a paid call.

## 3. The notes file

A per-database markdown file, like a CLAUDE.md:

```
Working notes about this database:
## Joins and keys
- ...
## Time and dates
## Values and naming
## Answer shape
## Traps
```

- Five fixed sections; only non-empty sections are shown to the agent.
- One convention per bullet, at most 40 words (the prompt asks for about 25).
- **At most 100 lines in total** (headings included), enforced in code: a batch of edits that would exceed it is rejected, so the proposer has to merge or delete first.
- The agent's prompt for this arm is the examples section followed by the notes file.

## 4. Updating the notes

After the `examples + notes` arm fails on question q (the correct SQL is then revealed):

1. **Proposer** (DeepSeek Flash, thinking high, JSON mode) sees: the schema and value profile, the current notes with numbered bullets, q, the examples that were shown, the agent's SQL and the correct SQL. It is asked what the agent still did not know that the examples did not make clear, as conventions that hold for other questions of this database. It returns edits, usually 1–3, no fixed limit:
   ```json
   {"edits": [{"op": "add", "section": "Answer shape", "text": "...", "evidence": "part of the correct SQL it explains"},
              {"op": "replace", "line": 4, "text": "...", "evidence": "..."},
              {"op": "delete", "line": 7, "evidence": "..."}]}
   ```
   or `{"edits": []}`.
2. **Per-edit validity (free):** known op and section, an existing line number, non-empty text under 40 words, a non-empty evidence field, and no leakage of q (v6's `leaks()`: no answer value that is not in the correct SQL, no copied question wording). Invalid edits are dropped and logged; the rest form the batch.
3. **Size:** a batch that would take the file over 100 lines is rejected ("notes full").
4. **Regression check** on a draft copy with the batch applied:
   - check questions: among earlier questions this arm answered correctly, the one most similar to q (local embeddings) and one random other (seeded by q's id);
   - each is re-answered with the draft notes and the same examples it was originally shown;
   - **pass** if both are still correct: the batch is applied; **fail** if either is wrong: the batch is rejected and the breaking question is logged;
   - with no earlier correct question, the batch is applied as **unchecked**;
   - near the budget cap the check is skipped and the batch is applied as **unchecked (budget)**, as v7's pre-checks were.
5. **Fix check (logged only):** q is re-answered with the draft notes; whether it now succeeds is logged but never required, so the proposer is not pushed to encode q's answer.

## 5. Report (`results_v9/summary.md` and `.html`)

v8's report with the fourth arm, plus:

- **Notes vs examples** (the key comparison): fixes and regressions of `examples + notes` against `examples`, on the second half and the whole stream, and by quarter.
- The new arm in first occurrences, template match and combination questions.
- **Notes updates:** failures, edits proposed / valid / applied, batches rejected (by reason) and unchecked, fix rate.
- **The final notes file**, printed in full.

## 6. Budget

`runs_v9/spend.json`, cap **$1.0**. Old arms $0 (cache). Expected: new arm about $0.2, regression and fix checks about $0.15, notes proposer about $0.15; total about $0.5.

## 7. Implementation plan

1. **Tag `v8`.**
2. **Replay-only mode:** `LLM(..., replay_only=False)` and `Jev(..., replay_only=False)`: on a cache miss with replay_only, raise `ReplayMiss` ("run stopped: an old arm needed a new call"). Tests: a cached call replays; a miss raises and makes no call.
3. **`src/evosql/notes.py`:** `SECTIONS`, `Notes` (bullets as (section, text); `render()` for the agent, `numbered()` for the proposer, `line_count()`), `validate(edit, notes, q, gold)`, `apply(notes, edits)` returning a new Notes, `propose_edits(llm, db, notes, q, shown, agent_sql)` with the JSON prompt. Tests: render hides empty sections; add / replace / delete by line; the 100-line cap; invalid edits dropped; leakage dropped.
4. **Stream:** two agent clients and two `Answers`: a replay-only one for none, facts (and its pre-checks) and examples, and a live one for the new arm and its checks; proposer and JEV for facts replay-only; a live proposer for notes. Per question, after the examples arm: `notes` arm = `answers_live.get(db, q, gold, notes=examples_notes(shown) + "\n\n" + notes.render())`. After reveal, if the notes arm failed: `update_notes(...)` per section 4. Keep, per earlier question, the examples shown and whether the notes arm was right (for the checks). Save the final file to `runs_v9/notes_s0_<db>.md`. Config: runs_v9 / results_v9, `stream.budget_usd: 1.0`, `order_budget_usd: [1.0]`, `stream.notes: {max_lines: 100, max_words: 40}`.
5. **Log contract:** each record adds `"notes_ok"`, `"notes_sql"`, `"notes_lines"` (lines at question time) and `"notes_update"` (null, or `{"edits": [...with "valid" and "reason"], "outcome": "applied" | "rejected: regression" | "rejected: notes full" | "applied unchecked" | "applied unchecked (budget)" | "no valid edits" | "no edits", "checked": [qids], "broke": qid or null, "fixes_source": bool or null, "usage": {"proposer": {...}, "check": {...}}}`); `"turns"` and `"latency_s"` become `[none, facts, examples, notes]`; `"usage"` adds `"notes"`.
6. **Report** as in section 5 (arms generalised by name, not position).
7. **Verify before the paid run:** full test suite; a dry run of the first questions with the live arm disabled, which must replay the v8 records exactly for the three old arms, at $0.
