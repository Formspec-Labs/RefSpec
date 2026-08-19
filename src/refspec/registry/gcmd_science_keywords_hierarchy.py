"""Derived skos:broader edges for GCMD Science Keywords from CSV column nesting.

Judgment (REF-041 in docs/decisions.md): the Science Keywords CSV export
encodes the publisher's concept hierarchy positionally. Every row is a
path through Category > Topic > Term > Variable_Level_1..3 >
Detailed_Variable, every ancestor prefix of every row is itself a row with
its own publisher UUID, and NASA's own RDF export of the same scheme
asserts ``skos:broader`` between exactly the UUID pairs this nesting
implies. Reading one row's immediate parent as its depth-1 prefix is
therefore a recoverable restructuring of publisher structure, not an
invented relation.

It is still not an assertion. The pinned CSV carries no relation field;
the predicate choice (``skos:broader``) is RefSpec's, made under REF-035
tier E5: an inferred edge is never an assertion, belongs only in the
derived graph, and stays opt-in. Nothing in this module feeds the asserted
graph. REF-043 registered the rule this module derives for as the Atlas
3.1 derived graph's third admitted rule
(``src/refspec/atlas/derived_graph/gcmd_column_nesting.py`` producer-side,
``_DERIVED_RULE_ADMISSIONS`` binding-side); this module remains the
CSV-level oracle its real-data tests prove that rule against, pair for
pair over the same pinned bytes.

Identity is path-scoped, never label-scoped: 512 (level, label) pairs in
the pinned 24.4 export appear under more than one parent, so any
label-keyed derivation would silently merge distinct publisher concepts.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from refspec.registry.gcmd_science_keywords import (
    GCMDKeywordRow,
    GCMDResourceError,
    ParsedGCMDScienceKeywords,
)
from refspec.storage import canonical_json

SKOS_BROADER = "http://www.w3.org/2004/02/skos/core#broader"
SKOS_NARROWER = "http://www.w3.org/2004/02/skos/core#narrower"

# Rule identity for the binding's derived-graph allowlist. REF-043
# registered this IRI as the derived graph's third admitted rule; the
# derived-graph implementation that carries it lives in
# refspec.atlas.derived_graph.gcmd_column_nesting.
GCMD_COLUMN_NESTING_RULE = "urn:ref:rule:gcmd-science-keywords-csv-column-nesting"

GCMD_HIERARCHY_PACKAGE_VERSION = "gcmd-science-keywords-derived-hierarchy-v1"

_LEVEL_NAMES = (
    "Category",
    "Topic",
    "Term",
    "Variable_Level_1",
    "Variable_Level_2",
    "Variable_Level_3",
    "Detailed_Variable",
)

# Frozen against the pinned 24.4 export (3,774 rows,
# sha256:f31d8137e860e4231ff312c89e4ffe59d12f636786a47dd2c41e28273a3f02e2).
GCMD_24_4_DERIVED_ROOT_COUNT = 2
GCMD_24_4_DERIVED_EDGE_COUNT = 3_772
GCMD_24_4_DERIVED_HOMONYM_LABEL_COUNT = 512
GCMD_24_4_DERIVED_EDGE_SET_SHA256 = "sha256:9685d20fd9e10d2e12d916b4e5f543ae17b332b6d13a3a311e14db9f79fcc964"


class GCMDHierarchyError(GCMDResourceError):
    """The pinned export does not satisfy the column-nesting rule's premises."""


@dataclass(frozen=True, slots=True)
class GCMDHierarchyEdge:
    """One derived child->broader edge with the exact CSV rows it cites."""

    edge_id: str
    rule: str
    predicate: str
    child_uuid: str
    parent_uuid: str
    child_label: str
    parent_label: str
    child_level: str
    parent_level: str
    child_source_path: str
    parent_source_path: str
    source_sha256: str

    def record(self) -> dict[str, str]:
        return {
            "childLevel": self.child_level,
            "childSourcePath": self.child_source_path,
            "childUuid": self.child_uuid,
            "edgeId": self.edge_id,
            "parentLevel": self.parent_level,
            "parentSourcePath": self.parent_source_path,
            "parentUuid": self.parent_uuid,
            "predicate": self.predicate,
            "rule": self.rule,
            "sourceSha256": self.source_sha256,
        }


@dataclass(frozen=True, slots=True)
class GCMDScienceKeywordsHierarchy:
    """The exact derived edge set one pinned export's column nesting implies."""

    keyword_version: str
    revision: str
    source_sha256: str
    row_count: int
    root_count: int
    homonym_label_count: int
    edges: tuple[GCMDHierarchyEdge, ...]
    edge_set_digest: str
    rule: str

    def by_child_uuid(self) -> dict[str, GCMDHierarchyEdge]:
        return {edge.child_uuid: edge for edge in self.edges}


def _row_depth(row: GCMDKeywordRow) -> int:
    # The pinned reader already refuses a populated level after a blank
    # ancestor, so depth is the count of leading non-blank levels here.
    levels = (
        row.category,
        row.topic,
        row.term,
        row.variable_level_1,
        row.variable_level_2,
        row.variable_level_3,
        row.detailed_variable,
    )
    depth = 0
    for level in levels:
        if level is None or level == "":
            break
        depth += 1
    return depth


def _row_prefix(row: GCMDKeywordRow, depth: int) -> tuple[str, ...]:
    levels = (
        row.category,
        row.topic,
        row.term,
        row.variable_level_1,
        row.variable_level_2,
        row.variable_level_3,
        row.detailed_variable,
    )
    return tuple(level or "" for level in levels[:depth])


def _edge_identity(edge_content: Mapping[str, str]) -> str:
    digest = "sha256:" + hashlib.sha256(
        canonical_json(dict(edge_content)).encode("utf-8")
    ).hexdigest()
    return "urn:ref:gcmd-derived-edge:" + digest.removeprefix("sha256:")


def derive_gcmd_science_keywords_hierarchy(
    parsed: ParsedGCMDScienceKeywords,
    *,
    asserted_relations: Iterable[tuple[str, str, str]] = (),
) -> GCMDScienceKeywordsHierarchy:
    """Derive the immediate-parent edge set implied by column nesting.

    ``asserted_relations`` carries already-asserted (subject UUID, predicate
    IRI, object UUID) triples; a derived edge that duplicates one -- or its
    ``skos:narrower`` inverse -- is refused, never silently dropped.

    Fails closed on any premise violation: an ancestor prefix without its
    own row, a repeated path, a self-edge, or an asserted duplicate.
    """

    by_path: dict[tuple[str, ...], GCMDKeywordRow] = {}
    for row in parsed.rows:
        prefix = _row_prefix(row, _row_depth(row))
        if prefix in by_path:
            raise GCMDHierarchyError(
                f"Science Keywords path repeats: {prefix} at {row.source_path}"
                f" and {by_path[prefix].source_path}"
            )
        by_path[prefix] = row

    asserted = set(asserted_relations)
    edges: list[GCMDHierarchyEdge] = []
    root_count = 0
    for row in parsed.rows:
        depth = _row_depth(row)
        if depth < 2:
            root_count += 1
            continue
        parent = by_path.get(_row_prefix(row, depth - 1))
        if parent is None:
            raise GCMDHierarchyError(
                f"row {row.source_path} has no materialized parent row for its"
                f" {_LEVEL_NAMES[depth - 2]} prefix"
            )
        child_uuid = row.identifiers[0].value
        parent_uuid = parent.identifiers[0].value
        if child_uuid == parent_uuid:
            raise GCMDHierarchyError(f"row {row.source_path} derives a self-edge")
        if (child_uuid, SKOS_BROADER, parent_uuid) in asserted or (
            parent_uuid,
            SKOS_NARROWER,
            child_uuid,
        ) in asserted:
            raise GCMDHierarchyError(
                f"derived edge {child_uuid} -> {parent_uuid} duplicates an"
                " asserted relation (or its narrower inverse)"
            )
        content = {
            "childLevel": _LEVEL_NAMES[depth - 1],
            "childSourcePath": row.source_path,
            "childUuid": child_uuid,
            "packageVersion": GCMD_HIERARCHY_PACKAGE_VERSION,
            "parentLevel": _LEVEL_NAMES[depth - 2],
            "parentSourcePath": parent.source_path,
            "parentUuid": parent_uuid,
            "predicate": SKOS_BROADER,
            "rule": GCMD_COLUMN_NESTING_RULE,
            "sourceSha256": parsed.source_sha256,
        }
        edge_id = _edge_identity(content)
        edges.append(
            GCMDHierarchyEdge(
                edge_id=edge_id,
                rule=GCMD_COLUMN_NESTING_RULE,
                predicate=SKOS_BROADER,
                child_uuid=child_uuid,
                parent_uuid=parent_uuid,
                child_label=row.preferred_label,
                parent_label=parent.preferred_label,
                child_level=_LEVEL_NAMES[depth - 1],
                parent_level=_LEVEL_NAMES[depth - 2],
                child_source_path=row.source_path,
                parent_source_path=parent.source_path,
                source_sha256=parsed.source_sha256,
            )
        )

    parents_by_label: dict[tuple[int, str], set[tuple[str, ...]]] = {}
    for prefix, row in by_path.items():
        depth = len([level for level in prefix if level != ""])
        if depth < 2:
            continue
        key = (depth - 1, prefix[depth - 1])
        parents_by_label.setdefault(key, set()).add(_row_prefix(row, depth - 1))
    homonym_label_count = sum(
        1 for parents in parents_by_label.values() if len(parents) > 1
    )

    # Pinned file order is the canonical edge order, so the digest below is
    # reproducible without a re-sort.
    edge_set_digest = "sha256:" + hashlib.sha256(
        canonical_json(
            {
                "edges": [edge.record() for edge in edges],
                "keywordVersion": parsed.keyword_version,
                "revision": parsed.revision,
                "rowCount": len(parsed.rows),
                "rule": GCMD_COLUMN_NESTING_RULE,
                "sourceSha256": parsed.source_sha256,
            }
        ).encode("utf-8")
    ).hexdigest()
    return GCMDScienceKeywordsHierarchy(
        keyword_version=parsed.keyword_version,
        revision=parsed.revision,
        source_sha256=parsed.source_sha256,
        row_count=len(parsed.rows),
        root_count=root_count,
        homonym_label_count=homonym_label_count,
        edges=tuple(edges),
        edge_set_digest=edge_set_digest,
        rule=GCMD_COLUMN_NESTING_RULE,
    )


__all__ = [
    "GCMD_24_4_DERIVED_EDGE_COUNT",
    "GCMD_24_4_DERIVED_EDGE_SET_SHA256",
    "GCMD_24_4_DERIVED_HOMONYM_LABEL_COUNT",
    "GCMD_24_4_DERIVED_ROOT_COUNT",
    "GCMD_COLUMN_NESTING_RULE",
    "GCMD_HIERARCHY_PACKAGE_VERSION",
    "SKOS_BROADER",
    "SKOS_NARROWER",
    "GCMDHierarchyEdge",
    "GCMDHierarchyError",
    "GCMDScienceKeywordsHierarchy",
    "derive_gcmd_science_keywords_hierarchy",
]
