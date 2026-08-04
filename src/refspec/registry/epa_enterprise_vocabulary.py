"""Source-faithful capture of one EPA Enterprise Vocabulary topic-tier export.

Source: EPA Enterprise Vocabulary, https://www.epa.gov/research/epa-enterprise-vocabulary.
That landing page states "EPA Enterprise Vocabulary v1 was released in April
2018" and describes browse/search access through EPA's Terminology Services
(System of Registries) application at ofmpub.epa.gov, which lets a visitor
"Export browse and search results in various formats (Excel, XML, PDF, RTF)".
There is no static, deep-linkable bulk distribution file: the exact XML shape
below was captured on 2026-08-03 from a real per-tier browse-and-export
request against tier 1005100 ("Regulatory Activities"), reached from
https://ofmpub.epa.gov/sor_internet/registry/termreg/searchandretrieve/
enterprisevocabulary/search.do?search=&tierTwoSelected=1005100&searchString= .

Catalog scope (binding): the 2026-07-28 catalog deferred pilot inclusion of
this source "until a current export, version record, maintenance evidence,
and license are verified" -- a deferral for unverified export/version/license,
not for the source being superseded. This module captures a real, verified
export instead of skipping it, and records what the 2026-08-03 research pass
could and could not verify as explicit, structured gaps rather than silently
resolving them. It authorizes no candidate or accepted-output use.

Source shape (verified, and materially different from SKOS/RDF): the export
XML is a proprietary <EnterpriseVocabularyReport> tree of <Row> elements, each
carrying a <Term> label, optional <Definitions>/<ScopeNote> free text, and an
optional <ChildTerms> holding nested <Row> children -- broader/narrower
structure is expressed purely by nesting position, not by any concept
identifier. The publisher supplies no stable term IRI, code, or URI anywhere
in this export; the browse UI's "openTerm"/"openRel" links re-resolve a term
by exact label text through search, not by identifier. Per house rule, this
module therefore never mints or infers a concept identity: every row keeps
only its positional source path, never an identifier.

Importing this module never opens a network connection. A caller must either
supply already-fetched bytes or inject a fetcher; direct network access
requires the caller to opt in explicitly.
"""

from __future__ import annotations

import dataclasses
import hashlib
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from refspec.storage import canonical_json

EPA_PUBLISHER = "U.S. Environmental Protection Agency"
EPA_LANDING_PAGE_URL = "https://www.epa.gov/research/epa-enterprise-vocabulary"
EPA_TERMINOLOGY_SERVICES_BASE_URL = (
    "https://ofmpub.epa.gov/sor_internet/registry/termreg/searchandretrieve/enterprisevocabulary/search.do"
)
# The only edition marker this research pass found anywhere in the source:
# the landing page's own prose. No changelog or v2 announcement was found.
EPA_EDITION_LABEL = "EPA Enterprise Vocabulary v1 (stated release: April 2018)"
EPA_NATIVE_FORMAT = "epaEnterpriseVocabularyXmlExport"

_ROOT_TAG = "EnterpriseVocabularyReport"
_ROW_TAG = "Row"
_TERM_TAG = "Term"
_DEFINITIONS_TAG = "Definitions"
_SCOPE_NOTE_TAG = "ScopeNote"
_CHILD_TERMS_TAG = "ChildTerms"
_ROW_ALLOWED_CHILD_TAGS = frozenset({_TERM_TAG, _DEFINITIONS_TAG, _SCOPE_NOTE_TAG, _CHILD_TERMS_TAG})

_DIGEST_PREFIX = "sha256:"


class EpaEnterpriseVocabularyError(ValueError):
    """An EPA Enterprise Vocabulary export cannot be preserved without guessing."""


# Verbatim framing of the catalog's decision for this source plus the
# revisit instruction that produced this module, kept exact so downstream
# readers see the same scope decision the catalog and the revisit recorded.
EPA_ENTERPRISE_VOCABULARY_CATALOG_ROLE = (
    "Specialist subject module candidate (Environment), alongside GEMET. The "
    "2026-07-28 catalog recorded: EPA reports more than 100 topic tiers and "
    "publishes several export formats; exact current concept count and "
    "update cadence remain unverified. Decision: Defer pilot inclusion until "
    "a current export, version record, maintenance evidence, and license "
    "are verified. This is a deferral for unverified export/version/license, "
    "not a finding that the source is superseded; this module captures a "
    "real, verified export and records the outstanding verification gaps "
    "instead of skipping the source."
)


@dataclass(frozen=True, slots=True)
class EpaVerificationGap:
    """One explicit, unresolved verification gap this research pass found."""

    kind: str
    finding: str


# Findings from the 2026-08-03 research pass against the live landing page
# and Terminology Services application. Each gap is recorded, not resolved;
# none of them is silently assumed favorable.
EPA_ENTERPRISE_VOCABULARY_VERIFICATION_GAPS: tuple[EpaVerificationGap, ...] = (
    EpaVerificationGap(
        kind="editionDate",
        finding=(
            "The landing page states only that 'EPA Enterprise Vocabulary v1 "
            "was released in April 2018'; no dated changelog, release notes, "
            "or v2 announcement was found, so whether term content has "
            "changed since 2018 is unverified."
        ),
    ),
    EpaVerificationGap(
        kind="license",
        finding=(
            "Neither the research landing page nor the Terminology Services "
            "(System of Registries) application publishes a content license "
            "or reuse terms for vocabulary term content. EPA's general site "
            "privacy/accessibility footer is not a content license."
        ),
    ),
    EpaVerificationGap(
        kind="maintenanceEvidence",
        finding=(
            "No changelog, release cadence, or update-frequency statement "
            "was found. The landing page's CMS 'Last updated' stamp reflects "
            "page content, not vocabulary content, and was not treated as "
            "maintenance evidence for the vocabulary itself."
        ),
    ),
    EpaVerificationGap(
        kind="exportDurability",
        finding=(
            "Excel/XML/PDF/RTF exports are generated per browse/search "
            "session through a jsessionid-scoped URL (observed 2026-08-03); "
            "no static, deep-linkable bulk distribution URL was found, so a "
            "captured export URL cannot be re-fetched verbatim later. A "
            "re-fetch must restart from the stable tier browse URL."
        ),
    ),
    EpaVerificationGap(
        kind="termIdentifiers",
        finding=(
            "No stable published term identifier or IRI was found anywhere "
            "in the source. The interactive browse table's internal row "
            "'uid' values are absent from the bulk export entirely and are "
            "not documented as persistent identifiers; the UI's own "
            "'openTerm'/'openRel' links re-resolve a term by exact label "
            "text through search, not by identifier."
        ),
    ),
    EpaVerificationGap(
        kind="nativeFormat",
        finding=(
            "The verified export is a proprietary <EnterpriseVocabularyReport> "
            "label tree (Term/Definitions/ScopeNote/ChildTerms), not native "
            "SKOS or RDF; no SKOS/RDF distribution was found for this source."
        ),
    ),
    EpaVerificationGap(
        kind="credentialGatedApi",
        finding=(
            "A 2026-08-04 follow-up found the channel that WOULD resolve the "
            "termIdentifiers and exportDurability gaps: EPA's SOR services "
            "catalog lists a 'Synaptica REST API' over the Knowledge "
            "Management System holding this vocabulary, publicly documented "
            "at https://etss.epa.gov/synaptica_rest_services/help (verified "
            "reachable without login) with GET vocabs/terms/children/topterms/"
            "uppaths endpoints returning XML with real term identifiers. "
            "Anonymous requests receive HTTP 401 and the catalog states "
            "'Authorization is required for use'; the etss.epa.gov "
            "application root itself redirects to EPA's Oracle Access "
            "Manager single sign-on. Promoting this source past a "
            "session-scoped label-tree capture is therefore an access "
            "request to EPA, not an engineering problem. data.gov and the "
            "Environmental Dataset Gateway carry no vocabulary release "
            "(verified absent 2026-08-04)."
        ),
    ),
    EpaVerificationGap(
        kind="noPublicMirror",
        finding=(
            "A 2026-08-04 mirror hunt (GitHub code search on the export's "
            "<EnterpriseVocabularyReport> root element and on "
            "'synaptica_rest_services', plus Wayback CDX over the "
            "Terminology Services paths) found no mirror of this vocabulary. "
            "The GitHub hits are one link-indexer repository that merely "
            "records a jsessionid-bearing export URL, and EPA's own open "
            "source applications, which call the Synaptica API with a "
            "GLOSSARY_AUTH basic-auth secret they do not publish "
            "(USEPA/mywaterway app/server/app/tasks/updateGlossary.js). One "
            "of those applications does republish what it fetched, at "
            "https://mywaterway.epa.gov/api/configFiles -> glossary: 135 "
            "term/definition pairs from a project vocabulary named 'HMW "
            "Glossary', with the publisher's identifiers, status and "
            "attribute structure stripped by that application's own "
            "transform. It is a different, much smaller vocabulary than the "
            "Enterprise Vocabulary and is second-hand, so it is not a "
            "substitute source. Wayback holds only navigation-page captures "
            "of the Terminology Services UI, no export payloads."
        ),
    ),
)


def _require_absolute_iri(value: str, label: str) -> str:
    parsed = urllib.parse.urlsplit(value)
    if not parsed.scheme:
        raise EpaEnterpriseVocabularyError(f"{label} must be an absolute IRI, got {value!r}")
    return value


def _validate_source_url(source_url: str) -> None:
    parsed = urllib.parse.urlsplit(source_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise EpaEnterpriseVocabularyError("source_url must be an absolute HTTP(S) URL")
    if parsed.username is not None or parsed.password is not None:
        raise EpaEnterpriseVocabularyError("source_url must not contain credentials")


def _expected_hex(expected_sha256: str) -> str:
    if not expected_sha256.startswith(_DIGEST_PREFIX) or len(expected_sha256) != len(_DIGEST_PREFIX) + 64:
        raise EpaEnterpriseVocabularyError("expected_sha256 must be a lowercase sha256:<64 hex> digest")
    hex_part = expected_sha256[len(_DIGEST_PREFIX) :]
    if any(character not in "0123456789abcdef" for character in hex_part):
        raise EpaEnterpriseVocabularyError("expected_sha256 must be a lowercase sha256:<64 hex> digest")
    return hex_part


def _source_payload(source: str | bytes) -> bytes:
    if isinstance(source, bytes):
        payload = source
    elif isinstance(source, str):
        payload = source.encode("utf-8")
    else:
        raise TypeError("source must be str or bytes")
    try:
        payload.decode("utf-8")
    except UnicodeDecodeError as error:
        raise EpaEnterpriseVocabularyError(
            f"EPA Enterprise Vocabulary export is not valid UTF-8 at byte {error.start}"
        ) from error
    return payload


def _format_path(path: tuple[int, ...]) -> str:
    return "/".join(f"Row[{index}]" for index in path)


@dataclass(frozen=True, slots=True)
class EpaTermRow:
    """One captured <Row>: its label plus whatever notes and children it carries.

    ``definitions_text``/``scope_note_text`` are ``None`` exactly when the
    element was absent from this payload (a browse without definitions was
    requested), and the source's own raw text -- possibly empty, possibly a
    lone non-breaking space -- when the element was present. Nothing here
    infers a meaning the source itself did not assert.
    """

    label: str
    source_path: str
    definitions_text: str | None
    scope_note_text: str | None
    child_terms: tuple[EpaTermRow, ...]

    def walk(self, *, depth: int = 0) -> tuple[tuple[int, EpaTermRow], ...]:
        rows: list[tuple[int, EpaTermRow]] = [(depth, self)]
        for child in self.child_terms:
            rows.extend(child.walk(depth=depth + 1))
        return tuple(rows)


def _non_blank(value: str | None) -> bool:
    return value is not None and value.strip() != ""


def _parse_row(element: ET.Element, *, path: tuple[int, ...]) -> EpaTermRow:
    location = _format_path(path)
    if element.tag != _ROW_TAG:
        raise EpaEnterpriseVocabularyError(f"{location} must be a <{_ROW_TAG}> element, got <{element.tag}>")
    if element.attrib:
        raise EpaEnterpriseVocabularyError(f"{location} must not carry attributes")

    children_by_tag: dict[str, list[ET.Element]] = {}
    for child in element:
        children_by_tag.setdefault(child.tag, []).append(child)
    unexpected_tags = set(children_by_tag) - _ROW_ALLOWED_CHILD_TAGS
    if unexpected_tags:
        raise EpaEnterpriseVocabularyError(f"{location} has unsupported child element(s): {sorted(unexpected_tags)}")
    for tag in _ROW_ALLOWED_CHILD_TAGS:
        if len(children_by_tag.get(tag, [])) > 1:
            raise EpaEnterpriseVocabularyError(f"{location} has more than one <{tag}> element")

    term_elements = children_by_tag.get(_TERM_TAG, [])
    if len(term_elements) != 1:
        raise EpaEnterpriseVocabularyError(f"{location} must contain exactly one <{_TERM_TAG}> element")
    term_element = term_elements[0]
    if term_element.attrib:
        raise EpaEnterpriseVocabularyError(f"{location} <{_TERM_TAG}> must not carry attributes")
    term_text = term_element.text or ""
    if not term_text.strip():
        raise EpaEnterpriseVocabularyError(f"{location} <{_TERM_TAG}> must not be blank")

    definitions_elements = children_by_tag.get(_DEFINITIONS_TAG, [])
    definitions_element = definitions_elements[0] if definitions_elements else None
    if definitions_element is not None and definitions_element.attrib:
        raise EpaEnterpriseVocabularyError(f"{location} <{_DEFINITIONS_TAG}> must not carry attributes")

    scope_note_elements = children_by_tag.get(_SCOPE_NOTE_TAG, [])
    scope_note_element = scope_note_elements[0] if scope_note_elements else None
    if scope_note_element is not None and scope_note_element.attrib:
        raise EpaEnterpriseVocabularyError(f"{location} <{_SCOPE_NOTE_TAG}> must not carry attributes")

    child_terms_elements = children_by_tag.get(_CHILD_TERMS_TAG, [])
    child_terms_element = child_terms_elements[0] if child_terms_elements else None
    child_rows: tuple[EpaTermRow, ...] = ()
    if child_terms_element is not None:
        if child_terms_element.attrib:
            raise EpaEnterpriseVocabularyError(f"{location} <{_CHILD_TERMS_TAG}> must not carry attributes")
        if (child_terms_element.text or "").strip():
            raise EpaEnterpriseVocabularyError(f"{location} <{_CHILD_TERMS_TAG}> contains unexpected text content")
        parsed_children = []
        for index, child in enumerate(child_terms_element):
            if child.tag != _ROW_TAG:
                raise EpaEnterpriseVocabularyError(
                    f"{location} <{_CHILD_TERMS_TAG}> contains an unsupported element <{child.tag}>"
                )
            parsed_children.append(_parse_row(child, path=path + (index,)))
        child_rows = tuple(parsed_children)

    return EpaTermRow(
        label=term_text,
        source_path=location,
        definitions_text=None if definitions_element is None else (definitions_element.text or ""),
        scope_note_text=None if scope_note_element is None else (scope_note_element.text or ""),
        child_terms=child_rows,
    )


@dataclass(frozen=True, slots=True)
class EpaImportCounts:
    """Feature counts for regression and import-coverage checks."""

    source_bytes: int
    top_level_rows: int
    total_rows: int
    max_depth: int
    rows_with_definitions_element: int
    rows_with_nonblank_definitions: int
    rows_with_scope_note_element: int
    rows_with_nonblank_scope_notes: int


@dataclass(frozen=True, slots=True)
class EpaEnterpriseVocabularyExport:
    """Deterministic parsed view of one exact EPA Enterprise Vocabulary export."""

    source_url: str
    source_sha256: str
    source_bytes: int
    rows: tuple[EpaTermRow, ...]

    @property
    def counts(self) -> EpaImportCounts:
        all_rows: list[tuple[int, EpaTermRow]] = []
        for row in self.rows:
            all_rows.extend(row.walk())
        return EpaImportCounts(
            source_bytes=self.source_bytes,
            top_level_rows=len(self.rows),
            total_rows=len(all_rows),
            max_depth=max((depth for depth, _ in all_rows), default=-1) + 1,
            rows_with_definitions_element=sum(1 for _, row in all_rows if row.definitions_text is not None),
            rows_with_nonblank_definitions=sum(1 for _, row in all_rows if _non_blank(row.definitions_text)),
            rows_with_scope_note_element=sum(1 for _, row in all_rows if row.scope_note_text is not None),
            rows_with_nonblank_scope_notes=sum(1 for _, row in all_rows if _non_blank(row.scope_note_text)),
        )


def parse_epa_enterprise_vocabulary_export(
    source: str | bytes,
    *,
    source_url: str,
    expected_sha256: str | None = None,
    expected_byte_length: int | None = None,
) -> EpaEnterpriseVocabularyExport:
    """Parse one EPA Enterprise Vocabulary export payload into lossless feature rows.

    This never turns a positional row into a minted concept identifier: the
    source publishes none, so this module preserves none.
    """

    _require_absolute_iri(source_url, "source_url")
    payload = _source_payload(source)
    source_sha256 = _DIGEST_PREFIX + hashlib.sha256(payload).hexdigest()
    if expected_sha256 is not None:
        _expected_hex(expected_sha256)
        if source_sha256 != expected_sha256:
            raise EpaEnterpriseVocabularyError(
                f"source digest mismatch: expected {expected_sha256}, got {source_sha256}"
            )
    if expected_byte_length is not None:
        if expected_byte_length <= 0:
            raise EpaEnterpriseVocabularyError("expected_byte_length must be positive")
        if len(payload) != expected_byte_length:
            raise EpaEnterpriseVocabularyError(
                f"source byte length mismatch: expected {expected_byte_length}, got {len(payload)}"
            )

    try:
        root = ET.fromstring(payload)
    except ET.ParseError as error:
        raise EpaEnterpriseVocabularyError(f"could not parse EPA Enterprise Vocabulary export XML: {error}") from error

    if root.tag != _ROOT_TAG:
        raise EpaEnterpriseVocabularyError(f"root element must be <{_ROOT_TAG}>, got <{root.tag}>")
    if root.attrib:
        raise EpaEnterpriseVocabularyError("root element must not carry attributes")
    if (root.text or "").strip():
        raise EpaEnterpriseVocabularyError("root element contains unexpected text content")

    rows = []
    for index, child in enumerate(root):
        if child.tag != _ROW_TAG:
            raise EpaEnterpriseVocabularyError(f"root element contains an unsupported element <{child.tag}>")
        rows.append(_parse_row(child, path=(index,)))

    return EpaEnterpriseVocabularyExport(
        source_url=source_url,
        source_sha256=source_sha256,
        source_bytes=len(payload),
        rows=tuple(rows),
    )


def parse_epa_enterprise_vocabulary_file(
    path: Path,
    *,
    source_url: str,
    expected_sha256: str | None = None,
    expected_byte_length: int | None = None,
) -> EpaEnterpriseVocabularyExport:
    """Parse one local export file while retaining its external source identity."""

    source_path = Path(path)
    if source_path.is_symlink() or not source_path.is_file():
        raise EpaEnterpriseVocabularyError(f"EPA Enterprise Vocabulary source is not a regular file: {source_path}")
    return parse_epa_enterprise_vocabulary_export(
        source_path.read_bytes(),
        source_url=source_url,
        expected_sha256=expected_sha256,
        expected_byte_length=expected_byte_length,
    )


@dataclass(frozen=True, slots=True)
class EpaFetchedExport:
    """One bounded response supplied by an acquisition transport."""

    requested_url: str
    resolved_url: str
    status_code: int
    content_type: str | None
    body: bytes

    def __post_init__(self) -> None:
        for value, field in ((self.requested_url, "requested_url"), (self.resolved_url, "resolved_url")):
            _validate_source_url(value)
        if self.status_code < 100 or self.status_code > 599:
            raise EpaEnterpriseVocabularyError("status_code must be an HTTP status")
        if not isinstance(self.body, bytes):
            raise EpaEnterpriseVocabularyError("resource body must be bytes")


class EpaExportFetcher(Protocol):
    """Transport boundary used by explicit EPA Enterprise Vocabulary acquisition."""

    def __call__(self, url: str, *, timeout_seconds: float, max_bytes: int) -> EpaFetchedExport: ...


EPA_USER_AGENT = (
    "RefSpec bounded EPA Enterprise Vocabulary export resolver/1.0 (research capture; contact via repository)"
)
DEFAULT_MAX_EXPORT_BYTES = 4 * 1024 * 1024


def fetch_epa_export_with_urllib(
    url: str,
    *,
    timeout_seconds: float,
    max_bytes: int,
) -> EpaFetchedExport:
    """Fetch one export URL directly; callers must opt into this transport."""

    if timeout_seconds <= 0:
        raise EpaEnterpriseVocabularyError("timeout_seconds must be positive")
    if max_bytes <= 0:
        raise EpaEnterpriseVocabularyError("max_bytes must be positive")
    request = urllib.request.Request(
        url,
        headers={"Accept": "text/xml", "User-Agent": EPA_USER_AGENT},
        method="GET",
    )
    try:
        response = urllib.request.urlopen(request, timeout=timeout_seconds)
    except urllib.error.HTTPError as error:
        raise EpaEnterpriseVocabularyError(f"EPA Enterprise Vocabulary returned HTTP {error.code} for {url}") from error
    except (OSError, urllib.error.URLError) as error:
        raise EpaEnterpriseVocabularyError(f"could not fetch {url}: {error}") from error
    with response:
        body = response.read(max_bytes + 1)
        if len(body) > max_bytes:
            raise EpaEnterpriseVocabularyError(
                f"EPA Enterprise Vocabulary response exceeds max_bytes={max_bytes}: {url}"
            )
        return EpaFetchedExport(
            requested_url=url,
            resolved_url=response.geturl(),
            status_code=getattr(response, "status", 200),
            content_type=response.headers.get("Content-Type"),
            body=body,
        )


def acquire_epa_enterprise_vocabulary_export(
    source_url: str,
    *,
    fetch: EpaExportFetcher | None = None,
    allow_direct_network: bool = False,
    timeout_seconds: float = 30.0,
    max_bytes: int = DEFAULT_MAX_EXPORT_BYTES,
    expected_sha256: str | None = None,
    expected_byte_length: int | None = None,
) -> EpaEnterpriseVocabularyExport:
    """Acquire and verify one EPA Enterprise Vocabulary export.

    Importing this module never opens a network connection. A caller must
    either inject ``fetch`` or set ``allow_direct_network=True``. Because the
    export URL is session-scoped (see the ``exportDurability`` verification
    gap), the caller is responsible for having already established a valid
    session before ``source_url`` is requested; this function only verifies
    and parses the bytes that come back.
    """

    if timeout_seconds <= 0:
        raise EpaEnterpriseVocabularyError("timeout_seconds must be positive")
    if max_bytes <= 0:
        raise EpaEnterpriseVocabularyError("max_bytes must be positive")
    if fetch is None:
        if not allow_direct_network:
            raise EpaEnterpriseVocabularyError(
                "live EPA Enterprise Vocabulary acquisition requires fetch or allow_direct_network=True"
            )
        fetch = fetch_epa_export_with_urllib

    resource = fetch(source_url, timeout_seconds=timeout_seconds, max_bytes=max_bytes)
    if resource.requested_url != source_url:
        raise EpaEnterpriseVocabularyError("export fetcher returned a different requested_url")
    if resource.status_code != 200:
        raise EpaEnterpriseVocabularyError(
            f"EPA Enterprise Vocabulary returned HTTP {resource.status_code} for {source_url}"
        )
    if len(resource.body) > max_bytes:
        raise EpaEnterpriseVocabularyError(f"EPA Enterprise Vocabulary response exceeds max_bytes={max_bytes}")
    return parse_epa_enterprise_vocabulary_export(
        resource.body,
        source_url=resource.resolved_url,
        expected_sha256=expected_sha256,
        expected_byte_length=expected_byte_length,
    )


@dataclass(frozen=True, slots=True)
class EpaPinnedTierCapture:
    """One verified, byte-pinned EPA Enterprise Vocabulary tier export used for tests.

    ``source_url`` is the exact URL the pinned bytes were fetched from; per
    the ``exportDurability`` gap it is session-scoped and is not expected to
    resolve again later. ``tier_browse_url`` is the stable entry point a
    caller can re-visit to establish a fresh session for the same tier.
    """

    tier_browse_url: str
    source_url: str
    retrieved_at: str
    expected_sha256: str
    expected_byte_length: int
    filename: str
    includes_definitions: bool

    def __post_init__(self) -> None:
        _validate_source_url(self.tier_browse_url)
        _validate_source_url(self.source_url)
        _expected_hex(self.expected_sha256)
        if self.expected_byte_length <= 0:
            raise EpaEnterpriseVocabularyError("expected_byte_length must be positive")
        if not self.filename or Path(self.filename).name != self.filename:
            raise EpaEnterpriseVocabularyError("filename must be one plain path component")
        if not self.retrieved_at.strip():
            raise EpaEnterpriseVocabularyError("retrieved_at must not be empty")


# Real captures fetched 2026-08-03 from the "Regulatory Activities" tier
# (tierTwoSelected=1005100) of https://ofmpub.epa.gov/sor_internet/registry/
# termreg/searchandretrieve/enterprisevocabulary/search.do . Bytes are
# committed verbatim under tests/fixtures/epa_enterprise_vocabulary/. The
# jsessionid-bearing source_url values are recorded for provenance only; see
# the "exportDurability" verification gap above.
EPA_REGULATORY_ACTIVITIES_TIER_CAPTURE = EpaPinnedTierCapture(
    tier_browse_url=f"{EPA_TERMINOLOGY_SERVICES_BASE_URL}?search=&tierTwoSelected=1005100&searchString=",
    source_url=(
        "https://ofmpub.epa.gov/sor_internet/registry/termreg/searchandretrieve/enterprisevocabulary/"
        "search.do;jsessionid=6rzJD5R63L2EfMuWe0LDBSbq7vQBn8EVKJ1JY89NdxFCd-bLvjxD!294405764"
        "?search=&searchString=&6578706f7274=1&d-8056443-e=13&tierTwoSelected=1005100"
    ),
    retrieved_at="2026-08-03T00:00:00Z",
    expected_sha256="sha256:c3e70136a058c6029c8aa47277723b3badf375c324d14a219f51844cb849fc8c",
    expected_byte_length=294,
    filename="epa-enterprise-vocabulary-tier-1005100.xml",
    includes_definitions=False,
)
EPA_REGULATORY_ACTIVITIES_TIER_WITH_DEFINITIONS_CAPTURE = EpaPinnedTierCapture(
    tier_browse_url=f"{EPA_TERMINOLOGY_SERVICES_BASE_URL}?search=&tierTwoSelected=1005100&searchString=",
    source_url=(
        "https://ofmpub.epa.gov/sor_internet/registry/termreg/searchandretrieve/enterprisevocabulary/"
        "search.do?search=&searchString=&6578706f7274=1&d-8056443-e=13&tierTwoSelected=1005100"
        "&checkedIncludeDef=true&showDefs=true"
    ),
    retrieved_at="2026-08-03T00:00:00Z",
    expected_sha256="sha256:beea0c4a099e07d3196903814f569ad781b081cc0b73ee47aff60d118a786df2",
    expected_byte_length=647,
    filename="epa-enterprise-vocabulary-tier-1005100-with-definitions.xml",
    includes_definitions=True,
)


def epa_enterprise_vocabulary_capture_manifest(
    export: EpaEnterpriseVocabularyExport,
    *,
    tier_browse_url: str,
    retrieved_at: str,
) -> dict[str, object]:
    """Deterministic, closed description of one verified EPA Enterprise Vocabulary capture.

    ``kind`` follows this catalog's subject-module labeling for the source's
    role; ``sourceIsNativeSkosRdf`` stays false because the verified export is
    not SKOS/RDF (see the "nativeFormat" gap). This module records
    verification gaps; exact product policy governs use.
    """

    _validate_source_url(tier_browse_url)
    if not retrieved_at.strip():
        raise EpaEnterpriseVocabularyError("retrieved_at must not be empty")
    return {
        "kind": "skosVocabulary",
        "catalogRole": EPA_ENTERPRISE_VOCABULARY_CATALOG_ROLE,
        "publisher": EPA_PUBLISHER,
        "landingPageUrl": EPA_LANDING_PAGE_URL,
        "tierBrowseUrl": tier_browse_url,
        "sourceUrl": export.source_url,
        "sourceSha256": export.source_sha256,
        "sourceBytes": export.source_bytes,
        "retrievedAt": retrieved_at,
        "editionLabel": EPA_EDITION_LABEL,
        "nativeFormat": EPA_NATIVE_FORMAT,
        "sourceIsNativeSkosRdf": False,
        "conceptIdentityClaimed": False,
        "verificationGaps": [dataclasses.asdict(gap) for gap in EPA_ENTERPRISE_VOCABULARY_VERIFICATION_GAPS],
        "counts": dataclasses.asdict(export.counts),
    }


def epa_enterprise_vocabulary_capture_digest(
    export: EpaEnterpriseVocabularyExport,
    *,
    tier_browse_url: str,
    retrieved_at: str,
) -> str:
    """A stable sha256 over the deterministic capture manifest."""

    manifest = epa_enterprise_vocabulary_capture_manifest(
        export,
        tier_browse_url=tier_browse_url,
        retrieved_at=retrieved_at,
    )
    return _DIGEST_PREFIX + hashlib.sha256(canonical_json(manifest).encode("utf-8")).hexdigest()


__all__ = [
    "DEFAULT_MAX_EXPORT_BYTES",
    "EPA_EDITION_LABEL",
    "EPA_ENTERPRISE_VOCABULARY_CATALOG_ROLE",
    "EPA_ENTERPRISE_VOCABULARY_VERIFICATION_GAPS",
    "EPA_LANDING_PAGE_URL",
    "EPA_NATIVE_FORMAT",
    "EPA_PUBLISHER",
    "EPA_REGULATORY_ACTIVITIES_TIER_CAPTURE",
    "EPA_REGULATORY_ACTIVITIES_TIER_WITH_DEFINITIONS_CAPTURE",
    "EPA_TERMINOLOGY_SERVICES_BASE_URL",
    "EPA_USER_AGENT",
    "EpaEnterpriseVocabularyError",
    "EpaEnterpriseVocabularyExport",
    "EpaExportFetcher",
    "EpaFetchedExport",
    "EpaImportCounts",
    "EpaPinnedTierCapture",
    "EpaTermRow",
    "EpaVerificationGap",
    "acquire_epa_enterprise_vocabulary_export",
    "epa_enterprise_vocabulary_capture_digest",
    "epa_enterprise_vocabulary_capture_manifest",
    "fetch_epa_export_with_urllib",
    "parse_epa_enterprise_vocabulary_export",
    "parse_epa_enterprise_vocabulary_file",
]
