import json
import sqlite3

from evosql.bird import Question, open_db
import evosql.labels
from evosql.labels import FILE, corrected, known_wrong


def test_corrected_labels_pick_our_database_and_flag_changed_results(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)  # gold rows are cached under ./cache
    monkeypatch.setattr(evosql.labels, "OUR_FIXES", tmp_path / "none.json")
    (tmp_path / "toy").mkdir()
    con = sqlite3.connect(tmp_path / "toy" / "toy.sqlite")
    con.execute("CREATE TABLE Patient (ID INTEGER, SEX TEXT)")
    con.executemany("INSERT INTO Patient VALUES (?, ?)", [(1, "F"), (1, "F"), (2, "M")])
    con.commit()
    con.close()
    (tmp_path / FILE).parent.mkdir(parents=True)
    (tmp_path / FILE).write_text(json.dumps([
        {"question_id": "7", "db_id": "toy", "SQL": "SELECT COUNT(DISTINCT ID) FROM Patient"},
        {"question_id": "8", "db_id": "toy", "SQL": "SELECT ID FROM Patient WHERE SEX = 'M'"},
        {"question_id": "7", "db_id": "other", "SQL": "SELECT 1"},
    ]))
    fixes = corrected(tmp_path, "toy")
    assert fixes == {7: "SELECT COUNT(DISTINCT ID) FROM Patient", 8: "SELECT ID FROM Patient WHERE SEX = 'M'"}
    db = open_db(tmp_path, "toy")
    counts_rows = Question(7, "toy", "How many patients?", "SELECT COUNT(ID) FROM Patient", "simple")
    same_result = Question(8, "toy", "Male patients?", "SELECT ID FROM Patient WHERE SEX = 'M' ORDER BY ID", "simple")
    no_fix = Question(9, "toy", "Female?", "SELECT ID FROM Patient WHERE SEX = 'F'", "simple")
    assert known_wrong(db, counts_rows, fixes)
    assert not known_wrong(db, same_result, fixes) and not known_wrong(db, no_fix, fixes)


def test_our_reviewed_fixes_override_the_study(tmp_path, monkeypatch):
    (tmp_path / FILE).parent.mkdir(parents=True)
    (tmp_path / FILE).write_text(json.dumps([{"question_id": "7", "db_id": "toy", "SQL": "SELECT 1"},
                                             {"question_id": "8", "db_id": "toy", "SQL": "SELECT 2"}]))
    ours = tmp_path / "ours.json"
    ours.write_text(json.dumps([{"question_id": 8, "db_id": "toy", "SQL": "SELECT 3", "reason": "r"},
                                {"question_id": 9, "db_id": "toy", "SQL": "SELECT 4", "reason": "r"}]))
    monkeypatch.setattr(evosql.labels, "OUR_FIXES", ours)
    assert corrected(tmp_path, "toy") == {7: "SELECT 1", 8: "SELECT 3", 9: "SELECT 4"}
