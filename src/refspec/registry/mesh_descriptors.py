"""Streaming, source-faithful capture of MeSH descriptor records.

The National Library of Medicine (NLM) publishes Medical Subject Headings
(MeSH) as several separate XML files. The 2026 descriptor file
(``desc2026.xml``) contains 31,110 ``DescriptorRecord`` elements; a much
larger, separately published Supplemental Concept Record file holds roughly
324,000 additional records. This module reads descriptors only. A
``SupplementalRecordSet`` root, or any other unexpected root, fails closed
instead of silently degrading, so the 324k supplemental concepts can never
enter a descriptor table through this module.

Every MeSH descriptor already carries a real, NLM-issued stable identifier
(``DescriptorUI``, e.g. ``D000001``) and a published linked-data URI
(``https://id.nlm.nih.gov/mesh/<DescriptorUI>``, verified live). This module
preserves that publisher identity directly as a ``ControlledIdentifier``; it
never mints one of its own, matching the project's identifier policy.

The RefSpec source catalog lists MeSH descriptors as a "Pilot descriptors"
specialist health-subject module -- a research recommendation, not an
adoption claim. Every package this module builds is therefore a
development-only, candidate ``sourceTermSnapshot``: it can support search
expansion and source-assigned evidence, but it never claims concept identity
and never authorizes accepted output. Use of MeSH data requires attribution
to the National Library of Medicine (see ``MESH_ATTRIBUTION_NOTICE``).

The production descriptor file is very large (over 300 MB for the 2026
release), so the XML walk uses ``xml.etree.ElementTree.iterparse`` and
releases each ``DescriptorRecord`` element's memory as soon as it is read;
parsing memory therefore stays bounded by one record, not by file size. The
exact SHA-256 digest of the source can only be known once every byte has
streamed past, so this module hashes the stream as it is consumed and
attaches that digest to each descriptor's identifier only after the walk
completes -- the resulting descriptor rows are still an exact, verifiable
capture of the source bytes.

Importing this module never opens a network connection. Acquiring the real
annual release is the caller's responsibility (the NLM download page is
``MESH_DOWNLOAD_PAGE_URL``); this module only parses and packages bytes it
is given.
"""

from __future__ import annotations

import hashlib
import io
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import IO, Any
from xml.etree import ElementTree

from refspec.registry.infrastructure.controlled_identifier import (
    ControlledIdentifier,
    identifier_values,
    validate_identifier_date,
)
from refspec.registry.infrastructure.source_controlled_resource import (
    SourceControlledResourceBundle,
    SourceControlledResourceView,
    build_source_controlled_resource_bundle,
)

MESH_DOWNLOAD_PAGE_URL = "https://www.nlm.nih.gov/databases/download/mesh.html"
MESH_DESCRIPTOR_AUTHORITY_URI = "https://id.nlm.nih.gov/mesh/"
MESH_DESCRIPTOR_UI_KIND = "publisherDescriptorUI"
MESH_ATTRIBUTION_NOTICE = (
    "Medical Subject Headings (MeSH) descriptor data courtesy of the U.S. "
    "National Library of Medicine. NLM attribution is required."
)

# Documented facts from the official 2026 release; informational only. This
# module never enforces these totals against a real capture because the
# production file spans multiple release years and this module never buffers
# the whole thing to count it twice.
MESH_2026_DESCRIPTOR_COUNT = 31_110
MESH_2026_QUALIFIER_COUNT = 76
MESH_2026_SUPPLEMENTAL_CONCEPT_COUNT = 324_049

_DESCRIPTOR_RECORD_SET_TAG = "DescriptorRecordSet"
_SUPPLEMENTAL_RECORD_SET_TAG = "SupplementalRecordSet"
_DESCRIPTOR_RECORD_TAG = "DescriptorRecord"
_EXPECTED_LANGUAGE_CODE = "eng"
# The official 2026 DTD permits DescriptorClass 1 through 6. The 2026
# descriptor distribution actually uses 1 through 4; accepting the complete
# DTD-valid set prevents a future valid publisher record from being rejected.
_KNOWN_DESCRIPTOR_CLASSES = frozenset({"1", "2", "3", "4", "5", "6"})
_DESCRIPTOR_UI = re.compile(r"^D\d{6,}$")
_ENTITY_GUARD_WINDOW_BYTES = 8192


class MeshDescriptorError(ValueError):
    """MeSH descriptor acquisition or parsing could not preserve source meaning."""


def _sha256(payload: bytes) -> str:
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _require_nonempty_text(value: str | None, field: str) -> str:
    if value is None:
        raise MeshDescriptorError(f"{field} is missing")
    text = value.strip()
    if not text:
        raise MeshDescriptorError(f"{field} must not be empty")
    return text


class _PrefixedStream:
    """Replay an already-consumed prefix, then read through to the source."""

    def __init__(self, prefix: bytes, rest: IO[bytes]) -> None:
        self._buffer = prefix
        self._rest = rest

    def read(self, size: int = -1) -> bytes:
        if not self._buffer:
            return self._rest.read(size)
        if size < 0:
            chunk, self._buffer = self._buffer, b""
            return chunk + self._rest.read()
        if size >= len(self._buffer):
            chunk, self._buffer = self._buffer, b""
            remaining = size - len(chunk)
            return chunk + (self._rest.read(remaining) if remaining else b"")
        chunk, self._buffer = self._buffer[:size], self._buffer[size:]
        return chunk


class _DigestingReader:
    """Hash and count exact bytes as ``iterparse`` streams them through."""

    def __init__(self, stream: IO[bytes]) -> None:
        self._stream = stream
        self._hasher = hashlib.sha256()
        self.byte_length = 0

    def read(self, size: int = -1) -> bytes:
        chunk = self._stream.read(size)
        self._hasher.update(chunk)
        self.byte_length += len(chunk)
        return chunk

    def sha256(self) -> str:
        return "sha256:" + self._hasher.hexdigest()


def _guarded_digesting_reader(source: IO[bytes]) -> _DigestingReader:
    """Reject inline XML entity declarations before any parsing begins.

    MeSH descriptor files legitimately declare an external DOCTYPE pointing at
    the official published DTD; that reference is preserved. A custom
    ``<!ENTITY`` declaration is never legitimate in this source and is
    rejected outright rather than trusted to the XML parser's own defenses.
    """

    prefix = source.read(_ENTITY_GUARD_WINDOW_BYTES)
    if b"<!ENTITY" in prefix.upper():
        raise MeshDescriptorError("MeSH descriptor XML must not declare custom XML entities")
    return _DigestingReader(_PrefixedStream(prefix, source))


@dataclass(frozen=True, slots=True)
class MeshDescriptor:
    """One streamed MeSH descriptor row: publisher identity plus its terms."""

    heading: str
    descriptor_class: str
    tree_numbers: tuple[str, ...]
    entry_terms: tuple[str, ...]
    identifiers: tuple[ControlledIdentifier, ...]

    @property
    def descriptor_ui(self) -> str:
        """Compatibility view of the one required publisher DescriptorUI."""

        values = identifier_values(self.identifiers, kinds=frozenset({MESH_DESCRIPTOR_UI_KIND}))
        if len(values) != 1:
            raise MeshDescriptorError("MeSH descriptor must contain exactly one publisher DescriptorUI")
        return values[0]

    @property
    def concept_iri(self) -> str:
        """The publisher-published MeSH linked-data URI for this descriptor."""

        return MESH_DESCRIPTOR_AUTHORITY_URI + self.descriptor_ui


@dataclass(frozen=True, slots=True)
class MeshDescriptorSnapshot:
    """One streamed descriptor table with an exact whole-source digest."""

    source_url: str
    source_sha256: str
    source_byte_length: int
    language_code: str
    observed_at: str | None
    descriptors: tuple[MeshDescriptor, ...]


def _read_descriptor_record(elem: ElementTree.Element) -> tuple[str, str, str, tuple[str, ...], tuple[str, ...]]:
    descriptor_class = elem.get("DescriptorClass")
    if descriptor_class not in _KNOWN_DESCRIPTOR_CLASSES:
        raise MeshDescriptorError(f"DescriptorRecord has an unsupported DescriptorClass {descriptor_class!r}")
    descriptor_ui = _require_nonempty_text(elem.findtext("DescriptorUI"), "DescriptorRecord DescriptorUI")
    if _DESCRIPTOR_UI.fullmatch(descriptor_ui) is None:
        raise MeshDescriptorError(f"DescriptorRecord has a malformed DescriptorUI {descriptor_ui!r}")
    heading = _require_nonempty_text(
        elem.findtext("DescriptorName/String"),
        f"DescriptorRecord {descriptor_ui} DescriptorName",
    )
    tree_numbers = tuple(
        _require_nonempty_text(node.text, f"DescriptorRecord {descriptor_ui} TreeNumber")
        for node in elem.findall("TreeNumberList/TreeNumber")
    )
    entry_terms: list[str] = []
    seen = {heading}
    for term in elem.findall("ConceptList/Concept/TermList/Term"):
        is_permuted = term.get("IsPermutedTermYN")
        if is_permuted not in {"Y", "N"}:
            raise MeshDescriptorError(
                f"DescriptorRecord {descriptor_ui} Term has unsupported IsPermutedTermYN {is_permuted!r}"
            )
        if is_permuted == "Y":
            # NLM generates these index permutations mechanically. The MeSH
            # lookup API omits them from ordinary terms, so they are not
            # source-authored alternate labels here.
            continue
        text = _require_nonempty_text(term.findtext("String"), f"DescriptorRecord {descriptor_ui} Term")
        if text not in seen:
            seen.add(text)
            entry_terms.append(text)
    return descriptor_ui, heading, descriptor_class, tree_numbers, tuple(entry_terms)


def parse_mesh_descriptor_stream(
    source: IO[bytes],
    *,
    source_url: str,
    observed_at: str | None = None,
) -> MeshDescriptorSnapshot:
    """Stream-parse one MeSH descriptor XML source into a descriptor table.

    Only a ``DescriptorRecordSet`` root is accepted, so a
    ``SupplementalRecordSet`` file -- or any other MeSH export -- fails
    closed instead of being silently treated as descriptors. The XML tree is
    walked with ``iterparse``, and each ``DescriptorRecord`` element (and its
    already-consumed siblings) is cleared as soon as it is read, so parsing
    memory is bounded by one record regardless of source file size.
    """

    if observed_at is not None:
        validate_identifier_date(observed_at, "MeSH descriptor observed_at")
    reader = _guarded_digesting_reader(source)
    context = ElementTree.iterparse(reader, events=("start", "end"))
    try:
        event, root = next(context)
    except StopIteration as error:
        raise MeshDescriptorError("MeSH descriptor XML is empty") from error
    except ElementTree.ParseError as error:
        raise MeshDescriptorError("MeSH descriptor XML is malformed") from error
    if event != "start" or root.tag not in {_DESCRIPTOR_RECORD_SET_TAG, _SUPPLEMENTAL_RECORD_SET_TAG}:
        raise MeshDescriptorError(f"MeSH XML root must be {_DESCRIPTOR_RECORD_SET_TAG!r}")
    if root.tag == _SUPPLEMENTAL_RECORD_SET_TAG:
        raise MeshDescriptorError(
            "source is a MeSH Supplemental Concept Record file "
            f"({_SUPPLEMENTAL_RECORD_SET_TAG!r}); this module packages "
            "descriptors only and never reads supplemental concepts"
        )
    language_code = _require_nonempty_text(root.get("LanguageCode"), f"{_DESCRIPTOR_RECORD_SET_TAG} LanguageCode")
    if language_code != _EXPECTED_LANGUAGE_CODE:
        raise MeshDescriptorError(f"MeSH descriptor XML declared unsupported LanguageCode {language_code!r}")

    raw_records: list[tuple[str, str, str, tuple[str, ...], tuple[str, ...]]] = []
    seen_uis: set[str] = set()
    try:
        for event, elem in context:
            if event != "end" or elem.tag != _DESCRIPTOR_RECORD_TAG:
                continue
            record = _read_descriptor_record(elem)
            descriptor_ui = record[0]
            if descriptor_ui in seen_uis:
                raise MeshDescriptorError(f"MeSH XML repeats DescriptorUI {descriptor_ui}")
            seen_uis.add(descriptor_ui)
            raw_records.append(record)
            elem.clear()
            while len(root):
                del root[0]
    except ElementTree.ParseError as error:
        raise MeshDescriptorError("MeSH descriptor XML is malformed") from error
    if not raw_records:
        raise MeshDescriptorError("MeSH descriptor XML contains no DescriptorRecord elements")

    source_sha256 = reader.sha256()
    descriptors = tuple(
        MeshDescriptor(
            heading=heading,
            descriptor_class=descriptor_class,
            tree_numbers=tree_numbers,
            entry_terms=entry_terms,
            identifiers=(
                ControlledIdentifier(
                    value=descriptor_ui,
                    kind=MESH_DESCRIPTOR_UI_KIND,
                    authority_uri=MESH_DESCRIPTOR_AUTHORITY_URI,
                    source_uri=source_url,
                    observed_at=observed_at,
                    effective_at=None,
                    source_digest=source_sha256,
                ),
            ),
        )
        for descriptor_ui, heading, descriptor_class, tree_numbers, entry_terms in raw_records
    )
    return MeshDescriptorSnapshot(
        source_url=source_url,
        source_sha256=source_sha256,
        source_byte_length=reader.byte_length,
        language_code=language_code,
        observed_at=observed_at,
        descriptors=descriptors,
    )


def parse_mesh_descriptor_bytes(
    payload: bytes,
    *,
    source_url: str,
    observed_at: str | None = None,
) -> MeshDescriptorSnapshot:
    """Parse exact in-memory bytes. Intended for fixture-scale captures."""

    return parse_mesh_descriptor_stream(io.BytesIO(payload), source_url=source_url, observed_at=observed_at)


def parse_mesh_descriptor_file(
    path: Path,
    *,
    source_url: str,
    observed_at: str | None = None,
) -> MeshDescriptorSnapshot:
    """Stream one MeSH descriptor XML file from disk without buffering it whole."""

    source = Path(path)
    if source.is_symlink() or not source.is_file():
        raise MeshDescriptorError(f"MeSH descriptor source is not a regular file: {source}")
    with source.open("rb") as stream:
        return parse_mesh_descriptor_stream(stream, source_url=source_url, observed_at=observed_at)


def _descriptor_observation(
    descriptor: MeshDescriptor,
    *,
    source_url: str,
    ordinal: int,
) -> dict[str, Any]:
    identifier = descriptor.identifiers[0]
    observation_path = f"$.{_DESCRIPTOR_RECORD_SET_TAG}.{_DESCRIPTOR_RECORD_TAG}[{ordinal}]"
    labels = [{"value": descriptor.heading, "language": "en", "role": "preferred"}] + [
        {"value": term, "language": "en", "role": "alternate"} for term in descriptor.entry_terms
    ]
    return {
        "id": f"urn:ref:mesh-descriptor:{identifier.value}",
        "sourceArtifact": source_url,
        "sourcePath": observation_path,
        "sourceOrdinal": ordinal,
        "labels": labels,
        "identifiers": [
            {
                "value": identifier.value,
                "kind": identifier.kind,
                "authorityUri": identifier.authority_uri,
                "sourceUri": identifier.source_uri,
                "sourcePath": f"{observation_path}.DescriptorUI",
                "observedAt": identifier.observed_at,
                "sourceDigest": identifier.source_digest,
            }
        ],
        "eligibleUses": ["sourceAssignedEvidence", "searchExpansion"],
        "conceptIdentityClaimed": False,
        # Extra, source-faithful fields beyond the shared observation shape.
        "treeNumbers": list(descriptor.tree_numbers),
        "descriptorClass": descriptor.descriptor_class,
    }


def build_mesh_descriptor_package(
    snapshot: MeshDescriptorSnapshot,
    *,
    resource_id: str,
    title: str,
    captured_at: str,
    source_payload: bytes,
) -> SourceControlledResourceBundle:
    """Package one streamed capture as a development-only candidate snapshot.

    This packaging retains the exact source bytes for provenance, so it is
    meant for bounded, fixture-scale captures -- never the full ~300 MB
    annual release. Production use should keep ``MeshDescriptorSnapshot`` as
    the queryable descriptor table and reference the release file by its
    pinned digest instead of embedding it whole in a JSON package. Every
    identifier in ``snapshot`` must carry a concrete ``observed_at``
    (``parse_mesh_descriptor_stream`` was called with one); packaging never
    invents one.
    """

    if len(source_payload) != snapshot.source_byte_length or _sha256(source_payload) != snapshot.source_sha256:
        raise MeshDescriptorError("source_payload does not match the streamed snapshot digest")
    observations = tuple(
        _descriptor_observation(descriptor, source_url=snapshot.source_url, ordinal=ordinal)
        for ordinal, descriptor in enumerate(snapshot.descriptors)
    )
    return build_source_controlled_resource_bundle(
        resource_id=resource_id,
        title=title,
        resource_kind="sourceTermSnapshot",
        identity_status="publisherIdentifiersPreserved",
        uses=("sourceAssignedEvidence", "searchExpansion"),
        captured_at=captured_at,
        candidate_use_authorized=True,
        observations=observations,
        source_artifacts={snapshot.source_url: source_payload},
        source_observed_count=len(snapshot.descriptors),
    )


@dataclass(frozen=True, slots=True)
class MeshDescriptorPackageView:
    """A packaged MeSH descriptor snapshot reopened after its closed set verifies."""

    package: SourceControlledResourceView
    observations_by_descriptor_ui: Mapping[str, Mapping[str, Any]]

    @classmethod
    def open(cls, path: Path) -> MeshDescriptorPackageView:
        """Open, verify, and index one MeSH descriptor package by DescriptorUI."""

        package = SourceControlledResourceView.open(path)
        if package.resource_manifest.get("resourceKind") != "sourceTermSnapshot":
            raise MeshDescriptorError("package is not a MeSH descriptor sourceTermSnapshot")
        by_ui: dict[str, Mapping[str, Any]] = {}
        for observation in package.observations:
            matches = [
                identifier
                for identifier in observation["identifiers"]
                if identifier["kind"] == MESH_DESCRIPTOR_UI_KIND
            ]
            if len(matches) != 1:
                raise MeshDescriptorError("MeSH package observation lacks exactly one publisher DescriptorUI")
            descriptor_ui = matches[0]["value"]
            if descriptor_ui in by_ui:
                raise MeshDescriptorError(f"MeSH package repeats DescriptorUI {descriptor_ui!r}")
            by_ui[descriptor_ui] = observation
        return cls(package=package, observations_by_descriptor_ui=MappingProxyType(by_ui))

    def lookup(self, descriptor_ui: str) -> Mapping[str, Any] | None:
        """Return one exact source observation by publisher DescriptorUI."""

        return self.observations_by_descriptor_ui.get(descriptor_ui)


__all__ = [
    "MESH_2026_DESCRIPTOR_COUNT",
    "MESH_2026_QUALIFIER_COUNT",
    "MESH_2026_SUPPLEMENTAL_CONCEPT_COUNT",
    "MESH_ATTRIBUTION_NOTICE",
    "MESH_DESCRIPTOR_AUTHORITY_URI",
    "MESH_DESCRIPTOR_UI_KIND",
    "MESH_DOWNLOAD_PAGE_URL",
    "MeshDescriptor",
    "MeshDescriptorError",
    "MeshDescriptorPackageView",
    "MeshDescriptorSnapshot",
    "build_mesh_descriptor_package",
    "parse_mesh_descriptor_bytes",
    "parse_mesh_descriptor_file",
    "parse_mesh_descriptor_stream",
]
