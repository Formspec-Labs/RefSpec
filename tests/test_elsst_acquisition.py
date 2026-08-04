"""Local-only tests for explicit, content-addressed ELSST acquisition."""

from __future__ import annotations

import hashlib
import importlib
import io
import os
from pathlib import Path

import pytest
from typing_extensions import Self

from refspec.registry.adapters import elsst_acquisition as acquisition
from refspec.registry.infrastructure import pinned_acquisition


def _release(payload: bytes) -> acquisition.ElsstReleaseSource:
    return acquisition.ElsstReleaseSource(
        version="test",
        release_iri="https://example.test/elsst/test",
        concept_scheme_iri="https://example.test/elsst/test/",
        source_url="https://example.test/ELSST_TEST.ttl",
        expected_sha256="sha256:" + hashlib.sha256(payload).hexdigest(),
        expected_byte_length=len(payload),
        filename="ELSST_TEST.ttl",
    )


def test_pinned_release_metadata_records_exact_sources_and_non_gating_license() -> None:
    assert acquisition.ELSST_R6.expected_byte_length == 19_915_491
    assert (
        acquisition.ELSST_R6.expected_sha256
        == "sha256:c362aec545db916ecb67af0eb9b8b4cecac1cb2118a717b69d8e6dad5591aa95"
    )
    assert acquisition.ELSST_R6.license_iri == "https://creativecommons.org/licenses/by-sa/4.0/"
    assert acquisition.ELSST_R6.attribution.startswith("Consortium of European Social Science Data Archives")
    assert not hasattr(acquisition.ELSST_R6, "use_authorized")


def test_real_r6_source_is_verified_and_content_addressed(tmp_path: Path) -> None:
    source_path = os.environ.get("REFSPEC_ELSST_R6_PATH")
    if source_path is None:
        pytest.skip("real ELSST R6 source is not configured")

    acquired = acquisition.acquire_elsst_release(
        acquisition.ELSST_R6,
        tmp_path / "store",
        source_path=Path(source_path),
    )

    assert acquired.sha256 == acquisition.ELSST_R6.expected_sha256
    assert acquired.byte_length == acquisition.ELSST_R6.expected_byte_length
    assert acquired.path.read_bytes() == Path(source_path).read_bytes()

    direct = pinned_acquisition.acquire_pinned_source(
        acquisition.ELSST_R6,
        tmp_path / "infrastructure-store",
        labels=pinned_acquisition.PinnedAcquisitionLabels(
            source_label="ELSST audit source",
            cached_location="cached ELSST audit source",
            local_file_label="ELSST audit source file",
            not_cached_message="ELSST audit source is not cached",
            request_headers={"User-Agent": "RefSpec real-data audit/1"},
        ),
        source_path=Path(source_path),
    )
    assert direct.sha256 == acquisition.ELSST_R6.expected_sha256
    assert direct.byte_length == acquisition.ELSST_R6.expected_byte_length


def test_local_source_is_verified_then_cached_without_network(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = b"@prefix skos: <http://www.w3.org/2004/02/skos/core#> .\n"
    release = _release(payload)
    source_path = tmp_path / "source.ttl"
    source_path.write_bytes(payload)
    calls: list[object] = []

    def fail_if_called(*args: object, **kwargs: object) -> object:
        calls.append((args, kwargs))
        raise AssertionError("network access was not authorized")

    monkeypatch.setattr(pinned_acquisition.urllib.request, "urlopen", fail_if_called)
    store = tmp_path / "store"
    acquired = acquisition.acquire_elsst_release(
        release,
        store,
        source_path=source_path,
    )
    source_path.unlink()
    cached = acquisition.acquire_elsst_release(release, store)

    digest_hex = release.expected_sha256.removeprefix("sha256:")
    assert acquired.path == store / "sha256" / digest_hex / release.filename
    assert acquired.path.read_bytes() == payload
    assert acquired.acquisition_mode == "local"
    assert acquired.cache_hit is False
    assert acquired.local_source_path == source_path.resolve()
    assert cached.acquisition_mode == "cache"
    assert cached.cache_hit is True
    assert cached.sha256 == release.expected_sha256
    assert cached.byte_length == len(payload)
    assert calls == []


def test_cache_miss_requires_explicit_local_or_network_choice(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    release = _release(b"source")
    calls: list[object] = []

    def fail_if_called(*args: object, **kwargs: object) -> object:
        calls.append((args, kwargs))
        raise AssertionError("network access was not authorized")

    monkeypatch.setattr(pinned_acquisition.urllib.request, "urlopen", fail_if_called)
    with pytest.raises(acquisition.ElsstAcquisitionError, match="allow_network=True"):
        acquisition.acquire_elsst_release(release, tmp_path)
    assert calls == []


def test_explicit_network_path_can_be_exercised_without_real_network(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = b"exact source"
    release = _release(payload)

    class Response(io.BytesIO):
        def geturl(self) -> str:
            return release.source_url

        def __enter__(self) -> Self:
            return self

        def __exit__(self, *args: object) -> None:
            self.close()

    requests: list[object] = []

    def open_local(request: object, *, timeout: float) -> Response:
        requests.append((request, timeout))
        return Response(payload)

    monkeypatch.setattr(pinned_acquisition.urllib.request, "urlopen", open_local)
    acquired = acquisition.acquire_elsst_release(
        release,
        tmp_path,
        allow_network=True,
        timeout_seconds=5.0,
    )

    assert acquired.path.read_bytes() == payload
    assert acquired.acquisition_mode == "network"
    assert acquired.resolved_url == release.source_url
    assert len(requests) == 1


@pytest.mark.parametrize(
    ("payload", "release_payload", "message"),
    [
        (b"short", b"longer", "byte length mismatch"),
        (b"wrong!", b"right!", "digest mismatch"),
    ],
)
def test_local_source_must_match_both_size_and_digest(
    tmp_path: Path,
    payload: bytes,
    release_payload: bytes,
    message: str,
) -> None:
    source_path = tmp_path / "source.ttl"
    source_path.write_bytes(payload)
    release = _release(release_payload)

    with pytest.raises(acquisition.ElsstAcquisitionError, match=message):
        acquisition.acquire_elsst_release(
            release,
            tmp_path / "store",
            source_path=source_path,
        )

    assert not list((tmp_path / "store").rglob(release.filename))
    assert not list((tmp_path / "store").rglob(".acquire-*.tmp"))


def test_module_import_has_no_network_side_effect(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[object] = []

    def fail_if_called(*args: object, **kwargs: object) -> object:
        calls.append((args, kwargs))
        raise AssertionError("network access on module import")

    monkeypatch.setattr(pinned_acquisition.urllib.request, "urlopen", fail_if_called)
    importlib.reload(acquisition)
    assert calls == []
