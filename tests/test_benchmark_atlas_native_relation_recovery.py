"""Focused checks for the E3 native-relation recovery benchmark."""

from __future__ import annotations

import json

from tools import benchmark_atlas_native_relation_recovery as e3


def _concept(member: str, label: str, *alts: str, definition: str | None = None) -> e3.AblatedConcept:
    return e3.AblatedConcept(member=member, pref_label=label, alt_labels=alts, definition=definition)


def test_ablated_corpus_supplies_no_hierarchy_to_the_context_view() -> None:
    resource = type(
        "R",
        (),
        {
            "iri": "urn:a",
            "labels": (type("L", (), {"value": "Housing", "role": "preferred"})(),),
            "definition": "a definition",
            "notes": ("a scope note",),
            "notations": (),
        },
    )()
    release = type("Rel", (), {"resources": (resource,)})()

    (concept,) = e3._ablated_concepts(release)

    assert concept.pref_label == "Housing"
    assert concept.definition == "a definition"
    assert concept.scope_note == "a scope note"
    # The ablation: the sparse context view weights parents and children, and
    # must find nothing to read.
    assert concept.broader == ()
    assert concept.parents == ()
    assert concept.children == ()


def test_label_overlap_bands_split_identical_partial_and_disjoint_pairs() -> None:
    assert e3._overlap_band("Motor vehicles", "motor  vehicles") == "identical"
    assert e3._overlap_band("Housing supply", "Housing supply and demand") == "high"
    assert e3._overlap_band("Small business tax credit", "State aid") == "disjoint"
    assert e3._overlap_band("GRIEF", "BEREAVEMENT") == "disjoint"


def test_low_band_requires_partial_overlap_below_the_high_threshold() -> None:
    band = e3._overlap_band("a b c d e", "a z y x w")

    assert band == "low"


def test_unordered_pair_key_is_direction_independent() -> None:
    assert e3._unordered("urn:z", "urn:a") == e3._unordered("urn:a", "urn:z") == ("urn:a", "urn:z")


def test_sparse_ranks_exclude_self_matches() -> None:
    concepts = (
        _concept("urn:a", "housing supply"),
        _concept("urn:b", "housing demand"),
        _concept("urn:c", "maritime shipping"),
    )

    ranks = e3._sparse_ranks(concepts, e3.retrieval.LABEL_SPARSE_VIEW, 10)

    assert all(left != right for left, right in ranks)
    assert ("urn:a", "urn:b") in ranks


def test_sparse_ranks_keep_the_best_bidirectional_rank_per_pair() -> None:
    concepts = (
        _concept("urn:a", "housing supply"),
        _concept("urn:b", "housing demand"),
        _concept("urn:c", "housing"),
    )

    ranks = e3._sparse_ranks(concepts, e3.retrieval.LABEL_SPARSE_VIEW, 10)

    assert all(rank >= 1 for rank in ranks.values())
    assert min(ranks.values()) == 1


def test_alias_anchor_matches_individual_labels_rather_than_a_concatenated_bag() -> None:
    concepts = (
        _concept("urn:a", "Family planning", "birth control", "contraception"),
        _concept("urn:b", "BIRTH CONTROL"),
        _concept("urn:c", "Maritime shipping"),
    )

    pairs = e3._exact_alias_pairs(concepts)

    # The shared evidence is one alternate label of A equalling the preferred
    # label of B; a single concatenated alias bag would dilute it away.
    assert ("urn:a", "urn:b") in pairs
    assert not any("urn:c" in pair for pair in pairs)


def test_preferred_label_anchor_ignores_alternate_labels() -> None:
    concepts = (
        _concept("urn:a", "Family planning", "birth control"),
        _concept("urn:b", "BIRTH CONTROL"),
    )

    assert e3._exact_label_pairs(concepts) == set()
    assert ("urn:a", "urn:b") in e3._exact_alias_pairs(concepts)


def test_recall_counts_ranked_hits_only_within_the_requested_depth() -> None:
    found = {("urn:a", "urn:b"): 3, ("urn:a", "urn:c"): 40}
    gold = {("urn:a", "urn:b"), ("urn:a", "urn:c"), ("urn:a", "urn:d")}

    assert e3._recall_row(found, gold, 5) == 1
    assert e3._recall_row(found, gold, 50) == 2
    assert e3._recall_row(found, gold, 1) == 0


def test_recall_treats_unranked_anchor_sets_as_depth_independent() -> None:
    found = {("urn:a", "urn:b")}
    gold = {("urn:a", "urn:b"), ("urn:a", "urn:c")}

    assert e3._recall_row(found, gold, None) == 1


def test_gold_loads_per_relation_class_with_overlap_bands(tmp_path) -> None:
    row = {
        "relationClass": "hierarchy",
        "subject": {"iri": "urn:a", "label": "MARRIED WOMEN"},
        "object": {"iri": "urn:b", "label": "WOMEN"},
    }
    other = {
        "relationClass": "associative",
        "subject": {"iri": "urn:c", "label": "GRIEF"},
        "object": {"iri": "urn:d", "label": "BEREAVEMENT"},
    }
    (tmp_path / "src.jsonl").write_text(f"{json.dumps(row)}\n{json.dumps(other)}\n", encoding="utf-8")

    gold = e3.load_gold(tmp_path, "src")

    assert gold.by_class["hierarchy"] == {("urn:a", "urn:b")}
    assert gold.by_class["associative"] == {("urn:c", "urn:d")}
    assert gold.overlap[("urn:a", "urn:b")] == "high"
    assert gold.overlap[("urn:c", "urn:d")] == "disjoint"
    assert gold.all_pairs() == {("urn:a", "urn:b"), ("urn:c", "urn:d")}


def test_arm_report_records_the_disjoint_slice_separately() -> None:
    gold = e3.GoldSet(source="src")
    gold.by_class["hierarchy"] = {("urn:a", "urn:b"), ("urn:c", "urn:d")}
    gold.overlap = {("urn:a", "urn:b"): "identical", ("urn:c", "urn:d"): "disjoint"}

    report = e3._arm_report("test", {("urn:a", "urn:b"): 1}, gold, (1, 10), 0.0)

    entry = report["byRelationClass"]["hierarchy"]
    assert entry["gold"] == 2
    assert entry["recallAtDepth"]["1"] == 1
    assert entry["byLabelOverlap"]["identical"] == {"gold": 1, "found": 1}
    assert entry["byLabelOverlap"]["disjoint"] == {"gold": 1, "found": 0}
