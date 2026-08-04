"""Tests for the secret-safe Zyte ICPSR acquisition transport."""

from __future__ import annotations

import base64
import io
import json
import urllib.error
from typing import Any

import pytest
from typing_extensions import Self

from refspec.registry.adapters import icpsr_zyte
from refspec.registry.infrastructure import zyte_transport


class _Response(io.BytesIO):
    def __enter__(self) -> Self:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()


def test_zyte_fetcher_posts_expected_request_without_exposing_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target_url = "https://www.icpsr.umich.edu/robots.txt"
    target_body = b"User-agent: *\n"
    seen: list[tuple[Any, float]] = []

    def fake_urlopen(request: Any, *, timeout: float) -> _Response:
        seen.append((request, timeout))
        provider_body = json.dumps(
            {
                "url": target_url,
                "statusCode": 200,
                "httpResponseHeaders": [{"name": "Content-Type", "value": "text/plain"}],
                "httpResponseBody": base64.b64encode(target_body).decode(),
            }
        ).encode()
        return _Response(provider_body)

    monkeypatch.setattr(
        zyte_transport.urllib.request,
        "urlopen",
        fake_urlopen,
    )
    fetcher = icpsr_zyte.ZyteIcpsrPageFetcher(token="test-token")
    page = fetcher(
        target_url,
        timeout_seconds=5.0,
        max_bytes=1024,
    )

    assert page.body == target_body
    assert page.status_code == 200
    assert len(seen) == 1
    request, timeout = seen[0]
    assert timeout == 5.0
    assert json.loads(request.data) == {
        "httpResponseBody": True,
        "httpResponseHeaders": True,
        "url": target_url,
    }
    assert base64.b64decode(request.get_header("Authorization").removeprefix("Basic ")) == b"test-token:"
    assert "test-token" not in repr(page)
    assert page.content_type == "text/plain"


def test_zyte_fetcher_reads_only_named_environment_variable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("ZYTE_TOKEN", raising=False)
    with pytest.raises(
        icpsr_zyte.IcpsrZyteError,
        match="ZYTE_TOKEN is required",
    ):
        icpsr_zyte.ZyteIcpsrPageFetcher.from_environment()

    monkeypatch.setenv("ZYTE_TOKEN", '"still-quoted"')
    with pytest.raises(
        icpsr_zyte.IcpsrZyteError,
        match="must not include dotenv quote",
    ):
        icpsr_zyte.ZyteIcpsrPageFetcher.from_environment()


def test_zyte_provider_error_does_not_include_body_or_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret = "do-not-print"
    provider_error = urllib.error.HTTPError(
        zyte_transport.ZYTE_API_URL,
        403,
        "provider says " + secret,
        {},
        io.BytesIO(("body " + secret).encode()),
    )

    def fail(*args: object, **kwargs: object) -> object:
        raise provider_error

    monkeypatch.setattr(zyte_transport.urllib.request, "urlopen", fail)
    fetcher = icpsr_zyte.ZyteIcpsrPageFetcher(token=secret)

    with pytest.raises(icpsr_zyte.IcpsrZyteError) as raised:
        fetcher(
            "https://www.icpsr.umich.edu/robots.txt",
            timeout_seconds=5.0,
            max_bytes=1024,
        )
    assert str(raised.value) == "Zyte acquisition failed with HTTP 403"
    assert secret not in str(raised.value)


@pytest.mark.parametrize(
    "provider_value",
    [
        {},
        {
            "httpResponseBody": "***",
            "httpResponseHeaders": [],
            "statusCode": 200,
        },
        {
            "httpResponseBody": base64.b64encode(b"ok").decode(),
            "httpResponseHeaders": [],
            "statusCode": "200",
        },
    ],
)
def test_zyte_malformed_responses_fail_explicitly(
    monkeypatch: pytest.MonkeyPatch,
    provider_value: dict[str, object],
) -> None:
    def fake_urlopen(*args: object, **kwargs: object) -> _Response:
        return _Response(json.dumps(provider_value).encode())

    monkeypatch.setattr(
        zyte_transport.urllib.request,
        "urlopen",
        fake_urlopen,
    )
    fetcher = icpsr_zyte.ZyteIcpsrPageFetcher(token="test-token")

    with pytest.raises(icpsr_zyte.IcpsrZyteError):
        fetcher(
            "https://www.icpsr.umich.edu/robots.txt",
            timeout_seconds=5.0,
            max_bytes=1024,
        )
