"""CFR List of Subjects assignment-capture tests.

Fixtures under tests/fixtures/cfr_list_of_subjects/ are constructed to match
the documented shape of an eCFR current-part page (a PART heading, a "List of
Subjects in {title} CFR Part {part}" box, and a "current as of" banner).  Live
`curl` access to www.ecfr.gov during authoring returned a bot-management
"Request Access" challenge page instead of the real page, so these bytes are
not a captured live sample -- the parser is strict so a real capture that
drifts from this shape fails loudly instead of silently.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path

import pytest

from refspec.registry import cfr_list_of_subjects as cfr

FIXTURES = Path(__file__).parent / "fixtures" / "cfr_list_of_subjects"


def _payload(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def _pin(
    source: cfr.CFRPartSource,
    payload: bytes,
    *,
    as_of_date: str = "2026-07-30",
    retrieved_at: str = "2026-07-30T13:15:00Z",
) -> cfr.CFRPartSnapshotPin:
    return cfr.CFRPartSnapshotPin(
        source=source,
        retrieved_at=retrieved_at,
        as_of_date=as_of_date,
        expected_sha256=cfr.sha256_digest(payload),
        expected_byte_length=len(payload),
    )


def _acquire_fixture(
    tmp_path: Path,
    source: cfr.CFRPartSource,
    fixture_name: str,
    **pin_kwargs: str,
) -> cfr.AcquiredCFRPage:
    path = FIXTURES / fixture_name
    return cfr.acquire_cfr_part_page(
        _pin(source, path.read_bytes(), **pin_kwargs),
        tmp_path,
        source_path=path,
    )


def test_source_constants_describe_title_and_part_provenance() -> None:
    source = cfr.CFR_LIST_OF_SUBJECTS_SOURCE_1_18
    assert source.cfr_title == 1
    assert source.cfr_part == "18"
    assert source.part_citation == "1 CFR Part 18"
    assert source.part_heading_marker == "PART 18"
    assert source.list_of_subjects_heading == "List of Subjects in 1 CFR Part 18"
    assert source.source_url == "https://www.ecfr.gov/current/title-1/chapter-I/subchapter-A/part-18"

    other = cfr.CFR_LIST_OF_SUBJECTS_SOURCE_40_52
    assert other.cfr_title == 40
    assert other.cfr_part == "52"
    assert other.part_citation == "40 CFR Part 52"
    assert other.list_of_subjects_heading == "List of Subjects in 40 CFR Part 52"


def test_source_url_must_be_official_ecfr_host() -> None:
    with pytest.raises(cfr.CFRAcquisitionError, match="official HTTPS eCFR"):
        replace(
            cfr.CFR_LIST_OF_SUBJECTS_SOURCE_1_18,
            source_url="https://not-ecfr.example.com/current/title-1/part-18",
        )


def test_local_capture_is_exact_and_content_addressed(tmp_path: Path) -> None:
    source = cfr.CFR_LIST_OF_SUBJECTS_SOURCE_1_18
    payload = _payload("title-1-part-18.html")
    pin = _pin(source, payload)

    acquired = cfr.acquire_cfr_part_page(pin, tmp_path, source_path=FIXTURES / "title-1-part-18.html")
    cached = cfr.acquire_cfr_part_page(pin, tmp_path)

    digest_hex = pin.expected_sha256.removeprefix("sha256:")
    assert acquired.path == tmp_path / "sha256" / digest_hex / source.filename
    assert acquired.path.read_bytes() == payload
    assert acquired.acquisition_mode == "local"
    assert acquired.cache_hit is False
    assert cached.sha256 == pin.expected_sha256
    assert cached.acquisition_mode == "cache"
    assert cached.cache_hit is True


def test_injected_fetcher_is_the_only_live_transport_boundary(tmp_path: Path) -> None:
    source = cfr.CFR_LIST_OF_SUBJECTS_SOURCE_1_18
    payload = _payload("title-1-part-18.html")
    calls: list[tuple[str, float]] = []

    class Fetcher:
        def fetch(self, source_url: str, *, timeout_seconds: float) -> cfr.FetchedCFRPage:
            calls.append((source_url, timeout_seconds))
            return cfr.FetchedCFRPage(
                body=payload,
                status_code=200,
                content_type="text/html; charset=UTF-8",
                resolved_url=source_url,
            )

    acquired = cfr.acquire_cfr_part_page(
        _pin(source, payload),
        tmp_path,
        fetcher=Fetcher(),
        timeout_seconds=17.0,
    )

    assert calls == [(source.source_url, 17.0)]
    assert acquired.acquisition_mode == "fetcher"
    assert acquired.content_type == "text/html; charset=UTF-8"


def test_initial_capture_establishes_pin_before_strict_reopen(tmp_path: Path) -> None:
    source = cfr.CFR_LIST_OF_SUBJECTS_SOURCE_1_18
    payload = _payload("title-1-part-18.html")

    class Fetcher:
        def fetch(self, source_url: str, *, timeout_seconds: float) -> cfr.FetchedCFRPage:
            assert timeout_seconds == 17.0
            return cfr.FetchedCFRPage(
                body=payload,
                status_code=200,
                content_type="text/html; charset=UTF-8",
                resolved_url=source_url,
            )

    captured = cfr.capture_initial_cfr_part_snapshot(
        source,
        tmp_path,
        retrieved_at="2026-07-30T13:15:00Z",
        as_of_date="2026-07-30",
        fetcher=Fetcher(),
        timeout_seconds=17.0,
    )
    reopened = cfr.acquire_cfr_part_page(captured.pin, tmp_path)

    assert captured.sha256 == cfr.sha256_digest(payload)
    assert captured.byte_length == len(payload)
    assert captured.path.read_bytes() == payload
    assert reopened.cache_hit is True
    assert reopened.pin == captured.pin


def test_challenge_page_never_publishes_source(tmp_path: Path) -> None:
    source = cfr.CFR_LIST_OF_SUBJECTS_SOURCE_1_18
    expected_payload = _payload("title-1-part-18.html")
    pin = _pin(source, expected_payload)

    # Reproduces the real bot-management markers observed from a live
    # `curl` request to www.ecfr.gov during authoring (redirected to a
    # "Federal Register :: Request Access" unblock page).
    challenge_body = (
        b"<!doctype html><html><head><title>Federal Register :: Request Access</title></head>"
        b"<body><button class='unblock-button' data-unblock-target='button'>Request Access</button>"
        b"<h3>IP Access Help</h3></body></html>"
    )

    class ChallengeFetcher:
        def fetch(self, source_url: str, *, timeout_seconds: float) -> cfr.FetchedCFRPage:
            del timeout_seconds
            return cfr.FetchedCFRPage(
                body=challenge_body,
                status_code=200,
                content_type="text/html",
                resolved_url=source_url,
            )

    with pytest.raises(cfr.CFRSourceDriftError, match="challenge page"):
        cfr.acquire_cfr_part_page(pin, tmp_path, fetcher=ChallengeFetcher())

    expected_path = tmp_path / "sha256" / pin.expected_sha256.removeprefix("sha256:") / source.filename
    assert not expected_path.exists()
    assert not list(tmp_path.rglob(".acquire-*.tmp"))


def test_digest_drift_never_publishes_source(tmp_path: Path) -> None:
    source = cfr.CFR_LIST_OF_SUBJECTS_SOURCE_1_18
    expected_payload = _payload("title-1-part-18.html")
    changed_payload = expected_payload.replace(b"Archives and records", b"Archives amd recoRds")
    assert len(changed_payload) == len(expected_payload)
    pin = _pin(source, expected_payload)

    class ChangedFetcher:
        def fetch(self, source_url: str, *, timeout_seconds: float) -> cfr.FetchedCFRPage:
            del timeout_seconds
            return cfr.FetchedCFRPage(
                body=changed_payload,
                status_code=200,
                content_type="text/html",
                resolved_url=source_url,
            )

    with pytest.raises(cfr.CFRSourceDriftError, match="digest drift"):
        cfr.acquire_cfr_part_page(pin, tmp_path, fetcher=ChangedFetcher())

    expected_path = tmp_path / "sha256" / pin.expected_sha256.removeprefix("sha256:") / source.filename
    assert not expected_path.exists()
    assert not list(tmp_path.rglob(".acquire-*.tmp"))


def test_parses_assignment_terms_without_minting_identity(tmp_path: Path) -> None:
    source = cfr.CFR_LIST_OF_SUBJECTS_SOURCE_1_18
    page = _acquire_fixture(tmp_path, source, "title-1-part-18.html")

    parsed = cfr.parse_cfr_list_of_subjects_page(page)

    assert parsed.source.part_citation == "1 CFR Part 18"
    assert parsed.as_of_date == "2026-07-30"
    assert parsed.role == "candidateRankingEvidence"
    assert [term.official_label for term in parsed.terms] == [
        "Archives and records",
        "Freedom of information",
        "Reporting and recordkeeping requirements",
    ]
    assert [term.source_ordinal for term in parsed.terms] == [1, 2, 3]
    assert all(term.identity_status == "publisherIdentifierAbsent" for term in parsed.terms)
    digest_hex = cfr.sha256_digest(_payload("title-1-part-18.html")).removeprefix("sha256:")
    assert parsed.terms[0].record_iri == (f"urn:ref:cfr-list-of-subjects-record:{digest_hex}:title-1:part-18:1")
    assert len({term.record_iri for term in parsed.terms}) == len(parsed.terms)
    assert parsed.duplicate_label_evidence == ()

    assert parsed.readiness.ready is False
    assert parsed.readiness.source_term_count == 3
    with pytest.raises(cfr.CFRPromotionError, match="candidate-ranking"):
        parsed.readiness.require_ready()


def test_repeated_source_labels_remain_distinct_capture_records(tmp_path: Path) -> None:
    source = cfr.CFR_LIST_OF_SUBJECTS_SOURCE_1_18
    page = _acquire_fixture(tmp_path, source, "title-1-part-18-duplicate.html")

    parsed = cfr.parse_cfr_list_of_subjects_page(page)

    repeated = tuple(term for term in parsed.terms if term.official_label == "Archives and records")
    assert len(repeated) == 2
    assert repeated[0].record_iri != repeated[1].record_iri
    assert [term.source_ordinal for term in repeated] == [1, 3]
    assert parsed.duplicate_label_evidence == (
        cfr.CFRDuplicateLabelEvidence(
            official_label="Archives and records",
            record_iris=(repeated[0].record_iri, repeated[1].record_iri),
            source_ordinals=(1, 3),
        ),
    )


def test_wrong_list_of_subjects_heading_fails_as_source_drift(tmp_path: Path) -> None:
    source = cfr.CFR_LIST_OF_SUBJECTS_SOURCE_1_18
    page = _acquire_fixture(tmp_path, source, "title-1-part-18-wrong-heading.html")

    with pytest.raises(cfr.CFRSourceDriftError, match="missing expected heading"):
        cfr.parse_cfr_list_of_subjects_page(page)


def test_list_of_subjects_heading_without_adjacent_list_fails_as_source_drift(
    tmp_path: Path,
) -> None:
    source = cfr.CFR_LIST_OF_SUBJECTS_SOURCE_1_18
    page = _acquire_fixture(tmp_path, source, "title-1-part-18-no-list.html")

    with pytest.raises(cfr.CFRSourceDriftError, match="immediately followed"):
        cfr.parse_cfr_list_of_subjects_page(page)


def test_missing_part_heading_marker_fails_as_source_drift(tmp_path: Path) -> None:
    source = cfr.CFR_LIST_OF_SUBJECTS_SOURCE_1_18
    original = _payload("title-1-part-18.html")
    mutated = original.replace(b"<h1>PART 18", b"<h1>XXXX 18")
    assert len(mutated) == len(original)
    pin = _pin(source, mutated)

    acquired = cfr.acquire_cfr_part_page(pin, tmp_path, source_path=None, fetcher=_StaticFetcher(mutated))

    with pytest.raises(cfr.CFRSourceDriftError, match="part heading marker"):
        cfr.parse_cfr_list_of_subjects_page(acquired)


class _StaticFetcher:
    def __init__(self, body: bytes) -> None:
        self._body = body

    def fetch(self, source_url: str, *, timeout_seconds: float) -> cfr.FetchedCFRPage:
        del timeout_seconds
        return cfr.FetchedCFRPage(
            body=self._body,
            status_code=200,
            content_type="text/html",
            resolved_url=source_url,
        )


def test_as_of_date_banner_mismatch_fails_as_source_drift(tmp_path: Path) -> None:
    source = cfr.CFR_LIST_OF_SUBJECTS_SOURCE_1_18
    payload = _payload("title-1-part-18.html")
    pin = _pin(source, payload, as_of_date="2026-08-01")

    acquired = cfr.acquire_cfr_part_page(pin, tmp_path, source_path=FIXTURES / "title-1-part-18.html")

    with pytest.raises(cfr.CFRSourceDriftError, match="current as of"):
        cfr.parse_cfr_list_of_subjects_page(acquired)


def test_second_title_and_part_produce_distinct_record_iris(tmp_path: Path) -> None:
    source = cfr.CFR_LIST_OF_SUBJECTS_SOURCE_40_52
    page = _acquire_fixture(tmp_path, source, "title-40-part-52.html")

    parsed = cfr.parse_cfr_list_of_subjects_page(page)

    assert parsed.source.part_citation == "40 CFR Part 52"
    assert [term.official_label for term in parsed.terms] == [
        "Environmental protection",
        "Air pollution control",
        "Incorporation by reference",
        "Intergovernmental relations",
        "Reporting and recordkeeping requirements",
    ]
    digest_hex = cfr.sha256_digest(_payload("title-40-part-52.html")).removeprefix("sha256:")
    assert parsed.terms[0].record_iri == (f"urn:ref:cfr-list-of-subjects-record:{digest_hex}:title-40:part-52:1")
    assert "title-1:part-18" not in parsed.terms[0].record_iri


def test_assignment_evidence_is_deterministic_canonical_json(tmp_path: Path) -> None:
    source = cfr.CFR_LIST_OF_SUBJECTS_SOURCE_1_18
    page = _acquire_fixture(tmp_path, source, "title-1-part-18.html")
    parsed = cfr.parse_cfr_list_of_subjects_page(page)

    first = cfr.cfr_list_of_subjects_assignment_evidence_bytes(parsed)
    second = cfr.cfr_list_of_subjects_assignment_evidence_bytes(parsed)

    assert first == second
    decoded = json.loads(first)
    assert decoded["conceptIdentityClaimed"] is False
    assert decoded["role"] == "candidateRankingEvidence"
    assert decoded["titlePartCitation"] == "1 CFR Part 18"
    assert decoded["termCount"] == 3
    assert [row["label"] for row in decoded["terms"]] == [
        "Archives and records",
        "Freedom of information",
        "Reporting and recordkeeping requirements",
    ]
    assert "conceptScheme" not in first.decode("utf-8")


def test_fixture_digest_is_derived_from_exact_bytes() -> None:
    payload = _payload("title-1-part-18.html")

    assert cfr.sha256_digest(payload) == "sha256:" + hashlib.sha256(payload).hexdigest()
