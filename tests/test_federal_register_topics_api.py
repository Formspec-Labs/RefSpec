from __future__ import annotations

import json
from pathlib import Path

import pytest

from refspec.registry.federal_register_thesaurus import (
    FederalRegisterThesaurus,
    LabelExpression,
    SourceLocator,
)
from refspec.registry.federal_register_topics_api import (
    FederalRegisterTopicsError,
    capture_federal_register_topics,
    compare_historical_thesaurus_to_topics,
    open_federal_register_topics_capture,
    parse_federal_register_topics_api,
)


def _topic(
    name: str,
    slug: str,
    *,
    see_also: list[dict[str, str]] | None = None,
) -> dict[str, object]:
    return {
        "cfr_references": [],
        "name": name,
        "see": [],
        "see_also": see_also or [],
        "slug": slug,
    }


def _payload() -> bytes:
    value = {
        "meta": {
            "count": {
                "thesaurus": 3,
                "ad_hoc": 1,
                "total": 4,
            }
        },
        "results": {
            "thesaurus": [
                _topic(
                    "Accounting",
                    "accounting",
                    see_also=[
                        {
                            "name": "Business and industry",
                            "slug": "business-industry",
                        }
                    ],
                ),
                _topic("Shared slug A", "shared"),
                _topic("Shared slug B", "shared"),
            ],
            "ad_hoc": [_topic("One-off location", "")],
        },
    }
    return json.dumps(value, separators=(",", ":")).encode("utf-8")


def _historical() -> FederalRegisterThesaurus:
    locator = SourceLocator(start_line=1, end_line=1, ordinal=1)
    labels = (
        LabelExpression(
            label_id="label-1",
            concept_id="concept-1",
            role="preferred",
            literal="Accounting",
            language_tag="en",
            source="heading",
            source_entry_id="entry-1",
            source_reference_id=None,
            locator=locator,
        ),
        LabelExpression(
            label_id="label-2",
            concept_id="concept-1",
            role="alternate",
            literal="Shared slug B",
            language_tag="en",
            source="x",
            source_entry_id="entry-1",
            source_reference_id="reference-1",
            locator=locator,
        ),
        LabelExpression(
            label_id="label-3",
            concept_id="concept-2",
            role="preferred",
            literal="Historical only",
            language_tag="en",
            source="heading",
            source_entry_id="entry-2",
            source_reference_id=None,
            locator=locator,
        ),
    )
    return FederalRegisterThesaurus(
        source_sha256="sha256:" + "1" * 64,
        source_lines=1,
        source_bytes=1,
        entries=(),
        concepts=(),
        labels=labels,
        category_notations=(),
        scope_notes=(),
        cross_references=(),
        relations=(),
        unresolved_references=(),
    )


def test_parser_preserves_source_rows_without_promoting_slugs_to_identity() -> None:
    snapshot = parse_federal_register_topics_api(_payload())

    assert snapshot.counts == {
        "thesaurus": 3,
        "ad_hoc": 1,
        "total": 4,
    }
    first = snapshot.thesaurus[0]
    assert first.source_locator == "results.thesaurus[0]"
    assert first.see_also[0].name == "Business and industry"
    assert first.source_record_digest.startswith("sha256:")
    assert snapshot.ad_hoc[0].slug == ""

    collisions = snapshot.slug_collisions()
    shared = collisions[("thesaurus", "shared")]
    assert [item.name for item in shared] == [
        "Shared slug A",
        "Shared slug B",
    ]
    assert shared[0].source_record_digest != shared[1].source_record_digest


def test_parser_rejects_declared_count_and_source_shape_drift() -> None:
    wrong_count = json.loads(_payload())
    wrong_count["meta"]["count"]["total"] = 5
    with pytest.raises(FederalRegisterTopicsError, match="declares 5"):
        parse_federal_register_topics_api(
            json.dumps(wrong_count).encode("utf-8")
        )

    extra_field = json.loads(_payload())
    extra_field["results"]["thesaurus"][0]["concept_id"] = "invented"
    with pytest.raises(FederalRegisterTopicsError, match="fields changed"):
        parse_federal_register_topics_api(
            json.dumps(extra_field).encode("utf-8")
        )


def test_capture_round_trips_exact_bytes_and_rejects_wrong_pins(
    tmp_path: Path,
) -> None:
    source = tmp_path / "topics-source.json"
    source.write_bytes(_payload())
    acquired = capture_federal_register_topics(
        tmp_path / "store",
        source_path=source,
    )

    assert acquired.path.read_bytes() == _payload()
    reopened = open_federal_register_topics_capture(
        acquired.path,
        expected_sha256=acquired.source_sha256,
        expected_byte_length=acquired.byte_length,
    )
    assert reopened.source_record_set_digest == (
        acquired.snapshot.source_record_set_digest
    )

    with pytest.raises(FederalRegisterTopicsError, match="byte length"):
        open_federal_register_topics_capture(
            acquired.path,
            expected_sha256=acquired.source_sha256,
            expected_byte_length=acquired.byte_length + 1,
        )
    with pytest.raises(FederalRegisterTopicsError, match="digest"):
        open_federal_register_topics_capture(
            acquired.path,
            expected_sha256="sha256:" + "0" * 64,
            expected_byte_length=acquired.byte_length,
        )


def test_local_capture_rejects_symlink_input(tmp_path: Path) -> None:
    source = tmp_path / "topics-source.json"
    source.write_bytes(_payload())
    linked = tmp_path / "linked.json"
    linked.symlink_to(source)

    with pytest.raises(
        FederalRegisterTopicsError,
        match="not a regular file",
    ):
        capture_federal_register_topics(
            tmp_path / "store",
            source_path=linked,
        )


def test_historical_comparison_records_differences_without_mapping() -> None:
    comparison = compare_historical_thesaurus_to_topics(
        _historical(),
        parse_federal_register_topics_api(_payload()),
    )

    assert comparison.historical_preferred_count == 2
    assert comparison.current_thesaurus_count == 3
    assert comparison.current_ad_hoc_count == 1
    assert comparison.preferred_label_overlap_count == 1
    assert comparison.historical_any_label_overlap_count == 2
    assert comparison.historical_preferred_only == ("historical only",)
    assert comparison.current_slug_collision_groups == 1
    assert comparison.canonical_digest.startswith("sha256:")
