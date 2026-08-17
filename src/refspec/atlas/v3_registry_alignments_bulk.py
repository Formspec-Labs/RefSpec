"""Atlas 3 mapping releases backed by bulk FAST and EuroVoc alignments."""

from __future__ import annotations

from collections.abc import Collection, Mapping
from pathlib import Path
from types import MappingProxyType

from rdflib.namespace import SKOS

from refspec.atlas.v3_registry_alignments import (
    EUROVOC_ATLAS_RELEASE_IRI,
    EUROVOC_DOMAINS_ATLAS_RELEASE_IRI,
    FAST_LCSH_ADOPTION_REVIEWER_IRI,
    FAST_LCSH_PUBLISHER_ASSERTION_REVIEWER_IRI,
    GEMET_EUROVOC_S46_REFUSALS,
    LCSH_ALIGNMENT_ENDPOINT_ATLAS_RELEASE_IRI,
)
from refspec.atlas.v3_registry_large import load_fast_topical_release
from refspec.atlas.v3_registry_selection import normalize_only_keys, wants_group
from refspec.atlas.v3_registry_vocabularies import (
    load_eurovoc_4_24_releases,
    load_gemet_release,
    load_mesh_2026_release,
)
from refspec.atlas.v3_source_data import (
    RegistryInputPin,
    RegistryLabel,
    RegistryMapping,
    RegistryMappingEvidence,
    RegistryMappingRelease,
    RegistryRelation,
    RegistryRelease,
    RegistryResource,
    canonical_digest,
    mapping_triple_digest,
)
from refspec.registry import oclc_fast_external_links as fast_bulk
from refspec.registry.eurovoc_alignment_portfolio import (
    EUROVOC_ALIGNMENT_CATALOGUE_URL,
    EUROVOC_ALIGNMENT_GENERAL_REUSE_BASIS_URL,
    EUROVOC_ALIGNMENT_LICENSE_STATEMENT,
    EUROVOC_ALIGNMENT_THIRD_PARTY_RIGHTS_EXCLUSION,
    EXPECTED_COMPLETE_CATALOGUE_ASSERTION_COUNT,
    EXPECTED_PORTFOLIO_ASSERTION_COUNT,
    EuroVocAlignmentCapture,
    EuroVocAlignmentPin,
    EuroVocAlignmentPortfolio,
    load_eurovoc_alignment_portfolio,
)
from refspec.registry.eurovoc_lcsh_alignment import (
    EUROVOC_LCSH_ALIGNMENT_BYTE_LENGTH,
    EUROVOC_LCSH_ALIGNMENT_FILENAME,
    EUROVOC_LCSH_ALIGNMENT_SHA256,
    EUROVOC_LCSH_ALIGNMENT_URL,
    parse_eurovoc_lcsh_alignment_file,
)
from refspec.registry.fast_topical import FAST_SCHEMA_SAME_AS, FAST_SKOS_RELATED_MATCH

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_SOURCE_ROOT = REPOSITORY_ROOT / "output" / "registry-real-data-sources"

FAST_BULK_MAPPING_DECIDED_AT = "2026-08-15T00:00:00+00:00"
FAST_BULK_EXPECTED_CURRENT_COUNT = 64_464
FAST_BULK_EXPECTED_HELD_COUNT = 64_461
FAST_BULK_EXPECTED_OVERLAP_COUNT = 64_452
FAST_BULK_EXPECTED_DELTA_COUNT = 9
FAST_BULK_EXPECTED_CURRENT_ONLY_COUNT = 12
FAST_BULK_EXPECTED_SELECTED_EXTERNAL_SUBJECT_STATEMENT_COUNT = 1_192
FAST_BULK_EXPECTED_SELECTED_EXTERNAL_SUBJECT_UNIQUE_COUNT = 1_191
FAST_SEE_ALSO_ENDPOINT_RELEASE_KEY = "fast-bulk-see-also-endpoints-2026-07-27"
FAST_SEE_ALSO_ENDPOINT_ATLAS_RELEASE_IRI = "urn:ref:atlas-release:3:fast-topical:bulk-see-also-endpoints:2026-07-27"
FAST_SEE_ALSO_INTERNAL_ASSERTION_COUNT = 78_981
FAST_SEE_ALSO_WIKIPEDIA_ASSERTION_COUNT = 76_190
FAST_SEE_ALSO_ENDPOINT_COUNT = 45_929
FAST_SEE_ALSO_MISSING_ENDPOINT_COUNT = 668
FAST_SEE_ALSO_CONTENT_BACKED_ASSERTION_COUNT = 47_049
FAST_SEE_ALSO_EMITTED_ASSERTION_COUNT = 0
FAST_SEE_ALSO_MISSING_ENDPOINT_ASSERTION_COUNT = 31_932
FAST_SEE_ALSO_S27_CONFLICT_PAIR_COUNT = 0
FAST_SEE_ALSO_S27_CONFLICT_PAIR_DIGEST = "sha256:37517e5f3dc66819f61f5a7bb8ace1921282415f10551d2defa5c3eb0985b570"

FAST_BULK_DELTA_CLAIMS = frozenset(
    {
        (
            "http://id.worldcat.org/fast/1023619",
            str(SKOS.relatedMatch),
            "http://id.loc.gov/authorities/subjects/sh2002006218",
        ),
        (
            "http://id.worldcat.org/fast/1053064",
            str(SKOS.relatedMatch),
            "http://id.loc.gov/authorities/subjects/sh2002011487",
        ),
        (
            "http://id.worldcat.org/fast/1053067",
            str(SKOS.relatedMatch),
            "http://id.loc.gov/authorities/subjects/sh99005039",
        ),
        (
            "http://id.worldcat.org/fast/1086592",
            str(SKOS.relatedMatch),
            "http://id.loc.gov/authorities/subjects/sh2002011487",
        ),
        (
            "http://id.worldcat.org/fast/1086596",
            str(SKOS.relatedMatch),
            "http://id.loc.gov/authorities/subjects/sh99004998",
        ),
        (
            "http://id.worldcat.org/fast/1086597",
            str(SKOS.relatedMatch),
            "http://id.loc.gov/authorities/subjects/sh99005758",
        ),
        (
            "http://id.worldcat.org/fast/1086600",
            str(SKOS.relatedMatch),
            "http://id.loc.gov/authorities/subjects/sh2002011487",
        ),
        (
            "http://id.worldcat.org/fast/822259",
            str(SKOS.relatedMatch),
            "http://id.loc.gov/authorities/subjects/sh99005039",
        ),
        (
            "http://id.worldcat.org/fast/908105",
            str(SKOS.relatedMatch),
            "http://id.loc.gov/authorities/subjects/sh2002006218",
        ),
    }
)

EUROVOC_GEMET_MAPPING_REVIEWER_IRI = "urn:ref:atlas-source-descriptor:eurovoc-alignment-gemet"
EUROVOC_MESH_MAPPING_REVIEWER_IRI = "urn:ref:atlas-source-descriptor:eurovoc-alignment-mesh"
MESH_HTTP_IRI_PREFIX = "http://id.nlm.nih.gov/mesh/"
MESH_HTTPS_IRI_PREFIX = "https://id.nlm.nih.gov/mesh/"
GEMET_ATLAS_RELEASE_IRI = "urn:ref:atlas-release:3:gemet:4.2.3"
MESH_ATLAS_RELEASE_IRI = "urn:ref:atlas-release:3:mesh-descriptors:2026"

FAST_BULK_MAPPING_POLICY = MappingProxyType(
    {
        "admission": (
            "retain OCLC schema:sameAs only through the recorded exactMatch operator adoption; "
            "retain skos:relatedMatch verbatim; the separate seeAlso endpoint release preserves endpoint "
            "content but emits no rdfs:seeAlso relation because Atlas 3.1 has no matching semantic predicate; "
            "refuse owl:sameAs"
        ),
        "direction": "one OCLC assertion in its published FAST-to-target direction; no inverse",
        "reconciliation": (
            "emit only held-endpoint bulk claims absent from the later MARC-derived FAST mapping release"
        ),
        "version": "atlas-3-fast-bulk-external-links-delta-v2",
    }
)
EUROVOC_PORTFOLIO_MAPPING_POLICY = MappingProxyType(
    {
        "admission": (
            "carry direct publisher SKOS mapping predicates verbatim for exact held "
            "endpoints, except frozen non-exact GEMET claims that conflict with the "
            "combined exactMatch components under SKOS S46"
        ),
        "direction": "one Publications Office assertion in its published EuroVoc-to-target direction; no inverse",
        "externalEndpoints": "capture and count; do not emit until the exact target resource is loaded",
        "version": "atlas-3-eurovoc-alignment-portfolio-v2",
    }
)
FAST_SEE_ALSO_RELATION_POLICY = MappingProxyType(
    {
        "admission": (
            "retain publisher content for both FAST endpoints selected by topical rdfs:seeAlso; emit no "
            "relation because rdfs:seeAlso is navigational and none of the held pairs has the hierarchy path "
            "required for atlas:thesaurusRelated"
        ),
        "direction": "preserve OCLC's published direction; no inverse and no closure",
        "refusal": (
            "all rdfs:seeAlso links remain counted source navigation; owl:sameAs remains refused; Wikipedia "
            "anyURI targets and unlabeled FAST targets are counted but receive no target resource"
        ),
        "version": "atlas-3-fast-bulk-see-also-navigation-v2",
    }
)

BULK_REGISTRY_MAPPING_RELEASE_KEYS = frozenset(
    {
        "fast-bulk-external-links-delta-2026-07-27",
        "eurovoc-gemet-alignment-20201218",
        "eurovoc-mesh-alignment-20171215",
    }
)
BULK_REGISTRY_ALIGNMENT_ENDPOINT_RELEASE_KEYS = frozenset({FAST_SEE_ALSO_ENDPOINT_RELEASE_KEY})


def _source_capture_payload(
    pin: RegistryInputPin,
    *,
    retrieved_at: str,
    source_version_note: str,
) -> dict[str, object]:
    return {
        "byteLength": pin.byte_length,
        "retrievedAt": retrieved_at,
        "sha256": pin.sha256,
        "sourceUrl": pin.source_iri,
        "sourceVersionNote": source_version_note,
    }


def _input_set_digest(inputs: tuple[RegistryInputPin, ...], roles: frozenset[str]) -> str:
    return canonical_digest(
        [
            {
                "byteLength": pin.byte_length,
                "role": pin.role,
                "sha256": pin.sha256,
                "sourceIri": pin.source_iri,
            }
            for pin in inputs
            if pin.role in roles
        ]
    )


def _claim_predicate_counts(claims: Collection[tuple[str, str, str]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for _subject, predicate, _object in claims:
        counts[predicate] = counts.get(predicate, 0) + 1
    return dict(sorted(counts.items()))


def _fast_bulk_input(source_root: Path) -> RegistryInputPin:
    return RegistryInputPin(
        path=Path(source_root) / fast_bulk.FAST_EXTERNAL_LINKS_FILENAME,
        logical_path=f"refspec/output/registry-real-data-sources/{fast_bulk.FAST_EXTERNAL_LINKS_FILENAME}",
        sha256=fast_bulk.FAST_EXTERNAL_LINKS_SHA256,
        byte_length=fast_bulk.FAST_EXTERNAL_LINKS_BYTE_LENGTH,
        source_iri=fast_bulk.FAST_EXTERNAL_LINKS_SOURCE_URL,
        role="publisherBulkExternalLinks",
    )


def _lcsh_endpoint_input(source_root: Path) -> RegistryInputPin:
    return RegistryInputPin(
        path=Path(source_root) / EUROVOC_LCSH_ALIGNMENT_FILENAME,
        logical_path=f"refspec/output/registry-real-data-sources/{EUROVOC_LCSH_ALIGNMENT_FILENAME}",
        sha256=EUROVOC_LCSH_ALIGNMENT_SHA256,
        byte_length=EUROVOC_LCSH_ALIGNMENT_BYTE_LENGTH,
        source_iri=EUROVOC_LCSH_ALIGNMENT_URL,
        role="publisherEndpointSelection",
    )


def _current_fast_lcsh_claims(
    fast_release: object,
    target_iris: frozenset[str],
) -> set[tuple[str, str, str]]:
    claims: set[tuple[str, str, str]] = set()
    for resource in fast_release.resources:  # type: ignore[attr-defined]
        raw_links = resource.native_payload["lcshLinks"]
        if not isinstance(raw_links, list):
            raise TypeError(f"FAST resource {resource.iri} has malformed LCSH links")
        for raw_link in raw_links:
            if not isinstance(raw_link, Mapping):
                raise TypeError(f"FAST resource {resource.iri} has a malformed LCSH link")
            object_iri = raw_link.get("targetIri")
            publisher_predicate = raw_link.get("publisherPredicateIri")
            if not isinstance(object_iri, str) or not isinstance(publisher_predicate, str):
                raise TypeError(f"FAST resource {resource.iri} has a malformed LCSH link")
            if object_iri not in target_iris:
                continue
            if publisher_predicate == FAST_SCHEMA_SAME_AS:
                predicate_iri = str(SKOS.exactMatch)
            elif publisher_predicate == FAST_SKOS_RELATED_MATCH:
                predicate_iri = str(SKOS.relatedMatch)
            else:
                raise ValueError(f"FAST resource {resource.iri} has unsupported LCSH predicate {publisher_predicate}")
            claims.add((resource.iri, predicate_iri, object_iri))
    return claims


def _fast_bulk_evidence(
    link: fast_bulk.OclcFastExternalLink,
    *,
    mapping_predicate: str,
    source_pin: RegistryInputPin,
) -> RegistryMappingEvidence:
    native_payload: dict[str, object] = {
        "mappingTripleDigest": mapping_triple_digest(
            subject_iri=link.subject_iri,
            predicate_iri=mapping_predicate,
            object_iri=link.object_iri,
        ),
        "objectIri": link.object_iri,
        "predicateIri": mapping_predicate,
        "publisherClaim": {
            "nativeStatement": link.native_statement,
            "objectIri": link.object_iri,
            "predicateIri": link.predicate_iri,
            "sourceEncoding": "ntriples",
            "sourceRecordDigest": link.source_record_digest,
            "subjectIri": link.subject_iri,
        },
        "subjectIri": link.subject_iri,
    }
    if link.predicate_iri == fast_bulk.SCHEMA_SAME_AS:
        native_payload["operatorAdoption"] = {
            "adoptedBy": FAST_LCSH_ADOPTION_REVIEWER_IRI,
            "fromPredicateIri": fast_bulk.SCHEMA_SAME_AS,
            "toPredicateIri": str(SKOS.exactMatch),
        }
        review_warrant = "operatorAdoption"
        reviewer_iri = FAST_LCSH_ADOPTION_REVIEWER_IRI
    else:
        review_warrant = "publisherAssertion"
        reviewer_iri = FAST_LCSH_PUBLISHER_ASSERTION_REVIEWER_IRI
    return RegistryMappingEvidence(
        source_locator=f"{source_pin.source_iri}#{fast_bulk.FAST_EXTERNAL_LINKS_MEMBER}-line-{link.line_number}",
        source_digest=source_pin.sha256,
        native_payload=native_payload,
        review_warrant=review_warrant,
        reviewer_iri=reviewer_iri,
        attested_at=FAST_BULK_MAPPING_DECIDED_AT,
    )


def load_fast_bulk_external_links_delta_release(
    source_root: Path = DEFAULT_SOURCE_ROOT,
) -> RegistryMappingRelease:
    """Emit the nine held-endpoint bulk claims not repeated by current FAST."""

    source_root = Path(source_root)
    fast_release = load_fast_topical_release(source_root)
    endpoint_pin = _lcsh_endpoint_input(source_root)
    endpoint_pin.verify()
    target_iris = parse_eurovoc_lcsh_alignment_file(endpoint_pin.path).lcsh_concept_iris
    held_subjects = frozenset(resource.iri for resource in fast_release.resources)
    current_claims = _current_fast_lcsh_claims(fast_release, target_iris)
    if len(current_claims) != FAST_BULK_EXPECTED_CURRENT_COUNT:
        raise ValueError(
            f"current FAST held-endpoint mapping count differs: expected {FAST_BULK_EXPECTED_CURRENT_COUNT}, "
            f"observed {len(current_claims)}"
        )

    bulk_pin = _fast_bulk_input(source_root)
    capture = fast_bulk.parse_oclc_fast_external_links_file(
        bulk_pin.path,
        retained_subject_iris=held_subjects,
        retained_target_iris=target_iris,
    )
    links_by_claim: dict[tuple[str, str, str], fast_bulk.OclcFastExternalLink] = {}
    for link in capture.retained_links:
        mapping_predicate = (
            str(SKOS.exactMatch) if link.predicate_iri == fast_bulk.SCHEMA_SAME_AS else str(SKOS.relatedMatch)
        )
        links_by_claim[(link.subject_iri, mapping_predicate, link.object_iri)] = link
    bulk_claims = set(links_by_claim)
    overlap = bulk_claims & current_claims
    bulk_only = bulk_claims - current_claims
    current_only = current_claims - bulk_claims
    observed_shape = (
        len(bulk_claims),
        len(overlap),
        len(bulk_only),
        len(current_only),
    )
    expected_shape = (
        FAST_BULK_EXPECTED_HELD_COUNT,
        FAST_BULK_EXPECTED_OVERLAP_COUNT,
        FAST_BULK_EXPECTED_DELTA_COUNT,
        FAST_BULK_EXPECTED_CURRENT_ONLY_COUNT,
    )
    if observed_shape != expected_shape or bulk_only != set(FAST_BULK_DELTA_CLAIMS):
        raise ValueError(
            "FAST bulk/current reconciliation drifted: "
            f"expected={expected_shape!r}, observed={observed_shape!r}, "
            f"deltaMatchesFrozenSet={bulk_only == set(FAST_BULK_DELTA_CLAIMS)}"
        )
    reconciliation_predicate_counts = {
        "bulkHeldEndpointPredicateCounts": _claim_predicate_counts(bulk_claims),
        "bulkOnlyDeltaPredicateCounts": _claim_predicate_counts(bulk_only),
        "currentOnlyPredicateCounts": _claim_predicate_counts(current_only),
        "currentPredicateCounts": _claim_predicate_counts(current_claims),
        "overlapPredicateCounts": _claim_predicate_counts(overlap),
    }
    expected_reconciliation_predicate_counts = {
        "bulkHeldEndpointPredicateCounts": {
            str(SKOS.exactMatch): 1_683,
            str(SKOS.relatedMatch): 62_778,
        },
        "bulkOnlyDeltaPredicateCounts": {str(SKOS.relatedMatch): 9},
        "currentOnlyPredicateCounts": {str(SKOS.relatedMatch): 12},
        "currentPredicateCounts": {
            str(SKOS.exactMatch): 1_683,
            str(SKOS.relatedMatch): 62_781,
        },
        "overlapPredicateCounts": {
            str(SKOS.exactMatch): 1_683,
            str(SKOS.relatedMatch): 62_769,
        },
    }
    if reconciliation_predicate_counts != expected_reconciliation_predicate_counts:
        raise ValueError(
            "FAST bulk/current reconciliation predicate mix drifted: "
            f"expected={expected_reconciliation_predicate_counts!r}, "
            f"observed={reconciliation_predicate_counts!r}"
        )

    mappings = tuple(
        RegistryMapping(
            subject=subject_iri,
            predicate=predicate_iri,
            object=object_iri,
            subject_atlas_release_iri=fast_release.atlas_release_iri,
            object_atlas_release_iri=LCSH_ALIGNMENT_ENDPOINT_ATLAS_RELEASE_IRI,
            asserted_at=FAST_BULK_MAPPING_DECIDED_AT,
            evidence=(
                _fast_bulk_evidence(
                    links_by_claim[(subject_iri, predicate_iri, object_iri)],
                    mapping_predicate=predicate_iri,
                    source_pin=bulk_pin,
                ),
            ),
        )
        for subject_iri, predicate_iri, object_iri in sorted(bulk_only)
    )
    return RegistryMappingRelease(
        key="fast-bulk-external-links-delta-2026-07-27",
        resource_id="fast-bulk-external-links-delta",
        source_module="refspec.registry.oclc_fast_external_links",
        ring="subject",
        scope="captureSubset",
        issued="2026-07-27",
        source_release_iri=(
            "urn:ref:registry-mapping-release:fast-bulk-external-links-delta:" + bulk_pin.sha256.removeprefix("sha256:")
        ),
        source_release_digest=bulk_pin.sha256,
        # The bulk archive proves every emitted assertion. Current FAST and
        # the selected LCSH release are endpoint dependencies, which the
        # construction seed derives from the mapping endpoints.
        inputs=(bulk_pin,),
        mappings=mappings,
        editorial_policy=FAST_BULK_MAPPING_POLICY,
        metadata={
            "assertionComposition": {
                "publisherVerbatimRelatedMatch": {
                    "assertionCount": len(mappings),
                    "evidenceWarrant": "publisherAssertion",
                    "predicateIri": str(SKOS.relatedMatch),
                    "promotion": "none",
                }
            },
            "bulkCapture": {
                "assertionCount": capture.assertion_count,
                "distinctSubjectCount": capture.distinct_subject_count,
                "predicateCounts": capture.predicate_counts,
                "refusedPredicateCounts": capture.refused_predicate_counts,
                "targetPredicateCounts": capture.target_predicate_counts,
            },
            "endpointAccounting": {
                "bothEndpointsHeldUniqueAssertionCount": FAST_BULK_EXPECTED_HELD_COUNT,
                "externalObjectStatementCount": 714_716,
                "externalSubjectStatementCount": 14_017,
                "heldObjectStatementCount": 65_653,
                "heldObjectUniqueAssertionCount": 65_652,
                "heldSubjectStatementCount": 766_352,
                "selectedExternalSubjectStatementCount": (FAST_BULK_EXPECTED_SELECTED_EXTERNAL_SUBJECT_STATEMENT_COUNT),
                "selectedExternalSubjectUniqueAssertionCount": (
                    FAST_BULK_EXPECTED_SELECTED_EXTERNAL_SUBJECT_UNIQUE_COUNT
                ),
            },
            "licenseOrRights": fast_bulk.FAST_EXTERNAL_LINKS_LICENSE_URL,
            "licenseStatement": fast_bulk.FAST_EXTERNAL_LINKS_LICENSE_ARCHIVE_STATEMENT,
            "licenseTitle": fast_bulk.FAST_EXTERNAL_LINKS_LICENSE_TITLE,
            "licenseUrl": fast_bulk.FAST_EXTERNAL_LINKS_LICENSE_URL,
            "licensingIsAdmissionGate": False,
            "reconciliation": {
                "bulkHeldEndpointCount": len(bulk_claims),
                "bulkOnlyDeltaCount": len(bulk_only),
                "choice": "emitBulkOnlyDelta",
                "currentMarcDerivedCount": len(current_claims),
                "currentOnlyCount": len(current_only),
                "evidence": (
                    "The October 2024 bulk snapshot does not strictly contain the current MARC-derived scope: "
                    "nine held-endpoint claims occur only in bulk and 12 occur only after later changes."
                ),
                "overlapCount": len(overlap),
                "overlapEmitted": False,
                **reconciliation_predicate_counts,
                "supersedesCurrentScope": False,
            },
            "retrievalPrecision": "dateOnly",
            "retrievedAt": fast_bulk.FAST_EXTERNAL_LINKS_RETRIEVED_AT,
            "sourceCapture": _source_capture_payload(
                bulk_pin,
                retrieved_at=fast_bulk.FAST_EXTERNAL_LINKS_RETRIEVED_AT,
                source_version_note=(
                    "OCLC publishes this rolling URL without a versioned path; "
                    "the digest and byte length pin this capture."
                ),
            ),
            "sourceHasVersionedUrl": fast_bulk.FAST_EXTERNAL_LINKS_HAS_VERSIONED_URL,
            "sourceIdentifierCount": 0,
            "sourceUrlDriftRule": (
                "OCLC publishes a rolling URL; the digest and byte length identify this captured file"
            ),
        },
    )


def _fast_bulk_see_also_assets(
    source_root: Path,
) -> RegistryRelease:
    source_root = Path(source_root)
    bulk_pin = _fast_bulk_input(source_root)
    fast_release = load_fast_topical_release(source_root)
    active_iris = frozenset(resource.iri for resource in fast_release.resources)
    capture = fast_bulk.parse_oclc_fast_external_links_file(
        bulk_pin.path,
        retained_predicate_iris={fast_bulk.RDFS_SEE_ALSO},
    )
    internal_links = tuple(link for link in capture.retained_links if link.target_vocabulary == "fast")
    wikipedia_links = tuple(link for link in capture.retained_links if link.target_vocabulary == "wikipedia")
    if (
        len(internal_links) != FAST_SEE_ALSO_INTERNAL_ASSERTION_COUNT
        or len(wikipedia_links) != FAST_SEE_ALSO_WIKIPEDIA_ASSERTION_COUNT
    ):
        raise ValueError("FAST seeAlso target partition drifted")
    requested_iris = frozenset(
        endpoint
        for link in internal_links
        for endpoint in (link.subject_iri, link.object_iri)
        if endpoint not in active_iris
    )
    endpoint_records, missing_iris = fast_bulk.capture_oclc_fast_endpoint_records(
        bulk_pin.path,
        endpoint_iris=requested_iris,
    )
    if (
        len(endpoint_records) != FAST_SEE_ALSO_ENDPOINT_COUNT
        or len(missing_iris) != FAST_SEE_ALSO_MISSING_ENDPOINT_COUNT
        or any(record.publisher_language_tag is not None for record in endpoint_records.values())
    ):
        raise ValueError("FAST seeAlso endpoint content shape drifted")
    endpoint_resources = tuple(
        RegistryResource(
            iri=record.iri,
            labels=(
                RegistryLabel(
                    value=record.label,
                    role="preferred",
                    source_path=(f"{fast_bulk.FAST_EXTERNAL_LINKS_MEMBER}-line-{record.label_line_number}"),
                    language=record.language,
                ),
            ),
            native_payload={
                "deprecated": record.deprecated,
                "label": {
                    "languageDeterminedBy": record.language_determined_by,
                    "lineNumber": record.label_line_number,
                    "nativeStatement": record.label_native_statement,
                    "publisherPredicateIri": str(SKOS.prefLabel),
                    "sourceRecordDigest": record.label_statement_digest,
                    "value": record.label,
                },
                "languageDeterminedBy": record.language_determined_by,
                "publisherLanguageTagPresent": False,
            },
            source_locator=(
                f"{bulk_pin.source_iri}#{fast_bulk.FAST_EXTERNAL_LINKS_MEMBER}-line-{record.label_line_number}"
            ),
            source_digest=record.label_statement_digest,
            status=("deprecatedAlignmentEndpoint" if record.deprecated else "alignmentEndpoint"),
        )
        for record in endpoint_records.values()
    )
    held_iris = active_iris | frozenset(endpoint_records)
    content_backed_links = tuple(
        link for link in internal_links if link.subject_iri in held_iris and link.object_iri in held_iris
    )
    if len(content_backed_links) != FAST_SEE_ALSO_CONTENT_BACKED_ASSERTION_COUNT:
        raise ValueError("FAST seeAlso content-backed assertion count drifted")
    omitted_internal = len(internal_links) - len(content_backed_links)
    if omitted_internal != FAST_SEE_ALSO_MISSING_ENDPOINT_ASSERTION_COUNT:
        raise ValueError("FAST seeAlso missing-endpoint assertion count drifted")
    relations: tuple[RegistryRelation, ...] = ()
    endpoint_inputs = (bulk_pin, *fast_release.inputs)
    return RegistryRelease(
        key=FAST_SEE_ALSO_ENDPOINT_RELEASE_KEY,
        resource_id="fast-bulk-see-also-endpoints",
        source_module="refspec.registry.oclc_fast_external_links",
        profile="conceptScheme",
        ring="subject",
        scope="captureSubset",
        issued="2026-07-27",
        source_release_iri=(
            "urn:ref:source-release:fast-topical:bulk-see-also-endpoints:" + bulk_pin.sha256.removeprefix("sha256:")
        ),
        source_release_digest=_input_set_digest(
            endpoint_inputs,
            frozenset(pin.role for pin in endpoint_inputs),
        ),
        atlas_release_iri=FAST_SEE_ALSO_ENDPOINT_ATLAS_RELEASE_IRI,
        scheme_iri="urn:ref:atlas-resource-scheme:fast-bulk-see-also-endpoints",
        inputs=endpoint_inputs,
        resources=endpoint_resources,
        relations=relations,
        metadata={
            "assertionComposition": {
                "publisherSeeAlso": {
                    "contentBackedAssertionCount": len(content_backed_links),
                    "emittedAssertionCount": len(relations),
                    "predicateIri": fast_bulk.RDFS_SEE_ALSO,
                    "semanticDisposition": "counted source navigation; no Atlas 3.1 semantic predicate",
                }
            },
            "bulkCapture": {
                "assertionCount": capture.assertion_count,
                "predicateCounts": capture.predicate_counts,
                "refusedPredicateCounts": capture.refused_predicate_counts,
            },
            "completePublisherRelease": False,
            "deprecatedEndpointCount": sum(record.deprecated for record in endpoint_records.values()),
            "endpointOwnershipPreference": "publisherOwnedVocabulary",
            "endpointAccounting": {
                "capturedFastSeeAlsoCount": len(internal_links),
                "capturedWikipediaSeeAlsoCount": len(wikipedia_links),
                "contentBackedFastSeeAlsoCount": len(content_backed_links),
                "contentfulCapturedEndpointCount": len(endpoint_records),
                "emittedAssertionCount": len(relations),
                "missingFastEndpointAssertionCount": omitted_internal,
                "missingFastEndpointCount": len(missing_iris),
                "wikipediaAssertionDisposition": "omitted because no target publisher content is captured",
            },
            "languageDeterminationRule": "authorityConvention:fast-topical-labels-are-English",
            "licenseStatement": fast_bulk.FAST_EXTERNAL_LINKS_LICENSE_ARCHIVE_STATEMENT,
            "licenseTitle": fast_bulk.FAST_EXTERNAL_LINKS_LICENSE_TITLE,
            "licenseUrl": fast_bulk.FAST_EXTERNAL_LINKS_LICENSE_URL,
            "licensingIsAdmissionGate": False,
            "mappingEndpointSubset": True,
            "missingEndpointCount": len(missing_iris),
            "missingEndpointIris": sorted(missing_iris),
            "missingEndpointReason": "pinned OCLC bulk file supplies no prefLabel; no stub emitted",
            "nonTopicalSeeAlsoDisposition": "two license-document statements counted and not treated as FAST relations",
            "owlSameAsDisposition": "two assertions refused because owl:sameAs merges identity",
            "publisherLanguageTagPresent": False,
            "resourceCount": len(endpoint_resources),
            "relationPolicy": dict(FAST_SEE_ALSO_RELATION_POLICY),
            "representation": "contentful FAST endpoints with rdfs:seeAlso counted as source navigation",
            "sourceCapture": _source_capture_payload(
                bulk_pin,
                retrieved_at=fast_bulk.FAST_EXTERNAL_LINKS_RETRIEVED_AT,
                source_version_note="rolling URL pinned by exact digest and byte length",
            ),
            "sourceIdentifierCount": 0,
            "skosS27ConflictList": {
                "canonicalItemShape": {"leftIri": "IRI", "rightIri": "IRI"},
                "count": FAST_SEE_ALSO_S27_CONFLICT_PAIR_COUNT,
                "digest": FAST_SEE_ALSO_S27_CONFLICT_PAIR_DIGEST,
            },
        },
    )


def load_fast_bulk_see_also_endpoint_release(
    source_root: Path = DEFAULT_SOURCE_ROOT,
) -> RegistryRelease:
    return _fast_bulk_see_also_assets(Path(source_root))


def _eurovoc_input(source_root: Path, pin: EuroVocAlignmentPin) -> RegistryInputPin:
    return RegistryInputPin(
        path=Path(source_root) / pin.filename,
        logical_path=f"refspec/output/registry-real-data-sources/{pin.filename}",
        sha256=pin.expected_sha256,
        byte_length=pin.expected_byte_length,
        source_iri=pin.source_url,
        role="publisherAlignment",
    )


def _subject_release_map(source_root: Path) -> dict[str, str]:
    return {
        resource.iri: release.atlas_release_iri
        for release in load_eurovoc_4_24_releases(source_root)
        for resource in release.resources
    }


def _portfolio_accounting(
    portfolio: EuroVocAlignmentPortfolio,
    subject_releases: Mapping[str, str],
    held_target_iris_by_key: Mapping[str, Collection[str]],
) -> list[dict[str, object]]:
    accounting: list[dict[str, object]] = []
    for alignment in portfolio.alignments:
        held_targets = held_target_iris_by_key.get(alignment.pin.key, ())
        held_target_count = sum(
            (
                mapping.object_iri in held_targets
                if alignment.pin.key != "mesh"
                else _mesh_held_iri(mapping.object_iri, held_targets) is not None
            )
            for mapping in alignment.mappings
        )
        both_held_count = sum(
            mapping.subject_iri in subject_releases
            and (
                mapping.object_iri in held_targets
                if alignment.pin.key != "mesh"
                else _mesh_held_iri(mapping.object_iri, held_targets) is not None
            )
            for mapping in alignment.mappings
        )
        accounting.append(
            {
                "assertionCount": len(alignment.mappings),
                "bothEndpointsHeldAssertionCount": both_held_count,
                "externalEndpointAssertionCount": len(alignment.mappings) - both_held_count,
                "externalEuroVocSubjectCount": sum(
                    mapping.subject_iri not in subject_releases for mapping in alignment.mappings
                ),
                "externalTargetAssertionCount": len(alignment.mappings) - held_target_count,
                "heldTargetAssertionCount": held_target_count,
                "key": alignment.pin.key,
                "nonEuroVocSourceAnomalyCount": alignment.non_eurovoc_mapping_count,
                "predicateCounts": alignment.predicate_counts,
                "retrievedAt": alignment.pin.retrieved_at,
                "sourceCapture": {
                    "byteLength": alignment.pin.expected_byte_length,
                    "retrievedAt": alignment.pin.retrieved_at,
                    "sha256": alignment.pin.expected_sha256,
                    "sourceUrl": alignment.pin.source_url,
                    "sourceVersionNote": "Versioned Cellar distribution URL.",
                },
                "version": alignment.pin.version,
            }
        )
    return accounting


def _eurovoc_evidence(
    mapping: object,
    *,
    emitted_object_iri: str,
    pin: EuroVocAlignmentPin,
    reviewer_iri: str,
    endpoint_resolution: Mapping[str, object] | None = None,
) -> RegistryMappingEvidence:
    native_payload: dict[str, object] = {
        "mappingTripleDigest": mapping_triple_digest(
            subject_iri=mapping.subject_iri,
            predicate_iri=mapping.predicate_iri,
            object_iri=emitted_object_iri,
        ),
        "objectIri": emitted_object_iri,
        "predicateIri": mapping.predicate_iri,
        "publisherClaim": {
            "objectIri": mapping.object_iri,
            "predicateIri": mapping.predicate_iri,
            "publisherAlignmentDigest": pin.expected_sha256,
            "publisherAlignmentRelease": pin.source_release_iri,
            "publisherAlignmentVersion": pin.version,
            "subjectIri": mapping.subject_iri,
        },
        "subjectIri": mapping.subject_iri,
    }
    if endpoint_resolution is not None:
        native_payload["endpointResolution"] = endpoint_resolution
    return RegistryMappingEvidence(
        source_locator=pin.source_url,
        source_digest=pin.expected_sha256,
        native_payload=native_payload,
        review_warrant="publisherAssertion",
        reviewer_iri=reviewer_iri,
        attested_at=f"{pin.issued}T00:00:00+00:00",
    )


def _common_eurovoc_metadata(
    portfolio: EuroVocAlignmentPortfolio,
    subject_releases: Mapping[str, str],
    held_target_iris_by_key: Mapping[str, Collection[str]],
) -> dict[str, object]:
    return {
        "catalogueAssertionCountIncludingLcsh": EXPECTED_COMPLETE_CATALOGUE_ASSERTION_COUNT,
        "catalogueExactMatchRatio": {"denominator": 10_000, "numerator": 9_375},
        "catalogueUrl": EUROVOC_ALIGNMENT_CATALOGUE_URL,
        "generalReuseBasis": EUROVOC_ALIGNMENT_GENERAL_REUSE_BASIS_URL,
        "licenseOrRights": EUROVOC_ALIGNMENT_LICENSE_STATEMENT,
        "licenseStatement": EUROVOC_ALIGNMENT_LICENSE_STATEMENT,
        "licensingIsAdmissionGate": False,
        "portfolioAssertionCountExcludingLcsh": EXPECTED_PORTFOLIO_ASSERTION_COUNT,
        "portfolioCapture": _portfolio_accounting(
            portfolio,
            subject_releases,
            held_target_iris_by_key,
        ),
        "portfolioFileCountExcludingLcsh": len(portfolio.alignments),
        "thirdPartyRightsExclusion": EUROVOC_ALIGNMENT_THIRD_PARTY_RIGHTS_EXCLUSION,
    }


def _alignment_by_key(portfolio: EuroVocAlignmentPortfolio, key: str) -> EuroVocAlignmentCapture:
    return next(alignment for alignment in portfolio.alignments if alignment.pin.key == key)


def _load_eurovoc_gemet_release(
    source_root: Path,
    portfolio: EuroVocAlignmentPortfolio,
    subject_releases: Mapping[str, str],
    held_target_iris_by_key: Mapping[str, Collection[str]],
) -> RegistryMappingRelease:
    alignment = _alignment_by_key(portfolio, "gemet")
    held_objects = held_target_iris_by_key["gemet"]
    held_claims = tuple(
        mapping
        for mapping in alignment.mappings
        if mapping.subject_iri in subject_releases and mapping.object_iri in held_objects
    )
    if len(held_claims) != 2_035:
        raise ValueError(f"EuroVoc--GEMET held publisher count differs: expected 2035, observed {len(held_claims)}")
    s46_refusals = GEMET_EUROVOC_S46_REFUSALS["eurovoc"]
    observed_claims = {(mapping.subject_iri, mapping.predicate_iri, mapping.object_iri) for mapping in held_claims}
    if not s46_refusals <= observed_claims:
        raise ValueError("EuroVoc--GEMET frozen SKOS S46 refusal list drifted")
    emitted = tuple(
        mapping
        for mapping in held_claims
        if (mapping.subject_iri, mapping.predicate_iri, mapping.object_iri) not in s46_refusals
    )
    if len(emitted) != 1_998:
        raise ValueError("EuroVoc--GEMET emitted count drifted after SKOS S46 refusals")
    source = _eurovoc_input(source_root, alignment.pin)
    mappings = tuple(
        RegistryMapping(
            subject=mapping.subject_iri,
            predicate=mapping.predicate_iri,
            object=mapping.object_iri,
            subject_atlas_release_iri=subject_releases[mapping.subject_iri],
            object_atlas_release_iri=GEMET_ATLAS_RELEASE_IRI,
            asserted_at=f"{alignment.pin.issued}T00:00:00+00:00",
            evidence=(
                _eurovoc_evidence(
                    mapping,
                    emitted_object_iri=mapping.object_iri,
                    pin=alignment.pin,
                    reviewer_iri=EUROVOC_GEMET_MAPPING_REVIEWER_IRI,
                ),
            ),
        )
        for mapping in emitted
    )
    return RegistryMappingRelease(
        key="eurovoc-gemet-alignment-20201218",
        resource_id="eurovoc-gemet-alignment",
        source_module="refspec.registry.eurovoc_alignment_portfolio",
        ring="subject",
        scope="captureSubset",
        issued=alignment.pin.issued,
        source_release_iri=alignment.pin.source_release_iri,
        source_release_digest=alignment.pin.expected_sha256,
        inputs=(source,),
        mappings=mappings,
        editorial_policy=EUROVOC_PORTFOLIO_MAPPING_POLICY,
        metadata={
            **_common_eurovoc_metadata(
                portfolio,
                subject_releases,
                held_target_iris_by_key,
            ),
            "assertionCounts": alignment.predicate_counts,
            "bothEndpointsHeldCount": len(held_claims),
            "emittedAssertionCount": len(mappings),
            "externalEuroVocSubjectCount": 1,
            "externalTargetCount": 0,
            "publisherAssertionCount": len(held_claims),
            "retrievedAt": alignment.pin.retrieved_at,
            "sourceCapture": _source_capture_payload(
                source,
                retrieved_at=alignment.pin.retrieved_at,
                source_version_note="Versioned Cellar distribution URL.",
            ),
            "sourceHasVersionedUrl": True,
            "sourceIdentifierCount": 0,
            "skosS46RefusalCount": len(s46_refusals),
            "skosS46RefusedPublisherClaims": [
                {
                    "objectIri": object_iri,
                    "predicateIri": predicate_iri,
                    "subjectIri": subject_iri,
                }
                for subject_iri, predicate_iri, object_iri in sorted(s46_refusals)
            ],
            "skosS46RefusalReason": (
                "non-exact publisher claim conflicts with the combined GEMET/EuroVoc exactMatch component"
            ),
            "totalPublisherAssertionCount": len(alignment.mappings),
        },
    )


def _mesh_held_iri(object_iri: str, held_objects: Collection[str]) -> str | None:
    if not object_iri.startswith(MESH_HTTP_IRI_PREFIX):
        return None
    candidate = MESH_HTTPS_IRI_PREFIX + object_iri.removeprefix(MESH_HTTP_IRI_PREFIX)
    return candidate if candidate in held_objects else None


def _load_eurovoc_mesh_release(
    source_root: Path,
    portfolio: EuroVocAlignmentPortfolio,
    subject_releases: Mapping[str, str],
    held_target_iris_by_key: Mapping[str, Collection[str]],
) -> RegistryMappingRelease:
    alignment = _alignment_by_key(portfolio, "mesh")
    held_objects = held_target_iris_by_key["mesh"]
    selected = tuple(
        (mapping, held_iri)
        for mapping in alignment.mappings
        if mapping.subject_iri in subject_releases
        if (held_iri := _mesh_held_iri(mapping.object_iri, held_objects)) is not None
    )
    if len(selected) != 5:
        raise ValueError(f"EuroVoc--MeSH held mapping count differs: expected 5, observed {len(selected)}")
    source = _eurovoc_input(source_root, alignment.pin)
    mappings = tuple(
        RegistryMapping(
            subject=mapping.subject_iri,
            predicate=mapping.predicate_iri,
            object=held_iri,
            subject_atlas_release_iri=subject_releases[mapping.subject_iri],
            object_atlas_release_iri=MESH_ATLAS_RELEASE_IRI,
            asserted_at=f"{alignment.pin.issued}T00:00:00+00:00",
            evidence=(
                _eurovoc_evidence(
                    mapping,
                    emitted_object_iri=held_iri,
                    pin=alignment.pin,
                    reviewer_iri=EUROVOC_MESH_MAPPING_REVIEWER_IRI,
                    endpoint_resolution={
                        "fromObjectIri": mapping.object_iri,
                        "method": "publisherIdentifierHttpToHttpsRedirect",
                        "predicateChanged": False,
                        "toObjectIri": held_iri,
                    },
                ),
            ),
        )
        for mapping, held_iri in selected
    )
    return RegistryMappingRelease(
        key="eurovoc-mesh-alignment-20171215",
        resource_id="eurovoc-mesh-alignment",
        source_module="refspec.registry.eurovoc_alignment_portfolio",
        ring="subject",
        scope="captureSubset",
        issued=alignment.pin.issued,
        source_release_iri=alignment.pin.source_release_iri,
        source_release_digest=alignment.pin.expected_sha256,
        inputs=(source,),
        mappings=mappings,
        editorial_policy=EUROVOC_PORTFOLIO_MAPPING_POLICY,
        metadata={
            **_common_eurovoc_metadata(
                portfolio,
                subject_releases,
                held_target_iris_by_key,
            ),
            "assertionCounts": alignment.predicate_counts,
            "bothEndpointsHeldCount": len(mappings),
            "emittedAssertionCount": len(mappings),
            "externalEuroVocSubjectCount": 1,
            "externalTargetCount": 5,
            "heldTargetAfterHttpToHttpsResolutionCount": 6,
            "objectIriResolution": (
                "The alignment uses NLM's http identifier spelling; the held MeSH descriptor release uses "
                "the same publisher identifiers with https. Evidence retains each published http IRI."
            ),
            "publisherAssertionCount": len(mappings),
            "retrievedAt": alignment.pin.retrieved_at,
            "sourceCapture": _source_capture_payload(
                source,
                retrieved_at=alignment.pin.retrieved_at,
                source_version_note="Versioned Cellar distribution URL.",
            ),
            "sourceHasVersionedUrl": True,
            "sourceIdentifierCount": 0,
            "totalPublisherAssertionCount": len(alignment.mappings),
            "unemittedHeldTargetWithExternalEuroVocSubjectCount": 1,
        },
    )


def load_eurovoc_portfolio_mapping_releases(
    source_root: Path = DEFAULT_SOURCE_ROOT,
    *,
    only_keys: Collection[str] | None = None,
) -> tuple[RegistryMappingRelease, ...]:
    """Load the held-endpoint GEMET and MeSH portions of the 17-file capture."""

    allowed = frozenset(
        {
            "eurovoc-gemet-alignment-20201218",
            "eurovoc-mesh-alignment-20171215",
        }
    )
    requested = normalize_only_keys(
        only_keys,
        allowed_keys=allowed,
        loader_name="load_eurovoc_portfolio_mapping_releases",
    )
    if not wants_group(requested, allowed):
        return ()
    source_root = Path(source_root)
    portfolio = load_eurovoc_alignment_portfolio(source_root)
    subject_releases = _subject_release_map(source_root)
    gemet_release = load_gemet_release(source_root)
    mesh_release = load_mesh_2026_release(source_root)
    if gemet_release.atlas_release_iri != GEMET_ATLAS_RELEASE_IRI:
        raise ValueError("EuroVoc--GEMET target release IRI differs from its exact pin")
    if mesh_release.atlas_release_iri != MESH_ATLAS_RELEASE_IRI:
        raise ValueError("EuroVoc--MeSH target release IRI differs from its exact pin")
    held_target_iris_by_key = {
        "gemet": frozenset(resource.iri for resource in gemet_release.resources),
        "mesh": frozenset(resource.iri for resource in mesh_release.resources),
    }
    loaders = (
        (
            "eurovoc-gemet-alignment-20201218",
            lambda: _load_eurovoc_gemet_release(
                source_root,
                portfolio,
                subject_releases,
                held_target_iris_by_key,
            ),
        ),
        (
            "eurovoc-mesh-alignment-20171215",
            lambda: _load_eurovoc_mesh_release(
                source_root,
                portfolio,
                subject_releases,
                held_target_iris_by_key,
            ),
        ),
    )
    return tuple(loader() for key, loader in loaders if requested is None or key in requested)


def load_all_registry_bulk_mapping_releases(
    source_root: Path = DEFAULT_SOURCE_ROOT,
    *,
    only_keys: Collection[str] | None = None,
) -> tuple[RegistryMappingRelease, ...]:
    """Load selected mapping releases owned by this independent adapter group."""

    requested = normalize_only_keys(
        only_keys,
        allowed_keys=BULK_REGISTRY_MAPPING_RELEASE_KEYS,
        loader_name="load_all_registry_bulk_mapping_releases",
    )
    if not wants_group(requested, BULK_REGISTRY_MAPPING_RELEASE_KEYS):
        return ()
    loaded: list[RegistryMappingRelease] = []
    fast_key = "fast-bulk-external-links-delta-2026-07-27"
    if requested is None or fast_key in requested:
        loaded.append(load_fast_bulk_external_links_delta_release(source_root))
    eurovoc_keys = frozenset(BULK_REGISTRY_MAPPING_RELEASE_KEYS - {fast_key})
    eurovoc_requested = None if requested is None else requested & eurovoc_keys
    loaded.extend(
        load_eurovoc_portfolio_mapping_releases(
            source_root,
            only_keys=eurovoc_requested,
        )
    )
    expected = BULK_REGISTRY_MAPPING_RELEASE_KEYS if requested is None else requested
    observed = [release.key for release in loaded]
    if len(observed) != len(set(observed)) or set(observed) != set(expected):
        raise ValueError(
            "load_all_registry_bulk_mapping_releases topology differs: "
            f"expected={sorted(expected)!r}, observed={sorted(observed)!r}"
        )
    return tuple(loaded)


def load_all_registry_bulk_alignment_endpoint_releases(
    source_root: Path = DEFAULT_SOURCE_ROOT,
    *,
    only_keys: Collection[str] | None = None,
) -> tuple[RegistryRelease, ...]:
    """Load contentful FAST endpoints needed by bulk see-also assertions."""

    requested = normalize_only_keys(
        only_keys,
        allowed_keys=BULK_REGISTRY_ALIGNMENT_ENDPOINT_RELEASE_KEYS,
        loader_name="load_all_registry_bulk_alignment_endpoint_releases",
    )
    if not wants_group(requested, BULK_REGISTRY_ALIGNMENT_ENDPOINT_RELEASE_KEYS):
        return ()
    return (load_fast_bulk_see_also_endpoint_release(source_root),)


__all__ = [
    "BULK_REGISTRY_ALIGNMENT_ENDPOINT_RELEASE_KEYS",
    "BULK_REGISTRY_MAPPING_RELEASE_KEYS",
    "DEFAULT_SOURCE_ROOT",
    "EUROVOC_ATLAS_RELEASE_IRI",
    "EUROVOC_DOMAINS_ATLAS_RELEASE_IRI",
    "EUROVOC_GEMET_MAPPING_REVIEWER_IRI",
    "EUROVOC_MESH_MAPPING_REVIEWER_IRI",
    "FAST_BULK_DELTA_CLAIMS",
    "FAST_BULK_EXPECTED_CURRENT_COUNT",
    "FAST_BULK_EXPECTED_CURRENT_ONLY_COUNT",
    "FAST_BULK_EXPECTED_DELTA_COUNT",
    "FAST_BULK_EXPECTED_HELD_COUNT",
    "FAST_BULK_EXPECTED_OVERLAP_COUNT",
    "FAST_BULK_MAPPING_POLICY",
    "FAST_SEE_ALSO_CONTENT_BACKED_ASSERTION_COUNT",
    "FAST_SEE_ALSO_EMITTED_ASSERTION_COUNT",
    "FAST_SEE_ALSO_ENDPOINT_ATLAS_RELEASE_IRI",
    "FAST_SEE_ALSO_ENDPOINT_RELEASE_KEY",
    "FAST_SEE_ALSO_RELATION_POLICY",
    "FAST_SEE_ALSO_S27_CONFLICT_PAIR_COUNT",
    "FAST_SEE_ALSO_S27_CONFLICT_PAIR_DIGEST",
    "GEMET_ATLAS_RELEASE_IRI",
    "MESH_ATLAS_RELEASE_IRI",
    "load_all_registry_bulk_alignment_endpoint_releases",
    "load_all_registry_bulk_mapping_releases",
    "load_eurovoc_portfolio_mapping_releases",
    "load_fast_bulk_external_links_delta_release",
    "load_fast_bulk_see_also_endpoint_release",
]
