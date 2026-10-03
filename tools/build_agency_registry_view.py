"""Seal REF-072's agency registry view: the release's bridges, event results and non-emissions as Parquet.

Builds ``agency-registry-2026-09-26`` from the five pinned agency rosters and
seals its projection -- the three asserted tables, the derived current
successors, and their manifest -- with
``seal_agency_registry_view()``. The manifest's sha256 is the pin a consumer
vendors the view by; ``--check`` rebuilds the view in a scratch directory and
refuses a manifest that is not the pinned one, and ``--verify`` checks a view
already on disk against a pin and against the release rebuilt here.
"""

from __future__ import annotations

import argparse
import tempfile
from pathlib import Path

from refspec.atlas import v3_registry_alignments_entity as entity
from refspec.atlas.parquet_artifact import file_sha256
from refspec.atlas.parquet_view import MANIFEST_FILE, seal_agency_registry_view, verify_agency_registry_view
from refspec.atlas.v3_source_data import RegistryMappingRelease

try:
    from tools import analyze_agency_roster_identifiers as census
except ImportError:  # Direct execution places tools/ on sys.path.
    import analyze_agency_roster_identifiers as census

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "output" / "agency-registry-view"
# The sealed view the design note names (plans/agency-registry-design.md section 8).
VIEW_MANIFEST_SHA256 = "sha256:99b8234ad15881e411ca4af2faa9e99bb9d91a22ba140e6ae792da4a8d4e41f9"


def build_release() -> RegistryMappingRelease:
    """The agency-registry release, rebuilt from the five pinned rosters."""

    return entity.load_agency_registry_mapping_release(census.load_five_agency_rosters(ROOT))


def build_view(output: Path) -> str:
    """Seal the view at ``output`` and return its manifest's sha256."""

    seal_agency_registry_view(output, build_release())
    return file_sha256(output / MANIFEST_FILE)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="directory to seal the view into")
    parser.add_argument("--check", action="store_true", help="rebuild in a scratch directory and compare the pin")
    parser.add_argument("--verify", type=Path, help="verify the view in this directory against the release")
    parser.add_argument("--expected-manifest-sha256", help="the pin --verify checks the view's manifest against")
    args = parser.parse_args(argv)
    if args.verify is not None:
        if not args.expected_manifest_sha256:
            parser.error("--verify needs --expected-manifest-sha256")
        verify_agency_registry_view(
            args.verify, expected_manifest_digest=args.expected_manifest_sha256, release=build_release()
        )
        print(f"agency registry view is its release's: {args.expected_manifest_sha256}")
        return 0
    if args.check:
        with tempfile.TemporaryDirectory() as scratch:
            digest = build_view(Path(scratch) / "view")
        if digest != VIEW_MANIFEST_SHA256:
            raise SystemExit(f"agency registry view manifest {digest} is not the pinned {VIEW_MANIFEST_SHA256}")
        print(f"agency registry view is current: {digest}")
        return 0
    print(build_view(args.output))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
