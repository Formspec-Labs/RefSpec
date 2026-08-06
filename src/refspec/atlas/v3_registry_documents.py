"""Load exact government publication identities into Atlas 3.

The publisher-specific registry parsers remain the source-shape authority.
This adapter promotes globally reusable document identities and their
authority-scoped identifiers; document-topic and document-bill observations
remain in the pinned native source record until their target releases exist.
"""

from __future__ import annotations

import json
import re
import tempfile
from pathlib import Path
from urllib.parse import urlsplit

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
from refspec.registry import cbo_topic_codes as cbo
from refspec.registry import gao_topics as gao
from refspec.registry.infrastructure.source_identity import derive_uuid7

ROOT = Path(__file__).resolve().parents[3]
CBO_CAPTURE = (
    ROOT
    / "tests/fixtures/cbo_topic_codes/"
    "cbo-119congress-cost-estimates-2026-08-04.xml"
)
GAO_CAPTURE = (
    ROOT
    / "tests/fixtures/gao_topics/"
    "gao-product-gao-26-108505-2026-08-04.html"
)

_CBO_PUBLICATION_ID = re.compile(r"[1-9][0-9]*")


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


def load_cbo_publication_release(
    repo_root: Path = ROOT,
) -> RegistryRelease:
    """Load all publication identities in the pinned 119th-Congress feed."""

    root = Path(repo_root)
    capture = root / CBO_CAPTURE.relative_to(ROOT)
    pin = cbo.CBO_119TH_CONGRESS_REAL_CAPTURE_2026_08_04
    source = _input_pin(
        capture,
        logical_path=capture.relative_to(root).as_posix(),
        source_iri=pin.source_url,
        sha256=pin.expected_sha256,
        byte_length=pin.expected_byte_length,
    )
    scheme_iri = "urn:ref:atlas-resource-scheme:cbo-publication-identifiers"
    with tempfile.TemporaryDirectory(prefix="refspec-atlas-v3-cbo-") as directory:
        acquired = cbo.acquire_cbo_per_congress_feed(
            pin,
            Path(directory),
            source_path=capture,
        )
        parsed = cbo.parse_cbo_per_congress_feed(acquired)

    resources: list[RegistryResource] = []
    seen_publications: set[str] = set()
    for record in parsed.records:
        publication_id = urlsplit(record.link).path.rsplit("/", 1)[-1]
        if _CBO_PUBLICATION_ID.fullmatch(publication_id) is None:
            raise ValueError(f"CBO publication URL has no numeric identity: {record.link}")
        if record.link in seen_publications:
            raise ValueError(f"CBO feed repeats publication identity {record.link}")
        seen_publications.add(record.link)
        source_path = f"response.item[{record.item_ordinal}]"
        native_payload = deep_freeze_json(
            {
                "billNumber": record.bill_number,
                "canonicalPublicationUrl": record.link,
                "date": record.date,
                "description": record.description,
                "feedItemKey": record.key,
                "publicationId": publication_id,
                "sourceArtifact": parsed.source_url,
                "sourcePath": source_path,
                "title": record.title,
            }
        )
        resources.append(
            RegistryResource(
                iri=record.link,
                labels=(
                    RegistryLabel(
                        value=record.title,
                        role="preferred",
                        source_path=f"{source_path}.Title",
                    ),
                ),
                native_payload=native_payload,
                source_locator=f"{parsed.source_url}#item={record.key}",
                source_digest=parsed.source_sha256,
                identifiers=(
                    RegistryIdentifier(
                        value=publication_id,
                        scheme_iri=scheme_iri,
                        source_path=f"{source_path}.Link",
                    ),
                ),
            )
        )

    return _release(
        key="cbo-119th-congress-publications",
        resource_id="cbo-publication-identifiers",
        source_module="refspec.registry.cbo_topic_codes",
        source_token="cbo-publications-119",
        issued=parsed.retrieved_at,
        scope="completeCapture",
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
            "congress": 119,
            "sourceGaps": list(parsed.gaps),
        },
    )


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


def load_registry_document_releases(
    repo_root: Path = ROOT,
) -> tuple[RegistryRelease, ...]:
    """Load every supported exact document-identifier release."""

    return (
        load_cbo_publication_release(repo_root),
        load_gao_report_release(repo_root),
        load_gao_topic_release(repo_root),
    )


__all__ = [
    "CBO_CAPTURE",
    "GAO_CAPTURE",
    "load_cbo_publication_release",
    "load_gao_report_release",
    "load_gao_topic_release",
    "load_registry_document_releases",
]
