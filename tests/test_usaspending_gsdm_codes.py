"""USAspending award/assistance type capture and GSDM crosswalk pin tests."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from refspec.registry import usaspending_gsdm_codes as usg
from refspec.registry.controlled_identifier import ControlledIdentifier

FIXTURES = Path(__file__).parent / "fixtures" / "usaspending_gsdm_codes"
AWARD_TYPES_FIXTURE = FIXTURES / "usaspending-award-types-2026-08-03.json"


def _acquire(tmp_path: Path, source_path: Path = AWARD_TYPES_FIXTURE) -> usg.AcquiredUSASpendingSource:
    return usg.acquire_usaspending_award_types(
        usg.USASPENDING_AWARD_TYPES_2026_08_03,
        tmp_path,
        source_path=source_path,
    )


def _portfolio(tmp_path: Path) -> usg.USASpendingGSDMPortfolio:
    award_types = usg.parse_award_types(_acquire(tmp_path))
    return usg.assemble_usaspending_gsdm_portfolio(award_types)


def test_live_snapshot_pin_matches_exact_official_json_bytes() -> None:
    payload = AWARD_TYPES_FIXTURE.read_bytes()

    assert len(payload) == 1_271
    assert usg.sha256_digest(payload) == "sha256:682269b46e0cf200c7002ca7d55ba3da3de8dc345958d579ec98e579fc6782e7"
    assert usg.USASPENDING_AWARD_TYPES_2026_08_03.expected_byte_length == len(payload)
    assert usg.USASPENDING_AWARD_TYPES_2026_08_03.expected_sha256 == usg.sha256_digest(payload)


def test_local_capture_is_content_addressed_and_rechecked_on_cache_hit(tmp_path: Path) -> None:
    pin = usg.USASPENDING_AWARD_TYPES_2026_08_03

    acquired = _acquire(tmp_path)
    cached = usg.acquire_usaspending_award_types(pin, tmp_path)

    assert acquired.path == (tmp_path / "sha256" / pin.expected_sha256.removeprefix("sha256:") / pin.source.filename)
    assert acquired.acquisition_mode == "local"
    assert acquired.cache_hit is False
    assert cached.sha256 == pin.expected_sha256
    assert cached.acquisition_mode == "cache"
    assert cached.cache_hit is True


def test_injected_fetcher_is_the_only_live_transport_boundary(tmp_path: Path) -> None:
    payload = AWARD_TYPES_FIXTURE.read_bytes()
    calls: list[tuple[str, float]] = []

    class Fetcher:
        def fetch(self, source_url: str, *, timeout_seconds: float) -> usg.FetchedUSASpendingResponse:
            calls.append((source_url, timeout_seconds))
            return usg.FetchedUSASpendingResponse(
                body=payload,
                status_code=200,
                content_type="application/json",
                resolved_url=source_url,
            )

    acquired = usg.acquire_usaspending_award_types(
        usg.USASPENDING_AWARD_TYPES_2026_08_03,
        tmp_path,
        fetcher=Fetcher(),
        timeout_seconds=13.0,
    )

    assert calls == [(usg.USASPENDING_AWARD_TYPES.source_url, 13.0)]
    assert acquired.acquisition_mode == "fetcher"


def test_award_types_split_into_award_and_assistance_categories(tmp_path: Path) -> None:
    resource = usg.parse_award_types(_acquire(tmp_path))

    assert len(resource.codes) == 33
    by_code = resource.by_code()
    assert by_code["A"] == usg.USASpendingCode(
        resource_name="awardTypes",
        category="contracts",
        use="deterministicMetadata",
        publisher_label="BPA Call",
        source_url=usg.USASPENDING_AWARD_TYPES.source_url,
        identifiers=(
            ControlledIdentifier(
                value="A",
                kind="awardTypeCode",
                authority_uri=usg.USASPENDING_IDENTIFIER_AUTHORITY_URI,
                source_uri=usg.USASPENDING_AWARD_TYPES.source_url,
                observed_at="2026-08-03T19:25:21Z",
                effective_at=None,
                source_digest=usg.USASPENDING_AWARD_TYPES_2026_08_03.expected_sha256,
            ),
        ),
        is_general_subject_concept=False,
    )
    assert by_code["IDV_A"].category == "idvs"
    assert by_code["IDV_A"].identifiers[0].kind == "awardTypeCode"
    assert by_code["02"].category == "grants"
    assert by_code["02"].identifiers[0].kind == "assistanceTypeCode"
    assert by_code["02"].publisher_label == "Block Grant"
    assert by_code["-1"].category == "other_financial_assistance"
    assert all(not code.is_general_subject_concept for code in resource.codes)
    assert all(code.use == "deterministicMetadata" for code in resource.codes)
    # loans "07" and "F003" both publish "Direct Loan": duplicate labels are a
    # real feature of this source and must not be rejected.
    assert by_code["07"].publisher_label == by_code["F003"].publisher_label == "Direct Loan"


def test_digest_or_shape_drift_never_becomes_a_parsed_resource(tmp_path: Path) -> None:
    payload = AWARD_TYPES_FIXTURE.read_bytes()
    changed = payload.replace(b'"BPA Call"', b'"BPA Calls"') + b" "
    assert len(changed) != len(payload)

    class ChangedFetcher:
        def fetch(self, source_url: str, *, timeout_seconds: float) -> usg.FetchedUSASpendingResponse:
            del timeout_seconds
            return usg.FetchedUSASpendingResponse(
                body=changed,
                status_code=200,
                content_type="application/json",
                resolved_url=source_url,
            )

    with pytest.raises(usg.USASpendingSourceDriftError, match="byte length drift"):
        usg.acquire_usaspending_award_types(
            usg.USASPENDING_AWARD_TYPES_2026_08_03,
            tmp_path,
            fetcher=ChangedFetcher(),
        )

    mini_payload = b'{"contracts":{"A":"BPA Call"}}'
    mini_pin = usg.USASpendingSnapshotPin(
        source=usg.USASPENDING_AWARD_TYPES,
        retrieved_at="2026-08-03T19:25:21Z",
        expected_sha256=usg.sha256_digest(mini_payload),
        expected_byte_length=len(mini_payload),
    )
    mini_path = tmp_path / "mini.json"
    mini_path.write_bytes(mini_payload)
    acquired = usg.acquire_usaspending_award_types(
        mini_pin,
        tmp_path / "shape",
        source_path=mini_path,
    )
    with pytest.raises(usg.USASpendingSourceDriftError, match="categories drifted"):
        usg.parse_award_types(acquired)


def test_award_type_source_url_and_filename_are_validated() -> None:
    with pytest.raises(usg.USASpendingAcquisitionError, match="official HTTPS api.usaspending.gov"):
        replace(usg.USASPENDING_AWARD_TYPES, source_url="https://example.com/references/award_types/")
    with pytest.raises(usg.USASpendingAcquisitionError, match="one plain path component"):
        replace(usg.USASPENDING_AWARD_TYPES, filename="../escape.json")
    with pytest.raises(usg.USASpendingAcquisitionError, match="sha256:<64 hex>"):
        replace(usg.USASPENDING_AWARD_TYPES_2026_08_03, expected_sha256="not-a-digest")
    with pytest.raises(usg.USASpendingAcquisitionError, match="must be positive"):
        replace(usg.USASPENDING_AWARD_TYPES_2026_08_03, expected_byte_length=0)


def test_gsdm_document_is_pinned_to_the_reviewed_v1_0_1_release() -> None:
    assert usg.GSDM_DOCUMENT.version == "1.0.1"
    assert usg.GSDM_DOCUMENT.former_name == "DATA Act Information Model Schema (DAIMS)"
    assert usg.GSDM_DOCUMENT.revision_date == "2024-04-11"
    assert usg.GSDM_DOCUMENT.document_url == (
        "https://fiscal.treasury.gov/files/data-transparency/gsdm-architecture-v1.0.1.pdf"
    )
    assert usg.GSDM_DOCUMENT.expected_sha256 == (
        "sha256:6901ce4004e3338e54a69abb59d81205680d63f25e8dca0f9a92815dff6ced9d"
    )
    assert usg.GSDM_DOCUMENT.expected_byte_length == 363_340
    assert "Enumerations/Domain Value" in usg.GSDM_DOCUMENT.metadata_registry_attributes
    assert len(usg.GSDM_DOCUMENT.metadata_registry_attributes) == 11


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("version", "1.0", "dotted major.minor.patch"),
        ("document_url", "http://fiscal.treasury.gov/x.pdf", "HTTPS fiscal.treasury.gov"),
        ("document_url", "https://example.com/x.pdf", "HTTPS fiscal.treasury.gov"),
        ("expected_sha256", "sha256:zz", "sha256:<64 hex>"),
        ("expected_byte_length", 0, "must be positive"),
        ("revision_date", "04/11/2024", "ISO 8601 date"),
    ],
)
def test_gsdm_document_pin_fails_closed_on_malformed_fields(field: str, value: object, message: str) -> None:
    with pytest.raises(usg.USASpendingAcquisitionError, match=message):
        replace(usg.GSDM_DOCUMENT, **{field: value})


def test_gsdm_action_type_covers_assistance_and_contract_domains() -> None:
    element = usg.GSDM_SCHEMA_CROSSWALK_ELEMENTS[0]
    assert element.gsdm_element == "ActionType"

    assistance = element.by_code("assistance")
    contracts = element.by_code("contracts")
    assert len(assistance) == 5
    assert len(contracts) == 21
    assert assistance["A"].label == "New"
    assert contracts["A"].label == "ADDITIONAL WORK (NEW AGREEMENT, JUSTIFICATION REQUIRED)"
    # The same letter means something different in each domain; codes must
    # never be looked up without their domain_group.
    assert assistance["A"].label != contracts["A"].label
    assert element.fpds_data_dictionary_element == "Reason for Modification"
    assert element.award_category_fields == (
        usg.GSDMFileElement("Assistance", "action_type"),
        usg.GSDMFileElement("Contracts", "reasonformodification"),
    )


def test_gsdm_assistance_and_contract_award_type_domain_values_and_crosswalk() -> None:
    assistance_type = usg.GSDM_ASSISTANCE_TYPE
    contract_award_type = usg.GSDM_CONTRACT_AWARD_TYPE

    assert len(assistance_type.domain_values) == 10
    block_grant = assistance_type.by_code()["02"]
    assert block_grant.label == "block grant (A)"
    assert block_grant.code_description is not None
    assert block_grant.code_description.startswith("Federal funds provided to a state or local government")
    assert assistance_type.download_files == (
        usg.GSDMFileElement("Assistance_PrimeAwardSummaries.csv", "assistance_type_code"),
        usg.GSDMFileElement("Assistance_PrimeTransactions.csv", "assistance_type_code"),
    )
    assert assistance_type.account_files == (
        usg.GSDMFileElement("FA_AccountBreakdownByAward.csv", "award_type_code"),
        usg.GSDMFileElement("TAS_AccountBreakdownByAward.csv", "award_type_code"),
    )

    assert len(contract_award_type.domain_values) == 4
    bpa_call = contract_award_type.by_code()["A"]
    assert bpa_call.label == "BPA Call"
    assert bpa_call.code_description == "Enter this code for an award that is a call against a BPA."
    assert contract_award_type.submission_tables == (
        usg.GSDMFileElement("transaction_fpds", "contract_award_type"),
    )


def test_gsdm_crosswalk_element_rejects_duplicate_domain_codes() -> None:
    duplicated = usg.GSDM_ACTION_TYPE.domain_values[:1] * 2
    with pytest.raises(usg.USASpendingSourceDriftError, match="repeat a"):
        replace(usg.GSDM_ACTION_TYPE, domain_values=duplicated)


def test_portfolio_assembles_award_types_with_pinned_gsdm_crosswalk(tmp_path: Path) -> None:
    portfolio = _portfolio(tmp_path)

    assert len(portfolio.award_types.codes) == 33
    assert portfolio.schema_crosswalk_elements == usg.GSDM_SCHEMA_CROSSWALK_ELEMENTS
    assert portfolio.gsdm_document.version == "1.0.1"
    assert any("457 GSDM/DAIMS crosswalk" in gap for gap in portfolio.gaps)
    assert any("published twice with independent" in gap for gap in portfolio.gaps)
    assert any("reused across two unrelated domains" in gap for gap in portfolio.gaps)
    with pytest.raises(usg.USASpendingSourceDriftError, match="no pinned GSDM crosswalk element"):
        portfolio.crosswalk_element("IDVType")


def test_portfolio_digest_is_stable_and_content_derived(tmp_path: Path) -> None:
    first = usg.portfolio_digest(_portfolio(tmp_path))
    second = usg.portfolio_digest(_portfolio(tmp_path / "second"))

    assert first == second
    assert first.startswith("sha256:")
    assert len(first) == len("sha256:") + 64

    mutated = usg.assemble_usaspending_gsdm_portfolio(
        replace(_portfolio(tmp_path / "third").award_types, source_sha256="sha256:" + "0" * 64)
    )
    # source_sha256 alone is not part of the digest payload; mutating a code's
    # label is what should move the digest.
    assert usg.portfolio_digest(mutated) == first


def test_validate_usaspending_award_type_succeeds_and_fails_closed(tmp_path: Path) -> None:
    portfolio = _portfolio(tmp_path)

    assignment = usg.validate_usaspending_award_type({"type": "IDV_C"}, portfolio)
    assert assignment.publisher_label == "FSS Federal Supply Schedule"
    assert assignment.category == "idvs"
    assert assignment.use == "deterministicMetadata"
    assert assignment.is_general_subject_concept is False
    assert [identifier.value for identifier in assignment.identifiers] == ["IDV_C"]

    with pytest.raises(usg.USASpendingAssignmentError, match="unknown USAspending award/assistance type code"):
        usg.validate_usaspending_award_type({"type": "ZZZ"}, portfolio)
    with pytest.raises(usg.USASpendingAssignmentError, match="must carry a string"):
        usg.validate_usaspending_award_type({"type": None}, portfolio)
    with pytest.raises(usg.USASpendingAssignmentError, match="must carry a string"):
        usg.validate_usaspending_award_type({}, portfolio)


def test_validate_gsdm_action_type_requires_a_matching_domain(tmp_path: Path) -> None:
    portfolio = _portfolio(tmp_path)

    assistance_value = usg.validate_gsdm_action_type(
        {"action_type_code": "B"}, portfolio, domain="assistance"
    )
    assert assistance_value.label == "Continuation"

    contract_value = usg.validate_gsdm_action_type(
        {"action_type_code": "B"}, portfolio, domain="contracts"
    )
    assert contract_value.label == "SUPPLEMENTAL AGREEMENT FOR WORK WITHIN SCOPE"

    with pytest.raises(usg.USASpendingAssignmentError, match="unknown GSDM ActionType code"):
        usg.validate_gsdm_action_type({"action_type_code": "ZZ"}, portfolio, domain="assistance")
    with pytest.raises(usg.USASpendingAssignmentError, match="unsupported GSDM ActionType domain"):
        usg.validate_gsdm_action_type({"action_type_code": "A"}, portfolio, domain="grants")  # type: ignore[arg-type]
    with pytest.raises(usg.USASpendingAssignmentError, match="must carry a string"):
        usg.validate_gsdm_action_type({}, portfolio, domain="assistance")
