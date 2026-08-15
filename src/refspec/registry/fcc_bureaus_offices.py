"""FCC's published Offices & Bureaus roster from fcc.gov.

REF-032 removed the observed FCC bureau inventory: a set-distinct over one
25-filing ECFS API response that carried the abolished Common Carrier Bureau
beside its successor. The named follow-up is the roster FCC itself publishes:
the ``Offices & Bureaus`` page at ``https://www.fcc.gov/offices-bureaus``,
which enumerates the Commission's offices and bureaus in two publisher-titled
sections, each entry a linked heading followed by the publisher's own
description paragraph.

The parser preserves the publisher's rendering verbatim: the two section
titles (``Offices``, ``Bureaus``), each entry's heading text, its fcc.gov
path, and its description. It refuses a page whose structure or entry counts
drift from the reviewed capture.

Importing this module performs no network access. The capture was fetched
through the shared Zyte transport because fcc.gov refuses plain clients.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Literal

FCC_PUBLISHER = "Federal Communications Commission"
FCC_OFFICES_BUREAUS_URL = "https://www.fcc.gov/offices-bureaus"
FCC_PAGE_HOST = "https://www.fcc.gov"

# The two publisher-titled sections, in page order, with the entry counts
# observed in the pinned capture. A different section set or count is drift.
FCC_EXPECTED_SECTIONS: tuple[tuple[str, int], ...] = (("Offices", 12), ("Bureaus", 7))

_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_PAGE_HREF = re.compile(r"^/[a-z0-9-]+$")

UnitKind = Literal["office", "bureau"]
_SECTION_KINDS: dict[str, UnitKind] = {"Offices": "office", "Bureaus": "bureau"}


class FccBureausOfficesError(ValueError):
    """Base class for FCC Offices & Bureaus roster failures."""


class FccSourceDriftError(FccBureausOfficesError):
    """The page no longer matches the reviewed structure or pin."""


@dataclass(frozen=True, slots=True)
class FccPagePin:
    """Exact identity of one captured fcc.gov page."""

    source_url: str
    retrieved_at: str
    expected_sha256: str
    expected_byte_length: int

    def __post_init__(self) -> None:
        if not self.source_url.startswith("https://www.fcc.gov/"):
            raise FccBureausOfficesError("source_url must be an official HTTPS fcc.gov URL")
        if _DIGEST.fullmatch(self.expected_sha256) is None:
            raise FccBureausOfficesError("expected_sha256 must be a lowercase sha256:<64 hex> digest")
        if self.expected_byte_length <= 0:
            raise FccBureausOfficesError("expected_byte_length must be positive")
        if not self.retrieved_at:
            raise FccBureausOfficesError("retrieved_at must not be empty")


FCC_OFFICES_BUREAUS_2026_08_15 = FccPagePin(
    source_url=FCC_OFFICES_BUREAUS_URL,
    retrieved_at="2026-08-15T07:50:53Z",
    expected_sha256="sha256:2915ee13f3dc07081671b70720e26ed1c376e7964d60cffa2ca4c1d7cab41f55",
    expected_byte_length=51_748,
)


def sha256_digest(payload: bytes) -> str:
    """Return the canonical RefSpec SHA-256 spelling."""

    return "sha256:" + hashlib.sha256(payload).hexdigest()


@dataclass(frozen=True, slots=True)
class FccOrganizationalUnit:
    """One office or bureau as the publisher's page states it."""

    kind: UnitKind
    name: str
    slug: str
    page_href: str
    page_url: str
    description: str
    source_ordinal: int


@dataclass(frozen=True, slots=True)
class FccBureausOfficesRoster:
    """The parsed, digest-pinned Offices & Bureaus roster."""

    units: tuple[FccOrganizationalUnit, ...]
    office_count: int
    bureau_count: int
    source_sha256: str
    source_byte_length: int
    retrieved_at: str

    def by_slug(self) -> dict[str, FccOrganizationalUnit]:
        return {unit.slug: unit for unit in self.units}


def _normalized(pieces: list[str]) -> str:
    return " ".join("".join(pieces).split())


class _RosterParser(HTMLParser):
    """Collect card-section titles and their heading/description entries."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.sections: list[tuple[str, list[dict[str, str]]]] = []
        self._collect: str | None = None
        self._buffer: list[str] = []
        self._depth = 0
        self._entry_href: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        classes = dict(attrs).get("class") or ""
        if tag == "div" and "component-card__field-card-header" in classes:
            self._collect = "section-title"
            self._buffer = []
            return
        if tag == "div" and "component-card__field-card-body" in classes:
            self._collect = None
            self._depth = 1
            return
        if self._depth > 0 and tag == "div":
            self._depth += 1
            return
        if self._depth > 0 and tag == "h3":
            self._collect = "entry-name"
            self._buffer = []
            return
        if self._depth > 0 and self._collect == "entry-name" and tag == "a":
            self._entry_href = dict(attrs).get("href") or ""
            return
        if self._depth > 0 and tag == "p":
            self._collect = "entry-description"
            self._buffer = []

    def handle_endtag(self, tag: str) -> None:
        if tag == "div" and self._collect == "section-title":
            self.sections.append((_normalized(self._buffer), []))
            self._collect = None
            self._buffer = []
            return
        if self._depth > 0 and tag == "div":
            self._depth -= 1
            if self._depth == 0:
                self._collect = None
            return
        if tag == "h3" and self._collect == "entry-name":
            if not self.sections:
                raise FccSourceDriftError("FCC roster entry appeared before any section title")
            self.sections[-1][1].append(
                {"name": _normalized(self._buffer), "href": self._entry_href or "", "description": ""}
            )
            self._collect = None
            self._buffer = []
            self._entry_href = None
            return
        if tag == "p" and self._collect == "entry-description":
            if not self.sections or not self.sections[-1][1]:
                raise FccSourceDriftError("FCC roster description appeared before its heading")
            current = self.sections[-1][1][-1]
            current["description"] = _normalized([current["description"], " ", *self._buffer])
            self._collect = None
            self._buffer = []

    def handle_data(self, data: str) -> None:
        if self._collect is not None:
            self._buffer.append(data)


def parse_fcc_bureaus_offices(
    payload: bytes,
    *,
    pin: FccPagePin = FCC_OFFICES_BUREAUS_2026_08_15,
) -> FccBureausOfficesRoster:
    """Parse the publisher's Offices & Bureaus roster from exact page bytes."""

    if len(payload) != pin.expected_byte_length:
        raise FccSourceDriftError(
            f"FCC page byte length drift: expected {pin.expected_byte_length}, got {len(payload)}"
        )
    actual = sha256_digest(payload)
    if actual != pin.expected_sha256:
        raise FccSourceDriftError(f"FCC page digest drift: expected {pin.expected_sha256}, got {actual}")

    parser = _RosterParser()
    parser.feed(payload.decode("utf-8"))
    parser.close()

    observed = tuple((title, len(entries)) for title, entries in parser.sections)
    if observed != FCC_EXPECTED_SECTIONS:
        raise FccSourceDriftError(
            f"FCC roster sections drifted: expected {FCC_EXPECTED_SECTIONS!r}, observed {observed!r}"
        )

    units: list[FccOrganizationalUnit] = []
    ordinal = 0
    for title, entries in parser.sections:
        kind = _SECTION_KINDS[title]
        for entry in entries:
            ordinal += 1
            href = entry["href"]
            if _PAGE_HREF.fullmatch(href) is None:
                raise FccSourceDriftError(f"FCC roster entry {entry['name']!r} has an unsupported href: {href!r}")
            if not entry["name"]:
                raise FccSourceDriftError("FCC roster entry has an empty heading")
            if not entry["description"]:
                raise FccSourceDriftError(f"FCC roster entry {entry['name']!r} has no description paragraph")
            units.append(
                FccOrganizationalUnit(
                    kind=kind,
                    name=entry["name"],
                    slug=href.removeprefix("/"),
                    page_href=href,
                    page_url=FCC_PAGE_HOST + href,
                    description=entry["description"],
                    source_ordinal=ordinal,
                )
            )

    if len({unit.slug for unit in units}) != len(units):
        raise FccSourceDriftError("FCC roster repeats a page slug")
    if len({unit.name for unit in units}) != len(units):
        raise FccSourceDriftError("FCC roster repeats a unit name")
    return FccBureausOfficesRoster(
        units=tuple(units),
        office_count=sum(1 for unit in units if unit.kind == "office"),
        bureau_count=sum(1 for unit in units if unit.kind == "bureau"),
        source_sha256=actual,
        source_byte_length=len(payload),
        retrieved_at=pin.retrieved_at,
    )


__all__ = [
    "FCC_EXPECTED_SECTIONS",
    "FCC_OFFICES_BUREAUS_2026_08_15",
    "FCC_OFFICES_BUREAUS_URL",
    "FCC_PAGE_HOST",
    "FCC_PUBLISHER",
    "FccBureausOfficesError",
    "FccBureausOfficesRoster",
    "FccOrganizationalUnit",
    "FccPagePin",
    "FccSourceDriftError",
    "UnitKind",
    "parse_fcc_bureaus_offices",
    "sha256_digest",
]
