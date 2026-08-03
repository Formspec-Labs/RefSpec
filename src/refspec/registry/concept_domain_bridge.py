"""Read one pinned, development-only bridge between concept domains.

The bridge keeps source concepts and target managed-release concepts distinct.
It carries explicit Rulespec ``ConceptMapping`` assertions that a lookup
consumer may use for candidate expansion.  It is deliberately not a managed
vocabulary release, a synthesized union, or accepted-output authorization.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Protocol, cast

from refspec.managed_release import ManagedReleaseConceptMapping
from refspec.vocabulary import require_language_tag

_ABSOLUTE_IRI = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:[^\s]+$")
_SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")
ICPSR_FEDERAL_REGISTER_BRIDGE_V1_SHA256 = (
    "sha256:41b08a28a4bd13de7cd0dbd7929adf78"
    "0768c2f394d44db50a9ea6f280011c52"
)
ICPSR_FEDERAL_REGISTER_BRIDGE_V2_SHA256 = (
    "sha256:1146c3a763a762c8cb1340cfa5bf5fef"
    "cf5cacd12ccfa7e931011e3a56acb8aa"
)
_CONCEPT_MAPPING_TYPES = frozenset(
    {
        "rkaf:ConceptMapping",
        "https://rulespec.org/ns/v1#ConceptMapping",
    }
)
_SKOS_MAPPING_PREDICATES = frozenset(
    {
        "skos:exactMatch",
        "skos:closeMatch",
        "skos:broadMatch",
        "skos:narrowMatch",
        "skos:relatedMatch",
        "http://www.w3.org/2004/02/skos/core#exactMatch",
        "http://www.w3.org/2004/02/skos/core#closeMatch",
        "http://www.w3.org/2004/02/skos/core#broadMatch",
        "http://www.w3.org/2004/02/skos/core#narrowMatch",
        "http://www.w3.org/2004/02/skos/core#relatedMatch",
    }
)
_TOP_LEVEL_FIELDS = frozenset(
    {
        "developmentOnly",
        "sourceSnapshot",
        "sourceScheme",
        "sourceRelease",
        "targetRelease",
        "sourceConcepts",
        "mappings",
    }
)
_SOURCE_SNAPSHOT_FIELDS = frozenset({"url", "revision", "sha256"})
_SOURCE_CONCEPT_REQUIRED_FIELDS = frozenset(
    {"id", "prefLabel", "evidenceUrl"}
)
_SOURCE_CONCEPT_OPTIONAL_FIELDS = frozenset({"altLabel", "definition"})
_MAPPING_FIELDS = frozenset(
    {
        "@id",
        "@type",
        "rkaf:assertionOrigin",
        "rkaf:epistemicBasis",
        "rkaf:assertsSubject",
        "rkaf:assertsPredicate",
        "rkaf:assertsObject",
        "rkaf:assertionPolarity",
        "rkaf:sourceConceptRelease",
        "rkaf:targetConceptRelease",
        "rkaf:managedByRegistry",
        "rkaf:usageEligibility",
    }
)
_DEVELOPMENT_MAPPING_VALUES = {
    "rkaf:assertionOrigin": "rkaf:humanAsserted",
    "rkaf:epistemicBasis": "rkaf:editorialAssertion",
    "rkaf:assertionPolarity": "rkaf:affirmed",
    "rkaf:usageEligibility": "rkaf:localOperationalUse",
}


class ConceptDomainBridgeError(ValueError):
    """A concept-domain bridge is not an exact, usable development artifact."""


class _ManagedReleaseMemberLike(Protocol):
    release_iri: str


class ManagedReleaseViewLike(Protocol):
    """The exact member lookup needed from a target managed release."""

    def lookup_member(
        self,
        member_iri: str,
    ) -> _ManagedReleaseMemberLike | None:
        """Return the exact target member, or ``None`` when it is absent."""


@dataclass(frozen=True, slots=True)
class ConceptDomainSourceSnapshot:
    """Declared upstream pin retained from the bridge review."""

    url: str
    revision: str
    sha256: str


@dataclass(frozen=True, slots=True)
class ConceptDomainSourceConcept:
    """One source-domain concept retained without merging target identity."""

    concept_iri: str
    preferred_labels: Mapping[str, str]
    alternate_labels: Mapping[str, tuple[str, ...]]
    definitions: Mapping[str, tuple[str, ...]]
    evidence_url: str
    record: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class ConceptDomainBridge:
    """One pinned set of source concepts and explicit cross-domain mappings."""

    development_only: bool
    source_snapshot: ConceptDomainSourceSnapshot
    source_scheme_iri: str
    source_release_iri: str
    target_release_iri: str
    source_concepts: tuple[ConceptDomainSourceConcept, ...]
    mappings: tuple[ManagedReleaseConceptMapping, ...]
    artifact_sha256: str
    record: Mapping[str, Any]

    def lookup_source_concept(
        self,
        concept_iri: str,
    ) -> ConceptDomainSourceConcept | None:
        """Return a source concept by exact IRI, never by label."""

        return next(
            (
                concept
                for concept in self.source_concepts
                if concept.concept_iri == concept_iri
            ),
            None,
        )


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType(
            {str(key): _freeze(child) for key, child in value.items()}
        )
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return tuple(_freeze(child) for child in value)
    return value


def _reject_duplicate_json_keys(
    pairs: list[tuple[str, Any]],
) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, child in pairs:
        if key in value:
            raise ConceptDomainBridgeError(
                f"JSON object repeats field {key!r}"
            )
        value[key] = child
    return value


def _require_exact_fields(
    value: Mapping[str, Any],
    required: frozenset[str],
    label: str,
    *,
    optional: frozenset[str] = frozenset(),
) -> None:
    actual = frozenset(value)
    missing = sorted(required - actual)
    unexpected = sorted(actual - required - optional)
    if missing or unexpected:
        details: list[str] = []
        if missing:
            details.append(f"missing {missing!r}")
        if unexpected:
            details.append(f"unexpected {unexpected!r}")
        raise ConceptDomainBridgeError(
            f"{label} has invalid fields: {', '.join(details)}"
        )


def _require_iri(value: object, label: str) -> str:
    if (
        not isinstance(value, str)
        or _ABSOLUTE_IRI.fullmatch(value) is None
    ):
        raise ConceptDomainBridgeError(
            f"{label} must be an absolute IRI"
        )
    return value


def _require_digest(value: object, label: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise ConceptDomainBridgeError(
            f"{label} must be sha256:<64 lowercase hex>"
        )
    return value


def _require_text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ConceptDomainBridgeError(f"{label} must be a non-empty string")
    return value


def _require_object(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ConceptDomainBridgeError(f"{label} must be a JSON object")
    return cast(Mapping[str, Any], value)


def _require_list(value: object, label: str) -> Sequence[Any]:
    if (
        not isinstance(value, Sequence)
        or isinstance(value, (str, bytes))
        or not value
    ):
        raise ConceptDomainBridgeError(
            f"{label} must be a non-empty JSON array"
        )
    return cast(Sequence[Any], value)


def _require_preferred_label_map(
    value: object,
    label: str,
) -> Mapping[str, str]:
    language_map = _require_object(value, label)
    if not language_map:
        raise ConceptDomainBridgeError(
            f"{label} must contain at least one language"
        )
    normalized: dict[str, str] = {}
    for language, literal in language_map.items():
        try:
            normalized_language = require_language_tag(
                language,
                f"{label} language",
            )
        except ValueError as error:
            raise ConceptDomainBridgeError(str(error)) from error
        normalized[normalized_language] = _require_text(
            literal,
            f"{label}.{language}",
        )
    return MappingProxyType(normalized)


def _require_multi_label_map(
    value: object,
    label: str,
) -> Mapping[str, tuple[str, ...]]:
    language_map = _require_object(value, label)
    if not language_map:
        raise ConceptDomainBridgeError(
            f"{label} must contain at least one language"
        )
    normalized: dict[str, tuple[str, ...]] = {}
    for language, raw_literals in language_map.items():
        try:
            normalized_language = require_language_tag(
                language,
                f"{label} language",
            )
        except ValueError as error:
            raise ConceptDomainBridgeError(str(error)) from error
        literals = (
            (raw_literals,)
            if isinstance(raw_literals, str)
            else tuple(
                _require_list(
                    raw_literals,
                    f"{label}.{language}",
                )
            )
        )
        checked = tuple(
            _require_text(
                literal,
                f"{label}.{language}[{index}]",
            )
            for index, literal in enumerate(literals)
        )
        if len(set(checked)) != len(checked):
            raise ConceptDomainBridgeError(
                f"{label}.{language} contains duplicate values"
            )
        normalized[normalized_language] = checked
    return MappingProxyType(normalized)


def _parse_source_concept(
    raw: object,
    *,
    index: int,
) -> ConceptDomainSourceConcept:
    label = f"sourceConcepts[{index}]"
    value = _require_object(raw, label)
    _require_exact_fields(
        value,
        _SOURCE_CONCEPT_REQUIRED_FIELDS,
        label,
        optional=_SOURCE_CONCEPT_OPTIONAL_FIELDS,
    )
    alternate_labels = (
        _require_multi_label_map(value["altLabel"], f"{label}.altLabel")
        if "altLabel" in value
        else MappingProxyType({})
    )
    definitions = (
        _require_multi_label_map(
            value["definition"],
            f"{label}.definition",
        )
        if "definition" in value
        else MappingProxyType({})
    )
    return ConceptDomainSourceConcept(
        concept_iri=_require_iri(value["id"], f"{label}.id"),
        preferred_labels=_require_preferred_label_map(
            value["prefLabel"],
            f"{label}.prefLabel",
        ),
        alternate_labels=alternate_labels,
        definitions=definitions,
        evidence_url=_require_iri(
            value["evidenceUrl"],
            f"{label}.evidenceUrl",
        ),
        record=cast(Mapping[str, Any], _freeze(value)),
    )


def _parse_mapping(
    raw: object,
    *,
    index: int,
    source_release_iri: str,
    target_release_iri: str,
    source_concepts: Mapping[str, ConceptDomainSourceConcept],
    target_view: ManagedReleaseViewLike,
) -> ManagedReleaseConceptMapping:
    label = f"mappings[{index}]"
    value = _require_object(raw, label)
    _require_exact_fields(value, _MAPPING_FIELDS, label)
    mapping_iri = _require_iri(value["@id"], f"{label}.@id")
    mapping_type = _require_iri(value["@type"], f"{label}.@type")
    if mapping_type not in _CONCEPT_MAPPING_TYPES:
        raise ConceptDomainBridgeError(
            f"{label}.@type must be rkaf:ConceptMapping"
        )
    for field in _MAPPING_FIELDS - {
        "@id",
        "@type",
        "rkaf:assertsPredicate",
    }:
        _require_iri(value[field], f"{label}.{field}")
    for field, expected in _DEVELOPMENT_MAPPING_VALUES.items():
        if value[field] != expected:
            raise ConceptDomainBridgeError(
                f"{label}.{field} must be {expected!r} for this "
                "development bridge"
            )
    relation_iri = _require_iri(
        value["rkaf:assertsPredicate"],
        f"{label}.rkaf:assertsPredicate",
    )
    if relation_iri not in _SKOS_MAPPING_PREDICATES:
        raise ConceptDomainBridgeError(
            f"{label}.rkaf:assertsPredicate must be one of the five "
            "SKOS mapping predicates"
        )
    source_member_iri = cast(str, value["rkaf:assertsSubject"])
    target_member_iri = cast(str, value["rkaf:assertsObject"])
    mapping_source_release = cast(
        str,
        value["rkaf:sourceConceptRelease"],
    )
    mapping_target_release = cast(
        str,
        value["rkaf:targetConceptRelease"],
    )
    if (
        source_member_iri not in source_concepts
        or mapping_source_release != source_release_iri
    ):
        raise ConceptDomainBridgeError(
            f"{label} source endpoint is not a sourceConcept in the exact "
            "sourceRelease"
        )
    target_member = target_view.lookup_member(target_member_iri)
    if (
        target_member is None
        or target_member.release_iri != target_release_iri
        or mapping_target_release != target_release_iri
    ):
        raise ConceptDomainBridgeError(
            f"{label} target endpoint is not a member of the exact "
            "targetRelease"
        )
    return ManagedReleaseConceptMapping(
        mapping_iri=mapping_iri,
        source_member_iri=source_member_iri,
        relation_iri=relation_iri,
        target_member_iri=target_member_iri,
        source_release_iri=source_release_iri,
        target_release_iri=target_release_iri,
        record=cast(Mapping[str, Any], _freeze(value)),
    )


def load_concept_domain_bridge(
    path: Path,
    *,
    expected_sha256: str,
    target_view: ManagedReleaseViewLike,
) -> ConceptDomainBridge:
    """Verify bridge bytes and target endpoints, then load the reviewed data.

    The source snapshot is a retained review-time pin. This offline reader
    does not reacquire upstream bytes; an import or promotion workflow must
    verify those bytes independently.
    """

    expected_sha256 = _require_digest(
        expected_sha256,
        "expected_sha256",
    )
    source_path = Path(path)
    if source_path.is_symlink() or not source_path.is_file():
        raise ConceptDomainBridgeError(
            f"concept-domain bridge is not a regular file: {source_path}"
        )
    payload = source_path.read_bytes()
    actual_sha256 = "sha256:" + hashlib.sha256(payload).hexdigest()
    if actual_sha256 != expected_sha256:
        raise ConceptDomainBridgeError(
            "concept-domain bridge digest does not match its pin"
        )
    try:
        parsed = json.loads(
            payload,
            object_pairs_hook=_reject_duplicate_json_keys,
        )
    except ConceptDomainBridgeError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ConceptDomainBridgeError(
            f"concept-domain bridge is not valid JSON: {error}"
        ) from error
    root = _require_object(parsed, "bridge")
    _require_exact_fields(root, _TOP_LEVEL_FIELDS, "bridge")
    if root["developmentOnly"] is not True:
        raise ConceptDomainBridgeError(
            "bridge.developmentOnly must be true"
        )

    snapshot_value = _require_object(
        root["sourceSnapshot"],
        "bridge.sourceSnapshot",
    )
    _require_exact_fields(
        snapshot_value,
        _SOURCE_SNAPSHOT_FIELDS,
        "bridge.sourceSnapshot",
    )
    source_snapshot = ConceptDomainSourceSnapshot(
        url=_require_iri(
            snapshot_value["url"],
            "bridge.sourceSnapshot.url",
        ),
        revision=_require_text(
            snapshot_value["revision"],
            "bridge.sourceSnapshot.revision",
        ),
        sha256=_require_digest(
            snapshot_value["sha256"],
            "bridge.sourceSnapshot.sha256",
        ),
    )
    source_scheme_iri = _require_iri(
        root["sourceScheme"],
        "bridge.sourceScheme",
    )
    source_release_iri = _require_iri(
        root["sourceRelease"],
        "bridge.sourceRelease",
    )
    target_release_iri = _require_iri(
        root["targetRelease"],
        "bridge.targetRelease",
    )

    source_concepts = tuple(
        _parse_source_concept(raw, index=index)
        for index, raw in enumerate(
            _require_list(root["sourceConcepts"], "bridge.sourceConcepts")
        )
    )
    source_concepts_by_iri = {
        concept.concept_iri: concept for concept in source_concepts
    }
    if len(source_concepts_by_iri) != len(source_concepts):
        raise ConceptDomainBridgeError(
            "bridge.sourceConcepts contains duplicate ids"
        )

    mappings = tuple(
        _parse_mapping(
            raw,
            index=index,
            source_release_iri=source_release_iri,
            target_release_iri=target_release_iri,
            source_concepts=source_concepts_by_iri,
            target_view=target_view,
        )
        for index, raw in enumerate(
            _require_list(root["mappings"], "bridge.mappings")
        )
    )
    mapping_ids = {mapping.mapping_iri for mapping in mappings}
    if len(mapping_ids) != len(mappings):
        raise ConceptDomainBridgeError(
            "bridge.mappings contains duplicate ids"
        )
    if mapping_ids.intersection(source_concepts_by_iri):
        raise ConceptDomainBridgeError(
            "bridge source concept and mapping ids must be unique"
        )

    return ConceptDomainBridge(
        development_only=True,
        source_snapshot=source_snapshot,
        source_scheme_iri=source_scheme_iri,
        source_release_iri=source_release_iri,
        target_release_iri=target_release_iri,
        source_concepts=source_concepts,
        mappings=mappings,
        artifact_sha256=actual_sha256,
        record=cast(Mapping[str, Any], _freeze(root)),
    )
