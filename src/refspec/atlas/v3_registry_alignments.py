"""Publisher mapping releases and the exact endpoint subsets they require."""

from __future__ import annotations

from collections import Counter
from collections.abc import Collection, Mapping
from dataclasses import replace
from pathlib import Path
from types import MappingProxyType
from urllib.parse import quote

from refspec.atlas.v3_registry_codes import load_registry_code_releases
from refspec.atlas.v3_registry_large import load_fast_topical_release
from refspec.atlas.v3_registry_selection import (
    normalize_only_keys,
    select_declared_group,
    wants_group,
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
from refspec.registry import fast_topical as fast
from refspec.registry import gao_cra_form_codes as gao_cra
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
from refspec.vocabulary import is_english_language_tag

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_SOURCE_ROOT = REPOSITORY_ROOT / "output" / "registry-real-data-sources"

LCSH_BULK_FILENAME = "lcsh-subjects-madsrdf-2026-08-06.jsonld.gz"
LCSH_BULK_SHA256 = "sha256:b33adc284bfb98e39c1331927e9ffee3d73dd0b1b83342906b6ea52c408a5856"
LCSH_BULK_BYTE_LENGTH = 140_187_915
LCSH_BULK_CAPTURED_AT = "2026-08-06"
LCSH_ALIGNMENT_ENDPOINT_COUNT = 1_966
EUROVOC_LCSH_MAPPING_COUNT = sum(EXPECTED_PREDICATE_COUNTS.values())
ATLAS_MAPPING_ADOPTION_REVIEWER_IRI = "urn:ref:actor:atlas-3-eurovoc-lcsh-operator-adoption"
ATLAS_MAPPING_ADOPTION_DECIDED_AT = "2026-08-06T00:00:00+00:00"
EUROVOC_ATLAS_RELEASE_IRI = "urn:ref:atlas-release:3:eurovoc:4.24"
EUROVOC_DOMAINS_ATLAS_RELEASE_IRI = "urn:ref:atlas-release:3:eurovoc-domains:4.24"
# One of the 1,703 EuroVoc subjects the publisher aligned to LCSH is a domain
# rather than a thesaurus concept: 100162 "76 INTERNATIONAL ORGANISATIONS" is
# skos:inScheme <http://eurovoc.europa.eu/domains>. Atlas loads domains as their
# own release, so that subject's endpoint pin has to name the domains release or
# it asserts against a release the graph never puts it in. Both inputs are
# digest-pinned, so this set is fixed; test_eurovoc_lcsh_alignment verifies it
# against the source and fails if the publisher ever aligns another domain.
EUROVOC_DOMAIN_SUBJECT_IRIS = frozenset({"http://eurovoc.europa.eu/100162"})
LCSH_ALIGNMENT_ENDPOINT_ATLAS_RELEASE_IRI = (
    "urn:ref:atlas-release:3:lcsh-subjects:eurovoc-alignment-endpoints:2026-08-06"
)
EUROVOC_LCSH_MAPPING_POLICY_PAYLOAD = MappingProxyType(
    {
        "admission": (
            "explicit mapping triple in the exact publisher alignment artifact, "
            "adopted by Atlas for the pinned endpoint releases"
        ),
        "artifactStatus": "developmentBaseline",
        "evidence": (
            "one exact mapping SourceRecord per assertion; no inverse, transitive, or similarity-generated mappings"
        ),
        "version": "atlas-3.0-eurovoc-lcsh-operator-adoption-v1",
    }
)
REGISTRY_ALIGNMENT_ENDPOINT_RELEASE_KEYS = frozenset({"lcsh-eurovoc-alignment-endpoints-2026-08-06"})
REGISTRY_MAPPING_RELEASE_KEYS = frozenset(
    {
        "eurovoc-lcsh-alignment-20240711",
        "fast-lcsh-adopted-2026-08-15",
        "unified-agenda-gao-cra-priority-2026-08-15",
    }
)

ATLAS_EQUIVALENT_VALUE = "https://refspec.org/ns/atlas/v3#equivalentValue"
UA_GAO_PRIORITY_MAPPING_DECIDED_AT = "2026-08-15T00:00:00+00:00"
UA_GAO_PRIORITY_MAPPING_REVIEWER_IRI = "urn:ref:actor:atlas-3-ua-gao-priority-institutional-adoption"
UA_GAO_INSTITUTIONAL_BRIDGE_FILENAME = "gao-09-205-2009-04-20-2026-08-15.pdf"
UA_GAO_INSTITUTIONAL_BRIDGE_URL = "https://www.gao.gov/assets/gao-09-205.pdf"
UA_GAO_INSTITUTIONAL_BRIDGE_SHA256 = "sha256:7cb03a0114456ccfaf4d4071f92ea7a6b1a3d286ec2da4de58a1ba9d0ed63277"
UA_GAO_INSTITUTIONAL_BRIDGE_BYTE_LENGTH = 1_869_486
UA_GAO_INSTITUTIONAL_BRIDGE_REPORT = "GAO-09-205"
UA_GAO_PRIORITY_MAPPING_POLICY_PAYLOAD = MappingProxyType(
    {
        "admission": (
            "adopt atlas:equivalentValue only for the five-category priority "
            "taxonomy that GAO-09-205 ties to GAO's CRA-form-backed Federal "
            "Rules Database and the Unified Agenda"
        ),
        "candidateAccounting": ("record every reviewed pair and the unmatched Unified Agenda value"),
        "evidence": (
            "three exact source records per assertion: the pinned reginfo.gov "
            "XSD documentation block, GAO Form 41217 item 8, and GAO-09-205's "
            "institutional link between the CRA-form data and Unified Agenda"
        ),
        "lexicalEvidence": (
            "equal labels and the Info./Admin./Other abbreviation corroborate "
            "the institutional link; they do not establish a mapping"
        ),
        "version": "atlas-3-ua-gao-priority-institutional-adoption-v2",
    }
)

_UA_GAO_PRIORITY_PAIRS = (
    ("Economically Significant", "Economically Significant", "equalLabels"),
    ("Other Significant", "Significant", "institutionalLabelVariant"),
    (
        "Substantive, Nonsignificant",
        "Substantive, Nonsignificant",
        "equalLabels",
    ),
    ("Routine and Frequent", "Routine and Frequent", "equalLabels"),
    (
        "Info./Admin./Other",
        "Informational/Administrative/Other",
        "abbreviationOnly",
    ),
)

FAST_LCSH_MAPPING_DECIDED_AT = "2026-08-15T00:00:00+00:00"
FAST_LCSH_ADOPTION_REVIEWER_IRI = "urn:ref:actor:atlas-3-fast-lcsh-schema-same-as-adoption"
FAST_LCSH_PUBLISHER_ASSERTION_REVIEWER_IRI = "urn:ref:atlas-source-descriptor:fast-topical"
FAST_LCSH_MAPPING_POLICY_PAYLOAD = MappingProxyType(
    {
        "admission": (
            "emit only current OCLC FAST LCSH links whose target belongs to "
            "the pinned lcsh-eurovoc-alignment-endpoints-2026-08-06 release"
        ),
        "adoption": ("RefSpec adopts OCLC schema:sameAs as skos:exactMatch for the pinned endpoint subset"),
        "evidence": (
            "one exact OCLC N-Triples statement or MARC authority record field "
            "per assertion, pinned to its source artifact"
        ),
        "publisherVerbatim": (
            "preserve OCLC skos:relatedMatch without promotion except when LC's "
            "independent mapping release places the same pair in a hierarchy; MARC "
            "$w nnd remains recorded in the refused claim's source evidence"
        ),
        "reconciliation": (
            "retain LC broadMatch and narrowMatch claims; refuse the frozen direct "
            "OCLC relatedMatch intersections required by SKOS S27"
        ),
        "version": "atlas-3-fast-lcsh-schema-same-as-adoption-v2",
    }
)

FAST_LCSH_VERIFIED_RECORD_COUNT = 427_423
FAST_LCSH_EXACT_LINK_COUNT = 252_535
FAST_LCSH_RELATED_LINK_COUNT = 349_932
FAST_LCSH_EXACT_EMITTED_COUNT = 1_683
FAST_LCSH_RELATED_EMITTED_COUNT = 62_781
FAST_LCSH_EXACT_UNEMITTED_COUNT = 250_852
FAST_LCSH_RELATED_UNEMITTED_COUNT = 287_151
FAST_LCSH_REACHED_ENDPOINT_COUNT = 1_817
FAST_LCSH_EXACT_SUBJECT_COUNT = 1_683
FAST_LCSH_RELATED_SUBJECT_COUNT = 57_013
FAST_LCSH_BASELINE_INFERRED_MAPPING_COUNT = 5_939
FAST_LCSH_INFERRED_MAPPING_COUNT = 13_001
FAST_LCSH_S27_REFUSAL_COUNT = 24_190
FAST_LCSH_S27_REFUSAL_DIGEST = "sha256:fc9afdc9c1da43839d133ff0efe409dd0c6c0624152bacdfb65e9bd9320653bd"

# The two publishers disagree about these 39 relations.  Each non-exact claim
# falls inside an exactMatch component assembled from their combined releases,
# so emitting it would violate SKOS S46.  Keep the exact publisher assertions
# and freeze the refused non-exact claims here.  The two release adapters fail
# if a pinned source no longer contains its frozen claims.
GEMET_EUROVOC_S46_REFUSALS = MappingProxyType(
    {
        "gemet": frozenset(
            {
                (
                    "http://www.eionet.europa.eu/gemet/concept/6827",
                    "http://www.w3.org/2004/02/skos/core#broadMatch",
                    "http://eurovoc.europa.eu/1756",
                ),
                (
                    "http://www.eionet.europa.eu/gemet/concept/8179",
                    "http://www.w3.org/2004/02/skos/core#broadMatch",
                    "http://eurovoc.europa.eu/4803",
                ),
            }
        ),
        "eurovoc": frozenset(
            {
                (
                    "http://eurovoc.europa.eu/1031",
                    "http://www.w3.org/2004/02/skos/core#closeMatch",
                    "http://www.eionet.europa.eu/gemet/concept/3312",
                ),
                (
                    "http://eurovoc.europa.eu/1282",
                    "http://www.w3.org/2004/02/skos/core#closeMatch",
                    "http://www.eionet.europa.eu/gemet/concept/6381",
                ),
                (
                    "http://eurovoc.europa.eu/1339",
                    "http://www.w3.org/2004/02/skos/core#closeMatch",
                    "http://www.eionet.europa.eu/gemet/concept/7221",
                ),
                (
                    "http://eurovoc.europa.eu/1426",
                    "http://www.w3.org/2004/02/skos/core#closeMatch",
                    "http://www.eionet.europa.eu/gemet/concept/4302",
                ),
                (
                    "http://eurovoc.europa.eu/1515",
                    "http://www.w3.org/2004/02/skos/core#closeMatch",
                    "http://www.eionet.europa.eu/gemet/concept/55",
                ),
                (
                    "http://eurovoc.europa.eu/152",
                    "http://www.w3.org/2004/02/skos/core#closeMatch",
                    "http://www.eionet.europa.eu/gemet/concept/3123",
                ),
                (
                    "http://eurovoc.europa.eu/1528",
                    "http://www.w3.org/2004/02/skos/core#closeMatch",
                    "http://www.eionet.europa.eu/gemet/concept/9407",
                ),
                (
                    "http://eurovoc.europa.eu/1752",
                    "http://www.w3.org/2004/02/skos/core#closeMatch",
                    "http://www.eionet.europa.eu/gemet/concept/1975",
                ),
                (
                    "http://eurovoc.europa.eu/1754",
                    "http://www.w3.org/2004/02/skos/core#closeMatch",
                    "http://www.eionet.europa.eu/gemet/concept/4046",
                ),
                (
                    "http://eurovoc.europa.eu/2025",
                    "http://www.w3.org/2004/02/skos/core#closeMatch",
                    "http://www.eionet.europa.eu/gemet/concept/5448",
                ),
                (
                    "http://eurovoc.europa.eu/2228",
                    "http://www.w3.org/2004/02/skos/core#closeMatch",
                    "http://www.eionet.europa.eu/gemet/concept/6828",
                ),
                (
                    "http://eurovoc.europa.eu/2306",
                    "http://www.w3.org/2004/02/skos/core#closeMatch",
                    "http://www.eionet.europa.eu/gemet/concept/5875",
                ),
                (
                    "http://eurovoc.europa.eu/2329",
                    "http://www.w3.org/2004/02/skos/core#closeMatch",
                    "http://www.eionet.europa.eu/gemet/concept/11506",
                ),
                (
                    "http://eurovoc.europa.eu/2357",
                    "http://www.w3.org/2004/02/skos/core#closeMatch",
                    "http://www.eionet.europa.eu/gemet/concept/3530",
                ),
                (
                    "http://eurovoc.europa.eu/2393",
                    "http://www.w3.org/2004/02/skos/core#closeMatch",
                    "http://www.eionet.europa.eu/gemet/concept/2160",
                ),
                (
                    "http://eurovoc.europa.eu/2402",
                    "http://www.w3.org/2004/02/skos/core#closeMatch",
                    "http://www.eionet.europa.eu/gemet/concept/11016",
                ),
                (
                    "http://eurovoc.europa.eu/2478",
                    "http://www.w3.org/2004/02/skos/core#closeMatch",
                    "http://www.eionet.europa.eu/gemet/concept/7480",
                ),
                (
                    "http://eurovoc.europa.eu/2594",
                    "http://www.w3.org/2004/02/skos/core#closeMatch",
                    "http://www.eionet.europa.eu/gemet/concept/9406",
                ),
                (
                    "http://eurovoc.europa.eu/2723",
                    "http://www.w3.org/2004/02/skos/core#closeMatch",
                    "http://www.eionet.europa.eu/gemet/concept/10044",
                ),
                (
                    "http://eurovoc.europa.eu/3114",
                    "http://www.w3.org/2004/02/skos/core#closeMatch",
                    "http://www.eionet.europa.eu/gemet/concept/3956",
                ),
                (
                    "http://eurovoc.europa.eu/324",
                    "http://www.w3.org/2004/02/skos/core#closeMatch",
                    "http://www.eionet.europa.eu/gemet/concept/8909",
                ),
                (
                    "http://eurovoc.europa.eu/3581",
                    "http://www.w3.org/2004/02/skos/core#closeMatch",
                    "http://www.eionet.europa.eu/gemet/concept/2263",
                ),
                (
                    "http://eurovoc.europa.eu/371",
                    "http://www.w3.org/2004/02/skos/core#closeMatch",
                    "http://www.eionet.europa.eu/gemet/concept/2766",
                ),
                (
                    "http://eurovoc.europa.eu/3739",
                    "http://www.w3.org/2004/02/skos/core#closeMatch",
                    "http://www.eionet.europa.eu/gemet/concept/3507",
                ),
                (
                    "http://eurovoc.europa.eu/3810",
                    "http://www.w3.org/2004/02/skos/core#closeMatch",
                    "http://www.eionet.europa.eu/gemet/concept/1327",
                ),
                (
                    "http://eurovoc.europa.eu/3967",
                    "http://www.w3.org/2004/02/skos/core#closeMatch",
                    "http://www.eionet.europa.eu/gemet/concept/245",
                ),
                (
                    "http://eurovoc.europa.eu/4330",
                    "http://www.w3.org/2004/02/skos/core#closeMatch",
                    "http://www.eionet.europa.eu/gemet/concept/1981",
                ),
                (
                    "http://eurovoc.europa.eu/4366",
                    "http://www.w3.org/2004/02/skos/core#closeMatch",
                    "http://www.eionet.europa.eu/gemet/concept/13312",
                ),
                (
                    "http://eurovoc.europa.eu/438",
                    "http://www.w3.org/2004/02/skos/core#closeMatch",
                    "http://www.eionet.europa.eu/gemet/concept/4785",
                ),
                (
                    "http://eurovoc.europa.eu/4412",
                    "http://www.w3.org/2004/02/skos/core#closeMatch",
                    "http://www.eionet.europa.eu/gemet/concept/11170",
                ),
                (
                    "http://eurovoc.europa.eu/4412",
                    "http://www.w3.org/2004/02/skos/core#closeMatch",
                    "http://www.eionet.europa.eu/gemet/concept/210",
                ),
                (
                    "http://eurovoc.europa.eu/4448",
                    "http://www.w3.org/2004/02/skos/core#closeMatch",
                    "http://www.eionet.europa.eu/gemet/concept/521",
                ),
                (
                    "http://eurovoc.europa.eu/4490",
                    "http://www.w3.org/2004/02/skos/core#closeMatch",
                    "http://www.eionet.europa.eu/gemet/concept/11186",
                ),
                (
                    "http://eurovoc.europa.eu/5216",
                    "http://www.w3.org/2004/02/skos/core#closeMatch",
                    "http://www.eionet.europa.eu/gemet/concept/7970",
                ),
                (
                    "http://eurovoc.europa.eu/5464",
                    "http://www.w3.org/2004/02/skos/core#closeMatch",
                    "http://www.eionet.europa.eu/gemet/concept/2456",
                ),
                (
                    "http://eurovoc.europa.eu/652",
                    "http://www.w3.org/2004/02/skos/core#closeMatch",
                    "http://www.eionet.europa.eu/gemet/concept/4269",
                ),
                (
                    "http://eurovoc.europa.eu/6918",
                    "http://www.w3.org/2004/02/skos/core#closeMatch",
                    "http://www.eionet.europa.eu/gemet/concept/2029",
                ),
            }
        ),
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


def _fast_lcsh_mapping_evidence(
    *,
    mapping_predicate: str,
    publisher_predicate: str,
    subject_iri: str,
    object_iri: str,
    link_payload: Mapping[str, object],
    source_pin: RegistryInputPin,
    numeric_id: str,
) -> RegistryMappingEvidence:
    triple_digest = mapping_triple_digest(
        subject_iri=subject_iri,
        predicate_iri=mapping_predicate,
        object_iri=object_iri,
    )
    native_payload: dict[str, object] = {
        "mappingTripleDigest": triple_digest,
        "objectIri": object_iri,
        "predicateIri": mapping_predicate,
        "publisherClaim": {
            "nativeStatement": link_payload["nativeStatement"],
            "objectIri": object_iri,
            "predicateIri": publisher_predicate,
            "sourceEncoding": link_payload["sourceEncoding"],
            "sourceRecordDigest": link_payload["sourceRecordDigest"],
            "subjectIri": subject_iri,
        },
        "subjectIri": subject_iri,
    }
    if publisher_predicate == fast.FAST_SCHEMA_SAME_AS:
        native_payload["operatorAdoption"] = {
            "adoptedBy": FAST_LCSH_ADOPTION_REVIEWER_IRI,
            "fromPredicateIri": fast.FAST_SCHEMA_SAME_AS,
            "toPredicateIri": "http://www.w3.org/2004/02/skos/core#exactMatch",
        }
        review_warrant = "operatorAdoption"
        reviewer_iri = FAST_LCSH_ADOPTION_REVIEWER_IRI
    else:
        review_warrant = "publisherAssertion"
        reviewer_iri = FAST_LCSH_PUBLISHER_ASSERTION_REVIEWER_IRI
    return RegistryMappingEvidence(
        source_locator=f"{source_pin.source_iri}#fast-{numeric_id}",
        source_digest=source_pin.sha256,
        native_payload=native_payload,
        review_warrant=review_warrant,
        reviewer_iri=reviewer_iri,
        attested_at=FAST_LCSH_MAPPING_DECIDED_AT,
    )


def _mapping_source_input_digest(
    inputs: tuple[RegistryInputPin, ...],
) -> str:
    """Digest the exact input subset that constitutes one mapping release."""

    return canonical_digest(
        [
            {
                "byteLength": item.byte_length,
                "role": item.role,
                "sha256": item.sha256,
                "sourceIri": item.source_iri,
            }
            for item in inputs
        ]
    )


def _resource_by_label(
    release: RegistryRelease,
) -> dict[str, RegistryResource]:
    result: dict[str, RegistryResource] = {}
    for resource in release.resources:
        preferred = [label.value for label in resource.labels if label.role == "preferred"]
        if len(preferred) != 1 or preferred[0] in result:
            raise ValueError(f"{release.key} must have one unique preferred label per resource")
        result[preferred[0]] = resource
    return result


def _ua_gao_institutional_bridge_pin(repo_root: Path) -> RegistryInputPin:
    return RegistryInputPin(
        path=(Path(repo_root) / "tests" / "fixtures" / "gao_cra_form_codes" / UA_GAO_INSTITUTIONAL_BRIDGE_FILENAME),
        logical_path=("tests/fixtures/gao_cra_form_codes/" + UA_GAO_INSTITUTIONAL_BRIDGE_FILENAME),
        sha256=UA_GAO_INSTITUTIONAL_BRIDGE_SHA256,
        byte_length=UA_GAO_INSTITUTIONAL_BRIDGE_BYTE_LENGTH,
        source_iri=UA_GAO_INSTITUTIONAL_BRIDGE_URL,
        role="institutionalTaxonomyBridge",
    )


def _ua_gao_mapping_evidence(
    *,
    mapping_subject: RegistryResource,
    mapping_object: RegistryResource,
    predicate: str,
    subject_release: RegistryRelease,
    object_release: RegistryRelease,
    institutional_bridge: RegistryInputPin,
    label_corroboration: str,
) -> tuple[
    RegistryMappingEvidence,
    RegistryMappingEvidence,
    RegistryMappingEvidence,
]:
    subject_label = mapping_subject.labels[0]
    object_label = mapping_object.labels[0]
    triple = {
        "subjectIri": mapping_subject.iri,
        "predicateIri": predicate,
        "objectIri": mapping_object.iri,
    }
    triple_digest = mapping_triple_digest(
        subject_iri=mapping_subject.iri,
        predicate_iri=predicate,
        object_iri=mapping_object.iri,
    )

    def evidence(
        resource: RegistryResource,
        release: RegistryRelease,
        *,
        endpoint_role: str,
        source_path: str,
    ) -> RegistryMappingEvidence:
        locator = resource.source_locator + "#source-path=" + quote(source_path, safe="")
        return RegistryMappingEvidence(
            source_locator=locator,
            source_digest=resource.source_digest,
            native_payload={
                **triple,
                "decisionBasis": "gaoInstitutionalTaxonomyReuse",
                "endpointRecord": {
                    "atlasReleaseIri": release.atlas_release_iri,
                    "endpointRole": endpoint_role,
                    "nativePayload": resource.native_payload,
                    "preferredLabel": resource.labels[0].value,
                    "resourceIri": resource.iri,
                    "sourcePath": source_path,
                    "sourceRecordDigest": canonical_digest(resource.native_payload),
                },
                "labelCorroboration": label_corroboration,
                "mappingTripleDigest": triple_digest,
            },
            review_warrant="humanReview",
            reviewer_iri=UA_GAO_PRIORITY_MAPPING_REVIEWER_IRI,
            attested_at=UA_GAO_PRIORITY_MAPPING_DECIDED_AT,
        )

    endpoint_evidence = (
        evidence(
            mapping_subject,
            subject_release,
            endpoint_role="subject",
            source_path=subject_label.source_path,
        ),
        evidence(
            mapping_object,
            object_release,
            endpoint_role="object",
            source_path=object_label.source_path,
        ),
    )
    bridge_evidence = RegistryMappingEvidence(
        source_locator=(institutional_bridge.source_iri + "#federal-rules-database-priority-and-footnotes-6-9"),
        source_digest=institutional_bridge.sha256,
        native_payload={
            **triple,
            "decisionBasis": "gaoInstitutionalTaxonomyReuse",
            "institutionalBridge": {
                "reportNumber": UA_GAO_INSTITUTIONAL_BRIDGE_REPORT,
                "sourceDigest": institutional_bridge.sha256,
                "sourceIri": institutional_bridge.source_iri,
                "tie": (
                    "GAO says its standardized CRA form supplies its Federal "
                    "Rules Database, uses Other Significant as a stored priority, "
                    "and defines that category by the Unified Agenda."
                ),
            },
            "labelCorroboration": label_corroboration,
            "mappingTripleDigest": triple_digest,
        },
        review_warrant="operatorAdoption",
        reviewer_iri=UA_GAO_PRIORITY_MAPPING_REVIEWER_IRI,
        attested_at=UA_GAO_PRIORITY_MAPPING_DECIDED_AT,
    )
    return (*endpoint_evidence, bridge_evidence)


def _verify_ua_gao_institutional_bridge(pin: RegistryInputPin) -> None:
    """Verify the GAO report's link from CRA-form data to Unified Agenda terms."""

    pin.verify()
    expected = gao_cra.GAO_CRA_INSTITUTIONAL_BRIDGE_2026_08_15
    if (
        pin.source_iri != expected.source_url
        or pin.sha256 != expected.expected_sha256
        or pin.byte_length != expected.expected_byte_length
    ):
        raise ValueError("GAO institutional evidence pin differs from the registry reader")
    gao_cra.parse_gao_cra_institutional_bridge(pin.path.read_bytes(), pin=expected)


def load_fast_lcsh_mapping_release(
    source_root: Path = DEFAULT_SOURCE_ROOT,
) -> RegistryMappingRelease:
    """Load the joinable FAST-to-LCSH slice without strengthening OCLC links."""

    fast_release = load_fast_topical_release(source_root)
    alignment_pin = replace(
        _alignment_pins(source_root)[0],
        role="publisherEndpointSelection",
    )
    alignment_pin.verify()
    alignment = parse_eurovoc_lcsh_alignment_file(alignment_pin.path)
    target_iris = alignment.lcsh_concept_iris
    source_pins = {pin.path.name: pin for pin in fast_release.inputs}
    mappings: list[RegistryMapping] = []
    emitted_counts: Counter[str] = Counter()
    all_link_counts: Counter[str] = Counter()
    exact_subject_iris: set[str] = set()
    exact_target_iris: set[str] = set()
    related_subject_iris: set[str] = set()
    related_target_iris: set[str] = set()
    source_identifier_count = 0

    for resource in fast_release.resources:
        source_identifier_count += len(resource.identifiers)
        source_filename = resource.native_payload["sourceFilename"]
        if not isinstance(source_filename, str) or source_filename not in source_pins:
            raise ValueError(f"FAST resource {resource.iri} has no pinned source filename")
        numeric_id = resource.native_payload["numericId"]
        if not isinstance(numeric_id, str):
            raise TypeError(f"FAST resource {resource.iri} has no numeric id")
        raw_links = resource.native_payload["lcshLinks"]
        if not isinstance(raw_links, list):
            raise TypeError(f"FAST resource {resource.iri} has malformed LCSH links")
        for raw_link in raw_links:
            if not isinstance(raw_link, Mapping):
                raise TypeError(f"FAST resource {resource.iri} has a malformed LCSH link")
            publisher_predicate = raw_link["publisherPredicateIri"]
            target_iri = raw_link["targetIri"]
            if not isinstance(publisher_predicate, str) or not isinstance(target_iri, str):
                raise TypeError(f"FAST resource {resource.iri} has a malformed LCSH link")
            all_link_counts[publisher_predicate] += 1
            if target_iri not in target_iris:
                continue
            if publisher_predicate == fast.FAST_SCHEMA_SAME_AS:
                mapping_predicate = "http://www.w3.org/2004/02/skos/core#exactMatch"
                exact_subject_iris.add(resource.iri)
                exact_target_iris.add(target_iri)
            elif publisher_predicate == fast.FAST_SKOS_RELATED_MATCH:
                mapping_predicate = fast.FAST_SKOS_RELATED_MATCH
                related_subject_iris.add(resource.iri)
                related_target_iris.add(target_iri)
            else:  # pragma: no cover - reader admits only the two predicates
                raise ValueError(f"FAST resource {resource.iri} has unsupported LCSH predicate {publisher_predicate}")
            emitted_counts[publisher_predicate] += 1
            mappings.append(
                RegistryMapping(
                    subject=resource.iri,
                    predicate=mapping_predicate,
                    object=target_iri,
                    subject_atlas_release_iri=fast_release.atlas_release_iri,
                    object_atlas_release_iri=LCSH_ALIGNMENT_ENDPOINT_ATLAS_RELEASE_IRI,
                    asserted_at=FAST_LCSH_MAPPING_DECIDED_AT,
                    evidence=(
                        _fast_lcsh_mapping_evidence(
                            mapping_predicate=mapping_predicate,
                            publisher_predicate=publisher_predicate,
                            subject_iri=resource.iri,
                            object_iri=target_iri,
                            link_payload=raw_link,
                            source_pin=source_pins[source_filename],
                            numeric_id=numeric_id,
                        ),
                    ),
                )
            )

    observed = {
        "recordsWithLcshLinks": fast_release.metadata["recordsWithLcshLinks"],
        "schemaSameAsLinks": all_link_counts[fast.FAST_SCHEMA_SAME_AS],
        "relatedMatchLinks": all_link_counts[fast.FAST_SKOS_RELATED_MATCH],
        "emittedExactMatches": emitted_counts[fast.FAST_SCHEMA_SAME_AS],
        "emittedRelatedMatches": emitted_counts[fast.FAST_SKOS_RELATED_MATCH],
        "exactMatchSubjectCount": len(exact_subject_iris),
        "relatedMatchSubjectCount": len(related_subject_iris),
        "subjectPredicateOverlapCount": len(exact_subject_iris & related_subject_iris),
        "reachedEndpointCount": len(exact_target_iris | related_target_iris),
        "sourceIdentifierCount": source_identifier_count,
    }
    expected = {
        "recordsWithLcshLinks": FAST_LCSH_VERIFIED_RECORD_COUNT,
        "schemaSameAsLinks": FAST_LCSH_EXACT_LINK_COUNT,
        "relatedMatchLinks": FAST_LCSH_RELATED_LINK_COUNT,
        "emittedExactMatches": FAST_LCSH_EXACT_EMITTED_COUNT,
        "emittedRelatedMatches": FAST_LCSH_RELATED_EMITTED_COUNT,
        "exactMatchSubjectCount": FAST_LCSH_EXACT_SUBJECT_COUNT,
        "relatedMatchSubjectCount": FAST_LCSH_RELATED_SUBJECT_COUNT,
        "subjectPredicateOverlapCount": 0,
        "reachedEndpointCount": FAST_LCSH_REACHED_ENDPOINT_COUNT,
        "sourceIdentifierCount": 0,
    }
    if observed != expected:
        raise ValueError(f"FAST--LCSH measured mapping shape drifted: expected={expected!r}, observed={observed!r}")

    # Every evidence row comes from one OCLC FAST base/change artifact. The
    # LCSH alignment is an endpoint-selection dependency represented by the
    # exact target release, not mapping evidence.
    mapping_inputs = tuple(fast_release.inputs)
    mapping_source_digest = _mapping_source_input_digest(mapping_inputs)
    return RegistryMappingRelease(
        key="fast-lcsh-adopted-2026-08-15",
        resource_id="fast-lcsh-adopted-mapping",
        source_module="refspec.registry.fast_topical",
        ring="subject",
        scope="captureSubset",
        issued="2026-08-15",
        source_release_iri=(
            "urn:ref:registry-mapping-release:fast-lcsh-adopted:" + mapping_source_digest.removeprefix("sha256:")
        ),
        source_release_digest=mapping_source_digest,
        source_release_input_roles=(
            "publisherBase",
            "publisherChange",
        ),
        inputs=mapping_inputs,
        mappings=tuple(mappings),
        editorial_policy=FAST_LCSH_MAPPING_POLICY_PAYLOAD,
        metadata={
            "activeFastRecordCount": len(fast_release.resources),
            "assertionComposition": {
                "adoptedExactMatch": {
                    "assertionCount": FAST_LCSH_EXACT_EMITTED_COUNT,
                    "endpointSelection": ("target is a member of the pinned LCSH alignment-endpoint release"),
                    "evidenceWarrant": "operatorAdoption",
                    "predicateIri": ("http://www.w3.org/2004/02/skos/core#exactMatch"),
                    "publisherStatement": ("OCLC schema:sameAs carried verbatim in each evidence record"),
                },
                "publisherVerbatimRelatedMatch": {
                    "assertionCount": FAST_LCSH_RELATED_EMITTED_COUNT,
                    "evidenceWarrant": "publisherAssertion",
                    "marcQualifier": "$w nnd",
                    "predicateIri": fast.FAST_SKOS_RELATED_MATCH,
                    "promotion": "none",
                },
                "unemittedPublisherLinks": {
                    "schemaSameAsCount": FAST_LCSH_EXACT_UNEMITTED_COUNT,
                    "skosRelatedMatchCount": FAST_LCSH_RELATED_UNEMITTED_COUNT,
                },
            },
            "emittedExactMatchCount": FAST_LCSH_EXACT_EMITTED_COUNT,
            "emittedRelatedMatchCount": FAST_LCSH_RELATED_EMITTED_COUNT,
            "endpointReleaseCount": LCSH_ALIGNMENT_ENDPOINT_COUNT,
            "endpointSelectionDigest": alignment_pin.sha256,
            "exactMatchTargetCount": len(exact_target_iris),
            "inferenceImpact": {
                "baselineInferredMappingCount": (FAST_LCSH_BASELINE_INFERRED_MAPPING_COUNT),
                "inferredMappingCount": FAST_LCSH_INFERRED_MAPPING_COUNT,
                "inferredMappingDelta": (FAST_LCSH_INFERRED_MAPPING_COUNT - FAST_LCSH_BASELINE_INFERRED_MAPPING_COUNT),
                "measurement": ("computed before distribution build with the Atlas 3.1 exact match component index"),
            },
            "publisherSchemaSameAsCount": FAST_LCSH_EXACT_LINK_COUNT,
            "publisherSkosRelatedMatchCount": FAST_LCSH_RELATED_LINK_COUNT,
            "reachedEndpointCount": FAST_LCSH_REACHED_ENDPOINT_COUNT,
            "recordsWithLcshLinks": FAST_LCSH_VERIFIED_RECORD_COUNT,
            "relatedMatchTargetCount": len(related_target_iris),
            "s46Safety": {
                "exactMatchSubjectCount": FAST_LCSH_EXACT_SUBJECT_COUNT,
                "relatedMatchSubjectCount": FAST_LCSH_RELATED_SUBJECT_COUNT,
                "subjectPredicateOverlapCount": 0,
                "status": "safeForCurrentPinnedEndpointFilter",
                "scopeDependency": (
                    "The exactMatch and relatedMatch FAST subject sets are "
                    "disjoint today because of the pinned endpoint filter, not "
                    "by design; widening the endpoint set reopens the S46 check."
                ),
            },
            "sourceFastAtlasReleaseIri": fast_release.atlas_release_iri,
            "sourceIdentifierCount": source_identifier_count,
            "sourceFastReleaseIri": fast_release.source_release_iri,
            "unemittedSchemaSameAsCount": FAST_LCSH_EXACT_UNEMITTED_COUNT,
            "unemittedSkosRelatedMatchCount": FAST_LCSH_RELATED_UNEMITTED_COUNT,
            "unemittedReason": (
                "the LCSH targets are not members of the pinned Atlas endpoint "
                "release; a fuller LCSH release is required"
            ),
        },
    )


def load_unified_agenda_gao_cra_priority_mapping_release(
    repo_root: Path = REPOSITORY_ROOT,
) -> RegistryMappingRelease:
    """Load the reviewed Unified Agenda to GAO CRA priority crosswalk."""

    releases = {
        release.key: release
        for release in load_registry_code_releases(
            Path(repo_root),
            only_keys={
                "gao-cra-priority-of-regulation",
                "unified-agenda-priority-category",
            },
        )
    }
    unified_agenda = releases["unified-agenda-priority-category"]
    gao_cra = releases["gao-cra-priority-of-regulation"]
    ua_by_label = _resource_by_label(unified_agenda)
    gao_by_label = _resource_by_label(gao_cra)
    institutional_bridge = _ua_gao_institutional_bridge_pin(Path(repo_root))
    _verify_ua_gao_institutional_bridge(institutional_bridge)

    mappings = tuple(
        RegistryMapping(
            subject=ua_by_label[subject_label].iri,
            predicate=ATLAS_EQUIVALENT_VALUE,
            object=gao_by_label[object_label].iri,
            subject_atlas_release_iri=unified_agenda.atlas_release_iri,
            object_atlas_release_iri=gao_cra.atlas_release_iri,
            asserted_at=UA_GAO_PRIORITY_MAPPING_DECIDED_AT,
            evidence=_ua_gao_mapping_evidence(
                mapping_subject=ua_by_label[subject_label],
                mapping_object=gao_by_label[object_label],
                predicate=ATLAS_EQUIVALENT_VALUE,
                subject_release=unified_agenda,
                object_release=gao_cra,
                institutional_bridge=institutional_bridge,
                label_corroboration=label_corroboration,
            ),
            effective_from="2026-08-15",
        )
        for subject_label, object_label, label_corroboration in _UA_GAO_PRIORITY_PAIRS
    )

    subject_input = replace(
        unified_agenda.inputs[0],
        role="publisherSubjectValues",
    )
    object_input = replace(
        gao_cra.inputs[0],
        role="publisherObjectValues",
    )
    inputs = (subject_input, object_input, institutional_bridge)
    source_release_digest = _mapping_source_input_digest(inputs)
    decisions = [
        {
            "decision": "adopted",
            "objectLabel": object_label,
            "predicateIri": ATLAS_EQUIVALENT_VALUE,
            "reason": (
                "GAO-09-205 ties this CRA-form-backed priority taxonomy to the "
                "Unified Agenda; the equal label corroborates that institutional "
                "link but does not establish it"
                if label_corroboration == "equalLabels"
                else (
                    "GAO-09-205 uses Other Significant for a priority stored in "
                    "its CRA-form-backed database and defines that category by "
                    "the Unified Agenda; the differing labels are an institutional "
                    "variant, not the basis for equivalence"
                    if label_corroboration == "institutionalLabelVariant"
                    else (
                        "GAO-09-205 ties this CRA-form-backed priority taxonomy to "
                        "the Unified Agenda; the expanded words corroborate the "
                        "institutional link but do not establish it"
                    )
                )
            ),
            "subjectLabel": subject_label,
        }
        for subject_label, object_label, label_corroboration in _UA_GAO_PRIORITY_PAIRS
    ]
    decisions.append(
        {
            # An unmatched candidate has no object: the wire grammar carries no
            # nulls, so the absence is stated by the key's omission.
            "decision": "unmatched",
            "reason": (
                "GAO-09-205 establishes a five-category Unified Agenda priority "
                "taxonomy for the CRA-form-backed database; Not Major is outside "
                "that taxonomy because GAO Form 41217 records Major/Non-Major "
                "separately from item 8 priority"
            ),
            "subjectLabel": "Not Major",
        }
    )
    return RegistryMappingRelease(
        key="unified-agenda-gao-cra-priority-2026-08-15",
        resource_id="unified-agenda-gao-cra-priority-mapping",
        source_module="refspec.registry.unified_agenda_codes",
        ring="value",
        scope="captureSubset",
        issued="2026-08-15",
        source_release_iri=(
            "urn:ref:registry-mapping-release:ua-gao-cra-priority:" + source_release_digest.removeprefix("sha256:")
        ),
        source_release_digest=source_release_digest,
        source_release_input_roles=(
            "publisherSubjectValues",
            "publisherObjectValues",
            "institutionalTaxonomyBridge",
        ),
        inputs=inputs,
        mappings=mappings,
        editorial_policy=UA_GAO_PRIORITY_MAPPING_POLICY_PAYLOAD,
        metadata={
            "adoptedAssertionCount": len(mappings),
            "candidateDecisions": decisions,
            "institutionalEvidence": {
                "reportNumber": UA_GAO_INSTITUTIONAL_BRIDGE_REPORT,
                "sourceDigest": institutional_bridge.sha256,
                "sourceIri": institutional_bridge.source_iri,
                "vocabularyTie": (
                    "GAO says the standardized CRA submission form supplies its "
                    "Federal Rules Database, reports priority as a database field, "
                    "uses Other Significant as a selected database priority, and "
                    "defines that priority by the Unified Agenda. Atlas applies "
                    "that institutional five-category taxonomy to Form 41217 item 8."
                ),
            },
            "lexicalEvidenceRole": (
                "Equal labels and the Info./Admin./Other abbreviation are "
                "corroboration only; lexical equality does not establish any "
                "atlas:equivalentValue assertion."
            ),
            "effectivePeriodBasis": (
                "The open period begins on RefSpec's 2026-08-15 adoption date; "
                "it does not restate either form revision's publication period."
            ),
            "reviewer": UA_GAO_PRIORITY_MAPPING_REVIEWER_IRI,
            "sourceEndpointIdentifierCount": sum(
                len(resource.identifiers) for release in (unified_agenda, gao_cra) for resource in release.resources
            ),
        },
    )


def load_eurovoc_lcsh_mapping_release(
    source_root: Path = DEFAULT_SOURCE_ROOT,
) -> RegistryMappingRelease:
    """Load the official alignment as separately pinned publisher mappings."""

    pins = _alignment_pins(source_root)
    alignment_pin, alignment_metadata_pin, eurovoc_4_20_pin, current_metadata_pin = pins
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
            f"EuroVoc--LCSH expected {EUROVOC_LCSH_MAPPING_COUNT} mappings; parsed {len(alignment.mappings)}"
        )
    mappings = tuple(
        RegistryMapping(
            subject=row.subject_iri,
            predicate=row.predicate_iri,
            object=row.object_iri,
            subject_atlas_release_iri=(
                EUROVOC_DOMAINS_ATLAS_RELEASE_IRI
                if row.subject_iri in EUROVOC_DOMAIN_SUBJECT_IRIS
                else EUROVOC_ATLAS_RELEASE_IRI
            ),
            object_atlas_release_iri=LCSH_ALIGNMENT_ENDPOINT_ATLAS_RELEASE_IRI,
            asserted_at=ATLAS_MAPPING_ADOPTION_DECIDED_AT,
            evidence=(
                RegistryMappingEvidence(
                    source_locator=alignment_pin.source_iri,
                    source_digest=alignment_pin.sha256,
                    native_payload={
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
                    review_warrant="operatorAdoption",
                    reviewer_iri=ATLAS_MAPPING_ADOPTION_REVIEWER_IRI,
                    attested_at=ATLAS_MAPPING_ADOPTION_DECIDED_AT,
                ),
            ),
        )
        for row in alignment.mappings
    )
    return RegistryMappingRelease(
        key="eurovoc-lcsh-alignment-20240711",
        resource_id="eurovoc-lcsh-alignment",
        source_module="refspec.registry.eurovoc_lcsh_alignment",
        ring="subject",
        scope="publisherRelease",
        issued=EUROVOC_LCSH_ALIGNMENT_ISSUED,
        source_release_iri=EUROVOC_LCSH_ALIGNMENT_RELEASE_IRI,
        source_release_digest=alignment_pin.sha256,
        inputs=pins,
        mappings=mappings,
        editorial_policy=EUROVOC_LCSH_MAPPING_POLICY_PAYLOAD,
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
    if not is_english_language_tag(record.preferred_label.language):
        raise ValueError(f"aligned LCSH authority lacks an English preferred label: {record.concept_iri}")
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
                source_path=(f"line-{record.line_number}:madsrdf:hasVariant[{index}]"),
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
        source_release_iri=("urn:ref:source-release:lcsh-subjects:eurovoc-alignment-endpoints:2026-08-06"),
        source_release_digest=_input_set_digest(inputs),
        atlas_release_iri=("urn:ref:atlas-release:3:lcsh-subjects:eurovoc-alignment-endpoints:2026-08-06"),
        scheme_iri="urn:ref:atlas-resource-scheme:lcsh-subjects",
        inputs=inputs,
        resources=resources,
        relations=relations,
        dropped_label_count=sum(
            not is_english_language_tag(label.language) for record in capture.records for label in record.variant_labels
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
    """Load selected separately pinned evidence-backed mapping releases."""

    requested = normalize_only_keys(
        only_keys,
        allowed_keys=REGISTRY_MAPPING_RELEASE_KEYS,
        loader_name="load_all_registry_mapping_releases",
    )
    if not wants_group(requested, REGISTRY_MAPPING_RELEASE_KEYS):
        return ()
    loaders = (
        (
            "eurovoc-lcsh-alignment-20240711",
            lambda: load_eurovoc_lcsh_mapping_release(source_root),
        ),
        (
            "fast-lcsh-adopted-2026-08-15",
            lambda: load_fast_lcsh_mapping_release(source_root),
        ),
        (
            "unified-agenda-gao-cra-priority-2026-08-15",
            load_unified_agenda_gao_cra_priority_mapping_release,
        ),
    )
    loaded = tuple(loader() for key, loader in loaders if requested is None or key in requested)
    expected = REGISTRY_MAPPING_RELEASE_KEYS if requested is None else requested
    observed = [release.key for release in loaded]
    if len(observed) != len(set(observed)) or set(observed) != set(expected):
        raise ValueError(
            "load_all_registry_mapping_releases release topology differs: "
            f"expected={sorted(expected)!r}, observed={sorted(observed)!r}"
        )
    return loaded


__all__ = [
    "ATLAS_EQUIVALENT_VALUE",
    "ATLAS_MAPPING_ADOPTION_DECIDED_AT",
    "ATLAS_MAPPING_ADOPTION_REVIEWER_IRI",
    "DEFAULT_SOURCE_ROOT",
    "EUROVOC_ATLAS_RELEASE_IRI",
    "EUROVOC_DOMAINS_ATLAS_RELEASE_IRI",
    "EUROVOC_DOMAIN_SUBJECT_IRIS",
    "EUROVOC_LCSH_MAPPING_COUNT",
    "EUROVOC_LCSH_MAPPING_POLICY_PAYLOAD",
    "FAST_LCSH_ADOPTION_REVIEWER_IRI",
    "FAST_LCSH_BASELINE_INFERRED_MAPPING_COUNT",
    "FAST_LCSH_EXACT_EMITTED_COUNT",
    "FAST_LCSH_EXACT_LINK_COUNT",
    "FAST_LCSH_EXACT_SUBJECT_COUNT",
    "FAST_LCSH_EXACT_UNEMITTED_COUNT",
    "FAST_LCSH_INFERRED_MAPPING_COUNT",
    "FAST_LCSH_MAPPING_DECIDED_AT",
    "FAST_LCSH_MAPPING_POLICY_PAYLOAD",
    "FAST_LCSH_PUBLISHER_ASSERTION_REVIEWER_IRI",
    "FAST_LCSH_REACHED_ENDPOINT_COUNT",
    "FAST_LCSH_RELATED_EMITTED_COUNT",
    "FAST_LCSH_RELATED_LINK_COUNT",
    "FAST_LCSH_RELATED_SUBJECT_COUNT",
    "FAST_LCSH_RELATED_UNEMITTED_COUNT",
    "FAST_LCSH_S27_REFUSAL_COUNT",
    "FAST_LCSH_S27_REFUSAL_DIGEST",
    "FAST_LCSH_VERIFIED_RECORD_COUNT",
    "GEMET_EUROVOC_S46_REFUSALS",
    "LCSH_ALIGNMENT_ENDPOINT_ATLAS_RELEASE_IRI",
    "LCSH_ALIGNMENT_ENDPOINT_COUNT",
    "LCSH_BULK_BYTE_LENGTH",
    "LCSH_BULK_CAPTURED_AT",
    "LCSH_BULK_FILENAME",
    "LCSH_BULK_SHA256",
    "REGISTRY_ALIGNMENT_ENDPOINT_RELEASE_KEYS",
    "REGISTRY_MAPPING_RELEASE_KEYS",
    "UA_GAO_INSTITUTIONAL_BRIDGE_BYTE_LENGTH",
    "UA_GAO_INSTITUTIONAL_BRIDGE_FILENAME",
    "UA_GAO_INSTITUTIONAL_BRIDGE_REPORT",
    "UA_GAO_INSTITUTIONAL_BRIDGE_SHA256",
    "UA_GAO_INSTITUTIONAL_BRIDGE_URL",
    "UA_GAO_PRIORITY_MAPPING_DECIDED_AT",
    "UA_GAO_PRIORITY_MAPPING_POLICY_PAYLOAD",
    "UA_GAO_PRIORITY_MAPPING_REVIEWER_IRI",
    "load_all_registry_alignment_endpoint_releases",
    "load_all_registry_mapping_releases",
    "load_eurovoc_lcsh_mapping_release",
    "load_fast_lcsh_mapping_release",
    "load_lcsh_alignment_endpoint_release",
    "load_unified_agenda_gao_cra_priority_mapping_release",
]
