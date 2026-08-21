"""Source-native Atlas 3 inputs for the complete cached subject vocabularies.

The registry parsers remain the authority for each publisher format.  These
adapters only normalize their checked output into the small Atlas writer
boundary in :mod:`refspec.atlas.v3_source_data`.  They retain English labels,
direct within-release relations, exact source pins, and publisher concept IRIs.
They never import SKOS mapping relations or infer hierarchy from path strings.
"""

from __future__ import annotations

import hashlib
import tempfile
from collections import defaultdict, deque
from collections.abc import Collection, Iterable, Mapping, Sequence
from dataclasses import asdict
from pathlib import Path
from typing import Any, cast

from refspec.atlas.registry_claim_input import (
    AtlasRegistryClaimInput,
    RegistryClaimResourceRules,
    registry_relations_from_claim_release,
    registry_resources_from_claim_release,
)
from refspec.atlas.v3_registry_selection import (
    normalize_only_keys,
    select_declared_group,
    wants_group,
)
from refspec.atlas.v3_source_data import (
    LabelRole,
    RegistryInputPin,
    RegistryIdentifier,
    RegistryLabel,
    RegistryRelation,
    RegistryRelease,
    RegistryResource,
    ReleaseScope,
    canonical_digest,
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
from refspec.registry.eurovoc_thesaurus import (
    EUROVOC_RELEASE_4_24,
    SCHEME_MEMBERSHIP_PREDICATE_IRI,
    EuroVocVocabulary,
    acquire_eurovoc_release,
    parse_acquired_eurovoc_release,
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
    ACRONYM_LABEL_PREDICATE_IRI as GEMET_ACRONYM_LABEL,
)
from refspec.registry.gemet_thesaurus import (
    DISPLAY_LABEL_PREDICATE_IRI as GEMET_DISPLAY_LABEL,
)
from refspec.registry.gemet_thesaurus import (
    GEMET_RELEASE_4_2_3,
    GemetVocabulary,
    parse_gemet_file,
)
from refspec.registry.gemet_thesaurus import (
    GROUP_COLLECTION_IRI as GEMET_GROUP_COLLECTION_IRI,
)
from refspec.registry.gemet_thesaurus import (
    MEMBER_PREDICATE_IRI as GEMET_MEMBER_PREDICATE_IRI,
)
from refspec.registry.gemet_thesaurus import (
    SUB_GROUP_OF_PREDICATE_IRI as GEMET_SUB_GROUP_OF_PREDICATE_IRI,
)
from refspec.registry.gemet_thesaurus import (
    SUPER_GROUP_COLLECTION_IRI as GEMET_SUPER_GROUP_COLLECTION_IRI,
)
from refspec.registry.infrastructure.registry_claim_release import (
    RegistryClaimReleaseView,
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
from refspec.vocabulary import is_english_language_tag

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_SOURCE_ROOT = REPOSITORY_ROOT / "output" / "registry-real-data-sources"
MESH_2026_SOURCE_URL = "https://nlmpubs.nlm.nih.gov/projects/mesh/MESH_FILES/xmlmesh/desc2026.xml"
MESH_2026_SHA256 = "sha256:9b034cad8bbd4d8d1ef43816d6fd78d33fada52eddff2a0b4455b1fca35cc5ba"
MESH_2026_BYTE_LENGTH = 312_952_703
GEMET_DEFINITION = "http://www.w3.org/2004/02/skos/core#definition"
_SKOS_DEFINITION = "http://www.w3.org/2004/02/skos/core#definition"
_SKOS_SCOPE_NOTE = "http://www.w3.org/2004/02/skos/core#scopeNote"
_EUROVOC_DOMAIN_OMITTED_NON_ENGLISH_LABEL_COUNT = 546
_EUROVOC_CONCEPT_OMITTED_NON_ENGLISH_LABEL_COUNT = 400_480

EXPECTED_RESOURCE_COUNTS = {
    "doe-osti-semantic-thesaurus-2020": 23_626,
    "elsst-r6": 3_470,
    "eurovoc-4.24": 7_515,
    "eurovoc-domains-4.24": 21,
    "eurovoc-microthesauri-4.24": 127,
    "federal-register-thesaurus-2025": 705,
    "gcmd-science-keywords-24-4": 3_774,
    "gemet-4.2.3": 5_649,
    "mesh-descriptors-2026": 31_110,
    "nasa-thesaurus-skos": 22_622,
}
EXPECTED_RELATION_COUNTS = {
    "doe-osti-semantic-thesaurus-2020": 127_256,
    "elsst-r6": 12_482,
    "eurovoc-4.24": 26_429,
    "eurovoc-domains-4.24": 0,
    "eurovoc-microthesauri-4.24": 7_902,
    "federal-register-thesaurus-2025": 1_451,
    "gcmd-science-keywords-24-4": 0,
    "gemet-4.2.3": 30_906,
    "mesh-descriptors-2026": 0,
    "nasa-thesaurus-skos": 160_370,
}
EXPECTED_LABEL_COUNTS = {
    "doe-osti-semantic-thesaurus-2020": 23_626,
    "elsst-r6": 6_234,
    "eurovoc-4.24": 17_431,
    "eurovoc-domains-4.24": 21,
    "eurovoc-microthesauri-4.24": 127,
    "federal-register-thesaurus-2025": 1_138,
    "gcmd-science-keywords-24-4": 3_774,
    "gemet-4.2.3": 5_993,
    "mesh-descriptors-2026": 134_904,
    "nasa-thesaurus-skos": 27_125,
}

_ROLE_ORDER = {"preferred": 0, "alternate": 1, "hidden": 2}
_NASA_RELATION_PREDICATES = {
    NASA_USE: "https://refspec.org/ns/atlas/v3#thesaurusUse",
    NASA_USED_FOR: "https://refspec.org/ns/atlas/v3#thesaurusUsedFor",
}
_ATLAS_HAS_SCHEME_MEMBER = "https://refspec.org/ns/atlas/v3#hasSchemeMember"
# GEMET's Group/SuperGroup/Theme collections assert membership toward their
# member concepts (or, for a SuperGroup, toward its member Groups) as
# skos:member -- a real predicate, same direction as atlas:hasSchemeMember,
# but not itself an admitted subject-ring NativeRelationAssertion predicate
# (registry-resource-profiles.json). This is a same-publisher, same-release
# predicate substitution -- GEMET owns every endpoint -- so it is recorded
# the way NASA's USE/USED_FOR remap above is: per-row, via
# _direct_relations' predicate_map (every emitted relation's source_payload
# keeps both the original predicateIri and the normalizedPredicateIri), plus
# a release-level note in _normalize_gemet's metadata. REF-035's adoption
# apparatus (RegistryMapping/RegistryMappingEvidence) is deliberately not
# used here: that machinery answers an evidence-warrant question -- do two
# *different* publishers' claims correspond -- and this is a predicate
# translation within one publisher's own release, not an adjudicated claim.
_GEMET_ORGANIZATION_MEMBERSHIP_PREDICATES = {
    GEMET_MEMBER_PREDICATE_IRI: _ATLAS_HAS_SCHEME_MEMBER,
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


def _literal_payload(value: Any) -> dict[str, str]:
    payload = {
        "value": value.lexical_form,
    }
    if value.language_tag is not None:
        if not is_english_language_tag(value.language_tag):
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
            continue
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


def _normalize_english_label_candidates(
    candidates: Iterable[tuple[str, str | None, str, LabelRole, str]],
    member_iris: Collection[str],
    *,
    untagged_is_english: bool = False,
) -> tuple[dict[str, list[RegistryLabel]], int, int, int, int]:
    """Normalize English-family labels with exact-English precedence."""

    rows = tuple(row for row in candidates if row[0] in member_iris)

    def is_base_english(language: str | None) -> bool:
        return (language is None and untagged_is_english) or (
            language is not None and language.casefold() == "en"
        )

    base_values: dict[str, set[str]] = defaultdict(set)
    base_preferred: set[str] = set()
    for subject_iri, language, value, role, _source_path in rows:
        if not is_base_english(language):
            continue
        base_values[subject_iri].add(value)
        if role == "preferred":
            base_preferred.add(subject_iri)

    labels: dict[str, list[RegistryLabel]] = defaultdict(list)
    seen: dict[str, set[tuple[str, str]]] = defaultdict(set)
    dropped = 0
    variant_count = 0
    duplicate_count = 0
    variant_synonym_count = 0
    for _position, (subject_iri, language, value, role, source_path) in sorted(
        enumerate(rows),
        key=lambda row: (not is_base_english(row[1][1]), row[0]),
    ):
        if not is_english_language_tag(
            language,
            untagged_is_english=untagged_is_english,
        ):
            dropped += 1
            continue
        variant = not is_base_english(language)
        if variant:
            variant_count += 1
        if variant and value in base_values[subject_iri]:
            duplicate_count += 1
            continue
        if variant and role == "preferred" and subject_iri in base_preferred:
            role = "alternate"
        identity = (value, role)
        if identity in seen[subject_iri]:
            if variant:
                duplicate_count += 1
            continue
        seen[subject_iri].add(identity)
        if variant:
            variant_synonym_count += 1
        labels[subject_iri].append(
            RegistryLabel(
                value=value,
                role=role,
                source_path=source_path,
            )
        )
    return (
        labels,
        dropped,
        variant_count,
        duplicate_count,
        variant_synonym_count,
    )


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
    inputs: Sequence[RegistryInputPin] | None = None,
    source_release_digest: str | None = None,
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
        source_release_digest=source_release_digest or source.sha256,
        atlas_release_iri=atlas_release_iri,
        scheme_iri=scheme_iri,
        inputs=tuple(inputs or (source,)),
        resources=tuple(resources),
        relations=_preserve_s27_conflicts(tuple(relations)),
        dropped_label_count=dropped_label_count,
        metadata=dict(metadata or {}),
    )


def _normalize_doe(parsed: DoeOstiThesaurus, source: RegistryInputPin) -> RegistryRelease:
    member_iris = {concept.concept_iri for concept in parsed.concepts}
    (
        labels,
        dropped,
        _variants,
        _duplicates,
        _synonyms,
    ) = _normalize_english_label_candidates(
        (
            (
                row.subject_iri,
                row.value.language_tag,
                row.value.lexical_form,
                "preferred",
                (
                    f"{row.subject_iri}::{row.value.language_tag}:"
                    "skos:prefLabel"
                ),
            )
            for row in parsed.labels
        ),
        member_iris,
    )
    notes: dict[str, list[Any]] = defaultdict(list)
    for row in parsed.notes:
        if row.subject_iri in member_iris and is_english_language_tag(row.value.language_tag):
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
    (
        labels,
        dropped,
        _variants,
        _duplicates,
        _synonyms,
    ) = _normalize_english_label_candidates(
        (
            (
                row.subject_iri,
                row.value.language_tag,
                row.value.lexical_form.strip(),
                row.role,
                f"{row.subject_iri}::{row.property_iri}",
            )
            for row in parsed.labels
        ),
        member_iris,
    )
    notes: dict[str, list[Any]] = defaultdict(list)
    for row in parsed.notes:
        if row.subject_iri in member_iris and is_english_language_tag(row.value.language_tag):
            notes[row.subject_iri].append(row)
    notations: dict[str, list[str]] = defaultdict(list)
    for row in parsed.notations:
        if row.subject_iri in member_iris:
            notations[row.subject_iri].append(row.value.lexical_form)
    metadata: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in parsed.metadata_literals:
        if row.subject_iri in member_iris and (
            row.value.language_tag is None
            or is_english_language_tag(row.value.language_tag)
        ):
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


def _normalize_eurovoc(
    parsed: EuroVocVocabulary,
    archive: RegistryInputPin,
    metadata: RegistryInputPin,
) -> tuple[RegistryRelease, RegistryRelease]:
    """Split the complete source into its thesaurus and domain schemes."""

    concept_iris = {concept.concept_iri for concept in parsed.concepts}
    domain_iris = {domain.domain_iri for domain in parsed.domains}
    memberships: dict[str, list[str]] = defaultdict(list)
    for row in parsed.scheme_memberships:
        memberships[row.subject_iri].append(row.object_iri)
    top_concept_of: dict[str, list[str]] = defaultdict(list)
    for row in parsed.top_concept_of_relations:
        top_concept_of[row.subject_iri].append(row.object_iri)
    annotations: dict[str, dict[str, list[str]]] = defaultdict(
        lambda: defaultdict(list)
    )
    for row in parsed.annotations:
        value = row.value.lexical_form.strip()
        if (
            row.subject_iri in concept_iris | domain_iris
            and value
            and is_english_language_tag(row.value.language_tag)
        ):
            annotations[row.subject_iri][row.property_iri].append(value)

    label_candidates = tuple(
        (
            row.subject_iri,
            row.value.language_tag,
            row.value.lexical_form.strip(),
            row.role,
            f"{row.subject_iri}::{row.property_iri}",
        )
        for row in parsed.labels
    )
    concept_labels, concept_dropped, _variants, _duplicates, _synonyms = (
        _normalize_english_label_candidates(label_candidates, concept_iris)
    )
    domain_labels, domain_dropped, _variants, _duplicates, _synonyms = (
        _normalize_english_label_candidates(label_candidates, domain_iris)
    )
    labels: dict[str, list[RegistryLabel]] = defaultdict(list, concept_labels)
    labels.update(domain_labels)
    dropped_by_kind = {
        "concept": concept_dropped,
        "domain": domain_dropped,
    }

    label_conflict_count = 0

    def normalized_labels(iri: str) -> tuple[RegistryLabel, ...]:
        nonlocal label_conflict_count
        retained, conflicts = _normalize_skos_label_roles(labels[iri])
        label_conflict_count += len(conflicts)
        return retained

    common_payload = {
        "attribution": EUROVOC_RELEASE_4_24.attribution,
        "licenseIri": EUROVOC_RELEASE_4_24.license_iri,
        "publisher": EUROVOC_RELEASE_4_24.publisher,
        "releaseVersion": EUROVOC_RELEASE_4_24.version,
    }
    def resource_annotations(iri: str) -> tuple[str | None, tuple[str, ...]]:
        definitions = sorted(
            set(annotations[iri].get(_SKOS_DEFINITION, ()))
        )
        scope_notes = set(annotations[iri].get(_SKOS_SCOPE_NOTE, ()))
        return (
            definitions[0] if definitions else None,
            tuple(sorted(scope_notes | set(definitions[1:]))),
        )

    concept_resources: list[RegistryResource] = []
    for concept in parsed.concepts:
        definition, notes = resource_annotations(concept.concept_iri)
        concept_resources.append(
            RegistryResource(
                iri=concept.concept_iri,
                labels=normalized_labels(concept.concept_iri),
                native_payload={
                    **common_payload,
                    "publisherConceptIri": concept.concept_iri,
                    "publisherResourceKind": "ThesaurusConcept",
                    "schemeIris": sorted(memberships[concept.concept_iri]),
                    "topConceptOfIris": sorted(
                        top_concept_of[concept.concept_iri]
                    ),
                },
                source_locator=concept.concept_iri,
                source_digest=EUROVOC_RELEASE_4_24.expected_member_sha256,
                definition=definition,
                notes=notes,
                notations=(concept.notation,),
                status="active",
            )
        )
    domain_resources: list[RegistryResource] = []
    for domain in parsed.domains:
        definition, notes = resource_annotations(domain.domain_iri)
        domain_resources.append(
            RegistryResource(
                iri=domain.domain_iri,
                labels=normalized_labels(domain.domain_iri),
                native_payload={
                    **common_payload,
                    "publisherConceptIri": domain.domain_iri,
                    "publisherResourceKind": "Domain",
                    "schemeIris": sorted(memberships[domain.domain_iri]),
                    "topConceptOfIris": sorted(
                        top_concept_of[domain.domain_iri]
                    ),
                },
                source_locator=domain.domain_iri,
                source_digest=EUROVOC_RELEASE_4_24.expected_member_sha256,
                definition=definition,
                notes=notes,
                notations=(domain.code,),
                status="active",
            )
        )
    if label_conflict_count:
        raise ValueError(
            "EuroVoc 4.24 contains English labels assigned to multiple SKOS roles"
        )

    inputs = (archive, metadata)
    release_digest_basis = {
        "archiveDigest": archive.sha256,
        "memberDigest": EUROVOC_RELEASE_4_24.expected_member_sha256,
        "metadataDigest": metadata.sha256,
        "version": EUROVOC_RELEASE_4_24.version,
    }
    concepts = _release(
        key="eurovoc-4.24",
        resource_id="eurovoc",
        source_module="refspec.registry.eurovoc_thesaurus",
        scope="publisherRelease",
        issued=EUROVOC_RELEASE_4_24.issued,
        source_release_iri=(
            "http://publications.europa.eu/resource/dataset/"
            "eurovoc/20260708-0#thesaurus-concepts"
        ),
        atlas_release_iri="urn:ref:atlas-release:3:eurovoc:4.24",
        scheme_iri="urn:ref:atlas-resource-scheme:eurovoc",
        source=archive,
        inputs=inputs,
        source_release_digest=canonical_digest(
            {**release_digest_basis, "memberPartition": "thesaurusConcepts"}
        ),
        resources=concept_resources,
        relations=_direct_relations(parsed.semantic_relations, concept_iris),
        dropped_label_count=dropped_by_kind["concept"],
        metadata={
            "completePublisherRelease": True,
            "licenseIri": EUROVOC_RELEASE_4_24.license_iri,
            "memberPartition": "thesaurusConcepts",
            "publisherConceptCount": len(concept_resources),
            "sourceArchiveDigest": archive.sha256,
            "sourceMemberDigest": EUROVOC_RELEASE_4_24.expected_member_sha256,
            "sourceMetadataDigest": metadata.sha256,
            "thesaurusVersion": parsed.thesaurus_version,
        },
    )
    domains = _release(
        key="eurovoc-domains-4.24",
        resource_id="eurovoc",
        source_module="refspec.registry.eurovoc_thesaurus",
        scope="publisherRelease",
        issued=EUROVOC_RELEASE_4_24.issued,
        source_release_iri=(
            "http://publications.europa.eu/resource/dataset/"
            "eurovoc/20260708-0#domains"
        ),
        atlas_release_iri="urn:ref:atlas-release:3:eurovoc-domains:4.24",
        scheme_iri="urn:ref:atlas-resource-scheme:eurovoc:domains",
        source=archive,
        inputs=inputs,
        source_release_digest=canonical_digest(
            {**release_digest_basis, "memberPartition": "domains"}
        ),
        resources=domain_resources,
        dropped_label_count=dropped_by_kind["domain"],
        metadata={
            "completePublisherRelease": True,
            "licenseIri": EUROVOC_RELEASE_4_24.license_iri,
            "memberPartition": "domains",
            "publisherConceptCount": len(domain_resources),
            "sourceArchiveDigest": archive.sha256,
            "sourceMemberDigest": EUROVOC_RELEASE_4_24.expected_member_sha256,
            "sourceMetadataDigest": metadata.sha256,
            "thesaurusVersion": parsed.thesaurus_version,
        },
    )
    return concepts, domains


_ATLAS_HAS_SCHEME_MEMBER = "https://refspec.org/ns/atlas/v3#hasSchemeMember"
# REF-046 (docs/decisions.md) found the 7,902 concept-to-microthesaurus
# skos:inScheme memberships are real publisher assertions. They cannot be
# projected as a second skos:inScheme triple on the concept:
# atlas:SubjectConceptShape fixes skos:inScheme to exactly one value, equal
# to atlas:inScheme, already spent on the concept's single primary EuroVoc
# scheme. Asserting the fact from the microthesaurus toward its member
# concept instead -- the mirror direction, under a distinct native predicate
# -- keeps the SAME fact (never a second, additional assertion in the
# opposite direction) while satisfying that cardinality and the producer's
# own requirement that a relation's evidence be a SourceRecord native to the
# release that owns the relation (the microthesaurus's own record, which
# lives in this release, not eurovoc-4.24's).
_EUROVOC_MICROTHESAURUS_MEMBERSHIP_TRANSFORMATION = {
    "fromPredicate": SCHEME_MEMBERSHIP_PREDICATE_IRI,
    "reason": "SubjectConceptShape fixes skos:inScheme to exactly one value equal to atlas:inScheme",
    "rule": "assertAdditionalSchemeMembershipFromContainerTowardMember",
    "toPredicate": _ATLAS_HAS_SCHEME_MEMBER,
}


def _eurovoc_microthesauri(parsed: EuroVocVocabulary) -> dict[str, str]:
    """Every EuroVoc concept scheme that is a notated microthesaurus.

    A microthesaurus is a concept scheme carrying a four-digit numeric
    publisher notation -- the same selection rule
    ``refspec.registry.eurovoc_organization_experiment`` uses. The main
    thesaurus scheme and the domains grouping scheme both carry
    ``notation=None`` and are excluded by construction.
    """

    return {
        scheme.scheme_iri: scheme.notation
        for scheme in parsed.concept_schemes
        if scheme.notation is not None and len(scheme.notation) == 4 and scheme.notation.isdigit()
    }


def _normalize_eurovoc_microthesauri(
    parsed: EuroVocVocabulary,
    archive: RegistryInputPin,
    metadata: RegistryInputPin,
) -> RegistryRelease:
    """Build the EuroVoc microthesauri organization release.

    The Publications Office asserts 127 notated microthesaurus schemes and
    7,902 concept-to-microthesaurus ``skos:inScheme`` memberships in the
    same pinned SKOS Core member ``eurovoc-4.24``/``eurovoc-domains-4.24``
    are already built from. REF-045 (docs/decisions.md) found both are real
    publisher facts, promoted here for the first time.

    English labels only, as every other EuroVoc-derived release in this
    module already does. This one previously carried all ~24 publisher
    languages and demoted each non-English ``skos:prefLabel`` to
    ``alternate``, because `atlas.shacl.ttl`'s `SkosXlPrefLabelShape` fixes
    ``skosxl:prefLabel`` to exactly one value per resource. That made it
    the only multilingual release here, and the only one whose Atlas role
    for a label differed from the publisher's -- a transformation no
    independent reader could reproduce without being told about it, and
    which nothing downstream asked for. Dropping the other languages
    removes both the anomaly and the transformation: every label the Atlas
    carries now has the publisher's own role.

    Every membership is still emitted, including the 142+121+1 concepts
    that belong to two, three, or four microthesauri at once --
    multi-membership is a real publisher fact and is never collapsed.
    """

    microthesauri = _eurovoc_microthesauri(parsed)
    concept_iris = {concept.concept_iri for concept in parsed.concepts}

    labels_by_iri: dict[str, list[RegistryLabel]] = defaultdict(list)
    for row in parsed.labels:
        if row.subject_iri not in microthesauri:
            continue
        if not is_english_language_tag(row.value.language_tag):
            continue
        labels_by_iri[row.subject_iri].append(
            RegistryLabel(
                value=row.value.lexical_form,
                role=row.role,
                source_path=f"{row.subject_iri}::{row.property_iri}::{row.value.language_tag}",
                language=row.value.language_tag.casefold(),
            )
        )
    missing_english_preferred = {
        iri
        for iri in microthesauri
        if sum(1 for label in labels_by_iri.get(iri, ()) if label.role == "preferred") != 1
    }
    if missing_english_preferred:
        raise ValueError(
            "EuroVoc microthesaurus has no exactly-one English preferred label to keep: "
            f"{sorted(missing_english_preferred)[:1]}"
        )

    common_payload = {
        "attribution": EUROVOC_RELEASE_4_24.attribution,
        "licenseIri": EUROVOC_RELEASE_4_24.license_iri,
        "publisher": EUROVOC_RELEASE_4_24.publisher,
        "releaseVersion": EUROVOC_RELEASE_4_24.version,
    }
    resources: list[RegistryResource] = []
    for scheme_iri, notation in sorted(microthesauri.items()):
        labels = _sorted_labels(labels_by_iri.get(scheme_iri, ()))
        if not labels:
            raise ValueError(f"EuroVoc microthesaurus {scheme_iri} has no label")
        resources.append(
            RegistryResource(
                iri=scheme_iri,
                labels=labels,
                native_payload={
                    **common_payload,
                    "publisherConceptIri": scheme_iri,
                    "publisherResourceKind": "MicroThesaurus",
                },
                source_locator=scheme_iri,
                source_digest=EUROVOC_RELEASE_4_24.expected_member_sha256,
                notations=(notation,),
                status="active",
            )
        )

    seen: set[tuple[str, str]] = set()
    relations: list[RegistryRelation] = []
    for row in parsed.scheme_memberships:
        if row.subject_iri not in concept_iris or row.object_iri not in microthesauri:
            continue
        if row.predicate_iri != SCHEME_MEMBERSHIP_PREDICATE_IRI:
            raise ValueError(
                f"EuroVoc microthesaurus membership uses an unexpected predicate: {row.predicate_iri}"
            )
        key = (row.object_iri, row.subject_iri)
        if key in seen:
            raise ValueError(f"duplicate EuroVoc microthesaurus membership: {key!r}")
        seen.add(key)
        relations.append(
            RegistryRelation(
                subject=row.object_iri,
                predicate=_ATLAS_HAS_SCHEME_MEMBER,
                object=row.subject_iri,
                source_payload={
                    "subjectIri": row.subject_iri,
                    "predicateIri": row.predicate_iri,
                    "objectIri": row.object_iri,
                    "normalizedPredicateIri": _ATLAS_HAS_SCHEME_MEMBER,
                    "editorialTransformation": _EUROVOC_MICROTHESAURUS_MEMBERSHIP_TRANSFORMATION,
                },
            )
        )
    relations.sort(key=lambda item: (item.subject, item.predicate, item.object))

    return _release(
        key="eurovoc-microthesauri-4.24",
        resource_id="eurovoc",
        source_module="refspec.registry.eurovoc_thesaurus",
        scope="publisherRelease",
        issued=EUROVOC_RELEASE_4_24.issued,
        source_release_iri=(
            "http://publications.europa.eu/resource/dataset/"
            "eurovoc/20260708-0#thesaurus-microthesauri"
        ),
        atlas_release_iri="urn:ref:atlas-release:3:eurovoc-microthesauri:4.24",
        scheme_iri="urn:ref:atlas-resource-scheme:eurovoc:microthesauri",
        source=archive,
        inputs=(archive, metadata),
        source_release_digest=canonical_digest(
            {
                "archiveDigest": archive.sha256,
                "memberDigest": EUROVOC_RELEASE_4_24.expected_member_sha256,
                "metadataDigest": metadata.sha256,
                "memberPartition": "microthesauri",
                "version": EUROVOC_RELEASE_4_24.version,
            }
        ),
        resources=resources,
        relations=tuple(relations),
        metadata={
            "completePublisherRelease": True,
            "licenseIri": EUROVOC_RELEASE_4_24.license_iri,
            "memberPartition": "microthesauri",
            "publisherConceptCount": len(resources),
            "sourceArchiveDigest": archive.sha256,
            "sourceMemberDigest": EUROVOC_RELEASE_4_24.expected_member_sha256,
            "sourceMetadataDigest": metadata.sha256,
            "thesaurusVersion": parsed.thesaurus_version,
        },
    )


def load_eurovoc_microthesauri_4_24_release(
    source_root: Path = DEFAULT_SOURCE_ROOT,
) -> RegistryRelease:
    """Load the EuroVoc 4.24 microthesauri organization release.

    Reads the same pinned archive and metadata ``load_eurovoc_4_24_releases``
    reads, independently of it: unlike ``eurovoc-4.24``/
    ``eurovoc-domains-4.24``, this release has no claim-input replay path,
    so it is always built from the raw pinned RDF.
    """

    archive = _input_pin(
        source_root,
        filename="eurovoc-4.24-skos-core.zip",
        sha256=EUROVOC_RELEASE_4_24.expected_sha256,
        byte_length=EUROVOC_RELEASE_4_24.expected_byte_length,
        source_iri=EUROVOC_RELEASE_4_24.source_url,
    )
    metadata_source = EUROVOC_RELEASE_4_24.metadata_source
    if metadata_source is None:
        raise ValueError("EuroVoc 4.24 has no pinned publisher metadata")
    metadata = _input_pin(
        source_root,
        filename="eurovoc-4.24-metadata.ttl",
        sha256=metadata_source.expected_sha256,
        byte_length=metadata_source.expected_byte_length,
        source_iri=metadata_source.source_url,
    )
    with tempfile.TemporaryDirectory(prefix="refspec-eurovoc-microthesauri-4.24-") as directory:
        acquired = acquire_eurovoc_release(
            EUROVOC_RELEASE_4_24,
            Path(directory),
            source_path=archive.path,
            metadata_path=metadata.path,
        )
        parsed = parse_acquired_eurovoc_release(acquired)
    return _normalize_eurovoc_microthesauri(parsed, archive, metadata)


def _claim_release_input_pin(
    view: RegistryClaimReleaseView,
    filename: str,
) -> RegistryInputPin:
    """Restore the established Atlas logical pin for one verified raw member."""

    matching = [
        row
        for row in cast(Sequence[Mapping[str, Any]], view.manifest["rawInputs"])
        if Path(cast(str, row["path"])).name == filename
    ]
    if len(matching) != 1:
        raise ValueError(
            f"EuroVoc claim release must contain one raw input named {filename}"
        )
    row = matching[0]
    return RegistryInputPin(
        path=view.root / cast(str, row["path"]),
        logical_path=f"refspec/output/registry-real-data-sources/{filename}",
        sha256=cast(str, row["sha256"]),
        byte_length=cast(int, row["byteLength"]),
        source_iri=cast(str, row["sourceLocator"]),
    )


def _open_eurovoc_4_24_claim_release(
    input_: AtlasRegistryClaimInput,
) -> tuple[RegistryClaimReleaseView, RegistryInputPin, RegistryInputPin]:
    """Open the exact EuroVoc bundle and restore its established input pins."""

    view = input_.open()
    if (
        view.manifest["releaseKey"] != "eurovoc-4.24"
        or view.manifest["issued"] != EUROVOC_RELEASE_4_24.issued
    ):
        raise ValueError("EuroVoc requires the EuroVoc 4.24 claim release")
    archive = _claim_release_input_pin(view, "eurovoc-4.24-skos-core.zip")
    metadata = _claim_release_input_pin(view, "eurovoc-4.24-metadata.ttl")
    metadata_source = EUROVOC_RELEASE_4_24.metadata_source
    if metadata_source is None:
        raise ValueError("EuroVoc 4.24 has no pinned publisher metadata")
    if (
        archive.sha256 != EUROVOC_RELEASE_4_24.expected_sha256
        or archive.byte_length != EUROVOC_RELEASE_4_24.expected_byte_length
        or archive.source_iri != EUROVOC_RELEASE_4_24.source_url
        or metadata.sha256 != metadata_source.expected_sha256
        or metadata.byte_length != metadata_source.expected_byte_length
        or metadata.source_iri != metadata_source.source_url
    ):
        raise ValueError("EuroVoc claim release raw pins differ from release 4.24")
    manifest_metadata = cast(Mapping[str, Any], view.manifest["metadata"])
    expected_metadata = {
        "attribution": EUROVOC_RELEASE_4_24.attribution,
        "licenseIri": EUROVOC_RELEASE_4_24.license_iri,
        "publisher": EUROVOC_RELEASE_4_24.publisher,
        "version": EUROVOC_RELEASE_4_24.version,
    }
    if any(
        manifest_metadata.get(key) != value
        for key, value in expected_metadata.items()
    ):
        raise ValueError("EuroVoc claim release metadata differs from release 4.24")
    return view, archive, metadata


def _eurovoc_claim_resource_rules(
    *,
    member_predicate: str,
    member_object_iri: str,
    resource_kind: str,
    excluded_member_claims: Collection[tuple[str, str]] = (),
) -> RegistryClaimResourceRules:
    return RegistryClaimResourceRules(
        member_predicate=member_predicate,
        member_object_iri=member_object_iri,
        resource_kind=resource_kind,
        label_roles={
            "http://www.w3.org/2004/02/skos/core#altLabel": "alternate",
            "http://www.w3.org/2004/02/skos/core#hiddenLabel": "hidden",
            "http://www.w3.org/2004/02/skos/core#prefLabel": "preferred",
        },
        definition_predicates={_SKOS_DEFINITION},
        excluded_member_claims=excluded_member_claims,
        note_predicates={_SKOS_SCOPE_NOTE},
        notation_predicates={"http://www.w3.org/2004/02/skos/core#notation"},
        native_iri_predicates={
            "schemeIris": "http://www.w3.org/2004/02/skos/core#inScheme",
            "topConceptOfIris": (
                "http://www.w3.org/2004/02/skos/core#topConceptOf"
            ),
        },
        common_native_payload={
            "attribution": EUROVOC_RELEASE_4_24.attribution,
            "licenseIri": EUROVOC_RELEASE_4_24.license_iri,
            "publisher": EUROVOC_RELEASE_4_24.publisher,
            "releaseVersion": EUROVOC_RELEASE_4_24.version,
        },
        strip_label_whitespace=True,
    )


def _eurovoc_claim_release_digest(
    archive: RegistryInputPin,
    metadata: RegistryInputPin,
    member_partition: str,
) -> str:
    return canonical_digest(
        {
            "archiveDigest": archive.sha256,
            "memberDigest": EUROVOC_RELEASE_4_24.expected_member_sha256,
            "metadataDigest": metadata.sha256,
            "memberPartition": member_partition,
            "version": EUROVOC_RELEASE_4_24.version,
        }
    )


def _eurovoc_domain_release_from_claims(
    view: RegistryClaimReleaseView,
    archive: RegistryInputPin,
    metadata: RegistryInputPin,
) -> RegistryRelease:
    """Build the EuroVoc domains view from an already verified claim release."""

    resources = registry_resources_from_claim_release(
        view,
        _eurovoc_claim_resource_rules(
            member_predicate="http://www.w3.org/2004/02/skos/core#inScheme",
            member_object_iri="http://eurovoc.europa.eu/domains",
            resource_kind="Domain",
        ),
    )
    source_digests = {resource.source_digest for resource in resources}
    if source_digests != {EUROVOC_RELEASE_4_24.expected_member_sha256}:
        raise ValueError("EuroVoc domain claims do not use the pinned RDF member")
    return _release(
        key="eurovoc-domains-4.24",
        resource_id="eurovoc",
        source_module="refspec.registry.eurovoc_thesaurus",
        scope="publisherRelease",
        issued=EUROVOC_RELEASE_4_24.issued,
        source_release_iri=(
            "http://publications.europa.eu/resource/dataset/"
            "eurovoc/20260708-0#domains"
        ),
        atlas_release_iri="urn:ref:atlas-release:3:eurovoc-domains:4.24",
        scheme_iri="urn:ref:atlas-resource-scheme:eurovoc:domains",
        source=archive,
        inputs=(archive, metadata),
        source_release_digest=_eurovoc_claim_release_digest(
            archive,
            metadata,
            "domains",
        ),
        resources=resources,
        dropped_label_count=_EUROVOC_DOMAIN_OMITTED_NON_ENGLISH_LABEL_COUNT,
        metadata={
            "completePublisherRelease": True,
            "licenseIri": EUROVOC_RELEASE_4_24.license_iri,
            "memberPartition": "domains",
            "publisherConceptCount": len(resources),
            "sourceArchiveDigest": archive.sha256,
            "sourceMemberDigest": EUROVOC_RELEASE_4_24.expected_member_sha256,
            "sourceMetadataDigest": metadata.sha256,
            "thesaurusVersion": EUROVOC_RELEASE_4_24.version,
        },
    )


def _eurovoc_concept_release_from_claims(
    view: RegistryClaimReleaseView,
    archive: RegistryInputPin,
    metadata: RegistryInputPin,
) -> RegistryRelease:
    """Build the main EuroVoc view from an already verified claim release."""

    resources = registry_resources_from_claim_release(
        view,
        _eurovoc_claim_resource_rules(
            member_predicate=(
                "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"
            ),
            member_object_iri=(
                "http://www.w3.org/2004/02/skos/core#Concept"
            ),
            resource_kind="ThesaurusConcept",
            excluded_member_claims={
                (
                    "http://www.w3.org/2004/02/skos/core#inScheme",
                    "http://eurovoc.europa.eu/domains",
                )
            },
        ),
    )
    source_digests = {resource.source_digest for resource in resources}
    if source_digests != {EUROVOC_RELEASE_4_24.expected_member_sha256}:
        raise ValueError("EuroVoc concept claims do not use the pinned RDF member")
    relations = registry_relations_from_claim_release(
        view,
        member_iris={resource.iri for resource in resources},
        predicate_map={
            _SKOS_BROADER: _SKOS_BROADER,
            _SKOS_NARROWER: _SKOS_NARROWER,
            _SKOS_RELATED: _SKOS_RELATED,
        },
    )
    return _release(
        key="eurovoc-4.24",
        resource_id="eurovoc",
        source_module="refspec.registry.eurovoc_thesaurus",
        scope="publisherRelease",
        issued=EUROVOC_RELEASE_4_24.issued,
        source_release_iri=(
            "http://publications.europa.eu/resource/dataset/"
            "eurovoc/20260708-0#thesaurus-concepts"
        ),
        atlas_release_iri="urn:ref:atlas-release:3:eurovoc:4.24",
        scheme_iri="urn:ref:atlas-resource-scheme:eurovoc",
        source=archive,
        inputs=(archive, metadata),
        source_release_digest=_eurovoc_claim_release_digest(
            archive,
            metadata,
            "thesaurusConcepts",
        ),
        resources=resources,
        relations=relations,
        dropped_label_count=_EUROVOC_CONCEPT_OMITTED_NON_ENGLISH_LABEL_COUNT,
        metadata={
            "completePublisherRelease": True,
            "licenseIri": EUROVOC_RELEASE_4_24.license_iri,
            "memberPartition": "thesaurusConcepts",
            "publisherConceptCount": len(resources),
            "sourceArchiveDigest": archive.sha256,
            "sourceMemberDigest": EUROVOC_RELEASE_4_24.expected_member_sha256,
            "sourceMetadataDigest": metadata.sha256,
            "thesaurusVersion": EUROVOC_RELEASE_4_24.version,
        },
    )


def load_eurovoc_4_24_domain_release_from_claims(
    input_: AtlasRegistryClaimInput,
) -> RegistryRelease:
    """Build the EuroVoc domains compatibility view without its source parser."""

    view, archive, metadata = _open_eurovoc_4_24_claim_release(input_)
    return _eurovoc_domain_release_from_claims(view, archive, metadata)


def load_eurovoc_4_24_releases_from_claims(
    input_: AtlasRegistryClaimInput,
) -> tuple[RegistryRelease, RegistryRelease]:
    """Build both EuroVoc compatibility views without its source parser."""

    view, archive, metadata = _open_eurovoc_4_24_claim_release(input_)
    return (
        _eurovoc_concept_release_from_claims(view, archive, metadata),
        _eurovoc_domain_release_from_claims(view, archive, metadata),
    )


def load_eurovoc_4_24_releases(
    source_root: Path = DEFAULT_SOURCE_ROOT,
    *,
    claim_input: AtlasRegistryClaimInput | None = None,
) -> tuple[RegistryRelease, RegistryRelease]:
    """Load the complete pinned English EuroVoc 4.24 knowledge base."""

    if claim_input is not None:
        return load_eurovoc_4_24_releases_from_claims(claim_input)

    archive = _input_pin(
        source_root,
        filename="eurovoc-4.24-skos-core.zip",
        sha256=EUROVOC_RELEASE_4_24.expected_sha256,
        byte_length=EUROVOC_RELEASE_4_24.expected_byte_length,
        source_iri=EUROVOC_RELEASE_4_24.source_url,
    )
    metadata_source = EUROVOC_RELEASE_4_24.metadata_source
    if metadata_source is None:
        raise ValueError("EuroVoc 4.24 has no pinned publisher metadata")
    metadata = _input_pin(
        source_root,
        filename="eurovoc-4.24-metadata.ttl",
        sha256=metadata_source.expected_sha256,
        byte_length=metadata_source.expected_byte_length,
        source_iri=metadata_source.source_url,
    )
    with tempfile.TemporaryDirectory(prefix="refspec-eurovoc-4.24-") as directory:
        acquired = acquire_eurovoc_release(
            EUROVOC_RELEASE_4_24,
            Path(directory),
            source_path=archive.path,
            metadata_path=metadata.path,
        )
        parsed = parse_acquired_eurovoc_release(acquired)
    return _normalize_eurovoc(parsed, archive, metadata)


def _gemet_theme_labels(
    parsed: GemetVocabulary,
    theme_iris: Collection[str],
) -> dict[str, list[RegistryLabel]]:
    """Theme rdfs:label/acronymLabel take their own path, not the SKOS-role
    helpers above: unlike concept and Group/SuperGroup skos:prefLabel, these
    are not SKOS label roles, so SKOS S13 preferred/alternate precedence
    does not apply. English-only, per this module's house policy; en/en-US
    exact-duplicate text collapses within each predicate (never across
    rdfs:label vs acronymLabel, which are always kept as two distinct
    labels when both are present). acronymLabel becomes an "alternate"
    label -- GEMET's own predicate name calls it a label, and it is an
    alternate name for the Theme, not a classification code -- never
    promoted to "preferred" and never dropped."""

    by_subject_predicate: dict[tuple[str, str], dict[str, str]] = defaultdict(dict)
    for row in parsed.organization_metadata_literals:
        if row.subject_iri not in theme_iris:
            continue
        if row.property_iri not in (GEMET_DISPLAY_LABEL, GEMET_ACRONYM_LABEL):
            continue
        if not is_english_language_tag(row.value.language_tag):
            continue
        by_subject_predicate[(row.subject_iri, row.property_iri)][row.value.language_tag] = row.value.lexical_form

    labels: dict[str, list[RegistryLabel]] = defaultdict(list)
    for (subject_iri, predicate_iri), by_language in by_subject_predicate.items():
        role: LabelRole = "preferred" if predicate_iri == GEMET_DISPLAY_LABEL else "alternate"
        for value in sorted(set(by_language.values())):
            labels[subject_iri].append(
                RegistryLabel(value=value, role=role, source_path=f"{subject_iri}::{predicate_iri}")
            )
    return labels


def _normalize_gemet(parsed: GemetVocabulary, source: RegistryInputPin) -> RegistryRelease:
    concept_iris = {concept.concept_iri for concept in parsed.concepts}
    group_iris = {item.resource_iri for item in parsed.organization_resources if item.kind == "group"}
    super_group_iris = {item.resource_iri for item in parsed.organization_resources if item.kind == "superGroup"}
    theme_iris = {item.resource_iri for item in parsed.organization_resources if item.kind == "theme"}
    organization_by_iri = {item.resource_iri: item for item in parsed.organization_resources}
    # Group/SuperGroup join the same skos:prefLabel/label-role pipeline as
    # concepts below; Theme does not (see _gemet_theme_labels) and so is
    # deliberately excluded from this member_iris set.
    member_iris = concept_iris | group_iris | super_group_iris
    (
        labels,
        dropped,
        english_family_variant_labels,
        english_family_duplicates,
        english_family_variant_synonyms,
    ) = _normalize_english_label_candidates(
        (
            (
                row.subject_iri,
                row.value.language_tag,
                row.value.lexical_form,
                row.role,
                f"{row.subject_iri}::{row.property_iri}",
            )
            for row in (*parsed.labels, *parsed.organization_labels)
        ),
        member_iris,
    )
    theme_labels = _gemet_theme_labels(parsed, theme_iris)
    notes: dict[str, list[Any]] = defaultdict(list)
    for row in parsed.notes:
        if row.subject_iri in concept_iris and is_english_language_tag(row.value.language_tag):
            notes[row.subject_iri].append(row)
    notations: dict[str, list[str]] = defaultdict(list)
    for row in parsed.notations:
        if row.subject_iri in concept_iris and is_english_language_tag(row.value.language_tag):
            notations[row.subject_iri].append(row.value.lexical_form)
    metadata: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in parsed.metadata_literals:
        if row.subject_iri in concept_iris and (
            row.value.language_tag is None
            or is_english_language_tag(row.value.language_tag)
        ):
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

    # GEMET's second, publisher-asserted organizing layer: Group, SuperGroup,
    # and Theme skos:Collections. E1 status (GEMET owns every endpoint), so
    # this is native relations under an admitted predicate, never a derived
    # rule. The two named meta-collections (groupCollection/
    # superGroupCollection) and gemet-schema:subGroupOf are deliberately not
    # emitted -- see the metadata block below for what was observed and why.
    for kind, iris in (("group", group_iris), ("superGroup", super_group_iris)):
        for resource_iri in sorted(iris):
            organization_resource = organization_by_iri[resource_iri]
            normalized_labels, label_role_conflicts = _normalize_skos_label_roles(
                labels[resource_iri]
            )
            label_role_conflict_count += len(label_role_conflicts)
            native_payload = {
                "organizationKind": kind,
                "publisherResourceIri": resource_iri,
                "typeIris": list(organization_resource.type_iris),
                "schemeIris": list(organization_resource.scheme_iris),
            }
            if label_role_conflicts:
                native_payload["labelRoleNormalization"] = {
                    "conflicts": list(label_role_conflicts),
                    "rule": "skos-s13-preferred-alternate-hidden-precedence-v1",
                }
            resources.append(
                RegistryResource(
                    iri=resource_iri,
                    labels=normalized_labels,
                    native_payload=native_payload,
                    source_locator=resource_iri,
                    source_digest=source.sha256,
                )
            )
    for resource_iri in sorted(theme_iris):
        organization_resource = organization_by_iri[resource_iri]
        resources.append(
            RegistryResource(
                iri=resource_iri,
                labels=theme_labels[resource_iri],
                native_payload={
                    "organizationKind": "theme",
                    "publisherResourceIri": resource_iri,
                    "typeIris": list(organization_resource.type_iris),
                    "schemeIris": list(organization_resource.scheme_iris),
                    "labelPredicates": {
                        "preferred": GEMET_DISPLAY_LABEL,
                        "alternate": GEMET_ACRONYM_LABEL,
                    },
                },
                source_locator=resource_iri,
                source_digest=source.sha256,
            )
        )

    all_member_iris = member_iris | theme_iris
    organization_relations = _direct_relations(
        parsed.organization_membership_relations,
        all_member_iris,
        predicate_map=_GEMET_ORGANIZATION_MEMBERSHIP_PREDICATES,
    )
    relations = (
        *_direct_relations(parsed.semantic_relations, member_iris),
        *organization_relations,
    )

    subgroup_of_count = len(parsed.organization_hierarchy_relations)
    meta_collection_iris = {GEMET_GROUP_COLLECTION_IRI, GEMET_SUPER_GROUP_COLLECTION_IRI} & set(organization_by_iri)
    meta_collection_membership_count = sum(
        1 for row in parsed.organization_membership_relations if row.subject_iri in meta_collection_iris
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
        relations=relations,
        dropped_label_count=dropped,
        metadata={
            "englishFamilyDuplicateLabelCount": english_family_duplicates,
            "englishFamilyVariantLabelCount": english_family_variant_labels,
            "englishFamilyVariantSynonymCount": english_family_variant_synonyms,
            "labelRoleConflictCount": label_role_conflict_count,
            "labelRoleConflictRule": (
                "skos-s13-preferred-alternate-hidden-precedence-v1"
            ),
            "organizationGroupCount": len(group_iris),
            "organizationSuperGroupCount": len(super_group_iris),
            "organizationThemeCount": len(theme_iris),
            "organizationMembershipPredicateAdoption": {
                "adoptedBy": "RefSpecOperator",
                "fromPredicateIri": GEMET_MEMBER_PREDICATE_IRI,
                "toPredicateIri": _ATLAS_HAS_SCHEME_MEMBER,
                "reason": (
                    "skos:member is not an admitted subject-ring NativeRelationAssertion "
                    "predicate; atlas:hasSchemeMember is the admitted predicate for a "
                    "grouping/scheme resource's membership toward its member concept, and "
                    "its assertion direction matches skos:member's exactly. This is a "
                    "same-publisher, same-release predicate translation (GEMET owns "
                    "Group, SuperGroup, Theme, and Concept alike), not a cross-vocabulary "
                    "adjudicated claim, so it is recorded here rather than through "
                    "RegistryMapping/RegistryMappingEvidence."
                ),
                "emittedRelationCount": len(organization_relations),
            },
            "organizationHierarchyObservedNotEmitted": {
                "predicateIri": GEMET_SUB_GROUP_OF_PREDICATE_IRI,
                "observedCount": subgroup_of_count,
                "reason": (
                    "gemet-schema:subGroupOf is exactly reciprocal with the SuperGroup's own "
                    "skos:member (0 mismatches over all 32 pairs in the pinned release); it "
                    "carries no information the emitted superGroup->group "
                    "atlas:hasSchemeMember relation lacks, and subGroupOf is not an admitted "
                    "subject-ring predicate."
                ),
            },
            "organizationMetaCollectionsObservedNotEmitted": {
                "resourceIris": sorted(meta_collection_iris),
                "observedMembershipCount": meta_collection_membership_count,
                "reason": (
                    "groupCollection/superGroupCollection carry only an enumeration "
                    "rdfs:label and skos:member listing every Group/SuperGroup; that "
                    "closure is already fully recoverable from the emitted Group/SuperGroup "
                    "resources and their superGroup->group atlas:hasSchemeMember relations, "
                    "so the two meta-collections are not promoted to resources."
                ),
            },
            "organizationThemeAcronymLanguageCoverage": {
                "rdfsLabelLanguageCount": 36,
                "acronymLabelLanguageCount": 21,
                "languagesWithLabelButNoAcronym": [
                    "ar", "az", "ca", "cs", "ga", "hr", "hy", "is",
                    "ka", "lt", "lv", "mt", "ro", "tr", "uk",
                ],
            },
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
    (
        labels,
        dropped,
        _variants,
        _duplicates,
        _synonyms,
    ) = _normalize_english_label_candidates(
        (
            (
                row.subject_iri,
                row.value.language_tag,
                row.value.lexical_form,
                row.role,
                f"{row.subject_iri}::{row.property_iri}",
            )
            for row in parsed.labels
        ),
        member_iris,
        untagged_is_english=True,
    )
    metadata: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in parsed.metadata_literals:
        if row.subject_iri in member_iris and (
            row.value.language_tag is None
            or is_english_language_tag(row.value.language_tag)
        ):
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


MESH_DESCRIPTORS_SCHEME_IRI = "urn:ref:atlas-resource-scheme:mesh-descriptors"


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
            # The DescriptorUI is deliberately NOT emitted into `identifiers`.
            # It was, briefly, pointed at MESH_DESCRIPTORS_SCHEME_IRI -- and the
            # producer refused the build, correctly. That IRI is MeSH's concept
            # scheme, not an identifier authority, and no amount of registering
            # would fix the modelling: an Atlas identifier names something the
            # scheme does not itself define, the way a CCN names a provider or
            # a GEOID names a geography. D000001 is the concept's own accession
            # number and is already the last segment of its own IRI, so a row
            # here would restate the subject's identity as a property of
            # itself. It stays in the IRI and in native_payload.
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
    load_eurovoc_microthesauri_4_24_release,
    load_federal_register_2025_release,
    load_gcmd_24_4_release,
    load_gemet_release,
    load_mesh_2026_release,
    load_nasa_thesaurus_release,
)

REGISTRY_VOCABULARY_RELEASE_KEYS = frozenset(EXPECTED_RESOURCE_COUNTS)


def load_all_registry_vocabulary_releases(
    source_root: Path = DEFAULT_SOURCE_ROOT,
    *,
    only_keys: Collection[str] | None = None,
    registry_claim_inputs: Mapping[str, AtlasRegistryClaimInput] | None = None,
) -> tuple[RegistryRelease, ...]:
    """Load selected complete cached vocabulary releases in stable key order."""

    requested = normalize_only_keys(
        only_keys,
        allowed_keys=REGISTRY_VOCABULARY_RELEASE_KEYS,
        loader_name="load_all_registry_vocabulary_releases",
    )
    individual_loaders = (
        ("doe-osti-semantic-thesaurus-2020", load_doe_osti_release),
        ("elsst-r6", load_elsst_r6_release),
        ("eurovoc-microthesauri-4.24", load_eurovoc_microthesauri_4_24_release),
        ("federal-register-thesaurus-2025", load_federal_register_2025_release),
        ("gcmd-science-keywords-24-4", load_gcmd_24_4_release),
        ("gemet-4.2.3", load_gemet_release),
        ("mesh-descriptors-2026", load_mesh_2026_release),
        ("nasa-thesaurus-skos", load_nasa_thesaurus_release),
    )
    releases: list[RegistryRelease] = []
    for key, loader in individual_loaders:
        group_keys = frozenset({key})
        if not wants_group(requested, group_keys):
            continue
        releases.extend(
            select_declared_group(
                (loader(source_root),),
                declared_keys=group_keys,
                requested_keys=requested,
                loader_name=loader.__name__,
            )
        )
    eurovoc_keys = frozenset({"eurovoc-4.24", "eurovoc-domains-4.24"})
    if wants_group(requested, eurovoc_keys):
        claim_inputs = (
            {} if registry_claim_inputs is None else registry_claim_inputs
        )
        eurovoc_claim_input = claim_inputs.get("eurovoc-4.24")
        if requested == frozenset({"eurovoc-domains-4.24"}) and (
            eurovoc_claim_input is not None
        ):
            releases.append(
                load_eurovoc_4_24_domain_release_from_claims(
                    eurovoc_claim_input
                )
            )
        else:
            releases.extend(
                select_declared_group(
                    load_eurovoc_4_24_releases(
                        source_root,
                        claim_input=eurovoc_claim_input,
                    ),
                    declared_keys=eurovoc_keys,
                    requested_keys=requested,
                    loader_name="load_eurovoc_4_24_releases",
                )
            )
    return tuple(sorted(releases, key=lambda release: release.key))


__all__ = [
    "DEFAULT_SOURCE_ROOT",
    "EXPECTED_LABEL_COUNTS",
    "EXPECTED_RELATION_COUNTS",
    "EXPECTED_RESOURCE_COUNTS",
    "MESH_2026_BYTE_LENGTH",
    "MESH_2026_SHA256",
    "MESH_2026_SOURCE_URL",
    "REGISTRY_VOCABULARY_LOADERS",
    "REGISTRY_VOCABULARY_RELEASE_KEYS",
    "load_all_registry_vocabulary_releases",
    "load_doe_osti_release",
    "load_elsst_r6_release",
    "load_eurovoc_4_24_domain_release_from_claims",
    "load_eurovoc_4_24_releases",
    "load_eurovoc_4_24_releases_from_claims",
    "load_eurovoc_microthesauri_4_24_release",
    "load_federal_register_2025_release",
    "load_gcmd_24_4_release",
    "load_gemet_release",
    "load_mesh_2026_release",
    "load_nasa_thesaurus_release",
]
