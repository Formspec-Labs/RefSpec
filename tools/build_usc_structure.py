"""Build the six U.S. Code oracle tables from explicit retained OLRC archives.

SpicyDocs reads source structure. This receiver preserves generation 2's
normalization, appendix scope, bracket exclusion and unexpanded ranges. The
dated research scripts remain frozen reproduction evidence, not current code.
Outputs are unsealed candidates: this tool never changes the oracle's pins.
"""

from __future__ import annotations

import argparse
import hashlib
import re
import sys
from collections.abc import Callable, Sequence
from importlib.metadata import version
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

import duckdb
from spicy_docs.sources.uscode import (
    DEFAULT_MAX_ARCHIVE_BYTES,
    DEFAULT_MAX_ARCHIVE_ENTRIES,
    DEFAULT_MAX_XML_BYTES,
    UsCodeSourceError,
)
from spicy_docs.sources.uscode_annual import AnnualSectionObservation, scan_uscode_annual_sections
from spicy_docs.sources.uscode_structure import UsCodeStructureObservation, scan_uscode_structure
from spicy_docs.sources.zip_archive import archive_members, open_archive, read_member

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src"))

from refspec.registry.citation_grammar import _normalize_dashes
from refspec.registry.infrastructure.artifact_serialization import file_sha256
from refspec.registry.usc_section_oracle import normalize_section
from refspec.storage import canonical_json

TABLES = {
    "sections": ("usc-oracle-sections.parquet", "title INTEGER, section VARCHAR, status VARCHAR"),
    "ranges": ("usc-oracle-ranges.parquet", "title INTEGER, lo VARCHAR, hi VARCHAR, status VARCHAR, raw VARCHAR"),
    "subsections": ("usc-oracle-subsections.parquet", "title INTEGER, section VARCHAR, sub VARCHAR"),
    "chapters": ("usc-oracle-chapters.parquet", "title INTEGER, chapter VARCHAR"),
    "annual_sections": ("usc-oracle-annual-sections.parquet", "year INTEGER, title INTEGER, appendix BOOLEAN, section VARCHAR"),
    "annual_ranges": ("usc-oracle-annual-ranges.parquet", "year INTEGER, title INTEGER, appendix BOOLEAN, lo VARCHAR, hi VARCHAR"),
}

# These names select generation 2's retained input scope. Native title/release
# identity belongs to SpicyDocs acquisition; this offline refresh makes no
# acquisition claim and does not copy its header parser.
_CORPUS_MEMBER = re.compile(r"usc(?P<title>[0-9]+)(?P<appendix>[aA]?)\.xml")
_ANNUAL_MEMBER = re.compile(r"(?P<year>[0-9]{4})usc(?P<title>[0-9]+)(?P<appendix>[aA]?)\.htm", re.IGNORECASE)
_ANNUAL_SIDE = re.compile(r"(?:index\.html?|usc\.css|[0-9]{4}usc(?:PopularNames|Table[0-9]+)\.htm|tbl[0-9]+(?:cd|pl)_[a-z0-9]+\.htm)", re.IGNORECASE)
_SUBSECTION = re.compile(r"[A-Za-z0-9]+")
_TOKEN = re.compile(r"[0-9][0-9A-Za-z.\-]*")
type Emit = Callable[[str, tuple[Any, ...]], None]


def read_release_title(body: bytes, *, appendix: bool, emit: Emit) -> None:
    """Apply the existing oracle's policies to shared raw XML observations."""

    def section(observation: UsCodeStructureObservation) -> None:
        for piece in observation.identifier_pieces:
            if piece.kind != "section" or piece.appendix:
                continue
            title = int(piece.title)
            value = normalize_section(piece.section)
            status = observation.status if observation.status is not None else "current"
            if "..." in value:
                low, _, high = value.partition("...")
                emit("ranges", (title, low, high, status, _normalize_dashes(piece.raw)))
            else:
                emit("sections", (title, value, status))

    def subsection(observation: UsCodeStructureObservation) -> None:
        if appendix:
            return
        # The old oracle admits one alphanumeric path component, not every
        # structurally named subsection or every depth under a section.
        for piece in observation.identifier_pieces:
            if piece.kind == "section-part" and not piece.appendix and _SUBSECTION.fullmatch(piece.section_part or ""):
                emit("subsections", (int(piece.title), normalize_section(piece.section), piece.section_part.lower()))

    def chapter(observation: UsCodeStructureObservation) -> None:
        if appendix:
            return
        for piece in observation.identifier_pieces:
            if piece.kind == "chapter" and not piece.appendix and "..." not in piece.chapter:
                emit("chapters", (int(piece.title), normalize_section(piece.chapter)))

    scan_uscode_structure(body, on_section=section, on_section_part=subsection, on_chapter=chapter)


def read_annual_title(body: bytes, *, year: int, title: int, appendix: bool, emit: Emit) -> None:
    """Keep generation 2's printed-section attestation scope, including ranges."""

    def section(observation: AnnualSectionObservation) -> None:
        if observation.section_label is None or observation.bracketed:
            return
        for piece in observation.parts:
            if piece.kind == "section":
                value = normalize_section(piece.section)
                if _TOKEN.fullmatch(value):
                    emit("annual_sections", (year, title, appendix, value))
            elif piece.kind == "range":
                low, high = normalize_section(piece.range_start), normalize_section(piece.range_end)
                if _TOKEN.fullmatch(low) and _TOKEN.fullmatch(high):
                    emit("annual_ranges", (year, title, appendix, low, high))

    scan_uscode_annual_sections(body, on_section=section)


def _literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


class _Tables:
    """Small insert batches; DuckDB spills larger DISTINCT/sort work to disk."""

    def __init__(self, connection: duckdb.DuckDBPyConnection) -> None:
        self.connection = connection
        self.pending: dict[str, list[tuple[Any, ...]]] = {name: [] for name in TABLES}
        for name, (_, columns) in TABLES.items():
            connection.execute(f"CREATE TABLE {name} ({columns})")

    def emit(self, name: str, row: tuple[Any, ...]) -> None:
        self.pending[name].append(row)
        if len(self.pending[name]) >= 1024:
            self.flush(name)

    def flush(self, name: str) -> None:
        rows = self.pending[name]
        if rows:
            parameters = ",".join("?" for _ in rows[0])
            self.connection.executemany(f"INSERT INTO {name} VALUES ({parameters})", rows)
            rows.clear()

    def write(self, output: Path) -> dict[str, Any]:
        files = {}
        for name, (filename, _) in TABLES.items():
            self.flush(name)
            path = output / filename
            query = f"SELECT DISTINCT * FROM {name} ORDER BY ALL"
            count = self.connection.execute(f"SELECT count(*) FROM ({query})").fetchone()[0]
            self.connection.execute(f"COPY ({query}) TO {_literal(str(path))} (FORMAT PARQUET)")
            files[filename] = {"rows": count, "sha256": file_sha256(path), "bytes": path.stat().st_size}
        return files


def _digest(body: bytes) -> str:
    return "sha256:" + hashlib.sha256(body).hexdigest()


def _archive(path: Path, *, year: int | None, emit: Emit) -> dict[str, Any]:
    # Read at most the declared compressed bound even if a file grows after stat.
    with path.open("rb") as stream:
        body = stream.read(DEFAULT_MAX_ARCHIVE_BYTES + 1)
    label = "retained U.S. Code structure archive"
    members = []
    with open_archive(
        body, max_bytes=DEFAULT_MAX_ARCHIVE_BYTES,
        max_entries=DEFAULT_MAX_ARCHIVE_ENTRIES, max_entry_bytes=DEFAULT_MAX_XML_BYTES,
        error_type=UsCodeSourceError, label=label,
    ) as archive:
        for info in archive_members(archive, max_entries=DEFAULT_MAX_ARCHIVE_ENTRIES, error_type=UsCodeSourceError, label=label):
            stem = info.filename.rsplit("/", 1)[-1]
            match = (_CORPUS_MEMBER if year is None else _ANNUAL_MEMBER).fullmatch(stem)
            if match is None and (year is None or not _ANNUAL_SIDE.fullmatch(stem)):
                raise ValueError(f"unclassified U.S. Code archive member: {info.filename}")
            data = read_member(archive, info, max_bytes=DEFAULT_MAX_XML_BYTES, error_type=UsCodeSourceError, label=label)
            members.append({"name": info.filename, "sha256": _digest(data), "bytes": len(data), "selected": match is not None})
            if match is None:
                continue
            appendix = bool(match["appendix"])
            if year is None:
                read_release_title(data, appendix=appendix, emit=emit)
            else:
                if int(match["year"]) != year:
                    raise ValueError(f"annual archive year differs from member name: {info.filename}")
                read_annual_title(data, year=year, title=int(match["title"]), appendix=appendix, emit=emit)
    if not any(member["selected"] for member in members):
        raise ValueError(f"U.S. Code archive has no selected titles: {path}")
    return {"path": str(path.resolve()), "year": year, "sha256": _digest(body), "bytes": len(body), "members": members}


def build(*, corpus: Path, annual: Sequence[tuple[int, Path]], output: Path) -> dict[str, Any]:
    """Write a new candidate directory only after every selected archive succeeds."""
    if output.exists():
        raise ValueError(f"output already exists: {output}")
    years = [year for year, _ in annual]
    if len(years) != len(set(years)) or any(not 1994 <= year <= 2100 for year in years):
        raise ValueError("annual archive years must be unique and between 1994 and 2100")
    output.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix=".usc-structure-", dir=output.parent) as temporary:
        work = Path(temporary)
        candidate = work / "candidate"
        candidate.mkdir()
        with duckdb.connect(str(work / "working.duckdb")) as connection:
            connection.execute("SET memory_limit = '256MiB'")
            connection.execute("SET max_temp_directory_size = '4GiB'")
            connection.execute(f"SET temp_directory = {_literal(str(work / 'spill'))}")
            # One transaction avoids a disk commit per inserted source row.
            connection.execute("BEGIN TRANSACTION")
            tables = _Tables(connection)
            inputs = [_archive(corpus, year=None, emit=tables.emit)]
            inputs.extend(_archive(path, year=year, emit=tables.emit) for year, path in sorted(annual))
            files = tables.write(candidate)
            connection.execute("COMMIT")
        receipt = {
            "format": "refspec-usc-structure-candidate-v1", "spicyDocsVersion": version("spicy-docs"),
            "policy": "generation-2-section-oracle", "inputs": inputs, "files": files,
            "bounds": {"archiveBytes": DEFAULT_MAX_ARCHIVE_BYTES, "entryBytes": DEFAULT_MAX_XML_BYTES,
                       "archiveEntries": DEFAULT_MAX_ARCHIVE_ENTRIES, "duckdbMemoryMiB": 256, "spillGiB": 4},
            "adopted": False,
        }
        (candidate / "receipt.json").write_text(canonical_json(receipt) + "\n", encoding="utf-8")
        candidate.rename(output)
    return receipt


def _annual_argument(value: str) -> tuple[int, Path]:
    year, separator, filename = value.partition("=")
    if not separator or not filename or not year.isdecimal():
        raise argparse.ArgumentTypeError("annual input must be YEAR=PATH")
    return int(year), Path(filename)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", type=Path, required=True, help="retained release-point XML zip")
    parser.add_argument("--annual", type=_annual_argument, action="append", default=[], metavar="YEAR=PATH")
    parser.add_argument("--output", type=Path, required=True, help="new candidate directory; never overwritten")
    args = parser.parse_args(argv)
    try:
        receipt = build(corpus=args.corpus, annual=args.annual, output=args.output)
    except (OSError, ValueError, duckdb.Error) as error:
        parser.exit(1, f"U.S. Code structure build failed: {error}\n")
    print(canonical_json({"output": str(args.output), "files": receipt["files"], "adopted": False}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
