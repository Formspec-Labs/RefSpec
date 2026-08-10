from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from rdflib import Dataset, Graph, Literal, Namespace, URIRef
from rdflib.namespace import OWL, RDF, SKOS

ROOT = Path(__file__).resolve().parents[1]
BINDING_ROOT = ROOT / "bindings" / "atlas" / "3.0"
VALIDATOR_PATH = BINDING_ROOT / "tools" / "validate.py"
FIXTURE_BUILDER = BINDING_ROOT / "tools" / "build_fixtures.py"
VALID_DISTRIBUTION = BINDING_ROOT / "fixtures" / "valid" / "all-resource-profiles"
REQUIREMENTS = BINDING_ROOT / "requirements.txt"
ATLAS = Namespace("https://refspec.org/ns/atlas/v3#")
RKAF = Namespace("https://rulespec.org/ns/v1#")
SKOSXL = Namespace("http://www.w3.org/2008/05/skos-xl#")
sys.path.insert(0, str(BINDING_ROOT / "tools"))
import validate as atlas_validate


def _load_distribution(
    distribution: Path = VALID_DISTRIBUTION,
) -> tuple[Dataset, dict[str, Graph], dict[str, object]]:
    manifest = json.loads(
        (distribution / "atlas-manifest.json").read_text(encoding="utf-8")
    )
    graph_ids = atlas_validate._check_pack_manifest(manifest)
    dataset, graphs = atlas_validate._parse_packed_dataset(
        distribution, manifest, graph_ids
    )
    return dataset, graphs, manifest


def _rdf_pack_text(distribution: Path = VALID_DISTRIBUTION) -> str:
    manifest = json.loads(
        (distribution / "atlas-manifest.json").read_text(encoding="utf-8")
    )
    payloads: list[bytes] = []
    for pack in manifest["packs"]:
        stored = (distribution / pack["path"]).read_bytes()
        payloads.append(
            atlas_validate.zstd.decompress(stored)
            if pack["transport"]["compression"] == "zstd"
            else stored
        )
    return b"".join(payloads).decode("utf-8")


def _standalone(*arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            "uv",
            "run",
            "--no-project",
            "--with-requirements",
            str(REQUIREMENTS),
            "python",
            str(VALIDATOR_PATH),
            *arguments,
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )


def test_atlas_v3_binding_and_sealed_corpus_pass() -> None:
    completed = _standalone()
    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout) == {
        "caseCount": 121,
        "invalidCount": 108,
        "registryDescriptorCount": 88,
        "registryDescriptorQuadCount": 1171,
        "schemaCount": 10,
    }


def _makefile_rule(name: str) -> tuple[list[str], list[str]]:
    """Return one Makefile rule's prerequisites and its recipe, line-joined."""

    lines = (ROOT / "Makefile").read_text(encoding="utf-8").splitlines()
    for index, line in enumerate(lines):
        if not line.startswith(f"{name}:"):
            continue
        prerequisites = line.split(":", 1)[1].split()
        recipe: list[str] = []
        pending = ""
        for follower in lines[index + 1 :]:
            if not follower.startswith("\t"):
                break
            pending += follower.strip()
            if pending.endswith("\\"):
                pending = pending[:-1] + " "
                continue
            recipe.append(pending)
            pending = ""
        return prerequisites, recipe
    raise AssertionError(f"Makefile has no rule named {name!r}")


def test_the_aggregate_test_target_runs_the_sealed_corpus_exactly_once() -> None:
    """`make test` drops `test-atlas-v3` because this module already runs it.

    The corpus pass is the single most expensive thing the suite does (~205s).
    Running it from both the Makefile and pytest cost that twice for one
    answer. The aggregate target now relies on
    ``test_atlas_v3_binding_and_sealed_corpus_pass`` above, so this check
    keeps the two halves of that claim true: the standalone target must still
    invoke exactly what ``_standalone()`` invokes, and ``test`` must not list
    it a second time.
    """

    prerequisites, _ = _makefile_rule("test")
    assert "test-package" in prerequisites
    assert "test-atlas-v3" not in prerequisites, (
        "make test would run the 110-case corpus twice: test-package already "
        "covers test-atlas-v3 via test_atlas_v3_binding_and_sealed_corpus_pass"
    )

    _, recipe = _makefile_rule("test-atlas-v3")
    assert len(recipe) == 1
    assert [
        ROOT / token if token.startswith("bindings/") else token
        for token in recipe[0].split()
    ] == ["uv", "run", "--no-project", "--with-requirements", REQUIREMENTS, "python", VALIDATOR_PATH]


def test_all_resource_profiles_fixture_has_synthetic_semantic_coverage() -> None:
    completed = _standalone("--distribution", str(VALID_DISTRIBUTION))
    assert completed.returncode == 0, completed.stderr
    result = json.loads(completed.stdout)

    assert result["counts"] == {
        "crossRingRelationAssertions": 3,
        "derivedRelations": 1,
        "identifiers": 1,
        "labels": 11,
        "mappingAssertions": 4,
        "nativeRelationAssertions": 2,
        "projectedRelations": 12,
        "relationAssertions": 12,
        "releases": 9,
        "resources": 11,
        "sourceAssignments": 3,
        "sourceRecords": 11,
    }
    assert result["quadCount"] == 1042
    assert result["inferredMappingCount"] == 7


def test_cross_ring_assertions_project_with_both_ring_directions() -> None:
    _dataset, graphs, _manifest = _load_distribution()
    asserted = graphs["asserted"]
    projection = graphs["projection"]
    assertions = set(
        asserted.subjects(RDF.type, ATLAS.CrossRingRelationAssertion)
    )

    assert len(assertions) == 3
    assert {
        (
            asserted.value(assertion, ATLAS.sourceRing),
            asserted.value(assertion, RDF.predicate),
            asserted.value(assertion, ATLAS.targetRing),
        )
        for assertion in assertions
    } == {
        (ATLAS.entity, ATLAS.hasIndexedSubject, ATLAS.subject),
        (ATLAS.legalIdentity, ATLAS.hasIndexedSubject, ATLAS.subject),
        (ATLAS.entity, ATLAS.referencesLegalIdentity, ATLAS.legalIdentity),
    }
    for assertion in assertions:
        assert asserted.value(assertion, ATLAS.semanticRing) is None
        triple = (
            asserted.value(assertion, RDF.subject),
            asserted.value(assertion, RDF.predicate),
            asserted.value(assertion, RDF.object),
        )
        assert triple in projection
        projected = list(projection.subjects(ATLAS.supportingAssertion, assertion))
        assert len(projected) == 1
        record = projected[0]
        assert projection.value(record, ATLAS.sourceRing) == asserted.value(
            assertion, ATLAS.sourceRing
        )
        assert projection.value(record, ATLAS.targetRing) == asserted.value(
            assertion, ATLAS.targetRing
        )
        assert projection.value(record, ATLAS.semanticRing) is None


def test_exact_match_entailment_does_not_become_an_editorial_assertion() -> None:
    _dataset, graphs, _manifest = _load_distribution()
    source = URIRef("urn:ref:atlas-fixture:resource:subject-a")
    target = URIRef("urn:ref:atlas-fixture:resource:subject-c")

    assert (source, SKOS.exactMatch, target) not in graphs["projection"]
    assert any(
        graphs["derived"].value(node, ATLAS.relationSubject) == source
        and graphs["derived"].value(node, ATLAS.relationPredicate) == SKOS.exactMatch
        and graphs["derived"].value(node, ATLAS.relationObject) == target
        for node in graphs["derived"].subjects(RDF.type, ATLAS.DerivedRelation)
    )
    assert not any(
        graphs["asserted"].value(assertion, RDF.subject) == source
        and graphs["asserted"].value(assertion, RDF.predicate) == SKOS.exactMatch
        and graphs["asserted"].value(assertion, RDF.object) == target
        for assertion in graphs["asserted"].subjects(RDF.type, ATLAS.MappingAssertion)
    )


def test_ontology_uses_the_declared_safe_local_profile() -> None:
    graph = Graph().parse(BINDING_ROOT / "ontology" / "atlas.ttl", format="turtle")

    forbidden_types = {
        OWL.FunctionalProperty,
        OWL.InverseFunctionalProperty,
        OWL.TransitiveProperty,
        OWL.SymmetricProperty,
        OWL.Restriction,
    }
    assert not any(
        any(graph.triples((None, RDF.type, value))) for value in forbidden_types
    )
    assert not any(graph.triples((None, OWL.propertyChainAxiom, None)))
    assert not any(
        str(subject).startswith(str(SKOS)) or str(subject).startswith(str(SKOSXL))
        for subject in graph.subjects()
    )

    graph.add((ATLAS.injected, OWL.inverseOf, ATLAS.other))
    with pytest.raises(atlas_validate.AtlasValidationError, match="ontology.profile"):
        atlas_validate._lint_ontology(graph)


def test_review_warrants_describe_basis_without_product_permission() -> None:
    """The six warrants survive the decomposition, and stay warrants.

    atlas:reviewMethod was one enum conflating four Rulespec axes. Splitting it
    would ordinarily lose the closure, so the admissible combinations are
    enumerated instead -- still six, still distinguishable, and still saying
    only what grounds a claim rather than what a consumer may do with it.
    """

    graph = Graph().parse(BINDING_ROOT / "ontology" / "atlas.ttl", format="turtle")

    assert set(atlas_validate.EVIDENCE_WARRANTS) == {
        "deterministicTransformation",
        "humanReview",
        "operatorAdoption",
        "publisherAssertion",
        "trustedPipelineReview",
        "twoMachineAdjudication",
    }
    # No warrant survived as an atlas: term: the axes are Rulespec's, and a
    # leftover atlas:humanReview would be the parallel vocabulary this wave
    # removed.
    assert not any(
        str(term).startswith(str(ATLAS))
        and str(term).removeprefix(str(ATLAS)) in atlas_validate.EVIDENCE_WARRANTS
        for term in graph.all_nodes()
    )
    assert not any(
        keyword in str(term).lower()
        for term in graph.all_nodes()
        for keyword in ("ceiling", "eligibility", "searchonly", "usagepermission")
    )


def test_canonical_rdf_renderer_escapes_terms_without_false_blank_nodes() -> None:
    literal = Literal('line one\nline\ttwo "quoted" — café _:not-a-node', lang="en")
    assert atlas_validate.ntriples_term(literal) == (
        '"line one\\nline\\ttwo \\"quoted\\" — café _:not-a-node"@en'
    )
    dataset_text = _rdf_pack_text()
    assert "\\nline\\ttwo" in dataset_text
    assert '\\"quoted\\"' in dataset_text
    assert "_:not-a-node" in dataset_text


def test_multi_ring_scheme_is_selected_by_ring_specific_releases() -> None:
    _dataset, graphs, _manifest = _load_distribution()
    asserted = graphs["asserted"]
    scheme = URIRef("urn:ref:atlas-fixture:scheme:mixed-code")

    assert set(asserted.objects(scheme, ATLAS.supportedRing)) == {
        ATLAS.subject,
        ATLAS.value,
    }
    assert not list(asserted.objects(scheme, ATLAS.semanticRing))
    assert (scheme, RDF.type, SKOS.ConceptScheme) in asserted
    release_rings = {
        asserted.value(release, ATLAS.semanticRing)
        for release in asserted.subjects(ATLAS.inScheme, scheme)
        if (release, RDF.type, ATLAS.AtlasRelease) in asserted
    }
    assert release_rings == {ATLAS.subject, ATLAS.value}


def test_supersession_projects_only_the_terminal_current_claim() -> None:
    distribution = (
        BINDING_ROOT / "fixtures" / "valid" / "superseded-policy-revision"
    )
    completed = _standalone("--distribution", str(distribution))
    assert completed.returncode == 0, completed.stderr
    _dataset, graphs, _manifest = _load_distribution(distribution)
    asserted = graphs["asserted"]
    projection = graphs["projection"]
    # An assertion carries no stored status: the successor names its
    # predecessor via rkaf:supersedesAssertion, and the predecessor is
    # superseded exactly because something names it that way.
    successor, old = next(iter(asserted.subject_objects(RKAF.supersedesAssertion)))

    assert successor not in {
        target for _subject, target in asserted.subject_objects(RKAF.supersedesAssertion)
    }
    assert old not in set(projection.objects(None, ATLAS.supportingAssertion))
    assert successor in set(projection.objects(None, ATLAS.supportingAssertion))


def test_assertion_identity_independently_excludes_lifecycle_and_evidence() -> None:
    _dataset, graphs, _manifest = _load_distribution()
    asserted = graphs["asserted"]
    assertion = next(asserted.subjects(RDF.type, ATLAS.MappingAssertion))
    policy = asserted.value(assertion, ATLAS.governedByPolicy)
    basis = {
        "object": str(asserted.value(assertion, RDF.object)),
        "policy": str(policy),
        "policyContentDigest": str(asserted.value(policy, ATLAS.contentDigest)),
        "predicate": str(asserted.value(assertion, RDF.predicate)),
        "semanticRing": str(asserted.value(assertion, ATLAS.semanticRing)),
        "sourceRelease": str(asserted.value(assertion, ATLAS.sourceRelease)),
        "subject": str(asserted.value(assertion, RDF.subject)),
        "targetRelease": str(asserted.value(assertion, ATLAS.targetRelease)),
        "type": str(ATLAS.MappingAssertion),
    }
    payload = (
        json.dumps(
            basis,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode()
    digest = "sha256:" + hashlib.sha256(payload).hexdigest()

    assert asserted.value(assertion, ATLAS.assertionIdentityDigest) == Literal(digest)
    assert str(assertion) == "urn:ref:atlas-assertion:" + digest.removeprefix("sha256:")
    assert not ({"assertedAt", "status", "supersedes", "evidence"} & basis.keys())


def test_cross_ring_assertion_identity_uses_both_directed_rings() -> None:
    _dataset, graphs, _manifest = _load_distribution()
    asserted = graphs["asserted"]
    assertion = next(
        asserted.subjects(RDF.type, ATLAS.CrossRingRelationAssertion)
    )
    policy = asserted.value(assertion, ATLAS.governedByPolicy)
    basis = {
        "object": str(asserted.value(assertion, RDF.object)),
        "policy": str(policy),
        "policyContentDigest": str(asserted.value(policy, ATLAS.contentDigest)),
        "predicate": str(asserted.value(assertion, RDF.predicate)),
        "sourceRelease": str(asserted.value(assertion, ATLAS.sourceRelease)),
        "sourceRing": str(asserted.value(assertion, ATLAS.sourceRing)),
        "subject": str(asserted.value(assertion, RDF.subject)),
        "targetRelease": str(asserted.value(assertion, ATLAS.targetRelease)),
        "targetRing": str(asserted.value(assertion, ATLAS.targetRing)),
        "type": str(ATLAS.CrossRingRelationAssertion),
    }
    payload = (
        json.dumps(
            basis,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode()
    digest = "sha256:" + hashlib.sha256(payload).hexdigest()

    assert asserted.value(assertion, ATLAS.assertionIdentityDigest) == Literal(digest)
    assert str(assertion) == "urn:ref:atlas-assertion:" + digest.removeprefix("sha256:")
    assert "semanticRing" not in basis


def test_fixture_corpus_rebuild_is_exact() -> None:
    result = subprocess.run(
        [
            "uv",
            "run",
            "--no-project",
            "--with-requirements",
            str(REQUIREMENTS),
            "python",
            str(FIXTURE_BUILDER),
            "--check",
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


def test_portable_validator_does_not_import_refspec() -> None:
    source = VALIDATOR_PATH.read_text(encoding="utf-8")
    assert "import refspec" not in source
    assert "from refspec" not in source


def _sandboxed_repository(tmp_path: Path) -> Path:
    """Copy the binding plus its one external input into a scratch repository.

    The builder resolves everything from its own location, so a faithful copy
    lets these tests tamper with real inputs without ever touching the
    committed corpus.
    """

    root = tmp_path / "repo"
    binding = root / "bindings" / "atlas" / "3.0"
    binding.parent.mkdir(parents=True)
    shutil.copytree(BINDING_ROOT, binding)
    adapter = root / "src" / "refspec" / "atlas" / "v3_source_data.py"
    adapter.parent.mkdir(parents=True)
    shutil.copy2(ROOT / "src" / "refspec" / "atlas" / "v3_source_data.py", adapter)
    return root


def _sandboxed_check(root: Path) -> subprocess.CompletedProcess[str]:
    binding = root / "bindings" / "atlas" / "3.0"
    return subprocess.run(
        [
            "uv",
            "run",
            "--no-project",
            "--with-requirements",
            str(binding / "requirements.txt"),
            "python",
            str(binding / "tools" / "build_fixtures.py"),
            "--check",
        ],
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
    )


def test_fixture_receipt_fast_path_passes_on_a_clean_tree(tmp_path: Path) -> None:
    result = _sandboxed_check(_sandboxed_repository(tmp_path))

    assert result.returncode == 0, result.stderr
    assert "receipt matches" in result.stdout
    assert "rebuilt and compared" not in result.stdout


def test_a_single_edited_fixture_byte_forces_the_rebuild_and_fails(tmp_path: Path) -> None:
    root = _sandboxed_repository(tmp_path)
    tampered = root / "bindings" / "atlas" / "3.0" / "fixtures" / "corpus.json"
    payload = tampered.read_bytes()
    tampered.write_bytes(payload.replace(b"all-resource-profiles", b"all-resource-profilez", 1))

    result = _sandboxed_check(root)

    # The receipt's output digest no longer matches, so the fast path is
    # refused, the full rebuild-and-diff runs, and it reports the difference.
    assert result.returncode != 0
    assert "receipt matches" not in result.stdout
    assert "Atlas 3.0 fixtures differ" in result.stdout + result.stderr


def test_an_edited_builder_input_forces_the_rebuild(tmp_path: Path) -> None:
    root = _sandboxed_repository(tmp_path)
    ontology = root / "bindings" / "atlas" / "3.0" / "ontology" / "atlas.ttl"
    ontology.write_bytes(ontology.read_bytes() + b"\n# an input digest the receipt does not know\n")

    result = _sandboxed_check(root)

    # atlas.ttl determines the corpus through bindingBundleDigest, so a changed
    # byte must re-derive rather than trust the receipt.
    assert "receipt matches" not in result.stdout
    assert result.returncode != 0
    assert "Atlas 3.0 fixtures differ" in result.stdout + result.stderr


def test_a_missing_or_unparseable_receipt_falls_back_to_the_rebuild(tmp_path: Path) -> None:
    root = _sandboxed_repository(tmp_path)
    receipt = root / "bindings" / "atlas" / "3.0" / "fixtures-receipt.json"

    receipt.write_bytes(b"{ this is not json")
    unparseable = _sandboxed_check(root)
    assert unparseable.returncode == 0, unparseable.stderr
    assert "rebuilt and compared" in unparseable.stdout

    receipt.unlink()
    missing = _sandboxed_check(root)
    assert missing.returncode == 0, missing.stderr
    assert "rebuilt and compared" in missing.stdout


def test_tool_edits_do_not_move_the_contract_digest_but_ontology_edits_do() -> None:
    """`bindingBundleDigest` pins what conformance means, not what computed it.

    Every case's manifest and acceptance record carries this digest, so
    whatever it covers must be reissued across all 110 cases whenever it moves.
    Keeping the tools inside it meant a one-line edit to the builder or the
    validator reissued the whole corpus for a contract that had not changed.
    Which validator produced a verdict is still pinned, separately and by name,
    through VALIDATOR_ID/VALIDATOR_VERSION.
    """

    baseline = atlas_validate._binding_digests()["bindingBundleDigest"]

    for contract in ("ontology/atlas.ttl", "shapes/atlas.shacl.ttl"):
        changed = (BINDING_ROOT / contract).read_bytes() + b"\n# contract comment\n"
        digests = atlas_validate._binding_digests(content_overrides={Path(contract): changed})
        assert digests["bindingBundleDigest"] != baseline, f"{contract} must reissue the corpus"

    # The tools are not bundled at all, so the bundle cannot even be asked
    # about them -- an edit to one leaves every fixture valid.
    for tool in atlas_validate.BINDING_TOOL_PATHS:
        with pytest.raises(atlas_validate.AtlasValidationError, match="not bundled"):
            atlas_validate._binding_digests(content_overrides={tool: b"# edited tool\n"})

    assert Path("README.md") not in atlas_validate.BINDING_BUNDLE_PATHS


def test_the_hoisted_longest_test_still_exists() -> None:
    """conftest.py names one test to schedule first; keep that pointer honest.

    The hook stays silent when the id is absent, so that a narrower run can
    collect part of this module without tripping over it. This is the check
    that notices instead -- a rename or removal fails here rather than quietly
    costing the suite ~34s of serial tail forever.
    """

    import conftest

    module, _, name = conftest.LONGEST_TEST.partition("::")
    assert module == Path(__file__).relative_to(ROOT).as_posix()
    assert name in globals(), f"{conftest.LONGEST_TEST} no longer exists; repoint LONGEST_TEST"
