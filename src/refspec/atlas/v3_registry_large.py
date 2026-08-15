"""Atlas 3 adapters for the largest exact registry source captures.

The registry modules remain responsible for parsing and source-shape checks.
This module only normalizes their verified publisher models into the shared
Atlas 3 source-data boundary.  It never creates cross-source mappings.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Callable, Collection, Iterator, Sequence
from dataclasses import asdict, dataclass
from itertools import islice
from pathlib import Path
from urllib.parse import quote

from refspec.atlas.v3_registry_selection import (
    normalize_only_keys,
    select_declared_group,
    wants_group,
)
from refspec.atlas.v3_source_data import (
    RegistryInputPin,
    RegistryLabel,
    RegistryRelation,
    RegistryRelease,
    RegistryResource,
    canonical_digest,
)
from refspec.registry import courtlistener_codes as courtlistener
from refspec.registry import fast_topical, naics_psc_codes, opm_workforce_codes
from refspec.registry import federal_register_topics_api as federal_register
from refspec.registry.infrastructure.source_identity import derive_uuid7

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_SOURCE_ROOT = ROOT / "output" / "registry-real-data-sources"

SKOS_BROADER = "http://www.w3.org/2004/02/skos/core#broader"
SKOS_RELATED = "http://www.w3.org/2004/02/skos/core#related"
ATLAS_THESAURUS_USE = "https://refspec.org/ns/atlas/v3#thesaurusUse"

COURTLISTENER_FULL_PIN = courtlistener.CourtListenerJurisdictionsSnapshotPin(
    source_url=courtlistener.COURTLISTENER_JURISDICTIONS_URL,
    retrieved_at="2026-08-03T00:00:00Z",
    expected_sha256=("sha256:883446028b029078c032bfe7c3545f9e109bb328c79ec486fbbbdbf35580b292"),
    expected_byte_length=3_156_029,
)
FEDERAL_REGISTER_TOPICS_SHA256 = "sha256:aba80a4dcacbffc7c9ec29eb88ea385ec313510fc8331d0f69078d940d1da35b"
FEDERAL_REGISTER_TOPICS_BYTE_LENGTH = 920_705
OPM_EHRI_SHA256 = opm_workforce_codes.OPM_EHRI_DATA_STANDARDS_SHA256
OPM_EHRI_BYTE_LENGTH = opm_workforce_codes.OPM_EHRI_DATA_STANDARDS_BYTE_LENGTH


@dataclass(frozen=True, slots=True)
class RegistryCatalogBinding:
    """One checked resource-catalog and Atlas-index placement."""

    resource_id: str
    source_module: str
    resource_kind: str
    profile: str
    ring: str

    @property
    def scheme_iri(self) -> str:
        return f"urn:ref:atlas-resource-scheme:{self.resource_id}"


LARGE_REGISTRY_BINDINGS = {
    "courtlistener-jurisdictions": RegistryCatalogBinding(
        resource_id="courtlistener-jurisdictions",
        source_module="refspec.registry.courtlistener_codes",
        resource_kind="identifierAuthority",
        profile="identifierScheme",
        ring="entity",
    ),
    "fast-topical": RegistryCatalogBinding(
        resource_id="fast-topical",
        source_module="refspec.registry.fast_topical",
        resource_kind="mappingReference",
        profile="conceptScheme",
        ring="subject",
    ),
    "federal-register-api-topics": RegistryCatalogBinding(
        resource_id="federal-register-api-topics",
        source_module="refspec.registry.federal_register_topics_api",
        resource_kind="sourceAssignedVocabulary",
        profile="conceptScheme",
        ring="subject",
    ),
    "naics": RegistryCatalogBinding(
        resource_id="naics",
        source_module="refspec.registry.naics_psc_codes",
        resource_kind="classification",
        profile="codeScheme",
        ring="value",
    ),
    "opm-ehri-workforce-codes": RegistryCatalogBinding(
        resource_id="opm-ehri-workforce-codes",
        source_module="refspec.registry.opm_workforce_codes",
        resource_kind="codeList",
        profile="codeScheme",
        ring="value",
    ),
    "psc": RegistryCatalogBinding(
        resource_id="psc",
        source_module="refspec.registry.naics_psc_codes",
        resource_kind="classification",
        profile="codeScheme",
        ring="value",
    ),
}


def _sequence_item[Item](
    values: Iterator[Item],
    length: int,
    index: int | slice,
) -> Item | tuple[Item, ...]:
    """Implement the small random-access surface required by ``Sequence``."""

    if isinstance(index, slice):
        start, stop, step = index.indices(length)
        if step == 1:
            return tuple(islice(values, start, stop))
        positions = tuple(range(start, stop, step))
        wanted = set(positions)
        found = {position: item for position, item in enumerate(values) if position in wanted}
        return tuple(found[position] for position in positions)
    normalized = index + length if index < 0 else index
    if normalized < 0 or normalized >= length:
        raise IndexError(index)
    try:
        return next(islice(values, normalized, normalized + 1))
    except StopIteration as error:  # pragma: no cover - defensive Sequence guard
        raise IndexError(index) from error


def _local_resource_iri(
    *,
    namespace_token: str,
    recorded_at: str,
    source_iri: str,
    source_key: str,
) -> str:
    """Mint a readable, deterministic UUIDv7 identity under one source root."""

    seed = (f"atlas-v3-registry-source-identity-v1\n{source_iri}\n{source_key}\n").encode()
    local_id = derive_uuid7(recorded_at, seed=seed)
    return f"urn:ref:source-concept:v2:{namespace_token}:{local_id}"


def _pin(
    path: Path,
    *,
    sha256: str,
    byte_length: int,
    source_iri: str,
    role: str = "publisherSource",
) -> RegistryInputPin:
    resolved = Path(path)
    try:
        logical_path = "refspec/" + resolved.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        logical_path = resolved.as_posix()
    return RegistryInputPin(
        path=resolved,
        logical_path=logical_path,
        sha256=sha256,
        byte_length=byte_length,
        source_iri=source_iri,
        role=role,
    )


def _atlas_release_iri(key: str, release_digest: str) -> str:
    return f"urn:ref:atlas-release:{key}:{release_digest.removeprefix('sha256:')}"


def _release_digest(
    *,
    parser: str,
    inputs: Sequence[RegistryInputPin],
    accounting: object,
) -> str:
    return canonical_digest(
        {
            "accounting": accounting,
            "inputs": [
                {
                    "byteLength": item.byte_length,
                    "role": item.role,
                    "sha256": item.sha256,
                    "sourceIri": item.source_iri,
                }
                for item in inputs
            ],
            "parser": parser,
        }
    )


def _composite_source_digest(inputs: Sequence[RegistryInputPin]) -> str:
    """Digest only exact source pins, independent of Atlas normalization."""

    return canonical_digest(
        [
            {
                "byteLength": item.byte_length,
                "role": item.role,
                "sha256": item.sha256,
                "sourceIri": item.source_iri,
            }
            for item in inputs
        ]
    )


class _FASTResourceSequence(Sequence[RegistryResource]):
    """Lazy normalized view that avoids copying 441,127 FAST rows."""

    __slots__ = ("_rows", "_source_digest")

    def __init__(
        self,
        rows: Sequence[fast_topical.FASTTopicalNativeRow],
        *,
        source_digest: str,
    ) -> None:
        self._rows = rows
        self._source_digest = source_digest

    def __len__(self) -> int:
        return len(self._rows)

    def _adapt(self, row: fast_topical.FASTTopicalNativeRow) -> RegistryResource:
        native_payload = {
            "altLabels": list(row.alt_labels),
            "broaderIds": list(row.broader_ids),
            "heading": row.heading,
            "identityStatus": "publisherIdentifierVerified",
            "legacyFstId": row.legacy_fst_id,
            "numericId": row.numeric_id,
            "publisherIri": row.uri,
        }
        source_path = row.uri
        preferred_label = row.heading.strip()
        labels = [
            RegistryLabel(
                value=preferred_label,
                role="preferred",
                source_path=f"{source_path}#skos:prefLabel",
            )
        ]
        seen_labels = {preferred_label}
        for position, raw_value in enumerate(row.alt_labels):
            value = raw_value.strip()
            if not value or value in seen_labels:
                continue
            seen_labels.add(value)
            labels.append(
                RegistryLabel(
                    value=value,
                    role="alternate",
                    source_path=f"{source_path}#skos:altLabel[{position}]",
                )
            )
        return RegistryResource(
            iri=row.uri,
            labels=tuple(labels),
            native_payload=native_payload,
            source_locator=row.uri,
            source_digest=self._source_digest,
            notations=(row.numeric_id, row.legacy_fst_id),
            status="active",
        )

    def __iter__(self) -> Iterator[RegistryResource]:
        return (self._adapt(row) for row in self._rows)

    def __getitem__(
        self,
        index: int | slice,
    ) -> RegistryResource | tuple[RegistryResource, ...]:
        if isinstance(index, slice):
            return tuple(self._adapt(row) for row in self._rows[index])
        return self._adapt(self._rows[index])


class _FASTRelationSequence(Sequence[RegistryRelation]):
    """Lazy active-member-only view of direct OCLC broader links."""

    __slots__ = ("_active_ids", "_length", "_rows", "dropped_target_count")

    def __init__(self, rows: Sequence[fast_topical.FASTTopicalNativeRow]) -> None:
        self._rows = rows
        self._active_ids = frozenset(row.numeric_id for row in rows)
        active_count = 0
        dropped_count = 0
        for row in rows:
            for target_id in row.broader_ids:
                if target_id in self._active_ids:
                    active_count += 1
                else:
                    dropped_count += 1
        self._length = active_count
        self.dropped_target_count = dropped_count

    def __len__(self) -> int:
        return self._length

    def __iter__(self) -> Iterator[RegistryRelation]:
        for row in self._rows:
            for target_id in row.broader_ids:
                if target_id not in self._active_ids:
                    continue
                yield RegistryRelation(
                    subject=row.uri,
                    predicate=SKOS_BROADER,
                    object=f"{fast_topical.FAST_URI_BASE}{target_id}",
                    source_payload={
                        "sourceRecord": row.uri,
                        "sourceProperty": "skos:broader",
                        "targetNumericId": target_id,
                    },
                )

    def __getitem__(
        self,
        index: int | slice,
    ) -> RegistryRelation | tuple[RegistryRelation, ...]:
        return _sequence_item(iter(self), len(self), index)


def _fast_release_from_snapshot(
    snapshot: fast_topical.ParsedFASTTopicalNativeSnapshot,
    inputs: Sequence[RegistryInputPin],
) -> RegistryRelease:
    relations = _FASTRelationSequence(snapshot.rows)
    tombstone_status_counts = dict(sorted(Counter(item.status for item in snapshot.tombstones).items()))
    metadata = {
        "activeBroaderRelationCount": len(relations),
        "baseActiveCount": snapshot.base_active_count,
        "currentActiveCount": len(snapshot.rows),
        "droppedInactiveBroaderTargetCount": relations.dropped_target_count,
        "facetMigrationCount": snapshot.facet_migration_count,
        "tombstoneCount": len(snapshot.tombstones),
        "tombstoneDigest": canonical_digest([asdict(item) for item in snapshot.tombstones]),
        "tombstoneReplacementCount": sum(len(item.replacement_ids) for item in snapshot.tombstones),
        "tombstoneStatusCounts": tombstone_status_counts,
        "tombstonesAreMembers": False,
        "topicalEventCount": snapshot.topical_event_count,
        "uniqueChangedIdCount": snapshot.unique_changed_id_count,
        "sourceRecordDigestSemantics": ("exact ordered base-and-change composite source release digest"),
    }
    source_release_digest = _composite_source_digest(inputs)
    resources = _FASTResourceSequence(
        snapshot.rows,
        source_digest=source_release_digest,
    )
    atlas_release_digest = _release_digest(
        parser="fast-topical-native-snapshot-v1",
        inputs=inputs,
        accounting=metadata,
    )
    binding = LARGE_REGISTRY_BINDINGS["fast-topical"]
    return RegistryRelease(
        key="fast-topical-current",
        resource_id=binding.resource_id,
        source_module=binding.source_module,
        profile=binding.profile,
        ring=binding.ring,
        scope="publisherRelease",
        issued="2026-02-13",
        source_release_iri=(fast_topical.FAST_TOPICAL_BULK_NT_ZIP_URL + "#changes-through-2026-02-13"),
        source_release_digest=source_release_digest,
        atlas_release_iri=_atlas_release_iri("fast-topical-current", atlas_release_digest),
        scheme_iri=binding.scheme_iri,
        inputs=tuple(inputs),
        resources=resources,
        relations=relations,
        metadata=metadata,
    )


def load_fast_topical_release(
    source_root: Path = DEFAULT_SOURCE_ROOT,
) -> RegistryRelease:
    """Load the exact OCLC base plus all four chronological change files."""

    root = Path(source_root)
    source_pins = (
        fast_topical.FAST_TOPICAL_NATIVE_BASE_PIN,
        *fast_topical.FAST_TOPICAL_CHANGE_PINS,
    )
    inputs = tuple(
        _pin(
            root / source.filename,
            sha256=source.expected_sha256,
            byte_length=source.expected_byte_length,
            source_iri=source.publisher_url,
            role="publisherBase" if position == 0 else "publisherChange",
        )
        for position, source in enumerate(source_pins)
    )
    snapshot = fast_topical.parse_fast_topical_native_snapshot(
        inputs[0].path,
        tuple(item.path for item in inputs[1:]),
    )
    return _fast_release_from_snapshot(snapshot, inputs)


def _naics_psc_release_from_parsed(
    parsed: naics_psc_codes.ParsedNaicsPscResource,
    input_pin: RegistryInputPin,
) -> RegistryRelease:
    is_naics = parsed.source.resource_name == "naicsCodes"
    key = "naics-2022" if is_naics else "psc-april-2025"
    token = "naics-2022" if is_naics else "psc-2025"
    binding = LARGE_REGISTRY_BINDINGS["naics" if is_naics else "psc"]
    resources: list[RegistryResource] = []
    for code in parsed.codes:
        identifier = code.identifiers[0]
        source_locator = f"{parsed.source.source_url}#code={quote(identifier.value, safe='')}"
        native_payload = {
            "facet": code.facet,
            "identifiers": [item.as_dict() for item in code.identifiers],
            "identityStatus": "publisherCodeSourceLocalIri",
            "publisherLabel": code.publisher_label,
            "resourceName": code.resource_name,
            "use": code.use,
        }
        resources.append(
            RegistryResource(
                iri=_local_resource_iri(
                    namespace_token=token,
                    recorded_at=parsed.retrieved_at,
                    source_iri=parsed.source.source_url,
                    source_key=identifier.value,
                ),
                labels=(
                    RegistryLabel(
                        value=code.publisher_label,
                        role="preferred",
                        source_path=source_locator,
                    ),
                ),
                native_payload=native_payload,
                source_locator=source_locator,
                source_digest=input_pin.sha256,
                notations=(identifier.value,),
                status="active",
            )
        )
    metadata = {
        "edition": parsed.edition,
        "hierarchyRelationCount": 0,
        "hierarchyStatus": (
            "no broaderValue emitted because the parser exposes facets but no publisher parent relation"
        ),
        "sourceRecordDigestSemantics": ("exact publisher artifact digest plus a code-fragment source locator"),
        "sourceObservedCount": len(parsed.codes),
    }
    atlas_release_digest = _release_digest(
        parser="naics-psc-codes-source-faithful-v1",
        inputs=(input_pin,),
        accounting=metadata,
    )
    return RegistryRelease(
        key=key,
        resource_id=binding.resource_id,
        source_module=binding.source_module,
        profile=binding.profile,
        ring=binding.ring,
        scope="publisherRelease",
        issued="2022-01-01" if is_naics else "2025-04-01",
        source_release_iri=parsed.source.source_url,
        source_release_digest=input_pin.sha256,
        atlas_release_iri=_atlas_release_iri(key, atlas_release_digest),
        scheme_iri=binding.scheme_iri,
        inputs=(input_pin,),
        resources=tuple(resources),
        metadata=metadata,
    )


def _load_naics_psc_release(
    source_path: Path,
    parser_pin: naics_psc_codes.NaicsPscSnapshotPin,
) -> RegistryRelease:
    input_pin = _pin(
        source_path,
        sha256=parser_pin.expected_sha256,
        byte_length=parser_pin.expected_byte_length,
        source_iri=parser_pin.source.source_url,
    )
    input_pin.verify()
    acquired = naics_psc_codes.AcquiredNaicsPscSource(
        pin=parser_pin,
        path=input_pin.path,
        sha256=input_pin.sha256,
        byte_length=input_pin.byte_length,
        source_url=input_pin.source_iri,
        resolved_url=None,
        content_type=(
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            if parser_pin.source.filename.endswith(".xlsx")
            else "text/csv"
        ),
        acquisition_mode="local",
        cache_hit=False,
        local_source_path=input_pin.path,
    )
    parsed = (
        naics_psc_codes.parse_naics_codes(acquired)
        if parser_pin.source.resource_name == "naicsCodes"
        else naics_psc_codes.parse_psc_codes(acquired)
    )
    if len(parsed.codes) != parser_pin.source.expected_count:
        raise ValueError(
            f"{parser_pin.source.resource_name} count differs after parsing: "
            f"expected {parser_pin.source.expected_count}, got {len(parsed.codes)}"
        )
    return _naics_psc_release_from_parsed(parsed, input_pin)


def load_naics_release(
    source_path: Path = DEFAULT_SOURCE_ROOT / "2-6-digit_2022_Codes.xlsx",
    *,
    parser_pin: naics_psc_codes.NaicsPscSnapshotPin = (naics_psc_codes.NAICS_CODES_2022_XLSX),
) -> RegistryRelease:
    """Load the exact official 2022 NAICS structure workbook."""

    if parser_pin.source.resource_name != "naicsCodes":
        raise ValueError("NAICS loader requires a naicsCodes parser pin")
    return _load_naics_psc_release(source_path, parser_pin)


def load_psc_release(
    source_path: Path = DEFAULT_SOURCE_ROOT / "PSC-April-2025-wayback.xlsx",
    *,
    parser_pin: naics_psc_codes.NaicsPscSnapshotPin = (naics_psc_codes.PSC_CODES_APRIL_2025_XLSX),
) -> RegistryRelease:
    """Load the exact April 2025 Product and Service Code workbook."""

    if parser_pin.source.resource_name != "pscCodes":
        raise ValueError("PSC loader requires a pscCodes parser pin")
    return _load_naics_psc_release(source_path, parser_pin)


def _courtlistener_release_from_parsed(
    parsed: courtlistener.ParsedCourtListenerJurisdictionsPage,
    input_pin: RegistryInputPin,
) -> RegistryRelease:
    resources: list[RegistryResource] = []
    for row in parsed.rows:
        court_ids = [item.value for item in row.identifiers if item.kind == "courtlistenerCourtId"]
        if len(court_ids) != 1:
            raise ValueError("CourtListener row must have one platform court identifier")
        court_id = court_ids[0]
        source_locator = f"{parsed.source_url}#abbreviation={quote(court_id, safe='')}"
        native_payload = {
            "citationAbbreviation": row.citation_abbreviation,
            "endDate": row.end_date,
            "identifiers": [item.as_dict() for item in row.identifiers],
            "identityStatus": "publisherPlatformIdentifier",
            "inUse": row.in_use,
            "jurisdictionType": row.jurisdiction_type,
            "modified": row.modified,
            "name": row.name,
            "sourceOrdinal": row.source_ordinal,
            "startDate": row.start_date,
        }
        notations = [court_id]
        if row.citation_abbreviation:
            notations.append(row.citation_abbreviation)
        resources.append(
            RegistryResource(
                iri=_local_resource_iri(
                    namespace_token="courtlistener",
                    recorded_at=parsed.retrieved_at,
                    source_iri=parsed.source_url,
                    source_key=court_id,
                ),
                labels=(
                    RegistryLabel(
                        value=row.name,
                        role="preferred",
                        source_path=source_locator,
                    ),
                ),
                native_payload=native_payload,
                source_locator=source_locator,
                source_digest=input_pin.sha256,
                notations=tuple(notations),
                status="active" if row.in_use else "inactive",
            )
        )
    metadata = {
        "activeCount": sum(row.in_use for row in parsed.rows),
        "gaps": [dict(item) for item in parsed.gaps],
        "inactiveCount": sum(not row.in_use for row in parsed.rows),
        "identityAuthority": "CourtListener platform",
        "officialCourtIdentityClaimed": False,
        "sourceRecordDigestSemantics": ("exact page-capture digest plus an abbreviation-fragment source locator"),
        "sourceObservedCount": len(parsed.rows),
    }
    atlas_release_digest = _release_digest(
        parser="courtlistener-jurisdictions-source-faithful-v1",
        inputs=(input_pin,),
        accounting=metadata,
    )
    binding = LARGE_REGISTRY_BINDINGS["courtlistener-jurisdictions"]
    return RegistryRelease(
        key="courtlistener-jurisdictions-2026-08-03",
        resource_id=binding.resource_id,
        source_module=binding.source_module,
        profile=binding.profile,
        ring=binding.ring,
        scope="completeCapture",
        issued="2026-08-03",
        source_release_iri=(parsed.source_url + "#capture-" + parsed.source_sha256.removeprefix("sha256:")),
        source_release_digest=input_pin.sha256,
        atlas_release_iri=_atlas_release_iri("courtlistener-jurisdictions-2026-08-03", atlas_release_digest),
        scheme_iri=binding.scheme_iri,
        inputs=(input_pin,),
        resources=tuple(resources),
        metadata=metadata,
    )


def load_courtlistener_jurisdictions_release(
    source_path: Path = (DEFAULT_SOURCE_ROOT / "courtlistener-jurisdictions-zyte.html"),
    *,
    parser_pin: courtlistener.CourtListenerJurisdictionsSnapshotPin = (COURTLISTENER_FULL_PIN),
    expected_count: int = 3_359,
) -> RegistryRelease:
    """Load one exact CourtListener jurisdictions-page capture."""

    input_pin = _pin(
        source_path,
        sha256=parser_pin.expected_sha256,
        byte_length=parser_pin.expected_byte_length,
        source_iri=parser_pin.source_url,
    )
    input_pin.verify()
    acquired = courtlistener.AcquiredCourtListenerJurisdictionsPage(
        pin=parser_pin,
        path=input_pin.path,
        sha256=input_pin.sha256,
        byte_length=input_pin.byte_length,
        source_url=input_pin.source_iri,
        resolved_url=None,
        content_type="text/html",
        acquisition_mode="local",
        cache_hit=False,
        local_source_path=input_pin.path,
    )
    parsed = courtlistener.parse_courtlistener_jurisdictions_page(acquired)
    if len(parsed.rows) != expected_count:
        raise ValueError(
            "CourtListener jurisdictions count differs after parsing: "
            f"expected {expected_count}, got {len(parsed.rows)}"
        )
    return _courtlistener_release_from_parsed(parsed, input_pin)


def _federal_register_release_from_snapshot(
    snapshot: federal_register.FederalRegisterTopicsSnapshot,
    input_pin: RegistryInputPin,
    *,
    issued: str,
) -> RegistryRelease:
    recorded_at = f"{issued}T00:00:00Z"
    # REF-032: only the publisher's own ``thesaurus`` collection is a
    # vocabulary. The ``ad_hoc`` collection is document fragments the API
    # harvested from rule text ("165 as follows:"), so the release is the
    # complete capture of the thesaurus collection and nothing else. The
    # split is the publisher's, taken at the collection field its payload
    # already carries.
    emitted = snapshot.thesaurus
    iri_by_record: dict[tuple[str, int], str] = {}
    record_by_pair: dict[
        tuple[str, str, str],
        federal_register.FederalRegisterTopicRecord,
    ] = {}
    for row in emitted:
        record_key = (row.collection, row.source_ordinal)
        iri_by_record[record_key] = _local_resource_iri(
            namespace_token="federal-register-api",
            recorded_at=recorded_at,
            source_iri=federal_register.FEDERAL_REGISTER_TOPICS_API_URL,
            source_key=(f"{row.collection}:{row.source_ordinal}:{row.source_record_digest}"),
        )
        pair = (row.collection, row.name, row.slug)
        if pair in record_by_pair:
            raise ValueError(f"Federal Register topic pair is duplicated: {pair!r}")
        record_by_pair[pair] = row

    resources: list[RegistryResource] = []
    relations: list[RegistryRelation] = []
    predicates = (("see", ATLAS_THESAURUS_USE), ("see_also", SKOS_RELATED))
    for row in emitted:
        # `row.source_locator` is a JSON-pointer-ish path (`results.ad_hoc[7]`)
        # whose brackets RFC 3987 excludes from an IRI. Percent-encoding them
        # here, where the string first becomes an IRI, is the fix: `quote`
        # encodes `%` first, so the transform is exactly invertible and the
        # source path is still readable in the locator.
        source_locator = (
            federal_register.FEDERAL_REGISTER_TOPICS_API_URL
            + "#"
            + quote(row.source_locator, safe="")
        )
        native_payload = {
            "collection": row.collection,
            "identityStatus": "sourceLocalCaptureRow",
            "record": row.native_payload(),
            "sourceOrdinal": row.source_ordinal,
            "sourceRecordDigest": row.source_record_digest,
        }
        resources.append(
            RegistryResource(
                iri=iri_by_record[(row.collection, row.source_ordinal)],
                labels=(
                    RegistryLabel(
                        value=row.name,
                        role="preferred",
                        source_path=source_locator,
                    ),
                ),
                native_payload=native_payload,
                source_locator=source_locator,
                source_digest=row.source_record_digest,
                notations=(row.slug,) if row.slug else (),
            )
        )
        for property_name, predicate in predicates:
            for link in getattr(row, property_name):
                target = record_by_pair.get((row.collection, link.name, link.slug))
                if target is None:
                    raise ValueError(
                        "Federal Register topic link has no exact same-collection target: "
                        f"{row.source_locator} {property_name} {link.native_payload()!r}"
                    )
                relations.append(
                    RegistryRelation(
                        subject=iri_by_record[(row.collection, row.source_ordinal)],
                        predicate=predicate,
                        object=iri_by_record[(target.collection, target.source_ordinal)],
                        source_payload={
                            "sourceRecord": row.source_locator,
                            "sourceProperty": property_name,
                            "target": link.native_payload(),
                        },
                    )
                )
    emitted_pairs: dict[tuple[str, str], int] = {}
    for row in emitted:
        key = (row.collection, row.slug)
        emitted_pairs[key] = emitted_pairs.get(key, 0) + 1
    metadata = {
        "emittedCollection": "thesaurus",
        "emittedCount": len(resources),
        "excludedAdHocCount": len(snapshot.ad_hoc),
        "excludedCollections": ["ad_hoc"],
        "identityStatus": "source-local exact capture; slugs are not identities",
        "managedThesaurus2025Merged": False,
        "relatedRelationCount": sum(relation.predicate == SKOS_RELATED for relation in relations),
        "slugCollisionGroupCount": sum(1 for count in emitted_pairs.values() if count > 1),
        "sourceRecordDigestSemantics": ("parser-canonical digest of the exact collection, ordinal, and source row"),
        "sourceRecordSetDigest": snapshot.source_record_set_digest,
        "thesaurusCount": len(snapshot.thesaurus),
        "totalCapturedCount": len(snapshot.records),
    }
    atlas_release_digest = _release_digest(
        parser=federal_register.FEDERAL_REGISTER_TOPICS_PARSER_VERSION,
        inputs=(input_pin,),
        accounting=metadata,
    )
    key = f"federal-register-api-topics-{issued}"
    binding = LARGE_REGISTRY_BINDINGS["federal-register-api-topics"]
    return RegistryRelease(
        key=key,
        resource_id=binding.resource_id,
        source_module=binding.source_module,
        profile=binding.profile,
        ring=binding.ring,
        scope="completeCapture",
        issued=issued,
        source_release_iri=(
            federal_register.FEDERAL_REGISTER_TOPICS_API_URL
            + "#capture-"
            + snapshot.source_sha256.removeprefix("sha256:")
        ),
        source_release_digest=input_pin.sha256,
        atlas_release_iri=_atlas_release_iri(key, atlas_release_digest),
        scheme_iri=binding.scheme_iri,
        inputs=(input_pin,),
        resources=tuple(resources),
        relations=tuple(relations),
        metadata=metadata,
    )


def load_federal_register_topics_release(
    source_path: Path = (DEFAULT_SOURCE_ROOT / "federal-register-topics-zyte.json"),
    *,
    expected_sha256: str = FEDERAL_REGISTER_TOPICS_SHA256,
    expected_byte_length: int = FEDERAL_REGISTER_TOPICS_BYTE_LENGTH,
    expected_counts: tuple[int, int] = (1_044, 6_723),
    issued: str = "2026-08-03",
) -> RegistryRelease:
    """Load the exact API capture without merging the 2025 managed thesaurus."""

    input_pin = _pin(
        source_path,
        sha256=expected_sha256,
        byte_length=expected_byte_length,
        source_iri=federal_register.FEDERAL_REGISTER_TOPICS_API_URL,
        role="publisherApiCapture",
    )
    input_pin.verify()
    snapshot = federal_register.open_federal_register_topics_capture(
        input_pin.path,
        expected_sha256=input_pin.sha256,
        expected_byte_length=input_pin.byte_length,
    )
    observed_counts = (len(snapshot.thesaurus), len(snapshot.ad_hoc))
    if observed_counts != expected_counts:
        raise ValueError(
            "Federal Register topics collection counts differ after parsing: "
            f"expected {expected_counts}, got {observed_counts}"
        )
    return _federal_register_release_from_snapshot(
        snapshot,
        input_pin,
        issued=issued,
    )


def _opm_ehri_release_from_export(
    export: opm_workforce_codes.OPMEHRIDataStandardsExport,
    input_pin: RegistryInputPin,
    *,
    issued: str,
) -> RegistryRelease:
    fields_by_name = {field.name: field for field in export.fields}
    if len(fields_by_name) != len(export.fields):
        raise ValueError("OPM EHRI field names are not unique")
    past_by_key: dict[
        tuple[str, str],
        list[opm_workforce_codes.OPMEHRIValue],
    ] = defaultdict(list)
    for value in export.past_values:
        past_by_key[(value.name, value.code)].append(value)

    resources: list[RegistryResource] = []
    seen_keys: set[tuple[str, str]] = set()
    for ordinal, value in enumerate(export.current_values):
        key = (value.name, value.code)
        if key in seen_keys:
            raise ValueError(f"OPM EHRI current field/code is duplicated: {key!r}")
        seen_keys.add(key)
        field = fields_by_name.get(value.name)
        if field is None:
            raise ValueError(f"OPM EHRI current value names an unknown field: {value.name!r}")
        source_locator = opm_workforce_codes.OPM_EHRI_DATA_STANDARDS_URL + f"#CurrentValues/{ordinal}"
        native_payload = {
            "currentValue": asdict(value),
            "field": asdict(field),
            "identityScope": {"code": value.code, "field": value.name},
            "identityStatus": "sourceLocalFieldCode",
            "isCurrentValue": True,
            "pastLifecycle": [asdict(item) for item in past_by_key.get(key, ())],
        }
        resources.append(
            RegistryResource(
                iri=_local_resource_iri(
                    namespace_token="opm-ehri",
                    recorded_at=f"{issued}T00:00:00Z",
                    source_iri=opm_workforce_codes.OPM_EHRI_DATA_STANDARDS_URL,
                    source_key=f"{value.name}\u001f{value.code}",
                ),
                labels=(
                    RegistryLabel(
                        value=value.explanation.strip(),
                        role="preferred",
                        source_path=source_locator,
                    ),
                ),
                native_payload=native_payload,
                source_locator=source_locator,
                source_digest=input_pin.sha256,
                definition=field.description.strip() or None,
                notations=(value.code, value.name),
                status="current",
            )
        )
    current_keys = set(seen_keys)
    past_only_keys = set(past_by_key) - current_keys
    metadata = {
        "agencySubelementExtracted": {
            "element": opm_workforce_codes.OPM_EHRI_AGENCY_SUBELEMENT_ELEMENT,
            "toReleaseKey": "opm-ehri-agency-subelement-2026-08-04",
            "currentValueCount": 798,
            "pastValueCount": 3004,
            "fieldDefinitionCount": 1,
        },
        "bulkPlumRowsIncluded": False,
        "currentFieldCount": len({value.name for value in export.current_values}),
        "currentValueCount": len(export.current_values),
        "fieldDefinitionCount": len(export.fields),
        "pastLifecycleAttachedCount": sum(len(past_by_key.get(key, ())) for key in current_keys),
        "pastOnlyIdentityCount": len(past_only_keys),
        "pastValueCount": len(export.past_values),
        "pastValuesAreMembers": False,
        "sourceRecordDigestSemantics": ("exact workbook digest plus a CurrentValues-row source locator"),
    }
    atlas_release_digest = _release_digest(
        parser="opm-ehri-data-standards-xlsx-v1",
        inputs=(input_pin,),
        accounting=metadata,
    )
    key = f"opm-ehri-data-standards-{issued}"
    binding = LARGE_REGISTRY_BINDINGS["opm-ehri-workforce-codes"]
    return RegistryRelease(
        key=key,
        resource_id=binding.resource_id,
        source_module=binding.source_module,
        profile=binding.profile,
        ring=binding.ring,
        scope="completeCapture",
        issued=issued,
        source_release_iri=(
            opm_workforce_codes.OPM_EHRI_DATA_STANDARDS_URL + "#capture-" + export.source_sha256.removeprefix("sha256:")
        ),
        source_release_digest=input_pin.sha256,
        atlas_release_iri=_atlas_release_iri(key, atlas_release_digest),
        scheme_iri=binding.scheme_iri,
        inputs=(input_pin,),
        resources=tuple(resources),
        metadata=metadata,
    )


def load_opm_ehri_release(
    source_path: Path = (DEFAULT_SOURCE_ROOT / "EHRI-Data-Standards-20260804.xlsx"),
    *,
    expected_sha256: str = OPM_EHRI_SHA256,
    expected_byte_length: int = OPM_EHRI_BYTE_LENGTH,
    expected_counts: tuple[int, int, int] = (534, 17_263, 16_425),
    issued: str = "2026-08-04",
) -> RegistryRelease:
    """Load current EHRI field/code values; never load bulk PLUM rows.

    The AGENCY/SUBELEMENT element is split out before emission: its rows are
    an organizational roster, emitted on the entity ring as
    ``opm-ehri-agency-subelement-2026-08-04`` (see
    :mod:`refspec.atlas.v3_registry_nonemitters`), not as workforce code
    values.  The full-workbook counts are still checked before the split.
    """

    input_pin = _pin(
        source_path,
        sha256=expected_sha256,
        byte_length=expected_byte_length,
        source_iri=opm_workforce_codes.OPM_EHRI_DATA_STANDARDS_URL,
    )
    input_pin.verify()
    export = opm_workforce_codes.parse_opm_ehri_data_standards_xlsx(input_pin.path.read_bytes())
    observed_counts = (
        len(export.fields),
        len(export.current_values),
        len(export.past_values),
    )
    if observed_counts != expected_counts:
        raise ValueError(
            f"OPM EHRI workbook counts differ after parsing: expected {expected_counts}, got {observed_counts}"
        )
    if export.source_sha256 != input_pin.sha256 or export.source_byte_length != input_pin.byte_length:
        raise ValueError("OPM EHRI parser output differs from its exact input pin")
    split = opm_workforce_codes.split_opm_ehri_element(export)
    return _opm_ehri_release_from_export(split.remainder, input_pin, issued=issued)


LARGE_REGISTRY_RELEASE_KEYS = frozenset(
    {
        "courtlistener-jurisdictions-2026-08-03",
        "fast-topical-current",
        "federal-register-api-topics-2026-08-03",
        "naics-2022",
        "opm-ehri-data-standards-2026-08-04",
        "psc-april-2025",
    }
)

def _large_registry_loader_specs() -> tuple[
    tuple[str, Callable[[Path], RegistryRelease], str | None], ...
]:
    return (
        ("fast-topical-current", load_fast_topical_release, None),
        ("naics-2022", load_naics_release, "2-6-digit_2022_Codes.xlsx"),
        ("psc-april-2025", load_psc_release, "PSC-April-2025-wayback.xlsx"),
        (
            "courtlistener-jurisdictions-2026-08-03",
            load_courtlistener_jurisdictions_release,
            "courtlistener-jurisdictions-zyte.html",
        ),
        (
            "federal-register-api-topics-2026-08-03",
            load_federal_register_topics_release,
            "federal-register-topics-zyte.json",
        ),
        (
            "opm-ehri-data-standards-2026-08-04",
            load_opm_ehri_release,
            "EHRI-Data-Standards-20260804.xlsx",
        ),
    )


def load_large_registry_releases(
    source_root: Path = DEFAULT_SOURCE_ROOT,
    *,
    only_keys: Collection[str] | None = None,
) -> tuple[RegistryRelease, ...]:
    """Load the selected full cached releases normalized by this module."""

    requested = normalize_only_keys(
        only_keys,
        allowed_keys=LARGE_REGISTRY_RELEASE_KEYS,
        loader_name="load_large_registry_releases",
    )
    root = Path(source_root)
    releases: list[RegistryRelease] = []
    for key, loader, filename in _large_registry_loader_specs():
        group_keys = frozenset({key})
        if not wants_group(requested, group_keys):
            continue
        source = root if filename is None else root / filename
        releases.extend(
            select_declared_group(
                (loader(source),),
                declared_keys=group_keys,
                requested_keys=requested,
                loader_name=loader.__name__,
            )
        )
    return tuple(releases)


__all__ = [
    "COURTLISTENER_FULL_PIN",
    "DEFAULT_SOURCE_ROOT",
    "FEDERAL_REGISTER_TOPICS_BYTE_LENGTH",
    "FEDERAL_REGISTER_TOPICS_SHA256",
    "LARGE_REGISTRY_BINDINGS",
    "LARGE_REGISTRY_RELEASE_KEYS",
    "OPM_EHRI_BYTE_LENGTH",
    "OPM_EHRI_SHA256",
    "RegistryCatalogBinding",
    "load_courtlistener_jurisdictions_release",
    "load_fast_topical_release",
    "load_federal_register_topics_release",
    "load_large_registry_releases",
    "load_naics_release",
    "load_opm_ehri_release",
    "load_psc_release",
]
