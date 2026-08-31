"""Agency crosswalk: curated sealed-build data plus the three measured rules.

RefSpec intake ledger port 1.5. ``refspec.registry.agency_crosswalk`` ships
the sealed 2026-08-02 agency-crosswalk build's mapping as curated data
(decision-tree branch 3 -- see the module docstring for why exact
re-derivation from local ``~/Work/corpora`` inputs is not currently
possible) plus small, data-independent reimplementations of its three
measured rules. This suite:

* pins the sealed receipt's tier histogram and several specific real
  mappings, named by agency, against the shipped data;
* proves each of the three rules with a positive and a negative fixture; and
* cross-checks the shipped rule functions against the *entire* embedded
  dataset (all 316 codes / 914 candidates), so a change to the ranking or
  tiering algorithm that disagrees with the sealed build's own verdict on
  any single code fails immediately.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

import pytest

from refspec.registry import agency_crosswalk as m

CORPORA_ROOT = Path.home() / "Work/corpora/_preserved-2026-08-27/rin-ontology-revision-candidate"


# ---------------------------------------------------------------------------
# Curated data: shape, histogram, and named real mappings.
# ---------------------------------------------------------------------------


def test_curated_tables_carry_the_sealed_build_row_counts() -> None:
    assert len(m.AGENCY_CROSSWALK) == 316
    assert len(m.AGENCY_CROSSWALK_CANDIDATES) == 914
    assert len({entry.agency_code for entry in m.AGENCY_CROSSWALK}) == 316


def test_tier_histogram_matches_sealed_receipt_exactly() -> None:
    expected = {"confident": 124, "probable": 29, "ambiguous": 23, "unmapped": 140}
    assert dict(m.AGENCY_CROSSWALK_TIER_HISTOGRAM) == expected
    assert m.tier_histogram() == expected
    assert sum(expected.values()) == len(m.AGENCY_CROSSWALK)


@pytest.mark.parametrize(
    ("agency_code", "tier", "primary_slug"),
    [
        # confident: high-share, well-supported. Named agencies anyone can
        # eyeball against the sealed agency-codes.parquet.
        ("EPA", "confident", "environmental-protection-agency"),
        ("FDA", "confident", "food-and-drug-administration"),
        ("IRS", "confident", "internal-revenue-service"),
        ("NOAA", "confident", "national-oceanic-and-atmospheric-administration"),
        ("HHS", "confident", "health-and-human-services-department"),
        # probable: perfect share but under the confident document floor (5).
        ("ACUS", "probable", "administrative-conference-of-the-united-states"),
        # ambiguous: perfect share but only 1 supporting document -- below
        # even the probable floor (2).
        ("CDFI", "ambiguous", "community-development-financial-institutions-fund"),
        # unmapped: a real regulations.gov code (used on the documents table)
        # the join never reached -- zero supporting evidence either path.
        ("ABMC", "unmapped", None),
    ],
)
def test_specific_real_agency_mappings(agency_code: str, tier: str, primary_slug: str | None) -> None:
    entry = m.AGENCY_CROSSWALK_BY_CODE[agency_code]
    assert entry.tier == tier
    assert entry.primary_slug == primary_slug


def test_unmapped_entries_have_no_primary_slug_and_confident_entries_do() -> None:
    for entry in m.AGENCY_CROSSWALK:
        if entry.tier == "unmapped":
            assert entry.primary_slug is None
            assert entry.support_documents == 0
        else:
            assert entry.primary_slug is not None
            assert entry.support_documents > 0


# ---------------------------------------------------------------------------
# Whole-dataset self-consistency: the shipped rule functions must reproduce
# the sealed build's own verdict on every single code, not just the examples.
# ---------------------------------------------------------------------------


def test_tier_for_share_reproduces_every_entrys_sealed_tier() -> None:
    for entry in m.AGENCY_CROSSWALK:
        assert m.tier_for_share(entry.confidence_share, entry.support_documents) == entry.tier


def test_rank_crosswalk_candidates_reproduces_every_codes_sealed_rank_order() -> None:
    for code, entry in m.AGENCY_CROSSWALK_BY_CODE.items():
        candidates = m.candidates_for_code(code)
        if not candidates:
            assert entry.primary_slug is None
            continue
        shares = [m.CrosswalkCandidateShare(c.agency_slug, c.share, c.depth) for c in candidates]
        ranked = m.rank_crosswalk_candidates(shares)
        sealed_order = tuple(c.agency_slug for c in sorted(candidates, key=lambda c: c.rank))
        assert ranked == sealed_order
        assert ranked[0] == entry.primary_slug


def test_candidate_rows_group_correctly_under_their_own_agency_code() -> None:
    for candidate in m.AGENCY_CROSSWALK_CANDIDATES:
        assert candidate in m.candidates_for_code(candidate.agency_code)
    # rank 1 is always exactly the is_primary row.
    for code in m.AGENCY_CROSSWALK_BY_CODE:
        candidates = m.candidates_for_code(code)
        primaries = [c for c in candidates if c.is_primary]
        if not candidates:
            continue
        assert len(primaries) == 1
        assert primaries[0].rank == 1


# ---------------------------------------------------------------------------
# Rule 3: 0.05-share specificity margin -- positive and negative fixture.
# ---------------------------------------------------------------------------


def test_rule3_specificity_margin_prefers_the_sub_agency_within_the_margin() -> None:
    """FAA: the department's share (0.999843) is HIGHER than the bureau's
    (0.999056), but the 0.000787 gap is inside SPECIFICITY_MARGIN (0.05), so
    the deeper slug (the sub-agency) wins -- the positive case the reference
    builder's own docstring names.
    """
    candidates = m.candidates_for_code("FAA")
    department = next(c for c in candidates if c.agency_slug == "transportation-department")
    bureau = next(c for c in candidates if c.agency_slug == "federal-aviation-administration")
    assert bureau.share < department.share
    assert department.share - bureau.share < m.SPECIFICITY_MARGIN
    assert bureau.depth > department.depth

    shares = [m.CrosswalkCandidateShare(c.agency_slug, c.share, c.depth) for c in candidates]
    ranked = m.rank_crosswalk_candidates(shares)
    assert ranked[0] == "federal-aviation-administration"
    assert m.AGENCY_CROSSWALK_BY_CODE["FAA"].primary_slug == "federal-aviation-administration"


def test_rule3_specificity_margin_does_not_reach_a_sub_agency_below_the_margin() -> None:
    """BOEM: the bureau's share (0.935103) is 0.0649 below the department's
    (1.0) -- outside SPECIFICITY_MARGIN (0.05) -- so depth is never
    consulted and the sub-agency is correctly NOT preferred. This is the
    negative fixture: a sub-agency whose share gap exceeds the margin must
    lose despite being the more specific slug.
    """
    candidates = m.candidates_for_code("BOEM")
    department = next(c for c in candidates if c.agency_slug == "interior-department")
    bureau = next(c for c in candidates if c.agency_slug == "ocean-energy-management-bureau")
    assert department.share - bureau.share > m.SPECIFICITY_MARGIN
    assert bureau.depth > department.depth

    shares = [m.CrosswalkCandidateShare(c.agency_slug, c.share, c.depth) for c in candidates]
    ranked = m.rank_crosswalk_candidates(shares)
    assert ranked[0] == "interior-department"
    assert ranked[0] != "ocean-energy-management-bureau"
    assert m.AGENCY_CROSSWALK_BY_CODE["BOEM"].primary_slug == "interior-department"


def test_rule3_margin_is_exclusive_at_the_boundary() -> None:
    """A candidate exactly SPECIFICITY_MARGIN below the best share is tied
    (inclusive `>=`); a hair further below is not.
    """
    tied = [
        m.CrosswalkCandidateShare("deep-agency", 0.95, depth=1),
        m.CrosswalkCandidateShare("shallow-agency", 1.0, depth=0),
    ]
    assert m.rank_crosswalk_candidates(tied)[0] == "deep-agency"

    not_tied = [
        m.CrosswalkCandidateShare("deep-agency", 0.949999, depth=1),
        m.CrosswalkCandidateShare("shallow-agency", 1.0, depth=0),
    ]
    assert m.rank_crosswalk_candidates(not_tied)[0] == "shallow-agency"


# ---------------------------------------------------------------------------
# Rule 2: decorated-ID normalization only when it resolves to a unique docket.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("FAA-2026-3485", "FAA-2026-3485"),
        ("Docket No. FAA-2026-3485", "FAA-2026-3485"),
        ("DOCKET NO. FAA-2026-3485", "FAA-2026-3485"),
        ("Doc. No. FAA-2026-3485", "FAA-2026-3485"),
        ("  FAA 2026 3485  ", "FAA20263485"),
        # The two forms the sealed spelling half-stripped (xhigh review catch,
        # 2026-08-31): the plural counter word, and the counter word's period
        # abutting the identifier. Each used to leave the counter glued on
        # ("NOS.FDA-...", "NO.CDC-...") and resolve not_found.
        ("Docket Nos. FDA-2025-E-0162", "FDA-2025-E-0162"),
        ("Docket No.CDC-2018-0075", "CDC-2018-0075"),
        ("Docket Number: EPA-HQ-OW-2020-0530", "EPA-HQ-OW-2020-0530"),
        # The guards the wider spelling must not break: a real identifier
        # opening on DOC or DOCKET, and an organization that really is NOS
        # (National Ocean Service) -- the zero-space strip is licensed only
        # by the counter word's own period, never by the bare word.
        ("DOC-2005-0010", "DOC-2005-0010"),
        ("DOCKET-2020-0001", "DOCKET-2020-0001"),
        ("Docket NOS-2020-0001", "NOS-2020-0001"),
        ("", ""),
        (None, ""),
    ],
)
def test_normalize_docket_id_strips_decoration_whitespace_and_case(raw: object, expected: str) -> None:
    assert m.normalize_docket_id(raw) == expected


def test_rule2_direct_and_normalized_resolution_succeed() -> None:
    docket_codes = {"FAA-2026-3485": "FAA"}

    direct = m.resolve_docket_agency_code("FAA-2026-3485", docket_codes)
    assert direct == m.DocketAgencyResolution("direct", "FAA")

    decorated = m.resolve_docket_agency_code("Docket No. FAA-2026-3485", docket_codes)
    assert decorated == m.DocketAgencyResolution("normalized", "FAA")


def test_rule2_unknown_docket_is_not_found_not_guessed() -> None:
    result = m.resolve_docket_agency_code("Docket No. ZZZ-9999-0000", {"FAA-2026-3485": "FAA"})
    assert result == m.DocketAgencyResolution("not_found", None)


def test_rule2_refuses_ambiguous_normalization_negative_fixture() -> None:
    """Two distinct raw docket ids that collide only after whitespace
    removal must refuse resolution rather than silently pick one -- the
    negative fixture for "decorated-ID normalization only when unique".
    """
    docket_codes = {
        "ABC-2020-0001": "AGENCY-ONE",
        "ABC-2020 -0001": "AGENCY-TWO",  # differs only by an internal space
    }
    # sanity: these two really do collide under normalization.
    assert m.normalize_docket_id("ABC-2020-0001") == m.normalize_docket_id("ABC-2020 -0001")

    result = m.resolve_docket_agency_code("DOCKET NO. ABC-2020- 0001 ", docket_codes)
    assert result.status == "ambiguous"
    assert result.agency_code is None


def test_rule2_build_normalized_docket_index_groups_by_key() -> None:
    docket_codes = {
        "ABC-2020-0001": "AGENCY-ONE",
        "ABC-2020 -0001": "AGENCY-TWO",
        "XYZ-2021-0002": "AGENCY-THREE",
    }
    index = m.build_normalized_docket_index(docket_codes)
    collisions = {key: ids for key, ids in index.items() if len(ids) > 1}
    assert collisions == {"ABC-2020-0001": frozenset({"ABC-2020-0001", "ABC-2020 -0001"})}


@pytest.mark.slow
def test_rule2_real_dockets_have_zero_normalization_collisions() -> None:
    """Cross-check against the byte-identical real dockets.parquet input
    (one of three of the sealed receipt's four raw inputs that still match
    -- see AGENCY_CROSSWALK_REGENERATION_STATUS): the sealed build's own
    claim of zero normalized-key collisions across 276,326 real dockets
    still holds.
    """
    path = CORPORA_ROOT / "dockets.parquet"
    if not path.exists():
        pytest.skip("~/Work/corpora checkout not present on this machine")

    payload = path.read_bytes()
    actual_sha256 = f"sha256:{hashlib.sha256(payload).hexdigest()}"
    assert actual_sha256 == m.AGENCY_CROSSWALK_INPUT_DIGESTS["dockets.parquet"], (
        "local dockets.parquet no longer matches the sealed receipt's pinned input"
    )

    pq = pytest.importorskip("pyarrow.parquet")
    table = pq.read_table(path, columns=["docket_id", "agency_code"])
    docket_codes: dict[str, str] = {}
    for row in table.to_pylist():
        docket_id, code = row["docket_id"], row["agency_code"]
        if docket_id and code:
            docket_codes[docket_id] = code

    assert len(docket_codes) == m.AGENCY_CROSSWALK_INPUT_ROW_COUNTS["dockets.parquet"]
    index = m.build_normalized_docket_index(docket_codes)
    collisions = {key: ids for key, ids in index.items() if len(ids) > 1}
    assert collisions == {}


# ---------------------------------------------------------------------------
# Rule 1: no docket-prefix inference.
# ---------------------------------------------------------------------------


def _naive_prefix_guess(docket_like: str) -> str:
    """The WRONG approach this module refuses to take, sketched here only to
    prove why: guessing an agency code from a docket-like string's leading
    letters.
    """
    match = re.match(r"^([A-Za-z]+)-", docket_like)
    return match.group(1).upper() if match else ""


def test_rule1_no_docket_prefix_inference_fabricates_nonexistent_codes() -> None:
    """Real Federal Register docket-link fields carry docket-like strings
    that are not regulations.gov dockets at all (the module docstring's
    579,669-of-715,080 "foreign identifier" population): IRS's Treasury
    regulation-project numbers ("REG-...") and EPA's own Federal Register
    document numbers ("FRL-..."). A prefix guess on either fabricates an
    agency code that does not exist anywhere in the real 316-code universe.
    """
    assert _naive_prefix_guess("REG-100163-00") not in m.AGENCY_CROSSWALK_BY_CODE
    assert _naive_prefix_guess("FRL-6543-2") not in m.AGENCY_CROSSWALK_BY_CODE


def test_rule1_no_docket_prefix_inference_cannot_trust_a_compound_string() -> None:
    """"CMS-0003-F and CMS-0005-F" names two dockets in one field value. Its
    prefix happens to spell a real code (CMS) -- which is exactly the trap:
    a prefix guess cannot distinguish "one valid docket id" from "two
    dockets joined by 'and'", so resolve_docket_agency_code never parses a
    docket id's characters at all, only ever looking it up as a whole
    string (rule 1), which correctly finds no match for this malformed value.
    """
    compound = "CMS-0003-F and CMS-0005-F"
    assert _naive_prefix_guess(compound) in m.AGENCY_CROSSWALK_BY_CODE  # the trap: looks right

    result = m.resolve_docket_agency_code(compound, {"CMS-0003-F": "CMS", "CMS-0005-F": "CMS"})
    assert result == m.DocketAgencyResolution("not_found", None)


def test_rule1_resolve_docket_agency_code_never_inspects_prefix_characters() -> None:
    """A docket id sharing a real agency's exact prefix letters but
    registered under a DIFFERENT code must resolve to the code actually on
    file, never to a guess from its own letters.
    """
    docket_codes = {"EPA-HQ-OW-2020-0001": "OTHER-AGENCY"}
    result = m.resolve_docket_agency_code("EPA-HQ-OW-2020-0001", docket_codes)
    assert result == m.DocketAgencyResolution("direct", "OTHER-AGENCY")
    assert result.agency_code != "EPA"


def test_module_exposes_no_prefix_inference_helper() -> None:
    """Structural guard: nothing in the public API guesses from a docket
    string's prefix. If a future change adds one, this test names it.
    """
    suspicious = {name for name in m.__all__ if "prefix" in name.lower() or "guess" in name.lower()}
    assert suspicious == set()


# ---------------------------------------------------------------------------
# Module hygiene.
# ---------------------------------------------------------------------------


def test_all_exports_are_defined_on_the_module() -> None:
    missing = [name for name in m.__all__ if not hasattr(m, name)]
    assert missing == []


def test_input_digest_and_row_count_provenance_share_the_same_four_files() -> None:
    assert set(m.AGENCY_CROSSWALK_INPUT_DIGESTS) == set(m.AGENCY_CROSSWALK_INPUT_ROW_COUNTS)
    assert all(digest.startswith("sha256:") for digest in m.AGENCY_CROSSWALK_INPUT_DIGESTS.values())
