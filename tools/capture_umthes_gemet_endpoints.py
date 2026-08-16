#!/usr/bin/env python3
"""Capture exact UMTHES RDF responses for every distinct GEMET target."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import urllib.error
import urllib.request
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT / "src"))

from refspec.registry import gemet_alignments as gemet
from refspec.registry import umthes_content as umthes

USER_AGENT = "RefSpec-UMTHES-exact-byte-capture/1.0"


def _sha256(payload: bytes) -> str:
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _canonical(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True) + "\n").encode("utf-8")


def _fetch(url: str) -> tuple[bytes, str]:
    request = urllib.request.Request(
        url,
        headers={"Accept": "application/n-triples,text/html;q=0.9", "User-Agent": USER_AGENT},
    )
    last_error: Exception | None = None
    for _attempt in range(3):
        try:
            with urllib.request.urlopen(request, timeout=45) as response:
                if response.status != 200:
                    raise RuntimeError(f"HTTP {response.status}")
                return response.read(), response.headers.get_content_type()
        except urllib.error.HTTPError as error:
            if error.code == 404:
                raise FileNotFoundError(f"HTTP 404: {url}") from error
            last_error = error
        except (OSError, TimeoutError) as error:
            last_error = error
    raise RuntimeError(f"could not fetch {url}: {last_error}")


def _zip_info(member: str) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(member, date_time=(1980, 1, 1, 0, 0, 0))
    info.compress_type = zipfile.ZIP_STORED
    info.external_attr = 0o100644 << 16
    return info


def capture(*, mapping_path: Path, output: Path, retrieved_at: str, workers: int) -> None:
    if output.exists():
        raise FileExistsError(f"refusing to overwrite existing capture: {output}")
    mapping = gemet.load_gemet_alignments(mapping_path)
    legacy_iris = sorted({row.object_iri for row in mapping.mappings if row.target_system == "umthes"})
    if len(legacy_iris) != umthes.UMTHES_EXPECTED_REQUESTED_RECORD_COUNT:
        raise ValueError(
            "GEMET UMTHES target count differs: expected "
            f"{umthes.UMTHES_EXPECTED_REQUESTED_RECORD_COUNT}, "
            f"observed {len(legacy_iris)}"
        )

    license_payload, license_content_type = _fetch(umthes.UMTHES_LICENSE_SOURCE_URL)
    umthes._verify_license(license_payload)  # exact publisher wording is an acquisition gate

    fetched: dict[str, tuple[bytes, str, str]] = {}

    def fetch_record(legacy_iri: str) -> tuple[str, bytes, str, str]:
        concept_id = legacy_iri.removeprefix(umthes.UMTHES_LEGACY_PREFIX)
        url = umthes.UMTHES_RECORD_URL_TEMPLATE.format(concept_id=concept_id)
        last_error: Exception | None = None
        for _attempt in range(3):
            payload, content_type = _fetch(url)
            try:
                umthes.parse_umthes_record_nt(
                    payload,
                    legacy_iri=legacy_iri,
                    source_url=url,
                    retrieved_at=retrieved_at,
                )
            except umthes.UmthesContentError as error:
                last_error = error
                continue
            return legacy_iri, payload, content_type, url
        raise RuntimeError(f"publisher returned no requested concept after retries: {last_error}")

    failures: list[str] = []
    unavailable: list[dict[str, object]] = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(fetch_record, iri): iri for iri in legacy_iris}
        for index, future in enumerate(as_completed(futures), start=1):
            legacy_iri = futures[future]
            try:
                iri, payload, content_type, url = future.result()
                fetched[iri] = (payload, content_type, url)
            except FileNotFoundError:
                concept_id = legacy_iri.removeprefix(umthes.UMTHES_LEGACY_PREFIX)
                unavailable.append(
                    {
                        "httpStatus": 404,
                        "legacyIri": legacy_iri,
                        "url": umthes.UMTHES_RECORD_URL_TEMPLATE.format(concept_id=concept_id),
                    }
                )
            except RuntimeError as error:
                failures.append(f"{legacy_iri}: {error}")
            if index % 250 == 0:
                print(f"fetched {index}/{len(legacy_iris)} responses; failures={len(failures)}", flush=True)
    if failures:
        raise RuntimeError("UMTHES capture failed:\n" + "\n".join(failures[:25]))
    unavailable_ids = {
        str(item["legacyIri"]).removeprefix(umthes.UMTHES_LEGACY_PREFIX) for item in unavailable
    }
    if unavailable_ids != umthes.UMTHES_UNAVAILABLE_CONCEPT_IDS:
        raise RuntimeError(
            "UMTHES unavailable target set differs: "
            f"expected={sorted(umthes.UMTHES_UNAVAILABLE_CONCEPT_IDS)!r}, "
            f"observed={sorted(unavailable_ids)!r}"
        )

    record_descriptors: list[dict[str, object]] = []
    record_members: list[tuple[str, bytes]] = []
    for legacy_iri in legacy_iris:
        if legacy_iri not in fetched:
            continue
        payload, content_type, url = fetched[legacy_iri]
        concept_id = legacy_iri.removeprefix(umthes.UMTHES_LEGACY_PREFIX)
        member = f"records/{concept_id}.nt"
        record_descriptors.append(
            {
                "byteLength": len(payload),
                "contentType": content_type,
                "legacyIri": legacy_iri,
                "member": member,
                "sha256": _sha256(payload),
                "url": url,
            }
        )
        record_members.append((member, payload))
    manifest = {
        "format": "refspec-umthes-http-capture/1",
        "license": {
            "byteLength": len(license_payload),
            "contentType": license_content_type,
            "member": "license.html",
            "sha256": _sha256(license_payload),
            "url": umthes.UMTHES_LICENSE_SOURCE_URL,
        },
        "recordCount": len(record_descriptors),
        "records": record_descriptors,
        "requestedRecordCount": len(legacy_iris),
        "retrievedAt": retrieved_at,
        "sourceUrlRoot": umthes.UMTHES_CAPTURE_SOURCE_ROOT,
        "sourceUrlTemplate": umthes.UMTHES_RECORD_URL_TEMPLATE,
        "unavailableRecords": sorted(unavailable, key=lambda item: str(item["legacyIri"])),
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".tmp")
    try:
        with zipfile.ZipFile(temporary, "w") as archive:
            archive.writestr(_zip_info("manifest.json"), _canonical(manifest))
            archive.writestr(_zip_info("license.html"), license_payload)
            for member, payload in record_members:
                archive.writestr(_zip_info(member), payload)
        temporary.replace(output)
    finally:
        if temporary.exists():
            temporary.unlink()
    archive_payload = output.read_bytes()
    print(f"path={output}")
    print(f"bytes={len(archive_payload)}")
    print(f"sha256={_sha256(archive_payload)}")
    print(f"records={len(record_descriptors)}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--mapping",
        type=Path,
        default=REPOSITORY_ROOT / "output" / "registry-real-data-sources" / gemet.GEMET_ALIGNMENT_FILENAME,
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=REPOSITORY_ROOT / "output" / "registry-real-data-sources" / umthes.UMTHES_CAPTURE_FILENAME,
    )
    parser.add_argument("--retrieved-at", required=True)
    parser.add_argument("--workers", type=int, default=8)
    args = parser.parse_args()
    if args.workers < 1 or args.workers > 16:
        parser.error("--workers must be between 1 and 16")
    capture(
        mapping_path=args.mapping,
        output=args.output,
        retrieved_at=args.retrieved_at,
        workers=args.workers,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
