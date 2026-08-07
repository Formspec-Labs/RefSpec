"""Publisher mapping releases and the exact endpoint subsets they require."""

from __future__ import annotations

from collections import Counter
from collections.abc import Collection
from pathlib import Path

from refspec.atlas.v3_registry_selection import (
    normalize_only_keys,
    select_declared_group,
    wants_group,
)
from refspec.atlas.v3_source_data import (
    RegistryInputPin,
    RegistryLabel,
    RegistryMappingRelease,
    RegistryPublisherMapping,
    RegistryRelation,
    RegistryRelease,
    RegistryResource,
    canonical_digest,
    mapping_triple_digest,
)
from refspec.registry import lcsh_topical as lcsh
from refspec.registry.eurovoc_lcsh_alignment import (
    EUROVOC_4_20_METADATA_BYTE_LENGTH,
    EUROVOC_4_20_METADATA_FILENAME,
    EUROVOC_4_20_METADATA_SHA256,
    EUROVOC_4_20_METADATA_URL,
    EUROVOC_4_20_RELEASE_IRI,
    EUROVOC_4_24_METADATA_BYTE_LENGTH,
    EUROVOC_4_24_METADATA_FILENAME,
    EUROVOC_4_24_METADATA_SHA256,
    EUROVOC_4_24_METADATA_URL,
    EUROVOC_LCSH_ALIGNMENT_BYTE_LENGTH,
    EUROVOC_LCSH_ALIGNMENT_FILENAME,
    EUROVOC_LCSH_ALIGNMENT_ISSUED,
    EUROVOC_LCSH_ALIGNMENT_METADATA_BYTE_LENGTH,
    EUROVOC_LCSH_ALIGNMENT_METADATA_FILENAME,
    EUROVOC_LCSH_ALIGNMENT_METADATA_SHA256,
    EUROVOC_LCSH_ALIGNMENT_METADATA_URL,
    EUROVOC_LCSH_ALIGNMENT_RELEASE_IRI,
    EUROVOC_LCSH_ALIGNMENT_SHA256,
    EUROVOC_LCSH_ALIGNMENT_URL,
    EXPECTED_PREDICATE_COUNTS,
    parse_eurovoc_lcsh_alignment_file,
    verify_eurovoc_4_24_metadata,
    verify_eurovoc_lcsh_release_metadata,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_SOURCE_ROOT = REPOSITORY_ROOT / "output" / "registry-real-data-sources"

LCSH_BULK_FILENAME = "lcsh-subjects-madsrdf-2026-08-06.jsonld.gz"
LCSH_BULK_SHA256 = (
    "sha256:b33adc284bfb98e39c1331927e9ffee3d73dd0b1b83342906b6ea52c408a5856"
)
LCSH_BULK_BYTE_LENGTH = 140_187_915
LCSH_BULK_CAPTURED_AT = "2026-08-06"
LCSH_ALIGNMENT_ENDPOINT_COUNT = 1_966
EUROVOC_LCSH_MAPPING_COUNT = sum(EXPECTED_PREDICATE_COUNTS.values())
ATLAS_MAPPING_ADOPTION_REVIEWER_IRI = (
    "urn:ref:actor:atlas-3-eurovoc-lcsh-operator-adoption"
)
ATLAS_MAPPING_ADOPTION_DECISION_DATE = "2026-08-06"
REGISTRY_ALIGNMENT_ENDPOINT_RELEASE_KEYS = frozenset(
    {"lcsh-eurovoc-alignment-endpoints-2026-08-06"}
)
REGISTRY_MAPPING_RELEASE_KEYS = frozenset(
    {"eurovoc-lcsh-alignment-20240711"}
)


def _pin(
    source_root: Path,
    *,
    filename: str,
    sha256: str,
    byte_length: int,
    source_iri: str,
    role: str,
) -> RegistryInputPin:
    return RegistryInputPin(
        path=Path(source_root) / filename,
        logical_path=f"refspec/output/registry-real-data-sources/{filename}",
        sha256=sha256,
        byte_length=byte_length,
        source_iri=source_iri,
        role=role,
    )


def _alignment_pins(
    source_root: Path,
) -> tuple[RegistryInputPin, RegistryInputPin, RegistryInputPin, RegistryInputPin]:
    return (
        _pin(
            source_root,
            filename=EUROVOC_LCSH_ALIGNMENT_FILENAME,
            sha256=EUROVOC_LCSH_ALIGNMENT_SHA256,
            byte_length=EUROVOC_LCSH_ALIGNMENT_BYTE_LENGTH,
            source_iri=EUROVOC_LCSH_ALIGNMENT_URL,
            role="publisherAlignment",
        ),
        _pin(
            source_root,
            filename=EUROVOC_LCSH_ALIGNMENT_METADATA_FILENAME,
            sha256=EUROVOC_LCSH_ALIGNMENT_METADATA_SHA256,
            byte_length=EUROVOC_LCSH_ALIGNMENT_METADATA_BYTE_LENGTH,
            source_iri=EUROVOC_LCSH_ALIGNMENT_METADATA_URL,
            role="publisherAlignmentReleaseMetadata",
        ),
        _pin(
            source_root,
            filename=EUROVOC_4_20_METADATA_FILENAME,
            sha256=EUROVOC_4_20_METADATA_SHA256,
            byte_length=EUROVOC_4_20_METADATA_BYTE_LENGTH,
            source_iri=EUROVOC_4_20_METADATA_URL,
            role="publisherSourceReleaseMetadata",
        ),
        _pin(
            source_root,
            filename=EUROVOC_4_24_METADATA_FILENAME,
            sha256=EUROVOC_4_24_METADATA_SHA256,
            byte_length=EUROVOC_4_24_METADATA_BYTE_LENGTH,
            source_iri=EUROVOC_4_24_METADATA_URL,
            role="currentPublisherLinksetMetadata",
        ),
    )


def _input_set_digest(inputs: tuple[RegistryInputPin, ...]) -> str:
    return canonical_digest(
        [
            {
                "byteLength": item.byte_length,
                "digest": item.sha256,
                "role": item.role,
                "sourceIri": item.source_iri,
            }
            for item in inputs
        ]
    )


def load_eurovoc_lcsh_mapping_release(
    source_root: Path = DEFAULT_SOURCE_ROOT,
) -> RegistryMappingRelease:
    """Load the official alignment as separately pinned publisher mappings."""

    pins = _alignment_pins(source_root)
    alignment_pin, alignment_metadata_pin, eurovoc_4_20_pin, current_metadata_pin = (
        pins
    )
    for pin in pins:
        pin.verify()
    alignment = parse_eurovoc_lcsh_alignment_file(alignment_pin.path)
    verify_eurovoc_lcsh_release_metadata(
        alignment_metadata_pin.path,
        eurovoc_4_20_pin.path,
    )
    verify_eurovoc_4_24_metadata(current_metadata_pin.path)
    if len(alignment.mappings) != EUROVOC_LCSH_MAPPING_COUNT:
        raise ValueError(
            f"EuroVoc--LCSH expected {EUROVOC_LCSH_MAPPING_COUNT} mappings; "
            f"parsed {len(alignment.mappings)}"
        )
    mappings = tuple(
        RegistryPublisherMapping(
            subject=row.subject_iri,
            predicate=row.predicate_iri,
            object=row.object_iri,
            source_locator=alignment_pin.source_iri,
            source_digest=alignment_pin.sha256,
            source_payload={
                "currentEuroVocLinksetCounts": dict(EXPECTED_PREDICATE_COUNTS),
                "currentEuroVocLinksetMetadataDigest": current_metadata_pin.sha256,
                "currentEuroVocRelease": "4.24",
                "currentMetadataRequalifiesIndividualPairs": False,
                "mappingTripleDigest": mapping_triple_digest(
                    subject_iri=row.subject_iri,
                    predicate_iri=row.predicate_iri,
                    object_iri=row.object_iri,
                ),
                "objectIri": row.object_iri,
                "predicateIri": row.predicate_iri,
                "publisherAlignmentDigest": alignment_pin.sha256,
                "publisherAlignmentIssued": EUROVOC_LCSH_ALIGNMENT_ISSUED,
                "publisherAlignmentRelease": EUROVOC_LCSH_ALIGNMENT_RELEASE_IRI,
                "publisherAlignmentVersion": "20240711-0",
                "publisherEuroVocRelease": EUROVOC_4_20_RELEASE_IRI,
                "publisherEuroVocVersion": "4.20",
                "publisherLcshRelease": "unspecifiedByPublisher",
                "subjectIri": row.subject_iri,
            },
        )
        for row in alignment.mappings
    )
    return RegistryMappingRelease(
        key="eurovoc-lcsh-alignment-20240711",
        resource_id="eurovoc-lcsh-alignment",
        source_module="refspec.registry.eurovoc_lcsh_alignment",
        ring="subject",
        issued=EUROVOC_LCSH_ALIGNMENT_ISSUED,
        source_release_iri=EUROVOC_LCSH_ALIGNMENT_RELEASE_IRI,
        source_release_digest=alignment_pin.sha256,
        inputs=pins,
        mappings=mappings,
        decision_date=ATLAS_MAPPING_ADOPTION_DECISION_DATE,
        review_method="operatorAdoption",
        reviewer_iri=ATLAS_MAPPING_ADOPTION_REVIEWER_IRI,
        confidence=None,
        metadata={
            "adoptionDecision": "atlasOperatorAdoption",
            "adoptionNote": (
                "Atlas applies each pinned publisher mapping only to the exact "
                "loaded endpoint releases. The 4.24 metadata repeats the aggregate "
                "linkset counts but does not requalify individual 4.20 mapping pairs."
            ),
            "adoptionRule": "pinned-publisher-mapping-to-loaded-versioned-endpoints-v1",
            "adoptionReviewer": ATLAS_MAPPING_ADOPTION_REVIEWER_IRI,
            "alignmentArtifactVersion": "20240711-0",
            "assertionCounts": dict(EXPECTED_PREDICATE_COUNTS),
            "currentEuroVocMetadataCarriesLinksets": True,
            "currentEuroVocRelease": "4.24",
            "euroVocSubjectCount": len(alignment.eurovoc_concept_iris),
            "lcshTargetCount": len(alignment.lcsh_concept_iris),
            "lcshTargetRelease": "unspecifiedByPublisher",
            "publisherEuroVocRelease": EUROVOC_4_20_RELEASE_IRI,
            "publisherEuroVocVersion": "4.20",
            "publisherRequalificationForEuroVoc4_24": False,
        },
    )


def _english_labels(record: lcsh.LcshTopicalRecord) -> tuple[RegistryLabel, ...]:
    if record.preferred_label.language.casefold() != "en":
        raise ValueError(
            f"aligned LCSH authority lacks an English preferred label: {record.concept_iri}"
        )
    labels = [
        RegistryLabel(
            value=record.preferred_label.value.strip(),
            role="preferred",
            source_path=f"line-{record.line_number}:madsrdf:authoritativeLabel",
        )
    ]
    seen = {labels[0].value}
    for index, label in enumerate(record.variant_labels):
        if label.language.casefold() != "en":
            continue
        value = label.value.strip()
        if not value or value in seen:
            continue
        seen.add(value)
        labels.append(
            RegistryLabel(
                value=value,
                role="alternate",
                source_path=(
                    f"line-{record.line_number}:madsrdf:hasVariant[{index}]"
                ),
            )
        )
    return tuple(labels)


def load_lcsh_alignment_endpoint_release(
    source_root: Path = DEFAULT_SOURCE_ROOT,
) -> RegistryRelease:
    """Load exactly every LCSH authority referenced by the official alignment."""

    alignment_pin = _alignment_pins(source_root)[0]
    bulk_pin = _pin(
        source_root,
        filename=LCSH_BULK_FILENAME,
        sha256=LCSH_BULK_SHA256,
        byte_length=LCSH_BULK_BYTE_LENGTH,
        source_iri=lcsh.LCSH_TOPICAL_MADS_NDJSON_URL,
        role="publisherBulkSource",
    )
    alignment_pin.verify()
    bulk_pin.verify()
    alignment = parse_eurovoc_lcsh_alignment_file(alignment_pin.path)
    capture = lcsh.capture_lcsh_authorities_by_iri_from_gzip_path(
        bulk_pin.path,
        source_url=bulk_pin.source_iri,
        concept_iris=alignment.lcsh_concept_iris,
    )
    if len(capture.records) != LCSH_ALIGNMENT_ENDPOINT_COUNT:
        raise ValueError(
            f"aligned LCSH endpoint count differs: expected "
            f"{LCSH_ALIGNMENT_ENDPOINT_COUNT}, observed {len(capture.records)}"
        )

    record_iris = {record.concept_iri for record in capture.records}
    resources = tuple(
        RegistryResource(
            iri=record.concept_iri,
            labels=_english_labels(record),
            native_payload={
                "authorityTypes": list(record.authority_types),
                "broaderIris": list(record.broader_iris),
                "captureSelection": {
                    "alignmentDigest": alignment_pin.sha256,
                    "alignmentRelease": EUROVOC_LCSH_ALIGNMENT_RELEASE_IRI,
                },
                "lccn": record.lccn,
                "lineNumber": record.line_number,
                "recordByteLength": record.source_byte_length,
                "recordDigest": record.source_sha256,
            },
            source_locator=f"{record.source_url}#line-{record.line_number}",
            source_digest=record.source_sha256,
            notations=(() if record.lccn is None else (record.lccn,)),
            status="alignmentEndpoint",
        )
        for record in capture.records
    )
    relations = tuple(
        RegistryRelation(
            subject=record.concept_iri,
            predicate="http://www.w3.org/2004/02/skos/core#broader",
            object=broader,
            source_payload={
                "lineNumber": record.line_number,
                "objectIri": broader,
                "predicateIri": "http://www.w3.org/2004/02/skos/core#broader",
                "subjectIri": record.concept_iri,
            },
        )
        for record in capture.records
        for broader in record.broader_iris
        if broader in record_iris
    )
    type_counts = Counter(
        authority_type
        for record in capture.records
        for authority_type in record.authority_types
        if authority_type != "madsrdf:Authority"
    )
    inputs = (bulk_pin, alignment_pin)
    return RegistryRelease(
        key="lcsh-eurovoc-alignment-endpoints-2026-08-06",
        resource_id="lcsh-subjects",
        source_module="refspec.registry.lcsh_topical",
        profile="conceptScheme",
        ring="subject",
        scope="captureSubset",
        issued=LCSH_BULK_CAPTURED_AT,
        source_release_iri=(
            "urn:ref:source-release:lcsh-subjects:"
            "eurovoc-alignment-endpoints:2026-08-06"
        ),
        source_release_digest=_input_set_digest(inputs),
        atlas_release_iri=(
            "urn:ref:atlas-release:3:lcsh-subjects:"
            "eurovoc-alignment-endpoints:2026-08-06"
        ),
        scheme_iri="urn:ref:atlas-resource-scheme:lcsh-subjects",
        inputs=inputs,
        resources=resources,
        relations=relations,
        dropped_label_count=sum(
            label.language.casefold() != "en"
            for record in capture.records
            for label in record.variant_labels
        ),
        metadata={
            "authorityTypeCounts": dict(sorted(type_counts.items())),
            "completePublisherRelease": False,
            "linesScanned": capture.lines_scanned,
            "mappingEndpointSubset": True,
            "publisherBulkDigest": bulk_pin.sha256,
            "publisherReleaseUnspecified": True,
            "selectionAlignmentDigest": alignment_pin.sha256,
            "selectionRule": "all-object-iris-in-official-eurovoc-lcsh-alignment",
        },
    )


def load_all_registry_alignment_endpoint_releases(
    source_root: Path = DEFAULT_SOURCE_ROOT,
    *,
    only_keys: Collection[str] | None = None,
) -> tuple[RegistryRelease, ...]:
    """Load selected endpoint subsets required by publisher alignments."""

    requested = normalize_only_keys(
        only_keys,
        allowed_keys=REGISTRY_ALIGNMENT_ENDPOINT_RELEASE_KEYS,
        loader_name="load_all_registry_alignment_endpoint_releases",
    )
    if not wants_group(requested, REGISTRY_ALIGNMENT_ENDPOINT_RELEASE_KEYS):
        return ()
    return select_declared_group(
        (load_lcsh_alignment_endpoint_release(source_root),),
        declared_keys=REGISTRY_ALIGNMENT_ENDPOINT_RELEASE_KEYS,
        requested_keys=requested,
        loader_name="load_lcsh_alignment_endpoint_release",
    )


def load_all_registry_mapping_releases(
    source_root: Path = DEFAULT_SOURCE_ROOT,
    *,
    only_keys: Collection[str] | None = None,
) -> tuple[RegistryMappingRelease, ...]:
    """Load selected separately pinned publisher mapping releases."""

    requested = normalize_only_keys(
        only_keys,
        allowed_keys=REGISTRY_MAPPING_RELEASE_KEYS,
        loader_name="load_all_registry_mapping_releases",
    )
    if not wants_group(requested, REGISTRY_MAPPING_RELEASE_KEYS):
        return ()
    return select_declared_group(
        (load_eurovoc_lcsh_mapping_release(source_root),),
        declared_keys=REGISTRY_MAPPING_RELEASE_KEYS,
        requested_keys=requested,
        loader_name="load_eurovoc_lcsh_mapping_release",
    )


__all__ = [
    "ATLAS_MAPPING_ADOPTION_DECISION_DATE",
    "ATLAS_MAPPING_ADOPTION_REVIEWER_IRI",
    "DEFAULT_SOURCE_ROOT",
    "EUROVOC_LCSH_MAPPING_COUNT",
    "LCSH_ALIGNMENT_ENDPOINT_COUNT",
    "LCSH_BULK_BYTE_LENGTH",
    "LCSH_BULK_CAPTURED_AT",
    "LCSH_BULK_FILENAME",
    "LCSH_BULK_SHA256",
    "REGISTRY_ALIGNMENT_ENDPOINT_RELEASE_KEYS",
    "REGISTRY_MAPPING_RELEASE_KEYS",
    "load_all_registry_alignment_endpoint_releases",
    "load_all_registry_mapping_releases",
    "load_eurovoc_lcsh_mapping_release",
    "load_lcsh_alignment_endpoint_release",
]
