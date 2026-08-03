"""Official OMB Circular A-11 fiscal code capture, parsing, and validation tests."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from refspec.registry import omb_a11_budget_codes as a11
from refspec.registry.controlled_identifier import ControlledIdentifier

FIXTURES = Path(__file__).parent / "fixtures" / "omb_a11_budget_codes"
FUNCTIONAL_FIXTURE = FIXTURES / "exhibit-79a-functional-classification-2025.txt"
OBJECT_FIXTURE = FIXTURES / "exhibit-83a-object-classification-2025.txt"
APPORTIONMENT_FIXTURE = FIXTURES / "section-120-13-apportionment-categories-2025.txt"


def _acquire(
    tmp_path: Path,
    pin: a11.OMBA11PageSnapshotPin,
    source_path: Path,
) -> a11.AcquiredOMBA11Page:
    return a11.acquire_omb_a11_page(pin, tmp_path, source_path=source_path)


def _portfolio(tmp_path: Path) -> a11.OMBA11ControlPortfolio:
    functional = a11.parse_omb_a11_functional_classification(
        _acquire(tmp_path, a11.OMB_A11_FUNCTIONAL_CLASSIFICATION_2025, FUNCTIONAL_FIXTURE)
    )
    objects = a11.parse_omb_a11_object_classification(
        _acquire(tmp_path, a11.OMB_A11_OBJECT_CLASSIFICATION_2025, OBJECT_FIXTURE)
    )
    apportionment = a11.parse_omb_a11_apportionment_categories(
        _acquire(tmp_path, a11.OMB_A11_APPORTIONMENT_CATEGORIES_2025, APPORTIONMENT_FIXTURE)
    )
    return a11.assemble_omb_a11_control_portfolio((functional, objects, apportionment))


def test_pinned_page_extracts_match_exact_official_capture_bytes() -> None:
    functional = FUNCTIONAL_FIXTURE.read_bytes()
    objects = OBJECT_FIXTURE.read_bytes()
    apportionment = APPORTIONMENT_FIXTURE.read_bytes()

    assert len(functional) == 3_635
    assert a11.sha256_digest(functional) == (
        "sha256:0a8f141ffbbd83b4d9de7e099249ff6eb4eed53c688b14afbde3e9a2f0e496bb"
    )
    assert len(objects) == 1_886
    assert a11.sha256_digest(objects) == ("sha256:3714b8b88982f87dc491061d316bc89dbc2151a97b3aa7b3add1726738b4b325")
    assert len(apportionment) == 3_377
    assert a11.sha256_digest(apportionment) == (
        "sha256:e0e4f4d718add1b21d5106f454e45e3c30a0a5896a964032b3dc249b1aeb871a"
    )


def test_local_capture_is_content_addressed_and_rechecked_on_cache_hit(
    tmp_path: Path,
) -> None:
    pin = a11.OMB_A11_FUNCTIONAL_CLASSIFICATION_2025

    acquired = _acquire(tmp_path, pin, FUNCTIONAL_FIXTURE)
    cached = a11.acquire_omb_a11_page(pin, tmp_path)

    assert acquired.path == (tmp_path / "sha256" / pin.expected_sha256.removeprefix("sha256:") / pin.source.filename)
    assert acquired.acquisition_mode == "local"
    assert acquired.cache_hit is False
    assert cached.sha256 == pin.expected_sha256
    assert cached.acquisition_mode == "cache"
    assert cached.cache_hit is True


def test_injected_fetcher_is_the_only_live_transport_boundary(tmp_path: Path) -> None:
    payload = OBJECT_FIXTURE.read_bytes()
    calls: list[tuple[str, float]] = []

    class Fetcher:
        def fetch(
            self,
            document_url: str,
            *,
            timeout_seconds: float,
        ) -> a11.FetchedOMBA11Page:
            calls.append((document_url, timeout_seconds))
            return a11.FetchedOMBA11Page(
                body=payload,
                status_code=200,
                content_type="text/plain",
                resolved_url=document_url,
            )

    acquired = a11.acquire_omb_a11_page(
        a11.OMB_A11_OBJECT_CLASSIFICATION_2025,
        tmp_path,
        fetcher=Fetcher(),
        timeout_seconds=13.0,
    )

    assert calls == [(a11.OMB_A11_OBJECT_CLASSIFICATION_SOURCE.document_url, 13.0)]
    assert acquired.acquisition_mode == "fetcher"


def test_functional_classification_is_deterministic_metadata_not_a_subject_scheme(
    tmp_path: Path,
) -> None:
    resource = a11.parse_omb_a11_functional_classification(
        _acquire(tmp_path, a11.OMB_A11_FUNCTIONAL_CLASSIFICATION_2025, FUNCTIONAL_FIXTURE)
    )

    assert len(resource.codes) == 98
    assert resource.fiscal_year_edition == a11.OMB_A11_EDITION_2025
    majors = resource.by_code(kind="budgetFunctionCode")
    subs = resource.by_code(kind="budgetSubfunctionCode")
    assert len(majors) == 20
    assert len(subs) == 78
    assert majors["050"] == a11.OMBA11Code(
        resource_name="functionalClassification",
        use="deterministicMetadata",
        category="majorFunction",
        fiscal_year_edition=a11.OMB_A11_EDITION_2025,
        publisher_label="NATIONAL DEFENSE",
        source_url=a11.OMB_A11_DOCUMENT_URL,
        identifiers=(
            ControlledIdentifier(
                value="050",
                kind="budgetFunctionCode",
                authority_uri=a11.OMB_A11_IDENTIFIER_AUTHORITY_URI,
                source_uri=a11.OMB_A11_DOCUMENT_URL,
                observed_at=a11.OMB_A11_FUNCTIONAL_CLASSIFICATION_2025.retrieved_at,
                effective_at=None,
                source_digest=a11.OMB_A11_FUNCTIONAL_CLASSIFICATION_2025.expected_sha256,
            ),
        ),
    )
    assert subs["051"].publisher_label == "Department of Defense-Military"
    assert subs["921–929"].publisher_label == "Allowances [Assigned by OMB]"
    assert all(not code.is_general_subject_concept for code in resource.codes)


def test_object_classification_derives_the_publisher_stated_appendix_code(
    tmp_path: Path,
) -> None:
    resource = a11.parse_omb_a11_object_classification(
        _acquire(tmp_path, a11.OMB_A11_OBJECT_CLASSIFICATION_2025, OBJECT_FIXTURE)
    )

    assert len(resource.codes) == 38
    by_schedule = resource.by_code(kind="objectClassScheduleCode")
    by_appendix = resource.by_code(kind="objectClassAppendixCode")
    assert by_schedule["X111"] is by_appendix["11.1"]
    assert by_schedule["X111"].publisher_label == "Full-time permanent"
    assert by_schedule["X310"].publisher_label == "Equipment"
    assert by_appendix["31.0"].publisher_label == "Equipment"
    assert by_schedule["9999"].publisher_label == "Total new obligations, unexpired accounts"
    assert all(code.use == "deterministicMetadata" for code in resource.codes)
    assert all(not code.is_general_subject_concept for code in resource.codes)


def test_apportionment_categories_capture_line_ranges_and_non_apportioned_lines(
    tmp_path: Path,
) -> None:
    resource = a11.parse_omb_a11_apportionment_categories(
        _acquire(tmp_path, a11.OMB_A11_APPORTIONMENT_CATEGORIES_2025, APPORTIONMENT_FIXTURE)
    )

    assert len(resource.codes) == 8
    categories = resource.by_code(kind="apportionmentCategoryCode")
    ranges = resource.by_code(kind="apportionmentLineRange")
    lines = resource.by_code(kind="apportionmentLineCode")
    assert set(categories) == {"A", "B", "AB", "C"}
    assert ranges["6001-6004"].identifiers[0].value == "A"
    assert ranges["6011-6110"].identifiers[0].value == "B"
    assert ranges["6111-6159"].identifiers[0].value == "AB"
    assert ranges["6170-6173"].identifiers[0].value == "C"
    assert set(lines) == {"6180", "6181", "6182", "6183"}
    assert lines["6180"].publisher_label == "Withheld pending rescission (rarely used)"
    assert lines["6182"].publisher_label == "Unapportioned balance of a revolving fund"


def test_portfolio_requires_one_shared_fiscal_year_edition(tmp_path: Path) -> None:
    portfolio = _portfolio(tmp_path)

    assert portfolio.fiscal_year_edition == a11.OMB_A11_EDITION_2025
    assert any("never merges editions" in gap for gap in portfolio.gaps)

    functional = a11.parse_omb_a11_functional_classification(
        _acquire(tmp_path, a11.OMB_A11_FUNCTIONAL_CLASSIFICATION_2025, FUNCTIONAL_FIXTURE)
    )
    mismatched = replace(functional, fiscal_year_edition="OMB Circular No. A–11 (2026)")
    objects = a11.parse_omb_a11_object_classification(
        _acquire(tmp_path, a11.OMB_A11_OBJECT_CLASSIFICATION_2025, OBJECT_FIXTURE)
    )
    apportionment = a11.parse_omb_a11_apportionment_categories(
        _acquire(tmp_path, a11.OMB_A11_APPORTIONMENT_CATEGORIES_2025, APPORTIONMENT_FIXTURE)
    )
    with pytest.raises(a11.OMBA11SourceDriftError, match="different fiscal-year editions"):
        a11.assemble_omb_a11_control_portfolio((mismatched, objects, apportionment))


def test_current_fiscal_record_validates_without_becoming_a_subject(
    tmp_path: Path,
) -> None:
    portfolio = _portfolio(tmp_path)
    record = {
        "fiscal_year_edition": a11.OMB_A11_EDITION_2025,
        "budget_function_code": "050",
        "budget_subfunction_code": "051",
        "object_class_code": "11.1",
        "apportionment_category_code": "B",
    }

    validated = a11.validate_budget_fiscal_codes(record, portfolio)

    assert validated.fiscal_year_edition == a11.OMB_A11_EDITION_2025
    assert validated.budget_function.publisher_label == "NATIONAL DEFENSE"
    assert validated.budget_subfunction is not None
    assert validated.budget_subfunction.publisher_label == "Department of Defense-Military"
    assert validated.object_class.publisher_label == "Full-time permanent"
    assert validated.apportionment_category.publisher_label.startswith("Category B apportions")
    assert all(
        not assignment.is_general_subject_concept
        for assignment in (
            validated.budget_function,
            validated.budget_subfunction,
            validated.object_class,
            validated.apportionment_category,
        )
    )


def test_record_from_a_different_fiscal_year_edition_fails_closed(tmp_path: Path) -> None:
    portfolio = _portfolio(tmp_path)
    record = {
        "fiscal_year_edition": "OMB Circular No. A–11 (2026)",
        "budget_function_code": "050",
        "object_class_code": "11.1",
        "apportionment_category_code": "B",
    }

    with pytest.raises(a11.OMBA11AssignmentError, match="different fiscal years are different facts"):
        a11.validate_budget_fiscal_codes(record, portfolio)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("budget_function_code", "051", "unknown OMB A-11 budget_function_code"),
        ("budget_subfunction_code", "050", "unknown OMB A-11 budget_subfunction_code"),
        ("object_class_code", "77.7", "unknown OMB A-11 object_class_code"),
        ("apportionment_category_code", "D", "unknown OMB A-11 apportionment_category_code"),
    ],
)
def test_unknown_or_miskinded_fiscal_code_fails_closed(
    tmp_path: Path,
    field: str,
    value: str,
    message: str,
) -> None:
    portfolio = _portfolio(tmp_path)
    record = {
        "fiscal_year_edition": a11.OMB_A11_EDITION_2025,
        "budget_function_code": "050",
        "object_class_code": "11.1",
        "apportionment_category_code": "B",
        field: value,
    }

    with pytest.raises(a11.OMBA11AssignmentError, match=message):
        a11.validate_budget_fiscal_codes(record, portfolio)


def test_digest_or_edition_drift_never_becomes_a_parsed_resource(tmp_path: Path) -> None:
    payload = FUNCTIONAL_FIXTURE.read_bytes()
    changed = payload.replace(b"NATIONAL DEFENSE", b"NATIONAL DEFENCE")
    assert len(changed) == len(payload)

    class ChangedFetcher:
        def fetch(
            self,
            document_url: str,
            *,
            timeout_seconds: float,
        ) -> a11.FetchedOMBA11Page:
            del timeout_seconds
            return a11.FetchedOMBA11Page(
                body=changed,
                status_code=200,
                content_type="text/plain",
                resolved_url=document_url,
            )

    with pytest.raises(a11.OMBA11SourceDriftError, match="digest drift"):
        a11.acquire_omb_a11_page(
            a11.OMB_A11_FUNCTIONAL_CLASSIFICATION_2025,
            tmp_path,
            fetcher=ChangedFetcher(),
        )

    stale_edition_payload = payload.replace(b"(2025)", b"(2024)")
    stale_pin = replace(
        a11.OMB_A11_FUNCTIONAL_CLASSIFICATION_2025,
        expected_sha256=a11.sha256_digest(stale_edition_payload),
        expected_byte_length=len(stale_edition_payload),
    )
    stale_path = tmp_path / "stale-edition.txt"
    stale_path.write_bytes(stale_edition_payload)
    with pytest.raises(a11.OMBA11SourceDriftError, match="edition drift"):
        a11.acquire_omb_a11_page(stale_pin, tmp_path / "stale-store", source_path=stale_path)


def test_object_classification_rejects_an_unrecognized_trailer_row(
    tmp_path: Path,
) -> None:
    payload = (
        b"X111 Full-time permanent\n"
        b"X990 Subtotal, obligations *\n"
        b"Garbled trailer text\n"
        b"OMB Circular No. A\xe2\x80\x9311 (2025)\n"
    )
    mini_source = replace(a11.OMB_A11_OBJECT_CLASSIFICATION_SOURCE, expected_code_count=2)
    mini_pin = a11.OMBA11PageSnapshotPin(
        source=mini_source,
        retrieved_at=a11.OMB_A11_DOCUMENT_RETRIEVED_AT,
        edition=a11.OMB_A11_EDITION_2025,
        expected_sha256=a11.sha256_digest(payload),
        expected_byte_length=len(payload),
    )
    mini_path = tmp_path / "mini-object-classification.txt"
    mini_path.write_bytes(payload)
    acquired = a11.acquire_omb_a11_page(mini_pin, tmp_path / "store", source_path=mini_path)

    with pytest.raises(a11.OMBA11SourceDriftError, match="unexpected Exhibit 83A content"):
        a11.parse_omb_a11_object_classification(acquired)
