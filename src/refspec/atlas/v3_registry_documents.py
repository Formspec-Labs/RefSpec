"""Load the witnessed GAO product identity and its observed topics into Atlas 3.

The publisher-specific registry parsers remain the source-shape authority.
This adapter promotes the one document identity the subject ring needs as a
witness -- the GAO report that anchors the observed-topics unit's cross-ring
relation -- and the topics observed on it. Document *populations* are not
Atlas units (REF-031); SpicyRegs acquires those.
"""

from __future__ import annotations

import json
import tempfile
from collections.abc import Collection
from pathlib import Path

from refspec.atlas.v3_registry_selection import (
    normalize_only_keys,
    select_declared_group,
    wants_group,
)
from refspec.atlas.v3_source_data import (
    RegistryCrossRingRelation,
    RegistryIdentifier,
    RegistryInputPin,
    RegistryLabel,
    RegistryRelease,
    RegistryResource,
    canonical_digest,
)
from refspec.immutable import deep_freeze_json
from refspec.registry import gao_topics as gao
from refspec.registry.infrastructure.source_identity import derive_uuid7

ROOT = Path(__file__).resolve().parents[3]
GAO_CAPTURE = (
    ROOT
    / "tests/fixtures/gao_topics/"
    "gao-product-gao-26-108505-2026-08-04.html"
)


def _input_pin(
    path: Path,
    *,
    logical_path: str,
    source_iri: str,
    sha256: str,
    byte_length: int,
) -> RegistryInputPin:
    pin = RegistryInputPin(
        path=path,
        logical_path=logical_path,
        sha256=sha256,
        byte_length=byte_length,
        source_iri=source_iri,
    )
    pin.verify()
    return pin


def _release(
    *,
    key: str,
    resource_id: str,
    source_module: str,
    source_token: str,
    issued: str,
    scope: str,
    source_digest: str,
    input_pin: RegistryInputPin,
    resources: tuple[RegistryResource, ...],
    metadata: dict[str, object],
    profile: str = "identifierScheme",
    ring: str = "entity",
    cross_ring_relations: tuple[RegistryCrossRingRelation, ...] = (),
) -> RegistryRelease:
    digest_token = source_digest.removeprefix("sha256:")
    return RegistryRelease(
        key=key,
        resource_id=resource_id,
        source_module=source_module,
        profile=profile,
        ring=ring,
        scope=scope,  # type: ignore[arg-type]
        issued=issued[:10],
        source_release_iri=f"urn:ref:registry-release:{source_token}:{digest_token}",
        source_release_digest=source_digest,
        atlas_release_iri=f"urn:ref:atlas-release:v3:{source_token}:{digest_token}",
        scheme_iri=f"urn:ref:atlas-resource-scheme:{resource_id}",
        inputs=(input_pin,),
        resources=resources,
        cross_ring_relations=cross_ring_relations,
        metadata=deep_freeze_json(metadata),
    )


def _mint_source_identity(
    *,
    source_token: str,
    recorded_at: str,
    source_artifact: str,
    source_path: str,
    source_value: str,
) -> str:
    seed = json.dumps(
        {
            "sourceArtifact": source_artifact,
            "sourcePath": source_path,
            "sourceValue": source_value,
        },
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    uuid = derive_uuid7(recorded_at, seed=seed)
    return f"urn:ref:source-concept:v2:{source_token}:{uuid}"


def load_gao_report_release(repo_root: Path = ROOT) -> RegistryRelease:
    """Load the globally identified GAO report in the pinned product page."""

    root = Path(repo_root)
    capture = root / GAO_CAPTURE.relative_to(ROOT)
    pin = gao.GAO_PRODUCT_GAO_26_108505_2026_08_04
    source = _input_pin(
        capture,
        logical_path=capture.relative_to(root).as_posix(),
        source_iri=pin.source_url,
        sha256=pin.expected_sha256,
        byte_length=pin.expected_byte_length,
    )
    scheme_iri = "urn:ref:atlas-resource-scheme:gao-report-identifiers"
    with tempfile.TemporaryDirectory(prefix="refspec-atlas-v3-gao-") as directory:
        acquired = gao.acquire_gao_product_page(
            pin,
            Path(directory),
            source_path=capture,
        )
        parsed = gao.parse_gao_product_topics_page(acquired)

    source_path = "product"
    resource = RegistryResource(
        iri=parsed.canonical_url,
        labels=(
            RegistryLabel(
                value=parsed.product_title,
                role="preferred",
                source_path="product.h1",
            ),
        ),
        native_payload=deep_freeze_json(
            {
                "canonicalUrl": parsed.canonical_url,
                "publicationDate": parsed.publication_date,
                "productReportNumber": parsed.product_report_number,
                "productTitle": parsed.product_title,
                "sourceArtifact": parsed.source_url,
                "sourcePath": source_path,
                "topicAssignments": [
                    {
                        "label": assignment.label,
                        "recordIri": assignment.record_iri,
                        "sourceOrdinal": assignment.source_ordinal,
                        "topicPath": assignment.topic_path,
                    }
                    for assignment in parsed.assignments
                ],
            }
        ),
        source_locator=parsed.source_url,
        source_digest=parsed.source_sha256,
        identifiers=(
            RegistryIdentifier(
                value=parsed.product_report_number,
                scheme_iri=scheme_iri,
                source_path="product.productId",
            ),
        ),
    )
    cross_ring_relations = tuple(
        RegistryCrossRingRelation(
            subject=resource.iri,
            predicate="https://refspec.org/ns/atlas/v3#hasIndexedSubject",
            object=_mint_source_identity(
                source_token="gao-topics",
                recorded_at=parsed.retrieved_at,
                source_artifact=parsed.source_url,
                source_path=(
                    f"topics.viewsRow[{assignment.source_ordinal}]"
                    ".viewsFieldFieldTopic"
                ),
                source_value=assignment.topic_path,
            ),
            source_ring="entity",
            target_ring="subject",
            source_payload=deep_freeze_json(
                {
                    "assignmentRecordIri": assignment.record_iri,
                    "productReportNumber": parsed.product_report_number,
                    "sourceArtifact": parsed.source_url,
                    "sourceOrdinal": assignment.source_ordinal,
                    "topicLabel": assignment.label,
                    "topicPath": assignment.topic_path,
                }
            ),
        )
        for assignment in parsed.assignments
    )
    return _release(
        key="gao-report-gao-26-108505",
        resource_id="gao-report-identifiers",
        source_module="refspec.registry.gao_topics",
        source_token="gao-reports",
        issued=parsed.retrieved_at,
        scope="captureSubset",
        source_digest=canonical_digest(
            {
                "source": parsed.source_sha256,
                "members": [resource.iri],
            }
        ),
        input_pin=source,
        resources=(resource,),
        metadata={
            "captureMemberCount": 1,
            "observedTopicAssignmentCount": len(parsed.assignments),
        },
        cross_ring_relations=cross_ring_relations,
    )


def load_gao_topic_release(repo_root: Path = ROOT) -> RegistryRelease:
    """Load the bounded GAO topic set observed on the pinned product page."""

    root = Path(repo_root)
    capture = root / GAO_CAPTURE.relative_to(ROOT)
    pin = gao.GAO_PRODUCT_GAO_26_108505_2026_08_04
    source = _input_pin(
        capture,
        logical_path=capture.relative_to(root).as_posix(),
        source_iri=pin.source_url,
        sha256=pin.expected_sha256,
        byte_length=pin.expected_byte_length,
    )
    with tempfile.TemporaryDirectory(prefix="refspec-atlas-v3-gao-topic-") as directory:
        acquired = gao.acquire_gao_product_page(
            pin,
            Path(directory),
            source_path=capture,
        )
        parsed = gao.parse_gao_product_topics_page(acquired)

    resources: list[RegistryResource] = []
    for assignment in parsed.assignments:
        source_path = f"topics.viewsRow[{assignment.source_ordinal}].viewsFieldFieldTopic"
        resources.append(
            RegistryResource(
                iri=_mint_source_identity(
                    source_token="gao-topics",
                    recorded_at=parsed.retrieved_at,
                    source_artifact=parsed.source_url,
                    source_path=source_path,
                    source_value=assignment.topic_path,
                ),
                labels=(
                    RegistryLabel(
                        value=assignment.label,
                        role="preferred",
                        source_path=source_path,
                    ),
                ),
                native_payload=deep_freeze_json(
                    {
                        "conceptIdentityClaimedByPublisher": False,
                        "observedOnProduct": parsed.product_report_number,
                        "sourceArtifact": parsed.source_url,
                        "sourcePath": source_path,
                        "topicPath": assignment.topic_path,
                    }
                ),
                source_locator=f"{parsed.source_url}#topic={assignment.source_ordinal}",
                source_digest=parsed.source_sha256,
            )
        )

    return _release(
        key="gao-topics-observed-on-gao-26-108505",
        resource_id="gao-topics",
        source_module="refspec.registry.gao_topics",
        source_token="gao-topics",
        issued=parsed.retrieved_at,
        scope="captureSubset",
        source_digest=canonical_digest(
            {
                "source": parsed.source_sha256,
                "members": [resource.iri for resource in resources],
            }
        ),
        input_pin=source,
        resources=tuple(resources),
        metadata={
            "captureMemberCount": len(resources),
            "identityPolicy": "refspecSourceScopedUuid7V2",
            "publisherConceptIdentityClaimed": False,
        },
        profile="conceptScheme",
        ring="subject",
    )


REGISTRY_DOCUMENT_RELEASE_KEYS = frozenset(
    {
        "gao-report-gao-26-108505",
        "gao-topics-observed-on-gao-26-108505",
    }
)


def load_registry_document_releases(
    repo_root: Path = ROOT,
    *,
    only_keys: Collection[str] | None = None,
) -> tuple[RegistryRelease, ...]:
    """Load selected supported exact document-identifier releases."""

    requested = normalize_only_keys(
        only_keys,
        allowed_keys=REGISTRY_DOCUMENT_RELEASE_KEYS,
        loader_name="load_registry_document_releases",
    )
    loaders = (
        ("gao-report-gao-26-108505", load_gao_report_release),
        ("gao-topics-observed-on-gao-26-108505", load_gao_topic_release),
    )
    releases: list[RegistryRelease] = []
    for key, loader in loaders:
        group_keys = frozenset({key})
        if not wants_group(requested, group_keys):
            continue
        releases.extend(
            select_declared_group(
                (loader(repo_root),),
                declared_keys=group_keys,
                requested_keys=requested,
                loader_name=loader.__name__,
            )
        )
    return tuple(releases)


__all__ = [
    "GAO_CAPTURE",
    "REGISTRY_DOCUMENT_RELEASE_KEYS",
    "load_gao_report_release",
    "load_gao_topic_release",
    "load_registry_document_releases",
]
