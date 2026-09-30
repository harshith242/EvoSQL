# EvoSQL v8: Memory on a Workload Where Questions Recur (Design)

Date: 2026-09-30
Status: approved decisions, before implementation.
Repo: `evosql/` (v7 is tagged `v7` before any v8 change; v7's spec is `2026-09-30-evosql-v7-design.md`)

## 1. Goal

v7 showed two things. Online, on Arcwise-Plat, memory barely helped, because knowledge rarely recurred (221 questions: facts +4 / −3). In a controlled probe where knowledge did recur, memory helped (none 22/30, v7 facts 28/30, examples 30/30).

v8 tests memory where recurrence is natural:

> On a stream of real hospital-database questions whose question types recur, does a per-database memory improve accuracy on later questions over no memory, and which memory form helps more: learned facts or past examples (question + correct SQL)?

## 2. Testbed: EHRSQL 2024 on the MIMIC-IV demo

- **Source:** `glee4810/ehrsql-2024` at commit `f9e1aa02160d39e3f8df52bf5c69c5cf2e472499` (CC-BY-4.0). Questions were collected by polling hospital staff and templatized; the database is the MIMIC-IV clinical demo (100 patients, ODbL), already time-shifted.
- **Files** (in `data/ehrsql/`, pinned by SHA-256 in `data/ehrsql/manifest.json`):
  - `mimic_iv/mimic_iv.sqlite` (37.0 MB), gitignored;
  - `annotated.json` (validation split: 1,163 questions, 931 answerable, 134 templates × 7);
  - `postprocessing.py`: the official scorer's SQL post-processing (time and vital-range placeholders).
- **Stream subset: 119 questions = 17 templates × all 7 of their validation questions.** Candidate templates are those with 7 answerable questions whose post-processed gold SQL runs in under 5 s and returns a non-empty result (128 of 134). Shuffle them with `random.Random(0)` and take the first 17. The chosen question ids are frozen in `data/ehrsql/stream_v8.json`.
- **Current time:** EHRSQL fixes "now" at `2100-12-31 23:59:00`. Gold SQL writes `current_time` and the official scorer replaces it. v8:
  - post-processes gold SQL at load time (official `post_process_sql`);
  - tells the agent the current time and asks it to write that literal, never `current_time` or `'now'` (an extra line appended to the database's value profile, so no agent code changes);
  - post-processes the agent's submitted SQL before scoring, as the official scorer does.
- **No column descriptions** ship with EHRSQL; the value profile has no docs part.

## 3. Stream

One order (seed 0) over the 119 questions. Test, then train, as in v7. Three arms:

| Arm | Memory section |
|---|---|
| **none** | empty |
| **facts** | v7 facts: JEV selection (cutoff 2.75, at most 2, unproven alone), SQL snippets, consolidation every 15 questions |
| **examples** | the 2 earlier stream questions most similar to this one (local embeddings), each with its correct SQL; none before the first revealed question |

- Examples need no learning call: after each question its correct SQL joins the pool (it is already revealed in every arm).
- The facts arm learns only from its own failures, as in v7. The examples arm does not affect the facts arm, and vice versa.

## 4. Proposer: DeepSeek V4 Pro

- Model `deepseek-v4-pro`, thinking on, `reasoning_effort: medium`, JSON output. Used for learning and consolidation.
- Peak prices per 1M tokens (upper bound): cache hit $0.044, cache miss $1.32, output $3.96.
- A 2-call smoke test checks JSON mode with thinking on before the run.

## 5. Report

v7's report, with one arm added: per-stream second-half results, learning curve and costs for **facts vs none** and **examples vs none**. With one stream there is no between-database bootstrap; question-level counts (fixes / regressions) and the learning curve by quarter carry the result, plus a per-template breakdown: accuracy of each arm on a template's first occurrence vs its later occurrences.

## 6. Budget

`runs_v8/spend.json`, cap **$3.0**. Expected: none about $0.25, facts about $0.25, examples about $0.25, proposer and consolidation (Pro) about $1.0, pre-checks about $0.1, JEV about $0.02. Total about $1.9.

## 7. Out of scope

- The Arcwise testbed and the v7 probe (kept under tag `v7`).
- Unanswerable EHRSQL questions (filtered out).
- The 34 test-only templates (a possible later held-out check).
