# EvoSQL v5 — Docs First, Learn Only the Gaps (Design Spec)

Date: 2026-09-29
Status: approved. Step 1 result: docs 18, hints 26 on the final set (gap 8 ≥ 4), so discovery runs.
Builds on v4 (tag `v4`, spec `2026-09-29-evosql-v4-design.md`).

## 1. Why v5

v4 on the 59 final questions (official gold): docs 11, retrieve 15 (+4/−0, p = 0.125), and a diagnostic arm with BIRD's hand-written hints 27.

- **The "docs" baseline had no docs.** BIRD's column descriptions hold the exact normal ranges (e.g. "CPK: Normal range: N < 250") for 39 columns. The agent saw them only through `describe_table`, which it called on 5 of 59 questions, and on Laboratory only once. So it guessed medical ranges (CPK > 200) that did not match the gold (CPK ≥ 250).
- **Most v4 facts restated the docs.** 17 of the 35 facts were normal ranges already in the column docs, and one of them was wrong: it gave albumin the total-protein range.
- **Much of the remaining gap is label noise, not knowledge.** Examples: 10 final gold queries count lab rows as patients, precedence bugs such as `OR` without brackets, text-vs-number comparisons. These are fixed in `labels/evosql_fixes.json` (26 reviewed fixes), which feeds the corrected score only.
- **What only learning can add is small.** Recurring conventions that the docs lack:
  - age = current year − birth year (5 final questions);
  - antibody codes stored as `'negative'` and `'0'` where the docs say `-` and `+-` (5 final questions).

## 2. Column docs for the agent and the proposer

Each value-profile line ends with the column's BIRD description, e.g.:

```
- Laboratory.CPK INTEGER, 64% null, range 0 .. 10835, typical 7 .. 308 | creatinine phosphokinase | values: Commonsense evidence:Normal range: N < 250
```

- **Static and cached.** The profile grows from ~1.4k to ~2.4k tokens. It stays static, so the prefix cache serves it.
- **Everyone sees it.** Every arm (docs, hints, knowledge arms) and the proposer see the same profile.
- **Config.** It is controlled by `agents.<profile>.column_docs`. v5 writes to `runs_v5/` and `results_v5/`, with a fresh $2 budget.

## 3. Decision rule (preregistered before the numbers are known)

Step 1 runs `docs` and `hints` on the final set with column docs. Let gap = hints − docs, correct answers on official gold.

- **gap ≥ 4:** run discovery (§4) and the gate and final arms (§5).
- **gap < 4:** stop. The v5 finding is that column docs close the gap and there is no room for learned knowledge on this database. The report says so.

## 4. Discovery (gap-only)

**Proposer changes (single pass, as in v4):**
- It sees the docs-augmented profile.
- A new prompt rule: *do not restate anything the column docs or the value profile already say*. Write only:
  - conventions (how ages, dates and counts are computed);
  - stored codes that differ from the documented symbols;
  - what question phrases mean;
  - row grain and join paths.
- Discovery questions whose corrected gold (study plus our fixes) differs from the official gold are skipped, as in v4, now with our fixes included.

**Proposer examples.** The made-up-shop examples add the two conventions that step 1 showed the docs miss (§3 result: gap 8, about 4–5 learnable):
- boundary inclusivity: "an abnormal Orders.Discount includes the boundary: at most 5 or at least 30, not strictly below or above";
- exact vs partial value match: "a status named in a question matches Orders.Status exactly ('S'), never as a substring".

**New free check, "already in docs":** a `constraint` or `encoding` fact is dropped when every number and quoted value it states already appears in the docs line of a column it names.

**Two knowledge sets from one discovery run:**

| Variant | Facts kept |
|---|---|
| `single` | every fact that passes the checks, merged (v4 behaviour) |
| `verified` | the facts of `single` whose source question now passes when re-answered with only its own facts (the agent in `all` style, with just that question's bundle); the rest are dropped |

- **Cost of `verified`:** it costs one extra agent run per failed discovery question that has facts (~$0.03).
- **Why the whole bundle:** it keeps or drops a question's facts together. Those are usually 1–3 facts written for the same failure.
- **Output:** both sets are saved as `runs_v5/knowledge_single.json` and `runs_v5/knowledge_verified.json`. `discover.jsonl` logs every verification.

**Dropped:** the stronger-proposer variant (`deepseek-v4-pro`, ~$0.37). With at most ~10 questions of headroom, the variants cannot be told apart beyond noise.

## 5. Arms, gate and final

| Arm | Knowledge |
|---|---|
| docs | none (column docs in the prompt) |
| hints | none, plus BIRD's hint for the question (ceiling, diagnostic) |
| retrieve@single | hybrid retrieval over `knowledge_single.json` |
| retrieve@verified | hybrid retrieval over `knowledge_verified.json` |

- **Gate (46 questions, one shot):** the two retrieve arms against docs. Pass rule as in v4: fixes ≥ regressions and regressions ≤ 3. The headline is the passing arm with the best net. Ties go to `single` (the simpler method wins ties). If neither passes, the headline is docs.
- **Final (59 questions):** all four arms.
- **Primary endpoint:** the headline arm vs docs, official gold, exact McNemar.
- **Diagnostic label.** The final set is reused: it was seen in the v4 analysis and the label review. Every v5 result on it is labelled **diagnostic**, and the report says so in its first line.

## 6. Metrics

v4's metrics are unchanged: accuracy with a CI, fixes and regressions, official and corrected p-values, cost, latency, turns, and knowledge use. Two additions:
- the gap closed: (arm − docs) / (hints − docs);
- the facts dropped as "already in docs".

## 7. Budget

A fresh $2 cap in `runs_v5/spend.json`. Estimates:

| Step | Estimate |
|---|---|
| Step 1 | ~$0.13 |
| Discovery (incl. verification) | ~$0.10 |
| Gate: docs + 2 arms | ~$0.20 |
| Final: 2 more arms | ~$0.17 |
| **Total** | **~$0.6** |

## 8. Out of scope

A stronger proposer, the tool and all delivery modes, a second database, relaxed scoring as a reported metric, and learning without gold.
