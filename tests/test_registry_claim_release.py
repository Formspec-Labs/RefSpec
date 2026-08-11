from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from jsonschema import Draft202012Validator

from refspec.registry.infrastructure.artifact_serialization import canonical_json_bytes
from refspec.registry.infrastructure.registry_claim_release import (
    CLAIM_RECORD_JSON_SCHEMA,
    CLAIM_RECORD_SCHEMA_FILE,
    CLAIMS_FILE,
    MANIFEST_FILE,
    MANIFEST_JSON_SCHEMA,
    MANIFEST_SCHEMA_FILE,
    RegistryClaim,
    RegistryClaimReleaseError,
    RegistryClaimReleaseView,
    RegistryRawInput,
    build_registry_claim_release,
)

RELEASE_ID = "urn:ref:registry-claim-release:test:v1"
RECIPE_ID = "urn:ref:recipe:test-rdf:v1"
LIMITATION_ID = "urn:ref:limitation:test-english-only:v1"
SOURCE_IRI = "https://example.test/source.ttl"
SOURCE_DIGEST = "sha256:" + hashlib.sha256(b"source bytes\n").hexdigest()


def _digest(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _claim(
    *,
    subject: str = "https://example.test/concept/1",
    predicate: str = "http://www.w3.org/2004/02/skos/core#prefLabel",
    lexical_value: str = "Example",
    datatype: str | None = None,
) -> RegistryClaim:
    return RegistryClaim(
        release_id=RELEASE_ID,
        subject=subject,
        predicate=predicate,
        object_kind="literal",
        lexical_value=lexical_value,
        language=None if datatype else "en",
        datatype=datatype,
        source_record_id=subject,
        source_locator=SOURCE_IRI,
        source_path="source.ttl#claim=1",
        source_digest=SOURCE_DIGEST,
        origin="observed",
        recipe_id=RECIPE_ID,
        limitation_ids=(LIMITATION_ID,),
    )


def _build(tmp_path: Path, name: str = "release") -> RegistryClaimReleaseView:
    raw = tmp_path / f"{name}-source.ttl"
    raw.write_bytes(b"source bytes\n")
    return build_registry_claim_release(
        tmp_path / name,
        release_id=RELEASE_ID,
        release_key="test-v1",
        issued="2026-08-07",
        release_scope={"mode": "completeCapture"},
        language_scope={
            "included": ["en", "untagged"],
            "mode": "englishOnly",
        },
        recipes=(
            {
                "description": "Parse the test RDF and preserve exact claims.",
                "id": RECIPE_ID,
                "implementation": "tests.test_registry_claim_release",
                "version": "1.0",
            },
        ),
        limitations=(
            {
                "description": "Non-English literals are intentionally omitted.",
                "id": LIMITATION_ID,
            },
        ),
        claims=(
            _claim(),
            RegistryClaim(
                release_id=RELEASE_ID,
                subject="https://example.test/concept/1",
                predicate="http://www.w3.org/2004/02/skos/core#broader",
                object_kind="iri",
                object_iri="https://example.test/concept/2",
                source_record_id="https://example.test/concept/1",
                source_locator=SOURCE_IRI,
                source_path="source.ttl#claim=2",
                source_digest=SOURCE_DIGEST,
                origin="observed",
                recipe_id=RECIPE_ID,
            ),
        ),
        raw_inputs=(
            RegistryRawInput(
                path=raw,
                logical_path="raw/source.ttl",
                source_locator=SOURCE_IRI,
            ),
        ),
        metadata={"publisher": "Example"},
    )


def _files(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file()
    }


def _reseal_claim_member(root: Path) -> str:
    manifest_path = root / MANIFEST_FILE
    manifest = json.loads(manifest_path.read_bytes())
    claims = root / CLAIMS_FILE
    manifest["claimTable"]["byteLength"] = claims.stat().st_size
    manifest["claimTable"]["sha256"] = _digest(claims)
    manifest_path.write_bytes(canonical_json_bytes(manifest))
    return _digest(manifest_path)


def test_bundle_is_byte_stable_closed_and_externally_authenticated(
    tmp_path: Path,
) -> None:
    first = _build(tmp_path, "first")
    second = _build(tmp_path, "second")

    assert _files(first.root) == _files(second.root)
    assert first.manifest_digest == second.manifest_digest
    assert [claim.object_kind for claim in first.claims] == ["iri", "literal"]
    assert set(_files(first.root)) == {
        MANIFEST_FILE,
        CLAIMS_FILE,
        CLAIM_RECORD_SCHEMA_FILE,
        MANIFEST_SCHEMA_FILE,
        "raw/source.ttl",
    }
    reopened = RegistryClaimReleaseView.open(
        first.root,
        expected_manifest_digest=first.manifest_digest,
    )
    assert reopened.claims == first.claims
    Draft202012Validator(MANIFEST_JSON_SCHEMA).validate(first.manifest)
    for claim in first.claims:
        Draft202012Validator(CLAIM_RECORD_JSON_SCHEMA).validate(
            claim.as_record()
        )


def test_reader_rejects_manifest_raw_member_and_closed_set_drift(
    tmp_path: Path,
) -> None:
    view = _build(tmp_path)

    with pytest.raises(RegistryClaimReleaseError, match="manifest digest differs"):
        RegistryClaimReleaseView.open(
            view.root,
            expected_manifest_digest="sha256:" + "0" * 64,
        )

    raw = view.root / "raw/source.ttl"
    raw.write_bytes(b"tampered raw\n")
    with pytest.raises(RegistryClaimReleaseError, match="member .* differs"):
        RegistryClaimReleaseView.open(
            view.root,
            expected_manifest_digest=view.manifest_digest,
        )

    raw.write_bytes(b"source bytes\n")
    (view.root / "undeclared.txt").write_text("extra", encoding="utf-8")
    with pytest.raises(RegistryClaimReleaseError, match="membership is not closed"):
        RegistryClaimReleaseView.open(
            view.root,
            expected_manifest_digest=view.manifest_digest,
        )


def test_reader_rejects_resealed_parquet_schema_drift(tmp_path: Path) -> None:
    view = _build(tmp_path)
    claim_path = view.root / CLAIMS_FILE
    pq.write_table(
        pa.table({"not_a_claim": ["changed"]}),
        claim_path,
        version="2.6",
    )
    manifest_digest = _reseal_claim_member(view.root)

    with pytest.raises(RegistryClaimReleaseError, match="Parquet schema differs"):
        RegistryClaimReleaseView.open(
            view.root,
            expected_manifest_digest=manifest_digest,
        )


def test_reader_rejects_resealed_parquet_row_mutation(tmp_path: Path) -> None:
    view = _build(tmp_path)
    claim_path = view.root / CLAIMS_FILE
    rows = pq.read_table(claim_path).to_pylist()
    literal = next(row for row in rows if row["object_kind"] == "literal")
    literal["lexical_value"] = "Silently normalized"
    pq.write_table(
        pa.Table.from_pylist(rows, schema=pq.read_schema(claim_path)),
        claim_path,
        version="2.6",
    )
    manifest_digest = _reseal_claim_member(view.root)

    with pytest.raises(RegistryClaimReleaseError, match="logical digest differs"):
        RegistryClaimReleaseView.open(
            view.root,
            expected_manifest_digest=manifest_digest,
        )


def test_claim_shape_rejects_mixed_iri_and_literal_objects() -> None:
    with pytest.raises(RegistryClaimReleaseError, match="literal fields"):
        RegistryClaim(
            release_id=RELEASE_ID,
            subject="https://example.test/concept/1",
            predicate="http://www.w3.org/2004/02/skos/core#broader",
            object_kind="iri",
            object_iri="https://example.test/concept/2",
            lexical_value="not allowed",
            source_record_id="https://example.test/concept/1",
            source_locator=SOURCE_IRI,
            source_path="source.ttl#claim=2",
            source_digest=SOURCE_DIGEST,
            origin="observed",
            recipe_id=RECIPE_ID,
        )


def test_bundle_rejects_claim_evidence_missing_from_raw_pins(tmp_path: Path) -> None:
    raw = tmp_path / "source.ttl"
    raw.write_bytes(b"source bytes\n")

    with pytest.raises(
        RegistryClaimReleaseError,
        match="source evidence absent from raw input pins",
    ):
        build_registry_claim_release(
            tmp_path / "release",
            release_id=RELEASE_ID,
            release_key="test-v1",
            issued="2026-08-07",
            release_scope={"mode": "completeCapture"},
            language_scope={"included": ["en"], "mode": "englishOnly"},
            recipes=({"id": RECIPE_ID},),
            limitations=({"id": LIMITATION_ID},),
            claims=(
                replace(_claim(), source_digest="sha256:" + "0" * 64),
            ),
            raw_inputs=(
                RegistryRawInput(
                    path=raw,
                    logical_path="raw/source.ttl",
                    source_locator=SOURCE_IRI,
                ),
            ),
        )


def test_claim_preserves_empty_typed_literal() -> None:
    claim = _claim(
        predicate="http://purl.org/dc/terms/created",
        lexical_value="",
        datatype="http://www.w3.org/2001/XMLSchema#dateTime",
    )

    assert claim.lexical_value == ""
    assert claim.language is None
    assert claim.datatype == "http://www.w3.org/2001/XMLSchema#dateTime"


def test_declared_observed_and_derived_origins_reopen_with_evidence(
    tmp_path: Path,
) -> None:
    raw = tmp_path / "methods-source.ttl"
    raw.write_bytes(b"source bytes\n")
    origins = ("observed", "scraped", "normalized", "inferred", "extrapolated")
    claims = tuple(
        RegistryClaim(
            release_id=RELEASE_ID,
            subject=f"https://example.test/concept/{index}",
            predicate="http://www.w3.org/2004/02/skos/core#prefLabel",
            object_kind="literal",
            lexical_value=f"Method {origin}",
            language="en",
            source_record_id=f"https://example.test/concept/{index}",
            source_locator=SOURCE_IRI,
            source_path=f"source.ttl#claim={index}",
            source_digest=SOURCE_DIGEST,
            origin=origin,  # type: ignore[arg-type]
            recipe_id=RECIPE_ID,
            confidence="1" if origin in {"inferred", "extrapolated"} else None,
            limitation_ids=(LIMITATION_ID,),
        )
        for index, origin in enumerate(origins, start=1)
    )

    view = build_registry_claim_release(
        tmp_path / "methods-release",
        release_id=RELEASE_ID,
        release_key="test-methods-v1",
        issued="2026-08-07",
        release_scope={
            "complete": False,
            "method": "scraped, normalized repair, inference, and extrapolation",
            "mode": "captureSubset",
        },
        language_scope={"included": ["en"], "mode": "englishOnly"},
        recipes=(
            {
                "description": (
                    "Retain observed and scraped evidence; record repair as "
                    "normalized and record inference or extrapolation explicitly."
                ),
                "id": RECIPE_ID,
                "implementation": "tests.test_registry_claim_release",
                "version": "1.0",
            },
        ),
        limitations=(
            {
                "description": "Synthetic fixture proves declared method handling.",
                "id": LIMITATION_ID,
            },
        ),
        claims=claims,
        raw_inputs=(
            RegistryRawInput(
                path=raw,
                logical_path="raw/source.ttl",
                source_locator=SOURCE_IRI,
            ),
        ),
    )

    assert {claim.origin for claim in view.claims} == set(origins)
    assert view.manifest["claimTable"]["originCounts"] == dict.fromkeys(sorted(origins), 1)
