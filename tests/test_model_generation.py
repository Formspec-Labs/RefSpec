from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

from refspec.binding import TYPE_SCHEMAS

REFSPEC_ROOT = Path(__file__).resolve().parents[1]
MODEL_PATH = REFSPEC_ROOT / "model" / "ref-records.cue"
ARTIFACT_MANIFEST = REFSPEC_ROOT / "model" / "generated-artifacts.json"
GENERATOR_PATH = REFSPEC_ROOT / "tools" / "generate_model.py"
GENERATOR_SPEC = importlib.util.spec_from_file_location("_refspec_model_generator", GENERATOR_PATH)
assert GENERATOR_SPEC is not None and GENERATOR_SPEC.loader is not None
GENERATOR = importlib.util.module_from_spec(GENERATOR_SPEC)
GENERATOR_SPEC.loader.exec_module(GENERATOR)
artifact_bytes = GENERATOR.artifact_bytes
load_model = GENERATOR.load_model


def test_authoritative_model_generates_without_drift() -> None:
    result = subprocess.run(
        [sys.executable, str(GENERATOR_PATH), "--check"],
        cwd=REFSPEC_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert "generation is idempotent" in result.stdout


def test_generated_manifest_binds_every_artifact_to_the_model() -> None:
    model_bytes = MODEL_PATH.read_bytes()
    model = load_model(MODEL_PATH)
    artifacts = artifact_bytes(model, model_bytes)
    manifest = json.loads(ARTIFACT_MANIFEST.read_text(encoding="utf-8"))

    assert manifest["sourceSha256"] == f"sha256:{hashlib.sha256(model_bytes).hexdigest()}"
    assert set(manifest["artifacts"]) == set(artifacts) - {"model/generated-artifacts.json"}
    for relative, expected in manifest["artifacts"].items():
        assert expected == f"sha256:{hashlib.sha256((REFSPEC_ROOT / relative).read_bytes()).hexdigest()}"


def test_every_dispatched_ref_record_is_generated_from_the_model() -> None:
    model = load_model(MODEL_PATH)
    schemas = model["schemas"]

    assert set(TYPE_SCHEMAS.values()) <= set(schemas)
    dispatch = schemas["ref-record.schema.json"]
    dispatched = {branch["$ref"] for branch in dispatch["oneOf"]}
    assert dispatched == set(TYPE_SCHEMAS.values())
