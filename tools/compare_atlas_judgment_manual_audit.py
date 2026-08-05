"""Compare a sealed blind Atlas judgment audit with its historical judge key.

This tool is read-only. It parses the independent verdict table, verifies its
row identity against the blind sample and sealed key, and reports concordance.
Concordance measures agreement with historical judges; it is not an estimate
of objective semantic accuracy.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from refspec.storage import canonical_json

VERDICTS = frozenset(
    {
        "same",
        "near_same",
        "target_is_broader",
        "target_is_narrower",
        "related",
        "unrelated",
        "insufficient_evidence",
    }
)
SUPPORTING_VERDICTS = frozenset(
    {
        "same",
        "near_same",
        "target_is_broader",
        "target_is_narrower",
        "related",
    }
)
NO_SUPPORT_VERDICTS = VERDICTS - SUPPORTING_VERDICTS
VERDICT_TABLE_ROW = re.compile(
    r"^\|\s*(?P<row>[0-9]+)\s*\|\s*`(?P<audit_id>audit-[0-9a-f]+)`\s*"
    r"\|\s*`(?P<verdict>[a-z_]+)`\s*\|$"
)

EXACT_MATCH = "http://www.w3.org/2004/02/skos/core#exactMatch"
CLOSE_MATCH = "http://www.w3.org/2004/02/skos/core#closeMatch"
BROAD_MATCH = "http://www.w3.org/2004/02/skos/core#broadMatch"
NARROW_MATCH = "http://www.w3.org/2004/02/skos/core#narrowMatch"
RELATED_MATCH = "http://www.w3.org/2004/02/skos/core#relatedMatch"


def _raw_digest(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _canonical_digest(value: object) -> str:
    return "sha256:" + hashlib.sha256(canonical_json(value).encode()).hexdigest()


def _read_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text())
    if not isinstance(value, dict):
        raise TypeError(f"{path} does not contain a JSON object")
    return value


def _read_manual_verdicts(path: Path) -> tuple[dict[str, str], tuple[str, ...]]:
    verdicts: dict[str, str] = {}
    order: list[str] = []
    expected_row = 1
    for line in path.read_text().splitlines():
        match = VERDICT_TABLE_ROW.match(line)
        if match is None:
            continue
        row_number = int(match.group("row"))
        if row_number != expected_row:
            raise ValueError(f"manual verdict table row {row_number} follows {expected_row - 1}")
        audit_id = match.group("audit_id")
        verdict = match.group("verdict")
        if audit_id in verdicts:
            raise ValueError(f"manual verdict table repeats {audit_id}")
        if verdict not in VERDICTS:
            raise ValueError(f"manual verdict table has unsupported verdict {verdict!r}")
        verdicts[audit_id] = verdict
        order.append(audit_id)
        expected_row += 1
    if not order:
        raise ValueError("manual verdict table has no rows")
    return verdicts, tuple(order)


def _support(verdict: str) -> bool:
    return verdict in SUPPORTING_VERDICTS


def _agreed_relation(verdicts: frozenset[str]) -> str | None:
    """Apply the Atlas v2 relation agreement lattice to supporting verdicts."""

    if not verdicts or not verdicts <= SUPPORTING_VERDICTS:
        return None
    if verdicts == {"same"}:
        return EXACT_MATCH
    if verdicts <= {"same", "near_same"}:
        return CLOSE_MATCH
    if verdicts == {"target_is_broader"}:
        return BROAD_MATCH
    if verdicts == {"target_is_narrower"}:
        return NARROW_MATCH
    if verdicts == {"related"}:
        return RELATED_MATCH
    return None


def _ratio(numerator: int, denominator: int) -> dict[str, int | float | None]:
    return {
        "count": numerator,
        "denominator": denominator,
        "rate": round(numerator / denominator, 8) if denominator else None,
    }


def _comparison(rows: Sequence[Mapping[str, Any]], family: str) -> dict[str, Any]:
    exact = 0
    support_agreement = 0
    both_support = 0
    compatible = 0
    contingency: Counter[str] = Counter()
    for row in rows:
        reviewer = str(row["reviewerVerdict"])
        provider = str(row["providerVerdicts"][family])
        exact += reviewer == provider
        reviewer_support = _support(reviewer)
        provider_support = _support(provider)
        support_agreement += reviewer_support == provider_support
        contingency[
            f"reviewer_{'support' if reviewer_support else 'noSupport'}__"
            f"provider_{'support' if provider_support else 'noSupport'}"
        ] += 1
        if reviewer_support and provider_support:
            both_support += 1
            compatible += _agreed_relation(frozenset({reviewer, provider})) is not None
    return {
        "exactVerdictAgreement": _ratio(exact, len(rows)),
        "supportVsNoSupportAgreement": _ratio(support_agreement, len(rows)),
        "compatibleRelationAndDirectionWhenBothSupport": _ratio(compatible, both_support),
        "supportContingency": dict(sorted(contingency.items())),
    }


def _pair_comparison(
    rows: Sequence[Mapping[str, Any]],
    families: Sequence[str],
) -> dict[str, Any]:
    pair_exact = 0
    pair_support_agreement = 0
    pair_both_support = 0
    pair_relation_compatible = 0
    reviewer_exact_to_both = 0
    reviewer_support_to_both = 0
    reviewer_compatible_with_supporting_pair = 0
    reviewer_compatible_denominator = 0
    for row in rows:
        provider_values = tuple(row["providerVerdicts"][name] for name in families)
        reviewer = str(row["reviewerVerdict"])
        pair_exact += len(set(provider_values)) == 1
        provider_supports = tuple(_support(value) for value in provider_values)
        pair_support_agreement += len(set(provider_supports)) == 1
        if all(provider_supports):
            pair_both_support += 1
            pair_relation_compatible += _agreed_relation(frozenset(provider_values)) is not None
            if _support(reviewer):
                reviewer_compatible_denominator += 1
                reviewer_compatible_with_supporting_pair += (
                    _agreed_relation(frozenset((*provider_values, reviewer))) is not None
                )
        reviewer_exact_to_both += all(reviewer == value for value in provider_values)
        reviewer_support_to_both += all(_support(reviewer) == value for value in provider_supports)
    return {
        "providerExactVerdictAgreement": _ratio(pair_exact, len(rows)),
        "providerSupportVsNoSupportAgreement": _ratio(pair_support_agreement, len(rows)),
        "providerCompatibleRelationAndDirectionWhenBothSupport": _ratio(pair_relation_compatible, pair_both_support),
        "reviewerExactVerdictMatchesBothProviders": _ratio(reviewer_exact_to_both, len(rows)),
        "reviewerSupportVsNoSupportMatchesBothProviders": _ratio(reviewer_support_to_both, len(rows)),
        "reviewerCompatibleWithBothWhenAllThreeSupport": _ratio(
            reviewer_compatible_with_supporting_pair,
            reviewer_compatible_denominator,
        ),
    }


def _slice_summary(
    rows: Sequence[Mapping[str, Any]],
    families: Sequence[str],
) -> dict[str, Any]:
    reviewer_support = sum(_support(str(row["reviewerVerdict"])) for row in rows)
    result: dict[str, Any] = {
        "rows": len(rows),
        "reviewerSupport": reviewer_support,
        "reviewerNoSupport": len(rows) - reviewer_support,
        "historicalDispositions": dict(sorted(Counter(str(row["disposition"]) for row in rows).items())),
    }
    result["providers"] = {family: _comparison(rows, family) for family in families}
    result["twoProviderAndReviewer"] = _pair_comparison(rows, families)
    return result


def compare(
    manual_path: Path,
    blind_path: Path,
    key_path: Path,
) -> dict[str, Any]:
    """Return a deterministic concordance report for the three audit files."""

    manual_verdicts, manual_order = _read_manual_verdicts(manual_path)
    blind = _read_object(blind_path)
    key = _read_object(key_path)
    blind_rows = blind.get("rows")
    key_rows = key.get("rows")
    if not isinstance(blind_rows, list) or not isinstance(key_rows, list):
        raise TypeError("blind sample and key must contain row arrays")
    blind_order = tuple(str(row["auditId"]) for row in blind_rows)
    key_order = tuple(str(row["auditId"]) for row in key_rows)
    if len(set(manual_order)) != len(manual_order):
        raise ValueError("manual verdict table has duplicate audit IDs")
    if manual_order != blind_order:
        raise ValueError("manual verdict table IDs or order differ from blind sample")
    if key_order != blind_order:
        raise ValueError("sealed key IDs or order differ from blind sample")
    blind_digest = _canonical_digest(blind)
    if key.get("blindSampleDigest") != blind_digest:
        raise ValueError("sealed key does not pin the canonical blind sample")

    families: set[str] = set()
    normalized_rows: list[dict[str, Any]] = []
    for key_row in key_rows:
        judgments = key_row.get("judgments")
        if not isinstance(judgments, list):
            raise TypeError("key row judgments must be an array")
        provider_verdicts: dict[str, str] = {}
        for judgment in judgments:
            family = str(judgment["family"])
            verdict = str(judgment["verdict"])
            if family in provider_verdicts:
                raise ValueError(f"key row {key_row['auditId']} repeats family {family}")
            if verdict not in VERDICTS:
                raise ValueError(f"key row has unsupported provider verdict {verdict!r}")
            provider_verdicts[family] = verdict
        families.update(provider_verdicts)
        audit_id = str(key_row["auditId"])
        normalized_rows.append(
            {
                "auditId": audit_id,
                "vocabularyPair": str(key_row["vocabularyPair"]),
                "generationClass": str(key_row["generationClass"]),
                "control": bool(key_row["control"]),
                "disposition": str(key_row["disposition"]),
                "relation": key_row.get("relation"),
                "reviewerVerdict": manual_verdicts[audit_id],
                "providerVerdicts": provider_verdicts,
            }
        )
    ordered_families = tuple(sorted(families))
    if any(tuple(sorted(row["providerVerdicts"])) != ordered_families for row in normalized_rows):
        raise ValueError("key rows do not contain one consistent provider-family set")

    pair_comparison = _pair_comparison(normalized_rows, ordered_families)
    triad_admission = 0
    for row in normalized_rows:
        provider_values = tuple(row["providerVerdicts"][name] for name in ordered_families)
        reviewer = row["reviewerVerdict"]
        provider_supports = tuple(_support(value) for value in provider_values)
        triad_relation = (
            _agreed_relation(frozenset((*provider_values, reviewer)))
            if _support(reviewer) and all(provider_supports)
            else None
        )
        triad_admission += bool(not row["control"] and triad_relation is not None)

    non_controls = [row for row in normalized_rows if not row["control"]]
    controls = [row for row in normalized_rows if row["control"]]
    disposition_contingency: dict[str, Any] = {}
    for disposition in sorted({str(row["disposition"]) for row in non_controls}):
        selected = [row for row in non_controls if row["disposition"] == disposition]
        support_count = sum(_support(str(row["reviewerVerdict"])) for row in selected)
        compatible_count = 0
        exact_relation_count = 0
        admitted_rows = 0
        for row in selected:
            provider_values = tuple(row["providerVerdicts"][family] for family in ordered_families)
            triad_relation = (
                _agreed_relation(frozenset((*provider_values, str(row["reviewerVerdict"]))))
                if _support(str(row["reviewerVerdict"])) and all(_support(value) for value in provider_values)
                else None
            )
            compatible_count += triad_relation is not None
            if row["relation"] is not None:
                admitted_rows += 1
                exact_relation_count += triad_relation == row["relation"]
        disposition_contingency[disposition] = {
            "rows": len(selected),
            "reviewerSupport": support_count,
            "reviewerNoSupport": len(selected) - support_count,
            "reviewerWouldPreserveAdmission": compatible_count,
            "reviewerWouldPreserveExactAdmittedRelation": {
                "count": exact_relation_count,
                "denominator": admitted_rows,
            },
        }

    by_generation: dict[str, list[dict[str, Any]]] = defaultdict(list)
    by_pair: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in normalized_rows:
        by_generation[str(row["generationClass"])].append(row)
        by_pair[str(row["vocabularyPair"])].append(row)

    return {
        "type": "AtlasHistoricalJudgmentManualConcordance",
        "schemaVersion": "1.0",
        "interpretation": ("Concordance with historical provider judgments; not objective semantic accuracy."),
        "sourceVerification": {
            "manualRawDigest": _raw_digest(manual_path),
            "blindRawDigest": _raw_digest(blind_path),
            "blindCanonicalDigest": blind_digest,
            "keyRawDigest": _raw_digest(key_path),
            "keyCanonicalDigest": _canonical_digest(key),
            "rowCount": len(normalized_rows),
            "manualIdsExactlyMatchBlindInOrder": True,
            "keyIdsExactlyMatchBlindInOrder": True,
            "keyPinsBlindCanonicalDigest": True,
            "stratumCounts": {
                f"{pair}|{generation_class}": count
                for (pair, generation_class), count in sorted(
                    Counter((row["vocabularyPair"], row["generationClass"]) for row in normalized_rows).items()
                )
            },
        },
        "definitions": {
            "support": sorted(SUPPORTING_VERDICTS),
            "noSupport": sorted(NO_SUPPORT_VERDICTS),
            "compatibleRelationAndDirection": (
                "The v2 lattice admits the combined supporting verdict set; "
                "same plus near_same is compatible at closeMatch."
            ),
        },
        "reviewerVerdictCounts": dict(sorted(Counter(row["reviewerVerdict"] for row in normalized_rows).items())),
        "providers": {family: _comparison(normalized_rows, family) for family in ordered_families},
        "twoProviderAndReviewer": {
            **pair_comparison,
            "historicalNonControlAdmissions": sum(row["disposition"] == "admitted" for row in non_controls),
            "nonControlAdmissionsIfReviewerWereAddedAsThirdGate": triad_admission,
        },
        "nonControlDispositionContingency": disposition_contingency,
        "controls": _slice_summary(controls, ordered_families),
        "controlsByGenerationClass": {
            name: _slice_summary(rows, ordered_families)
            for name, rows in sorted(by_generation.items())
            if all(row["control"] for row in rows)
        },
        "byGenerationClass": {
            name: _slice_summary(rows, ordered_families) for name, rows in sorted(by_generation.items())
        },
        "byVocabularyPair": {name: _slice_summary(rows, ordered_families) for name, rows in sorted(by_pair.items())},
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manual", required=True, type=Path)
    parser.add_argument("--blind", required=True, type=Path)
    parser.add_argument("--key", required=True, type=Path)
    parser.add_argument("--output", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = compare(args.manual, args.blind, args.key)
    rendered = canonical_json(result) + "\n"
    if args.output is not None:
        args.output.write_text(rendered)
    print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
