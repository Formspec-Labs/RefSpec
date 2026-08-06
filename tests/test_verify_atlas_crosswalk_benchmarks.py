"""Tests for the independent Atlas crosswalk benchmark verifier.

Every check gets two tests: one proving it passes on a consistent synthetic
suite, and one proving it *fires* on a deliberately broken one.  A verifier that
never fails is indistinguishable from no verifier at all, so the broken-input
cases carry the weight here.

The fixtures are synthetic on purpose.  Binding these tests to the real archive
would make them slow, would couple them to one release of the evidence, and
would stop them from exercising the failure paths at all.
"""

from __future__ import annotations

import copy
import json
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from tools import verify_atlas_crosswalk_benchmarks as verifier

CROSSWALK = "fr-elsst"

_VERDICTS = ("same", "related", "unrelated", "target_is_broader", "near_same", "target_is_narrower")
_DIRECTNESS = ("direct_candidate", "generic_thematic")

SKOS = "http://www.w3.org/2004/02/skos/core#"


# --------------------------------------------------------------------------- #
# synthetic suite
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class Spec:
    """One synthetic candidate and the set it belongs in."""

    row: int
    kind: str
    generation_class: str
    judges: tuple[tuple[str, str, str], ...]
    relation: str | None
    source_label: str
    target_label: str

    @property
    def candidate_id(self) -> str:
        return f"urn:ref:candidate:{CROSSWALK}:{self.row:03d}"

    @property
    def source_member(self) -> str:
        return f"urn:ref:source:{CROSSWALK}:{self.row:03d}"

    @property
    def target_member(self) -> str:
        return f"urn:ref:target:{CROSSWALK}:{self.row:03d}"

    @property
    def task_id(self) -> str:
        return f"task-{self.row:06d}"

    @property
    def verdict(self) -> str:
        return _VERDICTS[(self.row - 1) % len(_VERDICTS)]

    @property
    def directness(self) -> str:
        return _DIRECTNESS[(self.row - 1) % len(_DIRECTNESS)]


SPECS: tuple[Spec, ...] = (
    Spec(
        row=1,
        kind="positives",
        generation_class="normalizedLabelEquality",
        judges=(("google-gemini", "supports", "same"), ("openai", "supports", "same")),
        relation=f"{SKOS}closeMatch",
        source_label="Energy",
        target_label="ENERGY",
    ),
    Spec(
        row=2,
        kind="positives",
        generation_class="alternateLabelEquality",
        judges=(
            ("google-gemini", "supports", "target_is_narrower"),
            ("openai", "supports", "target_is_narrower"),
        ),
        relation=f"{SKOS}narrowMatch",
        source_label="Urban renewal",
        target_label="SLUM CLEARANCE",
    ),
    Spec(
        row=3,
        kind="hard-negatives",
        generation_class="substringNearMiss",
        judges=(("google-gemini", "supports", "related"), ("openai", "rejects", "unrelated")),
        relation=None,
        source_label="Child care",
        target_label="CHILD DAY CARE",
    ),
    Spec(
        row=4,
        kind="controls",
        generation_class="randomNegativeControl",
        judges=(("google-gemini", "rejects", "unrelated"), ("openai", "rejects", "unrelated")),
        relation=None,
        source_label="Lime",
        target_label="JOINT CUSTODY",
    ),
    Spec(
        row=5,
        kind="controls",
        generation_class="siblingDistractor",
        judges=(("google-gemini", "rejects", "unrelated"), ("openai", "rejects", "unrelated")),
        relation=None,
        source_label="Vaccination",
        target_label="SINGLE PERSONS",
    ),
    Spec(
        row=6,
        kind="disputed",
        generation_class="editDistanceNearMiss",
        judges=(
            ("google-gemini", "supports", "target_is_broader"),
            ("openai", "supports", "related"),
        ),
        relation=None,
        source_label="Telecommunications equipment",
        target_label="AUDIO VISUAL EQUIPMENT",
    ),
)


@dataclass
class Fixture:
    """Paths to a written-out synthetic suite plus its declared expectations."""

    root: Path
    benchmarks: Path
    archive: Path
    review: Path
    expectations: verifier.Expectations
    crosswalks: tuple[str, ...] = (CROSSWALK,)
    specs: tuple[Spec, ...] = field(default_factory=lambda: SPECS)

    def run(self) -> list[verifier.CheckResult]:
        return verifier.verify(
            self.benchmarks,
            self.archive,
            self.review,
            expectations=self.expectations,
            crosswalks=self.crosswalks,
        )


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.write_text("".join(f"{_canonical(row)}\n" for row in rows), encoding="utf-8")


def _bundle(specs: tuple[Spec, ...]) -> dict[str, Any]:
    artifacts: list[dict[str, Any]] = []
    seen_evidence: set[str] = set()
    candidates: list[dict[str, Any]] = []
    validations: list[dict[str, Any]] = []

    for spec in specs:
        evidence_id = f"urn:ref:artifact:evidence:{spec.generation_class}"
        if evidence_id not in seen_evidence:
            seen_evidence.add(evidence_id)
            artifacts.append(
                {
                    "id": evidence_id,
                    "role": "evidence",
                    "content": {"generationClass": spec.generation_class, "generationPolicy": "test"},
                }
            )
        artifacts.append(
            {
                "id": f"urn:ref:artifact:context:{spec.row:03d}",
                "role": "inputContext",
                "content": {
                    "protocol": "refspec-atlas-crosswalk-model-input-v2",
                    "payload": {
                        "taskId": spec.task_id,
                        "source": {"member": spec.source_member, "prefLabel": spec.source_label},
                        "target": {"member": spec.target_member, "prefLabel": spec.target_label},
                    },
                },
            }
        )
        candidates.append(
            {
                "id": spec.candidate_id,
                "sourceMember": spec.source_member,
                "targetMember": spec.target_member,
                "inputContextDigest": "sha256:deliberately-not-the-artifact-digest",
                "evidence": [{"id": evidence_id, "digest": "sha256:ignored"}],
            }
        )
        for group, outcome, relation in spec.judges:
            validations.append(
                {
                    "candidate": {"id": spec.candidate_id, "digest": "sha256:ignored"},
                    "independenceGroup": f"urn:ref:independence-group:{group}",
                    "outcome": outcome,
                    "verdictRelation": relation,
                }
            )

    return {
        "type": "urn:ref:type:VocabularyAtlasCrosswalkBundle",
        "schemaVersion": "2.0",
        "artifacts": artifacts,
        "mappingCandidates": candidates,
        "machineValidations": validations,
    }


def _assertions(specs: tuple[Spec, ...]) -> dict[str, Any]:
    return {
        "type": "RelationAssertionBundle",
        "schemaVersion": "2.0",
        "mappingAssertions": [
            {
                "id": f"urn:ref:mapping-assertion:{spec.row:03d}",
                "sourceConcept": spec.source_member,
                "targetConcept": spec.target_member,
                "relation": spec.relation,
                "lifecycleStatus": "current",
            }
            for spec in specs
            if spec.relation is not None
        ],
    }


def _benchmark_row(spec: Spec, set_name: str) -> dict[str, Any]:
    row: dict[str, Any] = {
        "crosswalk": CROSSWALK,
        "row": spec.row,
        "taskId": spec.task_id,
        "candidateId": spec.candidate_id,
        "generationClass": spec.generation_class,
        "sourceMember": spec.source_member,
        "sourceLabel": spec.source_label,
        "targetMember": spec.target_member,
        "targetLabel": spec.target_label,
        "sealedJudges": [
            {"group": group, "outcome": outcome, "verdictRelation": relation}
            for group, outcome, relation in spec.judges
        ],
        "independentVerdict": spec.verdict,
        "independentDirectness": spec.directness,
    }
    if set_name == "positives":
        row["admittedRelation"] = spec.relation
    if set_name == "disputed":
        row["competingRelations"] = sorted({relation for _, _, relation in spec.judges})
    if set_name == "controls":
        row["controlKind"] = "random" if spec.generation_class == "randomNegativeControl" else "sibling"
    return row


def _set_rows(specs: tuple[Spec, ...], set_name: str) -> list[dict[str, Any]]:
    chosen = specs if set_name == "directness" else tuple(spec for spec in specs if spec.kind == set_name)
    return [_benchmark_row(spec, set_name) for spec in sorted(chosen, key=lambda spec: spec.row)]


def _manifest(benchmarks: Path) -> dict[str, Any]:
    return {
        "type": "AtlasCrosswalkBenchmarkManifest",
        "populationBias": "label-oriented generator; sound for precision, not a recall benchmark",
        "sets": [
            {
                "set": name,
                "file": f"{name}.jsonl",
                "rows": len((benchmarks / f"{name}.jsonl").read_text(encoding="utf-8").splitlines()),
                "sha256": f"sha256:{verifier._sha256(benchmarks / f'{name}.jsonl')}",
                "usableFor": [f"{name} evaluation"],
                "notUsableFor": ["recall estimation"],
            }
            for name in verifier.ALL_SETS
        ],
    }


def build_fixture(tmp_path: Path, specs: tuple[Spec, ...] = SPECS) -> Fixture:
    """Write a fully consistent synthetic suite, archive, and blind review."""
    benchmarks = tmp_path / "benchmarks"
    archive = tmp_path / "archive"
    review = tmp_path / "review"
    benchmarks.mkdir()
    (archive / CROSSWALK / "relation-assertions-v2").mkdir(parents=True)
    (review / "independent").mkdir(parents=True)
    (review / "blind").mkdir(parents=True)

    (archive / CROSSWALK / "crosswalk-bundle.json").write_text(json.dumps(_bundle(specs)), encoding="utf-8")
    (archive / CROSSWALK / "relation-assertions-v2" / "relation-assertions.json").write_text(
        json.dumps(_assertions(specs)), encoding="utf-8"
    )

    _write_jsonl(
        review / "independent" / f"{CROSSWALK}.jsonl",
        [{"row": spec.row, "verdict": spec.verdict, "directness": spec.directness, "why": "test"} for spec in specs],
    )
    (review / "blind" / f"{CROSSWALK}.json").write_text(
        json.dumps(
            {
                "crosswalk": CROSSWALK,
                "rows": [
                    {
                        "row": spec.row,
                        "taskId": spec.task_id,
                        "source": {"member": spec.source_member, "prefLabel": spec.source_label},
                        "target": {"member": spec.target_member, "prefLabel": spec.target_label},
                    }
                    for spec in specs
                ],
            }
        ),
        encoding="utf-8",
    )

    for name in verifier.ALL_SETS:
        _write_jsonl(benchmarks / f"{name}.jsonl", _set_rows(specs, name))
    (benchmarks / "manifest.json").write_text(json.dumps(_manifest(benchmarks)), encoding="utf-8")

    expectations = verifier.Expectations(
        rows={name: len(_set_rows(specs, name)) for name in verifier.ALL_SETS},
        total=len(specs),
        label_sample=1,
    )
    return Fixture(
        root=tmp_path,
        benchmarks=benchmarks,
        archive=archive,
        review=review,
        expectations=expectations,
        specs=specs,
    )


# --------------------------------------------------------------------------- #
# mutation helpers
# --------------------------------------------------------------------------- #


def _read_rows(fixture: Fixture, name: str) -> list[dict[str, Any]]:
    path = fixture.benchmarks / f"{name}.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def rewrite(
    fixture: Fixture,
    name: str,
    mutate: Callable[[list[dict[str, Any]]], list[dict[str, Any]]],
    *,
    resync_manifest: bool = True,
) -> None:
    """Apply a mutation to one emitted set, keeping the manifest honest by default."""
    rows = mutate(copy.deepcopy(_read_rows(fixture, name)))
    _write_jsonl(fixture.benchmarks / f"{name}.jsonl", rows)
    if resync_manifest:
        (fixture.benchmarks / "manifest.json").write_text(json.dumps(_manifest(fixture.benchmarks)), encoding="utf-8")


def mutate_manifest(fixture: Fixture, mutate: Callable[[dict[str, Any]], dict[str, Any]]) -> None:
    path = fixture.benchmarks / "manifest.json"
    path.write_text(json.dumps(mutate(json.loads(path.read_text(encoding="utf-8")))), encoding="utf-8")


def result(results: list[verifier.CheckResult], name: str) -> verifier.CheckResult:
    for entry in results:
        if entry.name == name:
            return entry
    raise AssertionError(f"no check named {name!r} in {[entry.name for entry in results]}")


def failed(results: list[verifier.CheckResult]) -> set[str]:
    return {entry.name for entry in results if not entry.passed}


@pytest.fixture()
def suite(tmp_path: Path) -> Fixture:
    return build_fixture(tmp_path)


# --------------------------------------------------------------------------- #
# baseline
# --------------------------------------------------------------------------- #


def test_consistent_suite_passes_every_check(suite: Fixture) -> None:
    results = suite.run()
    assert len(results) == 10
    assert failed(results) == set(), [entry.summary for entry in results if not entry.passed]


def test_check_names_are_stable(suite: Fixture) -> None:
    assert [entry.name for entry in suite.run()] == [
        "partition",
        "counts",
        "positives-admitted",
        "controls-never-admitted",
        "disputed-are-disputed",
        "hard-negatives-rejected",
        "labels-match-source",
        "independent-verdicts",
        "manifest-integrity",
        "determinism",
    ]


# --------------------------------------------------------------------------- #
# check 1 -- partition
# --------------------------------------------------------------------------- #


def test_partition_fires_when_a_candidate_lands_in_two_sets(suite: Fixture) -> None:
    disputed = _read_rows(suite, "disputed")[0]
    rewrite(suite, "hard-negatives", lambda rows: [*rows, disputed])
    check = result(suite.run(), "partition")
    assert not check.passed
    assert any("appears in both" in detail for detail in check.failures)


def test_partition_fires_when_a_candidate_is_never_emitted(suite: Fixture) -> None:
    rewrite(suite, "controls", lambda rows: rows[:1])
    check = result(suite.run(), "partition")
    assert not check.passed
    assert any("never emitted" in detail for detail in check.failures)


def test_partition_fires_on_duplicate_rows_inside_one_set(suite: Fixture) -> None:
    rewrite(suite, "positives", lambda rows: [rows[0], *rows])
    check = result(suite.run(), "partition")
    assert not check.passed
    assert any("appears 2 times" in detail for detail in check.failures)


def test_partition_fires_when_a_row_claims_the_wrong_crosswalk(suite: Fixture) -> None:
    def bend(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        rows[0]["crosswalk"] = "fr-icpsr"
        return rows

    rewrite(suite, "positives", bend)
    check = result(suite.run(), "partition")
    assert not check.passed
    assert any("archive says" in detail for detail in check.failures)


# --------------------------------------------------------------------------- #
# check 2 -- counts
# --------------------------------------------------------------------------- #


def test_counts_fire_on_an_extra_row(suite: Fixture) -> None:
    rewrite(suite, "disputed", lambda rows: [*rows, copy.deepcopy(rows[0])])
    check = result(suite.run(), "counts")
    assert not check.passed
    assert any("expected 1" in detail for detail in check.failures)


def test_counts_fire_on_a_missing_file(suite: Fixture) -> None:
    (suite.benchmarks / "controls.jsonl").unlink()
    check = result(suite.run(), "counts")
    assert not check.passed
    assert any("file missing" in detail for detail in check.failures)


# --------------------------------------------------------------------------- #
# check 3 -- positives are admitted
# --------------------------------------------------------------------------- #


def test_positives_fire_when_the_pair_was_never_admitted(suite: Fixture) -> None:
    def bend(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        rows[0]["sourceMember"] = "urn:ref:source:fr-elsst:999"
        return rows

    rewrite(suite, "positives", bend)
    check = result(suite.run(), "positives-admitted")
    assert not check.passed
    assert any("not in mappingAssertions" in detail for detail in check.failures)


def test_positives_fire_on_a_wrong_admitted_relation(suite: Fixture) -> None:
    def bend(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        rows[0]["admittedRelation"] = f"{SKOS}exactMatch"
        return rows

    rewrite(suite, "positives", bend)
    check = result(suite.run(), "positives-admitted")
    assert not check.passed
    assert any("admittedRelation" in detail for detail in check.failures)


def test_positives_accept_the_local_name_form_of_a_relation(suite: Fixture) -> None:
    def bend(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        for row in rows:
            row["admittedRelation"] = str(row["admittedRelation"]).rsplit("#", 1)[-1]
        return rows

    rewrite(suite, "positives", bend)
    assert result(suite.run(), "positives-admitted").passed


def test_positives_fire_when_an_admitted_mapping_is_dropped(suite: Fixture) -> None:
    rewrite(suite, "positives", lambda rows: rows[:1])
    check = result(suite.run(), "positives-admitted")
    assert not check.passed
    assert any("never emitted as a positive" in detail for detail in check.failures)


# --------------------------------------------------------------------------- #
# check 4 -- controls are never admitted
# --------------------------------------------------------------------------- #


def test_controls_fire_when_a_control_pair_was_admitted(suite: Fixture) -> None:
    positive = _read_rows(suite, "positives")[0]

    def bend(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        rows[0]["sourceMember"] = positive["sourceMember"]
        rows[0]["targetMember"] = positive["targetMember"]
        return rows

    rewrite(suite, "controls", bend)
    check = result(suite.run(), "controls-never-admitted")
    assert not check.passed
    assert any("appears in mappingAssertions" in detail for detail in check.failures)


def test_controls_fire_on_a_non_control_generation_class(suite: Fixture) -> None:
    def bend(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        rows[0]["generationClass"] = "normalizedLabelEquality"
        return rows

    rewrite(suite, "controls", bend)
    check = result(suite.run(), "controls-never-admitted")
    assert not check.passed
    assert any("is not a control class" in detail for detail in check.failures)


def test_controls_fire_on_a_missing_control_kind(suite: Fixture) -> None:
    def bend(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        rows[0].pop("controlKind")
        return rows

    rewrite(suite, "controls", bend)
    check = result(suite.run(), "controls-never-admitted")
    assert not check.passed
    assert any("controlKind" in detail for detail in check.failures)


def test_controls_fire_when_a_control_candidate_is_filed_elsewhere(suite: Fixture) -> None:
    rewrite(suite, "controls", lambda rows: rows[:1])
    check = result(suite.run(), "controls-never-admitted")
    assert not check.passed
    assert any("not emitted as a control" in detail for detail in check.failures)


# --------------------------------------------------------------------------- #
# check 5 -- disputed really are disputed
# --------------------------------------------------------------------------- #


def test_disputed_reports_how_many_judge_pairs_differ(suite: Fixture) -> None:
    check = result(suite.run(), "disputed-are-disputed")
    assert check.passed
    assert "1/1" in check.summary


def test_disputed_fire_on_a_single_sealed_judge(suite: Fixture) -> None:
    def bend(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        rows[0]["sealedJudges"] = rows[0]["sealedJudges"][:1]
        return rows

    rewrite(suite, "disputed", bend)
    check = result(suite.run(), "disputed-are-disputed")
    assert not check.passed
    assert any("expected exactly 2" in detail for detail in check.failures)


def test_disputed_fire_when_a_judge_did_not_support(suite: Fixture) -> None:
    def bend(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        rows[0]["sealedJudges"][0]["outcome"] = "rejects"
        return rows

    rewrite(suite, "disputed", bend)
    check = result(suite.run(), "disputed-are-disputed")
    assert not check.passed
    assert any("expected both 'supports'" in detail for detail in check.failures)


def test_disputed_fire_when_the_archive_judges_disagree_with_the_row(suite: Fixture) -> None:
    def bend(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        rows[0]["sealedJudges"][1]["verdictRelation"] = "same"
        return rows

    rewrite(suite, "disputed", bend)
    check = result(suite.run(), "disputed-are-disputed")
    assert not check.passed
    assert any("disagree with archive" in detail for detail in check.failures)


def test_disputed_fire_when_a_rejected_candidate_is_filed_as_disputed(suite: Fixture) -> None:
    hard_negative = _read_rows(suite, "hard-negatives")[0]
    hard_negative["sealedJudges"] = [
        {"group": "google-gemini", "outcome": "supports", "verdictRelation": "related"},
        {"group": "openai", "outcome": "supports", "verdictRelation": "same"},
    ]
    rewrite(suite, "disputed", lambda rows: sorted([*rows, hard_negative], key=lambda row: row["row"]))
    check = result(suite.run(), "disputed-are-disputed")
    assert not check.passed
    assert any("archive sealed outcomes" in detail for detail in check.failures)


# --------------------------------------------------------------------------- #
# check 6 -- hard negatives are genuinely rejected
# --------------------------------------------------------------------------- #


def test_hard_negatives_fire_when_both_judges_supported(suite: Fixture) -> None:
    disputed = _read_rows(suite, "disputed")[0]
    disputed.pop("competingRelations", None)
    rewrite(suite, "hard-negatives", lambda rows: sorted([*rows, disputed], key=lambda row: row["row"]))
    check = result(suite.run(), "hard-negatives-rejected")
    assert not check.passed
    assert any("this is disputed, not rejected" in detail for detail in check.failures)


def test_hard_negatives_fire_when_the_pair_was_admitted(suite: Fixture) -> None:
    positive = _read_rows(suite, "positives")[0]

    def bend(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        rows[0]["sourceMember"] = positive["sourceMember"]
        rows[0]["targetMember"] = positive["targetMember"]
        return rows

    rewrite(suite, "hard-negatives", bend)
    check = result(suite.run(), "hard-negatives-rejected")
    assert not check.passed
    assert any("was admitted as" in detail for detail in check.failures)


def test_hard_negatives_fire_on_a_control_class_candidate(suite: Fixture) -> None:
    control = _read_rows(suite, "controls")[0]
    control.pop("controlKind", None)
    rewrite(suite, "hard-negatives", lambda rows: sorted([*rows, control], key=lambda row: row["row"]))
    check = result(suite.run(), "hard-negatives-rejected")
    assert not check.passed
    assert any("filed as hard negative" in detail for detail in check.failures)


# --------------------------------------------------------------------------- #
# check 7 -- labels match source
# --------------------------------------------------------------------------- #


def test_labels_fire_on_a_rewritten_pref_label(suite: Fixture) -> None:
    def bend(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        rows[0]["targetLabel"] = "Energy"
        return rows

    rewrite(suite, "positives", bend)
    check = result(suite.run(), "labels-match-source")
    assert not check.passed
    assert any("targetLabel" in detail for detail in check.failures)


def test_labels_fire_on_a_mismatched_task_id(suite: Fixture) -> None:
    def bend(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        rows[0]["taskId"] = "task-000999"
        return rows

    rewrite(suite, "directness", bend)
    check = result(suite.run(), "labels-match-source")
    assert not check.passed
    assert any("taskId" in detail for detail in check.failures)


def test_labels_fire_when_members_disagree_with_the_archive(suite: Fixture) -> None:
    def bend(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        rows[0]["targetMember"] = "urn:ref:target:fr-elsst:002"
        return rows

    rewrite(suite, "directness", bend)
    check = result(suite.run(), "labels-match-source")
    assert not check.passed
    assert any("disagree with archive" in detail for detail in check.failures)


# --------------------------------------------------------------------------- #
# check 8 -- independent verdicts
# --------------------------------------------------------------------------- #


def test_independent_verdicts_fire_on_a_changed_verdict(suite: Fixture) -> None:
    def bend(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        rows[0]["independentVerdict"] = "insufficient_evidence"
        return rows

    rewrite(suite, "positives", bend)
    check = result(suite.run(), "independent-verdicts")
    assert not check.passed
    assert any("independentVerdict" in detail for detail in check.failures)


def test_independent_verdicts_fire_on_a_changed_directness(suite: Fixture) -> None:
    def bend(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        rows[0]["independentDirectness"] = "generic_thematic"
        rows[0]["independentVerdict"] = _VERDICTS[0]
        return rows

    rewrite(suite, "directness", bend)
    check = result(suite.run(), "independent-verdicts")
    assert not check.passed
    assert any("independentDirectness" in detail for detail in check.failures)


def test_independent_verdicts_fire_when_the_row_number_points_at_another_pair(suite: Fixture) -> None:
    def bend(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        rows[0]["row"] = 2
        return rows

    rewrite(suite, "hard-negatives", bend)
    check = result(suite.run(), "independent-verdicts")
    assert not check.passed
    assert any("blind pair" in detail for detail in check.failures)


def test_independent_verdicts_fire_when_the_review_is_absent(suite: Fixture) -> None:
    (suite.review / "independent" / f"{CROSSWALK}.jsonl").unlink()
    check = result(suite.run(), "independent-verdicts")
    assert not check.passed
    assert any("cannot be verified" in detail for detail in check.failures)


# --------------------------------------------------------------------------- #
# check 9 -- manifest integrity
# --------------------------------------------------------------------------- #


def test_manifest_fires_on_a_declared_row_count_that_is_wrong(suite: Fixture) -> None:
    def bend(manifest: dict[str, Any]) -> dict[str, Any]:
        manifest["sets"][0]["rows"] = 99
        return manifest

    mutate_manifest(suite, bend)
    check = result(suite.run(), "manifest-integrity")
    assert not check.passed
    assert any("declares 99 rows" in detail for detail in check.failures)


def test_manifest_fires_on_a_stale_digest(suite: Fixture) -> None:
    rewrite(suite, "positives", lambda rows: rows, resync_manifest=False)

    def bend(manifest: dict[str, Any]) -> dict[str, Any]:
        manifest["sets"][0]["sha256"] = "sha256:" + "0" * 64
        return manifest

    mutate_manifest(suite, bend)
    check = result(suite.run(), "manifest-integrity")
    assert not check.passed
    assert any("declares sha256" in detail for detail in check.failures)


def test_manifest_fires_without_population_bias(suite: Fixture) -> None:
    def bend(manifest: dict[str, Any]) -> dict[str, Any]:
        manifest.pop("populationBias")
        return manifest

    mutate_manifest(suite, bend)
    check = result(suite.run(), "manifest-integrity")
    assert not check.passed
    assert any("populationBias" in detail for detail in check.failures)


def test_manifest_fires_on_an_empty_not_usable_for(suite: Fixture) -> None:
    def bend(manifest: dict[str, Any]) -> dict[str, Any]:
        manifest["sets"][2]["notUsableFor"] = []
        return manifest

    mutate_manifest(suite, bend)
    check = result(suite.run(), "manifest-integrity")
    assert not check.passed
    assert any("notUsableFor" in detail for detail in check.failures)


def test_manifest_fires_on_a_missing_set_descriptor(suite: Fixture) -> None:
    def bend(manifest: dict[str, Any]) -> dict[str, Any]:
        manifest["sets"] = [entry for entry in manifest["sets"] if entry["set"] != "disputed"]
        return manifest

    mutate_manifest(suite, bend)
    check = result(suite.run(), "manifest-integrity")
    assert not check.passed
    assert any("no descriptor for set 'disputed'" in detail for detail in check.failures)


def test_manifest_accepts_a_mapping_keyed_by_camel_case_set_names(suite: Fixture) -> None:
    def bend(manifest: dict[str, Any]) -> dict[str, Any]:
        manifest["sets"] = {
            verifier._camel(str(entry["set"])): {key: value for key, value in entry.items() if key != "set"}
            for entry in manifest["sets"]
        }
        return manifest

    mutate_manifest(suite, bend)
    assert result(suite.run(), "manifest-integrity").passed


def test_manifest_fires_when_absent(suite: Fixture) -> None:
    (suite.benchmarks / "manifest.json").unlink()
    check = result(suite.run(), "manifest-integrity")
    assert not check.passed


# --------------------------------------------------------------------------- #
# check 10 -- determinism
# --------------------------------------------------------------------------- #


def test_determinism_fires_on_unsorted_rows(suite: Fixture) -> None:
    rewrite(suite, "directness", lambda rows: list(reversed(rows)))
    check = result(suite.run(), "determinism")
    assert not check.passed
    assert any("not sorted" in detail for detail in check.failures)


def test_determinism_fires_on_a_non_canonical_line(suite: Fixture) -> None:
    path = suite.benchmarks / "positives.jsonl"
    rows = _read_rows(suite, "positives")
    path.write_text(
        json.dumps(rows[0], indent=None, sort_keys=False) + "\n" + _canonical(rows[1]) + "\n",
        encoding="utf-8",
    )
    mutate_manifest(suite, lambda manifest: _manifest(suite.benchmarks))
    check = result(suite.run(), "determinism")
    assert not check.passed
    assert any("not canonical" in detail for detail in check.failures)


def test_determinism_fires_without_a_trailing_newline(suite: Fixture) -> None:
    path = suite.benchmarks / "disputed.jsonl"
    path.write_text(path.read_text(encoding="utf-8").rstrip("\n"), encoding="utf-8")
    mutate_manifest(suite, lambda manifest: _manifest(suite.benchmarks))
    check = result(suite.run(), "determinism")
    assert not check.passed
    assert any("does not end with a newline" in detail for detail in check.failures)


def test_determinism_fires_on_malformed_json(suite: Fixture) -> None:
    path = suite.benchmarks / "controls.jsonl"
    path.write_text(path.read_text(encoding="utf-8") + "{not json}\n", encoding="utf-8")
    mutate_manifest(suite, lambda manifest: _manifest(suite.benchmarks))
    check = result(suite.run(), "determinism")
    assert not check.passed
    assert any("not valid JSON" in detail for detail in check.failures)


# --------------------------------------------------------------------------- #
# rendering and exit codes
# --------------------------------------------------------------------------- #


def test_render_marks_pass_and_fail(suite: Fixture) -> None:
    rewrite(suite, "positives", lambda rows: rows[:1])
    text = verifier.render(suite.run())
    assert "FAIL" in text
    assert "FAILURES" in text
    assert "positives-admitted" in text


def test_main_returns_two_when_the_benchmark_directory_is_absent(tmp_path: Path, capsys: Any) -> None:
    assert verifier.main(["--benchmarks", str(tmp_path / "nope"), "--archive", str(tmp_path)]) == 2
    assert "not found" in capsys.readouterr().out


def test_main_returns_two_when_the_archive_is_absent(tmp_path: Path) -> None:
    (tmp_path / "benchmarks").mkdir()
    assert verifier.main(["--benchmarks", str(tmp_path / "benchmarks"), "--archive", str(tmp_path / "nope")]) == 2


def test_main_returns_zero_when_every_check_passes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "benchmarks").mkdir()
    monkeypatch.setattr(
        verifier,
        "verify",
        lambda *args, **kwargs: [verifier.CheckResult("partition", True, "ok")],
    )
    args = ["--benchmarks", str(tmp_path / "benchmarks"), "--archive", str(tmp_path)]
    assert verifier.main(args) == 0


def test_main_returns_one_and_writes_json_when_a_check_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "benchmarks").mkdir()
    monkeypatch.setattr(
        verifier,
        "verify",
        lambda *args, **kwargs: [verifier.CheckResult("counts", False, "bad", ["positives: 1 line, expected 2"])],
    )
    output = tmp_path / "out" / "results.json"
    args = [
        "--benchmarks",
        str(tmp_path / "benchmarks"),
        "--archive",
        str(tmp_path),
        "--output",
        str(output),
    ]
    assert verifier.main(args) == 1
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["results"][0]["failures"] == ["positives: 1 line, expected 2"]
