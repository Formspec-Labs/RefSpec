"""Federal Register topics adopted from the shared source reader: acceptance, capture and row identity.

The frozen ``federal_register_topics_oracle`` holds the replaced decoder's
verdicts; the shared reader must match them everywhere except its six named
stricter refusals (duplicate keys, BOM, UTF-16, byte/depth/node limits) and
must publish a capture only after a fully verified response.
"""

from __future__ import annotations

import copy
import io
import json
from dataclasses import asdict
from pathlib import Path
from unittest.mock import patch

import httpx
import pytest
from spicy_docs.sources.federal_register.topics import DEFAULT_MAX_BYTES
from spicy_docs.transport.credentials import CredentialRefusedError

from refspec.atlas import v3_registry_large as atlas
from refspec.registry import federal_register_topics_api as current
from refspec.registry.packages.federal_register_topics_package import FEDERAL_REGISTER_TOPICS_CAPTURE_EVENT
from tests import federal_register_topics_oracle as frozen

FIXTURES = Path(__file__).parent / "fixtures"
FULL = FIXTURES / "federal_register_topics_api/federal-register-topics-2026-08-03.json"
MINI = FIXTURES / "federal-register-topics-mini.json"


def _assert_same(payload: bytes) -> None:
    """Compare the shared parser with the frozen oracle, or require both to refuse."""

    try:
        expected = frozen.parse_federal_register_topics_api(payload)
    except (ValueError, UnicodeError):
        with pytest.raises(current.FederalRegisterTopicsError):
            current.parse_federal_register_topics_api(payload)
        return
    actual = current.parse_federal_register_topics_api(payload)
    assert asdict(actual) == asdict(expected)
    assert [row.native_payload() for row in actual.records] == [row.native_payload() for row in expected.records]
    assert [row.source_record_digest for row in actual.records] == [row.source_record_digest for row in expected.records]
    assert [row.source_locator for row in actual.records] == [row.source_locator for row in expected.records]
    assert actual.source_record_set_digest == expected.source_record_set_digest
    assert {key: [row.source_locator for row in rows] for key, rows in actual.slug_collisions().items()} == {
        key: [row.source_locator for row in rows] for key, rows in expected.slug_collisions().items()
    }


@pytest.mark.parametrize("path", [FULL, MINI], ids=lambda path: path.name)
def test_all_retained_rows_native_payloads_and_digests_match_frozen_oracle(path):
    """Every retained record's payload, digest, locator, set digest and slug collisions match the oracle."""

    _assert_same(path.read_bytes())


def test_shared_reader_version_changes_atlas_release_identity_only():
    """The v2 parser version changes only the Atlas release IRI; digests, resources and relations are unchanged."""

    release = atlas.load_federal_register_topics_release(FULL)
    old_snapshot = frozen.parse_federal_register_topics_api(FULL.read_bytes())
    with patch.object(current, "FEDERAL_REGISTER_TOPICS_PARSER_VERSION", frozen.FEDERAL_REGISTER_TOPICS_PARSER_VERSION):
        old_release = atlas._federal_register_release_from_snapshot(
            old_snapshot, release.inputs[0], issued=release.issued,
        )
    assert current.FEDERAL_REGISTER_TOPICS_PARSER_VERSION == "federal-register-topics-api-shared-reader-v2"
    assert release.atlas_release_iri != old_release.atlas_release_iri
    assert release.source_release_digest == old_release.source_release_digest
    assert release.metadata["sourceRecordSetDigest"] == old_snapshot.source_record_set_digest
    assert release.resources == old_release.resources
    assert release.relations == old_release.relations
    before, after = asdict(old_release), asdict(release)
    before.pop("atlas_release_iri")
    after.pop("atlas_release_iri")
    assert after == before


@pytest.mark.parametrize(
    "path,value",
    [
        (("results", "thesaurus", 0, "name"), " Name\n with  spaces "),
        (("results", "thesaurus", 0, "name"), ""),
        (("results", "thesaurus", 0, "name"), "  "),
        (("results", "thesaurus", 0, "slug"), ""),
        (("results", "thesaurus", 0, "slug"), None),
        (("results", "thesaurus", 0, "see"), [{"name": "Name", "slug": ""}]),
        (("results", "thesaurus", 0, "see"), [{"name": "", "slug": ""}]),
        (("results", "thesaurus", 0, "see"), [{"name": "Name", "slug": "slug", "unknown": 1}]),
        (("results", "thesaurus", 0, "see_also"), [{"name": "Name", "slug": "slug"}] * 2),
        (("results", "thesaurus", 0, "see_also"), [None]),
        (("results", "thesaurus", 0, "see_also"), "wrong"),
        (("results", "thesaurus", 0, "cfr_references"), [None, "text", [], {}, True, 1.25, -0.0, 9007199254740993]),
        (("results", "thesaurus", 0, "cfr_references"), [{"title": "not interpreted", "extra": [1.1, False]}]),
        (("results", "thesaurus", 0, "cfr_references"), None),
        (("results", "thesaurus", 0, "unknown"), []),
        (("results", "thesaurus", 0), None),
        (("results", "ad_hoc"), []),
        (("results", "new_collection"), []),
        (("meta", "count", "total"), 999),
        (("meta", "count", "total"), -1),
        (("meta", "count", "total"), 3.0),
        (("meta", "count", "total"), True),
        (("meta", "count", "extra"), 1),
        (("meta", "extra"), None),
        (("extra",), "unknown root field"),
    ],
)
def test_value_and_shape_mutations_match_frozen_verdict(path, value):
    """Twenty-five value and shape mutations accept or refuse exactly as the frozen decoder did."""

    raw = json.loads(MINI.read_bytes())
    parent = raw
    for key in path[:-1]:
        parent = parent[key]
    parent[path[-1]] = value
    _assert_same(json.dumps(raw, ensure_ascii=False).encode())


@pytest.mark.parametrize(
    "path",
    [("meta",), ("results",), ("meta", "count"), ("meta", "count", "total"),
     ("results", "ad_hoc"), *(("results", "thesaurus", 0, key) for key in
                               ("name", "slug", "see", "see_also", "cfr_references"))],
)
def test_missing_fields_match_frozen_refusals(path):
    """Deleting each required field refuses exactly where the frozen decoder refused."""

    raw = json.loads(MINI.read_bytes())
    parent = raw
    for key in path[:-1]:
        parent = parent[key]
    del parent[path[-1]]
    _assert_same(json.dumps(raw).encode())


def test_duplicate_slugs_and_reordered_collections_preserve_capture_identity():
    """Duplicate slugs and a reordered collection keep capture identity equal to the oracle."""

    raw = json.loads(MINI.read_bytes())
    raw["results"]["thesaurus"] = [copy.deepcopy(raw["results"]["thesaurus"][0])] * 2
    raw["results"] = {"ad_hoc": raw["results"]["ad_hoc"], "thesaurus": raw["results"]["thesaurus"]}
    raw["meta"]["count"] = {"thesaurus": 2, "ad_hoc": len(raw["results"]["ad_hoc"]), "total": 2 + len(raw["results"]["ad_hoc"])}
    _assert_same(json.dumps(raw).encode())


def test_empty_collections_with_zero_counts_are_an_accepted_observation():
    """Empty collections with zero counts are accepted, not treated as drift."""

    _assert_same(b'{"meta":{"count":{"thesaurus":0,"ad_hoc":0,"total":0}},"results":{"thesaurus":[],"ad_hoc":[]}}')


# The replaced decoder accepted these. The source reader intentionally refuses
# ambiguous object keys, non-UTF-8 input and inputs above its declared bounds.
INTENTIONAL_REFUSALS = ("duplicate-key", "utf8-bom", "utf16", "byte-limit", "depth-limit", "node-limit")


@pytest.mark.parametrize("mutation", INTENTIONAL_REFUSALS)
def test_named_stricter_source_refusals(mutation):
    """The six named stricter refusals: duplicate keys, UTF-8 BOM, UTF-16, byte, depth and node limits."""

    payload = MINI.read_bytes()
    raw = json.loads(payload)
    if mutation == "duplicate-key":
        payload = b'{"results":null,' + payload.lstrip()[1:]
    elif mutation == "utf8-bom":
        payload = b"\xef\xbb\xbf" + payload
    elif mutation == "utf16":
        payload = payload.decode().encode("utf-16")
    elif mutation == "byte-limit":
        payload += b" " * DEFAULT_MAX_BYTES
    else:
        nested = "value"
        if mutation == "depth-limit":
            for _ in range(70):
                nested = [nested]
        else:
            nested = [""] * 500_000
        raw["results"]["thesaurus"][0]["cfr_references"] = [nested]
        payload = json.dumps(raw).encode()
    frozen.parse_federal_register_topics_api(payload)
    with pytest.raises(current.FederalRegisterTopicsError):
        current.parse_federal_register_topics_api(payload)


@pytest.mark.parametrize("path", [FULL, MINI], ids=lambda path: path.name)
def test_network_capture_uses_shared_response_and_preserves_event_and_bytes(tmp_path, path):
    """One network response is parsed once and yields the same bytes, event, digest, URL and snapshot as the frozen
    capture."""

    payload = path.read_bytes()
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(200, stream=httpx.ByteStream(payload), headers={"content-type": "application/json"})

    with patch.object(current, "read_fr_topics", side_effect=AssertionError("network response was parsed twice")):
        captured = current.capture_federal_register_topics(
            tmp_path / "current", allow_network=True,
            fetch_event=FEDERAL_REGISTER_TOPICS_CAPTURE_EVENT, transport=httpx.MockTransport(respond),
        )
    response = io.BytesIO(payload)
    response.geturl = lambda: current.FEDERAL_REGISTER_TOPICS_API_URL
    with patch.object(frozen.urllib.request, "urlopen", return_value=response):
        previous = frozen.capture_federal_register_topics(
            tmp_path / "frozen", allow_network=True, fetch_event=FEDERAL_REGISTER_TOPICS_CAPTURE_EVENT,
        )
    assert len(requests) == 1
    assert captured.path.read_bytes() == previous.path.read_bytes() == payload
    assert captured.capture_event == previous.capture_event == FEDERAL_REGISTER_TOPICS_CAPTURE_EVENT
    assert captured.source_sha256 == previous.source_sha256
    assert captured.resolved_url == previous.resolved_url == current.FEDERAL_REGISTER_TOPICS_API_URL
    assert captured.acquisition_mode == previous.acquisition_mode == "network"
    assert asdict(captured.snapshot) == asdict(previous.snapshot)


@pytest.mark.parametrize(
    "status,body,headers,error",
    [(200, b"<html>challenge</html>", {"content-type": "text/html"}, current.FederalRegisterTopicsError),
     (200, b"{}", {"content-type": "application/json"}, current.FederalRegisterTopicsError),
     (200, MINI.read_bytes(), {"content-type": "text/html"}, current.FederalRegisterTopicsError),
     (302, b"redirect", {"location": "https://example.com/challenge"}, current.FederalRegisterTopicsError),
     (404, b"missing", {}, current.FederalRegisterTopicsError),
     (401, b"refused", {}, CredentialRefusedError),
     (403, b"refused", {}, CredentialRefusedError)],
)
def test_network_refusal_never_publishes_capture(tmp_path, status, body, headers, error):
    """A challenge, empty body, wrong content type, redirect, 404 or 401/403 publishes nothing; refusals keep the
    response bytes."""

    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(status, stream=httpx.ByteStream(body), headers=headers)

    store = tmp_path / "store"
    with pytest.raises(error) as caught:
        current.capture_federal_register_topics(store, allow_network=True, transport=httpx.MockTransport(respond))
    assert len(requests) == 1
    assert not store.exists()
    if status in (401, 403):
        assert caught.value.refused_response.response_bytes == body
        assert caught.value.refused_response.unavailable_reason == "access-refused"


def test_network_capture_still_requires_explicit_selection(tmp_path):
    """Capture refuses without ``allow_network`` even when a transport is supplied."""

    def unexpected(request):
        raise AssertionError("network was not selected")

    with pytest.raises(current.FederalRegisterTopicsError, match="allow_network"):
        current.capture_federal_register_topics(tmp_path, transport=httpx.MockTransport(unexpected))


def test_network_byte_budget_refuses_before_publication(tmp_path):
    """A stated content-length above the fixed byte bound refuses before the stream is consumed or published."""

    # Return a stated size above the receiver's fixed bound without allocating
    # a huge fixture. The shared capture checks it before consuming the stream.
    def oversized(request):
        return httpx.Response(
            200, stream=httpx.ByteStream(b"bounded"),
            headers={"content-length": str(DEFAULT_MAX_BYTES + 1)},
        )

    with pytest.raises(current.FederalRegisterTopicsError, match="byte bound"):
        current.capture_federal_register_topics(
            tmp_path / "store", allow_network=True, transport=httpx.MockTransport(oversized),
        )
    assert not (tmp_path / "store").exists()


@pytest.mark.parametrize("failure", ["503", "timeout"])
def test_network_request_budget_is_one_attempt_and_errors_stay_receiver_errors(tmp_path, failure):
    """An HTTP 503 or connect timeout makes one attempt, raises the receiver's error, and publishes nothing."""

    requests = []

    def respond(request):
        requests.append(request)
        if failure == "timeout":
            raise httpx.ConnectTimeout("unavailable", request=request)
        return httpx.Response(503, stream=httpx.ByteStream(b"unavailable"))

    with pytest.raises(current.FederalRegisterTopicsError):
        current.capture_federal_register_topics(
            tmp_path / "store", allow_network=True, transport=httpx.MockTransport(respond),
        )
    assert len(requests) == 1
    assert not (tmp_path / "store").exists()
