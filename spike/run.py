"""Subprocess runner: each measurement gets a fresh interpreter.

    .venv/bin/python spike/run.py <script> <variant>[:<n_packs>] ...
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PY = str(ROOT / ".venv" / "bin" / "python")


def main() -> None:
    script = sys.argv[1]
    for spec in sys.argv[2:]:
        variant, _, n = spec.partition(":")
        cmd = [PY, str(ROOT / "spike" / script), variant]
        if n:
            cmd.append(n)
        proc = subprocess.run(cmd, capture_output=True, text=True, cwd=ROOT)
        out = [ln for ln in proc.stdout.splitlines() if ln.startswith("RESULT")]
        if out:
            print("\n".join(out), flush=True)
        else:
            print(f"FAILED {spec} rc={proc.returncode}", flush=True)
            print(proc.stdout[-2000:], flush=True)
            print(proc.stderr[-3000:], flush=True)


if __name__ == "__main__":
    main()
