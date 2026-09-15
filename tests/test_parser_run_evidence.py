"""Run records bind installed readers without changing source-derived identity."""

from __future__ import annotations

import hashlib
import json
import zipfile
from importlib import import_module
from pathlib import Path

import pytest

from refspec.registry import federal_register_topics_api as topics
from refspec.registry.infrastructure.artifact_serialization import producer_module_source
from refspec.registry.packages.federal_register_topics_package import (
    FEDERAL_REGISTER_TOPICS_CAPTURE_EVENT,
    build_federal_register_topics_source_package,
)
from tools import build_usc_source_credits as credits

FIXTURES = Path(__file__).parent / "fixtures"


def _assert_module_bytes(modules):
    for name, digest in modules.items():
        source = Path(import_module(name).__file__)
        assert digest == "sha256:" + hashlib.sha256(source.read_bytes()).hexdigest()


def _capture(store):
    return topics.capture_federal_register_topics(
        store,
        source_path=FIXTURES / "federal_register_topics_api/federal-register-topics-2026-08-03.json",
        fetch_event=FEDERAL_REGISTER_TOPICS_CAPTURE_EVENT,
    )


def test_replay_keeps_capture_and_package_identity_but_records_each_reader_run(tmp_path, monkeypatch):
    first = _capture(tmp_path)
    before = json.loads(first.receipt_path.read_bytes())
    _assert_module_bytes(before["producer"]["modules"])
    changed = tmp_path / "reader.py"
    changed.write_text("# changed installed reader bytes\n")
    module_name = "spicy_docs.sources.json_input"
    monkeypatch.setattr(import_module(module_name), "__file__", str(changed))
    second = _capture(tmp_path)
    after = json.loads(second.receipt_path.read_bytes())
    assert first.path == second.path
    assert (
        first.path.read_bytes()
        == (FIXTURES / "federal_register_topics_api/federal-register-topics-2026-08-03.json").read_bytes()
    )
    assert first.snapshot == second.snapshot
    assert first.receipt_path != second.receipt_path
    assert first.receipt_path.parent == tmp_path / "runs"
    assert before["captureEvent"] == after["captureEvent"] == first.capture_event.as_dict()
    assert before["sourceSha256"] == first.source_sha256
    assert before["sourceByteLength"] == first.byte_length
    assert before["parserVersion"] == topics.FEDERAL_REGISTER_TOPICS_PARSER_VERSION
    assert before["recordedAt"] != before["captureEvent"]["fetchedAt"]
    assert json.loads(first.receipt_path.read_bytes()) == before
    changed_names = {
        name
        for name in before["producer"]["modules"]
        if before["producer"]["modules"][name] != after["producer"]["modules"][name]
    }
    assert changed_names == {module_name}
    assert build_federal_register_topics_source_package(first).logical_digest == (
        build_federal_register_topics_source_package(second).logical_digest
    )


def test_topics_missing_reader_refuses_before_capture_publication(tmp_path, monkeypatch):
    monkeypatch.setattr(import_module("spicy_docs.sources.json_input"), "__file__", str(tmp_path / "absent.py"))
    with pytest.raises(ValueError, match="producer module missing"):
        _capture(tmp_path / "store")
    assert not (tmp_path / "store").exists()


def test_topics_run_id_collision_preserves_previous_receipt(tmp_path, monkeypatch):
    first = _capture(tmp_path)
    before = first.receipt_path.read_bytes()
    monkeypatch.setattr(topics, "generate_uuid7", lambda **kwargs: first.receipt_path.stem)
    with pytest.raises(FileExistsError):
        _capture(tmp_path)
    assert first.receipt_path.read_bytes() == before
    assert list(first.receipt_path.parent.iterdir()) == [first.receipt_path]


def test_source_credit_build_records_installed_reader_before_outputs(tmp_path, monkeypatch):
    archive = tmp_path / "title.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("usc05.xml", (FIXTURES / "uslm-source-links/title-05-s423.xml").read_bytes())
    receipt = credits.build(tmp_path / "first", archive=archive, release_point="119-102")
    modules = receipt["producer"]["modules"]
    assert set(modules) == {
        "tools.build_usc_source_credits",
        "spicy_docs.sources.uscode_references",
        "spicy_docs.sources.uscode",
        "spicy_docs.sources.xml_observations",
        "spicy_docs.sources.xml",
    }
    _assert_module_bytes(modules)
    assert json.loads((tmp_path / "first/receipt.json").read_bytes()) == receipt
    monkeypatch.setattr(import_module("spicy_docs.sources.xml"), "__file__", str(tmp_path / "absent.py"))
    with pytest.raises(ValueError, match="producer module missing"):
        credits.build(tmp_path / "missing", archive=archive, release_point="119-102")
    assert not (tmp_path / "missing").exists()


def _old_dependency_source(name):
    """Copied from Agenda at 6cf579bf before extracting its dependency resolver."""
    try:
        source = import_module(name).__file__
    except ImportError as error:
        raise ValueError(f"producer dependency module is unavailable: {name}") from error
    if source is None:
        raise ValueError(f"producer dependency module has no source file: {name}")
    path = Path(source).resolve()
    if not path.is_file():
        raise ValueError(f"producer module missing from this checkout: {name} (expected at {path})")
    return path


@pytest.mark.parametrize("mutation", ["original", "missing", "none", "unavailable"])
def test_shared_source_resolver_matches_old_dependency_check(tmp_path, monkeypatch, mutation):
    name = "spicy_docs.sources.xml"
    if mutation == "missing":
        monkeypatch.setattr(import_module(name), "__file__", str(tmp_path / "absent.py"))
    elif mutation == "none":
        monkeypatch.setattr(import_module(name), "__file__", None)
    elif mutation == "unavailable":
        name = "spicy_docs.nonexistent_test_module"

    def verdict(reader):
        try:
            return "ok", reader(name)
        except ValueError as error:
            return "refused", str(error)

    assert verdict(producer_module_source) == verdict(_old_dependency_source)
