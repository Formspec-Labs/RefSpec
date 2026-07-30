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
import unicodedata
import urllib.error
import urllib.request
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from refspec.registry.federal_register_thesaurus import FederalRegisterThesaurus
from refspec.storage import canonical_json

FEDERAL_REGISTER_TOPICS_API_URL = (
    "https://www.federalregister.gov/api/v1/topics.json"
)
FEDERAL_REGISTER_TOPICS_PARSER_VERSION = (
    "federal-register-topics-api-source-faithful-v1"
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


def _require_text(value: object, label: str) -> str:
    if not isinstance(value, str):
        raise FederalRegisterTopicsError(f"{label} must be text")
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


def _parse_link(value: object, label: str) -> FederalRegisterTopicLink:
    if not isinstance(value, Mapping):
        raise FederalRegisterTopicsError(f"{label} must be an object")
    _require_exact_keys(value, _LINK_KEYS, label)
    return FederalRegisterTopicLink(
        name=_require_nonempty_text(value["name"], f"{label}.name"),
        slug=_require_text(value["slug"], f"{label}.slug"),
    )


def _parse_links(value: object, label: str) -> tuple[FederalRegisterTopicLink, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise FederalRegisterTopicsError(f"{label} must be an array")
    return tuple(
        _parse_link(item, f"{label}[{index}]")
        for index, item in enumerate(value)
    )


def _parse_topic(
    value: object,
    *,
    collection: TopicCollection,
    source_ordinal: int,
) -> FederalRegisterTopicRecord:
    label = f"results.{collection}[{source_ordinal}]"
    if not isinstance(value, Mapping):
        raise FederalRegisterTopicsError(f"{label} must be an object")
    _require_exact_keys(value, _TOPIC_KEYS, label)
    cfr_references = value["cfr_references"]
    if not isinstance(cfr_references, Sequence) or isinstance(
        cfr_references, (str, bytes)
    ):
        raise FederalRegisterTopicsError(
            f"{label}.cfr_references must be an array"
        )
    return FederalRegisterTopicRecord(
        collection=collection,
        source_ordinal=source_ordinal,
        name=_require_nonempty_text(value["name"], f"{label}.name"),
        slug=_require_text(value["slug"], f"{label}.slug"),
        see=_parse_links(value["see"], f"{label}.see"),
        see_also=_parse_links(value["see_also"], f"{label}.see_also"),
        cfr_reference_json=tuple(
            _canonical_json_value(
                item,
                f"{label}.cfr_references[{index}]",
            )
            for index, item in enumerate(cfr_references)
        ),
    )


def parse_federal_register_topics_api(
    payload: bytes,
) -> FederalRegisterTopicsSnapshot:
    """Parse one exact API response and reject source-shape drift."""

    if not isinstance(payload, bytes) or not payload:
        raise FederalRegisterTopicsError("topics payload must be non-empty bytes")
    try:
        value = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise FederalRegisterTopicsError(
            "topics payload must be valid UTF-8 JSON"
        ) from error
    if not isinstance(value, Mapping):
        raise FederalRegisterTopicsError("topics response must be an object")
    _require_exact_keys(value, _ROOT_KEYS, "topics response")

    meta = value["meta"]
    results = value["results"]
    if not isinstance(meta, Mapping) or set(meta) != {"count"}:
        raise FederalRegisterTopicsError(
            "meta must contain only the declared count object"
        )
    declared_counts = meta["count"]
    if not isinstance(declared_counts, Mapping):
        raise FederalRegisterTopicsError("meta.count must be an object")
    _require_exact_keys(declared_counts, _RESULT_KEYS | {"total"}, "meta.count")
    if not isinstance(results, Mapping):
        raise FederalRegisterTopicsError("results must be an object")
    _require_exact_keys(results, _RESULT_KEYS, "results")

    parsed: dict[
        TopicCollection,
        tuple[FederalRegisterTopicRecord, ...],
    ] = {}
    for collection in ("thesaurus", "ad_hoc"):
        rows = results[collection]
        if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes)):
            raise FederalRegisterTopicsError(
                f"results.{collection} must be an array"
            )
        parsed[collection] = tuple(
            _parse_topic(
                row,
                collection=collection,
                source_ordinal=index,
            )
            for index, row in enumerate(rows)
        )

    actual_counts = {
        "thesaurus": len(parsed["thesaurus"]),
        "ad_hoc": len(parsed["ad_hoc"]),
    }
    actual_counts["total"] = sum(actual_counts.values())
    for key, actual in actual_counts.items():
        declared = declared_counts.get(key)
        if not isinstance(declared, int) or isinstance(declared, bool):
            raise FederalRegisterTopicsError(
                f"meta.count.{key} must be an integer"
            )
        if declared != actual:
            raise FederalRegisterTopicsError(
                f"meta.count.{key} declares {declared}, observed {actual}"
            )

    return FederalRegisterTopicsSnapshot(
        source_sha256=_sha256_bytes(payload),
        source_byte_length=len(payload),
        thesaurus=parsed["thesaurus"],
        ad_hoc=parsed["ad_hoc"],
    )


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


def _publish_capture(
    payload: bytes,
    store_dir: Path,
    *,
    source_url: str,
    resolved_url: str | None,
    acquisition_mode: Literal["local", "network"],
) -> AcquiredFederalRegisterTopics:
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
            except FileExistsError:
                if destination.is_symlink() or destination.read_bytes() != payload:
                    raise FederalRegisterTopicsError(
                        "capture target changed during publication"
                    )
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
    )


def capture_federal_register_topics(
    store_dir: Path,
    *,
    source_path: Path | None = None,
    allow_network: bool = False,
    timeout_seconds: float = 60.0,
) -> AcquiredFederalRegisterTopics:
    """Capture one mutable API response, locally unless network is explicit."""

    if timeout_seconds <= 0:
        raise FederalRegisterTopicsError(
            "timeout_seconds must be positive"
        )
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
        )
    if not allow_network:
        raise FederalRegisterTopicsError(
            "provide source_path or set allow_network=True explicitly"
        )

    request = urllib.request.Request(
        FEDERAL_REGISTER_TOPICS_API_URL,
        headers={
            "Accept": "application/json",
            "User-Agent": "RefSpec explicit Federal Register topics capture/1.0",
        },
        method="GET",
    )
    try:
        response = urllib.request.urlopen(request, timeout=timeout_seconds)
    except (OSError, urllib.error.URLError) as error:
        raise FederalRegisterTopicsError(
            f"could not capture {FEDERAL_REGISTER_TOPICS_API_URL}: {error}"
        ) from error
    with response:
        return _publish_capture(
            response.read(),
            Path(store_dir),
            source_url=FEDERAL_REGISTER_TOPICS_API_URL,
            resolved_url=response.geturl(),
            acquisition_mode="network",
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


def _normalized_label(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    return " ".join(normalized.split())


@dataclass(frozen=True, slots=True)
class FederalRegisterTopicsComparison:
    """Observed differences only; this record never asserts concept identity."""

    historical_source_sha256: str
    current_source_sha256: str
    historical_preferred_count: int
    current_thesaurus_count: int
    current_ad_hoc_count: int
    preferred_label_overlap_count: int
    historical_preferred_only: tuple[str, ...]
    current_preferred_only: tuple[str, ...]
    historical_any_label_overlap_count: int
    historical_relation_count: int
    current_see_also_count: int
    current_slug_collision_groups: int

    @property
    def canonical_digest(self) -> str:
        return _sha256_bytes(
            canonical_json(
                {
                    "historicalSourceSha256": self.historical_source_sha256,
                    "currentSourceSha256": self.current_source_sha256,
                    "historicalPreferredCount": (
                        self.historical_preferred_count
                    ),
                    "currentThesaurusCount": self.current_thesaurus_count,
                    "currentAdHocCount": self.current_ad_hoc_count,
                    "preferredLabelOverlapCount": (
                        self.preferred_label_overlap_count
                    ),
                    "historicalPreferredOnly": list(
                        self.historical_preferred_only
                    ),
                    "currentPreferredOnly": list(
                        self.current_preferred_only
                    ),
                    "historicalAnyLabelOverlapCount": (
                        self.historical_any_label_overlap_count
                    ),
                    "historicalRelationCount": (
                        self.historical_relation_count
                    ),
                    "currentSeeAlsoCount": self.current_see_also_count,
                    "currentSlugCollisionGroups": (
                        self.current_slug_collision_groups
                    ),
                    "identityInference": "none",
                    "outcome": "unresolved",
                }
            ).encode("utf-8")
        )


def compare_historical_thesaurus_to_topics(
    historical: FederalRegisterThesaurus,
    current: FederalRegisterTopicsSnapshot,
) -> FederalRegisterTopicsComparison:
    """Compare exact source literals while making no cross-source mapping."""

    historical_preferred = {
        _normalized_label(item.literal)
        for item in historical.labels
        if item.role == "preferred"
    }
    historical_all_labels = {
        _normalized_label(item.literal) for item in historical.labels
    }
    current_preferred = {
        _normalized_label(item.name) for item in current.thesaurus
    }
    return FederalRegisterTopicsComparison(
        historical_source_sha256=historical.source_sha256,
        current_source_sha256=current.source_sha256,
        historical_preferred_count=len(historical_preferred),
        current_thesaurus_count=len(current.thesaurus),
        current_ad_hoc_count=len(current.ad_hoc),
        preferred_label_overlap_count=len(
            historical_preferred & current_preferred
        ),
        historical_preferred_only=tuple(
            sorted(historical_preferred - current_preferred)
        ),
        current_preferred_only=tuple(
            sorted(current_preferred - historical_preferred)
        ),
        historical_any_label_overlap_count=len(
            historical_all_labels & current_preferred
        ),
        historical_relation_count=len(historical.relations),
        current_see_also_count=sum(
            len(item.see_also) for item in current.thesaurus
        ),
        current_slug_collision_groups=sum(
            collection == "thesaurus"
            for collection, _slug in current.slug_collisions()
        ),
    )


__all__ = [
    "FEDERAL_REGISTER_TOPICS_API_URL",
    "FEDERAL_REGISTER_TOPICS_PARSER_VERSION",
    "AcquiredFederalRegisterTopics",
    "FederalRegisterTopicLink",
    "FederalRegisterTopicRecord",
    "FederalRegisterTopicsComparison",
    "FederalRegisterTopicsError",
    "FederalRegisterTopicsSnapshot",
    "TopicCollection",
    "capture_federal_register_topics",
    "compare_historical_thesaurus_to_topics",
    "open_federal_register_topics_capture",
    "parse_federal_register_topics_api",
]
