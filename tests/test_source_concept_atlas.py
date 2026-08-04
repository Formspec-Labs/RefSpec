"""Subject source-concept releases enter the atlas through its verified seam."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import pytest
from rdflib import Dataset, Graph, Literal, URIRef
from rdflib.namespace import PROV, RDF, SKOS

from refspec.atlas.model import (
    RKAF,
    PinnedRulespecCoreRelease,
    VocabularyAtlasAsset,
    VocabularyAtlasError,
    build_vocabulary_atlas,
)
from refspec.atlas.source_concept import (
    PinnedSourceConceptSubjectAtlasRelease,
)
from refspec.registry.infrastructure.source_concept_release import (
    SourceConceptReleaseBundle,
    build_source_concept_release_bundle,
)
from refspec.registry.infrastructure.source_controlled_resource import (
    build_source_controlled_resource_bundle,
)
from refspec.registry.infrastructure.source_identity import derive_uuid7
from refspec.storage import canonical_json

CAPTURED_AT = "2026-08-04T12:00:00Z"
SOURCE_ID = "https://publisher.example/source/subject-terms.json"
SCHEME_ID = "https://publisher.example/schemes/subjects"


def _file_digest(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _release(*, ring: str = "subject") -> SourceConceptReleaseBundle:
    local_record_id = "urn:uuid:" + derive_uuid7(
        CAPTURED_AT,
        seed=b"source-concept-atlas-member",
    )
    observation = {
        "id": "urn:ref:test:source-observation:water-quality",
        "sourceArtifact": SOURCE_ID,
        "sourcePath": "terms/water-quality",
        "sourceOrdinal": 0,
        "labels": [
            {
                "value": "Water quality",
                "language": "en",
                "role": "preferred",
            },
            {
                "value": "Quality of water",
                "language": "en",
                "role": "alternate",
            },
        ],
        "identifiers": [],
        "uses": ["mappingReference"],
        "conceptIdentityClaimed": False,
        "localRecordId": local_record_id,
    }
    source_payload = b'{"terms":["Water quality"]}\n'
    source = build_source_controlled_resource_bundle(
        resource_id=f"source-concept-atlas-{ring}",
        title="Source concept atlas fixture",
        resource_kind="sourceTermSnapshot",
        identity_status="captureLocalObservationsOnly",
        uses=("mappingReference",),
        captured_at=CAPTURED_AT,
        observations=(observation,),
        source_artifacts={SOURCE_ID: source_payload},
        source_scheme={
            "id": SCHEME_ID,
            "code": "subjects",
            "label": "Subject scheme",
            "sourceArtifact": SOURCE_ID,
            "sourceFetchId": derive_uuid7(
                CAPTURED_AT,
                seed=b"source-concept-atlas-scheme-fetch",
            ),
            "sourceObservedAt": CAPTURED_AT,
        },
    )
    return build_source_concept_release_bundle(
        source,
        semantic_ring=ring,  # type: ignore[arg-type]
        selected_observation_ids=(str(observation["id"]),),
        selection_policy={
            "id": f"urn:ref:test:source-concept-atlas-selection:{ring}:v1",
            "type": "explicitObservationSet",
        },
        rights_metadata=(
            {
                "type": "RightsMetadata",
                "rightsStatus": "notStated",
                "sourceArtifact": SOURCE_ID,
                "sourceDigest": "sha256:" + hashlib.sha256(source_payload).hexdigest(),
            },
        ),
    )


def _pinned_release(
    tmp_path: Path,
) -> tuple[SourceConceptReleaseBundle, PinnedSourceConceptSubjectAtlasRelease]:
    release = _release()
    root = release.write_to(tmp_path / "source-concept-release")
    pinned = PinnedSourceConceptSubjectAtlasRelease.open(
        root / "bundle-manifest.json",
        expected_manifest_digest=release.manifest_digest,
    )
    return release, pinned


def _core_release(tmp_path: Path) -> PinnedRulespecCoreRelease:
    preimage: dict[str, Any] = {
        "record_type": "RulespecCoreRelease",
        "release_status": "fixture",
        "version": "0.2.0-pre.9+source-concept-test",
        "schema_artifacts": [
            {
                "artifact_digest": "sha256:" + "a" * 64,
                "media_type": "application/schema+json",
                "name": "compiled/json-schema/core/reference-resource-release.schema.json",
            }
        ],
        "validator_artifacts": [
            {
                "artifact_digest": "sha256:" + "b" * 64,
                "media_type": "text/x-python",
                "name": "tools/ci_validate.py",
            }
        ],
        "conformance_fixture_artifacts": [
            {
                "artifact_digest": "sha256:" + "c" * 64,
                "media_type": "application/ld+json",
                "name": "fixtures/reference-resource-release-digest-positive.jsonld",
            }
        ],
    }
    release_digest = "sha256:" + hashlib.sha256(canonical_json(preimage).encode("utf-8")).hexdigest()
    release_id = "urn:rulespec:core:" + release_digest.removeprefix("sha256:")
    path = tmp_path / "rulespec-core.json"
    path.write_text(
        canonical_json(
            {
                **preimage,
                "release_id": release_id,
                "release_digest": release_digest,
            }
        ),
        encoding="utf-8",
    )
    return PinnedRulespecCoreRelease.open(
        path,
        expected_file_digest=_file_digest(path),
        expected_release_id=release_id,
        expected_release_digest=release_digest,
    )


def _plain(value: Any) -> Any:
    if isinstance(value, dict) or hasattr(value, "items"):
        return {str(key): _plain(child) for key, child in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(child) for child in value]
    return value


def test_subject_adapter_exposes_exact_registered_members_and_labels(
    tmp_path: Path,
) -> None:
    release, pinned = _pinned_release(tmp_path)
    view = pinned.verified_view()
    member = next(iter(view.iter_members()))
    expressions = tuple(view.iter_expressions())

    assert view.release_id == release.release_id
    assert member.member_iri == release.concepts[0]["id"]
    assert member.release_iri == release.release_id
    assert member.scheme_iri == SCHEME_ID
    assert view.lookup_member(member.member_iri) == member
    assert {value.original_literal for value in expressions} == {
        "Water quality",
        "Quality of water",
    }
    assert {value.label_role for value in expressions} == {
        "preferred",
        "alternate",
    }
    assert tuple(view.iter_relations()) == ()

    graph = Graph()
    graph.parse(data=canonical_json(_plain(view.rulespec_graph)), format="json-ld")
    concept = URIRef(member.member_iri)
    release_node = URIRef(release.release_id)
    assert (concept, RDF.type, RKAF.RegisteredConcept) in graph
    assert (concept, RDF.type, RKAF.LocalConcept) not in graph
    assert (concept, SKOS.prefLabel, Literal("Water quality", lang="en")) in graph
    assert (concept, SKOS.altLabel, Literal("Quality of water", lang="en")) in graph
    assert (release_node, PROV.hadMember, concept) in graph

    pin = pinned.pin()
    assert pin["role"] == "ManagedReleaseView"
    assert pin["manifestDigest"] == release.manifest_digest
    assert pin["publicationReleaseId"] == release.release_id


@pytest.mark.parametrize("ring", ("entity", "value", "legalIdentity"))
def test_subject_adapter_rejects_every_non_subject_ring(
    tmp_path: Path,
    ring: str,
) -> None:
    release = _release(ring=ring)
    root = release.write_to(tmp_path / ring)

    with pytest.raises(VocabularyAtlasError, match="rejects non-subject"):
        PinnedSourceConceptSubjectAtlasRelease.open(
            root / "bundle-manifest.json",
            expected_manifest_digest=release.manifest_digest,
        )


def test_subject_release_builds_and_reproduces_through_the_shared_atlas(
    tmp_path: Path,
) -> None:
    release, pinned = _pinned_release(tmp_path)
    core = _core_release(tmp_path)
    asset = build_vocabulary_atlas((pinned,), rulespec_core=core)
    output = asset.write(tmp_path / "atlas")

    reopened = VocabularyAtlasAsset.open(
        output,
        expected_manifest_digest=asset.manifest_digest,
        expected_output_digest=asset.output_digest,
    )
    reproduced = VocabularyAtlasAsset.reproduce_from_inputs(
        output,
        releases=(pinned,),
        rulespec_core=core,
        expected_manifest_digest=asset.manifest_digest,
        expected_output_digest=asset.output_digest,
    )
    assert reopened.payload == asset.payload == reproduced.payload
    assert reopened.manifest["counts"]["managedReleases"] == 1

    release_graph_id = next(row["id"] for row in reopened.manifest["graphs"] if row["role"] == "releaseFacts")
    dataset = Dataset(default_union=False)
    dataset.parse(data=reopened.payload.decode("utf-8"), format="nquads")
    graph = dataset.graph(URIRef(release_graph_id))
    concept = URIRef(str(release.concepts[0]["id"]))
    assert (concept, RDF.type, RKAF.RegisteredConcept) in graph
    assert (concept, RDF.type, RKAF.LocalConcept) not in graph
    assert b"candidateUseAuthorized" not in reopened.payload
    assert b"acceptedOutputUseAuthorized" not in reopened.payload


def test_pinned_adapter_reopens_and_refuses_later_source_tampering(
    tmp_path: Path,
) -> None:
    release, pinned = _pinned_release(tmp_path)
    source_artifact = next(path for path in release.artifact_bytes() if path.startswith("source/sources/"))
    artifact_path = pinned.manifest_path.parent / source_artifact
    artifact_path.write_bytes(artifact_path.read_bytes() + b"forged")

    with pytest.raises(VocabularyAtlasError, match="bytes differ"):
        pinned.verified_view()
