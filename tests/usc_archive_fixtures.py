"""Small synthetic captures for archive identity and retention checks."""

import hashlib
import io
import json
import re
import zipfile

NS = "http://xml.house.gov/schemas/uslm/1.0"

# Any <uscDoc ...> start tag, so retained titles whose root carries attributes
# first accept the same synthetic metadata as the minimal synthetic bodies.
_OPENED_USCDOC = re.compile(rb"<uscDoc\b[^>]*>")


def title_xml(body: bytes, title="26", release="119-102") -> bytes:
    """Inject native title metadata and a main wrapper into a synthetic uscDoc body."""
    metadata = (
        f'<meta xmlns:dc="http://purl.org/dc/elements/1.1/">'
        f"<dc:title>Title {title}</dc:title><dc:type>USCTitle</dc:type>"
        f"<docNumber>{title.lstrip('0')}</docNumber>"
        f"<docPublicationName>Online@{release}</docPublicationName></meta>"
    ).encode()
    opened = _OPENED_USCDOC.search(body)
    if opened is None:
        raise ValueError("title body has no <uscDoc> root to carry native metadata")
    end = opened.end()
    inner = body[end:]
    return (
        body[:end]
        + metadata
        + b"<main><heading>Synthetic title</heading>"
        + inner.replace(b"</uscDoc>", b"</main></uscDoc>")
    )


def archive(*entries):
    """Build an in-memory zip archive from (name, body) entries."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as bundle:
        for name, body in entries:
            bundle.writestr(name, body)
    return buffer.getvalue()


def retain(cache, payload, *, title="26", release="119-102"):
    """Write a synthetic complete capture without calling production retention."""
    name = f"xml_usc{title}@{release}"
    destination = cache / name
    destination.mkdir(parents=True, exist_ok=True)
    (destination / "archive.zip").write_bytes(payload)
    url = f"https://uscode.house.gov/download/releasepoints/us/pl/{release.replace('-', '/')}/{name}.zip"
    evidence = {
        "requestedUrl": url,
        "resolvedUrl": url,
        "statusCode": 200,
        "method": "GET",
        "byteSize": len(payload),
        "sha256": "sha256:" + hashlib.sha256(payload).hexdigest(),
        "observedAt": "2026-09-15T00:00:00Z",
        "contentType": None,
        "contentEncoding": "identity",
    }
    (destination / "capture.json").write_text(json.dumps(evidence))
    return destination
