from __future__ import annotations

import importlib.util
from pathlib import Path

TOOL = Path(__file__).parents[1] / "tools" / "audit_atlas_judgment_baseline.py"
SPEC = importlib.util.spec_from_file_location("audit_atlas_judgment_baseline", TOOL)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_blind_field_gate_rejects_judgment_and_generator_leakage() -> None:
    MODULE._assert_blind(
        {
            "auditId": "audit-1",
            "source": {"prefLabel": "Air pollution"},
            "target": {"prefLabel": "Air quality"},
        }
    )

    for field in sorted(MODULE.FORBIDDEN_BLIND_FIELDS):
        try:
            MODULE._assert_blind({"source": {field: "leak"}})
        except ValueError as error:
            assert field in str(error)
        else:
            raise AssertionError(f"field {field!r} was not rejected")


def test_quantiles_are_deterministic_nearest_rank_summaries() -> None:
    assert MODULE._quantiles([]) is None
    assert MODULE._quantiles([9]) == {"minimum": 9, "p50": 9, "p95": 9, "maximum": 9}
    assert MODULE._quantiles(range(1, 101)) == {
        "minimum": 1,
        "p50": 51,
        "p95": 96,
        "maximum": 100,
    }
