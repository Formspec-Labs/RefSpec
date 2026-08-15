"""Generate the full English Atlas 3.1 distribution from pinned registry data.

The generator reads every supported complete release or explicitly bounded
capture whose exact bytes are available locally. It preserves publisher label
roles, authority-scoped identifiers, globally reusable document identities,
semantic rings, direct authored relations, release provenance, and separately
evidenced mapping releases. It never invents inverse, transitive, or similarity
mappings.

Every build is cold: it parses each pinned input, reconstructs the whole graph,
and rewrites every pack. Output is a digest-pinned, compressed, release-local distribution. Explorer
indexes remain optional reproducible views, and no database service is needed.
The generator validates normalized rows and fixed constructors against the
pinned compiled SHACL profile; independent consumers still validate serialized
RDF. It never consumes an Atlas 1.x or Atlas 2.x graph, and it never imports the
archived generated mapping pairs under ``research/evidence``.
"""

from __future__ import annotations

import argparse
import ast
import dataclasses
import hashlib
import heapq
import importlib.util
import json
import re
import sys
import tempfile
import time
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable, Mapping, Sequence
from contextlib import ExitStack
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from types import MappingProxyType
from typing import Any, TextIO
from typing import Literal as TypeLiteral
from urllib.parse import quote

try:  # Python 3.14+
    from compression import zstd
except ImportError:  # pragma: no cover - exercised on supported Python 3.10-3.13
    from backports import zstd

import pyarrow.parquet as pq
from rdflib import Dataset, Graph, Literal, URIRef
from rdflib.namespace import DCTERMS, PROV, RDF, SKOS, XSD

from refspec.atlas.compact_pack import CompactRecordRole, normalize_compact_record
from refspec.atlas.parquet_tables import TABLE_DIRECTORY, TABLE_NAMES, AtlasParquetTableWriter
from refspec.atlas.parquet_view import seal_atlas_parquet_view
from refspec.atlas.registry_claim_input import (
    ATLAS_CLAIM_RECORD_TYPE,
    ATLAS_CLAIM_RECORD_VERSION,
    AtlasRegistryClaimInput,
)
from refspec.atlas.v3_source_data import (
    LABEL_ROLES as SOURCE_LABEL_ROLES,
)
from refspec.atlas.v3_source_data import (
    MAPPING_REVIEW_METHODS,
    SEMANTIC_RINGS,
    MappingReviewMethod,
    RegistryCrossRingRelation,
    RegistryIdentifier,
    RegistryInputPin,
    RegistryMapping,
    RegistryMappingEvidence,
    RegistryMappingRelease,
    RegistryRelease,
    RegistrySupplementalSourceRecord,
    mapping_triple_digest,
)
from refspec.atlas.v3_source_data import (
    LabelRole as SourceLabelRole,
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
from refspec.release_model import canonical_sha256 as refspec_canonical_sha256
from refspec.vocabulary import is_english_language_tag

ROOT = Path(__file__).resolve().parents[1]
BINDING_ROOT = ROOT / "bindings" / "atlas" / "3.1"
if str(BINDING_ROOT / "tools") not in sys.path:
    sys.path.insert(0, str(BINDING_ROOT / "tools"))
DEFAULT_OUTPUT = ROOT / "output" / "atlas-3.1-full-2026-08-06" / "distribution"
SPICY_REGS_ROOT = ROOT.parent
COMPLETE_TOPOLOGY_SCOPE = "completeDeclaredTopology"
BOUNDED_SELECTION_SCOPE = "boundedReleaseSelection"
# The scope segment names what the distribution is. It is not decoration: this
# URN is what a consumer embeds in a snapshot pin, and a bounded artifact
# labelled `3.0-full-development` would be a name that lies about what it
# names. Retrofitting the segment after adoption moves every identifier, so
# both scopes are declared before either is published.
DISTRIBUTION_ID_PREFIXES = MappingProxyType(
    {
        COMPLETE_TOPOLOGY_SCOPE: "urn:ref:atlas:distribution:3.1-full-development:",
        BOUNDED_SELECTION_SCOPE: "urn:ref:atlas:distribution:3.1-bounded-development:",
    }
)
_DISTRIBUTION_IDENTITY_PROFILE = "atlas-3-source-accounting-content-identity-v1"
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
_COMPILED_PRODUCER_PROFILE = (
    "atlas-3-source-and-evidence-backed-mapping-v1"
)
_COMPILED_PRODUCER_MODE = (
    "compiledSourceAndEvidenceBackedMappingProducerValidation"
)
_CONSTRUCTION_SUMMARY_PROFILE = "atlas-3-release-local-construction-v1"
_LANGUAGE_SCOPE = {
    "includedLanguageFamilies": ["en"],
    "selectionRule": "bcp47-primary-language-subtag",
    "unselectedPublisherContent": "notRepresented",
    "wireLanguageTag": "en",
}
_CONSTRUCTION_SUMMARY_RECEIPT_PROFILE = (
    "atlas-3-authenticated-construction-summary-v1"
)
_ROLE_GRAPH_IDS = MappingProxyType(
    {
        "asserted": "urn:ref:atlas:graph:v3:asserted",
        "derived": "urn:ref:atlas:graph:v3:derived",
        "projection": "urn:ref:atlas:graph:v3:projection",
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
_SOURCE_CLAIM_ACCOUNTING_REASON = "source-fidelity-claim-record-v1"
_FALLBACK_SOURCE_NAMESPACES = MappingProxyType(
    {
        "loc-lst": "http://id.loc.gov/vocabulary/subjectSchemes/lst",
        "loc-cgpa": "http://id.loc.gov/vocabulary/subjectSchemes/cgpa",
        "icpsr-subject-thesaurus": (
            "https://www.icpsr.umich.edu/web/ICPSR/thesaurus/10001"
        ),
    }
)


class _StatusReporter:
    """Write rate-limited, artifact-neutral progress to a human-facing stream."""

    def __init__(
        self,
        *,
        enabled: bool,
        stream: TextIO = sys.stderr,
        interval_seconds: float = 15.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.enabled = enabled
        self.stream = stream
        self.interval_seconds = interval_seconds
        self.clock = clock
        self.started_at = clock()
        self.last_emitted_at: float | None = None

    def _write(
        self,
        phase: str,
        *,
        current: str | None = None,
        progress: tuple[int, int] | None = None,
        force: bool = False,
    ) -> None:
        if not self.enabled:
            return
        now = self.clock()
        if (
            not force
            and self.last_emitted_at is not None
            and now - self.last_emitted_at < self.interval_seconds
        ):
            return
        fields = [
            "atlas-build",
            f"elapsed={max(0.0, now - self.started_at):.1f}s",
            f"phase={json.dumps(phase, ensure_ascii=True)}",
        ]
        if progress is not None:
            fields.append(f"progress={progress[0]}/{progress[1]}")
        if current is not None:
            fields.append(f"current={json.dumps(current, ensure_ascii=True)}")
        print(" ".join(fields), file=self.stream, flush=True)
        self.last_emitted_at = now

    def phase(self, phase: str, *, current: str | None = None) -> None:
        self._write(phase, current=current, force=True)

    def progress(
        self,
        phase: str,
        completed: int,
        total: int,
        *,
        current: str | None = None,
    ) -> None:
        self._write(
            phase,
            current=current,
            progress=(completed, total),
            force=completed == total,
        )


_STATUS = _StatusReporter(enabled=False)


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
    supplemental_source_records: Sequence[RegistrySupplementalSourceRecord] = ()
    dropped_label_count: int = 0
    metadata: Mapping[str, Any] = dataclasses.field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ReleasePackPlan:
    """Small asserted-pack identity retained after normalized rows are freed."""

    key: str
    source_release_iri: str
    atlas_release_iri: str | None
    ring: str
    resource_count: int
    kind: TypeLiteral["sourceRelease", "mapping"] = "sourceRelease"


@dataclass(frozen=True, slots=True)
class ReleaseConstructionSeed:
    """Raw-input and endpoint facts used to derive one release-local build key."""

    key: str
    source_release_iri: str
    atlas_release_iri: str | None
    ring: str
    input_pins: tuple[Mapping[str, Any], ...]
    adapter_recipe_inputs: tuple[Mapping[str, Any], ...] = ()
    resource_profile: str | None = None
    scheme_iri: str | None = None
    registry_source_iri: str | None = None
    endpoint_release_keys: tuple[str, ...] = ()
    kind: TypeLiteral["sourceRelease", "mapping"] = "sourceRelease"


@dataclass(frozen=True, slots=True)
class PackWriteReceipt:
    """Exact content and transport facts captured while writing one pack."""

    content_byte_length: int
    content_digest: str
    content_quad_count: int
    transport_byte_length: int
    transport_digest: str


@dataclass(frozen=True, slots=True)
class PackContentReceipt:
    """Exact facts for one current canonical N-Quads stream."""

    byte_length: int
    digest: str
    quad_count: int


@dataclass(slots=True)
class ColdPackMaterialization:
    """Ledger of the packs one cold build wrote.

    Every build reconstructs and sorts current RDF and rewrites every pack.
    The reuse arm that once fed this is gone, and with the 3.1 bump so are the
    four cold-path constants that survived it in the wire --
    ``priorDistribution``, ``reuseCriterion``, ``reusedPackCount`` and
    ``reusedPacks`` said "no reuse happened" on every build ever produced.
    """

    rebuilt_paths: list[str] = dataclasses.field(default_factory=list)

    def report(self) -> dict[str, Any]:
        return {
            "currentCanonicalPackContent": "fullyRecomputedAndSorted",
            "graphConstruction": "fullRebuild",
            "mode": "coldPackMaterialization",
            "rebuiltPackCount": len(self.rebuilt_paths),
            "rebuiltPacks": sorted(self.rebuilt_paths),
        }


@dataclass(frozen=True, slots=True)
class CompiledProducerValidationReceipt:
    """Compact-row proof for pinned source and evidence-backed mapping rows."""

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
        source_module="refspec.registry.infrastructure.source_concept_release",
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
        source_module="refspec.registry.infrastructure.source_concept_release",
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
        source_module="refspec.registry.infrastructure.source_concept_release",
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
        source_module="refspec.registry.managed_releases.icpsr_managed_release",
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
REGISTRY_DESCRIPTORS_LOGICAL_PATH = "refspec/bindings/atlas/3.1/tests/registry-descriptors.nq"
REGISTRY_DESCRIPTORS_EXPECTED_DIGEST = (
    "sha256:45abf0930f93ab44c36cb59d5548379c18d0570158192e59da482aad66f5acff"
)
REGISTRY_DESCRIPTORS_PROOF = BINDING_ROOT / "tests" / "registry-descriptors.json"
REGISTRY_DESCRIPTORS_PROOF_LOGICAL_PATH = (
    "refspec/bindings/atlas/3.1/tests/registry-descriptors.json"
)
REGISTRY_DESCRIPTORS_PROOF_EXPECTED_DIGEST = (
    "sha256:a3b0a6a36c8520845b561642fa2eef564726f2ac52ed1abd20b1db15e471ac2a"
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
RKAF = ATLAS_VALIDATE.RKAF
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


def distribution_scope_profile(source_release_count: int) -> str:
    """Name a build's scope from the source releases its own ledger declares.

    This asks one question -- is this the complete code-declared release
    topology? -- of the single authority, ``_declared_construction_unit_keys``. A bounded selection is a subset of
    those keys and every declared unit contributes one ledger row, so the row
    count answers set membership exactly. There is deliberately no scope flag
    beside it: a second switch is a second thing to set wrong.
    """

    declared = len(_declared_construction_unit_keys())
    if source_release_count == declared:
        return COMPLETE_TOPOLOGY_SCOPE
    if 0 < source_release_count < declared:
        return BOUNDED_SELECTION_SCOPE
    raise ValueError(
        f"source accounting declares {source_release_count} source releases "
        f"against {declared} code-declared construction units"
    )


def distribution_identity(accounting: Mapping[str, Any]) -> str:
    """Derive one distribution's identity from the ledger content it labels.

    The source accounting is the closed record of exactly which source releases
    and which source records a distribution represents, so two builds over the
    same sources derive the same identity and two builds over different sources
    cannot share one. It is also the first identity-bearing document a build
    writes, which is why the identity is not the manifest digest: the manifest
    lists this ledger as a member, so a manifest-derived identity could never
    appear inside the ledger it covers. No field read here is a timestamp.

    The scope segment is read from the same closed content the digest covers,
    so it cannot be relabelled: editing ``totals`` to claim a wider scope
    changes the digest the identity carries beside it.
    """

    content = {
        key: value for key, value in accounting.items() if key != "distributionId"
    }
    if set(content) != {"inputs", "totals", "type", "version"}:
        raise ValueError(
            "distribution identity requires the closed source accounting content"
        )
    totals = content["totals"]
    if not isinstance(totals, Mapping) or not isinstance(
        totals.get("sourceReleases"), int
    ):
        raise ValueError("source accounting totals declare no source release count")
    prefix = DISTRIBUTION_ID_PREFIXES[
        distribution_scope_profile(totals["sourceReleases"])
    ]
    digest = _canonical_digest(
        {"content": content, "profile": _DISTRIBUTION_IDENTITY_PROFILE}
    )
    return prefix + digest.removeprefix("sha256:")


def _identified_source_accounting(content: Mapping[str, Any]) -> dict[str, Any]:
    """Close one source accounting document over its own content identity."""

    return {"distributionId": distribution_identity(content), **content}


def _distribution_id(accounting: Mapping[str, Any]) -> str:
    """Read a build's identity back by recomputing it from the labelled content."""

    identity = distribution_identity(accounting)
    if accounting.get("distributionId") != identity:
        raise ValueError("source accounting identity is not its own content digest")
    return identity


def _release_instant(issued: str) -> str:
    """Take one release's assertion instant from its own publication date."""

    try:
        canonical = date.fromisoformat(issued).isoformat()
    except (TypeError, ValueError) as error:
        raise ValueError(f"release issued date is not an ISO 8601 date: {issued!r}") from error
    if canonical != issued:
        raise ValueError(f"release issued date is not canonical YYYY-MM-DD: {issued!r}")
    return f"{issued}T00:00:00+00:00"


def _distribution_instant(releases: Iterable[LoadedRelease]) -> str:
    """Take a build's recorded instant from the newest release date it carries.

    A build clock would make two builds of identical content unequal, so the
    recorded instant is a fact of the pinned sources instead.
    """

    instants = [_release_instant(release.issued) for release in releases]
    if not instants:
        raise ValueError("a distribution instant requires at least one pinned release")
    return max(instants)


def _project_module_path(module_name: str) -> Path | None:
    """Resolve one project-owned Python module without importing it."""

    if module_name == "refspec":
        candidate = ROOT / "src" / "refspec" / "__init__.py"
    elif module_name.startswith("refspec."):
        relative = Path(*module_name.split(".")[1:])
        candidate = ROOT / "src" / "refspec" / relative.with_suffix(".py")
        if not candidate.is_file():
            candidate = ROOT / "src" / "refspec" / relative / "__init__.py"
    else:
        return None
    if candidate.is_symlink() or not candidate.is_file():
        return None
    return candidate


def _module_name_for_path(path: Path) -> str:
    relative = path.relative_to(ROOT / "src").with_suffix("")
    parts = list(relative.parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def _project_imports(path: Path) -> frozenset[str]:
    """Read local import edges from one Python module without executing it."""

    module_name = _module_name_for_path(path)
    package_parts = module_name.split(".")[:-1]
    imports: set[str] = set()
    tree = ast.parse(path.read_bytes(), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names if alias.name.startswith("refspec"))
            continue
        if not isinstance(node, ast.ImportFrom):
            continue
        if node.level:
            keep = len(package_parts) - (node.level - 1)
            if keep < 0:
                continue
            base_parts = package_parts[:keep]
            if node.module:
                base_parts.extend(node.module.split("."))
            base = ".".join(base_parts)
        else:
            base = node.module or ""
        if not base.startswith("refspec"):
            continue
        imports.add(base)
        for alias in node.names:
            if alias.name != "*":
                imports.add(f"{base}.{alias.name}")
    return frozenset(imports)


def _adapter_group_module(key: str, *, kind: str) -> str | None:
    """Return the declaration module whose edits affect this release group."""

    from refspec.atlas.v3_registry_alignments import (
        REGISTRY_ALIGNMENT_ENDPOINT_RELEASE_KEYS,
        REGISTRY_MAPPING_RELEASE_KEYS,
    )
    from refspec.atlas.v3_registry_codes import REGISTRY_CODE_RELEASE_KEYS
    from refspec.atlas.v3_registry_large import LARGE_REGISTRY_RELEASE_KEYS
    from refspec.atlas.v3_registry_nonemitters import REGISTRY_NONEMITTER_RELEASE_KEYS
    from refspec.atlas.v3_registry_vocabularies import REGISTRY_VOCABULARY_RELEASE_KEYS

    groups = (
        (REGISTRY_VOCABULARY_RELEASE_KEYS, "refspec.atlas.v3_registry_vocabularies"),
        (LARGE_REGISTRY_RELEASE_KEYS, "refspec.atlas.v3_registry_large"),
        (REGISTRY_CODE_RELEASE_KEYS, "refspec.atlas.v3_registry_codes"),
        (REGISTRY_NONEMITTER_RELEASE_KEYS, "refspec.atlas.v3_registry_nonemitters"),
        (
            REGISTRY_ALIGNMENT_ENDPOINT_RELEASE_KEYS | REGISTRY_MAPPING_RELEASE_KEYS,
            "refspec.atlas.v3_registry_alignments",
        ),
    )
    matches = [module for keys, module in groups if key in keys]
    if len(matches) > 1:
        raise ValueError(f"construction unit belongs to multiple adapter groups: {key}")
    if kind == "mapping" and matches != ["refspec.atlas.v3_registry_alignments"]:
        raise ValueError(f"mapping construction unit has no alignment adapter: {key}")
    return matches[0] if matches else None


def _adapter_recipe_inputs(
    *,
    key: str,
    kind: str,
    source_module: str | None,
) -> tuple[dict[str, Any], ...]:
    """Pin the portable release adapter closure without parsing source bytes."""

    paths: set[Path] = set()
    group_module = _adapter_group_module(key, kind=kind)
    if group_module is not None:
        group_path = _project_module_path(group_module)
        if group_path is None:
            raise FileNotFoundError(f"Atlas adapter module is missing: {group_module}")
        # The group file owns declarations and dispatch. Its imports include
        # unrelated releases, so only its own bytes are a group-wide input.
        paths.add(group_path)
    pending = [source_module] if source_module else []
    visited_modules: set[str] = set()
    while pending:
        module_name = pending.pop()
        if module_name in visited_modules:
            continue
        visited_modules.add(module_name)
        module_path = _project_module_path(module_name)
        if module_path is None:
            continue
        paths.add(module_path)
        pending.extend(sorted(_project_imports(module_path) - visited_modules))
    return tuple(
        {
            "byteLength": path.stat().st_size,
            "path": path.relative_to(ROOT).as_posix(),
            "sha256": _sha256_file(path),
        }
        for path in sorted(paths, key=lambda item: item.relative_to(ROOT).as_posix())
    )


def _adapter_recipe_digest(
    *,
    kind: str,
    inputs: Sequence[Mapping[str, Any]],
) -> str:
    """Pin the adapter sources one construction unit was built from.

    Paths and their content digests, nothing observed. The runtime block this
    used to fold in -- interpreter version, installed library versions, the
    Unicode database -- made two builds of the same tree from two entry points
    produce two manifest digests; `uv.lock` and `.python-version` pin that
    declaratively, and the release workflow is the one place a build is
    signed.
    """

    return _canonical_digest(
        {
            "constructionProfile": _CONSTRUCTION_SUMMARY_PROFILE,
            "inputs": [_plain(row) for row in inputs],
            "kind": kind,
        }
    )








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


def _is_registry_claim_payload(value: object) -> bool:
    return (
        isinstance(value, Mapping)
        and value.get("type") == ATLAS_CLAIM_RECORD_TYPE
        and value.get("schemaVersion") == ATLAS_CLAIM_RECORD_VERSION
        and isinstance(value.get("claims"), Sequence)
        and not isinstance(value.get("claims"), (str, bytes))
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
                if not is_english_language_tag(explicit_language):
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
                    english_values: list[str] = []
                    for language, values in sorted(
                        language_values.items(),
                        key=lambda item: (
                            item[0].casefold() != "en",
                            item[0].casefold(),
                            item[0],
                        ),
                    ):
                        if is_english_language_tag(language):
                            english_values.extend(values)
                        else:
                            dropped.append(
                                {
                                    "kind": "languageMap",
                                    "language": language,
                                    "path": "/".join(child_path),
                                    "values": values,
                                }
                            )
                    child = (
                        {"en": list(dict.fromkeys(english_values))}
                        if english_values
                        else {}
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
            seen_tagged_values: set[str] = set()
            base_preferred_values = {
                raw_child.get("value")
                for raw_child in item
                if isinstance(raw_child, Mapping)
                and raw_child.get("role") == "preferred"
                and isinstance(raw_child.get("value"), str)
                and any(
                    isinstance(raw_child.get(key), str)
                    and str(raw_child[key]).casefold() == "en"
                    for key in raw_child
                    if str(key).lower() in _EXPLICIT_LANGUAGE_KEYS
                )
            }
            for index, raw_child in enumerate(item):
                child = visit(raw_child, (*path, str(index)))
                if child is not _DROP_LANGUAGE_VALUE:
                    if isinstance(child, Mapping) and any(
                        str(key).lower() in _EXPLICIT_LANGUAGE_KEYS
                        for key in child
                    ):
                        raw_language = (
                            next(
                                (
                                    raw_child[key]
                                    for key in raw_child
                                    if str(key).lower() in _EXPLICIT_LANGUAGE_KEYS
                                ),
                                None,
                            )
                            if isinstance(raw_child, Mapping)
                            else None
                        )
                        is_variant = (
                            isinstance(raw_language, str)
                            and raw_language.casefold() != "en"
                        )
                        if is_variant and child.get("value") in base_preferred_values:
                            continue
                        if (
                            is_variant
                            and base_preferred_values
                            and child.get("role") == "preferred"
                        ):
                            child = {**child, "role": "alternate"}
                        identity = json.dumps(
                            _plain(child),
                            ensure_ascii=False,
                            separators=(",", ":"),
                            sort_keys=True,
                        )
                        if identity in seen_tagged_values:
                            continue
                        seen_tagged_values.add(identity)
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
    allow_untagged_explicit_language: bool = False,
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
                    if child is None and allow_untagged_explicit_language:
                        pass
                    else:
                        explicit_tags += 1
                    if not (
                        child is None and allow_untagged_explicit_language
                    ) and not (
                        isinstance(child, str)
                        and (
                            child.casefold() == "en"
                            or (
                                allow_untagged_explicit_language
                                and is_english_language_tag(child)
                            )
                        )
                    ):
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
                    "recursiveEnglishFamilyLanguageMapsAndTaggedValuesV2"
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
                    "recursiveEnglishFamilyLanguageMapsAndJsonLdLanguageValuesV2"
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
            supplemental_source_records=release.supplemental_source_records,
            dropped_label_count=release.dropped_label_count,
            metadata=release.metadata,
        )
    )


def _declared_construction_unit_keys() -> frozenset[str]:
    """Return the code-declared release topology without opening source bytes."""

    from refspec.atlas.v3_registry_alignments import (
        REGISTRY_ALIGNMENT_ENDPOINT_RELEASE_KEYS,
        REGISTRY_MAPPING_RELEASE_KEYS,
    )
    from refspec.atlas.v3_registry_codes import REGISTRY_CODE_RELEASE_KEYS
    from refspec.atlas.v3_registry_large import LARGE_REGISTRY_RELEASE_KEYS
    from refspec.atlas.v3_registry_nonemitters import REGISTRY_NONEMITTER_RELEASE_KEYS
    from refspec.atlas.v3_registry_vocabularies import REGISTRY_VOCABULARY_RELEASE_KEYS

    direct = {
        spec.key
        for spec in SOURCE_SPECS
        if spec.key not in {"elsst-r6", "federal-register-thesaurus-2025"}
    }
    return frozenset(
        {
            *direct,
            *REGISTRY_VOCABULARY_RELEASE_KEYS,
            *LARGE_REGISTRY_RELEASE_KEYS,
            *REGISTRY_CODE_RELEASE_KEYS,
            *REGISTRY_NONEMITTER_RELEASE_KEYS,
            *REGISTRY_ALIGNMENT_ENDPOINT_RELEASE_KEYS,
            *REGISTRY_MAPPING_RELEASE_KEYS,
        }
    )


def split_construction_unit_keys(
    include_keys: frozenset[str],
) -> tuple[frozenset[str], frozenset[str]]:
    """Split one release allowlist into source keys and mapping keys.

    ``load_releases`` and ``load_mapping_releases`` each refuse a key they do
    not declare, so a bounded caller has to route every requested key to the
    loader that owns it.
    """

    from refspec.atlas.v3_registry_alignments import REGISTRY_MAPPING_RELEASE_KEYS

    if not include_keys:
        raise ValueError("a bounded Atlas build names at least one release key")
    unknown = sorted(include_keys - _declared_construction_unit_keys())
    if unknown:
        raise ValueError(f"unknown Atlas construction units: {unknown}")
    mapping_keys = include_keys & REGISTRY_MAPPING_RELEASE_KEYS
    return frozenset(include_keys - mapping_keys), frozenset(mapping_keys)


# Registrant populations live in the entity-registry object, never in the
# Atlas: a sealed reference artifact cannot track registry churn (REF-030).
# The scheme refusal breaks any loader that reintroduces one of these
# authorities; the IRI refusal breaks a renamed release that re-ingests the
# same records under a new authority name.
REGISTRANT_POPULATION_SCHEME_PREFIXES = (
    "urn:ref:atlas-resource-scheme:cage-authority",
    "urn:ref:atlas-resource-scheme:epa-substance-identifiers",
    "urn:ref:atlas-resource-scheme:nppes-npi-authority",
    "urn:ref:atlas-resource-scheme:uei-authority",
)
REGISTRANT_POPULATION_IRI_PREFIXES = (
    "urn:ref:dla-cage-facility:",
    "urn:ref:epa-substance:",
    "urn:ref:nppes-provider:",
    "urn:ref:sam-entity:",
)


def _refuse_registrant_population_release(release: LoadedRelease) -> None:
    if release.scheme_iri.startswith(REGISTRANT_POPULATION_SCHEME_PREFIXES):
        raise ValueError(
            "registrant-population authority belongs to the entity registry, "
            f"not the Atlas (REF-030): {release.spec.key} uses {release.scheme_iri}"
        )
    for resource in release.resources:
        if resource.iri.startswith(REGISTRANT_POPULATION_IRI_PREFIXES):
            raise ValueError(
                "registrant-population records belong to the entity registry, "
                f"not the Atlas (REF-030): {release.spec.key} emits {resource.iri}"
            )


# Document populations are acquired by SpicyRegs, never enumerated in the
# Atlas: CBO publishes continuously, FCC ECFS holds six figures of
# proceedings, and GovInfo issues hundreds of CFR volumes a year, so no
# sealed reference artifact can hold an honest census of them (REF-031).
# The scheme refusal breaks a loader that reintroduces one of these
# document authorities; the IRI refusal breaks a renamed release that
# re-ingests the same documents. FCC's proceedings shared the
# ``fcc-ecfs-native-controls`` scheme with bureaus, filing types, and access
# statuses -- all of which stay -- so only the IRI prefix can name it.
#
# Amended by REF-032: GAO products are refused too. REF-031 exempted the one
# GAO report page because it witnessed the observed-topics unit; that unit has
# now left, and a report page was always a document population by this
# decision's own criterion. The FCC controls that shared the proceedings'
# scheme also left, but their scheme stays unguarded here -- FCC's *published*
# bureau roster is a named REF-032 follow-up and belongs under it.
DOCUMENT_POPULATION_SCHEME_PREFIXES = (
    "urn:ref:atlas-resource-scheme:cbo-publication-identifiers",
    "urn:ref:atlas-resource-scheme:gao-report-identifiers",
    "urn:ref:atlas-resource-scheme:govinfo-cfr-packages",
)
DOCUMENT_POPULATION_IRI_PREFIXES = (
    "https://www.cbo.gov/publication/",
    "https://www.gao.gov/products/",
    "urn:ref:govinfo-cfr-package:",
    "urn:ref:source-concept:v2:fcc-ecfs-proceedings:",
)


def _refuse_document_population_release(release: LoadedRelease) -> None:
    if release.scheme_iri.startswith(DOCUMENT_POPULATION_SCHEME_PREFIXES):
        raise ValueError(
            "document-population authority belongs to SpicyRegs, "
            f"not the Atlas (REF-031): {release.spec.key} uses {release.scheme_iri}"
        )
    for resource in release.resources:
        if resource.iri.startswith(DOCUMENT_POPULATION_IRI_PREFIXES):
            raise ValueError(
                "document-population records belong to SpicyRegs, "
                f"not the Atlas (REF-031): {release.spec.key} emits {resource.iri}"
            )


# Observed inventories are not reference (REF-032). The Atlas carries what a
# publisher *wrote down* -- a documented code list, a field dictionary, a
# thesaurus, an account roster. It does not carry the distinct values someone
# scanned out of that publisher's records, the first page of a paginated
# roster, the radio buttons on a search form, or a regex inferred from two
# examples. Those are observations about a data set; they age the moment the
# data moves, and a sealed reference artifact cannot honour them.
#
# The refusal is keyed to the *substrate* rather than to the resource, because
# the resource itself may legitimately return: FCC's published bureau roster,
# the Federal Register's documented document types, GAO's published /topics
# index, and the completed Federal Hierarchy roster are all named follow-ups
# of REF-032 and all belong in the Atlas the day they are captured from the
# publisher's own list. What may never return is a release built out of the
# bytes below -- a SpicyRegs Parquet snapshot, a 25-filing API response, a
# 15,777-row personnel roster, one product page, one alphabetical first page.
OBSERVED_INVENTORY_INPUT_PATH_PREFIXES = (
    # The SpicyRegs data plane: RefSpec's build reads no Parquet snapshot of
    # SpicyRegs's acquired records, and no capture derived from one.
    "output/registry-real-data-sources/regulatory-native-current/",
    "research/evidence/regulatory-native-controls-2026-08-03/",
    # Rosters and responses that were sampled, not published as lists.
    "output/registry-real-data-sources/OPM-PLUM-all-data-",
    "output/registry-real-data-sources/fh-orgs-default-page.json",
    "output/registry-real-data-sources/fh-orgs-sub-tier-page.json",
    "output/registry-real-data-sources/ferc-accessibility-tips.html",
    "tests/fixtures/agrovoc_thesaurus/",
    "tests/fixtures/epa_enterprise_vocabulary/",
    "tests/fixtures/fcc_ecfs_codes/",
    "tests/fixtures/gao_cra_facets/",
    "tests/fixtures/gao_topics/",
    "tests/fixtures/nalt_core/",
    "tests/fixtures/nrc_adams_codes/",
)
# Scheme strings that name the observation itself. A documented successor for
# the same resource uses the bare scheme and passes.
OBSERVED_INVENTORY_SCHEME_PREFIXES = (
    "urn:ref:atlas-resource-scheme:epa-enterprise-vocabulary:captured-label-tree",
    "urn:ref:atlas-resource-scheme:nrc-adams-identifiers:identifier-shapes",
    "urn:ref:atlas-resource-scheme:nrc-adams-native-controls:observed-structure",
)
# Minted namespaces no publisher-written list could ever occupy: a search
# widget's facet value, a search application's control label, a regexed shape,
# a Counter over another release's rows, an agency-code census that duplicates
# SpicyRegs's own ``agency_stats``, and a parse residue whose members include
# ``"44 CFR Part 64"`` and a bare ``"Rule"``.
OBSERVED_INVENTORY_IRI_PREFIXES = (
    "urn:ref:gao-cra-facet:",
    "urn:ref:nrc-adams-control:",
    "urn:ref:nrc-adams-identifier-shape:",
    "urn:ref:source-concept:v2:federal-register-unresolved-agency-name:",
    "urn:ref:source-concept:v2:ferc-accession-formats:",
    "urn:ref:source-concept:v2:opm-plum:",
    "urn:ref:source-concept:v2:regulations-gov-docket-agency-code:",
    "urn:ref:source-concept:v2:regulations-gov-document-agency-code:",
    "urn:ref:source-concept:v2:unified-agenda-agency-code:",
    "urn:ref:treasury-fast-book:fund-type:",
)


def _refuse_observed_inventory_release(release: LoadedRelease) -> None:
    for pin in (*release.spec.input_pins, release.spec):
        if pin.logical_path.startswith(OBSERVED_INVENTORY_INPUT_PATH_PREFIXES):
            raise ValueError(
                "observed inventories are not reference "
                f"(REF-032): {release.spec.key} reads {pin.logical_path}"
            )
    if release.scheme_iri.startswith(OBSERVED_INVENTORY_SCHEME_PREFIXES):
        raise ValueError(
            "observed inventories are not reference "
            f"(REF-032): {release.spec.key} uses {release.scheme_iri}"
        )
    for resource in release.resources:
        if resource.iri.startswith(OBSERVED_INVENTORY_IRI_PREFIXES):
            raise ValueError(
                "observed inventories are not reference "
                f"(REF-032): {release.spec.key} emits {resource.iri}"
            )


def load_releases(
    include_keys: frozenset[str] | None = None,
    *,
    registry_claim_inputs: Mapping[str, AtlasRegistryClaimInput] | None = None,
) -> tuple[LoadedRelease, ...]:
    """Load normalized releases and optionally add lossless claim bundles.

    ``registry_claim_inputs`` is keyed by the existing release key. Each value
    supplies an artifact path and external manifest digest; the generic Atlas
    adapter verifies both before the release enters construction.
    """

    from refspec.atlas.registry_claim_input import inject_registry_claim_release
    from refspec.atlas.v3_registry_alignments import (
        REGISTRY_ALIGNMENT_ENDPOINT_RELEASE_KEYS,
        load_all_registry_alignment_endpoint_releases,
    )
    from refspec.atlas.v3_registry_codes import (
        REGISTRY_CODE_RELEASE_KEYS,
        load_registry_code_releases,
    )
    from refspec.atlas.v3_registry_large import (
        LARGE_REGISTRY_RELEASE_KEYS,
        load_large_registry_releases,
    )
    from refspec.atlas.v3_registry_nonemitters import (
        REGISTRY_NONEMITTER_RELEASE_KEYS,
        load_registry_nonemitter_releases,
    )
    from refspec.atlas.v3_registry_vocabularies import (
        REGISTRY_VOCABULARY_RELEASE_KEYS,
        load_all_registry_vocabulary_releases,
    )
    loaders = {
        "sourceConceptRelease": _load_crs,
        "managedRelease": _load_elsst,
        "managedReleaseWithCoverageUnion": _load_icpsr,
    }
    claim_inputs = {} if registry_claim_inputs is None else registry_claim_inputs
    releases: list[LoadedRelease] = []
    selected_specs = tuple(
        spec
        for spec in SOURCE_SPECS
        if spec.key not in {"elsst-r6", "federal-register-thesaurus-2025"}
        and (include_keys is None or spec.key in include_keys)
    )
    for position, spec in enumerate(selected_specs, start=1):
        _STATUS.progress(
            "load-direct-releases",
            position - 1,
            len(selected_specs),
            current=spec.key,
        )
        release = loaders[spec.kind](spec)
        releases.append(_validate_loaded_release(release))
        _STATUS.progress(
            "load-direct-releases",
            position,
            len(selected_specs),
            current=spec.key,
        )

    selected = None if include_keys is None else include_keys
    _STATUS.phase("load-registry-releases")
    registry_releases = (
        *load_all_registry_vocabulary_releases(
            only_keys=None
            if selected is None
            else selected & REGISTRY_VOCABULARY_RELEASE_KEYS,
            registry_claim_inputs=claim_inputs,
        ),
        *load_large_registry_releases(
            only_keys=None if selected is None else selected & LARGE_REGISTRY_RELEASE_KEYS
        ),
        *load_registry_code_releases(
            ROOT,
            only_keys=None if selected is None else selected & REGISTRY_CODE_RELEASE_KEYS,
        ),
        *load_registry_nonemitter_releases(
            ROOT,
            only_keys=None if selected is None else selected & REGISTRY_NONEMITTER_RELEASE_KEYS,
        ),
        *load_all_registry_alignment_endpoint_releases(
            only_keys=None
            if selected is None
            else selected & REGISTRY_ALIGNMENT_ENDPOINT_RELEASE_KEYS
        ),
    )
    _validate_registry_release_descriptors(registry_releases)
    registry_keys = {release.key for release in registry_releases}
    unknown_claim_inputs = sorted(set(claim_inputs) - registry_keys)
    if unknown_claim_inputs:
        raise ValueError(
            "registry claim inputs do not match loaded registry releases: "
            f"{unknown_claim_inputs}"
        )
    registry_releases = tuple(
        inject_registry_claim_release(release, claim_inputs[release.key])
        if release.key in claim_inputs
        else release
        for release in registry_releases
    )
    releases.extend(_adapt_registry_release(release) for release in registry_releases)
    _STATUS.progress(
        "load-registry-releases",
        len(registry_releases),
        len(registry_releases),
    )
    if include_keys is not None:
        observed = {release.spec.key for release in releases}
        missing = sorted(include_keys - observed)
        if missing:
            raise ValueError(f"selective Atlas source loaders do not know keys: {missing}")
    for release in releases:
        _refuse_registrant_population_release(release)
        _refuse_document_population_release(release)
        _refuse_observed_inventory_release(release)
    return tuple(releases)


def load_mapping_releases(
    include_keys: frozenset[str] | None = None,
) -> tuple[RegistryMappingRelease, ...]:
    """Load evidence-backed mapping artifacts independently from vocabularies."""

    from refspec.atlas.v3_registry_alignments import (
        load_all_registry_mapping_releases,
    )

    if include_keys is not None and not include_keys:
        return ()
    _STATUS.phase("load-mapping-releases")
    releases = tuple(load_all_registry_mapping_releases(only_keys=include_keys))
    if include_keys is not None and {release.key for release in releases} != set(include_keys):
        raise ValueError("selective Atlas mapping loaders do not know every dirty key")
    _validate_registry_mapping_release_descriptors(releases)
    _STATUS.progress("load-mapping-releases", len(releases), len(releases))
    return releases


def _registry_source_descriptor_iri(resource_id: str) -> URIRef:
    return URIRef(
        "urn:ref:atlas-source-descriptor:" + quote(resource_id, safe="-._~")
    )


def _registry_primary_scheme_iri(resource_id: str) -> URIRef:
    return URIRef(
        "urn:ref:atlas-resource-scheme:" + quote(resource_id, safe="-._~")
    )


def _validated_registry_index_rows(
    index: Mapping[str, Any],
    descriptor_proof: Mapping[str, Any],
) -> tuple[Mapping[str, Any], ...]:
    actual_index_digest = _registry_index_content_digest(index)
    if index.get("indexDigest") != actual_index_digest:
        raise ValueError("Atlas registry index content digest differs")
    expected_index_id = (
        "urn:ref:atlas-index:" + actual_index_digest.removeprefix("sha256:")
    )
    if index.get("indexId") != expected_index_id:
        raise ValueError("Atlas registry index identity differs")

    artifact = descriptor_proof.get("artifact")
    proof_inputs = descriptor_proof.get("inputs")
    if not isinstance(artifact, Mapping) or not isinstance(proof_inputs, Mapping):
        raise TypeError("Atlas registry descriptor proof is incomplete")
    if artifact.get("sha256") != REGISTRY_DESCRIPTORS_EXPECTED_DIGEST:
        raise ValueError("Atlas registry descriptor proof pins a different dataset")
    if proof_inputs.get("atlasIndexDigest") != actual_index_digest:
        raise ValueError("Atlas registry index differs from the descriptor proof")

    rows = index.get("rows")
    if not isinstance(rows, list):
        raise TypeError("Atlas registry index has no rows")
    if any(not isinstance(row, Mapping) for row in rows):
        raise TypeError("Atlas registry index contains a non-object row")
    return tuple(rows)


def _registry_index_content_digest(index: Mapping[str, Any]) -> str:
    index_basis = {
        key: value
        for key, value in index.items()
        if key not in {"indexDigest", "indexId"}
    }
    return refspec_canonical_sha256(index_basis)


def _registry_index_rows() -> tuple[Mapping[str, Any], ...]:
    _verify_pinned_file(
        REGISTRY_DESCRIPTORS_PROOF,
        logical_path=REGISTRY_DESCRIPTORS_PROOF_LOGICAL_PATH,
        expected_digest=REGISTRY_DESCRIPTORS_PROOF_EXPECTED_DIGEST,
    )
    return _validated_registry_index_rows(
        _read_json(ROOT / "portfolio" / "atlas-index-v0.json"),
        _read_json(REGISTRY_DESCRIPTORS_PROOF),
    )


def _validate_registry_mapping_release_policy(
    release: RegistryMappingRelease,
    *,
    descriptors: Graph,
    index_rows: Sequence[Mapping[str, Any]],
) -> None:
    """Reconcile one mapping release with its mapping-only registry policy."""

    source_descriptor = _registry_source_descriptor_iri(release.resource_id)
    if (source_descriptor, RDF.type, ATLAS.RegistrySource) not in descriptors:
        raise ValueError(
            f"{release.key} names unknown registry source {release.resource_id!r}"
        )

    dispositions = list(
        descriptors.objects(source_descriptor, ATLAS.memberDisposition)
    )
    if dispositions != [Literal("mappingAssertionsOnly")]:
        raise ValueError(
            f"{release.key} registry source {release.resource_id!r} is not "
            "mappingAssertionsOnly"
        )

    scheme = _registry_primary_scheme_iri(release.resource_id)
    if (scheme, RDF.type, ATLAS.ResourceScheme) in descriptors:
        raise ValueError(
            f"{release.key} mapping-only registry source unexpectedly has a "
            "ResourceScheme"
        )

    payloads = list(descriptors.objects(source_descriptor, ATLAS.descriptorPayload))
    if len(payloads) != 1 or not isinstance(payloads[0], Literal):
        raise ValueError(f"{release.key} registry source has no unique descriptor payload")
    try:
        descriptor_payload = json.loads(str(payloads[0]))
    except json.JSONDecodeError as error:
        raise ValueError(
            f"{release.key} registry source descriptor payload is not JSON"
        ) from error
    if not isinstance(descriptor_payload, Mapping):
        raise TypeError(
            f"{release.key} registry source descriptor payload is not an object"
        )
    if descriptor_payload.get("resourceId") != release.resource_id:
        raise ValueError(f"{release.key} registry source descriptor identity differs")
    if descriptor_payload.get("resourceKind") != "mappingReference":
        raise ValueError(
            f"{release.key} registry source is not a mappingReference"
        )

    resource_rows = [
        row for row in index_rows if row.get("resourceId") == release.resource_id
    ]
    if not resource_rows:
        raise ValueError(
            f"{release.key} registry source is absent from the Atlas index"
        )
    matching_rows = [
        row
        for row in resource_rows
        if row.get("sourceModule") == release.source_module
        and row.get("semanticRing") == release.ring
    ]
    if len(matching_rows) != 1:
        raise ValueError(
            f"{release.key} registry source module/ring differs from the Atlas index"
        )
    intended_uses = matching_rows[0].get("intendedUses")
    if not isinstance(intended_uses, list) or "mappingReference" not in intended_uses:
        raise ValueError(
            f"{release.key} Atlas index row is not a mappingReference"
        )


def _validate_registry_mapping_release_descriptors(
    releases: Sequence[RegistryMappingRelease],
) -> None:
    """Require every mapping release to pass registry admission policy."""

    descriptors = _registry_asserted_graph()
    index_rows = _registry_index_rows()
    for release in releases:
        _validate_registry_mapping_release_policy(
            release,
            descriptors=descriptors,
            index_rows=index_rows,
        )


def _validate_registry_release_descriptors(
    releases: Sequence[RegistryRelease],
) -> None:
    """Require each normalized release to match the pinned registry policy."""

    descriptors = _registry_asserted_graph()
    index_rows = _registry_index_rows()

    for release in releases:
        source_descriptor = _registry_source_descriptor_iri(release.resource_id)
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
            and row.get("semanticRing") == release.ring
            for row in index_rows
        ):
            raise ValueError(
                f"{release.key} source module/ring differs from the Atlas index"
            )


def _node_iri(prefix: str, basis: Any) -> URIRef:
    digest = _canonical_digest(basis).removeprefix("sha256:")
    return URIRef(f"urn:ref:{prefix}:{digest}")


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
    # The digest is the policy's IRI, so it is already published; a triple
    # restating it would be the node saying its own name back.
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
    # atlas:sourceDigest on a SourceRecord is defined as sha256 over this
    # record's own canonical nativePayload bytes -- never the caller-supplied
    # ``source_digest`` (which, for several producers, pins an upstream
    # observation/file digest instead). Asserting anything other than the
    # payload's own digest here is exactly the gap that let a record's
    # sourceDigest go unverified against the bytes it claims to represent;
    # the validator now recomputes and checks this same digest in
    # ``_check_native_payloads``. The caller-supplied ``source_digest`` still
    # feeds the node-identity basis above so existing SourceRecord IRIs are
    # unaffected by this change.
    content_source_digest = "sha256:" + hashlib.sha256(native_payload_bytes).hexdigest()
    graph.add((node, RDF.type, ATLAS.SourceRecord))
    graph.add((node, ATLAS.inSourceRelease, source_release))
    graph.add((node, ATLAS.sourceDigest, Literal(content_source_digest)))
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
        allow_untagged_explicit_language=(
            _is_registry_claim_payload(native_payload)
        ),
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
            Literal(identifier_row.value),
        )
    )
    graph.add((identifier, ATLAS.identifierScheme, scheme))
    graph.add((identifier, ATLAS.identifies, resource))
    graph.add((identifier, ATLAS.sourceRecord, source_record))
    return identifier


def _review_method_for_assertion(
    assertion_type: URIRef,
    *,
    deterministic_transformation: bool = False,
) -> str:
    """Select the source-native warrant supported by an assertion's provenance."""

    if assertion_type in {
        ATLAS.CrossRingRelationAssertion,
        ATLAS.NativeRelationAssertion,
        ATLAS.SourceAssignment,
    }:
        return (
            "deterministicTransformation"
            if deterministic_transformation
            else "publisherAssertion"
        )
    raise ValueError(f"unsupported assertion review method: {assertion_type}")


# The one warrant this producer cannot honour. A mapping whose evidence
# declares twoMachineAdjudication is claiming two independent machines
# adjudicated it, and since the machine-adjudication protocol landed on the
# Atlas 3.1 wire that claim obliges the distribution to carry the whole record
# set behind it: an rkaf:RelationComparisonContext, its complete
# rkaf:ResolverProofRecord support, their issuers and model lineages, and the
# rkaf:Artifact records that resolve the sealed request and every sealed
# response to bundled bytes. This producer emits none of those, so accepting
# the warrant would build a distribution that its own binding validator
# refuses -- a failure discovered at the end of a full registry build rather
# than at the input that caused it. It fails here instead, at intake.
UNEMITTABLE_MAPPING_REVIEW_METHODS = frozenset({"twoMachineAdjudication"})


def _mapping_review_method(review_method: MappingReviewMethod) -> str:
    """Resolve one explicit, binding-approved mapping warrant to its axis name."""

    if review_method not in MAPPING_REVIEW_METHODS:
        raise ValueError(f"unsupported mapping review method: {review_method!r}")
    if review_method in UNEMITTABLE_MAPPING_REVIEW_METHODS:
        raise ValueError(
            f"mapping review method {review_method!r} is not emittable by this "
            "producer: the Atlas 3.1 binding requires every assertion carrying it "
            "to be licensed by an rkaf:RelationComparisonContext with a complete, "
            "independent rkaf:ResolverProofRecord set resolving to bundled "
            "rkaf:Artifact records, and this writer emits no adjudication "
            "records at all. No registry source declares it today; wire the "
            "protocol's emission before one does."
        )
    return review_method


# The two mapping rings this producer cannot honour, for the same reason and
# with the same shape as the warrant above. Since ring temporal context landed
# on the Atlas 3.1 wire, a value-ring or legal-identity-ring MappingAssertion
# must carry an rkaf:hasEffectivePeriod resolving to a well-formed
# rkaf:EffectivePeriod -- a crosswalk between two code editions and an
# equivalence between two codifications are claims about a period, and an
# undated one cannot be applied to a dated question. Nothing in
# refspec.atlas.v3_source_data carries an effective date for a mapping:
# RegistryMapping has a subject, an object, a predicate, two endpoint release
# pins, an assertedAt and its evidence, and no temporal field at all. So this
# producer has no date to emit, and the honest failure is to refuse the input
# rather than to invent one -- a fabricated period would be indistinguishable
# on the wire from a real one, which is worse than no mapping.
#
# Both real mapping releases are subject-ring today
# (src/refspec/atlas/v3_registry_alignments.py, EuroVoc<->LCSH), so this is the
# expected case rather than a live gap. Adding the field to RegistryMapping and
# threading it into _add_assertion's effective_period argument is the work owed
# before a value-ring or legal-identity mapping source arrives. The registry
# states both bounds as ISO calendar days, so that work also has to promote
# them: `<effectiveFrom>T00:00:00+00:00` and `<effectiveThrough>T23:59:59+00:00`,
# the one promotion sh:pattern on atlas:EffectivePeriodShape admits. Nothing
# here has to remember that -- a distribution promoting a day any other way is
# refused -- but a producer written against this comment starts out conforming.
UNEMITTABLE_MAPPING_RINGS = frozenset({"legalIdentity", "value"})


def _mapping_release_ring(ring: str) -> URIRef:
    """Resolve one mapping release's declared ring to its wire individual."""

    if ring not in SEMANTIC_RINGS:
        raise ValueError(f"unsupported mapping semantic ring: {ring!r}")
    if ring in UNEMITTABLE_MAPPING_RINGS:
        raise ValueError(
            f"mapping semantic ring {ring!r} is not emittable by this producer: "
            "the Atlas 3.1 binding requires every mapping assertion on this ring "
            "to carry an rkaf:hasEffectivePeriod resolving to a well-formed "
            "rkaf:EffectivePeriod, and no registry mapping source states an "
            "effective date for this producer to emit. Carry the dates on "
            "RegistryMapping and emit them before a source needs this ring; "
            "fabricating a period would publish a claim no source made."
        )
    return ATLAS[ring]


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


def _mapping_evidence(
    release: RegistryMappingRelease,
    mapping: RegistryMapping,
    evidence: RegistryMappingEvidence,
) -> tuple[URIRef, str, Mapping[str, Any]]:
    """Return one pinned mapping evidence row without source-specific guesses."""

    matching_pins = [
        pin
        for pin in release.inputs
        if pin.sha256 == evidence.source_digest
        and pin.source_iri == evidence.source_locator
    ]
    if len(matching_pins) != 1:
        raise ValueError(
            f"{release.key} mapping evidence locator and digest must identify "
            "exactly one pinned input"
        )
    payload = _plain(evidence.native_payload)
    if not isinstance(payload, Mapping):
        raise TypeError(f"{release.key} mapping payload must be an object")
    expected_triple = {
        "objectIri": mapping.object,
        "predicateIri": mapping.predicate,
        "subjectIri": mapping.subject,
    }
    if any(payload.get(key) != value for key, value in expected_triple.items()):
        raise ValueError(
            f"{release.key} mapping payload differs from its exact triple"
        )
    triple_digest = mapping_triple_digest(
        subject_iri=mapping.subject,
        predicate_iri=mapping.predicate,
        object_iri=mapping.object,
    )
    if payload.get("mappingTripleDigest", triple_digest) != triple_digest:
        raise ValueError(
            f"{release.key} mapping payload has the wrong triple digest"
        )
    ATLAS_VALIDATE.canonical_native_json_bytes(payload)
    return URIRef(evidence.source_locator), evidence.source_digest, payload


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
    source_ring: URIRef | None = None,
    target_ring: URIRef | None = None,
) -> URIRef:
    policy_digest = ATLAS_VALIDATE.rdf_node_digest(graph, policy)
    basis: dict[str, str] = {
        "object": str(obj),
        "policy": str(policy),
        "policyContentDigest": policy_digest,
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
            RKAF.assertedAt,
            Literal(_rdf_datetime(asserted_at), datatype=XSD.dateTime, normalize=False),
        )
    )
    graph.add((assertion, ATLAS.assertionIdentityDigest, Literal(identity_digest)))
    return assertion


def _add_evidence_binding(
    graph: Graph,
    *,
    assertion: URIRef,
    evidence_record: URIRef,
    reviewer: URIRef,
    review_warrant: str,
    decided_at: str,
) -> URIRef:
    """Attach one immutable approval to an existing assertion."""

    evidence_source_digest = Literal(
        ATLAS_VALIDATE.rdf_node_digest(graph, evidence_record)
    )
    evidence_facts: list[tuple[URIRef, object]] = [
        (RDF.type, RKAF.EvidenceBinding),
        (RKAF.bindsAssertion, assertion),
        (ATLAS.evidenceSourceRecord, evidence_record),
        (ATLAS.evidenceSourceDigest, evidence_source_digest),
        (RKAF.attestor, reviewer),
        (RKAF.decision, RKAF.approved),
        *ATLAS_VALIDATE.evidence_warrant_facts(review_warrant),
        (RKAF.evidentiaryFunction, RKAF.supports),
        (
            RKAF.attestedAt,
            Literal(
                _rdf_datetime(decided_at),
                datatype=XSD.dateTime,
                normalize=False,
            ),
        ),
    ]
    evidence_digest = ATLAS_VALIDATE._outgoing_facts_digest(evidence_facts)
    evidence = URIRef(
        "urn:ref:atlas-evidence:" + evidence_digest.removeprefix("sha256:")
    )
    if (evidence, RDF.type, None) in graph:
        raise ValueError(
            f"evidence decisions collapse to one binding: {evidence}"
        )
    for evidence_predicate, evidence_object in evidence_facts:
        graph.add((evidence, evidence_predicate, evidence_object))
    graph.add((evidence, ATLAS.contentDigest, Literal(evidence_digest)))
    return evidence


def _add_evidenced_assertion(
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
    review_warrant: str,
    decided_at: str,
    source_ring: URIRef | None = None,
    target_ring: URIRef | None = None,
) -> URIRef:
    """Construct one assertion with its single source-native approval."""

    assertion = _add_assertion(
        graph,
        assertion_type=assertion_type,
        ring=ring,
        subject=subject,
        predicate=predicate,
        obj=obj,
        source_release=source_release,
        target_release=target_release,
        policy=policy,
        asserted_at=asserted_at,
        source_ring=source_ring,
        target_ring=target_ring,
    )
    _add_evidence_binding(
        graph,
        assertion=assertion,
        evidence_record=evidence_record,
        reviewer=reviewer,
        review_warrant=review_warrant,
        decided_at=decided_at,
    )
    return assertion


def _expected_mapping_asserted_graph(
    mapping_releases: Sequence[RegistryMappingRelease],
) -> Graph:
    """Reconstruct the exact mapping claims, evidence, records, and policies."""

    graph = _new_build_graph()
    for release in mapping_releases:
        policy = _add_policy(graph, release.editorial_policy)
        source_release = URIRef(release.source_release_iri)
        for mapping in release.mappings:
            assertion = _add_assertion(
                graph,
                assertion_type=ATLAS.MappingAssertion,
                ring=_mapping_release_ring(release.ring),
                subject=URIRef(mapping.subject),
                predicate=URIRef(mapping.predicate),
                obj=URIRef(mapping.object),
                source_release=URIRef(mapping.subject_atlas_release_iri),
                target_release=URIRef(mapping.object_atlas_release_iri),
                policy=policy,
                asserted_at=mapping.asserted_at,
            )
            for evidence in mapping.evidence:
                locator, digest, payload = _mapping_evidence(
                    release,
                    mapping,
                    evidence,
                )
                record = _add_source_record(
                    graph,
                    source_release=source_release,
                    source_locator=locator,
                    source_digest=digest,
                    native_payload=payload,
                    represents_resource=None,
                )
                _add_evidence_binding(
                    graph,
                    assertion=assertion,
                    evidence_record=record,
                    reviewer=URIRef(evidence.reviewer_iri),
                    review_warrant=_mapping_review_method(evidence.review_warrant),
                    decided_at=evidence.attested_at,
                )
    return graph


def _mapping_accounting_expectations(
    mapping_releases: Sequence[RegistryMappingRelease],
) -> dict[str, dict[str, set[str]]]:
    """Group exact mapping assertion identities by evidence SourceRecord."""

    graph = _expected_mapping_asserted_graph(mapping_releases)
    expected: dict[str, dict[str, set[str]]] = defaultdict(
        lambda: defaultdict(set)
    )
    try:
        for binding in graph.subjects(RDF.type, RKAF.EvidenceBinding):
            assertion = graph.value(binding, RKAF.bindsAssertion)
            record = graph.value(binding, ATLAS.evidenceSourceRecord)
            source_release = (
                graph.value(record, ATLAS.inSourceRelease)
                if isinstance(record, URIRef)
                else None
            )
            if not all(
                isinstance(value, URIRef)
                for value in (assertion, record, source_release)
            ):
                raise AssertionError(
                    "expected mapping evidence lacks assertion or release ownership"
                )
            expected[str(source_release)][str(record)].add(str(assertion))
        return {
            release: {
                record: set(assertions)
                for record, assertions in records.items()
            }
            for release, records in expected.items()
        }
    finally:
        graph.close()


def _validate_compiled_evidence_output(
    asserted: Graph,
    expected_counts: Mapping[str, int],
    mapping_releases: Sequence[RegistryMappingRelease],
) -> None:
    """Reconcile every approval and the exact evidence-backed mapping subgraph."""

    expected_mapping = _expected_mapping_asserted_graph(mapping_releases)
    try:
        expected_assertions = set(
            expected_mapping.subjects(RDF.type, ATLAS.MappingAssertion)
        )
        actual_assertions = set(
            asserted.subjects(RDF.type, ATLAS.MappingAssertion)
        )
        if actual_assertions != expected_assertions:
            raise ValueError("compiled mapping assertion identities differ")

        def mapping_subjects(graph: Graph) -> set[URIRef]:
            bindings = {
                URIRef(binding)
                for assertion in expected_assertions
                for binding in graph.subjects(RKAF.bindsAssertion, assertion)
            }
            records = {
                URIRef(record)
                for binding in bindings
                for record in graph.objects(binding, ATLAS.evidenceSourceRecord)
                if isinstance(record, URIRef)
            }
            policies = {
                URIRef(policy)
                for assertion in expected_assertions
                for policy in graph.objects(assertion, ATLAS.governedByPolicy)
                if isinstance(policy, URIRef)
            }
            return expected_assertions | bindings | records | policies

        expected_subjects = mapping_subjects(expected_mapping)
        actual_subjects = mapping_subjects(asserted)
        if actual_subjects != expected_subjects:
            raise ValueError("compiled mapping evidence identities differ")
        for subject in expected_subjects:
            if set(asserted.predicate_objects(subject)) != set(
                expected_mapping.predicate_objects(subject)
            ):
                raise ValueError(
                    f"compiled mapping evidence facts differ: {subject}"
                )

        all_assertions = {
            URIRef(assertion)
            for assertion_type in ATLAS_VALIDATE.ASSERTION_TYPES
            for assertion in asserted.subjects(RDF.type, assertion_type)
        }
        typed_bindings = set(
            asserted.subjects(RDF.type, RKAF.EvidenceBinding)
        )
        bound_bindings: set[URIRef] = set()
        for assertion in all_assertions:
            bindings = {
                URIRef(binding)
                for binding in asserted.subjects(RKAF.bindsAssertion, assertion)
            }
            expected_count = (
                len(
                    set(
                        expected_mapping.subjects(
                            RKAF.bindsAssertion,
                            assertion,
                        )
                    )
                )
                if assertion in expected_assertions
                else 1
            )
            if len(bindings) != expected_count:
                raise ValueError(
                    f"compiled assertion evidence count differs: {assertion}"
                )
            bound_bindings.update(bindings)
        expected_binding_count = (
            expected_counts["relationAssertions"]
            - expected_counts["mappingAssertions"]
            + len(
                set(
                    expected_mapping.subjects(
                        RDF.type,
                        RKAF.EvidenceBinding,
                    )
                )
            )
        )
        if (
            typed_bindings != bound_bindings
            or len(typed_bindings) != expected_binding_count
        ):
            raise ValueError("compiled evidence binding inventory differs")
    finally:
        expected_mapping.close()


def _registry_asserted_graph() -> Graph:
    _verify_pinned_file(
        REGISTRY_DESCRIPTORS,
        logical_path=REGISTRY_DESCRIPTORS_LOGICAL_PATH,
        expected_digest=REGISTRY_DESCRIPTORS_EXPECTED_DIGEST,
    )
    _verify_pinned_file(
        REGISTRY_DESCRIPTORS_PROOF,
        logical_path=REGISTRY_DESCRIPTORS_PROOF_LOGICAL_PATH,
        expected_digest=REGISTRY_DESCRIPTORS_PROOF_EXPECTED_DIGEST,
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
        for record in release.supplemental_source_records:
            native_payload_count += 1
            maps, tags, payload_violations = _audit_english_language_content(
                record.native_payload,
                allow_untagged_explicit_language=(
                    _is_registry_claim_payload(record.native_payload)
                ),
            )
            language_map_count += maps
            explicit_language_tag_count += tags
            violations.extend(
                f"{release.spec.key}/{record.source_record_id}/{violation}"
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






def _validate_compiled_producer_rows(
    releases: tuple[LoadedRelease, ...],
    mapping_releases: Sequence[RegistryMappingRelease] = (),
) -> CompiledProducerValidationReceipt:
    """Validate source and evidence-backed mapping rows against compiled SHACL.

    This is deliberately narrower than the independent RDF validator. The
    fixed constructors cover carrier shape and datatype rules; this pass proves
    the joins and uniqueness rules directly on the smaller normalized rows.
    """

    if not releases and not mapping_releases:
        raise ValueError("producer row validation requires source releases")
    # Derived, not asserted. This used to be a table of six digests compiled
    # into this file, which the builder then compared against the binding it
    # had just hashed -- the producer agreeing with itself, at the price of a
    # `--repin` edit for every binding change. The digests below are read off
    # the binding files this build is about to validate against, and RECORDED.
    # The tripwire that matters is the independent validator's: it recomputes
    # them from the binding on ITS disk and refuses a manifest that disagrees
    # (`_check_binding_pins`). That is two parties comparing; this was one.
    binding_profile = ATLAS_VALIDATE._binding_digests()
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

        resource_source_release_iris = {
            release.source_release_iri for release in releases
        }
        mapping_source_release_iris = {
            release.source_release_iri for release in mapping_releases
        }
        if resource_source_release_iris & mapping_source_release_iris:
            raise ValueError("resource and mapping source release identities overlap")
        source_release_iris = (
            resource_source_release_iris | mapping_source_release_iris
        )
        atlas_release_iris = {release.atlas_release_iri for release in releases}
        if source_release_iris & atlas_release_iris:
            raise ValueError("source and Atlas release identities overlap")
        if (source_release_iris | atlas_release_iris) & catalog_carriers:
            raise ValueError("release identity overlaps a registry catalog carrier")

        resource_index: dict[str, tuple[str, URIRef, URIRef]] = {}

        def resource_facts(resource_iri: str) -> tuple[str, URIRef, URIRef] | None:
            return resource_index.get(resource_iri)

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
                resource_index[resource_iri] = (
                    release.spec.key,
                    URIRef(release.atlas_release_iri),
                    ring,
                )

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
                    previous_target = identifier_targets.get(key)
                    if previous_target is None:
                        identifier_targets[key] = resource_iri
                        previous_target = resource_iri
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
        mapping_claims: set[tuple[str, str, str]] = set()
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
                source = resource_facts(relation.subject)
                target = resource_facts(relation.object)
                if source is None or target is None:
                    raise ValueError(
                        f"native relation endpoint is outside loaded releases: {relation}"
                    )
                if source[0] != release.spec.key:
                    raise ValueError(
                        f"native relation is not owned by its subject release: {relation}"
                    )
                if source[2] != release_ring or target[2] != release_ring:
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
                source = resource_facts(relation.subject)
                target = resource_facts(relation.object)
                if source is None or target is None:
                    raise ValueError(
                        f"cross-ring relation endpoint is outside loaded releases: {relation}"
                    )
                source_ring = ATLAS[relation.source_ring]
                target_ring = ATLAS[relation.target_ring]
                if source[0] != release.spec.key:
                    raise ValueError(
                        f"cross-ring relation is not owned by its subject release: {relation}"
                    )
                if (source[2], target[2]) != (source_ring, target_ring):
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
                triple = (
                    URIRef(relation.subject),
                    URIRef(relation.predicate),
                    URIRef(relation.object),
                )
                if triple in current_relations:
                    raise ValueError(
                        f"cross-ring relation duplicates another relation: {triple}"
                    )
                current_relations[triple] = ()
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

        mapping_evidence_records: set[URIRef] = set()
        for mapping_release in mapping_releases:
            if not mapping_release.key:
                raise ValueError("mapping release key must be non-empty")
            if (
                ATLAS_VALIDATE.DIGEST_RE.fullmatch(
                    mapping_release.source_release_digest
                )
                is None
            ):
                raise ValueError(
                    f"{mapping_release.key} source release digest is not SHA-256"
                )
            try:
                parsed_issued = date.fromisoformat(mapping_release.issued)
            except (TypeError, ValueError) as error:
                raise ValueError(
                    f"{mapping_release.key} issued date is not canonical YYYY-MM-DD"
                ) from error
            if parsed_issued.isoformat() != mapping_release.issued:
                raise ValueError(
                    f"{mapping_release.key} issued date is not canonical YYYY-MM-DD"
                )
            _accounting_membership_mode(mapping_release.scope)
            _assert_portable_editorial_policy_payload(
                mapping_release.editorial_policy
            )
            release_ring = _mapping_release_ring(mapping_release.ring)
            allowed = relation_policies.get(release_ring, {}).get(
                ATLAS.MappingAssertion,
                frozenset(),
            )
            for mapping in mapping_release.mappings:
                for field, value in (
                    ("subject", mapping.subject),
                    ("predicate", mapping.predicate),
                    ("object", mapping.object),
                    (
                        "subject Atlas release",
                        mapping.subject_atlas_release_iri,
                    ),
                    (
                        "object Atlas release",
                        mapping.object_atlas_release_iri,
                    ),
                ):
                    _require_absolute_iri(
                        value,
                        context=f"{mapping_release.key} mapping {field}",
                    )
                source = resource_facts(mapping.subject)
                target = resource_facts(mapping.object)
                if source is None or target is None:
                    raise ValueError(
                        f"mapping endpoint is outside loaded releases: {mapping}"
                    )
                if source[1] == target[1]:
                    raise ValueError(
                        f"mapping endpoints use one release: {mapping}"
                    )
                if source[1] != URIRef(mapping.subject_atlas_release_iri):
                    raise ValueError(
                        "mapping subject endpoint release differs from its exact pin: "
                        f"{mapping}"
                    )
                if target[1] != URIRef(mapping.object_atlas_release_iri):
                    raise ValueError(
                        "mapping object endpoint release differs from its exact pin: "
                        f"{mapping}"
                    )
                if source[2] != release_ring or target[2] != release_ring:
                    raise ValueError(
                        f"mapping endpoint ring differs: {mapping}"
                    )
                predicate = URIRef(mapping.predicate)
                if predicate not in allowed:
                    raise ValueError(
                        f"mapping predicate is not allowed for "
                        f"{mapping_release.ring}: {predicate}"
                    )
                _rdf_datetime(mapping.asserted_at)
                for evidence in mapping.evidence:
                    _require_absolute_iri(
                        evidence.reviewer_iri,
                        context=f"{mapping_release.key} mapping evidence reviewer",
                    )
                    _mapping_review_method(evidence.review_warrant)
                    _rdf_datetime(evidence.attested_at)
                    locator, digest, payload = _mapping_evidence(
                        mapping_release,
                        mapping,
                        evidence,
                    )
                    evidence_record, _ = _source_record_constructor(
                        source_release=URIRef(mapping_release.source_release_iri),
                        source_locator=locator,
                        source_digest=digest,
                        native_payload=payload,
                    )
                    mapping_evidence_records.add(evidence_record)
                claim = (mapping.subject, mapping.predicate, mapping.object)
                if claim in mapping_claims:
                    raise ValueError(f"mapping claim repeats: {claim}")
                mapping_claims.add(claim)
                triple = (
                    URIRef(mapping.subject),
                    predicate,
                    URIRef(mapping.object),
                )
                if triple in current_relations:
                    raise ValueError(
                        f"mapping duplicates another relation: {triple}"
                    )
                current_relations[triple] = ()

        if relation_payload_count != english_only_scan["relationPayloadsChecked"]:
            raise ValueError("relation payload validation count differs")
        ATLAS_VALIDATE._check_skos_integrity(current_relations)

        resource_count = sum(len(release.resources) for release in releases)
        mapping_count = len(mapping_claims)
        native_relation_count = sum(len(release.relations) for release in releases)
        cross_ring_count = len(cross_ring_claims)
        expected_counts = {
            "crossRingRelationAssertions": cross_ring_count,
            "derivedRelations": 0,
            "identifiers": identifier_count,
            "labels": label_count,
            "mappingAssertions": mapping_count,
            "nativeRelationAssertions": native_relation_count,
            "projectedRelations": 0,
            "relationAssertions": (
                source_assignment_count
                + native_relation_count
                + cross_ring_count
                + mapping_count
            ),
            "releases": len(releases),
            "resources": resource_count,
            "sourceAssignments": source_assignment_count,
            "sourceRecords": (
                resource_count
                + remap_evidence_count
                + len(mapping_evidence_records)
                + sum(
                    len(release.supplemental_source_records)
                    for release in releases
                )
            ),
        }
    finally:
        descriptor_graph.close()

    return CompiledProducerValidationReceipt(
        binding_profile=binding_profile,
        english_only_scan=english_only_scan,
        expected_counts=expected_counts,
        source_release_count=len(releases) + len(mapping_releases),
    )


def _validate_compiled_source_accounting(
    releases: Sequence[LoadedRelease],
    accounting: Mapping[str, Any],
    mapping_releases: Sequence[RegistryMappingRelease] = (),
) -> str:
    """Reconcile the generated ledger with the compact source membership."""

    if set(accounting) != {"distributionId", "inputs", "totals", "type", "version"}:
        raise ValueError("compiled producer source accounting fields differ")
    if (
        accounting.get("distributionId") != distribution_identity(accounting)
        or accounting.get("type") != "AtlasSourceAccounting"
        or accounting.get("version") != "3.1"
    ):
        raise ValueError("compiled producer source accounting identity differs")
    inputs = accounting.get("inputs")
    if not isinstance(inputs, list):
        raise TypeError("compiled producer source accounting inputs are not a list")
    rows_by_release: dict[str, Mapping[str, Any]] = {}
    for row in inputs:
        if not isinstance(row, Mapping) or set(row) != {
            "dispositions",
            "membershipMode",
            "sourceRelease",
        }:
            raise ValueError("compiled producer source accounting row fields differ")
        source_release = row.get("sourceRelease")
        if not isinstance(source_release, str) or source_release in rows_by_release:
            raise ValueError("compiled producer source accounting repeats a release")
        rows_by_release[source_release] = row

    expected_releases = {
        release.source_release_iri for release in releases
    } | {
        release.source_release_iri for release in mapping_releases
    }
    if set(rows_by_release) != expected_releases:
        raise ValueError("compiled producer source accounting release set differs")

    mapping_expectations = _mapping_accounting_expectations(mapping_releases)
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
        if not isinstance(dispositions, list):
            raise ValueError(
                f"{release.spec.key} source accounting dispositions are not a list"
            )
        expected_resources = {resource.iri for resource in release.resources}
        represented_resources: set[str] = set()
        excluded = 0
        supplemental_records: set[str] = set()
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
                reason = disposition.get("reason")
                if set(disposition) != {"reason", "sourceRecord", "status"} or reason not in {
                    _TRANSFORMED_RELATION_ACCOUNTING_REASON,
                    _SOURCE_CLAIM_ACCOUNTING_REASON,
                }:
                    raise ValueError(
                        f"{release.spec.key} excluded disposition differs"
                    )
                if reason == _SOURCE_CLAIM_ACCOUNTING_REASON:
                    supplemental_records.add(source_record)
                excluded += 1
            else:
                raise ValueError(
                    f"{release.spec.key} source accounting status is unsupported"
                )
        if represented_resources != expected_resources:
            raise ValueError(
                f"{release.spec.key} source accounting resource membership differs"
            )
        expected_transformed = sum(
            relation.predicate == str(ATLAS.thesaurusRelated)
            for relation in release.relations
        )
        expected_supplemental = set()
        for supplemental in release.supplemental_source_records:
            record, _ = _source_record_constructor(
                source_release=URIRef(release.source_release_iri),
                source_locator=URIRef(supplemental.source_locator),
                source_digest=supplemental.source_digest,
                native_payload=supplemental.native_payload,
            )
            expected_supplemental.add(str(record))
        if supplemental_records != expected_supplemental:
            raise ValueError(
                f"{release.spec.key} supplemental SourceRecord membership differs"
            )
        expected_excluded = expected_transformed + len(expected_supplemental)
        if excluded != expected_excluded:
            raise ValueError(
                f"{release.spec.key} source accounting excluded count differs"
            )
        represented_total += len(represented_resources)
        excluded_total += excluded

    for mapping_release in mapping_releases:
        row = rows_by_release[mapping_release.source_release_iri]
        if row["membershipMode"] != _accounting_membership_mode(
            mapping_release.scope
        ):
            raise ValueError(
                f"{mapping_release.key} mapping source accounting membership mode differs"
            )
        dispositions = row["dispositions"]
        if not isinstance(dispositions, list):
            raise ValueError(
                f"{mapping_release.key} mapping source accounting dispositions are not a list"
            )
        expected_records = mapping_expectations.get(
            mapping_release.source_release_iri,
            {},
        )
        observed_records: set[str] = set()
        for disposition in dispositions:
            if (
                not isinstance(disposition, Mapping)
                or set(disposition)
                != {
                    "atlasAssertions",
                    "sourceRecord",
                    "status",
                }
                or disposition.get("status") != "represented"
                or not isinstance(disposition.get("atlasAssertions"), list)
            ):
                raise ValueError(
                    f"{mapping_release.key} represented mapping disposition differs"
                )
            source_record = disposition.get("sourceRecord")
            if (
                not isinstance(source_record, str)
                or source_record in source_records
                or source_record in observed_records
            ):
                raise ValueError(
                    f"{mapping_release.key} mapping SourceRecord is invalid or repeated"
                )
            assertions = disposition["atlasAssertions"]
            expected_assertions = expected_records.get(source_record)
            if (
                expected_assertions is None
                or any(not isinstance(assertion, str) for assertion in assertions)
                or len(assertions) != len(set(assertions))
                or set(assertions) != expected_assertions
            ):
                raise ValueError(
                    f"{mapping_release.key} represented mapping assertions differ"
                )
            observed_records.add(source_record)
        if observed_records != set(expected_records):
            raise ValueError(
                f"{mapping_release.key} mapping SourceRecord membership differs"
            )
        source_records.update(observed_records)
        represented_total += len(observed_records)

    expected_totals = {
        "excluded": excluded_total,
        "represented": represented_total,
        "sourceRecords": represented_total + excluded_total,
        "sourceReleases": len(releases) + len(mapping_releases),
        "unresolved": 0,
    }
    if accounting.get("totals") != expected_totals:
        raise ValueError("compiled producer source accounting totals differ")
    return _canonical_digest(accounting)




def _validate_compiled_producer_output(
    releases: Sequence[LoadedRelease],
    graphs: BuildGraphs,
    producer_validation: CompiledProducerValidationReceipt,
    mapping_releases: Sequence[RegistryMappingRelease] = (),
) -> dict[str, Any]:
    """Close the proof over fixed constructors without rewalking every quad."""

    if dict(producer_validation.binding_profile) != ATLAS_VALIDATE._binding_digests():
        raise ValueError(
            "the binding changed on disk between row validation and output validation"
        )
    if graphs.projection or graphs.derived:
        raise ValueError(
            "compiled producer requires empty projection and derived graphs"
        )
    if any(graphs.asserted.triples((None, RKAF.supersedesAssertion, None))):
        raise ValueError("compiled producer does not support supersession")
    observed_counts = _counts(graphs)
    if observed_counts != dict(producer_validation.expected_counts):
        raise ValueError(
            "compiled producer constructor counts differ: "
            f"expected={dict(producer_validation.expected_counts)}, "
            f"observed={observed_counts}"
        )
    _validate_compiled_evidence_output(
        graphs.asserted,
        producer_validation.expected_counts,
        mapping_releases,
    )
    accounting_digest = _validate_compiled_source_accounting(
        releases,
        graphs.accounting,
        mapping_releases,
    )
    if not isinstance(graphs.asserted, _MutationTrackedGraph):
        raise TypeError("compiled producer graph lacks a mutation receipt")
    graphs.sealed_asserted_revision = graphs.asserted.revision
    return {
        "bindingProfile": dict(producer_validation.binding_profile),
        "constructorProfile": _COMPILED_PRODUCER_PROFILE,
        "counts": observed_counts,
        "mode": _COMPILED_PRODUCER_MODE,
        "sourceAccountingDigest": accounting_digest,
        "sourceReleaseCount": producer_validation.source_release_count,
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
    mapping_releases: Sequence[RegistryMappingRelease] = (),
    include_projection: bool = True,
    all_plans: Sequence[ReleasePackPlan] = (),
) -> BuildGraphs:
    current_keys = {
        *(release.spec.key for release in releases),
        *(release.key for release in mapping_releases),
    }
    plans_by_key = {plan.key: plan for plan in all_plans}
    if len(plans_by_key) != len(all_plans):
        raise ValueError("Atlas release plans repeat a key")
    all_release_keys = set(plans_by_key) if all_plans else current_keys
    if current_keys != all_release_keys:
        raise ValueError("loaded releases do not match the Atlas release plan")
    asserted = _registry_asserted_graph()
    _ensure_release_schemes(asserted, releases)
    native_policy = _add_policy(asserted, SOURCE_NATIVE_EDITORIAL_POLICY_PAYLOAD)
    mapping_policies = {
        release.key: _add_policy(asserted, release.editorial_policy)
        for release in mapping_releases
    }

    source_release_nodes: dict[str, URIRef] = {}
    resource_facts: dict[str, tuple[str, URIRef, URIRef]] = {}

    def facts_for(resource_iri: str) -> tuple[str, URIRef, URIRef]:
        try:
            return resource_facts[resource_iri]
        except KeyError as error:
            raise ValueError(
                f"resource endpoint is outside loaded releases: {resource_iri}"
            ) from error

    resource_record: dict[str, URIRef] = {}
    identifier_targets: dict[tuple[str, str], str] = {}
    accounting_inputs: list[dict[str, Any]] = []
    source_accounting_by_release: dict[str, dict[str, Any]] = {}

    for release_position, release in enumerate(releases, start=1):
        _STATUS.progress(
            "construct-source-graphs",
            release_position - 1,
            len(releases),
            current=release.spec.key,
        )
        release_instant = _release_instant(release.issued)
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
        asserted.add(
            (atlas_release, RKAF.membershipMode, RKAF.completeMembership)
        )
        asserted.add((atlas_release, DCTERMS.identifier, Literal(release.spec.key)))
        asserted.add(
            (
                atlas_release,
                DCTERMS.issued,
                Literal(release.issued, datatype=XSD.date),
            )
        )

        dispositions: list[dict[str, Any]] = []
        for resource_position, resource_row in enumerate(
            release.resources,
            start=1,
        ):
            if resource_position % 25_000 == 0:
                _STATUS.progress(
                    "construct-source-graphs",
                    release_position - 1,
                    len(releases),
                    current=(
                        f"{release.spec.key} resources="
                        f"{resource_position}/{len(release.resources)}"
                    ),
                )
            if resource_row.iri in resource_facts:
                raise ValueError(
                    f"Atlas releases repeat resource IRI {resource_row.iri}"
                )
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
            resource_facts[resource_row.iri] = (
                release.spec.key,
                atlas_release,
                ring,
            )
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
            for identifier_row in resource_row.identifiers:
                identifier_key = (
                    identifier_row.scheme_iri,
                    identifier_row.value,
                )
                previous_target = identifier_targets.get(identifier_key)
                if previous_target is None:
                    identifier_targets[identifier_key] = resource_row.iri
                    previous_target = resource_row.iri
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
            if resource_row.definition:
                asserted.add(
                    (
                        resource,
                        ATLAS.definition,
                        Literal(resource_row.definition, lang="en"),
                    )
                )
            for note in resource_row.notes:
                if note:
                    asserted.add((resource, ATLAS.note, Literal(note, lang="en")))
            for notation in resource_row.notations:
                # Simple form, never an explicit xsd:string datatype: RDF 1.1
                # makes the two the same term, and the wire may spell a term
                # only one way. `rdf_canonical.ntriples_term` refuses the
                # typed form outright, so this is a rule, not a convention.
                asserted.add((resource, ATLAS.notation, Literal(notation)))
            if resource_row.status is not None:
                asserted.add((resource, ATLAS.recordStatus, Literal(resource_row.status)))
            if release.spec.emit_source_assignments:
                _add_evidenced_assertion(
                    asserted,
                    assertion_type=ATLAS.SourceAssignment,
                    ring=ring,
                    subject=record,
                    predicate=assignment_predicate,
                    obj=resource,
                    source_release=source_release,
                    target_release=atlas_release,
                    policy=native_policy,
                    asserted_at=release_instant,
                    evidence_record=record,
                    reviewer=NATIVE_REVIEWER,
                    review_warrant=_review_method_for_assertion(
                        ATLAS.SourceAssignment
                    ),
                    decided_at=release_instant,
                )
            dispositions.append(
                {
                    "atlasResources": [resource_row.iri],
                    "sourceRecord": str(record),
                    "status": "represented",
                }
            )
        for supplemental in release.supplemental_source_records:
            expected_record, _ = _source_record_constructor(
                source_release=source_release,
                source_locator=URIRef(supplemental.source_locator),
                source_digest=supplemental.source_digest,
                native_payload=supplemental.native_payload,
            )
            if (expected_record, RDF.type, ATLAS.SourceRecord) in asserted:
                raise ValueError(
                    f"supplemental source record is repeated: {expected_record}"
                )
            record = _add_source_record(
                asserted,
                source_release=source_release,
                source_locator=URIRef(supplemental.source_locator),
                source_digest=supplemental.source_digest,
                native_payload=supplemental.native_payload,
                represents_resource=None,
            )
            if record != expected_record:
                raise ValueError(
                    f"supplemental source record identity changed: {record}"
                )
            dispositions.append(
                {
                    "reason": _SOURCE_CLAIM_ACCOUNTING_REASON,
                    "sourceRecord": str(record),
                    "status": "excluded",
                }
            )
        accounting_row = {
            "dispositions": dispositions,
            "membershipMode": _accounting_membership_mode(release.spec.scope),
            "sourceRelease": str(source_release),
        }
        accounting_inputs.append(accounting_row)
        source_accounting_by_release[release.source_release_iri] = accounting_row
        _STATUS.progress(
            "construct-source-graphs",
            release_position,
            len(releases),
            current=release.spec.key,
        )

    for mapping_position, mapping_release in enumerate(mapping_releases, start=1):
        _STATUS.progress(
            "construct-mapping-graphs",
            mapping_position - 1,
            len(mapping_releases),
            current=mapping_release.key,
        )
        source_release = _add_source_release(
            asserted,
            identifier=mapping_release.source_release_iri,
            digest=mapping_release.source_release_digest,
            issued=mapping_release.issued,
            locator=URIRef(mapping_release.inputs[0].source_iri),
        )
        source_release_nodes[mapping_release.source_release_iri] = source_release
        accounting_row = {
            "dispositions": [],
            "membershipMode": _accounting_membership_mode(mapping_release.scope),
            "sourceRelease": str(source_release),
        }
        accounting_inputs.append(accounting_row)
        source_accounting_by_release[
            mapping_release.source_release_iri
        ] = accounting_row
        _STATUS.progress(
            "construct-mapping-graphs",
            mapping_position,
            len(mapping_releases),
            current=mapping_release.key,
        )

    native_count = 0
    remap_evidence_count = 0
    for release in releases:
        release_instant = _release_instant(release.issued)
        relation_ring, _, _ = _ring_dispatch(release.spec.ring)
        for relation in release.relations:
            try:
                source_atlas_release = facts_for(relation.subject)[1]
                target_atlas_release = facts_for(relation.object)[1]
                evidence_record = resource_record[relation.subject]
            except KeyError as error:
                raise ValueError(f"native relation endpoint is outside loaded releases: {relation}") from error
            review_warrant = _review_method_for_assertion(
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
                        "reason": _TRANSFORMED_RELATION_ACCOUNTING_REASON,
                        "sourceRecord": str(evidence_record),
                        "status": "excluded",
                    }
                )
                remap_evidence_count += 1
                review_warrant = _review_method_for_assertion(
                    ATLAS.NativeRelationAssertion,
                    deterministic_transformation=True,
                )
            _add_evidenced_assertion(
                asserted,
                assertion_type=ATLAS.NativeRelationAssertion,
                ring=relation_ring,
                subject=URIRef(relation.subject),
                predicate=URIRef(relation.predicate),
                obj=URIRef(relation.object),
                source_release=source_atlas_release,
                target_release=target_atlas_release,
                policy=native_policy,
                asserted_at=release_instant,
                evidence_record=evidence_record,
                reviewer=NATIVE_REVIEWER,
                review_warrant=review_warrant,
                decided_at=release_instant,
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

    # The one statement type this producer currently emits none of. The Atlas
    # 3.1 binding declares atlas:CrossRingRelationAssertion and this loop still
    # builds one from any release that carries a cross-ring relation -- but
    # after REF-032 no loaded release carries one. The single live instance was
    # a GAO report page pointing at a topic label observed on that same page:
    # not a ring crossing anyone could join against, just one document's own
    # metadata read twice. Saying so here, and pinning it with
    # ``test_producer_emits_no_cross_ring_assertions``, is the honest state --
    # the alternative is a wire type the artifact quietly never exercises.
    # The intended carrier is named in REF-032: a genuine institutional-roster
    # -> subject edge, once the Federal Hierarchy roster is completed and an
    # authority publishes subject assignments against it.
    cross_ring_count = 0
    for release in releases:
        release_instant = _release_instant(release.issued)
        for relation in release.cross_ring_relations:
            try:
                source_facts = facts_for(relation.subject)
                target_facts = facts_for(relation.object)
                source_atlas_release = source_facts[1]
                target_atlas_release = target_facts[1]
                evidence_record = resource_record[relation.subject]
                observed_source_ring = source_facts[2]
                observed_target_ring = target_facts[2]
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
            _add_evidenced_assertion(
                asserted,
                assertion_type=ATLAS.CrossRingRelationAssertion,
                ring=None,
                subject=URIRef(relation.subject),
                predicate=URIRef(relation.predicate),
                obj=URIRef(relation.object),
                source_release=source_atlas_release,
                target_release=target_atlas_release,
                policy=native_policy,
                asserted_at=release_instant,
                evidence_record=evidence_record,
                reviewer=NATIVE_REVIEWER,
                review_warrant=_review_method_for_assertion(
                    ATLAS.CrossRingRelationAssertion
                ),
                decided_at=release_instant,
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

    mapping_count = 0
    for mapping_release in mapping_releases:
        try:
            mapping_policy = mapping_policies[mapping_release.key]
        except KeyError as error:
            raise AssertionError(
                "mapping editorial policy was not constructed"
            ) from error
        mapping_ring = _mapping_release_ring(mapping_release.ring)
        accounting_row = source_accounting_by_release[
            mapping_release.source_release_iri
        ]
        mapping_dispositions: dict[str, set[str]] = defaultdict(set)
        for mapping in mapping_release.mappings:
            try:
                source_facts = facts_for(mapping.subject)
                target_facts = facts_for(mapping.object)
                source_atlas_release = source_facts[1]
                target_atlas_release = target_facts[1]
                observed_source_ring = source_facts[2]
                observed_target_ring = target_facts[2]
            except KeyError as error:
                raise ValueError(
                    f"mapping endpoint is outside loaded releases: {mapping}"
                ) from error
            if source_atlas_release == target_atlas_release:
                raise ValueError(
                    f"mapping endpoints use one release: {mapping}"
                )
            if source_atlas_release != URIRef(mapping.subject_atlas_release_iri):
                raise ValueError(
                    "mapping subject endpoint release differs from its exact pin: "
                    f"{mapping}"
                )
            if target_atlas_release != URIRef(mapping.object_atlas_release_iri):
                raise ValueError(
                    "mapping object endpoint release differs from its exact pin: "
                    f"{mapping}"
                )
            if (observed_source_ring, observed_target_ring) != (
                mapping_ring,
                mapping_ring,
            ):
                raise ValueError(
                    f"mapping endpoint ring differs: {mapping}"
                )
            assertion = _add_assertion(
                asserted,
                assertion_type=ATLAS.MappingAssertion,
                ring=mapping_ring,
                subject=URIRef(mapping.subject),
                predicate=URIRef(mapping.predicate),
                obj=URIRef(mapping.object),
                source_release=source_atlas_release,
                target_release=target_atlas_release,
                policy=mapping_policy,
                asserted_at=mapping.asserted_at,
            )
            for evidence in mapping.evidence:
                evidence_locator, evidence_digest, evidence_payload = (
                    _mapping_evidence(mapping_release, mapping, evidence)
                )
                evidence_record = _add_source_record(
                    asserted,
                    source_release=source_release_nodes[
                        mapping_release.source_release_iri
                    ],
                    source_locator=evidence_locator,
                    source_digest=evidence_digest,
                    native_payload=evidence_payload,
                    represents_resource=None,
                )
                _add_evidence_binding(
                    asserted,
                    assertion=assertion,
                    evidence_record=evidence_record,
                    reviewer=URIRef(evidence.reviewer_iri),
                    review_warrant=_mapping_review_method(
                        evidence.review_warrant
                    ),
                    decided_at=evidence.attested_at,
                )
                mapping_dispositions[str(evidence_record)].add(str(assertion))
            mapping_count += 1
        accounting_row["dispositions"].extend(
            {
                "atlasAssertions": sorted(assertions),
                "sourceRecord": source_record,
                "status": "represented",
            }
            for source_record, assertions in sorted(mapping_dispositions.items())
        )
    expected_mapping_count = sum(
        len(release.mappings) for release in mapping_releases
    )
    if mapping_count != expected_mapping_count:
        raise ValueError(
            f"expected {expected_mapping_count} mappings; emitted {mapping_count}"
        )
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
    accounting = _identified_source_accounting(
        {
            "inputs": accounting_inputs,
            "totals": {
                "excluded": excluded,
                "represented": represented,
                "sourceRecords": represented + excluded + unresolved,
                "sourceReleases": len(accounting_inputs),
                "unresolved": unresolved,
            },
            "type": "AtlasSourceAccounting",
            "version": "3.1",
        }
    )
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
    """Close the writer to source claims and evidence-backed mappings."""

    return _production_relation_scope_from_counts(_counts(graphs))


def _production_relation_scope_from_counts(
    counts: Mapping[str, int],
) -> dict[str, Any]:
    """Close a receipted writer to source claims and evidence-backed mappings."""

    scope = {
        "derivedRelations": counts["derivedRelations"],
        "mappingAssertions": counts["mappingAssertions"],
        "mode": "sourceClaimsAndEvidenceBackedMappings",
    }
    if scope["derivedRelations"]:
        raise ValueError(
            "evidence-backed Atlas build must contain zero derived relations"
        )
    return scope


def _dataset_lines(graphs: BuildGraphs) -> Iterable[str]:
    graph_ids = {role: URIRef(identifier) for role, identifier in _ROLE_GRAPH_IDS.items()}
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


def _materialize_nquads_pack(
    source: Path,
    target: Path,
    *,
    relative_path: str,
    incremental: ColdPackMaterialization | None,
) -> PackWriteReceipt:
    """Compress current canonical content and record the write."""

    receipt = _compress_nquads(source, target)
    if incremental is not None:
        incremental.rebuilt_paths.append(relative_path)
    return receipt


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
        source_release = URIRef(release.source_release_iri)
        if release.atlas_release_iri is not None:
            atlas_release = URIRef(release.atlas_release_iri)
            if atlas_release in atlas_release_owners:
                raise ValueError(
                    f"Atlas release is emitted more than once: {atlas_release}"
                )
            atlas_release_owners[atlas_release] = key
        if source_release in source_release_owners:
            raise ValueError(f"source release is emitted more than once: {source_release}")
        source_release_owners[source_release] = key

    # Only release nodes actually present in this graph belong to the write.
    owners: dict[URIRef, str] = {
        node: owner
        for node, owner in {
            **atlas_release_owners,
            **source_release_owners,
        }.items()
        if (node, RDF.type, None) in asserted
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
        evidence_bindings = list(
            asserted.subjects(RKAF.bindsAssertion, assertion)
        )
        if not evidence_bindings:
            raise ValueError(
                f"relation assertion {assertion} has no evidence binding"
            )
        evidence_owners = set()
        for binding in evidence_bindings:
            evidence_record = asserted.value(
                binding,
                ATLAS.evidenceSourceRecord,
            )
            owner = (
                owners.get(evidence_record)
                if isinstance(evidence_record, URIRef)
                else None
            )
            if owner is None:
                raise ValueError(
                    f"relation assertion {assertion} has no evidence release owner"
                )
            evidence_owners.add(owner)
        if len(evidence_owners) != 1:
            raise ValueError(
                f"relation assertion {assertion} has evidence from multiple releases"
            )
        owners[URIRef(assertion)] = next(iter(evidence_owners))

    own_from_object(
        RKAF.EvidenceBinding,
        RKAF.bindsAssertion,
        owners,
    )
    for event in asserted.subjects(RDF.type, RKAF.LifecycleEvent):
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


def _one_graph_object(
    graph: Graph,
    subject: URIRef,
    predicate: URIRef,
    *,
    expected_type: type[URIRef | Literal] | None = None,
) -> Any:
    values = list(graph.objects(subject, predicate))
    if len(values) != 1:
        raise ValueError(f"{subject} does not have exactly one {predicate}")
    value = values[0]
    if expected_type is not None and not isinstance(value, expected_type):
        raise TypeError(f"{subject} {predicate} has the wrong RDF term type")
    return value


def _atlas_local_name(value: Any, *, context: str) -> str:
    iri = str(value)
    namespace = str(ATLAS)
    if not iri.startswith(namespace) or len(iri) == len(namespace):
        raise ValueError(f"{context} is not an Atlas vocabulary term: {iri}")
    return iri[len(namespace) :]


def _rkaf_local_name(value: Any, *, context: str) -> str:
    """Shorten a Rulespec term for the compact projection.

    The compact record carries local names, so a term Atlas adopted from
    Rulespec projects the same way -- but it is read out of Rulespec's
    namespace, which is where it is defined.
    """

    iri = str(value)
    namespace = str(RKAF)
    if not iri.startswith(namespace) or len(iri) == len(namespace):
        raise ValueError(f"{context} is not a Rulespec vocabulary term: {iri}")
    return iri[len(namespace) :]


def _compact_record_role(graph: Graph, subject: URIRef) -> CompactRecordRole:
    types = set(graph.objects(subject, RDF.type))
    candidates = {
        role
        for role, marker in (
            (CompactRecordRole.RESOURCE, ATLAS.AtlasResource),
            (CompactRecordRole.LABEL, SKOSXL.Label),
            (CompactRecordRole.STATEMENT, ATLAS.RelationAssertion),
            (CompactRecordRole.EVIDENCE_BINDING, RKAF.EvidenceBinding),
            (CompactRecordRole.SOURCE_RECORD, ATLAS.SourceRecord),
            (CompactRecordRole.RELEASE, ATLAS.AtlasRelease),
            (CompactRecordRole.RELEASE, ATLAS.SourceRelease),
            (CompactRecordRole.IDENTIFIER, ATLAS.Identifier),
            (CompactRecordRole.LIFECYCLE_EVENT, RKAF.LifecycleEvent),
        )
        if marker in types
    }
    if len(candidates) != 1:
        raise ValueError(
            f"release-owned subject {subject} does not map to one compact role: "
            f"{sorted(str(value) for value in types)}"
        )
    return candidates.pop()


def _compact_record_from_graph(
    graph: Graph,
    subject: URIRef,
    role: CompactRecordRole,
) -> dict[str, Any]:
    """Losslessly encode one release-owned RDF subject as a logical record."""

    # Computed, never read: `atlas:contentDigest` is off the wire for every
    # carrier that does not derive its IRI from it, so the record's comparand
    # is the digest of the node's own facts rather than a triple restating it.
    record: dict[str, Any] = {
        "id": str(subject),
        "contentDigest": ATLAS_VALIDATE.rdf_node_digest(graph, subject),
    }
    if role == CompactRecordRole.RESOURCE:
        record.update(
            {
                "release": str(
                    _one_graph_object(
                        graph,
                        subject,
                        ATLAS.inRelease,
                        expected_type=URIRef,
                    )
                ),
                "scheme": str(
                    _one_graph_object(
                        graph,
                        subject,
                        ATLAS.inScheme,
                        expected_type=URIRef,
                    )
                ),
                "semanticRing": _atlas_local_name(
                    _one_graph_object(
                        graph,
                        subject,
                        ATLAS.semanticRing,
                        expected_type=URIRef,
                    ),
                    context=f"{subject} semantic ring",
                ),
                "resourceProfile": _atlas_local_name(
                    _one_graph_object(
                        graph,
                        subject,
                        ATLAS.resourceProfile,
                        expected_type=URIRef,
                    ),
                    context=f"{subject} resource profile",
                ),
                "sourceRecord": str(
                    _one_graph_object(
                        graph,
                        subject,
                        ATLAS.sourceRecord,
                        expected_type=URIRef,
                    )
                ),
            }
        )
        definitions = [str(value) for value in graph.objects(subject, ATLAS.definition)]
        if len(definitions) > 1:
            raise ValueError(f"{subject} has more than one definition")
        if definitions:
            record["definition"] = definitions[0]
        notes = sorted(str(value) for value in graph.objects(subject, ATLAS.note))
        if notes:
            record["notes"] = notes
        notations = sorted(str(value) for value in graph.objects(subject, ATLAS.notation))
        if notations:
            record["notations"] = notations
        statuses = [str(value) for value in graph.objects(subject, ATLAS.recordStatus)]
        if len(statuses) > 1:
            raise ValueError(f"{subject} has more than one record status")
        if statuses:
            record["recordStatus"] = statuses[0]
        return record

    if role == CompactRecordRole.LABEL:
        claims: list[tuple[str, URIRef]] = []
        for predicate, label_role in (
            (SKOSXL.prefLabel, "preferred"),
            (SKOSXL.altLabel, "alternate"),
            (SKOSXL.hiddenLabel, "hidden"),
        ):
            claims.extend(
                (label_role, URIRef(resource))
                for resource in graph.subjects(predicate, subject)
                if isinstance(resource, URIRef)
            )
        if len(claims) != 1:
            raise ValueError(f"label {subject} does not have exactly one role claim")
        literal = _one_graph_object(
            graph,
            subject,
            SKOSXL.literalForm,
            expected_type=Literal,
        )
        if literal.language != "en":
            raise ValueError(f"label {subject} is not English")
        record.update(
            {
                "resource": str(claims[0][1]),
                "labelRole": claims[0][0],
                "value": str(literal),
                "language": "en",
                "release": str(
                    _one_graph_object(
                        graph,
                        subject,
                        ATLAS.inRelease,
                        expected_type=URIRef,
                    )
                ),
                "sourceRecord": str(
                    _one_graph_object(
                        graph,
                        subject,
                        ATLAS.sourceRecord,
                        expected_type=URIRef,
                    )
                ),
            }
        )
        return record

    if role == CompactRecordRole.STATEMENT:
        types = set(graph.objects(subject, RDF.type))
        statement_types = [
            statement_type
            for statement_type in (
                ATLAS.NativeRelationAssertion,
                ATLAS.MappingAssertion,
                ATLAS.SourceAssignment,
                ATLAS.CrossRingRelationAssertion,
            )
            if statement_type in types
        ]
        if len(statement_types) != 1:
            raise ValueError(f"statement {subject} does not have one concrete type")
        statement_type = statement_types[0]
        record.update(
            {
                "statementType": _atlas_local_name(
                    statement_type,
                    context=f"{subject} statement type",
                ),
                "subject": str(
                    _one_graph_object(graph, subject, RDF.subject, expected_type=URIRef)
                ),
                "predicate": str(
                    _one_graph_object(graph, subject, RDF.predicate, expected_type=URIRef)
                ),
                "object": str(
                    _one_graph_object(graph, subject, RDF.object, expected_type=URIRef)
                ),
                "sourceRelease": str(
                    _one_graph_object(
                        graph,
                        subject,
                        ATLAS.sourceRelease,
                        expected_type=URIRef,
                    )
                ),
                "targetRelease": str(
                    _one_graph_object(
                        graph,
                        subject,
                        ATLAS.targetRelease,
                        expected_type=URIRef,
                    )
                ),
                "policy": str(
                    _one_graph_object(
                        graph,
                        subject,
                        ATLAS.governedByPolicy,
                        expected_type=URIRef,
                    )
                ),
                "assertedAt": str(
                    _one_graph_object(
                        graph,
                        subject,
                        RKAF.assertedAt,
                        expected_type=Literal,
                    )
                ),
                "assertionIdentityDigest": str(
                    _one_graph_object(
                        graph,
                        subject,
                        ATLAS.assertionIdentityDigest,
                        expected_type=Literal,
                    )
                ),
            }
        )
        if statement_type == ATLAS.CrossRingRelationAssertion:
            record["sourceRing"] = _atlas_local_name(
                _one_graph_object(
                    graph,
                    subject,
                    ATLAS.sourceRing,
                    expected_type=URIRef,
                ),
                context=f"{subject} source ring",
            )
            record["targetRing"] = _atlas_local_name(
                _one_graph_object(
                    graph,
                    subject,
                    ATLAS.targetRing,
                    expected_type=URIRef,
                ),
                context=f"{subject} target ring",
            )
        else:
            record["semanticRing"] = _atlas_local_name(
                _one_graph_object(
                    graph,
                    subject,
                    ATLAS.semanticRing,
                    expected_type=URIRef,
                ),
                context=f"{subject} semantic ring",
            )
        supersedes = list(graph.objects(subject, RKAF.supersedesAssertion))
        if len(supersedes) > 1:
            raise ValueError(f"statement {subject} supersedes multiple assertions")
        if supersedes:
            if not isinstance(supersedes[0], URIRef):
                raise TypeError(f"statement {subject} has a non-IRI supersession")
            record["supersedesAssertion"] = str(supersedes[0])
        return record

    if role == CompactRecordRole.EVIDENCE_BINDING:
        record.update(
            {
                "statement": str(
                    _one_graph_object(
                        graph,
                        subject,
                        RKAF.bindsAssertion,
                        expected_type=URIRef,
                    )
                ),
                "sourceRecord": str(
                    _one_graph_object(
                        graph,
                        subject,
                        ATLAS.evidenceSourceRecord,
                        expected_type=URIRef,
                    )
                ),
                "evidenceSourceDigest": str(
                    _one_graph_object(
                        graph,
                        subject,
                        ATLAS.evidenceSourceDigest,
                        expected_type=Literal,
                    )
                ),
                "attestor": str(
                    _one_graph_object(
                        graph,
                        subject,
                        RKAF.attestor,
                        expected_type=URIRef,
                    )
                ),
                **{
                    field: str(
                        _one_graph_object(
                            graph,
                            subject,
                            predicate,
                            expected_type=URIRef,
                        )
                    )
                    for field, predicate in (
                        ("attestorKind", RKAF.attestorKind),
                        ("assertionOrigin", RKAF.assertionOrigin),
                        ("epistemicBasis", RKAF.epistemicBasis),
                        ("evidenceRole", RKAF.evidenceRole),
                        ("evidentiaryFunction", RKAF.evidentiaryFunction),
                    )
                },
                "decision": str(
                    _one_graph_object(
                        graph,
                        subject,
                        RKAF.decision,
                        expected_type=URIRef,
                    )
                ),
                "attestedAt": str(
                    _one_graph_object(
                        graph,
                        subject,
                        RKAF.attestedAt,
                        expected_type=Literal,
                    )
                ),
            }
        )
        return record

    if role == CompactRecordRole.SOURCE_RECORD:
        payload = _one_graph_object(
            graph,
            subject,
            ATLAS.nativePayload,
            expected_type=Literal,
        )
        try:
            native_payload = json.loads(str(payload))
        except json.JSONDecodeError as error:
            raise ValueError(f"source record {subject} has invalid native JSON") from error
        record.update(
            {
                "sourceRelease": str(
                    _one_graph_object(
                        graph,
                        subject,
                        ATLAS.inSourceRelease,
                        expected_type=URIRef,
                    )
                ),
                "sourceDigest": str(
                    _one_graph_object(
                        graph,
                        subject,
                        ATLAS.sourceDigest,
                        expected_type=Literal,
                    )
                ),
                "sourceLocator": str(
                    _one_graph_object(
                        graph,
                        subject,
                        ATLAS.sourceLocator,
                        expected_type=URIRef,
                    )
                ),
                "nativePayload": native_payload,
            }
        )
        represented = list(graph.objects(subject, ATLAS.representsResource))
        if len(represented) > 1:
            raise ValueError(f"source record {subject} represents multiple resources")
        if represented:
            if not isinstance(represented[0], URIRef):
                raise TypeError(f"source record {subject} has a non-IRI resource")
            record["representsResource"] = str(represented[0])
        return record

    if role == CompactRecordRole.RELEASE:
        types = set(graph.objects(subject, RDF.type))
        source_release = ATLAS.SourceRelease in types
        atlas_release = ATLAS.AtlasRelease in types
        if source_release == atlas_release:
            raise ValueError(f"release {subject} has an ambiguous concrete type")
        record.update(
            {
                "releaseType": "SourceRelease" if source_release else "AtlasRelease",
                "identifier": str(
                    _one_graph_object(
                        graph,
                        subject,
                        DCTERMS.identifier,
                        expected_type=Literal,
                    )
                ),
                "issued": str(
                    _one_graph_object(
                        graph,
                        subject,
                        DCTERMS.issued,
                        expected_type=Literal,
                    )
                ),
            }
        )
        if source_release:
            record.update(
                {
                    "sourceDigest": str(
                        _one_graph_object(
                            graph,
                            subject,
                            ATLAS.sourceDigest,
                            expected_type=Literal,
                        )
                    ),
                    "sourceLocator": str(
                        _one_graph_object(
                            graph,
                            subject,
                            ATLAS.sourceLocator,
                            expected_type=URIRef,
                        )
                    ),
                }
            )
        else:
            record.update(
                {
                    "resourceProfile": _atlas_local_name(
                        _one_graph_object(
                            graph,
                            subject,
                            ATLAS.resourceProfile,
                            expected_type=URIRef,
                        ),
                        context=f"{subject} resource profile",
                    ),
                    "semanticRing": _atlas_local_name(
                        _one_graph_object(
                            graph,
                            subject,
                            ATLAS.semanticRing,
                            expected_type=URIRef,
                        ),
                        context=f"{subject} semantic ring",
                    ),
                    "scheme": str(
                        _one_graph_object(
                            graph,
                            subject,
                            ATLAS.inScheme,
                            expected_type=URIRef,
                        )
                    ),
                    "membershipMode": _rkaf_local_name(
                        _one_graph_object(
                            graph,
                            subject,
                            RKAF.membershipMode,
                            expected_type=URIRef,
                        ),
                        context=f"{subject} membership mode",
                    ),
                }
            )
        return record

    if role == CompactRecordRole.IDENTIFIER:
        record.update(
            {
                "identifierValue": str(
                    _one_graph_object(
                        graph,
                        subject,
                        ATLAS.identifierValue,
                        expected_type=Literal,
                    )
                ),
                "identifierScheme": str(
                    _one_graph_object(
                        graph,
                        subject,
                        ATLAS.identifierScheme,
                        expected_type=URIRef,
                    )
                ),
                "identifies": str(
                    _one_graph_object(
                        graph,
                        subject,
                        ATLAS.identifies,
                        expected_type=URIRef,
                    )
                ),
                "sourceRecord": str(
                    _one_graph_object(
                        graph,
                        subject,
                        ATLAS.sourceRecord,
                        expected_type=URIRef,
                    )
                ),
            }
        )
        return record
    if role == CompactRecordRole.LIFECYCLE_EVENT:
        source_records = sorted(
            str(value)
            for value in graph.objects(subject, ATLAS.sourceRecord)
            if isinstance(value, URIRef)
        )
        if not source_records or len(source_records) != len(
            list(graph.objects(subject, ATLAS.sourceRecord))
        ):
            raise ValueError(f"lifecycle event {subject} has invalid source records")
        record.update(
            {
                "appliesTo": str(
                    _one_graph_object(
                        graph,
                        subject,
                        RKAF.appliesTo,
                        expected_type=URIRef,
                    )
                ),
                "lifecycleEventKind": str(
                    _one_graph_object(
                        graph,
                        subject,
                        RKAF.lifecycleEventKind,
                        expected_type=URIRef,
                    )
                ),
                "effectiveDate": str(
                    _one_graph_object(
                        graph,
                        subject,
                        RKAF.effectiveDate,
                        expected_type=Literal,
                    )
                ),
                "sourceRecords": source_records,
            }
        )
        for field, predicate in (
            ("fromRelease", ATLAS.fromRelease),
            ("toRelease", ATLAS.toRelease),
        ):
            values = list(graph.objects(subject, predicate))
            if len(values) > 1:
                raise ValueError(f"lifecycle event {subject} has multiple {field} values")
            if values:
                if not isinstance(values[0], URIRef):
                    raise TypeError(f"lifecycle event {subject} has a non-IRI {field}")
                record[field] = str(values[0])
        return record
    raise AssertionError(f"unsupported compact role: {role}")






def _project_logical_records(
    asserted: Graph,
    *,
    pack_owners: Mapping[URIRef, tuple[str, str | None]],
    releases_by_key: Mapping[str, ReleasePackPlan],
    parquet: AtlasParquetTableWriter | None,
) -> dict[str, dict[str, int]]:
    """Project every release-owned subject into the typed Parquet tables.

    This is the walk that used to write the compact JSONL packs; the packs are
    gone and the tables are the served projection, so the walk feeds one
    consumer. Row order is role-major and, within a role, sorted by subject
    IRI: the compact packs took their order from release ownership and
    partitioning, and neither survives -- a table is one file per role -- so
    the order has to come from the records themselves to stay deterministic.

    Normalization happens here, once per record, because the row projection and
    the parity comparand must both see the same record.

    The per-release logical record counts the construction summary publishes
    are tallied here as well. They used to be read back off the compact pack
    inventory -- the producer counting its own output -- and are now taken from
    the graph walk, which is what the validator recomputes them against.

    The tally is keyed by construction-unit key, not by pack token. Those are
    two different strings: `pack_owners` is keyed for the filesystem, so
    `_release_pack_token` casefolds the unit key and replaces every character a
    pack path may not carry, which turns `eurovoc-4.24` into `eurovoc-4-24`.
    The construction summary is keyed by the unit itself. `releases_by_key`
    maps one to the other and is the only place that translation happens.
    """

    unit_key_by_token = {
        token: release.key for token, release in releases_by_key.items()
    }
    subjects_by_role: dict[CompactRecordRole, list[tuple[URIRef, str]]] = {
        role: [] for role in CompactRecordRole
    }
    for subject, (token, _) in pack_owners.items():
        subjects_by_role[_compact_record_role(asserted, subject)].append(
            (subject, unit_key_by_token[token])
        )
    record_counts: dict[str, dict[str, int]] = {
        unit_key_by_token[token]: dict.fromkeys(_COMPACT_ROLE_COUNT_FIELDS.values(), 0)
        for token, _ in pack_owners.values()
    }
    for role in CompactRecordRole:
        rows = subjects_by_role[role]
        rows.sort(key=lambda row: str(row[0]))
        count_field = _COMPACT_ROLE_COUNT_FIELDS[role.value]
        for subject, owner in rows:
            record_counts[owner][count_field] += 1
            if parquet is None:
                # `--no-parquet-view`: the counts are a construction fact and
                # are still owed, but projecting each record would be work
                # nothing reads.
                continue
            parquet.add(
                role,
                normalize_compact_record(
                    role,
                    _compact_record_from_graph(asserted, subject, role),
                ),
            )
    return record_counts


def _pack_spool_name(owner: str | None, partition: str | None) -> str:
    if owner is None:
        return "catalog"
    return owner if partition is None else f"{owner}-{partition}"


def _write_asserted_packs(
    output: Path,
    asserted: Graph,
    releases: Sequence[ReleasePackPlan],
    *,
    incremental: ColdPackMaterialization | None = None,
    parquet: AtlasParquetTableWriter | None = None,
    record_counts: dict[str, dict[str, int]] | None = None,
) -> list[dict[str, Any]]:
    """Write source-release-owned asserted packs and one shared catalog pack."""

    pack_owners, releases_by_key = _release_subject_owners(asserted, releases)
    graph_id = URIRef(_ROLE_GRAPH_IDS["asserted"])
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
            elif releases_by_key[owner].kind == "mapping":
                if partition is not None:
                    raise ValueError("mapping packs do not support source partitions")
                relative = Path("packs") / "mappings" / f"{owner}.nq.zst"
            else:
                filename = "all.nq.zst" if partition is None else f"{partition}.nq.zst"
                relative = Path("packs") / "sources" / owner / filename
            sorted_path = temporary / (_pack_spool_name(*key) + ".sorted.nq")
            with spool_path.open("r", encoding="utf-8", newline="") as lines:
                _write_sorted_lines(sorted_path, lines)
            target = output / relative
            receipt = _materialize_nquads_pack(
                sorted_path,
                target,
                relative_path=relative.as_posix(),
                incremental=incremental,
            )
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
                "kind": (
                    "catalog" if owner is None else releases_by_key[owner].kind
                ),
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
            for dependency in cross_pack_dependencies.get(key, set()):
                try:
                    dependency_ids.add(staged[dependency]["packId"])
                except KeyError as error:
                    raise ValueError(
                        f"RDF pack dependency has no written pack: {dependency}"
                    ) from error
            pack["dependencies"] = sorted(dependency_ids)
        if record_counts is not None:
            record_counts.update(
                _project_logical_records(
                    asserted,
                    pack_owners=pack_owners,
                    releases_by_key=releases_by_key,
                    parquet=parquet,
                )
            )
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
    incremental: ColdPackMaterialization | None = None,
) -> dict[str, Any] | None:
    if not graph:
        return None
    if role not in {"projection", "derived"}:
        raise ValueError(f"unsupported Atlas view graph role: {role}")
    relative = Path("packs") / "views" / f"{role}.nq.zst"
    with tempfile.TemporaryDirectory(prefix=f"atlas3-{role}-", dir=output) as raw_temp:
        sorted_path = Path(raw_temp) / f"{role}.nq"
        graph_id = URIRef(_ROLE_GRAPH_IDS[role])
        _write_sorted_lines(
            sorted_path,
            (
                ATLAS_VALIDATE.nquads_line(subject, predicate, obj, graph_id) + "\n"
                for subject, predicate, obj in graph
            ),
        )
        receipt = _materialize_nquads_pack(
            sorted_path,
            output / relative,
            relative_path=relative.as_posix(),
            incremental=incremental,
        )
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
    *,
    incremental: ColdPackMaterialization | None = None,
    parquet: AtlasParquetTableWriter | None = None,
    record_counts: dict[str, dict[str, int]] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if releases:
        asserted_packs = _write_asserted_packs(
            output,
            graphs.asserted,
            releases,
            incremental=incremental,
            parquet=parquet,
            record_counts=record_counts,
        )
    else:
        relative = Path("packs") / "atlas.nq.zst"
        with tempfile.TemporaryDirectory(prefix="atlas3-aggregate-", dir=output) as raw_temp:
            sorted_path = Path(raw_temp) / "atlas.nq"
            _write_sorted_lines(sorted_path, _dataset_lines(graphs))
            receipt = _materialize_nquads_pack(
                sorted_path,
                output / relative,
                relative_path=relative.as_posix(),
                incremental=incremental,
            )
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
                incremental=incremental,
            )
            if view is not None:
                packs.append(view)
    packs.sort(key=lambda pack: pack["packId"])
    graph_descriptors = []
    for role in ("asserted", "projection", "derived"):
        role_packs = [pack for pack in packs if pack["graphCounts"][role]]
        graph_descriptors.append(
            {
                "id": _ROLE_GRAPH_IDS[role],
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
    members_by_role = {member["role"]: member for member in manifest["members"]}
    construction_member = members_by_role.get("constructionSummary")
    if not isinstance(construction_member, Mapping):
        raise TypeError("manifest has no construction summary member")
    construction_path = ATLAS_VALIDATE._safe_distribution_path(
        output,
        construction_member["path"],
    )
    construction_summary = ATLAS_VALIDATE._load_json(
        construction_path,
        require_canonical=True,
        expected_digest=construction_member["digest"],
    )
    if not isinstance(construction_summary, Mapping):
        raise TypeError("construction summary root is not an object")
    expected_files = {
        "atlas-manifest.json",
        *(member["path"] for member in manifest["members"]),
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


_COMPACT_ROLE_COUNT_FIELDS = MappingProxyType(
    {
        "Resource": "resources",
        "Label": "labels",
        "Statement": "statements",
        "EvidenceBinding": "evidenceBindings",
        "SourceRecord": "sourceRecords",
        "Release": "releases",
        "Identifier": "identifiers",
        "LifecycleEvent": "lifecycleEvents",
    }
)


def _construction_base_build_keys(
    seeds: Sequence[ReleaseConstructionSeed],
    *,
    contract_digest: str,
) -> dict[str, dict[str, Any]]:
    """Derive deterministic pre-parse keys for every release-local unit."""

    values: dict[str, dict[str, Any]] = {}
    for seed in sorted(seeds, key=lambda item: item.key):
        input_inventory = sorted(
            (_plain(pin) for pin in seed.input_pins),
            key=lambda pin: (pin["path"], pin["role"], pin["sha256"]),
        )
        input_inventory_digest = _canonical_digest(input_inventory)
        adapter_recipe_inputs = sorted(
            (_plain(pin) for pin in seed.adapter_recipe_inputs),
            key=lambda pin: pin["path"],
        )
        adapter_recipe_digest = _adapter_recipe_digest(
            kind=seed.kind,
            inputs=adapter_recipe_inputs,
        )
        basis = _omit_absent_fields(
            {
                "adapterRecipeDigest": adapter_recipe_digest,
                "atlasRelease": seed.atlas_release_iri,
                "contractDigest": contract_digest,
                "constructionProfile": _CONSTRUCTION_SUMMARY_PROFILE,
                "inputInventoryDigest": input_inventory_digest,
                "key": seed.key,
                "kind": seed.kind,
                "languageScope": _LANGUAGE_SCOPE,
                "registrySource": seed.registry_source_iri,
                "resourceProfile": seed.resource_profile,
                "scheme": seed.scheme_iri,
                "semanticRing": seed.ring,
                "sourceRelease": seed.source_release_iri,
            }
        )
        values[seed.key] = {
            "adapterRecipeDigest": adapter_recipe_digest,
            "adapterRecipeInputCount": len(adapter_recipe_inputs),
            "adapterRecipeInputs": adapter_recipe_inputs,
            "baseBuildKey": _canonical_digest(basis),
            "inputFileCount": len(input_inventory),
            "inputInventoryDigest": input_inventory_digest,
            "inputs": input_inventory,
        }
    if len(values) != len(seeds):
        raise ValueError("Atlas construction seed keys are not unique")
    return values


def _construction_summary(
    *,
    accounting: Mapping[str, Any],
    binding: Mapping[str, Any],
    graph_descriptors: Sequence[Mapping[str, Any]],
    packs: Sequence[Mapping[str, Any]],
    plans: Sequence[ReleasePackPlan],
    record_counts: Mapping[str, Mapping[str, int]],
    seeds: Sequence[ReleaseConstructionSeed],
    source_accounting_digest: str,
) -> dict[str, Any]:
    """Build the authenticated index used for release-local reconstruction."""

    if not plans or not seeds:
        raise ValueError("construction summary requires release plans and seeds")
    plans_by_key = {plan.key: plan for plan in plans}
    seeds_by_key = {seed.key: seed for seed in seeds}
    if len(plans_by_key) != len(plans) or len(seeds_by_key) != len(seeds):
        raise ValueError("construction plans or seeds repeat a release key")
    if set(plans_by_key) != set(seeds_by_key):
        raise ValueError("construction plans and seeds name different release units")
    contract_digest = binding.get("contractDigest")
    if not isinstance(contract_digest, str):
        raise TypeError("candidate binding has no contract digest")
    base_keys = _construction_base_build_keys(
        seeds,
        contract_digest=contract_digest,
    )
    accounting_rows = {
        row["sourceRelease"]: row for row in accounting.get("inputs", ())
    }
    if len(accounting_rows) != len(accounting.get("inputs", ())):
        raise ValueError("source accounting contains duplicate release rows")
    expected_accounting_releases = {
        seed.source_release_iri for seed in seeds_by_key.values()
    }
    if set(accounting_rows) != expected_accounting_releases:
        raise ValueError("source accounting and construction release sets differ")
    if set(record_counts) != set(plans_by_key):
        raise ValueError("logical record counts and construction units differ")

    releases: list[dict[str, Any]] = []
    for key in sorted(plans_by_key):
        plan = plans_by_key[key]
        seed = seeds_by_key[key]
        if (
            plan.kind != seed.kind
            or plan.source_release_iri != seed.source_release_iri
            or plan.atlas_release_iri != seed.atlas_release_iri
            or plan.ring != seed.ring
        ):
            raise ValueError(f"construction plan and seed differ for {key}")
        try:
            accounting_row = accounting_rows[seed.source_release_iri]
        except KeyError as error:
            raise ValueError(f"construction unit {key} has no accounting row") from error
        endpoint_dependencies = [
            {
                "baseBuildKey": base_keys[dependency_key]["baseBuildKey"],
                "releaseKey": dependency_key,
                "sourceRelease": seeds_by_key[dependency_key].source_release_iri,
            }
            for dependency_key in sorted(seed.endpoint_release_keys)
        ]
        build_key = _canonical_digest(
            {
                "baseBuildKey": base_keys[key]["baseBuildKey"],
                "constructionProfile": _CONSTRUCTION_SUMMARY_PROFILE,
                "endpointDependencies": endpoint_dependencies,
            }
        )
        rdf_packs = sorted(
            (
                {
                    "contentDigest": pack["content"]["digest"],
                    "packId": pack["packId"],
                    "path": pack["path"],
                }
                for pack in packs
                if pack["kind"] == plan.kind
                and pack["sourceReleases"] == [plan.source_release_iri]
            ),
            key=lambda pack: pack["path"],
        )
        if not rdf_packs:
            raise ValueError(f"construction unit {key} owns no RDF packs")
        owned_record_counts = dict(record_counts[key])
        if set(owned_record_counts) != set(_COMPACT_ROLE_COUNT_FIELDS.values()):
            raise ValueError(f"construction unit {key} has an unsupported record count field")
        if not any(owned_record_counts.values()):
            raise ValueError(f"construction unit {key} owns no logical records")
        release_row = {
            "accountingRowDigest": _canonical_digest(accounting_row),
            "adapterRecipeDigest": base_keys[key]["adapterRecipeDigest"],
            "adapterRecipeInputCount": base_keys[key]["adapterRecipeInputCount"],
            "adapterRecipeInputs": base_keys[key]["adapterRecipeInputs"],
            **(
                {"atlasRelease": seed.atlas_release_iri}
                if seed.atlas_release_iri is not None
                else {}
            ),
            "baseBuildKey": base_keys[key]["baseBuildKey"],
            "buildKey": build_key,
            "endpointDependencies": endpoint_dependencies,
            "inputFileCount": base_keys[key]["inputFileCount"],
            "inputInventoryDigest": base_keys[key]["inputInventoryDigest"],
            "inputs": base_keys[key]["inputs"],
            "key": key,
            "kind": seed.kind,
            "rdfPacks": rdf_packs,
            "recordCounts": owned_record_counts,
            "semanticRing": seed.ring,
            "sourceRelease": seed.source_release_iri,
            **(
                {
                    "resourceProfile": seed.resource_profile,
                    **(
                        {"registrySource": seed.registry_source_iri}
                        if seed.registry_source_iri is not None
                        else {}
                    ),
                    "scheme": seed.scheme_iri,
                }
                if seed.kind == "sourceRelease"
                else {}
            ),
        }
        if seed.kind == "sourceRelease" and (
            seed.resource_profile is None or seed.scheme_iri is None
        ):
            raise ValueError(f"source construction unit {key} lacks scheme metadata")
        if seed.kind == "mapping" and (
            seed.resource_profile is not None
            or seed.scheme_iri is not None
            or seed.registry_source_iri is not None
        ):
            raise ValueError(f"mapping construction unit {key} has scheme metadata")
        releases.append(release_row)

    owned_rdf_path_counts = Counter(
        rdf_pack["path"] for release in releases for rdf_pack in release["rdfPacks"]
    )
    expected_owned_rdf_paths = {
        pack["path"]
        for pack in packs
        if pack["kind"] in {"sourceRelease", "mapping"}
    }
    if (
        set(owned_rdf_path_counts) != expected_owned_rdf_paths
        or any(count != 1 for count in owned_rdf_path_counts.values())
    ):
        raise ValueError("release construction RDF ownership is incomplete")

    catalog_packs = [pack for pack in packs if pack["kind"] == "catalog"]
    if len(catalog_packs) != 1:
        raise ValueError("construction summary requires exactly one catalog RDF pack")
    catalog_pack = catalog_packs[0]
    catalog_inputs = [
        {
            "byteLength": REGISTRY_DESCRIPTORS.stat().st_size,
            "path": REGISTRY_DESCRIPTORS_LOGICAL_PATH,
            "role": "registryDescriptors",
            "sha256": REGISTRY_DESCRIPTORS_EXPECTED_DIGEST,
            "sourceIri": "urn:ref:atlas:registry-descriptors:3.1",
        },
        {
            "byteLength": REGISTRY_DESCRIPTORS_PROOF.stat().st_size,
            "path": REGISTRY_DESCRIPTORS_PROOF_LOGICAL_PATH,
            "role": "registryDescriptorProof",
            "sha256": REGISTRY_DESCRIPTORS_PROOF_EXPECTED_DIGEST,
            "sourceIri": "urn:ref:atlas:registry-descriptor-proof:3.1",
        },
    ]
    catalog_inputs.sort(key=lambda pin: (pin["path"], pin["role"], pin["sha256"]))
    catalog_input_digest = _canonical_digest(catalog_inputs)
    scheme_inventory = [
        {
            "atlasRelease": row["atlasRelease"],
            "key": row["key"],
            "resourceProfile": row["resourceProfile"],
            **(
                {"registrySource": row["registrySource"]}
                if "registrySource" in row
                else {}
            ),
            "semanticRing": row["semanticRing"],
            "scheme": row["scheme"],
        }
        for row in releases
        if row["kind"] == "sourceRelease"
    ]
    release_scheme_inventory_digest = _canonical_digest(scheme_inventory)
    catalog = {
        "buildKey": _canonical_digest(
            {
                "contractDigest": contract_digest,
                "catalogInputInventoryDigest": catalog_input_digest,
                "constructionProfile": _CONSTRUCTION_SUMMARY_PROFILE,
                "languageScope": _LANGUAGE_SCOPE,
                "releaseSchemeInventoryDigest": release_scheme_inventory_digest,
            }
        ),
        "inputInventoryDigest": catalog_input_digest,
        "inputs": catalog_inputs,
        "releaseSchemeInventoryDigest": release_scheme_inventory_digest,
        "rdfPack": {
            "contentDigest": catalog_pack["content"]["digest"],
            "packId": catalog_pack["packId"],
            "path": catalog_pack["path"],
        },
    }
    asserted_inventory_digest = next(
        descriptor["inventoryDigest"]
        for descriptor in graph_descriptors
        if descriptor["role"] == "asserted"
    )
    summary: dict[str, Any] = {
        "assertedInventoryDigest": asserted_inventory_digest,
        "contractDigest": contract_digest,
        "catalog": catalog,
        "distributionId": _distribution_id(accounting),
        "languageScope": _LANGUAGE_SCOPE,
        "profile": _CONSTRUCTION_SUMMARY_PROFILE,
        "releaseCount": len(releases),
        "releaseInventoryDigest": _canonical_digest(releases),
        "releases": releases,
        "sourceAccountingDigest": source_accounting_digest,
        "type": "AtlasConstructionSummary",
        "version": "3.1",
    }
    summary["canonicalPayloadDigest"] = ATLAS_VALIDATE.canonical_sha256(
        summary,
        terminal_lf=False,
    )
    return summary


def _construction_summary_receipt(
    path: Path,
    summary: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "digest": _sha256_file(path),
        "path": path.name,
        "profile": _CONSTRUCTION_SUMMARY_RECEIPT_PROFILE,
        "releaseCount": summary["releaseCount"],
        "releaseInventoryDigest": summary["releaseInventoryDigest"],
    }


def _producer_validation_receipt(
    report: Mapping[str, Any],
    *,
    binding: Mapping[str, Any],
    asserted_inventory_digest: str,
    construction_summary_receipt: Mapping[str, Any],
) -> dict[str, Any]:
    """Turn the in-memory constructor receipt into a portable receipt.

    It is a receipt, not a proof, and the difference was load-bearing: the
    former ``shaclDataProof: compiledAgainstPinnedOntologyAndShapes`` claim
    passed while the normative shapes rejected 2,003 evidence bindings, and
    ``shaclMetaValidation`` and the eight-line ``checks`` prose asserted the
    same thing in three more registers. What is left is what the producer can
    actually show a reader: which constructor profile ran, what it counted,
    and which exact serialized bytes those counts belong to. Semantic
    conformance is the independent validator's verdict.
    """

    if set(report) != {
        "bindingProfile",
        "constructorProfile",
        "counts",
        "mode",
        "sourceAccountingDigest",
        "sourceReleaseCount",
        "status",
    }:
        raise ValueError("producer validation report fields differ")
    if (
        report.get("status") != "passed"
        or report.get("mode") != _COMPILED_PRODUCER_MODE
        or report.get("constructorProfile") != _COMPILED_PRODUCER_PROFILE
    ):
        raise ValueError("producer validation report identity differs")
    binding_profile = report.get("bindingProfile")
    if not isinstance(binding_profile, Mapping) or not binding_profile:
        raise ValueError("producer validation report records no binding profile")
    # The candidate's binding block is hashed off disk again here, at the end of
    # a build that can run for half an hour. Comparing it against the profile
    # this build actually validated against is what catches a binding edited
    # underneath a running build -- a real disagreement between two readings,
    # unlike the compiled pin table this replaced.
    if any(binding.get(field) != digest for field, digest in binding_profile.items()):
        raise ValueError("the binding changed on disk during this build")
    if (
        not isinstance(report.get("sourceReleaseCount"), int)
        or report["sourceReleaseCount"] < 1
    ):
        raise ValueError("producer validation report is incomplete")
    return {
        "assertedInventoryDigest": asserted_inventory_digest,
        "binding": dict(binding),
        "constructionSummary": dict(construction_summary_receipt),
        "constructorProfile": report["constructorProfile"],
        "counts": dict(report["counts"]),
        "mode": report["mode"],
        "sourceAccountingDigest": report["sourceAccountingDigest"],
        "sourceReleaseCount": report["sourceReleaseCount"],
        "status": report["status"],
        "type": "AtlasProducerValidation",
        "version": "3.1",
    }


def _check_producer_validation_receipt(
    report: Mapping[str, Any],
    *,
    manifest: Mapping[str, Any],
    accounting_path: Path,
    construction_summary_path: Path,
) -> None:
    """Bind the portable producer receipt to the exact serialized candidate."""

    if set(report) != {
        "assertedInventoryDigest",
        "binding",
        "constructorProfile",
        "constructionSummary",
        "counts",
        "mode",
        "sourceAccountingDigest",
        "sourceReleaseCount",
        "status",
        "type",
        "version",
    }:
        raise ValueError("producer validation receipt fields differ")
    if (
        report.get("type") != "AtlasProducerValidation"
        or report.get("version") != "3.1"
        or report.get("status") != "passed"
        or report.get("mode") != _COMPILED_PRODUCER_MODE
        or report.get("constructorProfile") != _COMPILED_PRODUCER_PROFILE
    ):
        raise ValueError("producer validation receipt identity differs")
    if report.get("binding") != manifest.get("binding"):
        raise ValueError("producer validation binding differs")
    asserted_inventory_digest = next(
        row["inventoryDigest"]
        for row in manifest["graphs"]
        if row["role"] == "asserted"
    )
    if report.get("assertedInventoryDigest") != asserted_inventory_digest:
        raise ValueError("producer asserted inventory digest differs")
    if report.get("counts") != manifest.get("counts"):
        raise ValueError("producer counts differ from the candidate manifest")
    if report.get("sourceAccountingDigest") != _sha256_file(accounting_path):
        raise ValueError("producer source accounting digest differs")
    accounting = json.loads(accounting_path.read_bytes())
    if report.get("sourceReleaseCount") != accounting.get("totals", {}).get(
        "sourceReleases"
    ):
        raise ValueError("producer source release count differs")
    construction_summary = json.loads(construction_summary_path.read_bytes())
    expected_construction_receipt = _construction_summary_receipt(
        construction_summary_path,
        construction_summary,
    )
    if report.get("constructionSummary") != expected_construction_receipt:
        raise ValueError("producer construction summary receipt differs")


def _write_candidate_distribution(
    output: Path,
    graphs: BuildGraphs,
    releases: Sequence[ReleasePackPlan] = (),
    *,
    created_at: str,
    compiled_validation: Mapping[str, Any] | None = None,
    construction_seeds: Sequence[ReleaseConstructionSeed] = (),
    parquet_tables: Path | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Write and producer-validate a candidate that is not yet publishable.

    ``parquet_tables`` names a directory outside the distribution where the
    typed Parquet tables are staged as the graph is walked. They are not
    distribution members -- the wire is unchanged -- and the caller closes the
    view over them once the manifest they are pinned to exists.
    """

    if compiled_validation is None:
        raise ValueError("candidate writing requires compiled producer validation")
    if not releases or not construction_seeds:
        raise ValueError("candidate writing requires release-local construction inputs")
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

    incremental = ColdPackMaterialization()
    output.mkdir(parents=True, exist_ok=True)
    extras = sorted(path.name for path in output.iterdir())
    if extras:
        raise FileExistsError(f"distribution contains unexpected existing files: {extras}")

    accounting_path = output / "atlas-source-accounting.json"
    acceptance_path = output / "atlas-acceptance.json"
    construction_summary_path = output / "atlas-construction-summary.json"
    manifest_path = output / "atlas-manifest.json"
    producer_validation_path = output / "atlas-producer-validation.json"
    record_counts: dict[str, dict[str, int]] = {}
    _STATUS.phase("write-rdf-packs-and-parquet-tables")
    parquet = None if parquet_tables is None else AtlasParquetTableWriter(parquet_tables)
    parquet_parity: dict[str, Any] | None = None
    try:
        packs, graph_descriptors = _write_graph_packs(
            output,
            graphs,
            releases,
            incremental=incremental,
            parquet=parquet,
            record_counts=record_counts,
        )
        if parquet is not None:
            parquet.close()
    except BaseException:
        if parquet is not None:
            parquet.__exit__()
        raise
    if graphs.asserted.revision != graphs.sealed_asserted_revision:
        raise ValueError("asserted graph changed while writing Atlas packs")
    if parquet_tables is not None:
        # Here, and not after the manifest: `graphs.release()` empties the
        # asserted graph at the end of this function, and the comparand needs
        # the graph the rows were emitted from, not a re-parse of the packs.
        _STATUS.phase("check-parquet-view-against-rdf")
        parquet_parity = _check_parquet_view_against_graph(parquet_tables, graphs.asserted)
        if graphs.asserted.revision != graphs.sealed_asserted_revision:
            raise ValueError("asserted graph changed while checking the Parquet view")
    _STATUS.phase("write-receipts-and-manifest")
    accounting_path.write_bytes(
        ATLAS_VALIDATE.canonical_json_bytes(graphs.accounting)
    )

    binding_digests = ATLAS_VALIDATE._binding_digests()
    binding = {
        "validatorVersion": "3.1",
        "version": "3.1",
        **binding_digests,
    }
    construction_summary = _construction_summary(
        accounting=graphs.accounting,
        binding=binding,
        graph_descriptors=graph_descriptors,
        packs=packs,
        plans=releases,
        record_counts=record_counts,
        seeds=construction_seeds,
        source_accounting_digest=_sha256_file(accounting_path),
    )
    construction_summary_path.write_bytes(
        ATLAS_VALIDATE.canonical_json_bytes(construction_summary)
    )
    producer_validation = _producer_validation_receipt(
        compiled_validation,
        binding=binding,
        asserted_inventory_digest=graph_descriptors[0]["inventoryDigest"],
        construction_summary_receipt=_construction_summary_receipt(
            construction_summary_path,
            construction_summary,
        ),
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
    validator_identity = {"name": "refspec-atlas-conformance", "version": "3.1"}
    distribution_id = _distribution_id(graphs.accounting)
    acceptance = {
        # Proof identity, recorded beside the validator identity it qualifies:
        # which validator ran, and which conformance corpus that validator was
        # answerable to. Deliberately not part of `binding.contractDigest` --
        # growing the corpus must not invalidate an artifact already on disk.
        "corpusDigest": ATLAS_VALIDATE.corpus_digest(),
        "distributionId": distribution_id,
        "evaluatedAt": created_at,
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
        "version": "3.1",
    }
    acceptance_path.write_bytes(ATLAS_VALIDATE.canonical_json_bytes(acceptance))

    manifest = {
        "binding": binding,
        "counts": dict(compiled_counts),
        "createdAt": created_at,
        "distributionId": distribution_id,
        "format": "refspec-atlas-packed-nquads-3.1",
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
            _file_member(
                construction_summary_path,
                role="constructionSummary",
                media_type="application/json",
            ),
        ],
        "packs": packs,
        "schemaVersion": "3.1",
        "type": "AtlasManifest",
    }
    manifest["canonicalPayloadDigest"] = ATLAS_VALIDATE.canonical_sha256(
        manifest, terminal_lf=False
    )
    manifest_path.write_bytes(ATLAS_VALIDATE.canonical_json_bytes(manifest))

    _STATUS.phase("validate-candidate-metadata")
    schemas, registry = ATLAS_VALIDATE._schema_registry()
    for value, schema_name, label in (
        (manifest, "manifest", "manifest"),
        (graphs.accounting, "sourceAccounting", "source accounting"),
        (acceptance, "acceptance", "acceptance"),
        (producer_validation, "producerValidation", "producer validation"),
        (construction_summary, "constructionSummary", "construction summary"),
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
    ATLAS_VALIDATE._check_construction_summary_identity(
        manifest,
        producer_validation,
        construction_summary,
        member_digests,
    )
    ATLAS_VALIDATE._check_construction_accounting(
        construction_summary,
        graphs.accounting,
    )
    ATLAS_VALIDATE._check_producer_validation(
        manifest,
        acceptance,
        producer_validation,
        construction_summary,
        member_digests,
        graphs.accounting,
    )
    ATLAS_VALIDATE._check_acceptance_metadata(
        manifest,
        acceptance,
        member_digests,
    )
    writer_receipts = _trusted_writer_receipt_checks(output, manifest=manifest)
    _check_producer_validation_receipt(
        producer_validation,
        manifest=manifest,
        accounting_path=accounting_path,
        construction_summary_path=construction_summary_path,
    )
    graphs.release()
    result: dict[str, Any] = {
        "independentFileConsumerValidation": {
            "performedByGenerator": False,
            "requiredForIndependentConsumers": True,
            "validator": (
                "bindings/atlas/3.1/tools/validate.py:validate_distribution"
            ),
        },
        "compiledProducerValidation": producer_validation,
        "packMaterialization": incremental.report(),
        "status": "passed",
        "trustedWriterReceiptChecks": writer_receipts,
    }
    if parquet_parity is not None:
        result["parquetViewParity"] = parquet_parity
    return result, manifest


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
    construction_seeds: Sequence[ReleaseConstructionSeed] = (),
    generation_report: Mapping[str, Any],
    compiled_validation: Mapping[str, Any],
    parquet_view: Path | None = None,
) -> dict[str, Any]:
    """Validate in a sibling temporary directory, then promote the result."""

    output.parent.mkdir(parents=True, exist_ok=True)
    counts = compiled_validation.get("counts")
    if not isinstance(counts, Mapping):
        raise TypeError("compiled producer validation has no count receipt")
    created_at = generation_report.get("createdAt")
    if not isinstance(created_at, str) or not created_at:
        raise TypeError("generation report has no recorded instant")
    distribution_id = _distribution_id(graphs.accounting)
    relation_scope = _production_relation_scope_from_counts(counts)
    report_distribution_path = _generation_report_distribution_path(output)
    with tempfile.TemporaryDirectory(
        prefix=f".{output.name}.candidate-",
        dir=output.parent,
    ) as raw_temporary_root:
        temporary_root = Path(raw_temporary_root)
        candidate = temporary_root / "distribution"
        staged_tables = None if parquet_view is None else temporary_root / "parquet-view"
        result, manifest = _write_candidate_distribution(
            candidate,
            graphs,
            releases,
            created_at=created_at,
            compiled_validation=compiled_validation,
            construction_seeds=construction_seeds,
            parquet_tables=staged_tables,
        )
        if staged_tables is not None:
            # The tables were streamed out of the graph while the packs were
            # written; only their authenticated identity was missing, and the
            # manifest they pin now exists.
            _STATUS.phase("seal-parquet-view")
            sealed_view = temporary_root / "sealed-parquet-view"
            seal_atlas_parquet_view(
                candidate,
                staged_tables,
                sealed_view,
                expected_manifest_digest=_sha256_file(candidate / "atlas-manifest.json"),
            )
        report = {
            **_plain(generation_report),
            "distribution": {
                "id": distribution_id,
                "manifestDigest": _sha256_file(candidate / "atlas-manifest.json"),
                "path": report_distribution_path,
            },
            "productionRelationScope": relation_scope,
            "validation": result,
        }
        candidate_report = temporary_root / "generation-report.json"
        candidate_report.write_bytes(ATLAS_VALIDATE.canonical_json_bytes(report))
        if manifest["distributionId"] != distribution_id:
            raise ValueError("candidate manifest distribution identity differs")
        report_path = _generation_report_path(output)
        if report_path.exists() and not (
            report_path.is_file() or report_path.is_symlink()
        ):
            raise FileExistsError(
                f"generation report path is not replaceable: {report_path}"
            )
        _STATUS.phase("promote-validated-distribution")
        _promote_validated_distribution(
            candidate,
            output,
            temporary_root=temporary_root,
        )
        if parquet_view is not None:
            previous_view_root = temporary_root / "previous-parquet-view"
            previous_view_root.mkdir()
            _promote_validated_distribution(
                sealed_view,
                parquet_view,
                temporary_root=previous_view_root,
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


def _mapping_release_summary(
    release: RegistryMappingRelease,
) -> dict[str, Any]:
    """Summarize one mapping collection without inventing a shared decision."""

    return {
        "editorialPolicyDigest": _canonical_digest(release.editorial_policy),
        "evidenceBindingCount": sum(
            len(mapping.evidence) for mapping in release.mappings
        ),
        "key": release.key,
        "mappingCount": len(release.mappings),
        "reviewMethods": sorted(
            {
                evidence.review_warrant
                for mapping in release.mappings
                for evidence in mapping.evidence
            }
        ),
        "scope": release.scope,
        "sourceRelease": release.source_release_iri,
    }


def verify_inputs(
    releases: tuple[LoadedRelease, ...] | None = None,
    mapping_releases: Sequence[RegistryMappingRelease] = (),
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
    for mapping_release in mapping_releases:
        for pin in mapping_release.inputs:
            identity = (pin.sha256, pin.byte_length)
            previous = verified_pins.get(pin.logical_path)
            if previous is not None:
                if previous != identity:
                    raise ValueError(
                        f"pinned input identity conflicts for {pin.logical_path}"
                    )
                continue
            pin.verify()
            verified_pins[pin.logical_path] = identity
    registry = Dataset(default_union=True)
    registry.parse(REGISTRY_DESCRIPTORS, format="nquads")
    descriptors = set(registry.subjects(RDF.type, ATLAS.ResourceScheme))
    if len(descriptors) != 88:
        raise ValueError(f"expected 88 registry descriptors; found {len(descriptors)}")

    return {
        "expectedResources": sum(source.expected_resources for source in sources),
        "registryDescriptors": len(descriptors),
        "registryDescriptorsPin": {
            "byteLength": REGISTRY_DESCRIPTORS.stat().st_size,
            "digest": REGISTRY_DESCRIPTORS_EXPECTED_DIGEST,
            "path": REGISTRY_DESCRIPTORS_LOGICAL_PATH,
        },
        "registryDescriptorsProofPin": {
            "byteLength": REGISTRY_DESCRIPTORS_PROOF.stat().st_size,
            "digest": REGISTRY_DESCRIPTORS_PROOF_EXPECTED_DIGEST,
            "path": REGISTRY_DESCRIPTORS_PROOF_LOGICAL_PATH,
        },
        "mappingSources": [
            {
                **_mapping_release_summary(release),
                "inputs": [
                    {
                        "byteLength": pin.byte_length,
                        "path": pin.logical_path,
                        "role": pin.role,
                        "sha256": pin.sha256,
                        "sourceIri": pin.source_iri,
                    }
                    for pin in release.inputs
                ],
            }
            for release in mapping_releases
        ],
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

    counts = {
        "crossRingRelations": len(release.cross_ring_relations),
        "identifiers": sum(len(resource.identifiers) for resource in release.resources),
        "nativeRelations": len(release.relations),
        "resources": len(release.resources),
    }
    if release.supplemental_source_records:
        counts["supplementalSourceRecords"] = len(
            release.supplemental_source_records
        )
    return counts


def _release_label_role_conflict_count(release: LoadedRelease) -> int:
    value = release.metadata.get("labelRoleConflictCount", 0)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(
            f"{release.spec.key} labelRoleConflictCount is not a non-negative integer"
        )
    return value


def _release_english_family_duplicate_label_count(release: LoadedRelease) -> int:
    value = release.metadata.get("englishFamilyDuplicateLabelCount", 0)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(
            f"{release.spec.key} englishFamilyDuplicateLabelCount is not a "
            "non-negative integer"
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
    mapping_releases: Sequence[RegistryMappingRelease] = (),
) -> tuple[ReleasePackPlan, ...]:
    plans = tuple(_release_pack_plan(release) for release in releases) + tuple(
        ReleasePackPlan(
            key=release.key,
            source_release_iri=release.source_release_iri,
            atlas_release_iri=None,
            ring=release.ring,
            resource_count=len(release.mappings),
            kind="mapping",
        )
        for release in mapping_releases
    )
    tokens = [_release_pack_token(plan) for plan in plans]
    if len(tokens) != len(set(tokens)):
        raise ValueError(
            "Atlas release keys collide after safe pack-path normalization"
        )
    return plans


def _construction_input_pin(pin: RegistryInputPin) -> dict[str, Any]:
    """Return one canonical raw-input pin without its machine-local path."""

    return {
        "byteLength": pin.byte_length,
        "path": pin.logical_path,
        "role": pin.role,
        "sha256": pin.sha256,
        "sourceIri": pin.source_iri,
    }


def _release_construction_seeds(
    releases: Sequence[LoadedRelease],
    mapping_releases: Sequence[RegistryMappingRelease] = (),
) -> tuple[ReleaseConstructionSeed, ...]:
    """Describe release-local raw inputs and cross-release endpoint dependencies."""

    resource_owner: dict[str, str] = {}
    for release in releases:
        for resource in release.resources:
            previous = resource_owner.setdefault(resource.iri, release.spec.key)
            if previous != release.spec.key:
                raise ValueError(
                    f"Atlas resource belongs to multiple construction units: {resource.iri}"
                )

    def endpoint_owner(resource_iri: str, *, context: str) -> str:
        owner = resource_owner.get(resource_iri)
        if owner is not None:
            return owner
        raise ValueError(
            f"{context} endpoint is outside the loaded construction units: "
            f"{resource_iri}"
        )

    seeds: list[ReleaseConstructionSeed] = []
    for release in releases:
        dependency_keys = {
            endpoint_owner(endpoint, context=f"{release.spec.key} relation")
            for relation in (*release.relations, *release.cross_ring_relations)
            for endpoint in (relation.subject, relation.object)
        }
        dependency_keys.discard(release.spec.key)
        seeds.append(
            ReleaseConstructionSeed(
                key=release.spec.key,
                source_release_iri=release.source_release_iri,
                atlas_release_iri=release.atlas_release_iri,
                ring=release.spec.ring,
                input_pins=tuple(
                    _construction_input_pin(pin)
                    for pin in sorted(
                        _source_input_pins(release.spec),
                        key=lambda item: item.logical_path,
                    )
                ),
                adapter_recipe_inputs=_adapter_recipe_inputs(
                    key=release.spec.key,
                    kind="sourceRelease",
                    source_module=release.spec.source_module,
                ),
                resource_profile=release.spec.profile,
                scheme_iri=release.scheme_iri,
                registry_source_iri=(
                    str(_registry_source_descriptor_iri(release.spec.resource_id))
                    if release.spec.resource_id is not None
                    else None
                ),
                endpoint_release_keys=tuple(sorted(dependency_keys)),
            )
        )
    for release in mapping_releases:
        dependency_keys = {
            endpoint_owner(endpoint, context=f"{release.key} mapping")
            for mapping in release.mappings
            for endpoint in (mapping.subject, mapping.object)
        }
        seeds.append(
            ReleaseConstructionSeed(
                key=release.key,
                source_release_iri=release.source_release_iri,
                atlas_release_iri=None,
                ring=release.ring,
                input_pins=tuple(
                    _construction_input_pin(pin)
                    for pin in sorted(release.inputs, key=lambda item: item.logical_path)
                ),
                adapter_recipe_inputs=_adapter_recipe_inputs(
                    key=release.key,
                    kind="mapping",
                    source_module=release.source_module,
                ),
                endpoint_release_keys=tuple(sorted(dependency_keys)),
                kind="mapping",
            )
        )
    keys = [seed.key for seed in seeds]
    if len(keys) != len(set(keys)):
        raise ValueError("Atlas construction unit keys are not unique")
    known_keys = set(keys)
    for seed in seeds:
        unknown = sorted(set(seed.endpoint_release_keys) - known_keys)
        if unknown:
            raise ValueError(
                f"{seed.key} construction dependencies are missing: {unknown}"
            )
        if not seed.input_pins:
            raise ValueError(f"{seed.key} construction unit has no raw-input pins")
    return tuple(sorted(seeds, key=lambda seed: seed.key))


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
        "supplementalSourceRecords": 0,
    }
    for release in releases:
        for key, value in _release_direct_source_counts(release).items():
            counts[key] += value
    if not counts["supplementalSourceRecords"]:
        del counts["supplementalSourceRecords"]
    return counts


def _check_parquet_view_against_graph(view: Path, asserted: Graph) -> dict[str, Any]:
    """Prove the emitted Parquet tables against the graph they were built from.

    The comparand is the binding validator's, not this file's: the producer
    wrote these tables, so nothing the producer computed is allowed to stand
    on both sides.  Three tiers, priced separately:

    * every row of every table, by identity -- full `id` set equality against
      what the asserted RDF says each role's records are, both directions.
      This is `_check_explorer_reachability`, the property the compact layer
      used to carry: a record missing from the tables is one no filter, no
      search and neither concept endpoint can ever reach, a record present
      only in them is one the distribution never asserted, and a repeated id
      is both at once.  Counts cannot see any of the three and the row sample
      reads too few positions to, so the identities have to be compared.
    * every source-record row, exhaustively -- ``sha256(native_payload)``
      against the ``source_digest`` column that row publishes.  This is a
      column scan, so breadth is nearly free, and ``atlas:sourceDigest`` is
      what a record-level citation resolves through.
    * up to five stable positions per table -- the whole row against
      ``ATLAS_VALIDATE.parquet_row_from_rdf``, which re-derives every column,
      including all five warrant columns, from the asserted RDF.
    """

    payload_rows = 0
    served_ids: dict[str, list[str]] = {}
    for role in CompactRecordRole:
        parquet = pq.ParquetFile(view / TABLE_DIRECTORY / TABLE_NAMES[role])
        identities: list[str] = []
        if role is CompactRecordRole.SOURCE_RECORD:
            for batch in parquet.iter_batches(columns=["id", "native_payload", "source_digest"]):
                for identity, payload, digest in zip(
                    batch.column("id").to_pylist(),
                    batch.column("native_payload").to_pylist(),
                    batch.column("source_digest").to_pylist(),
                    strict=True,
                ):
                    if hashlib.sha256(payload).digest() != digest:
                        raise ValueError(
                            f"Parquet native_payload does not hash to source_digest: {identity}"
                        )
                    identities.append(identity)
                    payload_rows += 1
        else:
            for batch in parquet.iter_batches(columns=["id"]):
                identities.extend(batch.column("id").to_pylist())
        served_ids[role.value] = identities

    # Before any row is reconciled: a table carrying a record the graph never
    # asserted has no RDF facts to compare a row against, so reaching the
    # sample first would report the absence rather than the substitution.
    ATLAS_VALIDATE._check_explorer_reachability(
        served_ids,
        ATLAS_VALIDATE._rdf_record_ids_by_role(asserted),
    )

    sampled_rows = 0
    for role in CompactRecordRole:
        parquet = pq.ParquetFile(view / TABLE_DIRECTORY / TABLE_NAMES[role])
        row_count = parquet.metadata.num_rows
        wanted = ATLAS_VALIDATE._compact_sample_indices(row_count)
        if not wanted:
            continue
        last = max(wanted)
        position = 0
        for batch in parquet.iter_batches():
            if position > last:
                break
            length = batch.num_rows
            hits = sorted(index for index in wanted if position <= index < position + length)
            if hits:
                rows = batch.to_pylist()
                for index in hits:
                    row = rows[index - position]
                    ATLAS_VALIDATE.check_parquet_row_against_rdf(
                        asserted,
                        URIRef(row["id"]),
                        role.value,
                        row,
                    )
                    sampled_rows += 1
            position += length
    return {
        "comparand": "bindings/atlas/3.1/tools/validate.py:parquet_row_from_rdf",
        "reachabilityComparand": (
            "bindings/atlas/3.1/tools/validate.py:_check_explorer_reachability"
        ),
        "reachabilityRows": sum(len(rows) for rows in served_ids.values()),
        "sampledRowsAgainstRdf": sampled_rows,
        "sourceRecordPayloadRows": payload_rows,
        "status": "passed",
    }


def _parquet_view_path(output: Path) -> Path:
    """Name the Parquet view beside its distribution, never inside it.

    A distribution validates its own membership as a closed set, so a derived
    view written into that directory would make the artifact fail its own
    walk. The generation report already sits here for the same reason.
    """

    return output.parent / "parquet-view"


def build_distribution(
    output: Path,
    *,
    registry_claim_inputs: Mapping[str, AtlasRegistryClaimInput] | None = None,
    include_keys: frozenset[str] | None = None,
    parquet_view: bool = True,
) -> None:
    """Build, validate, and atomically promote the Atlas 3 distribution.

    Every build is cold. ``include_keys`` bounds the build to a named set of
    construction units. Every later step is already release-scoped -- input
    verification, compiled producer validation, the source accounting, and the
    content-derived distribution identity all read the loaded releases -- so
    bounding the load bounds the distribution, including the scope segment its
    identity carries.

    ``parquet_view`` emits the typed Parquet view beside the distribution,
    straight from the in-memory graph, during the single walk that already
    writes the RDF and compact packs. Re-deriving it afterwards would mean
    re-reading everything that walk just wrote.
    """

    output.parent.mkdir(parents=True, exist_ok=True)
    claim_inputs = {} if registry_claim_inputs is None else registry_claim_inputs
    if claim_inputs and output.exists():
        raise ValueError(
            "injected registry claim builds currently require a new output"
        )
    source_keys, mapping_keys = (
        (None, None)
        if include_keys is None
        else split_construction_unit_keys(include_keys)
    )
    _STATUS.phase("load-source-releases")
    releases = load_releases(
        include_keys=source_keys,
        registry_claim_inputs=claim_inputs,
    )
    mapping_releases = load_mapping_releases(include_keys=mapping_keys)
    _STATUS.phase("verify-pinned-inputs")
    inventory = verify_inputs(releases, mapping_releases)
    _STATUS.phase("validate-normalized-rows")
    producer_validation = _validate_compiled_producer_rows(
        releases,
        mapping_releases,
    )
    english_only_scan = producer_validation.english_only_scan
    dropped_label_count = sum(release.dropped_label_count for release in releases)
    label_role_conflict_count = sum(
        _release_label_role_conflict_count(release) for release in releases
    )
    english_family_duplicate_label_count = sum(
        _release_english_family_duplicate_label_count(release)
        for release in releases
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
        "createdAt": _distribution_instant(releases),
        "directSourceCounts": observed_counts,
        "droppedLabelCount": dropped_label_count,
        "englishFamilyDuplicateLabelCount": english_family_duplicate_label_count,
        "labelRoleConflictCount": label_role_conflict_count,
        "retainedEnglishLabelCount": observed_counts["labels"],
        "sourceLabelCountBeforeLanguageFilter": (
            observed_counts["labels"]
            + dropped_label_count
            + english_family_duplicate_label_count
            + label_role_conflict_count
        ),
        "englishOnlyPolicy": {
            "atlasLabelLanguage": "en",
            "multilingualLabelTextInRdf": "prohibited",
            "rawMultilingualSources": "externalByExactLocatorAndDigest",
        },
        "englishOnlyScan": english_only_scan,
        "inputInventory": inventory,
        "mappingReleases": [
            {
                **_mapping_release_summary(release),
                "metadata": _plain(release.metadata),
            }
            for release in mapping_releases
        ],
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
        "version": "3.1-development",
    }
    pack_releases = _release_pack_plans(releases, mapping_releases)
    construction_seeds = _release_construction_seeds(releases, mapping_releases)
    # Fail on nulls or non-interoperable numbers before constructing the large graph.
    ATLAS_VALIDATE.canonical_json_bytes(generation_report)
    _STATUS.phase("construct-graphs")
    graphs = _build_graphs(
        releases,
        mapping_releases=mapping_releases,
        include_projection=False,
    )
    _STATUS.phase("validate-constructed-graphs")
    compiled_validation = _validate_compiled_producer_output(
        releases,
        graphs,
        producer_validation,
        mapping_releases,
    )
    del releases
    del mapping_releases
    _STATUS.phase("write-distribution")
    result = _write_distribution(
        output,
        graphs,
        releases=pack_releases,
        construction_seeds=construction_seeds,
        generation_report=generation_report,
        compiled_validation=compiled_validation,
        parquet_view=_parquet_view_path(output) if parquet_view else None,
    )
    print(json.dumps(result, indent=2, sort_keys=True))


def main() -> int:
    global _STATUS

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--check-inputs",
        action="store_true",
        help="verify and report all direct inputs without writing a distribution",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="suppress human-facing status lines on stderr",
    )
    parser.add_argument(
        "--registry-claim-input",
        action="append",
        nargs=3,
        metavar=("RELEASE_KEY", "BUNDLE_PATH", "MANIFEST_SHA256"),
        help=(
            "inject one verified registry claim bundle; repeat for additional "
            "release keys"
        ),
    )
    parser.add_argument(
        "--only-release",
        action="append",
        metavar="RELEASE_KEY",
        help=(
            "bound the build to this construction unit; repeat for additional "
            "keys"
        ),
    )
    parser.add_argument(
        "--no-parquet-view",
        action="store_true",
        help=(
            "skip the typed Parquet view emitted beside the distribution "
            "during the build's single graph walk"
        ),
    )
    args = parser.parse_args()
    registry_claim_inputs: dict[str, AtlasRegistryClaimInput] = {}
    for key, path, digest in args.registry_claim_input or ():
        if key in registry_claim_inputs:
            parser.error(f"registry claim input repeats release key {key!r}")
        registry_claim_inputs[key] = AtlasRegistryClaimInput(
            path=Path(path).resolve(),
            expected_manifest_digest=digest,
        )
    include_keys: frozenset[str] | None = None
    if args.only_release is not None:
        include_keys = frozenset(args.only_release)
        try:
            source_keys, mapping_keys = split_construction_unit_keys(include_keys)
        except ValueError as error:
            parser.error(str(error))
    _STATUS = _StatusReporter(enabled=not args.quiet)
    operation = "check-inputs" if args.check_inputs else "build-distribution"
    _STATUS.phase(operation)
    try:
        if args.check_inputs:
            releases = load_releases(
                include_keys=None if include_keys is None else source_keys,
                registry_claim_inputs=registry_claim_inputs,
            )
            mapping_releases = load_mapping_releases(
                include_keys=None if include_keys is None else mapping_keys
            )
            _STATUS.phase("verify-pinned-inputs")
            print(
                json.dumps(
                    verify_inputs(releases, mapping_releases),
                    indent=2,
                    sort_keys=True,
                )
            )
            _STATUS.phase("complete")
            return 0
        build_distribution(
            args.output.resolve(),
            registry_claim_inputs=registry_claim_inputs,
            include_keys=include_keys,
            parquet_view=not args.no_parquet_view,
        )
    except BaseException as error:
        _STATUS.phase("failed", current=type(error).__name__)
        raise
    _STATUS.phase("complete")
    print(args.output.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
