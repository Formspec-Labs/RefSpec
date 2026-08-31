"""RefSpec imports from rulespec and real packages, and reads only its own tree.

REF-023/REF-024 give RefSpec exactly one platform dependency — RuleSpec —
and the boundary audit of 2026-08-31 found the tree clean after fixing the
escapes it surfaced: a fidelity SourcePin reading ``/Users/.../spicy-regs``,
builders ``expanduser()``-ing into the corpora staging ground, a
``ROOT.parent / "spicy-regs"`` anchor in the Atlas generator, and a
``Path.home() / "Work/corpora/..."`` in a test. This suite is that audit as
a tripwire — every detector is a shared module-level predicate, exercised
by both the scan tests and the teeth tests, so a detector cannot drift away
from its own negative fixture.

What is deliberately NOT policed: inert provenance strings (a recorded
``~/...`` path nothing opens is data about the past), and evasion channels
an AST scan cannot see — ``joinpath`` with a computed name, f-string paths,
``importlib.import_module``, environment-variable indirection, and non-.py
files. The boundary this suite CLAIMS is exactly what its predicates
detect; treat a clean run as "the known escape mechanisms are absent," not
"no escape is possible."
"""

from __future__ import annotations

import ast
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

#: PyPI distribution name -> importable top-level module, for the few that
#: differ. Everything else imports under its own name.
_DIST_TO_MODULE = {
    "backports-zstd": "backports",
    "typing-extensions": "typing_extensions",
}

#: Sibling products. REF-022/REF-024: no RefSpec edge to any of these, in
#: either direction, under any pretext — not even in tests.
_FORBIDDEN_MODULES = frozenset({"spicy_regs", "spicysearch", "docspec"})

#: Sibling checkouts and the retired staging ground, as path components. A
#: division whose right side contains ANY of these components is an escape
#: (the first version matched only the leading component and missed
#: ``Path.home() / "Work/corpora/..."`` — review finding, 2026-08-31).
#: "rulespec" is deliberately absent: managed-release bundles carry a
#: ``rulespec/`` SUBDIRECTORY by format, so the word is a legitimate in-repo
#: path component (tests/test_managed_release_view.py builds them). The
#: sibling rulespec CHECKOUT is still fenced by the import test and the
#: absolute-literal scan; a relative division into it is a residual gap,
#: named in the module docstring's non-claims.
_SIBLING_PATH_COMPONENTS = frozenset(
    {"spicy-regs", "spicysearch", "DocSpec", "docspec", "corpora"}
)

#: Frozen research trees: committed investigation records whose scripts
#: legitimately recorded absolute paths at capture time. Named exemptions,
#: not an unstated scope — anything under research/ OUTSIDE these is scanned.
_FROZEN_RESEARCH_TREES = (
    "research/evidence/investigations-2026-08-23",
    "research/evidence/investigations-2026-08-24",
    "research/evidence/spicy-regs-nuggets-2026-08-27",
    "research/repo-traces-2026-08-08",
)


def _declared_dependency_modules() -> frozenset[str]:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]
    names = set()
    for spec in project["dependencies"]:
        dist = spec.split(";")[0].split("=")[0].split(">")[0].split("<")[0].strip()
        names.add(_DIST_TO_MODULE.get(dist, dist.replace("-", "_")))
    return frozenset(names)


def _top_level_imports(tree: ast.AST) -> set[str]:
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            found.add(node.module.split(".")[0])
    return found


def _expanduser_sites(tree: ast.AST) -> list[int]:
    return [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "expanduser"
    ]


def _path_home_sites(tree: ast.AST) -> list[int]:
    return [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "home"
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "Path"
    ]


#: The needle, split so the scanner does not flag its own predicate.
_ABSOLUTE_PREFIX = "/Users" + "/"


def _absolute_literal_sites(tree: ast.AST) -> list[int]:
    return [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and node.value.startswith(_ABSOLUTE_PREFIX)
    ]


def _sibling_division_sites(tree: ast.AST) -> list[int]:
    sites = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.BinOp)
            and isinstance(node.op, ast.Div)
            and isinstance(node.right, ast.Constant)
            and isinstance(node.right.value, str)
            and any(part in _SIBLING_PATH_COMPONENTS for part in node.right.value.split("/"))
        ):
            sites.append(node.lineno)
    return sites


def _python_files(*trees: str) -> list[Path]:
    files = []
    for tree in trees:
        for path in sorted((ROOT / tree).rglob("*.py")):
            rel = str(path.relative_to(ROOT))
            if any(rel.startswith(frozen) for frozen in _FROZEN_RESEARCH_TREES):
                continue
            files.append(path)
    return files


def test_src_imports_only_refspec_stdlib_and_declared_dependencies() -> None:
    allowed = _declared_dependency_modules() | set(sys.stdlib_module_names) | {"refspec"}
    violations = {}
    for path in _python_files("src"):
        extra = _top_level_imports(ast.parse(path.read_text())) - allowed
        if extra:
            violations[str(path.relative_to(ROOT))] = sorted(extra)
    assert not violations, (
        "src/ imports something that is neither refspec, the standard library, "
        f"nor a declared dependency: {violations}. A new real dependency belongs "
        "in pyproject.toml; anything else is a boundary escape."
    )


def test_no_tree_imports_a_sibling_product() -> None:
    violations = {}
    for path in _python_files("src", "tools", "tests", "bindings", "deploy", "research"):
        hits = _top_level_imports(ast.parse(path.read_text())) & _FORBIDDEN_MODULES
        if hits:
            violations[str(path.relative_to(ROOT))] = sorted(hits)
    assert not violations, (
        f"a sibling product is imported: {violations}. RefSpec's one platform "
        "dependency is RuleSpec (REF-023/REF-024); everything else talks to "
        "RefSpec through artifacts, never through imports."
    )


def test_no_runtime_path_escape_mechanisms() -> None:
    """No ``expanduser``, no ``Path.home()``, no absolute ``/Users`` literal,
    no path division through a sibling checkout — across src, tools, tests,
    and non-frozen research. Inert ``~/...`` provenance strings stay legal:
    with every opener banned, they cannot be opened, which is exactly the
    line between recording history and depending on it."""

    trees = ("src", "tools", "tests", "research")
    violations: dict[str, list[str]] = {}
    for path in _python_files(*trees):
        tree = ast.parse(path.read_text())
        hits = (
            [f"expanduser:{n}" for n in _expanduser_sites(tree)]
            + [f"Path.home:{n}" for n in _path_home_sites(tree)]
            + [f"/Users literal:{n}" for n in _absolute_literal_sites(tree)]
            + [f"sibling division:{n}" for n in _sibling_division_sites(tree)]
        )
        if hits:
            violations[str(path.relative_to(ROOT))] = hits
    assert not violations, (
        f"runtime path escapes: {violations}. Bring the bytes home to output/ "
        "(digest-verified) and point there instead."
    )


def test_every_detector_has_teeth() -> None:
    """Each negative fixture exercises the PRODUCTION predicate — the first
    version of this file asserted on re-implemented copies, so a detector
    edit left its teeth test green (review finding, 2026-08-31)."""

    assert _top_level_imports(ast.parse("import spicy_regs.ontology\n")) & _FORBIDDEN_MODULES
    assert _top_level_imports(ast.parse("from docspec import catalog\n")) & _FORBIDDEN_MODULES
    assert _expanduser_sites(ast.parse('Path("~/Work/x").expanduser()\n'))
    assert _path_home_sites(ast.parse('Path.home() / "Work/corpora/x"\n'))
    assert _absolute_literal_sites(ast.parse('p = "/Users' + '/nobody/Work/spicy-regs/output"\n'))
    # The exact two escapes the first version missed:
    assert _sibling_division_sites(ast.parse('CORPORA = Path.home() / "Work/corpora/_preserved"\n'))
    assert _sibling_division_sites(ast.parse('SIB = ROOT.parent / "spicy-regs"\n'))
    assert _sibling_division_sites(ast.parse('X = ROOT / "../spicy-regs/output"\n'))
    # And non-escapes must stay clean:
    assert not _sibling_division_sites(ast.parse('X = ROOT / "output/registry-real-data-sources"\n'))
    assert not _expanduser_sites(ast.parse('note = "~/Work/corpora/x is where it was staged"\n'))
