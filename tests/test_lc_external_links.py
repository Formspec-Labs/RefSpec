"""LC external-links reader tests over exact excerpts and the pinned archive."""

from __future__ import annotations

import hashlib
from collections import Counter
from pathlib import Path

import pytest

from refspec.registry import lc_external_links as lc

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "lc_external_links" / "lcsh-external-links-mini.nt"
SOURCE = ROOT / "output" / "registry-real-data-sources" / lc.LC_EXTERNAL_LINKS_FILENAME


def _fixture_lines() -> tuple[bytes, ...]:
    return tuple(FIXTURE.read_bytes().splitlines(keepends=True))


def test_exact_publisher_statement_fixture_is_pinned() -> None:
    payload = FIXTURE.read_bytes()

    assert len(payload) == 1_111
    assert hashlib.sha256(payload).hexdigest() == ("4af3601c5925c1e63c74807c77fcb8eac2863d12c2726772b8beaef56b81b13c")


def test_reader_preserves_all_four_mads_predicates_and_direction() -> None:
    capture = lc.parse_lc_external_links_statements(_fixture_lines())

    assert len(capture.assertions) == 4
    assert Counter(row.predicate_iri for row in capture.assertions) == {
        lc.MADS_BROADER_EXTERNAL_AUTHORITY: 1,
        lc.MADS_CLOSE_EXTERNAL_AUTHORITY: 1,
        lc.MADS_EXACT_EXTERNAL_AUTHORITY: 1,
        lc.MADS_NARROWER_EXTERNAL_AUTHORITY: 1,
    }
    assert [row.target_vocabulary for row in capture.assertions] == [
        "rameau",
        "fast",
        "nalt",
        "yso",
    ]
    assert all(row.subject_iri.startswith(lc.LCSH_SUBJECT_PREFIX) for row in capture.assertions)
    assert not any(row.object_iri.startswith(lc.LCSH_SUBJECT_PREFIX) for row in capture.assertions)
    assert all(row.native_statement.endswith(" .") for row in capture.assertions)
    assert all(row.statement_sha256.startswith("sha256:") for row in capture.assertions)


def test_reader_retains_absent_publisher_tag_and_records_language_rule() -> None:
    capture = lc.parse_lc_external_links_statements(_fixture_lines())
    rameau = capture.endpoint_labels["http://data.bnf.fr/ark:/12148/cb124656189"]

    assert len(capture.endpoint_labels) == 4
    assert capture.unlabeled_target_count == 0
    assert capture.explicitly_english_target_count == 0
    assert rameau[0].value == "Conditions économiques -- Rome -- 30 av. J.-C.-284"
    assert rameau[0].language is None
    assert rameau[0].datatype_iri is None
    assert rameau[0].determined_language == "fr"
    assert rameau[0].language_determined_by == (
        "authorityConvention:bnf-rameau-authoritative-labels-are-French"
    )
    assert capture.determined_language_label_counts == {"en": 2, "fi": 1, "fr": 1}
    assert capture.indeterminate_label_count == 0


def test_language_fallback_is_script_based_and_refuses_ambiguous_text() -> None:
    assert lc.determine_endpoint_label_language(
        value="環境について",
        target_vocabulary="future-authority",
        publisher_language_tag=None,
    ) == ("ja", "scriptRule:hiragana-or-katakana-without-Latin")
    assert lc.determine_endpoint_label_language(
        value="環境政策",
        target_vocabulary="future-authority",
        publisher_language_tag=None,
    ) == (None, None)
    assert lc.determine_endpoint_label_language(
        value="Environmental policy",
        target_vocabulary="future-authority",
        publisher_language_tag=None,
    ) == ("en", "fallbackRule:ASCII-with-Latin-letters-plausibly-English")
    assert lc.determine_endpoint_label_language(
        value="環境 policy",
        target_vocabulary="future-authority",
        publisher_language_tag=None,
    ) == (None, None)
    assert lc.determine_endpoint_label_language(
        value="политика",
        target_vocabulary="future-authority",
        publisher_language_tag=None,
    ) == (None, None)


def test_reader_refuses_an_unhandled_lc_external_authority_predicate() -> None:
    statements = (
        (
            b"<http://id.loc.gov/authorities/subjects/sh00000001> "
            b"<http://www.loc.gov/mads/rdf/v1#hasReciprocalExternalAuthority> "
            b"<http://id.worldcat.org/fast/1> .\n"
        ),
    )

    with pytest.raises(lc.LcExternalLinksError, match="unsupported LCSH external-authority"):
        lc.parse_lc_external_links_statements(statements)


def test_reader_refuses_an_unknown_target_vocabulary() -> None:
    statements = (
        (
            b"<http://id.loc.gov/authorities/subjects/sh00000001> "
            b"<http://www.loc.gov/mads/rdf/v1#hasCloseExternalAuthority> "
            b"<https://example.org/not-declared/1> .\n"
        ),
    )

    with pytest.raises(lc.LcExternalLinksError, match="does not belong to one declared vocabulary"):
        lc.parse_lc_external_links_statements(statements)


def test_reader_refuses_duplicate_mapping_claims() -> None:
    statement = (
        b"<http://id.loc.gov/authorities/subjects/sh00000001> "
        b"<http://www.loc.gov/mads/rdf/v1#hasCloseExternalAuthority> "
        b"<http://id.worldcat.org/fast/1> .\n"
    )

    with pytest.raises(lc.LcExternalLinksError, match="repeats an LCSH mapping claim"):
        lc.parse_lc_external_links_statements((statement, statement))


def test_reader_refuses_unsupported_literal_escapes() -> None:
    statements = (
        (
            b"<http://id.loc.gov/authorities/subjects/sh00000001> "
            b"<http://www.loc.gov/mads/rdf/v1#hasCloseExternalAuthority> "
            b"<http://id.worldcat.org/fast/1> .\n"
        ),
        b'<http://id.worldcat.org/fast/1> <http://www.loc.gov/mads/rdf/v1#authoritativeLabel> "bad\\qescape" .\n',
    )

    with pytest.raises(lc.LcExternalLinksError, match="unsupported escape"):
        lc.parse_lc_external_links_statements(statements)


def test_archive_reader_refuses_digest_and_length_drift(tmp_path: Path) -> None:
    drifted = tmp_path / lc.LC_EXTERNAL_LINKS_FILENAME
    drifted.write_bytes(b"not the pinned archive")

    with pytest.raises(lc.LcExternalLinksError, match="archive pin differs"):
        lc.load_lc_external_links_capture(drifted)


@pytest.fixture(scope="module")
def real_capture() -> lc.LcExternalLinksCapture:
    if not SOURCE.is_file():
        pytest.skip("pinned LC external-links archive is not cached")
    return lc.load_lc_external_links_capture(SOURCE)


@pytest.mark.slow
def test_real_archive_pins_all_target_vocabulary_and_predicate_counts(
    real_capture: lc.LcExternalLinksCapture,
) -> None:
    assert len(real_capture.assertions) == lc.EXPECTED_ASSERTION_COUNT
    assert len(real_capture.lcsh_subject_iris) == lc.EXPECTED_UNIQUE_LCSH_SUBJECT_COUNT
    assert real_capture.assertion_counts_by_vocabulary == dict(lc.EXPECTED_ASSERTION_COUNTS_BY_VOCABULARY)
    assert real_capture.assertion_counts_by_publisher_predicate == dict(
        lc.EXPECTED_ASSERTION_COUNTS_BY_PUBLISHER_PREDICATE
    )


@pytest.mark.slow
def test_real_archive_captures_and_deterministically_tags_every_external_label(
    real_capture: lc.LcExternalLinksCapture,
) -> None:
    assert len(real_capture.target_iris) == 792_134
    assert len(real_capture.endpoint_labels) == 792_134
    assert sum(len(labels) for labels in real_capture.endpoint_labels.values()) == 792_166
    assert sum(len(labels) > 1 for labels in real_capture.endpoint_labels.values()) == 32
    assert real_capture.unlabeled_target_count == 0
    assert real_capture.explicitly_english_target_count == 0
    assert real_capture.determined_language_label_counts == dict(
        lc.EXPECTED_DETERMINED_LANGUAGE_LABEL_COUNTS
    )
    assert real_capture.determined_language_target_counts == dict(
        lc.EXPECTED_DETERMINED_LANGUAGE_TARGET_COUNTS
    )
    assert real_capture.indeterminate_label_count == 0


def test_source_pin_and_rights_metadata_are_complete() -> None:
    assert lc.LC_EXTERNAL_LINKS_URL == "https://id.loc.gov/download/externallinks.nt.zip"
    assert lc.LC_EXTERNAL_LINKS_RETRIEVED_AT == "2026-08-15T22:49:53Z"
    assert lc.LC_EXTERNAL_LINKS_SHA256 == ("sha256:7d279d69c6920b41a579634a84a1b31ff73af764345fe51df3f7c480efeba9d1")
    assert lc.LC_EXTERNAL_LINKS_BYTE_LENGTH == 239_565_667
    assert lc.LC_LICENSE == "CC0 1.0 Universal"
    assert lc.LC_RIGHTS_STATEMENT_URL == (
        "https://www.loc.gov/legal/security-copyright-and-privacy/understanding-copyright/"
    )
    assert lc.LC_RIGHTS_STATEMENT
