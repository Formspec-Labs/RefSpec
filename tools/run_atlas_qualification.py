#!/usr/bin/env python3
"""Offline crosswalk qualification runner: extract, generate, qualify, bundle.

Qualification never runs inside an atlas build.  This tool runs beside one: it
reads two pinned managed releases, proposes a diverse candidate slice, asks two
independent model families about each candidate, and writes one sealed
digest-pinned ``CrosswalkBundle`` that ``refspec-build-vocabulary-atlas
--crosswalk`` consumes as a pinned input.

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
import sys
from collections import Counter
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from refspec.atlas import qualification as qual
from refspec.atlas import qualification_batch as qbatch
from refspec.atlas.cli import open_release
from refspec.storage import canonical_json

CONCEPTS_SOURCE = "concepts-source.json"
CONCEPTS_TARGET = "concepts-target.json"
CANDIDATES = "candidates.json"
RECEIPTS = "receipts.jsonl"
BUNDLE = "crosswalk-bundle.json"
RUN_RECEIPT = "qualification-receipt.json"
MODELS_RECEIPT = "models-list.json"


def _file_digest(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, payload: Any) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = canonical_json(payload) + "\n"
    path.write_text(text, encoding="utf-8")
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


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
    )


def _pair_from_dict(payload: Mapping[str, Any]) -> qual.CandidatePair:
    return qual.CandidatePair(
        source=_concept_from_dict(payload["source"]),
        target=_concept_from_dict(payload["target"]),
        generation_class=str(payload["generationClass"]),
        evidence=dict(payload["evidence"]),
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
        view = open_release(str(path), digest).verified_view()
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
    limits = dict(qual.DEFAULT_CLASS_LIMITS)
    for item in args.limit or ():
        name, _, value = item.partition("=")
        if name not in qual.GENERATION_CLASSES:
            raise SystemExit(f"unknown generation class {name!r}")
        limits[name] = int(value)
    pairs = qual.generate_candidate_pairs(
        [_concept_from_dict(item) for item in source["concepts"]],
        [_concept_from_dict(item) for item in target["concepts"]],
        limits=limits,
        seed=args.seed,
    )
    rows: list[dict[str, Any]] = []
    for pair in pairs:
        entry = qual.assemble_candidate(pair, generated_at=args.generated_at, readings=())
        context = next(item for item in entry.artifacts if item.role == "inputContext")
        rows.append(
            {
                "candidateId": entry.candidate.identifier,
                "evidence": dict(pair.evidence),
                "generationClass": pair.generation_class,
                "inputDigest": context.content_digest,
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
            "generationPolicy": qual.CANDIDATE_GENERATION_POLICY,
            "limits": dict(sorted(limits.items())),
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


def command_qualify(args: argparse.Namespace) -> int:
    output = Path(args.output)
    catalog = _read_json(output / CANDIDATES)
    rows = catalog["candidates"]
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
                    protocol=getattr(args, "protocol", "v1"),
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
# bundle
# ---------------------------------------------------------------------------


def command_bundle(args: argparse.Namespace) -> int:
    output = Path(args.output)
    catalog = _read_json(output / CANDIDATES)
    by_candidate: dict[str, list[dict[str, Any]]] = {}
    outcomes: Counter[str] = Counter()
    for line in (output / RECEIPTS).read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        record = json.loads(line)
        outcomes[str(record.get("outcome"))] += 1
        by_candidate.setdefault(str(record["candidate_id"]), []).append(record)

    entries: list[qual.AssembledCandidate] = []
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
            readings.append(reading)
            verdicts[f"{family.name}:{reading.verdict}"] += 1
        entry = qual.assemble_candidate(pair, generated_at=catalog["generatedAt"], readings=tuple(readings))
        if entry.candidate.identifier != row["candidateId"]:
            raise SystemExit(f"candidate identity moved for {row['candidateId']}; regenerate before bundling")
        entries.append(entry)
        tally = by_class.setdefault(pair.generation_class, Counter())
        tally["candidates"] += 1
        tally[f"validations:{len(readings)}"] += 1

    bundle = qual.crosswalk_bundle(entries)
    qualified = bundle.qualified()
    for entry in entries:
        if entry.candidate.identifier in qualified:
            by_class[entry.pair.generation_class]["qualified"] += 1

    path = output / BUNDLE
    if path.exists() and args.replace:
        path.unlink()
    bundle.write(path)
    pin = bundle.pin()

    receipt = {
        "bundle": {
            "file": BUNDLE,
            "fileDigest": pin["fileDigest"],
            "id": pin["id"],
            "bundleDigest": pin["digest"],
            "mediaType": pin["mediaType"],
        },
        "callOutcomes": dict(sorted(outcomes.items())),
        "candidateGenerationPolicy": catalog["generationPolicy"],
        "candidatesByClass": {
            name: dict(sorted(tally.items())) for name, tally in sorted(by_class.items())
        },
        "determinism": (
            "NOT reproducible. This artifact records provider calls; a rebuild will not "
            "reproduce it byte-for-byte. Every call carries its own request and response digest, "
            "and the bundle it produced is pinned by digest instead."
        ),
        "eligibilityPolicy": "twoIndependentMachinesSearchOnly",
        "generatedAt": catalog["generatedAt"],
        "qualifiedCandidates": len(qualified),
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
    _write_json(output / RUN_RECEIPT, receipt)
    print(canonical_json(receipt))
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


def _batch_keys(args: argparse.Namespace, families: Sequence[qual.ValidatorFamily]) -> dict[str, str]:
    return {family.name: qual.load_env_value(args.env, family.api_key_env) for family in families}


def _batch_sidecar_families(args: argparse.Namespace) -> dict[str, qual.ValidatorFamily]:
    """Every family the sidecar already names; a poll invents no new work."""

    sidecar = qbatch.read_sidecar(Path(args.output) / qbatch.SIDECAR)
    names = sorted({str(job["family"]) for job in sidecar.get("jobs", ())})
    unknown = [name for name in names if name not in qual.VALIDATOR_FAMILIES]
    if unknown:
        raise SystemExit(
            f"{qbatch.SIDECAR} names {unknown} which are not validator families; "
            "the sidecar was written against a different family configuration"
        )
    return {name: qual.VALIDATOR_FAMILIES[name] for name in names}


def command_batch_submit(args: argparse.Namespace) -> int:
    output = Path(args.output)
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
            protocol=args.protocol,
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
    generate.add_argument("--generated-at", required=True, help="pinned candidate timestamp; part of candidate identity")
    generate.add_argument("--seed", default=qual.GENERATION_SEED)
    generate.add_argument("--limit", action="append", metavar="CLASS=N")
    generate.set_defaults(handler=command_generate)

    qualify = subparsers.add_parser("qualify", help="ask each family about each candidate, once")
    qualify.add_argument("--env", type=Path, required=True, help="dotenv file holding the provider credentials")
    qualify.add_argument("--families", default="gemini,openai")
    qualify.add_argument(
        "--protocol",
        choices=("v1", "v2"),
        default="v1",
        help="validation protocol; v2 adjudicates the relation instead of a closeMatch yes/no",
    )
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

    bundle = subparsers.add_parser("bundle", help="seal one digest-pinned crosswalk bundle")
    bundle.add_argument("--replace", action="store_true", help="delete an existing bundle file first")
    bundle.set_defaults(handler=command_bundle)

    batch_submit = subparsers.add_parser(
        "batch-submit",
        help="buy the same questions asynchronously at half price; refuses at the cap before uploading",
    )
    batch_submit.add_argument("--env", type=Path, required=True, help="dotenv file holding the provider credentials")
    batch_submit.add_argument("--families", default="gemini,openai")
    batch_submit.add_argument(
        "--protocol",
        choices=("v1", "v2"),
        default=None,
        help="validation protocol; defaults to whatever the serial path defaults to",
    )
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


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.handler(args))


if __name__ == "__main__":
    raise SystemExit(main())
