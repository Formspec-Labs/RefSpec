"""Official NASA TechPort Technology Taxonomy capture, parsing, and packaging tests."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from refspec.registry import nasa_technology_taxonomy as nasa
from refspec.registry.infrastructure.controlled_identifier import ControlledIdentifier

FIXTURES = Path(__file__).parent / "fixtures" / "nasa_technology_taxonomy"
ROOTS_FIXTURE = FIXTURES / "techport-taxonomy-roots-2026-08-03.json"
CHILDREN_FIXTURE = FIXTURES / "techport-taxonomy-8817-children-2026-08-03.json"


def _acquire(
    tmp_path: Path,
    pin: nasa.NASATaxonomySnapshotPin,
    source_path: Path,
) -> nasa.AcquiredNASATaxonomySource:
    return nasa.acquire_nasa_taxonomy_source(pin, tmp_path, source_path=source_path)


def _portfolio(tmp_path: Path) -> nasa.NASATaxonomyPortfolio:
    root_index = nasa.parse_nasa_taxonomy_root_index(
        _acquire(tmp_path, nasa.NASA_TAXONOMY_ROOT_INDEX_2026_08_03, ROOTS_FIXTURE)
    )
    children = nasa.parse_nasa_taxonomy_children(
        _acquire(tmp_path, nasa.NASA_TAXONOMY_ROOT_CHILDREN_2026_08_03, CHILDREN_FIXTURE)
    )
    return nasa.assemble_nasa_taxonomy_portfolio(root_index, children)


def test_live_snapshot_pins_match_exact_official_json_bytes() -> None:
    roots = ROOTS_FIXTURE.read_bytes()
    children = CHILDREN_FIXTURE.read_bytes()

    assert len(roots) == 143
    assert nasa.sha256_digest(roots) == ("sha256:c0c4b8e154f337be41f59b6b61bdd3b6b673b33bd49e5904b780e640391cbb07")
    assert len(children) == 3_408
    assert nasa.sha256_digest(children) == ("sha256:4e0ed6f5edee5b7e80c8789e4c3ef39c337a1f27de4cddede431feb94d314932")


def test_local_capture_is_content_addressed_and_rechecked_on_cache_hit(
    tmp_path: Path,
) -> None:
    pin = nasa.NASA_TAXONOMY_ROOT_CHILDREN_2026_08_03

    acquired = _acquire(tmp_path, pin, CHILDREN_FIXTURE)
    cached = nasa.acquire_nasa_taxonomy_source(pin, tmp_path)

    assert acquired.path == (tmp_path / "sha256" / pin.expected_sha256.removeprefix("sha256:") / pin.source.filename)
    assert acquired.acquisition_mode == "local"
    assert acquired.cache_hit is False
    assert cached.sha256 == pin.expected_sha256
    assert cached.acquisition_mode == "cache"
    assert cached.cache_hit is True


def test_injected_fetcher_is_the_only_live_transport_boundary(tmp_path: Path) -> None:
    payload = ROOTS_FIXTURE.read_bytes()
    calls: list[tuple[str, float]] = []

    class Fetcher:
        def fetch(
            self,
            source_url: str,
            *,
            timeout_seconds: float,
        ) -> nasa.FetchedNASATaxonomyResponse:
            calls.append((source_url, timeout_seconds))
            return nasa.FetchedNASATaxonomyResponse(
                body=payload,
                status_code=200,
                content_type="application/json;charset=UTF-8",
                resolved_url=source_url,
            )

    acquired = nasa.acquire_nasa_taxonomy_source(
        nasa.NASA_TAXONOMY_ROOT_INDEX_2026_08_03,
        tmp_path,
        fetcher=Fetcher(),
        timeout_seconds=13.0,
    )

    assert calls == [(nasa.NASA_TAXONOMY_ROOT_INDEX.source_url, 13.0)]
    assert acquired.acquisition_mode == "fetcher"


def test_root_index_reports_the_captured_release_as_current(tmp_path: Path) -> None:
    resource = nasa.parse_nasa_taxonomy_root_index(
        _acquire(tmp_path, nasa.NASA_TAXONOMY_ROOT_INDEX_2026_08_03, ROOTS_FIXTURE)
    )

    assert len(resource.roots) == 1
    root = resource.roots[0]
    assert root.taxonomy_root_id == 8817
    assert root.release_status == "Released"
    assert root.title == "2024 NASA Technology Taxonomy"


def test_children_are_top_level_deterministic_codes_not_subject_concepts(
    tmp_path: Path,
) -> None:
    resource = nasa.parse_nasa_taxonomy_children(
        _acquire(tmp_path, nasa.NASA_TAXONOMY_ROOT_CHILDREN_2026_08_03, CHILDREN_FIXTURE)
    )

    assert len(resource.nodes) == 17
    assert resource.taxonomy_root_id == 8817
    assert resource.publisher_release == "2024 NASA Technology Taxonomy"
    assert all(node.level == 1 for node in resource.nodes)
    assert all(node.use == "deterministicMetadata" for node in resource.nodes)
    assert all(not node.is_general_subject_concept for node in resource.nodes)
    node = resource.by_code()["TX01"]
    assert node.publisher_label == "Propulsion Systems"
    assert node.has_children is True
    assert node.identifiers[0] == ControlledIdentifier(
        value="TX01",
        kind="taxonomyNodeCode",
        authority_uri=nasa.NASA_TECHPORT_IDENTIFIER_AUTHORITY_URI,
        source_uri=nasa.NASA_TAXONOMY_ROOT_CHILDREN.source_url,
        observed_at=nasa.NASA_TAXONOMY_ROOT_CHILDREN_2026_08_03.retrieved_at,
        effective_at=None,
        source_digest=nasa.NASA_TAXONOMY_ROOT_CHILDREN_2026_08_03.expected_sha256,
    )
    assert resource.by_code()["TX17"].publisher_label == "GN&C"


def test_portfolio_cross_checks_release_and_records_known_gaps(tmp_path: Path) -> None:
    portfolio = _portfolio(tmp_path)

    assert portfolio.children.publisher_release == "2024 NASA Technology Taxonomy"
    assert any("level 1" in gap for gap in portfolio.gaps)
    assert any("no independent taxonomy revision" in gap for gap in portfolio.gaps)
    assert any("no code is treated as a general-subject concept" in gap for gap in portfolio.gaps)


def test_release_index_and_children_root_mismatch_fails_closed(tmp_path: Path) -> None:
    root_index = nasa.parse_nasa_taxonomy_root_index(
        _acquire(tmp_path, nasa.NASA_TAXONOMY_ROOT_INDEX_2026_08_03, ROOTS_FIXTURE)
    )
    children = nasa.parse_nasa_taxonomy_children(
        _acquire(tmp_path, nasa.NASA_TAXONOMY_ROOT_CHILDREN_2026_08_03, CHILDREN_FIXTURE)
    )
    drifted_root = replace(children.nodes[0])  # ensure nodes remain frozen/comparable
    assert drifted_root == children.nodes[0]
    drifted_children = replace(children, taxonomy_root_id=9999)

    with pytest.raises(nasa.NASATaxonomySourceDriftError, match="taxonomy root"):
        nasa.assemble_nasa_taxonomy_portfolio(root_index, drifted_children)


def test_digest_or_unknown_shape_drift_never_becomes_a_parsed_resource(
    tmp_path: Path,
) -> None:
    payload = CHILDREN_FIXTURE.read_bytes()
    changed = payload.replace(b'"Propulsion Systems"', b'"Propulsion Systeme"')
    assert len(changed) == len(payload)

    class ChangedFetcher:
        def fetch(
            self,
            source_url: str,
            *,
            timeout_seconds: float,
        ) -> nasa.FetchedNASATaxonomyResponse:
            del timeout_seconds
            return nasa.FetchedNASATaxonomyResponse(
                body=changed,
                status_code=200,
                content_type="application/json;charset=UTF-8",
                resolved_url=source_url,
            )

    with pytest.raises(nasa.NASATaxonomySourceDriftError, match="digest drift"):
        nasa.acquire_nasa_taxonomy_source(
            nasa.NASA_TAXONOMY_ROOT_CHILDREN_2026_08_03,
            tmp_path,
            fetcher=ChangedFetcher(),
        )

    mini_payload = (
        b'{"taxonomyRootId":8817,"taxonomyRoot":{"taxonomyRootId":8817,"releaseStatus":"Released",'
        b'"title":"2024 NASA Technology Taxonomy","releaseStatusString":"Released"},'
        b'"children":[{"content":{"taxonomyNodeId":11004,"taxonomyRootId":8817,"code":"TX01",'
        b'"title":"Propulsion Systems","level":1,"hasChildren":true,"selected":false,'
        b'"hasInteriorContent":true,"unexpectedField":"drift"}}]}'
    )
    mini_source = replace(nasa.NASA_TAXONOMY_ROOT_CHILDREN, expected_count=1)
    mini_pin = nasa.NASATaxonomySnapshotPin(
        source=mini_source,
        retrieved_at="2026-08-03T19:03:22Z",
        expected_sha256=nasa.sha256_digest(mini_payload),
        expected_byte_length=len(mini_payload),
        publisher_release="2024 NASA Technology Taxonomy",
    )
    mini_path = tmp_path / "mini.json"
    mini_path.write_bytes(mini_payload)
    acquired = nasa.acquire_nasa_taxonomy_source(
        mini_pin,
        tmp_path / "shape",
        source_path=mini_path,
    )
    with pytest.raises(nasa.NASATaxonomySourceDriftError, match="fields drifted"):
        nasa.parse_nasa_taxonomy_children(acquired)


def test_non_top_level_node_is_refused(tmp_path: Path) -> None:
    payload = (
        b'{"taxonomyRootId":8817,"taxonomyRoot":{"taxonomyRootId":8817,"releaseStatus":"Released",'
        b'"title":"2024 NASA Technology Taxonomy","releaseStatusString":"Released"},'
        b'"children":[{"content":{"taxonomyNodeId":11005,"taxonomyRootId":8817,"code":"TX01",'
        b'"title":"Chemical Propulsion","level":2,"hasChildren":false,"selected":false,'
        b'"hasInteriorContent":false}}]}'
    )
    source = replace(nasa.NASA_TAXONOMY_ROOT_CHILDREN, expected_count=1)
    pin = nasa.NASATaxonomySnapshotPin(
        source=source,
        retrieved_at="2026-08-03T19:03:22Z",
        expected_sha256=nasa.sha256_digest(payload),
        expected_byte_length=len(payload),
        publisher_release="2024 NASA Technology Taxonomy",
    )
    path = tmp_path / "level2.json"
    path.write_bytes(payload)
    acquired = nasa.acquire_nasa_taxonomy_source(pin, tmp_path / "store", source_path=path)

    with pytest.raises(nasa.NASATaxonomySourceDriftError, match="level"):
        nasa.parse_nasa_taxonomy_children(acquired)


def test_duplicate_code_fails_closed(tmp_path: Path) -> None:
    payload = (
        b'{"taxonomyRootId":8817,"taxonomyRoot":{"taxonomyRootId":8817,"releaseStatus":"Released",'
        b'"title":"2024 NASA Technology Taxonomy","releaseStatusString":"Released"},'
        b'"children":['
        b'{"content":{"taxonomyNodeId":11004,"taxonomyRootId":8817,"code":"TX01",'
        b'"title":"Propulsion Systems","level":1,"hasChildren":true,"selected":false,"hasInteriorContent":true}},'
        b'{"content":{"taxonomyNodeId":11005,"taxonomyRootId":8817,"code":"TX01",'
        b'"title":"Duplicate","level":1,"hasChildren":true,"selected":false,"hasInteriorContent":true}}'
        b"]}"
    )
    source = replace(nasa.NASA_TAXONOMY_ROOT_CHILDREN, expected_count=2)
    pin = nasa.NASATaxonomySnapshotPin(
        source=source,
        retrieved_at="2026-08-03T19:03:22Z",
        expected_sha256=nasa.sha256_digest(payload),
        expected_byte_length=len(payload),
        publisher_release="2024 NASA Technology Taxonomy",
    )
    path = tmp_path / "dup.json"
    path.write_bytes(payload)
    acquired = nasa.acquire_nasa_taxonomy_source(pin, tmp_path / "store", source_path=path)

    with pytest.raises(nasa.NASATaxonomySourceDriftError, match="duplicate"):
        nasa.parse_nasa_taxonomy_children(acquired)


def test_build_package_preserves_two_source_artifacts_and_identifiers(
    tmp_path: Path,
) -> None:
    package = nasa.build_nasa_technology_taxonomy_package(ROOTS_FIXTURE, CHILDREN_FIXTURE)

    assert package.resource_manifest == {
        **package.resource_manifest,
        "resourceId": "nasa-technology-taxonomy-8817-top-level-2026-08-03",
        "resourceKind": "controlledCodeList",
        "schemaVersion": "2.0",
        "conceptIdentityClaimed": False,
        "uses": ("deterministicMetadata", "mappingReference"),
        "observationCount": 17,
    }
    by_code = {observation["identifiers"][0]["value"]: observation for observation in package.observations}
    tx01 = by_code["TX01"]
    assert tx01["labels"] == (
        {
            "value": "Propulsion Systems",
            "language": "en",
            "role": "preferred",
        },
    )
    assert tx01["identifiers"] == (
        {
            "value": "TX01",
            "kind": "taxonomyNodeCode",
            "authorityUri": "https://techport.nasa.gov/",
            "sourceUri": nasa.NASA_TAXONOMY_ROOT_CHILDREN.source_url,
            "sourcePath": "$.children[0].content",
            "observedAt": "2026-08-03T19:03:22Z",
            "sourceDigest": ("sha256:4e0ed6f5edee5b7e80c8789e4c3ef39c337a1f27de4cddede431feb94d314932"),
        },
        {
            "value": "11004",
            "kind": "publisherRecordId",
            "authorityUri": "https://techport.nasa.gov/",
            "sourceUri": nasa.NASA_TAXONOMY_ROOT_CHILDREN.source_url,
            "sourcePath": "$.children[0].content",
            "observedAt": "2026-08-03T19:03:22Z",
            "sourceDigest": ("sha256:4e0ed6f5edee5b7e80c8789e4c3ef39c337a1f27de4cddede431feb94d314932"),
        },
    )
    assert tx01["uses"] == ("deterministicMetadata", "mappingReference")
    assert tx01["conceptIdentityClaimed"] is False
    assert set(package.source_artifacts) == {
        nasa.NASA_TAXONOMY_ROOT_INDEX.source_url,
        nasa.NASA_TAXONOMY_ROOT_CHILDREN.source_url,
    }
    assert package.source_artifacts[nasa.NASA_TAXONOMY_ROOT_CHILDREN.source_url] == CHILDREN_FIXTURE.read_bytes()


def test_generation_is_byte_deterministic() -> None:
    first = nasa.build_nasa_technology_taxonomy_package(ROOTS_FIXTURE, CHILDREN_FIXTURE)
    second = nasa.build_nasa_technology_taxonomy_package(ROOTS_FIXTURE, CHILDREN_FIXTURE)

    assert first.artifact_bytes() == second.artifact_bytes()
    assert first.logical_digest == second.logical_digest
    assert first.logical_digest == nasa.NASA_TECHNOLOGY_TAXONOMY_PACKAGE_SPEC.expected_logical_digest


def test_view_reopens_pinned_package_and_supports_code_lookup(tmp_path: Path) -> None:
    built = nasa.build_nasa_technology_taxonomy_package(ROOTS_FIXTURE, CHILDREN_FIXTURE)
    package_path = built.write_to(tmp_path / "package")

    view = nasa.NASATechnologyTaxonomyView.open(package_path)

    assert len(view.nodes_by_code) == 17
    assert view.lookup_code("TX01")["labels"][0]["value"] == "Propulsion Systems"
    assert view.lookup_code("ZZ99") is None


def test_view_rejects_a_self_consistent_unpinned_repackage(tmp_path: Path) -> None:
    from refspec.registry.infrastructure.source_controlled_resource import (
        build_source_controlled_resource_bundle,
    )

    original = nasa.build_nasa_technology_taxonomy_package(ROOTS_FIXTURE, CHILDREN_FIXTURE)
    repackaged = build_source_controlled_resource_bundle(
        resource_id=nasa.NASA_TECHNOLOGY_TAXONOMY_PACKAGE_SPEC.resource_id,
        title=nasa.NASA_TECHNOLOGY_TAXONOMY_PACKAGE_SPEC.title,
        resource_kind="controlledCodeList",
        identity_status="publisherIdentifiersPreserved",
        uses=nasa.NASA_TECHNOLOGY_TAXONOMY_PACKAGE_SPEC.uses,
        captured_at=nasa.NASA_TAXONOMY_ROOT_CHILDREN_2026_08_03.retrieved_at,
        observations=original.observations,
        source_artifacts=original.source_artifacts,
        source_observed_count=17,
        gaps=nasa.NASA_TECHNOLOGY_TAXONOMY_PACKAGE_SPEC.known_gaps,
    )
    package_path = repackaged.write_to(tmp_path / "repackaged")

    with pytest.raises(nasa.NASATaxonomyPackageError, match="external pin"):
        nasa.NASATechnologyTaxonomyView.open(package_path)


def test_source_drift_cannot_produce_a_new_package(tmp_path: Path) -> None:
    payload = CHILDREN_FIXTURE.read_bytes().replace(
        b'"Robotic Systems"',
        b'"Robotic Systemz"',
    )
    assert len(payload) == len(CHILDREN_FIXTURE.read_bytes())
    changed = tmp_path / "changed-children.json"
    changed.write_bytes(payload)

    with pytest.raises(nasa.NASATaxonomySourceDriftError, match="digest drift"):
        nasa.build_nasa_technology_taxonomy_package(ROOTS_FIXTURE, changed)
