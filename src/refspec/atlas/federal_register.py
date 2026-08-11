"""Atlas adapter for the source-complete 2025 Federal Register thesaurus."""

from __future__ import annotations

import hashlib
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Self, cast

from refspec.immutable import deep_freeze_json
from refspec.managed_release import (
    ManagedReleaseExpression,
    ManagedReleaseMember,
    ManagedReleaseRelation,
)
from refspec.registry.federal_register_thesaurus_2025 import (
    ALTERNATE_LABEL_PROPERTY_IRI,
    FEDERAL_REGISTER_THESAURUS_2025_ISSUED,
    FEDERAL_REGISTER_THESAURUS_2025_SCHEME_IRI,
    FEDERAL_REGISTER_THESAURUS_2025_SHA256,
    PREFERRED_LABEL_PROPERTY_IRI,
    RELATED_PROPERTY_IRI,
)
from refspec.registry.managed_releases.federal_register_thesaurus_2025_managed_release import (
    FEDERAL_REGISTER_THESAURUS_2025_MANAGED_RELEASE_VERSION,
    FEDERAL_REGISTER_THESAURUS_2025_RESOURCE_ID,
    FederalRegisterThesaurus2025ManagedReleaseError,
    FederalRegisterThesaurus2025ManagedReleaseView,
)
from refspec.release_graph import rulespec_graph_digest

from .concept_release import (
    ConceptReleaseError,
    ManagedReleaseRingAssignment,
    PinnedManagedConceptRelease,
    PinnedManagedReleaseRingAssignment,
)
from .model import (
    VocabularyAtlasError,
    _require_digest,
    _require_iri,
    closed_reference_release_digest,
)

FEDERAL_REGISTER_THESAURUS_2025_REFERENCE_RELEASE_IRI = (
    "urn:ref:federal-register-thesaurus:2025-04-01:reference-resource-release:v1"
)
FEDERAL_REGISTER_THESAURUS_2025_RULESPEC_GRAPH_IRI = "urn:ref:federal-register-thesaurus:2025-04-01:rulespec-graph:v1"
FEDERAL_REGISTER_THESAURUS_2025_DISTRIBUTION_IRI = (
    "urn:ref:federal-register-thesaurus:2025-04-01:distribution:source-pdf"
)

_EXPECTED_CONCEPT_COUNT = 705
_EXPECTED_RELATED_REFERENCE_COUNT = 1_463
_EXPECTED_RESOLVED_RELATED_COUNT = 1_451
_EXPECTED_SUGGESTED_RELATED_COUNT = 11
_EXPECTED_UNRESOLVED_RELATED_COUNT = 1
_EXPECTED_OPEN_PATTERN_COUNT = 14
_RKAF = "https://rulespec.org/ns/v1#"
_ATLAS = "https://refspec.org/ns/atlas/v3#"
_RDF_TYPE = "@type"
_SKOS = "http://www.w3.org/2004/02/skos/core#"
_DCTERMS_FORMAT = "http://purl.org/dc/terms/format"
_REFERENCE_RELEASE_DIGEST = "rkaf:referenceReleaseDigest"
_MEMBERSHIP_MODE = "rkaf:membershipMode"
_COMPLETE_MEMBERSHIP = "rkaf:completeMembership"
_VERSION_BASIS = "rkaf:versionBasis"
_CONTENT_DERIVED = "rkaf:contentDerived"
_ARTIFACT_IDENTIFIER = _RKAF + "hasArtifactIdentifier"
_CONTENT_DIGEST = _RKAF + "hasContentDigest"
# Source fidelity is Atlas's own concern: these carry a Federal Register
# relation that the 2025 source states but does not resolve, together with the
# printed locator it was read from. Rulespec defines no term for any of it, so
# they live in the Atlas namespace rather than squatting rkaf:.
_SOURCE_RELATION_RECORD = "atlas:SourceRelationRecord"
_SOURCE_RELATION_RECORDS = "atlas:sourceRelationRecord"


def _sha256_file(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _plain(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _plain(child) for key, child in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return [_plain(child) for child in value]
    return value


def _iri(value: str) -> dict[str, str]:
    return {"@id": value}


def _language_literal(value: str) -> dict[str, str]:
    return {"@language": "en", "@value": value}


def _require_text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise VocabularyAtlasError(f"{label} is required")
    return value


def _require_mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise VocabularyAtlasError(f"{label} must be an object")
    return cast(Mapping[str, Any], value)


def _require_string_sequence(value: object, label: str) -> tuple[str, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise VocabularyAtlasError(f"{label} must be an array")
    result = tuple(value)
    if any(not isinstance(item, str) or not item.strip() for item in result):
        raise VocabularyAtlasError(f"{label} must contain non-empty strings")
    return cast(tuple[str, ...], result)


@dataclass(frozen=True, slots=True)
class FederalRegisterThesaurus2025AtlasView:
    """Verified facts exposed through the atlas's narrow release-view seam."""

    _publication_id: str
    _graph: Mapping[str, Any]
    _members: Mapping[str, ManagedReleaseMember]
    _expressions: tuple[ManagedReleaseExpression, ...]

    @property
    def release_id(self) -> str:
        return self._publication_id

    @property
    def rulespec_graph_id(self) -> str:
        return FEDERAL_REGISTER_THESAURUS_2025_RULESPEC_GRAPH_IRI

    @property
    def rulespec_graph(self) -> Mapping[str, Any]:
        return self._graph

    def iter_members(
        self,
        *,
        release_iri: str | None = None,
    ) -> Iterable[ManagedReleaseMember]:
        return (
            member
            for member in self._members.values()
            if release_iri is None or member.release_iri == release_iri
        )

    def lookup_member(self, member_iri: str) -> ManagedReleaseMember | None:
        return self._members.get(member_iri)

    def iter_expressions(self) -> Iterable[ManagedReleaseExpression]:
        return iter(self._expressions)

    def iter_relations(self) -> Iterable[ManagedReleaseRelation]:
        """The 2025 edition states no concept-to-concept relation of its own.

        Its related references already ride in the source graph, and the
        edition removed the 1995 broad categories, so there is no hierarchy
        here to normalize.
        """

        return ()


def _verified_package(
    manifest_path: Path,
    *,
    expected_manifest_digest: str,
) -> FederalRegisterThesaurus2025ManagedReleaseView:
    if manifest_path.is_symlink() or not manifest_path.is_file():
        raise VocabularyAtlasError("Federal Register managed-release manifest must be a regular file")
    actual = _sha256_file(manifest_path)
    if actual != expected_manifest_digest:
        raise VocabularyAtlasError("Federal Register managed-release manifest digest differs")
    try:
        view = FederalRegisterThesaurus2025ManagedReleaseView.open(manifest_path)
    except FederalRegisterThesaurus2025ManagedReleaseError as error:
        raise VocabularyAtlasError(str(error)) from error
    if _sha256_file(manifest_path) != expected_manifest_digest:
        raise VocabularyAtlasError("Federal Register managed-release manifest changed while opening")
    manifest = view.manifest
    release = _require_mapping(manifest.get("release"), "Federal Register release pin")
    counts = _require_mapping(manifest.get("counts"), "Federal Register release counts")
    coverage = view.coverage
    relation_statuses = Counter(
        _require_text(
            row.get("resolutionStatus"),
            "Federal Register relation resolution status",
        )
        for row in view.relations
    )
    if (
        manifest.get("type") != "urn:ref:type:FederalRegisterThesaurus2025ManagedReleaseManifest"
        or manifest.get("resourceId") != FEDERAL_REGISTER_THESAURUS_2025_RESOURCE_ID
        or manifest.get("version") != FEDERAL_REGISTER_THESAURUS_2025_MANAGED_RELEASE_VERSION
        or release.get("issued") != FEDERAL_REGISTER_THESAURUS_2025_ISSUED
        or release.get("schemeIri") != FEDERAL_REGISTER_THESAURUS_2025_SCHEME_IRI
        or release.get("sourceSha256") != FEDERAL_REGISTER_THESAURUS_2025_SHA256
    ):
        raise VocabularyAtlasError("Federal Register managed-release identity differs from the 2025 package")
    if (
        counts.get("concepts") != _EXPECTED_CONCEPT_COUNT
        or counts.get("relations") != _EXPECTED_RELATED_REFERENCE_COUNT
        or counts.get("suggestedOpenTermPatterns") != _EXPECTED_OPEN_PATTERN_COUNT
        or len(view.concepts) != _EXPECTED_CONCEPT_COUNT
        or len(view.relations) != _EXPECTED_RELATED_REFERENCE_COUNT
        or len(view.suggested_open_term_patterns) != _EXPECTED_OPEN_PATTERN_COUNT
        or relation_statuses
        != {
            "resolved": _EXPECTED_RESOLVED_RELATED_COUNT,
            "suggestedOpenTermPattern": _EXPECTED_SUGGESTED_RELATED_COUNT,
            "unresolved": _EXPECTED_UNRESOLVED_RELATED_COUNT,
        }
        or coverage.get("managedConceptCount") != _EXPECTED_CONCEPT_COUNT
        or coverage.get("candidateLookupAllowed") is not True
        or coverage.get("acceptedOutputAllowed") is not False
    ):
        raise VocabularyAtlasError("Federal Register managed-release coverage is incomplete")
    return view


def _project_view(
    package: FederalRegisterThesaurus2025ManagedReleaseView,
) -> FederalRegisterThesaurus2025AtlasView:
    concept_by_id: dict[str, Mapping[str, Any]] = {}
    concept_by_iri: dict[str, Mapping[str, Any]] = {}
    for row in package.concepts:
        concept_id = _require_text(row.get("conceptId"), "Federal Register concept id")
        concept_iri = _require_text(row.get("conceptIri"), "Federal Register concept IRI")
        if concept_id in concept_by_id or concept_iri in concept_by_iri:
            raise VocabularyAtlasError("Federal Register managed release repeats a concept")
        if row.get("schemeIri") != FEDERAL_REGISTER_THESAURUS_2025_SCHEME_IRI:
            raise VocabularyAtlasError("Federal Register concept uses another scheme")
        _require_text(row.get("preferredLabel"), "Federal Register preferred label")
        _require_mapping(row.get("sourceLocator"), "Federal Register concept source locator")
        concept_by_id[concept_id] = row
        concept_by_iri[concept_iri] = row

    variants_by_concept: dict[str, dict[str, Mapping[str, Any]]] = defaultdict(dict)
    for row in package.variants:
        if row.get("resolutionStatus") != "recognizedVariant":
            continue
        targets = _require_string_sequence(
            row.get("targetConceptIds"),
            "recognized Federal Register variant targets",
        )
        if len(targets) != 1 or targets[0] not in concept_by_id:
            raise VocabularyAtlasError("recognized Federal Register variant has no exact concept")
        label = _require_text(row.get("label"), "Federal Register variant label")
        _require_mapping(row.get("sourceLocator"), "Federal Register variant source locator")
        if label in variants_by_concept[targets[0]]:
            raise VocabularyAtlasError("Federal Register managed release repeats a recognized variant")
        variants_by_concept[targets[0]][label] = row

    related_by_source: dict[str, set[str]] = defaultdict(set)
    unresolved_relation_nodes: list[dict[str, Any]] = []
    for row in package.relations:
        resolution_status = _require_text(
            row.get("resolutionStatus"),
            "Federal Register relation resolution status",
        )
        if resolution_status != "resolved":
            if resolution_status not in {"suggestedOpenTermPattern", "unresolved"}:
                raise VocabularyAtlasError(
                    "Federal Register relation has an unsupported resolution status"
                )
            relation_id = _require_text(
                row.get("relationId"),
                "Federal Register source relation id",
            )
            source_concept_id = _require_text(
                row.get("sourceConceptId"),
                "Federal Register source relation concept id",
            )
            source_concept_iri = _require_text(
                row.get("sourceConceptIri"),
                "Federal Register source relation concept IRI",
            )
            if (
                source_concept_id not in concept_by_id
                or source_concept_iri not in concept_by_iri
                or concept_by_id[source_concept_id] is not concept_by_iri[source_concept_iri]
            ):
                raise VocabularyAtlasError(
                    "Federal Register source relation names another concept"
                )
            locator = _require_mapping(
                row.get("sourceLocator"),
                "Federal Register source relation locator",
            )
            if set(locator) != {"pdf_page", "printed_page", "source_ordinal"} or any(
                isinstance(locator[field], bool) or not isinstance(locator[field], int)
                for field in locator
            ):
                raise VocabularyAtlasError(
                    "Federal Register source relation locator is incomplete"
                )
            unresolved_relation_nodes.append(
                {
                    "@id": (
                        "urn:ref:federal-register-thesaurus:2025-04-01:"
                        f"source-related-reference:{relation_id}"
                    ),
                    _RDF_TYPE: _SOURCE_RELATION_RECORD,
                    "atlas:sourceConcept": _iri(source_concept_iri),
                    "atlas:sourceConceptId": source_concept_id,
                    "atlas:sourceRawTargetLabel": _require_text(
                        row.get("rawTargetLabel"),
                        "Federal Register source relation target label",
                    ),
                    "atlas:sourceRelationId": relation_id,
                    "atlas:sourceRelationStatus": resolution_status,
                    "atlas:sourcePdfPage": locator["pdf_page"],
                    "atlas:sourcePrintedPage": locator["printed_page"],
                    "atlas:sourceOrdinal": locator["source_ordinal"],
                }
            )
            continue
        source = _require_text(row.get("sourceConceptIri"), "Federal Register relation source")
        target = _require_text(row.get("targetConceptIri"), "Federal Register relation target")
        if row.get("predicateIri") != RELATED_PROPERTY_IRI:
            raise VocabularyAtlasError("resolved Federal Register relation uses another predicate")
        if source not in concept_by_iri or target not in concept_by_iri:
            raise VocabularyAtlasError("Federal Register relation endpoint is outside the release")
        _require_mapping(row.get("sourceLocator"), "Federal Register relation source locator")
        related_by_source[source].add(target)

    concept_nodes: list[dict[str, Any]] = []
    members: dict[str, ManagedReleaseMember] = {}
    expressions: list[ManagedReleaseExpression] = []
    for concept_id, row in sorted(concept_by_id.items()):
        concept_iri = cast(str, row["conceptIri"])
        preferred = cast(str, row["preferredLabel"])
        declared_alternates = _require_string_sequence(
            row.get("alternateLabels"),
            "Federal Register alternate labels",
        )
        source_alternates = variants_by_concept.get(concept_id, {})
        if set(declared_alternates) != set(source_alternates):
            raise VocabularyAtlasError("Federal Register alternate labels differ from source variants")
        node: dict[str, Any] = {
            "@id": concept_iri,
            _RDF_TYPE: _RKAF + "RegisteredConcept",
            "skos:inScheme": _iri(FEDERAL_REGISTER_THESAURUS_2025_SCHEME_IRI),
            PREFERRED_LABEL_PROPERTY_IRI: _language_literal(preferred),
        }
        if declared_alternates:
            node[ALTERNATE_LABEL_PROPERTY_IRI] = [_language_literal(label) for label in sorted(declared_alternates)]
        related = sorted(related_by_source.get(concept_iri, ()))
        if related:
            node[RELATED_PROPERTY_IRI] = [_iri(target) for target in related]
        concept_nodes.append(node)
        frozen_node = cast(Mapping[str, Any], deep_freeze_json(node))
        members[concept_iri] = ManagedReleaseMember(
            member_iri=concept_iri,
            release_iri=FEDERAL_REGISTER_THESAURUS_2025_REFERENCE_RELEASE_IRI,
            scheme_iri=FEDERAL_REGISTER_THESAURUS_2025_SCHEME_IRI,
            record=frozen_node,
        )
        expressions.append(
            ManagedReleaseExpression(
                expression_id=concept_iri + ":preferred-label",
                member_iri=concept_iri,
                indexed_text=preferred.casefold(),
                original_literal=preferred,
                language_tag="en",
                semantic_property_iri=PREFERRED_LABEL_PROPERTY_IRI,
                source_property_or_path="records/concepts.jsonl/preferredLabel",
                record=cast(
                    Mapping[str, Any],
                    deep_freeze_json(
                        {
                            "conceptId": concept_id,
                            "labelRole": "preferred",
                            "sourceLocator": row["sourceLocator"],
                        }
                    ),
                ),
                label_role="preferred",
                source_status="active",
            )
        )
        for ordinal, label in enumerate(sorted(declared_alternates), start=1):
            variant = source_alternates[label]
            expressions.append(
                ManagedReleaseExpression(
                    expression_id=concept_iri + f":alternate-label:{ordinal}",
                    member_iri=concept_iri,
                    indexed_text=label.casefold(),
                    original_literal=label,
                    language_tag="en",
                    semantic_property_iri=ALTERNATE_LABEL_PROPERTY_IRI,
                    source_property_or_path="records/variants.jsonl/label",
                    record=cast(
                        Mapping[str, Any],
                        deep_freeze_json(
                            {
                                "conceptId": concept_id,
                                "labelRole": "alternate",
                                "sourceLocator": variant["sourceLocator"],
                                "variantId": variant["variantId"],
                            }
                        ),
                    ),
                    label_role="alternate",
                    source_status="active",
                )
            )

    release_node: dict[str, Any] = {
        "@id": FEDERAL_REGISTER_THESAURUS_2025_REFERENCE_RELEASE_IRI,
        _RDF_TYPE: "rkaf:ReferenceResourceRelease",
        "dcterms:isVersionOf": _iri(FEDERAL_REGISTER_THESAURUS_2025_SCHEME_IRI),
        "dcat:version": FEDERAL_REGISTER_THESAURUS_2025_MANAGED_RELEASE_VERSION,
        "dcterms:type": _iri("skos:ConceptScheme"),
        "dcterms:issued": FEDERAL_REGISTER_THESAURUS_2025_ISSUED,
        _MEMBERSHIP_MODE: _COMPLETE_MEMBERSHIP,
        "prov:hadMember": [_iri(value) for value in sorted(concept_by_iri)],
        "dcat:distribution": _iri(FEDERAL_REGISTER_THESAURUS_2025_DISTRIBUTION_IRI),
        _VERSION_BASIS: _iri(_CONTENT_DERIVED),
    }
    if unresolved_relation_nodes:
        release_node[_SOURCE_RELATION_RECORDS] = [
            _iri(cast(str, row["@id"]))
            for row in sorted(
                unresolved_relation_nodes,
                key=lambda value: cast(str, value["@id"]),
            )
        ]
    graph: dict[str, Any] = {
        "@context": {
            "atlas": _ATLAS,
            "dcat": "http://www.w3.org/ns/dcat#",
            "dcterms": "http://purl.org/dc/terms/",
            "prov": "http://www.w3.org/ns/prov#",
            "rkaf": _RKAF,
            "skos": _SKOS,
        },
        "@graph": [
            {
                "@id": FEDERAL_REGISTER_THESAURUS_2025_SCHEME_IRI,
                _RDF_TYPE: "rkaf:ConceptScheme",
                PREFERRED_LABEL_PROPERTY_IRI: _language_literal(
                    "Federal Register Thesaurus of Indexing Terms, April 1, 2025"
                ),
            },
            {
                "@id": FEDERAL_REGISTER_THESAURUS_2025_DISTRIBUTION_IRI,
                _RDF_TYPE: _RKAF + "Artifact",
                _ARTIFACT_IDENTIFIER: FEDERAL_REGISTER_THESAURUS_2025_DISTRIBUTION_IRI,
                _DCTERMS_FORMAT: "application/pdf",
                _CONTENT_DIGEST: FEDERAL_REGISTER_THESAURUS_2025_SHA256,
            },
            *concept_nodes,
            *unresolved_relation_nodes,
            release_node,
        ]
    }
    release_node[_REFERENCE_RELEASE_DIGEST] = closed_reference_release_digest(
        graph,
        release_iri=FEDERAL_REGISTER_THESAURUS_2025_REFERENCE_RELEASE_IRI,
        label="Federal Register",
    )
    return FederalRegisterThesaurus2025AtlasView(
        _publication_id=cast(str, package.manifest["id"]),
        _graph=cast(Mapping[str, Any], deep_freeze_json(graph)),
        _members=MappingProxyType(dict(members)),
        _expressions=tuple(expressions),
    )


@dataclass(frozen=True, slots=True)
class PinnedFederalRegisterThesaurus2025AtlasRelease:
    """Exact specialized package adapted to the shared atlas producer seam.

    Rulespec contributes only its pinned Core publication.  Release-digest
    computation is part of the source-pinned RefSpec producer, so no Rulespec
    checkout or unrecorded validator can change this release's facts.
    """

    manifest_path: Path
    manifest_digest: str

    @classmethod
    def open(
        cls,
        manifest_path: Path | str,
        *,
        expected_manifest_digest: str,
    ) -> Self:
        selected = Path(manifest_path)
        _verified_package(
            selected,
            expected_manifest_digest=expected_manifest_digest,
        )
        return cls(
            manifest_path=selected.resolve(strict=True),
            manifest_digest=expected_manifest_digest,
        )

    def verified_view(self) -> FederalRegisterThesaurus2025AtlasView:
        package = _verified_package(
            self.manifest_path,
            expected_manifest_digest=self.manifest_digest,
        )
        return _project_view(package)

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


class PinnedFederalRegisterManagedConceptRelease(PinnedManagedConceptRelease):
    """Select the complete 2025 reference release for Atlas 2.0."""

    @classmethod
    def open(
        cls,
        manifest_path: Path | str,
        *,
        expected_manifest_digest: str,
        release_id: str,
        ring_assignment: PinnedManagedReleaseRingAssignment,
    ) -> Self:
        try:
            digest = _require_digest(
                expected_manifest_digest,
                "Federal Register managed release manifest digest",
            )
            selected_release = _require_iri(
                release_id,
                "Federal Register managed concept release id",
            )
            if not isinstance(
                ring_assignment,
                PinnedManagedReleaseRingAssignment,
            ):
                raise ConceptReleaseError(
                    "Federal Register managed concept release requires a pinned ring assignment"
                )
            assignment = ring_assignment.verified_assignment()
            package = _verified_package(
                Path(manifest_path),
                expected_manifest_digest=digest,
            )
            view = _project_view(package)
        except VocabularyAtlasError as error:
            raise ConceptReleaseError(str(error)) from error
        if (
            assignment.managed_manifest_digest != digest
            or assignment.release_id != selected_release
            or assignment.semantic_ring != "subject"
        ):
            raise ConceptReleaseError(
                "Federal Register ring assignment names another exact subject release"
            )
        if selected_release != FEDERAL_REGISTER_THESAURUS_2025_REFERENCE_RELEASE_IRI or not tuple(
            view.iter_members(release_iri=selected_release)
        ):
            raise ConceptReleaseError(
                "Federal Register 2025 release is absent from the selected package"
            )
        return cls(
            manifest_path=Path(manifest_path).resolve(strict=True),
            manifest_digest=digest,
            release_id=selected_release,
            ring_assignment=ring_assignment,
        )

    def _open_verified_view_and_assignment(
        self,
    ) -> tuple[FederalRegisterThesaurus2025AtlasView, ManagedReleaseRingAssignment]:
        try:
            package = _verified_package(
                self.manifest_path,
                expected_manifest_digest=self.manifest_digest,
            )
            view = _project_view(package)
        except VocabularyAtlasError as error:
            raise ConceptReleaseError(str(error)) from error
        assignment = self.ring_assignment.verified_assignment()
        if (
            assignment.managed_manifest_digest != self.manifest_digest
            or assignment.release_id != self.release_id
            or assignment.semantic_ring != "subject"
        ):
            raise ConceptReleaseError(
                "Federal Register ring assignment names another exact subject release"
            )
        if self.release_id != FEDERAL_REGISTER_THESAURUS_2025_REFERENCE_RELEASE_IRI or not tuple(
            view.iter_members(release_iri=self.release_id)
        ):
            raise ConceptReleaseError(
                "Federal Register 2025 release is no longer present or complete"
            )
        return view, assignment

    def verified_view(self) -> FederalRegisterThesaurus2025AtlasView:
        """Reopen the specialized package and select the same complete release."""

        view, _ = self._open_verified_view_and_assignment()
        return view

    def verified_view_and_pin(
        self,
    ) -> tuple[FederalRegisterThesaurus2025AtlasView, dict[str, Any]]:
        """Derive the Atlas pin and graph from one fresh verification boundary."""

        view, assignment = self._open_verified_view_and_assignment()
        return view, self._pin_from_verified_view(view, assignment)  # type: ignore[arg-type]


__all__ = [
    "FEDERAL_REGISTER_THESAURUS_2025_DISTRIBUTION_IRI",
    "FEDERAL_REGISTER_THESAURUS_2025_REFERENCE_RELEASE_IRI",
    "FEDERAL_REGISTER_THESAURUS_2025_RULESPEC_GRAPH_IRI",
    "FederalRegisterThesaurus2025AtlasView",
    "PinnedFederalRegisterManagedConceptRelease",
    "PinnedFederalRegisterThesaurus2025AtlasRelease",
]
