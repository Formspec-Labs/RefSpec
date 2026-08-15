"""NRC ADAMS Public Search documented profile properties and accession number.

The Nuclear Regulatory Commission publishes two PDFs on the ADAMS Public
Search (APS) host itself, retrievable with a plain HTTPS fetch:

* ``APS-User-Manual.pdf`` -- the APS User Manual. Its "Properties in
  Profile" section "describes the fields that make up a document profile in
  APS": twenty-two named properties, each with the publisher's own
  description, including the official definition of the accession number as
  exactly two elements (a two-character alphabetic code and a nine-character
  numeric code "known as the 'ADAMS Item ID'").

* ``APS-API-Guide.pdf`` -- the APS Application Programming Interface
  Developer's Guide, self-titled "Version 1.0". It documents the six text
  filter operators with their exact quoted API tokens, the exactly two date
  properties in the APS index, the request parameters of both REST
  endpoints, and -- in its "Appendix A: Document Properties" -- the thirteen
  API document-property names a document object may return. The appendix
  list is captured and drift-checked here but emitted by no Atlas release;
  the releases record that boundary in their ``notEmitted`` metadata.

These documents are the documented successors of the REF-032-deleted NRC
ADAMS units, which had been regexed out of a minified Angular bundle and
inferred from examples. The official accession-number definition states
exactly two elements and documents no finer structure for the nine-character
ADAMS Item ID, so the previously inferred ``MLYYDDDNNNN`` decomposition is
not carried anywhere in this module.

The manual introduces APS as the application that "will replace the previous
Web-Based ADAMS search application"; that sentence is retained as provenance
and nothing WBA-derived is read or captured. The API guide states that "the
most current properties available for search are published via the ADAMS
Public Search API Developer Portal", a portal that requires registration and
sign-in -- both PDFs are therefore point-in-time publisher documentation, and
their own version markers are recorded verbatim (the API guide's printed
"Version 1.0"; the manual prints no version statement, so its PDF
document-information timestamps are the available revision markers).

Parsing reads exact pinned bytes only, folds PDF presentation forms per
``refspec.pdf_text``, and keeps every description verbatim. Importing this
module never opens a network connection.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Sequence
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from urllib.parse import urlsplit

from refspec.pdf_text import fold_pdf_text

NRC_ADAMS_APS_PUBLISHER = "U.S. Nuclear Regulatory Commission"
APS_USER_MANUAL_URL = "https://adams-search.nrc.gov/assets/APS-User-Manual.pdf"
APS_API_GUIDE_URL = "https://adams-search.nrc.gov/assets/APS-API-Guide.pdf"

_DIGEST = re.compile(r"^sha256:([0-9a-f]{64})$")


class NRCAPSDocsError(ValueError):
    """Base class for APS publisher-document capture failures."""


class NRCAPSAcquisitionError(NRCAPSDocsError):
    """Exact official source bytes could not be verified safely."""


class NRCAPSSourceDriftError(NRCAPSDocsError):
    """A pinned APS document no longer matches its reviewed structure."""


def sha256_digest(payload: bytes) -> str:
    """Return the canonical RefSpec SHA-256 spelling."""

    return "sha256:" + hashlib.sha256(payload).hexdigest()


@dataclass(frozen=True, slots=True)
class NRCAPSPdfPin:
    """Exact identity of one official APS PDF capture."""

    source_url: str
    retrieved_at: str
    expected_sha256: str
    expected_byte_length: int
    expected_page_count: int

    def __post_init__(self) -> None:
        parsed = urlsplit(self.source_url)
        if parsed.scheme != "https" or parsed.hostname != "adams-search.nrc.gov":
            raise NRCAPSAcquisitionError("source_url must be an official HTTPS adams-search.nrc.gov URL")
        if parsed.username is not None or parsed.password is not None:
            raise NRCAPSAcquisitionError("source_url must not contain credentials")
        if _DIGEST.fullmatch(self.expected_sha256) is None:
            raise NRCAPSAcquisitionError("expected_sha256 must be a lowercase sha256:<64 hex> digest")
        if self.expected_byte_length <= 0 or self.expected_page_count <= 0:
            raise NRCAPSAcquisitionError("expected_byte_length and expected_page_count must be positive")
        if not self.retrieved_at.strip():
            raise NRCAPSAcquisitionError("retrieved_at must not be empty")


# Real captures made 2026-08-15 with a plain HTTPS fetch of the published
# asset URLs; both fixtures are pinned byte-exact in-repo.
APS_USER_MANUAL_2026_08_15 = NRCAPSPdfPin(
    source_url=APS_USER_MANUAL_URL,
    retrieved_at="2026-08-15T13:56:07Z",
    expected_sha256="sha256:ab6d6e298cf9a142aad94dbe39024eb0002513beef1e61851784652145643c93",
    expected_byte_length=2_687_062,
    expected_page_count=23,
)
APS_API_GUIDE_2026_08_15 = NRCAPSPdfPin(
    source_url=APS_API_GUIDE_URL,
    retrieved_at="2026-08-15T13:56:07Z",
    expected_sha256="sha256:5d1ed894dfbd30cb9ea4c7e05fb01c3bec5502dc4e4ab968daf88095b4c2d848",
    expected_byte_length=531_285,
    expected_page_count=24,
)


# The reviewed structure of the manual's "Properties in Profile" table: the
# twenty-two property names in table order. The parser recovers the table
# from the PDF text layer and refuses any drift from this shape; every
# description is taken from the PDF itself, never from here.
APS_PROFILE_PROPERTY_NAMES = (
    "Accession Number",
    "Addressee Affiliation",
    "Addressee Name",
    "Author Affiliation",
    "Author Name",
    "Case Reference Number",
    "Comment",
    "Contact Person",
    "Date Added",
    "Date Docketed",
    "Distribution List Codes",
    "Docket Number",
    "Document Date",
    "Document Report Number",
    "Document Title",
    "Document Type",
    "Documents Filed in Package",
    "Estimated Page Count",
    "Keyword",
    "License Number",
    "Microform Address",
    "Packages Filed In",
)
APS_PROFILE_PROPERTY_COUNT = len(APS_PROFILE_PROPERTY_NAMES)

# The API guide's six text-operator tokens, in the guide's own order. Labels
# and descriptions are parsed from the PDF; the tokens are the reviewed shape.
APS_TEXT_OPERATOR_TOKENS = (
    "contains",
    "notcontains",
    "starts",
    "notstarts",
    "equals",
    "notequals",
)
# The exactly two date properties the guide states for the APS index.
APS_DATE_PROPERTY_NAMES = ("DateAddedTimestamp", "DocumentDate")
# The documented request parameters, in the guide's own order.
APS_SEARCH_REQUEST_PARAMETER_NAMES = (
    "q",
    "filters",
    "anyFilters",
    "legacyLibFilter",
    "mainLibFilter",
    "sort",
    "sortDirection",
    "skip",
)
APS_GET_DOCUMENT_PARAMETER_NAMES = ("accessionNumber",)
# The guide's Appendix A ("Appendix A: Document Properties") states thirteen
# API document-property names -- the properties "returned in a document
# object or used as filters in search queries". They are captured and
# drift-checked but deliberately not emitted by any Atlas release: the
# emitted scheme is the manual's documented profile table, and the appendix
# is the API projection of the same application's properties.
APS_APPENDIX_A_DOCUMENT_PROPERTY_NAMES = (
    "AccessionNumber",
    "DocumentTitle",
    "AuthorName",
    "AuthorAffiliation",
    "AddresseeName",
    "AddresseeAffiliation",
    "DocumentDate",
    "DocumentType",
    "Keyword",
    "DocketNumber",
    "DateAddedTimestamp",
    "EstimatedPageCount",
    "Url",
)

# Zero-based indices of the two pages the Properties in Profile table spans
# in the pinned manual, plus the manual's WBA-succession sentence page.
_MANUAL_TABLE_PAGE_INDICES = (18, 19)
# The manual renders the table's Property Name cells in their own column
# (x-origin ~75pt); descriptions start at ~149pt and page prose at ~72pt.
# The band measures name-column cells by geometry, independent of the
# reviewed name list, so the property count is counted from the page rather
# than assumed from this module's constants.
_MANUAL_NAME_COLUMN_X_BAND = (74.0, 140.0)
_MANUAL_TABLE_END_HEADING = "Wildcards"
_MANUAL_INTRODUCTION_PAGE_INDEX = 3
_MANUAL_SECTION_HEADING = "Properties in Profile"
_MANUAL_TABLE_HEADER = "Property Name Description"
_MANUAL_TABLE_END_MARKER = "Wildcards APS supports using wildcards"
_MANUAL_WBA_SENTENCE = (
    "This application will replace the previous Web-Based ADAMS search application."
)
_ACCESSION_ELEMENTS_MARKER = "consisting of the following elements:"

# PDF document-information keys retained verbatim as revision markers. The
# personal author name the PDF carries is deliberately not retained: it is
# not a version marker.
_DOCUMENT_INFO_KEYS = ("/Title", "/Subject", "/CreationDate", "/ModDate", "/SourceModified")

_API_VERSION_RE = re.compile(r"Version \d+\.\d+")
_API_OPERATORS_MARKER = (
    "The quoted text for each operator is what should be passed in the operator property:"
)
_API_OPERATOR_COUNT_SENTENCE = "There are 6 operators in ADAMS Public Search"
_API_OPERATOR_ITEM_RE = re.compile(
    r"- (?P<label>[A-Z][A-Za-z ]*?) \(“(?P<token>[a-z]+)”\)"
    r"(?: – (?P<description>.*?))?"
    r"(?= - [A-Z][A-Za-z ]*? \(“|$)"
)
_API_DATE_PROPERTIES_MARKER = (
    "There are currently only 2 Date properties in the ADAMS Public Search index:"
)
_API_DATE_PROPERTIES_RE = re.compile(r"\s*- (?P<first>[A-Za-z]+) - (?P<second>[A-Za-z]+) To query")
_API_SEARCH_PARAMETERS_MARKER = "Request Body Parameters:"
_API_REQUEST_ITEM_RE = re.compile(
    r"- (?P<name>[A-Za-z]+) \((?P<declared_type>[a-z]+)\) – (?P<description>.*?)"
    r"(?= - [A-Za-z]+ \(|$)"
)
_API_GET_DOCUMENT_MARKER = "Parameters:"
_API_GET_DOCUMENT_ITEM_RE = re.compile(
    r"- (?P<name>[A-Za-z]+) \(location: (?P<location>[a-z]+), required\): (?P<description>.*?)"
    r"(?= - [A-Za-z]+ \(location: |$)"
)
# The guide's own statements that the sign-in Developer Portal, not these
# PDFs, carries the current property list. Their presence is a drift check
# and their text travels verbatim as capture metadata.
_API_PORTAL_SENTENCES = (
    (
        2,
        (
            "The most current properties available for search are published via the "
            "ADAMS Public Search API Developer Portal for each of the endpoints "
            "discussed below in section 3."
        ),
    ),
    (
        3,
        (
            "The API also has a Developer Portal is published at: "
            "https://adams-api-developer.nrc.gov/ for more direct access."
        ),
    ),
    (11, "The Developer Portal will have the latest list of available properties."),
)
_API_ENDPOINT_PAGE_INDICES = {"getDocument": 6, "searchDocumentLibrary": 8}
_API_OPERATORS_PAGE_INDEX = 11
_API_DATE_FILTERS_PAGE_INDEX = 12
_API_APPENDIX_A_PAGE_INDEX = 14
_API_APPENDIX_A_HEADING = "Appendix A: Document Properties"
_API_APPENDIX_A_INTRO = (
    "The following properties may be returned in a document object or used as "
    "filters in search queries:"
)
_API_APPENDIX_A_ITEM_RE = re.compile(
    r"- (?P<name>[A-Za-z]+): (?P<description>.*?)(?= - [A-Za-z]+: |$)"
)


@dataclass(frozen=True, slots=True)
class APSProfileProperty:
    """One documented APS document-profile property, in the publisher's words."""

    name: str
    description: str
    source_ordinal: int


@dataclass(frozen=True, slots=True)
class APSAccessionNumberElement:
    """One element of the official accession-number definition, verbatim."""

    ordinal: int
    text: str


@dataclass(frozen=True, slots=True)
class APSAccessionNumberDefinition:
    """The official accession-number definition and its two documented elements.

    ``definition`` is the complete description cell of the Accession Number
    property, verbatim. ``elements`` are its two bulleted elements, verbatim
    and in publisher order. NRC documents no finer decomposition of the
    nine-character ADAMS Item ID, and none is derived here.
    """

    definition: str
    elements: tuple[APSAccessionNumberElement, ...]


@dataclass(frozen=True, slots=True)
class ParsedAPSUserManual:
    """The Properties in Profile table read from one exact manual capture."""

    source_url: str
    source_sha256: str
    source_byte_length: int
    retrieved_at: str
    page_count: int
    properties: tuple[APSProfileProperty, ...]
    accession_number: APSAccessionNumberDefinition
    wba_replacement_statement: str
    document_information: dict[str, str]


@dataclass(frozen=True, slots=True)
class APSTextOperator:
    """One documented text-filter operator with its exact quoted API token."""

    label: str
    token: str
    description: str | None
    source_ordinal: int


@dataclass(frozen=True, slots=True)
class APSRequestParameter:
    """One documented request parameter of an APS API endpoint."""

    endpoint: str
    name: str
    declared_type: str
    description: str
    source_ordinal: int


@dataclass(frozen=True, slots=True)
class ParsedAPSAPIGuide:
    """The documented operators, date properties, and request parameters."""

    source_url: str
    source_sha256: str
    source_byte_length: int
    retrieved_at: str
    page_count: int
    self_described_version: str
    text_operators: tuple[APSTextOperator, ...]
    date_property_names: tuple[str, ...]
    search_request_parameters: tuple[APSRequestParameter, ...]
    get_document_parameters: tuple[APSRequestParameter, ...]
    appendix_document_property_names: tuple[str, ...]
    developer_portal_statements: tuple[str, ...]
    document_information: dict[str, str]


def _read_pinned_pdf(source_path: Path, pin: NRCAPSPdfPin, *, location: str):
    path = Path(source_path)
    if path.is_symlink() or not path.is_file():
        raise NRCAPSAcquisitionError(f"{location} is not a regular file: {path}")
    payload = path.read_bytes()
    if not payload.startswith(b"%PDF-"):
        raise NRCAPSSourceDriftError(f"{location} is not a PDF file")
    if len(payload) != pin.expected_byte_length:
        raise NRCAPSSourceDriftError(
            f"{location} byte length drift: expected {pin.expected_byte_length}, got {len(payload)}"
        )
    digest = sha256_digest(payload)
    if digest != pin.expected_sha256:
        raise NRCAPSSourceDriftError(f"{location} digest drift: expected {pin.expected_sha256}, got {digest}")
    try:
        from pypdf import PdfReader
    except ImportError as error:  # pragma: no cover - dependency gate
        raise NRCAPSDocsError("pypdf is required to parse the APS publisher PDFs") from error
    try:
        reader = PdfReader(BytesIO(payload))
    except Exception as error:
        raise NRCAPSSourceDriftError(f"{location} is not a readable PDF: {error}") from error
    if len(reader.pages) != pin.expected_page_count:
        raise NRCAPSSourceDriftError(
            f"{location} page count drift: expected {pin.expected_page_count}, got {len(reader.pages)}"
        )
    return reader, digest, len(payload)


def _normalized_page_text(reader, index: int) -> str:
    return re.sub(r"\s+", " ", fold_pdf_text(reader.pages[index].extract_text() or "")).strip()


def _document_information(reader, *, location: str) -> dict[str, str]:
    metadata = reader.metadata
    if metadata is None:
        raise NRCAPSSourceDriftError(f"{location} carries no PDF document information")
    markers: dict[str, str] = {}
    for key in _DOCUMENT_INFO_KEYS:
        value = metadata.get(key)
        if isinstance(value, str) and value.strip():
            markers[key.removeprefix("/")] = value
    if not markers:
        raise NRCAPSSourceDriftError(f"{location} publishes none of its expected revision markers")
    return markers


def _measured_property_name_column(reader) -> str:
    """Measure the property table's name column from page geometry.

    Every text fragment whose x-origin falls inside the name-column band is
    collected in content-stream order, starting after each page's ``Property
    Name`` header and stopping at the ``Wildcards`` heading that follows the
    table. The result is the concatenated, space-stripped text the name
    column actually renders -- measured from the page, not reconstructed
    from this module's reviewed name list -- so a silently added, removed,
    or renamed row cannot hide inside a neighbour's description cell.
    """

    measured: list[str] = []
    end_seen = False
    for index in _MANUAL_TABLE_PAGE_INDICES:
        fragments: list[str] = []
        state = {"stopped": False, "in_table": False, "pending_header": False}

        def _visit(
            text: str,
            cm: object,
            tm: Sequence[float],
            font_dict: object,
            font_size: object,
            state: dict[str, bool] = state,
            fragments: list[str] = fragments,
        ) -> None:
            if state["stopped"]:
                return
            piece = " ".join(fold_pdf_text(text).split())
            if not piece:
                return
            if piece == _MANUAL_TABLE_END_HEADING:
                state["stopped"] = True
                return
            low, high = _MANUAL_NAME_COLUMN_X_BAND
            if not low <= float(tm[4]) < high:
                return
            if not state["in_table"]:
                if piece == "Property":
                    state["pending_header"] = True
                elif piece == "Name" and state["pending_header"]:
                    state["in_table"] = True
                else:
                    state["pending_header"] = False
                return
            fragments.append(piece)

        reader.pages[index].extract_text(visitor_text=_visit)
        if not state["in_table"]:
            raise NRCAPSSourceDriftError(
                f"the Properties in Profile name-column header was not measured on page index {index}"
            )
        if state["stopped"]:
            end_seen = True
        measured.extend(fragments)
    if not end_seen:
        raise NRCAPSSourceDriftError(
            "the Wildcards heading no longer terminates the measured property table"
        )
    return "".join(piece.replace(" ", "") for piece in measured)


def _verify_measured_property_roster(measured_name_column: str) -> None:
    """Refuse unless the measured name column states exactly the reviewed names."""

    expected = "".join(name.replace(" ", "") for name in APS_PROFILE_PROPERTY_NAMES)
    if measured_name_column != expected:
        raise NRCAPSSourceDriftError(
            "the Properties in Profile name column does not measure as exactly the "
            f"reviewed {APS_PROFILE_PROPERTY_COUNT} property names: a table row was "
            "added, removed, or renamed"
        )


def parse_aps_user_manual(source_path: Path, *, pin: NRCAPSPdfPin) -> ParsedAPSUserManual:
    """Parse the complete Properties in Profile table from one exact capture.

    The table spans two pages; each page repeats the ``Property Name
    Description`` header and the second page ends where the manual's
    Wildcards section begins. The name column is first *measured* from page
    geometry (``_measured_property_name_column``) and must state exactly the
    reviewed 22 property names -- the count is counted, not assumed.
    Descriptions are then recovered by locating each reviewed property name
    in table order and taking the verbatim text between one name and the
    next. Any drift from the measured 22-property shape fails closed.
    """

    reader, digest, byte_length = _read_pinned_pdf(source_path, pin, location="APS User Manual")
    _verify_measured_property_roster(_measured_property_name_column(reader))

    first_index, second_index = _MANUAL_TABLE_PAGE_INDICES
    first_page = _normalized_page_text(reader, first_index)
    second_page = _normalized_page_text(reader, second_index)

    heading_index = first_page.find(_MANUAL_SECTION_HEADING)
    if heading_index == -1:
        raise NRCAPSSourceDriftError("the Properties in Profile heading moved off its pinned page")
    header_index = first_page.find(_MANUAL_TABLE_HEADER, heading_index)
    if header_index == -1:
        raise NRCAPSSourceDriftError("the Properties in Profile table header was not found after its heading")
    first_segment = first_page[header_index + len(_MANUAL_TABLE_HEADER) :].strip()

    continued_header_index = second_page.find(_MANUAL_TABLE_HEADER)
    if continued_header_index == -1:
        raise NRCAPSSourceDriftError("the Properties in Profile continued-page header was not found")
    end_index = second_page.find(_MANUAL_TABLE_END_MARKER, continued_header_index)
    if end_index == -1:
        raise NRCAPSSourceDriftError("the Wildcards section no longer terminates the property table")
    second_segment = second_page[continued_header_index + len(_MANUAL_TABLE_HEADER) : end_index].strip()

    table = f"{first_segment} {second_segment}".strip()

    positions: list[int] = []
    cursor = 0
    for name in APS_PROFILE_PROPERTY_NAMES:
        found = table.find(name, cursor)
        if found == -1:
            raise NRCAPSSourceDriftError(f"property {name!r} was not found in table order")
        positions.append(found)
        cursor = found + len(name)
    if positions[0] != 0:
        raise NRCAPSSourceDriftError("the property table no longer begins with its first reviewed property")

    properties: list[APSProfileProperty] = []
    for ordinal, name in enumerate(APS_PROFILE_PROPERTY_NAMES):
        begin = positions[ordinal] + len(name)
        end = positions[ordinal + 1] if ordinal + 1 < len(positions) else len(table)
        description = table[begin:end].strip()
        if not description:
            raise NRCAPSSourceDriftError(f"property {name!r} has an empty description cell")
        properties.append(APSProfileProperty(name=name, description=description, source_ordinal=ordinal))

    accession_description = properties[0].description
    marker_index = accession_description.find(_ACCESSION_ELEMENTS_MARKER)
    if marker_index == -1:
        raise NRCAPSSourceDriftError("the accession-number definition no longer enumerates its elements")
    element_texts = [
        text.strip()
        for text in accession_description[marker_index + len(_ACCESSION_ELEMENTS_MARKER) :].split("•")
        if text.strip()
    ]
    if len(element_texts) != 2:
        raise NRCAPSSourceDriftError(
            f"the accession-number definition states {len(element_texts)} elements; the reviewed shape is 2"
        )
    accession_number = APSAccessionNumberDefinition(
        definition=accession_description,
        elements=tuple(
            APSAccessionNumberElement(ordinal=ordinal, text=text)
            for ordinal, text in enumerate(element_texts)
        ),
    )

    introduction = _normalized_page_text(reader, _MANUAL_INTRODUCTION_PAGE_INDEX)
    if _MANUAL_WBA_SENTENCE not in introduction:
        raise NRCAPSSourceDriftError("the manual's WBA-succession sentence was not found on its pinned page")

    return ParsedAPSUserManual(
        source_url=pin.source_url,
        source_sha256=digest,
        source_byte_length=byte_length,
        retrieved_at=pin.retrieved_at,
        page_count=pin.expected_page_count,
        properties=tuple(properties),
        accession_number=accession_number,
        wba_replacement_statement=_MANUAL_WBA_SENTENCE,
        document_information=_document_information(reader, location="APS User Manual"),
    )


def _parse_region_items(regex: re.Pattern[str], region: str, *, location: str) -> list[re.Match[str]]:
    matches = list(regex.finditer(region))
    if not matches:
        raise NRCAPSSourceDriftError(f"{location} lists no parseable items")
    return matches


def _parse_get_document_parameters(region: str) -> tuple[APSRequestParameter, ...]:
    """Parse every Get Document parameter bullet; refuse any roster drift.

    Each bullet's description stops at the next ``- name (location: …``
    bullet, exactly like the Search Document Library item pattern, so a
    second documented parameter becomes a drifted-roster refusal rather
    than text silently swallowed into the first description.
    """

    matches = _parse_region_items(
        _API_GET_DOCUMENT_ITEM_RE, region, location="the Get Document parameter list"
    )
    parameters = tuple(
        APSRequestParameter(
            endpoint="getDocument",
            name=match.group("name"),
            declared_type=f"location: {match.group('location')}, required",
            description=match.group("description").strip(),
            source_ordinal=ordinal,
        )
        for ordinal, match in enumerate(matches)
    )
    actual_names = tuple(parameter.name for parameter in parameters)
    if actual_names != APS_GET_DOCUMENT_PARAMETER_NAMES:
        raise NRCAPSSourceDriftError(
            f"Get Document parameters drifted: expected {APS_GET_DOCUMENT_PARAMETER_NAMES}, "
            f"got {actual_names}"
        )
    return parameters


def parse_aps_api_guide(source_path: Path, *, pin: NRCAPSPdfPin) -> ParsedAPSAPIGuide:
    """Parse the documented operators, date properties, and request parameters.

    Every enumerated list is checked against its reviewed shape -- six text
    operators with their quoted tokens, exactly two date properties, eight
    Search Document Library body parameters and one Get Document path
    parameter -- and every label and description is the PDF's verbatim text.
    """

    reader, digest, byte_length = _read_pinned_pdf(source_path, pin, location="APS API Guide")

    cover = _normalized_page_text(reader, 0)
    version_match = _API_VERSION_RE.search(cover)
    if version_match is None:
        raise NRCAPSSourceDriftError("the API guide cover no longer states a version")
    self_described_version = version_match.group(0)

    operators_page = _normalized_page_text(reader, _API_OPERATORS_PAGE_INDEX)
    if _API_OPERATOR_COUNT_SENTENCE not in operators_page:
        raise NRCAPSSourceDriftError("the API guide no longer states its six-operator count")
    marker_index = operators_page.find(_API_OPERATORS_MARKER)
    if marker_index == -1:
        raise NRCAPSSourceDriftError("the operator-token list marker was not found")
    operator_region = operators_page[marker_index + len(_API_OPERATORS_MARKER) :].strip()
    operator_matches = _parse_region_items(
        _API_OPERATOR_ITEM_RE, operator_region, location="the text-operator list"
    )
    text_operators = tuple(
        APSTextOperator(
            label=match.group("label"),
            token=match.group("token"),
            description=(match.group("description") or "").strip() or None,
            source_ordinal=ordinal,
        )
        for ordinal, match in enumerate(operator_matches)
    )
    actual_tokens = tuple(operator.token for operator in text_operators)
    if actual_tokens != APS_TEXT_OPERATOR_TOKENS:
        raise NRCAPSSourceDriftError(
            f"text operators drifted: expected {APS_TEXT_OPERATOR_TOKENS}, got {actual_tokens}"
        )

    date_page = _normalized_page_text(reader, _API_DATE_FILTERS_PAGE_INDEX)
    date_marker_index = date_page.find(_API_DATE_PROPERTIES_MARKER)
    if date_marker_index == -1:
        raise NRCAPSSourceDriftError("the two-date-property statement was not found")
    date_match = _API_DATE_PROPERTIES_RE.match(date_page[date_marker_index + len(_API_DATE_PROPERTIES_MARKER) :])
    if date_match is None:
        raise NRCAPSSourceDriftError("the date-property list did not parse as exactly two names")
    date_property_names = (date_match.group("first"), date_match.group("second"))
    if date_property_names != APS_DATE_PROPERTY_NAMES:
        raise NRCAPSSourceDriftError(
            f"date properties drifted: expected {APS_DATE_PROPERTY_NAMES}, got {date_property_names}"
        )

    search_page = _normalized_page_text(reader, _API_ENDPOINT_PAGE_INDICES["searchDocumentLibrary"])
    search_marker_index = search_page.find(_API_SEARCH_PARAMETERS_MARKER)
    if search_marker_index == -1:
        raise NRCAPSSourceDriftError("the Search Document Library parameter list marker was not found")
    search_region = search_page[search_marker_index + len(_API_SEARCH_PARAMETERS_MARKER) :].strip()
    search_matches = _parse_region_items(
        _API_REQUEST_ITEM_RE, search_region, location="the Search Document Library parameter list"
    )
    search_request_parameters = tuple(
        APSRequestParameter(
            endpoint="searchDocumentLibrary",
            name=match.group("name"),
            declared_type=match.group("declared_type"),
            description=match.group("description").strip(),
            source_ordinal=ordinal,
        )
        for ordinal, match in enumerate(search_matches)
    )
    actual_search_names = tuple(parameter.name for parameter in search_request_parameters)
    if actual_search_names != APS_SEARCH_REQUEST_PARAMETER_NAMES:
        raise NRCAPSSourceDriftError(
            "Search Document Library parameters drifted: "
            f"expected {APS_SEARCH_REQUEST_PARAMETER_NAMES}, got {actual_search_names}"
        )

    get_page = _normalized_page_text(reader, _API_ENDPOINT_PAGE_INDICES["getDocument"])
    get_marker_index = get_page.find(_API_GET_DOCUMENT_MARKER)
    if get_marker_index == -1:
        raise NRCAPSSourceDriftError("the Get Document parameter list marker was not found")
    get_region = get_page[get_marker_index + len(_API_GET_DOCUMENT_MARKER) :].strip()
    get_document_parameters = _parse_get_document_parameters(get_region)

    appendix_page = _normalized_page_text(reader, _API_APPENDIX_A_PAGE_INDEX)
    if _API_APPENDIX_A_HEADING not in appendix_page:
        raise NRCAPSSourceDriftError("the Appendix A document-property heading moved off its pinned page")
    intro_index = appendix_page.find(_API_APPENDIX_A_INTRO)
    if intro_index == -1:
        raise NRCAPSSourceDriftError("the Appendix A document-property intro sentence was not found")
    appendix_region = appendix_page[intro_index + len(_API_APPENDIX_A_INTRO) :].strip()
    appendix_matches = _parse_region_items(
        _API_APPENDIX_A_ITEM_RE, appendix_region, location="the Appendix A document-property list"
    )
    appendix_names = tuple(match.group("name") for match in appendix_matches)
    if appendix_names != APS_APPENDIX_A_DOCUMENT_PROPERTY_NAMES:
        raise NRCAPSSourceDriftError(
            "Appendix A document properties drifted: "
            f"expected {APS_APPENDIX_A_DOCUMENT_PROPERTY_NAMES}, got {appendix_names}"
        )

    portal_statements: list[str] = []
    for page_index, sentence in _API_PORTAL_SENTENCES:
        if sentence not in _normalized_page_text(reader, page_index):
            raise NRCAPSSourceDriftError(
                f"the developer-portal statement on page index {page_index} was not found"
            )
        portal_statements.append(sentence)

    return ParsedAPSAPIGuide(
        source_url=pin.source_url,
        source_sha256=digest,
        source_byte_length=byte_length,
        retrieved_at=pin.retrieved_at,
        page_count=pin.expected_page_count,
        self_described_version=self_described_version,
        text_operators=text_operators,
        date_property_names=date_property_names,
        search_request_parameters=search_request_parameters,
        get_document_parameters=get_document_parameters,
        appendix_document_property_names=appendix_names,
        developer_portal_statements=tuple(portal_statements),
        document_information=_document_information(reader, location="APS API Guide"),
    )


__all__ = [
    "APS_API_GUIDE_2026_08_15",
    "APS_API_GUIDE_URL",
    "APS_APPENDIX_A_DOCUMENT_PROPERTY_NAMES",
    "APS_DATE_PROPERTY_NAMES",
    "APS_GET_DOCUMENT_PARAMETER_NAMES",
    "APS_PROFILE_PROPERTY_COUNT",
    "APS_PROFILE_PROPERTY_NAMES",
    "APS_SEARCH_REQUEST_PARAMETER_NAMES",
    "APS_TEXT_OPERATOR_TOKENS",
    "APS_USER_MANUAL_2026_08_15",
    "APS_USER_MANUAL_URL",
    "NRC_ADAMS_APS_PUBLISHER",
    "APSAccessionNumberDefinition",
    "APSAccessionNumberElement",
    "APSProfileProperty",
    "APSRequestParameter",
    "APSTextOperator",
    "NRCAPSAcquisitionError",
    "NRCAPSDocsError",
    "NRCAPSPdfPin",
    "NRCAPSSourceDriftError",
    "ParsedAPSAPIGuide",
    "ParsedAPSUserManual",
    "parse_aps_api_guide",
    "parse_aps_user_manual",
    "sha256_digest",
]
