"""Exact source/evidence parity when the artifact owner publishes BILLSTATUS bytes.

Runs the frozen test-only oracle in _billstatus_acquisition_oracle beside the
production owner across local, fetcher, and cache modes, tolerating only the
three NAMED_DIVERGENCES.
"""

from __future__ import annotations

import os
from contextlib import contextmanager
from dataclasses import asdict, replace
from pathlib import Path
from types import ModuleType
from unittest.mock import Mock

import _billstatus_acquisition_oracle as old
import pytest

from refspec.registry import billstatus_codes as bs

FIXTURE = Path(__file__).parent / "fixtures/billstatus_codes/billstatus-xml-user-guide-2026-08-03.md"
PIN = bs.BILLSTATUS_USER_GUIDE_2026_08_03
# Sealed source/code identities stay unchanged. Existing named-file caches are
# deliberately not searched or converted, even if their bytes are still valid.
# Bounded reads report only observed bytes; owner publication adds its directory
# and changed-file refusal rules instead of the old pathname-only writes.
NAMED_DIVERGENCES = frozenset({"owner-blob-layout", "bounded-oversize-diagnostic", "owner-publication-refusals"})


class Fetcher:
    """Record fetch calls and return one fixed response."""

    def __init__(self, response: bs.FetchedBillStatusResponse) -> None:
        self.response = response
        self.calls: list[tuple[str, float]] = []

    def fetch(self, source_url: str, *, timeout_seconds: float) -> bs.FetchedBillStatusResponse:
        self.calls.append((source_url, timeout_seconds))
        return self.response


def response(payload: bytes | None = None, **changes: object) -> bs.FetchedBillStatusResponse:
    """Build a FetchedBillStatusResponse from the fixture, overriding named fields."""

    return replace(
        bs.FetchedBillStatusResponse(
            body=FIXTURE.read_bytes() if payload is None else payload,
            status_code=200,
            content_type="text/plain; charset=utf-8",
            resolved_url=PIN.source.source_url,
        ),
        **changes,
    )


def target(module: ModuleType, root: Path, pin: bs.BillStatusSnapshotPin = PIN) -> Path:
    """Return the store path for each implementation: old named-file layout vs owner blob layout."""

    digest = pin.expected_sha256.removeprefix("sha256:")
    if module is old:
        return root / "sha256" / digest / pin.source.filename
    return root / "objects" / "sha256" / digest


def evidence(acquired: bs.AcquiredBillStatusSource) -> dict[str, object]:
    """Serialize acquisition evidence minus ``path``, the one explicitly frozen layout divergence."""

    result = asdict(acquired)
    result.pop("path")  # The one explicitly frozen layout divergence.
    return result


@pytest.mark.parametrize("mode", ["local", "fetcher", "cache"])
def test_real_guide_evidence_and_all_code_resources_match_frozen_acquisition(tmp_path: Path, mode: str) -> None:
    """Pin equal evidence and code resources between owner and oracle in local, fetcher, and cache modes."""

    results = []
    portfolios = []
    for module in (old, bs):
        root = tmp_path / module.__name__
        fetcher = Fetcher(response())
        if mode == "cache":
            module.acquire_billstatus_source(PIN, root, source_path=FIXTURE)
            result = module.acquire_billstatus_source(PIN, root, fetcher=fetcher)
            assert fetcher.calls == []
        elif mode == "local":
            result = module.acquire_billstatus_source(PIN, root, source_path=FIXTURE)
        else:
            result = module.acquire_billstatus_source(PIN, root, fetcher=fetcher, timeout_seconds=13.0)
            assert fetcher.calls == [(PIN.source.source_url, 13.0)]
        assert result.path == target(module, root)
        assert result.path.read_bytes() == FIXTURE.read_bytes()
        results.append(evidence(result))
        portfolios.append(bs.parse_billstatus_code_sets(result))
    assert results[0] == results[1]
    assert portfolios[0] == portfolios[1]
    assert NAMED_DIVERGENCES == {"owner-blob-layout", "bounded-oversize-diagnostic", "owner-publication-refusals"}


@pytest.mark.parametrize("mode", ["local", "fetcher", "cache"])
@pytest.mark.parametrize("mutation", ["short", "long", "digest", "utf8"])
def test_source_mutations_preserve_drift_category_and_check_order(tmp_path: Path, mode: str, mutation: str) -> None:
    """Pin the drift category/message for short, long, digest, and UTF-8 mutations in every mode."""

    body = FIXTURE.read_bytes()
    pin = PIN
    if mutation == "utf8":
        body = b"\xff"
        pin = replace(PIN, expected_sha256=old.sha256_digest(body), expected_byte_length=len(body))
        message = "is not valid UTF-8 text"
    elif mutation == "short":
        body = body[:-1]
        message = "byte length drift"
    elif mutation == "long":
        body += b"x"
        message = "byte length drift"
    else:
        body = body.replace(b"Signed by President", b"Signed by Presidwnt")
        message = "digest drift"
    for module in (old, bs):
        root = tmp_path / module.__name__
        path = target(module, root, pin) if mode == "cache" else tmp_path / f"{module.__name__}.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(body)
        kwargs = {"source_path": path} if mode == "local" else {}
        if mode == "fetcher":
            kwargs = {"fetcher": Fetcher(response(body))}
        with pytest.raises(bs.BillStatusSourceDriftError, match=message):
            module.acquire_billstatus_source(pin, root, **kwargs)
        if mode != "cache":
            assert not target(module, root, pin).exists()
            assert not root.exists()  # Refuse the payload before creating storage.


@pytest.mark.parametrize("location", ["local", "cache"])
@pytest.mark.parametrize("kind", ["symlink", "directory", "missing"])
def test_local_and_cached_path_refusals_match_old(tmp_path: Path, location: str, kind: str) -> None:
    """Pin symlink/directory refusals and the "not cached" message for a missing cache path."""

    for module in (old, bs):
        root = tmp_path / module.__name__
        path = target(module, root) if location == "cache" else tmp_path / f"{module.__name__}.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        if kind == "symlink":
            path.symlink_to(FIXTURE.resolve())
        elif kind == "directory":
            path.mkdir()
        kwargs = {"source_path": path} if location == "local" else {}
        message = "not cached" if kind == "missing" and location == "cache" else "not a regular file"
        with pytest.raises(bs.BillStatusAcquisitionError, match=message):
            module.acquire_billstatus_source(PIN, root, **kwargs)


@pytest.mark.parametrize(
    ("changes", "error", "message"),
    [({"status_code": status}, bs.BillStatusAcquisitionError, f"HTTP {status}") for status in (201, 301, 401, 403, 404)]
    + [
        ({"resolved_url": "https://example.com/guide"}, bs.BillStatusAcquisitionError, "official HTTPS"),
        ({"resolved_url": "http://raw.githubusercontent.com/guide"}, bs.BillStatusAcquisitionError, "official HTTPS"),
        (
            {"resolved_url": "https://user:pass@raw.githubusercontent.com/guide"},
            bs.BillStatusAcquisitionError,
            "credentials",
        ),
        ({"content_type": "text/html"}, bs.BillStatusSourceDriftError, "content type"),
    ],
)
def test_injected_response_refusals_match_old(
    tmp_path: Path, changes: dict, error: type[Exception], message: str
) -> None:
    """Pin HTTP status, resolved-URL host/credential, and content-type refusals before any write."""

    for module in (old, bs):
        root = tmp_path / module.__name__
        fetcher = Fetcher(response(**changes))
        with pytest.raises(error, match=message):
            module.acquire_billstatus_source(PIN, root, fetcher=fetcher)
        assert fetcher.calls == [(PIN.source.source_url, 30.0)]
        assert not root.exists()


@pytest.mark.parametrize("media_type", ["text/plain", "TEXT/MARKDOWN ; charset=utf-8"])
def test_accepted_response_keeps_literal_media_and_resolved_url(tmp_path: Path, media_type: str) -> None:
    """Pin that accepted media type and resolved URL are recorded verbatim, not normalized."""

    results = []
    for module in (old, bs):
        fetcher = Fetcher(
            response(content_type=media_type, resolved_url="https://raw.githubusercontent.com/other/guide")
        )
        result = module.acquire_billstatus_source(PIN, tmp_path / module.__name__, fetcher=fetcher)
        assert result.content_type == media_type
        assert result.resolved_url == "https://raw.githubusercontent.com/other/guide"
        results.append(evidence(result))
    assert results[0] == results[1]


@pytest.mark.parametrize("cached", [False, True])
@pytest.mark.parametrize("invalid", ["both-inputs", "zero-timeout", "negative-timeout"])
def test_configuration_refused_before_cache_selection(tmp_path: Path, cached: bool, invalid: str) -> None:
    """Pin that invalid configuration is refused before a valid cache can short-circuit acquisition."""

    for module in (old, bs):
        root = tmp_path / module.__name__
        if cached:
            module.acquire_billstatus_source(PIN, root, source_path=FIXTURE)
        fetcher = Fetcher(response())
        kwargs = (
            {"source_path": FIXTURE, "fetcher": fetcher}
            if invalid == "both-inputs"
            else {
                "timeout_seconds": 0 if invalid == "zero-timeout" else -1,
            }
        )
        with pytest.raises(bs.BillStatusAcquisitionError):
            module.acquire_billstatus_source(PIN, root, **kwargs)
        assert fetcher.calls == []


def test_valid_cache_precedes_invalid_local_source(tmp_path: Path) -> None:
    """Pin that a valid cache hit answers even when the supplied source_path is missing."""

    for module in (old, bs):
        root = tmp_path / module.__name__
        module.acquire_billstatus_source(PIN, root, source_path=FIXTURE)
        result = module.acquire_billstatus_source(PIN, root, source_path=tmp_path / "absent.md")
        assert result.acquisition_mode == "cache"
        assert result.local_source_path is None
        assert result.resolved_url is None
        assert result.content_type == "text/plain"


@pytest.mark.parametrize("mutation", ["valid", "corrupt", "symlink"])
def test_publication_race_preserves_winner_evidence_or_refuses(tmp_path: Path, monkeypatch, mutation: str) -> None:
    """Pin that a lost hard-link race yields the winner's cache evidence or refuses a bad winner, with no staging left.
    """

    results = []
    for module in (old, bs):
        root = tmp_path / module.__name__
        final = target(module, root)

        def competing_link(*args: object, destination: Path = final, **kwargs: object) -> None:
            del args, kwargs
            if mutation == "symlink":
                destination.symlink_to(FIXTURE.resolve())
            else:
                body = FIXTURE.read_bytes()
                if mutation == "corrupt":
                    body = body.replace(b"Signed by President", b"Signed by Presidwnt")
                destination.write_bytes(body)
            raise FileExistsError("another publisher won")

        with monkeypatch.context() as patch:
            patch.setattr(os, "link", competing_link)
            if mutation == "valid":
                result = module.acquire_billstatus_source(PIN, root, fetcher=Fetcher(response()))
                results.append(evidence(result))
                assert result.acquisition_mode == "cache"
                assert result.content_type == "text/plain"
                assert result.resolved_url is None
            else:
                error = bs.BillStatusAcquisitionError if mutation == "symlink" else bs.BillStatusSourceDriftError
                with pytest.raises(error):
                    module.acquire_billstatus_source(PIN, root, fetcher=Fetcher(response()))
        assert not list(root.rglob(".acquire-*.tmp"))
        assert not list((root / ".pending").glob("*"))
    if results:
        assert results[0] == results[1]


@pytest.mark.parametrize("corrupt", [False, True])
def test_old_named_file_cache_is_untouched_and_never_read(tmp_path: Path, corrupt: bool) -> None:
    """Pin that the old named-file cache is never read or modified, even while the owner cache is filled."""

    old_path = target(old, tmp_path)
    old_path.parent.mkdir(parents=True)
    body = b"changed old capture" if corrupt else FIXTURE.read_bytes()
    old_path.write_bytes(body)
    with pytest.raises(bs.BillStatusAcquisitionError, match="not cached"):
        bs.acquire_billstatus_source(PIN, tmp_path)
    current = bs.acquire_billstatus_source(PIN, tmp_path, source_path=FIXTURE)
    assert current.acquisition_mode == "local"
    assert current.path == target(bs, tmp_path)
    assert old_path.read_bytes() == body
    assert old_path.parent.is_dir()


def test_owner_partial_write_failure_removes_staging_and_publishes_nothing(tmp_path: Path, monkeypatch) -> None:
    """Pin that a partial write failure empties the pending directory and publishes nothing."""

    original_write = os.write
    calls = 0

    def failed_write(fd: int, body: bytes) -> int:
        nonlocal calls
        calls += 1
        if calls == 1:
            return original_write(fd, body[:10])
        raise OSError("injected disk failure after partial write")

    monkeypatch.setattr(os, "write", failed_write)
    with pytest.raises(OSError, match="injected disk failure"):
        bs.acquire_billstatus_source(PIN, tmp_path, source_path=FIXTURE)
    assert calls == 2
    assert not target(bs, tmp_path).exists()
    assert list((tmp_path / ".pending").iterdir()) == []


def test_actual_atlas_caller_preserves_all_three_releases(tmp_path: Path, monkeypatch) -> None:
    """Pin the real Atlas caller's three BILLSTATUS releases under owner and old acquisition."""

    from refspec.atlas.v3_registry_codes import _load_billstatus

    repo_root = Path(__file__).resolve().parents[1]
    current = _load_billstatus(repo_root, tmp_path / "current")
    monkeypatch.setattr(bs, "acquire_billstatus_source", old.acquire_billstatus_source)
    prior = _load_billstatus(repo_root, tmp_path / "prior")
    assert current == prior
    assert [(row.key, len(row.resources), row.scope) for row in current] == [
        ("billstatus-bill-types", 8, "completeCapture"),
        ("billstatus-summary-version-codes", 88, "completeCapture"),
        ("billstatus-action-codes", 36, "captureSubset"),
    ]


@pytest.mark.parametrize("mode", ["local", "cache"])
def test_oversized_files_use_bounded_observation_and_never_read_the_tail(
    tmp_path: Path, monkeypatch, mode: str
) -> None:
    """Pin that an oversized file is refused after a bounded read of expected_length+1, never the tail."""

    observed = []
    body = FIXTURE.read_bytes() + b"unread tail" * 100
    for module in (old, bs):
        root = tmp_path / module.__name__
        path = target(module, root) if mode == "cache" else tmp_path / f"{module.__name__}.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(body)
        original_open = Path.open

        @contextmanager
        def tracked_open(selected, *args, selected_path=path, opener=original_open, **kwargs):
            with opener(selected, *args, **kwargs) as stream:
                if selected == selected_path:
                    proxy = Mock(wraps=stream)
                    yield proxy
                    observed.append(proxy.read.call_args.args)
                else:
                    yield stream

        kwargs = {"source_path": path} if mode == "local" else {}
        with monkeypatch.context() as patch:
            patch.setattr(Path, "open", tracked_open)
            count = len(body) if module is old else PIN.expected_byte_length + 1
            with pytest.raises(bs.BillStatusSourceDriftError, match=f"got {count}"):
                module.acquire_billstatus_source(PIN, root, **kwargs)
    assert observed == [(), (PIN.expected_byte_length + 1,)]


def test_owner_changed_target_refusal_survives_a_now_valid_reread(tmp_path: Path, monkeypatch) -> None:
    """Pin that a changed-target refusal keeps its BlobIntegrityError cause even when a reread would validate."""

    from rulespec_artifacts import BlobIntegrityError

    error = BlobIntegrityError("destination changed during immutable verification")

    def changed_target(_writer, *_args, **_kwargs):
        target(bs, tmp_path).write_bytes(FIXTURE.read_bytes())
        raise error

    monkeypatch.setattr(bs.LocalBlobWriter, "put", changed_target)
    with pytest.raises(bs.BillStatusAcquisitionError, match="could not be published safely") as caught:
        bs.acquire_billstatus_source(PIN, tmp_path, source_path=FIXTURE)
    assert caught.value.__cause__ is error
    assert target(bs, tmp_path).read_bytes() == FIXTURE.read_bytes()
    assert list((tmp_path / ".pending").iterdir()) == []


def test_owner_refuses_symlinked_store_root_that_the_old_writer_followed(tmp_path: Path) -> None:
    """Pin that the owner refuses a symlinked cache root the old writer followed, writing nothing through it."""

    for module in (old, bs):
        destination = tmp_path / f"{module.__name__}-destination"
        destination.mkdir()
        root = tmp_path / module.__name__
        root.symlink_to(destination, target_is_directory=True)
        if module is old:
            assert (
                module.acquire_billstatus_source(PIN, root, source_path=FIXTURE).path.read_bytes()
                == FIXTURE.read_bytes()
            )
        else:
            with pytest.raises(bs.BillStatusAcquisitionError, match="cache layout is unavailable"):
                module.acquire_billstatus_source(PIN, root, source_path=FIXTURE)
            assert list(destination.iterdir()) == []


def test_owner_refuses_non_directory_staging_layout_without_replacing_it(tmp_path: Path) -> None:
    """Pin that a file sitting at .pending is preserved and refused rather than replaced."""

    sentinel = tmp_path / ".pending"
    sentinel.write_bytes(b"keep existing file")
    with pytest.raises(bs.BillStatusAcquisitionError, match="cache layout is unavailable"):
        bs.acquire_billstatus_source(PIN, tmp_path, source_path=FIXTURE)
    assert sentinel.read_bytes() == b"keep existing file"
    assert not target(bs, tmp_path).exists()
