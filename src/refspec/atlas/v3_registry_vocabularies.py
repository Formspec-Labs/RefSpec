"""Source-native Atlas 3 inputs for the complete cached subject vocabularies.

The registry parsers remain the authority for each publisher format.  These
adapters only normalize their checked output into the small Atlas writer
boundary in :mod:`refspec.atlas.v3_source_data`.  They retain English labels,
direct within-release relations, exact source pins, and publisher concept IRIs.
They never import SKOS mapping relations or infer hierarchy from path strings.
"""

from __future__ import annotations

import hashlib
from collections import defaultdict, deque
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict
from pathlib import Path
from typing import Any

from refspec.atlas.v3_source_data import (
    RegistryInputPin,
    RegistryLabel,
    RegistryRelation,
    RegistryRelease,
    RegistryResource,
    ReleaseScope,
)
from refspec.registry.adapters.elsst_acquisition import ELSST_R6
from refspec.registry.doe_osti_thesaurus import (
    DEFINITION_PREDICATE_IRI as DOE_DEFINITION,
)
from refspec.registry.doe_osti_thesaurus import (
    DOE_OSTI_THESAURUS_V1_2020,
    DoeOstiThesaurus,
    parse_doe_osti_thesaurus_file,
)
from refspec.registry.doe_osti_thesaurus import (
    SCOPE_NOTE_PREDICATE_IRI as DOE_SCOPE_NOTE,
)
from refspec.registry.elsst import (
    DEPRECATED_PREDICATE_IRI as ELSST_DEPRECATED,
)
from refspec.registry.elsst import (
    ElsstVocabulary,
    parse_elsst_file,
)
from refspec.registry.federal_register_thesaurus_2025 import (
    FEDERAL_REGISTER_THESAURUS_2025_BYTE_LENGTH,
    FEDERAL_REGISTER_THESAURUS_2025_ISSUED,
    FEDERAL_REGISTER_THESAURUS_2025_SCHEME_IRI,
    FEDERAL_REGISTER_THESAURUS_2025_SHA256,
    FEDERAL_REGISTER_THESAURUS_2025_URL,
    FederalRegisterThesaurus2025,
    parse_federal_register_thesaurus_2025_pdf,
)
from refspec.registry.federal_register_thesaurus_2025 import (
    RELATED_PROPERTY_IRI as FEDERAL_REGISTER_RELATED,
)
from refspec.registry.gcmd_science_keywords import (
    GCMD_SCIENCE_KEYWORDS_24_4,
    GCMD_SCIENCE_KEYWORDS_VIEWER_URL,
    AcquiredGCMDSource,
    ParsedGCMDScienceKeywords,
    parse_gcmd_science_keywords_csv,
)
from refspec.registry.gemet_thesaurus import (
    GEMET_RELEASE_4_2_3,
    GemetVocabulary,
    parse_gemet_file,
)
from refspec.registry.infrastructure.source_identity import derive_uuid7
from refspec.registry.mesh_descriptors import (
    MESH_2026_DESCRIPTOR_COUNT,
    MeshDescriptorSnapshot,
    parse_mesh_descriptor_file,
)
from refspec.registry.nasa_thesaurus import (
    NASA_THESAURUS_SKOS,
    NasaThesaurusVocabulary,
    parse_nasa_thesaurus_file,
)
from refspec.registry.nasa_thesaurus import (
    USE_INSTEAD_PREDICATE_IRI as NASA_USE,
)
from refspec.registry.nasa_thesaurus import (
    USED_FOR_PREDICATE_IRI as NASA_USED_FOR,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_SOURCE_ROOT = REPOSITORY_ROOT / "output" / "registry-real-data-sources"
MESH_2026_SOURCE_URL = "https://nlmpubs.nlm.nih.gov/projects/mesh/MESH_FILES/xmlmesh/desc2026.xml"
MESH_2026_SHA256 = "sha256:9b034cad8bbd4d8d1ef43816d6fd78d33fada52eddff2a0b4455b1fca35cc5ba"
MESH_2026_BYTE_LENGTH = 312_952_703
GEMET_DEFINITION = "http://www.w3.org/2004/02/skos/core#definition"

EXPECTED_RESOURCE_COUNTS = {
    "doe-osti-semantic-thesaurus-2020": 23_626,
    "elsst-r6": 3_470,
    "federal-register-thesaurus-2025": 705,
    "gcmd-science-keywords-24-4": 3_774,
    "gemet-4.2.3": 5_573,
    "mesh-descriptors-2026": 31_110,
    "nasa-thesaurus-skos": 22_622,
}
EXPECTED_RELATION_COUNTS = {
    "doe-osti-semantic-thesaurus-2020": 127_256,
    "elsst-r6": 12_482,
    "federal-register-thesaurus-2025": 1_451,
    "gcmd-science-keywords-24-4": 0,
    "gemet-4.2.3": 14_764,
    "mesh-descriptors-2026": 0,
    "nasa-thesaurus-skos": 160_370,
}
EXPECTED_LABEL_COUNTS = {
    "doe-osti-semantic-thesaurus-2020": 23_626,
    "elsst-r6": 6_234,
    "federal-register-thesaurus-2025": 1_138,
    "gcmd-science-keywords-24-4": 3_774,
    "gemet-4.2.3": 5_645,
    "mesh-descriptors-2026": 134_904,
    "nasa-thesaurus-skos": 27_125,
}

_ROLE_ORDER = {"preferred": 0, "alternate": 1, "hidden": 2}
_NASA_RELATION_PREDICATES = {
    NASA_USE: "https://refspec.org/ns/atlas/v3#thesaurusUse",
    NASA_USED_FOR: "https://refspec.org/ns/atlas/v3#thesaurusUsedFor",
}
_SKOS_BROADER = "http://www.w3.org/2004/02/skos/core#broader"
_SKOS_NARROWER = "http://www.w3.org/2004/02/skos/core#narrower"
_SKOS_RELATED = "http://www.w3.org/2004/02/skos/core#related"
_ATLAS_THESAURUS_RELATED = "https://refspec.org/ns/atlas/v3#thesaurusRelated"
_S27_TRANSFORMATION = {
    "fromPredicate": _SKOS_RELATED,
    "reason": "SKOS-S27-hierarchy-path",
    "rule": "preserveAuthoredAssociationOutsideSkosProjection",
    "toPredicate": _ATLAS_THESAURUS_RELATED,
}


def _input_pin(
    source_root: Path,
    *,
    filename: str,
    sha256: str,
    byte_length: int,
    source_iri: str,
) -> RegistryInputPin:
    return RegistryInputPin(
        path=Path(source_root) / filename,
        logical_path=f"refspec/output/registry-real-data-sources/{filename}",
        sha256=sha256,
        byte_length=byte_length,
        source_iri=source_iri,
    )


def _english(language_tag: str | None, *, untagged_is_english: bool = False) -> bool:
    if language_tag is None:
        return untagged_is_english
    return language_tag.casefold() == "en"


def _literal_payload(value: Any) -> dict[str, str]:
    payload = {
        "value": value.lexical_form,
    }
    if value.language_tag is not None:
        if not _english(value.language_tag):
            raise ValueError("non-English literal cannot enter an Atlas native payload")
        payload["language"] = "en"
    if value.datatype_iri is not None:
        payload["datatypeIri"] = value.datatype_iri
    return payload


def _sorted_labels(labels: Iterable[RegistryLabel]) -> tuple[RegistryLabel, ...]:
    return tuple(
        sorted(
            labels,
            key=lambda item: (
                _ROLE_ORDER[item.role],
                item.value.casefold(),
                item.value,
                item.source_path,
            ),
        )
    )


def _normalize_skos_label_roles(
    labels: Iterable[RegistryLabel],
) -> tuple[tuple[RegistryLabel, ...], tuple[dict[str, str], ...]]:
    """Apply SKOS S13 role precedence while receipting publisher conflicts."""

    retained: list[RegistryLabel] = []
    retained_by_value: dict[str, RegistryLabel] = {}
    conflicts: list[dict[str, str]] = []
    for label in _sorted_labels(labels):
        previous = retained_by_value.get(label.value)
        if previous is None:
            retained_by_value[label.value] = label
            retained.append(label)
            continue
        if previous.role == label.role:
            raise ValueError(
                "normalized registry labels repeat the same value and role: "
                f"{label.value!r} ({label.role})"
            )
        conflicts.append(
            {
                "language": "en",
                "retainedRole": previous.role,
                "retainedSourcePath": previous.source_path,
                "suppressedRole": label.role,
                "suppressedSourcePath": label.source_path,
                "value": label.value,
            }
        )
    return tuple(retained), tuple(conflicts)


def _direct_relations(
    rows: Iterable[Any],
    member_iris: set[str],
    *,
    predicate_map: Mapping[str, str] | None = None,
) -> tuple[RegistryRelation, ...]:
    """Keep each distinct authored triple whose endpoints are release members."""

    normalized_predicates = predicate_map or {}
    result: list[RegistryRelation] = []
    seen: set[tuple[str, str, str]] = set()
    for row in rows:
        predicate = normalized_predicates.get(row.predicate_iri, row.predicate_iri)
        key = (row.subject_iri, predicate, row.object_iri)
        if key in seen or key[0] not in member_iris or key[2] not in member_iris:
            continue
        seen.add(key)
        result.append(
            RegistryRelation(
                subject=key[0],
                predicate=key[1],
                object=key[2],
                source_payload={
                    "subjectIri": key[0],
                    "predicateIri": row.predicate_iri,
                    "objectIri": key[2],
                    "normalizedPredicateIri": key[1],
                },
            )
        )
    return tuple(sorted(result, key=lambda item: (item.subject, item.predicate, item.object)))


def _preserve_s27_conflicts(
    relations: Sequence[RegistryRelation],
) -> tuple[RegistryRelation, ...]:
    """Move hierarchy-connected authored associations to Atlas' native predicate."""

    hierarchy: dict[str, set[str]] = defaultdict(set)
    targets_by_source: dict[str, dict[str, frozenset[str]]] = defaultdict(dict)
    for relation in relations:
        if relation.predicate == _SKOS_BROADER:
            hierarchy[relation.subject].add(relation.object)
        elif relation.predicate == _SKOS_NARROWER:
            hierarchy[relation.object].add(relation.subject)
        elif relation.predicate == _SKOS_RELATED:
            pair = frozenset((relation.subject, relation.object))
            targets_by_source[relation.subject][relation.object] = pair
            targets_by_source[relation.object][relation.subject] = pair

    connected: set[frozenset[str]] = set()
    for source, source_targets in targets_by_source.items():
        pending = dict(source_targets)
        frontier = deque([source])
        visited = {source}
        while frontier and pending:
            current = frontier.popleft()
            for broader in hierarchy.get(current, ()):
                pair = pending.pop(broader, None)
                if pair is not None:
                    connected.add(pair)
                if broader not in visited:
                    visited.add(broader)
                    frontier.append(broader)

    return tuple(
        RegistryRelation(
            subject=relation.subject,
            predicate=_ATLAS_THESAURUS_RELATED,
            object=relation.object,
            source_payload={
                "editorialTransformation": _S27_TRANSFORMATION,
                "publisherRelation": dict(relation.source_payload),
            },
        )
        if relation.predicate == _SKOS_RELATED and frozenset((relation.subject, relation.object)) in connected
        else relation
        for relation in relations
    )


def _source_scoped_identity(
    *,
    namespace: str,
    source_scheme: str,
    source_key: str,
    recorded_at: str,
) -> tuple[str, dict[str, str]]:
    seed = (f"atlas-v3-source-concept-v1\n{source_scheme}\n{source_key}\n").encode()
    uuid = derive_uuid7(recorded_at, seed=seed)
    local_record_id = f"urn:uuid:{uuid}"
    return (
        f"urn:ref:source-concept:v2:{namespace}:{uuid}",
        {
            "identityKind": "refspecSourceScoped",
            "localRecordId": local_record_id,
            "namespaceToken": namespace,
            "sourceKey": source_key,
            "sourceScheme": source_scheme,
        },
    )


def _assert_release_counts(
    key: str,
    resources: Sequence[RegistryResource],
    relations: Sequence[RegistryRelation],
) -> None:
    expected = EXPECTED_RESOURCE_COUNTS[key]
    if len(resources) != expected:
        raise ValueError(f"{key} expected {expected} resources; parsed {len(resources)}")
    expected_labels = EXPECTED_LABEL_COUNTS[key]
    observed_labels = sum(len(resource.labels) for resource in resources)
    if observed_labels != expected_labels:
        raise ValueError(f"{key} expected {expected_labels} English labels; normalized {observed_labels}")
    expected_relations = EXPECTED_RELATION_COUNTS[key]
    if len(relations) != expected_relations:
        raise ValueError(f"{key} expected {expected_relations} direct relations; normalized {len(relations)}")


def _release(
    *,
    key: str,
    resource_id: str,
    source_module: str,
    scope: ReleaseScope,
    issued: str,
    source_release_iri: str,
    atlas_release_iri: str,
    scheme_iri: str,
    source: RegistryInputPin,
    resources: Sequence[RegistryResource],
    relations: Sequence[RegistryRelation] = (),
    dropped_label_count: int = 0,
    metadata: Mapping[str, Any] | None = None,
) -> RegistryRelease:
    _assert_release_counts(key, resources, relations)
    return RegistryRelease(
        key=key,
        resource_id=resource_id,
        source_module=source_module,
        profile="conceptScheme",
        ring="subject",
        scope=scope,
        issued=issued,
        source_release_iri=source_release_iri,
        source_release_digest=source.sha256,
        atlas_release_iri=atlas_release_iri,
        scheme_iri=scheme_iri,
        inputs=(source,),
        resources=tuple(resources),
        relations=_preserve_s27_conflicts(tuple(relations)),
        dropped_label_count=dropped_label_count,
        metadata=dict(metadata or {}),
    )


def _normalize_doe(parsed: DoeOstiThesaurus, source: RegistryInputPin) -> RegistryRelease:
    member_iris = {concept.concept_iri for concept in parsed.concepts}
    labels: dict[str, list[RegistryLabel]] = defaultdict(list)
    dropped = 0
    for row in parsed.labels:
        if row.subject_iri not in member_iris:
            continue
        if not _english(row.value.language_tag):
            dropped += 1
            continue
        labels[row.subject_iri].append(
            RegistryLabel(
                value=row.value.lexical_form,
                role="preferred",
                source_path=f"{row.subject_iri}::{row.value.language_tag}:skos:prefLabel",
            )
        )
    notes: dict[str, list[Any]] = defaultdict(list)
    for row in parsed.notes:
        if row.subject_iri in member_iris and _english(row.value.language_tag):
            notes[row.subject_iri].append(row)

    resources: list[RegistryResource] = []
    for concept in parsed.concepts:
        concept_notes = notes.get(concept.concept_iri, ())
        definitions = [row.value.lexical_form for row in concept_notes if row.property_iri == DOE_DEFINITION]
        other_notes = [row.value.lexical_form for row in concept_notes if row.property_iri == DOE_SCOPE_NOTE]
        resources.append(
            RegistryResource(
                iri=concept.concept_iri,
                labels=_sorted_labels(labels[concept.concept_iri]),
                native_payload={
                    "publisherConceptIri": concept.concept_iri,
                    "schemeIris": list(concept.scheme_iris),
                    "topConceptOfIris": list(concept.top_concept_of_iris),
                },
                source_locator=concept.concept_iri,
                source_digest=source.sha256,
                definition=definitions[0] if definitions else None,
                notes=tuple(other_notes + definitions[1:]),
            )
        )
    relations = _direct_relations(parsed.semantic_relations, member_iris)
    return _release(
        key="doe-osti-semantic-thesaurus-2020",
        resource_id="doe-osti-semantic-thesaurus-2020",
        source_module="refspec.registry.doe_osti_thesaurus",
        scope="publisherRelease",
        issued=DOE_OSTI_THESAURUS_V1_2020.stated_publication_date,
        source_release_iri="urn:ref:source-release:doe-osti-thesaurus:v1-2020",
        atlas_release_iri="urn:ref:atlas-release:3:doe-osti-thesaurus:v1-2020",
        scheme_iri="urn:ref:atlas-resource-scheme:doe-osti-semantic-thesaurus-2020",
        source=source,
        resources=resources,
        relations=relations,
        dropped_label_count=dropped,
    )


def load_doe_osti_release(source_root: Path = DEFAULT_SOURCE_ROOT) -> RegistryRelease:
    release = DOE_OSTI_THESAURUS_V1_2020
    source = _input_pin(
        source_root,
        filename="osti-semantic-thesaurus-2020.rdf",
        sha256=release.expected_sha256,
        byte_length=release.expected_byte_length,
        source_iri=release.source_url,
    )
    parsed = parse_doe_osti_thesaurus_file(
        source.path,
        source_url=release.source_url,
        expected_sha256=release.expected_sha256,
        expected_byte_length=release.expected_byte_length,
        expected_concept_scheme_iri=release.concept_scheme_iri,
    )
    return _normalize_doe(parsed, source)


def _normalize_elsst(parsed: ElsstVocabulary, source: RegistryInputPin) -> RegistryRelease:
    member_iris = {concept.concept_iri for concept in parsed.concepts}
    labels: dict[str, list[RegistryLabel]] = defaultdict(list)
    dropped = 0
    for row in parsed.labels:
        if row.subject_iri not in member_iris:
            continue
        if not _english(row.value.language_tag):
            dropped += 1
            continue
        labels[row.subject_iri].append(
            RegistryLabel(
                value=row.value.lexical_form.strip(),
                role=row.role,
                source_path=f"{row.subject_iri}::{row.property_iri}",
            )
        )
    notes: dict[str, list[Any]] = defaultdict(list)
    for row in parsed.notes:
        if row.subject_iri in member_iris and _english(row.value.language_tag):
            notes[row.subject_iri].append(row)
    notations: dict[str, list[str]] = defaultdict(list)
    for row in parsed.notations:
        if row.subject_iri in member_iris:
            notations[row.subject_iri].append(row.value.lexical_form)
    metadata: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in parsed.metadata_literals:
        if row.subject_iri in member_iris and (row.value.language_tag is None or _english(row.value.language_tag)):
            metadata[row.subject_iri].append({"propertyIri": row.property_iri, **_literal_payload(row.value)})
    deprecated = {
        row.subject_iri: row.value.lexical_form.casefold() == "true"
        for row in parsed.deprecated_assertions
        if row.subject_iri in member_iris and row.predicate_iri == ELSST_DEPRECATED
    }
    resources: list[RegistryResource] = []
    for concept in parsed.concepts:
        concept_notes = notes.get(concept.concept_iri, ())
        definitions = [
            row.value.lexical_form
            for row in concept_notes
            if row.property_iri == "http://www.w3.org/2004/02/skos/core#definition"
        ]
        other_notes = [
            row.value.lexical_form
            for row in concept_notes
            if row.property_iri != "http://www.w3.org/2004/02/skos/core#definition"
        ]
        resources.append(
            RegistryResource(
                iri=concept.concept_iri,
                labels=_sorted_labels(labels[concept.concept_iri]),
                native_payload={
                    "publisherConceptIri": concept.concept_iri,
                    "schemeIris": list(concept.scheme_iris),
                    "topConceptOfIris": list(concept.top_concept_of_iris),
                    "metadata": metadata.get(concept.concept_iri, []),
                },
                source_locator=concept.concept_iri,
                source_digest=source.sha256,
                definition=definitions[0] if definitions else None,
                notes=tuple(other_notes + definitions[1:]),
                notations=tuple(notations.get(concept.concept_iri, ())),
                status="deprecated" if deprecated.get(concept.concept_iri, False) else "active",
            )
        )
    return _release(
        key="elsst-r6",
        resource_id="elsst",
        source_module="refspec.registry.elsst",
        scope="publisherRelease",
        issued="2025-09-23",
        source_release_iri=ELSST_R6.release_iri,
        atlas_release_iri="urn:ref:atlas-release:3:elsst:r6",
        scheme_iri="urn:ref:atlas-resource-scheme:elsst",
        source=source,
        resources=resources,
        relations=_direct_relations(parsed.semantic_relations, member_iris),
        dropped_label_count=dropped,
    )


def load_elsst_r6_release(source_root: Path = DEFAULT_SOURCE_ROOT) -> RegistryRelease:
    source = _input_pin(
        source_root,
        filename=ELSST_R6.filename,
        sha256=ELSST_R6.expected_sha256,
        byte_length=ELSST_R6.expected_byte_length,
        source_iri=ELSST_R6.source_url,
    )
    parsed = parse_elsst_file(
        source.path,
        source_url=ELSST_R6.source_url,
        expected_sha256=ELSST_R6.expected_sha256,
        expected_byte_length=ELSST_R6.expected_byte_length,
    )
    return _normalize_elsst(parsed, source)


def _normalize_gemet(parsed: GemetVocabulary, source: RegistryInputPin) -> RegistryRelease:
    member_iris = {concept.concept_iri for concept in parsed.concepts}
    labels: dict[str, list[RegistryLabel]] = defaultdict(list)
    dropped = 0
    for row in parsed.labels:
        if row.subject_iri not in member_iris:
            continue
        if not _english(row.value.language_tag):
            dropped += 1
            continue
        labels[row.subject_iri].append(
            RegistryLabel(
                value=row.value.lexical_form,
                role=row.role,
                source_path=f"{row.subject_iri}::{row.property_iri}",
            )
        )
    notes: dict[str, list[Any]] = defaultdict(list)
    for row in parsed.notes:
        if row.subject_iri in member_iris and _english(row.value.language_tag):
            notes[row.subject_iri].append(row)
    notations: dict[str, list[str]] = defaultdict(list)
    for row in parsed.notations:
        if row.subject_iri in member_iris and _english(row.value.language_tag):
            notations[row.subject_iri].append(row.value.lexical_form)
    metadata: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in parsed.metadata_literals:
        if row.subject_iri in member_iris and (row.value.language_tag is None or _english(row.value.language_tag)):
            metadata[row.subject_iri].append({"propertyIri": row.property_iri, **_literal_payload(row.value)})

    resources: list[RegistryResource] = []
    label_role_conflict_count = 0
    for concept in parsed.concepts:
        concept_notes = notes.get(concept.concept_iri, ())
        definitions = [row.value.lexical_form for row in concept_notes if row.property_iri == GEMET_DEFINITION]
        other_notes = [row.value.lexical_form for row in concept_notes if row.property_iri != GEMET_DEFINITION]
        normalized_labels, label_role_conflicts = _normalize_skos_label_roles(
            labels[concept.concept_iri]
        )
        label_role_conflict_count += len(label_role_conflicts)
        native_payload: dict[str, Any] = {
            "publisherConceptIri": concept.concept_iri,
            "schemeIris": list(concept.scheme_iris),
            "topConceptOfIris": list(concept.top_concept_of_iris),
            "metadata": metadata.get(concept.concept_iri, []),
        }
        if label_role_conflicts:
            native_payload["labelRoleNormalization"] = {
                "conflicts": list(label_role_conflicts),
                "rule": "skos-s13-preferred-alternate-hidden-precedence-v1",
            }
        resources.append(
            RegistryResource(
                iri=concept.concept_iri,
                labels=normalized_labels,
                native_payload=native_payload,
                source_locator=concept.concept_iri,
                source_digest=source.sha256,
                definition=definitions[0] if definitions else None,
                notes=tuple(other_notes + definitions[1:]),
                notations=tuple(notations.get(concept.concept_iri, ())),
            )
        )
    return _release(
        key="gemet-4.2.3",
        resource_id="gemet",
        source_module="refspec.registry.gemet_thesaurus",
        scope="publisherRelease",
        issued="2021-12-06",
        source_release_iri="urn:ref:source-release:gemet:4.2.3",
        atlas_release_iri="urn:ref:atlas-release:3:gemet:4.2.3",
        scheme_iri="urn:ref:atlas-resource-scheme:gemet",
        source=source,
        resources=resources,
        relations=_direct_relations(parsed.semantic_relations, member_iris),
        dropped_label_count=dropped,
        metadata={
            "labelRoleConflictCount": label_role_conflict_count,
            "labelRoleConflictRule": (
                "skos-s13-preferred-alternate-hidden-precedence-v1"
            ),
        },
    )


def load_gemet_release(source_root: Path = DEFAULT_SOURCE_ROOT) -> RegistryRelease:
    release = GEMET_RELEASE_4_2_3
    source = _input_pin(
        source_root,
        filename=release.filename,
        sha256=release.expected_sha256,
        byte_length=release.expected_byte_length,
        source_iri=release.source_url,
    )
    parsed = parse_gemet_file(
        source.path,
        source_url=release.source_url,
        expected_sha256=release.expected_sha256,
        expected_byte_length=release.expected_byte_length,
    )
    return _normalize_gemet(parsed, source)


def _normalize_nasa(parsed: NasaThesaurusVocabulary, source: RegistryInputPin) -> RegistryRelease:
    member_iris = {concept.concept_iri for concept in parsed.concepts}
    labels: dict[str, list[RegistryLabel]] = defaultdict(list)
    dropped = 0
    for row in parsed.labels:
        if row.subject_iri not in member_iris:
            continue
        if not _english(row.value.language_tag, untagged_is_english=True):
            dropped += 1
            continue
        labels[row.subject_iri].append(
            RegistryLabel(
                value=row.value.lexical_form,
                role=row.role,
                source_path=f"{row.subject_iri}::{row.property_iri}",
            )
        )
    metadata: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in parsed.metadata_literals:
        if row.subject_iri in member_iris and (row.value.language_tag is None or _english(row.value.language_tag)):
            metadata[row.subject_iri].append({"propertyIri": row.property_iri, **_literal_payload(row.value)})
    resources = tuple(
        RegistryResource(
            iri=concept.concept_iri,
            labels=_sorted_labels(labels[concept.concept_iri]),
            native_payload={
                "publisherConceptIri": concept.concept_iri,
                "metadata": metadata.get(concept.concept_iri, []),
                "detachedAnnotationsNotJoined": True,
            },
            source_locator=concept.concept_iri,
            source_digest=source.sha256,
        )
        for concept in parsed.concepts
    )
    direct_rows = (*parsed.semantic_relations, *parsed.use_reference_relations)
    return _release(
        key="nasa-thesaurus-skos",
        resource_id="nasa-thesaurus",
        source_module="refspec.registry.nasa_thesaurus",
        scope="completeCapture",
        issued=NASA_THESAURUS_SKOS.content_last_modified,
        source_release_iri=NASA_THESAURUS_SKOS.source_url,
        atlas_release_iri="urn:ref:atlas-release:3:nasa-thesaurus:skos",
        scheme_iri="urn:ref:atlas-resource-scheme:nasa-thesaurus",
        source=source,
        resources=resources,
        relations=_direct_relations(
            direct_rows,
            member_iris,
            predicate_map=_NASA_RELATION_PREDICATES,
        ),
        dropped_label_count=dropped,
    )


def load_nasa_thesaurus_release(source_root: Path = DEFAULT_SOURCE_ROOT) -> RegistryRelease:
    release = NASA_THESAURUS_SKOS
    source = _input_pin(
        source_root,
        filename=release.filename,
        sha256=release.expected_sha256,
        byte_length=release.expected_byte_length,
        source_iri=release.source_url,
    )
    parsed = parse_nasa_thesaurus_file(
        source.path,
        source_url=release.source_url,
        expected_sha256=release.expected_sha256,
        expected_byte_length=release.expected_byte_length,
    )
    return _normalize_nasa(parsed, source)


def _normalize_mesh(parsed: MeshDescriptorSnapshot, source: RegistryInputPin) -> RegistryRelease:
    if len(parsed.descriptors) != MESH_2026_DESCRIPTOR_COUNT:
        raise ValueError(
            f"MeSH 2026 expected {MESH_2026_DESCRIPTOR_COUNT} descriptors; parsed {len(parsed.descriptors)}"
        )
    resources = tuple(
        RegistryResource(
            iri=descriptor.concept_iri,
            labels=(
                RegistryLabel(
                    value=descriptor.heading,
                    role="preferred",
                    source_path=f"xml:DescriptorRecord[{descriptor.descriptor_ui}]/DescriptorName/String",
                ),
                *(
                    RegistryLabel(
                        value=term,
                        role="alternate",
                        source_path=f"xml:DescriptorRecord[{descriptor.descriptor_ui}]/ConceptList/TermList/Term",
                    )
                    for term in descriptor.entry_terms
                ),
            ),
            native_payload={
                "publisherConceptIri": descriptor.concept_iri,
                "descriptorUi": descriptor.descriptor_ui,
                "descriptorClass": descriptor.descriptor_class,
                "treeNumbers": list(descriptor.tree_numbers),
            },
            source_locator=descriptor.concept_iri,
            source_digest=source.sha256,
            notations=descriptor.tree_numbers,
            status="active",
        )
        for descriptor in parsed.descriptors
    )
    return _release(
        key="mesh-descriptors-2026",
        resource_id="mesh-descriptors",
        source_module="refspec.registry.mesh_descriptors",
        scope="publisherRelease",
        issued="2026-01-01",
        source_release_iri=MESH_2026_SOURCE_URL,
        atlas_release_iri="urn:ref:atlas-release:3:mesh-descriptors:2026",
        scheme_iri="urn:ref:atlas-resource-scheme:mesh-descriptors",
        source=source,
        resources=resources,
    )


def load_mesh_2026_release(source_root: Path = DEFAULT_SOURCE_ROOT) -> RegistryRelease:
    source = _input_pin(
        source_root,
        filename="desc2026.xml",
        sha256=MESH_2026_SHA256,
        byte_length=MESH_2026_BYTE_LENGTH,
        source_iri=MESH_2026_SOURCE_URL,
    )
    parsed = parse_mesh_descriptor_file(
        source.path,
        source_url=MESH_2026_SOURCE_URL,
        observed_at="2026-08-03",
    )
    if parsed.source_sha256 != source.sha256 or parsed.source_byte_length != source.byte_length:
        raise ValueError("MeSH 2026 parser result does not match the exact source pin")
    return _normalize_mesh(parsed, source)


def _normalize_gcmd(
    parsed: ParsedGCMDScienceKeywords,
    source: RegistryInputPin,
) -> RegistryRelease:
    resources: list[RegistryResource] = []
    for row in parsed.rows:
        identifier = row.identifiers[0]
        iri, source_identity = _source_scoped_identity(
            namespace="gcmd-science-keywords",
            source_scheme=GCMD_SCIENCE_KEYWORDS_VIEWER_URL,
            source_key=identifier.value,
            recorded_at=parsed.retrieved_at,
        )
        locator_digest = hashlib.sha256(
            f"{source.source_iri}\n{row.source_path}\n{identifier.value}\n".encode()
        ).hexdigest()
        resources.append(
            RegistryResource(
                iri=iri,
                labels=(
                    RegistryLabel(
                        value=row.preferred_label,
                        role="preferred",
                        source_path=f"{row.source_path}.preferredLabel",
                    ),
                ),
                native_payload={
                    "sourceIdentity": source_identity,
                    "publisherIdentifier": {
                        "value": identifier.value,
                        "kind": identifier.kind,
                        "authorityUri": identifier.authority_uri,
                    },
                    "category": row.category,
                    "topic": row.topic,
                    "term": row.term,
                    "variableLevel1": row.variable_level_1,
                    "variableLevel2": row.variable_level_2,
                    "variableLevel3": row.variable_level_3,
                    "detailedVariable": row.detailed_variable,
                    "hierarchyIsDescriptiveNotInferred": True,
                },
                source_locator=("urn:ref:source-observation:gcmd-science-keywords-24-4:" + locator_digest),
                source_digest=source.sha256,
                notations=(identifier.value,),
            )
        )
    return _release(
        key="gcmd-science-keywords-24-4",
        resource_id="gcmd-science-keywords",
        source_module="refspec.registry.gcmd_science_keywords",
        scope="publisherRelease",
        issued=parsed.revision[:10],
        source_release_iri=GCMD_SCIENCE_KEYWORDS_VIEWER_URL,
        atlas_release_iri="urn:ref:atlas-release:3:gcmd-science-keywords:24.4",
        scheme_iri="urn:ref:atlas-resource-scheme:gcmd-science-keywords",
        source=source,
        resources=resources,
    )


def load_gcmd_24_4_release(source_root: Path = DEFAULT_SOURCE_ROOT) -> RegistryRelease:
    pin = GCMD_SCIENCE_KEYWORDS_24_4
    source = _input_pin(
        source_root,
        filename="gcmd-science-keywords-24.4.csv",
        sha256=pin.expected_sha256,
        byte_length=pin.expected_byte_length,
        source_iri=pin.source.source_url,
    )
    source.verify()
    acquired = AcquiredGCMDSource(
        pin=pin,
        path=source.path,
        sha256=source.sha256,
        byte_length=source.byte_length,
        source_url=source.source_iri,
        resolved_url=None,
        content_type="text/csv",
        acquisition_mode="local",
        cache_hit=True,
        local_source_path=source.path,
    )
    return _normalize_gcmd(parse_gcmd_science_keywords_csv(acquired), source)


def _pdf_source_path(locator: Any, field: str) -> str:
    return f"pdf:page[{locator.pdf_page}]/printed[{locator.printed_page}]/source[{locator.source_ordinal}]/{field}"


def _normalize_federal_register(
    parsed: FederalRegisterThesaurus2025,
    source: RegistryInputPin,
) -> RegistryRelease:
    counts = parsed.counts
    if (
        counts.official_terms != 705
        or counts.variant_occurrences != 526
        or counts.related_references != 1_463
        or counts.resolved_related_references != 1_451
    ):
        raise ValueError(f"Federal Register 2025 parsed-count drift: {counts!r}")

    iri_by_concept_id: dict[str, str] = {}
    identity_by_concept_id: dict[str, Mapping[str, str]] = {}
    for term in parsed.official_terms:
        iri, identity = _source_scoped_identity(
            namespace="federal-register-thesaurus",
            source_scheme=FEDERAL_REGISTER_THESAURUS_2025_SCHEME_IRI,
            source_key=term.concept_id,
            recorded_at=FEDERAL_REGISTER_THESAURUS_2025_ISSUED + "T00:00:00Z",
        )
        iri_by_concept_id[term.concept_id] = iri
        identity_by_concept_id[term.concept_id] = identity

    alternate_labels: dict[str, dict[str, Any]] = defaultdict(dict)
    recognized_variants: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for variant in parsed.variants:
        if variant.resolution_status == "recognizedVariant" and len(variant.target_concept_ids) == 1:
            target = variant.target_concept_ids[0]
            alternate_labels[target].setdefault(variant.label, variant.locator)
            recognized_variants[target].append(
                {
                    "variantId": variant.variant_id,
                    "label": variant.label,
                    "pdfLocator": asdict(variant.locator),
                }
            )

    resources = tuple(
        RegistryResource(
            iri=iri_by_concept_id[term.concept_id],
            labels=(
                RegistryLabel(
                    value=term.label,
                    role="preferred",
                    source_path=_pdf_source_path(term.locator, "officialTerm"),
                ),
                *(
                    RegistryLabel(
                        value=value,
                        role="alternate",
                        source_path=_pdf_source_path(locator, "recognizedVariant"),
                    )
                    for value, locator in sorted(
                        alternate_labels.get(term.concept_id, {}).items(),
                        key=lambda item: (item[0].casefold(), item[0]),
                    )
                ),
            ),
            native_payload={
                "sourceIdentity": identity_by_concept_id[term.concept_id],
                "sourceLocalConceptId": term.concept_id,
                "sourceLocalEntryId": term.entry_id,
                "pdfLocator": asdict(term.locator),
                "recognizedVariants": recognized_variants.get(term.concept_id, []),
            },
            source_locator=("urn:ref:source-record:federal-register-thesaurus:2025-04-01:" + term.entry_id),
            source_digest=source.sha256,
            status="active",
        )
        for term in parsed.official_terms
    )

    relations: list[RegistryRelation] = []
    seen: set[tuple[str, str, str]] = set()
    for row in parsed.related_references:
        if row.resolution_status != "resolved" or row.target_concept_id is None:
            continue
        key = (
            iri_by_concept_id[row.source_concept_id],
            FEDERAL_REGISTER_RELATED,
            iri_by_concept_id[row.target_concept_id],
        )
        if key in seen:
            continue
        seen.add(key)
        relations.append(
            RegistryRelation(
                subject=key[0],
                predicate=key[1],
                object=key[2],
                source_payload={
                    "relationId": row.relation_id,
                    "rawTargetLabel": row.raw_target_label,
                    "sourceConceptId": row.source_concept_id,
                    "targetConceptId": row.target_concept_id,
                    "pdfLocator": asdict(row.locator),
                },
            )
        )
    return _release(
        key="federal-register-thesaurus-2025",
        resource_id="federal-register-thesaurus-2025",
        source_module="refspec.registry.federal_register_thesaurus_2025",
        scope="publisherRelease",
        issued=FEDERAL_REGISTER_THESAURUS_2025_ISSUED,
        source_release_iri=FEDERAL_REGISTER_THESAURUS_2025_URL,
        atlas_release_iri="urn:ref:atlas-release:3:federal-register-thesaurus:2025-04-01",
        scheme_iri="urn:ref:atlas-resource-scheme:federal-register-thesaurus-2025",
        source=source,
        resources=resources,
        relations=relations,
    )


def load_federal_register_2025_release(
    source_root: Path = DEFAULT_SOURCE_ROOT,
) -> RegistryRelease:
    source = _input_pin(
        source_root,
        filename="federal-register-thesaurus-2025.pdf",
        sha256=FEDERAL_REGISTER_THESAURUS_2025_SHA256,
        byte_length=FEDERAL_REGISTER_THESAURUS_2025_BYTE_LENGTH,
        source_iri=FEDERAL_REGISTER_THESAURUS_2025_URL,
    )
    parsed = parse_federal_register_thesaurus_2025_pdf(source.path.read_bytes())
    return _normalize_federal_register(parsed, source)


REGISTRY_VOCABULARY_LOADERS = (
    load_doe_osti_release,
    load_elsst_r6_release,
    load_federal_register_2025_release,
    load_gcmd_24_4_release,
    load_gemet_release,
    load_mesh_2026_release,
    load_nasa_thesaurus_release,
)


def load_all_registry_vocabulary_releases(
    source_root: Path = DEFAULT_SOURCE_ROOT,
) -> tuple[RegistryRelease, ...]:
    """Load all complete cached vocabulary releases in stable key order."""

    return tuple(loader(source_root) for loader in REGISTRY_VOCABULARY_LOADERS)


__all__ = [
    "DEFAULT_SOURCE_ROOT",
    "EXPECTED_LABEL_COUNTS",
    "EXPECTED_RELATION_COUNTS",
    "EXPECTED_RESOURCE_COUNTS",
    "MESH_2026_BYTE_LENGTH",
    "MESH_2026_SHA256",
    "MESH_2026_SOURCE_URL",
    "REGISTRY_VOCABULARY_LOADERS",
    "load_all_registry_vocabulary_releases",
    "load_doe_osti_release",
    "load_elsst_r6_release",
    "load_federal_register_2025_release",
    "load_gcmd_24_4_release",
    "load_gemet_release",
    "load_mesh_2026_release",
    "load_nasa_thesaurus_release",
]
