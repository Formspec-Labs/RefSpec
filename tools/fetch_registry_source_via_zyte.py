#!/usr/bin/env python3
"""Fetch one exact publisher artifact through Zyte into RefSpec's ignored output."""

from __future__ import annotations

import argparse
import hashlib
import os
from pathlib import Path

from refspec.registry.infrastructure.zyte_transport import ZyteHttpFetcher

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def _load_local_zyte_token(dotenv_path: Path) -> None:
    """Load only ZYTE_TOKEN from the named local dotenv without logging it."""

    if os.environ.get("ZYTE_TOKEN"):
        return
    for line in dotenv_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        name, value = stripped.split("=", 1)
        if name.strip() != "ZYTE_TOKEN":
            continue
        token = value.strip()
        if len(token) >= 2 and token[0] == token[-1] and token[0] in {"'", '"'}:
            token = token[1:-1]
        os.environ["ZYTE_TOKEN"] = token
        return
    raise ValueError(f"{dotenv_path} contains no ZYTE_TOKEN")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("url")
    parser.add_argument("output", type=Path)
    parser.add_argument("--dotenv", type=Path, default=REPOSITORY_ROOT / ".env")
    parser.add_argument("--max-bytes", type=int, default=25_000_000)
    parser.add_argument("--timeout", type=float, default=180.0)
    parser.add_argument("--expected-sha256")
    parser.add_argument("--expected-byte-length", type=int)
    args = parser.parse_args()

    _load_local_zyte_token(args.dotenv)
    response = ZyteHttpFetcher.from_environment().fetch(
        args.url,
        timeout_seconds=args.timeout,
        max_bytes=args.max_bytes,
    )
    if response.status_code != 200:
        raise ValueError(f"publisher returned HTTP {response.status_code} through Zyte")
    digest = "sha256:" + hashlib.sha256(response.body).hexdigest()
    if args.expected_sha256 is not None and digest != args.expected_sha256:
        raise ValueError(f"source digest drift: expected {args.expected_sha256}, got {digest}")
    if args.expected_byte_length is not None and len(response.body) != args.expected_byte_length:
        raise ValueError(
            f"source byte length drift: expected {args.expected_byte_length}, got {len(response.body)}"
        )

    output = args.output if args.output.is_absolute() else REPOSITORY_ROOT / args.output
    output = output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(response.body)
    print(
        f"saved {output.relative_to(REPOSITORY_ROOT)} "
        f"bytes={len(response.body)} sha256={digest} content_type={response.content_type!r}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
