"""Published Atlas binding versions remain available to pinned consumers."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ATLAS_V1 = ROOT / "bindings" / "atlas" / "1.0"


def test_atlas_1_0_remains_available_for_pinned_consumers() -> None:
    """Publishing a successor version must not delete the 1.0 surface."""

    corpus_path = ATLAS_V1 / "fixtures" / "corpus.json"
    required_files = [
        ATLAS_V1 / "README.md",
        ATLAS_V1 / "schemas" / "vocabulary-atlas-manifest.schema.json",
        ATLAS_V1 / "schemas" / "vocabulary-atlas-projection-manifest.schema.json",
        ATLAS_V1 / "examples" / "federal-register-thesaurus-2025" / "atlas-manifest.json",
        ATLAS_V1 / "examples" / "federal-register-thesaurus-2025" / "atlas.nq",
        corpus_path,
    ]
    missing = [str(path.relative_to(ROOT)) for path in required_files if not path.is_file()]
    assert not missing, f"published Atlas 1.0 files were removed: {missing}"

    corpus = json.loads(corpus_path.read_text(encoding="utf-8"))
    fixture_files = [
        ATLAS_V1 / "fixtures" / str(case["directory"]) / filename
        for case in corpus["cases"]
        for filename in ("atlas-manifest.json", "atlas.nq")
    ]
    missing_fixtures = [str(path.relative_to(ROOT)) for path in fixture_files if not path.is_file()]
    assert not missing_fixtures, f"published Atlas 1.0 conformance fixtures were removed: {missing_fixtures}"
