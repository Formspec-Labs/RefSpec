"""Subject-atlas adapter for the shared source-concept release model.

The source-concept foundation serves four semantic rings.  Vocabulary Atlas
1.0 is still a subject atlas, so this adapter accepts only ``subject`` releases
and refuses entity, value, and legal-identity releases at the boundary.  It
copies exact release membership and labels; it does not infer hierarchy,
mapping, admission, or product permission.
"""

from __future__ import annotations

import hashlib
import unicodedata
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from typing_extensions import Self

from refspec.immutable import deep_freeze_json
from refspec.managed_release import (
    ManagedReleaseExpression,
    ManagedReleaseMember,
    ManagedReleaseRelation,
)
from refspec.registry.infrastructure.identifier_validation import absolute_uri_issue
from refspec.registry.infrastructure.source_concept_release import (
    SOURCE_CONCEPT_RELEASE_MEDIA_TYPE,
    SourceConceptReleaseError,
    SourceConceptReleaseView,
)
from refspec.release_graph import rulespec_graph_digest
from refspec.storage import canonical_json

from .model import VocabularyAtlasError, closed_reference_release_digest

_RKAF = "https://rulespec.org/ns/v1#"
_RDF_TYPE = "@type"
_SKOS = "http://www.w3.org/2004/02/skos/core#"
_SKOS_CONCEPT_SCHEME = _SKOS + "ConceptScheme"
_SKOS_IN_SCHEME = _SKOS + "inScheme"
_SKOS_LABEL_BY_ROLE = {
    "preferred": _SKOS + "prefLabel",
    "alternate": _SKOS + "altLabel",
    "hidden": _SKOS + "hiddenLabel",
}
_PROV_HAD_MEMBER = "http://www.w3.org/ns/prov#hadMember"
_PROV_WAS_DERIVED_FROM = "http://www.w3.org/ns/prov#wasDerivedFrom"
_DCAT_DISTRIBUTION = "http://www.w3.org/ns/dcat#distribution"
_DCAT_VERSION = "http://www.w3.org/ns/dcat#version"
_DCTERMS_FORMAT = "http://purl.org/dc/terms/format"
_DCTERMS_IS_VERSION_OF = "http://purl.org/dc/terms/isVersionOf"
_DCTERMS_PUBLISHER = "http://purl.org/dc/terms/publisher"
_DCTERMS_TYPE = "http://purl.org/dc/terms/type"
_REFERENCE_RELEASE_DIGEST = _RKAF + "referenceReleaseDigest"
_MEMBERSHIP_MODE = _RKAF + "membershipMode"
_COMPLETE_MEMBERSHIP = _RKAF + "completeMembership"
_VERSION_BASIS = _RKAF + "versionBasis"
_CONTENT_DERIVED = _RKAF + "contentDerived"
_ARTIFACT_IDENTIFIER = _RKAF + "hasArtifactIdentifier"
_CONTENT_DIGEST = _RKAF + "hasContentDigest"
_REGISTERED_CONCEPT = _RKAF + "RegisteredConcept"
_REFERENCE_RESOURCE_RELEASE = _RKAF + "ReferenceResourceRelease"
_ARTIFACT = _RKAF + "Artifact"


def _plain(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _plain(child) for key, child in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return [_plain(child) for child in value]
    return value


def _require_text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise VocabularyAtlasError(f"{label} is required")
    return value


def _require_iri(value: object, label: str) -> str:
    iri = _require_text(value, label)
    issue = absolute_uri_issue(iri)
    if issue == "missing-scheme":
        raise VocabularyAtlasError(f"{label} must be an absolute IRI")
    if issue == "credentials":
        raise VocabularyAtlasError(f"{label} must not contain credentials")
    return iri


def _iri(value: str) -> dict[str, str]:
    return {"@id": value}


def _literal(value: str, language: str) -> dict[str, str]:
    return {"@value": value, "@language": language}


def _source_scheme_iri(view: SourceConceptReleaseView) -> str:
    source_scheme = view.release_manifest.get("sourceScheme")
    if not isinstance(source_scheme, Mapping):
        raise VocabularyAtlasError("source-concept release sourceScheme must be an object")
    return _require_iri(
        source_scheme.get("id"),
        "source-concept release sourceScheme.id",
    )


def _observation_by_id(
    view: SourceConceptReleaseView,
) -> dict[str, Mapping[str, Any]]:
    result: dict[str, Mapping[str, Any]] = {}
    for index, observation in enumerate(view.source_bundle.observations):
        identifier = _require_iri(
            observation.get("id"),
            f"source-concept observation[{index}].id",
        )
        if identifier in result:
            raise VocabularyAtlasError("source-concept capture repeats an observation id")
        result[identifier] = observation
    return result


def _expression_id(
    *,
    release_id: str,
    member_iri: str,
    property_iri: str,
    literal: str,
    language: str,
    source_path: str,
) -> str:
    preimage = canonical_json(
        {
            "language": language,
            "literal": literal,
            "member": member_iri,
            "release": release_id,
            "semanticProperty": property_iri,
            "sourcePath": source_path,
        }
    ).encode("utf-8")
    return "urn:ref:source-concept-expression:" + hashlib.sha256(preimage).hexdigest()


@dataclass(frozen=True, slots=True)
class SourceConceptSubjectAtlasView:
    """Verified subject release facts exposed through the atlas view seam."""

    _release_id: str
    _rulespec_graph_id: str
    _graph: Mapping[str, Any]
    _members: Mapping[str, ManagedReleaseMember]
    _expressions: tuple[ManagedReleaseExpression, ...]

    @property
    def release_id(self) -> str:
        return self._release_id

    @property
    def reference_release_iri(self) -> str:
        return self._release_id

    @property
    def rulespec_graph_id(self) -> str:
        return self._rulespec_graph_id

    @property
    def rulespec_graph(self) -> Mapping[str, Any]:
        return self._graph

    def iter_members(self) -> Iterable[ManagedReleaseMember]:
        return self._members.values()

    def lookup_member(self, member_iri: str) -> ManagedReleaseMember | None:
        return self._members.get(member_iri)

    def iter_expressions(self) -> Iterable[ManagedReleaseExpression]:
        return iter(self._expressions)

    def iter_relations(self) -> Iterable[ManagedReleaseRelation]:
        # Relation vocabularies are ring-specific and are not part of this
        # first subject-release slice.  Returning none is an explicit refusal
        # to infer hierarchy from labels or source order.
        return ()


def source_concept_subject_atlas_view(
    view: SourceConceptReleaseView,
) -> SourceConceptSubjectAtlasView:
    """Project one verified subject release without adding authorization."""

    if view.semantic_ring != "subject":
        raise VocabularyAtlasError("source-concept subject atlas adapter rejects non-subject rings")
    release_id = _require_iri(view.release_id, "source-concept release id")
    scheme_iri = _source_scheme_iri(view)
    issuer = _require_iri(
        view.release_manifest.get("issuer"),
        "source-concept release issuer",
    )
    observations = _observation_by_id(view)
    graph_id = release_id + ":rulespec-graph"
    distribution_id = release_id + ":distribution"

    members: dict[str, ManagedReleaseMember] = {}
    expressions: list[ManagedReleaseExpression] = []
    concept_nodes: list[dict[str, Any]] = []
    for concept in sorted(view.concepts, key=lambda value: str(value["id"])):
        member_iri = _require_iri(concept.get("id"), "source concept id")
        if member_iri in members:
            raise VocabularyAtlasError("source-concept release repeats a member")
        if concept.get("semanticRing") != "subject":
            raise VocabularyAtlasError("source-concept release contains a non-subject member")
        if concept.get("sourceScheme") != scheme_iri:
            raise VocabularyAtlasError("source concept names another source scheme")
        observation_id = _require_iri(
            concept.get("sourceObservation"),
            "source concept observation",
        )
        observation = observations.get(observation_id)
        if observation is None:
            raise VocabularyAtlasError("source concept observation is outside its pinned capture")
        labels = observation.get("labels")
        if not isinstance(labels, Sequence) or isinstance(labels, (str, bytes)):
            raise VocabularyAtlasError("source concept labels must be an array")
        node: dict[str, Any] = {
            "@id": member_iri,
            _RDF_TYPE: _REGISTERED_CONCEPT,
            _SKOS_IN_SCHEME: _iri(scheme_iri),
            _DCTERMS_PUBLISHER: _iri(_require_iri(concept.get("issuer"), "source concept issuer")),
            _PROV_WAS_DERIVED_FROM: _iri(observation_id),
        }
        label_values: dict[str, list[dict[str, str]]] = {}
        source_base = _require_text(
            observation.get("sourcePath"),
            "source concept observation sourcePath",
        )
        for label_index, label_value in enumerate(labels):
            if not isinstance(label_value, Mapping):
                raise VocabularyAtlasError("source concept label must be an object")
            role = label_value.get("role")
            property_iri = _SKOS_LABEL_BY_ROLE.get(cast(str, role))
            if property_iri is None:
                raise VocabularyAtlasError("source concept label role is unsupported")
            literal = _require_text(
                label_value.get("value"),
                "source concept label value",
            )
            language = _require_text(
                label_value.get("language"),
                "source concept label language",
            )
            language_literal = _literal(literal, language)
            label_values.setdefault(property_iri, []).append(language_literal)
            source_path = f"{source_base}#labels/{label_index}"
            expressions.append(
                ManagedReleaseExpression(
                    expression_id=_expression_id(
                        release_id=release_id,
                        member_iri=member_iri,
                        property_iri=property_iri,
                        literal=literal,
                        language=language,
                        source_path=source_path,
                    ),
                    member_iri=member_iri,
                    indexed_text=unicodedata.normalize("NFKC", literal).casefold(),
                    original_literal=literal,
                    language_tag=language,
                    semantic_property_iri=property_iri,
                    source_property_or_path=source_path,
                    record=cast(
                        Mapping[str, Any],
                        deep_freeze_json(
                            {
                                "sourceObservation": observation_id,
                                "sourcePath": source_path,
                            }
                        ),
                    ),
                    label_role=cast(str, role),
                    source_status="notDeclared",
                )
            )
        for property_iri, values in sorted(label_values.items()):
            node[property_iri] = sorted(
                values,
                key=lambda value: (value["@language"], value["@value"]),
            )
        concept_nodes.append(node)
        members[member_iri] = ManagedReleaseMember(
            member_iri=member_iri,
            release_iri=release_id,
            scheme_iri=scheme_iri,
            record=cast(Mapping[str, Any], deep_freeze_json(node)),
        )

    member_iris = sorted(members)
    distribution_node = {
        "@id": distribution_id,
        _RDF_TYPE: _ARTIFACT,
        _ARTIFACT_IDENTIFIER: release_id,
        _DCTERMS_FORMAT: SOURCE_CONCEPT_RELEASE_MEDIA_TYPE,
        _CONTENT_DIGEST: view.logical_digest,
    }
    release_node: dict[str, Any] = {
        "@id": release_id,
        _RDF_TYPE: _REFERENCE_RESOURCE_RELEASE,
        _DCTERMS_IS_VERSION_OF: _iri(scheme_iri),
        _DCAT_VERSION: view.release_digest,
        _DCTERMS_TYPE: _iri(_SKOS_CONCEPT_SCHEME),
        _DCTERMS_PUBLISHER: _iri(issuer),
        _MEMBERSHIP_MODE: _iri(_COMPLETE_MEMBERSHIP),
        _VERSION_BASIS: _iri(_CONTENT_DERIVED),
        _PROV_HAD_MEMBER: [_iri(value) for value in member_iris],
        _DCAT_DISTRIBUTION: _iri(distribution_id),
    }
    graph: dict[str, Any] = {
        "@graph": [
            {
                "@id": scheme_iri,
                _RDF_TYPE: _SKOS_CONCEPT_SCHEME,
            },
            release_node,
            distribution_node,
            *concept_nodes,
        ]
    }
    release_node[_REFERENCE_RELEASE_DIGEST] = closed_reference_release_digest(
        graph,
        release_iri=release_id,
        label="source-concept subject",
    )
    frozen_graph = cast(Mapping[str, Any], deep_freeze_json(graph))
    return SourceConceptSubjectAtlasView(
        _release_id=release_id,
        _rulespec_graph_id=graph_id,
        _graph=frozen_graph,
        _members=cast(
            Mapping[str, ManagedReleaseMember],
            dict(sorted(members.items())),
        ),
        _expressions=tuple(sorted(expressions, key=lambda value: value.expression_id)),
    )


@dataclass(frozen=True, slots=True)
class PinnedSourceConceptSubjectAtlasRelease:
    """One exact source-concept bundle exposed as a subject atlas input."""

    manifest_path: Path
    manifest_digest: str

    @classmethod
    def open(
        cls,
        manifest_path: Path | str,
        *,
        expected_manifest_digest: str,
    ) -> Self:
        requested = Path(manifest_path)
        resolved = requested / "bundle-manifest.json" if requested.is_dir() else requested
        try:
            source_view = SourceConceptReleaseView.open(
                resolved,
                expected_manifest_digest=expected_manifest_digest,
            )
        except SourceConceptReleaseError as error:
            raise VocabularyAtlasError(str(error)) from error
        source_concept_subject_atlas_view(source_view)
        return cls(
            manifest_path=resolved.resolve(strict=True),
            manifest_digest=expected_manifest_digest,
        )

    def verified_view(self) -> SourceConceptSubjectAtlasView:
        """Reopen the exact release so later file changes fail closed."""

        try:
            source_view = SourceConceptReleaseView.open(
                self.manifest_path,
                expected_manifest_digest=self.manifest_digest,
            )
        except SourceConceptReleaseError as error:
            raise VocabularyAtlasError(str(error)) from error
        return source_concept_subject_atlas_view(source_view)

    def pin(self) -> dict[str, Any]:
        view = self.verified_view()
        return {
            "role": "ManagedReleaseView",
            "manifestDigest": self.manifest_digest,
            "publicationReleaseId": view.release_id,
            "rulespecGraph": {
                "id": view.rulespec_graph_id,
                "digest": rulespec_graph_digest(_plain(view.rulespec_graph)),
            },
        }


__all__ = [
    "PinnedSourceConceptSubjectAtlasRelease",
    "SourceConceptSubjectAtlasView",
    "source_concept_subject_atlas_view",
]
