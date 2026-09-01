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
one behaviour a test can break: :func:`lookup` must never hand back a
correction, a flag, or a refusal that is not backed by at least one witness
pointing at bytes this repository has actually committed.

Disposition typing
-------------------
Three dispositions, and they mean different things:

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
  unresolved; the witnesses record why, not what.

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

Deployment scope (adjudicated 2026-08-31)
------------------------------------------
**This module is repository tooling, and says so rather than pretending
otherwise.** Its default root is ``Path(__file__).resolve().parents[3]``,
which is the checkout when this file is imported from ``src/`` and is
somewhere useless (``site-packages/``) when it is imported from an installed
wheel. Rather than let that fail obscurely -- every witness "missing", the
table refusing to load with a filesystem error -- the default root is
verified once to *look like this repository* (it must carry
:data:`_REPOSITORY_ANCHOR` and be the top level of a git work tree) and
raises :class:`HandValidatedRegistryError` naming the deployment problem if
it does not. A caller with its own checkout passes ``repo_root=`` explicitly;
that root is held to the same git-work-tree rule, so passing ``/`` (or any
directory that merely happens to contain a matching relative path) refuses
instead of validating ``/etc/passwd``. If this table is ever wanted inside a
wheel, the fix is to ship the witnessed bytes with it and pin them by digest,
the way :mod:`refspec.registry.eo_roster` pins its roster -- not to loosen
this check.

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

REF-052 named the doctrine this module extends: "the column is the license"
-- a value arriving from a trusted column is licensed by the field it came
from, not by a shape a grammar recognises. A row here licenses an
interpretation the same way, on different terms: not by which column the
value arrived in, but by which witnesses a reviewer actually opened.
"""

from __future__ import annotations

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

Disposition = Literal["correction", "flag", "refusal-to-interpret"]
DISPOSITIONS: frozenset[Disposition] = frozenset({"correction", "flag", "refusal-to-interpret"})

#: A correction asserts that two spellings name one thing; that claim needs
#: more than a single witness. A flag or a refusal asserts nothing beyond
#: "this value was looked at", so one witness is the floor for every row.
#: Read-only: a floor a caller could raise or lower at runtime would make
#: "this row cleared the floor" a statement about that caller, not about the
#: table, and every negative fixture below would be one assignment from
#: passing vacuously.
MINIMUM_WITNESSES: Mapping[Disposition, int] = MappingProxyType(
    {
        "correction": 2,
        "flag": 1,
        "refusal-to-interpret": 1,
    }
)
MINIMUM_WITNESSES_FOR_CORRECTION = MINIMUM_WITNESSES["correction"]


class HandValidatedRegistryError(ValueError):
    """A row, or one of its witnesses, refuses to load."""


class NotReviewed(LookupError):
    """No hand-validated interpretation exists for this exact source value.

    Raised rather than returning ``None`` so "nobody has reviewed this" can
    never be mistaken for a disposition, a bug, or a falsy correction.
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
def _default_repository_root() -> Path:
    """The checkout this file lives in -- verified, not assumed. See the docstring."""

    root = Path(__file__).resolve().parents[3]
    if not (root / _REPOSITORY_ANCHOR).is_dir():
        raise HandValidatedRegistryError(
            f"this module is repository tooling: it resolves witnesses relative to the checkout it "
            f"lives in, and {root} does not carry {_REPOSITORY_ANCHOR}. Imported from an installed "
            f"wheel there is no evidence tree to check witnesses against; pass repo_root= explicitly "
            f"if you have a checkout"
        )
    return _work_tree_root(root)


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
    """Consult the register for one exact source value.

    Returns the full :class:`Interpretation` -- disposition, witnesses,
    reviewer, everything -- never a bare corrected string. Raises
    :class:`NotReviewed` when the value has never been reviewed, so a caller
    cannot mistake "nobody looked at this" for a falsy answer.
    """

    try:
        return _by_source_value()[source_value]
    except KeyError:
        raise NotReviewed(source_value) from None


__all__ = [
    "DISPOSITIONS",
    "MINIMUM_WITNESSES",
    "MINIMUM_WITNESSES_FOR_CORRECTION",
    "Disposition",
    "HandValidatedRegistryError",
    "Interpretation",
    "NotReviewed",
    "Witness",
    "build_interpretation",
    "load_interpretations",
    "lookup",
]
