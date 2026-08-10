"""Source-faithful capture of the CBO cost-estimates XML feed's Topic labels
and deterministic fiscal facets, plus a verified alternate discovery channel.

CBO publishes an XML feed of recently issued cost estimates at
``https://www.cbo.gov/cost-estimates/xml``. Each feed item carries CBO's own
browse Topic labels alongside deterministic per-estimate fiscal facets: bill
and committee links, budget-function code/label pairs, UMRA intergovernmental
and private-sector mandate flags, and a pay-as-you-go (PAYGO) flag. The
catalog decision for this source is explicit: the 27 browse topics are not a
published semantic vocabulary, so they are packaged only as capture-local
source evidence with no minted identity; the budget-function, mandate, and
PAYGO fields are deterministic fiscal facets that this module keeps
structured but never promotes into subject concepts.

Budget-function codes are the one field CBO supplies as an explicit
publisher-issued value (a ``code`` attribute alongside its label), so those --
and only those -- retain a ``ControlledIdentifier``. Bill number, committee,
and Congress stay plain deterministic text; this module does not mint an
identifier CBO itself does not publish inline, and it does not validate
budget-function codes against the OMB Circular A-11 master list, which is a
separate catalog source (`research/source-vocabulary-ontology-thesaurus-
catalog-2026-07-28.md`, the A-11/TAS/FAST Book row).

Live retrieval is provider-independent: callers inject a fetcher or provide
an already captured local file. Importing this module never opens a network
connection.

Implementation note: a direct capture attempt against the official
``cost-estimates/xml`` URL during development received an HTTP 403 DataDome
bot-challenge response instead of the XML feed (see the
``cbo-datadome-challenge-real-capture.html`` fixture, captured byte-for-byte).
A follow-up attempt on 2026-08-04 through the project's Zyte raw-HTTP
transport also failed -- four consecutive HTTP 520 responses -- so DataDome
blocks both direct and proxy raw-byte acquisition against that URL; a
rendered-browser transport would change the byte-provenance model and has
not been adopted. No verified live bytes of the ``cost-estimates/xml`` feed
were obtainable in this environment, so ``parse_cbo_cost_estimates_feed``
still ships with no pinned "verified live" snapshot constant of its own; the
fixture used by its tests (``cbo-cost-estimates-mini.xml``) is a structural
reconstruction faithful to the field list this catalog row documents
(topics, budget functions, mandate flags, PAYGO, bill and committee links),
not a byte-for-byte official capture. Every shape check in
``parse_cbo_cost_estimates_feed`` is strict specifically so that a real
capture that does not match this reconstruction fails loudly instead of
silently parsing.

VERIFIED FINDING (2026-08-04): CBO's per-Congress feeds -- one file per
Congress at ``https://www.cbo.gov/rss/{congress}congress-cost-estimates.xml``
(build one with ``cbo_per_congress_cost_estimates_url``) -- sit on a
different CDN tier than ``cost-estimates/xml`` and serve plain HTTP 200 with
no DataDome bot wall. A REAL capture of the 119th Congress feed is checked
in (``cbo-119congress-cost-estimates-2026-08-04.xml``, pinned as
``CBO_119TH_CONGRESS_REAL_CAPTURE_2026_08_04``) and confirmed to be the live
feed: 1,058 items. Its document shape is CBO's own custom XML -- a
``<response>`` root of ``<item key="N">`` elements each carrying exactly
``Title``/``Date``/``Link``/``Description``/``Bill_Number`` -- not RSS 2.0,
and structurally unrelated to ``cost-estimates/xml``'s ``<rss><channel>
<item>`` shape. This is a verified, bot-wall-free *discovery* channel
(titles, dates, publication links, and bill numbers, one file per Congress),
not a replacement fiscal-facet source: inspection of the full real capture
confirms it carries no Topic labels, no budget-function codes, no UMRA
mandate flags, and no PAYGO flag of its own. Those fiscal facets remain
unavailable outside the DataDome wall documented above, and budget-function
taxonomy is out of scope for this module entirely -- it lives in the
registry's ``omb_a11_budget_codes`` module, not here. Use
``parse_cbo_per_congress_feed`` for this shape; ``parse_cbo_cost_estimates_feed``
is unrelated to it and still parses only the (still unreachable)
``cost-estimates/xml`` shape.
"""

from __future__ import annotations

import hashlib
import os
import re
import tempfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Literal, Protocol
from urllib.parse import urlsplit

from refspec.registry.infrastructure.controlled_identifier import ControlledIdentifier
from refspec.registry.infrastructure.pinned_acquisition import FetcherAcquisitionMode as AcquisitionMode
from refspec.registry.infrastructure.source_controlled_resource import (
    SourceControlledResourceBundle,
    build_source_controlled_resource_bundle,
)

CBO_PUBLISHER = "Congressional Budget Office"
CBO_IDENTIFIER_AUTHORITY_URI = "https://www.cbo.gov/"
CBO_COST_ESTIMATES_XML_URL = "https://www.cbo.gov/cost-estimates/xml"
CBO_HOSTS = frozenset({"cbo.gov", "www.cbo.gov"})
CBO_LANGUAGE = "en"
CBO_TOPIC_EVIDENCE_RESOURCE_ID = "cbo-cost-estimate-topic-assignments"
CBO_NAMESPACE_URI = "https://www.cbo.gov/xmlns/cost-estimates/1.0"
CBO_NAMESPACES = {"cbo": CBO_NAMESPACE_URI}

CBO_PER_CONGRESS_COST_ESTIMATES_URL_TEMPLATE = "https://www.cbo.gov/rss/{congress}congress-cost-estimates.xml"
# A REAL per-Congress feed, captured directly with curl -- no bot wall on
# this CDN tier, unlike cost-estimates/xml above (see the module docstring).
# Confirmed to be the live 119th Congress feed: a custom <response>/<item>
# document, not RSS 2.0, carrying no Topic labels, budget-function codes,
# mandate flags, or PAYGO facets. See parse_cbo_per_congress_feed and
# CBO_PER_CONGRESS_PORTFOLIO_GAPS.
CBO_119TH_CONGRESS_REAL_CAPTURE_2026_08_04_SHA256 = (
    "sha256:edc957a1115320f1c0da4b02c33d1af146a3c508592ee20b4909e0a8db44d968"
)
CBO_119TH_CONGRESS_REAL_CAPTURE_2026_08_04_BYTE_LENGTH = 375_365
CBO_119TH_CONGRESS_REAL_CAPTURE_2026_08_04_RETRIEVED_AT = "2026-08-04T00:50:00Z"


_DIGEST = re.compile(r"^sha256:([0-9a-f]{64})$")
_PER_CONGRESS_PATH_PATTERN = re.compile(r"^/rss/(\d+)congress-cost-estimates\.xml$")
_PER_CONGRESS_LINK_PATTERN = re.compile(r"^https://www\.cbo\.gov/publication/\d+$")
_PER_CONGRESS_ITEM_CHILD_TAGS = ("Title", "Date", "Link", "Description", "Bill_Number")
# Observed verbatim from the real cbo.gov response captured while this module
# was implemented (a DataDome edge challenge), plus the generic markers other
# RefSpec adapters check for so a future vendor change still fails closed.
_CHALLENGE_MARKERS = (
    b"captcha-delivery.com",
    b"please enable js and disable any ad blocker",
    b"geo.captcha-delivery.com",
    b"cf-chl-",
    b"challenge-platform",
    b"cf-mitigated",
    b"attention required! | cloudflare",
    b"just a moment...</title>",
)
_NO_STABLE_TOPIC_IDENTIFIER_GAP = MappingProxyType(
    {
        "kind": "publisherTopicIdentifierUnavailable",
        "reason": (
            "the cost-estimates/xml feed carries each Topic as a free-text "
            "label with no stable code or IRI, and the catalog treats CBO's "
            "27 browse topics as not a published semantic vocabulary; this "
            "module never mints an identifier for one. The per-Congress "
            "/rss/{congress}congress-cost-estimates.xml feeds are a "
            "verified, bot-wall-free discovery channel (one file per "
            "Congress; see cbo_per_congress_cost_estimates_url and "
            "CBO_119TH_CONGRESS_REAL_CAPTURE_2026_08_04) but do not change "
            "this gap: they carry titles, dates, links, and bill numbers "
            "only, with no Topic labels, budget-function codes, mandate "
            "flags, or PAYGO facets of their own. Those fiscal facets "
            "remain unavailable outside the DataDome wall, and "
            "budget-function taxonomy is a separate catalog source served "
            "by the registry's omb_a11_budget_codes module, not this one."
        ),
    }
)


class CBOTopicCodesError(ValueError):
    """Base class for CBO cost-estimates controlled-resource failures."""


class CBOAcquisitionError(CBOTopicCodesError):
    """Exact source bytes could not be captured safely."""


class CBOSourceDriftError(CBOTopicCodesError):
    """The captured feed no longer has the reviewed structure or pin."""


def sha256_digest(payload: bytes) -> str:
    """Return the canonical RefSpec spelling for a SHA-256 digest."""

    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _validate_official_url(value: str, *, label: str) -> None:
    parsed = urlsplit(value)
    if parsed.scheme != "https" or parsed.hostname not in CBO_HOSTS:
        raise CBOAcquisitionError(f"{label} must be an official HTTPS cbo.gov URL")
    if parsed.username is not None or parsed.password is not None:
        raise CBOAcquisitionError(f"{label} must not contain credentials")


def _validate_feed_url(value: str) -> None:
    _validate_official_url(value, label="source_url")
    if urlsplit(value).path != "/cost-estimates/xml":
        raise CBOAcquisitionError(
            "source_url must address the official cost-estimates/xml feed; a "
            "browse topics or single-estimate page is not this source"
        )


def _validate_per_congress_feed_url(value: str) -> None:
    _validate_official_url(value, label="source_url")
    if _PER_CONGRESS_PATH_PATTERN.fullmatch(urlsplit(value).path) is None:
        raise CBOAcquisitionError(
            "source_url must address one official /rss/{congress}congress-cost-estimates.xml per-Congress feed"
        )


def cbo_per_congress_cost_estimates_url(congress: int) -> str:
    """Build the official per-Congress cost-estimates feed URL for one Congress.

    Documents the verified, bot-wall-free discovery-channel pattern: CBO
    publishes one XML file per Congress at
    ``https://www.cbo.gov/rss/{congress}congress-cost-estimates.xml``,
    confirmed reachable with a plain HTTP 200 and no DataDome challenge (see
    the module docstring).
    """

    if congress <= 0:
        raise CBOAcquisitionError("congress must be a positive integer")
    return CBO_PER_CONGRESS_COST_ESTIMATES_URL_TEMPLATE.format(congress=congress)


@dataclass(frozen=True, slots=True)
class CBOCostEstimatesFeedSnapshotPin:
    """Expected identity of one exact captured cost-estimates XML feed."""

    source_url: str
    retrieved_at: str
    expected_sha256: str
    expected_byte_length: int

    def __post_init__(self) -> None:
        _validate_feed_url(self.source_url)
        if _DIGEST.fullmatch(self.expected_sha256) is None:
            raise CBOAcquisitionError("expected_sha256 must be a lowercase sha256:<64 hex> digest")
        if self.expected_byte_length <= 0:
            raise CBOAcquisitionError("expected_byte_length must be positive")
        if not self.retrieved_at.strip():
            raise CBOAcquisitionError("retrieved_at must not be empty")


@dataclass(frozen=True, slots=True)
class CBOPerCongressFeedSnapshotPin:
    """Expected identity of one exact captured per-Congress cost-estimates feed."""

    source_url: str
    retrieved_at: str
    expected_sha256: str
    expected_byte_length: int

    def __post_init__(self) -> None:
        _validate_per_congress_feed_url(self.source_url)
        if _DIGEST.fullmatch(self.expected_sha256) is None:
            raise CBOAcquisitionError("expected_sha256 must be a lowercase sha256:<64 hex> digest")
        if self.expected_byte_length <= 0:
            raise CBOAcquisitionError("expected_byte_length must be positive")
        if not self.retrieved_at.strip():
            raise CBOAcquisitionError("retrieved_at must not be empty")


CBO_119TH_CONGRESS_REAL_CAPTURE_2026_08_04 = CBOPerCongressFeedSnapshotPin(
    source_url=cbo_per_congress_cost_estimates_url(119),
    retrieved_at=CBO_119TH_CONGRESS_REAL_CAPTURE_2026_08_04_RETRIEVED_AT,
    expected_sha256=CBO_119TH_CONGRESS_REAL_CAPTURE_2026_08_04_SHA256,
    expected_byte_length=CBO_119TH_CONGRESS_REAL_CAPTURE_2026_08_04_BYTE_LENGTH,
)


@dataclass(frozen=True, slots=True)
class FetchedCBOFeed:
    """Provider-independent result returned by an injected feed fetcher."""

    body: bytes
    status_code: int
    content_type: str
    resolved_url: str


class CBOFeedFetcher(Protocol):
    """Minimal transport boundary implemented by direct or proxy fetchers."""

    def fetch(self, source_url: str, *, timeout_seconds: float) -> FetchedCBOFeed:
        """Fetch the official feed once without changing its bytes."""


@dataclass(frozen=True, slots=True)
class AcquiredCBOCostEstimatesFeed:
    """One verified feed document in the content-addressed source store."""

    pin: CBOCostEstimatesFeedSnapshotPin
    path: Path
    source_url: str
    resolved_url: str | None
    sha256: str
    byte_length: int
    content_type: str
    acquisition_mode: AcquisitionMode
    cache_hit: bool
    local_source_path: Path | None


@dataclass(frozen=True, slots=True)
class AcquiredCBOPerCongressFeed:
    """One verified per-Congress feed document in the content-addressed source store."""

    pin: CBOPerCongressFeedSnapshotPin
    path: Path
    source_url: str
    resolved_url: str | None
    sha256: str
    byte_length: int
    content_type: str
    acquisition_mode: AcquisitionMode
    cache_hit: bool
    local_source_path: Path | None


def _validate_xml_payload(payload: bytes) -> None:
    lowered = payload[:64_000].lower()
    if any(marker in lowered for marker in _CHALLENGE_MARKERS):
        raise CBOSourceDriftError("cbo.gov returned a bot-challenge page instead of the cost estimates XML feed")
    stripped = payload.lstrip()
    if not stripped.startswith(b"<?xml") and b"<rss" not in lowered:
        raise CBOSourceDriftError("cbo.gov capture is not the expected cost estimates XML/RSS document")


def _validate_official_resolved_url(value: str) -> None:
    _validate_official_url(value, label="fetcher resolved_url")


def _validate_fetched_feed(fetched: FetchedCBOFeed, *, source_url: str) -> None:
    if fetched.status_code != 200:
        raise CBOAcquisitionError(f"could not acquire {source_url}: HTTP {fetched.status_code}")
    _validate_official_resolved_url(fetched.resolved_url)
    # Check the body for a bot-challenge page before the declared content
    # type: a WAF can serve a challenge under any content type, and the body
    # check gives the more specific, actionable failure message either way.
    _validate_xml_payload(fetched.body)
    media_type = fetched.content_type.partition(";")[0].strip().lower()
    if media_type not in {"application/xml", "text/xml", "application/rss+xml"}:
        raise CBOSourceDriftError(f"cost estimates XML feed content type drifted to {fetched.content_type!r}")


def _validate_fetched_per_congress_feed(fetched: FetchedCBOFeed, *, source_url: str) -> None:
    if fetched.status_code != 200:
        raise CBOAcquisitionError(f"could not acquire {source_url}: HTTP {fetched.status_code}")
    _validate_official_resolved_url(fetched.resolved_url)
    _validate_xml_payload(fetched.body)
    media_type = fetched.content_type.partition(";")[0].strip().lower()
    if media_type not in {"application/xml", "text/xml", "application/rss+xml"}:
        raise CBOSourceDriftError(f"per-Congress cost estimates feed content type drifted to {fetched.content_type!r}")


def _verify_payload(
    payload: bytes,
    pin: CBOCostEstimatesFeedSnapshotPin | CBOPerCongressFeedSnapshotPin,
    *,
    location: str,
) -> tuple[str, int]:
    _validate_xml_payload(payload)
    byte_length = len(payload)
    if byte_length != pin.expected_byte_length:
        raise CBOSourceDriftError(
            f"{location} byte length drift: expected {pin.expected_byte_length}, got {byte_length}"
        )
    actual_sha256 = sha256_digest(payload)
    if actual_sha256 != pin.expected_sha256:
        raise CBOSourceDriftError(f"{location} digest drift: expected {pin.expected_sha256}, got {actual_sha256}")
    return actual_sha256, byte_length


def _verify_existing(path: Path, pin: CBOCostEstimatesFeedSnapshotPin) -> AcquiredCBOCostEstimatesFeed:
    if path.is_symlink() or not path.is_file():
        raise CBOAcquisitionError(f"content-addressed target is not a regular file: {path}")
    actual_sha256, byte_length = _verify_payload(
        path.read_bytes(),
        pin,
        location="cached cost estimates feed",
    )
    return AcquiredCBOCostEstimatesFeed(
        pin=pin,
        path=path,
        source_url=pin.source_url,
        resolved_url=None,
        sha256=actual_sha256,
        byte_length=byte_length,
        content_type="application/xml",
        acquisition_mode="cache",
        cache_hit=True,
        local_source_path=None,
    )


def _publish_payload(
    payload: bytes,
    pin: CBOCostEstimatesFeedSnapshotPin,
    final_path: Path,
    *,
    content_type: str,
    acquisition_mode: Literal["local", "fetcher"],
    resolved_url: str | None,
    local_source_path: Path | None,
) -> AcquiredCBOCostEstimatesFeed:
    actual_sha256, byte_length = _verify_payload(
        payload,
        pin,
        location=f"{acquisition_mode} cost estimates feed",
    )
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
        return AcquiredCBOCostEstimatesFeed(
            pin=pin,
            path=final_path,
            source_url=pin.source_url,
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


def acquire_cbo_cost_estimates_feed(
    pin: CBOCostEstimatesFeedSnapshotPin,
    store_dir: Path,
    *,
    source_path: Path | None = None,
    fetcher: CBOFeedFetcher | None = None,
    timeout_seconds: float = 60.0,
) -> AcquiredCBOCostEstimatesFeed:
    """Acquire the exact feed document from cache, a local capture, or an injected fetcher.

    The caller supplies either ``source_path`` or ``fetcher`` on a cache miss.
    This keeps every live transport outside the source parser while applying
    the same digest, length, origin, and bot-challenge checks to all fetched
    bytes.
    """

    if timeout_seconds <= 0:
        raise CBOAcquisitionError("timeout_seconds must be positive")
    if source_path is not None and fetcher is not None:
        raise CBOAcquisitionError("provide source_path or fetcher, not both")

    digest_hex = pin.expected_sha256.removeprefix("sha256:")
    final_path = Path(store_dir) / "sha256" / digest_hex / "cost-estimates.xml"
    if final_path.exists() or final_path.is_symlink():
        return _verify_existing(final_path, pin)

    if source_path is not None:
        local_path = Path(source_path)
        if local_path.is_symlink() or not local_path.is_file():
            raise CBOAcquisitionError(f"local cost estimates feed source is not a regular file: {local_path}")
        return _publish_payload(
            local_path.read_bytes(),
            pin,
            final_path,
            content_type="application/xml",
            acquisition_mode="local",
            resolved_url=None,
            local_source_path=local_path.resolve(),
        )

    if fetcher is None:
        raise CBOAcquisitionError("cost estimates feed is not cached; provide source_path or an injected fetcher")

    fetched = fetcher.fetch(pin.source_url, timeout_seconds=timeout_seconds)
    _validate_fetched_feed(fetched, source_url=pin.source_url)
    return _publish_payload(
        fetched.body,
        pin,
        final_path,
        content_type=fetched.content_type,
        acquisition_mode="fetcher",
        resolved_url=fetched.resolved_url,
        local_source_path=None,
    )


def capture_initial_cbo_cost_estimates_feed_snapshot(
    store_dir: Path,
    *,
    retrieved_at: str,
    fetcher: CBOFeedFetcher,
    timeout_seconds: float = 60.0,
) -> AcquiredCBOCostEstimatesFeed:
    """Capture valid first-seen feed bytes and return the exact pin they establish.

    This is the discovery step used before a strict
    :func:`acquire_cbo_cost_estimates_feed` reopen.
    """

    if timeout_seconds <= 0:
        raise CBOAcquisitionError("timeout_seconds must be positive")
    if not retrieved_at.strip():
        raise CBOAcquisitionError("retrieved_at must not be empty")
    fetched = fetcher.fetch(CBO_COST_ESTIMATES_XML_URL, timeout_seconds=timeout_seconds)
    _validate_fetched_feed(fetched, source_url=CBO_COST_ESTIMATES_XML_URL)
    pin = CBOCostEstimatesFeedSnapshotPin(
        source_url=CBO_COST_ESTIMATES_XML_URL,
        retrieved_at=retrieved_at,
        expected_sha256=sha256_digest(fetched.body),
        expected_byte_length=len(fetched.body),
    )
    digest_hex = pin.expected_sha256.removeprefix("sha256:")
    final_path = Path(store_dir) / "sha256" / digest_hex / "cost-estimates.xml"
    return _publish_payload(
        fetched.body,
        pin,
        final_path,
        content_type=fetched.content_type,
        acquisition_mode="fetcher",
        resolved_url=fetched.resolved_url,
        local_source_path=None,
    )


def _verify_existing_per_congress(path: Path, pin: CBOPerCongressFeedSnapshotPin) -> AcquiredCBOPerCongressFeed:
    if path.is_symlink() or not path.is_file():
        raise CBOAcquisitionError(f"content-addressed target is not a regular file: {path}")
    actual_sha256, byte_length = _verify_payload(
        path.read_bytes(),
        pin,
        location="cached per-Congress cost estimates feed",
    )
    return AcquiredCBOPerCongressFeed(
        pin=pin,
        path=path,
        source_url=pin.source_url,
        resolved_url=None,
        sha256=actual_sha256,
        byte_length=byte_length,
        content_type="application/xml",
        acquisition_mode="cache",
        cache_hit=True,
        local_source_path=None,
    )


def _publish_per_congress_payload(
    payload: bytes,
    pin: CBOPerCongressFeedSnapshotPin,
    final_path: Path,
    *,
    content_type: str,
    acquisition_mode: Literal["local", "fetcher"],
    resolved_url: str | None,
    local_source_path: Path | None,
) -> AcquiredCBOPerCongressFeed:
    actual_sha256, byte_length = _verify_payload(
        payload,
        pin,
        location=f"{acquisition_mode} per-Congress cost estimates feed",
    )
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
            return _verify_existing_per_congress(final_path, pin)
        return AcquiredCBOPerCongressFeed(
            pin=pin,
            path=final_path,
            source_url=pin.source_url,
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


def acquire_cbo_per_congress_feed(
    pin: CBOPerCongressFeedSnapshotPin,
    store_dir: Path,
    *,
    source_path: Path | None = None,
    fetcher: CBOFeedFetcher | None = None,
    timeout_seconds: float = 60.0,
) -> AcquiredCBOPerCongressFeed:
    """Acquire one exact per-Congress feed document from cache, a local capture, or an injected fetcher.

    Mirrors :func:`acquire_cbo_cost_estimates_feed` for the verified,
    bot-wall-free ``/rss/{congress}congress-cost-estimates.xml`` discovery
    channel (see the module docstring): the same digest, length, origin, and
    bot-challenge guards apply to every fetched or locally supplied payload.
    """

    if timeout_seconds <= 0:
        raise CBOAcquisitionError("timeout_seconds must be positive")
    if source_path is not None and fetcher is not None:
        raise CBOAcquisitionError("provide source_path or fetcher, not both")

    digest_hex = pin.expected_sha256.removeprefix("sha256:")
    final_path = Path(store_dir) / "sha256" / digest_hex / "per-congress-cost-estimates.xml"
    if final_path.exists() or final_path.is_symlink():
        return _verify_existing_per_congress(final_path, pin)

    if source_path is not None:
        local_path = Path(source_path)
        if local_path.is_symlink() or not local_path.is_file():
            raise CBOAcquisitionError(
                f"local per-Congress cost estimates feed source is not a regular file: {local_path}"
            )
        return _publish_per_congress_payload(
            local_path.read_bytes(),
            pin,
            final_path,
            content_type="application/xml",
            acquisition_mode="local",
            resolved_url=None,
            local_source_path=local_path.resolve(),
        )

    if fetcher is None:
        raise CBOAcquisitionError(
            "per-Congress cost estimates feed is not cached; provide source_path or an injected fetcher"
        )

    fetched = fetcher.fetch(pin.source_url, timeout_seconds=timeout_seconds)
    _validate_fetched_per_congress_feed(fetched, source_url=pin.source_url)
    return _publish_per_congress_payload(
        fetched.body,
        pin,
        final_path,
        content_type=fetched.content_type,
        acquisition_mode="fetcher",
        resolved_url=fetched.resolved_url,
        local_source_path=None,
    )


@dataclass(frozen=True, slots=True)
class CBOTopicAssignment:
    """One exact Topic a cost-estimate feed item assigned to itself."""

    label: str
    source_ordinal: int
    record_iri: str


@dataclass(frozen=True, slots=True)
class CBOBudgetFunction:
    """One deterministic budget-function code/label CBO attaches to an estimate.

    ``identifiers`` is populated only when the feed item supplies a ``code``
    attribute; this module never invents one, and never validates the code
    against the OMB Circular A-11 master budget-function list (a separate
    catalog source).
    """

    label: str
    identifiers: tuple[ControlledIdentifier, ...]
    is_general_subject_concept: bool = False

    @property
    def code(self) -> str | None:
        return self.identifiers[0].value if self.identifiers else None


@dataclass(frozen=True, slots=True)
class CBOMandateFlags:
    """Deterministic UMRA mandate flags CBO reports for one estimate."""

    intergovernmental: bool | None
    private_sector: bool | None
    exceeds_threshold: bool | None


@dataclass(frozen=True, slots=True)
class CBOCostEstimateRecord:
    """One parsed feed item: its deterministic fiscal facets and Topic evidence."""

    item_ordinal: int
    title: str
    link: str
    pub_date: str
    congress: str | None
    bill_number: str | None
    committee: str | None
    topics: tuple[CBOTopicAssignment, ...]
    budget_functions: tuple[CBOBudgetFunction, ...]
    mandate: CBOMandateFlags
    pay_as_you_go: bool | None


@dataclass(frozen=True, slots=True)
class ParsedCBOCostEstimatesFeed:
    """Parsed Topic assignments and fiscal facets from one exact, digest-pinned feed."""

    source_url: str
    source_sha256: str
    source_byte_length: int
    retrieved_at: str
    records: tuple[CBOCostEstimateRecord, ...]
    gaps: tuple[str, ...]

    def record_by_bill_number(self) -> dict[str, CBOCostEstimateRecord]:
        """Index records by their deterministic bill number, dropping unlinked ones."""

        return {record.bill_number: record for record in self.records if record.bill_number}


CBO_PORTFOLIO_GAPS: tuple[str, ...] = (
    (
        "The cost-estimates/xml feed carries each Topic as a free-text label "
        "with no stable code or IRI; the catalog treats CBO's 27 browse "
        "topics as not a published semantic vocabulary."
    ),
    (
        "Budget-function labels are recorded exactly as the feed states them "
        "and are not cross-checked against the OMB Circular A-11 master "
        "budget-function list, which is a separate catalog source."
    ),
    (
        "Not every feed item carries a bill number, committee, budget "
        "function, mandate block, or PAYGO flag; a missing field on one item "
        "is not treated as drift."
    ),
)

CBO_PER_CONGRESS_PORTFOLIO_GAPS: tuple[str, ...] = (
    (
        "The /rss/{congress}congress-cost-estimates.xml per-Congress feed "
        "carries only Title, Date, Link, and Bill_Number per item; it "
        "carries no Topic labels, budget-function codes, mandate flags, or "
        "PAYGO facets."
    ),
    (
        "Not every item carries a non-empty Bill_Number; some procedural "
        "items (e.g. weekly House suspension-calendar notices) publish an "
        "empty <Bill_Number/> element, which this module treats as None "
        "rather than as drift."
    ),
    (
        "Budget-function taxonomy is out of scope for this feed entirely "
        "and is covered by the registry's omb_a11_budget_codes module, not "
        "this one."
    ),
    (
        "The fiscal facets documented for cost-estimates/xml (budget "
        "function, UMRA mandate flags, PAYGO) remain unavailable through "
        "this channel; they are unreachable outside the DataDome wall (see "
        "the module docstring)."
    ),
)


def cbo_topic_assignment_record_iri(
    source_sha256: str,
    item_ordinal: int,
    topic_ordinal: int,
) -> str:
    """Build a capture-local observation IRI, not a publisher identifier."""

    match = _DIGEST.fullmatch(source_sha256)
    if match is None:
        raise CBOSourceDriftError("source_sha256 must be a lowercase sha256:<64 hex> digest")
    if item_ordinal < 0 or topic_ordinal < 0:
        raise CBOSourceDriftError("item_ordinal and topic_ordinal must be non-negative")
    return f"urn:ref:cbo-cost-estimate-topic:{match.group(1)}:{item_ordinal}:{topic_ordinal}"


def _parse_tri_bool(value: str | None, field: str) -> bool | None:
    if value is None:
        return None
    text = value.strip().lower()
    if text == "true":
        return True
    if text == "false":
        return False
    raise CBOSourceDriftError(f"{field} must be 'true' or 'false', got {value!r}")


def _optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    text = value.strip()
    return text or None


def _read_acquired_payload(feed: AcquiredCBOCostEstimatesFeed) -> bytes:
    payload = feed.path.read_bytes()
    _verify_payload(payload, feed.pin, location="parsed cost estimates feed")
    return payload


def parse_cbo_cost_estimates_feed(feed: AcquiredCBOCostEstimatesFeed) -> ParsedCBOCostEstimatesFeed:
    """Parse the exact, digest-pinned feed into per-item Topics and fiscal facets."""

    payload = _read_acquired_payload(feed)
    try:
        root = ET.fromstring(payload)
    except ET.ParseError as error:
        raise CBOSourceDriftError("cost estimates feed payload is not valid XML") from error

    if root.tag != "rss" or root.attrib.get("version") != "2.0":
        raise CBOSourceDriftError("cost estimates feed root is no longer an RSS 2.0 document")
    channel = root.find("channel")
    if channel is None:
        raise CBOSourceDriftError("cost estimates feed is missing its channel element")
    items = channel.findall("item")
    if not items:
        raise CBOSourceDriftError("cost estimates feed channel contains no items")

    records: list[CBOCostEstimateRecord] = []
    for ordinal, item in enumerate(items):
        title = (item.findtext("title") or "").strip()
        if not title:
            raise CBOSourceDriftError(f"feed item {ordinal} is missing its title")
        link = (item.findtext("link") or "").strip()
        if not link:
            raise CBOSourceDriftError(f"feed item {ordinal} is missing its link")
        _validate_official_url(link, label=f"feed item {ordinal} link")
        pub_date = (item.findtext("pubDate") or "").strip()
        if not pub_date:
            raise CBOSourceDriftError(f"feed item {ordinal} is missing its pubDate")

        congress = _optional_text(item.findtext("cbo:congress", namespaces=CBO_NAMESPACES))
        bill_number = _optional_text(item.findtext("cbo:billNumber", namespaces=CBO_NAMESPACES))
        committee = _optional_text(item.findtext("cbo:committee", namespaces=CBO_NAMESPACES))

        topic_labels: list[str] = []
        topics_el = item.find("cbo:topics", CBO_NAMESPACES)
        if topics_el is not None:
            for topic_el in topics_el.findall("cbo:topic", CBO_NAMESPACES):
                label = (topic_el.text or "").strip()
                if not label:
                    raise CBOSourceDriftError(f"feed item {ordinal} has an empty Topic label")
                topic_labels.append(label)
        topics = tuple(
            CBOTopicAssignment(
                label=label,
                source_ordinal=topic_ordinal,
                record_iri=cbo_topic_assignment_record_iri(feed.sha256, ordinal, topic_ordinal),
            )
            for topic_ordinal, label in enumerate(topic_labels)
        )

        budget_functions: list[CBOBudgetFunction] = []
        budget_functions_el = item.find("cbo:budgetFunctions", CBO_NAMESPACES)
        if budget_functions_el is not None:
            for bf_el in budget_functions_el.findall("cbo:budgetFunction", CBO_NAMESPACES):
                bf_label = (bf_el.text or "").strip()
                if not bf_label:
                    raise CBOSourceDriftError(f"feed item {ordinal} has an empty budget function label")
                raw_code = bf_el.attrib.get("code")
                identifiers: tuple[ControlledIdentifier, ...] = ()
                if raw_code is not None:
                    code = raw_code.strip()
                    if not code:
                        raise CBOSourceDriftError(f"feed item {ordinal} has an empty budget function code")
                    identifiers = (
                        ControlledIdentifier(
                            value=code,
                            kind="budgetFunctionCode",
                            authority_uri=CBO_IDENTIFIER_AUTHORITY_URI,
                            source_uri=feed.pin.source_url,
                            observed_at=feed.pin.retrieved_at,
                            effective_at=None,
                            source_digest=feed.sha256,
                        ),
                    )
                budget_functions.append(CBOBudgetFunction(label=bf_label, identifiers=identifiers))

        mandates_el = item.find("cbo:mandates", CBO_NAMESPACES)
        if mandates_el is None:
            mandate = CBOMandateFlags(intergovernmental=None, private_sector=None, exceeds_threshold=None)
        else:
            mandate = CBOMandateFlags(
                intergovernmental=_parse_tri_bool(
                    mandates_el.attrib.get("intergovernmental"),
                    f"feed item {ordinal} mandates@intergovernmental",
                ),
                private_sector=_parse_tri_bool(
                    mandates_el.attrib.get("privateSector"),
                    f"feed item {ordinal} mandates@privateSector",
                ),
                exceeds_threshold=_parse_tri_bool(
                    mandates_el.attrib.get("exceedsThreshold"),
                    f"feed item {ordinal} mandates@exceedsThreshold",
                ),
            )

        pay_as_you_go = _parse_tri_bool(
            item.findtext("cbo:payAsYouGo", namespaces=CBO_NAMESPACES),
            f"feed item {ordinal} payAsYouGo",
        )

        records.append(
            CBOCostEstimateRecord(
                item_ordinal=ordinal,
                title=title,
                link=link,
                pub_date=pub_date,
                congress=congress,
                bill_number=bill_number,
                committee=committee,
                topics=topics,
                budget_functions=tuple(budget_functions),
                mandate=mandate,
                pay_as_you_go=pay_as_you_go,
            )
        )

    if not any(record.topics for record in records):
        raise CBOSourceDriftError("cost estimates feed assigns no Topic to any item")

    return ParsedCBOCostEstimatesFeed(
        source_url=feed.pin.source_url,
        source_sha256=feed.sha256,
        source_byte_length=feed.byte_length,
        retrieved_at=feed.pin.retrieved_at,
        records=tuple(records),
        gaps=CBO_PORTFOLIO_GAPS,
    )


@dataclass(frozen=True, slots=True)
class CBOPerCongressCostEstimateRecord:
    """One parsed per-Congress feed item: title, date, link, and bill number only.

    This feed carries no Topic labels, budget-function codes, mandate flags,
    or PAYGO facets; see :data:`CBO_PER_CONGRESS_PORTFOLIO_GAPS`.
    """

    item_ordinal: int
    key: str
    title: str
    date: str
    link: str
    description: str
    bill_number: str | None


@dataclass(frozen=True, slots=True)
class ParsedCBOPerCongressFeed:
    """Parsed title/date/link/bill-number records from one exact, digest-pinned per-Congress feed."""

    source_url: str
    source_sha256: str
    source_byte_length: int
    retrieved_at: str
    records: tuple[CBOPerCongressCostEstimateRecord, ...]
    gaps: tuple[str, ...]

    def record_by_bill_number(self) -> dict[str, CBOPerCongressCostEstimateRecord]:
        """Index records by their deterministic bill number, dropping unlinked ones."""

        return {record.bill_number: record for record in self.records if record.bill_number}


def _read_acquired_per_congress_payload(feed: AcquiredCBOPerCongressFeed) -> bytes:
    payload = feed.path.read_bytes()
    _verify_payload(payload, feed.pin, location="parsed per-Congress cost estimates feed")
    return payload


def parse_cbo_per_congress_feed(feed: AcquiredCBOPerCongressFeed) -> ParsedCBOPerCongressFeed:
    """Parse one exact, digest-pinned per-Congress feed into title/date/link/bill records.

    This is the verified, bot-wall-free discovery channel documented in the
    module docstring: ``https://www.cbo.gov/rss/{congress}congress-cost-
    estimates.xml`` serves a custom ``<response>``/``<item>`` document, not
    RSS 2.0. Every item must carry exactly ``Title``, ``Date``, ``Link``,
    ``Description``, and ``Bill_Number`` in that order (``Bill_Number`` may
    be an empty element -- the real capture shows this for procedural items
    such as weekly House suspension-calendar notices); ``Link`` must match
    ``https://www.cbo.gov/publication/<digits>``. This parser fails closed
    on an unexpected root tag, an unexpected root child, or an item whose
    children do not match that exact set. It carries no Topic labels,
    budget-function codes, mandate flags, or PAYGO facets -- see
    :data:`CBO_PER_CONGRESS_PORTFOLIO_GAPS`.
    """

    payload = _read_acquired_per_congress_payload(feed)
    try:
        root = ET.fromstring(payload)
    except ET.ParseError as error:
        raise CBOSourceDriftError("per-Congress cost estimates feed payload is not valid XML") from error

    if root.tag != "response":
        raise CBOSourceDriftError(f"per-Congress cost estimates feed root is no longer <response>, got <{root.tag}>")

    children = list(root)
    if not children:
        raise CBOSourceDriftError("per-Congress cost estimates feed has no items")

    records: list[CBOPerCongressCostEstimateRecord] = []
    for ordinal, item in enumerate(children):
        if item.tag != "item":
            raise CBOSourceDriftError(
                f"per-Congress cost estimates feed root child {ordinal} is not <item>, got <{item.tag}>"
            )

        child_tags = tuple(child.tag for child in item)
        if child_tags != _PER_CONGRESS_ITEM_CHILD_TAGS:
            raise CBOSourceDriftError(
                f"per-Congress feed item {ordinal} does not carry exactly "
                f"Title/Date/Link/Description/Bill_Number, got {list(child_tags)}"
            )

        key = item.attrib.get("key")
        if not key or not key.strip():
            raise CBOSourceDriftError(f"per-Congress feed item {ordinal} is missing its key attribute")

        title = (item.findtext("Title") or "").strip()
        if not title:
            raise CBOSourceDriftError(f"per-Congress feed item {ordinal} is missing its Title")
        date = (item.findtext("Date") or "").strip()
        if not date:
            raise CBOSourceDriftError(f"per-Congress feed item {ordinal} is missing its Date")
        link = (item.findtext("Link") or "").strip()
        if not link:
            raise CBOSourceDriftError(f"per-Congress feed item {ordinal} is missing its Link")
        if _PER_CONGRESS_LINK_PATTERN.fullmatch(link) is None:
            raise CBOSourceDriftError(
                f"per-Congress feed item {ordinal} link does not match "
                f"https://www.cbo.gov/publication/<digits>: {link!r}"
            )
        description = (item.findtext("Description") or "").strip()
        if not description:
            raise CBOSourceDriftError(f"per-Congress feed item {ordinal} is missing its Description")
        bill_number = _optional_text(item.findtext("Bill_Number"))

        records.append(
            CBOPerCongressCostEstimateRecord(
                item_ordinal=ordinal,
                key=key,
                title=title,
                date=date,
                link=link,
                description=description,
                bill_number=bill_number,
            )
        )

    return ParsedCBOPerCongressFeed(
        source_url=feed.pin.source_url,
        source_sha256=feed.sha256,
        source_byte_length=feed.byte_length,
        retrieved_at=feed.pin.retrieved_at,
        records=tuple(records),
        gaps=CBO_PER_CONGRESS_PORTFOLIO_GAPS,
    )


def _observation(record: CBOCostEstimateRecord, assignment: CBOTopicAssignment) -> dict[str, object]:
    return {
        "id": assignment.record_iri,
        "sourceArtifact": None,  # filled in by the caller once the source_url is known
        "sourcePath": f"channel.item[{record.item_ordinal}].topics.topic[{assignment.source_ordinal}]",
        "sourceOrdinal": assignment.source_ordinal,
        "labels": [
            {
                "value": assignment.label,
                "language": CBO_LANGUAGE,
                "role": "preferred",
            }
        ],
        # CBO's feed links a Topic to no stable code or navigational slug at
        # all; it is a free-text label only, so this module mints no identity.
        "identifiers": [],
        "uses": ["sourceAssignedEvidence"],
        "conceptIdentityClaimed": False,
        "estimateTitle": record.title,
        "estimateLink": record.link,
        "billNumber": record.bill_number,
        "committee": record.committee,
        "congress": record.congress,
        "itemOrdinal": record.item_ordinal,
    }


def build_cbo_topic_evidence_package(
    feed: AcquiredCBOCostEstimatesFeed,
    parsed: ParsedCBOCostEstimatesFeed,
) -> SourceControlledResourceBundle:
    """Package the feed's actual Topic assignments as source evidence.

    This never promotes the result into a concept scheme: ``resource_kind``
    stays ``sourceTermSnapshot`` and every observation's ``identifiers`` list
    stays empty. Candidate authorization does not apply to this non-atlas
    package. Budget functions,
    mandate flags, and the PAYGO flag are deterministic fiscal facets that
    stay on :class:`CBOCostEstimateRecord` and are never packaged here.
    """

    payload = feed.path.read_bytes()
    if len(payload) != feed.byte_length or sha256_digest(payload) != feed.sha256:
        raise CBOSourceDriftError("cost estimates feed package source differs from its acquired pin")
    if parsed.source_sha256 != feed.sha256:
        raise CBOSourceDriftError("parsed cost estimates feed and acquired feed digests differ")
    if parsed.source_url != feed.pin.source_url:
        raise CBOSourceDriftError("parsed cost estimates feed source_url differs from its acquired pin")

    observations: list[dict[str, object]] = []
    for record in parsed.records:
        for assignment in record.topics:
            observation = _observation(record, assignment)
            observation["sourceArtifact"] = parsed.source_url
            observations.append(observation)

    return build_source_controlled_resource_bundle(
        resource_id=CBO_TOPIC_EVIDENCE_RESOURCE_ID,
        title="CBO cost estimate Topic assignments",
        resource_kind="sourceTermSnapshot",
        identity_status="captureLocalObservationsOnly",
        uses=("sourceAssignedEvidence",),
        captured_at=parsed.retrieved_at,
        observations=tuple(observations),
        source_artifacts={parsed.source_url: payload},
        gaps=(_NO_STABLE_TOPIC_IDENTIFIER_GAP,),
    )


__all__ = [
    "CBO_119TH_CONGRESS_REAL_CAPTURE_2026_08_04",
    "CBO_119TH_CONGRESS_REAL_CAPTURE_2026_08_04_BYTE_LENGTH",
    "CBO_119TH_CONGRESS_REAL_CAPTURE_2026_08_04_RETRIEVED_AT",
    "CBO_119TH_CONGRESS_REAL_CAPTURE_2026_08_04_SHA256",
    "CBO_COST_ESTIMATES_XML_URL",
    "CBO_HOSTS",
    "CBO_IDENTIFIER_AUTHORITY_URI",
    "CBO_LANGUAGE",
    "CBO_NAMESPACE_URI",
    "CBO_PER_CONGRESS_COST_ESTIMATES_URL_TEMPLATE",
    "CBO_PER_CONGRESS_PORTFOLIO_GAPS",
    "CBO_PORTFOLIO_GAPS",
    "CBO_PUBLISHER",
    "CBO_TOPIC_EVIDENCE_RESOURCE_ID",
    "AcquiredCBOCostEstimatesFeed",
    "AcquiredCBOPerCongressFeed",
    "AcquisitionMode",
    "CBOAcquisitionError",
    "CBOBudgetFunction",
    "CBOCostEstimateRecord",
    "CBOCostEstimatesFeedSnapshotPin",
    "CBOFeedFetcher",
    "CBOMandateFlags",
    "CBOPerCongressCostEstimateRecord",
    "CBOPerCongressFeedSnapshotPin",
    "CBOSourceDriftError",
    "CBOTopicAssignment",
    "CBOTopicCodesError",
    "FetchedCBOFeed",
    "ParsedCBOCostEstimatesFeed",
    "ParsedCBOPerCongressFeed",
    "acquire_cbo_cost_estimates_feed",
    "acquire_cbo_per_congress_feed",
    "build_cbo_topic_evidence_package",
    "capture_initial_cbo_cost_estimates_feed_snapshot",
    "cbo_per_congress_cost_estimates_url",
    "cbo_topic_assignment_record_iri",
    "parse_cbo_cost_estimates_feed",
    "parse_cbo_per_congress_feed",
    "sha256_digest",
]
