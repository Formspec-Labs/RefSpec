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
from functools import cached_property, lru_cache
from pathlib import Path
from types import MappingProxyType

from refspec.registry import hand_validated_interpretations

__all__ = [
    "ABSENT_CAPABLE",
    "CANDIDATE_REJECTION_REASONS",
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
    "EoRosterOracle",
    "EoVerdict",
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

CANDIDATE_REJECTION_REASONS = (
    "xml_or_file_path",
    "zero_homoglyph_or_malformed_label",
    "leading_zero",
    "non_positive_number",
    "implausible_digit_length",
    "above_roster_max",
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

    def validate_candidate(
        self,
        candidate: int | str,
        *,
        surrounding_text: str | None = None,
        span: tuple[int, int] | None = None,
    ) -> EoCandidateCheck:
        """Validate a prose or numeric Executive Order candidate against path guards and this roster."""

        return _validate_eo_candidate(
            candidate,
            oracle=self,
            surrounding_text=surrounding_text,
            span=span,
        )

    def is_valid_candidate(
        self,
        candidate: int | str,
        *,
        surrounding_text: str | None = None,
        span: tuple[int, int] | None = None,
    ) -> bool:
        """Boolean convenience wrapper around :meth:`validate_candidate`."""

        return self.validate_candidate(
            candidate,
            surrounding_text=surrounding_text,
            span=span,
        ).is_valid

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
# Candidate validation & XML/file-path/homoglyph false-positive guards
# --------------------------------------------------------------------------- #

_EO_DASH_MAP = str.maketrans(dict.fromkeys("‐‑‒–—―−\x96\x97", "-"))
_EO_TOKEN_DELIMITERS = frozenset(",;()[]{}<>\"'")
_EO_DIGIT_RUN_RE = re.compile(r"\d+")
_EO_DOTTED_FILE_SUFFIX_RE = re.compile(r"\d\.[A-Za-z0-9]")
_EO_ZERO_HOMOGLYPH_INLINE_RE = re.compile(r"(?<![A-Za-z0-9])E0\s*\d")
_EO_ZERO_HOMOGLYPH_LABEL_RE = re.compile(r"(?<![A-Za-z0-9])E0\.?$")
_EO_PRECEDING_LABEL_TAIL_RE = re.compile(r"(?:(?i:orders?|ord\.?)|EOs?\.?|E\.O\.?s?|E0\.?)$")
_EO_CLEAN_PRECEDING_LABEL_RE = re.compile(
    r"(?:(?i:Executive\s+Orders?|Exec\.?\s*(?:Orders?|Ord\.?))|EOs?\.?|E\.\s*O\.?s?)\s*(?i:Nos?\.?\s*)?$"
)
_EO_CANDIDATE_LABEL_RE = re.compile(
    r"^(?:"
    r"(?i:Executive\s+Orders?|Exec\.?\s*(?:Orders?|Ord\.?))"
    r"|(?:EOs?\.?|E\.\s*O\.?s?)"
    r")\s*(?i:Nos?\.?\s*)?(?P<num>-?\d+)\.?$"
)
_MAX_EO_DIGITS_STRUCTURAL = 99_999


@dataclass(frozen=True, slots=True)
class EoCandidateCheck:
    """Result of validating an Executive Order candidate against path guards and roster bounds."""

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


def _expand_enclosing_token(norm: str, start: int, end: int) -> tuple[int, int]:
    tok_s = start
    while tok_s > 0 and not norm[tok_s - 1].isspace() and norm[tok_s - 1] not in _EO_TOKEN_DELIMITERS:
        tok_s -= 1
    tok_e = end
    while tok_e < len(norm) and not norm[tok_e].isspace() and norm[tok_e] not in _EO_TOKEN_DELIMITERS:
        tok_e += 1
    return tok_s, tok_e


def _preceding_horizontal_token(norm: str, pos: int) -> tuple[str, int]:
    idx = pos
    while idx > 0 and norm[idx - 1] in " \t":
        idx -= 1
    if idx == 0 or norm[idx - 1].isspace() or norm[idx - 1] in _EO_TOKEN_DELIMITERS:
        return "", idx
    end = idx
    while idx > 0 and not norm[idx - 1].isspace() and norm[idx - 1] not in _EO_TOKEN_DELIMITERS:
        idx -= 1
    return norm[idx:end], idx


def _inspect_span_in_context(norm: str, start: int, end: int, eo_number: int) -> str | None:
    """Uniformly inspect ``norm[start:end]`` and its enclosing token for path, homoglyph, and leading-zero traps."""

    tok_s, tok_e = _expand_enclosing_token(norm, start, end)
    enclosing_stripped = norm[tok_s:tok_e].rstrip(".")
    if any(ch in enclosing_stripped for ch in "\\/_:") or _EO_DOTTED_FILE_SUFFIX_RE.search(enclosing_stripped):
        return "xml_or_file_path"
    if _EO_ZERO_HOMOGLYPH_INLINE_RE.search(enclosing_stripped):
        return "zero_homoglyph_or_malformed_label"

    prev_tok, prev_s = _preceding_horizontal_token(norm, tok_s)
    if prev_tok.rstrip(".").lower() in {"no", "nos"}:
        prev_tok, prev_s = _preceding_horizontal_token(norm, prev_s)
    if prev_tok and _EO_PRECEDING_LABEL_TAIL_RE.search(prev_tok):
        if any(ch in prev_tok for ch in "\\/_") or ":" in prev_tok.rstrip(":"):
            return "xml_or_file_path"
        if _EO_ZERO_HOMOGLYPH_LABEL_RE.search(prev_tok):
            return "zero_homoglyph_or_malformed_label"
    elif prev_tok and _EO_ZERO_HOMOGLYPH_LABEL_RE.search(prev_tok):
        return "zero_homoglyph_or_malformed_label"

    for digit_match in _EO_DIGIT_RUN_RE.finditer(enclosing_stripped):
        digits = digit_match.group(0)
        if int(digits) == eo_number and digits.startswith("0"):
            return "leading_zero"
    return None


@lru_cache(maxsize=8)
def _index_eo_context(surrounding_text: str) -> tuple[str, tuple[tuple[int, int, int], ...]]:
    norm = surrounding_text.translate(_EO_DASH_MAP)
    runs = tuple((int(m.group(0)), m.start(), m.end()) for m in _EO_DIGIT_RUN_RE.finditer(norm))
    return norm, runs


def _context_rejection_for_number(
    eo_number: int,
    surrounding_text: str,
    span: tuple[int, int] | None,
) -> str | None:
    """Check ``surrounding_text`` for XML/file-path, leading-zero, or ``E0`` homoglyph traps around ``eo_number``."""

    norm, runs = _index_eo_context(surrounding_text)
    if span is not None:
        if (
            not isinstance(span, tuple)
            or len(span) != 2
            or any(isinstance(x, bool) or not isinstance(x, int) for x in span)
        ):
            raise TypeError("span must be a (start, end) tuple of ints")
        start, end = span
        if start < 0 or end > len(norm) or start >= end:
            raise ValueError(f"span {span!r} is out of bounds for surrounding_text of length {len(norm)}")
        return _inspect_span_in_context(norm, start, end, eo_number)

    reasons_seen: list[str] = []
    saw_clean_labeled = False
    for run_val, ns, ne in runs:
        if run_val != eo_number:
            continue
        trap = _inspect_span_in_context(norm, ns, ne, eo_number)
        if trap is not None:
            reasons_seen.append(trap)
            continue
        before = norm[max(0, ns - 36) : ns]
        if _EO_CLEAN_PRECEDING_LABEL_RE.search(before):
            saw_clean_labeled = True
    if saw_clean_labeled:
        return None
    return reasons_seen[0] if reasons_seen else None


def _validate_eo_candidate(
    candidate: int | str,
    *,
    oracle: EoRosterOracle | None = None,
    surrounding_text: str | None = None,
    span: tuple[int, int] | None = None,
) -> EoCandidateCheck:
    if isinstance(candidate, bool) or not isinstance(candidate, (int, str)):
        raise TypeError(f"candidate must be an int or str, got {type(candidate).__name__}")
    if span is not None and surrounding_text is None:
        raise ValueError("span requires surrounding_text")

    if isinstance(candidate, str):
        cleaned = candidate.translate(_EO_DASH_MAP).strip()
        if not cleaned:
            return EoCandidateCheck(None, False, None, "zero_homoglyph_or_malformed_label")
        if any(ch in cleaned for ch in "\\/_:") or _EO_DOTTED_FILE_SUFFIX_RE.search(cleaned):
            return EoCandidateCheck(None, False, None, "xml_or_file_path")

        bare_int = re.fullmatch(r"(-?\d+)\.?", cleaned)
        if bare_int is not None:
            digits = bare_int.group(1)
        else:
            labeled = _EO_CANDIDATE_LABEL_RE.fullmatch(cleaned)
            if labeled is None:
                return EoCandidateCheck(None, False, None, "zero_homoglyph_or_malformed_label")
            digits = labeled.group("num")

        eo_num = int(digits)
        if digits.startswith("-") or eo_num <= 0:
            return EoCandidateCheck(eo_num, False, None, "non_positive_number")
        if digits.startswith("0"):
            return EoCandidateCheck(eo_num, False, None, "leading_zero")
    else:
        eo_num = candidate
        if eo_num <= 0:
            return EoCandidateCheck(eo_num, False, None, "non_positive_number")

    if surrounding_text is not None:
        ctx_rejection = _context_rejection_for_number(eo_num, surrounding_text, span)
        if ctx_rejection is not None:
            return EoCandidateCheck(eo_num, False, None, ctx_rejection)

    verdict = oracle.verdict(eo_num) if oracle is not None else None
    if eo_num > _MAX_EO_DIGITS_STRUCTURAL:
        return EoCandidateCheck(eo_num, False, verdict, "implausible_digit_length")
    if oracle is not None and eo_num > oracle.max_eo and (verdict is None or verdict.verdict != "exists"):
        return EoCandidateCheck(eo_num, False, verdict, "above_roster_max")
    if verdict is not None and verdict.verdict == "absent":
        return EoCandidateCheck(eo_num, False, verdict, "absent_in_dense_window")
    return EoCandidateCheck(eo_num, True, verdict, None)


def is_valid_eo_candidate(
    candidate: int | str,
    *,
    oracle: EoRosterOracle | None = None,
    surrounding_text: str | None = None,
    span: tuple[int, int] | None = None,
) -> bool:
    """Whether ``candidate`` passes XML/file-path/homoglyph guards and optional ``oracle`` checks."""

    return _validate_eo_candidate(
        candidate,
        oracle=oracle,
        surrounding_text=surrounding_text,
        span=span,
    ).is_valid

