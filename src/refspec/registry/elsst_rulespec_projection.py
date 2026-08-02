"""Project exact ELSST releases through the Rulespec reference-resource seam.

ELSST's native SKOS distribution remains canonical.  This module does not
recast externally authored concepts as ``rkaf:RegisteredConcept`` records.
It preserves the exact source SKOS nodes, adds portable complete-membership
release manifests, and derives only lifecycle transitions proved by comparing
consecutive exact publisher releases.

A history is one or more editions in publication order.  Two is the case this
module was written for and it keeps its exact published identity; one is a
complete history that simply states no transition, because a transition is
derived by comparison and there is nothing to compare against.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass, replace
from typing import Any

from refspec.registry.elsst import (
    ADDITIONAL_CONTENT_NOTE_PREDICATE_IRI,
    BROADER_PREDICATE_IRI,
    DEPRECATED_PREDICATE_IRI,
    IDENTIFIER_PREDICATE_IRI,
    IS_REPLACED_BY_PREDICATE_IRI,
    IS_VERSION_OF_PREDICATE_IRI,
    ISSUED_PREDICATE_IRI,
    NARROWER_PREDICATE_IRI,
    NOTE_PREDICATE_IRIS,
    PRIOR_VERSION_PREDICATE_IRI,
    RELATED_PREDICATE_IRI,
    REPLACES_PREDICATE_IRI,
    ElsstLabelExpression,
    ElsstLiteral,
    ElsstNote,
    ElsstReleaseComparison,
    ElsstVocabulary,
    compare_elsst_releases,
)
from refspec.registry.elsst_acquisition import (
    ELSST_R5,
    ELSST_R6,
    ElsstReleaseSource,
)
from refspec.release_graph import (
    RulespecValidatorPin,
    compute_reference_resource_release_digest,
    validate_rulespec_graph,
)
from refspec.vocabulary import require_language_tag

ELSST_RULESPEC_GRAPH_IRI = "urn:ref:elsst:rulespec-graph"
ELSST_PROJECTION_ACTIVITY_IRI = "urn:ref:elsst:activity:rulespec-projection"
ELSST_DATE_MATERIALIZATION_POLICY_IRI = (
    "urn:ref:elsst:policy:source-date-start-of-day-utc"
)
ELSST_GENERAL_SUBJECT_FACET_IRI = "urn:ref:facet:general-subject"
XSD_BOOLEAN_IRI = "http://www.w3.org/2001/XMLSchema#boolean"
DCTERMS_ISSUED_IRI = "http://purl.org/dc/terms/issued"

_DATE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")
_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")

_NOTE_PROPERTY_NAMES = {
    **{predicate: f"skos:{predicate.rsplit('#', 1)[-1]}" for predicate in NOTE_PREDICATE_IRIS},
    ADDITIONAL_CONTENT_NOTE_PREDICATE_IRI: ("xkos:additionalContentNote"),
}
_RELATION_PROPERTY_NAMES = {
    BROADER_PREDICATE_IRI: "skos:broader",
    NARROWER_PREDICATE_IRI: "skos:narrower",
    RELATED_PREDICATE_IRI: "skos:related",
}
_VERSION_PROPERTY_NAMES = {
    IS_VERSION_OF_PREDICATE_IRI: "dcterms:isVersionOf",
    PRIOR_VERSION_PREDICATE_IRI: "owl:priorVersion",
}
_REPLACEMENT_PROPERTY_NAMES = {
    IS_REPLACED_BY_PREDICATE_IRI: "dcterms:isReplacedBy",
    REPLACES_PREDICATE_IRI: "dcterms:replaces",
}


class ElsstRulespecProjectionError(ValueError):
    """An exact ELSST source fact cannot be projected without guessing."""


@dataclass(frozen=True, slots=True)
class ElsstLifecycleTransition:
    """One release transition derived from exact source identity assertions."""

    event_iri: str
    operation: str
    source_status_concept_iri: str
    predecessor_concept_iris: tuple[str, ...]
    successor_concept_iris: tuple[str, ...]
    predecessor_release_iri: str
    successor_release_iri: str | None


@dataclass(frozen=True, slots=True)
class ElsstRulespecProjection:
    """A source-native graph plus its explicit projection evidence.

    ``release_iris``, ``distribution_iris`` and ``source_date_literals`` are
    parallel and in publication order, oldest first.  The last entry is the
    edition a deployment selects.
    """

    graph: dict[str, Any]
    release_iris: tuple[str, ...]
    distribution_iris: tuple[str, ...]
    lifecycle_transitions: tuple[ElsstLifecycleTransition, ...]
    source_date_literals: tuple[str, ...]
    date_materialization_policy: str
    rulespec_graph_iri: str
    projection_activity_iri: str
    identifier_scope: str
    release_digests: tuple[tuple[str, str], ...] = ()


def _sha256_identifier(prefix: str, value: object) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return f"{prefix}:{hashlib.sha256(payload).hexdigest()}"


def _source_identity(
    vocabulary: ElsstVocabulary,
    release: ElsstReleaseSource,
) -> dict[str, Any]:
    return {
        "descriptor": asdict(release),
        "observedDigest": vocabulary.source_sha256,
        "observedByteLength": vocabulary.source_bytes,
    }


def _projection_identifier_scope(
    *,
    vocabularies: Sequence[ElsstVocabulary],
    releases: Sequence[ElsstReleaseSource],
    validator: RulespecValidatorPin,
    identifier_scope: str | None,
) -> str:
    if identifier_scope is not None:
        if re.fullmatch(r"[0-9a-f]{64}", identifier_scope) is None:
            raise ElsstRulespecProjectionError(
                "identifier_scope must be 64 lowercase hexadecimal characters"
            )
        return identifier_scope
    identities = [
        _source_identity(vocabulary, release)
        for vocabulary, release in zip(vocabularies, releases, strict=True)
    ]
    validator_identity = {
        "identity": validator.identity,
        "sourceRevision": validator.source_revision,
        "evidenceRevision": validator.evidence_revision,
        "componentId": validator.component_id,
        "componentDigest": validator.component_digest,
    }
    if len(identities) == 2:
        # The published two-edition preimage, kept verbatim. Every committed
        # digest that names the R5/R6 bundle is derived from these exact keys,
        # so an ordered history must not restate the pair it already named.
        preimage: dict[str, Any] = {
            "projectionVersion": "elsst-source-native-v2",
            "previousSource": identities[0],
            "currentSource": identities[1],
            "validator": validator_identity,
        }
    else:
        preimage = {
            "projectionVersion": "elsst-source-native-history-v1",
            "sources": identities,
            "validator": validator_identity,
        }
    digest = _sha256_identifier("sha256", preimage)
    return digest.removeprefix("sha256:")


def _scoped_identifier(base: str, identifier_scope: str) -> str:
    return f"{base}:{identifier_scope}"


def _rulespec_context(
    validator: RulespecValidatorPin,
) -> dict[str, Any]:
    context_path = validator.working_directory / "context" / "rkaf-context.jsonld"
    try:
        document = json.loads(context_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ElsstRulespecProjectionError(f"cannot read pinned Rulespec JSON-LD context: {error}") from error
    context = document.get("@context") if isinstance(document, dict) else None
    if not isinstance(context, dict):
        raise ElsstRulespecProjectionError("pinned Rulespec context has no @context object")
    projected = copy.deepcopy(context)
    # These native ELSST properties are not Rulespec-owned terms.  Their
    # coercions preserve exact source IRIs and literals while the pinned
    # Rulespec context continues to govern every rkaf:* record.
    projected.update(
        {
            "owl": "http://www.w3.org/2002/07/owl#",
            "xkos": "http://rdf-vocabulary.ddialliance.org/xkos#",
            "owl:priorVersion": {
                "@id": "http://www.w3.org/2002/07/owl#priorVersion",
                "@type": "@id",
                "@container": "@set",
            },
            "owl:deprecated": {
                "@id": "http://www.w3.org/2002/07/owl#deprecated",
                "@type": "xsd:boolean",
            },
            "dcterms:isReplacedBy": {
                "@id": "http://purl.org/dc/terms/isReplacedBy",
                "@type": "@id",
                "@container": "@set",
            },
            "dcterms:replaces": {
                "@id": "http://purl.org/dc/terms/replaces",
                "@type": "@id",
                "@container": "@set",
            },
            "skos:topConceptOf": {
                "@id": "http://www.w3.org/2004/02/skos/core#topConceptOf",
                "@type": "@id",
                "@container": "@set",
            },
            "xkos:additionalContentNote": {
                "@id": ("http://rdf-vocabulary.ddialliance.org/xkos#additionalContentNote"),
                "@container": "@language",
            },
        }
    )
    return projected


def _language_map(
    values: Iterable[ElsstLiteral],
    *,
    field: str,
    preferred: bool,
) -> dict[str, Any]:
    by_language: dict[str, list[str]] = defaultdict(list)
    for value in values:
        language = value.language_tag
        if language is None:
            raise ElsstRulespecProjectionError(f"{field} contains an untagged source literal")
        try:
            require_language_tag(language, field)
        except ValueError as error:
            raise ElsstRulespecProjectionError(str(error)) from error
        if value.datatype_iri is not None:
            raise ElsstRulespecProjectionError(f"{field} mixes a language tag with a datatype")
        by_language[language].append(value.lexical_form)
    result: dict[str, Any] = {}
    for language, literals in sorted(by_language.items()):
        ordered = sorted(literals)
        if preferred:
            if len(ordered) != 1:
                raise ElsstRulespecProjectionError(
                    f"{field} has {len(ordered)} preferred labels for language {language}"
                )
            result[language] = ordered[0]
        else:
            result[language] = ordered
    if not result:
        raise ElsstRulespecProjectionError(f"{field} is empty")
    return result


def _language_tagged_value_objects(
    values: Iterable[ElsstLiteral],
    *,
    field: str,
) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    for value in values:
        language = value.language_tag
        if language is None:
            raise ElsstRulespecProjectionError(
                f"{field} contains an untagged source literal"
            )
        try:
            require_language_tag(language, field)
        except ValueError as error:
            raise ElsstRulespecProjectionError(str(error)) from error
        if value.datatype_iri is not None:
            raise ElsstRulespecProjectionError(
                f"{field} mixes a language tag with a datatype"
            )
        result.append(
            {
                "@value": value.lexical_form,
                "@language": language,
            }
        )
    return sorted(
        result,
        key=lambda item: (item["@language"], item["@value"]),
    )


def _date_literal(
    vocabulary: ElsstVocabulary,
    *,
    scheme_iri: str,
) -> str:
    values = {
        item.value.lexical_form
        for item in vocabulary.metadata_literals
        if item.subject_iri == scheme_iri and item.property_iri == ISSUED_PREDICATE_IRI
    }
    if len(values) != 1:
        raise ElsstRulespecProjectionError(f"{scheme_iri} must have exactly one source dcterms:issued date")
    value = values.pop()
    if _DATE.fullmatch(value) is None:
        raise ElsstRulespecProjectionError(f"{scheme_iri} source issue value {value!r} is not a date")
    return value


def _stable_resource_iri(
    vocabulary: ElsstVocabulary,
    *,
    scheme_iri: str,
) -> str:
    values = {
        item.object_iri
        for item in vocabulary.version_relations
        if item.subject_iri == scheme_iri and item.predicate_iri == IS_VERSION_OF_PREDICATE_IRI
    }
    if len(values) != 1:
        raise ElsstRulespecProjectionError(f"{scheme_iri} must identify exactly one stable source resource")
    return values.pop()


def _require_release_source(
    vocabulary: ElsstVocabulary,
    release: ElsstReleaseSource,
) -> None:
    if vocabulary.source_url != release.source_url:
        raise ElsstRulespecProjectionError(f"release {release.version} source URL does not match parsed bytes")
    if vocabulary.source_sha256 != release.expected_sha256:
        raise ElsstRulespecProjectionError(f"release {release.version} digest does not match parsed bytes")
    if vocabulary.source_bytes != release.expected_byte_length:
        raise ElsstRulespecProjectionError(f"release {release.version} byte length does not match parsed bytes")
    if release.concept_scheme_iri not in {item.scheme_iri for item in vocabulary.concept_schemes}:
        raise ElsstRulespecProjectionError(f"release {release.version} source scheme is absent")


def _labels_by_subject(
    vocabulary: ElsstVocabulary,
) -> dict[str, list[ElsstLabelExpression]]:
    result: dict[str, list[ElsstLabelExpression]] = defaultdict(list)
    for item in vocabulary.labels:
        result[item.subject_iri].append(item)
    return result


def _notes_by_subject(
    vocabulary: ElsstVocabulary,
) -> dict[str, list[ElsstNote]]:
    result: dict[str, list[ElsstNote]] = defaultdict(list)
    for item in vocabulary.notes:
        result[item.subject_iri].append(item)
    return result


def _native_text(
    *,
    subject_iri: str,
    labels: Mapping[str, list[ElsstLabelExpression]],
    notes: Mapping[str, list[ElsstNote]],
) -> dict[str, Any]:
    subject_labels = labels.get(subject_iri, [])
    by_role: dict[str, list[ElsstLiteral]] = defaultdict(list)
    for item in subject_labels:
        by_role[item.role].append(item.value)
    preferred = _language_map(
        by_role["preferred"],
        field=f"{subject_iri} skos:prefLabel",
        preferred=True,
    )
    node: dict[str, Any] = {"skos:prefLabel": preferred}
    for role, property_name in (
        ("alternate", "skos:altLabel"),
        ("hidden", "skos:hiddenLabel"),
    ):
        if by_role[role]:
            node[property_name] = _language_map(
                by_role[role],
                field=f"{subject_iri} {property_name}",
                preferred=False,
            )

    role_literals = {
        (
            item.role,
            item.value.language_tag.casefold() if item.value.language_tag is not None else "",
            item.value.lexical_form,
        )
        for item in subject_labels
    }
    for _role, language, literal in role_literals:
        roles = {
            role
            for role, candidate_language, candidate_literal in role_literals
            if candidate_language == language and candidate_literal == literal
        }
        if len(roles) > 1:
            raise ElsstRulespecProjectionError(
                f"{subject_iri} repeats {literal!r} across label roles for language {language}"
            )

    notes_by_property: dict[str, list[ElsstLiteral]] = defaultdict(list)
    for item in notes.get(subject_iri, []):
        notes_by_property[item.property_iri].append(item.value)
    for predicate_iri, values in sorted(notes_by_property.items()):
        try:
            property_name = _NOTE_PROPERTY_NAMES[predicate_iri]
        except KeyError as error:  # pragma: no cover - parser invariant
            raise ElsstRulespecProjectionError(f"unsupported parsed ELSST note property {predicate_iri}") from error
        node[property_name] = _language_map(
            values,
            field=f"{subject_iri} {property_name}",
            preferred=False,
        )
    return node


def _native_release_nodes(
    vocabulary: ElsstVocabulary,
    release: ElsstReleaseSource,
    *,
    identifier_scope: str,
) -> tuple[list[dict[str, Any]], str, str, str]:
    _require_release_source(vocabulary, release)
    concept_by_iri = {item.concept_iri: item for item in vocabulary.concepts}
    concept_iris = set(concept_by_iri)
    scheme_iri = release.concept_scheme_iri
    scheme = next(item for item in vocabulary.concept_schemes if item.scheme_iri == scheme_iri)
    labels = _labels_by_subject(vocabulary)
    notes = _notes_by_subject(vocabulary)

    relations_by_subject: dict[str, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
    for relation in vocabulary.semantic_relations:
        if relation.subject_iri not in concept_iris or relation.object_iri not in concept_iris:
            raise ElsstRulespecProjectionError(f"release {release.version} relation endpoint is not a member")
        subject_scheme = concept_by_iri[relation.subject_iri].scheme_iris
        object_scheme = concept_by_iri[relation.object_iri].scheme_iris
        if subject_scheme != (scheme_iri,) or object_scheme != (scheme_iri,):
            raise ElsstRulespecProjectionError(
                f"release {release.version} contains a cross-scheme SKOS semantic relation"
            )
        relations_by_subject[relation.subject_iri][_RELATION_PROPERTY_NAMES[relation.predicate_iri]].append(
            relation.object_iri
        )

    version_by_subject: dict[str, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
    for relation in vocabulary.version_relations:
        version_by_subject[relation.subject_iri][_VERSION_PROPERTY_NAMES[relation.predicate_iri]].append(
            relation.object_iri
        )

    replacement_by_subject: dict[str, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
    for relation in vocabulary.replacement_relations:
        replacement_by_subject[relation.subject_iri][_REPLACEMENT_PROPERTY_NAMES[relation.predicate_iri]].append(
            relation.object_iri
        )

    deprecation_by_subject: dict[str, list[ElsstLiteral]] = defaultdict(list)
    for assertion in vocabulary.deprecated_assertions:
        if assertion.predicate_iri != DEPRECATED_PREDICATE_IRI:
            raise ElsstRulespecProjectionError("parser returned an unexpected status predicate")
        deprecation_by_subject[assertion.subject_iri].append(assertion.value)

    notation_by_subject: dict[str, list[dict[str, str]]] = defaultdict(list)
    for notation in vocabulary.notations:
        datatype = notation.value.datatype_iri
        if datatype is None or notation.value.language_tag is not None:
            raise ElsstRulespecProjectionError(f"{notation.subject_iri} notation is not an exact typed literal")
        notation_by_subject[notation.subject_iri].append(
            {
                "@value": notation.value.lexical_form,
                "@type": datatype,
            }
        )

    scheme_node: dict[str, Any] = {
        "@id": scheme_iri,
        "@type": "skos:ConceptScheme",
        **_native_text(
            subject_iri=scheme_iri,
            labels=labels,
            notes=notes,
        ),
    }
    scheme_identifiers = _language_tagged_value_objects(
        (
            item.value
            for item in vocabulary.metadata_literals
            if item.subject_iri == scheme_iri
            and item.property_iri == IDENTIFIER_PREDICATE_IRI
        ),
        field=f"{scheme_iri} dcterms:identifier",
    )
    if scheme_identifiers:
        scheme_node["dcterms:identifier"] = scheme_identifiers
    if scheme.top_concept_iris:
        if not set(scheme.top_concept_iris) <= concept_iris:
            raise ElsstRulespecProjectionError(f"{scheme_iri} has a top concept outside its exact release")
        scheme_node["skos:hasTopConcept"] = sorted(scheme.top_concept_iris)
    for property_name, values in sorted(version_by_subject.get(scheme_iri, {}).items()):
        scheme_node[property_name] = sorted(values)

    concept_nodes: list[dict[str, Any]] = []
    for concept_iri in sorted(concept_iris):
        concept = concept_by_iri[concept_iri]
        if concept.scheme_iris != (scheme_iri,):
            raise ElsstRulespecProjectionError(f"{concept_iri} does not have exactly the selected source scheme")
        node: dict[str, Any] = {
            "@id": concept_iri,
            "@type": "skos:Concept",
            **_native_text(
                subject_iri=concept_iri,
                labels=labels,
                notes=notes,
            ),
            "skos:inScheme": scheme_iri,
        }
        if concept.top_concept_of_iris:
            if concept.top_concept_of_iris != (scheme_iri,):
                raise ElsstRulespecProjectionError(f"{concept_iri} has a foreign skos:topConceptOf target")
            node["skos:topConceptOf"] = [scheme_iri]
        for property_name, values in sorted(relations_by_subject.get(concept_iri, {}).items()):
            node[property_name] = sorted(values)
        for property_name, values in sorted(version_by_subject.get(concept_iri, {}).items()):
            node[property_name] = sorted(values)
        for property_name, values in sorted(replacement_by_subject.get(concept_iri, {}).items()):
            node[property_name] = sorted(values)
        if notation_by_subject.get(concept_iri):
            node["skos:notation"] = sorted(
                notation_by_subject[concept_iri],
                key=lambda item: (item["@type"], item["@value"]),
            )
        deprecated_values = deprecation_by_subject.get(concept_iri, [])
        if deprecated_values:
            if len(deprecated_values) != 1:
                raise ElsstRulespecProjectionError(f"{concept_iri} repeats owl:deprecated")
            deprecated = deprecated_values[0]
            if (
                deprecated.language_tag is not None
                or deprecated.datatype_iri != XSD_BOOLEAN_IRI
                or deprecated.lexical_form not in {
                    "true",
                    "1",
                    "false",
                    "0",
                }
            ):
                raise ElsstRulespecProjectionError(f"{concept_iri} has an unsupported deprecation literal")
            node["owl:deprecated"] = deprecated.lexical_form
        concept_nodes.append(node)

    source_date = _date_literal(vocabulary, scheme_iri=scheme_iri)
    scheme_node[DCTERMS_ISSUED_IRI] = {
        "@value": source_date,
        "@language": "en",
    }
    stable_resource_iri = _stable_resource_iri(
        vocabulary,
        scheme_iri=scheme_iri,
    )
    distribution_iri = _sha256_identifier(
        "urn:ref:elsst:distribution",
        {
            "identifierScope": identifier_scope,
            "releaseDescriptor": asdict(release),
            "sourceDigest": vocabulary.source_sha256,
            "sourceByteLength": vocabulary.source_bytes,
        },
    )
    distribution_node = {
        "@id": distribution_iri,
        "@type": "rkaf:Artifact",
        "rkaf:hasArtifactIdentifier": [release.source_url],
        "rkaf:artifactIdentifierScheme": ["rkaf:partner-defined"],
        "dcterms:format": "text/turtle",
        "rkaf:hasContentDigest": vocabulary.source_sha256,
    }
    release_node = {
        "@id": release.release_iri,
        "@type": "rkaf:ReferenceResourceRelease",
        "dcterms:isVersionOf": stable_resource_iri,
        "dcat:version": release.version,
        "dcterms:type": "skos:ConceptScheme",
        "rkaf:membershipMode": "rkaf:completeMembership",
        "prov:hadMember": sorted(concept_iris),
        "dcat:distribution": [distribution_iri],
        "rkaf:versionBasis": "rkaf:publisherAssigned",
    }
    return (
        [scheme_node, *concept_nodes, release_node, distribution_node],
        source_date,
        stable_resource_iri,
        distribution_iri,
    )


def _lifecycle_transitions(
    comparison: ElsstReleaseComparison,
    *,
    previous: ElsstVocabulary,
    current: ElsstVocabulary,
    previous_release: ElsstReleaseSource,
    current_release: ElsstReleaseSource,
    effective_date: str,
    registry_iri: str,
    identifier_scope: str,
) -> tuple[tuple[ElsstLifecycleTransition, dict[str, Any]], ...]:
    previous_members = {item.concept_iri for item in previous.concepts}
    current_members = {item.concept_iri for item in current.concepts}
    predecessor_by_current = {
        item.current_concept_iri: item.previous_concept_iri for item in comparison.retained_stable_identities
    }
    successors_by_status_subject: dict[str, list[str]] = defaultdict(list)
    for relation in comparison.replacement_pairs:
        successors_by_status_subject[relation.subject_iri].append(relation.object_iri)

    result: list[tuple[ElsstLifecycleTransition, dict[str, Any]]] = []
    for status_subject in comparison.new_deprecated_concept_iris:
        predecessor = predecessor_by_current.get(status_subject)
        if predecessor is None or predecessor not in previous_members:
            raise ElsstRulespecProjectionError(f"newly deprecated {status_subject} has no exact predecessor")
        successors = tuple(sorted(set(successors_by_status_subject.get(status_subject, []))))
        if any(item not in current_members for item in successors):
            raise ElsstRulespecProjectionError(f"{status_subject} has a replacement outside the current release")
        operation = "deprecation" if not successors else "replacement" if len(successors) == 1 else "split"
        event_iri = _sha256_identifier(
            "urn:ref:elsst:lifecycle",
            {
                "identifierScope": identifier_scope,
                "operation": operation,
                "sourceStatusConcept": status_subject,
                "predecessors": [predecessor],
                "successors": list(successors),
                "previousRelease": previous_release.release_iri,
                "currentRelease": current_release.release_iri,
            },
        )
        transition = ElsstLifecycleTransition(
            event_iri=event_iri,
            operation=operation,
            source_status_concept_iri=status_subject,
            predecessor_concept_iris=(predecessor,),
            successor_concept_iris=successors,
            predecessor_release_iri=previous_release.release_iri,
            successor_release_iri=(current_release.release_iri if successors else None),
        )
        node: dict[str, Any] = {
            "@id": event_iri,
            "@type": "rkaf:LifecycleEvent",
            "rkaf:lifecycleEventKind": "rkaf:conceptLifecycle",
            "rkaf:conceptLifecycleOperation": f"rkaf:{operation}",
            "rkaf:effectiveDate": f"{effective_date}T00:00:00Z",
            "rkaf:emittedBy": registry_iri,
            "rkaf:appliesTo": [predecessor],
            "rkaf:predecessorConcepts": [predecessor],
            "rkaf:predecessorConceptRelease": (previous_release.release_iri),
        }
        if successors:
            node["rkaf:successorConcepts"] = list(successors)
            node["rkaf:successorConceptRelease"] = current_release.release_iri
        result.append((transition, node))
    return tuple(result)


def build_elsst_rulespec_history_projection(
    vocabularies: Sequence[ElsstVocabulary],
    releases: Sequence[ElsstReleaseSource],
    *,
    validator: RulespecValidatorPin,
    identifier_scope: str | None = None,
) -> ElsstRulespecProjection:
    """Build an unsealed source-native graph over an ordered ELSST history.

    ``vocabularies`` and ``releases`` are parallel and in publication order,
    oldest first.  One edition is a complete history and states no lifecycle
    transition; each consecutive pair contributes the transitions its two
    releases prove.
    """

    if len(vocabularies) != len(releases):
        raise ElsstRulespecProjectionError("each ELSST vocabulary needs its exact release descriptor")
    if not releases:
        raise ElsstRulespecProjectionError("an ELSST history needs at least one exact publisher release")
    release_iris = tuple(release.release_iri for release in releases)
    if len(set(release_iris)) != len(release_iris):
        raise ElsstRulespecProjectionError("ELSST history releases must have distinct IRIs")
    resolved_identifier_scope = _projection_identifier_scope(
        vocabularies=vocabularies,
        releases=releases,
        validator=validator,
        identifier_scope=identifier_scope,
    )
    rulespec_graph_iri = _scoped_identifier(
        ELSST_RULESPEC_GRAPH_IRI,
        resolved_identifier_scope,
    )
    projection_activity_iri = _scoped_identifier(
        ELSST_PROJECTION_ACTIVITY_IRI,
        resolved_identifier_scope,
    )
    date_materialization_policy_iri = _scoped_identifier(
        ELSST_DATE_MATERIALIZATION_POLICY_IRI,
        resolved_identifier_scope,
    )
    projected = tuple(
        _native_release_nodes(
            vocabulary,
            release,
            identifier_scope=resolved_identifier_scope,
        )
        for vocabulary, release in zip(vocabularies, releases, strict=True)
    )
    release_nodes = [nodes for nodes, _date, _registry, _distribution in projected]
    dates = tuple(date for _nodes, date, _registry, _distribution in projected)
    registries = {registry for _nodes, _date, registry, _distribution in projected}
    distributions = tuple(distribution for _nodes, _date, _registry, distribution in projected)
    if len(registries) != 1:
        raise ElsstRulespecProjectionError("ELSST releases do not identify the same stable resource")
    registry_iri = next(iter(registries))

    transition_rows: list[tuple[ElsstLifecycleTransition, dict[str, Any]]] = []
    for index in range(1, len(releases)):
        transition_rows.extend(
            _lifecycle_transitions(
                compare_elsst_releases(vocabularies[index - 1], vocabularies[index]),
                previous=vocabularies[index - 1],
                current=vocabularies[index],
                previous_release=releases[index - 1],
                current_release=releases[index],
                effective_date=dates[index],
                registry_iri=registry_iri,
                identifier_scope=resolved_identifier_scope,
            )
        )
    transitions = tuple(item[0] for item in transition_rows)
    lifecycle_nodes = [item[1] for item in transition_rows]
    if len(vocabularies) == 2:
        # The published two-edition descriptor, kept verbatim for the same
        # reason its identifier scope is.
        descriptor_preimage: dict[str, Any] = {
            "previousSource": vocabularies[0].source_sha256,
            "currentSource": vocabularies[1].source_sha256,
            "projection": "elsst-source-native-r5-r6-v1",
            "identifierScope": resolved_identifier_scope,
            "dateMaterializationPolicy": (
                date_materialization_policy_iri
            ),
        }
    else:
        descriptor_preimage = {
            "sources": [vocabulary.source_sha256 for vocabulary in vocabularies],
            "projection": "elsst-source-native-history-v1",
            "identifierScope": resolved_identifier_scope,
            "dateMaterializationPolicy": (
                date_materialization_policy_iri
            ),
        }
    graph_descriptor_digest = _sha256_identifier("sha256", descriptor_preimage)
    graph = {
        "@context": _rulespec_context(validator),
        "@graph": [
            {
                "@id": rulespec_graph_iri,
                "@type": "rkaf:Artifact",
                "rkaf:hasArtifactIdentifier": [rulespec_graph_iri],
                "rkaf:artifactIdentifierScheme": ["rkaf:partner-defined"],
                "dcterms:format": "application/ld+json",
                "rkaf:hasContentDigest": graph_descriptor_digest,
            },
            {
                "@id": projection_activity_iri,
                "@type": "prov:Activity",
                "prov:used": [
                    *distributions,
                    date_materialization_policy_iri,
                ],
            },
            {
                "@id": date_materialization_policy_iri,
                "@type": "rkaf:Artifact",
                "rkaf:hasArtifactIdentifier": [
                    date_materialization_policy_iri
                ],
                "rkaf:artifactIdentifierScheme": [
                    "rkaf:partner-defined"
                ],
                "dcterms:format": "application/vnd.refspec.policy+json",
                "rkaf:hasContentDigest": _sha256_identifier(
                    "sha256",
                    {
                        "sourcePrecision": "date",
                        "materialization": "start-of-day",
                        "timezone": "UTC",
                        "derivedPrecision": True,
                    },
                ),
            },
            *(node for nodes in release_nodes for node in nodes),
            *lifecycle_nodes,
        ],
    }
    return ElsstRulespecProjection(
        graph=graph,
        release_iris=release_iris,
        distribution_iris=distributions,
        lifecycle_transitions=transitions,
        source_date_literals=dates,
        date_materialization_policy=(
            date_materialization_policy_iri
        ),
        rulespec_graph_iri=rulespec_graph_iri,
        projection_activity_iri=projection_activity_iri,
        identifier_scope=resolved_identifier_scope,
    )


def build_elsst_rulespec_projection(
    previous: ElsstVocabulary,
    current: ElsstVocabulary,
    *,
    validator: RulespecValidatorPin,
    previous_release: ElsstReleaseSource = ELSST_R5,
    current_release: ElsstReleaseSource = ELSST_R6,
    identifier_scope: str | None = None,
) -> ElsstRulespecProjection:
    """Build an unsealed, deterministic R5/R6 source-native Rulespec graph."""

    if previous_release.release_iri == current_release.release_iri:
        raise ElsstRulespecProjectionError("previous and current releases must have distinct IRIs")
    return build_elsst_rulespec_history_projection(
        (previous, current),
        (previous_release, current_release),
        validator=validator,
        identifier_scope=identifier_scope,
    )


def seal_elsst_rulespec_projection(
    projection: ElsstRulespecProjection,
    *,
    validator: RulespecValidatorPin,
) -> ElsstRulespecProjection:
    """Add independently computed RDFC-1.0 digests to both release records."""

    graph = copy.deepcopy(projection.graph)
    nodes = {node.get("@id"): node for node in graph.get("@graph", []) if isinstance(node, dict)}
    digests: list[tuple[str, str]] = []
    for release_iri in projection.release_iris:
        release = nodes.get(release_iri)
        if not isinstance(release, dict):
            raise ElsstRulespecProjectionError(f"projection is missing release {release_iri}")
        if "rkaf:referenceReleaseDigest" in release:
            raise ElsstRulespecProjectionError(f"release {release_iri} is already sealed")
        try:
            digest = compute_reference_resource_release_digest(
                graph,
                release_iri=release_iri,
                validator=validator,
            )
        except (TypeError, ValueError) as error:
            raise ElsstRulespecProjectionError(str(error)) from error
        if _DIGEST.fullmatch(digest) is None:  # pragma: no cover - helper invariant
            raise ElsstRulespecProjectionError(f"release {release_iri} digest is invalid")
        release["rkaf:referenceReleaseDigest"] = digest
        digests.append((release_iri, digest))
    return replace(
        projection,
        graph=graph,
        release_digests=tuple(digests),
    )


def require_valid_elsst_rulespec_projection(
    projection: ElsstRulespecProjection,
    *,
    validator: RulespecValidatorPin,
) -> None:
    """Require both exact Rulespec graph validators to accept the projection."""

    if {release for release, _digest in projection.release_digests} != set(projection.release_iris):
        raise ElsstRulespecProjectionError("both ELSST releases must be sealed before validation")
    failures = validate_rulespec_graph(
        projection.graph,
        validator=validator,
    )
    if failures:
        raise ElsstRulespecProjectionError(
            "pinned Rulespec validators rejected ELSST projection: " + " | ".join(failures)
        )


__all__ = [
    "DCTERMS_ISSUED_IRI",
    "ELSST_DATE_MATERIALIZATION_POLICY_IRI",
    "ELSST_GENERAL_SUBJECT_FACET_IRI",
    "ELSST_PROJECTION_ACTIVITY_IRI",
    "ELSST_RULESPEC_GRAPH_IRI",
    "ElsstLifecycleTransition",
    "ElsstRulespecProjection",
    "ElsstRulespecProjectionError",
    "build_elsst_rulespec_history_projection",
    "build_elsst_rulespec_projection",
    "require_valid_elsst_rulespec_projection",
    "seal_elsst_rulespec_projection",
]
