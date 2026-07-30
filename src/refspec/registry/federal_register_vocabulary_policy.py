"""Federal Register vocabulary selection, crosswalk, and source-term policy."""

from __future__ import annotations

import json
import unicodedata
from collections import Counter, defaultdict
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from typing import Any, Literal

from refspec.registry.federal_register_thesaurus import (
    FederalRegisterThesaurus,
)
from refspec.registry.federal_register_thesaurus_2025 import (
    FEDERAL_REGISTER_THESAURUS_2025_ISSUED,
    FEDERAL_REGISTER_THESAURUS_2025_SHA256,
    FEDERAL_REGISTER_THESAURUS_2025_URL,
    FederalRegisterThesaurus2025,
    OfficialTerm,
    federal_register_thesaurus_2025_concept_iri,
)
from refspec.storage import canonical_json

FEDERAL_REGISTER_THESAURUS_1995_SHA256 = (
    "sha256:d5e013336d4179790e8d6574d4dc9d8cfcb10ce76af202ff4db068617eb8fd30"
)
FEDERAL_REGISTER_THESAURUS_1995_URL = (
    "https://www.archives.gov/files/federal-register/cfr/"
    "thesaurus-alpha.txt"
)
FEDERAL_REGISTER_CROSSWALK_VERSION = (
    "federal-register-thesaurus-1995-to-2025-evidence-crosswalk-v1"
)
LISTS_OF_SUBJECTS_RESOLUTION_POLICY_VERSION = (
    "federal-register-lists-of-subjects-resolution-v1"
)

ListsOfSubjectsClassification = Literal[
    "officialTerm",
    "recognizedVariant",
    "sourceLocalOpenTerm",
    "unresolved",
]
CrosswalkCategory = Literal[
    "unchanged",
    "renamed",
    "redirected",
    "ambiguous",
    "removed",
]


class FederalRegisterVocabularyPolicyError(ValueError):
    """Federal Register vocabulary evidence or policy is incomplete."""


@dataclass(frozen=True, slots=True)
class ListsOfSubjectsResolution:
    """Explicit result for one authored List of Subjects literal."""

    policy_version: str
    literal: str
    classification: ListsOfSubjectsClassification
    concept_iris: tuple[str, ...]
    variant_ids: tuple[str, ...]
    source_record_id: str | None
    source_path: str | None
    concept_minted: bool
    reason: str


def _normalize_exact(value: str) -> str:
    return " ".join(
        unicodedata.normalize("NFKC", value).casefold().split()
    )


def _official_iri(term: OfficialTerm) -> str:
    return federal_register_thesaurus_2025_concept_iri(term.concept_id)


def resolve_list_of_subjects_term(
    literal: str,
    thesaurus: FederalRegisterThesaurus2025,
    *,
    source_record_id: str | None = None,
    source_path: str | None = None,
    allow_source_local_open_term: bool = False,
) -> ListsOfSubjectsResolution:
    """Classify one List of Subjects value without silently minting a concept.

    Unknown text becomes a source-local open term only when the caller supplies
    its exact source record and source path and explicitly enables that route.
    An ambiguous or defective thesaurus variant remains unresolved even when
    the source assigned it.
    """

    if not isinstance(literal, str) or not literal.strip():
        raise FederalRegisterVocabularyPolicyError(
            "List of Subjects literal must be non-empty text"
        )
    value = " ".join(literal.split())
    key = _normalize_exact(value)
    official = thesaurus.official_by_normalized_label().get(key)
    if official is not None:
        return ListsOfSubjectsResolution(
            policy_version=LISTS_OF_SUBJECTS_RESOLUTION_POLICY_VERSION,
            literal=value,
            classification="officialTerm",
            concept_iris=(_official_iri(official),),
            variant_ids=(),
            source_record_id=source_record_id,
            source_path=source_path,
            concept_minted=False,
            reason="exact match to an official April 1, 2025 indexing term",
        )

    variants = thesaurus.variants_by_normalized_label().get(key, ())
    if variants:
        targets = tuple(
            sorted(
                {
                    federal_register_thesaurus_2025_concept_iri(target)
                    for variant in variants
                    for target in variant.target_concept_ids
                }
            )
        )
        statuses = {variant.resolution_status for variant in variants}
        if statuses == {"recognizedVariant"} and len(targets) == 1:
            return ListsOfSubjectsResolution(
                policy_version=LISTS_OF_SUBJECTS_RESOLUTION_POLICY_VERSION,
                literal=value,
                classification="recognizedVariant",
                concept_iris=targets,
                variant_ids=tuple(item.variant_id for item in variants),
                source_record_id=source_record_id,
                source_path=source_path,
                concept_minted=False,
                reason=(
                    "exact match to a 2025 variant with one resolved official "
                    "See target"
                ),
            )
        return ListsOfSubjectsResolution(
            policy_version=LISTS_OF_SUBJECTS_RESOLUTION_POLICY_VERSION,
            literal=value,
            classification="unresolved",
            concept_iris=targets,
            variant_ids=tuple(item.variant_id for item in variants),
            source_record_id=source_record_id,
            source_path=source_path,
            concept_minted=False,
            reason=(
                "the 2025 source repeats this variant, redirects it to "
                "multiple official terms, or does not resolve its target"
            ),
        )

    if allow_source_local_open_term:
        if not source_record_id or not source_path:
            raise FederalRegisterVocabularyPolicyError(
                "source-local open terms require source_record_id and source_path"
            )
        return ListsOfSubjectsResolution(
            policy_version=LISTS_OF_SUBJECTS_RESOLUTION_POLICY_VERSION,
            literal=value,
            classification="sourceLocalOpenTerm",
            concept_iris=(),
            variant_ids=(),
            source_record_id=source_record_id,
            source_path=source_path,
            concept_minted=False,
            reason=(
                "the source assigned this non-thesaurus literal; preserve it "
                "as source-local evidence without a managed concept identity"
            ),
        )
    return ListsOfSubjectsResolution(
        policy_version=LISTS_OF_SUBJECTS_RESOLUTION_POLICY_VERSION,
        literal=value,
        classification="unresolved",
        concept_iris=(),
        variant_ids=(),
        source_record_id=source_record_id,
        source_path=source_path,
        concept_minted=False,
        reason=(
            "no exact official term or unambiguous recognized variant exists, "
            "and the source-local open-term route was not authorized"
        ),
    )


def _historical_preferred_labels(
    historical: FederalRegisterThesaurus,
) -> dict[str, str]:
    result: dict[str, str] = {}
    for label in historical.labels:
        if label.role != "preferred":
            continue
        if label.concept_id in result:
            raise FederalRegisterVocabularyPolicyError(
                f"1995 concept {label.concept_id!r} repeats its preferred label"
            )
        result[label.concept_id] = label.literal
    return result


def _historical_labels(
    historical: FederalRegisterThesaurus,
) -> dict[str, tuple[str, ...]]:
    values: dict[str, list[str]] = defaultdict(list)
    for label in historical.labels:
        if label.literal not in values[label.concept_id]:
            values[label.concept_id].append(label.literal)
    return {key: tuple(value) for key, value in values.items()}


def _current_label_evidence(
    literal: str,
    current: FederalRegisterThesaurus2025,
) -> tuple[set[str], list[dict[str, Any]], bool]:
    key = _normalize_exact(literal)
    official = current.official_by_normalized_label().get(key)
    if official is not None:
        return (
            {official.concept_id},
            [
                {
                    "literal": literal,
                    "matchKind": "currentOfficialTerm",
                    "targetConceptIds": [official.concept_id],
                    "currentLocator": asdict(official.locator),
                }
            ],
            False,
        )
    variants = current.variants_by_normalized_label().get(key, ())
    if not variants:
        return set(), [], False
    targets = {
        target
        for variant in variants
        for target in variant.target_concept_ids
    }
    ambiguous = (
        len(targets) != 1
        or any(
            variant.resolution_status != "recognizedVariant"
            for variant in variants
        )
    )
    return (
        targets,
        [
            {
                "literal": literal,
                "matchKind": "currentVariant",
                "variantIds": [item.variant_id for item in variants],
                "variantStatuses": sorted(
                    {item.resolution_status for item in variants}
                ),
                "targetConceptIds": sorted(targets),
                "currentLocators": [
                    asdict(item.locator) for item in variants
                ],
            }
        ],
        ambiguous,
    )


def build_federal_register_thesaurus_crosswalk(
    historical: FederalRegisterThesaurus,
    current: FederalRegisterThesaurus2025,
) -> dict[str, Any]:
    """Build an evidence-only 1995-to-2025 term crosswalk.

    ``renamed`` requires the old preferred label to be a current publisher
    variant with one official target. ``redirected`` uses a historical
    alternate-label chain and remains an analysis result, not an equivalence
    assertion. Ambiguity never collapses to one target.
    """

    if historical.source_sha256 != FEDERAL_REGISTER_THESAURUS_1995_SHA256:
        raise FederalRegisterVocabularyPolicyError(
            "crosswalk requires the pinned 1995 source"
        )
    if current.source_sha256 != FEDERAL_REGISTER_THESAURUS_2025_SHA256:
        raise FederalRegisterVocabularyPolicyError(
            "crosswalk requires the pinned April 1, 2025 source"
        )
    preferred_by_concept = _historical_preferred_labels(historical)
    labels_by_concept = _historical_labels(historical)
    current_by_id = {
        item.concept_id: item for item in current.official_terms
    }
    rows: list[dict[str, Any]] = []
    incoming_targets: set[str] = set()

    for concept in historical.concepts:
        preferred = preferred_by_concept[concept.concept_id]
        preferred_targets, preferred_evidence, preferred_ambiguous = (
            _current_label_evidence(preferred, current)
        )
        evidence = [
            {
                **item,
                "historicalLabelRole": "preferred",
                "historicalLocator": asdict(concept.locator),
            }
            for item in preferred_evidence
        ]
        category: CrosswalkCategory
        targets: set[str] = set()
        basis: str
        review_required = False

        preferred_official = any(
            item["matchKind"] == "currentOfficialTerm"
            for item in preferred_evidence
        )
        preferred_variant = any(
            item["matchKind"] == "currentVariant"
            for item in preferred_evidence
        )
        if preferred_official and len(preferred_targets) == 1:
            category = "unchanged"
            targets = set(preferred_targets)
            basis = "exactPreferredLabel"
        elif (
            preferred_variant
            and len(preferred_targets) == 1
            and not preferred_ambiguous
        ):
            category = "renamed"
            targets = set(preferred_targets)
            basis = "currentPublisherVariantRedirect"
        else:
            candidate_targets = set(preferred_targets)
            ambiguous = preferred_ambiguous
            for alternate in labels_by_concept[concept.concept_id]:
                if alternate == preferred:
                    continue
                alternate_targets, alternate_evidence, alternate_ambiguous = (
                    _current_label_evidence(alternate, current)
                )
                candidate_targets.update(alternate_targets)
                ambiguous = ambiguous or alternate_ambiguous
                evidence.extend(
                    {
                        **item,
                        "historicalLabelRole": "alternate",
                        "historicalLocator": asdict(concept.locator),
                    }
                    for item in alternate_evidence
                )
            targets = candidate_targets
            if ambiguous or len(targets) > 1:
                category = "ambiguous"
                basis = "multipleOrDefectiveLabelPaths"
                review_required = True
            elif len(targets) == 1:
                category = "redirected"
                basis = "historicalAlternateLabelChain"
                review_required = True
            elif preferred_variant:
                category = "ambiguous"
                basis = "unresolvedCurrentVariant"
                review_required = True
            else:
                category = "removed"
                basis = "noCurrentLabelEvidence"

        incoming_targets.update(targets)
        rows.append(
            {
                "historicalConceptId": concept.concept_id,
                "historicalPreferredLabel": preferred,
                "historicalLocator": asdict(concept.locator),
                "category": category,
                "basis": basis,
                "reviewRequired": review_required,
                "targetConceptIds": sorted(targets),
                "targetConceptIris": [
                    federal_register_thesaurus_2025_concept_iri(target)
                    for target in sorted(targets)
                ],
                "targetPreferredLabels": [
                    current_by_id[target].label for target in sorted(targets)
                ],
                "evidence": evidence,
            }
        )

    added = [
        {
            "conceptId": term.concept_id,
            "conceptIri": _official_iri(term),
            "preferredLabel": term.label,
            "locator": asdict(term.locator),
            "category": "added",
            "basis": "noIncoming1995LabelPath",
        }
        for term in current.official_terms
        if term.concept_id not in incoming_targets
    ]
    category_counts = Counter(row["category"] for row in rows)
    category_counts["added"] = len(added)
    result = {
        "schemaVersion": "1.0",
        "crosswalkVersion": FEDERAL_REGISTER_CROSSWALK_VERSION,
        "authority": {
            "status": "analysisOnly",
            "conceptIdentityAssertions": False,
            "mappingPublicationAuthorized": False,
            "candidateSelectionAuthorized": False,
            "interpretation": (
                "Rows record exact-label and authored redirect evidence. "
                "Redirected and ambiguous rows require review and never assert "
                "SKOS exactMatch, closeMatch, broader, or narrower."
            ),
        },
        "sources": {
            "historical": {
                "id": FEDERAL_REGISTER_THESAURUS_1995_URL,
                "version": "1995-11-16",
                "sha256": historical.source_sha256,
                "preferredTermCount": len(historical.concepts),
            },
            "current": {
                "id": FEDERAL_REGISTER_THESAURUS_2025_URL,
                "version": FEDERAL_REGISTER_THESAURUS_2025_ISSUED,
                "sha256": current.source_sha256,
                "officialTermCount": len(current.official_terms),
            },
        },
        "counts": {
            "historicalRows": len(rows),
            "currentOfficialTerms": len(current.official_terms),
            **{
                category: category_counts.get(category, 0)
                for category in (
                    "unchanged",
                    "renamed",
                    "redirected",
                    "ambiguous",
                    "removed",
                    "added",
                )
            },
        },
        "historicalTerms": rows,
        "added2025Terms": added,
    }
    validate_federal_register_thesaurus_crosswalk(
        result,
        historical=historical,
        current=current,
    )
    return result


def federal_register_thesaurus_crosswalk_bytes(
    crosswalk: Mapping[str, Any],
) -> bytes:
    """Serialize a validated crosswalk as canonical JSON."""

    return canonical_json(dict(crosswalk)).encode("utf-8") + b"\n"


def load_federal_register_thesaurus_crosswalk(
    source: bytes | str,
    *,
    historical: FederalRegisterThesaurus | None = None,
    current: FederalRegisterThesaurus2025 | None = None,
) -> dict[str, Any]:
    """Load the checked-in crosswalk and optionally validate exact members."""

    try:
        value = json.loads(source)
    except (TypeError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise FederalRegisterVocabularyPolicyError(
            f"Federal Register crosswalk is not valid JSON: {error}"
        ) from error
    if not isinstance(value, dict):
        raise FederalRegisterVocabularyPolicyError(
            "Federal Register crosswalk must be an object"
        )
    validate_federal_register_thesaurus_crosswalk(
        value,
        historical=historical,
        current=current,
    )
    return value


def validate_federal_register_thesaurus_crosswalk(
    crosswalk: Mapping[str, Any],
    *,
    historical: FederalRegisterThesaurus | None = None,
    current: FederalRegisterThesaurus2025 | None = None,
) -> None:
    """Validate crosswalk coverage, source pins, and non-authority boundary."""

    if (
        crosswalk.get("schemaVersion") != "1.0"
        or crosswalk.get("crosswalkVersion")
        != FEDERAL_REGISTER_CROSSWALK_VERSION
    ):
        raise FederalRegisterVocabularyPolicyError(
            "Federal Register crosswalk version drifted"
        )
    authority = crosswalk.get("authority")
    if not isinstance(authority, Mapping) or (
        authority.get("status") != "analysisOnly"
        or authority.get("conceptIdentityAssertions") is not False
        or authority.get("mappingPublicationAuthorized") is not False
        or authority.get("candidateSelectionAuthorized") is not False
    ):
        raise FederalRegisterVocabularyPolicyError(
            "Federal Register crosswalk must remain analysis-only"
        )
    sources = crosswalk.get("sources")
    if not isinstance(sources, Mapping):
        raise FederalRegisterVocabularyPolicyError(
            "Federal Register crosswalk source pins are required"
        )
    historical_source = sources.get("historical")
    current_source = sources.get("current")
    if not isinstance(historical_source, Mapping) or (
        historical_source.get("sha256")
        != FEDERAL_REGISTER_THESAURUS_1995_SHA256
    ):
        raise FederalRegisterVocabularyPolicyError(
            "Federal Register crosswalk 1995 source pin drifted"
        )
    if not isinstance(current_source, Mapping) or (
        current_source.get("sha256")
        != FEDERAL_REGISTER_THESAURUS_2025_SHA256
    ):
        raise FederalRegisterVocabularyPolicyError(
            "Federal Register crosswalk 2025 source pin drifted"
        )
    rows = crosswalk.get("historicalTerms")
    added = crosswalk.get("added2025Terms")
    counts = crosswalk.get("counts")
    if (
        not isinstance(rows, list)
        or not isinstance(added, list)
        or not isinstance(counts, Mapping)
        or any(not isinstance(item, Mapping) for item in (*rows, *added))
    ):
        raise FederalRegisterVocabularyPolicyError(
            "Federal Register crosswalk rows and counts are required"
        )
    categories = {
        "unchanged",
        "renamed",
        "redirected",
        "ambiguous",
        "removed",
    }
    if any(item.get("category") not in categories for item in rows):
        raise FederalRegisterVocabularyPolicyError(
            "Federal Register crosswalk has an unknown historical category"
        )
    historical_ids = [str(item.get("historicalConceptId")) for item in rows]
    if len(set(historical_ids)) != len(historical_ids):
        raise FederalRegisterVocabularyPolicyError(
            "Federal Register crosswalk repeats a 1995 concept"
        )
    target_ids = {
        str(target)
        for item in rows
        for target in item.get("targetConceptIds", [])
    }
    added_ids = {str(item.get("conceptId")) for item in added}
    if target_ids & added_ids:
        raise FederalRegisterVocabularyPolicyError(
            "an added 2025 term also has incoming 1995 evidence"
        )
    observed = Counter(str(item["category"]) for item in rows)
    if (
        counts.get("historicalRows") != len(rows)
        or counts.get("currentOfficialTerms") != len(target_ids | added_ids)
        or any(
            counts.get(category) != observed.get(category, 0)
            for category in categories
        )
        or counts.get("added") != len(added)
    ):
        raise FederalRegisterVocabularyPolicyError(
            "Federal Register crosswalk counts drifted"
        )
    if historical is not None and (
        set(historical_ids)
        != {item.concept_id for item in historical.concepts}
    ):
        raise FederalRegisterVocabularyPolicyError(
            "Federal Register crosswalk does not cover the exact 1995 release"
        )
    if current is not None:
        current_ids = {item.concept_id for item in current.official_terms}
        if target_ids | added_ids != current_ids:
            raise FederalRegisterVocabularyPolicyError(
                "Federal Register crosswalk does not cover the exact 2025 release"
            )


__all__ = [
    "FEDERAL_REGISTER_CROSSWALK_VERSION",
    "FEDERAL_REGISTER_THESAURUS_1995_SHA256",
    "LISTS_OF_SUBJECTS_RESOLUTION_POLICY_VERSION",
    "FederalRegisterVocabularyPolicyError",
    "ListsOfSubjectsResolution",
    "build_federal_register_thesaurus_crosswalk",
    "federal_register_thesaurus_crosswalk_bytes",
    "load_federal_register_thesaurus_crosswalk",
    "resolve_list_of_subjects_term",
    "validate_federal_register_thesaurus_crosswalk",
]
