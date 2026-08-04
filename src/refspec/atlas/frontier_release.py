"""Pass-2 cutting for sealed subject mapping-frontier releases.

Pass 1 produces a :class:`PinnedSelectionReceipt` against the full source.
This module consumes that exact receipt, preserves the selected source-scoped
concept identities, and builds one ordinary ``SourceConceptRelease`` whose
declared scope is ``policyFrontier``.  Candidate generation starts only from
the resulting sealed release; it is deliberately absent from this module.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, cast

from refspec.registry.infrastructure.semantic_foundation import RightsMetadata
from refspec.registry.infrastructure.source_concept_release import (
    SourceConceptReleaseBundle,
    SourceConceptReleaseError,
    build_source_concept_release_bundle,
)
from refspec.registry.infrastructure.source_controlled_resource import (
    SourceControlledResourceBundle,
)

from .frontier import PinnedSelectionReceipt, SelectionReceiptError


class FrontierReleaseError(ValueError):
    """Pass 2 received stale inputs or could not close the frontier release."""


def cut_subject_frontier_release(
    source: SourceControlledResourceBundle,
    *,
    selection_receipt: PinnedSelectionReceipt,
    rights_metadata: Sequence[RightsMetadata | Mapping[str, Any]],
    lifecycle_records: Sequence[Mapping[str, Any]] = (),
    reconciliation_record: Mapping[str, Any] | None = None,
) -> SourceConceptReleaseBundle:
    """Cut one complete subject frontier from an exact pass-1 receipt.

    The source capture remains embedded in full.  Release membership is the
    receipt's exact selected observation set; the shared release builder then
    verifies the receipt/source facts and the exact ``(concept, observation)``
    member pairs before deriving release identity.
    """

    if not isinstance(source, SourceControlledResourceBundle):
        raise FrontierReleaseError("frontier cutting requires one verified source capture")
    if not isinstance(selection_receipt, PinnedSelectionReceipt):
        raise FrontierReleaseError("frontier cutting requires one pinned selection receipt")
    try:
        receipt = selection_receipt.verified_receipt()
    except SelectionReceiptError as error:
        raise FrontierReleaseError(f"selection receipt is invalid: {error}") from error
    if receipt.scope_kind != "policyFrontier":
        raise FrontierReleaseError("frontier cutting requires a policyFrontier selection receipt")
    record = receipt.as_record()
    selected = tuple(
        str(value["sourceObservationId"]) for value in cast(Sequence[Mapping[str, Any]], record["selectedConcepts"])
    )
    policy = cast(Mapping[str, Any], record["selectionPolicy"])
    try:
        return build_source_concept_release_bundle(
            source,
            semantic_ring="subject",
            selected_observation_ids=selected,
            selection_policy={
                "id": policy["id"],
                "type": "policyFrontier",
                "selectionReceipt": selection_receipt.pin(),
            },
            rights_metadata=rights_metadata,
            lifecycle_records=lifecycle_records,
            reconciliation_record=reconciliation_record,
            selection_receipt=record,
        )
    except SourceConceptReleaseError as error:
        raise FrontierReleaseError(f"frontier release is invalid: {error}") from error


__all__ = [
    "FrontierReleaseError",
    "cut_subject_frontier_release",
]
