"""Development package for one exact FederalRegister.gov topics response.

FederalRegister.gov topics rows have labels and mutable slugs, but no stable
publisher term identifiers.  This package therefore mints RefSpec-owned
UUIDv7 ``localRecordId`` values from a persisted registration event, while
observation ``id`` values remain capture-scoped.  Those local ids are first
registration ids for this sealed package; carrying them across later captures
requires an explicit predecessor reconciliation step that this module does not
perform.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from refspec.registry.federal_register_topics_api import (
    AcquiredFederalRegisterTopics,
    FederalRegisterTopicRecord,
    FederalRegisterTopicsError,
)
from refspec.registry.infrastructure.source_controlled_resource import (
    SourceControlledResourceBundle,
    build_source_controlled_resource_bundle,
)
from refspec.registry.infrastructure.source_identity import (
    SourceCaptureEvent,
    SourceRegistrationEvent,
)
from refspec.storage import canonical_json

FEDERAL_REGISTER_TOPICS_RESOURCE_ID = "federal-register-api-topics"
FEDERAL_REGISTER_TOPICS_CAPTURED_AT = "2026-07-30T12:00:00Z"
FEDERAL_REGISTER_TOPICS_REGISTRATION_ID = "019fb2e5-4e00-70c3-9d12-d96d08bc7e91"
FEDERAL_REGISTER_TOPICS_FETCH_ID = "019fb2e5-4e00-7e9a-a33d-46fe91635169"
FEDERAL_REGISTER_TOPICS_REGISTRATION_EVENT = SourceRegistrationEvent(
    registration_id=FEDERAL_REGISTER_TOPICS_REGISTRATION_ID,
    registered_at=FEDERAL_REGISTER_TOPICS_CAPTURED_AT,
)
FEDERAL_REGISTER_TOPICS_CAPTURE_EVENT = SourceCaptureEvent(
    fetch_id=FEDERAL_REGISTER_TOPICS_FETCH_ID,
    fetched_at=FEDERAL_REGISTER_TOPICS_CAPTURED_AT,
)


def _source_record_id(
    capture_sha256: str,
    record: FederalRegisterTopicRecord,
) -> str:
    prefix = "sha256:"
    digest = capture_sha256.removeprefix(prefix)
    if (
        not capture_sha256.startswith(prefix)
        or len(digest) != 64
        or any(character not in "0123456789abcdef" for character in digest)
    ):
        raise FederalRegisterTopicsError(
            "topics capture identity must be a lowercase sha256 digest"
        )
    return (
        "urn:ref:source-record:federal-register-topics:"
        f"{digest}:{record.collection}:{record.source_ordinal}"
    )


def _local_record_id(
    record: FederalRegisterTopicRecord,
    *,
    observation_id: str,
    registration_event: SourceRegistrationEvent,
) -> str:
    source_key = canonical_json(
        {
            "resourceId": FEDERAL_REGISTER_TOPICS_RESOURCE_ID,
            "collection": record.collection,
            "captureObservation": observation_id,
        }
    )
    return registration_event.derived_record_urn(
        purpose="federal-register-topics-local-record",
        source_key=source_key,
    )


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
    actual_digest = "sha256:" + hashlib.sha256(payload).hexdigest()
    if actual_digest != acquired.source_sha256:
        raise FederalRegisterTopicsError("Federal Register topics package source digest changed")
    return payload


def _observation(
    acquired: AcquiredFederalRegisterTopics,
    record: FederalRegisterTopicRecord,
    *,
    observed_at: str,
    local_record_id: str,
) -> dict[str, Any]:
    observation_id = _source_record_id(acquired.source_sha256, record)
    return {
        "id": observation_id,
        "localRecordId": local_record_id,
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
        "sourceFetchId": acquired.capture_event.fetch_id,
        "sourceObservedAt": acquired.capture_event.fetched_at,
    }


def build_federal_register_topics_source_package(
    acquired: AcquiredFederalRegisterTopics,
    *,
    observed_at: str | None = None,
    registration_event: SourceRegistrationEvent = FEDERAL_REGISTER_TOPICS_REGISTRATION_EVENT,
) -> SourceControlledResourceBundle:
    """Package every source row without claiming stable concept identity.

    Fetch identity comes only from ``acquired.capture_event``. The default
    registration event is allowed only when that capture event is the
    designated package pin.
    """

    capture_event = acquired.capture_event
    package_observed_at = (
        observed_at if observed_at is not None else capture_event.fetched_at
    )
    if registration_event.registered_at != package_observed_at:
        raise FederalRegisterTopicsError(
            "Federal Register topics registration event time must equal observed_at"
        )
    if capture_event.fetched_at != package_observed_at:
        raise FederalRegisterTopicsError(
            "Federal Register topics capture event time must equal observed_at"
        )
    if (
        registration_event == FEDERAL_REGISTER_TOPICS_REGISTRATION_EVENT
        and capture_event != FEDERAL_REGISTER_TOPICS_CAPTURE_EVENT
    ):
        raise FederalRegisterTopicsError(
            "default Federal Register topics registration requires the designated capture event"
        )

    source_payload = _verified_source_bytes(acquired)
    observations: list[dict[str, Any]] = []
    for record in acquired.snapshot.records:
        observation_id = _source_record_id(acquired.source_sha256, record)
        observations.append(
            _observation(
                acquired,
                record,
                observed_at=package_observed_at,
                local_record_id=_local_record_id(
                    record,
                    observation_id=observation_id,
                    registration_event=registration_event,
                ),
            )
        )
    return build_source_controlled_resource_bundle(
        resource_id=FEDERAL_REGISTER_TOPICS_RESOURCE_ID,
        title="FederalRegister.gov Topics API source observations",
        resource_kind="sourceTermSnapshot",
        identity_status="captureLocalObservationsOnly",
        uses=("sourceAssignedEvidence",),
        captured_at=package_observed_at,
        candidate_use_authorized=False,
        observations=observations,
        source_artifacts={acquired.source_url: source_payload},
        registration_event=registration_event.as_dict(),
    )


__all__ = [
    "FEDERAL_REGISTER_TOPICS_CAPTURED_AT",
    "FEDERAL_REGISTER_TOPICS_CAPTURE_EVENT",
    "FEDERAL_REGISTER_TOPICS_FETCH_ID",
    "FEDERAL_REGISTER_TOPICS_REGISTRATION_EVENT",
    "FEDERAL_REGISTER_TOPICS_REGISTRATION_ID",
    "FEDERAL_REGISTER_TOPICS_RESOURCE_ID",
    "build_federal_register_topics_source_package",
]
