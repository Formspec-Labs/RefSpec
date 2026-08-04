"""Offline tests for ICPSR public identity acquisition and XML joins."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

import pytest

from refspec.registry import icpsr_subject as icpsr

FIXTURES = Path(__file__).parent / "fixtures"
ROBOTS = b"User-agent: *\nDisallow: /cgi-bin/\n"


def test_real_commit_pinned_xml_shape_count_and_boundary_samples() -> None:
    source_path_text = os.environ.get("REFSPEC_ICPSR_SUBJECT_XML_PATH")
    if source_path_text is None:
        pytest.skip("real ICPSR publisher repository capture is not configured")
    snapshot = icpsr.parse_icpsr_subject_xml(Path(source_path_text).read_bytes())

    assert snapshot.source_sha256 == icpsr.ICPSR_SUBJECT_XML_SHA256
    assert snapshot.source_byte_length == icpsr.ICPSR_SUBJECT_XML_BYTE_LENGTH
    assert len(snapshot.terms) == 3_765
    assert (snapshot.terms[0].source_local_record_number, snapshot.terms[0].label) == (
        "1",
        "abandoned buildings",
    )
    assert (snapshot.terms[-1].source_local_record_number, snapshot.terms[-1].label) == (
        "3765",
        "zip code areas",
    )


def _fixture_pages() -> dict[str, bytes]:
    return {letter: (FIXTURES / f"icpsr-subject-index-{letter}-mini.html").read_bytes() for letter in ("a", "s", "t")}


def _partial_index() -> icpsr.IcpsrSubjectIndex:
    return icpsr.build_icpsr_subject_index(
        _fixture_pages(),
        robots_body=ROBOTS,
        require_complete=False,
    )


def test_index_parser_uses_only_official_links_in_terms_section() -> None:
    page = icpsr.parse_icpsr_index_page(
        _fixture_pages()["a"],
        letter="a",
    )

    assert page.sha256 == ("sha256:" + hashlib.sha256(_fixture_pages()["a"]).hexdigest())
    assert [(term.code, term.label, term.preferred) for term in page.terms] == [
        ("24042", "ability", True),
        ("24043", "Abolition movement", True),
    ]
    assert page.terms[0].concept_iri == ("https://www.icpsr.umich.edu/web/ICPSR/thesaurus/10001/terms/24042")
    assert all(term.code != "99999" for term in page.terms)
    assert [(identifier.kind, identifier.value) for identifier in page.terms[0].identifiers] == [
        ("publisherCode", "24042"),
        (
            "publisherTermUri",
            "https://www.icpsr.umich.edu/web/ICPSR/thesaurus/10001/terms/24042",
        ),
    ]
    assert all(
        identifier.authority_uri == "https://www.icpsr.umich.edu/web/ICPSR/thesaurus/10001"
        and identifier.source_uri.endswith("?letter=a")
        and identifier.observed_at is None
        and identifier.effective_at is None
        and identifier.source_digest == page.sha256
        for identifier in page.terms[0].identifiers
    )


def test_capture_observation_time_is_threaded_into_every_identifier() -> None:
    observed_at = "2026-07-30T12:34:56Z"

    index = icpsr.build_icpsr_subject_index(
        _fixture_pages(),
        robots_body=ROBOTS,
        require_complete=False,
        observed_at=observed_at,
    )

    assert index.observed_at == observed_at
    assert all(identifier.observed_at == observed_at for term in index.terms for identifier in term.identifiers)


def test_capture_observation_time_must_be_an_iso_date_or_date_time() -> None:
    with pytest.raises(ValueError, match="ISO 8601"):
        icpsr.build_icpsr_subject_index(
            _fixture_pages(),
            robots_body=ROBOTS,
            require_complete=False,
            observed_at="July 30, 2026",
        )


def test_non_preferred_marker_is_role_not_part_of_label() -> None:
    page = icpsr.parse_icpsr_index_page(
        _fixture_pages()["t"],
        letter="t",
    )

    assert len(page.terms) == 1
    assert page.terms[0].label == "talent"
    assert page.terms[0].preferred is False


def test_xml_parser_preserves_authored_semantics_and_source_local_number() -> None:
    snapshot = icpsr.parse_icpsr_subject_xml((FIXTURES / "icpsr-subject-mini.xml").read_bytes())

    ability = next(term for term in snapshot.terms if term.label == "ability")
    abolition = next(term for term in snapshot.terms if term.label == "Abolition movement")
    assert ability.used_for_labels == ("talent",)
    assert ability.source_local_record_number == "3"
    assert abolition.scope_notes == ("Refers to the United States Abolition movement during the 1800s to end slavery.",)
    assert abolition.broader_labels == ("social movements",)
    assert abolition.related_labels == ("slavery",)
    assert abolition.input_timestamp == "2023-03-06 10:09:43.0"
    assert abolition.update_timestamp == "2023-03-06 10:09:43.0"


def test_xml_join_resolves_every_relation_to_source_published_iri() -> None:
    xml = icpsr.parse_icpsr_subject_xml((FIXTURES / "icpsr-subject-mini.xml").read_bytes())
    joined = icpsr.join_icpsr_xml_to_official_index(
        xml,
        _partial_index(),
        require_complete_index=False,
    )

    ability = next(term for term in joined.terms if term.identity.label == "ability")
    abolition = next(term for term in joined.terms if term.identity.label == "Abolition movement")
    assert ability.identity.code == "24042"
    assert ability.used_for[0].code == "27405"
    assert ability.used_for[0].preferred is False
    assert ability.source_local_record_number not in ability.identity.concept_iri
    assert abolition.broader[0].concept_iri.endswith("/terms/27251")
    assert abolition.related[0].concept_iri.endswith("/terms/27209")
    assert joined.index_only_terms == ()


def test_compatibility_report_exposes_drift_without_guessing_identity() -> None:
    xml = icpsr.parse_icpsr_subject_xml((FIXTURES / "icpsr-subject-mini.xml").read_bytes())
    pages = _fixture_pages()
    pages["a"] = pages["a"].replace(
        b">ability</a>",
        b">renamed ability</a>",
    )
    pages["s"] = pages["s"].replace(
        b"</h2>",
        b'</h2><a href="/web/ICPSR/thesaurus/10001/terms/29999">new index term</a>',
        1,
    )
    index = icpsr.build_icpsr_subject_index(
        pages,
        robots_body=ROBOTS,
        require_complete=False,
    )

    report = icpsr.compare_icpsr_xml_to_official_index(
        xml,
        index,
        require_complete_index=False,
    )

    assert report.compatible is False
    assert report.xml_term_count == 5
    assert report.index_term_count == 6
    assert report.matched_term_count == 4
    assert report.xml_only_labels == ("ability",)
    assert [term.label for term in report.index_only_terms] == [
        "new index term",
        "renamed ability",
    ]
    assert report.role_conflicts == ()


def test_join_fails_instead_of_deriving_identity_for_missing_label() -> None:
    xml_payload = (FIXTURES / "icpsr-subject-mini.xml").read_bytes()
    xml_payload = xml_payload.replace(
        b"<DESCRIPTOR>slavery</DESCRIPTOR>",
        b"<DESCRIPTOR>missing source term</DESCRIPTOR>",
    )
    xml = icpsr.parse_icpsr_subject_xml(xml_payload)

    with pytest.raises(
        icpsr.IcpsrSubjectError,
        match="lack an official public identity",
    ):
        icpsr.join_icpsr_xml_to_official_index(
            xml,
            _partial_index(),
            require_complete_index=False,
        )


def test_join_rejects_preferred_non_preferred_role_conflict() -> None:
    pages = _fixture_pages()
    pages["t"] = pages["t"].replace(b"talent*", b"talent")
    index = icpsr.build_icpsr_subject_index(
        pages,
        robots_body=ROBOTS,
        require_complete=False,
    )
    xml = icpsr.parse_icpsr_subject_xml((FIXTURES / "icpsr-subject-mini.xml").read_bytes())

    with pytest.raises(
        icpsr.IcpsrSubjectError,
        match="role mismatch",
    ):
        icpsr.join_icpsr_xml_to_official_index(
            xml,
            index,
            require_complete_index=False,
        )


def test_capture_digest_is_deterministic_and_capture_writes_exact_bytes(
    tmp_path: Path,
) -> None:
    first = icpsr.build_icpsr_subject_index(
        _fixture_pages(),
        robots_body=ROBOTS,
        require_complete=False,
    )
    reversed_pages = dict(reversed(list(_fixture_pages().items())))
    second = icpsr.build_icpsr_subject_index(
        reversed_pages,
        robots_body=ROBOTS,
        require_complete=False,
    )

    assert first.capture_digest == second.capture_digest
    manifest = icpsr.write_icpsr_subject_index_capture(first, tmp_path)
    assert manifest.read_bytes().endswith(b"\n")
    assert (tmp_path / "robots.txt").read_bytes() == ROBOTS
    assert (tmp_path / "pages" / "a.html").read_bytes() == _fixture_pages()["a"]
    assert icpsr.write_icpsr_subject_index_capture(first, tmp_path) == manifest


def test_acquisition_is_robots_checked_and_bounded_to_28_requests() -> None:
    calls: list[str] = []
    sleeps: list[float] = []

    def fake_fetch(
        url: str,
        *,
        timeout_seconds: float,
        max_bytes: int,
    ) -> icpsr.IcpsrFetchedPage:
        calls.append(url)
        if url == icpsr.ICPSR_ROBOTS_URL:
            body = ROBOTS
        else:
            letter = dict(item.split("=", 1) for item in url.split("?", 1)[1].split("&"))["letter"]
            letter = "#" if letter == "%23" else letter
            if letter == "#":
                body = b"<html><h2>Terms</h2></html>"
            else:
                ordinal = ord(letter) - ord("a") + 1
                body = (
                    '<html><h2>Terms</h2><a href="/web/ICPSR/'
                    f'thesaurus/10001/terms/{90000 + ordinal}">'
                    f"{letter} fixture</a></html>"
                ).encode()
        return icpsr.IcpsrFetchedPage(
            requested_url=url,
            resolved_url=url,
            status_code=200,
            content_type="text/html",
            body=body,
        )

    index = icpsr.acquire_icpsr_subject_index(
        fetch_page=fake_fetch,
        minimum_interval_seconds=0.25,
        sleep=sleeps.append,
    )

    assert index.complete is True
    assert len(index.terms) == 26
    assert len(calls) == 28
    assert calls[0] == icpsr.ICPSR_ROBOTS_URL
    assert sleeps == [0.25] * 27


def test_network_is_never_implicit() -> None:
    with pytest.raises(
        icpsr.IcpsrSubjectError,
        match="requires fetch_page",
    ):
        icpsr.acquire_icpsr_subject_index()


def test_pinned_xml_opener_rejects_unverified_bytes(tmp_path: Path) -> None:
    source = tmp_path / "subject.xml"
    source.write_bytes((FIXTURES / "icpsr-subject-mini.xml").read_bytes())

    with pytest.raises(icpsr.IcpsrSubjectError, match="byte length"):
        icpsr.open_pinned_icpsr_subject_xml(source)

    assert icpsr.ICPSR_SUBJECT_XML_BYTE_LENGTH == 1_244_558
    assert icpsr.ICPSR_SUBJECT_XML_SHA256 == ("sha256:1875e0331a8403c00fa47a3ededca98c902f55d0b84d70884543ed1d2db629ff")
