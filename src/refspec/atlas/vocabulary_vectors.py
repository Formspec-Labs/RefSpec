"""Tier-1 scalable memory-mapped semantic vector sidecar for Atlas Vocabulary Packs.

Implements ``refspec.atlas.vocabulary_protocols.SemanticIndex`` with zero database
coupling at query time, ``O(1)`` ``vector_for_rid`` reverse lookups, fast ``pack_id``
binding, pre-filtered low-selectivity search, and three storage layouts inside one
sealed binary container (``.vpack``):

* ``flat_f16`` (default for ``N <= 50,000`` unique vectors, e.g. OP-1 EuroVoc +
  Federal Register = 16.05 MiB): zero-copy ``np.memmap`` float16 matrix scanned
  via exact cosine dot product in ~0.17 ms.
* ``binary_i8`` (automatic for ``N > 50,000`` unique vectors, e.g. OP-2 11 major
  schemes = 807k unique vectors): portable zero-C-dependency strict ``x > 0``
  1-bit sign quantization (``binary_u8``) scanned via chunked XOR + NumPy 2
  ``np.bitwise_count`` SIMD Hamming distance (with 256-entry popcount LUT
  fallback on NumPy < 2.0), followed by exact symmetric ``int8`` dot-product
  reranking of the top ``rerank_top_r`` candidates.
* ``ivf_i8`` (explicitly selectable via ``mode="ivf_i8"``): deterministic seeded
  spherical k-means coarse partitioning + per-vector symmetric ``int8`` scalar
  quantization stored contiguously by cluster in ``np.memmap``. At query time,
  probed cluster ranges are gathered into one contiguous buffer and scored with
  a single BLAS SGEMV (with adaptive probe expansion when filtered).
"""

from __future__ import annotations

import contextlib
import errno
import hashlib
import json
import math
import mmap
import os
import sqlite3
import stat
import struct
import sys
import tempfile
import threading
from collections import OrderedDict, defaultdict
from collections.abc import Sequence
from collections.abc import Set as AbstractSet
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal
from urllib.parse import quote

import numpy as np

from refspec.atlas.vocabulary_protocols import (
    DEFAULT_CALIBRATION_EVT_SIGMA,
    DEFAULT_CALIBRATION_MIN_ELIGIBLE,
    VocabularyInputError,
    VocabularyPackError,
)

SIDECAR_MAGIC = b"RFVP0001"
SIDECAR_SCHEMA_VERSION = "2"
_SIDECAR_RECORD_TYPE = "AtlasSemanticSidecar"
_MAX_SIDECAR_HEADER_BYTES = 16 * 1024 * 1024
_DARWIN_SYSTEM_SYMLINKS = frozenset({"/var", "/tmp", "/etc"})
_PACK_RECORD_TYPE = "AtlasVocabularyPack"
_SUPPORTED_PACK_SCHEMA_VERSIONS: frozenset[str] = frozenset({"2", "3"})
_ALIGN_BYTES = 64
_FLAT_THRESHOLD = 50_000
_EXACT_FILTER_THRESHOLD = 5_000
_IVF_EXACT_FALLBACK_THRESHOLD = 50_000
_DEFAULT_RERANK_TOP_R = 256
_CHUNK_ROWS = 16_384
_FLAT_QUERY_CHUNK = 16_384
_BINARY_SCAN_CHUNK = 32_768
_RERANK_CHUNK_ROWS = 256
_MASK_CACHE_MAX_ENTRIES = 4
_MASK_CACHE_MAX_BYTES = 16_777_216
_MISSING_VIDX = 0xFFFFFFFF
_CALIBRATION_MODES = frozenset({"auto", "none", "centered_covariance"})
_HEADER_CALIBRATION_MODES = frozenset({"none", "centered_covariance"})
_AUTO_CALIBRATION_MIN_VECS = 1_024
_AUTO_CALIBRATION_MIN_MEAN_NORM_SQ = 0.10
_CALIBRATION_MIN_RESIDUAL_VAR = 1e-4
_CALIBRATION_EVT_N_FLOOR = DEFAULT_CALIBRATION_MIN_ELIGIBLE
_AUTO_REC_MIN_COSINE_LO = 0.25
_AUTO_REC_MIN_COSINE_HI = 0.95
_POPCOUNT_LUT = np.array([i.bit_count() for i in range(256)], dtype=np.uint8)
_U64_BYTE_OFFSETS = np.arange(8, dtype=np.intp)


@dataclass(frozen=True, slots=True)
class SemanticSidecarManifest:
    """Immutable metadata summary for a compiled Tier-1 semantic vector sidecar."""

    sidecar_path: Path
    sidecar_sha256: str
    size_bytes: int
    pack_id: str
    pack_sha256: str
    source_manifest_digest: str
    model_id: str
    mode: str
    dimensions: int
    unique_vector_count: int
    mapped_resource_count: int
    n_clusters: int
    built_at: str
    recommended_min_cosine: float | None = None
    calibration_mode: str = "none"
    corpus_mean_norm_sq: float | None = None
    corpus_pair_std: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "recordType": "AtlasSemanticSidecar",
            "schemaVersion": SIDECAR_SCHEMA_VERSION,
            "sidecarPath": str(self.sidecar_path),
            "sidecarSha256": self.sidecar_sha256,
            "sizeBytes": self.size_bytes,
            "packId": self.pack_id,
            "packSha256": self.pack_sha256,
            "sourceManifestDigest": self.source_manifest_digest,
            "modelId": self.model_id,
            "mode": self.mode,
            "dimensions": self.dimensions,
            "uniqueVectorCount": self.unique_vector_count,
            "mappedResourceCount": self.mapped_resource_count,
            "nClusters": self.n_clusters,
            "builtAt": self.built_at,
            "recommendedMinCosine": self.recommended_min_cosine,
            "calibrationMode": self.calibration_mode,
            "corpusMeanNormSq": self.corpus_mean_norm_sq,
            "corpusPairStd": self.corpus_pair_std,
        }


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


def _sha256_mmap(mm: mmap.mmap) -> str:
    """Hash an already-open read-only mmap in 1 MiB chunks without reopening by path."""

    digest = hashlib.sha256()
    mv = memoryview(mm)
    try:
        total = len(mv)
        chunk_size = 1 << 20
        for start in range(0, total, chunk_size):
            chunk = mv[start : start + chunk_size]
            try:
                digest.update(chunk)
            finally:
                chunk.release()
    finally:
        mv.release()
    return f"sha256:{digest.hexdigest()}"


def _align(offset: int) -> int:
    rem = offset % _ALIGN_BYTES
    return offset if rem == 0 else offset + (_ALIGN_BYTES - rem)


def _as_byte_view(arr: np.ndarray) -> memoryview:
    """Return a zero-copy C-contiguous byte view of ``arr`` for streaming writes."""

    return memoryview(np.ascontiguousarray(arr)).cast("B")


def _l2_normalize_rows(mat: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(mat, axis=1, keepdims=True)
    norms = np.where(norms > 1e-12, norms, 1.0)
    return mat / norms


def _l2_normalize_rows_inplace(mat_f32: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(mat_f32, axis=1, keepdims=True)
    norms = np.where(norms > 1e-12, norms, 1.0)
    mat_f32 /= norms
    return mat_f32


def _quantize_symmetric_i8(vecs_f32: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Per-vector symmetric int8 quantization: v ~= q * scale (0.999+ cosine fidelity)."""

    max_abs = np.max(np.abs(vecs_f32), axis=1)
    scales = np.where(max_abs > 1e-12, max_abs / 127.0, 1.0).astype(np.float32)
    q = np.rint(vecs_f32 / scales[:, None]).clip(-127, 127).astype(np.int8)
    return q, scales.astype(np.float16)


def _validate_recommended_min_cosine(
    value: Any,
    *,
    for_input: bool,
) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        if for_input:
            raise VocabularyInputError(
                "invalid_recommended_min_cosine",
                "recommended_min_cosine must be a finite number in [-1.0, 1.0] or None",
            )
        raise VocabularyPackError(
            "corrupt_sidecar",
            "recommendedMinCosine header value must be a finite number in [-1.0, 1.0] or null",
        )
    fval = float(value)
    if not math.isfinite(fval) or fval < -1.0 or fval > 1.0:
        if for_input:
            raise VocabularyInputError(
                "invalid_recommended_min_cosine",
                f"recommended_min_cosine must be finite and within [-1.0, 1.0], got {fval!r}",
            )
        raise VocabularyPackError(
            "corrupt_sidecar",
            f"recommendedMinCosine header value out of range [-1.0, 1.0]: {fval!r}",
        )
    return fval


def _validate_positive_int(value: Any, *, code: str, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise VocabularyInputError(code, f"{name} must be a positive integer (>= 1), got {value!r}")
    return value


def _validate_calibration_mode(
    value: Any,
    *,
    for_input: bool,
) -> str:
    if value is None and not for_input:
        return "none"
    allowed = _CALIBRATION_MODES if for_input else _HEADER_CALIBRATION_MODES
    if not isinstance(value, str) or value not in allowed:
        if for_input:
            raise VocabularyInputError(
                "invalid_calibration_mode",
                f"calibration_mode must be one of {sorted(allowed)}, got {value!r}",
            )
        raise VocabularyPackError(
            "corrupt_sidecar",
            f"calibrationMode header value must be one of {sorted(allowed)}, got {value!r}",
        )
    return value


def _validate_calibration_evt_sigma(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise VocabularyInputError(
            "invalid_calibration_evt_sigma",
            f"calibration_evt_sigma must be a finite positive number, got {value!r}",
        )
    fval = float(value)
    if not math.isfinite(fval) or fval <= 0.0:
        raise VocabularyInputError(
            "invalid_calibration_evt_sigma",
            f"calibration_evt_sigma must be a finite positive number, got {fval!r}",
        )
    return fval


class _CorpusMomentAccumulator:
    """Streaming float64 accumulator for exact corpus mean ``mu`` and ``Tr(Sigma^2)``."""

    def __init__(self, dim: int) -> None:
        self._dim = int(dim)
        self._sum_v = np.zeros(self._dim, dtype=np.float64)
        self._sum_vv = np.zeros((self._dim, self._dim), dtype=np.float64)
        self._count = 0

    def update(self, chunk_f32: np.ndarray) -> None:
        if chunk_f32.size == 0:
            return
        blk64 = np.asarray(chunk_f32, dtype=np.float64)
        self._sum_v += blk64.sum(axis=0)
        self._sum_vv += blk64.T @ blk64
        self._count += int(blk64.shape[0])

    def finalize(
        self,
        *,
        requested_mode: str,
        evt_sigma: float,
        explicit_recommended_min_cosine: float | None,
    ) -> tuple[str, np.ndarray | None, float | None, float | None, float | None]:
        """Resolve calibration mode and compute ``(mode, mu_f32, mu_norm_sq, pair_std, rec_min_cos)``."""

        if requested_mode == "none" or self._count == 0:
            return "none", None, None, None, explicit_recommended_min_cosine

        mu_f64 = self._sum_v / float(self._count)
        mu_norm_sq = float(np.dot(mu_f64, mu_f64))
        res_var = 1.0 - mu_norm_sq

        if requested_mode == "auto":
            if (
                self._count < _AUTO_CALIBRATION_MIN_VECS
                or mu_norm_sq < _AUTO_CALIBRATION_MIN_MEAN_NORM_SQ
                or res_var < _CALIBRATION_MIN_RESIDUAL_VAR
            ):
                return "none", None, None, None, explicit_recommended_min_cosine
        elif res_var < _CALIBRATION_MIN_RESIDUAL_VAR:
            raise VocabularyInputError(
                "degenerate_corpus_moments",
                f"cannot compute centered_covariance calibration: residual variance {res_var:.6g} "
                f"is below {_CALIBRATION_MIN_RESIDUAL_VAR}",
            )

        sigma = (self._sum_vv / float(self._count)) - np.outer(mu_f64, mu_f64)
        tr_sigma_sq = float(np.sum(sigma * sigma))
        pair_std = math.sqrt(max(tr_sigma_sq, 0.0)) / res_var

        rec_min = explicit_recommended_min_cosine
        if rec_min is None and pair_std > 0.0 and math.isfinite(pair_std):
            raw_evt = evt_sigma * pair_std * math.sqrt(2.0 * math.log(max(self._count, _CALIBRATION_EVT_N_FLOOR)))
            rec_min = round(min(max(raw_evt, _AUTO_REC_MIN_COSINE_LO), _AUTO_REC_MIN_COSINE_HI), 6)

        return (
            "centered_covariance",
            mu_f64.astype(np.float32),
            round(mu_norm_sq, 8),
            round(pair_std, 8),
            rec_min,
        )


def _reject_symlink_path(
    raw: Path,
    label: str,
    *,
    error_code: str = "invalid_sidecar",
) -> None:
    """Reject a symlink target or non-system symlinked parent component before calling ``.resolve()``."""

    candidate = raw if raw.is_absolute() else Path.cwd() / raw
    if raw.is_symlink() or candidate.is_symlink():
        raise VocabularyPackError(error_code, f"{label} path must not be a symlink: {raw}")
    for parent in candidate.parents:
        if sys.platform == "darwin" and str(parent) in _DARWIN_SYSTEM_SYMLINKS:
            continue
        if parent.is_symlink():
            raise VocabularyPackError(error_code, f"{label} traverses a symlinked parent directory: {parent}")


def _validate_regular_input_file(
    raw_input: Path | str,
    *,
    code_symlink: str,
    code_missing: str,
    label: str,
) -> Path:
    raw = Path(raw_input)
    _reject_symlink_path(raw, label, error_code=code_symlink)
    try:
        resolved = raw.resolve(strict=True)
    except OSError as exc:
        raise VocabularyPackError(code_missing, f"{label} not found: {raw_input}") from exc
    if not resolved.is_file():
        raise VocabularyPackError(code_symlink, f"{label} is not a regular file: {resolved}")
    return resolved


def _validate_regular_input_dir(
    raw_input: Path | str,
    *,
    code: str,
    label: str,
) -> Path:
    raw = Path(raw_input)
    _reject_symlink_path(raw, label, error_code=code)
    try:
        resolved = raw.resolve(strict=True)
    except OSError as exc:
        raise VocabularyPackError(code, f"{label} not found: {raw_input}") from exc
    if not resolved.is_dir():
        raise VocabularyPackError(code, f"{label} is not a regular directory: {resolved}")
    return resolved


def _validate_output_path(raw_output: Path | str) -> Path:
    raw = Path(raw_output)
    _reject_symlink_path(raw, "semantic sidecar output", error_code="invalid_sidecar")
    return raw.resolve()


def _read_pack_meta_and_resources(
    resolved_pack: Path,
    *,
    load_resources: bool = False,
) -> tuple[str, str, tuple[str, ...], dict[tuple[str, str], int]]:
    uri = f"file:{quote(str(resolved_pack))}?mode=ro&immutable=1"
    try:
        con = sqlite3.connect(uri, uri=True)
    except sqlite3.Error as exc:
        raise VocabularyPackError("corrupt_pack", f"failed to open vocabulary pack: {exc}") from exc
    try:
        try:
            meta = dict(con.execute("SELECT key, value FROM pack_meta").fetchall())
        except sqlite3.Error as exc:
            raise VocabularyPackError("corrupt_pack", f"vocabulary pack metadata is unreadable: {exc}") from exc

        record_type = meta.get("record_type")
        schema_version = meta.get("schema_version")
        if record_type != _PACK_RECORD_TYPE or schema_version not in _SUPPORTED_PACK_SCHEMA_VERSIONS:
            raise VocabularyPackError(
                "unsupported_schema",
                f"expected {_PACK_RECORD_TYPE} schema version in {sorted(_SUPPORTED_PACK_SCHEMA_VERSIONS)}, "
                f"got record_type={record_type!r} schema_version={schema_version!r}",
            )
        source_manifest_digest = str(meta.get("source_manifest_digest", "")).strip()
        if not source_manifest_digest:
            raise VocabularyPackError("corrupt_pack", "vocabulary pack lacks source_manifest_digest")
        pack_id = str(meta.get("pack_id", "")).strip()

        schemes: tuple[str, ...] = ()
        rid_by_key: dict[tuple[str, str], int] = {}
        if load_resources:
            raw_schemes = meta.get("schemes_json")
            if not raw_schemes:
                raise VocabularyPackError("corrupt_pack", "vocabulary pack lacks schemes_json")
            try:
                parsed_schemes = json.loads(raw_schemes)
            except json.JSONDecodeError as exc:
                raise VocabularyPackError("corrupt_pack", f"malformed schemes_json in pack_meta: {exc}") from exc
            if not isinstance(parsed_schemes, list) or not all(isinstance(s, str) for s in parsed_schemes):
                raise VocabularyPackError("corrupt_pack", "schemes_json in pack_meta must be a JSON string list")
            schemes = tuple(parsed_schemes)
            try:
                rel_by_id = dict(con.execute("SELECT rel_id, uri FROM releases").fetchall())
                rid_by_key = {
                    (res_id, rel_by_id[rel_id]): int(rid)
                    for rid, res_id, rel_id in con.execute(
                        "SELECT rid, id, rel_id FROM resources WHERE pref_label IS NOT NULL"
                    )
                }
            except (sqlite3.Error, KeyError) as exc:
                raise VocabularyPackError("corrupt_pack", f"failed to read vocabulary pack resources: {exc}") from exc
        return pack_id, source_manifest_digest, schemes, rid_by_key
    finally:
        con.close()


def _hamming_distances_u8(
    matrix_u8: np.ndarray,
    q_bits_u8: np.ndarray,
    out_dtype: np.dtype[Any] | type[np.unsignedinteger[Any]],
) -> np.ndarray:
    """Compute exact row-wise Hamming distances between packed binary rows and a query bit vector.

    Uses NumPy 2's SIMD ``np.bitwise_count`` (over aligned ``uint32`` word views when
    ``n_bytes % 4 == 0``, or ``uint8`` directly for non-multiple-of-4 packed widths and
    unaligned buffers), falling back cleanly to the 256-entry ``_POPCOUNT_LUT`` on NumPy < 2.0.
    """

    n_vecs, n_bytes = matrix_u8.shape
    dtype = np.dtype(out_dtype)
    if n_vecs == 0:
        return np.empty(0, dtype=dtype)
    if n_bytes == 0:
        return np.zeros(n_vecs, dtype=dtype)

    q_u8 = np.ascontiguousarray(q_bits_u8, dtype=np.uint8)
    hamming = np.empty(n_vecs, dtype=dtype)
    chunk_rows = min(_BINARY_SCAN_CHUNK, n_vecs)

    if hasattr(np, "bitwise_count"):
        if (
            n_bytes >= 4
            and n_bytes % 4 == 0
            and matrix_u8.flags.c_contiguous
            and (matrix_u8.ctypes.data % 4 == 0)
            and (q_u8.ctypes.data % 4 == 0)
        ):
            m32 = matrix_u8.view(np.uint32)
            q32 = q_u8.view(np.uint32)
            n_words = m32.shape[1]
            xor_buf = np.empty((chunk_rows, n_words), dtype=np.uint32)
            bc_buf = np.empty((chunk_rows, n_words), dtype=np.uint8)
            for start in range(0, n_vecs, chunk_rows):
                end = min(start + chunk_rows, n_vecs)
                n = end - start
                np.bitwise_xor(m32[start:end], q32, out=xor_buf[:n])
                np.bitwise_count(xor_buf[:n], out=bc_buf[:n])
                np.sum(bc_buf[:n], axis=1, dtype=dtype, out=hamming[start:end])
            return hamming

        buf_u8 = np.empty((chunk_rows, n_bytes), dtype=np.uint8)
        for start in range(0, n_vecs, chunk_rows):
            end = min(start + chunk_rows, n_vecs)
            n = end - start
            np.bitwise_xor(matrix_u8[start:end], q_u8, out=buf_u8[:n])
            np.bitwise_count(buf_u8[:n], out=buf_u8[:n])
            np.sum(buf_u8[:n], axis=1, dtype=dtype, out=hamming[start:end])
        return hamming

    for start in range(0, n_vecs, chunk_rows):
        end = min(start + chunk_rows, n_vecs)
        xored = np.bitwise_xor(matrix_u8[start:end], q_u8)
        hamming[start:end] = _POPCOUNT_LUT[xored].sum(axis=1, dtype=dtype)
    return hamming


def _hamming_distances_u8_indexed(
    matrix_u8: np.ndarray,
    q_bits_u8: np.ndarray,
    indices: np.ndarray,
    out_dtype: np.dtype[Any] | type[np.unsignedinteger[Any]],
) -> np.ndarray:
    """Compute exact Hamming distances for a sorted subset of packed binary rows in bounded RAM."""

    n_sub = int(indices.size)
    dtype = np.dtype(out_dtype)
    if n_sub == 0:
        return np.empty(0, dtype=dtype)
    hamming = np.empty(n_sub, dtype=dtype)
    chunk_rows = min(_BINARY_SCAN_CHUNK, n_sub)
    for start in range(0, n_sub, chunk_rows):
        end = min(start + chunk_rows, n_sub)
        sub_mat = np.ascontiguousarray(matrix_u8[indices[start:end]])
        hamming[start:end] = _hamming_distances_u8(sub_mat, q_bits_u8, dtype)
    return hamming


def _train_spherical_ivf(
    vecs_f16: np.ndarray,
    *,
    n_clusters: int,
    n_iter: int = 12,
    sample_size: int = 120_000,
    seed: int = 42,
) -> tuple[np.ndarray, np.ndarray]:
    """Deterministic seeded mini-batch spherical k-means returning (centroids_f32, cluster_ids_u32)."""

    n_clusters = _validate_positive_int(n_clusters, code="invalid_n_clusters", name="n_clusters")
    n_iter = _validate_positive_int(n_iter, code="invalid_ivf_iterations", name="ivf_iterations")
    n_total, dim = vecs_f16.shape
    k = min(n_clusters, max(1, n_total // 32))
    rng = np.random.default_rng(seed)

    # Sample training subset for fast k-means convergence without inflating RAM.
    if n_total > sample_size:
        train_idx = rng.choice(n_total, size=sample_size, replace=False)
        train_idx.sort()
        train = _l2_normalize_rows(vecs_f16[train_idx].astype(np.float32))
    else:
        train = _l2_normalize_rows(vecs_f16.astype(np.float32))

    # Deterministic random distinct initialization on unit sphere.
    init_idx = rng.choice(train.shape[0], size=k, replace=False)
    centroids = train[init_idx].copy()

    batch = 16_384
    for _ in range(n_iter):
        sums = np.zeros((k, dim), dtype=np.float32)
        counts = np.zeros(k, dtype=np.int64)
        for start in range(0, train.shape[0], batch):
            blk = train[start : start + batch]
            sims = blk @ centroids.T
            assign = np.argmax(sims, axis=1)
            np.add.at(sums, assign, blk)
            counts += np.bincount(assign, minlength=k)
        nonempty = counts > 0
        if np.any(nonempty):
            centroids[nonempty] = _l2_normalize_rows(sums[nonempty])
        # Re-seed any empty cluster deterministically from training samples.
        empty_ids = np.flatnonzero(~nonempty)
        if empty_ids.size:
            repl = rng.choice(train.shape[0], size=empty_ids.size, replace=False)
            centroids[empty_ids] = train[repl]

    # Assign ALL vectors to nearest centroid in bounded-RAM chunks.
    assignments = np.empty(n_total, dtype=np.uint32)
    for start in range(0, n_total, _CHUNK_ROWS):
        end = min(start + _CHUNK_ROWS, n_total)
        blk = vecs_f16[start:end].astype(np.float32)
        sims = blk @ centroids.T
        assignments[start:end] = np.argmax(sims, axis=1).astype(np.uint32)

    return centroids.astype(np.float32), assignments


def _write_sidecar_sections(
    *,
    out_path: Path,
    pack_id: str,
    pack_sha: str,
    source_manifest_digest: str,
    model_id: str,
    resolved_mode: Literal["flat_f16", "ivf_i8", "binary_i8"],
    dim: int,
    n_vecs: int,
    actual_clusters: int,
    ordered_rids: Sequence[Sequence[int]] | None,
    vectors_payload: np.ndarray,
    scales_f16: np.ndarray | None,
    binary_u8: np.ndarray | None,
    centroids_f32: np.ndarray | None,
    cluster_offsets_u32: np.ndarray | None,
    recommended_min_cosine: float | None,
    calibration_mode: str = "none",
    corpus_mean_f32: np.ndarray | None = None,
    corpus_mean_norm_sq: float | None = None,
    corpus_pair_std: float | None = None,
    prebuilt_csr: tuple[np.ndarray, np.ndarray, np.ndarray, int] | None = None,
) -> SemanticSidecarManifest:
    if prebuilt_csr is not None:
        rid_offsets, rids_u32, rid_to_vidx_u32, max_rid = prebuilt_csr
    else:
        assert ordered_rids is not None
        # Flatten CSR mapping from stored vector_idx -> rid(s) in the SQLite pack.
        rid_offsets = np.zeros(n_vecs + 1, dtype=np.uint32)
        flat_rids_list: list[int] = []
        max_rid = 0
        for i, rids in enumerate(ordered_rids):
            for r in rids:
                rid_int = int(r)
                if rid_int < 0 or rid_int >= _MISSING_VIDX:
                    raise VocabularyInputError(
                        "invalid_vectors",
                        f"rid must be in [0, {_MISSING_VIDX - 1}], got {rid_int}",
                    )
                flat_rids_list.append(rid_int)
                if rid_int > max_rid:
                    max_rid = rid_int
            rid_offsets[i + 1] = len(flat_rids_list)
        rids_u32 = np.asarray(flat_rids_list, dtype=np.uint32)

        # Direct O(1) rid -> stored vidx lookup array (built after cluster sorting for ivf_i8!).
        rid_to_vidx_u32 = np.full(max_rid + 1, _MISSING_VIDX, dtype=np.uint32)
        for vidx, rids in enumerate(ordered_rids):
            for r in rids:
                rid_int = int(r)
                if rid_to_vidx_u32[rid_int] == _MISSING_VIDX:
                    rid_to_vidx_u32[rid_int] = vidx

    built_at = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    sections: list[tuple[str, memoryview]] = []
    if centroids_f32 is not None and cluster_offsets_u32 is not None:
        sections.append(("centroids_f32", _as_byte_view(centroids_f32)))
        sections.append(("cluster_offsets_u32", _as_byte_view(cluster_offsets_u32)))
    sections.append(("vectors", _as_byte_view(vectors_payload)))
    if scales_f16 is not None:
        sections.append(("scales_f16", _as_byte_view(scales_f16)))
    if binary_u8 is not None:
        sections.append(("binary_u8", _as_byte_view(binary_u8)))
    sections.append(("rid_offsets_u32", _as_byte_view(rid_offsets)))
    sections.append(("rids_u32", _as_byte_view(rids_u32)))
    sections.append(("rid_to_vidx_u32", _as_byte_view(rid_to_vidx_u32)))
    if calibration_mode == "centered_covariance" and corpus_mean_f32 is not None:
        sections.append(("corpus_mean_f32", _as_byte_view(np.ascontiguousarray(corpus_mean_f32, dtype=np.float32))))

    # Compute deterministic 64-byte aligned offsets with fixed-point header pass.
    base_header: dict[str, Any] = {
        "recordType": "AtlasSemanticSidecar",
        "schemaVersion": SIDECAR_SCHEMA_VERSION,
        "packId": pack_id,
        "packSha256": pack_sha,
        "sourceManifestDigest": source_manifest_digest,
        "modelId": model_id,
        "mode": resolved_mode,
        "dimensions": int(dim),
        "uniqueVectorCount": int(n_vecs),
        "mappedResourceCount": int(rids_u32.size),
        "maxRid": int(max_rid),
        "nClusters": actual_clusters,
        "builtAt": built_at,
        "sections": {},
    }
    if recommended_min_cosine is not None:
        base_header["recommendedMinCosine"] = recommended_min_cosine
    if calibration_mode == "centered_covariance" and corpus_mean_f32 is not None:
        base_header["calibrationMode"] = calibration_mode
        if corpus_mean_norm_sq is not None:
            base_header["corpusMeanNormSq"] = float(corpus_mean_norm_sq)
        if corpus_pair_std is not None:
            base_header["corpusPairStd"] = float(corpus_pair_std)

    header_bytes = b""
    sec_meta: dict[str, dict[str, int]] = {}
    for _ in range(6):
        candidate = dict(base_header, sections=sec_meta)
        header_bytes = json.dumps(candidate, sort_keys=True, separators=(",", ":")).encode("utf-8")
        cursor = _align(len(SIDECAR_MAGIC) + 8 + len(header_bytes))
        new_meta: dict[str, dict[str, int]] = {}
        for name, buf in sections:
            offset = _align(cursor)
            nbytes = len(buf)
            new_meta[name] = {"offset": offset, "nbytes": nbytes}
            cursor = offset + nbytes
        if new_meta == sec_meta:
            break
        sec_meta = new_meta
    else:
        raise VocabularyPackError("build_failed", "sidecar header section offset layout did not converge")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_fd, tmp_name = tempfile.mkstemp(prefix=f".{out_path.name}.", suffix=".tmp", dir=str(out_path.parent))
    os.close(tmp_fd)
    tmp_path = Path(tmp_name)

    try:
        with tmp_path.open("wb") as handle:
            handle.write(SIDECAR_MAGIC)
            handle.write(struct.pack("<Q", len(header_bytes)))
            handle.write(header_bytes)
            for name, buf in sections:
                target_off = sec_meta[name]["offset"]
                pad = target_off - handle.tell()
                if pad > 0:
                    handle.write(b"\x00" * pad)
                handle.write(buf)
        os.chmod(tmp_path, 0o644)
        os.replace(tmp_path, out_path)
    except BaseException:
        tmp_path.unlink(missing_ok=True)
        raise

    sidecar_sha = _sha256_file(out_path)
    return SemanticSidecarManifest(
        sidecar_path=out_path,
        sidecar_sha256=sidecar_sha,
        size_bytes=out_path.stat().st_size,
        pack_id=pack_id,
        pack_sha256=pack_sha,
        source_manifest_digest=source_manifest_digest,
        model_id=model_id,
        mode=resolved_mode,
        dimensions=int(dim),
        unique_vector_count=int(n_vecs),
        mapped_resource_count=int(rids_u32.size),
        n_clusters=actual_clusters,
        built_at=built_at,
        recommended_min_cosine=recommended_min_cosine,
        calibration_mode=calibration_mode,
        corpus_mean_norm_sq=corpus_mean_norm_sq,
        corpus_pair_std=corpus_pair_std,
    )


def build_semantic_sidecar_from_arrays(
    pack_path: Path | str,
    output_path: Path | str,
    *,
    vectors_f16: np.ndarray,
    rids_per_vector: Sequence[Sequence[int]],
    model_id: str,
    mode: Literal["auto", "flat_f16", "ivf_i8", "binary_i8"] = "auto",
    n_clusters: int = 1024,
    ivf_iterations: int = 12,
    seed: int = 42,
    recommended_min_cosine: float | None = None,
    calibration_mode: Literal["auto", "none", "centered_covariance"] = "none",
    calibration_evt_sigma: float = DEFAULT_CALIBRATION_EVT_SIGMA,
) -> SemanticSidecarManifest:
    """Build a sealed ``.vpack`` sidecar directly from in-memory vectors and pack ``rid`` mappings.

    Mutates writable ``float16`` ``vectors_f16`` in-place during bounded-chunk L2
    normalization to keep build peak RSS minimal. Useful both as the core serializer
    for ``build_semantic_sidecar`` and for deterministic unit tests.
    """

    resolved_pack = _validate_regular_input_file(
        pack_path,
        code_symlink="invalid_pack",
        code_missing="missing_pack",
        label="vocabulary pack",
    )
    out_path = _validate_output_path(output_path)
    rec_min_cos = _validate_recommended_min_cosine(recommended_min_cosine, for_input=True)
    req_cal_mode = _validate_calibration_mode(calibration_mode, for_input=True)
    evt_sigma = _validate_calibration_evt_sigma(calibration_evt_sigma)
    n_clusters = _validate_positive_int(n_clusters, code="invalid_n_clusters", name="n_clusters")
    ivf_iterations = _validate_positive_int(ivf_iterations, code="invalid_ivf_iterations", name="ivf_iterations")

    pack_id, source_manifest_digest, _, _ = _read_pack_meta_and_resources(resolved_pack, load_resources=False)
    pack_sha = _sha256_file(resolved_pack)

    arr = np.asarray(vectors_f16, dtype=np.float16)
    if arr.ndim != 2 or arr.shape[0] == 0 or arr.shape[1] == 0:
        raise VocabularyInputError("invalid_vectors", "vectors_f16 must be a non-empty 2D array")
    n_vecs, dim = arr.shape
    if len(rids_per_vector) != n_vecs:
        raise VocabularyInputError("invalid_vectors", "rids_per_vector length must match vector count")
    if not isinstance(model_id, str) or not model_id.strip():
        raise VocabularyInputError("invalid_model", "model_id must be a non-empty string")

    resolved_mode: Literal["flat_f16", "ivf_i8", "binary_i8"]
    if mode == "auto":
        resolved_mode = "flat_f16" if n_vecs <= _FLAT_THRESHOLD else "binary_i8"
    elif mode in ("flat_f16", "ivf_i8", "binary_i8"):
        resolved_mode = mode
    else:
        raise VocabularyInputError("invalid_mode", f"unsupported sidecar mode: {mode!r}")

    if not arr.flags.writeable:
        arr = arr.copy()

    moment_acc = _CorpusMomentAccumulator(dim) if req_cal_mode != "none" else None

    # Normalize vectors in-place to unit L2 length in bounded chunks so dot product == exact cosine
    # without allocating a second full float16 matrix.
    for start in range(0, n_vecs, _CHUNK_ROWS):
        end = min(start + _CHUNK_ROWS, n_vecs)
        chunk_f32 = arr[start:end].astype(np.float32)
        _l2_normalize_rows_inplace(chunk_f32)
        if moment_acc is not None:
            moment_acc.update(chunk_f32)
        arr[start:end] = chunk_f32.astype(np.float16)

    if moment_acc is not None:
        resolved_cal_mode, corpus_mean_f32, corpus_mean_norm_sq, corpus_pair_std, rec_min_cos = moment_acc.finalize(
            requested_mode=req_cal_mode,
            evt_sigma=evt_sigma,
            explicit_recommended_min_cosine=rec_min_cos,
        )
    else:
        resolved_cal_mode = "none"
        corpus_mean_f32 = None
        corpus_mean_norm_sq = None
        corpus_pair_std = None

    centroids_f32: np.ndarray | None = None
    cluster_offsets_u32: np.ndarray | None = None
    vectors_payload: np.ndarray
    scales_f16: np.ndarray | None = None
    binary_u8: np.ndarray | None = None

    if resolved_mode == "ivf_i8":
        centroids_f32, assignments = _train_spherical_ivf(
            arr,
            n_clusters=n_clusters,
            n_iter=ivf_iterations,
            seed=seed,
        )
        k_actual = centroids_f32.shape[0]
        order = np.argsort(assignments, kind="stable")
        sorted_assign = assignments[order]
        counts = np.bincount(sorted_assign, minlength=k_actual).astype(np.uint32)
        cluster_offsets_u32 = np.zeros(k_actual + 1, dtype=np.uint32)
        np.cumsum(counts, out=cluster_offsets_u32[1:])

        # Quantize vectors in cluster-sorted order in bounded chunks.
        vectors_i8 = np.empty((n_vecs, dim), dtype=np.int8)
        scales_f16 = np.empty(n_vecs, dtype=np.float16)
        for start in range(0, n_vecs, _CHUNK_ROWS):
            end = min(start + _CHUNK_ROWS, n_vecs)
            idx_chunk = order[start:end]
            q_chunk, s_chunk = _quantize_symmetric_i8(arr[idx_chunk].astype(np.float32))
            vectors_i8[start:end] = q_chunk
            scales_f16[start:end] = s_chunk
        vectors_payload = vectors_i8
        ordered_rids: Sequence[Sequence[int]] = [rids_per_vector[int(i)] for i in order]
        actual_clusters = int(k_actual)
    elif resolved_mode == "binary_i8":
        # Chunked symmetric int8 quantization + 1-bit sign packing (zero C/platform dependencies).
        n_bytes_bin = (dim + 7) // 8
        vectors_i8 = np.empty((n_vecs, dim), dtype=np.int8)
        scales_f16 = np.empty(n_vecs, dtype=np.float16)
        binary_u8 = np.empty((n_vecs, n_bytes_bin), dtype=np.uint8)
        for start in range(0, n_vecs, _CHUNK_ROWS):
            end = min(start + _CHUNK_ROWS, n_vecs)
            chunk_f32 = arr[start:end].astype(np.float32)
            q_chunk, s_chunk = _quantize_symmetric_i8(chunk_f32)
            vectors_i8[start:end] = q_chunk
            scales_f16[start:end] = s_chunk
            binary_u8[start:end] = np.packbits(chunk_f32 > 0, axis=1)
        vectors_payload = vectors_i8
        ordered_rids = rids_per_vector
        actual_clusters = 0
    else:
        vectors_payload = arr
        ordered_rids = rids_per_vector
        actual_clusters = 0

    return _write_sidecar_sections(
        out_path=out_path,
        pack_id=pack_id,
        pack_sha=pack_sha,
        source_manifest_digest=source_manifest_digest,
        model_id=model_id.strip(),
        resolved_mode=resolved_mode,
        dim=int(dim),
        n_vecs=int(n_vecs),
        actual_clusters=actual_clusters,
        ordered_rids=ordered_rids,
        vectors_payload=vectors_payload,
        scales_f16=scales_f16,
        binary_u8=binary_u8,
        centroids_f32=centroids_f32,
        cluster_offsets_u32=cluster_offsets_u32,
        recommended_min_cosine=rec_min_cos,
        calibration_mode=resolved_cal_mode,
        corpus_mean_f32=corpus_mean_f32,
        corpus_mean_norm_sq=corpus_mean_norm_sq,
        corpus_pair_std=corpus_pair_std,
    )


def _validate_arrow_embeddings_batch(emb_arr: Any, *, n_keep: int) -> int:
    """Validate that an Arrow embeddings batch is non-null, list-typed, numeric, and uniform-width."""

    import pyarrow as pa

    if len(emb_arr) != n_keep:
        raise VocabularyPackError(
            "corrupt_embeddings",
            f"embedding batch length mismatch: expected {n_keep}, got {len(emb_arr)}",
        )
    if emb_arr.null_count != 0:
        raise VocabularyPackError(
            "corrupt_embeddings",
            f"embedding batch contains {emb_arr.null_count} null vector row(s)",
        )
    emb_type = emb_arr.type
    if pa.types.is_fixed_size_list(emb_type):
        dim = int(emb_type.list_size)
        if dim <= 0:
            raise VocabularyPackError(
                "corrupt_embeddings",
                f"embedding vectors have non-positive dimension: {dim}",
            )
    elif pa.types.is_list(emb_type) or pa.types.is_large_list(emb_type):
        offsets = emb_arr.offsets.to_numpy(zero_copy_only=False)
        widths = np.diff(offsets)
        if widths.size != n_keep or int(widths[0]) <= 0 or not bool(np.all(widths == widths[0])):
            raise VocabularyPackError(
                "corrupt_embeddings",
                "embedding vectors have empty or ragged list lengths within batch",
            )
        dim = int(widths[0])
    elif hasattr(pa.types, "is_list_view") and (
        pa.types.is_list_view(emb_type) or pa.types.is_large_list_view(emb_type)
    ):
        import pyarrow.compute as pc

        widths = pc.list_value_length(emb_arr).to_numpy(zero_copy_only=False)
        if widths.size != n_keep or int(widths[0]) <= 0 or not bool(np.all(widths == widths[0])):
            raise VocabularyPackError(
                "corrupt_embeddings",
                "embedding vectors have empty or ragged list lengths within batch",
            )
        dim = int(widths[0])
    else:
        raise VocabularyPackError(
            "corrupt_embeddings",
            f"embedding column must be an Arrow list array, got {emb_type}",
        )
    val_type = emb_type.value_type
    if not (pa.types.is_floating(val_type) or pa.types.is_integer(val_type)):
        raise VocabularyPackError(
            "corrupt_embeddings",
            f"embedding vector elements must be numeric, got {val_type}",
        )
    return dim


def build_semantic_sidecar(
    pack_path: Path | str,
    embeddings_dir: Path | str,
    output_path: Path | str,
    *,
    model_id: str = "BAAI/bge-m3",
    mode: Literal["auto", "flat_f16", "ivf_i8", "binary_i8"] = "auto",
    n_clusters: int = 1024,
    ivf_iterations: int = 12,
    seed: int = 42,
    recommended_min_cosine: float | None = None,
    calibration_mode: Literal["auto", "none", "centered_covariance"] = "auto",
    calibration_evt_sigma: float = DEFAULT_CALIBRATION_EVT_SIGMA,
) -> SemanticSidecarManifest:
    """Compile a Tier-1 ``.vpack`` sidecar from a compiled SQLite Pack and deduplicated BGE-M3 Parquet."""

    import duckdb

    if not isinstance(model_id, str) or not model_id.strip():
        raise VocabularyInputError("invalid_model", "model_id must be a non-empty string")
    if mode not in ("auto", "flat_f16", "ivf_i8", "binary_i8"):
        raise VocabularyInputError("invalid_mode", f"unsupported sidecar mode: {mode!r}")
    rec_min_cos = _validate_recommended_min_cosine(recommended_min_cosine, for_input=True)
    req_cal_mode = _validate_calibration_mode(calibration_mode, for_input=True)
    evt_sigma = _validate_calibration_evt_sigma(calibration_evt_sigma)
    n_clusters = _validate_positive_int(n_clusters, code="invalid_n_clusters", name="n_clusters")
    ivf_iterations = _validate_positive_int(ivf_iterations, code="invalid_ivf_iterations", name="ivf_iterations")

    resolved_pack = _validate_regular_input_file(
        pack_path,
        code_symlink="invalid_pack",
        code_missing="missing_pack",
        label="vocabulary pack",
    )
    out_path = _validate_output_path(output_path)
    emb_root = _validate_regular_input_dir(
        embeddings_dir,
        code="invalid_embeddings",
        label="embeddings directory",
    )
    emb_res = emb_root / "resources.parquet"
    if emb_res.is_symlink() or not emb_res.is_file():
        raise VocabularyPackError("invalid_embeddings", f"missing or unsafe embeddings resources table: {emb_res}")
    emb_vecs_dir = emb_root / "vectors"
    if emb_vecs_dir.is_symlink() or not emb_vecs_dir.is_dir():
        raise VocabularyPackError("invalid_embeddings", f"missing or unsafe embeddings vectors directory: {emb_vecs_dir}")
    part_files = sorted(emb_vecs_dir.glob("part-*.parquet"))
    if not part_files:
        raise VocabularyPackError("invalid_embeddings", f"no vector parquet parts found under: {emb_vecs_dir}")
    for part in part_files:
        if part.is_symlink() or not part.is_file():
            raise VocabularyPackError("invalid_embeddings", f"unsafe vector parquet part: {part}")
    emb_vecs_glob = str(emb_vecs_dir / "part-*.parquet")

    pack_id, source_manifest_digest, schemes, rid_by_key = _read_pack_meta_and_resources(
        resolved_pack,
        load_resources=True,
    )
    if not rid_by_key:
        raise VocabularyPackError("corrupt_pack", "vocabulary pack contains no labeled resources")
    if not schemes:
        raise VocabularyPackError("corrupt_pack", "vocabulary pack declares no schemes")

    schemes_sql = ", ".join("'" + s.replace("'", "''") + "'" for s in schemes)
    con_duck = duckdb.connect(":memory:")
    vectors_f16: np.ndarray | None = None
    vectors_i8: np.ndarray | None = None
    scales_f16: np.ndarray | None = None
    binary_u8: np.ndarray | None = None
    filtered_rids: list[list[int]] = []
    write_pos = 0
    stream_binary_i8 = False
    moment_acc: _CorpusMomentAccumulator | None = None
    try:
        # 1. Stream (resource_id, release, input_sha256) for schemes present in the pack.
        sha_to_rids: dict[str, list[int]] = defaultdict(list)
        res_cur = con_duck.execute(
            f"""
            SELECT resource_id, release, input_sha256
            FROM read_parquet('{str(emb_res).replace("'", "''")}')
            WHERE scheme IN ({schemes_sql})
            """
        )
        while True:
            rows = res_cur.fetchmany(50_000)
            if not rows:
                break
            for res_id, rel_uri, sha in rows:
                rid = rid_by_key.get((res_id, rel_uri))
                if rid is not None:
                    sha_to_rids[sha].append(rid)
        del rid_by_key

        if not sha_to_rids:
            raise VocabularyPackError("invalid_embeddings", "no pack resources matched the embeddings directory")

        max_vecs = len(sha_to_rids)
        stream_binary_i8 = mode == "binary_i8" or (mode == "auto" and max_vecs > _FLAT_THRESHOLD)

        # 2. Stream unique vectors via Arrow RecordBatchReader directly into the target
        #    quantized buffers (avoiding holding float32 + float16 + int8 + binary simultaneously).
        vec_cur = con_duck.execute(
            f"""
            WITH scoped AS (
                SELECT DISTINCT input_sha256
                FROM read_parquet('{str(emb_res).replace("'", "''")}')
                WHERE scheme IN ({schemes_sql})
            )
            SELECT v.input_sha256, v.embedding
            FROM scoped s
            JOIN read_parquet('{emb_vecs_glob.replace("'", "''")}') v USING (input_sha256)
            ORDER BY v.input_sha256
            """
        )
        reader = (
            vec_cur.to_arrow_reader(batch_size=_CHUNK_ROWS)
            if hasattr(vec_cur, "to_arrow_reader")
            else vec_cur.fetch_record_batch(rows_per_batch=_CHUNK_ROWS)
        )
        for batch in reader:
            if batch.num_rows == 0:
                continue
            shas = batch.column(0).to_pylist()
            keep_idx: list[int] = []
            for idx, sha in enumerate(shas):
                rids = sha_to_rids.pop(sha, None)
                if rids:
                    keep_idx.append(idx)
                    filtered_rids.append(sorted(set(rids)))
            if not keep_idx:
                continue
            emb_arr = batch.column(1)
            if len(keep_idx) != batch.num_rows:
                emb_arr = emb_arr.take(keep_idx)
            n_keep = len(keep_idx)
            dim = _validate_arrow_embeddings_batch(emb_arr, n_keep=n_keep)
            flat_arr = emb_arr.flatten()
            if flat_arr.null_count != 0:
                raise VocabularyPackError(
                    "corrupt_embeddings",
                    f"embedding vectors contain {flat_arr.null_count} null coordinate value(s)",
                )
            flat = flat_arr.to_numpy(zero_copy_only=False)
            if flat.size != n_keep * dim:
                raise VocabularyPackError(
                    "corrupt_embeddings",
                    f"flattened embedding element count ({flat.size}) does not match {n_keep} x {dim}",
                )
            chunk_f32 = np.array(flat, dtype=np.float32, copy=True).reshape(n_keep, dim)
            _l2_normalize_rows_inplace(chunk_f32)
            if stream_binary_i8:
                if vectors_i8 is None:
                    n_bytes_bin = (dim + 7) // 8
                    vectors_i8 = np.empty((max_vecs, dim), dtype=np.int8)
                    scales_f16 = np.empty(max_vecs, dtype=np.float16)
                    binary_u8 = np.empty((max_vecs, n_bytes_bin), dtype=np.uint8)
                    if req_cal_mode != "none":
                        moment_acc = _CorpusMomentAccumulator(dim)
                elif dim != vectors_i8.shape[1]:
                    raise VocabularyPackError(
                        "corrupt_embeddings",
                        f"inconsistent embedding dimension: expected {vectors_i8.shape[1]}, got {dim}",
                    )
                assert scales_f16 is not None and binary_u8 is not None
                if moment_acc is not None:
                    moment_acc.update(chunk_f32)
                q_chunk, s_chunk = _quantize_symmetric_i8(chunk_f32)
                vectors_i8[write_pos : write_pos + n_keep] = q_chunk
                scales_f16[write_pos : write_pos + n_keep] = s_chunk
                binary_u8[write_pos : write_pos + n_keep] = np.packbits(chunk_f32 > 0, axis=1)
                del q_chunk, s_chunk
            else:
                if vectors_f16 is None:
                    vectors_f16 = np.empty((max_vecs, dim), dtype=np.float16)
                elif dim != vectors_f16.shape[1]:
                    raise VocabularyPackError(
                        "corrupt_embeddings",
                        f"inconsistent embedding dimension: expected {vectors_f16.shape[1]}, got {dim}",
                    )
                vectors_f16[write_pos : write_pos + n_keep] = chunk_f32.astype(np.float16)
            write_pos += n_keep
            del chunk_f32, flat, flat_arr, emb_arr
        del sha_to_rids
    except duckdb.Error as exc:
        raise VocabularyPackError("invalid_embeddings", f"failed to read embeddings parquet: {exc}") from exc
    finally:
        # Close DuckDB immediately after streaming Arrow chunks so all engine memory is freed.
        con_duck.close()

    if write_pos == 0:
        raise VocabularyPackError("invalid_embeddings", "no embedding vectors matched labeled pack resources")

    if stream_binary_i8:
        assert vectors_i8 is not None and scales_f16 is not None and binary_u8 is not None
        if write_pos < vectors_i8.shape[0]:
            vectors_i8 = vectors_i8[:write_pos]
            scales_f16 = scales_f16[:write_pos]
            binary_u8 = binary_u8[:write_pos]
        if moment_acc is not None:
            resolved_cal_mode, corpus_mean_f32, corpus_mean_norm_sq, corpus_pair_std, rec_min_cos = moment_acc.finalize(
                requested_mode=req_cal_mode,
                evt_sigma=evt_sigma,
                explicit_recommended_min_cosine=rec_min_cos,
            )
        else:
            resolved_cal_mode = "none"
            corpus_mean_f32 = None
            corpus_mean_norm_sq = None
            corpus_pair_std = None
        pack_sha = _sha256_file(resolved_pack)
        return _write_sidecar_sections(
            out_path=out_path,
            pack_id=pack_id,
            pack_sha=pack_sha,
            source_manifest_digest=source_manifest_digest,
            model_id=model_id.strip(),
            resolved_mode="binary_i8",
            dim=int(vectors_i8.shape[1]),
            n_vecs=write_pos,
            actual_clusters=0,
            ordered_rids=filtered_rids,
            vectors_payload=vectors_i8,
            scales_f16=scales_f16,
            binary_u8=binary_u8,
            centroids_f32=None,
            cluster_offsets_u32=None,
            recommended_min_cosine=rec_min_cos,
            calibration_mode=resolved_cal_mode,
            corpus_mean_f32=corpus_mean_f32,
            corpus_mean_norm_sq=corpus_mean_norm_sq,
            corpus_pair_std=corpus_pair_std,
        )

    assert vectors_f16 is not None
    if write_pos < vectors_f16.shape[0]:
        vectors_f16 = vectors_f16[:write_pos]

    return build_semantic_sidecar_from_arrays(
        resolved_pack,
        out_path,
        vectors_f16=vectors_f16,
        rids_per_vector=filtered_rids,
        model_id=model_id,
        mode=mode,
        n_clusters=n_clusters,
        ivf_iterations=ivf_iterations,
        seed=seed,
        recommended_min_cosine=rec_min_cos,
        calibration_mode=calibration_mode,
        calibration_evt_sigma=evt_sigma,
    )


def calibrate_semantic_sidecar(
    source_sidecar_path: Path | str,
    output_path: Path | str,
    *,
    calibration_evt_sigma: float = DEFAULT_CALIBRATION_EVT_SIGMA,
    recommended_min_cosine: float | None = None,
) -> SemanticSidecarManifest:
    """Attach exact centered-covariance corpus moments & EVT OOD threshold to an existing ``.vpack``.

    Streams dequantized vectors from ``source_sidecar_path`` in bounded chunks with zero
    re-embedding, computes exact corpus mean ``mu`` (``D * 4`` bytes) and analytical pair
    std ``sigma_pair = sqrt(Tr(Sigma^2)) / (1 - ||mu||^2)``, and atomically writes a
    calibrated ``.vpack`` preserving all existing vector, index, and ``rid`` sections.
    """

    evt_sigma = _validate_calibration_evt_sigma(calibration_evt_sigma)
    explicit_rec = _validate_recommended_min_cosine(recommended_min_cosine, for_input=True)
    out_path = _validate_output_path(output_path)

    with AtlasSemanticSidecar.open(source_sidecar_path, use_calibration=False) as src:
        n_vecs = src._n_vecs
        dim = src._dim
        if n_vecs <= 0:
            raise VocabularyInputError("invalid_vectors", "cannot calibrate an empty semantic sidecar")

        moment_acc = _CorpusMomentAccumulator(dim)
        if src._mode == "flat_f16":
            assert src._vectors_f16 is not None
            for start in range(0, n_vecs, _CHUNK_ROWS):
                end = min(start + _CHUNK_ROWS, n_vecs)
                blk = src._vectors_f16[start:end].astype(np.float32)
                _l2_normalize_rows_inplace(blk)
                moment_acc.update(blk)
            vectors_payload: np.ndarray = src._vectors_f16
        else:
            assert src._vectors_i8 is not None and src._scales_f16 is not None
            for start in range(0, n_vecs, _CHUNK_ROWS):
                end = min(start + _CHUNK_ROWS, n_vecs)
                blk = src._vectors_i8[start:end].astype(np.float32) * src._scales_f16[start:end, None].astype(np.float32)
                _l2_normalize_rows_inplace(blk)
                moment_acc.update(blk)
            vectors_payload = src._vectors_i8

        resolved_cal_mode, corpus_mean_f32, corpus_mean_norm_sq, corpus_pair_std, final_rec = moment_acc.finalize(
            requested_mode="centered_covariance",
            evt_sigma=evt_sigma,
            explicit_recommended_min_cosine=explicit_rec,
        )
        mode_lit: Literal["flat_f16", "ivf_i8", "binary_i8"]
        if src._mode == "flat_f16":
            mode_lit = "flat_f16"
        elif src._mode == "ivf_i8":
            mode_lit = "ivf_i8"
        else:
            mode_lit = "binary_i8"

        return _write_sidecar_sections(
            out_path=out_path,
            pack_id=src._pack_id,
            pack_sha=src._pack_sha256,
            source_manifest_digest=src._source_manifest_digest,
            model_id=src._model_id,
            resolved_mode=mode_lit,
            dim=dim,
            n_vecs=n_vecs,
            actual_clusters=src._n_clusters,
            ordered_rids=None,
            vectors_payload=vectors_payload,
            scales_f16=src._scales_f16,
            binary_u8=src._binary_u8,
            centroids_f32=src._centroids_f32,
            cluster_offsets_u32=src._cluster_offsets,
            recommended_min_cosine=final_rec,
            calibration_mode=resolved_cal_mode,
            corpus_mean_f32=corpus_mean_f32,
            corpus_mean_norm_sq=corpus_mean_norm_sq,
            corpus_pair_std=corpus_pair_std,
            prebuilt_csr=(src._rid_offsets, src._rids, src._rid_to_vidx, src._max_rid),
        )


def _extract_sparse_rids_u64(
    mask_u8: np.ndarray,
    *,
    max_words: int,
) -> tuple[np.ndarray | None, bool]:
    """Scan a dense uint8 mask via 8-byte aligned uint64 words when sparse.

    Returns ``(rids_array, True)`` if the mask has ``<= max_words`` non-zero 8-byte
    words (ultra-fast `<0.2 ms` path at low selectivity), or ``(None, False)`` when
    selectivity is high enough that dense boolean indexing is faster.
    """

    n = int(mask_u8.size)
    if n == 0:
        return np.empty(0, dtype=np.intp), True
    if n < 16 or not mask_u8.flags.c_contiguous:
        return np.flatnonzero(mask_u8), True

    lead = (8 - (mask_u8.ctypes.data % 8)) % 8
    n_mid = ((n - lead) // 8) * 8
    mid_end = lead + n_mid
    mid_u64 = mask_u8[lead:mid_end].view(np.uint64)
    nz_words = np.flatnonzero(mid_u64)
    if nz_words.size > max_words:
        return None, False

    parts: list[np.ndarray] = []
    if lead > 0:
        lead_nz = np.flatnonzero(mask_u8[:lead])
        if lead_nz.size:
            parts.append(lead_nz)
    if nz_words.size > 0:
        cand_off = (lead + nz_words[:, None] * 8 + _U64_BYTE_OFFSETS).ravel()
        mid_nz = cand_off[mask_u8[cand_off] != 0]
        if mid_nz.size:
            parts.append(mid_nz)
    if mid_end < n:
        tail_nz = np.flatnonzero(mask_u8[mid_end:]) + mid_end
        if tail_nz.size:
            parts.append(tail_nz)
    if not parts:
        return np.empty(0, dtype=np.intp), True
    if len(parts) == 1:
        return parts[0], True
    return np.concatenate(parts), True


class AtlasSemanticSidecar:
    """Zero-copy memory-mapped Tier-1 semantic index implementing ``SemanticIndex``."""

    def __init__(
        self,
        *,
        path: Path,
        file_obj: Any,
        mm: mmap.mmap,
        header: dict[str, Any],
        rerank_top_r: int = _DEFAULT_RERANK_TOP_R,
        header_end: int = 0,
        use_calibration: bool = True,
    ) -> None:
        if isinstance(rerank_top_r, bool) or not isinstance(rerank_top_r, int) or rerank_top_r < 1:
            raise VocabularyInputError("invalid_rerank_top_r", "rerank_top_r must be a positive integer")
        self._path = path
        self._file = file_obj
        self._mm = mm
        self._state_lock = threading.Lock()
        self._active_queries = 0
        self._closing = False
        self._finalizing = False
        self._closed = False
        self._header = header
        self._rerank_top_r = rerank_top_r
        self._use_calibration = bool(use_calibration)
        self._calibration_mode: str = "none"
        self._corpus_mean_f32: np.ndarray | None = None
        self._corpus_mean_norm_sq: float | None = None
        self._corpus_pair_std: float | None = None
        self._corpus_res_var: float = 1.0
        self._vectors_f16: np.ndarray | None = None
        self._vectors_i8: np.ndarray | None = None
        self._scales_f16: np.ndarray | None = None
        self._centroids_f32: np.ndarray | None = None
        self._cluster_offsets: np.ndarray | None = None
        self._binary_u8: np.ndarray | None = None
        self._rid_offsets: np.ndarray = np.empty(0, dtype=np.uint32)
        self._rids: np.ndarray = np.empty(0, dtype=np.uint32)
        self._rid_to_vidx: np.ndarray = np.empty(0, dtype=np.uint32)
        self._vidx_of_rids: np.ndarray | None = None
        self._unique_rid_per_vidx: bool = True
        self._cache_lock = threading.Lock()
        self._bytes_mask_cache: OrderedDict[bytes, tuple[np.ndarray | None, np.ndarray | None, int]] = OrderedDict()

        def _require_int_field(mapping: dict[str, Any], key: str) -> int:
            val = mapping[key]
            if isinstance(val, bool) or not isinstance(val, int):
                raise TypeError(f"header field {key!r} must be an integer")
            return val

        def _require_str_field(mapping: dict[str, Any], key: str, *, allow_empty: bool = False) -> str:
            val = mapping[key]
            if not isinstance(val, str):
                raise TypeError(f"header field {key!r} must be a string")
            if not allow_empty and not val.strip():
                raise ValueError(f"header field {key!r} must be a non-empty string")
            return val

        try:
            if header.get("recordType") != _SIDECAR_RECORD_TYPE:
                raise VocabularyPackError(
                    "corrupt_sidecar",
                    f"expected {_SIDECAR_RECORD_TYPE} recordType, got {header.get('recordType')!r}",
                )
            mode = _require_str_field(header, "mode")
            self._mode: str = mode
            if self._mode not in ("flat_f16", "ivf_i8", "binary_i8"):
                raise VocabularyPackError("unsupported_sidecar", f"unsupported sidecar mode: {self._mode!r}")

            if isinstance(header_end, bool) or not isinstance(header_end, int) or header_end < 0:
                raise TypeError("header_end must be a non-negative integer")

            self._dim: int = _require_int_field(header, "dimensions")
            self._n_vecs: int = _require_int_field(header, "uniqueVectorCount")
            self._n_clusters: int = _require_int_field(header, "nClusters")
            self._max_rid: int = _require_int_field(header, "maxRid")
            mapped_count: int = _require_int_field(header, "mappedResourceCount")
            self._pack_id: str = _require_str_field(header, "packId", allow_empty=True)
            self._pack_sha256: str = _require_str_field(header, "packSha256")
            self._source_manifest_digest: str = _require_str_field(header, "sourceManifestDigest")
            self._model_id: str = _require_str_field(header, "modelId")
            self._recommended_min_cosine: float | None = _validate_recommended_min_cosine(
                header.get("recommendedMinCosine"),
                for_input=False,
            )
            self._calibration_mode = _validate_calibration_mode(
                header.get("calibrationMode"),
                for_input=False,
            )
            raw_mean_norm_sq = header.get("corpusMeanNormSq")
            if raw_mean_norm_sq is not None:
                if isinstance(raw_mean_norm_sq, bool) or not isinstance(raw_mean_norm_sq, (int, float)):
                    raise VocabularyPackError(
                        "corrupt_sidecar",
                        "corpusMeanNormSq header value must be a finite number",
                    )
                f_mnsq = float(raw_mean_norm_sq)
                if not math.isfinite(f_mnsq) or f_mnsq < 0.0 or f_mnsq > 1.0 - _CALIBRATION_MIN_RESIDUAL_VAR:
                    raise VocabularyPackError(
                        "corrupt_sidecar",
                        f"corpusMeanNormSq out of valid range [0.0, {1.0 - _CALIBRATION_MIN_RESIDUAL_VAR}]: {f_mnsq!r}",
                    )
                self._corpus_mean_norm_sq = f_mnsq
            raw_pair_std = header.get("corpusPairStd")
            if raw_pair_std is not None:
                if isinstance(raw_pair_std, bool) or not isinstance(raw_pair_std, (int, float)):
                    raise VocabularyPackError(
                        "corrupt_sidecar",
                        "corpusPairStd header value must be a finite positive number",
                    )
                f_pstd = float(raw_pair_std)
                if not math.isfinite(f_pstd) or f_pstd <= 0.0:
                    raise VocabularyPackError(
                        "corrupt_sidecar",
                        f"corpusPairStd must be finite and positive, got {f_pstd!r}",
                    )
                self._corpus_pair_std = f_pstd
            secs = header["sections"]
            if not isinstance(secs, dict):
                raise TypeError("sections must be a mapping")
            if self._dim <= 0 or self._n_vecs < 0 or self._n_clusters < 0 or self._max_rid < 0 or mapped_count < 0:
                raise ValueError("negative or invalid sidecar dimension/count")
            if self._mode == "ivf_i8" and self._n_clusters <= 0:
                raise ValueError("ivf_i8 sidecar requires positive nClusters")

            mm_len = len(mm)

            for sec_name, sec_meta in secs.items():
                if not isinstance(sec_meta, dict):
                    raise TypeError(f"section {sec_name!r} metadata must be a mapping")
                sec_offset = _require_int_field(sec_meta, "offset")
                sec_nbytes = _require_int_field(sec_meta, "nbytes")
                if sec_offset < header_end or sec_nbytes < 0 or sec_offset + sec_nbytes > mm_len:
                    raise ValueError(
                        f"section {sec_name!r} bounds invalid "
                        f"(offset={sec_offset}, header_end={header_end}, nbytes={sec_nbytes}, file={mm_len})"
                    )

            def _checked_offset(name: str, expected_bytes: int) -> int:
                meta = secs[name]
                if not isinstance(meta, dict):
                    raise TypeError(f"section {name!r} metadata must be a mapping")
                offset = _require_int_field(meta, "offset")
                nbytes = _require_int_field(meta, "nbytes")
                if offset < header_end or nbytes != expected_bytes or offset + expected_bytes > mm_len:
                    raise ValueError(
                        f"section {name!r} bounds invalid "
                        f"(offset={offset}, header_end={header_end}, nbytes={nbytes}, expected={expected_bytes}, file={mm_len})"
                    )
                return offset

            # Validate ALL section offsets and byte ranges BEFORE creating any np.frombuffer views.
            off_rid_offsets = _checked_offset("rid_offsets_u32", (self._n_vecs + 1) * 4)
            off_rids = _checked_offset("rids_u32", mapped_count * 4)
            off_rid_to_vidx = _checked_offset("rid_to_vidx_u32", (self._max_rid + 1) * 4)

            if self._mode == "flat_f16":
                off_vecs = _checked_offset("vectors", self._n_vecs * self._dim * 2)
            elif self._mode == "ivf_i8":
                off_centroids = _checked_offset("centroids_f32", self._n_clusters * self._dim * 4)
                off_cluster_offsets = _checked_offset("cluster_offsets_u32", (self._n_clusters + 1) * 4)
                off_vecs = _checked_offset("vectors", self._n_vecs * self._dim)
                off_scales = _checked_offset("scales_f16", self._n_vecs * 2)
            else:
                n_bytes_bin = (self._dim + 7) // 8
                off_vecs = _checked_offset("vectors", self._n_vecs * self._dim)
                off_scales = _checked_offset("scales_f16", self._n_vecs * 2)
                off_binary = _checked_offset("binary_u8", self._n_vecs * n_bytes_bin)

            off_corpus_mean: int | None = None
            if self._calibration_mode == "centered_covariance":
                off_corpus_mean = _checked_offset("corpus_mean_f32", self._dim * 4)
        except VocabularyPackError:
            raise
        except (KeyError, TypeError, ValueError) as exc:
            raise VocabularyPackError("corrupt_sidecar", f"invalid semantic sidecar header/sections: {exc}") from exc

        try:
            self._rid_offsets = np.frombuffer(
                mm,
                dtype=np.uint32,
                count=self._n_vecs + 1,
                offset=off_rid_offsets,
            )
            self._rids = np.frombuffer(
                mm,
                dtype=np.uint32,
                count=mapped_count,
                offset=off_rids,
            )
            self._rid_to_vidx = np.frombuffer(
                mm,
                dtype=np.uint32,
                count=self._max_rid + 1,
                offset=off_rid_to_vidx,
            )
            if self._mode == "flat_f16":
                self._vectors_f16 = np.frombuffer(
                    mm,
                    dtype=np.float16,
                    count=self._n_vecs * self._dim,
                    offset=off_vecs,
                ).reshape(self._n_vecs, self._dim)
            elif self._mode == "ivf_i8":
                self._centroids_f32 = np.frombuffer(
                    mm,
                    dtype=np.float32,
                    count=self._n_clusters * self._dim,
                    offset=off_centroids,
                ).reshape(self._n_clusters, self._dim)
                self._cluster_offsets = np.frombuffer(
                    mm,
                    dtype=np.uint32,
                    count=self._n_clusters + 1,
                    offset=off_cluster_offsets,
                )
                self._vectors_i8 = np.frombuffer(
                    mm,
                    dtype=np.int8,
                    count=self._n_vecs * self._dim,
                    offset=off_vecs,
                ).reshape(self._n_vecs, self._dim)
                self._scales_f16 = np.frombuffer(
                    mm,
                    dtype=np.float16,
                    count=self._n_vecs,
                    offset=off_scales,
                )
            else:
                # binary_i8
                self._vectors_i8 = np.frombuffer(
                    mm,
                    dtype=np.int8,
                    count=self._n_vecs * self._dim,
                    offset=off_vecs,
                ).reshape(self._n_vecs, self._dim)
                self._scales_f16 = np.frombuffer(
                    mm,
                    dtype=np.float16,
                    count=self._n_vecs,
                    offset=off_scales,
                )
                self._binary_u8 = np.frombuffer(
                    mm,
                    dtype=np.uint8,
                    count=self._n_vecs * n_bytes_bin,
                    offset=off_binary,
                ).reshape(self._n_vecs, n_bytes_bin)

            if off_corpus_mean is not None:
                self._corpus_mean_f32 = np.frombuffer(
                    mm,
                    dtype=np.float32,
                    count=self._dim,
                    offset=off_corpus_mean,
                )
                if not bool(np.all(np.isfinite(self._corpus_mean_f32))):
                    raise VocabularyPackError(
                        "corrupt_sidecar",
                        "corpus_mean_f32 contains non-finite coordinate values",
                    )
                mu64 = self._corpus_mean_f32.astype(np.float64)
                actual_norm_sq = float(np.dot(mu64, mu64))
                if not math.isfinite(actual_norm_sq) or actual_norm_sq > 1.0 - _CALIBRATION_MIN_RESIDUAL_VAR:
                    raise VocabularyPackError(
                        "corrupt_sidecar",
                        f"corpus_mean_f32 squared norm {actual_norm_sq!r} leaves insufficient residual variance",
                    )
                if self._corpus_mean_norm_sq is None:
                    self._corpus_mean_norm_sq = actual_norm_sq
                self._corpus_res_var = float(1.0 - actual_norm_sq)

            # Strict open-time structural bounds validation (fail-closed before serving any query).
            if self._rid_offsets.size != self._n_vecs + 1:
                raise VocabularyPackError("corrupt_sidecar", "rid_offsets length mismatch")
            if int(self._rid_offsets[0]) != 0:
                raise VocabularyPackError(
                    "corrupt_sidecar",
                    f"rid_offsets[0] must be 0, got {int(self._rid_offsets[0])}",
                )
            if self._rid_offsets.size > 1 and not bool(np.all(self._rid_offsets[1:] >= self._rid_offsets[:-1])):
                raise VocabularyPackError("corrupt_sidecar", "rid_offsets is not monotonically non-decreasing")
            if int(self._rid_offsets[-1]) > mapped_count:
                raise VocabularyPackError(
                    "corrupt_sidecar",
                    f"rid_offsets[-1] ({int(self._rid_offsets[-1])}) exceeds mappedResourceCount ({mapped_count})",
                )
            if mapped_count > 0 and int(self._rids.max()) > self._max_rid:
                raise VocabularyPackError(
                    "corrupt_sidecar",
                    f"rids contains entry ({int(self._rids.max())}) exceeding maxRid ({self._max_rid})",
                )

            if self._rid_to_vidx.size != self._max_rid + 1:
                raise VocabularyPackError("corrupt_sidecar", "rid_to_vidx length mismatch")
            if not bool(np.all((self._rid_to_vidx == _MISSING_VIDX) | (self._rid_to_vidx < self._n_vecs))):
                raise VocabularyPackError(
                    "corrupt_sidecar",
                    "rid_to_vidx contains out-of-range vector index",
                )

            if self._mode == "ivf_i8":
                assert self._cluster_offsets is not None
                if self._cluster_offsets.size != self._n_clusters + 1:
                    raise VocabularyPackError("corrupt_sidecar", "cluster_offsets length mismatch")
                if int(self._cluster_offsets[0]) != 0:
                    raise VocabularyPackError(
                        "corrupt_sidecar",
                        f"cluster_offsets[0] must be 0, got {int(self._cluster_offsets[0])}",
                    )
                if self._cluster_offsets.size > 1 and not bool(
                    np.all(self._cluster_offsets[1:] >= self._cluster_offsets[:-1])
                ):
                    raise VocabularyPackError(
                        "corrupt_sidecar",
                        "cluster_offsets is not monotonically non-decreasing",
                    )
                if int(self._cluster_offsets[-1]) != self._n_vecs:
                    raise VocabularyPackError(
                        "corrupt_sidecar",
                        f"cluster_offsets[-1] ({int(self._cluster_offsets[-1])}) must equal uniqueVectorCount ({self._n_vecs})",
                    )

            if mapped_count > 0:
                n_mapped_lookup = int(np.count_nonzero(self._rid_to_vidx != _MISSING_VIDX))
                self._unique_rid_per_vidx = (
                    n_mapped_lookup == mapped_count
                    and int(self._rid_offsets[-1]) == mapped_count
                    and bool(np.all(self._rid_offsets[1:] > self._rid_offsets[:-1]))
                    and bool(np.all(self._rid_to_vidx[self._rids] != _MISSING_VIDX))
                )
            else:
                self._unique_rid_per_vidx = True
        except BaseException:
            # Release ALL mmap-backed NumPy views before propagating so open() can close mmap cleanly.
            self._release_views()
            raise

    def _release_views(self) -> None:
        self._vectors_f16 = None
        self._vectors_i8 = None
        self._scales_f16 = None
        self._centroids_f32 = None
        self._cluster_offsets = None
        self._binary_u8 = None
        self._corpus_mean_f32 = None
        self._rid_offsets = None  # type: ignore[assignment]
        self._rids = None  # type: ignore[assignment]
        self._rid_to_vidx = None  # type: ignore[assignment]
        self._vidx_of_rids = None
        with self._cache_lock:
            self._bytes_mask_cache.clear()

    @classmethod
    def open(
        cls,
        sidecar_path: Path | str,
        *,
        trusted_sidecar_digest: str | None = None,
        rerank_top_r: int = _DEFAULT_RERANK_TOP_R,
        use_calibration: bool = True,
    ) -> AtlasSemanticSidecar:
        raw_path = Path(sidecar_path)
        _reject_symlink_path(raw_path, "semantic sidecar", error_code="invalid_sidecar")
        try:
            resolved = raw_path.resolve(strict=True)
        except OSError as exc:
            raise VocabularyPackError("missing_sidecar", f"semantic sidecar not found: {sidecar_path}") from exc

        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
        try:
            fd = os.open(resolved, flags)
        except OSError as exc:
            if exc.errno == errno.ELOOP:
                raise VocabularyPackError("invalid_sidecar", "semantic sidecar path must not be a symlink") from exc
            if exc.errno == errno.EISDIR:
                raise VocabularyPackError("invalid_sidecar", f"semantic sidecar is not a regular file: {resolved}") from exc
            raise VocabularyPackError("missing_sidecar", f"failed to open semantic sidecar: {exc}") from exc
        try:
            st = os.fstat(fd)
            if not stat.S_ISREG(st.st_mode):
                raise VocabularyPackError("invalid_sidecar", f"semantic sidecar is not a regular file: {resolved}")
            file_obj = os.fdopen(fd, "rb")
        except BaseException:
            os.close(fd)
            raise
        mm: mmap.mmap | None = None
        try:
            if st.st_size == 0:
                if trusted_sidecar_digest is not None:
                    norm = trusted_sidecar_digest.strip().lower()
                    if not norm.startswith("sha256:"):
                        norm = f"sha256:{norm}"
                    empty_sha = f"sha256:{hashlib.sha256(b'').hexdigest()}"
                    if empty_sha != norm:
                        raise VocabularyPackError("invalid_digest", "semantic sidecar digest differs from external pin")
                raise VocabularyPackError("corrupt_sidecar", "semantic sidecar file is empty")
            mm = mmap.mmap(file_obj.fileno(), 0, access=mmap.ACCESS_READ)
            if trusted_sidecar_digest is not None:
                norm = trusted_sidecar_digest.strip().lower()
                if not norm.startswith("sha256:"):
                    norm = f"sha256:{norm}"
                if _sha256_mmap(mm) != norm:
                    raise VocabularyPackError("invalid_digest", "semantic sidecar digest differs from external pin")
            if len(mm) < len(SIDECAR_MAGIC) + 8 or mm[: len(SIDECAR_MAGIC)] != SIDECAR_MAGIC:
                raise VocabularyPackError("corrupt_sidecar", "invalid semantic sidecar magic header")
            header_len = struct.unpack("<Q", mm[len(SIDECAR_MAGIC) : len(SIDECAR_MAGIC) + 8])[0]
            if header_len == 0:
                raise VocabularyPackError("corrupt_sidecar", "semantic sidecar header length must be positive")
            if header_len > _MAX_SIDECAR_HEADER_BYTES:
                raise VocabularyPackError(
                    "corrupt_sidecar",
                    f"semantic sidecar header length {header_len} exceeds maximum {_MAX_SIDECAR_HEADER_BYTES} bytes",
                )
            h_start = len(SIDECAR_MAGIC) + 8
            h_end = h_start + header_len
            if h_end > len(mm):
                raise VocabularyPackError("corrupt_sidecar", "truncated semantic sidecar header")
            try:
                header = json.loads(mm[h_start:h_end].decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise VocabularyPackError("corrupt_sidecar", f"malformed semantic sidecar JSON header: {exc}") from exc
            if not isinstance(header, dict):
                raise VocabularyPackError("corrupt_sidecar", "semantic sidecar header must be a JSON object")
            if header.get("schemaVersion") != SIDECAR_SCHEMA_VERSION:
                raise VocabularyPackError("unsupported_sidecar", "unsupported semantic sidecar schema version")
            if header.get("recordType") != _SIDECAR_RECORD_TYPE:
                raise VocabularyPackError(
                    "corrupt_sidecar",
                    f"expected {_SIDECAR_RECORD_TYPE} recordType, got {header.get('recordType')!r}",
                )
            return cls(
                path=resolved,
                file_obj=file_obj,
                mm=mm,
                header=header,
                rerank_top_r=rerank_top_r,
                header_end=h_end,
                use_calibration=use_calibration,
            )
        except BaseException:
            if mm is not None:
                with contextlib.suppress(BufferError):
                    mm.close()
            file_obj.close()
            raise

    @property
    def pack_id(self) -> str:
        return self._pack_id

    @property
    def pack_sha256(self) -> str:
        return self._pack_sha256

    @property
    def source_manifest_digest(self) -> str:
        return self._source_manifest_digest

    @property
    def model_id(self) -> str:
        return self._model_id

    @property
    def dimensions(self) -> int:
        return self._dim

    @property
    def mode(self) -> str:
        return self._mode

    @property
    def unique_vector_count(self) -> int:
        return self._n_vecs

    @property
    def recommended_min_cosine(self) -> float | None:
        return self._recommended_min_cosine

    @property
    def calibration_mode(self) -> str:
        return self._calibration_mode

    @property
    def calibration_active(self) -> bool:
        return (
            self._use_calibration
            and self._calibration_mode == "centered_covariance"
            and self._corpus_mean_f32 is not None
        )

    @property
    def corpus_mean_norm_sq(self) -> float | None:
        return self._corpus_mean_norm_sq

    @property
    def corpus_pair_std(self) -> float | None:
        return self._corpus_pair_std

    def _try_claim_finalize(self) -> bool:
        """Must be called while holding ``self._state_lock``."""

        if self._closing and self._active_queries == 0 and not self._closed and not self._finalizing:
            self._finalizing = True
            return True
        return False

    def _begin_query(self) -> None:
        with self._state_lock:
            if self._closing or self._closed:
                raise VocabularyPackError("closed_sidecar", "semantic sidecar is closed")
            self._active_queries += 1

    def _end_query(self) -> None:
        with self._state_lock:
            self._active_queries -= 1
            should_finalize = self._try_claim_finalize()
        if should_finalize:
            self._finalize_close()

    def _finalize_close(self) -> None:
        """Release all NumPy buffer views and close mmap + file descriptor cleanly."""

        self._release_views()
        closed_mm = False
        try:
            if not self._mm.closed:
                self._mm.close()
            closed_mm = True
        except BufferError:
            # Leave _closed=False so a subsequent close() or finalizer can complete cleanup.
            closed_mm = False
        finally:
            with self._state_lock:
                self._finalizing = False
                if closed_mm:
                    self._closed = True
        if closed_mm:
            self._file.close()

    def close(self) -> None:
        with self._state_lock:
            self._closing = True
            should_finalize = self._try_claim_finalize()
        if should_finalize:
            self._finalize_close()

    def __del__(self) -> None:
        if getattr(self, "_state_lock", None) is not None and getattr(self, "_mm", None) is not None:
            with contextlib.suppress(Exception):
                self.close()

    def __enter__(self) -> AtlasSemanticSidecar:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def vector_for_rid(self, rid: int) -> np.ndarray | None:
        """Return the unit-normalized stored float32 vector for ``rid`` in ``O(1)``, or ``None`` if unindexed."""

        self._begin_query()
        try:
            return self._vector_for_rid_impl(rid)
        finally:
            self._end_query()

    def _vector_for_rid_impl(self, rid: int) -> np.ndarray | None:
        if isinstance(rid, bool) or not isinstance(rid, int):
            return None
        if rid < 0 or rid >= self._rid_to_vidx.size:
            return None
        vidx = int(self._rid_to_vidx[rid])
        if vidx == _MISSING_VIDX or vidx >= self._n_vecs:
            return None

        if self._mode == "flat_f16":
            assert self._vectors_f16 is not None
            vec = self._vectors_f16[vidx].astype(np.float32)
        else:
            assert self._vectors_i8 is not None and self._scales_f16 is not None
            vec = self._vectors_i8[vidx].astype(np.float32) * float(self._scales_f16[vidx])

        norm = float(np.linalg.norm(vec))
        if math.isfinite(norm) and norm > 1e-12:
            vec = vec / norm
        return vec

    def _effective_rerank_top_r(self, k_eff: int, n_eligible: int, rerank_top_r: int | None) -> int:
        if rerank_top_r is not None:
            if isinstance(rerank_top_r, bool) or not isinstance(rerank_top_r, int) or rerank_top_r < 1:
                raise VocabularyInputError("invalid_rerank_top_r", "rerank_top_r must be a positive integer")
            base_r = rerank_top_r
        else:
            base_r = self._rerank_top_r
        return min(max(base_r, k_eff * 2, 1), n_eligible)

    def _get_vidx_of_rids(self) -> np.ndarray:
        if self._vidx_of_rids is None:
            with self._cache_lock:
                if self._vidx_of_rids is None:
                    counts = np.diff(self._rid_offsets)
                    mapped_end = int(self._rid_offsets[-1])
                    if mapped_end == 0:
                        self._vidx_of_rids = np.empty(0, dtype=np.uint32)
                    else:
                        self._vidx_of_rids = np.repeat(np.arange(self._n_vecs, dtype=np.uint32), counts)
        return self._vidx_of_rids

    def _project_vidxs_to_plan(
        self,
        vidxs: np.ndarray,
    ) -> tuple[np.ndarray | None, np.ndarray | None, int]:
        if vidxs.size == 0:
            return np.empty(0, dtype=np.int64), None, 0
        if vidxs.size <= _EXACT_FILTER_THRESHOLD:
            elig = np.unique(vidxs).astype(np.int64, copy=False)
            return elig, None, int(elig.size)
        vmask = np.zeros(self._n_vecs, dtype=np.bool_)
        vmask[vidxs] = True
        n_elig = int(np.count_nonzero(vmask))
        if n_elig == 0:
            return np.empty(0, dtype=np.int64), None, 0
        if n_elig <= _EXACT_FILTER_THRESHOLD:
            elig = np.flatnonzero(vmask).astype(np.int64, copy=False)
            return elig, None, n_elig
        return None, vmask, n_elig

    def _resolve_allowed_filter(
        self,
        allowed_rids: Any,
    ) -> tuple[np.ndarray | None, np.ndarray | None, int, np.ndarray | None, set[int] | None]:
        """Project ``allowed_rids`` onto eligible vector indices and return rid-level filter.

        Returns ``(eligible_vidx, allowed_vidx_mask, n_eligible, allowed_rid_mask, allowed_rid_set)``.
        Exactly one of ``eligible_vidx`` (sorted unique int64, length ``<= _EXACT_FILTER_THRESHOLD``)
        or ``allowed_vidx_mask`` (bool mask of length ``n_vecs``) is non-None when ``n_eligible > 0``.
        """

        if isinstance(allowed_rids, (bytes, bytearray, memoryview)):
            if isinstance(allowed_rids, memoryview) and (
                allowed_rids.ndim != 1 or allowed_rids.itemsize != 1 or not allowed_rids.c_contiguous
            ):
                raise VocabularyInputError(
                    "invalid_allowed_rids",
                    "memoryview allowed_rids must be a 1D contiguous byte buffer",
                )
            mask_u8 = np.frombuffer(allowed_rids, dtype=np.uint8)
            cache_key = allowed_rids if isinstance(allowed_rids, bytes) and len(allowed_rids) <= _MASK_CACHE_MAX_BYTES else None
            if cache_key is not None:
                with self._cache_lock:
                    cached = self._bytes_mask_cache.get(cache_key)
                    if cached is not None:
                        self._bytes_mask_cache.move_to_end(cache_key)
                        return cached[0], cached[1], cached[2], mask_u8, None

            plan = self._project_dense_mask(mask_u8)
            if cache_key is not None:
                with self._cache_lock:
                    self._bytes_mask_cache[cache_key] = plan
                    self._bytes_mask_cache.move_to_end(cache_key)
                    while len(self._bytes_mask_cache) > _MASK_CACHE_MAX_ENTRIES:
                        self._bytes_mask_cache.popitem(last=False)
            return plan[0], plan[1], plan[2], mask_u8, None

        if isinstance(allowed_rids, np.ndarray):
            if allowed_rids.ndim != 1:
                raise VocabularyInputError(
                    "invalid_allowed_rids",
                    f"numpy allowed_rids must be 1D, got shape {allowed_rids.shape}",
                )
            if allowed_rids.dtype == np.bool_:
                mask_u8 = (
                    allowed_rids.view(np.uint8)
                    if allowed_rids.flags.c_contiguous
                    else np.ascontiguousarray(allowed_rids, dtype=np.uint8)
                )
                elig, vmask, n_elig = self._project_dense_mask(mask_u8)
                return elig, vmask, n_elig, mask_u8, None
            if allowed_rids.dtype == np.uint8:
                mask_u8 = np.ascontiguousarray(allowed_rids)
                elig, vmask, n_elig = self._project_dense_mask(mask_u8)
                return elig, vmask, n_elig, mask_u8, None
            if np.issubdtype(allowed_rids.dtype, np.integer):
                if allowed_rids.size == 0:
                    return np.empty(0, dtype=np.int64), None, 0, None, set()
                valid = allowed_rids[(allowed_rids >= 0) & (allowed_rids <= self._max_rid)]
                if valid.size == 0:
                    return np.empty(0, dtype=np.int64), None, 0, None, set()
                rid_arr = valid.astype(np.int64, copy=False)
                rid_set = {int(r) for r in rid_arr.tolist()}
                elig, vmask, n_elig = self._project_explicit_rids(rid_arr)
                return elig, vmask, n_elig, None, rid_set
            raise VocabularyInputError(
                "invalid_allowed_rids",
                f"unsupported numpy dtype for allowed_rids: {allowed_rids.dtype}",
            )

        if isinstance(allowed_rids, (str, dict)):
            raise VocabularyInputError(
                "invalid_allowed_rids",
                f"unsupported allowed_rids type: {type(allowed_rids).__name__}",
            )

        if isinstance(allowed_rids, (Sequence, AbstractSet)):
            rid_set: set[int] = set()
            max_rid = self._max_rid
            for item in allowed_rids:
                if isinstance(item, bool) or not isinstance(item, (int, np.integer)):
                    raise VocabularyInputError(
                        "invalid_allowed_rids",
                        f"allowed_rids entries must be integers, got {type(item).__name__}",
                    )
                rid_int = int(item)
                if 0 <= rid_int <= max_rid:
                    rid_set.add(rid_int)
            if not rid_set:
                return np.empty(0, dtype=np.int64), None, 0, None, rid_set
            rid_arr = np.fromiter(rid_set, dtype=np.int64, count=len(rid_set))
            elig, vmask, n_elig = self._project_explicit_rids(rid_arr)
            return elig, vmask, n_elig, None, rid_set

        raise VocabularyInputError(
            "invalid_allowed_rids",
            f"unsupported allowed_rids type: {type(allowed_rids).__name__}",
        )

    def _project_dense_mask(
        self,
        mask_u8: np.ndarray,
    ) -> tuple[np.ndarray | None, np.ndarray | None, int]:
        limit_len = min(int(mask_u8.size), int(self._rid_to_vidx.size))
        if limit_len == 0 or self._n_vecs == 0:
            return np.empty(0, dtype=np.int64), None, 0
        m = mask_u8[:limit_len]

        if not self._unique_rid_per_vidx:
            mapped_end = int(self._rid_offsets[-1])
            if mapped_end == 0:
                return np.empty(0, dtype=np.int64), None, 0
            rids_used = self._rids[:mapped_end]
            in_bounds = rids_used < limit_len
            safe_idx = np.where(in_bounds, rids_used, 0)
            hit = in_bounds & (m[safe_idx] != 0)
            vidxs = self._get_vidx_of_rids()[hit]
            return self._project_vidxs_to_plan(vidxs)

        sparse_rids, is_sparse = _extract_sparse_rids_u64(m, max_words=_EXACT_FILTER_THRESHOLD)
        if is_sparse:
            assert sparse_rids is not None
            if sparse_rids.size == 0:
                return np.empty(0, dtype=np.int64), None, 0
            vidxs = self._rid_to_vidx[sparse_rids]
        else:
            vidxs = self._rid_to_vidx[:limit_len][m != 0]

        vidxs = vidxs[vidxs != _MISSING_VIDX]
        return self._project_vidxs_to_plan(vidxs)

    def _project_explicit_rids(
        self,
        rid_arr: np.ndarray,
    ) -> tuple[np.ndarray | None, np.ndarray | None, int]:
        if rid_arr.size == 0 or self._n_vecs == 0:
            return np.empty(0, dtype=np.int64), None, 0
        if not self._unique_rid_per_vidx:
            mapped_end = int(self._rid_offsets[-1])
            if mapped_end == 0:
                return np.empty(0, dtype=np.int64), None, 0
            rids_used = self._rids[:mapped_end]
            hit = np.isin(rids_used, rid_arr.astype(np.uint32, copy=False))
            vidxs = self._get_vidx_of_rids()[hit]
            return self._project_vidxs_to_plan(vidxs)
        vidxs = self._rid_to_vidx[rid_arr]
        vidxs = vidxs[vidxs != _MISSING_VIDX]
        return self._project_vidxs_to_plan(vidxs)

    def _score_f16_candidates(self, cand_vidx: np.ndarray, q: np.ndarray) -> np.ndarray:
        assert self._vectors_f16 is not None
        n_cand = int(cand_vidx.size)
        if n_cand == 0:
            return np.empty(0, dtype=np.float32)
        scores = np.empty(n_cand, dtype=np.float32)
        chunk = min(_RERANK_CHUNK_ROWS, n_cand)
        buf_f32 = np.empty((chunk, self._dim), dtype=np.float32)
        for start in range(0, n_cand, chunk):
            end = min(start + chunk, n_cand)
            n = end - start
            buf_f32[:n] = self._vectors_f16[cand_vidx[start:end]]
            np.matmul(buf_f32[:n], q, out=scores[start:end])
        return scores

    def _score_i8_candidates(self, cand_vidx: np.ndarray, q: np.ndarray) -> np.ndarray:
        assert self._vectors_i8 is not None and self._scales_f16 is not None
        n_cand = int(cand_vidx.size)
        if n_cand == 0:
            return np.empty(0, dtype=np.float32)
        scores = np.empty(n_cand, dtype=np.float32)
        chunk = min(_RERANK_CHUNK_ROWS, n_cand)
        buf_f32 = np.empty((chunk, self._dim), dtype=np.float32)
        for start in range(0, n_cand, chunk):
            end = min(start + chunk, n_cand)
            n = end - start
            buf_f32[:n] = self._vectors_i8[cand_vidx[start:end]]
            np.matmul(buf_f32[:n], q, out=scores[start:end])
        scores *= self._scales_f16[cand_vidx]
        return scores

    def _top_k_from_scored(
        self,
        cand_vidx: np.ndarray,
        cand_scores: np.ndarray,
        *,
        top_k: int,
        min_cosine: float,
    ) -> list[tuple[int, float]]:
        n_cand = int(cand_scores.size)
        if n_cand == 0:
            return []
        k_eff = min(top_k, n_cand) if self._unique_rid_per_vidx else n_cand
        if k_eff < n_cand:
            part = np.argpartition(cand_scores, -k_eff)[-k_eff:]
            part = part[np.argsort(-cand_scores[part])]
        else:
            part = np.argsort(-cand_scores)
        return [
            (int(cand_vidx[p]), float(cand_scores[p]))
            for p in part
            if float(cand_scores[p]) >= min_cosine
        ]

    def _search_ivf_i8_filtered(
        self,
        q: np.ndarray,
        *,
        top_k: int,
        min_cosine: float,
        nprobe: int,
        allowed_vidx_mask: np.ndarray,
        n_eligible: int,
        score_bias: float = 0.0,
    ) -> list[tuple[int, float]]:
        assert (
            self._centroids_f32 is not None
            and self._cluster_offsets is not None
            and self._vectors_i8 is not None
            and self._scales_f16 is not None
        )
        coarse = self._centroids_f32 @ q
        cluster_order = np.argsort(-coarse)
        k_eff = min(top_k, n_eligible)
        init_probe = min(max(1, int(nprobe)), self._n_clusters)
        target_elig = min(n_eligible, max(k_eff * 8, 256))

        def _gather_cluster_elig(c_from: int, c_to: int) -> np.ndarray:
            parts: list[np.ndarray] = []
            for cid in cluster_order[c_from:c_to]:
                c = int(cid)
                start = int(self._cluster_offsets[c])
                end = int(self._cluster_offsets[c + 1])
                if end > start:
                    local = np.flatnonzero(allowed_vidx_mask[start:end])
                    if local.size:
                        parts.append(local + start)
            if not parts:
                return np.empty(0, dtype=np.int64)
            if len(parts) == 1:
                return parts[0].astype(np.int64, copy=False)
            return np.concatenate(parts).astype(np.int64, copy=False)

        # Phase 1: probe initial clusters and expand adaptively until we gather enough eligible vectors.
        probed = 0
        collected_parts: list[np.ndarray] = []
        collected_count = 0
        while probed < self._n_clusters:
            next_probed = init_probe if probed == 0 else min(self._n_clusters, max(probed * 2, probed + init_probe))
            chunk_vidx = _gather_cluster_elig(probed, next_probed)
            probed = next_probed
            if chunk_vidx.size:
                collected_parts.append(chunk_vidx)
                collected_count += int(chunk_vidx.size)
            if collected_count >= target_elig:
                break

        if not collected_parts:
            return []

        cand_vidx = collected_parts[0] if len(collected_parts) == 1 else np.concatenate(collected_parts)
        cand_vidx.sort()
        cand_scores = self._score_i8_candidates(cand_vidx, q)
        if score_bias != 0.0:
            cand_scores -= score_bias
        above = cand_scores >= min_cosine
        hit_vidx_parts: list[np.ndarray] = [cand_vidx[above]] if np.any(above) else []
        hit_score_parts: list[np.ndarray] = [cand_scores[above]] if np.any(above) else []
        n_hits = int(hit_vidx_parts[0].size) if hit_vidx_parts else 0

        # Phase 2: if probed clusters under-filled top_k, expand adaptively (or exhaust all remaining clusters
        # for <= 50K eligible vectors) so filtered IVF never starves when eligible matches exist.
        if n_hits < k_eff and probed < self._n_clusters:
            max_probe = (
                self._n_clusters
                if n_eligible <= _IVF_EXACT_FALLBACK_THRESHOLD
                else min(self._n_clusters, max(init_probe * 4, 128))
            )
            while n_hits < k_eff and probed < max_probe:
                next_probed = min(max_probe, max(probed * 2, probed + init_probe))
                extra_vidx = _gather_cluster_elig(probed, next_probed)
                probed = next_probed
                if extra_vidx.size == 0:
                    continue
                extra_vidx.sort()
                extra_scores = self._score_i8_candidates(extra_vidx, q)
                if score_bias != 0.0:
                    extra_scores -= score_bias
                extra_above = extra_scores >= min_cosine
                if np.any(extra_above):
                    hit_vidx_parts.append(extra_vidx[extra_above])
                    hit_score_parts.append(extra_scores[extra_above])
                    n_hits += int(hit_vidx_parts[-1].size)

        if not hit_vidx_parts:
            return []
        all_vidx = hit_vidx_parts[0] if len(hit_vidx_parts) == 1 else np.concatenate(hit_vidx_parts)
        all_scores = hit_score_parts[0] if len(hit_score_parts) == 1 else np.concatenate(hit_score_parts)
        return self._top_k_from_scored(all_vidx, all_scores, top_k=top_k, min_cosine=min_cosine)

    def search_rids(
        self,
        query_vector: Sequence[float],
        *,
        top_k: int = 40,
        min_cosine: float = 0.55,
        nprobe: int = 24,
        allowed_rids: Any = None,
        rerank_top_r: int | None = None,
    ) -> list[tuple[int, float]]:
        """Return up to ``top_k`` ``(rid, cosine_score)`` pairs meeting ``min_cosine``."""

        self._begin_query()
        try:
            return self._search_rids_impl(
                query_vector,
                top_k=top_k,
                min_cosine=min_cosine,
                nprobe=nprobe,
                allowed_rids=allowed_rids,
                rerank_top_r=rerank_top_r,
            )
        finally:
            self._end_query()

    def _search_rids_impl(
        self,
        query_vector: Sequence[float],
        *,
        top_k: int = 40,
        min_cosine: float = 0.55,
        nprobe: int = 24,
        allowed_rids: Any = None,
        rerank_top_r: int | None = None,
    ) -> list[tuple[int, float]]:
        q = np.asarray(query_vector, dtype=np.float32)
        if q.ndim != 1 or q.shape[0] != self._dim:
            raise VocabularyInputError(
                "invalid_query_vector",
                f"query_vector must be 1D of length {self._dim}, got shape {q.shape}",
            )
        if top_k <= 0 or self._n_vecs == 0:
            return []
        norm = float(np.linalg.norm(q))
        if not math.isfinite(norm) or norm <= 1e-12:
            return []
        q = q / norm

        use_cal = (
            self._use_calibration
            and self._calibration_mode == "centered_covariance"
            and self._corpus_mean_f32 is not None
        )
        if use_cal:
            assert self._corpus_mean_f32 is not None
            # Exact algebraic identity: (v - mu)^T (q - mu) / (1 - ||mu||^2) = v^T q_score - score_bias
            q_sub = q - self._corpus_mean_f32
            q_score = (q_sub / self._corpus_res_var).astype(np.float32, copy=False)
            score_bias = float(np.dot(self._corpus_mean_f32, q_score))
            q_for_bits = q_sub
        else:
            q_score = q
            score_bias = 0.0
            q_for_bits = q

        eligible_vidx: np.ndarray | None = None
        allowed_vidx_mask: np.ndarray | None = None
        allowed_rid_mask: np.ndarray | None = None
        allowed_rid_set: set[int] | None = None
        n_eligible = self._n_vecs

        if allowed_rids is not None:
            (
                eligible_vidx,
                allowed_vidx_mask,
                n_eligible,
                allowed_rid_mask,
                allowed_rid_set,
            ) = self._resolve_allowed_filter(allowed_rids)
            if n_eligible == 0:
                return []

        eff_min_cosine = float(min_cosine)
        if (
            use_cal
            and eff_min_cosine > 0.0
            and n_eligible < self._n_vecs
            and self._n_vecs > _CALIBRATION_EVT_N_FLOOR
        ):
            eff_min_cosine *= math.sqrt(
                math.log(max(n_eligible, _CALIBRATION_EVT_N_FLOOR)) / math.log(self._n_vecs)
            )

        cand_pairs: list[tuple[int, float]]
        if eligible_vidx is not None:
            # Exact-scan fast path (<= 5,000 eligible vectors): 100% exact recall, sub-millisecond, zero starvation.
            if self._mode == "flat_f16":
                cand_scores = self._score_f16_candidates(eligible_vidx, q_score)
            else:
                cand_scores = self._score_i8_candidates(eligible_vidx, q_score)
            if score_bias != 0.0:
                cand_scores -= score_bias
            cand_pairs = self._top_k_from_scored(
                eligible_vidx,
                cand_scores,
                top_k=top_k,
                min_cosine=eff_min_cosine,
            )
        elif self._mode == "flat_f16":
            assert self._vectors_f16 is not None
            if allowed_vidx_mask is not None and n_eligible <= self._n_vecs // 4:
                sub_vidx = np.flatnonzero(allowed_vidx_mask).astype(np.int64, copy=False)
                cand_scores = self._score_f16_candidates(sub_vidx, q_score)
                if score_bias != 0.0:
                    cand_scores -= score_bias
                cand_pairs = self._top_k_from_scored(
                    sub_vidx,
                    cand_scores,
                    top_k=top_k,
                    min_cosine=eff_min_cosine,
                )
            else:
                if self._n_vecs <= _FLAT_QUERY_CHUNK:
                    scores = self._vectors_f16.astype(np.float32) @ q_score
                else:
                    scores = np.empty(self._n_vecs, dtype=np.float32)
                    for start in range(0, self._n_vecs, _FLAT_QUERY_CHUNK):
                        end = min(start + _FLAT_QUERY_CHUNK, self._n_vecs)
                        scores[start:end] = self._vectors_f16[start:end].astype(np.float32) @ q_score
                if score_bias != 0.0:
                    scores -= score_bias
                if allowed_vidx_mask is not None:
                    cand_vidx = np.flatnonzero(allowed_vidx_mask).astype(np.int64, copy=False)
                    cand_scores = scores[cand_vidx]
                else:
                    cand_vidx = np.arange(self._n_vecs, dtype=np.int64)
                    cand_scores = scores
                cand_pairs = self._top_k_from_scored(
                    cand_vidx,
                    cand_scores,
                    top_k=top_k,
                    min_cosine=eff_min_cosine,
                )
        elif self._mode == "ivf_i8":
            if allowed_vidx_mask is not None:
                cand_pairs = self._search_ivf_i8_filtered(
                    q_score,
                    top_k=top_k,
                    min_cosine=eff_min_cosine,
                    nprobe=nprobe,
                    allowed_vidx_mask=allowed_vidx_mask,
                    n_eligible=n_eligible,
                    score_bias=score_bias,
                )
            else:
                assert (
                    self._centroids_f32 is not None
                    and self._cluster_offsets is not None
                    and self._vectors_i8 is not None
                    and self._scales_f16 is not None
                )
                coarse = self._centroids_f32 @ q_score
                probe = min(max(1, int(nprobe)), self._n_clusters)
                if probe < self._n_clusters:
                    c_idx = np.argpartition(coarse, -probe)[-probe:]
                    c_idx = c_idx[np.argsort(-coarse[c_idx])]
                else:
                    c_idx = np.argsort(-coarse)

                # Gather probed cluster slices into ONE pre-allocated contiguous buffer and execute ONE BLAS SGEMV.
                ranges: list[tuple[int, int]] = []
                total_cand = 0
                for cid in c_idx:
                    c = int(cid)
                    start = int(self._cluster_offsets[c])
                    end = int(self._cluster_offsets[c + 1])
                    if end > start:
                        ranges.append((start, end))
                        total_cand += end - start
                if total_cand == 0:
                    return []

                cand_f32 = np.empty((total_cand, self._dim), dtype=np.float32)
                cand_scales = np.empty(total_cand, dtype=np.float32)
                cand_vidx = np.empty(total_cand, dtype=np.int64)
                pos = 0
                for start, end in ranges:
                    n_rows = end - start
                    cand_f32[pos : pos + n_rows] = self._vectors_i8[start:end]
                    cand_scales[pos : pos + n_rows] = self._scales_f16[start:end]
                    cand_vidx[pos : pos + n_rows] = np.arange(start, end, dtype=np.int64)
                    pos += n_rows

                all_sc = cand_f32 @ q_score
                all_sc *= cand_scales
                if score_bias != 0.0:
                    all_sc -= score_bias
                cand_pairs = self._top_k_from_scored(
                    cand_vidx,
                    all_sc,
                    top_k=top_k,
                    min_cosine=eff_min_cosine,
                )
        else:
            # binary_i8: chunked XOR + SIMD bitwise_count (or LUT fallback) Hamming scan, then exact int8 rerank.
            assert (
                self._binary_u8 is not None
                and self._vectors_i8 is not None
                and self._scales_f16 is not None
            )
            q_bits = np.packbits(q_for_bits > 0)
            ham_dtype = np.uint16 if self._binary_u8.shape[1] * 8 < 65_535 else np.uint32
            k_eff = min(top_k, n_eligible)
            r_eff = self._effective_rerank_top_r(k_eff, n_eligible, rerank_top_r)

            if r_eff >= n_eligible:
                cand_vidx = (
                    np.flatnonzero(allowed_vidx_mask).astype(np.int64, copy=False)
                    if allowed_vidx_mask is not None
                    else np.arange(self._n_vecs, dtype=np.int64)
                )
            elif allowed_vidx_mask is not None and n_eligible <= self._n_vecs // 4:
                sub_vidx = np.flatnonzero(allowed_vidx_mask).astype(np.int64, copy=False)
                hamming = _hamming_distances_u8_indexed(self._binary_u8, q_bits, sub_vidx, ham_dtype)
                local_cand = np.argpartition(hamming, r_eff - 1)[:r_eff]
                cand_vidx = sub_vidx[local_cand]
            else:
                hamming = _hamming_distances_u8(self._binary_u8, q_bits, ham_dtype)
                if allowed_vidx_mask is not None:
                    hamming[~allowed_vidx_mask] = np.iinfo(ham_dtype).max
                cand_vidx = np.argpartition(hamming, r_eff - 1)[:r_eff].astype(np.int64, copy=False)

            # Sort candidate vector indices for sequential mmap page-cache reads during chunked int8 rerank.
            cand_vidx.sort()
            cand_scores = self._score_i8_candidates(cand_vidx, q_score)
            if score_bias != 0.0:
                cand_scores -= score_bias
            cand_pairs = self._top_k_from_scored(
                cand_vidx,
                cand_scores,
                top_k=top_k,
                min_cosine=eff_min_cosine,
            )

        # Expand deduplicated vector indices to SQLite pack resource IDs (preserving best cosine per rid,
        # and strictly filtering to allowed_rids when a vector is shared across multiple resources).
        out: list[tuple[int, float]] = []
        seen: set[int] = set()
        allowed_mask_len = int(allowed_rid_mask.size) if allowed_rid_mask is not None else 0
        for vidx, score in cand_pairs:
            r_start = int(self._rid_offsets[vidx])
            r_end = int(self._rid_offsets[vidx + 1])
            for rid_val in self._rids[r_start:r_end]:
                rid_int = int(rid_val)
                if allowed_rid_mask is not None:
                    if rid_int >= allowed_mask_len or allowed_rid_mask[rid_int] == 0:
                        continue
                elif allowed_rid_set is not None and rid_int not in allowed_rid_set:
                    continue
                if rid_int not in seen:
                    seen.add(rid_int)
                    out.append((rid_int, score))
                    if len(out) >= top_k:
                        return out
        return out


__all__ = [
    "SIDECAR_MAGIC",
    "SIDECAR_SCHEMA_VERSION",
    "AtlasSemanticSidecar",
    "SemanticSidecarManifest",
    "build_semantic_sidecar",
    "build_semantic_sidecar_from_arrays",
    "calibrate_semantic_sidecar",
]
