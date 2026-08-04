"""Executable REF-TEST-172 mutations for the Rulespec dependency pin."""

from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path
from types import ModuleType

import pytest

REFSPEC_ROOT = Path(__file__).resolve().parents[1]
GATE_PATH = REFSPEC_ROOT / "bindings" / "json" / "1.0" / "tools" / "validate_rulespec_gate.py"
DEPENDENCY_MANIFEST = REFSPEC_ROOT / "profiles" / "rulespec-dependency.json"


def load_gate_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("refspec_rulespec_dependency_gate", GATE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


gate = load_gate_module()


@pytest.fixture
def dependency_manifest() -> dict:
    return json.loads(DEPENDENCY_MANIFEST.read_text(encoding="utf-8"))


@pytest.fixture
def rulespec_dir(
    tmp_path: Path,
    dependency_manifest: dict,
) -> Path:
    """Materialize only the local paths needed by mutation diagnostics."""

    root = tmp_path / "rulespec-inputs"
    for relative in dependency_manifest["adoptedConstraintSources"]:
        path = root / relative
        if Path(relative).suffix:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("test input\n", encoding="utf-8")
        else:
            path.mkdir(parents=True, exist_ok=True)
    paths = [
        dependency_manifest["validator"]["selfCertificationPath"],
        *dependency_manifest["generatedArtifacts"],
    ]
    for relative in paths:
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("test input\n", encoding="utf-8")
    (root / "VERSION").write_text(
        dependency_manifest["rulespecVersion"] + "\n",
        encoding="utf-8",
    )
    return root


def write_manifest(path: Path, manifest: dict) -> Path:
    path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return path


def mock_expensive_digests(
    monkeypatch: pytest.MonkeyPatch,
    manifest: dict,
) -> None:
    monkeypatch.setattr(
        gate,
        "current_contract_digest",
        lambda rulespec_dir: (manifest["constraintDigest"], None),
    )
    monkeypatch.setattr(
        gate,
        "current_corpus_digest",
        lambda rulespec_dir: (manifest["conformanceCorpusDigest"], None),
    )
    generated = manifest["generatedArtifacts"]
    certification_path = manifest["validator"]["selfCertificationPath"]

    def pinned_digest(path: Path) -> str:
        normalized = path.as_posix()
        if normalized.endswith(certification_path):
            return manifest["validator"]["selfCertificationSha256"]
        for relative, digest in generated.items():
            if normalized.endswith(relative):
                return digest
        raise AssertionError(f"unexpected digest path: {path}")

    monkeypatch.setattr(gate, "sha256_file", pinned_digest)


def apply_mutation(manifest: dict, mutation: str) -> None:
    if mutation == "contract_revision":
        manifest["contractRevision"] = "f" * 40
    elif mutation == "evidence_revision":
        manifest["evidenceRevision"] = "f" * 40
    elif mutation == "constraint_digest":
        manifest["constraintDigest"] = "sha256:" + ("0" * 64)
    elif mutation == "corpus_digest":
        manifest["conformanceCorpusDigest"] = "sha256:" + ("0" * 64)
    elif mutation == "validator_receipt_digest":
        manifest["validator"]["selfCertificationSha256"] = "0" * 64
    elif mutation == "generated_artifact_digest":
        artifact = next(iter(manifest["generatedArtifacts"]))
        manifest["generatedArtifacts"][artifact] = "0" * 64
    elif mutation == "release_availability_contradiction":
        manifest["releaseAvailability"] = "published"
        manifest["productionConformanceEligible"] = False
    else:
        raise AssertionError(f"unknown mutation {mutation}")


@pytest.mark.parametrize(
    ("mutation", "expected_error"),
    [
        (
            "contract_revision",
            "application profile 'Tested contract revision' does not match dependency manifest",
        ),
        (
            "evidence_revision",
            "application profile 'Vocabulary-closure revision' does not match dependency manifest",
        ),
        (
            "constraint_digest",
            "application profile 'Vocabulary-closure constraint digest' does not match dependency manifest",
        ),
        ("corpus_digest", "Rulespec conformance-corpus digest"),
        ("validator_receipt_digest", "Rulespec self-certification digest"),
        ("generated_artifact_digest", "generated Rulespec artifact"),
        (
            "release_availability_contradiction",
            "productionConformanceEligible must be true exactly when releaseAvailability is published",
        ),
    ],
)
def test_ref_test_172_rejects_dependency_manifest_mutations(
    mutation: str,
    expected_error: str,
    dependency_manifest: dict,
    monkeypatch: pytest.MonkeyPatch,
    rulespec_dir: Path,
    tmp_path: Path,
) -> None:
    baseline = copy.deepcopy(dependency_manifest)
    mutated = copy.deepcopy(dependency_manifest)
    apply_mutation(mutated, mutation)
    manifest_path = write_manifest(tmp_path / f"{mutation}.json", mutated)
    mock_expensive_digests(monkeypatch, baseline)

    errors = gate.validate_closure_pin(
        rulespec_dir,
        dependency_manifest_path=manifest_path,
    )

    assert any(expected_error in error for error in errors), errors


def test_ref_test_172_rejects_stale_normative_pin_text(
    dependency_manifest: dict,
    monkeypatch: pytest.MonkeyPatch,
    rulespec_dir: Path,
    tmp_path: Path,
) -> None:
    mock_expensive_digests(monkeypatch, dependency_manifest)
    pin_root = tmp_path / "pin-text"
    mutation_target = "spec/refspec.md"
    assert mutation_target in dependency_manifest["pinTextFiles"]
    for relative in dependency_manifest["pinTextFiles"]:
        source = REFSPEC_ROOT / relative
        target = pin_root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        text = source.read_text(encoding="utf-8")
        if relative == mutation_target:
            text = text.replace(
                dependency_manifest["rulespecVersion"],
                "0.2.0-pre.8",
            )
        target.write_text(text, encoding="utf-8")

    errors = gate.validate_closure_pin(
        rulespec_dir,
        refspec_root=pin_root,
    )

    assert any(
        "spec/refspec.md contains Rulespec versions ['0.2.0-pre.8'], expected only '0.2.0-pre.9'" in error
        for error in errors
    ), errors
