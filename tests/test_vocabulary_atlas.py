"""Static vocabulary atlas boundary, qualification, and tamper regressions."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from collections import defaultdict
from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path
from types import MappingProxyType
from typing import Any

import pytest
from rdflib import Dataset, Literal, URIRef
from rdflib.namespace import RDF

import refspec
import refspec.atlas as atlas_api
from refspec import binding
from refspec.atlas import (
    ATLAS,
    RKAF,
    CrosswalkArtifact,
    CrosswalkBundle,
    MachineValidation,
    MappingCandidate,
    MappingFeedback,
    PinnedManagedRelease,
    PinnedRulespecCoreRelease,
    VocabularyAtlasAsset,
    VocabularyAtlasError,
    VocabularyAtlasQueries,
    build_vocabulary_atlas,
)
from refspec.atlas.cli import main as atlas_main
from refspec.managed_release import (
    ManagedReleaseExpression,
    ManagedReleaseMember,
    ManagedReleaseView,
)
from refspec.release_graph import rulespec_graph_digest
from refspec.storage import canonical_json

_FIXTURE_SPEC = importlib.util.spec_from_file_location(
    "refspec_test_managed_release_view_fixture",
    Path(__file__).with_name("test_managed_release_view.py"),
)
assert _FIXTURE_SPEC is not None and _FIXTURE_SPEC.loader is not None
_FIXTURE_MODULE = importlib.util.module_from_spec(_FIXTURE_SPEC)
sys.modules[_FIXTURE_SPEC.name] = _FIXTURE_MODULE
_FIXTURE_SPEC.loader.exec_module(_FIXTURE_MODULE)
build_bundle = _FIXTURE_MODULE.build_bundle

SHA_A = "sha256:" + "a" * 64
SHA_B = "sha256:" + "b" * 64
_ABSENT = object()
SOURCE_MEMBER = "urn:test:atlas:source:concept"
TARGET_MEMBER = "urn:test:atlas:target:concept"
SOURCE_RELEASE = "urn:test:atlas:source:release"
TARGET_RELEASE = "urn:test:atlas:target:release"


def test_atlas_producer_api_stays_in_its_submodule() -> None:
    assert not hasattr(refspec, "VocabularyAtlasAsset")
    assert not hasattr(refspec, "CrosswalkBundle")
    assert hasattr(atlas_api, "AtlasReleaseFactsView")
    assert hasattr(atlas_api, "VerifiedManagedReleaseSource")
    assert not hasattr(atlas_api, "VocabularyReleaseView")
    assert not hasattr(atlas_api, "VerifiedVocabularyReleaseSource")


def test_queries_cannot_receive_a_hand_constructed_unverified_asset() -> None:
    with pytest.raises(TypeError, match="must come from"):
        VocabularyAtlasAsset(  # type: ignore[call-arg]
            payload=b"",
            manifest={"graphs": []},
        )

    forged = object.__new__(VocabularyAtlasAsset)
    object.__setattr__(forged, "payload", b"")
    object.__setattr__(forged, "manifest", {"graphs": []})
    with pytest.raises(VocabularyAtlasError, match="not a verified distribution"):
        VocabularyAtlasQueries(forged)


def _file_digest(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _plain_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _plain_json(child) for key, child in value.items()}
    if isinstance(value, tuple):
        return [_plain_json(child) for child in value]
    return value


def _core_preimage(**overrides: Any) -> dict[str, Any]:
    """Return the smallest record that satisfies the published Core contract."""

    preimage: dict[str, Any] = {
        "record_type": "RulespecCoreRelease",
        "release_status": "fixture",
        "version": "0.2.0-pre.9+test-fixture",
        "schema_artifacts": [
            {
                "artifact_digest": SHA_A,
                "media_type": "application/schema+json",
                "name": "compiled/json-schema/core/artifact.schema.json",
            }
        ],
        "validator_artifacts": [
            {
                "artifact_digest": SHA_B,
                "media_type": "text/x-python",
                "name": "tools/ci_validate.py",
            }
        ],
        "conformance_fixture_artifacts": [
            {
                "artifact_digest": SHA_A,
                "media_type": "application/ld+json",
                "name": "fixtures/ailineage-positive.jsonld",
            }
        ],
    }
    for key, value in overrides.items():
        if value is _ABSENT:
            preimage.pop(key, None)
        else:
            preimage[key] = value
    return preimage


def _open_core_release(tmp_path: Path, preimage: Mapping[str, Any]) -> PinnedRulespecCoreRelease:
    """Write the exact preimage with matching identity and open it."""

    release_digest = "sha256:" + hashlib.sha256(canonical_json(dict(preimage)).encode("utf-8")).hexdigest()
    release_id = "urn:rulespec:core:" + release_digest.removeprefix("sha256:")
    path = tmp_path / "rulespec-core.json"
    path.write_text(
        json.dumps(
            {**preimage, "release_digest": release_digest, "release_id": release_id},
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return PinnedRulespecCoreRelease.open(
        path,
        expected_file_digest=_file_digest(path),
        expected_release_id=release_id,
        expected_release_digest=release_digest,
    )


def _core_release(tmp_path: Path) -> PinnedRulespecCoreRelease:
    return _open_core_release(tmp_path, _core_preimage())


def _real_release(tmp_path: Path) -> PinnedManagedRelease:
    manifest = build_bundle(tmp_path / "managed")
    return PinnedManagedRelease.open(
        manifest,
        expected_manifest_digest=_file_digest(manifest),
    )


class _FixturePinnedRelease(PinnedManagedRelease):
    """A pin-shaped test adapter over a real ManagedReleaseView instance."""

    def verified_view(self) -> ManagedReleaseView:
        return self.view

    def pin(self) -> dict[str, Any]:
        return {
            "role": "ManagedReleaseView",
            "manifestDigest": self.manifest_digest,
            "publicationReleaseId": self.view.release_id,
            "rulespecGraph": {
                "id": self.view.rulespec_graph_id,
                "digest": rulespec_graph_digest(_plain_json(self.view.rulespec_graph)),
            },
        }


class _MismatchedReleaseSource:
    """Adversarial source whose pin describes a different verified view."""

    def __init__(
        self,
        view: ManagedReleaseView,
        pin: dict[str, Any],
    ) -> None:
        self._view = view
        self._pin = pin

    def verified_view(self) -> ManagedReleaseView:
        return self._view

    def pin(self) -> dict[str, Any]:
        return self._pin


def _view(
    *,
    publication: str,
    graph_id: str,
    release: str,
    member: str,
    label: str,
) -> ManagedReleaseView:
    member_record = MappingProxyType(
        {
            "@id": member,
            "@type": "https://rulespec.org/ns/v1#RegisteredConcept",
            "http://www.w3.org/2004/02/skos/core#prefLabel": label,
        }
    )
    release_record = MappingProxyType(
        {
            "@id": release,
            "@type": "https://rulespec.org/ns/v1#ReferenceResourceRelease",
            "http://www.w3.org/ns/prov#hadMember": (member,),
            "https://rulespec.org/ns/v1#referenceReleaseDigest": SHA_A,
        }
    )
    managed_member = ManagedReleaseMember(
        member_iri=member,
        release_iri=release,
        scheme_iri=release + ":scheme",
        record=member_record,
    )
    expression = ManagedReleaseExpression(
        expression_id=member + ":expression",
        member_iri=member,
        indexed_text=label.casefold(),
        original_literal=label,
        language_tag="en",
        semantic_property_iri="http://www.w3.org/2004/02/skos/core#prefLabel",
        source_property_or_path="prefLabel",
        record=MappingProxyType({}),
        label_role="preferred",
        source_status="current",
    )
    return ManagedReleaseView(
        _release_id=publication,
        _rulespec_graph_id=graph_id,
        _rulespec_graph=MappingProxyType({"@graph": (release_record, member_record)}),
        _expression_corpus_snapshot=MappingProxyType({"id": publication + ":corpus", "digest": SHA_A}),
        _members=MappingProxyType({member: managed_member}),
        _expressions=(expression,),
        _relations=(),
        _lifecycle_participants=(),
        _concept_mappings=(),
        _release_graph_validation_receipt=MappingProxyType({}),
    )


def _two_releases(tmp_path: Path) -> tuple[PinnedManagedRelease, PinnedManagedRelease]:
    source = _view(
        publication="urn:test:atlas:source:publication",
        graph_id="urn:test:atlas:source:graph",
        release=SOURCE_RELEASE,
        member=SOURCE_MEMBER,
        label="Shared policy label",
    )
    target = _view(
        publication="urn:test:atlas:target:publication",
        graph_id="urn:test:atlas:target:graph",
        release=TARGET_RELEASE,
        member=TARGET_MEMBER,
        label="  shared POLICY label ",
    )
    return (
        _FixturePinnedRelease(tmp_path / "source.json", SHA_A, source),
        _FixturePinnedRelease(tmp_path / "target.json", SHA_B, target),
    )


INPUT_CONTEXT_CONTENT: Mapping[str, Any] = {
    "protocol": "refspec-atlas-model-input-v1",
    "sourceLabel": "energy policy",
    "sourceMember": SOURCE_MEMBER,
    "targetLabel": "energy policy",
    "targetMember": TARGET_MEMBER,
}
INPUT_DIGEST = binding.canonical_sha256(dict(INPUT_CONTEXT_CONTENT))


def _input_context() -> CrosswalkArtifact:
    return CrosswalkArtifact.create(
        role="inputContext",
        media_type="application/json",
        content=INPUT_CONTEXT_CONTENT,
    )


def _candidate_and_artifacts() -> tuple[
    MappingCandidate,
    CrosswalkArtifact,
    CrosswalkArtifact,
    CrosswalkArtifact,
    CrosswalkArtifact,
]:
    evidence = CrosswalkArtifact.create(
        role="evidence",
        media_type="application/json",
        content={"method": "sealed-label-comparison", "version": "1"},
    )
    candidate = MappingCandidate.create(
        source_member=SOURCE_MEMBER,
        source_release=SOURCE_RELEASE,
        target_member=TARGET_MEMBER,
        target_release=TARGET_RELEASE,
        proposed_relation="http://www.w3.org/2004/02/skos/core#closeMatch",
        generator_kind="aiAgent",
        generator_actor="urn:test:atlas:generator",
        generator_provider="urn:test:atlas:provider:generator",
        model_id="atlas-generator",
        model_version="1",
        prompt_template="urn:test:atlas:prompt:v1",
        input_context_digest=INPUT_DIGEST,
        temperature="0",
        evidence=[evidence.reference()],
        generated_at="2026-07-31T18:00:00Z",
        seed=7,
    )
    request = CrosswalkArtifact.create(
        role="validationRequest",
        media_type="application/json",
        content={
            "candidate": candidate.reference(),
            "inputDigest": INPUT_DIGEST,
            "protocol": "refspec-atlas-machine-validation-v1",
        },
    )
    response_a = _response(candidate, request, suffix="a")
    response_b = _response(candidate, request, suffix="b")
    return candidate, evidence, request, response_a, response_b


def _response(
    candidate: MappingCandidate,
    request: CrosswalkArtifact,
    *,
    suffix: str,
    provider: str | None = None,
    provider_model_id: str | None = None,
) -> CrosswalkArtifact:
    return CrosswalkArtifact.create(
        role="validationResponse",
        media_type="application/json",
        content={
            "candidate": candidate.reference(),
            "inputDigest": INPUT_DIGEST,
            "requestArtifact": request.reference(),
            "validatorActor": f"urn:test:atlas:validator:{suffix}",
            "provider": provider or f"urn:test:atlas:provider:{suffix}",
            "providerModelId": provider_model_id or f"provider-model-{suffix}",
            "deterministicChecksPassed": True,
            "outcome": "supports",
        },
    )


def _validation(
    candidate: MappingCandidate,
    request: CrosswalkArtifact,
    response: CrosswalkArtifact,
    *,
    suffix: str,
    provider: str | None = None,
    provider_model_id: str | None = None,
) -> MachineValidation:
    return MachineValidation.create(
        candidate=candidate.reference(),
        validator_kind="aiAgent",
        validator_actor=f"urn:test:atlas:validator:{suffix}",
        independence_group=f"urn:test:atlas:group:{suffix}",
        provider=provider or f"urn:test:atlas:provider:{suffix}",
        provider_model_id=provider_model_id or f"provider-model-{suffix}",
        sealed_input_digest=INPUT_DIGEST,
        request_artifact=request.reference(),
        response_artifact=response.reference(),
        deterministic_checks_passed=True,
        outcome="supports",
        completed_at="2026-07-31T18:05:00Z",
    )


def _qualified_bundle(
    *,
    same_provider: bool = False,
    same_provider_model: bool = False,
) -> CrosswalkBundle:
    candidate, evidence, request, _, _ = _candidate_and_artifacts()
    providers = (
        ("urn:test:atlas:provider:shared",) * 2
        if same_provider
        else ("urn:test:atlas:provider:a", "urn:test:atlas:provider:b")
    )
    provider_model_ids = (
        ("shared-provider-model",) * 2 if same_provider_model else ("provider-model-a", "provider-model-b")
    )
    response_a = _response(
        candidate,
        request,
        suffix="a",
        provider=providers[0],
        provider_model_id=provider_model_ids[0],
    )
    response_b = _response(
        candidate,
        request,
        suffix="b",
        provider=providers[1],
        provider_model_id=provider_model_ids[1],
    )
    validations = (
        _validation(
            candidate,
            request,
            response_a,
            suffix="a",
            provider=providers[0],
            provider_model_id=provider_model_ids[0],
        ),
        _validation(
            candidate,
            request,
            response_b,
            suffix="b",
            provider=providers[1],
            provider_model_id=provider_model_ids[1],
        ),
    )
    return CrosswalkBundle.create(
        artifacts=(_input_context(), evidence, request, response_a, response_b),
        mapping_candidates=(candidate,),
        machine_validations=validations,
    )


def test_exact_inputs_build_deterministic_blank_node_free_asset(tmp_path: Path) -> None:
    release = _real_release(tmp_path)
    core = _core_release(tmp_path)

    first = build_vocabulary_atlas((release,), rulespec_core=core)
    second = build_vocabulary_atlas((release,), rulespec_core=core)

    assert first.payload == second.payload
    assert first.manifest_bytes() == second.manifest_bytes()
    assert b"_:" not in first.payload
    assert first.manifest["format"] == "refspec-vocabulary-atlas-nquads-1.0"
    assert [row["role"] for row in first.manifest["graphs"]] == [
        "releaseFacts",
        "analysis",
    ]
    assert {item["role"] for item in first.manifest["inputs"]} == {
        "ManagedReleaseView",
        "RulespecCoreRelease",
    }


def test_managed_release_pin_must_describe_the_same_verified_view(
    tmp_path: Path,
) -> None:
    source, target = _two_releases(tmp_path)
    mismatched = _MismatchedReleaseSource(source.verified_view(), target.pin())

    with pytest.raises(VocabularyAtlasError, match="pin differs from its verified view"):
        build_vocabulary_atlas(
            (mismatched,),
            rulespec_core=_core_release(tmp_path),
        )


def test_cli_builds_from_exact_file_pins(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    release = _real_release(tmp_path)
    core = _core_release(tmp_path)
    output = tmp_path / "cli-atlas"

    assert (
        atlas_main(
            (
                "--managed-release",
                str(release.manifest_path),
                release.manifest_digest,
                "--rulespec-core",
                str(core.path),
                "--rulespec-core-file-digest",
                core.file_digest,
                "--rulespec-core-release-id",
                core.release_id,
                "--rulespec-core-release-digest",
                core.release_digest,
                "--output",
                str(output),
            )
        )
        == 0
    )
    selection = json.loads(capsys.readouterr().out)

    reopened = VocabularyAtlasAsset.open(
        output,
        expected_manifest_digest=selection["manifestDigest"],
        expected_output_digest=selection["outputDigest"],
    )
    assert selection["assetId"] == reopened.manifest["id"]


def test_core_pin_rejects_a_release_that_declares_only_its_record_type(tmp_path: Path) -> None:
    with pytest.raises(VocabularyAtlasError, match="omits required fields"):
        _open_core_release(tmp_path, {"record_type": "RulespecCoreRelease"})


def test_core_pin_rejects_a_release_with_an_unknown_release_status(tmp_path: Path) -> None:
    with pytest.raises(VocabularyAtlasError, match="release_status"):
        _open_core_release(tmp_path, _core_preimage(release_status="draft"))


@pytest.mark.parametrize(
    "field",
    ["conformance_fixture_artifacts", "schema_artifacts", "validator_artifacts"],
)
def test_core_pin_rejects_a_release_with_empty_artifact_manifests(tmp_path: Path, field: str) -> None:
    with pytest.raises(VocabularyAtlasError, match=f"{field} must list at least one artifact"):
        _open_core_release(tmp_path, _core_preimage(**{field: []}))


def test_core_pin_rejects_a_release_with_a_malformed_artifact_entry(tmp_path: Path) -> None:
    with pytest.raises(VocabularyAtlasError, match=r"schema_artifacts\[0\]"):
        _open_core_release(
            tmp_path,
            _core_preimage(
                schema_artifacts=[
                    {
                        "media_type": "application/schema+json",
                        "name": "compiled/json-schema/core/artifact.schema.json",
                    }
                ]
            ),
        )


def test_core_pin_rejects_a_release_missing_its_version(tmp_path: Path) -> None:
    with pytest.raises(VocabularyAtlasError, match="omits required fields"):
        _open_core_release(tmp_path, _core_preimage(version=_ABSENT))


def test_core_pin_accepts_the_minimally_valid_core_release(tmp_path: Path) -> None:
    core = _core_release(tmp_path)

    assert core.release_id.startswith("urn:rulespec:core:")
    assert core.pin()["role"] == "RulespecCoreRelease"


def test_declared_rulespec_core_profile_opens_the_exact_sibling_fixture() -> None:
    refspec_root = Path(__file__).resolve().parents[1]
    rulespec_root = refspec_root.parents[1] / "rulespec"
    profile = json.loads((refspec_root / "profiles/rulespec-core-dependency.json").read_text())
    release_path = rulespec_root / profile["artifact"]["path"]
    if not release_path.is_file():
        pytest.skip(f"Rulespec Core sibling fixture is unavailable: {release_path}")

    opened = PinnedRulespecCoreRelease.open(
        release_path,
        expected_file_digest=profile["artifact"]["sha256"],
        expected_release_id=profile["release"]["releaseId"],
        expected_release_digest=profile["release"]["releaseDigest"],
    )

    assert opened.release_id == profile["release"]["releaseId"]


def test_equal_labels_form_analysis_cluster_but_never_mapping(tmp_path: Path) -> None:
    releases = _two_releases(tmp_path)
    asset = build_vocabulary_atlas(releases, rulespec_core=_core_release(tmp_path))
    queries = VocabularyAtlasQueries(asset)

    clusters = queries.label_clusters()
    assert len(clusters) == 1
    assert clusters[0].normalized_label == "shared policy label"
    assert set(clusters[0].members) == {SOURCE_MEMBER, TARGET_MEMBER}
    assert queries.search_only_mappings() == ()
    analysis_id = next(row["id"] for row in asset.manifest["graphs"] if row["role"] == "analysis")
    dataset = Dataset(default_union=False)
    dataset.parse(data=asset.payload.decode("utf-8"), format="nquads")
    analysis = dataset.graph(URIRef(analysis_id))
    assert not set(analysis.subjects(RDF.type, RKAF.ConceptMapping))


def test_equal_labels_inside_one_release_do_not_form_crosswalk_cluster(
    tmp_path: Path,
) -> None:
    release_id = "urn:test:atlas:one-release"
    member_ids = ("urn:test:atlas:member:one", "urn:test:atlas:member:two")
    records = tuple(
        MappingProxyType(
            {
                "@id": member_id,
                "@type": "https://rulespec.org/ns/v1#RegisteredConcept",
                "http://www.w3.org/2004/02/skos/core#prefLabel": "Duplicate label",
            }
        )
        for member_id in member_ids
    )
    members = MappingProxyType(
        {
            member_id: ManagedReleaseMember(
                member_iri=member_id,
                release_iri=release_id,
                scheme_iri=release_id + ":scheme",
                record=record,
            )
            for member_id, record in zip(member_ids, records, strict=True)
        }
    )
    expressions = tuple(
        ManagedReleaseExpression(
            expression_id=member_id + ":expression",
            member_iri=member_id,
            indexed_text="duplicate label",
            original_literal="Duplicate label",
            language_tag="en",
            semantic_property_iri="http://www.w3.org/2004/02/skos/core#prefLabel",
            source_property_or_path="prefLabel",
            record=MappingProxyType({}),
            label_role="preferred",
            source_status="current",
        )
        for member_id in member_ids
    )
    view = ManagedReleaseView(
        _release_id="urn:test:atlas:one-publication",
        _rulespec_graph_id="urn:test:atlas:one-graph",
        _rulespec_graph=MappingProxyType({"@graph": records}),
        _expression_corpus_snapshot=MappingProxyType({"id": "urn:test:corpus", "digest": SHA_A}),
        _members=members,
        _expressions=expressions,
        _relations=(),
        _lifecycle_participants=(),
        _concept_mappings=(),
        _release_graph_validation_receipt=MappingProxyType({}),
    )
    release = _FixturePinnedRelease(tmp_path / "same-release.json", SHA_A, view)

    asset = build_vocabulary_atlas((release,), rulespec_core=_core_release(tmp_path))

    assert VocabularyAtlasQueries(asset).label_clusters() == ()


def test_two_independent_machines_qualify_search_without_human_review(
    tmp_path: Path,
) -> None:
    bundle = _qualified_bundle()
    asset = build_vocabulary_atlas(
        _two_releases(tmp_path),
        rulespec_core=_core_release(tmp_path),
        crosswalk=bundle,
    )

    mappings = VocabularyAtlasQueries(asset).search_only_mappings()
    assert len(mappings) == 1
    assert mappings[0].source_member == SOURCE_MEMBER
    assert mappings[0].target_member == TARGET_MEMBER
    assert len(mappings[0].validation_ids) == 2
    assert asset.manifest["counts"]["feedback"] == 0


def test_shared_machine_provider_cannot_qualify_search(tmp_path: Path) -> None:
    asset = build_vocabulary_atlas(
        _two_releases(tmp_path),
        rulespec_core=_core_release(tmp_path),
        crosswalk=_qualified_bundle(same_provider=True),
    )

    assert VocabularyAtlasQueries(asset).search_only_mappings() == ()


def test_shared_provider_model_cannot_qualify_search(tmp_path: Path) -> None:
    asset = build_vocabulary_atlas(
        _two_releases(tmp_path),
        rulespec_core=_core_release(tmp_path),
        crosswalk=_qualified_bundle(same_provider_model=True),
    )

    assert VocabularyAtlasQueries(asset).search_only_mappings() == ()


def test_machine_validation_requires_provider_model_identity() -> None:
    candidate, _, request, response_a, _ = _candidate_and_artifacts()

    with pytest.raises(VocabularyAtlasError, match="provider model id is required"):
        _validation(
            candidate,
            request,
            response_a,
            suffix="a",
            provider_model_id=" ",
        )


def test_machine_response_must_match_the_declared_validator_result() -> None:
    candidate, evidence, request, _, response_b = _candidate_and_artifacts()
    contradictory = CrosswalkArtifact.create(
        role="validationResponse",
        media_type="application/json",
        content={
            "candidate": candidate.reference(),
            "inputDigest": INPUT_DIGEST,
            "requestArtifact": request.reference(),
            "validatorActor": "urn:test:atlas:validator:a",
            "provider": "urn:test:atlas:provider:a",
            "providerModelId": "provider-model-a",
            "deterministicChecksPassed": True,
            "outcome": "rejects",
        },
    )
    validations = (
        _validation(candidate, request, contradictory, suffix="a"),
        _validation(candidate, request, response_b, suffix="b"),
    )

    with pytest.raises(VocabularyAtlasError, match="response does not seal"):
        CrosswalkBundle.create(
            artifacts=(_input_context(), evidence, request, contradictory, response_b),
            mapping_candidates=(candidate,),
            machine_validations=validations,
        )


def test_feedback_is_append_only_and_does_not_change_eligibility(tmp_path: Path) -> None:
    bundle = _qualified_bundle()
    candidate = bundle.to_dict()["mappingCandidates"][0]
    feedback = MappingFeedback.create(
        candidate={
            "id": candidate["id"],
            "digest": candidate["canonicalPayloadDigest"],
        },
        actor="urn:test:atlas:reviewer",
        disposition="challenges",
        comment="Review this mapping during later evaluation.",
        recorded_at="2026-08-01T12:00:00Z",
    )
    extended = bundle.with_feedback(feedback)
    releases = _two_releases(tmp_path)
    core = _core_release(tmp_path)

    before = build_vocabulary_atlas(releases, rulespec_core=core, crosswalk=bundle)
    after = build_vocabulary_atlas(releases, rulespec_core=core, crosswalk=extended)

    assert VocabularyAtlasQueries(before).search_only_mappings() == (
        VocabularyAtlasQueries(after).search_only_mappings()
    )
    assert VocabularyAtlasQueries(after).feedback_ids() == (feedback.identifier,)
    with pytest.raises(VocabularyAtlasError, match="already present"):
        extended.with_feedback(feedback)


def test_candidate_input_context_bytes_must_exist_in_the_bundle() -> None:
    """The probe made permanent: a cited input context whose bytes are nowhere.

    Before this refusal a candidate could reach ``searchOnly`` while naming a
    sealed input no reader could ever obtain, so the two-machine gate proved
    only that three records agreed on a string.
    """

    evidence = CrosswalkArtifact.create(
        role="evidence",
        media_type="application/json",
        content={"method": "sealed-label-comparison", "version": "1"},
    )
    candidate = MappingCandidate.create(
        source_member=SOURCE_MEMBER,
        source_release=SOURCE_RELEASE,
        target_member=TARGET_MEMBER,
        target_release=TARGET_RELEASE,
        proposed_relation="http://www.w3.org/2004/02/skos/core#closeMatch",
        generator_kind="aiAgent",
        generator_actor="urn:test:atlas:generator",
        generator_provider="urn:test:atlas:provider:generator",
        model_id="atlas-generator",
        model_version="1",
        prompt_template="urn:test:atlas:prompt:v1",
        input_context_digest=SHA_A,
        temperature="0",
        evidence=[evidence.reference()],
        generated_at="2026-07-31T18:00:00Z",
        seed=7,
    )
    request = CrosswalkArtifact.create(
        role="validationRequest",
        media_type="application/json",
        content={
            "candidate": candidate.reference(),
            "inputDigest": INPUT_DIGEST,
            "protocol": "refspec-atlas-machine-validation-v1",
        },
    )
    response_a = _response(candidate, request, suffix="a")
    response_b = _response(candidate, request, suffix="b")
    validations = (
        _validation(candidate, request, response_a, suffix="a"),
        _validation(candidate, request, response_b, suffix="b"),
    )

    with pytest.raises(VocabularyAtlasError, match="input context"):
        CrosswalkBundle.create(
            artifacts=(evidence, request, response_a, response_b),
            mapping_candidates=(candidate,),
            machine_validations=validations,
        )


def test_input_context_artifact_must_digest_to_the_declared_input() -> None:
    """Naming an artifact is not enough; its bytes must produce the digest."""

    impostor = CrosswalkArtifact.create(
        role="inputContext",
        media_type="application/json",
        content={"sourceLabel": "wrong", "targetLabel": "wrong"},
    )
    candidate, evidence, request, response_a, response_b = _candidate_and_artifacts()
    validations = (
        _validation(candidate, request, response_a, suffix="a"),
        _validation(candidate, request, response_b, suffix="b"),
    )

    with pytest.raises(VocabularyAtlasError, match="input context"):
        CrosswalkBundle.create(
            artifacts=(impostor, evidence, request, response_a, response_b),
            mapping_candidates=(candidate,),
            machine_validations=validations,
        )


def test_matching_bytes_under_another_role_do_not_close_the_input_context() -> None:
    """The role filter is load-bearing, not decoration.

    An evidence artifact can hold the exact model-input bytes and still leave
    the citation open: a consumer resolving ``inputContextDigest`` looks for
    the input a machine was given, and evidence is a different claim about a
    different stage. Without the role test, any artifact whose content happened
    to digest alike would silently satisfy the gate.
    """

    disguised = CrosswalkArtifact.create(
        role="evidence",
        media_type="application/json",
        content=INPUT_CONTEXT_CONTENT,
    )
    assert disguised.content_digest == INPUT_DIGEST

    candidate, evidence, request, response_a, response_b = _candidate_and_artifacts()
    validations = (
        _validation(candidate, request, response_a, suffix="a"),
        _validation(candidate, request, response_b, suffix="b"),
    )

    with pytest.raises(
        VocabularyAtlasError,
        match="input context does not close against the bundle",
    ):
        CrosswalkBundle.create(
            artifacts=(disguised, evidence, request, response_a, response_b),
            mapping_candidates=(candidate,),
            machine_validations=validations,
        )


def test_an_ambiguous_input_context_refuses_instead_of_picking_one() -> None:
    """Two artifacts can share content bytes while differing in media type.

    Resolution must be exact. Silently taking the first match would make the
    published ``inputContextArtifact`` link depend on iteration order rather
    than on the bundle, so the producer refuses the ambiguity outright.
    """

    first = _input_context()
    second = CrosswalkArtifact.create(
        role="inputContext",
        media_type="application/vnd.refspec.model-input+json",
        content=INPUT_CONTEXT_CONTENT,
    )
    assert first.identifier != second.identifier
    assert first.content_digest == second.content_digest == INPUT_DIGEST

    candidate, evidence, request, response_a, response_b = _candidate_and_artifacts()
    validations = (
        _validation(candidate, request, response_a, suffix="a"),
        _validation(candidate, request, response_b, suffix="b"),
    )

    with pytest.raises(
        VocabularyAtlasError,
        match="input context resolves to several artifacts",
    ):
        CrosswalkBundle.create(
            artifacts=(first, second, evidence, request, response_a, response_b),
            mapping_candidates=(candidate,),
            machine_validations=validations,
        )


def test_input_context_is_a_supported_artifact_role() -> None:
    context = CrosswalkArtifact.create(
        role="inputContext",
        media_type="application/json",
        content={"sourceLabel": "energy policy", "targetLabel": "energy policy"},
    )

    assert context.role == "inputContext"
    assert context.content_digest == binding.canonical_sha256(
        {"sourceLabel": "energy policy", "targetLabel": "energy policy"}
    )


def test_qualified_bundle_projects_a_resolvable_input_context(tmp_path: Path) -> None:
    """The published graph carries the link a consumer needs to resolve."""

    bundle = _qualified_bundle()
    asset = build_vocabulary_atlas(
        _two_releases(tmp_path),
        rulespec_core=_core_release(tmp_path),
        crosswalk=bundle,
    )
    dataset = Dataset()
    dataset.parse(data=asset.payload.decode("utf-8"), format="nquads")
    analysis_id = next(
        graph["id"]
        for graph in asset.manifest["graphs"]
        if graph["role"] == "analysis"
    )
    analysis = dataset.graph(URIRef(analysis_id))

    candidates = list(analysis.subjects(RDF.type, ATLAS.MappingCandidate))
    assert len(candidates) == 1
    context = list(analysis.objects(candidates[0], ATLAS.inputContextArtifact))
    assert len(context) == 1
    assert (context[0], ATLAS.artifactRole, Literal("inputContext")) in analysis
    declared = list(analysis.objects(candidates[0], ATLAS.inputContextDigest))
    assert list(analysis.objects(context[0], ATLAS.contentDigest)) == declared


def test_crosswalk_references_must_close_against_bundled_artifacts() -> None:
    candidate, _, request, response_a, _ = _candidate_and_artifacts()
    validation = _validation(candidate, request, response_a, suffix="a")

    with pytest.raises(VocabularyAtlasError, match="does not close"):
        CrosswalkBundle.create(
            artifacts=(request, response_a),
            mapping_candidates=(candidate,),
            machine_validations=(validation,),
        )


def test_crosswalk_bundle_round_trips_as_an_exact_static_file(tmp_path: Path) -> None:
    bundle = _qualified_bundle()
    path = bundle.write(tmp_path / "crosswalk.json")

    reopened = CrosswalkBundle.open(
        path,
        expected_file_digest=_file_digest(path),
        expected_bundle_digest=bundle.digest,
    )

    assert reopened.to_dict() == bundle.to_dict()


def test_canonical_profile_rejects_float_temperature() -> None:
    _, evidence, _, _, _ = _candidate_and_artifacts()
    with pytest.raises(VocabularyAtlasError, match="decimal string"):
        MappingCandidate.create(
            source_member=SOURCE_MEMBER,
            source_release=SOURCE_RELEASE,
            target_member=TARGET_MEMBER,
            target_release=TARGET_RELEASE,
            proposed_relation="http://www.w3.org/2004/02/skos/core#closeMatch",
            generator_kind="aiModel",
            generator_actor="urn:test:atlas:generator",
            generator_provider="urn:test:atlas:provider",
            model_id="model",
            model_version="1",
            prompt_template="urn:test:atlas:prompt",
            input_context_digest=SHA_A,
            temperature=0.0,  # type: ignore[arg-type]
            evidence=(evidence.reference(),),
            generated_at="2026-07-31T18:00:00Z",
        )


def test_reopen_verifies_output_counts_and_exact_external_pins(tmp_path: Path) -> None:
    release = _real_release(tmp_path)
    core = _core_release(tmp_path)
    asset = build_vocabulary_atlas((release,), rulespec_core=core)
    output = asset.write(tmp_path / "atlas")

    reopened = VocabularyAtlasAsset.open(
        output,
        expected_manifest_digest=asset.manifest_digest,
        expected_output_digest=asset.output_digest,
    )
    assert reopened.payload == asset.payload
    assert reopened.rulespec_core_pin() == {
        "release_id": core.release_id,
        "release_digest": core.release_digest,
    }

    manifest_path = output / "atlas-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["output"]["quadCount"] += 1
    manifest["canonicalPayloadDigest"] = "sha256:" + "0" * 64
    manifest_path.write_text(
        canonical_json(manifest) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(VocabularyAtlasError, match="manifest digest differs"):
        VocabularyAtlasAsset.open(
            output,
            expected_manifest_digest=_file_digest(manifest_path),
            expected_output_digest=asset.output_digest,
        )


def test_reproduction_requires_crosswalk_bundle_and_rejects_release_pin_change(
    tmp_path: Path,
) -> None:
    releases = _two_releases(tmp_path)
    core = _core_release(tmp_path)
    bundle = _qualified_bundle()
    asset = build_vocabulary_atlas(
        releases,
        rulespec_core=core,
        crosswalk=bundle,
    )
    output = asset.write(tmp_path / "atlas")

    VocabularyAtlasAsset.open(
        output,
        expected_manifest_digest=asset.manifest_digest,
        expected_output_digest=asset.output_digest,
    )
    with pytest.raises(VocabularyAtlasError, match="release input pins differ"):
        VocabularyAtlasAsset.reproduce_from_inputs(
            output,
            releases=releases,
            rulespec_core=core,
            expected_manifest_digest=asset.manifest_digest,
            expected_output_digest=asset.output_digest,
        )
    VocabularyAtlasAsset.reproduce_from_inputs(
        output,
        releases=releases,
        rulespec_core=core,
        expected_manifest_digest=asset.manifest_digest,
        expected_output_digest=asset.output_digest,
        crosswalk=bundle,
    )
    changed = (replace(releases[0], manifest_digest=SHA_B), releases[1])
    with pytest.raises(VocabularyAtlasError, match="release input pins differ"):
        VocabularyAtlasAsset.reproduce_from_inputs(
            output,
            releases=changed,
            rulespec_core=core,
            expected_manifest_digest=asset.manifest_digest,
            expected_output_digest=asset.output_digest,
            crosswalk=bundle,
        )


def test_file_only_open_rejects_forged_machine_proof_despite_resealed_counts(
    tmp_path: Path,
) -> None:
    release = _real_release(tmp_path)
    core = _core_release(tmp_path)
    asset = build_vocabulary_atlas((release,), rulespec_core=core)
    output = asset.write(tmp_path / "atlas")
    manifest_path = output / "atlas-manifest.json"
    payload_path = output / "atlas.nq"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    analysis_id = next(row["id"] for row in manifest["graphs"] if row["role"] == "analysis")
    forged = URIRef("urn:test:atlas:forged-mapping")
    forged_lines = [
        f"<{forged}> <{RDF.type}> <{RKAF.ConceptMapping}> <{analysis_id}> .",
        f"<{forged}> <{RKAF.usageEligibility}> <{RKAF.searchOnly}> <{analysis_id}> .",
        f"<{forged}> <{ATLAS.qualifiedBy}> <urn:test:validator:missing-a> <{analysis_id}> .",
        f"<{forged}> <{ATLAS.qualifiedBy}> <urn:test:validator:missing-b> <{analysis_id}> .",
    ]
    payload = payload_path.read_text(encoding="utf-8").splitlines()
    forged_payload = ("\n".join(sorted([*payload, *forged_lines])) + "\n").encode("utf-8")
    payload_path.write_bytes(forged_payload)
    manifest["output"]["digest"] = "sha256:" + hashlib.sha256(forged_payload).hexdigest()
    manifest["output"]["byteLength"] = len(forged_payload)
    manifest["output"]["quadCount"] += len(forged_lines)
    analysis_graph = next(row for row in manifest["graphs"] if row["role"] == "analysis")
    analysis_graph["quadCount"] += len(forged_lines)
    manifest["counts"]["analysisFacts"] += len(forged_lines)
    manifest["counts"]["searchOnlyMappings"] += 1
    manifest["canonicalPayloadDigest"] = binding.canonical_payload_digest(manifest)
    manifest_path.write_text(canonical_json(manifest) + "\n", encoding="utf-8")

    with pytest.raises(VocabularyAtlasError, match="mapping source"):
        VocabularyAtlasAsset.open(
            output,
            expected_manifest_digest=_file_digest(manifest_path),
            expected_output_digest=_file_digest(payload_path),
        )


def test_queries_refuse_a_concept_mapping_that_is_not_search_only(
    tmp_path: Path,
) -> None:
    """Reading never accepts a mapping that opening would reject."""

    asset = build_vocabulary_atlas(
        _two_releases(tmp_path),
        rulespec_core=_core_release(tmp_path),
        crosswalk=_qualified_bundle(),
    )
    queries = VocabularyAtlasQueries(asset)
    assert len(queries.search_only_mappings()) == 1

    forged = URIRef("urn:test:atlas:not-search-only-mapping")
    queries._analysis.add((forged, RDF.type, RKAF.ConceptMapping))
    queries._analysis.add((forged, RKAF.usageEligibility, RKAF.notEligible))

    with pytest.raises(VocabularyAtlasError, match="contradictory eligibility"):
        queries.search_only_mappings()


def test_queries_refuse_a_search_only_mapping_with_three_machine_validations(
    tmp_path: Path,
) -> None:
    """Two independent machines is an exact count, not a floor."""

    asset = build_vocabulary_atlas(
        _two_releases(tmp_path),
        rulespec_core=_core_release(tmp_path),
        crosswalk=_qualified_bundle(),
    )
    queries = VocabularyAtlasQueries(asset)
    mapping = URIRef(queries.search_only_mappings()[0].mapping_id)

    queries._analysis.add(
        (mapping, ATLAS.qualifiedBy, URIRef("urn:test:atlas:validation:third"))
    )

    with pytest.raises(VocabularyAtlasError, match="exactly two machine validations"):
        queries.search_only_mappings()


def test_queries_refuse_a_label_cluster_that_does_not_cross_releases(
    tmp_path: Path,
) -> None:
    """Label clusters exist to cross releases; reading enforces that too."""

    asset = build_vocabulary_atlas(
        _two_releases(tmp_path),
        rulespec_core=_core_release(tmp_path),
    )
    queries = VocabularyAtlasQueries(asset)
    assert len(queries.label_clusters()) == 1

    forged = URIRef("urn:test:atlas:single-release-cluster")
    queries._analysis.add((forged, RDF.type, ATLAS.LabelCluster))
    queries._analysis.add((forged, ATLAS.normalizedLabel, Literal("single release label")))
    queries._analysis.add((forged, ATLAS.member, URIRef(SOURCE_MEMBER)))
    queries._analysis.add((forged, ATLAS.member, URIRef(TARGET_MEMBER)))
    queries._analysis.add((forged, ATLAS.memberRelease, URIRef(SOURCE_RELEASE)))

    with pytest.raises(VocabularyAtlasError, match="must cross releases"):
        queries.label_clusters()


def test_file_only_open_rejects_a_concept_mapping_that_is_not_search_only(
    tmp_path: Path,
) -> None:
    """The lax read is impossible because opening rejects the same graph."""

    release = _real_release(tmp_path)
    core = _core_release(tmp_path)
    asset = build_vocabulary_atlas((release,), rulespec_core=core)
    output = asset.write(tmp_path / "atlas")
    manifest_path = output / "atlas-manifest.json"
    payload_path = output / "atlas.nq"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    analysis_id = next(row["id"] for row in manifest["graphs"] if row["role"] == "analysis")
    forged = URIRef("urn:test:atlas:not-search-only-mapping")
    forged_lines = [
        f"<{forged}> <{RDF.type}> <{RKAF.ConceptMapping}> <{analysis_id}> .",
        f"<{forged}> <{RKAF.usageEligibility}> <{RKAF.notEligible}> <{analysis_id}> .",
    ]
    payload = payload_path.read_text(encoding="utf-8").splitlines()
    forged_payload = ("\n".join(sorted([*payload, *forged_lines])) + "\n").encode("utf-8")
    payload_path.write_bytes(forged_payload)
    manifest["output"]["digest"] = "sha256:" + hashlib.sha256(forged_payload).hexdigest()
    manifest["output"]["byteLength"] = len(forged_payload)
    manifest["output"]["quadCount"] += len(forged_lines)
    analysis_graph = next(row for row in manifest["graphs"] if row["role"] == "analysis")
    analysis_graph["quadCount"] += len(forged_lines)
    manifest["counts"]["analysisFacts"] += len(forged_lines)
    manifest["canonicalPayloadDigest"] = binding.canonical_payload_digest(manifest)
    manifest_path.write_text(canonical_json(manifest) + "\n", encoding="utf-8")

    with pytest.raises(VocabularyAtlasError, match="contradictory eligibility"):
        VocabularyAtlasAsset.open(
            output,
            expected_manifest_digest=_file_digest(manifest_path),
            expected_output_digest=_file_digest(payload_path),
        )


ALPHA_RELEASE = "urn:test:atlas:hierarchy:alpha:release"
BETA_RELEASE = "urn:test:atlas:hierarchy:beta:release"
BROADER = URIRef("http://www.w3.org/2004/02/skos/core#broader")
NARROWER = URIRef("http://www.w3.org/2004/02/skos/core#narrower")


def _hierarchy_view(
    *,
    publication: str,
    release: str,
    concepts: Mapping[str, str],
    edges: tuple[tuple[str, Any], ...] = (),
    narrower_edges: tuple[tuple[str, str], ...] = (),
    release_digest: str = SHA_A,
) -> ManagedReleaseView:
    """A managed release whose own graph states its intra-scheme hierarchy.

    ``edges`` are ``(narrower concept, broader concept)`` pairs exactly as the
    source thesaurus states them.  A broader value may be any JSON-LD node so a
    test can state a malformed one.
    """

    by_child: dict[str, list[Any]] = defaultdict(list)
    for child, parent in edges:
        by_child[child].append(parent if isinstance(parent, Mapping) else {"@id": parent})
    by_parent: dict[str, list[Any]] = defaultdict(list)
    for parent, child in narrower_edges:
        by_parent[parent].append({"@id": child})

    member_records = {}
    for member, label in concepts.items():
        record: dict[str, Any] = {
            "@id": member,
            "@type": "https://rulespec.org/ns/v1#RegisteredConcept",
            "http://www.w3.org/2004/02/skos/core#prefLabel": label,
        }
        if by_child.get(member):
            record["http://www.w3.org/2004/02/skos/core#broader"] = tuple(by_child[member])
        if by_parent.get(member):
            record["http://www.w3.org/2004/02/skos/core#narrower"] = tuple(by_parent[member])
        member_records[member] = MappingProxyType(record)

    release_record = MappingProxyType(
        {
            "@id": release,
            "@type": "https://rulespec.org/ns/v1#ReferenceResourceRelease",
            "http://www.w3.org/ns/prov#hadMember": tuple(concepts),
            "https://rulespec.org/ns/v1#referenceReleaseDigest": release_digest,
        }
    )
    members = {
        member: ManagedReleaseMember(
            member_iri=member,
            release_iri=release,
            scheme_iri=release + ":scheme",
            record=member_records[member],
        )
        for member in concepts
    }
    expressions = tuple(
        ManagedReleaseExpression(
            expression_id=member + ":expression",
            member_iri=member,
            indexed_text=label.casefold(),
            original_literal=label,
            language_tag="en",
            semantic_property_iri="http://www.w3.org/2004/02/skos/core#prefLabel",
            source_property_or_path="prefLabel",
            record=MappingProxyType({}),
            label_role="preferred",
            source_status="current",
        )
        for member, label in concepts.items()
    )
    return ManagedReleaseView(
        _release_id=publication,
        _rulespec_graph_id=publication + ":graph",
        _rulespec_graph=MappingProxyType({"@graph": (release_record, *member_records.values())}),
        _expression_corpus_snapshot=MappingProxyType({"id": publication + ":corpus", "digest": release_digest}),
        _members=MappingProxyType(members),
        _expressions=expressions,
        _relations=(),
        _lifecycle_participants=(),
        _concept_mappings=(),
        _release_graph_validation_receipt=MappingProxyType({}),
    )


ALPHA_CONCEPTS = {
    "urn:test:atlas:hierarchy:alpha:energy-policy": "Energy policy",
    "urn:test:atlas:hierarchy:alpha:renewable-energy-policy": "Renewable energy policy",
    "urn:test:atlas:hierarchy:alpha:offshore-wind-policy": "Offshore wind policy",
    "urn:test:atlas:hierarchy:alpha:marine-policy": "Marine policy",
}
ALPHA_EDGES = (
    (
        "urn:test:atlas:hierarchy:alpha:renewable-energy-policy",
        "urn:test:atlas:hierarchy:alpha:energy-policy",
    ),
    (
        "urn:test:atlas:hierarchy:alpha:offshore-wind-policy",
        "urn:test:atlas:hierarchy:alpha:renewable-energy-policy",
    ),
    (
        "urn:test:atlas:hierarchy:alpha:offshore-wind-policy",
        "urn:test:atlas:hierarchy:alpha:marine-policy",
    ),
)


def _alpha(tmp_path: Path, **overrides: Any) -> _FixturePinnedRelease:
    view = _hierarchy_view(
        publication="urn:test:atlas:hierarchy:alpha:publication",
        release=ALPHA_RELEASE,
        concepts=dict(overrides.pop("concepts", ALPHA_CONCEPTS)),
        edges=overrides.pop("edges", ALPHA_EDGES),
        **overrides,
    )
    return _FixturePinnedRelease(tmp_path / "alpha.json", SHA_A, view)


def _beta(tmp_path: Path) -> _FixturePinnedRelease:
    view = _hierarchy_view(
        publication="urn:test:atlas:hierarchy:beta:publication",
        release=BETA_RELEASE,
        concepts={"urn:test:atlas:hierarchy:beta:energy-policy": "Beta energy policy"},
        release_digest=SHA_B,
    )
    return _FixturePinnedRelease(tmp_path / "beta.json", SHA_B, view)


def _release_facts(asset: VocabularyAtlasAsset) -> Any:
    dataset = Dataset(default_union=False)
    dataset.parse(data=asset.payload.decode("utf-8"), format="nquads")
    row = next(item for item in asset.manifest["graphs"] if item["role"] == "releaseFacts")
    return dataset.graph(URIRef(row["id"]))


def test_source_hierarchy_is_published_as_release_layer_facts(tmp_path: Path) -> None:
    """Broader edges are layer-1 source facts, so they ride in release facts."""

    asset = build_vocabulary_atlas((_alpha(tmp_path),), rulespec_core=_core_release(tmp_path))

    graph = _release_facts(asset)
    assert set(graph.subject_objects(BROADER)) == {
        (URIRef(child), URIRef(parent)) for child, parent in ALPHA_EDGES
    }
    assert asset.manifest["counts"]["hierarchyEdges"] == len(ALPHA_EDGES)


def test_only_the_broader_direction_is_stored(tmp_path: Path) -> None:
    """One stored direction cannot disagree with its own inverse."""

    asset = build_vocabulary_atlas((_alpha(tmp_path),), rulespec_core=_core_release(tmp_path))

    assert not set(_release_facts(asset).subject_objects(NARROWER))


def test_a_release_without_hierarchy_declares_no_hierarchy_count(tmp_path: Path) -> None:
    """Absent means zero, so every hierarchy-free atlas stays byte-identical."""

    source, _ = _two_releases(tmp_path)
    asset = build_vocabulary_atlas((source,), rulespec_core=_core_release(tmp_path))

    assert "hierarchyEdges" not in asset.manifest["counts"]
    assert not set(_release_facts(asset).subject_objects(BROADER))


def test_a_verified_relation_row_publishes_its_edge_as_two_concept_iris(
    tmp_path: Path,
) -> None:
    """A compact source context leaves the object a literal on a generic parse.

    The normalized ``concept_relations`` rows are the verified form of exactly
    those edges, so the distribution publishes what they round-trip to rather
    than a string that no consumer could follow.
    """

    asset = build_vocabulary_atlas((_real_release(tmp_path),), rulespec_core=_core_release(tmp_path))

    assert set(_release_facts(asset).subject_objects(BROADER)) == {
        (
            URIRef("urn:rkaf:fixture:concept:income"),
            URIRef("urn:rkaf:fixture:concept:eligibility"),
        )
    }
    assert asset.manifest["counts"]["hierarchyEdges"] == 1
    assert VocabularyAtlasQueries(asset).narrower("urn:rkaf:fixture:concept:eligibility") == (
        "urn:rkaf:fixture:concept:income",
    )


def test_broader_and_narrower_read_the_one_stored_edge_from_both_ends(tmp_path: Path) -> None:
    asset = build_vocabulary_atlas((_alpha(tmp_path),), rulespec_core=_core_release(tmp_path))
    queries = VocabularyAtlasQueries(asset)

    assert queries.broader("urn:test:atlas:hierarchy:alpha:renewable-energy-policy") == (
        "urn:test:atlas:hierarchy:alpha:energy-policy",
    )
    assert queries.narrower("urn:test:atlas:hierarchy:alpha:energy-policy") == (
        "urn:test:atlas:hierarchy:alpha:renewable-energy-policy",
    )
    assert queries.broader("urn:test:atlas:hierarchy:alpha:energy-policy") == ()
    assert queries.hierarchy_edges() == tuple(sorted(ALPHA_EDGES))


def test_a_concept_may_have_more_than_one_broader_concept(tmp_path: Path) -> None:
    """ELSST R6 places 162 concepts under two or more parents."""

    asset = build_vocabulary_atlas((_alpha(tmp_path),), rulespec_core=_core_release(tmp_path))
    queries = VocabularyAtlasQueries(asset)

    assert queries.broader("urn:test:atlas:hierarchy:alpha:offshore-wind-policy") == (
        "urn:test:atlas:hierarchy:alpha:marine-policy",
        "urn:test:atlas:hierarchy:alpha:renewable-energy-policy",
    )


def test_transitive_broader_walks_every_parent_within_the_depth_bound(tmp_path: Path) -> None:
    asset = build_vocabulary_atlas((_alpha(tmp_path),), rulespec_core=_core_release(tmp_path))
    queries = VocabularyAtlasQueries(asset)

    assert queries.transitive_broader(
        "urn:test:atlas:hierarchy:alpha:offshore-wind-policy", max_depth=1
    ) == (
        "urn:test:atlas:hierarchy:alpha:marine-policy",
        "urn:test:atlas:hierarchy:alpha:renewable-energy-policy",
    )
    assert queries.transitive_broader(
        "urn:test:atlas:hierarchy:alpha:offshore-wind-policy", max_depth=2
    ) == (
        "urn:test:atlas:hierarchy:alpha:energy-policy",
        "urn:test:atlas:hierarchy:alpha:marine-policy",
        "urn:test:atlas:hierarchy:alpha:renewable-energy-policy",
    )


def test_transitive_broader_requires_a_positive_depth_bound(tmp_path: Path) -> None:
    asset = build_vocabulary_atlas((_alpha(tmp_path),), rulespec_core=_core_release(tmp_path))
    queries = VocabularyAtlasQueries(asset)

    with pytest.raises(VocabularyAtlasError, match="depth bound"):
        queries.transitive_broader("urn:test:atlas:hierarchy:alpha:offshore-wind-policy", max_depth=0)


def test_broader_across_two_releases_is_refused_because_mappings_carry_it(tmp_path: Path) -> None:
    """A cross-scheme claim needs the qualification proof, not a copied edge."""

    alpha = _alpha(
        tmp_path,
        edges=(
            (
                "urn:test:atlas:hierarchy:alpha:renewable-energy-policy",
                "urn:test:atlas:hierarchy:beta:energy-policy",
            ),
        ),
    )
    with pytest.raises(VocabularyAtlasError, match="hierarchy must stay inside one release"):
        build_vocabulary_atlas((alpha, _beta(tmp_path)), rulespec_core=_core_release(tmp_path))


def test_broader_to_a_non_member_is_refused(tmp_path: Path) -> None:
    alpha = _alpha(
        tmp_path,
        edges=(
            (
                "urn:test:atlas:hierarchy:alpha:renewable-energy-policy",
                "urn:test:atlas:hierarchy:alpha:absent-concept",
            ),
        ),
    )
    with pytest.raises(VocabularyAtlasError, match="hierarchy endpoint is not a release member"):
        build_vocabulary_atlas((alpha,), rulespec_core=_core_release(tmp_path))


def test_a_concept_cannot_be_broader_than_itself(tmp_path: Path) -> None:
    alpha = _alpha(
        tmp_path,
        edges=(
            (
                "urn:test:atlas:hierarchy:alpha:renewable-energy-policy",
                "urn:test:atlas:hierarchy:alpha:renewable-energy-policy",
            ),
        ),
    )
    with pytest.raises(VocabularyAtlasError, match="hierarchy edge repeats one concept"):
        build_vocabulary_atlas((alpha,), rulespec_core=_core_release(tmp_path))


def test_a_hierarchy_cycle_is_refused(tmp_path: Path) -> None:
    """ELSST R5 and R6 are both acyclic, so a cycle is a source defect."""

    alpha = _alpha(
        tmp_path,
        edges=(
            *ALPHA_EDGES,
            (
                "urn:test:atlas:hierarchy:alpha:energy-policy",
                "urn:test:atlas:hierarchy:alpha:offshore-wind-policy",
            ),
        ),
    )
    with pytest.raises(VocabularyAtlasError, match="hierarchy contains a cycle"):
        build_vocabulary_atlas((alpha,), rulespec_core=_core_release(tmp_path))


def test_a_stored_narrower_statement_is_refused(tmp_path: Path) -> None:
    """The inverse is derived; storing it invites the two to disagree."""

    alpha = _alpha(
        tmp_path,
        edges=(),
        narrower_edges=(
            (
                "urn:test:atlas:hierarchy:alpha:energy-policy",
                "urn:test:atlas:hierarchy:alpha:renewable-energy-policy",
            ),
        ),
    )
    with pytest.raises(VocabularyAtlasError, match="narrower is derived, never stored"):
        build_vocabulary_atlas((alpha,), rulespec_core=_core_release(tmp_path))


def test_broader_must_connect_two_concept_iris(tmp_path: Path) -> None:
    alpha = _alpha(
        tmp_path,
        edges=(
            (
                "urn:test:atlas:hierarchy:alpha:renewable-energy-policy",
                {"@value": "Energy policy"},
            ),
        ),
    )
    with pytest.raises(VocabularyAtlasError, match="hierarchy must connect two concept IRIs"):
        build_vocabulary_atlas((alpha,), rulespec_core=_core_release(tmp_path))


def _write_forged_hierarchy(tmp_path: Path, edit: Any) -> tuple[Path, Path, Path]:
    """Publish the valid hierarchy atlas, then reseal one forged line into it."""

    asset = build_vocabulary_atlas((_alpha(tmp_path),), rulespec_core=_core_release(tmp_path))
    output = asset.write(tmp_path / "atlas")
    manifest_path = output / "atlas-manifest.json"
    payload_path = output / "atlas.nq"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    lines = payload_path.read_text(encoding="utf-8").splitlines()
    forged = sorted(edit(lines, manifest))
    payload = ("\n".join(forged) + "\n").encode("utf-8")
    payload_path.write_bytes(payload)
    release_id = next(row["id"] for row in manifest["graphs"] if row["role"] == "releaseFacts")
    analysis_id = next(row["id"] for row in manifest["graphs"] if row["role"] == "analysis")
    release_quads = sum(1 for line in forged if line.endswith(f"<{release_id}> ."))
    analysis_quads = sum(1 for line in forged if line.endswith(f"<{analysis_id}> ."))
    for row in manifest["graphs"]:
        row["quadCount"] = release_quads if row["role"] == "releaseFacts" else analysis_quads
    manifest["counts"]["releaseFacts"] = release_quads
    manifest["counts"]["analysisFacts"] = analysis_quads
    manifest["output"]["digest"] = "sha256:" + hashlib.sha256(payload).hexdigest()
    manifest["output"]["byteLength"] = len(payload)
    manifest["output"]["quadCount"] = len(forged)
    manifest.pop("canonicalPayloadDigest")
    manifest["canonicalPayloadDigest"] = binding.canonical_payload_digest(manifest)
    manifest_path.write_text(canonical_json(manifest) + "\n", encoding="utf-8")
    return output, manifest_path, payload_path


def test_file_only_open_refuses_a_forged_dangling_broader(tmp_path: Path) -> None:
    """The consumer check stands alone; it never reopens producer inputs."""

    def _retarget(lines: list[str], manifest: Mapping[str, Any]) -> list[str]:
        marker = f"<{BROADER}> <urn:test:atlas:hierarchy:alpha:energy-policy>"
        edited = [
            line.replace(marker, f"<{BROADER}> <urn:test:atlas:hierarchy:alpha:absent-concept>")
            if marker in line
            else line
            for line in lines
        ]
        assert edited != lines
        return edited

    output, manifest_path, payload_path = _write_forged_hierarchy(tmp_path, _retarget)
    with pytest.raises(VocabularyAtlasError, match="hierarchy endpoint is not a release member"):
        VocabularyAtlasAsset.open(
            output,
            expected_manifest_digest=_file_digest(manifest_path),
            expected_output_digest=_file_digest(payload_path),
        )


def test_file_only_open_refuses_a_hierarchy_count_that_does_not_match(tmp_path: Path) -> None:
    def _drop_one(lines: list[str], manifest: Mapping[str, Any]) -> list[str]:
        kept = [line for line in lines if f"<{BROADER}>" not in line]
        assert len(kept) == len(lines) - len(ALPHA_EDGES)
        return kept

    output, manifest_path, payload_path = _write_forged_hierarchy(tmp_path, _drop_one)
    with pytest.raises(VocabularyAtlasError, match="declared counts differ"):
        VocabularyAtlasAsset.open(
            output,
            expected_manifest_digest=_file_digest(manifest_path),
            expected_output_digest=_file_digest(payload_path),
        )
