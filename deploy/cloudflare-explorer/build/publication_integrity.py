"""Freeze precomputed outputs and compare authenticated inventory with served bytes.

This qualifies an immutable candidate. Promotion and deployment remain separate.
"""

from __future__ import annotations

import argparse
import hashlib
import http.client
import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path, PurePosixPath

INVENTORY = "publication-inventory.json"
_DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")


def digest_bytes(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return "sha256:" + digest.hexdigest()


def _digest(value: str) -> str:
    if not _DIGEST.fullmatch(value):
        raise ValueError("an externally pinned sha256 digest is required")
    return value


def _files(root: Path) -> dict[str, Path]:
    files = {}
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise ValueError(f"publication tree contains a symlink: {path}")
        if path.is_file() and path.relative_to(root).as_posix() != INVENTORY:
            key = path.relative_to(root).as_posix()
            if any(character in key for character in "\n\r\t"):
                raise ValueError("publication paths must not contain line separators")
            files[key] = path
    if not files:
        raise ValueError("publication tree contains no output objects")
    return files


def freeze_inventory(root: Path, *, search_view_digest: str, release: bool) -> str:
    document = {
        "type": "AtlasExplorerPublicationInventory",
        "version": 1,
        "trustedSearchViewManifestDigest": _digest(search_view_digest),
        "releaseInputAuthenticated": release,
        "objects": [
            {"path": key, "byteLength": path.stat().st_size, "digest": file_digest(path)}
            for key, path in _files(root).items()
        ],
    }
    payload = (json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n").encode()
    (root / INVENTORY).write_bytes(payload)
    return digest_bytes(payload)


def load_inventory(root: Path, *, inventory_digest: str, search_view_digest: str) -> tuple[dict, dict]:
    payload = (root / INVENTORY).read_bytes()
    if digest_bytes(payload) != _digest(inventory_digest):
        raise ValueError("publication inventory digest differs from trusted pin")
    document = json.loads(payload)
    if document.get("type") != "AtlasExplorerPublicationInventory" or document.get("version") != 1:
        raise ValueError("unsupported publication inventory")
    if document.get("releaseInputAuthenticated") is not True:
        raise ValueError("development inventory cannot qualify a release")
    if document.get("trustedSearchViewManifestDigest") != _digest(search_view_digest):
        raise ValueError("publication inventory belongs to a different search view")
    objects = {}
    for row in document["objects"]:
        key = row["path"]
        path = PurePosixPath(key)
        if path.is_absolute() or ".." in path.parts or str(path) != key or key == INVENTORY or key in objects:
            raise ValueError("publication inventory contains an unsafe or duplicate path")
        if not isinstance(row["byteLength"], int) or row["byteLength"] < 0:
            raise ValueError("publication inventory length is invalid")
        _digest(row["digest"])
        objects[key] = row
    if not objects:
        raise ValueError("publication inventory is empty")
    objects[INVENTORY] = {"path": INVENTORY, "byteLength": len(payload), "digest": inventory_digest}
    return document, objects


def check_local(root: Path, objects: dict, *, allow_additions: bool = False) -> None:
    actual = set(_files(root)) | {INVENTORY}
    if (not set(objects) <= actual) or (not allow_additions and actual != set(objects)):
        raise ValueError("local output membership differs from frozen inventory")
    for key, row in objects.items():
        path = root / key
        if path.stat().st_size != row["byteLength"] or file_digest(path) != row["digest"]:
            raise ValueError(f"local output differs from frozen inventory: {key}")


def candidate_prefix(inventory_digest: str) -> str:
    return "candidates/" + _digest(inventory_digest).removeprefix("sha256:")


def verify_object(base: str, prefix: str, key: str, row: dict, *, worker_version: str) -> dict:
    url = base.rstrip("/") + "/data/" + urllib.parse.quote("/".join(part for part in (prefix, key) if part), safe="/")
    digest = hashlib.sha256()
    length = 0
    try:
        request = urllib.request.Request(url, headers={"Accept-Encoding": "identity", "Cache-Control": "no-cache"})
        with urllib.request.urlopen(request, timeout=60) as response:
            if response.status != 200:
                return {"path": key, "status": "error", "detail": f"HTTP {response.status}"}
            observed_version = response.headers.get("x-atlas-worker-version")
            if not worker_version or observed_version != worker_version:
                return {
                    "path": key,
                    "status": "mismatch",
                    "detail": "Worker version differs or is missing",
                    "observedWorkerVersion": observed_version,
                }
            while True:
                try:
                    block = response.read(1024 * 1024)
                except http.client.IncompleteRead as error:
                    block = error.partial
                    digest.update(block)
                    length += len(block)
                    break
                if not block:
                    break
                digest.update(block)
                length += len(block)
                if length > row["byteLength"]:
                    break
    except urllib.error.HTTPError as error:
        return {
            "path": key,
            "status": "missing" if error.code in {404, 410} else "error",
            "detail": f"HTTP {error.code}",
        }
    except (OSError, urllib.error.URLError, http.client.HTTPException) as error:
        return {"path": key, "status": "error", "detail": str(error)}
    actual = "sha256:" + digest.hexdigest()
    return {
        "path": key,
        "status": "passed" if length == row["byteLength"] and actual == row["digest"] else "mismatch",
        "observedWorkerVersion": observed_version,
        "actualByteLength": length,
        "actualDigest": actual,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("freeze", "check-local", "verify-object", "verify-public"))
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--inventory-digest", required=True)
    parser.add_argument("--search-view-digest", required=True)
    parser.add_argument("--base")
    parser.add_argument("--key")
    parser.add_argument("--account-id")
    parser.add_argument("--worker-version")
    parser.add_argument("--source-revision")
    parser.add_argument("--receipt", type=Path)
    parser.add_argument(
        "--active", action="store_true", help="verify active /data/<path> selection instead of direct candidate URLs"
    )
    args = parser.parse_args()
    if args.active and args.action != "verify-public":
        parser.error("--active requires verify-public")
    try:
        prefix = "" if args.active else candidate_prefix(args.inventory_digest)
        _, objects = load_inventory(
            args.root, inventory_digest=args.inventory_digest, search_view_digest=args.search_view_digest
        )
        if args.action == "freeze":
            check_local(args.root, objects, allow_additions=True)
            print(freeze_inventory(args.root, search_view_digest=args.search_view_digest, release=True))
            return 0
        if args.action == "check-local":
            check_local(args.root, objects)
            return 0
        if not args.base:
            raise ValueError("public verification requires --base")
        if args.action == "verify-object":
            if not args.worker_version:
                raise ValueError("served-byte verification requires --worker-version")
            if args.key not in objects:
                raise ValueError("object is absent from frozen inventory")
            results = [
                verify_object(
                    args.base,
                    prefix,
                    args.key,
                    objects[args.key],
                    worker_version=args.worker_version,
                )
            ]
        else:
            if not all((args.account_id, args.worker_version, args.source_revision, args.receipt)):
                raise ValueError("public verification requires account, Worker version, source revision and receipt")
            if args.receipt.resolve().is_relative_to(args.root.resolve()):
                raise ValueError("receipt must be outside the frozen output tree")
            check_local(args.root, objects)
            results = [
                verify_object(args.base, prefix, key, row, worker_version=args.worker_version)
                for key, row in objects.items()
            ]
        status = (
            2
            if any(row["status"] == "error" for row in results)
            else int(any(row["status"] != "passed" for row in results))
        )
        if args.action == "verify-public":
            receipt = {
                "type": "AtlasExplorerActiveVerification" if args.active else "AtlasExplorerCandidateVerification",
                "verificationScope": "active" if args.active else "candidate",
                "activeSelectionVerified": args.active and status == 0,
                "verifiedDataBaseUrl": args.base.rstrip("/") + "/data/" + (prefix + "/" if prefix else ""),
                "status": "passed" if status == 0 else "failed",
                "inventoryDigest": args.inventory_digest,
                "trustedSearchViewManifestDigest": args.search_view_digest,
                "candidatePrefix": candidate_prefix(args.inventory_digest),
                "publicBaseUrl": args.base,
                "reportedAccountId": args.account_id,
                "expectedWorkerVersion": args.worker_version,
                "sourceRevision": args.source_revision,
                "objects": results,
                "promoted": False,
            }
            args.receipt.parent.mkdir(parents=True, exist_ok=True)
            args.receipt.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
        for result in results:
            if result["status"] != "passed":
                print(json.dumps(result, sort_keys=True), file=sys.stderr)
        return status
    except (ValueError, KeyError, TypeError, OSError) as error:
        print(f"ERROR publication verification: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
