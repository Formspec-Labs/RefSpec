"""Pinned development concept-domain bridge regressions."""

from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import FrozenInstanceError, dataclass
from pathlib import Path

import pytest

from refspec.registry import (
    ICPSR_FEDERAL_REGISTER_BRIDGE_V1_SHA256,
    ConceptDomainBridgeError,
    load_concept_domain_bridge,
)

SOURCE_SCHEME = "https://example.org/source/scheme"
SOURCE_RELEASE = "urn:test:source-release:2026-07-30"
SOURCE_CONCEPT = "https://example.org/source/concepts/civil-liberties"
SECOND_SOURCE_CONCEPT = "https://example.org/source/concepts/courts"
TARGET_RELEASE = "urn:test:target-release:2026-07-30"
TARGET_CONCEPT = "urn:test:target-concept:civil-rights"
MAPPING_ID = "urn:test:mapping:civil-liberties-civil-rights"
SOURCE_SHA256 = "sha256:" + "a" * 64


@dataclass(frozen=True)
class _TargetMember:
    release_iri: str


class _TargetView:
    def __init__(self, members: dict[str, _TargetMember]) -> None:
        self._members = members

    def lookup_member(self, member_iri: str) -> _TargetMember | None:
        return self._members.get(member_iri)


def _target_view(
    *,
    release_iri: str = TARGET_RELEASE,
    include_member: bool = True,
) -> _TargetView:
    return _TargetView(
        {
            TARGET_CONCEPT: _TargetMember(release_iri=release_iri),
        }
        if include_member
        else {}
    )


def _bridge_record() -> dict[str, object]:
    return {
        "developmentOnly": True,
        "sourceSnapshot": {
            "url": "https://example.org/source/snapshot.json",
            "revision": "6e2651e55fb42b119a167f34000ec728d1206865",
            "sha256": SOURCE_SHA256,
        },
        "sourceScheme": SOURCE_SCHEME,
        "sourceRelease": SOURCE_RELEASE,
        "targetRelease": TARGET_RELEASE,
        "sourceConcepts": [
            {
                "id": SOURCE_CONCEPT,
                "prefLabel": {
                    "en": "Civil liberties",
                    "es": "Libertades civiles",
                    "zh-Hant": "公民自由",
                },
                "altLabel": {
                    "en": ["Civil freedom", "Individual liberties"],
                },
                "definition": {
                    "en": "Freedoms protected from government interference.",
                },
                "evidenceUrl": (
                    "https://example.org/source/concepts/civil-liberties"
                ),
            }
        ],
        "mappings": [
            {
                "@id": MAPPING_ID,
                "@type": "rkaf:ConceptMapping",
                "rkaf:assertionOrigin": "rkaf:humanAsserted",
                "rkaf:epistemicBasis": "rkaf:editorialAssertion",
                "rkaf:assertsSubject": SOURCE_CONCEPT,
                "rkaf:assertsPredicate": "skos:closeMatch",
                "rkaf:assertsObject": TARGET_CONCEPT,
                "rkaf:assertionPolarity": "rkaf:affirmed",
                "rkaf:sourceConceptRelease": SOURCE_RELEASE,
                "rkaf:targetConceptRelease": TARGET_RELEASE,
                "rkaf:managedByRegistry": "urn:test:registry:domain-bridge",
                "rkaf:usageEligibility": "rkaf:localOperationalUse",
            }
        ],
    }


def _write_record(path: Path, record: object) -> str:
    payload = (
        json.dumps(record, ensure_ascii=False, indent=2) + "\n"
    ).encode("utf-8")
    path.write_bytes(payload)
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _load(
    tmp_path: Path,
    record: object,
    *,
    target_view: _TargetView | None = None,
):
    path = tmp_path / "bridge.json"
    digest = _write_record(path, record)
    return load_concept_domain_bridge(
        path,
        expected_sha256=digest,
        target_view=target_view or _target_view(),
    )


def test_loads_pinned_bridge_without_merging_source_and_target_concepts(
    tmp_path: Path,
) -> None:
    bridge = _load(tmp_path, _bridge_record())

    assert bridge.development_only is True
    assert bridge.source_snapshot.sha256 == SOURCE_SHA256
    assert bridge.source_scheme_iri == SOURCE_SCHEME
    assert bridge.source_release_iri == SOURCE_RELEASE
    assert bridge.target_release_iri == TARGET_RELEASE
    assert len(bridge.source_concepts) == 1
    source = bridge.lookup_source_concept(SOURCE_CONCEPT)
    assert source is not None
    assert source.preferred_labels == {
        "en": "Civil liberties",
        "es": "Libertades civiles",
        "zh-Hant": "公民自由",
    }
    assert source.alternate_labels["en"] == (
        "Civil freedom",
        "Individual liberties",
    )
    assert source.definitions["en"] == (
        "Freedoms protected from government interference.",
    )
    assert source.concept_iri != TARGET_CONCEPT

    assert len(bridge.mappings) == 1
    mapping = bridge.mappings[0]
    assert mapping.mapping_iri == MAPPING_ID
    assert mapping.source_member_iri == SOURCE_CONCEPT
    assert mapping.relation_iri == "skos:closeMatch"
    assert mapping.target_member_iri == TARGET_CONCEPT
    assert mapping.source_release_iri == SOURCE_RELEASE
    assert mapping.target_release_iri == TARGET_RELEASE

    with pytest.raises(FrozenInstanceError):
        source.concept_iri = SECOND_SOURCE_CONCEPT  # type: ignore[misc]
    with pytest.raises(TypeError):
        source.preferred_labels["fr"] = "Libertés civiles"  # type: ignore[index]
    with pytest.raises(TypeError):
        mapping.record["rkaf:assertsObject"] = SOURCE_CONCEPT  # type: ignore[index]


def test_rejects_bridge_whose_bytes_do_not_match_the_pin(
    tmp_path: Path,
) -> None:
    path = tmp_path / "bridge.json"
    _write_record(path, _bridge_record())

    with pytest.raises(
        ConceptDomainBridgeError,
        match="digest does not match",
    ):
        load_concept_domain_bridge(
            path,
            expected_sha256="sha256:" + "0" * 64,
            target_view=_target_view(),
        )


@pytest.mark.parametrize(
    ("field", "value", "match"),
    [
        ("developmentOnly", False, "developmentOnly must be true"),
        ("sourceScheme", "not-an-iri", "must be an absolute IRI"),
    ],
)
def test_rejects_non_development_or_non_iri_wrapper_values(
    tmp_path: Path,
    field: str,
    value: object,
    match: str,
) -> None:
    record = _bridge_record()
    record[field] = value

    with pytest.raises(ConceptDomainBridgeError, match=match):
        _load(tmp_path, record)


def test_rejects_open_wrapper_and_nested_shapes(tmp_path: Path) -> None:
    wrapper = _bridge_record()
    wrapper["comment"] = "not part of the bridge shape"
    with pytest.raises(ConceptDomainBridgeError, match="unexpected"):
        _load(tmp_path, wrapper)

    concept = _bridge_record()
    concept["sourceConcepts"][0]["notation"] = "CIV"  # type: ignore[index]
    with pytest.raises(ConceptDomainBridgeError, match="unexpected"):
        _load(tmp_path, concept)

    mapping = _bridge_record()
    mapping["mappings"][0]["confidence"] = 0.9  # type: ignore[index]
    with pytest.raises(ConceptDomainBridgeError, match="unexpected"):
        _load(tmp_path, mapping)


@pytest.mark.parametrize(
    "pref_label",
    [
        "Civil liberties",
        {},
        {"@none": "Civil liberties"},
        {"en": ["Civil liberties", "Civil freedoms"]},
    ],
)
def test_rejects_malformed_or_untagged_preferred_labels(
    tmp_path: Path,
    pref_label: object,
) -> None:
    record = _bridge_record()
    record["sourceConcepts"][0]["prefLabel"] = pref_label  # type: ignore[index]

    with pytest.raises(ConceptDomainBridgeError):
        _load(tmp_path, record)


def test_accepts_only_the_five_skos_mapping_predicates(
    tmp_path: Path,
) -> None:
    for predicate in (
        "skos:exactMatch",
        "skos:closeMatch",
        "skos:broadMatch",
        "skos:narrowMatch",
        "skos:relatedMatch",
    ):
        record = _bridge_record()
        record["mappings"][0]["rkaf:assertsPredicate"] = predicate  # type: ignore[index]
        assert _load(tmp_path, record).mappings[0].relation_iri == predicate

    invalid = _bridge_record()
    invalid["mappings"][0]["rkaf:assertsPredicate"] = "skos:broader"  # type: ignore[index]
    with pytest.raises(
        ConceptDomainBridgeError,
        match="five SKOS mapping predicates",
    ):
        _load(tmp_path, invalid)


def test_rejects_duplicate_source_concept_or_mapping_ids(
    tmp_path: Path,
) -> None:
    duplicate_concept = _bridge_record()
    duplicate_concept["sourceConcepts"].append(  # type: ignore[union-attr]
        copy.deepcopy(duplicate_concept["sourceConcepts"][0])  # type: ignore[index]
    )
    with pytest.raises(ConceptDomainBridgeError, match="duplicate ids"):
        _load(tmp_path, duplicate_concept)

    duplicate_mapping = _bridge_record()
    duplicate_mapping["mappings"].append(  # type: ignore[union-attr]
        copy.deepcopy(duplicate_mapping["mappings"][0])  # type: ignore[index]
    )
    with pytest.raises(ConceptDomainBridgeError, match="duplicate ids"):
        _load(tmp_path, duplicate_mapping)


@pytest.mark.parametrize(
    ("mapping_field", "value"),
    [
        ("rkaf:assertsSubject", SECOND_SOURCE_CONCEPT),
        ("rkaf:sourceConceptRelease", "urn:test:source-release:other"),
    ],
)
def test_requires_source_endpoint_in_the_exact_source_release(
    tmp_path: Path,
    mapping_field: str,
    value: str,
) -> None:
    record = _bridge_record()
    record["mappings"][0][mapping_field] = value  # type: ignore[index]

    with pytest.raises(
        ConceptDomainBridgeError,
        match="source endpoint",
    ):
        _load(tmp_path, record)


def test_requires_target_endpoint_in_the_exact_managed_release(
    tmp_path: Path,
) -> None:
    with pytest.raises(ConceptDomainBridgeError, match="target endpoint"):
        _load(
            tmp_path,
            _bridge_record(),
            target_view=_target_view(include_member=False),
        )

    with pytest.raises(ConceptDomainBridgeError, match="target endpoint"):
        _load(
            tmp_path,
            _bridge_record(),
            target_view=_target_view(
                release_iri="urn:test:target-release:other",
            ),
        )

    wrong_mapping_release = _bridge_record()
    wrong_mapping_release["mappings"][0]["rkaf:targetConceptRelease"] = (  # type: ignore[index]
        "urn:test:target-release:other"
    )
    with pytest.raises(ConceptDomainBridgeError, match="target endpoint"):
        _load(tmp_path, wrong_mapping_release)


def test_rejects_duplicate_json_object_fields(tmp_path: Path) -> None:
    path = tmp_path / "bridge.json"
    payload = (
        b'{"developmentOnly":true,"developmentOnly":true,'
        b'"sourceSnapshot":{},"sourceScheme":"urn:test:scheme",'
        b'"sourceRelease":"urn:test:source","targetRelease":"urn:test:target",'
        b'"sourceConcepts":[],"mappings":[]}'
    )
    path.write_bytes(payload)

    with pytest.raises(ConceptDomainBridgeError, match="repeats field"):
        load_concept_domain_bridge(
            path,
            expected_sha256=(
                "sha256:" + hashlib.sha256(payload).hexdigest()
            ),
            target_view=_target_view(),
        )


def test_tracked_icpsr_federal_register_bridge_matches_its_pin() -> None:
    release = "urn:ref:fr-thesaurus-1995:release:1995-11-16-preview"
    target_ids = {
        "urn:ref:fr-thesaurus-1995:concept:0153",
        "urn:ref:fr-thesaurus-1995:concept:0444",
        "urn:ref:fr-thesaurus-1995:concept:0453",
        "urn:ref:fr-thesaurus-1995:concept:0542",
        "urn:ref:fr-thesaurus-1995:concept:0766",
        "urn:ref:fr-thesaurus-1995:concept:0798",
        "urn:ref:fr-thesaurus-1995:concept:0964",
    }
    bridge = load_concept_domain_bridge(
        Path(__file__).resolve().parents[1]
        / "examples"
        / "development"
        / "icpsr-federal-register-concept-bridge-v1.json",
        expected_sha256=(
            ICPSR_FEDERAL_REGISTER_BRIDGE_V1_SHA256
        ),
        target_view=_TargetView(
            {
                concept_id: _TargetMember(release_iri=release)
                for concept_id in target_ids
            }
        ),
    )

    assert bridge.target_release_iri == release
    assert {
        mapping.target_member_iri for mapping in bridge.mappings
    } == target_ids
    assert {
        mapping.relation_iri for mapping in bridge.mappings
    } == {"skos:closeMatch"}
    aliases = {
        alias
        for concept in bridge.source_concepts
        for values in concept.alternate_labels.values()
        for alias in values
    }
    assert "asylum seekers" in aliases
    assert "warrants" not in aliases
