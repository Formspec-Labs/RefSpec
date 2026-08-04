"""Path-backed relation bundles expose stable, fail-closed atlas input pins."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

import pytest

import refspec.atlas as atlas_api
from refspec.atlas.concept_release import PinnedSourceConceptRelease
from refspec.atlas.relation_assertion import (
    PinnedRelationAssertionBundle,
    RelationAssertionBundle,
    RelationAssertionError,
)
from refspec.atlas.relation_proof import register_trusted_relation_machine_proof_adapter
from refspec.registry.infrastructure.artifact_serialization import canonical_json_bytes, sha256_digest
from refspec.registry.infrastructure.semantic_foundation import (
    SUBJECT_EXACT_MATCH,
    EvidenceAssertion,
    MappingAssertion,
)
from refspec.registry.infrastructure.source_concept_release import build_source_concept_release_bundle
from refspec.registry.infrastructure.source_controlled_resource import build_source_controlled_resource_bundle
from refspec.registry.infrastructure.source_identity import derive_uuid7

ASSERTED_AT = "2026-08-04T16:00:00Z"
_TEST_PROOF_ADAPTER = "urn:ref:test:relation-proof-adapter:pinned-bundle:v1"


def _source_release(
    tmp_path: Path,
    name: str,
) -> tuple[PinnedSourceConceptRelease, str, str]:
    source_id = f"https://publisher.example/source/{name}.json"
    scheme_id = f"https://publisher.example/schemes/{name}"
    concept_id = f"https://publisher.example/concepts/{name}"
    payload = (f'{{"id":"{concept_id}","label":"{name.title()}"}}\n').encode()
    payload_digest = sha256_digest(payload)
    observation = {
        "id": f"urn:ref:test:source-observation:{name}",
        "sourceArtifact": source_id,
        "sourcePath": f"terms/{name}",
        "sourceOrdinal": 0,
        "labels": [{"value": name.title(), "language": "en", "role": "preferred"}],
        "identifiers": [
            {
                "value": concept_id,
                "kind": "publisherConceptIri",
                "authorityUri": scheme_id,
                "sourceUri": source_id,
                "sourcePath": f"terms/{name}.id",
                "observedAt": ASSERTED_AT,
                "sourceDigest": payload_digest,
            }
        ],
        "uses": ["mappingReference"],
        "conceptIdentityClaimed": False,
    }
    source = build_source_controlled_resource_bundle(
        resource_id=f"pinned-relation-{name}",
        title=f"{name.title()} relation source",
        resource_kind="sourceTermSnapshot",
        identity_status="publisherIdentifiersPreserved",
        uses=("mappingReference",),
        captured_at=ASSERTED_AT,
        observations=(observation,),
        source_artifacts={source_id: payload},
        source_scheme={
            "id": scheme_id,
            "code": name,
            "label": f"{name.title()} scheme",
            "sourceArtifact": source_id,
            "sourceFetchId": derive_uuid7(
                ASSERTED_AT,
                seed=f"pinned-relation-fetch:{name}".encode(),
            ),
            "sourceObservedAt": ASSERTED_AT,
        },
    )
    release = build_source_concept_release_bundle(
        source,
        semantic_ring="subject",
        selected_observation_ids=(observation["id"],),
        selection_policy={
            "id": f"urn:ref:test:pinned-relation-selection:{name}:v1",
            "type": "explicitObservationSet",
        },
        rights_metadata=(
            {
                "type": "RightsMetadata",
                "rightsStatus": "notStated",
                "sourceArtifact": source_id,
                "sourceDigest": payload_digest,
            },
        ),
    )
    root = release.write_to(tmp_path / f"source-release-{name}")
    pinned = PinnedSourceConceptRelease.open(
        root / "bundle-manifest.json",
        expected_manifest_digest=release.manifest_digest,
    )
    return pinned, release.release_id, concept_id


def _subject_facts(
    tmp_path: Path,
) -> tuple[
    PinnedSourceConceptRelease,
    PinnedSourceConceptRelease,
    EvidenceAssertion,
    MappingAssertion,
]:
    source, source_release, source_concept = _source_release(tmp_path, "source")
    target, target_release, target_concept = _source_release(tmp_path, "target")
    evidence = EvidenceAssertion(
        semantic_ring="subject",
        evidence_class="humanReviewed",
        basis="editorialReview",
        asserted_by="https://refspec.org/actors/reviewer-1",
        asserted_at=ASSERTED_AT,
        evidence=("urn:ref:test:evidence:pinned-relation:support",),
        review_decision="urn:ref:test:evidence:pinned-relation:decision",
    )
    mapping = MappingAssertion(
        semantic_ring="subject",
        source_concept=source_concept,
        target_concept=target_concept,
        source_release=source_release,
        target_release=target_release,
        relation=SUBJECT_EXACT_MATCH,
        evidence=(evidence.identifier,),
        asserted_at=ASSERTED_AT,
    )
    return source, target, evidence, mapping


def _persisted_human_bundle(
    tmp_path: Path,
) -> tuple[
    RelationAssertionBundle,
    Path,
    PinnedSourceConceptRelease,
    PinnedSourceConceptRelease,
]:
    source, target, evidence, mapping = _subject_facts(tmp_path)
    bundle = RelationAssertionBundle.create(
        semantic_ring="subject",
        release_sources=(source, target),
        evidence_assertions=(evidence,),
        mapping_assertions=(mapping,),
    )
    root = bundle.write_to(tmp_path / "relation-bundle")
    return bundle, root, source, target


def test_pinned_relation_bundle_exposes_the_exact_public_atlas_input_pin(tmp_path: Path) -> None:
    bundle, root, source, target = _persisted_human_bundle(tmp_path)

    pinned = PinnedRelationAssertionBundle.open(
        root,
        expected_manifest_digest=bundle.manifest_digest,
        release_sources=(target, source),
    )

    assert atlas_api.PinnedRelationAssertionBundle is PinnedRelationAssertionBundle
    assert pinned.manifest_path == (root / "bundle-manifest.json").resolve()
    assert pinned.verified_bundle().as_record() == bundle.as_record()
    assert pinned.pin() == {
        "role": "RelationAssertionBundle",
        "id": bundle.identifier,
        "semanticRing": "subject",
        "contentDigest": bundle.content_digest,
        "manifestDigest": bundle.manifest_digest,
    }
    assert str(tmp_path) not in repr(pinned.pin())


def test_pinned_relation_bundle_rejects_later_bundle_byte_changes(tmp_path: Path) -> None:
    bundle, root, source, target = _persisted_human_bundle(tmp_path)
    pinned = PinnedRelationAssertionBundle.open(
        root / "bundle-manifest.json",
        expected_manifest_digest=bundle.manifest_digest,
        release_sources=(source, target),
    )

    assertions = root / "relation-assertions.json"
    assertions.write_bytes(assertions.read_bytes() + b" ")

    with pytest.raises(RelationAssertionError, match="assertion artifact bytes differ"):
        pinned.pin()


def test_pinned_relation_bundle_rejects_later_release_changes(tmp_path: Path) -> None:
    bundle, root, source, target = _persisted_human_bundle(tmp_path)
    pinned = PinnedRelationAssertionBundle.open(
        root,
        expected_manifest_digest=bundle.manifest_digest,
        release_sources=(source, target),
    )

    source.manifest_path.write_bytes(source.manifest_path.read_bytes() + b" ")

    with pytest.raises(RelationAssertionError, match="manifest digest differs"):
        pinned.verified_bundle()


def _machine_proof_record(path: Path, mapping: MappingAssertion) -> dict[str, Any]:
    file_digest = sha256_digest(path.read_bytes())
    validations = [
        {
            "id": f"urn:ref:test:validation:pinned-relation:{suffix}",
            "contentDigest": sha256_digest(f"validation:{suffix}".encode()),
        }
        for suffix in ("a", "b")
    ]
    basis = {
        "type": "MachineEvidenceProof",
        "schemaVersion": "1.0",
        "proofAdapter": _TEST_PROOF_ADAPTER,
        "semanticRing": "subject",
        "evidenceClass": "machineQualified",
        "proofKind": "testIndependentValidations",
        "proofSource": {
            "type": "PinnedTestProof",
            "id": "urn:ref:test:proof-source:pinned-relation",
            "contentDigest": file_digest,
            "fileDigest": file_digest,
        },
        "candidate": {
            "id": "urn:ref:test:candidate:pinned-relation",
            "contentDigest": sha256_digest(b"pinned-relation-candidate"),
        },
        "validations": validations,
        "proofDetails": {"testPurpose": "pinned relation bundle reopening"},
        "sourceConcept": mapping.source_concept,
        "targetConcept": mapping.target_concept,
        "sourceRelease": mapping.source_release,
        "targetRelease": mapping.target_release,
        "relation": mapping.relation,
        "qualificationPolicy": "urn:ref:test:qualification-policy:pinned-relation:v1",
    }
    content_digest = sha256_digest(canonical_json_bytes(basis))
    return {
        **basis,
        "id": f"urn:ref:machine-evidence-proof:subject:{content_digest.removeprefix('sha256:')}",
        "contentDigest": content_digest,
    }


def test_pinned_relation_bundle_reopens_trusted_machine_proof_sources(tmp_path: Path) -> None:
    source, target, _, mapping = _subject_facts(tmp_path)
    proof_path = tmp_path / "trusted-relation-proof.bin"
    proof_path.write_bytes(b"trusted relation proof bytes\n")
    proof_record = _machine_proof_record(proof_path, mapping)

    @register_trusted_relation_machine_proof_adapter(_TEST_PROOF_ADAPTER)
    @dataclass(frozen=True, slots=True)
    class PinnedTestProof:
        path: Path
        file_digest: str
        record: Mapping[str, Any]

        def pin(self) -> Mapping[str, Any]:
            if sha256_digest(self.path.read_bytes()) != self.file_digest:
                raise ValueError("trusted test proof source digest differs")
            return self.record

    proof = PinnedTestProof(
        path=proof_path,
        file_digest=sha256_digest(proof_path.read_bytes()),
        record=proof_record,
    )
    validation_ids = tuple(row["id"] for row in proof_record["validations"])
    evidence = EvidenceAssertion(
        semantic_ring="subject",
        evidence_class="machineQualified",
        basis="statisticalInference",
        asserted_by="https://refspec.org/software/test-qualification-gate",
        asserted_at=ASSERTED_AT,
        evidence=(proof_record["id"],),
        candidate=proof_record["candidate"]["id"],
        machine_proof=proof_record["id"],
        source_concept=mapping.source_concept,
        target_concept=mapping.target_concept,
        source_release=mapping.source_release,
        target_release=mapping.target_release,
        relation=mapping.relation,
        validation_receipts=validation_ids,
    )
    machine_mapping = replace(mapping, evidence=(evidence.identifier,))
    bundle = RelationAssertionBundle.create(
        semantic_ring="subject",
        release_sources=(source, target),
        machine_proof_sources=(proof,),
        evidence_assertions=(evidence,),
        mapping_assertions=(machine_mapping,),
    )
    root = bundle.write_to(tmp_path / "machine-relation-bundle")
    pinned = PinnedRelationAssertionBundle.open(
        root,
        expected_manifest_digest=bundle.manifest_digest,
        release_sources=(source, target),
        machine_proof_sources=(proof,),
    )

    assert pinned.pin()["id"] == bundle.identifier

    proof_path.write_bytes(proof_path.read_bytes() + b"changed")

    with pytest.raises(RelationAssertionError, match="trusted test proof source digest differs"):
        pinned.verified_bundle()
