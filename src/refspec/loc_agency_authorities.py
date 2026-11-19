"""Library of Congress Corporate Name Authority (``LCNAF``) alignment for federal agencies.

Evaluates and provides deterministic offline verification for ``id.loc.gov``
Corporate Name Authorities (``http://id.loc.gov/authorities/names/<lccn>``)
against :mod:`refspec.registry.agency_crosswalk` and the pinned rolling
``externallinks.nt.zip`` archive in :mod:`refspec.registry.lc_external_links`.

Four measured findings from the 54-entity empirical alignment govern every
helper in this module:

1. **``externallinks.nt.zip`` already holds 2,018,402 LCNAF external links.**
   :mod:`refspec.registry.lc_external_links` filters that archive to
   ``http://id.loc.gov/authorities/subjects/`` (802,592 assertions), leaving
   2,018,402 ``http://id.loc.gov/authorities/names/`` assertions (1,418,942 to
   OCLC FAST and 425,540 to Wikidata) unread. Every single one (54/54, 100%)
   of the verified federal corporate authorities in this study is already
   present in that pinned August 2026 archive (23/54 with Wikidata links and
   53/54 with FAST links there, rising to 50/54 with Wikidata links in the
   November 2026 ``<lccn>.madsrdf.json`` graphs).
   :func:`load_lcnaf_external_links_from_archive` and
   :func:`parse_lcnaf_external_links_statements` stream those LCNAF statements
   in two passes without materializing the 1.85 GB uncompressed member.
2. **Left-anchored ``suggest2`` queries require a corporate heading ladder and
   jurisdiction/parent verification.** Bare Federal Register inverted names
   (``"Energy Department"``) hit 0/3 (0%); bare acronyms (``"EPA"``, ``"DOT"``,
   ``"FS"``, ``"EAB"``) hit 0/4 in top-3 due to global corporate collisions;
   bare natural names reach top-1 exact on only 13/54 (24.1%), returning 0 hits
   on 14/54 (25.9%) and foreign/state/sub-unit false friends at rank 1 on 27/54
   (50.0%, e.g. ``Liberia. Environmental Protection Agency`` ``no2025010917``).
   ``"United States. <Name>"`` reaches top-1 exact on 52/54 (96.3%) and misses
   direct-entry ``Centers for Medicare & Medicaid Services (U.S.)``
   (``no2001093385``, where Rung 1 hits ``Medicare Recovery Audit Contractor
   Program (U.S.)`` ``n2009184264``) and department-subordinate ``United States.
   Department of Justice. Executive Office for Immigration Review``
   (``n89643262``).
3. **``AGENCY_CROSSWALK.primary_slug`` collapses sub-agencies outside
   ``SPECIFICITY_MARGIN`` (0.05) and retains defunct codes.** Six codes in the
   47-agency sample (``CDC``, ``CISA``, ``USCBP``, ``BOEM``, plus defunct
   ``MMS`` and ``OTS``) resolve ``primary_slug`` to their parent cabinet
   department. :func:`lookup_verified_lcnaf_for_code` surfaces independent
   ``crosswalk_parent_collapsed`` and ``crosswalk_defunct_code`` flags.
4. **LCNAF uses successive entry with heterogeneous RDF succession predicates.**
   Reorganizations mint new LCCNs, and MADS/RDF encodes their links across three
   inconsistent modes: explicit ``hasEarlierEstablishedForm``/``hasLaterEstablishedForm``
   (e.g. ``AEC -> {NRC, ERDA}``, ``HCFA <-> CMS``, ``INS -> {USCIS, CBP, ICE}``),
   flattened untyped ``hasRelatedAuthority`` alongside child offices (``HEW <->
   HHS``, ``War -> Army -> DoD``, ``GPO``; note ``HEW``, ``HHS``, ``War``, and
   ``Army`` also carry unlinked blank-node pre-AACR2 ``Dept.`` earlier forms),
   or zero RDF links at all (``ICC`` vs ``STB``; ``CAB`` vs ``FAA``/``DOT``).
   LCNAF links therefore align with REF-072 change events as cross-checkable
   leads, never as ``atlas:sameEntityAs`` or an unverified succession oracle.
"""

from __future__ import annotations

import hashlib
import json
import re
import zipfile
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from types import MappingProxyType
from typing import Any, Literal

from refspec.registry import agency_crosswalk as cw
from refspec.registry import lc_external_links as lc

EVIDENCE_RELATIVE_DIR = "research/evidence/loc-statutes-and-authorities-2026-11-18"

LCNAF_ALIGNMENT_FILENAME = "lcnaf-federal-agencies-alignment.json"
LCNAF_ALIGNMENT_SHA256 = "sha256:0cf1dc0b3b7599d4c06363176a1c3f95e3e3b0f6fcd394d9b50511dcf69b5d6f"
LCNAF_ALIGNMENT_BYTE_LENGTH = 112_061

LCNAF_AUTHORITY_PREFIX = "http://id.loc.gov/authorities/names/"

MADS_CORPORATE_NAME = lc.MADS_NAMESPACE + "CorporateName"
MADS_HAS_VARIANT = lc.MADS_NAMESPACE + "hasVariant"
MADS_VARIANT_LABEL = lc.MADS_NAMESPACE + "variantLabel"
MADS_EARLIER_FORM = lc.MADS_NAMESPACE + "hasEarlierEstablishedForm"
MADS_LATER_FORM = lc.MADS_NAMESPACE + "hasLaterEstablishedForm"
MADS_RELATED_AUTHORITY = lc.MADS_NAMESPACE + "hasRelatedAuthority"
MADS_BROADER_AUTHORITY = lc.MADS_NAMESPACE + "hasBroaderAuthority"
MADS_IDENTIFIES_RWO = lc.MADS_NAMESPACE + "identifiesRWO"
BFLC_MARC_KEY = "http://id.loc.gov/ontologies/bflc/marcKey"

_NON_CORPORATE_MADS_TYPES = frozenset(
    {
        lc.MADS_NAMESPACE + "PersonalName",
        lc.MADS_NAMESPACE + "Topic",
        lc.MADS_NAMESPACE + "Geographic",
        lc.MADS_NAMESPACE + "ConferenceName",
        lc.MADS_NAMESPACE + "FamilyName",
        lc.MADS_NAMESPACE + "NameTitle",
        lc.MADS_NAMESPACE + "Title",
    }
)
_MARC_HEADING_TAG_RE = re.compile(r"^1\d\d")

SuccessionEncodingMode = Literal[
    "explicit_earlier_or_later_established_form",
    "flattened_into_untyped_related_authority",
    "unlinked_in_rdf_prose_only",
    "no_corporate_rename_link",
]

_NORM_RE = re.compile(r"[^a-z0-9]+")
_AMP_RE = re.compile(r"\s*&\s*")
_LCCN_RE = re.compile(r"^(?:n|no|nr|nb|sh|sj|gf|dg)\d{8,10}$")


class LcnafAlignmentError(ValueError):
    """Raised when a pinned LCNAF manifest or MADS/RDF payload is invalid or drifted."""


def _default_repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _freeze_json(value: Any) -> Any:
    if isinstance(value, dict):
        return MappingProxyType({k: _freeze_json(v) for k, v in value.items()})
    if isinstance(value, list):
        return tuple(_freeze_json(item) for item in value)
    return value


def _normalize_org_tokens(text: str) -> str:
    expanded = _AMP_RE.sub(" and ", text.lower())
    return _NORM_RE.sub(" ", expanded).strip()


@dataclass(frozen=True, slots=True)
class VerifiedLcnafAgencyRecord:
    """One SHA-256-verified federal corporate authority or historical predecessor in LCNAF."""

    key_id: str
    category: str
    crosswalk_code: str | None
    crosswalk_tier: str
    natural_name: str
    fr_or_alt_name: str
    crosswalk_parent_collapsed: bool
    crosswalk_defunct_code: bool
    resolution_rung: str
    lccn: str
    authority_iri: str
    authoritative_label: str
    marc_key: str
    madsrdf_sha256: str
    madsrdf_bytes: int
    us_prefixed_top1_exact: bool
    bare_name_top1_exact: bool
    in_pinned_lc_externallinks_zip: bool
    pinned_zip_wikidata_iris: tuple[str, ...]
    pinned_zip_fast_iris: tuple[str, ...]
    wikidata_iris: tuple[str, ...]
    fast_iris: tuple[str, ...]
    viaf_iris: tuple[str, ...]
    isni_iris: tuple[str, ...]
    earlier_lccns: tuple[str, ...]
    earlier_unlinked_labels: tuple[str, ...]
    later_lccns: tuple[str, ...]
    related_authority_count: int
    succession_encoding_mode: SuccessionEncodingMode


@dataclass(frozen=True, slots=True)
class ParsedLcnafMadsGraph:
    """Structured corporate authority facts extracted from one ``<lccn>.madsrdf.json`` graph."""

    lccn: str
    authority_iri: str
    authoritative_label: str
    marc_key: str
    variant_labels: tuple[str, ...]
    earlier_lccns: tuple[str, ...]
    earlier_unlinked_labels: tuple[str, ...]
    later_lccns: tuple[str, ...]
    related_lccns: tuple[str, ...]
    broader_lccns: tuple[str, ...]
    wikidata_iris: tuple[str, ...]
    fast_iris: tuple[str, ...]
    viaf_iris: tuple[str, ...]
    isni_iris: tuple[str, ...]


@cache
def load_lcnaf_alignment_manifest(repo_root: Path | None = None) -> Mapping[str, Any]:
    """Load and SHA-256-verify the immutable ``lcnaf-federal-agencies-alignment.json`` manifest."""

    root = _default_repo_root() if repo_root is None else Path(repo_root)
    path = root / EVIDENCE_RELATIVE_DIR / LCNAF_ALIGNMENT_FILENAME
    if path.is_symlink() or not path.is_file():
        raise LcnafAlignmentError(f"pinned LCNAF alignment manifest is missing or unsafe: {path}")
    payload = path.read_bytes()
    observed_sha = "sha256:" + hashlib.sha256(payload).hexdigest()
    if len(payload) != LCNAF_ALIGNMENT_BYTE_LENGTH or observed_sha != LCNAF_ALIGNMENT_SHA256:
        raise LcnafAlignmentError(
            f"pinned LCNAF alignment manifest drifted: "
            f"expected=({LCNAF_ALIGNMENT_BYTE_LENGTH}, {LCNAF_ALIGNMENT_SHA256}), "
            f"observed=({len(payload)}, {observed_sha})"
        )
    return _freeze_json(json.loads(payload.decode("utf-8")))


@cache
def load_verified_lcnaf_records(repo_root: Path | None = None) -> tuple[VerifiedLcnafAgencyRecord, ...]:
    """Return all 54 verified LCNAF federal agency and historical predecessor records."""

    doc = load_lcnaf_alignment_manifest(repo_root)
    return tuple(
        VerifiedLcnafAgencyRecord(
            key_id=r["key_id"],
            category=r["category"],
            crosswalk_code=r["crosswalk_code"],
            crosswalk_tier=r["crosswalk_tier"],
            natural_name=r["natural_name"],
            fr_or_alt_name=r["fr_or_alt_name"],
            crosswalk_parent_collapsed=bool(r["crosswalk_parent_collapsed"]),
            crosswalk_defunct_code=bool(r["crosswalk_defunct_code"]),
            resolution_rung=r["resolution_rung"],
            lccn=r["lccn"],
            authority_iri=r["authority_iri"],
            authoritative_label=r["authoritative_label"],
            marc_key=r["marc_key"],
            madsrdf_sha256=r["madsrdf_sha256"],
            madsrdf_bytes=int(r["madsrdf_bytes"]),
            us_prefixed_top1_exact=bool(r["us_prefixed_top1_exact"]),
            bare_name_top1_exact=bool(r["bare_name_top1_exact"]),
            in_pinned_lc_externallinks_zip=bool(r["in_pinned_lc_externallinks_zip"]),
            pinned_zip_wikidata_iris=tuple(r["pinned_zip_wikidata_iris"]),
            pinned_zip_fast_iris=tuple(r["pinned_zip_fast_iris"]),
            wikidata_iris=tuple(r["wikidata_iris"]),
            fast_iris=tuple(r["fast_iris"]),
            viaf_iris=tuple(r["viaf_iris"]),
            isni_iris=tuple(r["isni_iris"]),
            earlier_lccns=tuple(r["earlier_lccns"]),
            earlier_unlinked_labels=tuple(r["earlier_unlinked_labels"]),
            later_lccns=tuple(r["later_lccns"]),
            related_authority_count=int(r["related_authority_count"]),
            succession_encoding_mode=r["succession_encoding_mode"],
        )
        for r in doc["agencies"]
    )


def lookup_verified_lcnaf_for_code(
    agency_code: str,
    *,
    repo_root: Path | None = None,
) -> VerifiedLcnafAgencyRecord | None:
    """Look up a verified LCNAF corporate authority for a regulations.gov ``agency_code``.

    Cross-checks that ``agency_code`` exists in :data:`refspec.registry.agency_crosswalk.AGENCY_CROSSWALK_BY_CODE`
    and preserves independent ``crosswalk_parent_collapsed`` and ``crosswalk_defunct_code``
    flags so callers never silently equate a sub-agency's LCNAF authority with its parent
    department's ``primary_slug``.
    """

    if agency_code not in cw.AGENCY_CROSSWALK_BY_CODE:
        return None
    for record in load_verified_lcnaf_records(repo_root):
        if record.crosswalk_code == agency_code:
            return record
    return None


def build_lcnaf_corporate_queries(
    natural_name: str,
    *,
    parent_department_natural_name: str | None = None,
) -> tuple[str, ...]:
    """Build the ordered 3-query ``suggest2`` ladder covering all 4 LCNAF corporate entry patterns.

    1. ``"United States. <Name>"`` (AACR2/RDA subordinate to jurisdiction: 52/54 = 96.3%)
    2. ``"<Name>"`` (direct entry with ``(U.S.)`` qualifier or ``Federal ...`` corporate body, e.g. ``CMS``, ``FDIC``)
    3. ``"United States. <Parent Dept>. <Name>"`` (department-subordinate office, e.g. ``EOIR`` under ``DOJ``)
    """

    clean = natural_name.strip()
    if not clean:
        raise LcnafAlignmentError("natural_name must not be empty")
    queries: list[str] = []
    if clean.startswith(("United States.", "U.S. ")):
        queries.append(clean)
    else:
        queries.append(f"United States. {clean}")
        queries.append(clean)
    if parent_department_natural_name:
        pclean = parent_department_natural_name.strip().removeprefix("United States.").strip()
        if pclean:
            sub_q = f"United States. {pclean}. {clean}"
            if sub_q not in queries:
                queries.append(sub_q)
    return tuple(queries)


_UNQUALIFIED_US_STATUTORY_CORPORATIONS = frozenset({"federal deposit insurance corporation"})


def select_verified_lcnaf_hit(
    hits: Sequence[Mapping[str, Any]],
    *,
    natural_name: str,
    parent_department_natural_name: str | None = None,
) -> Mapping[str, Any] | None:
    """Select an exact U.S. federal corporate match from ``suggest2`` hits, refusing false friends.

    Requires explicit U.S. jurisdiction or parent-department corporate evidence:
    - Refuses foreign or state jurisdictions (``"Liberia. Environmental Protection Agency"``,
      ``"Bangladesh. Securities and Exchange Commission"``, ``"Alaska. Office of Management and Budget"``).
    - Refuses unqualified corporate labels lacking U.S. federal evidence (including
      ``"Federal Trade Commission"`` if stripped of ``"United States."``); only
      entries in the explicit statutory-corporation allowlist
      (``"Federal Deposit Insurance Corporation"``) are admissible without a
      ``United States`` / ``(U.S.)`` qualifier when no parent department is supplied.
    - Refuses unrequested subordinate divisions or cooperative programs whose
      variant happens to prefix-match (``"Medicare Recovery Audit Contractor
      Program (U.S.)"``, ``"United States. Environmental Protection Agency. Acid
      Rain Division"``) and bare acronym collisions.
    """

    target_norm = _normalize_org_tokens(natural_name.removeprefix("United States.").removeprefix("U.S.").strip())
    if not target_norm:
        return None

    admissible_authorized = {
        f"united states {target_norm}",
        f"u s {target_norm}",
        f"{target_norm} u s",
        f"{target_norm} united states",
    }
    if target_norm.startswith("department of "):
        short_dept = target_norm.removeprefix("department of ").strip()
        admissible_authorized.add(f"united states dept of {short_dept}")

    if parent_department_natural_name:
        pnorm = _normalize_org_tokens(
            parent_department_natural_name.removeprefix("United States.").removeprefix("U.S.").strip()
        )
        if pnorm:
            admissible_authorized.add(f"united states {pnorm} {target_norm}")
            admissible_authorized.add(f"u s {pnorm} {target_norm}")
    elif target_norm in _UNQUALIFIED_US_STATUTORY_CORPORATIONS:
        admissible_authorized.add(target_norm)

    for hit in hits:
        uri = str(hit.get("uri") or "")
        if not uri.startswith(LCNAF_AUTHORITY_PREFIX):
            continue
        lccn = uri.rstrip("/").rsplit("/", 1)[-1]
        if not _LCCN_RE.fullmatch(lccn):
            continue
        alabel = str(hit.get("aLabel") or "").strip()
        if not alabel:
            continue
        # Reject foreign/state jurisdictions ("Liberia. ...", "Alaska. ...") whenever a jurisdiction prefix precedes ". "
        if ". " in alabel and not alabel.startswith(("United States.", "U.S.")):
            continue
        anorm = _normalize_org_tokens(alabel)
        if anorm in admissible_authorized:
            return hit

    return None


def parse_lcnaf_madsrdf_graph(payload: bytes | str | Sequence[Mapping[str, Any]], *, expected_lccn: str) -> ParsedLcnafMadsGraph:
    """Parse one ``<lccn>.madsrdf.json`` JSON-LD array into typed corporate authority facts.

    Verifies that the primary authority node is a corporate authority
    (``madsrdf:CorporateName`` and MARC ``110`` heading), rejecting personal,
    topical, geographic, or title records.
    """

    if not _LCCN_RE.fullmatch(expected_lccn):
        raise LcnafAlignmentError(f"invalid LCCN identifier: {expected_lccn!r}")
    nodes = json.loads(payload) if isinstance(payload, (bytes, str)) else payload
    if not isinstance(nodes, list):
        raise LcnafAlignmentError(f"MADS/RDF JSON-LD payload for {expected_lccn} must be a list of graph nodes")

    by_id: dict[str, Mapping[str, Any]] = {
        str(node["@id"]): node for node in nodes if isinstance(node, Mapping) and isinstance(node.get("@id"), str)
    }
    authority_iri = LCNAF_AUTHORITY_PREFIX + expected_lccn
    main = by_id.get(authority_iri)
    if main is None:
        raise LcnafAlignmentError(f"MADS/RDF graph missing primary authority node {authority_iri}")

    raw_types = main.get("@type", ())
    node_types = {str(t) for t in (raw_types if isinstance(raw_types, list) else (raw_types,)) if isinstance(t, str)}
    disallowed = node_types & _NON_CORPORATE_MADS_TYPES
    if disallowed:
        raise LcnafAlignmentError(
            f"authority {authority_iri} has non-corporate MADS @type {sorted(disallowed)!r}"
        )
    if MADS_CORPORATE_NAME not in node_types:
        raise LcnafAlignmentError(
            f"authority {authority_iri} lacks madsrdf:CorporateName in @type {sorted(node_types)!r}"
        )

    alabels = [
        str(item["@value"])
        for item in main.get(lc.MADS_AUTHORITATIVE_LABEL, ())
        if isinstance(item, Mapping) and "@value" in item and "@language" not in item
    ]
    if not alabels:
        alabels = [
            str(item["@value"])
            for item in main.get(lc.MADS_AUTHORITATIVE_LABEL, ())
            if isinstance(item, Mapping) and "@value" in item
        ]
    if not alabels:
        raise LcnafAlignmentError(f"primary authority node {authority_iri} has no authoritativeLabel")

    marc_keys = [
        str(item["@value"])
        for item in main.get(BFLC_MARC_KEY, ())
        if isinstance(item, Mapping) and "@value" in item
    ]
    marc_110 = [m for m in marc_keys if m.startswith("110")]
    other_1xx = [m for m in marc_keys if _MARC_HEADING_TAG_RE.match(m) and not m.startswith("110")]
    if other_1xx and not marc_110:
        raise LcnafAlignmentError(
            f"authority {authority_iri} carries non-corporate MARC 1XX key {other_1xx[0]!r} without MARC 110"
        )
    if not marc_110:
        raise LcnafAlignmentError(
            f"corporate authority {authority_iri} missing authorized MARC 110 key (found {marc_keys!r})"
        )

    variants: list[str] = []
    for ref in main.get(MADS_HAS_VARIANT, ()):
        if not isinstance(ref, Mapping) or "@id" not in ref:
            continue
        vnode = by_id.get(str(ref["@id"]), {})
        for vitem in vnode.get(MADS_VARIANT_LABEL, ()):
            if isinstance(vitem, Mapping) and "@value" in vitem:
                variants.append(str(vitem["@value"]))

    def _extract_authority_links(predicate: str) -> tuple[tuple[str, ...], tuple[str, ...]]:
        lccns: list[str] = []
        unlinked_labels: list[str] = []
        for ref in main.get(predicate, ()):
            if not isinstance(ref, Mapping) or "@id" not in ref:
                continue
            rid = str(ref["@id"])
            if rid.startswith(LCNAF_AUTHORITY_PREFIX):
                lccns.append(rid.removeprefix(LCNAF_AUTHORITY_PREFIX).rstrip("/"))
            else:
                bnode = by_id.get(rid, {})
                for pred_lbl in (lc.MADS_AUTHORITATIVE_LABEL, MADS_VARIANT_LABEL):
                    for litem in bnode.get(pred_lbl, ()):
                        if isinstance(litem, Mapping) and "@value" in litem:
                            unlinked_labels.append(str(litem["@value"]))
        return tuple(lccns), tuple(unlinked_labels)

    ear_lccns, ear_unlinked = _extract_authority_links(MADS_EARLIER_FORM)
    lat_lccns, _ = _extract_authority_links(MADS_LATER_FORM)
    rel_lccns, _ = _extract_authority_links(MADS_RELATED_AUTHORITY)
    bro_lccns, _ = _extract_authority_links(MADS_BROADER_AUTHORITY)

    close_iris = [
        str(ref["@id"])
        for ref in main.get(lc.MADS_CLOSE_EXTERNAL_AUTHORITY, ())
        if isinstance(ref, Mapping) and isinstance(ref.get("@id"), str)
    ]
    rwo_iris = [
        str(ref["@id"])
        for ref in main.get(MADS_IDENTIFIES_RWO, ())
        if isinstance(ref, Mapping) and isinstance(ref.get("@id"), str)
    ]

    return ParsedLcnafMadsGraph(
        lccn=expected_lccn,
        authority_iri=authority_iri,
        authoritative_label=alabels[0],
        marc_key=marc_110[0],
        variant_labels=tuple(variants),
        earlier_lccns=ear_lccns,
        earlier_unlinked_labels=ear_unlinked,
        later_lccns=lat_lccns,
        related_lccns=rel_lccns,
        broader_lccns=bro_lccns,
        wikidata_iris=tuple(u for u in close_iris if "wikidata.org/entity/" in u),
        fast_iris=tuple(u for u in close_iris if "id.worldcat.org/fast/" in u),
        viaf_iris=tuple(u for u in rwo_iris if "viaf.org/viaf/" in u),
        isni_iris=tuple(u for u in rwo_iris if "isni.org/isni/" in u),
    )


def _scan_lcnaf_assertions(
    lines: Iterable[bytes],
    *,
    retained_subject_iris: frozenset[str] | None = None,
) -> tuple[lc.LcExternalLinkAssertion, ...]:
    """Stream pass 1 over ``external_links.nt``, retaining only matching LCNAF assertions."""

    subject_prefix = ("<" + LCNAF_AUTHORITY_PREFIX).encode("ascii")
    assertions: list[lc.LcExternalLinkAssertion] = []
    claims: set[tuple[str, str, str]] = set()

    for line_number, line in enumerate(lines, start=1):
        if not isinstance(line, bytes):
            raise TypeError("LC external-links statements must be bytes")
        if not line.startswith(subject_prefix):
            continue
        match = lc._IRI_TRIPLE.fullmatch(line)
        if match is None:
            continue
        try:
            subject_iri, predicate_iri, object_iri = (v.decode("ascii") for v in match.groups())
        except UnicodeDecodeError as error:
            raise lc.LcExternalLinksError(f"LCNAF external-links line {line_number} contains non-ASCII IRI") from error
        if retained_subject_iris is not None and subject_iri not in retained_subject_iris:
            continue
        if predicate_iri not in lc.SUPPORTED_PUBLISHER_PREDICATES:
            if predicate_iri.startswith(lc.MADS_NAMESPACE) and predicate_iri.endswith("ExternalAuthority"):
                raise lc.LcExternalLinksError(
                    f"unsupported LCNAF external-authority predicate on line {line_number}: {predicate_iri}"
                )
            continue
        claim = (subject_iri, predicate_iri, object_iri)
        if claim in claims:
            raise lc.LcExternalLinksError(
                f"LC external-links repeats an LCNAF mapping claim on line {line_number}: {claim!r}"
            )
        claims.add(claim)
        stmt_bytes = line.rstrip(b"\r\n")
        assertions.append(
            lc.LcExternalLinkAssertion(
                subject_iri=subject_iri,
                predicate_iri=predicate_iri,
                object_iri=object_iri,
                target_vocabulary=lc._target_vocabulary(object_iri),
                line_number=line_number,
                native_statement=stmt_bytes.decode("ascii"),
                statement_sha256=lc._sha256(stmt_bytes),
            )
        )

    return tuple(assertions)


def parse_lcnaf_external_links_statements(
    lines: Iterable[bytes] | Callable[[], Iterable[bytes]],
    *,
    retained_subject_iris: frozenset[str] | None = None,
) -> tuple[tuple[lc.LcExternalLinkAssertion, ...], Mapping[str, tuple[lc.LcExternalEndpointLabel, ...]]]:
    """Parse ``http://id.loc.gov/authorities/names/`` links from ``external_links.nt`` bytes in bounded ``O(retained)`` memory.

    Requires a reopenable zero-argument line-stream factory (such as
    ``lambda: archive.open(...)``) or a re-iterable ``Iterable[bytes]``
    container. Refuses single-pass ``Iterator[bytes]`` inputs so callers never
    buffer millions of unrelated literal lines from the 1.85 GB stream in RAM.
    """

    if isinstance(lines, Iterator):
        raise TypeError(
            "parse_lcnaf_external_links_statements requires a re-iterable container or zero-argument "
            "stream factory for bounded-memory two-pass scanning; got a single-pass Iterator"
        )

    if callable(lines):
        assertions = _scan_lcnaf_assertions(lines(), retained_subject_iris=retained_subject_iris)
        if not assertions:
            return (), MappingProxyType({})
        target_vocabularies = {row.object_iri: row.target_vocabulary for row in assertions}
        labels = lc._scan_endpoint_labels(lines(), target_vocabularies=target_vocabularies)
        return assertions, MappingProxyType(dict(labels))

    assertions = _scan_lcnaf_assertions(lines, retained_subject_iris=retained_subject_iris)
    if not assertions:
        return (), MappingProxyType({})
    target_vocabularies = {row.object_iri: row.target_vocabulary for row in assertions}
    labels = lc._scan_endpoint_labels(lines, target_vocabularies=target_vocabularies)
    return assertions, MappingProxyType(dict(labels))


def load_lcnaf_external_links_from_archive(
    path: Path,
    *,
    retained_subject_iris: frozenset[str] | None = None,
) -> tuple[tuple[lc.LcExternalLinkAssertion, ...], Mapping[str, tuple[lc.LcExternalEndpointLabel, ...]]]:
    """Verify the pinned ``lcsh-externallinks-2026-08-15.nt.zip`` archive and stream LCNAF assertions in two passes."""

    source = Path(path)
    lc._verify_archive(source)
    try:
        with zipfile.ZipFile(source) as archive:
            members = archive.infolist()
            if len(members) != 1 or members[0].filename != lc.LC_EXTERNAL_LINKS_MEMBER:
                raise lc.LcExternalLinksError(
                    f"LC external-links ZIP member shape differs: {[item.filename for item in members]!r}"
                )
            if members[0].file_size != lc.LC_EXTERNAL_LINKS_UNCOMPRESSED_BYTE_LENGTH:
                raise lc.LcExternalLinksError(
                    "LC external-links uncompressed byte length differs: "
                    f"expected {lc.LC_EXTERNAL_LINKS_UNCOMPRESSED_BYTE_LENGTH}, "
                    f"observed {members[0].file_size}"
                )
            with archive.open(lc.LC_EXTERNAL_LINKS_MEMBER) as stream1:
                assertions = _scan_lcnaf_assertions(stream1, retained_subject_iris=retained_subject_iris)
            if not assertions:
                return (), MappingProxyType({})
            target_vocabularies = {row.object_iri: row.target_vocabulary for row in assertions}
            with archive.open(lc.LC_EXTERNAL_LINKS_MEMBER) as stream2:
                labels = lc._scan_endpoint_labels(stream2, target_vocabularies=target_vocabularies)
    except zipfile.BadZipFile as error:
        raise lc.LcExternalLinksError(f"LC external-links source is not a valid ZIP: {source}") from error

    return assertions, MappingProxyType(dict(labels))


__all__ = [
    "EVIDENCE_RELATIVE_DIR",
    "LCNAF_ALIGNMENT_BYTE_LENGTH",
    "LCNAF_ALIGNMENT_FILENAME",
    "LCNAF_ALIGNMENT_SHA256",
    "LCNAF_AUTHORITY_PREFIX",
    "LcnafAlignmentError",
    "ParsedLcnafMadsGraph",
    "SuccessionEncodingMode",
    "VerifiedLcnafAgencyRecord",
    "build_lcnaf_corporate_queries",
    "load_lcnaf_alignment_manifest",
    "load_lcnaf_external_links_from_archive",
    "load_verified_lcnaf_records",
    "lookup_verified_lcnaf_for_code",
    "parse_lcnaf_external_links_statements",
    "parse_lcnaf_madsrdf_graph",
    "select_verified_lcnaf_hit",
]
