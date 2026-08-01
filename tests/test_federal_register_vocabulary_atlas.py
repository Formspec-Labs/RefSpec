"""Complete-package proof for the 2025 Federal Register atlas adapter."""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path

import pytest
from rdflib import Dataset, Literal, URIRef
from rdflib.namespace import PROV, RDF

import refspec.atlas.model as atlas_model
import refspec.registry.federal_register_thesaurus_2025_managed_release as managed_release_module
from refspec.atlas import (
    FEDERAL_REGISTER_THESAURUS_2025_REFERENCE_RELEASE_IRI,
    RKAF,
    PinnedFederalRegisterThesaurus2025AtlasRelease,
    PinnedRulespecCoreRelease,
    VocabularyAtlasAsset,
    build_vocabulary_atlas,
)
from refspec.atlas.cli import main as atlas_main
from refspec.managed_release import ManagedReleaseError
from refspec.registry.federal_register_thesaurus_2025 import (
    load_packaged_federal_register_thesaurus_2025,
)
from refspec.registry.federal_register_thesaurus_2025_managed_release import (
    build_federal_register_thesaurus_2025_managed_release,
)
from refspec.registry.federal_register_vocabulary_policy import (
    load_federal_register_thesaurus_crosswalk,
)
from refspec.storage import canonical_json

_EXAMPLE_MANIFEST_DIGEST = "sha256:956cab4f20477933ef015c2c87647ebb9cc40c4c68247a93b10dab8b113f60f1"
_EXAMPLE_OUTPUT_DIGEST = "sha256:8e1eaf2265874863981fe9322e0a0e286c01c43e598b091736b556ea424e830a"
_REFERENCE_RELEASE_DIGEST = "sha256:30742a82b3e268942aec713a02c5ae4264eadea36aa61b564ffc93eeecfd5fe6"
_RESOURCE_ROOT = (
    Path(__file__).parents[1] / "src" / "refspec" / "resources" / "federal_register_thesaurus" / "2025-04-01"
)
_EXAMPLE_ROOT = (
    Path(__file__).parents[1] / "bindings" / "atlas" / "1.0" / "examples" / "federal-register-thesaurus-2025"
)


def _file_digest(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _core_release(tmp_path: Path) -> PinnedRulespecCoreRelease:
    preimage = {
        "record_type": "RulespecCoreRelease",
        "release_status": "fixture",
        "version": "0.2.0-pre.9+test-fixture",
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
    digest = "sha256:" + hashlib.sha256(canonical_json(preimage).encode()).hexdigest()
    release_id = "urn:rulespec:core:" + digest.removeprefix("sha256:")
    path = tmp_path / "rulespec-core.json"
    path.write_text(
        json.dumps(
            {**preimage, "release_digest": digest, "release_id": release_id},
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    return PinnedRulespecCoreRelease.open(
        path,
        expected_file_digest=_file_digest(path),
        expected_release_id=release_id,
        expected_release_digest=digest,
    )


def _complete_package(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Path:
    source_pdf = b"%PDF-1.7\ncomplete-705-concept-fixture\n"
    actual_sha256 = managed_release_module._sha256_bytes

    def fixture_sha256(payload: bytes) -> str:
        if payload == source_pdf:
            return managed_release_module.FEDERAL_REGISTER_THESAURUS_2025_SHA256
        return actual_sha256(payload)

    monkeypatch.setattr(managed_release_module, "_sha256_bytes", fixture_sha256)
    checked = load_packaged_federal_register_thesaurus_2025()
    parsed = replace(checked, source_artifact_bytes=source_pdf)
    crosswalk = load_federal_register_thesaurus_crosswalk((_RESOURCE_ROOT / "crosswalk-1995-to-2025.json").read_bytes())
    release = build_federal_register_thesaurus_2025_managed_release(
        parsed,
        crosswalk,
        recorded_at="2026-07-31T00:00:00Z",
        recorded_by="urn:ref:actor:atlas-complete-package-test",
    )
    return release.write_to(tmp_path / "managed")["managed-release.json"]


def test_complete_2025_package_builds_one_portable_705_member_atlas(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest_path = _complete_package(tmp_path, monkeypatch)
    source = PinnedFederalRegisterThesaurus2025AtlasRelease.open(
        manifest_path,
        expected_manifest_digest=_file_digest(manifest_path),
    )
    view = source.verified_view()
    members = tuple(view.iter_members())
    expressions = tuple(view.iter_expressions())
    safety = next(
        member
        for member in members
        if member.record["http://www.w3.org/2004/02/skos/core#prefLabel"]["@value"] == "Safety"
    )

    assert len(members) == 705
    assert len(expressions) == 705 + 433
    assert safety.release_iri == FEDERAL_REGISTER_THESAURUS_2025_REFERENCE_RELEASE_IRI
    assert view.lookup_member(safety.member_iri) == safety

    asset = build_vocabulary_atlas((source,), rulespec_core=_core_release(tmp_path))
    output = asset.write(tmp_path / "atlas")
    reopened = VocabularyAtlasAsset.open(
        output,
        expected_manifest_digest=asset.manifest_digest,
        expected_output_digest=asset.output_digest,
    )
    release_graph_id = next(row["id"] for row in reopened.manifest["graphs"] if row["role"] == "releaseFacts")
    dataset = Dataset(default_union=False)
    dataset.parse(data=reopened.payload.decode("utf-8"), format="nquads")
    release_graph = dataset.graph(URIRef(release_graph_id))
    release = URIRef(FEDERAL_REGISTER_THESAURUS_2025_REFERENCE_RELEASE_IRI)

    assert len(set(release_graph.objects(release, PROV.hadMember))) == 705
    assert (
        release,
        RKAF.referenceReleaseDigest,
        Literal(_REFERENCE_RELEASE_DIGEST),
    ) in release_graph
    assert (
        URIRef(safety.member_iri),
        RDF.type,
        RKAF.RegisteredConcept,
    ) in release_graph

    reproduced = VocabularyAtlasAsset.reproduce_from_inputs(
        output,
        releases=(source,),
        rulespec_core=_core_release(tmp_path),
        expected_manifest_digest=asset.manifest_digest,
        expected_output_digest=asset.output_digest,
    )
    assert reproduced.payload == asset.payload


def _atlas_command(manifest_path: Path, core: PinnedRulespecCoreRelease, output: Path) -> tuple[str, ...]:
    return (
        "--managed-release",
        str(manifest_path),
        _file_digest(manifest_path),
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


def test_advertised_command_builds_the_complete_2025_package(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    manifest_path = _complete_package(tmp_path, monkeypatch)
    core = _core_release(tmp_path)
    output = tmp_path / "cli-atlas"

    assert atlas_main(_atlas_command(manifest_path, core, output)) == 0

    selection = json.loads(capsys.readouterr().out)
    reopened = VocabularyAtlasAsset.open(
        output,
        expected_manifest_digest=selection["manifestDigest"],
        expected_output_digest=selection["outputDigest"],
    )
    release_graph_id = next(row["id"] for row in reopened.manifest["graphs"] if row["role"] == "releaseFacts")
    dataset = Dataset(default_union=False)
    dataset.parse(data=reopened.payload.decode("utf-8"), format="nquads")
    release_graph = dataset.graph(URIRef(release_graph_id))
    release = URIRef(FEDERAL_REGISTER_THESAURUS_2025_REFERENCE_RELEASE_IRI)

    assert selection["assetId"] == reopened.manifest["id"]
    assert len(set(release_graph.objects(release, PROV.hadMember))) == 705


def test_advertised_command_accepts_the_explicit_specialized_input_format(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    manifest_path = _complete_package(tmp_path, monkeypatch)
    core = _core_release(tmp_path)
    output = tmp_path / "cli-atlas"

    assert (
        atlas_main(
            (
                *_atlas_command(manifest_path, core, output),
                "--input-format",
                "federal-register-thesaurus-2025",
            )
        )
        == 0
    )

    selection = json.loads(capsys.readouterr().out)
    assert selection["outputDirectory"] == str(output.resolve())


def test_advertised_command_fails_closed_when_the_wrong_reader_is_forced(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest_path = _complete_package(tmp_path, monkeypatch)
    core = _core_release(tmp_path)
    output = tmp_path / "cli-atlas"

    with pytest.raises(ManagedReleaseError, match="bundle manifest contains unsupported fields"):
        atlas_main(
            (
                *_atlas_command(manifest_path, core, output),
                "--input-format",
                "managed-bundle",
            )
        )


def test_specialized_adapter_rejects_the_retired_rulespec_validator_input(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest_path = _complete_package(tmp_path, monkeypatch)
    with pytest.raises(TypeError, match="validator"):
        PinnedFederalRegisterThesaurus2025AtlasRelease.open(
            manifest_path,
            expected_manifest_digest=_file_digest(manifest_path),
            validator=object(),  # type: ignore[call-arg]
        )


def test_generation_identity_pins_specialized_code_and_rdflib_drift(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = atlas_model._implementation_pin()
    modules = {row["path"]: row["digest"] for row in original["sourceModules"]}
    required = {
        "refspec/atlas/federal_register.py",
        "refspec/immutable.py",
        "refspec/registry/federal_register_thesaurus.py",
        "refspec/registry/federal_register_thesaurus_2025.py",
        "refspec/registry/federal_register_thesaurus_2025_managed_release.py",
        "refspec/registry/federal_register_vocabulary_policy.py",
    }
    assert required <= set(modules)
    for relative in required:
        assert modules[relative] == _file_digest(
            Path(atlas_model.__file__).parents[1] / relative.removeprefix("refspec/")
        )

    original_version = atlas_model.importlib.metadata.version

    def drifted_version(distribution: str) -> str:
        if distribution == "rdflib":
            return "drifted-test-version"
        return original_version(distribution)

    monkeypatch.setattr(atlas_model.importlib.metadata, "version", drifted_version)
    drifted_runtime = atlas_model._implementation_pin()
    assert atlas_model._digest_value(original) != atlas_model._digest_value(drifted_runtime)


def test_generation_identity_changes_when_specialized_source_bytes_drift(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = atlas_model._implementation_pin()
    federal_register_path = Path(atlas_model.__file__).with_name("federal_register.py").resolve()
    read_bytes = Path.read_bytes

    def drifted_bytes(path: Path) -> bytes:
        payload = read_bytes(path)
        if path.resolve() == federal_register_path:
            return payload + b"\n# adversarial source drift\n"
        return payload

    monkeypatch.setattr(Path, "read_bytes", drifted_bytes)
    drifted_source = atlas_model._implementation_pin()
    assert atlas_model._digest_value(original) != atlas_model._digest_value(drifted_source)


def test_checked_complete_2025_atlas_opens_from_only_its_two_file_pins() -> None:
    assert {path.name for path in _EXAMPLE_ROOT.iterdir()} == {
        "atlas-manifest.json",
        "atlas.nq",
    }
    asset = VocabularyAtlasAsset.open(
        _EXAMPLE_ROOT,
        expected_manifest_digest=_EXAMPLE_MANIFEST_DIGEST,
        expected_output_digest=_EXAMPLE_OUTPUT_DIGEST,
    )
    assert asset.manifest["id"] == (
        "urn:ref:vocabulary-atlas:9069a26d36c2695a02edb501dc51011f48aee382d96a0e200cd2c1d3574d7dec"
    )
    assert asset.manifest["counts"]["managedReleases"] == 1
    assert asset.manifest["counts"]["releaseFacts"] == 4719

    release_graph_id = next(row["id"] for row in asset.manifest["graphs"] if row["role"] == "releaseFacts")
    dataset = Dataset(default_union=False)
    dataset.parse(data=asset.payload.decode("utf-8"), format="nquads")
    graph = dataset.graph(URIRef(release_graph_id))
    release = URIRef(FEDERAL_REGISTER_THESAURUS_2025_REFERENCE_RELEASE_IRI)
    members = set(graph.objects(release, PROV.hadMember))
    safety = URIRef("urn:ref:federal-register-thesaurus:2025-04-01:concept:0570")

    assert len(members) == 705
    assert safety in members
    assert (
        release,
        RKAF.referenceReleaseDigest,
        Literal(_REFERENCE_RELEASE_DIGEST),
    ) in graph
    assert (
        safety,
        URIRef("http://www.w3.org/2004/02/skos/core#prefLabel"),
        Literal("Safety", lang="en"),
    ) in graph
