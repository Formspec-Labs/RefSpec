"""Read-only queries over a verified Atlas 2.0 distribution.

Atlas 2.0 uses RDF only as a closed index of canonical JSON records.  These
queries read that index and its exact containment links; they never infer
concept identity, mappings, or cross-ring relations from RDF statements or
label equality.
"""

from __future__ import annotations

import unicodedata
from collections import deque
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal, cast

from refspec import binding
from refspec.immutable import deep_freeze_json
from refspec.registry.infrastructure.artifact_serialization import plain_json
from refspec.registry.infrastructure.semantic_foundation import (
    SEMANTIC_RINGS,
    EvidenceAssertion,
    MappingAssertion,
    SemanticRing,
)

from .atlas_scope import SubjectParticipation
from .model import (
    VocabularyAtlasAsset,
    VocabularyAtlasError,
    _decode_atlas_dataset,
    _snapshots_from_records,
)
from .projection import VocabularyAtlasProjection
from .release_snapshot import AtlasReleaseSnapshot

CanonicalRecordRole = Literal[
    "conceptRelease",
    "concept",
    "releaseRecord",
    "relationBundle",
    "evidenceAssertion",
    "mappingAssertion",
    "machineProof",
]
LabelRole = Literal["preferred", "alternate", "hidden"]
LabelMatchMode = Literal["exact", "contains"]
VocabularyAtlasDistribution = VocabularyAtlasAsset | VocabularyAtlasProjection

_RECORD_ROLES = frozenset(
    {
        "conceptRelease",
        "concept",
        "releaseRecord",
        "relationBundle",
        "evidenceAssertion",
        "mappingAssertion",
        "machineProof",
    }
)
_RING_ORDER = {
    "subject": 0,
    "entity": 1,
    "value": 2,
    "legalIdentity": 3,
}
_SKOS_LABEL_FIELDS: tuple[tuple[str, LabelRole], ...] = (
    ("skos:prefLabel", "preferred"),
    ("http://www.w3.org/2004/02/skos/core#prefLabel", "preferred"),
    ("skos:altLabel", "alternate"),
    ("http://www.w3.org/2004/02/skos/core#altLabel", "alternate"),
    ("skos:hiddenLabel", "hidden"),
    ("http://www.w3.org/2004/02/skos/core#hiddenLabel", "hidden"),
)
_SKOS_NATIVE_RELATION_FIELDS: tuple[tuple[str, str], ...] = (
    (
        "skos:broader",
        "http://www.w3.org/2004/02/skos/core#broader",
    ),
    (
        "http://www.w3.org/2004/02/skos/core#broader",
        "http://www.w3.org/2004/02/skos/core#broader",
    ),
    (
        "skos:narrower",
        "http://www.w3.org/2004/02/skos/core#narrower",
    ),
    (
        "http://www.w3.org/2004/02/skos/core#narrower",
        "http://www.w3.org/2004/02/skos/core#narrower",
    ),
    (
        "skos:related",
        "http://www.w3.org/2004/02/skos/core#related",
    ),
    (
        "http://www.w3.org/2004/02/skos/core#related",
        "http://www.w3.org/2004/02/skos/core#related",
    ),
)
_SKOS_NATIVE_RELATION_PREDICATES = frozenset(predicate for _field, predicate in _SKOS_NATIVE_RELATION_FIELDS)


@dataclass(frozen=True, slots=True)
class CanonicalAtlasRecord:
    """One immutable JSON record and its exact Atlas 2.0 index facts."""

    record_id: str
    record_digest: str
    role: CanonicalRecordRole
    native_id: str | None
    release_ids: tuple[str, ...]
    relation_bundle_ids: tuple[str, ...]
    record: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class ConceptVersion:
    """One stable concept identity as recorded in one exact release."""

    concept_id: str
    release_id: str
    semantic_ring: SemanticRing
    record_id: str
    record_digest: str
    record: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class NativeConceptRelation:
    """One source-native SKOS assertion inside one exact concept release."""

    subject_concept: str
    predicate_iri: str
    object_concept: str
    release_id: str
    semantic_ring: SemanticRing
    source_record_id: str
    source_record_digest: str

    @property
    def relation_id(self) -> str:
        return native_concept_relation_id(
            subject_concept=self.subject_concept,
            predicate_iri=self.predicate_iri,
            object_concept=self.object_concept,
            release_id=self.release_id,
            source_record_id=self.source_record_id,
            source_record_digest=self.source_record_digest,
        )


def native_concept_relation_id(
    *,
    subject_concept: str,
    predicate_iri: str,
    object_concept: str,
    release_id: str,
    source_record_id: str,
    source_record_digest: str,
) -> str:
    """Derive the stable view identity for one exact native assertion."""

    digest = binding.canonical_sha256(
        {
            "subjectConcept": subject_concept,
            "predicate": predicate_iri,
            "objectConcept": object_concept,
            "releaseId": release_id,
            "sourceRecordId": source_record_id,
            "sourceRecordDigest": source_record_digest,
        }
    )
    return "urn:ref:vocabulary-atlas-native-relation:" + digest.removeprefix("sha256:")


@dataclass(frozen=True, slots=True)
class AtlasIndexClassification:
    """One resolved portfolio-index row that classifies an exact release."""

    row_id: str
    row_digest: str
    release_id: str
    semantic_ring: SemanticRing
    source_module: str
    resource_id: str
    subject_participation: SubjectParticipation | None
    record_id: str
    record: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class ConceptLabel:
    """One label fact tied to one concept version and its evidence record."""

    concept_id: str
    release_id: str
    semantic_ring: SemanticRing
    value: str
    language: str | None
    role: LabelRole
    evidence_record_id: str


@dataclass(frozen=True, slots=True)
class LabelMatch:
    """A discovery-only label match; it makes no identity or mapping claim."""

    concept: ConceptVersion
    label: ConceptLabel


@dataclass(frozen=True, slots=True)
class EvidenceAssertionView:
    """One typed evidence assertion with its canonical containment facts."""

    record_id: str
    assertion: EvidenceAssertion
    relation_bundle_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class MachineProofView:
    """One complete machine-proof pin cited by typed mapping evidence."""

    record_id: str
    proof_id: str
    semantic_ring: SemanticRing
    relation_bundle_ids: tuple[str, ...]
    record: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class MappingAssertionView:
    """A typed mapping plus its complete evidence and machine-proof closure."""

    record_id: str
    assertion: MappingAssertion
    relation_bundle_ids: tuple[str, ...]
    evidence_assertions: tuple[EvidenceAssertionView, ...]
    machine_proofs: tuple[MachineProofView, ...]

    @property
    def mapping_id(self) -> str:
        return self.assertion.identifier

    @property
    def external_evidence_ids(self) -> tuple[str, ...]:
        """Return every evidence reference retained by the supporting facts."""

        return tuple(
            sorted({identifier for view in self.evidence_assertions for identifier in view.assertion.evidence})
        )

    @property
    def candidate_ids(self) -> tuple[str, ...]:
        return tuple(
            sorted(
                {candidate for view in self.evidence_assertions if (candidate := view.assertion.candidate) is not None}
            )
        )

    @property
    def validation_receipt_ids(self) -> tuple[str, ...]:
        return tuple(
            sorted(
                {identifier for view in self.evidence_assertions for identifier in view.assertion.validation_receipts}
            )
        )


@dataclass(frozen=True, slots=True)
class ConceptNeighborhood:
    """Every direct, asserted relationship attached to one concept version."""

    concept: ConceptVersion
    native_relations: tuple[NativeConceptRelation, ...]
    mapping_assertions: tuple[MappingAssertionView, ...]


def _checked_ring(value: object) -> SemanticRing:
    if not isinstance(value, str) or value not in SEMANTIC_RINGS:
        raise VocabularyAtlasError("semantic ring must be subject, entity, value, or legalIdentity")
    return cast(SemanticRing, value)


def _checked_role(value: object) -> CanonicalRecordRole:
    if not isinstance(value, str) or value not in _RECORD_ROLES:
        raise VocabularyAtlasError("canonical record role is unsupported")
    return cast(CanonicalRecordRole, value)


def _native_id(record: Mapping[str, Any]) -> str | None:
    native = record.get("id", record.get("@id"))
    return native if isinstance(native, str) else None


def _normalized_text(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def _language_values(value: object) -> tuple[tuple[str, str | None], ...]:
    """Read the closed label forms used by source and managed releases."""

    if isinstance(value, str):
        return ((value, None),)
    if isinstance(value, Mapping):
        literal = value.get("@value")
        if isinstance(literal, str):
            language = value.get("@language")
            return (
                (
                    literal,
                    language if isinstance(language, str) and language else None,
                ),
            )
        result: list[tuple[str, str | None]] = []
        for language, child in value.items():
            normalized_language = language if isinstance(language, str) and language not in {"", "@none"} else None
            if isinstance(child, str):
                result.append((child, normalized_language))
            elif isinstance(child, Sequence) and not isinstance(child, (str, bytes)):
                result.extend((item, normalized_language) for item in child if isinstance(item, str))
        return tuple(result)
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return tuple(item for child in value for item in _language_values(child))
    return ()


def _native_relation_targets(
    value: object,
    *,
    label: str,
) -> tuple[str, ...]:
    if isinstance(value, str):
        targets = (value,)
    elif isinstance(value, Mapping) and isinstance(value.get("@id"), str):
        targets = (cast(str, value["@id"]),)
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        targets = tuple(
            target
            for index, child in enumerate(value)
            for target in _native_relation_targets(
                child,
                label=f"{label}[{index}]",
            )
        )
    else:
        raise VocabularyAtlasError(f"{label} must contain one or more concept IRIs")
    if any(not target.strip() for target in targets):
        raise VocabularyAtlasError(f"{label} must contain non-empty concept IRIs")
    if len(targets) != len(set(targets)):
        raise VocabularyAtlasError(f"{label} repeats a concept IRI")
    return targets


class VocabularyAtlasQueries:
    """Consumer queries over one verified canonical asset or derived projection."""

    def __init__(self, asset: VocabularyAtlasDistribution) -> None:
        if not isinstance(
            asset,
            (VocabularyAtlasAsset, VocabularyAtlasProjection),
        ):
            raise VocabularyAtlasError("vocabulary atlas queries require a verified atlas or projection")
        asset._require_verified()
        asset_id = asset.manifest.get("id")
        if not isinstance(asset_id, str):
            raise VocabularyAtlasError("verified atlas manifest has no asset id")
        decoded = _decode_atlas_dataset(asset.payload, asset_id=asset_id).records
        self._records = tuple(
            CanonicalAtlasRecord(
                record_id=value.identifier,
                record_digest=value.digest,
                role=_checked_role(value.role),
                native_id=_native_id(value.record),
                release_ids=tuple(sorted(value.release_containers)),
                relation_bundle_ids=tuple(sorted(value.relation_containers)),
                record=cast(Mapping[str, Any], deep_freeze_json(value.record)),
            )
            for value in decoded
        )
        self._records_by_role = {
            role: tuple(value for value in self._records if value.role == role) for role in _RECORD_ROLES
        }

        self._snapshots = _snapshots_from_records(decoded)
        self._snapshots = tuple(
            sorted(
                self._snapshots,
                key=lambda value: (
                    _RING_ORDER[value.semantic_ring],
                    value.release_id,
                ),
            )
        )
        self._release_rings = {value.release_id: value.semantic_ring for value in self._snapshots}
        self._concepts = self._build_concepts()
        self._concept_by_key = self._build_concept_index()
        self._native_relations = self._build_native_relations()
        self._classifications = self._build_classifications()
        self._release_records_by_native_id = {
            (release_id, value.native_id): value
            for value in self._records_by_role["releaseRecord"]
            if value.native_id is not None
            for release_id in value.release_ids
        }
        self._evidence_by_id = self._build_evidence()
        self._proofs_by_id = self._build_machine_proofs()
        self._mappings = self._build_mappings()

    def _build_concepts(self) -> tuple[ConceptVersion, ...]:
        values: list[ConceptVersion] = []
        for record in self._records_by_role["concept"]:
            if record.native_id is None:
                raise VocabularyAtlasError("canonical concept record has no native identity")
            for release_id in record.release_ids:
                ring = self._release_rings.get(release_id)
                if ring is None:
                    raise VocabularyAtlasError("canonical concept points to an unknown release")
                values.append(
                    ConceptVersion(
                        concept_id=record.native_id,
                        release_id=release_id,
                        semantic_ring=ring,
                        record_id=record.record_id,
                        record_digest=record.record_digest,
                        record=record.record,
                    )
                )
        return tuple(
            sorted(
                values,
                key=lambda value: (
                    _RING_ORDER[value.semantic_ring],
                    value.release_id,
                    value.concept_id,
                    value.record_id,
                ),
            )
        )

    def _build_native_relations(
        self,
    ) -> tuple[NativeConceptRelation, ...]:
        concepts_by_key = {(value.release_id, value.concept_id): value for value in self._concepts}
        relations: dict[
            tuple[str, str, str, str],
            NativeConceptRelation,
        ] = {}
        for concept in self._concepts:
            for field, predicate in _SKOS_NATIVE_RELATION_FIELDS:
                raw_targets = concept.record.get(field)
                if raw_targets is None:
                    continue
                for target in _native_relation_targets(
                    raw_targets,
                    label=(f"concept {concept.concept_id!r} native relation {field}"),
                ):
                    target_concept = concepts_by_key.get((concept.release_id, target))
                    if target_concept is None:
                        raise VocabularyAtlasError(
                            "source-native relation endpoint is outside its exact concept release"
                        )
                    if target_concept.semantic_ring != concept.semantic_ring:
                        raise VocabularyAtlasError("source-native relation crosses semantic rings")
                    key = (
                        concept.release_id,
                        concept.concept_id,
                        predicate,
                        target,
                    )
                    if key in relations:
                        raise VocabularyAtlasError("source-native relation is asserted more than once")
                    relations[key] = NativeConceptRelation(
                        subject_concept=concept.concept_id,
                        predicate_iri=predicate,
                        object_concept=target,
                        release_id=concept.release_id,
                        semantic_ring=concept.semantic_ring,
                        source_record_id=concept.record_id,
                        source_record_digest=concept.record_digest,
                    )
        return tuple(
            relations[key]
            for key in sorted(
                relations,
                key=lambda value: (
                    _RING_ORDER[relations[value].semantic_ring],
                    *value,
                ),
            )
        )

    def _build_concept_index(
        self,
    ) -> Mapping[tuple[str, str], ConceptVersion]:
        result: dict[tuple[str, str], ConceptVersion] = {}
        for value in self._concepts:
            key = (value.release_id, value.concept_id)
            if key in result:
                raise VocabularyAtlasError("atlas repeats a concept version inside one release")
            result[key] = value
        return result

    def _build_classifications(self) -> tuple[AtlasIndexClassification, ...]:
        values: list[AtlasIndexClassification] = []
        required = {
            "rowId",
            "rowDigest",
            "release",
            "semanticRing",
            "sourceModule",
            "resourceId",
        }
        for canonical in self._records_by_role["releaseRecord"]:
            row = canonical.record
            if not required <= set(row):
                continue
            row_id = row["rowId"]
            row_digest = row["rowDigest"]
            source_module = row["sourceModule"]
            resource_id = row["resourceId"]
            participation = row.get("atlasParticipation")
            if not all(isinstance(value, str) for value in (row_id, row_digest, source_module, resource_id)):
                raise VocabularyAtlasError("resolved atlas index row has invalid fields")
            if participation is not None and participation not in {
                "core",
                "specialist",
                "bridge",
            }:
                raise VocabularyAtlasError("resolved atlas index row has unsupported subject participation")
            ring = _checked_ring(row["semanticRing"])
            if ring != "subject" and participation is not None:
                raise VocabularyAtlasError("only subject index rows may name an atlas participation")
            for release_id in canonical.release_ids:
                values.append(
                    AtlasIndexClassification(
                        row_id=row_id,
                        row_digest=row_digest,
                        release_id=release_id,
                        semantic_ring=ring,
                        source_module=source_module,
                        resource_id=resource_id,
                        subject_participation=cast(
                            SubjectParticipation | None,
                            participation,
                        ),
                        record_id=canonical.record_id,
                        record=canonical.record,
                    )
                )
        return tuple(
            sorted(
                values,
                key=lambda value: (
                    _RING_ORDER[value.semantic_ring],
                    value.release_id,
                    value.row_id,
                ),
            )
        )

    def _build_evidence(self) -> Mapping[str, EvidenceAssertionView]:
        result: dict[str, EvidenceAssertionView] = {}
        for canonical in self._records_by_role["evidenceAssertion"]:
            assertion = EvidenceAssertion.from_record(cast(Mapping[str, Any], plain_json(canonical.record)))
            if assertion.identifier in result:
                raise VocabularyAtlasError("atlas repeats an evidence assertion identity")
            result[assertion.identifier] = EvidenceAssertionView(
                record_id=canonical.record_id,
                assertion=assertion,
                relation_bundle_ids=canonical.relation_bundle_ids,
            )
        return result

    def _build_machine_proofs(self) -> Mapping[str, MachineProofView]:
        result: dict[str, MachineProofView] = {}
        for canonical in self._records_by_role["machineProof"]:
            proof_id = canonical.record.get("id")
            if not isinstance(proof_id, str):
                raise VocabularyAtlasError("canonical machine proof has no native identity")
            if proof_id in result:
                raise VocabularyAtlasError("atlas repeats a machine proof identity")
            result[proof_id] = MachineProofView(
                record_id=canonical.record_id,
                proof_id=proof_id,
                semantic_ring=_checked_ring(canonical.record.get("semanticRing")),
                relation_bundle_ids=canonical.relation_bundle_ids,
                record=canonical.record,
            )
        return result

    def _supporting_evidence(
        self,
        identifiers: Sequence[str],
        *,
        relation_bundle_ids: tuple[str, ...],
    ) -> tuple[EvidenceAssertionView, ...]:
        required_bundles = set(relation_bundle_ids)
        selected: dict[str, EvidenceAssertionView] = {}
        pending = list(identifiers)
        while pending:
            identifier = pending.pop()
            if identifier in selected:
                continue
            view = self._evidence_by_id.get(identifier)
            if view is None:
                raise VocabularyAtlasError("mapping assertion cites missing evidence in the canonical index")
            if not required_bundles <= set(view.relation_bundle_ids):
                raise VocabularyAtlasError("mapping evidence is outside the mapping's relation bundle")
            selected[identifier] = view
            adopted = view.assertion.adopted_evidence
            if adopted is not None:
                pending.append(adopted)
        return tuple(selected[key] for key in sorted(selected))

    def _build_mappings(self) -> tuple[MappingAssertionView, ...]:
        result: list[MappingAssertionView] = []
        for canonical in self._records_by_role["mappingAssertion"]:
            assertion = MappingAssertion.from_record(cast(Mapping[str, Any], plain_json(canonical.record)))
            evidence = self._supporting_evidence(
                assertion.evidence,
                relation_bundle_ids=canonical.relation_bundle_ids,
            )
            required_bundles = set(canonical.relation_bundle_ids)
            proof_ids = {proof_id for view in evidence if (proof_id := view.assertion.machine_proof) is not None}
            proofs: list[MachineProofView] = []
            for proof_id in sorted(proof_ids):
                proof = self._proofs_by_id.get(proof_id)
                if proof is None:
                    raise VocabularyAtlasError("mapping evidence cites a missing machine proof")
                if not required_bundles <= set(proof.relation_bundle_ids):
                    raise VocabularyAtlasError("mapping machine proof is outside the mapping's relation bundle")
                proofs.append(proof)
            result.append(
                MappingAssertionView(
                    record_id=canonical.record_id,
                    assertion=assertion,
                    relation_bundle_ids=canonical.relation_bundle_ids,
                    evidence_assertions=evidence,
                    machine_proofs=tuple(proofs),
                )
            )
        return tuple(
            sorted(
                result,
                key=lambda value: (
                    _RING_ORDER[value.assertion.semantic_ring],
                    value.assertion.source_release,
                    value.assertion.target_release,
                    value.mapping_id,
                ),
            )
        )

    def records(
        self,
        *,
        role: CanonicalRecordRole | None = None,
    ) -> tuple[CanonicalAtlasRecord, ...]:
        """Return exact canonical records, optionally restricted by index role."""

        if role is None:
            return self._records
        return self._records_by_role[_checked_role(role)]

    def release_snapshots(
        self,
        *,
        semantic_ring: SemanticRing | None = None,
    ) -> tuple[AtlasReleaseSnapshot, ...]:
        """Return verified logical release snapshots, ordered by ring and id."""

        if semantic_ring is None:
            return self._snapshots
        ring = _checked_ring(semantic_ring)
        return tuple(value for value in self._snapshots if value.semantic_ring == ring)

    def release_snapshot(self, release_id: str) -> AtlasReleaseSnapshot:
        matches = tuple(value for value in self._snapshots if value.release_id == release_id)
        if len(matches) != 1:
            raise VocabularyAtlasError("atlas contains no unique release with that id")
        return matches[0]

    def concepts(
        self,
        *,
        semantic_ring: SemanticRing | None = None,
        release_id: str | None = None,
        concept_id: str | None = None,
    ) -> tuple[ConceptVersion, ...]:
        """Return release-scoped concept versions without coalescing identity."""

        ring = _checked_ring(semantic_ring) if semantic_ring is not None else None
        return tuple(
            value
            for value in self._concepts
            if (ring is None or value.semantic_ring == ring)
            and (release_id is None or value.release_id == release_id)
            and (concept_id is None or value.concept_id == concept_id)
        )

    def native_relations(
        self,
        *,
        release_id: str | None = None,
        predicate_iri: str | None = None,
        concept_id: str | None = None,
    ) -> tuple[NativeConceptRelation, ...]:
        """Return exact source-native SKOS assertions without inference.

        ``concept_id`` selects assertions where the concept is either the
        subject or object. Broader/narrower inverses and symmetric related
        assertions remain separate when the source release states both.
        """

        if predicate_iri is not None and predicate_iri not in _SKOS_NATIVE_RELATION_PREDICATES:
            raise VocabularyAtlasError("source-native relation predicate is unsupported")
        return tuple(
            value
            for value in self._native_relations
            if (release_id is None or value.release_id == release_id)
            and (predicate_iri is None or value.predicate_iri == predicate_iri)
            and (concept_id is None or concept_id in {value.subject_concept, value.object_concept})
        )

    def _native_hierarchy(
        self,
        *,
        release_id: str,
    ) -> tuple[
        Mapping[str, tuple[str, ...]],
        Mapping[str, tuple[str, ...]],
    ]:
        parents: dict[str, set[str]] = {}
        children: dict[str, set[str]] = {}
        broader = "http://www.w3.org/2004/02/skos/core#broader"
        narrower = "http://www.w3.org/2004/02/skos/core#narrower"
        for relation in self.native_relations(release_id=release_id):
            if relation.predicate_iri == broader:
                child, parent = relation.subject_concept, relation.object_concept
            elif relation.predicate_iri == narrower:
                child, parent = relation.object_concept, relation.subject_concept
            else:
                continue
            parents.setdefault(child, set()).add(parent)
            children.setdefault(parent, set()).add(child)
        return (
            {key: tuple(sorted(values)) for key, values in parents.items()},
            {key: tuple(sorted(values)) for key, values in children.items()},
        )

    def _native_hierarchy_closure(
        self,
        concept_id: str,
        *,
        release_id: str,
        ancestors: bool,
    ) -> tuple[ConceptVersion, ...]:
        self.concept(concept_id, release_id=release_id)
        parents, children = self._native_hierarchy(release_id=release_id)
        adjacency = parents if ancestors else children
        distances: dict[str, int] = {}
        pending = deque((value, 1) for value in adjacency.get(concept_id, ()))
        while pending:
            current, distance = pending.popleft()
            previous = distances.get(current)
            if previous is not None and previous <= distance:
                continue
            distances[current] = distance
            pending.extend((value, distance + 1) for value in adjacency.get(current, ()) if value != concept_id)
        return tuple(
            self.concept(identifier, release_id=release_id)
            for identifier in sorted(
                distances,
                key=lambda value: (distances[value], value),
            )
        )

    def native_ancestors(
        self,
        concept_id: str,
        *,
        release_id: str,
    ) -> tuple[ConceptVersion, ...]:
        """Return asserted broader ancestors, nearest first, without inference rows."""

        return self._native_hierarchy_closure(
            concept_id,
            release_id=release_id,
            ancestors=True,
        )

    def native_descendants(
        self,
        concept_id: str,
        *,
        release_id: str,
    ) -> tuple[ConceptVersion, ...]:
        """Return asserted narrower descendants, nearest first, without inference rows."""

        return self._native_hierarchy_closure(
            concept_id,
            release_id=release_id,
            ancestors=False,
        )

    def direct_neighborhood(
        self,
        concept_id: str,
        *,
        release_id: str,
    ) -> ConceptNeighborhood:
        """Return only direct native assertions and admitted mappings."""

        concept = self.concept(concept_id, release_id=release_id)
        return ConceptNeighborhood(
            concept=concept,
            native_relations=self.native_relations(
                release_id=release_id,
                concept_id=concept_id,
            ),
            mapping_assertions=self.mapping_assertions(
                release_id=release_id,
                concept_id=concept_id,
            ),
        )

    def concept_history(self, concept_id: str) -> tuple[ConceptVersion, ...]:
        """Return every release-scoped record for one stable concept identity."""

        return self.concepts(concept_id=concept_id)

    def concept(self, concept_id: str, *, release_id: str) -> ConceptVersion:
        match = self._concept_by_key.get((release_id, concept_id))
        if match is None:
            raise VocabularyAtlasError("atlas contains no unique concept version for that release")
        return match

    def index_classifications(
        self,
        *,
        semantic_ring: SemanticRing | None = None,
        release_id: str | None = None,
        source_module: str | None = None,
    ) -> tuple[AtlasIndexClassification, ...]:
        """Return exact portfolio classifications copied into the atlas."""

        ring = _checked_ring(semantic_ring) if semantic_ring is not None else None
        return tuple(
            value
            for value in self._classifications
            if (ring is None or value.semantic_ring == ring)
            and (release_id is None or value.release_id == release_id)
            and (source_module is None or value.source_module == source_module)
        )

    def _labels_for_version(
        self,
        version: ConceptVersion,
    ) -> tuple[ConceptLabel, ...]:
        values: list[ConceptLabel] = []
        for field, role in _SKOS_LABEL_FIELDS:
            for label, language in _language_values(version.record.get(field)):
                values.append(
                    ConceptLabel(
                        concept_id=version.concept_id,
                        release_id=version.release_id,
                        semantic_ring=version.semantic_ring,
                        value=label,
                        language=language,
                        role=role,
                        evidence_record_id=version.record_id,
                    )
                )

        observation_id = version.record.get("sourceObservation")
        observation = (
            self._release_records_by_native_id.get((version.release_id, observation_id))
            if isinstance(observation_id, str)
            else None
        )
        if observation is not None:
            raw_labels = observation.record.get("labels")
            if isinstance(raw_labels, Sequence) and not isinstance(raw_labels, (str, bytes)):
                for raw in raw_labels:
                    if not isinstance(raw, Mapping):
                        continue
                    label = raw.get("value")
                    language = raw.get("language")
                    role = raw.get("role")
                    if (
                        isinstance(label, str)
                        and (language is None or isinstance(language, str))
                        and role in {"preferred", "alternate", "hidden"}
                    ):
                        values.append(
                            ConceptLabel(
                                concept_id=version.concept_id,
                                release_id=version.release_id,
                                semantic_ring=version.semantic_ring,
                                value=label,
                                language=cast(str | None, language),
                                role=cast(LabelRole, role),
                                evidence_record_id=observation.record_id,
                            )
                        )
        unique = {
            (
                value.value,
                value.language,
                value.role,
                value.evidence_record_id,
            ): value
            for value in values
        }
        return tuple(
            unique[key]
            for key in sorted(
                unique,
                key=lambda value: (
                    _normalized_text(value[0]),
                    value[1] or "",
                    value[2],
                    value[3],
                ),
            )
        )

    def concept_labels(
        self,
        concept_id: str,
        *,
        release_id: str,
    ) -> tuple[ConceptLabel, ...]:
        """Return labels for one exact concept version, never another release."""

        return self._labels_for_version(self.concept(concept_id, release_id=release_id))

    def search_labels(
        self,
        query: str,
        *,
        semantic_ring: SemanticRing,
        release_id: str | None = None,
        language: str | None = None,
        mode: LabelMatchMode = "contains",
    ) -> tuple[LabelMatch, ...]:
        """Search labels inside one explicit ring as a discovery-only aid."""

        ring = _checked_ring(semantic_ring)
        if not isinstance(query, str) or not (needle := _normalized_text(query)):
            raise VocabularyAtlasError("label search query must be non-empty text")
        if mode not in {"exact", "contains"}:
            raise VocabularyAtlasError("label search mode must be exact or contains")
        if release_id is not None:
            release_ring = self._release_rings.get(release_id)
            if release_ring is None:
                raise VocabularyAtlasError("label search release is absent from the atlas")
            if release_ring != ring:
                raise VocabularyAtlasError("label search release belongs to a different semantic ring")

        result: list[LabelMatch] = []
        for concept in self.concepts(
            semantic_ring=ring,
            release_id=release_id,
        ):
            for label in self._labels_for_version(concept):
                haystack = _normalized_text(label.value)
                matched = haystack == needle if mode == "exact" else needle in haystack
                if matched and (language is None or label.language == language):
                    result.append(LabelMatch(concept=concept, label=label))
        return tuple(
            sorted(
                result,
                key=lambda value: (
                    _normalized_text(value.label.value),
                    value.concept.release_id,
                    value.concept.concept_id,
                    value.concept.record_id,
                ),
            )
        )

    def mapping_assertions(
        self,
        *,
        semantic_ring: SemanticRing | None = None,
        release_id: str | None = None,
        concept_id: str | None = None,
    ) -> tuple[MappingAssertionView, ...]:
        """Return typed mappings with complete evidence and proof references."""

        ring = _checked_ring(semantic_ring) if semantic_ring is not None else None
        return tuple(
            value
            for value in self._mappings
            if (ring is None or value.assertion.semantic_ring == ring)
            and (
                release_id is None
                or release_id
                in {
                    value.assertion.source_release,
                    value.assertion.target_release,
                }
            )
            and (
                concept_id is None
                or concept_id
                in {
                    value.assertion.source_concept,
                    value.assertion.target_concept,
                }
            )
        )

    def mapping_assertion(self, mapping_id: str) -> MappingAssertionView:
        matches = tuple(value for value in self._mappings if value.mapping_id == mapping_id)
        if len(matches) != 1:
            raise VocabularyAtlasError("atlas contains no unique mapping assertion with that id")
        return matches[0]


__all__ = [
    "AtlasIndexClassification",
    "CanonicalAtlasRecord",
    "CanonicalRecordRole",
    "ConceptLabel",
    "ConceptNeighborhood",
    "ConceptVersion",
    "EvidenceAssertionView",
    "LabelMatch",
    "LabelMatchMode",
    "LabelRole",
    "MachineProofView",
    "MappingAssertionView",
    "NativeConceptRelation",
    "VocabularyAtlasDistribution",
    "VocabularyAtlasQueries",
    "native_concept_relation_id",
]
