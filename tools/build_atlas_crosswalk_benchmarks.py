"""Split the adjudicated cross-vocabulary crosswalk archive into scoped evaluation sets.

The 2026-08-05 mapping-evidence archive holds 1,095 candidate pairs across three
crosswalks, each judged by two independent model families and re-reviewed once
blind.  Shipping that as a single "gold" file is how the programme already made
one expensive mistake: the 582 admitted mappings were scored as if they were a
recall denominator, when the candidate population came entirely from a retired
label-oriented string matcher.  No semantic-only pair -- a true mapping whose
labels share no characters -- could ever have entered the population, so recall
measured against it is recall against the string matcher's own reach.  A dense
or graph arm that surfaces exactly the pairs the string matcher cannot see is
punished for it.

The fix is not a caveat in a README.  It is to refuse to emit one undifferentiated
file at all.  Each of the five sets below answers a different question, and each
carries its own ``usableFor`` / ``notUsableFor`` constraints into the manifest so
that the scope travels with the data rather than with the memory of whoever built
it.

* ``positives`` -- the 582 admitted mappings.  Sound as a *numerator*: does an arm
  surface them, and where does it rank them.  Never a denominator.
* ``hard-negatives`` -- non-control candidates the sealed judges rejected.  These
  are string-plausible and semantically wrong, which is exactly the failure mode
  of a lexical arm, and exactly not the failure mode of a dense one.
* ``controls`` -- seeded random pairs and sibling distractors.  They measure the
  *reviewer*, not retrieval.  Only the random half is trivially rejectable: a
  sibling shares a broader concept with the true target by construction, so
  ``related`` is frequently the correct answer on it, and the sealed judges said
  so on more than half of them.
* ``disputed`` -- rejected despite both sealed judges supporting a relation.  They
  died on incompatible relation *type*, not on whether a relation exists.  They
  are the only adjudication-policy test set in the programme, and they are worth
  more unresolved than resolved.
* ``directness`` -- every row with its independent directness verdict, for rubric
  calibration only.  One reviewer per row, so it is corroboration and not ground
  truth.  An earlier build described that reviewer as having failed its control
  calibration; the E-V1/E-V2 replay retired that claim -- the 100% sealed-judge
  baseline it was measured against was a control-class exclusion applied before
  the lattice, and the reviewer is in fact more conservative on seeded negatives
  than either judge.

Membership is derived, never copied: the four decision sets are proven mutually
exclusive and proven to cover the population exactly, and the build fails closed
rather than emitting a set whose provenance it cannot account for.

Read-only against the archive and the blind review.  No release artifact is
modified and no provider is called.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

CROSSWALKS = ("fr-elsst", "fr-icpsr", "elsst-icpsr")

#: Generation classes that were seeded to be wrong.  Any evaluation that counts
#: them as retrieval failures is measuring the seeding, not the retrieval.
CONTROL_CLASSES = frozenset({"randomNegativeControl", "siblingDistractor"})

POSITIVES = "positives"
HARD_NEGATIVES = "hard-negatives"
CONTROLS = "controls"
DISPUTED = "disputed"
DIRECTNESS = "directness"

#: The four decision sets partition the population; ``directness`` re-covers all
#: of it with a different annotation and is deliberately outside the partition.
PARTITION_SETS = (POSITIVES, HARD_NEGATIVES, CONTROLS, DISPUTED)
ALL_SETS = (*PARTITION_SETS, DIRECTNESS)

POPULATION_BIAS = (
    "Every candidate in all five sets was proposed by a label-oriented string matcher, so the "
    "population cannot contain a semantically true mapping whose labels do not overlap, and no "
    "recall or coverage figure computed against it describes anything but that matcher's reach."
)

#: Scope constraints are data, not prose in a commit message.  They are written
#: into the manifest beside each set so a consumer that reads only the manifest
#: still learns what the set cannot answer.
SET_CONSTRAINTS: dict[str, dict[str, tuple[str, ...]]] = {
    POSITIVES: {
        "usableFor": ("does an arm surface known mappings", "ranking position of known mappings"),
        "notUsableFor": (
            "recall denominator — the candidate population is string-derived and cannot contain semantic-only pairs",
        ),
    },
    HARD_NEGATIVES: {
        "usableFor": ("precision against string-matching arms",),
        "notUsableFor": (
            (
                "precision against dense or semantic arms — this population contains no candidate they would "
                "uniquely propose"
            ),
        ),
    },
    CONTROLS: {
        "usableFor": ("reviewer and judge validity calibration, reported separately for the random and sibling halves",),
        "notUsableFor": (
            (
                "retrieval precision of any kind — these are seeded random pairs and sibling distractors, "
                "trivially rejectable"
            ),
            (
                "a pooled rejection rate — a sibling shares a broader concept with the true target, so "
                "'related' is often correct on it and naming it is not an error"
            ),
        ),
    },
    DISPUTED: {
        "usableFor": ("benchmark for adjudication policy: does a proposed lattice resolve these correctly",),
        "notUsableFor": (
            "positives — these are deliberately UNRESOLVED; resolving them destroys the only adjudication test set",
        ),
    },
    DIRECTNESS: {
        "usableFor": ("cross-vocabulary directness rubric calibration",),
        "notUsableFor": (
            "ground truth — one independent opinion per row, so corroboration rather than consensus",
        ),
    },
}

#: The archive is sealed and its census is known.  A build over all three
#: crosswalks that lands anywhere else has silently changed what it is reading.
EXPECTED_CENSUS: dict[str, int] = {
    POSITIVES: 582,
    CONTROLS: 270,
    DISPUTED: 86,
    HARD_NEGATIVES: 157,
    DIRECTNESS: 1095,
}


class BenchmarkIntegrityError(RuntimeError):
    """A membership, join, or census invariant failed, so nothing may be written."""


@dataclass(frozen=True)
class SealedJudge:
    """One independent model family's verdict on a candidate."""

    group: str
    outcome: str
    verdict_relation: str | None

    def as_dict(self) -> dict[str, Any]:
        return {"group": self.group, "outcome": self.outcome, "verdictRelation": self.verdict_relation}


@dataclass(frozen=True)
class CandidateRow:
    """One candidate with every fact needed to place it in exactly one set.

    ``admitted`` and ``admitted_relation`` drive membership but are not part of
    the emitted common shape: a consumer of ``hard-negatives`` should not have to
    read a field that is false on every row it holds.
    """

    crosswalk: str
    row: int
    task_id: str
    candidate_id: str
    generation_class: str
    source_member: str
    source_label: str
    target_member: str
    target_label: str
    sealed_judges: tuple[SealedJudge, ...]
    independent_verdict: str | None
    independent_directness: str | None
    admitted: bool
    admitted_relation: str | None

    @property
    def key(self) -> tuple[str, int]:
        return (self.crosswalk, self.row)

    @property
    def is_control(self) -> bool:
        return self.generation_class in CONTROL_CLASSES

    @property
    def both_judges_support(self) -> bool:
        return len(self.sealed_judges) == 2 and all(judge.outcome == "supports" for judge in self.sealed_judges)

    def common(self) -> dict[str, Any]:
        return {
            "crosswalk": self.crosswalk,
            "row": self.row,
            "taskId": self.task_id,
            "candidateId": self.candidate_id,
            "generationClass": self.generation_class,
            "sourceMember": self.source_member,
            "sourceLabel": self.source_label,
            "targetMember": self.target_member,
            "targetLabel": self.target_label,
            "sealedJudges": [judge.as_dict() for judge in self.sealed_judges],
            "independentVerdict": self.independent_verdict,
            "independentDirectness": self.independent_directness,
        }


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def _short(iri: str | None) -> str | None:
    """Local name of a SKOS relation IRI; verdicts already arrive short."""
    if not iri:
        return None
    return iri.rsplit("#", 1)[-1] or None


def generation_classes(bundle: dict[str, Any]) -> dict[str, str]:
    """Candidate id to generation class, taken from the first evidence artifact.

    A candidate can cite several evidence artifacts, but the first records the
    rule that put the pair into the population, which is the only thing that
    determines whether it is a seeded control.
    """
    evidence = {a["id"]: a.get("content", {}) for a in bundle.get("artifacts", ()) if a.get("role") == "evidence"}
    classes: dict[str, str] = {}
    for candidate in bundle.get("mappingCandidates", ()):
        names = [
            evidence[ref["id"]]["generationClass"]
            for ref in candidate.get("evidence", ())
            if ref.get("id") in evidence and evidence[ref["id"]].get("generationClass")
        ]
        if not names:
            raise BenchmarkIntegrityError(f"candidate {candidate['id']} carries no generation class")
        classes[candidate["id"]] = names[0]
    return classes


def input_contexts(bundle: dict[str, Any]) -> dict[tuple[str, str], dict[str, Any]]:
    """Sealed judge input payloads keyed by endpoint pair.

    ``candidate.inputContextDigest`` is computed over a different basis than the
    artifact digests and matches nothing, so the endpoint pair is the join key.
    It is one-to-one in this archive: 365 contexts against 365 candidates in each
    crosswalk.
    """
    contexts: dict[tuple[str, str], dict[str, Any]] = {}
    for artifact in bundle.get("artifacts", ()):
        if artifact.get("role") != "inputContext":
            continue
        payload = artifact["content"]["payload"]
        key = (payload["source"]["member"], payload["target"]["member"])
        if key in contexts:
            raise BenchmarkIntegrityError(f"duplicate input context for pair {key}")
        contexts[key] = payload
    return contexts


def sealed_verdicts(bundle: dict[str, Any]) -> dict[str, tuple[SealedJudge, ...]]:
    """Machine validations grouped by candidate, ordered by independence group."""
    grouped: dict[str, list[SealedJudge]] = {}
    for validation in bundle.get("machineValidations", ()):
        judge = SealedJudge(
            group=str(validation["independenceGroup"]).rsplit(":", 1)[-1],
            outcome=validation["outcome"],
            verdict_relation=_short(validation.get("verdictRelation")),
        )
        grouped.setdefault(validation["candidate"]["id"], []).append(judge)
    return {
        candidate_id: tuple(sorted(judges, key=lambda judge: judge.group)) for candidate_id, judges in grouped.items()
    }


def admitted_relations(archive: Path, crosswalk: str) -> dict[tuple[str, str], str]:
    """Endpoint pairs that reached the relation bundle, mapped to their relation.

    The assertion bundle names endpoints ``sourceConcept``/``targetConcept``
    rather than the ``sourceMember``/``targetMember`` the candidates use.
    """
    path = archive / crosswalk / "relation-assertions-v2" / "relation-assertions.json"
    relations: dict[tuple[str, str], str] = {}
    for assertion in _load_json(path).get("mappingAssertions", ()):
        source, target = assertion.get("sourceConcept"), assertion.get("targetConcept")
        if not source or not target:
            raise BenchmarkIntegrityError(f"{crosswalk}: mapping assertion without endpoints")
        relations[(source, target)] = _short(assertion.get("relation")) or ""
    return relations


def build_rows(archive: Path, review: Path, crosswalk: str) -> list[CandidateRow]:
    """Assemble every candidate of one crosswalk, failing closed on any broken join."""
    bundle = _load_json(archive / crosswalk / "crosswalk-bundle.json")
    contexts = input_contexts(bundle)
    classes = generation_classes(bundle)
    verdicts = sealed_verdicts(bundle)
    relations = admitted_relations(archive, crosswalk)
    candidates = {candidate["id"]: candidate for candidate in bundle.get("mappingCandidates", ())}

    key_rows = _load_json(review / "sealed-key" / f"{crosswalk}.json")["rows"]
    independent = {int(row["row"]): row for row in _load_jsonl(review / "independent" / f"{crosswalk}.jsonl")}
    if len(key_rows) != len(candidates):
        raise BenchmarkIntegrityError(
            f"{crosswalk}: sealed key holds {len(key_rows)} rows against {len(candidates)} candidates"
        )

    rows: list[CandidateRow] = []
    seen_admitted: set[tuple[str, str]] = set()
    for entry in key_rows:
        candidate_id = entry["candidateId"]
        candidate = candidates.get(candidate_id)
        if candidate is None:
            raise BenchmarkIntegrityError(f"{crosswalk}: sealed key row {entry['row']} names an unknown candidate")
        pair = (candidate["sourceMember"], candidate["targetMember"])
        payload = contexts.get(pair)
        if payload is None:
            raise BenchmarkIntegrityError(f"{crosswalk}: no input context for pair {pair}")
        judges = verdicts.get(candidate_id, ())
        if len(judges) != 2:
            raise BenchmarkIntegrityError(
                f"{crosswalk}: candidate {candidate_id} carries {len(judges)} sealed verdicts, expected 2"
            )
        review_row = independent.get(int(entry["row"]))
        if review_row is None:
            raise BenchmarkIntegrityError(f"{crosswalk}: no independent review for row {entry['row']}")

        admitted = bool(entry.get("admitted"))
        relation = relations.get(pair)
        if admitted and relation is None:
            raise BenchmarkIntegrityError(f"{crosswalk}: admitted row {entry['row']} has no relation assertion")
        if not admitted and relation is not None:
            raise BenchmarkIntegrityError(f"{crosswalk}: rejected row {entry['row']} carries a relation assertion")
        if admitted:
            seen_admitted.add(pair)

        rows.append(
            CandidateRow(
                crosswalk=crosswalk,
                row=int(entry["row"]),
                task_id=payload["taskId"],
                candidate_id=candidate_id,
                generation_class=classes[candidate_id],
                source_member=pair[0],
                source_label=payload["source"].get("prefLabel", ""),
                target_member=pair[1],
                target_label=payload["target"].get("prefLabel", ""),
                sealed_judges=judges,
                independent_verdict=review_row.get("verdict"),
                independent_directness=review_row.get("directness"),
                admitted=admitted,
                admitted_relation=relation,
            )
        )

    orphaned = set(relations) - seen_admitted
    if orphaned:
        raise BenchmarkIntegrityError(f"{crosswalk}: {len(orphaned)} relation assertions match no candidate pair")
    return rows


def partition(rows: Iterable[CandidateRow]) -> dict[str, list[dict[str, Any]]]:
    """Place every candidate into its sets and emit the per-set row shapes.

    Order of tests matters and encodes the precedence the sets were defined with:
    admission wins over everything, seeded controls are removed before any
    judgement about difficulty is made, and ``hard-negatives`` is the remainder
    rather than a rule of its own -- which is what makes the four sets a
    partition rather than four overlapping filters.
    """
    sets: dict[str, list[dict[str, Any]]] = {name: [] for name in ALL_SETS}
    for row in sorted(rows, key=lambda item: item.key):
        common = row.common()
        sets[DIRECTNESS].append(dict(common))
        if row.admitted:
            sets[POSITIVES].append({**common, "admittedRelation": row.admitted_relation})
        elif row.is_control:
            sets[CONTROLS].append({**common, "controlKind": row.generation_class})
        elif row.both_judges_support:
            # Rejected on relation *type*, not on whether a relation exists.
            sets[DISPUTED].append({**common, "competingRelations": [j.verdict_relation for j in row.sealed_judges]})
        else:
            sets[HARD_NEGATIVES].append(dict(common))
    return sets


def verify_partition(rows: Sequence[CandidateRow], sets: dict[str, list[dict[str, Any]]]) -> None:
    """Prove the four decision sets are disjoint and cover the population exactly."""
    seen: dict[tuple[str, int], str] = {}
    for name in PARTITION_SETS:
        for row in sets[name]:
            key = (row["crosswalk"], row["row"])
            if key in seen:
                raise BenchmarkIntegrityError(f"row {key} is in both {seen[key]} and {name}")
            seen[key] = name

    population = {row.key for row in rows}
    if len(population) != len(rows):
        raise BenchmarkIntegrityError("duplicate (crosswalk, row) keys in the source population")
    if seen.keys() != population:
        missing = len(population - seen.keys())
        extra = len(seen.keys() - population)
        raise BenchmarkIntegrityError(f"partition does not cover the population: {missing} missing, {extra} unknown")

    total = sum(len(sets[name]) for name in PARTITION_SETS)
    if total != len(rows):
        raise BenchmarkIntegrityError(f"partition sums to {total} rows against a population of {len(rows)}")
    if len(sets[DIRECTNESS]) != len(rows):
        raise BenchmarkIntegrityError(f"directness holds {len(sets[DIRECTNESS])} rows against {len(rows)} candidates")

    # Controls are seeded to be wrong.  An admitted control would mean either the
    # seeding or the adjudication is broken, and either way the calibration set
    # no longer calibrates anything.
    admitted_controls = [row.key for row in rows if row.is_control and row.admitted]
    if admitted_controls:
        raise BenchmarkIntegrityError(
            f"{len(admitted_controls)} seeded controls were admitted, e.g. {admitted_controls[0]}"
        )


def verify_census(sets: dict[str, list[dict[str, Any]]], expected: dict[str, int]) -> None:
    """Compare set sizes against the known census of the sealed archive."""
    actual = {name: len(rows) for name, rows in sets.items()}
    drift = {name: (count, actual.get(name)) for name, count in expected.items() if actual.get(name) != count}
    if drift:
        detail = ", ".join(f"{name}: expected {want}, built {got}" for name, (want, got) in sorted(drift.items()))
        raise BenchmarkIntegrityError(f"census drift against the sealed archive — {detail}")


def write_sets(output: Path, sets: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    """Write the JSONL sets and return the manifest describing them."""
    output.mkdir(parents=True, exist_ok=True)
    entries = []
    for name in ALL_SETS:
        filename = f"{name}.jsonl"
        payload = "".join(_canonical(row) + "\n" for row in sets[name]).encode("utf-8")
        (output / filename).write_bytes(payload)
        entries.append(
            {
                "set": name,
                "file": filename,
                "rows": len(sets[name]),
                "sha256": _sha256(payload),
                "usableFor": list(SET_CONSTRAINTS[name]["usableFor"]),
                "notUsableFor": list(SET_CONSTRAINTS[name]["notUsableFor"]),
            }
        )

    manifest = {
        "type": "AtlasCrosswalkBenchmarkManifest",
        "populationBias": POPULATION_BIAS,
        "partition": list(PARTITION_SETS),
        "rows": sum(len(sets[name]) for name in PARTITION_SETS),
        "sets": entries,
    }
    (output / "manifest.json").write_text(_canonical(manifest) + "\n", encoding="utf-8")
    return manifest


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--archive", type=Path, required=True, help="mapping-evidence archive directory")
    parser.add_argument("--review", type=Path, required=True, help="blind-review directory (independent/, sealed-key/)")
    parser.add_argument("--output", type=Path, required=True, help="directory to write the five sets and manifest into")
    parser.add_argument("--crosswalk", action="append", choices=list(CROSSWALKS), help="restrict to one crosswalk")
    args = parser.parse_args(argv)

    selected = tuple(args.crosswalk) if args.crosswalk else CROSSWALKS
    rows: list[CandidateRow] = []
    for crosswalk in selected:
        rows.extend(build_rows(args.archive, args.review, crosswalk))

    sets = partition(rows)
    verify_partition(rows, sets)
    if set(selected) == set(CROSSWALKS):
        verify_census(sets, EXPECTED_CENSUS)
    else:
        print("partial build: census against the sealed archive not enforced")

    manifest = write_sets(args.output, sets)
    for entry in manifest["sets"]:
        print(f"  {entry['set']:<15} rows={entry['rows']:<6} sha256={entry['sha256'][:16]}…")
    print(f"\n{manifest['rows']} rows partitioned across {', '.join(PARTITION_SETS)}")
    print(f"wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
