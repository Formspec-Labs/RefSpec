"""Mint or verify one distribution seal from the command line.

The seal is the last step of the four verbs -- build, prove once, sign, serve --
and it is the only one that needs a key the repository deliberately does not
hold. `src/refspec/seal.py` has carried `create_seal`/`verify_seal` since the
seal-2 format landed, but the only callers were tests, so minting a seal meant
writing a throwaway Python snippet and getting the argument order right by
reading the source. That is a bad shape for a step performed rarely, under
ceremony, by whoever holds the offline key. This is that call, spelled once.

Signing is refused unless the distribution already carries an acceptance
receipt, because a seal over an unproven distribution asserts something nobody
checked -- the seal binds the acceptance digest precisely so a consumer can
tell "signed" from "signed AND proven".
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT / "src"))

from refspec.seal import (
    ACCEPTANCE_MEMBER,
    SealError,
    create_seal,
    verify_seal,
)

DEFAULT_ALLOWED_SIGNERS = REPOSITORY_ROOT / "docs" / "seal-allowed-signers"


def _mint(args: argparse.Namespace) -> int:
    root = Path(args.distribution)
    acceptance = root / ACCEPTANCE_MEMBER
    if not acceptance.is_file():
        raise SealError(
            f"refusing to sign a distribution with no acceptance receipt: {acceptance}. "
            "Run validate.py --distribution over it first; the seal binds the "
            "acceptance digest so a consumer can distinguish signed from proven."
        )
    seal_path = create_seal(
        root,
        args.private_key,
        args.signer_identity,
        seal_path=args.output,
        parquet_view_path=args.parquet_view,
    )
    payload = json.loads(Path(seal_path).read_text())["payload"]
    print(
        json.dumps(
            {
                "sealPath": str(seal_path),
                "distributionId": payload.get("distributionId"),
                "manifestSha256": payload.get("manifestSha256"),
                "acceptanceSha256": payload.get("acceptanceSha256"),
                "parquetViewManifestSha256": payload.get("parquetViewManifestSha256"),
                "signerIdentity": args.signer_identity,
            },
            sort_keys=True,
        )
    )
    return 0


def _verify(args: argparse.Namespace) -> int:
    result = verify_seal(
        args.distribution,
        args.seal,
        args.allowed_signers,
        parquet_view_path=args.parquet_view,
    )
    print(json.dumps(result.as_dict() if hasattr(result, "as_dict") else str(result), sort_keys=True))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)

    mint = sub.add_parser("mint", help="sign a proven distribution")
    mint.add_argument("--distribution", required=True)
    mint.add_argument("--private-key", required=True, help="path to the offline signing key")
    mint.add_argument("--signer-identity", required=True, help="e.g. atlas-release@refspec")
    mint.add_argument("--parquet-view", default=None)
    mint.add_argument("--output", default=None)
    mint.set_defaults(func=_mint)

    check = sub.add_parser("verify", help="verify a seal against the allowed signers")
    check.add_argument("--distribution", required=True)
    check.add_argument("--seal", required=True)
    check.add_argument("--allowed-signers", default=str(DEFAULT_ALLOWED_SIGNERS))
    check.add_argument("--parquet-view", default=None)
    check.set_defaults(func=_verify)

    args = parser.parse_args()
    try:
        return int(args.func(args))
    except SealError as error:
        print(f"seal error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
