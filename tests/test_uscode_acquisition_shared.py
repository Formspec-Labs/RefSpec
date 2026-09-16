"""Old archive verdicts, named stricter admission and complete cache publication."""

import io
import json
import zipfile
from functools import partial
from pathlib import Path

import httpx
import pytest
import uscode_archive_oracle as old
from spicy_docs.transport.credentials import CredentialRefusedError
from usc_archive_fixtures import NS, archive, retain, title_xml

from refspec.registry import uscode_cache as cache
from tools import build_usc_source_credits as credits

REAL = (Path(__file__).parent / "fixtures/uscode-acquisition/xml_usc01@119-103.zip").read_bytes()
XML = title_xml(
    f'<uscDoc xmlns="{NS}"><section identifier="/us/usc/t26/s1"><heading>One</heading></section></uscDoc>'.encode()
)
VALID = archive(("usc26.xml", XML))


def verdict(call):
    try:
        call()
    except (cache.ExtractionError, ValueError, OSError, zipfile.BadZipFile):
        return False
    return True


def test_retained_publisher_title_has_exact_old_bytes_and_receipt(tmp_path):
    retain(tmp_path / "new", REAL, title="01", release="119-103")
    (tmp_path / "old").mkdir()
    (tmp_path / "old/xml_usc01.zip").write_bytes(REAL)
    after, after_pin = cache.fetch_title("01", "119/103", tmp_path / "new")
    before, before_pin = old.fetch_title("01", "119/103", tmp_path / "old")
    assert after == before and after_pin.as_dict() == before_pin.as_dict()


def test_old_and_shared_archive_verdicts_differ_only_for_frozen_identity_checks(tmp_path):
    mutations = {
        "valid": VALID,
        "html": b"<html>Error</html>",
        "truncated-zip": VALID[:-40],
        "two-xml": archive(("usc26.xml", XML), ("usc27.xml", XML)),
        "wrong-member-title": archive(("usc27.xml", XML)),
        "wrong-native-title": archive(("usc26.xml", XML.replace(b"<docNumber>26", b"<docNumber>27"))),
        "wrong-native-release": archive(("usc26.xml", XML.replace(b"Online@119-102", b"Online@119-103"))),
        "malformed-xml": archive(("usc26.xml", XML[:-5])),
        "foreign-root": archive(("usc26.xml", XML.replace(NS.encode(), b"urn:foreign"))),
        "extra-sidecar": archive(("usc26.xml", XML), ("readme.txt", b"sidecar")),
    }
    differences = {}
    for name, payload in mutations.items():
        before, after = tmp_path / name / "old", tmp_path / name / "new"
        before.mkdir(parents=True)
        (before / "xml_usc26.zip").write_bytes(payload)
        retain(after, payload)
        a = verdict(partial(old.fetch_title, "26", "119/102", before))
        b = verdict(partial(cache.fetch_title, "26", "119/102", after))
        if a != b:
            differences[name] = (a, b)
    assert differences == {
        "wrong-member-title": (True, False),
        "wrong-native-title": (True, False),
        "wrong-native-release": (True, False),
        "malformed-xml": (True, False),
        "foreign-root": (True, False),
        "extra-sidecar": (True, False),
    }


def inject(monkeypatch, payload=VALID, status=200):
    requests = []

    def respond(request):
        requests.append(str(request.url))
        return httpx.Response(status, stream=httpx.ByteStream(payload))

    monkeypatch.setattr(cache, "UsCodeAcquirer", partial(cache.UsCodeAcquirer, transport=httpx.MockTransport(respond)))
    return requests


def test_fresh_capture_replays_without_http_and_old_flat_cache_is_untouched(tmp_path, monkeypatch):
    obsolete = tmp_path / "xml_usc26.zip"
    obsolete.write_bytes(b"old other edition")
    requests = inject(monkeypatch)
    first = cache.fetch_title("26", "119/102", tmp_path)
    evidence = tmp_path / "xml_usc26@119-102/capture.json"
    recorded = evidence.read_bytes()
    assert json.loads(recorded)["sha256"] == "sha256:" + first[1].zip_sha256
    assert cache.fetch_title("26", "119/102", tmp_path) == first
    assert len(requests) == 1 and evidence.read_bytes() == recorded
    assert obsolete.read_bytes() == b"old other edition"
    assert not list(tmp_path.glob(".usc-title-*"))


@pytest.mark.parametrize(
    "payload,status",
    [(b"<html>Error</html>", 200), (VALID, 403), (archive(("usc26.xml", XML.replace(b"119-102", b"119-103"))), 200)],
    ids=["html", "403", "wrong-edition"],
)
def test_refused_source_never_publishes_cache(tmp_path, monkeypatch, payload, status):
    requests = inject(monkeypatch, payload, status)
    with pytest.raises((cache.ExtractionError, CredentialRefusedError)):
        cache.fetch_title("26", "119/102", tmp_path)
    assert len(requests) == 1 and not list(tmp_path.iterdir())


@pytest.mark.parametrize(
    "change",
    [
        "missing",
        "oversized",
        "url",
        "digest",
        "time",
        "array",
        "invalid-json",
        "mime",
        "encoding",
        "method",
        "duplicate-key",
    ],
)
def test_incomplete_or_contradictory_capture_refuses_without_refetch(tmp_path, monkeypatch, change):
    destination = retain(tmp_path, VALID)
    path = destination / "capture.json"
    evidence = json.loads(path.read_text())
    if change == "missing":
        path.unlink()
    elif change == "oversized":
        path.write_bytes(b" " * 16_385)
    elif change == "array":
        path.write_text("[]")
    elif change == "invalid-json":
        path.write_text("{")
    elif change == "duplicate-key":
        path.write_text(path.read_text().replace("{", '{"statusCode": 403,', 1))
    else:
        evidence[
            {
                "url": "resolvedUrl",
                "digest": "sha256",
                "time": "observedAt",
                "mime": "contentType",
                "encoding": "contentEncoding",
                "method": "method",
            }[change]
        ] = ""
        if change == "mime":
            evidence["contentType"] = "text/html"
        path.write_text(json.dumps(evidence))
    requests = inject(monkeypatch)
    with pytest.raises((cache.ExtractionError, ValueError, OSError)):
        cache.fetch_title("26", "119/102", tmp_path)
    assert requests == []


def test_late_cache_publication_error_cleans_temporary_files(tmp_path, monkeypatch):
    inject(monkeypatch)
    original = cache.write_bytes_once

    def fail(path, payload):
        if path.name == "capture.json":
            raise OSError("disk full")
        original(path, payload)

    monkeypatch.setattr(cache, "write_bytes_once", fail)
    with pytest.raises(OSError, match="disk full"):
        cache.fetch_title("26", "119/102", tmp_path)
    assert not list(tmp_path.iterdir())


def test_competing_cache_publisher_preserves_winner_and_refuses_losing_capture(tmp_path, monkeypatch):
    from spicy_docs.storage.publication import ImmutablePublicationError

    requests = inject(monkeypatch)
    original = cache.publish_directory_once
    winning_xml = XML.replace(b">One<", b">Winner<")
    winning_zip = archive(("usc26.xml", winning_xml))
    saved = {}

    def compete(candidate, destination):
        retain(tmp_path, winning_zip)
        saved.update({path.name: path.read_bytes() for path in destination.iterdir()})
        original(candidate, destination)

    monkeypatch.setattr(cache, "publish_directory_once", compete)
    with pytest.raises(ImmutablePublicationError):
        cache.fetch_title("26", "119/102", tmp_path)
    destination = tmp_path / "xml_usc26@119-102"
    assert {path.name: path.read_bytes() for path in destination.iterdir()} == saved
    assert not list(tmp_path.glob(".usc-title-*"))
    assert cache.fetch_title("26", "119/102", tmp_path)[0] == winning_xml
    assert len(requests) == 1


def test_source_credit_scan_preserves_old_sorted_results_and_member_pins(tmp_path):
    with zipfile.ZipFile(io.BytesIO(REAL)) as bundle:
        real = bundle.read("usc01.xml").replace(b"Online@119-103", b"Online@119-102")
    path = tmp_path / "corpus.zip"
    path.write_bytes(archive(("usc26.xml", XML), ("usc01.xml", real)))
    assert credits.scan_release_zip(path, release_point="119-102") == old.scan_release_zip(path)


def test_corpus_verdict_changes_are_only_named_source_identity_and_shape_checks(tmp_path):
    mutations = {
        "valid": VALID,
        "malformed-xml": archive(("usc26.xml", XML[:-5])),
        "wrong-release": archive(("usc26.xml", XML.replace(b"119-102", b"119-103"))),
        "wrong-title": archive(("usc27.xml", XML)),
        "sidecar": archive(("usc26.xml", XML), ("other.txt", b"other")),
        "empty": archive(),
        "directory-only": archive(("empty/", b"")),
    }
    differences = {}
    for name, payload in mutations.items():
        path = tmp_path / f"{name}.zip"
        path.write_bytes(payload)
        before = verdict(partial(old.scan_release_zip, path))
        after = verdict(partial(credits.scan_release_zip, path, release_point="119-102"))
        if before != after:
            differences[name] = (before, after)
    assert differences == dict.fromkeys(
        ("wrong-release", "wrong-title", "sidecar", "empty", "directory-only"), (True, False)
    )


def test_two_cached_editions_do_not_share_bytes_or_observation_evidence(tmp_path):
    newer = archive(("usc26.xml", XML.replace(b"119-102", b"119-103")))
    retain(tmp_path, VALID)
    retain(tmp_path, newer, release="119-103")
    previous = cache.fetch_title("26", "119/102", tmp_path)
    current = cache.fetch_title("26", "119/103", tmp_path)
    assert previous[0] == XML
    assert current[0] == XML.replace(b"119-102", b"119-103")
    assert previous[1].zip_sha256 != current[1].zip_sha256


@pytest.mark.parametrize("mutation", ["wrong-release", "bad-late-title", "empty"])
def test_source_credit_build_refuses_before_creating_outputs(tmp_path, mutation):
    entries = [("usc26.xml", XML)]
    if mutation == "wrong-release":
        entries[0] = ("usc26.xml", XML.replace(b"119-102", b"119-103"))
    elif mutation == "bad-late-title":
        entries.append(("usc27.xml", b"<broken>"))
    else:
        entries = []
    path = tmp_path / "source.zip"
    path.write_bytes(archive(*entries))
    with pytest.raises(ValueError):
        credits.build(tmp_path / "output", archive=path, release_point="119-102")
    assert not (tmp_path / "output").exists()
