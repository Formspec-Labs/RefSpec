"""Atlas 3 adapters for official publisher-authored mappings and endpoints."""

from __future__ import annotations

import importlib
import json
import shutil
import sys
from collections import Counter
from pathlib import Path
from types import SimpleNamespace

import pytest
from rdflib import URIRef
from rdflib.namespace import RDF, SKOS

from refspec.atlas import v3_registry_alignments as alignments
from refspec.atlas.v3_registry_vocabularies import load_eurovoc_4_24_releases
from refspec.atlas.v3_source_data import mapping_triple_digest
from refspec.registry import fast_topical as fast
from refspec.registry.eurovoc_lcsh_alignment import (
    EUROVOC_4_20_RELEASE_IRI,
    EUROVOC_LCSH_ALIGNMENT_SHA256,
    EXPECTED_PREDICATE_COUNTS,
)

SOURCE_ROOT = alignments.DEFAULT_SOURCE_ROOT
ROOT = Path(__file__).resolve().parents[1]
REQUIRED_FILES = (
    SOURCE_ROOT / alignments.LCSH_BULK_FILENAME,
    SOURCE_ROOT / "eurovoc-lcsh-alignment-20240711.rdf",
    SOURCE_ROOT / "eurovoc-lcsh-alignment-20240711-metadata.rdf",
    SOURCE_ROOT / "eurovoc-4.20-20240711-metadata.rdf",
    SOURCE_ROOT / "eurovoc-4.24-metadata.ttl",
    # The consolidated LCSH release's referenced-deprecated selection also
    # depends on the LC external-links archive and the Northwestern
    # MeSH-LCSH mapping (see v3_registry_alignments_lcsh.gather_referenced_lcsh_iris).
    SOURCE_ROOT / "lcsh-externallinks-2026-08-15.nt.zip",
    SOURCE_ROOT / "mesh-lcsh-mapping-20210325.zip",
)
HAS_OFFICIAL_SOURCES = all(path.is_file() for path in REQUIRED_FILES)
HAS_COMPLETE_EUROVOC = (SOURCE_ROOT / "eurovoc-4.24-skos-core.zip").is_file()


def _generator_module():
    sys.path.insert(0, str(ROOT / "tools"))
    try:
        return importlib.import_module("generate_atlas_v3_full")
    finally:
        sys.path.remove(str(ROOT / "tools"))


@pytest.fixture(scope="module")
def mapping_release():
    if not HAS_OFFICIAL_SOURCES:
        pytest.skip("official EuroVoc--LCSH alignment sources are not cached")
    return alignments.load_eurovoc_lcsh_mapping_release(Path(SOURCE_ROOT))


@pytest.fixture(scope="module")
def endpoint_release():
    if not HAS_OFFICIAL_SOURCES:
        pytest.skip("official LCSH bulk and EuroVoc alignment sources are not cached")
    return alignments.load_lcsh_consolidated_release(Path(SOURCE_ROOT))


@pytest.fixture(scope="module")
def eurovoc_releases():
    if not HAS_COMPLETE_EUROVOC:
        pytest.skip("official EuroVoc 4.24 source is not cached")
    return load_eurovoc_4_24_releases(Path(SOURCE_ROOT))


@pytest.fixture(scope="module")
def fast_mapping_release():
    required = (
        SOURCE_ROOT / fast.FAST_TOPICAL_NATIVE_BASE_PIN.filename,
        *(SOURCE_ROOT / pin.filename for pin in fast.FAST_TOPICAL_CHANGE_PINS),
        SOURCE_ROOT / "eurovoc-lcsh-alignment-20240711.rdf",
    )
    if not all(path.is_file() for path in required):
        pytest.skip("official FAST and LCSH alignment sources are not cached")
    return alignments.load_fast_lcsh_mapping_release(Path(SOURCE_ROOT))


@pytest.fixture(scope="module")
def ua_gao_mapping_release():
    return alignments.load_unified_agenda_gao_cra_priority_mapping_release(ROOT)


@pytest.mark.parametrize(
    "relative_path",
    (
        "tests/fixtures/unified_agenda_codes/reginfo-rin-data-ver10262011.xsd",
        ("tests/fixtures/gao_cra_form_codes/gao-cra-blank-form-rev-11-17-23-2026-08-15.pdf"),
        ("tests/fixtures/gao_cra_form_codes/gao-09-205-2009-04-20-2026-08-15.pdf"),
    ),
)
def test_ua_gao_priority_mapping_refuses_source_byte_drift(
    tmp_path: Path,
    relative_path: str,
) -> None:
    for fixture_group in ("unified_agenda_codes", "gao_cra_form_codes"):
        shutil.copytree(
            ROOT / "tests" / "fixtures" / fixture_group,
            tmp_path / "tests" / "fixtures" / fixture_group,
        )
    target = tmp_path / relative_path
    target.write_bytes(target.read_bytes() + b"drift")

    with pytest.raises(ValueError, match="input pin differs"):
        alignments.load_unified_agenda_gao_cra_priority_mapping_release(tmp_path)


def test_fast_default_served_set_is_computed_from_shipped_evidence(
    fast_mapping_release,
) -> None:
    generator = _generator_module()
    graph = generator._expected_mapping_asserted_graph((fast_mapping_release,))
    eligible_roles = {
        generator.RKAF.officialSourceMetadata,
        generator.RKAF.formalAdoptionEvent,
        generator.RKAF.structuralEvidence,
    }
    publisher_inputs = tuple(
        item.source_iri for item in fast_mapping_release.inputs if item.role in {"publisherBase", "publisherChange"}
    )

    def publisher_owns_fast_subject(binding, assertion) -> bool:
        record = graph.value(binding, generator.ATLAS.evidenceSourceRecord)
        locator = graph.value(record, generator.ATLAS.sourceLocator)
        payload_value = graph.value(record, generator.ATLAS.nativePayload)
        subject = graph.value(assertion, RDF.subject)
        if locator is None or payload_value is None or subject is None:
            return False
        publisher_claim = json.loads(str(payload_value)).get("publisherClaim", {})
        return (
            str(subject).startswith(fast.FAST_URI_BASE)
            and publisher_claim.get("subjectIri") == str(subject)
            and any(str(locator).startswith(source) for source in publisher_inputs)
        )

    default_served = {
        (
            str(graph.value(assertion, RDF.subject)),
            str(graph.value(assertion, RDF.predicate)),
            str(graph.value(assertion, RDF.object)),
        )
        for assertion in graph.subjects(RDF.type, generator.ATLAS.MappingAssertion)
        if any(
            graph.value(binding, generator.RKAF.evidenceRole) in eligible_roles
            and publisher_owns_fast_subject(binding, assertion)
            for binding in graph.subjects(generator.RKAF.bindsAssertion, assertion)
        )
    }

    assert len(default_served) == 602_459
    assert Counter(predicate for _, predicate, _ in default_served) == {
        str(SKOS.exactMatch): 252_527,
        str(SKOS.relatedMatch): 349_932,
    }
    assert default_served == {(row.subject, row.predicate, row.object) for row in fast_mapping_release.mappings}


def test_fast_inferred_mapping_delta_is_computed_before_build(
    mapping_release,
    fast_mapping_release,
) -> None:
    generator = _generator_module()

    def exact_triples(*releases):
        return frozenset(
            (URIRef(row.subject), URIRef(row.predicate), URIRef(row.object))
            for release in releases
            for row in release.mappings
            if row.predicate == str(SKOS.exactMatch)
        )

    baseline = generator.ATLAS_VALIDATE._build_exact_match_index_from_triples(exact_triples(mapping_release))
    with_fast = generator.ATLAS_VALIDATE._build_exact_match_index_from_triples(
        exact_triples(mapping_release, fast_mapping_release)
    )
    impact = fast_mapping_release.metadata["inferenceImpact"]

    assert baseline.inferred_count == 5_939
    assert with_fast.inferred_count == 765_537
    assert with_fast.inferred_count - baseline.inferred_count == 759_598
    assert impact["baselineInferredMappingCount"] == baseline.inferred_count
    assert impact["inferredMappingCount"] == with_fast.inferred_count
    assert impact["inferredMappingDelta"] == 759_598


def test_fast_lcsh_exact_sample_carries_the_full_adoption_chain(
    fast_mapping_release,
) -> None:
    mapping = next(row for row in fast_mapping_release.mappings if row.predicate == str(SKOS.exactMatch))
    (evidence,) = mapping.evidence
    publisher_claim = evidence.native_payload["publisherClaim"]

    assert evidence.review_warrant == "operatorAdoption"
    assert evidence.reviewer_iri == alignments.FAST_LCSH_ADOPTION_REVIEWER_IRI
    assert evidence.source_digest in {pin.sha256 for pin in fast_mapping_release.inputs[:-1]}
    assert evidence.source_locator.startswith(
        next(pin.source_iri for pin in fast_mapping_release.inputs if pin.sha256 == evidence.source_digest) + "#fast-"
    )
    assert publisher_claim["subjectIri"] == mapping.subject
    assert publisher_claim["objectIri"] == mapping.object
    assert publisher_claim["predicateIri"] == fast.FAST_SCHEMA_SAME_AS
    assert "<http://schema.org/sameAs>" in publisher_claim["nativeStatement"]
    assert publisher_claim["sourceRecordDigest"].startswith("sha256:")
    assert evidence.native_payload["operatorAdoption"] == {
        "adoptedBy": alignments.FAST_LCSH_ADOPTION_REVIEWER_IRI,
        "fromPredicateIri": fast.FAST_SCHEMA_SAME_AS,
        "toPredicateIri": str(SKOS.exactMatch),
    }


def test_fast_lcsh_mapping_refuses_endpoint_selection_drift(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The target endpoint is now the consolidated LCSH release, so this drift
    # check tampers with its own pinned bulk file -- verified before it ever
    # reaches the four referenced-IRI sources.
    monkeypatch.setattr(
        alignments,
        "load_fast_topical_release",
        lambda _root: SimpleNamespace(),
    )
    (tmp_path / alignments.LCSH_BULK_FILENAME).write_bytes(b"not the pinned LCSH bulk artifact")

    with pytest.raises(ValueError, match="input pin differs"):
        alignments.load_fast_lcsh_mapping_release(tmp_path)


def test_fast_lcsh_mapping_refuses_source_byte_drift(tmp_path: Path) -> None:
    (tmp_path / fast.FAST_TOPICAL_NATIVE_BASE_PIN.filename).write_bytes(b"not the pinned OCLC archive")

    with pytest.raises(fast.FASTTopicalSourceDriftError, match="byte length drift"):
        alignments.load_fast_lcsh_mapping_release(tmp_path)


def test_fast_lcsh_release_pins_joinable_and_unemitted_counts(
    fast_mapping_release,
    endpoint_release,
) -> None:
    release = fast_mapping_release
    assert release.key == "fast-lcsh-adopted-2026-08-15"
    assert release.ring == "subject"
    assert release.scope == "captureSubset"
    assert release.source_release_digest == ("sha256:45b6e92d27dfe56ac54e0567051d75edfe5b760d78d3f2a736328e0c11878c54")
    assert release.source_release_iri.endswith("45b6e92d27dfe56ac54e0567051d75edfe5b760d78d3f2a736328e0c11878c54")
    assert {pin.role for pin in release.inputs} == {
        "publisherBase",
        "publisherChange",
    }
    assert len(release.mappings) == 602_459
    assert Counter(row.predicate for row in release.mappings) == {
        str(SKOS.exactMatch): 252_527,
        str(SKOS.relatedMatch): 349_932,
    }
    endpoint_iris = {resource.iri for resource in endpoint_release.resources}
    mapping_targets = {row.object for row in release.mappings}
    assert mapping_targets <= endpoint_iris
    assert len(mapping_targets) == 254_453
    assert release.metadata["unemittedSchemaSameAsCount"] == 8
    assert release.metadata["unemittedSkosRelatedMatchCount"] == 0
    assert release.metadata["recordsWithLcshLinks"] == 427_423
    assert release.metadata["sourceIdentifierCount"] == 0
    assert all(not resource.identifiers for resource in endpoint_release.resources)
    assert release.metadata["assertionComposition"] == {
        "adoptedExactMatch": {
            "assertionCount": 252_527,
            "endpointSelection": "target is a member of the consolidated LCSH release",
            "evidenceWarrant": "operatorAdoption",
            "predicateIri": str(SKOS.exactMatch),
            "publisherStatement": ("OCLC schema:sameAs carried verbatim in each evidence record"),
        },
        "publisherVerbatimRelatedMatch": {
            "assertionCount": 349_932,
            "evidenceWarrant": "publisherAssertion",
            "marcQualifier": "$w nnd",
            "predicateIri": str(SKOS.relatedMatch),
            "promotion": "none",
        },
        "unemittedPublisherLinks": {
            "schemaSameAsCount": 8,
            "skosRelatedMatchCount": 0,
        },
    }
    assert "defaultServedPredicateIri" not in release.metadata
    assert "publisherRelatedMatchIsDefault" not in release.metadata


def test_fast_lcsh_s46_widened_scope_has_overlap_but_zero_component_conflicts(
    fast_mapping_release,
) -> None:
    """REF-040's own prediction (REF-035) came true: widening the endpoint
    reopened subject overlap between exactMatch and relatedMatch. The release
    still proves zero SKOS S46 exact-match-component conflicts over its own
    emitted pairs."""

    exact_subjects = {row.subject for row in fast_mapping_release.mappings if row.predicate == str(SKOS.exactMatch)}
    related_subjects = {row.subject for row in fast_mapping_release.mappings if row.predicate == str(SKOS.relatedMatch)}

    assert len(exact_subjects) == alignments.FAST_LCSH_EXACT_SUBJECT_COUNT == 252_527
    assert len(related_subjects) == (alignments.FAST_LCSH_RELATED_SUBJECT_COUNT) == 174_900
    assert len(exact_subjects & related_subjects) == alignments.FAST_LCSH_SUBJECT_PREDICATE_OVERLAP_COUNT == 12
    s46 = fast_mapping_release.metadata["s46Safety"]
    assert s46["conflictCount"] == 0
    assert s46["exactMatchSubjectCount"] == 252_527
    assert s46["relatedMatchSubjectCount"] == 174_900
    assert s46["subjectPredicateOverlapCount"] == 12
    assert s46["status"] == "measuredZeroConflictsOverThisReleasesOwnExactMatchComponents"


def test_fast_nnd_links_never_become_exact_matches(fast_mapping_release) -> None:
    nnd = [
        row
        for row in fast_mapping_release.mappings
        if "$wnnd" in row.evidence[0].native_payload["publisherClaim"]["nativeStatement"]
    ]
    assert nnd
    assert all(row.predicate == str(SKOS.relatedMatch) for row in nnd)
    assert all(
        row.evidence[0].review_warrant == "publisherAssertion"
        and row.evidence[0].native_payload["publisherClaim"]["predicateIri"] == fast.FAST_SKOS_RELATED_MATCH
        for row in nnd
    )
    assert all(
        row.evidence[0].native_payload["publisherClaim"]["predicateIri"] == fast.FAST_SCHEMA_SAME_AS
        for row in fast_mapping_release.mappings
        if row.predicate == str(SKOS.exactMatch)
    )


def test_new_mapping_endpoints_pass_all_refusal_guards_and_mint_no_identifiers(
    ua_gao_mapping_release,
    fast_mapping_release,
) -> None:
    generator = _generator_module()

    relation_policies = generator.ATLAS_VALIDATE._relation_policies()
    subject_mappings = relation_policies[generator.ATLAS.subject][generator.ATLAS.MappingAssertion]
    value_mappings = relation_policies[generator.ATLAS.value][generator.ATLAS.MappingAssertion]
    assert {SKOS.exactMatch, SKOS.relatedMatch} <= subject_mappings
    assert generator.ATLAS.equivalentValue in value_mappings

    ua_graph = generator._expected_mapping_asserted_graph((ua_gao_mapping_release,))
    ua_assertions = set(ua_graph.subjects(RDF.type, generator.ATLAS.MappingAssertion))
    assert len(ua_assertions) == 5
    assert all(ua_graph.value(assertion, generator.RKAF.hasEffectivePeriod) is not None for assertion in ua_assertions)
    assert len(set(ua_graph.subjects(RDF.type, generator.RKAF.EvidenceBinding))) == 15

    fast_samples = {
        predicate: next(mapping for mapping in fast_mapping_release.mappings if mapping.predicate == predicate)
        for predicate in (str(SKOS.exactMatch), str(SKOS.relatedMatch))
    }
    for mapping in fast_samples.values():
        evidence = mapping.evidence[0]
        locator, digest, payload = generator._mapping_evidence(
            fast_mapping_release,
            mapping,
            evidence,
        )
        assert str(locator) == evidence.source_locator
        assert digest == evidence.source_digest
        assert payload["mappingTripleDigest"] == mapping_triple_digest(
            subject_iri=mapping.subject,
            predicate_iri=mapping.predicate,
            object_iri=mapping.object,
        )
        assert generator._mapping_review_method(evidence.review_warrant) == (evidence.review_warrant)

    for release in (ua_gao_mapping_release, fast_mapping_release):
        endpoint_iris = {endpoint for mapping in release.mappings for endpoint in (mapping.subject, mapping.object)}
        shaped = SimpleNamespace(
            spec=SimpleNamespace(
                key=release.key,
                logical_path=release.inputs[0].logical_path,
                input_pins=release.inputs,
            ),
            scheme_iri=f"urn:ref:atlas-mapping-endpoints:{release.key}",
            resources=tuple(SimpleNamespace(iri=iri) for iri in endpoint_iris),
        )
        generator._refuse_registrant_population_release(shaped)
        generator._refuse_document_population_release(shaped)
        generator._refuse_observed_inventory_release(shaped)

    # Mapping releases carry only endpoint IRIs and source records. The two
    # source adapters keep publisher ids as notations/native payload, and mint
    # no RegistryIdentifier rows that could name an undeclared authority.
    assert all(
        "identifiers" not in evidence.native_payload
        for release in (ua_gao_mapping_release, fast_mapping_release)
        for mapping in release.mappings
        for evidence in mapping.evidence
    )
    assert ua_gao_mapping_release.metadata["sourceEndpointIdentifierCount"] == 0
    assert fast_mapping_release.metadata["sourceIdentifierCount"] == 0


def test_new_mapping_releases_assert_each_direction_once(
    ua_gao_mapping_release,
    fast_mapping_release,
) -> None:
    for release in (ua_gao_mapping_release, fast_mapping_release):
        direct = {(row.subject, row.predicate, row.object) for row in release.mappings}
        assert len(direct) == len(release.mappings)
        assert all((obj, predicate, subject) not in direct for subject, predicate, obj in direct)


def test_ua_gao_priority_evidence_binds_endpoints_and_institutional_bridge(
    ua_gao_mapping_release,
) -> None:
    for mapping in ua_gao_mapping_release.mappings:
        assert len(mapping.evidence) == 3
        subject_evidence, object_evidence, bridge_evidence = mapping.evidence
        assert subject_evidence.review_warrant == "humanReview"
        assert object_evidence.review_warrant == "humanReview"
        assert bridge_evidence.review_warrant == "operatorAdoption"
        assert subject_evidence.source_digest == ua_gao_mapping_release.inputs[0].sha256
        assert object_evidence.source_digest == ua_gao_mapping_release.inputs[1].sha256
        assert subject_evidence.source_locator.startswith(ua_gao_mapping_release.inputs[0].source_iri + "#")
        assert object_evidence.source_locator.startswith(ua_gao_mapping_release.inputs[1].source_iri + "#")
        subject_record = subject_evidence.native_payload["endpointRecord"]
        object_record = object_evidence.native_payload["endpointRecord"]
        assert "One of the following options" in (subject_record["nativePayload"]["documentation"])
        assert subject_record["nativePayload"]["sourceElementName"] == ("PRIORITY_CATEGORY")
        assert object_record["nativePayload"]["formNumber"] == "GAO Form 41217"
        assert object_record["nativePayload"]["formItem"] == "8"
        assert object_record["nativePayload"]["optionText"]
        assert bridge_evidence.source_digest == (alignments.UA_GAO_INSTITUTIONAL_BRIDGE_SHA256)
        assert bridge_evidence.source_locator.startswith(alignments.UA_GAO_INSTITUTIONAL_BRIDGE_URL + "#")
        assert bridge_evidence.native_payload["decisionBasis"] == ("gaoInstitutionalTaxonomyReuse")
        assert bridge_evidence.native_payload["institutionalBridge"] == {
            "reportNumber": "GAO-09-205",
            "sourceDigest": alignments.UA_GAO_INSTITUTIONAL_BRIDGE_SHA256,
            "sourceIri": alignments.UA_GAO_INSTITUTIONAL_BRIDGE_URL,
            "tie": (
                "GAO says its standardized CRA form supplies its Federal Rules "
                "Database, uses Other Significant as a stored priority, and "
                "defines that category by the Unified Agenda."
            ),
        }
        for evidence in mapping.evidence:
            assert evidence.native_payload["decisionBasis"] == ("gaoInstitutionalTaxonomyReuse")
            assert "exactPublisherLabel" not in evidence.native_payload.values()
            assert evidence.native_payload["mappingTripleDigest"] == (
                mapping_triple_digest(
                    subject_iri=mapping.subject,
                    predicate_iri=mapping.predicate,
                    object_iri=mapping.object,
                )
            )


def test_ua_gao_priority_records_non_adoptions_and_unmatched_value(
    ua_gao_mapping_release,
) -> None:
    decisions = ua_gao_mapping_release.metadata["candidateDecisions"]
    assert len(decisions) == 6
    abbreviation = next(row for row in decisions if row["subjectLabel"] == "Info./Admin./Other")
    institutional_variant = next(row for row in decisions if row["subjectLabel"] == "Other Significant")
    unmatched = next(row for row in decisions if row["subjectLabel"] == "Not Major")

    assert abbreviation["decision"] == "adopted"
    assert "corroborate" in abbreviation["reason"]
    assert institutional_variant == {
        "decision": "adopted",
        "objectLabel": "Significant",
        "predicateIri": alignments.ATLAS_EQUIVALENT_VALUE,
        "reason": (
            "GAO-09-205 uses Other Significant for a priority stored in its "
            "CRA-form-backed database and defines that category by the Unified "
            "Agenda; the differing labels are an institutional variant, not the "
            "basis for equivalence"
        ),
        "subjectLabel": "Other Significant",
    }
    assert unmatched["decision"] == "unmatched"
    # The wire carries no nulls: an unmatched candidate omits objectLabel.
    assert "objectLabel" not in unmatched
    assert "outside that taxonomy" in unmatched["reason"]
    assert "neither publisher" not in unmatched["reason"]
    assert "lexical equality does not establish" in (ua_gao_mapping_release.metadata["lexicalEvidenceRole"])


def test_ua_gao_priority_release_pins_all_adopted_pairs(
    ua_gao_mapping_release,
) -> None:
    release = ua_gao_mapping_release
    expected_pairs = {
        (
            ("urn:ref:source-concept:v2:unified-agenda-priority-category:019fc90d-39b8-7ef1-ad04-b4acf91fa67e"),
            ("urn:ref:source-concept:v2:gao-cra-priority-of-regulation:01a005b6-5ac0-7702-ae8a-28a97b649e47"),
        ),
        (
            ("urn:ref:source-concept:v2:unified-agenda-priority-category:019fc90d-39b8-784d-8c4f-f7b5d4c317a9"),
            ("urn:ref:source-concept:v2:gao-cra-priority-of-regulation:01a005b6-5ac0-7259-a561-bfdf6544c049"),
        ),
        (
            ("urn:ref:source-concept:v2:unified-agenda-priority-category:019fc90d-39b8-71b5-a1ca-3ddd5f402e16"),
            ("urn:ref:source-concept:v2:gao-cra-priority-of-regulation:01a005b6-5ac0-7514-a1b9-84e637cce4f5"),
        ),
        (
            ("urn:ref:source-concept:v2:unified-agenda-priority-category:019fc90d-39b8-79bc-9507-3e09505197e0"),
            ("urn:ref:source-concept:v2:gao-cra-priority-of-regulation:01a005b6-5ac0-764b-878b-039fbbc2452e"),
        ),
        (
            ("urn:ref:source-concept:v2:unified-agenda-priority-category:019fc90d-39b8-7c37-a150-07ae1667db99"),
            ("urn:ref:source-concept:v2:gao-cra-priority-of-regulation:01a005b6-5ac0-7239-93af-38d524510967"),
        ),
    }

    assert release.key == "unified-agenda-gao-cra-priority-2026-08-15"
    assert release.ring == "value"
    assert release.scope == "captureSubset"
    assert release.source_release_digest == ("sha256:01c704f758bbd4b339dd8ad30da25fdc25b24e35b397db73d67daf4f55e02e91")
    assert [item.role for item in release.inputs] == [
        "publisherSubjectValues",
        "publisherObjectValues",
        "institutionalTaxonomyBridge",
    ]
    assert len(release.mappings) == 5
    assert {(row.subject, row.object) for row in release.mappings} == expected_pairs
    assert {row.predicate for row in release.mappings} == {alignments.ATLAS_EQUIVALENT_VALUE}
    assert {row.effective_from for row in release.mappings} == {"2026-08-15"}
    assert {row.effective_through for row in release.mappings} == {None}


def test_mapping_release_is_separately_pinned_evidence_backed_input(
    mapping_release,
) -> None:
    assert mapping_release.key == "eurovoc-lcsh-alignment-20240711"
    assert mapping_release.resource_id == "eurovoc-lcsh-alignment"
    assert mapping_release.issued == "2024-07-11"
    assert mapping_release.ring == "subject"
    assert mapping_release.scope == "publisherRelease"
    assert mapping_release.source_release_digest == EUROVOC_LCSH_ALIGNMENT_SHA256
    assert mapping_release.editorial_policy == (alignments.EUROVOC_LCSH_MAPPING_POLICY_PAYLOAD)
    assert [source.role for source in mapping_release.inputs] == [
        "publisherAlignment",
        "publisherAlignmentReleaseMetadata",
        "publisherSourceReleaseMetadata",
        "currentPublisherLinksetMetadata",
    ]
    assert {row.asserted_at for row in mapping_release.mappings} == {alignments.ATLAS_MAPPING_ADOPTION_DECIDED_AT}
    assert {evidence.review_warrant for row in mapping_release.mappings for evidence in row.evidence} == {
        "operatorAdoption"
    }
    assert {evidence.reviewer_iri for row in mapping_release.mappings for evidence in row.evidence} == {
        alignments.ATLAS_MAPPING_ADOPTION_REVIEWER_IRI
    }
    assert {evidence.attested_at for row in mapping_release.mappings for evidence in row.evidence} == {
        alignments.ATLAS_MAPPING_ADOPTION_DECIDED_AT
    }
    assert mapping_release.metadata["adoptionDecision"] == "atlasOperatorAdoption"
    assert mapping_release.metadata["currentEuroVocRelease"] == "4.24"
    assert mapping_release.metadata["publisherEuroVocVersion"] == "4.20"
    assert mapping_release.metadata["publisherEuroVocRelease"] == (EUROVOC_4_20_RELEASE_IRI)
    assert mapping_release.metadata["lcshTargetRelease"] == "unspecifiedByPublisher"
    assert mapping_release.metadata["publisherRequalificationForEuroVoc4_24"] is False


def test_mapping_release_preserves_only_the_2003_direct_publisher_triples(
    mapping_release,
) -> None:
    assert len(mapping_release.mappings) == alignments.EUROVOC_LCSH_MAPPING_COUNT
    assert len({(row.subject, row.predicate, row.object) for row in mapping_release.mappings}) == 2_003
    assert Counter(row.predicate for row in mapping_release.mappings) == (EXPECTED_PREDICATE_COUNTS)
    assert len({row.subject for row in mapping_release.mappings}) == 1_829
    assert len({row.object for row in mapping_release.mappings}) == 1_966
    assert {row.predicate for row in mapping_release.mappings} == {
        str(SKOS.closeMatch),
        str(SKOS.exactMatch),
    }
    assert all(
        len(row.evidence) == 1
        and row.evidence[0].native_payload
        == {
            "currentEuroVocLinksetCounts": dict(EXPECTED_PREDICATE_COUNTS),
            "currentEuroVocLinksetMetadataDigest": mapping_release.inputs[3].sha256,
            "currentEuroVocRelease": "4.24",
            "currentMetadataRequalifiesIndividualPairs": False,
            "mappingTripleDigest": mapping_triple_digest(
                subject_iri=row.subject,
                predicate_iri=row.predicate,
                object_iri=row.object,
            ),
            "objectIri": row.object,
            "predicateIri": row.predicate,
            "publisherAlignmentDigest": EUROVOC_LCSH_ALIGNMENT_SHA256,
            "publisherAlignmentIssued": "2024-07-11",
            "publisherAlignmentRelease": mapping_release.source_release_iri,
            "publisherAlignmentVersion": "20240711-0",
            "publisherEuroVocRelease": EUROVOC_4_20_RELEASE_IRI,
            "publisherEuroVocVersion": "4.20",
            "publisherLcshRelease": "unspecifiedByPublisher",
            "subjectIri": row.subject,
        }
        and row.evidence[0].source_digest == EUROVOC_LCSH_ALIGNMENT_SHA256
        and row.evidence[0].source_locator == mapping_release.inputs[0].source_iri
        for row in mapping_release.mappings
    )


def test_mapping_claims_pin_both_exact_atlas_endpoint_releases(mapping_release) -> None:
    # The publisher aligned one EuroVoc domain alongside 1,702 thesaurus
    # concepts, and Atlas loads domains as their own release, so both endpoint
    # releases legitimately appear. Assert the split rather than a single value.
    subject_releases = {row.subject_atlas_release_iri for row in mapping_release.mappings}
    assert subject_releases == {
        alignments.EUROVOC_ATLAS_RELEASE_IRI,
        alignments.EUROVOC_DOMAINS_ATLAS_RELEASE_IRI,
    }
    domain_rows = {
        row.subject
        for row in mapping_release.mappings
        if row.subject_atlas_release_iri == alignments.EUROVOC_DOMAINS_ATLAS_RELEASE_IRI
    }
    assert domain_rows == set(alignments.EUROVOC_DOMAIN_SUBJECT_IRIS)
    assert {row.object_atlas_release_iri for row in mapping_release.mappings} == {
        alignments.LCSH_CONSOLIDATED_ATLAS_RELEASE_IRI
    }


def test_lcsh_endpoint_release_covers_every_alignment_target(endpoint_release) -> None:
    # REF-040 consolidated the three per-consumer LCSH endpoint releases
    # (this one among them) into one release: every current LCSH heading
    # plus only the deprecated headings a held mapping candidate references.
    assert endpoint_release.key == "lcsh-subjects-consolidated-2026-08-06"
    assert endpoint_release.scope == "captureSubset"
    assert endpoint_release.source_release_digest == (
        "sha256:572fe30b22ee032849e3bf608f8232bde845774309a48a9804b4ba71ff900159"
    )
    assert len(endpoint_release.resources) == 514_837
    assert len({resource.iri for resource in endpoint_release.resources}) == 514_837
    assert len(endpoint_release.relations) == 301_442
    assert endpoint_release.metadata["linesScanned"] == 521_055
    assert endpoint_release.metadata["completePublisherRelease"] is False
    assert endpoint_release.metadata["currentHeadingCount"] == 513_210
    assert endpoint_release.metadata["deprecatedHeadingsRetainedCount"] == 1_627
    assert endpoint_release.metadata["deprecatedTotalInPublisherFile"] == 7_845
    # The alignment's 1,966 endpoints are a subset of the consolidated release.
    alignment_iris = alignments.parse_eurovoc_lcsh_alignment_file(
        SOURCE_ROOT / "eurovoc-lcsh-alignment-20240711.rdf"
    ).lcsh_concept_iris
    assert alignment_iris <= {resource.iri for resource in endpoint_release.resources}


def test_lcsh_endpoint_release_is_english_only_and_keeps_publisher_iris_without_lccn(
    endpoint_release,
) -> None:
    assert sum(len(resource.labels) for resource in endpoint_release.resources) == 910_544
    assert endpoint_release.dropped_label_count == 0
    assert all(label.language == "en" for resource in endpoint_release.resources for label in resource.labels)
    assert all(
        sum(label.role == "preferred" for label in resource.labels) == 1 for resource in endpoint_release.resources
    )
    without_lccn = [resource for resource in endpoint_release.resources if not resource.notations]
    assert len(without_lccn) == 46_831
    assert all(resource.native_payload["lccn"] is None for resource in without_lccn)
    assert all(resource.iri.startswith("http://id.loc.gov/authorities/subjects/") for resource in without_lccn)


def test_lcsh_endpoint_release_preserves_all_authority_classes(endpoint_release) -> None:
    assert endpoint_release.metadata["authorityTypeCounts"] == {
        "madsrdf:ComplexSubject": 197_347,
        "madsrdf:ConferenceName": 1,
        "madsrdf:CorporateName": 9_873,
        "madsrdf:FamilyName": 24_381,
        "madsrdf:GenreForm": 426,
        "madsrdf:Geographic": 55_620,
        "madsrdf:HierarchicalGeographic": 41_223,
        "madsrdf:NameTitle": 22,
        "madsrdf:PersonalName": 1,
        "madsrdf:Temporal": 34,
        "madsrdf:Title": 87,
        "madsrdf:Topic": 185_822,
    }
    resource_iris = {resource.iri for resource in endpoint_release.resources}
    assert all(
        relation.subject in resource_iris
        and relation.object in resource_iris
        and relation.predicate == str(SKOS.broader)
        for relation in endpoint_release.relations
    )


def test_mapping_targets_match_the_exact_lcsh_endpoint_release(
    mapping_release,
    endpoint_release,
) -> None:
    # The consolidated release now backs every held LCSH mapping, not only
    # this one, so its targets are a subset rather than an exact match.
    assert {row.object for row in mapping_release.mappings} <= {resource.iri for resource in endpoint_release.resources}


def test_mapping_subjects_match_the_complete_eurovoc_release_partitions(
    mapping_release,
    eurovoc_releases,
) -> None:
    resources_by_release = {
        release.key: {resource.iri for resource in release.resources} for release in eurovoc_releases
    }
    mapping_subjects = {row.subject for row in mapping_release.mappings}

    assert mapping_subjects <= set().union(*resources_by_release.values())
    assert mapping_subjects & resources_by_release["eurovoc-domains-4.24"] == {"http://eurovoc.europa.eu/100162"}
