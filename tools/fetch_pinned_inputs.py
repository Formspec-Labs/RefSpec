"""Put the pinned inputs under ``output/`` in place from R2, each verified against its digest.

``output/`` is gitignored, so a clean clone has none of the publisher captures the
suite reads. ``tools/pinned_inputs.json`` lists every file under it whose SHA-256
this repository records somewhere (a reader's pin, a manifest, a receipt), plus
the few frozen receipts and rosters ``tests/test_fetch_pinned_inputs.py`` names,
which only the manifest's digest pins. The bytes live in the private
``refspec-pinned-inputs`` R2 bucket under ``sha256/<hex>``. R2 is only transport:
a download that does not hash to the manifest's digest is refused, and the
readers verify their own pins again.

Objects are kept in a content-addressed store (``--store``) and hard-linked into
place, so CI caches one directory and a warm run downloads nothing. A file
already at its path with the recorded size and digest is left alone, so running
this on a machine that has ``output/`` costs one hash pass.

Credentials are a read-only R2 token in ``REFSPEC_R2_ACCESS_KEY_ID`` and
``REFSPEC_R2_SECRET_ACCESS_KEY``; ``--check`` verifies without them.

Adding an input: pin its digest where its reader checks it, upload it with
``npx wrangler r2 object put refspec-pinned-inputs/sha256/<hex> --file <path> --remote``,
and add its entry here (entries stay sorted by path).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "tools" / "pinned_inputs.json"
# Inside output/, like every other byte this repository reads at runtime.
DEFAULT_STORE = ROOT / "output" / ".pinned-store"


def load_manifest(path: Path = MANIFEST) -> dict:
    """Read the manifest, refusing unsorted, duplicate or escaping paths."""
    manifest = json.loads(path.read_text())
    paths = [entry["path"] for entry in manifest["inputs"]]
    if paths != sorted(paths) or len(set(paths)) != len(paths):
        raise ValueError("pinned inputs must be unique and sorted by path")
    for entry in manifest["inputs"]:
        relative = Path(entry["path"])
        if relative.is_absolute() or ".." in relative.parts or relative.parts[0] != "output":
            raise ValueError(f"pinned input must live under output/: {entry['path']}")
    return manifest


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 22), b""):
            digest.update(chunk)
    return digest.hexdigest()


def is_current(path: Path, entry: dict) -> bool:
    """True when ``path`` is a regular file with the entry's size and digest."""
    if path.is_symlink() or not path.is_file() or path.stat().st_size != entry["bytes"]:
        return False
    return file_sha256(path) == entry["sha256"]


def _client(manifest: dict):
    import boto3  # locked through the dev group; only a download needs it

    return boto3.client(
        "s3",
        endpoint_url=os.environ.get("REFSPEC_R2_ENDPOINT", manifest["endpoint"]),
        aws_access_key_id=os.environ["REFSPEC_R2_ACCESS_KEY_ID"],
        aws_secret_access_key=os.environ["REFSPEC_R2_SECRET_ACCESS_KEY"],
        region_name="auto",
    )


def _blob(store: Path, entry: dict) -> Path:
    return store / "sha256" / entry["sha256"]


def _download(store: Path, entry: dict, client, manifest: dict) -> Path:
    """Download ``entry``'s object into the store, refusing bytes that do not hash to its digest."""
    blob = _blob(store, entry)
    blob.parent.mkdir(parents=True, exist_ok=True)
    partial = blob.with_name(blob.name + ".part")
    client.download_file(manifest["bucket"], manifest["key"].format(sha256=entry["sha256"]), str(partial))
    if not is_current(partial, entry):
        partial.unlink(missing_ok=True)
        raise ValueError(f"R2 object for {entry['path']} does not hash to its recorded digest")
    os.replace(partial, blob)
    return blob


def _stored(store: Path, entry: dict, client, manifest: dict) -> Path:
    """Return the verified store object for ``entry``, downloading it if absent."""
    blob = _blob(store, entry)
    return blob if is_current(blob, entry) else _download(store, entry, client, manifest)


def _place(blob: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    staged = target.with_name(target.name + ".fetching")
    staged.unlink(missing_ok=True)
    try:
        os.link(blob, staged)
    except OSError:
        shutil.copyfile(blob, staged)
    os.replace(staged, target)


def is_present(path: Path, entry: dict) -> bool:
    """True when ``path`` is a regular file of the entry's size: the cheap check every test tier runs."""
    return not path.is_symlink() and path.is_file() and path.stat().st_size == entry["bytes"]


def fetch(manifest: dict, root: Path, store: Path, *, client_factory=_client, workers: int = 8) -> tuple[int, int]:
    """Place every input not already current under ``root``; return (placed, downloaded).

    Each file is hashed once: a target's digest decides whether it is current,
    a store object's decides whether it needs downloading, and a download is
    hashed as it is verified. Several paths can share one object, so each
    object is resolved once and then linked to every path that names it. A
    warm store builds no client, so it needs no credentials.
    """
    entries = manifest["inputs"]
    with ThreadPoolExecutor(workers) as pool:
        verdicts = pool.map(lambda entry: is_current(root / entry["path"], entry), entries)
        missing = [entry for entry, ok in zip(entries, verdicts, strict=True) if not ok]
    unique = list({entry["sha256"]: entry for entry in missing}.values())
    with ThreadPoolExecutor(workers) as pool:
        stored = pool.map(lambda entry: is_current(_blob(store, entry), entry), unique)
        absent = [entry for entry, ok in zip(unique, stored, strict=True) if not ok]
    if absent:
        client = client_factory(manifest)
        with ThreadPoolExecutor(workers) as pool:
            list(pool.map(lambda entry: _download(store, entry, client, manifest), absent))
    for entry in missing:
        _place(_blob(store, entry), root / entry["path"])
    return len(missing), len(absent)


def prune(manifest: dict, store: Path) -> tuple[int, int]:
    """Delete store objects the manifest no longer names; return (objects, bytes) removed.

    CI restores the newest store under a prefix key, so without this it would
    grow by every manifest it has ever seen.
    """
    wanted = {entry["sha256"] for entry in manifest["inputs"]}
    removed = removed_bytes = 0
    for blob in sorted((store / "sha256").glob("*")) if (store / "sha256").is_dir() else ():
        if blob.name not in wanted:
            removed_bytes += blob.stat().st_size
            blob.unlink()
            removed += 1
    return removed, removed_bytes


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true", help="verify local files by digest; download nothing")
    mode.add_argument("--present", action="store_true", help="check local files by size only; download nothing")
    parser.add_argument("--prune", action="store_true", help="after fetching, drop store objects no longer listed")
    parser.add_argument("--store", type=Path, default=DEFAULT_STORE)
    parser.add_argument("--workers", type=int, default=8)
    args = parser.parse_args()

    manifest = load_manifest()
    entries = manifest["inputs"]
    if args.check or args.present:
        verify = is_present if args.present else is_current
        with ThreadPoolExecutor(args.workers) as pool:
            verdicts = pool.map(lambda entry: verify(ROOT / entry["path"], entry), entries)
            missing = [entry for entry, ok in zip(entries, verdicts, strict=True) if not ok]
        for entry in missing:
            print(f"missing or different: {entry['path']}", file=sys.stderr)
        if missing:
            print(
                f"{len(missing)} of {len(entries)} pinned inputs absent; run `make fetch-pinned-inputs`",
                file=sys.stderr,
            )
            return 1
        print(f"{len(entries)} pinned inputs present{'' if args.present else ' and verified'}")
        return 0

    placed, downloaded = fetch(manifest, ROOT, args.store, workers=args.workers)
    print(
        f"placed {placed} of {len(entries)} pinned inputs ({downloaded} downloaded); {len(entries) - placed} were already current"
    )
    if args.prune:
        removed, removed_bytes = prune(manifest, args.store)
        print(f"pruned {removed} store objects ({removed_bytes / 1e6:.0f} MB) the manifest no longer lists")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
