"""Compatibility entry point for the REF JSON Binding 1.0 validator."""

from __future__ import annotations

import sys
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

REFSPEC_ROOT = Path(__file__).resolve().parents[4]
BINDING_MODULE = REFSPEC_ROOT / "src" / "refspec" / "binding.py"
MODULE_SPEC = spec_from_file_location("_refspec_binding", BINDING_MODULE)
if MODULE_SPEC is None or MODULE_SPEC.loader is None:
    raise RuntimeError(f"cannot load REF binding validator from {BINDING_MODULE}")

binding = module_from_spec(MODULE_SPEC)
sys.modules[MODULE_SPEC.name] = binding
MODULE_SPEC.loader.exec_module(binding)
main = binding.main


if __name__ == "__main__":
    raise SystemExit(main())
