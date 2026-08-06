"""Make the repository root importable so tests can import ``tools`` modules.

Several test modules import analysis tooling as ``from tools import ...``.
The ``tools`` directory is a namespace package rather than an installed one,
so the repository root must be on ``sys.path`` for those imports to resolve
under pytest's default prepend import mode, which only inserts the test
directory itself.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
