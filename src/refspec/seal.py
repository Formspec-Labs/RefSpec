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
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from refspec.input_pin import verify_file_pin
from refspec.release_model import canonical_json_bytes, reject_duplicate_keys, reject_nonfinite_constant

# -2: the compact JSONL packs the summary used to declare are gone, and the
# payload binds the served Parquet view's manifest digest instead.
SEAL_FORMAT = "refspec-distribution-seal-2"
SEAL_TYPE = "RefSpecDistributionSeal"
SIGNATURE_NAMESPACE = "refspec-distribution-seal"
MANIFEST_MEMBER = "atlas-manifest.json"
ACCEPTANCE_MEMBER = "atlas-acceptance.json"
DEFAULT_PARQUET_VIEW_NAME = "parquet-view"
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
_READ_BLOCK = 1024 * 1024
_SSH_KEYGEN_TIMEOUT_SECONDS = 60


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


def create_seal(
    root: Path | str,
    private_key_path: Path | str,
    signer_identity: str,
    *,
    seal_path: Path | str | None = None,
    parquet_view_path: Path | str | None = None,
) -> Path:
    """Write one detached seal beside the distribution and return its path."""

    root = Path(root)
    if not root.is_dir():
        raise SealError(f"the distribution root is not a directory: {root}")
    if not isinstance(signer_identity, str) or not signer_identity.strip():
        raise SealError("the seal signer identity must be non-empty text")
    manifest_path = root / MANIFEST_MEMBER
    acceptance_path = root / ACCEPTANCE_MEMBER
    for path, label in ((manifest_path, "manifest"), (acceptance_path, "acceptance receipt")):
        if not path.is_file():
            raise SealError(f"refusing to seal a distribution with no {label}: {path}")
    selected = Path(seal_path) if seal_path is not None else default_seal_path(root)
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
    from refspec.atlas.parquet_view import MANIFEST_FILE as VIEW_MANIFEST_FILE

    view_manifest_sha256 = _file_sha256(view_root / VIEW_MANIFEST_FILE, "Parquet view manifest")
    _walk_parquet_view(
        view_root,
        expected_manifest_sha256=view_manifest_sha256,
        expected_distribution_manifest_sha256=manifest_sha256,
    )

    payload = {
        "acceptanceSha256": _file_sha256(acceptance_path, "acceptance receipt"),
        "distributionId": distribution_id,
        "manifestSha256": manifest_sha256,
        "parquetViewManifestSha256": view_manifest_sha256,
        "sealFormat": SEAL_FORMAT,
    }
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
) -> SealVerification:
    """Verify the signature, all three bound digests, closed membership, and every pinned byte."""

    root = Path(root)
    if not root.is_dir():
        raise SealError(f"the distribution root is not a directory: {root}")
    seal = _read_json_object(Path(seal_path), "seal")
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
    _require_exact_keys(payload, PAYLOAD_KEYS, "seal payload")
    if payload["sealFormat"] != SEAL_FORMAT:
        raise SealError(f"unsupported seal format: {payload['sealFormat']!r}")
    distribution_id = payload["distributionId"]
    if not isinstance(distribution_id, str) or not distribution_id:
        raise SealError("the seal payload names no distributionId")

    # 1. The signature over the canonical payload. Everything below is a digest
    #    the signature binds, so nothing below means anything until this holds.
    _verify_payload_signature(
        _canonical_bytes(payload, "seal payload"), signature, signer_identity, Path(allowed_signers_path)
    )

    # 2. The manifest the signature was taken over.
    manifest_path = root / MANIFEST_MEMBER
    manifest_sha256 = _file_sha256(manifest_path, "manifest")
    if manifest_sha256 != payload["manifestSha256"]:
        raise SealError(f"the manifest differs from the sealed digest: {manifest_path}")
    manifest = _read_json_object(manifest_path, "manifest")
    if manifest.get("distributionId") != distribution_id:
        raise SealError(f"the manifest names a different distribution than the seal: {distribution_id}")

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

    return SealVerification(
        distribution_id=distribution_id,
        signer_identity=signer_identity,
        manifest_sha256=manifest_sha256,
        acceptance_sha256=acceptance_sha256,
        parquet_view_manifest_sha256=view_manifest_sha256,
        member_count=walk.member_count,
        pack_count=walk.pack_count,
        parquet_table_count=table_count,
        verified_byte_length=walk.verified_byte_length + table_byte_length,
    )
