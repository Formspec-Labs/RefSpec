"""Generate the full English Atlas 3.0 distribution from pinned registry data.

The generator runs the RefSpec registry parsers over every supported complete
release or explicitly bounded capture whose exact bytes are available locally.
It preserves publisher label roles, source identities, semantic rings, direct
authored relations, and release-level provenance. It never consumes an Atlas
1.x or Atlas 2.x graph, and it never imports the archived generated mapping
pairs under ``research/evidence``.
"""

from __future__ import annotations

import argparse
import dataclasses
import gc
import hashlib
import heapq
import importlib.util
import json
import re
import sys
import tempfile
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any
from typing import Literal as TypeLiteral

from rdflib import Dataset, Graph, Literal, URIRef
from rdflib.namespace import DCTERMS, PROV, RDF, SKOS, XSD

from refspec.atlas.v3_source_data import RegistryInputPin, RegistryRelease
from refspec.managed_release import ManagedReleaseGraphFactsView
from refspec.registry.infrastructure.source_concept_release import (
    SourceConceptReleaseView,
    source_scoped_concept_iri,
)
from refspec.registry.infrastructure.source_identity import (
    SourceIdentityError,
    derive_uuid7,
    validate_uuid7_urn,
)
from refspec.registry.managed_releases.federal_register_thesaurus_2025_managed_release import (
    FederalRegisterThesaurus2025ManagedReleaseView,
)
from refspec.registry.managed_releases.icpsr_managed_release import (
    IcpsrManagedReleaseView,
    open_icpsr_managed_release_sources,
)

ROOT = Path(__file__).resolve().parents[1]
BINDING_ROOT = ROOT / "bindings" / "atlas" / "3.0"
if str(BINDING_ROOT / "tools") not in sys.path:
    sys.path.insert(0, str(BINDING_ROOT / "tools"))
DEFAULT_OUTPUT = ROOT / "output" / "atlas-3.0-full-2026-08-05" / "distribution"
SPICY_REGS_ROOT = ROOT.parent
CREATED_AT = "2026-08-05T23:00:00+00:00"
DISTRIBUTION_ID = "urn:ref:atlas:distribution:3.0-full-development:2026-08-05"
NATIVE_REVIEWER = URIRef("urn:ref:actor:atlas-3-source-native-import")
SOURCE_NATIVE_EDITORIAL_POLICY_PAYLOAD = MappingProxyType(
    {
        "admission": "exact source member with trusted parser review",
        "artifactStatus": "developmentBaseline",
        "evidence": (
            "source record preserves an English-only normalized native view "
            "and pins the exact external source locator and digest"
        ),
        "version": "atlas-3.0-source-native-v1",
    }
)
EDITORIAL_POLICY_PAYLOADS = MappingProxyType(
    {
        "sourceNative": SOURCE_NATIVE_EDITORIAL_POLICY_PAYLOAD,
    }
)
_FORBIDDEN_PORTABLE_POLICY_TERMS = frozenset(
    {"eligibility", "ceiling", "searchonly", "usagepermission"}
)
_FALLBACK_NAMESPACE_TOKEN = re.compile(r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$")
_FALLBACK_SOURCE_NAMESPACES = MappingProxyType(
    {
        "loc-lst": "http://id.loc.gov/vocabulary/subjectSchemes/lst",
        "loc-cgpa": "http://id.loc.gov/vocabulary/subjectSchemes/cgpa",
        "icpsr-subject-thesaurus": (
            "https://www.icpsr.umich.edu/web/ICPSR/thesaurus/10001"
        ),
    }
)
SourceLabelRole = TypeLiteral["preferred", "alternate", "hidden"]
SOURCE_LABEL_ROLES = frozenset({"preferred", "alternate", "hidden"})


@dataclass(frozen=True, slots=True)
class SourceSpec:
    key: str
    kind: str
    path: Path
    logical_path: str
    expected_digest: str
    expected_resources: int
    profile: str
    ring: str
    expected_relations: int = 0
    fallback_namespace_token: str | None = None
    emit_source_assignments: bool = True
    resource_id: str | None = None
    source_module: str | None = None
    scope: str = "publisherRelease"
    input_pins: tuple[RegistryInputPin, ...] = ()


@dataclass(frozen=True, slots=True)
class SourceLabel:
    value: str
    language: str | None
    role: SourceLabelRole
    source_path: str

    def __post_init__(self) -> None:
        if self.role not in SOURCE_LABEL_ROLES:
            raise ValueError(f"unsupported source label role: {self.role!r}")


@dataclass(frozen=True, slots=True)
class SourceResource:
    iri: str
    labels: tuple[SourceLabel, ...]
    native_payload: Mapping[str, Any] | None
    source_locator: str
    source_digest: str
    definition: str | None = None
    notes: tuple[str, ...] = ()
    notations: tuple[str, ...] = ()
    status: str | None = None


@dataclass(frozen=True, slots=True)
class SourceRelation:
    subject: str
    predicate: str
    object: str
    source_payload: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class LoadedRelease:
    spec: SourceSpec
    source_release_iri: str
    source_release_digest: str
    atlas_release_iri: str
    scheme_iri: str
    issued: str
    resources: Sequence[SourceResource]
    relations: Sequence[SourceRelation]
    dropped_label_count: int = 0
    metadata: Mapping[str, Any] = dataclasses.field(default_factory=dict)


@dataclass(slots=True)
class BuildGraphs:
    asserted: Graph
    projection: Graph
    derived: Graph
    accounting: dict[str, Any]

    def release(self) -> None:
        """Release the large in-memory RDF stores after their bytes are sealed."""

        self.asserted.close()
        self.projection.close()
        self.derived.close()
        self.asserted = Graph()
        self.projection = Graph()
        self.derived = Graph()
        self.accounting = {}


def _v3_fallback_source_identity(
    *,
    namespace_token: str | None,
    prior_iri: object,
    identity_kind: object,
    local_record_id: object,
    source_scheme: object,
) -> tuple[str, dict[str, str]]:
    """Mint one readable v3 fallback IRI while retaining its source identity.

    The UUIDv7 remains the durable local key. The readable token names the
    configured source namespace; the exact namespace IRI and prior opaque IRI
    remain evidence facts rather than being encoded only as a hash.
    """

    if (
        not isinstance(namespace_token, str)
        or _FALLBACK_NAMESPACE_TOKEN.fullmatch(namespace_token) is None
    ):
        raise ValueError(
            "fallback namespace token must be a lowercase hyphenated identifier"
        )
    if identity_kind != "refspecSourceScoped":
        raise ValueError(
            "only refspecSourceScoped identities may use an Atlas fallback IRI"
        )
    if not isinstance(local_record_id, str):
        raise TypeError("fallback localRecordId must be a UUIDv7 URN")
    try:
        durable_key = validate_uuid7_urn(
            local_record_id,
            label="fallback localRecordId",
        )
    except SourceIdentityError as error:
        raise ValueError(str(error)) from error
    if not isinstance(source_scheme, str) or not source_scheme:
        raise ValueError("fallback sourceScheme must be an absolute IRI")
    try:
        expected_prior_iri = source_scoped_concept_iri(
            source_scheme,
            durable_key,
        )
    except ValueError as error:
        raise ValueError(str(error)) from error
    expected_source_scheme = _FALLBACK_SOURCE_NAMESPACES.get(namespace_token)
    if source_scheme != expected_source_scheme:
        raise ValueError(
            "fallback namespace token does not identify the exact sourceScheme"
        )
    if prior_iri != expected_prior_iri:
        raise ValueError(
            "fallback prior source concept IRI does not match its scheme and UUIDv7"
        )

    local_uuid = durable_key.removeprefix("urn:uuid:")
    iri = f"urn:ref:source-concept:v2:{namespace_token}:{local_uuid}"
    return iri, {
        "identityKind": "refspecSourceScoped",
        "localRecordId": durable_key,
        "namespaceToken": namespace_token,
        "priorSourceConceptIri": expected_prior_iri,
        "sourceScheme": source_scheme,
    }


SOURCE_SPECS = (
    SourceSpec(
        key="crs-legislative-entities",
        kind="sourceConceptRelease",
        path=ROOT
        / "research/evidence/crs-source-concept-releases-2026-08-04/"
        "legislative-entities/bundle-manifest.json",
        logical_path=(
            "refspec/research/evidence/crs-source-concept-releases-2026-08-04/"
            "legislative-entities/bundle-manifest.json"
        ),
        expected_digest="sha256:aa80aaf0495a5e74a5194374cac05075fe8bcc0f0046261853293521544959fd",
        expected_resources=478,
        profile="conceptScheme",
        ring="entity",
        fallback_namespace_token="loc-lst",
    ),
    SourceSpec(
        key="crs-legislative-subjects",
        kind="sourceConceptRelease",
        path=ROOT
        / "research/evidence/crs-source-concept-releases-2026-08-04/"
        "legislative-subjects/bundle-manifest.json",
        logical_path=(
            "refspec/research/evidence/crs-source-concept-releases-2026-08-04/"
            "legislative-subjects/bundle-manifest.json"
        ),
        expected_digest="sha256:f20d688f08134a8b6b1c9a6e202e84c5e051e2786c743df66708be27b55b12e7",
        expected_resources=565,
        profile="conceptScheme",
        ring="subject",
        fallback_namespace_token="loc-lst",
    ),
    SourceSpec(
        key="crs-policy-areas",
        kind="sourceConceptRelease",
        path=ROOT
        / "research/evidence/crs-source-concept-releases-2026-08-04/"
        "policy-areas/bundle-manifest.json",
        logical_path=(
            "refspec/research/evidence/crs-source-concept-releases-2026-08-04/"
            "policy-areas/bundle-manifest.json"
        ),
        expected_digest="sha256:b5966cb93cc1a28cc87ea914538f9c2f3da0b44fb37f66385170b56954dabeb8",
        expected_resources=32,
        profile="conceptScheme",
        ring="subject",
        fallback_namespace_token="loc-cgpa",
    ),
    SourceSpec(
        key="elsst-r6",
        kind="managedRelease",
        path=ROOT
        / "output/elsst-r6-atlas2-bench-input-2026-08-04/managed-release/"
        "managed-release-bundle.json",
        logical_path=(
            "refspec/output/elsst-r6-atlas2-bench-input-2026-08-04/managed-release/"
            "managed-release-bundle.json"
        ),
        expected_digest="sha256:466a4464cd252bf0b0c0e872927abc430f7532610100cf01e8104eec0ee69f25",
        expected_resources=3470,
        profile="conceptScheme",
        ring="subject",
        expected_relations=12_482,
    ),
    SourceSpec(
        key="federal-register-thesaurus-2025",
        kind="managedRelease",
        path=SPICY_REGS_ROOT
        / "output/refspec-vocabulary-portfolio/federal-register-thesaurus-2025/"
        "managed-release/managed-release.json",
        logical_path=(
            "spicy-regs/output/refspec-vocabulary-portfolio/"
            "federal-register-thesaurus-2025/managed-release/managed-release.json"
        ),
        expected_digest="sha256:3491acfdb3c4b51fda6351fcc47c2ca13e63e9df99e30399e05f745c97bf9df6",
        expected_resources=705,
        profile="conceptScheme",
        ring="subject",
        expected_relations=1_451,
    ),
    SourceSpec(
        key="icpsr-subject-thesaurus",
        kind="managedReleaseWithCoverageUnion",
        path=SPICY_REGS_ROOT
        / "output/refspec-vocabulary-portfolio/icpsr/2026-07-30/managed-release/"
        "managed-release.json",
        logical_path=(
            "spicy-regs/output/refspec-vocabulary-portfolio/icpsr/2026-07-30/"
            "managed-release/managed-release.json"
        ),
        expected_digest="sha256:f3c9f4efa7fd12b6339db9feabb029b17425672293a8fb615999c881673ac12a",
        expected_resources=3810,
        profile="conceptScheme",
        ring="subject",
        expected_relations=18_761,
        fallback_namespace_token="icpsr-subject-thesaurus",
    ),
)
SOURCE_LANGUAGE_PROFILES = MappingProxyType(
    {
        "crs-legislative-entities": "explicitTaggedEnglishV1",
        "crs-legislative-subjects": "explicitTaggedEnglishV1",
        "crs-policy-areas": "explicitTaggedEnglishV1",
        "elsst-r6": "elsstCompleteLanguageMapProfileV1",
        "federal-register-thesaurus-2025": "pinnedPublisherEnglishSourceV1",
        "icpsr-subject-thesaurus": "pinnedPublisherEnglishSourceV1",
    }
)

REGISTRY_DESCRIPTORS = BINDING_ROOT / "tests" / "registry-descriptors.nq"
REGISTRY_DESCRIPTORS_LOGICAL_PATH = "refspec/bindings/atlas/3.0/tests/registry-descriptors.nq"
REGISTRY_DESCRIPTORS_EXPECTED_DIGEST = (
    "sha256:f6d9ae24aac695fb4f817afced5d8d7b96d9457ef9ede62c0e88e08b49e08620"
)


def _load_validator() -> Any:
    path = BINDING_ROOT / "tools" / "validate.py"
    spec = importlib.util.spec_from_file_location("refspec_atlas_v3_validate", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot import Atlas 3 validator from {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


ATLAS_VALIDATE = _load_validator()
ATLAS = ATLAS_VALIDATE.ATLAS
SKOSXL = ATLAS_VALIDATE.SKOSXL
_RING_RELATION_POLICIES = ATLAS_VALIDATE._relation_policies()
_SOURCE_LABEL_PREDICATES = MappingProxyType(
    {
        "alternate": SKOSXL.altLabel,
        "hidden": SKOSXL.hiddenLabel,
        "preferred": SKOSXL.prefLabel,
    }
)


def _ring_dispatch(ring_name: str) -> tuple[URIRef, URIRef, URIRef]:
    """Resolve one ring through the binding's canonical class/predicate policy."""

    ring = ATLAS[ring_name]
    resource_class = ATLAS_VALIDATE.RING_RESOURCE_CLASSES.get(ring)
    assignment_predicates = _RING_RELATION_POLICIES.get(ring, {}).get(
        ATLAS.SourceAssignment,
        frozenset(),
    )
    if resource_class is None or len(assignment_predicates) != 1:
        raise ValueError(f"unsupported Atlas semantic ring: {ring_name!r}")
    return ring, resource_class, next(iter(assignment_predicates))


def _source_label_role(value: object, *, context: str) -> SourceLabelRole:
    if value == "preferred":
        return "preferred"
    if value == "alternate":
        return "alternate"
    if value == "hidden":
        return "hidden"
    raise ValueError(f"{context} has unsupported label role: {value!r}")


def _source_label_role_from_preferred(
    value: object,
    *,
    context: str,
) -> SourceLabelRole:
    if value is True:
        return "preferred"
    if value is False:
        return "alternate"
    raise TypeError(f"{context} preferred flag is not boolean")


def _source_label_predicate(role: SourceLabelRole) -> URIRef:
    try:
        return _SOURCE_LABEL_PREDICATES[role]
    except KeyError as error:
        raise ValueError(f"unsupported source label role: {role!r}") from error


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return "sha256:" + digest.hexdigest()


def _verify_pinned_file(
    path: Path,
    *,
    logical_path: str,
    expected_digest: str,
) -> str:
    """Verify one externally pinned root without publishing its checkout path."""

    if path.is_symlink() or not path.is_file():
        raise FileNotFoundError(f"pinned Atlas input is not a regular file: {logical_path}")
    observed = _sha256_file(path)
    if observed != expected_digest:
        raise ValueError(
            f"pinned Atlas input drifted: {logical_path}; "
            f"expected={expected_digest}, observed={observed}"
        )
    return observed


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"expected a JSON object in {path}")
    return value


def _plain(value: Any) -> Any:
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {
            field.name: _plain(getattr(value, field.name))
            for field in dataclasses.fields(value)
        }
    if isinstance(value, (dict, MappingProxyType, Mapping)):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    if isinstance(value, (set, frozenset)):
        return sorted(_plain(item) for item in value)
    return value


def _portable_policy_term_violations(
    value: Any,
    *,
    path: str = "$",
) -> tuple[str, ...]:
    """Find serving-permission language that cannot enter portable policy."""

    violations: list[str] = []
    if isinstance(value, Mapping):
        for key, item in value.items():
            key_text = str(key)
            normalized_key = re.sub(r"[^a-z0-9]", "", key_text.casefold())
            for term in sorted(_FORBIDDEN_PORTABLE_POLICY_TERMS):
                if term in normalized_key:
                    violations.append(f"{path}/{key_text} (key contains {term})")
            violations.extend(
                _portable_policy_term_violations(
                    item,
                    path=f"{path}/{key_text}",
                )
            )
    elif isinstance(value, Sequence) and not isinstance(
        value,
        (str, bytes, bytearray),
    ):
        for index, item in enumerate(value):
            violations.extend(
                _portable_policy_term_violations(item, path=f"{path}/{index}")
            )
    elif isinstance(value, str):
        normalized_value = re.sub(r"[^a-z0-9]", "", value.casefold())
        for term in sorted(_FORBIDDEN_PORTABLE_POLICY_TERMS):
            if term in normalized_value:
                violations.append(f"{path} (value contains {term})")
    return tuple(violations)


def _assert_portable_editorial_policy_payload(payload: Mapping[str, Any]) -> None:
    violations = _portable_policy_term_violations(payload)
    if violations:
        raise ValueError(
            "Atlas 3 editorial policy contains serving eligibility or permission "
            "language: "
            + "; ".join(violations)
        )


def _canonical_digest(value: Any) -> str:
    return ATLAS_VALIDATE.canonical_sha256(_plain(value))


def _native_digest(value: Any) -> str:
    payload = ATLAS_VALIDATE.canonical_native_json_bytes(_plain(value))
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _rdf_datetime(value: str) -> str:
    """Use the rdflib round-trippable UTC spelling required by canonical N-Quads."""

    return value[:-1] + "+00:00" if value.endswith("Z") else value


_LANGUAGE_TAG_RE = re.compile(
    r"^[A-Za-z]{2,8}(?:-[A-Za-z0-9]{1,8})*$"
)
_EXPLICIT_LANGUAGE_KEYS = frozenset(
    {"@language", "lang", "language", "languagetag"}
)
ELSST_LANGUAGE_MAP_FIELDS = frozenset(
    {
        "skos:altLabel",
        "skos:changeNote",
        "skos:definition",
        "skos:editorialNote",
        "skos:example",
        "skos:hiddenLabel",
        "skos:historyNote",
        "skos:note",
        "skos:prefLabel",
        "skos:scopeNote",
        "xkos:additionalContentNote",
    }
)
_DROP_LANGUAGE_VALUE = object()


def _language_map_values(
    value: object,
    *,
    path: tuple[str, ...],
) -> dict[str, list[str]]:
    """Validate one profile-declared scalar-or-array language map."""

    location = "/".join(path) or "<root>"
    if not isinstance(value, Mapping):
        raise TypeError(f"language map at {location} is not an object")
    result: dict[str, list[str]] = {}
    for raw_language, raw_values in value.items():
        if (
            not isinstance(raw_language, str)
            or _LANGUAGE_TAG_RE.fullmatch(raw_language) is None
        ):
            raise ValueError(f"language map at {location} has an invalid tag")
        values = (
            list(raw_values)
            if isinstance(raw_values, Sequence)
            and not isinstance(raw_values, (str, bytes))
            else [raw_values]
        )
        if not all(isinstance(item, str) for item in values):
            raise TypeError(f"language map at {location} contains non-text values")
        result[raw_language] = values
    return result


def _looks_like_language_map(value: object) -> bool:
    if not isinstance(value, Mapping) or not value:
        return False
    try:
        _language_map_values(value, path=("candidate",))
    except (TypeError, ValueError):
        return False
    return True


def _normalize_english_language_content(
    value: object,
    *,
    language_map_fields: frozenset[str] = frozenset(),
) -> tuple[Any, tuple[Mapping[str, Any], ...]]:
    """Recursively retain English language-bearing values and receipt all drops."""

    dropped: list[Mapping[str, Any]] = []

    def visit(item: object, path: tuple[str, ...]) -> Any:
        if isinstance(item, (dict, MappingProxyType, Mapping)):
            explicit_keys = [
                str(key)
                for key in item
                if str(key).lower() in _EXPLICIT_LANGUAGE_KEYS
            ]
            if len(explicit_keys) > 1:
                raise ValueError(
                    f"multiple language tags at {'/'.join(path) or '<root>'}"
                )
            explicit_key = explicit_keys[0] if explicit_keys else None
            if explicit_key is not None:
                explicit_language = item[explicit_key]
                if not isinstance(explicit_language, str):
                    raise TypeError(
                        f"language tag at {'/'.join(path) or '<root>'} is not text"
                    )
                if explicit_language.lower() != "en":
                    dropped.append(
                        {
                            "kind": "languageTaggedValue",
                            "language": explicit_language,
                            "path": "/".join(path),
                            "values": [_plain(item)],
                        }
                    )
                    return _DROP_LANGUAGE_VALUE
            result: dict[str, Any] = {}
            for raw_key, raw_child in item.items():
                key = str(raw_key)
                child_path = (*path, key)
                if key in language_map_fields:
                    language_values = _language_map_values(
                        raw_child,
                        path=child_path,
                    )
                    child = {}
                    for language, values in sorted(language_values.items()):
                        if language.lower() == "en":
                            child["en"] = values
                        else:
                            dropped.append(
                                {
                                    "kind": "languageMap",
                                    "language": language,
                                    "path": "/".join(child_path),
                                    "values": values,
                                }
                            )
                elif (
                    key.startswith(("skos:", "xkos:"))
                    and _looks_like_language_map(raw_child)
                ):
                    raise ValueError(
                        f"unprofiled language-bearing field at {'/'.join(child_path)}"
                    )
                elif explicit_key is not None and key == explicit_key:
                    child = "en"
                else:
                    child = visit(raw_child, child_path)
                if child is not _DROP_LANGUAGE_VALUE:
                    result[key] = child
            return result

        if isinstance(item, Sequence) and not isinstance(item, (str, bytes)):
            result_list: list[Any] = []
            for index, raw_child in enumerate(item):
                child = visit(raw_child, (*path, str(index)))
                if child is not _DROP_LANGUAGE_VALUE:
                    result_list.append(child)
            return result_list
        return item

    normalized = visit(value, ())
    if normalized is _DROP_LANGUAGE_VALUE:
        normalized = None
    return normalized, tuple(dropped)


def _audit_english_language_content(
    value: object,
    *,
    language_map_fields: frozenset[str] = frozenset(),
) -> tuple[int, int, tuple[str, ...]]:
    """Audit every nested language map and explicit language tag."""

    language_maps = 0
    explicit_tags = 0
    violations: list[str] = []

    def visit(item: object, path: tuple[str, ...]) -> None:
        nonlocal language_maps, explicit_tags
        location = "/".join(path) or "<root>"
        if isinstance(item, (dict, MappingProxyType, Mapping)):
            for raw_key, child in item.items():
                key = str(raw_key)
                if key.lower() in _EXPLICIT_LANGUAGE_KEYS:
                    explicit_tags += 1
                    if not isinstance(child, str) or child.lower() != "en":
                        violations.append(f"{location}/{key}:tag={child!r}")
                child_path = (*path, key)
                if key in language_map_fields:
                    language_maps += 1
                    try:
                        language_values = _language_map_values(
                            child,
                            path=child_path,
                        )
                    except (TypeError, ValueError) as error:
                        violations.append(str(error))
                        continue
                    unexpected = sorted(
                        language
                        for language in language_values
                        if language.lower() != "en"
                    )
                    if unexpected:
                        violations.append(
                            f"{'/'.join(child_path)}:languageMap={unexpected}"
                        )
                elif (
                    key.startswith(("skos:", "xkos:"))
                    and _looks_like_language_map(child)
                ):
                    violations.append(
                        f"{'/'.join(child_path)}:unprofiledLanguageMap"
                    )
                else:
                    visit(child, child_path)
        elif isinstance(item, Sequence) and not isinstance(item, (str, bytes)):
            for index, child in enumerate(item):
                visit(child, (*path, str(index)))

    visit(value, ())
    return language_maps, explicit_tags, tuple(violations)


def _load_crs(spec: SourceSpec) -> LoadedRelease:
    _verify_pinned_file(
        spec.path,
        logical_path=spec.logical_path,
        expected_digest=spec.expected_digest,
    )
    view = SourceConceptReleaseView.open(
        spec.path,
        expected_manifest_digest=spec.expected_digest,
    )
    observations = {
        str(row["id"]): row for row in view.source_bundle.observations
    }
    resources: list[SourceResource] = []
    dropped_label_count = 0
    for concept in view.concepts:
        observation_id = str(concept["sourceObservation"])
        observation = observations.get(observation_id)
        if observation is None:
            raise ValueError(f"{spec.key} concept lacks source observation {observation_id}")
        identity_kind = concept.get("identityKind")
        source_identity: dict[str, str] | None = None
        if identity_kind == "refspecSourceScoped":
            resource_iri, source_identity = _v3_fallback_source_identity(
                namespace_token=spec.fallback_namespace_token,
                prior_iri=concept.get("id"),
                identity_kind=identity_kind,
                local_record_id=concept.get("localRecordId"),
                source_scheme=concept.get("sourceScheme"),
            )
        elif identity_kind == "publisherConceptIri":
            resource_iri = str(concept["id"])
        else:
            raise ValueError(
                f"{spec.key} concept {concept.get('id')!r} has unsupported identityKind"
            )
        normalized_observation, dropped_language_content = (
            _normalize_english_language_content(observation)
        )
        if not isinstance(normalized_observation, Mapping):
            raise TypeError(f"{spec.key} observation {observation_id} is not an object")
        normalized_labels = normalized_observation.get("labels")
        if not isinstance(normalized_labels, Sequence) or isinstance(
            normalized_labels,
            (str, bytes),
        ):
            raise TypeError(f"{spec.key} observation {observation_id} labels are invalid")
        labels_list: list[SourceLabel] = []
        for row in normalized_labels:
            if not isinstance(row, Mapping):
                raise TypeError(f"{spec.key} observation {observation_id} label is invalid")
            value = row.get("value")
            language = row.get("language")
            if not isinstance(value, str) or language != "en":
                raise ValueError(
                    f"{spec.key} observation {observation_id} label is not normalized English text"
                )
            labels_list.append(
                SourceLabel(
                    value=value,
                    language=language,
                    role=_source_label_role(
                        row.get("role"),
                        context=(
                            f"{spec.key} observation {observation_id} label"
                        ),
                    ),
                    source_path=str(observation["sourcePath"]),
                )
            )
        if not labels_list:
            raise ValueError(f"{spec.key} observation {observation_id} has no English label")
        dropped_label_count += len(dropped_language_content)
        native_payload = {
            "englishOnlyObservation": _plain(normalized_observation),
            "sourceEvidence": {
                "droppedLanguageContentDigest": _native_digest(
                    dropped_language_content
                ),
                "droppedLanguageValueCount": len(dropped_language_content),
                "languageNormalizationAlgorithm": (
                    "recursiveLanguageMapsAndTaggedValuesV1"
                ),
                "originalObservationDigest": _native_digest(observation),
                "sourceTextLanguage": "en",
            },
        }
        if source_identity is not None:
            native_payload["sourceIdentity"] = source_identity
        resources.append(
            SourceResource(
                iri=resource_iri,
                labels=tuple(labels_list),
                native_payload=native_payload,
                source_locator=observation_id,
                source_digest=str(concept["sourceObservationDigest"]),
                definition=(
                    str(normalized_observation["definition"])
                    if normalized_observation.get("definition")
                    else None
                ),
            )
        )
    if len(resources) != spec.expected_resources:
        raise ValueError(
            f"{spec.key} expected {spec.expected_resources} resources; found {len(resources)}"
        )
    scheme_iri = (
        "urn:ref:atlas-resource-scheme:crs-policy-areas"
        if spec.key == "crs-policy-areas"
        else "urn:ref:atlas-resource-scheme:crs-legislative-subject-terms"
    )
    return LoadedRelease(
        spec=spec,
        source_release_iri=view.release_id,
        source_release_digest=view.release_digest,
        atlas_release_iri=view.release_id + ":atlas-3",
        scheme_iri=scheme_iri,
        issued="2026-08-04",
        resources=tuple(resources),
        relations=(),
        dropped_label_count=dropped_label_count,
    )


def _load_federal_register(spec: SourceSpec) -> LoadedRelease:
    _verify_pinned_file(
        spec.path,
        logical_path=spec.logical_path,
        expected_digest=spec.expected_digest,
    )
    view = FederalRegisterThesaurus2025ManagedReleaseView.open(spec.path)
    relations_by_source: dict[str, list[Mapping[str, Any]]] = {}
    for relation in view.relations:
        relations_by_source.setdefault(str(relation["sourceConceptIri"]), []).append(
            relation
        )
    resources: list[SourceResource] = []
    for concept in view.concepts:
        locator = concept["sourceLocator"]
        payload = {
            "concept": _plain(concept),
            "relations": [
                _plain(row)
                for row in relations_by_source.get(str(concept["conceptIri"]), ())
            ],
        }
        labels = [
            SourceLabel(
                value=str(concept["preferredLabel"]),
                language="en",
                role="preferred",
                source_path=json.dumps(
                    _plain(locator), sort_keys=True, separators=(",", ":")
                ),
            )
        ]
        labels.extend(
            SourceLabel(
                value=str(value),
                language="en",
                role="alternate",
                source_path=json.dumps(
                    _plain(locator), sort_keys=True, separators=(",", ":")
                ),
            )
            for value in concept.get("alternateLabels", ())
        )
        resources.append(
            SourceResource(
                iri=str(concept["conceptIri"]),
                labels=tuple(labels),
                native_payload=payload,
                source_locator=(
                    "urn:ref:federal-register-thesaurus:2025-04-01:source-record:"
                    + str(concept["conceptId"])
                ),
                source_digest=_native_digest(payload),
            )
        )
    seen: set[tuple[str, str, str]] = set()
    relations: list[SourceRelation] = []
    for row in view.relations:
        if row.get("resolutionStatus") != "resolved":
            continue
        key = (
            str(row["sourceConceptIri"]),
            str(row["predicateIri"]),
            str(row["targetConceptIri"]),
        )
        if key in seen:
            continue
        seen.add(key)
        relations.append(SourceRelation(*key, source_payload=_plain(row)))
    release = view.manifest["release"]
    return LoadedRelease(
        spec=spec,
        source_release_iri=(
            "urn:ref:federal-register-thesaurus:2025-04-01:reference-resource-release:v1"
        ),
        source_release_digest=str(view.manifest["canonicalPayloadDigest"]),
        atlas_release_iri=(
            "urn:ref:federal-register-thesaurus:2025-04-01:atlas-release:3"
        ),
        scheme_iri="urn:ref:atlas-resource-scheme:federal-register-thesaurus-2025",
        issued=str(release["issued"]),
        resources=tuple(resources),
        relations=tuple(relations),
    )


def _load_elsst(spec: SourceSpec) -> LoadedRelease:
    _verify_pinned_file(
        spec.path,
        logical_path=spec.logical_path,
        expected_digest=spec.expected_digest,
    )
    view = ManagedReleaseGraphFactsView.open(
        spec.path,
        expected_manifest_digest=spec.expected_digest,
    )
    members = tuple(view.iter_members(release_iri="https://elsst.cessda.eu/id/6"))
    resources: list[SourceResource] = []
    relations: list[SourceRelation] = []
    dropped_label_count = 0
    for member in members:
        labels: list[SourceLabel] = []
        member_dropped_label_count = 0
        member_dropped_label_counts_by_language: dict[str, int] = {}
        record = member.record
        normalized_record, dropped_language_content = (
            _normalize_english_language_content(
                record,
                language_map_fields=ELSST_LANGUAGE_MAP_FIELDS,
            )
        )
        if not isinstance(normalized_record, Mapping):
            raise TypeError(f"ELSST member {member.member_iri} is not an object")
        dropped_language_value_counts_by_language: dict[str, int] = {}
        for dropped in dropped_language_content:
            language = str(dropped["language"])
            raw_values = dropped["values"]
            value_count = (
                len(raw_values)
                if isinstance(raw_values, Sequence)
                and not isinstance(raw_values, (str, bytes))
                else 1
            )
            dropped_language_value_counts_by_language[language] = (
                dropped_language_value_counts_by_language.get(language, 0)
                + value_count
            )
            if dropped["path"] in {
                "skos:altLabel",
                "skos:hiddenLabel",
                "skos:prefLabel",
            }:
                dropped_label_count += value_count
                member_dropped_label_count += value_count
                member_dropped_label_counts_by_language[language] = (
                    member_dropped_label_counts_by_language.get(language, 0)
                    + value_count
                )
        for property_name, role in (
            ("skos:prefLabel", "preferred"),
            ("skos:altLabel", "alternate"),
            ("skos:hiddenLabel", "hidden"),
        ):
            language_map = normalized_record.get(property_name, {})
            if not isinstance(language_map, Mapping):
                raise TypeError(
                    f"ELSST member {member.member_iri} {property_name} is not a language map"
                )
            for language, raw_values in sorted(language_map.items()):
                values = (
                    raw_values
                    if isinstance(raw_values, Sequence)
                    and not isinstance(raw_values, (str, bytes))
                    else (raw_values,)
                )
                for value in values:
                    labels.append(
                        SourceLabel(
                            value=str(value),
                            language=str(language),
                            role=role,
                            source_path=f"{member.member_iri}#{property_name}",
                        )
                    )
        if not labels:
            raise ValueError(f"ELSST member {member.member_iri} has no source label")

        def language_values(
            property_name: str,
            source_record: Mapping[str, Any] = normalized_record,
        ) -> tuple[str, ...]:
            language_map = source_record.get(property_name, {})
            if not isinstance(language_map, Mapping):
                return ()
            raw_values = language_map.get("en", ())
            rows = (
                raw_values
                if isinstance(raw_values, Sequence)
                and not isinstance(raw_values, (str, bytes))
                else (raw_values,)
            )
            return tuple(str(row) for row in rows)

        native_payload = {
            "englishOnlyMember": _plain(normalized_record),
            "sourceEvidence": {
                "droppedLabelCount": member_dropped_label_count,
                "droppedLabelCountsByLanguage": (
                    member_dropped_label_counts_by_language
                ),
                "droppedLanguageValueCount": sum(
                    dropped_language_value_counts_by_language.values()
                ),
                "droppedLanguageValueCountsByLanguage": (
                    dropped_language_value_counts_by_language
                ),
                "droppedLanguageContentDigest": _native_digest(
                    dropped_language_content
                ),
                "droppedLanguageFieldCount": len(
                    {str(row["path"]) for row in dropped_language_content}
                ),
                "languageNormalizationAlgorithm": (
                    "recursiveLanguageMapsAndJsonLdLanguageValuesV1"
                ),
                "originalMemberDigest": _native_digest(record),
                "originalSourceLocator": member.member_iri,
                "rawMultilingualContent": "externalByLocatorAndDigestOnly",
            },
        }

        resources.append(
            SourceResource(
                iri=member.member_iri,
                labels=tuple(labels),
                native_payload=native_payload,
                source_locator=member.member_iri,
                source_digest=_native_digest(record),
                definition=(language_values("skos:definition") or (None,))[0],
                notes=language_values("skos:scopeNote"),
            )
        )
        for property_name, predicate in (
            ("skos:broader", "http://www.w3.org/2004/02/skos/core#broader"),
            ("skos:narrower", "http://www.w3.org/2004/02/skos/core#narrower"),
            ("skos:related", "http://www.w3.org/2004/02/skos/core#related"),
        ):
            for target in record.get(property_name, ()):
                relations.append(
                    SourceRelation(
                        subject=member.member_iri,
                        predicate=predicate,
                        object=str(target),
                        source_payload={
                            "sourceMember": member.member_iri,
                            "sourceProperty": property_name,
                            "targetMember": str(target),
                        },
                    )
                )
    if len(resources) != spec.expected_resources:
        raise ValueError(
            f"{spec.key} expected {spec.expected_resources} resources; found {len(resources)}"
        )
    return LoadedRelease(
        spec=spec,
        source_release_iri="https://elsst.cessda.eu/id/6",
        source_release_digest=_canonical_digest(
            {
                "managedReleaseManifest": _sha256_file(spec.path),
                "members": sorted(member.member_iri for member in members),
                "selectedRelease": "https://elsst.cessda.eu/id/6",
            }
        ),
        atlas_release_iri="https://elsst.cessda.eu/id/6#atlas-3",
        scheme_iri="urn:ref:atlas-resource-scheme:elsst",
        issued="2026-08-04",
        resources=tuple(resources),
        relations=tuple(relations),
        dropped_label_count=dropped_label_count,
    )


def _icpsr_relation_predicate(value: str) -> str:
    return {
        "broader": "http://www.w3.org/2004/02/skos/core#broader",
        "narrower": "http://www.w3.org/2004/02/skos/core#narrower",
        "related": "http://www.w3.org/2004/02/skos/core#related",
        "use": "https://refspec.org/ns/atlas/v3#thesaurusUse",
        "usedFor": "https://refspec.org/ns/atlas/v3#thesaurusUsedFor",
    }[value]


def _load_icpsr(spec: SourceSpec) -> LoadedRelease:
    _verify_pinned_file(
        spec.path,
        logical_path=spec.logical_path,
        expected_digest=spec.expected_digest,
    )
    view = IcpsrManagedReleaseView.open(spec.path)
    sources = open_icpsr_managed_release_sources(spec.path.parent / "sources")
    scheme_iri = str(view.manifest["release"]["schemeIri"])
    recorded_at = str(view.coverage["recordedAt"])
    xml_by_label = {term.label: term for term in sources.xml.terms}
    index_by_iri = {term.concept_iri: term for term in sources.index.terms}
    label_to_resource = {
        term.label: term.concept_iri for term in sources.index.terms
    }

    minted_by_label: dict[
        str,
        tuple[str, str, dict[str, str]],
    ] = {}
    for label in view.coverage["gaps"]["xmlOnlyLabels"]:
        term = xml_by_label[str(label)]
        seed = (
            scheme_iri
            + "#source-local-record-number="
            + term.source_local_record_number
        )
        local_record_id = "urn:uuid:" + derive_uuid7(
            recorded_at,
            seed=seed.encode("utf-8"),
        )
        prior_iri = source_scoped_concept_iri(scheme_iri, local_record_id)
        iri, source_identity = _v3_fallback_source_identity(
            namespace_token=spec.fallback_namespace_token,
            prior_iri=prior_iri,
            identity_kind="refspecSourceScoped",
            local_record_id=local_record_id,
            source_scheme=scheme_iri,
        )
        label_to_resource[term.label] = iri
        minted_by_label[term.label] = (
            iri,
            seed,
            source_identity,
        )

    def xml_payload(term: Any) -> dict[str, Any]:
        return {
            "broaderLabels": list(term.broader_labels),
            "inputTimestamp": term.input_timestamp,
            "label": term.label,
            "narrowerLabels": list(term.narrower_labels),
            "preferred": term.preferred,
            "relatedLabels": list(term.related_labels),
            "scopeNotes": list(term.scope_notes),
            "sourceLocalRecordNumber": term.source_local_record_number,
            "updateTimestamp": term.update_timestamp,
            "useLabels": list(term.use_labels),
            "usedForLabels": list(term.used_for_labels),
        }

    resources: list[SourceResource] = []
    for concept in view.concepts:
        source_path = f"index/pages/{concept['sourceLetter']}#term={concept['publisherCode']}"
        source_locator = str(concept["conceptIri"])
        term = xml_by_label[str(concept["officialLabel"])]
        payload = {
            "identityStatus": "publisherIdentifierVerified",
            "indexTerm": _plain(index_by_iri[str(concept["conceptIri"])]),
            "managedConcept": _plain(concept),
            "sourceArtifactDigests": {
                "indexManifest": sources.source_manifest_digest,
                "subjectXml": sources.xml.source_sha256,
            },
            "sourcePaths": [source_path, f"subject.xml#record={term.source_local_record_number}"],
            "sourceScheme": scheme_iri,
            "xmlTerm": xml_payload(term),
        }
        resources.append(
            SourceResource(
                iri=str(concept["conceptIri"]),
                labels=(
                    SourceLabel(
                        value=str(concept["officialLabel"]),
                        language="en",
                        role=_source_label_role(
                            concept["officialLabelRole"],
                            context=(
                                "ICPSR managed concept "
                                f"{concept['conceptIri']} official label"
                            ),
                        ),
                        source_path=source_path,
                    ),
                ),
                native_payload=payload,
                source_locator=source_locator,
                source_digest=_native_digest(payload),
                notes=tuple(str(note) for note in concept.get("scopeNotes", ())),
            )
        )

    gaps = view.coverage["gaps"]
    for term in gaps["indexOnlyTerms"]:
        parsed = index_by_iri[str(term["conceptIri"])]
        source_path = f"index/pages/{parsed.source_letter}#term={term['code']}"
        payload = {
            "identityStatus": "publisherIdentifierVerified",
            "indexTerm": _plain(parsed),
            "sourceArtifactDigests": {"indexManifest": sources.source_manifest_digest},
            "sourcePath": source_path,
            "sourceScheme": scheme_iri,
        }
        resources.append(
            SourceResource(
                iri=str(term["conceptIri"]),
                labels=(
                    SourceLabel(
                        value=str(term["label"]),
                        language="en",
                        role=_source_label_role_from_preferred(
                            term["preferred"],
                            context=f"ICPSR index term {term['conceptIri']} label",
                        ),
                        source_path=source_path,
                    ),
                ),
                native_payload=payload,
                source_locator=str(term["conceptIri"]),
                source_digest=_native_digest(payload),
            )
        )

    for label in gaps["xmlOnlyLabels"]:
        term = xml_by_label[str(label)]
        iri, seed, source_identity = minted_by_label[term.label]
        payload = {
            "identityStatus": "publisherIdentifierAbsent",
            "identitySeed": seed,
            "mintingPolicy": "sourceNamespaceTokenPlusUuid7LocalRecordId",
            "mintingRule": "derive_uuid7(recordedAt, sourceScheme#source-local-record-number=TNR)",
            "recordedAt": recorded_at,
            "sourceArtifactDigests": {"subjectXml": sources.xml.source_sha256},
            "sourceIdentity": source_identity,
            "sourceLocalRecordNumber": term.source_local_record_number,
            "sourcePath": f"subject.xml#record={term.source_local_record_number}",
            "xmlTerm": xml_payload(term),
        }
        source_locator = (
            "urn:ref:icpsr:subject-xml:"
            + sources.xml.source_sha256.removeprefix("sha256:")
            + "#record="
            + term.source_local_record_number
        )
        resources.append(
            SourceResource(
                iri=iri,
                labels=(
                    SourceLabel(
                        value=term.label,
                        language="en",
                        role=_source_label_role_from_preferred(
                            term.preferred,
                            context=(
                                "ICPSR XML term "
                                f"{term.source_local_record_number} label"
                            ),
                        ),
                        source_path=str(payload["sourcePath"]),
                    ),
                ),
                native_payload=payload,
                source_locator=source_locator,
                source_digest=_native_digest(payload),
                notes=tuple(term.scope_notes),
            )
        )

    raw_relations: list[tuple[str, str, str, dict[str, Any]]] = []
    relation_fields = (
        ("broader", "broader_labels"),
        ("narrower", "narrower_labels"),
        ("related", "related_labels"),
        ("use", "use_labels"),
        ("usedFor", "used_for_labels"),
    )
    for term in sources.xml.terms:
        subject = label_to_resource[term.label]
        for relation_name, field_name in relation_fields:
            for target_label in getattr(term, field_name):
                try:
                    target = label_to_resource[target_label]
                except KeyError as error:
                    raise ValueError(
                        f"ICPSR relation target remains unresolved: {target_label!r}"
                    ) from error
                raw_relations.append(
                    (
                        subject,
                        relation_name,
                        target,
                        {
                            "relation": relation_name,
                            "sourceLabel": term.label,
                            "sourceLocalRecordNumber": term.source_local_record_number,
                            "sourcePath": f"subject.xml#record={term.source_local_record_number}",
                            "targetLabel": target_label,
                        },
                    )
                )

    broader: dict[str, set[str]] = {}
    for subject, relation_name, target, _ in raw_relations:
        if relation_name == "broader":
            broader.setdefault(subject, set()).add(target)
        elif relation_name == "narrower":
            broader.setdefault(target, set()).add(subject)
    ancestor_cache: dict[str, frozenset[str]] = {}

    def ancestors(start: str) -> frozenset[str]:
        if start not in ancestor_cache:
            found: set[str] = set()
            pending = list(broader.get(start, ()))
            while pending:
                value = pending.pop()
                if value in found:
                    continue
                found.add(value)
                pending.extend(broader.get(value, ()))
            ancestor_cache[start] = frozenset(found)
        return ancestor_cache[start]

    remapped_related = 0
    relations: list[SourceRelation] = []
    for subject, relation_name, target, payload in raw_relations:
        predicate = _icpsr_relation_predicate(relation_name)
        if relation_name == "related" and (
            target in ancestors(subject) or subject in ancestors(target)
        ):
            predicate = "https://refspec.org/ns/atlas/v3#thesaurusRelated"
            payload = {
                "editorialTransformation": {
                    "fromPredicate": str(SKOS.related),
                    "reason": "SKOS-S27-hierarchy-path",
                    "rule": "preserveAuthoredAssociationOutsideSkosProjection",
                    "toPredicate": predicate,
                },
                "publisherRelation": payload,
            }
            remapped_related += 1
        relations.append(
            SourceRelation(
                subject=subject,
                predicate=predicate,
                object=target,
                source_payload=payload,
            )
        )
    if len(relations) != 18_761 or remapped_related != 22:
        raise ValueError(
            "ICPSR direct relation reconciliation failed: "
            f"relations={len(relations)}, remappedRelated={remapped_related}"
        )
    if len(resources) != spec.expected_resources:
        raise ValueError(
            f"{spec.key} expected {spec.expected_resources} resources; found {len(resources)}"
        )
    release = view.manifest["release"]
    union_basis = {
        "indexCaptureDigest": sources.source_capture_digest,
        "managedSubset": release["id"],
        "membership": sorted(resource.iri for resource in resources),
        "subjectXmlDigest": sources.xml.source_sha256,
    }
    union_digest = _canonical_digest(union_basis)
    source_release_iri = (
        "urn:ref:icpsr:source-release:union:"
        + union_digest.removeprefix("sha256:")
    )
    return LoadedRelease(
        spec=spec,
        source_release_iri=source_release_iri,
        source_release_digest=union_digest,
        atlas_release_iri=source_release_iri + ":atlas-3",
        scheme_iri="urn:ref:atlas-resource-scheme:icpsr-subject-thesaurus",
        issued="2026-07-30",
        resources=tuple(resources),
        relations=tuple(relations),
    )


def _validate_loaded_release(release: LoadedRelease) -> LoadedRelease:
    observed = {
        "relations": len(release.relations),
        "resources": len(release.resources),
    }
    expected = {
        "relations": release.spec.expected_relations,
        "resources": release.spec.expected_resources,
    }
    if observed != expected:
        raise ValueError(
            f"{release.spec.key} source counts differ: "
            f"expected={expected}, observed={observed}"
        )
    return release


def _adapt_registry_release(release: RegistryRelease) -> LoadedRelease:
    """Adapt one normalized registry release without source-specific branching."""

    primary = release.inputs[0]
    spec = SourceSpec(
        key=release.key,
        kind="registryRelease",
        path=primary.path,
        logical_path=primary.logical_path,
        expected_digest=primary.sha256,
        expected_resources=release.expected_resources,
        expected_relations=release.expected_relations,
        profile=release.profile,
        ring=release.ring,
        emit_source_assignments=False,
        resource_id=release.resource_id,
        source_module=release.source_module,
        scope=release.scope,
        input_pins=tuple(release.inputs),
    )
    return _validate_loaded_release(
        LoadedRelease(
            spec=spec,
            source_release_iri=release.source_release_iri,
            source_release_digest=release.source_release_digest,
            atlas_release_iri=release.atlas_release_iri,
            scheme_iri=release.scheme_iri,
            issued=release.issued,
            resources=release.resources,  # type: ignore[arg-type]
            relations=release.relations,  # type: ignore[arg-type]
            dropped_label_count=release.dropped_label_count,
            metadata=release.metadata,
        )
    )


def load_releases() -> tuple[LoadedRelease, ...]:
    from refspec.atlas.v3_registry_codes import load_registry_code_releases
    from refspec.atlas.v3_registry_large import load_large_registry_releases
    from refspec.atlas.v3_registry_vocabularies import (
        load_all_registry_vocabulary_releases,
    )

    loaders = {
        "sourceConceptRelease": _load_crs,
        "managedRelease": _load_elsst,
        "managedReleaseWithCoverageUnion": _load_icpsr,
    }
    releases: list[LoadedRelease] = []
    for spec in SOURCE_SPECS:
        if spec.key in {"elsst-r6", "federal-register-thesaurus-2025"}:
            continue
        release = loaders[spec.kind](spec)
        releases.append(_validate_loaded_release(release))

    registry_releases = (
        *load_all_registry_vocabulary_releases(),
        *load_large_registry_releases(),
        *load_registry_code_releases(ROOT),
    )
    _validate_registry_release_descriptors(registry_releases)
    releases.extend(_adapt_registry_release(release) for release in registry_releases)
    return tuple(releases)


def _validate_registry_release_descriptors(
    releases: Sequence[RegistryRelease],
) -> None:
    """Require each normalized release to match the pinned registry policy."""

    descriptors = _registry_asserted_graph()
    index = json.loads((ROOT / "portfolio" / "atlas-index-v0.json").read_text())
    index_rows = index.get("rows")
    if not isinstance(index_rows, list):
        raise TypeError("Atlas registry index has no rows")

    for release in releases:
        expected_scheme = URIRef(
            "urn:ref:atlas-resource-scheme:" + release.resource_id
        )
        if URIRef(release.scheme_iri) != expected_scheme:
            raise ValueError(
                f"{release.key} scheme differs from registry descriptor: "
                f"{release.scheme_iri} != {expected_scheme}"
            )
        if (expected_scheme, RDF.type, ATLAS.ResourceScheme) not in descriptors:
            raise ValueError(
                f"{release.key} names unknown registry resource {release.resource_id!r}"
            )
        if (expected_scheme, ATLAS.resourceProfile, ATLAS[release.profile]) not in descriptors:
            raise ValueError(
                f"{release.key} profile {release.profile!r} differs from its descriptor"
            )
        if (expected_scheme, ATLAS.supportedRing, ATLAS[release.ring]) not in descriptors:
            raise ValueError(
                f"{release.key} ring {release.ring!r} differs from its descriptor"
            )
        if not any(
            isinstance(row, Mapping)
            and row.get("resourceId") == release.resource_id
            and row.get("semanticRing") == release.ring
            and row.get("sourceModule") == release.source_module
            for row in index_rows
        ):
            raise ValueError(
                f"{release.key} source module/ring is absent from the Atlas index"
            )


def _node_iri(prefix: str, basis: Any) -> URIRef:
    digest = _canonical_digest(basis).removeprefix("sha256:")
    return URIRef(f"urn:ref:{prefix}:{digest}")


def _add_content_digest(graph: Graph, node: URIRef) -> str:
    digest = ATLAS_VALIDATE.rdf_node_digest(graph, node)
    graph.add((node, ATLAS.contentDigest, Literal(digest)))
    return digest


def _add_policy(graph: Graph, payload: Mapping[str, Any]) -> URIRef:
    _assert_portable_editorial_policy_payload(payload)
    pending = URIRef("urn:ref:atlas-policy:pending:" + _canonical_digest(payload)[7:])
    graph.add((pending, RDF.type, ATLAS.EditorialPolicy))
    graph.add(
        (
            pending,
            ATLAS.policyPayload,
            Literal(
                ATLAS_VALIDATE.canonical_json_bytes(
                    _plain(payload), terminal_lf=False
                ).decode("utf-8"),
                datatype=RDF.JSON,
                normalize=False,
            ),
        )
    )
    digest = ATLAS_VALIDATE.rdf_node_digest(graph, pending)
    policy = URIRef("urn:ref:atlas-policy:" + digest.removeprefix("sha256:"))
    for _, predicate, obj in list(graph.triples((pending, None, None))):
        graph.remove((pending, predicate, obj))
        graph.add((policy, predicate, obj))
    graph.add((policy, ATLAS.contentDigest, Literal(digest)))
    return policy


def _add_source_release(
    graph: Graph,
    *,
    identifier: str,
    digest: str,
    issued: str,
    locator: URIRef,
) -> URIRef:
    node = URIRef(identifier)
    graph.add((node, RDF.type, ATLAS.SourceRelease))
    graph.add((node, DCTERMS.identifier, Literal(identifier)))
    graph.add((node, DCTERMS.issued, Literal(issued, datatype=XSD.date)))
    graph.add((node, ATLAS.sourceDigest, Literal(digest)))
    graph.add((node, ATLAS.sourceLocator, locator))
    _add_content_digest(graph, node)
    return node


def _add_source_record(
    graph: Graph,
    *,
    source_release: URIRef,
    source_locator: URIRef,
    source_digest: str,
    native_payload: Any,
    represents_resource: URIRef | None,
    language_map_fields: frozenset[str] = frozenset(),
) -> URIRef:
    _, _, language_violations = _audit_english_language_content(
        native_payload,
        language_map_fields=language_map_fields,
    )
    if language_violations:
        raise ValueError(
            "SourceRecord native payload is not English-only: "
            + ", ".join(language_violations[:5])
        )
    basis = {
        "nativePayloadDigest": _native_digest(native_payload),
        "sourceDigest": source_digest,
        "sourceLocator": str(source_locator),
        "sourceRelease": str(source_release),
    }
    node = _node_iri("atlas-source-record", basis)
    graph.add((node, RDF.type, ATLAS.SourceRecord))
    graph.add((node, ATLAS.inSourceRelease, source_release))
    graph.add((node, ATLAS.sourceDigest, Literal(source_digest)))
    graph.add((node, ATLAS.sourceLocator, source_locator))
    graph.add(
        (
            node,
            ATLAS.nativePayload,
            Literal(
                ATLAS_VALIDATE.canonical_native_json_bytes(
                    _plain(native_payload)
                ).decode("utf-8"),
                datatype=RDF.JSON,
                normalize=False,
            ),
        )
    )
    if represents_resource is not None:
        graph.add((node, ATLAS.representsResource, represents_resource))
    _add_content_digest(graph, node)
    return node


def _review_method_for_assertion(
    assertion_type: URIRef,
    *,
    deterministic_transformation: bool = False,
) -> URIRef:
    """Select the narrow review method supported by an assertion's provenance."""

    if assertion_type in {ATLAS.SourceAssignment, ATLAS.NativeRelationAssertion}:
        return (
            ATLAS.deterministicTransformation
            if deterministic_transformation
            else ATLAS.publisherAssertion
        )
    raise ValueError(f"unsupported assertion review method: {assertion_type}")


def _transformed_relation_evidence(
    relation: SourceRelation,
) -> tuple[URIRef, str, Mapping[str, Any]]:
    """Build evidence for a source relation moved outside the SKOS projection."""

    publisher_relation = relation.source_payload.get("publisherRelation")
    transformation = relation.source_payload.get("editorialTransformation")
    expected_transformation = {
        "fromPredicate": str(SKOS.related),
        "reason": "SKOS-S27-hierarchy-path",
        "rule": "preserveAuthoredAssociationOutsideSkosProjection",
        "toPredicate": str(ATLAS.thesaurusRelated),
    }
    if (
        relation.predicate != str(ATLAS.thesaurusRelated)
        or not isinstance(publisher_relation, Mapping)
        or transformation != expected_transformation
    ):
        raise ValueError(
            "atlas:thesaurusRelated lacks exact deterministic transformation evidence"
        )
    publisher_relation_digest = _native_digest(publisher_relation)
    evidence_payload = {
        "editorialTransformation": expected_transformation,
        "publisherRelation": _plain(publisher_relation),
        "publisherRelationDigest": publisher_relation_digest,
    }
    locator = URIRef(
        "urn:ref:publisher-relation:"
        + publisher_relation_digest.removeprefix("sha256:")
    )
    return locator, publisher_relation_digest, evidence_payload


def _add_assertion(
    graph: Graph,
    *,
    assertion_type: URIRef,
    ring: URIRef,
    subject: URIRef,
    predicate: URIRef,
    obj: URIRef,
    source_release: URIRef,
    target_release: URIRef,
    policy: URIRef,
    asserted_at: str,
    evidence_record: URIRef,
    reviewer: URIRef,
    review_method: URIRef,
    confidence: str | None,
) -> URIRef:
    policy_digest = graph.value(policy, ATLAS.contentDigest)
    if not isinstance(policy_digest, Literal):
        raise TypeError(f"policy has no content digest: {policy}")
    basis = {
        "object": str(obj),
        "policy": str(policy),
        "policyContentDigest": str(policy_digest),
        "predicate": str(predicate),
        "semanticRing": str(ring),
        "sourceRelease": str(source_release),
        "subject": str(subject),
        "targetRelease": str(target_release),
        "type": str(assertion_type),
    }
    identity_digest = _canonical_digest(basis)
    assertion = URIRef(
        "urn:ref:atlas-assertion:" + identity_digest.removeprefix("sha256:")
    )
    graph.add((assertion, RDF.type, ATLAS.RelationAssertion))
    graph.add((assertion, RDF.type, assertion_type))
    if assertion_type == ATLAS.MappingAssertion and ring == ATLAS.subject:
        graph.add((assertion, RDF.type, ATLAS.SkosMappingAssertion))
    graph.add((assertion, RDF.subject, subject))
    graph.add((assertion, RDF.predicate, predicate))
    graph.add((assertion, RDF.object, obj))
    graph.add((assertion, ATLAS.semanticRing, ring))
    graph.add((assertion, ATLAS.sourceRelease, source_release))
    graph.add((assertion, ATLAS.targetRelease, target_release))
    graph.add((assertion, ATLAS.governedByPolicy, policy))
    graph.add(
        (
            assertion,
            ATLAS.assertedAt,
            Literal(_rdf_datetime(asserted_at), datatype=XSD.dateTime, normalize=False),
        )
    )
    graph.add((assertion, ATLAS.assertionStatus, ATLAS.current))
    graph.add((assertion, ATLAS.assertionIdentityDigest, Literal(identity_digest)))
    _add_content_digest(graph, assertion)

    pending = URIRef("urn:ref:atlas-evidence:pending:" + identity_digest[7:])
    graph.add((pending, RDF.type, ATLAS.EvidenceBinding))
    graph.add((pending, ATLAS.bindsAssertion, assertion))
    graph.add((pending, ATLAS.evidenceSourceRecord, evidence_record))
    graph.add(
        (
            pending,
            ATLAS.evidenceSourceDigest,
            graph.value(evidence_record, ATLAS.contentDigest),
        )
    )
    graph.add((pending, ATLAS.reviewedBy, reviewer))
    graph.add((pending, ATLAS.decisionStatus, ATLAS.approved))
    graph.add((pending, ATLAS.reviewMethod, review_method))
    graph.add(
        (
            pending,
            ATLAS.decidedAt,
            Literal(_rdf_datetime(asserted_at), datatype=XSD.dateTime, normalize=False),
        )
    )
    if confidence is not None:
        graph.add(
            (
                pending,
                ATLAS.confidence,
                Literal(confidence, datatype=XSD.decimal, normalize=False),
            )
        )
    evidence_digest = ATLAS_VALIDATE.rdf_node_digest(graph, pending)
    evidence = URIRef(
        "urn:ref:atlas-evidence:" + evidence_digest.removeprefix("sha256:")
    )
    for _, evidence_predicate, evidence_object in list(
        graph.triples((pending, None, None))
    ):
        graph.remove((pending, evidence_predicate, evidence_object))
        graph.add((evidence, evidence_predicate, evidence_object))
    graph.add((evidence, ATLAS.contentDigest, Literal(evidence_digest)))
    return assertion


def _registry_asserted_graph() -> Graph:
    _verify_pinned_file(
        REGISTRY_DESCRIPTORS,
        logical_path=REGISTRY_DESCRIPTORS_LOGICAL_PATH,
        expected_digest=REGISTRY_DESCRIPTORS_EXPECTED_DIGEST,
    )
    dataset = Dataset(default_union=True)
    dataset.parse(REGISTRY_DESCRIPTORS, format="nquads")
    graph = Graph()
    for subject, predicate, obj, _ in dataset.quads((None, None, None, None)):
        graph.add((subject, predicate, obj))
    return graph


def _english_only_scan(releases: tuple[LoadedRelease, ...]) -> dict[str, Any]:
    release_keys = {release.spec.key for release in releases}
    for label, values in {
        "source key": [release.spec.key for release in releases],
        "source release": [release.source_release_iri for release in releases],
        "Atlas release": [release.atlas_release_iri for release in releases],
    }.items():
        if len(values) != len(set(values)):
            raise ValueError(f"Atlas releases repeat a {label}")
    language_profiles = {
        key: SOURCE_LANGUAGE_PROFILES.get(key, "registryEnglishOnlyV1")
        for key in sorted(release_keys)
    }
    label_count = 0
    language_map_count = 0
    explicit_language_tag_count = 0
    native_payload_count = 0
    relation_payload_count = 0
    resource_iris: set[str] = set()
    violations: list[str] = []
    for release in releases:
        for resource in release.resources:
            if resource.iri in resource_iris:
                raise ValueError(f"Atlas releases repeat resource IRI {resource.iri}")
            resource_iris.add(resource.iri)
            native_payload_count += 1
            for label in resource.labels:
                label_count += 1
                if label.language != "en":
                    raise ValueError(
                        "Atlas source normalization retained a non-English label: "
                        f"{release.spec.key}/{resource.iri}"
                    )
            maps, tags, payload_violations = _audit_english_language_content(
                resource.native_payload,
                language_map_fields=(
                    ELSST_LANGUAGE_MAP_FIELDS
                    if release.spec.key == "elsst-r6"
                    else frozenset()
                ),
            )
            language_map_count += maps
            explicit_language_tag_count += tags
            violations.extend(
                f"{release.spec.key}/{resource.iri}/{violation}"
                for violation in payload_violations
            )
        for relation in release.relations:
            relation_payload_count += 1
            maps, tags, payload_violations = _audit_english_language_content(
                relation.source_payload,
                language_map_fields=(
                    ELSST_LANGUAGE_MAP_FIELDS
                    if release.spec.key == "elsst-r6"
                    else frozenset()
                ),
            )
            language_map_count += maps
            explicit_language_tag_count += tags
            violations.extend(
                f"{release.spec.key}/{relation.subject}/{relation.predicate}/"
                f"{relation.object}/{violation}"
                for violation in payload_violations
            )
    if violations:
        raise ValueError(
            "Atlas native source content retained non-English language values: "
            + ", ".join(violations[:5])
        )
    return {
        "emittedLabels": label_count,
        "explicitLanguageTagsChecked": explicit_language_tag_count,
        "languageMapsChecked": language_map_count,
        "nativePayloadsChecked": native_payload_count,
        "nonEnglishAtlasLabels": 0,
        "nonEnglishNativeLanguageFields": 0,
        "normalizedLanguageTag": "en",
        "relationPayloadsChecked": relation_payload_count,
        "scanAlgorithm": "recursiveLanguageMapsAndExplicitLanguageTagsV1",
        "sourceLanguageProfiles": language_profiles,
        "status": "passed",
    }


def _finalize_source_accounting_inputs(
    accounting_inputs: list[dict[str, Any]],
) -> None:
    """Canonicalize source ledgers after every evidence record is appended."""

    for row in accounting_inputs:
        row["dispositions"] = sorted(
            row["dispositions"],
            key=lambda disposition: disposition["sourceRecord"],
        )
        row["declaredMemberCount"] = len(row["dispositions"])
    accounting_inputs.sort(key=lambda row: row["sourceRelease"])


def _build_graphs(
    releases: tuple[LoadedRelease, ...],
) -> BuildGraphs:
    asserted = _registry_asserted_graph()
    native_policy = _add_policy(asserted, SOURCE_NATIVE_EDITORIAL_POLICY_PAYLOAD)

    source_release_nodes: dict[str, URIRef] = {}
    resource_release: dict[str, URIRef] = {}
    resource_record: dict[str, URIRef] = {}
    accounting_inputs: list[dict[str, Any]] = []
    source_accounting_by_release: dict[str, dict[str, Any]] = {}

    for release in releases:
        source_locator = URIRef(
            "urn:ref:source-artifact-set:"
            + release.source_release_digest.removeprefix("sha256:")
        )
        source_release = _add_source_release(
            asserted,
            identifier=release.source_release_iri,
            digest=release.source_release_digest,
            issued=release.issued,
            locator=source_locator,
        )
        source_release_nodes[release.source_release_iri] = source_release
        atlas_release = URIRef(release.atlas_release_iri)
        profile = ATLAS[release.spec.profile]
        ring, resource_class, assignment_predicate = _ring_dispatch(
            release.spec.ring
        )
        scheme = URIRef(release.scheme_iri)
        asserted.add((atlas_release, RDF.type, ATLAS.AtlasRelease))
        asserted.add((atlas_release, ATLAS.resourceProfile, profile))
        asserted.add((atlas_release, ATLAS.semanticRing, ring))
        asserted.add((atlas_release, ATLAS.inScheme, scheme))
        asserted.add((atlas_release, ATLAS.membershipMode, ATLAS.completeMembership))
        asserted.add((atlas_release, DCTERMS.identifier, Literal(release.spec.key)))
        asserted.add(
            (atlas_release, DCTERMS.issued, Literal(release.issued, datatype=XSD.date))
        )

        dispositions: list[dict[str, Any]] = []
        for resource_row in release.resources:
            resource = URIRef(resource_row.iri)
            record = _add_source_record(
                asserted,
                source_release=source_release,
                source_locator=URIRef(resource_row.source_locator),
                source_digest=resource_row.source_digest,
                native_payload=resource_row.native_payload,
                represents_resource=resource,
                language_map_fields=(
                    ELSST_LANGUAGE_MAP_FIELDS
                    if release.spec.key == "elsst-r6"
                    else frozenset()
                ),
            )
            resource_record[resource_row.iri] = record
            resource_release[resource_row.iri] = atlas_release
            asserted.add((resource, RDF.type, ATLAS.AtlasResource))
            asserted.add((resource, RDF.type, resource_class))
            if ring == ATLAS.subject:
                asserted.add((resource, RDF.type, SKOS.Concept))
                asserted.add((resource, SKOS.inScheme, scheme))
            asserted.add((resource, ATLAS.inRelease, atlas_release))
            asserted.add((resource, ATLAS.inScheme, scheme))
            asserted.add((resource, ATLAS.semanticRing, ring))
            asserted.add((resource, ATLAS.resourceProfile, profile))
            asserted.add((resource, ATLAS.sourceRecord, record))
            asserted.add((atlas_release, PROV.hadMember, resource))

            for label_row in resource_row.labels:
                if label_row.language != "en":
                    raise ValueError(
                        f"Atlas label is not normalized to English: {resource_row.iri}"
                    )
                label = _node_iri(
                    "atlas-label",
                    {
                        "language": label_row.language,
                        "resource": resource_row.iri,
                        "role": label_row.role,
                        "sourcePath": label_row.source_path,
                        "value": label_row.value,
                    },
                )
                asserted.add(
                    (resource, _source_label_predicate(label_row.role), label)
                )
                asserted.add((label, RDF.type, SKOSXL.Label))
                asserted.add(
                    (
                        label,
                        SKOSXL.literalForm,
                        Literal(label_row.value, lang=label_row.language),
                    )
                )
                asserted.add((label, ATLAS.inRelease, atlas_release))
                asserted.add((label, ATLAS.sourceRecord, record))
                _add_content_digest(asserted, label)
            if resource_row.definition is not None:
                asserted.add(
                    (
                        resource,
                        ATLAS.definition,
                        Literal(resource_row.definition, lang="en"),
                    )
                )
            for note in resource_row.notes:
                asserted.add((resource, ATLAS.note, Literal(note, lang="en")))
            for notation in resource_row.notations:
                asserted.add(
                    (resource, ATLAS.notation, Literal(notation, datatype=XSD.string))
                )
            if resource_row.status is not None:
                asserted.add(
                    (
                        resource,
                        ATLAS.recordStatus,
                        Literal(resource_row.status, datatype=XSD.string),
                    )
                )
            _add_content_digest(asserted, resource)
            if release.spec.emit_source_assignments:
                _add_assertion(
                    asserted,
                    assertion_type=ATLAS.SourceAssignment,
                    ring=ring,
                    subject=record,
                    predicate=assignment_predicate,
                    obj=resource,
                    source_release=source_release,
                    target_release=atlas_release,
                    policy=native_policy,
                    asserted_at=CREATED_AT,
                    evidence_record=record,
                    reviewer=NATIVE_REVIEWER,
                    review_method=_review_method_for_assertion(
                        ATLAS.SourceAssignment
                    ),
                    confidence="1",
                )
            dispositions.append(
                {
                    "atlasResources": [resource_row.iri],
                    "sourceRecord": str(record),
                    "status": "represented",
                }
            )
        _add_content_digest(asserted, atlas_release)
        accounting_row = {
            "declaredMemberCount": len(dispositions),
            "dispositions": dispositions,
            "membershipMode": "complete",
            "sourceRelease": str(source_release),
        }
        accounting_inputs.append(accounting_row)
        source_accounting_by_release[release.source_release_iri] = accounting_row

    native_count = 0
    remap_evidence_count = 0
    for release in releases:
        relation_ring, _, _ = _ring_dispatch(release.spec.ring)
        for relation in release.relations:
            try:
                source_atlas_release = resource_release[relation.subject]
                target_atlas_release = resource_release[relation.object]
                evidence_record = resource_record[relation.subject]
            except KeyError as error:
                raise ValueError(f"native relation endpoint is outside loaded releases: {relation}") from error
            if source_atlas_release != target_atlas_release:
                raise ValueError(f"native relation crosses releases: {relation}")
            review_method = _review_method_for_assertion(
                ATLAS.NativeRelationAssertion
            )
            if relation.predicate == str(ATLAS.thesaurusRelated):
                (
                    evidence_locator,
                    publisher_relation_digest,
                    evidence_payload,
                ) = _transformed_relation_evidence(relation)
                evidence_record = _add_source_record(
                    asserted,
                    source_release=source_release_nodes[release.source_release_iri],
                    source_locator=evidence_locator,
                    source_digest=publisher_relation_digest,
                    native_payload=evidence_payload,
                    represents_resource=None,
                )
                accounting_row = source_accounting_by_release[
                    release.source_release_iri
                ]
                accounting_row["dispositions"].append(
                    {
                        "atlasResources": [],
                        "reason": (
                            "Evidence-only publisher relation plus deterministic "
                            "SKOS S27-preserving transformation."
                        ),
                        "sourceRecord": str(evidence_record),
                        "status": "excluded",
                    }
                )
                remap_evidence_count += 1
                review_method = _review_method_for_assertion(
                    ATLAS.NativeRelationAssertion,
                    deterministic_transformation=True,
                )
            _add_assertion(
                asserted,
                assertion_type=ATLAS.NativeRelationAssertion,
                ring=relation_ring,
                subject=URIRef(relation.subject),
                predicate=URIRef(relation.predicate),
                obj=URIRef(relation.object),
                source_release=source_atlas_release,
                target_release=target_atlas_release,
                policy=native_policy,
                asserted_at=CREATED_AT,
                evidence_record=evidence_record,
                reviewer=NATIVE_REVIEWER,
                review_method=review_method,
                confidence="1",
            )
            native_count += 1
    expected_native_count = sum(len(release.relations) for release in releases)
    expected_remap_count = sum(
        relation.predicate == str(ATLAS.thesaurusRelated)
        for release in releases
        for relation in release.relations
    )
    if native_count != expected_native_count:
        raise ValueError(
            f"expected {expected_native_count} native assertions; emitted {native_count}"
        )
    if remap_evidence_count != expected_remap_count:
        raise ValueError(
            f"expected {expected_remap_count} remap evidence records; "
            f"emitted {remap_evidence_count}"
        )

    if any(asserted.subjects(RDF.type, ATLAS.MappingAssertion)):
        raise ValueError("source-only Atlas build emitted a MappingAssertion")
    projection = ATLAS_VALIDATE._expected_projection(asserted)
    derived = Graph()
    _finalize_source_accounting_inputs(accounting_inputs)
    represented = sum(
        disposition["status"] == "represented"
        for row in accounting_inputs
        for disposition in row["dispositions"]
    )
    excluded = sum(
        disposition["status"] == "excluded"
        for row in accounting_inputs
        for disposition in row["dispositions"]
    )
    unresolved = sum(
        disposition["status"] == "unresolved"
        for row in accounting_inputs
        for disposition in row["dispositions"]
    )
    accounting = {
        "distributionId": DISTRIBUTION_ID,
        "inputs": accounting_inputs,
        "totals": {
            "excluded": excluded,
            "represented": represented,
            "sourceRecords": represented + excluded + unresolved,
            "sourceReleases": len(accounting_inputs),
            "unresolved": unresolved,
        },
        "type": "AtlasSourceAccounting",
        "version": "3.0",
    }
    return BuildGraphs(
        asserted=asserted,
        projection=projection,
        derived=derived,
        accounting=accounting,
    )


def _counts(graphs: BuildGraphs) -> dict[str, int]:
    asserted = graphs.asserted
    return {
        "derivedRelations": len(
            set(graphs.derived.subjects(RDF.type, ATLAS.DerivedRelation))
        ),
        "labels": len(set(asserted.subjects(RDF.type, SKOSXL.Label))),
        "mappingAssertions": len(
            set(asserted.subjects(RDF.type, ATLAS.MappingAssertion))
        ),
        "nativeRelationAssertions": len(
            set(asserted.subjects(RDF.type, ATLAS.NativeRelationAssertion))
        ),
        "projectedRelations": len(
            set(graphs.projection.subjects(RDF.type, ATLAS.ProjectedRelation))
        ),
        "relationAssertions": sum(
            len(set(asserted.subjects(RDF.type, assertion_type)))
            for assertion_type in ATLAS_VALIDATE.ASSERTION_TYPES
        ),
        "releases": len(set(asserted.subjects(RDF.type, ATLAS.AtlasRelease))),
        "resources": len(
            {
                subject
                for resource_type in ATLAS_VALIDATE.RESOURCE_TYPES
                for subject in asserted.subjects(RDF.type, resource_type)
            }
        ),
        "sourceAssignments": len(
            set(asserted.subjects(RDF.type, ATLAS.SourceAssignment))
        ),
        "sourceRecords": len(set(asserted.subjects(RDF.type, ATLAS.SourceRecord))),
    }


def _production_relation_scope(graphs: BuildGraphs) -> dict[str, Any]:
    """Close the production writer to publisher-source relations only."""

    counts = _counts(graphs)
    scope = {
        "derivedRelations": counts["derivedRelations"],
        "mappingAssertions": counts["mappingAssertions"],
        "mode": "publisherSourceOnly",
    }
    if scope["mappingAssertions"] or scope["derivedRelations"]:
        raise ValueError(
            "source-only Atlas build must contain zero mapping assertions and "
            "zero derived relations"
        )
    return scope


def _dataset_lines(graphs: BuildGraphs) -> Iterable[str]:
    graph_ids = {
        "asserted": URIRef(DISTRIBUTION_ID + ":asserted"),
        "derived": URIRef(DISTRIBUTION_ID + ":derived"),
        "projection": URIRef(DISTRIBUTION_ID + ":projection"),
    }
    for role, graph in (
        ("asserted", graphs.asserted),
        ("projection", graphs.projection),
        ("derived", graphs.derived),
    ):
        graph_id = graph_ids[role]
        for subject, predicate, obj in graph:
            yield ATLAS_VALIDATE.nquads_line(subject, predicate, obj, graph_id) + "\n"


def _merge_sorted_chunks(
    chunks: Sequence[Path],
    directory: Path,
    *,
    fan_in: int,
) -> list[Path]:
    """Bound open files while reducing sorted chunks to one merge frontier."""

    current = list(chunks)
    generation = 0
    while len(current) > fan_in:
        merged: list[Path] = []
        for position in range(0, len(current), fan_in):
            group = current[position : position + fan_in]
            target = directory / f"merge-{generation:03d}-{len(merged):05d}.nq"
            streams = [chunk.open(encoding="utf-8", newline="") for chunk in group]
            try:
                with target.open("w", encoding="utf-8", newline="") as output:
                    output.writelines(heapq.merge(*streams))
            finally:
                for stream in streams:
                    stream.close()
            for chunk in group:
                chunk.unlink()
            merged.append(target)
        current = merged
        generation += 1
    return current


def _write_sorted_lines(
    path: Path,
    lines: Iterable[str],
    *,
    chunk_line_count: int = 50_000,
    merge_fan_in: int = 64,
) -> None:
    """External merge-sort N-Quads without retaining the full dataset in RAM."""

    if chunk_line_count < 1 or merge_fan_in < 2:
        raise ValueError("external sort bounds must be positive")

    with tempfile.TemporaryDirectory(prefix="atlas3-sort-", dir=path.parent) as raw_temp:
        temp = Path(raw_temp)
        chunks: list[Path] = []
        buffered: list[str] = []
        for line in lines:
            buffered.append(line)
            if len(buffered) < chunk_line_count:
                continue
            buffered.sort()
            chunk = temp / f"chunk-{len(chunks):05d}.nq"
            chunk.write_text("".join(buffered), encoding="utf-8", newline="")
            chunks.append(chunk)
            buffered.clear()
        if buffered or not chunks:
            buffered.sort()
            chunk = temp / f"chunk-{len(chunks):05d}.nq"
            chunk.write_text("".join(buffered), encoding="utf-8", newline="")
            chunks.append(chunk)

        chunks = _merge_sorted_chunks(chunks, temp, fan_in=merge_fan_in)
        streams = [chunk.open(encoding="utf-8", newline="") for chunk in chunks]
        try:
            with path.open("w", encoding="utf-8", newline="") as output:
                output.writelines(heapq.merge(*streams))
        finally:
            for stream in streams:
                stream.close()


def _file_member(path: Path, *, role: str, media_type: str) -> dict[str, Any]:
    return {
        "byteLength": path.stat().st_size,
        "digest": _sha256_file(path),
        "mediaType": media_type,
        "path": path.name,
        "role": role,
    }


def _streaming_structural_checks(
    output: Path,
    *,
    manifest: Mapping[str, Any],
) -> dict[str, Any]:
    dataset_path = output / "atlas.nq"
    graph_counts = {row["id"]: 0 for row in manifest["graphs"]}
    graph_suffixes = {
        (" <" + graph_id + "> .\n").encode("utf-8"): graph_id
        for graph_id in graph_counts
    }
    previous: bytes | None = None
    line_count = 0
    skosxl_literal_form_count = 0
    projected_skos_label_count = 0
    skosxl_literal_form_predicate = f"<{SKOSXL.literalForm}>".encode()
    projected_skos_label_predicates = {
        f"<{SKOS.prefLabel}>".encode(),
        f"<{SKOS.altLabel}>".encode(),
        f"<{SKOS.hiddenLabel}>".encode(),
    }
    english_label_predicates = {
        skosxl_literal_form_predicate,
        *projected_skos_label_predicates,
    }
    with dataset_path.open("rb") as stream:
        for line in stream:
            line_count += 1
            if not line.endswith(b"\n") or b"\r" in line or line.strip() != line[:-1]:
                raise ValueError(f"atlas.nq line {line_count} is not canonical LF text")
            if previous is not None and line <= previous:
                raise ValueError(f"atlas.nq line {line_count} is not sorted and unique")
            previous = line
            matches = [
                graph_id for suffix, graph_id in graph_suffixes.items() if line.endswith(suffix)
            ]
            if len(matches) != 1:
                raise ValueError(f"atlas.nq line {line_count} has an undeclared graph")
            graph_counts[matches[0]] += 1
            if b'Z"^^<http://www.w3.org/2001/XMLSchema#dateTime>' in line:
                raise ValueError(
                    f"atlas.nq line {line_count} contains a non-round-trippable UTC datetime"
                )
            _, predicate, object_and_graph = line.split(b" ", 2)
            if predicate not in english_label_predicates:
                continue
            object_end = object_and_graph.rfind(b" <")
            if object_end < 0:
                raise ValueError(f"atlas.nq line {line_count} has no named graph")
            object_term = object_and_graph[:object_end]
            if not object_term.endswith(b"@en"):
                raise ValueError(
                    f"atlas.nq line {line_count} has a non-English normalized label"
                )
            if predicate == skosxl_literal_form_predicate:
                skosxl_literal_form_count += 1
            else:
                projected_skos_label_count += 1
    expected_graph_counts = {
        row["id"]: row["quadCount"] for row in manifest["graphs"]
    }
    if graph_counts != expected_graph_counts:
        raise ValueError(
            f"serialized graph counts differ: {graph_counts} != {expected_graph_counts}"
        )
    expected_label_count = manifest["counts"]["labels"]
    if (
        skosxl_literal_form_count != expected_label_count
        or projected_skos_label_count != expected_label_count
    ):
        raise ValueError(
            "serialized English label counts differ: "
            f"skosxl={skosxl_literal_form_count}, "
            f"projection={projected_skos_label_count}, "
            f"expected={expected_label_count}"
        )
    for member in manifest["members"]:
        path = output / member["path"]
        if path.stat().st_size != member["byteLength"] or _sha256_file(path) != member[
            "digest"
        ]:
            raise ValueError(f"serialized member differs from manifest: {path.name}")
    return {
        "canonicalRenderer": "bindings/atlas/3.0/tools/rdf_canonical.py",
        "checks": [
            "canonical LF text",
            "sorted unique N-Quads lines",
            "declared graph closure and exact quad counts",
            "manifest member lengths and digests",
            "round-trippable xsd:dateTime spelling",
            "English-only SKOS-XL and projected SKOS label literals",
        ],
        "graphQuadCounts": graph_counts,
        "lineCount": line_count,
        "promotionRequiresFullSemanticValidation": True,
        "projectedSkosLabelCount": projected_skos_label_count,
        "skosxlLiteralFormCount": skosxl_literal_form_count,
        "status": "passed",
    }


def _write_candidate_distribution(
    output: Path,
    graphs: BuildGraphs,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Write and fully validate a candidate that is not yet publishable."""

    output.mkdir(parents=True, exist_ok=True)
    allowed = {
        "atlas-acceptance.json",
        "atlas-manifest.json",
        "atlas-source-accounting.json",
        "atlas.nq",
    }
    extras = sorted(path.name for path in output.iterdir() if path.name not in allowed)
    if extras:
        raise FileExistsError(f"distribution contains unexpected existing files: {extras}")

    dataset_path = output / "atlas.nq"
    accounting_path = output / "atlas-source-accounting.json"
    acceptance_path = output / "atlas-acceptance.json"
    manifest_path = output / "atlas-manifest.json"
    _write_sorted_lines(dataset_path, _dataset_lines(graphs))
    accounting_path.write_bytes(
        ATLAS_VALIDATE.canonical_json_bytes(graphs.accounting)
    )

    binding_digests = ATLAS_VALIDATE._binding_digests()
    acceptance_inputs = {
        "atlasDigest": _sha256_file(dataset_path),
        **binding_digests,
        "sourceAccountingDigest": _sha256_file(accounting_path),
    }
    validator_identity = {"name": "refspec-atlas-conformance", "version": "3.0"}
    acceptance = {
        "distributionId": DISTRIBUTION_ID,
        "evaluatedAt": CREATED_AT,
        "gates": [
            {
                "evidenceDigest": ATLAS_VALIDATE.acceptance_gate_evidence_digest(
                    gate,
                    inputs=acceptance_inputs,
                    validator=validator_identity,
                ),
                "name": gate,
                "status": "passed",
            }
            for gate in sorted(ATLAS_VALIDATE.REQUIRED_GATES)
        ],
        "inputs": acceptance_inputs,
        "type": "AtlasAcceptance",
        "validator": validator_identity,
        "verdict": "passed",
        "version": "3.0",
    }
    acceptance_path.write_bytes(ATLAS_VALIDATE.canonical_json_bytes(acceptance))

    graph_descriptors = [
        {
            "id": DISTRIBUTION_ID + ":" + role,
            "quadCount": len(graph),
            "role": role,
        }
        for role, graph in (
            ("asserted", graphs.asserted),
            ("projection", graphs.projection),
            ("derived", graphs.derived),
        )
    ]
    manifest = {
        "binding": {
            "validatorVersion": "3.0",
            "version": "3.0",
            **binding_digests,
        },
        "counts": _counts(graphs),
        "createdAt": CREATED_AT,
        "distributionId": DISTRIBUTION_ID,
        "format": "refspec-atlas-nquads-3.0",
        "graphs": graph_descriptors,
        "members": [
            _file_member(
                dataset_path,
                role="atlasDataset",
                media_type="application/n-quads",
            ),
            _file_member(
                accounting_path,
                role="sourceAccounting",
                media_type="application/json",
            ),
            _file_member(
                acceptance_path,
                role="acceptance",
                media_type="application/json",
            ),
        ],
        "schemaVersion": "3.0",
        "type": "AtlasManifest",
    }
    manifest["canonicalPayloadDigest"] = ATLAS_VALIDATE.canonical_sha256(
        manifest, terminal_lf=False
    )
    manifest_path.write_bytes(ATLAS_VALIDATE.canonical_json_bytes(manifest))

    structural = _streaming_structural_checks(output, manifest=manifest)
    observed_files = {path.name for path in output.iterdir() if path.is_file()}
    if observed_files != allowed:
        raise ValueError(
            f"distribution member closure differs: {sorted(observed_files)}"
        )
    graphs.release()
    gc.collect()
    semantic = ATLAS_VALIDATE.validate_distribution(output)
    return (
        {
            "semantic": semantic,
            "status": "passed",
            "structural": structural,
        },
        manifest,
    )


def _generation_report_path(output: Path) -> Path:
    return output.parent / "generation-report.json"


def _generation_report_distribution_path(output: Path) -> str:
    """Name the distribution relative to its adjacent generation report."""

    if output == output.parent or not output.name:
        raise ValueError(f"distribution output has no relative report path: {output}")
    return output.name


def _promote_validated_distribution(
    candidate: Path,
    output: Path,
    *,
    temporary_root: Path,
) -> None:
    """Replace the visible distribution only after its candidate validated."""

    if output == output.parent:
        raise ValueError(f"refusing to replace a filesystem root: {output}")
    if output.is_symlink() or (output.exists() and not output.is_dir()):
        raise FileExistsError(f"distribution path is not a real directory: {output}")
    previous = temporary_root / "previous-distribution"
    if output.exists():
        output.rename(previous)
    try:
        candidate.rename(output)
    except BaseException:
        if previous.exists() and not output.exists():
            previous.rename(output)
        raise


def _write_distribution(
    output: Path,
    graphs: BuildGraphs,
    *,
    generation_report: Mapping[str, Any],
) -> dict[str, Any]:
    """Validate in a sibling temporary directory, then promote the result."""

    output.parent.mkdir(parents=True, exist_ok=True)
    relation_scope = _production_relation_scope(graphs)
    report_distribution_path = _generation_report_distribution_path(output)
    with tempfile.TemporaryDirectory(
        prefix=f".{output.name}.candidate-",
        dir=output.parent,
    ) as raw_temporary_root:
        temporary_root = Path(raw_temporary_root)
        candidate = temporary_root / "distribution"
        result, manifest = _write_candidate_distribution(candidate, graphs)
        report = {
            **_plain(generation_report),
            "distribution": {
                "id": DISTRIBUTION_ID,
                "manifestDigest": _sha256_file(candidate / "atlas-manifest.json"),
                "path": report_distribution_path,
            },
            "productionRelationScope": relation_scope,
            "validation": result,
        }
        candidate_report = temporary_root / "generation-report.json"
        candidate_report.write_bytes(ATLAS_VALIDATE.canonical_json_bytes(report))
        if manifest["distributionId"] != DISTRIBUTION_ID:
            raise ValueError("candidate manifest distribution identity differs")
        report_path = _generation_report_path(output)
        if report_path.exists() and not (
            report_path.is_file() or report_path.is_symlink()
        ):
            raise FileExistsError(
                f"generation report path is not replaceable: {report_path}"
            )
        _promote_validated_distribution(
            candidate,
            output,
            temporary_root=temporary_root,
        )
        try:
            candidate_report.replace(report_path)
        except BaseException:
            failed_candidate = temporary_root / "validated-distribution"
            output.rename(failed_candidate)
            previous = temporary_root / "previous-distribution"
            if previous.exists():
                previous.rename(output)
            raise
    return result


def _source_input_pins(source: SourceSpec) -> tuple[RegistryInputPin, ...]:
    if source.input_pins:
        return source.input_pins
    byte_length = source.path.stat().st_size if source.path.is_file() else -1
    return (
        RegistryInputPin(
            path=source.path,
            logical_path=source.logical_path,
            sha256=source.expected_digest,
            byte_length=byte_length,
            source_iri=(
                "urn:ref:source-artifact:"
                + source.expected_digest.removeprefix("sha256:")
            ),
        ),
    )


def verify_inputs(
    releases: tuple[LoadedRelease, ...] | None = None,
) -> dict[str, Any]:
    """Fail closed unless every original input named by the build is present."""

    _verify_pinned_file(
        REGISTRY_DESCRIPTORS,
        logical_path=REGISTRY_DESCRIPTORS_LOGICAL_PATH,
        expected_digest=REGISTRY_DESCRIPTORS_EXPECTED_DIGEST,
    )
    sources = (
        SOURCE_SPECS
        if releases is None
        else tuple(release.spec for release in releases)
    )
    verified_pins: dict[str, tuple[str, int]] = {}
    for source in sources:
        for pin in _source_input_pins(source):
            identity = (pin.sha256, pin.byte_length)
            previous = verified_pins.get(pin.logical_path)
            if previous is not None:
                if previous != identity:
                    raise ValueError(
                        f"pinned input identity conflicts for {pin.logical_path}"
                    )
                continue
            _verify_pinned_file(
                pin.path,
                logical_path=pin.logical_path,
                expected_digest=pin.sha256,
            )
            if pin.path.stat().st_size != pin.byte_length:
                raise ValueError(
                    f"pinned input byte length differs for {pin.logical_path}"
                )
            verified_pins[pin.logical_path] = identity
    registry = Dataset(default_union=True)
    registry.parse(REGISTRY_DESCRIPTORS, format="nquads")
    descriptors = {
        subject
        for subject in registry.subjects(
            RDF.type,
            ATLAS.ResourceScheme,
        )
    }
    if len(descriptors) != 86:
        raise ValueError(f"expected 86 registry descriptors; found {len(descriptors)}")

    return {
        "expectedResources": sum(source.expected_resources for source in sources),
        "registryDescriptors": len(descriptors),
        "registryDescriptorsPin": {
            "digest": REGISTRY_DESCRIPTORS_EXPECTED_DIGEST,
            "path": REGISTRY_DESCRIPTORS_LOGICAL_PATH,
        },
        "sources": [
            {
                "expectedResources": source.expected_resources,
                "expectedRelations": source.expected_relations,
                "inputRole": (
                    "registrySource"
                    if source.kind == "registryRelease"
                    else "upstreamManagedRelease"
                ),
                "key": source.key,
                "kind": source.kind,
                "path": source.logical_path,
                "inputs": [
                    {
                        "byteLength": pin.byte_length,
                        "path": pin.logical_path,
                        "role": pin.role,
                        "sha256": pin.sha256,
                        "sourceIri": pin.source_iri,
                    }
                    for pin in _source_input_pins(source)
                ],
                "resourceId": source.resource_id,
                "scope": source.scope,
                "sourceModule": source.source_module,
                "sha256": source.expected_digest,
                "usesPriorAtlasGraph": False,
            }
            for source in sources
        ],
    }


def build_distribution(output: Path) -> None:
    """Build, validate, and atomically promote the Atlas 3 distribution."""

    output.parent.mkdir(parents=True, exist_ok=True)
    releases = load_releases()
    inventory = verify_inputs(releases)
    english_only_scan = _english_only_scan(releases)
    dropped_label_count = sum(release.dropped_label_count for release in releases)
    observed_counts = {
        "labels": english_only_scan["emittedLabels"],
        "nativeRelations": sum(len(release.relations) for release in releases),
        "resources": sum(len(release.resources) for release in releases),
    }
    expected_counts = {
        "nativeRelations": sum(
            release.spec.expected_relations for release in releases
        ),
        "resources": sum(release.spec.expected_resources for release in releases),
    }
    if {key: observed_counts[key] for key in expected_counts} != expected_counts:
        raise ValueError(
            f"direct source counts differ: expected={expected_counts}, actual={observed_counts}"
        )
    graphs = _build_graphs(releases)
    result = _write_distribution(
        output,
        graphs,
        generation_report={
            "createdAt": CREATED_AT,
            "directSourceCounts": observed_counts,
            "droppedLabelCount": dropped_label_count,
            "retainedEnglishLabelCount": observed_counts["labels"],
            "sourceLabelCountBeforeLanguageFilter": (
                observed_counts["labels"] + dropped_label_count
            ),
            "englishOnlyPolicy": {
                "atlasLabelLanguage": "en",
                "multilingualLabelTextInRdf": "prohibited",
                "rawMultilingualSources": "externalByExactLocatorAndDigest",
            },
            "englishOnlyScan": english_only_scan,
            "inputInventory": inventory,
            "sourceReleases": [
                {
                    "atlasRelease": release.atlas_release_iri,
                    "key": release.spec.key,
                    "metadata": _plain(release.metadata),
                    "nativeRelations": len(release.relations),
                    "resourceId": release.spec.resource_id,
                    "resources": len(release.resources),
                    "scope": release.spec.scope,
                    "sourceRelease": release.source_release_iri,
                }
                for release in releases
            ],
            "type": "AtlasGenerationReport",
            "version": "3.0-development",
        },
    )
    print(json.dumps(result, indent=2, sort_keys=True))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--check-inputs",
        action="store_true",
        help="verify and report all direct inputs without writing a distribution",
    )
    args = parser.parse_args()
    if args.check_inputs:
        releases = load_releases()
        print(json.dumps(verify_inputs(releases), indent=2, sort_keys=True))
        return 0
    build_distribution(args.output.resolve())
    print(args.output.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
