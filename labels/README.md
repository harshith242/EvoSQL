# Reviewed gold SQL fixes

`evosql_fixes.json` holds reviewed fixes for BIRD dev `thrombosis_prediction`, each with its reason. They are layered over the annotation-error study's corrected labels (arXiv 2601.08778). They feed only the corrected score; the official gold stays the primary score.

A fix is added only when the gold SQL has a real bug that changes the result. The fixes cover:
- counting lab rows where the question asks for patients;
- `OR` without brackets;
- `OR` with a bare literal;
- an unquoted date;
- text-vs-number comparisons;
- a GOT/GPT swap;
- a column that contradicts both its hint and the column docs.

Questions reviewed and left unchanged:

| Question | Why it is not fixed |
|---|---|
| 1161, 1240, 1310 | They average over exam or lab rows, and the question can fairly mean per test. |
| 1167 | "Patients tested each month" can count tests; the hint says `COUNT(ID) / 12`. |
| 1245 | It asks how many examinations, so rows are right. |
| 1171, 1202, 1311 | They count joined rows, but `DISTINCT` gives the same result. |
| 1218 | It computes a percentage over lab rows, but no single per-patient reading exists: 19.84 with female patients who have labs as the denominator, 4.89 with all female patients. |
| 1243, 1282 | The denominator (1243) or tie-breaking in a top 3 (1282) is ambiguous. |
