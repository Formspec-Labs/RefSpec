"""Bounded LCSH topical ndjson streaming-parser tests.

Every test reads bytes from a fixture or an in-test mutation of one; nothing
here opens a network connection.
"""

from __future__ import annotations

import gzip
import hashlib
import itertools
import json
from dataclasses import dataclass
from pathlib import Path

import pytest

from refspec.registry.infrastructure.source_controlled_resource import SourceControlledResourceView
from refspec.registry.lcsh_topical import (
    LCSH_CONCEPT_URI_IDENTIFIER_KIND,
    LCSH_EXPECTED_CONTEXT_URL,
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
    capture_lcsh_current_and_referenced_deprecated,
    capture_lcsh_topical_subset,
    capture_lcsh_topical_subset_from_gzip_path,
    open_pinned_lcsh_topical_mini_fixture,
    parse_lcsh_authority_ndjson_line,
    parse_lcsh_authority_or_deprecated_ndjson_line,
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


# REF-040: a byte-faithful synthetic deprecated authority, matching the real
# shape LC publishes (captured 2026-08-17 from a byte-range read of the
# pinned bulk file: http://id.loc.gov/authorities/subjects/sh00000273,
# "Child concentration camp inmates"). madsrdf:DeprecatedAuthority records
# carry no madsrdf:authoritativeLabel; their only label is
# madsrdf:variantLabel, because the record is itself typed madsrdf:Variant.
DEPRECATED_IRI = "http://id.loc.gov/authorities/subjects/sh00000273"
USE_INSTEAD_IRI_1 = "http://id.loc.gov/authorities/subjects/sh2021004026"
USE_INSTEAD_IRI_2 = "http://id.loc.gov/authorities/subjects/sh2021004027"


def _deprecated_document(
    *,
    use_instead: bool = True,
    deletion_note: bool = True,
) -> dict:
    authority: dict = {
        "@id": DEPRECATED_IRI,
        "@type": ["madsrdf:DeprecatedAuthority", "madsrdf:Topic", "madsrdf:Variant"],
        "madsrdf:variantLabel": {"@language": "en", "@value": "Child concentration camp inmates"},
    }
    if use_instead:
        authority["madsrdf:useInstead"] = [{"@id": USE_INSTEAD_IRI_1}, {"@id": USE_INSTEAD_IRI_2}]
    if deletion_note:
        authority["madsrdf:deletionNote"] = {
            "@language": "en",
            "@value": "This authority record has been deleted because the heading is covered by other headings",
        }
    return {
        "@context": LCSH_EXPECTED_CONTEXT_URL,
        "@graph": [authority],
        "@id": "/authorities/subjects/sh00000273",
    }


def _deprecated_line(**kwargs) -> bytes:
    return json.dumps(_deprecated_document(**kwargs)).encode("utf-8")


def test_deprecated_authority_parses_with_variant_label_as_preferred_and_use_instead() -> None:
    record = parse_lcsh_authority_or_deprecated_ndjson_line(_deprecated_line(), source_url=SOURCE_URL, line_number=1)

    assert record is not None
    assert record.is_deprecated
    assert record.concept_iri == DEPRECATED_IRI
    assert record.preferred_label == LcshTopicalLabel(value="Child concentration camp inmates", language="en")
    assert record.variant_labels == ()
    assert record.use_instead_iris == (USE_INSTEAD_IRI_1, USE_INSTEAD_IRI_2)
    assert record.deletion_note is not None
    assert record.deletion_note.language == "en"
    assert "deleted" in record.deletion_note.value


def test_deprecated_authority_without_use_instead_or_deletion_note_still_parses() -> None:
    record = parse_lcsh_authority_or_deprecated_ndjson_line(
        _deprecated_line(use_instead=False, deletion_note=False),
        source_url=SOURCE_URL,
        line_number=1,
    )

    assert record is not None
    assert record.is_deprecated
    assert record.use_instead_iris == ()
    assert record.deletion_note is None


def test_active_record_parsed_by_the_deprecated_admitting_parser_carries_no_deprecation_fields() -> None:
    record = parse_lcsh_authority_or_deprecated_ndjson_line(_line(0), source_url=SOURCE_URL, line_number=1)

    assert record is not None
    assert not record.is_deprecated
    assert record.use_instead_iris == ()
    assert record.deletion_note is None
    assert record.concept_iri == ACTIONSCRIPT


def test_parsers_that_never_admit_deprecated_still_reject_a_deprecated_line() -> None:
    # Callers that do not opt in see no behavior change: both existing
    # public parse functions still fail closed on a deprecated authority.
    with pytest.raises(LcshTopicalError, match="exactly one"):
        parse_lcsh_topical_ndjson_line(_deprecated_line(), source_url=SOURCE_URL, line_number=1)
    with pytest.raises(LcshTopicalError, match="exactly one"):
        parse_lcsh_authority_ndjson_line(_deprecated_line(), source_url=SOURCE_URL, line_number=1)


def test_authority_typed_both_active_and_deprecated_is_rejected() -> None:
    document = _deprecated_document()
    document["@graph"][0]["@type"].append("madsrdf:Authority")

    with pytest.raises(LcshTopicalError, match="both active and deprecated"):
        parse_lcsh_authority_or_deprecated_ndjson_line(
            json.dumps(document).encode("utf-8"),
            source_url=SOURCE_URL,
            line_number=1,
        )


def test_blank_node_broader_target_is_excluded_only_when_admitting_deprecated() -> None:
    document = json.loads(_line(0))
    document["@graph"][0]["madsrdf:hasBroaderAuthority"] = {"@id": "_:nblank1"}
    line = json.dumps(document).encode("utf-8")

    record = parse_lcsh_authority_or_deprecated_ndjson_line(line, source_url=SOURCE_URL, line_number=1)
    assert record is not None
    assert record.broader_iris == ()

    with pytest.raises(LcshTopicalError, match="absolute"):
        parse_lcsh_topical_ndjson_line(line, source_url=SOURCE_URL, line_number=1)


def test_repeated_variant_label_tolerated_only_when_admitting_deprecated() -> None:
    # Line 2 (SAKI) has two madsrdf:hasVariant references, "Pale-headed saki"
    # and "Pithecia pithecia". Add a third reference to a new blank node
    # carrying an identical (value, language) pair to the first.
    document = json.loads(_line(2))
    graph = document["@graph"]
    authority = next(node for node in graph if node.get("@id") == SAKI)
    duplicate_element = {
        "@id": "_:duplicateVariantElement",
        "@type": "madsrdf:TopicElement",
        "madsrdf:elementValue": {"@language": "en", "@value": "Pale-headed saki"},
    }
    duplicate_variant = {
        "@id": "_:duplicateVariant",
        "@type": ["madsrdf:Topic", "madsrdf:Variant"],
        "madsrdf:elementList": {"@list": [{"@id": "_:duplicateVariantElement"}]},
        "madsrdf:variantLabel": {"@language": "en", "@value": "Pale-headed saki"},
    }
    graph.extend([duplicate_element, duplicate_variant])
    authority["madsrdf:hasVariant"] = [*authority["madsrdf:hasVariant"], {"@id": "_:duplicateVariant"}]
    line = json.dumps(document).encode("utf-8")

    record = parse_lcsh_authority_or_deprecated_ndjson_line(line, source_url=SOURCE_URL, line_number=3)
    assert record is not None
    assert record.variant_labels == (
        LcshTopicalLabel(value="Pale-headed saki", language="en"),
        LcshTopicalLabel(value="Pithecia pithecia", language="en"),
    )

    with pytest.raises(LcshTopicalError, match="repeats an identical variant label"):
        parse_lcsh_topical_ndjson_line(line, source_url=SOURCE_URL, line_number=3)


def test_capture_current_and_referenced_deprecated_retains_only_referenced_deprecated() -> None:
    # All six fixture lines are current authorities of some class (three
    # topical, three not); this reader admits every authority class, not
    # only topical headings, matching REF-040's "every authority class" scope.
    lines = [*_fixture_lines(), _deprecated_line()]

    unreferenced = capture_lcsh_current_and_referenced_deprecated(lines, source_url=SOURCE_URL, referenced_iris=())
    assert len(unreferenced.current_records) == 6
    assert unreferenced.deprecated_records == ()
    assert unreferenced.total_deprecated_seen == 1
    assert unreferenced.missing_referenced_iris == frozenset()

    referenced = capture_lcsh_current_and_referenced_deprecated(
        lines,
        source_url=SOURCE_URL,
        referenced_iris=(DEPRECATED_IRI, "http://id.loc.gov/authorities/subjects/sh99999999"),
    )
    assert len(referenced.current_records) == 6
    assert [record.concept_iri for record in referenced.deprecated_records] == [DEPRECATED_IRI]
    assert referenced.total_deprecated_seen == 1
    assert referenced.missing_referenced_iris == frozenset(
        {"http://id.loc.gov/authorities/subjects/sh99999999"}
    )


def test_capture_current_and_referenced_deprecated_rejects_a_repeated_concept() -> None:
    lines = [_line(0), _line(0)]
    with pytest.raises(LcshTopicalError, match="repeats concept"):
        capture_lcsh_current_and_referenced_deprecated(lines, source_url=SOURCE_URL, referenced_iris=())


PINNED_LCSH_BULK_PATH = (
    Path(__file__).resolve().parents[1]
    / "output"
    / "registry-real-data-sources"
    / "lcsh-subjects-madsrdf-2026-08-06.jsonld.gz"
)


@pytest.mark.skipif(not PINNED_LCSH_BULK_PATH.is_file(), reason="pinned LCSH bulk file is not cached")
def test_real_pinned_bulk_prefix_carries_a_real_deprecated_authority() -> None:
    # A bounded 200-line prefix of the real pinned file, not the full
    # 521,055-line / ~15s scan: line 188 is the real sh00000273 deprecated
    # record this module's fixtures are modeled on.
    with gzip.open(PINNED_LCSH_BULK_PATH, "rb") as handle:
        prefix = list(itertools.islice(handle, 200))
    assert len(prefix) == 200

    capture = capture_lcsh_current_and_referenced_deprecated(
        prefix, source_url=LCSH_TOPICAL_MADS_NDJSON_URL, referenced_iris=(DEPRECATED_IRI,)
    )

    assert capture.total_deprecated_seen >= 1
    retained = {record.concept_iri: record for record in capture.deprecated_records}
    assert DEPRECATED_IRI in retained
    real_record = retained[DEPRECATED_IRI]
    assert real_record.preferred_label.value == "Child concentration camp inmates"
    assert set(real_record.use_instead_iris) == {USE_INSTEAD_IRI_1, USE_INSTEAD_IRI_2}
    assert real_record.deletion_note is not None


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
