# EvoSQL v8 results

Online memory on EHRSQL (MIMIC-IV demo): 119 questions from 17 recurring templates, then 8 questions that each combine two templates, with the correct SQL revealed after each answer. Facts (JEV selection, consolidation, SQL snippets, DeepSeek Flash proposer with high thinking) and examples (the 2 most similar earlier questions with their correct SQL) are each compared with no memory.

## Primary: second half of each stream (facts vs none)

| Order | Database | Questions (2nd half) | None | Facts | Diff | Fixes / regressions | Injection rate |
|---|---|---|---|---|---|---|---|
| 0 | mimic_iv | 64 | 0.531 | 0.562 | +0.031 | +2 / -0 | 52% |

- **Direction count:** 1 of 1 streams positive, 0 negative, 0 tied.
- **One database:** question-level counts and the learning curve carry the result.
- **Heuristic, not exact (ignores dependence within a stream):** question-level sign-flip p = 0.492; question-clustered 95% CI +0.000 to +0.078.
- **Injection check:** 0 of 1 streams inert (facts injected on fewer than 10% of second-half questions). Where the arm is inert, a null result means the memory was rarely used, not that memory cannot help.

## Primary: second half of each stream (examples vs none)

| Order | Database | Questions (2nd half) | None | Examples | Diff | Fixes / regressions | Injection rate |
|---|---|---|---|---|---|---|---|
| 0 | mimic_iv | 64 | 0.531 | 0.828 | +0.297 | +22 / -3 | 100% |

- **Direction count:** 1 of 1 streams positive, 0 negative, 0 tied.
- **One database:** question-level counts and the learning curve carry the result.
- **Heuristic, not exact (ignores dependence within a stream):** question-level sign-flip p = 0.000; question-clustered 95% CI +0.156 to +0.422.
- **Injection check:** 0 of 1 streams inert (examples shown on fewer than 10% of second-half questions). Where the arm is inert, a null result means the memory was rarely used, not that memory cannot help.

## Whole stream, learning curve and memory size

| Order | Database | None (all) | Facts (all) | Examples (all) | Quarters none / facts / examples | Active facts at each quarter |
|---|---|---|---|---|---|---|
| 0 | mimic_iv | 0.535 | 0.543 | 0.772 | 0.52/0.48/0.65 · 0.56/0.56/0.78 · 0.53/0.53/0.84 · 0.53/0.59/0.81 | 6 · 13 · 16 · 15 |

## First occurrences

Accuracy on the 17 questions that are the first of their template in the stream.

| Arm | Correct | Accuracy |
|---|---|---|
| none | 9/17 | 0.529 |
| facts | 9/17 | 0.529 |
| examples | 9/17 | 0.529 |

The main results include all questions.

## Examples by template match

| Group | Questions | Fixes | Regressions | None accuracy | Examples accuracy |
|---|---|---|---|---|---|
| same template shown | 88 | 30 | 2 | 0.545 | 0.864 |
| other templates only | 30 | 3 | 1 | 0.467 | 0.533 |
| no examples shown | 1 | 0 | 0 | 1.000 | 1.000 |

## Combination questions

8 questions that each merge two of the templates, asked at the end of the stream.

| Arm | Correct | Fixes vs none | Regressions vs none |
|---|---|---|---|
| none | 5/8 | | |
| facts | 5/8 | +0 | -0 |
| examples | 5/8 | +1 | -1 |

An example from one of the two component templates was shown for 7 of 8.

## JEV selection

- Questions with at least one injected fact: 50 of 127; mean facts injected per question 0.39.
- Fact scores at or above the cutoff 2.75: 71 of 1405.
- JEV cost in the stream: $0.0199.

## Consolidation

- Passes: 9 run, 0 skipped for budget.
- Edits proposed {'generalize': 2, 'merge': 21, 'condition': 4}, applied {'merge': 19, 'generalize': 1, 'condition': 3}, rejected {'generalize': 1, 'merge': 2, 'condition': 1}.
- Rejection reasons: {'unknown column': 2, 'probe returned no rows': 1, "leakage: contains answer value '1'": 1}.
- Applied (order 0, mimic_iv): merge f2, f4, f9, f11, f12 -> f14: All five state the same rule: event-table subject_id does not reliably identify the patient; link via admissions.hadm_id.
- Applied (order 0, mimic_iv): merge f8, f10 -> f15: Both say icd_code is a prefixed code matched to long_title via the code, never a literal.
- Applied (order 0, mimic_iv): merge f3, f13 -> f16: Both describe the same charttime semantics: event times, period filters and after-ordering within one admission.
- Applied (order 0, mimic_iv): merge f14, f20 -> f21: Both state the same rule: in event tables subject_id is not the patient; reach the patient via admissions.hadm_id.
- Applied (order 0, mimic_iv): generalize f18 -> f18: Statement only covered 'last year' while its applies_to covers 'this year' and 'last month'; broaden to calendar-period phrases.
- Applied (order 0, mimic_iv): merge f21, f23 -> f27: f23 (labevents only) restates f21's rule that event subject_id does not identify the patient and events attach via admissions.hadm_id.
- Applied (order 0, mimic_iv): merge f22, f25 -> f28: Both state prescriptions tie to a patient only through admissions.hadm_id, not prescriptions.subject_id.
- Applied (order 0, mimic_iv): merge f6, f33, f38 -> f39: All three state that diagnoses_icd.charttime is a single value per admission, so first/last diagnosis is a whole dated set.
- Applied (order 0, mimic_iv): merge f15, f29 -> f40: Both describe stored icd_code values carrying the 'icd9|' prefix and being resolved via long_title.
- Applied (order 0, mimic_iv): merge f27, f28, f32 -> f41: f28 and f32 restate f27 for prescriptions and labevents; one relation fact covers all event tables.
- ... and 13 more applied edits.

## Snippets

- Snippets by outcome: {'kept': 9, 'snippet matches no row': 1, 'snippet failed: misuse of aggregate: SUM()': 1, "leakage: question literal 'respiratory rate'": 1}.
- Facts with SQL in the final facts files: 12 of 68.
- Injections of a fact with SQL: 9 of 50.

## Cost, latency, turns

- Logical cost (peak prices; a prompt answered once per run is counted once): none $0.137, facts $0.054, examples $0.155, proposer $0.301, pre-check $0.033, consolidation proposer $0.076, consolidation pre-check $0.075, JEV $0.022.
- $ per correct answer: none $0.0020, facts $0.0081 (learning included), examples $0.0016. Real API spend: $0.853 of $3.00.
- Latency (original API time per answer) p50 / p95 s: none 3.7 / 9.8, facts 3.7 / 10.1, examples 3.7 / 8.6.
- Agent turns: none 3.7, facts 3.7, examples 3.3.

## Learning

- Learning events: 58; outcomes: {'dropped: not scoped to the schema': 5, 'pre-check unmatched': 30, 'pre-check rejected': 1, 'pre-check passed': 16, 'dropped: leakage': 3, 'dropped: unknown column': 1, 'dropped: probe returned no rows': 2}.

### Order 0, mimic_iv: 68 facts, retired {'regression while unproven': 1, 'consolidated into f14': 5, 'consolidated into f16': 2, 'consolidated into f39': 3, 'no effect in 5 uses': 3, 'consolidated into f15': 2, 'consolidated into f21': 2, 'consolidated into f40': 2, 'consolidated into f58': 3, 'consolidated into f64': 2, 'consolidated into f27': 2, 'consolidated into f28': 2, 'consolidated into f41': 3, 'consolidated into f47': 2, 'consolidated into f42': 2, 'consolidated into f48': 2, 'consolidated into f59': 2, 'consolidated into f56': 2, 'consolidated into f49': 2, 'consolidated into f57': 2, 'consolidated into f55': 2, 'consolidated into f69': 3, 'consolidated into f66': 2, 'consolidated into f65': 2}

```
f1 score -1 uses 3 RETIRED (regression while unproven) [mapping] diagnoses_icd.icd_code: A condition named in a question matches d_icd_diagnoses.long_title; diagnoses_icd codes are stored prefixed, like 'icd9|3051', so the code must be looked up by title, never guessed.  (applies to: diagnosed with, diarrhea, tobacco use disorder, ICD code, diagnosis)
f2 score +0 uses 1 RETIRED (consolidated into f14) [relation] labevents.subject_id: A patient's labevents are found via admissions.hadm_id; labevents.subject_id does not reliably match the patient, so filter labevents by the subject's hadm_ids from admissions.  (applies to: patient's lab tests, undergone any lab test, lab test this year, labs for patient)
f3 score +0 uses 0 RETIRED (consolidated into f16) [meaning] procedures_icd.charttime: procedures_icd.charttime and labevents.charttime are the actual event times; 'this year' filters and 'followed' orderings compare these, not admissions.admittime.  (applies to: this year, during this year, lab tests that followed, laryngoscopy and other tracheoscopy, procedures performed)
f4 score +0 uses 1 RETIRED (consolidated into f14) [relation] diagnoses_icd.subject_id: A patient's diagnoses are found via admissions.hadm_id; diagnoses_icd.subject_id does not reliably match the patient, so filter diagnoses_icd by the subject's hadm_ids from admissions.  (applies to: diagnosis of patient, first diagnosis, received first, patient's diagnoses, diagnoses in 2100)
f6 score +0 uses 1 RETIRED (consolidated into f39) [grain] diagnoses_icd.charttime: All diagnoses_icd rows for one hadm_id share the same charttime, so the earliest charttime can carry several diagnoses; a patient's first diagnosis is that whole set, not one row.  (applies to: first diagnosis, earliest diagnosis, diagnosis in 2100, diagnoses recorded for an admission)
f7 score +0 uses 5 RETIRED (no effect in 5 uses) [grain] labevents: One labevents row is a single lab test result; each admission of a patient has many such rows, so receiving lab tests means any row exists in the period.  (applies to: received lab tests, has had lab tests since, lab test count, number of lab tests)
f8 score +0 uses 0 RETIRED (consolidated into f15) [mapping] diagnoses_icd.icd_code: diagnoses_icd.icd_code holds codes with a system prefix like 'icd9|'; a diagnosis named in a question matches d_icd_diagnoses.long_title, reached by joining on icd_code, never by comparing the code to the title.  (applies to: diagnosed with, diagnosis, icd_code, external cause, not elsewhere classified)
f9 score +0 uses 0 RETIRED (consolidated into f14) [relation] chartevents.subject_id: A patient's chartevents rows are reached through admissions.hadm_id and icustays.stay_id; chartevents.subject_id does not reliably match the patient it belongs to.  (applies to: patient's systolic blood pressure, patient's vital signs, chartevents measurements for a patient, ICU chart events, daily maximum measurement)
f10 score +0 uses 0 RETIRED (consolidated into f15) [mapping] procedures_icd.icd_code: procedures_icd.icd_code holds prefixed codes such as 'icd9|966'; a procedure named in a question matches d_icd_procedures.long_title via that code, never a guessed literal code string.  (applies to: ultrasonography of superior vena cava, guidance, procedure, patients who had a procedure, surgery, icd code)
f11 score +0 uses 1 RETIRED (consolidated into f14) [relation] prescriptions.subject_id: A patient's prescriptions are reached through admissions.hadm_id; prescriptions.subject_id does not reliably match the patient, so match prescriptions to admissions to get the subject.  (applies to: patients prescribed, also prescribed, same hospital visit, drug orders, prescribed miconazole powder 2%)
f12 score +0 uses 1 RETIRED (consolidated into f14) [relation] procedures_icd.subject_id: procedures_icd.subject_id and labevents.subject_id do not reliably match the patient; a subject's procedures and lab tests are linked by joining each to admissions on hadm_id and matching admissions.subject_id.  (applies to: alcohol detoxification, lab tests after a procedure, patients who had a procedure, most frequent lab tests, same month after procedure)
f13 score +0 uses 0 RETIRED (consolidated into f16) [mapping] labevents.charttime: "After receiving a procedure" means the lab's charttime is later than that procedure's charttime within the same admission; matching on admission alone also counts labs drawn beforehand.  (applies to: after receiving, same hospital visit after, following a procedure, since 1 year ago, most frequent lab tests)
f14 score +0 uses 1 RETIRED (consolidated into f21) [relation] subject_id (event tables): subject_id in labevents, diagnoses_icd, procedures_icd, prescriptions and chartevents does not reliably match the patient; link these events to admissions.hadm_id and use admissions.subject_id (chartevents also joins icustays.stay_id).  (applies to: patient's lab tests, patient's diagnoses, patients prescribed, patients who had a procedure, chartevents for a patient)
f15 score +0 uses 2 RETIRED (consolidated into f40) [mapping] icd_code: diagnoses_icd.icd_code and procedures_icd.icd_code store prefixed codes such as 'icd9|966'; a diagnosis or procedure named in a question matches d_icd_diagnoses or d_icd_procedures long_title via that code, never a guessed literal.  (applies to: diagnosed with, procedure, icd code, surgery, named diagnosis)
f16 score +0 uses 1 RETIRED (consolidated into f58) [meaning] charttime (procedures_icd, labevents): procedures_icd.charttime and labevents.charttime are the actual event times; period filters and 'after/followed' comparisons use them within the same admission, not admissions.admittime.  (applies to: this year, after receiving a procedure, same hospital visit after, lab tests that followed, since 1 year ago)
f17 score +0 uses 0 RETIRED (consolidated into f64) [meaning] admissions.dischtime: admissions.dischtime is null while a hospital encounter is still ongoing, so a patient's first completed encounter is the earliest admissions.admittime among encounters having a discharge time.  (applies to: first hospital encounter, first admission, completed encounter, hospital encounter, discharged)
f18 score +0 uses 5 RETIRED (no effect in 5 uses) [mapping] admissions.admittime: 'Last year' means the previous calendar year, not the trailing 12 months from now; the same calendar-period reading applies to phrases like 'this year' and 'last month'.  (applies to: last year, during the last year, this year, last month)
f19 score +0 uses 0 [grain] icustays: One icustays row is one ICU stay and a patient has several; the last ICU visit is the completed stay with the latest icustays.intime among that patient's admissions.  (applies to: last ICU visit, ICU stay, stayed in the ICU, systolic blood pressure, daily average)
f20 score +0 uses 0 RETIRED (consolidated into f21) [relation] prescriptions.hadm_id: prescriptions.subject_id is not the patient identifier; a prescription reaches its patient only through admissions.hadm_id, so a patient's prescriptions must be paired in time using admissions.subject_id.  (applies to: prescribed to patients, prescribed after, within 2 months after a prescription, same patient prescriptions, citrate dextrose 3% (acd-a) crrt)
f21 score +0 uses 1 RETIRED (consolidated into f27) [relation] subject_id (event tables): In labevents, diagnoses_icd, procedures_icd, prescriptions and chartevents, subject_id does not identify the patient; pair events by admissions.hadm_id and take the patient from admissions.subject_id (chartevents also via icustays.stay_id).  (applies to: patient's lab tests, patient's prescriptions, prescribed after, patients prescribed, same patient prescriptions)
f22 score +0 uses 2 RETIRED (consolidated into f28) [relation] prescriptions.hadm_id: Prescriptions attach to a patient only through admissions: match prescriptions.hadm_id to admissions.hadm_id and read admissions.subject_id; a patient's drug orders span several admissions.  (applies to: prescriptions, donepezil, drugs prescribed after, same patient, prescription follow-up)
f23 score +0 uses 0 RETIRED (consolidated into f27) [relation] labevents.hadm_id: labevents rows cannot be tied to a patient by labevents.subject_id; a patient's lab tests are reached through admissions.hadm_id, matching the admissions rows whose subject_id is that patient.  (applies to: lab test, laboratory test for patient 10029291, patient's labs, since 01/2100, had a lab test)
f24 score +1 uses 5 [mapping] admissions.admission_location: Being in the emergency room during a hospital visit is indicated by admissions.admission_location naming the emergency room; transfers.careunit (e.g. 'emergency department') is not the ER indicator.  (applies to: emergency room, first hospital visit, admitted to the emergency room, ER visit)
f25 score +0 uses 0 RETIRED (consolidated into f28) [relation] prescriptions.hadm_id: Two drug orders belong to the same patient only through admissions: their hadm_id values must resolve to one admissions.subject_id; prescriptions.subject_id alone does not identify the patient.  (applies to: patients given plasmalyte, drugs prescribed afterwards, same patient, top five drugs, same month)
f26 score +0 uses 2 [mapping] outputevents.value: 'Overall outputs' for a patient means the summed outputevents.value of that patient's ICU output records, not a listing of individual measurement rows.  (applies to: overall outputs, total output, outputs on a date, how much output)
f27 score +0 uses 1 RETIRED (consolidated into f41) [relation] subject_id (event tables): In labevents, diagnoses_icd, procedures_icd, prescriptions and chartevents, subject_id does not identify the patient; events belong to a patient through admissions.hadm_id matching that patient's admissions rows (chartevents also via icustays.stay_id).  (applies to: patient's lab tests, patient's prescriptions, lab test, had a lab test, patient's records)
f28 score +0 uses 3 RETIRED (consolidated into f41) [relation] prescriptions.hadm_id: Prescriptions belong to a patient only through admissions: prescriptions.hadm_id resolves to admissions.subject_id; prescriptions.subject_id alone does not identify the patient and a patient's drug orders span several admissions.  (applies to: prescriptions, same patient, drugs prescribed after, prescribed afterwards, top five drugs)
f29 score +0 uses 1 RETIRED (consolidated into f40) [encoding] procedures_icd.icd_code: Every stored icd_code in procedures_icd and diagnoses_icd carries an 'icd9|' prefix and no ICD-10 codes exist, so a procedure or diagnosis named in a question must be resolved to its code via d_icd_procedures or d_icd_diagnoses long_title.  (applies to: extirpation of matter from left lower lobe bronchus, via natural or artificial opening endoscopic, procedure name, diagnosis name, ICD code, most frequent diagnoses)
f30 score +0 uses 3 [meaning] admissions.admittime: admissions.admittime is the hospital admission time of that encounter, so asking when a patient was admitted wants this column's value, not the admission's other attributes.  (applies to: time the patient was admitted, when admitted to the hospital, admission time, admitted in 2100)
f31 score +0 uses 3 RETIRED (consolidated into f47) [mapping] prescriptions.drug: A drug named in a question matches prescriptions.drug as the whole stored lowercase string (e.g. 'lidocaine 5% patch'), not a shortened or partial drug name.  (applies to: lidocaine 5% patch, prescribed drug, drug name, medication)
f32 score +0 uses 0 RETIRED (consolidated into f41) [relation] labevents.hadm_id: A lab test belongs to a patient only through the admission: labevents.hadm_id resolves to admissions.subject_id, so a patient's lab tests are found via that patient's admissions rows, not by labevents.subject_id.  (applies to: lab test performed on a patient, patient's lab tests, labs in a given period, did patient 10007795 have labs)
f33 score +0 uses 0 RETIRED (consolidated into f39) [grain] diagnoses_icd.charttime: Each admission's diagnosis codes all share one diagnoses_icd.charttime, so the diagnosis received last is every distinct title dated at the patient's latest charttime, not one arbitrary row.  (applies to: diagnosis received last, latest diagnosis, most recent diagnosis, last diagnosis since 1 year ago, last diagnosis of a patient)
f34 score +0 uses 0 RETIRED (consolidated into f42) [mapping] d_items.label: A measurement named in a question, like body temperature, matches d_items.label exactly ('temperature celsius') among rows with linksto 'chartevents'; chartevents stores itemid, so an item named in a question must be resolved through d_items.  (applies to: body temperature, temperature celsius, vital sign measurement, chartevents itemid)
f35 score +0 uses 0 RETIRED (consolidated into f48) [mapping] d_icd_procedures.long_title: A procedure named in a question exists only as d_icd_procedures.long_title; procedures_icd.icd_code holds the numeric ICD-9 code with an 'icd9|' prefix, so no alphanumeric ICD-10-PCS code ever matches.  (applies to: performance of cardiac output, continuous, underwent a procedure, procedure name, procedure code, had a procedure performed)
f36 score +0 uses 2 RETIRED (consolidated into f59) [grain] prescriptions.drug: Medication frequency counts prescription rows, so repeat orders of the same drug for a patient each add to its count, including the drug that triggered the search.  (applies to: most commonly prescribed medications, previously prescribed, top prescribed drugs, medications prescribed after)
f37 score +0 uses 0 RETIRED (consolidated into f42) [mapping] d_items.label: The label 'respiratory rate' in d_items corresponds to more than one itemid, so chartevents measurement matching must include every itemid carrying that label rather than a single hardcoded code.  (applies to: respiratory rate, daily respiratory rate, maximum respiratory rate, chartevents measurement, d_items item)
f38 score +0 uses 0 RETIRED (consolidated into f39) [grain] diagnoses_icd.charttime: diagnoses_icd.charttime is one value per admission (one distinct charttime per hadm_id), so a patient's diagnoses arrive as per-admission sets and the first diagnosis since a year is every title at the earliest such charttime, not one row.  (applies to: first diagnosis since a year, diagnosis received for the first time, earliest diagnosis, new diagnosis in a period, diagnoses since 2100)
f39 score +1 uses 5 [grain] diagnoses_icd.charttime: diagnoses_icd.charttime is one value per hadm_id, so an admission's diagnoses form a single dated set; a patient's first or last diagnosis is every title at the earliest or latest such charttime, not one row.  (applies to: first diagnosis, earliest diagnosis, last diagnosis, latest diagnosis, diagnoses since 2100)
f40 score +0 uses 3 RETIRED (consolidated into f48) [encoding] icd_code (diagnoses_icd, procedures_icd): Every diagnoses_icd.icd_code and procedures_icd.icd_code stores an ICD-9 code with an 'icd9|' prefix and no ICD-10 codes exist; a named diagnosis or procedure resolves through d_icd_diagnoses or d_icd_procedures long_title.  (applies to: diagnosed with, procedure, icd code, surgery, named diagnosis)
f41 score +0 uses 3 RETIRED (consolidated into f56) [relation] subject_id (event tables): In labevents, diagnoses_icd, procedures_icd, prescriptions and chartevents, subject_id does not identify the patient; events reach a patient through admissions.hadm_id, or via icustays.stay_id for ICU event tables.  (applies to: patient's lab tests, patient's prescriptions, lab test, prescriptions, patient's records)
f42 score +0 uses 0 RETIRED (consolidated into f49) [mapping] d_items.label: A measurement named in a question matches d_items.label exactly (such as 'temperature celsius' or 'respiratory rate') among linksto 'chartevents' rows; one label may carry several itemids, all of which must match.  (applies to: body temperature, respiratory rate, vital sign measurement, chartevents itemid)
f43 score +0 uses 0 RETIRED (consolidated into f57) [mapping] after: Two diagnoses of one patient are compared by diagnoses_icd.charttime: the later charttime is the one occurring after, and 'the same hospital visit' means both rows share admissions.hadm_id.  (applies to: after being diagnosed, same hospital visit, diagnosed with X after Y, diagnosed in the same visit)
f44 score +0 uses 1 RETIRED (consolidated into f58) [relation] procedures_icd -> labevents: procedures_icd and labevents hold no usable patient id, so a procedure's later labs match at patient level through admissions.hadm_id, using admissions.subject_id, across that patient's admissions.  (applies to: lab tests after a procedure, labs following a procedure, same patient labs and procedures, thoracoscopic decortication of lung follow-up labs, during the same month)
f45 score +0 uses 0 RETIRED (consolidated into f49) [mapping] d_items.label: A question's 'systolic blood pressure' is stored as d_items.label 'arterial blood pressure systolic' with linksto 'chartevents', which gives the itemid used to filter measurements; the short phrase itself never appears.  (applies to: systolic blood pressure, blood pressure, monthly systolic blood pressure, maximum systolic blood pressure)
f46 score +0 uses 0 RETIRED (consolidated into f47) [mapping] prescriptions.drug: An acetaminophen prescription is a prescriptions row whose drug equals the generic name 'acetaminophen' exactly; partial or pattern matching on prescriptions.drug also catches other drug names and over-counts patients.  (applies to: given acetaminophen, acetaminophen prescription, prescribed acetaminophen, drug name in prescriptions)
f47 score +0 uses 5 RETIRED (no effect in 5 uses) [mapping] prescriptions.drug: A drug or medication named in a question matches prescriptions.drug as the whole stored lowercase string exactly (e.g. 'acetaminophen', 'lidocaine 5% patch'), never as a shortened, partial or pattern match.  (applies to: acetaminophen prescription, prescribed drug, drug name, medication, lidocaine 5% patch)
f48 score +0 uses 3 [encoding] icd_code (diagnoses_icd, procedures_icd): diagnoses_icd.icd_code and procedures_icd.icd_code store ICD-9 codes prefixed 'icd9|'; no ICD-10 codes exist, so a named diagnosis or procedure resolves through d_icd_diagnoses or d_icd_procedures.long_title.  (applies to: diagnosed with, procedure, procedure name, icd code, long_title)
f49 score +0 uses 1 RETIRED (consolidated into f55) [mapping] d_items.label: A measurement named in a question matches d_items.label among linksto 'chartevents' rows exactly, and one label may carry several itemids; 'systolic blood pressure' is stored as 'arterial blood pressure systolic'.  (applies to: systolic blood pressure, respiratory rate, body temperature, vital sign measurement, chartevents itemid)
f50 score +0 uses 0 RETIRED (consolidated into f56) [relation] labevents.hadm_id: A patient's lab tests are only those labevents rows whose hadm_id belongs to that patient's admissions; labevents.subject_id is a separate id namespace and does not identify the patient.  (applies to: patient's laboratory test, lab test since, labs for a patient, undergone a laboratory test, test results of patient)
f51 score +0 uses 0 RETIRED (consolidated into f55) [mapping] d_items.label: 'Diastolic blood pressure' is stored in d_items.label as 'arterial blood pressure diastolic' with linksto 'chartevents'; the numeric itemid must be looked up from that label, not assumed.  (applies to: diastolic blood pressure, arterial blood pressure diastolic, blood pressure measurement, daily maximum blood pressure)
f52 score +0 uses 0 RETIRED (consolidated into f59) [mapping] prescriptions.starttime: A medication prescribed after another in the same hospital encounter is a prescriptions row sharing hadm_id with a later prescriptions.starttime; only the order within the encounter matters, not the patient.  (applies to: previously prescribed, prescribed after, same hospital encounter, following medication, since 1 year ago)
f53 score +0 uses 0 RETIRED (consolidated into f57) [grain] diagnoses_icd.charttime: diagnoses_icd.charttime is one timestamp per admission, so diagnoses sharing a charttime belong to the same hospital stay; a diagnosis follows another only from a later, different admission.  (applies to: previous diagnosis, following diagnosis, diagnosed after, same month, diagnosis order)
f54 score +0 uses 0 RETIRED (consolidated into f58) [mapping] same month: 'During the same month' between a procedure and its lab tests means labevents.charttime is later than procedures_icd.charttime while both fall in one calendar month.  (applies to: same month, during the same month, lab tests conducted, after the procedure, procedure month)
f55 score +0 uses 1 [mapping] d_items.label: A vital-sign name in a question matches d_items.label exactly among linksto 'chartevents' rows, and one label may hold several itemids; systolic/diastolic blood pressure are stored as 'arterial blood pressure systolic'/'arterial blood pressure diastolic'.  (applies to: systolic blood pressure, diastolic blood pressure, respiratory rate, vital sign measurement, chartevents itemid)
f56 score +0 uses 3 RETIRED (consolidated into f69) [relation] subject_id (event tables): In labevents, diagnoses_icd, procedures_icd, prescriptions and chartevents, subject_id does not identify the patient; events reach a patient through admissions.hadm_id, or via icustays.stay_id for ICU event tables.  (applies to: patient's lab tests, patient's prescriptions, lab test, patient's records, chartevents for a patient)
f57 score +0 uses 0 RETIRED (consolidated into f66) [mapping] diagnoses_icd (following diagnosis): A diagnosis follows another when its diagnoses_icd.charttime is later; 'the same hospital visit' requires the two rows to share admissions.hadm_id, while an unqualified following does not.  (applies to: diagnosed after, following diagnosis, previous diagnosis)
f58 score +0 uses 1 RETIRED (consolidated into f66) [mapping] charttime (procedure/lab events): Event times and period filters use charttime, not admissions.admittime; 'the same hospital visit' requires a shared admissions.hadm_id, while a same-month or unqualified following only matches the patient.  (applies to: lab tests that followed, same hospital visit, same month, after a procedure, since 1 year ago)
f59 score +0 uses 3 RETIRED (consolidated into f65) [mapping] prescriptions (previously prescribed): Each prescription row counts once toward drug frequency; a later prescription is later prescriptions.starttime, and 'same hospital encounter' requires a shared admissions.hadm_id while an unqualified window matches only the patient.  (applies to: previously prescribed, commonly prescribed medications, prescribed after, same hospital encounter, medications prescribed after)
f60 score +0 uses 0 RETIRED (consolidated into f64) [mapping] admissions (hospital encounter): An encounter still in progress (admissions.dischtime null) does not count; a patient's 'first hospital encounter' is the earliest admissions.admittime among that patient's encounters having a discharge time.  (applies to: first hospital encounter, first admission, first visit, earliest encounter, first stay)
f61 score +0 uses 0 RETIRED (consolidated into f69) [relation] labevents.subject_id: labevents rows reach a patient through admissions.hadm_id, not labevents.subject_id; a patient's lab tests are the labevents rows whose hadm_id belongs to that patient's admissions.  (applies to: patient received lab tests, lab tests since 1 year ago, labs for patient 10018423, patient's lab results, patient had any laboratory test)
f62 score +0 uses 0 RETIRED (consolidated into f69) [relation] procedures_icd.hadm_id: procedures_icd.subject_id and diagnoses_icd.subject_id are not the patient; procedures and diagnoses belong to a patient via admissions rows matched on hadm_id, whose subject_id is the true patient identifier.  (applies to: patients that had previously received, diagnosis after a procedure, same patient, previously received a procedure)
f63 score +0 uses 0 RETIRED (consolidated into f65) [mapping] prescriptions (following a prescription): A prescription following another needs a strictly later prescriptions.starttime; 'the same month' means both starttimes share a calendar month, and a year filter applies to both prescriptions.  (applies to: after they were prescribed, this year, following prescription, prescribed later)
f64 score +0 uses 0 [mapping] admissions (hospital encounter): An encounter still in progress (admissions.dischtime null) does not count; a patient's first hospital encounter is the earliest admissions.admittime among that patient's encounters having a discharge time.  (applies to: first hospital encounter, first admission, first visit, completed encounter, discharged)
f65 score +0 uses 3 [mapping] prescriptions (following a prescription): Each prescription row counts once toward drug frequency; a following prescription has a strictly later prescriptions.starttime, 'same hospital encounter' requires a shared admissions.hadm_id while an unqualified window matches only the patient, and 'same month' means both starttimes share a calendar month.  (applies to: previously prescribed, prescribed after, same hospital encounter, following prescription)
f66 score +0 uses 1 [mapping] charttime (procedure/lab/diagnosis sequences): Event times and period filters use charttime, not admissions.admittime; a following event needs a strictly later charttime, 'the same hospital visit' requires a shared admissions.hadm_id, while a same-month or unqualified window matches only the patient.  (applies to: lab tests that followed, following diagnosis, diagnosed after, same hospital visit, same month)
f67 score +0 uses 0 [mapping] d_icd_diagnoses.long_title: A condition named in a question matches d_icd_diagnoses.long_title exactly, never as a substring, so 'atrial fibrillation' picks only the title spelled that way.  (applies to: atrial fibrillation, diagnosed with, diagnosis name, has a diagnosis of, condition)
f68 score +0 uses 0 [mapping] prescriptions.drug: A drug named in a question matches prescriptions.drug exactly as stored, never as a substring, so 'heparin' means only rows whose drug is stored as 'heparin'.  (applies to: prescribed heparin, having been prescribed, prescription of a drug, most frequent drug, patients prescribed X)
f69 score +0 uses 3 [relation] subject_id (event tables): In labevents, diagnoses_icd, procedures_icd, prescriptions, chartevents, inputevents and outputevents, subject_id is not the patient; events belong to a patient via admissions.hadm_id, or via icustays.stay_id for ICU rows.  (applies to: patient's lab tests, patient's prescriptions, patient had any laboratory test, diagnosis after a procedure, chartevents for a patient)
```

## Pinned data

`glee4810/ehrsql-2024` at commit `f9e1aa02160d39e3f8df52bf5c69c5cf2e472499`. Stream: 127 questions from 17 templates.

```
0984b949a5d8f6d5  data/ehrsql/stream_v8.json
a26a60261d7e3bbf  data/ehrsql/mimic_iv/mimic_iv.sqlite
9d6bd4d6cadb5097  data/ehrsql/annotated.json
f03f9594b400a255  data/ehrsql/postprocessing.py
```
