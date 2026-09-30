import json

from conftest import make_db
from evosql.bird import Question, open_db
from evosql.ehrsql import NOW, TIME_NOTE, load_stream, open_mimic, score_sql


def test_score_sql_fixes_the_current_time_and_leaves_a_missing_sql_alone():
    assert score_sql("SELECT strftime('%Y', current_time)") == f"SELECT strftime('%Y', '{NOW}')"
    assert score_sql(None) is None


def test_load_stream_gives_questions_in_file_order_their_templates_and_combination_components(tmp_path):
    items = [{"qid": q, "id": f"h{q}", "db_id": "mimic_iv", "template": t, "question": f"Question {q}?",
              "query": f"SELECT {q}", "gold_sql": f"SELECT {q} -- processed"} for q, t in ((1, "A"), (2, "B"))]
    items.append({**items[0], "qid": 3, "template": None, "components": ["A", "B"]})
    path = tmp_path / "stream.json"
    path.write_text(json.dumps(items))

    questions, templates, components = load_stream(path)

    assert questions[:2] == [Question(1, "mimic_iv", "Question 1?", "SELECT 1 -- processed"),
                             Question(2, "mimic_iv", "Question 2?", "SELECT 2 -- processed")]
    assert templates == {1: "A", 2: "B", 3: None} and components == {3: ["A", "B"]}


def test_open_mimic_has_no_docs_and_appends_the_time_note_to_the_profile(tmp_path):
    make_db(tmp_path, "mimic_iv", "CREATE TABLE patients (subject_id INTEGER); INSERT INTO patients VALUES (1);")

    db = open_mimic(tmp_path, "mimic_iv")

    assert db.notes == {"patients": {}}
    assert db.profile.endswith("\n\n" + TIME_NOTE)
    assert db.profile == open_db(tmp_path, "mimic_iv", tmp_path / "none").profile + "\n\n" + TIME_NOTE
