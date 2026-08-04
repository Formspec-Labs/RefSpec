"""Provider-level tests shared by every Zyte-backed source adapter."""

from __future__ import annotations

import base64
import io
import json
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
) -> _Response:
    return _Response(
        json.dumps(
            {
                "url": "https://example.test/final",
                "statusCode": 200,
                "httpResponseBody": base64.b64encode(body).decode(),
                "httpResponseHeaders": headers,
            }
        ).encode()
    )


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
