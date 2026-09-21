"""Compare the current CFR readers to the frozen pre-migration oracle and its mutations.

Verdicts must agree except for the five named INTENTIONAL_DIVERGENCES, each
exercised below; they only strengthen decoding or accept ordinary HTML attributes.
"""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path

import cfr_metadata_oracle as old
import pytest

from refspec.registry import cfr_list_of_subjects as current

FIXTURES = Path(__file__).parent / "fixtures/cfr_list_of_subjects"
ROSTER = (FIXTURES / "ecfr-agencies-2026-08-15.json").read_bytes()
PAGE = b"<dl><dt>40 CFR Part 52_Implementation plans.</dt><dd>Air pollution</dd></dl>"

# Every change in verdict must be named here and exercised below. These
# strengthen source decoding or support ordinary HTML attributes; neither
# changes the accepted retained roster or any of the 50 pinned pages.
INTENTIONAL_DIVERGENCES = {
    "duplicate_json_key": ("accept", "reject"),
    "utf16_json": ("accept", "reject"),
    "html_attributes": ("reject", "accept"),
    "unclosed_definition": ("accept", "reject"),
    "cross_list_assignment": ("accept", "reject"),
}


def _verdict(reader, payload, pin):
    """Return ('accept', serialized value) or ('reject', None) for one reader and payload."""

    try:
        value = reader(payload, pin=pin)
    except ValueError:
        return "reject", None
    return "accept", tuple(dataclasses.asdict(row) for row in value) if isinstance(
        value, tuple
    ) else dataclasses.asdict(value)


def _agency_pin(payload):
    """Repin the eCFR roster identity to the mutated payload's bytes."""

    return dataclasses.replace(
        current.ECFR_AGENCIES_2026_08_15,
        expected_sha256=current.sha256_digest(payload),
        expected_byte_length=len(payload),
    )


def _subject_pin(payload, title=40):
    """Repin a subject-index page identity to the mutated payload's bytes."""

    return current.CfrSubjectIndexPin(
        source_url=current.CFR_SUBJECT_INDEX_URL_TEMPLATE.format(title=title),
        retrieved_at="2026-08-20T00:00:00Z",
        expected_sha256=current.sha256_digest(payload),
        expected_byte_length=len(payload),
        cfr_title=title,
        revision_note="publisher page current as of April 1, 2025",
    )


def test_full_roster_agrees_with_frozen_reader():
    """Pin that the full eCFR roster yields the same verdict and records as the frozen reader."""

    pin = current.ECFR_AGENCIES_2026_08_15
    assert _verdict(current.parse_ecfr_agency_roster, ROSTER, pin) == _verdict(
        old.parse_ecfr_agency_roster, ROSTER, pin
    )


@pytest.mark.parametrize("pin", current.CFR_SUBJECT_INDEX_2026_08_20, ids=lambda pin: f"title-{pin.cfr_title}")
def test_all_fifty_retained_pages_agree_with_frozen_reader(pin):
    """Pin that all 50 retained subject-index pages yield the same verdict and rows as the frozen reader."""

    payload = (FIXTURES / f"subject-index/subject-title-{pin.cfr_title:02d}.html").read_bytes()
    assert _verdict(current.parse_cfr_subject_index, payload, pin) == _verdict(
        old.parse_cfr_subject_index, payload, pin
    )


@pytest.mark.parametrize(
    "mutation",
    [
        "unknown_field",
        "missing_field",
        "bad_children",
        "scalar_child",
        "missing_slug",
        "duplicate_slug",
        "bad_reference",
        "unknown_reference",
        "bad_title",
        "float_title",
        "null_short_name",
        "empty_short_name",
        "remove_row",
        "root_scalar",
        "root_unknown",
    ],
)
def test_agency_mutation_verdicts_agree(mutation):
    """Pin equal accept/reject verdicts with the oracle across 15 agency-roster mutations."""

    root = json.loads(ROSTER)
    row = root["agencies"][0]
    match mutation:
        case "unknown_field":
            row["new_field"] = "retained by provider, refused by pinned profile"
        case "missing_field":
            del row["sortable_name"]
        case "bad_children":
            row["children"] = None
        case "scalar_child":
            row["children"] = [None]
        case "missing_slug":
            del row["slug"]
        case "duplicate_slug":
            row["slug"] = root["agencies"][1]["slug"]
        case "bad_reference":
            row["cfr_references"] = [None]
        case "unknown_reference":
            row["cfr_references"][0]["future_key"] = "x"
        case "bad_title":
            row["cfr_references"][0]["title"] = True
        case "float_title":
            row["cfr_references"][0]["title"] = 1.0
        case "null_short_name":
            row["short_name"] = None
        case "empty_short_name":
            row["short_name"] = ""
        case "remove_row":
            root["agencies"].pop()
        case "root_scalar":
            root = []
        case "root_unknown":
            root["future_field"] = []
    payload = json.dumps(root).encode()
    pin = _agency_pin(payload)
    assert _verdict(current.parse_ecfr_agency_roster, payload, pin) == _verdict(
        old.parse_ecfr_agency_roster, payload, pin
    )


@pytest.mark.parametrize(
    "payload",
    [
        PAGE,
        PAGE.replace(b"40 CFR Part 52", b"40 CFR Question"),
        PAGE.replace(b"40 CFR", b"12 CFR"),
        PAGE.replace(b"Part ", b""),
        PAGE.replace(b"Part ", b"Oart "),
        PAGE.replace(b"_", "—".encode()),
        PAGE.replace(b"Air pollution", b"SO<sub>2</sub> and AT&amp;T"),
        PAGE.replace(b"Air pollution", b"N/A"),
        PAGE.replace(b"Air pollution", b"strong>N/A"),
        PAGE.replace(b"Air pollution", b"strong>"),
        PAGE.replace(b"Air pollution", b"12 CFR Part 1_Cross reference"),
        PAGE.replace(b"</dl>", b"<dd>40 CFR Part 53_Next.</dd><dd>Water</dd></dl>"),
        PAGE.replace(b"<dt>", b"<dt>40 CFR Part 51_Reserved.</dt><dt>"),
        PAGE.replace(b"<dd>", b'<ddgrant programs=""></ddgrant><dd>'),
        PAGE.replace(b"<dd>", b"<dd>First</dd>broken gap<dd>"),
        PAGE.replace(b"Air pollution", b"A\xffB"),
    ],
)
def test_subject_mutation_verdicts_and_values_agree(payload):
    """Pin equal verdicts and parsed values with the oracle across 16 subject-page mutations."""

    pin = _subject_pin(payload)
    assert _verdict(current.parse_cfr_subject_index, payload, pin) == _verdict(
        old.parse_cfr_subject_index, payload, pin
    )


@pytest.mark.parametrize("name", INTENTIONAL_DIVERGENCES)
def test_only_named_divergences_change_verdict(name):
    """Pin the exact (old, current) verdict pair for each named intentional divergence."""

    if name == "duplicate_json_key":
        payload = ROSTER.replace(b'"agencies":', b'"agencies":[],"agencies":', 1)
    elif name == "utf16_json":
        payload = ROSTER.decode().encode("utf-16")
    elif name == "html_attributes":
        payload = PAGE.replace(b"<dt>", b'<dt class="part">').replace(b"<dd>", b'<dd class="term">')
    elif name == "unclosed_definition":
        payload = PAGE.replace(b"</dl>", b"<dt>40 CFR Part 53_Unclosed<dd>Water</dd></dl>")
    else:
        payload = PAGE.replace(b"</dt><dd>", b"</dt></dl><dl><dd>")
    agency = name in {"duplicate_json_key", "utf16_json"}
    pin = _agency_pin(payload) if agency else _subject_pin(payload)
    readers = (
        (old.parse_ecfr_agency_roster, current.parse_ecfr_agency_roster)
        if agency
        else (old.parse_cfr_subject_index, current.parse_cfr_subject_index)
    )
    assert tuple(_verdict(reader, payload, pin)[0] for reader in readers) == INTENTIONAL_DIVERGENCES[name]


def test_inspection_roster_walk_matches_its_looser_frozen_reader():
    """Pin that spicy_docs' looser roster walk returns the same raw rows as the oracle's flatten."""

    from spicy_docs.sources.cfr.agencies import read_ecfr_agency_roster

    source = read_ecfr_agency_roster(ROSTER)
    expected = old._flatten_agencies(json.loads(ROSTER)["agencies"])
    assert tuple(record.raw for record in source.records) == expected


def _inspect_agencies(payload):
    # Minimal valid earlier inputs ensure this exercises the agency acceptance
    # and responsibility path, rather than failing before it reaches that path.
    structure = {
        "type": "title",
        "identifier": "1",
        "children": [
            {
                "type": "chapter",
                "identifier": "I",
                "children": [
                    {
                        "type": "part",
                        "identifier": "18",
                        "label": "Part 18",
                        "children": [{"type": "section", "identifier": "18.1"}],
                    }
                ],
            }
        ],
    }
    titles = {
        "titles": [
            {
                "number": 1,
                "name": "General Provisions",
                "latest_issue_date": "2024-05-17",
                "up_to_date_as_of": "2026-07-31",
            }
        ],
        "meta": {"date": "2026-07-31", "import_in_progress": False},
    }
    return current.inspect_ecfr_part_sources(
        json.dumps(structure).encode(),
        b'<DIV5 TYPE="PART" N="18"><P>Federal Register Thesaurus list of index terms</P></DIV5>',
        json.dumps(titles).encode(),
        payload,
        cfr_title=1,
        cfr_part="18",
    )


@pytest.mark.parametrize(
    "mutation", ["unchanged", "unknown_field", "scalar_child", "missing_child_slug", "bad_children"]
)
def test_actual_inspection_agency_acceptance_matches_frozen_walk(mutation):
    """Pin that the real inspection path accepts or refuses agencies exactly as the frozen walk does."""

    root = json.loads(ROSTER)
    row = root["agencies"][0]
    if mutation == "unknown_field":
        row["additional_metadata"] = {"retained": True}
    elif mutation == "scalar_child":
        row["children"] = [None]
    elif mutation == "missing_child_slug":
        row["children"] = [{"name": "Unnamed", "cfr_references": []}]
    elif mutation == "bad_children":
        row["children"] = "not an array"
    payload = json.dumps(root).encode()
    try:
        expected = old._flatten_agencies(root["agencies"])
    except old.CFRSourceDriftError:
        with pytest.raises(current.CFRSourceDriftError):
            _inspect_agencies(payload)
    else:
        inspected = _inspect_agencies(payload)
        assert inspected.total_agency_count == len(expected) == 316
        assert inspected.responsible_agencies == ("Administrative Committee of the Federal Register",)
