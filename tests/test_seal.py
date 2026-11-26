"""Prove the distribution seal against the real HEAD-conforming FR Thesaurus build.

Every test runs over a copy of that distribution and of the served Parquet view
beside it, because the negative cases tamper with bytes and the artifacts of
record must survive them untouched.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import sqlite3
import struct
import subprocess
from pathlib import Path
from typing import Any

import pytest

from refspec.atlas.compact_pack import CompactRecordRole, normalize_compact_record
from refspec.atlas.generation import select_atlas_generation
from refspec.atlas.parquet_artifact import canonical_payload_sha256, file_sha256
from refspec.atlas.parquet_tables import AtlasParquetTableWriter
from refspec.atlas.parquet_view import MANIFEST_FILE as VIEW_MANIFEST_FILE
from refspec.atlas.parquet_view import seal_atlas_parquet_view
from refspec.release_model import canonical_json_bytes
from refspec.seal import (
    ACCEPTANCE_MEMBER,
    MANIFEST_MEMBER,
    SEAL_FORMAT,
    SEAL_FORMAT_V3,
    SIGNATURE_NAMESPACE,
    SealError,
    create_seal,
    default_parquet_view_path,
    default_seal_path,
    default_semantic_sidecar_path,
    default_vocabulary_pack_path,
    verify_seal,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
RELEASE_ROOT = REPOSITORY_ROOT / "output" / "atlas-3.1-federal-register-thesaurus-2025-04-01"
SIGNER_IDENTITY = "release@refspec.test"

# The HEAD-conforming Federal Register Thesaurus distribution and its served
# Parquet view: `make release-atlas-federal-register-thesaurus` writes them in
# seconds, and `make test-package` and `make build-derived` both run it first,
# so a missing release fails here rather than skipping.


def _generate_key(directory: Path, name: str) -> Path:
    """Generate a throwaway ed25519 signing key and return its private-key path."""
    private_key = directory / name
    subprocess.run(
        ["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-C", name, "-f", str(private_key)],
        check=True,
        capture_output=True,
    )
    return private_key


def _write_allowed_signers(path: Path, private_key: Path, identity: str = SIGNER_IDENTITY) -> Path:
    """Write an allowed_signers file pairing identity with the key's public half."""
    public_key = Path(f"{private_key}.pub").read_text(encoding="utf-8").strip()
    path.write_text(f"{identity} {public_key}\n", encoding="utf-8")
    return path


def _tamper_one_byte(path: Path) -> None:
    """Flip one bit in the middle of the file's bytes."""
    payload = bytearray(path.read_bytes())
    payload[len(payload) // 2] ^= 0x01
    path.write_bytes(bytes(payload))


def _sign_bytes(private_key: Path, payload: bytes) -> str:
    """Sign payload with ssh-keygen under SIGNATURE_NAMESPACE, returning the armored signature."""
    completed = subprocess.run(
        ["ssh-keygen", "-Y", "sign", "-q", "-f", str(private_key), "-n", SIGNATURE_NAMESPACE, "-"],
        input=payload,
        check=True,
        capture_output=True,
    )
    return completed.stdout.decode("ascii")


def _read_json(path: Path) -> dict[str, Any]:
    """Load a JSON file as a dict."""
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
    selected = select_atlas_generation(RELEASE_ROOT / "distribution")
    shutil.copytree(selected.distribution, root)
    shutil.copytree(selected.parquet_view, default_parquet_view_path(root))
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
    """Pins the seal path and shape, all three bound digests, four members, two packs and the closed walk."""
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
    # Three since 1b5fd0ab (2026-08-19): the FR release's derived graph carries
    # content, so a derived view pack joins the source and catalog packs. This
    # test skipped until REF-071 and still said two.
    assert result.pack_count == len(manifest["packs"]) == 3
    # The third bound digest: the served Parquet view beside the distribution,
    # which the manifest cannot declare without a cycle -- the view manifest
    # pins the distribution manifest's own digest.
    assert result.parquet_view_manifest_sha256 == file_sha256(view / VIEW_MANIFEST_FILE)
    # Nine since ae23819d (2026-08-19) added the derived-relations table.
    assert result.parquet_table_count == len(view_manifest["members"]) == 9
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
    """Pins refusal naming the tampered member that differs from the sealed manifest."""
    _tamper_one_byte(distribution / "atlas-source-accounting.json")

    with pytest.raises(SealError, match="member differs from the sealed manifest: atlas-source-accounting.json"):
        verify_seal(distribution, sealed, allowed_signers)


def test_a_tampered_manifest_fails_before_the_member_walk(
    distribution: Path,
    sealed: Path,
    allowed_signers: Path,
) -> None:
    """Pins refusal when the manifest itself differs from the sealed digest, before any member walk."""
    _tamper_one_byte(distribution / MANIFEST_MEMBER)

    with pytest.raises(SealError, match="manifest differs from the sealed digest"):
        verify_seal(distribution, sealed, allowed_signers)


def test_a_tampered_acceptance_receipt_fails_the_receipt_binding(
    distribution: Path,
    sealed: Path,
    allowed_signers: Path,
) -> None:
    """Pins refusal when the acceptance receipt differs from its sealed digest."""
    _tamper_one_byte(distribution / ACCEPTANCE_MEMBER)

    with pytest.raises(SealError, match="acceptance receipt differs from the sealed digest"):
        verify_seal(distribution, sealed, allowed_signers)


def test_another_key_in_the_allowed_signers_file_fails_the_signature(
    tmp_path: Path,
    distribution: Path,
    sealed: Path,
) -> None:
    """Pins refusal when the seal is verified against a different key's allowed_signers file."""
    other_key = _generate_key(tmp_path, "other")
    other_signers = _write_allowed_signers(tmp_path / "allowed_signers", other_key)

    with pytest.raises(SealError, match="ssh-keygen refused to verify this seal"):
        verify_seal(distribution, sealed, other_signers)


def test_create_seal_refuses_a_target_inside_the_distribution(
    distribution: Path,
    signing_key: Path,
) -> None:
    """Pins refusal to write the seal inside the distribution, leaving no file behind."""
    inside = distribution / "packs" / "atlas-seal.json"

    with pytest.raises(SealError, match="refusing to write the seal inside the distribution"):
        create_seal(distribution, signing_key, SIGNER_IDENTITY, seal_path=inside)

    assert not inside.exists()


def test_create_seal_refuses_a_distribution_with_no_acceptance_receipt(
    distribution: Path,
    signing_key: Path,
) -> None:
    """Pins refusal to seal a distribution with no acceptance receipt, leaving no seal behind."""
    (distribution / ACCEPTANCE_MEMBER).unlink()

    with pytest.raises(SealError, match="refusing to seal a distribution with no acceptance receipt"):
        create_seal(distribution, signing_key, SIGNER_IDENTITY)

    assert not default_seal_path(distribution).exists()


def test_create_seal_refuses_a_distribution_with_no_manifest(
    distribution: Path,
    signing_key: Path,
) -> None:
    """Pins refusal to seal a distribution with no manifest."""
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
    """Pins refusal when the view manifest differs from the sealed view digest."""
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
    """Pins refusal of a symlinked directory inside the sealed tree."""
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
    """Pins refusal of an unknown top-level seal key, naming it."""
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
    """Pins that minting refuses an added file and leaves no seal behind."""
    (distribution / "packs" / "extra-note.txt").write_text("added before the seal was minted\n", encoding="utf-8")

    with pytest.raises(SealError, match=re.escape("packs/extra-note.txt is not a member")):
        create_seal(distribution, signing_key, SIGNER_IDENTITY)

    assert not default_seal_path(distribution).exists()


def test_seal_cli_mints_and_verifies_selected_generation(
    tmp_path, distribution, signing_key, allowed_signers, monkeypatch, capsys,
):
    import sys

    from tools import seal_distribution
    generation = tmp_path / ".selected.generations" / ("a" * 32)
    generation.mkdir(parents=True)
    view = default_parquet_view_path(distribution)
    distribution.rename(generation / "distribution")
    view.rename(generation / "parquet-view")
    (generation / "generation-report.json").write_text("{}")
    selection = tmp_path / "selected"
    selection.symlink_to((generation / "distribution").relative_to(tmp_path))
    monkeypatch.setattr(sys, "argv", ["seal", "mint", "--selection", str(selection),
        "--private-key", str(signing_key), "--signer-identity", SIGNER_IDENTITY])
    assert seal_distribution.main() == 0
    minted = json.loads(capsys.readouterr().out)
    assert minted["sealPath"] == str(generation / "distribution-seal.json")
    monkeypatch.setattr(sys, "argv", ["seal", "verify", "--selection", str(selection),
        "--allowed-signers", str(allowed_signers)])
    assert seal_distribution.main() == 0
    verified = json.loads(capsys.readouterr().out)
    assert verified["distribution_id"] == minted["distributionId"]
    assert verified["manifest_sha256"] == minted["manifestSha256"]


# ---------------------------------------------------------------------------
# Self-contained seal-2 backward compatibility and seal-3 pack/sidecar tests
# ---------------------------------------------------------------------------


def _write_minimal_distribution_and_view(
    base_dir: Path,
    *,
    distribution_id: str = "urn:ref:atlas-distribution:3:bounded:2026-08-21:test",
    created_at: str = "2026-08-21T00:00:00+00:00",
) -> tuple[Path, Path]:
    """Create a minimal closed-membership distribution + sealed Parquet view in tmp_path."""

    root = base_dir / "distribution"
    (root / "packs" / "sources").mkdir(parents=True)

    d1 = "sha256:" + "1" * 64
    d2 = "sha256:" + "2" * 64
    d3 = "sha256:" + "3" * 64
    d4 = "sha256:" + "4" * 64

    pack_path = root / "packs" / "sources" / "sample.nq.zst"
    pack_bytes = b"sample-pack-bytes-v3-seal-test\n"
    pack_path.write_bytes(pack_bytes)
    content_digest = "sha256:" + hashlib.sha256(pack_bytes).hexdigest()
    pack_id = "urn:ref:atlas:pack:" + content_digest.removeprefix("sha256:")

    asserted_inventory = [{"contentDigest": content_digest, "packId": pack_id, "quadCount": 1}]
    asserted_inventory_digest = canonical_payload_sha256(asserted_inventory)
    empty_inventory_digest = canonical_payload_sha256([])
    contract_digest = "sha256:" + "a" * 64

    accounting_path = root / "atlas-source-accounting.json"
    accounting_path.write_bytes(canonical_json_bytes({"distributionId": distribution_id}) + b"\n")

    acceptance_path = root / ACCEPTANCE_MEMBER
    acceptance_path.write_bytes(
        canonical_json_bytes(
            {
                "distributionId": distribution_id,
                "evaluatedAt": created_at,
                "type": "AtlasAcceptance",
                "verdict": "passed",
                "version": "3.1",
            }
        )
        + b"\n"
    )

    summary: dict[str, Any] = {
        "assertedInventoryDigest": asserted_inventory_digest,
        "contractDigest": contract_digest,
        "distributionId": distribution_id,
        "type": "AtlasConstructionSummary",
        "version": "3.1",
    }
    summary["canonicalPayloadDigest"] = canonical_payload_sha256(summary)
    summary_path = root / "atlas-construction-summary.json"
    summary_path.write_bytes(canonical_json_bytes(summary) + b"\n")

    def _member_row(path: Path, role: str) -> dict[str, Any]:
        return {
            "byteLength": path.stat().st_size,
            "digest": file_sha256(path),
            "mediaType": "application/json",
            "path": path.relative_to(root).as_posix(),
            "role": role,
        }

    manifest: dict[str, Any] = {
        "binding": {
            "contractDigest": contract_digest,
            "ontologyDigest": "sha256:" + "b" * 64,
        },
        "counts": {},
        "createdAt": created_at,
        "distributionId": distribution_id,
        "format": "refspec-atlas-packed-nquads-3.1",
        "graphs": [
            {
                "id": "urn:ref:graph:asserted",
                "inventoryDigest": asserted_inventory_digest,
                "packCount": 1,
                "quadCount": 1,
                "role": "asserted",
            },
            {
                "id": "urn:ref:graph:projection",
                "inventoryDigest": empty_inventory_digest,
                "packCount": 0,
                "quadCount": 0,
                "role": "projection",
            },
            {
                "id": "urn:ref:graph:derived",
                "inventoryDigest": empty_inventory_digest,
                "packCount": 0,
                "quadCount": 0,
                "role": "derived",
            },
        ],
        "members": [
            _member_row(accounting_path, "sourceAccounting"),
            _member_row(acceptance_path, "acceptance"),
            _member_row(summary_path, "constructionSummary"),
        ],
        "packs": [
            {
                "content": {"byteLength": len(pack_bytes), "digest": content_digest},
                "graphCounts": {"asserted": 1, "derived": 0, "projection": 0},
                "packId": pack_id,
                "path": pack_path.relative_to(root).as_posix(),
                "transport": {
                    "byteLength": len(pack_bytes),
                    "digest": file_sha256(pack_path),
                },
            }
        ],
        "schemaVersion": "3.1",
        "type": "AtlasManifest",
    }
    manifest["canonicalPayloadDigest"] = canonical_payload_sha256(manifest)
    manifest_path = root / MANIFEST_MEMBER
    manifest_path.write_bytes(canonical_json_bytes(manifest) + b"\n")

    release = "urn:test:atlas-release"
    source_record = "urn:ref:atlas-source-record:" + "5" * 64
    statement = "urn:ref:atlas-assertion:" + "3" * 64
    rows = {
        CompactRecordRole.RESOURCE: {
            "contentDigest": d1,
            "definition": "A test resource.",
            "id": "urn:test:resource",
            "notations": ["T-1"],
            "notes": [],
            "recordStatus": "active",
            "release": release,
            "resourceProfile": "conceptScheme",
            "scheme": "urn:test:scheme",
            "semanticRing": "subject",
            "sourceRecord": source_record,
        },
        CompactRecordRole.LABEL: {
            "contentDigest": d2,
            "id": "urn:ref:atlas-label:" + "7" * 64,
            "labelRole": "preferred",
            "language": "en",
            "release": release,
            "resource": "urn:test:resource",
            "sourceRecord": source_record,
            "value": "Test resource",
        },
        CompactRecordRole.STATEMENT: {
            "assertedAt": "2026-08-07T00:00:00+00:00",
            "assertionIdentityDigest": d3,
            "contentDigest": d4,
            "id": statement,
            "object": "urn:test:parent",
            "policy": "urn:ref:atlas-policy:" + "6" * 64,
            "predicate": "http://www.w3.org/2004/02/skos/core#broader",
            "semanticRing": "subject",
            "sourceRelease": release,
            "statementType": "NativeRelationAssertion",
            "subject": "urn:test:resource",
            "targetRelease": release,
        },
        CompactRecordRole.EVIDENCE_BINDING: {
            "assertionOrigin": "urn:test:origin",
            "attestedAt": "2026-08-07T00:00:00+00:00",
            "attestor": "urn:test:reviewer",
            "attestorKind": "urn:test:attestor-kind",
            "contentDigest": d2,
            "decision": "urn:test:approved",
            "epistemicBasis": "urn:test:basis",
            "evidenceRole": "urn:test:role",
            "evidenceSourceDigest": d1,
            "evidentiaryFunction": "urn:test:function",
            "id": "urn:ref:atlas-evidence:" + "2" * 64,
            "sourceRecord": source_record,
            "statement": statement,
        },
        CompactRecordRole.SOURCE_RECORD: {
            "contentDigest": d4,
            "id": source_record,
            "nativePayload": {"publisher": "Example"},
            "representsResource": "urn:test:resource",
            "sourceDigest": d3,
            "sourceLocator": "https://example.test/source",
            "sourceRelease": "urn:test:source-release",
        },
        CompactRecordRole.RELEASE: {
            "contentDigest": d1,
            "id": release,
            "identifier": "test-release",
            "issued": "2026-08-07",
            "membershipMode": "complete",
            "releaseType": "AtlasRelease",
            "resourceProfile": "conceptScheme",
            "scheme": "urn:test:scheme",
            "semanticRing": "subject",
        },
        CompactRecordRole.IDENTIFIER: {
            "contentDigest": d2,
            "id": "urn:ref:atlas-identifier:" + "8" * 64,
            "identifierScheme": "urn:test:identifier-scheme",
            "identifierValue": "T-1",
            "identifies": "urn:test:resource",
            "sourceRecord": source_record,
        },
        CompactRecordRole.LIFECYCLE_EVENT: {
            "appliesTo": "urn:test:resource",
            "contentDigest": d3,
            "effectiveDate": "2026-08-07T00:00:00+00:00",
            "id": "urn:test:event",
            "lifecycleEventKind": "urn:test:created",
            "sourceRecords": [source_record],
            "toRelease": release,
        },
    }
    staged = base_dir / "staged-tables"
    writer = AtlasParquetTableWriter(staged)
    try:
        for role, record in rows.items():
            writer.add(role, normalize_compact_record(role, record))
        writer.close()
    except BaseException:
        writer.__exit__()
        raise

    view_root = default_parquet_view_path(root)
    seal_atlas_parquet_view(
        root,
        staged,
        view_root,
        expected_manifest_digest=file_sha256(manifest_path),
        agency_projection={
            "status": "notEmitted",
            "missingReleaseKeys": ["regulations-gov-agencies-roster-2026-08-16"],
        },
        derived_relations={"status": "notEmitted"},
    )
    return root, view_root


def _write_test_vocabulary_pack(
    path: Path,
    *,
    source_manifest_digest: str,
    pack_id: str = "pack-test-0001",
    record_type: str = "AtlasVocabularyPack",
    schema_version: str = "3",
) -> Path:
    con = sqlite3.connect(str(path))
    try:
        con.execute("CREATE TABLE pack_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        con.executemany(
            "INSERT INTO pack_meta (key, value) VALUES (?, ?)",
            [
                ("pack_id", pack_id),
                ("record_type", record_type),
                ("schema_version", schema_version),
                ("source_manifest_digest", source_manifest_digest),
            ],
        )
        con.commit()
    finally:
        con.close()
    return path


def _write_test_semantic_sidecar(
    path: Path,
    *,
    pack_sha256: str,
    source_manifest_digest: str,
    pack_id: str | None = "pack-test-0001",
) -> Path:
    header: dict[str, Any] = {
        "dimensions": 4,
        "mappedResourceCount": 1,
        "maxRid": 1,
        "mode": "flat_f16",
        "modelId": "test-encoder",
        "nClusters": 0,
        "packSha256": pack_sha256,
        "recordType": "AtlasSemanticSidecar",
        "schemaVersion": "2",
        "sections": {},
        "sourceManifestDigest": source_manifest_digest,
        "uniqueVectorCount": 1,
    }
    if pack_id is not None:
        header["packId"] = pack_id
    header_bytes = canonical_json_bytes(header)
    payload = b"RFVP0001" + struct.pack("<Q", len(header_bytes)) + header_bytes + (b"\x00" * 64)
    path.write_bytes(payload)
    return path


def test_v2_seal_remains_backward_compatible_and_refuses_pack_verification(
    tmp_path: Path,
    signing_key: Path,
    allowed_signers: Path,
) -> None:
    """Omitting vocabulary_pack emits seal-2 and verifies cleanly while refusing unexpected pack args."""

    root, _view = _write_minimal_distribution_and_view(tmp_path)
    seal_path = create_seal(root, signing_key, SIGNER_IDENTITY)
    seal_doc = _read_json(seal_path)
    assert seal_doc["payload"]["sealFormat"] == SEAL_FORMAT
    assert set(seal_doc["payload"]) == {
        "acceptanceSha256",
        "distributionId",
        "manifestSha256",
        "parquetViewManifestSha256",
        "sealFormat",
    }

    verified = verify_seal(root, seal_path, allowed_signers)
    assert verified.seal_format == SEAL_FORMAT
    assert verified.vocabulary_pack_sha256 is None
    assert verified.semantic_sidecar_sha256 is None
    assert verified.created_at == "2026-08-21T00:00:00+00:00"

    pack = _write_test_vocabulary_pack(
        default_vocabulary_pack_path(root),
        source_manifest_digest=verified.manifest_sha256,
    )
    with pytest.raises(SealError, match="does not bind a vocabulary pack"):
        verify_seal(root, seal_path, allowed_signers, vocabulary_pack=pack)


def test_v3_seal_binds_vocabulary_pack_and_optional_sidecar(
    tmp_path: Path,
    signing_key: Path,
    allowed_signers: Path,
) -> None:
    """seal-3 binds vocabularyPackSha256 and optional semanticSidecarSha256 with bi-directional digests."""

    root, view = _write_minimal_distribution_and_view(tmp_path)
    manifest_digest = file_sha256(root / MANIFEST_MEMBER)
    view_digest = file_sha256(view / VIEW_MANIFEST_FILE)

    # 1. Pack bound to distribution manifest digest (no sidecar)
    pack = _write_test_vocabulary_pack(
        default_vocabulary_pack_path(root),
        source_manifest_digest=manifest_digest,
    )
    seal_pack_only = create_seal(
        root,
        signing_key,
        SIGNER_IDENTITY,
        seal_path=tmp_path / "distribution-pack-seal.json",
        vocabulary_pack=pack,
    )
    payload_pack_only = _read_json(seal_pack_only)["payload"]
    assert payload_pack_only["sealFormat"] == SEAL_FORMAT_V3
    assert set(payload_pack_only) == {
        "acceptanceSha256",
        "distributionId",
        "manifestSha256",
        "parquetViewManifestSha256",
        "sealFormat",
        "vocabularyPackSha256",
    }

    verified_pack = verify_seal(root, seal_pack_only, allowed_signers)
    assert verified_pack.seal_format == SEAL_FORMAT_V3
    assert verified_pack.vocabulary_pack_sha256 == file_sha256(pack)
    assert verified_pack.semantic_sidecar_sha256 is None

    # 2. Pack bound to Parquet view manifest digest + semantic sidecar
    pack_view = _write_test_vocabulary_pack(
        tmp_path / "vocabulary-pack-view.sqlite",
        source_manifest_digest=view_digest,
        pack_id="pack-view-0002",
    )
    pack_view_sha = file_sha256(pack_view)
    sidecar = _write_test_semantic_sidecar(
        default_semantic_sidecar_path(root),
        pack_sha256=pack_view_sha,
        source_manifest_digest=view_digest,
        pack_id="pack-view-0002",
    )
    seal_with_sidecar = create_seal(
        root,
        signing_key,
        SIGNER_IDENTITY,
        vocabulary_pack=pack_view,
        semantic_sidecar=sidecar,
    )
    payload_full = _read_json(seal_with_sidecar)["payload"]
    assert payload_full["sealFormat"] == SEAL_FORMAT_V3
    assert payload_full["vocabularyPackSha256"] == pack_view_sha
    assert payload_full["semanticSidecarSha256"] == file_sha256(sidecar)

    verified_full = verify_seal(
        root,
        seal_with_sidecar,
        allowed_signers,
        vocabulary_pack=pack_view,
        semantic_sidecar=sidecar,
    )
    assert verified_full.seal_format == SEAL_FORMAT_V3
    assert verified_full.vocabulary_pack_sha256 == pack_view_sha
    assert verified_full.semantic_sidecar_sha256 == file_sha256(sidecar)
    assert verified_full.verified_byte_length > pack_view.stat().st_size + sidecar.stat().st_size

    # Passing a sidecar against a pack-only seal-3 must be refused.
    with pytest.raises(SealError, match="does not bind a semantic sidecar"):
        verify_seal(root, seal_pack_only, allowed_signers, vocabulary_pack=pack, semantic_sidecar=sidecar)


def test_v3_seal_rejects_tamper_pack_swap_and_symlinks(
    tmp_path: Path,
    signing_key: Path,
    allowed_signers: Path,
) -> None:
    """seal-3 refuses tampered bytes, cross-manifest pack swaps, sidecar swaps, and symlinks."""

    root, _view = _write_minimal_distribution_and_view(tmp_path)
    manifest_digest = file_sha256(root / MANIFEST_MEMBER)

    # Sidecar without pack is refused.
    orphan_sidecar = _write_test_semantic_sidecar(
        tmp_path / "orphan.vpack",
        pack_sha256="sha256:" + "0" * 64,
        source_manifest_digest=manifest_digest,
    )
    with pytest.raises(SealError, match="without a vocabulary pack"):
        create_seal(root, signing_key, SIGNER_IDENTITY, semantic_sidecar=orphan_sidecar)

    # Pack derived from a different distribution manifest is refused at mint time (anti-pack-swap).
    wrong_pack = _write_test_vocabulary_pack(
        tmp_path / "wrong-pack.sqlite",
        source_manifest_digest="sha256:" + "f" * 64,
    )
    with pytest.raises(SealError, match="different distribution manifest"):
        create_seal(root, signing_key, SIGNER_IDENTITY, vocabulary_pack=wrong_pack)

    # Pack placed inside the distribution directory is refused.
    inside_pack = _write_test_vocabulary_pack(
        root / "inside-pack.sqlite",
        source_manifest_digest=manifest_digest,
    )
    with pytest.raises(SealError, match="inside-pack.sqlite is not a member"):
        create_seal(root, signing_key, SIGNER_IDENTITY, vocabulary_pack=inside_pack)
    inside_pack.unlink()

    # Mint valid v3 seal with pack + sidecar.
    pack = _write_test_vocabulary_pack(
        default_vocabulary_pack_path(root),
        source_manifest_digest=manifest_digest,
    )
    pack_sha = file_sha256(pack)
    sidecar = _write_test_semantic_sidecar(
        default_semantic_sidecar_path(root),
        pack_sha256=pack_sha,
        source_manifest_digest=manifest_digest,
    )

    # Sidecar bound to a different pack SHA is refused at mint time.
    mismatched_sidecar = _write_test_semantic_sidecar(
        tmp_path / "mismatched.vpack",
        pack_sha256="sha256:" + "e" * 64,
        source_manifest_digest=manifest_digest,
    )
    with pytest.raises(SealError, match="different vocabulary pack"):
        create_seal(root, signing_key, SIGNER_IDENTITY, vocabulary_pack=pack, semantic_sidecar=mismatched_sidecar)

    seal_path = create_seal(root, signing_key, SIGNER_IDENTITY, vocabulary_pack=pack, semantic_sidecar=sidecar)

    # 1. Tamper 1 byte in sidecar -> refused.
    sidecar_backup = sidecar.read_bytes()
    _tamper_one_byte(sidecar)
    with pytest.raises(SealError, match="semantic sidecar differs from the sealed digest"):
        verify_seal(root, seal_path, allowed_signers)
    sidecar.write_bytes(sidecar_backup)

    # 2. Tamper 1 byte in vocabulary pack -> refused.
    pack_backup = pack.read_bytes()
    _tamper_one_byte(pack)
    with pytest.raises(SealError, match="vocabulary pack differs from the sealed digest"):
        verify_seal(root, seal_path, allowed_signers)
    pack.write_bytes(pack_backup)

    # 3. Symlinked vocabulary pack -> refused before hashing.
    outside_pack = tmp_path / "outside-pack.sqlite"
    shutil.move(pack, outside_pack)
    pack.symlink_to(outside_pack)
    with pytest.raises(SealError, match="vocabulary pack is a symlink"):
        verify_seal(root, seal_path, allowed_signers)
    with pytest.raises(SealError, match="vocabulary pack is a symlink"):
        create_seal(root, signing_key, SIGNER_IDENTITY, seal_path=tmp_path / "s2.json", vocabulary_pack=pack)
    pack.unlink()
    shutil.move(outside_pack, pack)

    # 4. Symlinked semantic sidecar -> refused before hashing.
    outside_sidecar = tmp_path / "outside.vpack"
    shutil.move(sidecar, outside_sidecar)
    sidecar.symlink_to(outside_sidecar)
    with pytest.raises(SealError, match="semantic sidecar is a symlink"):
        verify_seal(root, seal_path, allowed_signers)
    sidecar.unlink()
    shutil.move(outside_sidecar, sidecar)

    # 5. Symlinked seal file -> refused.
    link_seal = tmp_path / "link-seal.json"
    link_seal.symlink_to(seal_path)
    with pytest.raises(SealError, match="seal file is a symlink"):
        verify_seal(root, link_seal, allowed_signers)


def test_seal_monotonic_rollback_guards(
    tmp_path: Path,
    signing_key: Path,
    allowed_signers: Path,
) -> None:
    """verify_seal enforces createdAt and explicit reject_distribution_ids on real SHA-256 Atlas IDs."""

    from tools.generate_atlas_v3_full import distribution_identity

    def _real_dist_id(tag: str) -> str:
        return distribution_identity(
            {
                "assertedInventoryDigest": "sha256:" + hashlib.sha256(tag.encode("utf-8")).hexdigest(),
                "inputs": [
                    {
                        "dispositions": [],
                        "membershipMode": "complete",
                        "sourceRelease": f"urn:ref:source-release:{tag}:2026-08-21",
                    }
                ],
                "totals": {
                    "excluded": 0,
                    "represented": 0,
                    "sourceRecords": 0,
                    "sourceReleases": 1,
                    "unresolved": 0,
                },
                "type": "AtlasSourceAccounting",
                "version": "3.1",
            }
        )

    # Generate two real SHA-256 distributionIds and ensure the NEWER release has
    # a lexicographically LOWER SHA-256 hex digest than the OLDER release.
    candidate_ids = sorted({_real_dist_id("release-alpha"), _real_dist_id("release-beta")})
    assert len(candidate_ids) == 2
    newer_dist_id, older_dist_id = candidate_ids[0], candidate_ids[1]
    assert newer_dist_id < older_dist_id
    for dist_id in (newer_dist_id, older_dist_id):
        assert re.fullmatch(r"urn:ref:atlas:distribution:3\.1-[a-z-]+:[0-9a-f]{64}", dist_id)

    older_root, _ = _write_minimal_distribution_and_view(
        tmp_path / "older",
        distribution_id=older_dist_id,
        created_at="2026-08-21T12:00:00+00:00",
    )
    older_seal = create_seal(older_root, signing_key, SIGNER_IDENTITY)

    newer_root, _ = _write_minimal_distribution_and_view(
        tmp_path / "newer",
        distribution_id=newer_dist_id,
        created_at="2026-08-22T12:00:00+00:00",
    )
    newer_seal = create_seal(newer_root, signing_key, SIGNER_IDENTITY)

    # Newer release with lexicographically LOWER SHA-256 ID is ACCEPTED when createdAt advances.
    verified_newer = verify_seal(
        newer_root,
        newer_seal,
        allowed_signers,
        previous_created_at="2026-08-21T12:00:00Z",
        reject_distribution_ids=[older_dist_id],
    )
    assert verified_newer.distribution_id == newer_dist_id
    assert verified_newer.created_at == "2026-08-22T12:00:00+00:00"

    # Older createdAt is REFUSED.
    with pytest.raises(SealError, match="distribution rollback refused"):
        verify_seal(
            older_root,
            older_seal,
            allowed_signers,
            previous_created_at="2026-08-22T00:00:00Z",
        )

    # Explicitly rejected/revoked distributionId is REFUSED.
    with pytest.raises(SealError, match="distributionId is explicitly rejected"):
        verify_seal(
            newer_root,
            newer_seal,
            allowed_signers,
            reject_distribution_ids=[newer_dist_id],
        )

    # Bare string passed to reject_distribution_ids is refused rather than substring-matched.
    with pytest.raises(SealError, match="reject_distribution_ids must be a collection"):
        verify_seal(
            newer_root,
            newer_seal,
            allowed_signers,
            reject_distribution_ids=older_dist_id,  # type: ignore[arg-type]
        )


def test_default_pack_and_sidecar_paths_are_scoped_to_distribution_name(tmp_path: Path) -> None:
    """Sibling distributions in the same parent dir receive distinct pack and sidecar default paths."""

    dist_a = tmp_path / "atlas-core"
    dist_b = tmp_path / "atlas-full"
    assert default_vocabulary_pack_path(dist_a) == tmp_path / "atlas-core-vocabulary-pack.sqlite"
    assert default_vocabulary_pack_path(dist_b) == tmp_path / "atlas-full-vocabulary-pack.sqlite"
    assert default_semantic_sidecar_path(dist_a) == tmp_path / "atlas-core-vocabulary-pack.vpack"
    assert default_semantic_sidecar_path(dist_b) == tmp_path / "atlas-full-vocabulary-pack.vpack"
    assert default_vocabulary_pack_path(dist_a) != default_vocabulary_pack_path(dist_b)
    assert default_semantic_sidecar_path(dist_a) != default_semantic_sidecar_path(dist_b)


def test_v3_seal_hardening_parent_symlinks_pack_meta_and_required_pack_id(
    tmp_path: Path,
    signing_key: Path,
    allowed_signers: Path,
) -> None:
    """Seal rejects symlinked parent dirs, bad pack_meta record_type/schema_version, and missing sidecar packId."""

    root, _view = _write_minimal_distribution_and_view(tmp_path)
    manifest_digest = file_sha256(root / MANIFEST_MEMBER)

    # 1. pack_meta record_type and schema_version validation.
    bad_type_pack = _write_test_vocabulary_pack(
        tmp_path / "bad-type.sqlite",
        source_manifest_digest=manifest_digest,
        record_type="NotAVocabularyPack",
    )
    with pytest.raises(SealError, match="unexpected pack_meta.record_type"):
        create_seal(root, signing_key, SIGNER_IDENTITY, vocabulary_pack=bad_type_pack)

    bad_ver_pack = _write_test_vocabulary_pack(
        tmp_path / "bad-ver.sqlite",
        source_manifest_digest=manifest_digest,
        schema_version="99",
    )
    with pytest.raises(SealError, match="unsupported pack_meta.schema_version"):
        create_seal(root, signing_key, SIGNER_IDENTITY, vocabulary_pack=bad_ver_pack)

    missing_pack_id_pack = _write_test_vocabulary_pack(
        tmp_path / "missing-pack-id.sqlite",
        source_manifest_digest=manifest_digest,
        pack_id="",
    )
    with pytest.raises(SealError, match="states no pack_meta.pack_id"):
        create_seal(root, signing_key, SIGNER_IDENTITY, vocabulary_pack=missing_pack_id_pack)

    # Schema version "2" is accepted cleanly.
    v2_pack = _write_test_vocabulary_pack(
        tmp_path / "v2-pack.sqlite",
        source_manifest_digest=manifest_digest,
        schema_version="2",
    )
    v2_seal = create_seal(
        root,
        signing_key,
        SIGNER_IDENTITY,
        seal_path=tmp_path / "v2-pack-seal.json",
        vocabulary_pack=v2_pack,
    )
    assert verify_seal(root, v2_seal, allowed_signers, vocabulary_pack=v2_pack).seal_format == SEAL_FORMAT_V3

    # 2. Omitted or empty sidecar packId fails closed whenever vocabulary pack states pack_id.
    pack = _write_test_vocabulary_pack(
        default_vocabulary_pack_path(root),
        source_manifest_digest=manifest_digest,
        pack_id="pack-required-001",
    )
    pack_sha = file_sha256(pack)
    no_pack_id_sidecar = _write_test_semantic_sidecar(
        tmp_path / "missing-pack-id.vpack",
        pack_sha256=pack_sha,
        source_manifest_digest=manifest_digest,
        pack_id=None,
    )
    with pytest.raises(SealError, match="semantic sidecar states no packId"):
        create_seal(
            root,
            signing_key,
            SIGNER_IDENTITY,
            vocabulary_pack=pack,
            semantic_sidecar=no_pack_id_sidecar,
        )

    empty_pack_id_sidecar = _write_test_semantic_sidecar(
        tmp_path / "empty-pack-id.vpack",
        pack_sha256=pack_sha,
        source_manifest_digest=manifest_digest,
        pack_id="",
    )
    with pytest.raises(SealError, match="semantic sidecar states no packId"):
        create_seal(
            root,
            signing_key,
            SIGNER_IDENTITY,
            vocabulary_pack=pack,
            semantic_sidecar=empty_pack_id_sidecar,
        )

    # 3. Symlinked parent directories are rejected on pack, sidecar, seal, and distribution root.
    sidecar = _write_test_semantic_sidecar(
        default_semantic_sidecar_path(root),
        pack_sha256=pack_sha,
        source_manifest_digest=manifest_digest,
        pack_id="pack-required-001",
    )
    seal_path = create_seal(root, signing_key, SIGNER_IDENTITY, vocabulary_pack=pack, semantic_sidecar=sidecar)

    real_parent = tmp_path / "real-parent"
    real_parent.mkdir()
    link_parent = tmp_path / "link-parent"
    link_parent.symlink_to(real_parent, target_is_directory=True)

    linked_pack = real_parent / "linked-pack.sqlite"
    shutil.copy2(pack, linked_pack)
    with pytest.raises(SealError, match="traverses a symlinked parent directory"):
        verify_seal(root, seal_path, allowed_signers, vocabulary_pack=link_parent / "linked-pack.sqlite")
    with pytest.raises(SealError, match="traverses a symlinked parent directory"):
        create_seal(
            root,
            signing_key,
            SIGNER_IDENTITY,
            seal_path=tmp_path / "tmp-seal.json",
            vocabulary_pack=link_parent / "linked-pack.sqlite",
        )

    linked_sidecar = real_parent / "linked.vpack"
    shutil.copy2(sidecar, linked_sidecar)
    with pytest.raises(SealError, match="traverses a symlinked parent directory"):
        verify_seal(
            root,
            seal_path,
            allowed_signers,
            vocabulary_pack=pack,
            semantic_sidecar=link_parent / "linked.vpack",
        )

    linked_seal = real_parent / "linked-seal.json"
    shutil.copy2(seal_path, linked_seal)
    with pytest.raises(SealError, match="traverses a symlinked parent directory"):
        verify_seal(root, link_parent / "linked-seal.json", allowed_signers)

    link_base = tmp_path / "link-base"
    link_base.symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(SealError, match="traverses a symlinked parent directory"):
        verify_seal(link_base / "distribution", seal_path, allowed_signers)


def test_seal_cli_supports_v3_pack_sidecar_and_rollback_flags(
    tmp_path: Path,
    signing_key: Path,
    allowed_signers: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """seal_distribution CLI wires --vocabulary-pack, --semantic-sidecar, and --previous-created-at cleanly."""

    import sys

    from tools import seal_distribution

    generation = tmp_path / ".selected.generations" / ("b" * 32)
    generation.mkdir(parents=True)
    root, view = _write_minimal_distribution_and_view(
        tmp_path / "staging",
        created_at="2026-08-21T12:00:00+00:00",
    )
    root.rename(generation / "distribution")
    view.rename(generation / "parquet-view")
    (generation / "generation-report.json").write_text("{}", encoding="utf-8")
    selection = tmp_path / "selected"
    selection.symlink_to((generation / "distribution").relative_to(tmp_path))

    manifest_digest = file_sha256(generation / "distribution" / MANIFEST_MEMBER)
    pack = _write_test_vocabulary_pack(
        default_vocabulary_pack_path(generation / "distribution"),
        source_manifest_digest=manifest_digest,
        pack_id="cli-pack-001",
    )
    sidecar = _write_test_semantic_sidecar(
        default_semantic_sidecar_path(generation / "distribution"),
        pack_sha256=file_sha256(pack),
        source_manifest_digest=manifest_digest,
        pack_id="cli-pack-001",
    )

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "seal",
            "mint",
            "--selection",
            str(selection),
            "--private-key",
            str(signing_key),
            "--signer-identity",
            SIGNER_IDENTITY,
            "--vocabulary-pack",
            str(pack),
            "--semantic-sidecar",
            str(sidecar),
        ],
    )
    assert seal_distribution.main() == 0
    minted = json.loads(capsys.readouterr().out)
    assert minted["sealFormat"] == SEAL_FORMAT_V3
    assert minted["vocabularyPackSha256"] == file_sha256(pack)
    assert minted["semanticSidecarSha256"] == file_sha256(sidecar)

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "seal",
            "verify",
            "--selection",
            str(selection),
            "--allowed-signers",
            str(allowed_signers),
            "--vocabulary-pack",
            str(pack),
            "--semantic-sidecar",
            str(sidecar),
            "--previous-created-at",
            "2026-08-21T00:00:00Z",
        ],
    )
    assert seal_distribution.main() == 0
    verified = json.loads(capsys.readouterr().out)
    assert verified["seal_format"] == SEAL_FORMAT_V3
    assert verified["vocabulary_pack_sha256"] == file_sha256(pack)
    assert verified["semantic_sidecar_sha256"] == file_sha256(sidecar)

    # Future --previous-created-at refuses rollback via CLI.
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "seal",
            "verify",
            "--selection",
            str(selection),
            "--allowed-signers",
            str(allowed_signers),
            "--previous-created-at",
            "2026-08-22T00:00:00Z",
        ],
    )
    assert seal_distribution.main() == 1
    assert "distribution rollback refused" in capsys.readouterr().err


def test_v3_seal_end_to_end_parquet_view_to_real_pack_and_vpack_sidecar(
    tmp_path: Path,
    signing_key: Path,
    allowed_signers: Path,
) -> None:
    """End-to-end: parquet-view -> build_vocabulary_pack -> .vpack sidecar -> seal-3 -> verify_seal."""

    import numpy as np

    from refspec.atlas.vocabulary_pack import AtlasVocabularyPack
    from refspec.atlas.vocabulary_pack_build import build_vocabulary_pack
    from refspec.atlas.vocabulary_vectors import AtlasSemanticSidecar, build_semantic_sidecar_from_arrays

    root, view = _write_minimal_distribution_and_view(tmp_path)
    view_manifest_digest = file_sha256(view / VIEW_MANIFEST_FILE)

    # 1. Compile a real schema-v3 SQLite pack directly from parquet-view (no parquet-search-view!).
    pack_path = default_vocabulary_pack_path(root)
    pack_manifest = build_vocabulary_pack(
        view,
        pack_path,
        trusted_manifest_digest=view_manifest_digest,
        schemes=["urn:test:scheme"],
    )
    assert pack_manifest.source_view_kind == "parquet-view"
    assert pack_manifest.resource_count == 1
    assert pack_manifest.agency_change_event_count == 1

    # 2. Compile a real .vpack semantic sidecar bound to the pack & view manifest digest.
    sidecar_path = default_semantic_sidecar_path(root)
    vectors_f16 = np.array([[1.0, 0.0, 0.0, 0.0]], dtype=np.float16)
    sidecar_manifest = build_semantic_sidecar_from_arrays(
        pack_path,
        sidecar_path,
        vectors_f16=vectors_f16,
        rids_per_vector=[[1]],
        model_id="e2e-seal3-test-encoder",
        mode="flat_f16",
    )
    assert sidecar_manifest.pack_sha256 == pack_manifest.pack_sha256
    assert sidecar_manifest.source_manifest_digest == view_manifest_digest

    # 3. Mint & verify real refspec-distribution-seal-3 binding distribution + parquet-view + pack + sidecar.
    seal_path = create_seal(
        root,
        signing_key,
        SIGNER_IDENTITY,
        vocabulary_pack=pack_path,
        semantic_sidecar=sidecar_path,
    )
    verified = verify_seal(root, seal_path, allowed_signers)
    assert verified.seal_format == SEAL_FORMAT_V3
    assert verified.vocabulary_pack_sha256 == pack_manifest.pack_sha256
    assert verified.semantic_sidecar_sha256 == sidecar_manifest.sidecar_sha256

    # Confirm the sealed pack + sidecar open and serve together cleanly.
    with (
        AtlasSemanticSidecar.open(
            sidecar_path, trusted_sidecar_digest=verified.semantic_sidecar_sha256
        ) as sidecar,
        AtlasVocabularyPack.open(
            pack_path,
            trusted_pack_digest=verified.vocabulary_pack_sha256,
            trusted_manifest_digest=view_manifest_digest,
            semantic_index=sidecar,
        ) as pack,
    ):
        assert pack.lookup_sync("Test resource")[0]["id"] == "urn:test:resource"
        events = pack.agency_change_events_sync()
        assert len(events) == 1 and events[0]["id"] == "urn:test:event"

    # 4. Negative checks: tamper pack, tamper sidecar, and mismatched source_manifest_digest.
    pack_backup = pack_path.read_bytes()
    _tamper_one_byte(pack_path)
    with pytest.raises(SealError, match="vocabulary pack differs from the sealed digest"):
        verify_seal(root, seal_path, allowed_signers)
    pack_path.write_bytes(pack_backup)

    sidecar_backup = sidecar_path.read_bytes()
    _tamper_one_byte(sidecar_path)
    with pytest.raises(SealError, match="semantic sidecar differs from the sealed digest"):
        verify_seal(root, seal_path, allowed_signers)
    sidecar_path.write_bytes(sidecar_backup)

    swapped_pack = tmp_path / "swapped-pack.sqlite"
    shutil.copy2(pack_path, swapped_pack)
    con = sqlite3.connect(str(swapped_pack))
    con.execute(
        "UPDATE pack_meta SET value = ? WHERE key = 'source_manifest_digest'",
        ("sha256:" + "9" * 64,),
    )
    con.commit()
    con.close()
    with pytest.raises(SealError, match="derived from a different distribution manifest"):
        create_seal(root, signing_key, SIGNER_IDENTITY, seal_path=tmp_path / "bad-seal.json", vocabulary_pack=swapped_pack)
