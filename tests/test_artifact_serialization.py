"""Shared package serialization helpers preserve SCR/MVB byte contracts."""

from __future__ import annotations

from refspec.registry.infrastructure.artifact_serialization import (
    canonical_json_bytes,
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
