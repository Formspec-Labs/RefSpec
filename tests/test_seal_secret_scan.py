"""Every builder that seals an artifact scans it for secrets first.

The invariant existed in `usc_act_index.py` and was PORTED AWAY: on 2026-08-31
`build_usc_source_credits.py` and `build_usc_popular_names.py` were written
from it and both omitted the scan, sealing row tables and receipts unguarded
for four days. Nothing leaked -- spicy-regs still enforced it upstream -- but
an invariant that lives as one copy per builder is an invariant only until the
next port forgets it.

So this file asserts the property twice over. `test_the_scanner_refuses...`
pins the behaviour, and `test_every_sealing_builder...` pins that each builder
CALLS it, which is the half that would have caught the 08-31 regression. The
second is a static check on purpose: running these builders needs the pinned
USC bulk source, so a test that only ran under real data would not have failed
in CI either.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from refspec.registry.infrastructure.artifact_serialization import (
    scan_for_secrets,
    scan_text_for_secrets,
)

ROOT = Path(__file__).resolve().parents[1]

#: Every tool that writes a sealed artifact. A builder added here without the
#: scan fails the test below rather than shipping unguarded.
SEALING_BUILDERS = (
    "tools/build_usc_source_credits.py",
    "tools/build_usc_popular_names.py",
)


@pytest.mark.parametrize(
    ("value", "where"),
    [
        ("sk-" + "a" * 24, "openai-style key"),
        ("sk-proj-" + "b" * 24, "project-scoped key"),
        ("api_key=abcdefgh12345", "query-string key"),
        ("API-KEY=abcdefgh12345", "upper-case spelling"),
    ],
)
def test_the_scanner_refuses_a_secret_like_value(value: str, where: str) -> None:
    """A refusal, not a report: a build that would seal a credential stops."""

    with pytest.raises(SystemExit, match="refusing to seal"):
        scan_for_secrets([{"column": value}], "table")
    with pytest.raises(SystemExit, match="refusing to seal"):
        scan_text_for_secrets(value, "receipt.json")


def test_the_scanner_passes_ordinary_content() -> None:
    """The negative fixture. A guard that refuses everything is not a guard.

    These are shapes the USC builders really carry -- a section identifier, a
    Statutes at Large citation, a public law number -- and each contains digits
    and punctuation the pattern could over-read.
    """

    rows = [
        {"identifier": "/us/usc/t42/s1983", "credit": "Pub. L. 96-170, Sec. 1, 93 Stat. 1284"},
        {"identifier": "/us/usc/t22/s283z-11", "credit": "Pub. L. 92-246, title III, Sec. 301"},
        {"identifier": None, "credit": "api key rotation is described in the note"},
    ]
    assert scan_for_secrets(rows, "credits") is None
    assert scan_text_for_secrets('{"rows": 12, "digest": "sha256:' + "0" * 64 + '"}', "receipt.json") is None


@pytest.mark.parametrize("builder", SEALING_BUILDERS)
def test_every_sealing_builder_calls_the_scan(builder: str) -> None:
    """The half that would have caught the 2026-08-31 port.

    Read as a syntax tree rather than grepped, so a mention inside a comment or
    a docstring cannot satisfy it -- only a real call does.
    """

    source = (ROOT / builder).read_text(encoding="utf-8")
    called = {
        node.func.id
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    assert "scan_for_secrets" in called, f"{builder} seals row tables without scanning them"
    assert "scan_text_for_secrets" in called, f"{builder} seals a receipt without scanning it"


def test_the_row_scan_guards_the_write_choke_point() -> None:
    """Scanning inside ``write_parquet`` is what makes the guard hard to lose.

    At the call sites it is one omission per new table; at the choke point a
    table sealed without a scan is unreachable. This pins the placement, not
    merely the presence.
    """

    for builder in SEALING_BUILDERS:
        tree = ast.parse((ROOT / builder).read_text(encoding="utf-8"))
        writer = next(
            (n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "write_parquet"),
            None,
        )
        assert writer is not None, f"{builder} has no write_parquet to guard"
        inner = {
            n.func.id for n in ast.walk(writer) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
        }
        assert "scan_for_secrets" in inner, f"{builder}: the row scan is not at the write choke point"
