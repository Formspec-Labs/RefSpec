"""The projection CLI selects one registered Atlas 2.0 view policy."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import test_vocabulary_atlas_model as model_fixtures

from refspec.atlas.atlas_scope import AtlasScopeRelease
from refspec.atlas.model import (
    VocabularyAtlasAsset,
    VocabularyAtlasError,
    build_vocabulary_atlas,
)
from refspec.atlas.projection import VocabularyAtlasProjection
from refspec.atlas.projection_cli import build_parser, main


def _parent(
    tmp_path: Path,
) -> tuple[Path, VocabularyAtlasAsset, dict[str, str]]:
    fixture = model_fixtures._SCOPE_FIXTURE
    values: list[tuple[AtlasScopeRelease, Any]] = []
    modules = {
        "core": "refspec.registry.cli_core",
        "specialistA": "refspec.registry.cli_specialist_a",
        "specialistB": "refspec.registry.cli_specialist_b",
        "entity": "refspec.registry.cli_entity",
    }
    for name, ring, participation in (
        ("core", "subject", "core"),
        ("specialistA", "subject", "specialist"),
        ("specialistB", "subject", "specialist"),
        ("entity", "entity", None),
    ):
        _, source, _ = fixture._source_release(
            tmp_path,
            f"cli-{name}",
            ring=ring,
        )
        release = AtlasScopeRelease(source)
        values.append(
            (
                release,
                fixture._IndexSpec(
                    release,
                    f"cli-{name}",
                    participation=participation,
                    source_module=modules[name],
                ),
            )
        )
    pinned, _ = model_fixtures._pinned_scope(
        tmp_path,
        name="projection-cli",
        releases=tuple(value[0] for value in values),
        specs=tuple(value[1] for value in values),
    )
    asset = build_vocabulary_atlas(pinned)
    directory = asset.write(tmp_path / "parent-atlas")
    return directory, asset, modules


def _arguments(
    parent: Path,
    asset: VocabularyAtlasAsset,
    output: Path,
) -> list[str]:
    return [
        "--atlas",
        str(parent),
        "--atlas-manifest-digest",
        asset.manifest_digest,
        "--output",
        str(output),
    ]


def test_ring_cli_builds_and_reports_a_two_file_projection(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    parent, asset, _ = _parent(tmp_path)
    output = tmp_path / "subject-ring"

    result = main([*_arguments(parent, asset, output), "--ring", "subject"])
    report = json.loads(capsys.readouterr().out)
    projection = VocabularyAtlasProjection.open(
        output,
        expected_manifest_digest=report["manifestDigest"],
    )

    assert result == 0
    assert {path.name for path in output.iterdir()} == {
        "atlas-manifest.json",
        "atlas.nq",
    }
    assert report["assetId"] == projection.manifest["id"]
    assert report["derivedFrom"]["manifestDigest"] == asset.manifest_digest
    assert report["projectionPolicy"] == {
        "id": "urn:ref:policy:vocabulary-atlas-projection:ring:subject",
        "version": "1",
        "selectors": {"semanticRing": "subject"},
    }
    assert projection.manifest["rings"][0]["releaseCount"] == 3
    assert projection.manifest["rings"][1]["releaseCount"] == 0


def test_subject_module_cli_resolves_core_plus_only_the_named_specialist(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    parent, asset, modules = _parent(tmp_path)
    output = tmp_path / "subject-module"

    result = main(
        [
            *_arguments(parent, asset, output),
            "--subject-module",
            modules["specialistA"],
        ]
    )
    report = json.loads(capsys.readouterr().out)
    projection = VocabularyAtlasProjection.open(
        output,
        expected_manifest_digest=report["manifestDigest"],
    )

    assert result == 0
    assert report["projectionPolicy"]["selectors"] == {"sourceModule": modules["specialistA"]}
    assert projection.manifest["rings"][0]["releaseCount"] == 2
    assert projection.manifest["counts"]["conceptReleases"] == 2


def test_cli_requires_exactly_one_selector() -> None:
    common = [
        "--atlas",
        "parent",
        "--atlas-manifest-digest",
        "sha256:" + "1" * 64,
        "--output",
        "projection",
    ]
    parser = build_parser()

    with pytest.raises(SystemExit):
        parser.parse_args(common)
    with pytest.raises(SystemExit):
        parser.parse_args(
            [
                *common,
                "--ring",
                "subject",
                "--subject-module",
                "refspec.registry.specialist",
            ]
        )


def test_cli_refuses_a_malformed_subject_module_before_opening_parent() -> None:
    with pytest.raises(VocabularyAtlasError, match="dotted Python module"):
        main(
            [
                "--atlas",
                "does-not-exist",
                "--atlas-manifest-digest",
                "sha256:" + "1" * 64,
                "--output",
                "projection",
                "--subject-module",
                "not-dotted",
            ]
        )


def test_parent_manifest_pin_alone_closes_the_parent_files(tmp_path: Path) -> None:
    parent, asset, _ = _parent(tmp_path)
    (parent / "atlas.nq").write_bytes((parent / "atlas.nq").read_bytes() + b" ")
    output = tmp_path / "projection"

    with pytest.raises(VocabularyAtlasError, match="output digest differs"):
        main([*_arguments(parent, asset, output), "--ring", "subject"])
    assert not output.exists()
