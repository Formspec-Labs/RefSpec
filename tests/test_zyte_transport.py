"""Provider-level tests shared by every Zyte-backed source adapter."""

from __future__ import annotations

import base64
import hashlib
import io
import json
import os
from pathlib import Path
from typing import Any

import pytest
from typing_extensions import Self

from refspec.registry.infrastructure import zyte_transport


class _Response(io.BytesIO):
    def __enter__(self) -> Self:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()


def _provider_response(
    body: bytes,
    *,
    headers: list[dict[str, str]],
    resolved_url: str = "https://example.test/final",
) -> _Response:
    return _Response(
        json.dumps(
            {
                "url": resolved_url,
                "statusCode": 200,
                "httpResponseBody": base64.b64encode(body).decode(),
                "httpResponseHeaders": headers,
            }
        ).encode()
    )


@pytest.mark.parametrize(
    ("environment_name", "target_url", "content_type", "expected_sha256"),
    [
        (
            "REFSPEC_CRS_LEGISLATIVE_SUBJECTS_PATH",
            "https://www.congress.gov/help/field-values/legislative-subject-terms",
            "text/html; charset=utf-8",
            "sha256:8b4964a8cea53d63bce0a029bac38a2bc260059883120bc36e1759a4b5e844d1",
        ),
        (
            "REFSPEC_ICPSR_INDEX_PAGE_A_PATH",
            "https://www.icpsr.umich.edu/web/ICPSR/thesaurus/10001?letter=a",
            "text/html; charset=utf-8",
            "sha256:804b57d463a2a6f87c4c732825a1dc33a659f85ee3f6ef51c108ff14d2703de4",
        ),
    ],
)
def test_generic_transport_preserves_pinned_real_publisher_bytes(
    monkeypatch: pytest.MonkeyPatch,
    environment_name: str,
    target_url: str,
    content_type: str,
    expected_sha256: str,
) -> None:
    source_path = os.environ.get(environment_name)
    if source_path is None:
        pytest.skip(f"real publisher capture is unavailable: {environment_name}")
    body = Path(source_path).read_bytes()

    def fake_urlopen(*args: object, **kwargs: object) -> _Response:
        return _provider_response(
            body,
            headers=[{"name": "Content-Type", "value": content_type}],
            resolved_url=target_url,
        )

    monkeypatch.setattr(zyte_transport.urllib.request, "urlopen", fake_urlopen)
    response = zyte_transport.ZyteHttpFetcher(token="test-token").fetch(
        target_url,
        timeout_seconds=30.0,
        max_bytes=len(body),
    )

    assert response.body == body
    assert response.requested_url == target_url
    assert response.resolved_url == target_url
    assert response.content_type == content_type
    assert "sha256:" + hashlib.sha256(response.body).hexdigest() == expected_sha256


def test_generic_transport_preserves_target_content_type(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[Any] = []

    def fake_urlopen(request: Any, *, timeout: float) -> _Response:
        seen.append((request, timeout))
        return _provider_response(
            b"<html></html>",
            headers=[
                {"name": "Cache-Control", "value": "max-age=60"},
                {
                    "name": "content-type",
                    "value": "text/html; charset=UTF-8",
                },
            ],
        )

    monkeypatch.setattr(
        zyte_transport.urllib.request,
        "urlopen",
        fake_urlopen,
    )
    response = zyte_transport.ZyteHttpFetcher(token="test-token").fetch(
        "https://example.test/source",
        timeout_seconds=7.0,
        max_bytes=1024,
    )

    assert response.content_type == "text/html; charset=UTF-8"
    assert response.body == b"<html></html>"
    assert response.resolved_url == "https://example.test/final"
    request, timeout = seen[0]
    assert timeout == 7.0
    assert json.loads(request.data) == {
        "httpResponseBody": True,
        "httpResponseHeaders": True,
        "url": "https://example.test/source",
    }


def test_generic_transport_enforces_decoded_target_bound(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_urlopen(*args: object, **kwargs: object) -> _Response:
        return _provider_response(
            b"five!",
            headers=[{"name": "Content-Type", "value": "text/plain"}],
        )

    monkeypatch.setattr(
        zyte_transport.urllib.request,
        "urlopen",
        fake_urlopen,
    )
    with pytest.raises(
        zyte_transport.ZyteTransportError,
        match="exceeds max_bytes=4",
    ):
        zyte_transport.ZyteHttpFetcher(token="test-token").fetch(
            "https://example.test/source",
            timeout_seconds=7.0,
            max_bytes=4,
        )


@pytest.mark.parametrize(
    "headers",
    [
        None,
        [
            {"name": "Content-Type", "value": "text/html"},
            {"name": "content-type", "value": "application/xhtml+xml"},
        ],
    ],
)
def test_generic_transport_rejects_missing_or_ambiguous_headers(
    monkeypatch: pytest.MonkeyPatch,
    headers: list[dict[str, str]] | None,
) -> None:
    def fake_urlopen(*args: object, **kwargs: object) -> _Response:
        value: dict[str, object] = {
            "url": "https://example.test/source",
            "statusCode": 200,
            "httpResponseBody": base64.b64encode(b"ok").decode(),
        }
        if headers is not None:
            value["httpResponseHeaders"] = headers
        return _Response(json.dumps(value).encode())

    monkeypatch.setattr(
        zyte_transport.urllib.request,
        "urlopen",
        fake_urlopen,
    )
    with pytest.raises(zyte_transport.ZyteTransportError):
        zyte_transport.ZyteHttpFetcher(token="test-token").fetch(
            "https://example.test/source",
            timeout_seconds=7.0,
            max_bytes=1024,
        )
