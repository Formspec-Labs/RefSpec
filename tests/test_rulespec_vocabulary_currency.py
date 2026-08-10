"""Every rkaf: term RefSpec depends on must still exist upstream.

RefSpec pins 24 upstream Rulespec artifacts by digest
(profiles/rulespec-dependency.json) but reads none of them: nothing in
RefSpec's src/ opens a compiled schema, a generated Rust type, or the JSON-LD
context file. What RefSpec actually consumes from Rulespec is much narrower
and much less visible -- the rkaf: IRIs it uses as string constants to build
the JSON-LD graph and BehaviorTestCase documents that
``refspec.release_graph.load_pinned_rulespec_validator`` submits to the real,
pinned Rulespec validators (``rkaf-validate-cli``, ``ci_validate.py``,
``rkaf-runtime-cli``). If upstream renamed one of those terms, nothing in the
former closure-pin machinery would have noticed -- it checked compiled
artifact digests and Git revisions, never the vocabulary itself.

This test collects every such term from RefSpec's src/ and asserts it still
exists in a real Rulespec checkout.

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
- ``constraints/core/*.cue`` plus ``constraints/profiles/refspec/open-label.cue``
  is used instead: git-tracked (always present in any checkout, no build
  step), authoritative (CUE is the hand-written source; everything under
  compiled/ is a downstream projection of it), complete (class, property, and
  enum-value terms are all literal ``"rkaf:..."`` tokens in the CUE source),
  and it is exactly RefSpec's own declared ``adoptedConstraintSources`` in
  profiles/rulespec-dependency.json -- the scope RefSpec already claims to
  depend on, not a new one invented for this test.

CUE only covers the L1-L3 JSON-LD graph vocabulary. RefSpec's release_graph
module also builds L4 ``BehaviorTestCase`` documents (evaluationScopes,
subjectAssertion, expectedOutput, ...) -- a separate wire format Rulespec
never compiles from CUE at all. Its normative definition is
``spec/rkaf-behavior.md``; its only implementation is the
``crates/rkaf-runtime`` Rust crate. Both are git-tracked, so both are added
to the source of truth for exactly that surface.

_KNOWN_LOCAL_ONLY_TERMS is a real, checked exception, not a loophole:
src/refspec/atlas/federal_register.py and
src/refspec/atlas/release_snapshot.py use a handful of rkaf:-prefixed
identifiers (SourceRelationRecord, RightsMetadata, ...) that do not exist
anywhere in Rulespec -- not in constraints/, spec/, or crates/rkaf-runtime --
as of this writing (confirmed by exhaustive search of a real checkout). That
is a real, separate finding: Atlas appears to be minting its own rkaf: terms
rather than getting them ratified upstream, which is exactly what AGENTS.md's
"never mint a parallel term for a concept rkaf already defines" rule is
about. Fixing that is out of scope here. The terms are listed explicitly, by
name, so a rename or removal affecting any *other* term is still caught, and
so this known gap stays visible instead of silently passing.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

import pytest

REFSPEC_ROOT = Path(__file__).resolve().parents[1]
REFSPEC_SRC = REFSPEC_ROOT / "src"

# Confirmed absent from constraints/, spec/, and crates/rkaf-runtime in a real
# Rulespec checkout (checked 2026-08-09). See module docstring.
_KNOWN_LOCAL_ONLY_TERMS = frozenset(
    {
        # src/refspec/atlas/federal_register.py -- unresolved Federal Register
        # relation records.
        "sourceConcept",
        "sourceConceptId",
        "sourceOrdinal",
        "sourcePdfPage",
        "sourcePrintedPage",
        "sourceRawTargetLabel",
        "sourceRelationId",
        "sourceRelationRecord",
        "SourceRelationRecord",
        "sourceRelationStatus",
        # src/refspec/atlas/release_snapshot.py -- legacy rights-type
        # recognition.
        "rightsMetadata",
        "RightsMetadata",
        "RightsStatement",
    }
)

_RKAF_COMPACT_IRI = re.compile(r"rkaf:([A-Za-z][A-Za-z0-9_-]*)")
_RKAF_FULL_IRI = re.compile(r"https://rulespec\.org/ns/v1#([A-Za-z][A-Za-z0-9_-]*)")
_RKAF_NAMESPACE_FSTRING = re.compile(r"\{RKAF_NAMESPACE\}([A-Za-z][A-Za-z0-9_]*)")


def _extract_rkaf_terms(text: str) -> set[str]:
    return (
        set(_RKAF_COMPACT_IRI.findall(text))
        | set(_RKAF_FULL_IRI.findall(text))
        | set(_RKAF_NAMESPACE_FSTRING.findall(text))
    )


def refspec_rkaf_terms(*, src_root: Path = REFSPEC_SRC) -> set[str]:
    """Every distinct rkaf: local name used as a string constant under src/."""

    terms: set[str] = set()
    for path in src_root.rglob("*.py"):
        terms |= _extract_rkaf_terms(path.read_text(encoding="utf-8"))
    return terms - _KNOWN_LOCAL_ONLY_TERMS


def rulespec_vocabulary_terms(rulespec_dir: Path) -> set[str]:
    """Every distinct rkaf: local name Rulespec defines, from its own source."""

    sources = [
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
    assert used, "found no rkaf: terms in src/ -- the extraction regex is broken"

    defined = rulespec_vocabulary_terms(rulespec_dir)
    assert defined, f"found no rkaf: terms in {rulespec_dir} -- the checkout looks empty"

    missing = sorted(used - defined)
    assert not missing, (
        f"{len(missing)} rkaf: term(s) RefSpec uses no longer exist in the Rulespec "
        f"checkout at {rulespec_dir}: {missing}. Either Rulespec renamed/removed a "
        "term RefSpec depends on, or this test's _KNOWN_LOCAL_ONLY_TERMS exception "
        "list needs updating."
    )
