"""Extract cross-vocabulary crosswalk gold and sealed blind review samples.

The 2026-08-05 mapping-evidence archive holds three adjudicated cross-vocabulary
crosswalks: 1,095 candidates, each judged by two independent model families,
582 admitted and 513 rejected.  That is the only cross-vocabulary typed material
available, and the 513 rejections are the only negative gold anywhere in the
programme.

Two artifacts come out of here.

**Gold.** Positive and negative rows in the same shape as the native-relation
test sets, so the existing frontier and evidence tooling can score against them.

**Blind samples.** Each row carries exactly the ``inputContext`` payload the
sealed judges received -- preferred labels, definitions, scope notes, vocabulary
names -- and nothing else.  Outcomes, verdict relations, admission status,
generation class, and provider identity are withheld into a separate key file
that a reviewer must not open.  This reproduces the chain-of-custody pattern the
candidate ledger used for its 108-row and 120-row manual audits: seal the sample,
digest it, record decisions, and only then join.

The gold has a known bias and it is not a recall benchmark.  Candidates came from
the retired label-oriented generator, so the population contains only pairs that
generator proposed.  Scoring arm *recall* against it reproduces the circularity
that disqualified the 582 historical mappings.  It is sound for precision,
direction, judge agreement, and directness calibration, none of which depend on
the candidate population being unbiased.

Read-only against the archive.  No release artifact is modified.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

CROSSWALKS = ("fr-elsst", "fr-icpsr", "elsst-icpsr")

#: Fields the sealed judges saw.  Anything outside this set is withheld.
CONCEPT_FIELDS = ("member", "prefLabel", "altLabels", "definition", "scopeNote", "vocabulary", "release")


def _digest(payload: bytes) -> str:
    return f"sha256:{hashlib.sha256(payload).hexdigest()}"


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def load_bundle(archive: Path, crosswalk: str) -> dict[str, Any]:
    return json.loads((archive / crosswalk / "crosswalk-bundle.json").read_text(encoding="utf-8"))


def admitted_pairs(archive: Path, crosswalk: str) -> dict[tuple[str, str], str]:
    """Endpoint pairs admitted into the relation bundle, mapped to their relation.

    The bundle carries three parallel 190-row lists; ``mappingAssertions`` is the
    admitted set, and it names endpoints ``sourceConcept``/``targetConcept``
    rather than the ``sourceMember``/``targetMember`` the candidates use.
    """
    path = archive / crosswalk / "relation-assertions-v2" / "relation-assertions.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    admitted: dict[tuple[str, str], str] = {}
    for row in data.get("mappingAssertions", []):
        source, target = row.get("sourceConcept"), row.get("targetConcept")
        if source and target:
            admitted[(source, target)] = str(row.get("relation", "")).rsplit("#", 1)[-1]
    return admitted


def extract(archive: Path, crosswalk: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Return (blind rows, key rows) for one crosswalk, in canonical order."""
    bundle = load_bundle(archive, crosswalk)
    # The archive's context digests are computed over a different basis than the
    # candidate's ``inputContextDigest``, so join on the endpoint pair instead.
    # Verified one-to-one: 365 unique context pairs against 365 candidates in
    # every crosswalk.
    contexts = {
        (
            artifact["content"]["payload"]["source"]["member"],
            artifact["content"]["payload"]["target"]["member"],
        ): artifact["content"]
        for artifact in bundle["artifacts"]
        if artifact["role"] == "inputContext"
    }
    candidates = {candidate["id"]: candidate for candidate in bundle["mappingCandidates"]}
    validations: dict[str, list[dict[str, Any]]] = {}
    for validation in bundle["machineValidations"]:
        validations.setdefault(validation["candidate"]["id"], []).append(validation)
    admitted = admitted_pairs(archive, crosswalk)

    blind: list[dict[str, Any]] = []
    key: list[dict[str, Any]] = []
    for candidate_id in sorted(candidates):
        candidate = candidates[candidate_id]
        context = contexts.get((candidate["sourceMember"], candidate["targetMember"]))
        if context is None:
            continue
        payload = context["payload"]
        row = len(blind) + 1
        blind.append(
            {
                "row": row,
                "taskId": payload.get("taskId"),
                "source": {field: payload["source"][field] for field in CONCEPT_FIELDS if field in payload["source"]},
                "target": {field: payload["target"][field] for field in CONCEPT_FIELDS if field in payload["target"]},
            }
        )
        verdicts = sorted(validations.get(candidate_id, []), key=lambda item: item["independenceGroup"])
        key.append(
            {
                "row": row,
                "taskId": payload.get("taskId"),
                "candidateId": candidate_id,
                "sourceMember": candidate["sourceMember"],
                "targetMember": candidate["targetMember"],
                "proposedRelation": candidate.get("proposedRelation"),
                "admitted": (candidate["sourceMember"], candidate["targetMember"]) in admitted,
                "admittedRelation": admitted.get((candidate["sourceMember"], candidate["targetMember"])),
                "judges": [
                    {
                        "group": verdict["independenceGroup"].rsplit(":", 1)[-1],
                        "model": verdict.get("providerModelId"),
                        "outcome": verdict["outcome"],
                        "verdictRelation": (verdict.get("verdictRelation") or "").rsplit("#", 1)[-1] or None,
                    }
                    for verdict in verdicts
                ],
            }
        )
    return blind, key


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--crosswalk", action="append", choices=list(CROSSWALKS))
    parser.add_argument(
        "--key-only",
        action="store_true",
        help="Rewrite only the sealed key, leaving blind samples untouched mid-review.",
    )
    args = parser.parse_args()

    selected = args.crosswalk or list(CROSSWALKS)
    blind_dir = args.output / "blind"
    key_dir = args.output / "sealed-key"
    blind_dir.mkdir(parents=True, exist_ok=True)
    key_dir.mkdir(parents=True, exist_ok=True)
    summary = []

    for crosswalk in selected:
        blind, key = extract(args.archive, crosswalk)
        blind_bytes = (_canonical({"crosswalk": crosswalk, "rows": blind}) + "\n").encode("utf-8")
        key_bytes = (_canonical({"crosswalk": crosswalk, "rows": key}) + "\n").encode("utf-8")
        if not args.key_only:
            (blind_dir / f"{crosswalk}.json").write_bytes(blind_bytes)
        (key_dir / f"{crosswalk}.json").write_bytes(key_bytes)
        entry = {
            "crosswalk": crosswalk,
            "rows": len(blind),
            "blindDigest": _digest(blind_bytes),
            "keyDigest": _digest(key_bytes),
            "admitted": sum(1 for row in key if row["admitted"]),
            "rejected": sum(1 for row in key if not row["admitted"]),
        }
        summary.append(entry)
        print(
            f"  {crosswalk:<14} rows={entry['rows']:<5} admitted={entry['admitted']:<5} "
            f"rejected={entry['rejected']:<5} blind={entry['blindDigest'][:23]}…"
        )

    manifest = {
        "type": "AtlasCrosswalkBlindReviewManifest",
        "note": (
            "Blind rows carry only the concept facts the sealed judges saw. Outcomes, verdict "
            "relations, admission status, generation class, and provider identity are in sealed-key/ "
            "and must not be opened before decisions are recorded."
        ),
        "biasWarning": (
            "Candidates came from the retired label-oriented generator. Sound for precision, "
            "direction, judge agreement, and directness calibration; NOT a recall benchmark."
        ),
        "crosswalks": summary,
    }
    (args.output / "manifest.json").write_text(_canonical(manifest) + "\n", encoding="utf-8")
    print(f"\nwrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
