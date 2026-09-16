"""Retain validated OLRC title captures by title and release point.

SpicyDocs acquires and validates the source. This tool retains its exact ZIP
and original HTTP facts together. Cache digests describe retained bytes; they
do not authenticate the publisher or recover an unrecorded capture history.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from spicy_docs.sources.json_input import load_bounded_json
from spicy_docs.sources.uscode import (
    DEFAULT_MAX_ARCHIVE_BYTES,
    ReleasePoint,
    TitleSelection,
    UsCodeSourceError,
    title_xml_locator,
)
from spicy_docs.sources.uscode_acquisition import ZIP_MEDIA_TYPES, UsCodeAcquirer, UsCodeAcquisitionBudget
from spicy_docs.sources.uscode_archive import read_title_archive
from spicy_docs.storage.publication import publish_directory_once, write_bytes_once

from refspec.registry.infrastructure.artifact_serialization import sha256_digest
from refspec.registry.uslm import ExtractionError
from refspec.storage import canonical_json


@dataclass(frozen=True)
class SourceBytes:
    """The exact source payload an extraction ran against."""

    url: str
    zip_bytes: int
    zip_sha256: str
    member: str
    xml_bytes: int
    xml_sha256: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "url": self.url,
            "zipBytes": self.zip_bytes,
            "zipSha256": self.zip_sha256,
            "member": self.member,
            "xmlBytes": self.xml_bytes,
            "xmlSha256": self.xml_sha256,
        }


def fetch_title(title: str, release_point: str, cache: Path) -> tuple[bytes, SourceBytes]:
    """Reuse one fully retained capture or acquire and publish a validated title.

    Old flat cache files are not consulted. Incomplete, contradictory or invalid
    cache entries refuse the run; a competing publisher also refuses explicitly.
    """
    try:
        selection = TitleSelection(ReleasePoint.from_label(release_point.replace("/", "-")), title)
        url = title_xml_locator(selection)
        destination = cache / selection.file_name.removesuffix(".zip")
        if destination.exists():
            with (destination / "archive.zip").open("rb") as stream:
                payload = stream.read(DEFAULT_MAX_ARCHIVE_BYTES + 1)
            result = read_title_archive(payload, selection=selection)
            payload_digest = sha256_digest(payload)
            with (destination / "capture.json").open("rb") as stream:
                encoded = stream.read(16_385)
            evidence = load_bounded_json(
                encoded, source="title cache capture", error_type=ValueError, number_policy="integer", max_bytes=16_384
            )
            if not isinstance(evidence, dict) or any(
                evidence.get(key) != value
                for key, value in {
                    "requestedUrl": url,
                    "resolvedUrl": url,
                    "statusCode": 200,
                    "method": "GET",
                    "contentEncoding": "identity",
                    "byteSize": len(payload),
                    "sha256": payload_digest,
                }.items()
            ):
                raise ExtractionError(
                    "title cache capture evidence differs from the requested source or retained bytes"
                )
            media_type = evidence.get("contentType")
            if "contentType" not in evidence or (media_type is not None and not isinstance(media_type, str)):
                raise ExtractionError("title cache capture Content-Type is not a recorded string or null")
            if (media_type or "").split(";", 1)[0].strip().casefold() not in ZIP_MEDIA_TYPES:
                raise ExtractionError("title cache capture Content-Type differs from the requested format")
            if not isinstance(evidence.get("observedAt"), str) or not evidence["observedAt"]:
                raise ExtractionError("title cache capture evidence has no original observation time")
        else:
            budget = UsCodeAcquisitionBudget(1, DEFAULT_MAX_ARCHIVE_BYTES, 180, 0)
            with UsCodeAcquirer(budget=budget) as acquirer:
                acquired = acquirer.acquire_title(selection)
            result, capture = acquired.result, acquired.capture
            payload = capture.body
            payload_digest = capture.sha256
            evidence = {
                "requestedUrl": capture.requested_url,
                "resolvedUrl": capture.resolved_url,
                "statusCode": capture.status_code,
                "method": capture.method,
                "contentType": capture.content_type,
                "contentEncoding": capture.content_encoding,
                "observedAt": capture.observed_at,
                "byteSize": capture.byte_size,
                "sha256": payload_digest,
            }
            cache.mkdir(parents=True, exist_ok=True)
            with TemporaryDirectory(prefix=".usc-title-", dir=cache) as temporary:
                candidate = Path(temporary) / "capture"
                write_bytes_once(candidate / "archive.zip", payload)
                write_bytes_once(candidate / "capture.json", (canonical_json(evidence) + "\n").encode())
                publish_directory_once(candidate, destination)
    except UsCodeSourceError as error:
        raise ExtractionError(f"title {title}: {error}") from error
    entry = result.entry
    return result.xml_bytes, SourceBytes(
        url,
        len(payload),
        payload_digest.removeprefix("sha256:"),
        entry.name,
        entry.byte_size,
        entry.sha256.removeprefix("sha256:"),
    )
