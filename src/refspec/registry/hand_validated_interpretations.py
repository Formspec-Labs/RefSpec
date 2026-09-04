"""A small table of hand-validated interpretations, consulted, never applied.

Some source values are malformed in a way no grammar should generalise from:
a document number with a word fused onto it because one printer's composition
run dropped a space; an Executive Order number that three corpus rows cite as
complete and in-series, which is a real order that has nothing to do with the
authority the citing rule needed. A person (or an agent, acting for one) can
look at the raw
bytes, work out what the bytes do and do not establish, and be right -- but
that judgment is only worth having if it arrives with the same receipt
discipline as everything else this platform mints: named witnesses, pointing
at committed bytes, that a future reviewer can re-open and check.

That is what this module is. It is not a grammar, not a normaliser, and not
an importer of ``research/evidence/hand-attestations-2026-08-31/`` (that
evidence home is deliberately un-versioned prose plus JSON, kept exactly as
written; this module's :data:`_TABLE` restates its founding row in a typed
shape, the way :mod:`refspec.registry.usc_section_oracle` restates the dash
table it does not import). Structure earns its keep here by having exactly
one behaviour a test can break: no accessor -- :func:`lookup` for either
table, :func:`is_a_refused_federal_register_collision` for
:data:`_FR_COLLISION_TABLE` (REF-066, below) -- may ever hand back a
correction, a flag, a refusal or a consulted row that is not backed by at
least one witness pointing at bytes this repository has actually committed.
Read that sentence with the deployment scope below: the check is against
the checkout this file lives in, so it is the checkout, and every CI run,
that holds a row to its witnesses. An installed wheel carries the rows and
no evidence tree, and REF-066's refusal set -- and only that -- is designed
to keep working there.

Disposition typing
-------------------
Four dispositions, and they mean different things:

* **correction** -- asserts a replacement (:attr:`Interpretation.interpreted_value`
  is set) and requires at least :data:`MINIMUM_WITNESSES_FOR_CORRECTION`
  independent witnesses, because asserting that two spellings name the same
  thing is the strongest claim this table makes. Independence is enforced at
  the floor a table can enforce it: two witnesses must be two distinct files
  (distinct spellings AND distinct resolved paths), so one file cited twice
  can never satisfy a floor of two. Independence of *origin* -- the founding
  row's own warning that a print page, a granule id and an API record can be
  one defect inherited twice -- is a judgment the row's prose must state; no
  type can check it.
* **flag** -- doubts the publisher's own value without asserting what it
  should have been. ``interpreted_value`` stays ``None``: a flag that quietly
  carried a replacement value would be a correction wearing a lighter label.
* **refusal-to-interpret** -- a value was looked at and deliberately left
  unresolved; the witnesses record why, not what. Unlike a flag, this is not
  doubt about the publisher's spelling -- the value is spelled exactly as
  published -- it is a refusal to let that value settle into ONE identity,
  because the evidence shows it would have to stand for more than one thing.
* **consulted** -- a value was examined and a candidate correction or refusal
  was deliberately NOT applied, because the evidence showed the value was
  already right. ``interpreted_value`` stays ``None``, the same as a flag: a
  consulted row is not a correction wearing a lighter label either. It exists
  so "we looked at this and it was fine" is a recorded fact rather than a
  silence a later reviewer cannot tell apart from "nobody looked".

Every disposition needs at least one witness (:data:`MINIMUM_WITNESSES`); a
row with none refuses to load, and so does a row whose witness fails the
committed-bytes check below (:func:`build_interpretation`).

What "a committed file" means here
-----------------------------------
The check is against **git**, not against the filesystem, because
``Path.is_file()`` answers a weaker question than this table needs. On a
case-insensitive volume (APFS, NTFS) it says yes to ``readme.md`` when the
repository committed ``README.md``; it says yes to a file nobody ever added;
it says yes to a tracked file whose working bytes a reviewer edited after
reading them; and it follows symlinks out of the tree. Each of those is a
witness that a future reviewer cannot re-open and see what this row's author
saw. So a witness path must, all four:

1. appear in ``git ls-files`` **byte-exactly** -- membership and spelling in
   one check, since the index stores the one spelling that was committed;
2. be absent from ``git diff --name-only HEAD`` -- working bytes equal to
   HEAD, so what the row cites is what the repository carries;
3. resolve (through every symlink, via ``os.path.realpath``) to a path still
   strictly inside the repository root; and
4. be a regular file at that resolved path.

Both git calls are made once per root and cached; this is repo tooling and
the cost is two subprocesses per process, ~25ms on this repository.

Deployment scope (adjudicated 2026-08-31, split 2026-09-02)
-----------------------------------------------------------
**The founding table is repository tooling, and says so rather than
pretending otherwise.** Its default root is
``Path(__file__).resolve().parents[3]``, which is the checkout when this
file is imported from ``src/`` and is somewhere useless
(``site-packages/``) when it is imported from an installed wheel. Rather
than let that fail obscurely -- every witness "missing", the table refusing
to load with a filesystem error -- the default root is verified once to
*look like this repository* (it must carry :data:`_REPOSITORY_ANCHOR` and
be the top level of a git work tree) and :func:`_default_repository_root`
raises :class:`HandValidatedRegistryError` naming the deployment problem if
it does not. A caller with its own checkout passes ``repo_root=``
explicitly; that root is held to the same git-work-tree rule, so passing
``/`` (or any directory that merely happens to contain a matching relative
path) refuses instead of validating ``/etc/passwd``.

**REF-066's collision refusal is not, because it cannot be.** An adversarial
audit on 2026-09-02 simulated an installed layout and found
``mint_federal_register_document_iri("2024-00366")`` -- an ordinary,
non-colliding number nobody has ever reviewed -- raising, because the
predicate read the census receipt out of the evidence tree before doing
anything else. That is this repository's own catalogued defect shape:
runtime behaviour bound to a REPRESENTATION (a git checkout) rather than to
the fact it encodes. So the two are separated by what they are:

* the **verdicts** -- seven ``source_value`` strings and their dispositions
  -- are BEHAVIOURAL, tiny, and already Python literals in
  :data:`_FR_COLLISION_TABLE`, so they travel inside the wheel and answer
  in any layout with no census, no git and no filesystem;
* the **census receipt** and the **fourteen witness files** are AUDIT data.
  They live only in a checkout, they are checked there exactly as before
  (:func:`_the_census_agrees_with_this_table` holds the rows true against
  the receipt in both directions; :func:`_witnessed` holds each row to its
  own committed bytes), and neither is reachable by a value that is not one
  of the seven.

:func:`_repository_root_if_present` is the whole of that split: one
``is_dir()`` on the evidence anchor, no subprocess, answering ``None``
where :func:`_default_repository_root` would raise. The wheel therefore
carries no un-witnessed *claim* -- it carries the same seven rows CI
witnesses on every run, and a test proves the embedded seven and the pinned
census still name the same numbers.

What this module never does
----------------------------
It never overwrites source data: nothing here mutates a caller's value, and
:func:`lookup` always returns the interpretation *alongside* the value it was
asked about, never a bare replacement string that could be mistaken for the
thing itself. There is deliberately no public helper that hands back an
``interpreted_value`` on its own. And it never answers for a value nobody has
reviewed -- :func:`lookup` raises :class:`NotReviewed` rather than returning
``None``, because ``None`` cannot be told apart from a bug that forgot to
look.

Who consults it
----------------
:meth:`refspec.registry.eo_roster.EoRosterOracle.flag_for` is the first real
consumer: it delegates to :func:`lookup` for hand-reviewed doubt about an
Executive Order number rather than keeping a second copy of the same claim,
and surfaces the returned :class:`Interpretation` *alongside* its own
verdict, never instead of it. That is the shape "consulted, never applied"
was meant to have, and it is what the boundary tests in
``tests/test_hand_validated_interpretations.py`` pin from this side.

:func:`refspec.registry.iri_minting.mint_federal_register_document_iri` is
the second: it consults :func:`is_a_refused_federal_register_collision`
before minting ``rkaf:us-frdoc`` at all, and refuses (returns ``None``) for
every value that answers ``True`` -- see the next section.

REF-052 named the doctrine this module extends: "the column is the license"
-- a value arriving from a trusted column is licensed by the field it came
from, not by a shape a grammar recognises. A row here licenses an
interpretation the same way, on different terms: not by which column the
value arrived in, but by which witnesses a reviewer actually opened.

The Federal Register collision census (REF-066)
--------------------------------------------------
rulespec's modern Federal Register space, ``rkaf:us-frdoc``, mints from the
document number alone because the modern form was assumed to identify one
document. A full crawl of the *published* (not merely the pinned-parquet)
Federal Register, brought home 2026-09-02 as
``research/evidence/fr-collision-census-2026-09-02/fr-full-collision-census.json``
and pinned by sha256 in :data:`_FR_COLLISION_CENSUS_PIN` -- the same
discipline :mod:`refspec.registry.eo_roster` applies to its own roster --
found **seven** modern-form numbers that each name two documents on two
different dates. Reading the actual documents (that evidence home's
``specimens/``, fourteen raw full-text captures) settled which of two things
each one is:

* **five genuinely different documents** (different agencies, different
  subjects, no textual relationship): minting one identifier for either
  pair would silently merge two unrelated regulatory actions. Recorded here
  as ``refusal-to-interpret`` rows.
* **two republications of one matter**, each explicitly a correction *of
  its own document number* -- "In notice document 2015-17759 ... make the
  following correction" is the document's own text, not an inference. A
  single identifier for both is the CORRECT reading, not a tolerated one.
  Recorded here as ``consulted`` rows.

The population is never a SECOND list a consumer could drift from the
rows: the seven ``source_value`` fields of :data:`_FR_COLLISION_TABLE` are
the population and the verdict at once, exactly as every row in
:data:`_TABLE` already is one literal.
:func:`is_a_refused_federal_register_collision` asks them first -- one dict
lookup, no census, no git -- so an ordinary document number is answered in
any deployment, and only a value that IS one of the seven pays for the
pinned census to be re-read and that single row's witnesses to be
re-checked. The receipt then holds the rows honest rather than defining
them (:func:`_the_census_agrees_with_this_table`); the roles were the other
way round for one day, and the deployment-scope section above records the
audit that swapped them.

That table is kept apart from :data:`_TABLE` and never loaded through
:func:`load_interpretations`, so minting an ORDINARY document number never
waits on every collision's evidence at once, and one collision's broken
witness never refuses the other six. The isolation that buys is precise,
and worth stating precisely: a witness FILE going wrong is isolated to the
row that cites it; a row SHAPE going wrong is not, because all seven rows
are constructed eagerly at import and a malformed one fails the import
itself. :func:`_federal_register_collision_row` says why that difference is
deliberate.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from functools import cache
from pathlib import Path, PurePosixPath
from types import MappingProxyType
from typing import Literal

#: A directory every checkout of THIS repository carries. The default root is
#: verified against it so an installed-wheel import fails with a sentence
#: about deployment rather than with a pile of missing witnesses.
_REPOSITORY_ANCHOR = "research/evidence/hand-attestations-2026-08-31"

_GIT_TIMEOUT_SECONDS = 60

Disposition = Literal["correction", "flag", "refusal-to-interpret", "consulted"]
DISPOSITIONS: frozenset[Disposition] = frozenset({"correction", "flag", "refusal-to-interpret", "consulted"})

#: A correction asserts that two spellings name one thing; that claim needs
#: more than a single witness. A flag, a refusal or a consulted row asserts
#: nothing beyond "this value was looked at", so one witness is the floor for
#: every row but a correction. Read-only: a floor a caller could raise or
#: lower at runtime would make "this row cleared the floor" a statement about
#: that caller, not about the table, and every negative fixture below would
#: be one assignment from passing vacuously.
MINIMUM_WITNESSES: Mapping[Disposition, int] = MappingProxyType(
    {
        "correction": 2,
        "flag": 1,
        "refusal-to-interpret": 1,
        "consulted": 1,
    }
)
MINIMUM_WITNESSES_FOR_CORRECTION = MINIMUM_WITNESSES["correction"]


class HandValidatedRegistryError(ValueError):
    """A row, or one of its witnesses, refuses to load."""


class NotReviewed(LookupError):
    """No hand-validated interpretation exists for this exact source value.

    Raised rather than returning ``None`` so "nobody has reviewed this" can
    never be mistaken for a disposition, a bug, or a falsy correction. It
    means neither table names the value: :func:`lookup` reads :data:`_TABLE`
    and REF-066's :data:`_FR_COLLISION_TABLE` alike, so a ``consulted`` row
    -- "examined, and deliberately left alone" -- can never come back as
    "nobody examined it".
    """


# --------------------------------------------------------------------------- #
# Git: what makes a witness path a committed file
# --------------------------------------------------------------------------- #


def _git(root: Path, *arguments: str) -> bytes:
    """Run one read-only git command in ``root``, turning its refusal into ours."""

    command = ["git", "-C", str(root), *arguments]
    try:
        completed = subprocess.run(command, capture_output=True, check=False, timeout=_GIT_TIMEOUT_SECONDS)
    except OSError as error:
        raise HandValidatedRegistryError(
            f"git is unavailable, so no witness can be checked against the repository: {error}"
        ) from error
    except subprocess.TimeoutExpired as error:
        raise HandValidatedRegistryError(
            f"git did not answer `{' '.join(arguments)}` under {root} within {_GIT_TIMEOUT_SECONDS}s"
        ) from error
    if completed.returncode != 0:
        detail = completed.stderr.decode("utf-8", "replace").strip() or f"exit {completed.returncode}"
        raise HandValidatedRegistryError(f"git refused `{' '.join(arguments)}` under {root}: {detail}")
    return completed.stdout


def _nul_separated(payload: bytes) -> frozenset[str]:
    return frozenset(chunk.decode("utf-8", "surrogateescape") for chunk in payload.split(b"\0") if chunk)


@cache
def _work_tree_root(root: Path) -> Path:
    """Resolve ``root`` and require that it IS a git work tree's top level.

    Not "is inside one" and not "exists": a witness path is only meaningful
    relative to the root the index spells its paths against, so a root one
    directory off would silently check every witness against the wrong
    prefix. This is also what stops ``repo_root=Path("/")`` from turning the
    shape-legal relative path ``etc/passwd`` into a validated witness.
    """

    resolved = Path(os.path.realpath(root))
    if not resolved.is_dir():
        raise HandValidatedRegistryError(f"repo_root is not a directory: {root}")
    toplevel = _git(resolved, "rev-parse", "--show-toplevel").decode("utf-8", "replace").strip()
    if not toplevel or Path(os.path.realpath(toplevel)) != resolved:
        raise HandValidatedRegistryError(
            f"repo_root must be a git work tree's own top level, not a directory inside or above one: "
            f"given {root}, git's top level there is {toplevel or '(none)'}"
        )
    return resolved


@cache
def _repository_root_if_present() -> Path | None:
    """The checkout this file lives in, or ``None`` when it does not live in one.

    The one probe here that answers rather than raises, because one caller
    -- REF-066's collision predicate -- has to work in both layouts. The
    discriminator is the evidence tree itself (:data:`_REPOSITORY_ANCHOR`,
    a single ``is_dir()``, no git, no subprocess): a source checkout
    carries it, ``site-packages/`` does not.

    Deliberately NOT a relaxation of the witness discipline. When the
    anchor IS present this returns the same verified work-tree root
    :func:`_default_repository_root` returns, so a checkout whose git is
    broken still raises here rather than quietly dropping the check --
    "the evidence is right there and I cannot verify it" is a different
    fact from "there is no evidence tree", and only the second one is a
    deployment shape rather than a fault.

    What this cannot see: an installed wheel whose ``site-packages`` parent
    happens to carry a directory of this exact name. ``_work_tree_root``
    would then have to agree that root is a git work tree's own top level,
    and every witness would fail loudly against it -- wrong, but never
    silently wrong.
    """

    root = Path(__file__).resolve().parents[3]
    if not (root / _REPOSITORY_ANCHOR).is_dir():
        return None
    return _work_tree_root(root)


@cache
def _default_repository_root() -> Path:
    """The checkout this file lives in -- verified, not assumed. See the docstring."""

    root = _repository_root_if_present()
    if root is None:
        raise HandValidatedRegistryError(
            f"this module is repository tooling: it resolves witnesses relative to the checkout it "
            f"lives in, and {Path(__file__).resolve().parents[3]} does not carry {_REPOSITORY_ANCHOR}. "
            f"Imported from an installed wheel there is no evidence tree to check witnesses against; "
            f"pass repo_root= explicitly if you have a checkout"
        )
    return root


@cache
def _tracked_paths(root: Path) -> frozenset[str]:
    """Every path git tracks under ``root``, in the exact spelling it committed."""

    return _nul_separated(_git(root, "ls-files", "-z"))


@cache
def _paths_differing_from_head(root: Path) -> frozenset[str]:
    """Every tracked path whose working bytes differ from HEAD (staged or not)."""

    return _nul_separated(_git(root, "diff", "--name-only", "-z", "HEAD", "--"))


def _check_witness(root: Path, source_value: str, witness: Witness) -> Path:
    """Confirm one witness is committed, unmodified, and inside ``root``. Returns its resolved path."""

    if witness.path not in _tracked_paths(root):
        raise HandValidatedRegistryError(
            f"{source_value!r} witness is not a committed file of this repository -- git tracks no "
            f"path spelled exactly this way: {witness.path}"
        )
    if witness.path in _paths_differing_from_head(root):
        raise HandValidatedRegistryError(
            f"{source_value!r} witness has working bytes that differ from HEAD, so what a future "
            f"reviewer would open is not what this row cites: {witness.path}"
        )
    resolved = Path(os.path.realpath(root / witness.path))
    if not resolved.is_relative_to(root):
        raise HandValidatedRegistryError(
            f"{source_value!r} witness resolves outside the repository root -- a symlink, most "
            f"likely: {witness.path} -> {resolved}"
        )
    if not resolved.is_file():
        raise HandValidatedRegistryError(
            f"{source_value!r} witness does not exist as a regular file: {witness.path}"
        )
    return resolved


# --------------------------------------------------------------------------- #
# The typed row
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class Witness:
    """One pointer at committed raw evidence, and what a reviewer read there."""

    path: str
    shows: str

    def __post_init__(self) -> None:
        if not isinstance(self.path, str) or not self.path.strip():
            raise HandValidatedRegistryError("a witness must name a path")
        posix = PurePosixPath(self.path)
        if (
            self.path.startswith("/")
            or "\\" in self.path
            or ".." in posix.parts
            or "." in posix.parts
            or self.path != posix.as_posix()
        ):
            raise HandValidatedRegistryError(f"witness path must be repo-root-relative: {self.path!r}")
        if not isinstance(self.shows, str) or not self.shows.strip():
            raise HandValidatedRegistryError(f"witness {self.path!r} must say what it shows")


@dataclass(frozen=True, slots=True)
class Interpretation:
    """One hand-validated reading of a source value, with its full provenance.

    Constructing this validates shape only (disposition typing, witness
    count, distinctness, non-empty attestation). It does not touch the
    filesystem or git -- that is :func:`build_interpretation`'s job, because
    "is this witness committed" is a loading-time question, not a shape
    question, and the two should fail for different, distinguishable reasons.

    ``witnesses`` is canonicalised to a ``tuple`` of :class:`Witness` in
    ``__post_init__``. A caller may therefore pass any iterable, and cannot
    keep a handle on it: a frozen row that shared a list with its constructor
    would be frozen in name only -- ``row.witnesses.clear()`` after
    validation would empty a row that had passed the witness floor.
    """

    source_value: str
    context: str
    disposition: Disposition
    witnesses: tuple[Witness, ...]
    reviewer: str
    reviewed_at: str
    interpreted_value: str | None = None
    notes: str = ""

    def __post_init__(self) -> None:
        if not self.source_value.strip():
            raise HandValidatedRegistryError("a row must name a source_value")
        if not self.context.strip():
            raise HandValidatedRegistryError(f"{self.source_value!r} must name a context")
        if self.disposition not in DISPOSITIONS:
            raise HandValidatedRegistryError(
                f"{self.source_value!r} has an undeclared disposition: {self.disposition!r}"
            )
        object.__setattr__(self, "witnesses", self._own_witnesses())
        if not self.witnesses:
            raise HandValidatedRegistryError(f"{self.source_value!r} has no witnesses and refuses to load")
        required = MINIMUM_WITNESSES[self.disposition]
        if len(self.witnesses) < required:
            raise HandValidatedRegistryError(
                f"{self.source_value!r} is a {self.disposition!r} row with {len(self.witnesses)} witness(es); "
                f"needs at least {required}"
            )
        if self.disposition == "correction":
            if self.interpreted_value is None or not self.interpreted_value.strip():
                raise HandValidatedRegistryError(
                    f"{self.source_value!r} is a correction and must assert interpreted_value"
                )
        elif self.interpreted_value is not None:
            raise HandValidatedRegistryError(
                f"{self.source_value!r} is a {self.disposition!r} row and must not assert interpreted_value "
                f"(got {self.interpreted_value!r}); that is what disposition='correction' is for"
            )
        if not self.reviewer.strip():
            raise HandValidatedRegistryError(f"{self.source_value!r} must name a reviewer")
        try:
            date.fromisoformat(self.reviewed_at)
        except ValueError as error:
            raise HandValidatedRegistryError(f"{self.source_value!r}.reviewed_at must be an ISO date") from error

    def _own_witnesses(self) -> tuple[Witness, ...]:
        """Copy the witnesses into a tuple this row owns, checking each one."""

        try:
            witnesses = tuple(self.witnesses)
        except TypeError as error:
            raise HandValidatedRegistryError(
                f"{self.source_value!r} witnesses must be an iterable of Witness, got "
                f"{type(self.witnesses).__name__}"
            ) from error
        for element in witnesses:
            if not isinstance(element, Witness):
                raise HandValidatedRegistryError(
                    f"{self.source_value!r} has a witness that is not a Witness: {element!r}"
                )
        spellings = [witness.path for witness in witnesses]
        repeated = sorted({path for path in spellings if spellings.count(path) > 1})
        if repeated:
            raise HandValidatedRegistryError(
                f"{self.source_value!r} names the same witness path more than once ({', '.join(repeated)}); "
                f"the witness floor counts distinct evidence, and one file cited twice is one file"
            )
        return witnesses


def build_interpretation(
    *,
    source_value: str,
    context: str,
    disposition: Disposition,
    witnesses: tuple[Witness, ...],
    reviewer: str,
    reviewed_at: str,
    interpreted_value: str | None = None,
    notes: str = "",
    repo_root: Path | None = None,
) -> Interpretation:
    """Validate one row's shape, then confirm every witness is committed bytes.

    This is the one function both :func:`load_interpretations` and a test
    call to exercise the negative fixtures: an untracked path, a
    case-misspelled path, a locally modified path and a symlink out of the
    tree all refuse here, distinctly from the shape errors
    :class:`Interpretation` raises on its own.
    """

    return _witnessed(
        Interpretation(
            source_value=source_value,
            context=context,
            disposition=disposition,
            witnesses=witnesses,
            reviewer=reviewer,
            reviewed_at=reviewed_at,
            interpreted_value=interpreted_value,
            notes=notes,
        ),
        repo_root=repo_root,
    )


def _witnessed(interpretation: Interpretation, *, repo_root: Path | None = None) -> Interpretation:
    """Check every witness of an already-shaped row. Returns the same object."""

    root = _default_repository_root() if repo_root is None else _work_tree_root(Path(repo_root))
    seen: dict[Path, str] = {}
    for witness in interpretation.witnesses:
        resolved = _check_witness(root, interpretation.source_value, witness)
        if resolved in seen:
            raise HandValidatedRegistryError(
                f"{interpretation.source_value!r} cites one file under two spellings "
                f"({seen[resolved]} and {witness.path} both resolve to {resolved}); "
                f"the witness floor counts distinct evidence"
            )
        seen[resolved] = witness.path
    return interpretation


# --------------------------------------------------------------------------- #
# The Federal Register collision census (REF-066)
# --------------------------------------------------------------------------- #

#: The sealed evidence home the census and its raw specimens were brought
#: home to, so this module never reaches outside the checkout for either --
#: see its README.md for the crawl's own scope, caveat and per-number
#: adjudication summary.
FR_COLLISION_CENSUS_ARTIFACT = "research/evidence/fr-collision-census-2026-09-02"
_FR_COLLISION_CENSUS_FILE = "fr-full-collision-census.json"
#: Pins the census exactly as :data:`refspec.registry.eo_roster._ROSTER_PIN`
#: pins that module's roster: the reader hashes the file it is about to
#: parse and refuses to load on any drift, so a re-crawl (or an edit) cannot
#: silently change which numbers this table is answering for.
_FR_COLLISION_CENSUS_PIN = "sha256:427a68272f87225e45c7bc25376c73c2761e07a613c7d87a8a6cdaa73c73356c"


def _verify_pinned_collision_census(directory: Path) -> bytes:
    """Return the pinned census's bytes, refusing loudly on drift.

    The bytes are returned rather than the path for the same reason
    :mod:`refspec.registry.eo_roster`'s equivalent does: the caller parses
    exactly what was hashed, with no window for the file to change between
    the hash and the read.
    """

    payload = (directory / _FR_COLLISION_CENSUS_FILE).read_bytes()
    digest = f"sha256:{hashlib.sha256(payload).hexdigest()}"
    if digest != _FR_COLLISION_CENSUS_PIN:
        raise HandValidatedRegistryError(
            f"pinned Federal Register collision census drifted: "
            f"expected={_FR_COLLISION_CENSUS_PIN}, observed={digest}"
        )
    return payload


@cache
def _federal_register_collision_population(repo_root: Path | None = None) -> frozenset[str]:
    """Every modern-form ``document_number`` the pinned census measures as a collision.

    Population membership only, read once from the one pinned receipt this
    module knows about -- not yet a verdict, and (since the audit named in
    :func:`_repository_root_if_present`) not the thing an ordinary mint
    waits on either. This is AUDIT data: it exists only in a checkout, and
    its job is to hold :data:`_FR_COLLISION_TABLE`'s seven rows true
    against the receipt they were derived from -- see
    :func:`_the_census_agrees_with_this_table`, the one production caller.

    A future re-crawl that finds an eighth collision ships as a NEW dated
    evidence home and a new pin, never as a silent edit to this one's
    bytes, so this function's answer changes only when the module itself
    changes.
    """

    root = _default_repository_root() if repo_root is None else _work_tree_root(Path(repo_root))
    payload = _verify_pinned_collision_census(root / FR_COLLISION_CENSUS_ARTIFACT)
    census = json.loads(payload)
    return frozenset(str(record["recordId"]) for record in census["modernFormCollisions"])


@cache
def _the_census_agrees_with_this_table() -> None:
    """Hold the seven adjudicated rows true against the pinned census -- where it exists.

    REF-066 originally made this check on every value, by reading the
    census FIRST and asking the table second. That order bound an ordinary
    mint to a git checkout (the audit in
    :func:`_repository_root_if_present`), so the roles are swapped: the
    ROWS are the population, because they travel inside the wheel, and the
    RECEIPT is what holds them honest. The comparison is the same one, in
    both directions, and it is exact -- a census member no row adjudicates
    and a row the census does not measure are equally a drift.

    Cost: one cached O(B) receipt hash and parse over the seven-member
    result, paid the first time any consumer asks about one of the seven
    and never by a value that is not one of them.

    What this cannot see: the same drift from an installed layout, where
    there is no census to disagree with the rows -- a collision an eighth
    crawl finds mints as first-class there until the new census and the
    rows that adjudicate it ship together. In a checkout it raises on the
    first ask about any of the seven, which any pass over a real Federal
    Register column reaches at once; and
    ``tests/test_hand_validated_interpretations.py`` compares the two sets
    directly, whether or not a member is ever asked about.
    """

    root = _repository_root_if_present()
    if root is None:
        return
    measured = _federal_register_collision_population(root)
    adjudicated = frozenset(_fr_collision_rows_by_source_value())
    if measured != adjudicated:
        raise HandValidatedRegistryError(
            f"the pinned Federal Register collision census and _FR_COLLISION_TABLE disagree about "
            f"which numbers collide: measured but never adjudicated {sorted(measured - adjudicated)}; "
            f"adjudicated but not measured {sorted(adjudicated - measured)}. A re-crawl ships as a "
            f"new dated evidence home, a new pin, AND the rows that adjudicate it, in one change"
        )


@cache
def _fr_collision_rows_by_source_value() -> Mapping[str, Interpretation]:
    """:data:`_FR_COLLISION_TABLE`, indexed by ``source_value``, checked for overlap.

    Two checks: :func:`_require_unique_source_values` over
    :data:`_FR_COLLISION_TABLE` alone (the same duplicate-catching rule
    :func:`load_interpretations` applies to :data:`_TABLE`), and that no
    ``source_value`` is adjudicated in BOTH tables -- overlap would mean two
    different code paths silently answering for the same value, one of them
    unreachable through :func:`lookup`. Neither check touches git: it is
    over already-constructed :class:`Interpretation` objects, so it costs
    nothing a caller has to wait on.
    """

    _require_unique_source_values(_FR_COLLISION_TABLE)
    overlap = {row.source_value for row in _FR_COLLISION_TABLE} & {row.source_value for row in _TABLE}
    if overlap:
        raise HandValidatedRegistryError(
            f"source_value(s) {sorted(overlap)} are adjudicated in both _TABLE and "
            f"_FR_COLLISION_TABLE; one value belongs in exactly one table"
        )
    return MappingProxyType({row.source_value: row for row in _FR_COLLISION_TABLE})


@cache
def _federal_register_collision_row(record_id: str) -> Interpretation:
    """The hand-validated row for one adjudicated collision number, witnessed where it can be.

    Looked up directly against :data:`_FR_COLLISION_TABLE`, NOT through
    :func:`load_interpretations` / :func:`lookup` / :func:`_by_source_value`:
    those validate :data:`_TABLE` together, on purpose, as one fixed literal
    -- exactly right for a handful of rarely-changing rows consulted by name
    (E5-2394, 8284), and the wrong property for a population consulted on
    nearly every Federal Register document number minted anywhere on the
    platform. Minting an ORDINARY, non-colliding document number must never
    depend on the witness state of an unrelated Executive Order flag, and
    must not fail for every OTHER collision merely because one collision's
    own evidence is momentarily unavailable. Each member is witnessed on its
    own, with the exact same check :func:`_witnessed` gives every row in
    :data:`_TABLE` -- just scoped to the one row a caller actually asked
    about, and cached per ``record_id`` so repeated asks about the same
    number cost one check, not seven.

    **Blast radius, in two different cases that must not be conflated.**
    A witness FILE going wrong -- deleted, edited away from HEAD, never
    committed, symlinked out of the tree -- is isolated: it raises for the
    one row that cites it and for nothing else. An ordinary mint, EO 8284's
    flag, and the other six collisions are untouched, which is the whole
    reason this table is not loaded through :func:`load_interpretations`.
    A row SHAPE going wrong is NOT isolated and is not meant to be: all
    seven :class:`Interpretation` objects are constructed eagerly at import
    (``witnesses=()``, an undeclared disposition, a ``consulted`` row
    carrying an ``interpreted_value``), so a malformed row fails the module
    import and takes every consumer down with it. That is the right blast
    radius for the two cases being different things: evidence can be
    momentarily unavailable in a deployment, but a row's shape is a defect
    in this module's own source, and it should stop everything at import
    rather than lurk until the one value it describes is asked about.

    Witnesses are checked only where they exist to check. In an installed
    layout (:func:`_repository_root_if_present` answers ``None``) the row
    answers on its own: the verdict is package data, the witness discipline
    is an audit property of the checkout, and REF-066's refusal must not
    depend on the second to deliver the first.
    """

    row = _fr_collision_rows_by_source_value().get(record_id)
    if row is None:
        raise NotReviewed(record_id)
    root = _repository_root_if_present()
    return row if root is None else _witnessed(row, repo_root=root)


def is_a_refused_federal_register_collision(document_number: str) -> bool:
    """Whether ``document_number`` is a pinned-census collision this table refuses.

    Three steps, and the ORDER is the whole point. Membership is checked
    FIRST against this module's own seven rows -- Python literals that
    travel inside the wheel, so the answer costs one dict lookup and
    touches no file, no census and no git. Every one of the 1,004,233-plus
    real document numbers that is not one of the seven returns ``False``
    there, in any layout, whether or not this file was imported from a
    checkout and whether or not git even exists. That property is not a
    nicety: an audit on 2026-09-02 found the earlier census-first order
    raising :class:`HandValidatedRegistryError` from an installed layout
    for ``2024-00366``, an ordinary non-colliding number, which made a pure
    minting function depend on a git checkout.

    Only for one of the seven do the two repository-only checks run:
    :func:`_the_census_agrees_with_this_table` (the rows still say what the
    pinned receipt measured) and :func:`_federal_register_collision_row`
    (this row's own witnesses are still committed bytes). Where there is no
    checkout, neither can run and neither is needed for the verdict.

    The verdict is the row's disposition -- not a second list a caller
    could drift from the first. ``refusal-to-interpret`` (the number names
    two genuinely different documents; minting one identity would merge
    them) answers ``True``. ``consulted`` (the number names one matter
    published twice, so ONE identity is correct) answers ``False``. Any
    other disposition is a data-integrity problem worth stopping for rather
    than silently minting or silently refusing -- see REF-066.

    :func:`refspec.registry.iri_minting.mint_federal_register_document_iri`
    is the one consumer, and checks this FIRST, before attempting any mint:
    minting anything for one of these numbers, even the
    ``rkaf:partner-defined`` escape hatch, would still be one identifier
    standing for two documents.

    What this cannot see: a collision the pinned census's own crawl missed.
    The census describes the crawled Federal Register from 1994 onward (its
    own ``coverage.caveat``, quoted in the evidence home's README) and
    nothing about the printed Register before that; a ninth or tenth
    collision this crawl did not observe would still mint as first-class
    today. Nor can it see a re-crawl's eighth collision from an installed
    layout at all -- there is no census there to disagree with these rows;
    see :func:`_the_census_agrees_with_this_table`.
    """

    if document_number not in _fr_collision_rows_by_source_value():
        return False
    _the_census_agrees_with_this_table()
    row = _federal_register_collision_row(document_number)
    if row.disposition == "refusal-to-interpret":
        return True
    if row.disposition != "consulted":
        raise HandValidatedRegistryError(
            f"{document_number!r} is a Federal Register document-number collision (per the pinned "
            f"census) but its hand-validated row is disposition {row.disposition!r}, not "
            f"'refusal-to-interpret' or 'consulted'"
        )
    return False


@cache
def refused_federal_register_document_numbers() -> frozenset[str]:
    """The full set of census members currently resolved to a refusal.

    A convenience for introspection and tests -- "what does this table
    refuse, in total" -- built by asking
    :func:`is_a_refused_federal_register_collision` about every adjudicated
    member, so it resolves and (in a checkout) witnesses all seven rows at
    once. :func:`refspec.registry.iri_minting.mint_federal_register_document_iri`
    does NOT call this: it calls the per-value predicate directly, so that
    minting one ordinary document number never has to wait on every OTHER
    collision's evidence being resolved at once.
    """

    return frozenset(
        record_id
        for record_id in _fr_collision_rows_by_source_value()
        if is_a_refused_federal_register_collision(record_id)
    )


# --------------------------------------------------------------------------- #
# The table
# --------------------------------------------------------------------------- #

# Two rows so far, built eagerly as frozen Interpretation objects rather than
# held as dicts: a dict row is mutable module state, and "the table said X"
# has to mean the same thing on the second call as on the first. Shape errors
# therefore surface at import; witness checking still waits for
# load_interpretations(), which is what touches git.
#
# Row 1 restates the pilot attestation this module was commissioned to build
# on top of -- research/evidence/hand-attestations-2026-08-31/attestations.jsonl,
# id att-2026-08-31-0001 -- in this module's own typed shape. That evidence
# home's README explicitly declines to be a module ("There is deliberately no
# module here, no reader, and no test... these rows become its founding
# corpus, already shaped for the purpose"); this table is that module. Each
# `shows` below was re-derived by opening the witness itself, so it states
# what THAT file's bytes carry and not what the surrounding investigation
# concluded: the print PDF's colophon is quoted with the EN DASH U+2013 its
# text layer actually holds, the two error-page bodies claim to be error
# pages and not transport statuses, and the one transport status this row
# does assert points at the saved response headers that carry it.
#
# Row 2 is a flag, not a correction, by design, and its prose is confined to
# what its five witnesses establish. It was REWRITTEN on 2026-08-31 after a
# review of the sibling eo_roster lane: an earlier draft of this row rested
# its doubt on NARA's per-order probe of 8284 coming back not_found, and read
# that 404 as the publisher declining to vouch for the number. It is a fact
# about one ROUTE. The same publisher's 1939 disposition table carries the
# order in full, this repository's own committed adjudication recorded its
# official title and date, and the Federal Register printed it at 4 FR 4603.
# So the row now records what the witnesses do establish: EO 8284 exists, and
# the corpus row that cites it is nonetheless doubted -- on relevance, by an
# adjudication that read the rule's other authorities, not on existence. That
# is exactly what a flag is for: "doubted" without "and here is the
# replacement", which the witnesses still do not support.
_TABLE: tuple[Interpretation, ...] = (
    Interpretation(
        source_value="E5-2394",
        context=(
            "federalregister.gov document_number as it would be spelled by inserting the conventional "
            "space before a colophon's 'Filed' -- dereferences nowhere at either publisher."
        ),
        disposition="correction",
        interpreted_value="E5-2394Filed",
        witnesses=(
            Witness(
                path=(
                    "research/evidence/hand-attestations-2026-08-31/witnesses/"
                    "govinfo-print-FR-2005-05-16-E5-2394Filed.pdf"
                ),
                shows=(
                    "Printed Federal Register page 25814 (Vol. 70, No. 93, Monday, May 16, 2005 -- the "
                    "citation 70 FR 25814). Its own colophon reads "
                    "'[FR Doc. E5–2394Filed 5–16–05; 8:45 am]' with no space before "
                    "'Filed', the dashes being EN DASH U+2013 as the print font sets them, while the "
                    "control colophon for a different notice on the same page, "
                    "'[FR Doc. E5–2414 Filed 5–13–05; 8:45 am]', keeps its space. The "
                    "fusion is this document's own composition defect, not a scan or extraction artifact."
                ),
            ),
            Witness(
                path="research/evidence/hand-attestations-2026-08-31/witnesses/fr-api-E5-2394Filed.json",
                shows=(
                    "federalregister.gov API record whose document_number field reads 'E5-2394Filed'; its "
                    "title, agencies, docket I.D. 051005A, publication_date 2005-05-16 and citation "
                    "70 FR 25814 all match the print page."
                ),
            ),
            Witness(
                path="research/evidence/hand-attestations-2026-08-31/witnesses/fr-rawtext-E5-2394Filed.txt",
                shows=(
                    "federalregister.gov full-text page; header '[FR Doc No: E5-2394Filed]' and colophon "
                    "'[FR Doc. E5-2394Filed 5-16-05; 8:45 am]' repeat the fusion, here with ASCII "
                    "hyphen-minus where the print page sets an en dash."
                ),
            ),
            Witness(
                path="research/evidence/hand-attestations-2026-08-31/witnesses/govinfo-mods-E5-2394Filed.xml",
                shows=(
                    "GovInfo granule MODS metadata; '<accessId>E5-2394Filed</accessId>' -- GPO's own "
                    "granule identifier carries the fused token, so the defect is not introduced by the "
                    "Federal Register API layer."
                ),
            ),
            Witness(
                path="research/evidence/hand-attestations-2026-08-31/witnesses/fr-api-E5-2394-404.html",
                shows=(
                    "The BODY the Federal Register served for the unfused spelling: its own error page, "
                    "'<title>404 Not Found</title>' over an '<h1>404 Not Found</h1>' and \"We're unable to "
                    "find the requested page\". These bytes are the page, not the transport status and not "
                    "the request -- the sibling header capture carries both."
                ),
            ),
            Witness(
                path="research/evidence/hand-attestations-2026-08-31/witnesses/hdr-fr-api-E5-2394.txt",
                shows=(
                    "The saved response headers for GET "
                    "https://www.federalregister.gov/api/v1/documents/E5-2394.json, first line "
                    "'HTTP/2 404' with content-type text/html and content-length 4569 -- the transport "
                    "status the body witness cannot show, and the byte count that ties it to that body."
                ),
            ),
            Witness(
                path="research/evidence/hand-attestations-2026-08-31/witnesses/govinfo-print-E5-2394-notfound.html",
                shows=(
                    "What GovInfo served for the unfused PDF path: not a PDF but its generic error "
                    "document, '<title>Page Not Found | GovInfo</title>' canonical to "
                    "https://www.govinfo.gov/error. No transport status is asserted for this request -- "
                    "no header capture for it was committed -- but the bytes are an error page rather "
                    "than the requested document, so the unfused spelling dereferences to nothing here "
                    "either."
                ),
            ),
        ),
        reviewer=(
            "mikewolfd (operator); Claude (Fable 5), "
            "session https://claude.ai/code/session_01LQcDmLDtAnpSpMi1ZzUwTx"
        ),
        reviewed_at="2026-08-31",
        notes=(
            "Transcribed from the pilot attestation at "
            "research/evidence/hand-attestations-2026-08-31/attestations.jsonl (id att-2026-08-31-0001), "
            "which remains the fuller record: it also carries a viewing aid "
            "(witnesses/colophon-comparison-600dpi.png, a 600dpi crop kept for the next human's eye -- not "
            "counted as a witness here, since it carries no information its parent PDF lacks) and the rest "
            "of the saved probe pair-set, whose headers show the neighbouring numbers E5-2393 and E5-2395 "
            "answering 200 while E5-2394 and E5-2396 both answer 404 (a vacancy, not a series ending). "
            "COUNTING WARNING, from that attestation's own notes: the print page, the GovInfo granule id "
            "and the Federal Register API record are one composition defect inherited twice, not three "
            "independent observations -- the witness count here is a count of files opened, and the "
            "reasoning must not treat those three as independent confirmations. Direction is one-way: "
            "resolve an encountered 'E5-2394' TO the stored 'E5-2394Filed', never the reverse -- rewriting "
            "a stored 'E5-2394Filed' back to 'E5-2394' would convert a fetchable identifier into a dead "
            "one, per the pilot attestation's own direction.reverse_substitution=forbidden."
        ),
    ),
    Interpretation(
        source_value="8284",
        context=(
            "Executive Order number carried in this repository's NARA disposition-table codification "
            "window (pre-FR-API EOs) and cited as a complete, in-series executive_order value by the "
            "Unified Agenda corpus."
        ),
        disposition="flag",
        interpreted_value=None,
        witnesses=(
            Witness(
                path="research/evidence/silent-misreads-2026-08-24/adjudication/B_2.tsv",
                shows=(
                    "The adjudication row for this very citation, from the 2026-08-24 silent-misreads "
                    "batch: verdict MISREAD_LAUNDERED, loud_or_silent SILENT, and a publisher check "
                    "against archives.gov/federal-register/executive-orders/1939.html quoting NARA's own "
                    "1939 disposition table -- 'Executive Order 8284 -- Prescribing the Duties of the "
                    "Librarian Emeritus of the Library of Congress' (signed Nov 13 1939), beside "
                    "'Executive Order 8248 -- Establishing the Divisions of the Executive Office of the "
                    "President and Defining Their Functions and Duties' (signed Sept 8 1939). The row "
                    "states the resolution in its own words: '8284 exists and is real, but has nothing to "
                    "do with a governmentwide regulatory authority'. The doubt this flag records is that "
                    "one: relevance, adjudicated against the rule's other authorities, not existence."
                ),
            ),
            Witness(
                path="research/evidence/silent-misreads-2026-08-22.md",
                shows=(
                    "The earlier survey that first bounded this surface, recording the same reading in "
                    "prose: EO 8284 is '\"Prescribing the Duties of the Librarian Emeritus\", which "
                    "confers no fee authority', while OMB Circular A-25's authority is EO 8248 -- and, "
                    "in the same passage, that BOTH members of every such near-miss pair it found are "
                    "real orders, so frequency alone cannot adjudicate one. It calls the technique 'a "
                    "lead-generator, not a detector', which is the same restraint this row's disposition "
                    "encodes."
                ),
            ),
            Witness(
                path="research/evidence/investigations-2026-08-24/inv-eo/nara/orders/eo-08284.html",
                shows=(
                    "NARA's per-order Executive Order detail ROUTE for 08284, fetched 2026-08-24 for the "
                    "EO-existence-oracle investigation (inv-eo): "
                    "'<title>Page Not Found | National Archives</title>', a Drupal 7 error page canonical "
                    "to /global-pages/404, not an order record. These bytes show that NARA's site served "
                    "nothing at this address. They are not a listing of what NARA holds -- the same "
                    "publisher's 1939 disposition table carries the order in full -- so what they "
                    "establish is a fact about one route, and nothing whatever about the order."
                ),
            ),
            Witness(
                path="research/evidence/investigations-2026-08-24/inv-eo/derived/cited-eo-census.csv",
                shows=(
                    "Census row '8284,3,3,201404,201504,' then the edition list 201404,201410,201504 and "
                    "two zeroes: 3 Unified Agenda rows across 3 editions cite 8284, every one of them a "
                    "complete citation (partial_rows=0) and in series (out_of_series_rows=0)."
                ),
            ),
            Witness(
                path="research/evidence/investigations-2026-08-24/inv-eo/derived/nara-order-details.csv",
                shows=(
                    "Two rows from the same 109-page NARA probe. '8284,,,,True' -- the probe recorded "
                    "not_found for 8284, matching the 404 page above. And row eo_number=8248: title "
                    "'Establishing the divisions of the Executive Office of the President and defining "
                    "their functions and duties', date 'Sept. 8, 1939', citation '4 FR 3864', "
                    "not_found=False -- a genuine NARA-codified order whose number is one adjacent-digit "
                    "transposition from 8284 (8-2-8-4 -> 8-2-4-8). Recording that adjacency is all this "
                    "witness does: nothing in these bytes shows that 8284 denotes 8248, which is why it "
                    "is not this row's interpreted_value."
                ),
            ),
        ),
        reviewer=(
            "Claude (Fable 5), Lane E hand-validated-interpretations wave, rewritten in the Lane D "
            "review pass 2026-08-31; operator mikewolfd; "
            "session https://claude.ai/code/session_01LQcDmLDtAnpSpMi1ZzUwTx"
        ),
        reviewed_at="2026-08-31",
        notes=(
            "WHAT THE WITNESSES ESTABLISH, and no more. (1) EO 8284 EXISTS. It is 'Prescribing the "
            "Duties of the Librarian Emeritus of the Library of Congress', signed November 13, 1939, "
            "published at 4 FR 4603 -- recorded in this repository's own committed adjudication and "
            "survey, both of which read NARA's 1939 disposition table. (2) Three Unified Agenda rows "
            "across three editions cite 8284 as a complete, in-series Executive Order number. (3) That "
            "citation is nonetheless doubted, and the doubt is about RELEVANCE, not existence: the "
            "adjudication finds a real-but-unrelated order read as the identity, where the rule's own "
            "quartet of authorities points at EO 8248 (the Executive Office reorganization). (4) NARA's "
            "per-order detail route for 8284 serves a 'Page Not Found' page while its 1939 year table "
            "publishes the order -- a fact about that route. "
            "WHAT THEY DO NOT ESTABLISH. Not that 8284 denotes 8248: that remains a hypothesis, recorded "
            "for a future reviewer and deliberately not asserted as this row's interpreted_value. The "
            "adjudication's own survey says why the shape alone cannot settle it -- both members of "
            "every near-miss pair it found are real orders, so it is 'a lead-generator, not a detector'. "
            "WHAT AN EARLIER DRAFT OF THIS ROW GOT WRONG. It rested this flag on the route 404, reading "
            "it as the publisher's own probe-negative, and the sibling eo_roster lane went further and "
            "wrote that 8284 'does not exist at all'. Both were refuted by evidence this repository "
            "already carried; refspec.registry.eo_roster now answers `exists` for 8284, sourced to a "
            "pinned capture of NARA's 1939 table, and its 404 is recorded as a route artifact. A flag "
            "that survives its own founding argument has to say so, which is what this paragraph is. "
            "ON THE MINED RIDER. research/investigations-mined-2026-08-31.md carries the rider the "
            "earlier draft followed: 'EO 8284 is the publisher's own probe-negative (NARA not_found) "
            "published as a good citation on 3 rows; the 8284->8248 correction currently rests partly on "
            "a Wikipedia tie-break and should ship as a flag, not a correction.' The rider reached the "
            "right disposition by the wrong route. Two findings about it, from the bytes: the "
            "'probe-negative' is the route artifact above; and the two committed Wikipedia captures for "
            "these numbers (research/evidence/investigations-2026-08-24/inv-eo/derived/wiki-eo-8248.html "
            "and wiki-eo-8284.html) each contain the literal MediaWiki string 'Wikipedia does not have "
            "an article with this exact name' -- for 8248 exactly as much as for 8284. Whatever "
            "tie-break the rider means, it is not in these two files as committed, so there is no "
            "Wikipedia tie-break here to weigh in either direction."
        ),
    ),
)


# --------------------------------------------------------------------------- #
# The Federal Register collision rows (REF-066) -- kept apart from _TABLE
# --------------------------------------------------------------------------- #
#
# These seven rows use the exact same Interpretation/Witness discipline as
# every row in _TABLE above, checked by the exact same _witnessed(). They
# live in their OWN tuple rather than being appended to _TABLE, for one
# reason: load_interpretations() validates _TABLE as one atomic unit, BY
# DESIGN -- exactly right for a handful of rarely-changing rows consulted by
# name (E5-2394, 8284), and the wrong property for a population consulted on
# nearly every Federal Register document number minted anywhere on the
# platform. Coupling an ORDINARY document number's mint to the witness
# health of an unrelated Executive Order flag (or vice versa) would make one
# broken witness anywhere refuse every mint everywhere, not just the seven
# numbers this table is actually about -- see
# :func:`_federal_register_collision_row` and
# :func:`is_a_refused_federal_register_collision`, which resolve and witness
# each of these seven independently, one at a time, and never touch
# :data:`_TABLE`.
#
# Rows 1-7: the seven modern-form Federal Register document-number
# collisions the 2026-09-02 full crawl found. Each pair of witnesses is the
# two dated federalregister.gov full-text captures for that ``recordId`` --
# research/evidence/fr-collision-census-2026-09-02/specimens/
# {recordId}__{date}.html -- fetched and read directly, because the API's
# own `correction_of` field answers `null` for every one of these seven,
# including the two that ARE self-corrections (fetched 2026-09-02:
# `correction_of":null` on both 2015-17759 and 2015-25354). Metadata cannot
# separate a `refusal-to-interpret` row from a `consulted` row here; only
# the document body can, which is why every `shows` string below quotes the
# body, not the API record.
#
# Five are `refusal-to-interpret`: two unrelated documents, different
# agencies, different subjects, sharing one number by accident of the
# publisher's own numbering. Minting one ``rkaf:us-frdoc`` for either pair
# would merge two regulatory actions that have nothing to do with each
# other. Two are `consulted`: a notice and its own correction, explicitly
# self-referential ("In notice document 2015-17759 ... make the following
# correction"), so ONE identifier for both is what a reader following
# either copy would expect -- examined and correctly left to mint, not
# overlooked.
_FR_COLLISION_TABLE: tuple[Interpretation, ...] = (
    Interpretation(
        source_value="2010-31094",
        context=(
            "Federal Register document_number, modern form -- the 2026-09-02 collision census "
            "(research/evidence/fr-collision-census-2026-09-02/) records two publication dates for this "
            "number, 2010-01-06 and 2010-12-10."
        ),
        disposition="refusal-to-interpret",
        interpreted_value=None,
        witnesses=(
            Witness(
                path="research/evidence/fr-collision-census-2026-09-02/specimens/2010-31094__2010-01-06.html",
                shows=(
                    "EPA notice [EPA-HQ-OPP-2009-0879; FRL-8806-4]: the Exposure Modeling Public Meeting "
                    "(EMPM), scheduled for January 26, 2010, has been cancelled and that the next EMPM "
                    "will be held in July 2010."
                ),
            ),
            Witness(
                path="research/evidence/fr-collision-census-2026-09-02/specimens/2010-31094__2010-12-10.html",
                shows=(
                    "DOT/FAA NPRM extension of comment period [Docket No. FAA-2010-0997; Notice No. "
                    "10-14], an unrelated airport-safety-management-system rulemaking published two "
                    "agencies and eleven months away from the January EPA notice above."
                ),
            ),
        ),
        reviewer="Claude (Sonnet 5), Lane A collision-refusal wave; operator mikewolfd",
        reviewed_at="2026-09-02",
        notes=(
            "Different departments (Environmental Protection Agency; Department of Transportation / "
            "Federal Aviation Administration), different dockets, different subjects, no textual "
            "relationship between the two documents. One document number, two unrelated documents: "
            "refused rather than merged. See REF-066."
        ),
    ),
    Interpretation(
        source_value="2010-31384",
        context=(
            "Federal Register document_number, modern form -- the 2026-09-02 collision census records "
            "two publication dates for this number, 2010-01-06 and 2010-12-16."
        ),
        disposition="refusal-to-interpret",
        interpreted_value=None,
        witnesses=(
            Witness(
                path="research/evidence/fr-collision-census-2026-09-02/specimens/2010-31384__2010-01-06.html",
                shows=(
                    "Department of Commerce, National Telecommunications and Information Administration "
                    "notice reopening the application period for a spectrum management advisory "
                    "committee."
                ),
            ),
            Witness(
                path="research/evidence/fr-collision-census-2026-09-02/specimens/2010-31384__2010-12-16.html",
                shows=(
                    "DOT/FAA final rule [Docket No. FAA-2009-0430; Directorate Identifier 2008-NM-148-AD; "
                    "Amendment 39-16540; AD 2010-26-01], an airworthiness directive for Boeing 777-200 "
                    "series airplanes -- unrelated to the Commerce/NTIA notice above."
                ),
            ),
        ),
        reviewer="Claude (Sonnet 5), Lane A collision-refusal wave; operator mikewolfd",
        reviewed_at="2026-09-02",
        notes=(
            "Different departments (Commerce/NTIA; Transportation/FAA), different subjects (a spectrum "
            "advisory committee application window against a Boeing 777 airworthiness directive), no "
            "textual relationship. One document number, two unrelated documents: refused rather than "
            "merged. See REF-066."
        ),
    ),
    Interpretation(
        source_value="2010-31396",
        context=(
            "Federal Register document_number, modern form -- the 2026-09-02 collision census records "
            "two publication dates for this number, 2010-01-06 and 2010-12-15."
        ),
        disposition="refusal-to-interpret",
        interpreted_value=None,
        witnesses=(
            Witness(
                path="research/evidence/fr-collision-census-2026-09-02/specimens/2010-31396__2010-01-06.html",
                shows=(
                    "EPA notice [EPA-HQ-OPP-2009-0977; FRL-8806-2]: receipt of a registrant's request to "
                    "voluntarily cancel their registrations of certain pesticide products."
                ),
            ),
            Witness(
                path="research/evidence/fr-collision-census-2026-09-02/specimens/2010-31396__2010-12-15.html",
                shows=(
                    "DOT Maritime Administration notice [Docket No. MARAD 2010 0109], requesting "
                    "extension of approval for an information collection -- unrelated to the pesticide "
                    "registration notice above."
                ),
            ),
        ),
        reviewer="Claude (Sonnet 5), Lane A collision-refusal wave; operator mikewolfd",
        reviewed_at="2026-09-02",
        notes=(
            "Different departments (Environmental Protection Agency; Transportation/Maritime "
            "Administration), different subjects, no textual relationship. One document number, two "
            "unrelated documents: refused rather than merged. See REF-066."
        ),
    ),
    Interpretation(
        source_value="2010-31415",
        context=(
            "Federal Register document_number, modern form -- the 2026-09-02 collision census records "
            "two publication dates for this number, 2010-01-06 and 2010-12-15."
        ),
        disposition="refusal-to-interpret",
        interpreted_value=None,
        witnesses=(
            Witness(
                path="research/evidence/fr-collision-census-2026-09-02/specimens/2010-31415__2010-01-06.html",
                shows=(
                    "Postal Regulatory Commission notice [Docket No. CP2010-19; Order No. 374] concerning "
                    "a Global Direct Contracts 1 agreement added to the Competitive Product List."
                ),
            ),
            Witness(
                path="research/evidence/fr-collision-census-2026-09-02/specimens/2010-31415__2010-12-15.html",
                shows=(
                    "DOE/Federal Energy Regulatory Commission notice of competing preliminary permit "
                    "applications naming Hydro Friends Fund XLVII, FFP Missouri 16, LLC among the "
                    "applicants -- a hydropower-feasibility filing unrelated to the postal ratemaking "
                    "notice above."
                ),
            ),
        ),
        reviewer="Claude (Sonnet 5), Lane A collision-refusal wave; operator mikewolfd",
        reviewed_at="2026-09-02",
        notes=(
            "Different agencies (the independent Postal Regulatory Commission; Energy/FERC), different "
            "subjects, no textual relationship. One document number, two unrelated documents: refused "
            "rather than merged. See REF-066."
        ),
    ),
    Interpretation(
        source_value="2010-517",
        context=(
            "Federal Register document_number, modern form -- the 2026-09-02 collision census records "
            "two publication dates for this number, 2010-01-14 and 2010-01-28. The closest of the seven: "
            "its second appearance is captioned 'Correction', the same surface word the two consulted "
            "rows below carry, and only reading WHICH document it corrects separates it from them."
        ),
        disposition="refusal-to-interpret",
        interpreted_value=None,
        witnesses=(
            Witness(
                path="research/evidence/fr-collision-census-2026-09-02/specimens/2010-517__2010-01-14.html",
                shows=(
                    "DOE/Federal Energy Regulatory Commission notice [Docket No. CP10-33-000]: "
                    "CenterPoint Energy Gas Transmission Company (CEGT) filed an application to abandon "
                    "by sale to ScissorTail Energy, LLC its Shawnee Compressor Station facilities."
                ),
            ),
            Witness(
                path="research/evidence/fr-collision-census-2026-09-02/specimens/2010-517__2010-01-28.html",
                shows=(
                    "DHS/Coast Guard rule [Docket No. USCG-2007-0115; RIN 1625-AA87], captioned "
                    "'Correction': 'Rule document E8-11863 was inadvertently published in the Proposed "
                    "Rules section of the issue of May 28, 2008, beginning on page 30560. It should have "
                    "appeared in the Rules and Regulations section.' This corrects E8-11863, NOT "
                    "2010-517 itself, and comes from a different department than the gas-pipeline notice "
                    "above."
                ),
            ),
        ),
        reviewer="Claude (Sonnet 5), Lane A collision-refusal wave; operator mikewolfd",
        reviewed_at="2026-09-02",
        notes=(
            "The word 'Correction' in the second document's caption is what makes this specimen worth "
            "naming apart from the other four refusals: by shape alone it reads like the consulted rows "
            "below, which are also captioned 'Correction'. Reading the body settles it -- this correction "
            "names a DIFFERENT document number (E8-11863) as what it corrects, never '2010-517', and it "
            "comes from a different department (Homeland Security/Coast Guard) than the gas-pipeline "
            "abandonment notice (Energy/FERC) that also carries '2010-517'. Two unrelated documents "
            "happen to share a number and one of them happens to be a correction of something else "
            "entirely: refused rather than merged. See REF-066."
        ),
    ),
    Interpretation(
        source_value="2015-17759",
        context=(
            "Federal Register document_number, modern form -- the 2026-09-02 collision census records "
            "two publication dates for this number, 2015-07-21 and 2015-08-05. The federalregister.gov "
            "API's own correction_of field answers null for both dates (fetched 2026-09-02), so this "
            "row rests on the document bodies, not the API's correction-linking metadata."
        ),
        disposition="consulted",
        interpreted_value=None,
        witnesses=(
            Witness(
                path="research/evidence/fr-collision-census-2026-09-02/specimens/2015-17759__2015-07-21.html",
                shows=(
                    "SEC notice [Release No. 34-75460; File No. SR-NYSEMKT-2015-48]: NYSE MKT LLC filed a "
                    "proposed rule change extending the pilot period applicable to the Customer Best "
                    "Execution Auction (CUBE)."
                ),
            ),
            Witness(
                path="research/evidence/fr-collision-census-2026-09-02/specimens/2015-17759__2015-08-05.html",
                shows=(
                    "Same SEC release and file number, captioned 'Correction': 'In notice document "
                    "2015-17759, appearing on pages 43141 through 43143 in the issue of Tuesday, July 21, "
                    "2015, make the following correction' -- a one-word date fix in the same filing, self-"
                    "referencing its own document number."
                ),
            ),
        ),
        reviewer="Claude (Sonnet 5), Lane A collision-refusal wave; operator mikewolfd",
        reviewed_at="2026-09-02",
        notes=(
            "Same agency (Securities and Exchange Commission), same release and file number, and the "
            "second document names the FIRST one by its own document_number as what it corrects -- one "
            "matter, published twice under one number. A single rkaf:us-frdoc identifier for '2015-17759' "
            "is the CORRECT reading, not a tolerance: it is what a reader following either copy would "
            "expect the number to resolve to. Consulted and deliberately left to mint normally rather "
            "than refused. See REF-066."
        ),
    ),
    Interpretation(
        source_value="2015-25354",
        context=(
            "Federal Register document_number, modern form -- the 2026-09-02 collision census records "
            "two publication dates for this number, 2015-10-06 and 2015-10-13. The federalregister.gov "
            "API's own correction_of field answers null for both dates (fetched 2026-09-02), so this "
            "row rests on the document bodies, not the API's correction-linking metadata."
        ),
        disposition="consulted",
        interpreted_value=None,
        witnesses=(
            Witness(
                path="research/evidence/fr-collision-census-2026-09-02/specimens/2015-25354__2015-10-06.html",
                shows=(
                    "Department of Education notice [Docket No.: ED-2015-ICCD-0118] proposing "
                    "reinstatement of a previously approved information collection for the Talent Search "
                    "Program, comments due before December 7, 2015."
                ),
            ),
            Witness(
                path="research/evidence/fr-collision-census-2026-09-02/specimens/2015-25354__2015-10-13.html",
                shows=(
                    "Same Department of Education docket, captioned 'Correction': 'In notice document "
                    "2015-25354, appearing on pages 60358-60369 in the Issue of Tuesday, October 6, 2015, "
                    "make the following correction' -- the comment deadline corrected from December 7, "
                    "2015 to November 5, 2015, self-referencing its own document number."
                ),
            ),
        ),
        reviewer="Claude (Sonnet 5), Lane A collision-refusal wave; operator mikewolfd",
        reviewed_at="2026-09-02",
        notes=(
            "Same agency (Department of Education), same docket (ED-2015-ICCD-0118), and the second "
            "document names the FIRST one by its own document_number as what it corrects -- one matter, "
            "published twice under one number. A single rkaf:us-frdoc identifier for '2015-25354' is the "
            "CORRECT reading, not a tolerance. Consulted and deliberately left to mint normally rather "
            "than refused. See REF-066."
        ),
    ),
)


def _require_unique_source_values(rows: tuple[Interpretation, ...]) -> None:
    """Refuse a table where two rows claim the same value, naming both.

    Silently returning the first match would make the second row's review
    invisible: a reviewer could add a contradicting reading, see the tests
    pass, and never learn that nothing consults it.
    """

    first: dict[str, Interpretation] = {}
    for row in rows:
        earlier = first.get(row.source_value)
        if earlier is not None:
            raise HandValidatedRegistryError(
                f"two rows claim source_value {row.source_value!r}: "
                f"[{earlier.disposition}, reviewed {earlier.reviewed_at}, context {earlier.context!r}] "
                f"and [{row.disposition}, reviewed {row.reviewed_at}, context {row.context!r}]. "
                f"One value, one reading -- merge them or give them different source_values"
            )
        first[row.source_value] = row


@cache
def load_interpretations() -> tuple[Interpretation, ...]:
    """Return every hand-validated row, each already checked against git.

    Cached: the table is a fixed, in-repository literal, and the check this
    performs runs two git subprocesses and a realpath over every witness --
    not something a hot lookup path should repeat.
    """

    _require_unique_source_values(_TABLE)
    return tuple(_witnessed(row) for row in _TABLE)


@cache
def _by_source_value() -> Mapping[str, Interpretation]:
    return MappingProxyType({row.source_value: row for row in load_interpretations()})


def lookup(source_value: str) -> Interpretation:
    """Consult the register for one exact source value, in either table.

    Returns the full :class:`Interpretation` -- disposition, witnesses,
    reviewer, everything -- never a bare corrected string. Raises
    :class:`NotReviewed` when NEITHER table names the value, so a caller
    cannot mistake "nobody looked at this" for a falsy answer.

    Both tables are reachable. REF-066's :data:`_FR_COLLISION_TABLE` is
    asked first, one row at a time through
    :func:`_federal_register_collision_row`, then :data:`_TABLE`, loaded
    and witnessed as one unit exactly as it always has been. That the
    collision half is reachable at all is what an audit on 2026-09-02 found
    missing: a ``consulted`` row exists precisely to record "examined, and
    deliberately not acted on", and a caller who got :class:`NotReviewed`
    -- "nobody looked" -- for ``2015-17759`` was told the opposite of what
    two witnesses say about it.

    The ORDER is behaviour-neutral and chosen for cost:
    :func:`_fr_collision_rows_by_source_value` refuses to build at all if
    one ``source_value`` is adjudicated in both tables, so no value can be
    answered differently by asking one first. Asking the wheel-carried
    table first means a collision number resolves without loading and
    witnessing the founding table -- and so keeps answering in an installed
    layout, where :data:`_TABLE` is repository tooling and raises. A value
    in neither table pays one dict miss and then that same founding load.
    """

    row = _fr_collision_rows_by_source_value().get(source_value)
    if row is not None:
        return _federal_register_collision_row(source_value)
    try:
        return _by_source_value()[source_value]
    except KeyError:
        raise NotReviewed(source_value) from None


__all__ = [
    "DISPOSITIONS",
    "FR_COLLISION_CENSUS_ARTIFACT",
    "MINIMUM_WITNESSES",
    "MINIMUM_WITNESSES_FOR_CORRECTION",
    "Disposition",
    "HandValidatedRegistryError",
    "Interpretation",
    "NotReviewed",
    "Witness",
    "build_interpretation",
    "is_a_refused_federal_register_collision",
    "load_interpretations",
    "lookup",
    "refused_federal_register_document_numbers",
]
