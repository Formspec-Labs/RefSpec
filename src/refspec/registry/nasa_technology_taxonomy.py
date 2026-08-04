"""Pinned NASA TechPort Technology Taxonomy import for controlled-code mapping.

TechPort (https://techport.nasa.gov/) publishes the NASA Technology Taxonomy
through two JSON endpoints: ``/api/taxonomies`` lists every taxonomy release
and its current status, and ``/api/taxonomies/{taxonomyRootId}`` returns the
release title plus its immediate (level 1) technology-area nodes, each with a
publisher-assigned code (for example ``TX01``) and title. Deeper technology
levels require additional per-node requests that this module does not perform;
only the level 1 roster is captured, parsed, and packaged.

Per the catalog scope decision, this is a versioned taxonomy export used as
mapping input and deterministic metadata for NASA-sourced records. It is not
promoted to a general-subject concept scheme until an evaluation proves
document-subject value, and the instrument and platform branches are excluded
from any future policy-topic mapping regardless of that evaluation's outcome.
No code in this module is treated as a general subject concept.

The API publishes no independent taxonomy revision number beyond a release
title and status string; RefSpec identifies a source snapshot by the official
URL, retrieval time, byte length, and SHA-256 digest. It preserves the
publisher-issued code and node identifier as identity and does not mint or
derive any identifier the publisher does not supply.

Acquisition accepts a local exact capture or an injected fetcher. Importing
this module never opens a network connection, and no scraping provider is
required for the current JSON endpoints.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Literal, Protocol, cast
from urllib.parse import urlsplit

from refspec.registry.infrastructure.controlled_identifier import ControlledIdentifier
from refspec.registry.infrastructure.source_controlled_resource import (
    ResourceUse,
    SourceControlledResourceBundle,
    SourceControlledResourceView,
    build_source_controlled_resource_bundle,
)
from refspec.storage import canonical_json

NASA_TECHPORT_PUBLISHER = "National Aeronautics and Space Administration (NASA), TechPort"
NASA_TECHPORT_IDENTIFIER_AUTHORITY_URI = "https://techport.nasa.gov/"
NASA_TECHPORT_API_BASE = "https://techport.nasa.gov/api"
NASA_TAXONOMY_PACKAGE_VERSION = "nasa-technology-taxonomy-package-v1"

ResourceName = Literal["taxonomyRootIndex", "taxonomyRootChildren"]

_DIGEST = re.compile(r"^sha256:([0-9a-f]{64})$")
_TAXONOMY_CODE = re.compile(r"^TX\d{2}$")
_RELEASE_DESCRIPTOR_FIELDS = frozenset({"taxonomyRootId", "releaseStatus", "title", "releaseStatusString"})
_CHILD_NODE_FIELDS = frozenset(
    {
        "taxonomyNodeId",
        "taxonomyRootId",
        "code",
        "title",
        "level",
        "hasChildren",
        "selected",
        "hasInteriorContent",
    }
)

# These gaps describe what the official source does not publish and what this
# module deliberately declines to model. They travel with every parsed and
# packaged resource so a caller never mistakes silence for a subject claim.
NASA_TAXONOMY_PORTFOLIO_GAPS = (
    (
        "The official /api/taxonomies/{id} endpoint returns only the immediate "
        "(level 1) children of a taxonomy root; deeper technology-area levels "
        "are not captured or modeled by this module."
    ),
    (
        "The API publishes no independent taxonomy revision number beyond the "
        "release title and status; retrieval time and exact source digest are "
        "the available pin."
    ),
    (
        "This module packages taxonomy codes and titles as deterministic "
        "metadata only; no code is treated as a general-subject concept, and "
        "per catalog guidance the instrument and platform branches remain "
        "excluded from any future policy-topic mapping regardless of "
        "evaluation outcome elsewhere."
    ),
)


class NASATaxonomyError(ValueError):
    """Base class for NASA Technology Taxonomy import failures."""


class NASATaxonomyAcquisitionError(NASATaxonomyError):
    """Exact official source bytes could not be acquired safely."""


class NASATaxonomySourceDriftError(NASATaxonomyError):
    """A TechPort taxonomy source no longer matches the reviewed structure or pin."""


class NASATaxonomyPackageError(NASATaxonomyError):
    """A packaged taxonomy bundle differs from its exact source or declared use."""


@dataclass(frozen=True, slots=True)
class NASATaxonomySource:
    """One official TechPort taxonomy endpoint."""

    resource_name: ResourceName
    use: ResourceUse
    source_url: str
    filename: str
    expected_count: int
    taxonomy_root_id: int | None = None

    def __post_init__(self) -> None:
        parsed = urlsplit(self.source_url)
        if parsed.scheme != "https" or parsed.hostname != "techport.nasa.gov":
            raise NASATaxonomyAcquisitionError("source_url must be an official HTTPS techport.nasa.gov URL")
        if parsed.username is not None or parsed.password is not None:
            raise NASATaxonomyAcquisitionError("source_url must not contain credentials")
        if not self.filename or Path(self.filename).name != self.filename:
            raise NASATaxonomyAcquisitionError("filename must be one plain path component")
        if self.expected_count <= 0:
            raise NASATaxonomyAcquisitionError("expected_count must be positive")
        if self.resource_name == "taxonomyRootChildren":
            if self.taxonomy_root_id is None or self.taxonomy_root_id <= 0:
                raise NASATaxonomyAcquisitionError("taxonomyRootChildren source must declare a positive root id")
        elif self.taxonomy_root_id is not None:
            raise NASATaxonomyAcquisitionError("taxonomyRootIndex source must not declare a taxonomy_root_id")


NASA_TAXONOMY_ROOT_INDEX = NASATaxonomySource(
    resource_name="taxonomyRootIndex",
    use="deterministicMetadata",
    source_url=f"{NASA_TECHPORT_API_BASE}/taxonomies",
    filename="taxonomy-roots.json",
    expected_count=1,
)
NASA_TAXONOMY_ROOT_CHILDREN = NASATaxonomySource(
    resource_name="taxonomyRootChildren",
    use="deterministicMetadata",
    source_url=f"{NASA_TECHPORT_API_BASE}/taxonomies/8817",
    filename="taxonomy-8817-children.json",
    expected_count=17,
    taxonomy_root_id=8817,
)


@dataclass(frozen=True, slots=True)
class NASATaxonomySnapshotPin:
    """Exact identity of one official taxonomy response."""

    source: NASATaxonomySource
    retrieved_at: str
    expected_sha256: str
    expected_byte_length: int
    publisher_release: str | None = None

    def __post_init__(self) -> None:
        if _DIGEST.fullmatch(self.expected_sha256) is None:
            raise NASATaxonomyAcquisitionError("expected_sha256 must be a lowercase sha256:<64 hex> digest")
        if self.expected_byte_length <= 0:
            raise NASATaxonomyAcquisitionError("expected_byte_length must be positive")
        if not self.retrieved_at:
            raise NASATaxonomyAcquisitionError("retrieved_at must not be empty")


# Captured 2026-08-03 with a live GET against the official endpoints. Both
# byte strings are pinned exactly; any drift fails closed at parse time.
NASA_TAXONOMY_ROOT_INDEX_2026_08_03 = NASATaxonomySnapshotPin(
    source=NASA_TAXONOMY_ROOT_INDEX,
    retrieved_at="2026-08-03T19:03:21Z",
    expected_sha256="sha256:c0c4b8e154f337be41f59b6b61bdd3b6b673b33bd49e5904b780e640391cbb07",
    expected_byte_length=143,
)
NASA_TAXONOMY_ROOT_CHILDREN_2026_08_03 = NASATaxonomySnapshotPin(
    source=NASA_TAXONOMY_ROOT_CHILDREN,
    retrieved_at="2026-08-03T19:03:22Z",
    expected_sha256="sha256:4e0ed6f5edee5b7e80c8789e4c3ef39c337a1f27de4cddede431feb94d314932",
    expected_byte_length=3_408,
    publisher_release="2024 NASA Technology Taxonomy",
)


@dataclass(frozen=True, slots=True)
class FetchedNASATaxonomyResponse:
    """Provider-independent response returned by an injected fetcher."""

    body: bytes
    status_code: int
    content_type: str
    resolved_url: str


class NASATaxonomyFetcher(Protocol):
    """Small transport boundary for official TechPort taxonomy endpoints."""

    def fetch(self, source_url: str, *, timeout_seconds: float) -> FetchedNASATaxonomyResponse:
        """Fetch one response while preserving its exact body bytes."""


AcquisitionMode = Literal["cache", "local", "fetcher"]


@dataclass(frozen=True, slots=True)
class AcquiredNASATaxonomySource:
    """One verified source object in the content-addressed store."""

    pin: NASATaxonomySnapshotPin
    path: Path
    sha256: str
    byte_length: int
    source_url: str
    resolved_url: str | None
    content_type: str
    acquisition_mode: AcquisitionMode
    cache_hit: bool
    local_source_path: Path | None


@dataclass(frozen=True, slots=True)
class NASATaxonomyReleaseDescriptor:
    """One taxonomy release as listed by the official root index."""

    taxonomy_root_id: int
    release_status: str
    title: str
    release_status_string: str


@dataclass(frozen=True, slots=True)
class ParsedNASATaxonomyRootIndex:
    """A parsed, digest-pinned listing of every published taxonomy release."""

    source: NASATaxonomySource
    retrieved_at: str
    source_sha256: str
    source_byte_length: int
    roots: tuple[NASATaxonomyReleaseDescriptor, ...]

    def by_root_id(self) -> dict[int, NASATaxonomyReleaseDescriptor]:
        """Index releases by their publisher-issued taxonomy root id."""

        return {root.taxonomy_root_id: root for root in self.roots}


@dataclass(frozen=True, slots=True)
class NASATaxonomyNode:
    """One top-level (level 1) technology-area node and its identifiers."""

    resource_name: ResourceName
    use: ResourceUse
    publisher_label: str
    level: int
    has_children: bool
    has_interior_content: bool
    source_url: str
    identifiers: tuple[ControlledIdentifier, ...]
    is_general_subject_concept: bool = False


@dataclass(frozen=True, slots=True)
class ParsedNASATaxonomyChildren:
    """A parsed, digest-pinned roster of one taxonomy root's top-level nodes."""

    source: NASATaxonomySource
    retrieved_at: str
    source_sha256: str
    source_byte_length: int
    taxonomy_root_id: int
    publisher_release: str
    release_status: str
    nodes: tuple[NASATaxonomyNode, ...]
    gaps: tuple[str, ...]

    def by_code(self) -> dict[str, NASATaxonomyNode]:
        """Index each node's ``code`` while retaining all other identifiers."""

        result: dict[str, NASATaxonomyNode] = {}
        for entry in self.nodes:
            matches = [identifier for identifier in entry.identifiers if identifier.kind == "taxonomyNodeCode"]
            if len(matches) != 1:
                raise NASATaxonomySourceDriftError("taxonomy node must retain exactly one taxonomyNodeCode")
            result[matches[0].value] = entry
        return result


@dataclass(frozen=True, slots=True)
class NASATaxonomyPortfolio:
    """The cross-checked release index and top-level node roster."""

    root_index: ParsedNASATaxonomyRootIndex
    children: ParsedNASATaxonomyChildren
    gaps: tuple[str, ...]


def sha256_digest(payload: bytes) -> str:
    """Return the canonical RefSpec SHA-256 spelling."""

    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _validate_resolved_url(value: str) -> None:
    parsed = urlsplit(value)
    if parsed.scheme != "https" or parsed.hostname != "techport.nasa.gov":
        raise NASATaxonomyAcquisitionError("fetcher resolved_url must remain on official HTTPS techport.nasa.gov")
    if parsed.username is not None or parsed.password is not None:
        raise NASATaxonomyAcquisitionError("fetcher resolved_url must not contain credentials")


def _verify_payload(payload: bytes, pin: NASATaxonomySnapshotPin, *, location: str) -> tuple[str, int]:
    byte_length = len(payload)
    if byte_length != pin.expected_byte_length:
        raise NASATaxonomySourceDriftError(
            f"{location} byte length drift: expected {pin.expected_byte_length}, got {byte_length}"
        )
    actual_sha256 = sha256_digest(payload)
    if actual_sha256 != pin.expected_sha256:
        raise NASATaxonomySourceDriftError(
            f"{location} digest drift: expected {pin.expected_sha256}, got {actual_sha256}"
        )
    try:
        json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise NASATaxonomySourceDriftError(f"{location} is not valid JSON") from error
    return actual_sha256, byte_length


def _verify_existing(path: Path, pin: NASATaxonomySnapshotPin) -> AcquiredNASATaxonomySource:
    if path.is_symlink() or not path.is_file():
        raise NASATaxonomyAcquisitionError(f"content-addressed target is not a regular file: {path}")
    actual_sha256, byte_length = _verify_payload(
        path.read_bytes(),
        pin,
        location="cached NASA taxonomy source",
    )
    return AcquiredNASATaxonomySource(
        pin=pin,
        path=path,
        sha256=actual_sha256,
        byte_length=byte_length,
        source_url=pin.source.source_url,
        resolved_url=None,
        content_type="application/json",
        acquisition_mode="cache",
        cache_hit=True,
        local_source_path=None,
    )


def _publish_payload(
    payload: bytes,
    pin: NASATaxonomySnapshotPin,
    final_path: Path,
    *,
    content_type: str,
    acquisition_mode: Literal["local", "fetcher"],
    resolved_url: str | None,
    local_source_path: Path | None,
) -> AcquiredNASATaxonomySource:
    actual_sha256, byte_length = _verify_payload(
        payload,
        pin,
        location=f"{acquisition_mode} NASA taxonomy source",
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
        return AcquiredNASATaxonomySource(
            pin=pin,
            path=final_path,
            sha256=actual_sha256,
            byte_length=byte_length,
            source_url=pin.source.source_url,
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


def acquire_nasa_taxonomy_source(
    pin: NASATaxonomySnapshotPin,
    store_dir: Path,
    *,
    source_path: Path | None = None,
    fetcher: NASATaxonomyFetcher | None = None,
    timeout_seconds: float = 30.0,
) -> AcquiredNASATaxonomySource:
    """Acquire one exact taxonomy response through a provider-neutral boundary."""

    if timeout_seconds <= 0:
        raise NASATaxonomyAcquisitionError("timeout_seconds must be positive")
    if source_path is not None and fetcher is not None:
        raise NASATaxonomyAcquisitionError("provide source_path or fetcher, not both")
    digest_hex = cast(re.Match[str], _DIGEST.fullmatch(pin.expected_sha256)).group(1)
    final_path = Path(store_dir) / "sha256" / digest_hex / pin.source.filename
    if final_path.exists() or final_path.is_symlink():
        return _verify_existing(final_path, pin)

    if source_path is not None:
        local_path = Path(source_path)
        if local_path.is_symlink() or not local_path.is_file():
            raise NASATaxonomyAcquisitionError(f"local NASA taxonomy source is not a regular file: {local_path}")
        return _publish_payload(
            local_path.read_bytes(),
            pin,
            final_path,
            content_type="application/json",
            acquisition_mode="local",
            resolved_url=None,
            local_source_path=local_path.resolve(),
        )

    if fetcher is None:
        raise NASATaxonomyAcquisitionError(
            "NASA taxonomy source is not cached; provide source_path or an injected fetcher"
        )
    fetched = fetcher.fetch(pin.source.source_url, timeout_seconds=timeout_seconds)
    if fetched.status_code != 200:
        raise NASATaxonomyAcquisitionError(f"could not acquire {pin.source.source_url}: HTTP {fetched.status_code}")
    _validate_resolved_url(fetched.resolved_url)
    media_type = fetched.content_type.partition(";")[0].strip().lower()
    if media_type != "application/json":
        raise NASATaxonomySourceDriftError(f"NASA taxonomy content type drifted to {fetched.content_type!r}")
    return _publish_payload(
        fetched.body,
        pin,
        final_path,
        content_type=fetched.content_type,
        acquisition_mode="fetcher",
        resolved_url=fetched.resolved_url,
        local_source_path=None,
    )


def _parse_release_descriptor(record: object, *, label: str) -> NASATaxonomyReleaseDescriptor:
    if not isinstance(record, Mapping) or set(record) != _RELEASE_DESCRIPTOR_FIELDS:
        raise NASATaxonomySourceDriftError(
            f"{label} fields drifted: {sorted(record) if isinstance(record, Mapping) else type(record)}"
        )
    root_id = record["taxonomyRootId"]
    if not isinstance(root_id, int) or isinstance(root_id, bool) or root_id <= 0:
        raise NASATaxonomySourceDriftError(f"{label}.taxonomyRootId must be a positive integer")
    release_status = record["releaseStatus"]
    release_status_string = record["releaseStatusString"]
    title = record["title"]
    for value, field in (
        (release_status, "releaseStatus"),
        (release_status_string, "releaseStatusString"),
        (title, "title"),
    ):
        if not isinstance(value, str) or not value.strip() or value != value.strip():
            raise NASATaxonomySourceDriftError(f"{label}.{field} must be non-empty trimmed text")
    return NASATaxonomyReleaseDescriptor(
        taxonomy_root_id=root_id,
        release_status=cast(str, release_status),
        title=cast(str, title),
        release_status_string=cast(str, release_status_string),
    )


def parse_nasa_taxonomy_root_index(acquired: AcquiredNASATaxonomySource) -> ParsedNASATaxonomyRootIndex:
    """Parse the exact list of published taxonomy releases."""

    if acquired.pin.source.resource_name != "taxonomyRootIndex":
        raise NASATaxonomySourceDriftError("acquired source is not the taxonomy root index")
    payload = acquired.path.read_bytes()
    _verify_payload(payload, acquired.pin, location="parsed NASA taxonomy root index")
    try:
        root = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise NASATaxonomySourceDriftError("NASA taxonomy root index payload is not valid JSON") from error
    if not isinstance(root, Mapping) or set(root) != {"taxonomyRoots"}:
        raise NASATaxonomySourceDriftError(
            f"NASA taxonomy root index fields drifted: {sorted(root) if isinstance(root, Mapping) else type(root)}"
        )
    raw_roots = root["taxonomyRoots"]
    if not isinstance(raw_roots, list):
        raise NASATaxonomySourceDriftError("NASA taxonomy root index taxonomyRoots must be an array")
    if len(raw_roots) != acquired.pin.source.expected_count:
        raise NASATaxonomySourceDriftError(
            f"taxonomy root index count drift: expected {acquired.pin.source.expected_count}, parsed {len(raw_roots)}"
        )
    roots = tuple(
        _parse_release_descriptor(record, label=f"taxonomyRoots[{ordinal}]") for ordinal, record in enumerate(raw_roots)
    )
    if len({root.taxonomy_root_id for root in roots}) != len(roots):
        raise NASATaxonomySourceDriftError("NASA taxonomy root index contains a duplicate taxonomyRootId")
    return ParsedNASATaxonomyRootIndex(
        source=acquired.pin.source,
        retrieved_at=acquired.pin.retrieved_at,
        source_sha256=acquired.sha256,
        source_byte_length=acquired.byte_length,
        roots=roots,
    )


def parse_nasa_taxonomy_children(acquired: AcquiredNASATaxonomySource) -> ParsedNASATaxonomyChildren:
    """Parse the exact level 1 technology-area nodes of one taxonomy root."""

    if acquired.pin.source.resource_name != "taxonomyRootChildren":
        raise NASATaxonomySourceDriftError("acquired source is not a taxonomy root children response")
    payload = acquired.path.read_bytes()
    _verify_payload(payload, acquired.pin, location="parsed NASA taxonomy children")
    try:
        root = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise NASATaxonomySourceDriftError("NASA taxonomy children payload is not valid JSON") from error
    if not isinstance(root, Mapping) or set(root) != {"taxonomyRootId", "taxonomyRoot", "children"}:
        raise NASATaxonomySourceDriftError(
            f"NASA taxonomy children fields drifted: {sorted(root) if isinstance(root, Mapping) else type(root)}"
        )

    top_root_id = root["taxonomyRootId"]
    if not isinstance(top_root_id, int) or isinstance(top_root_id, bool):
        raise NASATaxonomySourceDriftError("NASA taxonomy children taxonomyRootId must be an integer")
    if top_root_id != acquired.pin.source.taxonomy_root_id:
        raise NASATaxonomySourceDriftError(
            f"NASA taxonomy children taxonomyRootId drift: expected {acquired.pin.source.taxonomy_root_id}, got {top_root_id}"
        )
    release = _parse_release_descriptor(root["taxonomyRoot"], label="taxonomyRoot")
    if release.taxonomy_root_id != top_root_id:
        raise NASATaxonomySourceDriftError(
            "NASA taxonomy children taxonomyRoot.taxonomyRootId does not match the envelope"
        )
    if acquired.pin.publisher_release is not None and release.title != acquired.pin.publisher_release:
        raise NASATaxonomySourceDriftError(
            f"NASA taxonomy children release title drift: expected {acquired.pin.publisher_release!r}, got {release.title!r}"
        )

    raw_children = root["children"]
    if not isinstance(raw_children, list):
        raise NASATaxonomySourceDriftError("NASA taxonomy children must be an array")
    if len(raw_children) != acquired.pin.source.expected_count:
        raise NASATaxonomySourceDriftError(
            f"taxonomy children count drift: expected {acquired.pin.source.expected_count}, parsed {len(raw_children)}"
        )

    nodes: list[NASATaxonomyNode] = []
    for ordinal, entry in enumerate(raw_children):
        label = f"children[{ordinal}]"
        if not isinstance(entry, Mapping) or set(entry) != {"content"}:
            raise NASATaxonomySourceDriftError(
                f"{label} fields drifted: {sorted(entry) if isinstance(entry, Mapping) else type(entry)}"
            )
        record = entry["content"]
        if not isinstance(record, Mapping) or set(record) != _CHILD_NODE_FIELDS:
            raise NASATaxonomySourceDriftError(
                f"{label}.content fields drifted: {sorted(record) if isinstance(record, Mapping) else type(record)}"
            )

        code = record["code"]
        title = record["title"]
        if not isinstance(code, str) or _TAXONOMY_CODE.fullmatch(code) is None:
            raise NASATaxonomySourceDriftError(f"{label}.content has malformed publisher code")
        if not isinstance(title, str) or not title.strip() or title != title.strip():
            raise NASATaxonomySourceDriftError(f"{label}.content has malformed publisher title")

        node_id = record["taxonomyNodeId"]
        if not isinstance(node_id, int) or isinstance(node_id, bool) or node_id <= 0:
            raise NASATaxonomySourceDriftError(f"{label}.content.taxonomyNodeId must be a positive integer")
        node_root_id = record["taxonomyRootId"]
        if node_root_id != top_root_id:
            raise NASATaxonomySourceDriftError(f"{label}.content.taxonomyRootId does not match the envelope")
        level = record["level"]
        if level != 1:
            raise NASATaxonomySourceDriftError(
                f"{label}.content.level {level!r} is not supported; this module only parses top-level (level 1) nodes"
            )
        for flag_field in ("hasChildren", "selected", "hasInteriorContent"):
            if not isinstance(record[flag_field], bool):
                raise NASATaxonomySourceDriftError(f"{label}.content.{flag_field} must be a boolean")

        identifiers = (
            ControlledIdentifier(
                value=code,
                kind="taxonomyNodeCode",
                authority_uri=NASA_TECHPORT_IDENTIFIER_AUTHORITY_URI,
                source_uri=acquired.pin.source.source_url,
                observed_at=acquired.pin.retrieved_at,
                effective_at=None,
                source_digest=acquired.sha256,
            ),
            ControlledIdentifier(
                value=str(node_id),
                kind="publisherRecordId",
                authority_uri=NASA_TECHPORT_IDENTIFIER_AUTHORITY_URI,
                source_uri=acquired.pin.source.source_url,
                observed_at=acquired.pin.retrieved_at,
                effective_at=None,
                source_digest=acquired.sha256,
            ),
        )
        nodes.append(
            NASATaxonomyNode(
                resource_name=acquired.pin.source.resource_name,
                use=acquired.pin.source.use,
                publisher_label=title,
                level=cast(int, level),
                has_children=cast(bool, record["hasChildren"]),
                has_interior_content=cast(bool, record["hasInteriorContent"]),
                source_url=acquired.pin.source.source_url,
                identifiers=identifiers,
            )
        )

    codes = [node.identifiers[0].value for node in nodes]
    if len(set(codes)) != len(codes):
        raise NASATaxonomySourceDriftError("NASA taxonomy children contain a duplicate publisher code")
    node_ids = [node.identifiers[1].value for node in nodes]
    if len(set(node_ids)) != len(node_ids):
        raise NASATaxonomySourceDriftError("NASA taxonomy children contain a duplicate taxonomyNodeId")
    if len({node.publisher_label for node in nodes}) != len(nodes):
        raise NASATaxonomySourceDriftError("NASA taxonomy children contain a duplicate publisher label")

    return ParsedNASATaxonomyChildren(
        source=acquired.pin.source,
        retrieved_at=acquired.pin.retrieved_at,
        source_sha256=acquired.sha256,
        source_byte_length=acquired.byte_length,
        taxonomy_root_id=top_root_id,
        publisher_release=release.title,
        release_status=release.release_status,
        nodes=tuple(nodes),
        gaps=NASA_TAXONOMY_PORTFOLIO_GAPS,
    )


def assemble_nasa_taxonomy_portfolio(
    root_index: ParsedNASATaxonomyRootIndex,
    children: ParsedNASATaxonomyChildren,
) -> NASATaxonomyPortfolio:
    """Cross-check the release index against the captured node roster."""

    release = root_index.by_root_id().get(children.taxonomy_root_id)
    if release is None:
        raise NASATaxonomySourceDriftError(f"taxonomy root {children.taxonomy_root_id} is not listed by the root index")
    if release.title != children.publisher_release:
        raise NASATaxonomySourceDriftError(
            f"taxonomy root {children.taxonomy_root_id} title drift: "
            f"index says {release.title!r}, children say {children.publisher_release!r}"
        )
    if release.release_status != children.release_status:
        raise NASATaxonomySourceDriftError(
            f"taxonomy root {children.taxonomy_root_id} status drift: "
            f"index says {release.release_status!r}, children say {children.release_status!r}"
        )
    return NASATaxonomyPortfolio(
        root_index=root_index,
        children=children,
        gaps=NASA_TAXONOMY_PORTFOLIO_GAPS,
    )


# --- Development-only source-controlled package -----------------------------


@dataclass(frozen=True, slots=True)
class NASATechnologyTaxonomyPackageSpec:
    """Pinned identity and use of the NASA Technology Taxonomy package."""

    resource_id: str
    title: str
    root_index_pin: NASATaxonomySnapshotPin
    children_pin: NASATaxonomySnapshotPin
    uses: tuple[ResourceUse, ...]
    known_gaps: tuple[str, ...]
    expected_logical_digest: str

    def __post_init__(self) -> None:
        if not self.resource_id or not self.title:
            raise NASATaxonomyPackageError("package identity fields must not be empty")
        if not self.uses:
            raise NASATaxonomyPackageError("package must declare at least one eligible use")
        if _DIGEST.fullmatch(self.expected_logical_digest) is None:
            raise NASATaxonomyPackageError("expected_logical_digest must be a SHA-256 digest")


# This package digest is an external pin over the deterministic logical
# package. It is updated only when the exact source or packaging rules change.
NASA_TECHNOLOGY_TAXONOMY_PACKAGE_SPEC = NASATechnologyTaxonomyPackageSpec(
    resource_id="nasa-technology-taxonomy-8817-top-level-2026-08-03",
    title="NASA TechPort 2024 Technology Taxonomy, top-level areas (TX01-TX17), captured 2026-08-03",
    root_index_pin=NASA_TAXONOMY_ROOT_INDEX_2026_08_03,
    children_pin=NASA_TAXONOMY_ROOT_CHILDREN_2026_08_03,
    uses=("mappingReference", "deterministicMetadata"),
    known_gaps=NASA_TAXONOMY_PORTFOLIO_GAPS,
    expected_logical_digest="sha256:28d1e95113e6b90d5baae7dac2599dfa6ffa6fd90b25b67d3d0a229ed84ffcc5",
)


def _parse_exact_children_source(pin: NASATaxonomySnapshotPin, payload: bytes) -> ParsedNASATaxonomyChildren:
    with tempfile.TemporaryDirectory(prefix="refspec-nasa-taxonomy-") as temporary:
        root = Path(temporary)
        source_path = root / pin.source.filename
        source_path.write_bytes(payload)
        acquired = acquire_nasa_taxonomy_source(pin, root / "store", source_path=source_path)
        return parse_nasa_taxonomy_children(acquired)


def _parse_exact_root_index_source(pin: NASATaxonomySnapshotPin, payload: bytes) -> ParsedNASATaxonomyRootIndex:
    with tempfile.TemporaryDirectory(prefix="refspec-nasa-taxonomy-") as temporary:
        root = Path(temporary)
        source_path = root / pin.source.filename
        source_path.write_bytes(payload)
        acquired = acquire_nasa_taxonomy_source(pin, root / "store", source_path=source_path)
        return parse_nasa_taxonomy_root_index(acquired)


def _observation_id(*, source_path: str, identifiers: Sequence[Mapping[str, Any]]) -> str:
    identity = {
        "packageVersion": NASA_TAXONOMY_PACKAGE_VERSION,
        "resourceId": NASA_TECHNOLOGY_TAXONOMY_PACKAGE_SPEC.resource_id,
        "sourceArtifact": NASA_TAXONOMY_ROOT_CHILDREN.source_url,
        "sourcePath": source_path,
        "identifiers": [
            {
                "value": identifier["value"],
                "kind": identifier["kind"],
                "authorityUri": identifier["authorityUri"],
            }
            for identifier in identifiers
        ],
    }
    digest = hashlib.sha256(canonical_json(identity).encode("utf-8")).hexdigest()
    return f"urn:ref:source-observation:{NASA_TECHNOLOGY_TAXONOMY_PACKAGE_SPEC.resource_id}:{digest}"


def _identifier_payload(*, identifier: ControlledIdentifier, source_path: str) -> dict[str, Any]:
    return {
        "value": identifier.value,
        "kind": identifier.kind,
        "authorityUri": identifier.authority_uri,
        "sourceUri": identifier.source_uri,
        "sourcePath": source_path,
        "observedAt": identifier.observed_at,
        "sourceDigest": identifier.source_digest,
    }


def _observations(children: ParsedNASATaxonomyChildren) -> tuple[Mapping[str, Any], ...]:
    result: list[Mapping[str, Any]] = []
    for ordinal, node in enumerate(children.nodes):
        if node.resource_name != "taxonomyRootChildren" or node.use not in NASA_TECHNOLOGY_TAXONOMY_PACKAGE_SPEC.uses:
            raise NASATaxonomyPackageError(f"taxonomy node {ordinal} has an incompatible resource or use")
        if node.is_general_subject_concept:
            raise NASATaxonomyPackageError(f"taxonomy node {ordinal} must not claim general subject concept status")
        source_path = f"$.children[{ordinal}].content"
        identifiers = tuple(
            _identifier_payload(identifier=identifier, source_path=source_path) for identifier in node.identifiers
        )
        result.append(
            {
                "id": _observation_id(source_path=source_path, identifiers=identifiers),
                "sourceArtifact": NASA_TAXONOMY_ROOT_CHILDREN.source_url,
                "sourcePath": source_path,
                # This ordinal is a source locator only. Publisher identity is
                # preserved in identifiers and never derived from row order.
                "sourceOrdinal": ordinal,
                "labels": [
                    {
                        "value": node.publisher_label,
                        "language": "en",
                        "role": "preferred",
                    }
                ],
                "identifiers": list(identifiers),
                "uses": list(NASA_TECHNOLOGY_TAXONOMY_PACKAGE_SPEC.uses),
                "conceptIdentityClaimed": False,
            }
        )
    return tuple(result)


def build_nasa_technology_taxonomy_package(
    root_index_path: Path,
    children_path: Path,
) -> SourceControlledResourceBundle:
    """Build one exact, development-only NASA Technology Taxonomy package."""

    spec = NASA_TECHNOLOGY_TAXONOMY_PACKAGE_SPEC
    root_index_file = Path(root_index_path)
    children_file = Path(children_path)
    for path in (root_index_file, children_file):
        if path.is_symlink() or not path.is_file():
            raise NASATaxonomyPackageError(f"NASA taxonomy source is not a regular file: {path}")

    root_index_bytes = root_index_file.read_bytes()
    children_bytes = children_file.read_bytes()
    root_index = _parse_exact_root_index_source(spec.root_index_pin, root_index_bytes)
    children = _parse_exact_children_source(spec.children_pin, children_bytes)
    assemble_nasa_taxonomy_portfolio(root_index, children)

    return build_source_controlled_resource_bundle(
        resource_id=spec.resource_id,
        title=spec.title,
        resource_kind="controlledCodeList",
        identity_status="publisherIdentifiersPreserved",
        uses=spec.uses,
        captured_at=spec.children_pin.retrieved_at,
        observations=_observations(children),
        source_artifacts={
            NASA_TAXONOMY_ROOT_INDEX.source_url: root_index_bytes,
            NASA_TAXONOMY_ROOT_CHILDREN.source_url: children_bytes,
        },
        source_observed_count=len(children.nodes),
        gaps=[{"kind": "catalogScopeGap", "reason": gap} for gap in spec.known_gaps],
    )


@dataclass(frozen=True, slots=True)
class NASATechnologyTaxonomyView:
    """A package reopened only after its complete closed set verifies."""

    package: SourceControlledResourceView
    nodes_by_code: Mapping[str, Mapping[str, Any]]

    @classmethod
    def open(cls, path: Path) -> NASATechnologyTaxonomyView:
        """Open the known NASA Technology Taxonomy package and rebuild it."""

        package = SourceControlledResourceView.open(path)
        spec = NASA_TECHNOLOGY_TAXONOMY_PACKAGE_SPEC
        resource_id = package.resource_manifest.get("resourceId")
        if resource_id != spec.resource_id:
            raise NASATaxonomyPackageError(f"unknown NASA taxonomy resource {resource_id!r}")
        if package.logical_digest != spec.expected_logical_digest:
            raise NASATaxonomyPackageError(f"{resource_id} logical digest differs from its external pin")

        root_index_bytes = package.source_artifact_bytes(NASA_TAXONOMY_ROOT_INDEX.source_url)
        children_bytes = package.source_artifact_bytes(NASA_TAXONOMY_ROOT_CHILDREN.source_url)
        for payload, pin in (
            (root_index_bytes, spec.root_index_pin),
            (children_bytes, spec.children_pin),
        ):
            if len(payload) != pin.expected_byte_length or sha256_digest(payload) != pin.expected_sha256:
                raise NASATaxonomyPackageError(f"{resource_id} retained source differs from its dated pin")

        root_index = _parse_exact_root_index_source(spec.root_index_pin, root_index_bytes)
        children = _parse_exact_children_source(spec.children_pin, children_bytes)
        assemble_nasa_taxonomy_portfolio(root_index, children)

        rebuilt = build_source_controlled_resource_bundle(
            resource_id=spec.resource_id,
            title=spec.title,
            resource_kind="controlledCodeList",
            identity_status="publisherIdentifiersPreserved",
            uses=spec.uses,
            captured_at=spec.children_pin.retrieved_at,
            observations=_observations(children),
            source_artifacts={
                NASA_TAXONOMY_ROOT_INDEX.source_url: root_index_bytes,
                NASA_TAXONOMY_ROOT_CHILDREN.source_url: children_bytes,
            },
            source_observed_count=len(children.nodes),
            gaps=[{"kind": "catalogScopeGap", "reason": gap} for gap in spec.known_gaps],
        )
        if rebuilt.artifact_bytes() != {
            relative_path: (Path(path) / relative_path).read_bytes() for relative_path in rebuilt.artifact_bytes()
        }:
            raise NASATaxonomyPackageError(f"{resource_id} package differs from its deterministic NASA taxonomy build")

        by_code: dict[str, Mapping[str, Any]] = {}
        for ordinal, observation in enumerate(package.observations):
            matches = [
                identifier for identifier in observation["identifiers"] if identifier["kind"] == "taxonomyNodeCode"
            ]
            if len(matches) != 1:
                raise NASATaxonomyPackageError(f"{resource_id} observation {ordinal} lacks one publisher code")
            code = matches[0]["value"]
            if code in by_code:
                raise NASATaxonomyPackageError(f"{resource_id} repeats publisher code {code!r}")
            by_code[code] = observation
        return cls(package=package, nodes_by_code=MappingProxyType(by_code))

    def lookup_code(self, value: str) -> Mapping[str, Any] | None:
        """Return one exact source observation by publisher taxonomy code."""

        return self.nodes_by_code.get(value)


__all__ = [
    "NASA_TAXONOMY_PORTFOLIO_GAPS",
    "NASA_TAXONOMY_ROOT_CHILDREN",
    "NASA_TAXONOMY_ROOT_CHILDREN_2026_08_03",
    "NASA_TAXONOMY_ROOT_INDEX",
    "NASA_TAXONOMY_ROOT_INDEX_2026_08_03",
    "NASA_TECHNOLOGY_TAXONOMY_PACKAGE_SPEC",
    "NASA_TECHPORT_API_BASE",
    "NASA_TECHPORT_IDENTIFIER_AUTHORITY_URI",
    "NASA_TECHPORT_PUBLISHER",
    "AcquiredNASATaxonomySource",
    "FetchedNASATaxonomyResponse",
    "NASATaxonomyAcquisitionError",
    "NASATaxonomyError",
    "NASATaxonomyFetcher",
    "NASATaxonomyNode",
    "NASATaxonomyPackageError",
    "NASATaxonomyPortfolio",
    "NASATaxonomyReleaseDescriptor",
    "NASATaxonomySnapshotPin",
    "NASATaxonomySource",
    "NASATaxonomySourceDriftError",
    "NASATechnologyTaxonomyPackageSpec",
    "NASATechnologyTaxonomyView",
    "ParsedNASATaxonomyChildren",
    "ParsedNASATaxonomyRootIndex",
    "acquire_nasa_taxonomy_source",
    "assemble_nasa_taxonomy_portfolio",
    "build_nasa_technology_taxonomy_package",
    "parse_nasa_taxonomy_children",
    "parse_nasa_taxonomy_root_index",
    "sha256_digest",
]
