"""Derived skos:broader edges from GCMD Science Keywords column nesting.

The judgment and its evidence are REF-041 in docs/decisions.md. These tests
prove the derivation over both a byte-faithful complete-branch excerpt and
the real pinned 24.4 bytes (when configured), and prove every fail-closed
premise bites: the excerpt fixture that is NOT prefix-closed (the existing
mini excerpt), a deleted parent row, a repeated path with a fresh UUID, an
asserted-relation collision in both directions, and the fact that the
shipped Atlas 3.1 validator refuses this rule's IRI today.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from refspec.registry import gcmd_science_keywords as gcmd
from refspec.registry import gcmd_science_keywords_hierarchy as hierarchy

FIXTURES = Path(__file__).parent / "fixtures" / "gcmd_science_keywords"
MINI_CSV_FIXTURE = FIXTURES / "gcmd-science-keywords-24.4-mini.csv"
BRANCH_CSV_FIXTURE = FIXTURES / "gcmd-science-keywords-24.4-agriculture-branch.csv"

BINDING_TOOLS = (
    Path(__file__).resolve().parents[1] / "bindings" / "atlas" / "3.1" / "tools"
)


def _pin_for(payload: bytes, row_count: int) -> gcmd.GCMDSnapshotPin:
    return gcmd.GCMDSnapshotPin(
        source=gcmd.GCMD_SCIENCE_KEYWORDS_SOURCE,
        retrieved_at="2026-08-03T19:03:43Z",
        expected_sha256=gcmd.sha256_digest(payload),
        expected_byte_length=len(payload),
        expected_keyword_version="24.4",
        expected_revision="2026-07-22T11:07:16.739Z",
        expected_row_count=row_count,
    )


def _parsed_from(
    tmp_path: Path,
    payload: bytes,
    row_count: int,
) -> gcmd.ParsedGCMDScienceKeywords:
    source_path = tmp_path / "source.csv"
    source_path.write_bytes(payload)
    acquired = gcmd.acquire_gcmd_science_keywords(
        _pin_for(payload, row_count), tmp_path / "store", source_path=source_path
    )
    return gcmd.parse_gcmd_science_keywords_csv(acquired)


def _branch_parsed(tmp_path: Path) -> gcmd.ParsedGCMDScienceKeywords:
    payload = BRANCH_CSV_FIXTURE.read_bytes()
    return _parsed_from(tmp_path, payload, 126)


def test_complete_branch_excerpt_derives_prefix_closed_edges(tmp_path: Path) -> None:
    hierarchy_result = hierarchy.derive_gcmd_science_keywords_hierarchy(
        _branch_parsed(tmp_path)
    )

    assert hierarchy_result.row_count == 126
    assert hierarchy_result.root_count == 1
    assert len(hierarchy_result.edges) == 125
    assert hierarchy_result.rule == hierarchy.GCMD_COLUMN_NESTING_RULE
    by_child = hierarchy_result.by_child_uuid()
    aquaculture = by_child["8916dafb-5ad5-45c6-ab64-3500ea1e9577"]
    assert (aquaculture.child_label, aquaculture.parent_label) == (
        "AQUACULTURE",
        "AGRICULTURAL AQUATIC SCIENCES",
    )
    assert aquaculture.predicate == hierarchy.SKOS_BROADER
    assert aquaculture.child_source_path == "csv:row[3]"
    assert aquaculture.parent_source_path == "csv:row[2]"
    assert aquaculture.source_sha256 == gcmd.sha256_digest(BRANCH_CSV_FIXTURE.read_bytes())
    assert aquaculture.edge_id.startswith("urn:ref:gcmd-derived-edge:")
    root_edge = by_child["a956d045-3b12-441c-8a18-fac7d33b2b4e"]
    assert (root_edge.child_label, root_edge.parent_label) == (
        "AGRICULTURE",
        "EARTH SCIENCE",
    )


def test_every_edge_cites_two_distinct_exact_csv_rows(tmp_path: Path) -> None:
    hierarchy_result = hierarchy.derive_gcmd_science_keywords_hierarchy(
        _branch_parsed(tmp_path)
    )
    parsed = _branch_parsed(tmp_path)
    source_paths = {row.source_path for row in parsed.rows}

    assert len({edge.edge_id for edge in hierarchy_result.edges}) == 125
    for edge in hierarchy_result.edges:
        assert edge.child_source_path in source_paths
        assert edge.parent_source_path in source_paths
        assert edge.child_source_path != edge.parent_source_path
        assert edge.child_uuid != edge.parent_uuid


def test_derivation_is_reproducible_from_the_pinned_bytes(tmp_path: Path) -> None:
    first = hierarchy.derive_gcmd_science_keywords_hierarchy(_branch_parsed(tmp_path))
    second = hierarchy.derive_gcmd_science_keywords_hierarchy(_branch_parsed(tmp_path))

    assert first.edge_set_digest == second.edge_set_digest
    assert [edge.edge_id for edge in first.edges] == [edge.edge_id for edge in second.edges]
    assert [edge.record() for edge in first.edges] == [
        edge.record() for edge in second.edges
    ]


def test_mini_excerpt_is_not_prefix_closed_and_fails_closed(tmp_path: Path) -> None:
    payload = MINI_CSV_FIXTURE.read_bytes()
    parsed = _parsed_from(tmp_path, payload, 9)

    with pytest.raises(hierarchy.GCMDHierarchyError, match="no materialized parent row"):
        hierarchy.derive_gcmd_science_keywords_hierarchy(parsed)


def test_deleted_parent_row_fails_closed(tmp_path: Path) -> None:
    payload = BRANCH_CSV_FIXTURE.read_bytes()
    lines = payload.splitlines(keepends=True)
    # csv:row[2] is AGRICULTURAL AQUATIC SCIENCES, the parent of AQUACULTURE.
    mutated = b"".join(lines[:4] + lines[5:])
    parsed = _parsed_from(tmp_path, mutated, 125)

    with pytest.raises(hierarchy.GCMDHierarchyError, match="no materialized parent row"):
        hierarchy.derive_gcmd_science_keywords_hierarchy(parsed)


def test_repeated_path_with_a_fresh_uuid_fails_closed(tmp_path: Path) -> None:
    payload = BRANCH_CSV_FIXTURE.read_bytes()
    duplicated = payload.replace(
        b'"EARTH SCIENCE","AGRICULTURE","AGRICULTURAL AQUATIC SCIENCES","",'
        b'"","","","ca227ff0-4742-4e51-a763-4582fa28291c"\n',
        b'"EARTH SCIENCE","AGRICULTURE","AGRICULTURAL AQUATIC SCIENCES","",'
        b'"","","","ca227ff0-4742-4e51-a763-4582fa28291c"\n'
        b'"EARTH SCIENCE","AGRICULTURE","AGRICULTURAL AQUATIC SCIENCES","",'
        b'"","","","0e6f5c90-8406-4d75-9a41-7d3e3729db21"\n',
        1,
    )
    assert len(duplicated) > len(payload)
    parsed = _parsed_from(tmp_path, duplicated, 127)

    with pytest.raises(hierarchy.GCMDHierarchyError, match="path repeats"):
        hierarchy.derive_gcmd_science_keywords_hierarchy(parsed)


def test_asserted_relation_collision_fails_closed_in_both_directions(
    tmp_path: Path,
) -> None:
    parsed = _branch_parsed(tmp_path)

    with pytest.raises(hierarchy.GCMDHierarchyError, match="duplicates an asserted"):
        hierarchy.derive_gcmd_science_keywords_hierarchy(
            parsed,
            asserted_relations=(
                (
                    "8916dafb-5ad5-45c6-ab64-3500ea1e9577",
                    hierarchy.SKOS_BROADER,
                    "ca227ff0-4742-4e51-a763-4582fa28291c",
                ),
            ),
        )
    with pytest.raises(hierarchy.GCMDHierarchyError, match="duplicates an asserted"):
        hierarchy.derive_gcmd_science_keywords_hierarchy(
            parsed,
            asserted_relations=(
                (
                    "ca227ff0-4742-4e51-a763-4582fa28291c",
                    hierarchy.SKOS_NARROWER,
                    "8916dafb-5ad5-45c6-ab64-3500ea1e9577",
                ),
            ),
        )
    unrelated = hierarchy.derive_gcmd_science_keywords_hierarchy(
        parsed,
        asserted_relations=(
            ("8916dafb-5ad5-45c6-ab64-3500ea1e9577", hierarchy.SKOS_BROADER, "e9f67a66-e9fc-435c-b720-ae32a2c3d8f5"),
        ),
    )
    assert len(unrelated.edges) == 125


def test_binding_does_not_allowlist_this_rule_today() -> None:
    sys.path.insert(0, str(BINDING_TOOLS))
    try:
        import validate as atlas_validate
    finally:
        sys.path.remove(str(BINDING_TOOLS))

    assert hierarchy.GCMD_COLUMN_NESTING_RULE != str(
        atlas_validate.EXACT_MATCH_TRANSITIVITY_RULE
    )
    assert atlas_validate.EXACT_MATCH_TRANSITIVITY_RULE == atlas_validate.URIRef(
        "urn:ref:rule:skos-exact-match-closure-path"
    )


def test_frozen_pins_match_the_documented_real_release() -> None:
    assert hierarchy.GCMD_24_4_DERIVED_ROOT_COUNT == 2
    assert hierarchy.GCMD_24_4_DERIVED_EDGE_COUNT == 3_772
    assert hierarchy.GCMD_24_4_DERIVED_HOMONYM_LABEL_COUNT == 512
    assert hierarchy.GCMD_24_4_DERIVED_EDGE_SET_SHA256.startswith("sha256:")
    assert len(hierarchy.GCMD_24_4_DERIVED_EDGE_SET_SHA256) == len("sha256:") + 64


def test_real_full_release_derives_the_frozen_edge_set(tmp_path: Path) -> None:
    source_path_text = os.environ.get("REFSPEC_GCMD_SCIENCE_KEYWORDS_PATH")
    if source_path_text is None:
        pytest.skip("real GCMD publisher distribution is not configured")
    acquired = gcmd.acquire_gcmd_science_keywords(
        gcmd.GCMD_SCIENCE_KEYWORDS_24_4,
        tmp_path,
        source_path=Path(source_path_text),
    )
    parsed = gcmd.parse_gcmd_science_keywords_csv(acquired)

    result = hierarchy.derive_gcmd_science_keywords_hierarchy(parsed)

    assert result.row_count == 3_774
    assert result.root_count == hierarchy.GCMD_24_4_DERIVED_ROOT_COUNT
    assert len(result.edges) == hierarchy.GCMD_24_4_DERIVED_EDGE_COUNT
    assert result.homonym_label_count == hierarchy.GCMD_24_4_DERIVED_HOMONYM_LABEL_COUNT
    assert result.edge_set_digest == hierarchy.GCMD_24_4_DERIVED_EDGE_SET_SHA256
    edges_again = hierarchy.derive_gcmd_science_keywords_hierarchy(parsed)
    assert [edge.edge_id for edge in edges_again.edges] == [
        edge.edge_id for edge in result.edges
    ]
