"""Lossless Federal Register 1995 thesaurus adapter tests."""

from __future__ import annotations

import os
from collections import Counter
from pathlib import Path

import pytest

from refspec.registry.federal_register_thesaurus import (
    ASSOCIATIVE_PREDICATE_IRI,
    BROADER_PREDICATE_IRI,
    CATEGORY_NOTATION_DATATYPE_IRI,
    SCOPE_NOTE_PROPERTY_IRI,
    ImportCounts,
    ThesaurusParseError,
    UnresolvedReferenceError,
    parse_federal_register_thesaurus,
)

SYNTHETIC_THESAURUS = """FEDERAL REGISTER THESAURUS OF INDEXING TERMS
November 16, 1995

Alphabetic list of indexing terms, with references to preferred or
related terms:

Accidents
    see
          Safety
Accounting (02, 08)
     sa
          Uniform System of Accounts
      x
          Auditing
     xx
          Business and industry
          Law
Additives
    see
          Color additives
          Food additives
Business and industry (02)
Color additives (17)
Food additives (17)
     (The names of specific foods are not listed in this Thesaurus but
may be used as indexing terms.)
Law (08)
Safety (13)
Uniform System of Accounts (02)
Work Incentive Programs (WIN) (11)
"""

FULL_SOURCE_ENV = "REFSPEC_FR_THESAURUS_1995_PATH"
HISTORICAL_SHA256 = "sha256:d5e013336d4179790e8d6574d4dc9d8cfcb10ce76af202ff4db068617eb8fd30"
HISTORICAL_COUNTS = ImportCounts(
    source_lines=4_853,
    source_bytes=99_349,
    entries=1_004,
    preferred_concepts=629,
    nonpreferred_entries=375,
    preferred_labels=629,
    alternate_labels=924,
    scope_notes=45,
    category_notations=616,
    see_references=463,
    broader_relations=740,
    associative_relations=756,
    resolved_references=1_939,
    unresolved_references=20,
)


def _concept_id(parsed, preferred_label: str) -> str:
    entry = next(item for item in parsed.entries if item.label == preferred_label)
    assert entry.concept_id is not None
    return entry.concept_id


def test_parser_preserves_labels_notes_notation_and_every_relation() -> None:
    parsed = parse_federal_register_thesaurus(SYNTHETIC_THESAURUS)

    assert parsed.counts == ImportCounts(
        source_lines=30,
        source_bytes=len(SYNTHETIC_THESAURUS.encode("utf-8")),
        entries=10,
        preferred_concepts=8,
        nonpreferred_entries=2,
        preferred_labels=8,
        alternate_labels=4,
        scope_notes=1,
        category_notations=8,
        see_references=3,
        broader_relations=2,
        associative_relations=1,
        resolved_references=6,
        unresolved_references=0,
    )

    labels_by_concept: dict[str, list[tuple[str, str, str]]] = {}
    for label in parsed.labels:
        labels_by_concept.setdefault(label.concept_id, []).append((label.role, label.literal, label.source))
    assert labels_by_concept[_concept_id(parsed, "Safety")] == [
        ("alternate", "Accidents", "see"),
        ("preferred", "Safety", "heading"),
    ]
    assert labels_by_concept[_concept_id(parsed, "Accounting")] == [
        ("preferred", "Accounting", "heading"),
        ("alternate", "Auditing", "x"),
    ]
    assert ("alternate", "Additives", "see") in labels_by_concept[_concept_id(parsed, "Color additives")]
    assert ("alternate", "Additives", "see") in labels_by_concept[_concept_id(parsed, "Food additives")]

    note = parsed.scope_notes[0]
    assert note.property_iri == SCOPE_NOTE_PROPERTY_IRI
    assert note.text == (
        "The names of specific foods are not listed in this Thesaurus but may be used as indexing terms."
    )
    assert note.raw_lines == (
        "     (The names of specific foods are not listed in this Thesaurus but",
        "may be used as indexing terms.)",
    )
    assert (note.locator.start_line, note.locator.end_line) == (25, 26)

    accounting_notation = next(
        item for item in parsed.category_notations if item.concept_id == _concept_id(parsed, "Accounting")
    )
    assert accounting_notation.raw_literal == "(02, 08)"
    assert accounting_notation.codes == ("02", "08")
    assert accounting_notation.datatype_iri == CATEGORY_NOTATION_DATATYPE_IRI
    assert accounting_notation.locator.start_line == 10
    assert accounting_notation.locator.ordinal > 0
    assert (
        next(item for item in parsed.entries if item.label == "Work Incentive Programs (WIN)").raw_heading
        == "Work Incentive Programs (WIN) (11)"
    )

    accounting_id = _concept_id(parsed, "Accounting")
    relations = [item for item in parsed.relations if item.source_concept_id == accounting_id]
    assert [(item.marker, item.predicate_iri, item.raw_target_label) for item in relations] == [
        ("sa", ASSOCIATIVE_PREDICATE_IRI, "Uniform System of Accounts"),
        ("xx", BROADER_PREDICATE_IRI, "Business and industry"),
        ("xx", BROADER_PREDICATE_IRI, "Law"),
    ]
    assert all(item.resolution_status == "resolved" for item in relations)


def test_identifiers_use_source_ordinals_not_labels() -> None:
    original = parse_federal_register_thesaurus(SYNTHETIC_THESAURUS)
    renamed = parse_federal_register_thesaurus(
        SYNTHETIC_THESAURUS.replace("Accounting (02, 08)", "Ledger work (02, 08)")
    )

    original_id = _concept_id(original, "Accounting")
    renamed_id = _concept_id(renamed, "Ledger work")
    assert original_id == renamed_id == "frt95-concept-0002"
    assert "account" not in original_id
    assert "ledger" not in renamed_id


@pytest.mark.parametrize(
    ("entry", "marker", "reference_kind"),
    [
        ("Alias", "see", "see"),
        ("Preferred (01)", "sa", "related"),
        ("Preferred (01)", "xx", "broader"),
    ],
)
def test_unresolved_required_references_are_explicit_and_fail_closed(
    entry: str,
    marker: str,
    reference_kind: str,
) -> None:
    source = f"""FEDERAL REGISTER THESAURUS OF INDEXING TERMS
Alphabetic list of indexing terms, with references to preferred or related terms:

{entry}
    {marker}
          Missing preferred term
"""

    inspected = parse_federal_register_thesaurus(source, require_resolved=False)
    assert len(inspected.unresolved_references) == 1
    unresolved = inspected.unresolved_references[0]
    assert unresolved.reference_kind == reference_kind
    assert unresolved.raw_target_label == "Missing preferred term"
    assert unresolved.locator.start_line == 6
    assert unresolved.reason.endswith("not a preferred source heading")

    with pytest.raises(UnresolvedReferenceError) as exc_info:
        parse_federal_register_thesaurus(source)
    assert exc_info.value.result == inspected


def test_ambiguous_preferred_reference_targets_fail_without_guessing() -> None:
    source = """FEDERAL REGISTER THESAURUS OF INDEXING TERMS
Alphabetic list of indexing terms, with references to preferred or related terms:

Mixed Case (01)
mixed   case (02)
"""

    with pytest.raises(ThesaurusParseError, match="same normalized label"):
        parse_federal_register_thesaurus(source)


def test_unterminated_scope_note_fails_without_inventing_an_entry() -> None:
    source = """FEDERAL REGISTER THESAURUS OF INDEXING TERMS
Alphabetic list of indexing terms, with references to preferred or related terms:

Food (01)
     (An unfinished scope note
"""

    with pytest.raises(ThesaurusParseError, match="unterminated scope note"):
        parse_federal_register_thesaurus(source)


@pytest.mark.skipif(
    not os.environ.get(FULL_SOURCE_ENV),
    reason=f"set {FULL_SOURCE_ENV} to the verified 1995 thesaurus text",
)
def test_verified_historical_full_source_counts_and_fail_closed_result() -> None:
    source_path = Path(os.environ[FULL_SOURCE_ENV])
    source = source_path.read_bytes()

    inspected = parse_federal_register_thesaurus(source, require_resolved=False)
    assert inspected.source_sha256 == HISTORICAL_SHA256
    assert inspected.counts == HISTORICAL_COUNTS
    assert Counter(item.source for item in inspected.labels) == {
        "heading": 629,
        "see": 462,
        "x": 462,
    }
    assert Counter((item.marker, item.resolution_status) for item in inspected.relations) == {
        ("sa", "resolved"): 739,
        ("sa", "unresolved"): 17,
        ("xx", "resolved"): 738,
        ("xx", "unresolved"): 2,
    }
    assert Counter(item.reference_kind for item in inspected.unresolved_references) == {
        "see": 1,
        "related": 17,
        "broader": 2,
    }
    assert any(
        item.raw_target_label == "e and local governments" and item.locator.start_line == 2_568
        for item in inspected.unresolved_references
    )

    with pytest.raises(UnresolvedReferenceError) as exc_info:
        parse_federal_register_thesaurus(source)
    assert exc_info.value.result.source_sha256 == HISTORICAL_SHA256
    assert exc_info.value.result.counts == HISTORICAL_COUNTS
