"""What ``tools/build_usc_popular_names.py`` reads, refuses, and reproduces.

Every fragment these tests assert against is a byte slice of the captured
``popularnames.htm`` pinned in
``research/evidence/usc-regeneration-2026-08-31/``, cut by that directory's own
``scripts/extract_fixtures.py``. Where a rule needs a case OLRC does not
currently publish, the case is made by **mutating a real fragment** and the
mutation is named in the test, because a rule that has never been shown to
reject anything is not known to reject anything.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pyarrow.parquet as pq
import pytest

from refspec.registry.citation_grammar import normalize_popular_name
from tools import build_usc_popular_names as builder

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "research" / "evidence" / "usc-regeneration-2026-08-31"
ENTRIES = json.loads((EVIDENCE / "fixtures" / "popular-name-entries.json").read_text(encoding="utf-8"))

#: The frozen table this build must reproduce. Both act-index artifacts state
#: it byte for byte, which is why the digest below appears twice in
#: ``act_resolution.py``'s pins.
FROZEN_TABLE = ROOT / "output" / "usc-act-index-2026-08-22" / "usc-popular-names.parquet"
FROZEN_DIGEST = "sha256:603d5b072133d8fe6802736aeaa70b9fb9832e4fb996158a083fae3ce1026a9a"

#: What the frozen table becomes once
#: :meth:`refspec.registry.act_resolution.ActIndex.from_artifact` applies
#: ``normalize_popular_name`` to its two key columns on load
#: (``act_resolution.py:499,501``) -- and, exactly, what this build derives.
LOADED_DIGEST = "sha256:a8777c959adbf5f904a9b84ae6bdbaff5833add132e7998c6c0f8e66c948bb10"

#: The four rows whose ``name_key`` the frozen table spells with a leading
#: ``''`` that today's normalizer strips. ``act_resolution.py:495-499`` already
#: names this population -- "a no-op for 20,861 of the pinned table's 20,865
#: rows" -- and re-normalizes on load, which is why the two tables are one index.
DELIBERATE_KEY_DIVERGENCES = (
    "``Kick-Back'' Racket Act",
    "``SPARS'' Act",
    "``Seeing-Eye'' Dogs on Railroads Act",
    "``Six Triple Eight'' Congressional Gold Medal Act of 2021",
)

frozen_table_required = pytest.mark.skipif(
    not FROZEN_TABLE.exists(), reason=f"frozen popular-name table absent: {FROZEN_TABLE}"
)
pinned_html_required = pytest.mark.skipif(
    not builder.PINNED_HTML.exists(), reason=f"pinned capture absent: {builder.PINNED_HTML}"
)


def records(fixture: str) -> tuple[builder.PopularNameRecord, ...]:
    return builder.parse_popular_names(ENTRIES[fixture]).records


def only(fixture: str, content_type: str) -> list[builder.PopularNameRecord]:
    return [record for record in records(fixture) if record.content_type == content_type]


# --- the Statutes at Large place -------------------------------------------


def test_the_statutes_at_large_place_is_read_from_the_statviewer_query_and_the_prose_agrees() -> None:
    (cite,) = only("statviewer_and_stated_citation_agree", "cite")

    assert (cite.name, cite.table3_key) == ("1921 Silver Dollar Coin Anniversary Act", "116-286")
    assert (cite.statutes_at_large_volume, cite.statutes_at_large_page) == ("134", "4879")
    # Both statements are present and they agree -- the witness is what makes
    # that a checked fact rather than an assumed one.
    assert cite.statutes_at_large_witness == "both"


def test_a_cite_stating_no_statviewer_query_falls_back_to_the_prose_citation() -> None:
    # The 21st Century Cures Act states two cites: the first links a statviewer
    # page, the second states only "130 Stat. 1039". One of the 56 such rows.
    first, second = only("stated_citation_only", "cite")

    assert (first.statutes_at_large_volume, first.statutes_at_large_page) == ("130", "1033")
    assert first.statutes_at_large_witness == "both"
    assert (second.statutes_at_large_volume, second.statutes_at_large_page) == ("130", "1039")
    assert second.statutes_at_large_witness == "stated"


def test_a_cite_stating_neither_place_mints_no_volume() -> None:
    # The negative fixture: the real entry with both statements deleted. The
    # rule must refuse, not reach for the volume of some other citation.
    mutilated = (
        ENTRIES["statviewer_and_stated_citation_agree"]
        .replace("statviewer.htm?volume=134&amp;page=4879", "statviewer.htm")
        .replace("134 Stat. 4879", "")
    )
    (cite,) = [r for r in builder.parse_popular_names(mutilated).records if r.content_type == "cite"]

    assert (cite.statutes_at_large_volume, cite.statutes_at_large_page) == (None, None)
    assert cite.statutes_at_large_witness is None
    # And the rest of the row still reads, so the refusal is about one column.
    assert cite.table3_key == "116-286"


def test_a_table3_link_is_not_mistaken_for_a_statviewer_link() -> None:
    # The same entry also links "/table3/116_286.htm". Only the statviewer link
    # states a place, and only its query is read.
    entry = ENTRIES["statviewer_and_stated_citation_agree"]
    assert "/table3/116_286.htm" in entry
    assert builder.STATVIEWER.search('<a href="/table3/116_286.htm">116-286</a>') is None


# --- the record kinds -------------------------------------------------------


def test_the_tools_own_kinds_are_kept_distinct_and_verbatim() -> None:
    assert [r.content_type for r in records("statviewer_and_stated_citation_agree")] == ["cite"]
    assert [r.content_type for r in records("see")] == ["see"]
    assert [r.content_type for r in records("renamed")] == ["renamed"]
    assert [r.content_type for r in records("also_known_as")] == ["also-known-as", "cite"]
    assert [r.content_type for r in records("stated_citation_only")] == ["cite", "cite", "short-title-ref"]


def test_a_target_is_read_only_out_of_a_see_or_renamed_construction() -> None:
    (see,) = only("see", "see")
    (renamed,) = only("renamed", "renamed")

    assert (see.name, see.see_also) == ("Clean Water Act", "Federal Water Pollution Control Act")
    assert (renamed.name, renamed.see_also) == ("Internal Revenue Code", "Internal Revenue Code of 1939")


def test_also_known_as_reads_like_a_redirect_and_mints_none() -> None:
    # The negative fixture, published verbatim by OLRC: "Also known as the 21st
    # Century IDEA" is a naming fact, not a cross-reference, and the kind is
    # what says so.
    (aka,) = only("also_known_as", "also-known-as")

    assert aka.name == "21st Century Integrated Digital Experience Act"
    assert "Also known as the 21st Century IDEA" in ENTRIES["also_known_as"]
    assert aka.see_also is None


def test_a_short_title_reference_contributes_no_act_identity() -> None:
    # It anchors a section and states nothing about which act was enacted where.
    (reference,) = only("stated_citation_only", "short-title-ref")

    assert (reference.usc_title, reference.usc_section) == ("42", "201")
    assert reference.table3_key is None
    assert reference.division is None
    assert (reference.statutes_at_large_volume, reference.statutes_at_large_page) == (None, None)


def test_an_information_paragraph_without_a_kind_is_refused_rather_than_read() -> None:
    # Mutation of a real entry: OLRC states a content-type on all 20,865
    # paragraphs, so the only way to see the refusal is to remove one.
    mutilated = ENTRIES["see"].replace("content-type='see'", "")
    scan = builder.parse_popular_names(mutilated)

    assert scan.records == ()
    assert [d.reason for d in scan.defects] == ["information_without_a_content_type"]
    assert scan.defects[0].raw_value == "See Federal Water Pollution Control Act"


def test_an_entry_without_a_name_is_quarantined_rather_than_read() -> None:
    mutilated = ENTRIES["see"].replace("<p class='popular-name'>Clean Water Act</p>", "<p class='popular-name'></p>")
    scan = builder.parse_popular_names(mutilated)

    assert scan.records == ()
    assert [(d.reason, d.raw_value) for d in scan.defects] == [("entry_without_a_name", "CleanWaterAct")]


# --- the U.S. Code anchor ---------------------------------------------------


def test_a_usc_anchor_is_read_only_in_the_title_colon_section_shape() -> None:
    # One entry states both: "18:App.)" is title 18 with a section suffix the
    # identifier grammar excludes -- the source speaking, and kept -- while
    # "18A:1" names an appendix title, which is not U.S. Code title 18.
    cite, reference = records("usckey_accepted_and_refused")

    assert (cite.usc_title, cite.usc_section) == ("18", "App.)")
    assert cite.refused_usc_anchor is None
    assert (reference.usc_title, reference.usc_section) == (None, None)
    assert reference.refused_usc_anchor == "18A:1"


def test_a_refused_anchor_is_quarantined_with_the_value_it_refused() -> None:
    scan = builder.parse_popular_names(ENTRIES["usckey_accepted_and_refused"])

    assert [(d.reason, d.raw_value) for d in scan.defects] == [("usc_anchor_unparsable", "18A:1")]
    # The record itself survives: only the anchor was refused.
    assert len(scan.records) == 2


# --- ambiguity --------------------------------------------------------------


def test_a_name_stating_several_enacting_acts_keeps_every_row_and_is_counted() -> None:
    found = records("ambiguous_name")
    cites = [r for r in found if r.content_type == "cite"]

    assert [r.table3_key for r in cites] == ["109-148", "109-163"]
    assert builder.ambiguous_names(found) == {"detainee treatment act of 2005": ("109-148", "109-163")}


def test_a_name_stating_one_enacting_act_is_not_reported_as_ambiguous() -> None:
    assert builder.ambiguous_names(records("statviewer_and_stated_citation_agree")) == {}
    # Two cite rows, one act: repetition is not ambiguity.
    assert builder.ambiguous_names(records("stated_citation_only")) == {}


# --- equivalence with the frozen artifact -----------------------------------


@pytest.mark.slow
@pinned_html_required
@frozen_table_required
def test_every_row_this_build_parses_is_a_row_the_frozen_table_states() -> None:
    rows = builder.table_rows(builder.parse_popular_names(builder.read_pinned_html()).records)
    report = builder.compare_to_frozen(rows, FROZEN_TABLE)

    assert (report["derived_rows"], report["frozen_rows"]) == (20865, 20865)
    assert report["parsed_rows_identical"] is True
    # The whole delta, enumerated: four derived keys, no parsed value.
    assert report["rows_differing_only_in_a_derived_key"] == 4
    assert {item["column"] for item in report["differences"]} == {"name_key"}
    assert tuple(item["name"] for item in report["differences"]) == DELIBERATE_KEY_DIVERGENCES
    assert report["all_differences_collapse_under_the_loader_normalizer"] is True
    assert report["rows_identical"] is False


@pytest.mark.slow
@pinned_html_required
@frozen_table_required
def test_the_derived_table_is_the_frozen_one_after_the_loaders_own_normalization(tmp_path: Path) -> None:
    """Byte-identity, once the difference the loader erases is erased.

    Three digests, and they settle where the four-row delta comes from. The
    writer here reproduces the frozen bytes exactly from the frozen rows, so
    writer metadata is not a source of difference; and the derived table equals
    the frozen table with ``normalize_popular_name`` applied to its key columns
    -- which is what ``ActIndex.from_artifact`` does unconditionally on load.
    """

    def digest(path: Path) -> str:
        return f"sha256:{hashlib.sha256(path.read_bytes()).hexdigest()}"

    frozen = pq.read_table(FROZEN_TABLE).to_pylist()
    assert digest(FROZEN_TABLE) == FROZEN_DIGEST

    round_trip = tmp_path / "round-trip.parquet"
    builder.write_parquet(round_trip, builder.POPULAR_NAME_COLUMNS, frozen)
    assert digest(round_trip) == FROZEN_DIGEST, "the writer, not the parse, would be the difference"

    as_loaded = tmp_path / "as-loaded.parquet"
    builder.write_parquet(
        as_loaded,
        builder.POPULAR_NAME_COLUMNS,
        [
            {
                **row,
                "name_key": normalize_popular_name(row["name_key"]),
                "see_also_key": normalize_popular_name(row["see_also_key"]) if row["see_also_key"] else None,
            }
            for row in frozen
        ],
    )

    derived = tmp_path / "derived.parquet"
    builder.write_parquet(
        derived,
        builder.POPULAR_NAME_COLUMNS,
        builder.table_rows(builder.parse_popular_names(builder.read_pinned_html()).records),
    )
    assert digest(derived) == digest(as_loaded) == LOADED_DIGEST


@pytest.mark.slow
@pinned_html_required
def test_the_receipt_states_the_measurements_the_rules_were_derived_from(tmp_path: Path) -> None:
    receipt = builder.build(tmp_path / "artifact", html_path=builder.PINNED_HTML)

    assert receipt["coverage"]["entries"] == 13628
    assert receipt["coverage"]["popular_name_rows"] == 20865
    assert receipt["coverage"]["distinct_names"] == 13626
    assert receipt["coverage"]["release_points"] == ["119-102"]
    assert receipt["coverage"]["content_types"] == {
        "also-known-as": 665,
        "cite": 13087,
        "renamed": 113,
        "see": 484,
        "short-title-ref": 6516,
    }
    measured = receipt["measured"]
    assert measured["cite_rows_stating_both_places_and_agreeing"] == 12988
    assert measured["cite_rows_stating_only_the_prose_citation"] == 56
    assert measured["cite_rows_stating_only_the_statviewer_query"] == 0
    assert measured["cite_rows_stating_neither"] == 43
    # The rule's whole claim: a second witness that never contradicts the first.
    assert measured["cite_rows_where_the_two_places_disagree"] == 0
    # Stated by the page, carried by no column, and named rather than dropped.
    assert measured["stated_but_not_carried"] == {"datekey": 13047}
    assert receipt["coverage"]["quarantine_reasons"] == {
        "name_states_several_enacting_acts": 34,
        "usc_anchor_unparsable": 6,
    }
    assert receipt["inputs"]["popular_names_digest"] == (
        "sha256:65c5185e8e9508c8a22d8c2bf49d563808a45d053872af79d2bc95b7c2566a12"
    )
