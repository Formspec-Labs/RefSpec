"""Read-only queries over a verified vocabulary atlas asset."""

from __future__ import annotations

from dataclasses import dataclass

from rdflib import Dataset, URIRef
from rdflib.namespace import RDF

from .model import ATLAS, RKAF, VocabularyAtlasAsset, VocabularyAtlasError


def _one_iri(graph, subject, predicate, label: str) -> str:
    values = tuple(graph.objects(subject, predicate))
    if len(values) != 1 or not isinstance(values[0], URIRef):
        raise VocabularyAtlasError(f"{label} must have exactly one IRI")
    return str(values[0])


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

    def search_only_mappings(self) -> tuple[SearchOnlyMapping, ...]:
        results: list[SearchOnlyMapping] = []
        for node in sorted(
            set(self._analysis.subjects(RDF.type, RKAF.ConceptMapping)),
            key=str,
        ):
            if (node, RKAF.usageEligibility, RKAF.searchOnly) not in self._analysis:
                continue
            validations = tuple(sorted(str(value) for value in self._analysis.objects(node, ATLAS.qualifiedBy)))
            if len(validations) < 2:
                raise VocabularyAtlasError("searchOnly mapping lacks machine qualification")
            results.append(
                SearchOnlyMapping(
                    mapping_id=str(node),
                    source_member=_one_iri(self._analysis, node, RKAF.assertsSubject, "mapping source"),
                    relation=_one_iri(self._analysis, node, RKAF.assertsPredicate, "mapping relation"),
                    target_member=_one_iri(self._analysis, node, RKAF.assertsObject, "mapping target"),
                    source_release=_one_iri(
                        self._analysis,
                        node,
                        RKAF.sourceConceptRelease,
                        "mapping source release",
                    ),
                    target_release=_one_iri(
                        self._analysis,
                        node,
                        RKAF.targetConceptRelease,
                        "mapping target release",
                    ),
                    validation_ids=validations,
                )
            )
        return tuple(results)

    def label_clusters(self) -> tuple[LabelCluster, ...]:
        results: list[LabelCluster] = []
        for node in sorted(set(self._analysis.subjects(RDF.type, ATLAS.LabelCluster)), key=str):
            labels = tuple(self._analysis.objects(node, ATLAS.normalizedLabel))
            if len(labels) != 1:
                raise VocabularyAtlasError("label cluster has invalid label cardinality")
            results.append(
                LabelCluster(
                    cluster_id=str(node),
                    normalized_label=str(labels[0]),
                    members=tuple(sorted(str(value) for value in self._analysis.objects(node, ATLAS.member))),
                    releases=tuple(sorted(str(value) for value in self._analysis.objects(node, ATLAS.memberRelease))),
                )
            )
        return tuple(results)

    def feedback_ids(self) -> tuple[str, ...]:
        return tuple(sorted(str(node) for node in set(self._analysis.subjects(RDF.type, ATLAS.MappingFeedback))))


__all__ = [
    "LabelCluster",
    "SearchOnlyMapping",
    "VocabularyAtlasQueries",
]
