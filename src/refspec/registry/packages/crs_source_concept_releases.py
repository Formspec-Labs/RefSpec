"""Ring-scoped source-concept releases from reconciled CRS packages.

CRS source packages preserve the Library of Congress schemes, Congress.gov
captures, and RefSpec ``localRecordId`` values without claiming concept
identity.  This module takes the next explicit step: after reconciliation is
complete, it publishes those stable local records as source-scoped concepts.

The Legislative Subject Terms source contains three semantic kinds.  Topical
terms publish in the subject ring; geographic and organization terms publish
in the entity ring.  Policy Areas publish in a separate subject release
because they come from a separate source package and scheme.  None of these
releases grants admission, retrieval, or output permission.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from refspec.registry.crs_legislative_resources import CRSIdentityError
from refspec.registry.infrastructure.artifact_serialization import sha256_digest
from refspec.registry.infrastructure.source_concept_release import (
    SemanticRing,
    SourceConceptReleaseBundle,
    build_source_concept_release_bundle,
)
from refspec.registry.infrastructure.source_controlled_resource import (
    SourceControlledResourceBundle,
)
from refspec.registry.packages.crs_source_packages import (
    CRSResourceReconciliation,
    CRSSourcePackages,
)

CRS_LEGISLATIVE_SUBJECT_SELECTION_POLICY = {
    "id": "urn:ref:crs-source-concept-selection:legislative-topical-subjects:v1",
    "type": "explicitObservationSet",
}
CRS_LEGISLATIVE_ENTITY_SELECTION_POLICY = {
    "id": "urn:ref:crs-source-concept-selection:legislative-entities:v1",
    "type": "explicitObservationSet",
}
CRS_POLICY_AREA_SELECTION_POLICY = {
    "id": "urn:ref:crs-source-concept-selection:policy-areas:v1",
    "type": "explicitObservationSet",
}

_LEGISLATIVE_SUBJECT_CATEGORIES = frozenset({"subject"})
_LEGISLATIVE_ENTITY_CATEGORIES = frozenset(
    {
        "geographicEntity",
        "organizationName",
    }
)
_LEGISLATIVE_CATEGORIES = _LEGISLATIVE_SUBJECT_CATEGORIES | _LEGISLATIVE_ENTITY_CATEGORIES
_POLICY_AREA_CATEGORIES = frozenset({"policyArea"})


@dataclass(frozen=True, slots=True)
class CRSSourceConceptReleases:
    """The three releases produced from one reconciled CRS source ledger."""

    legislative_subjects: SourceConceptReleaseBundle
    legislative_entities: SourceConceptReleaseBundle
    policy_areas: SourceConceptReleaseBundle

    def releases(self) -> tuple[SourceConceptReleaseBundle, ...]:
        """Return releases in stable source-then-ring order."""

        return (
            self.legislative_subjects,
            self.legislative_entities,
            self.policy_areas,
        )


def _reconciliation_by_resource(
    packages: CRSSourcePackages,
) -> dict[str, CRSResourceReconciliation]:
    packages.require_reconciled()
    by_resource = {reconciliation.resource_name: reconciliation for reconciliation in packages.reconciliations}
    if len(by_resource) != len(packages.reconciliations) or set(by_resource) != {
        "legislativeSubjectTerms",
        "policyAreas",
    }:
        raise CRSIdentityError("CRS source-concept releases require one reconciliation for each source package")
    return by_resource


def _require_exact_reconciliation_binding(
    *,
    resource_name: str,
    source: SourceControlledResourceBundle,
    reconciliation: CRSResourceReconciliation,
) -> Mapping[str, Any]:
    manifest_id = source.resource_manifest.get("id")
    local_record_id_set_digest = source.coverage_report.get("localRecordIdSetDigest")
    local_record_content_set_digest = source.coverage_report.get("localRecordContentSetDigest")
    if reconciliation.resource_name != resource_name:
        raise CRSIdentityError(f"CRS {resource_name} reconciliation names another resource")
    if reconciliation.requires_human_review or reconciliation.status == "reviewRequired":
        raise CRSIdentityError(f"CRS {resource_name} reconciliation still requires human review")
    if reconciliation.current_manifest_id != manifest_id:
        raise CRSIdentityError(f"CRS {resource_name} reconciliation names the wrong source manifest")
    if reconciliation.current_local_record_id_set_digest != local_record_id_set_digest:
        raise CRSIdentityError(f"CRS {resource_name} reconciliation local-record identity digest drifted")
    if reconciliation.current_local_record_content_set_digest != local_record_content_set_digest:
        raise CRSIdentityError(f"CRS {resource_name} reconciliation local-record content digest drifted")
    return reconciliation.as_dict()


def _selected_observation_ids(
    source: SourceControlledResourceBundle,
    *,
    categories: frozenset[str],
) -> tuple[str, ...]:
    identifiers: list[str] = []
    for index, observation in enumerate(source.observations):
        category = observation.get("category")
        identifier = observation.get("id")
        if category in categories:
            if not isinstance(identifier, str) or not identifier:
                raise CRSIdentityError(f"CRS source observation {index} lacks an identifier")
            identifiers.append(identifier)
    if not identifiers:
        raise CRSIdentityError("CRS source-concept selection must contain at least one observation")
    if len(identifiers) != len(set(identifiers)):
        raise CRSIdentityError("CRS source observations repeat an identifier")
    return tuple(sorted(identifiers))


def _require_exact_categories(
    source: SourceControlledResourceBundle,
    *,
    expected: frozenset[str],
    resource_name: str,
) -> None:
    categories = {observation.get("category") for observation in source.observations}
    if categories != set(expected):
        raise CRSIdentityError(
            f"CRS {resource_name} categories changed: expected {sorted(expected)!r}, "
            f"received {sorted(str(value) for value in categories)!r}"
        )


def _build_release(
    source: SourceControlledResourceBundle,
    *,
    semantic_ring: SemanticRing,
    categories: frozenset[str],
    selection_policy: Mapping[str, str],
    reconciliation_record: Mapping[str, Any],
) -> SourceConceptReleaseBundle:
    selected_observation_ids = _selected_observation_ids(
        source,
        categories=categories,
    )
    selected_ids = frozenset(selected_observation_ids)
    selected_source_artifacts = {
        str(observation["sourceArtifact"]) for observation in source.observations if observation["id"] in selected_ids
    }
    return build_source_concept_release_bundle(
        source,
        semantic_ring=semantic_ring,
        selected_observation_ids=selected_observation_ids,
        selection_policy=selection_policy,
        rights_metadata=tuple(
            {
                "type": "RightsMetadata",
                "rightsStatus": "notStated",
                "sourceArtifact": source_artifact,
                "sourceDigest": sha256_digest(source.source_artifacts[source_artifact]),
            }
            for source_artifact in sorted(selected_source_artifacts)
        ),
        reconciliation_record=reconciliation_record,
    )


def build_crs_source_concept_releases(
    packages: CRSSourcePackages,
) -> CRSSourceConceptReleases:
    """Build three ring-scoped releases from one exactly reconciled ledger."""

    reconciliations = _reconciliation_by_resource(packages)
    legislative_source = packages.legislative_subject_terms
    policy_source = packages.policy_areas
    _require_exact_categories(
        legislative_source,
        expected=_LEGISLATIVE_CATEGORIES,
        resource_name="legislativeSubjectTerms",
    )
    _require_exact_categories(
        policy_source,
        expected=_POLICY_AREA_CATEGORIES,
        resource_name="policyAreas",
    )
    legislative_reconciliation = _require_exact_reconciliation_binding(
        resource_name="legislativeSubjectTerms",
        source=legislative_source,
        reconciliation=reconciliations["legislativeSubjectTerms"],
    )
    policy_reconciliation = _require_exact_reconciliation_binding(
        resource_name="policyAreas",
        source=policy_source,
        reconciliation=reconciliations["policyAreas"],
    )
    return CRSSourceConceptReleases(
        legislative_subjects=_build_release(
            legislative_source,
            semantic_ring="subject",
            categories=_LEGISLATIVE_SUBJECT_CATEGORIES,
            selection_policy=CRS_LEGISLATIVE_SUBJECT_SELECTION_POLICY,
            reconciliation_record=legislative_reconciliation,
        ),
        legislative_entities=_build_release(
            legislative_source,
            semantic_ring="entity",
            categories=_LEGISLATIVE_ENTITY_CATEGORIES,
            selection_policy=CRS_LEGISLATIVE_ENTITY_SELECTION_POLICY,
            reconciliation_record=legislative_reconciliation,
        ),
        policy_areas=_build_release(
            policy_source,
            semantic_ring="subject",
            categories=_POLICY_AREA_CATEGORIES,
            selection_policy=CRS_POLICY_AREA_SELECTION_POLICY,
            reconciliation_record=policy_reconciliation,
        ),
    )


__all__: Sequence[str] = (
    "CRS_LEGISLATIVE_ENTITY_SELECTION_POLICY",
    "CRS_LEGISLATIVE_SUBJECT_SELECTION_POLICY",
    "CRS_POLICY_AREA_SELECTION_POLICY",
    "CRSSourceConceptReleases",
    "build_crs_source_concept_releases",
)
