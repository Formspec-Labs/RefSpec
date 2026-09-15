"""Frozen CFR metadata readers from RefSpec 1ffeb5ba; test-only comparison.

Bodies and their local dependencies copied from registry/cfr_list_of_subjects.py.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from html import unescape
from typing import Any
from urllib.parse import urlsplit

ECFR_AGENCIES_URL = "https://www.ecfr.gov/api/admin/v1/agencies.json"


ECFR_AGENCIES_LICENSE_RIGHTS_STATEMENT = "US federal public domain (17 USC 105) with no explicit CC license"


ECFR_AGENCIES_SOURCE_VERSION_NOTE = (
    "The publisher exposes this as a rolling, unversioned endpoint; no versioned URL is available."
)


_SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")


ECFR_AGENCIES_EXPECTED_TOP_LEVEL_COUNT = 153


ECFR_AGENCIES_EXPECTED_AGENCY_COUNT = 316


ECFR_AGENCIES_EXPECTED_REFERENCE_COUNT = 487


ECFR_AGENCIES_EXPECTED_REFERENCED_AGENCY_COUNT = 315


ECFR_AGENCIES_EXPECTED_REFERENCED_TITLE_COUNT = 49


class CFRListOfSubjectsError(ValueError):
    """Publisher bytes cannot be represented without guessing."""


class CFRSourceDriftError(CFRListOfSubjectsError):
    """A publisher response no longer matches the reviewed source shape."""


def sha256_digest(payload: bytes) -> str:
    """Return the canonical RefSpec spelling for a SHA-256 digest."""

    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _json_object(payload: bytes, label: str) -> Mapping[str, Any]:
    if not isinstance(payload, bytes) or not payload:
        raise CFRSourceDriftError(f"{label} must be non-empty bytes")
    try:
        value = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise CFRSourceDriftError(f"{label} is not valid UTF-8 JSON") from error
    if not isinstance(value, Mapping):
        raise CFRSourceDriftError(f"{label} root must be an object")
    return value


def _required_text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise CFRSourceDriftError(f"{label} must be non-empty text")
    return value


@dataclass(frozen=True, slots=True)
class EcfrAgenciesSnapshotPin:
    """Exact identity and rights record for one eCFR agencies response."""

    source_url: str
    retrieved_at: str
    expected_sha256: str
    expected_byte_length: int
    license_rights_statement: str
    source_version_note: str

    def __post_init__(self) -> None:
        parsed = urlsplit(self.source_url)
        if (
            parsed.scheme != "https"
            or parsed.hostname != "www.ecfr.gov"
            or parsed.username is not None
            or parsed.password is not None
        ):
            raise CFRListOfSubjectsError("eCFR agencies source_url must be the official credential-free HTTPS endpoint")
        if parsed.query or parsed.fragment:
            raise CFRListOfSubjectsError("eCFR agencies source_url must not carry a query or fragment")
        if _SHA256.fullmatch(self.expected_sha256) is None:
            raise CFRListOfSubjectsError("eCFR agencies expected_sha256 must be sha256:<64 lowercase hex>")
        if self.expected_byte_length <= 0:
            raise CFRListOfSubjectsError("eCFR agencies expected_byte_length must be positive")
        if not self.retrieved_at.endswith("Z"):
            raise CFRListOfSubjectsError("eCFR agencies retrieved_at must be a UTC timestamp")
        if not self.license_rights_statement:
            raise CFRListOfSubjectsError("eCFR agencies license/rights statement must not be empty")
        if "unversioned" not in self.source_version_note:
            raise CFRListOfSubjectsError("eCFR agencies source version note must record the rolling endpoint")


ECFR_AGENCIES_2026_08_15 = EcfrAgenciesSnapshotPin(
    source_url=ECFR_AGENCIES_URL,
    retrieved_at="2026-08-15T22:51:57Z",
    expected_sha256="sha256:766685f466d62fa558a504cdeac23eef1d41f3ea24a2f5a3f78b38f2bcd5365e",
    expected_byte_length=98_197,
    license_rights_statement=ECFR_AGENCIES_LICENSE_RIGHTS_STATEMENT,
    source_version_note=ECFR_AGENCIES_SOURCE_VERSION_NOTE,
)


@dataclass(frozen=True, slots=True)
class EcfrAgencyCfrReference:
    """One eCFR-published agency reference to CFR structure."""

    title: int
    source_ordinal: int
    chapter: str | None
    subtitle: str | None
    subchapter: str | None
    part: str | None
    raw: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class EcfrAgencyRecord:
    """One agency row from the nested eCFR administrative roster."""

    name: str
    short_name: str | None
    display_name: str
    sortable_name: str
    slug: str
    parent_slug: str | None
    child_slugs: tuple[str, ...]
    source_path: str
    references: tuple[EcfrAgencyCfrReference, ...]
    raw: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class EcfrAgencyRoster:
    """The complete digest-pinned eCFR agency roster and all CFR references."""

    source_url: str
    retrieved_at: str
    source_sha256: str
    source_byte_length: int
    records: tuple[EcfrAgencyRecord, ...]
    top_level_agency_count: int
    reference_count: int
    referenced_agency_count: int
    referenced_title_count: int

    def by_slug(self) -> dict[str, EcfrAgencyRecord]:
        return {record.slug: record for record in self.records}


_ECFR_AGENCY_FIELDS = frozenset(
    {
        "name",
        "short_name",
        "display_name",
        "sortable_name",
        "slug",
        "cfr_references",
    }
)


_ECFR_REFERENCE_FIELD_SETS = frozenset(
    {
        frozenset({"title", "chapter"}),
        frozenset({"title", "subtitle"}),
        frozenset({"title", "chapter", "subchapter"}),
        frozenset({"title", "chapter", "part"}),
        frozenset({"title", "chapter", "subtitle"}),
    }
)


def _ecfr_optional_text(value: object, label: str) -> str | None:
    if value is None or value == "":
        return None
    return _required_text(value, label)


def _parse_ecfr_agency_reference(value: object, *, path: str, ordinal: int) -> EcfrAgencyCfrReference:
    label = f"{path}.cfr_references[{ordinal}]"
    if not isinstance(value, Mapping) or frozenset(value) not in _ECFR_REFERENCE_FIELD_SETS:
        fields = sorted(value) if isinstance(value, Mapping) else type(value).__name__
        raise CFRSourceDriftError(f"{label} fields drifted: {fields}")
    title = value["title"]
    if not isinstance(title, int) or isinstance(title, bool) or not 1 <= title <= 50:
        raise CFRSourceDriftError(f"{label}.title must be an integer from 1 through 50")
    return EcfrAgencyCfrReference(
        title=title,
        source_ordinal=ordinal,
        chapter=_ecfr_optional_text(value.get("chapter"), f"{label}.chapter"),
        subtitle=_ecfr_optional_text(value.get("subtitle"), f"{label}.subtitle"),
        subchapter=_ecfr_optional_text(value.get("subchapter"), f"{label}.subchapter"),
        part=_ecfr_optional_text(value.get("part"), f"{label}.part"),
        raw=value,
    )


def _parse_ecfr_agency_rows(
    values: object,
    *,
    path: str,
    parent_slug: str | None,
) -> tuple[EcfrAgencyRecord, ...]:
    if not isinstance(values, list):
        raise CFRSourceDriftError(f"{path} must be an array")
    parsed: list[EcfrAgencyRecord] = []
    for ordinal, value in enumerate(values):
        row_path = f"{path}[{ordinal}]"
        if not isinstance(value, Mapping):
            raise CFRSourceDriftError(f"{row_path} must be an object")
        fields = frozenset(value)
        if fields not in {_ECFR_AGENCY_FIELDS, _ECFR_AGENCY_FIELDS | {"children"}}:
            raise CFRSourceDriftError(f"{row_path} fields drifted: {sorted(fields)}")
        slug = _required_text(value["slug"], f"{row_path}.slug")
        short_name = _ecfr_optional_text(value["short_name"], f"{row_path}.short_name")
        references_value = value["cfr_references"]
        if not isinstance(references_value, list):
            raise CFRSourceDriftError(f"{row_path}.cfr_references must be an array")
        references = tuple(
            _parse_ecfr_agency_reference(item, path=row_path, ordinal=reference_ordinal)
            for reference_ordinal, item in enumerate(references_value)
        )
        child_values = value.get("children", [])
        if not isinstance(child_values, list):
            raise CFRSourceDriftError(f"{row_path}.children must be an array")
        child_slugs = tuple(
            _required_text(child.get("slug"), f"{row_path}.children[{child_ordinal}].slug")
            if isinstance(child, Mapping)
            else ""
            for child_ordinal, child in enumerate(child_values)
        )
        if "" in child_slugs:
            raise CFRSourceDriftError(f"{row_path}.children entries must be objects")
        parsed.append(
            EcfrAgencyRecord(
                name=_required_text(value["name"], f"{row_path}.name"),
                short_name=short_name,
                display_name=_required_text(value["display_name"], f"{row_path}.display_name"),
                sortable_name=_required_text(value["sortable_name"], f"{row_path}.sortable_name"),
                slug=slug,
                parent_slug=parent_slug,
                child_slugs=child_slugs,
                source_path=row_path,
                references=references,
                raw=value,
            )
        )
        parsed.extend(_parse_ecfr_agency_rows(child_values, path=f"{row_path}.children", parent_slug=slug))
    return tuple(parsed)


def parse_ecfr_agency_roster(
    payload: bytes,
    *,
    pin: EcfrAgenciesSnapshotPin = ECFR_AGENCIES_2026_08_15,
) -> EcfrAgencyRoster:
    """Parse the complete eCFR agency roster after refusing byte or shape drift."""

    if len(payload) != pin.expected_byte_length:
        raise CFRSourceDriftError(
            f"eCFR agencies byte length drift: expected {pin.expected_byte_length}, got {len(payload)}"
        )
    digest = sha256_digest(payload)
    if digest != pin.expected_sha256:
        raise CFRSourceDriftError(f"eCFR agencies digest drift: expected {pin.expected_sha256}, got {digest}")
    root = _json_object(payload, "eCFR agencies response")
    if set(root) != {"agencies"}:
        raise CFRSourceDriftError(f"eCFR agencies response fields drifted: {sorted(root)}")
    top_level = root["agencies"]
    records = _parse_ecfr_agency_rows(top_level, path="$.agencies", parent_slug=None)
    if not isinstance(top_level, list):
        raise CFRSourceDriftError("eCFR agencies response must contain an agencies array")

    slugs = [record.slug for record in records]
    if len(slugs) != len(set(slugs)):
        raise CFRSourceDriftError("eCFR agencies response repeats an agency slug")
    references = [reference for record in records for reference in record.references]
    referenced_agencies = sum(bool(record.references) for record in records)
    referenced_titles = {reference.title for reference in references}
    observed = (
        len(top_level),
        len(records),
        len(references),
        referenced_agencies,
        len(referenced_titles),
    )
    expected = (
        ECFR_AGENCIES_EXPECTED_TOP_LEVEL_COUNT,
        ECFR_AGENCIES_EXPECTED_AGENCY_COUNT,
        ECFR_AGENCIES_EXPECTED_REFERENCE_COUNT,
        ECFR_AGENCIES_EXPECTED_REFERENCED_AGENCY_COUNT,
        ECFR_AGENCIES_EXPECTED_REFERENCED_TITLE_COUNT,
    )
    if observed != expected:
        raise CFRSourceDriftError(
            "eCFR agencies counts drifted: "
            f"expected top/total/references/referenced-agencies/titles={expected}, got {observed}"
        )
    return EcfrAgencyRoster(
        source_url=pin.source_url,
        retrieved_at=pin.retrieved_at,
        source_sha256=digest,
        source_byte_length=len(payload),
        records=records,
        top_level_agency_count=len(top_level),
        reference_count=len(references),
        referenced_agency_count=referenced_agencies,
        referenced_title_count=len(referenced_titles),
    )


@dataclass(frozen=True, slots=True)
class CfrSubjectIndexPin:
    """Exact identity and rights record for one archives.gov subject-index page."""

    source_url: str
    retrieved_at: str
    expected_sha256: str
    expected_byte_length: int
    cfr_title: int
    revision_note: str

    def __post_init__(self) -> None:
        parsed = urlsplit(self.source_url)
        if (
            parsed.scheme != "https"
            or parsed.hostname != "www.archives.gov"
            or parsed.username is not None
            or parsed.password is not None
        ):
            raise CFRListOfSubjectsError(
                "CFR subject index source_url must be the official credential-free archives.gov endpoint"
            )
        if parsed.query or parsed.fragment:
            raise CFRListOfSubjectsError("CFR subject index source_url must not carry a query or fragment")
        if parsed.path != f"/federal-register/cfr/subject-title-{self.cfr_title:02d}.html":
            raise CFRListOfSubjectsError("CFR subject index source_url does not match its declared title")
        if _SHA256.fullmatch(self.expected_sha256) is None:
            raise CFRListOfSubjectsError("CFR subject index expected_sha256 must be sha256:<64 lowercase hex>")
        if self.expected_byte_length <= 0:
            raise CFRListOfSubjectsError("CFR subject index expected_byte_length must be positive")
        if not self.retrieved_at.endswith("Z"):
            raise CFRListOfSubjectsError("CFR subject index retrieved_at must be a UTC timestamp")
        if not (1 <= self.cfr_title <= 50):
            raise CFRListOfSubjectsError("CFR title must be between 1 and 50")
        if "current as of" not in self.revision_note:
            raise CFRListOfSubjectsError("CFR subject index revision note must record the publisher's revision date")


@dataclass(frozen=True, slots=True)
class CfrPartSubjects:
    """One CFR part and the index terms the publisher assigns to it."""

    cfr_title: int
    cfr_part: str
    part_heading: str
    terms: tuple[str, ...]


_SUBJECT_DT_DD = re.compile(
    r"<dt>(?P<dt>(?:(?!</dt>).)*?)</dt>"
    # Between a heading and its first term the publisher may emit a malformed
    # element -- 45 CFR 2531 is preceded by ``<ddgrant programs="" ...>``, an
    # unclosed ``<dd>`` whose term was swallowed into the tag name. Skipping
    # any run that reaches neither a ``<dt`` nor a ``<dd>`` keeps that part's
    # real terms; requiring ``<dd>`` immediately dropped the part outright.
    r"(?P<gap>(?:(?!<dt[\s>])(?!<dd>).)*)"
    r"(?P<dds>(?:\s*<dd>.*?</dd>)+)",
    re.DOTALL | re.IGNORECASE,
)


_SUBJECT_DD = re.compile(r"<dd>(.*?)</dd>", re.DOTALL | re.IGNORECASE)


_SUBJECT_TAGS = re.compile(r"<[^>]*>")


_SUBJECT_HEAD = re.compile(
    r"(?P<title>\d{1,2})\s*CFR\s*(?:(?P<kw>Parts?|Oart|Chapter)\s*)?"
    r"(?P<part>[0-9][0-9A-Za-z.\-]*)\s*[_\u2014\u2013-]\s*(?P<heading>.*)",
    re.IGNORECASE | re.DOTALL,
)


_SUBJECT_LEAKED_TAG = "strong>"


CFR_RESERVED_TITLES: frozenset[int] = frozenset({35})


def _subject_text(fragment: str) -> str:
    return " ".join(unescape(_SUBJECT_TAGS.sub(" ", fragment)).split())


def parse_cfr_subject_index(
    payload: bytes,
    *,
    pin: CfrSubjectIndexPin,
) -> tuple[CfrPartSubjects, ...]:
    """Parse one archives.gov subject-index page into publisher part assignments.

    Fail-closed in both directions. The payload must match the pin's digest
    and byte length exactly, and every ``<dt>`` that names a CFR citation must
    yield a title and a part or the parse raises -- an unmatched entry is
    never skipped. Entries whose declared title disagrees with the pin raise
    too, so a page fetched under the wrong title cannot be silently absorbed.
    """

    digest = sha256_digest(payload)
    if digest != pin.expected_sha256:
        raise CFRSourceDriftError(
            f"CFR subject index title {pin.cfr_title} digest {digest} does not match the pinned {pin.expected_sha256}"
        )
    if len(payload) != pin.expected_byte_length:
        raise CFRSourceDriftError(
            f"CFR subject index title {pin.cfr_title} is {len(payload)} bytes; pinned {pin.expected_byte_length}"
        )

    body = payload.decode("utf-8", errors="replace")
    parts: list[CfrPartSubjects] = []
    for match in _SUBJECT_DT_DD.finditer(body):
        entry = _subject_text(match.group("dt"))
        if not entry or "CFR" not in entry.upper():
            continue
        if entry.lower().startswith(_SUBJECT_LEAKED_TAG):
            entry = entry[len(_SUBJECT_LEAKED_TAG) :].lstrip()
        head = _SUBJECT_HEAD.match(entry)
        if head is None:
            raise CFRSourceDriftError(
                f"CFR subject index title {pin.cfr_title} has an unparsable part entry: {entry[:120]!r}"
            )
        declared_title = int(head.group("title"))
        if declared_title != pin.cfr_title:
            raise CFRSourceDriftError(
                f"CFR subject index for title {pin.cfr_title} contains a title {declared_title} entry"
            )
        # Fifth documented publisher irregularity, and the consequential one:
        # 32 part headings across 14 pages are marked up as <dd> rather than
        # <dt>. Left alone, the mistyped part vanishes AND its terms are
        # wrongly attributed to the part above it. Recover them as the part
        # headings they plainly are, rather than admitting them as terms.
        pending: list[tuple[str, str, list[str]]] = [
            (head.group("part").rstrip("."), head.group("heading").strip().rstrip("."), [])
        ]
        for raw_dd in _SUBJECT_DD.findall(match.group("dds")):
            value = _subject_text(raw_dd)
            if not value or value.upper() == "N/A":
                continue
            if value.lower().startswith(_SUBJECT_LEAKED_TAG):
                value = value[len(_SUBJECT_LEAKED_TAG) :].lstrip()
            nested = _SUBJECT_HEAD.match(value) if "CFR" in value.upper() else None
            if nested is not None and int(nested.group("title")) == declared_title:
                pending.append(
                    (
                        nested.group("part").rstrip("."),
                        nested.group("heading").strip().rstrip("."),
                        [],
                    )
                )
                continue
            pending[-1][2].append(value.rstrip("."))
        for part_number, heading, collected in pending:
            if not collected:
                continue
            parts.append(
                CfrPartSubjects(
                    cfr_title=declared_title,
                    cfr_part=part_number,
                    part_heading=heading,
                    terms=tuple(collected),
                )
            )
    if not parts and pin.cfr_title not in CFR_RESERVED_TITLES:
        raise CFRSourceDriftError(f"CFR subject index title {pin.cfr_title} yielded no part assignments")
    if parts and pin.cfr_title in CFR_RESERVED_TITLES:
        raise CFRSourceDriftError(
            f"CFR title {pin.cfr_title} is reserved but its subject index carries {len(parts)} parts"
        )
    return tuple(parts)


def _flatten_agencies(value: Sequence[object]) -> tuple[Mapping[str, Any], ...]:
    rows: list[Mapping[str, Any]] = []
    for ordinal, item in enumerate(value):
        if not isinstance(item, Mapping):
            raise CFRSourceDriftError(f"agencies[{ordinal}] must be an object")
        _required_text(item.get("name"), f"agencies[{ordinal}].name")
        _required_text(item.get("slug"), f"agencies[{ordinal}].slug")
        children = item.get("children", [])
        references = item.get("cfr_references")
        if not isinstance(children, list) or not isinstance(references, list):
            raise CFRSourceDriftError(f"agencies[{ordinal}] children and cfr_references must be arrays")
        rows.append(item)
        rows.extend(_flatten_agencies(children))
    return tuple(rows)
