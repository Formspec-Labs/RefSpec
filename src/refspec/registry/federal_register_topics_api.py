"""Exact capture and source-faithful parsing for FederalRegister.gov topics.

The public topics endpoint is a mutable API response, not a versioned
vocabulary distribution.  This adapter therefore gives each response an exact
byte identity and preserves collection plus source ordinal for every row.  It
does not turn a topic name or slug into an authoritative concept identifier.

Importing this module never opens a network connection.  Network capture must
be requested explicitly, and every captured response is written to a
content-addressed local store only after it passes the source-shape checks.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from spicy_docs.sources.federal_register.topics import (
    DEFAULT_MAX_BYTES,
    FR_TOPICS_URL,
    FrTopicLink,
    FrTopicRow,
    FrTopicsAcquirer,
    FrTopicsBudget,
    FrTopicsRead,
    FrTopicsSourceError,
    read_fr_topics,
)

from refspec.registry.infrastructure.artifact_serialization import (
    file_sha256,
    producer_module_source,
)
from refspec.registry.infrastructure.source_identity import (
    SourceCaptureEvent,
    SourceIdentityError,
    generate_uuid7,
)
from refspec.storage import canonical_json

if TYPE_CHECKING:
    import httpx

FEDERAL_REGISTER_TOPICS_API_URL = FR_TOPICS_URL
# Names RefSpec's mapping policy; installed source-reader hashes identify its code.
FEDERAL_REGISTER_TOPICS_PARSER_VERSION = (
    "federal-register-topics-api-shared-reader-v2"
)

_DIGEST = re.compile(r"^sha256:([0-9a-f]{64})$")
_ROOT_KEYS = frozenset({"meta", "results"})
_RESULT_KEYS = frozenset({"thesaurus", "ad_hoc"})
_TOPIC_KEYS = frozenset(
    {"cfr_references", "name", "see", "see_also", "slug"}
)
_LINK_KEYS = frozenset({"name", "slug"})

TopicCollection = Literal["thesaurus", "ad_hoc"]


class FederalRegisterTopicsError(ValueError):
    """A topics response cannot be preserved without guessing."""


def _sha256_bytes(payload: bytes) -> str:
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _require_exact_keys(
    value: Mapping[str, Any],
    expected: frozenset[str],
    label: str,
) -> None:
    actual = set(value)
    if actual != expected:
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        raise FederalRegisterTopicsError(
            f"{label} fields changed; missing={missing}, extra={extra}"
        )


def _require_nonempty_text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise FederalRegisterTopicsError(f"{label} must be non-empty text")
    return value


def _canonical_json_value(value: object, label: str) -> str:
    try:
        encoded = canonical_json(value)
    except (TypeError, ValueError) as error:
        raise FederalRegisterTopicsError(
            f"{label} must be finite JSON"
        ) from error
    return encoded


@dataclass(frozen=True, slots=True)
class FederalRegisterTopicLink:
    """One exact API-authored topic link."""

    name: str
    slug: str

    def native_payload(self) -> dict[str, str]:
        return {"name": self.name, "slug": self.slug}


@dataclass(frozen=True, slots=True)
class FederalRegisterTopicRecord:
    """One source row identified only within its exact captured response."""

    collection: TopicCollection
    source_ordinal: int
    name: str
    slug: str
    see: tuple[FederalRegisterTopicLink, ...]
    see_also: tuple[FederalRegisterTopicLink, ...]
    cfr_reference_json: tuple[str, ...]

    @property
    def source_locator(self) -> str:
        """Return a capture-local locator, not a concept identifier."""

        return f"results.{self.collection}[{self.source_ordinal}]"

    def native_payload(self) -> dict[str, Any]:
        return {
            "cfr_references": [
                json.loads(item) for item in self.cfr_reference_json
            ],
            "name": self.name,
            "see": [item.native_payload() for item in self.see],
            "see_also": [item.native_payload() for item in self.see_also],
            "slug": self.slug,
        }

    @property
    def source_record_digest(self) -> str:
        """Bind the exact collection, ordinal, and native row."""

        identity = {
            "collection": self.collection,
            "sourceOrdinal": self.source_ordinal,
            "record": self.native_payload(),
        }
        return _sha256_bytes(canonical_json(identity).encode("utf-8"))


@dataclass(frozen=True, slots=True)
class FederalRegisterTopicsSnapshot:
    """One parsed view of one exact topics API response."""

    source_sha256: str
    source_byte_length: int
    thesaurus: tuple[FederalRegisterTopicRecord, ...]
    ad_hoc: tuple[FederalRegisterTopicRecord, ...]

    @property
    def records(self) -> tuple[FederalRegisterTopicRecord, ...]:
        return (*self.thesaurus, *self.ad_hoc)

    @property
    def counts(self) -> dict[str, int]:
        return {
            "thesaurus": len(self.thesaurus),
            "ad_hoc": len(self.ad_hoc),
            "total": len(self.thesaurus) + len(self.ad_hoc),
        }

    @property
    def source_record_set_digest(self) -> str:
        """Digest every source row without inventing cross-capture identity."""

        rows = [
            {
                "collection": item.collection,
                "sourceOrdinal": item.source_ordinal,
                "sourceRecordDigest": item.source_record_digest,
            }
            for item in self.records
        ]
        return _sha256_bytes(canonical_json(rows).encode("utf-8"))

    def slug_collisions(
        self,
    ) -> dict[tuple[TopicCollection, str], tuple[FederalRegisterTopicRecord, ...]]:
        """Return slugs that cannot identify one row inside a collection."""

        grouped: dict[
            tuple[TopicCollection, str],
            list[FederalRegisterTopicRecord],
        ] = defaultdict(list)
        for item in self.records:
            grouped[(item.collection, item.slug)].append(item)
        return {
            key: tuple(rows)
            for key, rows in grouped.items()
            if len(rows) > 1
        }


def _accepted_link(link: FrTopicLink) -> FederalRegisterTopicLink:
    _require_exact_keys(link.raw, _LINK_KEYS, link.source_path)
    return FederalRegisterTopicLink(
        name=_require_nonempty_text(link.name, f"{link.source_path}.name"),
        slug=link.slug,
    )


def _accepted_topic(row: FrTopicRow) -> FederalRegisterTopicRecord:
    _require_exact_keys(row.raw, _TOPIC_KEYS, row.source_path)
    return FederalRegisterTopicRecord(
        collection=row.collection,
        source_ordinal=row.source_ordinal,
        name=_require_nonempty_text(row.name, f"{row.source_path}.name"),
        slug=row.slug,
        see=tuple(_accepted_link(link) for link in row.see),
        see_also=tuple(_accepted_link(link) for link in row.see_also),
        cfr_reference_json=tuple(
            _canonical_json_value(reference.raw, reference.source_path)
            for reference in row.cfr_references
        ),
    )


def _accepted_snapshot(source: FrTopicsRead) -> FederalRegisterTopicsSnapshot:
    """Apply RefSpec's complete-key, nonempty-label and count acceptance rules."""
    _require_exact_keys(source.raw, _ROOT_KEYS, "topics response")
    _require_exact_keys(source.raw["meta"], frozenset({"count"}), "meta")
    _require_exact_keys(source.raw["meta"]["count"], _RESULT_KEYS | {"total"}, "meta.count")
    _require_exact_keys(source.raw["results"], _RESULT_KEYS, "results")
    parsed = {
        collection.name: tuple(_accepted_topic(row) for row in collection.rows)
        for collection in source.collections
    }
    for key, actual in source.observed_counts.items():
        declared = source.declared_counts[key]
        if declared != actual:
            raise FederalRegisterTopicsError(
                f"meta.count.{key} declares {declared}, observed {actual}"
            )
    return FederalRegisterTopicsSnapshot(
        source_sha256="sha256:" + source.input_sha256,
        source_byte_length=source.input_bytes,
        thesaurus=parsed["thesaurus"],
        ad_hoc=parsed["ad_hoc"],
    )


def parse_federal_register_topics_api(payload: bytes) -> FederalRegisterTopicsSnapshot:
    """Read through SpicyDocs, then apply the receiver's source acceptance rules."""
    try:
        source = read_fr_topics(payload)
    except FrTopicsSourceError as error:
        raise FederalRegisterTopicsError(str(error)) from error
    return _accepted_snapshot(source)


@dataclass(frozen=True, slots=True)
class AcquiredFederalRegisterTopics:
    """One verified topics response in a content-addressed local store."""

    path: Path
    source_url: str
    resolved_url: str | None
    source_sha256: str
    byte_length: int
    acquisition_mode: Literal["local", "network"]
    snapshot: FederalRegisterTopicsSnapshot
    capture_event: SourceCaptureEvent
    receipt_path: Path


def _resolve_capture_event(
    *,
    retrieved_at: str | None,
    fetch_event: SourceCaptureEvent | None,
) -> SourceCaptureEvent:
    try:
        if fetch_event is not None:
            if retrieved_at is not None and fetch_event.fetched_at != retrieved_at:
                raise FederalRegisterTopicsError(
                    "Federal Register topics fetch event time must equal retrieved_at"
                )
            return SourceCaptureEvent(
                fetch_id=fetch_event.fetch_id,
                fetched_at=fetch_event.fetched_at,
            )
        observed_at = retrieved_at or datetime.now(UTC).isoformat(
            timespec="seconds"
        ).replace("+00:00", "Z")
        return SourceCaptureEvent.generate(fetched_at=observed_at)
    except SourceIdentityError as error:
        raise FederalRegisterTopicsError(str(error)) from error


def _publish_capture(
    payload: bytes,
    store_dir: Path,
    *,
    source_url: str,
    resolved_url: str | None,
    acquisition_mode: Literal["local", "network"],
    capture_event: SourceCaptureEvent,
    producer_modules: dict[str, str],
    snapshot: FederalRegisterTopicsSnapshot | None = None,
) -> AcquiredFederalRegisterTopics:
    if snapshot is None:
        snapshot = parse_federal_register_topics_api(payload)
    digest_hex = snapshot.source_sha256.removeprefix("sha256:")
    destination = (
        Path(store_dir) / "sha256" / digest_hex / "topics.json"
    )
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists() or destination.is_symlink():
        if destination.is_symlink() or not destination.is_file():
            raise FederalRegisterTopicsError(
                f"capture target is not a regular file: {destination}"
            )
        existing = destination.read_bytes()
        if existing != payload:
            raise FederalRegisterTopicsError(
                "content-addressed capture path contains different bytes"
            )
    else:
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=".topics-",
            suffix=".tmp",
            dir=destination.parent,
        )
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "wb") as output:
                output.write(payload)
                output.flush()
                os.fsync(output.fileno())
            try:
                os.link(temporary, destination)
            except FileExistsError as error:
                if destination.is_symlink() or destination.read_bytes() != payload:
                    raise FederalRegisterTopicsError(
                        "capture target changed during publication"
                    ) from error
        finally:
            temporary.unlink(missing_ok=True)
    # A replay may reuse the acquisition event and bytes. Give this processing
    # run its own record, outside the content-addressed source and sealed package.
    recorded_at = datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    run_id = generate_uuid7(recorded_at=recorded_at)
    receipt_path = Path(store_dir) / "runs" / f"{run_id}.json"
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    receipt = canonical_json({
        "schemaVersion": "federal-register-topics-run-v1",
        "runId": run_id,
        "recordedAt": recorded_at,
        "captureEvent": capture_event.as_dict(),
        "acquisitionMode": acquisition_mode,
        "sourceSha256": snapshot.source_sha256,
        "sourceByteLength": snapshot.source_byte_length,
        "parserVersion": FEDERAL_REGISTER_TOPICS_PARSER_VERSION,
        "producer": {"modules": producer_modules},
    })
    descriptor, temporary_name = tempfile.mkstemp(prefix=".run-", dir=receipt_path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            output.write(receipt)
            output.flush()
            os.fsync(output.fileno())
        os.link(temporary, receipt_path)
    finally:
        temporary.unlink(missing_ok=True)
    return AcquiredFederalRegisterTopics(
        path=destination,
        source_url=source_url,
        resolved_url=resolved_url,
        source_sha256=snapshot.source_sha256,
        byte_length=snapshot.source_byte_length,
        acquisition_mode=acquisition_mode,
        snapshot=snapshot,
        capture_event=capture_event,
        receipt_path=receipt_path,
    )


def capture_federal_register_topics(
    store_dir: Path,
    *,
    source_path: Path | None = None,
    allow_network: bool = False,
    timeout_seconds: float = 60.0,
    retrieved_at: str | None = None,
    fetch_event: SourceCaptureEvent | None = None,
    transport: httpx.BaseTransport | None = None,
) -> AcquiredFederalRegisterTopics:
    """Capture one mutable API response, locally unless network is explicit.

    Every capture records a :class:`SourceCaptureEvent`. Pass ``fetch_event``
    when rebuilding a previously persisted acquisition; otherwise a new event
    is minted. ``receipt_path`` retains that event and this run's source-reader
    hashes separately from the source bytes and sealed package identity.
    """

    if timeout_seconds <= 0:
        raise FederalRegisterTopicsError(
            "timeout_seconds must be positive"
        )
    capture_event = _resolve_capture_event(
        retrieved_at=retrieved_at,
        fetch_event=fetch_event,
    )
    producer_modules = {
        name: file_sha256(producer_module_source(name))
        for name in (
            __name__,
            "spicy_docs.sources.federal_register.topics",
            "spicy_docs.reading.json_input",
        )
    }
    if source_path is not None:
        local_path = Path(source_path)
        if local_path.is_symlink() or not local_path.is_file():
            raise FederalRegisterTopicsError(
                f"local topics source is not a regular file: {local_path}"
            )
        return _publish_capture(
            local_path.read_bytes(),
            Path(store_dir),
            source_url=FEDERAL_REGISTER_TOPICS_API_URL,
            resolved_url=None,
            acquisition_mode="local",
            capture_event=capture_event,
            producer_modules=producer_modules,
        )
    if not allow_network:
        raise FederalRegisterTopicsError(
            "provide source_path or set allow_network=True explicitly"
        )

    import httpx

    budget = FrTopicsBudget(
        max_requests=1,
        max_bytes=DEFAULT_MAX_BYTES,
        timeout_seconds=timeout_seconds,
        min_request_interval_seconds=0,
    )
    try:
        with FrTopicsAcquirer(budget=budget, transport=transport) as source:
            acquired = source.acquire_topics()
    except (FrTopicsSourceError, httpx.HTTPError, OSError) as error:
        raise FederalRegisterTopicsError(str(error)) from error
    return _publish_capture(
        acquired.capture.body,
        Path(store_dir),
        source_url=acquired.capture.requested_url,
        resolved_url=acquired.capture.resolved_url,
        acquisition_mode="network",
        capture_event=capture_event,
        producer_modules=producer_modules,
        snapshot=_accepted_snapshot(acquired.topics),
    )


def open_federal_register_topics_capture(
    path: Path,
    *,
    expected_sha256: str,
    expected_byte_length: int,
) -> FederalRegisterTopicsSnapshot:
    """Reopen one exact capture and recheck both byte pins."""

    if _DIGEST.fullmatch(expected_sha256) is None:
        raise FederalRegisterTopicsError(
            "expected_sha256 must be a lowercase sha256:<64 hex> digest"
        )
    source_path = Path(path)
    if source_path.is_symlink() or not source_path.is_file():
        raise FederalRegisterTopicsError(
            f"captured topics source is not a regular file: {source_path}"
        )
    payload = source_path.read_bytes()
    if len(payload) != expected_byte_length:
        raise FederalRegisterTopicsError(
            "captured topics byte length does not match its pin"
        )
    actual_digest = _sha256_bytes(payload)
    if actual_digest != expected_sha256:
        raise FederalRegisterTopicsError(
            "captured topics digest does not match its pin"
        )
    return parse_federal_register_topics_api(payload)


__all__ = [
    "FEDERAL_REGISTER_TOPICS_API_URL",
    "FEDERAL_REGISTER_TOPICS_PARSER_VERSION",
    "AcquiredFederalRegisterTopics",
    "FederalRegisterTopicLink",
    "FederalRegisterTopicRecord",
    "FederalRegisterTopicsError",
    "FederalRegisterTopicsSnapshot",
    "TopicCollection",
    "capture_federal_register_topics",
    "open_federal_register_topics_capture",
    "parse_federal_register_topics_api",
]
