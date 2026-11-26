"""Sign one Atlas distribution from beside it, and verify the whole artifact.

The seal is detached and lives beside the distribution directory, never inside
it: a distribution validates its own membership as a closed set, so a file
written into that directory makes the sealed artifact fail its own walk. The
served Parquet view sits beside it for the same reason.

`verify_seal` is deliberately not a signature check. Downstream admission gates
recompute member digests before they read a byte, so a seal that only proved
provenance would be refused at that seam. This module proves the signature, the
three digests the signature binds, and then closed membership plus every pinned
byte on disk: the distribution's members and packs, and every table of the
Parquet view. `create_seal` runs that same walk before it signs, so a seal can
only exist over an artifact that already verifies.

**Why the view digest is in the signed payload rather than in the construction
summary.** The obvious shape -- the summary pinning `view-manifest.json` --
does not exist: the view manifest pins the distribution manifest's digest and
the construction summary's digest as its input identity, and the summary is a
manifest member, so a summary that pinned the view manifest would be a cycle.
The seal is written after both artifacts are final, so binding the view there
is the one placement with no cycle and no second root of trust. The other
direction is checked too: the view's `input.manifestSha256` must be the
manifest digest this seal signs, so neither artifact can be paired with a
distribution it was not derived from.

What the seal does NOT reach: the source side. It attests that acceptance ran
on these bytes; it does not attest that the artifact faithfully transcribes its
publisher sources -- that is the fidelity auditor's scheduled job
(`tools/verify_atlas_source_fidelity.py`) -- nor that the publisher captures
behind it were complete.
"""

from __future__ import annotations

import errno
import hashlib
import json
import os
import sqlite3
import stat
import struct
import subprocess
import sys
import tempfile
from collections.abc import Collection, Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote

from refspec.input_pin import verify_file_pin
from refspec.release_model import canonical_json_bytes, reject_duplicate_keys, reject_nonfinite_constant

# -2: the compact JSONL packs the summary used to declare are gone, and the
# payload binds the served Parquet view's manifest digest instead.
# -3: extends -2 by cryptographically binding a detached compiled SQLite
# vocabulary pack (and optional `.vpack` semantic vector sidecar) beside the
# distribution with bi-directional manifest-digest pairing.
SEAL_FORMAT = "refspec-distribution-seal-2"
SEAL_FORMAT_V3 = "refspec-distribution-seal-3"
SUPPORTED_SEAL_FORMATS = frozenset({SEAL_FORMAT, SEAL_FORMAT_V3})
SEAL_TYPE = "RefSpecDistributionSeal"
SIGNATURE_NAMESPACE = "refspec-distribution-seal"
MANIFEST_MEMBER = "atlas-manifest.json"
ACCEPTANCE_MEMBER = "atlas-acceptance.json"
DEFAULT_PARQUET_VIEW_NAME = "parquet-view"
DEFAULT_VOCABULARY_PACK_NAME = "vocabulary-pack.sqlite"
DEFAULT_SEMANTIC_SIDECAR_NAME = "vocabulary-pack.vpack"
SEAL_KEYS = frozenset({"payload", "signature", "signerIdentity", "type"})
PAYLOAD_KEYS = frozenset(
    {
        "acceptanceSha256",
        "distributionId",
        "manifestSha256",
        "parquetViewManifestSha256",
        "sealFormat",
    }
)
PAYLOAD_KEYS_V3_BASE = PAYLOAD_KEYS | frozenset({"vocabularyPackSha256"})
PAYLOAD_KEYS_V3_WITH_SIDECAR = PAYLOAD_KEYS_V3_BASE | frozenset({"semanticSidecarSha256"})
_SIDECAR_MAGIC = b"RFVP0001"
_MAX_SIDECAR_HEADER_BYTES = 16 * 1024 * 1024
_READ_BLOCK = 1024 * 1024
_SSH_KEYGEN_TIMEOUT_SECONDS = 60
_DARWIN_SYSTEM_SYMLINKS: dict[str, str] = {
    "/var": "private/var",
    "/tmp": "private/tmp",
    "/etc": "private/etc",
}


class SealError(Exception):
    """One seal refusal, naming the first thing that did not hold."""


@dataclass(frozen=True)
class SealVerification:
    """Exactly what one successful `verify_seal` checked, and over how many bytes."""

    distribution_id: str
    signer_identity: str
    manifest_sha256: str
    acceptance_sha256: str
    parquet_view_manifest_sha256: str
    member_count: int
    pack_count: int
    parquet_table_count: int
    verified_byte_length: int
    seal_format: str = SEAL_FORMAT
    vocabulary_pack_sha256: str | None = None
    semantic_sidecar_sha256: str | None = None
    created_at: str | None = None


@dataclass(frozen=True)
class _DistributionWalk:
    """What one full walk of a distribution root found and authenticated."""

    member_count: int
    pack_count: int
    verified_byte_length: int


def _file_sha256(path: Path, label: str) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(_READ_BLOCK), b""):
                digest.update(block)
    except OSError as error:
        raise SealError(f"cannot read the {label}: {path}") from error
    return "sha256:" + digest.hexdigest()


def _read_json_object(path: Path, label: str) -> dict[str, Any]:
    """Read one JSON object under the repository's canonical reader rules."""

    try:
        value = json.loads(
            path.read_bytes().decode("utf-8"),
            object_pairs_hook=reject_duplicate_keys,
            parse_constant=reject_nonfinite_constant,
        )
    except (OSError, UnicodeDecodeError, ValueError) as error:
        raise SealError(f"the {label} is not readable canonical UTF-8 JSON: {path}: {error}") from error
    if not isinstance(value, dict):
        raise SealError(f"the {label} must be a JSON object: {path}")
    return value


def _canonical_bytes(value: Any, label: str) -> bytes:
    try:
        return canonical_json_bytes(value)
    except (TypeError, ValueError) as error:
        raise SealError(f"the {label} has no canonical JSON encoding: {error}") from error


def _require_exact_keys(value: dict[str, Any], expected: frozenset[str], label: str) -> None:
    """Refuse, never ignore, a key this version does not know or a key it needs."""

    actual = set(value)
    if actual != expected:
        raise SealError(
            f"the {label} must hold exactly {sorted(expected)}: "
            f"unexpected={sorted(actual - expected)}, missing={sorted(expected - actual)}"
        )


def _member_path(root: Path, relative: object, label: str) -> Path:
    if not isinstance(relative, str) or not relative:
        raise SealError(f"{label} states no path")
    path = Path(relative)
    if path.is_absolute() or ".." in path.parts or relative != path.as_posix():
        raise SealError(f"{label} path is unsafe: {relative!r}")
    return root / path


def _run_ssh_keygen(arguments: list[str], message: bytes, verb: str) -> bytes:
    """Run one `ssh-keygen -Y` operation over stdin, turning its refusal into ours."""

    try:
        completed = subprocess.run(
            ["ssh-keygen", *arguments],
            input=message,
            capture_output=True,
            check=False,
            timeout=_SSH_KEYGEN_TIMEOUT_SECONDS,
        )
    except OSError as error:
        raise SealError(f"ssh-keygen is unavailable, so this seal cannot be {verb}ed") from error
    except subprocess.TimeoutExpired as error:
        raise SealError(
            f"ssh-keygen did not {verb} this seal within {_SSH_KEYGEN_TIMEOUT_SECONDS}s"
        ) from error
    if completed.returncode != 0:
        detail = completed.stderr.decode("utf-8", "replace").strip() or f"exit {completed.returncode}"
        raise SealError(f"ssh-keygen refused to {verb} this seal: {detail}")
    return completed.stdout


def _sign_payload(payload: bytes, private_key_path: Path) -> str:
    arguments = ["-Y", "sign", "-q", "-f", str(private_key_path), "-n", SIGNATURE_NAMESPACE, "-"]
    return _run_ssh_keygen(arguments, payload, "sign").decode("ascii")


def _verify_payload_signature(payload: bytes, signature: str, identity: str, allowed_signers_path: Path) -> None:
    if not allowed_signers_path.is_file():
        raise SealError(f"the allowed-signers file is missing: {allowed_signers_path}")
    with tempfile.NamedTemporaryFile("w", suffix=".sig", encoding="ascii") as handle:
        try:
            handle.write(signature)
            handle.flush()
        except UnicodeEncodeError as error:
            raise SealError("the seal signature is not an OpenSSH armored signature") from error
        arguments = ["-Y", "verify", "-f", str(allowed_signers_path), "-I", identity]
        _run_ssh_keygen([*arguments, "-n", SIGNATURE_NAMESPACE, "-s", handle.name], payload, "verify")


def _verify_pinned_file(root: Path, path_source: Any, pin_source: Any, kind: str) -> tuple[str, int]:
    if not isinstance(path_source, dict) or not isinstance(pin_source, dict):
        raise SealError(f"manifest {kind} is not an object")
    relative = path_source.get("path")
    path = _member_path(root, relative, f"manifest {kind}")
    expected_sha256 = pin_source.get("digest")
    expected_byte_length = pin_source.get("byteLength")
    if not isinstance(expected_sha256, str) or not isinstance(expected_byte_length, int):
        raise SealError(f"manifest {kind} states no digest and byte length: {relative}")
    try:
        verify_file_pin(
            path,
            expected_sha256=expected_sha256,
            expected_byte_length=expected_byte_length,
            logical_path=relative,
        )
    except (OSError, ValueError) as error:
        raise SealError(f"{kind} differs from the sealed manifest: {relative}: {error}") from error
    return str(relative), expected_byte_length


def _sweep_tree(root: Path) -> tuple[set[str], set[str]]:
    """Enumerate the sealed tree, refusing anything that is not a regular file or directory.

    Symlinks are refused wherever they appear — a linked file, or a linked
    directory anywhere on the way to one — because a link's bytes live outside
    the sealed set and a pin taken through it says nothing about the artifact.
    """

    if root.is_symlink():
        raise SealError(f"the distribution root is a symlink: {root}")
    files: set[str] = set()
    directories: set[str] = set()
    for parent, directory_names, file_names in os.walk(root, followlinks=False):
        parent_path = Path(parent)
        for name in sorted(directory_names) + sorted(file_names):
            entry = parent_path / name
            relative = entry.relative_to(root).as_posix()
            if entry.is_symlink():
                raise SealError(f"the distribution holds a symlink: {relative}")
            if entry.is_dir():
                directories.add(relative)
            elif entry.is_file():
                files.add(relative)
            else:
                raise SealError(f"the distribution holds something that is not a regular file: {relative}")
    return files, directories


def _check_closed_membership(expected_files: set[str], files: set[str], directories: set[str]) -> None:
    """Refuse a tree that is not exactly the expected set of files and directories."""

    expected_directories = {
        parent.as_posix() for relative in expected_files for parent in Path(relative).parents if parent != Path(".")
    }
    for offending, complaint in (
        (sorted(files - expected_files), "is not a member of the sealed distribution"),
        (sorted(directories - expected_directories), "is a directory the sealed distribution does not declare"),
        (sorted(expected_files - files), "is a sealed member that is missing"),
        (sorted(expected_directories - directories), "is a sealed directory that is missing"),
    ):
        if offending:
            raise SealError(f"{offending[0]} {complaint}")


def _declare(expected: set[str], relative: str) -> None:
    if relative in expected:
        raise SealError(f"the distribution declares {relative} twice")
    expected.add(relative)


def _walk_distribution(root: Path, manifest: dict[str, Any]) -> _DistributionWalk:
    """Authenticate closed membership and every pinned byte under one distribution root.

    The manifest reaches every byte in one hop now that the compact JSONL packs
    are gone: `members[]` and `packs[].transport` are the whole set, which is
    the same closed membership the Atlas validator enforces in
    `_check_distribution_files`. The served projection is not in here; it is
    walked separately by `_walk_parquet_view`.
    """

    members = manifest.get("members")
    packs = manifest.get("packs")
    if not isinstance(members, list) or not isinstance(packs, list):
        raise SealError(f"the manifest states no members and packs lists: {root / MANIFEST_MEMBER}")

    files, directories = _sweep_tree(root)
    expected: set[str] = {MANIFEST_MEMBER}
    verified_byte_length = 0

    for member in members:
        relative, byte_length = _verify_pinned_file(root, member, member, "member")
        _declare(expected, relative)
        verified_byte_length += byte_length

    for pack in packs:
        transport = pack.get("transport") if isinstance(pack, dict) else None
        relative, byte_length = _verify_pinned_file(root, pack, transport, "pack")
        _declare(expected, relative)
        verified_byte_length += byte_length

    _check_closed_membership(expected, files, directories)
    return _DistributionWalk(
        member_count=len(members),
        pack_count=len(packs),
        verified_byte_length=verified_byte_length,
    )


def default_parquet_view_path(root: Path | str) -> Path:
    """Name the sibling Parquet view directory the Atlas builder writes."""

    return Path(root).parent / DEFAULT_PARQUET_VIEW_NAME


def _walk_parquet_view(
    view_root: Path,
    *,
    expected_manifest_sha256: str,
    expected_distribution_manifest_sha256: str,
) -> tuple[int, int]:
    """Authenticate the served Parquet view against the digest the seal binds.

    Every table byte is proved here, by the view's own closed-membership
    verifier rather than by a second copy of it. What this adds is the pairing:
    the view manifest must be the one the signature names, and its input pin
    must name the distribution manifest the signature also names.
    """

    from refspec.atlas.parquet_view import (
        MANIFEST_FILE as VIEW_MANIFEST_FILE,
    )
    from refspec.atlas.parquet_view import (
        AtlasParquetViewError,
        verify_atlas_parquet_view,
    )

    _reject_symlink_parents(view_root, "sealed Parquet view")
    if view_root.is_symlink() or not view_root.is_dir():
        raise SealError(f"the sealed Parquet view is missing or unsafe: {view_root}")
    manifest_sha256 = _file_sha256(view_root / VIEW_MANIFEST_FILE, "Parquet view manifest")
    if manifest_sha256 != expected_manifest_sha256:
        raise SealError(f"the Parquet view manifest differs from the sealed digest: {view_root}")
    try:
        view_manifest = verify_atlas_parquet_view(view_root, expected_manifest_digest=manifest_sha256)
    except AtlasParquetViewError as error:
        raise SealError(f"the sealed Parquet view does not verify: {error}") from error
    if view_manifest["input"]["manifestSha256"] != expected_distribution_manifest_sha256:
        raise SealError("the sealed Parquet view was derived from a different distribution manifest")
    members = view_manifest["members"]
    return len(members), sum(int(member["byteLength"]) for member in members)


def default_seal_path(root: Path | str) -> Path:
    """Name the sibling seal file for one distribution root."""

    root = Path(root)
    return root.parent / f"{root.name}-seal.json"


def default_vocabulary_pack_path(root: Path | str) -> Path:
    """Name the sibling SQLite vocabulary pack file beside one distribution root."""

    root = Path(root)
    return root.parent / f"{root.name}-{DEFAULT_VOCABULARY_PACK_NAME}"


def default_semantic_sidecar_path(root: Path | str) -> Path:
    """Name the sibling `.vpack` semantic vector sidecar beside one distribution root."""

    root = Path(root)
    return root.parent / f"{root.name}-{DEFAULT_SEMANTIC_SIDECAR_NAME}"


def _is_darwin_system_symlink(parent: Path) -> bool:
    if sys.platform != "darwin":
        return False
    expected_target = _DARWIN_SYSTEM_SYMLINKS.get(str(parent))
    if expected_target is None:
        return False
    try:
        actual_target = os.readlink(parent)
    except OSError:
        return False
    return actual_target in {expected_target, "/" + expected_target}


def _reject_symlink_parents(path: Path, label: str) -> None:
    """Refuse symlinked parent directories (ignoring macOS /var, /tmp, /etc system links)."""

    for parent in path.parents:
        if not parent.is_symlink():
            continue
        if _is_darwin_system_symlink(parent):
            continue
        raise SealError(f"the {label} traverses a symlinked parent directory: {parent}")


def _require_detached_regular_file(path: Path, resolved_root: Path, label: str) -> Path:
    """Refuse symlinks, symlinked parent directories, non-regular files, and files inside the distribution."""

    if path.is_symlink():
        raise SealError(f"the {label} is a symlink: {path}")
    _reject_symlink_parents(path, label)
    if not path.is_file():
        raise SealError(f"the {label} is missing or not a regular file: {path}")
    resolved = path.resolve()
    if resolved == resolved_root or resolved_root in resolved.parents:
        raise SealError(f"refusing to bind a {label} inside the distribution: {path}")
    return path


def _hash_regular_file_nofollow(path: Path, label: str) -> tuple[str, int, tuple[int, int, int, int]]:
    """Hash one regular file via a single O_NOFOLLOW descriptor and return (sha256, size, fstat_snapshot)."""

    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path, flags)
    except OSError as error:
        if error.errno == errno.ELOOP:
            raise SealError(f"the {label} is a symlink: {path}") from error
        raise SealError(f"cannot read the {label}: {path}") from error

    digest = hashlib.sha256()
    byte_length = 0
    try:
        with os.fdopen(fd, "rb") as stream:
            before = os.fstat(stream.fileno())
            if not stat.S_ISREG(before.st_mode):
                raise SealError(f"the {label} is missing or not a regular file: {path}")
            for block in iter(lambda: stream.read(_READ_BLOCK), b""):
                digest.update(block)
                byte_length += len(block)
            after = os.fstat(stream.fileno())
    except OSError as error:
        raise SealError(f"cannot read the {label}: {path}") from error

    before_snap = (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
    after_snap = (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
    if before_snap != after_snap or byte_length != before.st_size:
        raise SealError(f"the {label} changed while it was read: {path}")
    return "sha256:" + digest.hexdigest(), byte_length, before_snap


def _parse_iso_instant(raw: object, label: str) -> datetime:
    if not isinstance(raw, str) or not raw.strip():
        raise SealError(f"{label} must be a non-empty ISO-8601 timestamp")
    normalized = raw.strip()
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as error:
        raise SealError(f"{label} is not a valid ISO-8601 timestamp: {raw!r}") from error
    if parsed.tzinfo is None:
        raise SealError(f"{label} must include a timezone offset: {raw!r}")
    return parsed


def _check_rollback_guards(
    distribution_id: str,
    manifest: Mapping[str, Any],
    *,
    previous_created_at: str | None,
    reject_distribution_ids: Collection[str] | None,
) -> str | None:
    """Enforce optional monotonic createdAt and explicit rejected distributionId anti-rollback guards."""

    raw_created_at = manifest.get("createdAt")
    created_at = raw_created_at if isinstance(raw_created_at, str) and raw_created_at.strip() else None

    if reject_distribution_ids is not None:
        if isinstance(reject_distribution_ids, (str, bytes)):
            raise SealError("reject_distribution_ids must be a collection of distributionId strings")
        rejected: set[str] = set()
        for item in reject_distribution_ids:
            if not isinstance(item, str) or not item.strip():
                raise SealError("reject_distribution_ids entries must be non-empty strings")
            rejected.add(item)
        if distribution_id in rejected:
            raise SealError(f"distributionId is explicitly rejected: {distribution_id!r}")

    if previous_created_at is not None:
        previous_dt = _parse_iso_instant(previous_created_at, "previous_created_at")
        if created_at is None:
            raise SealError("cannot enforce previous_created_at rollback guard: manifest states no createdAt")
        manifest_dt = _parse_iso_instant(created_at, "manifest createdAt")
        if manifest_dt < previous_dt:
            raise SealError(
                f"distribution rollback refused: manifest createdAt {created_at!r} predates {previous_created_at!r}"
            )

    return created_at


def _verify_vocabulary_pack(
    pack_path: Path,
    *,
    resolved_root: Path,
    expected_pack_sha256: str | None,
    valid_manifest_digests: frozenset[str],
) -> tuple[str, str, str, int]:
    """Authenticate a detached SQLite vocabulary pack and its bi-directional manifest binding.

    `valid_manifest_digests` contains the sealed distribution manifest digest and
    the sealed Parquet view manifest digest (whose own `input.manifestSha256` has
    already been verified against the distribution manifest). Accepting either
    proves the pack was compiled from this exact sealed distribution while
    blocking cross-distribution pack swaps.
    """

    _require_detached_regular_file(pack_path, resolved_root, "vocabulary pack")
    pack_sha256, byte_length, snapshot = _hash_regular_file_nofollow(pack_path, "vocabulary pack")
    if expected_pack_sha256 is not None and pack_sha256 != expected_pack_sha256:
        raise SealError(f"the vocabulary pack differs from the sealed digest: {pack_path}")

    uri = f"file:{quote(str(pack_path.resolve()))}?mode=ro&immutable=1"
    con: sqlite3.Connection | None = None
    try:
        con = sqlite3.connect(uri, uri=True)
        meta = dict(con.execute("SELECT key, value FROM pack_meta").fetchall())
    except sqlite3.Error as error:
        raise SealError(f"cannot read pack_meta from the vocabulary pack: {pack_path}: {error}") from error
    finally:
        if con is not None:
            con.close()

    try:
        after_sql = pack_path.lstat()
    except OSError as error:
        raise SealError(f"cannot stat the vocabulary pack after reading pack_meta: {pack_path}") from error
    if not stat.S_ISREG(after_sql.st_mode) or (
        after_sql.st_dev,
        after_sql.st_ino,
        after_sql.st_size,
        after_sql.st_mtime_ns,
    ) != snapshot:
        raise SealError(f"the vocabulary pack changed while it was read: {pack_path}")

    record_type = meta.get("record_type")
    if record_type != "AtlasVocabularyPack":
        raise SealError(
            f"the vocabulary pack has unexpected pack_meta.record_type {record_type!r}: {pack_path}"
        )
    schema_version = meta.get("schema_version")
    if schema_version not in {"2", "3"}:
        raise SealError(
            f"the vocabulary pack has unsupported pack_meta.schema_version {schema_version!r}: {pack_path}"
        )

    source_manifest_digest = meta.get("source_manifest_digest")
    if not isinstance(source_manifest_digest, str) or not source_manifest_digest:
        raise SealError(f"the vocabulary pack states no pack_meta.source_manifest_digest: {pack_path}")
    if source_manifest_digest not in valid_manifest_digests:
        raise SealError(
            "the vocabulary pack was derived from a different distribution manifest: "
            f"{source_manifest_digest!r}"
        )
    pack_id = meta.get("pack_id")
    return pack_sha256, source_manifest_digest, str(pack_id) if isinstance(pack_id, str) else "", byte_length


def _verify_semantic_sidecar(
    sidecar_path: Path,
    *,
    resolved_root: Path,
    expected_sidecar_sha256: str | None,
    expected_pack_sha256: str,
    expected_pack_id: str,
    expected_source_manifest_digest: str,
) -> tuple[str, int]:
    """Authenticate a detached `.vpack` semantic sidecar and its binding to the sealed pack."""

    _require_detached_regular_file(sidecar_path, resolved_root, "semantic sidecar")

    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(sidecar_path, flags)
    except OSError as error:
        if error.errno == errno.ELOOP:
            raise SealError(f"the semantic sidecar is a symlink: {sidecar_path}") from error
        raise SealError(f"cannot read the semantic sidecar: {sidecar_path}") from error

    digest = hashlib.sha256()
    total_bytes = 0
    header_bytes: bytes | None = None
    header_len = 0
    header_error: str | None = None
    prefix_len = len(_SIDECAR_MAGIC) + 8
    try:
        with os.fdopen(fd, "rb") as stream:
            before = os.fstat(stream.fileno())
            if not stat.S_ISREG(before.st_mode):
                raise SealError(f"the semantic sidecar is missing or not a regular file: {sidecar_path}")
            prefix = stream.read(prefix_len)
            digest.update(prefix)
            total_bytes += len(prefix)
            if len(prefix) < prefix_len or prefix[: len(_SIDECAR_MAGIC)] != _SIDECAR_MAGIC:
                header_error = f"the semantic sidecar has an invalid magic header: {sidecar_path}"
            else:
                (header_len,) = struct.unpack("<Q", prefix[len(_SIDECAR_MAGIC) :])
                if header_len == 0 or header_len > _MAX_SIDECAR_HEADER_BYTES or prefix_len + header_len > before.st_size:
                    header_error = f"the semantic sidecar header length is invalid: {sidecar_path}"
                else:
                    header_bytes = stream.read(header_len)
                    digest.update(header_bytes)
                    total_bytes += len(header_bytes)
                    if len(header_bytes) != header_len:
                        header_error = f"the semantic sidecar header is truncated: {sidecar_path}"
            for block in iter(lambda: stream.read(_READ_BLOCK), b""):
                digest.update(block)
                total_bytes += len(block)
            after = os.fstat(stream.fileno())
    except OSError as error:
        raise SealError(f"cannot read the semantic sidecar: {sidecar_path}") from error

    before_snap = (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
    after_snap = (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
    if before_snap != after_snap or total_bytes != before.st_size:
        raise SealError(f"the semantic sidecar changed while it was read: {sidecar_path}")

    sidecar_sha256 = "sha256:" + digest.hexdigest()
    if expected_sidecar_sha256 is not None and sidecar_sha256 != expected_sidecar_sha256:
        raise SealError(f"the semantic sidecar differs from the sealed digest: {sidecar_path}")
    if header_error is not None or header_bytes is None:
        raise SealError(header_error or f"cannot read the semantic sidecar header: {sidecar_path}")

    try:
        header = json.loads(
            header_bytes.decode("utf-8"),
            object_pairs_hook=reject_duplicate_keys,
            parse_constant=reject_nonfinite_constant,
        )
    except (UnicodeDecodeError, ValueError) as error:
        raise SealError(f"the semantic sidecar header is not canonical UTF-8 JSON: {sidecar_path}: {error}") from error
    if not isinstance(header, dict) or header.get("recordType") != "AtlasSemanticSidecar":
        raise SealError(f"the semantic sidecar header is not an AtlasSemanticSidecar: {sidecar_path}")
    if header.get("packSha256") != expected_pack_sha256:
        raise SealError("the semantic sidecar was derived from a different vocabulary pack")
    if header.get("sourceManifestDigest") != expected_source_manifest_digest:
        raise SealError("the semantic sidecar was derived from a different distribution manifest")
    if expected_pack_id:
        sidecar_pack_id = header.get("packId")
        if not isinstance(sidecar_pack_id, str) or not sidecar_pack_id:
            raise SealError(f"the semantic sidecar states no packId: {sidecar_path}")
        if sidecar_pack_id != expected_pack_id:
            raise SealError("the semantic sidecar packId differs from the sealed vocabulary pack")
    return sidecar_sha256, total_bytes


def create_seal(
    root: Path | str,
    private_key_path: Path | str,
    signer_identity: str,
    *,
    seal_path: Path | str | None = None,
    parquet_view_path: Path | str | None = None,
    vocabulary_pack: Path | str | None = None,
    semantic_sidecar: Path | str | None = None,
) -> Path:
    """Write one detached seal beside the distribution and return its path.

    Emits `refspec-distribution-seal-2` when neither `vocabulary_pack` nor
    `semantic_sidecar` is supplied, and `refspec-distribution-seal-3` when a
    compiled vocabulary pack (and optional semantic vector sidecar) is bound.
    """

    root = Path(root)
    if root.is_symlink():
        raise SealError(f"the distribution root is a symlink: {root}")
    _reject_symlink_parents(root, "distribution root")
    if not root.is_dir():
        raise SealError(f"the distribution root is not a directory: {root}")
    if not isinstance(signer_identity, str) or not signer_identity.strip():
        raise SealError("the seal signer identity must be non-empty text")
    if semantic_sidecar is not None and vocabulary_pack is None:
        raise SealError("refusing to bind a semantic sidecar without a vocabulary pack")

    manifest_path = root / MANIFEST_MEMBER
    acceptance_path = root / ACCEPTANCE_MEMBER
    for path, label in ((manifest_path, "manifest"), (acceptance_path, "acceptance receipt")):
        if not path.is_file():
            raise SealError(f"refusing to seal a distribution with no {label}: {path}")
    selected = Path(seal_path) if seal_path is not None else default_seal_path(root)
    if selected.is_symlink():
        raise SealError(f"refusing to write the seal through a symlink: {selected}")
    _reject_symlink_parents(selected, "seal file")
    resolved_root = root.resolve()
    if selected.resolve() == resolved_root or resolved_root in selected.resolve().parents:
        raise SealError(f"refusing to write the seal inside the distribution: {selected}")

    manifest = _read_json_object(manifest_path, "manifest")
    acceptance = _read_json_object(acceptance_path, "acceptance receipt")
    distribution_id = manifest.get("distributionId")
    if not isinstance(distribution_id, str) or not distribution_id:
        raise SealError(f"the manifest names no distributionId: {manifest_path}")
    if acceptance.get("distributionId") != distribution_id:
        raise SealError("refusing to seal an acceptance receipt that names a different distribution")
    if acceptance.get("verdict") != "passed":
        raise SealError(f"refusing to seal an acceptance verdict of {acceptance.get('verdict')!r}")

    # A signature over an artifact nobody walked is a promise about bytes the
    # signer never read, so the mint runs exactly the walk the reader runs.
    _walk_distribution(root, manifest)
    manifest_sha256 = _file_sha256(manifest_path, "manifest")
    view_root = Path(parquet_view_path) if parquet_view_path is not None else default_parquet_view_path(root)
    _reject_symlink_parents(view_root, "sealed Parquet view")
    if view_root.is_symlink() or not view_root.is_dir():
        raise SealError(f"the sealed Parquet view is missing or unsafe: {view_root}")
    from refspec.atlas.parquet_view import MANIFEST_FILE as VIEW_MANIFEST_FILE

    view_manifest_sha256 = _file_sha256(view_root / VIEW_MANIFEST_FILE, "Parquet view manifest")
    _walk_parquet_view(
        view_root,
        expected_manifest_sha256=view_manifest_sha256,
        expected_distribution_manifest_sha256=manifest_sha256,
    )

    payload: dict[str, Any] = {
        "acceptanceSha256": _file_sha256(acceptance_path, "acceptance receipt"),
        "distributionId": distribution_id,
        "manifestSha256": manifest_sha256,
        "parquetViewManifestSha256": view_manifest_sha256,
        "sealFormat": SEAL_FORMAT,
    }
    if vocabulary_pack is not None:
        pack_sha256, pack_manifest_digest, pack_id, _ = _verify_vocabulary_pack(
            Path(vocabulary_pack),
            resolved_root=resolved_root,
            expected_pack_sha256=None,
            valid_manifest_digests=frozenset({manifest_sha256, view_manifest_sha256}),
        )
        payload["sealFormat"] = SEAL_FORMAT_V3
        payload["vocabularyPackSha256"] = pack_sha256
        if semantic_sidecar is not None:
            sidecar_sha256, _ = _verify_semantic_sidecar(
                Path(semantic_sidecar),
                resolved_root=resolved_root,
                expected_sidecar_sha256=None,
                expected_pack_sha256=pack_sha256,
                expected_pack_id=pack_id,
                expected_source_manifest_digest=pack_manifest_digest,
            )
            payload["semanticSidecarSha256"] = sidecar_sha256

    seal = {
        "payload": payload,
        "signature": _sign_payload(_canonical_bytes(payload, "seal payload"), Path(private_key_path)),
        "signerIdentity": signer_identity,
        "type": SEAL_TYPE,
    }
    selected.write_bytes(_canonical_bytes(seal, "seal") + b"\n")
    return selected


def verify_seal(
    root: Path | str,
    seal_path: Path | str,
    allowed_signers_path: Path | str,
    *,
    parquet_view_path: Path | str | None = None,
    vocabulary_pack: Path | str | None = None,
    semantic_sidecar: Path | str | None = None,
    previous_created_at: str | None = None,
    reject_distribution_ids: Collection[str] | None = None,
) -> SealVerification:
    """Verify the signature, all bound digests, closed membership, and every pinned byte.

    Supports both `refspec-distribution-seal-2` (distribution + Parquet view)
    and `refspec-distribution-seal-3` (also binding a compiled SQLite vocabulary
    pack and optional `.vpack` semantic vector sidecar with bi-directional
    manifest checks). Optional `previous_created_at` and `reject_distribution_ids`
    guards reject stale/rolled-back or explicitly revoked releases.

    Artifact-internal only: a pass says acceptance ran on these exact bytes. It
    says nothing about whether those bytes faithfully transcribe the publisher
    sources, or whether the captures behind them were complete -- source
    fidelity is the auditor's separate, scheduled job.
    """

    root = Path(root)
    if root.is_symlink():
        raise SealError(f"the distribution root is a symlink: {root}")
    _reject_symlink_parents(root, "distribution root")
    if not root.is_dir():
        raise SealError(f"the distribution root is not a directory: {root}")
    seal_file = Path(seal_path)
    if seal_file.is_symlink():
        raise SealError(f"the seal file is a symlink: {seal_file}")
    _reject_symlink_parents(seal_file, "seal file")
    seal = _read_json_object(seal_file, "seal")
    _require_exact_keys(seal, SEAL_KEYS, "seal")
    payload = seal["payload"]
    signature = seal["signature"]
    signer_identity = seal["signerIdentity"]
    if (
        seal["type"] != SEAL_TYPE
        or not isinstance(payload, dict)
        or not isinstance(signature, str)
        or not isinstance(signer_identity, str)
        or not signer_identity
    ):
        raise SealError(f"the seal is not a well-formed {SEAL_TYPE}: {seal_path}")

    seal_format = payload.get("sealFormat")
    if seal_format == SEAL_FORMAT:
        _require_exact_keys(payload, PAYLOAD_KEYS, "seal payload")
        if vocabulary_pack is not None or semantic_sidecar is not None:
            raise SealError(
                f"seal format {SEAL_FORMAT} does not bind a vocabulary pack or semantic sidecar"
            )
    elif seal_format == SEAL_FORMAT_V3:
        has_sidecar = "semanticSidecarSha256" in payload
        expected_keys = PAYLOAD_KEYS_V3_WITH_SIDECAR if has_sidecar else PAYLOAD_KEYS_V3_BASE
        _require_exact_keys(payload, expected_keys, "seal payload")
        if not has_sidecar and semantic_sidecar is not None:
            raise SealError(f"seal {seal_path} does not bind a semantic sidecar")
    else:
        raise SealError(f"unsupported seal format: {seal_format!r}")

    distribution_id = payload["distributionId"]
    if not isinstance(distribution_id, str) or not distribution_id:
        raise SealError("the seal payload names no distributionId")

    # 1. The signature over the canonical payload. Everything below is a digest
    #    the signature binds, so nothing below means anything until this holds.
    _verify_payload_signature(
        _canonical_bytes(payload, "seal payload"), signature, signer_identity, Path(allowed_signers_path)
    )

    # 2. The manifest the signature was taken over, plus optional anti-rollback guards.
    manifest_path = root / MANIFEST_MEMBER
    manifest_sha256 = _file_sha256(manifest_path, "manifest")
    if manifest_sha256 != payload["manifestSha256"]:
        raise SealError(f"the manifest differs from the sealed digest: {manifest_path}")
    manifest = _read_json_object(manifest_path, "manifest")
    if manifest.get("distributionId") != distribution_id:
        raise SealError(f"the manifest names a different distribution than the seal: {distribution_id}")
    created_at = _check_rollback_guards(
        distribution_id,
        manifest,
        previous_created_at=previous_created_at,
        reject_distribution_ids=reject_distribution_ids,
    )

    # 3. The acceptance receipt, which is what makes the signature attest that
    #    acceptance ran, with which gates, over these bytes.
    acceptance_path = root / ACCEPTANCE_MEMBER
    acceptance_sha256 = _file_sha256(acceptance_path, "acceptance receipt")
    if acceptance_sha256 != payload["acceptanceSha256"]:
        raise SealError(f"the acceptance receipt differs from the sealed digest: {acceptance_path}")

    # 4. Closed membership, then every member and pack streamed from disk. A
    #    pack's `path` names its transport bytes, so `transport` carries that
    #    file's pin.
    walk = _walk_distribution(root, manifest)

    # 5. The served Parquet view beside the distribution, proved against the
    #    third digest the signature binds and paired back to this manifest.
    view_manifest_sha256 = payload["parquetViewManifestSha256"]
    if not isinstance(view_manifest_sha256, str) or not view_manifest_sha256:
        raise SealError("the seal payload names no parquetViewManifestSha256")
    view_root = Path(parquet_view_path) if parquet_view_path is not None else default_parquet_view_path(root)
    table_count, table_byte_length = _walk_parquet_view(
        view_root,
        expected_manifest_sha256=view_manifest_sha256,
        expected_distribution_manifest_sha256=manifest_sha256,
    )

    verified_byte_length = walk.verified_byte_length + table_byte_length
    verified_pack_sha256: str | None = None
    verified_sidecar_sha256: str | None = None

    # 6. For seal-3, authenticate the detached SQLite vocabulary pack (and
    #    optional `.vpack` semantic sidecar) with bi-directional manifest checks.
    if seal_format == SEAL_FORMAT_V3:
        expected_pack_sha256 = payload["vocabularyPackSha256"]
        if not isinstance(expected_pack_sha256, str) or not expected_pack_sha256:
            raise SealError("the seal payload names no vocabularyPackSha256")
        resolved_root = root.resolve()
        pack_file = Path(vocabulary_pack) if vocabulary_pack is not None else default_vocabulary_pack_path(root)
        verified_pack_sha256, pack_manifest_digest, pack_id, pack_byte_length = _verify_vocabulary_pack(
            pack_file,
            resolved_root=resolved_root,
            expected_pack_sha256=expected_pack_sha256,
            valid_manifest_digests=frozenset({manifest_sha256, view_manifest_sha256}),
        )
        verified_byte_length += pack_byte_length

        if "semanticSidecarSha256" in payload:
            expected_sidecar_sha256 = payload["semanticSidecarSha256"]
            if not isinstance(expected_sidecar_sha256, str) or not expected_sidecar_sha256:
                raise SealError("the seal payload names no semanticSidecarSha256")
            sidecar_file = (
                Path(semantic_sidecar) if semantic_sidecar is not None else default_semantic_sidecar_path(root)
            )
            verified_sidecar_sha256, sidecar_byte_length = _verify_semantic_sidecar(
                sidecar_file,
                resolved_root=resolved_root,
                expected_sidecar_sha256=expected_sidecar_sha256,
                expected_pack_sha256=verified_pack_sha256,
                expected_pack_id=pack_id,
                expected_source_manifest_digest=pack_manifest_digest,
            )
            verified_byte_length += sidecar_byte_length

    return SealVerification(
        distribution_id=distribution_id,
        signer_identity=signer_identity,
        manifest_sha256=manifest_sha256,
        acceptance_sha256=acceptance_sha256,
        parquet_view_manifest_sha256=view_manifest_sha256,
        member_count=walk.member_count,
        pack_count=walk.pack_count,
        parquet_table_count=table_count,
        verified_byte_length=verified_byte_length,
        seal_format=seal_format,
        vocabulary_pack_sha256=verified_pack_sha256,
        semantic_sidecar_sha256=verified_sidecar_sha256,
        created_at=created_at,
    )
