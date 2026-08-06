from __future__ import annotations

import hashlib
import importlib
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from rdflib import Graph, URIRef
from rdflib.namespace import RDF

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
generator = importlib.import_module("generate_atlas_v3_full")


def test_candidate_releases_build_graphs_before_semantic_validation(
    tmp_path: Path,
    monkeypatch,
) -> None:
    graphs = generator.BuildGraphs(
        asserted=Graph(),
        projection=Graph(),
        derived=Graph(),
        accounting={"sentinel": "large source ledger"},
    )
    for graph, suffix in (
        (graphs.asserted, "asserted"),
        (graphs.projection, "projection"),
        (graphs.derived, "derived"),
    ):
        graph.add(
            (
                URIRef(f"urn:test:{suffix}:subject"),
                URIRef("urn:test:predicate"),
                URIRef("urn:test:object"),
            )
        )

    events: list[str] = []

    def collect() -> int:
        events.append("collect")
        return 0

    def validate_distribution(output: Path) -> dict[str, str]:
        events.append("validate")
        assert output == tmp_path
        assert not graphs.asserted
        assert not graphs.projection
        assert not graphs.derived
        assert graphs.accounting == {}
        return {"status": "passed"}

    monkeypatch.setattr(generator.gc, "collect", collect)
    monkeypatch.setattr(
        generator.ATLAS_VALIDATE,
        "validate_distribution",
        validate_distribution,
    )

    result, _ = generator._write_candidate_distribution(tmp_path, graphs)

    assert events == ["collect", "validate"]
    assert result["semantic"] == {"status": "passed"}


def test_fixed_distribution_inputs_are_externally_pinned_and_logical() -> None:
    inventory = generator.verify_inputs()

    assert set(inventory) == {
        "expectedResources",
        "registryDescriptors",
        "registryDescriptorsPin",
        "sources",
    }
    assert all(not row["path"].startswith("/") for row in inventory["sources"])
    assert all(row["usesPriorAtlasGraph"] is False for row in inventory["sources"])
    assert "mapping-evidence" not in json.dumps(inventory, sort_keys=True)
    assert not hasattr(generator, "PROOF_BUNDLES")
    assert not hasattr(generator, "load_proof_bundles")


def test_v3_fallback_identity_is_readable_deterministic_and_source_preserving() -> None:
    local_record_id = "urn:uuid:019fc9f2-c758-7134-9432-2a0de8fde1dd"
    source_scheme = "http://id.loc.gov/vocabulary/subjectSchemes/lst"
    prior_iri = (
        "urn:ref:source-concept:v1:"
        "6db43bea6ad5f32b25d57b4cd182d1b3b7f5de9a29a727b65fc17954cec97f01:"
        "019fc9f2-c758-7134-9432-2a0de8fde1dd"
    )

    iri, source_identity = generator._v3_fallback_source_identity(
        namespace_token="loc-lst",
        prior_iri=prior_iri,
        identity_kind="refspecSourceScoped",
        local_record_id=local_record_id,
        source_scheme=source_scheme,
    )

    assert iri == (
        "urn:ref:source-concept:v2:loc-lst:"
        "019fc9f2-c758-7134-9432-2a0de8fde1dd"
    )
    assert source_identity == {
        "identityKind": "refspecSourceScoped",
        "localRecordId": local_record_id,
        "namespaceToken": "loc-lst",
        "priorSourceConceptIri": prior_iri,
        "sourceScheme": source_scheme,
    }


@pytest.mark.parametrize(
    "overrides, message",
    (
        ({"namespace_token": None}, "fallback namespace token"),
        ({"namespace_token": "LOC_LST"}, "fallback namespace token"),
        (
            {"identity_kind": "publisherConceptIri"},
            "only refspecSourceScoped",
        ),
        ({"local_record_id": "urn:uuid:not-a-uuid"}, "UUID"),
        ({"source_scheme": "not-an-iri"}, "absolute IRI"),
        (
            {"namespace_token": "loc-cgpa"},
            "does not identify the exact sourceScheme",
        ),
        ({"prior_iri": "urn:test:wrong"}, "prior source concept IRI"),
    ),
)
def test_v3_fallback_identity_fails_closed(
    overrides: dict[str, object],
    message: str,
) -> None:
    values: dict[str, object] = {
        "namespace_token": "loc-lst",
        "prior_iri": (
            "urn:ref:source-concept:v1:"
            "6db43bea6ad5f32b25d57b4cd182d1b3b7f5de9a29a727b65fc17954cec97f01:"
            "019fc9f2-c758-7134-9432-2a0de8fde1dd"
        ),
        "identity_kind": "refspecSourceScoped",
        "local_record_id": (
            "urn:uuid:019fc9f2-c758-7134-9432-2a0de8fde1dd"
        ),
        "source_scheme": "http://id.loc.gov/vocabulary/subjectSchemes/lst",
    }
    values.update(overrides)

    with pytest.raises(ValueError, match=message):
        generator._v3_fallback_source_identity(**values)


def test_v3_fallback_identity_rejects_non_string_local_id() -> None:
    with pytest.raises(TypeError, match="localRecordId"):
        generator._v3_fallback_source_identity(
            namespace_token="loc-lst",
            prior_iri="urn:test:prior",
            identity_kind="refspecSourceScoped",
            local_record_id=7,
            source_scheme="http://id.loc.gov/vocabulary/subjectSchemes/lst",
        )


def _source_spec(key: str):
    return next(spec for spec in generator.SOURCE_SPECS if spec.key == key)


@pytest.mark.parametrize(
    ("role", "predicate"),
    (
        ("preferred", generator.SKOSXL.prefLabel),
        ("alternate", generator.SKOSXL.altLabel),
        ("hidden", generator.SKOSXL.hiddenLabel),
    ),
)
def test_source_label_roles_map_to_skosxl(role: str, predicate: URIRef) -> None:
    label = generator.SourceLabel(
        value="Label",
        language="en",
        role=role,
        source_path="source#label",
    )

    assert label.role == role
    assert generator._source_label_predicate(role) == predicate


def test_source_label_roles_fail_closed() -> None:
    with pytest.raises(ValueError, match="unsupported source label role"):
        generator.SourceLabel(
            value="Label",
            language="en",
            role="future-role",
            source_path="source#label",
        )
    with pytest.raises(ValueError, match="unsupported source label role"):
        generator._source_label_predicate("future-role")


def test_crs_loader_preserves_source_label_roles(
    tmp_path: Path,
    monkeypatch,
) -> None:
    source = tmp_path / "crs-source.json"
    source.write_text("{}", encoding="utf-8")
    digest = "sha256:" + hashlib.sha256(source.read_bytes()).hexdigest()
    observation = {
        "id": "urn:test:observation",
        "labels": [
            {"language": "en", "role": "preferred", "value": "Public label"},
            {"language": "en", "role": "hidden", "value": "Search-only form"},
        ],
        "sourcePath": "source.json#concept",
    }
    view = SimpleNamespace(
        concepts=(
            {
                "id": "https://example.test/concept",
                "identityKind": "publisherConceptIri",
                "sourceObservation": observation["id"],
                "sourceObservationDigest": "sha256:" + "1" * 64,
            },
        ),
        release_digest="sha256:" + "2" * 64,
        release_id="urn:test:crs-release",
        source_bundle=SimpleNamespace(observations=(observation,)),
    )
    monkeypatch.setattr(
        generator.SourceConceptReleaseView,
        "open",
        staticmethod(lambda *_args, **_kwargs: view),
    )
    spec = generator.SourceSpec(
        key="crs-test",
        kind="sourceConceptRelease",
        path=source,
        logical_path="test/crs-source.json",
        expected_digest=digest,
        expected_resources=1,
        profile="conceptScheme",
        ring="subject",
    )

    release = generator._load_crs(spec)

    assert {label.value: label.role for label in release.resources[0].labels} == {
        "Public label": "preferred",
        "Search-only form": "hidden",
    }


def test_elsst_loader_includes_english_hidden_labels(
    tmp_path: Path,
    monkeypatch,
) -> None:
    source = tmp_path / "elsst-source.json"
    source.write_text("{}", encoding="utf-8")
    digest = "sha256:" + hashlib.sha256(source.read_bytes()).hexdigest()
    member = SimpleNamespace(
        member_iri="https://example.test/elsst/concept",
        record={
            "skos:altLabel": {"en": ["Alternate label"]},
            "skos:hiddenLabel": {
                "en": ["Hidden label"],
                "fr": ["Etiquette cachee"],
            },
            "skos:prefLabel": {"en": "Preferred label"},
        },
    )

    class FakeElsstView:
        def iter_members(self, *, release_iri: str):
            assert release_iri == "https://elsst.cessda.eu/id/6"
            return iter((member,))

    monkeypatch.setattr(
        generator.ManagedReleaseGraphFactsView,
        "open",
        staticmethod(lambda *_args, **_kwargs: FakeElsstView()),
    )
    spec = generator.SourceSpec(
        key="elsst-r6",
        kind="managedRelease",
        path=source,
        logical_path="test/elsst-source.json",
        expected_digest=digest,
        expected_resources=1,
        profile="conceptScheme",
        ring="subject",
    )

    release = generator._load_elsst(spec)

    assert {label.value: label.role for label in release.resources[0].labels} == {
        "Alternate label": "alternate",
        "Hidden label": "hidden",
        "Preferred label": "preferred",
    }
    assert release.dropped_label_count == 1


@pytest.fixture(scope="module")
def crs_releases():
    return tuple(
        generator._load_crs(_source_spec(key))
        for key in (
            "crs-legislative-entities",
            "crs-legislative-subjects",
            "crs-policy-areas",
        )
    )


def test_all_1075_crs_fallback_ids_are_readable_and_reversible(
    crs_releases,
) -> None:
    resources = [
        (release, resource)
        for release in crs_releases
        for resource in release.resources
    ]
    counts_by_namespace = {
        token: sum(
            len(release.resources)
            for release in crs_releases
            if release.spec.fallback_namespace_token == token
        )
        for token in ("loc-lst", "loc-cgpa")
    }

    assert len(resources) == 1_075
    assert counts_by_namespace == {"loc-lst": 1_043, "loc-cgpa": 32}
    assert not any(
        resource.iri.startswith("urn:ref:source-concept:v1:")
        for _, resource in resources
    )
    for release, resource in resources:
        token = release.spec.fallback_namespace_token
        assert resource.iri.startswith(
            f"urn:ref:source-concept:v2:{token}:"
        )
        assert resource.native_payload is not None
        source_identity = resource.native_payload["sourceIdentity"]
        assert source_identity["identityKind"] == "refspecSourceScoped"
        assert source_identity["namespaceToken"] == token
        assert source_identity["priorSourceConceptIri"].startswith(
            "urn:ref:source-concept:v1:"
        )
        assert resource.iri.endswith(
            source_identity["localRecordId"].removeprefix("urn:uuid:")
        )

    entity_release = next(
        release
        for release in crs_releases
        if release.spec.key == "crs-legislative-entities"
    )
    brazil = next(
        resource
        for resource in entity_release.resources
        if any(label.value == "Brazil" for label in resource.labels)
    )
    assert brazil.iri == (
        "urn:ref:source-concept:v2:loc-lst:"
        "019fc9f2-c758-7134-9432-2a0de8fde1dd"
    )
    assert brazil.native_payload is not None
    assert brazil.native_payload["sourceIdentity"] == {
        "identityKind": "refspecSourceScoped",
        "localRecordId": "urn:uuid:019fc9f2-c758-7134-9432-2a0de8fde1dd",
        "namespaceToken": "loc-lst",
        "priorSourceConceptIri": (
            "urn:ref:source-concept:v1:"
            "6db43bea6ad5f32b25d57b4cd182d1b3b7f5de9a29a727b65fc17954cec97f01:"
            "019fc9f2-c758-7134-9432-2a0de8fde1dd"
        ),
        "sourceScheme": "http://id.loc.gov/vocabulary/subjectSchemes/lst",
    }


@pytest.fixture(scope="module")
def icpsr_release():
    return generator._load_icpsr(_source_spec("icpsr-subject-thesaurus"))


def test_only_five_icpsr_xml_gaps_receive_readable_fallback_ids(
    icpsr_release,
) -> None:
    fallback_resources = [
        resource
        for resource in icpsr_release.resources
        if resource.native_payload is not None
        and resource.native_payload.get("identityStatus")
        == "publisherIdentifierAbsent"
    ]
    publisher_resources = [
        resource
        for resource in icpsr_release.resources
        if resource.native_payload is not None
        and resource.native_payload.get("identityStatus")
        != "publisherIdentifierAbsent"
    ]
    fallback_ids = {resource.iri for resource in fallback_resources}
    fallback_relation_endpoints = {
        endpoint
        for relation in icpsr_release.relations
        for endpoint in (relation.subject, relation.object)
        if endpoint.startswith(
            "urn:ref:source-concept:v2:icpsr-subject-thesaurus:"
        )
    }

    assert len(fallback_resources) == 5
    assert len(publisher_resources) == 3_805
    assert all(
        resource.iri.startswith(
            "urn:ref:source-concept:v2:icpsr-subject-thesaurus:"
        )
        for resource in fallback_resources
    )
    assert all(
        resource.native_payload is not None
        and resource.native_payload["sourceIdentity"]["priorSourceConceptIri"].startswith(
            "urn:ref:source-concept:v1:"
        )
        for resource in fallback_resources
    )
    assert all(
        resource.iri == resource.source_locator
        for resource in publisher_resources
    )
    assert fallback_relation_endpoints == fallback_ids
    assert not any(
        resource.iri.startswith("urn:ref:source-concept:v1:")
        for resource in icpsr_release.resources
    )
    assert not any(
        endpoint.startswith("urn:ref:source-concept:v1:")
        for relation in icpsr_release.relations
        for endpoint in (relation.subject, relation.object)
    )


def test_mapping_evidence_archive_preserves_all_exact_proof_bytes() -> None:
    archive_root = (
        ROOT / "research" / "evidence" / "atlas-3-mapping-evidence-2026-08-05"
    )
    manifest_path = archive_root / "manifest.json"
    manifest_bytes = manifest_path.read_bytes()
    assert "sha256:" + hashlib.sha256(manifest_bytes).hexdigest() == (
        "sha256:287858f602d3073f81584e43f2692c1f35575bc62c767bf1ed90b217ac19f9e8"
    )
    archive = json.loads(manifest_bytes)
    counts = {
        row["id"]: row["mappingAssertionCount"]
        for row in archive["pairs"]
    }

    assert counts == {
        "elsst-icpsr": 191,
        "fr-elsst": 190,
        "fr-icpsr": 201,
    }
    assert sum(counts.values()) == 582
    assert len(archive["artifacts"]) == 9
    expected_paths = {
        f"{pair}/{name}"
        for pair in ("elsst-icpsr", "fr-elsst", "fr-icpsr")
        for name in (
            "crosswalk-bundle.json",
            "relation-assertions-v2/bundle-manifest.json",
            "relation-assertions-v2/relation-assertions.json",
        )
    }
    descriptors = {row["path"]: row for row in archive["artifacts"]}
    assert set(descriptors) == expected_paths
    for relative_path, descriptor in descriptors.items():
        artifact = archive_root / relative_path
        payload = artifact.read_bytes()
        assert descriptor["byteLength"] == len(payload)
        assert descriptor["sha256"] == (
            "sha256:" + hashlib.sha256(payload).hexdigest()
        )


def test_production_relation_scope_rejects_mapping_and_derived_relations() -> None:
    clean = generator.BuildGraphs(Graph(), Graph(), Graph(), {})
    assert generator._production_relation_scope(clean) == {
        "derivedRelations": 0,
        "mappingAssertions": 0,
        "mode": "publisherSourceOnly",
    }

    mapping = generator.BuildGraphs(Graph(), Graph(), Graph(), {})
    mapping.asserted.add(
        (
            URIRef("urn:test:mapping"),
            RDF.type,
            generator.ATLAS.MappingAssertion,
        )
    )
    with pytest.raises(ValueError, match="zero mapping assertions"):
        generator._production_relation_scope(mapping)

    derived = generator.BuildGraphs(Graph(), Graph(), Graph(), {})
    derived.derived.add(
        (
            URIRef("urn:test:derived"),
            RDF.type,
            generator.ATLAS.DerivedRelation,
        )
    )
    with pytest.raises(ValueError, match="zero mapping assertions"):
        generator._production_relation_scope(derived)


def test_recursive_english_normalization_covers_complete_elsst_profile() -> None:
    payload = {
        "nested": {
            "skos:hiddenLabel": {"en": "Hidden", "fr": "Cache"},
            "skos:editorialNote": {"EN": ["Keep"], "de": ["Drop"]},
        },
        "ordinary": {"id": ["urn:test:not-a-language-map"]},
        "tagged": [
            {"language": "EN", "value": "Keep"},
            {"language": "fr", "value": "Drop"},
        ],
    }

    normalized, dropped = generator._normalize_english_language_content(
        payload,
        language_map_fields=generator.ELSST_LANGUAGE_MAP_FIELDS,
    )

    assert normalized["nested"] == {
        "skos:editorialNote": {"en": ["Keep"]},
        "skos:hiddenLabel": {"en": ["Hidden"]},
    }
    assert normalized["ordinary"] == {"id": ["urn:test:not-a-language-map"]}
    assert normalized["tagged"] == [{"language": "en", "value": "Keep"}]
    assert {(row["path"], row["language"]) for row in dropped} == {
        ("nested/skos:editorialNote", "de"),
        ("nested/skos:hiddenLabel", "fr"),
        ("tagged/1", "fr"),
    }
    maps, tags, violations = generator._audit_english_language_content(
        normalized,
        language_map_fields=generator.ELSST_LANGUAGE_MAP_FIELDS,
    )
    assert (maps, tags, violations) == (2, 1, ())


def test_english_normalization_fails_closed_for_unprofiled_language_field() -> None:
    with pytest.raises(ValueError, match="unprofiled language-bearing field"):
        generator._normalize_english_language_content(
            {"skos:futureNote": {"en": "Known", "fr": "Inconnu"}},
            language_map_fields=generator.ELSST_LANGUAGE_MAP_FIELDS,
        )


def test_source_record_rejects_nested_non_english_tagged_content() -> None:
    with pytest.raises(ValueError, match="not English-only"):
        generator._add_source_record(
            Graph(),
            source_release=URIRef("urn:test:release"),
            source_locator=URIRef("urn:test:locator"),
            source_digest="sha256:" + "0" * 64,
            native_payload={"proofDetails": {"language": "fr", "value": "preuve"}},
            represents_resource=None,
        )


def test_review_methods_match_assertion_provenance_without_operator_adoption() -> None:
    observed = {
        generator._review_method_for_assertion(generator.ATLAS.SourceAssignment),
        generator._review_method_for_assertion(
            generator.ATLAS.NativeRelationAssertion
        ),
        generator._review_method_for_assertion(
            generator.ATLAS.NativeRelationAssertion,
            deterministic_transformation=True,
        ),
    }

    assert observed == {
        generator.ATLAS.publisherAssertion,
        generator.ATLAS.deterministicTransformation,
    }
    assert generator.ATLAS.operatorAdoption not in observed
    with pytest.raises(ValueError, match="unsupported assertion"):
        generator._review_method_for_assertion(generator.ATLAS.MappingAssertion)


def test_active_editorial_policies_contain_no_serving_permission_language() -> None:
    graph = Graph()
    emitted_payloads = []

    for payload in generator.EDITORIAL_POLICY_PAYLOADS.values():
        policy = generator._add_policy(graph, payload)
        encoded = graph.value(policy, generator.ATLAS.policyPayload)
        assert encoded is not None
        emitted_payload = json.loads(str(encoded))
        emitted_payloads.append(emitted_payload)
        assert emitted_payload == generator._plain(payload)
        assert generator._portable_policy_term_violations(emitted_payload) == ()

    assert len(emitted_payloads) == 1
    with pytest.raises(ValueError, match="serving eligibility or permission"):
        generator._add_policy(
            Graph(),
            {"nested": [{"usage-permission": "searchOnly"}]},
        )


def test_icpsr_remap_evidence_is_content_derived_and_preserves_publisher_row() -> None:
    publisher_relation = {
        "relation": "related",
        "sourceLabel": "A",
        "sourceLocalRecordNumber": "1",
        "sourcePath": "subject.xml#record=1",
        "targetLabel": "B",
    }
    relation = generator.SourceRelation(
        subject="urn:test:a",
        predicate=str(generator.ATLAS.thesaurusRelated),
        object="urn:test:b",
        source_payload={
            "editorialTransformation": {
                "fromPredicate": str(generator.SKOS.related),
                "reason": "SKOS-S27-hierarchy-path",
                "rule": "preserveAuthoredAssociationOutsideSkosProjection",
                "toPredicate": str(generator.ATLAS.thesaurusRelated),
            },
            "publisherRelation": publisher_relation,
        },
    )

    locator, source_digest, payload = generator._icpsr_remap_evidence(relation)

    assert source_digest == generator._native_digest(publisher_relation)
    assert str(locator).endswith(source_digest.removeprefix("sha256:"))
    assert payload["publisherRelation"] == publisher_relation
    assert payload["publisherRelationDigest"] == source_digest
    assert json.dumps(payload, sort_keys=True) == json.dumps(
        generator._icpsr_remap_evidence(relation)[2],
        sort_keys=True,
    )


def test_source_accounting_recounts_all_22_icpsr_remap_evidence_records() -> None:
    represented = [
        {
            "atlasResources": [f"urn:test:icpsr:{index}"],
            "sourceRecord": f"urn:test:source-record:{index:04d}",
            "status": "represented",
        }
        for index in reversed(range(3_810))
    ]
    remap_evidence = [
        {
            "atlasResources": [],
            "reason": "Evidence-only deterministic relation remap.",
            "sourceRecord": f"urn:test:remap-evidence:{index:02d}",
            "status": "excluded",
        }
        for index in reversed(range(22))
    ]
    icpsr = {
        "declaredMemberCount": len(represented),
        "dispositions": [*represented, *remap_evidence],
        "membershipMode": "complete",
        "sourceRelease": "urn:test:release:icpsr",
    }
    other = {
        "declaredMemberCount": 0,
        "dispositions": [],
        "membershipMode": "complete",
        "sourceRelease": "urn:test:release:aaa",
    }
    accounting_inputs = [icpsr, other]

    generator._finalize_source_accounting_inputs(accounting_inputs)

    assert accounting_inputs == [other, icpsr]
    assert icpsr["declaredMemberCount"] == 3_832
    assert len(icpsr["dispositions"]) == 3_832
    assert [row["sourceRecord"] for row in icpsr["dispositions"]] == sorted(
        row["sourceRecord"] for row in icpsr["dispositions"]
    )


def test_generation_report_uses_a_location_independent_distribution_path(
    tmp_path: Path,
) -> None:
    first = tmp_path / "checkout-a" / "distribution"
    second = tmp_path / "checkout-b" / "distribution"

    assert generator._generation_report_distribution_path(first) == "distribution"
    assert generator._generation_report_distribution_path(second) == "distribution"
    assert not Path(generator._generation_report_distribution_path(first)).is_absolute()
