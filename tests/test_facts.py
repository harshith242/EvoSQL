import pytest

from conftest import make_db
from evosql.bird import Question
from evosql.facts import Fact, check_fact, check_snippet, leaks, merge, render


@pytest.fixture
def db(tmp_path):
    return make_db(tmp_path, "toy", "CREATE TABLE Laboratory (ID INTEGER, RNP TEXT, UN INTEGER); "
                                    "INSERT INTO Laboratory VALUES (1, 'negative', 29), (2, '0', 40), (3, '16', 12);")


def fact(text, subject="Laboratory.RNP", kind="encoding", applies_to=("normal RNP",), probe=None, qids=(1,), id="f1",
         values=()):
    return Fact(id, kind, subject, text, list(applies_to), probe, list(qids), list(values))


def value(v, column="RNP"):
    return {"table": "Laboratory", "column": column, "value": v}


def test_sql_is_rejected_but_ordinary_english_passes(db):
    assert check_fact(fact("Use WHERE RNP IN ('0') for normal Laboratory.RNP."), db) == "contains SQL"
    assert check_fact(fact("Uses count(ID) per patient in Laboratory.RNP."), db) == "contains SQL"
    assert check_fact(fact("Normal results come from two codes in Laboratory.RNP."), db) is None


def test_only_structured_values_are_grounded_and_facts_must_name_the_schema(db):
    assert check_fact(fact("Normal is a 'negative' code.", values=[value("negative")]), db) is None
    assert check_fact(fact("Normal is a code.", values=[value("neg")]), db) == "value not in data: 'neg'"
    assert check_fact(fact("A 'normal' result is a code in Laboratory.RNP."), db) is None  # quoted prose is not a value
    assert check_fact(fact("Normal is 'negative'.", subject="Laboratory.RNPX"), db) == "unknown column"
    unscoped = fact("Averages are over rows.", subject="averages", kind="meaning")
    assert check_fact(unscoped, db) == "not scoped to the schema"


def test_fact_needs_a_trigger_phrase_and_a_probe_with_a_result(db):
    ok = "Normal Laboratory.RNP is 'negative'."
    assert check_fact(fact(ok, applies_to=[]), db) == "no applies_to phrase"
    assert check_fact(fact(ok, probe="SELECT 1 FROM Laboratory WHERE RNP = 'negative'"), db) is None
    assert check_fact(fact(ok, probe="SELECT COUNT(*) FROM Laboratory WHERE RNP = 'x'"), db) is None  # absence: count 0
    assert check_fact(fact(ok, probe="SELECT 1 FROM Laboratory WHERE RNP = 'neg'"), db) == "probe returned no rows"
    assert check_fact(fact(ok, probe="SELECT nope FROM Laboratory"), db).startswith("probe failed")
    assert check_fact(fact(ok, probe="DELETE FROM Laboratory"), db) == "probe is not a SELECT"
    assert check_fact(fact(ok, probe="SELECT 1; DELETE FROM Laboratory"), db).startswith("probe failed")


def test_facts_that_only_restate_the_column_docs_are_dropped(db):
    note = lambda values: {"un": {"name": "UN", "description": "urea nitrogen", "values": values}}
    db.notes = {"Laboratory": note("Commonsense evidence:Normal range: N < 30")}
    restated = fact("A normal Laboratory.UN is below 30.", "Laboratory.UN", "constraint")
    assert check_fact(restated, db) == "already in docs"
    boundary = fact("An abnormal Laboratory.UN includes the boundary: 30 or more.", "Laboratory.UN", "constraint")
    new_range = fact("A dangerous Laboratory.UN is above 40.", "Laboratory.UN", "constraint")
    assert check_fact(boundary, db) is None and check_fact(new_range, db) is None
    # Docs with the direction inverted (as BIRD's uric acid docs are): a fact that corrects them is kept.
    db.notes = {"Laboratory": note("Normal range: N > 30")}
    assert check_fact(restated, db) is None


def test_answer_values_and_copied_wording_leak(db):
    q = "How many patients have a normal anti-ribonuclear protein level?"
    assert leaks("There are 42 such patients.", q, "SELECT COUNT(*) FROM Laboratory", [(42,)])
    assert leaks("Exactly 7 results are high.", q, "SELECT COUNT(*) FROM Laboratory WHERE UN > 30", [(7,)])
    assert leaks("Patients have a normal anti-ribonuclear protein level when RNP is 0.", q, "SELECT 1", [])
    assert leaks("normal anti-ribonuclear protein level", q, "SELECT 1", [], wording=False) is None
    assert leaks("Stored as 'neg'.", "q", "SELECT RNP FROM Laboratory", [("neg",)], allowed={"neg"}) is None


def test_merge_unites_duplicates_and_resolves_mapping_conflicts(db):
    same = [fact("Normal is 'negative'.", qids=[1], id="f1"),
            fact("normal is 'negative'", applies_to=["RNP"], qids=[2], id="f2")]
    merged, _ = merge(same, db)
    assert len(merged) == 1 and merged[0].source_qids == [1, 2] and merged[0].applies_to == ["normal RNP", "RNP"]
    # Texts that differ only in a symbolic stored value are different facts, not duplicates.
    plus, minus = fact("Positive is stored as '+'.", id="f1"), fact("Positive is stored as '-'.", qids=[2], id="f2")
    assert len(merge([plus, minus], db)[0]) == 2
    # "urea" mapped to two different columns: the better-supported mapping wins.
    rnp = fact("Urea means Laboratory.RNP.", kind="mapping", applies_to=["urea"], qids=[1], id="f1")
    un = fact("Urea means Laboratory.UN.", "Laboratory.UN", "mapping", ["Urea"], qids=[2, 3], id="f2")
    merged, conflicts = merge([rnp, un], db)
    assert [f.id for f in merged] == ["f2"] and conflicts == [{"phrase": "urea", "facts": ["f1", "f2"], "kept": "f2"}]
    # A tie drops both.
    merged, conflicts = merge([rnp, fact(un.fact, un.subject, "mapping", ["urea"], qids=[5], id="f2")], db)
    assert merged == [] and conflicts[0]["kept"] is None
    # A shared generic phrase is taken from both facts; the facts themselves survive on their specific phrases.
    rnp = fact("Normal Laboratory.RNP is 'negative'.", kind="mapping", applies_to=["normal RNP", "normal"], id="f1")
    un = fact("Normal Laboratory.UN is below 30.", "Laboratory.UN", "mapping", ["normal urea", "Normal"], id="f2")
    merged, conflicts = merge([rnp, un], db)
    assert [f.applies_to for f in merged] == [["normal RNP"], ["normal urea"]] and conflicts[0]["phrase"] == "normal"


def test_render_lists_one_line_per_fact_with_its_snippet():
    plain = fact("Normal is 'negative'.")
    with_sql = Fact("f2", "mapping", "status.status", "Finished means a completed race.", ["finished"], None, [2], [],
                    {"table": "status", "form": "predicate", "sql": "status.status = 'Finished'"})
    assert render([]) == ""
    assert render([plain, with_sql]) == (
        "Learned database knowledge:\n"
        "- [encoding] Laboratory.RNP: Normal is 'negative'.\n"
        "- [mapping] status.status: Finished means a completed race. (SQL on status: status.status = 'Finished')")


@pytest.fixture
def sdb(tmp_path):
    return make_db(tmp_path, "shop", "CREATE TABLE status (statusId INTEGER, status TEXT); "
                                     "CREATE TABLE results (raceId INTEGER, statusId INTEGER, time TEXT); "
                                     "INSERT INTO status VALUES (1, 'Finished'), (2, 'Finished'), (3, 'Accident'); "
                                     "INSERT INTO results VALUES (1, 1, '1:30'), (1, 3, NULL);")


GOLD = "SELECT COUNT(*) FROM results JOIN status ON results.statusId = status.statusId WHERE status.status = 'Finished'"
FINISHED = Question(1, "shop", "How many results have the Finished status?", GOLD)


def snippet(sql, table="status", form="predicate"):
    return {"table": table, "form": form, "sql": sql}


def test_a_grounded_one_table_snippet_that_runs_passes(sdb):
    assert check_snippet(snippet("status.status = 'Finished'"), sdb, FINISHED, [(2,)]) is None
    assert check_snippet(snippet("UPPER(status.status)", form="expression"), sdb, FINISHED, [(2,)]) is None


def test_a_snippet_must_stay_on_one_table_in_the_gold_sql(sdb):
    check = lambda sql: check_snippet(snippet(sql), sdb, FINISHED, [(2,)])
    assert check("results.time IS NOT NULL") == "not one table"
    assert check("status.statusId = results.statusId") == "not one table"
    assert check("time IS NOT NULL") == "not one table"  # a bare column of another table
    q = Question(1, "shop", "How many finished?", "SELECT COUNT(*) FROM status WHERE status = 'Finished'")
    assert check_snippet(snippet("statusId = 1"), sdb, q, [(2,)]) == "not grounded in the gold SQL"


def test_a_question_literal_leaks_unless_it_is_a_code_stored_in_two_rows(sdb):
    q = Question(2, "shop", "How many Finished or Accident results?", GOLD.replace("Finished", "Accident"))
    leak = check_snippet(snippet("status.status = 'Accident'"), sdb, q, [(1,)])
    assert leak == "leakage: question literal 'Accident'"  # stored once; 'Finished' is in 2 rows and passes
    assert check_snippet(snippet("status.status = 'Finished'"), sdb, q, [(1,)]) is None


def test_a_snippet_must_run_and_must_be_a_single_expression(sdb):
    sql = "status.status = 'Finished'"
    check = lambda *args, **kwargs: check_snippet(snippet(*args, **kwargs), sdb, FINISHED, [(2,)])
    assert check("status.status = 'Nope'") == "snippet matches no row"
    assert check("status.statusId IN (SELECT statusId FROM status)") == "not a single short expression"
    assert check(sql + "; --") == "not a single short expression"
    assert check(sql, table="nope") == "unknown table"
    assert check(sql, form="clause") == "malformed snippet"
