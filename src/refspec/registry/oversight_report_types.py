"""Source-faithful capture of Oversight.gov's federal Report Type filter values.

Oversight.gov's federal reports listing page
(``https://www.oversight.gov/reports/federal``) renders a faceted search
sidebar. One facet, "Report Type", is a ``<select multiple>`` control whose
``<option>`` elements carry Oversight.gov's own internal filter identifier (a
Drupal taxonomy term id, for example ``"3"`` for Audit) next to the display
label. The live facet publishes ten values: Audit, CIGIE Annual Report,
Disaster Recovery Report, Inspection / Evaluation, Investigation, Other, Peer
Review of OIG, Review, Semiannual Report, and Top Management Challenges. This
is the deterministic report-genre metadata the catalog decision for this
source names -- audit, inspection/evaluation, investigation, review, peer
review, semiannual, and other -- plus the remaining values the facet itself
actually publishes; this module captures every option the page renders, not
only the catalog's illustrative subset. The page documents no JSON constants
endpoint, no separate subject/topic taxonomy, and no public API for this
facet or for report content generally: the ``<select>`` embedded in the
listing page is the only published source, so this module packages it as
deterministic genre metadata and never as a topic vocabulary.

The listing page also renders live federal-report search results below the
filter sidebar, so its whole-page bytes change on essentially every request
even though the Report Type facet itself is stable. A snapshot pin here
therefore marks one dated scrape, not an independently re-fetchable stable
release -- the same limitation this module documents for courtlistener.com's
jurisdictions page.

Acquisition accepts a local exact capture or an injected fetcher. Importing
this module never opens a network connection.
"""

from __future__ import annotations

import hashlib
import os
import re
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from types import MappingProxyType
from typing import Any, Literal, Protocol
from urllib.parse import urlsplit

from refspec.registry.infrastructure.controlled_identifier import ControlledIdentifier
from refspec.registry.infrastructure.pinned_acquisition import FetcherAcquisitionMode as AcquisitionMode
from refspec.registry.infrastructure.source_controlled_resource import (
    ResourceUse,
    SourceControlledResourceBundle,
    build_source_controlled_resource_bundle,
)
from refspec.storage import canonical_json

OVERSIGHT_HOSTS = frozenset({"www.oversight.gov"})
OVERSIGHT_REPORT_TYPES_URL = "https://www.oversight.gov/reports/federal"
OVERSIGHT_IDENTIFIER_AUTHORITY_URI = "https://www.oversight.gov/"
OVERSIGHT_LANGUAGE = "en"
OVERSIGHT_REPORT_TYPES_RESOURCE_ID = "oversight-gov-federal-report-types"


_DIGEST = re.compile(r"^sha256:([0-9a-f]{64})$")
_REPORT_TYPE_SELECTOR = "edit-field-report-type"
_REPORT_TYPE_FIELD_NAME = "field_report_type[]"
# Generic vendor challenge/interstitial markers other RefSpec adapters check
# for so a future WAF or bot-management change still fails closed.
_CHALLENGE_MARKERS = (
    b"<title>access denied</title>",
    b"errors.edgesuite.net",
    b"cf-chl-",
    b"challenge-platform",
    b"cf-mitigated",
    b"attention required! | cloudflare",
    b"just a moment...</title>",
)
_NO_PUBLIC_TOPIC_TAXONOMY_GAP = MappingProxyType(
    {
        "kind": "publisherTopicTaxonomyUnavailable",
        "reason": (
            "oversight.gov publishes the Report Type facet as deterministic "
            "genre metadata only. It exposes no subject/topic taxonomy, JSON "
            "constants endpoint, or public API for report content; the "
            "<select> embedded in the /reports/federal listing page is the "
            "only published source for this facet."
        ),
    }
)
_VOLATILE_LISTING_PAGE_GAP = MappingProxyType(
    {
        "kind": "volatileWholePagePin",
        "reason": (
            "The captured page renders live federal-report search results "
            "below the filter sidebar, so a whole-page digest pin marks one "
            "dated scrape, not a stable, independently re-fetchable release, "
            "even though the Report Type facet itself is stable."
        ),
    }
)
OVERSIGHT_REPORT_TYPES_GAPS: tuple[Mapping[str, str], ...] = (
    _NO_PUBLIC_TOPIC_TAXONOMY_GAP,
    _VOLATILE_LISTING_PAGE_GAP,
)


class OversightReportTypesError(ValueError):
    """Base class for Oversight.gov report-type controlled-resource failures."""


class OversightAcquisitionError(OversightReportTypesError):
    """Exact official page bytes could not be acquired safely."""


class OversightSourceDriftError(OversightReportTypesError):
    """The captured reports listing page no longer has the reviewed structure."""


def sha256_digest(payload: bytes) -> str:
    """Return the canonical RefSpec SHA-256 spelling."""

    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _validate_oversight_url(value: str, field: str) -> None:
    parsed = urlsplit(value)
    if parsed.scheme != "https" or parsed.hostname not in OVERSIGHT_HOSTS:
        raise OversightAcquisitionError(f"{field} must be an official HTTPS oversight.gov URL")
    if parsed.username is not None or parsed.password is not None:
        raise OversightAcquisitionError(f"{field} must not contain credentials")


@dataclass(frozen=True, slots=True)
class OversightReportTypesSnapshotPin:
    """Exact identity of one captured federal reports listing page."""

    source_url: str
    retrieved_at: str
    expected_sha256: str
    expected_byte_length: int

    def __post_init__(self) -> None:
        _validate_oversight_url(self.source_url, "source_url")
        if self.source_url != OVERSIGHT_REPORT_TYPES_URL:
            raise OversightAcquisitionError("source_url must be the official federal reports listing page")
        if _DIGEST.fullmatch(self.expected_sha256) is None:
            raise OversightAcquisitionError("expected_sha256 must be a lowercase sha256:<64 hex> digest")
        if self.expected_byte_length <= 0:
            raise OversightAcquisitionError("expected_byte_length must be positive")
        if not self.retrieved_at.strip():
            raise OversightAcquisitionError("retrieved_at must not be empty")


# The exact page captured while this module was implemented. A future
# request returns different bytes for the live search-result rows below the
# filter sidebar (see _VOLATILE_LISTING_PAGE_GAP); this pin freezes one
# historical, reproducible scrape and does not assert the whole page is
# stable.
OVERSIGHT_REPORT_TYPES_2026_08_03 = OversightReportTypesSnapshotPin(
    source_url=OVERSIGHT_REPORT_TYPES_URL,
    retrieved_at="2026-08-03T19:25:24Z",
    expected_sha256="sha256:8f1f8b29a5ecb224e19505ccdb24edf59b785273a60e807dc95355ffbc1785dd",
    expected_byte_length=110_293,
)


@dataclass(frozen=True, slots=True)
class FetchedOversightPage:
    """Provider-independent response returned by an injected fetcher."""

    body: bytes
    status_code: int
    content_type: str
    resolved_url: str


class OversightPageFetcher(Protocol):
    """Small transport boundary for the official federal reports listing page."""

    def fetch(self, source_url: str, *, timeout_seconds: float) -> FetchedOversightPage:
        """Fetch the page while preserving its exact body bytes."""


@dataclass(frozen=True, slots=True)
class AcquiredOversightReportTypesPage:
    """One verified source object in the content-addressed store."""

    pin: OversightReportTypesSnapshotPin
    path: Path
    sha256: str
    byte_length: int
    source_url: str
    resolved_url: str | None
    content_type: str
    acquisition_mode: AcquisitionMode
    cache_hit: bool
    local_source_path: Path | None


def _validate_html_payload(payload: bytes) -> None:
    lowered = payload[:64_000].lower()
    if any(marker in lowered for marker in _CHALLENGE_MARKERS):
        raise OversightSourceDriftError(
            "oversight.gov returned an access-denied or challenge page instead of the reports listing page"
        )
    if b"<html" not in lowered and b"<!doctype html" not in lowered:
        raise OversightSourceDriftError("oversight.gov reports listing capture is not an HTML document")


def _validate_resolved_url(value: str) -> None:
    _validate_oversight_url(value, "fetcher resolved_url")


def _verify_payload(
    payload: bytes,
    pin: OversightReportTypesSnapshotPin,
    *,
    location: str,
) -> tuple[str, int]:
    _validate_html_payload(payload)
    byte_length = len(payload)
    if byte_length != pin.expected_byte_length:
        raise OversightSourceDriftError(
            f"{location} byte length drift: expected {pin.expected_byte_length}, got {byte_length}"
        )
    actual_sha256 = sha256_digest(payload)
    if actual_sha256 != pin.expected_sha256:
        raise OversightSourceDriftError(f"{location} digest drift: expected {pin.expected_sha256}, got {actual_sha256}")
    return actual_sha256, byte_length


def _verify_existing(
    path: Path,
    pin: OversightReportTypesSnapshotPin,
) -> AcquiredOversightReportTypesPage:
    if path.is_symlink() or not path.is_file():
        raise OversightAcquisitionError(f"content-addressed target is not a regular file: {path}")
    actual_sha256, byte_length = _verify_payload(
        path.read_bytes(),
        pin,
        location="cached Oversight.gov reports listing page",
    )
    return AcquiredOversightReportTypesPage(
        pin=pin,
        path=path,
        sha256=actual_sha256,
        byte_length=byte_length,
        source_url=pin.source_url,
        resolved_url=None,
        content_type="text/html",
        acquisition_mode="cache",
        cache_hit=True,
        local_source_path=None,
    )


def _publish_payload(
    payload: bytes,
    pin: OversightReportTypesSnapshotPin,
    final_path: Path,
    *,
    content_type: str,
    acquisition_mode: Literal["local", "fetcher"],
    resolved_url: str | None,
    local_source_path: Path | None,
) -> AcquiredOversightReportTypesPage:
    actual_sha256, byte_length = _verify_payload(
        payload,
        pin,
        location=f"{acquisition_mode} Oversight.gov reports listing page",
    )
    final_path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=".acquire-",
        suffix=".tmp",
        dir=final_path.parent,
    )
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
        return AcquiredOversightReportTypesPage(
            pin=pin,
            path=final_path,
            sha256=actual_sha256,
            byte_length=byte_length,
            source_url=pin.source_url,
            resolved_url=resolved_url,
            content_type=content_type,
            acquisition_mode=acquisition_mode,
            cache_hit=False,
            local_source_path=local_source_path,
        )
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        temporary_path.unlink(missing_ok=True)


def acquire_oversight_report_types_page(
    pin: OversightReportTypesSnapshotPin,
    store_dir: Path,
    *,
    source_path: Path | None = None,
    fetcher: OversightPageFetcher | None = None,
    timeout_seconds: float = 30.0,
) -> AcquiredOversightReportTypesPage:
    """Acquire one exact reports listing page through a provider-neutral boundary."""

    if timeout_seconds <= 0:
        raise OversightAcquisitionError("timeout_seconds must be positive")
    if source_path is not None and fetcher is not None:
        raise OversightAcquisitionError("provide source_path or fetcher, not both")
    digest_hex = pin.expected_sha256.removeprefix("sha256:")
    final_path = Path(store_dir) / "sha256" / digest_hex / "oversight-reports-federal.html"
    if final_path.exists() or final_path.is_symlink():
        return _verify_existing(final_path, pin)

    if source_path is not None:
        local_path = Path(source_path)
        if local_path.is_symlink() or not local_path.is_file():
            raise OversightAcquisitionError(f"local reports listing source is not a regular file: {local_path}")
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
        raise OversightAcquisitionError(
            "reports listing page is not cached; provide source_path or an injected fetcher"
        )
    fetched = fetcher.fetch(pin.source_url, timeout_seconds=timeout_seconds)
    if fetched.status_code != 200:
        raise OversightAcquisitionError(f"could not acquire {pin.source_url}: HTTP {fetched.status_code}")
    _validate_resolved_url(fetched.resolved_url)
    media_type = fetched.content_type.partition(";")[0].strip().lower()
    if media_type not in {"text/html", "application/xhtml+xml"}:
        raise OversightSourceDriftError(f"reports listing page content type drifted to {fetched.content_type!r}")
    return _publish_payload(
        fetched.body,
        pin,
        final_path,
        content_type=fetched.content_type,
        acquisition_mode="fetcher",
        resolved_url=fetched.resolved_url,
        local_source_path=None,
    )


def _normalize_text(chunks: Sequence[str]) -> str:
    return " ".join("".join(chunks).split())


class _ReportTypeSelectParser(HTMLParser):
    """Walk exactly one ``<select>`` filter control and collect its raw options.

    The parser never interprets any other filter on the listing page (State,
    Agency Wide, Agency Reviewed, and several others all use the same
    ``<select>`` markup shape). It matches only the element whose
    ``data-drupal-selector`` and ``name`` attributes both identify the Report
    Type facet, and it records every ``<option>`` value/label pair inside
    that one element in document order. A real structural change -- a
    renamed selector, a missing ``multiple`` attribute, an empty option list
    -- surfaces as a count or attribute mismatch the caller rejects as drift
    rather than a silent parse.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.select_match_count = 0
        self.select_multiple_attr: str | None = None
        self.options: list[tuple[str | None, str]] = []

        self._select_open = False
        self._in_option = False
        self._option_value: str | None = None
        self._option_chunks: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._open(tag, attrs)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._open(tag, attrs)
        if tag == "option" and self._in_option:
            self._close_option()

    def handle_endtag(self, tag: str) -> None:
        if tag == "option" and self._in_option:
            self._close_option()
        elif tag == "select" and self._select_open:
            self._select_open = False

    def handle_data(self, data: str) -> None:
        if self._in_option:
            self._option_chunks.append(data)

    def _open(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr_map = dict(attrs)
        if tag == "select":
            if (
                attr_map.get("data-drupal-selector") == _REPORT_TYPE_SELECTOR
                and attr_map.get("name") == _REPORT_TYPE_FIELD_NAME
            ):
                self.select_match_count += 1
                if not self._select_open:
                    self._select_open = True
                    self.select_multiple_attr = attr_map.get("multiple")
            return
        if tag == "option" and self._select_open and not self._in_option:
            self._in_option = True
            self._option_value = attr_map.get("value")
            self._option_chunks = []

    def _close_option(self) -> None:
        self.options.append((self._option_value, _normalize_text(self._option_chunks)))
        self._in_option = False
        self._option_value = None
        self._option_chunks = []


@dataclass(frozen=True, slots=True)
class OversightReportTypeOption:
    """One exact Report Type filter option captured verbatim from the page."""

    label: str
    source_ordinal: int
    identifiers: tuple[ControlledIdentifier, ...]


@dataclass(frozen=True, slots=True)
class ParsedOversightReportTypesPage:
    """A parsed, digest-pinned Oversight.gov Report Type facet snapshot."""

    source_url: str
    retrieved_at: str
    source_sha256: str
    source_byte_length: int
    options: tuple[OversightReportTypeOption, ...]
    gaps: tuple[Mapping[str, str], ...]

    def by_publisher_value(self) -> dict[str, OversightReportTypeOption]:
        """Index each option's publisher filter identifier, retaining every field."""

        result: dict[str, OversightReportTypeOption] = {}
        for option in self.options:
            matches = [identifier for identifier in option.identifiers if identifier.kind == "oversightReportTypeId"]
            if len(matches) != 1:
                raise OversightSourceDriftError("Report Type option must retain exactly one oversightReportTypeId")
            result[matches[0].value] = option
        return result


def _read_acquired_payload(page: AcquiredOversightReportTypesPage) -> bytes:
    payload = page.path.read_bytes()
    _verify_payload(payload, page.pin, location="parsed Oversight.gov reports listing page")
    return payload


def parse_oversight_report_types_page(page: AcquiredOversightReportTypesPage) -> ParsedOversightReportTypesPage:
    """Parse exact Report Type facet options without minting or correcting any value."""

    payload = _read_acquired_payload(page)
    try:
        decoded = payload.decode("utf-8")
    except UnicodeDecodeError as error:
        raise OversightSourceDriftError("oversight.gov reports listing page is not UTF-8") from error

    parser = _ReportTypeSelectParser()
    try:
        parser.feed(decoded)
        parser.close()
    except OversightReportTypesError:
        raise
    except Exception as error:
        raise OversightSourceDriftError("oversight.gov reports listing page is malformed HTML") from error

    if parser.select_match_count != 1:
        raise OversightSourceDriftError("reports listing page must contain exactly one Report Type filter select")
    if parser.select_multiple_attr != "multiple":
        raise OversightSourceDriftError("Report Type filter is no longer a multiple-select control")
    if not parser.options:
        raise OversightSourceDriftError("Report Type filter published no options")

    options: list[OversightReportTypeOption] = []
    for ordinal, (value, label) in enumerate(parser.options):
        if value is None or not value.strip():
            raise OversightSourceDriftError(f"Report Type option {ordinal} has no publisher value")
        if not label:
            raise OversightSourceDriftError(f"Report Type option {ordinal} has no label text")
        options.append(
            OversightReportTypeOption(
                label=label,
                source_ordinal=ordinal,
                identifiers=(
                    ControlledIdentifier(
                        value=value,
                        kind="oversightReportTypeId",
                        authority_uri=OVERSIGHT_IDENTIFIER_AUTHORITY_URI,
                        source_uri=page.pin.source_url,
                        observed_at=page.pin.retrieved_at,
                        effective_at=None,
                        source_digest=page.sha256,
                    ),
                ),
            )
        )

    publisher_values = {option.identifiers[0].value for option in options}
    if len(publisher_values) != len(options):
        raise OversightSourceDriftError("Report Type filter contains duplicate publisher values")
    labels = {option.label for option in options}
    if len(labels) != len(options):
        raise OversightSourceDriftError("Report Type filter contains duplicate labels")

    return ParsedOversightReportTypesPage(
        source_url=page.pin.source_url,
        retrieved_at=page.pin.retrieved_at,
        source_sha256=page.sha256,
        source_byte_length=page.byte_length,
        options=tuple(options),
        gaps=OVERSIGHT_REPORT_TYPES_GAPS,
    )


def _identifier_payload(identifier: ControlledIdentifier, *, source_path: str) -> dict[str, Any]:
    return {
        "value": identifier.value,
        "kind": identifier.kind,
        "authorityUri": identifier.authority_uri,
        "sourceUri": identifier.source_uri,
        "sourcePath": f"{source_path}.value",
        "observedAt": identifier.observed_at,
        "sourceDigest": identifier.source_digest,
    }


def _observation_id(*, source_url: str, source_path: str, identifiers: Sequence[Mapping[str, Any]]) -> str:
    identity = {
        "resourceId": OVERSIGHT_REPORT_TYPES_RESOURCE_ID,
        "sourceArtifact": source_url,
        "sourcePath": source_path,
        "identifiers": [
            {"value": item["value"], "kind": item["kind"], "authorityUri": item["authorityUri"]} for item in identifiers
        ],
    }
    digest = hashlib.sha256(canonical_json(identity).encode("utf-8")).hexdigest()
    return f"urn:ref:source-observation:{OVERSIGHT_REPORT_TYPES_RESOURCE_ID}:{digest}"


def _observation(option: OversightReportTypeOption, parsed: ParsedOversightReportTypesPage) -> dict[str, Any]:
    source_path = f"filters.reportType.options[{option.source_ordinal}]"
    identifiers = [_identifier_payload(identifier, source_path=source_path) for identifier in option.identifiers]
    return {
        "id": _observation_id(source_url=parsed.source_url, source_path=source_path, identifiers=identifiers),
        "sourceArtifact": parsed.source_url,
        "sourcePath": source_path,
        # A source option locator only; filter identity always comes from
        # identifiers, never from this position in the select.
        "sourceOrdinal": option.source_ordinal,
        "labels": [
            {"value": option.label, "language": OVERSIGHT_LANGUAGE, "role": "preferred"},
        ],
        "identifiers": identifiers,
        "uses": ["deterministicMetadata"],
        "conceptIdentityClaimed": False,
    }


def build_oversight_report_types_package(
    page: AcquiredOversightReportTypesPage,
    parsed: ParsedOversightReportTypesPage,
    *,
    uses: Sequence[ResourceUse] = ("deterministicMetadata",),
) -> SourceControlledResourceBundle:
    """Package the exact captured Report Type facet as a controlled code list.

    This never promotes the result into a concept scheme or a subject
    taxonomy: ``resource_kind`` stays ``controlledCodeList``, every
    observation's ``uses`` stays limited to the declared deterministic
    uses, and ``conceptIdentityClaimed`` stays false throughout, matching the
    catalog decision that this source supplies deterministic genre metadata
    and that no public topic taxonomy exists for it.
    """

    payload = page.path.read_bytes()
    if len(payload) != page.byte_length or sha256_digest(payload) != page.sha256:
        raise OversightSourceDriftError("Report Type package source differs from its acquired pin")
    if parsed.source_sha256 != page.sha256:
        raise OversightSourceDriftError("parsed reports listing page and acquired page digests differ")
    if parsed.source_url != page.pin.source_url:
        raise OversightSourceDriftError("parsed reports listing page source_url differs from its acquired pin")

    observations = tuple(_observation(option, parsed) for option in parsed.options)
    return build_source_controlled_resource_bundle(
        resource_id=OVERSIGHT_REPORT_TYPES_RESOURCE_ID,
        title="Oversight.gov federal report types",
        resource_kind="controlledCodeList",
        identity_status="publisherIdentifiersPreserved",
        uses=uses,
        captured_at=parsed.retrieved_at,
        observations=observations,
        source_artifacts={parsed.source_url: payload},
        source_observed_count=len(parsed.options),
        gaps=parsed.gaps,
    )


__all__ = [
    "OVERSIGHT_HOSTS",
    "OVERSIGHT_IDENTIFIER_AUTHORITY_URI",
    "OVERSIGHT_LANGUAGE",
    "OVERSIGHT_REPORT_TYPES_2026_08_03",
    "OVERSIGHT_REPORT_TYPES_GAPS",
    "OVERSIGHT_REPORT_TYPES_RESOURCE_ID",
    "OVERSIGHT_REPORT_TYPES_URL",
    "AcquiredOversightReportTypesPage",
    "AcquisitionMode",
    "FetchedOversightPage",
    "OversightAcquisitionError",
    "OversightPageFetcher",
    "OversightReportTypeOption",
    "OversightReportTypesError",
    "OversightReportTypesSnapshotPin",
    "OversightSourceDriftError",
    "ParsedOversightReportTypesPage",
    "acquire_oversight_report_types_page",
    "build_oversight_report_types_package",
    "parse_oversight_report_types_page",
    "sha256_digest",
]
