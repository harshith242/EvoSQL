from evosql.bird import Question
from evosql.knowledge import Edit, Knowledge
from evosql.learner import Gate, GateConfig, leaks

TABLES = ["Patient", "Laboratory"]


def question(qid, text="how many patients"):
    return Question(qid, "toy", f"{text} {qid}", "SELECT COUNT(*) FROM Patient", "simple", "")


Q = {i: question(i) for i in range(1, 5)}
CURRENT, SEEN = Q[1], [Q[2], Q[3], Q[4]]

# Which questions the agent gets right, given the set of note texts in its prompt.
OUTCOMES = {
    (): {2, 4},
    ("good",): {1, 2, 3, 4},
    ("bad",): {1},
    ("useless",): {2, 4},
    ("good", "useless"): {1, 2, 3, 4},
}


def solve(q, knowledge):
    return q.qid in OUTCOMES.get(tuple(sorted(n.text for n in knowledge.notes)), set())


def gate(**cfg):
    return Gate(GateConfig(**cfg), solve, TABLES, Q)


def add(text):
    return Edit("add", when="patient counts", text=text)


def test_note_that_fixes_question_and_a_replay_question_is_accepted_and_credited():
    d = gate(replay_k=3, noise_p=0.1).accept(add("good"), CURRENT, Knowledge(), SEEN, step=5, gold=[(7,)])
    assert d.accepted and d.gain == 2
    assert d.knowledge.notes[0].credited_qids == [1, 3]


def test_note_that_fixes_question_but_breaks_others_is_rejected_by_gate_but_kept_by_ratchet():
    evosql = gate(replay_k=3).accept(add("bad"), CURRENT, Knowledge(), SEEN, 5, [(7,)])
    ratchet = gate(replay_k=0, leakage_check=False, token_check=False, cap_tokens=0)
    assert not evosql.accepted and evosql.gain == -1
    assert ratchet.accept(add("bad"), CURRENT, Knowledge(), SEEN, 5, [(7,)]).accepted


def test_noise_band_raises_the_bar_on_small_gains():
    d = gate(replay_k=3, noise_p=0.5).accept(add("good"), CURRENT, Knowledge(), SEEN, 5, [(7,)])
    assert not d.accepted and "below needed 3" in d.reason


def test_delete_is_accepted_at_zero_gain():
    k, note_id = Knowledge().apply(add("useless"), 1, 2)
    d = gate(replay_k=3).accept(Edit("delete", note_id=note_id), CURRENT, k, SEEN, 5, [(7,)])
    assert d.accepted and d.knowledge.notes == []


def test_prune_drops_notes_that_no_longer_help_and_keeps_ones_that_do():
    k, useless = Knowledge().apply(add("useless"), 1, 2)
    k, good = k.apply(add("good"), 2, 1)
    k.get(useless).credited_qids, k.get(good).credited_qids = [2], [1]
    pruned, removed = gate().prune(k)
    assert removed == [useless] and [n.id for n in pruned.notes] == [good]


def test_cap_rejects_when_pruning_cannot_make_room():
    k, good = Knowledge().apply(add("good"), 1, 1)
    k.get(good).credited_qids = [1]
    d = gate(cap_tokens=k.total_tokens() + 1).accept(add("useless"), Q[2], k, [], 5, [(7,)])
    assert not d.accepted and d.reason == "over knowledge cap"


def test_leakage_flags_answer_values_but_allows_filter_constants_from_gold_sql():
    gold_sql, gold = "SELECT COUNT(*) FROM Patient WHERE SEX = 'F'", [(42,)]
    q = "How many female patients were admitted to the hospital?"
    assert leaks(add("the answer is 42"), q, gold_sql, gold)
    assert leaks(add("use SEX = 'F' for female patients"), q, gold_sql, gold) is None
    assert leaks(add("patients were admitted to the hospital means Admission = '+'"), q, gold_sql, gold)


def test_modify_of_a_note_pruned_to_make_room_is_rejected_not_crashed():
    k, useless = Knowledge().apply(add("useless"), 1, 2)
    k.get(useless).credited_qids = [2]
    edit = Edit("modify", note_id=useless, when="patient counts", text="good")
    d = gate(cap_tokens=1).accept(edit, CURRENT, k, SEEN, 5, [(7,)])
    assert not d.accepted and d.reason.startswith("invalid edit after prune") and d.pruned == [useless]
