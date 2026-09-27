"""Pin the Atlas 3.1 binding's sealed corpus, validator portability, contract digests, and Makefile tiers."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from rdflib import Dataset, Graph, Literal, Namespace, URIRef
from rdflib.namespace import OWL, RDF, RDFS, SKOS

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
    """Pin the admitted translation set to exactly the seven live source predicates."""

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
    """Parse the packed distribution into a dataset, its named graphs, and the manifest."""

    manifest = json.loads(
        (distribution / "atlas-manifest.json").read_text(encoding="utf-8")
    )
    graph_ids = atlas_validate._check_pack_manifest(manifest)
    dataset, graphs = atlas_validate._parse_packed_dataset(
        distribution, manifest, graph_ids
    )
    return dataset, graphs, manifest


def _rdf_pack_text(distribution: Path = VALID_DISTRIBUTION) -> str:
    """Return the concatenated decompressed pack text of the distribution."""

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
    """Run the binding validator under uv with the binding's pinned requirements."""

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
    """Pin the standalone validator's exit 0 and the frozen corpus counts."""

    completed = _standalone()
    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout) == {
        "caseCount": 190,
        "invalidCount": 165,
        "registryDescriptorCount": 106,
        "registryDescriptorQuadCount": 1257,
        "schemaCount": 10,
    }


@pytest.mark.slow
def test_memory_fallback_matches_the_sealed_corpus() -> None:
    """Pin that the memory-store fallback yields the same corpus counts as the stock store."""

    completed = _standalone(
        environment={atlas_validate.RDF_STORE_ENV: atlas_validate.MEMORY_STORE}
    )
    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout) == {
        "caseCount": 190,
        "invalidCount": 165,
        "registryDescriptorCount": 106,
        "registryDescriptorQuadCount": 1257,
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
    """Pin that `make test` reaches the sealed corpus exactly once: both tiers listed, `test-atlas-v3` not, recipe
    matching ``_standalone()``.

    The corpus pass is ``@pytest.mark.slow``, so only `test-slow` (`--tier slow`)
    runs it; dropping it silently stopped the whole slow tier under `make test`
    between the 2026-08-23 slow-marking pass and the fix. The ``full-atlas``
    tier is deliberately not part of `make test` (REF-071): it constructs the
    complete topology and is its own local target, `make test-full-atlas`.
    """

    prerequisites, _ = _makefile_rule("test")
    assert "test-package" in prerequisites
    assert "test-slow" in prerequisites, (
        "make test would skip the sealed corpus and the rest of the slow "
        "tier: test_atlas_v3_binding_and_sealed_corpus_pass is "
        "pytest.mark.slow, and only test-slow (--tier slow) runs it"
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
    # tier SELECTS: `test-package` must take `--tier fast` and `test-slow` must
    # take `--tier slow`, or the prerequisite list above is satisfied by a pair
    # that runs the corpus twice (both unfiltered) or not at all (both fast).
    assert _slow_tier_partition_violation(MAKEFILE) is None
    assert _pytest_tier_selections(_makefile_rule("test-package")[1]) == ["fast"]
    assert _pytest_tier_selections(_makefile_rule("test-slow")[1]) == ["slow"]


#: The two Makefile edits that keep every prerequisite assertion above green
#: while breaking what `make test` actually runs -- the hole review finding 10
#: found in this guard. Each is (description, old text, new text), applied to a
#: COPY of the Makefile; the real one is never written.
_SLOW_TIER_MUTATIONS = (
    (
        "test-package stops filtering, so the corpus runs in both tiers",
        "uv run pytest -q -n auto --tier fast $(PYTEST_ARGS);",
        "uv run pytest -q -n auto $(PYTEST_ARGS);",
    ),
    (
        "test-slow takes the fast tier too, so the corpus runs in neither",
        "uv run pytest -q -n $(SLOW_WORKERS) --tier slow $(PYTEST_ARGS)",
        "uv run pytest -q -n $(SLOW_WORKERS) --tier fast $(PYTEST_ARGS)",
    ),
)


def _pytest_tier_selections(recipe: list[str]) -> list[str | None]:
    """Every ``--tier`` selection the recipe's pytest invocations make, in order.

    A pytest command carrying no ``--tier`` at all yields ``None`` rather than
    being skipped: "unfiltered" is one of the two mutations this has to catch,
    and a parser that only looked at the selections it found would read an
    unfiltered command as no command.
    """

    found: list[str | None] = []
    for line in recipe:
        for command in line.split(";"):
            match = re.search(r"(?:^|\s)pytest(?:\s|$)", command)
            if match is None:
                continue
            selection = re.search(r"\s--tier\s+(\S+)", command[match.end() :])
            found.append(None if selection is None else selection.group(1))
    return found


def _slow_tier_partition_violation(makefile: Path) -> str | None:
    """Why `test-package` and `test-slow` do not partition the suite, or None.

    Evaluated through conftest.tier_of rather than by string match, so the
    question asked is the one that matters: for a test marked ``slow`` (the
    sealed corpus pass), and for one that is not, does EXACTLY ONE of the two
    targets select it? Two targets selecting it is the sealed corpus running
    twice; none selecting it is the corpus not running at all under
    `make test`.
    """

    from conftest import tier_of

    class _Marked:
        def __init__(self, *markers: str) -> None:
            self.markers = markers

        def get_closest_marker(self, name: str):
            return name if name in self.markers else None

    selections = {}
    for target in ("test-package", "test-slow"):
        tiers = _pytest_tier_selections(_makefile_rule(target, makefile)[1])
        if len(tiers) != 1:
            return f"{target} runs {len(tiers)} pytest commands, expected exactly 1"
        selections[target] = tiers[0]

    for marked in (True, False):
        tier = tier_of(_Marked("slow") if marked else _Marked())
        selecting = [
            target
            for target, selection in selections.items()
            # No `--tier` at all selects everything.
            if selection is None or selection == tier
        ]
        if len(selecting) != 1:
            state = "slow-marked" if marked else "unmarked"
            return (
                f"{state} tests are selected by {len(selecting)} tier(s) "
                f"({', '.join(selecting) or 'none'}); selections were {selections}"
            )
    return None


def test_the_slow_tier_guard_rejects_a_makefile_that_breaks_the_partition(tmp_path: Path) -> None:
    """Pin that the partition guard fails under both mutations (corpus twice, corpus never) and accepts the clean copy.

    Both mutations leave the prerequisite list untouched -- which is why the
    old guard stayed green through either -- and are applied to a copy, never
    the real Makefile.
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
    """Pin the all-profiles fixture's semantic counts, 1474 quads, and 7 inferred mappings."""

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
    """Pin the three cross-ring assertions and that each projects with both directed rings."""

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
    """Pin that an exactMatch entailment stays a derived relation, never an asserted mapping."""

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
    """Pin that the ontology avoids unsafe OWL constructs and SKOS subjects, and that an injected inverseOf is refused.
    """

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

    atlas_validate._lint_ontology(graph)
    specializes_skos = Graph()
    for triple in graph:
        specializes_skos.add(triple)
    specializes_skos.add((ATLAS.originalOrganization, RDFS.subPropertyOf, SKOS.exactMatch))
    with pytest.raises(atlas_validate.AtlasValidationError, match="specializes the SKOS property"):
        atlas_validate._lint_ontology(specializes_skos)

    graph.add((ATLAS.injected, OWL.inverseOf, ATLAS.other))
    with pytest.raises(atlas_validate.AtlasValidationError, match="ontology.profile"):
        atlas_validate._lint_ontology(graph)


def test_review_warrants_describe_basis_without_product_permission() -> None:
    """Pin the six admissible warrant-axis values and that no atlas: term or permission keyword survives.

    atlas:reviewMethod was one enum conflating four Rulespec axes; the closure
    is enumerated instead so it stays six, distinguishable, and about grounding
    rather than about what a consumer may do.
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
    """Pin that the renderer escapes newlines/tabs/quotes and leaves a literal's ``_:`` as text."""

    literal = Literal('line one\nline\ttwo "quoted" — café _:not-a-node', lang="en")
    assert atlas_validate.ntriples_term(literal) == (
        '"line one\\nline\\ttwo \\"quoted\\" — café _:not-a-node"@en'
    )
    dataset_text = _rdf_pack_text()
    assert "\\nline\\ttwo" in dataset_text
    assert '\\"quoted\\"' in dataset_text
    assert "_:not-a-node" in dataset_text


def test_multi_ring_scheme_is_selected_by_ring_specific_releases() -> None:
    """Pin that a multi-ring scheme takes supportedRing from its ring-specific releases, with no semanticRing."""

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
    """Pin that only the successor assertion projects while the superseded predecessor is dropped."""

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
    """Pin that the assertion digest recomputes from its nine basis fields and excludes lifecycle/evidence fields."""

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
    """Pin that cross-ring assertion identity includes both directed rings and no semanticRing."""

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
    """Pin that --check rebuilds the fixture corpus exactly."""

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
    """Pin that the binding's validator and substrate parser never import refspec."""

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
    """Run the fixture builder's --check inside the sandboxed copy."""

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
    """Pin that a clean tree takes the receipt fast path without rebuilding."""

    result = _sandboxed_check(_sandboxed_repository(tmp_path))

    assert result.returncode == 0, result.stderr
    assert "receipt matches" in result.stdout
    assert "rebuilt and compared" not in result.stdout


@pytest.mark.slow
def test_a_single_edited_fixture_byte_forces_the_rebuild_and_fails(tmp_path: Path) -> None:
    """Pin that one edited corpus byte defeats the receipt, forces the rebuild, and fails."""

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
    """Pin that a changed ontology byte forces re-derivation rather than trusting the receipt."""

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
    """Pin that a corrupt or absent receipt falls back to rebuild-and-compare."""

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


def _sandboxed_make_fixtures(root: Path) -> subprocess.CompletedProcess[str]:
    """Run `make atlas-v3-fixtures`, every tier's prerequisite, inside the sandboxed copy."""

    shutil.copy2(MAKEFILE, root / "Makefile")
    return subprocess.run(
        ["make", "--no-print-directory", "atlas-v3-fixtures"], cwd=root, check=False, capture_output=True, text=True
    )


def _stale_the_case_tree(fixtures: Path) -> tuple[Path, bytes, Path]:
    """Edit one byte of a valid case and add a case another commit had; return the edited file, its bytes, the stray."""

    edited = min((fixtures / "valid").rglob("atlas-acceptance.json"))
    original = edited.read_bytes()
    edited.write_bytes(original.replace(b"{", b"{ ", 1))
    stray = fixtures / "invalid" / "a-case-another-commit-had" / "atlas-manifest.json"
    stray.parent.mkdir()
    stray.write_bytes(b"{}\n")
    return edited, original, stray


def test_a_stale_or_mutated_case_file_is_not_the_tree_the_receipt_pins(tmp_path: Path, monkeypatch) -> None:
    """Pin that `make atlas-v3-fixtures`' question sees one edited byte under valid/ and one stray file under invalid/.

    Until 2026-09-27 the target asked only whether `valid/` existed, so the
    suite at another commit read the old commit's cases. The clean copy is the
    control, and the make run shows the target answers it without a rebuild.
    """

    import build_fixtures as atlas_fixtures

    root = _sandboxed_repository(tmp_path)
    fixtures = root / "bindings" / "atlas" / "3.1" / "fixtures"
    monkeypatch.setattr(atlas_fixtures, "FIXTURE_ROOT", fixtures)
    monkeypatch.setattr(atlas_fixtures, "GENERATED_ROOTS", (fixtures / "valid", fixtures / "invalid"))
    monkeypatch.setattr(atlas_fixtures, "RECEIPT_PATH", fixtures.parent / "fixtures-receipt.json")
    assert atlas_fixtures._tree_is_the_receipts()

    clean = _sandboxed_make_fixtures(root)
    assert clean.returncode == 0, clean.stderr
    assert "are the tree fixtures-receipt.json pins" in clean.stdout
    assert "rebuilding" not in clean.stdout

    edited, original, stray = _stale_the_case_tree(fixtures)
    assert not atlas_fixtures._tree_is_the_receipts()
    edited.write_bytes(original)
    assert not atlas_fixtures._tree_is_the_receipts(), "the stray alone"
    stray.unlink()
    stray.parent.rmdir()
    assert atlas_fixtures._tree_is_the_receipts()


@pytest.mark.slow
def test_make_atlas_v3_fixtures_rebuilds_a_stale_tree_to_the_receipts(tmp_path: Path) -> None:
    """Pin that the tiers' prerequisite replaces a stale case tree with the one the receipt pins (~20s rebuild)."""

    root = _sandboxed_repository(tmp_path)
    fixtures = root / "bindings" / "atlas" / "3.1" / "fixtures"
    edited, original, stray = _stale_the_case_tree(fixtures)

    result = _sandboxed_make_fixtures(root)

    assert result.returncode == 0, result.stderr
    assert "rebuilding" in result.stdout
    assert "matched the committed receipt" in result.stdout
    assert edited.read_bytes() == original
    assert not stray.parent.exists()
    assert _sandboxed_make_fixtures(root).stdout.count("are the tree fixtures-receipt.json pins") == 1


def test_tool_edits_do_not_move_the_contract_digest_but_ontology_edits_do() -> None:
    """Pin that the three contract inputs reissue contractDigest while tool edits are refused as not in the contract.

    Keeping the tools out means a one-line builder or validator edit no longer
    reissues the whole corpus for an unchanged contract; which validator
    produced a verdict is pinned separately by VALIDATOR_ID/VALIDATOR_VERSION.
    """

    baseline = atlas_validate._binding_digests()["contractDigest"]

    for contract in (
        "admitted-derived-rules.json",
        "ontology/atlas.ttl",
        "registry-resource-profiles.json",
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


#: A registry module the atlas index cites as source-implementation evidence and
#: the Federal Register release's adapter recipe does not pin. The recipe's three
#: files (see the release's construction summary) still move the release pins on
#: purpose: they are the code that built its pack (REF-073).
EDITED_REGISTRY_MODULE = "src/refspec/registry/billstatus_codes.py"
FR_RELEASE_INPUTS = (
    "output/registry-real-data-sources/federal-register-thesaurus-2025.pdf",
    "output/refspec-vocabulary-portfolio/federal-register-thesaurus-2025",
)


def _load_tool(name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "tools" / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _scratch_registry_repository(tmp_path: Path, *, release_inputs: bool = False) -> Path:
    """Copy what the registry generators read into a scratch repository, and with ``release_inputs`` what the
    Federal Register release build reads besides: the rest of the code, the binding, and its pinned inputs.

    The generated fixture cases are left behind (the build never reads them), and so is every file the index
    does not cite.
    """

    def skip(directory: str, names: list[str]) -> list[str]:
        generated = {"valid", "invalid"} if Path(directory).name == "fixtures" else set()
        return [name for name in names if name == "__pycache__" or name in generated]

    root = tmp_path / "registry-repo"
    for directory in ("src", "portfolio", *(("tools", "bindings") if release_inputs else ())):
        shutil.copytree(ROOT / directory, root / directory, ignore=skip)
    index = json.loads((ROOT / "portfolio" / "atlas-index-v0.json").read_text(encoding="utf-8"))
    cited = {item["path"] for row in index["rows"] for item in row["readinessEvidence"]}
    # A source-concept release's evidence names its package beside it, so the whole directory comes.
    cited |= {str(Path(row["release"]["evidencePath"]).parent) for row in index["rows"] if row["release"]}
    for relative in sorted(cited | set(FR_RELEASE_INPUTS if release_inputs else ())):
        source, target = ROOT / relative, root / relative
        if target.exists():
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        if source.is_dir():
            shutil.copytree(source, target, ignore=skip)
        else:
            shutil.copy2(source, target)
    return root


def _append_comment(path: Path) -> None:
    path.write_bytes(path.read_bytes() + b"\n# an edit that changes no behavior\n")


def test_a_registry_module_edit_leaves_the_contract_digest_where_it_was(tmp_path: Path) -> None:
    """Pin that the registry proofs regenerate byte-identical after a module edit (REF-073).

    The atlas index hashes every module it cites, and until REF-073 its digest
    carried those bytes into the registry coverage and descriptor proofs, two
    contract files, so a comment in any cited module moved `contractDigest` and
    the release pins. The edit still reaches the index -- its `evidenceDigest`
    moves, which is what makes the unchanged proofs mean something.
    """

    from refspec.atlas_index import build_atlas_index
    from refspec.resource_catalog import load_json

    coverage_tool = _load_tool("generate_atlas_v3_registry_coverage")
    descriptor_tool = _load_tool("generate_atlas_v3_registry_descriptors")
    root = _scratch_registry_repository(tmp_path)
    committed = load_json(ROOT / "portfolio" / "atlas-index-v0.json")
    implementations = {
        item["path"]
        for row in committed["rows"]
        for item in row["readinessEvidence"]
        if item["kind"] == "sourceImplementation"
    }
    assert EDITED_REGISTRY_MODULE in implementations, "an edit the index does not hash would prove nothing"

    _append_comment(root / EDITED_REGISTRY_MODULE)
    catalog = load_json(ROOT / "portfolio" / "resource-catalog-v0.json")
    profiles = load_json(BINDING_ROOT / "registry-resource-profiles.json")
    index = build_atlas_index(
        load_json(ROOT / "portfolio" / "atlas-index-input-v0.json"), catalog, repository_root=root
    )
    assert index["evidenceDigest"] != committed["evidenceDigest"]
    assert index["indexDigest"] == committed["indexDigest"]

    coverage = coverage_tool.render_json(
        coverage_tool.build_registry_coverage(catalog, index, profiles, repository_root=root)
    ).encode("utf-8")
    dataset, proof = descriptor_tool.build_registry_descriptors(catalog, index, profiles)
    regenerated = {
        Path("tests/registry-coverage.json"): coverage,
        Path("tests/registry-descriptors.json"): proof,
        Path("tests/registry-descriptors.nq"): dataset,
    }
    for relative, payload in regenerated.items():
        assert payload == (BINDING_ROOT / relative).read_bytes(), f"{relative} moved with a module edit"
    assert (
        atlas_validate._binding_digests(content_overrides=regenerated)["contractDigest"]
        == atlas_validate._binding_digests()["contractDigest"]
    )


def _contract_dev_pair(root: Path, output: Path) -> tuple[str, str]:
    """Build the bounded Federal Register release as `make contract-dev` does; return the two digests it prints."""

    environment = {**os.environ, "PYTHONPATH": str(root / "src")}
    for tool in (
        "generate_atlas_index",
        "generate_atlas_v3_registry_coverage",
        "generate_atlas_v3_registry_descriptors",
    ):
        generated = subprocess.run(
            [sys.executable, f"tools/{tool}.py", "--write"], cwd=root, env=environment, capture_output=True, text=True
        )
        assert generated.returncode == 0, generated.stderr
    built = subprocess.run(
        [
            sys.executable,
            "tools/generate_atlas_v3_full.py",
            "--only-release",
            "federal-register-thesaurus-2025",
            "--output",
            str(output / "distribution"),
        ],
        cwd=root,
        env=environment,
        capture_output=True,
        text=True,
    )
    assert built.returncode == 0, built.stderr[-4000:]
    manifest, view = (
        hashlib.sha256((output / member).read_bytes()).hexdigest()
        for member in ("distribution/atlas-manifest.json", "parquet-view/view-manifest.json")
    )
    return manifest, view


@pytest.mark.slow
@pytest.mark.pinned_input(
    not all((ROOT / relative).exists() for relative in FR_RELEASE_INPUTS),
    reason="the Federal Register thesaurus release inputs are absent",
)
def test_a_registry_module_edit_leaves_the_release_pins_and_a_contract_edit_moves_them(tmp_path: Path) -> None:
    """Pin, end to end, the pair `make contract-dev` prints (REF-073), ~4 s a build.

    The fast test above sees only the contract files; this one would also see a
    new path from module bytes into the manifest or view that bypasses them. The
    release is built from a scratch copy of the repository -- the same bytes at
    another path -- once after a registry module edit, where the pair must be the
    recorded pins, and once each after an ontology and a shapes edit, where both
    must move.
    """

    makefile = MAKEFILE.read_text(encoding="utf-8")
    pins = tuple(
        re.search(rf"^{name} \?= ([0-9a-f]{{64}})$", makefile, re.MULTILINE).group(1)
        for name in ("ATLAS_FR_RELEASE_MANIFEST_SHA256", "ATLAS_FR_RELEASE_VIEW_SHA256")
    )
    root = _scratch_registry_repository(tmp_path, release_inputs=True)

    _append_comment(root / EDITED_REGISTRY_MODULE)
    assert _contract_dev_pair(root, tmp_path / "module-edit") == pins

    for contract in ("ontology/atlas.ttl", "shapes/atlas.shacl.ttl"):
        path = root / "bindings" / "atlas" / "3.1" / contract
        original = path.read_bytes()
        _append_comment(path)
        manifest, view = _contract_dev_pair(root, tmp_path / Path(contract).stem)
        assert manifest != pins[0] and view != pins[1], f"{contract} must move both pins"
        path.write_bytes(original)


def test_derived_rule_registry_is_contract_covered_and_matches_the_executable_roster() -> None:
    """Pin that the registry is contract-covered, canonical, matches the executable roster, and holds 6 rules."""

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
    """Pin that a drifted admittedPredicates list raises binding.derived-rule-registry."""

    document = json.loads(
        json.dumps(atlas_validate._derived_rule_registry_document())
    )
    document["rules"][0]["admittedPredicates"] = [str(SKOS.closeMatch)]

    with pytest.raises(atlas_validate.AtlasValidationError) as exc_info:
        atlas_validate._check_derived_rule_registry(document)

    assert exc_info.value.code == "binding.derived-rule-registry"


def test_growing_the_conformance_corpus_leaves_the_contract_where_it_was() -> None:
    """Pin that fixtures/corpus.json is outside the contract and recorded in the acceptance record instead (REF-029).

    Inside contractDigest, adding one conformance case moved every manifest and
    acceptance record on disk, breaking external pins and invalidating a signed
    release for a contract that had not changed a byte.
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
    """Pin that conftest.LONGEST_TEST still names a test in this module.

    The scheduling hook stays silent when the id is absent, so only this check
    notices a rename instead of quietly losing the serial-tail optimization.
    """

    import conftest

    module, _, name = conftest.LONGEST_TEST.partition("::")
    assert module == Path(__file__).relative_to(ROOT).as_posix()
    assert name in globals(), f"{conftest.LONGEST_TEST} no longer exists; repoint LONGEST_TEST"
