# Prompt: build the v7 probe question set

Paste everything below the line into a new Claude Code session opened in `new-techniques/evosql/`.

---

You are building a small, hand-checked Text-to-SQL test set for four SQLite databases. The set tests whether knowledge from a past workload of questions transfers to new, related questions, the way a real analyst's questions recur over weeks: some are rewordings, some ask the same kind of thing about a different entity, some need the same non-obvious knowledge in a different form.

## What you may and may not read

**Read only:**
- the databases: `data/bird_dev/<db>/<db>.sqlite` (open read-only: `sqlite3 "file:<path>?mode=ro"`);
- their column descriptions: `data/arcwise/schemas/<db>/database_description/*.csv`;
- the past workload: `data/arcwise/arcwise_plat_full_with_diff.json` (fields `question_id`, `db_id`, `question`, `SQL`), for the databases `formula_1`, `superhero`, `card_games`, `european_football_2` only.

**Do not open** anything under `runs_*`, `results_*`, `cache/`, `src/`, `tests/`, `docs/specs/`, `docs/plans/`, or anything outside `evosql/`. They contain an agent's learned memory, and the test set must not be shaped by it. Make no LLM or other paid API calls; only run SQLite locally.

## Step 1: pick source questions

For each database, read its past questions and gold SQL next to the schema and column descriptions. A good source question is one whose gold SQL relies on **knowledge that is not obvious from the schema and descriptions alone**, for example:
- a stored code or spelling that differs from the question's words (a status value, a publisher name, a language name);
- a storage format (a date or time stored as text, a value stored as a string);
- what a question phrase means in this data ("finished", "full name", "unknown power");
- which table or column holds something when several look plausible;
- row grain (what one row is) or a join path.

Skip a source if its gold SQL looks wrong or disagrees with another past question about the same thing. Use each source for at most 2 probe questions.

## Step 2: write 30 questions

| Level | Count | Definition |
|---|---|---|
| `paraphrase` | 8 | Same meaning as the source, different wording. Its gold SQL must return **exactly the same rows** as the source's gold SQL. |
| `same_quirk` | 8 | Needs the **same non-obvious knowledge** as the source, but asks about a different entity, filter, time range or aggregation. The result must differ from the source's result. |
| `new_surface` | 8 | Needs the same knowledge, but it shows up in a **different surface form** a keyword match would miss: a different language, value, synonym or phrasing of the concept. The result must differ from the source's result. |
| `control` | 6 | Needs **no** non-obvious knowledge beyond the schema and descriptions, and is not close to any past question (different main entity and measure). `source_qid` is null. |

Per database: `formula_1` and `card_games` get 2 of each of the first three levels plus 2 controls (8 each); `superhero` and `european_football_2` get 2 of each of the first three levels plus 1 control (7 each).

Write questions the way a real analyst would type them: plain, sometimes informal, no column names unless a person would naturally use them. Keep the style of the past questions.

## Step 3: gold SQL rules

Each gold SQL must:
- be a single read-only SQLite `SELECT` (CTEs allowed);
- return **at least 1 and at most 1000 rows**, and run in under 10 seconds;
- be **deterministic**: no `CURRENT_TIMESTAMP`, `'now'` or `RANDOM()`; no `LIMIT` that cuts through ties (check the value at the cut; if tied, change the question or include ties);
- select **only what the question asks for, in the order it asks**; no `ROUND` unless the question asks for rounding; keep stored units and types;
- follow the same conventions as its source's gold SQL where they overlap (same output columns for the same kind of request), so a correct answer is unambiguous.

For each item, write `knowledge`: one line naming the non-obvious knowledge the gold SQL relies on (for controls: "none").

## Step 4: validate and save

Write a small validation script in your scratchpad (not in the repo) and run it until every item passes:
1. the JSON matches the format below; ids `p01`..`p30`; level counts and per-database counts as above;
2. every gold SQL runs twice with identical results, returns 1–1000 rows, and takes under 10 s;
3. `paraphrase`: rows equal the source's gold rows (as sets);
4. `same_quirk` and `new_surface`: rows differ from the source's gold rows;
5. no probe question text equals a past question text.

Save:
- `data/probe/probe_v7.json`: a list of
  ```json
  {"id": "p01", "db_id": "formula_1", "level": "paraphrase", "source_qid": 954,
   "question": "...", "gold_sql": "...", "knowledge": "..."}
  ```
- `data/probe/review.md`: one section per item with level, the source question and its gold SQL, the new question, `knowledge`, the new gold SQL, the row count and the first 3 rows. The user reviews this before the set is frozen.

Then stop and ask the user to review `data/probe/review.md`. After they approve (and after any edits they ask for, re-validated), write `data/probe/manifest.json` with the SHA-256 of `probe_v7.json`, the date and the counts per level and database, and commit `data/probe/` locally.
