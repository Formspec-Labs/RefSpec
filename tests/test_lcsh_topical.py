"""Bounded LCSH topical ndjson streaming-parser tests.

Every test reads bytes from a fixture or an in-test mutation of one; nothing
here opens a network connection.
"""

from __future__ import annotations

import gzip
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

import pytest

from refspec.registry.infrastructure.source_controlled_resource import SourceControlledResourceView
from refspec.registry.lcsh_topical import (
    LCSH_CONCEPT_URI_IDENTIFIER_KIND,
    LCSH_LCCN_IDENTIFIER_KIND,
    LCSH_SUBJECTS_SCHEME_IRI,
    LCSH_TOPICAL_MADS_NDJSON_URL,
    LCSH_TOPICAL_MINI_FIXTURE_BYTE_LENGTH,
    LCSH_TOPICAL_MINI_FIXTURE_SHA256,
    MAX_TOPICAL_SUBSET_RECORDS,
    LcshTopicalError,
    LcshTopicalLabel,
    build_lcsh_topical_snapshot,
    capture_lcsh_authorities_by_iri,
    capture_lcsh_topical_subset,
    capture_lcsh_topical_subset_from_gzip_path,
    open_pinned_lcsh_topical_mini_fixture,
    parse_lcsh_authority_ndjson_line,
    parse_lcsh_topical_ndjson_line,
)

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "lcsh_topical" / "lcsh-topical-mini.ndjson"
SOURCE_URL = LCSH_TOPICAL_MADS_NDJSON_URL
CAPTURED_AT = "2026-08-03T00:00:00Z"

ACTIONSCRIPT = "http://id.loc.gov/authorities/subjects/sh00000011"
TACOS = "http://id.loc.gov/authorities/subjects/sh00000014"
SAKI = "http://id.loc.gov/authorities/subjects/sh00000029"
CHANCHERA_LAKE = "http://id.loc.gov/authorities/subjects/sh00000023"
ANGIOTENSIN = "http://id.loc.gov/authorities/subjects/sh00000071"
CORPORATE = "http://id.loc.gov/authorities/subjects/sh00000145"


def _fixture_lines() -> list[bytes]:
    return FIXTURE_PATH.read_bytes().splitlines()


@dataclass(frozen=True)
class _PinnedNdjsonLines:
    """Keep the whole-file pin attached while the reader streams its lines."""

    payload: bytes

    def __iter__(self):
        return iter(self.payload.splitlines())


def _line(index: int) -> bytes:
    return _fixture_lines()[index]


def test_pinned_real_mini_fixture_matches_its_captured_bytes() -> None:
    payload = open_pinned_lcsh_topical_mini_fixture(FIXTURE_PATH)

    assert len(payload) == LCSH_TOPICAL_MINI_FIXTURE_BYTE_LENGTH
    assert ("sha256:" + hashlib.sha256(payload).hexdigest()) == LCSH_TOPICAL_MINI_FIXTURE_SHA256
    assert len(payload.splitlines()) == 6

    capture = capture_lcsh_topical_subset(_PinnedNdjsonLines(payload), source_url=SOURCE_URL)
    assert len(capture.records) == 3
    assert capture.lines_scanned == 6
    assert capture.excluded_count == 3


def test_pinned_fixture_opener_rejects_tampered_bytes(tmp_path: Path) -> None:
    tampered = tmp_path / "lcsh-topical-mini.ndjson"
    tampered.write_bytes(FIXTURE_PATH.read_bytes() + b"\n")

    with pytest.raises(LcshTopicalError, match="byte length"):
        open_pinned_lcsh_topical_mini_fixture(tampered)


def test_parses_topical_record_with_list_valued_broader_authority_and_no_variant() -> None:
    record = parse_lcsh_topical_ndjson_line(_line(0), source_url=SOURCE_URL, line_number=1)

    assert record is not None
    assert record.concept_iri == ACTIONSCRIPT
    assert record.lccn == "sh 00000011"
    assert record.preferred_label == LcshTopicalLabel(value="ActionScript (Computer program language)", language="en")
    assert record.broader_iris == (
        "http://id.loc.gov/authorities/subjects/sh2006006405",
        "http://id.loc.gov/authorities/subjects/sh2006007256",
        "http://id.loc.gov/authorities/subjects/sh2007005223",
    )
    assert record.variant_labels == ()
    assert record.line_number == 1
    assert record.source_url == SOURCE_URL
    assert record.raw_line == _line(0)
    assert record.source_sha256 == "sha256:" + hashlib.sha256(_line(0)).hexdigest()
    assert record.source_byte_length == len(_line(0))


def test_parses_topical_record_with_single_object_valued_broader_authority() -> None:
    record = parse_lcsh_topical_ndjson_line(_line(1), source_url=SOURCE_URL, line_number=2)

    assert record is not None
    assert record.concept_iri == TACOS
    assert record.lccn == "sh 00000014"
    assert record.preferred_label == LcshTopicalLabel(value="Tacos", language="en")
    assert record.broader_iris == ("http://id.loc.gov/authorities/subjects/sh85129334",)
    assert record.variant_labels == ()


def test_parses_topical_record_and_resolves_its_variant_labels() -> None:
    record = parse_lcsh_topical_ndjson_line(_line(2), source_url=SOURCE_URL, line_number=3)

    assert record is not None
    assert record.concept_iri == SAKI
    assert record.preferred_label.value == "White-faced saki"
    assert record.variant_labels == (
        LcshTopicalLabel(value="Pale-headed saki", language="en"),
        LcshTopicalLabel(value="Pithecia pithecia", language="en"),
    )


@pytest.mark.parametrize("index", [3, 4, 5])
def test_non_topical_authority_lines_are_skipped_without_erroring(index: int) -> None:
    record = parse_lcsh_topical_ndjson_line(_line(index), source_url=SOURCE_URL, line_number=index + 1)

    assert record is None


def test_bare_string_typed_component_stub_nodes_are_not_mistaken_for_the_authority() -> None:
    # Line 5 (Angiotensin II--Antagonists, a ComplexSubject) embeds two
    # madsrdf:componentList stub nodes typed bare "madsrdf:Topic" (a string,
    # not a list containing madsrdf:Authority). The parser must still find
    # exactly one authority node and correctly treat this record as
    # non-topical.
    line = _line(4)
    assert b'"@type": "madsrdf:Topic"' in line

    record = parse_lcsh_topical_ndjson_line(line, source_url=SOURCE_URL, line_number=5)

    assert record is None


def test_parser_requires_bytes_input() -> None:
    with pytest.raises(LcshTopicalError, match="bytes"):
        parse_lcsh_topical_ndjson_line("not bytes", source_url=SOURCE_URL, line_number=1)  # type: ignore[arg-type]


def test_parser_skips_blank_lines() -> None:
    assert parse_lcsh_topical_ndjson_line(b"", source_url=SOURCE_URL, line_number=1) is None
    assert parse_lcsh_topical_ndjson_line(b"   ", source_url=SOURCE_URL, line_number=1) is None


def test_parser_rejects_invalid_json() -> None:
    with pytest.raises(LcshTopicalError, match="not valid JSON"):
        parse_lcsh_topical_ndjson_line(b"{not json", source_url=SOURCE_URL, line_number=1)


def test_parser_rejects_invalid_utf8() -> None:
    with pytest.raises(LcshTopicalError, match="UTF-8"):
        parse_lcsh_topical_ndjson_line(b"\xff\xfe", source_url=SOURCE_URL, line_number=1)


def test_parser_rejects_an_unexpected_context() -> None:
    mutated = _line(0).replace(
        b'"@context": "http://id.loc.gov/authorities/subjects/context.json"',
        b'"@context": "http://id.loc.gov/authorities/names/context.json"',
    )
    with pytest.raises(LcshTopicalError, match="@context"):
        parse_lcsh_topical_ndjson_line(mutated, source_url=SOURCE_URL, line_number=1)


def test_parser_rejects_a_missing_graph() -> None:
    document = json.loads(_line(0))
    del document["@graph"]
    with pytest.raises(LcshTopicalError, match="@graph"):
        parse_lcsh_topical_ndjson_line(json.dumps(document).encode("utf-8"), source_url=SOURCE_URL, line_number=1)


def test_parser_selects_the_top_level_authority_when_graph_contains_other_authorities() -> None:
    document = json.loads(_line(0))
    duplicate = dict(document["@graph"][0])
    duplicate["@id"] = "http://id.loc.gov/authorities/subjects/sh99999999"
    document["@graph"].append(duplicate)

    record = parse_lcsh_topical_ndjson_line(
        json.dumps(document).encode("utf-8"),
        source_url=SOURCE_URL,
        line_number=1,
    )

    assert record is not None
    assert record.concept_iri == ACTIONSCRIPT


def test_parser_rejects_a_graph_without_its_top_level_authority() -> None:
    document = json.loads(_line(0))
    document["@graph"][0]["@id"] = (
        "http://id.loc.gov/authorities/subjects/sh99999999"
    )
    with pytest.raises(LcshTopicalError, match="exactly one"):
        parse_lcsh_topical_ndjson_line(json.dumps(document).encode("utf-8"), source_url=SOURCE_URL, line_number=1)


def test_generic_authority_parser_keeps_non_topic_and_does_not_mint_missing_lccn() -> None:
    document = json.loads(_line(3))
    authority = next(
        node
        for node in document["@graph"]
        if node.get("@id") == CHANCHERA_LAKE
    )
    authority.pop("identifiers:lccn", None)

    record = parse_lcsh_authority_ndjson_line(
        json.dumps(document).encode("utf-8"),
        source_url=SOURCE_URL,
        line_number=4,
    )

    assert record is not None
    assert record.concept_iri == CHANCHERA_LAKE
    assert record.lccn is None
    assert "madsrdf:Geographic" in record.authority_types
    assert "madsrdf:Topic" not in record.authority_types


def test_parser_rejects_a_record_missing_its_authoritative_label() -> None:
    document = json.loads(_line(0))
    del document["@graph"][0]["madsrdf:authoritativeLabel"]
    with pytest.raises(LcshTopicalError, match="authoritativeLabel"):
        parse_lcsh_topical_ndjson_line(json.dumps(document).encode("utf-8"), source_url=SOURCE_URL, line_number=1)


def test_parser_rejects_an_untagged_authoritative_label() -> None:
    document = json.loads(_line(0))
    del document["@graph"][0]["madsrdf:authoritativeLabel"]["@language"]
    with pytest.raises(LcshTopicalError, match="language"):
        parse_lcsh_topical_ndjson_line(json.dumps(document).encode("utf-8"), source_url=SOURCE_URL, line_number=1)


def test_parser_rejects_a_record_missing_its_lccn() -> None:
    document = json.loads(_line(0))
    del document["@graph"][0]["identifiers:lccn"]
    with pytest.raises(LcshTopicalError, match="identifiers:lccn"):
        parse_lcsh_topical_ndjson_line(json.dumps(document).encode("utf-8"), source_url=SOURCE_URL, line_number=1)


def test_parser_rejects_a_non_absolute_broader_authority_target() -> None:
    document = json.loads(_line(0))
    document["@graph"][0]["madsrdf:hasBroaderAuthority"] = {"@id": "_:nblank1"}
    with pytest.raises(LcshTopicalError, match="absolute"):
        parse_lcsh_topical_ndjson_line(json.dumps(document).encode("utf-8"), source_url=SOURCE_URL, line_number=1)


def test_parser_rejects_a_dangling_variant_reference() -> None:
    document = json.loads(_line(2))
    document["@graph"][0]["madsrdf:hasVariant"] = [{"@id": "_:doesNotExist"}]
    with pytest.raises(LcshTopicalError, match="hasVariant"):
        parse_lcsh_topical_ndjson_line(json.dumps(document).encode("utf-8"), source_url=SOURCE_URL, line_number=3)


def test_capture_retains_only_topical_records_and_counts_excluded_lines() -> None:
    capture = capture_lcsh_topical_subset(_fixture_lines(), source_url=SOURCE_URL)

    assert [record.concept_iri for record in capture.records] == [ACTIONSCRIPT, TACOS, SAKI]
    assert capture.lines_scanned == 6
    assert capture.excluded_count == 3
    assert capture.source_url == SOURCE_URL


def test_capture_is_bounded_and_stops_as_soon_as_max_records_is_reached() -> None:
    capture = capture_lcsh_topical_subset(_fixture_lines(), source_url=SOURCE_URL, max_records=2)

    assert [record.concept_iri for record in capture.records] == [ACTIONSCRIPT, TACOS]
    # The third fixture line (SAKI) and every line after it are never read.
    assert capture.lines_scanned == 2


def test_capture_rejects_a_non_positive_max_records() -> None:
    with pytest.raises(LcshTopicalError, match="max_records"):
        capture_lcsh_topical_subset(_fixture_lines(), source_url=SOURCE_URL, max_records=0)


def test_capture_refuses_a_bound_above_the_mapping_only_ceiling() -> None:
    with pytest.raises(LcshTopicalError, match="mapping-only ceiling"):
        capture_lcsh_topical_subset(
            _fixture_lines(),
            source_url=SOURCE_URL,
            max_records=MAX_TOPICAL_SUBSET_RECORDS + 1,
        )


def test_capture_rejects_a_repeated_concept_iri_within_one_stream() -> None:
    lines = [_line(0), _line(0)]
    with pytest.raises(LcshTopicalError, match="repeats"):
        capture_lcsh_topical_subset(lines, source_url=SOURCE_URL)


def test_uri_selection_scans_once_and_keeps_every_requested_authority_class() -> None:
    capture = capture_lcsh_authorities_by_iri(
        _fixture_lines(),
        source_url=SOURCE_URL,
        concept_iris=(CHANCHERA_LAKE, ACTIONSCRIPT),
    )

    assert capture.lines_scanned == 6
    assert capture.requested_iris == tuple(sorted((ACTIONSCRIPT, CHANCHERA_LAKE)))
    assert [record.concept_iri for record in capture.records] == list(
        capture.requested_iris
    )
    assert {record.concept_iri: record.authority_types for record in capture.records} == {
        ACTIONSCRIPT: ("madsrdf:Authority", "madsrdf:Topic"),
        CHANCHERA_LAKE: ("madsrdf:Authority", "madsrdf:Geographic"),
    }


def test_uri_selection_fails_closed_when_a_requested_authority_is_absent() -> None:
    with pytest.raises(LcshTopicalError, match="lacks 1 requested authorities"):
        capture_lcsh_authorities_by_iri(
            _fixture_lines(),
            source_url=SOURCE_URL,
            concept_iris=(
                "http://id.loc.gov/authorities/subjects/sh99999999",
            ),
        )


def test_capture_from_gzip_path_streams_a_bounded_prefix(tmp_path: Path) -> None:
    gzip_path = tmp_path / "subjects.madsrdf.jsonld.gz"
    with gzip.open(gzip_path, "wb") as handle:
        handle.write(FIXTURE_PATH.read_bytes())

    capture = capture_lcsh_topical_subset_from_gzip_path(gzip_path, source_url=SOURCE_URL, max_records=2)

    assert [record.concept_iri for record in capture.records] == [ACTIONSCRIPT, TACOS]
    assert capture.lines_scanned == 2


def test_capture_from_gzip_path_rejects_a_missing_file(tmp_path: Path) -> None:
    with pytest.raises(LcshTopicalError, match="regular file"):
        capture_lcsh_topical_subset_from_gzip_path(tmp_path / "absent.gz", source_url=SOURCE_URL)


def test_capture_from_gzip_path_rejects_a_symlink(tmp_path: Path) -> None:
    gzip_path = tmp_path / "subjects.madsrdf.jsonld.gz"
    with gzip.open(gzip_path, "wb") as handle:
        handle.write(FIXTURE_PATH.read_bytes())
    link = tmp_path / "link.gz"
    link.symlink_to(gzip_path)

    with pytest.raises(LcshTopicalError, match="regular file"):
        capture_lcsh_topical_subset_from_gzip_path(link, source_url=SOURCE_URL)


def _topical_records():
    capture = capture_lcsh_topical_subset(_fixture_lines(), source_url=SOURCE_URL)
    return capture.records


def test_build_lcsh_topical_snapshot_produces_a_mapping_only_bundle(tmp_path: Path) -> None:
    bundle = build_lcsh_topical_snapshot(
        _topical_records(),
        resource_id="lcsh-topical-mini-2026-08-03",
        title="LCSH topical subset, captured 2026-08-03",
        captured_at=CAPTURED_AT,
        source_observed_count=6,
    )

    manifest = bundle.resource_manifest
    assert manifest["resourceKind"] == "sourceTermSnapshot"
    assert manifest["identityStatus"] == "publisherIdentifiersPreserved"
    assert manifest["schemaVersion"] == "2.0"
    assert "candidateUseAuthorized" not in manifest
    assert "acceptedOutputUseAuthorized" not in manifest
    assert manifest["conceptIdentityClaimed"] is False
    assert manifest["uses"] == ("mappingReference", "searchExpansion")
    assert manifest["observationCount"] == 3

    coverage = bundle.coverage_report
    assert coverage["sourceObservedCount"] == 6
    assert coverage["parsedCount"] == 3
    assert coverage["excludedCount"] == 3
    assert coverage["reportStatus"] == "gap"

    def _concept_uri(observation: dict) -> str:
        return next(
            identifier["value"]
            for identifier in observation["identifiers"]
            if identifier["kind"] == LCSH_CONCEPT_URI_IDENTIFIER_KIND
        )

    by_iri = {_concept_uri(observation): observation for observation in bundle.observations}
    saki = by_iri[SAKI]
    assert saki["conceptIdentityClaimed"] is False
    assert saki["uses"] == ("mappingReference", "searchExpansion")
    assert [label["role"] for label in saki["labels"]] == ["preferred", "alternate", "alternate"]
    assert {label["value"] for label in saki["labels"] if label["role"] == "alternate"} == {
        "Pale-headed saki",
        "Pithecia pithecia",
    }
    identifier_kinds = {identifier["kind"] for identifier in saki["identifiers"]}
    assert identifier_kinds == {LCSH_LCCN_IDENTIFIER_KIND, LCSH_CONCEPT_URI_IDENTIFIER_KIND}
    for identifier in saki["identifiers"]:
        assert identifier["authorityUri"] == LCSH_SUBJECTS_SCHEME_IRI
        assert identifier["sourceUri"] == SOURCE_URL
        assert identifier["sourceDigest"] == ("sha256:" + hashlib.sha256(_line(2)).hexdigest())

    package_path = bundle.write_to(tmp_path / "package")
    opened = SourceControlledResourceView.open(package_path)
    assert opened.logical_digest == bundle.logical_digest
    assert opened.source_artifact_bytes(SAKI) == _line(2)


def test_build_lcsh_topical_snapshot_requires_at_least_one_record() -> None:
    with pytest.raises(LcshTopicalError, match="at least one"):
        build_lcsh_topical_snapshot(
            (),
            resource_id="empty",
            title="Empty",
            captured_at=CAPTURED_AT,
            source_observed_count=0,
        )


def test_build_lcsh_topical_snapshot_rejects_mixed_source_urls() -> None:
    records = list(_topical_records())
    other = parse_lcsh_topical_ndjson_line(
        _line(0),
        source_url="https://example.test/other.ndjson",
        line_number=1,
    )
    records[0] = other

    with pytest.raises(LcshTopicalError, match="same source_url"):
        build_lcsh_topical_snapshot(
            records,
            resource_id="mixed",
            title="Mixed",
            captured_at=CAPTURED_AT,
            source_observed_count=6,
        )
