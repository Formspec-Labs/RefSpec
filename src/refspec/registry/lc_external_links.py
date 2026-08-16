"""Pinned streaming reader for Library of Congress external authority links.

The Library of Congress (LC) publishes one rolling N-Triples ZIP containing
links from its authority records to external vocabularies.  This reader keeps
only assertions whose subject is an LCSH authority, preserves the publisher's
MADS/RDF predicate and direction, and captures target labels.  LC omits the
language tag on those labels, so the reader retains that absence and assigns a
language through the frozen authority and script rules below.

The download URL is not versioned.  The exact retrieved bytes are therefore
the release identity: URL, retrieval timestamp, SHA-256 digest, and byte length
are all pinned below.  Importing this module never opens a network connection.
"""

from __future__ import annotations

import hashlib
import re
import zipfile
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType

LC_EXTERNAL_LINKS_URL = "https://id.loc.gov/download/externallinks.nt.zip"
LC_EXTERNAL_LINKS_FILENAME = "lcsh-externallinks-2026-08-15.nt.zip"
LC_EXTERNAL_LINKS_MEMBER = "external_links.nt"
LC_EXTERNAL_LINKS_SHA256 = "sha256:7d279d69c6920b41a579634a84a1b31ff73af764345fe51df3f7c480efeba9d1"
LC_EXTERNAL_LINKS_BYTE_LENGTH = 239_565_667
LC_EXTERNAL_LINKS_RETRIEVED_AT = "2026-08-15T22:49:53Z"
LC_EXTERNAL_LINKS_UNCOMPRESSED_BYTE_LENGTH = 1_855_295_301

LC_RIGHTS_STATEMENT = "These works are also available for worldwide use and reuse under CC0 1.0 Universal."
LC_RIGHTS_STATEMENT_URL = "https://www.loc.gov/legal/security-copyright-and-privacy/understanding-copyright/"
LC_LICENSE = "CC0 1.0 Universal"
LC_LICENSE_URL = "https://creativecommons.org/publicdomain/zero/1.0/"

MADS_NAMESPACE = "http://www.loc.gov/mads/rdf/v1#"
MADS_AUTHORITATIVE_LABEL = MADS_NAMESPACE + "authoritativeLabel"
MADS_CLOSE_EXTERNAL_AUTHORITY = MADS_NAMESPACE + "hasCloseExternalAuthority"
MADS_EXACT_EXTERNAL_AUTHORITY = MADS_NAMESPACE + "hasExactExternalAuthority"
MADS_BROADER_EXTERNAL_AUTHORITY = MADS_NAMESPACE + "hasBroaderExternalAuthority"
MADS_NARROWER_EXTERNAL_AUTHORITY = MADS_NAMESPACE + "hasNarrowerExternalAuthority"
LCSH_SUBJECT_PREFIX = "http://id.loc.gov/authorities/subjects/"

SUPPORTED_PUBLISHER_PREDICATES = frozenset(
    {
        MADS_CLOSE_EXTERNAL_AUTHORITY,
        MADS_EXACT_EXTERNAL_AUTHORITY,
        MADS_BROADER_EXTERNAL_AUTHORITY,
        MADS_NARROWER_EXTERNAL_AUTHORITY,
    }
)

TARGET_VOCABULARY_PREFIXES = MappingProxyType(
    {
        "agrovoc": ("http://aims.fao.org/aos/agrovoc/",),
        "getty-aat": ("http://vocab.getty.edu/aat/",),
        "getty-ulan": ("http://vocab.getty.edu/ulan/",),
        "bncf": ("http://purl.org/bncf/tid/",),
        "bne": ("http://datos.bne.es/resource/",),
        "fast": ("http://id.worldcat.org/fast/",),
        "gnd": ("https://d-nb.info/gnd/",),
        "homosaurus": ("https://homosaurus.org/v3/",),
        "nalt": ("https://lod.nal.usda.gov/nalt/",),
        "ndl-names": (
            "http://id.ndl.go.jp/auth/ndlna/",
            "https://id.ndl.go.jp/auth/ndlna/",
        ),
        "ndl-subjects": (
            "http://id.ndl.go.jp/auth/ndlsh/",
            "https://id.ndl.go.jp/auth/ndlsh/",
        ),
        "periodo-lcsh-periods": ("http://n2t.net/ark:/99152/p06c6g3",),
        "rameau": ("http://data.bnf.fr/ark:/12148/",),
        "wikidata": ("http://www.wikidata.org/entity/",),
        "yso": ("http://www.yso.fi/onto/yso/",),
    }
)

# LC's ``external_links.nt`` omits every target-label language tag.  These
# rules are release policy, not row-level guesses.  A fixed authority language
# wins because it records the target publisher's file convention.  The
# script/character fallback is only for a future declared authority without a
# fixed convention; the current pinned archive does not need it.
TARGET_LABEL_LANGUAGE_RULES = MappingProxyType(
    {
        "agrovoc": ("en", "authorityConvention:agrovoc-lc-links-use-English-labels"),
        "getty-aat": ("en", "authorityConvention:getty-aat-publisher-file-is-English"),
        "getty-ulan": ("en", "authorityConvention:getty-ulan-publisher-file-is-English"),
        "bncf": ("it", "authorityConvention:bncf-authoritative-labels-are-Italian"),
        "bne": ("es", "authorityConvention:bne-authoritative-labels-are-Spanish"),
        "fast": ("en", "authorityConvention:fast-topical-labels-are-English"),
        "gnd": ("de", "authorityConvention:gnd-authoritative-labels-are-German"),
        "homosaurus": ("en", "authorityConvention:homosaurus-v3-base-labels-are-English"),
        "nalt": ("en", "authorityConvention:nalt-lc-links-use-English-labels"),
        "ndl-names": ("ja", "authorityConvention:ndl-names-authoritative-labels-are-Japanese"),
        "ndl-subjects": ("ja", "authorityConvention:ndl-subjects-authoritative-labels-are-Japanese"),
        "periodo-lcsh-periods": ("en", "sourceConvention:periodo-lcsh-period-labels-are-English"),
        "rameau": ("fr", "authorityConvention:bnf-rameau-authoritative-labels-are-French"),
        "wikidata": ("en", "sourceConvention:lc-external-links-selects-English-wikidata-labels"),
        "yso": ("fi", "sourceConvention:lc-external-links-selects-Finnish-yso-labels"),
    }
)

EXPECTED_ASSERTION_COUNTS_BY_VOCABULARY = MappingProxyType(
    {
        "agrovoc": 1_105,
        "getty-aat": 933,
        "getty-ulan": 125,
        "bncf": 18_180,
        "bne": 43_310,
        "fast": 535_372,
        "gnd": 45_202,
        "homosaurus": 600,
        "nalt": 15_753,
        "ndl-names": 21,
        "ndl-subjects": 14_563,
        "periodo-lcsh-periods": 1_478,
        "rameau": 87_015,
        "wikidata": 23_324,
        "yso": 15_611,
    }
)
EXPECTED_ASSERTION_COUNTS_BY_PUBLISHER_PREDICATE = MappingProxyType(
    {
        MADS_BROADER_EXTERNAL_AUTHORITY: 182_767,
        MADS_CLOSE_EXTERNAL_AUTHORITY: 607_059,
        MADS_EXACT_EXTERNAL_AUTHORITY: 12_554,
        MADS_NARROWER_EXTERNAL_AUTHORITY: 212,
    }
)
EXPECTED_ASSERTION_COUNT = 802_592
EXPECTED_UNIQUE_LCSH_SUBJECT_COUNT = 362_148
EXPECTED_DETERMINED_LANGUAGE_LABEL_COUNTS = MappingProxyType(
    {
        "de": 42_725,
        "en": 577_287,
        "es": 42_609,
        "fi": 14_626,
        "fr": 83_379,
        "it": 17_490,
        "ja": 14_050,
    }
)
EXPECTED_DETERMINED_LANGUAGE_TARGET_COUNTS = MappingProxyType(
    {
        "de": 42_725,
        "en": 577_255,
        "es": 42_609,
        "fi": 14_626,
        "fr": 83_379,
        "it": 17_490,
        "ja": 14_050,
    }
)

_IRI_TRIPLE = re.compile(rb"^<([^>]*)>\s+<([^>]*)>\s+<([^>]*)>\s+\.\s*$")
_LITERAL_TRIPLE = re.compile(
    rb'^<([^>]*)>\s+<([^>]*)>\s+"((?:[^"\\]|\\.)*)"'
    rb"(?:@([A-Za-z]+(?:-[A-Za-z0-9]+)*)|\^\^<([^>]*)>)?\s+\.\s*$"
)
_NT_ESCAPES = {"\\": "\\", '"': '"', "n": "\n", "r": "\r", "t": "\t"}
_JAPANESE_KANA = re.compile(r"[\u3040-\u30ff]")
_PLAUSIBLY_ENGLISH_ASCII = re.compile(r"[A-Za-z]")
_LATIN_SCRIPT = re.compile(r"[A-Za-z\u00c0-\u024f]")
_CHUNK_BYTES = 1 << 20


class LcExternalLinksError(ValueError):
    """The pinned LC external-links artifact cannot be preserved exactly."""


@dataclass(frozen=True, slots=True)
class LcExternalLinkAssertion:
    """One LC-authored LCSH-to-external assertion in its published direction."""

    subject_iri: str
    predicate_iri: str
    object_iri: str
    target_vocabulary: str
    line_number: int
    native_statement: str
    statement_sha256: str


@dataclass(frozen=True, slots=True)
class LcExternalEndpointLabel:
    """One target label with both publisher and RefSpec language facts."""

    endpoint_iri: str
    value: str
    language: str | None
    datatype_iri: str | None
    line_number: int
    native_statement: str
    statement_sha256: str
    determined_language: str | None
    language_determined_by: str | None


@dataclass(frozen=True, slots=True)
class LcExternalLinksCapture:
    """The selected LCSH assertions and target-label evidence from one ZIP."""

    source_url: str
    source_sha256: str
    source_byte_length: int
    retrieved_at: str
    archive_member: str
    assertions: Sequence[LcExternalLinkAssertion]
    endpoint_labels: Mapping[str, Sequence[LcExternalEndpointLabel]]

    @property
    def lcsh_subject_iris(self) -> frozenset[str]:
        return frozenset(row.subject_iri for row in self.assertions)

    @property
    def target_iris(self) -> frozenset[str]:
        return frozenset(row.object_iri for row in self.assertions)

    @property
    def assertion_counts_by_vocabulary(self) -> dict[str, int]:
        return dict(sorted(Counter(row.target_vocabulary for row in self.assertions).items()))

    @property
    def assertion_counts_by_publisher_predicate(self) -> dict[str, int]:
        return dict(sorted(Counter(row.predicate_iri for row in self.assertions).items()))

    @property
    def target_counts_by_vocabulary(self) -> dict[str, int]:
        targets: dict[str, set[str]] = {}
        for row in self.assertions:
            targets.setdefault(row.target_vocabulary, set()).add(row.object_iri)
        return {key: len(values) for key, values in sorted(targets.items())}

    @property
    def unlabeled_target_count(self) -> int:
        return len(self.target_iris - self.endpoint_labels.keys())

    @property
    def explicitly_english_target_count(self) -> int:
        return sum(any(label.language == "en" for label in labels) for labels in self.endpoint_labels.values())

    @property
    def determined_language_label_counts(self) -> dict[str, int]:
        return dict(
            sorted(
                Counter(
                    label.determined_language
                    for labels in self.endpoint_labels.values()
                    for label in labels
                    if label.determined_language is not None
                ).items()
            )
        )

    @property
    def determined_language_target_counts(self) -> dict[str, int]:
        counts: Counter[str] = Counter()
        for labels in self.endpoint_labels.values():
            languages = {label.determined_language for label in labels if label.determined_language is not None}
            for language in languages:
                counts[language] += 1
        return dict(sorted(counts.items()))

    @property
    def indeterminate_label_count(self) -> int:
        return sum(
            label.determined_language is None
            for labels in self.endpoint_labels.values()
            for label in labels
        )


def _sha256(payload: bytes) -> str:
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _unescape_literal(value: bytes, *, line_number: int) -> str:
    try:
        escaped = value.decode("ascii")
    except UnicodeDecodeError as error:
        raise LcExternalLinksError(
            f"LC external-links line {line_number} contains raw non-ASCII literal bytes"
        ) from error
    output: list[str] = []
    index = 0
    while index < len(escaped):
        character = escaped[index]
        if character != "\\":
            output.append(character)
            index += 1
            continue
        if index + 1 >= len(escaped):
            raise LcExternalLinksError(f"LC external-links line {line_number} ends in a literal escape")
        marker = escaped[index + 1]
        if marker in _NT_ESCAPES:
            output.append(_NT_ESCAPES[marker])
            index += 2
            continue
        if marker in {"u", "U"}:
            width = 4 if marker == "u" else 8
            digits = escaped[index + 2 : index + 2 + width]
            if len(digits) != width or not all(character in "0123456789abcdefABCDEF" for character in digits):
                raise LcExternalLinksError(f"LC external-links line {line_number} has a malformed Unicode escape")
            try:
                output.append(chr(int(digits, 16)))
            except ValueError as error:
                raise LcExternalLinksError(
                    f"LC external-links line {line_number} has an invalid Unicode code point"
                ) from error
            index += 2 + width
            continue
        raise LcExternalLinksError(f"LC external-links line {line_number} has unsupported escape \\{marker}")
    return "".join(output)


def _target_vocabulary(object_iri: str) -> str:
    matches = [key for key, prefixes in TARGET_VOCABULARY_PREFIXES.items() if object_iri.startswith(prefixes)]
    if len(matches) != 1:
        raise LcExternalLinksError(
            f"LCSH external-link target does not belong to one declared vocabulary: {object_iri}"
        )
    return matches[0]


def determine_endpoint_label_language(
    *,
    value: str,
    target_vocabulary: str,
    publisher_language_tag: str | None,
) -> tuple[str | None, str | None]:
    """Return the deterministic label language and the rule that established it."""

    if publisher_language_tag is not None:
        return publisher_language_tag.lower(), "publisherLanguageTag"
    authority_rule = TARGET_LABEL_LANGUAGE_RULES.get(target_vocabulary)
    if authority_rule is not None:
        return authority_rule
    if _JAPANESE_KANA.search(value) and _LATIN_SCRIPT.search(value) is None:
        return "ja", "scriptRule:hiragana-or-katakana-without-Latin"
    if value.isascii() and _PLAUSIBLY_ENGLISH_ASCII.search(value):
        return "en", "fallbackRule:ASCII-with-Latin-letters-plausibly-English"
    return None, None


def _scan_assertions(lines: Iterable[bytes]) -> tuple[LcExternalLinkAssertion, ...]:
    assertions: list[LcExternalLinkAssertion] = []
    claims: set[tuple[str, str, str]] = set()
    subject_prefix = ("<" + LCSH_SUBJECT_PREFIX).encode("ascii")
    for line_number, line in enumerate(lines, start=1):
        if not isinstance(line, bytes):
            raise TypeError("LC external-links statements must be bytes")
        if not line.startswith(subject_prefix):
            continue
        match = _IRI_TRIPLE.fullmatch(line)
        if match is None:
            continue
        try:
            subject_iri, predicate_iri, object_iri = (value.decode("ascii") for value in match.groups())
        except UnicodeDecodeError as error:
            raise LcExternalLinksError(f"LC external-links line {line_number} contains a non-ASCII IRI") from error
        if predicate_iri not in SUPPORTED_PUBLISHER_PREDICATES:
            if predicate_iri.startswith(MADS_NAMESPACE) and predicate_iri.endswith("ExternalAuthority"):
                raise LcExternalLinksError(
                    f"unsupported LCSH external-authority predicate on line {line_number}: {predicate_iri}"
                )
            continue
        claim = (subject_iri, predicate_iri, object_iri)
        if claim in claims:
            raise LcExternalLinksError(
                f"LC external-links repeats an LCSH mapping claim on line {line_number}: {claim!r}"
            )
        claims.add(claim)
        native_statement_bytes = line.rstrip(b"\r\n")
        try:
            native_statement = native_statement_bytes.decode("ascii")
        except UnicodeDecodeError as error:  # pragma: no cover - IRIs above already prove ASCII
            raise LcExternalLinksError(f"LC external-links line {line_number} is not ASCII N-Triples") from error
        assertions.append(
            LcExternalLinkAssertion(
                subject_iri=subject_iri,
                predicate_iri=predicate_iri,
                object_iri=object_iri,
                target_vocabulary=_target_vocabulary(object_iri),
                line_number=line_number,
                native_statement=native_statement,
                statement_sha256=_sha256(native_statement_bytes),
            )
        )
    return tuple(assertions)


def _scan_endpoint_labels(
    lines: Iterable[bytes],
    *,
    target_vocabularies: Mapping[str, str],
) -> Mapping[str, tuple[LcExternalEndpointLabel, ...]]:
    target_bytes = {value.encode("ascii") for value in target_vocabularies}
    labels: dict[str, list[LcExternalEndpointLabel]] = {}
    seen: set[tuple[str, str, str | None, str | None]] = set()
    for line_number, line in enumerate(lines, start=1):
        if not isinstance(line, bytes):
            raise TypeError("LC external-links statements must be bytes")
        if not line.startswith(b"<"):
            continue
        subject_end = line.find(b">")
        if subject_end < 2 or line[1:subject_end] not in target_bytes:
            continue
        match = _LITERAL_TRIPLE.fullmatch(line)
        if match is None:
            continue
        subject_raw, predicate_raw, value_raw, language_raw, datatype_raw = match.groups()
        if predicate_raw != MADS_AUTHORITATIVE_LABEL.encode("ascii"):
            continue
        endpoint_iri = subject_raw.decode("ascii")
        language = None if language_raw is None else language_raw.decode("ascii").lower()
        datatype_iri = None if datatype_raw is None else datatype_raw.decode("ascii")
        value = _unescape_literal(value_raw, line_number=line_number)
        determined_language, language_determined_by = determine_endpoint_label_language(
            value=value,
            target_vocabulary=target_vocabularies[endpoint_iri],
            publisher_language_tag=language,
        )
        claim = (endpoint_iri, value, language, datatype_iri)
        if claim in seen:
            raise LcExternalLinksError(f"LC external-links repeats a target label on line {line_number}: {claim!r}")
        seen.add(claim)
        native_statement_bytes = line.rstrip(b"\r\n")
        label = LcExternalEndpointLabel(
            endpoint_iri=endpoint_iri,
            value=value,
            language=language,
            datatype_iri=datatype_iri,
            line_number=line_number,
            native_statement=native_statement_bytes.decode("ascii"),
            statement_sha256=_sha256(native_statement_bytes),
            determined_language=determined_language,
            language_determined_by=language_determined_by,
        )
        labels.setdefault(endpoint_iri, []).append(label)
    return MappingProxyType(
        {iri: tuple(sorted(values, key=lambda item: item.line_number)) for iri, values in sorted(labels.items())}
    )


def parse_lc_external_links_statements(
    lines: Sequence[bytes],
    *,
    source_url: str = LC_EXTERNAL_LINKS_URL,
    source_sha256: str | None = None,
    source_byte_length: int | None = None,
    retrieved_at: str = LC_EXTERNAL_LINKS_RETRIEVED_AT,
) -> LcExternalLinksCapture:
    """Parse reusable statement bytes for tests and bounded source excerpts."""

    assertions = _scan_assertions(lines)
    target_vocabularies = {row.object_iri: row.target_vocabulary for row in assertions}
    labels = _scan_endpoint_labels(
        lines,
        target_vocabularies=target_vocabularies,
    )
    payload = b"".join(lines)
    return LcExternalLinksCapture(
        source_url=source_url,
        source_sha256=_sha256(payload) if source_sha256 is None else source_sha256,
        source_byte_length=len(payload) if source_byte_length is None else source_byte_length,
        retrieved_at=retrieved_at,
        archive_member=LC_EXTERNAL_LINKS_MEMBER,
        assertions=assertions,
        endpoint_labels=labels,
    )


def _verify_archive(path: Path) -> None:
    source = Path(path)
    if source.is_symlink() or not source.is_file():
        raise LcExternalLinksError(f"LC external-links source is not a regular file: {source}")
    hasher = hashlib.sha256()
    observed_length = 0
    with source.open("rb") as handle:
        for chunk in iter(lambda: handle.read(_CHUNK_BYTES), b""):
            observed_length += len(chunk)
            hasher.update(chunk)
    observed_digest = "sha256:" + hasher.hexdigest()
    if observed_length != LC_EXTERNAL_LINKS_BYTE_LENGTH or observed_digest != LC_EXTERNAL_LINKS_SHA256:
        raise LcExternalLinksError(
            "LC external-links archive pin differs: "
            f"expected=({LC_EXTERNAL_LINKS_BYTE_LENGTH}, {LC_EXTERNAL_LINKS_SHA256}), "
            f"observed=({observed_length}, {observed_digest})"
        )


def load_lc_external_links_capture(path: Path) -> LcExternalLinksCapture:
    """Verify and stream the complete pinned rolling LC external-links ZIP."""

    source = Path(path)
    _verify_archive(source)
    try:
        with zipfile.ZipFile(source) as archive:
            members = archive.infolist()
            if len(members) != 1 or members[0].filename != LC_EXTERNAL_LINKS_MEMBER:
                raise LcExternalLinksError(
                    f"LC external-links ZIP member shape differs: {[item.filename for item in members]!r}"
                )
            if members[0].file_size != LC_EXTERNAL_LINKS_UNCOMPRESSED_BYTE_LENGTH:
                raise LcExternalLinksError(
                    "LC external-links uncompressed byte length differs: "
                    f"expected {LC_EXTERNAL_LINKS_UNCOMPRESSED_BYTE_LENGTH}, "
                    f"observed {members[0].file_size}"
                )
            with archive.open(LC_EXTERNAL_LINKS_MEMBER) as lines:
                assertions = _scan_assertions(lines)
            with archive.open(LC_EXTERNAL_LINKS_MEMBER) as lines:
                target_vocabularies = {row.object_iri: row.target_vocabulary for row in assertions}
                labels = _scan_endpoint_labels(
                    lines,
                    target_vocabularies=target_vocabularies,
                )
    except zipfile.BadZipFile as error:
        raise LcExternalLinksError(f"LC external-links source is not a valid ZIP: {source}") from error

    capture = LcExternalLinksCapture(
        source_url=LC_EXTERNAL_LINKS_URL,
        source_sha256=LC_EXTERNAL_LINKS_SHA256,
        source_byte_length=LC_EXTERNAL_LINKS_BYTE_LENGTH,
        retrieved_at=LC_EXTERNAL_LINKS_RETRIEVED_AT,
        archive_member=LC_EXTERNAL_LINKS_MEMBER,
        assertions=assertions,
        endpoint_labels=labels,
    )
    observed = {
        "assertionCount": len(capture.assertions),
        "assertionCountsByPublisherPredicate": (capture.assertion_counts_by_publisher_predicate),
        "assertionCountsByVocabulary": capture.assertion_counts_by_vocabulary,
        "determinedLanguageLabelCounts": capture.determined_language_label_counts,
        "determinedLanguageTargetCounts": capture.determined_language_target_counts,
        "indeterminateLabelCount": capture.indeterminate_label_count,
        "uniqueLcshSubjectCount": len(capture.lcsh_subject_iris),
    }
    expected = {
        "assertionCount": EXPECTED_ASSERTION_COUNT,
        "assertionCountsByPublisherPredicate": dict(EXPECTED_ASSERTION_COUNTS_BY_PUBLISHER_PREDICATE),
        "assertionCountsByVocabulary": dict(EXPECTED_ASSERTION_COUNTS_BY_VOCABULARY),
        "determinedLanguageLabelCounts": dict(EXPECTED_DETERMINED_LANGUAGE_LABEL_COUNTS),
        "determinedLanguageTargetCounts": dict(EXPECTED_DETERMINED_LANGUAGE_TARGET_COUNTS),
        "indeterminateLabelCount": 0,
        "uniqueLcshSubjectCount": EXPECTED_UNIQUE_LCSH_SUBJECT_COUNT,
    }
    if observed != expected:
        raise LcExternalLinksError(
            f"LC external-links measured shape differs: expected={expected!r}, observed={observed!r}"
        )
    return capture


__all__ = [
    "EXPECTED_ASSERTION_COUNT",
    "EXPECTED_ASSERTION_COUNTS_BY_PUBLISHER_PREDICATE",
    "EXPECTED_ASSERTION_COUNTS_BY_VOCABULARY",
    "EXPECTED_DETERMINED_LANGUAGE_LABEL_COUNTS",
    "EXPECTED_DETERMINED_LANGUAGE_TARGET_COUNTS",
    "EXPECTED_UNIQUE_LCSH_SUBJECT_COUNT",
    "LCSH_SUBJECT_PREFIX",
    "LC_EXTERNAL_LINKS_BYTE_LENGTH",
    "LC_EXTERNAL_LINKS_FILENAME",
    "LC_EXTERNAL_LINKS_MEMBER",
    "LC_EXTERNAL_LINKS_RETRIEVED_AT",
    "LC_EXTERNAL_LINKS_SHA256",
    "LC_EXTERNAL_LINKS_URL",
    "LC_LICENSE",
    "LC_LICENSE_URL",
    "LC_RIGHTS_STATEMENT",
    "LC_RIGHTS_STATEMENT_URL",
    "MADS_BROADER_EXTERNAL_AUTHORITY",
    "MADS_CLOSE_EXTERNAL_AUTHORITY",
    "MADS_EXACT_EXTERNAL_AUTHORITY",
    "MADS_NARROWER_EXTERNAL_AUTHORITY",
    "SUPPORTED_PUBLISHER_PREDICATES",
    "TARGET_LABEL_LANGUAGE_RULES",
    "TARGET_VOCABULARY_PREFIXES",
    "LcExternalEndpointLabel",
    "LcExternalLinkAssertion",
    "LcExternalLinksCapture",
    "LcExternalLinksError",
    "determine_endpoint_label_language",
    "load_lc_external_links_capture",
    "parse_lc_external_links_statements",
]
