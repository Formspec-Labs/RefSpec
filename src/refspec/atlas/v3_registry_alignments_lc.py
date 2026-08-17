"""Atlas 3 release adapters for LC-authored LCSH external links.

LC owns the LCSH source vocabulary and asserts each row into a vocabulary
owned elsewhere.  The MADS/RDF source predicates are translated only to the
SKOS mapping predicates LC documents as their equivalents, so every emitted
row uses ``operatorAdoption`` and records the source predicate, target
predicate, and adopting actor.  No inverse or transitive assertion is added.
"""

from __future__ import annotations

import gzip
import hashlib
import json
from collections import Counter
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType

from refspec.atlas.v3_registry_large import load_fast_topical_release
from refspec.atlas.v3_registry_selection import normalize_only_keys, select_declared_group, wants_group
from refspec.atlas.v3_source_data import (
    LabelRole,
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
from refspec.registry import lc_external_links as external
from refspec.registry import lcsh_topical as lcsh
from refspec.registry.eurovoc_lcsh_alignment import (
    EUROVOC_LCSH_ALIGNMENT_BYTE_LENGTH,
    EUROVOC_LCSH_ALIGNMENT_FILENAME,
    EUROVOC_LCSH_ALIGNMENT_SHA256,
    EUROVOC_LCSH_ALIGNMENT_URL,
    parse_eurovoc_lcsh_alignment_file,
)
from refspec.vocabulary import is_english_language_tag

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_SOURCE_ROOT = REPOSITORY_ROOT / "output" / "registry-real-data-sources"

LCSH_BULK_FILENAME = "lcsh-subjects-madsrdf-2026-08-06.jsonld.gz"
LCSH_BULK_SHA256 = "sha256:b33adc284bfb98e39c1331927e9ffee3d73dd0b1b83342906b6ea52c408a5856"
LCSH_BULK_BYTE_LENGTH = 140_187_915
LCSH_BULK_CAPTURED_AT = "2026-08-06"

LCSH_EUROVOC_ENDPOINT_ATLAS_RELEASE_IRI = "urn:ref:atlas-release:3:lcsh-subjects:eurovoc-alignment-endpoints:2026-08-06"
LCSH_EXTERNAL_LINKS_ENDPOINT_ATLAS_RELEASE_IRI = (
    "urn:ref:atlas-release:3:lcsh-subjects:external-links-endpoints:2026-08-15"
)
LCSH_EXTERNAL_LINKS_ENDPOINT_RELEASE_KEY = "lcsh-external-links-endpoints-2026-08-15"
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
LC_REGISTRY_ALIGNMENT_ENDPOINT_RELEASE_KEYS = frozenset(
    {LCSH_EXTERNAL_LINKS_ENDPOINT_RELEASE_KEY, *LC_EXTERNAL_TARGET_ENDPOINT_RELEASE_KEYS.values()}
)
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
LC_ALL_CANDIDATE_LCSH_SUBJECT_COUNT = 362_148
LC_ALL_EXISTING_LCSH_ENDPOINT_SUBJECT_COUNT = 1_951
LC_ALL_CANDIDATE_NEW_LCSH_ENDPOINT_SUBJECT_COUNT = 360_197
LC_ALL_NEW_LCSH_ENDPOINT_SUBJECT_COUNT = 359_728
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


def _lcsh_bulk_pin(source_root: Path) -> RegistryInputPin:
    return RegistryInputPin(
        path=Path(source_root) / LCSH_BULK_FILENAME,
        logical_path=f"refspec/output/registry-real-data-sources/{LCSH_BULK_FILENAME}",
        sha256=LCSH_BULK_SHA256,
        byte_length=LCSH_BULK_BYTE_LENGTH,
        source_iri=lcsh.LCSH_TOPICAL_MADS_NDJSON_URL,
        role="publisherSubjectEndpointSource",
    )


def _existing_endpoint_selection_pin(source_root: Path) -> RegistryInputPin:
    return RegistryInputPin(
        path=Path(source_root) / EUROVOC_LCSH_ALIGNMENT_FILENAME,
        logical_path=("refspec/output/registry-real-data-sources/" + EUROVOC_LCSH_ALIGNMENT_FILENAME),
        sha256=EUROVOC_LCSH_ALIGNMENT_SHA256,
        byte_length=EUROVOC_LCSH_ALIGNMENT_BYTE_LENGTH,
        source_iri=EUROVOC_LCSH_ALIGNMENT_URL,
        role="existingEndpointExclusion",
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


@dataclass(frozen=True, slots=True)
class _LcshEndpointRecord:
    concept_iri: str
    labels: tuple[RegistryLabel, ...]
    lccn: str | None
    broader_iris: tuple[str, ...]
    authority_types: tuple[str, ...]
    notes: tuple[str, ...]
    use_instead_iris: tuple[str, ...]
    status: str
    dropped_label_count: int
    source_url: str
    line_number: int
    raw_line: bytes

    @property
    def source_sha256(self) -> str:
        return "sha256:" + hashlib.sha256(self.raw_line).hexdigest()

    @property
    def source_byte_length(self) -> int:
        return len(self.raw_line)


@dataclass(frozen=True, slots=True)
class _LcshEndpointCapture:
    source_url: str
    lines_scanned: int
    requested_iris: tuple[str, ...]
    records: tuple[_LcshEndpointRecord, ...]
    missing_iris: tuple[str, ...]


def _term_set(value: object, *, context: str) -> tuple[str, ...]:
    if isinstance(value, str):
        return (value,)
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        return tuple(sorted(set(value)))
    raise ValueError(f"{context} @type must be text or an array of text")


def _label_value(
    value: object,
    *,
    context: str,
) -> tuple[str, str]:
    if not isinstance(value, dict):
        raise ValueError(f"{context} must be a JSON-LD value object")
    text = value.get("@value")
    language = value.get("@language")
    if not isinstance(text, str) or not text.strip():
        raise ValueError(f"{context} has no non-empty @value")
    if not isinstance(language, str) or not language:
        raise ValueError(f"{context} has no language tag")
    return text.strip(), language


def _reference_list(value: object, *, context: str) -> tuple[dict[str, object], ...]:
    if value is None:
        return ()
    if isinstance(value, dict):
        return (value,)
    if isinstance(value, list) and all(isinstance(item, dict) for item in value):
        return tuple(value)
    raise ValueError(f"{context} must be a reference or array of references")


def _endpoint_record(
    document: dict[str, object],
    *,
    authority: dict[str, object],
    concept_iri: str,
    source_url: str,
    line_number: int,
    raw_line: bytes,
) -> _LcshEndpointRecord:
    types = _term_set(authority.get("@type"), context=concept_iri)
    active = "madsrdf:Authority" in types
    deprecated = "madsrdf:DeprecatedAuthority" in types
    if active == deprecated:
        raise ValueError(f"{concept_iri} line {line_number} must be active or deprecated, not both")
    graph = document.get("@graph")
    if not isinstance(graph, list):
        raise ValueError(f"{concept_iri} line {line_number} has no @graph")
    by_id: dict[str, dict[str, object]] = {}
    for node in graph:
        if not isinstance(node, dict):
            raise ValueError(f"{concept_iri} line {line_number} has a non-object graph node")
        node_id = node.get("@id")
        if not isinstance(node_id, str) or not node_id:
            raise ValueError(f"{concept_iri} line {line_number} has a graph node without @id")
        if node_id in by_id:
            raise ValueError(f"{concept_iri} line {line_number} repeats graph node {node_id}")
        by_id[node_id] = node

    labels: list[RegistryLabel] = []
    seen_values: set[str] = set()
    dropped_label_count = 0

    def add_label(value: object, *, role: LabelRole, source_path: str) -> None:
        nonlocal dropped_label_count
        text, language = _label_value(value, context=f"{concept_iri} {source_path}")
        if not is_english_language_tag(language):
            dropped_label_count += 1
            return
        if text in seen_values:
            return
        seen_values.add(text)
        labels.append(
            RegistryLabel(
                value=text,
                role=role,
                source_path=f"line-{line_number}:{source_path}",
            )
        )

    authoritative = authority.get("madsrdf:authoritativeLabel")
    if authoritative is not None:
        add_label(
            authoritative,
            role="preferred",
            source_path="madsrdf:authoritativeLabel",
        )
    direct_variant = authority.get("madsrdf:variantLabel")
    if direct_variant is not None:
        add_label(
            direct_variant,
            role="alternate",
            source_path="madsrdf:variantLabel",
        )
    for index, reference in enumerate(
        _reference_list(
            authority.get("madsrdf:hasVariant"),
            context=f"{concept_iri} madsrdf:hasVariant",
        )
    ):
        variant_id = reference.get("@id")
        if not isinstance(variant_id, str) or variant_id not in by_id:
            raise ValueError(f"{concept_iri} line {line_number} references an absent variant")
        add_label(
            by_id[variant_id].get("madsrdf:variantLabel"),
            role="alternate",
            source_path=f"madsrdf:hasVariant[{index}]",
        )
    if not labels:
        raise ValueError(f"{concept_iri} line {line_number} has no retained English label")
    if active and sum(label.role == "preferred" for label in labels) != 1:
        raise ValueError(f"{concept_iri} line {line_number} has no preferred label")

    broader_iris = tuple(
        sorted(
            {
                str(reference["@id"])
                for reference in _reference_list(
                    authority.get("madsrdf:hasBroaderAuthority"),
                    context=f"{concept_iri} madsrdf:hasBroaderAuthority",
                )
            }
        )
    )
    lccn = authority.get("identifiers:lccn")
    if lccn is not None and (not isinstance(lccn, str) or not lccn.strip()):
        raise ValueError(f"{concept_iri} line {line_number} has an invalid LCCN")
    deletion_note = authority.get("madsrdf:deletionNote")
    notes: tuple[str, ...] = ()
    if deletion_note is not None:
        note, language = _label_value(
            deletion_note,
            context=f"{concept_iri} madsrdf:deletionNote",
        )
        if is_english_language_tag(language):
            notes = (note,)
        else:
            dropped_label_count += 1
    use_instead = authority.get("madsrdf:useInstead")
    use_instead_iris: tuple[str, ...] = ()
    if use_instead is not None:
        references = _reference_list(
            use_instead,
            context=f"{concept_iri} madsrdf:useInstead",
        )
        targets = tuple(reference.get("@id") for reference in references)
        if any(not isinstance(target, str) or not target.startswith(("http://", "https://")) for target in targets):
            raise ValueError(f"{concept_iri} line {line_number} has invalid useInstead")
        use_instead_iris = tuple(str(target) for target in targets)
    return _LcshEndpointRecord(
        concept_iri=concept_iri,
        labels=tuple(labels),
        lccn=lccn,
        broader_iris=broader_iris,
        authority_types=types,
        notes=notes,
        use_instead_iris=use_instead_iris,
        status="deprecatedAlignmentEndpoint" if deprecated else "alignmentEndpoint",
        dropped_label_count=dropped_label_count,
        source_url=source_url,
        line_number=line_number,
        raw_line=raw_line,
    )


def _blank_broader_evidence(
    document: dict[str, object],
    *,
    authority: dict[str, object],
    concept_iri: str,
    line_number: int,
) -> tuple[dict[str, object], ...]:
    """Remove only unaddressable broader blank nodes and retain their evidence."""

    broader_field = "madsrdf:hasBroaderAuthority"
    raw_broader = authority.get(broader_field)
    if raw_broader is None:
        return ()
    if isinstance(raw_broader, dict):
        references = [raw_broader]
    elif isinstance(raw_broader, list) and all(isinstance(item, dict) for item in raw_broader):
        references = raw_broader
    else:
        raise ValueError(f"{concept_iri} line {line_number} has malformed {broader_field}")
    absolute_references: list[dict[str, object]] = []
    blank_ids: list[str] = []
    for reference in references:
        target = reference.get("@id")
        if not isinstance(target, str) or not target:
            raise ValueError(f"{concept_iri} line {line_number} has a broader reference without @id")
        if target.startswith(("http://", "https://")):
            absolute_references.append(reference)
        elif target.startswith("_:"):
            blank_ids.append(target)
        else:
            raise ValueError(f"{concept_iri} line {line_number} has unsupported broader target {target!r}")
    if absolute_references:
        authority[broader_field] = absolute_references[0] if len(absolute_references) == 1 else absolute_references
    else:
        authority.pop(broader_field, None)

    graph = document.get("@graph")
    if not isinstance(graph, list):
        raise ValueError(f"{concept_iri} line {line_number} has no @graph")
    by_id = {node.get("@id"): node for node in graph if isinstance(node, dict) and isinstance(node.get("@id"), str)}
    evidence: list[dict[str, object]] = []
    for blank_id in blank_ids:
        node = by_id.get(blank_id)
        if not isinstance(node, dict):
            raise ValueError(f"{concept_iri} line {line_number} lacks broader blank node {blank_id}")
        label = node.get("madsrdf:authoritativeLabel")
        if not isinstance(label, dict):
            raise ValueError(f"{concept_iri} line {line_number} broader blank node lacks a label")
        value = label.get("@value")
        language = label.get("@language")
        if not isinstance(value, str) or not value:
            raise ValueError(f"{concept_iri} line {line_number} broader blank node has no label value")
        if language is not None and not isinstance(language, str):
            raise ValueError(f"{concept_iri} line {line_number} broader blank node has invalid language")
        evidence.append(
            {
                "authoritativeLabel": value,
                "blankNodeId": blank_id,
                "language": language,
                "reason": "publisher supplied no absolute IRI for the broader authority",
            }
        )
    return tuple(evidence)


def _capture_lcsh_endpoint_records(
    path: Path,
    *,
    source_url: str,
    concept_iris: Collection[str],
) -> tuple[
    _LcshEndpointCapture,
    Mapping[str, tuple[dict[str, object], ...]],
]:
    """Select LCSH records while retaining unaddressable broader blank nodes."""

    requested = frozenset(concept_iris)
    prefix = lcsh.LCSH_SUBJECTS_SCHEME_IRI + "/"
    if not requested or any(not iri.startswith(prefix) for iri in requested):
        raise ValueError("LC external-links endpoint selection contains a non-LCSH IRI")
    path_to_iri = {"/authorities/subjects/" + iri.removeprefix(prefix): iri for iri in requested}
    selected: dict[str, _LcshEndpointRecord] = {}
    blank_broader: dict[str, tuple[dict[str, object], ...]] = {}
    lines_scanned = 0
    with gzip.open(path, "rb") as lines:
        for line_number, line in enumerate(lines, start=1):
            lines_scanned = line_number
            raw = line.rstrip(b"\r\n")
            if not raw.strip():
                continue
            try:
                document = json.loads(raw)
            except (UnicodeDecodeError, json.JSONDecodeError) as error:
                raise ValueError(f"LCSH bulk line {line_number} is not valid UTF-8 JSON: {error}") from error
            if not isinstance(document, dict):
                raise ValueError(f"LCSH bulk line {line_number} is not a JSON object")
            concept_iri = path_to_iri.get(document.get("@id"))
            if concept_iri is None:
                continue
            if concept_iri in selected:
                raise ValueError(f"LCSH bulk repeats selected authority {concept_iri}")
            graph = document.get("@graph")
            if not isinstance(graph, list):
                raise ValueError(f"{concept_iri} line {line_number} has no @graph")
            authority_nodes = [node for node in graph if isinstance(node, dict) and node.get("@id") == concept_iri]
            if len(authority_nodes) != 1:
                raise ValueError(f"{concept_iri} line {line_number} has no unique authority node")
            authority = authority_nodes[0]
            blank_broader[concept_iri] = _blank_broader_evidence(
                document,
                authority=authority,
                concept_iri=concept_iri,
                line_number=line_number,
            )
            selected[concept_iri] = _endpoint_record(
                document,
                authority=authority,
                concept_iri=concept_iri,
                source_url=source_url,
                line_number=line_number,
                raw_line=raw,
            )
    missing = tuple(sorted(requested - selected.keys()))
    capture = _LcshEndpointCapture(
        source_url=source_url,
        lines_scanned=lines_scanned,
        requested_iris=tuple(sorted(requested)),
        records=tuple(selected[iri] for iri in sorted(selected)),
        missing_iris=missing,
    )
    return capture, MappingProxyType(blank_broader)


def load_lcsh_external_links_endpoint_release(
    source_root: Path = DEFAULT_SOURCE_ROOT,
) -> RegistryRelease:
    """Load the new LCSH subjects required by the emitted LC-to-FAST rows."""

    capture, fast_release, _active_fast_emitted, _, _missing_active_fast_subject = _load_capture_and_fast(source_root)
    selection_pin = _existing_endpoint_selection_pin(source_root)
    selection_pin.verify()
    existing_alignment = parse_eurovoc_lcsh_alignment_file(selection_pin.path)
    existing_endpoint_iris = existing_alignment.lcsh_concept_iris
    candidate_subject_iris = set(capture.lcsh_subject_iris)
    overlap = candidate_subject_iris & existing_endpoint_iris
    candidate_new_subject_iris = candidate_subject_iris - existing_endpoint_iris
    observed_selection = {
        "candidateNewEndpointCount": len(candidate_new_subject_iris),
        "candidateSubjectCount": len(candidate_subject_iris),
        "existingEndpointOverlapCount": len(overlap),
    }
    expected_selection = {
        "candidateNewEndpointCount": LC_ALL_CANDIDATE_NEW_LCSH_ENDPOINT_SUBJECT_COUNT,
        "candidateSubjectCount": LC_ALL_CANDIDATE_LCSH_SUBJECT_COUNT,
        "existingEndpointOverlapCount": LC_ALL_EXISTING_LCSH_ENDPOINT_SUBJECT_COUNT,
    }
    if observed_selection != expected_selection:
        raise ValueError(
            "LC external-links LCSH endpoint partition drifted: "
            f"expected={expected_selection!r}, observed={observed_selection!r}"
        )

    bulk_pin = _lcsh_bulk_pin(source_root)
    bulk_pin.verify()
    selected, blank_broader = _capture_lcsh_endpoint_records(
        bulk_pin.path,
        source_url=bulk_pin.source_iri,
        concept_iris=candidate_new_subject_iris,
    )
    if len(selected.missing_iris) != LC_ALL_MISSING_LCSH_SUBJECT_COUNT:
        raise ValueError(
            "LCSH bulk missing-subject count differs: "
            f"expected={LC_ALL_MISSING_LCSH_SUBJECT_COUNT}, "
            f"observed={len(selected.missing_iris)}"
        )
    if len(selected.records) != LC_ALL_NEW_LCSH_ENDPOINT_SUBJECT_COUNT:
        raise ValueError(
            "LC external-links LCSH endpoint record count differs: "
            f"expected {LC_ALL_NEW_LCSH_ENDPOINT_SUBJECT_COUNT}, "
            f"observed {len(selected.records)}"
        )

    resources = tuple(
        RegistryResource(
            iri=record.concept_iri,
            labels=record.labels,
            native_payload={
                "authorityTypes": list(record.authority_types),
                "broaderIris": list(record.broader_iris),
                "captureSelection": {
                    "externalLinksDigest": capture.source_sha256,
                    "externalLinksSource": capture.source_url,
                    "fastAtlasReleaseIri": fast_release.atlas_release_iri,
                    "reason": "subject of an LC external-authority assertion with a contentful target",
                },
                "lccn": record.lccn,
                "lineNumber": record.line_number,
                "recordByteLength": record.source_byte_length,
                "recordDigest": record.source_sha256,
                "unrepresentedBroaderAuthorities": list(blank_broader[record.concept_iri]),
                "useInsteadIris": list(record.use_instead_iris),
            },
            source_locator=f"{record.source_url}#line-{record.line_number}",
            source_digest=record.source_sha256,
            notes=record.notes,
            notations=(() if record.lccn is None else (record.lccn,)),
            status=record.status,
        )
        for record in selected.records
    )
    loaded_new_subject_iris = {record.concept_iri for record in selected.records}
    if loaded_new_subject_iris != candidate_new_subject_iris - set(selected.missing_iris):
        raise ValueError("loaded LC external-links LCSH endpoint set differs")
    all_loaded_lcsh_iris = loaded_new_subject_iris | existing_endpoint_iris
    relations = tuple(
        RegistryRelation(
            subject=record.concept_iri,
            predicate="http://www.w3.org/2004/02/skos/core#broader",
            object=broader_iri,
            source_payload={
                "lineNumber": record.line_number,
                "objectIri": broader_iri,
                "predicateIri": "http://www.w3.org/2004/02/skos/core#broader",
                "subjectIri": record.concept_iri,
            },
        )
        for record in selected.records
        for broader_iri in record.broader_iris
        if broader_iri in all_loaded_lcsh_iris
    )
    inputs = (
        bulk_pin,
        _external_pin(source_root, role="publisherEndpointSelection"),
        selection_pin,
        *fast_release.inputs,
    )
    return RegistryRelease(
        key=LCSH_EXTERNAL_LINKS_ENDPOINT_RELEASE_KEY,
        resource_id="lcsh-subjects",
        source_module="refspec.registry.lcsh_topical",
        profile="conceptScheme",
        ring="subject",
        scope="captureSubset",
        issued="2026-08-15",
        source_release_iri=("urn:ref:source-release:lcsh-subjects:external-links-endpoints:2026-08-15"),
        source_release_digest=_input_set_digest(inputs),
        atlas_release_iri=LCSH_EXTERNAL_LINKS_ENDPOINT_ATLAS_RELEASE_IRI,
        scheme_iri="urn:ref:atlas-resource-scheme:lcsh-subjects",
        inputs=inputs,
        resources=resources,
        relations=relations,
        dropped_label_count=sum(record.dropped_label_count for record in selected.records),
        metadata={
            "completePublisherRelease": False,
            "existingEndpointOverlapCount": len(overlap),
            "externalLinksSourceArtifact": _source_artifact_metadata(),
            "endpointOwnershipPreference": "publisherOwnedVocabulary",
            "fastAtlasReleaseIri": fast_release.atlas_release_iri,
            "linesScanned": selected.lines_scanned,
            "mappingEndpointSubset": True,
            "missingLcshSubjectCount": len(selected.missing_iris),
            "missingLcshSubjectIris": list(selected.missing_iris),
            "missingLcshSubjectReason": (
                "LC external-links subjects absent from the separately pinned current "
                "LCSH topical bulk file; no endpoint resource can be verified"
            ),
            "newEndpointCount": len(resources),
            "unrepresentedBroaderBlankNodeCount": sum(len(values) for values in blank_broader.values()),
            "publisherReleaseUnspecified": True,
            "selectionRule": (
                "LCSH subjects of LC external-authority assertions whose target has a captured "
                "publisher label; current FAST targets reuse the pinned FAST release and other "
                "targets use the contentful LC endpoint captures; existing LCSH endpoints are reused"
            ),
            "sourceIdentifierCount": 0,
        },
    )


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
    """Load every exact LC assertion whose two endpoints carry real content."""

    capture, fast_release, _active_fast_emitted, outside_current_fast, _missing_active_fast_subject = (
        _load_capture_and_fast(source_root)
    )
    selection_pin = _existing_endpoint_selection_pin(source_root)
    selection_pin.verify()
    existing_endpoint_iris = parse_eurovoc_lcsh_alignment_file(selection_pin.path).lcsh_concept_iris
    candidate_subject_iris = set(capture.lcsh_subject_iris)
    lcsh_pin = _lcsh_bulk_pin(source_root)
    lcsh_pin.verify()
    selected, _blank_broader = _capture_lcsh_endpoint_records(
        lcsh_pin.path,
        source_url=lcsh_pin.source_iri,
        concept_iris=candidate_subject_iris - existing_endpoint_iris,
    )
    held_lcsh_subjects = existing_endpoint_iris | {record.concept_iri for record in selected.records}
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
            subject_atlas_release_iri=(
                LCSH_EUROVOC_ENDPOINT_ATLAS_RELEASE_IRI
                if row.subject_iri in existing_endpoint_iris
                else LCSH_EXTERNAL_LINKS_ENDPOINT_ATLAS_RELEASE_IRI
            ),
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
            "lcshEndpointAbsentCount": len(selected.missing_iris),
            "lcshEndpointAbsentIris": list(selected.missing_iris),
            "lcshEndpointAbsentReason": (
                "subject absent from the separately pinned current LCSH topical "
                "bulk file; no mapping endpoint resource can be verified"
            ),
            "madsRdfPredicateCorrespondence": {
                "documentationUrl": LC_MADS_DOCUMENTATION_URL,
                "fromTo": dict(MADS_TO_SKOS_PREDICATE),
            },
            "otherPublisherDirection": {
                "adoptedExactMatchCount": 1_683,
                "direction": "FAST-to-LCSH",
                "publisher": "OCLC",
                "publisherVerbatimRelatedMatchCount": 62_781,
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
    if requested is None or LCSH_EXTERNAL_LINKS_ENDPOINT_RELEASE_KEY in requested:
        loaded.append(load_lcsh_external_links_endpoint_release(source_root))
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
    "LCSH_EXTERNAL_LINKS_ENDPOINT_ATLAS_RELEASE_IRI",
    "LCSH_EXTERNAL_LINKS_ENDPOINT_RELEASE_KEY",
    "LCSH_EXTERNAL_LINKS_MAPPING_RELEASE_KEY",
    "LC_ALL_NEW_LCSH_ENDPOINT_SUBJECT_COUNT",
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
    "load_lcsh_external_links_endpoint_release",
]
