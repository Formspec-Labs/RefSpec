#!/usr/bin/env python3
"""Offline crosswalk qualification runner: extract, generate, qualify, bundle.

Qualification never runs inside an atlas build.  This tool runs beside one: it
reads two pinned managed releases, proposes a diverse candidate slice, asks two
independent model families about each candidate, and writes one sealed
digest-pinned ``CrosswalkBundle``.  Atlas 2.0 can select qualified or reviewed
proofs from that bundle through its trusted crosswalk machine-proof adapter;
qualification remains separate from atlas construction.

Four stages, because opening a real managed release is expensive (ELSST takes
about eight minutes) and provider calls cost money.  Each stage writes a file
the next one reads, so a failed run resumes instead of re-paying:

    extract   two managed releases -> concepts-{source,target}.json
    generate  concepts             -> candidates.json  (deterministic, seeded)
    qualify   candidates           -> receipts.jsonl   (one row per call)
    bundle    candidates+receipts  -> crosswalk-bundle.json + receipt

``qualify`` is resumable: a candidate/family pair already present in
``receipts.jsonl`` is never called twice.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from collections import Counter
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from refspec.atlas import qualification as qual
from refspec.atlas import qualification_batch as qbatch
from refspec.atlas.concept_release import (
    PinnedManagedConceptRelease,
    PinnedManagedReleaseRingAssignment,
    PinnedSourceConceptRelease,
)
from refspec.atlas.federal_register import (
    PinnedFederalRegisterManagedConceptRelease,
    PinnedFederalRegisterThesaurus2025AtlasRelease,
)
from refspec.atlas.icpsr import (
    ICPSR_MANAGED_RELEASE_MANIFEST_TYPE,
    PinnedIcpsrManagedConceptRelease,
    PinnedIcpsrSubjectAtlasRelease,
)
from refspec.atlas.machine_evidence import (
    PinnedCrosswalkMachineProof,
    build_machine_evidence_from_crosswalk_proof,
)
from refspec.atlas.model import CrosswalkBundle, PinnedManagedRelease, VerifiedManagedReleaseSource
from refspec.atlas.relation_assertion import RelationAssertionBundle
from refspec.registry.infrastructure.semantic_foundation import MappingAssertion
from refspec.registry.infrastructure.source_concept_release import SourceConceptReleaseView
from refspec.storage import canonical_json

CONCEPTS_SOURCE = "concepts-source.json"
CONCEPTS_TARGET = "concepts-target.json"
CANDIDATES = "candidates.json"
RECEIPTS = "receipts.jsonl"
SCORING_RECEIPTS = "scoring-receipts.jsonl"
BUNDLE = "crosswalk-bundle.json"
RUN_RECEIPT = "qualification-receipt.json"
MODELS_RECEIPT = "models-list.json"
SCORER_MODELS_RECEIPT = "scorer-models-list.json"
SCORING_SPEND = "scoring-spend.json"
SCORING_BATCH_SIDECAR = "scoring-batch-jobs.json"

_FEDERAL_REGISTER_2025_MANIFEST_TYPE = "urn:ref:type:FederalRegisterThesaurus2025ManagedReleaseManifest"


def _file_digest(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, payload: Any) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = canonical_json(payload) + "\n"
    path.write_text(text, encoding="utf-8")
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _open_managed_release(
    manifest_path: Path,
    expected_manifest_digest: str,
) -> VerifiedManagedReleaseSource:
    """Open one exact qualification input through its source-specific reader."""

    try:
        manifest = json.loads(manifest_path.read_bytes().decode("utf-8"))
    except (OSError, UnicodeDecodeError, ValueError):
        manifest = None
    declared_type = manifest.get("type") if isinstance(manifest, dict) else None
    if declared_type == _FEDERAL_REGISTER_2025_MANIFEST_TYPE:
        return PinnedFederalRegisterThesaurus2025AtlasRelease.open(
            manifest_path,
            expected_manifest_digest=expected_manifest_digest,
        )
    if declared_type == ICPSR_MANAGED_RELEASE_MANIFEST_TYPE:
        return PinnedIcpsrSubjectAtlasRelease.open(
            manifest_path,
            expected_manifest_digest=expected_manifest_digest,
        )
    return PinnedManagedRelease.open(
        manifest_path,
        expected_manifest_digest=expected_manifest_digest,
    )


def _open_qualification_release(
    manifest_path: Path,
    expected_manifest_digest: str,
) -> tuple[str, Any]:
    """Open either managed-release or SourceConceptRelease qualification bytes."""

    try:
        manifest = json.loads(manifest_path.read_bytes().decode("utf-8"))
    except (OSError, UnicodeDecodeError, ValueError):
        manifest = None
    if isinstance(manifest, Mapping) and manifest.get("packageKind") == "sourceConceptRelease":
        return (
            "sourceConceptRelease",
            SourceConceptReleaseView.open(
                manifest_path,
                expected_manifest_digest=expected_manifest_digest,
            ),
        )
    return "managedRelease", _open_managed_release(manifest_path, expected_manifest_digest).verified_view()


def _open_relation_release(
    manifest_path: Path,
    *,
    release_id: str | None,
    ring_assignment_path: Path | None,
) -> PinnedSourceConceptRelease | PinnedManagedConceptRelease:
    """Open one exact subject endpoint for relation-bundle emission."""

    digest = _file_digest(manifest_path)
    try:
        manifest = json.loads(manifest_path.read_bytes().decode("utf-8"))
    except (OSError, UnicodeDecodeError, ValueError):
        manifest = None
    if isinstance(manifest, Mapping) and manifest.get("packageKind") == "sourceConceptRelease":
        release = PinnedSourceConceptRelease.open(
            manifest_path,
            expected_manifest_digest=digest,
        )
        if release_id is not None and release.release_id != release_id:
            raise SystemExit(f"source-concept release is {release.release_id}, not {release_id}")
        if ring_assignment_path is not None:
            raise SystemExit("a SourceConceptRelease does not take a managed ring assignment")
        return release
    if release_id is None or ring_assignment_path is None:
        raise SystemExit("a managed endpoint requires both --*-release-id and --*-ring-assignment")
    assignment = PinnedManagedReleaseRingAssignment.open(
        ring_assignment_path,
        expected_file_digest=_file_digest(ring_assignment_path),
    )
    reader = _managed_concept_release_reader(manifest)
    return reader.open(
        manifest_path,
        expected_manifest_digest=digest,
        release_id=release_id,
        ring_assignment=assignment,
    )


def _managed_concept_release_reader(manifest: object) -> type[PinnedManagedConceptRelease]:
    """Select the exact managed concept reader for custom package shapes."""

    declared_type = manifest.get("type") if isinstance(manifest, Mapping) else None
    if declared_type == _FEDERAL_REGISTER_2025_MANIFEST_TYPE:
        return PinnedFederalRegisterManagedConceptRelease
    if declared_type == ICPSR_MANAGED_RELEASE_MANIFEST_TYPE:
        return PinnedIcpsrManagedConceptRelease
    return PinnedManagedConceptRelease


def _context_dict(concept: qual.AtlasConceptContext) -> dict[str, Any]:
    payload: dict[str, Any] = {"member": concept.member, "prefLabel": concept.pref_label}
    if concept.alt_labels:
        payload["altLabels"] = list(concept.alt_labels)
    if concept.definition:
        payload["definition"] = concept.definition
    if concept.scope_note:
        payload["scopeNote"] = concept.scope_note
    return payload


def _context_from_dict(payload: Mapping[str, Any]) -> qual.AtlasConceptContext:
    return qual.AtlasConceptContext(
        member=str(payload["member"]),
        pref_label=str(payload["prefLabel"]),
        alt_labels=tuple(payload.get("altLabels", ())),
        definition=payload.get("definition"),
        scope_note=payload.get("scopeNote"),
    )


def _concept_dict(concept: qual.AtlasConcept) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "member": concept.member,
        "prefLabel": concept.pref_label,
        "release": concept.release,
    }
    if concept.alt_labels:
        payload["altLabels"] = list(concept.alt_labels)
    if concept.broader:
        payload["broader"] = list(concept.broader)
    if concept.definition:
        payload["definition"] = concept.definition
    if concept.scope_note:
        payload["scopeNote"] = concept.scope_note
    if concept.vocabulary:
        payload["vocabulary"] = concept.vocabulary
    if concept.parents:
        payload["parents"] = [_context_dict(value) for value in concept.parents]
    if concept.children:
        payload["children"] = [_context_dict(value) for value in concept.children]
    return payload


def _concept_from_dict(payload: Mapping[str, Any]) -> qual.AtlasConcept:
    return qual.AtlasConcept(
        member=str(payload["member"]),
        release=str(payload["release"]),
        pref_label=str(payload["prefLabel"]),
        alt_labels=tuple(payload.get("altLabels", ())),
        definition=payload.get("definition"),
        scope_note=payload.get("scopeNote"),
        broader=tuple(payload.get("broader", ())),
        vocabulary=str(payload.get("vocabulary", "")),
        parents=tuple(_context_from_dict(value) for value in payload.get("parents", ())),
        children=tuple(_context_from_dict(value) for value in payload.get("children", ())),
    )


def _pair_from_dict(payload: Mapping[str, Any]) -> qual.CandidatePair:
    return qual.CandidatePair(
        source=_concept_from_dict(payload["source"]),
        target=_concept_from_dict(payload["target"]),
        generation_class=str(payload["generationClass"]),
        evidence=dict(payload["evidence"]),
        generation_policy=str(payload.get("generationPolicy", qual.CANDIDATE_GENERATION_POLICY)),
    )


# ---------------------------------------------------------------------------
# extract
# ---------------------------------------------------------------------------


def command_extract(args: argparse.Namespace) -> int:
    output = Path(args.output)
    for role, manifest, release_iri, vocabulary, filename in (
        ("source", args.source_manifest, args.source_release_iri, args.source_vocabulary, CONCEPTS_SOURCE),
        ("target", args.target_manifest, args.target_release_iri, args.target_vocabulary, CONCEPTS_TARGET),
    ):
        path = Path(manifest)
        digest = _file_digest(path)
        print(f"opening {role} release {path} ({digest})", file=sys.stderr, flush=True)
        release_kind, view = _open_qualification_release(path, digest)
        if release_kind == "sourceConceptRelease":
            if release_iri is not None and release_iri != view.release_id:
                raise SystemExit(
                    f"{role} SourceConceptRelease is {view.release_id}, not the requested {release_iri}"
                )
            concepts = qual.concepts_from_source_release(
                view,
                language=args.language,
                vocabulary=vocabulary,
            )
        else:
            concepts = qual.concepts_from_view(
                view,
                language=args.language,
                release_iri=release_iri,
                vocabulary=vocabulary,
            )
        if not concepts:
            raise SystemExit(f"{role} release yielded no concepts; check --{role}-release-iri and --language")
        written = _write_json(
            output / filename,
            {
                "concepts": [_concept_dict(concept) for concept in concepts],
                "conceptCount": len(concepts),
                "language": args.language,
                "manifestDigest": digest,
                # The name, never the absolute path: the digest is the identity,
                # and the research archive strips machine-local paths anyway.
                "manifestName": path.name,
                "publicationReleaseId": view.release_id,
                "referenceRelease": release_iri or min({concept.release for concept in concepts}),
                "releaseKind": release_kind,
                "role": role,
                "vocabulary": vocabulary,
            },
        )
        print(f"  {len(concepts)} concepts -> {output / filename} ({written})", file=sys.stderr, flush=True)
    return 0


# ---------------------------------------------------------------------------
# generate
# ---------------------------------------------------------------------------


def command_generate(args: argparse.Namespace) -> int:
    output = Path(args.output)
    source = _read_json(output / CONCEPTS_SOURCE)
    target = _read_json(output / CONCEPTS_TARGET)
    if args.production and args.limit:
        raise SystemExit("--production uses the complete deterministic catalog and does not accept --limit")
    limits = dict(qual.DEFAULT_CLASS_LIMITS)
    for item in args.limit or ():
        name, _, value = item.partition("=")
        if name not in qual.GENERATION_CLASSES:
            raise SystemExit(f"unknown generation class {name!r}")
        limits[name] = int(value)
    pairs = qual.generate_candidate_pairs(
        [_concept_from_dict(item) for item in source["concepts"]],
        [_concept_from_dict(item) for item in target["concepts"]],
        limits=None if args.production else limits,
        seed=args.seed,
        production=bool(args.production),
    )
    rows: list[dict[str, Any]] = []
    for pair in pairs:
        entry = qual.assemble_candidate(
            pair,
            generated_at=args.generated_at,
            readings=(),
            protocol=qual.PROTOCOL,
        )
        context = next(item for item in entry.artifacts if item.role == "inputContext")
        rows.append(
            {
                "candidateId": entry.candidate.identifier,
                "evidence": dict(pair.evidence),
                "generationClass": pair.generation_class,
                "generationPolicy": pair.generation_policy,
                "inputDigest": context.content_digest,
                "scoringInputDigest": qual.scoring_input_digest(pair),
                "source": _concept_dict(pair.source),
                "target": _concept_dict(pair.target),
            }
        )
    counts = Counter(row["generationClass"] for row in rows)
    digest = _write_json(
        output / CANDIDATES,
        {
            "candidates": rows,
            "countsByClass": dict(sorted(counts.items())),
            "generatedAt": args.generated_at,
            "coverageMode": (
                qual.PRODUCTION_COVERAGE_MODE if args.production else qual.PILOT_COVERAGE_MODE
            ),
            "generationPolicy": (
                qual.PRODUCTION_CANDIDATE_GENERATION_POLICY
                if args.production
                else qual.PILOT_CANDIDATE_GENERATION_POLICY
            ),
            "limits": None if args.production else dict(sorted(limits.items())),
            "productionFloor": qual.PRODUCTION_FLOOR if args.production else None,
            # The protocol is part of what a candidate *is*: it seals a
            # different rubric and a different payload, so a catalog belongs to
            # exactly one protocol and says which.
            "protocol": qual.PROTOCOL,
            "proposedRelation": qual.PROPOSED_RELATION,
            "seed": args.seed,
            "sourceManifestDigest": source["manifestDigest"],
            "targetManifestDigest": target["manifestDigest"],
            "total": len(rows),
        },
    )
    print(canonical_json({"total": len(rows), "byClass": dict(sorted(counts.items())), "digest": digest}))
    return 0


# ---------------------------------------------------------------------------
# qualify
# ---------------------------------------------------------------------------


def _projected_cost(family: qual.ValidatorFamily, calls: int) -> float:
    tracker = qual.SpendTracker(family)
    return tracker.cost(calls * 900, calls * family.max_output_tokens)


def _coverage_mode(catalog: Mapping[str, Any]) -> str:
    mode = str(catalog.get("coverageMode", qual.PILOT_COVERAGE_MODE))
    if mode not in {qual.PILOT_COVERAGE_MODE, qual.PRODUCTION_COVERAGE_MODE}:
        raise SystemExit(f"candidate catalog has unsupported coverage mode {mode!r}")
    if mode == qual.PRODUCTION_COVERAGE_MODE:
        if catalog.get("generationPolicy") != qual.PRODUCTION_CANDIDATE_GENERATION_POLICY:
            raise SystemExit("production candidate catalog does not name the production generation policy")
        if catalog.get("productionFloor") != qual.PRODUCTION_FLOOR or catalog.get("limits") is not None:
            raise SystemExit("production candidate catalog carries a pilot limit or an unsupported floor")
    return mode


def _refuse_production_subset(catalog: Mapping[str, Any], limit: int | None) -> None:
    if _coverage_mode(catalog) == qual.PRODUCTION_COVERAGE_MODE and limit is not None:
        raise SystemExit("production qualification must process the complete candidate catalog")


def command_qualify(args: argparse.Namespace) -> int:
    output = Path(args.output)
    catalog = _read_json(output / CANDIDATES)
    protocol = qbatch.run_protocol(catalog)
    rows = catalog["candidates"]
    _refuse_production_subset(catalog, args.max_candidates)
    if args.max_candidates is not None:
        # Spread, never a head slice: candidates.json is written in class order,
        # so `rows[:N]` for any N under the equality count would call only
        # label-equal pairs and the run could not refuse anything.
        rows = qual.stratified_subset(rows, args.max_candidates)

    families = [qual.VALIDATOR_FAMILIES[name] for name in args.families.split(",")]
    transport = qual.UrllibTransport()
    keys = {family.name: qual.load_env_value(args.env, family.api_key_env) for family in families}

    resolved: dict[str, str] = {}
    model_receipts: list[dict[str, Any]] = []
    for family in families:
        model_ids, receipt = qual.list_models(transport, family, keys[family.name])
        model_id, rule = qual.resolve_validator_model(family, model_ids)
        receipt["resolved_model_id"] = model_id
        receipt["resolution_rule"] = rule
        model_receipts.append(receipt)
        resolved[family.name] = model_id
        print(f"{family.name}: {model_id} ({rule})", file=sys.stderr, flush=True)
    _write_json(output / MODELS_RECEIPT, {"families": model_receipts})

    done: set[tuple[str, str]] = set()
    receipts_path = output / RECEIPTS
    if receipts_path.exists():
        for line in receipts_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            record = json.loads(line)
            done.add((str(record["candidate_id"]), str(record["family"])))

    trackers = {family.name: qual.SpendTracker(family, cap_usd=args.cap.get(family.name)) for family in families}
    pending = [(row, family) for row in rows for family in families if (row["candidateId"], family.name) not in done]
    projection = sum(_projected_cost(family, sum(1 for _, item in pending if item is family)) for family in families)
    print(
        f"{len(pending)} calls pending; conservative projection ${projection:.2f} "
        f"against a ${qual.TOTAL_SPEND_CAP_USD:.2f} total cap",
        file=sys.stderr,
        flush=True,
    )
    if projection > qual.TOTAL_SPEND_CAP_USD:
        raise SystemExit(
            f"projected ${projection:.2f} exceeds the ${qual.TOTAL_SPEND_CAP_USD:.2f} total cap; shrink the slice"
        )

    stopped: dict[str, str] = {}
    with receipts_path.open("a", encoding="utf-8") as handle:
        for index, (row, family) in enumerate(pending, start=1):
            if family.name in stopped:
                continue
            pair = _pair_from_dict(row)
            try:
                receipt = qual.validate_candidate(
                    transport,
                    family,
                    keys[family.name],
                    resolved[family.name],
                    pair=pair,
                    candidate_id=row["candidateId"],
                    input_digest=row["inputDigest"],
                    tracker=trackers[family.name],
                    protocol=protocol,
                )
            except qual.SpendCapReached as error:
                stopped[family.name] = str(error)
                print(f"STOP {family.name}: {error}", file=sys.stderr, flush=True)
                continue
            handle.write(canonical_json(receipt) + "\n")
            handle.flush()
            if index % 25 == 0 or index == len(pending):
                spend = sum(tracker.assumed_cost_usd for tracker in trackers.values())
                print(f"  {index}/{len(pending)}  ${spend:.3f}", file=sys.stderr, flush=True)

    summary = {
        "spendByFamily": [tracker.summary() for tracker in trackers.values()],
        "stopped": stopped,
        "totalAssumedCostUsd": round(sum(tracker.assumed_cost_usd for tracker in trackers.values()), 6),
    }
    _write_json(output / "spend.json", summary)
    print(canonical_json(summary))
    return 0


# ---------------------------------------------------------------------------
# score (serial)
# ---------------------------------------------------------------------------


def _scoring_rows(catalog: Mapping[str, Any], limit: int | None = None) -> list[Mapping[str, Any]]:
    _refuse_production_subset(catalog, limit)
    rows = list(catalog["candidates"])
    return rows if limit is None else list(qual.stratified_subset(rows, limit))


def _scoring_candidate_rows(catalog: Mapping[str, Any], limit: int | None = None) -> list[qbatch.CandidateRow]:
    return [
        qbatch.CandidateRow(
            candidate_id=str(row["candidateId"]),
            pair=(pair := _pair_from_dict(row)),
            input_digest=str(row.get("scoringInputDigest") or qual.scoring_input_digest(pair)),
        )
        for row in _scoring_rows(catalog, limit)
    ]


def command_score(args: argparse.Namespace) -> int:
    output = Path(args.output)
    catalog = _read_json(output / CANDIDATES)
    rows = _scoring_rows(catalog, args.max_candidates)
    try:
        family = qual.VALIDATOR_FAMILIES[args.family]
    except KeyError as error:
        raise SystemExit(f"unknown scorer family {args.family!r}") from error
    transport = qual.UrllibTransport()
    key = qual.load_env_value(args.env, family.api_key_env)
    model_ids, model_receipt = qual.list_models(transport, family, key)
    model_id, rule = qual.resolve_validator_model(family, model_ids)
    model_receipt["resolved_model_id"] = model_id
    model_receipt["resolution_rule"] = rule
    _write_json(output / SCORER_MODELS_RECEIPT, {"families": [model_receipt]})

    receipts_path = output / SCORING_RECEIPTS
    done = qbatch.read_receipt_pairs(receipts_path)
    pending = [row for row in rows if (str(row["candidateId"]), family.name) not in done]
    tracker = qual.SpendTracker(family, cap_usd=args.cap.get(family.name))
    projection = _projected_cost(family, len(pending))
    if projection > tracker.cap:
        raise SystemExit(
            f"{family.name}: scoring {len(pending)} candidates projects ${projection:.4f}, "
            f"above the ${tracker.cap:.2f} cap"
        )
    with receipts_path.open("a", encoding="utf-8") as handle:
        for row in pending:
            pair = _pair_from_dict(row)
            receipt = qual.score_candidate(
                transport,
                family,
                key,
                model_id,
                pair=pair,
                candidate_id=str(row["candidateId"]),
                input_digest=str(row.get("scoringInputDigest") or qual.scoring_input_digest(pair)),
                tracker=tracker,
            )
            handle.write(canonical_json(receipt) + "\n")
            handle.flush()
    summary = {
        "protocol": qual.SCORING_PROTOCOL,
        "spendByFamily": [tracker.summary()],
        "totalAssumedCostUsd": round(tracker.assumed_cost_usd, 6),
    }
    _write_json(output / SCORING_SPEND, summary)
    print(canonical_json(summary))
    return 0


# ---------------------------------------------------------------------------
# bundle
# ---------------------------------------------------------------------------


def command_bundle(args: argparse.Namespace) -> int:
    output = Path(args.output)
    catalog = _read_json(output / CANDIDATES)
    coverage_mode = _coverage_mode(catalog)
    candidate_ids = {str(row["candidateId"]) for row in catalog["candidates"]}
    by_candidate: dict[str, list[dict[str, Any]]] = {}
    outcomes: Counter[str] = Counter()
    receipt_rows: list[dict[str, Any]] = []
    receipt_path = output / RECEIPTS
    for line in receipt_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        record = json.loads(line)
        receipt_rows.append(record)
        outcomes[str(record.get("outcome"))] += 1
        by_candidate.setdefault(str(record["candidate_id"]), []).append(record)

    unknown_candidates = sorted(set(by_candidate) - candidate_ids)
    if unknown_candidates:
        raise SystemExit(f"receipt log names candidates outside the catalog: {unknown_candidates}")
    receipt_keys = [(str(row["candidate_id"]), str(row["family"])) for row in receipt_rows]
    if len(receipt_keys) != len(set(receipt_keys)):
        raise SystemExit("receipt log repeats a candidate/family call")
    if coverage_mode == qual.PRODUCTION_COVERAGE_MODE:
        expected_keys = {
            (candidate_id, family) for candidate_id in candidate_ids for family in qual.VALIDATOR_FAMILIES
        }
        missing = sorted(expected_keys - set(receipt_keys))
        extra = sorted(set(receipt_keys) - expected_keys)
        if missing or extra:
            raise SystemExit(
                "production bundle requires exactly one receipt for both blind judge families per candidate; "
                f"missing={missing[:5]!r}, extra={extra[:5]!r}"
            )

    scoring_path = output / SCORING_RECEIPTS
    scoring_rows = [] if not scoring_path.exists() else [
        json.loads(line)
        for line in scoring_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    scoring_by_candidate: dict[str, list[dict[str, Any]]] = {}
    for record in scoring_rows:
        scoring_by_candidate.setdefault(str(record["candidate_id"]), []).append(record)
    unknown_scored = sorted(set(scoring_by_candidate) - candidate_ids)
    if unknown_scored:
        raise SystemExit(f"scoring receipts name candidates outside the catalog: {unknown_scored}")
    scoring_keys = [(str(row["candidate_id"]), str(row["family"])) for row in scoring_rows]
    if len(scoring_keys) != len(set(scoring_keys)):
        raise SystemExit("scoring receipts repeat a candidate/family call")

    protocol = qbatch.run_protocol(catalog)
    entries: list[qual.AssembledCandidate] = []
    readings_by_candidate: dict[str, tuple[qual.ValidationReading, ...]] = {}
    verdicts: Counter[str] = Counter()
    by_class: dict[str, Counter[str]] = {}
    for row in catalog["candidates"]:
        pair = _pair_from_dict(row)
        readings: list[qual.ValidationReading] = []
        for receipt in sorted(by_candidate.get(row["candidateId"], []), key=lambda item: str(item["family"])):
            family = qual.VALIDATOR_FAMILIES[str(receipt["family"])]
            reading = qual.reading_from_receipt(receipt, family, str(receipt["model_id"]))
            if reading is None:
                continue
            if reading.protocol != protocol:
                raise SystemExit(
                    f"receipt for {row['candidateId']} speaks {reading.protocol}, "
                    f"but the candidate catalog is {protocol}"
                )
            readings.append(reading)
            verdicts[f"{family.name}:{reading.verdict}"] += 1
        entry = qual.assemble_candidate(
            pair,
            generated_at=catalog["generatedAt"],
            readings=tuple(readings),
            protocol=protocol,
        )
        if entry.candidate.identifier != row["candidateId"]:
            raise SystemExit(f"candidate identity moved for {row['candidateId']}; regenerate before bundling")
        entries.append(entry)
        readings_by_candidate[str(row["candidateId"])] = tuple(readings)
        tally = by_class.setdefault(pair.generation_class, Counter())
        tally["candidates"] += 1
        tally[f"validations:{len(readings)}"] += 1

    bundle = qual.crosswalk_bundle(entries)
    qualified = bundle.qualified()
    # Two different measurements, kept apart on purpose. `qualified` means
    # "earned a mapping" and includes directional relations. The distractor
    # floor asks the narrower question: did anything claim substitutability?
    substitutable = {
        "http://www.w3.org/2004/02/skos/core#exactMatch",
        "http://www.w3.org/2004/02/skos/core#closeMatch",
    }
    relations = bundle.adjudicated_relations()
    for entry in entries:
        if entry.candidate.identifier not in qualified:
            continue
        by_class[entry.pair.generation_class]["qualified"] += 1
        relation = relations.get(entry.candidate.identifier)
        if relation is None or relation in substitutable:
            by_class[entry.pair.generation_class]["qualifiedAsSubstitutable"] += 1

    candidate_accounting: list[dict[str, Any]] = []
    for entry in entries:
        candidate_id = entry.candidate.identifier
        readings = readings_by_candidate[candidate_id]
        control = entry.pair.generation_class in qual.CONTROL_GENERATION_CLASSES
        relation = relations.get(candidate_id)
        if control:
            disposition = "controlled"
        elif relation is not None:
            disposition = "admitted"
        elif len(readings) < len(qual.VALIDATOR_FAMILIES):
            disposition = "incomplete"
        elif any(reading.outcome == "abstains" for reading in readings):
            disposition = "abstained"
        else:
            disposition = "rejected"
        pins = []
        for record in sorted(by_candidate.get(candidate_id, ()), key=lambda value: str(value["family"])):
            receipt_digest = "sha256:" + hashlib.sha256(
                (canonical_json(record) + "\n").encode("utf-8")
            ).hexdigest()
            pins.append(
                {
                    "family": str(record["family"]),
                    "outcome": str(record.get("outcome")),
                    "receiptDigest": receipt_digest,
                }
            )
        scorer_pins: list[dict[str, Any]] = []
        valid_scores: list[qual.ScoreReading] = []
        for record in sorted(scoring_by_candidate.get(candidate_id, ()), key=lambda value: str(value["family"])):
            family = qual.VALIDATOR_FAMILIES[str(record["family"])]
            reading = qual.score_reading_from_receipt(record, family, str(record["model_id"]))
            if reading is not None:
                valid_scores.append(reading)
            scorer_pins.append(
                {
                    "family": family.name,
                    "modelId": str(record["model_id"]),
                    "endpoint": qual.endpoint_host(str(record.get("request_url") or "")),
                    "outcome": str(record.get("outcome")),
                    "deterministicChecksPassed": bool(
                        reading is not None and reading.deterministic_checks_passed
                    ),
                    "requestSha256": str(record.get("request_sha256") or ""),
                    "responseSha256": str(record.get("response_sha256") or ""),
                    "receiptDigest": "sha256:"
                    + hashlib.sha256((canonical_json(record) + "\n").encode("utf-8")).hexdigest(),
                }
            )
        accounting: dict[str, Any] = {
            "candidateId": candidate_id,
            "generationClass": entry.pair.generation_class,
            "control": control,
            "scored": any(reading.deterministic_checks_passed for reading in valid_scores),
            "scorerReceipts": scorer_pins,
            "judgeReceipts": pins,
            "judged": (
                len(readings) == len(qual.VALIDATOR_FAMILIES)
                and all(reading.deterministic_checks_passed for reading in readings)
            ),
            "disposition": disposition,
        }
        if disposition == "admitted":
            accounting["relation"] = relation
        candidate_accounting.append(accounting)

    disposition_counts = Counter(str(row["disposition"]) for row in candidate_accounting)
    accounting_counts = {
        "generated": len(candidate_accounting),
        "scored": sum(int(bool(row["scored"])) for row in candidate_accounting),
        "scorerReceipts": sum(len(row["scorerReceipts"]) for row in candidate_accounting),
        "judgeReceipts": sum(len(row["judgeReceipts"]) for row in candidate_accounting),
        "judged": sum(int(bool(row["judged"])) for row in candidate_accounting),
        "abstained": disposition_counts["abstained"],
        "rejected": disposition_counts["rejected"],
        "controlled": disposition_counts["controlled"],
        "admitted": disposition_counts["admitted"],
        "incomplete": disposition_counts["incomplete"],
    }

    path = output / BUNDLE
    if path.exists() and args.replace:
        path.unlink()
    bundle.write(path)
    pin = bundle.pin()

    receipt: dict[str, Any] = {
        "type": qual.QUALIFICATION_RUN_RECEIPT_TYPE,
        "schemaVersion": qual.QUALIFICATION_RUN_RECEIPT_VERSION,
        "bundle": {
            "file": BUNDLE,
            "fileDigest": pin["fileDigest"],
            "id": pin["id"],
            "bundleDigest": pin["digest"],
            "mediaType": pin["mediaType"],
        },
        "callOutcomes": dict(sorted(outcomes.items())),
        "candidateAccounting": candidate_accounting,
        "candidateCatalog": {
            "file": CANDIDATES,
            "fileDigest": _file_digest(output / CANDIDATES),
            "total": len(candidate_accounting),
        },
        "candidateGenerationPolicy": catalog["generationPolicy"],
        "candidatesByClass": {name: dict(sorted(tally.items())) for name, tally in sorted(by_class.items())},
        "determinism": (
            "NOT reproducible. This artifact records provider calls; a rebuild will not "
            "reproduce it byte-for-byte. Every call carries its own request and response digest, "
            "and the bundle it produced is pinned by digest instead."
        ),
        # The admission rule this run actually applied.
        "eligibilityPolicy": "twoIndependentMachinesRelationAgreement",
        "coverageMode": coverage_mode,
        "counts": accounting_counts,
        "generatedAt": catalog["generatedAt"],
        "productionFloor": catalog.get("productionFloor"),
        "protocol": protocol,
        "qualifiedCandidates": len(qualified),
        "relationsByPredicate": dict(sorted(Counter(relations.values()).items())),
        "receiptLog": {
            "file": RECEIPTS,
            "fileDigest": _file_digest(receipt_path),
            "total": len(receipt_rows),
        },
        "scoring": {
            "status": (
                "complete"
                if accounting_counts["scored"] == accounting_counts["generated"]
                else "incomplete"
                if scoring_rows
                else "notRun"
            ),
            "protocol": qual.SCORING_PROTOCOL,
            "receiptLog": {
                "file": SCORING_RECEIPTS,
                "fileDigest": _file_digest(scoring_path) if scoring_path.exists() else None,
                "total": len(scoring_rows),
            },
        },
        "sourceManifestDigest": catalog["sourceManifestDigest"],
        "targetManifestDigest": catalog["targetManifestDigest"],
        "totalCandidates": len(entries),
        "verdictsByFamily": dict(sorted(verdicts.items())),
    }
    if (output / "spend.json").exists():
        receipt["spend"] = _read_json(output / "spend.json")
    if (output / MODELS_RECEIPT).exists():
        receipt["models"] = [
            {
                "family": item["family"],
                "model_id": item.get("resolved_model_id"),
                "resolution_rule": item.get("resolution_rule"),
            }
            for item in _read_json(output / MODELS_RECEIPT)["families"]
        ]
    if (output / SCORER_MODELS_RECEIPT).exists():
        receipt["scoring"]["models"] = [
            {
                "family": item["family"],
                "modelId": item.get("resolved_model_id"),
                "resolutionRule": item.get("resolution_rule"),
            }
            for item in _read_json(output / SCORER_MODELS_RECEIPT)["families"]
        ]
        receipt["scoring"]["modelsFileDigest"] = _file_digest(output / SCORER_MODELS_RECEIPT)
    if (output / SCORING_SPEND).exists():
        receipt["scoring"]["spend"] = _read_json(output / SCORING_SPEND)
    sealed_receipt = qual.seal_qualification_run_receipt(receipt)
    _write_json(output / RUN_RECEIPT, sealed_receipt)
    print(canonical_json(sealed_receipt))
    return 0


def _verify_run_file_pin(root: Path, pin: Mapping[str, Any]) -> Path:
    name = pin.get("file")
    digest = pin.get("fileDigest")
    if not isinstance(name, str) or Path(name).name != name:
        raise SystemExit("qualification run receipt carries an unsafe artifact name")
    path = root / name
    if not isinstance(digest, str) or _file_digest(path) != digest:
        raise SystemExit(f"qualification artifact {name} differs from its run-receipt pin")
    return path


def _verify_candidate_receipt_pins(
    path: Path,
    accounting: Mapping[str, Mapping[str, Any]],
    *,
    accounting_key: str,
) -> None:
    actual: dict[tuple[str, str], str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        record = json.loads(line)
        if line != canonical_json(record):
            raise SystemExit(f"{path.name} contains a non-canonical receipt row")
        key = (str(record["candidate_id"]), str(record["family"]))
        if key in actual:
            raise SystemExit(f"{path.name} repeats a candidate/family receipt")
        actual[key] = "sha256:" + hashlib.sha256((line + "\n").encode("utf-8")).hexdigest()
    expected: dict[tuple[str, str], str] = {}
    for candidate_id, row in accounting.items():
        for pin in row[accounting_key]:
            key = (candidate_id, str(pin["family"]))
            expected[key] = str(pin["receiptDigest"])
    if actual != expected:
        raise SystemExit(f"{path.name} rows differ from candidate-level run accounting")


def command_seal_relations(args: argparse.Namespace) -> int:
    """Emit every admitted non-control mapping as one verified relation bundle."""

    output = Path(args.output)
    run_path = output / RUN_RECEIPT
    raw = run_path.read_text(encoding="utf-8")
    parsed = json.loads(raw)
    if raw != canonical_json(parsed) + "\n":
        raise SystemExit("qualification run receipt bytes are not canonical")
    run = qual.validate_qualification_run_receipt(parsed)
    if run["coverageMode"] == qual.PRODUCTION_COVERAGE_MODE and run["productionReady"] is not True:
        raise SystemExit("production relation sealing requires complete scorer and judge coverage")
    catalog_path = _verify_run_file_pin(output, run["candidateCatalog"])
    bundle_path = _verify_run_file_pin(output, run["bundle"])
    _verify_run_file_pin(output, run["receiptLog"])
    scoring_log = run["scoring"]["receiptLog"]
    if scoring_log.get("fileDigest") is not None:
        _verify_run_file_pin(output, scoring_log)

    catalog = _read_json(catalog_path)
    bundle_pin = run["bundle"]
    bundle = CrosswalkBundle.open(
        bundle_path,
        expected_file_digest=str(bundle_pin["fileDigest"]),
        expected_bundle_digest=str(bundle_pin["bundleDigest"]),
    )
    if bundle.identifier != bundle_pin["id"]:
        raise SystemExit("run receipt names another CrosswalkBundle identity")
    bundle_record = bundle.to_dict()
    bundle_candidates = {
        str(row["id"]): row for row in bundle_record["mappingCandidates"]
    }
    accounting = {str(row["candidateId"]): row for row in run["candidateAccounting"]}
    catalog_ids = {str(row["candidateId"]) for row in catalog["candidates"]}
    if set(bundle_candidates) != set(accounting) or set(accounting) != catalog_ids:
        raise SystemExit("catalog, Crosswalk bundle, and run accounting do not name the same candidates")
    _verify_candidate_receipt_pins(
        output / str(run["receiptLog"]["file"]),
        accounting,
        accounting_key="judgeReceipts",
    )
    if run["counts"]["scorerReceipts"]:
        _verify_candidate_receipt_pins(
            output / str(run["scoring"]["receiptLog"]["file"]),
            accounting,
            accounting_key="scorerReceipts",
        )
    relations = bundle.adjudicated_relations()
    admitted = {
        candidate_id: row
        for candidate_id, row in accounting.items()
        if row["disposition"] == "admitted"
    }
    for candidate_id, relation in relations.items():
        row = accounting[candidate_id]
        if row["control"] is True:
            continue
        if candidate_id not in admitted or row.get("relation") != relation:
            raise SystemExit("an adjudicated non-control candidate is missing or changed in run accounting")
    if set(admitted) != {candidate_id for candidate_id in relations if accounting[candidate_id]["control"] is False}:
        raise SystemExit("run accounting admits a candidate without an adjudicated bundle relation")
    if not admitted:
        raise SystemExit("qualification run contains no admitted non-control relation")

    release_sources = (
        _open_relation_release(
            Path(args.source_release_manifest),
            release_id=args.source_release_id,
            ring_assignment_path=args.source_ring_assignment,
        ),
        _open_relation_release(
            Path(args.target_release_manifest),
            release_id=args.target_release_id,
            ring_assignment_path=args.target_ring_assignment,
        ),
    )
    endpoint_release_ids = {source.release_id for source in release_sources}
    proofs: list[PinnedCrosswalkMachineProof] = []
    evidence_assertions = []
    mappings: list[MappingAssertion] = []
    for candidate_id in sorted(admitted):
        candidate = bundle_candidates[candidate_id]
        if {str(candidate["sourceRelease"]), str(candidate["targetRelease"])} != endpoint_release_ids:
            raise SystemExit("admitted candidate endpoints differ from the two verified releases")
        proof = PinnedCrosswalkMachineProof.qualified(
            bundle_path,
            expected_file_digest=str(bundle_pin["fileDigest"]),
            expected_bundle_digest=str(bundle_pin["bundleDigest"]),
            candidate_id=candidate_id,
            qualification_run_path=run_path,
            expected_qualification_run_file_digest=_file_digest(run_path),
            expected_qualification_run_content_digest=str(run["contentDigest"]),
        )
        evidence = build_machine_evidence_from_crosswalk_proof(
            proof,
            asserted_by=args.asserted_by,
            asserted_at=args.asserted_at,
        )
        mapping = MappingAssertion(
            semantic_ring="subject",
            source_concept=str(candidate["sourceMember"]),
            target_concept=str(candidate["targetMember"]),
            source_release=str(candidate["sourceRelease"]),
            target_release=str(candidate["targetRelease"]),
            relation=str(admitted[candidate_id]["relation"]),
            evidence=(evidence.identifier,),
            asserted_at=args.asserted_at,
        )
        proofs.append(proof)
        evidence_assertions.append(evidence)
        mappings.append(mapping)

    relation_bundle = RelationAssertionBundle.create(
        semantic_ring="subject",
        release_sources=release_sources,
        machine_proof_sources=tuple(proofs),
        evidence_assertions=tuple(evidence_assertions),
        mapping_assertions=tuple(mappings),
    )
    destination = output / args.relation_output
    root = relation_bundle.write_to(destination)
    summary = {
        "id": relation_bundle.identifier,
        "manifest": (root / "bundle-manifest.json").name,
        "manifestDigest": relation_bundle.manifest_digest,
        "mappingAssertions": len(mappings),
        "sourceRun": {"id": run["id"], "contentDigest": run["contentDigest"]},
    }
    print(canonical_json(summary))
    return 0


# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# batch-submit / batch-status / batch-collect
#
# The same question, bought asynchronously at half price.  These three stages
# stand beside `qualify`, never in front of it: they append rows to the same
# `receipts.jsonl`, carrying the same fields, so `bundle` and the resume set
# cannot tell which road a row came down.  Everything a batch adds -- job ids,
# provider endpoints, submit and completion times, counts -- goes to the
# `batch-jobs.json` sidecar instead of into a receipt.
# ---------------------------------------------------------------------------


def _batch_rows(args: argparse.Namespace, *, subset: bool) -> list[qbatch.CandidateRow]:
    """Candidate rows for a batch stage, sliced the way `qualify` slices them."""

    catalog = _read_json(Path(args.output) / CANDIDATES)
    rows = catalog["candidates"]
    _refuse_production_subset(catalog, getattr(args, "max_candidates", None) if subset else None)
    if subset and getattr(args, "max_candidates", None) is not None:
        rows = qual.stratified_subset(rows, args.max_candidates)
    return [
        qbatch.CandidateRow(
            candidate_id=str(row["candidateId"]),
            pair=_pair_from_dict(row),
            input_digest=str(row["inputDigest"]),
        )
        for row in rows
    ]


def _batch_protocol(args: argparse.Namespace) -> str:
    """The run's protocol, read from the run's own candidates and nowhere else.

    A batch buys the question before anyone can read an answer, so the rubric
    has to come from the artifact that defines the run rather than from a flag
    someone might forget or a library default that might move.
    """

    catalog = _read_json(Path(args.output) / CANDIDATES)
    return qbatch.run_protocol(catalog)


def _batch_keys(args: argparse.Namespace, families: Sequence[qual.ValidatorFamily]) -> dict[str, str]:
    return {family.name: qual.load_env_value(args.env, family.api_key_env) for family in families}


def _batch_sidecar_families(
    args: argparse.Namespace,
    sidecar_name: str = qbatch.SIDECAR,
) -> dict[str, qual.ValidatorFamily]:
    """Every family the sidecar already names; a poll invents no new work."""

    sidecar = qbatch.read_sidecar(Path(args.output) / sidecar_name)
    names = sorted({str(job["family"]) for job in sidecar.get("jobs", ())})
    unknown = [name for name in names if name not in qual.VALIDATOR_FAMILIES]
    if unknown:
        raise SystemExit(
            f"{sidecar_name} names {unknown} which are not validator families; "
            "the sidecar was written against a different family configuration"
        )
    return {name: qual.VALIDATOR_FAMILIES[name] for name in names}


def command_batch_submit(args: argparse.Namespace) -> int:
    output = Path(args.output)
    protocol = _batch_protocol(args)
    print(f"protocol {protocol} (from {CANDIDATES})", file=sys.stderr, flush=True)
    families = [qual.VALIDATOR_FAMILIES[name] for name in args.families.split(",")]
    transport = qbatch.default_transport()
    plain = qbatch.PlainTransport(transport)
    keys = _batch_keys(args, families)

    resolved: dict[str, str] = {}
    model_receipts: list[dict[str, Any]] = []
    for family in families:
        model_ids, receipt = qual.list_models(plain, family, keys[family.name])
        model_id, rule = qual.resolve_validator_model(family, model_ids)
        receipt["resolved_model_id"] = model_id
        receipt["resolution_rule"] = rule
        model_receipts.append(receipt)
        resolved[family.name] = model_id
        print(f"{family.name}: {model_id} ({rule})", file=sys.stderr, flush=True)
    # Merged, not replaced.  Submitting one family at a time is the normal
    # batch shape, and a bare overwrite would drop the other family's model
    # resolution out of the sealed run receipt.
    if (output / MODELS_RECEIPT).exists():
        submitted = {item["family"] for item in model_receipts}
        model_receipts = [
            item for item in _read_json(output / MODELS_RECEIPT)["families"] if item["family"] not in submitted
        ] + model_receipts
    _write_json(output / MODELS_RECEIPT, {"families": sorted(model_receipts, key=lambda item: str(item["family"]))})

    try:
        summary = qbatch.submit(
            transport=transport,
            receipts_path=output / RECEIPTS,
            sidecar_path=output / qbatch.SIDECAR,
            families=families,
            keys=keys,
            models=resolved,
            rows=_batch_rows(args, subset=True),
            caps=args.cap,
            total_cap_usd=args.total_cap,
            protocol=protocol,
        )
    except qbatch.BatchSpendCapReached as error:
        # Refused before anything was bought.  A batch cannot be stopped once
        # submitted, so this is the only place the cap can still say no.
        raise SystemExit(str(error)) from error
    print(canonical_json(summary))
    return 0


def command_batch_status(args: argparse.Namespace) -> int:
    output = Path(args.output)
    families = _batch_sidecar_families(args)
    if not families:
        print(canonical_json({"jobs": []}))
        return 0
    summary = qbatch.poll(
        transport=qbatch.default_transport(),
        sidecar_path=output / qbatch.SIDECAR,
        families=families,
        keys=_batch_keys(args, list(families.values())),
    )
    for job in summary["jobs"]:
        print(f"{job['family']} {job['jobId']}: {job['state']} ({job['providerStatus']})", file=sys.stderr, flush=True)
    print(canonical_json(summary))
    return 0


def command_batch_collect(args: argparse.Namespace) -> int:
    output = Path(args.output)
    families = _batch_sidecar_families(args)
    if not families:
        print(canonical_json({"jobs": [], "receiptsAppended": 0}))
        return 0
    transport = qbatch.default_transport()
    keys = _batch_keys(args, list(families.values()))
    # Poll first.  Job state lives in the sidecar, so a collect that trusted a
    # stale sidecar would find every job still `pending`, collect nothing, and
    # exit zero as though there had been nothing to collect.
    qbatch.poll(transport=transport, sidecar_path=output / qbatch.SIDECAR, families=families, keys=keys)
    summary = qbatch.collect(
        transport=transport,
        receipts_path=output / RECEIPTS,
        sidecar_path=output / qbatch.SIDECAR,
        families=families,
        keys=keys,
        rows=_batch_rows(args, subset=False),
        protocol=_batch_protocol(args),
    )
    # Additive only.  `spend.json` belongs to `qualify`; the batch road adds its
    # own keys beside whatever the serial road wrote and never rewrites them.
    spend_path = output / "spend.json"
    spend = _read_json(spend_path) if spend_path.exists() else {}
    spend["batchSpendByFamily"] = summary["spendByFamily"]
    spend["totalBatchAssumedCostUsd"] = summary["totalBatchAssumedCostUsd"]
    _write_json(spend_path, spend)
    print(canonical_json(summary))
    return 0


def command_batch_cancel(args: argparse.Namespace) -> int:
    output = Path(args.output)
    families = _batch_sidecar_families(args)
    if not families:
        print(canonical_json({"cancellations": []}))
        return 0
    summary = qbatch.cancel(
        transport=qbatch.default_transport(),
        sidecar_path=output / qbatch.SIDECAR,
        families=families,
        keys=_batch_keys(args, list(families.values())),
    )
    for item in summary["cancellations"]:
        print(canonical_json(item), file=sys.stderr, flush=True)
    print(canonical_json(summary))
    return 0


def command_score_batch_submit(args: argparse.Namespace) -> int:
    output = Path(args.output)
    catalog = _read_json(output / CANDIDATES)
    rows = _scoring_candidate_rows(catalog, args.max_candidates)
    try:
        family = qual.VALIDATOR_FAMILIES[args.family]
    except KeyError as error:
        raise SystemExit(f"unknown scorer family {args.family!r}") from error
    transport = qbatch.default_transport()
    key = qual.load_env_value(args.env, family.api_key_env)
    model_ids, receipt = qual.list_models(qbatch.PlainTransport(transport), family, key)
    model_id, rule = qual.resolve_validator_model(family, model_ids)
    receipt["resolved_model_id"] = model_id
    receipt["resolution_rule"] = rule
    _write_json(output / SCORER_MODELS_RECEIPT, {"families": [receipt]})
    try:
        summary = qbatch.submit(
            transport=transport,
            receipts_path=output / SCORING_RECEIPTS,
            sidecar_path=output / SCORING_BATCH_SIDECAR,
            families=(family,),
            keys={family.name: key},
            models={family.name: model_id},
            rows=rows,
            caps=args.cap,
            total_cap_usd=args.total_cap,
            protocol=qual.SCORING_PROTOCOL,
            work_kind="scoring",
        )
    except qbatch.BatchSpendCapReached as error:
        raise SystemExit(str(error)) from error
    print(canonical_json(summary))
    return 0


def command_score_batch_status(args: argparse.Namespace) -> int:
    output = Path(args.output)
    families = _batch_sidecar_families(args, SCORING_BATCH_SIDECAR)
    if not families:
        print(canonical_json({"jobs": []}))
        return 0
    summary = qbatch.poll(
        transport=qbatch.default_transport(),
        sidecar_path=output / SCORING_BATCH_SIDECAR,
        families=families,
        keys=_batch_keys(args, list(families.values())),
    )
    print(canonical_json(summary))
    return 0


def command_score_batch_collect(args: argparse.Namespace) -> int:
    output = Path(args.output)
    families = _batch_sidecar_families(args, SCORING_BATCH_SIDECAR)
    if not families:
        print(canonical_json({"jobs": [], "receiptsAppended": 0}))
        return 0
    transport = qbatch.default_transport()
    keys = _batch_keys(args, list(families.values()))
    qbatch.poll(
        transport=transport,
        sidecar_path=output / SCORING_BATCH_SIDECAR,
        families=families,
        keys=keys,
    )
    summary = qbatch.collect(
        transport=transport,
        receipts_path=output / SCORING_RECEIPTS,
        sidecar_path=output / SCORING_BATCH_SIDECAR,
        families=families,
        keys=keys,
        rows=_scoring_candidate_rows(_read_json(output / CANDIDATES)),
        protocol=qual.SCORING_PROTOCOL,
        work_kind="scoring",
    )
    _write_json(output / SCORING_SPEND, summary)
    print(canonical_json(summary))
    return 0


def command_score_batch_cancel(args: argparse.Namespace) -> int:
    output = Path(args.output)
    families = _batch_sidecar_families(args, SCORING_BATCH_SIDECAR)
    if not families:
        print(canonical_json({"cancellations": []}))
        return 0
    summary = qbatch.cancel(
        transport=qbatch.default_transport(),
        sidecar_path=output / SCORING_BATCH_SIDECAR,
        families=families,
        keys=_batch_keys(args, list(families.values())),
    )
    print(canonical_json(summary))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="run_atlas_qualification")
    parser.add_argument("--output", type=Path, required=True, help="run directory; every stage reads and writes here")
    subparsers = parser.add_subparsers(dest="command", required=True)

    extract = subparsers.add_parser("extract", help="project two managed releases into crosswalk concepts")
    extract.add_argument("--source-manifest", required=True)
    extract.add_argument("--source-release-iri", default=None)
    extract.add_argument("--source-vocabulary", default="")
    extract.add_argument("--target-manifest", required=True)
    extract.add_argument("--target-release-iri", default=None)
    extract.add_argument("--target-vocabulary", default="")
    extract.add_argument("--language", default="en")
    extract.set_defaults(handler=command_extract)

    generate = subparsers.add_parser("generate", help="propose the deterministic candidate slice")
    generate.add_argument(
        "--generated-at", required=True, help="pinned candidate timestamp; part of candidate identity"
    )
    generate.add_argument("--seed", default=qual.GENERATION_SEED)
    generate.add_argument("--limit", action="append", metavar="CLASS=N")
    generate.add_argument(
        "--production",
        action="store_true",
        help="generate the complete deterministic catalog without pilot class caps",
    )
    generate.set_defaults(handler=command_generate)

    qualify = subparsers.add_parser("qualify", help="ask each family about each candidate, once")
    qualify.add_argument("--env", type=Path, required=True, help="dotenv file holding the provider credentials")
    qualify.add_argument("--families", default="gemini,openai")
    qualify.add_argument(
        "--max-candidates",
        type=int,
        default=None,
        help="call a stratified subset spread across every generation class, not the first N",
    )
    qualify.add_argument(
        "--cap",
        action=_CapAction,
        default={},
        metavar="FAMILY=USD",
        help="override one family's hard spend cap",
    )
    qualify.set_defaults(handler=command_qualify)

    score = subparsers.add_parser("score", help="score candidate priority synchronously")
    score.add_argument("--env", type=Path, required=True, help="dotenv file holding the scorer credential")
    score.add_argument("--family", default="openai")
    score.add_argument("--max-candidates", type=int, default=None, help="score a pilot-only stratified subset")
    score.add_argument("--cap", action=_CapAction, default={}, metavar="FAMILY=USD")
    score.set_defaults(handler=command_score)

    bundle = subparsers.add_parser("bundle", help="seal one digest-pinned crosswalk bundle")
    bundle.add_argument("--replace", action="store_true", help="delete an existing bundle file first")
    bundle.set_defaults(handler=command_bundle)

    seal_relations = subparsers.add_parser(
        "seal-relations",
        help="emit admitted non-control mappings as one RelationAssertionBundle",
    )
    seal_relations.add_argument("--source-release-manifest", type=Path, required=True)
    seal_relations.add_argument("--source-release-id", default=None)
    seal_relations.add_argument("--source-ring-assignment", type=Path, default=None)
    seal_relations.add_argument("--target-release-manifest", type=Path, required=True)
    seal_relations.add_argument("--target-release-id", default=None)
    seal_relations.add_argument("--target-ring-assignment", type=Path, default=None)
    seal_relations.add_argument("--asserted-by", required=True)
    seal_relations.add_argument("--asserted-at", required=True)
    seal_relations.add_argument("--relation-output", default="relation-assertions")
    seal_relations.set_defaults(handler=command_seal_relations)

    batch_submit = subparsers.add_parser(
        "batch-submit",
        help="buy the same questions asynchronously at half price; refuses at the cap before uploading",
    )
    batch_submit.add_argument("--env", type=Path, required=True, help="dotenv file holding the provider credentials")
    batch_submit.add_argument("--families", default="gemini,openai")
    batch_submit.add_argument(
        "--max-candidates",
        type=int,
        default=None,
        help="batch a stratified subset spread across every generation class, not the first N",
    )
    batch_submit.add_argument(
        "--cap",
        action=_CapAction,
        default={},
        metavar="FAMILY=USD",
        help="override one family's hard spend cap",
    )
    batch_submit.add_argument(
        "--total-cap",
        type=_positive_finite_usd,
        default=qual.TOTAL_SPEND_CAP_USD,
        metavar="USD",
        help="set the hard spend cap across all families for this batch submission",
    )
    batch_submit.set_defaults(handler=command_batch_submit)

    batch_status = subparsers.add_parser("batch-status", help="poll every submitted batch job and print its state")
    batch_status.add_argument("--env", type=Path, required=True, help="dotenv file holding the provider credentials")
    batch_status.set_defaults(handler=command_batch_status)

    batch_collect = subparsers.add_parser(
        "batch-collect",
        help="download finished batches and append their receipts; safe to run twice",
    )
    batch_collect.add_argument("--env", type=Path, required=True, help="dotenv file holding the provider credentials")
    batch_collect.set_defaults(handler=command_batch_collect)

    batch_cancel = subparsers.add_parser(
        "batch-cancel",
        help="ask both providers to stop every job this run still has in flight",
    )
    batch_cancel.add_argument("--env", type=Path, required=True, help="dotenv file holding the provider credentials")
    batch_cancel.set_defaults(handler=command_batch_cancel)

    score_batch_submit = subparsers.add_parser(
        "score-batch-submit",
        help="submit scorer requests through the provider batch API",
    )
    score_batch_submit.add_argument("--env", type=Path, required=True)
    score_batch_submit.add_argument("--family", default="openai")
    score_batch_submit.add_argument("--max-candidates", type=int, default=None)
    score_batch_submit.add_argument("--cap", action=_CapAction, default={}, metavar="FAMILY=USD")
    score_batch_submit.add_argument(
        "--total-cap",
        type=_positive_finite_usd,
        default=qual.TOTAL_SPEND_CAP_USD,
        metavar="USD",
        help="set the hard spend cap across all families for this batch submission",
    )
    score_batch_submit.set_defaults(handler=command_score_batch_submit)

    score_batch_status = subparsers.add_parser("score-batch-status", help="poll scorer batch jobs")
    score_batch_status.add_argument("--env", type=Path, required=True)
    score_batch_status.set_defaults(handler=command_score_batch_status)

    score_batch_collect = subparsers.add_parser("score-batch-collect", help="collect scorer batch receipts")
    score_batch_collect.add_argument("--env", type=Path, required=True)
    score_batch_collect.set_defaults(handler=command_score_batch_collect)

    score_batch_cancel = subparsers.add_parser("score-batch-cancel", help="cancel scorer batch jobs")
    score_batch_cancel.add_argument("--env", type=Path, required=True)
    score_batch_cancel.set_defaults(handler=command_score_batch_cancel)
    return parser


class _CapAction(argparse.Action):
    def __call__(
        self,
        parser: argparse.ArgumentParser,
        namespace: argparse.Namespace,
        values: Any,
        option_string: str | None = None,
    ) -> None:
        caps = dict(getattr(namespace, self.dest) or {})
        name, _, value = str(values).partition("=")
        if name not in qual.VALIDATOR_FAMILIES:
            raise argparse.ArgumentError(self, f"unknown family {name!r}")
        caps[name] = float(value)
        setattr(namespace, self.dest, caps)


def _positive_finite_usd(value: str) -> float:
    cap = float(value)
    if not math.isfinite(cap) or cap <= 0:
        raise argparse.ArgumentTypeError("must be a positive finite USD value")
    return cap


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.handler(args))


if __name__ == "__main__":
    raise SystemExit(main())
