"""The pinned-inputs manifest and its fetcher: what they accept, and what they refuse."""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import fetch_pinned_inputs as fetcher


def _entry(path: str, payload: bytes) -> dict:
    return {"path": path, "sha256": hashlib.sha256(payload).hexdigest(), "bytes": len(payload)}


def _manifest(tmp_path: Path, inputs: list[dict]) -> Path:
    path = tmp_path / "pinned_inputs.json"
    path.write_text(
        json.dumps({"bucket": "b", "endpoint": "https://r2.test", "key": "sha256/{sha256}", "inputs": inputs})
    )
    return path


class _FakeClient:
    """Serves one payload per key, standing in for R2."""

    def __init__(self, objects: dict[str, bytes]) -> None:
        self.objects = objects
        self.calls = 0

    def download_file(self, bucket: str, key: str, filename: str) -> None:
        self.calls += 1
        Path(filename).write_bytes(self.objects[key])


#: The only inputs R2 carries whose digest no tracked file records, each with why
#: its bytes are safe to freeze there. Both directions fail below: an unlisted
#: unrecorded entry, and a listed one whose digest has since been recorded.
PINNED_ONLY_BY_THE_MANIFEST = {
    "output/atlas-3.1-parquet-search-view-2026-08-21d/tables/resources.parquet": (
        "test_atlas_duckdb_view checks it against the member digest in the pinned view manifest"
    ),
    "output/atlas-3.1-parquet-search-view-2026-08-21d/tables/releases.parquet": (
        "test_atlas_duckdb_view checks it against the member digest in the pinned view manifest"
    ),
    "output/atlas-3.1-parquet-search-view-2026-08-21d/tables/derived-relations.parquet": (
        "test_atlas_duckdb_view checks it against the member digest in the pinned view manifest"
    ),
    "output/registry-real-data-sources/public-law-roster/public-law-roster.csv": (
        "generated from the pinned congress pages; the loud-tier suite regenerates and compares it"
    ),
    "output/registry-real-data-sources/public-law-roster/receipt.json": "the roster's build receipt",
    "output/usc-act-index-2026-08-02/receipt.json": "receipt of the dated index whose parquets act_resolution pins",
    "output/usc-source-credit-index-2026-08-02/quarantine.parquet": "part of the dated source-credit index",
    "output/usc-source-credit-index-2026-08-02/receipt.json": "receipt of the dated source-credit index",
}


def _recorded_digests(wanted: set[str]) -> set[str]:
    """The subset of ``wanted`` that appears in a tracked file other than the manifest.

    "Recorded" means the 64-hex string occurs, not that a reader verifies it: a
    reader's pin, a receipt or an evidence summary all count.
    """
    tracked = subprocess.run(["git", "ls-files", "-z"], cwd=ROOT, capture_output=True, check=True).stdout
    recorded: set[str] = set()
    for name in tracked.decode().split("\0"):
        path = ROOT / name
        if not name or name == "tools/pinned_inputs.json" or not path.is_file() or path.stat().st_size > 200_000_000:
            continue
        recorded.update(
            match.decode() for match in re.findall(rb"[0-9a-f]{64}", path.read_bytes()) if match.decode() in wanted
        )
    return recorded


def test_every_manifest_digest_is_recorded_elsewhere_in_the_repository() -> None:
    """R2 carries only bytes this repository already names; an unpinned file would ride on trust.

    Both directions: an input no tracked file records must be a named frozen
    exception, and a named exception whose digest has since been recorded is
    stale and must leave the list.
    """
    by_path = {entry["path"]: entry["sha256"] for entry in fetcher.load_manifest()["inputs"]}
    assert set(PINNED_ONLY_BY_THE_MANIFEST) <= set(by_path), "a frozen exception names an input the manifest dropped"
    recorded = _recorded_digests(set(by_path.values()))
    unrecorded = {path for path, digest in by_path.items() if digest not in recorded}
    assert unrecorded - set(PINNED_ONLY_BY_THE_MANIFEST) == set(), "an input nothing records rides on trust"
    assert set(PINNED_ONLY_BY_THE_MANIFEST) - unrecorded == set(), "a frozen exception is recorded now; drop it"


@pytest.mark.parametrize(
    ("inputs", "message"),
    [
        (
            [
                {"path": "output/b", "sha256": "0" * 64, "bytes": 1},
                {"path": "output/a", "sha256": "0" * 64, "bytes": 1},
            ],
            "sorted",
        ),
        ([{"path": "output/a", "sha256": "0" * 64, "bytes": 1}] * 2, "unique"),
        ([{"path": "src/refspec/x.py", "sha256": "0" * 64, "bytes": 1}], "under output/"),
        ([{"path": "output/../src/x", "sha256": "0" * 64, "bytes": 1}], "under output/"),
    ],
)
def test_manifest_refuses_unsorted_duplicate_and_escaping_paths(
    tmp_path: Path, inputs: list[dict], message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        fetcher.load_manifest(_manifest(tmp_path, inputs))


def test_a_download_that_does_not_hash_to_its_digest_is_refused_and_not_stored(tmp_path: Path) -> None:
    entry = _entry("output/a.json", b"published")
    client = _FakeClient({f"sha256/{entry['sha256']}": b"tampered"})
    manifest = json.loads(_manifest(tmp_path, [entry]).read_text())
    with pytest.raises(ValueError, match="does not hash"):
        fetcher._stored(tmp_path / "store", entry, client, manifest)
    assert not [path for path in (tmp_path / "store").rglob("*") if path.is_file()]


def test_a_verified_download_is_stored_once_and_hard_linked_into_place(tmp_path: Path) -> None:
    entry = _entry("output/a.json", b"published")
    client = _FakeClient({f"sha256/{entry['sha256']}": b"published"})
    manifest = json.loads(_manifest(tmp_path, [entry]).read_text())
    blob = fetcher._stored(tmp_path / "store", entry, client, manifest)
    assert fetcher._stored(tmp_path / "store", entry, client, manifest) == blob
    assert client.calls == 1
    target = tmp_path / entry["path"]
    fetcher._place(blob, target)
    assert target.read_bytes() == b"published" and target.stat().st_ino == blob.stat().st_ino
    assert fetcher.is_current(target, entry)
    assert not fetcher.is_current(target, dict(entry, sha256="0" * 64))
    assert not fetcher.is_current(target, dict(entry, bytes=entry["bytes"] + 1))


def test_a_symlink_at_the_target_is_never_current(tmp_path: Path) -> None:
    entry = _entry("output/a.json", b"published")
    real = tmp_path / "real.json"
    real.write_bytes(b"published")
    link = tmp_path / "link.json"
    link.symlink_to(real)
    assert fetcher.is_current(real, entry) and not fetcher.is_current(link, entry)


def _two_inputs(tmp_path: Path) -> tuple[dict, dict[str, bytes]]:
    first, second = _entry("output/a.json", b"first"), _entry("output/b.json", b"second")
    manifest = json.loads(_manifest(tmp_path, [first, second]).read_text())
    return manifest, {f"sha256/{first['sha256']}": b"first", f"sha256/{second['sha256']}": b"second"}


def test_a_cold_fetch_hashes_each_file_once_and_a_warm_one_builds_no_client(tmp_path: Path, monkeypatch) -> None:
    manifest, objects = _two_inputs(tmp_path)
    client = _FakeClient(objects)
    hashed: list[str] = []
    real_sha256 = fetcher.file_sha256
    monkeypatch.setattr(fetcher, "file_sha256", lambda path: hashed.append(path.name) or real_sha256(path))

    placed, downloaded = fetcher.fetch(manifest, tmp_path, tmp_path / "store", client_factory=lambda _m: client)
    assert (placed, downloaded, client.calls) == (2, 2, 2)
    # Targets and store objects are absent, so only the two downloads are hashed.
    assert len(hashed) == 2

    (tmp_path / "output" / "a.json").unlink()
    hashed.clear()

    def refuse(_manifest):
        raise AssertionError("a warm store needs no client")

    assert fetcher.fetch(manifest, tmp_path, tmp_path / "store", client_factory=refuse) == (1, 0)
    # b.json current (one hash), a.json's store object current (one hash).
    assert len(hashed) == 2


def test_prune_drops_only_objects_the_manifest_no_longer_lists(tmp_path: Path) -> None:
    manifest, objects = _two_inputs(tmp_path)
    fetcher.fetch(manifest, tmp_path, tmp_path / "store", client_factory=lambda _m: _FakeClient(objects))
    stale = tmp_path / "store" / "sha256" / ("f" * 64)
    stale.write_bytes(b"an older manifest's object")
    assert fetcher.prune(manifest, tmp_path / "store") == (1, len(b"an older manifest's object"))
    assert not stale.exists() and len(list((tmp_path / "store" / "sha256").iterdir())) == 2


def test_presence_is_size_only_and_refuses_a_symlink(tmp_path: Path) -> None:
    entry = _entry("output/a.json", b"published")
    target = tmp_path / "a.json"
    target.write_bytes(b"tampered!")  # same length, different bytes
    assert fetcher.is_present(target, entry) and not fetcher.is_current(target, entry)
    assert not fetcher.is_present(target, dict(entry, bytes=entry["bytes"] + 1))
    link = tmp_path / "link.json"
    link.symlink_to(target)
    assert not fetcher.is_present(link, entry)
