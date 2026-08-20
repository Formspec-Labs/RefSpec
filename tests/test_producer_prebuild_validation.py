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
from refspec.atlas import v3_registry_alignments_lc as lc_alignments
from refspec.atlas import v3_registry_alignments_lcsh as lcsh_alignments
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
from refspec.registry import fast_topical as fast_topical_registry
from refspec.registry import gemet_alignments as gemet
from refspec.registry import lc_external_links as lc_external_links_registry
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
        "regulations-gov-agency-identity-2026-08-16",
        "unified-agenda-gao-cra-priority-2026-08-15",
    }
)

# The real-data replacement proof stays small enough for the legacy resident
# graph while still covering the production seams that synthetic fixtures miss:
# FAST crosses the large-source threshold, the value mapping carries three
# evidence records per assertion, and REF-038 contributes all five agency
# rosters plus its entity-identity mapping and projection.
REAL_STREAMING_EQUIVALENCE_KEYS = frozenset(
    {
        "ecfr-agencies-roster-2026-08-15",
        "ecfr-cfr-titles",
        "fast-topical-current",
        "federal-hierarchy-orgs-complete-2026-08-15",
        "federal-register-agencies-roster-2026-08-15",
        "gao-cra-priority-of-regulation",
        "opm-ehri-agency-subelement-2026-08-04",
        "regulations-gov-agencies-roster-2026-08-16",
        "regulations-gov-agency-identity-2026-08-16",
        "treasury-fast-book-accounts-parts-ii-iii-2026-07",
        "unified-agenda-gao-cra-priority-2026-08-15",
        "unified-agenda-priority-category",
    }
)

# Every pinned source `_reconcile_fast_lcsh_s27_mapping_conflicts` needs on
# both sides of the reconciliation: the FAST-LCSH candidate release (which
# itself depends on the consolidated LCSH release's full referenced-IRI
# union) and LC's external-links mapping release.
FAST_LCSH_S27_REQUIRED_FILES = (
    base_alignments.DEFAULT_SOURCE_ROOT / base_alignments.LCSH_BULK_FILENAME,
    base_alignments.DEFAULT_SOURCE_ROOT / "eurovoc-lcsh-alignment-20240711.rdf",
    base_alignments.DEFAULT_SOURCE_ROOT / "eurovoc-lcsh-alignment-20240711-metadata.rdf",
    base_alignments.DEFAULT_SOURCE_ROOT / "eurovoc-4.20-20240711-metadata.rdf",
    base_alignments.DEFAULT_SOURCE_ROOT / "eurovoc-4.24-metadata.ttl",
    base_alignments.DEFAULT_SOURCE_ROOT / lc_external_links_registry.LC_EXTERNAL_LINKS_FILENAME,
    base_alignments.DEFAULT_SOURCE_ROOT / "mesh-lcsh-mapping-20210325.zip",
    base_alignments.DEFAULT_SOURCE_ROOT / fast_topical_registry.FAST_TOPICAL_NATIVE_BASE_PIN.filename,
    *(
        base_alignments.DEFAULT_SOURCE_ROOT / pin.filename
        for pin in fast_topical_registry.FAST_TOPICAL_CHANGE_PINS
    ),
)
HAS_FAST_LCSH_S27_SOURCES = all(path.is_file() for path in FAST_LCSH_S27_REQUIRED_FILES)


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

    assert len(mapping_releases) == 11
    assert sum(len(release.resources) for release in releases) == 1_344_511
    # fast-lcsh-adopted-2026-08-15's emitted total moved from 427,704 to
    # 427,693 (865,264 - 11) when the SKOS S27 reconciliation widened its
    # hierarchy scope to include the consolidated LCSH release's native
    # skos:broader statements (see FAST_LCSH_S27_REFUSAL_COUNT).
    assert sum(len(release.mappings) for release in mapping_releases) == 865_253
    assert validation.compiled_rows.expected_counts["resources"] == 1_344_511
    assert validation.compiled_rows.expected_counts["mappingAssertions"] == 865_253
    assert (
        validation.compiled_rows.expected_counts["evidenceBindings"]
        - validation.compiled_rows.expected_counts["relationAssertions"]
        == 339
    )
    assert {
        release.key: sum(len(mapping.evidence) for mapping in release.mappings)
        - len(release.mappings)
        for release in mapping_releases
        if sum(len(mapping.evidence) for mapping in release.mappings)
        != len(release.mappings)
    } == {
        "mesh-lcsh-mapping-2021-03-31": 8,
        "regulations-gov-agency-identity-2026-08-16": 321,
        "unified-agenda-gao-cra-priority-2026-08-15": 10,
    }
    assert validation.compiled_rows.expected_construction_counts[
        "evidenceBindings"
    ] == validation.compiled_rows.expected_counts["evidenceBindings"]
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
        if key == "regulations-gov-agency-identity-2026-08-16":
            expected_evidence_roles = {
                "agencyRoster01Input01",
                "agencyRoster02Input01",
                "agencyRoster02Input02",
                "agencyRoster02Input04",
                "agencyRoster02Input05",
                "agencyRoster04Input01",
                "agencyRoster05Input01",
            }
        else:
            expected_evidence_roles = {pin.role for pin in release.inputs}
        expected_evidence_pins = {
            index
            for index, pin in enumerate(release.inputs)
            if pin.role in expected_evidence_roles
        }
        assert {release.inputs[index].role for index in used_pins} == (
            expected_evidence_roles
        ), key
        assert used_pins == expected_evidence_pins, key


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
    assert validation.compiled_rows.expected_counts["evidenceBindings"] == 3
    assert validation.compiled_rows.expected_construction_counts == {
        "resources": 2,
        "labels": 2,
        "statements": 3,
        "evidenceBindings": 3,
        "sourceRecords": 3,
        "releases": 5,
        "identifiers": 0,
        "lifecycleEvents": 0,
    }
    assert validation.deep_compiled_output is None


@pytest.mark.parametrize(
    "field",
    sorted(generator.ATLAS_VALIDATE.COMPACT_ROLE_COUNT_FIELDS.values()),
)
def test_default_prebuild_refuses_each_mutated_logical_aggregate(
    field: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Every construction-summary aggregate has a fast negative oracle."""

    _install_synthetic_release_schemes(monkeypatch)
    releases = _synthetic_releases(tmp_path)
    mapping_release = _synthetic_mapping_release(tmp_path, releases)
    receipt = generator._validate_compiled_producer_rows(
        releases,
        (mapping_release,),
    )
    mutated = dict(receipt.expected_construction_counts)
    mutated[field] += 1

    with pytest.raises(ValueError, match="prebuild construction aggregate counts differ"):
        generator._reconcile_prebuild_construction_counts(
            receipt.expected_counts,
            source_release_count=receipt.source_release_count,
            declared_record_counts=mutated,
        )


@pytest.mark.parametrize(
    "field",
    (
        "crossRingRelationAssertions",
        # "derivedRelations" is deliberately absent here as of REF-042: it is
        # no longer a field `_reconcile_prebuild_construction_counts` refuses
        # outright the way "projectedRelations" still is, because it can now
        # be legitimately nonzero (a registered derivation rule's expected
        # row count). That function's actual job -- reconciling the eight
        # logical construction-record roles -- never covered derivedRelations
        # anyway (`source_and_mapping_construction_record_counts` does not
        # reference it). A mutated derivedRelations expected count is still
        # caught, just by a different, already-tested check: the streamed
        # build's own `spool.counts != prebuild.compiled_rows.expected_counts`
        # comparison in `_stream_construct_graphs`
        # (`tests/test_generate_atlas_v3_full.py`'s
        # `test_streamed_whole_graph_refusal_probe[count-mismatch]` proves
        # that comparison refuses a wrong aggregate count generically).
        "evidenceBindings",
        "identifiers",
        "labels",
        "mappingAssertions",
        "nativeRelationAssertions",
        "projectedRelations",
        "relationAssertions",
        "releases",
        "resources",
        "sourceAssignments",
        "sourceRecords",
    ),
)
def test_default_prebuild_refuses_each_mutated_semantic_aggregate(
    field: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Every manifest aggregate `_reconcile_prebuild_construction_counts`
    still owns is reconciled before graph construction."""

    _install_synthetic_release_schemes(monkeypatch)
    releases = _synthetic_releases(tmp_path)
    mapping_release = _synthetic_mapping_release(tmp_path, releases)
    receipt = generator._validate_compiled_producer_rows(
        releases,
        (mapping_release,),
    )
    mutated = dict(receipt.expected_counts)
    mutated[field] += 1

    with pytest.raises(ValueError):
        generator._reconcile_prebuild_construction_counts(
            mutated,
            source_release_count=receipt.source_release_count,
            declared_record_counts=receipt.expected_construction_counts,
        )


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
    """Prove the reconciliation catches a conflict reachable only through a
    source release's native skos:broader relation, not just through the LC
    mapping release's own broadMatch/narrowMatch claims.

    This is the synthetic analogue of the real REF-040 build failure:
    ``fast_iri``/``chained_lcsh_iri`` conflict only via a two-hop path (a
    ``skos:broader`` edge the consolidated LCSH source release would carry,
    chained into LC's own ``broadMatch`` from ``lcsh_iri`` to ``fast_iri``)
    -- a shape the pre-fix reconciliation, which read only
    ``lc_release.mappings``, could not see.
    """

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
    chained_lcsh_iri = "urn:test:lcsh:4"
    chained_conflict = dataclasses.replace(
        template,
        subject=fast_iri,
        predicate=str(SKOS.relatedMatch),
        object=chained_lcsh_iri,
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
        mappings=(conflict, admitted_related, admitted_exact, chained_conflict),
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
    # A source release carrying the intra-LCSH skos:broader edge that only
    # the consolidated LCSH release contributes in production: chained_lcsh
    # is broader than lcsh:1, which LC's own broadMatch already connects to
    # fast:1 -- so chained_fast/chained_lcsh is hierarchy-connected only
    # through this two-hop path.
    lcsh_consolidated_source = dataclasses.replace(
        releases[0],
        spec=dataclasses.replace(releases[0].spec, key=lcsh_alignments.LCSH_CONSOLIDATED_RELEASE_KEY),
        relations=(
            generator.SourceRelation(
                subject=chained_lcsh_iri,
                predicate=str(SKOS.broader),
                object=lcsh_iri,
                source_payload={"lineNumber": 1},
            ),
        ),
    )
    frozen_list = [
        {"fastIri": fast_iri, "lcshIri": lcsh_iri},
        {"fastIri": fast_iri, "lcshIri": chained_lcsh_iri},
    ]
    monkeypatch.setattr(base_alignments, "FAST_LCSH_S27_REFUSAL_COUNT", 2)
    monkeypatch.setattr(
        base_alignments,
        "FAST_LCSH_S27_REFUSAL_DIGEST",
        generator._canonical_digest(frozen_list),
    )
    raw_relations = {
        (URIRef(row.subject), URIRef(row.predicate), URIRef(row.object)): ()
        for row in (*fast_release.mappings, *lc_release.mappings, *lcsh_consolidated_source.relations)
    }
    with pytest.raises(generator.ATLAS_VALIDATE.AtlasValidationError) as error:
        generator.ATLAS_VALIDATE._check_skos_integrity(raw_relations)
    assert error.value.code == "dataset.skos-integrity"
    assert "SKOS S27 transitive hierarchy conflict" in error.value.detail

    # Without the consolidated-LCSH-shaped source release, the reconciliation
    # must refuse rather than silently reconcile against a narrower hierarchy.
    with pytest.raises(ValueError, match="requires the consolidated LCSH"):
        generator._reconcile_fast_lcsh_s27_mapping_conflicts((fast_release, lc_release))
    with pytest.raises(ValueError, match="requires the consolidated LCSH"):
        generator._reconcile_fast_lcsh_s27_mapping_conflicts(
            (fast_release, lc_release),
            (),
        )

    reconciled = generator._reconcile_fast_lcsh_s27_mapping_conflicts(
        (fast_release, lc_release),
        (lcsh_consolidated_source,),
    )
    reconciled_fast = next(release for release in reconciled if release.key == "fast-lcsh-adopted-2026-08-15")
    assert {(row.subject, row.predicate, row.object) for row in reconciled_fast.mappings} == {
        (admitted_related.subject, admitted_related.predicate, admitted_related.object),
        (admitted_exact.subject, admitted_exact.predicate, admitted_exact.object),
    }
    assert reconciled_fast.metadata["skosS27Reconciliation"]["frozenConflictList"] == {
        "canonicalItemShape": {"fastIri": "IRI", "lcshIri": "IRI"},
        "count": 2,
        "digest": generator._canonical_digest(frozen_list),
    }
    admitted_relations = {
        (URIRef(row.subject), URIRef(row.predicate), URIRef(row.object)): ()
        for release in reconciled
        for row in release.mappings
    }
    admitted_relations.update(
        {
            (URIRef(relation.subject), URIRef(relation.predicate), URIRef(relation.object)): ()
            for relation in lcsh_consolidated_source.relations
        }
    )
    generator.ATLAS_VALIDATE._check_skos_integrity(admitted_relations)


@pytest.fixture(scope="module")
def real_fast_lcsh_s27_inputs() -> tuple[
    RegistryMappingRelease,
    RegistryMappingRelease,
    generator.LoadedRelease,
]:
    if not HAS_FAST_LCSH_S27_SOURCES:
        pytest.skip("official FAST, LCSH, and LC external-links sources are not cached")
    fast_release = base_alignments.load_fast_lcsh_mapping_release(base_alignments.DEFAULT_SOURCE_ROOT)
    lc_release = lc_alignments.load_lc_external_links_mapping_release(lc_alignments.DEFAULT_SOURCE_ROOT)
    lcsh_release = lcsh_alignments.load_lcsh_consolidated_release(lcsh_alignments.DEFAULT_SOURCE_ROOT)
    lcsh_source_release = generator._adapt_registry_release(lcsh_release)
    return fast_release, lc_release, lcsh_source_release


def test_fast_lcsh_s27_pin_matches_the_real_widened_conflict_set(
    real_fast_lcsh_s27_inputs: tuple[
        RegistryMappingRelease,
        RegistryMappingRelease,
        generator.LoadedRelease,
    ],
) -> None:
    """Reproduce the S27 reconciliation over real pinned data outside a full
    build.

    REF-040 widened the FAST-LCSH target scope from a 1,966-concept subset to
    every held LCSH concept, which reopens many more OCLC relatedMatch pairs
    against LC's independent hierarchy claims -- and, separately, against the
    consolidated LCSH release's own 301,442 native skos:broader statements,
    which is the hierarchy source that actually caused the REF-040 build
    failure (see
    `test_fast_lcsh_s27_pin_would_be_wrong_under_the_old_narrower_hierarchy_scope`).
    This is the fast, ungated check that must fail the moment the frozen
    conflict pin drifts from that widened reality, instead of only surfacing
    hours into a full distribution build.
    """

    fast_release, lc_release, lcsh_source_release = real_fast_lcsh_s27_inputs
    reconciled = generator._reconcile_fast_lcsh_s27_mapping_conflicts(
        (fast_release, lc_release),
        (lcsh_source_release,),
    )
    reconciled_fast = next(release for release in reconciled if release.key == fast_release.key)
    frozen = reconciled_fast.metadata["skosS27Reconciliation"]["frozenConflictList"]
    assert frozen["count"] == base_alignments.FAST_LCSH_S27_REFUSAL_COUNT == 174_766
    assert frozen["digest"] == base_alignments.FAST_LCSH_S27_REFUSAL_DIGEST
    admitted_related = sum(
        1 for row in reconciled_fast.mappings if row.predicate == str(SKOS.relatedMatch)
    )
    admitted_exact = sum(1 for row in reconciled_fast.mappings if row.predicate == str(SKOS.exactMatch))
    assert admitted_exact == 252_527
    assert admitted_related == 175_166
    assert len(reconciled_fast.mappings) == 427_693


def test_fast_lcsh_s27_pin_would_be_wrong_under_the_old_narrower_hierarchy_scope(
    real_fast_lcsh_s27_inputs: tuple[
        RegistryMappingRelease,
        RegistryMappingRelease,
        generator.LoadedRelease,
    ],
) -> None:
    """Prove the corpus-scope fix actually bites: the pre-fix hierarchy scope
    (LC's own broadMatch/narrowMatch claims alone) computes a different,
    wrong refusal count against the same real pinned data.

    This is what actually shipped the REF-040 build failure: a full build
    reached SKOS S27 at elapsed=776s and failed on
    (sh2008003833, fast/1910413) -- a pair hierarchy-connected only through
    a chain of intra-LCSH skos:broader edges the consolidated LCSH release
    contributes, which `_reconcile_fast_lcsh_s27_mapping_conflicts` never
    consulted before this fix. Reproducing the *old* narrower computation
    directly (not just calling the fixed function) proves this test would
    have caught the gap without ever running a build.
    """

    fast_release, lc_release, _lcsh_source_release = real_fast_lcsh_s27_inputs
    ATLAS_VALIDATE = generator.ATLAS_VALIDATE

    # The pre-fix hierarchy: only lc_release's own broadMatch/narrowMatch
    # claims, exactly what `_reconcile_fast_lcsh_s27_mapping_conflicts` read
    # before this fix.
    old_hierarchy: dict = {}
    for mapping in lc_release.mappings:
        subject = URIRef(mapping.subject)
        predicate = URIRef(mapping.predicate)
        obj = URIRef(mapping.object)
        if predicate == SKOS.broadMatch:
            ATLAS_VALIDATE._add_compact_target(old_hierarchy, subject, obj)
        elif predicate == SKOS.narrowMatch:
            ATLAS_VALIDATE._add_compact_target(old_hierarchy, obj, subject)

    related_pairs = {
        ATLAS_VALIDATE._canonical_pair(URIRef(mapping.subject), URIRef(mapping.object))
        for mapping in fast_release.mappings
        if mapping.predicate == str(SKOS.relatedMatch)
    }
    old_scope_refused_count = len(
        ATLAS_VALIDATE._hierarchy_connected_pairs(old_hierarchy, iter(related_pairs))
    )

    # This is the exact stale value the frozen pin carried before this fix --
    # correct for the old, too-narrow hierarchy scope, wrong for what the
    # binding's corpus-wide SKOS S27 check actually evaluates.
    assert old_scope_refused_count == 174_755
    assert old_scope_refused_count != base_alignments.FAST_LCSH_S27_REFUSAL_COUNT
    assert base_alignments.FAST_LCSH_S27_REFUSAL_COUNT == 174_766


def test_fast_lcsh_s27_pin_drift_fails_fast_without_a_full_build(
    real_fast_lcsh_s27_inputs: tuple[
        RegistryMappingRelease,
        RegistryMappingRelease,
        generator.LoadedRelease,
    ],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Proven-biting negative: a stale pin must be refused against the real,
    widened data, not just against a hand-built synthetic fixture.

    The pin below is the exact pre-REF-040 value -- correct for the retired
    narrow EuroVoc-alignment target scope, wrong for the widened one this
    release now uses. Reproducing this failure used to require a full,
    multi-hour distribution build; this test reproduces it in the time it
    takes to load three pinned releases.
    """

    fast_release, lc_release, lcsh_source_release = real_fast_lcsh_s27_inputs
    monkeypatch.setattr(base_alignments, "FAST_LCSH_S27_REFUSAL_COUNT", 24_190)
    monkeypatch.setattr(
        base_alignments,
        "FAST_LCSH_S27_REFUSAL_DIGEST",
        "sha256:fc9afdc9c1da43839d133ff0efe409dd0c6c0624152bacdfb65e9bd9320653bd",
    )
    with pytest.raises(ValueError, match="FAST--LCSH SKOS S27 refusal list drifted"):
        generator._reconcile_fast_lcsh_s27_mapping_conflicts(
            (fast_release, lc_release),
            (lcsh_source_release,),
        )


def test_fast_lcsh_s27_reconciliation_refuses_one_side_without_the_other(
    tmp_path: Path,
) -> None:
    """Loading exactly one of the reconciliation's two mapping releases, or
    omitting the consolidated LCSH source release, must refuse -- not
    silently ship 'fast-lcsh-adopted-2026-08-15' unreconciled or reconciled
    against a hierarchy narrower than what the corpus will carry.

    Before this fix, `_reconcile_fast_lcsh_s27_mapping_conflicts` returned its
    input unchanged whenever either mapping release was missing -- including
    when only one was missing. Any bounded/scoped build (`--only-release
    fast-lcsh-adopted-2026-08-15` without its LC hierarchy dependency) never
    exercised the S27 check at all, which is why the stale pin only ever
    surfaced in the unbounded full build. A second, separate gap let both
    mapping releases load without the consolidated LCSH source release
    (`lcsh-subjects-consolidated-2026-08-06`) present -- the actual gap that
    shipped the REF-040 build failure.
    """

    releases = _synthetic_releases(tmp_path)
    template = _synthetic_mapping_release(tmp_path, releases)
    fast_only = dataclasses.replace(template, key="fast-lcsh-adopted-2026-08-15")
    lc_only = dataclasses.replace(template, key="lcsh-external-links-mappings-2026-08-15")

    with pytest.raises(ValueError, match="requires both"):
        generator._reconcile_fast_lcsh_s27_mapping_conflicts((fast_only,))
    with pytest.raises(ValueError, match="requires both"):
        generator._reconcile_fast_lcsh_s27_mapping_conflicts((lc_only,))

    # Both mapping releases present, but the consolidated LCSH source release
    # is not -- must refuse, not reconcile against a narrower hierarchy.
    with pytest.raises(ValueError, match="requires the consolidated LCSH"):
        generator._reconcile_fast_lcsh_s27_mapping_conflicts((fast_only, lc_only))
    with pytest.raises(ValueError, match="requires the consolidated LCSH"):
        generator._reconcile_fast_lcsh_s27_mapping_conflicts((fast_only, lc_only), ())
    other_source = dataclasses.replace(
        releases[0],
        spec=dataclasses.replace(releases[0].spec, key="synthetic-unrelated-source"),
    )
    with pytest.raises(ValueError, match="requires the consolidated LCSH"):
        generator._reconcile_fast_lcsh_s27_mapping_conflicts((fast_only, lc_only), (other_source,))

    # Neither key in scope is still a legitimate no-op: a construction unit
    # that never touches FAST-LCSH mapping has nothing to reconcile.
    unrelated = dataclasses.replace(template, key="eurovoc-lcsh-alignment-20240711")
    assert generator._reconcile_fast_lcsh_s27_mapping_conflicts((unrelated,)) == (unrelated,)


def test_fast_see_also_has_no_thesaurus_related_eligible_pairs() -> None:
    source_root = bulk_alignments.DEFAULT_SOURCE_ROOT
    source = bulk_alignments._fast_bulk_input(source_root)
    if not source.path.is_file():
        pytest.skip("pinned OCLC FAST bulk source is not cached")
    fast_release = bulk_alignments.load_fast_topical_release(source_root)
    active_iris = frozenset(resource.iri for resource in fast_release.resources)
    capture = bulk_alignments.fast_bulk.parse_oclc_fast_external_links_file(
        source.path,
        retained_predicate_iris={bulk_alignments.fast_bulk.RDFS_SEE_ALSO},
    )
    internal_links = tuple(
        link for link in capture.retained_links if link.target_vocabulary == "fast"
    )
    requested_iris = frozenset(
        endpoint
        for link in internal_links
        for endpoint in (link.subject_iri, link.object_iri)
        if endpoint not in active_iris
    )
    endpoint_records, _missing_iris = (
        bulk_alignments.fast_bulk.capture_oclc_fast_endpoint_records(
            source.path,
            endpoint_iris=requested_iris,
        )
    )
    held_iris = active_iris | frozenset(endpoint_records)
    content_backed_links = tuple(
        link
        for link in internal_links
        if link.subject_iri in held_iris and link.object_iri in held_iris
    )
    assert len(content_backed_links) == (
        bulk_alignments.FAST_SEE_ALSO_CONTENT_BACKED_ASSERTION_COUNT
    )

    hierarchy = {}
    for relation in fast_release.relations:
        subject = URIRef(relation.subject)
        predicate = URIRef(relation.predicate)
        obj = URIRef(relation.object)
        if predicate == SKOS.broader:
            generator.ATLAS_VALIDATE._add_compact_target(hierarchy, subject, obj)
        elif predicate == SKOS.narrower:
            generator.ATLAS_VALIDATE._add_compact_target(hierarchy, obj, subject)
    related_pairs = {
        generator.ATLAS_VALIDATE._canonical_pair(
            URIRef(link.subject_iri),
            URIRef(link.object_iri),
        )
        for link in content_backed_links
    }
    conflicts = generator.ATLAS_VALIDATE._hierarchy_connected_pairs(
        hierarchy,
        related_pairs,
    )
    assert len(conflicts) == bulk_alignments.FAST_SEE_ALSO_S27_CONFLICT_PAIR_COUNT == 0
    assert generator._canonical_digest([]) == (
        bulk_alignments.FAST_SEE_ALSO_S27_CONFLICT_PAIR_DIGEST
    )


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


def test_prebuild_accepts_the_cfr_part_to_subject_crossing_without_a_build() -> None:
    """REF-047's cross-ring carrier, proved admissible in seconds.

    A full build takes hours, so nothing else in the suite would catch a
    cross-ring assertion the producer refuses until a release run failed on
    it. This loads the two real releases the crossing spans and runs the whole
    prebuild: endpoint ring agreement, the closed cross-ring predicate matrix,
    release ownership of every assertion, and the compiled row counts.
    """

    releases = generator.load_releases(
        frozenset(
            {
                "cfr-subject-index-parts-2026-08-20",
                "federal-register-api-topics-2026-08-03",
            }
        )
    )
    started_at = time.perf_counter()

    validation = generator.validate_prebuild_loaded_releases(releases)

    assert time.perf_counter() - started_at < 60
    counts = validation.compiled_rows.expected_counts
    assert counts["crossRingRelationAssertions"] == 31_683
    assert counts["mappingAssertions"] == 0
    assert counts["resources"] == 9_467
    # 8,423 CFR parts + 1,044 Federal Register topics; the topics release owns
    # its own 1,428 native relations and the crossing owns none.
    assert counts["nativeRelationAssertions"] == 1_428
    assert counts["relationAssertions"] == counts["evidenceBindings"] == 33_111


def test_prebuild_refuses_a_cfr_part_subject_link_that_leaves_the_admitted_cell() -> None:
    """The cross-ring predicate gate is what admits this crossing, not prose.

    `atlas:hasIndexedSubject` is the only predicate Atlas 3.1's closed matrix
    allows from legalIdentity to subject. Swapping in the entity-ring
    predicate that carries REF-037's other crossing must fail before anything
    is written.
    """

    releases = generator.load_releases(
        frozenset(
            {
                "cfr-subject-index-parts-2026-08-20",
                "federal-register-api-topics-2026-08-03",
            }
        )
    )
    carrier = next(
        release for release in releases if release.spec.key == "cfr-subject-index-parts-2026-08-20"
    )
    first, *rest = carrier.cross_ring_relations
    dirty = dataclasses.replace(
        carrier,
        cross_ring_relations=(
            dataclasses.replace(
                first,
                predicate="https://refspec.org/ns/atlas/v3#referencesLegalIdentity",
            ),
            *rest,
        ),
    )
    mutated = tuple(dirty if release is carrier else release for release in releases)

    with pytest.raises(ValueError, match="cross-ring"):
        generator.validate_prebuild_loaded_releases(mutated)


@pytest.mark.skipif(
    os.environ.get("REFSPEC_PRODUCER_PREBUILD_REAL_EQUIVALENCE") != "1",
    reason=(
        "set REFSPEC_PRODUCER_PREBUILD_REAL_EQUIVALENCE=1 for the bounded "
        "real-release streamed/legacy byte proof"
    ),
)
def test_bounded_real_releases_match_streamed_and_legacy_bytes(
    tmp_path: Path,
) -> None:
    """Run one bounded real multi-evidence corpus through both writer paths."""

    source_keys, mapping_keys = generator.split_construction_unit_keys(
        REAL_STREAMING_EQUIVALENCE_KEYS
    )
    releases = generator.load_releases(source_keys)
    mapping_releases = generator.load_mapping_releases(
        mapping_keys,
        source_releases=releases,
    )
    assert {release.spec.key for release in releases} == set(source_keys)
    assert {release.key for release in mapping_releases} == set(mapping_keys)
    assert any(
        len(release.resources) >= generator._PACK_LARGE_RELEASE_RESOURCE_THRESHOLD
        for release in releases
    )
    assert any(
        mapping.evidence
        for release in mapping_releases
        for mapping in release.mappings
    )
    assert any(
        len(mapping.evidence) > 1
        for release in mapping_releases
        for mapping in release.mappings
    )
    assert "regulations-gov-agency-identity-2026-08-16" in {
        release.key for release in mapping_releases
    }

    prebuild = generator.validate_prebuild_loaded_releases(
        releases,
        mapping_releases,
    )
    agency_projection, missing_projection_keys = (
        generator._agency_projection_from_loaded_releases(
            releases,
            mapping_releases,
        )
    )
    assert agency_projection is not None
    assert missing_projection_keys == ()
    created_at = prebuild.generation_report["createdAt"]
    assert isinstance(created_at, str)

    legacy_graphs = generator._build_graphs(
        releases,
        mapping_releases=mapping_releases,
        include_projection=False,
    )
    try:
        legacy_validation = generator._validate_compiled_producer_output(
            releases,
            legacy_graphs,
            prebuild.compiled_rows,
            mapping_releases,
        )
        legacy_accounting = generator._plain(legacy_graphs.accounting)
        legacy_root = tmp_path / "legacy"
        legacy_result, legacy_manifest = generator._write_candidate_distribution(
            legacy_root / "distribution",
            legacy_graphs,
            releases=prebuild.pack_plans,
            created_at=created_at,
            compiled_validation=legacy_validation,
            construction_seeds=prebuild.construction_seeds,
            parquet_tables=legacy_root / "parquet-view",
            agency_projection=agency_projection,
        )
    finally:
        legacy_graphs.release()

    streamed = generator._stream_construct_graphs(
        list(releases),
        list(mapping_releases),
        prebuild=prebuild,
        spool_root=tmp_path / "stream-spool",
    )
    streamed_root = tmp_path / "streamed"
    streamed_result, streamed_manifest = generator._write_streamed_candidate_distribution(
        streamed_root / "distribution",
        streamed,
        prebuild.pack_plans,
        created_at=created_at,
        construction_seeds=prebuild.construction_seeds,
        parquet_tables=streamed_root / "parquet-view",
        agency_projection=agency_projection,
    )

    def files(root: Path) -> dict[str, bytes]:
        return {
            path.relative_to(root).as_posix(): path.read_bytes()
            for path in root.rglob("*")
            if path.is_file()
        }

    legacy_distribution = files(legacy_root / "distribution")
    streamed_distribution = files(streamed_root / "distribution")
    legacy_parquet = files(legacy_root / "parquet-view")
    streamed_parquet = files(streamed_root / "parquet-view")

    assert streamed.accounting == legacy_accounting
    assert streamed.compiled_validation == legacy_validation
    assert streamed_result["status"] == legacy_result["status"] == "passed"
    assert streamed_manifest == legacy_manifest
    assert streamed_manifest["counts"]["evidenceBindings"] > (
        streamed_manifest["counts"]["relationAssertions"]
    )
    assert {
        "atlas-acceptance.json",
        "atlas-construction-summary.json",
        "atlas-manifest.json",
        "atlas-producer-validation.json",
        "atlas-source-accounting.json",
    } <= set(legacy_distribution)
    assert streamed_distribution == legacy_distribution
    assert streamed_parquet == legacy_parquet
