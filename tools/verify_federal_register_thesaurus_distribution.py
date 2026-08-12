"""Reconcile a bounded Atlas 3.1 distribution with the pinned thesaurus PDF.

The release job publishes one governed scheme, the April 1, 2025 Federal
Register Thesaurus, and has to answer one question afterwards: do the published
bytes still say what the source says? This reads both ends and compares them.

The source end is the exact PDF named by
``refspec.registry.federal_register_thesaurus_2025``. Its digest and byte
length are verified before it is parsed, and the parse yields the occurrence
ledger: every related reference the publisher authored, classified as resolved,
suggested open-term pattern, or unresolved. That ledger is the only place the
count of source occurrences exists; a distribution carries the resolved subset
and cannot state what it dropped.

The distribution end is measured from the published bytes. The manifest,
supporting members, and pack inventory are authenticated against an external
manifest digest; the served Parquet view beside it is authenticated against its
own external view-manifest digest, and every table is then read. Resource,
label, and statement identities are counted from those rows -- not copied from
the producer's own receipt inside the artifact, which is the producer's claim
rather than an independent reading of it.

Both ends are then compared as sets, so a distribution that carries the right
number of wrong rows fails. Any difference is written to the receipt and exits
non-zero.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq

from refspec.atlas.compact_pack import CompactRecordRole
from refspec.atlas.parquet_tables import TABLE_DIRECTORY, TABLE_NAMES
from refspec.atlas.parquet_view import (
    verify_atlas_parquet_source_metadata,
    verify_atlas_parquet_view,
)
from refspec.atlas.v3_registry_vocabularies import (
    DEFAULT_SOURCE_ROOT,
    load_federal_register_2025_release,
)
from refspec.registry.federal_register_thesaurus_2025 import (
    FEDERAL_REGISTER_THESAURUS_2025_BYTE_LENGTH,
    FEDERAL_REGISTER_THESAURUS_2025_SHA256,
    parse_federal_register_thesaurus_2025_pdf,
)
from refspec.storage import canonical_json

RELEASE_KEY = "federal-register-thesaurus-2025"
ATLAS_RELEASE_IRI = "urn:ref:atlas-release:3:federal-register-thesaurus:2025-04-01"
SOURCE_FILENAME = "federal-register-thesaurus-2025.pdf"


class BoundedReleaseVerificationError(ValueError):
    """The published distribution and the pinned source disagree."""


def _sha256_file(path: Path) -> str:
    import hashlib

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return "sha256:" + digest.hexdigest()


def verify_pinned_source(source_root: Path) -> dict[str, Any]:
    """Verify the exact publisher PDF before anything reads it as meaning."""

    path = Path(source_root) / SOURCE_FILENAME
    if path.is_symlink() or not path.is_file():
        raise BoundedReleaseVerificationError(f"pinned thesaurus source is absent: {path}")
    digest = _sha256_file(path)
    byte_length = path.stat().st_size
    if digest != FEDERAL_REGISTER_THESAURUS_2025_SHA256:
        raise BoundedReleaseVerificationError(
            f"pinned thesaurus source digest differs: {digest}"
        )
    if byte_length != FEDERAL_REGISTER_THESAURUS_2025_BYTE_LENGTH:
        raise BoundedReleaseVerificationError(
            f"pinned thesaurus source byte length differs: {byte_length}"
        )
    return {"byteLength": byte_length, "path": str(path), "sha256": digest}


def source_occurrence_ledger(source_root: Path) -> dict[str, Any]:
    """Classify every authored related reference in the exact source."""

    path = Path(source_root) / SOURCE_FILENAME
    parsed = parse_federal_register_thesaurus_2025_pdf(path.read_bytes())
    statuses = Counter(row.resolution_status for row in parsed.related_references)
    occurrences = len(parsed.related_references)
    if sum(statuses.values()) != occurrences:
        raise BoundedReleaseVerificationError(
            "related-reference statuses do not cover every occurrence"
        )
    if statuses["resolved"] != parsed.counts.resolved_related_references:
        raise BoundedReleaseVerificationError(
            "resolved related-reference count differs from the parsed ledger"
        )
    return {
        "officialTerms": parsed.counts.official_terms,
        "relatedReferenceOccurrences": occurrences,
        "relatedReferenceStatuses": dict(sorted(statuses.items())),
        "sourcePages": parsed.counts.source_pages,
        "unrepresentedOccurrences": occurrences - statuses["resolved"],
    }


def _measure_distribution(
    distribution: Path,
    expected_manifest_digest: str,
    parquet_view: Path,
    expected_view_manifest_digest: str,
) -> dict[str, Any]:
    """Read the published bytes and count what they actually carry."""

    verified = verify_atlas_parquet_source_metadata(
        distribution,
        expected_manifest_digest,
    )
    view_manifest = verify_atlas_parquet_view(
        parquet_view,
        expected_manifest_digest=expected_view_manifest_digest,
    )
    if view_manifest["input"]["manifestSha256"] != verified.manifest_digest:
        raise BoundedReleaseVerificationError(
            "the Parquet view was derived from a different distribution manifest"
        )
    resources: set[str] = set()
    labels: set[tuple[str, str, str]] = set()
    statements: set[tuple[str, str, str]] = set()
    source_records: set[str] = set()
    releases: set[str] = set()
    label_roles: Counter[str] = Counter()
    for role in CompactRecordRole:
        table = pq.ParquetFile(parquet_view / TABLE_DIRECTORY / TABLE_NAMES[role])
        for batch in table.iter_batches():
            rows = batch.to_pylist()
            if role is CompactRecordRole.RESOURCE:
                resources.update(row["id"] for row in rows)
            elif role is CompactRecordRole.LABEL:
                for row in rows:
                    labels.add((row["resource"], row["label_role"], row["value"]))
                    label_roles[row["label_role"]] += 1
            elif role is CompactRecordRole.STATEMENT:
                statements.update(
                    (row["subject"], row["predicate"], row["object"]) for row in rows
                )
            elif role is CompactRecordRole.SOURCE_RECORD:
                source_records.update(row["id"] for row in rows)
            elif role is CompactRecordRole.RELEASE:
                releases.update(row["id"] for row in rows)
    return {
        "distributionId": verified.manifest["distributionId"],
        "labelRoleCounts": dict(sorted(label_roles.items())),
        "labels": labels,
        "manifestSha256": verified.manifest_digest,
        "parquetViewId": view_manifest["viewId"],
        "releases": releases,
        "resources": resources,
        "sourceRecords": source_records,
        "statements": statements,
    }


def _difference(
    name: str,
    expected: set[Any],
    observed: set[Any],
    failures: list[str],
) -> None:
    if expected == observed:
        return
    failures.append(
        f"{name} differ: {len(expected - observed)} absent from the distribution, "
        f"{len(observed - expected)} unexpected in the distribution"
    )


def verify_distribution(
    distribution: Path,
    *,
    expected_manifest_digest: str,
    parquet_view: Path,
    expected_view_manifest_digest: str,
    source_root: Path,
) -> dict[str, Any]:
    """Reconcile the published distribution with the pinned publisher source."""

    source_pin = verify_pinned_source(source_root)
    ledger = source_occurrence_ledger(source_root)
    release = load_federal_register_2025_release(source_root)
    if release.key != RELEASE_KEY or release.atlas_release_iri != ATLAS_RELEASE_IRI:
        raise BoundedReleaseVerificationError("normalized release identity differs")

    expected_resources = {resource.iri for resource in release.resources}
    expected_labels = {
        (resource.iri, label.role, label.value)
        for resource in release.resources
        for label in resource.labels
    }
    expected_statements = {
        (relation.subject, relation.predicate, relation.object)
        for relation in release.relations
    }
    measured = _measure_distribution(
        distribution,
        expected_manifest_digest,
        parquet_view,
        expected_view_manifest_digest,
    )

    failures: list[str] = []
    _difference("concepts", expected_resources, measured["resources"], failures)
    _difference("labels", expected_labels, measured["labels"], failures)
    _difference("relation rows", expected_statements, measured["statements"], failures)
    if len(expected_statements) != ledger["relatedReferenceStatuses"].get("resolved"):
        failures.append(
            "resolved related references do not match the normalized relation rows"
        )
    if ATLAS_RELEASE_IRI not in measured["releases"]:
        failures.append(f"distribution does not carry the release {ATLAS_RELEASE_IRI}")
    if len(measured["sourceRecords"]) != len(expected_resources):
        failures.append(
            "source records and concepts differ: "
            f"{len(measured['sourceRecords'])} against {len(expected_resources)}"
        )

    counts = {
        "concepts": len(measured["resources"]),
        "labels": len(measured["labels"]),
        "relatedReferenceOccurrences": ledger["relatedReferenceOccurrences"],
        "relationRows": len(measured["statements"]),
    }
    return {
        "atlasRelease": ATLAS_RELEASE_IRI,
        "distribution": {
            "id": measured["distributionId"],
            "manifestSha256": measured["manifestSha256"],
            "path": str(distribution),
        },
        "parquetView": {
            "path": str(parquet_view),
            "viewId": measured["parquetViewId"],
            "viewManifestSha256": expected_view_manifest_digest,
        },
        "failures": failures,
        "labelRoleCounts": measured["labelRoleCounts"],
        "measuredCounts": counts,
        "releaseKey": RELEASE_KEY,
        "sourceLedger": ledger,
        "sourcePin": source_pin,
        "status": "failed" if failures else "passed",
        "type": "AtlasBoundedReleaseVerification",
        "version": "1.0",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--distribution", type=Path, required=True)
    parser.add_argument("--expected-manifest-sha256", required=True)
    parser.add_argument("--parquet-view", type=Path, required=True)
    parser.add_argument("--expected-view-manifest-sha256", required=True)
    parser.add_argument("--source-root", type=Path, default=DEFAULT_SOURCE_ROOT)
    parser.add_argument(
        "--output",
        type=Path,
        help="write the verification receipt beside the distribution",
    )
    args = parser.parse_args(argv)
    try:
        receipt = verify_distribution(
            args.distribution.resolve(),
            expected_manifest_digest=args.expected_manifest_sha256,
            parquet_view=args.parquet_view.resolve(),
            expected_view_manifest_digest=args.expected_view_manifest_sha256,
            source_root=args.source_root,
        )
    except (BoundedReleaseVerificationError, ValueError) as error:
        print(f"{type(error).__name__}: {error}", file=sys.stderr)
        return 1
    payload = canonical_json(receipt)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload, encoding="utf-8")
    print(json.dumps(receipt, indent=2, sort_keys=True))
    return 0 if receipt["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
