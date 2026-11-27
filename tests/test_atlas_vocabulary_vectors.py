"""Focused tests for Tier-1 AtlasSemanticSidecar (flat_f16, ivf_i8, binary_i8) and DI integration."""

from __future__ import annotations

import concurrent.futures
import json
import math
import sqlite3
import struct
import threading
from pathlib import Path
from typing import Any

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from test_atlas_vocabulary_pack import R_EURO, R_FR, S_EURO, S_FR, _write_compact_fixture

from refspec.atlas import vocabulary_vectors as vv
from refspec.atlas.vocabulary_pack import AtlasVocabularyPack, build_vocabulary_pack
from refspec.atlas.vocabulary_protocols import (
    ExactPinnedRRF,
    SemanticIndex,
    VocabularyInputError,
    VocabularyPackError,
)
from refspec.atlas.vocabulary_vectors import (
    _POPCOUNT_LUT,
    SIDECAR_MAGIC,
    SIDECAR_SCHEMA_VERSION,
    AtlasSemanticSidecar,
    _hamming_distances_u8,
    build_semantic_sidecar,
    build_semantic_sidecar_from_arrays,
    calibrate_semantic_sidecar,
)


def _pack_rids(pack_path: Path) -> dict[str, int]:
    con = sqlite3.connect(str(pack_path))
    try:
        return dict(con.execute("SELECT id, rid FROM resources WHERE pref_label IS NOT NULL").fetchall())
    finally:
        con.close()


def test_flat_f16_sidecar_build_open_search_vector_for_rid_and_di_wiring(tmp_path: Path) -> None:
    view_root, digest = _write_compact_fixture(tmp_path / "view")
    pack_path = tmp_path / "vocab.sqlite"
    pman = build_vocabulary_pack(
        view_root,
        pack_path,
        trusted_manifest_digest=digest,
        schemes=(S_EURO, S_FR),
        languages=("en",),
    )
    rids = _pack_rids(pack_path)

    # 4 unique vectors (unnormalized to verify in-place normalization!); share one vector across BOTH Housing concepts
    vecs = np.asarray(
        [
            [3.0, 4.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],  # eurovoc computer crime -> [0.6, 0.8, 0, ...]
            [0.0, 2.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],  # fr medicare -> [0, 1, 0, ...]
            [0.0, 0.0, 5.0, 0.0, 0.0, 0.0, 0.0, 0.0],  # fr flood insurance -> [0, 0, 1, ...]
            [0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0],  # shared housing (EuroVoc + FR)
        ],
        dtype=np.float16,
    )
    rid_groups = [
        [rids["http://eurovoc.europa.eu/3027"]],
        [rids["urn:ref:fr:medicare"]],
        [rids["urn:ref:fr:flood-insurance"]],
        [rids["http://eurovoc.europa.eu/1234"], rids["urn:ref:fr:housing"]],
    ]

    vpath = tmp_path / "vocab.vpack"
    vman = build_semantic_sidecar_from_arrays(
        pack_path,
        vpath,
        vectors_f16=vecs,
        rids_per_vector=rid_groups,
        model_id="BAAI/bge-m3",
        mode="flat_f16",
    )
    assert vman.mode == "flat_f16"
    assert vman.pack_id == pman.pack_id
    assert vman.unique_vector_count == 4
    assert vman.mapped_resource_count == 5
    manifest_dict = vman.to_dict()
    assert manifest_dict["schemaVersion"] == SIDECAR_SCHEMA_VERSION == "2"
    assert manifest_dict["packId"] == pman.pack_id
    # In-place normalization updated vecs[0] directly without allocating a second full matrix.
    assert np.allclose(vecs[0].astype(np.float32), [0.6, 0.8, 0, 0, 0, 0, 0, 0], atol=1e-2)

    with AtlasSemanticSidecar.open(vpath, trusted_sidecar_digest=vman.sidecar_sha256) as sidecar:
        assert isinstance(sidecar, SemanticIndex)
        assert sidecar.pack_id == pman.pack_id
        assert sidecar.dimensions == 8

        # T2.1: O(1) vector_for_rid returns unit-normalized float32 vector for both single and shared rids!
        cc_vec = sidecar.vector_for_rid(rids["http://eurovoc.europa.eu/3027"])
        assert cc_vec is not None
        assert cc_vec.dtype == np.float32
        assert np.isclose(np.linalg.norm(cc_vec), 1.0, atol=1e-5)
        assert np.allclose(cc_vec, [0.6, 0.8, 0, 0, 0, 0, 0, 0], atol=1e-2)

        h1 = sidecar.vector_for_rid(rids["http://eurovoc.europa.eu/1234"])
        h2 = sidecar.vector_for_rid(rids["urn:ref:fr:housing"])
        assert h1 is not None and h2 is not None
        assert np.allclose(h1, h2)
        assert sidecar.vector_for_rid(-1) is None
        assert sidecar.vector_for_rid(0) is None
        assert sidecar.vector_for_rid(rids["http://eurovoc.europa.eu/9001"]) is None  # unindexed rid
        assert sidecar.vector_for_rid(999_999) is None

        # Multi-rid expansion returns both Housing resources at cosine 1.0
        housing_hits = sidecar.search_rids([0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0], top_k=5, min_cosine=0.8)
        assert {r for r, _ in housing_hits} == {
            rids["http://eurovoc.europa.eu/1234"],
            rids["urn:ref:fr:housing"],
        }
        assert all(score > 0.999 for _, score in housing_hits)

        # Calibrated cosine floor abstains cleanly on orthogonal vectors
        assert sidecar.search_rids([0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0], top_k=5, min_cosine=0.55) == []

        # Wrong query vector dimension -> VocabularyInputError (HTTP 400)
        with pytest.raises(VocabularyInputError, match="length 8"):
            sidecar.search_rids([1.0, 0.0, 0.0])

        # Full DI integration with AtlasVocabularyPack + ExactPinnedRRF + verify_pack_digest=False fast-open
        with AtlasVocabularyPack.open(
            pack_path,
            verify_pack_digest=False,
            semantic_index=sidecar,
            rank_fusion=ExactPinnedRRF(k=60.0, min_cosine=0.55),
        ) as pack:
            # Nonliteral Spanish query hits Medicare via query_vector
            es_hits = pack.lookup_sync(
                "seguro medico federal",
                limit=5,
                query_vector=[0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
            )
            assert es_hits[0]["id"] == "urn:ref:fr:medicare"

            # Exact-pinned control stays #1 even if dense vector points at Flood insurance!
            exact_hits = pack.lookup_sync(
                "computer crime",
                limit=5,
                query_vector=[0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0],
            )
            assert exact_hits[0]["id"] == "http://eurovoc.europa.eu/3027"
            assert any(h["id"] == "urn:ref:fr:flood-insurance" for h in exact_hits[1:])

            # Offline similar_sync uses vector_for_rid -> finds FR Housing counterpart for EuroVoc Housing!
            sim = pack.similar_sync(
                {"id": "http://eurovoc.europa.eu/1234", "scheme": S_EURO, "release": R_EURO},
                limit=5,
                min_cosine=0.8,
            )
            assert len(sim) == 1
            assert sim[0]["concept"]["id"] == "urn:ref:fr:housing"
            assert sim[0]["asserted"] is False
            assert sim[0]["semanticSimilarity"] > 0.999


def test_ivf_i8_sidecar_single_buffer_gather_vector_for_rid_and_pack_id_guards(tmp_path: Path) -> None:
    view_root, digest = _write_compact_fixture(tmp_path / "view")
    pack_path = tmp_path / "vocab.sqlite"
    pman = build_vocabulary_pack(
        view_root,
        pack_path,
        trusted_manifest_digest=digest,
        schemes=(S_EURO, S_FR),
        languages=("en",),
    )

    # Synthetic 1,024-vector unit-sphere corpus in 64D to exercise IVF clustering + single-buffer SGEMV + int8.
    rng = np.random.default_rng(123)
    raw = rng.normal(size=(1024, 64)).astype(np.float32)
    raw /= np.linalg.norm(raw, axis=1, keepdims=True)
    vecs_f16 = raw.astype(np.float16)
    rid_groups = [[i + 1] for i in range(1024)]

    vpath = tmp_path / "ivf.vpack"
    vman = build_semantic_sidecar_from_arrays(
        pack_path,
        vpath,
        vectors_f16=vecs_f16,
        rids_per_vector=rid_groups,
        model_id="BAAI/bge-m3",
        mode="ivf_i8",
        n_clusters=16,
        ivf_iterations=10,
        seed=42,
    )
    assert vman.mode == "ivf_i8"
    assert vman.n_clusters == 16
    assert vman.pack_id == pman.pack_id

    with AtlasSemanticSidecar.open(vpath, trusted_sidecar_digest=vman.sidecar_sha256) as sidecar:
        assert sidecar.pack_id == pman.pack_id
        # Exact self-retrieval across 20 random probes with nprobe=8 must hit exact top-1 with cosine > 0.99!
        for probe_idx in range(0, 200, 10):
            hits = sidecar.search_rids(raw[probe_idx], top_k=5, min_cosine=0.5, nprobe=8)
            assert hits, f"expected hit for probe {probe_idx}"
            top_rid, top_cos = hits[0]
            assert top_rid == probe_idx + 1
            assert top_cos > 0.99

            # T2.1: vector_for_rid works AFTER cluster sorting and reconstructs unit vector with cosine > 0.99!
            rec = sidecar.vector_for_rid(probe_idx + 1)
            assert rec is not None
            assert rec.dtype == np.float32
            assert np.isclose(np.linalg.norm(rec), 1.0, atol=1e-5)
            assert float(rec @ raw[probe_idx]) > 0.99

        assert sidecar.vector_for_rid(0) is None
        assert sidecar.vector_for_rid(1025) is None
        assert sidecar.search_rids(raw[0], top_k=0) == []

    # Digest mismatch on open -> VocabularyPackError
    with pytest.raises(VocabularyPackError, match="digest differs"):
        AtlasSemanticSidecar.open(vpath, trusted_sidecar_digest="sha256:" + "0" * 64)

    # Sidecar bound to a DIFFERENT SQLite pack must be refused by AtlasVocabularyPack.open (fast & full)!
    other_pack = tmp_path / "other.sqlite"
    build_vocabulary_pack(
        view_root,
        other_pack,
        trusted_manifest_digest=digest,
        schemes=(S_EURO,),  # different schemes -> different pack_id & pack_sha256!
        languages=("en",),
    )
    with (
        AtlasSemanticSidecar.open(vpath) as sidecar,
        pytest.raises(VocabularyPackError, match="pack identity does not match"),
    ):
        AtlasVocabularyPack.open(other_pack, verify_pack_digest=False, semantic_index=sidecar)

    with (
        AtlasSemanticSidecar.open(vpath) as sidecar,
        pytest.raises(VocabularyPackError, match="pack identity does not match"),
    ):
        AtlasVocabularyPack.open(other_pack, semantic_index=sidecar)

    # Confirm valid opening against matching pack works cleanly (both full digest & fast pack_id binding)
    with (
        AtlasSemanticSidecar.open(vpath) as sidecar,
        AtlasVocabularyPack.open(
            pack_path, trusted_pack_digest=pman.pack_sha256, semantic_index=sidecar
        ) as pack,
    ):
        assert pack.has_semantic_index is True
        assert pack.resolve_sync({"id": "http://eurovoc.europa.eu/3027", "scheme": S_EURO, "release": R_EURO})[
            "label"
        ] == "computer crime"
        assert pack.resolve_sync({"id": "urn:ref:fr:medicare", "scheme": S_FR, "release": R_FR})[
            "label"
        ] == "Medicare"


def test_binary_i8_sidecar_hamming_screen_int8_rerank_and_non_mult8_dim(tmp_path: Path) -> None:
    view_root, digest = _write_compact_fixture(tmp_path / "view")
    pack_path = tmp_path / "vocab.sqlite"
    pman = build_vocabulary_pack(
        view_root,
        pack_path,
        trusted_manifest_digest=digest,
        schemes=(S_EURO, S_FR),
        languages=("en",),
    )

    # Test with non-multiple-of-8 dimension (70D -> 9 packed bytes) to verify bit-padding safety!
    rng = np.random.default_rng(777)
    raw = rng.normal(size=(1024, 70)).astype(np.float32)
    raw /= np.linalg.norm(raw, axis=1, keepdims=True)
    vecs_f16 = raw.astype(np.float16)
    rid_groups = [[i + 1] for i in range(1024)]

    vpath = tmp_path / "bin.vpack"
    vman = build_semantic_sidecar_from_arrays(
        pack_path,
        vpath,
        vectors_f16=vecs_f16,
        rids_per_vector=rid_groups,
        model_id="BAAI/bge-m3",
        mode="binary_i8",
    )
    assert vman.mode == "binary_i8"
    assert vman.n_clusters == 0
    assert vman.pack_id == pman.pack_id
    assert vman.dimensions == 70

    with AtlasSemanticSidecar.open(vpath, trusted_sidecar_digest=vman.sidecar_sha256) as sidecar:
        assert isinstance(sidecar, SemanticIndex)
        assert sidecar.mode == "binary_i8"
        assert sidecar.pack_id == pman.pack_id

        # Self-retrieval across 20 probes with rerank_top_r=64 must hit exact top-1 with cosine > 0.99!
        for probe_idx in range(0, 200, 10):
            hits = sidecar.search_rids(raw[probe_idx], top_k=5, min_cosine=0.5, rerank_top_r=64)
            assert hits, f"expected binary_i8 hit for probe {probe_idx}"
            top_rid, top_cos = hits[0]
            assert top_rid == probe_idx + 1
            assert top_cos > 0.99

            # Verify O(1) vector_for_rid reconstruction matches original vector cleanly
            rec = sidecar.vector_for_rid(probe_idx + 1)
            assert rec is not None
            assert rec.dtype == np.float32
            assert np.isclose(np.linalg.norm(rec), 1.0, atol=1e-5)
            assert float(rec @ raw[probe_idx]) > 0.99

        # Also exercise rerank_top_r >= n_vecs full-rerank branch cleanly
        hits_full = sidecar.search_rids(raw[5], top_k=3, min_cosine=0.5, rerank_top_r=2048)
        assert hits_full[0][0] == 6
        assert hits_full[0][1] > 0.99

        assert sidecar.vector_for_rid(-5) is None
        assert sidecar.vector_for_rid(0) is None
        assert sidecar.vector_for_rid(2000) is None


def test_streaming_build_semantic_sidecar_from_parquet_and_schema_version_guard(tmp_path: Path) -> None:
    view_root, digest = _write_compact_fixture(tmp_path / "view")
    pack_path = tmp_path / "vocab.sqlite"
    pman = build_vocabulary_pack(
        view_root,
        pack_path,
        trusted_manifest_digest=digest,
        schemes=(S_EURO, S_FR),
        languages=("en",),
    )
    rids = _pack_rids(pack_path)

    # Create synthetic BGE-M3 Parquet embeddings directory (with shared input_sha256 for Housing + extra unmatched row)
    emb_dir = tmp_path / "embeddings"
    vecs_dir = emb_dir / "vectors"
    vecs_dir.mkdir(parents=True)

    res_table = pa.Table.from_pylist(
        [
            {"resource_id": "http://eurovoc.europa.eu/3027", "release": R_EURO, "scheme": S_EURO, "input_sha256": "sha_cc"},
            {"resource_id": "urn:ref:fr:medicare", "release": R_FR, "scheme": S_FR, "input_sha256": "sha_med"},
            {"resource_id": "http://eurovoc.europa.eu/1234", "release": R_EURO, "scheme": S_EURO, "input_sha256": "sha_house"},
            {"resource_id": "urn:ref:fr:housing", "release": R_FR, "scheme": S_FR, "input_sha256": "sha_house"},
            {"resource_id": "urn:ref:unmatched", "release": R_FR, "scheme": S_FR, "input_sha256": "sha_unused"},
        ]
    )
    pq.write_table(res_table, emb_dir / "resources.parquet")

    vec_table = pa.Table.from_pylist(
        [
            {"input_sha256": "sha_cc", "embedding": [2.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]},
            {"input_sha256": "sha_house", "embedding": [0.0, 0.0, 3.0, 0.0, 0.0, 0.0, 0.0, 0.0]},
            {"input_sha256": "sha_med", "embedding": [0.0, 4.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]},
            {"input_sha256": "sha_unused", "embedding": [0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0]},
        ]
    )
    pq.write_table(vec_table, vecs_dir / "part-00000.parquet")

    vpath = tmp_path / "streamed.vpack"
    vman = build_semantic_sidecar(
        pack_path,
        emb_dir,
        vpath,
        model_id="BAAI/bge-m3",
        mode="binary_i8",
    )
    assert vman.mode == "binary_i8"
    assert vman.pack_id == pman.pack_id
    assert vman.unique_vector_count == 3
    assert vman.mapped_resource_count == 4

    with (
        AtlasSemanticSidecar.open(vpath, trusted_sidecar_digest=vman.sidecar_sha256) as sidecar,
        AtlasVocabularyPack.open(pack_path, verify_pack_digest=False, semantic_index=sidecar) as pack,
    ):
        hits = sidecar.search_rids([0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0], top_k=5, min_cosine=0.8)
        assert {r for r, _ in hits} == {
            rids["http://eurovoc.europa.eu/1234"],
            rids["urn:ref:fr:housing"],
        }
        # End-to-end similar_sync over streamed binary_i8 sidecar!
        sim = pack.similar_sync(
            {"id": "urn:ref:fr:housing", "scheme": S_FR, "release": R_FR},
            limit=5,
            min_cosine=0.8,
        )
        assert [item["concept"]["id"] for item in sim] == ["http://eurovoc.europa.eu/1234"]

    # Reject legacy schemaVersion "1" sidecar cleanly
    v1_path = tmp_path / "legacy_v1.vpack"
    v1_header = json.dumps({"schemaVersion": "1", "mode": "flat_f16"}).encode("utf-8")
    v1_path.write_bytes(SIDECAR_MAGIC + struct.pack("<Q", len(v1_header)) + v1_header)
    with pytest.raises(VocabularyPackError, match="unsupported semantic sidecar schema version"):
        AtlasSemanticSidecar.open(v1_path)

    # Finding 8 & 12: truncated header, truncated section body, malformed JSON all raise VocabularyPackError,
    # close() is idempotent, and NaN/Inf query vectors return [] cleanly!
    raw_bytes = vpath.read_bytes()
    trunc_hdr = tmp_path / "truncated_hdr.vpack"
    trunc_hdr.write_bytes(raw_bytes[: len(raw_bytes) // 2])
    with pytest.raises(VocabularyPackError, match="truncated semantic sidecar header"):
        AtlasSemanticSidecar.open(trunc_hdr)

    trunc_body = tmp_path / "truncated_body.vpack"
    trunc_body.write_bytes(raw_bytes[:-4])
    with pytest.raises(VocabularyPackError, match="invalid semantic sidecar header/sections"):
        AtlasSemanticSidecar.open(trunc_body)

    bad_json_path = tmp_path / "bad_json.vpack"
    bad_json = b"{not-json"
    bad_json_path.write_bytes(SIDECAR_MAGIC + struct.pack("<Q", len(bad_json)) + bad_json)
    with pytest.raises(VocabularyPackError, match="malformed semantic sidecar JSON header"):
        AtlasSemanticSidecar.open(bad_json_path)

    sc = AtlasSemanticSidecar.open(vpath)
    assert sc.search_rids([float("nan")] * 8, top_k=5) == []
    assert sc.search_rids([float("inf")] * 8, top_k=5) == []
    sc.close()
    sc.close()  # idempotent close must not raise


def test_hamming_simd_bitwise_count_parity_and_strict_gt_zero_packing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify bit-for-bit Hamming parity across aligned/unaligned/non-mult-8 widths and strict (x > 0) packing."""
    rng = np.random.default_rng(2026)

    # 1. Bit-for-bit parity between _hamming_distances_u8 (SIMD bitwise_count) and _POPCOUNT_LUT reference
    #    across 64D (8B), 70D (9B non-mult-8), 100D (13B non-mult-8), 384D (48B), and 1024D (128B).
    for dim in (64, 70, 100, 384, 1024):
        n_bytes = (dim + 7) // 8
        mat = rng.integers(0, 256, size=(257, n_bytes), dtype=np.uint8)
        q_bits = rng.integers(0, 256, size=(n_bytes,), dtype=np.uint8)
        expected_u16 = _POPCOUNT_LUT[np.bitwise_xor(mat, q_bits)].sum(axis=1, dtype=np.uint16)
        expected_u32 = expected_u16.astype(np.uint32)

        got_u16 = _hamming_distances_u8(mat, q_bits, np.uint16)
        got_u32 = _hamming_distances_u8(mat, q_bits, np.uint32)
        assert got_u16.dtype == np.uint16
        assert got_u32.dtype == np.uint32
        assert np.array_equal(got_u16, expected_u16), f"u16 mismatch at dim={dim}"
        assert np.array_equal(got_u32, expected_u32), f"u32 mismatch at dim={dim}"

    # Unaligned 16B slice (addr % 4 != 0) and empty matrix must both match cleanly.
    raw_unaligned = rng.integers(0, 256, size=1 + 64 * 16, dtype=np.uint8)
    mat_unaligned = raw_unaligned[1:].reshape(64, 16)
    q_16 = rng.integers(0, 256, size=(16,), dtype=np.uint8)
    expected_unaligned = _POPCOUNT_LUT[np.bitwise_xor(mat_unaligned, q_16)].sum(axis=1, dtype=np.uint16)
    assert np.array_equal(_hamming_distances_u8(mat_unaligned, q_16, np.uint16), expected_unaligned)
    assert _hamming_distances_u8(np.empty((0, 16), dtype=np.uint8), q_16, np.uint16).shape == (0,)

    # NumPy < 2.0 LUT fallback path must match bit-for-bit when np.bitwise_count is absent.
    mat_128 = rng.integers(0, 256, size=(128, 128), dtype=np.uint8)
    q_128 = rng.integers(0, 256, size=(128,), dtype=np.uint8)
    simd_res = _hamming_distances_u8(mat_128, q_128, np.uint16)
    monkeypatch.delattr(np, "bitwise_count", raising=False)
    lut_fallback_res = _hamming_distances_u8(mat_128, q_128, np.uint16)
    assert np.array_equal(lut_fallback_res, simd_res)
    monkeypatch.undo()

    # 2. Strict (x > 0) bit-packing parity in BOTH builder and query (zeros pack as 0, matching fast-shared!)
    view_root, digest = _write_compact_fixture(tmp_path / "view")
    pack_path = tmp_path / "vocab.sqlite"
    build_vocabulary_pack(
        view_root,
        pack_path,
        trusted_manifest_digest=digest,
        schemes=(S_EURO, S_FR),
        languages=("en",),
    )

    for dim in (64, 70, 384, 1024):
        vecs = np.zeros((4, dim), dtype=np.float16)
        # Row 0: positive at [0], zero elsewhere -> ONLY bit 0 set under strict (x > 0)!
        vecs[0, 0] = np.float16(1.0)
        # Row 1: positive everywhere -> all `dim` bits set (trailing pad bits remain 0).
        vecs[1, :] = np.float16(1.0)
        # Row 2: negative at [0], positive at [1], zero elsewhere -> ONLY bit 1 set.
        vecs[2, 0] = np.float16(-1.0)
        vecs[2, 1] = np.float16(1.0)
        # Row 3: random signs
        vecs[3, :] = rng.normal(size=dim).astype(np.float16)

        # Compute expected bit-packing AFTER L2-normalization (normalization preserves sign & exact zeros).
        expected_packed = np.packbits(vecs.astype(np.float32) > 0, axis=-1)
        # Explicitly check strict > 0 on exact zeros: row 0 has ONLY MSB of byte 0 set (0x80), all other bytes 0!
        assert expected_packed[0, 0] == 0x80
        assert np.all(expected_packed[0, 1:] == 0)

        vpath = tmp_path / f"bin_{dim}.vpack"
        build_semantic_sidecar_from_arrays(
            pack_path,
            vpath,
            vectors_f16=vecs.copy(),
            rids_per_vector=[[1], [2], [3], [4]],
            model_id="BAAI/bge-m3",
            mode="binary_i8",
        )
        with AtlasSemanticSidecar.open(vpath) as sidecar:
            assert sidecar._binary_u8 is not None
            assert np.array_equal(sidecar._binary_u8, expected_packed), f"binary_u8 mismatch at dim={dim}"

            # Query with exact zeros at positions [1:] must match Row 0 at Hamming distance 0 (NOT Row 1!),
            # proving query packing also uses strict (q > 0) rather than (q >= 0)!
            q_zero_tail = np.zeros(dim, dtype=np.float32)
            q_zero_tail[0] = 1.0
            q_bits = np.packbits(q_zero_tail > 0)
            hams = _hamming_distances_u8(sidecar._binary_u8, q_bits, np.uint16)
            assert int(hams[0]) == 0
            assert int(hams[1]) == dim - 1
            # Query with exact zeros at positions [1:] matches Row 0 at Hamming distance 0 and cosine 1.0.
            hits = sidecar.search_rids(q_zero_tail, top_k=1, min_cosine=0.5, rerank_top_r=1)
            assert len(hits) == 1
            assert hits[0][0] == 1
            assert hits[0][1] > 0.99


def _make_minimal_pack(pack_path: Path, *, schema_version: str = "3", record_type: str = "AtlasVocabularyPack") -> Path:
    con = sqlite3.connect(str(pack_path))
    try:
        con.execute("CREATE TABLE pack_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        con.executemany(
            "INSERT INTO pack_meta (key, value) VALUES (?, ?)",
            [
                ("record_type", record_type),
                ("schema_version", schema_version),
                ("pack_id", "pack:unit-test-vpack"),
                ("source_manifest_digest", "sha256:" + "a" * 64),
                ("schemes_json", json.dumps([S_EURO, S_FR])),
            ],
        )
        con.commit()
    finally:
        con.close()
    return pack_path


def _read_vpack_header(vpack_path: Path) -> tuple[dict[str, Any], int, bytearray]:
    raw = bytearray(vpack_path.read_bytes())
    h_start = len(SIDECAR_MAGIC) + 8
    header_len = struct.unpack("<Q", raw[len(SIDECAR_MAGIC) : h_start])[0]
    header = json.loads(raw[h_start : h_start + header_len].decode("utf-8"))
    return header, h_start + header_len, raw


def _rewrite_vpack_with_header(out_path: Path, header: dict[str, Any], body_after_header: bytes) -> None:
    patched = json.loads(json.dumps(header))
    min_sec_off = min(sec["offset"] for sec in patched["sections"].values())
    hdr_bytes = json.dumps(patched, sort_keys=True, separators=(",", ":")).encode("utf-8")
    prefix_len = len(SIDECAR_MAGIC) + 8 + len(hdr_bytes)
    if prefix_len > min_sec_off:
        new_min = ((prefix_len + 63) // 64) * 64
        shift = new_min - min_sec_off
        for sec in patched["sections"].values():
            sec["offset"] += shift
        hdr_bytes = json.dumps(patched, sort_keys=True, separators=(",", ":")).encode("utf-8")
        prefix_len = len(SIDECAR_MAGIC) + 8 + len(hdr_bytes)
        min_sec_off = new_min
    pad = min_sec_off - prefix_len
    out_path.write_bytes(SIDECAR_MAGIC + struct.pack("<Q", len(hdr_bytes)) + hdr_bytes + b"\x00" * pad + body_after_header)


@pytest.mark.parametrize("mode", ["flat_f16", "binary_i8", "ivf_i8"])
def test_allowed_rids_sub_one_percent_selectivity_zero_starvation_all_modes(tmp_path: Path, mode: str) -> None:
    """Prove <1% selectivity allowed_rids yields 100% exact recall instead of 0-hit post-filter starvation."""
    pack_path = _make_minimal_pack(tmp_path / f"pack_{mode}.sqlite")
    rng = np.random.default_rng(101)
    n_total = 2_000
    dim = 64

    # Query lies along basis e_0.
    q = np.zeros(dim, dtype=np.float32)
    q[0] = 1.0

    # 1,990 disallowed decoys have cosine ~0.95..0.99 to q (completely saturating unfiltered top-40!).
    vecs = np.zeros((n_total, dim), dtype=np.float32)
    noise = rng.normal(size=(n_total, dim - 1)).astype(np.float32)
    noise /= np.linalg.norm(noise, axis=1, keepdims=True)
    for i in range(n_total):
        c = 0.96 + 0.03 * (i / n_total)
        vecs[i, 0] = c
        vecs[i, 1:] = np.sqrt(max(1e-6, 1.0 - c * c)) * noise[i]

    # 10 allowed targets (0.5% selectivity < 1%) scattered across indices with lower cosine (0.62..0.89).
    target_indices = [17, 143, 389, 612, 877, 1024, 1289, 1511, 1777, 1945]
    expected_cosines: dict[int, float] = {}
    for rank_idx, vidx in enumerate(target_indices):
        c = 0.62 + 0.03 * rank_idx  # 0.62 .. 0.89, strictly below all 1,990 decoys!
        vecs[vidx, 0] = c
        vecs[vidx, 1:] = np.sqrt(1.0 - c * c) * noise[vidx]
        expected_cosines[vidx + 1] = c  # rid = vidx + 1

    expected_order = [rid for rid, _ in sorted(expected_cosines.items(), key=lambda kv: -kv[1])]
    rids_per_vec = [[i + 1] for i in range(n_total)]

    vpath = tmp_path / f"starve_{mode}.vpack"
    build_semantic_sidecar_from_arrays(
        pack_path,
        vpath,
        vectors_f16=vecs.astype(np.float16),
        rids_per_vector=rids_per_vec,
        model_id="BAAI/bge-m3",
        mode=mode,  # type: ignore[arg-type]
        n_clusters=32,
        ivf_iterations=8,
        seed=42,
    )

    with AtlasSemanticSidecar.open(vpath) as sidecar:
        # 1. Confirm unfiltered top-40 contains ZERO target rids (proving post-filtering would starve to 0 hits!).
        unfiltered = sidecar.search_rids(q, top_k=40, min_cosine=0.55, nprobe=4)
        assert len(unfiltered) == 40
        assert not ({r for r, _ in unfiltered} & set(expected_order))

        # 2. Dense bytearray mask (using both 1 and 255 as non-zero truthy bytes) -> 100% exact recall!
        mask_ba = bytearray(n_total + 1)
        for idx, rid in enumerate(expected_order):
            mask_ba[rid] = 255 if idx % 2 == 0 else 1
        hits_ba = sidecar.search_rids(q, top_k=10, min_cosine=0.55, nprobe=1, allowed_rids=mask_ba)
        assert [r for r, _ in hits_ba] == expected_order
        for rid, score in hits_ba:
            assert abs(score - expected_cosines[rid]) < 0.02

        # 3. Immutable bytes mask (twice to exercise cache hit), memoryview, bool & uint8 ndarrays.
        mask_bytes = bytes(mask_ba)
        hits_b1 = sidecar.search_rids(q, top_k=10, min_cosine=0.55, nprobe=1, allowed_rids=mask_bytes)
        hits_b2 = sidecar.search_rids(q, top_k=10, min_cosine=0.55, nprobe=1, allowed_rids=mask_bytes)
        hits_mv = sidecar.search_rids(q, top_k=10, min_cosine=0.55, nprobe=1, allowed_rids=memoryview(mask_ba))
        hits_bool = sidecar.search_rids(
            q, top_k=10, min_cosine=0.55, nprobe=1, allowed_rids=np.frombuffer(mask_ba, dtype=np.uint8) != 0
        )
        hits_u8 = sidecar.search_rids(
            q, top_k=10, min_cosine=0.55, nprobe=1, allowed_rids=np.frombuffer(mask_ba, dtype=np.uint8)
        )
        for res in (hits_b1, hits_b2, hits_mv, hits_bool, hits_u8):
            assert [r for r, _ in res] == expected_order

        # 4. Explicit set, list, tuple, and int64 ndarray of rids -> identical 100% exact recall!
        for allowed in (
            set(expected_order),
            list(reversed(expected_order)),
            tuple(expected_order),
            np.asarray(expected_order, dtype=np.int64),
        ):
            hits_exp = sidecar.search_rids(q, top_k=10, min_cosine=0.55, nprobe=1, allowed_rids=allowed)
            assert [r for r, _ in hits_exp] == expected_order


@pytest.mark.parametrize("mode", ["flat_f16", "binary_i8", "ivf_i8"])
def test_allowed_rids_above_exact_threshold_premasked_paths(tmp_path: Path, mode: str) -> None:
    """Exercise pre-masked ANN/binary/flat paths (> 5,000 eligible vectors) at both mid and high selectivity."""
    pack_path = _make_minimal_pack(tmp_path / f"pack_big_{mode}.sqlite")
    rng = np.random.default_rng(202)
    # 6,400 vectors (dim=16): > 5,000 eligible exercises full pre-masked branch (>25% selectivity);
    # we also test <=25% selectivity via monkeypatching _EXACT_FILTER_THRESHOLD or larger pool below.
    n_total = 6_400
    dim = 16
    q = np.zeros(dim, dtype=np.float32)
    q[0] = 1.0

    vecs = rng.normal(size=(n_total, dim)).astype(np.float32)
    vecs[:, 0] = -np.abs(vecs[:, 0]) - 0.5  # push background away from q
    vecs /= np.linalg.norm(vecs, axis=1, keepdims=True)

    # First 1,200 vectors are disallowed decoys pointing almost identically along q (cosine ~0.999).
    vecs[:1_200, 0] = 0.999
    vecs[:1_200, 1:] *= 0.01
    vecs[:1_200] /= np.linalg.norm(vecs[:1_200], axis=1, keepdims=True)

    # Remaining 5,200 vectors (> 5,000!) are allowed; plant 5 strong matches inside them!
    planted_rids = [1_250, 2_500, 3_750, 5_000, 6_300]
    for idx, rid in enumerate(planted_rids):
        v = np.zeros(dim, dtype=np.float32)
        v[0] = 0.85 + 0.02 * idx
        v[1] = np.sqrt(1.0 - v[0] * v[0])
        vecs[rid - 1] = v

    vpath = tmp_path / f"premask_{mode}.vpack"
    build_semantic_sidecar_from_arrays(
        pack_path,
        vpath,
        vectors_f16=vecs.astype(np.float16),
        rids_per_vector=[[i + 1] for i in range(n_total)],
        model_id="BAAI/bge-m3",
        mode=mode,  # type: ignore[arg-type]
        n_clusters=32,
        ivf_iterations=8,
        seed=7,
    )

    allowed_mask = bytearray(n_total + 1)
    for rid in range(1_201, n_total + 1):
        allowed_mask[rid] = 1

    with AtlasSemanticSidecar.open(vpath) as sidecar:
        # Unfiltered top-20 is 100% disallowed decoys.
        unfiltered = sidecar.search_rids(q, top_k=20, min_cosine=0.55, nprobe=2)
        assert all(rid <= 1_200 for rid, _ in unfiltered)

        # Filtered (>5,000 eligible) recovers ALL 5 planted targets with zero disallowed leakage (even at nprobe=1!).
        hits = sidecar.search_rids(q, top_k=5, min_cosine=0.75, nprobe=1, allowed_rids=allowed_mask)
        assert [r for r, _ in hits] == list(reversed(planted_rids))
        assert all(r > 1_200 for r, _ in hits)

        # Also test mid-selectivity (5,000 < n_eligible <= n_vecs // 4) indexed-binary / sub-flat / IVF adaptive path.
        if mode in ("flat_f16", "binary_i8"):
            sub_mask = bytearray(n_total + 1)
            for rid in range(5_201, n_total + 1):  # 1,200 eligible (18.75% <= 25%)
                sub_mask[rid] = 1
            old_thresh = vv._EXACT_FILTER_THRESHOLD
            try:
                vv._EXACT_FILTER_THRESHOLD = 500
                sub_hits = sidecar.search_rids(q, top_k=5, min_cosine=0.75, allowed_rids=sub_mask)
                assert [r for r, _ in sub_hits] == [6_300]
            finally:
                vv._EXACT_FILTER_THRESHOLD = old_thresh


def test_allowed_rids_shared_vector_filtering_edges_and_thread_safety(tmp_path: Path) -> None:
    """Verify shared-vector rid filtering, empty/short/oversized masks, validation errors, and concurrent queries."""
    pack_path = _make_minimal_pack(tmp_path / "pack_shared.sqlite")
    vecs = np.asarray(
        [
            [1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],  # shared by rid=10 and rid=20
            [0.9, 0.435, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],  # rid=30
            [0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],  # rid=10 also appears here (multi-vidx-per-rid edge case!)
        ],
        dtype=np.float16,
    )
    vpath = tmp_path / "shared.vpack"
    build_semantic_sidecar_from_arrays(
        pack_path,
        vpath,
        vectors_f16=vecs,
        rids_per_vector=[[10, 20], [30], [10]],
        model_id="BAAI/bge-m3",
        mode="binary_i8",
    )

    q = [1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
    with AtlasSemanticSidecar.open(vpath) as sidecar:
        assert sidecar._unique_rid_per_vidx is False

        # Allowing ONLY rid=20 must NOT leak rid=10 from the shared vector!
        mask_20 = bytearray(31)
        mask_20[20] = 1
        hits_ba = sidecar.search_rids(q, top_k=5, min_cosine=0.5, allowed_rids=mask_20)
        assert [r for r, _ in hits_ba] == [20]

        hits_set = sidecar.search_rids(q, top_k=5, min_cosine=0.5, allowed_rids={20})
        assert [r for r, _ in hits_set] == [20]

        # Multi-vidx-per-rid: allowing rid=10 with query along e_1 finds vidx=2 (cosine ~1.0)!
        hits_e1 = sidecar.search_rids([0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0], top_k=5, min_cosine=0.8, allowed_rids={10})
        assert [r for r, _ in hits_e1] == [10]
        assert hits_e1[0][1] > 0.99

        # Empty, short, oversized, and out-of-range filters behave safely.
        assert sidecar.search_rids(q, top_k=5, allowed_rids=bytearray()) == []
        assert sidecar.search_rids(q, top_k=5, allowed_rids=bytes(31)) == []
        assert sidecar.search_rids(q, top_k=5, allowed_rids=[]) == []
        assert sidecar.search_rids(q, top_k=5, allowed_rids=set()) == []
        assert sidecar.search_rids(q, top_k=5, allowed_rids=[0, -5, 999_999]) == []
        short_mask = bytearray(11)
        short_mask[10] = 1
        assert [r for r, _ in sidecar.search_rids(q, top_k=5, min_cosine=0.5, allowed_rids=short_mask)] == [10]
        oversized_mask = bytearray(500)
        oversized_mask[30] = 1
        oversized_mask[450] = 1
        assert [r for r, _ in sidecar.search_rids(q, top_k=5, min_cosine=0.5, allowed_rids=oversized_mask)] == [30]

        # Invalid allowed_rids inputs raise VocabularyInputError cleanly.
        for bad in (
            "10",
            {10: True},
            [True],
            ["10"],
            np.asarray([1.0, 2.0], dtype=np.float32),
            np.ones((2, 2), dtype=np.uint8),
            memoryview(np.ones((2, 2), dtype=np.uint8)),
        ):
            with pytest.raises(VocabularyInputError):
                sidecar.search_rids(q, top_k=5, allowed_rids=bad)

        # 8-thread concurrent search smoke test (unfiltered + bytes cached + bytearray + set).
        mask_bytes = bytes(mask_20)

        def _worker(tid: int) -> list[int]:
            if tid % 3 == 0:
                return [r for r, _ in sidecar.search_rids(q, top_k=5, min_cosine=0.5, allowed_rids=mask_bytes)]
            if tid % 3 == 1:
                return [r for r, _ in sidecar.search_rids(q, top_k=5, min_cosine=0.5, allowed_rids=mask_20)]
            return [r for r, _ in sidecar.search_rids(q, top_k=5, min_cosine=0.5, allowed_rids={20})]

        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(_worker, range(32)))
        assert all(r == [20] for r in results)

    # Closed sidecar refuses subsequent queries cleanly with VocabularyPackError.
    with pytest.raises(VocabularyPackError, match="closed"):
        sidecar.search_rids(q, top_k=5)
    with pytest.raises(VocabularyPackError, match="closed"):
        sidecar.vector_for_rid(10)


def test_corrupt_bounds_and_symlink_fail_closed_on_open_and_build(tmp_path: Path) -> None:
    """Verify corrupted rid_offsets, rid_to_vidx, rids, cluster_offsets, pack_meta, and symlinks fail closed."""
    pack_path = _make_minimal_pack(tmp_path / "pack.sqlite")
    rng = np.random.default_rng(55)
    vecs = rng.normal(size=(128, 16)).astype(np.float16)
    rids = [[i + 1] for i in range(128)]

    vpack_ivf = tmp_path / "valid_ivf.vpack"
    build_semantic_sidecar_from_arrays(
        pack_path,
        vpack_ivf,
        vectors_f16=vecs.copy(),
        rids_per_vector=rids,
        model_id="BAAI/bge-m3",
        mode="ivf_i8",
        n_clusters=4,
        ivf_iterations=6,
    )
    hdr, _, base_bytes = _read_vpack_header(vpack_ivf)

    def _patch_u32(name: str, index: int, value: int, label: str) -> Path:
        patched = bytearray(base_bytes)
        off = hdr["sections"][name]["offset"] + index * 4
        struct.pack_into("<I", patched, off, value)
        out = tmp_path / f"corrupt_{label}.vpack"
        out.write_bytes(patched)
        return out

    # 1. rid_offsets[0] != 0
    with pytest.raises(VocabularyPackError, match="rid_offsets\\[0\\]"):
        AtlasSemanticSidecar.open(_patch_u32("rid_offsets_u32", 0, 1, "rid_off_start"))

    # 2. Non-monotonic rid_offsets (rid_offsets[2] < rid_offsets[1])
    with pytest.raises(VocabularyPackError, match="monotonically non-decreasing"):
        AtlasSemanticSidecar.open(_patch_u32("rid_offsets_u32", 2, 0, "rid_off_nonmono"))

    # 3. rid_offsets[-1] > mappedResourceCount (out-of-bounds)
    with pytest.raises(VocabularyPackError, match="exceeds mappedResourceCount"):
        AtlasSemanticSidecar.open(_patch_u32("rid_offsets_u32", 128, 999, "rid_off_oob"))

    # 4. rids entry > maxRid
    with pytest.raises(VocabularyPackError, match="exceeding maxRid"):
        AtlasSemanticSidecar.open(_patch_u32("rids_u32", 0, 999, "rids_gt_maxrid"))

    # 5. rid_to_vidx out-of-range vector index (== n_vecs, NOT _MISSING_VIDX)
    with pytest.raises(VocabularyPackError, match="rid_to_vidx contains out-of-range"):
        AtlasSemanticSidecar.open(_patch_u32("rid_to_vidx_u32", 1, 128, "rid_to_vidx_oob"))

    # 6. cluster_offsets[0] != 0
    with pytest.raises(VocabularyPackError, match="cluster_offsets\\[0\\]"):
        AtlasSemanticSidecar.open(_patch_u32("cluster_offsets_u32", 0, 1, "cluster_off_start"))

    # 7. Non-monotonic cluster_offsets
    patched_cm = bytearray(base_bytes)
    c_off = hdr["sections"]["cluster_offsets_u32"]["offset"]
    struct.pack_into("<II", patched_cm, c_off + 4, 20, 10)
    cm_path = tmp_path / "corrupt_cluster_nonmono.vpack"
    cm_path.write_bytes(patched_cm)
    with pytest.raises(VocabularyPackError, match="cluster_offsets is not monotonically"):
        AtlasSemanticSidecar.open(cm_path)

    # 8. cluster_offsets[-1] != uniqueVectorCount (both under and over)
    with pytest.raises(VocabularyPackError, match="must equal uniqueVectorCount"):
        AtlasSemanticSidecar.open(_patch_u32("cluster_offsets_u32", 4, 120, "cluster_off_short"))
    with pytest.raises(VocabularyPackError, match="must equal uniqueVectorCount"):
        AtlasSemanticSidecar.open(_patch_u32("cluster_offsets_u32", 4, 200, "cluster_off_long"))

    # 9. Header section nbytes mismatch (wrong rid_offsets byte length)
    bad_hdr = json.loads(json.dumps(hdr))
    bad_hdr["sections"]["rid_offsets_u32"]["nbytes"] += 4
    min_sec = min(s["offset"] for s in hdr["sections"].values())
    bad_hdr_path = tmp_path / "corrupt_nbytes.vpack"
    _rewrite_vpack_with_header(bad_hdr_path, bad_hdr, bytes(base_bytes[min_sec:]))
    with pytest.raises(VocabularyPackError, match="bounds invalid"):
        AtlasSemanticSidecar.open(bad_hdr_path)

    # 10. Symlinked .vpack (both valid target and broken symlink) fail closed BEFORE .resolve()
    link_vpack = tmp_path / "link.vpack"
    link_vpack.symlink_to(vpack_ivf)
    with pytest.raises(VocabularyPackError, match="must not be a symlink"):
        AtlasSemanticSidecar.open(link_vpack)

    broken_link = tmp_path / "broken.vpack"
    broken_link.symlink_to(tmp_path / "does_not_exist.vpack")
    with pytest.raises(VocabularyPackError, match="must not be a symlink"):
        AtlasSemanticSidecar.open(broken_link)

    # 11. Symlinked pack_path / output_path rejected in build_semantic_sidecar_from_arrays
    link_pack = tmp_path / "link_pack.sqlite"
    link_pack.symlink_to(pack_path)
    with pytest.raises(VocabularyPackError, match="must not be a symlink"):
        build_semantic_sidecar_from_arrays(
            link_pack, tmp_path / "out1.vpack", vectors_f16=vecs[:4].copy(), rids_per_vector=[[1], [2], [3], [4]], model_id="m"
        )
    with pytest.raises(VocabularyPackError, match="must not be a symlink"):
        build_semantic_sidecar_from_arrays(
            pack_path, link_vpack, vectors_f16=vecs[:4].copy(), rids_per_vector=[[1], [2], [3], [4]], model_id="m"
        )

    # 12. Symlinked embeddings_dir / resources.parquet / vectors part rejected in build_semantic_sidecar
    emb_dir = tmp_path / "emb_real"
    (emb_dir / "vectors").mkdir(parents=True)
    pq.write_table(
        pa.Table.from_pylist([{"resource_id": "x", "release": "r", "scheme": S_EURO, "input_sha256": "s"}]),
        emb_dir / "resources.parquet",
    )
    pq.write_table(
        pa.Table.from_pylist([{"input_sha256": "s", "embedding": [1.0, 0.0, 0.0, 0.0]}]),
        emb_dir / "vectors" / "part-00000.parquet",
    )
    link_emb = tmp_path / "emb_link"
    link_emb.symlink_to(emb_dir)
    with pytest.raises(VocabularyPackError, match="must not be a symlink"):
        build_semantic_sidecar(pack_path, link_emb, tmp_path / "out_emb.vpack")

    emb_bad_part = tmp_path / "emb_bad_part"
    (emb_bad_part / "vectors").mkdir(parents=True)
    (emb_bad_part / "resources.parquet").write_bytes((emb_dir / "resources.parquet").read_bytes())
    (emb_bad_part / "vectors" / "part-00000.parquet").symlink_to(emb_dir / "vectors" / "part-00000.parquet")
    with pytest.raises(VocabularyPackError, match="unsafe vector parquet part"):
        build_semantic_sidecar(pack_path, emb_bad_part, tmp_path / "out_emb2.vpack")

    # 13. Unsupported pack schema_version / record_type rejected cleanly
    bad_schema_pack = _make_minimal_pack(tmp_path / "bad_schema.sqlite", schema_version="99")
    with pytest.raises(VocabularyPackError, match="expected AtlasVocabularyPack schema version"):
        build_semantic_sidecar_from_arrays(
            bad_schema_pack, tmp_path / "out_bad.vpack", vectors_f16=vecs[:4].copy(), rids_per_vector=[[1], [2], [3], [4]], model_id="m"
        )
    bad_type_pack = _make_minimal_pack(tmp_path / "bad_type.sqlite", record_type="OtherPack")
    with pytest.raises(VocabularyPackError, match="expected AtlasVocabularyPack schema version"):
        build_semantic_sidecar(bad_type_pack, emb_dir, tmp_path / "out_bad2.vpack")


def test_binary_i8_rerank_top_r_decoupling_and_auto_mode_threshold(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify binary_i8 decouples r_eff >= 2 * k_eff (rescuing Hamming rank > top_k) and mode='auto' routes >50K to binary_i8."""
    pack_path = _make_minimal_pack(tmp_path / "pack_auto.sqlite")

    # Part 1: Behavioral proof of rerank_top_r decoupling on binary_i8 (top_k=64 screens >=128 candidates).
    dim = 64
    n_vecs = 512
    q = np.full(dim, 0.01, dtype=np.float32)
    q[:4] = 10.0
    q /= np.linalg.norm(q)

    vecs = np.empty((n_vecs, dim), dtype=np.float32)
    # Rows 0..79 (80 decoys): ALL 64 dims strictly positive -> Hamming distance 0 to q, moderate cosine (~0.70).
    decoy = np.full(dim, 0.16, dtype=np.float32)
    decoy[:4] = 0.65
    decoy /= np.linalg.norm(decoy)
    vecs[:80] = decoy

    # Row 80 (target, rid=81): flips 16 tiny tail dims negative -> Hamming distance 16 (Hamming rank #81,
    # strictly past top_k=64 and strictly inside 2*top_k=128!), while true cosine to q is > 0.999!
    target = np.full(dim, 0.01, dtype=np.float32)
    target[:4] = 10.0
    target[4:20] = -0.01
    target /= np.linalg.norm(target)
    vecs[80] = target

    # Rows 81..511: opposite signs on >= 32 dims -> Hamming distance >= 32 (strictly behind target).
    bg = np.full(dim, -1.0, dtype=np.float32)
    bg[:4] = 0.1
    bg /= np.linalg.norm(bg)
    vecs[81:] = bg

    vpath = tmp_path / "decouple.vpack"
    build_semantic_sidecar_from_arrays(
        pack_path,
        vpath,
        vectors_f16=vecs.astype(np.float16),
        rids_per_vector=[[i + 1] for i in range(n_vecs)],
        model_id="BAAI/bge-m3",
        mode="binary_i8",
    )

    # Open with default rerank_top_r=64 so WITHOUT decoupling (k_eff*2), top_k=64 would only scan 64 Hamming-0 decoys
    # and miss target rid=81 at Hamming rank #81!
    with AtlasSemanticSidecar.open(vpath, rerank_top_r=64) as sidecar:
        assert sidecar._effective_rerank_top_r(64, n_vecs, None) == 128
        assert sidecar._effective_rerank_top_r(64, n_vecs, 64) == 128
        assert sidecar._effective_rerank_top_r(512, 100_000, None) == 1024
        assert sidecar._effective_rerank_top_r(512, 100_000, 2048) == 2048

        # Both omitted rerank_top_r and explicit rerank_top_r=64 screen >= 128 candidates and rescue rid=81 to #1!
        hits_default = sidecar.search_rids(q, top_k=64, min_cosine=0.5)
        assert hits_default[0][0] == 81
        assert hits_default[0][1] > 0.99

        hits_explicit = sidecar.search_rids(q, top_k=64, min_cosine=0.5, rerank_top_r=64)
        assert hits_explicit[0][0] == 81
        assert hits_explicit[0][1] > 0.99

        with pytest.raises(VocabularyInputError, match="positive integer"):
            sidecar.search_rids(q, top_k=5, rerank_top_r=0)
        with pytest.raises(VocabularyInputError, match="positive integer"):
            sidecar.search_rids(q, top_k=5, rerank_top_r=True)  # type: ignore[arg-type]

    # Part 2: mode="auto" routes N <= 50,000 -> flat_f16 and N > 50,000 -> binary_i8 (exact real boundary!).
    n_le = 50_000
    v_le = np.ones((n_le, 2), dtype=np.float16)
    man_le = build_semantic_sidecar_from_arrays(
        pack_path,
        tmp_path / "auto_50k.vpack",
        vectors_f16=v_le,
        rids_per_vector=[[i + 1] for i in range(n_le)],
        model_id="BAAI/bge-m3",
        mode="auto",
    )
    assert man_le.mode == "flat_f16"

    n_gt = 50_001
    v_gt = np.ones((n_gt, 2), dtype=np.float16)
    man_gt = build_semantic_sidecar_from_arrays(
        pack_path,
        tmp_path / "auto_50k_plus_1.vpack",
        vectors_f16=v_gt,
        rids_per_vector=[[i + 1] for i in range(n_gt)],
        model_id="BAAI/bge-m3",
        mode="auto",
    )
    assert man_gt.mode == "binary_i8"
    with AtlasSemanticSidecar.open(tmp_path / "auto_50k_plus_1.vpack") as sc_gt:
        assert sc_gt.mode == "binary_i8"
        assert sc_gt.unique_vector_count == 50_001

    # Also verify streaming build_semantic_sidecar routes mode="auto" above threshold directly into binary_i8!
    view_root, digest = _write_compact_fixture(tmp_path / "view_auto")
    real_pack = tmp_path / "real_auto.sqlite"
    build_vocabulary_pack(
        view_root,
        real_pack,
        trusted_manifest_digest=digest,
        schemes=(S_EURO, S_FR),
        languages=("en",),
    )
    emb_dir = tmp_path / "emb_auto"
    (emb_dir / "vectors").mkdir(parents=True)
    pq.write_table(
        pa.Table.from_pylist(
            [
                {"resource_id": "http://eurovoc.europa.eu/3027", "release": R_EURO, "scheme": S_EURO, "input_sha256": "s1"},
                {"resource_id": "urn:ref:fr:medicare", "release": R_FR, "scheme": S_FR, "input_sha256": "s2"},
                {"resource_id": "urn:ref:fr:housing", "release": R_FR, "scheme": S_FR, "input_sha256": "s3"},
            ]
        ),
        emb_dir / "resources.parquet",
    )
    pq.write_table(
        pa.Table.from_pylist(
            [
                {"input_sha256": "s1", "embedding": [1.0, 0.0, 0.0, 0.0]},
                {"input_sha256": "s2", "embedding": [0.0, 1.0, 0.0, 0.0]},
                {"input_sha256": "s3", "embedding": [0.0, 0.0, 1.0, 0.0]},
            ]
        ),
        emb_dir / "vectors" / "part-00000.parquet",
    )
    monkeypatch.setattr(vv, "_FLAT_THRESHOLD", 2)
    stream_man = build_semantic_sidecar(
        real_pack,
        emb_dir,
        tmp_path / "stream_auto.vpack",
        mode="auto",
        recommended_min_cosine=0.61,
    )
    assert stream_man.mode == "binary_i8"
    assert stream_man.recommended_min_cosine == pytest.approx(0.61)
    with AtlasSemanticSidecar.open(tmp_path / "stream_auto.vpack") as sc_stream:
        assert sc_stream.mode == "binary_i8"
        assert sc_stream.recommended_min_cosine == pytest.approx(0.61)


def test_recommended_min_cosine_roundtrip_and_backward_compatibility(tmp_path: Path) -> None:
    """Verify recommended_min_cosine round-trips cleanly and stays backward-compatible when omitted."""
    pack_path = _make_minimal_pack(tmp_path / "pack_rec.sqlite")
    vecs = np.eye(4, dtype=np.float16)
    rids = [[1], [2], [3], [4]]

    # 1. Explicit recommended_min_cosine round-trips in manifest, header JSON, and opened sidecar.
    v_with = tmp_path / "with_rec.vpack"
    man_with = build_semantic_sidecar_from_arrays(
        pack_path,
        v_with,
        vectors_f16=vecs.copy(),
        rids_per_vector=rids,
        model_id="BAAI/bge-m3",
        mode="flat_f16",
        recommended_min_cosine=0.625,
    )
    assert man_with.recommended_min_cosine == pytest.approx(0.625)
    assert man_with.to_dict()["recommendedMinCosine"] == pytest.approx(0.625)
    hdr_with, _, _ = _read_vpack_header(v_with)
    assert hdr_with["recommendedMinCosine"] == pytest.approx(0.625)
    with AtlasSemanticSidecar.open(v_with) as sc_with:
        assert sc_with.recommended_min_cosine == pytest.approx(0.625)

    # 2. Omitted recommended_min_cosine -> None and absent from header (backward-compatible with existing .vpack).
    v_without = tmp_path / "without_rec.vpack"
    man_without = build_semantic_sidecar_from_arrays(
        pack_path,
        v_without,
        vectors_f16=vecs.copy(),
        rids_per_vector=rids,
        model_id="BAAI/bge-m3",
        mode="flat_f16",
    )
    assert man_without.recommended_min_cosine is None
    assert man_without.to_dict()["recommendedMinCosine"] is None
    hdr_without, _, raw_without = _read_vpack_header(v_without)
    assert "recommendedMinCosine" not in hdr_without
    with AtlasSemanticSidecar.open(v_without) as sc_without:
        assert sc_without.recommended_min_cosine is None

    # 3. Invalid recommended_min_cosine rejected on build (VocabularyInputError) and corrupt header (VocabularyPackError).
    for bad_val in (float("nan"), float("inf"), 1.01, -1.01, True, "0.6"):
        with pytest.raises(VocabularyInputError, match="recommended_min_cosine"):
            build_semantic_sidecar_from_arrays(
                pack_path,
                tmp_path / "bad_rec.vpack",
                vectors_f16=vecs.copy(),
                rids_per_vector=rids,
                model_id="BAAI/bge-m3",
                recommended_min_cosine=bad_val,  # type: ignore[arg-type]
            )

    min_sec = min(s["offset"] for s in hdr_without["sections"].values())
    for idx, corrupt_val in enumerate((2.5, "bad", True)):
        bad_hdr = json.loads(json.dumps(hdr_without))
        bad_hdr["recommendedMinCosine"] = corrupt_val
        corrupt_rec = tmp_path / f"corrupt_rec_{idx}.vpack"
        _rewrite_vpack_with_header(corrupt_rec, bad_hdr, bytes(raw_without[min_sec:]))
        with pytest.raises(VocabularyPackError, match="recommendedMinCosine"):
            AtlasSemanticSidecar.open(corrupt_rec)


def test_parent_symlink_refusal_and_single_fd_toctou_free_open(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """F5.1 & F5.2: Reject symlinked parent directories on open/build and hash open mmap without path reopen."""
    real_dir = tmp_path / "real_dir"
    real_dir.mkdir()
    pack_path = _make_minimal_pack(real_dir / "pack.sqlite")
    vecs = np.eye(4, dtype=np.float16)
    rids = [[1], [2], [3], [4]]
    vpath = real_dir / "sidecar.vpack"
    vman = build_semantic_sidecar_from_arrays(
        pack_path,
        vpath,
        vectors_f16=vecs.copy(),
        rids_per_vector=rids,
        model_id="BAAI/bge-m3",
        mode="flat_f16",
    )

    emb_dir = real_dir / "embeddings"
    (emb_dir / "vectors").mkdir(parents=True)
    pq.write_table(
        pa.Table.from_pylist([{"resource_id": "x", "release": "r", "scheme": S_EURO, "input_sha256": "s"}]),
        emb_dir / "resources.parquet",
    )
    pq.write_table(
        pa.Table.from_pylist([{"input_sha256": "s", "embedding": [1.0, 0.0, 0.0, 0.0]}]),
        emb_dir / "vectors" / "part-00000.parquet",
    )

    symlink_dir = tmp_path / "symlink_dir"
    symlink_dir.symlink_to(real_dir)

    # F5.1: <symlink_dir>/sidecar.vpack rejected on open (both absolute and relative paths).
    with pytest.raises(VocabularyPackError, match="symlinked parent directory") as exc_open:
        AtlasSemanticSidecar.open(symlink_dir / "sidecar.vpack")
    assert exc_open.value.code == "invalid_sidecar"

    monkeypatch.chdir(tmp_path)
    with pytest.raises(VocabularyPackError, match="symlinked parent directory"):
        AtlasSemanticSidecar.open(Path("symlink_dir") / "sidecar.vpack")

    # F5.1: <symlink_dir> rejected for pack_path and output_path (direct & nested) on build_semantic_sidecar_from_arrays.
    with pytest.raises(VocabularyPackError, match="symlinked parent directory") as exc_pack:
        build_semantic_sidecar_from_arrays(
            symlink_dir / "pack.sqlite",
            tmp_path / "out_a.vpack",
            vectors_f16=vecs.copy(),
            rids_per_vector=rids,
            model_id="BAAI/bge-m3",
        )
    assert exc_pack.value.code == "invalid_pack"

    for bad_out in (symlink_dir / "out_b.vpack", symlink_dir / "nested_new" / "out_c.vpack"):
        with pytest.raises(VocabularyPackError, match="symlinked parent directory") as exc_out:
            build_semantic_sidecar_from_arrays(
                pack_path,
                bad_out,
                vectors_f16=vecs.copy(),
                rids_per_vector=rids,
                model_id="BAAI/bge-m3",
            )
        assert exc_out.value.code == "invalid_sidecar"

    # F5.1: <symlink_dir> rejected for pack_path, embeddings_dir, and output_path on build_semantic_sidecar.
    with pytest.raises(VocabularyPackError, match="symlinked parent directory"):
        build_semantic_sidecar(symlink_dir / "pack.sqlite", emb_dir, tmp_path / "out_s1.vpack")
    with pytest.raises(VocabularyPackError, match="symlinked parent directory"):
        build_semantic_sidecar(pack_path, symlink_dir / "embeddings", tmp_path / "out_s2.vpack")
    with pytest.raises(VocabularyPackError, match="symlinked parent directory"):
        build_semantic_sidecar(pack_path, emb_dir, symlink_dir / "out_s3.vpack")

    # F5.2: AtlasSemanticSidecar.open() verifies digest from the open mmap (NEVER reopens via _sha256_file)
    # and rejects non-regular files (directories) via fstat S_ISREG.
    def _forbid_path_reopen(_path: Path) -> str:
        raise AssertionError("open() must not reopen path via _sha256_file")

    monkeypatch.setattr(vv, "_sha256_file", _forbid_path_reopen)
    with AtlasSemanticSidecar.open(vpath, trusted_sidecar_digest=vman.sidecar_sha256) as sidecar:
        assert sidecar.dimensions == 4
    with pytest.raises(VocabularyPackError, match="digest differs") as exc_dig:
        AtlasSemanticSidecar.open(vpath, trusted_sidecar_digest="sha256:" + "f" * 64)
    assert exc_dig.value.code == "invalid_digest"

    with pytest.raises(VocabularyPackError, match="not a regular file") as exc_dir:
        AtlasSemanticSidecar.open(real_dir)
    assert exc_dir.value.code == "invalid_sidecar"

    empty_vpack = tmp_path / "empty.vpack"
    empty_vpack.write_bytes(b"")
    with pytest.raises(VocabularyPackError, match="digest differs") as exc_empty_dig:
        AtlasSemanticSidecar.open(empty_vpack, trusted_sidecar_digest=vman.sidecar_sha256)
    assert exc_empty_dig.value.code == "invalid_digest"
    with pytest.raises(VocabularyPackError, match="empty") as exc_empty:
        AtlasSemanticSidecar.open(empty_vpack)
    assert exc_empty.value.code == "corrupt_sidecar"


def test_strict_vpack_header_validation_guards(tmp_path: Path) -> None:
    """F5.3: Enforce header_len <= 16 MiB, recordType, strict string fields, and section offset >= h_end."""
    pack_path = _make_minimal_pack(tmp_path / "pack_hdr.sqlite")
    vecs = np.eye(4, dtype=np.float16)
    rids = [[1], [2], [3], [4]]
    vpath = tmp_path / "valid.vpack"
    build_semantic_sidecar_from_arrays(
        pack_path,
        vpath,
        vectors_f16=vecs.copy(),
        rids_per_vector=rids,
        model_id="BAAI/bge-m3",
        mode="flat_f16",
    )
    base_hdr, base_h_end, base_raw = _read_vpack_header(vpath)
    min_sec = min(s["offset"] for s in base_hdr["sections"].values())
    body = bytes(base_raw[min_sec:])

    # 1. header_len > 16 MiB and header_len == 0 fail before JSON decode.
    oversized_path = tmp_path / "oversized_hdr_len.vpack"
    oversized_path.write_bytes(SIDECAR_MAGIC + struct.pack("<Q", vv._MAX_SIDECAR_HEADER_BYTES + 1) + b"{}")
    with pytest.raises(VocabularyPackError, match="exceeds maximum") as exc_big:
        AtlasSemanticSidecar.open(oversized_path)
    assert exc_big.value.code == "corrupt_sidecar"

    zero_hdr_path = tmp_path / "zero_hdr_len.vpack"
    zero_hdr_path.write_bytes(SIDECAR_MAGIC + struct.pack("<Q", 0) + b"{}")
    with pytest.raises(VocabularyPackError, match="must be positive") as exc_zero:
        AtlasSemanticSidecar.open(zero_hdr_path)
    assert exc_zero.value.code == "corrupt_sidecar"

    # 2. Bad or missing recordType fails closed.
    for idx, bad_rt in enumerate(("OtherRecord", None, 123)):
        hdr = json.loads(json.dumps(base_hdr))
        hdr["recordType"] = bad_rt
        p = tmp_path / f"bad_rt_{idx}.vpack"
        _rewrite_vpack_with_header(p, hdr, body)
        with pytest.raises(VocabularyPackError, match="recordType") as exc_rt:
            AtlasSemanticSidecar.open(p)
        assert exc_rt.value.code == "corrupt_sidecar"

    hdr_missing_rt = json.loads(json.dumps(base_hdr))
    del hdr_missing_rt["recordType"]
    p_missing_rt = tmp_path / "missing_rt.vpack"
    _rewrite_vpack_with_header(p_missing_rt, hdr_missing_rt, body)
    with pytest.raises(VocabularyPackError, match="recordType"):
        AtlasSemanticSidecar.open(p_missing_rt)

    # 3. Non-string / null required string metadata fields fail closed (never coerce None -> "None").
    for field, bad_val in (
        ("packId", None),
        ("packId", 42),
        ("packSha256", None),
        ("packSha256", ""),
        ("sourceManifestDigest", None),
        ("sourceManifestDigest", 99),
        ("modelId", None),
        ("modelId", ""),
        ("mode", None),
        ("mode", 123),
    ):
        hdr = json.loads(json.dumps(base_hdr))
        hdr[field] = bad_val
        p = tmp_path / f"bad_{field}_{type(bad_val).__name__}.vpack"
        _rewrite_vpack_with_header(p, hdr, body)
        with pytest.raises(VocabularyPackError, match="invalid semantic sidecar header/sections") as exc_f:
            AtlasSemanticSidecar.open(p)
        assert exc_f.value.code == "corrupt_sidecar"

    # 4. Section offset < h_end (header byte aliasing) fails closed.
    for label, alias_offset in (("zero", 0), ("overlap_header", base_h_end - 8)):
        hdr = json.loads(json.dumps(base_hdr))
        hdr["sections"]["vectors"]["offset"] = alias_offset
        hdr_bytes = json.dumps(hdr, sort_keys=True, separators=(",", ":")).encode("utf-8")
        # Pad out to original file length so offset + nbytes <= mm_len; only offset < h_end triggers rejection!
        pad_needed = max(0, len(base_raw) - (len(SIDECAR_MAGIC) + 8 + len(hdr_bytes)))
        p = tmp_path / f"alias_{label}.vpack"
        p.write_bytes(SIDECAR_MAGIC + struct.pack("<Q", len(hdr_bytes)) + hdr_bytes + b"\x00" * pad_needed)
        with pytest.raises(VocabularyPackError, match="bounds invalid") as exc_off:
            AtlasSemanticSidecar.open(p)
        assert exc_off.value.code == "corrupt_sidecar"

    # Extra section aliasing header bytes is also rejected.
    hdr_extra = json.loads(json.dumps(base_hdr))
    hdr_extra["sections"]["extra_alias"] = {"offset": 0, "nbytes": 4}
    hdr_extra_bytes = json.dumps(hdr_extra, sort_keys=True, separators=(",", ":")).encode("utf-8")
    p_extra = tmp_path / "alias_extra.vpack"
    pad_extra = max(0, len(base_raw) - (len(SIDECAR_MAGIC) + 8 + len(hdr_extra_bytes)))
    p_extra.write_bytes(
        SIDECAR_MAGIC + struct.pack("<Q", len(hdr_extra_bytes)) + hdr_extra_bytes + b"\x00" * pad_extra
    )
    with pytest.raises(VocabularyPackError, match="bounds invalid"):
        AtlasSemanticSidecar.open(p_extra)


def test_flat_f16_multi_vidx_per_rid_no_top_k_starvation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """F10.1: flat_f16 search routes through _top_k_from_scored so multi-vector rids never under-fill top_k."""
    pack_path = _make_minimal_pack(tmp_path / "pack_multi_flat.sqlite")
    # Two highest-scoring vectors BOTH belong to rid=10; third vector belongs to rid=20; fourth to rid=30.
    vecs = np.asarray(
        [
            [1.0, 0.0, 0.0, 0.0],    # vidx=0 -> rid=10, cos=1.00
            [0.95, 0.31, 0.0, 0.0],  # vidx=1 -> rid=10, cos~0.95
            [0.85, 0.52, 0.0, 0.0],  # vidx=2 -> rid=20, cos~0.85
            [0.70, 0.71, 0.0, 0.0],  # vidx=3 -> rid=30, cos~0.70
        ],
        dtype=np.float16,
    )
    vpath = tmp_path / "multi_flat.vpack"
    build_semantic_sidecar_from_arrays(
        pack_path,
        vpath,
        vectors_f16=vecs,
        rids_per_vector=[[10], [10], [20], [30]],
        model_id="BAAI/bge-m3",
        mode="flat_f16",
    )

    q = [1.0, 0.0, 0.0, 0.0]
    with AtlasSemanticSidecar.open(vpath) as sidecar:
        assert sidecar._unique_rid_per_vidx is False

        # Unfiltered top_k=2 must return BOTH rid=10 (best score ~1.0) and rid=20 (score ~0.85), never just [10]!
        hits = sidecar.search_rids(q, top_k=2, min_cosine=0.5)
        assert [r for r, _ in hits] == [10, 20]
        assert hits[0][1] > 0.99
        assert 0.80 < hits[1][1] < 0.90

        # Pre-masked flat_f16 branch (n_eligible > _EXACT_FILTER_THRESHOLD and > n_vecs // 4) also avoids starvation.
        monkeypatch.setattr(vv, "_EXACT_FILTER_THRESHOLD", 1)
        mask = bytearray(31)
        mask[10] = 1
        mask[20] = 1
        mask[30] = 1
        masked_hits = sidecar.search_rids(q, top_k=2, min_cosine=0.5, allowed_rids=mask)
        assert [r for r, _ in masked_hits] == [10, 20]


def test_ivf_cluster_and_iteration_parameter_validation(tmp_path: Path) -> None:
    """F10.2: Reject n_clusters < 1, ivf_iterations < 1, and booleans with VocabularyInputError."""
    pack_path = _make_minimal_pack(tmp_path / "pack_ivf_params.sqlite")
    vecs = np.eye(8, dtype=np.float16)
    rids = [[i + 1] for i in range(8)]

    for bad_clusters in (0, -1, True, False):
        with pytest.raises(VocabularyInputError, match="n_clusters") as exc_c:
            build_semantic_sidecar_from_arrays(
                pack_path,
                tmp_path / "bad_c.vpack",
                vectors_f16=vecs.copy(),
                rids_per_vector=rids,
                model_id="BAAI/bge-m3",
                mode="ivf_i8",
                n_clusters=bad_clusters,  # type: ignore[arg-type]
            )
        assert exc_c.value.code == "invalid_n_clusters"

    for bad_iters in (0, -3, True, False):
        with pytest.raises(VocabularyInputError, match="ivf_iterations") as exc_i:
            build_semantic_sidecar_from_arrays(
                pack_path,
                tmp_path / "bad_i.vpack",
                vectors_f16=vecs.copy(),
                rids_per_vector=rids,
                model_id="BAAI/bge-m3",
                mode="ivf_i8",
                ivf_iterations=bad_iters,  # type: ignore[arg-type]
            )
        assert exc_i.value.code == "invalid_ivf_iterations"

    # Also validated upfront in build_semantic_sidecar before reading Parquet/DuckDB.
    with pytest.raises(VocabularyInputError, match="n_clusters") as exc_sc:
        build_semantic_sidecar(pack_path, tmp_path, tmp_path / "out_sc.vpack", n_clusters=0)
    assert exc_sc.value.code == "invalid_n_clusters"
    with pytest.raises(VocabularyInputError, match="ivf_iterations") as exc_si:
        build_semantic_sidecar(pack_path, tmp_path, tmp_path / "out_si.vpack", ivf_iterations=0)
    assert exc_si.value.code == "invalid_ivf_iterations"


@pytest.mark.parametrize("mode", ["flat_f16", "binary_i8"])
def test_build_semantic_sidecar_rejects_null_and_ragged_arrow_embeddings(
    tmp_path: Path,
    mode: str,
) -> None:
    """F10.3: Null rows, null coordinates, empty lists, and ragged list lengths raise corrupt_embeddings."""
    view_root, digest = _write_compact_fixture(tmp_path / f"view_{mode}")
    pack_path = tmp_path / f"pack_{mode}.sqlite"
    build_vocabulary_pack(
        view_root,
        pack_path,
        trusted_manifest_digest=digest,
        schemes=(S_EURO, S_FR),
        languages=("en",),
    )

    def _make_emb_dir(label: str, vec_rows: list[dict[str, Any]]) -> Path:
        emb_dir = tmp_path / f"emb_{mode}_{label}"
        (emb_dir / "vectors").mkdir(parents=True)
        res_rows = [
            {"resource_id": "http://eurovoc.europa.eu/3027", "release": R_EURO, "scheme": S_EURO, "input_sha256": "s1"},
            {"resource_id": "urn:ref:fr:medicare", "release": R_FR, "scheme": S_FR, "input_sha256": "s2"},
            {"resource_id": "urn:ref:fr:housing", "release": R_FR, "scheme": S_FR, "input_sha256": "s3"},
        ][: len(vec_rows)]
        pq.write_table(pa.Table.from_pylist(res_rows), emb_dir / "resources.parquet")
        schema = pa.schema([("input_sha256", pa.string()), ("embedding", pa.list_(pa.float32()))])
        pq.write_table(pa.Table.from_pylist(vec_rows, schema=schema), emb_dir / "vectors" / "part-00000.parquet")
        return emb_dir

    # 1. Null vector row where non-null flattened length (12) is divisible by n_keep (3)!
    null_row_dir = _make_emb_dir(
        "null_row",
        [
            {"input_sha256": "s1", "embedding": [1.0, 2.0, 3.0, 4.0, 5.0, 6.0]},
            {"input_sha256": "s2", "embedding": None},
            {"input_sha256": "s3", "embedding": [7.0, 8.0, 9.0, 10.0, 11.0, 12.0]},
        ],
    )
    with pytest.raises(VocabularyPackError, match="null vector row") as exc_null:
        build_semantic_sidecar(pack_path, null_row_dir, tmp_path / f"out_null_{mode}.vpack", mode=mode)  # type: ignore[arg-type]
    assert exc_null.value.code == "corrupt_embeddings"

    # 2. Ragged rows where flattened length (8) is divisible by n_keep (2) -> previously split silently into (2, 4)!
    ragged_dir = _make_emb_dir(
        "ragged",
        [
            {"input_sha256": "s1", "embedding": [1.0, 2.0]},
            {"input_sha256": "s2", "embedding": [3.0, 4.0, 5.0, 6.0, 7.0, 8.0]},
        ],
    )
    with pytest.raises(VocabularyPackError, match="ragged list lengths") as exc_rag:
        build_semantic_sidecar(pack_path, ragged_dir, tmp_path / f"out_rag_{mode}.vpack", mode=mode)  # type: ignore[arg-type]
    assert exc_rag.value.code == "corrupt_embeddings"

    # 3. Null coordinate inside a list row.
    null_coord_dir = _make_emb_dir(
        "null_coord",
        [
            {"input_sha256": "s1", "embedding": [1.0, None, 0.0, 0.0]},
            {"input_sha256": "s2", "embedding": [0.0, 1.0, 0.0, 0.0]},
        ],
    )
    with pytest.raises(VocabularyPackError, match="null coordinate") as exc_coord:
        build_semantic_sidecar(pack_path, null_coord_dir, tmp_path / f"out_coord_{mode}.vpack", mode=mode)  # type: ignore[arg-type]
    assert exc_coord.value.code == "corrupt_embeddings"

    # 4. Empty list rows.
    empty_list_dir = _make_emb_dir(
        "empty_list",
        [
            {"input_sha256": "s1", "embedding": []},
            {"input_sha256": "s2", "embedding": []},
        ],
    )
    with pytest.raises(VocabularyPackError, match="empty or ragged") as exc_empty:
        build_semantic_sidecar(pack_path, empty_list_dir, tmp_path / f"out_empty_{mode}.vpack", mode=mode)  # type: ignore[arg-type]
    assert exc_empty.value.code == "corrupt_embeddings"


def test_concurrent_close_waits_for_inflight_queries_without_buffer_error_leak(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """F10.4: close() during active search_rids never raises BufferError or leaks self._mm / self._file."""
    pack_path = _make_minimal_pack(tmp_path / "pack_close.sqlite")
    rng = np.random.default_rng(999)
    vecs = rng.normal(size=(256, 32)).astype(np.float32)
    vecs /= np.linalg.norm(vecs, axis=1, keepdims=True)
    rids = [[i + 1] for i in range(256)]
    q = vecs[0]

    # Part 1: Deterministic barrier test proving close() defers mmap teardown until the active view holder exits.
    vpath = tmp_path / "close_barrier.vpack"
    build_semantic_sidecar_from_arrays(
        pack_path,
        vpath,
        vectors_f16=vecs.astype(np.float16),
        rids_per_vector=rids,
        model_id="BAAI/bge-m3",
        mode="flat_f16",
    )
    sidecar = AtlasSemanticSidecar.open(vpath)
    entered = threading.Event()
    release = threading.Event()
    orig_top_k = sidecar._top_k_from_scored

    def _blocked_top_k(*args: Any, **kwargs: Any) -> list[tuple[int, float]]:
        # Hold an explicit view into the mmap-backed array while blocked so premature mm.close() WOULD raise BufferError!
        assert sidecar._vectors_f16 is not None
        live_mmap_view = sidecar._vectors_f16[:4]
        entered.set()
        assert release.wait(timeout=5.0)
        assert live_mmap_view.shape == (4, 32)
        return orig_top_k(*args, **kwargs)

    monkeypatch.setattr(sidecar, "_top_k_from_scored", _blocked_top_k)

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(sidecar.search_rids, q, top_k=5, min_cosine=0.5)
        assert entered.wait(timeout=5.0)
        assert sidecar._active_queries == 1

        # Closing mid-query must NOT raise BufferError and must immediately reject new queries.
        sidecar.close()
        assert sidecar._closing is True
        assert sidecar._mm.closed is False

        with pytest.raises(VocabularyPackError, match="closed") as exc_s:
            sidecar.search_rids(q, top_k=5)
        assert exc_s.value.code == "closed_sidecar"
        with pytest.raises(VocabularyPackError, match="closed") as exc_v:
            sidecar.vector_for_rid(1)
        assert exc_v.value.code == "closed_sidecar"

        # Releasing the in-flight query finishes it cleanly and finalizes mmap + fd teardown!
        release.set()
        worker_hits = future.result(timeout=5.0)

    assert worker_hits and worker_hits[0][0] == 1
    assert sidecar._active_queries == 0
    assert sidecar._closed is True
    assert sidecar._mm.closed is True
    assert sidecar._file.closed is True
    sidecar.close()  # idempotent after deferred finalization

    # Part 2: Multi-thread stress test across all three storage modes.
    def _hammer(
        tid: int,
        sc: AtlasSemanticSidecar,
        barrier: threading.Barrier,
    ) -> None:
        barrier.wait()
        for step in range(40):
            try:
                if (tid + step) % 4 == 0:
                    sc.vector_for_rid((step % 256) + 1)
                else:
                    sc.search_rids(q, top_k=5, min_cosine=0.5, nprobe=4)
            except VocabularyPackError as exc:
                if exc.code == "closed_sidecar":
                    return
                raise

    for mode in ("flat_f16", "binary_i8", "ivf_i8"):
        mp = tmp_path / f"close_stress_{mode}.vpack"
        build_semantic_sidecar_from_arrays(
            pack_path,
            mp,
            vectors_f16=vecs.astype(np.float16),
            rids_per_vector=rids,
            model_id="BAAI/bge-m3",
            mode=mode,  # type: ignore[arg-type]
            n_clusters=8,
            ivf_iterations=4,
        )
        sc = AtlasSemanticSidecar.open(mp)
        started_barrier = threading.Barrier(9)
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            futures = [pool.submit(_hammer, i, sc, started_barrier) for i in range(8)]
            started_barrier.wait()
            sc.close()
            for fut in futures:
                fut.result(timeout=10.0)

        assert sc._active_queries == 0
        assert sc._closed is True
        assert sc._mm.closed is True
        assert sc._file.closed is True


@pytest.mark.parametrize("mode", ["flat_f16", "binary_i8", "ivf_i8"])
def test_centered_covariance_calibration_parity_and_evt_ood_abstention_all_modes(tmp_path: Path, mode: str) -> None:
    """Verify exact (v-mu)^T(q-mu)/(1-||mu||^2) parity, unsupervised EVT threshold, and subset scaling across all 3 modes."""
    pack_path = _make_minimal_pack(tmp_path / f"cal_pack_{mode}.sqlite")
    rng = np.random.default_rng(77)
    n_vecs = 1_200
    dim = 64

    # Construct a realistic narrow-cone anisotropic corpus (||mu|| ~ 0.82, avg pairwise cosine ~ 0.67).
    cone_axis = np.zeros(dim, dtype=np.float32)
    cone_axis[0] = 1.0
    perp = rng.normal(size=(n_vecs, dim)).astype(np.float32)
    perp[:, 0] = 0.0
    perp /= np.linalg.norm(perp, axis=1, keepdims=True)
    vecs = 0.82 * cone_axis[None, :] + math.sqrt(1.0 - 0.82**2) * perp
    vecs /= np.linalg.norm(vecs, axis=1, keepdims=True)
    rids = [[i + 1] for i in range(n_vecs)]

    # Build with calibration_mode="auto": N=1200 >= 1024 and ||mu||^2 ~ 0.67 >= 0.10 -> activates centered_covariance!
    vpath = tmp_path / f"cal_{mode}.vpack"
    man = build_semantic_sidecar_from_arrays(
        pack_path,
        vpath,
        vectors_f16=vecs.astype(np.float16),
        rids_per_vector=rids,
        model_id="google/embeddinggemma-2-512d-mrl",
        mode=mode,  # type: ignore[arg-type]
        n_clusters=16,
        ivf_iterations=6,
        seed=42,
        calibration_mode="auto",
    )
    assert man.calibration_mode == "centered_covariance"
    assert man.corpus_mean_norm_sq is not None and 0.60 < man.corpus_mean_norm_sq < 0.75
    assert man.corpus_pair_std is not None and man.corpus_pair_std > 0.0
    assert man.recommended_min_cosine is not None and 0.25 <= man.recommended_min_cosine <= 0.95
    assert man.to_dict()["calibrationMode"] == "centered_covariance"

    # Compute exact reference corpus mean & centered-covariance scores.
    vecs_f32 = vecs.astype(np.float16).astype(np.float32)
    vecs_f32 /= np.linalg.norm(vecs_f32, axis=1, keepdims=True)
    mu_ref = vecs_f32.astype(np.float64).mean(axis=0)
    res_var_ref = 1.0 - float(np.dot(mu_ref, mu_ref))

    # Positive query = perturbed target vector #5; OOD queries = fresh random vectors inside the same narrow cone!
    q_pos = vecs_f32[5].copy()
    ood_perp = rng.normal(size=(8, dim)).astype(np.float32)
    ood_perp[:, 0] = 0.0
    ood_perp /= np.linalg.norm(ood_perp, axis=1, keepdims=True)
    q_oods = 0.82 * cone_axis[None, :] + math.sqrt(1.0 - 0.82**2) * ood_perp
    q_oods /= np.linalg.norm(q_oods, axis=1, keepdims=True)

    with (
        AtlasSemanticSidecar.open(vpath) as sidecar,
        AtlasSemanticSidecar.open(vpath, use_calibration=False) as raw_sidecar,
    ):
        assert sidecar.calibration_mode == "centered_covariance"
        assert sidecar.calibration_active is True
        assert raw_sidecar.calibration_active is False

        # 1. Exact parity on positive self-retrieval: calibrated score matches (v-mu)^T(q-mu)/(1-||mu||^2).
        hits_pos = sidecar.search_rids(q_pos, top_k=5, min_cosine=sidecar.recommended_min_cosine or 0.55, nprobe=16, rerank_top_r=256)
        assert hits_pos and hits_pos[0][0] == 6
        expected_self = float(np.dot(vecs_f32[5] - mu_ref, q_pos - mu_ref) / res_var_ref)
        assert hits_pos[0][1] == pytest.approx(expected_self, abs=0.03)

        # 2. Uncalibrated raw_sidecar leaks OOD false positives at min_cosine=0.55 (narrow cone!),
        #    while calibrated sidecar abstains cleanly (0/8 OOD FP) using unsupervised recommended_min_cosine!
        raw_fp = sum(1 for qo in q_oods if raw_sidecar.search_rids(qo, top_k=5, min_cosine=0.55, nprobe=16))
        cal_fp = sum(
            1
            for qo in q_oods
            if sidecar.search_rids(qo, top_k=5, min_cosine=sidecar.recommended_min_cosine or 0.55, nprobe=16)
        )
        assert raw_fp == 8
        assert cal_fp == 0

        # 3. Subset-size EVT scaling lowers effective threshold on tiny filtered subsets while clamping at N_floor=64.
        # Build a query whose calibrated similarity to target rid=6 sits strictly between scaled_thr and full_thr.
        full_thr = float(sidecar.recommended_min_cosine or 0.70)
        evt_factor_64 = math.sqrt(math.log(64) / math.log(n_vecs))
        target_score = 0.5 * (full_thr + full_thr * evt_factor_64)
        # Construct synthetic query with exact dot_c / res_var == target_score to vecs_f32[5]
        v5_sub = vecs_f32[5] - mu_ref.astype(np.float32)
        v5_unit = v5_sub / np.linalg.norm(v5_sub)
        orth = rng.normal(size=dim).astype(np.float32)
        orth[0] = 0.0
        orth -= float(np.dot(orth, v5_unit)) * v5_unit
        orth /= np.linalg.norm(orth)
        alpha = target_score * res_var_ref / float(np.linalg.norm(v5_sub))
        beta = math.sqrt(max(1e-6, res_var_ref - alpha * alpha))
        q_mid = mu_ref.astype(np.float32) + alpha * v5_unit + beta * orth
        q_mid /= np.linalg.norm(q_mid)

        # Filtered to 8 rids (<= 64 -> uses N_floor=64 EVT scaling): target rid=6 MUST pass!
        small_subset = {6, 10, 20, 30, 40, 50, 60, 70}
        filtered_hits = sidecar.search_rids(
            q_mid, top_k=5, min_cosine=full_thr, nprobe=16, allowed_rids=small_subset
        )
        assert any(rid == 6 for rid, _ in filtered_hits)


def test_calibrate_semantic_sidecar_upgrade_and_corrupt_header_rejection(tmp_path: Path) -> None:
    """Verify zero-re-embedding calibrate_semantic_sidecar (separate & in-place) and fail-closed validation."""
    pack_path = _make_minimal_pack(tmp_path / "cal_upgrade.sqlite")
    rng = np.random.default_rng(19)
    n_vecs = 128
    dim = 32
    axis = np.zeros(dim, dtype=np.float32)
    axis[0] = 1.0
    perp = rng.normal(size=(n_vecs, dim)).astype(np.float32)
    perp[:, 0] = 0.0
    perp /= np.linalg.norm(perp, axis=1, keepdims=True)
    vecs = 0.80 * axis[None, :] + 0.60 * perp
    vecs /= np.linalg.norm(vecs, axis=1, keepdims=True)
    rids = [[i + 1] for i in range(n_vecs)]

    # 1. Build uncalibrated sidecar, then upgrade via calibrate_semantic_sidecar.
    raw_vpath = tmp_path / "raw_bin.vpack"
    build_semantic_sidecar_from_arrays(
        pack_path,
        raw_vpath,
        vectors_f16=vecs.astype(np.float16),
        rids_per_vector=rids,
        model_id="google/embeddinggemma-2-512d-mrl",
        mode="binary_i8",
        calibration_mode="none",
    )
    with AtlasSemanticSidecar.open(raw_vpath) as raw_sc:
        assert raw_sc.calibration_mode == "none"
        assert raw_sc.calibration_active is False

    cal_vpath = tmp_path / "upgraded_bin.vpack"
    man = calibrate_semantic_sidecar(raw_vpath, cal_vpath)
    assert man.calibration_mode == "centered_covariance"
    assert man.recommended_min_cosine is not None
    assert man.corpus_mean_norm_sq is not None and man.corpus_pair_std is not None

    # In-place recalibration must succeed cleanly via atomic mkstemp + os.replace.
    man_inplace = calibrate_semantic_sidecar(cal_vpath, cal_vpath, recommended_min_cosine=0.72)
    assert man_inplace.recommended_min_cosine == pytest.approx(0.72)

    with AtlasSemanticSidecar.open(cal_vpath) as cal_sc:
        assert cal_sc.calibration_active is True
        assert cal_sc.recommended_min_cosine == pytest.approx(0.72)
        hits = cal_sc.search_rids(vecs[3], top_k=3, min_cosine=0.5)
        assert hits and hits[0][0] == 4

    # 2. Input validation & degenerate corpus rejection.
    with pytest.raises(VocabularyInputError) as exc_cm:
        build_semantic_sidecar_from_arrays(
            pack_path,
            tmp_path / "bad_cm.vpack",
            vectors_f16=vecs.astype(np.float16),
            rids_per_vector=rids,
            model_id="m",
            calibration_mode="bogus",  # type: ignore[arg-type]
        )
    assert exc_cm.value.code == "invalid_calibration_mode"

    for bad_sig in (0.0, -1.0, float("nan"), True):
        with pytest.raises(VocabularyInputError) as exc_es:
            calibrate_semantic_sidecar(raw_vpath, tmp_path / "bad_es.vpack", calibration_evt_sigma=bad_sig)  # type: ignore[arg-type]
        assert exc_es.value.code == "invalid_calibration_evt_sigma"

    identical = np.tile(axis, (16, 1)).astype(np.float16)
    with pytest.raises(VocabularyInputError) as exc_deg:
        build_semantic_sidecar_from_arrays(
            pack_path,
            tmp_path / "deg.vpack",
            vectors_f16=identical,
            rids_per_vector=[[i + 1] for i in range(16)],
            model_id="m",
            mode="flat_f16",
            calibration_mode="centered_covariance",
        )
    assert exc_deg.value.code == "degenerate_corpus_moments"

    # 3. Corrupt calibration headers / corpus_mean_f32 bytes fail closed on open.
    base_hdr, _hend, base_raw = _read_vpack_header(cal_vpath)
    min_sec = min(s["offset"] for s in base_hdr["sections"].values())
    body = bytes(base_raw[min_sec:])

    for idx, patch in enumerate(
        (
            {"calibrationMode": "unknown_mode"},
            {"corpusMeanNormSq": 1.0},
            {"corpusMeanNormSq": -0.1},
            {"corpusMeanNormSq": True},
            {"corpusPairStd": 0.0},
            {"corpusPairStd": -0.5},
        )
    ):
        hdr = json.loads(json.dumps(base_hdr))
        hdr.update(patch)
        p = tmp_path / f"corrupt_cal_{idx}.vpack"
        _rewrite_vpack_with_header(p, hdr, body)
        with pytest.raises(VocabularyPackError) as exc_c:
            AtlasSemanticSidecar.open(p)
        assert exc_c.value.code == "corrupt_sidecar"

    # Missing corpus_mean_f32 section when calibrationMode=="centered_covariance" fails closed.
    hdr_no_sec = json.loads(json.dumps(base_hdr))
    del hdr_no_sec["sections"]["corpus_mean_f32"]
    p_no_sec = tmp_path / "missing_mu_sec.vpack"
    _rewrite_vpack_with_header(p_no_sec, hdr_no_sec, body)
    with pytest.raises(VocabularyPackError) as exc_ms:
        AtlasSemanticSidecar.open(p_no_sec)
    assert exc_ms.value.code == "corrupt_sidecar"

    # NaN injected into corpus_mean_f32 section fails closed.
    nan_raw = bytearray(base_raw)
    mu_off = base_hdr["sections"]["corpus_mean_f32"]["offset"]
    nan_raw[mu_off : mu_off + 4] = struct.pack("<f", float("nan"))
    p_nan = tmp_path / "nan_mu.vpack"
    p_nan.write_bytes(nan_raw)
    with pytest.raises(VocabularyPackError, match="non-finite") as exc_nan:
        AtlasSemanticSidecar.open(p_nan)
    assert exc_nan.value.code == "corrupt_sidecar"



