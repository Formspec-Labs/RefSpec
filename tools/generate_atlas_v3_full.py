"""Generate the full English Atlas 3.0 distribution from pinned registry data.

The generator runs the RefSpec registry parsers over every supported complete
release or explicitly bounded capture whose exact bytes are available locally.
It preserves publisher label roles, authority-scoped identifiers, globally
reusable document identities, semantic rings, direct authored relations, and
release-level provenance. It writes compressed source-release packs under one
digest-pinned root manifest; projection and local explorer indexes remain
optional reproducible views, so generation requires no database service. It
validates its normalized rows and fixed constructors against an exact pinned
compiled SHACL profile; independent consumers still validate the serialized
RDF normally. It never consumes an Atlas 1.x or Atlas 2.x graph, and it never
imports the archived generated mapping pairs under ``research/evidence``.
"""

from __future__ import annotations

import argparse
import dataclasses
import hashlib
import heapq
import importlib.util
import json
import re
import sys
import tempfile
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
from contextlib import ExitStack
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from types import MappingProxyType
from typing import Any, TextIO
from typing import Literal as TypeLiteral

try:  # Python 3.14+
    from compression import zstd
except ImportError:  # pragma: no cover - exercised on supported Python 3.10-3.13
    from backports import zstd

from rdflib import Dataset, Graph, Literal, URIRef
from rdflib.namespace import DCTERMS, PROV, RDF, SKOS, XSD

from refspec.atlas.v3_source_data import (
    RegistryCrossRingRelation,
    RegistryIdentifier,
    RegistryInputPin,
    RegistryRelease,
)
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
DEFAULT_OUTPUT = ROOT / "output" / "atlas-3.0-full-2026-08-06" / "distribution"
SPICY_REGS_ROOT = ROOT.parent
CREATED_AT = "2026-08-06T08:45:00+00:00"
DISTRIBUTION_ID = "urn:ref:atlas:distribution:3.0-full-development:2026-08-06"
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
_PACK_PATH_TOKEN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_PACK_PATH_UNSAFE = re.compile(r"[^a-z0-9]+")
_PACK_LARGE_RELEASE_RESOURCE_THRESHOLD = 50_000
_PACK_LARGE_RELEASE_BUCKETS = 16
_PACK_ZSTD_LEVEL = 1
_COMPILED_PRODUCER_PROFILE = "atlas-3-source-only-compiled-shacl-v1"
_COMPILED_PRODUCER_IMPLEMENTATION_DIGEST = "sha256:d595162942030934a8f140fca03588a8cad01adf585b5af641207356bd542eee"
_COMPILED_PRODUCER_BINDING_PINS = MappingProxyType(
    {
        "acceptanceSchemaDigest": (
            "sha256:1057490a6bf3422bc8477ad215715ff63d92a407ffa47526c48cd942efab7617"
        ),
        "bindingBundleDigest": (
            "sha256:51175ad57bbcfafe0c9d7fbb5ce59c764ff0db6c65b83c45c5de52b7db13a8c0"
        ),
        "manifestSchemaDigest": (
            "sha256:f166c1bd8bf24acccd1de39310cbcbf4d56fc4a79a0f9f2810df5e5cafa0dd7f"
        ),
        "ontologyDigest": (
            "sha256:8741c40241aa9918977d2b7eb4cde4b1e235af64ec05afde56e28654e278bbef"
        ),
        "shapesDigest": (
            "sha256:e26b339c9d2f8bcb61aca2ba5f240577ee113d504a2dd044440987cdde574831"
        ),
        "sourceAccountingSchemaDigest": (
            "sha256:af6bca95147fc6bae1418bf2034ed53310e08691b5a299aa6465a3f8894e7bb2"
        ),
    }
)
_GENERATED_CARRIER_IRI_PREFIXES = (
    "urn:ref:atlas-assertion:",
    "urn:ref:atlas-evidence:",
    "urn:ref:atlas-identifier:",
    "urn:ref:atlas-label:",
    "urn:ref:atlas-policy:",
    "urn:ref:atlas-source-record:",
)
_TRANSFORMED_RELATION_ACCOUNTING_REASON = (
    "Evidence-only publisher relation plus deterministic "
    "SKOS S27-preserving transformation."
)
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
    expected_cross_ring_relations: int = 0
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
    identifiers: Sequence[RegistryIdentifier] = ()


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
    cross_ring_relations: Sequence[RegistryCrossRingRelation] = ()
    dropped_label_count: int = 0
    metadata: Mapping[str, Any] = dataclasses.field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ReleasePackPlan:
    """Small release identity retained after normalized source rows are freed."""

    key: str
    source_release_iri: str
    atlas_release_iri: str
    ring: str
    resource_count: int


@dataclass(frozen=True, slots=True)
class PackWriteReceipt:
    """Exact content and transport facts captured while writing one pack."""

    content_byte_length: int
    content_digest: str
    content_quad_count: int
    transport_byte_length: int
    transport_digest: str


@dataclass(frozen=True, slots=True)
class CompiledSourceValidationReceipt:
    """Compact-row proof for the pinned source-only producer profile."""

    binding_profile: Mapping[str, str]
    english_only_scan: Mapping[str, Any]
    expected_counts: Mapping[str, int]
    source_release_count: int


@dataclass(slots=True)
class BuildGraphs:
    asserted: Graph
    projection: Graph
    derived: Graph
    accounting: dict[str, Any]
    sealed_asserted_revision: int | None = None

    def release(self) -> None:
        """Release the large in-memory RDF stores after their bytes are sealed."""

        self.asserted.close()
        self.projection.close()
        self.derived.close()
        self.asserted = _new_build_graph()
        self.projection = _new_build_graph()
        self.derived = _new_build_graph()
        self.accounting = {}
        self.sealed_asserted_revision = None


class _MutationTrackedGraph(Graph):
    """An RDFLib graph with a cheap in-process mutation receipt."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.revision = 0

    def add(self, triple: tuple[Any, Any, Any]) -> _MutationTrackedGraph:
        if triple not in self:
            super().add(triple)
            self.revision += 1
        return self

    def remove(self, triple: tuple[Any, Any, Any]) -> _MutationTrackedGraph:
        removed = tuple(self.triples(triple))
        if removed:
            super().remove(triple)
            self.revision += len(removed)
        return self


def _new_build_graph() -> _MutationTrackedGraph:
    """Create a single-context graph without rdflib's redundant context index."""

    return _MutationTrackedGraph(store="SimpleMemory")


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
        scope="completeCapture",
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
        scope="completeCapture",
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
        scope="completeCapture",
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
    "sha256:af705a3473488f664460a33b7bb57237140c4e1a5ccb7105182ba7394218112c"
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


def _omit_absent_fields(value: Mapping[str, Any]) -> dict[str, Any]:
    """Omit optional top-level fields instead of serializing JSON null."""

    return {str(key): item for key, item in value.items() if item is not None}


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
        "crossRingRelations": len(release.cross_ring_relations),
        "relations": len(release.relations),
        "resources": len(release.resources),
    }
    expected = {
        "crossRingRelations": release.spec.expected_cross_ring_relations,
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
        expected_cross_ring_relations=release.expected_cross_ring_relations,
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
            cross_ring_relations=release.cross_ring_relations,
            dropped_label_count=release.dropped_label_count,
            metadata=release.metadata,
        )
    )


def load_releases() -> tuple[LoadedRelease, ...]:
    from refspec.atlas.v3_registry_codes import load_registry_code_releases
    from refspec.atlas.v3_registry_documents import load_registry_document_releases
    from refspec.atlas.v3_registry_large import load_large_registry_releases
    from refspec.atlas.v3_registry_nonemitters import (
        load_registry_nonemitter_releases,
    )
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
        *load_registry_document_releases(ROOT),
        *load_registry_nonemitter_releases(ROOT),
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
        source_descriptor = URIRef(
            "urn:ref:atlas-source-descriptor:" + release.resource_id
        )
        if (source_descriptor, RDF.type, ATLAS.RegistrySource) not in descriptors:
            raise ValueError(
                f"{release.key} names unknown registry source {release.resource_id!r}"
            )
        scheme = URIRef(release.scheme_iri)
        scheme_prefix = "urn:ref:atlas-resource-scheme:" + release.resource_id
        if str(scheme) != scheme_prefix and not str(scheme).startswith(scheme_prefix + ":"):
            raise ValueError(
                f"{release.key} scheme is outside its registry source namespace: {scheme}"
            )
        if (scheme, RDF.type, ATLAS.ResourceScheme) in descriptors:
            if (scheme, ATLAS.sourceDescriptor, source_descriptor) not in descriptors:
                raise ValueError(f"{release.key} scheme differs from its source descriptor")
            if (scheme, ATLAS.resourceProfile, ATLAS[release.profile]) not in descriptors:
                raise ValueError(
                    f"{release.key} profile {release.profile!r} differs from its descriptor"
                )
            if (scheme, ATLAS.supportedRing, ATLAS[release.ring]) not in descriptors:
                raise ValueError(
                    f"{release.key} ring {release.ring!r} differs from its descriptor"
                )
        else:
            policies = ATLAS_VALIDATE._profile_policies()
            policy = policies.get(ATLAS[release.profile])
            if policy is None or release.ring not in policy["applicableSemanticRings"]:
                raise ValueError(
                    f"{release.key} child scheme profile/ring is not allowed: "
                    f"{release.profile}/{release.ring}"
                )
        if not any(
            isinstance(row, Mapping)
            and row.get("resourceId") == release.resource_id
            and row.get("sourceModule") == release.source_module
            for row in index_rows
        ):
            raise ValueError(
                f"{release.key} source module is absent from the Atlas index"
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
    node, native_payload_bytes = _source_record_constructor(
        source_release=source_release,
        source_locator=source_locator,
        source_digest=source_digest,
        native_payload=native_payload,
        language_map_fields=language_map_fields,
    )
    graph.add((node, RDF.type, ATLAS.SourceRecord))
    graph.add((node, ATLAS.inSourceRelease, source_release))
    graph.add((node, ATLAS.sourceDigest, Literal(source_digest)))
    graph.add((node, ATLAS.sourceLocator, source_locator))
    graph.add(
        (
            node,
            ATLAS.nativePayload,
            Literal(
                native_payload_bytes.decode("utf-8"),
                datatype=RDF.JSON,
                normalize=False,
            ),
        )
    )
    if represents_resource is not None:
        graph.add((node, ATLAS.representsResource, represents_resource))
    _add_content_digest(graph, node)
    return node


def _source_record_constructor(
    *,
    source_release: URIRef,
    source_locator: URIRef,
    source_digest: str,
    native_payload: Any,
    language_map_fields: frozenset[str] = frozenset(),
) -> tuple[URIRef, bytes]:
    """Validate and receipt the deterministic SourceRecord constructor."""

    _, _, language_violations = _audit_english_language_content(
        native_payload,
        language_map_fields=language_map_fields,
    )
    if language_violations:
        raise ValueError(
            "SourceRecord native payload is not English-only: "
            + ", ".join(language_violations[:5])
        )
    plain_payload = _plain(native_payload)
    native_payload_bytes = ATLAS_VALIDATE.canonical_native_json_bytes(
        plain_payload
    )
    basis = {
        "nativePayloadDigest": (
            "sha256:" + hashlib.sha256(native_payload_bytes).hexdigest()
        ),
        "sourceDigest": source_digest,
        "sourceLocator": str(source_locator),
        "sourceRelease": str(source_release),
    }
    node = _node_iri("atlas-source-record", basis)
    return node, native_payload_bytes


def _add_identifier(
    graph: Graph,
    *,
    identifier_row: RegistryIdentifier,
    resource: URIRef,
    source_record: URIRef,
) -> URIRef:
    """Add one source-backed identifier under an identifier-authority scheme."""

    scheme = URIRef(identifier_row.scheme_iri)
    profiles = set(graph.objects(scheme, ATLAS.resourceProfile))
    if (
        (scheme, RDF.type, ATLAS.ResourceScheme) not in graph
        or profiles != {ATLAS.identifierScheme}
    ):
        raise ValueError(
            "identifier scheme must be an atlas:ResourceScheme with the "
            f"atlas:identifierScheme profile: {scheme}"
        )
    identifier = _node_iri(
        "atlas-identifier",
        {
            "identifierScheme": str(scheme),
            "identifierValue": identifier_row.value,
            "identifies": str(resource),
            "sourcePath": identifier_row.source_path,
            "sourceRecord": str(source_record),
        },
    )
    graph.add((identifier, RDF.type, ATLAS.Identifier))
    graph.add(
        (
            identifier,
            ATLAS.identifierValue,
            Literal(identifier_row.value, datatype=XSD.string),
        )
    )
    graph.add((identifier, ATLAS.identifierScheme, scheme))
    graph.add((identifier, ATLAS.identifies, resource))
    graph.add((identifier, ATLAS.sourceRecord, source_record))
    _add_content_digest(graph, identifier)
    return identifier


def _review_method_for_assertion(
    assertion_type: URIRef,
    *,
    deterministic_transformation: bool = False,
) -> URIRef:
    """Select the narrow review method supported by an assertion's provenance."""

    if assertion_type in {
        ATLAS.CrossRingRelationAssertion,
        ATLAS.NativeRelationAssertion,
        ATLAS.SourceAssignment,
    }:
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
    ring: URIRef | None,
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
    source_ring: URIRef | None = None,
    target_ring: URIRef | None = None,
) -> URIRef:
    policy_digest = graph.value(policy, ATLAS.contentDigest)
    if not isinstance(policy_digest, Literal):
        raise TypeError(f"policy has no content digest: {policy}")
    basis: dict[str, str] = {
        "object": str(obj),
        "policy": str(policy),
        "policyContentDigest": str(policy_digest),
        "predicate": str(predicate),
        "sourceRelease": str(source_release),
        "subject": str(subject),
        "targetRelease": str(target_release),
        "type": str(assertion_type),
    }
    if assertion_type == ATLAS.CrossRingRelationAssertion:
        if ring is not None or source_ring is None or target_ring is None:
            raise ValueError(
                "cross-ring assertions require sourceRing and targetRing only"
            )
        if source_ring == target_ring:
            raise ValueError("cross-ring assertion endpoints use one ring")
        basis["sourceRing"] = str(source_ring)
        basis["targetRing"] = str(target_ring)
    else:
        if ring is None or source_ring is not None or target_ring is not None:
            raise ValueError(
                "same-ring assertions require one semanticRing only"
            )
        basis["semanticRing"] = str(ring)
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
    if assertion_type == ATLAS.CrossRingRelationAssertion:
        graph.add((assertion, ATLAS.sourceRing, source_ring))
        graph.add((assertion, ATLAS.targetRing, target_ring))
    else:
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

    evidence_source_digest = graph.value(
        evidence_record,
        ATLAS.contentDigest,
    )
    if not isinstance(evidence_source_digest, Literal):
        raise TypeError(
            f"evidence source record {evidence_record} lacks one content digest"
        )
    evidence_facts: list[tuple[URIRef, object]] = [
        (RDF.type, ATLAS.EvidenceBinding),
        (ATLAS.bindsAssertion, assertion),
        (ATLAS.evidenceSourceRecord, evidence_record),
        (ATLAS.evidenceSourceDigest, evidence_source_digest),
        (ATLAS.reviewedBy, reviewer),
        (ATLAS.decisionStatus, ATLAS.approved),
        (ATLAS.reviewMethod, review_method),
        (
            ATLAS.decidedAt,
            Literal(
                _rdf_datetime(asserted_at),
                datatype=XSD.dateTime,
                normalize=False,
            ),
        ),
    ]
    if confidence is not None:
        evidence_facts.append(
            (
                ATLAS.confidence,
                Literal(confidence, datatype=XSD.decimal, normalize=False),
            )
        )
    evidence_digest = ATLAS_VALIDATE._outgoing_facts_digest(evidence_facts)
    evidence = URIRef(
        "urn:ref:atlas-evidence:" + evidence_digest.removeprefix("sha256:")
    )
    for evidence_predicate, evidence_object in evidence_facts:
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
    graph = _new_build_graph()
    for subject, predicate, obj, _ in dataset.quads((None, None, None, None)):
        graph.add((subject, predicate, obj))
    return graph


def _ensure_release_schemes(
    graph: Graph,
    releases: Sequence[LoadedRelease],
) -> None:
    """Add source-owned child schemes required by mixed registry sources."""

    grouped: dict[URIRef, list[LoadedRelease]] = {}
    for release in releases:
        grouped.setdefault(URIRef(release.scheme_iri), []).append(release)
    policies = ATLAS_VALIDATE._profile_policies()
    for scheme, scheme_releases in sorted(grouped.items(), key=lambda row: str(row[0])):
        profiles = {release.spec.profile for release in scheme_releases}
        resource_ids = {release.spec.resource_id for release in scheme_releases}
        rings = {release.spec.ring for release in scheme_releases}
        if len(profiles) != 1 or len(resource_ids) != 1:
            raise ValueError(f"registry child scheme has inconsistent ownership: {scheme}")
        profile_name = next(iter(profiles))
        resource_id = next(iter(resource_ids))
        profile = ATLAS[profile_name]
        policy = policies.get(profile)
        if policy is None or not rings <= set(policy["applicableSemanticRings"]):
            raise ValueError(f"registry child scheme has unsupported rings: {scheme}")
        if (scheme, RDF.type, ATLAS.ResourceScheme) in graph:
            if set(graph.objects(scheme, ATLAS.resourceProfile)) != {profile}:
                raise ValueError(f"registry scheme profile differs across releases: {scheme}")
            if not {ATLAS[ring] for ring in rings} <= set(
                graph.objects(scheme, ATLAS.supportedRing)
            ):
                raise ValueError(f"registry scheme omits a release ring: {scheme}")
            if "subject" in rings and (scheme, RDF.type, SKOS.ConceptScheme) not in graph:
                raise ValueError(
                    f"registry subject scheme is not a SKOS ConceptScheme: {scheme}"
                )
            continue
        if resource_id is None:
            raise ValueError(f"registry child scheme has no catalog source owner: {scheme}")
        source = URIRef("urn:ref:atlas-source-descriptor:" + resource_id)
        if (source, RDF.type, ATLAS.RegistrySource) not in graph:
            raise ValueError(f"registry child scheme names unknown source: {source}")
        graph.add((scheme, RDF.type, ATLAS.ResourceScheme))
        if profile == ATLAS.conceptScheme or "subject" in rings:
            graph.add((scheme, RDF.type, SKOS.ConceptScheme))
        graph.add((scheme, DCTERMS.identifier, Literal(str(scheme))))
        graph.add((scheme, ATLAS.resourceProfile, profile))
        graph.add((scheme, ATLAS.sourceDescriptor, source))
        for ring in sorted(rings):
            graph.add((scheme, ATLAS.supportedRing, ATLAS[ring]))
        _add_content_digest(graph, scheme)


def _expected_projection_graph(asserted: Graph) -> Graph:
    """Build the validator-defined projection in the lean single-context store."""

    projection = _new_build_graph()
    supported = ATLAS_VALIDATE._validate_assertions(asserted)
    for triple in ATLAS_VALIDATE._expected_projection_triples(asserted, supported):
        projection.add(triple)
    return projection


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
        for relation in (*release.relations, *release.cross_ring_relations):
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


def _require_absolute_iri(value: object, *, context: str) -> str:
    if (
        not isinstance(value, str)
        or ATLAS_VALIDATE.ABSOLUTE_IRI_RE.fullmatch(value) is None
    ):
        raise ValueError(f"{context} must be an absolute IRI")
    return value


def _compiled_producer_implementation_digest() -> str:
    """Digest this trusted writer while excluding only its self pin.

    The generator contains the compact-row checks, graph constructors,
    canonical serializers, pack writer, and proof assembly. Pinning the whole
    file fails closed when any part of that transitive local recipe changes.
    Binding-owned renderers, schemas, policies, and descriptors are pinned
    separately by ``bindingBundleDigest``.
    """

    raw = Path(__file__).read_bytes()
    expected = _COMPILED_PRODUCER_IMPLEMENTATION_DIGEST.encode("ascii")
    needle = (
        b'_COMPILED_PRODUCER_IMPLEMENTATION_DIGEST = "'
        + expected
        + b'"'
    )
    replacement = b'_COMPILED_PRODUCER_IMPLEMENTATION_DIGEST = "<self>"'
    if raw.count(needle) != 1:
        raise ValueError("compiled producer implementation self pin is ambiguous")
    normalized = raw.replace(needle, replacement, 1)
    return "sha256:" + hashlib.sha256(normalized).hexdigest()


def _validate_compiled_binding_profile() -> dict[str, str]:
    """Pin and meta-validate the exact SHACL profile compiled below."""

    observed_digests = ATLAS_VALIDATE._binding_digests()
    observed = {
        field: observed_digests[field]
        for field in _COMPILED_PRODUCER_BINDING_PINS
    }
    expected = dict(_COMPILED_PRODUCER_BINDING_PINS)
    if observed != expected:
        raise ValueError(
            "compiled producer validation profile drifted; review the ontology and "
            f"SHACL changes and repin {_COMPILED_PRODUCER_PROFILE}: "
            f"expected={expected}, observed={observed}"
        )
    implementation_digest = _compiled_producer_implementation_digest()
    if implementation_digest != _COMPILED_PRODUCER_IMPLEMENTATION_DIGEST:
        raise ValueError(
            "compiled producer implementation drifted; review and repin "
            f"{_COMPILED_PRODUCER_PROFILE}: expected="
            f"{_COMPILED_PRODUCER_IMPLEMENTATION_DIGEST}, "
            f"observed={implementation_digest}"
        )

    ontology, shapes = ATLAS_VALIDATE._parse_binding_graphs()
    ATLAS_VALIDATE._lint_ontology(ontology)
    try:
        conforms, _, report = ATLAS_VALIDATE.shacl_validate(
            Graph(),
            shacl_graph=shapes,
            ont_graph=ontology,
            inference="none",
            advanced=False,
            meta_shacl=True,
        )
    except Exception as error:
        raise ValueError(f"compiled producer SHACL meta-validation failed: {error}") from error
    finally:
        ontology.close()
        shapes.close()
    if not conforms:
        compact = " ".join(str(report).split())
        raise ValueError(
            "compiled producer SHACL profile is not well formed: "
            f"{compact[:900]}"
        )
    return observed


def _validate_compiled_source_rows(
    releases: tuple[LoadedRelease, ...],
) -> CompiledSourceValidationReceipt:
    """Validate source-only rows against the exact compiled SHACL profile.

    This is deliberately narrower than the independent RDF validator. The
    fixed constructors cover carrier shape and datatype rules; this pass proves
    the joins and uniqueness rules directly on the smaller normalized rows.
    """

    if not releases:
        raise ValueError("compiled producer validation requires source releases")
    binding_profile = _validate_compiled_binding_profile()
    english_only_scan = _english_only_scan(releases)
    profile_policies = ATLAS_VALIDATE._profile_policies()
    relation_policies = ATLAS_VALIDATE._relation_policies()
    cross_ring_policies = ATLAS_VALIDATE._cross_ring_relation_policies()

    descriptor_graph = _registry_asserted_graph()
    try:
        _ensure_release_schemes(descriptor_graph, releases)
        catalog_carriers = {
            str(subject)
            for carrier_type in (ATLAS.RegistrySource, ATLAS.ResourceScheme)
            for subject in descriptor_graph.subjects(RDF.type, carrier_type)
        }
        identifier_schemes = {
            str(subject)
            for subject in descriptor_graph.subjects(
                ATLAS.resourceProfile,
                ATLAS.identifierScheme,
            )
            if (subject, RDF.type, ATLAS.ResourceScheme) in descriptor_graph
        }

        source_release_iris = {release.source_release_iri for release in releases}
        atlas_release_iris = {release.atlas_release_iri for release in releases}
        if source_release_iris & atlas_release_iris:
            raise ValueError("source and Atlas release identities overlap")
        if (source_release_iris | atlas_release_iris) & catalog_carriers:
            raise ValueError("release identity overlaps a registry catalog carrier")

        resource_index: dict[str, tuple[LoadedRelease, URIRef]] = {}
        relation_evidence_records: set[URIRef] = set()
        identifier_targets: dict[tuple[str, str], str] = {}
        label_count = 0
        identifier_count = 0
        source_assignment_count = 0

        for release in releases:
            _validate_loaded_release(release)
            if not release.spec.key:
                raise ValueError("source release key must be non-empty")
            if not release.resources:
                raise ValueError(
                    f"{release.spec.key} source release has no Atlas resources"
                )
            for field, value in (
                ("source release", release.source_release_iri),
                ("Atlas release", release.atlas_release_iri),
                ("resource scheme", release.scheme_iri),
            ):
                iri = _require_absolute_iri(
                    value,
                    context=f"{release.spec.key} {field}",
                )
                if iri.startswith(_GENERATED_CARRIER_IRI_PREFIXES):
                    raise ValueError(
                        f"{release.spec.key} {field} uses a generated carrier namespace"
                    )
            if ATLAS_VALIDATE.DIGEST_RE.fullmatch(release.source_release_digest) is None:
                raise ValueError(
                    f"{release.spec.key} source release digest is not SHA-256"
                )
            try:
                parsed_issued = date.fromisoformat(release.issued)
            except (TypeError, ValueError) as error:
                raise ValueError(
                    f"{release.spec.key} issued date is not canonical YYYY-MM-DD"
                ) from error
            if parsed_issued.isoformat() != release.issued:
                raise ValueError(
                    f"{release.spec.key} issued date is not canonical YYYY-MM-DD"
                )
            if release.dropped_label_count < 0:
                raise ValueError(f"{release.spec.key} dropped label count is negative")
            _release_label_role_conflict_count(release)
            _accounting_membership_mode(release.spec.scope)

            ring, resource_class, _ = _ring_dispatch(release.spec.ring)
            profile = ATLAS[release.spec.profile]
            profile_policy = profile_policies.get(profile)
            if (
                profile_policy is None
                or release.spec.ring
                not in profile_policy["applicableSemanticRings"]
                or str(resource_class)
                not in profile_policy["applicableEntryClasses"]
            ):
                raise ValueError(
                    f"{release.spec.key} profile/ring/resource class is unsupported"
                )
            scheme = URIRef(release.scheme_iri)
            if set(descriptor_graph.objects(scheme, ATLAS.resourceProfile)) != {
                profile
            } or ring not in descriptor_graph.objects(scheme, ATLAS.supportedRing):
                raise ValueError(
                    f"{release.spec.key} release ownership differs from its scheme"
                )
            if (
                ring == ATLAS.subject
                and (scheme, RDF.type, SKOS.ConceptScheme) not in descriptor_graph
            ):
                raise ValueError(
                    f"{release.spec.key} subject scheme is not a SKOS ConceptScheme"
                )

            for resource in release.resources:
                resource_iri = _require_absolute_iri(
                    resource.iri,
                    context=f"{release.spec.key} resource",
                )
                if (
                    resource_iri in catalog_carriers
                    or resource_iri in source_release_iris
                    or resource_iri in atlas_release_iris
                    or resource_iri.startswith(_GENERATED_CARRIER_IRI_PREFIXES)
                ):
                    raise ValueError(
                        f"resource identity overlaps another carrier: {resource_iri}"
                    )
                if resource_iri in resource_index:
                    raise ValueError(f"Atlas releases repeat resource IRI {resource_iri}")
                resource_index[resource_iri] = (release, ring)

                _require_absolute_iri(
                    resource.source_locator,
                    context=f"{release.spec.key}/{resource_iri} source locator",
                )
                if (
                    not isinstance(resource.source_digest, str)
                    or ATLAS_VALIDATE.DIGEST_RE.fullmatch(resource.source_digest) is None
                ):
                    raise ValueError(
                        f"{release.spec.key}/{resource_iri} source digest is not SHA-256"
                    )
                if not isinstance(resource.labels, Sequence) or not resource.labels:
                    raise ValueError(f"{resource_iri} has no English label")
                preferred_count = 0
                value_roles: dict[str, SourceLabelRole] = {}
                for label in resource.labels:
                    if (
                        not isinstance(label.value, str)
                        or not label.value
                        or label.language != "en"
                        or label.role not in SOURCE_LABEL_ROLES
                        or not isinstance(label.source_path, str)
                        or not label.source_path
                    ):
                        raise ValueError(
                            f"{resource_iri} has an invalid English label row"
                        )
                    preferred_count += label.role == "preferred"
                    previous_role = value_roles.setdefault(label.value, label.role)
                    if previous_role != label.role:
                        raise ValueError(
                            f"{resource_iri} reuses label value {label.value!r} "
                            "across SKOS-XL roles"
                        )
                    label_count += 1
                if preferred_count > 1:
                    raise ValueError(
                        f"{resource_iri} has more than one preferred English label"
                    )

                for field, values, allow_empty in (
                    ("notes", resource.notes, True),
                    ("notations", resource.notations, False),
                ):
                    if not isinstance(values, Sequence) or isinstance(values, str):
                        raise TypeError(f"{resource_iri} {field} must be a sequence")
                    if any(
                        not isinstance(value, str) or (not allow_empty and not value)
                        for value in values
                    ):
                        raise ValueError(f"{resource_iri} has invalid {field}")
                if resource.definition is not None and not isinstance(
                    resource.definition,
                    str,
                ):
                    raise ValueError(f"{resource_iri} definition must be text")
                if resource.status is not None and (
                    not isinstance(resource.status, str) or not resource.status
                ):
                    raise ValueError(f"{resource_iri} status must be non-empty text")

                for identifier in resource.identifiers:
                    scheme_iri = _require_absolute_iri(
                        identifier.scheme_iri,
                        context=f"{resource_iri} identifier scheme",
                    )
                    if scheme_iri not in identifier_schemes:
                        raise ValueError(
                            f"{resource_iri} identifier scheme is not an "
                            f"Atlas identifier authority: {scheme_iri}"
                        )
                    if (
                        not isinstance(identifier.value, str)
                        or not identifier.value
                        or not isinstance(identifier.source_path, str)
                        or not identifier.source_path
                    ):
                        raise ValueError(f"{resource_iri} has an invalid identifier row")
                    key = (scheme_iri, identifier.value)
                    previous_target = identifier_targets.setdefault(key, resource_iri)
                    if previous_target != resource_iri:
                        raise ValueError(
                            "authority-scoped identifier resolves to multiple resources: "
                            f"scheme={scheme_iri}, value={identifier.value!r}, "
                            f"targets={previous_target!r}, {resource_iri!r}"
                        )
                    identifier_count += 1
                if release.spec.emit_source_assignments:
                    source_assignment_count += 1

        current_relations: dict[
            tuple[URIRef, URIRef, URIRef],
            tuple[URIRef, ...],
        ] = {}
        cross_ring_claims: set[tuple[str, str, str, str, str]] = set()
        remap_evidence_count = 0
        relation_payload_count = 0
        for release in releases:
            release_ring = ATLAS[release.spec.ring]
            allowed = relation_policies.get(release_ring, {}).get(
                ATLAS.NativeRelationAssertion,
                frozenset(),
            )
            for relation in release.relations:
                relation_payload_count += 1
                for field, value in (
                    ("subject", relation.subject),
                    ("predicate", relation.predicate),
                    ("object", relation.object),
                ):
                    _require_absolute_iri(
                        value,
                        context=f"{release.spec.key} relation {field}",
                    )
                source = resource_index.get(relation.subject)
                target = resource_index.get(relation.object)
                if source is None or target is None:
                    raise ValueError(
                        f"native relation endpoint is outside loaded releases: {relation}"
                    )
                if source[0] is not release:
                    raise ValueError(
                        f"native relation is not owned by its subject release: {relation}"
                    )
                if source[1] != release_ring or target[1] != release_ring:
                    raise ValueError(f"native relation endpoint ring differs: {relation}")
                predicate = URIRef(relation.predicate)
                if predicate not in allowed:
                    raise ValueError(
                        f"native relation predicate is not allowed for "
                        f"{release.spec.ring}: {predicate}"
                    )
                if not isinstance(relation.source_payload, Mapping):
                    raise TypeError(
                        f"native relation source payload is not an object: {relation}"
                    )
                ATLAS_VALIDATE.canonical_native_json_bytes(
                    _plain(relation.source_payload)
                )
                if predicate == ATLAS.thesaurusRelated:
                    evidence_locator, evidence_digest, evidence_payload = (
                        _transformed_relation_evidence(relation)
                    )
                    evidence_record, _ = _source_record_constructor(
                        source_release=URIRef(release.source_release_iri),
                        source_locator=evidence_locator,
                        source_digest=evidence_digest,
                        native_payload=evidence_payload,
                    )
                    if evidence_record in relation_evidence_records:
                        raise ValueError(
                            f"relation evidence SourceRecord is repeated: {evidence_record}"
                        )
                    relation_evidence_records.add(evidence_record)
                    remap_evidence_count += 1
                triple = (
                    URIRef(relation.subject),
                    predicate,
                    URIRef(relation.object),
                )
                if triple in current_relations:
                    raise ValueError(f"native relation claim is repeated: {triple}")
                current_relations[triple] = ()

            for relation in release.cross_ring_relations:
                relation_payload_count += 1
                for field, value in (
                    ("subject", relation.subject),
                    ("predicate", relation.predicate),
                    ("object", relation.object),
                ):
                    _require_absolute_iri(
                        value,
                        context=f"{release.spec.key} cross-ring relation {field}",
                    )
                source = resource_index.get(relation.subject)
                target = resource_index.get(relation.object)
                if source is None or target is None:
                    raise ValueError(
                        f"cross-ring relation endpoint is outside loaded releases: {relation}"
                    )
                source_ring = ATLAS[relation.source_ring]
                target_ring = ATLAS[relation.target_ring]
                if source[0] is not release:
                    raise ValueError(
                        f"cross-ring relation is not owned by its subject release: {relation}"
                    )
                if (source[1], target[1]) != (source_ring, target_ring):
                    raise ValueError(
                        f"cross-ring relation endpoint ring differs: {relation}"
                    )
                if URIRef(relation.predicate) not in cross_ring_policies.get(
                    (source_ring, target_ring),
                    frozenset(),
                ):
                    raise ValueError(
                        f"cross-ring relation predicate is not allowed: {relation}"
                    )
                if not isinstance(relation.source_payload, Mapping):
                    raise TypeError(
                        f"cross-ring relation source payload is not an object: {relation}"
                    )
                ATLAS_VALIDATE.canonical_native_json_bytes(
                    _plain(relation.source_payload)
                )
                claim = (
                    relation.subject,
                    relation.predicate,
                    relation.object,
                    relation.source_ring,
                    relation.target_ring,
                )
                if claim in cross_ring_claims:
                    raise ValueError(f"cross-ring relation claim is repeated: {claim}")
                cross_ring_claims.add(claim)

        if relation_payload_count != english_only_scan["relationPayloadsChecked"]:
            raise ValueError("relation payload validation count differs")
        ATLAS_VALIDATE._check_skos_integrity(current_relations)

        resource_count = len(resource_index)
        native_relation_count = len(current_relations)
        cross_ring_count = len(cross_ring_claims)
        expected_counts = {
            "crossRingRelationAssertions": cross_ring_count,
            "derivedRelations": 0,
            "identifiers": identifier_count,
            "labels": label_count,
            "mappingAssertions": 0,
            "nativeRelationAssertions": native_relation_count,
            "projectedRelations": 0,
            "relationAssertions": (
                source_assignment_count + native_relation_count + cross_ring_count
            ),
            "releases": len(releases),
            "resources": resource_count,
            "sourceAssignments": source_assignment_count,
            "sourceRecords": resource_count + remap_evidence_count,
        }
    finally:
        descriptor_graph.close()

    return CompiledSourceValidationReceipt(
        binding_profile=binding_profile,
        english_only_scan=english_only_scan,
        expected_counts=expected_counts,
        source_release_count=len(releases),
    )


def _validate_compiled_source_accounting(
    releases: Sequence[LoadedRelease],
    accounting: Mapping[str, Any],
) -> str:
    """Reconcile the generated ledger with the compact source membership."""

    if set(accounting) != {"distributionId", "inputs", "totals", "type", "version"}:
        raise ValueError("compiled producer source accounting fields differ")
    if (
        accounting.get("distributionId") != DISTRIBUTION_ID
        or accounting.get("type") != "AtlasSourceAccounting"
        or accounting.get("version") != "3.0"
    ):
        raise ValueError("compiled producer source accounting identity differs")
    inputs = accounting.get("inputs")
    if not isinstance(inputs, list):
        raise TypeError("compiled producer source accounting inputs are not a list")
    rows_by_release: dict[str, Mapping[str, Any]] = {}
    for row in inputs:
        if not isinstance(row, Mapping) or set(row) != {
            "declaredMemberCount",
            "dispositions",
            "membershipMode",
            "sourceRelease",
        }:
            raise ValueError("compiled producer source accounting row fields differ")
        source_release = row.get("sourceRelease")
        if not isinstance(source_release, str) or source_release in rows_by_release:
            raise ValueError("compiled producer source accounting repeats a release")
        rows_by_release[source_release] = row

    expected_releases = {release.source_release_iri for release in releases}
    if set(rows_by_release) != expected_releases:
        raise ValueError("compiled producer source accounting release set differs")

    source_records: set[str] = set()
    represented_total = 0
    excluded_total = 0
    for release in releases:
        row = rows_by_release[release.source_release_iri]
        if row["membershipMode"] != _accounting_membership_mode(release.spec.scope):
            raise ValueError(
                f"{release.spec.key} source accounting membership mode differs"
            )
        dispositions = row["dispositions"]
        if (
            not isinstance(dispositions, list)
            or row["declaredMemberCount"] != len(dispositions)
        ):
            raise ValueError(
                f"{release.spec.key} source accounting member count differs"
            )
        expected_resources = {resource.iri for resource in release.resources}
        represented_resources: set[str] = set()
        excluded = 0
        for disposition in dispositions:
            if not isinstance(disposition, Mapping):
                raise TypeError(
                    f"{release.spec.key} source accounting disposition is not an object"
                )
            source_record = disposition.get("sourceRecord")
            if (
                not isinstance(source_record, str)
                or not source_record.startswith("urn:ref:atlas-source-record:")
                or source_record in source_records
            ):
                raise ValueError(
                    f"{release.spec.key} source accounting SourceRecord is invalid or repeated"
                )
            source_records.add(source_record)
            status = disposition.get("status")
            if status == "represented":
                if set(disposition) != {
                    "atlasResources",
                    "sourceRecord",
                    "status",
                }:
                    raise ValueError(
                        f"{release.spec.key} represented disposition fields differ"
                    )
                resources = disposition.get("atlasResources")
                if not isinstance(resources, list) or len(resources) != 1:
                    raise ValueError(
                        f"{release.spec.key} represented disposition is not one resource"
                    )
                resource = resources[0]
                if not isinstance(resource, str) or resource in represented_resources:
                    raise ValueError(
                        f"{release.spec.key} represented resource is invalid or repeated"
                    )
                represented_resources.add(resource)
            elif status == "excluded":
                if (
                    set(disposition)
                    != {"atlasResources", "reason", "sourceRecord", "status"}
                    or disposition.get("atlasResources") != []
                    or disposition.get("reason")
                    != _TRANSFORMED_RELATION_ACCOUNTING_REASON
                ):
                    raise ValueError(
                        f"{release.spec.key} excluded disposition differs"
                    )
                excluded += 1
            else:
                raise ValueError(
                    f"{release.spec.key} source accounting status is unsupported"
                )
        if represented_resources != expected_resources:
            raise ValueError(
                f"{release.spec.key} source accounting resource membership differs"
            )
        expected_excluded = sum(
            relation.predicate == str(ATLAS.thesaurusRelated)
            for relation in release.relations
        )
        if excluded != expected_excluded:
            raise ValueError(
                f"{release.spec.key} source accounting excluded count differs"
            )
        represented_total += len(represented_resources)
        excluded_total += excluded

    expected_totals = {
        "excluded": excluded_total,
        "represented": represented_total,
        "sourceRecords": represented_total + excluded_total,
        "sourceReleases": len(releases),
        "unresolved": 0,
    }
    if accounting.get("totals") != expected_totals:
        raise ValueError("compiled producer source accounting totals differ")
    return _canonical_digest(accounting)


def _validate_compiled_producer_output(
    releases: Sequence[LoadedRelease],
    graphs: BuildGraphs,
    source_validation: CompiledSourceValidationReceipt,
) -> dict[str, Any]:
    """Close the proof over fixed constructors without rewalking every quad."""

    if dict(source_validation.binding_profile) != dict(
        _COMPILED_PRODUCER_BINDING_PINS
    ):
        raise ValueError("compiled producer binding receipt differs")
    if graphs.projection or graphs.derived:
        raise ValueError(
            "compiled source-only producer requires empty projection and derived graphs"
        )
    if any(graphs.asserted.triples((None, ATLAS.supersedes, None))):
        raise ValueError("compiled source-only producer does not support supersession")
    observed_counts = _counts(graphs)
    if observed_counts != dict(source_validation.expected_counts):
        raise ValueError(
            "compiled producer constructor counts differ: "
            f"expected={dict(source_validation.expected_counts)}, "
            f"observed={observed_counts}"
        )
    accounting_digest = _validate_compiled_source_accounting(
        releases,
        graphs.accounting,
    )
    if not isinstance(graphs.asserted, _MutationTrackedGraph):
        raise TypeError("compiled producer graph lacks a mutation receipt")
    graphs.sealed_asserted_revision = graphs.asserted.revision
    return {
        "bindingProfile": dict(source_validation.binding_profile),
        "checks": [
            "normalized resource, English SKOS-XL label, and identifier rows",
            "release, scheme, profile, and semantic-ring ownership",
            "native and cross-ring relation endpoints, policies, and source payloads",
            "SKOS hierarchy and associative-relation integrity",
            "fixed source-record, label, identifier, assertion, and evidence constructors",
            "source-accounting membership and counts",
            "zero mappings, projections, derived relations, and supersession",
        ],
        "constructorProfile": _COMPILED_PRODUCER_PROFILE,
        "counts": observed_counts,
        "mode": "compiledSourceProducerValidation",
        "shaclDataProof": "compiledAgainstPinnedOntologyAndShapes",
        "shaclMetaValidation": "pySHACL",
        "sourceAccountingDigest": accounting_digest,
        "sourceReleaseCount": source_validation.source_release_count,
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


def _accounting_membership_mode(scope: str) -> str:
    """State whether the source ledger covers the source or only a named subset."""

    if scope == "captureSubset":
        return "partial"
    if scope in {"completeCapture", "publisherRelease"}:
        return "complete"
    raise ValueError(f"unsupported source release scope: {scope!r}")


def _build_graphs(
    releases: tuple[LoadedRelease, ...],
    *,
    include_projection: bool = True,
) -> BuildGraphs:
    asserted = _registry_asserted_graph()
    _ensure_release_schemes(asserted, releases)
    native_policy = _add_policy(asserted, SOURCE_NATIVE_EDITORIAL_POLICY_PAYLOAD)

    source_release_nodes: dict[str, URIRef] = {}
    resource_release: dict[str, URIRef] = {}
    resource_record: dict[str, URIRef] = {}
    resource_ring: dict[str, URIRef] = {}
    identifier_targets: dict[tuple[str, str], str] = {}
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
            resource_ring[resource_row.iri] = ring
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
            for identifier_row in resource_row.identifiers:
                identifier_key = (
                    identifier_row.scheme_iri,
                    identifier_row.value,
                )
                previous_target = identifier_targets.setdefault(
                    identifier_key,
                    resource_row.iri,
                )
                if previous_target != resource_row.iri:
                    raise ValueError(
                        "authority-scoped identifier resolves to multiple resources: "
                        f"scheme={identifier_row.scheme_iri}, "
                        f"value={identifier_row.value!r}, "
                        f"targets={previous_target!r}, {resource_row.iri!r}"
                    )
                _add_identifier(
                    asserted,
                    identifier_row=identifier_row,
                    resource=resource,
                    source_record=record,
                )
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
            "membershipMode": _accounting_membership_mode(release.spec.scope),
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
                        "reason": _TRANSFORMED_RELATION_ACCOUNTING_REASON,
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

    cross_ring_count = 0
    for release in releases:
        for relation in release.cross_ring_relations:
            try:
                source_atlas_release = resource_release[relation.subject]
                target_atlas_release = resource_release[relation.object]
                evidence_record = resource_record[relation.subject]
                observed_source_ring = resource_ring[relation.subject]
                observed_target_ring = resource_ring[relation.object]
            except KeyError as error:
                raise ValueError(
                    f"cross-ring relation endpoint is outside loaded releases: {relation}"
                ) from error
            source_ring = ATLAS[relation.source_ring]
            target_ring = ATLAS[relation.target_ring]
            if source_atlas_release != URIRef(release.atlas_release_iri):
                raise ValueError(
                    "cross-ring relation must be owned by its subject release: "
                    f"{relation}"
                )
            if (observed_source_ring, observed_target_ring) != (
                source_ring,
                target_ring,
            ):
                raise ValueError(
                    f"cross-ring relation endpoint ring differs: {relation}"
                )
            _add_assertion(
                asserted,
                assertion_type=ATLAS.CrossRingRelationAssertion,
                ring=None,
                subject=URIRef(relation.subject),
                predicate=URIRef(relation.predicate),
                obj=URIRef(relation.object),
                source_release=source_atlas_release,
                target_release=target_atlas_release,
                policy=native_policy,
                asserted_at=CREATED_AT,
                evidence_record=evidence_record,
                reviewer=NATIVE_REVIEWER,
                review_method=_review_method_for_assertion(
                    ATLAS.CrossRingRelationAssertion
                ),
                confidence="1",
                source_ring=source_ring,
                target_ring=target_ring,
            )
            cross_ring_count += 1
    expected_cross_ring_count = sum(
        len(release.cross_ring_relations) for release in releases
    )
    if cross_ring_count != expected_cross_ring_count:
        raise ValueError(
            "expected "
            f"{expected_cross_ring_count} cross-ring assertions; "
            f"emitted {cross_ring_count}"
        )

    if any(asserted.subjects(RDF.type, ATLAS.MappingAssertion)):
        raise ValueError("source-only Atlas build emitted a MappingAssertion")
    projection = (
        _expected_projection_graph(asserted) if include_projection else _new_build_graph()
    )
    derived = _new_build_graph()
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
        "crossRingRelationAssertions": len(
            set(
                asserted.subjects(
                    RDF.type,
                    ATLAS.CrossRingRelationAssertion,
                )
            )
        ),
        "identifiers": len(set(asserted.subjects(RDF.type, ATLAS.Identifier))),
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

    return _production_relation_scope_from_counts(_counts(graphs))


def _production_relation_scope_from_counts(
    counts: Mapping[str, int],
) -> dict[str, Any]:
    """Close a receipted production writer to publisher-source relations."""

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


class _DigestingBinaryWriter:
    """Hash every byte accepted by a binary output stream."""

    def __init__(self, stream: Any) -> None:
        self._stream = stream
        self._digest = hashlib.sha256()
        self.byte_length = 0

    def write(self, data: bytes) -> int:
        view = memoryview(data)
        written_total = 0
        while written_total < len(view):
            written = self._stream.write(view[written_total:])
            if written is None:
                written = len(view) - written_total
            if written <= 0:
                raise OSError("stored Atlas pack write made no progress")
            accepted = view[written_total : written_total + written]
            self._digest.update(accepted)
            self.byte_length += written
            written_total += written
        return written_total

    def flush(self) -> None:
        self._stream.flush()

    @property
    def digest(self) -> str:
        return "sha256:" + self._digest.hexdigest()


def _compress_nquads(source: Path, target: Path) -> PackWriteReceipt:
    """Compress canonical N-Quads and receipt both forms in one write pass."""

    content_digest = hashlib.sha256()
    content_byte_length = 0
    content_quad_count = 0
    target.parent.mkdir(parents=True, exist_ok=True)
    with (
        source.open("rb") as input_stream,
        target.open("wb") as stored_stream,
    ):
        transport_writer = _DigestingBinaryWriter(stored_stream)
        with zstd.open(
            transport_writer,
            "wb",
            level=_PACK_ZSTD_LEVEL,
        ) as output_stream:
            for block in iter(lambda: input_stream.read(1024 * 1024), b""):
                content_digest.update(block)
                content_byte_length += len(block)
                content_quad_count += block.count(b"\n")
                output_stream.write(block)
    transport_byte_length = target.stat().st_size
    if transport_byte_length != transport_writer.byte_length:
        raise OSError(
            "stored Atlas pack length differs from bytes accepted by its writer"
        )
    return PackWriteReceipt(
        content_byte_length=content_byte_length,
        content_digest="sha256:" + content_digest.hexdigest(),
        content_quad_count=content_quad_count,
        transport_byte_length=transport_byte_length,
        transport_digest=transport_writer.digest,
    )


def _release_pack_token(release: ReleasePackPlan) -> str:
    token = _PACK_PATH_UNSAFE.sub("-", release.key.casefold()).strip("-")
    if _PACK_PATH_TOKEN.fullmatch(token) is None:
        raise ValueError(f"release key is unsafe for an Atlas pack path: {token!r}")
    return token


def _release_subject_owners(
    asserted: Graph,
    releases: Sequence[ReleasePackPlan],
) -> tuple[
    dict[URIRef, tuple[str, str | None]],
    dict[str, ReleasePackPlan],
]:
    """Resolve each release-owned subject to its final pack exactly once."""

    releases_by_key = {_release_pack_token(release): release for release in releases}
    if len(releases_by_key) != len(releases):
        raise ValueError("Atlas release keys collide after safe pack-path normalization")
    atlas_release_owners: dict[URIRef, str] = {}
    source_release_owners: dict[URIRef, str] = {}
    for key, release in releases_by_key.items():
        atlas_release = URIRef(release.atlas_release_iri)
        source_release = URIRef(release.source_release_iri)
        if atlas_release in atlas_release_owners:
            raise ValueError(f"Atlas release is emitted more than once: {atlas_release}")
        if source_release in source_release_owners:
            raise ValueError(f"source release is emitted more than once: {source_release}")
        atlas_release_owners[atlas_release] = key
        source_release_owners[source_release] = key

    owners: dict[URIRef, str] = {
        **atlas_release_owners,
        **source_release_owners,
    }

    def own_from_object(
        node_type: URIRef,
        predicate: URIRef,
        target_owners: Mapping[URIRef, str],
    ) -> None:
        for node in asserted.subjects(RDF.type, node_type):
            target = asserted.value(node, predicate)
            owner = target_owners.get(target) if isinstance(target, URIRef) else None
            if owner is None:
                raise ValueError(
                    f"{node_type} {node} has no release-owned {predicate} target"
                )
            owners[URIRef(node)] = owner

    own_from_object(ATLAS.AtlasResource, ATLAS.inRelease, atlas_release_owners)
    own_from_object(SKOSXL.Label, ATLAS.inRelease, atlas_release_owners)
    own_from_object(
        ATLAS.SourceRecord,
        ATLAS.inSourceRelease,
        source_release_owners,
    )

    for identifier in asserted.subjects(RDF.type, ATLAS.Identifier):
        resource = asserted.value(identifier, ATLAS.identifies)
        owner = owners.get(resource) if isinstance(resource, URIRef) else None
        if owner is None:
            raise ValueError(f"identifier {identifier} has no release-owned resource")
        owners[URIRef(identifier)] = owner

    for assertion in asserted.subjects(RDF.type, ATLAS.RelationAssertion):
        source_release = asserted.value(assertion, ATLAS.sourceRelease)
        target_release = asserted.value(assertion, ATLAS.targetRelease)
        owner = None
        for release_node in (source_release, target_release):
            if isinstance(release_node, URIRef):
                owner = atlas_release_owners.get(release_node) or source_release_owners.get(
                    release_node
                )
            if owner is not None:
                break
        if owner is None:
            raise ValueError(f"relation assertion {assertion} has no release owner")
        owners[URIRef(assertion)] = owner

    own_from_object(
        ATLAS.EvidenceBinding,
        ATLAS.bindsAssertion,
        owners,
    )
    for event in asserted.subjects(RDF.type, ATLAS.LifecycleEvent):
        source_record = asserted.value(event, ATLAS.sourceRecord)
        owner = owners.get(source_record) if isinstance(source_record, URIRef) else None
        if owner is None:
            raise ValueError(f"lifecycle event {event} has no release-owned source record")
        owners[URIRef(event)] = owner

    pack_owners: dict[URIRef, tuple[str, str | None]] = {}
    for subject, owner in owners.items():
        release = releases_by_key[owner]
        pack_owners[subject] = (
            owner,
            _release_pack_partition(release, subject),
        )

    return pack_owners, releases_by_key


def _release_pack_partition(
    release: ReleasePackPlan,
    subject: URIRef,
) -> str | None:
    if release.resource_count < _PACK_LARGE_RELEASE_RESOURCE_THRESHOLD:
        return None
    digest = hashlib.sha256(str(subject).encode("utf-8")).hexdigest()
    bucket_width = (_PACK_LARGE_RELEASE_BUCKETS - 1).bit_length() // 4
    if 16**bucket_width != _PACK_LARGE_RELEASE_BUCKETS:
        raise ValueError("Atlas pack bucket count must be an exact hexadecimal power")
    return digest[:bucket_width]


def _pack_spool_name(owner: str | None, partition: str | None) -> str:
    if owner is None:
        return "catalog"
    return owner if partition is None else f"{owner}-{partition}"


def _write_asserted_packs(
    output: Path,
    asserted: Graph,
    releases: Sequence[ReleasePackPlan],
) -> list[dict[str, Any]]:
    """Write source-release-owned asserted packs and one shared catalog pack."""

    pack_owners, releases_by_key = _release_subject_owners(asserted, releases)
    graph_id = URIRef(DISTRIBUTION_ID + ":asserted")
    with tempfile.TemporaryDirectory(prefix="atlas3-packs-", dir=output) as raw_temp:
        temporary = Path(raw_temp)
        spool_paths: dict[tuple[str | None, str | None], Path] = {}
        line_counts: Counter[tuple[str | None, str | None]] = Counter()
        cross_pack_dependencies: dict[
            tuple[str | None, str | None], set[tuple[str | None, str | None]]
        ] = defaultdict(set)
        with ExitStack() as stack:
            streams: dict[tuple[str | None, str | None], TextIO] = {}
            def stream_for(key: tuple[str | None, str | None]) -> TextIO:
                stream = streams.get(key)
                if stream is not None:
                    return stream
                path = temporary / (_pack_spool_name(*key) + ".unsorted.nq")
                spool_paths[key] = path
                stream = stack.enter_context(
                    path.open("w", encoding="utf-8", newline="")
                )
                streams[key] = stream
                return stream

            for subject, predicate, obj in asserted:
                if not isinstance(subject, URIRef):
                    raise TypeError("Atlas asserted graph contains a non-IRI subject")
                key = pack_owners.get(subject, (None, None))
                owner, _ = key
                line = (
                    ATLAS_VALIDATE.nquads_line(subject, predicate, obj, graph_id)
                    + "\n"
                )
                if len(line.encode("utf-8")) > ATLAS_VALIDATE.NQUADS_MAX_LINE_BYTES:
                    raise ValueError(
                        "canonical Atlas N-Quads line exceeds the binding limit"
                    )
                stream_for(key).write(line)
                line_counts[key] += 1
                if owner is None or not isinstance(obj, URIRef):
                    continue
                object_key = pack_owners.get(obj)
                if object_key is None:
                    continue
                if object_key != key:
                    cross_pack_dependencies[key].add(object_key)

        staged: dict[tuple[str | None, str | None], dict[str, Any]] = {}
        for key, spool_path in sorted(
            spool_paths.items(), key=lambda row: _pack_spool_name(*row[0])
        ):
            owner, partition = key
            if owner is None:
                relative = Path("packs") / "catalog.nq.zst"
            else:
                filename = "all.nq.zst" if partition is None else f"{partition}.nq.zst"
                relative = Path("packs") / "sources" / owner / filename
            sorted_path = temporary / (_pack_spool_name(*key) + ".sorted.nq")
            with spool_path.open("r", encoding="utf-8", newline="") as lines:
                _write_sorted_lines(sorted_path, lines)
            target = output / relative
            receipt = _compress_nquads(sorted_path, target)
            pack: dict[str, Any] = {
                "content": {
                    "byteLength": receipt.content_byte_length,
                    "digest": receipt.content_digest,
                    "mediaType": "application/n-quads",
                    "quadCount": receipt.content_quad_count,
                },
                "dependencies": [],
                "graphCounts": {
                    "asserted": line_counts[key],
                    "derived": 0,
                    "projection": 0,
                },
                "kind": "catalog" if owner is None else "sourceRelease",
                "packId": "urn:ref:atlas:pack:"
                + receipt.content_digest.removeprefix("sha256:"),
                "path": relative.as_posix(),
                "rings": [] if owner is None else [releases_by_key[owner].ring],
                "sourceReleases": (
                    [] if owner is None else [releases_by_key[owner].source_release_iri]
                ),
                "transport": {
                    "byteLength": receipt.transport_byte_length,
                    "compression": "zstd",
                    "digest": receipt.transport_digest,
                    "mediaType": "application/zstd",
                },
            }
            if partition is not None:
                pack["partition"] = {
                    "prefix": partition,
                    "strategy": "sha256-subject-iri-prefix",
                }
            staged[key] = pack

        if (None, None) not in staged:
            raise ValueError("Atlas asserted graph produced no catalog pack")
        catalog_id = staged[(None, None)]["packId"]
        for key, pack in staged.items():
            owner, _ = key
            if owner is None:
                continue
            dependency_ids = {catalog_id}
            dependency_ids.update(
                staged[dependency]["packId"]
                for dependency in cross_pack_dependencies.get(key, set())
            )
            pack["dependencies"] = sorted(dependency_ids)
        return sorted(staged.values(), key=lambda pack: pack["path"])


def _graph_inventory_digest(
    packs: Sequence[Mapping[str, Any]],
    role: str,
) -> str:
    rows = sorted(
        (
            {
                "contentDigest": pack["content"]["digest"],
                "packId": pack["packId"],
                "quadCount": pack["graphCounts"][role],
            }
            for pack in packs
            if pack["graphCounts"][role]
        ),
        key=lambda row: row["packId"],
    )
    return ATLAS_VALIDATE.canonical_sha256(rows, terminal_lf=False)


def _write_view_pack(
    output: Path,
    *,
    role: str,
    graph: Graph,
    asserted_packs: Sequence[Mapping[str, Any]],
    asserted_inventory_digest: str,
) -> dict[str, Any] | None:
    if not graph:
        return None
    if role not in {"projection", "derived"}:
        raise ValueError(f"unsupported Atlas view graph role: {role}")
    relative = Path("packs") / "views" / f"{role}.nq.zst"
    with tempfile.TemporaryDirectory(prefix=f"atlas3-{role}-", dir=output) as raw_temp:
        sorted_path = Path(raw_temp) / f"{role}.nq"
        graph_id = URIRef(DISTRIBUTION_ID + ":" + role)
        _write_sorted_lines(
            sorted_path,
            (
                ATLAS_VALIDATE.nquads_line(subject, predicate, obj, graph_id) + "\n"
                for subject, predicate, obj in graph
            ),
        )
        receipt = _compress_nquads(sorted_path, output / relative)
    graph_counts = {"asserted": 0, "derived": 0, "projection": 0}
    graph_counts[role] = len(graph)
    return {
        "content": {
            "byteLength": receipt.content_byte_length,
            "digest": receipt.content_digest,
            "mediaType": "application/n-quads",
            "quadCount": receipt.content_quad_count,
        },
        "dependencies": sorted(pack["packId"] for pack in asserted_packs),
        "graphCounts": graph_counts,
        "inputAssertedDigest": asserted_inventory_digest,
        "kind": "view",
        "packId": "urn:ref:atlas:pack:"
        + receipt.content_digest.removeprefix("sha256:"),
        "path": relative.as_posix(),
        "rings": [],
        "sourceReleases": [],
        "transport": {
            "byteLength": receipt.transport_byte_length,
            "compression": "zstd",
            "digest": receipt.transport_digest,
            "mediaType": "application/zstd",
        },
    }


def _write_graph_packs(
    output: Path,
    graphs: BuildGraphs,
    releases: Sequence[ReleasePackPlan],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if releases:
        asserted_packs = _write_asserted_packs(output, graphs.asserted, releases)
    else:
        relative = Path("packs") / "atlas.nq.zst"
        with tempfile.TemporaryDirectory(prefix="atlas3-aggregate-", dir=output) as raw_temp:
            sorted_path = Path(raw_temp) / "atlas.nq"
            _write_sorted_lines(sorted_path, _dataset_lines(graphs))
            receipt = _compress_nquads(sorted_path, output / relative)
        graph_counts = {
            "asserted": len(graphs.asserted),
            "derived": len(graphs.derived),
            "projection": len(graphs.projection),
        }
        asserted_packs = [
            {
                "content": {
                    "byteLength": receipt.content_byte_length,
                    "digest": receipt.content_digest,
                    "mediaType": "application/n-quads",
                    "quadCount": receipt.content_quad_count,
                },
                "dependencies": [],
                "graphCounts": graph_counts,
                "kind": "aggregate",
                "packId": "urn:ref:atlas:pack:"
                + receipt.content_digest.removeprefix("sha256:"),
                "path": relative.as_posix(),
                "rings": [],
                "sourceReleases": [],
                "transport": {
                    "byteLength": receipt.transport_byte_length,
                    "compression": "zstd",
                    "digest": receipt.transport_digest,
                    "mediaType": "application/zstd",
                },
            }
        ]
    asserted_inventory_digest = _graph_inventory_digest(asserted_packs, "asserted")
    if not releases and (
        asserted_packs[0]["graphCounts"]["projection"]
        or asserted_packs[0]["graphCounts"]["derived"]
    ):
        asserted_packs[0]["inputAssertedDigest"] = asserted_inventory_digest
    packs = list(asserted_packs)
    if releases:
        for role, graph in (
            ("projection", graphs.projection),
            ("derived", graphs.derived),
        ):
            view = _write_view_pack(
                output,
                role=role,
                graph=graph,
                asserted_packs=asserted_packs,
                asserted_inventory_digest=asserted_inventory_digest,
            )
            if view is not None:
                packs.append(view)
    packs.sort(key=lambda pack: pack["packId"])
    graph_descriptors = []
    for role in ("asserted", "projection", "derived"):
        role_packs = [pack for pack in packs if pack["graphCounts"][role]]
        graph_descriptors.append(
            {
                "id": DISTRIBUTION_ID + ":" + role,
                "inventoryDigest": _graph_inventory_digest(packs, role),
                "packCount": len(role_packs),
                "quadCount": sum(pack["graphCounts"][role] for pack in role_packs),
                "role": role,
            }
        )
    return packs, graph_descriptors


def _file_member(path: Path, *, role: str, media_type: str) -> dict[str, Any]:
    return {
        "byteLength": path.stat().st_size,
        "digest": _sha256_file(path),
        "mediaType": media_type,
        "path": path.name,
        "role": role,
    }


def _trusted_writer_receipt_checks(
    output: Path,
    *,
    manifest: Mapping[str, Any],
) -> dict[str, Any]:
    """Reconcile a trusted writer's receipts without rereading RDF content."""

    ATLAS_VALIDATE._check_pack_manifest(manifest)
    expected_files = {
        "atlas-acceptance.json",
        "atlas-manifest.json",
        "atlas-producer-validation.json",
        "atlas-source-accounting.json",
        *(pack["path"] for pack in manifest["packs"]),
    }
    observed_files = {
        path.relative_to(output).as_posix()
        for path in output.rglob("*")
        if path.is_file() or path.is_symlink()
    }
    if observed_files != expected_files:
        raise ValueError(
            "distribution member closure differs: "
            f"expected={sorted(expected_files)}, observed={sorted(observed_files)}"
        )

    stored_byte_length = 0
    for pack in manifest["packs"]:
        path = output / pack["path"]
        transport = pack["transport"]
        if path.is_symlink() or not path.is_file():
            raise ValueError(f"stored pack is missing or unsafe: {pack['path']}")
        if (
            path.stat().st_size != transport["byteLength"]
            or _sha256_file(path) != transport["digest"]
        ):
            raise ValueError(f"stored pack transport differs: {pack['path']}")
        expected_pack_id = (
            "urn:ref:atlas:pack:"
            + pack["content"]["digest"].removeprefix("sha256:")
        )
        if pack["packId"] != expected_pack_id:
            raise ValueError(f"stored pack identity differs: {pack['path']}")
        stored_byte_length += transport["byteLength"]

    for member in manifest["members"]:
        path = output / member["path"]
        if path.is_symlink() or not path.is_file():
            raise ValueError(f"manifest member is missing or unsafe: {member['path']}")
        if path.stat().st_size != member["byteLength"] or _sha256_file(path) != member[
            "digest"
        ]:
            raise ValueError(f"serialized member differs from manifest: {path.name}")

    return {
        "checks": [
            "uncompressed byte lengths, SHA-256 digests, and quad counts captured while writing",
            "stored pack lengths and SHA-256 digests",
            "manifest graph pack counts, quad counts, and inventory digests",
            "manifest member lengths and digests",
            "closed distribution file inventory",
        ],
        "contentQuadCount": sum(
            pack["content"]["quadCount"] for pack in manifest["packs"]
        ),
        "graphQuadCounts": {
            row["role"]: row["quadCount"] for row in manifest["graphs"]
        },
        "mode": "trustedWriterReceipts",
        "packCount": len(manifest["packs"]),
        "status": "passed",
        "storedByteLength": stored_byte_length,
        "writerControls": [
            "canonical RDF renderer",
            "bounded external sort",
        ],
    }


def _compiled_producer_proof(
    report: Mapping[str, Any],
    *,
    binding: Mapping[str, Any],
    asserted_inventory_digest: str,
) -> dict[str, Any]:
    """Turn the in-memory constructor receipt into a portable proof."""

    if set(report) != {
        "bindingProfile",
        "checks",
        "constructorProfile",
        "counts",
        "mode",
        "shaclDataProof",
        "shaclMetaValidation",
        "sourceAccountingDigest",
        "sourceReleaseCount",
        "status",
    }:
        raise ValueError("compiled producer validation report fields differ")
    if (
        report.get("status") != "passed"
        or report.get("mode") != "compiledSourceProducerValidation"
        or report.get("constructorProfile") != _COMPILED_PRODUCER_PROFILE
        or report.get("shaclDataProof")
        != "compiledAgainstPinnedOntologyAndShapes"
        or report.get("shaclMetaValidation") != "pySHACL"
    ):
        raise ValueError("compiled producer validation report identity differs")
    binding_profile = report.get("bindingProfile")
    if binding_profile != dict(_COMPILED_PRODUCER_BINDING_PINS):
        raise ValueError("compiled producer validation binding profile differs")
    if any(
        binding.get(field) != digest
        for field, digest in _COMPILED_PRODUCER_BINDING_PINS.items()
    ):
        raise ValueError("candidate binding differs from compiled producer profile")
    if (
        not isinstance(report.get("sourceReleaseCount"), int)
        or report["sourceReleaseCount"] < 1
        or not isinstance(report.get("checks"), list)
        or not report["checks"]
    ):
        raise ValueError("compiled producer validation report is incomplete")
    return {
        "assertedInventoryDigest": asserted_inventory_digest,
        "binding": dict(binding),
        "checks": list(report["checks"]),
        "constructorProfile": report["constructorProfile"],
        "counts": dict(report["counts"]),
        "implementationDigest": _COMPILED_PRODUCER_IMPLEMENTATION_DIGEST,
        "mode": report["mode"],
        "shaclDataProof": report["shaclDataProof"],
        "shaclMetaValidation": report["shaclMetaValidation"],
        "sourceAccountingDigest": report["sourceAccountingDigest"],
        "sourceReleaseCount": report["sourceReleaseCount"],
        "status": report["status"],
        "type": "AtlasProducerValidation",
        "version": "3.0",
    }


def _check_compiled_validation_report(
    report: Mapping[str, Any],
    *,
    manifest: Mapping[str, Any],
    accounting_path: Path,
) -> None:
    """Bind the portable producer proof to the exact serialized candidate."""

    if set(report) != {
        "assertedInventoryDigest",
        "binding",
        "checks",
        "constructorProfile",
        "counts",
        "implementationDigest",
        "mode",
        "shaclDataProof",
        "shaclMetaValidation",
        "sourceAccountingDigest",
        "sourceReleaseCount",
        "status",
        "type",
        "version",
    }:
        raise ValueError("compiled producer validation proof fields differ")
    if (
        report.get("type") != "AtlasProducerValidation"
        or report.get("version") != "3.0"
        or report.get("status") != "passed"
        or report.get("mode") != "compiledSourceProducerValidation"
        or report.get("constructorProfile") != _COMPILED_PRODUCER_PROFILE
        or report.get("implementationDigest")
        != _COMPILED_PRODUCER_IMPLEMENTATION_DIGEST
        or report.get("shaclDataProof")
        != "compiledAgainstPinnedOntologyAndShapes"
        or report.get("shaclMetaValidation") != "pySHACL"
    ):
        raise ValueError("compiled producer validation proof identity differs")
    if report.get("binding") != manifest.get("binding"):
        raise ValueError("compiled producer validation binding differs")
    asserted_inventory_digest = next(
        row["inventoryDigest"]
        for row in manifest["graphs"]
        if row["role"] == "asserted"
    )
    if report.get("assertedInventoryDigest") != asserted_inventory_digest:
        raise ValueError("compiled producer asserted inventory digest differs")
    if any(
        manifest["binding"].get(field) != digest
        for field, digest in _COMPILED_PRODUCER_BINDING_PINS.items()
    ):
        raise ValueError("candidate binding differs from compiled producer profile")
    if report.get("counts") != manifest.get("counts"):
        raise ValueError("compiled producer counts differ from the candidate manifest")
    if report.get("sourceAccountingDigest") != _sha256_file(accounting_path):
        raise ValueError("compiled producer source accounting digest differs")
    if report.get("sourceReleaseCount") != manifest["counts"]["releases"]:
        raise ValueError("compiled producer source release count differs")
    if not isinstance(report.get("checks"), list) or not report["checks"]:
        raise ValueError("compiled producer validation proof is incomplete")


def _write_candidate_distribution(
    output: Path,
    graphs: BuildGraphs,
    releases: Sequence[ReleasePackPlan] = (),
    *,
    compiled_validation: Mapping[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Write and producer-validate a candidate that is not yet publishable."""

    if compiled_validation is None:
        raise ValueError("candidate writing requires compiled producer validation")
    compiled_counts = compiled_validation.get("counts")
    if not isinstance(compiled_counts, Mapping):
        raise TypeError("compiled producer validation has no count receipt")
    if (
        not isinstance(graphs.asserted, _MutationTrackedGraph)
        or graphs.sealed_asserted_revision is None
        or graphs.asserted.revision != graphs.sealed_asserted_revision
    ):
        raise ValueError(
            "asserted graph changed after compiled producer validation"
        )

    output.mkdir(parents=True, exist_ok=True)
    extras = sorted(path.name for path in output.iterdir())
    if extras:
        raise FileExistsError(f"distribution contains unexpected existing files: {extras}")

    accounting_path = output / "atlas-source-accounting.json"
    acceptance_path = output / "atlas-acceptance.json"
    manifest_path = output / "atlas-manifest.json"
    producer_validation_path = output / "atlas-producer-validation.json"
    packs, graph_descriptors = _write_graph_packs(output, graphs, releases)
    if graphs.asserted.revision != graphs.sealed_asserted_revision:
        raise ValueError("asserted graph changed while writing Atlas packs")
    accounting_path.write_bytes(
        ATLAS_VALIDATE.canonical_json_bytes(graphs.accounting)
    )

    binding_digests = ATLAS_VALIDATE._binding_digests()
    binding = {
        "validatorVersion": "3.0",
        "version": "3.0",
        **binding_digests,
    }
    producer_validation = _compiled_producer_proof(
        compiled_validation,
        binding=binding,
        asserted_inventory_digest=graph_descriptors[0]["inventoryDigest"],
    )
    producer_validation_path.write_bytes(
        ATLAS_VALIDATE.canonical_json_bytes(producer_validation)
    )
    acceptance_inputs = {
        "atlasDigest": graph_descriptors[0]["inventoryDigest"],
        **binding_digests,
        "producerValidationDigest": _sha256_file(producer_validation_path),
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

    manifest = {
        "binding": binding,
        "counts": dict(compiled_counts),
        "createdAt": CREATED_AT,
        "distributionId": DISTRIBUTION_ID,
        "format": "refspec-atlas-packed-nquads-3.0",
        "graphs": graph_descriptors,
        "members": [
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
            _file_member(
                producer_validation_path,
                role="producerValidation",
                media_type="application/json",
            ),
        ],
        "packs": packs,
        "schemaVersion": "3.0",
        "type": "AtlasManifest",
    }
    manifest["canonicalPayloadDigest"] = ATLAS_VALIDATE.canonical_sha256(
        manifest, terminal_lf=False
    )
    manifest_path.write_bytes(ATLAS_VALIDATE.canonical_json_bytes(manifest))

    schemas, registry = ATLAS_VALIDATE._schema_registry()
    for value, schema_name, label in (
        (manifest, "manifest", "manifest"),
        (graphs.accounting, "sourceAccounting", "source accounting"),
        (acceptance, "acceptance", "acceptance"),
        (producer_validation, "producerValidation", "producer validation"),
    ):
        ATLAS_VALIDATE._validate_json_schema(
            value,
            schema_name,
            schemas=schemas,
            registry=registry,
            label=label,
        )
    ATLAS_VALIDATE._check_manifest_digest(manifest)
    ATLAS_VALIDATE._check_pack_manifest(manifest)
    ATLAS_VALIDATE._check_binding_pins(manifest, acceptance)
    member_digests = {
        member["path"]: member["digest"] for member in manifest["members"]
    }
    ATLAS_VALIDATE._check_producer_validation(
        manifest,
        acceptance,
        producer_validation,
        member_digests,
    )
    ATLAS_VALIDATE._check_acceptance_metadata(
        manifest,
        acceptance,
        member_digests,
    )
    writer_receipts = _trusted_writer_receipt_checks(output, manifest=manifest)
    _check_compiled_validation_report(
        producer_validation,
        manifest=manifest,
        accounting_path=accounting_path,
    )
    graphs.release()
    return (
        {
            "independentFileConsumerValidation": {
                "performedByGenerator": False,
                "requiredForIndependentConsumers": True,
                "validator": (
                    "bindings/atlas/3.0/tools/validate.py:validate_distribution"
                ),
            },
            "compiledProducerValidation": producer_validation,
            "status": "passed",
            "trustedWriterReceiptChecks": writer_receipts,
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
    releases: Sequence[ReleasePackPlan] = (),
    generation_report: Mapping[str, Any],
    compiled_validation: Mapping[str, Any],
) -> dict[str, Any]:
    """Validate in a sibling temporary directory, then promote the result."""

    output.parent.mkdir(parents=True, exist_ok=True)
    counts = compiled_validation.get("counts")
    if not isinstance(counts, Mapping):
        raise TypeError("compiled producer validation has no count receipt")
    relation_scope = _production_relation_scope_from_counts(counts)
    report_distribution_path = _generation_report_distribution_path(output)
    with tempfile.TemporaryDirectory(
        prefix=f".{output.name}.candidate-",
        dir=output.parent,
    ) as raw_temporary_root:
        temporary_root = Path(raw_temporary_root)
        candidate = temporary_root / "distribution"
        result, manifest = _write_candidate_distribution(
            candidate,
            graphs,
            releases,
            compiled_validation=compiled_validation,
        )
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
    if len(descriptors) != 88:
        raise ValueError(f"expected 88 registry descriptors; found {len(descriptors)}")

    return {
        "expectedResources": sum(source.expected_resources for source in sources),
        "registryDescriptors": len(descriptors),
        "registryDescriptorsPin": {
            "digest": REGISTRY_DESCRIPTORS_EXPECTED_DIGEST,
            "path": REGISTRY_DESCRIPTORS_LOGICAL_PATH,
        },
        "sources": [
            _omit_absent_fields({
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
            })
            for source in sources
        ],
    }


def _release_direct_source_counts(release: LoadedRelease) -> dict[str, int]:
    """Count direct normalized records emitted from one source release."""

    return {
        "crossRingRelations": len(release.cross_ring_relations),
        "identifiers": sum(len(resource.identifiers) for resource in release.resources),
        "nativeRelations": len(release.relations),
        "resources": len(release.resources),
    }


def _release_label_role_conflict_count(release: LoadedRelease) -> int:
    value = release.metadata.get("labelRoleConflictCount", 0)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(
            f"{release.spec.key} labelRoleConflictCount is not a non-negative integer"
        )
    return value


def _release_pack_plan(release: LoadedRelease) -> ReleasePackPlan:
    return ReleasePackPlan(
        key=release.spec.key,
        source_release_iri=release.source_release_iri,
        atlas_release_iri=release.atlas_release_iri,
        ring=release.spec.ring,
        resource_count=len(release.resources),
    )


def _release_pack_plans(
    releases: Sequence[LoadedRelease],
) -> tuple[ReleasePackPlan, ...]:
    plans = tuple(_release_pack_plan(release) for release in releases)
    tokens = [_release_pack_token(plan) for plan in plans]
    if len(tokens) != len(set(tokens)):
        raise ValueError(
            "Atlas release keys collide after safe pack-path normalization"
        )
    return plans


def _direct_source_counts(
    releases: Sequence[LoadedRelease],
    *,
    label_count: int,
) -> dict[str, int]:
    """Aggregate direct normalized source counts without counting RDF projections."""

    counts = {
        "crossRingRelations": 0,
        "identifiers": 0,
        "labels": label_count,
        "nativeRelations": 0,
        "resources": 0,
    }
    for release in releases:
        for key, value in _release_direct_source_counts(release).items():
            counts[key] += value
    return counts


def build_distribution(output: Path) -> None:
    """Build, validate, and atomically promote the Atlas 3 distribution."""

    output.parent.mkdir(parents=True, exist_ok=True)
    releases = load_releases()
    inventory = verify_inputs(releases)
    source_validation = _validate_compiled_source_rows(releases)
    english_only_scan = source_validation.english_only_scan
    dropped_label_count = sum(release.dropped_label_count for release in releases)
    label_role_conflict_count = sum(
        _release_label_role_conflict_count(release) for release in releases
    )
    observed_counts = _direct_source_counts(
        releases,
        label_count=english_only_scan["emittedLabels"],
    )
    expected_counts = {
        "crossRingRelations": sum(
            release.spec.expected_cross_ring_relations for release in releases
        ),
        "nativeRelations": sum(
            release.spec.expected_relations for release in releases
        ),
        "resources": sum(release.spec.expected_resources for release in releases),
    }
    if {key: observed_counts[key] for key in expected_counts} != expected_counts:
        raise ValueError(
            f"direct source counts differ: expected={expected_counts}, actual={observed_counts}"
        )
    generation_report = {
        "createdAt": CREATED_AT,
        "directSourceCounts": observed_counts,
        "droppedLabelCount": dropped_label_count,
        "labelRoleConflictCount": label_role_conflict_count,
        "retainedEnglishLabelCount": observed_counts["labels"],
        "sourceLabelCountBeforeLanguageFilter": (
            observed_counts["labels"]
            + dropped_label_count
            + label_role_conflict_count
        ),
        "englishOnlyPolicy": {
            "atlasLabelLanguage": "en",
            "multilingualLabelTextInRdf": "prohibited",
            "rawMultilingualSources": "externalByExactLocatorAndDigest",
        },
        "englishOnlyScan": english_only_scan,
        "inputInventory": inventory,
        "sourceReleases": [
            _omit_absent_fields({
                "atlasRelease": release.atlas_release_iri,
                **_release_direct_source_counts(release),
                "key": release.spec.key,
                "metadata": _plain(release.metadata),
                "resourceId": release.spec.resource_id,
                "scope": release.spec.scope,
                "sourceRelease": release.source_release_iri,
            })
            for release in releases
        ],
        "type": "AtlasGenerationReport",
        "version": "3.0-development",
    }
    # Fail on nulls or non-interoperable numbers before constructing the large graph.
    ATLAS_VALIDATE.canonical_json_bytes(generation_report)
    pack_releases = _release_pack_plans(releases)
    graphs = _build_graphs(releases, include_projection=False)
    compiled_validation = _validate_compiled_producer_output(
        releases,
        graphs,
        source_validation,
    )
    del releases
    result = _write_distribution(
        output,
        graphs,
        releases=pack_releases,
        generation_report=generation_report,
        compiled_validation=compiled_validation,
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
