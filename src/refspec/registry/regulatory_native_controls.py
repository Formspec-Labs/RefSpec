"""Capture regulatory source controls without promoting them to subjects.

The active Spicy Regs tables already contain useful document types, process
states, agency identifiers, and attachment formats.  This module captures
those exact source values as filter and search controls.  It deliberately does
not mint concepts from their labels or make them eligible subject candidates.

Identifier extraction is record-oriented and lossless: a source record may
produce zero, one, or many structured identifier observations.  Each
observation retains its identifier kind, authority, source record, ordinal,
and observation date.  No observation is selected as a canonical identifier.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, Literal
from urllib.parse import quote, urlparse

import pyarrow.parquet as pq

from refspec.registry.infrastructure.controlled_identifier import ControlledIdentifier
from refspec.storage import canonical_json

SOURCE_PINS_FORMAT = "urn:ref:registry:regulatory-native-source-pins:v1"
CONTROL_CAPTURE_FORMAT = "urn:ref:registry:regulatory-native-control-capture:v1"
PARSER_VERSION = "regulatory-native-controls-source-faithful-v1"

_SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")
_GIT_REVISION = re.compile(r"^[0-9a-f]{40}$")

ControlUse = Literal[
    "deterministicCodeOrClassification",
    "identifierAuthority",
    "sourceAssignedEvidence",
]
Extraction = Literal[
    "scalar",
    "jsonArrayFormat",
    "jsonArrayAgencySlug",
    "jsonArrayUnresolvedAgencyRawName",
]


class RegulatoryNativeControlError(ValueError):
    """A source pin, controlled value, or identifier cannot be preserved."""


def _sha256_bytes(value: bytes) -> str:
    return f"sha256:{hashlib.sha256(value).hexdigest()}"


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise RegulatoryNativeControlError(f"duplicate JSON object key {key!r}")
        result[key] = value
    return result


def _exact_keys(
    value: Mapping[str, Any],
    expected: set[str],
    label: str,
) -> None:
    actual = set(value)
    if actual != expected:
        raise RegulatoryNativeControlError(
            f"{label} fields changed; missing={sorted(expected - actual)}, extra={sorted(actual - expected)}"
        )


def _nonempty_text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise RegulatoryNativeControlError(f"{label} must be non-empty text")
    return value


def _unique_text_list(value: object, label: str) -> tuple[str, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)) or not value:
        raise RegulatoryNativeControlError(f"{label} must be a non-empty text array")
    result = tuple(_nonempty_text(item, f"{label}[{index}]") for index, item in enumerate(value))
    if len(result) != len(set(result)):
        raise RegulatoryNativeControlError(f"{label} contains duplicates")
    return result


def _https_uri(value: object, label: str) -> str:
    text = _nonempty_text(value, label)
    parsed = urlparse(text)
    if parsed.scheme != "https" or not parsed.netloc:
        raise RegulatoryNativeControlError(f"{label} must be an absolute HTTPS URI")
    return text


def _observed_at(value: object, label: str) -> str:
    text = _nonempty_text(value, label)
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as error:
        raise RegulatoryNativeControlError(f"{label} must be an ISO date-time") from error
    if parsed.tzinfo is None:
        raise RegulatoryNativeControlError(f"{label} must include a timezone")
    return text


def _effective_on(value: object, label: str) -> str:
    text = _nonempty_text(value, label)
    try:
        date.fromisoformat(text)
    except ValueError as error:
        raise RegulatoryNativeControlError(f"{label} must be an ISO date") from error
    return text


@dataclass(frozen=True, slots=True)
class SourcePin:
    """Exact identity of one Spicy Regs Parquet source."""

    table: str
    profile_ids: tuple[str, ...]
    uri: str
    sha256: str
    byte_length: int
    etag: str
    last_modified: str
    row_count: int
    columns: tuple[str, ...]

    def native_payload(self) -> dict[str, Any]:
        return {
            "byteLength": self.byte_length,
            "columns": list(self.columns),
            "etag": self.etag,
            "lastModified": self.last_modified,
            "profileIds": list(self.profile_ids),
            "rowCount": self.row_count,
            "sha256": self.sha256,
            "table": self.table,
            "uri": self.uri,
        }


@dataclass(frozen=True, slots=True)
class SourcePinSet:
    """One dated set of exact source objects and extraction code."""

    captured_at: str
    spicy_regs_revision: str
    sources: tuple[SourcePin, ...]

    @property
    def by_table(self) -> dict[str, SourcePin]:
        return {source.table: source for source in self.sources}

    def native_payload(self) -> dict[str, Any]:
        return {
            "capturedAt": self.captured_at,
            "format": SOURCE_PINS_FORMAT,
            "sources": [source.native_payload() for source in self.sources],
            "spicyRegsRevision": self.spicy_regs_revision,
        }


def _parse_source_pin(value: object, index: int) -> SourcePin:
    label = f"sources[{index}]"
    if not isinstance(value, Mapping):
        raise RegulatoryNativeControlError(f"{label} must be an object")
    _exact_keys(
        value,
        {
            "byteLength",
            "columns",
            "etag",
            "lastModified",
            "profileIds",
            "rowCount",
            "sha256",
            "table",
            "uri",
        },
        label,
    )
    sha256 = _nonempty_text(value["sha256"], f"{label}.sha256")
    if not _SHA256.fullmatch(sha256):
        raise RegulatoryNativeControlError(f"{label}.sha256 must be a SHA-256 digest")
    byte_length = value["byteLength"]
    row_count = value["rowCount"]
    if not isinstance(byte_length, int) or byte_length <= 0:
        raise RegulatoryNativeControlError(f"{label}.byteLength must be positive")
    if not isinstance(row_count, int) or row_count < 0:
        raise RegulatoryNativeControlError(f"{label}.rowCount must be non-negative")
    return SourcePin(
        table=_nonempty_text(value["table"], f"{label}.table"),
        profile_ids=_unique_text_list(value["profileIds"], f"{label}.profileIds"),
        uri=_https_uri(value["uri"], f"{label}.uri"),
        sha256=sha256,
        byte_length=byte_length,
        etag=_nonempty_text(value["etag"], f"{label}.etag"),
        last_modified=_nonempty_text(value["lastModified"], f"{label}.lastModified"),
        row_count=row_count,
        columns=_unique_text_list(value["columns"], f"{label}.columns"),
    )


def parse_source_pins(payload: bytes) -> SourcePinSet:
    """Parse an exact source-pin document and reject shape drift."""

    if not isinstance(payload, bytes) or not payload:
        raise RegulatoryNativeControlError("source pins must be non-empty bytes")
    try:
        value = json.loads(payload, object_pairs_hook=_reject_duplicate_keys)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise RegulatoryNativeControlError("source pins must be valid UTF-8 JSON") from error
    if not isinstance(value, Mapping):
        raise RegulatoryNativeControlError("source pins must contain one object")
    _exact_keys(
        value,
        {"capturedAt", "format", "sources", "spicyRegsRevision"},
        "source pins",
    )
    if value["format"] != SOURCE_PINS_FORMAT:
        raise RegulatoryNativeControlError("unknown source-pins format")
    revision = _nonempty_text(value["spicyRegsRevision"], "spicyRegsRevision")
    if not _GIT_REVISION.fullmatch(revision):
        raise RegulatoryNativeControlError("spicyRegsRevision must be a 40-character Git revision")
    sources_value = value["sources"]
    if not isinstance(sources_value, list):
        raise RegulatoryNativeControlError("sources must be an array")
    sources = tuple(_parse_source_pin(source, index) for index, source in enumerate(sources_value))
    tables = [source.table for source in sources]
    expected_tables = [
        "dockets",
        "documents",
        "federal_register",
        "unified_agenda",
    ]
    if tables != expected_tables:
        raise RegulatoryNativeControlError(f"source tables must be {expected_tables}")
    return SourcePinSet(
        captured_at=_observed_at(value["capturedAt"], "capturedAt"),
        spicy_regs_revision=revision,
        sources=sources,
    )


def load_source_pins(path: Path) -> SourcePinSet:
    """Read and parse one source-pin document."""

    return parse_source_pins(path.read_bytes())


@dataclass(frozen=True, slots=True)
class ControlSpec:
    """One source field and the non-subject role assigned to its values."""

    control_id: str
    resource_id: str
    profile_ids: tuple[str, ...]
    source_table: str
    source_field: str
    extraction: Extraction
    facet: str
    use: ControlUse


CONTROL_SPECS: tuple[ControlSpec, ...] = (
    ControlSpec(
        "regulations-gov-docket-type",
        "regulations-gov-native-controls",
        ("regulations-docket-v2",),
        "dockets",
        "docket_type",
        "scalar",
        "urn:ref:facet:genre",
        "deterministicCodeOrClassification",
    ),
    ControlSpec(
        "regulations-gov-docket-agency-code",
        "regulations-gov-native-controls",
        ("regulations-docket-v2",),
        "dockets",
        "agency_code",
        "scalar",
        "urn:ref:facet:entity",
        "identifierAuthority",
    ),
    ControlSpec(
        "regulations-gov-document-type",
        "regulations-gov-native-controls",
        ("regulations-document-v2",),
        "documents",
        "document_type",
        "scalar",
        "urn:ref:facet:genre",
        "deterministicCodeOrClassification",
    ),
    ControlSpec(
        "regulations-gov-document-agency-code",
        "regulations-gov-native-controls",
        ("regulations-document-v2",),
        "documents",
        "agency_code",
        "scalar",
        "urn:ref:facet:entity",
        "identifierAuthority",
    ),
    ControlSpec(
        "regulations-gov-attachment-format",
        "regulations-gov-native-controls",
        ("regulations-document-v2",),
        "documents",
        "attachments_json",
        "jsonArrayFormat",
        "urn:ref:facet:code-list-value",
        "deterministicCodeOrClassification",
    ),
    ControlSpec(
        "federal-register-document-type",
        "federal-register-native-controls",
        ("federal-register-document-v1",),
        "federal_register",
        "document_type",
        "scalar",
        "urn:ref:facet:genre",
        "deterministicCodeOrClassification",
    ),
    ControlSpec(
        "federal-register-presidential-subtype",
        "federal-register-native-controls",
        ("federal-register-document-v1",),
        "federal_register",
        "subtype",
        "scalar",
        "urn:ref:facet:genre",
        "deterministicCodeOrClassification",
    ),
    ControlSpec(
        "federal-register-agency-slug",
        "federal-register-native-controls",
        ("federal-register-document-v1",),
        "federal_register",
        "agencies_json",
        "jsonArrayAgencySlug",
        "urn:ref:facet:entity",
        "identifierAuthority",
    ),
    ControlSpec(
        "federal-register-unresolved-agency-name",
        "federal-register-native-controls",
        ("federal-register-document-v1",),
        "federal_register",
        "agencies_json",
        "jsonArrayUnresolvedAgencyRawName",
        "urn:ref:facet:entity",
        "sourceAssignedEvidence",
    ),
    ControlSpec(
        "unified-agenda-rin-status",
        "unified-agenda-native-controls",
        ("unified-agenda-observation-v1",),
        "unified_agenda",
        "rin_status",
        "scalar",
        "urn:ref:facet:administrative-process-stage",
        "deterministicCodeOrClassification",
    ),
    ControlSpec(
        "unified-agenda-rule-stage",
        "unified-agenda-native-controls",
        ("unified-agenda-observation-v1",),
        "unified_agenda",
        "rule_stage",
        "scalar",
        "urn:ref:facet:administrative-process-stage",
        "deterministicCodeOrClassification",
    ),
    ControlSpec(
        "unified-agenda-priority-category",
        "unified-agenda-native-controls",
        ("unified-agenda-observation-v1",),
        "unified_agenda",
        "priority_category",
        "scalar",
        "urn:ref:facet:code-list-value",
        "deterministicCodeOrClassification",
    ),
    ControlSpec(
        "unified-agenda-major-flag",
        "unified-agenda-native-controls",
        ("unified-agenda-observation-v1",),
        "unified_agenda",
        "major",
        "scalar",
        "urn:ref:facet:code-list-value",
        "deterministicCodeOrClassification",
    ),
    ControlSpec(
        "unified-agenda-agency-code",
        "unified-agenda-native-controls",
        ("unified-agenda-observation-v1",),
        "unified_agenda",
        "agency_code",
        "scalar",
        "urn:ref:facet:entity",
        "identifierAuthority",
    ),
)


@dataclass(frozen=True, slots=True)
class NativeValueCount:
    """One exact source literal and its observed occurrence count."""

    value: str
    count: int

    def native_payload(self) -> dict[str, Any]:
        return {"count": self.count, "value": self.value}


@dataclass(frozen=True, slots=True)
class ControlCapture:
    """Observed values for one declared source-native control."""

    spec: ControlSpec
    source_row_count: int
    source_field_missing_row_count: int
    value_occurrence_count: int
    unresolved_value_count: int
    values: tuple[NativeValueCount, ...]

    def native_payload(self) -> dict[str, Any]:
        return {
            "conceptIdentityPolicy": "notAConcept",
            "controlId": self.spec.control_id,
            "extraction": self.spec.extraction,
            "facet": self.spec.facet,
            "profileIds": list(self.spec.profile_ids),
            "resourceId": self.spec.resource_id,
            "sourceField": self.spec.source_field,
            "sourceFieldMissingRowCount": (self.source_field_missing_row_count),
            "sourceRowCount": self.source_row_count,
            "sourceTable": self.spec.source_table,
            "subjectUse": "forbidden",
            "unresolvedValueCount": self.unresolved_value_count,
            "use": self.spec.use,
            "valueOccurrenceCount": self.value_occurrence_count,
            "values": [value.native_payload() for value in self.values],
        }


IDENTIFIER_POLICY = {
    "canonicalIdentifierSelected": False,
    "cardinality": "zeroOrMore",
    "duplicatesPreserved": True,
    "requiredFields": [
        "value",
        "kind",
        "authorityUri",
        "sourceUri",
        "observedAt",
    ],
}


@dataclass(frozen=True, slots=True)
class RegulatoryNativeControlCapture:
    """The deterministic catalog generated from exact pinned source tables."""

    source_pins: SourcePinSet
    controls: tuple[ControlCapture, ...]

    def native_payload(self) -> dict[str, Any]:
        return {
            "capturedAt": self.source_pins.captured_at,
            "controls": [control.native_payload() for control in self.controls],
            "format": CONTROL_CAPTURE_FORMAT,
            "identifierPolicy": IDENTIFIER_POLICY,
            "parserVersion": PARSER_VERSION,
            "sourcePins": [source.native_payload() for source in self.source_pins.sources],
            "spicyRegsRevision": self.source_pins.spicy_regs_revision,
        }

    @property
    def digest(self) -> str:
        return _sha256_bytes(canonical_json(self.native_payload()).encode("utf-8"))


def _parse_array(value: object, label: str) -> list[object]:
    if isinstance(value, list):
        return value
    if not isinstance(value, str):
        raise RegulatoryNativeControlError(f"{label} must be a JSON array string")
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as error:
        raise RegulatoryNativeControlError(f"{label} must be valid JSON") from error
    if not isinstance(parsed, list):
        raise RegulatoryNativeControlError(f"{label} must contain a JSON array")
    return parsed


def _extract_values(
    spec: ControlSpec,
    raw: object,
    *,
    label: str,
) -> tuple[list[str], bool, int]:
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        return [], True, 0
    if spec.extraction == "scalar":
        if not isinstance(raw, str):
            raise RegulatoryNativeControlError(f"{label} must be text")
        return [raw], False, 0

    values: list[str] = []
    unresolved = 0
    for index, item in enumerate(_parse_array(raw, label)):
        item_label = f"{label}[{index}]"
        if not isinstance(item, Mapping):
            raise RegulatoryNativeControlError(f"{item_label} must be an object")
        if spec.extraction == "jsonArrayFormat":
            candidate = item.get("format")
        elif spec.extraction == "jsonArrayAgencySlug":
            candidate = item.get("slug")
        else:
            slug = item.get("slug")
            if isinstance(slug, str) and slug.strip():
                continue
            candidate = item.get("raw_name")
        if not isinstance(candidate, str) or not candidate.strip():
            unresolved += 1
            continue
        values.append(candidate)
    return values, False, unresolved


def capture_control_values(
    source_pins: SourcePinSet,
    rows_by_table: Mapping[str, Iterable[Mapping[str, object]]],
) -> RegulatoryNativeControlCapture:
    """Capture all declared controls from normalized Spicy Regs rows."""

    pin_by_table = source_pins.by_table
    if set(rows_by_table) != set(pin_by_table):
        raise RegulatoryNativeControlError("row tables must exactly match the source pins")
    controls: list[ControlCapture] = []
    specs_by_table: dict[str, list[ControlSpec]] = {}
    for spec in CONTROL_SPECS:
        specs_by_table.setdefault(spec.source_table, []).append(spec)

    for table in ("dockets", "documents", "federal_register", "unified_agenda"):
        table_specs = specs_by_table[table]
        counters = {spec.control_id: Counter() for spec in table_specs}
        missing = Counter()
        unresolved = Counter()
        source_row_count = 0
        for source_row_count, row in enumerate(
            rows_by_table[table],
            start=1,
        ):
            if not isinstance(row, Mapping):
                raise RegulatoryNativeControlError(f"{table} row {source_row_count - 1} must be an object")
            for spec in table_specs:
                extracted, is_missing, unresolved_count = _extract_values(
                    spec,
                    row.get(spec.source_field),
                    label=(f"{table}[{source_row_count - 1}].{spec.source_field}"),
                )
                counters[spec.control_id].update(extracted)
                missing[spec.control_id] += int(is_missing)
                unresolved[spec.control_id] += unresolved_count

        expected_rows = pin_by_table[table].row_count
        if source_row_count != expected_rows:
            raise RegulatoryNativeControlError(
                f"{table} row count differs from pin: {source_row_count} != {expected_rows}"
            )
        for spec in table_specs:
            values = tuple(
                NativeValueCount(value=value, count=count) for value, count in sorted(counters[spec.control_id].items())
            )
            controls.append(
                ControlCapture(
                    spec=spec,
                    source_row_count=source_row_count,
                    source_field_missing_row_count=missing[spec.control_id],
                    value_occurrence_count=sum(counters[spec.control_id].values()),
                    unresolved_value_count=unresolved[spec.control_id],
                    values=values,
                )
            )
    controls_by_id = {control.spec.control_id: control for control in controls}
    return RegulatoryNativeControlCapture(
        source_pins=source_pins,
        controls=tuple(controls_by_id[spec.control_id] for spec in CONTROL_SPECS),
    )


def _verify_pinned_file(path: Path, pin: SourcePin) -> None:
    if not path.is_file() or path.is_symlink():
        raise RegulatoryNativeControlError(f"{pin.table} input must be a regular file")
    byte_length = path.stat().st_size
    if byte_length != pin.byte_length:
        raise RegulatoryNativeControlError(f"{pin.table} byte length differs from pin")
    digest = _sha256_bytes(path.read_bytes())
    if digest != pin.sha256:
        raise RegulatoryNativeControlError(f"{pin.table} digest differs from pin")
    columns = tuple(pq.ParquetFile(path).schema_arrow.names)
    if columns != pin.columns:
        raise RegulatoryNativeControlError(f"{pin.table} columns differ from pin")


def capture_control_values_from_parquet(
    source_pins: SourcePinSet,
    paths_by_table: Mapping[str, Path],
) -> RegulatoryNativeControlCapture:
    """Capture controls from exact local copies of the pinned Parquet files."""

    if set(paths_by_table) != set(source_pins.by_table):
        raise RegulatoryNativeControlError("Parquet tables must exactly match the source pins")
    required_by_table: dict[str, tuple[str, ...]] = {}
    for table in paths_by_table:
        required_by_table[table] = tuple(
            dict.fromkeys(spec.source_field for spec in CONTROL_SPECS if spec.source_table == table)
        )

    def rows(table: str, path: Path) -> Iterable[Mapping[str, object]]:
        for batch in pq.ParquetFile(path).iter_batches(
            columns=required_by_table[table],
            batch_size=50_000,
        ):
            yield from batch.to_pylist()

    for table, path in paths_by_table.items():
        _verify_pinned_file(path, source_pins.by_table[table])
    return capture_control_values(
        source_pins,
        {table: rows(table, path) for table, path in paths_by_table.items()},
    )


def render_control_capture(
    capture: RegulatoryNativeControlCapture,
) -> bytes:
    """Render one stable, reviewable capture document."""

    return (
        json.dumps(
            capture.native_payload(),
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def _parse_capture_mapping(
    value: Mapping[str, Any],
) -> RegulatoryNativeControlCapture:
    _exact_keys(
        value,
        {
            "capturedAt",
            "controls",
            "format",
            "identifierPolicy",
            "parserVersion",
            "sourcePins",
            "spicyRegsRevision",
        },
        "control capture",
    )
    if value["format"] != CONTROL_CAPTURE_FORMAT:
        raise RegulatoryNativeControlError("unknown control-capture format")
    if value["parserVersion"] != PARSER_VERSION:
        raise RegulatoryNativeControlError("unknown control-capture parser version")
    if value["identifierPolicy"] != IDENTIFIER_POLICY:
        raise RegulatoryNativeControlError(
            "identifier policy must preserve zero-or-more observations without selecting a canonical identifier"
        )
    pin_payload = {
        "capturedAt": value["capturedAt"],
        "format": SOURCE_PINS_FORMAT,
        "sources": value["sourcePins"],
        "spicyRegsRevision": value["spicyRegsRevision"],
    }
    source_pins = parse_source_pins(canonical_json(pin_payload).encode("utf-8"))
    controls_value = value["controls"]
    if not isinstance(controls_value, list):
        raise RegulatoryNativeControlError("controls must be an array")
    if len(controls_value) != len(CONTROL_SPECS):
        raise RegulatoryNativeControlError("control capture does not cover every declared control")

    controls: list[ControlCapture] = []
    for index, (item, spec) in enumerate(zip(controls_value, CONTROL_SPECS, strict=True)):
        label = f"controls[{index}]"
        if not isinstance(item, Mapping):
            raise RegulatoryNativeControlError(f"{label} must be an object")
        _exact_keys(
            item,
            {
                "conceptIdentityPolicy",
                "controlId",
                "extraction",
                "facet",
                "profileIds",
                "resourceId",
                "sourceField",
                "sourceFieldMissingRowCount",
                "sourceRowCount",
                "sourceTable",
                "subjectUse",
                "unresolvedValueCount",
                "use",
                "valueOccurrenceCount",
                "values",
            },
            label,
        )
        expected_static = {
            "conceptIdentityPolicy": "notAConcept",
            "controlId": spec.control_id,
            "extraction": spec.extraction,
            "facet": spec.facet,
            "profileIds": list(spec.profile_ids),
            "resourceId": spec.resource_id,
            "sourceField": spec.source_field,
            "sourceTable": spec.source_table,
            "subjectUse": "forbidden",
            "use": spec.use,
        }
        for field, expected in expected_static.items():
            if item[field] != expected:
                raise RegulatoryNativeControlError(f"{label}.{field} differs from its declared control")
        integers: dict[str, int] = {}
        for field in (
            "sourceFieldMissingRowCount",
            "sourceRowCount",
            "unresolvedValueCount",
            "valueOccurrenceCount",
        ):
            field_value = item[field]
            if not isinstance(field_value, int) or field_value < 0:
                raise RegulatoryNativeControlError(f"{label}.{field} must be non-negative")
            integers[field] = field_value
        if integers["sourceRowCount"] != source_pins.by_table[spec.source_table].row_count:
            raise RegulatoryNativeControlError(f"{label}.sourceRowCount differs from its source pin")
        values_value = item["values"]
        if not isinstance(values_value, list):
            raise RegulatoryNativeControlError(f"{label}.values must be an array")
        values: list[NativeValueCount] = []
        seen: set[str] = set()
        for value_index, value_item in enumerate(values_value):
            value_label = f"{label}.values[{value_index}]"
            if not isinstance(value_item, Mapping):
                raise RegulatoryNativeControlError(f"{value_label} must be an object")
            _exact_keys(value_item, {"count", "value"}, value_label)
            literal = _nonempty_text(value_item["value"], f"{value_label}.value")
            count = value_item["count"]
            if not isinstance(count, int) or count <= 0:
                raise RegulatoryNativeControlError(f"{value_label}.count must be positive")
            if literal in seen:
                raise RegulatoryNativeControlError(f"{label}.values repeats {literal!r}")
            seen.add(literal)
            values.append(NativeValueCount(literal, count))
        if [value.value for value in values] != sorted(seen):
            raise RegulatoryNativeControlError(f"{label}.values must use source-literal order")
        if sum(value.count for value in values) != integers["valueOccurrenceCount"]:
            raise RegulatoryNativeControlError(f"{label}.valueOccurrenceCount differs from value counts")
        if (
            spec.extraction == "scalar"
            and integers["valueOccurrenceCount"] + integers["sourceFieldMissingRowCount"] != integers["sourceRowCount"]
        ):
            raise RegulatoryNativeControlError(f"{label} scalar coverage does not equal its source rows")
        controls.append(
            ControlCapture(
                spec=spec,
                source_row_count=integers["sourceRowCount"],
                source_field_missing_row_count=integers["sourceFieldMissingRowCount"],
                value_occurrence_count=integers["valueOccurrenceCount"],
                unresolved_value_count=integers["unresolvedValueCount"],
                values=tuple(values),
            )
        )
    return RegulatoryNativeControlCapture(
        source_pins=source_pins,
        controls=tuple(controls),
    )


def parse_control_capture(
    payload: bytes,
    *,
    expected_sha256: str | None = None,
    expected_byte_length: int | None = None,
) -> RegulatoryNativeControlCapture:
    """Parse and verify one exact checked-in controlled-value capture."""

    if not isinstance(payload, bytes) or not payload:
        raise RegulatoryNativeControlError("control capture must be non-empty bytes")
    if expected_byte_length is not None and len(payload) != expected_byte_length:
        raise RegulatoryNativeControlError("control capture byte length differs from pin")
    actual_sha256 = _sha256_bytes(payload)
    if expected_sha256 is not None and actual_sha256 != expected_sha256:
        raise RegulatoryNativeControlError("control capture digest differs from pin")
    try:
        value = json.loads(payload, object_pairs_hook=_reject_duplicate_keys)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise RegulatoryNativeControlError("control capture must be valid UTF-8 JSON") from error
    if not isinstance(value, Mapping):
        raise RegulatoryNativeControlError("control capture must contain one object")
    return _parse_capture_mapping(value)


@dataclass(frozen=True, slots=True)
class IdentifierObservation:
    """One source-authored identifier observation; never a canonical choice."""

    identifier: ControlledIdentifier
    source_table: str
    source_field: str
    source_ordinal: int
    source_record_key: tuple[tuple[str, str], ...]
    label: str | None = None

    def __post_init__(self) -> None:
        _nonempty_text(self.source_table, "identifier.sourceTable")
        _nonempty_text(self.source_field, "identifier.sourceField")
        if not isinstance(self.source_ordinal, int) or self.source_ordinal < 0:
            raise RegulatoryNativeControlError("identifier.sourceOrdinal must be non-negative")
        if not self.source_record_key:
            raise RegulatoryNativeControlError("identifier.sourceRecordKey must not be empty")
        for key, value in self.source_record_key:
            _nonempty_text(key, "identifier.sourceRecordKey key")
            _nonempty_text(value, "identifier.sourceRecordKey value")
        if self.label is not None:
            _nonempty_text(self.label, "identifier.label")

    @property
    def value(self) -> str:
        return self.identifier.value

    @property
    def kind(self) -> str:
        return self.identifier.kind

    @property
    def authority_uri(self) -> str:
        return self.identifier.authority_uri

    @property
    def source_uri(self) -> str:
        return self.identifier.source_uri

    @property
    def observed_at(self) -> str | None:
        return self.identifier.observed_at

    @property
    def effective_at(self) -> str | None:
        return self.identifier.effective_at

    def native_payload(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            **self.identifier.as_dict(),
            "sourceField": self.source_field,
            "sourceOrdinal": self.source_ordinal,
            "sourceRecordKey": dict(self.source_record_key),
            "sourceTable": self.source_table,
        }
        if self.label is not None:
            result["label"] = self.label
        return result


def _text_value(value: object) -> str | None:
    return value if isinstance(value, str) and value.strip() else None


def _json_text_values(value: object, label: str) -> list[str]:
    result: list[str] = []
    for index, item in enumerate(_parse_array(value, label)):
        if not isinstance(item, str) or not item.strip():
            raise RegulatoryNativeControlError(f"{label}[{index}] must be non-empty text")
        result.append(item)
    return result


def extract_identifier_observations(
    source_table: str,
    row: Mapping[str, object],
    *,
    observed_at: str,
    source_digest: str | None = None,
) -> tuple[IdentifierObservation, ...]:
    """Extract zero-or-more identifiers without selecting a canonical value."""

    _observed_at(observed_at, "observedAt")
    observations: list[IdentifierObservation] = []

    if source_table == "dockets":
        record_id = _text_value(row.get("docket_id"))
        if record_id is None:
            return ()
        source_uri = f"https://www.regulations.gov/docket/{quote(record_id, safe='')}"
        record_key = (("docket_id", record_id),)
    elif source_table == "documents":
        record_id = _text_value(row.get("document_id"))
        if record_id is None:
            return ()
        source_uri = f"https://www.regulations.gov/document/{quote(record_id, safe='')}"
        record_key = (("document_id", record_id),)
    elif source_table == "federal_register":
        record_id = _text_value(row.get("document_number"))
        if record_id is None:
            return ()
        row_uri = _text_value(row.get("html_url"))
        source_uri = (
            row_uri
            if row_uri and urlparse(row_uri).scheme == "https"
            else (f"https://www.federalregister.gov/d/{quote(record_id, safe='')}")
        )
        record_key = (("document_number", record_id),)
    elif source_table == "unified_agenda":
        rin = _text_value(row.get("rin"))
        edition = _text_value(row.get("agenda_edition"))
        if rin is None or edition is None:
            return ()
        row_uri = _text_value(row.get("url"))
        source_uri = (
            row_uri
            if row_uri and urlparse(row_uri).scheme == "https"
            else (
                "https://www.reginfo.gov/public/do/eAgendaViewRule"
                f"?pubId={quote(edition, safe='')}"
                f"&RIN={quote(rin, safe='')}"
            )
        )
        record_key = (("agenda_edition", edition), ("rin", rin))
    else:
        raise RegulatoryNativeControlError(f"unsupported identifier source table {source_table!r}")

    def add(
        value: object,
        *,
        kind: str,
        authority_uri: str,
        source_field: str,
        source_ordinal: int = 0,
        label: str | None = None,
        effective_on: str | None = None,
    ) -> None:
        text = _text_value(value)
        if text is None:
            return
        observations.append(
            IdentifierObservation(
                identifier=ControlledIdentifier(
                    value=text,
                    kind=kind,
                    authority_uri=authority_uri,
                    source_uri=source_uri,
                    observed_at=observed_at,
                    effective_at=effective_on,
                    source_digest=source_digest,
                ),
                source_table=source_table,
                source_field=source_field,
                source_ordinal=source_ordinal,
                source_record_key=record_key,
                label=label,
            )
        )

    regsgov = "https://www.regulations.gov/"
    regsgov_api = "https://open.gsa.gov/api/regulationsgov/"
    reginfo = "https://www.reginfo.gov/public/do/eAgendaMain"
    federal_register = "https://www.federalregister.gov/"

    if source_table == "dockets":
        add(
            row.get("docket_id"),
            kind="regulationsGovDocketId",
            authority_uri=regsgov,
            source_field="docket_id",
        )
        add(
            row.get("agency_code"),
            kind="regulationsGovAgencyCode",
            authority_uri=regsgov_api,
            source_field="agency_code",
        )
        add(
            row.get("rin"),
            kind="regulationIdentifierNumber",
            authority_uri=reginfo,
            source_field="rin",
        )
    elif source_table == "documents":
        add(
            row.get("document_id"),
            kind="regulationsGovDocumentId",
            authority_uri=regsgov,
            source_field="document_id",
        )
        add(
            row.get("docket_id"),
            kind="regulationsGovDocketId",
            authority_uri=regsgov,
            source_field="docket_id",
        )
        add(
            row.get("agency_code"),
            kind="regulationsGovAgencyCode",
            authority_uri=regsgov_api,
            source_field="agency_code",
        )
        add(
            row.get("fr_doc_num"),
            kind="federalRegisterDocumentNumber",
            authority_uri=federal_register,
            source_field="fr_doc_num",
        )
        additional = row.get("additional_rins")
        if additional is not None and additional != "":
            for ordinal, rin in enumerate(
                _json_text_values(
                    additional,
                    "documents.additional_rins",
                )
            ):
                add(
                    rin,
                    kind="regulationIdentifierNumber",
                    authority_uri=reginfo,
                    source_field="additional_rins",
                    source_ordinal=ordinal,
                )
    elif source_table == "federal_register":
        effective = _text_value(row.get("effective_on"))
        if effective is not None:
            _effective_on(effective, "federal_register.effective_on")
        add(
            row.get("document_number"),
            kind="federalRegisterDocumentNumber",
            authority_uri=federal_register,
            source_field="document_number",
            effective_on=effective,
        )
        add(
            row.get("executive_order_number"),
            kind="executiveOrderNumber",
            authority_uri=federal_register,
            source_field="executive_order_number",
            effective_on=effective,
        )
        agencies = row.get("agencies_json")
        if agencies is not None and agencies != "":
            for ordinal, agency in enumerate(_parse_array(agencies, "federal_register.agencies_json")):
                if not isinstance(agency, Mapping):
                    raise RegulatoryNativeControlError("federal_register.agencies_json entries must be objects")
                agency_label = _text_value(agency.get("name"))
                add(
                    (str(agency["id"]) if agency.get("id") is not None else None),
                    kind="federalRegisterAgencyId",
                    authority_uri=("https://www.federalregister.gov/agencies"),
                    source_field="agencies_json.id",
                    source_ordinal=ordinal,
                    label=agency_label,
                )
                add(
                    agency.get("slug"),
                    kind="federalRegisterAgencySlug",
                    authority_uri=("https://www.federalregister.gov/agencies"),
                    source_field="agencies_json.slug",
                    source_ordinal=ordinal,
                    label=agency_label,
                )
        for field, kind, authority in (
            (
                "docket_ids_json",
                "federalRegisterDocketReference",
                ("https://www.federalregister.gov/developers/documentation/api/v1"),
            ),
            (
                "regulation_id_numbers_json",
                "regulationIdentifierNumber",
                reginfo,
            ),
        ):
            raw_values = row.get(field)
            if raw_values is None or raw_values == "":
                continue
            for ordinal, raw_value in enumerate(
                _json_text_values(
                    raw_values,
                    f"federal_register.{field}",
                )
            ):
                add(
                    raw_value,
                    kind=kind,
                    authority_uri=authority,
                    source_field=field,
                    source_ordinal=ordinal,
                )
    else:
        agency_name = _text_value(row.get("agency_name"))
        add(
            row.get("rin"),
            kind="regulationIdentifierNumber",
            authority_uri=reginfo,
            source_field="rin",
        )
        add(
            row.get("agency_code"),
            kind="unifiedAgendaAgencyCode",
            authority_uri=reginfo,
            source_field="agency_code",
            label=agency_name,
        )
        add(
            row.get("publication_id"),
            kind="unifiedAgendaPublicationId",
            authority_uri=reginfo,
            source_field="publication_id",
        )
    return tuple(observations)
