"""Realistic R5-history/R6-selected managed-release tests for ELSST."""

from __future__ import annotations

import gc
import hashlib
import json
import os
import resource
import shutil
import sys
import time
from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path

import pytest

from refspec import ManagedReleaseError, ManagedReleaseView
from refspec.registry import elsst_managed_release
from refspec.registry.elsst_acquisition import (
    ELSST_R5,
    ELSST_R6,
    AcquiredElsstSource,
    ElsstReleaseSource,
    acquire_elsst_release,
)
from refspec.registry.elsst_managed_release import (
    ElsstCandidateGovernance,
    ElsstManagedRelease,
    ElsstManagedReleaseError,
    build_elsst_managed_release,
)
from refspec.storage import canonical_json

REFSPEC_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RULESPEC_DIR = REFSPEC_ROOT.parents[1] / "rulespec"
FIXTURE_DIR = Path(__file__).parent / "fixtures"
SCALE_EVIDENCE_PATH = (
    REFSPEC_ROOT
    / "research"
    / "evidence"
    / "elsst-r5-r6-managed-release-2026-07-29"
    / "evidence.json"
)
R5_FIXTURE = FIXTURE_DIR / "elsst-projection-mini-r5.ttl"
R6_FIXTURE = FIXTURE_DIR / "elsst-projection-mini-r6.ttl"

RECORDED_AT = "2026-07-29T20:00:00Z"
RECORDED_BY = "urn:test:agent:elsst-managed-release"
R6_RETIRED = (
    "https://elsst.cessda.eu/id/6/"
    "05fd5779-69ad-4872-ae25-a8c400b73e10"
)
R5_RETIRED = R6_RETIRED.replace("/id/6/", "/id/5/")
R6_SUCCESSOR = (
    "https://elsst.cessda.eu/id/6/"
    "4ae8f7d8-3ff9-4258-9dc8-7cf9c345dd6f"
)
R5_SUCCESSOR_VERSION = (
    "https://elsst.cessda.eu/id/5/"
    "4ae8f7d8-3ff9-4258-9dc8-7cf9c345dd6f"
)
IS_VERSION_OF = "http://purl.org/dc/terms/isVersionOf"
PRIOR_VERSION = "http://www.w3.org/2002/07/owl#priorVersion"
TEST_R5_RELEASE_IRI = "urn:test:elsst:release:r5"
TEST_R6_RELEASE_IRI = "urn:test:elsst:release:r6"
# The first complete native-source run established a 343-second,
# 2,978,086,912-byte baseline. These opt-in experimental ceilings leave
# enough host-variance margin to catch material regressions without
# misclassifying a complete semantic proof as a release failure.
REAL_GATE_MAX_WALL_SECONDS = 420.0
REAL_GATE_MAX_PEAK_MEMORY_BYTES = 7 * 1024**3 // 2


def _process_peak_memory_bytes() -> int:
    peak = int(
        resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    )
    return peak if sys.platform == "darwin" else peak * 1024


@pytest.fixture
def rulespec_dir() -> Path:
    configured = os.environ.get("RULESPEC_DIR")
    path = (
        Path(configured).resolve()
        if configured
        else DEFAULT_RULESPEC_DIR.resolve()
    )
    if not (path / ".git").exists():
        pytest.skip(
            f"live Rulespec checkout is unavailable: {path}"
        )
    return path


def _fixture_release(
    path: Path,
    *,
    version: str,
    release_iri: str,
    scheme_iri: str,
) -> ElsstReleaseSource:
    payload = path.read_bytes()
    return ElsstReleaseSource(
        version=version,
        release_iri=release_iri,
        concept_scheme_iri=scheme_iri,
        source_url=f"https://example.test/ELSST_R{version}.ttl",
        expected_sha256=(
            "sha256:" + hashlib.sha256(payload).hexdigest()
        ),
        expected_byte_length=len(payload),
        filename=path.name,
    )


def _fixture_pair(
    store_dir: Path,
) -> tuple[AcquiredElsstSource, AcquiredElsstSource]:
    previous_source = _fixture_release(
        R5_FIXTURE,
        version="5",
        release_iri=TEST_R5_RELEASE_IRI,
        scheme_iri=ELSST_R5.concept_scheme_iri,
    )
    current_source = _fixture_release(
        R6_FIXTURE,
        version="6",
        release_iri=TEST_R6_RELEASE_IRI,
        scheme_iri=ELSST_R6.concept_scheme_iri,
    )
    return (
        acquire_elsst_release(
            previous_source,
            store_dir / "r5",
            source_path=R5_FIXTURE,
        ),
        acquire_elsst_release(
            current_source,
            store_dir / "r6",
            source_path=R6_FIXTURE,
        ),
    )


def _governance() -> ElsstCandidateGovernance:
    return ElsstCandidateGovernance(
        actor_iri="urn:test:actor:elsst-local-reviewer",
        organization_iri="urn:test:organization:spicy-regs",
        effective_at=RECORDED_AT,
    )


@pytest.fixture(scope="module")
def managed_fixture(
    tmp_path_factory: pytest.TempPathFactory,
) -> tuple[ElsstManagedRelease, Path]:
    rulespec_dir = DEFAULT_RULESPEC_DIR.resolve()
    if not (rulespec_dir / ".git").exists():
        pytest.skip(
            f"live Rulespec checkout is unavailable: {rulespec_dir}"
        )
    sources = _fixture_pair(
        tmp_path_factory.mktemp("elsst-acquired-sources")
    )
    managed = build_elsst_managed_release(
        *sources,
        rulespec_root=rulespec_dir,
        recorded_at=RECORDED_AT,
        recorded_by=RECORDED_BY,
        governance=_governance(),
    )
    output = tmp_path_factory.mktemp("elsst-managed-release")
    managed.bundle.write_to(output)
    return managed, output / "managed-release-bundle.json"


def _manifest_digest(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _scale_evidence() -> dict:
    return json.loads(SCALE_EVIDENCE_PATH.read_text(encoding="utf-8"))


def test_scale_evidence_matches_exact_sources_and_gate_budget() -> None:
    evidence = _scale_evidence()
    assert evidence["evidenceType"] == (
        "ElsstR5R6ManagedReleaseScaleProof"
    )
    assert evidence["sources"]["r5"] == {
        "id": ELSST_R5.source_url,
        "release": ELSST_R5.release_iri,
        "version": ELSST_R5.version,
        "byteLength": ELSST_R5.expected_byte_length,
        "digest": ELSST_R5.expected_sha256,
        "releaseDigest": (
            "sha256:"
            "7b3a045d1068f1d5f27ed81739fd715ad9e039662278a0d37e1b6ff530d1bbd5"
        ),
        "importSnapshot": {
            "id": (
                "urn:ref:elsst:registry-import:r5:native-skos-v1:"
                "4d76bf751f0133f7740cdf36c9cb02ecef59157bf59104658d91225f4b54d399"
            ),
            "digest": (
                "sha256:"
                "c6cbaaf05664a8b088bf7b44a5c40b8c06deb7508f0157a7e879efd26c2e24b1"
            ),
        },
    }
    assert evidence["sources"]["r6"] == {
        "id": ELSST_R6.source_url,
        "release": ELSST_R6.release_iri,
        "version": ELSST_R6.version,
        "byteLength": ELSST_R6.expected_byte_length,
        "digest": ELSST_R6.expected_sha256,
        "releaseDigest": (
            "sha256:"
            "a75f6dd4679a712fb494ee7ae5cc8ba48f0eb353047e9a3b034cb82e917deea2"
        ),
        "importSnapshot": {
            "id": (
                "urn:ref:elsst:registry-import:r6:native-skos-v1:"
                "4d76bf751f0133f7740cdf36c9cb02ecef59157bf59104658d91225f4b54d399"
            ),
            "digest": (
                "sha256:"
                "a6089946dca4b5314b6cc6164c60691c8e73769b4fd41a65dda473536d153af5"
            ),
        },
    }
    assert evidence["performance"]["gate"] == {
        "maxWallSeconds": REAL_GATE_MAX_WALL_SECONDS,
        "maxPeakMemoryBytes": REAL_GATE_MAX_PEAK_MEMORY_BYTES,
    }
    assert evidence["managedRelease"]["counts"] == {
        "releases": 2,
        "concepts": 6905,
        "registryImports": 2,
        "coverageReports": 2,
        "deploymentSelections": 1,
        "indexedExpressions": 308_639,
        "normalizedLabels": 176_664,
        "normalizedRelations": 24_844,
        "lifecycleParticipants": 6,
    }


def test_managed_bundle_packages_both_releases_and_only_selects_r6(
    managed_fixture: tuple[ElsstManagedRelease, Path],
) -> None:
    managed, manifest_path = managed_fixture

    assert managed.expression_count == 39
    assert managed.label_count == 30
    assert managed.relation_count == 4
    assert managed.participant_count == 2
    assert len(managed.import_records) == 2
    assert len(managed.coverage_records) == 2
    assert (
        managed.selected_deployment["referenceResourceRelease"]["id"]
        == TEST_R6_RELEASE_IRI
    )
    assert {
        row["referenceResourceRelease"]["id"]
        for row in next(
            record
            for record in managed.bundle.ref_records
            if record.get("type") == "urn:ref:type:OutputProfile"
        )["releasePermissions"]
    } == {
        TEST_R5_RELEASE_IRI,
        TEST_R6_RELEASE_IRI,
    }
    record_paths = [
        path
        for path in managed.bundle.artifact_bytes()
        if path.startswith("records/registryimportsnapshot-")
    ]
    assert len(record_paths) == 2
    assert manifest_path.is_file()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    corpus_descriptor = manifest["indexedExpressionCorpus"]
    assert corpus_descriptor["recordCount"] == managed.expression_count
    assert corpus_descriptor["schemaVersion"] == (
        "ref-indexed-expression-corpus-1.0"
    )
    assert corpus_descriptor["canonicalIdentityDigest"] == (
        corpus_descriptor["expressionCorpusSnapshot"]["digest"]
    )
    combined_receipt = json.loads(
        (
            manifest_path.parent
            / manifest["combinedValidationReceipt"]["path"]
        ).read_text(encoding="utf-8")
    )
    receipt_record_ids = {
        reference["id"]
        for reference in combined_receipt["refRecordDigests"]
    }
    assert not receipt_record_ids.intersection(
        expression["id"]
        for expression in managed.bundle.indexed_expressions
    )
    assert receipt_record_ids == {
        managed.bundle.publication_release_manifest["id"],
        *(
            record["id"]
            for record in managed.bundle.ref_records
        ),
    }
    r6_import = managed.import_records[1]
    assert managed.selected_deployment["rightsAssessment"] == (
        r6_import["rightsAssessment"]
    )
    assert managed.selected_deployment["adoptedPolicyRefs"] == (
        r6_import["adoptedPolicyRefs"]
    )
    for report in managed.coverage_records:
        rows = {
            row["feature"]: row
            for row in report["features"]
        }
        assert set(rows) == {
            "labels",
            "languages",
            "notation",
            "notes",
            "hierarchy",
            "associativeRelations",
            "mappings",
            "status",
            "replacements",
            "identifiers",
            "membership",
        }
        assert rows["labels"]["sourceObservedCount"] > 0
        assert rows["identifiers"]["sourceObservedCount"] > 0
        assert all(
            row["sourceObservedCount"]
            == row["parsedCount"]
            == row["indexedCount"]
            for row in rows.values()
        )
        assert all(
            row["sourceObservedDigest"]
            == row["parsedDigest"]
            == row["indexedDigest"]
            for row in rows.values()
        )


def test_managed_release_rejects_an_omitted_indexed_expression(
    tmp_path: Path,
    rulespec_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = elsst_managed_release._build_expressions
    original_raw_census = (
        elsst_managed_release.census_raw_elsst_turtle
    )
    original_parsed_census = (
        elsst_managed_release.census_parsed_elsst
    )
    census_events: list[str] = []

    def record_raw_census(*args: object, **kwargs: object):
        census_events.append("raw")
        return original_raw_census(*args, **kwargs)

    def record_parsed_census(*args: object, **kwargs: object):
        census_events.append("parsed")
        return original_parsed_census(*args, **kwargs)

    def omit_one_note_expression(**kwargs: object):
        assert census_events == [
            "raw",
            "parsed",
            "raw",
            "parsed",
        ]
        expressions, identities = original(**kwargs)
        omitted = False
        retained = []
        for record in expressions:
            release = record.get("referenceResourceRelease")
            is_current_note = (
                isinstance(release, Mapping)
                and release.get("id") == TEST_R6_RELEASE_IRI
                and record.get("semanticProperty")
                == "http://www.w3.org/2004/02/skos/core#definition"
            )
            if is_current_note and not omitted:
                omitted = True
                continue
            retained.append(record)
        assert omitted
        return tuple(retained), identities

    monkeypatch.setattr(
        elsst_managed_release,
        "_build_expressions",
        omit_one_note_expression,
    )
    monkeypatch.setattr(
        elsst_managed_release,
        "census_raw_elsst_turtle",
        record_raw_census,
    )
    monkeypatch.setattr(
        elsst_managed_release,
        "census_parsed_elsst",
        record_parsed_census,
    )

    with pytest.raises(
        ElsstManagedReleaseError,
        match=r"notes parsedToIndexed missing=1",
    ):
        build_elsst_managed_release(
            *_fixture_pair(tmp_path / "acquired"),
            rulespec_root=rulespec_dir,
            recorded_at=RECORDED_AT,
            recorded_by=RECORDED_BY,
            governance=_governance(),
        )


def test_managed_view_retrieves_exact_verified_turtle_bytes(
    managed_fixture: tuple[ElsstManagedRelease, Path],
) -> None:
    managed, manifest_path = managed_fixture
    view = ManagedReleaseView.open(
        manifest_path,
        expected_manifest_digest=_manifest_digest(manifest_path),
    )

    assert view.source_artifact_bytes(
        managed.projection.distribution_iris[0]
    ) == R5_FIXTURE.read_bytes()
    assert view.source_artifact_bytes(
        managed.projection.distribution_iris[1]
    ) == R6_FIXTURE.read_bytes()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert set(manifest["sourceArtifacts"]) == set(
        managed.projection.distribution_iris
    )
    captures = [
        record
        for record in managed.bundle.ref_records
        if record.get("type") == "urn:ref:type:Capture"
    ]
    assert {
        record["storageReference"] for record in captures
    } == set(manifest["sourceArtifacts"])


@pytest.mark.parametrize(
    "failure_mode",
    ["missing", "tampered", "length", "symlink", "ambiguous"],
)
def test_managed_view_rejects_invalid_source_bytes(
    managed_fixture: tuple[ElsstManagedRelease, Path],
    tmp_path: Path,
    failure_mode: str,
) -> None:
    _managed, manifest_path = managed_fixture
    copied = tmp_path / "bundle"
    shutil.copytree(manifest_path.parent, copied)
    copied_manifest = copied / manifest_path.name
    manifest = json.loads(
        copied_manifest.read_text(encoding="utf-8")
    )
    descriptor = next(iter(manifest["sourceArtifacts"].values()))
    source_path = copied / descriptor["path"]
    if failure_mode == "missing":
        source_path.unlink()
    elif failure_mode == "tampered":
        source_path.write_bytes(source_path.read_bytes() + b"\n# tampered\n")
    elif failure_mode == "length":
        descriptor["byteLength"] += 1
        copied_manifest.write_text(
            canonical_json(manifest) + "\n",
            encoding="utf-8",
        )
    elif failure_mode == "symlink":
        source_target = source_path.with_suffix(".retained")
        source_path.rename(source_target)
        source_path.symlink_to(source_target)
    else:
        manifest["sourceArtifacts"][
            "urn:test:elsst:ambiguous-source"
        ] = dict(descriptor)
        copied_manifest.write_text(
            canonical_json(manifest) + "\n",
            encoding="utf-8",
        )

    with pytest.raises(
        ManagedReleaseError,
        match=(
            "missing|digest mismatch|byte length mismatch|symlink|"
            "duplicates another bundle artifact"
        ),
    ):
        ManagedReleaseView.open(
            copied_manifest,
            expected_manifest_digest=_manifest_digest(
                copied_manifest
            ),
        )


def test_managed_view_preserves_multilingual_history_and_current_boundary(
    managed_fixture: tuple[ElsstManagedRelease, Path],
) -> None:
    _managed, manifest_path = managed_fixture
    view = ManagedReleaseView.open(
        manifest_path,
        expected_manifest_digest=_manifest_digest(manifest_path),
    )
    permission = view.require_candidate_use(
        facet_iri="urn:ref:facet:general-subject",
        assignment_role_iri=(
            "https://rulespec.org/ns/v1#assignmentPrimary"
        ),
        resource_route="document",
    )

    assert permission.reference_resource_release["id"] == (
        TEST_R6_RELEASE_IRI
    )
    assert view.lookup_member(R5_SUCCESSOR_VERSION) is not None
    assert view.lookup_member(R6_SUCCESSOR) is not None
    successor_candidates = tuple(
        view.iter_candidate_expressions(
            facet_iri="urn:ref:facet:general-subject",
            assignment_role_iri=(
                "https://rulespec.org/ns/v1#assignmentPrimary"
            ),
            resource_route="document",
            member_iri=R6_SUCCESSOR,
        )
    )
    preferred = {
        (item.language_tag, item.original_literal)
        for item in successor_candidates
        if item.label_role == "preferred"
    }
    assert {
        ("el", "ΑΡΧΗΓΟΣ ΝΟΙΚΟΚΥΡΙΟΥ"),
        ("en", "HEADS OF HOUSEHOLD"),
        ("es", "CABEZAS DE HOGAR"),
    } <= preferred

    assert tuple(view.iter_expressions(member_iri=R6_RETIRED))
    assert not tuple(
        view.iter_candidate_expressions(
            facet_iri="urn:ref:facet:general-subject",
            assignment_role_iri=(
                "https://rulespec.org/ns/v1#assignmentPrimary"
            ),
            resource_route="document",
            member_iri=R6_RETIRED,
        )
    )
    assert len(tuple(view.iter_relations())) == 4
    participants = tuple(view.iter_lifecycle_participants())
    assert {
        (row.participant_role, row.release_iri)
        for row in participants
    } == {
        ("predecessor", TEST_R5_RELEASE_IRI),
        ("successor", TEST_R6_RELEASE_IRI),
    }


def test_managed_view_exposes_exact_native_identity_without_new_version_model(
    managed_fixture: tuple[ElsstManagedRelease, Path],
) -> None:
    _managed, manifest_path = managed_fixture
    view = ManagedReleaseView.open(
        manifest_path,
        expected_manifest_digest=_manifest_digest(manifest_path),
    )

    links = tuple(
        view.iter_identity_links(member_iri=R6_SUCCESSOR)
    )
    assert any(
        link.predicate_iri == IS_VERSION_OF
        and link.object_iri
        == (
            "https://elsst.cessda.eu/id/"
            "4ae8f7d8-3ff9-4258-9dc8-7cf9c345dd6f"
        )
        and link.object_release_iri is None
        for link in links
    )
    assert any(
        link.predicate_iri == PRIOR_VERSION
        and link.object_iri == R5_SUCCESSOR_VERSION
        and link.object_release_iri == TEST_R5_RELEASE_IRI
        for link in links
    )


def test_elsst_license_is_recorded_but_does_not_limit_experimental_use(
    managed_fixture: tuple[ElsstManagedRelease, Path],
) -> None:
    managed, _manifest_path = managed_fixture
    rights = next(
        record
        for record in managed.bundle.ref_records
        if record.get("type") == "urn:ref:type:RightsAssessment"
    )

    assert set(rights["permissions"].values()) == {"permitted"}
    assert "does not use this record as a runtime gate" in (
        rights["purpose"]
    )
    assert managed.selected_deployment["selectionState"] == "selected"


@pytest.mark.parametrize("failure_mode", ["missing", "tampered"])
def test_build_rejects_missing_or_tampered_acquired_source(
    rulespec_dir: Path,
    tmp_path: Path,
    failure_mode: str,
) -> None:
    previous, current = _fixture_pair(tmp_path / "source-store")
    if failure_mode == "missing":
        previous.path.unlink()
    else:
        previous.path.write_bytes(
            previous.path.read_bytes() + b"\n# tampered\n"
        )

    with pytest.raises(
        ElsstManagedReleaseError,
        match="intact verified acquired source",
    ):
        build_elsst_managed_release(
            previous,
            current,
            rulespec_root=rulespec_dir,
            recorded_at=RECORDED_AT,
            recorded_by=RECORDED_BY,
            governance=_governance(),
        )


def test_build_rejects_canonical_release_iri_with_fixture_descriptor(
    rulespec_dir: Path,
    tmp_path: Path,
) -> None:
    forged_descriptor = _fixture_release(
        R5_FIXTURE,
        version="5",
        release_iri=ELSST_R5.release_iri,
        scheme_iri=ELSST_R5.concept_scheme_iri,
    )
    forged_previous = acquire_elsst_release(
        forged_descriptor,
        tmp_path / "forged-r5",
        source_path=R5_FIXTURE,
    )
    _previous, current = _fixture_pair(
        tmp_path / "valid-fixture-pair"
    )

    with pytest.raises(
        ElsstManagedReleaseError,
        match="requires the exact canonical release descriptor",
    ):
        build_elsst_managed_release(
            forged_previous,
            current,
            rulespec_root=rulespec_dir,
            recorded_at=RECORDED_AT,
            recorded_by=RECORDED_BY,
            governance=_governance(),
        )


def _generated_ids(managed: ElsstManagedRelease) -> set[str]:
    record_ids = {
        str(record["id"])
        for record in (
            *managed.bundle.ref_records,
            managed.bundle.publication_release_manifest,
            managed.bundle.combined_validation_receipt,
        )
    }
    graph_ids = {
        str(node["@id"])
        for node in managed.bundle.rulespec_graph["@graph"]
        if isinstance(node, dict)
        and isinstance(node.get("@id"), str)
        and str(node["@id"]).startswith("urn:ref:elsst:")
    }
    return record_ids | graph_ids


def test_build_identity_prevents_timestamp_and_governance_id_collisions(
    managed_fixture: tuple[ElsstManagedRelease, Path],
    rulespec_dir: Path,
    tmp_path: Path,
) -> None:
    first, _manifest_path = managed_fixture
    sources = _fixture_pair(tmp_path / "source-store")
    changed_at = "2026-07-29T20:01:00Z"
    second = build_elsst_managed_release(
        *sources,
        rulespec_root=rulespec_dir,
        recorded_at=changed_at,
        recorded_by=RECORDED_BY,
        governance=replace(
            _governance(),
            actor_iri="urn:test:actor:second-elsst-reviewer",
            effective_at=changed_at,
        ),
    )

    assert _generated_ids(first)
    assert _generated_ids(first).isdisjoint(_generated_ids(second))
    assert [
        (item["id"], item["version"])
        for item in first.release_references
    ] == [
        (item["id"], item["version"])
        for item in second.release_references
    ]


@pytest.mark.parametrize(
    ("authored_status", "candidate_expected"),
    [("true", False), ("false", True)],
)
def test_native_boolean_status_controls_candidates_without_label_synthesis(
    rulespec_dir: Path,
    tmp_path: Path,
    authored_status: str,
    candidate_expected: bool,
) -> None:
    previous_text = R5_FIXTURE.read_text(encoding="utf-8")
    previous_text = previous_text.replace(
        f"<{R5_RETIRED}> a skos:Concept ;",
        (
            f"<{R5_RETIRED}> a skos:Concept ;\n"
            f"    owl:deprecated {authored_status} ;"
        ),
        1,
    )
    current_text = R6_FIXTURE.read_text(encoding="utf-8").replace(
        "owl:deprecated true",
        f"owl:deprecated {authored_status}",
        1,
    )
    previous_path = tmp_path / "status-r5.ttl"
    current_path = tmp_path / "status-r6.ttl"
    previous_path.write_text(previous_text, encoding="utf-8")
    current_path.write_text(current_text, encoding="utf-8")
    previous_descriptor = _fixture_release(
        previous_path,
        version="5",
        release_iri=TEST_R5_RELEASE_IRI,
        scheme_iri=ELSST_R5.concept_scheme_iri,
    )
    current_descriptor = _fixture_release(
        current_path,
        version="6",
        release_iri=TEST_R6_RELEASE_IRI,
        scheme_iri=ELSST_R6.concept_scheme_iri,
    )
    sources = (
        acquire_elsst_release(
            previous_descriptor,
            tmp_path / "source-store-r5",
            source_path=previous_path,
        ),
        acquire_elsst_release(
            current_descriptor,
            tmp_path / "source-store-r6",
            source_path=current_path,
        ),
    )
    managed = build_elsst_managed_release(
        *sources,
        rulespec_root=rulespec_dir,
        recorded_at=RECORDED_AT,
        recorded_by=RECORDED_BY,
        governance=_governance(),
    )
    assert managed.projection.lifecycle_transitions == ()
    node = next(
        item
        for item in managed.bundle.rulespec_graph["@graph"]
        if item.get("@id") == R6_RETIRED
    )
    assert node["owl:deprecated"] == authored_status
    output = tmp_path / "bundle"
    managed.bundle.write_to(output)
    manifest_path = output / "managed-release-bundle.json"
    view = ManagedReleaseView.open(
        manifest_path,
        expected_manifest_digest=_manifest_digest(manifest_path),
    )
    raw = tuple(view.iter_expressions(member_iri=R6_RETIRED))
    assert raw
    assert {
        item.source_status
        for item in raw
        if item.source_status is not None
    } == {"notDeclared"}
    candidates = tuple(
        view.iter_candidate_expressions(
            facet_iri="urn:ref:facet:general-subject",
            assignment_role_iri=(
                "https://rulespec.org/ns/v1#assignmentPrimary"
            ),
            resource_route="document",
            member_iri=R6_RETIRED,
        )
    )
    assert bool(candidates) is candidate_expected


def test_opt_in_full_r5_r6_managed_release_opens_and_selects_current_r6(
    rulespec_dir: Path,
    tmp_path: Path,
    request: pytest.FixtureRequest,
) -> None:
    r5_path = os.environ.get("REFSPEC_ELSST_R5_PATH")
    r6_path = os.environ.get("REFSPEC_ELSST_R6_PATH")
    if r5_path is None or r6_path is None:
        pytest.skip(
            "set both REFSPEC_ELSST_R5_PATH and "
            "REFSPEC_ELSST_R6_PATH"
        )
    gate_started = time.perf_counter()
    sources = (
        acquire_elsst_release(
            ELSST_R5,
            tmp_path / "source-store-r5",
            source_path=Path(r5_path),
        ),
        acquire_elsst_release(
            ELSST_R6,
            tmp_path / "source-store-r6",
            source_path=Path(r6_path),
        ),
    )

    managed = build_elsst_managed_release(
        *sources,
        rulespec_root=rulespec_dir,
        recorded_at=RECORDED_AT,
        recorded_by=RECORDED_BY,
        governance=_governance(),
    )
    counts = (
        managed.expression_count,
        managed.label_count,
        managed.relation_count,
        managed.participant_count,
    )
    coverage_digests = tuple(
        record["canonicalPayloadDigest"]
        for record in managed.coverage_records
    )
    selection_digest = managed.selected_deployment[
        "canonicalPayloadDigest"
    ]
    managed.bundle.write_to(tmp_path)
    manifest_path = tmp_path / "managed-release-bundle.json"
    manifest = json.loads(
        manifest_path.read_text(encoding="utf-8")
    )
    del managed
    del sources
    gc.collect()
    view = ManagedReleaseView.open(
        manifest_path,
        expected_manifest_digest=_manifest_digest(manifest_path),
    )

    assert counts == (308_639, 176_664, 24_844, 6)
    evidence = _scale_evidence()
    assert _manifest_digest(manifest_path) == (
        evidence["managedRelease"]["bundleManifestDigest"]
    )
    assert manifest["indexedExpressionCorpus"] == {
        "canonicalIdentityDigest": (
            evidence["managedRelease"]["expressionCorpus"][
                "logicalDigest"
            ]
        ),
        "expressionCorpusSnapshot": {
            "digest": (
                evidence["managedRelease"]["expressionCorpus"][
                    "logicalDigest"
                ]
            ),
            "id": (
                evidence["managedRelease"]["expressionCorpus"][
                    "id"
                ]
            ),
        },
        "path": "corpus/indexed-expressions.jsonl",
        "recordCount": 308_639,
        "schemaVersion": "ref-indexed-expression-corpus-1.0",
        "sha256": (
            evidence["managedRelease"]["expressionCorpus"][
                "artifactDigest"
            ]
        ),
    }
    assert coverage_digests == (
        evidence["coverage"]["r5"]["digest"],
        evidence["coverage"]["r6"]["digest"],
    )
    assert selection_digest == (
        evidence["managedRelease"]["selection"]["digest"]
    )
    assert sum(1 for _item in view.iter_expressions()) == 308_639
    assert not tuple(
        view.iter_candidate_expressions(
            facet_iri="urn:ref:facet:general-subject",
            assignment_role_iri=(
                "https://rulespec.org/ns/v1#assignmentPrimary"
            ),
            resource_route="document",
            member_iri=R6_RETIRED,
        )
    )
    wall_seconds = time.perf_counter() - gate_started
    peak_memory_bytes = _process_peak_memory_bytes()
    metrics = {
        "wallSeconds": round(wall_seconds, 3),
        "peakMemoryBytes": peak_memory_bytes,
        "maxWallSeconds": REAL_GATE_MAX_WALL_SECONDS,
        "maxPeakMemoryBytes": (
            REAL_GATE_MAX_PEAK_MEMORY_BYTES
        ),
    }
    request.node.user_properties.extend(
        [
            ("elsstRealGateWallSeconds", metrics["wallSeconds"]),
            (
                "elsstRealGatePeakMemoryBytes",
                peak_memory_bytes,
            ),
        ]
    )
    print(
        "ELSST_REAL_GATE_METRICS="
        + canonical_json(metrics)
    )
    assert wall_seconds <= REAL_GATE_MAX_WALL_SECONDS
    assert peak_memory_bytes <= REAL_GATE_MAX_PEAK_MEMORY_BYTES
