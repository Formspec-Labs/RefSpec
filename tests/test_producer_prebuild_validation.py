from __future__ import annotations

import dataclasses
import hashlib
import importlib
import os
import sys
import time
from pathlib import Path

import pytest
from rdflib import Graph, URIRef
from rdflib.namespace import RDF, SKOS

from refspec.atlas import v3_registry_alignments as base_alignments
from refspec.atlas import v3_registry_alignments_bulk as bulk_alignments
from refspec.atlas import v3_registry_alignments_subject as subject_alignments
from refspec.atlas.v3_registry_vocabularies import load_gemet_release
from refspec.atlas.v3_source_data import (
    RegistryIdentifier,
    RegistryInputPin,
    RegistryMapping,
    RegistryMappingEvidence,
    RegistryMappingRelease,
    mapping_triple_digest,
)
from refspec.registry import gemet_alignments as gemet
from refspec.registry.eurovoc_alignment_portfolio import (
    load_eurovoc_alignment_portfolio,
)

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
generator = importlib.import_module("generate_atlas_v3_full")

WAVE_MAPPING_KEYS = frozenset(
    {
        "eurovoc-gemet-alignment-20201218",
        "eurovoc-mesh-alignment-20171215",
        "fast-bulk-external-links-delta-2026-07-27",
        "fast-lcsh-adopted-2026-08-15",
        "gemet-eurovoc-alignments-4.2.3",
        "gemet-umthes-alignments-4.2.3",
        "lcsh-external-links-mappings-2026-08-15",
        "mesh-lcsh-mapping-2021-03-31",
        "unified-agenda-gao-cra-priority-2026-08-15",
    }
)


@pytest.fixture(scope="module")
def complete_prebuild():
    if os.environ.get("REFSPEC_PRODUCER_PREBUILD_FULL") != "1":
        pytest.skip("set REFSPEC_PRODUCER_PREBUILD_FULL=1 to load the complete producer topology")
    started_at = time.perf_counter()
    try:
        releases = generator.load_releases()
        mapping_releases = generator.load_mapping_releases(
            source_releases=releases,
        )
    except FileNotFoundError as error:
        pytest.skip(str(error))
    validation = generator.validate_prebuild_loaded_releases(
        releases,
        mapping_releases,
    )
    return releases, mapping_releases, validation, time.perf_counter() - started_at


def test_complete_producer_prebuild_validation_runs_before_distribution_writes(
    complete_prebuild,
) -> None:
    releases, mapping_releases, validation, _elapsed = complete_prebuild

    assert len(mapping_releases) == 10
    assert sum(len(release.resources) for release in releases) == 1_344_511
    assert sum(len(release.mappings) for release in mapping_releases) == 864_943
    assert validation.compiled_rows.expected_counts["resources"] == 1_344_511
    assert validation.compiled_rows.expected_counts["mappingAssertions"] == 864_943
    assert validation.deep_compiled_output is None
    assert len(validation.pack_plans) == len(releases) + len(mapping_releases)
    assert len(validation.construction_seeds) == len(validation.pack_plans)
    assert validation.generation_report["type"] == "AtlasGenerationReport"

    owners = {
        resource.iri: (release.spec.key, release.atlas_release_iri)
        for release in releases
        for resource in release.resources
    }
    for release in mapping_releases:
        for mapping in release.mappings:
            assert owners[mapping.subject][1] == mapping.subject_atlas_release_iri
            assert owners[mapping.object][1] == mapping.object_atlas_release_iri

    assert {
        release.key: release.metadata["endpointOwnership"]["repinnedMappingCount"]
        for release in mapping_releases
        if release.metadata["endpointOwnership"]["repinnedMappingCount"]
    } == {
        "lcsh-external-links-mappings-2026-08-15": 11_243,
        "mesh-lcsh-mapping-2021-03-31": 13_235,
    }


def test_every_wave_mapping_evidence_resolves_to_one_used_unique_pin(
    complete_prebuild,
) -> None:
    _releases, mapping_releases, _validation, _elapsed = complete_prebuild
    by_key = {release.key: release for release in mapping_releases}
    assert WAVE_MAPPING_KEYS <= by_key.keys()

    for key in sorted(WAVE_MAPPING_KEYS):
        release = by_key[key]
        pin_identities = [(pin.source_iri, pin.sha256) for pin in release.inputs]
        assert len(pin_identities) == len(set(pin_identities)), key
        assert len({pin.sha256 for pin in release.inputs}) == len(release.inputs), key
        used_pins: set[int] = set()
        for mapping in release.mappings:
            for evidence in mapping.evidence:
                matches = [
                    index
                    for index, pin in enumerate(release.inputs)
                    if pin.sha256 == evidence.source_digest
                    and (
                        pin.source_iri == evidence.source_locator
                        or evidence.source_locator.startswith(pin.source_iri + "#")
                    )
                ]
                assert len(matches) == 1, (key, evidence.source_locator)
                used_pins.update(matches)
                generator._mapping_evidence(release, mapping, evidence)
        assert used_pins == set(range(len(release.inputs))), key


def test_complete_prebuild_finishes_without_constructing_or_writing_graphs(
    complete_prebuild,
) -> None:
    _releases, _mapping_releases, _validation, elapsed = complete_prebuild
    assert elapsed < 900, f"complete producer pre-build validation took {elapsed:.1f}s"


def _synthetic_releases(
    tmp_path: Path,
) -> tuple[generator.LoadedRelease, generator.LoadedRelease]:
    source = tmp_path / "source.json"
    source.write_text("{}\n", encoding="utf-8")
    digest = "sha256:" + hashlib.sha256(source.read_bytes()).hexdigest()

    def release(ordinal: str) -> generator.LoadedRelease:
        resource = generator.SourceResource(
            iri=f"urn:test:resource:{ordinal}",
            labels=(
                generator.SourceLabel(
                    value=ordinal.title(),
                    language="en",
                    role="preferred",
                    source_path=f"source.json#{ordinal}.label",
                ),
            ),
            native_payload={"id": ordinal},
            source_locator=f"https://example.test/source.json#{ordinal}",
            source_digest=digest,
        )
        spec = generator.SourceSpec(
            key=f"synthetic-{ordinal}",
            kind="test",
            path=source,
            logical_path="tests/synthetic/source.json",
            expected_digest=digest,
            expected_resources=1,
            profile="conceptScheme",
            ring="subject",
            source_module="refspec.atlas.v3_source_data",
        )
        return generator.LoadedRelease(
            spec=spec,
            source_release_iri=f"urn:test:source-release:{ordinal}",
            source_release_digest=digest,
            atlas_release_iri=f"urn:test:atlas-release:{ordinal}",
            scheme_iri=f"urn:test:scheme:{ordinal}",
            issued="2026-08-15",
            resources=(resource,),
            relations=(),
        )

    return release("first"), release("second")


def _synthetic_mapping_release(
    tmp_path: Path,
    releases: tuple[generator.LoadedRelease, generator.LoadedRelease],
) -> RegistryMappingRelease:
    source = tmp_path / "mapping.nt"
    source.write_text("synthetic mapping\n", encoding="utf-8")
    digest = "sha256:" + hashlib.sha256(source.read_bytes()).hexdigest()
    pin = RegistryInputPin(
        path=source,
        logical_path="tests/synthetic/mapping.nt",
        sha256=digest,
        byte_length=source.stat().st_size,
        source_iri="https://example.test/mapping.nt",
        role="publisherMapping",
    )
    subject = releases[0].resources[0].iri
    obj = releases[1].resources[0].iri
    predicate = str(SKOS.exactMatch)
    mapping = RegistryMapping(
        subject=subject,
        predicate=predicate,
        object=obj,
        subject_atlas_release_iri=releases[0].atlas_release_iri,
        object_atlas_release_iri=releases[1].atlas_release_iri,
        asserted_at="2026-08-15T01:00:00+00:00",
        evidence=(
            RegistryMappingEvidence(
                source_locator=pin.source_iri + "#line-1",
                source_digest=pin.sha256,
                native_payload={
                    "mappingTripleDigest": mapping_triple_digest(
                        subject_iri=subject,
                        predicate_iri=predicate,
                        object_iri=obj,
                    ),
                    "objectIri": obj,
                    "predicateIri": predicate,
                    "subjectIri": subject,
                },
                review_warrant="publisherAssertion",
                reviewer_iri="urn:test:publisher",
                attested_at="2026-08-15T00:00:00+00:00",
            ),
        ),
    )
    return RegistryMappingRelease(
        key="eurovoc-lcsh-alignment-20240711",
        resource_id="eurovoc-lcsh-alignment",
        source_module="refspec.registry.eurovoc_lcsh_alignment",
        ring="subject",
        scope="captureSubset",
        issued="2026-08-15",
        source_release_iri="urn:test:mapping-release",
        source_release_digest=digest,
        inputs=(pin,),
        mappings=(mapping,),
        editorial_policy={"profile": "synthetic-mapping-v1"},
    )


def _install_synthetic_release_schemes(monkeypatch: pytest.MonkeyPatch) -> None:
    descriptors: Graph = generator._registry_asserted_graph()
    for scheme in ("urn:test:scheme:first", "urn:test:scheme:second"):
        node = URIRef(scheme)
        descriptors.add((node, RDF.type, generator.ATLAS.ResourceScheme))
        descriptors.add((node, RDF.type, SKOS.ConceptScheme))
        descriptors.add(
            (
                node,
                generator.ATLAS.resourceProfile,
                generator.ATLAS.conceptScheme,
            )
        )
        descriptors.add(
            (
                node,
                generator.ATLAS.supportedRing,
                generator.ATLAS.subject,
            )
        )
    monkeypatch.setattr(generator, "_registry_asserted_graph", lambda: descriptors)


def test_default_prebuild_validation_accepts_a_valid_release_set_in_seconds(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_synthetic_release_schemes(monkeypatch)
    releases = _synthetic_releases(tmp_path)
    mapping_release = _synthetic_mapping_release(tmp_path, releases)
    started_at = time.perf_counter()

    validation = generator.validate_prebuild_loaded_releases(
        releases,
        (mapping_release,),
    )

    assert time.perf_counter() - started_at < 5
    assert validation.compiled_rows.expected_counts["resources"] == 2
    assert validation.compiled_rows.expected_counts["mappingAssertions"] == 1
    assert validation.deep_compiled_output is None


def test_prebuild_refuses_null_wire_metadata_in_seconds(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_synthetic_release_schemes(monkeypatch)
    releases = _synthetic_releases(tmp_path)
    dirty = dataclasses.replace(releases[0], metadata={"publisherField": None})

    with pytest.raises(generator.ATLAS_VALIDATE.AtlasValidationError) as error:
        generator.validate_prebuild_loaded_releases((dirty, releases[1]))
    assert error.value.code == "json.null"


def test_prebuild_refuses_an_unregistered_identifier_authority_in_seconds(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_synthetic_release_schemes(monkeypatch)
    releases = _synthetic_releases(tmp_path)
    resource = dataclasses.replace(
        releases[0].resources[0],
        identifiers=(
            RegistryIdentifier(
                value="UNREGISTERED-1",
                scheme_iri="urn:test:unregistered-identifier-authority",
                source_path="source.json#identifier",
            ),
        ),
    )
    dirty = dataclasses.replace(releases[0], resources=(resource,))

    with pytest.raises(ValueError, match="not an Atlas identifier authority"):
        generator.validate_prebuild_loaded_releases((dirty, releases[1]))


def test_prebuild_refuses_duplicate_resource_iris_in_seconds(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_synthetic_release_schemes(monkeypatch)
    releases = _synthetic_releases(tmp_path)
    duplicate = dataclasses.replace(
        releases[1],
        resources=(
            dataclasses.replace(
                releases[1].resources[0],
                iri=releases[0].resources[0].iri,
            ),
        ),
    )

    with pytest.raises(ValueError, match="Atlas releases repeat resource IRI"):
        generator.validate_prebuild_loaded_releases((releases[0], duplicate))


def test_prebuild_refuses_mapping_pack_partitioning_in_seconds(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_synthetic_release_schemes(monkeypatch)
    releases = _synthetic_releases(tmp_path)
    mapping_release = _synthetic_mapping_release(tmp_path, releases)
    original_partition = generator._release_pack_partition

    def legacy_partition(plan, subject):
        if plan.kind == "mapping":
            return "0"
        return original_partition(plan, subject)

    monkeypatch.setattr(generator, "_release_pack_partition", legacy_partition)
    with pytest.raises(ValueError, match="must not use a source pack partition"):
        generator.validate_prebuild_loaded_releases(releases, (mapping_release,))


def test_prebuild_refuses_unpinned_mapping_evidence_in_seconds(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_synthetic_release_schemes(monkeypatch)
    releases = _synthetic_releases(tmp_path)
    mapping_release = _synthetic_mapping_release(tmp_path, releases)
    mapping = mapping_release.mappings[0]
    evidence = dataclasses.replace(
        mapping.evidence[0],
        source_digest="sha256:" + "f" * 64,
    )
    dirty = dataclasses.replace(
        mapping_release,
        mappings=(dataclasses.replace(mapping, evidence=(evidence,)),),
    )

    with pytest.raises(ValueError, match="must identify exactly one pinned input"):
        generator.validate_prebuild_loaded_releases(releases, (dirty,))


def test_fast_lcsh_s27_reconciliation_uses_the_real_hierarchy_check(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    releases = _synthetic_releases(tmp_path)
    template_release = _synthetic_mapping_release(tmp_path, releases)
    template = template_release.mappings[0]
    fast_iri = "urn:test:fast:1"
    lcsh_iri = "urn:test:lcsh:1"
    conflict = dataclasses.replace(
        template,
        subject=fast_iri,
        predicate=str(SKOS.relatedMatch),
        object=lcsh_iri,
    )
    admitted_related = dataclasses.replace(
        template,
        subject="urn:test:fast:2",
        predicate=str(SKOS.relatedMatch),
        object="urn:test:lcsh:2",
    )
    admitted_exact = dataclasses.replace(
        template,
        subject="urn:test:fast:3",
        predicate=str(SKOS.exactMatch),
        object="urn:test:lcsh:3",
    )
    hierarchy = dataclasses.replace(
        template,
        subject=lcsh_iri,
        predicate=str(SKOS.broadMatch),
        object=fast_iri,
    )
    fast_release = dataclasses.replace(
        template_release,
        key="fast-lcsh-adopted-2026-08-15",
        mappings=(conflict, admitted_related, admitted_exact),
        metadata={
            "assertionComposition": {
                "publisherVerbatimRelatedMatch": {"assertionCount": 2},
            },
            "s46Safety": {"relatedMatchSubjectCount": 2},
        },
    )
    lc_release = dataclasses.replace(
        template_release,
        key="lcsh-external-links-mappings-2026-08-15",
        mappings=(hierarchy,),
        metadata={},
    )
    frozen_list = [{"fastIri": fast_iri, "lcshIri": lcsh_iri}]
    monkeypatch.setattr(base_alignments, "FAST_LCSH_S27_REFUSAL_COUNT", 1)
    monkeypatch.setattr(
        base_alignments,
        "FAST_LCSH_S27_REFUSAL_DIGEST",
        generator._canonical_digest(frozen_list),
    )
    raw_relations = {
        (URIRef(row.subject), URIRef(row.predicate), URIRef(row.object)): ()
        for row in (*fast_release.mappings, *lc_release.mappings)
    }
    with pytest.raises(generator.ATLAS_VALIDATE.AtlasValidationError) as error:
        generator.ATLAS_VALIDATE._check_skos_integrity(raw_relations)
    assert error.value.code == "dataset.skos-integrity"
    assert "SKOS S27 transitive hierarchy conflict" in error.value.detail

    reconciled = generator._reconcile_fast_lcsh_s27_mapping_conflicts((fast_release, lc_release))
    reconciled_fast = next(release for release in reconciled if release.key == "fast-lcsh-adopted-2026-08-15")
    assert {(row.subject, row.predicate, row.object) for row in reconciled_fast.mappings} == {
        (admitted_related.subject, admitted_related.predicate, admitted_related.object),
        (admitted_exact.subject, admitted_exact.predicate, admitted_exact.object),
    }
    assert reconciled_fast.metadata["skosS27Reconciliation"]["frozenConflictList"] == {
        "canonicalItemShape": {"fastIri": "IRI", "lcshIri": "IRI"},
        "count": 1,
        "digest": generator._canonical_digest(frozen_list),
    }
    admitted_relations = {
        (URIRef(row.subject), URIRef(row.predicate), URIRef(row.object)): ()
        for release in reconciled
        for row in release.mappings
    }
    generator.ATLAS_VALIDATE._check_skos_integrity(admitted_relations)


def test_frozen_gemet_eurovoc_s46_refusals_match_the_real_validator() -> None:
    source_root = subject_alignments.DEFAULT_SOURCE_ROOT
    if not (source_root / gemet.GEMET_ALIGNMENT_FILENAME).is_file():
        pytest.skip("pinned GEMET source is not cached")
    gemet_capture = gemet.load_gemet_alignments(source_root / gemet.GEMET_ALIGNMENT_FILENAME)
    gemet_rows = tuple(row for row in gemet_capture.mappings if row.target_system == "eurovoc")
    portfolio = load_eurovoc_alignment_portfolio(source_root)
    eurovoc_alignment = next(row for row in portfolio.alignments if row.pin.key == "gemet")
    eurovoc_subjects = bulk_alignments._subject_release_map(source_root)
    gemet_objects = {resource.iri for resource in load_gemet_release(source_root).resources}
    eurovoc_rows = tuple(
        row
        for row in eurovoc_alignment.mappings
        if row.subject_iri in eurovoc_subjects and row.object_iri in gemet_objects
    )
    raw_rows = (*gemet_rows, *eurovoc_rows)
    raw_relations = {
        (URIRef(row.subject_iri), URIRef(row.predicate_iri), URIRef(row.object_iri)): () for row in raw_rows
    }

    with pytest.raises(generator.ATLAS_VALIDATE.AtlasValidationError) as error:
        generator.ATLAS_VALIDATE._check_skos_integrity(raw_relations)
    assert error.value.code == "dataset.skos-integrity"
    assert "SKOS S46 exactMatch-component conflict" in error.value.detail

    frozen = frozenset().union(*base_alignments.GEMET_EUROVOC_S46_REFUSALS.values())
    assert len(frozen) == 39
    assert frozen <= {(row.subject_iri, row.predicate_iri, row.object_iri) for row in raw_rows}
    admitted_relations = {
        triple: evidence for triple, evidence in raw_relations.items() if tuple(map(str, triple)) not in frozen
    }
    generator.ATLAS_VALIDATE._check_skos_integrity(admitted_relations)


def test_frozen_umthes_s27_transformations_match_the_real_validator() -> None:
    source_root = subject_alignments.DEFAULT_SOURCE_ROOT
    if not (source_root / subject_alignments.umthes.UMTHES_CAPTURE_FILENAME).is_file():
        pytest.skip("pinned UMTHES source is not cached")
    endpoint = subject_alignments.load_umthes_endpoint_release(source_root)
    raw_relations = {}
    for relation in endpoint.relations:
        publisher = relation.source_payload.get("publisherRelation")
        predicate = publisher["predicateIri"] if publisher is not None else relation.predicate
        raw_relations[(URIRef(relation.subject), URIRef(predicate), URIRef(relation.object))] = ()

    with pytest.raises(generator.ATLAS_VALIDATE.AtlasValidationError) as error:
        generator.ATLAS_VALIDATE._check_skos_integrity(raw_relations)
    assert error.value.code == "dataset.skos-integrity"
    assert "SKOS S27 transitive hierarchy conflict" in error.value.detail

    hierarchy = {}
    related_pairs = set()
    for subject, predicate, obj in raw_relations:
        if predicate == SKOS.broader:
            generator.ATLAS_VALIDATE._add_compact_target(hierarchy, subject, obj)
        elif predicate == SKOS.narrower:
            generator.ATLAS_VALIDATE._add_compact_target(hierarchy, obj, subject)
        elif predicate == SKOS.related:
            related_pairs.add(generator.ATLAS_VALIDATE._canonical_pair(subject, obj))
    conflicts = generator.ATLAS_VALIDATE._hierarchy_connected_pairs(hierarchy, related_pairs)
    assert {(str(left), str(right)) for left, right in conflicts} == (
        subject_alignments.UMTHES_S27_RELATED_PAIRS
    )
    frozen_list = [
        {"leftIri": left, "rightIri": right}
        for left, right in sorted(subject_alignments.UMTHES_S27_RELATED_PAIRS)
    ]
    assert generator._canonical_digest(frozen_list) == (
        subject_alignments.UMTHES_S27_RELATED_PAIR_DIGEST
    )

    admitted_relations = {
        (URIRef(relation.subject), URIRef(relation.predicate), URIRef(relation.object)): ()
        for relation in endpoint.relations
    }
    generator.ATLAS_VALIDATE._check_skos_integrity(admitted_relations)


@pytest.mark.skipif(
    os.environ.get("REFSPEC_PRODUCER_PREBUILD_DEEP") != "1",
    reason="set REFSPEC_PRODUCER_PREBUILD_DEEP=1 for graph construction without writes",
)
def test_deep_prebuild_runs_compiled_output_validation(complete_prebuild) -> None:
    releases, mapping_releases, _validation, _elapsed = complete_prebuild
    validation = generator.validate_prebuild_loaded_releases(
        releases,
        mapping_releases,
        deep=True,
    )
    assert validation.deep_compiled_output is not None
    assert validation.deep_compiled_output["status"] == "passed"
