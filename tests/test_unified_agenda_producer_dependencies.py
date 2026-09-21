"""Runtime receipts identify the installed source-reader implementation."""

from __future__ import annotations

import hashlib
from importlib import import_module
from pathlib import Path

import pytest

from refspec.registry import unified_agenda_parquet as builder

DEPENDENCIES = {
    "spicy_docs.sources.unified_agenda.records",
    "spicy_docs.reading.xml_observations",
    "spicy_docs.reading.xml",
}


def test_receipt_hashes_actual_installed_parser_and_xml_dependencies():
    """Pin that receipt module digests hash the actual installed source files."""

    modules = builder._producer_block()["modules"]
    assert DEPENDENCIES <= modules.keys()
    for name in DEPENDENCIES:
        source = Path(import_module(name).__file__)
        assert builder._producer_module_source(name) == source.resolve()
        assert modules[name] == "sha256:" + hashlib.sha256(source.read_bytes()).hexdigest()


def test_dependency_drift_changes_receipt_without_changing_receiver(monkeypatch, tmp_path):
    """Pin that changing one reader file moves only that module's receipt digest."""

    before = builder._producer_block()["modules"]
    name = "spicy_docs.sources.unified_agenda.records"
    replacement = tmp_path / "changed_reader.py"
    replacement.write_text("# changed provider implementation\n")
    monkeypatch.setattr(import_module(name), "__file__", str(replacement))
    after = builder._producer_block()["modules"]
    assert {key for key in before if before[key] != after[key]} == {name}


def test_missing_dependency_refuses_before_build_creates_output(monkeypatch, tmp_path):
    """Pin refusal on a missing producer module before any output directory is created."""

    name = "spicy_docs.sources.unified_agenda.records"
    monkeypatch.setattr(import_module(name), "__file__", str(tmp_path / "missing_reader.py"))
    output = tmp_path / "output"
    with pytest.raises(ValueError, match="producer module missing"):
        builder.build_unified_agenda_parquet(source_root=tmp_path / "unused", output_root=output)
    assert not output.exists()
