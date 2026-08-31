"""What ``tools/build_usc_source_credits.py`` retains, refuses, and reproduces.

Every credit these tests assert against is the verbatim flattened text of a real
``<sourceCredit>`` in release point 119-102, pinned by
``research/evidence/usc-regeneration-2026-08-31/fixtures/uslm-source-credits.json``
and cut by that directory's ``scripts/extract_fixtures.py``. The USLM scaffold
around a credit is built here rather than pinned, because the ancestry -- not
the markup -- is the fact under test, and because the cases that must be refused
(a credit under no section, a credit whose page its own citation never states)
do not occur on this release point and can only be reached by mutating a real
one. Each such mutation is named where it is made.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from tools import build_usc_source_credits as builder

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "research" / "evidence" / "usc-regeneration-2026-08-31"
CREDITS = json.loads((EVIDENCE / "fixtures" / "uslm-source-credits.json").read_text(encoding="utf-8"))

FROZEN_ARTIFACT = ROOT / "output" / "usc-source-credit-index-2026-08-02"
FROZEN_TABLE = FROZEN_ARTIFACT / "usc-source-credits.parquet"
#: The digest ``act_resolution.py:147`` pins. This build reproduces it byte for
#: byte from the salvaged release-point archive.
FROZEN_DIGEST = "sha256:d377545fe60d592a120bda30dffba665380cf82f826ae06cb327a581f0af9d8a"

archive_required = pytest.mark.skipif(
    not builder.DEFAULT_ARCHIVE.exists(), reason=f"release-point archive absent: {builder.DEFAULT_ARCHIVE}"
)
frozen_required = pytest.mark.skipif(
    not FROZEN_TABLE.exists(), reason=f"frozen source-credit table absent: {FROZEN_TABLE}"
)


def credit(label: str) -> str:
    return CREDITS[label]["credit"]


def identifier(label: str) -> str:
    return CREDITS[label]["identifier"]


def _unit(section_identifier: str | None, text: str) -> tuple[str, str, str]:
    opening = f'<section identifier="{section_identifier}">' if section_identifier is not None else "<chapter>"
    closing = "</section>" if section_identifier is not None else "</chapter>"
    return opening, f"<sourceCredit>{text}</sourceCredit>", closing


def uslm(*sections: tuple[str | None, str]) -> str:
    """A minimal USLM title carrying the given ``(identifier, credit)`` pairs."""
    body = "".join("".join(_unit(*section)) for section in sections)
    return f'<?xml version="1.0" encoding="UTF-8"?><uscDoc>{body}</uscDoc>'


def uslm_with_a_nested_section(outer: tuple[str, str], inner: tuple[str, str]) -> str:
    """The shape a nearest-preceding-tag scan gets wrong.

    The inner section closes *before* the outer section states its own credit,
    so the tag immediately preceding the outer credit is the inner section's
    close. Only the ancestry says whose credit it is.
    """
    outer_open, outer_credit, outer_close = _unit(*outer)
    body = f"{outer_open}{''.join(_unit(*inner))}{outer_credit}{outer_close}"
    return f'<?xml version="1.0" encoding="UTF-8"?><uscDoc>{body}</uscDoc>'


# --- the enactment construction ---------------------------------------------


def test_an_added_construction_is_the_only_thing_that_claims_an_enactment() -> None:
    scan = builder.scan_source_credits(uslm((identifier("added_enactment"), credit("added_enactment"))))

    assert scan.credits_scanned == 1
    assert scan.strict_matches == 1
    (retained,) = scan.credits
    assert (retained.public_law, retained.division, retained.act_section) == ("116-260", "EE", "107")
    assert (retained.usc_title, retained.usc_section) == ("26", "6038E")
    assert (retained.statutes_at_large_volume, retained.statutes_at_large_page) == ("134", "3048")


def test_a_citation_with_no_construction_is_refused_even_though_it_names_a_division() -> None:
    # 22 U.S.C. 2714a: "(Pub. L. 114-94, div. C, title XXXII, § 32101, ...)".
    # Everything the expression needs is present and the lead is not, so this
    # index carries no row for it.
    text = credit("no_construction_2714a")
    assert builder.ENACTMENT.search(text) is not None, "the citation matches; only the lead is missing"

    scan = builder.scan_source_credits(uslm((identifier("no_construction_2714a"), text)))

    assert (scan.credits_scanned, scan.strict_matches) == (1, 0)
    assert scan.credits == ()
    assert scan.quarantine == ()


def test_the_measured_false_positive_the_strict_rule_removes_stays_removed() -> None:
    # 26 U.S.C. 7652's credit names (116-260, div. EE, § 107) -- the act section
    # that enacted 26 U.S.C. 6038E -- and never uses the word "amended", which
    # is why reading the role by proximity to that word does not work either.
    text = credit("no_construction_7652")
    assert "116–260, div. EE" in text
    assert "amended" not in text

    scan = builder.scan_source_credits(uslm((identifier("no_construction_7652"), text)))

    assert scan.strict_matches == 0
    assert scan.credits == ()


def test_the_lead_is_read_across_an_intervening_structural_unit() -> None:
    # "as added Pub. L. 117-58, div. D, title I, § 40123" -- title I is crossed
    # and not captured, because the act section is the last one.
    scan = builder.scan_source_credits(uslm((identifier("en_dash_section"), credit("en_dash_section"))))

    (retained,) = scan.credits
    assert (retained.public_law, retained.division, retained.act_section) == ("117-58", "D", "40123")


# --- the bounded Statutes at Large lookup -----------------------------------


def test_the_page_search_stops_where_the_next_citation_begins() -> None:
    # 5 U.S.C. 3116: an enactment at 132 Stat. 2007 and an amendment at
    # 133 Stat. 1604, in one credit. They are not interchangeable.
    text = credit("enactment_then_amendment")
    scan = builder.scan_source_credits(uslm((identifier("enactment_then_amendment"), text)))

    (retained,) = scan.credits
    assert (retained.statutes_at_large_volume, retained.statutes_at_large_page) == ("132", "2007")
    assert "133 Stat. 1604" in text


def test_an_enactment_stating_no_page_of_its_own_borrows_none(tmp_path: Path) -> None:
    """The mutation the release point does not supply.

    On 119-102 every retained citation states its page before the next one
    begins, so the bound never changes an answer and cannot be shown working by
    real data alone. Deleting the enactment's own page from the real 5 U.S.C.
    3116 credit is what puts the rule under load: bounded, the row refuses;
    unbounded, it would reach past the semicolon and publish the *amendment's*
    133 Stat. 1604 as the enactment's page.
    """

    text = credit("enactment_then_amendment").replace(", Aug. 13, 2018, 132 Stat. 2007", ", Aug. 13, 2018")
    scan = builder.scan_source_credits(uslm((identifier("enactment_then_amendment"), text)))

    (retained,) = scan.credits
    assert (retained.statutes_at_large_volume, retained.statutes_at_large_page) == (None, None)

    matches = list(builder.ENACTMENT.finditer(text))
    assert builder.bounded_page(text, matches, 0) is None
    unbounded = builder.STATUTES_AT_LARGE.search(text, matches[0].end())
    assert unbounded is not None and unbounded.group("page") == "1604"
    # And the scan noticed that the bound was load-bearing on this text.
    assert scan.pages_the_bound_changed == 1


# --- attribution ------------------------------------------------------------


def test_a_credit_is_attributed_to_its_ancestor_not_its_nearest_preceding_tag() -> None:
    outer, inner = identifier("added_enactment"), identifier("enactment_then_amendment")
    document = uslm_with_a_nested_section(
        (outer, credit("added_enactment")),
        (inner, credit("enactment_then_amendment")),
    )
    # The tag immediately before the outer credit is the inner section's close.
    assert document.index("</section>") < document.index(credit("added_enactment"))

    seen = list(builder.iter_source_credits(document))
    assert [section for section, _ in seen] == [inner, outer]

    # And the attribution survives the whole scan, not just the walk.
    scan = builder.scan_source_credits(document)
    assert {c.usc_identifier: (c.usc_title, c.usc_section) for c in scan.credits} == {
        outer: ("26", "6038E"),
        inner: ("5", "3116"),
    }


def test_a_uslm_en_dash_section_is_straightened_and_the_verbatim_identifier_kept() -> None:
    scan = builder.scan_source_credits(uslm((identifier("en_dash_section"), credit("en_dash_section"))))

    (retained,) = scan.credits
    assert identifier("en_dash_section") == "/us/usc/t16/s824s–1"
    assert retained.usc_section == "824s-1"
    assert retained.usc_identifier == "/us/usc/t16/s824s–1"


def test_a_credit_under_no_section_is_quarantined_rather_than_attributed() -> None:
    # Mutation: the real enactment credit re-parented under a chapter. Release
    # point 119-102 has no such credit that also matches the strict rule
    # (``credits_outside_a_section`` is 0), so the reason code is only
    # exercisable by moving one.
    scan = builder.scan_source_credits(uslm((None, credit("added_enactment"))))

    assert scan.credits == ()
    assert scan.credits_outside_a_section == 1
    (quarantined,) = scan.quarantine
    assert quarantined.reason == "credit_outside_usc_section"
    assert (quarantined.public_law, quarantined.division, quarantined.act_section) == ("116-260", "EE", "107")


def test_an_appendix_section_identifier_is_quarantined_rather_than_read_as_a_section() -> None:
    # "/us/usc/t18a/pl/91/538/s1" is an appendix path, and t18a is not title 18.
    scan = builder.scan_source_credits(uslm(("/us/usc/t18a/pl/91/538/s1", credit("added_enactment"))))

    assert scan.credits == ()
    assert scan.credits_outside_a_section == 0
    (quarantined,) = scan.quarantine
    assert quarantined.reason == "section_identifier_unparsable"
    assert quarantined.raw_value == "/us/usc/t18a/pl/91/538/s1"


def test_a_subsection_identifier_is_not_a_section_identifier() -> None:
    assert builder.USC_SECTION_IDENTIFIER.fullmatch("/us/usc/t26/s6038E") is not None
    assert builder.USC_SECTION_IDENTIFIER.fullmatch("/us/usc/t26/s6038E/a") is None


def test_a_release_point_of_any_other_shape_is_refused_rather_than_turned_into_a_url() -> None:
    assert builder.uslm_release_url("119-102").endswith("/us/pl/119/102/xml_uscAll@119-102.zip")
    for refused in ("", "119", "119-", "0-1", "119_102"):
        with pytest.raises(ValueError):
            builder.uslm_release_url(refused)


# --- equivalence with the frozen artifact -----------------------------------


@pytest.mark.slow
@archive_required
@frozen_required
def test_the_derived_table_is_byte_identical_to_the_frozen_source_credit_index(tmp_path: Path) -> None:
    scan, _ = builder.scan_release_zip(builder.DEFAULT_ARCHIVE)
    rows = builder.credit_rows(scan.credits)

    report = builder.compare_to_frozen(rows, FROZEN_TABLE)
    assert (report["derived_rows"], report["frozen_rows"]) == (3721, 3721)
    assert report["rows_identical"] is True
    assert report["rows_only_in_derived"] == []
    assert report["rows_only_in_frozen"] == []

    derived = tmp_path / "usc-source-credits.parquet"
    builder.write_parquet(derived, builder.CREDIT_COLUMNS, rows)
    assert f"sha256:{hashlib.sha256(derived.read_bytes()).hexdigest()}" == FROZEN_DIGEST
    assert f"sha256:{hashlib.sha256(FROZEN_TABLE.read_bytes()).hexdigest()}" == FROZEN_DIGEST


@pytest.mark.slow
@archive_required
@frozen_required
def test_the_receipt_reproduces_every_coverage_count_the_frozen_receipt_states(tmp_path: Path) -> None:
    frozen = json.loads((FROZEN_ARTIFACT / "receipt.json").read_text(encoding="utf-8"))
    receipt = builder.build(tmp_path / "artifact", archive=builder.DEFAULT_ARCHIVE, release_point="119-102")

    assert receipt["coverage"] == frozen["coverage"]
    assert receipt["inputs"]["archive_digest"] == frozen["inputs"]["archive_digest"]
    assert receipt["inputs"]["archive_bytes"] == frozen["inputs"]["archive_bytes"]
    assert receipt["inputs"]["titles"] == frozen["inputs"]["titles"]
    assert receipt["outputs"]["usc-source-credits.parquet"]["digest"] == FROZEN_DIGEST


@pytest.mark.slow
@archive_required
def test_bounding_the_page_search_changes_no_retained_answer_on_this_release_point() -> None:
    """The rule's measured effect, pinned rather than assumed.

    Zero is a fact about release point 119-102, not about the rule: the
    mutation above shows what the bound prevents. Pinning the count here means a
    release point where it stops being zero fails the suite instead of arriving
    as a quietly changed page number.
    """

    scan, _ = builder.scan_release_zip(builder.DEFAULT_ARCHIVE)

    assert scan.credits_scanned == 51548
    assert scan.pages_the_bound_changed == builder.BOUND_CHANGES_NO_ANSWER_ON_119_102 == 0
    assert sum(1 for c in scan.credits if c.statutes_at_large_page is None) == 0
