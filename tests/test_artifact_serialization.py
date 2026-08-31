"""Shared package serialization helpers preserve SCR/MVB byte contracts."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

from refspec.registry.infrastructure.artifact_serialization import (
    canonical_json_bytes,
    file_sha256,
    path_sha256_descriptor,
    sha256_digest,
    source_artifact_path,
)


def test_canonical_json_bytes_are_newline_terminated() -> None:
    payload = canonical_json_bytes({"a": 1})

    assert payload.endswith(b"\n")
    assert sha256_digest(payload).startswith("sha256:")
    assert path_sha256_descriptor("x.json", payload) == {
        "path": "x.json",
        "sha256": sha256_digest(payload),
    }


def test_source_artifact_path_styles_remain_distinct() -> None:
    identifier = "https://example.test/source.bin"
    payload = b"exact-bytes"

    scr_path = source_artifact_path(identifier, payload, style="scr")
    mvb_path = source_artifact_path(identifier, payload, style="mvb")

    assert scr_path.startswith("sources/source-")
    assert mvb_path.startswith("sources/source-")
    assert scr_path != mvb_path


# --- file_sha256 replacement oracles -----------------------------------
#
# refspec.atlas.parquet_artifact.file_sha256 and
# refspec.registry.usc_act_index.file_sha256 were two byte-identical copies
# of this streaming hash before both call sites were switched to import it
# from here. Per AGENTS.md's replacement doctrine, both retired
# implementations are copied verbatim below as test-only oracles -- not
# imported, since importing the thing under replacement would make the
# comparison circular -- and this test proves verdict agreement over a
# mutation battery before trusting the shared function in their place.
#
# tools/build_usc_popular_names.py and tools/build_usc_source_credits.py
# carried a third and fourth copy, retired the same day. Both were, line for
# line, the same `for block in iter(lambda: handle.read(1 << 20), b"")`
# implementation already covered by `_usc_act_index_file_sha256_oracle`
# below -- not a near-match but the identical source text -- so no third
# oracle function is added here; that existing oracle's mutation battery
# already speaks for them.


def _usc_act_index_file_sha256_oracle(path: Path) -> str:
    """Copied verbatim from the pre-consolidation usc_act_index.py."""

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return f"sha256:{digest.hexdigest()}"


def _parquet_artifact_file_sha256_oracle(path: Path) -> str:
    """Copied verbatim from the pre-consolidation parquet_artifact.py."""

    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def test_file_sha256_matches_both_retired_copies_on_known_content(tmp_path: Path) -> None:
    target = tmp_path / "known.bin"
    target.write_bytes(b"gemet-theme-label-order")

    expected = "sha256:" + hashlib.sha256(b"gemet-theme-label-order").hexdigest()

    assert file_sha256(target) == expected
    assert _usc_act_index_file_sha256_oracle(target) == expected
    assert _parquet_artifact_file_sha256_oracle(target) == expected


def test_file_sha256_matches_both_retired_copies_over_a_mutation_battery(tmp_path: Path) -> None:
    chunk = 1024 * 1024
    sizes = (0, 1, 3, chunk - 1, chunk, chunk + 1, 2 * chunk, 2 * chunk + 17)

    for index, size in enumerate(sizes):
        payload = os.urandom(size)
        target = tmp_path / f"mutation-{index}.bin"
        target.write_bytes(payload)

        shared = file_sha256(target)
        assert shared == _usc_act_index_file_sha256_oracle(target)
        assert shared == _parquet_artifact_file_sha256_oracle(target)
        assert shared == "sha256:" + hashlib.sha256(payload).hexdigest()

    # A byte that only differs in the chunk immediately after a boundary
    # read still has to change the digest -- guards against an off-by-one
    # in the streaming loop silently dropping the final partial chunk.
    boundary = tmp_path / "boundary.bin"
    boundary.write_bytes(os.urandom(chunk) + b"\x00")
    boundary_flipped = tmp_path / "boundary-flipped.bin"
    boundary_flipped.write_bytes(boundary.read_bytes()[:-1] + b"\x01")

    assert file_sha256(boundary) != file_sha256(boundary_flipped)
    assert file_sha256(boundary) == _usc_act_index_file_sha256_oracle(boundary)
    assert file_sha256(boundary) == _parquet_artifact_file_sha256_oracle(boundary)
