"""Prove the three mechanical standing-practice gates break when violated.

A gate that has never been seen to fail is a gate nobody knows is wired. Each
test here breaks one of the standing practices adopted from the 2026-08-12
spikes on purpose and requires the check to notice:

* strict-parser lint (`tools/lint_rdf_strict.py`) -- a second, independent
  parser over the published bytes;
* the double-build determinism gate's comparator
  (`tools/compare_build_trees.py`);
* the shapes scale benchmark's recorded baseline
  (`tools/atlas-shacl-scale-baseline.json`), whose numbers are the only thing
  standing between a 3x SHACL regression and a green release.

The benchmark's own timing path is not exercised here: it needs a built
distribution, which is gitignored, regenerable and absent on CI. What is
checked is that its baseline file still says what the tool reads.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools import compare_build_trees, lint_rdf_strict
from tools.benchmark_atlas_shacl_scale import DEFAULT_BASELINE

ROOT = Path(__file__).resolve().parents[1]

GOOD_LINE = '<http://example.org/s> <http://example.org/p> "x" <http://example.org/g> .\n'
# A UCHAR standing for `<`, which RFC 3987 excludes from an IRI: rdflib's
# round-trip accepted this class and the byte grammar refuses it (findings item
# (h)). Here it stands for any wire defect a producer-side parser might wave
# through.
BAD_LINE = '<http://example.org/\\u003C> <http://example.org/p> "x" .\n'


def test_the_committed_wire_sentinel_parses_under_the_second_parser() -> None:
    quads = lint_rdf_strict._parse_strict(lint_rdf_strict.REGISTRY_DESCRIPTORS)
    assert quads > 0


def test_the_strict_parser_lint_refuses_a_defective_line(tmp_path: Path) -> None:
    good = tmp_path / "good.nq"
    good.write_text(GOOD_LINE, encoding="utf-8")
    assert lint_rdf_strict._parse_strict(good) == 1

    bad = tmp_path / "bad.nq"
    bad.write_text(GOOD_LINE + BAD_LINE, encoding="utf-8")
    with pytest.raises(SyntaxError, match="bad.nq"):
        lint_rdf_strict._parse_strict(bad)


def test_the_determinism_comparator_separates_identical_trees_from_changed_ones(
    tmp_path: Path,
) -> None:
    first = tmp_path / "first" / "distribution"
    second = tmp_path / "second" / "distribution"
    for root in (first, second):
        (root / "packs").mkdir(parents=True)
        (root / "atlas-manifest.json").write_text('{"a": 1}', encoding="utf-8")
        (root / "packs" / "all.nq").write_text(GOOD_LINE, encoding="utf-8")

    assert compare_build_trees.main([str(first.parent), str(second.parent)]) == 0

    # One byte, in one file the manifest does not cover: whole trees are
    # compared for exactly this reason.
    (second / "packs" / "all.nq").write_text(GOOD_LINE * 2, encoding="utf-8")
    assert compare_build_trees.main([str(first.parent), str(second.parent)]) == 1

    (second / "packs" / "extra.nq").write_text(GOOD_LINE, encoding="utf-8")
    assert compare_build_trees.main([str(first.parent), str(second.parent)]) == 1


def test_the_shapes_scale_baseline_still_says_what_the_benchmark_reads() -> None:
    baseline = json.loads(DEFAULT_BASELINE.read_text(encoding="utf-8"))
    assert baseline["toleranceRatio"] > 1
    assert baseline["quadCountToleranceRatio"] > 1
    assert baseline["measurements"], "an empty baseline gates nothing"
    for key, measurement in baseline["measurements"].items():
        assert key == f"{measurement['scaleClass']}/{measurement['mode']}"
        assert measurement["shaclSeconds"] > 0
        assert measurement["quadCount"] > 0
        assert measurement["machine"] and measurement["recordedAt"]
