"""Promote experiment evidence out of `/tmp` into durable storage.

The 2026-08-05 candidate ledger closes with an explicit requirement:

    Before integration, promote every selected artifact now held under `/tmp`
    into durable content-addressed evidence storage: exact benchmark inputs, BGE
    rank bytes and manifest, blind samples and fixed decisions, cost receipts,
    and the selected frontier result. Reopen and verify every digest after
    promotion.

That never happened.  The material is still in a `/tmp` working directory that
macOS clears on a schedule, and it includes artifacts that **cannot be
regenerated at any price**: blind review samples and the fixed human decisions
recorded against them.  A sealed decision cannot be re-sealed once the reviewer
has seen the answer key, so losing those bytes destroys the evidence
permanently, not merely expensively.

Promotion splits by *replaceability and size*, because the repository tracks
54 MB of evidence with a 4.2 MB largest file and should not absorb 190 MB of
mostly-regenerable binaries:

``sealed``
    Small, irreplaceable, and cited by the ledger's acceptance gates. Goes into
    ``research/evidence/`` and is committed.

``bulk``
    Large but regenerable — rank byte matrices and provider request/response
    receipts. Goes into ``output/``, which is git-ignored, so the bytes survive
    a `/tmp` sweep without inflating the repository.

``session``
    Rank artifacts and the ablated corpus produced by the 2026-08-06 E3 sweep.
    Regenerable in about an hour of compute. Also ``output/``.

Digests for **every** promoted file are written to the committed manifest
regardless of tier, so the repository always records what exists, where it
lives, and what it hashed to — even for bytes it does not carry.

Copies are verified by re-reading and re-hashing the destination. Re-running is
idempotent: an existing destination file with a matching digest is left alone.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

DEFAULT_SOURCE = Path("/tmp/refspec-candidate-benchmark.ANhNrc")


@dataclass(frozen=True, slots=True)
class Tier:
    """One promotion group: what to take, where it lands, and whether git keeps it."""

    name: str
    destination: Path
    committed: bool
    rationale: str
    patterns: tuple[str, ...] = ()
    directories: tuple[str, ...] = ()


def sealed_tier(repo: Path) -> Tier:
    return Tier(
        name="sealed",
        destination=repo / "research/evidence/atlas-candidate-benchmark-sealed-2026-08-05",
        committed=True,
        rationale="irreplaceable sealed decisions and the receipts the acceptance gates cite",
        patterns=(
            "*blind*",
            "*decision*",
            "*manual-audit*",
            "judge-audit*",
            "*-rendering.md",
            "*cost*.json",
            "*frontier*.json",
            "*candidate-path*.json",
            "*ranks-manifest.json",
            "evidence-sha256.txt",
            "benchmark-result.json",
            "benchmark-report.md",
        ),
    )


def bulk_tier(repo: Path) -> Tier:
    return Tier(
        name="bulk",
        destination=repo / "output/atlas-candidate-benchmark-archive-2026-08-05",
        committed=False,
        rationale="regenerable rank matrices and provider receipts; too large for the repository",
        patterns=("atlas-bge-five-view-ranks.u8", "atlas-lean-lexical-k3-sparse-k1-pairs.u64"),
        directories=("evidence",),
    )


def session_tier(repo: Path, scratchpad: Path | None) -> Tier | None:
    if scratchpad is None or not scratchpad.exists():
        return None
    return Tier(
        name="session",
        destination=repo / "output/atlas-e3-rank-artifacts-2026-08-06",
        committed=False,
        rationale="2026-08-06 E3 rank artifacts and ablated corpus; ~1 hour of compute to rebuild",
        patterns=("e3-corpus.json",),
        directories=("valid",),
    )


def digest(path: Path) -> str:
    sha = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            sha.update(block)
    return f"sha256:{sha.hexdigest()}"


def select(source: Path, tier: Tier) -> list[Path]:
    chosen: set[Path] = set()
    for pattern in tier.patterns:
        chosen.update(path for path in source.glob(pattern) if path.is_file())
    for name in tier.directories:
        root = source / name
        if root.is_dir():
            chosen.update(path for path in root.rglob("*") if path.is_file())
    return sorted(chosen)


def promote(source: Path, tier: Tier, *, dry_run: bool) -> dict[str, Any]:
    files = select(source, tier)
    records: list[dict[str, Any]] = []
    copied = skipped = 0
    total = 0

    for path in files:
        relative = path.relative_to(source)
        target = tier.destination / relative
        source_digest = digest(path)
        size = path.stat().st_size
        total += size

        if dry_run:
            records.append({"path": str(relative), "bytes": size, "sha256": source_digest})
            continue

        if target.exists() and digest(target) == source_digest:
            skipped += 1
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)
            # Re-read the destination rather than trusting the copy; the ledger
            # requires reopening every digest after promotion.
            written = digest(target)
            if written != source_digest:
                raise RuntimeError(f"digest mismatch after copying {relative}: {source_digest} -> {written}")
            copied += 1
        records.append({"path": str(relative), "bytes": size, "sha256": source_digest})

    return {
        "tier": tier.name,
        "destination": str(tier.destination),
        "committed": tier.committed,
        "rationale": tier.rationale,
        "files": len(files),
        "bytes": total,
        "copied": copied,
        "verifiedUnchanged": skipped,
        "artifacts": records,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--scratchpad", type=Path, default=None, help="Session scratchpad holding E3 rank artifacts.")
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--tier", action="append", choices=("sealed", "bulk", "session"))
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if not args.source.exists():
        print(f"source not found: {args.source}")
        print("If /tmp has already been cleared, the sealed decisions are unrecoverable.")
        return 1

    candidates = [sealed_tier(args.repo), bulk_tier(args.repo), session_tier(args.repo, args.scratchpad)]
    tiers = [tier for tier in candidates if tier and (not args.tier or tier.name in args.tier)]

    results = [
        promote(args.source if tier.name != "session" else args.scratchpad, tier, dry_run=args.dry_run)
        for tier in tiers
    ]

    for result in results:
        mark = "commit" if result["committed"] else "output/ (git-ignored)"
        print(
            f"  {result['tier']:<8} {result['files']:>4} files  {result['bytes'] / 1e6:>7.1f} MB  "
            f"copied={result['copied']:<4} unchanged={result['verifiedUnchanged']:<4} -> {mark}"
        )

    if not args.dry_run:
        manifest = {
            "type": "AtlasTmpEvidencePromotionManifest",
            "source": str(args.source),
            "note": (
                "Digests are recorded for every promoted artifact regardless of tier, so the "
                "repository records what exists and where even for bytes it does not carry. "
                "Sealed decisions cannot be regenerated; bulk and session tiers can."
            ),
            "tiers": results,
        }
        path = args.repo / "research/evidence/atlas-tmp-evidence-promotion-2026-08-06.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(f"\nwrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
