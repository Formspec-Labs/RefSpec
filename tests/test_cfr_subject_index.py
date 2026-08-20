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

import pytest

from refspec.registry.cfr_list_of_subjects import (
    CFR_RESERVED_TITLES,
    CFR_SUBJECT_INDEX_URL_TEMPLATE,
    CFRListOfSubjectsError,
    CFRSourceDriftError,
    CfrSubjectIndexPin,
    parse_cfr_subject_index,
)

REVISION = "publisher page current as of April 1, 2025"


def _page(body: str) -> bytes:
    return f"<html><body><dl>{body}</dl></body></html>".encode("utf-8")


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
    text = open(source, encoding="utf-8").read()
    for forbidden in ("import requests", "urlopen", "httpx", "socket."):
        assert forbidden not in text
