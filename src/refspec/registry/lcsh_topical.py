"""Bounded streaming reader for the LCSH topical subset.

The Library of Congress publishes every LCSH authority (topical, geographic,
corporate name, complex subject, and more) as one MADS/SKOS JSON-LD graph per
line in a single bulk ndjson.gz distribution
(id.loc.gov/download/authorities/subjects.madsrdf.jsonld.gz, linked from
https://id.loc.gov/authorities/subjects.html). The catalog marks LCSH mapping
only: its bibliographic scope and size make it unsuitable as a candidate pool.
This module never assembles a RefSpec concept scheme from it. It streams the
ndjson one line at a time, retains only records whose madsrdf:Authority type
set also contains madsrdf:Topic, and packages a bounded topical subset as a
source-controlled resource (see source_controlled_resource.py) that carries
the publisher's own concept IRI and LCCN but explicitly claims no concept
identity and is not authorized as a classifier candidate pool.

Every entry point takes bytes, an iterable of lines, or an explicit local
path; importing this module never opens a network connection. Records that
claim to be topical but omit a required field are refused rather than
guessed; non-topical lines are simply skipped, since most of the bulk file is
out of this subset's scope by design. No concept identity is minted: every
identifier retained here is a value the publisher itself assigned.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import urllib.parse
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from refspec.registry.infrastructure.source_controlled_resource import (
    ResourceUse,
    SourceControlledResourceBundle,
    build_source_controlled_resource_bundle,
)
from refspec.storage import canonical_json

LCSH_SUBJECTS_SCHEME_IRI = "http://id.loc.gov/authorities/subjects"
LCSH_AUTHORITIES_PAGE_URL = "https://id.loc.gov/authorities/subjects.html"
LCSH_TOPICAL_MADS_NDJSON_URL = "https://id.loc.gov/download/authorities/subjects.madsrdf.jsonld.gz"
LCSH_EXPECTED_CONTEXT_URL = "http://id.loc.gov/authorities/subjects/context.json"

# The JSON-LD terms this reader recognizes, kept exactly as LOC publishes
# them (compacted, using the record's own context). This is not a general
# JSON-LD expander: a differently bound context would be refused, not
# silently reinterpreted.
_AUTHORITY_TYPE_TERM = "madsrdf:Authority"
_TOPIC_TYPE_TERM = "madsrdf:Topic"
_LCCN_FIELD = "identifiers:lccn"
_AUTHORITATIVE_LABEL_FIELD = "madsrdf:authoritativeLabel"
_BROADER_FIELD = "madsrdf:hasBroaderAuthority"
_VARIANT_FIELD = "madsrdf:hasVariant"
_VARIANT_LABEL_FIELD = "madsrdf:variantLabel"

LCSH_LCCN_IDENTIFIER_KIND = "publisherLccn"
LCSH_CONCEPT_URI_IDENTIFIER_KIND = "publisherConceptUri"
LCSH_TOPICAL_ELIGIBLE_USES: tuple[ResourceUse, ...] = ("searchExpansion",)

# A real sample captured 2026-08-03 via a bounded byte-range read of the URL
# above (never the whole 140+ MB distribution). These six lines are
# byte-exact excerpts of that response: three madsrdf:Topic authority
# records plus three non-Topic authority records used to exercise the
# topical filter. Pinning catches an accidental fixture edit that would
# silently stop testing real source bytes.
LCSH_TOPICAL_MINI_FIXTURE_SHA256 = "sha256:42b4ef9de8b905de05015c5154b5182307c7ed3b21b6058231c11e09ced0391f"
LCSH_TOPICAL_MINI_FIXTURE_BYTE_LENGTH = 21599


class LcshTopicalError(ValueError):
    """An LCSH ndjson line or subset capture cannot be preserved without guessing."""


def _sha256(payload: bytes) -> str:
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _require_absolute_iri(value: object, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise LcshTopicalError(f"{label} must be a non-empty string")
    parsed = urllib.parse.urlsplit(value)
    if not parsed.scheme or not parsed.netloc:
        raise LcshTopicalError(f"{label} must be an absolute IRI, got {value!r}")
    return value


def _term_set(value: object, *, label: str) -> frozenset[str]:
    if value is None:
        return frozenset()
    if isinstance(value, str):
        return frozenset({value})
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        return frozenset(value)
    raise LcshTopicalError(f"{label} @type must be a string or array of strings")


def _as_ref_list(value: object, *, label: str) -> tuple[Mapping[str, Any], ...]:
    if value is None:
        return ()
    if isinstance(value, Mapping):
        return (value,)
    if isinstance(value, list):
        if not all(isinstance(item, Mapping) for item in value):
            raise LcshTopicalError(f"{label} must contain only JSON-LD references")
        return tuple(value)
    raise LcshTopicalError(f"{label} must be a JSON-LD reference or an array of references")


@dataclass(frozen=True, slots=True)
class LcshTopicalLabel:
    """One MADS label with its required language tag."""

    value: str
    language: str


def _require_label(value: object, *, label: str) -> LcshTopicalLabel:
    if not isinstance(value, Mapping):
        raise LcshTopicalError(f"{label} must be an object")
    text = value.get("@value")
    language = value.get("@language")
    if not isinstance(text, str) or not text:
        raise LcshTopicalError(f"{label} must have a non-empty @value")
    if not isinstance(language, str) or not language:
        raise LcshTopicalError(f"{label} is missing a language tag")
    return LcshTopicalLabel(value=text, language=language)


@dataclass(frozen=True, slots=True)
class LcshTopicalRecord:
    """One retained madsrdf:Topic authority, with its exact source line."""

    concept_iri: str
    lccn: str
    preferred_label: LcshTopicalLabel
    variant_labels: tuple[LcshTopicalLabel, ...]
    broader_iris: tuple[str, ...]
    source_url: str
    line_number: int
    raw_line: bytes

    @property
    def source_sha256(self) -> str:
        """The pinned digest of this record's exact ndjson line."""

        return _sha256(self.raw_line)

    @property
    def source_byte_length(self) -> int:
        return len(self.raw_line)


def parse_lcsh_topical_ndjson_line(
    line: bytes,
    *,
    source_url: str,
    line_number: int,
) -> LcshTopicalRecord | None:
    """Parse one ndjson line; return None for a non-topical or blank line.

    Only the exact input bytes are retained as source evidence: a trailing
    newline (the ndjson line separator, not JSON-LD content) is stripped
    before pinning, everything else is kept byte-for-byte.
    """

    if not isinstance(line, bytes):
        raise LcshTopicalError("an ndjson line must be bytes")
    raw = line.rstrip(b"\r\n")
    if not raw.strip():
        return None
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as error:
        raise LcshTopicalError(f"line {line_number} is not valid UTF-8 at byte {error.start}") from error
    try:
        document = json.loads(text)
    except json.JSONDecodeError as error:
        raise LcshTopicalError(f"line {line_number} is not valid JSON: {error}") from error
    if not isinstance(document, dict):
        raise LcshTopicalError(f"line {line_number} must decode to a JSON object")
    if document.get("@context") != LCSH_EXPECTED_CONTEXT_URL:
        raise LcshTopicalError(f"line {line_number} does not use the expected @context {LCSH_EXPECTED_CONTEXT_URL!r}")
    graph = document.get("@graph")
    if not isinstance(graph, list) or not graph:
        raise LcshTopicalError(f"line {line_number} lacks a non-empty @graph array")

    by_id: dict[str, Mapping[str, Any]] = {}
    for node in graph:
        if not isinstance(node, Mapping):
            raise LcshTopicalError(f"line {line_number} contains a non-object @graph node")
        node_id = node.get("@id")
        if not isinstance(node_id, str) or not node_id:
            raise LcshTopicalError(f"line {line_number} contains a @graph node without an @id")
        if node_id in by_id:
            raise LcshTopicalError(f"line {line_number} repeats @graph node @id {node_id!r}")
        by_id[node_id] = node

    authorities = [
        node for node in graph if _AUTHORITY_TYPE_TERM in _term_set(node.get("@type"), label=f"line {line_number} node")
    ]
    if len(authorities) != 1:
        raise LcshTopicalError(
            f"line {line_number} must contain exactly one {_AUTHORITY_TYPE_TERM} node, found {len(authorities)}"
        )
    authority = authorities[0]
    types = _term_set(authority.get("@type"), label=f"line {line_number} authority")
    if _TOPIC_TYPE_TERM not in types:
        return None

    concept_iri = _require_absolute_iri(authority.get("@id"), f"line {line_number} authority @id")
    lccn = authority.get(_LCCN_FIELD)
    if not isinstance(lccn, str) or not lccn.strip():
        raise LcshTopicalError(f"{concept_iri} lacks a non-empty {_LCCN_FIELD}")

    preferred_label = _require_label(
        authority.get(_AUTHORITATIVE_LABEL_FIELD),
        label=f"{concept_iri} {_AUTHORITATIVE_LABEL_FIELD}",
    )

    broader_iris = tuple(
        sorted(
            {
                _require_absolute_iri(ref.get("@id"), f"{concept_iri} {_BROADER_FIELD} target")
                for ref in _as_ref_list(authority.get(_BROADER_FIELD), label=f"{concept_iri} {_BROADER_FIELD}")
            }
        )
    )

    variant_labels: list[LcshTopicalLabel] = []
    for ref in _as_ref_list(authority.get(_VARIANT_FIELD), label=f"{concept_iri} {_VARIANT_FIELD}"):
        variant_id = ref.get("@id")
        if not isinstance(variant_id, str) or variant_id not in by_id:
            raise LcshTopicalError(f"{concept_iri} {_VARIANT_FIELD} references an @id absent from @graph")
        variant_node = by_id[variant_id]
        variant_labels.append(
            _require_label(
                variant_node.get(_VARIANT_LABEL_FIELD),
                label=f"{concept_iri} variant {variant_id}",
            )
        )
    deduplicated_variants = tuple(sorted(set(variant_labels), key=lambda item: (item.language, item.value)))
    if len(deduplicated_variants) != len(variant_labels):
        raise LcshTopicalError(f"{concept_iri} repeats an identical variant label")

    return LcshTopicalRecord(
        concept_iri=concept_iri,
        lccn=lccn,
        preferred_label=preferred_label,
        variant_labels=deduplicated_variants,
        broader_iris=broader_iris,
        source_url=source_url,
        line_number=line_number,
        raw_line=raw,
    )


@dataclass(frozen=True, slots=True)
class LcshTopicalSubsetCapture:
    """A bounded topical pull plus the exact line accounting behind it."""

    source_url: str
    lines_scanned: int
    records: tuple[LcshTopicalRecord, ...]

    @property
    def excluded_count(self) -> int:
        """Lines that were read and parsed but were not a topical heading."""

        return self.lines_scanned - len(self.records)


def capture_lcsh_topical_subset(
    lines: Iterable[bytes],
    *,
    source_url: str,
    max_records: int | None = None,
) -> LcshTopicalSubsetCapture:
    """Stream an ndjson source once, retaining only topical headings.

    Iteration stops as soon as ``max_records`` topical headings are
    retained, so a bounded subset can be drawn from the full authority file
    without reading it to completion; lines after the bound are never
    fetched from ``lines``.
    """

    if max_records is not None and max_records <= 0:
        raise LcshTopicalError("max_records must be positive when supplied")
    records: list[LcshTopicalRecord] = []
    seen: set[str] = set()
    lines_scanned = 0
    for line_number, line in enumerate(lines, start=1):
        if max_records is not None and len(records) >= max_records:
            break
        lines_scanned = line_number
        record = parse_lcsh_topical_ndjson_line(line, source_url=source_url, line_number=line_number)
        if record is None:
            continue
        if record.concept_iri in seen:
            raise LcshTopicalError(
                f"line {line_number} repeats concept {record.concept_iri!r} already seen on this stream"
            )
        seen.add(record.concept_iri)
        records.append(record)
    return LcshTopicalSubsetCapture(source_url=source_url, lines_scanned=lines_scanned, records=tuple(records))


def capture_lcsh_topical_subset_from_gzip_path(
    path: Path,
    *,
    source_url: str,
    max_records: int | None = None,
) -> LcshTopicalSubsetCapture:
    """Stream a local gzip ndjson file without loading it into memory at once.

    ``gzip.open`` decompresses and yields one line at a time; combined with
    ``max_records`` this never materializes the full authority file.
    """

    source_path = Path(path)
    if source_path.is_symlink() or not source_path.is_file():
        raise LcshTopicalError(f"LCSH ndjson source is not a regular file: {source_path}")
    with gzip.open(source_path, "rb") as handle:
        return capture_lcsh_topical_subset(handle, source_url=source_url, max_records=max_records)


def open_pinned_lcsh_topical_mini_fixture(path: Path) -> bytes:
    """Open and verify the exact bytes of the pinned real LCSH topical fixture."""

    source = Path(path)
    if source.is_symlink() or not source.is_file():
        raise LcshTopicalError(f"LCSH topical fixture is not a regular file: {source}")
    payload = source.read_bytes()
    if len(payload) != LCSH_TOPICAL_MINI_FIXTURE_BYTE_LENGTH:
        raise LcshTopicalError("LCSH topical mini fixture byte length does not match the pinned real capture")
    if _sha256(payload) != LCSH_TOPICAL_MINI_FIXTURE_SHA256:
        raise LcshTopicalError("LCSH topical mini fixture digest does not match the pinned real capture")
    return payload


def _observation_id(*, resource_id: str, record: LcshTopicalRecord) -> str:
    identity = {
        "resourceId": resource_id,
        "conceptIri": record.concept_iri,
        "lccn": record.lccn,
        "sourceUrl": record.source_url,
    }
    digest = hashlib.sha256(canonical_json(identity).encode("utf-8")).hexdigest()
    return f"urn:ref:source-observation:{resource_id}:{digest}"


def build_lcsh_topical_snapshot(
    records: Sequence[LcshTopicalRecord],
    *,
    resource_id: str,
    title: str,
    captured_at: str,
    source_observed_count: int,
    gaps: Sequence[Mapping[str, str]] = (),
) -> SourceControlledResourceBundle:
    """Package a bounded LCSH topical subset as mapping-only source evidence.

    The catalog marks LCSH mapping only, so ``candidate_use_authorized`` is
    always False here and no observation ever claims concept identity; the
    publisher's LCCN and concept IRI are preserved as identifiers, not
    promoted into a RefSpec concept scheme.
    """

    if not records:
        raise LcshTopicalError("an LCSH topical snapshot must retain at least one record")
    source_url = records[0].source_url
    if any(record.source_url != source_url for record in records):
        raise LcshTopicalError("every record in one snapshot must share the same source_url")
    excluded_count = source_observed_count - len(records)
    if excluded_count < 0:
        raise LcshTopicalError("source_observed_count must account for every retained record")

    source_artifacts: dict[str, bytes] = {}
    observations: list[dict[str, Any]] = []
    seen_iris: set[str] = set()
    for record in sorted(records, key=lambda item: item.concept_iri):
        if record.concept_iri in seen_iris:
            raise LcshTopicalError(f"snapshot repeats concept {record.concept_iri!r}")
        seen_iris.add(record.concept_iri)
        source_artifacts[record.concept_iri] = record.raw_line
        digest = record.source_sha256
        source_path = f"line[{record.line_number}]"
        labels = [
            {
                "value": record.preferred_label.value,
                "language": record.preferred_label.language,
                "role": "preferred",
            },
            *(
                {"value": variant.value, "language": variant.language, "role": "alternate"}
                for variant in record.variant_labels
            ),
        ]
        identifiers = [
            {
                "value": record.lccn,
                "kind": LCSH_LCCN_IDENTIFIER_KIND,
                "authorityUri": LCSH_SUBJECTS_SCHEME_IRI,
                "sourceUri": record.source_url,
                "sourcePath": f"{source_path}.{_LCCN_FIELD}",
                "observedAt": captured_at,
                "sourceDigest": digest,
            },
            {
                "value": record.concept_iri,
                "kind": LCSH_CONCEPT_URI_IDENTIFIER_KIND,
                "authorityUri": LCSH_SUBJECTS_SCHEME_IRI,
                "sourceUri": record.source_url,
                "sourcePath": f"{source_path}.@id",
                "observedAt": captured_at,
                "sourceDigest": digest,
            },
        ]
        observations.append(
            {
                "id": _observation_id(resource_id=resource_id, record=record),
                "sourceArtifact": record.concept_iri,
                "sourcePath": source_path,
                "sourceOrdinal": record.line_number,
                "labels": labels,
                "identifiers": identifiers,
                "eligibleUses": list(LCSH_TOPICAL_ELIGIBLE_USES),
                "conceptIdentityClaimed": False,
            }
        )

    return build_source_controlled_resource_bundle(
        resource_id=resource_id,
        title=title,
        resource_kind="sourceTermSnapshot",
        identity_status="publisherIdentifiersPreserved",
        uses=LCSH_TOPICAL_ELIGIBLE_USES,
        captured_at=captured_at,
        candidate_use_authorized=False,
        observations=observations,
        source_artifacts=source_artifacts,
        source_observed_count=source_observed_count,
        excluded_count=excluded_count,
        gaps=gaps,
    )


__all__ = [
    "LCSH_AUTHORITIES_PAGE_URL",
    "LCSH_CONCEPT_URI_IDENTIFIER_KIND",
    "LCSH_EXPECTED_CONTEXT_URL",
    "LCSH_LCCN_IDENTIFIER_KIND",
    "LCSH_SUBJECTS_SCHEME_IRI",
    "LCSH_TOPICAL_ELIGIBLE_USES",
    "LCSH_TOPICAL_MADS_NDJSON_URL",
    "LCSH_TOPICAL_MINI_FIXTURE_BYTE_LENGTH",
    "LCSH_TOPICAL_MINI_FIXTURE_SHA256",
    "LcshTopicalError",
    "LcshTopicalLabel",
    "LcshTopicalRecord",
    "LcshTopicalSubsetCapture",
    "build_lcsh_topical_snapshot",
    "capture_lcsh_topical_subset",
    "capture_lcsh_topical_subset_from_gzip_path",
    "open_pinned_lcsh_topical_mini_fixture",
    "parse_lcsh_topical_ndjson_line",
]
