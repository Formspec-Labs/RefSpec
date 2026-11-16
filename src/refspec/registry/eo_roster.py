"""Does Executive Order N exist -- asked of a pinned, window-split oracle.

Today the only fence on an Executive Order citation is
``citation_grammar.EO_HIGHEST_KNOWN`` -- a bare ``1 <= n <= 14_420`` range
check (``_SeriesCalendar.eo_in_known_series``). It cannot distinguish a real
order from a plausible-looking typo: **43 unresolved numbers / 2,876 rows**
pass it today and read as valid citations
(``research/investigations-mined-2026-08-31.md``, item 5). This module is
the fence that can, built the way
:mod:`refspec.registry.usc_section_oracle` fences a U.S.C. section: a pinned,
digest-verified roster consulted at read time, never guessed at.

What the oracle is
-------------------
One roster of 6,147 numbers, re-derived from committed raw bytes and pinned
by sha256 in :data:`_ROSTER_PIN` -- see
``research/evidence/eo-roster-2026-08-31/README.md`` for the full method and
provenance chain, and its ``derive_roster.py`` for the extraction. Five
publisher captures feed it, each named in :data:`SOURCE_RANGES` with the
number range it actually witnesses:

* **the NARA codification-numeric index** (18 raw pages, 4,162 numbers,
  9-12,667) -- an *existence-only* listing with no title/date;
* **the NARA 1939 disposition table** (286 numbers, 8,031-8,316) -- a
  complete calendar-year listing with title, signing date and FR citation
  for every order, fetched and pinned 2026-08-31 to resolve EO 8284 (below);
* **109 NARA per-order detail-page probes**, fetched for the numbers this
  corpus cites in that range. 108 return an order page and one -- EO 8284 --
  returns a Drupal "Page Not Found". That is a fact about NARA's per-order
  ROUTE, not about the order: the same publisher's 1939 year table carries
  EO 8284 in full, so the probe's ``not_found`` is never read as absence;
* **the FR-API window** (1,531 numbers, 12,890-14,420) -- every Federal
  Register API record with an assigned ``executive_order_number``;
* **the 1989-1993 gap closure** (223 numbers, 12,668-12,890) -- every entry
  NARA's per-year disposition pages carry across the dead zone between the
  other two sources, 62 of them ONLY from Wayback captures of two NARA pages
  now dead on the live site (every non-1989-92 year route on archives.gov now
  serves one identical stub). Those Wayback bytes are pinned publisher
  evidence, not prunable research -- see the Durability section of
  ``research/investigations-mined-2026-08-31.md``.

The window split, and why it is the whole point
-------------------------------------------------
A roster miss means two different things depending on WHERE the missed
number falls, and conflating them mints false ``absent`` verdicts. Each
declared window in :data:`WINDOWS` carries a measured density, and only a
window in :data:`ABSENT_CAPABLE` may ever authorize ``absent``:

* :data:`FR_API_WINDOW` (12,890-:data:`FR_API_DENSE_MAX`) is **measured fully
  dense**: every one of the 1,531 integers in this range is on the roster
  (density 1,531/1,531, re-verified at load -- see :func:`_verify_density`).
  A miss here is a genuine absence, so :meth:`EoRosterOracle.verdict` may
  publish ``absent``.
* :data:`NARA_CODIFICATION_WINDOW` (9-12,667) is **measured 34.7% dense**
  (4,394 of 12,659 numbers) -- the roster only names numbers this corpus
  happened to cite, or that the numeric index and the 1939 table printed,
  never a complete listing of every order Presidents issued 1862-1993. A
  miss here is overwhelmingly a coverage hole, not a nonexistent number, so
  a miss NEVER becomes ``absent`` -- only ``unknown``. EO 9397 (1943, the
  Social Security numbering order, cited as an amendment-chain endpoint by a
  sibling harvest) is a live specimen: it is a real, famous order, it is NOT
  on this roster, and this oracle answers ``unknown``, never ``absent``.
* :data:`NARA_DISPOSITION_WINDOW` (12,668-12,889) holds the gap closure. It
  measures 222/222 on today's roster, which is *not* a licence to call
  absences there: a fully-dense measurement over one narrow run of years is
  a much weaker claim than the FR API's own record of every assigned number,
  and widening ``absent`` authority is exactly the kind of quiet promotion
  this module refuses to make without its own review. Affirm-only, like the
  codification window.
* A number in neither window (below 9, or above :data:`FR_API_DENSE_MAX`) is
  ``unknown`` for the same reason: this oracle has no density claim there.

Measured absence, not inherited absence
----------------------------------------
:data:`FR_API_DENSE_MAX` is **evidence**, not a restatement of the citation
grammar's ceiling: it is the largest number the FR-API capture assigns, and
:func:`_verify_density` refuses to load unless the pinned roster still
attains it and fills every integer beneath it back to 12,890. An earlier
draft bound this bound to ``citation_grammar.EO_HIGHEST_KNOWN`` instead, so
advancing that constant for a new order would have silently extended the
range in which this module publishes ``absent`` -- ``verdict(14421)`` would
have answered "absent" on the authority of a roster that has never seen a
number that high. The two values coincide today (both are 14,420, the newest
assigned EO number as of 2026-08) and that coincidence is asserted nowhere:
if the grammar's ceiling moves first, this oracle keeps answering ``unknown``
above its own measured bound until the roster is re-derived and re-pinned.

Measured against the corpus's own cited-EO census
(``research/evidence/investigations-2026-08-24/inv-eo/derived/
cited-eo-census.csv``, reproduced in
``research/evidence/eo-roster-2026-08-31/measure.py``): the roster affirms
378 of 391 cited numbers (18,954 of 19,011 rows), leaving 10 numbers honestly
``unknown`` (50 rows) -- 9 pre-1929 orders outside the NARA disposition-table
era, plus EO 7419. Three more uncovered numbers (20450, 21600, 23891) exceed
the roster's own ceiling and are already caught by today's
``eo_in_known_series`` fence -- this oracle answers them ``unknown`` too, not
new information.

EO 8284: what a route-level 404 does and does not establish
-------------------------------------------------------------
EO 8284 is cited on 3 corpus rows, and NARA's per-order detail route for it
serves a "Page Not Found" page. An earlier draft of this module read that as
a "publisher probe-negative" and kept 8284 off the roster; the repository's
own committed evidence said otherwise all along
(``research/evidence/silent-misreads-2026-08-22.md`` and
``research/evidence/silent-misreads-2026-08-24/adjudication/B_2.tsv``, which
record the order's official title and date), and NARA's own 1939 disposition
table -- now fetched and pinned into the evidence home -- lists **EO 8284,
"Prescribing the Duties of the Librarian Emeritus of the Library of
Congress", signed 1939-11-13, 4 FR 4603** between 8283 and 8285. The Federal
Register issue of 1939-11-17 carries the order's text over the signature
``[No. 8284]``. So the order exists, this oracle answers ``exists``, and the
404 is recorded for what it is: a fact about one route.

That correction is why :meth:`flag_for` is deliberately narrow. The
hand-reviewed row for source value ``"8284"`` in
:mod:`refspec.registry.hand_validated_interpretations` survives -- the corpus
row really is doubted, because an adjudication in this repository finds it a
laundered misread of a real-but-unrelated order -- but it now rests on
witnesses that establish the order's existence rather than on a 404 that
never established its absence.
"""

from __future__ import annotations

import csv
import hashlib
import re
from collections.abc import Mapping
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path
from types import MappingProxyType

from refspec.registry import hand_validated_interpretations

__all__ = [
    "ABSENT_CAPABLE",
    "CANDIDATE_REJECTION_REASONS",
    "DEFAULT_MAX_PLAUSIBLE_EO",
    "EO_PLAUSIBLE_HEADROOM",
    "EO_ROSTER_ARTIFACT",
    "FR_API_DENSE_MAX",
    "FR_API_WINDOW",
    "GOVINFO_FR_1939_11_17_CAPTURE",
    "NARA_CODIFICATION_WINDOW",
    "NARA_DISPOSITION_WINDOW",
    "NARA_EO_1939_CAPTURE",
    "SOURCE_RANGES",
    "UNKNOWN_REASONS",
    "VERDICTS",
    "WINDOWS",
    "EoCandidateCheck",
    "EoCapturePin",
    "EoProseCitation",
    "EoRosterOracle",
    "EoVerdict",
    "find_executive_order_citations",
    "is_valid_eo_candidate",
    "window_for",
]

#: The sealed evidence home, relative to the repository root, whose digest
#: this module's :data:`_ROSTER_PIN` restates. See its README.md for the
#: full re-derivation-and-diff ceremony against the investigation copies.
EO_ROSTER_ARTIFACT = "research/evidence/eo-roster-2026-08-31"
_ROSTER_FILE = "derived/roster.csv"
_ROSTER_PIN = "sha256:967ad595326ea37bb368357f7da6253fe292123e305c95c346bf152254e20c9d"


@dataclass(frozen=True)
class EoCapturePin:
    """One raw publisher capture in the sealed evidence home, pinned immutably.

    These are provenance, not a runtime input: this module reads the DERIVED
    roster, so no execution consumes the captures and the audit manifest names
    that honestly as a blocker rather than declaring them as testInputs (it was
    tried the other way on 2026-09-02 and the real-data gate correctly refused
    it -- a declared publisher input whose digest no execution ever sees).
    What they DO earn: the two publisher URLs below reach the manifest's
    ``declaredUrls`` because this module states them, so the acquisition is
    recorded where a reader will find it, and
    ``test_the_capture_pins_agree_with_the_evidence_manifest`` holds these
    digests to the ones ``MANIFEST-sha256.csv`` states so the two copies
    cannot drift apart.
    """

    source_url: str
    retrieved_at: str
    expected_sha256: str
    expected_byte_length: int


#: NARA's own 1939 Executive Order disposition table -- the publisher page
#: whose contiguous 8,031-8,316 run (and the EO 8284 row the review turned
#: on) seeds the roster's 1939 window. Retrieved-at is the capture's own
#: response `date` header, kept beside it in raw/nara-eo-1939.headers.txt.
NARA_EO_1939_CAPTURE = EoCapturePin(
    source_url="https://www.archives.gov/federal-register/executive-orders/1939.html",
    retrieved_at="2026-08-31T23:05:56Z",
    expected_sha256="sha256:6575dcd808f06c39def77e7411d50813bdb32edb7c9359bbdda9f309a037711a",
    expected_byte_length=144_520,
)

#: The Federal Register issue of 1939-11-17 (Volume 4), whose front page
#: prints EO 8284 at 4 FR 4603 -- the primary source that settled the 8284
#: reversal (REF-057). The URL is GovInfo's canonical package path for the
#: issue; its response today still reports the pinned content-length
#: (2,400,332) and the capture's own last-modified (2025-09-22T19:57:34Z),
#: verified 2026-09-01. Retrieved-at is the capture's response `date` header
#: (raw/govinfo-FR-1939-11-17.headers.txt).
GOVINFO_FR_1939_11_17_CAPTURE = EoCapturePin(
    source_url="https://www.govinfo.gov/content/pkg/FR-1939-11-17/pdf/FR-1939-11-17.pdf",
    retrieved_at="2026-08-31T23:09:32Z",
    expected_sha256="sha256:9a6a961b3e327c92b85a9afeaff4dafbfacf3178007467e3f83c3f1313b25987",
    expected_byte_length=2_400_332,
)

VERDICTS = ("exists", "absent", "unknown")

#: The largest Executive Order number the FR-API capture assigns, and the top
#: of the only range in which this module may say `absent`. Evidence, not a
#: grammar constant: :func:`_verify_density` refuses to load a roster that
#: does not attain it -- see the module docstring's "Measured absence".
FR_API_DENSE_MAX = 14_420

#: Headroom above the roster's highest attested number for prose candidate
#: validation (`1 <= N <= max_eo + 200`), admitting newly signed orders not yet
#: in the pinned capture while rejecting 6-7+ digit OCR/slug concatenations
#: (`E.O. 1165492`) and out-of-series numbers (`20450`).
EO_PLAUSIBLE_HEADROOM = 200
DEFAULT_MAX_PLAUSIBLE_EO = FR_API_DENSE_MAX + EO_PLAUSIBLE_HEADROOM

CANDIDATE_REJECTION_REASONS = (
    "xml_or_file_path",
    "zero_homoglyph_or_malformed_label",
    "leading_zero",
    "non_positive_number",
    "exceeds_plausible_ceiling",
    "absent_in_dense_window",
)

#: 34.7% dense (4,394 of 12,659 numbers, measured against the pinned roster
#: -- see the evidence home's measure.py). Affirm-only.
NARA_CODIFICATION_WINDOW = (9, 12_667)

#: The 1989-1993 gap closure's own range. 222/222 on today's roster and still
#: affirm-only on purpose -- see the module docstring.
NARA_DISPOSITION_WINDOW = (12_668, 12_889)

#: Fully dense (1,531 of 1,531 -- every integer in range is on the roster,
#: re-verified at load).
FR_API_WINDOW = (12_890, FR_API_DENSE_MAX)

#: Every declared window, and the range of numbers it speaks for. Windows are
#: disjoint and ordered; a number in none of them gets no density claim.
WINDOWS: Mapping[str, tuple[int, int]] = MappingProxyType(
    {
        "nara_codification": NARA_CODIFICATION_WINDOW,
        "nara_disposition": NARA_DISPOSITION_WINDOW,
        "fr_api": FR_API_WINDOW,
    }
)

#: The windows whose measured density licenses an `absent` verdict. Exactly
#: one, and widening this set is a claim that needs its own measurement and
#: its own review -- not a side effect of a roster re-pin.
ABSENT_CAPABLE = frozenset({"fr_api"})

#: Each roster source and the number range it actually witnesses, restated
#: from ``derive_roster.py``'s own measurement (it prints these) and verified
#: against the pinned roster at load. An `exists` verdict whose number falls
#: outside the range of the capture that supposedly witnessed it is a shape
#: error, not a verdict -- see :meth:`EoVerdict.__post_init__`.
SOURCE_RANGES: Mapping[str, tuple[int, int]] = MappingProxyType(
    {
        "nara-codification-index": (9, 12_667),
        "nara-order-detail-probe": (9_830, 12_656),
        "nara-disposition-1939": (8_031, 8_316),
        "gap-closure-nara-live": (12_668, 12_827),
        "gap-closure-wayback": (12_828, 12_889),
        "fr-api": (12_890, 14_420),
    }
)

#: Why a verdict is `unknown`, named so a consumer counts these rather than
#: reading a miss as evidence of nonexistence.
UNKNOWN_REASONS = (
    #: Inside one of the affirm-only NARA windows, missing from the roster.
    #: A coverage hole, not a nonexistent number (EO 9397 is the specimen).
    "nara_window_miss",
    #: Below the first window or above FR_API_DENSE_MAX. This oracle makes
    #: no density claim in either region.
    "outside_known_windows",
)


def window_for(eo_number: int) -> str | None:
    """The declared window containing this number, or ``None`` for neither."""

    for name, (low, high) in WINDOWS.items():
        if low <= eo_number <= high:
            return name
    return None


@dataclass(frozen=True, slots=True)
class EoVerdict:
    """What the oracle can say about one Executive Order number.

    Every field is checked against every other one, because the failure this
    module exists to prevent is a verdict that reads coherent and is not:

    * ``window`` names what authorized the verdict, and must be the window
      that actually CONTAINS ``eo_number`` (or ``None`` when no window does).
      An earlier draft let the 32 gap rows claim ``"nara_codification"``
      while sitting above that window's top, so a consumer could receive an
      ``exists`` whose authorizing window did not contain the number.
    * ``absent`` additionally requires a window in :data:`ABSENT_CAPABLE`.
    * ``exists`` requires a ``source`` in :data:`SOURCE_RANGES` whose own
      declared range contains ``eo_number`` -- a roster row that names a
      capture which never saw that number cannot publish an existence claim.
    * ``reason`` is set if and only if the verdict is ``unknown``, and names
      which of the two coverage stories applies -- checked against the
      window, so "inside a sparse window" and "outside every window" can
      never be swapped. Mirrors :class:`refspec.registry.usc_section_oracle.
      SectionVerdict`'s invariant.
    """

    eo_number: int
    verdict: str
    window: str | None
    reason: str | None = None
    #: The roster row's own provenance tag where one exists (e.g.
    #: ``"gap-closure-wayback"``), ``None`` for `absent`/`unknown`. Carried
    #: so a caller can tell a Wayback-only exists apart from a live-page one
    #: -- see the module docstring's Durability note.
    source: str | None = None

    def __post_init__(self) -> None:
        if self.verdict not in VERDICTS:
            raise ValueError(f"undeclared verdict: {self.verdict!r}")
        if (self.verdict == "unknown") != (self.reason is not None):
            raise ValueError("an unknown verdict names its coverage gap, and no other verdict names one")
        if self.reason is not None and self.reason not in UNKNOWN_REASONS:
            raise ValueError(f"undeclared unknown reason: {self.reason!r}")

        containing = window_for(self.eo_number)
        if self.window is not None and self.window not in WINDOWS:
            raise ValueError(f"undeclared window: {self.window!r}")
        if self.window is not None and self.window != containing:
            raise ValueError(
                f"window {self.window!r} does not contain EO {self.eo_number}; "
                f"the window that does is {containing!r}"
            )

        if self.verdict in ("exists", "absent") and self.window is None:
            raise ValueError(f"{self.verdict} must name the window that authorized it, got None")
        if self.verdict == "absent" and self.window not in ABSENT_CAPABLE:
            raise ValueError("absent is only ever authorized by the fully-dense fr_api window")

        if self.verdict == "exists":
            if self.source is None:
                raise ValueError(f"an exists verdict must name the capture that witnessed EO {self.eo_number}")
            if self.source not in SOURCE_RANGES:
                raise ValueError(f"undeclared roster source: {self.source!r}")
            low, high = SOURCE_RANGES[self.source]
            if not low <= self.eo_number <= high:
                raise ValueError(
                    f"source {self.source!r} witnesses {low}-{high} and cannot vouch for EO {self.eo_number}"
                )
        elif self.source is not None:
            raise ValueError("only an exists verdict carries a roster source")

        if self.reason == "nara_window_miss" and self.window in (None, *ABSENT_CAPABLE):
            raise ValueError(
                f"nara_window_miss names a miss inside an affirm-only window, not {self.window!r}"
            )
        if self.reason == "outside_known_windows" and containing is not None:
            raise ValueError(
                f"outside_known_windows cannot describe EO {self.eo_number}, which falls in {containing!r}"
            )


def _verify_pinned_roster(directory: Path) -> bytes:
    """Return the pinned roster's bytes, refusing loudly on drift.

    The bytes are returned rather than the path on purpose: the caller parses
    exactly what was hashed. Hashing a path and then re-opening it leaves a
    window in which the file can change between the two reads, so the digest
    would vouch for bytes nobody parsed.
    """

    payload = (directory / _ROSTER_FILE).read_bytes()
    digest = f"sha256:{hashlib.sha256(payload).hexdigest()}"
    if digest != _ROSTER_PIN:
        raise ValueError(f"pinned EO roster drifted: expected={_ROSTER_PIN}, observed={digest}")
    return payload


def _verify_density(rows: Mapping[int, tuple[str, str]]) -> None:
    """Refuse a roster that does not back the absence claims this module makes.

    Two checks, both of which a re-pin could otherwise break silently:

    1. every integer in an :data:`ABSENT_CAPABLE` window is on the roster --
       the density that licenses `absent` is re-measured, never assumed; and
    2. every declared :data:`SOURCE_RANGES` entry matches what the roster's
       rows for that source actually span, so a range cannot be widened past
       the evidence to wave a number through :class:`EoVerdict`'s check.
    """

    for window in sorted(ABSENT_CAPABLE):
        low, high = WINDOWS[window]
        missing = [number for number in range(low, high + 1) if number not in rows]
        if missing:
            raise ValueError(
                f"the {window} window claims to be fully dense but the pinned roster misses "
                f"{len(missing)} number(s) in {low}-{high}, starting at {missing[0]}; "
                f"this module may not publish `absent` on evidence it does not have"
            )

    attained: dict[str, tuple[int, int]] = {}
    for number, (_, source) in rows.items():
        low, high = attained.get(source, (number, number))
        attained[source] = (min(low, number), max(high, number))
    if attained.keys() != SOURCE_RANGES.keys():
        raise ValueError(
            f"the pinned roster's sources are {sorted(attained)}, not the declared {sorted(SOURCE_RANGES)}"
        )
    for source, measured in sorted(attained.items()):
        if measured != tuple(SOURCE_RANGES[source]):
            raise ValueError(
                f"source {source!r} spans {measured} in the pinned roster but declares "
                f"{tuple(SOURCE_RANGES[source])}; a declared range must be measured, not chosen"
            )


@dataclass(frozen=True)
class EoRosterOracle:
    """The EO existence oracle, loaded from one digest-verified directory."""

    directory: Path

    @classmethod
    def from_directory(cls, directory: Path | str) -> EoRosterOracle:
        """Bind to a sealed roster directory, verifying its digest first."""

        oracle = cls(directory=Path(directory))
        oracle.verify()
        return oracle

    @classmethod
    def from_repository(cls, root: Path | str) -> EoRosterOracle:
        """Bind to the copy this repository carries."""

        return cls.from_directory(Path(root) / EO_ROSTER_ARTIFACT)

    def verify(self) -> None:
        """Hash the pinned roster. Called by :meth:`from_directory` first."""

        _verify_pinned_roster(self.directory)

    @cached_property
    def _rows(self) -> Mapping[int, tuple[str, str]]:
        """``eo_number -> (window, source)``, loaded from the pinned roster.

        Parsed from the very buffer the digest vouched for, then held to the
        same coherence :class:`EoVerdict` enforces: the roster is trusted
        data, but a trusted file that has been edited into an incoherent
        state must refuse to load rather than answer differently.
        """

        payload = _verify_pinned_roster(self.directory)
        rows: dict[int, tuple[str, str]] = {}
        for row in csv.DictReader(payload.decode("utf-8").splitlines()):
            number = int(row["eo_number"])
            window, source = row["window"], row["source"]
            if window != window_for(number):
                raise ValueError(
                    f"pinned roster row for EO {number} names window {window!r}, "
                    f"which does not contain it ({window_for(number)!r} does)"
                )
            rows[number] = (window, source)
        _verify_density(rows)
        return MappingProxyType(rows)

    def verdict(self, eo_number: int) -> EoVerdict:
        """The typed verdict for one number: exists / absent / unknown."""

        number = int(eo_number)
        hit = self._rows.get(number)
        if hit is not None:
            window, source = hit
            return EoVerdict(number, "exists", window, source=source)
        window = window_for(number)
        if window is None:
            return EoVerdict(number, "unknown", None, reason="outside_known_windows")
        if window in ABSENT_CAPABLE:
            return EoVerdict(number, "absent", window)
        return EoVerdict(number, "unknown", window, reason="nara_window_miss")

    @cached_property
    def max_eo(self) -> int:
        """The highest Executive Order number attested in this roster."""

        return max(self._rows)

    @property
    def max_plausible_number(self) -> int:
        """Default prose-validation ceiling (``max_eo + 200``)."""

        return self.max_eo + EO_PLAUSIBLE_HEADROOM

    def is_plausible_number(self, eo_number: int, *, headroom: int = EO_PLAUSIBLE_HEADROOM) -> bool:
        """Whether ``eo_number`` sits within ``1 <= N <= max_eo + headroom``."""

        if isinstance(eo_number, bool):
            raise TypeError("eo_number must be an integer, not bool")
        if headroom < 0:
            raise ValueError(f"headroom must be non-negative, got {headroom}")
        number = int(eo_number)
        return 1 <= number <= self.max_eo + headroom

    def validate_candidate(
        self,
        candidate: int | str,
        *,
        surrounding_text: str | None = None,
        span: tuple[int, int] | None = None,
        headroom: int = EO_PLAUSIBLE_HEADROOM,
    ) -> EoCandidateCheck:
        """Validate a prose or numeric Executive Order candidate against ceiling, path guards, and roster."""

        return _validate_eo_candidate(
            candidate,
            oracle=self,
            surrounding_text=surrounding_text,
            span=span,
            headroom=headroom,
        )

    def is_valid_candidate(
        self,
        candidate: int | str,
        *,
        surrounding_text: str | None = None,
        span: tuple[int, int] | None = None,
        headroom: int = EO_PLAUSIBLE_HEADROOM,
    ) -> bool:
        """Boolean convenience wrapper around :meth:`validate_candidate`."""

        return self.validate_candidate(
            candidate,
            surrounding_text=surrounding_text,
            span=span,
            headroom=headroom,
        ).is_valid

    def scan_text(
        self,
        text: str,
        *,
        headroom: int = EO_PLAUSIBLE_HEADROOM,
        deduplicate: bool = True,
    ) -> tuple[EoProseCitation, ...]:
        """Extract valid Executive Order citations from unstructured prose."""

        return find_executive_order_citations(text, oracle=self, headroom=headroom, deduplicate=deduplicate)

    @staticmethod
    def flag_for(eo_number: int) -> hand_validated_interpretations.Interpretation | None:
        """The hand-validated FLAG for this number, or ``None`` if none is recorded.

        Delegates to :func:`hand_validated_interpretations.lookup` rather than
        keeping a second copy of the same claim -- see that module's docstring
        and this module's own on EO 8284. Three properties this method holds,
        each with a test:

        * ``None`` means exactly "no hand-validated flag is recorded for this
          number" -- the table's :class:`~refspec.registry
          .hand_validated_interpretations.NotReviewed` is converted here
          rather than propagated, because "nobody reviewed it" is the normal
          case for an EO number and not an error a caller can act on;
        * a row whose disposition is anything but ``"flag"`` RAISES. A
          correction reaching a caller through a method named ``flag_for``
          would be a substitution arriving under a label that promises not to
          make one, and this oracle has no correction pathway at all;
        * a flag NEVER changes what :meth:`verdict` returns. It exists so a
          caller can surface hand-reviewed doubt ALONGSIDE an honest verdict,
          never instead of it -- EO 8284 is `exists` AND flagged.
        """

        try:
            row = hand_validated_interpretations.lookup(str(int(eo_number)))
        except hand_validated_interpretations.NotReviewed:
            return None
        if row.disposition != "flag":
            raise hand_validated_interpretations.HandValidatedRegistryError(
                f"the hand-validated row for {row.source_value!r} is a {row.disposition!r}, not a flag; "
                f"flag_for() will not hand one back under a name that promises a flag -- read it through "
                f"hand_validated_interpretations.lookup and decide there"
            )
        return row


# --------------------------------------------------------------------------- #
# Prose candidate validation & XML/file-path false-positive guards
# --------------------------------------------------------------------------- #

_EO_DASH_MAP = str.maketrans(dict.fromkeys("‐‑‒–—―−\x96\x97", "-"))
_EO_PARAGRAPH_BREAK_RE = re.compile(r"\r?\n[ \t]*\r?\n")

_EO_CANDIDATE_LABEL_RE = re.compile(
    r"^(?:"
    r"(?i:Executive\s+Orders?|Exec\.?\s*(?:Orders?|Ord\.?))"
    r"|(?:EOs?\.?|E\.\s*O\.?s?)"
    r")\s*(?i:Nos?\.?\s*)?(?P<num>-?\d+)\.?$"
)
_EO_PATH_SUFFIX_RE = re.compile(r"\.[A-Za-z0-9]{1,8}(?:\.[A-Za-z0-9]{1,8})*$")

_EO_PROSE_SPELLED_RE = re.compile(
    r"(?<![0-9A-Za-z_\\/:])(?P<lbl>Executive\s+Orders?|Exec\.?\s*(?:Orders?|Ord\.?))\s*(?P<no>Nos?\.?\s*)?"
    r"(?P<num>[1-9]\d*)(?![0-9A-Za-z_\\/])(?!\.[0-9A-Za-z])",
    re.IGNORECASE,
)
_EO_PROSE_ABBR_RE = re.compile(
    r"(?<![0-9A-Za-z_\\/:])(?P<lbl>EOs?\.?|E\.\s*O\.?s?)\s*(?P<no>(?i:Nos?\.?)\s*)?"
    r"(?P<num>[1-9]\d*)(?![0-9A-Za-z_\\/])(?!\.[0-9A-Za-z])"
)
_EO_PROSE_TAIL_PLURAL_RE = re.compile(
    r"\s*(?:,\s*(?:and\s+)?|\s+and\s+)"
    r"(?P<num>[1-9]\d*)(?![0-9A-Za-z_\\/])(?!\.[0-9A-Za-z])"
    r"(?!\s*(?i:FR\b|Fed\.?\s*Reg|C\.?\s*F\.?\s*R|U\.?\s*S\.?\s*C|Stat\b))"
)
_EO_PROSE_TAIL_SINGULAR_RE = re.compile(
    r"\s*(?:,\s*(?:and\s+)?|\s+and\s+)"
    r"(?P<num>[1-9]\d{3,})(?![0-9A-Za-z_\\/])(?!\.[0-9A-Za-z])"
    r"(?!\s*(?i:FR\b|Fed\.?\s*Reg|C\.?\s*F\.?\s*R|U\.?\s*S\.?\s*C|Stat\b))"
)


def _eo_match_is_plural(match: re.Match[str]) -> bool:
    lbl = (match.group("lbl") or "").rstrip(".").lower()
    no_lbl = (match.group("no") or "").strip().rstrip(".").lower()
    return lbl.endswith("s") or no_lbl.endswith("s")


@dataclass(frozen=True, slots=True)
class EoCandidateCheck:
    """Result of validating an Executive Order candidate against ceiling, path guards, and roster."""

    eo_number: int | None
    is_valid: bool
    verdict: EoVerdict | None = None
    rejection_reason: str | None = None

    def __post_init__(self) -> None:
        if self.is_valid != (self.rejection_reason is None):
            raise ValueError("a valid candidate carries no rejection_reason, and a rejected candidate must name one")
        if self.rejection_reason is not None and self.rejection_reason not in CANDIDATE_REJECTION_REASONS:
            raise ValueError(f"undeclared candidate rejection reason: {self.rejection_reason!r}")
        if self.is_valid and (self.eo_number is None or self.eo_number < 1):
            raise ValueError("a valid EO candidate must carry a positive integer eo_number")


@dataclass(frozen=True, slots=True)
class EoProseCitation:
    """One validated Executive Order citation extracted from unstructured prose."""

    eo_number: int
    surface: str
    start: int
    end: int
    verdict: EoVerdict | None = None


def _span_has_path_or_homoglyph_trap(text: str, start: int, end: int) -> str | None:
    """Inspect characters surrounding ``text[start:end]`` for path separators, extensions, or ``E0`` homoglyphs."""

    if start < 0 or end > len(text) or start >= end:
        return None
    segment = text[start:end]
    if "\\" in segment or "/" in segment:
        return "xml_or_file_path"
    if start > 0 and text[start - 1] in "\\/:_":
        return "xml_or_file_path"
    if end < len(text):
        nxt = text[end]
        if nxt in "\\/_":
            return "xml_or_file_path"
        if nxt == "." and end + 1 < len(text) and text[end + 1].isalnum():
            return "xml_or_file_path"
    if re.search(r"(?<![A-Za-z])E0\s*\d", segment):
        return "zero_homoglyph_or_malformed_label"
    prefix = text[max(0, start - 6) : start]
    if re.search(r"[\\/:]\s*$", prefix):
        return "xml_or_file_path"
    if re.search(r"(?<![A-Za-z])E0\s*$", prefix):
        return "zero_homoglyph_or_malformed_label"
    return None


def _context_rejection_for_number(eo_number: int, surrounding_text: str, span: tuple[int, int] | None) -> str | None:
    """Check ``surrounding_text`` for XML/file-path or ``E0`` homoglyph traps around ``eo_number``."""

    norm = surrounding_text.translate(_EO_DASH_MAP)
    if span is not None:
        return _span_has_path_or_homoglyph_trap(norm, span[0], span[1])

    # If the surrounding prose carries a genuine EO citation for this number, accept the context.
    for match in (*_EO_PROSE_SPELLED_RE.finditer(norm), *_EO_PROSE_ABBR_RE.finditer(norm)):
        if int(match.group("num")) == eo_number:
            return None
        tail_re = _EO_PROSE_TAIL_PLURAL_RE if _eo_match_is_plural(match) else _EO_PROSE_TAIL_SINGULAR_RE
        pos = match.end()
        while (tail := tail_re.match(norm, pos)) is not None:
            if _EO_PARAGRAPH_BREAK_RE.search(norm, pos, tail.end()):
                break
            if int(tail.group("num")) == eo_number:
                return None
            pos = tail.end()

    # Otherwise check whether the number appears inside a path/XML token, leading-zero run, or E0 homoglyph.
    reasons_seen: list[str] = []
    for num_match in re.finditer(rf"(?<!\d)0*{eo_number}(?!\d)", norm):
        ns, ne = num_match.start(), num_match.end()
        token_s = ns
        while token_s > 0 and not norm[token_s - 1].isspace() and norm[token_s - 1] not in ",;()[]\"'":
            token_s -= 1
        token_e = ne
        while token_e < len(norm) and not norm[token_e].isspace() and norm[token_e] not in ",;()[]\"'":
            token_e += 1
        enclosing = norm[token_s:token_e].rstrip(".")
        if "\\" in enclosing or "/" in enclosing or ":" in enclosing or _EO_PATH_SUFFIX_RE.search(enclosing[ne - token_s :]):
            reasons_seen.append("xml_or_file_path")
            continue
        before = norm[max(0, ns - 8) : ns]
        if re.search(r"(?<![A-Za-z])E0\s*$", before):
            reasons_seen.append("zero_homoglyph_or_malformed_label")
            continue
        if num_match.group(0).startswith("0"):
            reasons_seen.append("leading_zero")
    return reasons_seen[0] if reasons_seen else None


def _validate_eo_candidate(
    candidate: int | str,
    *,
    oracle: EoRosterOracle | None = None,
    surrounding_text: str | None = None,
    span: tuple[int, int] | None = None,
    headroom: int = EO_PLAUSIBLE_HEADROOM,
) -> EoCandidateCheck:
    if isinstance(candidate, bool):
        raise TypeError("candidate must be an int or str, not bool")
    if headroom < 0:
        raise ValueError(f"headroom must be non-negative, got {headroom}")

    if isinstance(candidate, str):
        cleaned = candidate.translate(_EO_DASH_MAP).strip()
        if not cleaned:
            return EoCandidateCheck(None, False, None, "zero_homoglyph_or_malformed_label")
        if "\\" in cleaned or "/" in cleaned or ":" in cleaned:
            return EoCandidateCheck(None, False, None, "xml_or_file_path")
        # Dotted suffix after digits (e.g. "EO12866.xml", "E043025.003.xml", "E.O. 12866.003") is a file/slug token;
        # a single trailing sentence period ("E.O. 12866.") has nothing after the dot and is allowed.
        if re.search(r"\d\.[A-Za-z0-9]", cleaned) or "_" in cleaned:
            return EoCandidateCheck(None, False, None, "xml_or_file_path")

        bare_int = re.fullmatch(r"(-?\d+)\.?", cleaned)
        if bare_int is not None:
            digits = bare_int.group(1)
            if digits.startswith("-") or int(digits) <= 0:
                return EoCandidateCheck(int(digits), False, None, "non_positive_number")
            if digits.startswith("0"):
                return EoCandidateCheck(int(digits), False, None, "leading_zero")
            eo_num = int(digits)
        else:
            labeled = _EO_CANDIDATE_LABEL_RE.fullmatch(cleaned)
            if labeled is None:
                return EoCandidateCheck(None, False, None, "zero_homoglyph_or_malformed_label")
            digits = labeled.group("num")
            if digits.startswith("-") or int(digits) <= 0:
                return EoCandidateCheck(int(digits), False, None, "non_positive_number")
            if digits.startswith("0"):
                return EoCandidateCheck(int(digits), False, None, "leading_zero")
            eo_num = int(digits)
    else:
        eo_num = int(candidate)
        if eo_num <= 0:
            return EoCandidateCheck(eo_num, False, None, "non_positive_number")

    if surrounding_text is not None:
        ctx_rejection = _context_rejection_for_number(eo_num, surrounding_text, span)
        if ctx_rejection is not None:
            return EoCandidateCheck(eo_num, False, None, ctx_rejection)

    verdict = oracle.verdict(eo_num) if oracle is not None else None
    ceiling = (oracle.max_eo if oracle is not None else FR_API_DENSE_MAX) + headroom
    if eo_num > ceiling and (verdict is None or verdict.verdict != "exists"):
        return EoCandidateCheck(eo_num, False, verdict, "exceeds_plausible_ceiling")
    if verdict is not None and verdict.verdict == "absent":
        return EoCandidateCheck(eo_num, False, verdict, "absent_in_dense_window")
    return EoCandidateCheck(eo_num, True, verdict, None)


def is_valid_eo_candidate(
    candidate: int | str,
    *,
    oracle: EoRosterOracle | None = None,
    surrounding_text: str | None = None,
    span: tuple[int, int] | None = None,
    headroom: int = EO_PLAUSIBLE_HEADROOM,
) -> bool:
    """Whether ``candidate`` passes ceiling, XML/file-path, and optional ``oracle`` checks."""

    return _validate_eo_candidate(
        candidate,
        oracle=oracle,
        surrounding_text=surrounding_text,
        span=span,
        headroom=headroom,
    ).is_valid


def find_executive_order_citations(
    text: str,
    *,
    oracle: EoRosterOracle | None = None,
    headroom: int = EO_PLAUSIBLE_HEADROOM,
    deduplicate: bool = True,
) -> tuple[EoProseCitation, ...]:
    """Extract valid Executive Order citations from unstructured prose with ceiling and path guards."""

    if not text:
        return ()
    if headroom < 0:
        raise ValueError(f"headroom must be non-negative, got {headroom}")
    norm = str(text).translate(_EO_DASH_MAP)
    ceiling = (oracle.max_eo if oracle is not None else FR_API_DENSE_MAX) + headroom

    raw_hits: list[EoProseCitation] = []
    for pattern in (_EO_PROSE_SPELLED_RE, _EO_PROSE_ABBR_RE):
        for match in pattern.finditer(norm):
            candidates: list[tuple[int, int, int]] = [(int(match.group("num")), match.start(), match.end())]
            tail_re = _EO_PROSE_TAIL_PLURAL_RE if _eo_match_is_plural(match) else _EO_PROSE_TAIL_SINGULAR_RE
            pos = match.end()
            while (tail := tail_re.match(norm, pos)) is not None:
                if _EO_PARAGRAPH_BREAK_RE.search(norm, pos, tail.end()):
                    break
                candidates.append((int(tail.group("num")), tail.start("num"), tail.end()))
                pos = tail.end()
            for eo_num, s_off, e_off in candidates:
                if _span_has_path_or_homoglyph_trap(norm, s_off, e_off) is not None:
                    continue
                verdict = oracle.verdict(eo_num) if oracle is not None else None
                if eo_num < 1 or (eo_num > ceiling and (verdict is None or verdict.verdict != "exists")):
                    continue
                if verdict is not None and verdict.verdict == "absent":
                    continue
                raw_hits.append(EoProseCitation(eo_num, text[s_off:e_off], s_off, e_off, verdict))

    raw_hits.sort(key=lambda item: (item.start, item.end))
    if not deduplicate:
        return tuple(raw_hits)
    seen: set[int] = set()
    unique: list[EoProseCitation] = []
    for hit in raw_hits:
        if hit.eo_number not in seen:
            seen.add(hit.eo_number)
            unique.append(hit)
    return tuple(unique)

