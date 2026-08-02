"""Read-only queries over a verified vocabulary atlas asset.

These readers are a projection, never a second opinion.  Every rule about what
counts as a ``searchOnly`` mapping or a label cluster lives in
:mod:`refspec.atlas.model`, which already applied it while opening the
distribution, so the readers here call the same accessors instead of
re-deriving them.  An analysis graph that ``model`` rejects therefore cannot be
read here as if it were well formed.
"""

from __future__ import annotations

from dataclasses import dataclass

from rdflib import Dataset, URIRef
from rdflib.namespace import RDF, SKOS

from .model import (
    ATLAS,
    RKAF,
    VocabularyAtlasAsset,
    VocabularyAtlasError,
    _label_cluster_nodes,
    _one_literal,
    _one_resource,
    _require_iri,
    _search_only_mapping_nodes,
    _search_only_mapping_validations,
)


@dataclass(frozen=True, slots=True)
class SearchOnlyMapping:
    mapping_id: str
    source_member: str
    relation: str
    target_member: str
    source_release: str
    target_release: str
    validation_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class LabelCluster:
    cluster_id: str
    normalized_label: str
    members: tuple[str, ...]
    releases: tuple[str, ...]


class VocabularyAtlasQueries:
    """Small consumer-equivalent queries over immutable asset bytes."""

    def __init__(self, asset: VocabularyAtlasAsset) -> None:
        asset._require_verified()
        dataset = Dataset(default_union=False)
        dataset.parse(data=asset.payload.decode("utf-8"), format="nquads")
        graph_rows = {row["role"]: row for row in asset.manifest["graphs"]}
        self._analysis = dataset.graph(URIRef(graph_rows["analysis"]["id"]))
        self._release_facts = dataset.graph(URIRef(graph_rows["releaseFacts"]["id"]))

    def broader(self, concept_iri: str) -> tuple[str, ...]:
        """Return one concept's immediate broader concepts.

        ``model`` already refused every dangling, cross-release, self-joined,
        and cyclic edge while opening the distribution, so this is a plain
        read of the release facts the source vocabulary stated.  A concept may
        have several parents: ELSST places 162 of them under more than one.
        """

        concept = URIRef(_require_iri(concept_iri, "concept id"))
        return tuple(sorted(str(value) for value in self._release_facts.objects(concept, SKOS.broader)))

    def narrower(self, concept_iri: str) -> tuple[str, ...]:
        """Return one concept's immediate narrower concepts.

        Only the broader direction is stored, so this inverts that one
        statement rather than reading a second, separately fallible one.
        """

        concept = URIRef(_require_iri(concept_iri, "concept id"))
        return tuple(sorted(str(value) for value in self._release_facts.subjects(SKOS.broader, concept)))

    def hierarchy_edges(self) -> tuple[tuple[str, str], ...]:
        """Return every stored edge as a ``(narrower, broader)`` pair."""

        return tuple(
            sorted(
                (str(child), str(parent))
                for child, parent in self._release_facts.subject_objects(SKOS.broader)
            )
        )

    def transitive_broader(self, concept_iri: str, *, max_depth: int) -> tuple[str, ...]:
        """Return the broader closure reachable within ``max_depth`` steps.

        The bound is required rather than defaulted.  Refused cycles already
        make the walk finite, so the bound is the caller's own statement of
        how far a query may generalize — ELSST's deepest branch is 8 — not a
        safety net this reader picked for them.
        """

        if max_depth < 1:
            raise VocabularyAtlasError("transitive hierarchy needs a positive depth bound")
        concept = URIRef(_require_iri(concept_iri, "concept id"))
        reached: set[URIRef] = set()
        frontier = {concept}
        for _ in range(max_depth):
            following = {
                value
                for node in frontier
                for value in self._release_facts.objects(node, SKOS.broader)
                if isinstance(value, URIRef)
            } - reached
            if not following:
                break
            reached |= following
            frontier = following
        reached.discard(concept)
        return tuple(sorted(str(value) for value in reached))

    def search_only_mappings(self) -> tuple[SearchOnlyMapping, ...]:
        analysis = self._analysis
        return tuple(
            SearchOnlyMapping(
                mapping_id=str(node),
                source_member=str(_one_resource(analysis, node, RKAF.assertsSubject, "mapping source")),
                relation=str(_one_resource(analysis, node, RKAF.assertsPredicate, "mapping relation")),
                target_member=str(_one_resource(analysis, node, RKAF.assertsObject, "mapping target")),
                source_release=str(
                    _one_resource(analysis, node, RKAF.sourceConceptRelease, "mapping source release")
                ),
                target_release=str(
                    _one_resource(analysis, node, RKAF.targetConceptRelease, "mapping target release")
                ),
                validation_ids=tuple(str(value) for value in _search_only_mapping_validations(analysis, node)),
            )
            for node in _search_only_mapping_nodes(analysis)
        )

    def label_clusters(self) -> tuple[LabelCluster, ...]:
        analysis = self._analysis
        return tuple(
            LabelCluster(
                cluster_id=str(node),
                normalized_label=str(
                    _one_literal(analysis, node, ATLAS.normalizedLabel, "label cluster normalized label")
                ),
                members=tuple(sorted(str(value) for value in analysis.objects(node, ATLAS.member))),
                releases=tuple(sorted(str(value) for value in analysis.objects(node, ATLAS.memberRelease))),
            )
            for node in _label_cluster_nodes(analysis)
        )

    def feedback_ids(self) -> tuple[str, ...]:
        return tuple(sorted(str(node) for node in set(self._analysis.subjects(RDF.type, ATLAS.MappingFeedback))))


__all__ = [
    "LabelCluster",
    "SearchOnlyMapping",
    "VocabularyAtlasQueries",
]
