"""Publisher mapping releases and the exact endpoint subsets they require."""

from __future__ import annotations

from collections import Counter
from collections.abc import Collection, Mapping, Sequence
from dataclasses import replace
from pathlib import Path
from types import MappingProxyType
from urllib.parse import quote

from refspec.atlas.v3_registry_alignments_lcsh import (
    LCSH_CONSOLIDATED_ATLAS_RELEASE_IRI,
    LCSH_CONSOLIDATED_RELEASE_KEY,
    load_lcsh_consolidated_release,
)
from refspec.atlas.v3_registry_codes import load_registry_code_releases
from refspec.atlas.v3_registry_large import load_fast_topical_release
from refspec.atlas.v3_registry_selection import (
    normalize_only_keys,
    select_declared_group,
    wants_group,
)
from refspec.atlas.v3_source_data import (
    RegistryInputPin,
    RegistryMapping,
    RegistryMappingEvidence,
    RegistryMappingRelease,
    RegistryRelease,
    RegistryResource,
    canonical_digest,
    mapping_triple_digest,
)
from refspec.registry import fast_topical as fast
from refspec.registry import gao_cra_form_codes as gao_cra
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
LCSH_BULK_SHA256 = "sha256:b33adc284bfb98e39c1331927e9ffee3d73dd0b1b83342906b6ea52c408a5856"
LCSH_BULK_BYTE_LENGTH = 140_187_915
LCSH_BULK_CAPTURED_AT = "2026-08-06"
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
REGISTRY_ALIGNMENT_ENDPOINT_RELEASE_KEYS = frozenset({LCSH_CONSOLIDATED_RELEASE_KEY})
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
            "the consolidated LCSH release (every current LCSH heading plus "
            "the deprecated headings held mappings reference)"
        ),
        "adoption": ("RefSpec adopts OCLC schema:sameAs as skos:exactMatch for every held LCSH target"),
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
# REF-040 widened the target endpoint from the retired 1,966-concept
# EuroVoc-alignment subset to every held LCSH concept (the consolidated
# release). These nine counts are measured against that widened target set;
# the prior narrow-scope values are design lineage, not current behavior.
FAST_LCSH_EXACT_EMITTED_COUNT = 252_527
FAST_LCSH_RELATED_EMITTED_COUNT = 349_932
FAST_LCSH_EXACT_UNEMITTED_COUNT = 8
FAST_LCSH_RELATED_UNEMITTED_COUNT = 0
FAST_LCSH_REACHED_ENDPOINT_COUNT = 254_453
FAST_LCSH_EXACT_SUBJECT_COUNT = 252_527
FAST_LCSH_RELATED_SUBJECT_COUNT = 174_900
# A FAST subject can now carry both an exactMatch and a relatedMatch into
# LCSH (REF-035 foresaw this: "an artifact of the filter, not a property of
# FAST"). Twelve do. None of the twelve is an actual SKOS S46 conflict: see
# `_fast_lcsh_s46_conflicts`, whose measured conflict count over this
# release's own emitted pairs is zero.
FAST_LCSH_SUBJECT_PREDICATE_OVERLAP_COUNT = 12
# Measured with the Atlas 3.1 exact-match component index over the same two
# releases test_fast_inferred_mapping_delta_is_computed_before_build proves
# this against: eurovoc-lcsh-alignment-20240711's exactMatch edges alone
# (baseline), then joined with this release's now-widened exactMatch edges.
# This is not the full-corpus figure (other mapping releases' exactMatch
# edges are not included); it is the same two-release measurement this
# constant has always recorded.
FAST_LCSH_BASELINE_INFERRED_MAPPING_COUNT = 5_939
FAST_LCSH_INFERRED_MAPPING_COUNT = 765_537
# REF-037 measured this pin (24,190; digest ...653bd) against the retired
# 1,966-concept EuroVoc-alignment target subset. REF-040 widened the target
# to every held LCSH concept, which reopens far more relatedMatch pairs
# against LC's hierarchy claims: the pin below is measured fresh against that
# widened scope by loading both `fast-lcsh-adopted-2026-08-15` and
# `lcsh-external-links-mappings-2026-08-15` and reproducing
# `_reconcile_fast_lcsh_s27_mapping_conflicts`'s own derivation
# (tools/generate_atlas_v3_full.py). It is not hand-computed: the frozen
# count and digest here are read back from that derivation over the real
# pinned sources, and `tests/test_producer_prebuild_validation.py`
# (`test_fast_lcsh_s27_pin_matches_the_real_widened_conflict_set`) re-derives
# and compares them on every run that has the pinned sources cached, so drift
# fails in seconds instead of at hour two of a full build.
#
# A first version of this pin (174,755; digest ...ce7782) was measured
# against only `lcsh-external-links-mappings-2026-08-15`'s own
# broadMatch/narrowMatch hierarchy -- narrower than what the binding's
# corpus-wide SKOS S27 check actually evaluates once the distribution also
# carries the consolidated LCSH release's 301,442 native `skos:broader`
# statements. That gap let a real conflict reach the validator 13 minutes
# into a full build (sh2008003833 / fast/1910413). The pin below is
# reconciled against the corpus-scope hierarchy instead: every native
# skos:broader/skos:narrower relation across the loaded source releases
# (which must include `lcsh-subjects-consolidated-2026-08-06`) plus every
# loaded mapping release's broadMatch/narrowMatch -- the same statements
# `refspec_atlas_v3_validate._check_skos_integrity` sees. Widening the
# hierarchy scope this way moves 11 more relatedMatch pairs from admitted to
# refused (174,755 -> 174,766).
FAST_LCSH_S27_REFUSAL_COUNT = 174_766
FAST_LCSH_S27_REFUSAL_DIGEST = "sha256:2113d4079b4677c0fea40c8c11583f265b5f3cd95d2988bcb941ab5c8897c6ce"

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


def _fast_lcsh_s46_conflicts(
    exact_pairs: Sequence[tuple[str, str]],
    related_pairs: Sequence[tuple[str, str]],
) -> tuple[tuple[str, str], ...]:
    """Find any relatedMatch pair whose two nodes share an exactMatch component.

    Mirrors the corpus-wide SKOS S46 check
    (``bindings/atlas/3.1/tools/validate.py:_build_exact_match_index_from_triples``)
    at release scope: union-find over this release's own exactMatch edges,
    then test every relatedMatch pair for same-component membership. This is
    a self-check on this release's own emitted pairs, not a substitute for
    the corpus-wide preflight, which also sees other releases' exactMatch
    edges.
    """

    parent: dict[str, str] = {}

    def find(node: str) -> str:
        root = node
        while parent.get(root, root) != root:
            root = parent[root]
        while parent.get(node, node) != root:
            parent[node], node = root, parent.get(node, node)
        return root

    def union(a: str, b: str) -> None:
        root_a, root_b = find(a), find(b)
        if root_a != root_b:
            parent[root_a] = root_b

    for subject, obj in exact_pairs:
        parent.setdefault(subject, subject)
        parent.setdefault(obj, obj)
        union(subject, obj)
    return tuple(
        pair
        for pair in related_pairs
        if pair[0] in parent and pair[1] in parent and find(pair[0]) == find(pair[1])
    )


def load_fast_lcsh_mapping_release(
    source_root: Path = DEFAULT_SOURCE_ROOT,
) -> RegistryMappingRelease:
    """Load the FAST-to-LCSH mapping against every held LCSH concept.

    The target endpoint is the consolidated LCSH release
    (``v3_registry_alignments_lcsh.load_lcsh_consolidated_release``), not the
    former 1,966-concept EuroVoc-alignment endpoint subset: every current
    LCSH heading FAST names now resolves, and REF-035's predicate policies
    (schema:sameAs -> exactMatch under operatorAdoption; skos:relatedMatch
    stays publisherAssertion verbatim, never promoted) apply unchanged.
    """

    fast_release = load_fast_topical_release(source_root)
    consolidated_release = load_lcsh_consolidated_release(source_root)
    target_iris = frozenset(resource.iri for resource in consolidated_release.resources)
    source_pins = {pin.path.name: pin for pin in fast_release.inputs}
    mappings: list[RegistryMapping] = []
    emitted_counts: Counter[str] = Counter()
    all_link_counts: Counter[str] = Counter()
    exact_subject_iris: set[str] = set()
    exact_target_iris: set[str] = set()
    related_subject_iris: set[str] = set()
    related_target_iris: set[str] = set()
    exact_pairs: list[tuple[str, str]] = []
    related_pairs: list[tuple[str, str]] = []
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
                exact_pairs.append((resource.iri, target_iri))
            elif publisher_predicate == fast.FAST_SKOS_RELATED_MATCH:
                mapping_predicate = fast.FAST_SKOS_RELATED_MATCH
                related_subject_iris.add(resource.iri)
                related_target_iris.add(target_iri)
                related_pairs.append((resource.iri, target_iri))
            else:  # pragma: no cover - reader admits only the two predicates
                raise ValueError(f"FAST resource {resource.iri} has unsupported LCSH predicate {publisher_predicate}")
            emitted_counts[publisher_predicate] += 1
            mappings.append(
                RegistryMapping(
                    subject=resource.iri,
                    predicate=mapping_predicate,
                    object=target_iri,
                    subject_atlas_release_iri=fast_release.atlas_release_iri,
                    object_atlas_release_iri=LCSH_CONSOLIDATED_ATLAS_RELEASE_IRI,
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

    s46_conflicts = _fast_lcsh_s46_conflicts(exact_pairs, related_pairs)
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
        "s46ConflictCount": len(s46_conflicts),
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
        "subjectPredicateOverlapCount": FAST_LCSH_SUBJECT_PREDICATE_OVERLAP_COUNT,
        "reachedEndpointCount": FAST_LCSH_REACHED_ENDPOINT_COUNT,
        "s46ConflictCount": 0,
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
                    "endpointSelection": ("target is a member of the consolidated LCSH release"),
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
            "endpointReleaseResourceCount": len(target_iris),
            "endpointSelectionDigest": consolidated_release.source_release_digest,
            "exactMatchTargetCount": len(exact_target_iris),
            "inferenceImpact": {
                "baselineInferredMappingCount": (FAST_LCSH_BASELINE_INFERRED_MAPPING_COUNT),
                "inferredMappingCount": FAST_LCSH_INFERRED_MAPPING_COUNT,
                "inferredMappingDelta": (FAST_LCSH_INFERRED_MAPPING_COUNT - FAST_LCSH_BASELINE_INFERRED_MAPPING_COUNT),
                "measurement": (
                    "computed before distribution build with the Atlas 3.1 exact match "
                    "component index over eurovoc-lcsh-alignment-20240711 and this "
                    "release's exactMatch edges; REF-040 widened this release's target "
                    "endpoint from the retired 1,966-concept EuroVoc-alignment subset "
                    "to every held LCSH concept, which is why the current figure moved"
                ),
            },
            "publisherSchemaSameAsCount": FAST_LCSH_EXACT_LINK_COUNT,
            "publisherSkosRelatedMatchCount": FAST_LCSH_RELATED_LINK_COUNT,
            "reachedEndpointCount": FAST_LCSH_REACHED_ENDPOINT_COUNT,
            "recordsWithLcshLinks": FAST_LCSH_VERIFIED_RECORD_COUNT,
            "relatedMatchTargetCount": len(related_target_iris),
            "s46Safety": {
                "conflictCount": len(s46_conflicts),
                "exactMatchSubjectCount": FAST_LCSH_EXACT_SUBJECT_COUNT,
                "relatedMatchSubjectCount": FAST_LCSH_RELATED_SUBJECT_COUNT,
                "status": "measuredZeroConflictsOverThisReleasesOwnExactMatchComponents",
                "subjectPredicateOverlapCount": FAST_LCSH_SUBJECT_PREDICATE_OVERLAP_COUNT,
                "scopeDependency": (
                    "REF-035's warning was correct: widening the endpoint set to every "
                    "held LCSH concept reopened subject overlap between the exactMatch "
                    "and relatedMatch FAST subject sets (now "
                    f"{FAST_LCSH_SUBJECT_PREDICATE_OVERLAP_COUNT}, was 0 under the narrow "
                    "filter). This release's own exactMatch-component union-find over "
                    "its emitted pairs finds zero relatedMatch pairs sharing a component "
                    "with an exactMatch pair; the corpus-wide S46 preflight remains the "
                    "authority once other releases' exactMatch edges are in the graph."
                ),
            },
            "sourceFastAtlasReleaseIri": fast_release.atlas_release_iri,
            "sourceIdentifierCount": source_identifier_count,
            "sourceFastReleaseIri": fast_release.source_release_iri,
            "unemittedSchemaSameAsCount": FAST_LCSH_EXACT_UNEMITTED_COUNT,
            "unemittedSkosRelatedMatchCount": FAST_LCSH_RELATED_UNEMITTED_COUNT,
            "unemittedReason": (
                "the LCSH target is absent from the pinned bulk file entirely -- "
                "neither current nor a referenced deprecated heading"
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
            object_atlas_release_iri=LCSH_CONSOLIDATED_ATLAS_RELEASE_IRI,
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
        (load_lcsh_consolidated_release(source_root),),
        declared_keys=REGISTRY_ALIGNMENT_ENDPOINT_RELEASE_KEYS,
        requested_keys=requested,
        loader_name="load_lcsh_consolidated_release",
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
    "FAST_LCSH_SUBJECT_PREDICATE_OVERLAP_COUNT",
    "FAST_LCSH_VERIFIED_RECORD_COUNT",
    "GEMET_EUROVOC_S46_REFUSALS",
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
    "load_unified_agenda_gao_cra_priority_mapping_release",
]
