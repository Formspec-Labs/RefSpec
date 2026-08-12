"""Immutable managed-release bundle and read-only view regressions."""

from __future__ import annotations

import hashlib
import json
from dataclasses import FrozenInstanceError
from pathlib import Path

import pyarrow.parquet as pq
import pytest

import refspec.managed_release as managed_release_module
import refspec.release_graph as release_graph_module
from refspec import (
    ManagedReleaseError,
    ManagedReleaseGraphFactsView,
    ManagedReleaseView,
    binding,
    canonical_text_digest,
    indexed_expression_id,
    seal_payload,
)
from refspec.generated_rulespec_dependency import RULESPEC_DEPENDENCY_BYTES
from refspec.release_graph import (
    DEPENDENCY_MANIFEST_ID,
    RELEASE_GRAPH_GATE_COMPONENT_ID,
    RELEASE_GRAPH_GATE_VERSION,
    RULESPEC_BEHAVIOR_RUNTIME_COMPONENT_ID,
    RULESPEC_VALIDATOR_COMPONENT_ID,
    canonical_value_digest,
    rulespec_graph_digest,
)
from refspec.storage import write_parquet_rows
from refspec.vocabulary import (
    CONCEPT_EVENT_PARTICIPANT_COLUMNS,
    CONCEPT_LABEL_COLUMNS,
    CONCEPT_RELATION_COLUMNS,
)

GRAPH_ID = "urn:test:rulespec-graph:subjects:v1"
RELEASE_ID = "urn:rkaf:fixture:release:digest-vector"
SCHEME_ID = "urn:rkaf:fixture:resource:topics"
MEMBER_ID = "urn:rkaf:fixture:concept:income"
ELIGIBILITY_MEMBER_ID = "urn:rkaf:fixture:concept:eligibility"
DISTRIBUTION_ID = "urn:rkaf:fixture:distribution:digest-vector-jsonld"
SECOND_DISTRIBUTION_ID = "urn:rkaf:fixture:distribution:digest-vector-turtle"
LIFECYCLE_EVENT_ID = "urn:rkaf:fixture:lifecycle:income-deprecation"
MAPPING_ID = "urn:rkaf:fixture:mapping:income-eligibility"
CORPUS_ID = "urn:test:expression-corpus:subjects:v1"
EXPRESSION_ID = "urn:ref:indexed-expression:ba926eb760fec851d37bbec4a2fb60d9423b2554e3d89b5f432f334bc75e4f9b"
ELIGIBILITY_EXPRESSION_ID = "urn:ref:indexed-expression:3dc5a10f9dd6bbd77e235b1ac702b1375b59c0479c2df08f641f17d64b67c732"
CORPUS_DIGEST = (
    "sha256:246435c660ddaf3902741c347c6301f425c2aeae002dc764fc7c2e8ddd33f18d"
)
IMPORT_ID = "urn:test:import:subjects:v1"
IMPORT_ACTIVITY_ID = "urn:test:activity:import"
RECEIPT_ID = "urn:test:run-receipt:subjects:v1"
PUBLICATION_ID = "urn:test:publication-release:subjects:v1"
CONFORMANCE_RESULT_ID = "urn:test:rulespec-conformance-result:subjects:v1"
COMBINED_RECEIPT_ID = "urn:test:combined-validation-receipt:subjects:v1"
DIGEST_A = "sha256:" + "a" * 64
DIGEST_B = "sha256:" + "b" * 64
RELEASE_DIGEST = (
    "sha256:999bb800008a7d517d4f0269304358d79a10925f21d13ea9376b0eee1feda431"
)
_TABLE_COLUMNS_FOR_TEST = {
    "concept_labels": CONCEPT_LABEL_COLUMNS,
    "concept_relations": CONCEPT_RELATION_COLUMNS,
    "concept_event_participants": CONCEPT_EVENT_PARTICIPANT_COLUMNS,
}


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _descriptor(path: Path, root: Path) -> dict[str, str]:
    return {
        "path": path.relative_to(root).as_posix(),
        "sha256": "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest(),
    }


def _manifest_digest(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _open_view(path: Path) -> ManagedReleaseView:
    return ManagedReleaseView.open(
        path,
        expected_manifest_digest=_manifest_digest(path),
    )


def _open_graph_facts(path: Path) -> ManagedReleaseGraphFactsView:
    return ManagedReleaseGraphFactsView.open(
        path,
        expected_manifest_digest=_manifest_digest(path),
    )


def build_bundle(
    root: Path,
    *,
    local_eligibility_concept: bool = False,
    release_members: list[str] | None = None,
    scheme_prior_version: str | None = None,
) -> Path:
    exact_release_members = (
        [MEMBER_ID, ELIGIBILITY_MEMBER_ID]
        if release_members is None
        else release_members
    )
    eligibility_member = {
        "@id": ELIGIBILITY_MEMBER_ID,
        "@type": (
            "rkaf:LocalConcept"
            if local_eligibility_concept
            else "rkaf:RegisteredConcept"
        ),
        "skos:prefLabel": {"en": "Eligibility policy"},
        "skos:inScheme": SCHEME_ID,
        "rkaf:conceptScope": "policy/eligibility",
    }
    if local_eligibility_concept:
        eligibility_member["rkaf:definedInScope"] = "urn:ref:test:scope:subject-atlas"
    else:
        eligibility_member["rkaf:managedByRegistry"] = "urn:test:registry:subjects"
        eligibility_member["rkaf:registeredAt"] = "2026-07-29T12:00:00Z"
    graph = {
        "@context": {
            "rkaf": "https://rulespec.org/ns/v1#",
            "skos": "http://www.w3.org/2004/02/skos/core#",
            "prov": "http://www.w3.org/ns/prov#",
            "dcterms": "http://purl.org/dc/terms/",
            "dcat": "http://www.w3.org/ns/dcat#",
        },
        "@graph": [
            {
                "@id": SCHEME_ID,
                "@type": "rkaf:ConceptScheme",
                "skos:prefLabel": {"en": "Policy topics"},
                "skos:definition": {
                    "en": "A governed scheme for policy subject concepts."
                },
                "skos:hasTopConcept": [ELIGIBILITY_MEMBER_ID],
                "rkaf:schemeFacet": "urn:rkaf:facet:topic",
                "rkaf:managedByRegistry": "urn:test:registry:subjects",
            },
            {
                "@id": RELEASE_ID,
                "@type": "rkaf:ReferenceResourceRelease",
                "dcterms:isVersionOf": SCHEME_ID,
                "dcat:version": "2026.07.28",
                "dcterms:type": "skos:ConceptScheme",
                "rkaf:membershipMode": "rkaf:completeMembership",
                "prov:hadMember": exact_release_members,
                "dcat:distribution": [
                    DISTRIBUTION_ID,
                    SECOND_DISTRIBUTION_ID,
                ],
                "rkaf:referenceReleaseDigest": RELEASE_DIGEST,
                "rkaf:versionBasis": "rkaf:publisherAssigned",
                "dcterms:issued": "2026-07-28T12:00:00Z",
            },
            {
                "@id": MEMBER_ID,
                "@type": "rkaf:RegisteredConcept",
                "skos:prefLabel": {"en": "Poultry slaughter inspection"},
                "skos:inScheme": SCHEME_ID,
                "skos:broader": [ELIGIBILITY_MEMBER_ID],
                "rkaf:managedByRegistry": "urn:test:registry:subjects",
                "rkaf:conceptScope": "policy/water",
                "rkaf:registeredAt": "2026-07-29T12:00:00Z",
            },
            eligibility_member,
            {
                "@id": DISTRIBUTION_ID,
                "@type": "rkaf:Artifact",
                "rkaf:hasArtifactIdentifier": [DISTRIBUTION_ID],
                "rkaf:artifactIdentifierScheme": ["rkaf:partner-defined"],
                "dcterms:format": "application/ld+json",
                "rkaf:hasContentDigest": DIGEST_A,
            },
            {
                "@id": SECOND_DISTRIBUTION_ID,
                "@type": "rkaf:Artifact",
                "rkaf:hasArtifactIdentifier": [SECOND_DISTRIBUTION_ID],
                "rkaf:artifactIdentifierScheme": ["rkaf:partner-defined"],
                "dcterms:format": "text/turtle",
                "rkaf:hasContentDigest": DIGEST_B,
            },
            {
                "@id": CONFORMANCE_RESULT_ID,
                "@type": "rkaf:Artifact",
                "rkaf:hasArtifactIdentifier": [CONFORMANCE_RESULT_ID],
                "rkaf:artifactIdentifierScheme": ["rkaf:partner-defined"],
                "dcterms:format": "application/json",
                "rkaf:hasContentDigest": DIGEST_B,
            },
            {
                "@id": IMPORT_ACTIVITY_ID,
                "@type": "prov:Activity",
            },
            {
                "@id": LIFECYCLE_EVENT_ID,
                "@type": "rkaf:LifecycleEvent",
                "rkaf:lifecycleEventKind": "rkaf:conceptLifecycle",
                "rkaf:conceptLifecycleOperation": "rkaf:deprecation",
                "rkaf:effectiveDate": "2026-07-29T12:00:00Z",
                "rkaf:emittedBy": "urn:test:registry:subjects",
                "rkaf:appliesTo": [MEMBER_ID],
                "rkaf:predecessorConcepts": [MEMBER_ID],
                "rkaf:predecessorConceptRelease": RELEASE_ID,
            },
            {
                "@id": MAPPING_ID,
                "@type": "rkaf:ConceptMapping",
                "rkaf:assertionOrigin": "rkaf:humanAsserted",
                "rkaf:epistemicBasis": "rkaf:editorialAssertion",
                "rkaf:assertsSubject": MEMBER_ID,
                "rkaf:assertsPredicate": "skos:closeMatch",
                "rkaf:assertsObject": ELIGIBILITY_MEMBER_ID,
                "rkaf:assertionPolarity": "rkaf:affirmed",
                "rkaf:sourceConceptRelease": RELEASE_ID,
                "rkaf:targetConceptRelease": RELEASE_ID,
                "rkaf:managedByRegistry": "urn:test:registry:subjects",
                "rkaf:usageEligibility": "rkaf:localOperationalUse",
            },
        ],
    }
    if scheme_prior_version is not None:
        graph["@context"]["owl"] = "http://www.w3.org/2002/07/owl#"
        graph["@graph"][0]["owl:priorVersion"] = scheme_prior_version
    graph_path = root / "rulespec" / "release.jsonld"
    _write_json(graph_path, graph)

    dependency_manifest = json.loads(RULESPEC_DEPENDENCY_BYTES.decode("utf-8"))
    dependency_path = root / "rulespec" / "rulespec-dependency.json"
    dependency_path.parent.mkdir(parents=True, exist_ok=True)
    dependency_path.write_bytes(RULESPEC_DEPENDENCY_BYTES)
    dependency_digest = _manifest_digest(dependency_path)
    validator_pin = {
        "id": RULESPEC_VALIDATOR_COMPONENT_ID,
        "revision": dependency_manifest["validator"]["sourceRevision"],
        "digest": canonical_value_digest(
            {
                "identity": dependency_manifest["validator"]["identity"],
                "sourceRevision": dependency_manifest["validator"]["sourceRevision"],
                "selfCertificationSha256": dependency_manifest["validator"][
                    "selfCertificationSha256"
                ],
            }
        ),
    }
    behavior_runtime_pin = {
        "id": RULESPEC_BEHAVIOR_RUNTIME_COMPONENT_ID,
        "revision": dependency_manifest["validator"]["sourceRevision"],
        "digest": canonical_value_digest(
            {
                "identity": "rkaf-behavior-validate",
                "sourceRevision": dependency_manifest["validator"]["sourceRevision"],
                "sourcePaths": [
                    "crates/rkaf-runtime",
                    "crates/rkaf-runtime-cli",
                ],
            }
        ),
    }
    gate_pin = {
        "id": RELEASE_GRAPH_GATE_COMPONENT_ID,
        "revision": RELEASE_GRAPH_GATE_VERSION,
        "digest": "sha256:"
        + hashlib.sha256(Path(release_graph_module.__file__).read_bytes()).hexdigest(),
    }

    receipt = seal_payload(
        {
            "id": RECEIPT_ID,
            "type": "urn:ref:type:RunReceipt",
            "recordedAt": "2026-07-29T17:00:00Z",
            "recordedBy": "urn:test:agent:import",
            "schemaVersion": "1.0",
            "operationalState": "complete",
            "inputCaptures": [],
            "inputSnapshots": [],
            "rulespecReleases": [
                {
                    "id": RELEASE_ID,
                    "version": "2026.07.28",
                    "digest": RELEASE_DIGEST,
                }
            ],
            "coverageWindow": {
                "startedAt": "2026-07-29T16:59:00Z",
                "endedAt": "2026-07-29T17:00:00Z",
            },
            "rulespecActivityRefs": [IMPORT_ACTIVITY_ID],
            "rulespecAgentRefs": ["urn:test:agent:import"],
            "rulespecOutputRefs": [RELEASE_ID],
            "environmentLock": {
                "id": "urn:test:environment-lock:subjects:v1",
                "digest": DIGEST_A,
            },
            "outputs": [
                {
                    "id": CORPUS_ID,
                    "digest": DIGEST_A,
                }
            ],
            "counts": {"concepts": 2, "expressions": 2},
            "exclusions": [],
            "failures": [],
            "quarantinedItems": [],
            "startedAt": "2026-07-29T16:59:00Z",
            "endedAt": "2026-07-29T17:00:00Z",
            "nondeterministicStages": [],
            "reproducibility": "deterministicFromPinnedInputs",
        }
    )
    receipt_path = root / "records" / "run-receipt.json"
    _write_json(receipt_path, receipt)

    import_snapshot = seal_payload(
        {
            "id": IMPORT_ID,
            "type": "urn:ref:type:RegistryImportSnapshot",
            "recordedAt": "2026-07-29T17:00:15Z",
            "recordedBy": "urn:test:agent:import",
            "schemaVersion": "1.0",
            "operationalState": "complete",
            "inventoryCoverageComponent": ("urn:test:inventory-component:subjects:v1"),
            "importProfile": {
                "id": "urn:test:import-profile:subjects",
                "version": "1",
                "digest": DIGEST_A,
            },
            "captures": [],
            "externalReferences": [
                "https://example.test/vocabularies/subjects/2026.07.28"
            ],
            "referenceResourceRelease": {
                "id": RELEASE_ID,
                "version": "2026.07.28",
                "digest": RELEASE_DIGEST,
            },
            "distributionArtifacts": [
                {
                    "id": DISTRIBUTION_ID,
                    "digest": DIGEST_A,
                },
                {
                    "id": SECOND_DISTRIBUTION_ID,
                    "digest": DIGEST_B,
                },
            ],
            "rightsAssessment": {
                "id": "urn:test:rights-assessment:subjects:v1",
                "digest": DIGEST_A,
            },
            "adoptedPolicyRefs": ["urn:test:policy:external-vocabulary-use:v1"],
            "transformation": {
                "id": "urn:test:implementation:subjects-parser",
                "revision": "1",
                "digest": DIGEST_A,
            },
            "exclusions": [],
            "failures": [],
            "rulespecValidationResult": {
                "id": CONFORMANCE_RESULT_ID,
                "digest": DIGEST_B,
            },
            "refValidationResult": {
                "id": "urn:test:validation-result:subjects:v1",
                "digest": DIGEST_B,
            },
            "expectedRefreshCadence": "fixture-frozen",
            "activity": IMPORT_ACTIVITY_ID,
            "receipt": RECEIPT_ID,
        }
    )
    import_snapshot_path = root / "records" / "import-snapshot.json"
    _write_json(import_snapshot_path, import_snapshot)
    import_reference = {
        "id": IMPORT_ID,
        "digest": import_snapshot["canonicalPayloadDigest"],
    }

    corpus_snapshot = {"id": CORPUS_ID, "digest": CORPUS_DIGEST}
    publication = seal_payload(
        {
            "id": PUBLICATION_ID,
            "type": "urn:ref:type:PublicationReleaseManifest",
            "recordedAt": "2026-07-29T17:01:00Z",
            "recordedBy": "urn:test:agent:publish",
            "schemaVersion": "1.0",
            "operationalState": "published",
            "version": "1.0.0-development",
            "refspecVersion": "0.1.0.dev0",
            "operationalSerializationProfile": {
                "id": "https://refspec.org/bindings/json/1.0",
                "version": "1.0",
                "digest": DIGEST_A,
            },
            "rulespecDependency": {
                "version": dependency_manifest["rulespecVersion"],
                "adoptedProfiles": ["urn:rulespec:profile:refspec"],
                "validator": validator_pin,
                "conformanceResult": {
                    "id": CONFORMANCE_RESULT_ID,
                    "digest": DIGEST_B,
                },
                "releaseAvailability": dependency_manifest["releaseAvailability"],
            },
            "claimedConformanceLevels": [
                "REF JSON Binding 1.0",
                "Rulespec validated release chain",
            ],
            "inventoryCoveragePins": [],
            "refOperationalRecords": [
                {
                    "id": RECEIPT_ID,
                    "digest": receipt["canonicalPayloadDigest"],
                },
                import_reference,
            ],
            "rulespecReleaseGraph": {
                "id": GRAPH_ID,
                "digest": rulespec_graph_digest(graph),
            },
            "expressionCorpusSnapshot": corpus_snapshot,
            "runReceipt": {
                "id": RECEIPT_ID,
                "digest": receipt["canonicalPayloadDigest"],
            },
            "releaseState": "complete",
            "deploymentClass": "developmentOnly",
            "consumerEligible": True,
            "publishedAt": "2026-07-29T17:01:00Z",
            "activity": "urn:test:activity:publish",
        }
    )
    publication_path = root / "records" / "publication.json"
    _write_json(publication_path, publication)

    expression = seal_payload(
        {
            "id": EXPRESSION_ID,
            "type": "urn:ref:type:IndexedVocabularyExpression",
            "recordedAt": "2026-07-29T17:00:30Z",
            "recordedBy": "urn:test:agent:index",
            "schemaVersion": "1.0",
            "operationalState": "active",
            "referenceResourceRelease": {
                "id": RELEASE_ID,
                "version": "2026.07.28",
                "digest": RELEASE_DIGEST,
            },
            "registryImportSnapshot": {
                **import_reference,
            },
            "distributionArtifact": {
                "id": DISTRIBUTION_ID,
                "digest": DIGEST_A,
            },
            "scheme": SCHEME_ID,
            "member": MEMBER_ID,
            "semanticProperty": ("http://www.w3.org/2004/02/skos/core#prefLabel"),
            "sourcePath": "source/records/0/prefLabel",
            "originalLiteral": "Poultry slaughter inspection",
            "language": "en",
            "normalizationPolicy": {
                "id": "urn:test:normalization:unicode",
                "version": "1",
                "digest": DIGEST_A,
            },
            "indexedText": "poultry slaughter inspection",
            "indexedTextDigest": canonical_text_digest("poultry slaughter inspection"),
            "indexedRepresentationVersion": "labels-v1",
            "expressionCorpusSnapshot": corpus_snapshot,
            "activity": "urn:test:activity:index",
            "receipt": RECEIPT_ID,
        }
    )
    eligibility_expression = seal_payload(
        {
            **expression,
            "id": ELIGIBILITY_EXPRESSION_ID,
            "distributionArtifact": {
                "id": SECOND_DISTRIBUTION_ID,
                "digest": DIGEST_B,
            },
            "member": ELIGIBILITY_MEMBER_ID,
            "originalLiteral": "Eligibility policy",
            "indexedText": "eligibility policy",
            "indexedTextDigest": canonical_text_digest("eligibility policy"),
        }
    )
    corpus_path = root / "corpus" / "indexed-expressions.jsonl"
    corpus_path.parent.mkdir(parents=True, exist_ok=True)
    corpus_path.write_text(
        "".join(
            json.dumps(value, ensure_ascii=False, sort_keys=True) + "\n"
            for value in (expression, eligibility_expression)
        ),
        encoding="utf-8",
    )

    combined_receipt = seal_payload(
        {
            "id": COMBINED_RECEIPT_ID,
            "type": "urn:ref:type:ReleaseGraphValidationReceipt",
            "recordedAt": "2026-07-29T17:01:30Z",
            "recordedBy": "urn:test:agent:combined-gate",
            "schemaVersion": "1.0",
            "operationalState": "passed",
            "receiptVersion": "1.0",
            "rulespecDependencyManifest": {
                "id": DEPENDENCY_MANIFEST_ID,
                "digest": dependency_digest,
            },
            "rulespecGraph": {
                "id": GRAPH_ID,
                "digest": rulespec_graph_digest(graph),
            },
            "refRecordDigests": [
                {
                    "id": PUBLICATION_ID,
                    "digest": publication["canonicalPayloadDigest"],
                },
                {
                    "id": RECEIPT_ID,
                    "digest": receipt["canonicalPayloadDigest"],
                },
                import_reference,
            ],
            "rulespecValidator": validator_pin,
            "rulespecBehaviorRuntime": behavior_runtime_pin,
            "gateImplementation": gate_pin,
            "verdicts": {
                "refBinding": "pass",
                "rulespecConformance": "pass",
                "rulespecBehavior": "pass",
                "crossBoundary": "pass",
            },
            "authorizationEvaluations": [],
            "coveredRulespecIdentifiers": sorted(
                {
                    SCHEME_ID,
                    RELEASE_ID,
                    MEMBER_ID,
                    ELIGIBILITY_MEMBER_ID,
                    DISTRIBUTION_ID,
                    SECOND_DISTRIBUTION_ID,
                    CONFORMANCE_RESULT_ID,
                    IMPORT_ACTIVITY_ID,
                    LIFECYCLE_EVENT_ID,
                    MAPPING_ID,
                }
            ),
            "crossReferencesDigest": DIGEST_B,
            "validatedAt": "2026-07-29T17:01:30Z",
            "activity": "urn:test:activity:combined-release-gate",
        }
    )
    combined_receipt_path = root / "validation" / "combined-receipt.json"
    _write_json(combined_receipt_path, combined_receipt)

    table_root = root / "tables"
    label_path = write_parquet_rows(
        table_root / "concept_labels.parquet",
        columns=CONCEPT_LABEL_COLUMNS,
        rows=[
            {
                "label_id": "label-water-en",
                "concept_iri": MEMBER_ID,
                "scheme_iri": SCHEME_ID,
                "release_iri": RELEASE_ID,
                "import_snapshot_id": IMPORT_ID,
                "distribution_artifact_id": DISTRIBUTION_ID,
                "source_property_iri": (
                    "http://www.w3.org/2004/02/skos/core#prefLabel"
                ),
                "label_role": "preferred",
                "original_literal": "Poultry slaughter inspection",
                "language_tag": "en",
                "status": "current",
                "expression_id": EXPRESSION_ID,
                "migration_only": False,
            },
            {
                "label_id": "label-eligibility-en",
                "concept_iri": ELIGIBILITY_MEMBER_ID,
                "scheme_iri": SCHEME_ID,
                "release_iri": RELEASE_ID,
                "import_snapshot_id": IMPORT_ID,
                "distribution_artifact_id": SECOND_DISTRIBUTION_ID,
                "source_property_iri": (
                    "http://www.w3.org/2004/02/skos/core#prefLabel"
                ),
                "label_role": "preferred",
                "original_literal": "Eligibility policy",
                "language_tag": "en",
                "status": "current",
                "expression_id": ELIGIBILITY_EXPRESSION_ID,
                "migration_only": False,
            },
        ],
    )
    relation_path = write_parquet_rows(
        table_root / "concept_relations.parquet",
        columns=CONCEPT_RELATION_COLUMNS,
        rows=[
            {
                "relation_id": "income-broader-eligibility",
                "release_iri": RELEASE_ID,
                "import_snapshot_id": IMPORT_ID,
                "distribution_artifact_id": DISTRIBUTION_ID,
                "subject_concept_iri": MEMBER_ID,
                "subject_scheme_iri": SCHEME_ID,
                "predicate_iri": ("http://www.w3.org/2004/02/skos/core#broader"),
                "object_concept_iri": ELIGIBILITY_MEMBER_ID,
                "object_scheme_iri": SCHEME_ID,
                "source_property_or_path": "skos:broader",
                "migration_only": False,
            }
        ],
    )
    event_path = write_parquet_rows(
        table_root / "concept_event_participants.parquet",
        columns=CONCEPT_EVENT_PARTICIPANT_COLUMNS,
        rows=[
            {
                "event_id": LIFECYCLE_EVENT_ID,
                "operation": "deprecation",
                "participant_role": "predecessor",
                "concept_iri": MEMBER_ID,
                "concept_type_iri": ("https://rulespec.org/ns/v1#RegisteredConcept"),
                "release_iri": RELEASE_ID,
                "complete_membership": True,
                "ordinal": 0,
                "migration_only": False,
            }
        ],
    )

    manifest = {
        "bundleVersion": "1.0",
        "publicationReleaseManifest": _descriptor(
            publication_path,
            root,
        ),
        "refRecords": [
            _descriptor(receipt_path, root),
            _descriptor(import_snapshot_path, root),
        ],
        "rulespecGraph": _descriptor(graph_path, root),
        "rulespecGraphId": GRAPH_ID,
        "rulespecDependencyManifest": _descriptor(
            dependency_path,
            root,
        ),
        "combinedValidationReceipt": _descriptor(
            combined_receipt_path,
            root,
        ),
        "normalizedTables": [
            {
                "name": "concept_labels",
                **_descriptor(label_path, root),
            },
            {
                "name": "concept_relations",
                **_descriptor(relation_path, root),
            },
            {
                "name": "concept_event_participants",
                **_descriptor(event_path, root),
            },
        ],
        "indexedExpressionCorpus": {
            **_descriptor(corpus_path, root),
            "expressionCorpusSnapshot": corpus_snapshot,
            "recordCount": 2,
            "schemaVersion": "ref-indexed-expression-corpus-1.0",
            "canonicalIdentityDigest": CORPUS_DIGEST,
        },
    }
    manifest_path = root / "managed-release-bundle.json"
    _write_json(manifest_path, manifest)
    return manifest_path


def _replace_normalized_table(
    manifest_path: Path,
    *,
    table_name: str,
    rows: list[dict[str, object]],
) -> None:
    table_path = manifest_path.parent / "tables" / f"{table_name}.parquet"
    write_parquet_rows(
        table_path,
        columns=tuple(_TABLE_COLUMNS_FOR_TEST[table_name]),
        rows=rows,
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    descriptor = next(
        value for value in manifest["normalizedTables"] if value["name"] == table_name
    )
    descriptor.update(_descriptor(table_path, manifest_path.parent))
    _write_json(manifest_path, manifest)


def test_view_is_exact_and_read_only_after_verified_open(tmp_path: Path) -> None:
    manifest_path = build_bundle(tmp_path)
    view = _open_view(manifest_path)

    assert view.rulespec_graph_id == GRAPH_ID
    assert view.rulespec_graph["@graph"]
    assert {
        candidate.member_iri for candidate in view.iter_members(release_iri=RELEASE_ID)
    } == {
        MEMBER_ID,
        ELIGIBILITY_MEMBER_ID,
    }
    member = view.lookup_member(MEMBER_ID)
    assert member is not None
    assert member.release_iri == RELEASE_ID
    assert view.lookup_member(MEMBER_ID.upper()) is None
    expression = next(iter(view.iter_expressions(member_iri=MEMBER_ID)))
    assert expression.expression_id == EXPRESSION_ID
    assert expression.indexed_text == "poultry slaughter inspection"
    assert (
        expression.semantic_property_iri
        == "http://www.w3.org/2004/02/skos/core#prefLabel"
    )
    assert expression.source_property_or_path == "source/records/0/prefLabel"
    assert expression.record["sourcePath"] == "source/records/0/prefLabel"
    assert expression.label_role == "preferred"
    assert expression.source_status == "current"
    relation = next(iter(view.iter_relations(subject_member_iri=MEMBER_ID)))
    assert relation.object_member_iri == ELIGIBILITY_MEMBER_ID
    participant = next(
        iter(view.iter_lifecycle_participants(event_iri=LIFECYCLE_EVENT_ID))
    )
    assert participant.member_iri == MEMBER_ID
    assert participant.participant_role == "predecessor"
    mapping = next(iter(view.iter_concept_mappings(source_member_iri=MEMBER_ID)))
    assert mapping.mapping_iri == MAPPING_ID
    assert mapping.relation_iri == "skos:closeMatch"
    assert mapping.target_member_iri == ELIGIBILITY_MEMBER_ID
    assert view.usage_ceiling == "candidateUseOnly"
    assert view.release_graph_validation_receipt["id"] == COMBINED_RECEIPT_ID

    with pytest.raises(TypeError):
        member.record["changed"] = True  # type: ignore[index]
    with pytest.raises(TypeError):
        expression.record["changed"] = True  # type: ignore[index]
    with pytest.raises(TypeError):
        relation.record["changed"] = True  # type: ignore[index]
    with pytest.raises(TypeError):
        participant.record["changed"] = True  # type: ignore[index]
    with pytest.raises(TypeError):
        mapping.record["changed"] = True  # type: ignore[index]
    with pytest.raises(TypeError):
        view.release_graph_validation_receipt["changed"] = True  # type: ignore[index]
    with pytest.raises(TypeError):
        view.rulespec_graph["@graph"] = []  # type: ignore[index]
    with pytest.raises(FrozenInstanceError):
        member.member_iri = "urn:test:other"  # type: ignore[misc]
    for forbidden in ("mutate", "reconcile", "deploy", "authorize_output"):
        assert not hasattr(view, forbidden)

    corpus_path = tmp_path / "corpus" / "indexed-expressions.jsonl"
    corpus_path.write_text("tampered after open\n", encoding="utf-8")
    assert next(iter(view.iter_expressions())).indexed_text == (
        "poultry slaughter inspection"
    )


def test_graph_facts_view_matches_full_graph_and_members(tmp_path: Path) -> None:
    manifest_path = build_bundle(tmp_path)

    full = _open_view(manifest_path)
    facts = _open_graph_facts(manifest_path)

    assert facts.release_id == full.release_id == PUBLICATION_ID
    assert facts.rulespec_graph_id == full.rulespec_graph_id == GRAPH_ID
    assert facts.rulespec_graph == full.rulespec_graph
    assert (
        facts.release_graph_validation_receipt["rulespecGraph"]["digest"]
        == full.release_graph_validation_receipt["rulespecGraph"]["digest"]
    )
    assert {member.member_iri: member.record for member in facts.iter_members()} == {
        member.member_iri: member.record for member in full.iter_members()
    }
    assert facts.release_graph_validation_receipt == (
        full.release_graph_validation_receipt
    )
    assert facts.eligibility_scope == "graphFactsOnly"
    assert not hasattr(facts, "iter_expressions")
    assert not hasattr(facts, "source_artifact_bytes")


def test_graph_facts_never_constructs_expression_validator(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest_path = build_bundle(tmp_path)

    def forbidden_validator() -> None:
        raise AssertionError("graph-facts reader parsed the expression corpus")

    monkeypatch.setattr(
        binding,
        "IndexedExpressionCorpusValidator",
        forbidden_validator,
    )

    assert _open_graph_facts(manifest_path).release_id == PUBLICATION_ID


def test_graph_facts_rejects_corpus_byte_corruption_and_next_open_mutation(
    tmp_path: Path,
) -> None:
    manifest_path = build_bundle(tmp_path)
    facts = _open_graph_facts(manifest_path)
    corpus_path = tmp_path / "corpus" / "indexed-expressions.jsonl"

    corpus_path.write_bytes(corpus_path.read_bytes() + b" ")

    assert facts.lookup_member(MEMBER_ID) is not None
    with pytest.raises(ManagedReleaseError, match="digest mismatch"):
        _open_graph_facts(manifest_path)


def test_graph_facts_accepts_hash_consistent_semantic_corpus_corruption_only(
    tmp_path: Path,
) -> None:
    manifest_path = build_bundle(tmp_path)
    corpus_path = tmp_path / "corpus" / "indexed-expressions.jsonl"
    records = [
        json.loads(line)
        for line in corpus_path.read_text(encoding="utf-8").splitlines()
    ]
    records[0] = seal_payload(
        {
            **records[0],
            "originalLiteral": "Changed without changing expression identity",
        }
    )
    corpus_path.write_text(
        "".join(
            json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n"
            for record in records
        ),
        encoding="utf-8",
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["indexedExpressionCorpus"].update(_descriptor(corpus_path, tmp_path))
    _write_json(manifest_path, manifest)

    assert _open_graph_facts(manifest_path).lookup_member(MEMBER_ID) is not None
    with pytest.raises(
        ManagedReleaseError,
        match="id does not bind its exact identity",
    ):
        _open_view(manifest_path)


def test_graph_facts_rejects_incomplete_release(tmp_path: Path) -> None:
    manifest_path = build_bundle(tmp_path, release_members=[])

    with pytest.raises(
        ManagedReleaseError,
        match="no exact complete-membership release members",
    ):
        _open_graph_facts(manifest_path)


def test_graph_facts_rejects_graph_corruption_after_outer_repin(
    tmp_path: Path,
) -> None:
    manifest_path = build_bundle(tmp_path)
    graph_path = tmp_path / "rulespec" / "release.jsonld"
    graph = json.loads(graph_path.read_text(encoding="utf-8"))
    graph["@graph"][0]["skos:definition"]["en"] = "Changed graph facts"
    _write_json(graph_path, graph)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["rulespecGraph"] = _descriptor(graph_path, tmp_path)
    _write_json(manifest_path, manifest)

    with pytest.raises(ManagedReleaseError, match="exact Rulespec graph digest"):
        _open_graph_facts(manifest_path)


def test_graph_facts_rejects_dependency_corruption_after_outer_repin(
    tmp_path: Path,
) -> None:
    manifest_path = build_bundle(tmp_path)
    dependency_path = tmp_path / "rulespec" / "rulespec-dependency.json"
    dependency = json.loads(dependency_path.read_text(encoding="utf-8"))
    dependency["localSubstitute"] = True
    _write_json(dependency_path, dependency)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["rulespecDependencyManifest"] = _descriptor(
        dependency_path,
        tmp_path,
    )
    _write_json(manifest_path, manifest)

    with pytest.raises(ManagedReleaseError, match="exact RefSpec-embedded"):
        _open_graph_facts(manifest_path)


def test_graph_facts_rejects_receipt_corruption_after_outer_repin(
    tmp_path: Path,
) -> None:
    manifest_path = build_bundle(tmp_path)
    receipt_path = tmp_path / "validation" / "combined-receipt.json"
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["gateImplementation"]["digest"] = "sha256:" + "0" * 64
    receipt = seal_payload(receipt)
    _write_json(receipt_path, receipt)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["combinedValidationReceipt"] = _descriptor(
        receipt_path,
        tmp_path,
    )
    _write_json(manifest_path, manifest)

    with pytest.raises(ManagedReleaseError, match="installed RefSpec"):
        _open_graph_facts(manifest_path)


def test_graph_facts_rejects_repeated_artifact_path(tmp_path: Path) -> None:
    manifest_path = build_bundle(tmp_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["normalizedTables"][1].update(
        {
            "path": manifest["normalizedTables"][0]["path"],
            "sha256": manifest["normalizedTables"][0]["sha256"],
        }
    )
    _write_json(manifest_path, manifest)

    with pytest.raises(ManagedReleaseError, match="duplicates another"):
        _open_graph_facts(manifest_path)


def test_graph_facts_rejects_missing_or_symlinked_artifact(
    tmp_path: Path,
) -> None:
    manifest_path = build_bundle(tmp_path)
    label_path = tmp_path / "tables" / "concept_labels.parquet"
    saved_path = tmp_path / "tables" / "saved-concept-labels.parquet"
    label_path.replace(saved_path)

    with pytest.raises(ManagedReleaseError, match="missing"):
        _open_graph_facts(manifest_path)

    label_path.symlink_to(saved_path)
    with pytest.raises(ManagedReleaseError, match="symlink"):
        _open_graph_facts(manifest_path)


def test_graph_property_targets_are_indexed_once_per_node(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0
    original = managed_release_module._iri_values

    def counted(value: object) -> tuple[str, ...]:
        nonlocal calls
        calls += 1
        return original(value)

    monkeypatch.setattr(managed_release_module, "_iri_values", counted)
    nodes = {
        "urn:test:a": {
            "@id": "urn:test:a",
            "skos:prefLabel": {"en": ["Alpha", "Alpha"]},
            "skos:broader": ["urn:test:b", "urn:test:b"],
        },
        "urn:test:b": {
            "@id": "urn:test:b",
            "skos:prefLabel": {"en": "Beta"},
            "rkaf:predecessorConceptRelease": "urn:test:release",
        },
    }

    index = managed_release_module._index_graph_property_targets(nodes)

    assert calls == 2 * 7
    assert (
        "urn:test:a",
        "skos:prefLabel",
        "en",
        "Alpha",
    ) in index.language_literals
    assert index.iri_targets[("urn:test:a", "skos:broader")] == {
        "urn:test:b"
    }
    assert index.iri_sequences[
        ("urn:test:b", "rkaf:predecessorConceptRelease")
    ] == ("urn:test:release",)


def test_indexed_expression_identity_includes_semantic_property() -> None:
    common = {
        "reference_resource_release": {
            "id": RELEASE_ID,
            "version": "2026.07.28",
            "digest": RELEASE_DIGEST,
        },
        "registry_import_snapshot": {
            "id": "urn:test:import:subjects:v1",
            "digest": DIGEST_A,
        },
        "distribution_artifact": {
            "id": DISTRIBUTION_ID,
            "digest": DIGEST_A,
        },
        "scheme_iri": SCHEME_ID,
        "member_iri": MEMBER_ID,
        "source_property_or_path": "source/records/0/value",
        "original_literal": "Poultry slaughter inspection",
        "language_tag": "en",
        "datatype_iri": None,
    }

    preferred_id = indexed_expression_id(
        **common,
        semantic_property_iri=("http://www.w3.org/2004/02/skos/core#prefLabel"),
    )
    alternate_id = indexed_expression_id(
        **common,
        semantic_property_iri=("http://www.w3.org/2004/02/skos/core#altLabel"),
    )

    assert preferred_id != alternate_id


def test_bundle_rejects_artifact_tampering(tmp_path: Path) -> None:
    manifest_path = build_bundle(tmp_path)
    corpus_path = tmp_path / "corpus" / "indexed-expressions.jsonl"
    corpus_path.write_bytes(corpus_path.read_bytes() + b" ")

    with pytest.raises(ManagedReleaseError, match="digest mismatch"):
        _open_view(manifest_path)


def test_expression_corpus_record_count_is_an_independent_pin(
    tmp_path: Path,
) -> None:
    manifest_path = build_bundle(tmp_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["indexedExpressionCorpus"]["recordCount"] = 3
    _write_json(manifest_path, manifest)

    with pytest.raises(
        ManagedReleaseError,
        match="recordCount does not match",
    ):
        _open_view(manifest_path)


def test_expression_corpus_identity_tamper_fails_after_file_repin(
    tmp_path: Path,
) -> None:
    manifest_path = build_bundle(tmp_path)
    corpus_path = tmp_path / "corpus" / "indexed-expressions.jsonl"
    records = [
        json.loads(line)
        for line in corpus_path.read_text(encoding="utf-8").splitlines()
    ]
    changed = {
        **records[0],
        "originalLiteral": "Changed without changing expression identity",
    }
    records[0] = seal_payload(changed)
    corpus_path.write_text(
        "".join(
            json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n"
            for record in records
        ),
        encoding="utf-8",
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["indexedExpressionCorpus"].update(_descriptor(corpus_path, tmp_path))
    _write_json(manifest_path, manifest)

    with pytest.raises(
        ManagedReleaseError,
        match="id does not bind its exact identity",
    ):
        _open_view(manifest_path)


def test_expression_corpus_file_order_does_not_change_logical_identity(
    tmp_path: Path,
) -> None:
    manifest_path = build_bundle(tmp_path)
    corpus_path = tmp_path / "corpus" / "indexed-expressions.jsonl"
    lines = corpus_path.read_text(encoding="utf-8").splitlines()
    corpus_path.write_text(
        "\n".join(reversed(lines)) + "\n",
        encoding="utf-8",
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["indexedExpressionCorpus"].update(_descriptor(corpus_path, tmp_path))
    _write_json(manifest_path, manifest)

    view = _open_view(manifest_path)
    assert {item.expression_id for item in view.iter_expressions()} == {
        EXPRESSION_ID,
        ELIGIBILITY_EXPRESSION_ID,
    }


@pytest.mark.parametrize(
    ("table_name", "field", "replacement"),
    [
        (
            "concept_relations",
            "object_concept_iri",
            MEMBER_ID,
        ),
        (
            "concept_event_participants",
            "concept_iri",
            ELIGIBILITY_MEMBER_ID,
        ),
    ],
)
def test_bundle_rejects_normalized_rows_that_do_not_round_trip_to_graph(
    tmp_path: Path,
    table_name: str,
    field: str,
    replacement: str,
) -> None:
    manifest_path = build_bundle(tmp_path)
    table_path = tmp_path / "tables" / f"{table_name}.parquet"
    rows = pq.read_table(table_path).to_pylist()
    rows[0][field] = replacement
    write_parquet_rows(
        table_path,
        columns=tuple(_TABLE_COLUMNS_FOR_TEST[table_name]),
        rows=rows,
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    descriptor = next(
        value for value in manifest["normalizedTables"] if value["name"] == table_name
    )
    descriptor.update(_descriptor(table_path, tmp_path))
    _write_json(manifest_path, manifest)

    with pytest.raises(ManagedReleaseError, match="round-trip"):
        _open_view(manifest_path)


def test_bundle_rejects_normalized_row_with_unpackaged_import_snapshot(
    tmp_path: Path,
) -> None:
    manifest_path = build_bundle(tmp_path)
    table_path = tmp_path / "tables" / "concept_relations.parquet"
    rows = pq.read_table(table_path).to_pylist()
    rows[0]["import_snapshot_id"] = "urn:test:import:missing"
    _replace_normalized_table(
        manifest_path,
        table_name="concept_relations",
        rows=rows,
    )

    with pytest.raises(
        ManagedReleaseError,
        match="import snapshot is absent from the bundle",
    ):
        _open_view(manifest_path)


def test_bundle_rejects_label_role_that_disagrees_with_skos_property(
    tmp_path: Path,
) -> None:
    manifest_path = build_bundle(tmp_path)
    table_path = tmp_path / "tables" / "concept_labels.parquet"
    rows = pq.read_table(table_path).to_pylist()
    rows[0]["label_role"] = "alternate"
    _replace_normalized_table(
        manifest_path,
        table_name="concept_labels",
        rows=rows,
    )

    with pytest.raises(
        ManagedReleaseError,
        match="label role disagrees with its exact SKOS property",
    ):
        _open_view(manifest_path)


def test_bundle_rejects_duplicate_lifecycle_participant_role_ordinal(
    tmp_path: Path,
) -> None:
    manifest_path = build_bundle(tmp_path)
    table_path = tmp_path / "tables" / "concept_event_participants.parquet"
    rows = pq.read_table(table_path).to_pylist()
    rows.append(dict(rows[0]))
    _replace_normalized_table(
        manifest_path,
        table_name="concept_event_participants",
        rows=rows,
    )

    with pytest.raises(
        ManagedReleaseError,
        match="repeats an event role ordinal",
    ):
        _open_view(manifest_path)


def test_bundle_rejects_relation_lineage_that_disagrees_with_import_snapshot(
    tmp_path: Path,
) -> None:
    manifest_path = build_bundle(tmp_path)
    table_path = tmp_path / "tables" / "concept_relations.parquet"
    rows = pq.read_table(table_path).to_pylist()
    rows[0]["distribution_artifact_id"] = CONFORMANCE_RESULT_ID
    _replace_normalized_table(
        manifest_path,
        table_name="concept_relations",
        rows=rows,
    )

    with pytest.raises(
        ManagedReleaseError,
        match="import, release, and distribution lineage disagree",
    ):
        _open_view(manifest_path)


def test_bundle_rejects_lifecycle_participant_concept_type_mismatch(
    tmp_path: Path,
) -> None:
    manifest_path = build_bundle(tmp_path)
    table_path = tmp_path / "tables" / "concept_event_participants.parquet"
    rows = pq.read_table(table_path).to_pylist()
    rows[0]["concept_type_iri"] = "http://www.w3.org/2004/02/skos/core#Concept"
    _replace_normalized_table(
        manifest_path,
        table_name="concept_event_participants",
        rows=rows,
    )

    with pytest.raises(
        ManagedReleaseError,
        match="concept type does not match the exact member graph",
    ):
        _open_view(manifest_path)


def test_bundle_requires_the_externally_selected_manifest_digest(
    tmp_path: Path,
) -> None:
    manifest_path = build_bundle(tmp_path)

    with pytest.raises(ManagedReleaseError, match="manifest digest mismatch"):
        ManagedReleaseView.open(
            manifest_path,
            expected_manifest_digest=DIGEST_B,
        )


@pytest.mark.parametrize(
    "unsafe_path",
    [
        "/tmp/publication.json",
        "../publication.json",
        "C:/publication.json",
        "https://example.test/publication.json",
    ],
)
def test_bundle_rejects_non_relative_or_traversing_paths(
    tmp_path: Path,
    unsafe_path: str,
) -> None:
    manifest_path = build_bundle(tmp_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["publicationReleaseManifest"]["path"] = unsafe_path
    _write_json(manifest_path, manifest)

    with pytest.raises(ManagedReleaseError, match="relative"):
        _open_view(manifest_path)


def test_bundle_rejects_mutable_path_without_digest(tmp_path: Path) -> None:
    manifest_path = build_bundle(tmp_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    del manifest["rulespecGraph"]["sha256"]
    _write_json(manifest_path, manifest)

    with pytest.raises(ManagedReleaseError, match="immutable SHA-256"):
        _open_view(manifest_path)


def test_bundle_rejects_missing_artifact(tmp_path: Path) -> None:
    manifest_path = build_bundle(tmp_path)
    (tmp_path / "tables" / "concept_labels.parquet").unlink()

    with pytest.raises(ManagedReleaseError, match="missing"):
        _open_view(manifest_path)


def test_bundle_rejects_ref_record_reference_mismatch(tmp_path: Path) -> None:
    manifest_path = build_bundle(tmp_path)
    publication_path = tmp_path / "records" / "publication.json"
    publication = json.loads(publication_path.read_text(encoding="utf-8"))
    publication["runReceipt"]["digest"] = DIGEST_A
    publication = seal_payload(publication)
    _write_json(publication_path, publication)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["publicationReleaseManifest"] = _descriptor(
        publication_path,
        tmp_path,
    )
    _write_json(manifest_path, manifest)

    with pytest.raises(ManagedReleaseError, match="digest-mismatched"):
        _open_view(manifest_path)


def test_bundle_rejects_digest_valid_but_schema_invalid_publication(
    tmp_path: Path,
) -> None:
    manifest_path = build_bundle(tmp_path)
    publication_path = tmp_path / "records" / "publication.json"
    publication = json.loads(publication_path.read_text(encoding="utf-8"))
    del publication["refspecVersion"]
    publication = seal_payload(publication)
    _write_json(publication_path, publication)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["publicationReleaseManifest"] = _descriptor(
        publication_path,
        tmp_path,
    )
    _write_json(manifest_path, manifest)

    with pytest.raises(
        ManagedReleaseError,
        match="fails REF JSON Binding 1.0",
    ):
        _open_view(manifest_path)


def test_bundle_rejects_expression_and_lookup_identity_conflation(
    tmp_path: Path,
) -> None:
    manifest_path = build_bundle(tmp_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["lookupIndexManifest"] = dict(
        manifest["indexedExpressionCorpus"]["expressionCorpusSnapshot"]
    )
    _write_json(manifest_path, manifest)

    with pytest.raises(ManagedReleaseError, match="conflates"):
        _open_view(manifest_path)


def test_bundle_rejects_embedded_physical_lookup_index(tmp_path: Path) -> None:
    manifest_path = build_bundle(tmp_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["lookupIndexManifest"] = {
        "id": "urn:test:lookup-index:subjects:v1",
        "digest": DIGEST_B,
    }
    _write_json(manifest_path, manifest)

    with pytest.raises(ManagedReleaseError, match="consumer configuration"):
        _open_view(manifest_path)


def test_bundle_rejects_nonpassing_combined_validation_receipt(
    tmp_path: Path,
) -> None:
    manifest_path = build_bundle(tmp_path)
    receipt_path = tmp_path / "validation" / "combined-receipt.json"
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["verdicts"]["rulespecConformance"] = "fail"
    receipt = seal_payload(receipt)
    _write_json(receipt_path, receipt)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["combinedValidationReceipt"] = _descriptor(
        receipt_path,
        tmp_path,
    )
    _write_json(manifest_path, manifest)

    with pytest.raises(
        ManagedReleaseError,
        match="combined validation receipt fails REF JSON Binding 1.0",
    ):
        _open_view(manifest_path)


def test_bundle_rejects_combined_receipt_with_incomplete_ref_coverage(
    tmp_path: Path,
) -> None:
    manifest_path = build_bundle(tmp_path)
    receipt_path = tmp_path / "validation" / "combined-receipt.json"
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["refRecordDigests"] = [
        reference
        for reference in receipt["refRecordDigests"]
        if reference["id"] != IMPORT_ID
    ]
    receipt = seal_payload(receipt)
    _write_json(receipt_path, receipt)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["combinedValidationReceipt"] = _descriptor(
        receipt_path,
        tmp_path,
    )
    _write_json(manifest_path, manifest)

    with pytest.raises(ManagedReleaseError, match="exactly cover"):
        _open_view(manifest_path)


def test_bundle_rejects_self_consistent_alternate_rulespec_dependency(
    tmp_path: Path,
) -> None:
    manifest_path = build_bundle(tmp_path)
    dependency_path = tmp_path / "rulespec" / "rulespec-dependency.json"
    dependency = json.loads(dependency_path.read_text(encoding="utf-8"))
    dependency["localSubstitute"] = True
    _write_json(dependency_path, dependency)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["rulespecDependencyManifest"] = _descriptor(
        dependency_path,
        tmp_path,
    )
    _write_json(manifest_path, manifest)

    with pytest.raises(ManagedReleaseError, match="exact RefSpec-embedded"):
        _open_view(manifest_path)


def test_bundle_rejects_receipt_claiming_another_gate(
    tmp_path: Path,
) -> None:
    manifest_path = build_bundle(tmp_path)
    receipt_path = tmp_path / "validation" / "combined-receipt.json"
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["gateImplementation"]["digest"] = "sha256:" + "0" * 64
    receipt = seal_payload(receipt)
    _write_json(receipt_path, receipt)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["combinedValidationReceipt"] = _descriptor(
        receipt_path,
        tmp_path,
    )
    _write_json(manifest_path, manifest)

    with pytest.raises(ManagedReleaseError, match="installed RefSpec"):
        _open_view(manifest_path)


def test_bundle_rejects_uncovered_authorization_evaluation(
    tmp_path: Path,
) -> None:
    manifest_path = build_bundle(tmp_path)
    receipt_path = tmp_path / "validation" / "combined-receipt.json"
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    governance_id = "urn:test:deployment:not-packaged"
    receipt["authorizationEvaluations"] = [
        {
            "governanceRecord": {
                "id": governance_id,
                "digest": DIGEST_A,
            },
            "behaviorTest": {
                "id": (
                    "urn:ref:behavior-test:governance-authorization:"
                    + hashlib.sha256(governance_id.encode("utf-8")).hexdigest()
                ),
                "digest": DIGEST_B,
            },
            "inputGraph": receipt["rulespecGraph"],
            "behaviorContract": "rkaf:UsageEligibilityReducer",
            "subjectAssertion": MEMBER_ID,
            "evaluationScope": "urn:test:environment:production",
            "evaluationTime": "2026-07-29T17:01:00Z",
            "minimumUsageEligibility": "rkaf:localOperationalUse",
            "effectiveUsageEligibility": "rkaf:localOperationalUse",
            "outputDigest": canonical_value_digest(
                {
                    "byScope": {
                        "urn:test:environment:production": ("rkaf:localOperationalUse")
                    }
                }
            ),
            "runtime": receipt["rulespecBehaviorRuntime"],
            "result": "pass",
        }
    ]
    receipt = seal_payload(receipt)
    _write_json(receipt_path, receipt)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["combinedValidationReceipt"] = _descriptor(
        receipt_path,
        tmp_path,
    )
    _write_json(manifest_path, manifest)

    with pytest.raises(
        ManagedReleaseError,
        match="exactly cover every selected deployment",
    ):
        _open_view(manifest_path)
