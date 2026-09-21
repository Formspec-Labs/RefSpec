"""Frozen acquisition/archive checks from RefSpec 63947226; test-only oracle."""

import hashlib
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from refspec.registry.uslm import ExtractionError
from tools.build_usc_source_credits import CreditScan, scan_source_credits

BASE_URL = "https://uscode.house.gov/download/releasepoints/us/pl"


def _sha256(body):
    return hashlib.sha256(body).hexdigest()


@dataclass(frozen=True)
class SourceBytes:
    """The exact publisher payload an extraction ran against."""

    url: str
    zip_bytes: int
    zip_sha256: str
    member: str
    xml_bytes: int
    xml_sha256: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "url": self.url,
            "zipBytes": self.zip_bytes,
            "zipSha256": self.zip_sha256,
            "member": self.member,
            "xmlBytes": self.xml_bytes,
            "xmlSha256": self.xml_sha256,
        }


def fetch_title(title: str, release_point: str, cache: Path) -> tuple[bytes, SourceBytes]:
    """Return the title's USLM XML and a pin describing the bytes it came from.

    The zip is cached verbatim, and re-running against a cached file re-derives
    every digest from those bytes, so a corrupted or hand-edited cache cannot
    pass itself off as the publisher's payload.
    """
    url = f"{BASE_URL}/{release_point}/xml_usc{title}@{release_point.replace('/', '-')}.zip"
    cache.mkdir(parents=True, exist_ok=True)
    path = cache / f"xml_usc{title}.zip"
    if not path.exists():
        request = urllib.request.Request(url, headers={"User-Agent": "RefSpec-USLM-extractor/1.0"})
        # Fixed https host, built from the release point and a validated title code.
        with urllib.request.urlopen(request, timeout=180) as response:
            if response.status != 200:
                raise ExtractionError(f"title {title}: {url} returned HTTP {response.status}")
            path.write_bytes(response.read())

    payload = path.read_bytes()
    # The publisher redirects unknown titles to an HTML error page that arrives
    # with a success status, so "the request worked" is not evidence the bytes are
    # the corpus.  Check the payload itself.
    if not payload.startswith(b"PK"):
        raise ExtractionError(
            f"title {title}: {url} did not return a zip archive "
            f"({len(payload)} bytes beginning {payload[:16]!r}) — the title may be reserved or withdrawn"
        )
    with zipfile.ZipFile(path) as archive:
        members = [name for name in archive.namelist() if name.lower().endswith(".xml")]
        if len(members) != 1:
            raise ExtractionError(f"title {title}: expected exactly one XML member, found {members}")
        xml = archive.read(members[0])

    pin = SourceBytes(
        url=url,
        zip_bytes=len(payload),
        zip_sha256=_sha256(payload),
        member=members[0],
        xml_bytes=len(xml),
        xml_sha256=_sha256(xml),
    )
    return xml, pin


def scan_release_zip(archive: Path) -> tuple[CreditScan, list[tuple[str, str]]]:
    """Scan every title in a whole-Code release zip.

    Returns the merged scan and one ``(member, sha256)`` pair per title, sorted,
    so a receipt pins the bytes each count was read from rather than only the
    zip they arrived in.
    """
    scan = CreditScan()
    members: list[tuple[str, str]] = []
    with zipfile.ZipFile(archive) as bundle:
        for name in sorted(n for n in bundle.namelist() if n.endswith(".xml")):
            payload = bundle.read(name)
            members.append((name, f"sha256:{hashlib.sha256(payload).hexdigest()}"))
            scan = scan.merge(scan_source_credits(payload))
    return scan, members
