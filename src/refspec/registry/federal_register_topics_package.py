"""Development package for one exact FederalRegister.gov topics response."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from refspec.registry.federal_register_topics_api import (
    AcquiredFederalRegisterTopics,
    FederalRegisterTopicsError,
)
from refspec.registry.federal_register_topics_reconciliation import (
    federal_register_topic_source_record_id,
)
from refspec.registry.source_controlled_resource import (
    SourceControlledResourceBundle,
    build_source_controlled_resource_bundle,
)

FEDERAL_REGISTER_TOPICS_RESOURCE_ID = "federal-register-api-topics"


def _verified_source_bytes(
    acquired: AcquiredFederalRegisterTopics,
) -> bytes:
    path = Path(acquired.path)
    if path.is_symlink() or not path.is_file():
        raise FederalRegisterTopicsError("Federal Register topics package source must be a regular file")
    payload = path.read_bytes()
    if len(payload) != acquired.byte_length:
        raise FederalRegisterTopicsError("Federal Register topics package source byte length changed")
    if acquired.snapshot.source_sha256 != acquired.source_sha256:
        raise FederalRegisterTopicsError("Federal Register topics parsed and acquired digests differ")
    import hashlib

    actual_digest = "sha256:" + hashlib.sha256(payload).hexdigest()
    if actual_digest != acquired.source_sha256:
        raise FederalRegisterTopicsError("Federal Register topics package source digest changed")
    return payload


def _observation(
    acquired: AcquiredFederalRegisterTopics,
    record: Any,
    *,
    observed_at: str,
) -> dict[str, Any]:
    return {
        "id": federal_register_topic_source_record_id(
            acquired.source_sha256,
            record,
        ),
        "sourceArtifact": acquired.source_url,
        "sourcePath": record.source_locator,
        "sourceOrdinal": record.source_ordinal,
        "labels": [
            {
                "value": record.name,
                "language": "en",
                "role": "preferred",
            }
        ],
        # FederalRegister.gov does not describe the mutable slug as a stable
        # publisher concept identifier.
        "identifiers": [],
        "eligibleUses": ["sourceAssignedEvidence"],
        "conceptIdentityClaimed": False,
        "collection": record.collection,
        "sourceRecordDigest": record.source_record_digest,
        "nativeRecord": record.native_payload(),
        "observedAt": observed_at,
    }


def build_federal_register_topics_source_package(
    acquired: AcquiredFederalRegisterTopics,
    *,
    observed_at: str,
) -> SourceControlledResourceBundle:
    """Package every source row without reconciling it to the 1995 thesaurus."""

    source_payload = _verified_source_bytes(acquired)
    observations = tuple(
        _observation(acquired, record, observed_at=observed_at) for record in acquired.snapshot.records
    )
    return build_source_controlled_resource_bundle(
        resource_id=FEDERAL_REGISTER_TOPICS_RESOURCE_ID,
        title="FederalRegister.gov Topics API source observations",
        resource_kind="sourceTermSnapshot",
        identity_status="captureLocalObservationsOnly",
        uses=("sourceAssignedEvidence",),
        captured_at=observed_at,
        # Reconciliation with the historical thesaurus remains unresolved.
        candidate_use_authorized=False,
        observations=observations,
        source_artifacts={acquired.source_url: source_payload},
    )


__all__ = [
    "FEDERAL_REGISTER_TOPICS_RESOURCE_ID",
    "build_federal_register_topics_source_package",
]
