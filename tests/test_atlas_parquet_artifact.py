from __future__ import annotations

from refspec.atlas.parquet_artifact import (
    PARQUET_MEMBER_FIELDS,
    artifact_file_paths,
    normalize_sha256_prefix,
)


def test_artifact_file_paths_includes_nested_files_and_symlinks(tmp_path) -> None:
    nested = tmp_path / "tables"
    nested.mkdir()
    (nested / "resources.parquet").write_bytes(b"parquet")
    (tmp_path / "view-manifest.json").write_text("{}\n", encoding="utf-8")
    (tmp_path / "unsafe-link").symlink_to("missing")

    assert artifact_file_paths(tmp_path) == {
        "tables/resources.parquet",
        "unsafe-link",
        "view-manifest.json",
    }


def test_parquet_member_fields_match_the_shared_manifest_shape() -> None:
    assert PARQUET_MEMBER_FIELDS == {
        "byteLength",
        "mediaType",
        "path",
        "role",
        "rowCount",
        "schemaDigest",
        "sha256",
    }


def test_normalize_sha256_prefix_accepts_bare_and_prefixed_digests() -> None:
    bare = "a" * 64

    assert normalize_sha256_prefix(bare) == "sha256:" + bare
    assert normalize_sha256_prefix("sha256:" + bare) == "sha256:" + bare
