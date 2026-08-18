"""Atlas 3 release adapters for LC-authored LCSH external links.

LC owns the LCSH source vocabulary and asserts each row into a vocabulary
owned elsewhere.  The MADS/RDF source predicates are translated only to the
SKOS mapping predicates LC documents as their equivalents, so every emitted
row uses ``operatorAdoption`` and records the source predicate, target
predicate, and adopting actor.  No inverse or transitive assertion is added.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Collection, Sequence
from pathlib import Path
from types import MappingProxyType

from refspec.atlas.v3_registry_alignments_lcsh import (
    LCSH_CONSOLIDATED_ATLAS_RELEASE_IRI,
    load_lcsh_consolidated_release,
)
from refspec.atlas.v3_registry_large import load_fast_topical_release
from refspec.atlas.v3_registry_selection import normalize_only_keys, select_declared_group, wants_group
from refspec.atlas.v3_source_data import (
    RegistryInputPin,
    RegistryLabel,
    RegistryMapping,
    RegistryMappingEvidence,
    RegistryMappingRelease,
    RegistryRelease,
    RegistryResource,
    canonical_digest,
    mapping_triple_digest,
)
from refspec.registry import lc_external_links as external

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_SOURCE_ROOT = REPOSITORY_ROOT / "output" / "registry-real-data-sources"

LCSH_EXTERNAL_LINKS_MAPPING_RELEASE_KEY = "lcsh-external-links-mappings-2026-08-15"

LC_EXTERNAL_TARGET_VOCABULARIES = frozenset(external.TARGET_VOCABULARY_PREFIXES)
LC_EXTERNAL_TARGET_ENDPOINT_RELEASE_KEYS = MappingProxyType(
    {
        vocabulary: f"lc-external-{vocabulary}-endpoints-2026-08-15"
        for vocabulary in sorted(LC_EXTERNAL_TARGET_VOCABULARIES)
    }
)
LC_EXTERNAL_TARGET_ATLAS_RELEASE_IRIS = MappingProxyType(
    {
        vocabulary: f"urn:ref:atlas-release:3:lc-external-{vocabulary}-endpoints:2026-08-15"
        for vocabulary in sorted(LC_EXTERNAL_TARGET_VOCABULARIES)
    }
)
# REF-040 retired the LCSH endpoint release this module used to mint
# (``lcsh-external-links-endpoints-2026-08-15``): its resources moved into
# the consolidated LCSH release, so this key set now only names the
# non-LCSH target endpoint releases (FAST residue, AGROVOC, BNCF, ...).
LC_REGISTRY_ALIGNMENT_ENDPOINT_RELEASE_KEYS = frozenset(LC_EXTERNAL_TARGET_ENDPOINT_RELEASE_KEYS.values())
LC_REGISTRY_MAPPING_RELEASE_KEYS = frozenset({LCSH_EXTERNAL_LINKS_MAPPING_RELEASE_KEY})

LC_MAPPING_ADOPTION_REVIEWER_IRI = "urn:ref:actor:atlas-3-lc-mads-external-predicate-adoption"
LC_MAPPING_DECIDED_AT = "2026-08-15T22:49:53+00:00"
LC_MADS_DOCUMENTATION_URL = "https://www.loc.gov/standards/mads/rdf/"

SKOS_CLOSE_MATCH = "http://www.w3.org/2004/02/skos/core#closeMatch"
SKOS_EXACT_MATCH = "http://www.w3.org/2004/02/skos/core#exactMatch"
SKOS_BROAD_MATCH = "http://www.w3.org/2004/02/skos/core#broadMatch"
SKOS_NARROW_MATCH = "http://www.w3.org/2004/02/skos/core#narrowMatch"

MADS_TO_SKOS_PREDICATE = MappingProxyType(
    {
        external.MADS_BROADER_EXTERNAL_AUTHORITY: SKOS_BROAD_MATCH,
        external.MADS_CLOSE_EXTERNAL_AUTHORITY: SKOS_CLOSE_MATCH,
        external.MADS_EXACT_EXTERNAL_AUTHORITY: SKOS_EXACT_MATCH,
        external.MADS_NARROWER_EXTERNAL_AUTHORITY: SKOS_NARROW_MATCH,
    }
)

LC_FAST_SOURCE_ASSERTION_COUNT = 535_372
LC_FAST_HELD_TARGET_ASSERTION_COUNT = 426_841
LC_FAST_ACTIVE_EMITTED_ASSERTION_COUNT = 426_833
LC_FAST_EMITTED_ASSERTION_COUNT = 534_968
LC_FAST_ABSENT_ENDPOINT_ASSERTION_COUNT = 108_531
LC_FAST_HELD_TARGET_PREDICATE_COUNTS = MappingProxyType(
    {
        external.MADS_BROADER_EXTERNAL_AUTHORITY: 174_757,
        external.MADS_CLOSE_EXTERNAL_AUTHORITY: 252_084,
    }
)
LC_FAST_ACTIVE_EMITTED_PREDICATE_COUNTS = MappingProxyType(
    {
        external.MADS_BROADER_EXTERNAL_AUTHORITY: 174_757,
        external.MADS_CLOSE_EXTERNAL_AUTHORITY: 252_076,
    }
)
LC_FAST_ABSENT_ENDPOINT_PREDICATE_COUNTS = MappingProxyType(
    {
        external.MADS_BROADER_EXTERNAL_AUTHORITY: 6_848,
        external.MADS_CLOSE_EXTERNAL_AUTHORITY: 101_683,
    }
)
LC_EMITTED_PUBLISHER_PREDICATE_COUNTS = MappingProxyType(
    {
        external.MADS_BROADER_EXTERNAL_AUTHORITY: 182_639,
        external.MADS_CLOSE_EXTERNAL_AUTHORITY: 606_593,
        external.MADS_EXACT_EXTERNAL_AUTHORITY: 12_548,
        external.MADS_NARROWER_EXTERNAL_AUTHORITY: 212,
    }
)
LC_FAST_ACTIVE_RESOURCE_COUNT = 441_127
LC_FAST_REACHED_RESOURCE_COUNT = 426_833
LC_FAST_REACHED_RESOURCE_PERCENT = "96.75966331691328"
LC_FAST_HELD_TARGET_LCSH_SUBJECT_COUNT = 252_784
LC_FAST_LCSH_SUBJECT_COUNT = 252_776
LC_FAST_MISSING_LCSH_SUBJECT_IRIS = frozenset(
    {
        "http://id.loc.gov/authorities/subjects/sh85012731",
        "http://id.loc.gov/authorities/subjects/sh85071357",
        "http://id.loc.gov/authorities/subjects/sh85093187",
        "http://id.loc.gov/authorities/subjects/sh85113270",
        "http://id.loc.gov/authorities/subjects/sh85122666",
        "http://id.loc.gov/authorities/subjects/sh93009322",
        "http://id.loc.gov/authorities/subjects/sh98004477",
        "http://id.loc.gov/authorities/subjects/sh99003885",
    }
)
# REF-040: the consolidated LCSH release holds every current heading, so
# only this count (LCSH subjects absent from the pinned bulk file entirely)
# still bounds what this release can emit; the former candidate/existing/new
# endpoint-partition counts described the retired bespoke capture and are
# gone with it.
LC_ALL_MISSING_LCSH_SUBJECT_COUNT = 469
LC_EXTERNAL_TARGET_ASSERTION_COUNT = 267_220
LC_EXTERNAL_EMITTED_ASSERTION_COUNT = 267_024
LC_EXTERNAL_MISSING_SUBJECT_ASSERTION_COUNT = 196
LC_UNEMITTED_ASSERTION_COUNT = 600
LC_EXTERNAL_TARGET_LABEL_COUNT = 792_166
LC_EXTERNAL_TARGET_COUNT = 792_134
LC_EXTERNAL_NON_FAST_TARGET_COUNT = 256_762
LC_EXTERNAL_RECOVERED_TARGET_COUNT = 365_293
LC_EXTERNAL_NON_FAST_LABEL_COUNTS_BY_LANGUAGE = MappingProxyType(
    {"de": 42_725, "en": 41_911, "es": 42_609, "fi": 14_626, "fr": 83_379, "it": 17_490, "ja": 14_050}
)
LC_EXTERNAL_NON_FAST_TARGET_COUNTS_BY_LANGUAGE = MappingProxyType(
    {"de": 42_725, "en": 41_883, "es": 42_609, "fi": 14_626, "fr": 83_379, "it": 17_490, "ja": 14_050}
)
LC_EXTERNAL_RECOVERED_LABEL_COUNTS_BY_LANGUAGE = MappingProxyType(
    {"de": 42_725, "en": 150_446, "es": 42_609, "fi": 14_626, "fr": 83_379, "it": 17_490, "ja": 14_050}
)
LC_EXTERNAL_RECOVERED_TARGET_COUNTS_BY_LANGUAGE = MappingProxyType(
    {"de": 42_725, "en": 150_414, "es": 42_609, "fi": 14_626, "fr": 83_379, "it": 17_490, "ja": 14_050}
)
LC_EXTERNAL_TARGET_MULTI_LABEL_COUNT = 32
LC_EXTERNAL_EXPLICIT_ENGLISH_LABEL_COUNT = 0
LC_EXTERNAL_TARGET_COUNTS_BY_VOCABULARY = MappingProxyType(
    {
        "agrovoc": 1_105,
        "bncf": 17_490,
        "bne": 42_609,
        "getty-aat": 931,
        "getty-ulan": 125,
        "fast": 108_531,
        "gnd": 42_725,
        "homosaurus": 600,
        "nalt": 14_524,
        "ndl-names": 21,
        "ndl-subjects": 14_029,
        "periodo-lcsh-periods": 1_478,
        "rameau": 83_379,
        "wikidata": 23_120,
        "yso": 14_626,
    }
)
LC_EXTERNAL_EMITTED_ASSERTION_COUNTS_BY_VOCABULARY = MappingProxyType(
    {
        "agrovoc": 1_105,
        "bncf": 18_177,
        "bne": 43_293,
        "getty-aat": 933,
        "getty-ulan": 125,
        "gnd": 45_194,
        "homosaurus": 600,
        "nalt": 15_695,
        "ndl-subjects": 14_557,
        "periodo-lcsh-periods": 1_477,
        "rameau": 86_933,
        "wikidata": 23_324,
        "yso": 15_611,
    }
)

LC_EXTERNAL_LINKS_MAPPING_POLICY = MappingProxyType(
    {
        "admission": (
            "emit LC assertions when the pinned sources provide real content for both endpoints; "
            "reuse current FAST objects and emit every other target from its LC-published label"
        ),
        "direction": (
            "preserve LC's LCSH-to-FAST direction and do not mint an inverse; "
            "the producer retains these hierarchy claims when it refuses direct "
            "OCLC relatedMatch conflicts under SKOS S27"
        ),
        "evidence": (
            "one exact LC N-Triples statement per assertion, with the rolling "
            "archive pinned by URL, retrieval timestamp, digest, and byte length"
        ),
        "predicateAdoption": (
            "translate only the four MADS external-authority predicates to the "
            "SKOS mapping predicates named as their equivalents in LC MADS/RDF documentation"
        ),
        "transitivity": "no inverse assertions and no transitive closure",
        "version": "atlas-3-lc-external-links-mads-to-skos-adoption-v2",
    }
)


def _external_pin(source_root: Path, *, role: str) -> RegistryInputPin:
    return RegistryInputPin(
        path=Path(source_root) / external.LC_EXTERNAL_LINKS_FILENAME,
        logical_path=("refspec/output/registry-real-data-sources/" + external.LC_EXTERNAL_LINKS_FILENAME),
        sha256=external.LC_EXTERNAL_LINKS_SHA256,
        byte_length=external.LC_EXTERNAL_LINKS_BYTE_LENGTH,
        source_iri=external.LC_EXTERNAL_LINKS_URL,
        role=role,
    )


def _input_set_digest(inputs: Sequence[RegistryInputPin]) -> str:
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


def _source_artifact_metadata() -> dict[str, object]:
    return {
        "byteLength": external.LC_EXTERNAL_LINKS_BYTE_LENGTH,
        "digest": external.LC_EXTERNAL_LINKS_SHA256,
        "exactSourceUrl": external.LC_EXTERNAL_LINKS_URL,
        "license": external.LC_LICENSE,
        "licenseUrl": external.LC_LICENSE_URL,
        "publisherVersionedSourceUrl": "publisher provides no versioned URL",
        "retrievedAt": external.LC_EXTERNAL_LINKS_RETRIEVED_AT,
        "rightsStatement": external.LC_RIGHTS_STATEMENT,
        "rightsStatementUrl": external.LC_RIGHTS_STATEMENT_URL,
        "versioning": (
            "LC publishes a rolling latest file; the digest and byte length pin "
            "the retrieved bytes so later drift is detectable"
        ),
    }


def _load_capture_and_fast(
    source_root: Path,
) -> tuple[
    external.LcExternalLinksCapture,
    RegistryRelease,
    tuple[external.LcExternalLinkAssertion, ...],
    tuple[external.LcExternalLinkAssertion, ...],
    tuple[external.LcExternalLinkAssertion, ...],
]:
    capture = external.load_lc_external_links_capture(Path(source_root) / external.LC_EXTERNAL_LINKS_FILENAME)
    fast_release = load_fast_topical_release(source_root)
    active_fast_iris = {resource.iri for resource in fast_release.resources}
    fast_rows = tuple(row for row in capture.assertions if row.target_vocabulary == "fast")
    held_target_rows = tuple(row for row in fast_rows if row.object_iri in active_fast_iris)
    absent = tuple(row for row in fast_rows if row.object_iri not in active_fast_iris)
    missing_lcsh_subject = tuple(
        row for row in held_target_rows if row.subject_iri in LC_FAST_MISSING_LCSH_SUBJECT_IRIS
    )
    emitted = tuple(row for row in held_target_rows if row.subject_iri not in LC_FAST_MISSING_LCSH_SUBJECT_IRIS)
    observed = {
        "absentAssertionCount": len(absent),
        "absentPredicateCounts": dict(sorted(Counter(row.predicate_iri for row in absent).items())),
        "activeFastResourceCount": len(active_fast_iris),
        "emittedAssertionCount": len(emitted),
        "emittedLcshSubjectCount": len({row.subject_iri for row in emitted}),
        "emittedPredicateCounts": dict(sorted(Counter(row.predicate_iri for row in emitted).items())),
        "emittedTargetCount": len({row.object_iri for row in emitted}),
        "heldTargetAssertionCount": len(held_target_rows),
        "heldTargetPredicateCounts": dict(sorted(Counter(row.predicate_iri for row in held_target_rows).items())),
        "missingLcshSubjectAssertionCount": len(missing_lcsh_subject),
        "missingLcshSubjectIris": sorted({row.subject_iri for row in missing_lcsh_subject}),
        "sourceAssertionCount": len(fast_rows),
    }
    expected = {
        "absentAssertionCount": LC_FAST_ABSENT_ENDPOINT_ASSERTION_COUNT,
        "absentPredicateCounts": dict(LC_FAST_ABSENT_ENDPOINT_PREDICATE_COUNTS),
        "activeFastResourceCount": LC_FAST_ACTIVE_RESOURCE_COUNT,
        "emittedAssertionCount": LC_FAST_ACTIVE_EMITTED_ASSERTION_COUNT,
        "emittedLcshSubjectCount": LC_FAST_LCSH_SUBJECT_COUNT,
        "emittedPredicateCounts": dict(LC_FAST_ACTIVE_EMITTED_PREDICATE_COUNTS),
        "emittedTargetCount": LC_FAST_REACHED_RESOURCE_COUNT,
        "heldTargetAssertionCount": LC_FAST_HELD_TARGET_ASSERTION_COUNT,
        "heldTargetPredicateCounts": dict(LC_FAST_HELD_TARGET_PREDICATE_COUNTS),
        "missingLcshSubjectAssertionCount": len(LC_FAST_MISSING_LCSH_SUBJECT_IRIS),
        "missingLcshSubjectIris": sorted(LC_FAST_MISSING_LCSH_SUBJECT_IRIS),
        "sourceAssertionCount": LC_FAST_SOURCE_ASSERTION_COUNT,
    }
    if observed != expected:
        raise ValueError(
            f"LC external-links FAST endpoint selection drifted: expected={expected!r}, observed={observed!r}"
        )
    return capture, fast_release, emitted, absent, missing_lcsh_subject


def _external_target_endpoint_releases(
    capture: external.LcExternalLinksCapture,
    *,
    source_pin: RegistryInputPin,
    active_fast_iris: Collection[str],
    fast_release_inputs: Sequence[RegistryInputPin],
) -> tuple[RegistryRelease, ...]:
    labels_by_vocabulary: dict[
        str,
        list[tuple[str, Sequence[external.LcExternalEndpointLabel]]],
    ] = {vocabulary: [] for vocabulary in LC_EXTERNAL_TARGET_VOCABULARIES}
    target_vocabularies = {row.object_iri: row.target_vocabulary for row in capture.assertions}
    for endpoint_iri, labels in capture.endpoint_labels.items():
        vocabulary = target_vocabularies.get(endpoint_iri)
        if vocabulary is not None and not (vocabulary == "fast" and endpoint_iri in active_fast_iris):
            labels_by_vocabulary[vocabulary].append((endpoint_iri, labels))
    observed_counts = {vocabulary: len(records) for vocabulary, records in sorted(labels_by_vocabulary.items())}
    if observed_counts != dict(LC_EXTERNAL_TARGET_COUNTS_BY_VOCABULARY):
        raise ValueError(
            "LC external target endpoint counts drifted: "
            f"expected={dict(LC_EXTERNAL_TARGET_COUNTS_BY_VOCABULARY)!r}, "
            f"observed={observed_counts!r}"
        )
    observed_label_languages = Counter(
        label.determined_language
        for records in labels_by_vocabulary.values()
        for _endpoint_iri, labels in records
        for label in labels
    )
    observed_target_languages = Counter(
        str(labels[0].determined_language)
        for records in labels_by_vocabulary.values()
        for _endpoint_iri, labels in records
    )
    if dict(sorted(observed_label_languages.items())) != dict(LC_EXTERNAL_RECOVERED_LABEL_COUNTS_BY_LANGUAGE) or dict(
        sorted(observed_target_languages.items())
    ) != dict(LC_EXTERNAL_RECOVERED_TARGET_COUNTS_BY_LANGUAGE):
        raise ValueError("LC external target language distribution drifted")

    releases: list[RegistryRelease] = []
    for vocabulary in sorted(labels_by_vocabulary):
        resources: list[RegistryResource] = []
        language_counts: Counter[str] = Counter()
        publisher_label_count = 0
        for endpoint_iri, publisher_labels in sorted(labels_by_vocabulary[vocabulary]):
            if any(
                label.determined_language is None or label.language_determined_by is None for label in publisher_labels
            ):
                raise ValueError(f"LC external endpoint has an indeterminate label: {endpoint_iri}")
            ordered_labels = tuple(sorted(publisher_labels, key=lambda item: item.line_number))
            normalized_sources: list[external.LcExternalEndpointLabel] = []
            seen_normalized_labels: set[tuple[str, str]] = set()
            for label in ordered_labels:
                normalized_value = label.value.strip()
                if not normalized_value:
                    raise ValueError(f"LC external endpoint has an empty normalized label: {endpoint_iri}")
                normalized_key = (normalized_value, str(label.determined_language))
                if normalized_key in seen_normalized_labels:
                    continue
                seen_normalized_labels.add(normalized_key)
                normalized_sources.append(label)
            normalized_labels = tuple(
                RegistryLabel(
                    value=label.value.strip(),
                    role="preferred" if index == 0 else "alternate",
                    source_path=f"{external.LC_EXTERNAL_LINKS_MEMBER}-line-{label.line_number}",
                    language=str(label.determined_language),
                )
                for index, label in enumerate(normalized_sources)
            )
            publisher_label_count += len(ordered_labels)
            language_counts.update(label.language for label in normalized_labels)
            statement_digests = [label.statement_sha256 for label in ordered_labels]
            language_rules = {str(label.language_determined_by) for label in ordered_labels}
            if len(language_rules) != 1:
                raise ValueError(f"LC external endpoint uses more than one language rule: {endpoint_iri}")
            resources.append(
                RegistryResource(
                    iri=endpoint_iri,
                    labels=normalized_labels,
                    native_payload={
                        "languageDeterminedBy": next(iter(language_rules)),
                        "publisherLabels": [
                            {
                                "determinedLanguageTag": label.determined_language,
                                "languageDeterminedBy": label.language_determined_by,
                                "lineNumber": label.line_number,
                                "nativeStatement": label.native_statement,
                                "publisherLanguageTagPresent": False,
                                "publisherPredicateIri": external.MADS_AUTHORITATIVE_LABEL,
                                "sourceRecordDigest": label.statement_sha256,
                                "value": label.value,
                            }
                            for label in ordered_labels
                        ],
                        "publisherLanguageTagPresent": False,
                        "targetVocabulary": vocabulary,
                    },
                    source_locator=(
                        f"{source_pin.source_iri}#{external.LC_EXTERNAL_LINKS_MEMBER}-line-"
                        f"{ordered_labels[0].line_number}"
                    ),
                    source_digest=canonical_digest(statement_digests),
                    status="alignmentEndpoint",
                )
            )
        release_key = LC_EXTERNAL_TARGET_ENDPOINT_RELEASE_KEYS[vocabulary]
        atlas_release_iri = LC_EXTERNAL_TARGET_ATLAS_RELEASE_IRIS[vocabulary]
        inputs = (source_pin, *fast_release_inputs) if vocabulary == "fast" else (source_pin,)
        releases.append(
            RegistryRelease(
                key=release_key,
                resource_id=f"lc-external-{vocabulary}-endpoints",
                source_module="refspec.registry.lc_external_links",
                profile="conceptScheme",
                ring="subject",
                scope="captureSubset",
                issued="2026-08-15",
                source_release_iri=(
                    f"urn:ref:source-release:lc-external-{vocabulary}-endpoints:"
                    + source_pin.sha256.removeprefix("sha256:")
                ),
                source_release_digest=source_pin.sha256,
                atlas_release_iri=atlas_release_iri,
                scheme_iri=(f"urn:ref:atlas-resource-scheme:lc-external-{vocabulary}-endpoints"),
                inputs=inputs,
                resources=tuple(resources),
                metadata={
                    "completePublisherRelease": False,
                    "endpointOwnershipPreference": "mappingPublisherSuppliedTargetContent",
                    "existingEndpointExclusionCount": (
                        LC_FAST_HELD_TARGET_ASSERTION_COUNT if vocabulary == "fast" else 0
                    ),
                    "languageDeterminationRule": external.TARGET_LABEL_LANGUAGE_RULES[vocabulary][1],
                    "languageDistribution": dict(sorted(language_counts.items())),
                    "mappingEndpointSubset": True,
                    "preferredLabelSelectionRule": (
                        "first authoritativeLabel statement by source line is preferred; "
                        "additional publisher authoritativeLabel statements are retained as alternate labels"
                    ),
                    "publisherLabelCount": publisher_label_count,
                    "publisherLanguageTagPresent": False,
                    "resourceCount": len(resources),
                    "sourceArtifact": _source_artifact_metadata(),
                    "sourceIdentifierCount": 0,
                    "targetVocabulary": vocabulary,
                },
            )
        )
    return tuple(releases)


def load_lc_external_target_endpoint_releases(
    source_root: Path = DEFAULT_SOURCE_ROOT,
) -> tuple[RegistryRelease, ...]:
    """Emit contentful targets not already present in the current FAST release."""

    source_pin = _external_pin(source_root, role="publisherEndpointSource")
    capture = external.load_lc_external_links_capture(source_pin.path)
    fast_release = load_fast_topical_release(source_root)
    active_fast_iris = frozenset(resource.iri for resource in fast_release.resources)
    return _external_target_endpoint_releases(
        capture,
        source_pin=source_pin,
        active_fast_iris=active_fast_iris,
        fast_release_inputs=fast_release.inputs,
    )


def _mapping_evidence(
    row: external.LcExternalLinkAssertion,
    *,
    mapping_predicate: str,
    source_pin: RegistryInputPin,
) -> RegistryMappingEvidence:
    triple_digest = mapping_triple_digest(
        subject_iri=row.subject_iri,
        predicate_iri=mapping_predicate,
        object_iri=row.object_iri,
    )
    return RegistryMappingEvidence(
        source_locator=(f"{source_pin.source_iri}#{external.LC_EXTERNAL_LINKS_MEMBER}-line-{row.line_number}"),
        # The locator identifies a row inside the pinned ZIP. The evidence
        # digest therefore identifies that ZIP; the exact row digest remains
        # in publisherClaim.sourceRecordDigest below.
        source_digest=source_pin.sha256,
        native_payload={
            "mappingTripleDigest": triple_digest,
            "objectIri": row.object_iri,
            "operatorAdoption": {
                "adoptedBy": LC_MAPPING_ADOPTION_REVIEWER_IRI,
                "fromPredicateIri": row.predicate_iri,
                "toPredicateIri": mapping_predicate,
            },
            "predicateIri": mapping_predicate,
            "publisherClaim": {
                "nativeStatement": row.native_statement,
                "objectIri": row.object_iri,
                "predicateIri": row.predicate_iri,
                "sourceEncoding": "ntriplesStatement",
                "sourceRecordDigest": row.statement_sha256,
                "subjectIri": row.subject_iri,
            },
            "subjectIri": row.subject_iri,
        },
        review_warrant="operatorAdoption",
        reviewer_iri=LC_MAPPING_ADOPTION_REVIEWER_IRI,
        attested_at=LC_MAPPING_DECIDED_AT,
    )


def _unemitted_counts(
    capture: external.LcExternalLinksCapture,
    emitted: Collection[external.LcExternalLinkAssertion],
) -> tuple[dict[str, int], dict[str, int]]:
    emitted_claims = {(row.subject_iri, row.predicate_iri, row.object_iri) for row in emitted}
    rows = (
        row for row in capture.assertions if (row.subject_iri, row.predicate_iri, row.object_iri) not in emitted_claims
    )
    by_vocabulary: Counter[str] = Counter()
    by_predicate: Counter[str] = Counter()
    for row in rows:
        by_vocabulary[row.target_vocabulary] += 1
        by_predicate[row.predicate_iri] += 1
    return dict(sorted(by_vocabulary.items())), dict(sorted(by_predicate.items()))


def load_lc_external_links_mapping_release(
    source_root: Path = DEFAULT_SOURCE_ROOT,
) -> RegistryMappingRelease:
    """Load every exact LC assertion whose two endpoints carry real content.

    The LCSH (subject) side resolves against the consolidated LCSH release
    (``v3_registry_alignments_lcsh.load_lcsh_consolidated_release``): every
    current LCSH heading, plus the deprecated headings this and the other
    held mappings reference. This release previously bootstrapped its own
    LCSH endpoint capture (the retired ``lcsh-external-links-endpoints``
    release); the consolidated release already holds every one of its
    candidate subjects that the bulk file contains at all, so the emitted
    count is unchanged -- only the LCSH endpoint's owning release changes.
    """

    capture, fast_release, _active_fast_emitted, outside_current_fast, _missing_active_fast_subject = (
        _load_capture_and_fast(source_root)
    )
    consolidated_release = load_lcsh_consolidated_release(source_root)
    held_lcsh_subjects = frozenset(resource.iri for resource in consolidated_release.resources)
    candidate_subject_iris = set(capture.lcsh_subject_iris)
    missing_lcsh_subject_iris = tuple(sorted(candidate_subject_iris - held_lcsh_subjects))
    if len(missing_lcsh_subject_iris) != LC_ALL_MISSING_LCSH_SUBJECT_COUNT:
        raise ValueError(
            "LCSH bulk missing-subject count differs: "
            f"expected={LC_ALL_MISSING_LCSH_SUBJECT_COUNT}, observed={len(missing_lcsh_subject_iris)}"
        )
    emitted = tuple(row for row in capture.assertions if row.subject_iri in held_lcsh_subjects)
    fast_emitted = tuple(row for row in emitted if row.target_vocabulary == "fast")
    external_emitted = tuple(row for row in emitted if row.target_vocabulary != "fast")
    if len(external_emitted) != LC_EXTERNAL_EMITTED_ASSERTION_COUNT or dict(
        sorted(Counter(row.target_vocabulary for row in external_emitted).items())
    ) != dict(LC_EXTERNAL_EMITTED_ASSERTION_COUNTS_BY_VOCABULARY):
        raise ValueError("LC external-vocabulary emitted assertion shape differs")
    if len(fast_emitted) != LC_FAST_EMITTED_ASSERTION_COUNT or dict(
        sorted(Counter(row.predicate_iri for row in emitted).items())
    ) != dict(LC_EMITTED_PUBLISHER_PREDICATE_COUNTS):
        raise ValueError("LC external-links emitted FAST or predicate shape differs")
    active_fast_iris = frozenset(resource.iri for resource in fast_release.resources)
    source_pin = _external_pin(source_root, role="publisherMappingSource")
    mappings = tuple(
        RegistryMapping(
            subject=row.subject_iri,
            predicate=MADS_TO_SKOS_PREDICATE[row.predicate_iri],
            object=row.object_iri,
            subject_atlas_release_iri=LCSH_CONSOLIDATED_ATLAS_RELEASE_IRI,
            object_atlas_release_iri=(
                fast_release.atlas_release_iri
                if row.target_vocabulary == "fast" and row.object_iri in active_fast_iris
                else LC_EXTERNAL_TARGET_ATLAS_RELEASE_IRIS[row.target_vocabulary]
            ),
            asserted_at=LC_MAPPING_DECIDED_AT,
            evidence=(
                _mapping_evidence(
                    row,
                    mapping_predicate=MADS_TO_SKOS_PREDICATE[row.predicate_iri],
                    source_pin=source_pin,
                ),
            ),
        )
        for row in emitted
    )
    expected_mapping_count = LC_FAST_EMITTED_ASSERTION_COUNT + LC_EXTERNAL_EMITTED_ASSERTION_COUNT
    if len(mappings) != expected_mapping_count:
        raise ValueError(
            "LC external-links emitted mapping count differs: "
            f"expected {expected_mapping_count}, observed {len(mappings)}"
        )

    by_vocabulary, by_predicate = _unemitted_counts(capture, emitted)
    if sum(by_vocabulary.values()) != LC_UNEMITTED_ASSERTION_COUNT:
        raise ValueError("LC external-links unemitted assertion accounting differs")
    external_unemitted = sum(count for vocabulary, count in by_vocabulary.items() if vocabulary != "fast")
    if external_unemitted != LC_EXTERNAL_MISSING_SUBJECT_ASSERTION_COUNT:
        raise ValueError("LC external-links external-vocabulary accounting differs")
    if (
        len(capture.endpoint_labels) != LC_EXTERNAL_TARGET_COUNT
        or sum(len(values) for values in capture.endpoint_labels.values()) != LC_EXTERNAL_TARGET_LABEL_COUNT
        or capture.explicitly_english_target_count != LC_EXTERNAL_EXPLICIT_ENGLISH_LABEL_COUNT
        or sum(len(values) > 1 for values in capture.endpoint_labels.values()) != LC_EXTERNAL_TARGET_MULTI_LABEL_COUNT
    ):
        raise ValueError("LC external-links endpoint-label accounting differs")

    return RegistryMappingRelease(
        key=LCSH_EXTERNAL_LINKS_MAPPING_RELEASE_KEY,
        resource_id="lcsh-external-links-mapping",
        source_module="refspec.registry.lc_external_links",
        ring="subject",
        scope="captureSubset",
        issued="2026-08-15",
        source_release_iri=(
            "urn:ref:registry-mapping-release:lcsh-external-links:" + source_pin.sha256.removeprefix("sha256:")
        ),
        source_release_digest=source_pin.sha256,
        # Mapping inputs are evidence-bearing artifacts. LCSH, FAST, and the
        # endpoint-selection capture are construction dependencies represented
        # by the mapping's exact endpoint releases, not duplicate raw inputs.
        inputs=(source_pin,),
        mappings=mappings,
        editorial_policy=LC_EXTERNAL_LINKS_MAPPING_POLICY,
        metadata={
            "assertionCountsByPublisherPredicate": (capture.assertion_counts_by_publisher_predicate),
            "assertionCountsByTargetVocabulary": capture.assertion_counts_by_vocabulary,
            "capturedAssertionCount": len(capture.assertions),
            "capturedExternalEndpointLabelCount": sum(len(values) for values in capture.endpoint_labels.values()),
            "capturedExternalTargetCount": len(capture.endpoint_labels),
            "contentfulNonFastEndpointCount": LC_EXTERNAL_NON_FAST_TARGET_COUNT,
            "contentfulRecoveredEndpointCount": LC_EXTERNAL_RECOVERED_TARGET_COUNT,
            "determinedLanguageLabelCounts": capture.determined_language_label_counts,
            "determinedLanguageTargetCounts": capture.determined_language_target_counts,
            "emittedAssertionCount": len(mappings),
            "emittedPredicateCounts": dict(sorted(Counter(row.predicate for row in mappings).items())),
            "endpointCoverage": {
                "activeFastResourceCount": LC_FAST_ACTIVE_RESOURCE_COUNT,
                "exactIriCoveragePercent": LC_FAST_REACHED_RESOURCE_PERCENT,
                "reachedFastResourceCount": LC_FAST_REACHED_RESOURCE_COUNT,
            },
            "externalEndpointDisposition": {
                "capturedNonFastAssertionCount": LC_EXTERNAL_TARGET_ASSERTION_COUNT,
                "classifiedTargetCount": LC_EXTERNAL_TARGET_COUNT,
                "emittedNonFastAssertionCount": len(external_emitted),
                "explicitEnglishLabelCount": capture.explicitly_english_target_count,
                "missingNonFastSubjectAssertionCount": external_unemitted,
                "recoveredEndpointCount": LC_EXTERNAL_RECOVERED_TARGET_COUNT,
                "reusedCurrentFastEndpointCount": LC_FAST_HELD_TARGET_ASSERTION_COUNT,
                "reason": (
                    "target labels use deterministic authority or source conventions; "
                    "rows are omitted only when the pinned LCSH source has no subject record"
                ),
                "status": "emittedWithDeterminedLanguage",
            },
            "fastEndpointOutsideCurrentReleaseCount": len(outside_current_fast),
            "fastEndpointOutsideCurrentReleaseDisposition": (
                "emitted from captured LC labels in the lc-external-fast endpoint release"
            ),
            "fastEndpointOutsideCurrentReleasePredicateCounts": dict(LC_FAST_ABSENT_ENDPOINT_PREDICATE_COUNTS),
            "lcshEndpointAbsentCount": len(missing_lcsh_subject_iris),
            "lcshEndpointAbsentIris": list(missing_lcsh_subject_iris),
            "lcshEndpointAbsentReason": (
                "subject absent from the separately pinned current LCSH topical "
                "bulk file; no mapping endpoint resource can be verified"
            ),
            "madsRdfPredicateCorrespondence": {
                "documentationUrl": LC_MADS_DOCUMENTATION_URL,
                "fromTo": dict(MADS_TO_SKOS_PREDICATE),
            },
            "otherPublisherDirection": {
                "adoptedExactMatchCount": 252_527,
                "direction": "FAST-to-LCSH",
                "publisher": "OCLC",
                "publisherVerbatimRelatedMatchCount": 349_932,
                "relationship": (
                    "independent assertions from a different publisher with different "
                    "predicates; the producer retains LC hierarchy and refuses the "
                    "frozen direct OCLC relatedMatch conflicts under SKOS S27"
                ),
            },
            "sourceArtifact": _source_artifact_metadata(),
            "sourceIdentifierCount": 0,
            "unemittedAssertionCount": sum(by_vocabulary.values()),
            "unemittedAssertionCountsByPublisherPredicate": by_predicate,
            "unemittedAssertionCountsByTargetVocabulary": by_vocabulary,
        },
    )


def load_lc_registry_alignment_endpoint_releases(
    source_root: Path = DEFAULT_SOURCE_ROOT,
    *,
    only_keys: Collection[str] | None = None,
) -> tuple[RegistryRelease, ...]:
    """Load selected LC external-links endpoint releases."""

    requested = normalize_only_keys(
        only_keys,
        allowed_keys=LC_REGISTRY_ALIGNMENT_ENDPOINT_RELEASE_KEYS,
        loader_name="load_lc_registry_alignment_endpoint_releases",
    )
    if not wants_group(requested, LC_REGISTRY_ALIGNMENT_ENDPOINT_RELEASE_KEYS):
        return ()
    loaded: list[RegistryRelease] = []
    target_keys = frozenset(LC_EXTERNAL_TARGET_ENDPOINT_RELEASE_KEYS.values())
    if requested is None or requested & target_keys:
        loaded.extend(load_lc_external_target_endpoint_releases(source_root))
    return select_declared_group(
        tuple(loaded),
        declared_keys=LC_REGISTRY_ALIGNMENT_ENDPOINT_RELEASE_KEYS,
        requested_keys=requested,
        loader_name="load_lc_registry_alignment_endpoint_releases",
    )


def load_lc_registry_mapping_releases(
    source_root: Path = DEFAULT_SOURCE_ROOT,
    *,
    only_keys: Collection[str] | None = None,
) -> tuple[RegistryMappingRelease, ...]:
    """Load selected LC external-links mapping releases."""

    requested = normalize_only_keys(
        only_keys,
        allowed_keys=LC_REGISTRY_MAPPING_RELEASE_KEYS,
        loader_name="load_lc_registry_mapping_releases",
    )
    if not wants_group(requested, LC_REGISTRY_MAPPING_RELEASE_KEYS):
        return ()
    return select_declared_group(
        (load_lc_external_links_mapping_release(source_root),),
        declared_keys=LC_REGISTRY_MAPPING_RELEASE_KEYS,
        requested_keys=requested,
        loader_name="load_lc_registry_mapping_releases",
    )


__all__ = [
    "DEFAULT_SOURCE_ROOT",
    "LCSH_EXTERNAL_LINKS_MAPPING_RELEASE_KEY",
    "LC_ALL_MISSING_LCSH_SUBJECT_COUNT",
    "LC_EXTERNAL_EMITTED_ASSERTION_COUNT",
    "LC_EXTERNAL_EXPLICIT_ENGLISH_LABEL_COUNT",
    "LC_EXTERNAL_LINKS_MAPPING_POLICY",
    "LC_EXTERNAL_NON_FAST_LABEL_COUNTS_BY_LANGUAGE",
    "LC_EXTERNAL_NON_FAST_TARGET_COUNT",
    "LC_EXTERNAL_NON_FAST_TARGET_COUNTS_BY_LANGUAGE",
    "LC_EXTERNAL_RECOVERED_LABEL_COUNTS_BY_LANGUAGE",
    "LC_EXTERNAL_RECOVERED_TARGET_COUNT",
    "LC_EXTERNAL_RECOVERED_TARGET_COUNTS_BY_LANGUAGE",
    "LC_EXTERNAL_TARGET_ATLAS_RELEASE_IRIS",
    "LC_EXTERNAL_TARGET_COUNTS_BY_VOCABULARY",
    "LC_EXTERNAL_TARGET_ENDPOINT_RELEASE_KEYS",
    "LC_FAST_ABSENT_ENDPOINT_ASSERTION_COUNT",
    "LC_FAST_ABSENT_ENDPOINT_PREDICATE_COUNTS",
    "LC_FAST_ACTIVE_EMITTED_PREDICATE_COUNTS",
    "LC_FAST_ACTIVE_RESOURCE_COUNT",
    "LC_FAST_EMITTED_ASSERTION_COUNT",
    "LC_FAST_LCSH_SUBJECT_COUNT",
    "LC_FAST_REACHED_RESOURCE_COUNT",
    "LC_FAST_REACHED_RESOURCE_PERCENT",
    "LC_FAST_SOURCE_ASSERTION_COUNT",
    "LC_MAPPING_ADOPTION_REVIEWER_IRI",
    "LC_REGISTRY_ALIGNMENT_ENDPOINT_RELEASE_KEYS",
    "LC_REGISTRY_MAPPING_RELEASE_KEYS",
    "MADS_TO_SKOS_PREDICATE",
    "load_lc_external_links_mapping_release",
    "load_lc_external_target_endpoint_releases",
    "load_lc_registry_alignment_endpoint_releases",
    "load_lc_registry_mapping_releases",
]
