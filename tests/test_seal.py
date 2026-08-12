"""Prove the distribution seal against the real HEAD-conforming FR Thesaurus build.

Every test runs over a copy of that distribution and of the served Parquet view
beside it, because the negative cases tamper with bytes and the artifacts of
record must survive them untouched.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

from refspec.atlas.parquet_artifact import file_sha256
from refspec.atlas.parquet_view import MANIFEST_FILE as VIEW_MANIFEST_FILE
from refspec.release_model import canonical_json_bytes
from refspec.seal import (
    ACCEPTANCE_MEMBER,
    MANIFEST_MEMBER,
    SIGNATURE_NAMESPACE,
    SealError,
    create_seal,
    default_parquet_view_path,
    default_seal_path,
    verify_seal,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
RELEASE_ROOT = REPOSITORY_ROOT / "output" / "atlas-3.1-federal-register-thesaurus-2025-04-01"
DISTRIBUTION_ROOT = RELEASE_ROOT / "distribution"
PARQUET_VIEW_ROOT = RELEASE_ROOT / "parquet-view"
SIGNER_IDENTITY = "release@refspec.test"

pytestmark = pytest.mark.skipif(
    not (DISTRIBUTION_ROOT / MANIFEST_MEMBER).is_file()
    or not (PARQUET_VIEW_ROOT / VIEW_MANIFEST_FILE).is_file(),
    reason=(
        "the HEAD-conforming Federal Register Thesaurus distribution and its served "
        f"Parquet view are not built at {RELEASE_ROOT.relative_to(REPOSITORY_ROOT)}"
    ),
)


def _generate_key(directory: Path, name: str) -> Path:
    private_key = directory / name
    subprocess.run(
        ["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-C", name, "-f", str(private_key)],
        check=True,
        capture_output=True,
    )
    return private_key


def _write_allowed_signers(path: Path, private_key: Path, identity: str = SIGNER_IDENTITY) -> Path:
    public_key = Path(f"{private_key}.pub").read_text(encoding="utf-8").strip()
    path.write_text(f"{identity} {public_key}\n", encoding="utf-8")
    return path


def _tamper_one_byte(path: Path) -> None:
    payload = bytearray(path.read_bytes())
    payload[len(payload) // 2] ^= 0x01
    path.write_bytes(bytes(payload))


def _sign_bytes(private_key: Path, payload: bytes) -> str:
    completed = subprocess.run(
        ["ssh-keygen", "-Y", "sign", "-q", "-f", str(private_key), "-n", SIGNATURE_NAMESPACE, "-"],
        input=payload,
        check=True,
        capture_output=True,
    )
    return completed.stdout.decode("ascii")


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def signing_key(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return _generate_key(tmp_path_factory.mktemp("release-key"), "release")


@pytest.fixture(scope="module")
def allowed_signers(tmp_path_factory: pytest.TempPathFactory, signing_key: Path) -> Path:
    directory = tmp_path_factory.mktemp("allowed-signers")
    return _write_allowed_signers(directory / "allowed_signers", signing_key)


@pytest.fixture
def distribution(tmp_path: Path) -> Path:
    """Copy both sealed artifacts: the distribution and the view beside it.

    The seal binds three digests, and the third is the served Parquet view's
    manifest. The view sits beside the distribution, so the copy has to keep
    that relationship or `default_parquet_view_path` finds nothing.
    """

    root = tmp_path / "distribution"
    shutil.copytree(DISTRIBUTION_ROOT, root)
    shutil.copytree(PARQUET_VIEW_ROOT, default_parquet_view_path(root))
    return root


@pytest.fixture
def parquet_view(distribution: Path) -> Path:
    return default_parquet_view_path(distribution)


@pytest.fixture
def sealed(distribution: Path, signing_key: Path) -> Path:
    return create_seal(distribution, signing_key, SIGNER_IDENTITY)


def test_seal_is_written_beside_the_distribution_and_verifies_every_member_and_pack(
    distribution: Path,
    sealed: Path,
    allowed_signers: Path,
) -> None:
    assert sealed == default_seal_path(distribution) == distribution.parent / "distribution-seal.json"
    assert sealed.parent == distribution.parent
    assert not sealed.is_relative_to(distribution)

    manifest = json.loads((distribution / MANIFEST_MEMBER).read_text(encoding="utf-8"))
    view = default_parquet_view_path(distribution)
    view_manifest = json.loads((view / VIEW_MANIFEST_FILE).read_text(encoding="utf-8"))
    seal = json.loads(sealed.read_text(encoding="utf-8"))
    assert seal["type"] == "RefSpecDistributionSeal"
    assert seal["signerIdentity"] == SIGNER_IDENTITY
    assert seal["signature"].startswith("-----BEGIN SSH SIGNATURE-----")
    assert set(seal["payload"]) == {
        "acceptanceSha256",
        "distributionId",
        "manifestSha256",
        "parquetViewManifestSha256",
        "sealFormat",
    }

    result = verify_seal(distribution, sealed, allowed_signers)

    assert result.distribution_id == manifest["distributionId"]
    assert result.signer_identity == SIGNER_IDENTITY
    assert result.manifest_sha256 == seal["payload"]["manifestSha256"]
    assert result.acceptance_sha256 == seal["payload"]["acceptanceSha256"]
    assert result.member_count == len(manifest["members"]) == 4
    assert result.pack_count == len(manifest["packs"]) == 2
    # The third bound digest: the served Parquet view beside the distribution,
    # which the manifest cannot declare without a cycle -- the view manifest
    # pins the distribution manifest's own digest.
    assert result.parquet_view_manifest_sha256 == file_sha256(view / VIEW_MANIFEST_FILE)
    assert result.parquet_table_count == len(view_manifest["members"]) == 8
    assert view_manifest["input"]["manifestSha256"] == result.manifest_sha256
    assert result.verified_byte_length == sum(
        [member["byteLength"] for member in manifest["members"]]
        + [pack["transport"]["byteLength"] for pack in manifest["packs"]]
        + [member["byteLength"] for member in view_manifest["members"]]
    )

    # Every file on disk is walked; nothing in the sealed tree is unreached.
    walked = (
        {MANIFEST_MEMBER}
        | {member["path"] for member in manifest["members"]}
        | {pack["path"] for pack in manifest["packs"]}
    )
    assert walked == {
        path.relative_to(distribution).as_posix() for path in distribution.rglob("*") if path.is_file()
    }

    # The bound acceptance digest is the receipt's own digest, so the signature
    # transitively attests the gate results recorded for exactly these bytes.
    acceptance = next(member for member in manifest["members"] if member["role"] == "acceptance")
    assert result.acceptance_sha256 == acceptance["digest"]


def test_a_tampered_pack_fails_the_member_walk_naming_the_pack(
    distribution: Path,
    sealed: Path,
    allowed_signers: Path,
) -> None:
    """A valid signature over an intact manifest is not enough: the bytes are walked."""

    manifest = json.loads((distribution / MANIFEST_MEMBER).read_text(encoding="utf-8"))
    pack = manifest["packs"][0]["path"]
    _tamper_one_byte(distribution / pack)

    with pytest.raises(SealError, match=f"pack differs from the sealed manifest: {pack}"):
        verify_seal(distribution, sealed, allowed_signers)


def test_a_tampered_member_fails_the_member_walk_naming_the_member(
    distribution: Path,
    sealed: Path,
    allowed_signers: Path,
) -> None:
    _tamper_one_byte(distribution / "atlas-source-accounting.json")

    with pytest.raises(SealError, match="member differs from the sealed manifest: atlas-source-accounting.json"):
        verify_seal(distribution, sealed, allowed_signers)


def test_a_tampered_manifest_fails_before_the_member_walk(
    distribution: Path,
    sealed: Path,
    allowed_signers: Path,
) -> None:
    _tamper_one_byte(distribution / MANIFEST_MEMBER)

    with pytest.raises(SealError, match="manifest differs from the sealed digest"):
        verify_seal(distribution, sealed, allowed_signers)


def test_a_tampered_acceptance_receipt_fails_the_receipt_binding(
    distribution: Path,
    sealed: Path,
    allowed_signers: Path,
) -> None:
    _tamper_one_byte(distribution / ACCEPTANCE_MEMBER)

    with pytest.raises(SealError, match="acceptance receipt differs from the sealed digest"):
        verify_seal(distribution, sealed, allowed_signers)


def test_another_key_in_the_allowed_signers_file_fails_the_signature(
    tmp_path: Path,
    distribution: Path,
    sealed: Path,
) -> None:
    other_key = _generate_key(tmp_path, "other")
    other_signers = _write_allowed_signers(tmp_path / "allowed_signers", other_key)

    with pytest.raises(SealError, match="ssh-keygen refused to verify this seal"):
        verify_seal(distribution, sealed, other_signers)


def test_create_seal_refuses_a_target_inside_the_distribution(
    distribution: Path,
    signing_key: Path,
) -> None:
    inside = distribution / "packs" / "atlas-seal.json"

    with pytest.raises(SealError, match="refusing to write the seal inside the distribution"):
        create_seal(distribution, signing_key, SIGNER_IDENTITY, seal_path=inside)

    assert not inside.exists()


def test_create_seal_refuses_a_distribution_with_no_acceptance_receipt(
    distribution: Path,
    signing_key: Path,
) -> None:
    (distribution / ACCEPTANCE_MEMBER).unlink()

    with pytest.raises(SealError, match="refusing to seal a distribution with no acceptance receipt"):
        create_seal(distribution, signing_key, SIGNER_IDENTITY)

    assert not default_seal_path(distribution).exists()


def test_create_seal_refuses_a_distribution_with_no_manifest(
    distribution: Path,
    signing_key: Path,
) -> None:
    (distribution / MANIFEST_MEMBER).unlink()

    with pytest.raises(SealError, match="refusing to seal a distribution with no manifest"):
        create_seal(distribution, signing_key, SIGNER_IDENTITY)


def test_a_tampered_parquet_table_fails_the_view_walk(
    distribution: Path,
    parquet_view: Path,
    sealed: Path,
    allowed_signers: Path,
) -> None:
    """The served projection is outside the distribution; the seal payload reaches it."""

    view_manifest = json.loads((parquet_view / VIEW_MANIFEST_FILE).read_text(encoding="utf-8"))
    table = view_manifest["members"][0]["path"]
    assert table.startswith("tables/") and table.endswith(".parquet")
    _tamper_one_byte(parquet_view / table)

    with pytest.raises(SealError, match="the sealed Parquet view does not verify"):
        verify_seal(distribution, sealed, allowed_signers)


def test_a_tampered_view_manifest_fails_against_the_sealed_view_digest(
    distribution: Path,
    parquet_view: Path,
    sealed: Path,
    allowed_signers: Path,
) -> None:
    _tamper_one_byte(parquet_view / VIEW_MANIFEST_FILE)

    with pytest.raises(SealError, match="Parquet view manifest differs from the sealed digest"):
        verify_seal(distribution, sealed, allowed_signers)


def test_a_missing_parquet_view_fails_the_seal(
    distribution: Path,
    parquet_view: Path,
    sealed: Path,
    allowed_signers: Path,
) -> None:
    """A distribution copied without its served view is not the sealed artifact."""

    shutil.rmtree(parquet_view)

    with pytest.raises(SealError, match="sealed Parquet view is missing or unsafe"):
        verify_seal(distribution, sealed, allowed_signers)


def test_a_file_added_to_the_sealed_tree_is_refused_as_a_non_member(
    distribution: Path,
    sealed: Path,
    allowed_signers: Path,
) -> None:
    """Membership is closed: every digest still holds, and the artifact is still refused."""

    extra = distribution / "packs" / "extra-note.txt"
    extra.write_text("added after the seal was minted\n", encoding="utf-8")

    with pytest.raises(SealError, match=re.escape("packs/extra-note.txt is not a member")):
        verify_seal(distribution, sealed, allowed_signers)

    extra.unlink()
    (distribution / "packs" / "spare").mkdir()

    with pytest.raises(SealError, match=re.escape("packs/spare is a directory the sealed distribution does not")):
        verify_seal(distribution, sealed, allowed_signers)


def test_a_symlinked_member_is_refused_before_its_digest_is_taken(
    tmp_path: Path,
    distribution: Path,
    sealed: Path,
    allowed_signers: Path,
) -> None:
    """A link's bytes live outside the sealed set, so a pin taken through it proves nothing."""

    member = distribution / "atlas-source-accounting.json"
    outside = tmp_path / "atlas-source-accounting.json"
    shutil.move(member, outside)
    member.symlink_to(outside)

    with pytest.raises(SealError, match=re.escape("the distribution holds a symlink: atlas-source-accounting.json")):
        verify_seal(distribution, sealed, allowed_signers)


def test_a_symlinked_directory_inside_the_sealed_tree_is_refused(
    tmp_path: Path,
    distribution: Path,
    sealed: Path,
    allowed_signers: Path,
) -> None:
    inner = distribution / "packs" / "sources"
    outside = tmp_path / "sources"
    shutil.move(inner, outside)
    inner.symlink_to(outside, target_is_directory=True)

    with pytest.raises(SealError, match=re.escape("the distribution holds a symlink: packs/sources")):
        verify_seal(distribution, sealed, allowed_signers)


def test_a_payload_carrying_an_extra_key_is_refused_for_strictness_not_for_its_signature(
    tmp_path: Path,
    distribution: Path,
    sealed: Path,
    signing_key: Path,
    allowed_signers: Path,
) -> None:
    """An unknown payload field is refused, never ignored — even correctly signed."""

    seal = _read_json(sealed)
    payload = dict(seal["payload"]) | {"rebuildUrl": "https://example.org/rebuild"}
    forged = tmp_path / "forged-seal.json"
    forged.write_bytes(
        canonical_json_bytes(
            {
                "payload": payload,
                "signature": _sign_bytes(signing_key, canonical_json_bytes(payload)),
                "signerIdentity": SIGNER_IDENTITY,
                "type": seal["type"],
            }
        )
        + b"\n"
    )

    with pytest.raises(SealError, match=re.escape("the seal payload must hold exactly")) as refusal:
        verify_seal(distribution, forged, allowed_signers)

    assert "rebuildUrl" in str(refusal.value)
    assert "ssh-keygen" not in str(refusal.value)


def test_a_seal_carrying_an_extra_top_level_key_is_refused(
    tmp_path: Path,
    distribution: Path,
    sealed: Path,
    allowed_signers: Path,
) -> None:
    forged = tmp_path / "forged-seal.json"
    forged.write_bytes(canonical_json_bytes(_read_json(sealed) | {"mintedAt": "2026-08-11"}) + b"\n")

    with pytest.raises(SealError, match=re.escape("the seal must hold exactly")) as refusal:
        verify_seal(distribution, forged, allowed_signers)

    assert "mintedAt" in str(refusal.value)


def test_create_seal_refuses_to_sign_a_distribution_that_does_not_verify(
    distribution: Path,
    signing_key: Path,
) -> None:
    """The mint runs the reader's walk first, so no signature is ever taken over broken bytes."""

    _tamper_one_byte(distribution / "atlas-source-accounting.json")

    with pytest.raises(SealError, match="member differs from the sealed manifest: atlas-source-accounting.json"):
        create_seal(distribution, signing_key, SIGNER_IDENTITY)

    assert not default_seal_path(distribution).exists()


def test_create_seal_refuses_to_sign_a_distribution_with_an_added_file(
    distribution: Path,
    signing_key: Path,
) -> None:
    (distribution / "packs" / "extra-note.txt").write_text("added before the seal was minted\n", encoding="utf-8")

    with pytest.raises(SealError, match=re.escape("packs/extra-note.txt is not a member")):
        create_seal(distribution, signing_key, SIGNER_IDENTITY)

    assert not default_seal_path(distribution).exists()
