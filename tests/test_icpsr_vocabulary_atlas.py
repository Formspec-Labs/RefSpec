"""Atlas-door proof for the development-only ICPSR subject thesaurus."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from rdflib import Dataset, Literal, URIRef
from rdflib.namespace import PROV, RDF, SKOS

import refspec.atlas.cli as atlas_cli
import refspec.atlas.model as atlas_model
from refspec.atlas import (
    ATLAS,
    RKAF,
    PinnedIcpsrSubjectAtlasRelease,
    PinnedRulespecCoreRelease,
    VocabularyAtlasAsset,
    VocabularyAtlasError,
    build_vocabulary_atlas,
)
from refspec.atlas.cli import main as atlas_main
from refspec.atlas.icpsr import ICPSR_RELEASE_IRI_PREFIX
from refspec.atlas.queries import VocabularyAtlasQueries
from refspec.managed_release import ManagedReleaseError
from refspec.registry.icpsr_managed_release import (
    IcpsrManagedRelease,
    IcpsrManagedReleaseSources,
    build_icpsr_managed_release,
    open_icpsr_managed_release_sources,
)
from refspec.registry.icpsr_subject import (
    ICPSR_SUBJECT_SCHEME_IRI,
    build_icpsr_subject_index,
    parse_icpsr_subject_xml,
)
from refspec.storage import canonical_json

FIXTURES = Path(__file__).parent / "fixtures"
REAL_CAPTURE = Path(__file__).resolve().parents[2] / "output" / "refspec-vocabulary-portfolio" / "icpsr" / "2026-07-30"
ROBOTS = b"User-agent: *\nDisallow: /cgi-bin/\n"
RECORDED_AT = "2026-07-30T16:00:00Z"
RECORDED_BY = "urn:test:agent:icpsr-vocabulary-atlas"
REAL_RECORDED_BY = "urn:ref:actor:codex-local-development"


def _file_digest(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _core_release(tmp_path: Path) -> PinnedRulespecCoreRelease:
    preimage = {
        "record_type": "RulespecCoreRelease",
        "release_status": "fixture",
        "version": "0.2.0-pre.9+test-fixture",
        "schema_artifacts": [
            {
                "artifact_digest": "sha256:" + "a" * 64,
                "media_type": "application/schema+json",
                "name": "compiled/json-schema/core/reference-resource-release.schema.json",
            }
        ],
        "validator_artifacts": [
            {
                "artifact_digest": "sha256:" + "b" * 64,
                "media_type": "text/x-python",
                "name": "tools/ci_validate.py",
            }
        ],
        "conformance_fixture_artifacts": [
            {
                "artifact_digest": "sha256:" + "c" * 64,
                "media_type": "application/ld+json",
                "name": "fixtures/reference-resource-release-digest-positive.jsonld",
            }
        ],
    }
    digest = "sha256:" + hashlib.sha256(canonical_json(preimage).encode()).hexdigest()
    release_id = "urn:rulespec:core:" + digest.removeprefix("sha256:")
    path = tmp_path / "rulespec-core.json"
    path.write_text(
        canonical_json({**preimage, "release_id": release_id, "release_digest": digest}),
        encoding="utf-8",
    )
    return PinnedRulespecCoreRelease.open(
        path,
        expected_file_digest=_file_digest(path),
        expected_release_id=release_id,
        expected_release_digest=digest,
    )


def _fixture_sources() -> IcpsrManagedReleaseSources:
    pages = {letter: (FIXTURES / f"icpsr-subject-index-{letter}-mini.html").read_bytes() for letter in ("a", "s", "t")}
    xml_payload = (FIXTURES / "icpsr-subject-mini.xml").read_bytes()
    index = build_icpsr_subject_index(
        pages,
        robots_body=ROBOTS,
        require_complete=False,
        observed_at=RECORDED_AT,
    )
    return IcpsrManagedReleaseSources(
        index=index,
        xml=parse_icpsr_subject_xml(xml_payload),
        source_capture_digest=index.capture_digest,
        source_manifest_digest="sha256:" + hashlib.sha256(b"fixture manifest").hexdigest(),
        source_artifacts={
            "index/robots.txt": ROBOTS,
            **{f"index/pages/{letter}.html": payload for letter, payload in pages.items()},
            "subject.xml": xml_payload,
        },
    )


def _fixture_release() -> IcpsrManagedRelease:
    return build_icpsr_managed_release(
        _fixture_sources(),
        recorded_at=RECORDED_AT,
        recorded_by=RECORDED_BY,
        require_complete_index=False,
        expected_gap_counts=(0, 0),
    )


def _fixture_package(tmp_path: Path) -> Path:
    return _fixture_release().write_to(tmp_path / "icpsr-package")


def _release_facts(asset: VocabularyAtlasAsset):
    release_graph_id = next(row["id"] for row in asset.manifest["graphs"] if row["role"] == "releaseFacts")
    dataset = Dataset(default_union=False)
    dataset.parse(data=asset.payload.decode("utf-8"), format="nquads")
    return dataset.graph(URIRef(release_graph_id))


def _fixture_atlas(tmp_path: Path) -> tuple[PinnedIcpsrSubjectAtlasRelease, VocabularyAtlasAsset]:
    manifest_path = _fixture_package(tmp_path)
    source = PinnedIcpsrSubjectAtlasRelease.open(
        manifest_path,
        expected_manifest_digest=_file_digest(manifest_path),
    )
    return source, build_vocabulary_atlas((source,), rulespec_core=_core_release(tmp_path))


def test_atlas_admits_the_development_icpsr_release_with_its_marker(tmp_path: Path) -> None:
    source, asset = _fixture_atlas(tmp_path)
    output = asset.write(tmp_path / "atlas")
    reopened = VocabularyAtlasAsset.open(
        output,
        expected_manifest_digest=asset.manifest_digest,
        expected_output_digest=asset.output_digest,
    )

    graph = _release_facts(reopened)
    release = URIRef(source.verified_view().reference_release_iri)

    assert reopened.manifest["counts"]["managedReleases"] == 1
    assert len(set(graph.objects(release, PROV.hadMember))) == 5
    assert (release, RDF.type, RKAF.ReferenceResourceRelease) in graph
    assert (release, RKAF.membershipMode, RKAF.partialMembership) in graph
    # The bundle declared itself development-only; the projection republishes
    # that declaration rather than dropping or overriding it.
    assert (release, ATLAS.operationalState, Literal("developmentOnly")) in graph
    assert (release, ATLAS.acceptedOutputAllowed, Literal(False)) in graph
    assert (release, ATLAS.candidateLookupAllowed, Literal(True)) in graph


def test_projection_copies_labels_notes_hierarchy_and_the_use_pair(tmp_path: Path) -> None:
    _source, asset = _fixture_atlas(tmp_path)
    graph = _release_facts(asset)
    ability = URIRef("https://www.icpsr.umich.edu/web/ICPSR/thesaurus/10001/terms/24042")
    talent = URIRef("https://www.icpsr.umich.edu/web/ICPSR/thesaurus/10001/terms/27405")
    abolition = URIRef("https://www.icpsr.umich.edu/web/ICPSR/thesaurus/10001/terms/24043")
    movements = URIRef("https://www.icpsr.umich.edu/web/ICPSR/thesaurus/10001/terms/27251")
    slavery = URIRef("https://www.icpsr.umich.edu/web/ICPSR/thesaurus/10001/terms/27209")

    assert (ability, SKOS.prefLabel, Literal("ability", lang="en")) in graph
    assert (ability, SKOS.notation, Literal("24042")) in graph
    assert (ability, SKOS.inScheme, URIRef(ICPSR_SUBJECT_SCHEME_IRI)) in graph
    # A non-preferred ICPSR term is a concept with its own published URI, so it
    # keeps that identity and its own label role instead of collapsing into an
    # alternate label on the descriptor.
    assert (talent, SKOS.altLabel, Literal("talent", lang="en")) in graph
    assert (talent, SKOS.prefLabel, None) not in graph
    assert (talent, ATLAS.thesaurusUse, ability) in graph
    assert (ability, ATLAS.thesaurusUsedFor, talent) in graph
    assert (ability, SKOS.altLabel, Literal("talent", lang="en")) not in graph

    assert (abolition, SKOS.broader, movements) in graph
    assert (abolition, SKOS.related, slavery) in graph
    assert (
        abolition,
        SKOS.scopeNote,
        Literal(
            "Refers to the United States Abolition movement during the 1800s to end slavery.",
            lang="en",
        ),
    ) in graph
    assert asset.manifest["counts"]["hierarchyEdges"] == 1


def test_hierarchy_reads_back_through_the_shared_atlas_queries(tmp_path: Path) -> None:
    _source, asset = _fixture_atlas(tmp_path)
    queries = VocabularyAtlasQueries(asset)
    abolition = "https://www.icpsr.umich.edu/web/ICPSR/thesaurus/10001/terms/24043"
    movements = "https://www.icpsr.umich.edu/web/ICPSR/thesaurus/10001/terms/27251"

    assert queries.broader(abolition) == (movements,)
    assert queries.narrower(movements) == (abolition,)
    assert queries.hierarchy_edges() == ((abolition, movements),)
    assert queries.transitive_broader(abolition, max_depth=4) == (movements,)


def test_projection_reproduces_from_its_exact_pinned_inputs(tmp_path: Path) -> None:
    source, asset = _fixture_atlas(tmp_path)
    output = asset.write(tmp_path / "atlas")

    reproduced = VocabularyAtlasAsset.reproduce_from_inputs(
        output,
        releases=(source,),
        rulespec_core=_core_release(tmp_path),
        expected_manifest_digest=asset.manifest_digest,
        expected_output_digest=asset.output_digest,
    )
    assert reproduced.payload == asset.payload


def test_adapter_refuses_a_bundle_that_drops_its_development_marker(tmp_path: Path) -> None:
    manifest_path = _fixture_package(tmp_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["operationalState"] = "operational"
    manifest_path.write_text(canonical_json(manifest) + "\n", encoding="utf-8")

    with pytest.raises(VocabularyAtlasError, match="development-only|canonicalPayloadDigest"):
        PinnedIcpsrSubjectAtlasRelease.open(
            manifest_path,
            expected_manifest_digest=_file_digest(manifest_path),
        )


def _reseal(record: dict[str, object]) -> dict[str, object]:
    unsealed = {key: value for key, value in record.items() if key != "canonicalPayloadDigest"}
    digest = hashlib.sha256(canonical_json(unsealed).encode("utf-8")).hexdigest()
    return {**unsealed, "canonicalPayloadDigest": "sha256:" + digest}


def _forge(root: Path, relative: str, payload: bytes) -> None:
    """Rewrite one packaged artifact and re-seal the manifest around it.

    A bundle nobody can forge is a bundle whose checks are untested. This
    produces the shape an adversary would: internally consistent digests and a
    valid seal, differing only in the fact under test.
    """

    manifest_path = root / "managed-release.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    (root / relative).write_bytes(payload)
    manifest["artifacts"] = [
        (
            {
                **descriptor,
                "sha256": "sha256:" + hashlib.sha256(payload).hexdigest(),
                "byteLength": len(payload),
            }
            if descriptor["path"] == relative
            else descriptor
        )
        for descriptor in manifest["artifacts"]
    ]
    manifest_path.write_text(canonical_json(_reseal(manifest)) + "\n", encoding="utf-8")


def test_adapter_refuses_a_release_identifier_its_own_sources_did_not_derive(tmp_path: Path) -> None:
    manifest_path = _fixture_package(tmp_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["release"] = {**manifest["release"], "id": ICPSR_RELEASE_IRI_PREFIX + "0" * 64}
    manifest_path.write_text(canonical_json(_reseal(manifest)) + "\n", encoding="utf-8")

    with pytest.raises(VocabularyAtlasError, match="not derived from its own source digests"):
        PinnedIcpsrSubjectAtlasRelease.open(
            manifest_path,
            expected_manifest_digest=_file_digest(manifest_path),
        )


def test_adapter_refuses_records_and_expressions_that_state_different_text(tmp_path: Path) -> None:
    manifest_path = _fixture_package(tmp_path)
    root = manifest_path.parent
    concepts = [json.loads(line) for line in (root / "records/concepts.jsonl").read_bytes().splitlines()]
    # The concept rows now claim a label no indexed expression carries, and the
    # expressions carry one no concept row claims. Every digest still agrees.
    concepts[0]["officialLabel"] = "forged label"
    _forge(
        root,
        "records/concepts.jsonl",
        b"".join(canonical_json(row).encode("utf-8") + b"\n" for row in concepts),
    )

    source = PinnedIcpsrSubjectAtlasRelease.open(
        manifest_path,
        expected_manifest_digest=_file_digest(manifest_path),
    )
    with pytest.raises(VocabularyAtlasError, match="state different text"):
        source.verified_view()
    with pytest.raises(VocabularyAtlasError, match="state different text"):
        build_vocabulary_atlas((source,), rulespec_core=_core_release(tmp_path))


def test_advertised_command_routes_a_non_string_manifest_type_generically(tmp_path: Path) -> None:
    unreadable = tmp_path / "manifest.json"
    unreadable.write_text(json.dumps({"type": ["not", "a", "string"]}), encoding="utf-8")

    assert atlas_cli._detected_input_format(str(unreadable)) == atlas_cli.MANAGED_BUNDLE_FORMAT


def test_adapter_refuses_a_manifest_whose_pinned_bytes_differ(tmp_path: Path) -> None:
    manifest_path = _fixture_package(tmp_path)

    with pytest.raises(VocabularyAtlasError, match="manifest digest differs"):
        PinnedIcpsrSubjectAtlasRelease.open(
            manifest_path,
            expected_manifest_digest="sha256:" + "0" * 64,
        )


def test_advertised_command_detects_and_builds_the_icpsr_package(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    manifest_path = _fixture_package(tmp_path)
    core = _core_release(tmp_path)
    output = tmp_path / "cli-atlas"
    command = (
        "--managed-release",
        str(manifest_path),
        _file_digest(manifest_path),
        "--rulespec-core",
        str(core.path),
        "--rulespec-core-file-digest",
        core.file_digest,
        "--rulespec-core-release-id",
        core.release_id,
        "--rulespec-core-release-digest",
        core.release_digest,
        "--output",
        str(output),
    )

    assert atlas_main(command) == 0
    selection = json.loads(capsys.readouterr().out)
    reopened = VocabularyAtlasAsset.open(
        output,
        expected_manifest_digest=selection["manifestDigest"],
        expected_output_digest=selection["outputDigest"],
    )
    assert reopened.manifest["counts"]["hierarchyEdges"] == 1

    forced = tmp_path / "cli-atlas-forced"
    assert atlas_main((*command[:-1], str(forced), "--input-format", "icpsr-subject-thesaurus")) == 0
    with pytest.raises(ManagedReleaseError, match="bundle manifest contains unsupported fields"):
        atlas_main(
            (
                *command[:-1],
                str(tmp_path / "cli-atlas-wrong"),
                "--input-format",
                "managed-bundle",
            )
        )


def test_generation_identity_pins_the_icpsr_reader_and_its_drift(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = atlas_model._implementation_pin()
    modules = {row["path"]: row["digest"] for row in original["sourceModules"]}
    # Import-closed over the ICPSR reader: `controlled_identifier` is what
    # extracts the codes and term IRIs that become every concept IRI, so
    # leaving it out would let those change without changing the atlas id.
    required = {
        "refspec/atlas/icpsr.py",
        "refspec/registry/controlled_identifier.py",
        "refspec/registry/icpsr_managed_release.py",
        "refspec/registry/icpsr_subject.py",
    }
    assert required <= set(modules)
    for relative in required:
        assert modules[relative] == _file_digest(
            Path(atlas_model.__file__).parents[1] / relative.removeprefix("refspec/")
        )

    icpsr_path = Path(atlas_model.__file__).with_name("icpsr.py").resolve()
    read_bytes = Path.read_bytes

    def drifted_bytes(path: Path) -> bytes:
        payload = read_bytes(path)
        if path.resolve() == icpsr_path:
            return payload + b"\n# adversarial source drift\n"
        return payload

    monkeypatch.setattr(Path, "read_bytes", drifted_bytes)
    assert atlas_model._digest_value(original) != atlas_model._digest_value(atlas_model._implementation_pin())


def test_exact_2026_07_30_capture_reaches_the_atlas_with_its_measured_facts(
    tmp_path: Path,
) -> None:
    if not REAL_CAPTURE.is_dir():
        pytest.skip("ignored exact ICPSR capture is unavailable")

    managed = build_icpsr_managed_release(
        open_icpsr_managed_release_sources(REAL_CAPTURE),
        recorded_at=RECORDED_AT,
        recorded_by=REAL_RECORDED_BY,
        expected_gap_counts=(5, 45),
    )
    manifest_path = managed.write_to(tmp_path / "icpsr-real")
    source = PinnedIcpsrSubjectAtlasRelease.open(
        manifest_path,
        expected_manifest_digest=_file_digest(manifest_path),
    )
    view = source.verified_view()
    asset = build_vocabulary_atlas((source,), rulespec_core=_core_release(tmp_path))
    graph = _release_facts(asset)
    release = URIRef(view.reference_release_iri)

    assert len(set(graph.objects(release, PROV.hadMember))) == 3_760
    assert len(tuple(view.iter_expressions())) == 4_490
    # Measured from the 2026-07-30 capture rather than assumed: the release
    # states both hierarchy directions and they are exact inverses, so the
    # atlas admits them without touching the agreement refusal.
    assert asset.manifest["counts"]["hierarchyEdges"] == 1_759
    assert len(set(graph.subject_objects(SKOS.narrower))) == 1_759
    assert len(set(graph.subject_objects(SKOS.related))) == 14_360
    assert len(set(graph.subject_objects(SKOS.scopeNote))) == 730
    # Exactly the concepts' own labels: the scheme node states none, because
    # neither ICPSR source view gives the thesaurus a label to copy.
    assert len(set(graph.subject_objects(SKOS.prefLabel))) == 3_280
    assert len(set(graph.subject_objects(SKOS.altLabel))) == 480
    # ISO 25964 USE/UF is not reciprocal in this source, which is the reason
    # neither direction may be collapsed into an alternate label.
    assert len(set(graph.subject_objects(ATLAS.thesaurusUse))) == 479
    assert len(set(graph.subject_objects(ATLAS.thesaurusUsedFor))) == 394
    assert (release, ATLAS.operationalState, Literal("developmentOnly")) in graph
