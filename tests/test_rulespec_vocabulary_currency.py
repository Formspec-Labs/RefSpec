"""Every rkaf: term RefSpec depends on must still exist upstream.

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
still exists in a real Rulespec checkout.

Scanning only src/ was the bug that let the leak run the other way. A shipped
JSON binding fixture asserted ``rulespec.org/ns/v1#assignedConcept``, a test
invented ``#assignmentSecondary`` as a fifth member of a closed four-value
upstream enum, and a research script queried a docket class that only the
document pipeline in another repository defines -- none of them
visible to a src/-only scan. So every text file under the directories that can
carry a vocabulary claim is read: src/, tests/, research/, bindings/, and
tools/.

Source of truth, and why: three candidates were inspected.

- ``context/rkaf-context.jsonld`` was rejected. It only lists terms that need
  JSON-LD ``@type``/``@container`` coercion; a plain string-valued property or
  an enum member (``rkaf:notEligible``, ``rkaf:affirmed``, ...) needs no such
  entry and simply does not appear there. Absence from this file does not
  mean the term does not exist -- it is unusable as a completeness check.
- ``compiled/json-schema/`` was rejected. It is listed in Rulespec's
  ``.gitignore`` and is produced by ``tools/compile_all.sh``, which needs a
  CUE/Rust toolchain. A plain ``git clone`` of Rulespec -- the only checkout
  shape this test can assume when it is not skipping -- does not contain it,
  which would make "checkout present" and "compiled/ present" different
  conditions this test cannot tell apart.
- ``constraints/analysis/*.cue`` and ``constraints/core/*.cue`` plus
  ``constraints/profiles/refspec/open-label.cue``
  is used instead: git-tracked (always present in any checkout, no build
  step), authoritative (CUE is the hand-written source; everything under
  compiled/ is a downstream projection of it), complete (class, property, and
  enum-value terms are all literal ``"rkaf:..."`` tokens in the CUE source),
  and it is exactly RefSpec's own declared ``adoptedConstraintSources`` in
  profiles/rulespec-dependency.json -- the scope RefSpec already claims to
  depend on, not a new one invented for this test. ``constraints/analysis``
  joined that list when the Atlas 3.0 binding put rulespec's
  machine-adjudication records (``rkaf:ResolverProofRecord`` and the comparison
  context citing it) on the wire; the two lists move together on purpose, so a
  term adopted from a package RefSpec has not declared fails here rather than
  shipping unnoticed.

CUE only covers the L1-L3 JSON-LD graph vocabulary. RefSpec's release_graph
module also builds L4 ``BehaviorTestCase`` documents (evaluationScopes,
subjectAssertion, expectedOutput, ...) -- a separate wire format Rulespec
never compiles from CUE at all. Its normative definition is
``spec/rkaf-behavior.md``; its only implementation is the
``crates/rkaf-runtime`` Rust crate. Both are git-tracked, so both are added
to the source of truth for exactly that surface.

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

import os
import re
from pathlib import Path

import pytest

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


def rulespec_vocabulary_terms(rulespec_dir: Path) -> set[str]:
    """Every distinct rkaf: local name Rulespec defines, from its own source."""

    sources = [
        *sorted((rulespec_dir / "constraints" / "analysis").glob("*.cue")),
        *sorted((rulespec_dir / "constraints" / "core").glob("*.cue")),
        rulespec_dir / "constraints" / "profiles" / "refspec" / "open-label.cue",
        rulespec_dir / "spec" / "rkaf-behavior.md",
        *sorted((rulespec_dir / "crates" / "rkaf-runtime" / "src").glob("*.rs")),
    ]
    terms: set[str] = set()
    for path in sources:
        if path.is_file():
            terms |= _extract_rkaf_terms(path.read_text(encoding="utf-8"))
    return terms


def discover_rulespec_checkout() -> Path | None:
    """Locate a real Rulespec checkout, or None if none is available.

    ``REFSPEC_RULESPEC_CHECKOUT`` overrides the default sibling-checkout
    location (``~/Work/rulespec``, matching where the pinned dependency is
    developed). A directory only counts if it actually looks like a
    Rulespec checkout -- present but empty, or present but the wrong repo,
    must skip exactly like absent.
    """

    override = os.environ.get("REFSPEC_RULESPEC_CHECKOUT")
    candidate = Path(override).expanduser() if override else Path.home() / "Work" / "rulespec"
    if not (candidate / "constraints" / "core").is_dir():
        return None
    if not (candidate / "spec" / "rkaf-behavior.md").is_file():
        return None
    return candidate


def test_every_rkaf_term_refspec_uses_exists_upstream() -> None:
    rulespec_dir = discover_rulespec_checkout()
    if rulespec_dir is None:
        pytest.skip(
            "no Rulespec checkout found (set REFSPEC_RULESPEC_CHECKOUT or "
            "clone Rulespec to ~/Work/rulespec) -- skipping the rkaf: "
            "vocabulary currency check"
        )

    used = refspec_rkaf_terms()
    assert used, "found no rkaf: terms in the repository -- the extraction regex is broken"

    defined = rulespec_vocabulary_terms(rulespec_dir)
    assert defined, f"found no rkaf: terms in {rulespec_dir} -- the checkout looks empty"

    missing = sorted(used - defined)
    assert not missing, (
        f"{len(missing)} rkaf: term(s) this repository claims do not exist in the "
        f"Rulespec checkout at {rulespec_dir}: {missing}. Either Rulespec "
        "renamed or removed a term RefSpec depends on, or RefSpec has minted a "
        "term inside Rulespec's namespace. Terms RefSpec owns belong in "
        "https://refspec.org/ns/atlas/v3# -- there is no exception list."
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
