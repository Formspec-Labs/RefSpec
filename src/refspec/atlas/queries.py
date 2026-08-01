"""Fail-closed queries over a sealed vocabulary-atlas asset."""

from __future__ import annotations

from dataclasses import dataclass

from rdflib import Graph, URIRef
from rdflib import Literal as RdfLiteral
from rdflib.namespace import RDF, RDFS

from .crosswalk import ATLAS, RKAF
from .model import (
    CROSSWALK_SELECTION_POLICY,
    VocabularyAtlasAsset,
    VocabularyAtlasError,
)


def _one_resource(graph: Graph, subject: URIRef, predicate: URIRef) -> URIRef:
    values = tuple(graph.objects(subject, predicate))
    if len(values) != 1 or not isinstance(values[0], URIRef):
        raise VocabularyAtlasError(
            f"{subject} must have exactly one resource-valued {predicate}"
        )
    return values[0]


@dataclass(frozen=True, slots=True)
class LabelCluster:
    """Concepts from different schemes with the same normalized label."""

    cluster_id: str
    normalized_label: str
    concept_ids: tuple[str, ...]
    release_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class MappingCandidateView:
    """One generated proposal, whether or not it passed validation."""

    candidate_id: str
    source_concept_id: str
    source_release_id: str
    relation: str
    target_concept_id: str
    target_release_id: str
    qualified_for_search: bool


@dataclass(frozen=True, slots=True)
class SearchOnlyMapping:
    """One machine-generated mapping cleared only for search expansion."""

    mapping_id: str
    candidate_id: str
    baseline_receipt_id: str
    source_concept_id: str
    source_release_id: str
    relation: str
    target_concept_id: str
    target_release_id: str


@dataclass(frozen=True, slots=True)
class FeedbackView:
    """Optional feedback recorded after candidate generation."""

    feedback_id: str
    candidate_id: str
    actor_id: str
    disposition: str
    comment: str


class VocabularyAtlasQueries:
    """Read the two named graphs without enabling inference or equivalence."""

    def __init__(self, asset: VocabularyAtlasAsset) -> None:
        dataset = asset.dataset
        self._asserted = dataset.graph(URIRef(asset.asserted_graph_iri))
        self._analysis = dataset.graph(URIRef(asset.analysis_graph_iri))

    def label_clusters(self) -> tuple[LabelCluster, ...]:
        results: list[LabelCluster] = []
        for node in sorted(
            self._analysis.subjects(RDF.type, ATLAS.LabelCluster), key=str
        ):
            labels = tuple(self._analysis.objects(node, ATLAS.normalizedLabel))
            if len(labels) != 1:
                raise VocabularyAtlasError(
                    f"label cluster {node} must have one normalized label"
                )
            results.append(
                LabelCluster(
                    cluster_id=str(node),
                    normalized_label=str(labels[0]),
                    concept_ids=tuple(
                        sorted(
                            str(value)
                            for value in self._analysis.objects(node, ATLAS.member)
                        )
                    ),
                    release_ids=tuple(
                        sorted(
                            {
                                str(value)
                                for value in self._analysis.objects(
                                    node, ATLAS.memberRelease
                                )
                            }
                        )
                    ),
                )
            )
        return tuple(results)

    def mapping_candidates(self) -> tuple[MappingCandidateView, ...]:
        qualified = {
            str(value)
            for mapping in self._asserted.subjects(RDF.type, RKAF.ConceptMapping)
            for value in self._asserted.objects(mapping, ATLAS.qualifiedFrom)
        }
        results: list[MappingCandidateView] = []
        for node in sorted(
            self._analysis.subjects(RDF.type, ATLAS.ConceptMappingCandidate),
            key=str,
        ):
            source = _one_resource(self._analysis, node, ATLAS.sourceConcept)
            source_release = _one_resource(self._analysis, node, ATLAS.sourceRelease)
            relation = _one_resource(self._analysis, node, ATLAS.proposedRelation)
            target = _one_resource(self._analysis, node, ATLAS.targetConcept)
            target_release = _one_resource(self._analysis, node, ATLAS.targetRelease)
            results.append(
                MappingCandidateView(
                    candidate_id=str(node),
                    source_concept_id=str(source),
                    source_release_id=str(source_release),
                    relation=str(relation),
                    target_concept_id=str(target),
                    target_release_id=str(target_release),
                    qualified_for_search=str(node) in qualified,
                )
            )
        return tuple(results)

    def search_only_mappings(self) -> tuple[SearchOnlyMapping, ...]:
        """Return only mappings with an exact usable baseline proof chain."""

        results: list[SearchOnlyMapping] = []
        for node in sorted(
            self._asserted.subjects(RDF.type, RKAF.ConceptMapping), key=str
        ):
            if (node, RKAF.usageEligibility, RKAF.searchOnly) not in self._asserted:
                continue
            if (
                node,
                RKAF.assertionOrigin,
                RKAF.aiSuggested,
            ) not in self._asserted:
                raise VocabularyAtlasError(f"search mapping {node} is not AI suggested")
            if (
                node,
                RKAF.epistemicBasis,
                RKAF.statisticalInference,
            ) not in self._asserted:
                raise VocabularyAtlasError(f"search mapping {node} hides its basis")
            if (node, RKAF.assertionPolarity, RKAF.affirmed) not in self._asserted:
                raise VocabularyAtlasError(f"search mapping {node} has unsafe polarity")
            _one_resource(self._asserted, node, RKAF.hasAILineage)
            if (
                node,
                ATLAS.verificationStatus,
                ATLAS.unverified,
            ) not in self._asserted:
                raise VocabularyAtlasError(
                    f"search mapping {node} hides verification state"
                )
            if (
                node,
                ATLAS.selectionPolicy,
                RdfLiteral(CROSSWALK_SELECTION_POLICY),
            ) not in self._asserted:
                raise VocabularyAtlasError(f"search mapping {node} has another policy")
            candidate = _one_resource(self._asserted, node, ATLAS.qualifiedFrom)
            baseline = _one_resource(self._asserted, node, ATLAS.qualifiedBy)
            if (
                candidate,
                RDF.type,
                ATLAS.ConceptMappingCandidate,
            ) not in self._analysis:
                raise VocabularyAtlasError(f"mapping {node} has no candidate record")
            if (
                baseline,
                RDF.type,
                ATLAS.BaselineValidationReceipt,
            ) not in self._analysis:
                raise VocabularyAtlasError(f"mapping {node} has no baseline receipt")
            if (baseline, ATLAS.validates, candidate) not in self._analysis:
                raise VocabularyAtlasError(
                    f"mapping {node} baseline targets another record"
                )
            if (candidate, ATLAS.qualifiedBy, baseline) not in self._analysis:
                raise VocabularyAtlasError(
                    f"mapping {node} candidate omits qualification"
                )
            if (
                candidate,
                ATLAS.verificationStatus,
                ATLAS.unverified,
            ) not in self._analysis:
                raise VocabularyAtlasError(
                    f"mapping {node} candidate hides verification state"
                )
            aggregate = tuple(self._analysis.objects(baseline, ATLAS.aggregateResult))
            if len(aggregate) != 1 or str(aggregate[0]) not in {
                "usable_for_search",
                "usable_with_nonblocking_limits",
            }:
                raise VocabularyAtlasError(f"mapping {node} baseline is not usable")
            results.append(
                SearchOnlyMapping(
                    mapping_id=str(node),
                    candidate_id=str(candidate),
                    baseline_receipt_id=str(baseline),
                    source_concept_id=str(
                        _one_resource(self._asserted, node, RKAF.assertsSubject)
                    ),
                    source_release_id=str(
                        _one_resource(self._asserted, node, RKAF.sourceConceptRelease)
                    ),
                    relation=str(
                        _one_resource(self._asserted, node, RKAF.assertsPredicate)
                    ),
                    target_concept_id=str(
                        _one_resource(self._asserted, node, RKAF.assertsObject)
                    ),
                    target_release_id=str(
                        _one_resource(self._asserted, node, RKAF.targetConceptRelease)
                    ),
                )
            )
        return tuple(results)

    def feedback(self, candidate_id: str | None = None) -> tuple[FeedbackView, ...]:
        results: list[FeedbackView] = []
        for node in sorted(
            self._analysis.subjects(RDF.type, ATLAS.MappingFeedback), key=str
        ):
            candidate = _one_resource(self._analysis, node, ATLAS.feedbackOn)
            if candidate_id is not None and str(candidate) != candidate_id:
                continue
            actor = _one_resource(self._analysis, node, ATLAS.feedbackActor)
            dispositions = tuple(
                self._analysis.objects(node, ATLAS.feedbackDisposition)
            )
            comments = tuple(self._analysis.objects(node, RDFS.comment))
            if len(dispositions) != 1 or len(comments) != 1:
                raise VocabularyAtlasError(f"feedback {node} has invalid cardinality")
            results.append(
                FeedbackView(
                    feedback_id=str(node),
                    candidate_id=str(candidate),
                    actor_id=str(actor),
                    disposition=str(dispositions[0]),
                    comment=str(comments[0]),
                )
            )
        return tuple(results)


__all__ = [
    "FeedbackView",
    "LabelCluster",
    "MappingCandidateView",
    "SearchOnlyMapping",
    "VocabularyAtlasQueries",
]
