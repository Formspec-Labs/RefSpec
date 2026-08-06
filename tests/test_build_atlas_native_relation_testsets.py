"""Focused checks for the per-source native-relation test-set builder."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from tools import build_atlas_native_relation_testsets as builder

BROADER = builder.BROADER
NARROWER = builder.NARROWER
RELATED = builder.RELATED
USE = builder.THESAURUS_USE
USED_FOR = builder.THESAURUS_USED_FOR


def _label(value: str, role: str = "preferred") -> SimpleNamespace:
    return SimpleNamespace(value=value, role=role, language="en", source_path="test")


def _resource(iri: str, label: str, *, role: str = "preferred", definition: str | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        iri=iri,
        labels=(_label(label, role),),
        definition=definition,
        notes=(),
        notations=(),
    )


def _relation(subject: str, predicate: str, obj: str, marker: str = "m") -> SimpleNamespace:
    return SimpleNamespace(subject=subject, predicate=predicate, object=obj, source_payload={"marker": marker})


def _release(resources, relations, key: str = "test-source") -> SimpleNamespace:
    return SimpleNamespace(
        spec=SimpleNamespace(key=key),
        atlas_release_iri=f"urn:ref:atlas-release:3:{key}",
        source_release_digest="sha256:00",
        resources=tuple(resources),
        relations=tuple(relations),
    )


def test_hierarchy_collapses_both_directions_into_one_broader_oriented_row() -> None:
    release = _release(
        [_resource("urn:a", "LOANS"), _resource("urn:b", "CREDIT")],
        [_relation("urn:a", BROADER, "urn:b"), _relation("urn:b", NARROWER, "urn:a")],
    )

    rows = builder._rows_for_release(release)

    assert len(rows) == 1
    row = rows[0]
    assert row["relationClass"] == "hierarchy"
    assert row["directionality"] == "directed"
    # Subject is always the narrower concept under SKOS broader orientation.
    assert row["subject"]["label"] == "LOANS"
    assert row["object"]["label"] == "CREDIT"
    assert row["assertedPredicates"] == [BROADER, NARROWER]
    assert row["assertedDirectionCount"] == 2
    assert row["oneWayInSource"] is False
    assert len(row["sourcePayloads"]) == 2


def test_narrower_only_hierarchy_is_still_broader_oriented_and_flagged_one_way() -> None:
    release = _release(
        [_resource("urn:a", "CREDIT"), _resource("urn:b", "LOANS")],
        [_relation("urn:a", NARROWER, "urn:b")],
    )

    (row,) = builder._rows_for_release(release)

    assert row["subject"]["label"] == "LOANS"
    assert row["object"]["label"] == "CREDIT"
    assert row["assertedPredicates"] == [NARROWER]
    assert row["oneWayInSource"] is True


def test_reciprocal_associative_edges_deduplicate_and_sort_by_iri() -> None:
    release = _release(
        [_resource("urn:z", "Agriculture"), _resource("urn:a", "Agricultural research")],
        [_relation("urn:z", RELATED, "urn:a"), _relation("urn:a", RELATED, "urn:z")],
    )

    (row,) = builder._rows_for_release(release)

    assert row["relationClass"] == "associative"
    assert row["directionality"] == "undirected"
    assert (row["subject"]["iri"], row["object"]["iri"]) == ("urn:a", "urn:z")
    assert row["oneWayInSource"] is False


def test_one_way_associative_edge_preserves_publisher_asymmetry() -> None:
    release = _release(
        [_resource("urn:a", "A"), _resource("urn:z", "Z")],
        [_relation("urn:a", RELATED, "urn:z")],
    )

    (row,) = builder._rows_for_release(release)

    assert row["assertedDirectionCount"] == 1
    assert row["oneWayInSource"] is True
    # Symmetric SKOS semantics still make the row undirected.
    assert row["directionality"] == "undirected"


def test_equivalence_orients_access_term_to_preferred_term_from_either_predicate() -> None:
    release = _release(
        [
            _resource("urn:access", "abduction", role="alternate"),
            _resource("urn:preferred", "kidnapping"),
        ],
        [_relation("urn:preferred", USED_FOR, "urn:access")],
    )

    (row,) = builder._rows_for_release(release)

    assert row["relationClass"] == "equivalence"
    assert row["subject"]["label"] == "abduction"
    assert row["subject"]["labelRole"] == "alternate"
    assert row["object"]["label"] == "kidnapping"
    assert row["object"]["labelRole"] == "preferred"


def test_use_and_used_for_for_the_same_pair_collapse_to_one_row() -> None:
    release = _release(
        [_resource("urn:access", "ACA", role="alternate"), _resource("urn:pref", "Affordable Care Act")],
        [_relation("urn:access", USE, "urn:pref"), _relation("urn:pref", USED_FOR, "urn:access")],
    )

    (row,) = builder._rows_for_release(release)

    assert row["assertedPredicates"] == [USE, USED_FOR]
    assert row["assertedDirectionCount"] == 2


def test_hierarchy_and_association_between_the_same_pair_stay_separate_rows() -> None:
    release = _release(
        [_resource("urn:a", "A"), _resource("urn:b", "B")],
        [_relation("urn:a", BROADER, "urn:b"), _relation("urn:a", RELATED, "urn:b")],
    )

    rows = builder._rows_for_release(release)

    assert sorted(str(row["relationClass"]) for row in rows) == ["associative", "hierarchy"]


def test_alternate_only_endpoint_keeps_a_display_label() -> None:
    resource = _resource("urn:access", "abduction", role="alternate")

    block = builder._concept_block(resource)

    assert block["label"] == "abduction"
    assert block["labelRole"] == "alternate"
    assert block["altLabels"] == []


def test_definition_and_notes_survive_into_the_endpoint_block() -> None:
    resource = SimpleNamespace(
        iri="urn:a",
        labels=(_label("A"), _label("A alias", "alternate")),
        definition="a definition",
        notes=("scope note",),
        notations=("A1",),
    )

    block = builder._concept_block(resource)

    assert block["altLabels"] == ["A alias"]
    assert block["definition"] == "a definition"
    assert block["notes"] == ["scope note"]
    assert block["notations"] == ["A1"]


def test_unknown_predicate_fails_closed() -> None:
    release = _release(
        [_resource("urn:a", "A"), _resource("urn:b", "B")],
        [_relation("urn:a", "urn:unmapped#predicate", "urn:b")],
    )

    with pytest.raises(ValueError, match="unmapped native predicate"):
        builder._rows_for_release(release)


def test_endpoint_outside_the_release_fails_closed() -> None:
    release = _release(
        [_resource("urn:a", "A")],
        [_relation("urn:a", RELATED, "urn:missing")],
    )

    with pytest.raises(ValueError, match="not a release member"):
        builder._rows_for_release(release)


def test_rows_are_emitted_in_a_stable_canonical_order() -> None:
    resources = [_resource(f"urn:{token}", token.upper()) for token in ("c", "a", "b")]
    relations = [_relation("urn:c", RELATED, "urn:a"), _relation("urn:b", RELATED, "urn:a")]

    forward = builder._rows_for_release(_release(resources, relations))
    reversed_inputs = builder._rows_for_release(_release(list(reversed(resources)), list(reversed(relations))))

    assert [row["id"] for row in forward] == [row["id"] for row in reversed_inputs]


def test_build_writes_canonical_jsonl_and_a_reproducible_manifest(tmp_path, monkeypatch) -> None:
    release = _release(
        [_resource("urn:a", "A"), _resource("urn:b", "B")],
        [_relation("urn:a", BROADER, "urn:b")],
    )
    monkeypatch.setattr(builder, "load_test_set_releases", lambda: (release,))

    first = builder.build_test_sets(tmp_path)
    emitted = (tmp_path / "test-source.jsonl").read_bytes()
    second = builder.build_test_sets(tmp_path)

    assert first["manifestDigest"] == second["manifestDigest"]
    assert emitted == (tmp_path / "test-source.jsonl").read_bytes()
    assert emitted.endswith(b"\n")
    assert json.loads(emitted.decode("utf-8"))["relationClass"] == "hierarchy"
    assert first["totals"]["canonicalRows"] == 1
    assert first["sources"][0]["rawNativeRelations"] == 1
