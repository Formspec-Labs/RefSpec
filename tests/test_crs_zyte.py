"""Tests for the Zyte implementation of the CRS page-fetcher boundary."""

from __future__ import annotations

import base64
import io
import json
import os
from pathlib import Path

import pytest
from typing_extensions import Self

from refspec.registry.adapters import crs_zyte
from refspec.registry.infrastructure import zyte_transport


class _Response(io.BytesIO):
    def __enter__(self) -> Self:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()


def test_crs_fetcher_preserves_pinned_publisher_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_path = os.environ.get("REFSPEC_CRS_LEGISLATIVE_SUBJECTS_PATH")
    if source_path is None:
        pytest.skip("real CRS publisher response is not configured")
    source_url = "https://www.congress.gov/help/field-values/legislative-subject-terms"
    body = Path(source_path).read_bytes()

    def fake_urlopen(*args: object, **kwargs: object) -> _Response:
        return _Response(
            json.dumps(
                {
                    "url": source_url,
                    "statusCode": 200,
                    "httpResponseBody": base64.b64encode(body).decode(),
                    "httpResponseHeaders": [
                        {"name": "Content-Type", "value": "text/html; charset=utf-8"}
                    ],
                }
            ).encode()
        )

    monkeypatch.setattr(zyte_transport.urllib.request, "urlopen", fake_urlopen)
    fetched = crs_zyte.ZyteCRSPageFetcher(
        token="test-token",
        max_bytes=len(body) + 1,
    ).fetch(source_url, timeout_seconds=5.0)

    assert fetched.body == body
    assert fetched.resolved_url == source_url


def test_crs_fetcher_returns_real_content_type_and_exact_bytes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_url = "https://www.congress.gov/help/field-values/legislative-subject-terms"
    body = b"<!doctype html><html></html>"

    def fake_urlopen(*args: object, **kwargs: object) -> _Response:
        return _Response(
            json.dumps(
                {
                    "url": source_url,
                    "statusCode": 200,
                    "httpResponseBody": base64.b64encode(body).decode(),
                    "httpResponseHeaders": [
                        {
                            "name": "Content-Type",
                            "value": "text/html; charset=utf-8",
                        }
                    ],
                }
            ).encode()
        )

    monkeypatch.setattr(
        zyte_transport.urllib.request,
        "urlopen",
        fake_urlopen,
    )
    fetched = crs_zyte.ZyteCRSPageFetcher(
        token="test-token",
        max_bytes=1024,
    ).fetch(source_url, timeout_seconds=5.0)

    assert fetched.body == body
    assert fetched.content_type == "text/html; charset=utf-8"
    assert fetched.resolved_url == source_url
    assert fetched.status_code == 200


def test_crs_fetcher_requires_target_content_type(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_urlopen(*args: object, **kwargs: object) -> _Response:
        return _Response(
            json.dumps(
                {
                    "url": "https://www.congress.gov/help/field-values/policy-area",
                    "statusCode": 200,
                    "httpResponseBody": base64.b64encode(b"<html></html>").decode(),
                    "httpResponseHeaders": [],
                }
            ).encode()
        )

    monkeypatch.setattr(
        zyte_transport.urllib.request,
        "urlopen",
        fake_urlopen,
    )
    with pytest.raises(
        crs_zyte.CRSZyteError,
        match="omitted Content-Type",
    ):
        crs_zyte.ZyteCRSPageFetcher(token="test-token").fetch(
            "https://www.congress.gov/help/field-values/policy-area",
            timeout_seconds=5.0,
        )
