from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from rdflib import Dataset, Graph, Literal, Namespace, URIRef
from rdflib.namespace import OWL, RDF, SKOS

ROOT = Path(__file__).resolve().parents[1]
BINDING_ROOT = ROOT / "bindings" / "atlas" / "3.1"
VALIDATOR_PATH = BINDING_ROOT / "tools" / "validate.py"
FIXTURE_BUILDER = BINDING_ROOT / "tools" / "build_fixtures.py"
VALID_DISTRIBUTION = BINDING_ROOT / "fixtures" / "valid" / "all-resource-profiles"
REQUIREMENTS = BINDING_ROOT / "requirements.txt"
MAKEFILE = ROOT / "Makefile"
ATLAS = Namespace("https://refspec.org/ns/atlas/v3#")
RKAF = Namespace("https://rulespec.org/ns/v1#")
SKOSXL = Namespace("http://www.w3.org/2008/05/skos-xl#")
sys.path.insert(0, str(BINDING_ROOT / "tools"))
import validate as atlas_validate


def test_mapping_predicate_translation_table_admits_only_live_source_translations() -> None:
    assert atlas_validate.ADMITTED_MAPPING_PREDICATE_TRANSLATIONS == {
        ("http://schema.org/sameAs", str(SKOS.exactMatch)),
        (
            "http://www.loc.gov/mads/rdf/v1#hasBroaderExternalAuthority",
            str(SKOS.broadMatch),
        ),
        (
            "http://www.loc.gov/mads/rdf/v1#hasCloseExternalAuthority",
            str(SKOS.closeMatch),
        ),
        ("https://www.loc.gov/marc/authority/ad750.html", str(SKOS.exactMatch)),
        ("https://www.loc.gov/marc/authority/ad750.html", str(SKOS.broadMatch)),
        ("https://www.loc.gov/marc/authority/ad750.html", str(SKOS.narrowMatch)),
        ("https://www.loc.gov/marc/authority/ad750.html", str(SKOS.relatedMatch)),
    }


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


def _standalone(
    *arguments: str,
    environment: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
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
        env={**os.environ, **(environment or {})},
    )


@pytest.mark.slow
def test_atlas_v3_binding_and_sealed_corpus_pass() -> None:
    completed = _standalone()
    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout) == {
        "caseCount": 174,
        "invalidCount": 151,
        "registryDescriptorCount": 106,
        "registryDescriptorQuadCount": 1252,
        "schemaCount": 10,
    }


@pytest.mark.slow
def test_memory_fallback_matches_the_sealed_corpus() -> None:
    """The stock store remains a complete oracle and operational fallback."""

    completed = _standalone(
        environment={atlas_validate.RDF_STORE_ENV: atlas_validate.MEMORY_STORE}
    )
    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout) == {
        "caseCount": 174,
        "invalidCount": 151,
        "registryDescriptorCount": 106,
        "registryDescriptorQuadCount": 1252,
        "schemaCount": 10,
    }


def _makefile_rule(name: str, makefile: Path | None = None) -> tuple[list[str], list[str]]:
    """Return one Makefile rule's prerequisites and its recipe, line-joined.

    ``makefile`` defaults to the repository's own, and is a parameter only so
    the mutation demonstration below can point the same parser at a temporary
    copy -- the Makefile itself is never written by these tests.
    """

    lines = (makefile or MAKEFILE).read_text(encoding="utf-8").splitlines()
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
    """`make test` reaches the sealed corpus through the slow tier, once.

    The corpus pass is one subprocess over the whole sealed corpus, run by
    ``test_atlas_v3_binding_and_sealed_corpus_pass`` above. That test is
    ``@pytest.mark.slow``, so `test-package`'s `-m "not slow"` does not run
    it -- only `test-slow` (`-m slow`) does. `test` must therefore list
    `test-slow` as a prerequisite, or the corpus (and the rest of the
    slow-marked tier) silently stops running under `make test`, which is
    exactly what happened between the slow-marking pass on 2026-08-23 and
    the fix that added this line: `test-package` was the only tier wired
    into `test`, so `make test` alone no longer reached the sealed corpus or
    the rest of the slow tier at all. `test` must also still not list
    `test-atlas-v3`: doing so would run the identical corpus subprocess a
    second time for the same answer, which is the waste this check has
    always guarded against. This check keeps all three parts of that claim
    true: `test-package` and `test-slow` are both listed, `test-atlas-v3` is
    not, and the standalone target still invokes exactly what
    ``_standalone()`` invokes.
    """

    prerequisites, _ = _makefile_rule("test")
    assert "test-package" in prerequisites
    assert "test-slow" in prerequisites, (
        "make test would skip the sealed corpus and the rest of the slow "
        "tier: test_atlas_v3_binding_and_sealed_corpus_pass is "
        "pytest.mark.slow, and only test-slow (-m slow) runs it"
    )
    assert "test-atlas-v3" not in prerequisites, (
        "make test would run the sealed corpus twice: the slow tier already "
        "covers test-atlas-v3 via test_atlas_v3_binding_and_sealed_corpus_pass"
    )

    _, recipe = _makefile_rule("test-atlas-v3")
    assert len(recipe) == 1
    assert [
        ROOT / token if token.startswith("bindings/") else token
        for token in recipe[0].split()
    ] == ["uv", "run", "--no-project", "--with-requirements", REQUIREMENTS, "python", VALIDATOR_PATH]

    # Listing both tiers is only half the claim. The other half is what each
    # tier SELECTS: `test-package` must take `not slow` and `test-slow` must
    # take `slow`, or the prerequisite list above is satisfied by a pair that
    # runs the corpus twice (both unfiltered) or not at all (both `not slow`).
    assert _slow_tier_partition_violation(MAKEFILE) is None
    assert _pytest_marker_expressions(_makefile_rule("test-package")[1]) == ["not slow"]
    assert _pytest_marker_expressions(_makefile_rule("test-slow")[1]) == ["slow"]


#: The two Makefile edits that keep every prerequisite assertion above green
#: while breaking what `make test` actually runs -- the hole review finding 10
#: found in this guard. Each is (description, old text, new text), applied to a
#: COPY of the Makefile; the real one is never written.
_SLOW_TIER_MUTATIONS = (
    (
        "test-package stops filtering, so the corpus runs in both tiers",
        'uv run pytest -q -n auto -m "not slow";',
        "uv run pytest -q -n auto;",
    ),
    (
        "test-slow takes `not slow` too, so the corpus runs in neither tier",
        "test-slow: atlas-v3-fixtures\n\tuv run pytest -q -n auto -m slow",
        'test-slow: atlas-v3-fixtures\n\tuv run pytest -q -n auto -m "not slow"',
    ),
)


def _pytest_marker_expressions(recipe: list[str]) -> list[str | None]:
    """Every ``-m`` selection the recipe's pytest invocations make, in order.

    A pytest command carrying no ``-m`` at all yields ``None`` rather than
    being skipped: "unfiltered" is one of the two mutations this has to catch,
    and a parser that only looked at the expressions it found would read an
    unfiltered command as no command.
    """

    found: list[str | None] = []
    for line in recipe:
        for command in line.split(";"):
            match = re.search(r"(?:^|\s)pytest(?:\s|$)", command)
            if match is None:
                continue
            selection = re.search(
                r"""\s-m\s+(?:"([^"]*)"|'([^']*)'|(\S+))""", command[match.end() :]
            )
            found.append(
                None if selection is None else next(g for g in selection.groups() if g is not None)
            )
    return found


def _slow_tier_partition_violation(makefile: Path) -> str | None:
    """Why `test-package` and `test-slow` do not partition the suite, or None.

    Evaluated with pytest's own marker-expression evaluator rather than by
    string match, so the question asked is the one that matters: for a test
    marked ``slow``, and for one that is not, does EXACTLY ONE of the two
    tiers select it? Two tiers selecting it is the sealed corpus running
    twice; none selecting it is the corpus not running at all under
    `make test`.
    """

    from _pytest.mark.expression import Expression

    selections = {}
    for target in ("test-package", "test-slow"):
        expressions = _pytest_marker_expressions(_makefile_rule(target, makefile)[1])
        if len(expressions) != 1:
            return f"{target} runs {len(expressions)} pytest commands, expected exactly 1"
        selections[target] = expressions[0]

    for marked in (True, False):
        selecting = [
            target
            for target, expression in selections.items()
            # No `-m` at all selects everything.
            if expression is None
            or Expression.compile(expression).evaluate(
                lambda name, marked=marked: marked and name == "slow"
            )
        ]
        if len(selecting) != 1:
            state = "slow-marked" if marked else "unmarked"
            return (
                f"{state} tests are selected by {len(selecting)} tier(s) "
                f"({', '.join(selecting) or 'none'}); selections were {selections}"
            )
    return None


def test_the_slow_tier_guard_rejects_a_makefile_that_breaks_the_partition(tmp_path: Path) -> None:
    """The guard above must fail under each mutation it exists to catch.

    Review finding 10: the guard asserted only that `test` lists
    `test-package` and `test-slow` and not `test-atlas-v3`. Both mutations
    below leave that prerequisite list untouched -- the first runs the sealed
    corpus twice, the second runs it zero times, and the old guard stayed
    green through either. Each is applied to a COPY of the Makefile, which is
    what the ``makefile`` parameter on ``_makefile_rule`` is for; the
    repository's Makefile is only ever read.
    """

    original = MAKEFILE.read_text(encoding="utf-8")
    for description, old, new in _SLOW_TIER_MUTATIONS:
        assert original.count(old) == 1, f"mutation no longer applies: {description}"
        mutated = tmp_path / f"Makefile.{abs(hash(description))}"
        mutated.write_text(original.replace(old, new, 1), encoding="utf-8")

        violation = _slow_tier_partition_violation(mutated)
        assert violation is not None, f"guard stayed green under: {description}"

    # And the unmutated copy is accepted, so the rejections above are the
    # mutations talking and not the copy itself.
    clean = tmp_path / "Makefile.clean"
    clean.write_text(original, encoding="utf-8")
    assert _slow_tier_partition_violation(clean) is None
    assert MAKEFILE.read_text(encoding="utf-8") == original


def test_all_resource_profiles_fixture_has_synthetic_semantic_coverage() -> None:
    completed = _standalone("--distribution", str(VALID_DISTRIBUTION))
    assert completed.returncode == 0, completed.stderr
    result = json.loads(completed.stdout)

    assert result["counts"] == {
        "crossRingRelationAssertions": 3,
        "derivedRelations": 1,
        "evidenceBindings": 13,
        "identifiers": 1,
        "labels": 27,
        "mappingAssertions": 5,
        "nativeRelationAssertions": 2,
        "projectedRelations": 13,
        "relationAssertions": 13,
        "releases": 16,
        "resources": 27,
        "sourceAssignments": 3,
        "sourceRecords": 27,
    }
    assert result["quadCount"] == 1474
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

    assert set(atlas_validate.evidence_warrant_axis_values()) == {
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
        and str(term).removeprefix(str(ATLAS))
        in atlas_validate.evidence_warrant_axis_values()
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


def _policy_node_digest(graph: Graph, node: URIRef) -> str:
    """Recompute one node's digest the way an independent reader must.

    `atlas:contentDigest` is off the wire for every carrier that does not
    derive its IRI from it -- an editorial policy's IRI *is* the digest -- so
    the assertion identity basis is checked here against a digest this test
    derives itself rather than one the artifact restates.
    """

    rows = sorted(
        f"{predicate.n3()} {obj.n3()} ." for predicate, obj in graph.predicate_objects(node)
    )
    return "sha256:" + hashlib.sha256(("\n".join(rows) + "\n").encode("utf-8")).hexdigest()



def test_assertion_identity_independently_excludes_lifecycle_and_evidence() -> None:
    _dataset, graphs, _manifest = _load_distribution()
    asserted = graphs["asserted"]
    assertion = next(asserted.subjects(RDF.type, ATLAS.MappingAssertion))
    policy = asserted.value(assertion, ATLAS.governedByPolicy)
    basis = {
        "object": str(asserted.value(assertion, RDF.object)),
        "policy": str(policy),
        "policyContentDigest": _policy_node_digest(asserted, policy),
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
        "policyContentDigest": _policy_node_digest(asserted, policy),
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
    for path in (
        VALIDATOR_PATH,
        BINDING_ROOT / "tools" / "parse_substrate.py",
    ):
        source = path.read_text(encoding="utf-8")
        assert "import refspec" not in source
        assert "from refspec" not in source


def _sandboxed_repository(tmp_path: Path) -> Path:
    """Copy the binding plus its one external input into a scratch repository.

    The builder resolves everything from its own location, so a faithful copy
    lets these tests tamper with real inputs without ever touching the
    committed corpus.
    """

    root = tmp_path / "repo"
    binding = root / "bindings" / "atlas" / "3.1"
    binding.parent.mkdir(parents=True)
    shutil.copytree(BINDING_ROOT, binding)
    adapter = root / "src" / "refspec" / "atlas" / "v3_source_data.py"
    adapter.parent.mkdir(parents=True)
    shutil.copy2(ROOT / "src" / "refspec" / "atlas" / "v3_source_data.py", adapter)
    return root


def _sandboxed_check(root: Path) -> subprocess.CompletedProcess[str]:
    binding = root / "bindings" / "atlas" / "3.1"
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


@pytest.mark.slow
def test_a_single_edited_fixture_byte_forces_the_rebuild_and_fails(tmp_path: Path) -> None:
    root = _sandboxed_repository(tmp_path)
    tampered = root / "bindings" / "atlas" / "3.1" / "fixtures" / "corpus.json"
    payload = tampered.read_bytes()
    tampered.write_bytes(payload.replace(b"all-resource-profiles", b"all-resource-profilez", 1))

    result = _sandboxed_check(root)

    # The receipt's output digest no longer matches, so the fast path is
    # refused, the full rebuild-and-diff runs, and it reports the difference.
    assert result.returncode != 0
    assert "receipt matches" not in result.stdout
    assert "Atlas 3.1 fixtures differ" in result.stdout + result.stderr


@pytest.mark.slow
def test_an_edited_builder_input_forces_the_rebuild(tmp_path: Path) -> None:
    root = _sandboxed_repository(tmp_path)
    ontology = root / "bindings" / "atlas" / "3.1" / "ontology" / "atlas.ttl"
    ontology.write_bytes(ontology.read_bytes() + b"\n# an input digest the receipt does not know\n")

    result = _sandboxed_check(root)

    # atlas.ttl determines the corpus through contractDigest, so a changed
    # byte must re-derive rather than trust the receipt.
    assert "receipt matches" not in result.stdout
    assert result.returncode != 0
    assert "Atlas 3.1 fixtures differ" in result.stdout + result.stderr


@pytest.mark.slow
def test_a_missing_or_unparseable_receipt_falls_back_to_the_rebuild(tmp_path: Path) -> None:
    root = _sandboxed_repository(tmp_path)
    receipt = root / "bindings" / "atlas" / "3.1" / "fixtures-receipt.json"

    receipt.write_bytes(b"{ this is not json")
    unparseable = _sandboxed_check(root)
    assert unparseable.returncode == 0, unparseable.stderr
    assert "rebuilt and compared" in unparseable.stdout

    receipt.unlink()
    missing = _sandboxed_check(root)
    assert missing.returncode == 0, missing.stderr
    assert "rebuilt and compared" in missing.stdout


def test_tool_edits_do_not_move_the_contract_digest_but_ontology_edits_do() -> None:
    """`contractDigest` pins what conformance means, not what computed it.

    Every case's manifest and acceptance record carries this digest, so
    whatever it covers must be reissued across the full corpus whenever it moves.
    Keeping the tools inside it meant a one-line edit to the builder or the
    validator reissued the whole corpus for a contract that had not changed.
    Which validator produced a verdict is still pinned, separately and by name,
    through VALIDATOR_ID/VALIDATOR_VERSION.
    """

    baseline = atlas_validate._binding_digests()["contractDigest"]

    for contract in (
        "admitted-derived-rules.json",
        "ontology/atlas.ttl",
        "shapes/atlas.shacl.ttl",
    ):
        changed = (BINDING_ROOT / contract).read_bytes() + b"\n# contract comment\n"
        digests = atlas_validate._binding_digests(content_overrides={Path(contract): changed})
        assert digests["contractDigest"] != baseline, f"{contract} must reissue the corpus"

    # The tools are not in the contract at all, so it cannot even be asked
    # about them -- an edit to one leaves every fixture valid.
    for tool in atlas_validate.BINDING_TOOL_PATHS:
        with pytest.raises(atlas_validate.AtlasValidationError, match="not in the contract"):
            atlas_validate._binding_digests(content_overrides={tool: b"# edited tool\n"})

    assert Path("README.md") not in atlas_validate.CONTRACT_PATHS


def test_derived_rule_registry_is_contract_covered_and_matches_the_executable_roster() -> None:
    relative = Path("admitted-derived-rules.json")
    assert relative in atlas_validate.CONTRACT_PATHS
    document = atlas_validate._load_json(
        BINDING_ROOT / relative,
        require_canonical=True,
    )
    assert document == atlas_validate._derived_rule_registry_document()
    assert atlas_validate._check_derived_rule_registry() == document
    assert len(document["rules"]) == 6


def test_derived_rule_registry_refuses_semantic_drift_from_the_executable_roster() -> None:
    document = json.loads(
        json.dumps(atlas_validate._derived_rule_registry_document())
    )
    document["rules"][0]["admittedPredicates"] = [str(SKOS.closeMatch)]

    with pytest.raises(atlas_validate.AtlasValidationError) as exc_info:
        atlas_validate._check_derived_rule_registry(document)

    assert exc_info.value.code == "binding.derived-rule-registry"


def test_growing_the_conformance_corpus_leaves_the_contract_where_it_was() -> None:
    """Contract identity and proof identity are two different questions.

    `fixtures/corpus.json` used to sit inside the contract digest, so adding one
    conformance case moved `binding.contractDigest` in every manifest, every
    acceptance record and every construction summary on disk -- breaking the
    external manifest pins and invalidating a signed release for a contract
    that had not changed a byte. The corpus is what proves the VALIDATOR, so it
    is recorded where the validation event is described: beside the validator
    identity in the acceptance record (REF-029).
    """

    assert Path("fixtures/corpus.json") not in atlas_validate.CONTRACT_PATHS
    with pytest.raises(atlas_validate.AtlasValidationError, match="not in the contract"):
        atlas_validate._binding_digests(
            content_overrides={Path("fixtures/corpus.json"): b'{"cases": []}'}
        )

    acceptance = json.loads(
        (VALID_DISTRIBUTION / "atlas-acceptance.json").read_text(encoding="utf-8")
    )
    manifest = json.loads(
        (VALID_DISTRIBUTION / "atlas-manifest.json").read_text(encoding="utf-8")
    )
    assert acceptance["corpusDigest"] == atlas_validate.corpus_digest()
    assert acceptance["validator"] == {
        "name": atlas_validate.VALIDATOR_ID,
        "version": atlas_validate.VALIDATOR_VERSION,
    }
    assert "corpusDigest" not in manifest["binding"]
    assert "corpusDigest" not in acceptance["inputs"]


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
