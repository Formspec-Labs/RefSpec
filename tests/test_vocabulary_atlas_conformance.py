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

from refspec.atlas import (
    VocabularyAtlasAsset,
    VocabularyAtlasError,
    VocabularyAtlasQueries,
)

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


def test_the_corpus_proves_the_qualification_path_can_pass() -> None:
    """A corpus of refusals says nothing about the gate a producer must pass.

    Every valid distribution published before this one carried zero mapping
    candidates, so a reader could accept the whole corpus without ever
    executing the `searchOnly` proof.
    """

    counts = {
        case["directory"]: json.loads(
            (_FIXTURE_ROOT / case["directory"] / "atlas-manifest.json").read_text(
                encoding="utf-8"
            )
        )["counts"]
        for case in _CORPUS["cases"]
        if case["valid"]
    }
    non_vacuous = {
        directory: count
        for directory, count in counts.items()
        if count["searchOnlyMappings"] > 0
    }

    assert non_vacuous, "no valid distribution exercises the searchOnly gate"
    for count in non_vacuous.values():
        assert count["mappingCandidates"] >= 2
        assert count["machineValidations"] >= 3


def test_the_qualified_fixture_qualifies_one_candidate_and_refuses_the_other() -> None:
    """The fixture proves both outcomes, or it only proves the gate is open."""

    directory = _FIXTURE_ROOT / "valid" / "qualified-search-only"
    case = next(
        item
        for item in _CORPUS["cases"]
        if item["directory"] == "valid/qualified-search-only"
    )
    asset = VocabularyAtlasAsset.open(
        directory,
        expected_manifest_digest=case["manifestDigest"],
        expected_output_digest=case["outputDigest"],
    )
    queries = VocabularyAtlasQueries(asset)

    mappings = queries.search_only_mappings()
    assert len(mappings) == 1
    assert asset.manifest["counts"]["mappingCandidates"] == 2
    assert asset.manifest["counts"]["searchOnlyMappings"] == 1

    nquads = asset.payload.decode("utf-8")
    assert nquads.count("<https://rulespec.org/ns/v1#notEligible>") == 1
    assert "<https://refspec.org/ns/vocabulary-atlas/v1#inputContextArtifact>" in nquads


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
