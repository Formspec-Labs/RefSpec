from __future__ import annotations

import hashlib
from collections import defaultdict
from dataclasses import replace
from pathlib import Path

from refspec.atlas.registry_claim_input import (
    ATLAS_CLAIM_RECORD_TYPE,
    ATLAS_CLAIM_RECORD_VERSION,
    AtlasRegistryClaimInput,
    AtlasSourceClaimRecord,
    adapt_registry_claim_release,
    inject_registry_claim_release,
    validate_atlas_registry_claims,
)
from refspec.atlas.v3_source_data import (
    RegistryInputPin,
    RegistryLabel,
    RegistryRelease,
    RegistryResource,
)
from refspec.registry.infrastructure.registry_claim_release import (
    RegistryClaim,
    RegistryRawInput,
    build_registry_claim_release,
)

RELEASE_ID = "urn:ref:registry-claim-release:adapter-test:v1"
RECIPE_ID = "urn:ref:recipe:adapter-test:v1"
SOURCE_IRI = "https://example.test/source.ttl"
SUBJECT = "https://example.test/concept/one"
TARGET = "https://example.test/concept/two"
SOURCE_BYTES = b"adapter source\n"
SOURCE_DIGEST = "sha256:" + hashlib.sha256(SOURCE_BYTES).hexdigest()


def _claim(
    ordinal: int,
    *,
    predicate: str,
    subject: str = SUBJECT,
    object_iri: str | None = None,
    lexical_value: str | None = None,
    language: str | None = None,
    datatype: str | None = None,
) -> RegistryClaim:
    return RegistryClaim(
        release_id=RELEASE_ID,
        subject=subject,
        predicate=predicate,
        object_kind="iri" if object_iri is not None else "literal",
        object_iri=object_iri,
        lexical_value=lexical_value,
        language=language,
        datatype=datatype,
        source_record_id=subject,
        source_locator=SOURCE_IRI,
        source_path=f"raw/source.ttl#claim={ordinal}",
        source_digest=SOURCE_DIGEST,
        origin="observed",
        recipe_id=RECIPE_ID,
    )


def _input(tmp_path: Path) -> tuple[AtlasRegistryClaimInput, tuple[RegistryClaim, ...]]:
    raw = tmp_path / "source.ttl"
    raw.write_bytes(SOURCE_BYTES)
    claims = (
        _claim(
            1,
            predicate="http://www.w3.org/2004/02/skos/core#prefLabel",
            lexical_value=" One ",
            language="en",
        ),
        _claim(
            2,
            predicate="http://www.w3.org/2004/02/skos/core#notation",
            lexical_value="1",
            datatype="http://www.w3.org/2001/XMLSchema#string",
        ),
        _claim(
            3,
            predicate="http://www.w3.org/2004/02/skos/core#broader",
            object_iri=TARGET,
        ),
        _claim(
            4,
            predicate="http://www.w3.org/2004/02/skos/core#definition",
            lexical_value="  Exact definition  ",
            language="en",
        ),
        _claim(
            5,
            predicate="http://www.w3.org/1999/02/22-rdf-syntax-ns#type",
            object_iri="http://www.w3.org/2004/02/skos/core#Concept",
        ),
    )
    view = build_registry_claim_release(
        tmp_path / "release",
        release_id=RELEASE_ID,
        release_key="adapter-test-v1",
        issued="2026-08-07",
        release_scope={"complete": True, "mode": "completeCapture"},
        language_scope={"included": ["en", "untagged"], "mode": "englishOnly"},
        recipes=(
            {
                "description": "Test recipe",
                "id": RECIPE_ID,
                "implementation": "tests.test_atlas_registry_claim_input",
                "version": "1.0",
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
    return (
        AtlasRegistryClaimInput(
            path=view.root,
            expected_manifest_digest=view.manifest_digest,
        ),
        tuple(sorted(claims, key=RegistryClaim.sort_key)),
    )


def _records(
    claims: tuple[RegistryClaim, ...],
    *,
    manifest_digest: str,
) -> tuple[AtlasSourceClaimRecord, ...]:
    grouped: dict[tuple[str, str, str], list[RegistryClaim]] = defaultdict(list)
    for claim in claims:
        grouped[
            (claim.source_record_id, claim.source_locator, claim.source_digest)
        ].append(claim)
    return tuple(
        AtlasSourceClaimRecord(
            source_record_id=key[0],
            source_locator=key[1],
            source_digest=key[2],
            native_payload={
                "claimRelease": RELEASE_ID,
                "claimReleaseManifestDigest": manifest_digest,
                "claims": [
                    claim.as_record()
                    for claim in sorted(rows, key=RegistryClaim.sort_key)
                ],
                "schemaVersion": ATLAS_CLAIM_RECORD_VERSION,
                "type": ATLAS_CLAIM_RECORD_TYPE,
            },
        )
        for key, rows in sorted(grouped.items())
    )


def test_parser_free_adapter_round_trips_every_claim(tmp_path: Path) -> None:
    input_, expected = _input(tmp_path)
    adapted = adapt_registry_claim_release(input_)
    report = validate_atlas_registry_claims(input_, adapted.records)

    assert adapted.release_id == RELEASE_ID
    assert report.passed is True
    assert report.expected_count == len(expected)
    assert report.actual_count == len(expected)
    assert report.exact_count == len(expected)
    module = Path(__file__).parents[1] / "src/refspec/atlas/registry_claim_input.py"
    source = module.read_text(encoding="utf-8")
    assert "eurovoc" not in source.casefold()
    assert "gemet" not in source.casefold()


def test_injection_adds_authenticated_inputs_without_replacing_compatibility_view(
    tmp_path: Path,
) -> None:
    input_, expected = _input(tmp_path)
    normalized_source = tmp_path / "normalized-source.ttl"
    normalized_source.write_bytes(SOURCE_BYTES)
    release = RegistryRelease(
        key="adapter-test-v1",
        resource_id="adapter-test",
        source_module="tests.test_atlas_registry_claim_input",
        profile="conceptScheme",
        ring="subject",
        scope="completeCapture",
        issued="2026-08-07",
        source_release_iri="urn:test:normalized-release",
        source_release_digest=SOURCE_DIGEST,
        atlas_release_iri="urn:test:atlas-release",
        scheme_iri="https://example.test/scheme",
        inputs=(
            RegistryInputPin(
                path=normalized_source,
                logical_path="registry-sources/adapter-test/source.ttl",
                sha256=SOURCE_DIGEST,
                byte_length=len(SOURCE_BYTES),
                source_iri=SOURCE_IRI,
            ),
        ),
        resources=(
            RegistryResource(
                iri=SUBJECT,
                labels=(
                    RegistryLabel(
                        value="One",
                        role="preferred",
                        source_path="normalized#label",
                    ),
                ),
                native_payload={"compatibility": True},
                source_locator=SOURCE_IRI,
                source_digest=SOURCE_DIGEST,
            ),
        ),
        metadata={"compatibility": True},
    )

    injected = inject_registry_claim_release(release, input_)

    assert injected.resources == release.resources
    assert injected.metadata["compatibility"] is True
    assert len(injected.inputs) == len(release.inputs) + 2
    assert {pin.role for pin in injected.inputs[-2:]} == {
        "registryClaimManifest",
        "registryClaims",
    }
    assert len(injected.supplemental_source_records) == 1
    payload = injected.supplemental_source_records[0].native_payload
    assert len(payload["claims"]) == len(expected)
    assert payload["claimReleaseManifestDigest"] == input_.expected_manifest_digest
    injected.verify_inputs()


def test_validator_collects_missing_added_datatype_direction_and_normalization(
    tmp_path: Path,
) -> None:
    input_, expected = _input(tmp_path)
    manifest_digest = input_.expected_manifest_digest
    actual = [expected[0]]
    notation = next(claim for claim in expected if claim.source_path.endswith("=2"))
    relation = next(claim for claim in expected if claim.source_path.endswith("=3"))
    definition = next(claim for claim in expected if claim.source_path.endswith("=4"))
    actual.extend(
        (
            replace(
                notation,
                datatype="http://www.w3.org/2001/XMLSchema#token",
            ),
            replace(
                relation,
                subject=TARGET,
                object_iri=SUBJECT,
                source_record_id=TARGET,
            ),
            replace(definition, lexical_value=definition.lexical_value.strip()),
            _claim(
                99,
                predicate="http://www.w3.org/2004/02/skos/core#note",
                lexical_value="Unexpected",
                language="en",
            ),
        )
    )
    report = validate_atlas_registry_claims(
        input_,
        _records(tuple(actual), manifest_digest=manifest_digest),
    )

    assert report.passed is False
    assert report.exact_count == 1
    assert report.as_dict()["differenceCounts"] == {
        "added": 1,
        "changed": 3,
        "missing": 1,
    }
    changed_fields = [
        difference.changed_fields
        for difference in report.differences
        if difference.kind == "changed"
    ]
    assert any("datatype" in fields for fields in changed_fields)
    assert any(
        {"subject", "object_iri", "source_record_id"}.issubset(fields)
        for fields in changed_fields
    )
    assert any("lexical_value" in fields for fields in changed_fields)
