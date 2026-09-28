# EvoSQL — Design Spec (v1)

Date: 2026-09-28
Status: approved design, pre-implementation

## 1. Goal

A Text2SQL agent that gets better at **one specific database** over time by learning notes from its own mistakes, with a **gate** that only keeps notes that measurably help. We compare it honestly against a naive "keep anything that fixes it" learner and a budget-matched baseline.

Headline result: a learning curve (accuracy vs. questions seen) per arm, plus notes growth and tokens per correct answer.

## 2. Scope

**In v1**
- Per-database knowledge learning in a streaming (prequential) setup.
- Five arms (Section 6).
- Free LLMs only, one pinned cloud provider.

**Not in v1 (possible v2)**
- Harness self-improvement across databases (prompt/tool-strategy evolution).
- GEPA, ACE baselines.
- Tool-based knowledge lookup (EvoOntology `browse`/`resolve`), MCP server.
- Programmatic tool calling, TAG-Bench, Spider 2.0.
- Learning from result-only feedback (no gold SQL).

## 3. Key decisions

| Topic | Decision | Why |
|---|---|---|
| Knowledge transfer | Knowledge is per database, never shared across databases | Schema quirks are database-specific |
| Evaluation style | Prequential: each question is scored *before* the system learns from it | No fixed split needed; no testing on learned questions |
| Dataset | BIRD dev, 3-4 databases with the most questions (~140 each) | Mini-dev has only ~45 per database, too short for a curve |
| BIRD `evidence` hints | Hidden in all main arms | Hints overlap with what learning should discover |
| Feedback signal | Correct/incorrect + gold SQL after each answer | Stands in for an analyst correcting the query; stated openly in README |
| Knowledge delivery | All notes rendered into the system prompt | Simplest; stable prefix; token cost is directly measurable |
| Gate | Targeted replay gate (Section 5) | Per-note decisions, explainable log; ratchet is the same code with regularizers off |
| Models | Free models, one pinned provider (Groq, OpenRouter or Ollama Cloud), OpenAI-compatible API | User constraint; pinned for reproducibility |
| Language / tooling | Python, `uv` | |

## 4. Flow

### 4.1 Setup (per database)

1. Load the database and its questions; drop the `evidence` field.
2. Create 3 fixed shuffled orders (seeds 0, 1, 2). All arms use the same orders, so results are paired per question.
3. Start with empty notes. Arms with docs get BIRD's column-description CSVs.
4. **Noise calibration:** run the docs arm twice on 20 questions; flip rate `p` = share of questions whose correctness changes with nothing changed.

### 4.2 Streaming loop

```
for each question q in order:
    sql      = agent.answer(q, notes)
    correct  = exec_match(sql, q.gold_sql)          # scored before learning
    log(q, sql, correct, tokens, calls, notes_size)

    if learning_arm and not correct:
        edit = proposer.propose(q, sql, q.gold_sql, notes)   # add / modify / delete one note
        if gate.accept(edit, q, notes, seen_questions):
            notes = apply(edit, notes)
        log(edit, decision, reason)

    if learning_arm and step % prune_every == 0:
        notes = prune(notes)

    checkpoint()
```

### 4.3 Example

Question: "How many charter schools are in Fresno County?"
Agent SQL uses `schools.Charter = 'Y'`; gold uses `frpm."Charter School (Y/N)" = 1`. Results differ, so the answer is marked wrong.
Proposer drafts: *"When a question is about charter schools, use `frpm."Charter School (Y/N)" = 1`, not `schools.Charter`."*
Gate replays: the current question is now fixed, one earlier question is also fixed, and nothing breaks. The note is **accepted**.
A broader note, *"always use frpm for school questions"*, fixes this question but breaks two address questions. That note is **rejected**, and the reason is logged.

## 5. Gate

Inputs: candidate edit, current question, current notes, questions seen so far.

```
accept(edit):
    if leakage_check and leaks(edit, q):              reject "leakage"
    if token_check and tokens(edit.note) > 80:        reject "too long"

    replay = [q] + related_seen(q, k=replay_k)        # seen questions sharing tables with q
    before = run(replay, notes)                        # cached where possible
    after  = run(replay, notes + edit)
    if not after[q].correct and edit.kind != delete:  reject "does not fix q"

    net_gain = correct(after) - correct(before)
    need     = 0 if edit.kind == delete else 1 + round(p * len(replay))
    accept if net_gain >= need, else reject "below noise band"
```

- **Leakage check (rule-based):** reject a note that contains any value from the gold result rows, or that shares a 5-word run with the question text. The note must state general knowledge, not the answer.
- **Pruning (every 20 questions):** for each note, re-run the questions it was credited with (its source question plus replay gains) without the note. If accuracy does not drop, delete it.
- **Knowledge cap:** 3,000 tokens total. If a new note would exceed the cap, run pruning first; if still over, reject.

**Ratchet = same class with switches off:** `replay_k = 0`, no leakage check, no token check, no pruning, no cap, `need = 1` (just "fixes q"). We run the leakage checker on the ratchet's notes afterwards only to report its leakage rate.

## 6. Arms

| # | Arm | Docs | Learning | Orders run |
|---|---|---|---|---|
| 1 | Vanilla | no | none | 1 (order-independent) |
| 2 | Docs | yes | none | 1 |
| 3 | Docs + ratchet | yes | ratchet | 3 |
| 4 | **Docs + EvoSQL** | yes | gated | 3 |
| 5 | Docs + self-consistency | yes | none; N samples at temperature 0.7, majority vote over result sets | 1 |

N for arm 5 = round(EvoSQL tokens per question, including learning and replay / docs-arm tokens per question), capped at 7. It is computed after arm 4 runs.

Optional reference: docs arm **with** BIRD hints, 1 order, reported as a ceiling only.

## 7. Components

Repo: `new-techniques/evosql/` (standalone git repo).

| Module | Responsibility |
|---|---|
| `bird.py` | Download BIRD dev; load questions per database; read-only SQLite execution (30 s timeout, row cap); execution-match using BIRD's set-comparison semantics |
| `llm.py` | OpenAI-compatible client, one pinned provider/model per role (agent, proposer); disk cache keyed by (model, messages, params, sample index); backoff on 429; token and call counters |
| `agent.py` | Tool loop with `list_tables`, `describe_table` (+ docs if the arm has them), `profile_column`, `run_sql`, `submit`; native tool calls with strict-JSON fallback; max 8 steps |
| `knowledge.py` | `Note {id, when, text, source_qids, credited_qids, tokens, created_step}`; render to prompt; JSON save/load |
| `learner.py` | Proposer prompt and parsing; `Gate` with switches `replay_k`, `leakage_check`, `token_check`, `prune_every`, `cap`, `noise_p` |
| `stream.py` | Prequential runner; appends one JSONL record per step; resumes from the last record |
| `analysis/` | Learning curves, bootstrap CIs, paired McNemar tests, tokens/calls per correct answer, note-count growth, accept/reject summary |
| `configs/` | One YAML per arm, plus provider/model/database settings |

Outputs: `runs/<arm>/<db>/order<k>.jsonl` and `runs/<arm>/<db>/order<k>.notes.json` (the final notes; each note records the step at which it was created).

## 8. Models and budget

- **Agent** (most calls) and **proposer** (only on failures) are both free models from one provider, chosen after a **20-question smoke test** that checks tool-calling reliability, speed and daily limits.
- Temperature 0 for agent and proposer (the provider may still be nondeterministic, which the noise calibration captures).
- Rough call volume for 4 databases: about 60k LLM calls, most of them from EvoSQL replay. Free-tier daily caps mean the runs take days, so the runner must be resumable and cache-first.
- **Staging:** (1) smoke test, 20 questions; (2) 1 database, 1 order, all arms; (3) full run. Reduce `replay_k` from 5 to 3 if call volume is too high.

## 9. Metrics and statistics

- **Primary:** prequential accuracy curve (rolling and cumulative) per arm; final-third accuracy per arm.
- **Confidence intervals:** bootstrap over questions and orders; paired McNemar between arms on the same questions.
- **Cost:** tokens per correct answer and LLM calls per correct answer (answering + learning, reported separately).
- **Knowledge:** note count and knowledge tokens over time; accepted/rejected edits by reason; ratchet leakage rate.
- **Noise:** calibrated flip rate `p`, reported next to every gain.
- **Framing:** all results are without BIRD hints and are not comparable to the leaderboard; the README states this.

## 10. Error handling

| Case | Handling |
|---|---|
| Rate limit / provider error | Exponential backoff; after repeated failures stop cleanly; resume from checkpoint |
| SQL error or timeout | Error text is returned to the agent as a tool result; a final submitted SQL that errors counts as wrong |
| Agent hits max steps or gives unparsable output | No answer, counted as wrong, logged |
| Proposer output unparsable | Skip learning for that step, log `proposer_error` |
| Provider silently changes the model | Model ID logged on every call; runs with mixed IDs are flagged in analysis |

## 11. Testing

- Unit tests: execution-match comparator (order, duplicates, NULLs, floats), leakage check, gate decisions (with a stub agent returning scripted correctness), knowledge render/save, runner resume.
- A fake LLM client for deterministic tests; no network in the test suite.
- Smoke run: 20 questions end to end on the real provider before any full run.

## 12. Success criteria

- End-to-end run of all 5 arms on at least 1 database, resumable, fully re-analyzable from the cache with zero new calls.
- README with the learning-curve chart, cost table, note-growth chart and an honest verdict, including if EvoSQL does **not** beat the ratchet or self-consistency.
