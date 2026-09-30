Working notes about this database:
## Joins and keys
- Two clinical records belong to the same hospital visit only when their hadm_id match; matching subject_id alone pairs events from different admissions.
- Patient-to-event filters route through hadm_id, and ICU event tables (chartevents, inputevents, outputevents) additionally through stay_id: event.stay_id IN (SELECT stay_id FROM icustays WHERE hadm_id IN ...); never filter an event table's own subject_id column.
- Two records of the same event type compared within one visit are two filtered copies joined on subject_id AND hadm_id, ordered by each copy's own charttime.
- A 'within N months following' relation between a procedure and a later prescription matches on subject_id, not hadm_id, so the pair may span two different hospital visits.
## Time and dates
- A year or period scope binds each record's own charttime, not the admission's admittime, and must be repeated on every filtered copy of an event table.
- A named month inside 'this year' keeps the year-scope equality and adds strftime('%m', col) = 'NN'; that is a component match, not a shifted anchor such as start of month.
- Relative period words map to calendar-year equality against the literal now: 'previous year'/'last year' is datetime(col,'start of year') = datetime(now,'start of year','-1 year').
## Values and naming
- Match clinical concepts through the dictionary for that event type - d_icd_procedures/d_icd_diagnoses.long_title, d_items/d_labitems.label - never hardcode icd_code or itemid literals.
- Group and rank 'most common' answers by the dictionary code (itemid, icd_code), not by label; labels aren't unique, so resolve names only in the outermost query.
- Drug values are pre-normalized lowercase strings; match a named drug by exact equality, not LIKE or case-insensitive patterns that could pull sibling formulations.
## Answer shape
- For 'N most common' answers rank groups by COUNT(*) with DENSE_RANK and keep rank <= N, never LIMIT N, returning the grouped value not its count; ties may add rows beyond N.
- Yes/no questions phrased 'Has/Does/Is there any...' return a single boolean via SELECT COUNT(*)>0, not the matching rows, timestamps or labels themselves.
- 'First'/'last' an item was received means the record(s) at the extreme timestamp: match charttime = (SELECT MIN/MAX charttime ...), never ORDER BY ... LIMIT 1, so ties at that instant all return.
- 'Which/what name' answers return DISTINCT descriptive names, since the same long_title recurs across codes or visits and would otherwise repeat in results.
- Day- or period-bucketed measurements return one row per bucket holding only the aggregated value; the date expression belongs in GROUP BY, not in the SELECT list.
- 'How many patients' counts COUNT(DISTINCT subject_id) over the qualifying rows, so a patient with several matching visits is counted once.
## Traps
- 'After'/'before' between two events means strictly later/earlier charttime via < or >, not <=, so co-timed records in the same visit are excluded.
- Choosing the 'first' (or last) hospital visit or ICU stay excludes ongoing ones: require dischtime IS NOT NULL (or outtime IS NOT NULL) before ORDER BY admittime/intime LIMIT 1.