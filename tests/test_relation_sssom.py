"""Lossless SSSOM distribution tests for shared relation assertions."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from dataclasses import FrozenInstanceError
from pathlib import Path
from typing import Any

import pytest

from refspec.atlas.machine_evidence import build_machine_evidence_from_crosswalk_proof
from refspec.atlas.relation_assertion import (
    PinnedSourceConceptRelationRelease,
    RelationAssertionBundle,
)
from refspec.atlas.relation_sssom import (
    EVIDENCE_PATH,
    MANIFEST_PATH,
    MAPPINGS_PATH,
    RelationSssomDistribution,
    RelationSssomError,
    relation_sssom_text,
)
from refspec.registry.infrastructure.artifact_serialization import (
    canonical_json_bytes,
    plain_json,
    sha256_digest,
)
from refspec.registry.infrastructure.semantic_foundation import (
    ENTITY_RELATED,
    LEGAL_CITES,
    SUBJECT_CLOSE_MATCH,
    SUBJECT_EXACT_MATCH,
    SUBJECT_RELATED_MATCH,
    VALUE_EXACT_CROSSWALK,
    EvidenceAssertion,
    MappingAssertion,
)
from refspec.registry.infrastructure.source_concept_release import build_source_concept_release_bundle
from refspec.registry.infrastructure.source_controlled_resource import build_source_controlled_resource_bundle
from refspec.registry.infrastructure.source_identity import derive_uuid7

ASSERTED_AT = "2026-08-04T16:00:00Z"

_PROOF_FIXTURE_SPEC = importlib.util.spec_from_file_location(
    "refspec_test_relation_machine_proof_fixture",
    Path(__file__).with_name("test_relation_assertion_bundle.py"),
)
assert _PROOF_FIXTURE_SPEC is not None and _PROOF_FIXTURE_SPEC.loader is not None
_PROOF_FIXTURE_MODULE = importlib.util.module_from_spec(_PROOF_FIXTURE_SPEC)
sys.modules[_PROOF_FIXTURE_SPEC.name] = _PROOF_FIXTURE_MODULE
_PROOF_FIXTURE_SPEC.loader.exec_module(_PROOF_FIXTURE_MODULE)
build_crosswalk_machine_proofs = _PROOF_FIXTURE_MODULE._crosswalk_machine_proofs


def _source_release(
    tmp_path: Path,
    name: str,
    *,
    ring: str = "subject",
) -> tuple[PinnedSourceConceptRelationRelease, str, str]:
    source_id = f"https://publisher.example/source/{name}.json"
    source_payload = (f'{{"terms":["{name}"]}}\n').encode()
    observation = {
        "id": f"urn:ref:test:source-observation:{ring}:{name}",
        "sourceArtifact": source_id,
        "sourcePath": f"terms/{name}",
        "sourceOrdinal": 0,
        "labels": [{"value": name.title(), "language": "en", "role": "preferred"}],
        "identifiers": [],
        "uses": ["mappingReference"],
        "conceptIdentityClaimed": False,
        "localRecordId": "urn:uuid:" + derive_uuid7(ASSERTED_AT, seed=f"relation-sssom:{ring}:{name}".encode()),
    }
    source = build_source_controlled_resource_bundle(
        resource_id=f"relation-sssom-{ring}-{name}",
        title=f"{name.title()} relation source",
        resource_kind="sourceTermSnapshot",
        identity_status="captureLocalObservationsOnly",
        uses=("mappingReference",),
        captured_at=ASSERTED_AT,
        observations=(observation,),
        source_artifacts={source_id: source_payload},
        source_scheme={
            "id": f"https://publisher.example/schemes/{name}",
            "code": name,
            "label": f"{name.title()} scheme",
            "sourceArtifact": source_id,
            "sourceFetchId": derive_uuid7(
                ASSERTED_AT,
                seed=f"relation-sssom-fetch:{ring}:{name}".encode(),
            ),
            "sourceObservedAt": ASSERTED_AT,
        },
    )
    release = build_source_concept_release_bundle(
        source,
        semantic_ring=ring,  # type: ignore[arg-type]
        selected_observation_ids=(observation["id"],),
        selection_policy={
            "id": f"urn:ref:test:relation-sssom-selection:{ring}:{name}:v1",
            "type": "explicitObservationSet",
        },
        rights_metadata=(
            {
                "type": "RightsMetadata",
                "rightsStatus": "notStated",
                "sourceArtifact": source_id,
                "sourceDigest": "sha256:" + hashlib.sha256(source_payload).hexdigest(),
            },
        ),
    )
    root = release.write_to(tmp_path / f"source-release-{ring}-{name}")
    return (
        PinnedSourceConceptRelationRelease.open(
            root / "bundle-manifest.json",
            expected_manifest_digest=release.manifest_digest,
        ),
        release.release_id,
        str(release.concepts[0]["id"]),
    )


def _evidence() -> tuple[EvidenceAssertion, EvidenceAssertion]:
    publisher = EvidenceAssertion(
        semantic_ring="subject",
        evidence_class="publisherAsserted",
        basis="publisherCrosswalk",
        asserted_by="https://publisher.example/",
        asserted_at=ASSERTED_AT,
        evidence=("urn:ref:test:evidence:publisher-row",),
        source_artifact="https://publisher.example/source/crosswalk.json",
        source_digest="sha256:" + "a" * 64,
    )
    human = EvidenceAssertion(
        semantic_ring="subject",
        evidence_class="humanReviewed",
        basis="editorialReview",
        asserted_by="https://refspec.org/actors/reviewer-1",
        asserted_at=ASSERTED_AT,
        evidence=("urn:ref:test:evidence:review-workpaper",),
        review_decision="urn:ref:test:review-decision:accepted",
    )
    return publisher, human


def _subject_bundle(tmp_path: Path) -> RelationAssertionBundle:
    source, source_release, source_concept = _source_release(tmp_path, "source")
    target, target_release, target_concept = _source_release(tmp_path, "target")
    publisher, human = _evidence()
    proof_scope = MappingAssertion(
        semantic_ring="subject",
        source_concept=source_concept,
        target_concept=target_concept,
        source_release=source_release,
        target_release=target_release,
        relation=SUBJECT_EXACT_MATCH,
        evidence=(human.identifier,),
        asserted_at=ASSERTED_AT,
    )
    qualified_proof, _ = build_crosswalk_machine_proofs(tmp_path, proof_scope)
    machine = build_machine_evidence_from_crosswalk_proof(
        qualified_proof,
        asserted_by="https://refspec.org/software/qualifier-v2",
        asserted_at=ASSERTED_AT,
    )
    mappings = (
        MappingAssertion(
            semantic_ring="subject",
            source_concept=source_concept,
            target_concept=target_concept,
            source_release=source_release,
            target_release=target_release,
            relation=SUBJECT_EXACT_MATCH,
            evidence=(machine.identifier,),
            asserted_at=ASSERTED_AT,
        ),
        MappingAssertion(
            semantic_ring="subject",
            source_concept=source_concept,
            target_concept=target_concept,
            source_release=source_release,
            target_release=target_release,
            relation=SUBJECT_CLOSE_MATCH,
            evidence=(publisher.identifier,),
            asserted_at=ASSERTED_AT,
        ),
        MappingAssertion(
            semantic_ring="subject",
            source_concept=source_concept,
            target_concept=target_concept,
            source_release=source_release,
            target_release=target_release,
            relation=SUBJECT_RELATED_MATCH,
            evidence=(human.identifier,),
            asserted_at=ASSERTED_AT,
        ),
    )
    return RelationAssertionBundle.create(
        semantic_ring="subject",
        release_sources=(target, source),
        machine_proof_sources=(qualified_proof,),
        evidence_assertions=(human, machine, publisher),
        mapping_assertions=tuple(reversed(mappings)),
    )


def _split_sssom(text: str) -> tuple[list[str], list[dict[str, str]]]:
    lines = text.splitlines()
    header = [line for line in lines if line.startswith("#")]
    body = [line for line in lines if not line.startswith("#")]
    columns = body[0].split("\t")
    return header, [dict(zip(columns, line.split("\t"), strict=True)) for line in body[1:]]


def _curie_map(header: list[str]) -> dict[str, str]:
    start = header.index("# curie_map:") + 1
    result: dict[str, str] = {}
    for line in header[start:]:
        if not line.startswith("#   "):
            break
        prefix, _, expansion = line.removeprefix("#   ").partition(": ")
        result[prefix] = json.loads(expansion)
    return result


def _expand(curie: str, prefixes: dict[str, str]) -> str:
    prefix, _, local = curie.partition(":")
    return prefixes[prefix] + local


def _jsonl(payload: bytes) -> list[dict[str, Any]]:
    return [json.loads(line) for line in payload.decode("utf-8").splitlines()]


def test_distribution_is_deterministic_and_sssom_rows_keep_assertion_identity(tmp_path: Path) -> None:
    bundle = _subject_bundle(tmp_path)
    first = RelationSssomDistribution.create(bundle)
    second = RelationSssomDistribution.create(bundle)

    assert first.artifact_bytes() == second.artifact_bytes()
    assert first.distribution_id.startswith("urn:ref:relation-sssom-distribution:subject:")
    assert first.content_digest.startswith("sha256:")
    assert set(first.artifact_bytes()) == {MAPPINGS_PATH, EVIDENCE_PATH, MANIFEST_PATH}

    header, rows = _split_sssom(first.artifact_bytes()[MAPPINGS_PATH].decode())
    prefixes = _curie_map(header)
    by_assertion = {row["see_also"]: row for row in rows}
    by_relation = {mapping.relation: by_assertion[mapping.identifier] for mapping in bundle.mapping_assertions}
    assert set(by_assertion) == {row.identifier for row in bundle.mapping_assertions}
    assert {row["mapping_source"] for row in rows} == {bundle.identifier}
    machine_evidence = next(row for row in bundle.evidence_assertions if row.evidence_class == "machineQualified")
    assert machine_evidence.candidate not in by_assertion
    assert _expand(by_relation[SUBJECT_EXACT_MATCH]["mapping_justification"], prefixes).endswith("MappingReview")
    assert _expand(by_relation[SUBJECT_RELATED_MATCH]["mapping_justification"], prefixes).endswith("MappingReview")
    assert _expand(by_relation[SUBJECT_CLOSE_MATCH]["mapping_justification"], prefixes).endswith("UnspecifiedMatching")


def test_sidecar_is_one_to_one_lossless_and_never_fakes_machine_facts(tmp_path: Path) -> None:
    bundle = _subject_bundle(tmp_path)
    payload = RelationSssomDistribution.create(bundle).artifact_bytes()[EVIDENCE_PATH]
    rows = _jsonl(payload)
    by_assertion = {row["mappingAssertionId"]: row for row in rows}

    assert list(by_assertion) == sorted(row.identifier for row in bundle.mapping_assertions)
    assert len(rows) == len(bundle.mapping_assertions)
    machine_assertion = next(row for row in bundle.evidence_assertions if row.evidence_class == "machineQualified")
    machine_mapping = next(row for row in bundle.mapping_assertions if machine_assertion.identifier in row.evidence)
    machine = by_assertion[machine_mapping.identifier]
    machine_metadata = machine["machineQualificationEvidence"]
    proof_pin = plain_json(bundle.machine_proof_pins[0])
    assert proof_pin["proofKind"] == "crosswalkV2IndependentValidations"
    assert proof_pin["qualificationPolicy"].endswith("two-independent-machines-relation-agreement-v2")
    assert machine_metadata == [
        {
            "evidenceAssertionId": machine_assertion.identifier,
            "candidate": machine_assertion.candidate,
            "machineProof": proof_pin,
            "validationReceipts": list(machine_assertion.validation_receipts),
            "useCeiling": "searchOnly",
        }
    ]
    assert "proofStatus" not in machine_metadata[0]
    assert "qualificationPolicy" not in machine_metadata[0]
    assert {
        item["machineProof"]["id"]
        for row in rows
        for key in ("machineQualificationEvidence", "machineReviewEvidence")
        for item in row.get(key, [])
    } == {pin["id"] for pin in bundle.machine_proof_pins}
    for mapping in bundle.mapping_assertions:
        if mapping.identifier != machine_mapping.identifier:
            assert "machineQualificationEvidence" not in by_assertion[mapping.identifier]

    mappings = {row.identifier: row for row in bundle.mapping_assertions}
    for identifier, row in by_assertion.items():
        mapping = mappings[identifier]
        assert row["assertionDigest"] == sha256_digest(canonical_json_bytes(mapping.as_record()))
        assert row["relation"] == mapping.relation
        assert row["directEvidence"] == [
            next(item.as_record() for item in bundle.evidence_assertions if item.identifier == evidence_id)
            for evidence_id in mapping.evidence
        ]
        assert row["releasePins"] == [
            plain_json(pin)
            for pin in bundle.release_pins
            if pin["releaseId"] in {mapping.source_release, mapping.target_release}
        ]


def test_sidecar_preserves_operator_adoption_closure(tmp_path: Path) -> None:
    source, source_release, source_concept = _source_release(tmp_path, "operator-source")
    target, target_release, target_concept = _source_release(tmp_path, "operator-target")
    review_basis = EvidenceAssertion(
        semantic_ring="subject",
        evidence_class="humanReviewed",
        basis="editorialReview",
        asserted_by="https://refspec.org/actors/reviewer-1",
        asserted_at=ASSERTED_AT,
        evidence=("urn:ref:test:evidence:sssom-review-workpaper",),
        review_decision="urn:ref:test:decision:sssom-proof-scope",
    )
    proof_scope = MappingAssertion(
        semantic_ring="subject",
        source_concept=source_concept,
        target_concept=target_concept,
        source_release=source_release,
        target_release=target_release,
        relation=SUBJECT_EXACT_MATCH,
        evidence=(review_basis.identifier,),
        asserted_at=ASSERTED_AT,
    )
    _, reviewed_proof = build_crosswalk_machine_proofs(tmp_path, proof_scope)
    reviewed = build_machine_evidence_from_crosswalk_proof(
        reviewed_proof,
        asserted_by="https://refspec.org/software/qualification-runner-v2",
        asserted_at=ASSERTED_AT,
    )
    adopted = EvidenceAssertion(
        semantic_ring="subject",
        evidence_class="operatorAdopted",
        basis="operatorDirection",
        asserted_by="https://refspec.org/actors/operator-1",
        asserted_at=ASSERTED_AT,
        evidence=("urn:ref:test:evidence:sssom-operator-decision",),
        adopted_evidence=reviewed.identifier,
    )
    mapping = MappingAssertion(
        semantic_ring="subject",
        source_concept=source_concept,
        target_concept=target_concept,
        source_release=source_release,
        target_release=target_release,
        relation=SUBJECT_EXACT_MATCH,
        evidence=(adopted.identifier,),
        asserted_at=ASSERTED_AT,
    )
    bundle = RelationAssertionBundle.create(
        semantic_ring="subject",
        release_sources=(source, target),
        machine_proof_sources=(reviewed_proof,),
        evidence_assertions=(reviewed, adopted),
        mapping_assertions=(mapping,),
    )

    row = _jsonl(RelationSssomDistribution.create(bundle).artifact_bytes()[EVIDENCE_PATH])[0]

    assert [item["id"] for item in row["directEvidence"]] == [adopted.identifier]
    assert [item["id"] for item in row["evidenceClosure"]] == sorted((reviewed.identifier, adopted.identifier))
    assert row["machineReviewEvidence"] == [
        {
            "evidenceAssertionId": reviewed.identifier,
            "candidate": reviewed.candidate,
            "machineProof": plain_json(reviewed_proof.pin()),
            "validationReceipts": list(reviewed.validation_receipts),
            "useCeiling": "notApplicable",
        }
    ]
    assert "qualificationPolicy" not in row["machineReviewEvidence"][0]["machineProof"]


def test_ring_specific_context_survives_the_sidecar(tmp_path: Path) -> None:
    source, source_release, source_concept = _source_release(tmp_path, "value-source", ring="value")
    target, target_release, target_concept = _source_release(tmp_path, "value-target", ring="value")
    evidence = EvidenceAssertion(
        semantic_ring="value",
        evidence_class="publisherAsserted",
        basis="publisherCrosswalk",
        asserted_by="https://publisher.example/",
        asserted_at=ASSERTED_AT,
        evidence=("urn:ref:test:evidence:value-row",),
        source_artifact="https://publisher.example/source/value-crosswalk.json",
        source_digest="sha256:" + "b" * 64,
    )
    context = {
        "sourceEdition": "2025",
        "targetEdition": "2026",
        "effectiveFrom": "2026-01-01",
        "effectiveThrough": "2026-12-31",
    }
    mapping = MappingAssertion(
        semantic_ring="value",
        source_concept=source_concept,
        target_concept=target_concept,
        source_release=source_release,
        target_release=target_release,
        relation=VALUE_EXACT_CROSSWALK,
        evidence=(evidence.identifier,),
        asserted_at=ASSERTED_AT,
        context=context,
    )
    bundle = RelationAssertionBundle.create(
        semantic_ring="value",
        release_sources=(source, target),
        evidence_assertions=(evidence,),
        mapping_assertions=(mapping,),
    )

    row = _jsonl(RelationSssomDistribution.create(bundle).artifact_bytes()[EVIDENCE_PATH])[0]
    assert row["relation"] == VALUE_EXACT_CROSSWALK
    assert row["context"] == context


@pytest.mark.parametrize(
    ("ring", "relation", "context"),
    [
        ("entity", ENTITY_RELATED, None),
        ("legalIdentity", LEGAL_CITES, {"effectiveAt": "2026-08-04"}),
    ],
)
def test_distribution_refuses_rings_without_an_sssom_profile(
    tmp_path: Path,
    ring: str,
    relation: str,
    context: dict[str, str] | None,
) -> None:
    source, source_release, source_concept = _source_release(tmp_path, f"{ring}-source", ring=ring)
    target, target_release, target_concept = _source_release(tmp_path, f"{ring}-target", ring=ring)
    evidence = EvidenceAssertion(
        semantic_ring=ring,  # type: ignore[arg-type]
        evidence_class="humanReviewed",
        basis="editorialReview",
        asserted_by="https://refspec.org/actors/reviewer-1",
        asserted_at=ASSERTED_AT,
        evidence=(f"urn:ref:test:evidence:{ring}-review",),
        review_decision=f"urn:ref:test:review-decision:{ring}-accepted",
    )
    mapping = MappingAssertion(
        semantic_ring=ring,  # type: ignore[arg-type]
        source_concept=source_concept,
        target_concept=target_concept,
        source_release=source_release,
        target_release=target_release,
        relation=relation,
        evidence=(evidence.identifier,),
        asserted_at=ASSERTED_AT,
        context=context,
    )
    bundle = RelationAssertionBundle.create(
        semantic_ring=ring,  # type: ignore[arg-type]
        release_sources=(source, target),
        evidence_assertions=(evidence,),
        mapping_assertions=(mapping,),
    )

    with pytest.raises(RelationSssomError, match="supports only subject and value rings"):
        RelationSssomDistribution.create(bundle)
    with pytest.raises(RelationSssomError, match="supports only subject and value rings"):
        relation_sssom_text(bundle)
    supported = RelationSssomDistribution.create(_subject_bundle(tmp_path))
    supported_root = supported.write_to(tmp_path / f"supported-distribution-for-{ring}")
    with pytest.raises(RelationSssomError, match="supports only subject and value rings"):
        RelationSssomDistribution.open(
            supported_root / MANIFEST_PATH,
            expected_manifest_digest=supported.manifest_digest,
            relation_bundle=bundle,
        )


def test_manifest_pins_bundle_and_exact_artifact_bytes(tmp_path: Path) -> None:
    bundle = _subject_bundle(tmp_path)
    distribution = RelationSssomDistribution.create(bundle)
    artifacts = distribution.artifact_bytes()
    manifest = json.loads(artifacts[MANIFEST_PATH])

    assert manifest["relationAssertionBundle"] == {
        "id": bundle.identifier,
        "contentDigest": bundle.content_digest,
        "manifestDigest": bundle.manifest_digest,
    }
    assert manifest["mappingCount"] == len(bundle.mapping_assertions)
    assert manifest["evidenceAssertionCount"] == len(bundle.evidence_assertions)
    assert manifest["machineProofCount"] == len(bundle.machine_proof_pins)
    assert manifest["directEvidenceLinkCount"] == sum(len(row.evidence) for row in bundle.mapping_assertions)
    assert manifest["semantics"] == {
        "sssomRows": "interoperabilityProjection",
        "machineProofFacts": "derivedFromPinnedMachineProof",
        "productUse": "requiresEvidenceSidecarAndExactProductPolicy",
    }
    by_path = {row["path"]: row for row in manifest["artifacts"]}
    for path in (MAPPINGS_PATH, EVIDENCE_PATH):
        assert by_path[path]["sha256"] == sha256_digest(artifacts[path])
        assert by_path[path]["byteLength"] == len(artifacts[path])
        assert by_path[path]["rowCount"] == len(bundle.mapping_assertions)


def test_persisted_distribution_reopens_and_reverifies(tmp_path: Path) -> None:
    bundle = _subject_bundle(tmp_path)
    distribution = RelationSssomDistribution.create(bundle)
    root = distribution.write_to(tmp_path / "relation-sssom")

    reopened = RelationSssomDistribution.open(
        root / MANIFEST_PATH,
        expected_manifest_digest=distribution.manifest_digest,
        relation_bundle=bundle,
    )

    assert reopened.artifact_bytes() == distribution.artifact_bytes()
    reopened.verify()


def test_open_rechecks_bytes_after_constructing_the_result(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle = _subject_bundle(tmp_path)
    distribution = RelationSssomDistribution.create(bundle)
    root = distribution.write_to(tmp_path / "mutation-during-open")
    original_post_init = RelationSssomDistribution.__post_init__
    construction_count = 0

    def mutate_during_final_construction(value: RelationSssomDistribution) -> None:
        nonlocal construction_count
        construction_count += 1
        original_post_init(value)
        if construction_count == 2:
            target = root / MAPPINGS_PATH
            target.write_bytes(target.read_bytes() + b" ")

    monkeypatch.setattr(RelationSssomDistribution, "__post_init__", mutate_during_final_construction)

    with pytest.raises(RelationSssomError, match="changed while opening"):
        RelationSssomDistribution.open(
            root / MANIFEST_PATH,
            expected_manifest_digest=distribution.manifest_digest,
            relation_bundle=bundle,
        )


def test_open_rechecks_the_file_set_after_constructing_the_result(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle = _subject_bundle(tmp_path)
    distribution = RelationSssomDistribution.create(bundle)
    root = distribution.write_to(tmp_path / "file-set-mutation-during-open")
    original_post_init = RelationSssomDistribution.__post_init__
    construction_count = 0

    def add_file_during_final_construction(value: RelationSssomDistribution) -> None:
        nonlocal construction_count
        construction_count += 1
        original_post_init(value)
        if construction_count == 2:
            (root / "unexpected.txt").write_text("unexpected", encoding="utf-8")

    monkeypatch.setattr(RelationSssomDistribution, "__post_init__", add_file_during_final_construction)

    with pytest.raises(RelationSssomError, match="changed while opening"):
        RelationSssomDistribution.open(
            root / MANIFEST_PATH,
            expected_manifest_digest=distribution.manifest_digest,
            relation_bundle=bundle,
        )


@pytest.mark.parametrize(
    ("field", "claim"),
    [
        ("productUse", "authorizedByThisDistribution"),
        ("machineProofFacts", "callerDeclared"),
    ],
)
def test_open_rejects_a_resealed_semantics_claim(tmp_path: Path, field: str, claim: str) -> None:
    bundle = _subject_bundle(tmp_path)
    distribution = RelationSssomDistribution.create(bundle)
    root = distribution.write_to(tmp_path / "false-product-use-claim")
    manifest_path = root / MANIFEST_PATH
    manifest = json.loads(manifest_path.read_bytes())
    manifest["semantics"][field] = claim
    changed = canonical_json_bytes(manifest)
    manifest_path.write_bytes(changed)

    with pytest.raises(RelationSssomError, match="manifest semantics differ"):
        RelationSssomDistribution.open(
            manifest_path,
            expected_manifest_digest=sha256_digest(changed),
            relation_bundle=bundle,
        )


@pytest.mark.parametrize("path", [MAPPINGS_PATH, EVIDENCE_PATH, MANIFEST_PATH])
def test_open_rejects_tampered_artifacts(tmp_path: Path, path: str) -> None:
    bundle = _subject_bundle(tmp_path)
    distribution = RelationSssomDistribution.create(bundle)
    root = distribution.write_to(tmp_path / f"tampered-{path.split('.')[0]}")
    target = root / path
    target.write_bytes(target.read_bytes() + b" ")

    with pytest.raises(RelationSssomError, match="differ|canonical|newline-terminated"):
        RelationSssomDistribution.open(
            root / MANIFEST_PATH,
            expected_manifest_digest=distribution.manifest_digest,
            relation_bundle=bundle,
        )


def test_open_rejects_extra_files_and_distribution_is_immutable(tmp_path: Path) -> None:
    bundle = _subject_bundle(tmp_path)
    distribution = RelationSssomDistribution.create(bundle)
    root = distribution.write_to(tmp_path / "extra-file")
    (root / "unexpected.txt").write_text("unexpected", encoding="utf-8")

    with pytest.raises(RelationSssomError, match="file set differs"):
        RelationSssomDistribution.open(
            root / MANIFEST_PATH,
            expected_manifest_digest=distribution.manifest_digest,
            relation_bundle=bundle,
        )
    with pytest.raises(FrozenInstanceError):
        distribution.relation_bundle = bundle  # type: ignore[misc]
    with pytest.raises(RelationSssomError, match="requires a RelationAssertionBundle"):
        relation_sssom_text(object())  # type: ignore[arg-type]


def test_an_independent_sssom_reader_keeps_mapping_source_and_assertion_id(tmp_path: Path) -> None:
    pytest.importorskip("sssom")
    from sssom.parsers import parse_sssom_table

    bundle = _subject_bundle(tmp_path)
    distribution = RelationSssomDistribution.create(bundle)
    root = distribution.write_to(tmp_path / "sssom-reader")
    frame = parse_sssom_table(str(root / MAPPINGS_PATH)).df

    assert set(frame["mapping_source"]) == {bundle.identifier}
    assert set(frame["see_also"]) == {row.identifier for row in bundle.mapping_assertions}
