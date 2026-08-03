"""Source-faithful capture of CFR "List of Subjects" assignments.

1 CFR 18.20 requires each agency Federal Register rule document to carry a
list of index terms, drawn from the Federal Register Thesaurus of Indexing
Terms, for every CFR part the document affects.  eCFR renders the resulting,
currently-in-force term list for a part on that part's "current" page (a
"List of Subjects in {title} CFR Part {part}" box).

This module captures that box's exact bytes, verifies them against a pinned
digest, and parses the term labels with explicit title+part provenance.  It
does not mint identifiers for the labels, does not reconcile them against the
Federal Register Thesaurus, and does not assemble them into a concept scheme:
the source catalog classifies this resource as candidate-ranking and
evaluation evidence for CFR-linked material, not a governed vocabulary, so a
managed release is refused unconditionally.

Live retrieval is provider-independent.  Callers inject a fetcher or provide
an already captured local file.  Importing this module never opens a network
connection.

A live `curl` request to an eCFR "current" part page during authoring was
redirected to a bot-management "Federal Register :: Request Access" page
instead of returning the real document, so the bundled test fixtures are
constructed to match the documented page shape rather than captured live
bytes.  The parser is strict about that shape so a real capture that drifts
from it fails loudly instead of silently.
"""

from __future__ import annotations

import hashlib
import os
import re
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Literal, Protocol, cast
from urllib.parse import quote, urlsplit

from refspec.storage import canonical_json

ECFR_PUBLISHER = "Office of the Federal Register, National Archives and Records Administration"
CFR_LANGUAGE = "en"
ASSIGNMENT_EVIDENCE_VERSION = "1.0"

# The only role this resource may carry.  The source catalog designates CFR
# List of Subjects assignments as candidate-ranking and evaluation evidence
# for CFR-linked material, not a governed concept scheme; terms reference the
# Federal Register Thesaurus rather than defining their own vocabulary.
AssignmentRole = Literal["candidateRankingEvidence"]
AcquisitionMode = Literal["cache", "local", "fetcher"]
IdentityStatus = Literal["publisherIdentifierAbsent"]

_DIGEST = re.compile(r"^sha256:([0-9a-f]{64})$")
_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_CHALLENGE_MARKERS = (
    # Observed verbatim from a live www.ecfr.gov capture attempt made while
    # authoring this module: it returned a bot-management challenge instead
    # of the requested page.
    b"federal register :: request access",
    b"unblock_controller",
    b"ip access help",
    b"cf-chl-",
    b"just a moment...</title>",
)


class CFRListOfSubjectsError(ValueError):
    """Base class for CFR List of Subjects capture failures."""


class CFRAcquisitionError(CFRListOfSubjectsError):
    """Exact source bytes could not be captured safely."""


class CFRSourceDriftError(CFRListOfSubjectsError):
    """The captured eCFR page no longer has the reviewed structure."""


class CFRPromotionError(CFRListOfSubjectsError):
    """A managed concept-scheme release was requested against catalog-scoped evidence."""


@dataclass(frozen=True, slots=True)
class CFRPartSource:
    """One eCFR "current" part page whose List of Subjects box is captured."""

    cfr_title: int
    cfr_part: str
    source_url: str
    filename: str

    def __post_init__(self) -> None:
        if self.cfr_title <= 0:
            raise CFRAcquisitionError("cfr_title must be a positive CFR title number")
        if not self.cfr_part.strip():
            raise CFRAcquisitionError("cfr_part must not be empty")
        parsed = urlsplit(self.source_url)
        if parsed.scheme != "https" or parsed.hostname not in {"ecfr.gov", "www.ecfr.gov"}:
            raise CFRAcquisitionError("source_url must be an official HTTPS eCFR URL")
        if parsed.username is not None or parsed.password is not None:
            raise CFRAcquisitionError("source_url must not contain credentials")
        if not self.filename or Path(self.filename).name != self.filename:
            raise CFRAcquisitionError("filename must be one plain path component")

    @property
    def part_citation(self) -> str:
        """The exact citation eCFR embeds in its List of Subjects heading."""

        return f"{self.cfr_title} CFR Part {self.cfr_part}"

    @property
    def part_heading_marker(self) -> str:
        return f"PART {self.cfr_part}"

    @property
    def list_of_subjects_heading(self) -> str:
        return f"List of Subjects in {self.part_citation}"


CFR_LIST_OF_SUBJECTS_SOURCE_1_18 = CFRPartSource(
    cfr_title=1,
    cfr_part="18",
    source_url="https://www.ecfr.gov/current/title-1/chapter-I/subchapter-A/part-18",
    filename="title-1-part-18.html",
)
CFR_LIST_OF_SUBJECTS_SOURCE_40_52 = CFRPartSource(
    cfr_title=40,
    cfr_part="52",
    source_url="https://www.ecfr.gov/current/title-40/chapter-I/part-52",
    filename="title-40-part-52.html",
)


@dataclass(frozen=True, slots=True)
class CFRPartSnapshotPin:
    """Expected identity of one exact eCFR part-page capture."""

    source: CFRPartSource
    retrieved_at: str
    as_of_date: str
    expected_sha256: str
    expected_byte_length: int

    def __post_init__(self) -> None:
        if _DIGEST.fullmatch(self.expected_sha256) is None:
            raise CFRAcquisitionError("expected_sha256 must be a lowercase sha256:<64 hex> digest")
        if self.expected_byte_length <= 0:
            raise CFRAcquisitionError("expected_byte_length must be positive")
        if not self.retrieved_at.strip():
            raise CFRAcquisitionError("retrieved_at must not be empty")
        if _ISO_DATE.fullmatch(self.as_of_date) is None:
            raise CFRAcquisitionError("as_of_date must be an ISO 8601 date (YYYY-MM-DD)")


@dataclass(frozen=True, slots=True)
class FetchedCFRPage:
    """Provider-independent result returned by an injected page fetcher."""

    body: bytes
    status_code: int
    content_type: str
    resolved_url: str


class CFRPageFetcher(Protocol):
    """Minimal transport boundary implemented by direct or proxy fetchers."""

    def fetch(self, source_url: str, *, timeout_seconds: float) -> FetchedCFRPage:
        """Fetch one official page without changing its bytes."""


@dataclass(frozen=True, slots=True)
class AcquiredCFRPage:
    """One verified eCFR part page in the content-addressed source store."""

    pin: CFRPartSnapshotPin
    path: Path
    source_url: str
    resolved_url: str | None
    sha256: str
    byte_length: int
    content_type: str
    acquisition_mode: AcquisitionMode
    cache_hit: bool
    local_source_path: Path | None


def sha256_digest(payload: bytes) -> str:
    """Return the canonical RefSpec spelling for a SHA-256 digest."""

    return "sha256:" + hashlib.sha256(payload).hexdigest()


def cfr_source_record_iri(
    source: CFRPartSource,
    *,
    source_sha256: str,
    source_ordinal: int,
) -> str:
    """Build a capture-local observation IRI, not a publisher identifier."""

    match = _DIGEST.fullmatch(source_sha256)
    if match is None:
        raise CFRSourceDriftError("source_sha256 must be a lowercase sha256:<64 hex> digest")
    if source_ordinal <= 0:
        raise CFRSourceDriftError("source_ordinal must be positive")
    part = quote(source.cfr_part, safe="")
    return f"urn:ref:cfr-list-of-subjects-record:{match.group(1)}:title-{source.cfr_title}:part-{part}:{source_ordinal}"


def _validate_official_resolved_url(value: str) -> None:
    parsed = urlsplit(value)
    if parsed.scheme != "https" or parsed.hostname not in {"ecfr.gov", "www.ecfr.gov"}:
        raise CFRAcquisitionError("fetcher resolved_url must remain on official HTTPS eCFR")
    if parsed.username is not None or parsed.password is not None:
        raise CFRAcquisitionError("fetcher resolved_url must not contain credentials")


def _validate_html_payload(payload: bytes) -> None:
    lowered = payload[:64_000].lower()
    if any(marker in lowered for marker in _CHALLENGE_MARKERS):
        raise CFRSourceDriftError("eCFR returned a challenge page instead of the part page")
    if b"<html" not in lowered and b"<!doctype html" not in lowered:
        raise CFRSourceDriftError("eCFR part-page capture is not an HTML document")


def _validate_fetched_page(fetched: FetchedCFRPage, *, source_url: str) -> None:
    if fetched.status_code != 200:
        raise CFRAcquisitionError(f"could not acquire {source_url}: HTTP {fetched.status_code}")
    _validate_official_resolved_url(fetched.resolved_url)
    media_type = fetched.content_type.partition(";")[0].strip().lower()
    if media_type not in {"text/html", "application/xhtml+xml"}:
        raise CFRSourceDriftError(f"eCFR part page content type drifted to {fetched.content_type!r}")
    _validate_html_payload(fetched.body)


def _verify_payload(payload: bytes, pin: CFRPartSnapshotPin, *, location: str) -> tuple[str, int]:
    _validate_html_payload(payload)
    byte_length = len(payload)
    if byte_length != pin.expected_byte_length:
        raise CFRSourceDriftError(
            f"{location} byte length drift: expected {pin.expected_byte_length}, got {byte_length}"
        )
    actual_sha256 = sha256_digest(payload)
    if actual_sha256 != pin.expected_sha256:
        raise CFRSourceDriftError(f"{location} digest drift: expected {pin.expected_sha256}, got {actual_sha256}")
    return actual_sha256, byte_length


def _verify_existing(path: Path, pin: CFRPartSnapshotPin) -> AcquiredCFRPage:
    if path.is_symlink() or not path.is_file():
        raise CFRAcquisitionError(f"content-addressed target is not a regular file: {path}")
    actual_sha256, byte_length = _verify_payload(path.read_bytes(), pin, location="cached eCFR page")
    return AcquiredCFRPage(
        pin=pin,
        path=path,
        source_url=pin.source.source_url,
        resolved_url=None,
        sha256=actual_sha256,
        byte_length=byte_length,
        content_type="text/html",
        acquisition_mode="cache",
        cache_hit=True,
        local_source_path=None,
    )


def _publish_payload(
    payload: bytes,
    pin: CFRPartSnapshotPin,
    final_path: Path,
    *,
    content_type: str,
    acquisition_mode: Literal["local", "fetcher"],
    resolved_url: str | None,
    local_source_path: Path | None,
) -> AcquiredCFRPage:
    actual_sha256, byte_length = _verify_payload(payload, pin, location=f"{acquisition_mode} eCFR page")
    object_dir = final_path.parent
    object_dir.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=".acquire-", suffix=".tmp", dir=object_dir)
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as output:
            descriptor = -1
            output.write(payload)
            output.flush()
            os.fsync(output.fileno())
        try:
            os.link(temporary_path, final_path)
        except FileExistsError:
            return _verify_existing(final_path, pin)
        return AcquiredCFRPage(
            pin=pin,
            path=final_path,
            source_url=pin.source.source_url,
            resolved_url=resolved_url,
            sha256=actual_sha256,
            byte_length=byte_length,
            content_type=content_type,
            acquisition_mode=acquisition_mode,
            cache_hit=False,
            local_source_path=local_source_path,
        )
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        temporary_path.unlink(missing_ok=True)


def acquire_cfr_part_page(
    pin: CFRPartSnapshotPin,
    store_dir: Path,
    *,
    source_path: Path | None = None,
    fetcher: CFRPageFetcher | None = None,
    timeout_seconds: float = 60.0,
) -> AcquiredCFRPage:
    """Acquire one exact page from cache, a local capture, or an injected fetcher.

    The caller supplies either ``source_path`` or ``fetcher`` on a cache miss.
    This keeps any live transport outside the source parser while applying
    the same digest, length, origin, and challenge-page checks to every
    captured payload.
    """

    if timeout_seconds <= 0:
        raise CFRAcquisitionError("timeout_seconds must be positive")
    if source_path is not None and fetcher is not None:
        raise CFRAcquisitionError("provide source_path or fetcher, not both")

    digest_hex = cast(re.Match[str], _DIGEST.fullmatch(pin.expected_sha256)).group(1)
    final_path = Path(store_dir) / "sha256" / digest_hex / pin.source.filename
    if final_path.exists() or final_path.is_symlink():
        return _verify_existing(final_path, pin)

    if source_path is not None:
        local_path = Path(source_path)
        if local_path.is_symlink() or not local_path.is_file():
            raise CFRAcquisitionError(f"local eCFR source is not a regular file: {local_path}")
        return _publish_payload(
            local_path.read_bytes(),
            pin,
            final_path,
            content_type="text/html",
            acquisition_mode="local",
            resolved_url=None,
            local_source_path=local_path.resolve(),
        )

    if fetcher is None:
        raise CFRAcquisitionError("eCFR page is not cached; provide source_path or an injected fetcher")

    fetched = fetcher.fetch(pin.source.source_url, timeout_seconds=timeout_seconds)
    _validate_fetched_page(fetched, source_url=pin.source.source_url)
    return _publish_payload(
        fetched.body,
        pin,
        final_path,
        content_type=fetched.content_type,
        acquisition_mode="fetcher",
        resolved_url=fetched.resolved_url,
        local_source_path=None,
    )


def capture_initial_cfr_part_snapshot(
    source: CFRPartSource,
    store_dir: Path,
    *,
    retrieved_at: str,
    as_of_date: str,
    fetcher: CFRPageFetcher,
    timeout_seconds: float = 60.0,
) -> AcquiredCFRPage:
    """Capture valid first-seen bytes and return the exact pin they establish.

    This is the discovery step used before a strict :func:`acquire_cfr_part_page`
    reopen.  It validates origin, status, media type, challenge markers, and
    HTML shape before publishing bytes under their content digest.
    """

    if timeout_seconds <= 0:
        raise CFRAcquisitionError("timeout_seconds must be positive")
    if not retrieved_at.strip():
        raise CFRAcquisitionError("retrieved_at must not be empty")
    fetched = fetcher.fetch(source.source_url, timeout_seconds=timeout_seconds)
    _validate_fetched_page(fetched, source_url=source.source_url)
    pin = CFRPartSnapshotPin(
        source=source,
        retrieved_at=retrieved_at,
        as_of_date=as_of_date,
        expected_sha256=sha256_digest(fetched.body),
        expected_byte_length=len(fetched.body),
    )
    digest_hex = pin.expected_sha256.removeprefix("sha256:")
    final_path = Path(store_dir) / "sha256" / digest_hex / source.filename
    return _publish_payload(
        fetched.body,
        pin,
        final_path,
        content_type=fetched.content_type,
        acquisition_mode="fetcher",
        resolved_url=fetched.resolved_url,
        local_source_path=None,
    )


_Block = tuple[Literal["heading", "list"], object]


class _PartPageParser(HTMLParser):
    """Collect ordered headings and lists without any site CSS dependency."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.blocks: list[_Block] = []
        self.all_text: list[str] = []
        self._heading_tag: str | None = None
        self._heading_text: list[str] | None = None
        self._list_depth = 0
        self._list_items: list[list[str]] = []
        self._item_text: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        del attrs
        if tag in {"h1", "h2", "h3", "h4"}:
            self._heading_tag = tag
            self._heading_text = []
        if tag in {"ul", "ol"}:
            self._list_depth += 1
            if self._list_depth == 1:
                self._list_items.append([])
        elif tag == "li" and self._list_depth:
            self._item_text = []

    def handle_data(self, data: str) -> None:
        self.all_text.append(data)
        if self._heading_text is not None:
            self._heading_text.append(data)
        if self._item_text is not None:
            self._item_text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == self._heading_tag and self._heading_text is not None:
            text = _normalize_text(self._heading_text)
            if text:
                self.blocks.append(("heading", text))
            self._heading_text = None
            self._heading_tag = None
        if tag == "li" and self._item_text is not None:
            text = _normalize_text(self._item_text)
            if text and self._list_items:
                self._list_items[-1].append(text)
            self._item_text = None
        elif tag in {"ul", "ol"} and self._list_depth:
            self._list_depth -= 1
            if self._list_depth == 0:
                items = self._list_items.pop()
                if items:
                    self.blocks.append(("list", tuple(items)))


def _normalize_text(chunks: Sequence[str]) -> str:
    return " ".join("".join(chunks).split())


def _read_acquired_payload(page: AcquiredCFRPage) -> bytes:
    payload = page.path.read_bytes()
    _verify_payload(payload, page.pin, location="parsed eCFR page")
    return payload


def _parse_html(payload: bytes) -> _PartPageParser:
    try:
        decoded = payload.decode("utf-8")
    except UnicodeDecodeError as error:
        raise CFRSourceDriftError("eCFR part page is not UTF-8") from error
    parser = _PartPageParser()
    try:
        parser.feed(decoded)
        parser.close()
    except Exception as error:
        raise CFRSourceDriftError("eCFR part page is malformed HTML") from error
    return parser


@dataclass(frozen=True, slots=True)
class CFRSubjectTermEvidence:
    """One exact term label observed in a CFR part's List of Subjects box.

    This is capture-local evidence, not a vocabulary entry: eCFR attaches no
    identifier to the label, and the label is expected to reference a term
    already defined by the Federal Register Thesaurus of Indexing Terms.
    """

    official_label: str
    language: str
    source_ordinal: int
    record_iri: str
    identity_status: IdentityStatus = "publisherIdentifierAbsent"


@dataclass(frozen=True, slots=True)
class CFRDuplicateLabelEvidence:
    """Source rows that share a label but remain separate observations."""

    official_label: str
    record_iris: tuple[str, ...]
    source_ordinals: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class CFRAssignmentReadiness:
    """Why this capture can never become a managed concept-scheme release."""

    part_citation: str
    source_term_count: int
    source_sha256: str
    ready: bool
    blockers: tuple[str, ...]

    def require_ready(self) -> None:
        """Fail rather than promoting catalog-scoped evidence to a vocabulary."""

        if not self.ready:
            raise CFRPromotionError("; ".join(self.blockers))


@dataclass(frozen=True, slots=True)
class ParsedCFRListOfSubjects:
    """One CFR part's List of Subjects assignment, from one exact capture."""

    source: CFRPartSource
    source_sha256: str
    source_byte_length: int
    retrieved_at: str
    as_of_date: str
    part_heading: str
    terms: tuple[CFRSubjectTermEvidence, ...]
    duplicate_label_evidence: tuple[CFRDuplicateLabelEvidence, ...]
    readiness: CFRAssignmentReadiness
    role: AssignmentRole = "candidateRankingEvidence"


def _duplicate_label_evidence(
    terms: Sequence[CFRSubjectTermEvidence],
) -> tuple[CFRDuplicateLabelEvidence, ...]:
    grouped: dict[str, list[CFRSubjectTermEvidence]] = {}
    for term in terms:
        grouped.setdefault(term.official_label, []).append(term)
    return tuple(
        CFRDuplicateLabelEvidence(
            official_label=label,
            record_iris=tuple(term.record_iri for term in matches),
            source_ordinals=tuple(term.source_ordinal for term in matches),
        )
        for label, matches in grouped.items()
        if len(matches) > 1
    )


def _readiness(
    source: CFRPartSource,
    source_sha256: str,
    terms: Sequence[CFRSubjectTermEvidence],
) -> CFRAssignmentReadiness:
    blockers = (
        (
            "the source catalog classifies CFR List of Subjects assignments as "
            "candidate-ranking and evaluation evidence for CFR-linked material, "
            "not a governed concept scheme; do not create an unlabeled duplicate vocabulary"
        ),
        (
            "eCFR attaches no publisher identifier to List of Subjects labels; "
            "every label remains capture-local evidence pending Federal Register "
            "Thesaurus reconciliation"
        ),
    )
    return CFRAssignmentReadiness(
        part_citation=source.part_citation,
        source_term_count=len(terms),
        source_sha256=source_sha256,
        ready=False,
        blockers=blockers,
    )


def parse_cfr_list_of_subjects_page(page: AcquiredCFRPage) -> ParsedCFRListOfSubjects:
    """Parse one pinned eCFR part page into its List of Subjects assignment."""

    payload = _read_acquired_payload(page)
    parser = _parse_html(payload)
    source = page.pin.source

    part_headings = [text for kind, text in parser.blocks if kind == "heading"]
    if not any(source.part_heading_marker in heading for heading in part_headings):
        raise CFRSourceDriftError(f"missing expected part heading marker {source.part_heading_marker!r}")
    part_heading = next(heading for heading in part_headings if source.part_heading_marker in heading)

    page_text = _normalize_text(parser.all_text)
    as_of_marker = f"current as of {page.pin.as_of_date}"
    if as_of_marker not in page_text:
        raise CFRSourceDriftError(f"missing expected 'current as of' banner for {page.pin.as_of_date!r}")

    heading_index = next(
        (
            index
            for index, (kind, value) in enumerate(parser.blocks)
            if kind == "heading" and value == source.list_of_subjects_heading
        ),
        None,
    )
    if heading_index is None:
        raise CFRSourceDriftError(f"missing expected heading {source.list_of_subjects_heading!r}")
    if heading_index + 1 >= len(parser.blocks) or parser.blocks[heading_index + 1][0] != "list":
        raise CFRSourceDriftError(
            f"List of Subjects heading {source.list_of_subjects_heading!r} is not immediately followed by a term list"
        )
    labels = cast(tuple[str, ...], parser.blocks[heading_index + 1][1])
    if not labels:
        raise CFRSourceDriftError("List of Subjects term list is empty")

    terms = tuple(
        CFRSubjectTermEvidence(
            official_label=label,
            language=CFR_LANGUAGE,
            source_ordinal=ordinal,
            record_iri=cfr_source_record_iri(source, source_sha256=page.sha256, source_ordinal=ordinal),
        )
        for ordinal, label in enumerate(labels, start=1)
    )

    return ParsedCFRListOfSubjects(
        source=source,
        source_sha256=page.sha256,
        source_byte_length=page.byte_length,
        retrieved_at=page.pin.retrieved_at,
        as_of_date=page.pin.as_of_date,
        part_heading=part_heading,
        terms=terms,
        duplicate_label_evidence=_duplicate_label_evidence(terms),
        readiness=_readiness(source, page.sha256, terms),
    )


def cfr_list_of_subjects_assignment_evidence(parsed: ParsedCFRListOfSubjects) -> dict[str, Any]:
    """Summarize one assignment capture as a deterministic evidence document.

    The result never claims concept identity and never names a concept
    scheme: it is development-only evidence tying labels to their exact
    title+part+capture provenance.
    """

    return {
        "schemaVersion": ASSIGNMENT_EVIDENCE_VERSION,
        "evidenceKind": "cfrListOfSubjectsAssignment",
        "role": parsed.role,
        "titlePartCitation": parsed.source.part_citation,
        "cfrTitle": parsed.source.cfr_title,
        "cfrPart": parsed.source.cfr_part,
        "sourceUrl": parsed.source.source_url,
        "sourceSha256": parsed.source_sha256,
        "sourceByteLength": parsed.source_byte_length,
        "retrievedAt": parsed.retrieved_at,
        "asOfDate": parsed.as_of_date,
        "partHeading": parsed.part_heading,
        "termCount": len(parsed.terms),
        "terms": [
            {
                "id": term.record_iri,
                "label": term.official_label,
                "language": term.language,
                "sourceOrdinal": term.source_ordinal,
                "identityStatus": term.identity_status,
            }
            for term in parsed.terms
        ],
        "sourceLimitations": [
            "eCFR does not attach a publisher term identifier to List of Subjects entries.",
            (
                "Terms reference the Federal Register Thesaurus of Indexing Terms "
                "and are not a separately governed vocabulary."
            ),
        ],
        "conceptIdentityClaimed": False,
    }


def cfr_list_of_subjects_assignment_evidence_bytes(parsed: ParsedCFRListOfSubjects) -> bytes:
    """Serialize one assignment's evidence deterministically."""

    return canonical_json(cfr_list_of_subjects_assignment_evidence(parsed)).encode("utf-8") + b"\n"


__all__ = [
    "ASSIGNMENT_EVIDENCE_VERSION",
    "CFR_LANGUAGE",
    "CFR_LIST_OF_SUBJECTS_SOURCE_1_18",
    "CFR_LIST_OF_SUBJECTS_SOURCE_40_52",
    "ECFR_PUBLISHER",
    "AcquiredCFRPage",
    "AcquisitionMode",
    "AssignmentRole",
    "CFRAcquisitionError",
    "CFRAssignmentReadiness",
    "CFRDuplicateLabelEvidence",
    "CFRListOfSubjectsError",
    "CFRPageFetcher",
    "CFRPartSnapshotPin",
    "CFRPartSource",
    "CFRPromotionError",
    "CFRSourceDriftError",
    "CFRSubjectTermEvidence",
    "FetchedCFRPage",
    "IdentityStatus",
    "ParsedCFRListOfSubjects",
    "acquire_cfr_part_page",
    "capture_initial_cfr_part_snapshot",
    "cfr_list_of_subjects_assignment_evidence",
    "cfr_list_of_subjects_assignment_evidence_bytes",
    "cfr_source_record_iri",
    "parse_cfr_list_of_subjects_page",
    "sha256_digest",
]
