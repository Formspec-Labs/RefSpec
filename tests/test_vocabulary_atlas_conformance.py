"""Portable vocabulary-atlas schema and static conformance corpus."""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator

from refspec.atlas import VocabularyAtlasAsset, VocabularyAtlasError

_REPO_ROOT = Path(__file__).parents[1]
_BINDING_ROOT = _REPO_ROOT / "bindings" / "atlas" / "1.0"
_FIXTURE_ROOT = _BINDING_ROOT / "fixtures"
_CORPUS = json.loads((_FIXTURE_ROOT / "corpus.json").read_text(encoding="utf-8"))


def _digest(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def test_atlas_manifest_schema_is_valid_and_producer_neutral() -> None:
    schema = json.loads(
        (_BINDING_ROOT / "schemas" / "vocabulary-atlas-manifest.schema.json").read_text(encoding="utf-8")
    )
    Draft202012Validator.check_schema(schema)
    runtime = schema["$defs"]["implementation"]["properties"]["runtime"]
    assert runtime == {
        "additionalProperties": {"minLength": 1, "type": "string"},
        "minProperties": 1,
        "propertyNames": {"minLength": 1},
        "type": "object",
    }


def test_atlas_manifest_schema_bounds_integers_to_the_interoperable_range() -> None:
    schema = json.loads(
        (_BINDING_ROOT / "schemas" / "vocabulary-atlas-manifest.schema.json").read_text(encoding="utf-8")
    )

    assert schema["$defs"]["nonnegativeInteger"] == {
        "maximum": 9007199254740991,
        "minimum": 0,
        "type": "integer",
    }
    assert schema["$defs"]["positiveInteger"] == {
        "maximum": 9007199254740991,
        "minimum": 1,
        "type": "integer",
    }

    validator = Draft202012Validator(schema)
    manifest = json.loads(
        (_FIXTURE_ROOT / "valid" / "minimal" / "atlas-manifest.json").read_text(encoding="utf-8")
    )
    assert validator.is_valid(manifest)

    manifest["output"]["byteLength"] = 9007199254740992
    assert not validator.is_valid(manifest)


def test_generated_conformance_distributions_are_current() -> None:
    """The non-vacuous distributions are tooling output, not hand-edited bytes."""

    result = subprocess.run(
        [sys.executable, "tools/generate_atlas_conformance_fixtures.py"],
        cwd=_REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize("case", _CORPUS["cases"], ids=lambda case: case["id"])
def test_static_atlas_conformance_corpus(case: dict[str, Any]) -> None:
    directory = _FIXTURE_ROOT / case["directory"]
    manifest_path = directory / "atlas-manifest.json"
    output_path = directory / "atlas.nq"
    assert {path.name for path in directory.iterdir()} == {
        "atlas-manifest.json",
        "atlas.nq",
    }
    assert _digest(manifest_path) == case["manifestDigest"]
    assert _digest(output_path) == case["outputDigest"]

    schema = json.loads(
        (_BINDING_ROOT / "schemas" / "vocabulary-atlas-manifest.schema.json").read_text(encoding="utf-8")
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    Draft202012Validator(schema).validate(manifest)

    if case["valid"]:
        asset = VocabularyAtlasAsset.open(
            directory,
            expected_manifest_digest=case["manifestDigest"],
            expected_output_digest=case["outputDigest"],
        )
        assert asset.manifest_digest == case["manifestDigest"]
        assert asset.output_digest == case["outputDigest"]
        return

    with pytest.raises(VocabularyAtlasError, match=re.escape(case["errorContains"])):
        VocabularyAtlasAsset.open(
            directory,
            expected_manifest_digest=case["manifestDigest"],
            expected_output_digest=case["outputDigest"],
        )
