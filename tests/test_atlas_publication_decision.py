"""Publication decisions bind one exact scope to one exact generated result."""

from __future__ import annotations

import copy
from dataclasses import FrozenInstanceError
from pathlib import Path
from typing import Any

import pytest
import test_atlas_scope as scope_fixture

import refspec.atlas as atlas_api
from refspec.atlas.atlas_scope import (
    AtlasScopeRelease,
    PinnedVocabularyAtlasScope,
    ScopeKind,
    VocabularyAtlasScope,
)
from refspec.atlas.model import VocabularyAtlasAsset, build_vocabulary_atlas
from refspec.atlas.projection import (
    VocabularyAtlasProjection,
    build_atlas_projection,
    ring_projection_policy,
)
from refspec.atlas.publication_decision import (
    PUBLICATION_DECISION_TYPE,
    PUBLICATION_DECISION_VERSION,
    PublicationDecisionError,
    VocabularyAtlasPublicationDecision,
    build_vocabulary_atlas_publication_decision,
    read_vocabulary_atlas_publication_decision,
)
from refspec.registry.infrastructure.artifact_serialization import (
    canonical_json_bytes,
    plain_json,
    sha256_digest,
)


def _pinned_scope(
    tmp_path: Path,
    *,
    name: str = "decision",
    scope_kind: ScopeKind = "bench",
) -> PinnedVocabularyAtlasScope:
    _, source, _ = scope_fixture._source_release(tmp_path, name)
    release = AtlasScopeRelease(source)
    atlas_index, _, _ = scope_fixture._pinned_index(
        tmp_path,
        name,
        (
            scope_fixture._IndexSpec(
                release,
                name,
                participation="core",
                source_module=f"refspec.registry.{name.replace('-', '_')}",
                resource_id=f"{name}-resource",
            ),
        ),
    )
    scope = VocabularyAtlasScope.create(
        scope_name=f"urn:ref:test:vocabulary-atlas-scope:{name}",
        scope_kind=scope_kind,
        atlas_index=atlas_index,
        releases=(release,),
    )
    path = scope.write_to(tmp_path / f"{name}-scope.json")
    return PinnedVocabularyAtlasScope.open(
        path,
        expected_file_digest=sha256_digest(path.read_bytes()),
        atlas_index=atlas_index,
        releases=(release,),
    )


def _digest(label: str) -> str:
    return sha256_digest(label.encode())


def _atlas_result(suffix: str = "one") -> dict[str, str]:
    return {
        "role": "VocabularyAtlas",
        "id": f"urn:ref:test:vocabulary-atlas:{suffix}",
        "manifestDigest": _digest(f"atlas-manifest:{suffix}"),
        "distributionDigest": _digest(f"atlas-distribution:{suffix}"),
    }


def _projection_result(suffix: str = "one") -> dict[str, Any]:
    return {
        "role": "VocabularyAtlasProjection",
        "id": f"urn:ref:test:vocabulary-atlas-projection:{suffix}",
        "manifestDigest": _digest(f"projection-manifest:{suffix}"),
        "distributionDigest": _digest(f"projection-distribution:{suffix}"),
        "parent": {
            "assetId": f"urn:ref:test:vocabulary-atlas:{suffix}",
            "manifestDigest": _digest(f"parent-manifest:{suffix}"),
            "distributionDigest": _digest(f"parent-distribution:{suffix}"),
        },
    }


def _policies(*, projection: bool = False) -> list[dict[str, str]]:
    result = [
        {
            "role": "qualificationPolicy",
            "id": "urn:ref:test:qualification-policy:v2",
            "version": "2.0",
            "contentDigest": _digest("qualification-policy-v2"),
        },
        {
            "role": "selectionPolicy",
            "id": "urn:ref:test:selection-policy:v1",
            "version": "1.0",
            "contentDigest": _digest("selection-policy-v1"),
        },
    ]
    if projection:
        result.append(
            {
                "role": "projectionPolicy",
                "id": "urn:ref:test:projection-policy:ring-subject:v1",
                "version": "1.0",
                "contentDigest": _digest("projection-policy-ring-subject-v1"),
            }
        )
    return result


def _verified_atlas_result(asset: VocabularyAtlasAsset) -> dict[str, str]:
    return {
        "role": "VocabularyAtlas",
        "id": str(asset.manifest["id"]),
        "manifestDigest": asset.manifest_digest,
        "distributionDigest": asset.output_digest,
    }


def _verified_projection_result(
    projection: VocabularyAtlasProjection,
) -> dict[str, Any]:
    return {
        "role": "VocabularyAtlasProjection",
        "id": str(projection.manifest["id"]),
        "manifestDigest": projection.manifest_digest,
        "distributionDigest": projection.output_digest,
        "parent": projection.parent_pin,
    }


def _verified_projection_policies(
    projection: VocabularyAtlasProjection,
) -> list[dict[str, str]]:
    policy = plain_json(projection.manifest["projectionPolicy"])
    assert isinstance(policy, dict)
    return [
        *_policies(),
        {
            "role": "projectionPolicy",
            "id": str(policy["id"]),
            "version": str(policy["version"]),
            "contentDigest": sha256_digest(canonical_json_bytes(policy)),
        },
    ]


def _decision(
    scope: PinnedVocabularyAtlasScope,
    *,
    projection: bool = False,
) -> VocabularyAtlasPublicationDecision:
    return build_vocabulary_atlas_publication_decision(
        scope,
        artifact_kind="projection" if projection else "atlas",
        policies=_policies(projection=projection),
        decision_actor="https://refspec.org/actors/portfolio-reviewer-1",
        decided_at="2026-08-04T20:15:00Z",
        result=_projection_result() if projection else _atlas_result(),
        exceptions=(
            {
                "kind": "rights",
                "appliesTo": "urn:ref:test:release:licensed",
                "statement": "Distribution is limited to approved bench users.",
            },
            {
                "kind": "developmentOnly",
                "appliesTo": "urn:ref:test:release:experimental",
                "statement": "This release remains bench-only pending evaluation.",
            },
        ),
        supersedes=(
            {
                "id": "urn:ref:vocabulary-atlas-publication-decision:prior-b",
                "recordDigest": _digest("prior-b"),
            },
            {
                "id": "urn:ref:vocabulary-atlas-publication-decision:prior-a",
                "recordDigest": _digest("prior-a"),
            },
        ),
    )


def test_atlas_decision_derives_scope_and_planning_index_from_one_exact_scope(
    tmp_path: Path,
) -> None:
    scope = _pinned_scope(tmp_path)
    decision = _decision(scope)
    record = decision.as_record()
    scope_record = scope.verified_scope().as_record()

    assert atlas_api.PUBLICATION_DECISION_TYPE == PUBLICATION_DECISION_TYPE
    assert atlas_api.PUBLICATION_DECISION_VERSION == PUBLICATION_DECISION_VERSION
    assert atlas_api.PublicationDecisionError is PublicationDecisionError
    assert atlas_api.VocabularyAtlasPublicationDecision is VocabularyAtlasPublicationDecision
    assert atlas_api.build_vocabulary_atlas_publication_decision is build_vocabulary_atlas_publication_decision
    assert atlas_api.read_vocabulary_atlas_publication_decision is read_vocabulary_atlas_publication_decision
    assert record["type"] == PUBLICATION_DECISION_TYPE
    assert record["schemaVersion"] == PUBLICATION_DECISION_VERSION
    assert record["artifactKind"] == "atlas"
    assert record["scope"] == scope.pin()
    assert record["planningIndex"] == scope_record["atlasIndex"]
    assert record["intendedScope"] == {
        "name": scope_record["scopeName"],
        "kind": "bench",
    }
    assert [row["role"] for row in record["policies"]] == [
        "qualificationPolicy",
        "selectionPolicy",
    ]
    assert record["sourceApprovals"] == [
        {
            "releaseId": scope_record["releases"][0]["releaseId"],
            "manifestDigest": scope_record["releases"][0]["manifestDigest"],
            "semanticRing": "subject",
            "disposition": "approved",
            "conditions": [],
        }
    ]
    assert record["rowDispositions"] == [
        {
            **scope_record["releases"][0]["atlasIndexRows"][0],
            "disposition": "included",
            "reason": "Included in this publication scope.",
        }
    ]
    assert [row["id"] for row in record["supersedes"]] == sorted(row["id"] for row in record["supersedes"])
    assert decision.identifier.startswith("urn:ref:vocabulary-atlas-publication-decision:")
    decision.validate_for_scope(scope)
    decision.validate_result(_atlas_result())


def test_publication_decision_accepts_a_non_authorizing_published_scope(
    tmp_path: Path,
) -> None:
    scope = _pinned_scope(tmp_path, name="published", scope_kind="published")

    decision = _decision(scope)

    assert decision.as_record()["intendedScope"] == {
        "name": scope.verified_scope().scope_name,
        "kind": "published",
    }


def test_decision_reconciles_source_conditions_and_refuses_incomplete_controls(
    tmp_path: Path,
) -> None:
    scope = _pinned_scope(tmp_path, name="release-controls")
    release_id = scope.verified_scope().as_record()["releases"][0]["releaseId"]
    condition = {
        "kind": "developmentOnly",
        "appliesTo": release_id,
        "statement": "Public use is approved with this source condition recorded.",
    }
    decision = build_vocabulary_atlas_publication_decision(
        scope,
        artifact_kind="atlas",
        policies=_policies(),
        decision_actor="https://refspec.org/actors/portfolio-reviewer-1",
        decided_at="2026-08-04T20:15:00Z",
        result=_atlas_result("release-controls"),
        exceptions=(condition,),
    )
    assert decision.as_record()["sourceApprovals"][0]["conditions"] == [
        {
            "kind": "developmentOnly",
            "statement": condition["statement"],
        }
    ]

    with pytest.raises(PublicationDecisionError, match="every exact planning-index row"):
        build_vocabulary_atlas_publication_decision(
            scope,
            artifact_kind="atlas",
            policies=_policies(),
            decision_actor="https://refspec.org/actors/portfolio-reviewer-1",
            decided_at="2026-08-04T20:15:00Z",
            result=_atlas_result("missing-row"),
            row_dispositions=(),
        )
    with pytest.raises(PublicationDecisionError, match="every and only included source"):
        build_vocabulary_atlas_publication_decision(
            scope,
            artifact_kind="atlas",
            policies=_policies(),
            decision_actor="https://refspec.org/actors/portfolio-reviewer-1",
            decided_at="2026-08-04T20:15:00Z",
            result=_atlas_result("missing-approval"),
            source_approvals=(),
        )


def test_atlas_decision_validates_the_verified_distribution_bytes(
    tmp_path: Path,
) -> None:
    scope = _pinned_scope(tmp_path, name="verified-atlas")
    asset = build_vocabulary_atlas(scope)
    decision = build_vocabulary_atlas_publication_decision(
        scope,
        artifact_kind="atlas",
        policies=_policies(),
        decision_actor="https://refspec.org/actors/portfolio-reviewer-1",
        decided_at="2026-08-04T20:15:00Z",
        result=_verified_atlas_result(asset),
    )

    decision.validate_distribution(asset)

    with pytest.raises(PublicationDecisionError, match="does not accept a projection parent"):
        decision.validate_distribution(asset, parent=asset)
    with pytest.raises(PublicationDecisionError, match="verified atlas or projection"):
        decision.validate_distribution(object())  # type: ignore[arg-type]

    other_scope = _pinned_scope(tmp_path, name="verified-atlas-other-scope")
    other_decision = build_vocabulary_atlas_publication_decision(
        other_scope,
        artifact_kind="atlas",
        policies=_policies(),
        decision_actor="https://refspec.org/actors/portfolio-reviewer-1",
        decided_at="2026-08-04T20:15:00Z",
        result=_verified_atlas_result(asset),
    )
    with pytest.raises(PublicationDecisionError, match="another exact atlas scope"):
        other_decision.validate_distribution(asset)


def test_projection_decision_validates_parent_scope_policy_and_result(
    tmp_path: Path,
) -> None:
    scope = _pinned_scope(tmp_path, name="verified-projection")
    parent = build_vocabulary_atlas(scope)
    projection = build_atlas_projection(
        parent,
        policy=ring_projection_policy("subject"),
    )
    policies = _verified_projection_policies(projection)
    decision = build_vocabulary_atlas_publication_decision(
        scope,
        artifact_kind="projection",
        policies=policies,
        decision_actor="https://refspec.org/actors/portfolio-reviewer-1",
        decided_at="2026-08-04T20:15:00Z",
        result=_verified_projection_result(projection),
    )

    decision.validate_distribution(projection, parent=parent)
    assert [
        policy["contentDigest"] for policy in decision.as_record()["policies"] if policy["role"] != "projectionPolicy"
    ] == [
        _digest("qualification-policy-v2"),
        _digest("selection-policy-v1"),
    ]

    with pytest.raises(PublicationDecisionError, match="requires its verified atlas parent"):
        decision.validate_distribution(projection)

    other_scope = _pinned_scope(tmp_path, name="other-projection-parent")
    other_parent = build_vocabulary_atlas(other_scope)
    with pytest.raises(PublicationDecisionError, match="parent pin differs"):
        decision.validate_distribution(projection, parent=other_parent)


def test_projection_distribution_rejects_wrong_policy_result_or_decision_kind(
    tmp_path: Path,
) -> None:
    scope = _pinned_scope(tmp_path, name="projection-refusals")
    parent = build_vocabulary_atlas(scope)
    projection = build_atlas_projection(
        parent,
        policy=ring_projection_policy("subject"),
    )
    policies = _verified_projection_policies(projection)
    wrong_policy = copy.deepcopy(policies)
    wrong_policy[-1]["contentDigest"] = _digest("wrong-projection-policy")
    policy_decision = build_vocabulary_atlas_publication_decision(
        scope,
        artifact_kind="projection",
        policies=wrong_policy,
        decision_actor="https://refspec.org/actors/portfolio-reviewer-1",
        decided_at="2026-08-04T20:15:00Z",
        result=_verified_projection_result(projection),
    )
    with pytest.raises(PublicationDecisionError, match="projection policy differs"):
        policy_decision.validate_distribution(projection, parent=parent)

    wrong_result = _verified_projection_result(projection)
    wrong_result["distributionDigest"] = _digest("wrong-projection-result")
    result_decision = build_vocabulary_atlas_publication_decision(
        scope,
        artifact_kind="projection",
        policies=policies,
        decision_actor="https://refspec.org/actors/portfolio-reviewer-1",
        decided_at="2026-08-04T20:15:00Z",
        result=wrong_result,
    )
    with pytest.raises(PublicationDecisionError, match="another exact result"):
        result_decision.validate_distribution(projection, parent=parent)

    atlas_decision = build_vocabulary_atlas_publication_decision(
        scope,
        artifact_kind="atlas",
        policies=_policies(),
        decision_actor="https://refspec.org/actors/portfolio-reviewer-1",
        decided_at="2026-08-04T20:15:00Z",
        result=_verified_atlas_result(parent),
    )
    with pytest.raises(PublicationDecisionError, match="cannot validate a projection"):
        atlas_decision.validate_distribution(projection, parent=parent)


def test_decision_is_deterministic_content_derived_and_immutable(tmp_path: Path) -> None:
    scope = _pinned_scope(tmp_path)
    first = _decision(scope)
    second = build_vocabulary_atlas_publication_decision(
        scope,
        artifact_kind="atlas",
        policies=list(reversed(_policies())),
        decision_actor="https://refspec.org/actors/portfolio-reviewer-1",
        decided_at="2026-08-04T20:15:00Z",
        result=_atlas_result(),
        exceptions=list(reversed(first.as_record()["exceptions"])),
        supersedes=list(reversed(first.as_record()["supersedes"])),
    )

    assert first.as_record() == second.as_record()
    assert first.artifact_bytes() == second.artifact_bytes()
    assert first.record_digest == _digest_bytes_without_helper(first.artifact_bytes(), first)
    with pytest.raises(TypeError):
        first.record["artifactKind"] = "projection"  # type: ignore[index]
    with pytest.raises(FrozenInstanceError):
        first.record = {}  # type: ignore[misc]


def _digest_bytes_without_helper(
    _artifact: bytes,
    decision: VocabularyAtlasPublicationDecision,
) -> str:
    # The record digest covers the basis, not the file that contains the digest.
    forged = decision.as_record()
    del forged["id"]
    del forged["recordDigest"]
    from refspec.registry.infrastructure.artifact_serialization import canonical_json_bytes

    return sha256_digest(canonical_json_bytes(forged))


def test_projection_decision_requires_one_projection_policy_and_exact_parent(
    tmp_path: Path,
) -> None:
    scope = _pinned_scope(tmp_path)
    decision = _decision(scope, projection=True)

    assert decision.artifact_kind == "projection"
    assert decision.as_record()["result"]["parent"]["assetId"] == ("urn:ref:test:vocabulary-atlas:one")
    decision.validate_result(_projection_result())

    with pytest.raises(PublicationDecisionError, match="exactly one projection policy"):
        build_vocabulary_atlas_publication_decision(
            scope,
            artifact_kind="projection",
            policies=_policies(),
            decision_actor="https://refspec.org/actors/reviewer",
            decided_at="2026-08-04T20:15:00Z",
            result=_projection_result(),
        )

    policies = _policies(projection=True)
    policies.append(copy.deepcopy(policies[-1]))
    policies[-1]["id"] = "urn:ref:test:projection-policy:second"
    with pytest.raises(PublicationDecisionError, match="exactly one projection policy"):
        build_vocabulary_atlas_publication_decision(
            scope,
            artifact_kind="projection",
            policies=policies,
            decision_actor="https://refspec.org/actors/reviewer",
            decided_at="2026-08-04T20:15:00Z",
            result=_projection_result(),
        )

    same_parent = _projection_result()
    same_parent["id"] = same_parent["parent"]["assetId"]
    with pytest.raises(PublicationDecisionError, match="differ from its parent"):
        build_vocabulary_atlas_publication_decision(
            scope,
            artifact_kind="projection",
            policies=_policies(projection=True),
            decision_actor="https://refspec.org/actors/reviewer",
            decided_at="2026-08-04T20:15:00Z",
            result=same_parent,
        )


def test_atlas_decision_rejects_projection_policy_and_result_shape(tmp_path: Path) -> None:
    scope = _pinned_scope(tmp_path)
    with pytest.raises(PublicationDecisionError, match="cannot name a projection policy"):
        build_vocabulary_atlas_publication_decision(
            scope,
            artifact_kind="atlas",
            policies=_policies(projection=True),
            decision_actor="https://refspec.org/actors/reviewer",
            decided_at="2026-08-04T20:15:00Z",
            result=_atlas_result(),
        )

    wrong = _atlas_result()
    wrong["role"] = "VocabularyAtlasProjection"
    with pytest.raises(PublicationDecisionError, match="must be VocabularyAtlas"):
        build_vocabulary_atlas_publication_decision(
            scope,
            artifact_kind="atlas",
            policies=_policies(),
            decision_actor="https://refspec.org/actors/reviewer",
            decided_at="2026-08-04T20:15:00Z",
            result=wrong,
        )


@pytest.mark.parametrize(
    "policies",
    [
        [],
        [_policies()[0]],
        [_policies()[1]],
    ],
)
def test_every_decision_requires_selection_and_qualification_policy_pins(
    tmp_path: Path,
    policies: list[dict[str, str]],
) -> None:
    scope = _pinned_scope(tmp_path)

    with pytest.raises(
        PublicationDecisionError,
        match="requires selectionPolicy and qualificationPolicy",
    ):
        build_vocabulary_atlas_publication_decision(
            scope,
            artifact_kind="atlas",
            policies=policies,
            decision_actor="https://refspec.org/actors/reviewer",
            decided_at="2026-08-04T20:15:00Z",
            result=_atlas_result(),
        )


def test_decision_fails_closed_for_other_scope_result_or_stale_content(
    tmp_path: Path,
) -> None:
    scope = _pinned_scope(tmp_path, name="decision-a")
    other_scope = _pinned_scope(tmp_path, name="decision-b")
    decision = _decision(scope)

    with pytest.raises(PublicationDecisionError, match="another exact atlas scope"):
        decision.validate_for_scope(other_scope)
    with pytest.raises(PublicationDecisionError, match="another exact result"):
        decision.validate_result(_atlas_result("other"))

    stale = decision.as_record()
    stale["decisionActor"] = "https://refspec.org/actors/other"
    with pytest.raises(PublicationDecisionError, match="identity, inputs"):
        VocabularyAtlasPublicationDecision.from_record(stale)

    extra = decision.as_record()
    extra["authorization"] = {"granted": True}
    with pytest.raises(PublicationDecisionError, match="fields differ"):
        VocabularyAtlasPublicationDecision.from_record(extra)


def test_decision_file_round_trips_under_an_external_digest(tmp_path: Path) -> None:
    scope = _pinned_scope(tmp_path)
    decision = _decision(scope)
    path = decision.write_to(tmp_path / "publication-decision.json")
    digest = sha256_digest(path.read_bytes())

    reopened = read_vocabulary_atlas_publication_decision(
        path,
        expected_file_digest=digest,
    )
    assert reopened.as_record() == decision.as_record()
    reopened.validate_for_scope(scope)

    with pytest.raises(PublicationDecisionError, match="file digest differs"):
        read_vocabulary_atlas_publication_decision(
            path,
            expected_file_digest=_digest("wrong-file"),
        )
    with pytest.raises(PublicationDecisionError, match="already exists"):
        decision.write_to(path)


def test_reader_preserves_resolvable_v1_publication_decisions(tmp_path: Path) -> None:
    scope = _pinned_scope(tmp_path, name="legacy-decision")
    legacy = _decision(scope).as_record()
    legacy["schemaVersion"] = "1.0"
    del legacy["sourceApprovals"]
    del legacy["rowDispositions"]
    del legacy["id"]
    del legacy["recordDigest"]
    digest = sha256_digest(canonical_json_bytes(legacy))
    legacy.update(
        {
            "id": "urn:ref:vocabulary-atlas-publication-decision:" + digest.removeprefix("sha256:"),
            "recordDigest": digest,
        }
    )

    reopened = VocabularyAtlasPublicationDecision.from_record(legacy)

    assert reopened.as_record() == legacy
    reopened.validate_for_scope(scope)
