import pytest

from evosql.knowledge import Edit, Knowledge


def test_add_modify_delete_leave_original_untouched():
    k0 = Knowledge()
    k1, n1 = k0.apply(Edit("add", when="charter schools", text="use frpm.Charter"), step=1, qid=10)
    k2, _ = k1.apply(Edit("modify", note_id=n1, when="charter schools", text="use frpm flag = 1"), step=2, qid=11)
    k3, _ = k2.apply(Edit("delete", note_id=n1), step=3, qid=12)
    assert k0.notes == [] and k1.get(n1).text == "use frpm.Charter"
    assert k2.get(n1).text == "use frpm flag = 1" and k2.get(n1).source_qid == 10
    assert k3.notes == []


def test_unknown_note_id_is_rejected():
    with pytest.raises(ValueError):
        Knowledge().apply(Edit("delete", note_id="n9"), step=1, qid=1)


def test_save_load_keeps_ids_so_deleted_ids_are_never_reused(tmp_path):
    k, n1 = Knowledge().apply(Edit("add", when="a", text="b"), 1, 1)
    k, _ = k.apply(Edit("delete", note_id=n1), 2, 2)
    k.save(tmp_path / "notes.json")
    loaded = Knowledge.load(tmp_path / "notes.json")
    _, new_id = loaded.apply(Edit("add", when="c", text="d"), 3, 3)
    assert new_id == "n2"
