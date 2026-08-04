"""Current List of Subjects matching against the 2025 Federal Register thesaurus."""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from typing import Literal

from refspec.registry.federal_register_thesaurus_2025 import (
    FederalRegisterThesaurus2025,
    OfficialTerm,
    federal_register_thesaurus_2025_concept_iri,
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


class FederalRegisterListsOfSubjectsError(ValueError):
    """A List of Subjects value cannot be classified without guessing."""


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
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


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
    """Classify one current List of Subjects value without minting a concept."""

    if not isinstance(literal, str) or not literal.strip():
        raise FederalRegisterListsOfSubjectsError(
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
                reason="exact match to a 2025 variant with one official target",
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
            reason="the 2025 variant is repeated, ambiguous, or unresolved",
        )

    if allow_source_local_open_term:
        if not source_record_id or not source_path:
            raise FederalRegisterListsOfSubjectsError(
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
            reason="preserve the source-assigned value without managed concept identity",
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
        reason="no exact official term or unambiguous recognized variant exists",
    )


__all__ = [
    "LISTS_OF_SUBJECTS_RESOLUTION_POLICY_VERSION",
    "FederalRegisterListsOfSubjectsError",
    "ListsOfSubjectsResolution",
    "resolve_list_of_subjects_term",
]
