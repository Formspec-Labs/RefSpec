"""Subject-ring mapping releases sourced from GEMET and Northwestern."""

from __future__ import annotations

import gzip
import json
import urllib.parse
from collections import Counter
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType

from rdflib.namespace import SKOS

from refspec.atlas.v3_registry_alignments import GEMET_EUROVOC_S46_REFUSALS
from refspec.atlas.v3_registry_selection import normalize_only_keys, select_declared_group, wants_group
from refspec.atlas.v3_registry_vocabularies import load_mesh_2026_release
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
from refspec.registry import gemet_alignments as gemet
from refspec.registry import lcsh_mesh_mapping as mesh_lcsh
from refspec.registry import lcsh_topical as lcsh
from refspec.registry import umthes_content as umthes
from refspec.vocabulary import is_english_language_tag

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_SOURCE_ROOT = REPOSITORY_ROOT / "output" / "registry-real-data-sources"

GEMET_ATLAS_RELEASE_IRI = "urn:ref:atlas-release:3:gemet:4.2.3"
EUROVOC_ATLAS_RELEASE_IRI = "urn:ref:atlas-release:3:eurovoc:4.24"
MESH_ATLAS_RELEASE_IRI = "urn:ref:atlas-release:3:mesh-descriptors:2026"
LCSH_MESH_ENDPOINT_ATLAS_RELEASE_IRI = "urn:ref:atlas-release:3:lcsh-subjects:mesh-mapping-endpoints:2026-08-15"
UMTHES_ENDPOINT_ATLAS_RELEASE_IRI = "urn:ref:atlas-release:3:umthes:gemet-endpoints:2026-08-15"
UMTHES_ENDPOINT_RELEASE_KEY = "umthes-gemet-endpoints-2026-08-15"
GEMET_UMTHES_MAPPING_RELEASE_KEY = "gemet-umthes-alignments-4.2.3"

GEMET_PUBLISHER_ATTESTOR_IRI = "urn:ref:atlas-source-descriptor:gemet"
GEMET_ASSERTED_AT = "2021-12-06T13:37:25+00:00"
LCSH_MESH_ADOPTED_BY = "urn:ref:actor:atlas-3-northwestern-lcsh-mesh-adoption"
LCSH_MESH_ADOPTED_AT = "2026-08-15T00:00:00+00:00"

LCSH_BULK_FILENAME = "lcsh-subjects-madsrdf-2026-08-06.jsonld.gz"
LCSH_BULK_SHA256 = "sha256:b33adc284bfb98e39c1331927e9ffee3d73dd0b1b83342906b6ea52c408a5856"
LCSH_BULK_BYTE_LENGTH = 140_187_915
LCSH_BULK_RETRIEVED_AT = "2026-08-06"
LCSH_LICENSE_STATEMENT = "publisher states no license"

MESH_2026_FILENAME = "desc2026.xml"
MESH_2026_SOURCE_URL = "https://nlmpubs.nlm.nih.gov/projects/mesh/MESH_FILES/xmlmesh/desc2026.xml"
MESH_2026_SHA256 = "sha256:9b034cad8bbd4d8d1ef43816d6fd78d33fada52eddff2a0b4455b1fca35cc5ba"
MESH_2026_BYTE_LENGTH = 312_952_703
MESH_2026_RETRIEVED_AT = "2026-08-03"

EXPECTED_GEMET_EUROVOC_PUBLISHER_MAPPING_COUNT = 1_938
EXPECTED_GEMET_EUROVOC_MAPPING_COUNT = 1_936
EXPECTED_GEMET_EXTERNAL_MAPPING_COUNT = gemet.EXPECTED_MAPPING_COUNT - EXPECTED_GEMET_EUROVOC_PUBLISHER_MAPPING_COUNT
EXPECTED_GEMET_UMTHES_MAPPING_COUNT = 3_470
EXPECTED_GEMET_UMTHES_UNAVAILABLE_MAPPING_COUNT = 13
EXPECTED_UMTHES_ENDPOINT_COUNT = 3_365
EXPECTED_UMTHES_LABEL_COUNTS_BY_LANGUAGE = MappingProxyType({"de": 11_127, "en": 6_116})
EXPECTED_UMTHES_RELATION_COUNT = 4_900
EXPECTED_UMTHES_DEPRECATED_ENDPOINT_COUNT = 974
EXPECTED_LCSH_MESH_ENDPOINT_COUNT = 12_844
EXPECTED_LCSH_MESH_MAPPING_COUNT = 13_251
EXPECTED_LCSH_MESH_SUBJECT_COUNT = 12_694
EXPECTED_LCSH_MESH_PREDICATE_COUNTS = MappingProxyType(
    {
        str(SKOS.exactMatch): 13_053,
        str(SKOS.broadMatch): 134,
        str(SKOS.narrowMatch): 35,
        str(SKOS.relatedMatch): 29,
    }
)
EXPECTED_LCSH_MESH_UNAVAILABLE_MAPPING_COUNT = 19

# The existing LCSH parser remains the oracle.  These are the only two exact
# records for which this larger endpoint set deliberately accepts a weaker
# normalization: one duplicate identical variant is collapsed, and one blank
# node broader target is retained only in native payload because Atlas relation
# endpoints must be IRIs.  Any third divergence fails the load.
LCSH_ENDPOINT_ORACLE_DIVERGENCES = MappingProxyType(
    {
        "http://id.loc.gov/authorities/subjects/sh2017000370": "duplicate-identical-variant-label",
        "http://id.loc.gov/authorities/subjects/sh85122121": "blank-node-broader-target",
    }
)

# UMTHES publishes these 25 associative pairs in both directions while its
# held endpoint subset also connects each pair through skos:broader/narrower.
# SKOS S27 forbids publishing both views as SKOS relations.  Preserve the
# authored associations as atlas:thesaurusRelated and fail if the pinned source
# no longer produces this exact frozen set.
UMTHES_S27_RELATED_PAIRS = frozenset(
    {
        ("https://sns.uba.de/umthes/_00001406", "https://sns.uba.de/umthes/_00019176"),
        ("https://sns.uba.de/umthes/_00001669", "https://sns.uba.de/umthes/_00005454"),
        ("https://sns.uba.de/umthes/_00005312", "https://sns.uba.de/umthes/_00005454"),
        ("https://sns.uba.de/umthes/_00008137", "https://sns.uba.de/umthes/_00008167"),
        ("https://sns.uba.de/umthes/_00008540", "https://sns.uba.de/umthes/_00016221"),
        ("https://sns.uba.de/umthes/_00010436", "https://sns.uba.de/umthes/_00028827"),
        ("https://sns.uba.de/umthes/_00011329", "https://sns.uba.de/umthes/_00011345"),
        ("https://sns.uba.de/umthes/_00012333", "https://sns.uba.de/umthes/_00027148"),
        ("https://sns.uba.de/umthes/_00014642", "https://sns.uba.de/umthes/_00049796"),
        ("https://sns.uba.de/umthes/_00019864", "https://sns.uba.de/umthes/_00025839"),
        ("https://sns.uba.de/umthes/_00019864", "https://sns.uba.de/umthes/_00046593"),
        ("https://sns.uba.de/umthes/_00021508", "https://sns.uba.de/umthes/_00031070"),
        ("https://sns.uba.de/umthes/_00023467", "https://sns.uba.de/umthes/_00028879"),
        ("https://sns.uba.de/umthes/_00024463", "https://sns.uba.de/umthes/_00026565"),
        ("https://sns.uba.de/umthes/_00024489", "https://sns.uba.de/umthes/_00051534"),
        ("https://sns.uba.de/umthes/_00025128", "https://sns.uba.de/umthes/_00025357"),
        ("https://sns.uba.de/umthes/_00025368", "https://sns.uba.de/umthes/_00025839"),
        ("https://sns.uba.de/umthes/_00025839", "https://sns.uba.de/umthes/_00040695"),
        ("https://sns.uba.de/umthes/_00025839", "https://sns.uba.de/umthes/_00046593"),
        ("https://sns.uba.de/umthes/_00028753", "https://sns.uba.de/umthes/_00028879"),
        ("https://sns.uba.de/umthes/_00030278", "https://sns.uba.de/umthes/_00049885"),
        ("https://sns.uba.de/umthes/_00031310", "https://sns.uba.de/umthes/_00040993"),
        ("https://sns.uba.de/umthes/_00040578", "https://sns.uba.de/umthes/_00051500"),
        ("https://sns.uba.de/umthes/_00040578", "https://sns.uba.de/umthes/_00051501"),
        ("https://sns.uba.de/umthes/_00040695", "https://sns.uba.de/umthes/_00046593"),
    }
)
UMTHES_S27_RELATED_PAIR_DIGEST = "sha256:47d7ff80a1ec4525cec72a723b6100182f8cc210031beef54d1d4bebfb4f732b"
ATLAS_THESAURUS_RELATED = "https://refspec.org/ns/atlas/v3#thesaurusRelated"

GEMET_MAPPING_POLICY = MappingProxyType(
    {
        "admission": (
            "preserve GEMET-to-EuroVoc SKOS mapping predicates verbatim except "
            "the frozen non-exact claims that conflict with the combined exactMatch "
            "components under SKOS S46; account for every external-target row"
        ),
        "direction": "publisher direction only; no minted inverse and no transitive closure",
        "externalEndpoints": (
            "AGROVOC, UMTHES, DBpedia, and Eionet determination rows remain in the "
            "verified capture until Atlas holds source-faithful endpoint resources"
        ),
        "version": "atlas-3-gemet-eurovoc-publisher-assertions-v2",
    }
)
LCSH_MESH_MAPPING_POLICY = MappingProxyType(
    {
        "admission": (
            "translate only MARC 750 corresponding-heading rows with one MeSH descriptor "
            "and one active LCSH authority; preserve explicit BM, NM, and RM strength"
        ),
        "direction": "MeSH authority record to LCSH target only; no inverse and no closure",
        "refusal": (
            "count 780 subdivision components, 788 search instructions, compound MeSH "
            "identifiers, unresolved targets, and non-LCSH indicators without emitting them"
        ),
        "serving": (
            "REF-035 computes standing from endpoint ownership; the adopting actor owns "
            "neither endpoint, so these asserted E3 rows remain opt-in"
        ),
        "version": "atlas-3-northwestern-mesh-lcsh-e3-adoption-v1",
    }
)
GEMET_UMTHES_MAPPING_POLICY = MappingProxyType(
    {
        "admission": (
            "preserve GEMET SKOS mapping predicates when the separately pinned SNS response "
            "provides real UMTHES publisher content for the target"
        ),
        "direction": "preserve GEMET-to-UMTHES direction; no inverse and no closure",
        "endpointResolution": (
            "replace the retired data.uba.de/umt IRI with the current sns.uba.de/umthes IRI "
            "using the unchanged publisher concept identifier"
        ),
        "licensing": "record CC BY-NC 4.0 verbatim; licensing is not an admission gate",
        "version": "atlas-3-gemet-umthes-publisher-assertions-v1",
    }
)

REGISTRY_SUBJECT_ALIGNMENT_ENDPOINT_RELEASE_KEYS = frozenset(
    {"lcsh-mesh-mapping-endpoints-2026-08-15", UMTHES_ENDPOINT_RELEASE_KEY}
)
REGISTRY_SUBJECT_MAPPING_RELEASE_KEYS = frozenset(
    {
        "gemet-eurovoc-alignments-4.2.3",
        GEMET_UMTHES_MAPPING_RELEASE_KEY,
        "mesh-lcsh-mapping-2021-03-31",
    }
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


def _gemet_pin(source_root: Path) -> RegistryInputPin:
    return _pin(
        source_root,
        filename=gemet.GEMET_ALIGNMENT_FILENAME,
        sha256=gemet.GEMET_ALIGNMENT_SHA256,
        byte_length=gemet.GEMET_ALIGNMENT_BYTE_LENGTH,
        source_iri=gemet.GEMET_ALIGNMENT_SOURCE_URL,
        role="publisherMappingSource",
    )


def _umthes_pin(source_root: Path) -> RegistryInputPin:
    return _pin(
        source_root,
        filename=umthes.UMTHES_CAPTURE_FILENAME,
        sha256=umthes.UMTHES_CAPTURE_SHA256,
        byte_length=umthes.UMTHES_CAPTURE_BYTE_LENGTH,
        source_iri=umthes.UMTHES_CAPTURE_SOURCE_ROOT,
        role="publisherEndpointSource",
    )


def _mapping_pin(source_root: Path) -> RegistryInputPin:
    return _pin(
        source_root,
        filename=mesh_lcsh.LCSH_MESH_MAPPING_FILENAME,
        sha256=mesh_lcsh.LCSH_MESH_MAPPING_SHA256,
        byte_length=mesh_lcsh.LCSH_MESH_MAPPING_BYTE_LENGTH,
        source_iri=mesh_lcsh.LCSH_MESH_MAPPING_SOURCE_URL,
        role="thirdPartyMappingSource",
    )


def _mesh_pin(source_root: Path) -> RegistryInputPin:
    return _pin(
        source_root,
        filename=MESH_2026_FILENAME,
        sha256=MESH_2026_SHA256,
        byte_length=MESH_2026_BYTE_LENGTH,
        source_iri=MESH_2026_SOURCE_URL,
        role="subjectEndpointSource",
    )


def _lcsh_pin(source_root: Path) -> RegistryInputPin:
    return _pin(
        source_root,
        filename=LCSH_BULK_FILENAME,
        sha256=LCSH_BULK_SHA256,
        byte_length=LCSH_BULK_BYTE_LENGTH,
        source_iri=lcsh.LCSH_TOPICAL_MADS_NDJSON_URL,
        role="objectEndpointSource",
    )


def _input_set_digest(inputs: Sequence[RegistryInputPin]) -> str:
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


def load_gemet_eurovoc_mapping_release(
    source_root: Path = DEFAULT_SOURCE_ROOT,
) -> RegistryMappingRelease:
    """Load the immediately joinable GEMET-to-EuroVoc publisher assertions."""

    source = _gemet_pin(source_root)
    source.verify()
    capture = gemet.load_gemet_alignments(source.path)
    eurovoc_rows = tuple(row for row in capture.mappings if row.target_system == "eurovoc")
    if len(eurovoc_rows) != EXPECTED_GEMET_EUROVOC_PUBLISHER_MAPPING_COUNT:
        raise ValueError(
            "GEMET-to-EuroVoc publisher count drifted: expected "
            f"{EXPECTED_GEMET_EUROVOC_PUBLISHER_MAPPING_COUNT}, got {len(eurovoc_rows)}"
        )
    s46_refusals = GEMET_EUROVOC_S46_REFUSALS["gemet"]
    observed_claims = {(row.subject_iri, row.predicate_iri, row.object_iri) for row in eurovoc_rows}
    if not s46_refusals <= observed_claims:
        raise ValueError("GEMET-to-EuroVoc frozen SKOS S46 refusal list drifted")
    admitted_rows = tuple(
        row for row in eurovoc_rows if (row.subject_iri, row.predicate_iri, row.object_iri) not in s46_refusals
    )
    if len(admitted_rows) != EXPECTED_GEMET_EUROVOC_MAPPING_COUNT:
        raise ValueError("GEMET-to-EuroVoc emitted count drifted after SKOS S46 refusals")

    mappings = tuple(
        RegistryMapping(
            subject=row.subject_iri,
            predicate=row.predicate_iri,
            object=row.object_iri,
            subject_atlas_release_iri=GEMET_ATLAS_RELEASE_IRI,
            object_atlas_release_iri=EUROVOC_ATLAS_RELEASE_IRI,
            asserted_at=GEMET_ASSERTED_AT,
            evidence=(
                RegistryMappingEvidence(
                    source_locator=(
                        source.source_iri
                        + "#mapping-"
                        + mapping_triple_digest(
                            subject_iri=row.subject_iri,
                            predicate_iri=row.predicate_iri,
                            object_iri=row.object_iri,
                        ).removeprefix("sha256:")
                    ),
                    source_digest=source.sha256,
                    native_payload={
                        "mappingTripleDigest": mapping_triple_digest(
                            subject_iri=row.subject_iri,
                            predicate_iri=row.predicate_iri,
                            object_iri=row.object_iri,
                        ),
                        "objectIri": row.object_iri,
                        "predicateIri": row.predicate_iri,
                        "publisherClaim": {
                            "objectIri": row.object_iri,
                            "predicateIri": row.predicate_iri,
                            "sourceEncoding": "SKOS RDF/XML",
                            "subjectIri": row.subject_iri,
                        },
                        "subjectIri": row.subject_iri,
                    },
                    review_warrant="publisherAssertion",
                    reviewer_iri=GEMET_PUBLISHER_ATTESTOR_IRI,
                    attested_at=GEMET_ASSERTED_AT,
                ),
            ),
        )
        for row in admitted_rows
    )
    external_counts = {
        pair: sum(counts.values()) for pair, counts in capture.pair_predicate_counts.items() if pair != "eurovoc"
    }
    if sum(external_counts.values()) != EXPECTED_GEMET_EXTERNAL_MAPPING_COUNT:
        raise ValueError("GEMET external endpoint accounting drifted")
    return RegistryMappingRelease(
        key="gemet-eurovoc-alignments-4.2.3",
        resource_id="gemet-alignments",
        source_module="refspec.registry.gemet_alignments",
        ring="subject",
        scope="captureSubset",
        issued=gemet.GEMET_ALIGNMENT_ISSUED,
        source_release_iri="urn:ref:source-release:gemet-alignments:4.2.3",
        source_release_digest=source.sha256,
        inputs=(source,),
        mappings=mappings,
        editorial_policy=GEMET_MAPPING_POLICY,
        metadata={
            "completePublisherMappingCount": gemet.EXPECTED_MAPPING_COUNT,
            "decompressedByteLength": capture.rdf_byte_length,
            "decompressedDigest": capture.rdf_sha256,
            "externalEndpointCounts": external_counts,
            "externalEndpointDisposition": {
                "umthes": "emittedBySeparateContentfulEndpointAndMappingReleases",
                "remaining": "capturedByReaderPendingSourceFaithfulEndpointReleases",
            },
            "heldEndpointPair": "gemet-eurovoc",
            "heldEndpointPublisherAssertionCount": len(eurovoc_rows),
            "licenseStatement": capture.license_statement,
            "licenseUrl": capture.license_url,
            "retrievedAt": capture.retrieved_at,
            "rollingSourceUrl": False,
            "sourceByteLength": capture.source_byte_length,
            "sourceDigest": capture.source_sha256,
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
            "sourceUrl": capture.source_url,
            "umthesContentRightsNote": gemet.UMTHES_CONTENT_RIGHTS_NOTE,
            "versionedSourceUrl": True,
        },
    )


def _umthes_registry_labels(record: umthes.UmthesRecord) -> tuple[RegistryLabel, ...]:
    role_rank = {"preferred": 0, "alternate": 1, "hidden": 2}
    selected: dict[tuple[str, str], umthes.UmthesLabel] = {}
    for label in record.labels:
        key = (label.value, label.language)
        previous = selected.get(key)
        if previous is None or role_rank[label.role] < role_rank[previous.role]:
            selected[key] = label
    return tuple(
        RegistryLabel(
            value=label.value,
            role=label.role,  # type: ignore[arg-type]
            source_path=f"{record.source_url}#{label.predicate_iri}",
            language=label.language,
        )
        for label in sorted(
            selected.values(),
            key=lambda item: (role_rank[item.role], item.language, item.value),
        )
    )


def _umthes_registry_relation(
    record: umthes.UmthesRecord,
    relation: umthes.UmthesRelation,
) -> RegistryRelation:
    publisher_payload = {
        "objectIri": relation.object_iri,
        "predicateIri": relation.predicate_iri,
        "responseDigest": record.source_sha256,
        "subjectIri": record.concept_iri,
    }
    pair = tuple(sorted((record.concept_iri, relation.object_iri)))
    if relation.predicate_iri != str(SKOS.related) or pair not in UMTHES_S27_RELATED_PAIRS:
        return RegistryRelation(
            subject=record.concept_iri,
            predicate=relation.predicate_iri,
            object=relation.object_iri,
            source_payload=publisher_payload,
        )
    return RegistryRelation(
        subject=record.concept_iri,
        predicate=ATLAS_THESAURUS_RELATED,
        object=relation.object_iri,
        source_payload={
            "editorialTransformation": {
                "fromPredicate": str(SKOS.related),
                "reason": "SKOS-S27-hierarchy-path",
                "rule": "preserveAuthoredAssociationOutsideSkosProjection",
                "toPredicate": ATLAS_THESAURUS_RELATED,
            },
            "publisherRelation": publisher_payload,
        },
    )


def _umthes_assets(
    source_root: Path,
) -> tuple[RegistryRelease, RegistryMappingRelease]:
    source_root = Path(source_root)
    endpoint_pin = _umthes_pin(source_root)
    mapping_pin = _gemet_pin(source_root)
    endpoint_pin.verify()
    mapping_pin.verify()
    content = umthes.load_umthes_content_capture(endpoint_pin.path)
    mappings_capture = gemet.load_gemet_alignments(mapping_pin.path)
    if (
        len(content.records) != EXPECTED_UMTHES_ENDPOINT_COUNT
        or content.label_counts_by_language != dict(EXPECTED_UMTHES_LABEL_COUNTS_BY_LANGUAGE)
        or sum(record.deprecated for record in content.records) != EXPECTED_UMTHES_DEPRECATED_ENDPOINT_COUNT
    ):
        raise ValueError("UMTHES endpoint content shape drifted")
    held_current_iris = frozenset(record.concept_iri for record in content.records)
    endpoint_resources = tuple(
        RegistryResource(
            iri=record.concept_iri,
            labels=_umthes_registry_labels(record),
            native_payload={
                "definitions": [
                    {
                        "language": value.language,
                        "predicateIri": value.predicate_iri,
                        "value": value.value,
                    }
                    for value in record.definitions
                ],
                "deprecated": record.deprecated,
                "labels": [
                    {
                        "language": label.language,
                        "predicateIri": label.predicate_iri,
                        "role": label.role,
                        "value": label.value,
                    }
                    for label in record.labels
                ],
                "legacyIri": record.legacy_iri,
                "relations": [
                    {
                        "objectIri": relation.object_iri,
                        "predicateIri": relation.predicate_iri,
                    }
                    for relation in record.relations
                ],
                "responseByteLength": record.source_byte_length,
                "responseDigest": record.source_sha256,
                "retrievedAt": record.retrieved_at,
            },
            source_locator=record.source_url,
            source_digest=record.source_sha256,
            definition=next(
                (value.value for value in record.definitions if value.language == "en"),
                next((value.value for value in record.definitions if value.language == "de"), None),
            ),
            status=("deprecatedAlignmentEndpoint" if record.deprecated else "alignmentEndpoint"),
        )
        for record in content.records
    )
    publisher_label_count = sum(len(record.labels) for record in content.records)
    emitted_label_count = sum(len(resource.labels) for resource in endpoint_resources)
    relations = tuple(
        _umthes_registry_relation(record, relation)
        for record in content.records
        for relation in record.relations
        if relation.object_iri in held_current_iris
    )
    if len(relations) != EXPECTED_UMTHES_RELATION_COUNT:
        raise ValueError("UMTHES held-endpoint relation count drifted")
    transformed_s27_pairs = {
        tuple(sorted((relation.subject, relation.object)))
        for relation in relations
        if relation.predicate == ATLAS_THESAURUS_RELATED
    }
    transformed_s27_relation_count = sum(
        relation.predicate == ATLAS_THESAURUS_RELATED for relation in relations
    )
    if (
        transformed_s27_pairs != UMTHES_S27_RELATED_PAIRS
        or transformed_s27_relation_count != 2 * len(UMTHES_S27_RELATED_PAIRS)
    ):
        raise ValueError("UMTHES frozen SKOS S27 transformation list drifted")
    endpoint_inputs = (endpoint_pin, mapping_pin)
    endpoint_release = RegistryRelease(
        key=UMTHES_ENDPOINT_RELEASE_KEY,
        resource_id="umthes",
        source_module="refspec.registry.umthes_content",
        profile="conceptScheme",
        ring="subject",
        scope="captureSubset",
        issued="2026-08-15",
        source_release_iri=(
            "urn:ref:source-release:umthes:gemet-endpoints:" + endpoint_pin.sha256.removeprefix("sha256:")
        ),
        source_release_digest=_input_set_digest(endpoint_inputs),
        atlas_release_iri=UMTHES_ENDPOINT_ATLAS_RELEASE_IRI,
        scheme_iri="urn:ref:atlas-resource-scheme:umthes",
        inputs=endpoint_inputs,
        resources=endpoint_resources,
        relations=relations,
        metadata={
            "attributionStatement": umthes.UMTHES_ATTRIBUTION_STATEMENT,
            "captureByteLength": endpoint_pin.byte_length,
            "captureDigest": endpoint_pin.sha256,
            "capturedRelationCount": sum(len(record.relations) for record in content.records),
            "completePublisherRelease": False,
            "definitionCountsByLanguage": content.definition_counts_by_language,
            "duplicateAcrossRoleLabelClaimCount": publisher_label_count - emitted_label_count,
            "emittedLabelCount": emitted_label_count,
            "emittedRelationCount": len(relations),
            "endpointOwnershipPreference": "publisherOwnedVocabulary",
            "labelCountsByLanguage": content.label_counts_by_language,
            "licenseStatement": umthes.UMTHES_LICENSE_STATEMENT,
            "licenseSource": {
                "byteLength": content.license_source_byte_length,
                "retrievedAt": content.retrieved_at,
                "sha256": content.license_source_sha256,
                "url": umthes.UMTHES_LICENSE_SOURCE_URL,
            },
            "licenseUrl": umthes.UMTHES_LICENSE_URL,
            "licensingIsAdmissionGate": False,
            "mappingEndpointSubset": True,
            "publisherRecordCount": len(content.records),
            "publisherLabelCount": publisher_label_count,
            "retrievedAt": content.retrieved_at,
            "sourceIdentifierCount": 0,
            "sourceUrlRoot": umthes.UMTHES_CAPTURE_SOURCE_ROOT,
            "skosS27Transformation": {
                "frozenConflictList": {
                    "canonicalItemShape": {"leftIri": "IRI", "rightIri": "IRI"},
                    "count": len(UMTHES_S27_RELATED_PAIRS),
                    "digest": UMTHES_S27_RELATED_PAIR_DIGEST,
                },
                "publisherRelationCount": transformed_s27_relation_count,
                "reason": "SKOS-S27-hierarchy-path",
                "toPredicateIri": ATLAS_THESAURUS_RELATED,
            },
            "unavailableEndpointCount": len(content.unavailable_records),
            "unavailableEndpoints": list(content.unavailable_records),
            "unavailableEndpointReason": "publisher returned HTTP 404; no stub emitted",
            "unemittedRelationCount": sum(len(record.relations) for record in content.records) - len(relations),
            "unemittedRelationReason": "target publisher content is outside the GEMET-selected capture; no stub emitted",
        },
    )

    held_legacy_iris = frozenset(record.legacy_iri for record in content.records)
    umthes_rows = tuple(row for row in mappings_capture.mappings if row.target_system == "umthes")
    admitted_rows = tuple(row for row in umthes_rows if row.object_iri in held_legacy_iris)
    unavailable_rows = tuple(row for row in umthes_rows if row.object_iri not in held_legacy_iris)
    if (
        len(admitted_rows) != EXPECTED_GEMET_UMTHES_MAPPING_COUNT
        or len(unavailable_rows) != EXPECTED_GEMET_UMTHES_UNAVAILABLE_MAPPING_COUNT
    ):
        raise ValueError("GEMET-to-UMTHES endpoint join shape drifted")
    mappings = tuple(
        RegistryMapping(
            subject=row.subject_iri,
            predicate=row.predicate_iri,
            object=umthes.current_iri_for_legacy(row.object_iri),
            subject_atlas_release_iri=GEMET_ATLAS_RELEASE_IRI,
            object_atlas_release_iri=UMTHES_ENDPOINT_ATLAS_RELEASE_IRI,
            asserted_at=GEMET_ASSERTED_AT,
            evidence=(
                RegistryMappingEvidence(
                    source_locator=(
                        mapping_pin.source_iri
                        + "#mapping-"
                        + mapping_triple_digest(
                            subject_iri=row.subject_iri,
                            predicate_iri=row.predicate_iri,
                            object_iri=row.object_iri,
                        ).removeprefix("sha256:")
                    ),
                    source_digest=mapping_pin.sha256,
                    native_payload={
                        "endpointResolution": {
                            "fromObjectIri": row.object_iri,
                            "method": "publisherNamespaceMigrationByStableLocalIdentifier",
                            "predicateChanged": False,
                            "toObjectIri": umthes.current_iri_for_legacy(row.object_iri),
                        },
                        "mappingTripleDigest": mapping_triple_digest(
                            subject_iri=row.subject_iri,
                            predicate_iri=row.predicate_iri,
                            object_iri=umthes.current_iri_for_legacy(row.object_iri),
                        ),
                        "objectIri": umthes.current_iri_for_legacy(row.object_iri),
                        "predicateIri": row.predicate_iri,
                        "publisherClaim": {
                            "objectIri": row.object_iri,
                            "predicateIri": row.predicate_iri,
                            "sourceEncoding": "SKOS RDF/XML",
                            "subjectIri": row.subject_iri,
                        },
                        "subjectIri": row.subject_iri,
                    },
                    review_warrant="publisherAssertion",
                    reviewer_iri=GEMET_PUBLISHER_ATTESTOR_IRI,
                    attested_at=GEMET_ASSERTED_AT,
                ),
            ),
        )
        for row in admitted_rows
    )
    mapping_release = RegistryMappingRelease(
        key=GEMET_UMTHES_MAPPING_RELEASE_KEY,
        resource_id="gemet-umthes-alignments",
        source_module="refspec.registry.gemet_alignments",
        ring="subject",
        scope="captureSubset",
        issued=gemet.GEMET_ALIGNMENT_ISSUED,
        source_release_iri="urn:ref:source-release:gemet-umthes-alignments:4.2.3",
        source_release_digest=mapping_pin.sha256,
        # The GEMET RDF proves the mapping. The UMTHES capture belongs to the
        # separately pinned target endpoint release.
        inputs=(mapping_pin,),
        mappings=mappings,
        editorial_policy=GEMET_UMTHES_MAPPING_POLICY,
        metadata={
            "admittedMappingCount": len(mappings),
            "attributionStatement": umthes.UMTHES_ATTRIBUTION_STATEMENT,
            "candidateMappingCount": len(umthes_rows),
            "gemetLicenseStatement": mappings_capture.license_statement,
            "gemetLicenseUrl": mappings_capture.license_url,
            "licenseStatement": umthes.UMTHES_LICENSE_STATEMENT,
            "licenseUrl": umthes.UMTHES_LICENSE_URL,
            "licensingIsAdmissionGate": False,
            "predicateCounts": dict(sorted(Counter(row.predicate for row in mappings).items())),
            "sourceIdentifierCount": 0,
            "unavailableMappingCount": len(unavailable_rows),
            "unavailableTargetIris": sorted({row.object_iri for row in unavailable_rows}),
            "unavailableTargetReason": "publisher returned HTTP 404; no stub or mapping emitted",
        },
    )
    return endpoint_release, mapping_release


def load_umthes_endpoint_release(
    source_root: Path = DEFAULT_SOURCE_ROOT,
) -> RegistryRelease:
    endpoint, _mapping = _umthes_assets(Path(source_root))
    return endpoint


def load_gemet_umthes_mapping_release(
    source_root: Path = DEFAULT_SOURCE_ROOT,
) -> RegistryMappingRelease:
    _endpoint, mapping = _umthes_assets(Path(source_root))
    return mapping


@dataclass(frozen=True, slots=True)
class _EndpointSelection:
    release: RegistryRelease
    active_iris: frozenset[str]
    unavailable_iris: frozenset[str]


def _plain_reference_list(value: object, *, label: str) -> tuple[Mapping[str, object], ...]:
    if value is None:
        return ()
    if isinstance(value, Mapping):
        return (value,)
    if isinstance(value, list) and all(isinstance(item, Mapping) for item in value):
        return tuple(value)
    raise ValueError(f"{label} must be a JSON-LD reference or list of references")


def _plain_language_label(value: object, *, label: str) -> lcsh.LcshTopicalLabel:
    if not isinstance(value, Mapping):
        raise ValueError(f"{label} must be a language-tagged JSON-LD literal")
    text = value.get("@value")
    language = value.get("@language")
    if not isinstance(text, str) or not text or not isinstance(language, str) or not language:
        raise ValueError(f"{label} must have a non-empty value and language")
    return lcsh.LcshTopicalLabel(value=text, language=language)


def _fallback_lcsh_record(
    raw_line: bytes,
    *,
    concept_iri: str,
    source_url: str,
    line_number: int,
) -> lcsh.LcshTopicalRecord:
    """Normalize one frozen oracle divergence without broadening the parser."""

    document = json.loads(raw_line)
    if document.get("@context") != lcsh.LCSH_EXPECTED_CONTEXT_URL:
        raise ValueError(f"fallback LCSH record {concept_iri} changed context")
    graph = document.get("@graph")
    if not isinstance(graph, list):
        raise ValueError(f"fallback LCSH record {concept_iri} has no graph")
    by_id = {node.get("@id"): node for node in graph if isinstance(node, Mapping) and isinstance(node.get("@id"), str)}
    authority = by_id.get(concept_iri)
    if not isinstance(authority, Mapping):
        raise ValueError(f"fallback LCSH record {concept_iri} has no authority node")
    types_value = authority.get("@type")
    types = {types_value} if isinstance(types_value, str) else set(types_value or [])
    if "madsrdf:Authority" not in types:
        raise ValueError(f"fallback LCSH record {concept_iri} is not active")
    preferred = _plain_language_label(
        authority.get("madsrdf:authoritativeLabel"),
        label=f"{concept_iri} authoritative label",
    )
    variants = []
    for reference in _plain_reference_list(
        authority.get("madsrdf:hasVariant"),
        label=f"{concept_iri} variants",
    ):
        variant = by_id.get(reference.get("@id"))
        if not isinstance(variant, Mapping):
            raise ValueError(f"fallback LCSH record {concept_iri} has a dangling variant")
        variants.append(
            _plain_language_label(
                variant.get("madsrdf:variantLabel"),
                label=f"{concept_iri} variant label",
            )
        )
    broader_iris = tuple(
        sorted(
            {
                target
                for reference in _plain_reference_list(
                    authority.get("madsrdf:hasBroaderAuthority"),
                    label=f"{concept_iri} broader targets",
                )
                if isinstance((target := reference.get("@id")), str) and urllib.parse.urlsplit(target).scheme
            }
        )
    )
    lccn = authority.get("identifiers:lccn")
    if lccn is not None and not isinstance(lccn, str):
        raise ValueError(f"fallback LCSH record {concept_iri} has a malformed LCCN")
    return lcsh.LcshTopicalRecord(
        concept_iri=concept_iri,
        lccn=lccn,
        preferred_label=preferred,
        variant_labels=tuple(sorted(set(variants), key=lambda item: (item.language, item.value))),
        broader_iris=broader_iris,
        authority_types=tuple(sorted(types)),
        source_url=source_url,
        line_number=line_number,
        raw_line=raw_line.rstrip(b"\r\n"),
    )


def _english_labels(record: lcsh.LcshTopicalRecord) -> tuple[RegistryLabel, ...]:
    if not is_english_language_tag(record.preferred_label.language):
        raise ValueError(f"LCSH endpoint has no English preferred label: {record.concept_iri}")
    labels = [
        RegistryLabel(
            value=record.preferred_label.value.strip(),
            role="preferred",
            source_path=f"line-{record.line_number}:madsrdf:authoritativeLabel",
        )
    ]
    seen = {labels[0].value}
    for index, label in enumerate(record.variant_labels):
        if not is_english_language_tag(label.language):
            continue
        value = label.value.strip()
        if not value or value in seen:
            continue
        seen.add(value)
        labels.append(
            RegistryLabel(
                value=value,
                role="alternate",
                source_path=f"line-{record.line_number}:madsrdf:hasVariant[{index}]",
            )
        )
    return tuple(labels)


def _document_iri(document: Mapping[str, object]) -> str | None:
    value = document.get("@id")
    prefix = "/authorities/subjects/"
    if not isinstance(value, str) or not value.startswith(prefix):
        return None
    return lcsh.LCSH_SUBJECTS_SCHEME_IRI + "/" + value.removeprefix(prefix)


def _active_authority(document: Mapping[str, object], concept_iri: str) -> bool:
    graph = document.get("@graph")
    if not isinstance(graph, list):
        return False
    for node in graph:
        if not isinstance(node, Mapping) or node.get("@id") != concept_iri:
            continue
        value = node.get("@type")
        types = {value} if isinstance(value, str) else set(value or [])
        return "madsrdf:Authority" in types
    return False


def _load_lcsh_endpoint_selection(
    source_root: Path,
    *,
    requested_iris: Collection[str],
    inputs: tuple[RegistryInputPin, RegistryInputPin, RegistryInputPin],
) -> _EndpointSelection:
    lcsh_pin, mapping_pin, mesh_pin = inputs
    for source in inputs:
        source.verify()
    requested = frozenset(requested_iris)
    selected: dict[str, lcsh.LcshTopicalRecord] = {}
    unavailable: set[str] = set()
    oracle_divergences: dict[str, str] = {}
    lines_scanned = 0
    with gzip.open(lcsh_pin.path, "rb") as source:
        for line_number, line in enumerate(source, start=1):
            lines_scanned = line_number
            try:
                document = json.loads(line)
            except (UnicodeDecodeError, json.JSONDecodeError) as error:
                raise ValueError(f"LCSH bulk line {line_number} is not valid UTF-8 JSON: {error}") from error
            if not isinstance(document, Mapping):
                raise ValueError(f"LCSH bulk line {line_number} is not an object")
            concept_iri = _document_iri(document)
            if concept_iri not in requested:
                continue
            if concept_iri in selected or concept_iri in unavailable:
                raise ValueError(f"LCSH bulk repeats selected endpoint {concept_iri}")
            if not _active_authority(document, concept_iri):
                unavailable.add(concept_iri)
                continue
            try:
                record = lcsh.parse_lcsh_authority_ndjson_line(
                    line,
                    source_url=lcsh_pin.source_iri,
                    line_number=line_number,
                )
            except lcsh.LcshTopicalError:
                expected_divergence = LCSH_ENDPOINT_ORACLE_DIVERGENCES.get(concept_iri)
                if expected_divergence is None:
                    raise
                oracle_divergences[concept_iri] = expected_divergence
                record = _fallback_lcsh_record(
                    line,
                    concept_iri=concept_iri,
                    source_url=lcsh_pin.source_iri,
                    line_number=line_number,
                )
            if record is None or record.concept_iri != concept_iri:
                raise ValueError(f"LCSH endpoint parser did not return {concept_iri}")
            selected[concept_iri] = record
    absent = requested - selected.keys() - unavailable
    unavailable.update(absent)
    if oracle_divergences != dict(LCSH_ENDPOINT_ORACLE_DIVERGENCES):
        raise ValueError(
            "LCSH endpoint oracle divergence set drifted: "
            f"expected={dict(LCSH_ENDPOINT_ORACLE_DIVERGENCES)!r}, observed={oracle_divergences!r}"
        )

    record_iris = frozenset(selected)
    resources = tuple(
        RegistryResource(
            iri=record.concept_iri,
            labels=_english_labels(record),
            native_payload={
                "authorityTypes": list(record.authority_types),
                "broaderIris": list(record.broader_iris),
                "captureSelection": {
                    "mappingDigest": mapping_pin.sha256,
                    "meshEndpointDigest": mesh_pin.sha256,
                },
                "lccn": record.lccn,
                "lineNumber": record.line_number,
                "oracleDivergence": oracle_divergences.get(record.concept_iri),
                "recordByteLength": record.source_byte_length,
                "recordDigest": record.source_sha256,
            },
            source_locator=f"{record.source_url}#line-{record.line_number}",
            source_digest=record.source_sha256,
            notations=(() if record.lccn is None else (record.lccn,)),
            status="alignmentEndpoint",
        )
        for record in (selected[iri] for iri in sorted(selected))
    )
    relations = tuple(
        RegistryRelation(
            subject=record.concept_iri,
            predicate=str(SKOS.broader),
            object=broader,
            source_payload={
                "lineNumber": record.line_number,
                "objectIri": broader,
                "predicateIri": str(SKOS.broader),
                "subjectIri": record.concept_iri,
            },
        )
        for record in (selected[iri] for iri in sorted(selected))
        for broader in record.broader_iris
        if broader in record_iris
    )
    release = RegistryRelease(
        key="lcsh-mesh-mapping-endpoints-2026-08-15",
        resource_id="lcsh-subjects",
        source_module="refspec.registry.lcsh_topical",
        profile="conceptScheme",
        ring="subject",
        scope="captureSubset",
        issued="2026-08-15",
        source_release_iri=("urn:ref:source-release:lcsh-subjects:mesh-mapping-endpoints:2026-08-15"),
        source_release_digest=_input_set_digest(inputs),
        atlas_release_iri=LCSH_MESH_ENDPOINT_ATLAS_RELEASE_IRI,
        scheme_iri="urn:ref:atlas-resource-scheme:lcsh-subjects",
        inputs=inputs,
        resources=resources,
        relations=relations,
        dropped_label_count=sum(
            not is_english_language_tag(label.language)
            for record in selected.values()
            for label in record.variant_labels
        ),
        metadata={
            "activeEndpointCount": len(resources),
            "completePublisherRelease": False,
            "endpointOwnershipPreference": "publisherVocabularyViaThirdPartySelection",
            "licenseStatement": LCSH_LICENSE_STATEMENT,
            "mappingSelectionByteLength": mapping_pin.byte_length,
            "mappingSelectionDigest": mapping_pin.sha256,
            "mappingSelectionLicenseStatement": mesh_lcsh.LCSH_MESH_LICENSE_STATEMENT,
            "mappingSelectionLicenseUrl": mesh_lcsh.LCSH_MESH_LICENSE_URL,
            "mappingSelectionRetrievedAt": mesh_lcsh.LCSH_MESH_MAPPING_RETRIEVED_AT,
            "mappingSelectionSourceUrl": mapping_pin.source_iri,
            "meshSelectionByteLength": mesh_pin.byte_length,
            "meshSelectionDigest": mesh_pin.sha256,
            "meshSelectionRetrievedAt": MESH_2026_RETRIEVED_AT,
            "meshSelectionSourceUrl": mesh_pin.source_iri,
            "oracleDivergences": dict(sorted(oracle_divergences.items())),
            "publisherBulkByteLength": lcsh_pin.byte_length,
            "publisherBulkDigest": lcsh_pin.sha256,
            "publisherBulkRetrievedAt": LCSH_BULK_RETRIEVED_AT,
            "publisherBulkSourceUrl": lcsh_pin.source_iri,
            "publisherBulkVersionedSourceUrl": False,
            "publisherBulkVersionNote": (
                "publisher provides no versioned URL; the rolling download is pinned by digest and byte length"
            ),
            "requestedEndpointCount": len(requested),
            "selectionRule": "active LCSH targets of admitted mappings whose MeSH subject remains in 2026",
            "sourceIdentifierCount": 0,
            "unavailableEndpointCount": len(unavailable),
            "unavailableEndpointIris": sorted(unavailable),
            "linesScanned": lines_scanned,
        },
    )
    return _EndpointSelection(
        release=release,
        active_iris=record_iris,
        unavailable_iris=frozenset(unavailable),
    )


def _lcsh_mesh_assets(
    source_root: Path,
) -> tuple[RegistryRelease, RegistryMappingRelease]:
    mapping_pin = _mapping_pin(source_root)
    mesh_pin = _mesh_pin(source_root)
    lcsh_pin = _lcsh_pin(source_root)
    for source in (mapping_pin, mesh_pin, lcsh_pin):
        source.verify()
    capture = mesh_lcsh.load_lcsh_mesh_mapping(mapping_pin.path)
    mesh_release = load_mesh_2026_release(source_root)
    if mesh_release.atlas_release_iri != MESH_ATLAS_RELEASE_IRI:
        raise ValueError("MeSH endpoint release identity drifted")
    mesh_iris = frozenset(resource.iri for resource in mesh_release.resources)
    current_mesh_rows = tuple(row for row in capture.mappings if row.subject_iri in mesh_iris)
    requested_lcsh_iris = {row.object_iri for row in current_mesh_rows}
    endpoint_inputs = (lcsh_pin, mapping_pin, mesh_pin)
    selection = _load_lcsh_endpoint_selection(
        source_root,
        requested_iris=requested_lcsh_iris,
        inputs=endpoint_inputs,
    )
    admitted_rows = tuple(row for row in current_mesh_rows if row.object_iri in selection.active_iris)
    unavailable_rows = len(capture.mappings) - len(admitted_rows)
    if (
        len(selection.release.resources) != EXPECTED_LCSH_MESH_ENDPOINT_COUNT
        or len(admitted_rows) != EXPECTED_LCSH_MESH_MAPPING_COUNT
        or len({row.subject_iri for row in admitted_rows}) != EXPECTED_LCSH_MESH_SUBJECT_COUNT
        or Counter(row.predicate_iri for row in admitted_rows) != EXPECTED_LCSH_MESH_PREDICATE_COUNTS
        or unavailable_rows != EXPECTED_LCSH_MESH_UNAVAILABLE_MAPPING_COUNT
    ):
        raise ValueError("current LCSH--MeSH endpoint join shape drifted")

    mappings = tuple(
        RegistryMapping(
            subject=row.subject_iri,
            predicate=row.predicate_iri,
            object=row.object_iri,
            subject_atlas_release_iri=MESH_ATLAS_RELEASE_IRI,
            object_atlas_release_iri=LCSH_MESH_ENDPOINT_ATLAS_RELEASE_IRI,
            asserted_at=LCSH_MESH_ADOPTED_AT,
            evidence=tuple(
                RegistryMappingEvidence(
                    source_locator=(
                        mapping_pin.source_iri
                        + f"#record-{field.record_index}-mapping-field-{field.mapping_field_index}"
                    ),
                    source_digest=mapping_pin.sha256,
                    native_payload={
                        "mappingTripleDigest": mapping_triple_digest(
                            subject_iri=row.subject_iri,
                            predicate_iri=row.predicate_iri,
                            object_iri=row.object_iri,
                        ),
                        "objectIri": row.object_iri,
                        "operatorAdoption": {
                            "adoptedBy": LCSH_MESH_ADOPTED_BY,
                            "fromPredicateIri": row.source_predicate_iri,
                            "toPredicateIri": row.predicate_iri,
                        },
                        "predicateIri": row.predicate_iri,
                        "publisherClaim": {
                            "nativeField": field.native_payload(),
                            "objectIri": row.object_iri,
                            "predicateIri": row.source_predicate_iri,
                            "sourceEncoding": "MARCXML",
                            "subjectIri": row.subject_iri,
                            "translationBasis": row.translation_basis,
                        },
                        "subjectIri": row.subject_iri,
                    },
                    review_warrant="operatorAdoption",
                    reviewer_iri=LCSH_MESH_ADOPTED_BY,
                    attested_at=LCSH_MESH_ADOPTED_AT,
                )
                for field in row.source_fields
            ),
        )
        for row in admitted_rows
    )
    mapping_release = RegistryMappingRelease(
        key="mesh-lcsh-mapping-2021-03-31",
        resource_id="northwestern-mesh-lcsh-mapping",
        source_module="refspec.registry.lcsh_mesh_mapping",
        ring="subject",
        scope="captureSubset",
        issued=mesh_lcsh.LCSH_MESH_MAPPING_ISSUED,
        source_release_iri="urn:ref:source-release:northwestern-mesh-lcsh-mapping:v1.0.0",
        source_release_digest=mapping_pin.sha256,
        # Northwestern's MARCXML proves each adopted mapping. MeSH and LCSH
        # source bytes belong to the endpoint releases named by the mappings.
        inputs=(mapping_pin,),
        mappings=mappings,
        editorial_policy=LCSH_MESH_MAPPING_POLICY,
        metadata={
            "acceptedSourceFieldCount": capture.accepted_source_field_count,
            "admittedCurrentEndpointMappingCount": len(mappings),
            "candidateMappingCount": len(capture.mappings),
            "licenseStatement": mesh_lcsh.LCSH_MESH_LICENSE_STATEMENT,
            "licenseUrl": mesh_lcsh.LCSH_MESH_LICENSE_URL,
            "linkingFieldCount": capture.linking_field_count,
            "linkingRecordCount": capture.linking_record_count,
            "marcTranslation": {
                "field": mesh_lcsh.MARC_750_FIELD_IRI,
                "relationCodes": dict(mesh_lcsh.MARC_RELATION_CODE_TO_SKOS),
                "relationTexts": dict(mesh_lcsh.MARC_RELATION_TEXT_TO_SKOS),
                "unqualified750": str(SKOS.exactMatch),
            },
            "observedRecordCount": capture.record_count,
            "publisherDeclaredRecordCount": mesh_lcsh.PUBLISHER_DECLARED_RECORD_COUNT,
            "refusalCounts": capture.refusal_counts,
            "retrievedAt": capture.retrieved_at,
            "sourceByteLength": capture.source_byte_length,
            "sourceDigest": capture.source_sha256,
            "sourceIdentifierCount": 0,
            "sourceUrl": capture.source_url,
            "unavailableCurrentEndpointMappingCount": unavailable_rows,
            "versionedSourceUrl": True,
            "workingFileRightsNote": mesh_lcsh.LCSH_MESH_WORKING_FILE_RIGHTS_NOTE,
        },
    )
    return selection.release, mapping_release


def load_lcsh_mesh_endpoint_release(
    source_root: Path = DEFAULT_SOURCE_ROOT,
) -> RegistryRelease:
    """Load current active LCSH endpoints required by the Northwestern mapping."""

    endpoint, _mapping = _lcsh_mesh_assets(Path(source_root))
    return endpoint


def load_lcsh_mesh_mapping_release(
    source_root: Path = DEFAULT_SOURCE_ROOT,
) -> RegistryMappingRelease:
    """Load the current-endpoint E3 subset of the Northwestern mapping."""

    _endpoint, mapping = _lcsh_mesh_assets(Path(source_root))
    return mapping


def load_subject_registry_alignment_endpoint_releases(
    source_root: Path = DEFAULT_SOURCE_ROOT,
    *,
    only_keys: Collection[str] | None = None,
) -> tuple[RegistryRelease, ...]:
    """Load selected subject mapping endpoint subsets."""

    requested = normalize_only_keys(
        only_keys,
        allowed_keys=REGISTRY_SUBJECT_ALIGNMENT_ENDPOINT_RELEASE_KEYS,
        loader_name="load_subject_registry_alignment_endpoint_releases",
    )
    if not wants_group(requested, REGISTRY_SUBJECT_ALIGNMENT_ENDPOINT_RELEASE_KEYS):
        return ()
    loaded: list[RegistryRelease] = []
    if requested is None or "lcsh-mesh-mapping-endpoints-2026-08-15" in requested:
        loaded.append(load_lcsh_mesh_endpoint_release(source_root))
    if requested is None or UMTHES_ENDPOINT_RELEASE_KEY in requested:
        loaded.append(load_umthes_endpoint_release(source_root))
    return select_declared_group(
        tuple(loaded),
        declared_keys=REGISTRY_SUBJECT_ALIGNMENT_ENDPOINT_RELEASE_KEYS,
        requested_keys=requested,
        loader_name="load_subject_registry_alignment_endpoint_releases",
    )


def load_subject_registry_mapping_releases(
    source_root: Path = DEFAULT_SOURCE_ROOT,
    *,
    only_keys: Collection[str] | None = None,
) -> tuple[RegistryMappingRelease, ...]:
    """Load selected GEMET and Northwestern subject mapping releases."""

    requested = normalize_only_keys(
        only_keys,
        allowed_keys=REGISTRY_SUBJECT_MAPPING_RELEASE_KEYS,
        loader_name="load_subject_registry_mapping_releases",
    )
    if not wants_group(requested, REGISTRY_SUBJECT_MAPPING_RELEASE_KEYS):
        return ()
    loaders = (
        ("gemet-eurovoc-alignments-4.2.3", lambda: load_gemet_eurovoc_mapping_release(source_root)),
        (GEMET_UMTHES_MAPPING_RELEASE_KEY, lambda: load_gemet_umthes_mapping_release(source_root)),
        ("mesh-lcsh-mapping-2021-03-31", lambda: load_lcsh_mesh_mapping_release(source_root)),
    )
    loaded = tuple(loader() for key, loader in loaders if requested is None or key in requested)
    expected = REGISTRY_SUBJECT_MAPPING_RELEASE_KEYS if requested is None else requested
    observed = [release.key for release in loaded]
    if len(observed) != len(set(observed)) or set(observed) != set(expected):
        raise ValueError(
            "load_subject_registry_mapping_releases topology differs: "
            f"expected={sorted(expected)!r}, observed={sorted(observed)!r}"
        )
    return loaded


__all__ = [
    "DEFAULT_SOURCE_ROOT",
    "EUROVOC_ATLAS_RELEASE_IRI",
    "EXPECTED_GEMET_EUROVOC_MAPPING_COUNT",
    "EXPECTED_GEMET_UMTHES_MAPPING_COUNT",
    "EXPECTED_LCSH_MESH_ENDPOINT_COUNT",
    "EXPECTED_LCSH_MESH_MAPPING_COUNT",
    "EXPECTED_LCSH_MESH_PREDICATE_COUNTS",
    "EXPECTED_LCSH_MESH_SUBJECT_COUNT",
    "EXPECTED_LCSH_MESH_UNAVAILABLE_MAPPING_COUNT",
    "GEMET_ATLAS_RELEASE_IRI",
    "GEMET_MAPPING_POLICY",
    "GEMET_PUBLISHER_ATTESTOR_IRI",
    "GEMET_UMTHES_MAPPING_POLICY",
    "GEMET_UMTHES_MAPPING_RELEASE_KEY",
    "LCSH_ENDPOINT_ORACLE_DIVERGENCES",
    "LCSH_MESH_ADOPTED_AT",
    "LCSH_MESH_ADOPTED_BY",
    "LCSH_MESH_ENDPOINT_ATLAS_RELEASE_IRI",
    "LCSH_MESH_MAPPING_POLICY",
    "MESH_ATLAS_RELEASE_IRI",
    "REGISTRY_SUBJECT_ALIGNMENT_ENDPOINT_RELEASE_KEYS",
    "REGISTRY_SUBJECT_MAPPING_RELEASE_KEYS",
    "UMTHES_ENDPOINT_ATLAS_RELEASE_IRI",
    "UMTHES_ENDPOINT_RELEASE_KEY",
    "load_gemet_eurovoc_mapping_release",
    "load_gemet_umthes_mapping_release",
    "load_lcsh_mesh_endpoint_release",
    "load_lcsh_mesh_mapping_release",
    "load_subject_registry_alignment_endpoint_releases",
    "load_subject_registry_mapping_releases",
    "load_umthes_endpoint_release",
]
