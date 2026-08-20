"""The independent publisher reader for the CFR List of Subjects.

REF-037 requires that every construction unit be compared against a reading of
the pinned publisher bytes that shares no code with the producer. The producer
side (``refspec.registry.cfr_list_of_subjects``) reads these fifty pages with
regular expressions. The reader under test here reads them with the event-driven
``html.parser``: it is told where every element starts and ends, so a heading the
publisher typed as ``<dd>``, a tag name the publisher mangled, and an element the
publisher never closed are all facts it observes rather than text a pattern
happens to span.

Three kinds of test earn that claim:

* the reader reproduces an exact census of the real pinned bytes, so publisher
  drift fails it before any Atlas comparison runs;
* the reader *fails* on deliberately mutated bytes -- a flipped element type, a
  removed term, a wrong digest -- because a reader that cannot fail proves
  nothing about the bytes it accepted;
* the divergences between this reading and the shipped release are frozen and
  named, so a new one fails this suite instead of becoming a diff nobody reads.
"""

from __future__ import annotations

import csv
import re
from dataclasses import replace
from pathlib import Path

import pytest

from refspec.input_pin import read_verified_file_pin
from tools.verify_atlas_source_fidelity import (
    _CFR_SUBJECT_INDEX_CENSUS,
    _CFR_SUBJECT_INDEX_DUPLICATE_PARTS,
    _CFR_SUBJECT_INDEX_IRREGULARITIES,
    _CFR_SUBJECT_INDEX_RESOLUTION,
    SOURCES,
    PublisherView,
    SourceSpec,
    _read_cfr_subject_index,
    read_publisher_inputs,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = REPOSITORY_ROOT / "output" / "registry-real-data-sources"
SOURCE_NAME = "cfr-subject-index-parts-2026-08-20"
EVIDENCE_CSV = REPOSITORY_ROOT / "research/evidence/cfr-subject-index-2026-08-20/part-subjects.csv"
HAS_TOPICS_WITNESS = (
    REPOSITORY_ROOT / "tests/fixtures/federal_register_topics_api/federal-register-topics-2026-08-03.json"
).is_file()


@pytest.fixture(scope="module")
def spec() -> SourceSpec:
    matches = [candidate for candidate in SOURCES if candidate.name == SOURCE_NAME]
    assert len(matches) == 1, f"expected exactly one {SOURCE_NAME} comparison spec"
    return matches[0]


def _payloads(spec: SourceSpec) -> dict[object, bytes]:
    return {
        pin: read_verified_file_pin(
            REPOSITORY_ROOT / pin.path,
            expected_sha256=pin.sha256,
            expected_byte_length=pin.byte_length,
            logical_path=pin.path,
        )
        for pin in spec.inputs
    }


@pytest.fixture(scope="module")
def view(spec: SourceSpec) -> PublisherView:
    return _read_cfr_subject_index(spec, _payloads(spec))


def test_spec_pins_every_publisher_page_and_the_target_witness(spec: SourceSpec) -> None:
    pages = [pin for pin in spec.inputs if pin.role == "publisherSubjectIndexPage"]
    witnesses = [pin for pin in spec.inputs if pin.role == "targetVocabularyWitness"]
    assert len(pages) == 50
    assert len(witnesses) == 1
    assert {pin.fmt for pin in pages} == {"html"}
    titles = sorted(int(pin.path.rsplit("subject-title-", 1)[1].removesuffix(".html")) for pin in pages)
    assert titles == list(range(1, 51))
    for pin in spec.inputs:
        assert (REPOSITORY_ROOT / pin.path).is_file(), pin.path
        assert pin.sha256.startswith("sha256:") and len(pin.sha256) == 71


def test_every_pinned_page_authenticates_against_its_declared_digest(spec: SourceSpec) -> None:
    for pin in spec.inputs:
        payload = read_verified_file_pin(
            REPOSITORY_ROOT / pin.path,
            expected_sha256=pin.sha256,
            expected_byte_length=pin.byte_length,
            logical_path=pin.path,
        )
        assert len(payload) == pin.byte_length


def test_reader_reproduces_its_census_of_the_pinned_bytes(view: PublisherView) -> None:
    assert len(view.concepts) == _CFR_SUBJECT_INDEX_CENSUS["distinctParts"] == 8_425
    assert len(view.relations) == _CFR_SUBJECT_INDEX_RESOLUTION["partSubjectRelations"] == 31_685
    assert len(view.pref_labels) == len(view.notations) == len(view.expected_native_payloads) == 8_425
    assert _CFR_SUBJECT_INDEX_CENSUS["pages"] == 50
    assert _CFR_SUBJECT_INDEX_CENSUS["titlesWithParts"] == 49
    assert _CFR_SUBJECT_INDEX_CENSUS["partEntries"] == 8_428
    assert _CFR_SUBJECT_INDEX_CENSUS["termAssignments"] == 32_202
    assert _CFR_SUBJECT_INDEX_CENSUS["distinctTermAssignments"] == 32_188
    assert _CFR_SUBJECT_INDEX_CENSUS["distinctTerms"] == 1_068
    assert _CFR_SUBJECT_INDEX_RESOLUTION["resolvedTerms"] == 863
    assert _CFR_SUBJECT_INDEX_RESOLUTION["unresolvedTerms"] == 205


def test_reserved_cfr_title_35_carries_no_parts(view: PublisherView) -> None:
    titles = {payload["cfrTitle"] for payload in view.expected_native_payloads.values()}
    assert 35 not in titles
    assert titles == set(range(1, 51)) - {35}


def test_publisher_irregularities_are_counted_not_skipped() -> None:
    assert _CFR_SUBJECT_INDEX_IRREGULARITIES["headingTypedAsDefinition"] == 32
    assert _CFR_SUBJECT_INDEX_IRREGULARITIES["missingPartKeyword"] == 13
    assert _CFR_SUBJECT_INDEX_IRREGULARITIES["misspelledPartKeyword"] == 1
    assert _CFR_SUBJECT_INDEX_IRREGULARITIES["emDashSeparator"] == 1
    assert _CFR_SUBJECT_INDEX_IRREGULARITIES["leakedStrongFragment"] == 1
    assert _CFR_SUBJECT_INDEX_IRREGULARITIES["headingWithoutCitation"] == 2
    assert _CFR_SUBJECT_INDEX_IRREGULARITIES["unattributedTermAssignment"] == 6
    assert _CFR_SUBJECT_INDEX_IRREGULARITIES["malformedListElement"] == 1


@pytest.mark.parametrize(
    ("resource", "heading", "notation"),
    [
        # A part heading the publisher typed as <dd>. It is a part here, with
        # its own terms, not a stray term on the part above it.
        ("urn:ref:cfr-part:2:376", "Nonprocurement debarment and suspension", "2 CFR Part 376"),
        # "2 CFR 401_": the word "Part" is missing from the citation.
        ("urn:ref:cfr-part:2:401", "Buy America preferences for infrastructure projects", "2 CFR Part 401"),
        # "48 CFR Oart 739_": a typo for "Part".
        ("urn:ref:cfr-part:48:739", "Acquisition of information technology", "48 CFR Part 739"),
        # "30 CFR Part 285—": an em dash where every other heading has "_".
        (
            "urn:ref:cfr-part:30:285",
            "Renewable energy and alternate uses of existing facilities on the Outer Continental Self",
            "30 CFR Part 285",
        ),
        # "<dt>strong&gt;48 CFR Part 2952_": an escaped tag fragment leaked in.
        ("urn:ref:cfr-part:48:2952", "Solicitation provisions and contract clauses", "48 CFR Part 2952"),
    ],
)
def test_publisher_irregularities_still_yield_the_right_part(
    view: PublisherView,
    resource: str,
    heading: str,
    notation: str,
) -> None:
    assert resource in view.concepts
    assert {literal.value for literal in view.pref_labels[resource]} == {heading}
    assert {literal.value for literal in view.notations[resource]} == {notation}


def test_a_mistyped_heading_does_not_leak_its_terms_into_the_part_above(view: PublisherView) -> None:
    """2 CFR 300 is a <dt>; 2 CFR 376 immediately after it is a <dd>.

    This is the shape a reader without element boundaries gets wrong: the
    mistyped part disappears and its terms join the part above it. Here the two
    parts keep their own headings and their own, disjoint, term lists.
    """
    above = view.expected_native_payloads["urn:ref:cfr-part:2:300"]
    mistyped = view.expected_native_payloads["urn:ref:cfr-part:2:376"]
    assert mistyped["partHeading"] not in above["partHeading"]
    assert above["publisherIndexTerms"] == [
        "Accounting",
        "Administrative practice and procedure",
        "Government contracts",
        "Grants administration",
        "Loan programs",
        "Scholarships and fellowships",
    ]
    assert mistyped["publisherIndexTerms"] == [
        "Administrative practice and procedure",
        "Grant programs",
        "Reporting and recordkeeping requirements",
    ]


def test_the_three_parts_the_publisher_lists_twice_merge_into_one_resource(view: PublisherView) -> None:
    for cfr_title, part in _CFR_SUBJECT_INDEX_DUPLICATE_PARTS:
        payload = view.expected_native_payloads[f"urn:ref:cfr-part:{cfr_title}:{part}"]
        assert payload["publisherListedPartTwice"] is True
    marked = {
        resource for resource, payload in view.expected_native_payloads.items() if "publisherListedPartTwice" in payload
    }
    assert len(marked) == len(_CFR_SUBJECT_INDEX_DUPLICATE_PARTS) == 3


def test_relations_only_ever_point_at_a_held_topic_concept(view: PublisherView) -> None:
    predicates = {predicate for _subject, predicate, _target in view.relations}
    assert predicates == {"https://refspec.org/ns/atlas/v3#hasIndexedSubject"}
    subjects = {subject for subject, _predicate, _target in view.relations}
    assert subjects <= view.concepts
    targets = {target for _subject, _predicate, target in view.relations}
    assert all(target.startswith("urn:ref:source-concept:v2:federal-register-api:") for target in targets)
    # 863 distinct publisher term strings resolve; they collapse onto 840 held
    # concepts because the publisher writes some terms in more than one case.
    assert len(targets) == 840
    assert len(subjects) == 8_404


# --- proof that the reader can fail ----------------------------------------


def _mutate_one_page(spec: SourceSpec, needle: bytes, replacement: bytes) -> dict[object, bytes]:
    payloads = _payloads(spec)
    for pin, payload in payloads.items():
        if needle in payload:
            payloads[pin] = payload.replace(needle, replacement, 1)
            return payloads
    raise AssertionError(f"no pinned page contains {needle!r}")


def test_reader_raises_when_a_heading_element_is_flipped_to_a_definition(spec: SourceSpec) -> None:
    mutated = _mutate_one_page(
        spec,
        b"<dt><strong>40 CFR Part 52_",
        b"<dd><strong>40 CFR Part 52_",
    )
    with pytest.raises(ValueError, match=r"closes </dt> while <dd> is open"):
        _read_cfr_subject_index(spec, mutated)


def test_reader_raises_when_a_whole_heading_is_retyped_as_a_definition(spec: SourceSpec) -> None:
    mutated = _mutate_one_page(
        spec,
        b"<dt><strong>40 CFR Part 52_Approval and promulgation of implementation plans. </strong></dt>",
        b"<dd><strong>40 CFR Part 52_Approval and promulgation of implementation plans. </strong></dd>",
    )
    with pytest.raises(ValueError, match="irregularities differ"):
        _read_cfr_subject_index(spec, mutated)


def test_reader_raises_when_one_index_term_is_dropped(spec: SourceSpec) -> None:
    mutated = _mutate_one_page(spec, b"<dd>Air pollution control</dd>\n", b"")
    with pytest.raises(ValueError, match="census differs"):
        _read_cfr_subject_index(spec, mutated)


def test_rewriting_one_part_heading_moves_exactly_that_label(spec: SourceSpec) -> None:
    mutated = _mutate_one_page(
        spec,
        b"40 CFR Part 52_Approval and promulgation of implementation plans.",
        b"40 CFR Part 52_Approval and promulgation of implementation schemes.",
    )
    view = _read_cfr_subject_index(spec, mutated)
    labels = {literal.value for literal in view.pref_labels["urn:ref:cfr-part:40:52"]}
    assert labels == {"Approval and promulgation of implementation schemes"}


def test_reader_raises_when_a_definition_list_is_removed(spec: SourceSpec) -> None:
    mutated = _mutate_one_page(spec, b"<dl>", b"<div>")
    with pytest.raises(ValueError):
        _read_cfr_subject_index(spec, mutated)


def test_reader_raises_when_the_topic_witness_loses_a_concept(spec: SourceSpec) -> None:
    payloads = _payloads(spec)
    witness = next(pin for pin in spec.inputs if pin.role == "targetVocabularyWitness")
    payloads[witness] = payloads[witness].replace(b'"Air pollution control"', b'"Air pollution controls"', 1)
    with pytest.raises(ValueError, match="term resolution differs"):
        _read_cfr_subject_index(spec, payloads)


def test_pin_authentication_raises_when_a_declared_digest_is_wrong(spec: SourceSpec) -> None:
    page = next(pin for pin in spec.inputs if pin.path.endswith("subject-title-40.html"))
    wrong = replace(page, sha256="sha256:" + "0" * 64)
    broken = replace(spec, inputs=tuple(wrong if pin is page else pin for pin in spec.inputs))
    with pytest.raises(Exception, match="digest|sha256|SHA-256"):
        read_publisher_inputs(SOURCE_ROOT, broken)


def test_pin_authentication_raises_when_the_bytes_on_disk_are_edited(spec: SourceSpec, tmp_path: Path) -> None:
    page = next(pin for pin in spec.inputs if pin.path.endswith("subject-title-40.html"))
    staged = tmp_path / page.path
    staged.parent.mkdir(parents=True, exist_ok=True)
    original = (REPOSITORY_ROOT / page.path).read_bytes()
    staged.write_bytes(original.replace(b"<dd>Air pollution control</dd>", b"<dd>Air pollution controls</dd>", 1))
    with pytest.raises(Exception, match="digest|sha256|SHA-256|byte"):
        read_publisher_inputs(tmp_path, spec)


def test_reading_the_unedited_tree_through_the_pin_path_still_passes(spec: SourceSpec) -> None:
    view = read_publisher_inputs(SOURCE_ROOT, spec)
    assert len(view.concepts) == 8_425


# --- frozen divergences from the shipped release ---------------------------
#
# This list was written when the release was produced by a regex reader that
# spanned irregular elements between two headings, swallowing the second
# heading into the first and losing the part. Both entries -- 42 CFR 59 and
# 45 CFR 2532 -- were real defects, this reader was right about both, and the
# producer has since been fixed. What remains is not a defect but a
# definitional difference, named here for the same reason.
#
# 42 CFR 58 is [Reserved] and the publisher lists no terms under it. This
# reader emits it as a concept carrying zero terms; the producer omits a part
# with no assignments, because the artifact records part->term assignments and
# a part with none contributes nothing to it. Neither reading is wrong about
# the bytes. If the roster ever needs [Reserved] parts as concepts in their own
# right, this is the line to change.
TERMLESS_PARTS = ((42, "58"),)
RELEASE_COUNTS = {"partEntries": 8_427, "distinctParts": 8_424, "termAssignments": 32_202}


@pytest.mark.skipif(not EVIDENCE_CSV.is_file(), reason="release evidence CSV is not present")
def test_divergence_from_the_shipped_release_is_exactly_the_frozen_list(view: PublisherView) -> None:
    with EVIDENCE_CSV.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    # Both sides are compared as sets of (title, part, term). The CSV lists one
    # row per publisher listing, so it repeats a term the publisher repeated
    # under one part; the reader merges repeats into the part's own term list.
    released = {(int(row["cfr_title"]), row["cfr_part"], row["term"]) for row in rows}
    read = {
        (payload["cfrTitle"], payload["cfrPart"], term)
        for payload in view.expected_native_payloads.values()
        for term in payload["publisherIndexTerms"]
    }
    assert not (read - released), f"this reading claims assignments the release does not: {read - released}"
    assert not (released - read), f"the release claims assignments this reading does not: {released - read}"

    released_parts = {(int(row["cfr_title"]), row["cfr_part"]) for row in rows}
    read_parts = {(payload["cfrTitle"], payload["cfrPart"]) for payload in view.expected_native_payloads.values()}
    # The only parts this reader has and the release does not are term-less.
    assert read_parts - released_parts == set(TERMLESS_PARTS)
    assert released_parts - read_parts == set()
    assert len(released_parts) == RELEASE_COUNTS["distinctParts"]
    for cfr_title, part in TERMLESS_PARTS:
        payload = view.expected_native_payloads[f"urn:ref:cfr-part:{cfr_title}:{part}"]
        assert payload["publisherIndexTerms"] == []


@pytest.mark.skipif(not EVIDENCE_CSV.is_file(), reason="release evidence CSV is not present")
def test_the_release_no_longer_swallows_a_heading_into_the_part_above() -> None:
    """The defect this file was written to name, asserted as fixed.

    A term-less part has no ``<dd>`` after its own close tag, and a malformed
    element can sit between a heading and its first term. Either one used to
    let the producer run forward to the next part's terms. Both parts below
    were lost entirely and their terms attributed to the part above; both are
    now present, with their own headings and their own terms.
    """
    with EVIDENCE_CSV.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    headings = {(int(row["cfr_title"]), row["cfr_part"]): row["part_heading"] for row in rows}
    terms: dict[tuple[int, str], set[str]] = {}
    for row in rows:
        terms.setdefault((int(row["cfr_title"]), row["cfr_part"]), set()).add(row["term"])

    assert headings[(42, "59")] == "Grants for family planning services"
    assert headings[(45, "2532")] == "Innovative and special demonstration programs"
    # 45 CFR 2531 is preceded by a malformed ``<ddgrant ...>`` open tag, which
    # is not a heading defect but drops the part unless the gap is skipped.
    assert terms[(45, "2531")] == {"Grant programs-social programs", "Volunteers"}
    # No heading text ever contains another part's heading. The publisher
    # separates a part number from its title with "_", so that -- not the bare
    # phrase "CFR Part" -- is the swallow signature: 15 CFR 2007 ends with
    # "[GSP (15 CFR Part 2007)]" and 40 CFR 194 cites "40 CFR Part 191", both
    # legitimately and both parsed correctly.
    swallowed = [key for key, heading in headings.items() if re.search(r"CFR Part \S+_", heading)]
    assert not swallowed, f"a heading still contains another part's heading: {swallowed}"
