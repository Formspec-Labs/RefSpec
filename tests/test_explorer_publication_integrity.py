"""Served-byte publication checks against a bounded local HTTP server."""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

BUILD = Path(__file__).resolve().parents[1] / "deploy/cloudflare-explorer/build"
SPEC = importlib.util.spec_from_file_location("publication_integrity", BUILD / "publication_integrity.py")
assert SPEC and SPEC.loader
integrity = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(integrity)


@pytest.fixture
def publication(tmp_path):
    root = tmp_path / "outputs"
    root.mkdir()
    (root / "test.parquet").write_bytes(b"PAR1-content-PAR1")
    view_digest = "sha256:" + "1" * 64
    digest = integrity.freeze_inventory(root, search_view_digest=view_digest, release=True)
    _, objects = integrity.load_inventory(root, inventory_digest=digest, search_view_digest=view_digest)
    return root, view_digest, digest, objects


@pytest.fixture
def server(publication):
    root, _, digest, _ = publication
    prefix = "/data/" + integrity.candidate_prefix(digest) + "/"
    served = {prefix + path.name: path.read_bytes() for path in root.iterdir()}
    statuses = {}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            status = statuses.get(self.path, 200 if self.path in served else 404)
            data = served.get(self.path, b"")
            if self.headers.get("Range") and status == 200:
                self.send_response(206)
                self.send_header("Content-Range", f"bytes 0-0/{len(data)}")
                self.send_header("Content-Length", "1")
                self.end_headers()
                self.wfile.write(data[:1])
                return
            self.send_response(status)
            version = statuses.get("version:" + self.path, "test-version")
            if version:
                self.send_header("x-atlas-worker-version", version)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *_args):
            pass

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=httpd.serve_forever)
    thread.start()
    try:
        yield f"http://127.0.0.1:{httpd.server_port}", prefix, served, statuses
    finally:
        httpd.shutdown()
        thread.join()
        httpd.server_close()


@pytest.mark.parametrize(
    "mode,expected",
    [
        ("clean", "passed"),
        ("same-size", "mismatch"),
        ("truncated", "mismatch"),
        ("missing", "missing"),
        ("transport", "error"),
    ],
)
def test_actual_served_bytes(publication, server, mode, expected):
    _, _, digest, objects = publication
    base, prefix, served, statuses = server
    key = "test.parquet"
    if mode == "same-size":
        served[prefix + key] = b"X" * len(served[prefix + key])
    elif mode == "truncated":
        served[prefix + key] = served[prefix + key][:-1]
    elif mode == "missing":
        statuses[prefix + key] = 404
    elif mode == "transport":
        statuses[prefix + key] = 503
    assert (
        integrity.verify_object(
            base, integrity.candidate_prefix(digest), key, objects[key], worker_version="test-version"
        )["status"]
        == expected
    )


def test_inventory_pin_and_local_tampering(publication):
    root, view_digest, digest, objects = publication
    integrity.check_local(root, objects)
    with pytest.raises(ValueError, match="different search view"):
        integrity.load_inventory(root, inventory_digest=digest, search_view_digest="sha256:" + "2" * 64)
    (root / "test.parquet").write_bytes(b"X" * objects["test.parquet"]["byteLength"])
    with pytest.raises(ValueError, match="differs"):
        integrity.check_local(root, objects)
    (root / integrity.INVENTORY).write_text("{}")
    with pytest.raises(ValueError, match="digest"):
        integrity.load_inventory(root, inventory_digest=digest, search_view_digest=view_digest)


def test_development_inventory_refused(publication):
    root, view_digest, _, _ = publication
    digest = integrity.freeze_inventory(root, search_view_digest=view_digest, release=False)
    with pytest.raises(ValueError, match="development"):
        integrity.load_inventory(root, inventory_digest=digest, search_view_digest=view_digest)


@pytest.mark.parametrize("tamper", (False, True))
def test_verify_script_freezes_candidate_and_receipts(publication, server, tmp_path, tamper):
    root, view_digest, digest, _ = publication
    base, prefix, served, _ = server
    if tamper:
        served[prefix + "test.parquet"] = b"X" * len(served[prefix + "test.parquet"])
    receipt = tmp_path / "receipt.json"
    result = subprocess.run(
        ["bash", str(BUILD / "verify-all.sh")],
        env={
            **os.environ,
            "SRC_DIR": str(root),
            "WORKER_BASE": base,
            "INVENTORY_DIGEST": digest,
            "SEARCH_VIEW_DIGEST": view_digest,
            "CLOUDFLARE_ACCOUNT_ID": "test-account",
            "WORKER_VERSION": "test-version",
            "SOURCE_REVISION": "test-revision",
            "PUBLICATION_RECEIPT": str(receipt),
            "PUBLICATION_PYTHON": sys.executable,
        },
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert result.returncode == int(tamper), result.stdout + result.stderr
    document = json.loads(receipt.read_bytes())
    assert document["status"] == ("failed" if tamper else "passed")
    assert document["expectedWorkerVersion"] == "test-version"
    assert document["inventoryDigest"] == digest
    assert document["promoted"] is False


def test_existing_shell_empty_and_outside_target_guards(tmp_path):
    root = tmp_path / "empty"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.write_text("outside")
    env = {**os.environ, "SRC_DIR": str(root)}
    verify = subprocess.run(["bash", str(BUILD / "verify-all.sh")], env=env, capture_output=True, text=True)
    assert verify.returncode == 2
    assert "empty audit" in verify.stderr
    upload = subprocess.run(
        ["bash", str(BUILD / "upload-verified.sh"), str(outside)], env=env, capture_output=True, text=True
    )
    assert upload.returncode == 1
    assert "not under SRC_DIR" in upload.stderr


@pytest.mark.parametrize("version", ("", "other-version"))
def test_missing_or_wrong_serving_version(publication, server, version):
    _, _, digest, objects = publication
    base, prefix, _, statuses = server
    statuses["version:" + prefix + "test.parquet"] = version
    result = integrity.verify_object(
        base, integrity.candidate_prefix(digest), "test.parquet", objects["test.parquet"], worker_version="test-version"
    )
    assert result["status"] == "mismatch"
    assert result["observedWorkerVersion"] == (version or None)


def test_version_change_between_objects_fails_receipt(publication, server, tmp_path):
    root, view_digest, digest, _ = publication
    base, prefix, _, statuses = server
    statuses["version:" + prefix + integrity.INVENTORY] = "new-version"
    receipt = tmp_path / "receipt.json"
    result = subprocess.run(
        [
            sys.executable,
            str(BUILD / "publication_integrity.py"),
            "verify-public",
            "--root",
            str(root),
            "--inventory-digest",
            digest,
            "--search-view-digest",
            view_digest,
            "--base",
            base,
            "--worker-version",
            "test-version",
            "--account-id",
            "test-account",
            "--source-revision",
            "revision",
            "--receipt",
            str(receipt),
        ],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 1
    assert json.loads(receipt.read_bytes())["status"] == "failed"


@pytest.mark.parametrize("change", ("add-vendor", "modify-old", "remove-old"))
def test_final_vendor_freeze_preserves_authenticated_outputs(publication, change):
    root, view_digest, digest, _ = publication
    vendor = root / "vendor"
    vendor.mkdir()
    (vendor / "engine.mjs").write_text("export const engine = true;")
    if change == "modify-old":
        original = root / "test.parquet"
        original.write_bytes(b"X" * original.stat().st_size)
    elif change == "remove-old":
        (root / "test.parquet").unlink()
    result = subprocess.run(
        [
            sys.executable,
            str(BUILD / "publication_integrity.py"),
            "freeze",
            "--root",
            str(root),
            "--inventory-digest",
            digest,
            "--search-view-digest",
            view_digest,
        ],
        capture_output=True,
        text=True,
        timeout=10,
    )
    if change == "add-vendor":
        assert result.returncode == 0, result.stderr
        _, objects = integrity.load_inventory(
            root, inventory_digest=result.stdout.strip(), search_view_digest=view_digest
        )
        assert "vendor/engine.mjs" in objects
        integrity.check_local(root, objects)
    else:
        assert result.returncode == 2
        assert integrity.file_digest(root / integrity.INVENTORY) == digest


@pytest.mark.parametrize("wrong_active", (False, True))
def test_active_selection_verification_does_not_accept_good_direct_candidate(
    publication, server, tmp_path, wrong_active
):
    root, view_digest, digest, objects = publication
    base, prefix, served, _ = server
    for key in objects:
        served["/data/" + key] = served[prefix + key]
    if wrong_active:
        # Same-size bytes from a different active candidate evade range probes.
        served["/data/test.parquet"] = b"X" * len(served["/data/test.parquet"])
    receipt = tmp_path / "active-receipt.json"
    environment = {
        **os.environ,
        "SRC_DIR": str(root),
        "WORKER_BASE": base,
        "INVENTORY_DIGEST": digest,
        "SEARCH_VIEW_DIGEST": view_digest,
        "CLOUDFLARE_ACCOUNT_ID": "test-account",
        "WORKER_VERSION": "test-version",
        "SOURCE_REVISION": "test-revision",
        "PUBLICATION_RECEIPT": str(receipt),
        "PUBLICATION_PYTHON": sys.executable,
        "VERIFY_ACTIVE_DATA": "1",
    }
    direct = integrity.verify_object(
        base, integrity.candidate_prefix(digest), "test.parquet", objects["test.parquet"], worker_version="test-version"
    )
    assert direct["status"] == "passed"
    result = subprocess.run(
        ["bash", str(BUILD / "verify-all.sh")], env=environment, capture_output=True, text=True, timeout=15
    )
    assert result.returncode == int(wrong_active), result.stdout + result.stderr
    document = json.loads(receipt.read_bytes())
    assert document["verificationScope"] == "active"
    assert document["verifiedDataBaseUrl"] == base + "/data/"
    assert document["activeSelectionVerified"] is (not wrong_active)
    assert document["promoted"] is False
