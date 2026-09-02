"""The Executive Order existence oracle: the window split, and what it protects.

Five kinds of test.

**Pin tests** hold the roster to the digest ``eo_roster._ROSTER_PIN`` states,
and check that a drifted or swapped file refuses loudly rather than answering
differently -- the pattern is
:mod:`tests.test_usc_section_oracle`'s ``test_a_drifted_table_refuses_loudly``.

**Coherence tests** construct :class:`~refspec.registry.eo_roster.EoVerdict`
directly and hold every rejected shape: a window that does not contain the
number it authorizes, a source whose capture never saw that number, an
``absent`` outside the one window whose density licenses absence, a reason
that contradicts the window. Each is a verdict a consumer could have read as
coherent, so each gets its own negative fixture.

**Load-time evidence tests** (finding 2's guard): the roster's absence
authority is re-measured every time it loads. A hole in the declared dense
window, a source range declared wider than the roster attains, or a ``window``
column that does not contain its own number all refuse to load.

**Specimen tests**, against the real pinned roster: EO 8284 (real, published
in 4 FR 4603, whose per-order NARA route nonetheless 404s) is `exists` AND
carries a hand-reviewed flag; EO 9397 (a real, famous 1943 order the sparse
NARA window does not enumerate) is `unknown`, never `absent`; EO 12866 is
`exists` sourced to the Wayback-only half of the gap closure; the three
already-out-of-series numbers are `unknown`.

**Measurement tests** reproduce the corpus-wide numbers directly from the
shipped module, over a census bound by its own committed digest, and hold the
re-derivation ceremony's diff report to its named deltas.
"""

from __future__ import annotations

import csv
import hashlib
import inspect
from itertools import pairwise
from pathlib import Path
from types import MappingProxyType

import pytest

from refspec.registry import citation_grammar, eo_roster, hand_validated_interpretations
from refspec.registry.eo_roster import (
    _ROSTER_PIN,
    ABSENT_CAPABLE,
    EO_ROSTER_ARTIFACT,
    FR_API_DENSE_MAX,
    FR_API_WINDOW,
    NARA_CODIFICATION_WINDOW,
    NARA_DISPOSITION_WINDOW,
    UNKNOWN_REASONS,
    VERDICTS,
    WINDOWS,
    EoRosterOracle,
    EoVerdict,
    window_for,
)

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE_HOME = ROOT / EO_ROSTER_ARTIFACT
ROSTER_PATH = EVIDENCE_HOME / "derived" / "roster.csv"
INV_EO = ROOT / "research/evidence/investigations-2026-08-24/inv-eo"


def oracle() -> EoRosterOracle:
    return EoRosterOracle.from_repository(ROOT)


def _manifested_rows(path: Path, manifest: Path, root: Path) -> list[dict[str, str]]:
    """Rows of a CSV whose bytes match the digest its manifest committed.

    A measurement is only as good as the file it measured. Reading the census
    without checking it against
    ``inv-eo/derived/MANIFEST-sha256.csv`` would let an edited census quietly
    re-state what this suite claims to have measured.
    """

    relative = str(path.relative_to(root))
    expected = {
        row["relative_path"]: (int(row["bytes"]), row["sha256"])
        for row in csv.DictReader(manifest.open(newline=""))
    }
    assert relative in expected, f"{relative} is not manifested; it is not evidence this test may read"
    payload = path.read_bytes()
    assert (len(payload), hashlib.sha256(payload).hexdigest()) == expected[relative], (
        f"{relative} drifted from the digest its manifest committed"
    )
    return list(csv.DictReader(payload.decode("utf-8").splitlines()))


def _write_roster(path: Path, rows: list[tuple[int, str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["eo_number", "window", "source"])
        for eo_number, window, source in rows:
            writer.writerow([eo_number, window, source])


#: A miniature of the real window layout: one affirm-only window and one
#: absent-capable one, small enough that a test can write every row.
_SYNTHETIC_WINDOWS = MappingProxyType({"nara_codification": (9, 99), "fr_api": (200, 205)})


def _synthetic_oracle(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    rows: list[tuple[int, str, str]],
    *,
    windows: MappingProxyType | None = None,
    verify_density: bool = True,
) -> EoRosterOracle:
    """An oracle bound to a throwaway roster, with the module's own declared
    windows and source ranges swapped for ones this small roster satisfies.

    The real roster cannot exercise ``verdict``'s branches: its sparse windows
    span twelve thousand numbers and its dense one has no holes at all (which
    is exactly what :func:`~refspec.registry.eo_roster._verify_density`
    verifies). So the layout is miniaturised here, and ``verify_density`` is
    the one switch a test may throw to reach the `absent` branch -- see
    ``test_a_hole_in_the_dense_window_is_absent_but_only_past_the_load_guard``.
    """

    directory = tmp_path / "synthetic"
    roster = directory / "derived" / "roster.csv"
    _write_roster(roster, rows)
    monkeypatch.setattr(
        eo_roster, "_ROSTER_PIN", f"sha256:{hashlib.sha256(roster.read_bytes()).hexdigest()}"
    )
    monkeypatch.setattr(eo_roster, "WINDOWS", windows or _SYNTHETIC_WINDOWS)
    ranges: dict[str, tuple[int, int]] = {}
    for number, _, source in rows:
        low, high = ranges.get(source, (number, number))
        ranges[source] = (min(low, number), max(high, number))
    monkeypatch.setattr(eo_roster, "SOURCE_RANGES", MappingProxyType(ranges))
    if not verify_density:
        monkeypatch.setattr(eo_roster, "_verify_density", lambda rows: None)
    return EoRosterOracle.from_directory(directory)


# --------------------------------------------------------------------------- #
# Pin tests
# --------------------------------------------------------------------------- #


def test_the_pinned_roster_matches_its_stated_digest() -> None:
    digest = f"sha256:{hashlib.sha256(ROSTER_PATH.read_bytes()).hexdigest()}"
    assert digest == _ROSTER_PIN


def test_from_repository_verifies_and_binds() -> None:
    bound = oracle()
    bound.verify()  # must not raise
    assert bound.directory == EVIDENCE_HOME


def test_the_roster_is_parsed_from_the_very_bytes_that_were_hashed() -> None:
    """A verifier that hands back a PATH invites its caller to re-open the file.

    Between the hash and that second read the file can change, and the digest
    would then vouch for bytes nobody parsed. The race itself is not
    observable in a deterministic test, so what is pinned here is the shape
    that makes it impossible: the verifier returns the buffer, and the loader
    reads nothing else.
    """

    payload = eo_roster._verify_pinned_roster(EVIDENCE_HOME)
    assert isinstance(payload, bytes)
    assert hashlib.sha256(payload).hexdigest() == _ROSTER_PIN.removeprefix("sha256:")
    loader = inspect.getsource(EoRosterOracle.__dict__["_rows"].func)
    assert "read_bytes" not in loader and "open(" not in loader, (
        "the roster loader must parse the verified buffer, never re-open the file it hashed"
    )


def test_a_drifted_roster_refuses_loudly_and_names_itself(tmp_path: Path) -> None:
    directory = tmp_path / "drifted"
    (directory / "derived").mkdir(parents=True)
    (directory / "derived" / "roster.csv").write_bytes(ROSTER_PATH.read_bytes() + b"\n")
    with pytest.raises(ValueError, match="pinned EO roster drifted"):
        EoRosterOracle.from_directory(directory)
    # And nothing loads through the bare, unverified dataclass either.
    with pytest.raises(ValueError, match="drifted"):
        _ = EoRosterOracle(directory=directory).verdict(1)


# --------------------------------------------------------------------------- #
# EoVerdict coherence: every rejected construction
# --------------------------------------------------------------------------- #


def test_verdict_rejects_an_undeclared_value() -> None:
    with pytest.raises(ValueError, match="undeclared verdict"):
        EoVerdict(1000, "maybe", "nara_codification")


def test_unknown_must_name_its_reason_and_nothing_else_may() -> None:
    with pytest.raises(ValueError, match="names its coverage gap"):
        EoVerdict(1000, "unknown", "nara_codification")  # no reason
    with pytest.raises(ValueError, match="names its coverage gap"):
        EoVerdict(1000, "exists", "nara_codification", reason="nara_window_miss")


def test_unknown_reason_must_be_declared() -> None:
    with pytest.raises(ValueError, match="undeclared unknown reason"):
        EoVerdict(1, "unknown", None, reason="because I said so")


def test_exists_and_absent_must_name_a_real_window() -> None:
    with pytest.raises(ValueError, match="must name the window"):
        EoVerdict(1000, "exists", None)
    with pytest.raises(ValueError, match="undeclared window"):
        EoVerdict(1000, "absent", "some_other_window")


def test_a_window_must_contain_the_number_it_authorizes() -> None:
    """The incoherence a consumer could not see: an `exists` for EO 12866

    tagged ``nara_codification``, a window whose top is 12,667. The 32 gap
    rows carried exactly that label before this check existed, so a caller
    reading "which window vouched for this" got a window that does not
    contain the number.
    """

    with pytest.raises(ValueError, match="does not contain EO 12866"):
        EoVerdict(12_866, "exists", "nara_codification", source="gap-closure-wayback")
    # The coherent form of the same row loads.
    EoVerdict(12_866, "exists", "nara_disposition", source="gap-closure-wayback")


def test_absent_is_only_ever_the_fully_dense_window() -> None:
    """The whole design constraint in one invariant: a sparse window's miss

    structurally cannot become `absent`, even by constructing the dataclass
    directly.
    """

    with pytest.raises(ValueError, match="fully-dense fr_api window"):
        EoVerdict(1000, "absent", "nara_codification")
    with pytest.raises(ValueError, match="fully-dense fr_api window"):
        EoVerdict(12_700, "absent", "nara_disposition")
    EoVerdict(13_000, "absent", "fr_api")  # must not raise


def test_exists_must_name_a_source_and_only_exists_carries_one() -> None:
    with pytest.raises(ValueError, match="must name the capture that witnessed"):
        EoVerdict(1000, "exists", "nara_codification")
    with pytest.raises(ValueError, match="only an exists verdict carries a roster source"):
        EoVerdict(13_000, "absent", "fr_api", source="fr-api")
    with pytest.raises(ValueError, match="only an exists verdict carries a roster source"):
        EoVerdict(1, "unknown", None, reason="outside_known_windows", source="fr-api")


def test_an_exists_source_must_be_declared_and_must_reach_the_number() -> None:
    """A capture vouches for the range it actually saw, and no further.

    ``nara-disposition-1939`` is one calendar year's table (8,031-8,316). A
    roster row claiming it witnessed EO 12,000 is a shape error -- the kind
    an editing mistake or a merge-order change could introduce, and the kind
    that would otherwise publish an existence claim nothing supports.
    """

    with pytest.raises(ValueError, match="undeclared roster source"):
        EoVerdict(1000, "exists", "nara_codification", source="a-source-nobody-declared")
    with pytest.raises(ValueError, match="witnesses 8031-8316 and cannot vouch for EO 12000"):
        EoVerdict(12_000, "exists", "nara_codification", source="nara-disposition-1939")
    EoVerdict(8_284, "exists", "nara_codification", source="nara-disposition-1939")  # must not raise


def test_a_reason_must_agree_with_the_window() -> None:
    with pytest.raises(ValueError, match="names a miss inside an affirm-only window"):
        EoVerdict(13_000, "unknown", "fr_api", reason="nara_window_miss")
    with pytest.raises(ValueError, match="names a miss inside an affirm-only window"):
        EoVerdict(1, "unknown", None, reason="nara_window_miss")
    with pytest.raises(ValueError, match="outside_known_windows cannot describe EO 1000"):
        EoVerdict(1000, "unknown", None, reason="outside_known_windows")


# --------------------------------------------------------------------------- #
# Window behaviour (synthetic roster; exercises every branch)
# --------------------------------------------------------------------------- #


def test_a_window_hit_is_exists_and_carries_its_source(tmp_path, monkeypatch) -> None:
    rows = [(n, "fr_api", "fr-api") for n in range(200, 206)]
    bound = _synthetic_oracle(tmp_path, monkeypatch, rows)
    assert bound.verdict(203) == EoVerdict(203, "exists", "fr_api", source="fr-api")


def test_sparse_window_miss_is_unknown_never_absent(tmp_path, monkeypatch) -> None:
    """The whole point of the window split: an EMPTY sparse window must still

    never mint `absent` -- 34.7% density means most misses are coverage holes.
    """

    rows = [(n, "fr_api", "fr-api") for n in range(200, 206)]
    bound = _synthetic_oracle(tmp_path, monkeypatch, rows)
    for number in (9, 50, 99):
        verdict = bound.verdict(number)
        assert verdict.verdict == "unknown"
        assert verdict.window == "nara_codification"
        assert verdict.reason == "nara_window_miss"


def test_outside_every_window_is_unknown_with_a_different_reason(tmp_path, monkeypatch) -> None:
    rows = [(n, "fr_api", "fr-api") for n in range(200, 206)]
    bound = _synthetic_oracle(tmp_path, monkeypatch, rows)
    for number in (1, 8, 100, 199, 206, 99_999):
        verdict = bound.verdict(number)
        assert verdict.verdict == "unknown"
        assert verdict.window is None
        assert verdict.reason == "outside_known_windows"


def test_a_hole_in_the_dense_window_is_absent_but_only_past_the_load_guard(
    tmp_path, monkeypatch
) -> None:
    """`absent` and the density guard are two halves of one claim.

    A hole in the absent-capable window is precisely the evidence that
    licenses `absent` -- and precisely what
    :func:`~refspec.registry.eo_roster._verify_density` refuses to load,
    because a roster that no longer fills its declared dense window has a
    declaration to fix, not an absence to publish. So the branch below is
    unreachable on any roster that loads today, and reaching it here takes
    switching the guard off deliberately. That is the honest shape of the
    claim: `absent` is what this oracle would say if a re-derivation ever
    re-declared a dense window around a genuine hole, and a human re-pins
    before it ever says it.
    """

    rows = [(n, "fr_api", "fr-api") for n in (200, 201, 202, 204, 205)]
    with pytest.raises(ValueError, match="claims to be fully dense"):
        _synthetic_oracle(tmp_path, monkeypatch, rows).verdict(203)

    bound = _synthetic_oracle(tmp_path, monkeypatch, rows, verify_density=False)
    assert bound.verdict(203) == EoVerdict(203, "absent", "fr_api")


def test_a_roster_row_whose_window_does_not_contain_it_refuses_to_load(tmp_path, monkeypatch) -> None:
    rows = [(n, "fr_api", "fr-api") for n in range(200, 206)] + [(50, "fr_api", "fr-api")]
    with pytest.raises(ValueError, match="names window 'fr_api', which does not contain it"):
        _synthetic_oracle(tmp_path, monkeypatch, rows).verdict(50)


def test_a_source_range_wider_than_the_roster_attains_refuses_to_load(tmp_path, monkeypatch) -> None:
    """A declared range is a measurement, so it cannot be quietly widened.

    Widening one would wave numbers through :class:`EoVerdict`'s source check
    on the strength of a declaration rather than a capture.
    """

    rows = [(n, "fr_api", "fr-api") for n in range(200, 206)]
    bound = _synthetic_oracle(tmp_path, monkeypatch, rows)
    monkeypatch.setattr(eo_roster, "SOURCE_RANGES", MappingProxyType({"fr-api": (1, 99_999)}))
    with pytest.raises(ValueError, match="a declared range must be measured, not chosen"):
        _ = EoRosterOracle(directory=bound.directory).verdict(203)


def test_windows_are_declared_disjoint_and_ordered() -> None:
    spans = list(WINDOWS.values())
    assert spans == sorted(spans)
    for (_, high), (low, _) in pairwise(spans):
        assert high < low, "declared windows must not overlap"
    assert WINDOWS["nara_codification"] == NARA_CODIFICATION_WINDOW
    assert WINDOWS["nara_disposition"] == NARA_DISPOSITION_WINDOW
    assert WINDOWS["fr_api"] == FR_API_WINDOW
    assert ABSENT_CAPABLE == {"fr_api"}
    assert set(UNKNOWN_REASONS) == {"nara_window_miss", "outside_known_windows"}
    assert set(VERDICTS) == {"exists", "absent", "unknown"}
    assert window_for(8_284) == "nara_codification"
    assert window_for(FR_API_DENSE_MAX + 1) is None


# --------------------------------------------------------------------------- #
# The absence bound is evidence, not the grammar's ceiling
# --------------------------------------------------------------------------- #


def test_the_dense_windows_upper_bound_is_the_rosters_own_measurement() -> None:
    """``FR_API_DENSE_MAX`` restates the pinned roster, not a constant

    elsewhere. Read straight off the roster file here so a re-pin that moves
    the FR-API capture's top without moving the declaration breaks.
    """

    rows = list(csv.DictReader(ROSTER_PATH.read_bytes().decode("utf-8").splitlines()))
    fr_api_numbers = {int(row["eo_number"]) for row in rows if row["source"] == "fr-api"}
    assert max(fr_api_numbers) == FR_API_DENSE_MAX
    assert FR_API_WINDOW == (12_890, FR_API_DENSE_MAX)
    on_roster = {int(row["eo_number"]) for row in rows}
    assert set(range(*FR_API_WINDOW)) | {FR_API_WINDOW[1]} <= on_roster, "the dense window has a hole"


def test_the_grammar_ceiling_cannot_hand_this_oracle_absence_authority() -> None:
    """Finding 2's guard, held at the seam it would actually fail at.

    ``FR_API_WINDOW``'s top once tracked ``citation_grammar.EO_HIGHEST_KNOWN``
    while the roster stayed pinned, so a source edit advancing that constant
    for a newly signed order would have made ``verdict(14421)`` answer
    `absent` on evidence this module has never seen.

    The failure mode is a SOURCE EDIT, not a runtime value: both the old
    ``FR_API_WINDOW = (12_890, EO_HIGHEST_KNOWN)`` and a ``from ... import``
    of the constant are evaluated once at import, so monkeypatching
    ``citation_grammar`` afterwards proves nothing. What can be held is the
    coupling itself -- this module's namespace must carry no grammar ceiling
    under any spelling -- plus the behaviour above the measured bound. The
    two together were verified to fail when the coupling is reintroduced and
    the ceiling advanced (12 tests in this file break, and the load guard
    refuses by name).
    """

    leaked = {"citation_grammar", "EO_HIGHEST_KNOWN"} & set(vars(eo_roster))
    assert not leaked, (
        f"the oracle must not read the grammar's ceiling, but its namespace carries {sorted(leaked)}; "
        f"the two values coincide today by measurement, and nothing may assert that they must"
    )
    assert FR_API_DENSE_MAX == citation_grammar.EO_HIGHEST_KNOWN, (
        "not a requirement -- a note that today's coincidence is real, so a future divergence is "
        "read here first"
    )
    verdict = oracle().verdict(FR_API_DENSE_MAX + 1)
    assert verdict.verdict == "unknown"
    assert verdict.reason == "outside_known_windows"


def test_todays_dense_window_has_no_misses_at_all() -> None:
    """The measurement behind "absent is currently unreachable".

    Every integer the absent-capable window covers is on the roster, so no
    call to ``verdict`` in that range can take the `absent` branch. Held as a
    running fact rather than left implicit, because it is the reason the
    wiring spec predicts zero rows flipping to False.
    """

    bound = oracle()
    low, high = FR_API_WINDOW
    assert all(bound.verdict(number).verdict == "exists" for number in range(low, high + 1))


# --------------------------------------------------------------------------- #
# Specimen tests against the real pinned roster
# --------------------------------------------------------------------------- #


def test_eo_8284_exists_and_is_flagged_never_corrected() -> None:
    """The finding this lane was sent back for.

    EO 8284's per-order NARA route serves a Drupal "Page Not Found", and an
    earlier draft read that as the publisher denying the order. It is a fact
    about one route: NARA's own 1939 disposition table (pinned into this
    lane's evidence home) lists EO 8284, "Prescribing the Duties of the
    Librarian Emeritus of the Library of Congress", signed 1939-11-13, at
    4 FR 4603, and this repository's committed adjudication recorded the same
    title and date all along. So the verdict is `exists`, sourced to that
    table. The hand-validated FLAG survives, because the corpus row is still
    doubted -- on relevance, adjudicated elsewhere -- and a flag rides
    ALONGSIDE the verdict, never instead of it.
    """

    bound = oracle()
    verdict = bound.verdict(8284)
    assert verdict.verdict == "exists"
    assert verdict.window == "nara_codification"
    assert verdict.source == "nara-disposition-1939"

    flag = bound.flag_for(8284)
    assert flag is not None
    assert flag.disposition == "flag"
    assert flag.interpreted_value is None
    assert any("8248" in witness.shows for witness in flag.witnesses)


def test_eo_9397_amendment_chain_endpoint_is_unknown_not_absent() -> None:
    """Cross-lane negative fixture: the prose-harvest lane's amendment-chain

    walk cites EO 9397 (1943, the order that created Social Security
    numbers) as a chain endpoint. It falls inside the sparse NARA
    codification window and is NOT on the roster. A real, famous,
    unambiguously EXISTING order must still read `unknown`, never `absent`:
    that is exactly what the window split exists to prevent from going the
    other way.
    """

    verdict = oracle().verdict(9397)
    assert verdict.verdict == "unknown"
    assert verdict.window == "nara_codification"
    assert verdict.reason == "nara_window_miss"


def test_eo_12866_exists_sourced_to_the_wayback_only_gap_closure() -> None:
    """Regulatory Planning and Review, signed 1993-09-30 -- one of the gap

    numbers that resolve ONLY from a Wayback capture of a NARA page now dead
    on the live site (Durability section,
    research/investigations-mined-2026-08-31.md). ``source`` names exactly
    that so a caller can tell this durability profile apart from a live
    page's, and ``window`` names the gap-closure window that contains it
    rather than the codification window that does not.
    """

    verdict = oracle().verdict(12_866)
    assert verdict.verdict == "exists"
    assert verdict.window == "nara_disposition"
    assert verdict.source == "gap-closure-wayback"


def test_eo_8248_exists_and_carries_no_flag() -> None:
    """The flag's named candidate is an ordinary `exists` -- the flag names

    only 8284, never leaks onto 8248.
    """

    verdict = oracle().verdict(8248)
    assert verdict.verdict == "exists"
    assert oracle().flag_for(8248) is None


@pytest.mark.parametrize("number", [20450, 21600, 23891])
def test_already_out_of_series_numbers_are_unknown_not_a_crash(number: int) -> None:
    """These three exceed the roster's ceiling and are already flagged False

    by today's ``_SeriesCalendar.eo_in_known_series`` fence -- this oracle
    agrees they are not resolvable, by the same "outside every window" reason
    as anything else above the ceiling, not by re-deriving a second opinion
    about the ceiling itself.

    Called on an INSTANCE, not the class: the wiring spec turns
    ``eo_in_known_series`` into an instance method that consults the oracle,
    and a class-level call site would break with a TypeError the moment that
    lands.
    """

    from refspec.registry.unified_agenda_parquet import _SeriesCalendar

    verdict = oracle().verdict(number)
    assert verdict.verdict == "unknown"
    assert verdict.reason == "outside_known_windows"
    assert _SeriesCalendar.build(None).eo_in_known_series(str(number)) is False


def test_a_pre_1929_cited_number_is_unknown_with_no_special_casing_needed() -> None:
    """EO 1205 (cited 202204-202404) is real-shaped but pre-dates the NARA

    disposition-table era; the window split alone produces the right answer
    with no pre-1929 special rule.
    """

    verdict = oracle().verdict(1205)
    assert verdict.verdict == "unknown"
    assert verdict.reason == "nara_window_miss"


# --------------------------------------------------------------------------- #
# flag_for: what it will and will not hand back
# --------------------------------------------------------------------------- #


def test_flag_for_returns_none_when_no_flag_is_recorded() -> None:
    """Documented, not incidental: ``None`` means "no hand-validated flag is

    recorded for this number", which is the normal case for an EO number.
    """

    assert EoRosterOracle.flag_for(13_000) is None
    with pytest.raises(hand_validated_interpretations.NotReviewed):
        hand_validated_interpretations.lookup("13000")


def test_flag_for_refuses_to_hand_back_a_correction(monkeypatch) -> None:
    """A correction reaching a caller through a method named ``flag_for``

    would be a substitution arriving under a label that promises not to make
    one. The table already carries a correction row (for a Federal Register
    document number), so this is not hypothetical -- only the key differs.
    """

    correction = hand_validated_interpretations.lookup("E5-2394")
    assert correction.disposition == "correction"
    monkeypatch.setattr(hand_validated_interpretations, "lookup", lambda value: correction)
    with pytest.raises(
        hand_validated_interpretations.HandValidatedRegistryError, match="not a flag"
    ):
        EoRosterOracle.flag_for(8284)


def test_a_flag_row_cannot_be_constructed_as_a_correction() -> None:
    """Not just an observation about today's row -- the type itself refuses.

    A disposition of "flag" carrying an interpreted_value is a shape error in
    hand_validated_interpretations.Interpretation, so no future edit to the
    8284 row can smuggle a correction in without changing its disposition
    first, which is the loud, reviewable act this suite wants any such change
    to be -- and which ``flag_for`` above then refuses to serve.
    """

    with pytest.raises(hand_validated_interpretations.HandValidatedRegistryError, match="must not assert"):
        hand_validated_interpretations.Interpretation(
            source_value="8284",
            context="test",
            disposition="flag",
            witnesses=(hand_validated_interpretations.Witness(path="README.md", shows="exists"),),
            reviewer="test",
            reviewed_at="2026-08-31",
            interpreted_value="8248",
        )


# --------------------------------------------------------------------------- #
# Measurement tests: the module against the corpus's own census
# --------------------------------------------------------------------------- #


def test_measured_against_the_cited_eo_census() -> None:
    """The corpus-wide numbers, reproduced from the SHIPPED module over a

    census bound by the digest its own investigation committed, so neither an
    edited census nor a silent roster promotion can restate them.

    The mined note (research/investigations-mined-2026-08-31.md, item 5)
    predicted 377 numbers / 18,951 rows and 11 unknown. This roster affirms
    one more number than that: EO 8284, whose existence the mined note's
    source had wrongly doubted on a route-level 404. See README.md.
    """

    bound = oracle()
    census = _manifested_rows(
        INV_EO / "derived/cited-eo-census.csv", INV_EO / "derived/MANIFEST-sha256.csv", INV_EO
    )
    row_count = {int(row["eo_number"]): int(row["row_count"]) for row in census}

    verdicts = {number: bound.verdict(number) for number in row_count}
    covered = [n for n, v in verdicts.items() if v.verdict == "exists"]
    unknown_in_range = [
        n for n, v in verdicts.items() if v.verdict == "unknown" and v.reason == "nara_window_miss"
    ]
    already_out_of_series = [
        n for n, v in verdicts.items() if v.verdict == "unknown" and v.reason == "outside_known_windows"
    ]

    assert len(census) == 391
    assert sum(row_count.values()) == 19_011
    assert len(covered) == 378
    assert sum(row_count[n] for n in covered) == 18_954
    assert len(unknown_in_range) == 10
    assert sum(row_count[n] for n in unknown_in_range) == 50
    assert sorted(already_out_of_series) == [20450, 21600, 23891]
    assert 8284 in covered, "EO 8284 is a real order; a route-level 404 never made it absent"
    assert all(n > FR_API_DENSE_MAX for n in already_out_of_series)
    assert not any(v.verdict == "absent" for v in verdicts.values()), (
        "no cited EO number should ever read absent -- the dense window's density is "
        "measured, and it has no holes for a cited number to fall into"
    )


def test_the_rederivation_ceremony_names_every_delta() -> None:
    """Holds the evidence home's own diff report to its claims: nothing the

    investigation had was lost, every added number is one of the two named
    deltas, and EO 8284 arrives through the derivation rather than by hand.
    """

    report = (EVIDENCE_HOME / "diff-report.txt").read_text()
    assert "match=False" not in report
    assert "0 mismatches" in report
    assert "lost=[]" in report
    assert "added, UNEXPLAINED (expect empty): []" in report
    assert "covers-theirs=True" in report
    assert "EO 8284: on the roster=True source=nara-disposition-1939" in report


def test_the_evidence_home_manifest_is_a_two_way_inventory() -> None:
    """Both directions, because one direction is not an inventory.

    A one-way check (every manifest row hashes) passes happily over a
    directory carrying an unlisted file -- exactly the shape by which an
    unreviewed capture joins a sealed evidence home.
    """

    manifest_path = EVIDENCE_HOME / "MANIFEST-sha256.csv"
    rows = list(csv.DictReader(manifest_path.open(newline="")))
    assert rows

    listed = {row["relative_path"] for row in rows}
    on_disk = {
        str(path.relative_to(EVIDENCE_HOME))
        for path in EVIDENCE_HOME.rglob("*")
        if path.is_file() and path != manifest_path and "__pycache__" not in path.parts
    }
    assert listed == on_disk, (
        f"unlisted on disk: {sorted(on_disk - listed)}; listed but absent: {sorted(listed - on_disk)}"
    )

    for row in rows:
        payload = (EVIDENCE_HOME / row["relative_path"]).read_bytes()
        assert hashlib.sha256(payload).hexdigest() == row["sha256"], row["relative_path"]
        assert len(payload) == int(row["bytes"]), row["relative_path"]


def test_the_pinned_raw_captures_back_the_8284_claim() -> None:
    """The two captures this lane fetched, read for what they actually say.

    Not a digest check (the manifest test above does that) but a content
    check: the NARA year table has to carry the order between its neighbours,
    and the Federal Register issue has to carry the signed text.
    """

    raw = EVIDENCE_HOME / "raw"
    nara = (raw / "nara-eo-1939.html").read_text(encoding="utf-8", errors="replace")
    assert '<a name="8283"></a>' in nara
    assert '<a name="8284"></a>' in nara
    assert '<a name="8285"></a>' in nara
    assert "Prescribing the Duties of the Librarian Emeritus of the Library of Congress" in nara
    assert "4 FR 4603, November 17, 1939" in nara

    pypdf = pytest.importorskip("pypdf")
    reader = pypdf.PdfReader(str(raw / "govinfo-FR-1939-11-17.pdf"))
    text = "".join(page.extract_text() or "" for page in reader.pages)
    assert "Librarian Emeritus" in text
    assert "November 13, 1939" in text


def test_the_capture_pins_agree_with_the_evidence_manifest() -> None:
    """The module restates two digests the evidence manifest also holds.

    Two copies of one fact drift, so this is the tripwire that says when they
    have. The captures are provenance rather than a runtime input -- the reader
    consumes the derived roster -- but their URLs reach the audit manifest's
    ``declaredUrls`` because this module states them, which is the whole reason
    they live here rather than only in the evidence home.
    """

    import csv

    from refspec.registry.eo_roster import (
        GOVINFO_FR_1939_11_17_CAPTURE,
        NARA_EO_1939_CAPTURE,
    )

    manifest = {
        row["relative_path"]: row
        for row in csv.DictReader((EVIDENCE_HOME / "MANIFEST-sha256.csv").read_text().splitlines())
    }
    for relative_path, pin in (
        ("raw/nara-eo-1939.html", NARA_EO_1939_CAPTURE),
        ("raw/govinfo-FR-1939-11-17.pdf", GOVINFO_FR_1939_11_17_CAPTURE),
    ):
        row = manifest[relative_path]
        assert pin.expected_sha256 == f"sha256:{row['sha256']}", relative_path
        assert pin.expected_byte_length == int(row["bytes"]), relative_path
        assert pin.source_url.startswith("https://"), relative_path
