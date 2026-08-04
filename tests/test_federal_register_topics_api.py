from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from refspec.registry.federal_register_topics_api import (
    FederalRegisterTopicsError,
    capture_federal_register_topics,
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


def test_real_topics_response_shape_count_and_boundary_samples() -> None:
    source_path_text = os.environ.get("REFSPEC_FR_TOPICS_PATH")
    if source_path_text is None:
        pytest.skip("real Federal Register topics response is not configured")
    snapshot = parse_federal_register_topics_api(Path(source_path_text).read_bytes())

    assert snapshot.source_sha256 == (
        "sha256:aba80a4dcacbffc7c9ec29eb88ea385ec313510fc8331d0f69078d940d1da35b"
    )
    assert snapshot.counts == {"thesaurus": 1_044, "ad_hoc": 6_723, "total": 7_767}
    assert (snapshot.thesaurus[0].name, snapshot.thesaurus[0].slug) == (
        "Accountants",
        "accountants",
    )
    assert (snapshot.thesaurus[-1].name, snapshot.thesaurus[-1].slug) == ("Zoning", "zoning")
    assert (snapshot.ad_hoc[0].name, snapshot.ad_hoc[0].slug) == (
        "1200 Sixth Avenue",
        "sixth-avenue",
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
        retrieved_at="2026-07-30T12:00:00Z",
    )

    assert acquired.path.read_bytes() == _payload()
    assert acquired.capture_event.fetched_at == "2026-07-30T12:00:00Z"
    assert acquired.capture_event.fetch_id
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
