"""Focused checks for the scoped crosswalk benchmark split.

The membership rules are the whole product here: a row in the wrong set silently
turns a calibration control into a retrieval failure, or an unresolved dispute
into a positive.  These exercise the rules against small synthetic archives so a
failure names the rule that broke, not the 1,095-row archive it broke on.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from tools import build_atlas_crosswalk_benchmarks as builder

CROSSWALK = "fr-elsst"


def _candidate(index: int, evidence_id: str) -> dict[str, Any]:
    return {
        "id": f"urn:candidate:{index}",
        "sourceMember": f"urn:source:{index}",
        "targetMember": f"urn:target:{index}",
        "evidence": [{"id": evidence_id}],
    }


def _context(index: int) -> dict[str, Any]:
    return {
        "role": "inputContext",
        "id": f"urn:artifact:context:{index}",
        "content": {
            "payload": {
                "taskId": f"task-{index}",
                "source": {"member": f"urn:source:{index}", "prefLabel": f"Source {index}"},
                "target": {"member": f"urn:target:{index}", "prefLabel": f"Target {index}"},
            }
        },
    }


def _validation(index: int, group: str, outcome: str, relation: str | None) -> dict[str, Any]:
    return {
        "candidate": {"id": f"urn:candidate:{index}"},
        "independenceGroup": f"urn:ref:independence-group:{group}",
        "outcome": outcome,
        "verdictRelation": relation,
    }


def _write_archive(root: Path, specs: list[dict[str, Any]]) -> tuple[Path, Path]:
    """Materialise a miniature archive plus blind review from row specifications.

    Each spec supplies ``generationClass``, ``admitted``, and the two sealed
    outcomes; everything else is filled in so the joins the tool performs are the
    same shape as the real archive's.
    """
    archive = root / "archive"
    review = root / "review"
    (archive / CROSSWALK / "relation-assertions-v2").mkdir(parents=True)
    (review / "sealed-key").mkdir(parents=True)
    (review / "independent").mkdir(parents=True)

    artifacts: list[dict[str, Any]] = []
    candidates: list[dict[str, Any]] = []
    validations: list[dict[str, Any]] = []
    key_rows: list[dict[str, Any]] = []
    independent_lines: list[str] = []
    assertions: list[dict[str, Any]] = []

    for index, spec in enumerate(specs, start=1):
        evidence_id = f"urn:artifact:evidence:{index}"
        artifacts.append(
            {
                "role": "evidence",
                "id": evidence_id,
                "content": {"generationClass": spec["generationClass"]},
            }
        )
        artifacts.append(_context(index))
        candidates.append(_candidate(index, evidence_id))
        for group, outcome in zip(("google-gemini", "openai"), spec["outcomes"], strict=True):
            relation = spec.get("relations", {}).get(group, "same")
            validations.append(_validation(index, group, outcome, relation))
        key_rows.append(
            {
                "row": index,
                "candidateId": f"urn:candidate:{index}",
                "admitted": spec["admitted"],
            }
        )
        independent_lines.append(
            json.dumps({"row": index, "verdict": spec.get("verdict", "same"), "directness": "direct_candidate"})
        )
        if spec["admitted"]:
            assertions.append(
                {
                    "sourceConcept": f"urn:source:{index}",
                    "targetConcept": f"urn:target:{index}",
                    "relation": "http://www.w3.org/2004/02/skos/core#closeMatch",
                }
            )

    bundle = {"artifacts": artifacts, "mappingCandidates": candidates, "machineValidations": validations}
    (archive / CROSSWALK / "crosswalk-bundle.json").write_text(json.dumps(bundle), encoding="utf-8")
    (archive / CROSSWALK / "relation-assertions-v2" / "relation-assertions.json").write_text(
        json.dumps({"mappingAssertions": assertions}), encoding="utf-8"
    )
    (review / "sealed-key" / f"{CROSSWALK}.json").write_text(
        json.dumps({"crosswalk": CROSSWALK, "rows": key_rows}), encoding="utf-8"
    )
    (review / "independent" / f"{CROSSWALK}.jsonl").write_text("\n".join(independent_lines) + "\n", encoding="utf-8")
    return archive, review


#: One row destined for each of the four decision sets, in order.
POPULATION: list[dict[str, Any]] = [
    {"generationClass": "normalizedLabelEquality", "admitted": True, "outcomes": ("supports", "supports")},
    {"generationClass": "randomNegativeControl", "admitted": False, "outcomes": ("rejects", "rejects")},
    {"generationClass": "siblingDistractor", "admitted": False, "outcomes": ("rejects", "abstains")},
    {
        "generationClass": "substringNearMiss",
        "admitted": False,
        "outcomes": ("supports", "supports"),
        "relations": {"google-gemini": "target_is_broader", "openai": "related"},
    },
    {"generationClass": "editDistanceNearMiss", "admitted": False, "outcomes": ("supports", "rejects")},
    {"generationClass": "alternateLabelEquality", "admitted": False, "outcomes": ("abstains", "abstains")},
]


def _build(tmp_path: Path, specs: list[dict[str, Any]] | None = None) -> dict[str, list[dict[str, Any]]]:
    archive, review = _write_archive(tmp_path, specs if specs is not None else POPULATION)
    rows = builder.build_rows(archive, review, CROSSWALK)
    sets = builder.partition(rows)
    builder.verify_partition(rows, sets)
    return sets


def test_membership_rules_place_each_row_in_exactly_one_decision_set(tmp_path: Path) -> None:
    sets = _build(tmp_path)

    assert [row["row"] for row in sets[builder.POSITIVES]] == [1]
    assert [row["row"] for row in sets[builder.CONTROLS]] == [2, 3]
    assert [row["row"] for row in sets[builder.DISPUTED]] == [4]
    assert [row["row"] for row in sets[builder.HARD_NEGATIVES]] == [5, 6]


def test_admission_outranks_every_other_rule(tmp_path: Path) -> None:
    # A control that was somehow admitted must not be silently reclassified; the
    # partition check is what refuses it, not the placement.
    specs = [{"generationClass": "randomNegativeControl", "admitted": True, "outcomes": ("supports", "supports")}]
    archive, review = _write_archive(tmp_path, specs)
    rows = builder.build_rows(archive, review, CROSSWALK)
    sets = builder.partition(rows)

    assert [row["row"] for row in sets[builder.POSITIVES]] == [1]
    with pytest.raises(builder.BenchmarkIntegrityError, match="seeded controls were admitted"):
        builder.verify_partition(rows, sets)


def test_a_control_is_never_disputed_even_when_both_judges_support_it(tmp_path: Path) -> None:
    specs = [{"generationClass": "siblingDistractor", "admitted": False, "outcomes": ("supports", "supports")}]
    sets = _build(tmp_path, specs)

    assert sets[builder.DISPUTED] == []
    assert [row["controlKind"] for row in sets[builder.CONTROLS]] == ["siblingDistractor"]


def test_disputed_requires_both_judges_to_support_not_merely_one(tmp_path: Path) -> None:
    specs = [
        {"generationClass": "substringNearMiss", "admitted": False, "outcomes": ("supports", "abstains")},
        {"generationClass": "substringNearMiss", "admitted": False, "outcomes": ("supports", "supports")},
    ]
    sets = _build(tmp_path, specs)

    assert [row["row"] for row in sets[builder.HARD_NEGATIVES]] == [1]
    assert [row["row"] for row in sets[builder.DISPUTED]] == [2]


def test_row_shapes_carry_the_per_set_extras(tmp_path: Path) -> None:
    sets = _build(tmp_path)
    common = {
        "crosswalk",
        "row",
        "taskId",
        "candidateId",
        "generationClass",
        "sourceMember",
        "sourceLabel",
        "targetMember",
        "targetLabel",
        "sealedJudges",
        "independentVerdict",
        "independentDirectness",
    }

    assert set(sets[builder.HARD_NEGATIVES][0]) == common
    assert set(sets[builder.DIRECTNESS][0]) == common
    assert set(sets[builder.POSITIVES][0]) == common | {"admittedRelation"}
    assert set(sets[builder.CONTROLS][0]) == common | {"controlKind"}
    assert set(sets[builder.DISPUTED][0]) == common | {"competingRelations"}
    assert sets[builder.POSITIVES][0]["admittedRelation"] == "closeMatch"
    # The two competing relations are what makes the row an adjudication test.
    assert sets[builder.DISPUTED][0]["competingRelations"] == ["target_is_broader", "related"]
    assert sets[builder.DIRECTNESS][0]["independentDirectness"] == "direct_candidate"
    assert sets[builder.DIRECTNESS][0]["sealedJudges"][0]["group"] == "google-gemini"


def test_directness_covers_every_row_while_staying_out_of_the_partition(tmp_path: Path) -> None:
    sets = _build(tmp_path)

    partition_rows = sum(len(sets[name]) for name in builder.PARTITION_SETS)
    assert partition_rows == len(POPULATION)
    assert len(sets[builder.DIRECTNESS]) == len(POPULATION)


def test_verify_partition_rejects_a_row_claimed_by_two_sets(tmp_path: Path) -> None:
    archive, review = _write_archive(tmp_path, POPULATION)
    rows = builder.build_rows(archive, review, CROSSWALK)
    sets = builder.partition(rows)
    sets[builder.HARD_NEGATIVES].append(dict(sets[builder.POSITIVES][0]))

    with pytest.raises(builder.BenchmarkIntegrityError, match="is in both"):
        builder.verify_partition(rows, sets)


def test_verify_partition_rejects_an_incomplete_cover(tmp_path: Path) -> None:
    archive, review = _write_archive(tmp_path, POPULATION)
    rows = builder.build_rows(archive, review, CROSSWALK)
    sets = builder.partition(rows)
    sets[builder.HARD_NEGATIVES].pop()

    with pytest.raises(builder.BenchmarkIntegrityError, match="does not cover the population"):
        builder.verify_partition(rows, sets)


def test_census_drift_fails_closed() -> None:
    sets: dict[str, list[dict[str, Any]]] = {name: [] for name in builder.ALL_SETS}
    sets[builder.POSITIVES] = [{"row": 1}]

    builder.verify_census(sets, {builder.POSITIVES: 1})
    with pytest.raises(builder.BenchmarkIntegrityError, match="census drift"):
        builder.verify_census(sets, {builder.POSITIVES: 2})


def test_the_sealed_archive_census_is_the_documented_one() -> None:
    assert builder.EXPECTED_CENSUS == {
        builder.POSITIVES: 582,
        builder.CONTROLS: 270,
        builder.DISPUTED: 86,
        builder.HARD_NEGATIVES: 157,
        builder.DIRECTNESS: 1095,
    }
    partition_total = sum(builder.EXPECTED_CENSUS[name] for name in builder.PARTITION_SETS)
    assert partition_total == builder.EXPECTED_CENSUS[builder.DIRECTNESS] == 1095


def test_admitted_row_without_a_relation_assertion_fails_closed(tmp_path: Path) -> None:
    archive, review = _write_archive(tmp_path, POPULATION)
    path = archive / CROSSWALK / "relation-assertions-v2" / "relation-assertions.json"
    path.write_text(json.dumps({"mappingAssertions": []}), encoding="utf-8")

    with pytest.raises(builder.BenchmarkIntegrityError, match="no relation assertion"):
        builder.build_rows(archive, review, CROSSWALK)


def test_relation_assertion_for_a_rejected_row_fails_closed(tmp_path: Path) -> None:
    archive, review = _write_archive(tmp_path, POPULATION)
    path = archive / CROSSWALK / "relation-assertions-v2" / "relation-assertions.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["mappingAssertions"].append(
        {"sourceConcept": "urn:source:5", "targetConcept": "urn:target:5", "relation": "skos#closeMatch"}
    )
    path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(builder.BenchmarkIntegrityError, match="carries a relation assertion"):
        builder.build_rows(archive, review, CROSSWALK)


def test_a_candidate_missing_a_sealed_verdict_fails_closed(tmp_path: Path) -> None:
    archive, review = _write_archive(tmp_path, POPULATION)
    path = archive / CROSSWALK / "crosswalk-bundle.json"
    bundle = json.loads(path.read_text(encoding="utf-8"))
    bundle["machineValidations"] = [
        v for v in bundle["machineValidations"] if v["candidate"]["id"] != "urn:candidate:1"
    ]
    path.write_text(json.dumps(bundle), encoding="utf-8")

    with pytest.raises(builder.BenchmarkIntegrityError, match="sealed verdicts, expected 2"):
        builder.build_rows(archive, review, CROSSWALK)


def test_a_missing_independent_review_fails_closed(tmp_path: Path) -> None:
    archive, review = _write_archive(tmp_path, POPULATION)
    path = review / "independent" / f"{CROSSWALK}.jsonl"
    kept = [line for line in path.read_text(encoding="utf-8").splitlines() if json.loads(line)["row"] != 3]
    path.write_text("\n".join(kept) + "\n", encoding="utf-8")

    with pytest.raises(builder.BenchmarkIntegrityError, match="no independent review"):
        builder.build_rows(archive, review, CROSSWALK)


def test_a_missing_input_context_fails_closed(tmp_path: Path) -> None:
    archive, review = _write_archive(tmp_path, POPULATION)
    path = archive / CROSSWALK / "crosswalk-bundle.json"
    bundle = json.loads(path.read_text(encoding="utf-8"))
    bundle["artifacts"] = [a for a in bundle["artifacts"] if a["id"] != "urn:artifact:context:2"]
    path.write_text(json.dumps(bundle), encoding="utf-8")

    with pytest.raises(builder.BenchmarkIntegrityError, match="no input context"):
        builder.build_rows(archive, review, CROSSWALK)


def test_output_is_byte_identical_across_runs(tmp_path: Path) -> None:
    archive, review = _write_archive(tmp_path, POPULATION)
    argv = ["--archive", str(archive), "--review", str(review), "--crosswalk", CROSSWALK]

    first, second = tmp_path / "out-a", tmp_path / "out-b"
    assert builder.main([*argv, "--output", str(first)]) == 0
    assert builder.main([*argv, "--output", str(second)]) == 0

    for name in (*builder.ALL_SETS, "manifest"):
        filename = f"{name}.jsonl" if name != "manifest" else "manifest.json"
        assert (first / filename).read_bytes() == (second / filename).read_bytes()


def test_rows_are_sorted_by_crosswalk_then_row(tmp_path: Path) -> None:
    archive, review = _write_archive(tmp_path, POPULATION)
    rows = builder.build_rows(archive, review, CROSSWALK)
    shuffled = [rows[3], rows[0], rows[5], rows[1], rows[4], rows[2]]

    sets = builder.partition(shuffled)

    keys = [(row["crosswalk"], row["row"]) for row in sets[builder.DIRECTNESS]]
    assert keys == sorted(keys)


def test_manifest_carries_the_scope_constraints_and_population_bias(tmp_path: Path) -> None:
    archive, review = _write_archive(tmp_path, POPULATION)
    output = tmp_path / "out"
    assert (
        builder.main(
            ["--archive", str(archive), "--review", str(review), "--crosswalk", CROSSWALK, "--output", str(output)]
        )
        == 0
    )

    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    entries = {entry["set"]: entry for entry in manifest["sets"]}

    assert set(entries) == set(builder.ALL_SETS)
    assert "string matcher" in manifest["populationBias"] and "recall" in manifest["populationBias"]
    assert any("recall denominator" in text for text in entries[builder.POSITIVES]["notUsableFor"])
    assert any("dense or semantic arms" in text for text in entries[builder.HARD_NEGATIVES]["notUsableFor"])
    assert any("trivially rejectable" in text for text in entries[builder.CONTROLS]["notUsableFor"])
    assert any("deliberately UNRESOLVED" in text for text in entries[builder.DISPUTED]["notUsableFor"])
    assert any("ground truth" in text for text in entries[builder.DIRECTNESS]["notUsableFor"])
    for entry in entries.values():
        assert entry["usableFor"] and entry["notUsableFor"]
        # The digest must describe the file that was actually written.
        assert entry["sha256"] == builder._sha256((output / entry["file"]).read_bytes())
