import numpy as np

from evosql.delivery import Retrieve
from evosql.facts import Fact, FactBook
from evosql.search import HybridIndex, bm25, words

FACTS = [
    Fact("f1", "constraint", "Laboratory.PLT", "A normal Laboratory.PLT is between 100 and 400.", ["normal platelet", "PLT"]),
    Fact("f2", "encoding", "Patient.SEX", "Women are stored as 'F'.", ["female", "woman"]),
    Fact("f3", "grain", "Laboratory", "One Laboratory row is one test; count patients by distinct Laboratory.ID.", ["how many patients"]),
    Fact("f4", "relation", "Patient-Laboratory", "Patient 1:N Laboratory via Patient.ID and Laboratory.ID.", ["lab results"]),
]


def fake_embed(texts):
    # One axis per topic plus a small shared one, so cosine is high only for texts about the same topic.
    axes = [("platelet", "thrombocyte"), ("female", "women"), ("row", "join"), ("birth", "date")]
    return np.array([[sum(w in t.lower() for w in axis) for axis in axes] + [0.1] for t in texts], float)


def test_bm25_ranks_the_exact_phrase_match_first():
    docs = [words(f"{' '.join(f.applies_to)} {f.subject} {f.fact}") for f in FACTS]
    scores = bm25(words("normal platelets"), docs)
    assert scores.index(max(scores)) == 0 and scores[1] == 0


def test_fusion_tags_how_each_fact_matched_and_the_floor_drops_unrelated_facts():
    index = HybridIndex(FACTS, fake_embed, min_cosine=0.5)
    hits = [(f.id, how) for f, how in index.search("How many female patients?", k=5)]
    assert hits[0] == ("f2", "keyword + semantic")  # found by both lists, listed once
    assert "f1" not in dict(hits)  # no shared word, unrelated embedding
    assert dict(hits)["f3"] == "keyword"
    assert [(f.id, how) for f, how in index.search("thrombocyte level", k=5)] == [("f1", "semantic")]
    assert index.search("date of birth", k=5) == []


def test_retrieve_caps_matched_facts_and_always_adds_grain_and_relation():
    retrieve = Retrieve(FactBook(FACTS), HybridIndex(FACTS, fake_embed, 0.5), cap=1)
    prompt = retrieve.prompt("female platelet counts")
    assert ("Patient.SEX" in prompt) != ("Laboratory.PLT\n" in prompt)  # only one of the two matches fits the cap
    assert "[grain]" in prompt and "[relation]" in prompt and retrieve.used == {"facts_in_prompt": 3}
