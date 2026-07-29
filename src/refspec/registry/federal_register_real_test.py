"""Run the opt-in, networked Federal Register vocabulary regression.

This command is intentionally absent from the default offline test path.  It
explicitly acquires the pinned source into a temporary content-addressed store,
then runs only the full-source tests against the live pinned Rulespec checkout.
The temporary source bytes are removed when the command exits and never enter
Git.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import tempfile
from collections.abc import Sequence
from pathlib import Path

from refspec.registry.federal_register_acquisition import (
    AcquisitionError,
    acquire_federal_register_thesaurus_1995,
)

REFSPEC_ROOT = Path(__file__).resolve().parents[3]


def run_real_vocabulary_regression(
    *,
    rulespec_root: Path,
) -> int:
    """Acquire the exact source and run all opt-in historical regressions."""

    with tempfile.TemporaryDirectory(
        prefix="refspec-real-vocabulary-"
    ) as temporary:
        acquired = acquire_federal_register_thesaurus_1995(
            Path(temporary) / "source-store"
        )
        environment = os.environ.copy()
        environment["REFSPEC_FR_THESAURUS_1995_PATH"] = str(acquired.path)
        environment["RULESPEC_DIR"] = str(rulespec_root.resolve())
        result = subprocess.run(
            [
                "uv",
                "run",
                "pytest",
                "-q",
                (
                    "tests/test_federal_register_thesaurus.py::"
                    "test_verified_historical_full_source_counts_and_"
                    "fail_closed_result"
                ),
                (
                    "tests/test_federal_register_vertical_slice.py::"
                    "test_verified_full_source_build_closes_exact_"
                    "historical_counts"
                ),
            ],
            cwd=REFSPEC_ROOT,
            env=environment,
            check=False,
        )
        return result.returncode


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rulespec-root", type=Path, required=True)
    args = parser.parse_args(list(argv) if argv is not None else None)
    try:
        return run_real_vocabulary_regression(
            rulespec_root=args.rulespec_root
        )
    except AcquisitionError as error:
        parser.error(str(error))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
