"""Ranges survive typed output and cannot stand in for one CFR part.

The range-aware consumer must carry both endpoints through the production Arrow schemas and identity
keys, refuse flat pinpoint ranges with ``range_pinpoints_not_represented``, and diverge from the
copied pre-range oracle exactly where ranges, multiple parts, or refused scope are involved."""
import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from cfr_range_consumer_oracle import (
    old__explain_cfr_part,
    old__held_parts_by_rule,
    old_cfr_citation,
)

from refspec.registry import cfr_authority_notes as notes_module
from refspec.registry import term_explanation as explanations
from refspec.registry import unified_agenda_parquet as agenda
from refspec.registry.citation_grammar import parse_authority_citation

# Source cases inspected in the title-41 XML, section 51-10.151, and the
# title-40 part-6 authority note. Explicit endpoints, not inferred members.
SECTION_RANGE = "41 CFR 101-19.600 to 101-19.607"
PART_RANGE = "40 CFR parts 1500 through 1508"
RANGE_COLUMNS = ("cfr_part_end", "cfr_section_end", "cfr_end_part_is_plausible", "cfr_refusal")


class Notes:
    """Minimal authority-note cache that holds every part and records each lookup."""

    def __init__(self):
        self.lookups = []

    def holds(self, title, part):
        self.lookups.append((title, part))
        return True

    def note(self, title, part):
        self.lookups.append((title, part))
        return SimpleNamespace(part_head=f"PART {part}", authority_note="", citations=())


def _reference(text):
    """Agenda CFR-reference rows for text, read through the real range-aware path against pinned held parts."""

    return [{"rin": "1000-AA00", "publication_id": "202510", "reference_text": text, **reading}
            for reading in agenda._cfr_reference_readings(text, {(41, "101-19"), (40, "1500")})]


def _authority(text):
    """One joined legal-authority row built through the real field-copy path with a no-op calendar."""

    citation, = [row for row in parse_authority_citation(text) if row.authority_type == "cfr"]
    donor = {"rin": "1000-AA00", "publication_id": "202510", "ordinal": 0,
             "authority_text": text, "authority_source": "box"}
    # CFR carries no data for any of these other series. Avoid dated oracle
    # artifacts while executing the real joined-row field-copy path.
    calendar = SimpleNamespace(**{method: lambda *args: None for method in (
        "usc_title_is_possible", "eo_in_known_series", "pl_congress_in_series",
        "stat_volume_in_series", "fr_volume_in_series", "fr_page_in_series")})
    return agenda._joined_citation_row(donor, citation, text, calendar)


@pytest.mark.parametrize(("text", "expected"), [
    (SECTION_RANGE, (41, "101-19", "600", "101-19", "607")),
    (PART_RANGE, (40, "1500", None, "1508", None)),
    ("41 CFR parts 50-1 through 50-200", (41, "50-1", None, "50-200", None)),
])
def test_cfr_range_endpoints_survive_both_typed_tables(tmp_path, text, expected):
    reference, = _reference(text)
    authority = _authority(text)
    names = ("cfr_title", "cfr_part", "cfr_section", "cfr_part_end", "cfr_section_end")
    assert tuple(reference[name] for name in names) == expected
    assert tuple(authority[name] for name in names) == expected
    assert reference["cfr_part_in_current_ofr_index"] is None
    for index, (schema, row) in enumerate(((agenda.CFR_REFERENCES_SCHEMA, reference),
                                          (agenda.LEGAL_AUTHORITIES_SCHEMA, authority))):
        assert row["cfr_end_part_is_plausible"] is True
        assert row["cfr_refusal"] is None
        assert set(RANGE_COLUMNS) <= set(schema.names)
        # Fill only unrelated required columns, then exercise the complete
        # production Arrow schema, not a permissive inferred schema.
        complete = dict(row)
        for field in schema:
            if not field.nullable and complete.get(field.name) is None:
                complete[field.name] = (False if pa.types.is_boolean(field.type) else
                                        0 if pa.types.is_integer(field.type) else "")
        path = tmp_path / f"range-{index}.parquet"
        pq.write_table(pa.Table.from_pylist([complete], schema=schema), path)
        actual, = pq.read_table(path).to_pylist()
        assert tuple(actual[name] for name in names) == expected
        assert {name: actual[name] for name in RANGE_COLUMNS} == {name: row[name] for name in RANGE_COLUMNS}
        source_column = "reference_text" if index == 0 else "authority_text"
        assert actual[source_column] == text


def test_cfr_refusal_and_endpoint_plausibility_survive_join_and_identity_keys():
    first = _authority(SECTION_RANGE)
    second = {**first, "cfr_section_end": "608"}
    refused = {**first, "cfr_refusal": "unsupported-test-scope"}
    for key in (agenda._citation_identity, agenda._join_citation_key):
        assert key(first) != key(second)
        assert key(first) != key(refused)
    citation, = [row for row in parse_authority_citation(SECTION_RANGE) if row.authority_type == "cfr"]
    changed = replace(citation, cfr_end_part_is_plausible=False, cfr_refusal="unsupported-test-scope")
    # The shared list drives the joined-row copy; every endpoint/refusal must
    # come from the new native result, not default to NULL on that branch.
    actual = {name: getattr(changed, name) for name in agenda._JOIN_CITATION_COLUMNS}
    assert actual["cfr_end_part_is_plausible"] is False
    assert actual["cfr_refusal"] == "unsupported-test-scope"


def test_repeated_explicit_cfr_citations_are_not_deduplicated():
    rows = _reference("41 CFR part 102-38; 41 CFR part 102-38")
    assert len(rows) == 2
    assert [row["cfr_part"] for row in rows] == ["102-38", "102-38"]


@pytest.mark.parametrize("text", ["40 CFR 60.1(a) through 60.2(b)",
                                  "40 CFR 60.1 through 60.2(b)",
                                  "40 CFR 60.1(a) through 60.2"])
def test_flat_range_rows_disclose_unrepresented_endpoint_pinpoints(text):
    reference, = _reference(text)
    for row in (reference, _authority(text)):
        assert row["cfr_part_end"] == "60"
        assert row["cfr_section_end"] == "2"
        assert row["cfr_refusal"] == "range_pinpoints_not_represented"
        assert agenda._cfr_row_citation(row) is None
        assert text in (row.get("reference_text"), row.get("authority_text"))


def test_subparts_do_not_duplicate_structured_part_rows():
    rows = _reference("49 CFR part 172, subparts E and F")
    assert len(rows) == 1
    assert rows[0]["cfr_part"] == "172"


@pytest.mark.parametrize("text", ["41 CFR 60-1-60-2", "49 CFR parts 172 and 173, subpart E"])
def test_refused_scope_is_retained_and_not_used_as_a_part(text):
    rows = _reference(text)
    refused = [row for row in rows if row["cfr_refusal"] is not None]
    assert refused
    for row in refused:
        assert row["cfr_part_in_current_ofr_index"] is None
        assert agenda._cfr_row_citation(row) is None


@pytest.mark.parametrize("text", [SECTION_RANGE, PART_RANGE])
def test_range_part_note_comparisons_diverge_from_the_copied_first_part_check(text):
    """The copied check holds and looks up the range's first part; the range-aware consumer holds nothing."""

    row, = _reference(text)
    old_notes, new_notes = Notes(), Notes()
    assert old__held_parts_by_rule([row], old_notes)
    assert agenda._held_parts_by_rule([row], new_notes) == {}
    assert new_notes.lookups == []
    assert old_cfr_citation(row["cfr_title"], row["cfr_part"]) is not None
    assert agenda._CFR_NOTE_CITATION_BY_TYPE["cfr"](row) is None
    assert not [reading for reading in notes_module.read_note_citations(text) if reading.family == "cfr"]


@pytest.mark.parametrize("text", ["49 CFR 1.95", "7 CFR 15a", "5 CFR part 10001"])
def test_single_part_comparison_and_explanation_keep_copied_behavior(text):
    row, = _reference(text)
    old_notes, new_notes = Notes(), Notes()
    assert agenda._held_parts_by_rule([row], new_notes) == old__held_parts_by_rule([row], old_notes)
    assert new_notes.lookups == old_notes.lookups
    assert agenda._cfr_row_citation(row) == old_cfr_citation(row["cfr_title"], row["cfr_part"])
    assert explanations._explain_cfr_part(text, None, Notes()) == old__explain_cfr_part(text, None, Notes())


@pytest.mark.parametrize("text", [SECTION_RANGE, PART_RANGE, "49 CFR parts 172 and 173",
                                  "41 CFR 60-1-60-2", "49 CFR parts 172 and 173, subpart E"])
def test_explanation_withholds_ranges_multiple_parts_and_refused_scope(text):
    notes = Notes()
    answer = explanations.explain_term(text, index=None, notes=notes)
    assert answer.unexplained_reason == "cfr_scope_not_one_part"
    assert notes.lookups == []


def test_range_start_is_not_a_single_section_witness():
    authority = {"authority_type": "usc", "rin": "1000-AA00", "usc_title": 26,
                 "usc_section": "472-8", "usc_section_verdict": "absent"}
    row, = _reference("26 CFR 1.472-8")
    single = dict(authority)
    assert agenda._write_usc_slot_reading([single], [row], None)["reg-suffix"] == 1
    for extra in ({"cfr_section_end": "472-9"}, {"cfr_refusal": "ambiguous-scope"}):
        target = dict(authority)
        assert agenda._write_usc_slot_reading([target], [{**row, **extra}], None)["reg-suffix"] == 0
        assert target["usc_slot_reading"] is None


def test_unread_structured_reference_still_has_one_null_row():
    row, = _reference("None")
    assert all(value is None for key, value in row.items() if key.startswith("cfr_"))


@pytest.mark.parametrize("case", json.loads(
    (Path(__file__).parent / "fixtures/cfr-note-range-divergences.json").read_text()
)["cases"], ids=lambda case: case["id"])
def test_every_reviewed_note_delta_keeps_its_exact_family_identities(case):
    """Each reviewed case's non-CFR family identities must equal the frozen baseline, so no other family moved."""

    assert case["reasons"]
    actual = sorted([c.family, c.identity, c.span_end or ""]
                    for c in notes_module.read_note_citations(case["text"], oracle=None))
    assert actual == case["expected_without_oracle"]
    # The changed CFR interpretation must not alter any other family, even
    # when USC, Public Law and act citations share the same source note.
    assert [c for c in actual if c[0] != "cfr"] == [
        c for c in case["baseline_without_oracle"] if c[0] != "cfr"
    ]
