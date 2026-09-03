"""Loading rules, disposition typing, and what "a committed witness" means.

These tests pin the rules `hand_validated_interpretations.py`'s module
docstring states in prose: a row without a witness refuses to load, a witness
that is not committed bytes refuses to load, a correction needs more
witnesses than a flag or a refusal, and a disposition other than "correction"
may never carry an interpreted_value.

Three groups are worth calling out.

**The committed-bytes group** builds a real throwaway git repository in
``tmp_path`` and points witnesses at it, because every interesting negative
here is invisible to ``Path.is_file()``: a file that exists but was never
added, a spelling that differs from the index only in case (which resolves
happily on APFS), a tracked file edited after it was read, and a tracked
symlink out of the tree. Only git can tell those apart from a real witness,
so only a real git repository can test that they refuse.

**The anchor group** re-reads every witness of the real table and asserts
that a literal string quoted in that witness's ``shows`` text is present in
that witness's OWN bytes -- the check that catches a summary drifting onto
what a *neighbouring* file shows, which is how the print PDF's en dash and
two error-page bodies' transport statuses went wrong the first time.

**The boundary group** pins the "consulted, never applied" contract from this
side: ``lookup`` hands back the frozen row, and no public function in this
module returns a bare string a caller could mistake for the corrected value.

A note on caching: the module caches its git answers per repository root, for
the life of the process. That is right for repo tooling and wrong for a test
that mutates a repository mid-test, so the fixtures here mutate BEFORE
validating, and the two tests that swap the table clear the load caches
around themselves.
"""

from __future__ import annotations

import dataclasses
import inspect
import subprocess
import typing
from pathlib import Path

import pypdf
import pytest

from refspec.registry import hand_validated_interpretations as module
from refspec.registry.hand_validated_interpretations import (
    DISPOSITIONS,
    MINIMUM_WITNESSES,
    HandValidatedRegistryError,
    Interpretation,
    NotReviewed,
    Witness,
    build_interpretation,
    is_a_refused_federal_register_collision,
    load_interpretations,
    lookup,
    refused_federal_register_document_numbers,
)

ROOT = Path(__file__).resolve().parents[1]

_ONE_WITNESS = (
    Witness(
        path="research/evidence/hand-attestations-2026-08-31/README.md",
        shows="the evidence home's own ceremony statement",
    ),
)
_TWO_WITNESSES = (
    *_ONE_WITNESS,
    Witness(
        path="research/evidence/hand-attestations-2026-08-31/attestations.jsonl",
        shows="the founding row, as committed JSON",
    ),
)


def _row(**overrides: object) -> dict:
    base: dict = {
        "source_value": "test-value",
        "context": "a fixture row, not a real interpretation",
        "disposition": "flag",
        "witnesses": _ONE_WITNESS,
        "reviewer": "test-suite",
        "reviewed_at": "2026-08-31",
        "interpreted_value": None,
        "notes": "",
    }
    base.update(overrides)
    return base


# --- loading rules -----------------------------------------------------


def test_a_row_without_a_witness_refuses_to_load() -> None:
    with pytest.raises(HandValidatedRegistryError, match="no witnesses"):
        Interpretation(**{**_row(), "witnesses": ()})


def test_a_witness_pointing_at_an_uncommitted_path_refuses_to_load() -> None:
    """The negative fixture: a fabricated row with a dangling witness."""

    dangling = Witness(
        path="research/evidence/this-file-was-never-committed-2026-08-31.json",
        shows="nothing -- this path does not exist",
    )
    with pytest.raises(HandValidatedRegistryError, match="not a committed file"):
        build_interpretation(**{**_row(), "witnesses": (dangling,)})


def test_a_witness_with_no_path_or_no_shows_refuses_to_load() -> None:
    with pytest.raises(HandValidatedRegistryError, match="must name a path"):
        Witness(path="", shows="something")
    with pytest.raises(HandValidatedRegistryError, match="must say what it shows"):
        Witness(path="research/evidence/hand-attestations-2026-08-31/README.md", shows="")


@pytest.mark.parametrize(
    "path",
    [
        "/etc/passwd",  # absolute
        "../outside-the-repo.json",  # traversal
        "research/../../outside.json",  # traversal, mid-path
        "./research/evidence/hand-attestations-2026-08-31/README.md",  # non-canonical
        "research//evidence/hand-attestations-2026-08-31/README.md",  # non-canonical
        "research/evidence/hand-attestations-2026-08-31/",  # trailing slash
        "research\\evidence\\hand-attestations-2026-08-31\\README.md",  # not POSIX
    ],
)
def test_a_witness_path_must_be_a_canonical_repo_relative_posix_path(path: str) -> None:
    """Shape alone, before any filesystem or git question is asked.

    Every spelling here either escapes the repository or names one file two
    ways, and the git-membership check downstream compares byte-exactly
    against the index -- so a non-canonical spelling would refuse there too,
    with a much less informative message.
    """

    with pytest.raises(HandValidatedRegistryError, match="repo-root-relative"):
        Witness(path=path, shows="refused on shape alone")


def test_an_unknown_disposition_refuses_to_load() -> None:
    with pytest.raises(HandValidatedRegistryError, match="undeclared disposition"):
        Interpretation(**{**_row(), "disposition": "guess"})  # type: ignore[arg-type]


def test_reviewed_at_must_be_an_iso_date() -> None:
    with pytest.raises(HandValidatedRegistryError, match="ISO date"):
        Interpretation(**{**_row(), "reviewed_at": "August 31, 2026"})


def test_reviewer_and_context_and_source_value_must_be_non_empty() -> None:
    with pytest.raises(HandValidatedRegistryError, match="reviewer"):
        Interpretation(**{**_row(), "reviewer": "   "})
    with pytest.raises(HandValidatedRegistryError, match="context"):
        Interpretation(**{**_row(), "context": ""})
    with pytest.raises(HandValidatedRegistryError, match="source_value"):
        Interpretation(**{**_row(), "source_value": ""})


# --- what "a committed file" means (against a real throwaway repository) ----


def _run_git(root: Path, *arguments: str) -> None:
    subprocess.run(["git", "-C", str(root), *arguments], check=True, capture_output=True)


@pytest.fixture
def scratch_repo(tmp_path: Path) -> Path:
    """A real git repository with two committed files under ``evidence/``.

    Real, not simulated: the module asks git these questions, so anything
    less would test a mock's opinion of git rather than git's.
    """

    root = tmp_path / "scratch"
    (root / "evidence").mkdir(parents=True)
    _run_git(root.parent, "init", "-q", "-b", "main", str(root))
    _run_git(root, "config", "user.email", "lane-e@example.invalid")
    _run_git(root, "config", "user.name", "Lane E test suite")
    _run_git(root, "config", "commit.gpgsign", "false")
    (root / "evidence" / "README.md").write_text("committed witness bytes\n")
    (root / "evidence" / "second.txt").write_text("a second, distinct committed witness\n")
    _run_git(root, "add", "-A")
    _run_git(root, "commit", "-q", "-m", "committed evidence")
    return root


def _scratch_row(root: Path, *paths: str, **overrides: object) -> Interpretation:
    witnesses = tuple(Witness(path=path, shows=f"the bytes at {path}") for path in paths)
    return build_interpretation(**{**_row(), "witnesses": witnesses, **overrides}, repo_root=root)


def test_a_committed_unmodified_witness_loads(scratch_repo: Path) -> None:
    """The positive control every negative below is measured against."""

    row = _scratch_row(scratch_repo, "evidence/README.md")
    assert row.witnesses[0].path == "evidence/README.md"


def test_a_file_that_exists_but_git_never_tracked_refuses(scratch_repo: Path) -> None:
    """`Path.is_file()` says yes to this. That is exactly the gap."""

    (scratch_repo / "evidence" / "untracked.txt").write_text("never added, never committed\n")
    assert (scratch_repo / "evidence" / "untracked.txt").is_file()
    with pytest.raises(HandValidatedRegistryError, match="not a committed file"):
        _scratch_row(scratch_repo, "evidence/untracked.txt")


def test_a_case_misspelled_witness_path_refuses(scratch_repo: Path) -> None:
    """git committed ``README.md``; this row spells it ``readme.md``.

    On a case-insensitive volume (APFS, NTFS) the misspelling resolves to the
    real file and every filesystem check passes, so the citation reads as
    verified while naming a path the repository does not contain. The index
    stores one spelling, and that is the one a witness must use.
    """

    with pytest.raises(HandValidatedRegistryError, match="not a committed file"):
        _scratch_row(scratch_repo, "evidence/readme.md")


def test_a_tracked_witness_with_locally_modified_bytes_refuses(scratch_repo: Path) -> None:
    """What a future reviewer would open is no longer what the row cites."""

    (scratch_repo / "evidence" / "README.md").write_text("edited after it was read\n")
    with pytest.raises(HandValidatedRegistryError, match="differ from HEAD"):
        _scratch_row(scratch_repo, "evidence/README.md")


def test_a_tracked_witness_with_staged_modifications_also_refuses(scratch_repo: Path) -> None:
    """Staging is not committing: HEAD is still the only thing that counts."""

    (scratch_repo / "evidence" / "README.md").write_text("edited, then staged\n")
    _run_git(scratch_repo, "add", "evidence/README.md")
    with pytest.raises(HandValidatedRegistryError, match="differ from HEAD"):
        _scratch_row(scratch_repo, "evidence/README.md")


def test_a_tracked_symlink_pointing_out_of_the_repository_refuses(scratch_repo: Path) -> None:
    """Tracked, unmodified, and still not evidence this repository carries."""

    outside = scratch_repo.parent / "outside.txt"
    outside.write_text("bytes nobody committed here\n")
    (scratch_repo / "evidence" / "escape.txt").symlink_to("../../outside.txt")
    _run_git(scratch_repo, "add", "-A")
    _run_git(scratch_repo, "commit", "-q", "-m", "a symlink out of the tree")
    assert (scratch_repo / "evidence" / "escape.txt").is_file()  # is_file() follows it
    with pytest.raises(HandValidatedRegistryError, match="resolves outside the repository root"):
        _scratch_row(scratch_repo, "evidence/escape.txt")


def test_a_repo_root_that_is_not_a_git_work_tree_refuses(tmp_path: Path) -> None:
    """The public ``repo_root`` argument used to accept any directory.

    A shape-legal relative path plus an arbitrary root is a validated witness
    for whatever that root happens to contain -- the review's own example was
    ``etc/passwd`` with ``repo_root=/``. The root must now BE a git work
    tree's top level, which no such directory is.
    """

    (tmp_path / "etc").mkdir()
    (tmp_path / "etc" / "passwd").write_text("root:x:0:0:\n")
    with pytest.raises(HandValidatedRegistryError, match="git refused|top level|not a directory"):
        _scratch_row(tmp_path, "etc/passwd")


def test_a_repo_root_below_the_work_tree_top_level_refuses(scratch_repo: Path) -> None:
    """A root one directory off would check every witness against the wrong prefix."""

    with pytest.raises(HandValidatedRegistryError, match="top level"):
        _scratch_row(scratch_repo / "evidence", "README.md")


def test_two_spellings_of_one_file_do_not_satisfy_the_two_witness_floor(scratch_repo: Path) -> None:
    """Distinct paths are not enough; the resolved paths must differ too."""

    (scratch_repo / "evidence" / "alias.md").symlink_to("README.md")
    _run_git(scratch_repo, "add", "-A")
    _run_git(scratch_repo, "commit", "-q", "-m", "an in-tree alias")
    with pytest.raises(HandValidatedRegistryError, match="cites one file under two spellings"):
        _scratch_row(
            scratch_repo,
            "evidence/README.md",
            "evidence/alias.md",
            disposition="correction",
            interpreted_value="the-real-value",
        )


# --- disposition typing --------------------------------------------------


def test_every_disposition_needs_at_least_one_witness() -> None:
    assert set(MINIMUM_WITNESSES) == DISPOSITIONS
    assert all(minimum >= 1 for minimum in MINIMUM_WITNESSES.values())


def test_correction_needs_strictly_more_witnesses_than_any_other_disposition() -> None:
    assert MINIMUM_WITNESSES["correction"] > MINIMUM_WITNESSES["flag"]
    assert MINIMUM_WITNESSES["correction"] > MINIMUM_WITNESSES["refusal-to-interpret"]
    assert MINIMUM_WITNESSES["correction"] > MINIMUM_WITNESSES["consulted"]


def test_the_witness_floors_cannot_be_moved_at_runtime() -> None:
    """A floor a caller could lower would make every negative fixture vacuous."""

    with pytest.raises(TypeError):
        MINIMUM_WITNESSES["correction"] = 1  # type: ignore[index]
    with pytest.raises(TypeError):
        del MINIMUM_WITNESSES["correction"]  # type: ignore[attr-defined]
    assert MINIMUM_WITNESSES["correction"] == 2


def test_a_correction_below_the_witness_floor_refuses_to_load() -> None:
    with pytest.raises(HandValidatedRegistryError, match="needs at least"):
        Interpretation(
            **{
                **_row(),
                "disposition": "correction",
                "interpreted_value": "the-real-value",
                "witnesses": _ONE_WITNESS,
            }
        )


def test_a_correction_at_the_witness_floor_loads() -> None:
    row = Interpretation(
        **{
            **_row(),
            "disposition": "correction",
            "interpreted_value": "the-real-value",
            "witnesses": _TWO_WITNESSES,
        }
    )
    assert row.interpreted_value == "the-real-value"


def test_one_witness_cited_twice_never_satisfies_the_two_witness_floor() -> None:
    """(w, w) has length 2 and is one reading. The floor counts evidence."""

    doubled = (_ONE_WITNESS[0], _ONE_WITNESS[0])
    with pytest.raises(HandValidatedRegistryError, match="names the same witness path more than once"):
        Interpretation(
            **{
                **_row(),
                "disposition": "correction",
                "interpreted_value": "the-real-value",
                "witnesses": doubled,
            }
        )
    # ... and the same two spellings, differing, are accepted. Both directions.
    assert len(
        Interpretation(
            **{
                **_row(),
                "disposition": "correction",
                "interpreted_value": "the-real-value",
                "witnesses": _TWO_WITNESSES,
            }
        ).witnesses
    ) == 2


def test_a_correction_without_an_interpreted_value_refuses_to_load() -> None:
    with pytest.raises(HandValidatedRegistryError, match="must assert interpreted_value"):
        Interpretation(
            **{
                **_row(),
                "disposition": "correction",
                "interpreted_value": None,
                "witnesses": _TWO_WITNESSES,
            }
        )


@pytest.mark.parametrize("disposition", ["flag", "refusal-to-interpret", "consulted"])
def test_a_flag_or_refusal_asserting_an_interpreted_value_refuses_to_load(disposition: str) -> None:
    with pytest.raises(HandValidatedRegistryError, match="must not assert interpreted_value"):
        Interpretation(**{**_row(), "disposition": disposition, "interpreted_value": "a-sneaky-correction"})


# --- the register never mutates what it hands back ------------------------


def test_an_interpretation_is_frozen() -> None:
    row = Interpretation(**_row())
    with pytest.raises(dataclasses.FrozenInstanceError):
        row.interpreted_value = "mutated"  # type: ignore[misc]


def test_a_witness_is_frozen() -> None:
    with pytest.raises(dataclasses.FrozenInstanceError):
        _ONE_WITNESS[0].shows = "mutated"  # type: ignore[misc]


def test_a_row_owns_its_witnesses_rather_than_sharing_the_callers_container() -> None:
    """Frozen shallowly is frozen in name only.

    A caller that keeps a handle on the list it passed can empty a row that
    has already cleared the witness floor -- the row would then be a
    correction with zero witnesses, which no negative fixture can catch
    because the fixture ran before the mutation.
    """

    mutable = [*_TWO_WITNESSES]
    row = Interpretation(
        **{
            **_row(),
            "disposition": "correction",
            "interpreted_value": "the-real-value",
            "witnesses": mutable,  # type: ignore[dict-item]
        }
    )
    mutable.clear()
    assert isinstance(row.witnesses, tuple)
    assert len(row.witnesses) == 2
    assert row.witnesses[0].path.endswith("README.md")


def test_a_witness_list_element_that_is_not_a_witness_refuses() -> None:
    with pytest.raises(HandValidatedRegistryError, match="not a Witness"):
        Interpretation(
            **{
                **_row(),
                "witnesses": ["research/evidence/hand-attestations-2026-08-31/README.md"],  # type: ignore[dict-item]
            }
        )


def test_witnesses_must_be_iterable_at_all() -> None:
    with pytest.raises(HandValidatedRegistryError, match="iterable of Witness"):
        Interpretation(**{**_row(), "witnesses": 3})  # type: ignore[dict-item]


# --- the explicit unknown-value contract -----------------------------------


def test_an_unreviewed_value_raises_not_reviewed_rather_than_returning_none() -> None:
    with pytest.raises(NotReviewed):
        lookup("no-row-has-ever-claimed-this-exact-string-2026-08-31")


# --- one value, one reading -------------------------------------------------


@pytest.fixture
def restored_table_caches():
    """Swap ``_TABLE`` safely: the load caches must be cold on both sides."""

    module.load_interpretations.cache_clear()
    module._by_source_value.cache_clear()
    yield
    module.load_interpretations.cache_clear()
    module._by_source_value.cache_clear()


def test_two_rows_claiming_one_source_value_refuse_to_load(
    monkeypatch: pytest.MonkeyPatch, restored_table_caches: None
) -> None:
    """Returning the first match silently would hide the second row's review.

    A reviewer could add a contradicting reading of a value already in the
    table, watch the suite pass, and never learn that nothing consults it.
    """

    shadow = Interpretation(
        **{
            **_row(),
            "source_value": "E5-2394",
            "context": "a second, contradicting reading of a value the table already carries",
        }
    )
    monkeypatch.setattr(module, "_TABLE", (*module._TABLE, shadow))
    with pytest.raises(HandValidatedRegistryError, match="two rows claim source_value 'E5-2394'") as raised:
        load_interpretations()
    # Both rows are named, so a reviewer can see which two collided.
    assert "correction" in str(raised.value)
    assert "a second, contradicting reading" in str(raised.value)


# --- the real table ---------------------------------------------------------


def test_the_real_table_loads_and_every_witness_resolves() -> None:
    rows = load_interpretations()
    assert len(rows) >= 2
    for row in rows:
        assert len(row.witnesses) >= MINIMUM_WITNESSES[row.disposition]


def test_the_real_collision_table_has_seven_rows_and_every_witness_resolves() -> None:
    """REF-066's own table, deliberately not part of :func:`load_interpretations`."""

    assert len(module._FR_COLLISION_TABLE) == 7
    for source_value in module._federal_register_collision_population():
        row = module._federal_register_collision_row(source_value)
        assert len(row.witnesses) >= MINIMUM_WITNESSES[row.disposition]


def test_the_founding_row_is_the_pilot_attestation() -> None:
    row = lookup("E5-2394")
    assert row.disposition == "correction"
    assert row.interpreted_value == "E5-2394Filed"
    assert len(row.witnesses) == 7
    shown = " ".join(witness.shows for witness in row.witnesses)
    assert "E5-2394Filed" in shown
    assert "404" in shown


def test_the_eo_8284_row_is_a_flag_not_a_correction() -> None:
    row = lookup("8284")
    assert row.disposition == "flag"
    assert row.interpreted_value is None
    assert "8248" in row.notes
    assert "Wikipedia" in row.notes


def test_the_eo_8284_row_claims_only_what_its_witnesses_establish() -> None:
    """The prose is the claim, so the prose is what a test has to hold.

    Two drafts of this row overclaimed in opposite directions. The first said
    the number "never existed because someone transposed two digits". The
    second rested its doubt on NARA's per-order route serving a 404, which is
    a fact about that route: the same publisher's 1939 disposition table
    publishes EO 8284, and this repository's own committed adjudication
    recorded its title and date all along. What survives is narrower and
    better witnessed -- the order exists, three rows cite it, and the citation
    is doubted on RELEVANCE by an adjudication that read the rule's other
    authorities. The 8248 reading stays a hypothesis.
    """

    row = lookup("8284")
    summaries = " ".join(witness.shows for witness in row.witnesses)
    # The witness summaries state observations, never either overclaim.
    assert "not_found" in summaries
    assert "never existed" not in summaries
    assert "no real order" not in summaries
    # The resolution, stated positively, with the citation that carries it.
    assert "EO 8284 EXISTS" in row.notes
    assert "4 FR 4603" in row.notes
    # The non-claim is still named explicitly, so a later edit that starts
    # asserting it has to delete a sentence rather than merely add one.
    assert "Not that 8284 denotes 8248" in row.notes
    assert "hypothesis" in row.notes
    # ... and the row says outright that its own founding argument was wrong,
    # rather than quietly dropping it.
    assert "WHAT AN EARLIER DRAFT OF THIS ROW GOT WRONG" in row.notes
    assert "route artifact" in row.notes


def test_lookup_returns_the_same_object_load_interpretations_holds() -> None:
    rows = load_interpretations()
    by_value = {row.source_value: row for row in rows}
    assert lookup("E5-2394") is by_value["E5-2394"]


# --- REF-066: the Federal Register document-number collision census --------

#: The seven modern-form numbers the 2026-09-02 collision census names, and
#: the disposition each was adjudicated to after reading the actual documents
#: (research/evidence/fr-collision-census-2026-09-02/specimens/). Five are
#: genuinely different documents; two are one matter published twice. This is
#: the negative fixture the module docstring's own doctrine demands: without
#: it, a future reviewer who sees "seven numbers, one census" could
#: "helpfully" refuse all seven instead of the five that actually collide.
_FR_COLLISION_REFUSALS = frozenset({"2010-31094", "2010-31384", "2010-31396", "2010-31415", "2010-517"})
_FR_COLLISION_CONSULTED = frozenset({"2015-17759", "2015-25354"})


def test_the_seven_collision_numbers_split_five_refused_two_consulted() -> None:
    for source_value in _FR_COLLISION_REFUSALS:
        row = module._federal_register_collision_row(source_value)
        assert row.disposition == "refusal-to-interpret", source_value
        assert row.interpreted_value is None
        assert is_a_refused_federal_register_collision(source_value) is True

    for source_value in _FR_COLLISION_CONSULTED:
        row = module._federal_register_collision_row(source_value)
        assert row.disposition == "consulted", source_value
        assert row.interpreted_value is None
        assert is_a_refused_federal_register_collision(source_value) is False


def test_an_ordinary_document_number_is_not_a_collision() -> None:
    """The cheap, common case: not one of the seven, never touches a witness."""

    assert is_a_refused_federal_register_collision("2024-00366") is False


def test_the_2010_517_row_names_what_makes_it_the_hard_one() -> None:
    """The specimen that could be mistaken for a self-correction at a glance."""

    row = module._federal_register_collision_row("2010-517")
    assert row.disposition == "refusal-to-interpret"
    summaries = " ".join(witness.shows for witness in row.witnesses)
    assert "E8-11863" in summaries
    assert "E8-11863" in row.notes
    assert "different department" in row.notes


def test_the_two_consulted_rows_name_their_own_document_number_in_the_correction() -> None:
    """What separates a `consulted` row from the five refusals: self-reference."""

    for source_value in _FR_COLLISION_CONSULTED:
        row = module._federal_register_collision_row(source_value)
        summaries = " ".join(witness.shows for witness in row.witnesses)
        assert f"document {source_value}" in summaries
        assert "CORRECT reading" in row.notes


def test_refused_federal_register_document_numbers_is_exactly_the_five() -> None:
    assert refused_federal_register_document_numbers() == _FR_COLLISION_REFUSALS
    assert refused_federal_register_document_numbers().isdisjoint(_FR_COLLISION_CONSULTED)


def test_the_rows_that_ship_and_the_pinned_census_name_the_same_seven() -> None:
    """The embedded verdicts cannot drift from the receipt they came from.

    The rows travel inside the wheel and answer there alone (REF-066, and
    `_repository_root_if_present`), so this is the check that keeps them
    honest: the seven `source_value` literals, the census's own measured
    population, and the two hand-written halves below are compared against
    each other here, in a checkout, where all three exist. It runs whether
    or not any consumer ever asks about a member -- which is more than
    `_the_census_agrees_with_this_table` can promise at runtime.

    What this cannot see: a collision the census's crawl never observed. It
    would be absent from all three sets and agree with itself.
    """

    seven = _FR_COLLISION_REFUSALS | _FR_COLLISION_CONSULTED
    assert module._federal_register_collision_population() == seven
    assert frozenset(module._fr_collision_rows_by_source_value()) == seven
    module._the_census_agrees_with_this_table()


def test_lookup_returns_the_collision_rows_in_both_dispositions() -> None:
    """A `consulted` row must be readable as "examined", never as "nobody looked".

    The audit's own words for the defect this replaces: `lookup` raised
    `NotReviewed` for `2015-17759`, contradicting that exception's
    documented meaning and defeating the point of the disposition. Both
    halves are asserted, so a fix that made every collision number look
    refused would fail here too.

    What this cannot see: whether a caller ACTS on the row it gets back --
    the boundary group below is what pins "consulted, never applied".
    """

    for source_value in sorted(_FR_COLLISION_CONSULTED):
        row = lookup(source_value)
        assert row.disposition == "consulted", source_value
        assert row is module._federal_register_collision_row(source_value)
    for source_value in sorted(_FR_COLLISION_REFUSALS):
        assert lookup(source_value).disposition == "refusal-to-interpret", source_value
    with pytest.raises(NotReviewed):
        lookup("2024-00366")


def test_the_collision_rows_never_shadow_the_founding_table() -> None:
    """The FR collision rows and `_TABLE`'s own rows share no source_value."""

    assert {row.source_value for row in module._FR_COLLISION_TABLE}.isdisjoint(
        row.source_value for row in module._TABLE
    )
    # And the founding table is completely unaffected by the collision table
    # existing at all -- E5-2394 and 8284 still resolve through the ordinary,
    # shared lookup() path, independent of the census evidence's own state.
    assert lookup("E5-2394").disposition == "correction"
    assert lookup("8284").disposition == "flag"


# --- REF-066, in isolation: the derivation logic without the real evidence --
#
# The tests above exercise the real table and the real, committed evidence
# home. This group proves the AGGREGATION rule itself -- the rows decide
# membership and disposition decides the outcome, the pinned census must
# agree with them in both directions, a `flag` or `correction` disposition
# on one of them is a data-integrity problem worth raising on, and a
# dangling witness refuses through the public predicate -- using synthetic
# rows so it needs no new commit to run, and a synthetic census so it never
# touches the real, seven-member one either.


@pytest.fixture
def restored_collision_caches():
    """Swap the FR collision table and clear every cache it feeds."""

    module._fr_collision_rows_by_source_value.cache_clear()
    module._federal_register_collision_row.cache_clear()
    module._the_census_agrees_with_this_table.cache_clear()
    module.refused_federal_register_document_numbers.cache_clear()
    yield
    module._fr_collision_rows_by_source_value.cache_clear()
    module._federal_register_collision_row.cache_clear()
    module._the_census_agrees_with_this_table.cache_clear()
    module.refused_federal_register_document_numbers.cache_clear()


def _synthetic_row(source_value: str, disposition: str, **overrides: object) -> Interpretation:
    return Interpretation(**{**_row(), "source_value": source_value, "disposition": disposition, **overrides})


def test_refused_numbers_derives_from_population_and_disposition_together(
    monkeypatch: pytest.MonkeyPatch, restored_collision_caches: None
) -> None:
    synthetic = (
        _synthetic_row("collision-refuse", "refusal-to-interpret"),
        _synthetic_row("collision-mint", "consulted"),
    )
    monkeypatch.setattr(module, "_FR_COLLISION_TABLE", synthetic)
    monkeypatch.setattr(
        module, "_federal_register_collision_population", lambda *_: frozenset({"collision-refuse", "collision-mint"})
    )
    assert module.refused_federal_register_document_numbers() == frozenset({"collision-refuse"})
    assert is_a_refused_federal_register_collision("collision-refuse") is True
    assert is_a_refused_federal_register_collision("collision-mint") is False
    # A value that is not in the (synthetic) table never resolves a row.
    assert is_a_refused_federal_register_collision("2024-00366") is False


def test_a_census_member_no_row_adjudicates_is_caught_as_drift(
    monkeypatch: pytest.MonkeyPatch, restored_collision_caches: None
) -> None:
    """An eighth collision a re-crawl finds, but nobody has adjudicated yet.

    The rows are the population a consumer carries and the census is what
    holds them true, so this is a disagreement between the two, raised in
    both directions the first time any ADJUDICATED member is asked about --
    not on the unadjudicated value itself, which no row and therefore no
    consumer can distinguish from an ordinary number.

    What this cannot see: the same drift in an installed layout. There is
    no census there to disagree with the rows, so an eighth collision would
    mint as first-class until a new census and its rows ship together --
    stated in `_the_census_agrees_with_this_table` and in REF-066.
    """

    monkeypatch.setattr(module, "_FR_COLLISION_TABLE", (_synthetic_row("collision-refuse", "refusal-to-interpret"),))
    monkeypatch.setattr(
        module, "_federal_register_collision_population", lambda *_: frozenset({"collision-refuse", "never-reviewed"})
    )
    with pytest.raises(HandValidatedRegistryError, match="never adjudicated \\['never-reviewed'\\]"):
        is_a_refused_federal_register_collision("collision-refuse")


def test_a_row_the_census_never_measured_is_caught_as_drift(
    monkeypatch: pytest.MonkeyPatch, restored_collision_caches: None
) -> None:
    """The other direction: a row adjudicating a number the receipt does not name."""

    monkeypatch.setattr(module, "_FR_COLLISION_TABLE", (_synthetic_row("invented-collision", "refusal-to-interpret"),))
    monkeypatch.setattr(module, "_federal_register_collision_population", lambda *_: frozenset())
    with pytest.raises(HandValidatedRegistryError, match="not measured \\['invented-collision'\\]"):
        is_a_refused_federal_register_collision("invented-collision")


def test_a_collision_row_with_a_dangling_witness_refuses_through_the_predicate(
    monkeypatch: pytest.MonkeyPatch, restored_collision_caches: None
) -> None:
    """The witness check, exercised where the refusal is actually consumed.

    `build_interpretation` has its own dangling-witness fixture above, and
    an audit on 2026-09-02 showed that fixture is not enough: deleting the
    single `_witnessed(row)` call inside
    `_federal_register_collision_row` left every collision test green,
    because the others read dispositions, witness counts or anchors and
    never make a witness fail. This one does, through the public predicate,
    so the deletion is caught where it matters.

    What this cannot see: a witness that IS committed but whose `shows`
    prose describes some other file's bytes -- that is the anchor group's
    job -- and, in an installed layout, nothing at all: there are no
    witnesses to dangle there, which is why `_repository_root_if_present`
    answers None and the row is trusted as package data.
    """

    dangling = Witness(
        path="research/evidence/this-file-was-never-committed-2026-08-31.json",
        shows="nothing -- this path does not exist",
    )
    synthetic = _synthetic_row("collision-dangling", "refusal-to-interpret", witnesses=(dangling,))
    monkeypatch.setattr(module, "_FR_COLLISION_TABLE", (synthetic,))
    monkeypatch.setattr(
        module, "_federal_register_collision_population", lambda *_: frozenset({"collision-dangling"})
    )
    with pytest.raises(HandValidatedRegistryError, match="not a committed file"):
        is_a_refused_federal_register_collision("collision-dangling")


def test_the_five_still_refuse_where_there_is_no_checkout(
    monkeypatch: pytest.MonkeyPatch, restored_collision_caches: None
) -> None:
    """REF-066's verdicts are package data: they answer with no evidence tree and no git.

    The audit that forced this: from a simulated installed layout the old
    census-first predicate raised for `2024-00366`, an ordinary number, so
    a pure minting function had become repository-dependent. Here the
    checkout probe is made to answer None (what an installed wheel gets)
    AND every git call is made to explode, so any surviving reach for the
    repository fails the test rather than passing quietly.

    What this cannot see: whether a real installed layout actually fails
    the anchor probe -- that is `_repository_root_if_present`'s own
    `is_dir()`, and REF-066 records the performed simulation (the package
    copied under a site-packages-shaped directory, no .git anywhere) that
    proved it end to end.
    """

    def _no_git(*_arguments: object, **_keywords: object) -> bytes:
        raise AssertionError("no git call may be reached without a checkout")

    monkeypatch.setattr(module, "_repository_root_if_present", lambda: None)
    monkeypatch.setattr(module, "_git", _no_git)
    assert is_a_refused_federal_register_collision("2024-00366") is False
    for source_value in sorted(_FR_COLLISION_REFUSALS):
        assert is_a_refused_federal_register_collision(source_value) is True, source_value
    for source_value in sorted(_FR_COLLISION_CONSULTED):
        assert is_a_refused_federal_register_collision(source_value) is False, source_value
    assert module.refused_federal_register_document_numbers() == _FR_COLLISION_REFUSALS


@pytest.mark.parametrize("disposition", ["flag", "correction"])
def test_a_collision_population_member_with_the_wrong_disposition_raises(
    disposition: str, monkeypatch: pytest.MonkeyPatch, restored_collision_caches: None
) -> None:
    """Only `refusal-to-interpret` and `consulted` are valid answers here."""

    overrides: dict[str, object] = {}
    if disposition == "correction":
        overrides = {"witnesses": _TWO_WITNESSES, "interpreted_value": "irrelevant"}
    synthetic = _synthetic_row("collision-wrong-disposition", disposition, **overrides)
    monkeypatch.setattr(module, "_FR_COLLISION_TABLE", (synthetic,))
    monkeypatch.setattr(
        module, "_federal_register_collision_population", lambda *_: frozenset({"collision-wrong-disposition"})
    )
    with pytest.raises(HandValidatedRegistryError, match="not 'refusal-to-interpret' or 'consulted'"):
        is_a_refused_federal_register_collision("collision-wrong-disposition")


def test_a_collision_row_that_duplicates_a_founding_source_value_refuses(
    monkeypatch: pytest.MonkeyPatch, restored_collision_caches: None
) -> None:
    """The overlap check: one value cannot be adjudicated in both tables."""

    shadow = _synthetic_row("E5-2394", "refusal-to-interpret")
    monkeypatch.setattr(module, "_FR_COLLISION_TABLE", (shadow,))
    monkeypatch.setattr(module, "_federal_register_collision_population", lambda *_: frozenset({"E5-2394"}))
    with pytest.raises(HandValidatedRegistryError, match="adjudicated in both"):
        is_a_refused_federal_register_collision("E5-2394")


def test_a_drifted_collision_census_refuses_to_load(tmp_path: Path) -> None:
    """The sha256 pin, exercised directly against a mutated copy."""

    directory = tmp_path / "drifted"
    directory.mkdir()
    real = ROOT / module.FR_COLLISION_CENSUS_ARTIFACT / "fr-full-collision-census.json"
    (directory / "fr-full-collision-census.json").write_bytes(real.read_bytes() + b" ")
    with pytest.raises(HandValidatedRegistryError, match="drifted"):
        module._verify_pinned_collision_census(directory)


# --- every witness summary is anchored in that witness's own bytes ----------

#: One literal string per witness of the real table, chosen so that it is
#: present BOTH in the witness's ``shows`` text and in the witness's own
#: bytes. That pairing is the point: a summary that drifts onto what a
#: neighbouring file shows (the two error-page bodies, whose transport
#: statuses live in a saved header capture rather than in the HTML) or that
#: silently re-encodes what it quotes (the print PDF sets EN DASH U+2013, not
#: ASCII hyphen-minus) breaks here rather than reading as verified.
_ANCHORS = {
    "research/evidence/hand-attestations-2026-08-31/witnesses/"
    "govinfo-print-FR-2005-05-16-E5-2394Filed.pdf": "[FR Doc. E5–2394Filed 5–16–05; 8:45 am]",
    "research/evidence/hand-attestations-2026-08-31/witnesses/fr-api-E5-2394Filed.json": "I.D. 051005A",
    "research/evidence/hand-attestations-2026-08-31/witnesses/fr-rawtext-E5-2394Filed.txt": (
        "[FR Doc. E5-2394Filed 5-16-05; 8:45 am]"
    ),
    "research/evidence/hand-attestations-2026-08-31/witnesses/govinfo-mods-E5-2394Filed.xml": (
        "<accessId>E5-2394Filed</accessId>"
    ),
    "research/evidence/hand-attestations-2026-08-31/witnesses/fr-api-E5-2394-404.html": (
        "<title>404 Not Found</title>"
    ),
    "research/evidence/hand-attestations-2026-08-31/witnesses/hdr-fr-api-E5-2394.txt": "HTTP/2 404",
    "research/evidence/hand-attestations-2026-08-31/witnesses/govinfo-print-E5-2394-notfound.html": (
        "<title>Page Not Found | GovInfo</title>"
    ),
    "research/evidence/investigations-2026-08-24/inv-eo/nara/orders/eo-08284.html": (
        "<title>Page Not Found | National Archives</title>"
    ),
    "research/evidence/silent-misreads-2026-08-24/adjudication/B_2.tsv": (
        "8284 exists and is real"
    ),
    "research/evidence/silent-misreads-2026-08-22.md": (
        '"Prescribing the Duties of the Librarian Emeritus", which confers no fee'
    ),
    "research/evidence/investigations-2026-08-24/inv-eo/derived/cited-eo-census.csv": (
        "8284,3,3,201404,201504,"
    ),
    "research/evidence/investigations-2026-08-24/inv-eo/derived/nara-order-details.csv": "4 FR 3864",
}


def _witness_text(path: Path) -> str:
    """The witness's own content, as text a quoted anchor can be looked for in.

    A PDF stores typography, not text, so its anchor is checked against the
    embedded text layer -- which is where the en dash the print page sets
    survives, and where an ASCII hyphen-minus would not be found.
    """

    if path.suffix == ".pdf":
        reader = pypdf.PdfReader(str(path))
        return "".join(page.extract_text() or "" for page in reader.pages)
    return path.read_text(encoding="utf-8", errors="replace")


def test_every_witness_of_the_real_table_has_an_anchor() -> None:
    """A new witness cannot skip the check below by simply not being listed."""

    cited = {witness.path for row in load_interpretations() for witness in row.witnesses}
    assert cited == set(_ANCHORS)


@pytest.mark.parametrize(("path", "anchor"), sorted(_ANCHORS.items()))
def test_a_witness_summary_quotes_a_string_its_own_bytes_carry(path: str, anchor: str) -> None:
    witnesses = {w.path: w for row in load_interpretations() for w in row.witnesses}
    shows = witnesses[path].shows
    assert anchor in shows, f"{path}: the anchor is no longer quoted in the summary"
    assert anchor in _witness_text(ROOT / path), f"{path}: the summary quotes a string these bytes lack"


# --- the same anchor discipline, over REF-066's own (separate) table -------
#
# `_FR_COLLISION_TABLE` is deliberately not part of `load_interpretations()`
# (see its own module comment), so the two groups above never see its
# fourteen witnesses. This group repeats the identical check against it
# directly, chosen the same way: a literal string present in both the
# `shows` prose and the specimen's own raw bytes -- verified by opening each
# specimen fetched from federalregister.gov and reading the text AROUND the
# docket, agency or correction sentence quoted.
_FR_COLLISION_ANCHORS = {
    "research/evidence/fr-collision-census-2026-09-02/specimens/2010-31094__2010-01-06.html": (
        "EPA-HQ-OPP-2009-0879; FRL-8806-4]"
    ),
    "research/evidence/fr-collision-census-2026-09-02/specimens/2010-31094__2010-12-10.html": (
        "FAA-2010-0997; Notice No. 10-14]"
    ),
    "research/evidence/fr-collision-census-2026-09-02/specimens/2010-31384__2010-01-06.html": (
        "National Telecommunications and Information Administration"
    ),
    "research/evidence/fr-collision-census-2026-09-02/specimens/2010-31384__2010-12-16.html": (
        "FAA-2009-0430; Directorate Identifier 2008-NM-148-AD; Amendment 39-16540; AD 2010-26-01]"
    ),
    "research/evidence/fr-collision-census-2026-09-02/specimens/2010-31396__2010-01-06.html": (
        "EPA-HQ-OPP-2009-0977; FRL-8806-2]"
    ),
    "research/evidence/fr-collision-census-2026-09-02/specimens/2010-31396__2010-12-15.html": "MARAD 2010 0109",
    "research/evidence/fr-collision-census-2026-09-02/specimens/2010-31415__2010-01-06.html": (
        "CP2010-19; Order No. 374]"
    ),
    "research/evidence/fr-collision-census-2026-09-02/specimens/2010-31415__2010-12-15.html": (
        "Hydro Friends Fund XLVII, FFP Missouri 16, LLC"
    ),
    "research/evidence/fr-collision-census-2026-09-02/specimens/2010-517__2010-01-14.html": (
        "CenterPoint Energy Gas Transmission Company (CEGT)"
    ),
    "research/evidence/fr-collision-census-2026-09-02/specimens/2010-517__2010-01-28.html": (
        "Rule document E8-11863 was inadvertently published in the Proposed Rules section of the issue of "
        "May 28, 2008, beginning on page 30560. It should have appeared in the Rules and Regulations section."
    ),
    "research/evidence/fr-collision-census-2026-09-02/specimens/2015-17759__2015-07-21.html": "SR-NYSEMKT-2015-48",
    "research/evidence/fr-collision-census-2026-09-02/specimens/2015-17759__2015-08-05.html": (
        "In notice document 2015-17759, appearing on pages 43141 through 43143 in the issue of Tuesday, "
        "July 21, 2015, make the following correction"
    ),
    "research/evidence/fr-collision-census-2026-09-02/specimens/2015-25354__2015-10-06.html": "ED-2015-ICCD-0118",
    "research/evidence/fr-collision-census-2026-09-02/specimens/2015-25354__2015-10-13.html": (
        "In notice document 2015-25354, appearing on pages 60358-60369 in the Issue of Tuesday, "
        "October 6, 2015, make the following correction"
    ),
}


def test_every_witness_of_the_real_collision_table_has_an_anchor() -> None:
    cited = {witness.path for row in module._FR_COLLISION_TABLE for witness in row.witnesses}
    assert cited == set(_FR_COLLISION_ANCHORS)


@pytest.mark.parametrize(("path", "anchor"), sorted(_FR_COLLISION_ANCHORS.items()))
def test_a_collision_witness_summary_quotes_a_string_its_own_bytes_carry(path: str, anchor: str) -> None:
    witnesses = {w.path: w for row in module._FR_COLLISION_TABLE for w in row.witnesses}
    shows = witnesses[path].shows
    assert anchor in shows, f"{path}: the anchor is no longer quoted in the summary"
    assert anchor in _witness_text(ROOT / path), f"{path}: the summary quotes a string these bytes lack"


# --- the boundary: consulted, never applied ---------------------------------


def test_lookup_hands_back_the_frozen_row_not_a_value() -> None:
    row = lookup("E5-2394")
    assert isinstance(row, Interpretation)
    assert typing.get_type_hints(lookup)["return"] is Interpretation
    with pytest.raises(dataclasses.FrozenInstanceError):
        row.interpreted_value = "applied"  # type: ignore[misc]


def test_no_public_function_hands_back_a_bare_interpreted_value() -> None:
    """The one shape that would turn consultation into application.

    ``lookup`` returns the interpretation ALONGSIDE its provenance, so a
    caller writing a correction into a record has to have opened a row that
    says it is a correction. A helper returning ``str`` would let the same
    caller skip that, and it would be one line to add -- so the absence of
    one is pinned rather than assumed.
    """

    public = {
        name: value
        for name, value in vars(module).items()
        if not name.startswith("_") and inspect.isfunction(value) and value.__module__ == module.__name__
    }
    assert set(public) <= set(module.__all__), "a public function escaped the declared surface"
    for name, function in public.items():
        returns = typing.get_type_hints(function).get("return")
        assert returns not in (str, str | None), f"{name} returns a bare value a caller could apply"


def test_the_eo_roster_is_a_real_consulting_consumer() -> None:
    """Not documentation-only: a shipped module delegates to this table.

    ``EoRosterOracle.flag_for`` returns the very object this table holds,
    beside its own verdict rather than instead of it. Skipped rather than
    hard-imported so a sibling lane's breakage cannot masquerade as this
    one's; ``tests/test_eo_roster.py`` asserts the same delegation from the
    consumer's side.
    """

    eo_roster = pytest.importorskip("refspec.registry.eo_roster")
    assert eo_roster.EoRosterOracle.flag_for(8284) is lookup("8284")
    assert eo_roster.EoRosterOracle.flag_for(8248) is None
