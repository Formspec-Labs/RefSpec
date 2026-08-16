from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest

from refspec.atlas_index import (
    AtlasIndexError,
    PinnedAtlasIndex,
    atlas_index_rows,
    build_atlas_index,
    validate_atlas_index,
)
from refspec.resource_catalog import load_json

ROOT = Path(__file__).resolve().parents[1]
INPUT = ROOT / "portfolio" / "atlas-index-input-v0.json"
CATALOG = ROOT / "portfolio" / "resource-catalog-v0.json"
INDEX = ROOT / "portfolio" / "atlas-index-v0.json"

ROLE = "https://rulespec.org/ns/v1#assignmentContextual"


def _write(path: Path, content: str = "evidence\n") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _fixture(tmp_path: Path) -> tuple[dict[str, object], dict[str, object]]:
    _write(tmp_path / "src/refspec/registry/alpha.py")
    _write(tmp_path / "src/refspec/registry/beta.py")
    _write(tmp_path / "src/refspec/registry/infrastructure/helper.py")
    _write(tmp_path / "src/refspec/registry/__init__.py")
    _write(tmp_path / "evidence/alpha.json", "{}\n")
    _write(tmp_path / "evidence/beta.json", "{}\n")
    digest = "sha256:" + "1" * 64
    catalog: dict[str, object] = {
        "catalogDigest": digest,
        "catalogId": "urn:ref:resource-catalog:" + "1" * 64,
        "resources": [{"resourceId": "alpha"}, {"resourceId": "beta"}],
    }
    index_input: dict[str, object] = {
        "format": "refspec-atlas-index-input/experimental-v0",
        "implementationModules": ["refspec.registry.infrastructure.helper"],
        "recordedAt": "2026-08-04T08:01:00Z",
        "resourceCatalogDigest": digest,
        "rows": [
            {
                "assignmentRole": ROLE,
                "atlasParticipation": "bridge",
                "facet": "urn:ref:facet:general-subject",
                "intendedUses": ["searchExpansion", "mappingReference"],
                "planningStatus": "planned",
                "semanticRing": "subject",
                "readinessEvidence": [{"kind": "sourceObservation", "path": "evidence/alpha.json"}],
                "release": None,
                "resourceId": "alpha",
                "sourceModule": "refspec.registry.alpha",
            },
            {
                "assignmentRole": ROLE,
                "atlasParticipation": None,
                "facet": "urn:ref:facet:code-list-value",
                "intendedUses": ["deterministicMetadata"],
                "planningStatus": "notApplicable",
                "semanticRing": "value",
                "readinessEvidence": [{"kind": "sourceObservation", "path": "evidence/beta.json"}],
                "release": None,
                "resourceId": "beta",
                "sourceModule": "refspec.registry.beta",
            },
        ],
    }
    return index_input, catalog


def test_checked_atlas_index_is_exact_and_exhaustive() -> None:
    index_input = load_json(INPUT)
    catalog = load_json(CATALOG)
    index = load_json(INDEX)

    validate_atlas_index(index, index_input, catalog, repository_root=ROOT)

    assert index["nonAuthorizing"] is True
    assert index["summary"] == {
        "exactReleaseCount": 6,
        "implementationModuleCount": 25,
        # REF-033: nasa-technology-taxonomy left the subject ring for the
        # value ring, taking its bridge claim with it (bridge 10 -> 9).
        # REF-035 through REF-037 add the mapping and acquisition bridges.
        "participationCounts": {"bridge": 34, "core": 1, "specialist": 3},
        # REF-033: four entity-ring placements landed (the Federal Register
        # agencies roster, the FCC published bureaus/offices roster, the
        # complete Federal Hierarchy roster, and the EHRI AGENCY/SUBELEMENT
        # roster split out of the value-ring workbook release); the LDA and
        # NASA rows moved from the subject ring to the value ring, and the
        # Federal Register documented document types joined the value ring.
        # REF-034: GAO's published /topics index joined the subject ring, and
        # three value-ring placements landed for the documented successors
        # (the GAO Form 41217 option lists and NRC's two published APS
        # documentation units).
        # REF-035 adds one subject-ring and one value-ring mapping source.
        # The Regulations.gov agency roster adds one entity-ring source.
        "semanticRingCounts": {
            "entity": 17,
            "legalIdentity": 3,
            "subject": 45,
            "value": 45,
        },
        "rowCount": 110,
        "sourceModuleCount": 60,
        "statusCounts": {
            "deferred": 2,
            "notApplicable": 44,
            "planned": 54,
            # REF-030: the four registrant-population authorities (UEI, CAGE,
            # NPI, CompTox) are rejected for Atlas participation; they live in
            # the entity-registry object instead. REF-031: the three
            # document-population authorities (CBO publications, FCC ECFS
            # proceedings, GovInfo CFR packages) are rejected too; SpicyRegs
            # acquires those. REF-032 rejects the two observed inventories
            # whose reader survives -- OPM PLUM position statuses and the FAST
            # Book fund types -- while the seven readers left with no unit
            # and no named follow-up were deleted, taking fourteen planning
            # rows with them. REF-033 rejects the two deleted census-family
            # units whose reader survives (the ACS geography span and the
            # NASBO chapter scan) and removes the SCOTUS and SEC rows with
            # their deleted readers. REF-034 flips the treasury-fast-book
            # value row back off rejected (11 -> 10): the rejected verdict
            # named the observed fund-type Counter, and the workbook's own
            # documented Intro-sheet fund groups now ship under that row.
            "rejected": 10,
            "superseded": 0,
            "unassessed": 0,
        },
    }
    assert len(atlas_index_rows(index, semantic_ring="subject")) == 45


def test_pinned_atlas_index_reopens_the_exact_non_authorizing_snapshot(
    tmp_path: Path,
) -> None:
    index_input, catalog = _fixture(tmp_path)
    index = build_atlas_index(index_input, catalog, repository_root=tmp_path)
    path = tmp_path / "atlas-index.json"
    path.write_text(json.dumps(index, indent=2) + "\n", encoding="utf-8")
    file_digest = "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()

    pinned = PinnedAtlasIndex.open(
        path,
        expected_file_digest=file_digest,
        index_input=index_input,
        resource_catalog=catalog,
        repository_root=tmp_path,
    )

    reopened = pinned.verified_index()
    assert reopened["indexId"] == index["indexId"]
    assert reopened["indexDigest"] == index["indexDigest"]
    assert tuple(row["rowId"] for row in reopened["rows"]) == tuple(row["rowId"] for row in index["rows"])
    assert pinned.pin() == {
        "role": "AtlasIndex",
        "id": index["indexId"],
        "indexDigest": index["indexDigest"],
        "fileDigest": file_digest,
    }
    assert str(tmp_path) not in str(pinned.pin())


def test_pinned_atlas_index_rejects_file_and_evidence_drift(
    tmp_path: Path,
) -> None:
    index_input, catalog = _fixture(tmp_path)
    index = build_atlas_index(index_input, catalog, repository_root=tmp_path)
    path = tmp_path / "atlas-index.json"
    path.write_text(json.dumps(index, indent=2) + "\n", encoding="utf-8")
    pinned = PinnedAtlasIndex.open(
        path,
        expected_file_digest=("sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()),
        index_input=index_input,
        resource_catalog=catalog,
        repository_root=tmp_path,
    )

    path.write_text(path.read_text(encoding="utf-8") + " ", encoding="utf-8")
    with pytest.raises(AtlasIndexError, match="file digest differs"):
        pinned.verified_index()

    path.write_text(json.dumps(index, indent=2) + "\n", encoding="utf-8")
    _write(tmp_path / "evidence/alpha.json", '{"changed":true}\n')
    with pytest.raises(AtlasIndexError, match="checked atlas index differs"):
        pinned.verified_index()


def test_generation_is_order_independent_and_preserves_one_resource_across_rings(
    tmp_path: Path,
) -> None:
    index_input, catalog = _fixture(tmp_path)
    repeated = copy.deepcopy(index_input["rows"][0])  # type: ignore[index]
    repeated.update(
        {
            "atlasParticipation": None,
            "facet": "urn:ref:facet:code-list-value",
            "intendedUses": ["deterministicMetadata"],
            "planningStatus": "notApplicable",
            "semanticRing": "value",
        }
    )
    index_input["rows"].append(repeated)  # type: ignore[union-attr]

    expected = build_atlas_index(index_input, catalog, repository_root=tmp_path)
    reordered = copy.deepcopy(index_input)
    reordered["rows"].reverse()  # type: ignore[union-attr]
    reordered["implementationModules"].reverse()  # type: ignore[union-attr]

    assert build_atlas_index(reordered, catalog, repository_root=tmp_path) == expected
    assert len(expected["rows"]) == 3
    assert {row["semanticRing"] for row in expected["rows"] if row["resourceId"] == "alpha"} == {"subject", "value"}
    assert all(row["rowId"].endswith(row["rowDigest"].removeprefix("sha256:")) for row in expected["rows"])


def test_subject_row_may_remain_evidence_only_without_participation(tmp_path: Path) -> None:
    index_input, catalog = _fixture(tmp_path)
    index_input["rows"][0]["atlasParticipation"] = None  # type: ignore[index]

    built = build_atlas_index(index_input, catalog, repository_root=tmp_path)

    subject_rows = atlas_index_rows(built, semantic_ring="subject")
    assert len(subject_rows) == 1
    assert subject_rows[0]["atlasParticipation"] is None


def test_source_assignment_is_an_intended_use_not_a_destination(tmp_path: Path) -> None:
    index_input, catalog = _fixture(tmp_path)
    row = index_input["rows"][0]  # type: ignore[index]
    row["atlasParticipation"] = None
    row["intendedUses"] = ["sourceAssignedEvidence"]

    built = build_atlas_index(index_input, catalog, repository_root=tmp_path)

    subject_row = atlas_index_rows(built, semantic_ring="subject")[0]
    assert subject_row["intendedUses"] == ["sourceAssignedEvidence"]
    assert "publicationTarget" not in subject_row

    row["publicationTarget"] = "sourceAssignedEvidence"
    with pytest.raises(AtlasIndexError, match="extra=.*publicationTarget"):
        build_atlas_index(index_input, catalog, repository_root=tmp_path)


def test_exact_duplicate_row_is_rejected(tmp_path: Path) -> None:
    index_input, catalog = _fixture(tmp_path)
    index_input["rows"].append(copy.deepcopy(index_input["rows"][0]))  # type: ignore[index,union-attr]

    with pytest.raises(AtlasIndexError, match="repeats an exact row"):
        build_atlas_index(index_input, catalog, repository_root=tmp_path)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("semanticRing", "searchIndex", "unsupported"),
        ("atlasParticipation", "ring2", "unsupported"),
        ("planningStatus", "ready", "unsupported"),
        ("intendedUses", ["authorization"], "unsupported"),
        ("facet", "urn:ref:facet:unknown", "unsupported"),
        ("assignmentRole", "urn:ref:role:unknown", "unsupported"),
    ],
)
def test_closed_row_values_are_enforced(tmp_path: Path, field: str, value: object, message: str) -> None:
    index_input, catalog = _fixture(tmp_path)
    index_input["rows"][0][field] = value  # type: ignore[index]

    with pytest.raises(AtlasIndexError, match=message):
        build_atlas_index(index_input, catalog, repository_root=tmp_path)


def test_non_subject_participation_and_bridge_generation_are_rejected(tmp_path: Path) -> None:
    index_input, catalog = _fixture(tmp_path)
    index_input["rows"][1]["atlasParticipation"] = "core"  # type: ignore[index]
    with pytest.raises(AtlasIndexError, match="non-subject rows"):
        build_atlas_index(index_input, catalog, repository_root=tmp_path)

    index_input, catalog = _fixture(tmp_path)
    index_input["rows"][0]["intendedUses"] = ["candidateGeneration"]  # type: ignore[index]
    with pytest.raises(AtlasIndexError, match="bridge rows"):
        build_atlas_index(index_input, catalog, repository_root=tmp_path)


def test_permission_fields_and_unknown_catalog_resources_are_rejected(tmp_path: Path) -> None:
    index_input, catalog = _fixture(tmp_path)
    index_input["rows"][0]["candidateUseAuthorized"] = False  # type: ignore[index]
    with pytest.raises(AtlasIndexError, match="permission-shaped"):
        build_atlas_index(index_input, catalog, repository_root=tmp_path)

    index_input, catalog = _fixture(tmp_path)
    index_input["rows"][0]["resourceId"] = "missing"  # type: ignore[index]
    with pytest.raises(AtlasIndexError, match="absent from the resource catalog"):
        build_atlas_index(index_input, catalog, repository_root=tmp_path)


@pytest.mark.parametrize("unsafe", ["/tmp/evidence.json", "../evidence.json", "missing.json"])
def test_unsafe_or_missing_evidence_paths_are_rejected(tmp_path: Path, unsafe: str) -> None:
    index_input, catalog = _fixture(tmp_path)
    index_input["rows"][0]["readinessEvidence"][0]["path"] = unsafe  # type: ignore[index]

    with pytest.raises(AtlasIndexError, match="repository-relative|checked regular file"):
        build_atlas_index(index_input, catalog, repository_root=tmp_path)


def test_symlinked_evidence_is_rejected(tmp_path: Path) -> None:
    index_input, catalog = _fixture(tmp_path)
    (tmp_path / "evidence/link.json").symlink_to(tmp_path / "evidence/alpha.json")
    index_input["rows"][0]["readinessEvidence"][0]["path"] = "evidence/link.json"  # type: ignore[index]

    with pytest.raises(AtlasIndexError, match="checked regular file"):
        build_atlas_index(index_input, catalog, repository_root=tmp_path)


def test_exact_release_requires_matching_evidence_and_validation(tmp_path: Path) -> None:
    index_input, catalog = _fixture(tmp_path)
    release_id = "urn:example:release:1"
    manifest_digest = "sha256:" + "2" * 64
    _write(
        tmp_path / "evidence/release.json",
        json.dumps({"releaseId": release_id, "manifestDigest": manifest_digest}) + "\n",
    )
    row = index_input["rows"][0]  # type: ignore[index]
    row["release"] = {
        "evidencePath": "evidence/release.json",
        "manifestDigest": manifest_digest,
        "releaseId": release_id,
    }
    with pytest.raises(AtlasIndexError, match="release-validation"):
        build_atlas_index(index_input, catalog, repository_root=tmp_path)

    row["readinessEvidence"].append(  # type: ignore[union-attr]
        {"kind": "managedReleaseValidation", "path": "evidence/release.json"}
    )
    built = build_atlas_index(index_input, catalog, repository_root=tmp_path)
    assert built["summary"]["exactReleaseCount"] == 1

    row["release"]["manifestDigest"] = "sha256:" + "3" * 64  # type: ignore[index]
    with pytest.raises(AtlasIndexError, match="does not record both"):
        build_atlas_index(index_input, catalog, repository_root=tmp_path)


def test_source_concept_release_validation_requires_a_ring_matched_package_row(
    tmp_path: Path,
) -> None:
    index_input, catalog = _fixture(tmp_path)
    release_id = "urn:example:source-concept-release:1"
    manifest_digest = "sha256:" + "2" * 64
    evidence_path = tmp_path / "evidence/release.json"
    _write(
        evidence_path,
        json.dumps({"releaseId": release_id, "manifestDigest": manifest_digest}) + "\n",
    )
    row = index_input["rows"][0]  # type: ignore[index]
    row["release"] = {
        "evidencePath": "evidence/release.json",
        "manifestDigest": manifest_digest,
        "releaseId": release_id,
    }
    row["readinessEvidence"].append(  # type: ignore[union-attr]
        {"kind": "sourceConceptReleaseValidation", "path": "evidence/release.json"}
    )

    with pytest.raises(AtlasIndexError, match="lacks structured"):
        build_atlas_index(index_input, catalog, repository_root=tmp_path)

    _write(
        evidence_path,
        json.dumps(
            {
                "releaseId": release_id,
                "manifestDigest": manifest_digest,
                "releases": [
                    {
                        "path": "source-release",
                        "releaseId": release_id,
                        "manifestDigest": manifest_digest,
                        "semanticRing": "entity",
                    }
                ],
            }
        )
        + "\n",
    )
    with pytest.raises(AtlasIndexError, match="semanticRing differs"):
        build_atlas_index(index_input, catalog, repository_root=tmp_path)


@pytest.mark.parametrize(
    ("semantic_ring", "facet", "intended_use"),
    [
        ("entity", "urn:ref:facet:entity", "entityResolution"),
        ("legalIdentity", "urn:ref:facet:legal-location", "legalIdentityResolution"),
        ("value", "urn:ref:facet:code-list-value", "deterministicMetadata"),
    ],
)
def test_non_subject_rings_share_the_exact_release_foundation(
    tmp_path: Path,
    semantic_ring: str,
    facet: str,
    intended_use: str,
) -> None:
    index_input, catalog = _fixture(tmp_path)
    release_id = f"urn:example:{semantic_ring}:release:1"
    manifest_digest = "sha256:" + "2" * 64
    _write(
        tmp_path / "evidence/release.json",
        json.dumps({"releaseId": release_id, "manifestDigest": manifest_digest}) + "\n",
    )
    row = index_input["rows"][1]  # type: ignore[index]
    row.update(
        {
            "facet": facet,
            "intendedUses": [intended_use],
            "semanticRing": semantic_ring,
            "release": {
                "evidencePath": "evidence/release.json",
                "manifestDigest": manifest_digest,
                "releaseId": release_id,
            },
        }
    )
    row["readinessEvidence"].append(  # type: ignore[union-attr]
        {"kind": "managedReleaseValidation", "path": "evidence/release.json"}
    )

    built = build_atlas_index(index_input, catalog, repository_root=tmp_path)

    ring_rows = atlas_index_rows(built, semantic_ring=semantic_ring)
    assert len(ring_rows) == 1
    assert ring_rows[0]["release"]["releaseId"] == release_id


def test_registry_module_classification_is_exhaustive(tmp_path: Path) -> None:
    index_input, catalog = _fixture(tmp_path)
    index_input["rows"].pop()  # type: ignore[union-attr]
    with pytest.raises(AtlasIndexError, match="missing=.*beta"):
        build_atlas_index(index_input, catalog, repository_root=tmp_path)

    index_input, catalog = _fixture(tmp_path)
    _write(tmp_path / "src/refspec/registry/new/nested.py")
    with pytest.raises(AtlasIndexError, match="missing=.*nested"):
        build_atlas_index(index_input, catalog, repository_root=tmp_path)


def test_source_and_implementation_modules_cannot_overlap(tmp_path: Path) -> None:
    index_input, catalog = _fixture(tmp_path)
    index_input["implementationModules"].append("refspec.registry.alpha")  # type: ignore[union-attr]

    with pytest.raises(AtlasIndexError, match="overlap"):
        build_atlas_index(index_input, catalog, repository_root=tmp_path)


def test_catalog_drift_and_generated_output_drift_are_rejected(tmp_path: Path) -> None:
    index_input, catalog = _fixture(tmp_path)
    changed_catalog = copy.deepcopy(catalog)
    changed_catalog["catalogDigest"] = "sha256:" + "9" * 64
    with pytest.raises(AtlasIndexError, match="does not match"):
        build_atlas_index(index_input, changed_catalog, repository_root=tmp_path)

    built = build_atlas_index(index_input, catalog, repository_root=tmp_path)
    changed_output = copy.deepcopy(built)
    changed_output["nonAuthorizing"] = False
    with pytest.raises(AtlasIndexError, match="differs"):
        validate_atlas_index(
            changed_output,
            index_input,
            catalog,
            repository_root=tmp_path,
        )


def test_evidence_byte_drift_changes_the_index_identity(tmp_path: Path) -> None:
    index_input, catalog = _fixture(tmp_path)
    built = build_atlas_index(index_input, catalog, repository_root=tmp_path)
    _write(tmp_path / "evidence/alpha.json", '{"changed":true}\n')

    with pytest.raises(AtlasIndexError, match="differs"):
        validate_atlas_index(built, index_input, catalog, repository_root=tmp_path)


def test_offline_tooling_stays_outside_the_pinned_index_closure() -> None:
    """Qualification never runs inside a build, so it must never pin into one.

    The index pins the digest of every source the build depends on. An offline
    module listed there would move the Atlas identity whenever the runner
    changed, which is the coupling the offline-tool idiom exists to prevent.
    """

    index = json.loads(
        (Path(__file__).resolve().parents[1] / "portfolio/atlas-index-v0.json").read_text(encoding="utf-8")
    )

    pinned: set[str] = set()

    def collect(node: object) -> None:
        if isinstance(node, dict):
            path = node.get("path")
            if isinstance(path, str):
                pinned.add(path)
            for value in node.values():
                collect(value)
        elif isinstance(node, list):
            for value in node:
                collect(value)

    collect(index)
    assert pinned, "the atlas index pins no source paths; this guard would be vacuous"

    offline = sorted(
        path for path in pinned if "qualification" in path or "benchmark" in path or "candidate_retrieval" in path
    )
    assert not offline, f"offline tooling entered the pinned index closure: {offline}"
