"""The Office of the Federal Register's per-part CFR subject index.

``src/refspec/registry/cfr_list_of_subjects.py`` was built on a true statement
about eCFR -- that its APIs publish no per-part List of Subjects -- read as
though it were a statement about the world. It is not. The OFR publishes the
index directly as fifty static HTML pages on archives.gov, and
``parse_cfr_subject_index`` reads them.

These tests prove the parser is fail-closed in both directions: an unparsable
entry raises rather than being skipped, and the publisher's own documented
irregularities are handled by name so that a NEW malformation still surfaces.
That distinction is the point -- zero rejects from a permissive regex means
nothing; zero from a parser that raises on every unmatched entry means the
pattern covers the data.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from refspec.registry.cfr_list_of_subjects import (
    CFR_RESERVED_TITLES,
    CFR_SUBJECT_INDEX_2026_08_20,
    CFR_SUBJECT_INDEX_DUPLICATE_PART_KEYS,
    CFR_SUBJECT_INDEX_EXPECTED_ASSIGNMENT_COUNT,
    CFR_SUBJECT_INDEX_EXPECTED_PAGE_COUNT,
    CFR_SUBJECT_INDEX_EXPECTED_PART_COUNT,
    CFR_SUBJECT_INDEX_EXPECTED_PART_ENTRY_COUNT,
    CFR_SUBJECT_INDEX_EXPECTED_PARTS_BY_TITLE,
    CFR_SUBJECT_INDEX_EXPECTED_TERM_COUNT,
    CFR_SUBJECT_INDEX_EXPECTED_TITLE_COUNT,
    CFR_SUBJECT_INDEX_URL_TEMPLATE,
    CFRListOfSubjectsError,
    CFRSourceDriftError,
    CfrSubjectIndexPin,
    parse_cfr_subject_index,
)

REVISION = "publisher page current as of April 1, 2025"


def _page(body: str) -> bytes:
    return f"<html><body><dl>{body}</dl></body></html>".encode()


def _pin(payload: bytes, *, title: int = 40, **overrides: object) -> CfrSubjectIndexPin:
    fields: dict[str, object] = {
        "source_url": CFR_SUBJECT_INDEX_URL_TEMPLATE.format(title=title),
        "retrieved_at": "2026-08-20T00:00:00Z",
        "expected_sha256": "sha256:" + hashlib.sha256(payload).hexdigest(),
        "expected_byte_length": len(payload),
        "cfr_title": title,
        "revision_note": REVISION,
    }
    fields.update(overrides)
    return CfrSubjectIndexPin(**fields)  # type: ignore[arg-type]


ONE_PART = _page(
    "<dt><strong>40 CFR Part 52_Approval and promulgation of implementation plans. </strong></dt>"
    "<dd>Air pollution control</dd><dd>Environmental protection</dd>"
)


def test_parses_one_part_and_its_terms() -> None:
    (part,) = parse_cfr_subject_index(ONE_PART, pin=_pin(ONE_PART))
    assert part.cfr_title == 40
    assert part.cfr_part == "52"
    assert part.part_heading == "Approval and promulgation of implementation plans"
    assert part.terms == ("Air pollution control", "Environmental protection")


def test_digest_mismatch_raises() -> None:
    with pytest.raises(CFRSourceDriftError, match="does not match the pinned"):
        parse_cfr_subject_index(ONE_PART, pin=_pin(ONE_PART, expected_sha256="sha256:" + "0" * 64))


def test_byte_length_mismatch_raises() -> None:
    with pytest.raises(CFRSourceDriftError, match="bytes; pinned"):
        parse_cfr_subject_index(ONE_PART, pin=_pin(ONE_PART, expected_byte_length=len(ONE_PART) + 1))


def test_unparsable_part_entry_raises_rather_than_being_skipped() -> None:
    """The property that makes a zero-reject count mean anything."""

    payload = _page("<dt><strong>40 CFR Something Entirely Unexpected</strong></dt><dd>Air pollution control</dd>")
    with pytest.raises(CFRSourceDriftError, match="unparsable part entry"):
        parse_cfr_subject_index(payload, pin=_pin(payload))


def test_entry_from_a_different_title_raises() -> None:
    """A page fetched under the wrong title cannot be silently absorbed."""

    payload = _page("<dt><strong>12 CFR Part 52_Something else. </strong></dt><dd>Banks and banking</dd>")
    with pytest.raises(CFRSourceDriftError, match="contains a title 12 entry"):
        parse_cfr_subject_index(payload, pin=_pin(payload, title=40))


@pytest.mark.parametrize(
    ("entry", "title", "expected_part"),
    [
        # Documented publisher irregularities, each handled by name.
        ("<strong>48 CFR Part 2952_Solicitation provisions. </strong>", 48, "2952"),  # leaked tag
        ("<strong>2 CFR 401_Requirements. </strong>", 2, "401"),  # missing "Part" keyword
        ("<strong>48 CFR Oart 739_Information technology. </strong>", 48, "739"),  # publisher typo
        ("<strong>40 CFR Part 60—Standards of performance. </strong>", 40, "60"),  # em-dash separator
    ],
)
def test_documented_publisher_irregularities_parse(entry: str, title: int, expected_part: str) -> None:
    payload = _page(f"<dt>{entry}</dt><dd>Government procurement</dd>")
    (part,) = parse_cfr_subject_index(payload, pin=_pin(payload, title=title))
    assert part.cfr_part == expected_part


def test_a_part_whose_only_term_is_na_is_omitted() -> None:
    payload = _page(
        "<dt><strong>40 CFR Part 52_Implementation plans. </strong></dt><dd>Air pollution control</dd>"
        "<dt><strong>40 CFR Part 9_Reserved. </strong></dt><dd>N/A</dd>"
    )
    parts = parse_cfr_subject_index(payload, pin=_pin(payload))
    assert [p.cfr_part for p in parts] == ["52"]


def test_reserved_title_may_be_empty_but_a_populated_one_is_drift() -> None:
    """Title 35 is reserved, so zero parts is correct there and drift elsewhere."""

    assert CFR_RESERVED_TITLES == frozenset({35})
    empty = _page("")
    assert parse_cfr_subject_index(empty, pin=_pin(empty, title=35)) == ()
    with pytest.raises(CFRSourceDriftError, match="yielded no part assignments"):
        parse_cfr_subject_index(empty, pin=_pin(empty, title=40))

    populated = _page("<dt><strong>35 CFR Part 1_Something. </strong></dt><dd>Administrative practice and procedure</dd>")
    with pytest.raises(CFRSourceDriftError, match="is reserved but its subject index carries"):
        parse_cfr_subject_index(populated, pin=_pin(populated, title=35))


@pytest.mark.parametrize(
    ("override", "match"),
    [
        ({"source_url": "http://www.archives.gov/federal-register/cfr/subject-title-40.html"}, "credential-free"),
        ({"source_url": "https://example.com/federal-register/cfr/subject-title-40.html"}, "credential-free"),
        ({"source_url": "https://www.archives.gov/federal-register/cfr/subject-title-40.html?x=1"}, "query"),
        ({"source_url": "https://www.archives.gov/federal-register/cfr/subject-title-12.html"}, "does not match"),
        ({"expected_sha256": "notadigest"}, "sha256:"),
        ({"expected_byte_length": 0}, "positive"),
        ({"retrieved_at": "2026-08-20"}, "UTC"),
        (
            {
                "cfr_title": 51,
                "source_url": "https://www.archives.gov/federal-register/cfr/subject-title-51.html",
            },
            "between 1 and 50",
        ),
        ({"revision_note": "some note"}, "revision date"),
    ],
)
def test_pin_rejects_malformed_identity(override: dict[str, object], match: str) -> None:
    with pytest.raises(CFRListOfSubjectsError, match=match):
        _pin(ONE_PART, **override)


def test_parser_performs_no_network_access() -> None:
    """The module's standing contract: callers supply exact publisher bytes."""

    import refspec.registry.cfr_list_of_subjects as module

    source = module.__file__
    assert source is not None
    text = Path(source).read_text(encoding="utf-8")
    for forbidden in ("import requests", "urlopen", "httpx", "socket."):
        assert forbidden not in text


def test_a_part_heading_mistyped_as_dd_is_recovered_not_admitted_as_a_term() -> None:
    """The publisher marks 32 part headings as <dd> instead of <dt>.

    Left alone this is doubly wrong: the mistyped part vanishes entirely, and
    its terms are silently attributed to the part above it. Both halves are
    checked here.
    """

    payload = _page(
        "<dt><strong>40 CFR Part 1031_Control of air pollution from aircraft engines.</strong></dt>"
        "<dd>Air pollution control</dd><dd>Aircraft</dd>"
        "<dd><strong>40 CFR Part 1033_Control of emissions from locomotives. </strong></dd>"
        "<dd>Administrative practice and procedure</dd>"
    )
    parts = {p.cfr_part: p for p in parse_cfr_subject_index(payload, pin=_pin(payload))}
    assert set(parts) == {"1031", "1033"}
    assert parts["1031"].terms == ("Air pollution control", "Aircraft")
    assert parts["1033"].terms == ("Administrative practice and procedure",)
    assert parts["1033"].part_heading == "Control of emissions from locomotives"


def test_a_nested_citation_from_another_title_stays_a_term() -> None:
    """Only same-title citations are treated as mistyped headings.

    A <dd> naming a DIFFERENT title is a cross-reference, not a misplaced
    heading, and must not silently create a part under the wrong title.
    """

    payload = _page(
        "<dt><strong>40 CFR Part 52_Implementation plans. </strong></dt>"
        "<dd>Air pollution control</dd><dd>12 CFR Part 3_Something else</dd>"
    )
    (part,) = parse_cfr_subject_index(payload, pin=_pin(payload))
    assert part.cfr_part == "52"
    assert part.terms == ("Air pollution control", "12 CFR Part 3_Something else")


# ---------------------------------------------------------------------------
# The tracked capture. Everything above is synthetic and proves the parser's
# posture. These prove that the fifty pages this repository actually carries
# still say what the pins say they say -- which is the only reason the Atlas
# release built from them is reproducible.
# ---------------------------------------------------------------------------

CAPTURE_ROOT = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "cfr_list_of_subjects" / "subject-index"


def _capture_pages() -> tuple[tuple[CfrSubjectIndexPin, bytes], ...]:
    return tuple(
        (pin, (CAPTURE_ROOT / f"subject-title-{pin.cfr_title:02d}.html").read_bytes())
        for pin in CFR_SUBJECT_INDEX_2026_08_20
    )


def test_the_capture_carries_one_pinned_page_for_every_cfr_title() -> None:
    assert len(CFR_SUBJECT_INDEX_2026_08_20) == CFR_SUBJECT_INDEX_EXPECTED_PAGE_COUNT
    assert [pin.cfr_title for pin in CFR_SUBJECT_INDEX_2026_08_20] == list(range(1, 51))
    for pin, payload in _capture_pages():
        assert "sha256:" + hashlib.sha256(payload).hexdigest() == pin.expected_sha256
        assert len(payload) == pin.expected_byte_length


def test_every_pinned_page_parses_to_its_pinned_part_count() -> None:
    for pin, payload in _capture_pages():
        parts = parse_cfr_subject_index(payload, pin=pin)
        assert len(parts) == CFR_SUBJECT_INDEX_EXPECTED_PARTS_BY_TITLE[pin.cfr_title]
        assert all(part.cfr_title == pin.cfr_title for part in parts)
    assert CFR_SUBJECT_INDEX_EXPECTED_PARTS_BY_TITLE[35] == 0


def test_the_capture_census_is_exactly_what_the_reader_pins() -> None:
    """The whole-capture totals, stated as failures rather than as prose.

    The part-entry count and the part count differ by three because the
    publisher lists three parts twice. Both numbers are pinned: collapsing
    them would hide either the duplication or its repair.
    """

    entries = [part for pin, payload in _capture_pages() for part in parse_cfr_subject_index(payload, pin=pin)]
    keys = [(part.cfr_title, part.cfr_part) for part in entries]
    duplicates = sorted({key for key in keys if keys.count(key) > 1})

    assert len(entries) == CFR_SUBJECT_INDEX_EXPECTED_PART_ENTRY_COUNT
    assert len(set(keys)) == CFR_SUBJECT_INDEX_EXPECTED_PART_COUNT
    assert tuple(duplicates) == CFR_SUBJECT_INDEX_DUPLICATE_PART_KEYS
    assert sum(len(part.terms) for part in entries) == CFR_SUBJECT_INDEX_EXPECTED_ASSIGNMENT_COUNT
    assert len({term for part in entries for term in part.terms}) == CFR_SUBJECT_INDEX_EXPECTED_TERM_COUNT
    assert len({part.cfr_title for part in entries}) == CFR_SUBJECT_INDEX_EXPECTED_TITLE_COUNT
    assert CFR_RESERVED_TITLES.isdisjoint({part.cfr_title for part in entries})


def test_a_mutated_capture_page_fails_its_pin() -> None:
    """The pins are load-bearing, not decorative.

    A byte changed anywhere in a captured page must fail the digest before the
    parser reads a single entry -- otherwise the release built from these
    pages would silently describe different bytes than it names.
    """

    pin = CFR_SUBJECT_INDEX_2026_08_20[0]
    payload = (CAPTURE_ROOT / f"subject-title-{pin.cfr_title:02d}.html").read_bytes()
    mutated = payload.replace(b"Definitions", b"Defin1tions", 1)
    assert mutated != payload

    with pytest.raises(CFRSourceDriftError, match="does not match the pinned"):
        parse_cfr_subject_index(mutated, pin=pin)


def test_a_part_with_no_terms_does_not_swallow_the_next_part() -> None:
    """A [Reserved] part has no <dd>, which a non-greedy <dt> group will span.

    Found by an independent event-driven reader after the mistyped-<dd> fix
    had already shipped: 42 CFR 59 and 45 CFR 2532 were vanishing entirely
    and their terms were being attributed to the [Reserved] parts above them.
    The publisher also emits bare `<dt>&nbsp;</dt>` separators, which have the
    same effect.
    """

    payload = _page(
        "<dt><strong>42 CFR Part 58_Grants for training. [Reserved]</strong></dt>"
        "<dt>&nbsp;</dt>"
        "<dt><strong>42 CFR Part 59_Grants for family planning services. </strong></dt>"
        "<dd>Family planning</dd><dd>Grant programs-health</dd>"
    )
    parts = {p.cfr_part: p for p in parse_cfr_subject_index(payload, pin=_pin(payload, title=42))}

    # 59 is present, with its own terms and its own heading.
    assert set(parts) == {"59"}
    assert parts["59"].part_heading == "Grants for family planning services"
    assert parts["59"].terms == ("Family planning", "Grant programs-health")
    # 58 carries no terms, so it yields no assignments -- and critically it does
    # not appear holding 59's.
    assert "58" not in parts


def test_a_malformed_element_between_heading_and_terms_does_not_drop_the_part() -> None:
    """45 CFR 2531 is preceded by an unclosed <dd> whose term ate the tag name.

    Requiring a <dd> immediately after </dt> dropped the part outright, which
    is a quieter failure than swallowing: no wrong data, just a part missing.
    The independent source-fidelity reader had it and the release did not.
    """

    payload = _page(
        "<dt><strong>45 CFR Part 2531_Purposes and availability of grants. </strong></dt>"
        '<ddgrant programs="" programs-social="">'
        "<dd>Grant programs-social programs</dd><dd>Volunteers</dd>"
        "<dt><strong>45 CFR Part 2532_Innovative and special demonstration programs. </strong></dt>"
        "<dd>Grant programs-social programs</dd><dd>Volunteers</dd>"
    )
    parts = {p.cfr_part: p for p in parse_cfr_subject_index(payload, pin=_pin(payload, title=45))}

    assert set(parts) == {"2531", "2532"}
    assert parts["2531"].terms == ("Grant programs-social programs", "Volunteers")
    assert parts["2531"].part_heading == "Purposes and availability of grants"
    # The gap must not reach across a heading: 2532 keeps its own terms.
    assert parts["2532"].terms == ("Grant programs-social programs", "Volunteers")
