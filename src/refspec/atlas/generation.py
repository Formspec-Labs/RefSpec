"""Select one retained Atlas generation before opening any of its artifacts.

Selection is local path metadata, never acceptance or byte-integrity evidence.
Callers keep the returned paths and run their existing independent checks.
"""

from __future__ import annotations

import argparse
import os
import re
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class AtlasGeneration:
    """Concrete sibling paths that do not follow the mutable selector again."""

    root: Path

    @property
    def distribution(self) -> Path:
        return self.root / "distribution"

    @property
    def parquet_view(self) -> Path:
        return self.root / "parquet-view"

    @property
    def report(self) -> Path:
        return self.root / "generation-report.json"

    @property
    def seal(self) -> Path:
        return self.root / "distribution-seal.json"


def selection_path(output: Path | str) -> Path:
    """Normalize the parent, preserving the final mutable selector name."""
    path = Path(output)
    if not path.name or path.name in {".", ".."}:
        raise ValueError(f"Atlas selection needs a file name: {path}")
    return path.parent.resolve() / path.name


def generation_store(output: Path | str) -> Path:
    path = selection_path(output)
    return path.parent / f".{path.name}.generations"


def _real_directory(path: Path) -> None:
    if path.is_symlink() or not path.is_dir():
        raise ValueError(f"Atlas generation requires a real directory: {path}")


def select_atlas_generation(output: Path | str) -> AtlasGeneration:
    """Read the pointer once; refuse foreign paths and extra mutable links.

    The trusted builder selects only after distribution, optional view and
    report finish. This constant-size check is not a replacement for manifest,
    view, signature, closure or semantic validation. Local owner custody must
    keep selected artifacts unchanged; freshness remains the consumer's choice.
    """
    output = selection_path(output)
    try:
        target = Path(os.readlink(output))
    except OSError as error:
        raise ValueError(f"Atlas selection must be a builder generation symlink: {output}") from error
    if (
        target.is_absolute()
        or len(target.parts) != 3
        or target.parts[0] != f".{output.name}.generations"
        or re.fullmatch(r"[0-9a-f]{32}", target.parts[1]) is None
        or target.parts[2] != "distribution"
    ):
        raise ValueError(f"Atlas selection has an invalid generation target: {output}")
    generation = AtlasGeneration(output.parent / target.parent)
    for path in (generation.root.parent, generation.root, generation.distribution):
        _real_directory(path)
    for path in (generation.report, generation.distribution / "atlas-manifest.json"):
        if path.is_symlink() or not path.is_file():
            raise ValueError(f"Atlas generation is missing a regular artifact: {path}")
    if generation.parquet_view.exists() or generation.parquet_view.is_symlink():
        _real_directory(generation.parquet_view)
        manifest = generation.parquet_view / "view-manifest.json"
        if manifest.is_symlink() or not manifest.is_file():
            raise ValueError(f"Atlas generation is missing a regular view manifest: {manifest}")
    return generation


def require_selection_output(output: Path | str) -> Path:
    """Return the normalized selector; refuse a real path or an invalid existing selection."""
    output = selection_path(output)
    if output.exists() and not output.is_symlink():
        raise FileExistsError(f"Atlas selection refuses an existing real output: {output}")
    if output.is_symlink():
        select_atlas_generation(output)  # Refuse foreign or incomplete selections.
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("selection", type=Path)
    parser.add_argument("--artifact", choices=("root", "distribution", "parquet_view", "report", "seal"), default="root")
    args = parser.parse_args()
    try:
        generation = select_atlas_generation(args.selection)
    except ValueError as error:
        parser.error(str(error))
    print(getattr(generation, args.artifact))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
