"""Build the pinned 2025 Federal Register thesaurus package and crosswalk."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from refspec.registry.federal_register_thesaurus import (
    parse_federal_register_thesaurus,
)
from refspec.registry.federal_register_thesaurus_2025 import (
    federal_register_thesaurus_2025_extract_bytes,
    parse_federal_register_thesaurus_2025_pdf,
)
from refspec.registry.federal_register_thesaurus_2025_managed_release import (
    build_federal_register_thesaurus_2025_managed_release,
)
from refspec.registry.federal_register_vocabulary_policy import (
    build_federal_register_thesaurus_crosswalk,
    federal_register_thesaurus_crosswalk_bytes,
)
from refspec.storage import canonical_json


def _write_exact(path: Path, payload: bytes) -> None:
    if path.exists() and path.read_bytes() != payload:
        raise FileExistsError(f"refusing to overwrite different artifact {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)


def _sha256_bytes(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pdf", type=Path, required=True)
    parser.add_argument("--historical-source", type=Path, required=True)
    parser.add_argument("--resource-dir", type=Path, required=True)
    parser.add_argument("--release-dir", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument(
        "--recorded-at",
        default="2026-07-30T20:00:00Z",
    )
    parser.add_argument(
        "--recorded-by",
        default="urn:ref:actor:spicy-regs-vocabulary-maintainer",
    )
    args = parser.parse_args()

    current = parse_federal_register_thesaurus_2025_pdf(
        args.pdf.read_bytes()
    )
    historical = parse_federal_register_thesaurus(
        args.historical_source.read_bytes(),
        require_resolved=False,
    )
    crosswalk = build_federal_register_thesaurus_crosswalk(
        historical,
        current,
    )
    extract_bytes = federal_register_thesaurus_2025_extract_bytes(current)
    crosswalk_bytes = federal_register_thesaurus_crosswalk_bytes(crosswalk)
    _write_exact(args.resource_dir / "source-extract.json", extract_bytes)
    _write_exact(
        args.resource_dir / "crosswalk-1995-to-2025.json",
        crosswalk_bytes,
    )

    release = build_federal_register_thesaurus_2025_managed_release(
        current,
        crosswalk,
        recorded_at=args.recorded_at,
        recorded_by=args.recorded_by,
    )
    release.write_to(args.release_dir)
    manifest_bytes = release.artifact_bytes()["managed-release.json"]
    evidence = {
        "evidenceType": (
            "FederalRegisterThesaurus2025DevelopmentManagedRelease"
        ),
        "recordedAt": args.recorded_at,
        "operationalState": "developmentOnly",
        "source": {
            "id": release.manifest["release"]["source"],
            "issued": release.manifest["release"]["issued"],
            "digest": release.manifest["release"]["sourceSha256"],
            "byteLength": len(release.source_pdf),
            "pages": current.source_pages,
        },
        "managedRelease": {
            "id": release.manifest["id"],
            "manifestDigest": _sha256_bytes(manifest_bytes),
            "candidateLookupAllowed": True,
            "defaultForProfiles": ["federal-register-document-v1"],
            "priority": "strongSourceNative",
            "rootOntology": False,
            "acceptedOutputAllowed": False,
        },
        "counts": {
            **release.manifest["counts"],
            "recognizedVariantOccurrences": (
                current.counts.recognized_variant_occurrences
            ),
            "ambiguousVariantOccurrences": (
                current.counts.ambiguous_variant_occurrences
            ),
            "unresolvedVariantOccurrences": (
                current.counts.unresolved_variant_occurrences
            ),
            "crosswalk": crosswalk["counts"],
        },
        "boundaries": release.manifest["vocabularyBoundaries"],
        "interpretation": (
            "The April 1, 2025 publication is the default managed candidate "
            "vocabulary for Federal Register documents. Current API Topics "
            "remain mutable source-assigned metadata. The 1995 release remains "
            "available only for history, regression, and change analysis."
        ),
    }
    _write_exact(
        args.evidence,
        canonical_json(evidence).encode("utf-8") + b"\n",
    )
    print(json.dumps(evidence["counts"], indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
