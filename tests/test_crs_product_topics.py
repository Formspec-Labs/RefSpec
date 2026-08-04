"""CRS Product Types and Product Topics source-foundation tests.

Congress.gov's CRS products help page documents a small, closed set of
product-type genres and states that topics are attached to one product
edition rather than published as a governed, enumerable thesaurus.  These
tests exercise byte-exact capture, strict structural parsing, and the
explicit refusal to mint concept identity or a topic vocabulary.
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import replace
from pathlib import Path

import pytest

from refspec.registry import crs_product_topics as crs

FIXTURES = Path(__file__).parent / "fixtures" / "crs_product_topics"


def _payload(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def _pin(source: crs.CRSProductsPageSource, payload: bytes) -> crs.CRSProductsPageSnapshotPin:
    return crs.CRSProductsPageSnapshotPin(
        source=source,
        retrieved_at="2026-08-03T12:00:00Z",
        expected_sha256=crs.sha256_digest(payload),
        expected_byte_length=len(payload),
    )


def _mini_source(**overrides: object) -> crs.CRSProductsPageSource:
    overrides.setdefault("expected_product_type_count", 3)
    overrides.setdefault("topics_heading", "CRS Product Topics")
    overrides.setdefault("topics_marker_phrase", "not published as a separate, versioned thesaurus")
    return replace(crs.CRS_PRODUCTS_PAGE, **overrides)  # type: ignore[arg-type]


def _acquire_fixture(
    tmp_path: Path,
    source: crs.CRSProductsPageSource,
    fixture_name: str,
) -> crs.AcquiredCRSProductsPage:
    path = FIXTURES / fixture_name
    return crs.acquire_crs_products_page(
        _pin(source, path.read_bytes()),
        tmp_path,
        source_path=path,
    )


def test_current_official_page_declares_expected_shape() -> None:
    source = crs.CRS_PRODUCTS_PAGE
    assert source.source_url == "https://www.congress.gov/help/crs-products"
    assert source.expected_heading == "Congressional Research Service (CRS) Products"
    assert source.product_types_heading == "CRS Product Types"
    assert source.expected_product_type_count == 7
    assert source.topics_heading == "Searching CRS products"
    assert source.topics_marker_phrase == "CRS Product Topic"


def test_real_publisher_page_shape_count_and_boundary_samples(tmp_path: Path) -> None:
    source_path_text = os.environ.get("REFSPEC_CRS_PRODUCTS_PATH")
    if source_path_text is None:
        pytest.skip("real Congress.gov CRS products page is not configured")
    source_path = Path(source_path_text)
    page = crs.acquire_crs_products_page(
        crs.CRSProductsPageSnapshotPin(
            source=crs.CRS_PRODUCTS_PAGE,
            retrieved_at="2026-08-03T00:00:00Z",
            expected_sha256="sha256:91c478b93fe4a3588c48bf065d999a5830111f63f9888001bd60cf748ba060cc",
            expected_byte_length=371_848,
        ),
        tmp_path,
        source_path=source_path,
    )
    parsed = crs.parse_crs_products_page(page)

    assert len(parsed.product_types) == 7
    assert parsed.product_types[0].official_label == "Reports"
    assert parsed.product_types[-1].official_label == "Appropriations Status Table"
    assert "filtered by CRS Product Topic" in parsed.topics_scope_note.text


def test_local_capture_is_exact_and_content_addressed(tmp_path: Path) -> None:
    payload = _payload("crs-products-mini.html")
    source = _mini_source()
    pin = _pin(source, payload)

    acquired = crs.acquire_crs_products_page(
        pin,
        tmp_path,
        source_path=FIXTURES / "crs-products-mini.html",
    )
    cached = crs.acquire_crs_products_page(pin, tmp_path)

    digest_hex = pin.expected_sha256.removeprefix("sha256:")
    assert acquired.path == tmp_path / "sha256" / digest_hex / source.filename
    assert acquired.path.read_bytes() == payload
    assert acquired.acquisition_mode == "local"
    assert acquired.cache_hit is False
    assert cached.sha256 == pin.expected_sha256
    assert cached.acquisition_mode == "cache"
    assert cached.cache_hit is True


def test_injected_fetcher_is_the_only_live_transport_boundary(tmp_path: Path) -> None:
    payload = _payload("crs-products-mini.html")
    source = _mini_source()
    calls: list[tuple[str, float]] = []

    class Fetcher:
        def fetch(
            self,
            source_url: str,
            *,
            timeout_seconds: float,
        ) -> crs.FetchedCRSProductsPage:
            calls.append((source_url, timeout_seconds))
            return crs.FetchedCRSProductsPage(
                body=payload,
                status_code=200,
                content_type="text/html; charset=UTF-8",
                resolved_url=source_url,
            )

    acquired = crs.acquire_crs_products_page(
        _pin(source, payload),
        tmp_path,
        fetcher=Fetcher(),
        timeout_seconds=17.0,
    )

    assert calls == [(source.source_url, 17.0)]
    assert acquired.acquisition_mode == "fetcher"
    assert acquired.content_type == "text/html; charset=UTF-8"


def test_challenge_page_never_publishes_source(tmp_path: Path) -> None:
    source = _mini_source()
    expected_payload = _payload("crs-products-mini.html")
    pin = _pin(source, expected_payload)

    class ChallengeFetcher:
        def fetch(
            self,
            source_url: str,
            *,
            timeout_seconds: float,
        ) -> crs.FetchedCRSProductsPage:
            del timeout_seconds
            return crs.FetchedCRSProductsPage(
                body=b"<!doctype html><html><title>Just a moment...</title><div class='cf-chl-widget'></div></html>",
                status_code=200,
                content_type="text/html",
                resolved_url=source_url,
            )

    with pytest.raises(crs.CRSProductSourceDriftError, match="challenge page"):
        crs.acquire_crs_products_page(pin, tmp_path, fetcher=ChallengeFetcher())

    expected_path = tmp_path / "sha256" / pin.expected_sha256.removeprefix("sha256:") / source.filename
    assert not expected_path.exists()
    assert not list(tmp_path.rglob(".acquire-*.tmp"))


def test_digest_drift_never_publishes_source(tmp_path: Path) -> None:
    expected_payload = _payload("crs-products-mini.html")
    changed_payload = expected_payload.replace(b"Legal Sidebar", b"Legal Sidebbr")
    assert len(changed_payload) == len(expected_payload)
    source = _mini_source()
    pin = _pin(source, expected_payload)

    class ChangedFetcher:
        def fetch(
            self,
            source_url: str,
            *,
            timeout_seconds: float,
        ) -> crs.FetchedCRSProductsPage:
            del timeout_seconds
            return crs.FetchedCRSProductsPage(
                body=changed_payload,
                status_code=200,
                content_type="text/html",
                resolved_url=source_url,
            )

    with pytest.raises(crs.CRSProductSourceDriftError, match="digest drift"):
        crs.acquire_crs_products_page(pin, tmp_path, fetcher=ChangedFetcher())

    expected_path = tmp_path / "sha256" / pin.expected_sha256.removeprefix("sha256:") / source.filename
    assert not expected_path.exists()
    assert not list(tmp_path.rglob(".acquire-*.tmp"))


def test_product_types_are_parsed_as_genre_metadata_without_minting_ids(
    tmp_path: Path,
) -> None:
    source = _mini_source()
    page = crs.parse_crs_products_page(_acquire_fixture(tmp_path, source, "crs-products-mini.html"))

    assert [product_type.official_label for product_type in page.product_types] == [
        "Report",
        "In Focus",
        "Legal Sidebar",
    ]
    assert all(product_type.role == "genreMetadata" for product_type in page.product_types)
    assert all(product_type.identifiers == () for product_type in page.product_types)
    assert all(product_type.identity_status == "publisherIdentifierAbsent" for product_type in page.product_types)
    assert page.product_types[0].description.startswith("A CRS Report provides in-depth research")
    assert [product_type.source_ordinal for product_type in page.product_types] == [1, 2, 3]
    assert len({product_type.record_iri for product_type in page.product_types}) == 3


def test_product_topics_scope_note_is_source_evidence_only(tmp_path: Path) -> None:
    source = _mini_source()
    page = crs.parse_crs_products_page(_acquire_fixture(tmp_path, source, "crs-products-mini.html"))

    assert page.topics_scope_note.role == "sourceEvidenceOnly"
    assert "specific product edition" in page.topics_scope_note.text
    assert "not published as a separate, versioned thesaurus" in page.topics_scope_note.text
    assert page.topics_scope_note.identity_status == "publisherIdentifierAbsent"


def test_structure_or_count_change_fails_as_source_drift(tmp_path: Path) -> None:
    source = _mini_source(expected_product_type_count=4)
    page = _acquire_fixture(tmp_path, source, "crs-products-mini.html")

    with pytest.raises(crs.CRSProductSourceDriftError, match="definition list or two-column table"):
        crs.parse_crs_products_page(page)


def test_missing_topics_marker_phrase_fails_as_source_drift(tmp_path: Path) -> None:
    payload = _payload("crs-products-mini.html").replace(
        b"are not published as a separate, versioned\n        thesaurus independent of the product.",
        b"may be revised at any time without further notice to the general\n        public reading this page.",
    )
    variant_path = tmp_path / "crs-products-variant.html"
    variant_path.write_bytes(payload)
    source = _mini_source()
    pin = _pin(source, payload)

    acquired = crs.acquire_crs_products_page(pin, tmp_path / "store", source_path=variant_path)

    with pytest.raises(crs.CRSProductSourceDriftError, match="scope-note marker phrase"):
        crs.parse_crs_products_page(acquired)


def test_assembled_resource_is_blocked_from_a_managed_release(tmp_path: Path) -> None:
    source = _mini_source()
    page = crs.parse_crs_products_page(_acquire_fixture(tmp_path, source, "crs-products-mini.html"))

    resource = crs.assemble_crs_product_topics(page)

    assert resource.readiness.ready is False
    assert any("governed" in blocker or "thesaurus" in blocker for blocker in resource.readiness.blockers)
    assert any("identifiers" in blocker for blocker in resource.readiness.blockers)
    with pytest.raises(crs.CRSProductIdentityError):
        resource.readiness.require_ready()


def test_product_edition_topic_assignment_preserves_labels_per_edition() -> None:
    assignment = crs.capture_product_edition_topic_assignment(
        product_number="R47654",
        edition_label="2026-01-05",
        topic_labels=["Appropriations", "Government Operations and Politics", "Appropriations"],
        source_url="https://crsreports.congress.gov/product/details?prodcode=R47654",
        retrieved_at="2026-08-03T12:00:00Z",
    )

    assert assignment.product_number == "R47654"
    assert assignment.edition_label == "2026-01-05"
    assert assignment.topic_labels == ("Appropriations", "Government Operations and Politics")
    assert assignment.role == "sourceEvidenceOnly"
    assert assignment.identity_status == "publisherIdentifierAbsent"

    other_edition = crs.capture_product_edition_topic_assignment(
        product_number="R47654",
        edition_label="2026-03-11",
        topic_labels=["Appropriations"],
        source_url="https://crsreports.congress.gov/product/details?prodcode=R47654",
        retrieved_at="2026-08-03T12:00:00Z",
    )
    assert other_edition.record_iri != assignment.record_iri


def test_product_edition_topic_assignment_rejects_missing_evidence() -> None:
    with pytest.raises(crs.CRSProductSourceDriftError, match="topic_labels"):
        crs.capture_product_edition_topic_assignment(
            product_number="R47654",
            edition_label="2026-01-05",
            topic_labels=[],
            source_url="https://crsreports.congress.gov/product/details?prodcode=R47654",
            retrieved_at="2026-08-03T12:00:00Z",
        )
    with pytest.raises(crs.CRSProductAcquisitionError, match="official HTTPS Congress.gov"):
        crs.capture_product_edition_topic_assignment(
            product_number="R47654",
            edition_label="2026-01-05",
            topic_labels=["Appropriations"],
            source_url="https://example.com/product/R47654",
            retrieved_at="2026-08-03T12:00:00Z",
        )
    with pytest.raises(crs.CRSProductAcquisitionError, match="credentials"):
        crs.capture_product_edition_topic_assignment(
            product_number="R47654",
            edition_label="2026-01-05",
            topic_labels=["Appropriations"],
            source_url="https://user:pass@crsreports.congress.gov/product/details?prodcode=R47654",
            retrieved_at="2026-08-03T12:00:00Z",
        )


def test_fixture_digest_is_derived_from_exact_bytes() -> None:
    payload = _payload("crs-products-mini.html")

    assert crs.sha256_digest(payload) == "sha256:" + hashlib.sha256(payload).hexdigest()
