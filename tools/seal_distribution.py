"""Mint or verify a seal for one selected Atlas generation.

Pin the selection once, then use its concrete sibling artifacts. The seal
primitives retain acceptance, digest, signature, pairing and membership checks.

Minting is an offline-key ceremony step, performed rarely by whoever holds the
key this repository does not. Signing requires a passed acceptance receipt
(``create_seal`` enforces it), because the seal binds the acceptance digest so a
consumer can tell "signed" from "signed AND proven".
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT / "src"))

from refspec.atlas.generation import AtlasGeneration, select_atlas_generation
from refspec.seal import SealError, create_seal, verify_seal

DEFAULT_ALLOWED_SIGNERS = REPOSITORY_ROOT / "docs" / "seal-allowed-signers"


def _mint(args: argparse.Namespace, generation: AtlasGeneration) -> int:
    """Sign only after the seal primitive verifies the selected artifacts."""
    seal_path = create_seal(
        generation.distribution,
        args.private_key,
        args.signer_identity,
        seal_path=generation.seal,
        parquet_view_path=generation.parquet_view,
        vocabulary_pack=args.vocabulary_pack,
        semantic_sidecar=args.semantic_sidecar,
    )
    payload = json.loads(seal_path.read_text())["payload"]
    summary = {
        "sealPath": str(seal_path),
        "sealFormat": payload["sealFormat"],
        "distributionId": payload["distributionId"],
        "manifestSha256": payload["manifestSha256"],
        "acceptanceSha256": payload["acceptanceSha256"],
        "parquetViewManifestSha256": payload["parquetViewManifestSha256"],
        "signerIdentity": args.signer_identity,
    }
    if "vocabularyPackSha256" in payload:
        summary["vocabularyPackSha256"] = payload["vocabularyPackSha256"]
    if "semanticSidecarSha256" in payload:
        summary["semanticSidecarSha256"] = payload["semanticSidecarSha256"]
    print(json.dumps(summary, sort_keys=True))
    return 0


def _verify(args: argparse.Namespace, generation: AtlasGeneration) -> int:
    """Verify the selected seal and every artifact it binds."""
    result = verify_seal(
        generation.distribution,
        generation.seal,
        args.allowed_signers,
        parquet_view_path=generation.parquet_view,
        vocabulary_pack=args.vocabulary_pack,
        semantic_sidecar=args.semantic_sidecar,
        previous_created_at=args.previous_created_at,
        reject_distribution_ids=args.reject_distribution_id,
    )
    print(json.dumps(asdict(result), sort_keys=True))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)

    mint = sub.add_parser("mint", help="sign a selected generation")
    mint.add_argument("--selection", required=True)
    mint.add_argument("--private-key", required=True, help="path to the offline signing key")
    mint.add_argument("--signer-identity", required=True)
    mint.add_argument("--vocabulary-pack", default=None, help="optional detached SQLite vocabulary pack for seal-3")
    mint.add_argument("--semantic-sidecar", default=None, help="optional detached .vpack semantic sidecar for seal-3")
    mint.set_defaults(func=_mint)

    check = sub.add_parser("verify", help="verify a selected generation")
    check.add_argument("--selection", required=True)
    check.add_argument("--allowed-signers", default=str(DEFAULT_ALLOWED_SIGNERS))
    check.add_argument("--vocabulary-pack", default=None, help="optional detached SQLite vocabulary pack for seal-3")
    check.add_argument("--semantic-sidecar", default=None, help="optional detached .vpack semantic sidecar for seal-3")
    check.add_argument(
        "--previous-created-at",
        default=None,
        help="optional ISO-8601 minimum manifest createdAt anti-rollback timestamp",
    )
    check.add_argument(
        "--reject-distribution-id",
        action="append",
        default=None,
        help="optional revoked or disallowed distributionId to refuse (repeatable)",
    )
    check.set_defaults(func=_verify)

    args = parser.parse_args()
    try:
        return args.func(args, select_atlas_generation(args.selection))
    except (SealError, OSError, ValueError) as error:
        print(f"seal error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
