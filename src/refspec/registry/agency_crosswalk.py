"""Federal Register agency <-> regulations.gov agency-code crosswalk.

RefSpec intake ledger port 1.5
(``plans/2026-08-31-refspec-intake-ledger.md`` section 1.5). The reference
implementation is spicy-regs' ``tools/build_agency_crosswalk_artifact.py``
(preserved at
``~/Work/corpora/_nuggets-2026-08-27/source/tools/build_agency_crosswalk_artifact.py``),
which joined 1,004,233 Federal Register documents, 276,326 regulations.gov
dockets, 715,080 FR-to-docket link rows, and 1,987,880 regulations.gov
documents into one artifact answering: which Federal Register agency slug
(``agencies_json``, e.g. ``federal-aviation-administration``) does a given
regulations.gov agency *code* (``agency_code``, e.g. ``FAA``, the docket-ID
prefix) stand for? The sealed build ran 2026-08-02 and is preserved at
``~/Work/corpora/_preserved-2026-08-27/spicy-regs-output-complete/
agency-crosswalk-2026-08-02/`` (``receipt.json`` artifact_id
``urn:spicyregs:agency-crosswalk-artifact:80864133d2e5d484fef4afd0``).

**Decision-tree branch taken: curated data, not re-derivation (branch 3).**
The ledger's instruction was to re-derive the crosswalk from raw inputs if
they are available locally, or ship the sealed mapping as curated reference
data with the rules documented if not. Verified 2026-08-31 against
``~/Work/corpora/_preserved-2026-08-27/rin-ontology-revision-candidate/``,
the exact path the sealed receipt names as its inputs:

* ``federal_register.parquet``, ``dockets.parquet``, and ``documents.parquet``
  are byte-identical to the receipt's pinned sha256 digests (see
  ``AGENCY_CROSSWALK_INPUT_DIGESTS``).
* ``fr_docket_links.parquet`` is **not**. The file at that path has been
  overwritten since the 2026-08-02 10:52 build: 893,766 rows against the
  pinned 715,080, a materially different schema (it now carries full
  document metadata columns alongside ``docket_id``/``document_number``), and
  a different sha256 (``sha256:e55cc0ab...`` where the receipt pins
  ``sha256:b3409f0a...``). This matches the codebase's own observed failure
  mode for gitignored corpora output trees: loss/overwrite, not tamper.

A from-scratch rebuild against the three matching inputs plus the *current*
``fr_docket_links.parquet`` was attempted as a measurement (not shipped as
code: this module does not re-run the join). It reproduces
confident:124 / probable:30 / ambiguous:23 / unmapped:139 -- one agency code
short of the sealed confident:124 / probable:29 / ambiguous:23 / unmapped:140.
Close, but not the exact reproduction branch 2 would require, because one of
the four raw inputs is not the one that built the receipt. That near-miss is
recorded here rather than papered over: see
``AGENCY_CROSSWALK_REGENERATION_STATUS``.

Because exact re-derivation is not currently possible, ``AGENCY_CROSSWALK``
below ships the sealed artifact's ``agency-codes.parquet`` (316 rows -- every
regulations.gov agency code the sealed build's ``documents`` table evidence
touched) and ``agency-crosswalk.parquet`` (914 rows -- every ranked
FR-slug candidate behind those 316 codes) as curated reference data, exactly
as this registry already carries other small curated tables.
``AGENCY_CROSSWALK_TIER_HISTOGRAM`` pins the sealed receipt's own accounting,
not a fresh derivation, and ``tier_histogram()`` checks the shipped data
still adds up to it.

**The three measured rules**, load-bearing enough that the reference
builder's docstring names them explicitly, and reimplemented here (not
imported, not copied) as small, data-independent functions so each has a
test that breaks if the rule is violated:

1. **No docket-prefix inference.** An agency code is read only from the
   ``agency_code`` *field* on the ``dockets``/``documents`` tables, never
   parsed from a docket ID's leading letters. 579,669 of 715,080 real
   FR-docket-link rows in the sealed build carry docket-like strings that are
   not regulations.gov dockets at all (``FRL-...`` Federal Register document
   numbers, ``REG-100163-00`` Treasury regulation-project numbers, compound
   strings like ``"CMS-0003-F and CMS-0005-F"`` naming two dockets in one
   field) -- a prefix guess would either fabricate a code that does not exist
   or silently misjoin a malformed compound string. See
   ``resolve_docket_agency_code``.
2. **Decorated-ID normalization only when it resolves to a unique docket.**
   The Federal Register's docket references carry decorations
   (``"Docket No. FAA-2026-3485"``) that the regulations.gov dockets spine
   does not; ``normalize_docket_id`` strips them, but a normalized key that
   matches more than one raw docket id is refused (``status="ambiguous"``),
   never guessed. In the sealed build this recovered 88,073 of 715,080 link
   rows with zero collisions; a real-data slow test below confirms the same
   zero-collision result still holds over the byte-identical ``dockets.parquet``.
3. **0.05-share sub-agency preference.** A sub-agency and its parent
   department routinely both get named on the same documents, so both can
   reach a high raw share; ``rank_crosswalk_candidates`` treats candidates
   within ``SPECIFICITY_MARGIN`` (0.05) of the best share as tied and breaks
   the tie toward the deeper (more specific) slug -- e.g. code ``FAA``
   resolves to ``federal-aviation-administration`` (share 0.999056) over its
   parent ``transportation-department`` (share 0.999843), because the 0.000787
   gap is inside the margin. Outside the margin the rule does not fire: code
   ``BOEM`` resolves to ``interior-department`` (share 1.0), not the deeper
   ``ocean-energy-management-bureau`` (share 0.935103), because that 0.0649
   gap exceeds 0.05.

Tiering itself is share-and-support, both pinned as ``CONFIDENT_SHARE`` /
``PROBABLE_SHARE`` / ``MIN_CONFIDENT_DOCUMENTS`` / ``MIN_PROBABLE_DOCUMENTS``:
confident is a primary share >= 0.8 over >= 5 supporting documents; probable
is >= 0.6 over >= 2; ambiguous is any code with evidence meeting neither;
unmapped is a code the join never reached. Ambiguous and unmapped codes stay
in ``AGENCY_CROSSWALK``, marked, rather than being dropped.

Importing this module performs no network access and no big-data read; the
real-corpora cross-checks below run only under ``pytest.mark.slow`` and skip
cleanly when the corpora checkout is not present on the machine.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal

# --------------------------------------------------------------------------
# Provenance constants -- where this data came from, and its known gaps.
# --------------------------------------------------------------------------

AGENCY_CROSSWALK_REFERENCE_BUILDER = (
    "~/Work/corpora/_nuggets-2026-08-27/source/tools/build_agency_crosswalk_artifact.py"
)
AGENCY_CROSSWALK_SEALED_RECEIPT_PATH = (
    "~/Work/corpora/_preserved-2026-08-27/spicy-regs-output-complete/"
    "agency-crosswalk-2026-08-02/receipt.json"
)
AGENCY_CROSSWALK_SEALED_ARTIFACT_ID = "urn:spicyregs:agency-crosswalk-artifact:80864133d2e5d484fef4afd0"
AGENCY_CROSSWALK_REGENERATION_INPUTS = (
    "~/Work/corpora/_preserved-2026-08-27/rin-ontology-revision-candidate/"
)

#: The receipt's own pinned sha256 for each of the four raw inputs it joined.
#: Verified 2026-08-31 against AGENCY_CROSSWALK_REGENERATION_INPUTS: three of
#: four match; see AGENCY_CROSSWALK_REGENERATION_STATUS for the one that does not.
AGENCY_CROSSWALK_INPUT_DIGESTS: Mapping[str, str] = {
    "federal_register.parquet": "sha256:ac18315faa8be4a8d3656e758597d672c5d85c23cc6f8fde0ac53c9295b22bf2",
    "dockets.parquet": "sha256:b14cd488b7898391cff448ac4de19f85936072dcb1aa105da32eea88e6fd7938",
    "fr_docket_links.parquet": "sha256:b3409f0ada792a8c9534edcf87c290a8b39e482e4803f08656bfa9de4504fd45",
    "documents.parquet": "sha256:52f085f9ec2ee0c08fe3fb59bcd789bfef34000f87608ea36af9a6adbacfb04d",
}
AGENCY_CROSSWALK_INPUT_ROW_COUNTS: Mapping[str, int] = {
    "federal_register.parquet": 1_004_233,
    "dockets.parquet": 276_326,
    "fr_docket_links.parquet": 715_080,
    "documents.parquet": 1_987_880,
}

AGENCY_CROSSWALK_REGENERATION_STATUS = (
    "As of 2026-08-31, federal_register.parquet, dockets.parquet, and "
    "documents.parquet under AGENCY_CROSSWALK_REGENERATION_INPUTS match "
    "AGENCY_CROSSWALK_INPUT_DIGESTS byte-for-byte. fr_docket_links.parquet "
    "does not: the file at that path now holds 893,766 rows (pinned: "
    "715,080) with additional document-metadata columns, sha256:e55cc0ab... "
    "(pinned: sha256:b3409f0a...). A rebuild against the current file "
    "reproduces confident:124 / probable:30 / ambiguous:23 / unmapped:139 -- "
    "one code short of AGENCY_CROSSWALK_TIER_HISTOGRAM's sealed "
    "confident:124 / probable:29 / ambiguous:23 / unmapped:140. This module "
    "therefore ships the sealed mapping as curated data (decision-tree "
    "branch 3) rather than re-deriving it."
)

# --------------------------------------------------------------------------
# Rule 2: docket-id normalization, refused when ambiguous.
# --------------------------------------------------------------------------

#: Decoration must be followed by whitespace, a colon, or the counter word's
#: own period, so a real identifier like ``DOC-2005-0010`` cannot be
#: truncated into a false match -- and neither can ``Docket NOS-2020-0001``,
#: whose organization really is the National Ocean Service: the zero-space
#: form is licensed only when the counter word states its period.
#:
#: DELIBERATE DIVERGENCE from the sealed spelling (xhigh review catch,
#: 2026-08-31). The 2026-08-02 build's pattern required whitespace/colon
#: after an optional period and knew no plural, so ``Docket Nos. FDA-...``
#: half-stripped to ``NOS.FDA-...`` and ``Docket No.CDC-2018-0075`` to
#: ``NO.CDC-...`` -- both then resolved not_found against dockets that are
#: in the table. The correction is strictly additive (two more decoration
#: forms strip; every previously stripped form normalizes identically), its
#: only failure mode was silent recall loss, and the one sealed claim that
#: can still be re-verified -- zero normalized-key collisions over the
#: byte-identical 276,326 dockets -- holds under this spelling too. The
#: sealed recall figure (88,073 of 715,080) remains the sealed rule's own
#: measurement; the links input needed to re-measure it is lost
#: (AGENCY_CROSSWALK_REGENERATION_STATUS).
DOCKET_DECORATION_PATTERN = (
    r"^\s*(?:(?:docket|doc\.?)\s*(?:no(?:s)?|number(?:s)?)(?:\.[\s:]*|[\s:]+)|docket\.?[\s:]+)"
)
DOCKET_NORMALIZATION_RULES = (
    "strip_leading_docket_decorations",
    "remove_internal_whitespace",
    "uppercase",
)
_DOCKET_DECORATION = re.compile(DOCKET_DECORATION_PATTERN, re.IGNORECASE)
_INTERNAL_WHITESPACE = re.compile(r"\s+")


def normalize_docket_id(value: object) -> str:
    """Reduce a docket reference to its comparison key.

    A key, not an identifier: this answers "what do I compare it against?"
    and refuses nothing on its own -- a key that matches no docket is just a
    key that matches no docket. Comparing is not identifying; a key that
    names more than one docket is a collision :func:`resolve_docket_agency_code`
    quarantines, never resolves. Applies :data:`DOCKET_NORMALIZATION_RULES` in
    order: strip leading Federal Register docket decorations (repeatedly,
    since some references carry two), remove internal whitespace, uppercase.
    Returns ``""`` when nothing survives.

    Measured in the sealed 2026-08-02 build across 276,326 real dockets:
    88,073 of 715,080 FR-docket-link rows recovered, zero normalized keys
    covering two dockets.
    """
    text = "" if value is None else str(value).strip()
    if not text:
        return ""
    previous = None
    while previous != text:
        previous = text
        text = _DOCKET_DECORATION.sub("", text).strip()
    return _INTERNAL_WHITESPACE.sub("", text).upper()


def build_normalized_docket_index(docket_codes: Mapping[str, str]) -> dict[str, frozenset[str]]:
    """Group raw docket ids by their normalized comparison key.

    Build this once per batch of lookups and pass it to
    :func:`resolve_docket_agency_code` as ``index`` -- omitting it rebuilds
    the index on every call, which is fine for a handful of lookups and
    wasteful for a real join.
    """
    index: dict[str, set[str]] = {}
    for raw in docket_codes:
        index.setdefault(normalize_docket_id(raw), set()).add(raw)
    return {key: frozenset(values) for key, values in index.items()}


DocketResolutionStatus = Literal["direct", "normalized", "ambiguous", "not_found"]


@dataclass(frozen=True, slots=True)
class DocketAgencyResolution:
    """The outcome of resolving one docket reference to an agency code.

    ``status`` distinguishes an exact match (``"direct"``), a match recovered
    only after :func:`normalize_docket_id` (``"normalized"``), a normalized
    key that names more than one raw docket and was therefore refused
    (``"ambiguous"``), and a key that named none (``"not_found"``).
    ``agency_code`` is set only for ``"direct"`` and ``"normalized"``.
    """

    status: DocketResolutionStatus
    agency_code: str | None


def resolve_docket_agency_code(
    docket_id: str,
    docket_codes: Mapping[str, str],
    *,
    index: Mapping[str, frozenset[str]] | None = None,
) -> DocketAgencyResolution:
    """Resolve a Federal Register docket reference to a regulations.gov agency code.

    Reads ``agency_code`` only from ``docket_codes`` (the field-based
    ``docket_id -> agency_code`` mapping the caller supplies from the real
    dockets spine) -- never from the docket id string's own leading letters.
    That is rule 1 (no docket-prefix inference): this function has no branch
    that inspects ``docket_id``'s characters for anything but an exact or
    normalized *key* lookup, so a docket-like string that resembles a known
    agency's prefix but is not a real docket (see the module docstring's
    ``REG-``/``FRL-``/compound-string examples) can only ever resolve to
    ``"not_found"``, never to a fabricated code.

    Rule 2 (ambiguous normalization is refused) is enforced directly: when
    the normalized key matches more than one raw docket id, this returns
    ``status="ambiguous"`` with no ``agency_code``, even if every candidate
    happens to share the same code.
    """
    direct = docket_codes.get(docket_id)
    if direct is not None:
        return DocketAgencyResolution("direct", direct)
    key = normalize_docket_id(docket_id)
    if not key:
        return DocketAgencyResolution("not_found", None)
    normalized_index = index if index is not None else build_normalized_docket_index(docket_codes)
    matches = normalized_index.get(key, frozenset())
    if not matches:
        return DocketAgencyResolution("not_found", None)
    if len(matches) > 1:
        return DocketAgencyResolution("ambiguous", None)
    return DocketAgencyResolution("normalized", docket_codes[next(iter(matches))])


# --------------------------------------------------------------------------
# Rule 3: 0.05-share specificity margin.
# --------------------------------------------------------------------------

#: Candidates within this much of the best share are treated as tied, and
#: the tie is broken toward the deeper (more specific) slug.
SPECIFICITY_MARGIN = 0.05


@dataclass(frozen=True, slots=True)
class CrosswalkCandidateShare:
    """One (agency slug, share, depth) reading, used only to rank candidates."""

    agency_slug: str
    share: float
    depth: int


def rank_crosswalk_candidates(
    candidates: Sequence[CrosswalkCandidateShare],
    *,
    specificity_margin: float = SPECIFICITY_MARGIN,
) -> tuple[str, ...]:
    """Order candidate agency slugs: share first, then sub-agency specificity.

    A sub-agency and its parent department are routinely both named on the
    same documents, so several slugs can legitimately reach a near-identical
    share. Candidates within ``specificity_margin`` of the best share are
    treated as tied on evidence and the tie is broken toward the deeper slug
    in the parent chain -- a crosswalk wants the sub-agency, not the parent
    it always co-occurs with. Outside the margin, share wins outright and
    depth is not consulted: a much-lower-share sub-agency is never preferred
    just for being deeper. See ``AGENCY_CROSSWALK_CANDIDATES`` for ``FAA``
    (margin fires) and ``BOEM`` (margin does not fire) as real examples.
    """
    if not candidates:
        return ()
    best = max(candidate.share for candidate in candidates)
    tied = {
        candidate.agency_slug
        for candidate in candidates
        if candidate.share >= best - specificity_margin
    }

    def sort_key(candidate: CrosswalkCandidateShare) -> tuple[int, int, float, str]:
        if candidate.agency_slug in tied:
            return (0, -candidate.depth, -candidate.share, candidate.agency_slug)
        return (1, 0, -candidate.share, candidate.agency_slug)

    return tuple(candidate.agency_slug for candidate in sorted(candidates, key=sort_key))


# --------------------------------------------------------------------------
# Tiering: share AND support, both pinned.
# --------------------------------------------------------------------------

CrosswalkTier = Literal["confident", "probable", "ambiguous", "unmapped"]
CROSSWALK_TIERS: tuple[CrosswalkTier, ...] = ("confident", "probable", "ambiguous", "unmapped")

#: A code whose primary slug reaches this share, over at least
#: MIN_CONFIDENT_DOCUMENTS documents, is "confident".
CONFIDENT_SHARE = 0.8
#: The same at a lower bar, over at least MIN_PROBABLE_DOCUMENTS documents,
#: is "probable".
PROBABLE_SHARE = 0.6
#: Share is meaningless over a handful of documents: floors, not just ratios.
MIN_CONFIDENT_DOCUMENTS = 5
MIN_PROBABLE_DOCUMENTS = 2


def tier_for_share(share: float, support_documents: int) -> CrosswalkTier:
    """Classify one code's primary-slug share into a crosswalk tier."""

    if support_documents <= 0:
        return "unmapped"
    if share >= CONFIDENT_SHARE and support_documents >= MIN_CONFIDENT_DOCUMENTS:
        return "confident"
    if share >= PROBABLE_SHARE and support_documents >= MIN_PROBABLE_DOCUMENTS:
        return "probable"
    return "ambiguous"


# --------------------------------------------------------------------------
# The curated crosswalk itself: the sealed build's agency-codes.parquet (316
# rows) and agency-crosswalk.parquet (914 candidate rows), sorted by
# (agency_code[, rank]) exactly as the sealed artifact orders them.
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class AgencyCrosswalkEntry:
    """One regulations.gov agency code's crosswalk verdict.

    From the sealed 2026-08-02 build's ``agency-codes.parquet``.
    ``confidence_share`` and ``support_documents`` describe ``primary_slug``
    specifically (the union of ``dockets_path_documents`` and
    ``documents_path_documents`` reached for this code); ``primary_slug`` is
    ``None`` exactly when ``tier == "unmapped"``.
    """

    agency_code: str
    in_dockets_table: bool
    tier: CrosswalkTier
    primary_slug: str | None
    confidence_share: float
    support_documents: int
    dockets_path_documents: int
    documents_path_documents: int
    evidence_is_documents_only: bool


_AGENCY_CROSSWALK_ROWS: tuple[
    tuple[str, bool, CrosswalkTier, str | None, float, int, int, int, bool], ...
] = (
    ('ABMC', False, 'unmapped', None, 0.0, 0, 0, 0, False),
    ('ACF', True, 'confident', 'health-and-human-services-department', 1.0, 25, 4, 21, False),
    ('ACFR', False, 'unmapped', None, 0.0, 0, 0, 0, False),
    ('ACHP', False, 'unmapped', None, 0.0, 0, 0, 0, False),
    ('ACL', True, 'unmapped', None, 0.0, 0, 0, 0, False),
    ('ACUS', False, 'probable', 'administrative-conference-of-the-united-states', 1.0, 3, 0, 3, True),
    ('ADF', False, 'unmapped', None, 0.0, 0, 0, 0, False),
    ('AFRH', False, 'unmapped', None, 0.0, 0, 0, 0, False),
    ('AHRQ', True, 'unmapped', None, 0.0, 0, 0, 0, False),
    ('AID', True, 'probable', 'agency-for-international-development', 1.0, 4, 3, 1, False),
    ('AMC', False, 'unmapped', None, 0.0, 0, 0, 0, False),
    ('AMS', True, 'confident', 'agricultural-marketing-service', 0.992089, 1896, 1864, 45, False),
    ('AOA', True, 'unmapped', None, 0.0, 0, 0, 0, False),
    ('APHIS', True, 'confident', 'animal-and-plant-health-inspection-service', 0.995971, 2730, 2707, 31, False),
    ('APPAL', False, 'unmapped', None, 0.0, 0, 0, 0, False),
    ('ARCTIC', False, 'unmapped', None, 0.0, 0, 0, 0, False),
    ('ARCTICGAS', False, 'unmapped', None, 0.0, 0, 0, 0, False),
    ('ARS', True, 'unmapped', None, 0.0, 0, 0, 0, False),
    ('ARTS', False, 'confident', 'national-foundation-on-the-arts-and-the-humanities', 1.0, 17, 0, 17, True),
    ('ASC', True, 'probable', 'appraisal-subcommittee-of-the-federal-financial-institutions-examination-council', 1.0, 2, 0, 2, True),
    ('ATBCB', True, 'confident', 'architectural-and-transportation-barriers-compliance-board', 1.0, 64, 62, 3, False),
    ('ATF', True, 'confident', 'alcohol-tobacco-firearms-and-explosives-bureau', 1.0, 40, 2, 39, False),
    ('ATR', True, 'unmapped', None, 0.0, 0, 0, 0, False),
    ('ATSDR', True, 'confident', 'agency-for-toxic-substances-and-disease-registry', 0.958904, 73, 72, 2, False),
    ('BBG', False, 'unmapped', None, 0.0, 0, 0, 0, False),
    ('BGSEEF', False, 'unmapped', None, 0.0, 0, 0, 0, False),
    ('BIA', True, 'confident', 'indian-affairs-bureau', 1.0, 37, 35, 2, False),
    ('BIS', True, 'probable', 'industry-and-security-bureau', 1.0, 4, 0, 4, True),
    ('BLM', True, 'confident', 'land-management-bureau', 1.0, 39, 34, 7, False),
    ('BLS', True, 'unmapped', None, 0.0, 0, 0, 0, False),
    ('BOEM', True, 'confident', 'interior-department', 1.0, 339, 330, 13, False),
    ('BOP', True, 'unmapped', None, 0.0, 0, 0, 0, False),
    ('BOR', True, 'probable', 'reclamation-bureau', 1.0, 2, 2, 0, False),
    ('BPA', True, 'unmapped', None, 0.0, 0, 0, 0, False),
    ('BPD', True, 'unmapped', None, 0.0, 0, 0, 0, False),
    ('BSC', True, 'probable', 'general-services-administration', 0.75, 8, 8, 0, False),
    ('BSEE', True, 'confident', 'interior-department', 1.0, 11, 3, 8, False),
    ('CCC', True, 'confident', 'commodity-credit-corporation', 1.0, 9, 3, 6, False),
    ('CCJJDP', False, 'unmapped', None, 0.0, 0, 0, 0, False),
    ('CDC', True, 'confident', 'health-and-human-services-department', 1.0, 1396, 1390, 6, False),
    ('CDFI', True, 'ambiguous', 'community-development-financial-institutions-fund', 1.0, 1, 1, 0, False),
    ('CDFIF', False, 'unmapped', None, 0.0, 0, 0, 0, False),
    ('CEQ', True, 'confident', 'council-on-environmental-quality', 1.0, 31, 30, 1, False),
    ('CFPB', True, 'confident', 'consumer-financial-protection-bureau', 1.0, 817, 813, 9, False),
    ('CFTC', True, 'confident', 'commodity-futures-trading-commission', 1.0, 28, 0, 28, True),
    ('CIA', False, 'ambiguous', 'central-intelligence-agency', 1.0, 1, 0, 1, True),
    ('CIGIE', False, 'unmapped', None, 0.0, 0, 0, 0, False),
    ('CISA', True, 'confident', 'homeland-security-department', 1.0, 163, 158, 7, False),
    ('CITA', False, 'probable', 'committee-for-the-implementation-of-textile-agreements', 1.0, 3, 0, 3, True),
    ('CMS', True, 'confident', 'centers-for-medicare-medicaid-services', 0.982143, 56, 1, 55, False),
    ('CNCS', True, 'confident', 'corporation-for-national-and-community-service', 1.0, 10, 0, 10, True),
    ('COE', True, 'confident', 'engineers-corps', 1.0, 68, 66, 3, False),
    ('COFA', False, 'probable', 'commission-of-fine-arts', 1.0, 2, 0, 2, True),
    ('COLC', True, 'confident', 'copyright-office-library-of-congress', 1.0, 5, 1, 4, False),
    ('CORP', False, 'unmapped', None, 0.0, 0, 0, 0, False),
    ('CPPBSD', True, 'confident', 'committee-for-purchase-from-people-who-are-blind-or-severely-disabled', 1.0, 21, 0, 21, True),
    ('CPSC', True, 'confident', 'consumer-product-safety-commission', 0.998243, 569, 561, 18, False),
    ('CRB', False, 'ambiguous', 'copyright-royalty-board', 1.0, 1, 0, 1, True),
    ('CRC', False, 'confident', 'civil-rights-commission', 1.0, 28, 0, 28, True),
    ('CSB', True, 'ambiguous', 'chemical-safety-and-hazard-investigation-board', 1.0, 1, 1, 0, False),
    ('CSEO', True, 'unmapped', None, 0.0, 0, 0, 0, False),
    ('CSOSA', False, 'unmapped', None, 0.0, 0, 0, 0, False),
    ('CSREES', True, 'unmapped', None, 0.0, 0, 0, 0, False),
    ('DARS', True, 'confident', 'defense-acquisition-regulations-system', 0.99278, 831, 831, 5, False),
    ('DC', False, 'unmapped', None, 0.0, 0, 0, 0, False),
    ('DEA', True, 'confident', 'drug-enforcement-administration', 1.0, 32, 0, 32, True),
    ('DEPO', True, 'unmapped', None, 0.0, 0, 0, 0, False),
    ('DFC', False, 'unmapped', None, 0.0, 0, 0, 0, False),
    ('DHS', True, 'confident', 'homeland-security-department', 1.0, 1410, 1403, 9, False),
    ('DIA', False, 'unmapped', None, 0.0, 0, 0, 0, False),
    ('DISA', False, 'unmapped', None, 0.0, 0, 0, 0, False),
    ('DLA', False, 'unmapped', None, 0.0, 0, 0, 0, False),
    ('DNFSB', False, 'unmapped', None, 0.0, 0, 0, 0, False),
    ('DOC', True, 'unmapped', None, 0.0, 0, 0, 0, False),
    ('DOD', True, 'confident', 'defense-department', 0.998403, 626, 598, 28, False),
    ('DOE', True, 'confident', 'energy-department', 1.0, 128, 97, 44, False),
    ('DOI', True, 'confident', 'interior-department', 1.0, 124, 122, 4, False),
    ('DOJ', True, 'probable', 'justice-department', 1.0, 3, 1, 2, False),
    ('DOL', True, 'confident', 'labor-department', 1.0, 22, 6, 16, False),
    ('DOS', True, 'confident', 'state-department', 1.0, 54, 11, 43, False),
    ('DOT', True, 'confident', 'transportation-department', 0.995006, 801, 796, 16, False),
    ('DRBC', False, 'ambiguous', 'delaware-river-basin-commission', 1.0, 1, 0, 1, True),
    ('EAB', True, 'unmapped', None, 0.0, 0, 0, 0, False),
    ('EAC', True, 'probable', 'election-assistance-commission', 1.0, 2, 2, 0, False),
    ('EBSA', True, 'probable', 'employee-benefits-security-administration', 1.0, 2, 0, 2, True),
    ('ECAB', True, 'unmapped', None, 0.0, 0, 0, 0, False),
    ('ECSA', True, 'unmapped', None, 0.0, 0, 0, 0, False),
    ('ED', True, 'confident', 'education-department', 1.0, 2885, 2877, 21, False),
    ('EDA', True, 'unmapped', None, 0.0, 0, 0, 0, False),
    ('EEOC', True, 'confident', 'equal-employment-opportunity-commission', 1.0, 7, 2, 5, False),
    ('EERE', True, 'confident', 'energy-department', 1.0, 1458, 1457, 5, False),
    ('EIA', True, 'probable', 'energy-information-administration', 1.0, 2, 0, 2, True),
    ('EIB', True, 'probable', 'export-import-bank', 1.0, 3, 3, 0, False),
    ('EOA', True, 'unmapped', None, 0.0, 0, 0, 0, False),
    ('EOIR', True, 'ambiguous', 'executive-office-for-immigration-review', 1.0, 1, 0, 1, True),
    ('EOP', False, 'unmapped', None, 0.0, 0, 0, 0, False),
    ('EPA', True, 'confident', 'environmental-protection-agency', 0.999874, 23723, 23677, 144, False),
    ('ERS', True, 'probable', 'agriculture-department', 1.0, 2, 1, 1, False),
    ('ERULE', True, 'unmapped', None, 0.0, 0, 0, 0, False),
    ('ESA', True, 'unmapped', None, 0.0, 0, 0, 0, False),
    ('ETA', True, 'confident', 'labor-department', 1.0, 48, 48, 0, False),
    ('FAA', True, 'confident', 'federal-aviation-administration', 0.999056, 25417, 25367, 157, False),
    ('FAR', True, 'confident', 'defense-department', 1.0, 100, 88, 12, False),
    ('FAS', True, 'ambiguous', 'foreign-agricultural-service', 1.0, 1, 0, 1, True),
    ('FASAB', False, 'ambiguous', 'federal-accounting-standards-advisory-board', 1.0, 1, 0, 1, True),
    ('FBI', True, 'ambiguous', 'homeland-security-department', 1.0, 1, 1, 0, False),
    ('FCA', False, 'ambiguous', 'farm-credit-administration', 1.0, 1, 0, 1, True),
    ('FCC', False, 'confident', 'federal-communications-commission', 1.0, 32, 0, 32, True),
    ('FCIC', True, 'confident', 'federal-crop-insurance-corporation', 0.986667, 75, 75, 0, False),
    ('FCSC', True, 'unmapped', None, 0.0, 0, 0, 0, False),
    ('FCSIC', False, 'ambiguous', 'farm-credit-system-insurance-corporation', 1.0, 1, 0, 1, True),
    ('FDA', True, 'confident', 'food-and-drug-administration', 0.999187, 13529, 13510, 106, False),
    ('FDIC', False, 'confident', 'federal-deposit-insurance-corporation', 1.0, 13, 0, 13, True),
    ('FEC', False, 'unmapped', None, 0.0, 0, 0, 0, False),
    ('FEMA', True, 'confident', 'homeland-security-department', 0.985075, 67, 59, 8, False),
    ('FERC', False, 'confident', 'federal-energy-regulatory-commission', 1.0, 158, 0, 158, True),
    ('FFIEC', True, 'probable', 'federal-financial-institutions-examination-council', 1.0, 4, 4, 0, False),
    ('FHFA', False, 'confident', 'federal-housing-finance-agency', 1.0, 7, 0, 7, True),
    ('FHFB', False, 'unmapped', None, 0.0, 0, 0, 0, False),
    ('FHWA', True, 'confident', 'federal-highway-administration', 0.987277, 786, 780, 10, False),
    ('FINCEN', True, 'confident', 'financial-crimes-enforcement-network', 1.0, 9, 7, 2, False),
    ('FINCIC', False, 'unmapped', None, 0.0, 0, 0, 0, False),
    ('FIRSTNET', True, 'unmapped', None, 0.0, 0, 0, 0, False),
    ('FISCAL', True, 'confident', 'treasury-department', 1.0, 19, 14, 5, False),
    ('FLETC', True, 'confident', 'homeland-security-department', 1.0, 10, 10, 0, False),
    ('FLRA', False, 'unmapped', None, 0.0, 0, 0, 0, False),
    ('FMC', True, 'confident', 'federal-maritime-commission', 1.0, 68, 61, 8, False),
    ('FMCS', False, 'ambiguous', 'federal-mediation-and-conciliation-service', 1.0, 1, 0, 1, True),
    ('FMCSA', True, 'confident', 'federal-motor-carrier-safety-administration', 0.999271, 4113, 4111, 24, False),
    ('FNA', True, 'confident', 'food-and-nutrition-administration', 1.0, 10, 0, 10, True),
    ('FNS', True, 'confident', 'food-and-nutrition-service', 0.994413, 179, 177, 2, False),
    ('FPAC', True, 'ambiguous', 'agriculture-department', 1.0, 1, 1, 0, False),
    ('FPPO', False, 'unmapped', None, 0.0, 0, 0, 0, False),
    ('FR', False, 'unmapped', None, 0.0, 0, 0, 0, False),
    ('FRA', True, 'confident', 'federal-railroad-administration', 0.997593, 2077, 2072, 24, False),
    ('FRS', False, 'confident', 'federal-reserve-system', 1.0, 31, 0, 31, True),
    ('FRTIB', True, 'probable', 'federal-retirement-thrift-investment-board', 1.0, 2, 0, 2, True),
    ('FS', True, 'confident', 'forest-service', 1.0, 8, 0, 8, True),
    ('FSA', True, 'confident', 'agriculture-department', 1.0, 15, 11, 4, False),
    ('FSIS', True, 'confident', 'food-safety-and-inspection-service', 1.0, 750, 747, 4, False),
    ('FSOC', True, 'probable', 'financial-stability-oversight-council', 1.0, 3, 3, 0, False),
    ('FTA', True, 'confident', 'federal-transit-administration', 1.0, 400, 394, 9, False),
    ('FTC', True, 'confident', 'federal-trade-commission', 1.0, 14, 0, 14, True),
    ('FTZB', True, 'unmapped', None, 0.0, 0, 0, 0, False),
    ('FWS', True, 'confident', 'fish-and-wildlife-service', 0.998353, 3036, 3016, 57, False),
    ('GAO', False, 'unmapped', None, 0.0, 0, 0, 0, False),
    ('GAPFAC', True, 'ambiguous', 'general-services-administration', 1.0, 1, 1, 0, False),
    ('GCERC', False, 'unmapped', None, 0.0, 0, 0, 0, False),
    ('GEO', False, 'unmapped', None, 0.0, 0, 0, 0, False),
    ('GIPSA', True, 'unmapped', None, 0.0, 0, 0, 0, False),
    ('GPO', False, 'unmapped', None, 0.0, 0, 0, 0, False),
    ('GSA', True, 'confident', 'general-services-administration', 1.0, 66, 55, 11, False),
    ('HHS', True, 'confident', 'health-and-human-services-department', 1.0, 28, 24, 5, False),
    ('HHSIG', True, 'ambiguous', 'health-and-human-services-department', 1.0, 1, 0, 1, True),
    ('HOPE', False, 'unmapped', None, 0.0, 0, 0, 0, False),
    ('HPAC', False, 'unmapped', None, 0.0, 0, 0, 0, False),
    ('HRSA', True, 'ambiguous', 'health-and-human-services-department', 1.0, 1, 0, 1, True),
    ('HST', False, 'unmapped', None, 0.0, 0, 0, 0, False),
    ('HUD', True, 'confident', 'housing-and-urban-development-department', 1.0, 74, 41, 33, False),
    ('IAF', False, 'unmapped', None, 0.0, 0, 0, 0, False),
    ('IAIA', False, 'unmapped', None, 0.0, 0, 0, 0, False),
    ('ICEB', True, 'confident', 'homeland-security-department', 1.0, 62, 58, 5, False),
    ('IHS', True, 'probable', 'indian-health-service', 1.0, 2, 0, 2, True),
    ('IIO', False, 'unmapped', None, 0.0, 0, 0, 0, False),
    ('IPEC', True, 'unmapped', None, 0.0, 0, 0, 0, False),
    ('IRS', True, 'confident', 'internal-revenue-service', 1.0, 15, 0, 15, True),
    ('ISOO', True, 'unmapped', None, 0.0, 0, 0, 0, False),
    ('ITA', True, 'confident', 'international-trade-administration', 0.99187, 123, 4, 119, False),
    ('ITC', False, 'confident', 'international-trade-commission', 1.0, 64, 0, 64, True),
    ('JBEA', False, 'ambiguous', 'joint-board-for-enrollment-of-actuaries', 1.0, 1, 0, 1, True),
    ('LMSO', True, 'ambiguous', 'labor-management-standards-office', 1.0, 1, 0, 1, True),
    ('LOC', False, 'unmapped', None, 0.0, 0, 0, 0, False),
    ('LSC', False, 'confident', 'legal-services-corporation', 1.0, 5, 0, 5, True),
    ('MARAD', True, 'confident', 'maritime-administration', 0.996799, 2812, 2798, 20, False),
    ('MBDA', True, 'unmapped', None, 0.0, 0, 0, 0, False),
    ('MCC', False, 'ambiguous', 'millennium-challenge-corporation', 1.0, 1, 0, 1, True),
    ('MCRMC', False, 'unmapped', None, 0.0, 0, 0, 0, False),
    ('MISS', False, 'unmapped', None, 0.0, 0, 0, 0, False),
    ('MKU', False, 'unmapped', None, 0.0, 0, 0, 0, False),
    ('MMC', False, 'unmapped', None, 0.0, 0, 0, 0, False),
    ('MMS', True, 'confident', 'interior-department', 1.0, 87, 87, 0, False),
    ('MSHA', True, 'confident', 'mine-safety-and-health-administration', 1.0, 106, 94, 16, False),
    ('MSHFRC', False, 'unmapped', None, 0.0, 0, 0, 0, False),
    ('MSPB', False, 'ambiguous', 'merit-systems-protection-board', 1.0, 1, 0, 1, True),
    ('NAL', True, 'unmapped', None, 0.0, 0, 0, 0, False),
    ('NARA', True, 'confident', 'national-archives-and-records-administration', 0.993902, 164, 160, 4, False),
    ('NASA', True, 'confident', 'national-aeronautics-and-space-administration', 1.0, 27, 10, 17, False),
    ('NASS', True, 'unmapped', None, 0.0, 0, 0, 0, False),
    ('NCD', False, 'ambiguous', 'national-council-on-disability', 1.0, 1, 0, 1, True),
    ('NCLIS', False, 'unmapped', None, 0.0, 0, 0, 0, False),
    ('NCMNPS', False, 'unmapped', None, 0.0, 0, 0, 0, False),
    ('NCPC', False, 'unmapped', None, 0.0, 0, 0, 0, False),
    ('NCPPCC', False, 'unmapped', None, 0.0, 0, 0, 0, False),
    ('NCS', True, 'confident', 'homeland-security-department', 1.0, 26, 26, 0, False),
    ('NCUA', True, 'confident', 'national-credit-union-administration', 1.0, 58, 47, 11, False),
    ('NEC', False, 'unmapped', None, 0.0, 0, 0, 0, False),
    ('NEIGHBOR', False, 'ambiguous', 'neighborhood-reinvestment-corporation', 1.0, 1, 0, 1, True),
    ('NHTSA', True, 'confident', 'national-highway-traffic-safety-administration', 0.997184, 2841, 2837, 26, False),
    ('NIFA', True, 'probable', 'national-institute-of-food-and-agriculture', 1.0, 3, 0, 3, True),
    ('NIGC', True, 'unmapped', None, 0.0, 0, 0, 0, False),
    ('NIH', True, 'confident', 'health-and-human-services-department', 1.0, 29, 28, 1, False),
    ('NIL', False, 'unmapped', None, 0.0, 0, 0, 0, False),
    ('NIST', True, 'unmapped', None, 0.0, 0, 0, 0, False),
    ('NLRB', True, 'unmapped', None, 0.0, 0, 0, 0, False),
    ('NMB', False, 'unmapped', None, 0.0, 0, 0, 0, False),
    ('NNSA', True, 'unmapped', None, 0.0, 0, 0, 0, False),
    ('NOAA', True, 'confident', 'national-oceanic-and-atmospheric-administration', 1.0, 49, 7, 42, False),
    ('NPREC', False, 'unmapped', None, 0.0, 0, 0, 0, False),
    ('NPS', True, 'confident', 'national-park-service', 0.95, 20, 19, 3, False),
    ('NRC', True, 'confident', 'nuclear-regulatory-commission', 0.999764, 8475, 8464, 48, False),
    ('NRCS', True, 'confident', 'agriculture-department', 1.0, 125, 125, 1, False),
    ('NRPC', False, 'unmapped', None, 0.0, 0, 0, 0, False),
    ('NSA', False, 'unmapped', None, 0.0, 0, 0, 0, False),
    ('NSCAI', False, 'unmapped', None, 0.0, 0, 0, 0, False),
    ('NSF', True, 'probable', 'national-science-foundation', 1.0, 4, 1, 4, False),
    ('NSPC', True, 'unmapped', None, 0.0, 0, 0, 0, False),
    ('NTIA', True, 'probable', 'national-telecommunications-and-information-administration', 1.0, 2, 2, 0, False),
    ('NTSB', True, 'confident', 'national-transportation-safety-board', 1.0, 46, 46, 0, False),
    ('NWBC', False, 'unmapped', None, 0.0, 0, 0, 0, False),
    ('NWTRB', False, 'unmapped', None, 0.0, 0, 0, 0, False),
    ('OCC', True, 'confident', 'comptroller-of-the-currency', 0.990196, 102, 96, 6, False),
    ('ODNI', False, 'unmapped', None, 0.0, 0, 0, 0, False),
    ('OEPNU', True, 'unmapped', None, 0.0, 0, 0, 0, False),
    ('OFAC', True, 'confident', 'foreign-assets-control-office', 1.0, 31, 13, 18, False),
    ('OFCCP', True, 'confident', 'labor-department', 1.0, 6, 6, 0, False),
    ('OFHEO', False, 'unmapped', None, 0.0, 0, 0, 0, False),
    ('OFPP', True, 'confident', 'federal-procurement-policy-office', 1.0, 10, 0, 10, True),
    ('OFR', True, 'probable', 'federal-register-office', 0.75, 4, 4, 0, False),
    ('OJJDP', True, 'unmapped', None, 0.0, 0, 0, 0, False),
    ('OJP', True, 'unmapped', None, 0.0, 0, 0, 0, False),
    ('OMB', True, 'confident', 'management-and-budget-office', 0.833333, 6, 3, 3, False),
    ('ONCD', True, 'unmapped', None, 0.0, 0, 0, 0, False),
    ('ONDCP', True, 'unmapped', None, 0.0, 0, 0, 0, False),
    ('ONHIR', False, 'unmapped', None, 0.0, 0, 0, 0, False),
    ('ONRR', True, 'confident', 'interior-department', 1.0, 234, 234, 3, False),
    ('OPIC', False, 'unmapped', None, 0.0, 0, 0, 0, False),
    ('OPM', True, 'confident', 'personnel-management-office', 1.0, 72, 0, 72, True),
    ('OPPM', True, 'unmapped', None, 0.0, 0, 0, 0, False),
    ('OSC', False, 'unmapped', None, 0.0, 0, 0, 0, False),
    ('OSHA', True, 'confident', 'occupational-safety-and-health-administration', 0.995986, 1744, 1743, 23, False),
    ('OSHRC', False, 'unmapped', None, 0.0, 0, 0, 0, False),
    ('OSM', True, 'confident', 'surface-mining-reclamation-and-enforcement-office', 1.0, 76, 76, 3, False),
    ('OSTP', True, 'unmapped', None, 0.0, 0, 0, 0, False),
    ('OTS', True, 'confident', 'treasury-department', 1.0, 17, 17, 0, False),
    ('PACIFIC', False, 'unmapped', None, 0.0, 0, 0, 0, False),
    ('PBGC', True, 'confident', 'pension-benefit-guaranty-corporation', 1.0, 5, 0, 5, True),
    ('PBRB', False, 'unmapped', None, 0.0, 0, 0, 0, False),
    ('PC', False, 'unmapped', None, 0.0, 0, 0, 0, False),
    ('PCLOB', True, 'probable', 'privacy-and-civil-liberties-oversight-board', 1.0, 2, 2, 0, False),
    ('PCSCOTUS', True, 'confident', 'general-services-administration', 1.0, 5, 5, 0, False),
    ('PHMSA', True, 'confident', 'pipeline-and-hazardous-materials-safety-administration', 0.981087, 846, 836, 41, False),
    ('PHS', False, 'unmapped', None, 0.0, 0, 0, 0, False),
    ('PRC', False, 'unmapped', None, 0.0, 0, 0, 0, False),
    ('PRES', False, 'unmapped', None, 0.0, 0, 0, 0, False),
    ('PT', False, 'unmapped', None, 0.0, 0, 0, 0, False),
    ('PTO', True, 'confident', 'patent-and-trademark-office', 0.997452, 785, 777, 9, False),
    ('RATB', False, 'unmapped', None, 0.0, 0, 0, 0, False),
    ('RBS', True, 'confident', 'rural-business-cooperative-service', 1.0, 84, 83, 1, False),
    ('RHS', True, 'confident', 'rural-housing-service', 0.992754, 138, 135, 3, False),
    ('RISC', False, 'unmapped', None, 0.0, 0, 0, 0, False),
    ('RITA', True, 'confident', 'transportation-department', 1.0, 29, 26, 3, False),
    ('RMA', True, 'unmapped', None, 0.0, 0, 0, 0, False),
    ('RRB', False, 'probable', 'railroad-retirement-board', 1.0, 3, 0, 3, True),
    ('RTB', True, 'unmapped', None, 0.0, 0, 0, 0, False),
    ('RUF', False, 'unmapped', None, 0.0, 0, 0, 0, False),
    ('RUS', True, 'confident', 'rural-utilities-service', 1.0, 120, 119, 1, False),
    ('SAMHSA', True, 'probable', 'substance-abuse-and-mental-health-services-administration', 1.0, 2, 2, 0, False),
    ('SBA', True, 'confident', 'small-business-administration', 1.0, 80, 80, 1, False),
    ('SEC', False, 'confident', 'securities-and-exchange-commission', 1.0, 245, 0, 245, True),
    ('SIGAR', False, 'unmapped', None, 0.0, 0, 0, 0, False),
    ('SIGIR', False, 'unmapped', None, 0.0, 0, 0, 0, False),
    ('SJI', False, 'unmapped', None, 0.0, 0, 0, 0, False),
    ('SLSDC', True, 'confident', 'great-lakes-st-lawrence-seaway-development-corporation', 1.0, 21, 21, 0, False),
    ('SRBC', False, 'probable', 'susquehanna-river-basin-commission', 1.0, 4, 0, 4, True),
    ('SS', False, 'unmapped', None, 0.0, 0, 0, 0, False),
    ('SSA', True, 'confident', 'social-security-administration', 1.0, 996, 996, 6, False),
    ('SSS', False, 'unmapped', None, 0.0, 0, 0, 0, False),
    ('STB', False, 'confident', 'surface-transportation-board', 1.0, 18, 0, 18, True),
    ('SWPA', True, 'unmapped', None, 0.0, 0, 0, 0, False),
    ('TA', True, 'unmapped', None, 0.0, 0, 0, 0, False),
    ('TRADE', False, 'unmapped', None, 0.0, 0, 0, 0, False),
    ('TRAIN', True, 'unmapped', None, 0.0, 0, 0, 0, False),
    ('TREAS', True, 'confident', 'treasury-department', 1.0, 26, 25, 2, False),
    ('TSA', True, 'confident', 'transportation-security-administration', 0.988701, 354, 350, 5, False),
    ('TTB', True, 'confident', 'alcohol-and-tobacco-tax-and-trade-bureau', 0.997297, 370, 370, 0, False),
    ('TVA', False, 'probable', 'tennessee-valley-authority', 1.0, 3, 0, 3, True),
    ('URMCC', False, 'unmapped', None, 0.0, 0, 0, 0, False),
    ('USA', True, 'confident', 'army-department', 0.985915, 71, 66, 5, False),
    ('USAF', True, 'confident', 'air-force-department', 1.0, 30, 29, 1, False),
    ('USAGM', False, 'unmapped', None, 0.0, 0, 0, 0, False),
    ('USBC', True, 'confident', 'commerce-department', 0.9, 10, 3, 7, False),
    ('USC', True, 'unmapped', None, 0.0, 0, 0, 0, False),
    ('USCBP', True, 'confident', 'homeland-security-department', 1.0, 428, 413, 19, False),
    ('USCC', False, 'unmapped', None, 0.0, 0, 0, 0, False),
    ('USCG', True, 'confident', 'coast-guard', 0.991778, 12405, 12371, 112, False),
    ('USCIS', True, 'confident', 'homeland-security-department', 1.0, 55, 30, 27, False),
    ('USDA', True, 'confident', 'agriculture-department', 1.0, 68, 47, 24, False),
    ('USDAIG', True, 'unmapped', None, 0.0, 0, 0, 0, False),
    ('USEIB', False, 'unmapped', None, 0.0, 0, 0, 0, False),
    ('USGS', True, 'confident', 'geological-survey', 0.972973, 37, 34, 6, False),
    ('USIP', False, 'unmapped', None, 0.0, 0, 0, 0, False),
    ('USJC', False, 'unmapped', None, 0.0, 0, 0, 0, False),
    ('USMINT', True, 'unmapped', None, 0.0, 0, 0, 0, False),
    ('USN', True, 'confident', 'defense-department', 1.0, 103, 98, 5, False),
    ('USOPC', False, 'unmapped', None, 0.0, 0, 0, 0, False),
    ('USPC', True, 'unmapped', None, 0.0, 0, 0, 0, False),
    ('USPS', False, 'confident', 'postal-service', 1.0, 9, 0, 9, True),
    ('USSC', False, 'unmapped', None, 0.0, 0, 0, 0, False),
    ('USTR', True, 'confident', 'trade-representative-office-of-united-states', 1.0, 253, 249, 5, False),
    ('USUHS', False, 'unmapped', None, 0.0, 0, 0, 0, False),
    ('VA', True, 'confident', 'veterans-affairs-department', 1.0, 76, 47, 37, False),
    ('VCNP', False, 'unmapped', None, 0.0, 0, 0, 0, False),
    ('VETS', True, 'probable', 'veterans-employment-and-training-service', 1.0, 2, 2, 0, False),
    ('WAPA', True, 'ambiguous', 'western-area-power-administration', 1.0, 1, 0, 1, True),
    ('WCPO', True, 'confident', 'workers-compensation-programs-office', 1.0, 8, 2, 6, False),
    ('WHD', True, 'probable', 'labor-department', 1.0, 3, 3, 1, False),
)

AGENCY_CROSSWALK: tuple[AgencyCrosswalkEntry, ...] = tuple(
    AgencyCrosswalkEntry(*row) for row in _AGENCY_CROSSWALK_ROWS
)

AGENCY_CROSSWALK_BY_CODE: Mapping[str, AgencyCrosswalkEntry] = {
    entry.agency_code: entry for entry in AGENCY_CROSSWALK
}

#: The sealed receipt's own tier accounting (its ``counts.tier_histogram``),
#: pinned rather than re-derived -- see AGENCY_CROSSWALK_REGENERATION_STATUS
#: for why a fresh derivation is not currently exact.
AGENCY_CROSSWALK_TIER_HISTOGRAM: Mapping[CrosswalkTier, int] = {
    "confident": 124,
    "probable": 29,
    "ambiguous": 23,
    "unmapped": 140,
}


def tier_histogram(entries: Sequence[AgencyCrosswalkEntry] = AGENCY_CROSSWALK) -> dict[str, int]:
    """Count entries by tier -- the module's own accounting check."""

    counts: dict[str, int] = dict.fromkeys(CROSSWALK_TIERS, 0)
    for entry in entries:
        counts[entry.tier] += 1
    return counts


@dataclass(frozen=True, slots=True)
class AgencyCrosswalkCandidate:
    """One ranked (agency_code, agency_slug) candidate row.

    From the sealed build's ``agency-crosswalk.parquet``. ``rank`` and
    ``is_primary`` are the sealed build's own verdict, applying
    :func:`rank_crosswalk_candidates`; the per-code test suite recomputes
    them from ``share``/``depth`` alone and checks they agree.
    """

    agency_code: str
    agency_slug: str
    rank: int
    depth: int
    share: float
    support_documents: int
    is_primary: bool


_AGENCY_CROSSWALK_CANDIDATE_ROWS: tuple[
    tuple[str, str, int, int, float, int, bool], ...
] = (
    ('ACF', 'health-and-human-services-department', 1, 0, 1.0, 25, True),
    ('ACF', 'children-and-families-administration', 2, 1, 0.8, 20, False),
    ('ACUS', 'administrative-conference-of-the-united-states', 1, 0, 1.0, 3, True),
    ('AID', 'agency-for-international-development', 1, 0, 1.0, 4, True),
    ('AID', 'agriculture-department', 2, 0, 0.5, 2, False),
    ('AID', 'education-department', 3, 0, 0.5, 2, False),
    ('AID', 'health-and-human-services-department', 4, 0, 0.5, 2, False),
    ('AID', 'homeland-security-department', 5, 0, 0.5, 2, False),
    ('AID', 'housing-and-urban-development-department', 6, 0, 0.5, 2, False),
    ('AID', 'justice-department', 7, 0, 0.5, 2, False),
    ('AID', 'labor-department', 8, 0, 0.5, 2, False),
    ('AID', 'veterans-affairs-department', 9, 0, 0.5, 2, False),
    ('AID', 'appraisal-subcommittee-of-the-federal-financial-institutions-examination-council', 10, 0, 0.25, 1, False),
    ('AID', 'commerce-department', 11, 0, 0.25, 1, False),
    ('AID', 'consumer-product-safety-commission', 12, 0, 0.25, 1, False),
    ('AID', 'corporation-for-national-and-community-service', 13, 0, 0.25, 1, False),
    ('AID', 'defense-department', 14, 0, 0.25, 1, False),
    ('AID', 'delta-regional-authority', 15, 0, 0.25, 1, False),
    ('AID', 'election-assistance-commission', 16, 0, 0.25, 1, False),
    ('AID', 'energy-department', 17, 0, 0.25, 1, False),
    ('AID', 'environmental-protection-agency', 18, 0, 0.25, 1, False),
    ('AID', 'executive-office-of-the-president', 19, 0, 0.25, 1, False),
    ('AID', 'export-import-bank', 20, 0, 0.25, 1, False),
    ('AID', 'federal-communications-commission', 21, 0, 0.25, 1, False),
    ('AID', 'gulf-coast-ecosystem-restoration-council', 22, 0, 0.25, 1, False),
    ('AID', 'institute-of-museum-and-library-services', 23, 1, 0.25, 1, False),
    ('AID', 'interior-department', 24, 0, 0.25, 1, False),
    ('AID', 'management-and-budget-office', 25, 0, 0.25, 1, False),
    ('AID', 'marine-mammal-commission', 26, 0, 0.25, 1, False),
    ('AID', 'millennium-challenge-corporation', 27, 0, 0.25, 1, False),
    ('AID', 'national-aeronautics-and-space-administration', 28, 0, 0.25, 1, False),
    ('AID', 'national-archives-and-records-administration', 29, 0, 0.25, 1, False),
    ('AID', 'national-credit-union-administration', 30, 0, 0.25, 1, False),
    ('AID', 'national-endowment-for-the-arts', 31, 1, 0.25, 1, False),
    ('AID', 'national-endowment-for-the-humanities', 32, 1, 0.25, 1, False),
    ('AID', 'national-foundation-on-the-arts-and-the-humanities', 33, 0, 0.25, 1, False),
    ('AID', 'national-science-foundation', 34, 0, 0.25, 1, False),
    ('AID', 'nuclear-regulatory-commission', 35, 0, 0.25, 1, False),
    ('AID', 'office-of-national-drug-control-policy', 36, 1, 0.25, 1, False),
    ('AID', 'peace-corps', 37, 0, 0.25, 1, False),
    ('AID', 'small-business-administration', 38, 0, 0.25, 1, False),
    ('AID', 'social-security-administration', 39, 0, 0.25, 1, False),
    ('AID', 'state-department', 40, 0, 0.25, 1, False),
    ('AID', 'transportation-department', 41, 0, 0.25, 1, False),
    ('AID', 'treasury-department', 42, 0, 0.25, 1, False),
    ('AID', 'u-s-international-development-finance-corporation', 43, 0, 0.25, 1, False),
    ('AID', 'united-states-agency-for-global-media', 44, 0, 0.25, 1, False),
    ('AMS', 'agricultural-marketing-service', 1, 1, 0.992089, 1881, True),
    ('AMS', 'agriculture-department', 2, 0, 1.0, 1896, False),
    ('AMS', 'commodity-credit-corporation', 3, 1, 0.001582, 3, False),
    ('APHIS', 'animal-and-plant-health-inspection-service', 1, 1, 0.995971, 2719, True),
    ('APHIS', 'agriculture-department', 2, 0, 1.0, 2730, False),
    ('APHIS', 'food-safety-and-inspection-service', 3, 1, 0.000733, 2, False),
    ('APHIS', 'commerce-department', 4, 0, 0.000366, 1, False),
    ('APHIS', 'fish-and-wildlife-service', 5, 1, 0.000366, 1, False),
    ('APHIS', 'interior-department', 6, 0, 0.000366, 1, False),
    ('APHIS', 'national-oceanic-and-atmospheric-administration', 7, 1, 0.000366, 1, False),
    ('ARTS', 'national-foundation-on-the-arts-and-the-humanities', 1, 0, 1.0, 17, True),
    ('ARTS', 'national-endowment-for-the-arts', 2, 1, 0.470588, 8, False),
    ('ARTS', 'institute-of-museum-and-library-services', 3, 1, 0.411765, 7, False),
    ('ARTS', 'national-endowment-for-the-humanities', 4, 1, 0.235294, 4, False),
    ('ARTS', 'agency-for-international-development', 5, 0, 0.058824, 1, False),
    ('ARTS', 'agriculture-department', 6, 0, 0.058824, 1, False),
    ('ARTS', 'appraisal-subcommittee-of-the-federal-financial-institutions-examination-council', 7, 0, 0.058824, 1, False),
    ('ARTS', 'commerce-department', 8, 0, 0.058824, 1, False),
    ('ARTS', 'consumer-product-safety-commission', 9, 0, 0.058824, 1, False),
    ('ARTS', 'corporation-for-national-and-community-service', 10, 0, 0.058824, 1, False),
    ('ARTS', 'defense-department', 11, 0, 0.058824, 1, False),
    ('ARTS', 'delta-regional-authority', 12, 0, 0.058824, 1, False),
    ('ARTS', 'education-department', 13, 0, 0.058824, 1, False),
    ('ARTS', 'election-assistance-commission', 14, 0, 0.058824, 1, False),
    ('ARTS', 'energy-department', 15, 0, 0.058824, 1, False),
    ('ARTS', 'environmental-protection-agency', 16, 0, 0.058824, 1, False),
    ('ARTS', 'executive-office-of-the-president', 17, 0, 0.058824, 1, False),
    ('ARTS', 'export-import-bank', 18, 0, 0.058824, 1, False),
    ('ARTS', 'federal-communications-commission', 19, 0, 0.058824, 1, False),
    ('ARTS', 'gulf-coast-ecosystem-restoration-council', 20, 0, 0.058824, 1, False),
    ('ARTS', 'health-and-human-services-department', 21, 0, 0.058824, 1, False),
    ('ARTS', 'homeland-security-department', 22, 0, 0.058824, 1, False),
    ('ARTS', 'housing-and-urban-development-department', 23, 0, 0.058824, 1, False),
    ('ARTS', 'interior-department', 24, 0, 0.058824, 1, False),
    ('ARTS', 'justice-department', 25, 0, 0.058824, 1, False),
    ('ARTS', 'labor-department', 26, 0, 0.058824, 1, False),
    ('ARTS', 'management-and-budget-office', 27, 0, 0.058824, 1, False),
    ('ARTS', 'marine-mammal-commission', 28, 0, 0.058824, 1, False),
    ('ARTS', 'millennium-challenge-corporation', 29, 0, 0.058824, 1, False),
    ('ARTS', 'national-aeronautics-and-space-administration', 30, 0, 0.058824, 1, False),
    ('ARTS', 'national-archives-and-records-administration', 31, 0, 0.058824, 1, False),
    ('ARTS', 'national-credit-union-administration', 32, 0, 0.058824, 1, False),
    ('ARTS', 'national-science-foundation', 33, 0, 0.058824, 1, False),
    ('ARTS', 'nuclear-regulatory-commission', 34, 0, 0.058824, 1, False),
    ('ARTS', 'office-of-national-drug-control-policy', 35, 1, 0.058824, 1, False),
    ('ARTS', 'peace-corps', 36, 0, 0.058824, 1, False),
    ('ARTS', 'small-business-administration', 37, 0, 0.058824, 1, False),
    ('ARTS', 'social-security-administration', 38, 0, 0.058824, 1, False),
    ('ARTS', 'state-department', 39, 0, 0.058824, 1, False),
    ('ARTS', 'transportation-department', 40, 0, 0.058824, 1, False),
    ('ARTS', 'treasury-department', 41, 0, 0.058824, 1, False),
    ('ARTS', 'u-s-international-development-finance-corporation', 42, 0, 0.058824, 1, False),
    ('ARTS', 'united-states-agency-for-global-media', 43, 0, 0.058824, 1, False),
    ('ARTS', 'veterans-affairs-department', 44, 0, 0.058824, 1, False),
    ('ASC', 'appraisal-subcommittee-of-the-federal-financial-institutions-examination-council', 1, 0, 1.0, 2, True),
    ('ASC', 'agency-for-international-development', 2, 0, 0.5, 1, False),
    ('ASC', 'agriculture-department', 3, 0, 0.5, 1, False),
    ('ASC', 'commerce-department', 4, 0, 0.5, 1, False),
    ('ASC', 'consumer-product-safety-commission', 5, 0, 0.5, 1, False),
    ('ASC', 'corporation-for-national-and-community-service', 6, 0, 0.5, 1, False),
    ('ASC', 'defense-department', 7, 0, 0.5, 1, False),
    ('ASC', 'delta-regional-authority', 8, 0, 0.5, 1, False),
    ('ASC', 'education-department', 9, 0, 0.5, 1, False),
    ('ASC', 'election-assistance-commission', 10, 0, 0.5, 1, False),
    ('ASC', 'energy-department', 11, 0, 0.5, 1, False),
    ('ASC', 'environmental-protection-agency', 12, 0, 0.5, 1, False),
    ('ASC', 'executive-office-of-the-president', 13, 0, 0.5, 1, False),
    ('ASC', 'export-import-bank', 14, 0, 0.5, 1, False),
    ('ASC', 'federal-communications-commission', 15, 0, 0.5, 1, False),
    ('ASC', 'gulf-coast-ecosystem-restoration-council', 16, 0, 0.5, 1, False),
    ('ASC', 'health-and-human-services-department', 17, 0, 0.5, 1, False),
    ('ASC', 'homeland-security-department', 18, 0, 0.5, 1, False),
    ('ASC', 'housing-and-urban-development-department', 19, 0, 0.5, 1, False),
    ('ASC', 'institute-of-museum-and-library-services', 20, 1, 0.5, 1, False),
    ('ASC', 'interior-department', 21, 0, 0.5, 1, False),
    ('ASC', 'justice-department', 22, 0, 0.5, 1, False),
    ('ASC', 'labor-department', 23, 0, 0.5, 1, False),
    ('ASC', 'management-and-budget-office', 24, 0, 0.5, 1, False),
    ('ASC', 'marine-mammal-commission', 25, 0, 0.5, 1, False),
    ('ASC', 'millennium-challenge-corporation', 26, 0, 0.5, 1, False),
    ('ASC', 'national-aeronautics-and-space-administration', 27, 0, 0.5, 1, False),
    ('ASC', 'national-archives-and-records-administration', 28, 0, 0.5, 1, False),
    ('ASC', 'national-credit-union-administration', 29, 0, 0.5, 1, False),
    ('ASC', 'national-endowment-for-the-arts', 30, 1, 0.5, 1, False),
    ('ASC', 'national-endowment-for-the-humanities', 31, 1, 0.5, 1, False),
    ('ASC', 'national-foundation-on-the-arts-and-the-humanities', 32, 0, 0.5, 1, False),
    ('ASC', 'national-science-foundation', 33, 0, 0.5, 1, False),
    ('ASC', 'nuclear-regulatory-commission', 34, 0, 0.5, 1, False),
    ('ASC', 'office-of-national-drug-control-policy', 35, 1, 0.5, 1, False),
    ('ASC', 'peace-corps', 36, 0, 0.5, 1, False),
    ('ASC', 'small-business-administration', 37, 0, 0.5, 1, False),
    ('ASC', 'social-security-administration', 38, 0, 0.5, 1, False),
    ('ASC', 'state-department', 39, 0, 0.5, 1, False),
    ('ASC', 'transportation-department', 40, 0, 0.5, 1, False),
    ('ASC', 'treasury-department', 41, 0, 0.5, 1, False),
    ('ASC', 'u-s-international-development-finance-corporation', 42, 0, 0.5, 1, False),
    ('ASC', 'united-states-agency-for-global-media', 43, 0, 0.5, 1, False),
    ('ASC', 'veterans-affairs-department', 44, 0, 0.5, 1, False),
    ('ATBCB', 'architectural-and-transportation-barriers-compliance-board', 1, 0, 1.0, 64, True),
    ('ATF', 'alcohol-tobacco-firearms-and-explosives-bureau', 1, 1, 1.0, 40, True),
    ('ATF', 'justice-department', 2, 0, 1.0, 40, False),
    ('ATSDR', 'agency-for-toxic-substances-and-disease-registry', 1, 1, 0.958904, 70, True),
    ('ATSDR', 'health-and-human-services-department', 2, 0, 1.0, 73, False),
    ('ATSDR', 'centers-for-disease-control-and-prevention', 3, 1, 0.027397, 2, False),
    ('BIA', 'indian-affairs-bureau', 1, 1, 1.0, 37, True),
    ('BIA', 'interior-department', 2, 0, 1.0, 37, False),
    ('BIS', 'industry-and-security-bureau', 1, 1, 1.0, 4, True),
    ('BIS', 'commerce-department', 2, 0, 1.0, 4, False),
    ('BLM', 'land-management-bureau', 1, 1, 1.0, 39, True),
    ('BLM', 'interior-department', 2, 0, 1.0, 39, False),
    ('BOEM', 'interior-department', 1, 0, 1.0, 339, True),
    ('BOEM', 'ocean-energy-management-bureau', 2, 1, 0.935103, 317, False),
    ('BOEM', 'ocean-energy-management-regulation-and-enforcement-bureau', 3, 1, 0.050147, 17, False),
    ('BOEM', 'safety-and-environmental-enforcement-bureau', 4, 1, 0.020649, 7, False),
    ('BOR', 'reclamation-bureau', 1, 1, 1.0, 2, True),
    ('BOR', 'interior-department', 2, 0, 1.0, 2, False),
    ('BSC', 'general-services-administration', 1, 0, 0.75, 6, True),
    ('BSC', 'personnel-management-office', 2, 0, 0.25, 2, False),
    ('BSEE', 'interior-department', 1, 0, 1.0, 11, True),
    ('BSEE', 'safety-and-environmental-enforcement-bureau', 2, 1, 0.909091, 10, False),
    ('BSEE', 'ocean-energy-management-bureau', 3, 1, 0.090909, 1, False),
    ('CCC', 'commodity-credit-corporation', 1, 1, 1.0, 9, True),
    ('CCC', 'agriculture-department', 2, 0, 1.0, 9, False),
    ('CCC', 'farm-service-agency', 3, 1, 0.222222, 2, False),
    ('CDC', 'health-and-human-services-department', 1, 0, 1.0, 1396, True),
    ('CDC', 'centers-for-disease-control-and-prevention', 2, 1, 0.928367, 1296, False),
    ('CDC', 'agency-for-toxic-substances-and-disease-registry', 3, 1, 0.002865, 4, False),
    ('CDC', 'justice-department', 4, 0, 0.000716, 1, False),
    ('CDC', 'justice-programs-office', 5, 1, 0.000716, 1, False),
    ('CDFI', 'community-development-financial-institutions-fund', 1, 1, 1.0, 1, True),
    ('CDFI', 'treasury-department', 2, 0, 1.0, 1, False),
    ('CEQ', 'council-on-environmental-quality', 1, 1, 1.0, 31, True),
    ('CFPB', 'consumer-financial-protection-bureau', 1, 0, 1.0, 817, True),
    ('CFPB', 'federal-reserve-system', 2, 0, 0.03672, 30, False),
    ('CFPB', 'treasury-department', 3, 0, 0.023256, 19, False),
    ('CFPB', 'comptroller-of-the-currency', 4, 1, 0.022032, 18, False),
    ('CFPB', 'national-credit-union-administration', 5, 0, 0.015912, 13, False),
    ('CFPB', 'federal-deposit-insurance-corporation', 6, 0, 0.013464, 11, False),
    ('CFPB', 'federal-housing-finance-agency', 7, 0, 0.007344, 6, False),
    ('CFPB', 'securities-and-exchange-commission', 8, 0, 0.004896, 4, False),
    ('CFPB', 'commodity-futures-trading-commission', 9, 0, 0.002448, 2, False),
    ('CFPB', 'centers-for-medicare-medicaid-services', 10, 1, 0.001224, 1, False),
    ('CFPB', 'health-and-human-services-department', 11, 0, 0.001224, 1, False),
    ('CFTC', 'commodity-futures-trading-commission', 1, 0, 1.0, 28, True),
    ('CFTC', 'securities-and-exchange-commission', 2, 0, 0.142857, 4, False),
    ('CFTC', 'comptroller-of-the-currency', 3, 1, 0.035714, 1, False),
    ('CFTC', 'consumer-financial-protection-bureau', 4, 0, 0.035714, 1, False),
    ('CFTC', 'federal-deposit-insurance-corporation', 5, 0, 0.035714, 1, False),
    ('CFTC', 'federal-housing-finance-agency', 6, 0, 0.035714, 1, False),
    ('CFTC', 'federal-reserve-system', 7, 0, 0.035714, 1, False),
    ('CFTC', 'national-credit-union-administration', 8, 0, 0.035714, 1, False),
    ('CFTC', 'treasury-department', 9, 0, 0.035714, 1, False),
    ('CIA', 'central-intelligence-agency', 1, 0, 1.0, 1, True),
    ('CISA', 'homeland-security-department', 1, 0, 1.0, 163, True),
    ('CITA', 'committee-for-the-implementation-of-textile-agreements', 1, 0, 1.0, 3, True),
    ('CMS', 'centers-for-medicare-medicaid-services', 1, 1, 0.982143, 55, True),
    ('CMS', 'health-and-human-services-department', 2, 0, 1.0, 56, False),
    ('CMS', 'consumer-financial-protection-bureau', 3, 0, 0.017857, 1, False),
    ('CMS', 'treasury-department', 4, 0, 0.017857, 1, False),
    ('CNCS', 'corporation-for-national-and-community-service', 1, 0, 1.0, 10, True),
    ('CNCS', 'agency-for-international-development', 2, 0, 0.1, 1, False),
    ('CNCS', 'agriculture-department', 3, 0, 0.1, 1, False),
    ('CNCS', 'appraisal-subcommittee-of-the-federal-financial-institutions-examination-council', 4, 0, 0.1, 1, False),
    ('CNCS', 'commerce-department', 5, 0, 0.1, 1, False),
    ('CNCS', 'consumer-product-safety-commission', 6, 0, 0.1, 1, False),
    ('CNCS', 'defense-department', 7, 0, 0.1, 1, False),
    ('CNCS', 'delta-regional-authority', 8, 0, 0.1, 1, False),
    ('CNCS', 'education-department', 9, 0, 0.1, 1, False),
    ('CNCS', 'election-assistance-commission', 10, 0, 0.1, 1, False),
    ('CNCS', 'energy-department', 11, 0, 0.1, 1, False),
    ('CNCS', 'environmental-protection-agency', 12, 0, 0.1, 1, False),
    ('CNCS', 'executive-office-of-the-president', 13, 0, 0.1, 1, False),
    ('CNCS', 'export-import-bank', 14, 0, 0.1, 1, False),
    ('CNCS', 'federal-communications-commission', 15, 0, 0.1, 1, False),
    ('CNCS', 'gulf-coast-ecosystem-restoration-council', 16, 0, 0.1, 1, False),
    ('CNCS', 'health-and-human-services-department', 17, 0, 0.1, 1, False),
    ('CNCS', 'homeland-security-department', 18, 0, 0.1, 1, False),
    ('CNCS', 'housing-and-urban-development-department', 19, 0, 0.1, 1, False),
    ('CNCS', 'institute-of-museum-and-library-services', 20, 1, 0.1, 1, False),
    ('CNCS', 'interior-department', 21, 0, 0.1, 1, False),
    ('CNCS', 'justice-department', 22, 0, 0.1, 1, False),
    ('CNCS', 'labor-department', 23, 0, 0.1, 1, False),
    ('CNCS', 'management-and-budget-office', 24, 0, 0.1, 1, False),
    ('CNCS', 'marine-mammal-commission', 25, 0, 0.1, 1, False),
    ('CNCS', 'millennium-challenge-corporation', 26, 0, 0.1, 1, False),
    ('CNCS', 'national-aeronautics-and-space-administration', 27, 0, 0.1, 1, False),
    ('CNCS', 'national-archives-and-records-administration', 28, 0, 0.1, 1, False),
    ('CNCS', 'national-credit-union-administration', 29, 0, 0.1, 1, False),
    ('CNCS', 'national-endowment-for-the-arts', 30, 1, 0.1, 1, False),
    ('CNCS', 'national-endowment-for-the-humanities', 31, 1, 0.1, 1, False),
    ('CNCS', 'national-foundation-on-the-arts-and-the-humanities', 32, 0, 0.1, 1, False),
    ('CNCS', 'national-science-foundation', 33, 0, 0.1, 1, False),
    ('CNCS', 'nuclear-regulatory-commission', 34, 0, 0.1, 1, False),
    ('CNCS', 'office-of-national-drug-control-policy', 35, 1, 0.1, 1, False),
    ('CNCS', 'peace-corps', 36, 0, 0.1, 1, False),
    ('CNCS', 'small-business-administration', 37, 0, 0.1, 1, False),
    ('CNCS', 'social-security-administration', 38, 0, 0.1, 1, False),
    ('CNCS', 'state-department', 39, 0, 0.1, 1, False),
    ('CNCS', 'transportation-department', 40, 0, 0.1, 1, False),
    ('CNCS', 'treasury-department', 41, 0, 0.1, 1, False),
    ('CNCS', 'u-s-international-development-finance-corporation', 42, 0, 0.1, 1, False),
    ('CNCS', 'united-states-agency-for-global-media', 43, 0, 0.1, 1, False),
    ('CNCS', 'veterans-affairs-department', 44, 0, 0.1, 1, False),
    ('COE', 'engineers-corps', 1, 1, 1.0, 68, True),
    ('COE', 'defense-department', 2, 0, 1.0, 68, False),
    ('COFA', 'commission-of-fine-arts', 1, 0, 1.0, 2, True),
    ('COLC', 'copyright-office-library-of-congress', 1, 1, 1.0, 5, True),
    ('COLC', 'library-of-congress', 2, 0, 1.0, 5, False),
    ('CPPBSD', 'committee-for-purchase-from-people-who-are-blind-or-severely-disabled', 1, 0, 1.0, 21, True),
    ('CPSC', 'consumer-product-safety-commission', 1, 0, 0.998243, 568, True),
    ('CPSC', 'commerce-department', 2, 0, 0.003515, 2, False),
    ('CPSC', 'agency-for-international-development', 3, 0, 0.001757, 1, False),
    ('CPSC', 'agriculture-department', 4, 0, 0.001757, 1, False),
    ('CPSC', 'appraisal-subcommittee-of-the-federal-financial-institutions-examination-council', 5, 0, 0.001757, 1, False),
    ('CPSC', 'corporation-for-national-and-community-service', 6, 0, 0.001757, 1, False),
    ('CPSC', 'defense-department', 7, 0, 0.001757, 1, False),
    ('CPSC', 'delta-regional-authority', 8, 0, 0.001757, 1, False),
    ('CPSC', 'education-department', 9, 0, 0.001757, 1, False),
    ('CPSC', 'election-assistance-commission', 10, 0, 0.001757, 1, False),
    ('CPSC', 'energy-department', 11, 0, 0.001757, 1, False),
    ('CPSC', 'environmental-protection-agency', 12, 0, 0.001757, 1, False),
    ('CPSC', 'executive-office-of-the-president', 13, 0, 0.001757, 1, False),
    ('CPSC', 'export-import-bank', 14, 0, 0.001757, 1, False),
    ('CPSC', 'federal-communications-commission', 15, 0, 0.001757, 1, False),
    ('CPSC', 'gulf-coast-ecosystem-restoration-council', 16, 0, 0.001757, 1, False),
    ('CPSC', 'health-and-human-services-department', 17, 0, 0.001757, 1, False),
    ('CPSC', 'homeland-security-department', 18, 0, 0.001757, 1, False),
    ('CPSC', 'housing-and-urban-development-department', 19, 0, 0.001757, 1, False),
    ('CPSC', 'institute-of-museum-and-library-services', 20, 1, 0.001757, 1, False),
    ('CPSC', 'interior-department', 21, 0, 0.001757, 1, False),
    ('CPSC', 'justice-department', 22, 0, 0.001757, 1, False),
    ('CPSC', 'labor-department', 23, 0, 0.001757, 1, False),
    ('CPSC', 'management-and-budget-office', 24, 0, 0.001757, 1, False),
    ('CPSC', 'marine-mammal-commission', 25, 0, 0.001757, 1, False),
    ('CPSC', 'millennium-challenge-corporation', 26, 0, 0.001757, 1, False),
    ('CPSC', 'national-aeronautics-and-space-administration', 27, 0, 0.001757, 1, False),
    ('CPSC', 'national-archives-and-records-administration', 28, 0, 0.001757, 1, False),
    ('CPSC', 'national-credit-union-administration', 29, 0, 0.001757, 1, False),
    ('CPSC', 'national-endowment-for-the-arts', 30, 1, 0.001757, 1, False),
    ('CPSC', 'national-endowment-for-the-humanities', 31, 1, 0.001757, 1, False),
    ('CPSC', 'national-foundation-on-the-arts-and-the-humanities', 32, 0, 0.001757, 1, False),
    ('CPSC', 'national-science-foundation', 33, 0, 0.001757, 1, False),
    ('CPSC', 'nuclear-regulatory-commission', 34, 0, 0.001757, 1, False),
    ('CPSC', 'office-of-national-drug-control-policy', 35, 1, 0.001757, 1, False),
    ('CPSC', 'peace-corps', 36, 0, 0.001757, 1, False),
    ('CPSC', 'small-business-administration', 37, 0, 0.001757, 1, False),
    ('CPSC', 'social-security-administration', 38, 0, 0.001757, 1, False),
    ('CPSC', 'state-department', 39, 0, 0.001757, 1, False),
    ('CPSC', 'transportation-department', 40, 0, 0.001757, 1, False),
    ('CPSC', 'treasury-department', 41, 0, 0.001757, 1, False),
    ('CPSC', 'u-s-international-development-finance-corporation', 42, 0, 0.001757, 1, False),
    ('CPSC', 'united-states-agency-for-global-media', 43, 0, 0.001757, 1, False),
    ('CPSC', 'veterans-affairs-department', 44, 0, 0.001757, 1, False),
    ('CRB', 'copyright-royalty-board', 1, 1, 1.0, 1, True),
    ('CRB', 'library-of-congress', 2, 0, 1.0, 1, False),
    ('CRC', 'civil-rights-commission', 1, 0, 1.0, 28, True),
    ('CSB', 'chemical-safety-and-hazard-investigation-board', 1, 0, 1.0, 1, True),
    ('DARS', 'defense-acquisition-regulations-system', 1, 1, 0.99278, 825, True),
    ('DARS', 'defense-department', 2, 0, 1.0, 831, False),
    ('DEA', 'drug-enforcement-administration', 1, 1, 1.0, 32, True),
    ('DEA', 'justice-department', 2, 0, 1.0, 32, False),
    ('DHS', 'homeland-security-department', 1, 0, 1.0, 1410, True),
    ('DHS', 'federal-emergency-management-agency', 2, 1, 0.004255, 6, False),
    ('DHS', 'u-s-customs-and-border-protection', 3, 1, 0.004255, 6, False),
    ('DHS', 'transportation-security-administration', 4, 1, 0.002837, 4, False),
    ('DHS', 'coast-guard', 5, 1, 0.002128, 3, False),
    ('DHS', 'justice-department', 6, 0, 0.002128, 3, False),
    ('DHS', 'national-communications-system', 7, 1, 0.002128, 3, False),
    ('DHS', 'secret-service', 8, 1, 0.002128, 3, False),
    ('DHS', 'agency-for-international-development', 9, 0, 0.001418, 2, False),
    ('DHS', 'agriculture-department', 10, 0, 0.001418, 2, False),
    ('DHS', 'education-department', 11, 0, 0.001418, 2, False),
    ('DHS', 'health-and-human-services-department', 12, 0, 0.001418, 2, False),
    ('DHS', 'housing-and-urban-development-department', 13, 0, 0.001418, 2, False),
    ('DHS', 'labor-department', 14, 0, 0.001418, 2, False),
    ('DHS', 'veterans-affairs-department', 15, 0, 0.001418, 2, False),
    ('DHS', 'u-s-citizenship-and-immigration-services', 16, 1, 0.000709, 1, False),
    ('DOD', 'defense-department', 1, 0, 0.998403, 625, True),
    ('DOD', 'defense-intelligence-agency', 2, 1, 0.030351, 19, False),
    ('DOD', 'defense-logistics-agency', 3, 1, 0.025559, 16, False),
    ('DOD', 'navy-department', 4, 1, 0.01278, 8, False),
    ('DOD', 'federal-procurement-policy-office', 5, 1, 0.009585, 6, False),
    ('DOD', 'general-services-administration', 6, 0, 0.009585, 6, False),
    ('DOD', 'management-and-budget-office', 7, 0, 0.009585, 6, False),
    ('DOD', 'national-aeronautics-and-space-administration', 8, 0, 0.009585, 6, False),
    ('DOD', 'army-department', 9, 1, 0.003195, 2, False),
    ('DOD', 'national-security-agency-central-security-service', 10, 1, 0.001597, 1, False),
    ('DOE', 'energy-department', 1, 0, 1.0, 128, True),
    ('DOI', 'interior-department', 1, 0, 1.0, 124, True),
    ('DOI', 'national-park-service', 2, 1, 0.080645, 10, False),
    ('DOI', 'reclamation-bureau', 3, 1, 0.072581, 9, False),
    ('DOI', 'agriculture-department', 4, 0, 0.048387, 6, False),
    ('DOI', 'fish-and-wildlife-service', 5, 1, 0.048387, 6, False),
    ('DOI', 'land-management-bureau', 6, 1, 0.048387, 6, False),
    ('DOI', 'forest-service', 7, 1, 0.040323, 5, False),
    ('DOI', 'geological-survey', 8, 1, 0.032258, 4, False),
    ('DOI', 'indian-affairs-bureau', 9, 1, 0.024194, 3, False),
    ('DOI', 'safety-and-environmental-enforcement-bureau', 10, 1, 0.016129, 2, False),
    ('DOI', 'commerce-department', 11, 0, 0.008065, 1, False),
    ('DOI', 'national-oceanic-and-atmospheric-administration', 12, 1, 0.008065, 1, False),
    ('DOI', 'surface-mining-reclamation-and-enforcement-office', 13, 1, 0.008065, 1, False),
    ('DOJ', 'justice-department', 1, 0, 1.0, 3, True),
    ('DOJ', 'homeland-security-department', 2, 0, 0.666667, 2, False),
    ('DOJ', 'agency-for-international-development', 3, 0, 0.333333, 1, False),
    ('DOJ', 'agriculture-department', 4, 0, 0.333333, 1, False),
    ('DOJ', 'education-department', 5, 0, 0.333333, 1, False),
    ('DOJ', 'health-and-human-services-department', 6, 0, 0.333333, 1, False),
    ('DOJ', 'housing-and-urban-development-department', 7, 0, 0.333333, 1, False),
    ('DOJ', 'labor-department', 8, 0, 0.333333, 1, False),
    ('DOJ', 'veterans-affairs-department', 9, 0, 0.333333, 1, False),
    ('DOL', 'labor-department', 1, 0, 1.0, 22, True),
    ('DOL', 'agency-for-international-development', 2, 0, 0.045455, 1, False),
    ('DOL', 'agriculture-department', 3, 0, 0.045455, 1, False),
    ('DOL', 'education-department', 4, 0, 0.045455, 1, False),
    ('DOL', 'health-and-human-services-department', 5, 0, 0.045455, 1, False),
    ('DOL', 'homeland-security-department', 6, 0, 0.045455, 1, False),
    ('DOL', 'housing-and-urban-development-department', 7, 0, 0.045455, 1, False),
    ('DOL', 'justice-department', 8, 0, 0.045455, 1, False),
    ('DOL', 'veterans-affairs-department', 9, 0, 0.045455, 1, False),
    ('DOL', 'workers-compensation-programs-office', 10, 1, 0.045455, 1, False),
    ('DOS', 'state-department', 1, 0, 1.0, 54, True),
    ('DOT', 'transportation-department', 1, 0, 0.995006, 797, True),
    ('DOT', 'transportation-statistics-bureau', 2, 1, 0.02372, 19, False),
    ('DOT', 'federal-aviation-administration', 3, 1, 0.006242, 5, False),
    ('DOT', 'federal-transit-administration', 4, 1, 0.004994, 4, False),
    ('DOT', 'federal-motor-carrier-safety-administration', 5, 1, 0.003745, 3, False),
    ('DOT', 'federal-railroad-administration', 6, 1, 0.003745, 3, False),
    ('DOT', 'u-s-committee-on-the-marine-transportation-system', 7, 0, 0.003745, 3, False),
    ('DOT', 'coast-guard', 8, 1, 0.002497, 2, False),
    ('DOT', 'defense-department', 9, 0, 0.002497, 2, False),
    ('DOT', 'engineers-corps', 10, 1, 0.002497, 2, False),
    ('DOT', 'federal-highway-administration', 11, 1, 0.002497, 2, False),
    ('DOT', 'homeland-security-department', 12, 0, 0.002497, 2, False),
    ('DOT', 'maritime-administration', 13, 1, 0.002497, 2, False),
    ('DOT', 'national-highway-traffic-safety-administration', 14, 1, 0.002497, 2, False),
    ('DOT', 'pipeline-and-hazardous-materials-safety-administration', 15, 1, 0.002497, 2, False),
    ('DOT', 'commerce-department', 16, 0, 0.001248, 1, False),
    ('DOT', 'international-trade-administration', 17, 1, 0.001248, 1, False),
    ('DRBC', 'delaware-river-basin-commission', 1, 0, 1.0, 1, True),
    ('EAC', 'election-assistance-commission', 1, 0, 1.0, 2, True),
    ('EBSA', 'employee-benefits-security-administration', 1, 1, 1.0, 2, True),
    ('EBSA', 'labor-department', 2, 0, 1.0, 2, False),
    ('EBSA', 'health-and-human-services-department', 3, 0, 0.5, 1, False),
    ('EBSA', 'internal-revenue-service', 4, 1, 0.5, 1, False),
    ('EBSA', 'treasury-department', 5, 0, 0.5, 1, False),
    ('ED', 'education-department', 1, 0, 1.0, 2885, True),
    ('ED', 'agency-for-international-development', 2, 0, 0.000693, 2, False),
    ('ED', 'agriculture-department', 3, 0, 0.000693, 2, False),
    ('ED', 'health-and-human-services-department', 4, 0, 0.000693, 2, False),
    ('ED', 'homeland-security-department', 5, 0, 0.000693, 2, False),
    ('ED', 'housing-and-urban-development-department', 6, 0, 0.000693, 2, False),
    ('ED', 'justice-department', 7, 0, 0.000693, 2, False),
    ('ED', 'labor-department', 8, 0, 0.000693, 2, False),
    ('ED', 'veterans-affairs-department', 9, 0, 0.000693, 2, False),
    ('EEOC', 'equal-employment-opportunity-commission', 1, 0, 1.0, 7, True),
    ('EERE', 'energy-department', 1, 0, 1.0, 1458, True),
    ('EERE', 'energy-efficiency-and-renewable-energy-office', 2, 1, 0.04321, 63, False),
    ('EIA', 'energy-information-administration', 1, 1, 1.0, 2, True),
    ('EIA', 'energy-department', 2, 0, 1.0, 2, False),
    ('EIB', 'export-import-bank', 1, 0, 1.0, 3, True),
    ('EOIR', 'executive-office-for-immigration-review', 1, 1, 1.0, 1, True),
    ('EOIR', 'justice-department', 2, 0, 1.0, 1, False),
    ('EPA', 'environmental-protection-agency', 1, 0, 0.999874, 23720, True),
    ('EPA', 'transportation-department', 2, 0, 0.001644, 39, False),
    ('EPA', 'defense-department', 3, 0, 0.001602, 38, False),
    ('EPA', 'national-highway-traffic-safety-administration', 4, 1, 0.001602, 38, False),
    ('EPA', 'engineers-corps', 5, 1, 0.001222, 29, False),
    ('EPA', 'energy-department', 6, 0, 0.000169, 4, False),
    ('EPA', 'homeland-security-department', 7, 0, 0.000126, 3, False),
    ('EPA', 'nuclear-regulatory-commission', 8, 0, 0.000126, 3, False),
    ('EPA', 'coast-guard', 9, 1, 8.4e-05, 2, False),
    ('EPA', 'general-services-administration', 10, 0, 8.4e-05, 2, False),
    ('EPA', 'national-oceanic-and-atmospheric-administration', 11, 1, 8.4e-05, 2, False),
    ('EPA', 'commerce-department', 12, 0, 4.2e-05, 1, False),
    ('EPA', 'fish-and-wildlife-service', 13, 1, 4.2e-05, 1, False),
    ('EPA', 'interior-department', 14, 0, 4.2e-05, 1, False),
    ('EPA', 'internal-revenue-service', 15, 1, 4.2e-05, 1, False),
    ('EPA', 'science-and-technology-policy-office', 16, 0, 4.2e-05, 1, False),
    ('EPA', 'treasury-department', 17, 0, 4.2e-05, 1, False),
    ('ERS', 'agriculture-department', 1, 0, 1.0, 2, True),
    ('ERS', 'economic-research-service', 2, 1, 0.5, 1, False),
    ('ETA', 'labor-department', 1, 0, 1.0, 48, True),
    ('ETA', 'employment-and-training-administration', 2, 1, 0.916667, 44, False),
    ('ETA', 'education-department', 3, 0, 0.083333, 4, False),
    ('ETA', 'homeland-security-department', 4, 0, 0.0625, 3, False),
    ('ETA', 'occupational-safety-and-health-administration', 5, 1, 0.020833, 1, False),
    ('ETA', 'u-s-citizenship-and-immigration-services', 6, 1, 0.020833, 1, False),
    ('ETA', 'wage-and-hour-division', 7, 1, 0.020833, 1, False),
    ('FAA', 'federal-aviation-administration', 1, 1, 0.999056, 25393, True),
    ('FAA', 'transportation-department', 2, 0, 0.999843, 25413, False),
    ('FAA', 'commerce-department', 3, 0, 7.9e-05, 2, False),
    ('FAA', 'homeland-security-department', 4, 0, 7.9e-05, 2, False),
    ('FAA', 'interior-department', 5, 0, 7.9e-05, 2, False),
    ('FAA', 'national-park-service', 6, 1, 7.9e-05, 2, False),
    ('FAA', 'transportation-security-administration', 7, 1, 7.9e-05, 2, False),
    ('FAA', 'national-telecommunications-and-information-administration', 8, 1, 3.9e-05, 1, False),
    ('FAA', 'state-department', 9, 0, 3.9e-05, 1, False),
    ('FAA', 'technology-administration', 10, 1, 3.9e-05, 1, False),
    ('FAR', 'defense-department', 1, 0, 1.0, 100, True),
    ('FAR', 'general-services-administration', 2, 0, 1.0, 100, False),
    ('FAR', 'national-aeronautics-and-space-administration', 3, 0, 1.0, 100, False),
    ('FAR', 'federal-procurement-policy-office', 4, 1, 0.27, 27, False),
    ('FAR', 'management-and-budget-office', 5, 0, 0.25, 25, False),
    ('FAS', 'foreign-agricultural-service', 1, 1, 1.0, 1, True),
    ('FAS', 'agriculture-department', 2, 0, 1.0, 1, False),
    ('FASAB', 'federal-accounting-standards-advisory-board', 1, 0, 1.0, 1, True),
    ('FBI', 'homeland-security-department', 1, 0, 1.0, 1, True),
    ('FBI', 'justice-department', 2, 0, 1.0, 1, False),
    ('FCA', 'farm-credit-administration', 1, 0, 1.0, 1, True),
    ('FCC', 'federal-communications-commission', 1, 0, 1.0, 32, True),
    ('FCIC', 'federal-crop-insurance-corporation', 1, 1, 0.986667, 74, True),
    ('FCIC', 'agriculture-department', 2, 0, 1.0, 75, False),
    ('FCIC', 'farm-service-agency', 3, 1, 0.013333, 1, False),
    ('FCIC', 'risk-management-agency', 4, 1, 0.013333, 1, False),
    ('FCSIC', 'farm-credit-system-insurance-corporation', 1, 0, 1.0, 1, True),
    ('FDA', 'food-and-drug-administration', 1, 1, 0.999187, 13518, True),
    ('FDA', 'health-and-human-services-department', 2, 0, 0.999926, 13528, False),
    ('FDA', 'agriculture-department', 3, 0, 0.000665, 9, False),
    ('FDA', 'food-safety-and-inspection-service', 4, 1, 0.000517, 7, False),
    ('FDA', 'centers-for-medicare-medicaid-services', 5, 1, 0.00037, 5, False),
    ('FDA', 'health-resources-and-services-administration', 6, 1, 0.000148, 2, False),
    ('FDA', 'environmental-protection-agency', 7, 0, 7.4e-05, 1, False),
    ('FDIC', 'federal-deposit-insurance-corporation', 1, 0, 1.0, 13, True),
    ('FDIC', 'commodity-futures-trading-commission', 2, 0, 0.076923, 1, False),
    ('FDIC', 'comptroller-of-the-currency', 3, 1, 0.076923, 1, False),
    ('FDIC', 'consumer-financial-protection-bureau', 4, 0, 0.076923, 1, False),
    ('FDIC', 'federal-housing-finance-agency', 5, 0, 0.076923, 1, False),
    ('FDIC', 'federal-reserve-system', 6, 0, 0.076923, 1, False),
    ('FDIC', 'national-credit-union-administration', 7, 0, 0.076923, 1, False),
    ('FDIC', 'securities-and-exchange-commission', 8, 0, 0.076923, 1, False),
    ('FDIC', 'treasury-department', 9, 0, 0.076923, 1, False),
    ('FEMA', 'homeland-security-department', 1, 0, 0.985075, 66, True),
    ('FEMA', 'federal-emergency-management-agency', 2, 1, 0.791045, 53, False),
    ('FEMA', 'nuclear-regulatory-commission', 3, 0, 0.014925, 1, False),
    ('FERC', 'federal-energy-regulatory-commission', 1, 1, 1.0, 158, True),
    ('FERC', 'energy-department', 2, 0, 1.0, 158, False),
    ('FFIEC', 'federal-financial-institutions-examination-council', 1, 0, 1.0, 4, True),
    ('FHFA', 'federal-housing-finance-agency', 1, 0, 1.0, 7, True),
    ('FHFA', 'commodity-futures-trading-commission', 2, 0, 0.142857, 1, False),
    ('FHFA', 'comptroller-of-the-currency', 3, 1, 0.142857, 1, False),
    ('FHFA', 'consumer-financial-protection-bureau', 4, 0, 0.142857, 1, False),
    ('FHFA', 'federal-deposit-insurance-corporation', 5, 0, 0.142857, 1, False),
    ('FHFA', 'federal-reserve-system', 6, 0, 0.142857, 1, False),
    ('FHFA', 'national-credit-union-administration', 7, 0, 0.142857, 1, False),
    ('FHFA', 'securities-and-exchange-commission', 8, 0, 0.142857, 1, False),
    ('FHFA', 'treasury-department', 9, 0, 0.142857, 1, False),
    ('FHWA', 'federal-highway-administration', 1, 1, 0.987277, 776, True),
    ('FHWA', 'transportation-department', 2, 0, 0.996183, 783, False),
    ('FHWA', 'federal-transit-administration', 3, 1, 0.03944, 31, False),
    ('FHWA', 'federal-railroad-administration', 4, 1, 0.01145, 9, False),
    ('FHWA', 'indian-affairs-bureau', 5, 1, 0.002545, 2, False),
    ('FHWA', 'interior-department', 6, 0, 0.002545, 2, False),
    ('FHWA', 'morris-k-udall-and-stewart-l-udall-foundation', 7, 0, 0.002545, 2, False),
    ('FHWA', 'energy-department', 8, 0, 0.001272, 1, False),
    ('FHWA', 'maritime-administration', 9, 1, 0.001272, 1, False),
    ('FINCEN', 'financial-crimes-enforcement-network', 1, 1, 1.0, 9, True),
    ('FINCEN', 'treasury-department', 2, 0, 1.0, 9, False),
    ('FINCEN', 'comptroller-of-the-currency', 3, 1, 0.111111, 1, False),
    ('FINCEN', 'federal-deposit-insurance-corporation', 4, 0, 0.111111, 1, False),
    ('FINCEN', 'federal-reserve-system', 5, 0, 0.111111, 1, False),
    ('FINCEN', 'foreign-assets-control-office', 6, 1, 0.111111, 1, False),
    ('FINCEN', 'national-credit-union-administration', 7, 0, 0.111111, 1, False),
    ('FISCAL', 'treasury-department', 1, 0, 1.0, 19, True),
    ('FISCAL', 'fiscal-service', 2, 1, 0.736842, 14, False),
    ('FISCAL', 'bureau-of-the-fiscal-service', 3, 1, 0.263158, 5, False),
    ('FLETC', 'homeland-security-department', 1, 0, 1.0, 10, True),
    ('FLETC', 'federal-law-enforcement-training-center', 2, 1, 0.6, 6, False),
    ('FMC', 'federal-maritime-commission', 1, 0, 1.0, 68, True),
    ('FMCS', 'federal-mediation-and-conciliation-service', 1, 0, 1.0, 1, True),
    ('FMCSA', 'federal-motor-carrier-safety-administration', 1, 1, 0.999271, 4110, True),
    ('FMCSA', 'transportation-department', 2, 0, 0.999514, 4111, False),
    ('FMCSA', 'national-highway-traffic-safety-administration', 3, 1, 0.001216, 5, False),
    ('FMCSA', 'pipeline-and-hazardous-materials-safety-administration', 4, 1, 0.000243, 1, False),
    ('FMCSA', 'research-and-innovative-technology-administration', 5, 1, 0.000243, 1, False),
    ('FNA', 'food-and-nutrition-administration', 1, 1, 1.0, 10, True),
    ('FNA', 'agriculture-department', 2, 0, 1.0, 10, False),
    ('FNS', 'food-and-nutrition-service', 1, 1, 0.994413, 178, True),
    ('FNS', 'agriculture-department', 2, 0, 1.0, 179, False),
    ('FNS', 'food-and-nutrition-administration', 3, 1, 0.005587, 1, False),
    ('FPAC', 'agriculture-department', 1, 0, 1.0, 1, True),
    ('FRA', 'federal-railroad-administration', 1, 1, 0.997593, 2072, True),
    ('FRA', 'transportation-department', 2, 0, 1.0, 2077, False),
    ('FRA', 'pipeline-and-hazardous-materials-safety-administration', 3, 1, 0.001444, 3, False),
    ('FRS', 'federal-reserve-system', 1, 0, 1.0, 31, True),
    ('FRS', 'commodity-futures-trading-commission', 2, 0, 0.032258, 1, False),
    ('FRS', 'comptroller-of-the-currency', 3, 1, 0.032258, 1, False),
    ('FRS', 'consumer-financial-protection-bureau', 4, 0, 0.032258, 1, False),
    ('FRS', 'federal-deposit-insurance-corporation', 5, 0, 0.032258, 1, False),
    ('FRS', 'federal-housing-finance-agency', 6, 0, 0.032258, 1, False),
    ('FRS', 'national-credit-union-administration', 7, 0, 0.032258, 1, False),
    ('FRS', 'securities-and-exchange-commission', 8, 0, 0.032258, 1, False),
    ('FRS', 'treasury-department', 9, 0, 0.032258, 1, False),
    ('FRTIB', 'federal-retirement-thrift-investment-board', 1, 0, 1.0, 2, True),
    ('FS', 'forest-service', 1, 1, 1.0, 8, True),
    ('FS', 'agriculture-department', 2, 0, 1.0, 8, False),
    ('FSA', 'agriculture-department', 1, 0, 1.0, 15, True),
    ('FSA', 'farm-service-agency', 2, 1, 0.733333, 11, False),
    ('FSA', 'commodity-credit-corporation', 3, 1, 0.266667, 4, False),
    ('FSIS', 'food-safety-and-inspection-service', 1, 1, 1.0, 750, True),
    ('FSIS', 'agriculture-department', 2, 0, 1.0, 750, False),
    ('FSIS', 'food-and-drug-administration', 3, 1, 0.012, 9, False),
    ('FSIS', 'health-and-human-services-department', 4, 0, 0.012, 9, False),
    ('FSOC', 'financial-stability-oversight-council', 1, 0, 1.0, 3, True),
    ('FTA', 'federal-transit-administration', 1, 1, 1.0, 400, True),
    ('FTA', 'transportation-department', 2, 0, 1.0, 400, False),
    ('FTA', 'federal-highway-administration', 3, 1, 0.0225, 9, False),
    ('FTC', 'federal-trade-commission', 1, 0, 1.0, 14, True),
    ('FWS', 'fish-and-wildlife-service', 1, 1, 0.998353, 3031, True),
    ('FWS', 'interior-department', 2, 0, 1.0, 3036, False),
    ('FWS', 'agriculture-department', 3, 0, 0.02141, 65, False),
    ('FWS', 'forest-service', 4, 1, 0.02141, 65, False),
    ('FWS', 'commerce-department', 5, 0, 0.010211, 31, False),
    ('FWS', 'national-oceanic-and-atmospheric-administration', 6, 1, 0.010211, 31, False),
    ('FWS', 'national-park-service', 7, 1, 0.000659, 2, False),
    ('GAPFAC', 'general-services-administration', 1, 0, 1.0, 1, True),
    ('GSA', 'general-services-administration', 1, 0, 1.0, 66, True),
    ('GSA', 'defense-department', 2, 0, 0.090909, 6, False),
    ('GSA', 'federal-procurement-policy-office', 3, 1, 0.090909, 6, False),
    ('GSA', 'management-and-budget-office', 4, 0, 0.090909, 6, False),
    ('GSA', 'national-aeronautics-and-space-administration', 5, 0, 0.090909, 6, False),
    ('HHS', 'health-and-human-services-department', 1, 0, 1.0, 28, True),
    ('HHS', 'centers-for-medicare-medicaid-services', 2, 1, 0.321429, 9, False),
    ('HHS', 'children-and-families-administration', 3, 1, 0.25, 7, False),
    ('HHS', 'food-and-drug-administration', 4, 1, 0.25, 7, False),
    ('HHS', 'public-health-service', 5, 1, 0.178571, 5, False),
    ('HHS', 'agency-for-international-development', 6, 0, 0.035714, 1, False),
    ('HHS', 'agriculture-department', 7, 0, 0.035714, 1, False),
    ('HHS', 'education-department', 8, 0, 0.035714, 1, False),
    ('HHS', 'homeland-security-department', 9, 0, 0.035714, 1, False),
    ('HHS', 'housing-and-urban-development-department', 10, 0, 0.035714, 1, False),
    ('HHS', 'justice-department', 11, 0, 0.035714, 1, False),
    ('HHS', 'labor-department', 12, 0, 0.035714, 1, False),
    ('HHS', 'veterans-affairs-department', 13, 0, 0.035714, 1, False),
    ('HHSIG', 'health-and-human-services-department', 1, 0, 1.0, 1, True),
    ('HRSA', 'health-and-human-services-department', 1, 0, 1.0, 1, True),
    ('HUD', 'housing-and-urban-development-department', 1, 0, 1.0, 74, True),
    ('HUD', 'agency-for-international-development', 2, 0, 0.013514, 1, False),
    ('HUD', 'agriculture-department', 3, 0, 0.013514, 1, False),
    ('HUD', 'education-department', 4, 0, 0.013514, 1, False),
    ('HUD', 'health-and-human-services-department', 5, 0, 0.013514, 1, False),
    ('HUD', 'homeland-security-department', 6, 0, 0.013514, 1, False),
    ('HUD', 'justice-department', 7, 0, 0.013514, 1, False),
    ('HUD', 'labor-department', 8, 0, 0.013514, 1, False),
    ('HUD', 'veterans-affairs-department', 9, 0, 0.013514, 1, False),
    ('ICEB', 'homeland-security-department', 1, 0, 1.0, 62, True),
    ('ICEB', 'u-s-immigration-and-customs-enforcement', 2, 1, 0.612903, 38, False),
    ('ICEB', 'executive-office-for-immigration-review', 3, 1, 0.016129, 1, False),
    ('ICEB', 'justice-department', 4, 0, 0.016129, 1, False),
    ('IHS', 'indian-health-service', 1, 1, 1.0, 2, True),
    ('IHS', 'health-and-human-services-department', 2, 0, 1.0, 2, False),
    ('IRS', 'internal-revenue-service', 1, 1, 1.0, 15, True),
    ('IRS', 'treasury-department', 2, 0, 1.0, 15, False),
    ('IRS', 'employee-benefits-security-administration', 3, 1, 0.133333, 2, False),
    ('IRS', 'health-and-human-services-department', 4, 0, 0.133333, 2, False),
    ('IRS', 'labor-department', 5, 0, 0.133333, 2, False),
    ('IRS', 'personnel-management-office', 6, 0, 0.133333, 2, False),
    ('ITA', 'international-trade-administration', 1, 1, 0.99187, 122, True),
    ('ITA', 'commerce-department', 2, 0, 1.0, 123, False),
    ('ITC', 'international-trade-commission', 1, 0, 1.0, 64, True),
    ('JBEA', 'joint-board-for-enrollment-of-actuaries', 1, 0, 1.0, 1, True),
    ('LMSO', 'labor-management-standards-office', 1, 1, 1.0, 1, True),
    ('LMSO', 'labor-department', 2, 0, 1.0, 1, False),
    ('LSC', 'legal-services-corporation', 1, 0, 1.0, 5, True),
    ('MARAD', 'maritime-administration', 1, 1, 0.996799, 2803, True),
    ('MARAD', 'transportation-department', 2, 0, 0.999289, 2810, False),
    ('MARAD', 'coast-guard', 3, 1, 0.001067, 3, False),
    ('MARAD', 'homeland-security-department', 4, 0, 0.001067, 3, False),
    ('MARAD', 'state-department', 5, 0, 0.000356, 1, False),
    ('MCC', 'millennium-challenge-corporation', 1, 0, 1.0, 1, True),
    ('MMS', 'interior-department', 1, 0, 1.0, 87, True),
    ('MMS', 'minerals-management-service', 2, 1, 0.885057, 77, False),
    ('MMS', 'ocean-energy-management-regulation-and-enforcement-bureau', 3, 1, 0.114943, 10, False),
    ('MMS', 'natural-resources-revenue-office', 4, 1, 0.022989, 2, False),
    ('MSHA', 'mine-safety-and-health-administration', 1, 1, 1.0, 106, True),
    ('MSHA', 'labor-department', 2, 0, 1.0, 106, False),
    ('MSPB', 'merit-systems-protection-board', 1, 0, 1.0, 1, True),
    ('MSPB', 'personnel-management-office', 2, 0, 1.0, 1, False),
    ('NARA', 'national-archives-and-records-administration', 1, 0, 0.993902, 163, True),
    ('NARA', 'federal-register-office', 2, 1, 0.006098, 1, False),
    ('NARA', 'information-security-oversight-office', 3, 1, 0.006098, 1, False),
    ('NASA', 'national-aeronautics-and-space-administration', 1, 0, 1.0, 27, True),
    ('NASA', 'defense-department', 2, 0, 0.37037, 10, False),
    ('NASA', 'federal-procurement-policy-office', 3, 1, 0.37037, 10, False),
    ('NASA', 'general-services-administration', 4, 0, 0.37037, 10, False),
    ('NASA', 'management-and-budget-office', 5, 0, 0.37037, 10, False),
    ('NCD', 'national-council-on-disability', 1, 0, 1.0, 1, True),
    ('NCS', 'homeland-security-department', 1, 0, 1.0, 26, True),
    ('NCS', 'national-communications-system', 2, 1, 0.846154, 22, False),
    ('NCUA', 'national-credit-union-administration', 1, 0, 1.0, 58, True),
    ('NCUA', 'comptroller-of-the-currency', 2, 1, 0.12069, 7, False),
    ('NCUA', 'federal-deposit-insurance-corporation', 3, 0, 0.12069, 7, False),
    ('NCUA', 'federal-reserve-system', 4, 0, 0.12069, 7, False),
    ('NCUA', 'treasury-department', 5, 0, 0.12069, 7, False),
    ('NCUA', 'consumer-financial-protection-bureau', 6, 0, 0.103448, 6, False),
    ('NCUA', 'federal-housing-finance-agency', 7, 0, 0.051724, 3, False),
    ('NCUA', 'commodity-futures-trading-commission', 8, 0, 0.017241, 1, False),
    ('NCUA', 'financial-crimes-enforcement-network', 9, 1, 0.017241, 1, False),
    ('NCUA', 'securities-and-exchange-commission', 10, 0, 0.017241, 1, False),
    ('NEIGHBOR', 'neighborhood-reinvestment-corporation', 1, 0, 1.0, 1, True),
    ('NHTSA', 'national-highway-traffic-safety-administration', 1, 1, 0.997184, 2833, True),
    ('NHTSA', 'transportation-department', 2, 0, 0.997536, 2834, False),
    ('NHTSA', 'environmental-protection-agency', 3, 0, 0.013024, 37, False),
    ('NHTSA', 'federal-motor-carrier-safety-administration', 4, 1, 0.002112, 6, False),
    ('NHTSA', 'federal-highway-administration', 5, 1, 0.00176, 5, False),
    ('NHTSA', 'commerce-department', 6, 0, 0.000704, 2, False),
    ('NHTSA', 'national-telecommunications-and-information-administration', 7, 1, 0.000704, 2, False),
    ('NIFA', 'national-institute-of-food-and-agriculture', 1, 1, 1.0, 3, True),
    ('NIFA', 'agriculture-department', 2, 0, 1.0, 3, False),
    ('NIH', 'health-and-human-services-department', 1, 0, 1.0, 29, True),
    ('NIH', 'national-institutes-of-health', 2, 1, 0.206897, 6, False),
    ('NOAA', 'national-oceanic-and-atmospheric-administration', 1, 1, 1.0, 49, True),
    ('NOAA', 'commerce-department', 2, 0, 1.0, 49, False),
    ('NOAA', 'fish-and-wildlife-service', 3, 1, 0.020408, 1, False),
    ('NOAA', 'interior-department', 4, 0, 0.020408, 1, False),
    ('NPS', 'national-park-service', 1, 1, 0.95, 19, True),
    ('NPS', 'interior-department', 2, 0, 1.0, 20, False),
    ('NPS', 'fish-and-wildlife-service', 3, 1, 0.1, 2, False),
    ('NPS', 'land-management-bureau', 4, 1, 0.1, 2, False),
    ('NRC', 'nuclear-regulatory-commission', 1, 0, 0.999764, 8473, True),
    ('NRC', 'securities-and-exchange-commission', 2, 0, 0.000472, 4, False),
    ('NRC', 'homeland-security-department', 3, 0, 0.000118, 1, False),
    ('NRC', 'national-oceanic-and-atmospheric-administration', 4, 1, 0.000118, 1, False),
    ('NRCS', 'agriculture-department', 1, 0, 1.0, 125, True),
    ('NRCS', 'natural-resources-conservation-service', 2, 1, 0.912, 114, False),
    ('NRCS', 'commodity-credit-corporation', 3, 1, 0.136, 17, False),
    ('NRCS', 'forest-service', 4, 1, 0.016, 2, False),
    ('NSF', 'national-science-foundation', 1, 0, 1.0, 4, True),
    ('NTIA', 'national-telecommunications-and-information-administration', 1, 1, 1.0, 2, True),
    ('NTIA', 'commerce-department', 2, 0, 1.0, 2, False),
    ('NTSB', 'national-transportation-safety-board', 1, 0, 1.0, 46, True),
    ('OCC', 'comptroller-of-the-currency', 1, 1, 0.990196, 101, True),
    ('OCC', 'treasury-department', 2, 0, 0.990196, 101, False),
    ('OCC', 'federal-reserve-system', 3, 0, 0.764706, 78, False),
    ('OCC', 'federal-deposit-insurance-corporation', 4, 0, 0.607843, 62, False),
    ('OCC', 'federal-housing-finance-agency', 5, 0, 0.303922, 31, False),
    ('OCC', 'consumer-financial-protection-bureau', 6, 0, 0.22549, 23, False),
    ('OCC', 'securities-and-exchange-commission', 7, 0, 0.215686, 22, False),
    ('OCC', 'farm-credit-administration', 8, 0, 0.137255, 14, False),
    ('OCC', 'national-credit-union-administration', 9, 0, 0.107843, 11, False),
    ('OCC', 'commodity-futures-trading-commission', 10, 0, 0.088235, 9, False),
    ('OCC', 'housing-and-urban-development-department', 11, 0, 0.078431, 8, False),
    ('OCC', 'thrift-supervision-office', 12, 1, 0.019608, 2, False),
    ('OCC', 'federal-financial-institutions-examination-council', 13, 0, 0.009804, 1, False),
    ('OCC', 'financial-crimes-enforcement-network', 14, 1, 0.009804, 1, False),
    ('OFAC', 'foreign-assets-control-office', 1, 1, 1.0, 31, True),
    ('OFAC', 'treasury-department', 2, 0, 1.0, 31, False),
    ('OFCCP', 'labor-department', 1, 0, 1.0, 6, True),
    ('OFCCP', 'federal-contract-compliance-programs-office', 2, 1, 0.666667, 4, False),
    ('OFPP', 'federal-procurement-policy-office', 1, 1, 1.0, 10, True),
    ('OFPP', 'management-and-budget-office', 2, 0, 1.0, 10, False),
    ('OFPP', 'defense-department', 3, 0, 0.9, 9, False),
    ('OFPP', 'general-services-administration', 4, 0, 0.9, 9, False),
    ('OFPP', 'national-aeronautics-and-space-administration', 5, 0, 0.9, 9, False),
    ('OFR', 'federal-register-office', 1, 1, 0.75, 3, True),
    ('OFR', 'federal-register-administrative-committee', 2, 0, 0.25, 1, False),
    ('OMB', 'management-and-budget-office', 1, 0, 0.833333, 5, True),
    ('OMB', 'transportation-department', 2, 0, 0.333333, 2, False),
    ('OMB', 'agency-for-international-development', 3, 0, 0.166667, 1, False),
    ('OMB', 'agriculture-department', 4, 0, 0.166667, 1, False),
    ('OMB', 'appraisal-subcommittee-of-the-federal-financial-institutions-examination-council', 5, 0, 0.166667, 1, False),
    ('OMB', 'commerce-department', 6, 0, 0.166667, 1, False),
    ('OMB', 'consumer-product-safety-commission', 7, 0, 0.166667, 1, False),
    ('OMB', 'corporation-for-national-and-community-service', 8, 0, 0.166667, 1, False),
    ('OMB', 'defense-department', 9, 0, 0.166667, 1, False),
    ('OMB', 'delta-regional-authority', 10, 0, 0.166667, 1, False),
    ('OMB', 'education-department', 11, 0, 0.166667, 1, False),
    ('OMB', 'election-assistance-commission', 12, 0, 0.166667, 1, False),
    ('OMB', 'energy-department', 13, 0, 0.166667, 1, False),
    ('OMB', 'environmental-protection-agency', 14, 0, 0.166667, 1, False),
    ('OMB', 'executive-office-of-the-president', 15, 0, 0.166667, 1, False),
    ('OMB', 'export-import-bank', 16, 0, 0.166667, 1, False),
    ('OMB', 'federal-communications-commission', 17, 0, 0.166667, 1, False),
    ('OMB', 'gulf-coast-ecosystem-restoration-council', 18, 0, 0.166667, 1, False),
    ('OMB', 'health-and-human-services-department', 19, 0, 0.166667, 1, False),
    ('OMB', 'homeland-security-department', 20, 0, 0.166667, 1, False),
    ('OMB', 'housing-and-urban-development-department', 21, 0, 0.166667, 1, False),
    ('OMB', 'institute-of-museum-and-library-services', 22, 1, 0.166667, 1, False),
    ('OMB', 'interior-department', 23, 0, 0.166667, 1, False),
    ('OMB', 'justice-department', 24, 0, 0.166667, 1, False),
    ('OMB', 'labor-department', 25, 0, 0.166667, 1, False),
    ('OMB', 'marine-mammal-commission', 26, 0, 0.166667, 1, False),
    ('OMB', 'millennium-challenge-corporation', 27, 0, 0.166667, 1, False),
    ('OMB', 'national-aeronautics-and-space-administration', 28, 0, 0.166667, 1, False),
    ('OMB', 'national-archives-and-records-administration', 29, 0, 0.166667, 1, False),
    ('OMB', 'national-credit-union-administration', 30, 0, 0.166667, 1, False),
    ('OMB', 'national-endowment-for-the-arts', 31, 1, 0.166667, 1, False),
    ('OMB', 'national-endowment-for-the-humanities', 32, 1, 0.166667, 1, False),
    ('OMB', 'national-foundation-on-the-arts-and-the-humanities', 33, 0, 0.166667, 1, False),
    ('OMB', 'national-science-foundation', 34, 0, 0.166667, 1, False),
    ('OMB', 'nuclear-regulatory-commission', 35, 0, 0.166667, 1, False),
    ('OMB', 'office-of-national-drug-control-policy', 36, 1, 0.166667, 1, False),
    ('OMB', 'peace-corps', 37, 0, 0.166667, 1, False),
    ('OMB', 'small-business-administration', 38, 0, 0.166667, 1, False),
    ('OMB', 'social-security-administration', 39, 0, 0.166667, 1, False),
    ('OMB', 'state-department', 40, 0, 0.166667, 1, False),
    ('OMB', 'treasury-department', 41, 0, 0.166667, 1, False),
    ('OMB', 'u-s-international-development-finance-corporation', 42, 0, 0.166667, 1, False),
    ('OMB', 'united-states-agency-for-global-media', 43, 0, 0.166667, 1, False),
    ('OMB', 'veterans-affairs-department', 44, 0, 0.166667, 1, False),
    ('ONRR', 'interior-department', 1, 0, 1.0, 234, True),
    ('ONRR', 'natural-resources-revenue-office', 2, 1, 0.854701, 200, False),
    ('ONRR', 'hearings-and-appeals-office-interior-department', 3, 1, 0.008547, 2, False),
    ('ONRR', 'ocean-energy-management-regulation-and-enforcement-bureau', 4, 1, 0.004274, 1, False),
    ('OPM', 'personnel-management-office', 1, 0, 1.0, 72, True),
    ('OPM', 'employee-benefits-security-administration', 2, 1, 0.013889, 1, False),
    ('OPM', 'health-and-human-services-department', 3, 0, 0.013889, 1, False),
    ('OPM', 'internal-revenue-service', 4, 1, 0.013889, 1, False),
    ('OPM', 'labor-department', 5, 0, 0.013889, 1, False),
    ('OPM', 'merit-systems-protection-board', 6, 0, 0.013889, 1, False),
    ('OPM', 'treasury-department', 7, 0, 0.013889, 1, False),
    ('OSHA', 'occupational-safety-and-health-administration', 1, 1, 0.995986, 1737, True),
    ('OSHA', 'labor-department', 2, 0, 0.998853, 1742, False),
    ('OSM', 'surface-mining-reclamation-and-enforcement-office', 1, 1, 1.0, 76, True),
    ('OSM', 'interior-department', 2, 0, 1.0, 76, False),
    ('OTS', 'treasury-department', 1, 0, 1.0, 17, True),
    ('OTS', 'thrift-supervision-office', 2, 1, 0.941176, 16, False),
    ('OTS', 'comptroller-of-the-currency', 3, 1, 0.411765, 7, False),
    ('OTS', 'federal-reserve-system', 4, 0, 0.411765, 7, False),
    ('OTS', 'federal-deposit-insurance-corporation', 5, 0, 0.352941, 6, False),
    ('OTS', 'national-credit-union-administration', 6, 0, 0.294118, 5, False),
    ('OTS', 'federal-trade-commission', 7, 0, 0.235294, 4, False),
    ('OTS', 'federal-housing-finance-agency', 8, 0, 0.058824, 1, False),
    ('OTS', 'securities-and-exchange-commission', 9, 0, 0.058824, 1, False),
    ('PBGC', 'pension-benefit-guaranty-corporation', 1, 0, 1.0, 5, True),
    ('PCLOB', 'privacy-and-civil-liberties-oversight-board', 1, 0, 1.0, 2, True),
    ('PCSCOTUS', 'general-services-administration', 1, 0, 1.0, 5, True),
    ('PHMSA', 'pipeline-and-hazardous-materials-safety-administration', 1, 1, 0.981087, 830, True),
    ('PHMSA', 'transportation-department', 2, 0, 1.0, 846, False),
    ('PHMSA', 'federal-railroad-administration', 3, 1, 0.003546, 3, False),
    ('PHMSA', 'federal-motor-carrier-safety-administration', 4, 1, 0.001182, 1, False),
    ('PHMSA', 'labor-department', 5, 0, 0.001182, 1, False),
    ('PHMSA', 'occupational-safety-and-health-administration', 6, 1, 0.001182, 1, False),
    ('PTO', 'patent-and-trademark-office', 1, 1, 0.997452, 783, True),
    ('PTO', 'commerce-department', 2, 0, 1.0, 785, False),
    ('PTO', 'national-telecommunications-and-information-administration', 3, 1, 0.005096, 4, False),
    ('PTO', 'copyright-office-library-of-congress', 4, 1, 0.002548, 2, False),
    ('PTO', 'library-of-congress', 5, 0, 0.002548, 2, False),
    ('RBS', 'rural-business-cooperative-service', 1, 1, 1.0, 84, True),
    ('RBS', 'agriculture-department', 2, 0, 1.0, 84, False),
    ('RBS', 'rural-utilities-service', 3, 1, 0.178571, 15, False),
    ('RBS', 'rural-housing-service', 4, 1, 0.107143, 9, False),
    ('RBS', 'commodity-credit-corporation', 5, 1, 0.02381, 2, False),
    ('RBS', 'procurement-and-property-management-office-of', 6, 1, 0.011905, 1, False),
    ('RHS', 'rural-housing-service', 1, 1, 0.992754, 137, True),
    ('RHS', 'agriculture-department', 2, 0, 1.0, 138, False),
    ('RHS', 'rural-business-cooperative-service', 3, 1, 0.028986, 4, False),
    ('RHS', 'rural-utilities-service', 4, 1, 0.021739, 3, False),
    ('RITA', 'transportation-department', 1, 0, 1.0, 29, True),
    ('RITA', 'research-and-innovative-technology-administration', 2, 1, 0.689655, 20, False),
    ('RITA', 'transportation-statistics-bureau', 3, 1, 0.206897, 6, False),
    ('RITA', 'coast-guard', 4, 1, 0.034483, 1, False),
    ('RITA', 'homeland-security-department', 5, 0, 0.034483, 1, False),
    ('RRB', 'railroad-retirement-board', 1, 0, 1.0, 3, True),
    ('RUS', 'rural-utilities-service', 1, 1, 1.0, 120, True),
    ('RUS', 'agriculture-department', 2, 0, 1.0, 120, False),
    ('RUS', 'rural-business-cooperative-service', 3, 1, 0.158333, 19, False),
    ('RUS', 'rural-housing-service', 4, 1, 0.158333, 19, False),
    ('RUS', 'farm-service-agency', 5, 1, 0.008333, 1, False),
    ('SAMHSA', 'substance-abuse-and-mental-health-services-administration', 1, 1, 1.0, 2, True),
    ('SAMHSA', 'health-and-human-services-department', 2, 0, 1.0, 2, False),
    ('SBA', 'small-business-administration', 1, 0, 1.0, 80, True),
    ('SBA', 'treasury-department', 2, 0, 0.0625, 5, False),
    ('SEC', 'securities-and-exchange-commission', 1, 0, 1.0, 245, True),
    ('SEC', 'commodity-futures-trading-commission', 2, 0, 0.016327, 4, False),
    ('SEC', 'comptroller-of-the-currency', 3, 1, 0.004082, 1, False),
    ('SEC', 'consumer-financial-protection-bureau', 4, 0, 0.004082, 1, False),
    ('SEC', 'federal-deposit-insurance-corporation', 5, 0, 0.004082, 1, False),
    ('SEC', 'federal-housing-finance-agency', 6, 0, 0.004082, 1, False),
    ('SEC', 'federal-reserve-system', 7, 0, 0.004082, 1, False),
    ('SEC', 'national-credit-union-administration', 8, 0, 0.004082, 1, False),
    ('SEC', 'treasury-department', 9, 0, 0.004082, 1, False),
    ('SLSDC', 'great-lakes-st-lawrence-seaway-development-corporation', 1, 1, 1.0, 21, True),
    ('SLSDC', 'transportation-department', 2, 0, 0.904762, 19, False),
    ('SRBC', 'susquehanna-river-basin-commission', 1, 0, 1.0, 4, True),
    ('SSA', 'social-security-administration', 1, 0, 1.0, 996, True),
    ('SSA', 'children-and-families-administration', 2, 1, 0.001004, 1, False),
    ('SSA', 'health-and-human-services-department', 3, 0, 0.001004, 1, False),
    ('STB', 'surface-transportation-board', 1, 0, 1.0, 18, True),
    ('TREAS', 'treasury-department', 1, 0, 1.0, 26, True),
    ('TREAS', 'consumer-financial-protection-bureau', 2, 0, 0.115385, 3, False),
    ('TREAS', 'commodity-futures-trading-commission', 3, 0, 0.076923, 2, False),
    ('TREAS', 'comptroller-of-the-currency', 4, 1, 0.076923, 2, False),
    ('TREAS', 'federal-deposit-insurance-corporation', 5, 0, 0.076923, 2, False),
    ('TREAS', 'federal-housing-finance-agency', 6, 0, 0.076923, 2, False),
    ('TREAS', 'federal-reserve-system', 7, 0, 0.076923, 2, False),
    ('TREAS', 'national-credit-union-administration', 8, 0, 0.076923, 2, False),
    ('TREAS', 'securities-and-exchange-commission', 9, 0, 0.076923, 2, False),
    ('TREAS', 'centers-for-medicare-medicaid-services', 10, 1, 0.038462, 1, False),
    ('TREAS', 'health-and-human-services-department', 11, 0, 0.038462, 1, False),
    ('TSA', 'transportation-security-administration', 1, 1, 0.988701, 350, True),
    ('TSA', 'homeland-security-department', 2, 0, 0.923729, 327, False),
    ('TSA', 'transportation-department', 3, 0, 0.081921, 29, False),
    ('TSA', 'federal-aviation-administration', 4, 1, 0.00565, 2, False),
    ('TTB', 'alcohol-and-tobacco-tax-and-trade-bureau', 1, 1, 0.997297, 369, True),
    ('TTB', 'treasury-department', 2, 0, 1.0, 370, False),
    ('TVA', 'tennessee-valley-authority', 1, 0, 1.0, 3, True),
    ('USA', 'army-department', 1, 1, 0.985915, 70, True),
    ('USA', 'defense-department', 2, 0, 1.0, 71, False),
    ('USAF', 'air-force-department', 1, 1, 1.0, 30, True),
    ('USAF', 'defense-department', 2, 0, 1.0, 30, False),
    ('USBC', 'commerce-department', 1, 0, 0.9, 9, True),
    ('USBC', 'census-bureau', 2, 1, 0.6, 6, False),
    ('USBC', 'management-and-budget-office', 3, 0, 0.1, 1, False),
    ('USCBP', 'homeland-security-department', 1, 0, 1.0, 428, True),
    ('USCBP', 'u-s-customs-and-border-protection', 2, 1, 0.897196, 384, False),
    ('USCBP', 'treasury-department', 3, 0, 0.299065, 128, False),
    ('USCBP', 'customs-service', 4, 1, 0.002336, 1, False),
    ('USCBP', 'state-department', 5, 0, 0.002336, 1, False),
    ('USCG', 'coast-guard', 1, 1, 0.991778, 12303, True),
    ('USCG', 'homeland-security-department', 2, 0, 0.969448, 12026, False),
    ('USCG', 'transportation-department', 3, 0, 0.033132, 411, False),
    ('USCG', 'maritime-administration', 4, 1, 0.007739, 96, False),
    ('USCG', 'transportation-security-administration', 5, 1, 0.000645, 8, False),
    ('USCG', 'commerce-department', 6, 0, 0.000161, 2, False),
    ('USCG', 'environmental-protection-agency', 7, 0, 0.000161, 2, False),
    ('USCG', 'national-oceanic-and-atmospheric-administration', 8, 1, 0.000161, 2, False),
    ('USCG', 'energy-department', 9, 0, 8.1e-05, 1, False),
    ('USCG', 'federal-energy-regulatory-commission', 10, 1, 8.1e-05, 1, False),
    ('USCG', 'research-and-innovative-technology-administration', 11, 1, 8.1e-05, 1, False),
    ('USCG', 'state-department', 12, 0, 8.1e-05, 1, False),
    ('USCIS', 'homeland-security-department', 1, 0, 1.0, 55, True),
    ('USCIS', 'u-s-citizenship-and-immigration-services', 2, 1, 0.472727, 26, False),
    ('USCIS', 'executive-office-for-immigration-review', 3, 1, 0.018182, 1, False),
    ('USCIS', 'justice-department', 4, 0, 0.018182, 1, False),
    ('USDA', 'agriculture-department', 1, 0, 1.0, 68, True),
    ('USDA', 'us-codex-office', 2, 1, 0.044118, 3, False),
    ('USDA', 'commodity-credit-corporation', 3, 1, 0.029412, 2, False),
    ('USDA', 'natural-resources-conservation-service', 4, 1, 0.029412, 2, False),
    ('USDA', 'agency-for-international-development', 5, 0, 0.014706, 1, False),
    ('USDA', 'education-department', 6, 0, 0.014706, 1, False),
    ('USDA', 'energy-and-environmental-policy-office', 7, 1, 0.014706, 1, False),
    ('USDA', 'farm-service-agency', 8, 1, 0.014706, 1, False),
    ('USDA', 'federal-crop-insurance-corporation', 9, 1, 0.014706, 1, False),
    ('USDA', 'health-and-human-services-department', 10, 0, 0.014706, 1, False),
    ('USDA', 'homeland-security-department', 11, 0, 0.014706, 1, False),
    ('USDA', 'housing-and-urban-development-department', 12, 0, 0.014706, 1, False),
    ('USDA', 'justice-department', 13, 0, 0.014706, 1, False),
    ('USDA', 'labor-department', 14, 0, 0.014706, 1, False),
    ('USDA', 'rural-business-cooperative-service', 15, 1, 0.014706, 1, False),
    ('USDA', 'rural-housing-service', 16, 1, 0.014706, 1, False),
    ('USDA', 'rural-utilities-service', 17, 1, 0.014706, 1, False),
    ('USDA', 'veterans-affairs-department', 18, 0, 0.014706, 1, False),
    ('USGS', 'geological-survey', 1, 1, 0.972973, 36, True),
    ('USGS', 'interior-department', 2, 0, 1.0, 37, False),
    ('USN', 'defense-department', 1, 0, 1.0, 103, True),
    ('USN', 'navy-department', 2, 1, 0.941748, 97, False),
    ('USPS', 'postal-service', 1, 0, 1.0, 9, True),
    ('USTR', 'trade-representative-office-of-united-states', 1, 0, 1.0, 253, True),
    ('USTR', 'interior-department', 2, 0, 0.003953, 1, False),
    ('USTR', 'state-department', 3, 0, 0.003953, 1, False),
    ('VA', 'veterans-affairs-department', 1, 0, 1.0, 76, True),
    ('VA', 'agency-for-international-development', 2, 0, 0.013158, 1, False),
    ('VA', 'agriculture-department', 3, 0, 0.013158, 1, False),
    ('VA', 'education-department', 4, 0, 0.013158, 1, False),
    ('VA', 'health-and-human-services-department', 5, 0, 0.013158, 1, False),
    ('VA', 'homeland-security-department', 6, 0, 0.013158, 1, False),
    ('VA', 'housing-and-urban-development-department', 7, 0, 0.013158, 1, False),
    ('VA', 'justice-department', 8, 0, 0.013158, 1, False),
    ('VA', 'labor-department', 9, 0, 0.013158, 1, False),
    ('VETS', 'veterans-employment-and-training-service', 1, 1, 1.0, 2, True),
    ('VETS', 'labor-department', 2, 0, 1.0, 2, False),
    ('WAPA', 'western-area-power-administration', 1, 1, 1.0, 1, True),
    ('WAPA', 'energy-department', 2, 0, 1.0, 1, False),
    ('WCPO', 'workers-compensation-programs-office', 1, 1, 1.0, 8, True),
    ('WCPO', 'labor-department', 2, 0, 1.0, 8, False),
    ('WHD', 'labor-department', 1, 0, 1.0, 3, True),
    ('WHD', 'wage-and-hour-division', 2, 1, 0.666667, 2, False),
)

AGENCY_CROSSWALK_CANDIDATES: tuple[AgencyCrosswalkCandidate, ...] = tuple(
    AgencyCrosswalkCandidate(*row) for row in _AGENCY_CROSSWALK_CANDIDATE_ROWS
)

_CANDIDATES_BY_CODE: dict[str, tuple[AgencyCrosswalkCandidate, ...]] = {}
for _candidate in AGENCY_CROSSWALK_CANDIDATES:
    _CANDIDATES_BY_CODE.setdefault(_candidate.agency_code, ())
    _CANDIDATES_BY_CODE[_candidate.agency_code] = (
        *_CANDIDATES_BY_CODE[_candidate.agency_code],
        _candidate,
    )
del _candidate


def candidates_for_code(agency_code: str) -> tuple[AgencyCrosswalkCandidate, ...]:
    """Every ranked candidate slug for one agency code, in sealed rank order."""

    return _CANDIDATES_BY_CODE.get(agency_code, ())


__all__ = [
    "AGENCY_CROSSWALK",
    "AGENCY_CROSSWALK_BY_CODE",
    "AGENCY_CROSSWALK_CANDIDATES",
    "AGENCY_CROSSWALK_INPUT_DIGESTS",
    "AGENCY_CROSSWALK_INPUT_ROW_COUNTS",
    "AGENCY_CROSSWALK_REFERENCE_BUILDER",
    "AGENCY_CROSSWALK_REGENERATION_INPUTS",
    "AGENCY_CROSSWALK_REGENERATION_STATUS",
    "AGENCY_CROSSWALK_SEALED_ARTIFACT_ID",
    "AGENCY_CROSSWALK_SEALED_RECEIPT_PATH",
    "AGENCY_CROSSWALK_TIER_HISTOGRAM",
    "CONFIDENT_SHARE",
    "CROSSWALK_TIERS",
    "DOCKET_DECORATION_PATTERN",
    "DOCKET_NORMALIZATION_RULES",
    "MIN_CONFIDENT_DOCUMENTS",
    "MIN_PROBABLE_DOCUMENTS",
    "PROBABLE_SHARE",
    "SPECIFICITY_MARGIN",
    "AgencyCrosswalkCandidate",
    "AgencyCrosswalkEntry",
    "CrosswalkCandidateShare",
    "CrosswalkTier",
    "DocketAgencyResolution",
    "DocketResolutionStatus",
    "build_normalized_docket_index",
    "candidates_for_code",
    "normalize_docket_id",
    "rank_crosswalk_candidates",
    "resolve_docket_agency_code",
    "tier_for_share",
    "tier_histogram",
]
