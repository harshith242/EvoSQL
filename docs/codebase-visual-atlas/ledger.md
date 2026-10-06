# EvoSQL visual atlas: evidence ledger

Every element in an illustration maps to a row here. Line numbers are for commit `01ac02d` plus the atlas.

| # | Visual element | File:symbol (lines) | What the code does | observed / inferred |
|---|---|---|---|---|
| 1 | Question conveyor (one at a time) | src/evosql/stream.py: run_stream (176–238) | Loops over the questions of one database in a fixed seeded order, one record per question | observed |
| 2 | "Answer first" desk | src/evosql/stream.py: run_stream (186–194) | none, facts, examples and examples + notes all answer before anything about q is revealed | observed |
| 3 | Agent's toolbox | src/evosql/agent.py: answer (81), TOOLS (29–35) | Tool loop: describe_table, profile_column, run_sql, then submit one SQL | observed |
| 4 | Column cheat sheet in every prompt | src/evosql/bird.py: value_profile (119) | Profile of every column (common values, ranges, descriptions) in the system prompt of all arms | observed |
| 5 | Correct-SQL envelope opened after answering | src/evosql/bird.py: gold_rows (160), exec_match (154) | Gold result rows; an answer is right when its result set equals the gold rows | observed |
| 6 | "Remember it" after reveal | src/evosql/memory.py: FactMemory.observe (35) | The revealed question joins the history (pool for examples and pre-checks) | observed |
| 7 | Fact writer | src/evosql/proposer.py: propose (61) | After a facts-arm miss, an LLM writes one fact (JSON) from the question, wrong SQL and correct SQL | observed |
| 8 | Fact inspection stamp | src/evosql/facts.py: check (105), check_snippet (120) | Free checks: real columns and values, not already in docs, no leakage; optional SQL snippet verified | observed |
| 9 | Judge picking cards | src/evosql/jev.py: fact_scores (80); src/evosql/memory.py: pick (12) | JEV scores every active fact 0–3 against the question; facts ≥ 2.75, at most 2 (an unproven one only alone) | observed |
| 10 | Bin for harmful facts | src/evosql/memory.py: credit (71) | +1 / −1 against no memory; facts that break answers are retired | observed |
| 11 | Drawer tidy-up every 15 questions | src/evosql/stream.py: consolidation_pass (115), run_stream (231–232); src/evosql/consolidate.py: consolidate (72) | Every 15 questions the memory is generalized / merged / pruned with checked edits | observed |
| 12 | Cabinet of solved questions | src/evosql/search.py: similar (41), examples_notes (50) | The 2 earlier questions most similar to q (local embeddings), each shown with its correct SQL | observed |
| 13 | Notes sheet always pinned | src/evosql/stream.py: notes_text (81–83); src/evosql/notes.py: Notes.render (51) | Examples section followed by the notes file; always in the prompt of that arm | observed |
| 14 | Five-section notes file, max 100 lines | src/evosql/notes.py: SECTIONS, Notes (36–67); configs/base.yaml: stream.notes | Joins and keys, time and dates, values and naming, answer shape, traps; line_count ≤ 100 | observed |
| 15 | Notes editor | src/evosql/notes.py: propose_edits (110), validate (71), apply (95) | After a notes-arm miss, an LLM returns add/replace/delete edits with evidence; invalid or leaking edits dropped | observed |
| 16 | Regression gate (2 old questions) | src/evosql/stream.py: update_notes (128–173) | Draft notes re-answer the most similar and one random earlier question the arm got right; any miss rejects the batch | observed |
| 17 | Size gate | src/evosql/stream.py: update_notes (144) | A batch that pushes the file over max_lines is rejected | observed |
| 18 | Replay-only old arms | src/evosql/llm.py: ReplayMiss (25), LLM.chat (70) | Old arms may only replay cached calls; a cache miss stops the run | observed |
| 19 | MIMIC results (all questions) | results/mimic/v9_summary.md | none 0.535, facts 0.543, examples 0.772, examples + notes 0.890; combination questions 5/5/5/8 of 8 | observed |
| 20 | formula_1 results (all questions) | results/arcwise/v9_formula_1_summary.md | none 0.591, facts 0.621, examples 0.712, examples + notes 0.727 | observed |
| 21 | "Facts fail as a unit" | results/mimic/v8_summary.md, results/mimic/v9_notes.md | Interpretation from comparing what facts vs notes contained | inferred (not drawn as a code fact) |

## Shot list

| Shot | Idea | Anchors (ledger rows) | Metaphor | Xiaohei's action | Takeaway |
|---|---|---|---|---|---|
| 01-answer-then-reveal | The test-then-train stream | 1, 2, 3, 5, 6 | Conveyor of sealed question parcels; answer sheet first, then the envelope with the correct SQL is torn open | Writes the answer, then opens the envelope and drops the parcel into the "remembered" basket | Every question is answered before its correct SQL is seen; memory only comes from earlier questions |
| 02-facts-drawer | How the facts memory works | 7, 8, 9, 10, 11 | Index-card drawer; a judge with a magnifier picks at most 2 cards; a bin for cards that hurt | Writes a single fact card and stamps it before filing | Facts are single rules that a judge must find; often the right card isn't there |
| 03-examples-and-notes | How examples and examples + notes build the prompt | 4, 12, 13, 14 | Cabinet of solved questions; two pinned on the board next to an always-present notes sheet | Pulls the 2 closest solved questions and pins them beside the notes sheet | Examples show the whole recipe; notes add the conventions examples leave out |
| 04-notes-gate | How a notes edit is kept or rejected | 15, 16, 17 | Turnstile gate that only opens if two earlier right answers stay right | Carries a draft notes page through a gate where two old answers are re-checked | A notes edit is kept only if earlier right answers stay right |
| 05-results | What each memory type achieved | 19, 20 | Four stacks of correct answer sheets measured with a tape | Measures the stacks with a tape measure | On recurring questions examples + notes win; facts barely help |
