# EvoSQL

A Text-to-SQL agent that learns from its own mistakes on one database. After each answer it is shown the correct SQL, and it can keep what it learned for later questions. EvoSQL compares four ways of keeping that memory, measured honestly against the same agent without memory.

## Results at a glance

Accuracy on a stream of questions, one database at a time. Each question is answered **before** its correct SQL is revealed, so memory only ever comes from earlier questions.

**MIMIC-IV (EHRSQL), questions that recur by type** — 127 questions: 119 from 17 question templates, then 8 questions that combine two templates.

| Memory | Whole stream | Second half | Combination questions |
|---|---|---|---|
| none | 0.535 | 0.531 | 5/8 |
| facts | 0.543 | 0.562 | 5/8 |
| examples | 0.772 | 0.828 | 5/8 |
| **examples + notes** | **0.890** | **0.953** | **8/8** |

**BIRD (Arcwise-Plat), questions that rarely recur** — formula_1, 66 questions.

| Memory | Whole stream | Second half |
|---|---|---|
| none | 0.591 | 0.515 |
| facts | 0.621 | 0.576 |
| **examples** | **0.712** | **0.697** |
| examples + notes | 0.727 | 0.667 |

On all 4 Arcwise databases (221 questions), facts moved accuracy from 0.679 to 0.683 (+4 fixed / −3 broken).

## How each memory works

- **none**: the agent sees the schema and a short profile of every column (common values, ranges, descriptions). Nothing is remembered.
- **facts**: after a wrong answer, a second model writes one short fact about the database (for example "a driver's full name is forename + surname"). Facts are checked against the data before they are kept. For each new question, a small judge model ([JEV](https://openrouter.ai/docs/guides/community/jev)) picks at most 2 relevant facts. Facts that break answers are retired, and the memory is cleaned up every 15 questions.
- **examples**: the 2 earlier questions most similar to the new one, each with its correct SQL.
- **examples + notes**: the examples, plus a short notes file about the database (like a CLAUDE.md, at most 100 lines), always in the prompt. After a wrong answer, a model edits the notes, writing only what the examples did not show. An edit is kept only if 2 earlier questions the agent had right are still right with it.

All arms use the same agent (DeepSeek Flash, thinking off) and the same questions in the same order.

## What we learned

1. **Facts rarely help when questions don't repeat.** On BIRD, most mistakes needed knowledge that no earlier question had taught (about 35 of 45 real misses in one audit). Facts gave about +0.4%.
2. **Picking facts better is not enough.** Switching fact selection to the JEV judge doubled precision (81% vs 42% of injected facts were relevant) but barely changed accuracy: the right fact usually didn't exist yet.
3. **Examples beat facts, most of all when question types repeat.** On MIMIC, showing 2 similar solved questions raised accuracy from 0.54 to 0.77; almost all of the gain came from questions whose example had the same template (0.55 → 0.86). Even on BIRD formula_1 they helped (0.59 → 0.71), more than facts (0.62).
4. **Facts fail as a unit.** A question needs a whole recipe (joins, time windows, ranking with ties, which columns to return); a fact holds one rule, and a retrieved fact is easy to miss.
5. **A notes file helps where conventions repeat.** Written to cover what examples leave out (shared conventions such as "top N keeps ties", "yes/no questions return COUNT(*)>0"), it added +16 fixed / −1 broken on top of examples on MIMIC and answered all 8 combination questions. On BIRD formula_1, where questions share fewer conventions, it was about even with examples alone (+3 / −2). Final notes: [MIMIC](results/mimic/v9_notes.md) (24 lines), [formula_1](results/arcwise/v9_formula_1_notes.md) (28 lines).

## Caveats

- One question order per database, and one database per setting for the notes arm.
- The notes learn the "house style" of the people who wrote the correct SQL (for example, that "top 3" includes ties). For an assistant on one database that is what you want, but it is convention, not general SQL skill.
- The regression check uses only 2 earlier questions per edit.
- Any change to the prompt shifts the model's answers a little, so a few fixes or regressions in any arm may be luck.

## Cost

Every run is capped and cached; the old arms of a new run replay from cache at no cost.

| Run | Real spend |
|---|---|
| Facts on BIRD, 4 databases (v6) | $1.29 |
| JEV-selected facts on BIRD (v7) | $0.52 |
| Facts and examples on MIMIC (v8) | $0.85 |
| Examples + notes on MIMIC (v9) | $0.31 |
| Examples + notes on BIRD formula_1 | $0.23 |

## Run it

Needs Python 3.13, [uv](https://docs.astral.sh/uv/), [Ollama](https://ollama.com) with `qwen3-embedding:0.6b` (local embeddings), and API keys in `.env`: `DEEPSEEK_API_KEY` and `OPENROUTER_API_KEY` (for JEV).

```bash
uv sync
uv run python scripts/get_ehrsql_data.py      # MIMIC-IV demo + EHRSQL questions (~38 MB), pinned by hash
uv run python scripts/get_arcwise_data.py     # BIRD dev databases + Arcwise-Plat questions, pinned by hash
uv run python -m evosql stream                # MIMIC run (configs/base.yaml)
uv run python -m evosql report                # writes results_v9/summary.md and summary.html
uv run python -m evosql --config configs/arcwise.yaml stream   # BIRD formula_1 run
```

`stream --replay-check` re-runs only the old arms from cache and confirms they match the earlier run exactly, without spending anything.

## Repository

- `src/evosql/`: the agent (`agent.py`), the stream and arms (`stream.py`), facts (`facts.py`, `proposer.py`, `memory.py`, `consolidate.py`, `jev.py`), notes (`notes.py`), data loading (`bird.py`, `ehrsql.py`) and the report (`report.py`).
- `configs/`: `base.yaml` (MIMIC) and `arcwise.yaml` (BIRD formula_1).
- `results/`: the published reports, the final notes file and the log of every notes edit.
- `tests/`: unit tests, no network (`uv run pytest`).
- Earlier versions are kept as git tags (`v3` to `v9`); v3–v5 were offline experiments on one BIRD database.

## Credits

- Questions and data: [EHRSQL 2024](https://github.com/glee4810/ehrsql-2024) (CC-BY-4.0) on the [MIMIC-IV clinical database demo](https://physionet.org/content/mimic-iv-demo/2.2/) (ODbL); [Arcwise-Plat](https://github.com/uiuc-kang-lab/text_to_sql_benchmarks), corrected [BIRD](https://bird-bench.github.io/) Mini-Dev.
- Ideas this builds on: [ACE](https://arxiv.org/abs/2510.04618) and [Dynamic Cheatsheet](https://arxiv.org/abs/2504.07952) (evolving notes), [ReasoningBank](https://arxiv.org/abs/2509.25140) (learning from failures), [storing verified SQL](https://arxiv.org/abs/2608.07213), EvoOntology (arXiv 2609.15779).
- Code: MIT license.
