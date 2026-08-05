from __future__ import annotations

import hashlib
import sys
from pathlib import Path

import pytest

from refspec.storage import canonical_json

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from compare_atlas_judgment_manual_audit import compare


def _write_fixture(tmp_path: Path) -> tuple[Path, Path, Path]:
    manual = tmp_path / "manual.md"
    blind_path = tmp_path / "blind.json"
    key_path = tmp_path / "key.json"
    manual.write_text(
        """| Row | Audit ID | Independent verdict |
| ---: | --- | --- |
| 1 | `audit-a` | `same` |
| 2 | `audit-b` | `unrelated` |
| 3 | `audit-c` | `target_is_broader` |
"""
    )
    blind = {
        "type": "blind",
        "rows": [
            {"auditId": "audit-a"},
            {"auditId": "audit-b"},
            {"auditId": "audit-c"},
        ],
    }
    blind_path.write_text(canonical_json(blind) + "\n")
    blind_digest = "sha256:" + hashlib.sha256(canonical_json(blind).encode()).hexdigest()
    key = {
        "type": "key",
        "blindSampleDigest": blind_digest,
        "rows": [
            {
                "auditId": "audit-a",
                "vocabularyPair": "pair",
                "generationClass": "labels",
                "control": False,
                "disposition": "admitted",
                "relation": "http://www.w3.org/2004/02/skos/core#closeMatch",
                "judgments": [
                    {"family": "gemini", "verdict": "same"},
                    {"family": "openai", "verdict": "near_same"},
                ],
            },
            {
                "auditId": "audit-b",
                "vocabularyPair": "pair",
                "generationClass": "labels",
                "control": False,
                "disposition": "abstained",
                "judgments": [
                    {"family": "gemini", "verdict": "unrelated"},
                    {"family": "openai", "verdict": "insufficient_evidence"},
                ],
            },
            {
                "auditId": "audit-c",
                "vocabularyPair": "pair",
                "generationClass": "labels",
                "control": False,
                "disposition": "admitted",
                "relation": "http://www.w3.org/2004/02/skos/core#narrowMatch",
                "judgments": [
                    {"family": "gemini", "verdict": "target_is_narrower"},
                    {"family": "openai", "verdict": "target_is_narrower"},
                ],
            },
        ],
    }
    key_path.write_text(canonical_json(key) + "\n")
    return manual, blind_path, key_path


def test_compare_separates_exact_support_and_relation_compatibility(
    tmp_path: Path,
) -> None:
    manual, blind, key = _write_fixture(tmp_path)

    result = compare(manual, blind, key)

    assert result["sourceVerification"]["manualIdsExactlyMatchBlindInOrder"] is True
    assert result["providers"]["gemini"]["exactVerdictAgreement"] == {
        "count": 2,
        "denominator": 3,
        "rate": 0.66666667,
    }
    assert result["providers"]["openai"]["supportVsNoSupportAgreement"]["count"] == 3
    assert result["twoProviderAndReviewer"]["providerCompatibleRelationAndDirectionWhenBothSupport"]["count"] == 2
    assert result["twoProviderAndReviewer"]["reviewerCompatibleWithBothWhenAllThreeSupport"] == {
        "count": 1,
        "denominator": 2,
        "rate": 0.5,
    }
    assert result["nonControlDispositionContingency"]["admitted"] == {
        "rows": 2,
        "reviewerSupport": 2,
        "reviewerNoSupport": 0,
        "reviewerWouldPreserveAdmission": 1,
        "reviewerWouldPreserveExactAdmittedRelation": {
            "count": 1,
            "denominator": 2,
        },
    }


def test_compare_rejects_manual_id_or_order_drift(tmp_path: Path) -> None:
    manual, blind, key = _write_fixture(tmp_path)
    manual.write_text(manual.read_text().replace("audit-a", "audit-d", 1))

    with pytest.raises(ValueError, match="IDs or order differ"):
        compare(manual, blind, key)
