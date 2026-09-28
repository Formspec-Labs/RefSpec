"""Assemble batch 1 of the agency registry and the owner's adjudication sheet (candidates, never assertions).

Batch 1 (plans/agency-registry-design.md) proposes, from REF-038's pinned
rosters, ``sameEntityAs`` bridges from Federal Register agencies to the
eCFR/Federal Hierarchy organizations that the 18 non-FR-mapped regulations.gov
codes select, and dated succession events from defunct Federal Register
agencies to their successors. Every row is
``candidate-pending-owner-adjudication`` and carries no reviewer, evidence tier
or decision: the owner (``urn:ref:reviewer:refspec-owner``) is the only
adjudicator, and nothing here is ever emitted as an assertion.

A bridge row carries what a REF-038 assertion would seal -- a typed basis from
the closed ``AgencyDecisionBasis`` vocabulary, both publishers' sealed names
(the field REF-038's ``publisher_name`` seals, never a display label) and both
structured parents -- so the owner approves text a release can reproduce. eCFR
bridges are *found* by slug equality, which REF-038 refuses as a basis, so the
basis submitted is publisher evidence. A succession is an event: one key per
defunct organization and one decision spanning every successor row, so no
successor can be accepted alone.

The candidates come from the rosters alone, and ``candidates_digest`` covers
only them. Live counts come from the replay snapshot named by
``--replay-root`` (required); its digest, never its path, is recorded beside
them. What each candidate would do under spicy-regs' own resolution rule is
measured outside this repository and read from ``--rule-effects`` as a file
(spicy-regs is never imported); the tool refuses a measurement taken against
another candidate set, replay, or spicy-regs commit. ``--check`` re-derives
the JSON, the table and the adjudication sheet byte for byte.

The owner's answers live in plans/agency-registry-batch-1-decisions.json, which
the tool only reads: each decision is keyed by candidate or event id and bound
to that item's own ``content_digest``, re-rendered into the sheet, shown as
stale (never dropped) once its own item changes, and refused when its id is
unknown. ``--check-committed`` is what CI can run without the replay or the
rule effects.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, NamedTuple

from refspec.atlas import agency_projection
from refspec.atlas import v3_registry_alignments_entity as entity_alignments
from refspec.atlas.v3_source_data import RegistryRelease, RegistryResource

try:
    from tools import analyze_agency_roster_identifiers as census
except ImportError:  # Direct execution places tools/ on sys.path.
    import analyze_agency_roster_identifiers as census

CANDIDATE_STATUS = "candidate-pending-owner-adjudication"
OWNER_REVIEWER_IRI = entity_alignments.AGENCY_REGISTRY_REVIEWER_IRI
REPORT_JSON = Path("plans/agency-registry-batch-1-candidates.json")
REPORT_MARKDOWN = Path("plans/agency-registry-batch-1-candidates.md")
ADJUDICATION_MARKDOWN = Path("plans/agency-registry-batch-1-adjudication.md")
DECISIONS_JSON = Path("plans/agency-registry-batch-1-decisions.json")
DESIGN_NOTE = Path("plans/agency-registry-design.md")
# The owner's decision contract lives beside the release that reads it
# (v3_registry_alignments_entity), so the release and this sheet agree by
# construction; these names stay importable from here.
DECISIONS_SCHEMA_VERSION = entity_alignments.DECISIONS_SCHEMA_VERSION
DECISION_CHANNELS = entity_alignments.DECISION_CHANNELS
Decisions = entity_alignments.Decisions
NO_DECISIONS = entity_alignments.NO_DECISIONS
decision_digests = entity_alignments.decision_digests
decision_answers = entity_alignments.decision_answers
load_decisions = entity_alignments.load_decisions
# spicy-regs' side of the rule effects, pinned as design note section 9 cites it; the
# module digest catches a measurement run from an uncommitted spicy-regs tree.
SPICY_REGS_COMMIT = "680009a5b761bc07c955d0c23fe56fd0799fa4ec"
SPICY_REGS_VENDORED_PROJECTION_SHA256 = "sha256:c9ec0fde1bf5fda17402983880bc091e9caa417845178f232214606e264c049f"
SPICY_REGS_AGENCIES_MODULE_SHA256 = "sha256:613004c3155bb1369b88b6ebb20d61d774e894deb599103b9faa900ffba80cb6"
# The measurement itself lives outside RefSpec (REF-024) and lands in spicy-regs at this path.
MEASUREMENT_SCRIPT = "scripts/measure_agency_registry_effects.py"
MEASUREMENT_SCRIPT_SHA256 = "sha256:0c31ebffa9de5133ee9f7432d1513f7b919c48b14a24a6a878b3ae048990bae7"
# The effect note reads the measured effects, so it stays outside what a decision binds to.
_OUTSIDE_CONTENT = frozenset({"content_digest", "effect_note"})
SCHEMA_VERSION = "refspec-agency-registry-batch-1-candidates/4"
FR_PARQUET = "federal_register.parquet"
CANDIDATES_DIGEST_COVERS = entity_alignments.CANDIDATES_DIGEST_COVERS

FR = agency_projection.FR_RELEASE_KEY
FH = agency_projection.FH_RELEASE_KEY
ECFR = agency_projection.ECFR_RELEASE_KEY
ROSTER_NAMES = {
    FR: "federal-register-agencies",
    FH: "federal-hierarchy-organizations",
    ECFR: "ecfr-agencies",
}
ROSTER_LABELS = {FR: "FR", FH: "Federal Hierarchy", ECFR: "eCFR"}
IRI_PREFIXES = {
    FR: "urn:ref:federal-register-agency:",
    FH: "urn:ref:federal-hierarchy-org:",
    ECFR: "urn:ref:ecfr-agency:",
}
ID_TOKENS = {FR: "fr", FH: "fh:", ECFR: "ecfr:"}

SLUG_FINDING_NOTE = (
    "Found by exact slug equality between the two rosters, which is only the "
    "search rule: REF-038 refuses equal strings from different identifier "
    "authorities (Federal Register slug versus eCFR slug among them), so the "
    "basis submitted is the publisher evidence REF-038 admits instead."
)
PAIRING_FINDING_NOTE = (
    "The Federal Hierarchy carries no slug, so no mechanical equality joins it "
    "to the Federal Register; this pairing is the tool's reviewed data."
)


@dataclass(frozen=True, slots=True)
class Rejected:
    """The closest rejected alternative; ``status_quo`` rows leave FR mentions unreached."""

    description: str
    why_rejected: str
    status_quo: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "description": self.description,
            "why_rejected": self.why_rejected,
            "leaves_fr_mentions_unreached": self.status_quo,
        }


@dataclass(frozen=True, slots=True)
class OwnerQuestion:
    """A judgment the sheet asks as options, none of them presupposed."""

    question: str
    options: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {"question": self.question, "options": list(self.options)}


@dataclass(frozen=True, slots=True)
class IdentityBridge:
    """One proposed FR-to-eCFR/FH ``sameEntityAs`` bridge, in REF-038's assertion shape."""

    fr_agency_id: int
    target_release_key: str
    target_key: str  # eCFR slug or Federal Hierarchy org id
    basis: entity_alignments.AgencyDecisionBasis | None  # None: held, see ``hold``
    reasoning: str
    rejected: Rejected
    owner_question: OwnerQuestion | None = None
    hold: str | None = None  # why no basis in REF-038's vocabulary fits
    alternative_basis: entity_alignments.AgencyDecisionBasis | None = None
    effect_note: str | None = None  # how to read the measured effect, where it misleads


def _status_quo(fr_id: int, code: str, target: str) -> Rejected:
    return Rejected(
        description="Leave the Federal Register agency unbridged (status quo).",
        why_rejected=(
            f"No regulations.gov code reaches FR {fr_id} today -- {code} selects "
            f"only the {target} record -- so the status quo keeps the Federal "
            "Register agency unreached and the two rosters' records of one "
            "organization unjoined."
        ),
        status_quo=True,
    )


def _subunit_rejection(other_id: int, other_name: str, short_name: str, relation: str) -> Rejected:
    return Rejected(
        description=f"FR {other_id} ({other_name}, short name {short_name}) shares the publisher short name.",
        why_rejected=(
            f"FR {other_id} is {relation}; bridging across that parent/subunit "
            "pair folds structure into identity, the broader-record move "
            "REF-038's subunit rule refuses."
        ),
    )


def _predecessor_rejection(other_id: int, other_name: str, short_name: str) -> Rejected:
    return Rejected(
        description=f"FR {other_id} ({other_name}, short name {short_name}) shares the publisher short name.",
        why_rejected=(
            f"FR {other_id} is not a coincidence but the defunct predecessor: "
            f"event:fr{other_id} separately proposes its succession, so the two "
            "records join through that dated event, not through a shared short name."
        ),
    )


# eCFR bridges were found by slug equality; FH bridges are reviewed pairings.
# Each reasoning names both sealed publisher names verbatim (checked at
# assembly), so the release can reproduce the text the owner approves.
IDENTITY_BRIDGES = (
    IdentityBridge(
        118,
        ECFR,
        "economic-analysis-bureau",
        "obviousPublisherNameVariant",
        (
            "The eCFR name Bureau of Economic Analysis is the Federal Register "
            "name Economic Analysis Bureau in ordinary word order, and both "
            "publishers place the bureau under the Commerce department."
        ),
        Rejected(
            "FR 150 (Export Administration Bureau, short name EAB) shares the publisher short name.",
            (
                "The two are sibling bureaus under Commerce with different "
                "publisher names; the shared short name EAB is a genuine acronym "
                "collision, and REF-038 bridges no identity on a short name alone."
            ),
        ),
    ),
    IdentityBridge(
        136,
        ECFR,
        "energy-department",
        "obviousPublisherNameVariant",
        (
            "Department of Energy is Energy Department in ordinary word order, and "
            "both records are top-level organizations with no parent."
        ),
        _subunit_rejection(137, "Energy Efficiency and Renewable Energy Office", "DOE", "a subunit of FR 136"),
    ),
    IdentityBridge(
        151,
        ECFR,
        "export-import-bank",
        "obviousPublisherNameVariant",
        (
            "Export-Import Bank and Export-Import Bank of the United States are "
            "the short and full legal names of one bank, and both records are "
            "top-level organizations with no parent."
        ),
        Rejected(
            "Keep FR 151 reached only through USEIB and leave the eCFR bank record unjoined.",
            (
                "Nothing is unreached today -- USEIB reaches FR 151 and EIB the "
                "eCFR record -- so the bridge adds no reach to a Federal Register "
                "id; it joins two rosters' records of one bank, and in exchange FR "
                "151 becomes ambiguous (EIB, USEIB) in the reverse lookup. Which "
                "trade is right is the owner's question on this row."
            ),
        ),
        OwnerQuestion(
            (
                "FR 151 Export-Import Bank and eCFR Export-Import Bank of the United "
                "States: are they the same organization, and is joining them worth "
                "the reverse-lookup cost?"
            ),
            (
                "Not the same organization: reject the bridge.",
                (
                    "The same organization, but reject the reverse-lookup cost: no "
                    "bridge, FR 151 stays resolved through USEIB alone."
                ),
                "Accept the bridge: FR 151 becomes ambiguous (EIB, USEIB) in the reverse lookup.",
            ),
        ),
    ),
    IdentityBridge(
        186,
        ECFR,
        "federal-register-office",
        "obviousPublisherNameVariant",
        (
            "Office of Federal Register is Federal Register Office in ordinary "
            "word order, and both publishers place the office under the National "
            "Archives and Records Administration."
        ),
        Rejected(
            "FR 574 (Financial Research Office, short name OFR) shares the publisher short name.",
            (
                "FR 574 is Treasury's financial-research office, an unrelated "
                "organization that shares the OFR acronym; the publisher names and "
                "parents differ."
            ),
        ),
    ),
    IdentityBridge(
        244,
        FH,
        "100006936",
        "publisherNameWithParentContext",
        (
            "The Federal Hierarchy's OFFICE OF INSPECTOR GENERAL is generic on its "
            "own; its parent, the Agriculture department, selects the one "
            "inspector-general office the Federal Register names Inspector General "
            "Office, Agriculture Department."
        ),
        Rejected(
            "Bridge USDAIG to the Agriculture department itself (FR 12), the department the office sits under.",
            (
                "The Federal Hierarchy record is the inspector general's office, a "
                "subunit, not the department; the parent would absorb the office "
                "the code selects, the broader-record move REF-038 refuses."
            ),
        ),
    ),
    IdentityBridge(
        245,
        FH,
        "100004455",
        "publisherNameWithParentContext",
        (
            "The Federal Hierarchy's OFFICE OF THE INSPECTOR GENERAL is generic on "
            "its own; its parent, the Health and Human Services department, "
            "selects the one inspector-general office the Federal Register names "
            "Inspector General Office, Health and Human Services Department."
        ),
        Rejected(
            "Bridge HHSIG to the HHS department itself (FR 221), the department the office sits under.",
            (
                "The Federal Hierarchy record is the inspector general's office, a "
                "subunit, not the department; a bridge to the parent would erase "
                "the office the code selects, the move REF-038's subunit rule refuses."
            ),
        ),
    ),
    IdentityBridge(
        271,
        ECFR,
        "labor-department",
        "obviousPublisherNameVariant",
        (
            "Department of Labor is Labor Department in ordinary word order, and "
            "both records are top-level organizations with no parent."
        ),
        _subunit_rejection(134, "Employment Standards Administration", "DOL", "a subunit of FR 271"),
    ),
    IdentityBridge(
        277,
        ECFR,
        "library-of-congress",
        "exactPublisherNameEquality",
        (
            "Both publishers carry the identical name Library of Congress, and "
            "both records are top-level organizations with no parent."
        ),
        _subunit_rejection(88, "Copyright Royalty Board", "LOC", "a subunit of FR 277"),
    ),
    IdentityBridge(
        296,
        FH,
        "300000070",
        None,
        (
            "The Federal Hierarchy still carries MORRIS K. UDALL SCHOLARSHIP AND "
            "EXCELLENCE IN NATIONAL ENVIRONMENTAL POLICY FOUNDATION, the name "
            "Pub. L. 111-90 sec. 5 (2009-11-03, "
            "https://www.congress.gov/111/plaws/publ90/PLAW-111publ90.htm) "
            "replaced in place with Morris K. Udall and Stewart L. Udall "
            "Foundation; under the rename rule a stale name in another roster is "
            "identity evidence, not a succession. REF-038 uses "
            "obviousPublisherNameVariant only for case, word-order or qualifier "
            "differences, and its evidence has no field for a statute, so the row "
            "is held for a vocabulary amendment rather than stretched to fit. The "
            "Federal Hierarchy's duplicate Sub-Tier 300000385 under the same "
            "department is not the bridged record."
        ),
        Rejected(
            (
                "Read the Federal Hierarchy record as a different, pre-2009 "
                "organization and key the FR agency from the Federal Register side."
            ),
            (
                "Pub. L. 111-90 renamed one foundation in place; it chartered no "
                "second one, so two rows would split a continuing entity."
            ),
        ),
        OwnerQuestion(
            (
                "Is the Federal Hierarchy's MORRIS K. UDALL SCHOLARSHIP AND "
                "EXCELLENCE IN NATIONAL ENVIRONMENTAL POLICY FOUNDATION "
                "(300000070) the foundation FR 296 publishes as Morris K. Udall and "
                "Stewart L. Udall Foundation, renamed in place by Pub. L. 111-90 "
                "sec. 5 (2009-11-03)?"
            ),
            (
                (
                    "Proposed: the same foundation, held for a vocabulary amendment -- "
                    "a statutory-rename basis carrying the public record."
                ),
                (
                    "The same foundation, accepted now under obviousPublisherNameVariant "
                    "(stretching it beyond case, word order and qualifiers)."
                ),
                "Not the same organization: FR 296 is keyed from the Federal Register side in batch 2.",
            ),
        ),
        hold=(
            "vocabularyAmendment: a statutory-rename basis carrying the public "
            "record, which REF-038's AgencyDecisionBasis lacks"
        ),
        alternative_basis="obviousPublisherNameVariant",
    ),
    IdentityBridge(
        4,
        ECFR,
        "african-development-foundation",
        "obviousPublisherNameVariant",
        (
            "The eCFR name African Development Foundation omits only the country "
            "prefix of the Federal Register name United States African "
            "Development Foundation, and both records are top-level "
            "organizations with no parent."
        ),
        _status_quo(4, "ADF", "eCFR"),
    ),
    IdentityBridge(
        409,
        ECFR,
        "postal-regulatory-commission",
        "exactPublisherNameEquality",
        (
            "Both publishers carry the identical name Postal Regulatory "
            "Commission, and both records are top-level organizations with no parent."
        ),
        Rejected(
            "FR 564 (Postal Rate Commission, short name PRC) shares the publisher short name.",
            (
                "Not a coincidence, and not decided here: the event:fr564 row asks "
                "whether 564 is the predecessor or a duplicate, so the two records "
                "join through that decision, not through a shared short name."
            ),
        ),
    ),
    IdentityBridge(
        503,
        FH,
        "100012075",
        "obviousPublisherNameVariant",
        (
            "U.S. IMMIGRATION AND CUSTOMS ENFORCEMENT and U.S. Immigration and "
            "Customs Enforcement differ only in letter case, and both publishers "
            "place the agency under the Homeland Security department."
        ),
        Rejected(
            "Treat ICEB as unreachable and key ICE from the Federal Register side in batch 2.",
            "Both rosters publish one name under one parent; the pairing needs no new entity, only the join.",
        ),
        effect_note=(
            "The USCBP→TREAS line in its effect with the rest of batch 1 is the "
            "Customs Service's own documents: once ICE has a code, event:fr96's two "
            "results carry two codes, so those documents keep Treasury's code -- "
            "the same code they resolve to today. No CBP document moves."
        ),
    ),
    IdentityBridge(
        587,
        FH,
        "100525875",
        "obviousPublisherNameVariant",
        (
            "ADMINISTRATION FOR COMMUNITY LIVING (ACL) is Community Living "
            "Administration in ordinary word order with its acronym appended, and "
            "both publishers place it under the Health and Human Services department."
        ),
        Rejected(
            "Key the Administration for Community Living from the Federal Register side (batch 2).",
            (
                "Both rosters already publish the organization; a batch-2 row "
                "would duplicate the entity the code ACL selects instead of "
                "joining the two published names."
            ),
        ),
    ),
    IdentityBridge(
        603,
        ECFR,
        "investment-security-office",
        "obviousPublisherNameVariant",
        (
            "Office of Investment Security is Investment Security Office in "
            "ordinary word order, and both publishers place the office under the "
            "Treasury department."
        ),
        _predecessor_rejection(259, "International Investment Office", "IIO"),
    ),
    IdentityBridge(
        88,
        ECFR,
        "copyright-royalty-board",
        "exactPublisherNameEquality",
        (
            "Both publishers carry the identical name Copyright Royalty Board, "
            "and both place the board under the Library of Congress."
        ),
        _subunit_rejection(277, "Library of Congress", "LOC", "the parent of FR 88"),
    ),
)


@dataclass(frozen=True, slots=True)
class NonEmission:
    """A withdrawn proposal, recorded so a later batch revisits it instead of re-deriving it."""

    fr_agency_id: int
    target_release_key: str
    target_key: str
    reason: str
    closest_alternative: Mapping[str, str]


NON_EMISSIONS = (
    NonEmission(
        255,
        ECFR,
        "international-boundary-and-water-commission-united-states-and-mexico",
        (
            "Withdrawn: the row rested on slug equality, and the names differ in "
            "scope, not spelling -- FR 255, International Boundary and Water "
            "Commission, United States and Mexico, names the binational commission, "
            "which the Federal Register's own description calls 'an international "
            "body composed of the United States Section and the Mexican Section'; "
            "the eCFR record, United States Section United States and Mexico "
            "International Boundary and Water Commission, names one of those "
            "sections (REF-038 already maps MEXICO to it). Under REF-038's subunit "
            "rule the broader record justifies no identity with its section."
        ),
        {
            "relation": "partOf",
            "description": (
                "eCFR United States Section United States and Mexico International "
                "Boundary and Water Commission partOf FR 255 International Boundary "
                "and Water Commission, United States and Mexico."
            ),
            "why_not_proposed": (
                "The registry mints no cross-roster partOf yet (design note "
                "section 3); the structure goes through the owner loop in a later "
                "batch, and until then FR 255 is keyed from the Federal Register "
                "side in batch 2."
            ),
        },
    ),
)

NO_FR_BRIDGE = (
    {
        "value_id": "no-fr-bridge:regs:CISA",
        "value": "CISA",
        "roster": "regulations-gov-agencies",
        "reason": "noCounterpartInHeldFRRoster",
        "reason_in_ref038_vocabulary": False,
        "reasoning": (
            "REF-038 resolves code CISA to Federal Hierarchy org 500044551, "
            "Cybersecurity and Infrastructure Security Agency; that stays. The held "
            "Federal Register roster (472 resources, captured 2026-08-15) contains "
            "no CISA resource under any name or acronym, so no FR bridge can be "
            "proposed. The reason noCounterpartInHeldFRRoster is a new value, "
            "outside REF-038's AbstentionReason vocabulary; CISA is not an abstention."
        ),
        "status": CANDIDATE_STATUS,
    },
)


@dataclass(frozen=True, slots=True)
class PublicRecord:
    """One citable public record for a succession."""

    kind: Literal["statute", "reorganizationPlan", "frNotice", "frDocument", "publisherRoster"]
    citation: str
    url: str
    note: str

    def to_dict(self) -> dict[str, str]:
        return {"kind": self.kind, "citation": self.citation, "url": self.url, "note": self.note}


@dataclass(frozen=True, slots=True)
class SuccessorRow:
    """One resulting organization of a succession event, with what it took and why."""

    successor_fr_id: int
    functions_taken: str | None
    records: tuple[PublicRecord, ...]
    reasoning: str
    rejected: Rejected
    original_fr_id: int | None = None  # required only when the event has several originals


@dataclass(frozen=True, slots=True)
class SuccessionEvent:
    """One dated change event: its defunct original organizations and every resulting one.

    Several originals make a merger (PPRC and ProPAC into MedPAC); a row names
    its original when there is more than one.
    """

    originals: tuple[int, ...]
    effective_date: str
    date_basis: str
    rows: tuple[SuccessorRow, ...]
    date_alternatives: tuple[tuple[str, str], ...] = ()
    owner_note: str | None = None
    owner_question: OwnerQuestion | None = None


# Verified against the publishers (each URL fetched and read in context); the
# dates are the operative dates the records state, each labelled with its kind.
HSA = PublicRecord(
    "statute",
    "Homeland Security Act of 2002, Pub. L. 107-296, 116 Stat. 2135",
    "https://www.congress.gov/107/plaws/publ296/PLAW-107publ296.htm",
    "Enacted 2002-11-25; sec. 4 sets the Act's effective date 60 days later.",
)
HDOC_108_32 = PublicRecord(
    "reorganizationPlan",
    "Reorganization Plan Modification for the Department of Homeland Security, H. Doc. 108-32 (108th Congress)",
    "https://www.govinfo.gov/content/pkg/CDOC-108hdoc32/pdf/CDOC-108hdoc32.pdf",
    (
        "The President's plan modification under HSA sec. 1502, effective "
        "2003-03-01. Subsection (a) builds the interior-enforcement bureau "
        "(Immigration and Customs Enforcement) around the transferred "
        "investigation, detention-and-removal, and intelligence programs; "
        "subsection (b) builds the Bureau of Customs and Border Protection around "
        "the border inspections program, including the Border Patrol."
    ),
)
INS_TRANSFER_NOTICE = PublicRecord(
    "frNotice",
    (
        "68 FR 10922 (2003-03-06), FR Doc 03-5146, Authority of the Secretary of "
        "Homeland Security; Delegations of Authority; Immigration Laws"
    ),
    (
        "https://www.federalregister.gov/documents/2003/03/06/03-5146/"
        "authority-of-the-secretary-of-homeland-security-delegations-of-authority-immigration-laws"
    ),
    "States that the INS functions transfer to DHS on March 1, 2003, and that the INS is abolished on that date.",
)
REORG_MODIFICATION = PublicRecord(
    "frNotice",
    (
        "68 FR 51868 (2003-08-28), FR Doc 03-21995, Delegations of Authority: "
        "Signature of Customs and Border Protection Regulations"
    ),
    (
        "https://www.federalregister.gov/documents/2003/08/28/03-21995/"
        "delegations-of-authority-signature-of-customs-and-border-protection-"
        "regulations-published-in-the"
    ),
    (
        "Recites the Reorganization Plan Modification effective March 1, 2003, "
        "which renamed the Bureau of Border Security as Immigration and Customs "
        "Enforcement (ICE brings together the investigation arms of the former "
        "Customs Service and the investigative functions of the former INS), "
        "records that the United States Customs Service 'is now known as the "
        "bureau of Customs and Border Protection', and recites that HSA sec. 412 "
        "keeps the Secretary of the Treasury's legal authority over customs "
        "revenue functions."
    ),
)
INS_SPLIT_REJECTED = Rejected(
    "A single succession from INS to the DHS department (FR 227).",
    (
        "The Homeland Security Act did not move INS into DHS whole: sec. 441 "
        "transfers its programs, sec. 451 builds the services bureau, sec. 471 "
        "abolishes INS only 'upon completion of all transfers', and the "
        "Reorganization Plan Modification effective 2003-03-01 split the programs "
        "across three components. One result at the department would misroute "
        "every pre-2003 INS document to an entity that never published it."
    ),
)
ICCTA = PublicRecord(
    "statute",
    "ICC Termination Act of 1995, Pub. L. 104-88, 109 Stat. 803, secs. 2, 101, 103, 201, 203, 205, 314-316",
    "https://www.congress.gov/104/plaws/publ88/PLAW-104publ88.htm",
    (
        "Sec. 101 abolishes the Interstate Commerce Commission; sec. 2 makes the "
        "Act effective 1996-01-01; title II charters the Surface Transportation "
        "Board; sec. 203 moves the Commission's assets and personnel for Board "
        "functions to the Board (203(a)) and for Secretary functions to the "
        "Secretary of Transportation (203(b)); the recodified motor-carrier part "
        "vests in the Secretary (49 U.S.C. 13301(a)); sec. 205 deems references to "
        "the ICC to refer to the Board or the Secretary, as appropriate; secs. "
        "314-316 strike 'Interstate Commerce Commission' from the Fair Credit "
        "Reporting, Equal Credit Opportunity, and Fair Debt Collection Practices "
        "Acts and insert 'Secretary of Transportation, with respect to all "
        "carriers subject to the jurisdiction of the Surface Transportation Board'."
    ),
)
ICC_SPLIT_REJECTED = Rejected(
    "A single succession from the ICC to the Department of Transportation (FR 492) alone.",
    (
        "ICCTA sec. 101 abolished the Commission; sec. 203 splits the aftermath "
        "into two streams (assets and personnel for Board functions to the Board, "
        "for Secretary functions to the Secretary) and sec. 205 deems references "
        "to the ICC to mean the Board or the Secretary 'as appropriate'. The "
        "functions genuinely divided, and the Board is an independent decisional "
        "body, not the department acting."
    ),
)
FARRA = PublicRecord(
    "statute",
    (
        "Foreign Affairs Reform and Restructuring Act of 1998, div. G of Pub. L. "
        "105-277, 112 Stat. 2681-761, secs. 1301, 1311, 1312, 1322"
    ),
    "https://www.govinfo.gov/content/pkg/PLAW-105publ277/html/PLAW-105publ277.htm",
    (
        "Sec. 1301 makes the title effective on the earlier of 1999-10-01 or the "
        "date of abolition under the sec. 1601 reorganization plan; sec. 1311 "
        "abolishes the United States Information Agency 'other than the "
        "Broadcasting Board of Governors and the International Broadcasting "
        "Bureau'; sec. 1312(a) transfers all its functions to the Secretary of "
        "State and 1312(b) excepts the Board, the Bureau, and their functions; "
        "sec. 1322 amends 22 U.S.C. 6203(a) so the Board 'shall continue to exist "
        "within the Executive branch' as an independent establishment (5 U.S.C. 104)."
    ),
)

SUCCESSION_EVENTS = (
    SuccessionEvent(
        (150,),
        "2002-04-18",
        "the Commerce organizational order's date, on which the name-change rule took effect",
        (
            SuccessorRow(
                241,
                None,
                (
                    PublicRecord(
                        "frNotice",
                        "67 FR 20630 (2002-04-26), FR Doc 02-10166, Industry and Security Programs; Change of Agency Name",
                        (
                            "https://www.federalregister.gov/documents/2002/04/26/02-10166/"
                            "industry-and-security-programs-change-of-agency-name"
                        ),
                        (
                            "Records that Commerce changed the Bureau of Export "
                            "Administration's name to the Bureau of Industry and "
                            "Security by internal organizational order on "
                            "2002-04-18 and makes the rule effective that day, "
                            "preserving all prior actions under the new name."
                        ),
                    ),
                ),
                (
                    "Commerce renamed the Bureau of Export Administration the Bureau "
                    "of Industry and Security by organizational order effective "
                    "2002-04-18; the Federal Register roster keeps the old name on "
                    "FR 150 and the new one on FR 241."
                ),
                Rejected(
                    "Export Administration Bureau sameEntityAs Industry and Security Bureau, folded into identity.",
                    (
                        "The rename has a date the public record states; identity "
                        "would misdate documents under the old name, and FR 150's "
                        "short name EAB, shared with the Economic Analysis Bureau "
                        "(FR 118), shows how wrong an acronym-level identity would be."
                    ),
                ),
            ),
        ),
    ),
    SuccessionEvent(
        (232,),
        "2003-03-01",
        "the transfer-and-abolition date the delegation rule and the reorganization plan state",
        (
            SuccessorRow(
                499,
                "immigration services and adjudications (the services bureau HSA sec. 451 establishes)",
                (HSA, INS_TRANSFER_NOTICE),
                (
                    "HSA sec. 451 established the Bureau of Citizenship and "
                    "Immigration Services for the service functions; the delegation "
                    "rule records the transfer of all INS functions to DHS and the "
                    "INS's abolition on 2003-03-01."
                ),
                INS_SPLIT_REJECTED,
            ),
            SuccessorRow(
                501,
                "the Border Patrol and the inspections program (H. Doc. 108-32 subsection (b))",
                (HSA, HDOC_108_32, INS_TRANSFER_NOTICE, REORG_MODIFICATION),
                (
                    "HSA sec. 441 transfers the Border Patrol and inspections "
                    "programs; the plan's subsection (b) places them in the Bureau of "
                    "Customs and Border Protection it builds, effective 2003-03-01."
                ),
                INS_SPLIT_REJECTED,
            ),
            SuccessorRow(
                503,
                "investigations, detention and removal, and intelligence (H. Doc. 108-32 subsection (a))",
                (HSA, HDOC_108_32, INS_TRANSFER_NOTICE, REORG_MODIFICATION),
                (
                    "HSA sec. 441 transfers the investigations, detention-and-removal "
                    "and intelligence programs; the plan's subsection (a) builds "
                    "Immigration and Customs Enforcement around them, effective "
                    "2003-03-01, and 68 FR 51868 records that ICE brings together "
                    "those investigative functions of the former INS."
                ),
                INS_SPLIT_REJECTED,
            ),
        ),
    ),
    SuccessionEvent(
        (259,),
        "2008-11-21",
        "the change date the Federal Register roster states, the day E8-27525 published the renamed heading",
        (
            SuccessorRow(
                603,
                None,
                (
                    PublicRecord(
                        "publisherRoster",
                        "Federal Register agency roster description of 259, International Investment Office",
                        "https://www.federalregister.gov/agencies/international-investment-office",
                        "The publisher's own roster description: 'Name changed Nov. 21, 2008 (73 FR 70716) to Office of Investment Security.'",
                    ),
                    PublicRecord(
                        "frNotice",
                        (
                            "73 FR 70702 (2008-11-21), FR Doc E8-27525, Regulations "
                            "Pertaining to Mergers, Acquisitions, and Takeovers by "
                            "Foreign Persons"
                        ),
                        (
                            "https://www.federalregister.gov/documents/2008/11/21/"
                            "E8-27525/regulations-pertaining-to-mergers-acquisitions-and-"
                            "takeovers-by-foreign-persons"
                        ),
                        (
                            "Spans 73 FR 70702-70729; its page 70716 -- the page the "
                            "roster cites -- revises the heading of 31 CFR chapter VIII "
                            "to 'Office of Investment Security, Department of the "
                            "Treasury'. Published 2008-11-21, effective 2008-12-22."
                        ),
                    ),
                    PublicRecord(
                        "frDocument",
                        "73 FR 21861 (2008-04-23), FR Doc 08-1172, Regulations Pertaining to Mergers, Acquisitions, and Takeovers by Foreign Persons",
                        (
                            "https://www.federalregister.gov/documents/2008/04/23/08-1172/"
                            "regulations-pertaining-to-mergers-acquisitions-and-takeovers-by-foreign-persons"
                        ),
                        "The last document the Federal Register files under the old name (the publisher's API, newest first).",
                    ),
                ),
                (
                    "The Federal Register roster's own description of FR 259 records "
                    "the change to the Office of Investment Security, citing 73 FR "
                    "70716, a page inside rule E8-27525; both records sit under the "
                    "Treasury department."
                ),
                Rejected(
                    "International Investment Office sameEntityAs Investment Security Office, folded into identity.",
                    (
                        "The rename carries a date the publisher states; identity "
                        "would misdate the documents under the old name and discard "
                        "the date the roster itself records."
                    ),
                ),
            ),
        ),
        date_alternatives=(
            (
                "2008-12-22",
                (
                    "a CFR-heading date: 73 FR 70716, the page the roster cites, is "
                    "inside E8-27525, whose chapter-heading revision took effect with "
                    "the rule -- the same kind of date set aside for PWBA (2003-04-03) "
                    "and HCFA (2001-07-31)"
                ),
            ),
        ),
        owner_note="The last document under the old name is FR Doc 08-1172 (73 FR 21861, 2008-04-23).",
    ),
    SuccessionEvent(
        (404,),
        "2003-02-03",
        "the Secretary's Order's effective date, 'upon the date of publication in the Federal Register'",
        (
            SuccessorRow(
                131,
                None,
                (
                    PublicRecord(
                        "frNotice",
                        (
                            "68 FR 5374 (2003-02-03), FR Doc 03-2163, Secretary's Order "
                            "1-2003: Delegation of Authority and Assignment of "
                            "Responsibilities to the Employee Benefits Security "
                            "Administration"
                        ),
                        (
                            "https://www.federalregister.gov/documents/2003/02/03/03-2163/"
                            "delegation-of-authority-and-assignment-of-responsibilities-to-"
                            "the-employee-benefits-security"
                        ),
                        (
                            "Secretary of Labor's Order 1-2003 redesignates the Pension "
                            "and Welfare Benefits Administration as the Employee "
                            "Benefits Security Administration, signed 2003-01-23 and "
                            "effective on publication, 2003-02-03."
                        ),
                    ),
                    PublicRecord(
                        "frNotice",
                        "68 FR 16399 (2003-04-03), FR Doc 03-8099, Change of Agency Name; Technical Amendments",
                        (
                            "https://www.federalregister.gov/documents/2003/04/03/03-8099/"
                            "change-of-agency-name-technical-amendments"
                        ),
                        (
                            "The conforming CFR record, revising 29 CFR chapter XXV "
                            "effective 2003-04-03 -- carried only as the CFR conforming "
                            "date, not the rename date."
                        ),
                    ),
                ),
                (
                    "Secretary of Labor's Order 1-2003 renamed the Pension and "
                    "Welfare Benefits Administration the Employee Benefits Security "
                    "Administration, effective on publication 2003-02-03; the CFR "
                    "conforming amendments followed effective 2003-04-03."
                ),
                Rejected(
                    "Pension and Welfare Benefits Administration sameEntityAs Employee Benefits Security Administration.",
                    "The rename has a stated effective date; identity would erase it and misdate the documents under each name.",
                ),
            ),
        ),
    ),
    SuccessionEvent(
        (510,),
        "1999-10-01",
        "FARRA sec. 1301's effective date, the earlier of 1999-10-01 or the sec. 1601 plan's abolition date",
        (
            SuccessorRow(
                476,
                (
                    "every USIA function other than broadcasting: all functions of the "
                    "Director and of the agency, transferred to the Secretary of State "
                    "(FARRA sec. 1312(a))"
                ),
                (FARRA,),
                (
                    "The 1998 restructuring Act abolished USIA and vested every "
                    "remaining function in the Secretary of State, effective "
                    "1999-10-01 under sec. 1301's default; if the owner holds that the "
                    "plan abolished USIA earlier, the owner fixes that date."
                ),
                Rejected(
                    "United States Information Agency sameEntityAs State Department, folded into identity.",
                    (
                        "An agency was abolished into a department, not renamed; "
                        "identity would equate a subunit's functions with the "
                        "absorbing department, and the broadcasting exception means "
                        "part of USIA never went to State."
                    ),
                ),
            ),
            SuccessorRow(
                41,
                (
                    "international broadcasting, which the Board already held inside "
                    "USIA and kept: sec. 1311 excepts the Board and the International "
                    "Broadcasting Bureau from the abolition, sec. 1312(b) keeps them "
                    "and their functions out of the transfer to State, and sec. 1322 "
                    "continues the Board as an independent establishment"
                ),
                (
                    FARRA,
                    PublicRecord(
                        "publisherRoster",
                        "Federal Register agency roster description of 41, Broadcasting Board of Governors",
                        "https://www.federalregister.gov/agencies/broadcasting-board-of-governors",
                        (
                            "The publisher's own roster description: the Board "
                            "'became an independent agency on October 1, 1999, by "
                            "authority of the Foreign Affairs Reform and "
                            "Restructuring Act of 1998'."
                        ),
                    ),
                ),
                (
                    "The Board is not new: the 1994 International Broadcasting Act "
                    "consolidated broadcasting into USIA under it, and FARRA carved "
                    "it out of the abolition and continued it, so USIA's "
                    "broadcasting functions stayed there, not at State. The "
                    "International Broadcasting Bureau (FR 256, sealed name "
                    "International Broadcasting Board) is its component and stays "
                    "with it."
                ),
                Rejected(
                    "Leave broadcasting out and keep USIA to State as a single-successor event.",
                    (
                        "Secs. 1311 and 1312(b) keep broadcasting from both the "
                        "abolition and the transfer; a State-only event would route "
                        "USIA's broadcasting documents to a department that never "
                        "held that function."
                    ),
                ),
            ),
        ),
        owner_note=(
            "FR 41 is not a new body: it published before the event (measured "
            "periods) and kept functions it already held (sec. 1312(b)). The split "
            "has a cost: a consumer that needs exactly one code gets none for USIA's "
            "documents, where either result on its own would code them (effect column)."
        ),
    ),
    SuccessionEvent(
        (543,),
        "1996-01-01",
        "ICCTA sec. 2's effective date for the Act",
        (
            SuccessorRow(
                481,
                (
                    "the surviving economic regulation: rail rate and service "
                    "regulation and the residual carrier jurisdiction the Act "
                    "recodifies into subtitle IV, chartered as the Board (ICCTA title II)"
                ),
                (ICCTA,),
                (
                    "The ICC Termination Act abolished the Interstate Commerce "
                    "Commission and chartered the Surface Transportation Board for "
                    "the economic functions that survived it, both effective "
                    "1996-01-01 by the Act's own effective-date section."
                ),
                ICC_SPLIT_REJECTED,
            ),
            SuccessorRow(
                492,
                (
                    "the functions the Act vests in the Secretary: carrying out the "
                    "recodified motor-carrier part (49 U.S.C. 13301(a): 'Except as "
                    "otherwise specified, the Secretary shall carry out this part') "
                    "and the carrier-related consumer-protection enforcement the "
                    "conforming amendments redirect (ICCTA secs. 314-316)"
                ),
                (ICCTA,),
                (
                    "The Act did not send everything to the Board: the Secretary of "
                    "Transportation carries out the recodified motor-carrier part, "
                    "the consumer-protection Acts the ICC enforced for carriers were "
                    "redirected to the Secretary, and sec. 203(b) moves the personnel "
                    "and assets for Secretary functions separately from the Board's."
                ),
                ICC_SPLIT_REJECTED,
            ),
        ),
    ),
    SuccessionEvent(
        (559,),
        "2001-06-29",
        (
            "the Reorganization Order's signature date -- the order states no "
            "effective date, and 66 FR 39450 records the Secretary's 2001-06-14 "
            "announcement of the new name"
        ),
        (
            SuccessorRow(
                45,
                None,
                (
                    PublicRecord(
                        "frNotice",
                        (
                            "66 FR 35437 (2001-07-05), FR Doc 01-16800, Centers for "
                            "Medicare & Medicaid Services; Statement of Organization, "
                            "Functions and Delegations of Authority; Reorganization Order"
                        ),
                        (
                            "https://www.federalregister.gov/documents/2001/07/05/01-16800/"
                            "centers-for-medicare-and-medicaid-services-statement-of-"
                            "organization-functions-and-delegations-of"
                        ),
                        (
                            "The Secretary's Reorganization Order retitling Part F "
                            "(Health Care Financing Administration) as the Centers for "
                            "Medicare & Medicaid Services and vesting every HCFA "
                            "delegation in the CMS Administrator; 'Dated: June 29, "
                            "2001', with no effective-date clause."
                        ),
                    ),
                    PublicRecord(
                        "frNotice",
                        (
                            "66 FR 39450 (2001-07-31), FR Doc 01-18959, Medicare and "
                            "Medicaid Programs; Change of Agency Name: Technical Amendments"
                        ),
                        (
                            "https://www.federalregister.gov/documents/2001/07/31/01-18959/"
                            "medicare-and-medicaid-programs-change-of-agency-name-technical-"
                            "amendments"
                        ),
                        (
                            "Records that the Secretary 'announced on June 14, 2001, "
                            "the new name'; its own effective date, 2001-07-31, is the "
                            "CFR conforming date, carried beside, not as, the rename date."
                        ),
                    ),
                ),
                (
                    "The HHS Secretary's Reorganization Order, dated 2001-06-29, "
                    "retitled the Health Care Financing Administration the Centers for "
                    "Medicare & Medicaid Services; the Federal Register roster keeps "
                    "both records under the HHS department."
                ),
                Rejected(
                    "Health Care Finance Administration sameEntityAs Centers for Medicare & Medicaid Services.",
                    (
                        "The rename has a dated order; identity would erase that date "
                        "and misdate the documents filed under each name, even though "
                        "the periods are not cleanly disjoint (measured periods)."
                    ),
                ),
            ),
        ),
        owner_note=(
            "The periods are not mutually exclusive: documents printed under the "
            "old heading kept arriving after the order, and the Register also maps "
            "one later, unrelated heading to HCFA's record (the measured periods "
            "list each printed heading)."
        ),
    ),
    SuccessionEvent(
        (564,),
        "2006-12-20",
        (
            "PAEA's approval date; sec. 604 states no separate effective date, and "
            "title VI's one effective-date clause, sec. 603(d)(1), governs "
            "appropriations, not the redesignation"
        ),
        (
            SuccessorRow(
                409,
                None,
                (
                    PublicRecord(
                        "statute",
                        "Postal Accountability and Enhancement Act, Pub. L. 109-435, 120 Stat. 3198, sec. 604",
                        "https://www.congress.gov/109/plaws/publ435/PLAW-109publ435.htm",
                        (
                            "Sec. 604 redesignates the Postal Rate Commission as the "
                            "Postal Regulatory Commission throughout titles 39, 5, and "
                            "44, and sec. 604(f) deems any other reference to the one a "
                            "reference to the other; the Act was approved 2006-12-20."
                        ),
                    ),
                    PublicRecord(
                        "publisherRoster",
                        "Federal Register agency roster description of 409, Postal Regulatory Commission",
                        "https://www.federalregister.gov/agencies/postal-regulatory-commission",
                        (
                            "The publisher's own roster description: 'The Postal "
                            "Regulatory Commission is the successor agency to the "
                            "Postal Rate Commission'."
                        ),
                    ),
                    PublicRecord(
                        "publisherRoster",
                        "Federal Register agency roster description of 564, Postal Rate Commission",
                        "https://www.federalregister.gov/agencies/postal-rate-commission",
                        (
                            "The record is named Postal Rate Commission, but its "
                            "description is the Postal Regulatory Commission's "
                            "post-PAEA text: 'The Postal Regulatory Commission (PRC) "
                            "is an independent agency that has exercised regulatory "
                            "oversight over the Postal Service since its creation by "
                            "the Postal Reorganization Act of 1970 ... the Postal "
                            "Accountability and Enhancement Act (PAEA) enacted on "
                            "December 20, 2006, significantly strengthened the "
                            "Commission's authority'."
                        ),
                    ),
                    PublicRecord(
                        "frDocument",
                        "68 FR 14435 (2003-03-25), FR Doc 03-7022, Customized Market Mail",
                        "https://www.federalregister.gov/documents/2003/03/25/03-7022/customized-market-mail",
                        (
                            "The Register's only document under FR 564 (the publisher's "
                            "API); its agency heading reads 'POSTAL RATE COMMISSION 39 "
                            "U.S.C. 3623', a statute citation fused into the heading."
                        ),
                    ),
                ),
                (
                    "PAEA sec. 604 redesignated the Postal Rate Commission as the "
                    "Postal Regulatory Commission, and the roster's description of FR "
                    "409 names it the successor agency. The records are not "
                    "period-disjoint, though: the Register files documents headed "
                    "POSTAL RATE COMMISSION under FR 409, FR 564's one document "
                    "carries a heading with a citation fused in, and FR 564's own "
                    "description is the Postal Regulatory Commission's post-PAEA "
                    "text, so FR 564 may be a duplicate record of the same commission "
                    "rather than a predecessor."
                ),
                Rejected(
                    "Postal Rate Commission sameEntityAs Postal Regulatory Commission, folded into identity.",
                    (
                        "Proposed only if the owner reads FR 564 as a duplicate "
                        "record; the event's question offers it as an answer rather "
                        "than rejecting it."
                    ),
                ),
            ),
        ),
        owner_note=(
            "The records are not period-disjoint: the Register files documents "
            "headed POSTAL RATE COMMISSION under 409 (measured periods); 564's only "
            "document, FR Doc 03-7022, is headed 'POSTAL RATE COMMISSION 39 U.S.C. "
            "3623'; and 564's own roster description is the Postal Regulatory "
            "Commission's post-PAEA text."
        ),
        owner_question=OwnerQuestion(
            "Is FR 564 Postal Rate Commission the predecessor of FR 409, or a duplicate record of it?",
            (
                "Succession: 564 became 409 on 2006-12-20, as this event proposes.",
                "Duplicate record: FR 564 sameEntityAs FR 409, both records of one commission.",
                "Neither: relate nothing, and the 1 mention under FR 564 stays unreached.",
            ),
        ),
    ),
    SuccessionEvent(
        (96,),
        "2003-03-01",
        (
            "the Reorganization Plan Modification's effective date, as 68 FR 51868 "
            "recites it; the Homeland Security Act itself names no such date, since "
            "its sec. 4 takes effect 60 days after enactment"
        ),
        (
            SuccessorRow(
                501,
                "the Customs Service's inspection and ports-of-entry side (the plan's subsection (b) bureau)",
                (HSA, HDOC_108_32, REORG_MODIFICATION),
                (
                    "HSA sec. 403(1) transferred the United States Customs Service to "
                    "DHS; 68 FR 51868 records that the Service 'is now known as the "
                    "bureau of Customs and Border Protection', whose inspection and "
                    "border side is the plan's subsection (b). HSA sec. 412 keeps the "
                    "Secretary of the Treasury's authority over customs revenue functions."
                ),
                Rejected(
                    "Customs Service sameEntityAs U.S. Customs and Border Protection, folded into identity.",
                    (
                        "The Customs Service published under its own FR id before "
                        "2003-03-01 and CBP after, and its investigation arms went to "
                        "ICE; identity would collapse the two records and the split "
                        "the record separates."
                    ),
                ),
            ),
            SuccessorRow(
                503,
                "the investigation arms of the former Customs Service (H. Doc. 108-32 subsection (a))",
                (HDOC_108_32, REORG_MODIFICATION),
                (
                    "The plan's subsection (a) builds Immigration and Customs "
                    "Enforcement as the interior-enforcement bureau, and 68 FR 51868 "
                    "records that ICE 'brings together the investigation arms of the "
                    "former Customs Service', with the same 2003-03-01 effect. HSA "
                    "sec. 412 keeps customs revenue authority with Treasury."
                ),
                Rejected(
                    "Fold the Customs investigators into the Customs-to-CBP row alone.",
                    (
                        "68 FR 51868 names the former Customs Service's investigation "
                        "arms as ICE's, not CBP's; one result would misroute the "
                        "enforcement functions the record assigns to the other bureau."
                    ),
                ),
            ),
        ),
    ),
)


@dataclass(frozen=True, slots=True)
class LaterSuccession:
    """A defunct register-only agency held for a later succession batch, not batch 2."""

    fr_agency_id: int
    successor_fr_ids: tuple[int, ...]
    evidence: Literal["publisherRoster", "statute", "recordNotYetRead"]
    note: str


# Defunct agencies with successors are a succession question, not a
# register-only row. ``evidence`` says what this pass read: the Federal
# Register roster's own description, a statute already in hand, or nothing
# yet (the later batch reads the record before proposing anything).
LATER_SUCCESSION_BATCH = (
    LaterSuccession(17, (136,), "publisherRoster", "Roster: abolished, responsibilities to DOE by act of 1977-08-04; its 1994-1996 documents conflict, so verify."),
    LaterSuccession(31, (476,), "statute", "FARRA secs. 1201, 1211-1212: abolished, all functions to the Secretary of State (earlier of 1999-04-01 or the plan date)."),
    LaterSuccession(106, (), "publisherRoster", "Roster: renamed Defense Security Service in 1999 (not in the held FR roster)."),
    LaterSuccession(108, (344,), "publisherRoster", "Roster: functions to NIMA by Pub. L. 104-201 (1996-09-23); NIMA redesignated NGA in 2003."),
    LaterSuccession(110, (), "publisherRoster", "Roster: absorbed into DTRA by DoD Directive 5105.62 (1998-09-30; DTRA not in the held FR roster)."),
    LaterSuccession(140, (), "recordNotYetRead", "Renamed the Office of Science in 1998 (not in the held FR roster)."),
    LaterSuccession(148, (578,), "recordNotYetRead", "Succeeded by CIGIE under the Inspector General Reform Act of 2008."),
    LaterSuccession(198, (200,), "publisherRoster", "Roster: renamed the Food and Nutrition Service again, 63 FR 9721 (1998-02-26)."),
    LaterSuccession(258, (476, 6, 397), "statute", "FARRA secs. 1401, 1411-1412 and the roster: abolished, functions to State, USAID and OPIC -- a split."),
    LaterSuccession(290, (136,), "publisherRoster", "Roster: terminated 1996 (110 Stat. 32); certain functions to the Secretary of Energy (110 Stat. 1321-167) -- a split."),
    LaterSuccession(306, (212,), "recordNotYetRead", "Became the Geological Survey's biological resources division in 1996."),
    LaterSuccession(389, (181,), "recordNotYetRead", "Succeeded by the Federal Motor Carrier Safety Administration (2000-01-01)."),
    LaterSuccession(407, (284,), "publisherRoster", "Roster (FR 440's description): BBA 1997 merged its duties with ProPAC's into MedPAC."),
    LaterSuccession(428, (578,), "recordNotYetRead", "Succeeded by CIGIE under the Inspector General Reform Act of 2008."),
    LaterSuccession(440, (284,), "publisherRoster", "Roster: BBA 1997 terminated ProPAC and merged its duties with PPRC's into MedPAC."),
    LaterSuccession(452, (164,), "recordNotYetRead", "Remaining functions to the FDIC at its 1995 termination; the roster says only 'terminated'."),
    LaterSuccession(457, (458,), "publisherRoster", "Roster: renamed Rural Housing Service as of 1996-01-30."),
    LaterSuccession(488, (497,), "publisherRoster", "Roster: abolished 1998-07-29, authority and duties to the Secretary of the Treasury."),
    LaterSuccession(496, (261,), "recordNotYetRead", "Abolished 1996; residual tourism functions to the International Trade Administration."),
    LaterSuccession(557, (91, 468), "publisherRoster", "Roster: functions to CNCS (107 Stat. 888), SCORE and ACE to SBA -- a split."),
    LaterSuccession(568, (575, 576), "publisherRoster", "Roster: divided into BOEM and BSEE on 2011-10-01 (ONRR, FR 586, split off 2010-10-01) -- a split."),
)

# The previous round numbered rows by position; the new ids are content-derived.
PREVIOUS_ROUND_IDS = (
    ("batch1-001", "same:fr118:ecfr:economic-analysis-bureau"),
    ("batch1-002", "same:fr136:ecfr:energy-department"),
    ("batch1-003", "same:fr151:ecfr:export-import-bank"),
    ("batch1-004", "same:fr186:ecfr:federal-register-office"),
    ("batch1-005", "same:fr244:fh:100006936"),
    ("batch1-006", "same:fr245:fh:100004455"),
    ("batch1-007", "same:fr255:ecfr:international-boundary-and-water-commission-united-states-and-mexico"),
    ("batch1-008", "same:fr271:ecfr:labor-department"),
    ("batch1-009", "same:fr277:ecfr:library-of-congress"),
    ("batch1-010", "same:fr296:fh:300000070"),
    ("batch1-011", "same:fr4:ecfr:african-development-foundation"),
    ("batch1-012", "same:fr409:ecfr:postal-regulatory-commission"),
    ("batch1-013", "same:fr503:fh:100012075"),
    ("batch1-014", "same:fr587:fh:100525875"),
    ("batch1-015", "same:fr603:ecfr:investment-security-office"),
    ("batch1-016", "same:fr88:ecfr:copyright-royalty-board"),
    ("batch1-017", "succ:fr150:fr241"),
    ("batch1-018", "succ:fr232:fr499"),
    ("batch1-019", "succ:fr232:fr501"),
    ("batch1-020", "succ:fr232:fr503"),
    ("batch1-021", "succ:fr259:fr603"),
    ("batch1-022", "succ:fr404:fr131"),
    ("batch1-023", "succ:fr510:fr476"),
    ("batch1-024", "succ:fr543:fr481"),
    ("batch1-025", "succ:fr543:fr492"),
    ("batch1-026", "succ:fr559:fr45"),
    ("batch1-027", "succ:fr564:fr409"),
    ("batch1-028", "succ:fr96:fr501"),
    ("batch1-029", "succ:fr96:fr503"),
)


def content_digest(entry: Mapping[str, Any], members: Sequence[Mapping[str, Any]] = ()) -> str:
    """What a decision binds to: the entry as the owner reads it and, for an event, its rows.

    Roster-derived only -- questions, options, both sides' sealed names and ids, the
    relation or basis, dates and records -- so a replay or effect refresh stales nothing,
    and a change to another row leaves this one's decision current.
    """

    def owner_view(item: Mapping[str, Any]) -> dict[str, Any]:
        return {key: value for key, value in item.items() if key not in _OUTSIDE_CONTENT}

    return _digest({"entry": owner_view(entry), "members": [owner_view(member) for member in members]})


def _canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _digest(value: Any) -> str:
    return "sha256:" + hashlib.sha256(_canonical_json_bytes(value)).hexdigest()


def _file_digest(path: Path) -> str:
    with path.open("rb") as handle:  # streamed: the replay parquet is ~157 MB
        return "sha256:" + hashlib.file_digest(handle, "sha256").hexdigest()


class _Roster(NamedTuple):
    """One pinned roster release indexed for record lookups."""

    release: RegistryRelease
    resources: Mapping[str, RegistryResource]
    parents: Mapping[str, str]

    def iri(self, key: object) -> str:
        return IRI_PREFIXES[self.release.key] + str(key)

    def token(self, iri: str) -> str:
        return ID_TOKENS[self.release.key] + iri.removeprefix(IRI_PREFIXES[self.release.key])

    def name(self, iri: str) -> str:
        return entity_alignments.publisher_name(self.release.key, self.resources[iri])[1]

    def record(self, iri: str) -> dict[str, Any]:
        """The record REF-038 would seal: the sealed name field and value, plus the structured parent."""

        resource = self.resources[iri]
        field, name = entity_alignments.publisher_name(self.release.key, resource)
        payload = resource.native_payload
        record: dict[str, Any] = {
            "roster": ROSTER_NAMES[self.release.key],
            "release_key": self.release.key,
            "resource_iri": iri,
            "name_field": field,
            "publisher_name": name,
        }
        if self.release.key == FR:
            record.update(id=int(payload["id"]), slug=payload["slug"], short_name=payload.get("short_name"))
        elif self.release.key == ECFR:
            record.update(slug=payload["slug"], short_name=payload.get("short_name"))
        else:
            record.update(id=str(payload["fhorgid"]))
        parent = self.parents.get(iri)
        record["parent"] = None if parent is None else {"resource_iri": parent, "publisher_name": self.name(parent)}
        return record


def _rosters(releases: Sequence[RegistryRelease]) -> dict[str, _Roster]:
    by_key = {release.key: release for release in releases}
    return {
        key: _Roster(
            by_key[key],
            {resource.iri: resource for resource in by_key[key].resources},
            agency_projection.parent_by_subject(by_key[key]),
        )
        for key in (FR, FH, ECFR)
    }


def _reached_fr_ids(projection: agency_projection.AgencyProjection) -> set[int]:
    prefix = IRI_PREFIXES[FR]
    return {int(row.org.removeprefix(prefix)) for row in projection.rows if row.org.startswith(prefix)}


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def _identity_candidates(
    rosters: Mapping[str, _Roster],
    codes_by_org: Mapping[str, Sequence[str]],
    reached: set[int],
) -> list[dict[str, Any]]:
    fr = rosters[FR]
    fr_by_slug: dict[str, list[str]] = defaultdict(list)
    for iri, resource in fr.resources.items():
        fr_by_slug[resource.native_payload["slug"]].append(iri)
    rows: list[dict[str, Any]] = []
    for bridge in IDENTITY_BRIDGES:
        target = rosters[bridge.target_release_key]
        target_iri = target.iri(bridge.target_key)
        source_iri = fr.iri(bridge.fr_agency_id)
        codes = sorted(codes_by_org.get(target_iri, ()))
        _require(bool(codes), f"no regulations.gov code selects {target_iri}")
        if bridge.target_release_key == ECFR:
            _require(
                fr_by_slug.get(bridge.target_key) == [source_iri],
                f"slug {bridge.target_key!r} no longer finds FR {bridge.fr_agency_id}",
            )
        if bridge.basis is None:
            # A held row names why no basis fits and the closest one that would.
            _require(bool(bridge.hold) and bridge.owner_question is not None, f"FR {bridge.fr_agency_id} holds without saying why")
            _require(bridge.alternative_basis in entity_alignments.AGENCY_DECISION_BASES, "alternative basis is outside REF-038")
        else:
            _require(bridge.basis in entity_alignments.AGENCY_DECISION_BASES, f"basis {bridge.basis!r} is outside REF-038")
        source, target_record = fr.record(source_iri), target.record(target_iri)
        for record in (source, target_record):
            _require(
                record["publisher_name"] in bridge.reasoning,
                f"reasoning for FR {bridge.fr_agency_id} does not quote {record['publisher_name']!r}",
            )
        row: dict[str, Any] = {
            "candidate_id": f"same:{fr.token(source_iri)}:{target.token(target_iri)}",
            "relation": "sameEntityAs",
            "relation_iri": agency_projection.ATLAS_SAME_ENTITY_AS,
            "group": "A" if bridge.owner_question is None else "B",
            "proposed_basis": bridge.basis,
            "source": source,
            "target": target_record,
            "regulations_gov_codes": codes,
            "fr_id_reached_today": bridge.fr_agency_id in reached,
            "codes_selecting_fr_id_after_bridge": sorted({*codes, *codes_by_org.get(source_iri, ())}),
            "finding": SLUG_FINDING_NOTE if bridge.target_release_key == ECFR else PAIRING_FINDING_NOTE,
            "reasoning": bridge.reasoning,
            "closest_rejected_alternative": bridge.rejected.to_dict(),
            "status": CANDIDATE_STATUS,
        }
        if bridge.hold is not None:
            row["proposed_hold"] = bridge.hold
            row["alternative_basis"] = bridge.alternative_basis
        if bridge.effect_note is not None:
            row["effect_note"] = bridge.effect_note
        if bridge.owner_question is not None:
            row["owner_question"] = bridge.owner_question.to_dict()
        row["content_digest"] = content_digest(row)
        rows.append(row)
    return sorted(rows, key=lambda row: row["candidate_id"])


def _non_emissions(rosters: Mapping[str, _Roster], codes_by_org: Mapping[str, Sequence[str]]) -> list[dict[str, Any]]:
    fr = rosters[FR]
    rows = []
    for item in NON_EMISSIONS:
        target = rosters[item.target_release_key]
        source_iri, target_iri = fr.iri(item.fr_agency_id), target.iri(item.target_key)
        rows.append(
            {
                "candidate_id": f"same:{fr.token(source_iri)}:{target.token(target_iri)}",
                "proposed_decision": "nonEmission",
                "withdrawn_relation": "sameEntityAs",
                "source": fr.record(source_iri),
                "target": target.record(target_iri),
                "regulations_gov_codes": sorted(codes_by_org.get(target_iri, ())),
                "reason": item.reason,
                "closest_alternative": dict(item.closest_alternative),
                "leaves_fr_mentions_unreached": True,
                "status": CANDIDATE_STATUS,
            }
        )
        rows[-1]["content_digest"] = content_digest(rows[-1])
    return rows


def event_id(fr: _Roster, originals: Sequence[int]) -> str:
    """``event:`` over the sorted original FR ids: ``event:fr232``, a merger ``event:fr407+fr440``."""

    return "event:" + "+".join(fr.token(fr.iri(fr_id)) for fr_id in sorted(set(originals)))


def _succession_candidates(
    rosters: Mapping[str, _Roster],
    events: Sequence[SuccessionEvent] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    events = SUCCESSION_EVENTS if events is None else events
    fr = rosters[FR]
    rows: list[dict[str, Any]] = []
    out: list[dict[str, Any]] = []
    for event in sorted(events, key=lambda item: sorted(item.originals)):
        originals = sorted(set(event.originals))
        key = event_id(fr, originals)
        _require(len(originals) == len(event.originals), f"{key} repeats an original")
        pairs = []
        for successor in event.rows:
            original = successor.original_fr_id
            if original is None and len(originals) == 1:
                original = originals[0]
            _require(original in originals, f"{key} row to FR {successor.successor_fr_id} names no original of the event")
            pairs.append((original, successor))
        _require(len({(o, r.successor_fr_id) for o, r in pairs}) == len(pairs), f"{key} repeats a row")
        _require({o for o, _ in pairs} == set(originals), f"{key} has an original with no row")
        _require(not set(originals) & {r.successor_fr_id for _, r in pairs}, f"{key} lists an original among its results")
        if len(pairs) > 1:
            _require(all(r.functions_taken for _, r in pairs), f"{key} splits or merges without naming functions")
        records: dict[str, dict[str, str]] = {}
        row_ids = []
        for original, successor in sorted(pairs, key=lambda pair: (pair[0], pair[1].successor_fr_id)):
            source_iri, target_iri = fr.iri(original), fr.iri(successor.successor_fr_id)
            row_id = f"succ:{fr.token(source_iri)}:{fr.token(target_iri)}"
            row_ids.append(row_id)
            for record in successor.records:
                records.setdefault(record.citation, record.to_dict())
            rows.append(
                {
                    "candidate_id": row_id,
                    "relation": "resultingOrganization",
                    "event_id": key,
                    "source": fr.record(source_iri),
                    "target": fr.record(target_iri),
                    "functions_taken": successor.functions_taken,
                    "public_records": [record.to_dict() for record in successor.records],
                    "reasoning": successor.reasoning,
                    "closest_rejected_alternative": successor.rejected.to_dict(),
                    "status": CANDIDATE_STATUS,
                }
            )
            rows[-1]["content_digest"] = content_digest(rows[-1])
        entry: dict[str, Any] = {
            "event_id": key,
            "event_type": "ChangeEvent",
            "group": "C" if len(pairs) == 1 else "D",
            "originals": [fr.record(fr.iri(original)) for original in originals],
            "effective_date": event.effective_date,
            "date_basis": event.date_basis,
            "effective_date_alternatives": [
                {"date": date, "date_basis": basis} for date, basis in event.date_alternatives
            ],
            "rows": row_ids,
            "public_records": list(records.values()),
            "owner_note": event.owner_note,
            "status": CANDIDATE_STATUS,
        }
        if event.owner_question is not None:
            entry["owner_question"] = event.owner_question.to_dict()
        entry["content_digest"] = content_digest(entry, [row for row in rows if row["event_id"] == key])
        out.append(entry)
    return rows, out


def _later_succession_batch(rosters: Mapping[str, _Roster]) -> list[dict[str, Any]]:
    fr = rosters[FR]
    return [
        {
            "fr_agency": fr.record(fr.iri(item.fr_agency_id)),
            "successors": [fr.record(fr.iri(fr_id)) for fr_id in item.successor_fr_ids],
            "evidence": item.evidence,
            "note": item.note,
        }
        for item in sorted(LATER_SUCCESSION_BATCH, key=lambda item: item.fr_agency_id)
    ]


def assemble_candidates(releases: Sequence[RegistryRelease]) -> dict[str, Any]:
    """Build every adjudicable row from the pinned rosters alone (no replay input)."""

    identity_release = entity_alignments.load_regulations_gov_agency_identity_mapping_release(releases)
    projection = agency_projection.build_agency_projection(releases, identity_release)
    rosters = _rosters(releases)
    reached = _reached_fr_ids(projection)
    codes_by_org: dict[str, list[str]] = defaultdict(list)
    for row in projection.rows:
        codes_by_org[row.org].append(row.source_value)
    non_fr_orgs = {row.org for row in projection.rows if not row.org.startswith(IRI_PREFIXES[FR])}
    _require(sum(len(codes_by_org[org]) for org in non_fr_orgs) == 18, "expected the 18 non-FR-mapped codes")

    candidates = _identity_candidates(rosters, codes_by_org, reached)
    non_emissions = _non_emissions(rosters, codes_by_org)
    unbridged = [org for org in non_fr_orgs for item in NO_FR_BRIDGE if item["value"] in codes_by_org[org]]
    accounted = [row["target"]["resource_iri"] for row in (*candidates, *non_emissions)] + unbridged
    _require(sorted(accounted) == sorted(non_fr_orgs), "bridges, non-emissions and no-bridge values must cover the 18 codes")
    succession_rows, events = _succession_candidates(rosters)
    candidates.extend(succession_rows)
    ids = [row["candidate_id"] for row in (*candidates, *non_emissions)]
    _require(len(ids) == len(set(ids)), "candidate ids collide")
    for old, new in PREVIOUS_ROUND_IDS:
        _require(new in ids, f"previous-round id {old} maps to unknown {new}")

    later = _later_succession_batch(rosters)
    claimed = {row["source"]["id"] for row in (*candidates, *non_emissions)}
    for item in later:
        fr_id = item["fr_agency"]["id"]
        _require(fr_id not in reached and fr_id not in claimed, f"later-succession FR {fr_id} is already reached or in batch 1")
    return {
        "candidates": candidates,
        "events": events,
        "non_emissions": non_emissions,
        "no_fr_bridge": [{**row, "content_digest": content_digest(row)} for row in NO_FR_BRIDGE],
        "later_succession_batch": later,
        "previous_round_ids": dict(PREVIOUS_ROUND_IDS),
        "_reached": reached,
        "_fr_names": {int(iri.removeprefix(IRI_PREFIXES[FR])): rosters[FR].name(iri) for iri in rosters[FR].resources},
        "_inputs": {
            "roster_releases": {release.key: release.source_release_digest for release in releases},
            "identity_mapping_release": {
                "key": identity_release.key,
                "digest": identity_release.source_release_digest,
            },
            "agency_projection_digest": projection.digest,
        },
    }


def candidates_digest(assembled: Mapping[str, Any]) -> str:
    return _digest({key: assembled[key] for key in CANDIDATES_DIGEST_COVERS})


class _EventWindow(NamedTuple):
    """What the period measurement needs of one event."""

    event_id: str
    effective_date: str
    originals: tuple[int, ...]
    results: tuple[int, ...]


def _measure_replay(
    replay_root: Path,
    *,
    reached: set[int],
    bridged: set[int],
    windows: Sequence[_EventWindow],
) -> dict[str, Any]:
    """Read the replay's Federal Register rows once, in DuckDB, and return every live count."""

    import duckdb

    fr_path = replay_root / FR_PARQUET
    con = duckdb.connect()
    con.execute(
        "create temp table mentions as "
        "with f as (select row_number() over () rid, document_number dn, publication_date pd, agencies_json "
        "from read_parquet(?)) "
        "select f.rid, f.dn, f.pd, t.a.id::INT aid, t.a.raw_name heading from f, "
        "unnest(from_json(f.agencies_json, '[{\"id\":\"VARCHAR\",\"raw_name\":\"VARCHAR\"}]')) t(a) "
        "where t.a.id is not null",
        [str(fr_path)],
    )
    rows, documents, multi = con.execute(
        "select count(*), count(distinct document_number), "
        "(select count(*) from (select document_number from read_parquet(?) group by 1 having count(*) > 1)) "
        "from read_parquet(?)",
        [str(fr_path), str(fr_path)],
    ).fetchone()
    per_id = {
        aid: {"mentions": n, "documents": d, "first_published": lo, "last_published": hi}
        for aid, n, d, lo, hi in con.execute(
            "select aid, count(*), count(distinct dn), min(pd), max(pd) from mentions group by aid order by aid"
        ).fetchall()
    }

    naming = {unit: con.execute(f"select count(distinct {unit}) from mentions").fetchone()[0] for unit in ("rid", "dn")}

    def unreached(ids: set[int], unit: str) -> int:
        # Units naming any agency, minus those naming a reached one: one semi-join, O(mentions).
        con.execute("create or replace temp table reached_ids as select unnest(?::INT[]) aid", [sorted(ids)])
        reached_units = con.execute(
            f"select count(distinct {unit}) from mentions where aid in (select aid from reached_ids)"
        ).fetchone()[0]
        return naming[unit] - reached_units

    # The printed agency headings behind each event's out-of-period mentions -- what the
    # Register filed where -- in one grouped query over every window.
    sides = {"originals_on_or_after": "originals", "results_before": "results"}
    periods: dict[str, Any] = {
        window.event_id: {side: {str(fr_id): [] for fr_id in getattr(window, field)} for side, field in sides.items()}
        for window in windows
    }
    window_rows = [
        (window.event_id, side, fr_id, window.effective_date)
        for window in windows
        for side, field in sides.items()
        for fr_id in getattr(window, field)
    ]
    con.execute("create temp table windows (event_id VARCHAR, side VARCHAR, aid INT, date VARCHAR)")
    con.executemany("insert into windows values (?, ?, ?, ?)", window_rows)
    for event, side, aid, heading, count, first, last in con.execute(
        "select w.event_id, w.side, w.aid, m.heading, count(*), min(m.pd), max(m.pd) "
        "from windows w join mentions m on m.aid = w.aid "
        "and ((w.side = 'originals_on_or_after' and m.pd >= w.date) or (w.side = 'results_before' and m.pd < w.date)) "
        "group by all order by 1, 2, 3, count(*) desc, m.heading nulls last"
    ).fetchall():
        periods[event][side][str(aid)].append(
            {"heading": heading, "mentions": count, "first_published": first, "last_published": last}
        )

    after = reached | bridged
    measured = {
        "federal_register": {
            "sha256": _file_digest(fr_path),
            "row_count": rows,
            "distinct_document_number_count": documents,
            "document_numbers_on_multiple_rows": multi,
            "agency_mention_count": sum(stats["mentions"] for stats in per_id.values()),
            "distinct_agency_id_count": len(per_id),
        },
        "unreached": {
            "rows_today": unreached(reached, "rid"),
            "rows_after_bridges": unreached(after, "rid"),
            "documents_today": unreached(reached, "dn"),
            "documents_after_bridges": unreached(after, "dn"),
        },
        "per_id": per_id,
        "event_periods": periods,
    }
    con.close()
    return measured


def _rule_effect_pins() -> dict[str, str]:
    return {
        "spicy_regs_commit": SPICY_REGS_COMMIT,
        "vendored_projection_sha256": SPICY_REGS_VENDORED_PROJECTION_SHA256,
        "spicy_regs_agencies_module_sha256": SPICY_REGS_AGENCIES_MODULE_SHA256,
        "measurement_script_sha256": MEASUREMENT_SCRIPT_SHA256,
    }


def load_rule_effects(
    path: Path,
    *,
    candidates_digest: str,
    replay_sha256: str,
    keys: set[str],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Read spicy-regs' own measurement of each candidate (read as a file; spicy-regs is never imported).

    Refuses effects measured against another candidate set or another replay, so a
    stale measurement cannot be rendered beside the rows it no longer describes.
    """

    data = json.loads(path.read_text())
    pins = _rule_effect_pins()
    for key, pinned in pins.items():
        _require(key in data, f"rule effects do not record {key}")
        _require(data[key] == pinned, f"rule effects record {key} {data[key]!r}; the design cites {pinned!r}")
    _require(
        data["refspec_candidates_digest"] == candidates_digest,
        "rule effects were measured against another candidate set; rerun the measurement",
    )
    _require(data["replay"]["federal_register_sha256"] == replay_sha256, "rule effects were measured on another replay")
    _require(keys <= set(data["effects"]), f"rule effects miss {sorted(keys - set(data['effects']))}")
    inputs = {
        "sha256": _file_digest(path),
        "rule": data["rule"],
        **pins,
        "proceedings_sha256": data["replay"]["proceedings_sha256"],
    }
    measured = {
        key: data[key]
        for key in ("baseline", "all_batch1_adopted", "effects", "split_variants", "withdrawn_reference")
    }
    return inputs, measured


def assemble_report(repo_root: Path, replay_root: Path, rule_effects: Path | None = None) -> dict[str, Any]:
    """The candidates (roster-derived, digest-covered) plus the live counts beside them."""

    assembled = assemble_candidates(census.load_five_agency_rosters(repo_root))
    reached = assembled.pop("_reached")
    fr_names = assembled.pop("_fr_names")
    inputs = assembled.pop("_inputs")
    bridged = {row["source"]["id"] for row in assembled["candidates"] if row["relation"] == "sameEntityAs"}
    rows = {row["candidate_id"]: row for row in assembled["candidates"]}
    windows = [
        _EventWindow(
            event["event_id"],
            event["effective_date"],
            tuple(original["id"] for original in event["originals"]),
            tuple(sorted({rows[row_id]["target"]["id"] for row_id in event["rows"]})),
        )
        for event in assembled["events"]
    ]
    originals = {original for window in windows for original in window.originals}
    later_ids = {item["fr_agency"]["id"] for item in assembled["later_succession_batch"]}
    live = _measure_replay(replay_root, reached=reached, bridged=bridged, windows=windows)
    per_id = live.pop("per_id")
    mentions = {aid: stats["mentions"] for aid, stats in per_id.items()}
    after = reached | bridged
    batch2 = set(mentions) - after - originals - later_ids
    total = sum(mentions.values())
    digest = candidates_digest(assembled)
    federal_register = live.pop("federal_register")
    effect_inputs, effects = (None, None)
    if rule_effects is not None:
        keys = {row["candidate_id"] for row in assembled["candidates"] if row["relation"] == "sameEntityAs"}
        keys |= {event["event_id"] for event in assembled["events"]}
        effect_inputs, effects = load_rule_effects(
            rule_effects, candidates_digest=digest, replay_sha256=federal_register["sha256"], keys=keys
        )

    def covered(ids: set[int]) -> int:
        return sum(count for aid, count in mentions.items() if aid in ids)

    report: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "note": (
            "Every row is a candidate pending owner adjudication and asserts "
            "nothing; only the owner's decision, recorded with the owner's reviewer "
            "IRI and date, turns a row into an assertion, following REF-038."
        ),
        "owner_reviewer_iri": OWNER_REVIEWER_IRI,
        "inputs": {**inputs, "replay": {"federal_register": federal_register}, "rule_effects": effect_inputs},
        "candidates_digest": digest,
        "candidates_digest_covers": list(CANDIDATES_DIGEST_COVERS),
        **assembled,
        "measured": {
            "reached_fr_ids_today": len(reached),
            "reached_fr_ids_not_in_fr_data": sorted(reached - set(mentions)),
            "fr_ids_newly_reached_by_bridges": len(bridged - reached),
            "fr_ids_after_bridges": len(after),
            "agency_mention_total": total,
            "agency_mention_coverage_today": covered(reached),
            "agency_mention_coverage_after_bridges": covered(after),
            "event_original_mentions": covered(originals),
            **live.pop("unreached"),
            "batch2_register_only_fr_ids": len(batch2),
            "batch2_register_only_mentions": covered(batch2),
            "later_succession_batch_mentions": covered(later_ids),
            "batch2_register_only": sorted(
                ({"id": aid, "name": fr_names[aid], "mentions": mentions[aid]} for aid in batch2),
                key=lambda row: (-row["mentions"], row["id"]),
            ),
            "event_periods": live.pop("event_periods"),
            "per_fr_id": {str(aid): stats for aid, stats in per_id.items()},
            "rule_effects": effects,
        },
    }
    report["digest"] = _digest(report)
    return report


# --- Rendering: every sentence below is generated from the report. ---


def _table(headers: Sequence[str], rows: Sequence[Sequence[object]]) -> list[str]:
    lines = ["| " + " | ".join(headers) + " |", "| " + " | ".join("---" for _ in headers) + " |"]
    lines.extend("| " + " | ".join(str(value).replace("|", "\\|") for value in row) + " |" for row in rows)
    return lines


def _n(value: int) -> str:
    return f"{value:,}"


def _stats(report: Mapping[str, Any], fr_id: int) -> Mapping[str, Any]:
    empty = {"mentions": 0, "documents": 0, "first_published": None, "last_published": None}
    return report["measured"]["per_fr_id"].get(str(fr_id), empty)


def _named(record: Mapping[str, Any]) -> str:
    label = ROSTER_LABELS[record["release_key"]]
    if "id" in record:
        return f"{label} {record['id']} {record['publisher_name']}"
    return f"{label} {record['publisher_name']} (`{record['slug']}`)"


def _originals(event: Mapping[str, Any]) -> str:
    return " and ".join(_named(original) for original in event["originals"])


def _mentions(count: int) -> str:
    return f"{_n(count)} mention" + ("" if count == 1 else "s")


def _parent(record: Mapping[str, Any]) -> str:
    parent = record["parent"]
    return "none" if parent is None else f"{parent['publisher_name']} (`{parent['resource_iri']}`)"


def _basis(row: Mapping[str, Any]) -> str:
    if row["proposed_basis"] is not None:
        return f"`{row['proposed_basis']}`"
    return f"hold ({row['proposed_hold']}); alternative `{row['alternative_basis']}`"


def _rejection(report: Mapping[str, Any], row: Mapping[str, Any]) -> str:
    rejected = row["closest_rejected_alternative"]
    text = f"{rejected['description']} Rejected: {rejected['why_rejected']}"
    if rejected["leaves_fr_mentions_unreached"]:
        text += f" The status quo leaves {_n(_stats(report, row['source']['id'])['mentions'])} FR mentions unreached."
    return text


def _date_text(event: Mapping[str, Any]) -> str:
    text = f"{event['effective_date']} ({event['date_basis']})"
    for alternative in event["effective_date_alternatives"]:
        text += f"; alternative {alternative['date']} ({alternative['date_basis']})"
    return text


def _span(first: str | None, last: str | None) -> str:
    return f"{first}" if first == last else f"{first} to {last}"


def _headings(groups: Sequence[Mapping[str, Any]], limit: int = 3) -> str:
    shown = [
        f"{'no heading' if group['heading'] is None else repr(group['heading'])} {_n(group['mentions'])} "
        f"({_span(group['first_published'], group['last_published'])})"
        for group in groups[:limit]
    ]
    if len(groups) > limit:
        more = len(groups) - limit
        shown.append(f"{more} more heading" + ("" if more == 1 else "s"))
    return ", printed as " + "; ".join(shown) if shown else ""


def _period_text(report: Mapping[str, Any], event: Mapping[str, Any], rows: Mapping[str, Any]) -> str:
    periods = report["measured"]["event_periods"][event["event_id"]]
    parts = []
    for original in event["originals"]:
        stats = _stats(report, original["id"])
        late = periods["originals_on_or_after"][str(original["id"])]
        parts.append(
            f"FR {original['id']}: {_mentions(stats['mentions'])} dated "
            f"{_span(stats['first_published'], stats['last_published'])}; "
            f"{_n(sum(group['mentions'] for group in late))} on or after {event['effective_date']}{_headings(late)}"
        )
    for result in sorted({rows[row_id]["target"]["id"] for row_id in event["rows"]}):
        early = periods["results_before"][str(result)]
        parts.append(
            f"FR {result}: {_n(sum(group['mentions'] for group in early))} of "
            f"{_n(_stats(report, result)['mentions'])} mentions before {event['effective_date']}{_headings(early)}"
        )
    return ". ".join(parts) + "."


def _count(value: int, noun: str) -> str:
    return f"{_n(value)} {noun}" + ("" if value == 1 else "s")


def _delta_text(delta: Mapping[str, Any]) -> str:
    def both(kind: str) -> str:
        return f"{_count(delta[f'fr_rows_{kind}'], 'row')} / {_count(delta[f'docketless_{kind}'], 'proceeding')}"

    parts = []
    if delta["fr_rows_gained"] or delta["docketless_gained"]:
        parts.append(f"newly codes {both('gained')}")
    if delta["fr_rows_lost"] or delta["docketless_lost"]:
        parts.append(f"uncodes {both('lost')}")
    if delta["fr_rows_changed"] or delta["docketless_changed"]:
        moves = sorted(delta["fr_rows_rerouted"].items(), key=lambda item: (-item[1], item[0]))
        shown = ", ".join(f"{move} {_n(count)}" for move, count in moves[:3])
        if len(moves) > 3:
            shown += f", {len(moves) - 3} more"
        parts.append(f"re-routes {both('changed')} (rows: {shown})")
    return "; ".join(parts) or "no change"


def _effect(report: Mapping[str, Any], key: str) -> str:
    """spicy-regs' rule, alone and on top of the rest of batch 1 (when that differs)."""

    effects = report["measured"]["rule_effects"]
    if effects is None:
        return "not measured"
    entry = effects["effects"][key]
    text = f"Alone: {_delta_text(entry['alone'])}"
    if entry["on_top"] != entry["alone"]:
        text += f". With the rest of batch 1: {_delta_text(entry['on_top'])}"
    return text + "."


def _split_cost(report: Mapping[str, Any], event: Mapping[str, Any], rows: Mapping[str, Any]) -> str:
    """For a consumer needing one code: what the split codes, against each result on its own."""

    effects = report["measured"]["rule_effects"]
    if effects is None or len(event["rows"]) < 2:
        return ""
    variants = effects["split_variants"][event["event_id"]]
    each = "; ".join(f"{_named(rows[row_id]['target'])}: {_delta_text(variants[row_id])}" for row_id in event["rows"])
    return f" Each result on its own, for a consumer that needs exactly one code: {each}."


def _provenance(report: Mapping[str, Any]) -> str:
    text = (
        f"Candidates digest `{report['candidates_digest']}` (covers "
        f"{', '.join(report['candidates_digest_covers'])}; no replay count enters it). "
        "Live counts come from the replay's `federal_register.parquet`, sha256 "
        f"`{report['inputs']['replay']['federal_register']['sha256']}`, passed as `--replay-root`; "
        "only its digest is recorded."
    )
    effects = report["inputs"]["rule_effects"]
    if effects is not None:
        text += (
            f" Effects under spicy-regs' rule (`{effects['rule']}` at {effects['spicy_regs_commit'][:7]}) come "
            f"from the measurement passed as `--rule-effects`, sha256 `{effects['sha256']}`, which the tool "
            "refuses if it was measured against another candidate set, replay, or spicy-regs commit, projection "
            "or module. \"Re-routes\" counts documents "
            "that move from one code to another, e.g. from a parent department's code to the successor's."
        )
    return text


REPRODUCE = (
    "Reproduce with `uv run python tools/assemble_agency_registry_batch_1.py --replay-root <replay-snapshot> "
    "--rule-effects <rule-effects.json> --check` (the measurement is spicy-regs' "
    f"`{MEASUREMENT_SCRIPT}` at commit {SPICY_REGS_COMMIT[:7]}, which holds it -- spicy-regs has since retired "
    "the script -- run in spicy-regs' own environment); CI runs "
    "`--check-committed`, which needs neither input."
)


def render_markdown(report: Mapping[str, Any]) -> str:
    """The reviewable candidate table, generated from the JSON."""

    measured = report["measured"]
    fed = report["inputs"]["replay"]["federal_register"]
    total = measured["agency_mention_total"]
    identity = [row for row in report["candidates"] if row["relation"] == "sameEntityAs"]
    rows = {row["candidate_id"]: row for row in report["candidates"]}
    lines = [
        "# Agency registry batch 1 — candidate table",
        "",
        (
            "Generated by `tools/assemble_agency_registry_batch_1.py` from the adjacent JSON. "
            "Nothing here is an assertion: every row is `candidate-pending-owner-adjudication`, "
            f"and only the owner ({report['owner_reviewer_iri']}) turns one into an assertion. "
            "The owner decides from [agency-registry-batch-1-adjudication.md](agency-registry-batch-1-adjudication.md)."
        ),
        "",
        "## Measured against the replay snapshot",
        "",
        *_table(
            ("Measure", "Value"),
            (
                ("Federal Register rows (distinct document numbers)", f"{_n(fed['row_count'])} ({_n(fed['distinct_document_number_count'])}; {_n(fed['document_numbers_on_multiple_rows'])} numbers on more than one row)"),
                ("Agency mentions (non-null ids) / distinct FR agency ids", f"{_n(total)} / {_n(fed['distinct_agency_id_count'])}"),
                ("FR ids reached through REF-038 today", f"{measured['reached_fr_ids_today']} ({len(measured['reached_fr_ids_not_in_fr_data'])} never appear in the snapshot: {', '.join(map(str, measured['reached_fr_ids_not_in_fr_data']))})"),
                ("Mention coverage today", f"{_n(measured['agency_mention_coverage_today'])} ({measured['agency_mention_coverage_today'] / total:.1%})"),
                ("FR ids newly reached by the identity candidates", measured["fr_ids_newly_reached_by_bridges"]),
                ("Mention coverage after the identity candidates", f"{_n(measured['agency_mention_coverage_after_bridges'])} ({measured['agency_mention_coverage_after_bridges'] / total:.1%})"),
                ("Rows naming no reached agency (today → after)", f"{_n(measured['rows_today'])} → {_n(measured['rows_after_bridges'])}"),
                ("Documents naming no reached agency (today → after)", f"{_n(measured['documents_today'])} → {_n(measured['documents_after_bridges'])}"),
                ("Mentions of the succession events' original agencies", _n(measured["event_original_mentions"])),
                ("Batch 2 register-only residue", f"{measured['batch2_register_only_fr_ids']} ids / {_n(measured['batch2_register_only_mentions'])} mentions"),
                ("Later succession batch (defunct with successors)", f"{len(report['later_succession_batch'])} ids / {_n(measured['later_succession_batch_mentions'])} mentions"),
            ),
        ),
        "",
        (
            "A row is one replay row; a document is one distinct document number; a "
            "mention is one `agencies_json` entry with a non-null id. \"Reached\" means "
            "some regulations.gov code's REF-038 projection row names the FR id. The "
            "effect columns apply spicy-regs' own resolution rule "
            "(`agency_code_for_fr_agencies`), measured outside this repository "
            "(design note, section 9); a re-route moves documents that resolve today, "
            "often from a parent department's code to the successor's -- a change a "
            "consumer sees."
        ),
        "",
        "## Identity candidates (`sameEntityAs`, FR agency to the eCFR/FH record)",
        "",
        *_table(
            ("Candidate", "Group", "FR agency (parent)", "Counterpart (parent)", "Proposed basis", "Codes: counterpart → FR id after bridge", "FR mentions / documents", "Effect under spicy-regs' rule", "Closest rejected alternative"),
            (
                (
                    f"`{row['candidate_id']}`",
                    row["group"],
                    f"{_named(row['source'])} (parent: {_parent(row['source'])})",
                    f"{_named(row['target'])} (parent: {_parent(row['target'])})",
                    _basis(row),
                    f"{', '.join(row['regulations_gov_codes'])} → {', '.join(row['codes_selecting_fr_id_after_bridge'])}",
                    f"{_n(_stats(report, row['source']['id'])['mentions'])} / {_n(_stats(report, row['source']['id'])['documents'])}",
                    _effect(report, row["candidate_id"]) + (f" {row['effect_note']}" if "effect_note" in row else ""),
                    _rejection(report, row),
                )
                for row in identity
            ),
        ),
        "",
        (
            "Names are the sealed publisher fields REF-038 records (FR `name`, eCFR "
            "`name`, Federal Hierarchy `fhorgname`), not display labels. The eCFR rows "
            "were *found* by slug equality, which REF-038 refuses as a basis; each "
            "row's reasoning in the JSON is the publisher evidence it admits. The "
            "codes column lists the codes selecting the counterpart today and every "
            "code that would select the FR id once the bridge lands; more than one "
            "is ambiguous in the reverse lookup."
        ),
        "",
        "## Proposed non-emissions and codes with no FR bridge",
        "",
        *_table(
            ("Item", "Proposal", "Closest alternative", "FR mentions left unreached"),
            [
                (
                    f"`{row['candidate_id']}`",
                    row["reason"],
                    f"`{row['closest_alternative']['relation']}`: {row['closest_alternative']['description']} {row['closest_alternative']['why_not_proposed']}",
                    _n(_stats(report, row["source"]["id"])["mentions"]),
                )
                for row in report["non_emissions"]
            ]
            + [(f"`{row['value_id']}`", f"No FR bridge (`{row['reason']}`): {row['reasoning']}", "—", "—") for row in report["no_fr_bridge"]],
        ),
        "",
        "## Succession events (one decision per event)",
        "",
        *_table(
            ("Event", "Group", "Originals", "Date (basis)", "Results", "Public records (every row's)", "Effect under spicy-regs' rule"),
            (
                (
                    f"`{event['event_id']}`",
                    event["group"],
                    _originals(event),
                    _date_text(event),
                    ", ".join(f"`{row_id}` {rows[row_id]['target']['publisher_name']}" for row_id in event["rows"]),
                    "; ".join(record["citation"] for record in event["public_records"]),
                    _effect(report, event["event_id"]) + _split_cost(report, event, rows),
                )
                for event in report["events"]
            ),
        ),
        "",
        *_table(
            ("Row", "Result", "Functions taken", "Records this row cites", "Closest rejected alternative"),
            (
                (
                    f"`{row['candidate_id']}`",
                    _named(row["target"]),
                    row["functions_taken"] or "— (single result)",
                    "; ".join(record["citation"] for record in row["public_records"]),
                    _rejection(report, row),
                )
                for row in report["candidates"]
                if row["relation"] == "resultingOrganization"
            ),
        ),
        "",
        "### Measured publication periods",
        "",
        *_table(
            ("Event", "Periods under the original and result ids"),
            ((f"`{event['event_id']}`", _period_text(report, event, rows)) for event in report["events"]),
        ),
        "",
        "## Later batches",
        "",
        (
            f"**Batch 2, register-only:** {measured['batch2_register_only_fr_ids']} FR ids "
            f"({_n(measured['batch2_register_only_mentions'])} mentions) remain after batch 1 "
            "and the later succession batch, led by "
            + ", ".join(
                f"{row['id']} {row['name']} ({_n(row['mentions'])} mentions)"
                for row in measured["batch2_register_only"][:5]
            )
            + "."
        ),
        "",
        "**Later succession batch:** defunct register-only agencies with successors, held out of batch 2.",
        "",
        *_table(
            ("FR agency", "Mentions", "Proposed successors", "Evidence read", "Note"),
            (
                (
                    f"{item['fr_agency']['id']} {item['fr_agency']['publisher_name']}",
                    _n(_stats(report, item["fr_agency"]["id"])["mentions"]),
                    ", ".join(f"{s['id']} {s['publisher_name']}" for s in item["successors"]) or "— (not in the held FR roster)",
                    f"`{item['evidence']}`",
                    item["note"],
                )
                for item in report["later_succession_batch"]
            ),
        ),
        "",
        "## Candidate ids from the previous round",
        "",
        (
            "The previous round numbered rows by position (`batch1-NNN`); ids are now "
            "derived from the rows' own records, so adding a row moves no other id. "
            "An event's id runs over its sorted original ids (`event:fr232`; a merger "
            "would be `event:fr407+fr440`)."
        ),
        "",
        *_table(("Previous id", "Id now"), ((old, f"`{new}`") for old, new in report["previous_round_ids"].items())),
        "",
        "Plus one new row: `succ:fr510:fr41` (USIA's broadcasting remnant, in `event:fr510`).",
        "",
        _provenance(report),
        "",
        REPRODUCE,
        "",
    ]
    return "\n".join(lines)


def _decision_cell(decisions: Decisions, key: str) -> str:
    decision = decisions.current.get(key)
    if decision is not None:
        note = f": {decision['note']}" if "note" in decision else ""
        return f"**{decision['answer']}** ({decision['decided_on']}, {decision['channel']}){note}"
    decision = decisions.stale.get(key)
    if decision is not None:
        return f"STALE: {decision['answer']} ({decision['decided_on']}), made on an earlier version of this item; re-confirm"
    return ""


def render_adjudication_sheet(report: Mapping[str, Any], decisions: Decisions = NO_DECISIONS) -> str:
    """The owner's one-sitting sheet, generated from the JSON and the decisions file; it adjudicates nothing."""

    rows = {row["candidate_id"]: row for row in report["candidates"]}
    identity = [row for row in report["candidates"] if row["relation"] == "sameEntityAs"]
    decidable = decision_answers(report)
    digests = decision_digests(report)
    undecided = len(set(decidable) - set(decisions.current))

    def cell(key: str) -> str:
        return _decision_cell(decisions, key)

    lines = [
        "<!-- markdownlint-disable MD013 -->",
        "",
        "# Agency registry batch 1 — owner adjudication sheet",
        "",
        (
            "Generated from [agency-registry-batch-1-candidates.json](agency-registry-batch-1-candidates.json) "
            "and [agency-registry-batch-1-decisions.json](agency-registry-batch-1-decisions.json) by "
            "`tools/assemble_agency_registry_batch_1.py`; `--check` fails if this sheet disagrees with "
            "either. **Do not edit this sheet.** You (reviewer "
            f"`{report['owner_reviewer_iri']}`) answer through the question tool or by editing the "
            "decisions file, never the sheet: each decision there is keyed by the candidate or event "
            "id, records the answer, the date, the channel, and the `content_digest` of that item as "
            "you decided it (the Decision keys table at the end), and the tool re-renders the **Owner decision / date** "
            "cells from it. A replay or effect refresh never touches a decision, and neither does a "
            "change to another item; when the item itself changes, its decision shows as STALE until "
            "you re-confirm it, never dropped. Every row is still "
            "`candidate-pending-owner-adjudication`: accepted rows become assertions carrying your "
            "reviewer IRI and the decision date; rejected and abstained rows become non-emissions."
        ),
        "",
        (
            f"Decisions recorded: {len(decisions.current)} current, {len(decisions.stale)} stale, "
            f"{undecided} of {len(decidable)} decidable items undecided."
        ),
        "",
        _provenance(report),
        "",
        (
            "The effect column is what spicy-regs' current rule would do with each "
            "decision -- a consumer-visible change, including documents re-routed from "
            "a parent department's code to a successor's. Whether spicy-regs applies "
            "forward successor lookups to historical documents is spicy-regs' own "
            "decision, not this sheet's."
        ),
        "",
        "## A. Obvious identity — answer `yes` / `no`",
        "",
        *_table(
            ("Candidate", "Question", "Proposed basis", "Parents", "FR mentions", "Effect under spicy-regs' rule", "Owner decision / date"),
            (
                (
                    f"`{row['candidate_id']}`",
                    f"Is {_named(row['source'])} the same organization as {_named(row['target'])}?"
                    + _ambiguity_note(report, row),
                    _basis(row),
                    f"{_parent(row['source'])} / {_parent(row['target'])}",
                    _n(_stats(report, row["source"]["id"])["mentions"]),
                    _effect(report, row["candidate_id"]) + (f" {row['effect_note']}" if "effect_note" in row else ""),
                    cell(row["candidate_id"]),
                )
                for row in identity
                if row["group"] == "A"
            ),
        ),
        "",
        "## B. Identity needing a judgment — answer with the option number",
        "",
        *_table(
            ("Candidate", "Question", "Options", "FR mentions", "Effect under spicy-regs' rule (if bridged)", "Owner decision / date"),
            (
                (
                    f"`{row['candidate_id']}`",
                    row["owner_question"]["question"] + _ambiguity_note(report, row) + f" Proposed basis: {_basis(row)}.",
                    " ".join(f"({index}) {option}" for index, option in enumerate(row["owner_question"]["options"], start=1)),
                    _n(_stats(report, row["source"]["id"])["mentions"]),
                    _effect(report, row["candidate_id"]),
                    cell(row["candidate_id"]),
                )
                for row in identity
                if row["group"] == "B"
            ),
        ),
        "",
        "## N. Proposed non-emissions and codes with no FR bridge — answer `confirm` / `overrule`",
        "",
        *_table(
            ("Item", "Proposal", "Owner decision / date"),
            [
                (
                    f"`{row['candidate_id']}`",
                    (
                        f"Withdraw {_named(row['source'])} sameEntityAs {_named(row['target'])}. {row['reason']} "
                        f"Closest alternative: `{row['closest_alternative']['relation']}`. The status quo leaves "
                        f"{_n(_stats(report, row['source']['id'])['mentions'])} FR mentions unreached."
                    ),
                    cell(row["candidate_id"]),
                )
                for row in report["non_emissions"]
            ]
            + [
                (f"`{row['value_id']}`", f"No FR bridge for {row['value']}: {row['reasoning']}", cell(row["value_id"]))
                for row in report["no_fr_bridge"]
            ],
        ),
        "",
        "## C. Renames — answer `accept` / `wrong-date` (with a note) / `not-a-succession`, or the option number where the row lists options",
        "",
        *_table(
            ("Event", "Question", "Records", "Measured periods", "Effect under spicy-regs' rule", "Owner decision / date"),
            (
                (
                    f"`{event['event_id']}` (row `{event['rows'][0]}`)",
                    (
                        f"Did {_originals(event)} become {_named(rows[event['rows'][0]]['target'])} on "
                        f"{_date_text(event)}?"
                        + (f" {event['owner_note']}" if event["owner_note"] else "")
                        + _options(event)
                    ),
                    "; ".join(record["citation"] for record in event["public_records"]),
                    _period_text(report, event, rows),
                    _effect(report, event["event_id"]),
                    cell(event["event_id"]),
                )
                for event in report["events"]
                if event["group"] == "C"
            ),
        ),
        "",
        "## D. Splits and mergers — one decision per event",
        "",
        (
            "Answer each event once: `accept-every-row` / `wrong-date` (with a note) / "
            "`wrong-functions` (with a note naming the row; the event goes back) / "
            "`not-a-succession`. No row can be accepted alone: the decisions file takes "
            "event ids, never row ids. The event's records are every record any of its "
            "rows cites; each row lists the records behind its own functions."
        ),
        "",
    ]
    for index, event in enumerate((event for event in report["events"] if event["group"] == "D"), start=1):
        lines.extend(
            [
                f"### D.{index} `{event['event_id']}`: {_originals(event)}, {event['effective_date']}",
                "",
                *_table(
                    ("Event", "Question", "Records", "Measured periods", "Effect under spicy-regs' rule", "Owner decision / date"),
                    (
                        (
                            f"`{event['event_id']}`",
                            f"Did {_originals(event)} end on {_date_text(event)}, leaving each result below with "
                            "the functions its row names?"
                            + (f" {event['owner_note']}" if event["owner_note"] else ""),
                            "; ".join(record["citation"] for record in event["public_records"]),
                            _period_text(report, event, rows),
                            _effect(report, event["event_id"]) + _split_cost(report, event, rows),
                            cell(event["event_id"]),
                        ),
                    ),
                ),
                "",
                *_table(
                    ("Row", "Result", "Functions the row names", "Records this row cites"),
                    (
                        (
                            f"`{row_id}`",
                            _named(rows[row_id]["target"]),
                            rows[row_id]["functions_taken"],
                            "; ".join(record["citation"] for record in rows[row_id]["public_records"]),
                        )
                        for row_id in event["rows"]
                    ),
                ),
                "",
            ]
        )
    lines.extend(
        [
            "## Decision keys",
            "",
            "Record a decision under its id with one of its answers and the content digest shown here.",
            "",
            *_table(
                ("Id", "Answers", "Content digest"),
                (
                    (f"`{key}`", " / ".join(f"`{answer}`" for answer in answers), f"`{digests[key]}`")
                    for key, answers in decidable.items()
                ),
            ),
            "",
            "## Stale decisions",
            "",
        ]
    )
    if decisions.stale:
        lines.extend(
            _table(
                ("Id", "Answer", "Decided on", "Decided on content digest", "Content digest now"),
                (
                    (f"`{key}`", decision["answer"], decision["decided_on"], f"`{decision['content_digest']}`", f"`{digests[key]}`")
                    for key, decision in decisions.stale.items()
                ),
            )
        )
    else:
        lines.append("None.")
    lines.append("")
    return "\n".join(lines)


def _options(event: Mapping[str, Any]) -> str:
    question = event.get("owner_question")
    if question is None:
        return ""
    return f" {question['question']} " + " ".join(
        f"({index}) {option}" for index, option in enumerate(question["options"], start=1)
    )


def _ambiguity_note(report: Mapping[str, Any], row: Mapping[str, Any]) -> str:
    codes = row["codes_selecting_fr_id_after_bridge"]
    if len(codes) < 2:
        return ""
    fr_id = row["source"]["id"]
    note = (
        f" After the bridge, FR {fr_id} is selected by {', '.join(codes)}: ambiguous in the "
        "reverse lookup, so no single code resolves it"
    )
    if not row["fr_id_reached_today"]:
        return note + ", as none does today."
    stats = _stats(report, fr_id)
    return (
        note + f" -- the cost: today FR {fr_id} resolves, and its {_mentions(stats['mentions'])} "
        f"({_n(stats['documents'])} documents) would lose that code."
    )


def _outputs(report: Mapping[str, Any], decisions: Decisions) -> dict[Path, bytes]:
    return {
        REPORT_JSON: _canonical_json_bytes(report) + b"\n",
        REPORT_MARKDOWN: render_markdown(report).encode("utf-8"),
        ADJUDICATION_MARKDOWN: render_adjudication_sheet(report, decisions).encode("utf-8"),
    }


def write_or_check(root: Path, report: Mapping[str, Any], decisions: Decisions, *, write: bool) -> list[str]:
    """Write the three generated plans/ artifacts, or return the ones missing or drifted.

    The decisions file is only ever read: a --write re-renders the owner's
    decisions into the sheet and cannot erase them.
    """

    problems = []
    for relative, payload in _outputs(report, decisions).items():
        path = root / relative
        if write:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(payload)
        elif not path.is_file():
            problems.append(f"missing: {relative}")
        elif path.read_bytes() != payload:
            problems.append(f"drifted: {relative}")
    return problems


def check_committed(root: Path) -> list[str]:
    """What CI can verify without the replay or the rule effects, which live outside the repo.

    The committed JSON's candidates must still follow from the pinned rosters, its
    rule effects must carry the pinned spicy-regs side the design note cites, the
    decisions file must match its schema and binding, and the table and sheet must
    be exactly what the committed JSON and decisions render to.
    """

    raw = (root / REPORT_JSON).read_bytes()
    report = json.loads(raw)
    problems = []
    if _canonical_json_bytes(report) + b"\n" != raw:
        problems.append(f"not canonical JSON: {REPORT_JSON}")
    if _digest({key: value for key, value in report.items() if key != "digest"}) != report["digest"]:
        problems.append(f"report digest does not match its content: {REPORT_JSON}")
    assembled = assemble_candidates(census.load_five_agency_rosters(root))
    if candidates_digest(assembled) != report["candidates_digest"] or any(
        report[key] != assembled[key] for key in CANDIDATES_DIGEST_COVERS
    ):
        problems.append(f"candidates no longer follow from the pinned rosters: {REPORT_JSON}")
    effects = report["inputs"]["rule_effects"] or {}
    if any(effects.get(key) != pinned for key, pinned in _rule_effect_pins().items()):
        problems.append(f"rule effects lack the pinned spicy-regs side: {REPORT_JSON}")
    design = (root / DESIGN_NOTE).read_text()
    cited = (SPICY_REGS_COMMIT[:7], SPICY_REGS_VENDORED_PROJECTION_SHA256[:15], MEASUREMENT_SCRIPT, MEASUREMENT_SCRIPT_SHA256[:15])
    if any(citation not in design for citation in cited):
        problems.append(f"the design note does not cite the pinned spicy-regs commit, projection and script: {DESIGN_NOTE}")
    decisions = load_decisions(root / DECISIONS_JSON, report)
    for relative, payload in _outputs(report, decisions).items():
        if relative != REPORT_JSON and (root / relative).read_bytes() != payload:
            problems.append(f"drifted from the committed JSON and decisions: {relative}")
    return problems


def _report_stale(decisions: Decisions) -> None:
    if decisions.stale:
        print(
            f"{len(decisions.stale)} stale decision(s), kept and shown in the sheet: {', '.join(decisions.stale)}",
            file=sys.stderr,
        )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--write", action="store_true", help="write the generated plans/ artifacts")
    mode.add_argument("--check", action="store_true", help="re-derive the plans/ artifacts and compare")
    mode.add_argument(
        "--check-committed",
        action="store_true",
        help="CI's check: the committed artifacts against the rosters, pins and decisions, no replay needed",
    )
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--replay-root", type=Path, help="rulemaking replay snapshot directory holding federal_register.parquet")
    parser.add_argument(
        "--rule-effects",
        type=Path,
        help=(
            "spicy-regs' own measurement of each candidate (required with --write/--check; "
            "without it, stdout carries the candidates that measurement reads)"
        ),
    )
    args = parser.parse_args(argv)
    root = args.repo_root.resolve()
    if args.check_committed:
        problems = check_committed(root)
        _report_stale(load_decisions(root / DECISIONS_JSON, json.loads((root / REPORT_JSON).read_text())))
        if problems:
            raise SystemExit("committed agency-registry artifacts inconsistent: " + "; ".join(problems))
        return 0
    if args.replay_root is None:
        parser.error("--replay-root is required unless --check-committed")
    if (args.write or args.check) and args.rule_effects is None:
        parser.error("--write and --check need --rule-effects")
    report = assemble_report(
        root, args.replay_root.resolve(), None if args.rule_effects is None else args.rule_effects.resolve()
    )
    if not (args.write or args.check):
        print(_canonical_json_bytes(report).decode("utf-8"))
        return 0
    decisions = load_decisions(root / DECISIONS_JSON, report)
    _report_stale(decisions)
    problems = write_or_check(root, report, decisions, write=args.write)
    if problems:
        raise SystemExit("candidate artifacts out of date: " + "; ".join(problems))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
