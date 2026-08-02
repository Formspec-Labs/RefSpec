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


def test_the_corpus_marks_in_place_amendments_machine_readably() -> None:
    """1.0 is amended in place, so the version alone cannot date a pin.

    Case digests changed under an unchanged binding version. Without a marker a
    consumer holding earlier 1.0 digests can only discover the difference by
    reading prose, which no reader does.
    """

    assert _CORPUS["amendments"] == ["2026-08-02", "2026-08-02-hierarchy"]
    assert _CORPUS["schemaVersion"] == "refspec-vocabulary-atlas-conformance-corpus/v1"

    readme = (_BINDING_ROOT / "README.md").read_text(encoding="utf-8")
    for amendment in _CORPUS["amendments"]:
        assert f"Amendment {amendment}" in readme


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


def test_the_corpus_proves_a_hierarchy_can_publish() -> None:
    """Three hierarchy refusals prove nothing if none of them can be passed.

    The same anti-vacuity guard the qualification path carries: a reader that
    rejects every hierarchy is indistinguishable from a correct one unless
    some valid distribution states one.
    """

    valid = {
        case["directory"]: json.loads(
            (_FIXTURE_ROOT / case["directory"] / "atlas-manifest.json").read_text(encoding="utf-8")
        )
        for case in _CORPUS["cases"]
        if case["valid"]
    }
    with_hierarchy = {
        directory: manifest
        for directory, manifest in valid.items()
        if manifest["counts"].get("hierarchyEdges", 0) > 0
    }

    assert with_hierarchy, "no valid distribution states a hierarchy"

    case = next(item for item in _CORPUS["cases"] if item["directory"] == "valid/hierarchy")
    asset = VocabularyAtlasAsset.open(
        _FIXTURE_ROOT / "valid" / "hierarchy",
        expected_manifest_digest=case["manifestDigest"],
        expected_output_digest=case["outputDigest"],
    )
    queries = VocabularyAtlasQueries(asset)

    assert asset.manifest["counts"]["hierarchyEdges"] == len(queries.hierarchy_edges()) == 4
    # A tree-shaped reader passes every other check and still gets this wrong.
    assert len(queries.broader("urn:ref:conformance:alpha:offshore-wind-policy")) == 2
    assert queries.transitive_broader(
        "urn:ref:conformance:alpha:offshore-wind-policy", max_depth=2
    ) == (
        "urn:ref:conformance:alpha:environmental-policy",
        "urn:ref:conformance:alpha:marine-policy",
        "urn:ref:conformance:alpha:renewable-energy-policy",
    )
    # Both directions are stated and retained; the edge count comes from
    # broader alone, and the two agree. A reader that merged broader with the
    # inverse of narrower without checking agreement passes this case and
    # fails `invalid/disagreeing-narrower`.
    nquads = asset.payload.decode("utf-8")
    assert nquads.count("<http://www.w3.org/2004/02/skos/core#narrower>") == 4
    assert nquads.count("<http://www.w3.org/2004/02/skos/core#broader>") == 4


def test_a_hierarchy_free_atlas_gains_no_count_and_the_example_no_new_bytes() -> None:
    """`hierarchyEdges` is absent when there is no hierarchy to count.

    The complete Federal Register example is the case that matters: it is a
    real published distribution over a vocabulary with no hierarchy, and
    consumers hold its two pins. Requiring the count unconditionally would
    have restated it for nothing.
    """

    for name in ("valid/minimal", "valid/qualified-search-only"):
        manifest = json.loads((_FIXTURE_ROOT / name / "atlas-manifest.json").read_text(encoding="utf-8"))
        assert "hierarchyEdges" not in manifest["counts"]

    example = _BINDING_ROOT / "examples" / "federal-register-thesaurus-2025"
    assert _digest(example / "atlas-manifest.json") == (
        "sha256:956cab4f20477933ef015c2c87647ebb9cc40c4c68247a93b10dab8b113f60f1"
    )
    assert _digest(example / "atlas.nq") == (
        "sha256:8e1eaf2265874863981fe9322e0a0e286c01c43e598b091736b556ea424e830a"
    )


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
