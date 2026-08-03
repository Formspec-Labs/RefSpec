"""EPA Enterprise Vocabulary export parser and capture tests.

Fixtures are real, byte-exact Terminology Services (System of Registries)
captures from https://ofmpub.epa.gov/sor_internet/registry/termreg/
searchandretrieve/enterprisevocabulary/search.do (tier 1005100, "Regulatory
Activities"), fetched 2026-08-03. No test opens a network connection; every
payload is a fixture file already checked into the repo or a small synthetic
string built for one edge case.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from refspec.registry.epa_enterprise_vocabulary import (
    EPA_ENTERPRISE_VOCABULARY_CATALOG_ROLE,
    EPA_ENTERPRISE_VOCABULARY_VERIFICATION_GAPS,
    EPA_LANDING_PAGE_URL,
    EPA_PUBLISHER,
    EPA_REGULATORY_ACTIVITIES_TIER_CAPTURE,
    EPA_REGULATORY_ACTIVITIES_TIER_WITH_DEFINITIONS_CAPTURE,
    EpaEnterpriseVocabularyError,
    EpaFetchedExport,
    EpaImportCounts,
    acquire_epa_enterprise_vocabulary_export,
    epa_enterprise_vocabulary_capture_digest,
    epa_enterprise_vocabulary_capture_manifest,
    parse_epa_enterprise_vocabulary_export,
    parse_epa_enterprise_vocabulary_file,
)

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "epa_enterprise_vocabulary"
NO_DEFS_PATH = FIXTURE_DIR / "epa-enterprise-vocabulary-tier-1005100.xml"
WITH_DEFS_PATH = FIXTURE_DIR / "epa-enterprise-vocabulary-tier-1005100-with-definitions.xml"

SYNTHETIC_THREE_LEVEL_TURTLE = """\
<?xml version="1.0"?>
<EnterpriseVocabularyReport>
<Row>
<Term>Top A</Term>
<ChildTerms><Row>
<Term>Mid A1</Term>
<ChildTerms><Row>
<Term>Leaf A1a</Term>
<ChildTerms></ChildTerms>
</Row>
</ChildTerms>
</Row>
</ChildTerms>
</Row>
<Row>
<Term>Top B</Term>
<ChildTerms></ChildTerms>
</Row>
</EnterpriseVocabularyReport>
"""


def _fixture_bytes(path: Path) -> bytes:
    return path.read_bytes()


def test_parser_preserves_the_real_tier_export_without_definitions_requested() -> None:
    source = _fixture_bytes(NO_DEFS_PATH)
    export = parse_epa_enterprise_vocabulary_export(
        source,
        source_url=EPA_REGULATORY_ACTIVITIES_TIER_CAPTURE.source_url,
    )

    assert export.source_bytes == len(source)
    assert export.source_sha256 == "sha256:" + hashlib.sha256(source).hexdigest()
    assert export == parse_epa_enterprise_vocabulary_export(
        source, source_url=EPA_REGULATORY_ACTIVITIES_TIER_CAPTURE.source_url
    )

    assert [row.label for row in export.rows] == ["Non-Regulatory Solution", "Regulatory Activity"]
    non_regulatory, regulatory = export.rows
    assert non_regulatory.child_terms == ()
    # This capture never requested definitions/scope notes; the elements are
    # genuinely absent from the payload, not merely empty.
    assert non_regulatory.definitions_text is None
    assert non_regulatory.scope_note_text is None

    assert len(regulatory.child_terms) == 1
    deregulation = regulatory.child_terms[0]
    assert deregulation.label == "Deregulation"
    assert deregulation.definitions_text is None
    assert deregulation.scope_note_text is None
    assert deregulation.child_terms == ()
    assert deregulation.source_path == "Row[1]/Row[0]"

    assert export.counts == EpaImportCounts(
        source_bytes=len(source),
        top_level_rows=2,
        total_rows=3,
        max_depth=2,
        rows_with_definitions_element=0,
        rows_with_nonblank_definitions=0,
        rows_with_scope_note_element=0,
        rows_with_nonblank_scope_notes=0,
    )


def test_parser_preserves_definitions_and_a_literal_nbsp_scope_note() -> None:
    source = _fixture_bytes(WITH_DEFS_PATH)
    export = parse_epa_enterprise_vocabulary_export(
        source,
        source_url=EPA_REGULATORY_ACTIVITIES_TIER_WITH_DEFINITIONS_CAPTURE.source_url,
    )

    non_regulatory, regulatory = export.rows
    # Present-but-empty elements are "" (an element the source chose to
    # publish empty), which is distinct from None (element absent).
    assert non_regulatory.definitions_text == ""
    assert non_regulatory.scope_note_text == ""

    deregulation = regulatory.child_terms[0]
    assert deregulation.definitions_text is not None
    assert deregulation.definitions_text.startswith("Definition: The removal or relaxation")
    assert deregulation.definitions_text.endswith("[GEneral Multilingual Environmental Thesaurus]")
    # The source's own scope note for this row is a lone non-breaking space,
    # not an empty string; the raw character is preserved rather than
    # normalized away.
    assert deregulation.scope_note_text == "\xa0"

    assert export.counts == EpaImportCounts(
        source_bytes=len(source),
        top_level_rows=2,
        total_rows=3,
        max_depth=2,
        rows_with_definitions_element=3,
        rows_with_nonblank_definitions=1,
        rows_with_scope_note_element=3,
        rows_with_nonblank_scope_notes=0,
    )


def test_parser_tracks_ordinal_source_paths_and_depth_on_a_synthetic_three_level_tree() -> None:
    export = parse_epa_enterprise_vocabulary_export(
        SYNTHETIC_THREE_LEVEL_TURTLE,
        source_url="https://example.test/epa-ev-three-level.xml",
    )

    top_a, top_b = export.rows
    assert top_a.source_path == "Row[0]"
    mid_a1 = top_a.child_terms[0]
    assert mid_a1.source_path == "Row[0]/Row[0]"
    leaf = mid_a1.child_terms[0]
    assert leaf.source_path == "Row[0]/Row[0]/Row[0]"
    assert top_b.source_path == "Row[1]"
    assert top_b.child_terms == ()

    assert export.counts.max_depth == 3
    assert export.counts.total_rows == 4
    assert export.counts.top_level_rows == 2


@pytest.mark.parametrize(
    ("source", "message"),
    [
        (
            '<?xml version="1.0"?><NotTheRightRoot></NotTheRightRoot>',
            "root element must be",
        ),
        (
            '<?xml version="1.0"?><EnterpriseVocabularyReport unexpected="1"></EnterpriseVocabularyReport>',
            "must not carry attributes",
        ),
        (
            '<?xml version="1.0"?><EnterpriseVocabularyReport>stray text</EnterpriseVocabularyReport>',
            "unexpected text content",
        ),
        (
            '<?xml version="1.0"?><EnterpriseVocabularyReport><NotARow /></EnterpriseVocabularyReport>',
            "unsupported element",
        ),
        (
            (
                '<?xml version="1.0"?><EnterpriseVocabularyReport><Row><ChildTerms></ChildTerms></Row>'
                "</EnterpriseVocabularyReport>"
            ),
            "exactly one",
        ),
        (
            (
                '<?xml version="1.0"?><EnterpriseVocabularyReport><Row><Term>   </Term></Row>'
                "</EnterpriseVocabularyReport>"
            ),
            "must not be blank",
        ),
        (
            (
                '<?xml version="1.0"?><EnterpriseVocabularyReport><Row><Term id="x">A</Term></Row>'
                "</EnterpriseVocabularyReport>"
            ),
            "must not carry attributes",
        ),
        (
            (
                '<?xml version="1.0"?><EnterpriseVocabularyReport><Row><Term>A</Term>'
                "<Extra>1</Extra></Row></EnterpriseVocabularyReport>"
            ),
            "unsupported child element",
        ),
        (
            (
                '<?xml version="1.0"?><EnterpriseVocabularyReport><Row><Term>A</Term><Term>B</Term></Row>'
                "</EnterpriseVocabularyReport>"
            ),
            "more than one",
        ),
        (
            (
                '<?xml version="1.0"?><EnterpriseVocabularyReport><Row><Term>A</Term>'
                "<ChildTerms>stray</ChildTerms></Row></EnterpriseVocabularyReport>"
            ),
            "unexpected text content",
        ),
        (
            (
                '<?xml version="1.0"?><EnterpriseVocabularyReport><Row><Term>A</Term>'
                "<ChildTerms><NotARow /></ChildTerms></Row></EnterpriseVocabularyReport>"
            ),
            "unsupported element",
        ),
        (
            "not xml at all",
            "could not parse",
        ),
    ],
)
def test_parser_rejects_lossy_or_ambiguous_export_shapes(source: str, message: str) -> None:
    with pytest.raises(EpaEnterpriseVocabularyError, match=message):
        parse_epa_enterprise_vocabulary_export(source, source_url="https://example.test/epa-ev-edge.xml")


def test_parser_rejects_a_relative_source_url() -> None:
    with pytest.raises(EpaEnterpriseVocabularyError, match="absolute IRI"):
        parse_epa_enterprise_vocabulary_export(
            '<?xml version="1.0"?><EnterpriseVocabularyReport></EnterpriseVocabularyReport>',
            source_url="not-a-url",
        )


def test_parser_enforces_optional_distribution_digest_and_size_pins() -> None:
    source = _fixture_bytes(NO_DEFS_PATH)
    digest = "sha256:" + hashlib.sha256(source).hexdigest()
    parsed = parse_epa_enterprise_vocabulary_export(
        source,
        source_url=EPA_REGULATORY_ACTIVITIES_TIER_CAPTURE.source_url,
        expected_sha256=digest,
        expected_byte_length=len(source),
    )
    assert parsed.source_sha256 == digest

    with pytest.raises(EpaEnterpriseVocabularyError, match="digest mismatch"):
        parse_epa_enterprise_vocabulary_export(
            source,
            source_url=EPA_REGULATORY_ACTIVITIES_TIER_CAPTURE.source_url,
            expected_sha256="sha256:" + "0" * 64,
        )
    with pytest.raises(EpaEnterpriseVocabularyError, match="byte length mismatch"):
        parse_epa_enterprise_vocabulary_export(
            source,
            source_url=EPA_REGULATORY_ACTIVITIES_TIER_CAPTURE.source_url,
            expected_byte_length=len(source) + 1,
        )
    with pytest.raises(EpaEnterpriseVocabularyError, match="sha256:<64 hex>"):
        parse_epa_enterprise_vocabulary_export(
            source,
            source_url=EPA_REGULATORY_ACTIVITIES_TIER_CAPTURE.source_url,
            expected_sha256="not-a-digest",
        )


@pytest.mark.parametrize(
    "pinned",
    [EPA_REGULATORY_ACTIVITIES_TIER_CAPTURE, EPA_REGULATORY_ACTIVITIES_TIER_WITH_DEFINITIONS_CAPTURE],
)
def test_pinned_real_captures_match_committed_fixture_bytes(pinned) -> None:
    path = NO_DEFS_PATH if not pinned.includes_definitions else WITH_DEFS_PATH
    source = path.read_bytes()
    assert len(source) == pinned.expected_byte_length
    assert "sha256:" + hashlib.sha256(source).hexdigest() == pinned.expected_sha256

    export = parse_epa_enterprise_vocabulary_export(
        source,
        source_url=pinned.source_url,
        expected_sha256=pinned.expected_sha256,
        expected_byte_length=pinned.expected_byte_length,
    )
    assert export.source_sha256 == pinned.expected_sha256
    assert [row.label for row in export.rows] == ["Non-Regulatory Solution", "Regulatory Activity"]


def test_parse_epa_enterprise_vocabulary_file_reads_a_local_pinned_fixture(tmp_path: Path) -> None:
    pinned = EPA_REGULATORY_ACTIVITIES_TIER_CAPTURE
    source = NO_DEFS_PATH.read_bytes()
    local_path = tmp_path / "capture.xml"
    local_path.write_bytes(source)

    export = parse_epa_enterprise_vocabulary_file(
        local_path,
        source_url=pinned.source_url,
        expected_sha256=pinned.expected_sha256,
        expected_byte_length=pinned.expected_byte_length,
    )
    assert export.source_sha256 == pinned.expected_sha256

    with pytest.raises(EpaEnterpriseVocabularyError, match="not a regular file"):
        parse_epa_enterprise_vocabulary_file(
            tmp_path / "missing.xml",
            source_url=pinned.source_url,
        )


def test_acquire_export_requires_an_explicit_transport() -> None:
    with pytest.raises(EpaEnterpriseVocabularyError, match="requires fetch or allow_direct_network=True"):
        acquire_epa_enterprise_vocabulary_export("https://example.test/epa-ev-edge.xml")


def test_acquire_export_uses_an_injected_fetcher_and_matches_direct_parsing() -> None:
    body = _fixture_bytes(NO_DEFS_PATH)
    url = "https://example.test/epa-ev-tier-1005100.xml"

    def fetch(requested_url: str, *, timeout_seconds: float, max_bytes: int) -> EpaFetchedExport:
        assert requested_url == url
        assert timeout_seconds > 0
        assert max_bytes > 0
        return EpaFetchedExport(
            requested_url=requested_url,
            resolved_url=requested_url,
            status_code=200,
            content_type="text/xml; charset=UTF-8",
            body=body,
        )

    export = acquire_epa_enterprise_vocabulary_export(url, fetch=fetch)
    direct = parse_epa_enterprise_vocabulary_export(body, source_url=url)
    assert export == direct


def test_acquire_export_rejects_a_non_200_response() -> None:
    def fetch(requested_url: str, *, timeout_seconds: float, max_bytes: int) -> EpaFetchedExport:
        return EpaFetchedExport(
            requested_url=requested_url,
            resolved_url=requested_url,
            status_code=404,
            content_type="text/html",
            body=b"not found",
        )

    with pytest.raises(EpaEnterpriseVocabularyError, match="HTTP 404"):
        acquire_epa_enterprise_vocabulary_export("https://example.test/epa-ev-edge.xml", fetch=fetch)


def test_acquire_export_rejects_a_mismatched_requested_url() -> None:
    def fetch(requested_url: str, *, timeout_seconds: float, max_bytes: int) -> EpaFetchedExport:
        return EpaFetchedExport(
            requested_url="https://example.test/wrong.xml",
            resolved_url="https://example.test/wrong.xml",
            status_code=200,
            content_type="text/xml",
            body=b"",
        )

    with pytest.raises(EpaEnterpriseVocabularyError, match="different requested_url"):
        acquire_epa_enterprise_vocabulary_export("https://example.test/epa-ev-edge.xml", fetch=fetch)


def test_acquire_export_rejects_a_response_over_max_bytes() -> None:
    def fetch(requested_url: str, *, timeout_seconds: float, max_bytes: int) -> EpaFetchedExport:
        return EpaFetchedExport(
            requested_url=requested_url,
            resolved_url=requested_url,
            status_code=200,
            content_type="text/xml",
            body=b"x" * (max_bytes + 1),
        )

    with pytest.raises(EpaEnterpriseVocabularyError, match="exceeds max_bytes"):
        acquire_epa_enterprise_vocabulary_export("https://example.test/epa-ev-edge.xml", fetch=fetch, max_bytes=16)


def test_capture_manifest_is_deterministic_and_records_every_verification_gap() -> None:
    export = parse_epa_enterprise_vocabulary_export(
        _fixture_bytes(WITH_DEFS_PATH),
        source_url=EPA_REGULATORY_ACTIVITIES_TIER_WITH_DEFINITIONS_CAPTURE.source_url,
    )
    manifest = epa_enterprise_vocabulary_capture_manifest(
        export,
        tier_browse_url=EPA_REGULATORY_ACTIVITIES_TIER_WITH_DEFINITIONS_CAPTURE.tier_browse_url,
        retrieved_at=EPA_REGULATORY_ACTIVITIES_TIER_WITH_DEFINITIONS_CAPTURE.retrieved_at,
    )
    assert manifest == epa_enterprise_vocabulary_capture_manifest(
        export,
        tier_browse_url=EPA_REGULATORY_ACTIVITIES_TIER_WITH_DEFINITIONS_CAPTURE.tier_browse_url,
        retrieved_at=EPA_REGULATORY_ACTIVITIES_TIER_WITH_DEFINITIONS_CAPTURE.retrieved_at,
    )

    assert manifest["kind"] == "skosVocabulary"
    assert manifest["publisher"] == EPA_PUBLISHER
    assert manifest["landingPageUrl"] == EPA_LANDING_PAGE_URL
    assert manifest["catalogRole"] == EPA_ENTERPRISE_VOCABULARY_CATALOG_ROLE
    assert "Defer pilot inclusion" in manifest["catalogRole"]
    assert manifest["sourceIsNativeSkosRdf"] is False
    assert manifest["conceptIdentityClaimed"] is False
    assert manifest["candidateUseAuthorized"] is False

    gap_kinds = {gap["kind"] for gap in manifest["verificationGaps"]}
    assert gap_kinds == {gap.kind for gap in EPA_ENTERPRISE_VOCABULARY_VERIFICATION_GAPS}
    assert {"editionDate", "license", "maintenanceEvidence", "exportDurability", "termIdentifiers"}.issubset(gap_kinds)

    digest_a = epa_enterprise_vocabulary_capture_digest(
        export,
        tier_browse_url=EPA_REGULATORY_ACTIVITIES_TIER_WITH_DEFINITIONS_CAPTURE.tier_browse_url,
        retrieved_at=EPA_REGULATORY_ACTIVITIES_TIER_WITH_DEFINITIONS_CAPTURE.retrieved_at,
    )
    digest_b = epa_enterprise_vocabulary_capture_digest(
        export,
        tier_browse_url=EPA_REGULATORY_ACTIVITIES_TIER_WITH_DEFINITIONS_CAPTURE.tier_browse_url,
        retrieved_at=EPA_REGULATORY_ACTIVITIES_TIER_WITH_DEFINITIONS_CAPTURE.retrieved_at,
    )
    assert digest_a == digest_b
    assert digest_a.startswith("sha256:")

    other_export = parse_epa_enterprise_vocabulary_export(
        _fixture_bytes(NO_DEFS_PATH),
        source_url=EPA_REGULATORY_ACTIVITIES_TIER_CAPTURE.source_url,
    )
    other_digest = epa_enterprise_vocabulary_capture_digest(
        other_export,
        tier_browse_url=EPA_REGULATORY_ACTIVITIES_TIER_CAPTURE.tier_browse_url,
        retrieved_at=EPA_REGULATORY_ACTIVITIES_TIER_CAPTURE.retrieved_at,
    )
    assert other_digest != digest_a
