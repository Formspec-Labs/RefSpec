from __future__ import annotations

import json
from pathlib import Path

import pytest

from refspec.atlas import compact_pack
from refspec.atlas.compact_pack import (
    CompactPackError,
    CompactPackHeader,
    build_compact_pack,
    read_compact_pack,
    write_compact_pack,
)
from refspec.registry.infrastructure.artifact_serialization import sha256_digest


def _header(**overrides: object) -> CompactPackHeader:
    values: dict[str, object] = {
        "role": "resources",
        "path": "packs/resources/00.jsonl.zst",
        "defaults": {
            "release": "urn:ref:release:test",
            "ring": "subject",
        },
        "dependencies": ("urn:ref:pack:z", "urn:ref:pack:a"),
        "partition": {"prefix": "00", "strategy": "sha256-id-prefix"},
    }
    values.update(overrides)
    return CompactPackHeader(**values)  # type: ignore[arg-type]


def _rows() -> list[dict[str, object]]:
    return [
        {
            "id": "urn:ref:resource:b",
            "label": "Beta",
            "contentDigest": "publisher-specific-digest",
        },
        {
            "id": "urn:ref:resource:a",
            "label": "Alpha",
            "ring": "entity",
        },
    ]


def _rewrite_pack(
    directory: Path,
    descriptor: dict[str, object],
    content: bytes,
) -> dict[str, object]:
    transport = compact_pack.zstd.compress(content, level=9)
    updated = json.loads(json.dumps(descriptor))
    content_descriptor = updated["content"]
    transport_descriptor = updated["transport"]
    assert isinstance(content_descriptor, dict)
    assert isinstance(transport_descriptor, dict)
    content_digest = sha256_digest(content)
    content_descriptor["byteLength"] = len(content)
    content_descriptor["digest"] = content_digest
    transport_descriptor["byteLength"] = len(transport)
    transport_descriptor["digest"] = sha256_digest(transport)
    updated["packId"] = compact_pack.PACK_ID_PREFIX + content_digest.removeprefix("sha256:")
    path = updated["path"]
    assert isinstance(path, str)
    target = directory.joinpath(*path.split("/"))
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(transport)
    return updated


def test_compact_pack_round_trip_expands_defaults_and_preserves_row_digests(
    tmp_path: Path,
) -> None:
    inventory = write_compact_pack(tmp_path, _header(), _rows())

    stored = read_compact_pack(tmp_path, inventory.to_dict())

    assert [row["id"] for row in stored.rows] == [
        "urn:ref:resource:a",
        "urn:ref:resource:b",
    ]
    assert stored.rows[0] == {
        "id": "urn:ref:resource:a",
        "label": "Alpha",
        "release": "urn:ref:release:test",
        "ring": "entity",
    }
    assert stored.rows[1] == {
        "id": "urn:ref:resource:b",
        "label": "Beta",
        "release": "urn:ref:release:test",
        "ring": "subject",
        "contentDigest": "publisher-specific-digest",
    }
    content_lines = stored.content.decode("utf-8").splitlines()
    assert json.loads(content_lines[0]) == {
        "type": "AtlasCompactPackHeader",
        "schemaVersion": "1.0",
        "role": "resources",
        "dependencies": ["urn:ref:pack:a", "urn:ref:pack:z"],
        "defaults": {
            "release": "urn:ref:release:test",
            "ring": "subject",
        },
        "partition": {"prefix": "00", "strategy": "sha256-id-prefix"},
    }
    assert '"release"' not in content_lines[1]
    assert (
        content_lines[1]
        == '{"id":"urn:ref:resource:a","label":"Alpha","ring":"entity"}'
    )
    descriptor = stored.inventory.to_dict()
    assert descriptor["dependencies"] == ["urn:ref:pack:a", "urn:ref:pack:z"]
    assert descriptor["content"]["recordCount"] == 2  # type: ignore[index]
    assert descriptor["content"]["digest"] == sha256_digest(stored.content)  # type: ignore[index]
    assert descriptor["transport"]["digest"] == sha256_digest(stored.transport)  # type: ignore[index]
    assert descriptor["logicalRowsDigest"] != descriptor["content"]["digest"]  # type: ignore[index]


def test_compact_pack_bytes_are_stable_across_input_order_and_explicit_defaults() -> None:
    first = build_compact_pack(_header(), _rows())
    second = build_compact_pack(
        _header(
            defaults={"ring": "subject", "release": "urn:ref:release:test"},
            dependencies=("urn:ref:pack:a", "urn:ref:pack:z"),
        ),
        [
            {
                **_rows()[1],
                "release": "urn:ref:release:test",
            },
            {
                **_rows()[0],
                "release": "urn:ref:release:test",
                "ring": "subject",
            },
        ],
    )

    assert second.content == first.content
    assert second.transport == first.transport
    assert second.inventory.to_dict() == first.inventory.to_dict()


def test_compact_pack_content_identity_seals_pack_defaults() -> None:
    first = build_compact_pack(_header(), _rows())
    changed = build_compact_pack(
        _header(
            defaults={
                "release": "urn:ref:release:changed",
                "ring": "subject",
            }
        ),
        _rows(),
    )

    assert changed.inventory.pack_id != first.inventory.pack_id
    assert changed.inventory.content["digest"] != first.inventory.content["digest"]


def test_compact_pack_rejects_duplicate_ids() -> None:
    with pytest.raises(CompactPackError, match="duplicate row id"):
        build_compact_pack(
            _header(),
            [{"id": "urn:duplicate"}, {"id": "urn:duplicate", "label": "again"}],
        )


@pytest.mark.parametrize(
    "path",
    [
        "/tmp/resources.jsonl.zst",
        "../resources.jsonl.zst",
        "packs/../resources.jsonl.zst",
        "packs\\resources.jsonl.zst",
        "packs//resources.jsonl.zst",
        "packs/resources:00.jsonl.zst",
        "packs/resource rows.jsonl.zst",
        "packs/resources.jsonl",
    ],
)
def test_compact_pack_rejects_unsafe_or_nonpack_paths(path: str) -> None:
    with pytest.raises(CompactPackError, match=r"\$\.path"):
        build_compact_pack(_header(path=path), _rows())


@pytest.mark.parametrize("field", ["id", "contentDigest", "canonicalPayloadDigest"])
def test_compact_pack_rejects_identity_fields_in_defaults(field: str) -> None:
    with pytest.raises(CompactPackError, match="cannot be defaults"):
        build_compact_pack(_header(defaults={field: "unsafe"}), _rows())


def test_compact_pack_rejects_transport_digest_and_length_tampering(tmp_path: Path) -> None:
    inventory = write_compact_pack(tmp_path, _header(), _rows())
    digest_tamper = inventory.to_dict()
    digest_tamper["transport"]["digest"] = "sha256:" + "0" * 64  # type: ignore[index]
    with pytest.raises(CompactPackError, match="transport digest"):
        read_compact_pack(tmp_path, digest_tamper)

    length_tamper = inventory.to_dict()
    length_tamper["transport"]["byteLength"] += 1  # type: ignore[index,operator]
    with pytest.raises(CompactPackError, match="transport byte length"):
        read_compact_pack(tmp_path, length_tamper)


def test_compact_pack_rejects_content_length_and_expanded_defaults_tampering(
    tmp_path: Path,
) -> None:
    inventory = write_compact_pack(tmp_path, _header(), _rows())
    content_length_tamper = inventory.to_dict()
    content_length_tamper["content"]["byteLength"] += 1  # type: ignore[index,operator]
    with pytest.raises(CompactPackError, match="decompressed content byte length"):
        read_compact_pack(tmp_path, content_length_tamper)

    defaults_tamper = inventory.to_dict()
    defaults_tamper["defaults"]["release"] = "urn:ref:release:other"  # type: ignore[index]
    with pytest.raises(CompactPackError, match="header does not match"):
        read_compact_pack(tmp_path, defaults_tamper)

    logical_digest_tamper = inventory.to_dict()
    logical_digest_tamper["logicalRowsDigest"] = "sha256:" + "0" * 64
    with pytest.raises(CompactPackError, match="expanded logical row digest"):
        read_compact_pack(tmp_path, logical_digest_tamper)


def test_compact_pack_parser_fails_closed_on_noncanonical_and_out_of_order_rows(
    tmp_path: Path,
) -> None:
    inventory = write_compact_pack(tmp_path, _header(defaults={}), _rows())
    descriptor = inventory.to_dict()
    valid_lines = build_compact_pack(_header(defaults={}), _rows()).content.splitlines(
        keepends=True
    )
    noncanonical = valid_lines[0] + (
        b'{"label": "Alpha", "id": "urn:ref:resource:a", "ring": "entity"}\n'
    )
    malformed_descriptor = _rewrite_pack(tmp_path, descriptor, noncanonical)
    malformed_descriptor["content"]["recordCount"] = 1  # type: ignore[index]
    with pytest.raises(CompactPackError, match="not canonical JSON"):
        read_compact_pack(tmp_path, malformed_descriptor)

    reversed_descriptor = _rewrite_pack(
        tmp_path,
        descriptor,
        valid_lines[0] + b"".join(reversed(valid_lines[1:])),
    )
    with pytest.raises(CompactPackError, match="out-of-order"):
        read_compact_pack(tmp_path, reversed_descriptor)


def test_compact_pack_descriptor_is_closed_and_target_is_immutable(tmp_path: Path) -> None:
    inventory = write_compact_pack(tmp_path, _header(), _rows())
    unknown = inventory.to_dict()
    unknown["surprise"] = True
    with pytest.raises(CompactPackError, match="unknown fields"):
        read_compact_pack(tmp_path, unknown)

    with pytest.raises(CompactPackError, match="refusing to replace"):
        write_compact_pack(
            tmp_path,
            _header(),
            [{"id": "urn:ref:resource:changed", "label": "changed"}],
        )
