"""Every rkaf: term RefSpec depends on must still exist in the packaged contract.

RefSpec used to pin 24 upstream Rulespec artifacts by digest and read none of
them: nothing in RefSpec's src/ opens a compiled schema, a generated Rust
type, or the JSON-LD context file. That pin is gone. What RefSpec actually
consumes from Rulespec is much narrower and much less visible -- the rkaf:
IRIs it uses as string constants to build
the JSON-LD graph and BehaviorTestCase documents that
``refspec.release_graph.load_pinned_rulespec_validator`` submits to the real,
pinned Rulespec validators (``rkaf-validate-cli``, ``ci_validate.py``,
``rkaf-runtime-cli``). If upstream renamed one of those terms, nothing in the
former closure-pin machinery would have noticed -- it checked compiled
artifact digests and Git revisions, never the vocabulary itself.

This test collects every such term from the whole repository and asserts it
still exists in the packaged ``rulespec-conformance`` contract.

Scanning only src/ was the bug that let the leak run the other way. A shipped
JSON binding fixture asserted ``rulespec.org/ns/v1#assignedConcept``, a test
invented ``#assignmentSecondary`` as a fifth member of a closed four-value
upstream enum, and a research script queried a docket class that only the
document pipeline in another repository defines -- none of them
visible to a src/-only scan. So every text file under the directories that can
carry a vocabulary claim is read: src/, tests/, research/, bindings/, and
tools/.

Source of truth, and why it changed: ``rulespec_conformance.contract.terms``
(the vendored wheel; see ``vendor/README.md``) is a generated, importable
registry of every rkaf: local name Rulespec declares -- built upstream by
``tools/build_contract_exports.py`` from ``constraints/**/*.cue``,
``context/rkaf-context.jsonld``, ``spec/rkaf-vocabulary.md``,
``spec/rkaf-behavior.md``, and ``crates/rkaf-runtime/src/*.rs``. That is a
strict superset of what this test used to scan from a live checkout
(``constraints/core``, ``constraints/analysis``, one profile file, the
behavior spec, and the runtime crate), it needs no checkout at all -- CI
carries it as an ordinary dependency -- and unlike a checkout it cannot be
missing, stale, or ahead of what RefSpec actually depends on: the wheel
version pinned in ``pyproject.toml`` *is* the dependency.

That mostly obsoletes this file. A Python reference to a real name inside
``rulespec_conformance.contract`` -- ``terms.hasContentDigest``,
``enums.USAGE_ELIGIBILITY`` -- now raises ``ImportError`` at import time if
the name does not exist; the check is the import, with no separate test
required. What ``ImportError`` semantics cannot reach is a *string literal*
spelling a term: a JSON-LD fixture's ``"@type": "rkaf:Artifact"``, a
Markdown trace quoting a compact IRI in prose, or a Turtle template minting
one that turns out not to be real. None of those ever touch the packaged
registry as a Python name, so nothing raises if one is wrong. This test is
what still catches them: the same whole-repository text scan as before, now
checked against the packaged registry instead of a checkout scan of the CUE.

There is no exception list. There used to be one, naming the rkaf:-prefixed
identifiers Atlas had minted for itself (SourceRelationRecord, RightsMetadata,
...). Those terms now live in RefSpec's own https://refspec.org/ns/atlas/v3#
namespace, where RefSpec is entitled to define them, so nothing is left to
excuse. An empty exception list is the point: AGENTS.md says never mint a
parallel term for a concept rkaf already defines, and a term in rkaf's
namespace that rkaf does not define is the same violation seen from the other
side.

``urn:rkaf:`` is not a compact IRI. RefSpec identifiers such as
``urn:rkaf:us:cfr:7:273.9`` and ``urn:rkaf:fixture:release:digest-vector``
contain the sequence ``rkaf:`` mid-URN; reading ``us`` or ``fixture`` out of
them as vocabulary terms produced four false leaks. The compact-IRI pattern
therefore refuses a ``urn:`` prefix.
"""

from __future__ import annotations

import re
from pathlib import Path

from rulespec_conformance.contract import terms as rulespec_terms

REFSPEC_ROOT = Path(__file__).resolve().parents[1]

# Every directory that can carry a vocabulary claim: shipped code, the tests
# that pin its wire formats, the binding fixtures consumers receive, the
# generators that write them, and the research record.
REFSPEC_SCANNED_DIRECTORIES = ("src", "tests", "research", "bindings", "tools")

# Binary payloads a text scan cannot read. Everything else is read as UTF-8;
# anything that fails to decode is skipped for the same reason.
_BINARY_SUFFIXES = frozenset(
    {".gz", ".jpg", ".jpeg", ".lbug", ".parquet", ".pdf", ".png", ".zip"}
)

# ``(?<!urn:)`` keeps urn:rkaf:us:cfr:... and urn:rkaf:fixture:... out: those
# are RefSpec identifiers that merely contain "rkaf:", not compact IRIs.
_RKAF_COMPACT_IRI = re.compile(r"(?<!urn:)\brkaf:([A-Za-z][A-Za-z0-9_-]*)")
_RKAF_FULL_IRI = re.compile(r"https://rulespec\.org/ns/v1#([A-Za-z][A-Za-z0-9_-]*)")
_RKAF_NAMESPACE_FSTRING = re.compile(r"\{RKAF_NAMESPACE\}([A-Za-z][A-Za-z0-9_]*)")


def _extract_rkaf_terms(text: str) -> set[str]:
    return (
        set(_RKAF_COMPACT_IRI.findall(text))
        | set(_RKAF_FULL_IRI.findall(text))
        | set(_RKAF_NAMESPACE_FSTRING.findall(text))
    )


def refspec_rkaf_terms(*, root: Path = REFSPEC_ROOT) -> set[str]:
    """Every distinct rkaf: local name this repository claims, anywhere."""

    terms: set[str] = set()
    for directory in REFSPEC_SCANNED_DIRECTORIES:
        for path in (root / directory).rglob("*"):
            if not path.is_file() or path.suffix.lower() in _BINARY_SUFFIXES:
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            terms |= _extract_rkaf_terms(text)
    return terms


def rulespec_defined_local_names() -> frozenset[str]:
    """Every rkaf: local name the packaged contract registry declares.

    ``rulespec_terms.TERMS`` is a frozenset of ``Term`` (a ``str`` subclass
    holding the exact compact IRI, e.g. ``"rkaf:hasContentDigest"``);
    ``.local`` strips the ``rkaf:`` prefix so callers compare like-for-like
    with :func:`refspec_rkaf_terms`, which never captures the prefix either.
    """

    return frozenset(term.local for term in rulespec_terms.TERMS)


def test_every_rkaf_term_refspec_uses_exists_in_the_packaged_registry() -> None:
    used = refspec_rkaf_terms()
    assert used, "found no rkaf: terms in the repository -- the extraction regex is broken"

    defined = rulespec_defined_local_names()
    assert defined, (
        "rulespec_conformance.contract.terms.TERMS is empty -- the packaged "
        "registry looks broken"
    )

    # SHACL shape identifiers (``rkaf:SomeShape``) are not data-vocabulary
    # terms: rulespec's own export tool (rulespec's tools/build_contract_exports.py)
    # deliberately excludes "*Shape node names" from the registry as "shape
    # identifiers, not data vocabulary" -- confirmed structurally by
    # test_no_shape_identifier_is_a_real_vocabulary_term below, which fails
    # the day that stops being true. bindings/atlas/3.1/tools/validate.py
    # cites two of rulespec's SHACL shapes by name in prose, comparing
    # Atlas's own validation rules to them; that is documentation, not a
    # claim that a JSON-LD graph or BehaviorTestCase this repository builds
    # carries the term.
    claimed = {name for name in used if not name.endswith("Shape")}

    missing = sorted(claimed - defined)
    assert not missing, (
        f"{len(missing)} rkaf: term(s) this repository claims do not exist in "
        "the packaged rulespec-conformance contract (rulespec_conformance."
        f"contract.terms.TERMS): {missing}. Either Rulespec renamed or removed "
        "a term RefSpec depends on -- bump the vendored wheel (see "
        "vendor/README.md) and re-check -- or RefSpec has minted a term inside "
        "Rulespec's namespace. Terms RefSpec owns belong in "
        "https://refspec.org/ns/atlas/v3# -- there is no exception list."
    )


def test_no_shape_identifier_is_a_real_vocabulary_term() -> None:
    """Guards the ``*Shape`` exclusion above against ever going stale.

    If this ever fails, rulespec started registering a SHACL shape name as a
    real rkaf: term, and the exclusion in the currency test above -- which
    exists only because that was never true -- must be revisited rather than
    silently continuing to skip it.
    """

    shape_suffixed = sorted(name for name in rulespec_defined_local_names() if name.endswith("Shape"))
    assert not shape_suffixed, (
        f"rulespec_conformance.contract.terms.TERMS now defines shape-suffixed "
        f"name(s) {shape_suffixed!r} as real terms -- the '*Shape is never a "
        "real term' exclusion above no longer holds; narrow or remove it."
    )


def test_a_urn_that_contains_rkaf_is_not_a_vocabulary_claim() -> None:
    """The URN guard must exclude urn:rkaf: without blinding the scan.

    Dropping the guard resurrects four phantom terms (us, facet, fixture,
    test) and buries the real ones in noise; widening it to any prefix blinds
    the scan to real compact IRIs. Both directions are pinned here.
    """

    assert _extract_rkaf_terms("urn:rkaf:us:cfr:7:273.9") == set()
    assert _extract_rkaf_terms('"urn:rkaf:fixture:release:digest-vector"') == set()
    assert _extract_rkaf_terms('"rkaf:completeMembership"') == {"completeMembership"}
    assert _extract_rkaf_terms('{"@id": "urn:x"}, "rkaf:appliesTo"') == {"appliesTo"}
    assert _extract_rkaf_terms(
        '"https://rulespec.org/ns/v1#assignmentPrimary"'
    ) == {"assignmentPrimary"}


def test_the_scan_reaches_beyond_python_files_under_src(tmp_path: Path) -> None:
    """A src/-only, *.py-only scan is what let the binding fixtures leak.

    The two worst offenders were a shipped JSON fixture and a Markdown trace,
    neither of which the old scan could see. Every scanned directory is
    exercised here in a file type that is not Python.
    """

    for directory in REFSPEC_SCANNED_DIRECTORIES:
        assert (REFSPEC_ROOT / directory).is_dir(), directory

    # The planted IRIs are assembled at run time. Written out literally they
    # would be leaks in this very file, and this test would fail the one above.
    prefix = "rkaf" + ":"
    planted = {
        "src": ("refspec/graph.jsonld", '{{"@type": "{term}"}}'),
        "tests": ("fixtures/case.json", '{{"@type": "{term}"}}'),
        "research": ("note.md", "asserts `{term}`"),
        "bindings": ("json/1.0/fixtures/x.json", '"{term}"'),
        "tools": ("templates/seed.ttl", "a {term} ."),
    }
    expected: set[str] = set()
    for directory, (relative, template) in planted.items():
        local_name = f"plantedIn{directory.capitalize()}"
        path = tmp_path / directory / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(template.format(term=prefix + local_name), encoding="utf-8")
        expected.add(local_name)
    (tmp_path / "src" / "refspec" / "atlas.png").write_bytes(
        b"\x89PNG\r" + (prefix + "plantedInBinary").encode()
    )

    assert refspec_rkaf_terms(root=tmp_path) == expected
