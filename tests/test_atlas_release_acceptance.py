"""Release acceptance closes one exact Atlas publication chain."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest
import test_atlas_publication as publication_fixtures
import test_vocabulary_atlas_model as model_fixtures

import refspec
import refspec.atlas as atlas_api
from refspec.atlas.atlas_scope import AtlasScopeRelease
from refspec.atlas.model import VocabularyAtlasAsset, build_vocabulary_atlas
from refspec.atlas.publication import build_explorer_model
from refspec.atlas.publication_decision import VocabularyAtlasPublicationDecision
from refspec.atlas.release_acceptance import (
    RELEASE_ACCEPTANCE_TYPE,
    RELEASE_ACCEPTANCE_VERSION,
    ReleaseAcceptanceError,
    VocabularyAtlasReleaseAcceptance,
    build_vocabulary_atlas_release_acceptance,
    read_vocabulary_atlas_release_acceptance,
)
from refspec.registry.infrastructure.artifact_serialization import (
    canonical_json_bytes,
    sha256_digest,
)


def _checks(asset: VocabularyAtlasAsset) -> list[dict[str, Any]]:
    return [
        {
            "id": "urn:ref:test:release-acceptance:complete-explorer",
            "statement": "The complete explorer reconciles to the canonical Atlas.",
            "status": "passed",
            "evidence": [str(asset.manifest["id"])],
        }
    ]


def _explorer(
    scope: Any,
    asset: VocabularyAtlasAsset,
    decision: VocabularyAtlasPublicationDecision,
    **limits: int,
) -> dict[str, Any]:
    return build_explorer_model(
        asset,
        planning_index=scope.verified_scope().atlas_index,
        decision=decision,
        **limits,
    )


def _acceptance(
    scope: Any,
    asset: VocabularyAtlasAsset,
    decision: VocabularyAtlasPublicationDecision,
    *,
    explorer: dict[str, Any] | None = None,
    checks: list[dict[str, Any]] | None = None,
) -> VocabularyAtlasReleaseAcceptance:
    planning_index = scope.verified_scope().atlas_index
    selected_explorer = (
        _explorer(scope, asset, decision)
        if explorer is None
        else explorer
    )
    return build_vocabulary_atlas_release_acceptance(
        asset,
        scope=scope,
        planning_index=planning_index,
        publication_decision=decision,
        explorer=selected_explorer,
        checks=_checks(asset) if checks is None else checks,
    )


def test_acceptance_pins_inputs_derives_counts_and_reopens(
    tmp_path: Path,
) -> None:
    scope, asset, decision, relation = publication_fixtures._mapped_fixture(tmp_path)
    explorer = _explorer(scope, asset, decision)

    acceptance = _acceptance(scope, asset, decision, explorer=explorer)
    record = acceptance.as_record()

    assert record["type"] == RELEASE_ACCEPTANCE_TYPE
    assert record["schemaVersion"] == RELEASE_ACCEPTANCE_VERSION
    assert record["atlas"] == {
        "role": "VocabularyAtlas",
        "id": asset.manifest["id"],
        "manifestDigest": asset.manifest_digest,
        "distributionDigest": asset.output_digest,
    }
    assert record["scope"] == scope.pin()
    assert record["planningIndex"] == scope.verified_scope().atlas_index.pin()
    assert record["publicationDecision"] == {
        "role": "VocabularyAtlasPublicationDecision",
        "id": decision.identifier,
        "recordDigest": decision.record_digest,
        "fileDigest": sha256_digest(decision.artifact_bytes()),
    }
    assert record["explorer"]["fileDigest"] == sha256_digest(canonical_json_bytes(explorer))

    counts = record["counts"]
    assert counts["concepts"]["total"] == 2
    assert counts["nativeRelations"]["total"] == 0
    assert sum(row["count"] for row in counts["nativeRelations"]["byRelease"]) == 0
    assert counts["mappingAssertions"] == {
        "total": 1,
        "byRing": [
            {"semanticRing": "subject", "count": 1},
            {"semanticRing": "entity", "count": 0},
            {"semanticRing": "value", "count": 0},
            {"semanticRing": "legalIdentity", "count": 0},
        ],
        "byRelation": [{"value": relation, "count": 1}],
    }
    assert counts["evidence"]["assertionTotal"] == 1
    assert counts["evidence"]["byClass"] == [{"value": "humanReviewed", "count": 1}]
    assert counts["facets"]["rowCount"] == 2
    assert counts["facets"]["exactReleaseRowCount"] == 2
    assert counts["facets"]["includedReleaseRowCount"] == 2

    statuses = {row["layer"]: row["status"] for row in record["reproducibility"]}
    assert statuses == {
        "planningIndex": "reproduced",
        "sourceConceptReleases": "reproduced",
        "scope": "reproduced",
        "atlas": "reproduced",
        "explorer": "reproduced",
        "machineQualificationEvidence": "notApplicable",
    }
    assert acceptance.identifier == (
        "urn:ref:vocabulary-atlas-release-acceptance:" + acceptance.record_digest.removeprefix("sha256:")
    )
    assert VocabularyAtlasReleaseAcceptance.from_record(record) == acceptance
    assert _acceptance(scope, asset, decision, explorer=explorer) == acceptance
    acceptance.validate_inputs(
        asset,
        scope=scope,
        planning_index=scope.verified_scope().atlas_index,
        publication_decision=decision,
        explorer=explorer,
    )


def test_acceptance_reports_native_relations_per_release_ring_and_total(
    tmp_path: Path,
) -> None:
    source, _assignment = model_fixtures._SCOPE_FIXTURE._managed_release(tmp_path)
    release = AtlasScopeRelease(source)
    scope, _ = model_fixtures._pinned_scope(
        tmp_path,
        name="release-acceptance-native",
        releases=(release,),
        specs=(
            model_fixtures._SCOPE_FIXTURE._IndexSpec(
                release,
                "release-acceptance-native",
                participation="bridge",
            ),
        ),
    )
    asset = build_vocabulary_atlas(scope)
    decision = publication_fixtures._atlas_decision(scope, asset)

    record = _acceptance(scope, asset, decision).as_record()
    native = record["counts"]["nativeRelations"]

    assert native["total"] == 1
    assert native["byRelease"] == [
        {
            "releaseId": source.release_id,
            "semanticRing": "subject",
            "count": 1,
        }
    ]
    assert native["byRing"][0] == {"semanticRing": "subject", "count": 1}
    assert native["byPredicate"] == [
        {
            "value": "http://www.w3.org/2004/02/skos/core#broader",
            "count": 1,
        }
    ]
    assert record["counts"]["facets"]["bySubjectParticipation"] == [{"value": "bridge", "count": 1}]


@pytest.mark.parametrize(
    ("checks", "message"),
    [
        (
            [
                {
                    "id": "urn:ref:test:release-acceptance:failed",
                    "statement": "A required check failed.",
                    "status": "failed",
                    "evidence": ["urn:ref:test:evidence:failure"],
                }
            ],
            "status must be passed",
        ),
        (
            [
                {
                    "id": "urn:ref:test:release-acceptance:duplicate",
                    "statement": "First duplicate check.",
                    "status": "passed",
                    "evidence": ["urn:ref:test:evidence:first"],
                },
                {
                    "id": "urn:ref:test:release-acceptance:duplicate",
                    "statement": "Second duplicate check.",
                    "status": "passed",
                    "evidence": ["urn:ref:test:evidence:second"],
                },
            ],
            "repeat an id",
        ),
        ([], "at least one check"),
    ],
)
def test_acceptance_rejects_incomplete_caller_checks(
    tmp_path: Path,
    checks: list[dict[str, Any]],
    message: str,
) -> None:
    scope, asset, decision = publication_fixtures._canonical_fixture(
        tmp_path,
        name="release-acceptance-checks",
    )

    with pytest.raises(ReleaseAcceptanceError, match=message):
        _acceptance(scope, asset, decision, checks=checks)


def test_acceptance_rejects_stale_or_bounded_explorer(tmp_path: Path) -> None:
    scope, asset, decision, _ = publication_fixtures._mapped_fixture(tmp_path)
    stale = deepcopy(_explorer(scope, asset, decision))
    stale["summary"]["availableConceptCount"] += 1

    with pytest.raises(ReleaseAcceptanceError, match="available counts"):
        _acceptance(scope, asset, decision, explorer=stale)

    bounded = _explorer(scope, asset, decision, max_concepts=1)
    with pytest.raises(ReleaseAcceptanceError, match="complete explorer"):
        _acceptance(scope, asset, decision, explorer=bounded)


def test_acceptance_record_is_closed_and_exported(tmp_path: Path) -> None:
    scope, asset, decision = publication_fixtures._canonical_fixture(
        tmp_path,
        name="release-acceptance-closed",
    )
    acceptance = _acceptance(scope, asset, decision)
    changed = acceptance.as_record()
    changed["unexpected"] = True

    with pytest.raises(ReleaseAcceptanceError, match="fields differ"):
        VocabularyAtlasReleaseAcceptance.from_record(changed)

    assert atlas_api.VocabularyAtlasReleaseAcceptance is VocabularyAtlasReleaseAcceptance
    assert atlas_api.build_vocabulary_atlas_release_acceptance is build_vocabulary_atlas_release_acceptance
    assert refspec.VocabularyAtlasReleaseAcceptance is VocabularyAtlasReleaseAcceptance
    assert refspec.build_vocabulary_atlas_release_acceptance is build_vocabulary_atlas_release_acceptance
    assert atlas_api.read_vocabulary_atlas_release_acceptance is read_vocabulary_atlas_release_acceptance
    assert refspec.read_vocabulary_atlas_release_acceptance is read_vocabulary_atlas_release_acceptance


def test_acceptance_file_round_trips_under_an_external_digest(tmp_path: Path) -> None:
    scope, asset, decision = publication_fixtures._canonical_fixture(
        tmp_path,
        name="release-acceptance-file",
    )
    acceptance = _acceptance(scope, asset, decision)
    path = acceptance.write_to(tmp_path / "release-acceptance.json")

    reopened = read_vocabulary_atlas_release_acceptance(
        path,
        expected_file_digest=sha256_digest(path.read_bytes()),
    )

    assert reopened.as_record() == acceptance.as_record()
    reopened.validate_inputs(
        asset,
        scope=scope,
        planning_index=scope.verified_scope().atlas_index,
        publication_decision=decision,
        explorer=_explorer(scope, asset, decision),
    )
    with pytest.raises(ReleaseAcceptanceError, match="file digest differs"):
        read_vocabulary_atlas_release_acceptance(
            path,
            expected_file_digest=sha256_digest(b"wrong"),
        )
    with pytest.raises(ReleaseAcceptanceError, match="already exists"):
        acceptance.write_to(path)
