"""Deterministic, lossless vocabulary-atlas distributions.

The canonical Atlas 2.0 publisher accepts one exact
``PinnedVocabularyAtlasScope``.  It preserves source and RefSpec concept
identity, release-scoped records, typed evidence, and ring-specific mapping
assertions as canonical JSON records.  RDF supplies only the exact record
index and containment needed to read those records; labels never mint identity
or relations.
"""

from __future__ import annotations

import hashlib
import importlib.metadata
import itertools
import json
import platform
import re
import unicodedata
from collections import defaultdict
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from types import MappingProxyType
from typing import Any, Literal, Protocol, cast

from rdflib import BNode, Dataset, Graph, Namespace, URIRef
from rdflib import Literal as RdfLiteral
from rdflib.compare import to_canonical_graph
from rdflib.namespace import DCAT, DCTERMS, PROV, RDF, RDFS, SKOS, XSD
from typing_extensions import Self

from refspec import binding
from refspec.managed_release import (
    ManagedReleaseExpression,
    ManagedReleaseMember,
    ManagedReleaseRelation,
    ManagedReleaseView,
)
from refspec.release_graph import rulespec_graph_digest
from refspec.storage import canonical_json

FORMAT_ID = "refspec-vocabulary-atlas-nquads-2.0"
SCHEMA_VERSION = "2.0"
ATLAS_FILE = "atlas.nq"
MANIFEST_FILE = "atlas-manifest.json"
SCOPE_FILE = "atlas-scope.json"
CROSSWALK_MEDIA_TYPE = "application/vnd.refspec.vocabulary-atlas-crosswalk+json"

ATLAS = Namespace("https://refspec.org/ns/vocabulary-atlas/v2#")
RKAF = Namespace("https://rulespec.org/ns/v1#")

_SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")
_ABSOLUTE_IRI = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:[^\s<>]+$")
_DECIMAL = re.compile(r"^(?:0|1|2)(?:\.[0-9]+)?$")
_MAPPING_RELATIONS = frozenset(
    {
        "http://www.w3.org/2004/02/skos/core#exactMatch",
        "http://www.w3.org/2004/02/skos/core#closeMatch",
        "http://www.w3.org/2004/02/skos/core#broadMatch",
        "http://www.w3.org/2004/02/skos/core#narrowMatch",
        "http://www.w3.org/2004/02/skos/core#relatedMatch",
    }
)

#: Protocol v2 verdict strings a sealed validation may carry, with the outcome
#: each one derives.  Mirrors ``qualification.VERDICTS_V2`` without importing
#: it: the format is the authority on what a sealed record admits.
_V2_VERDICT_OUTCOMES: Mapping[str, str] = MappingProxyType(
    {
        "same": "supports",
        "near_same": "supports",
        "target_is_broader": "supports",
        "target_is_narrower": "supports",
        "related": "supports",
        "unrelated": "rejects",
        "insufficient_evidence": "abstains",
    }
)
_V2_VERDICTS = frozenset(_V2_VERDICT_OUTCOMES)
_CROSSWALK_SCHEMA_V2 = "2.0"
#: Adjudicated-``related`` is a relation like any other — it is recorded on the
#: candidate as ``skos:relatedMatch`` — but it is the one agreed relation that
#: emits no ``ConceptMapping``.  Promoting associative links to consumable
#: mappings is a separate decision for a consumer that actually wants them.
_RELATED_MATCH = "http://www.w3.org/2004/02/skos/core#relatedMatch"
#: v1 validations carry no verdict relation at all; their agreement is the v1
#: yes/no and emission uses the candidate's proposed relation exactly as before.
_PROPOSED_TAG = "proposed"


def _agreed_relation_for(verdicts: frozenset[str]) -> str | None:
    """The v2 agreement lattice, folded over *every* supporting verdict.

    The rule is universal, not existential: every supporting validation on one
    question must be relation-compatible with every other, and the mapping is
    emitted at the weakest claim any of them made.  ``same``+``near_same`` agree
    that substitution is symmetric and disagree only about identity, so that set
    qualifies at ``closeMatch``.  Every other mixture is a real disagreement
    about the claim itself — emitting either relation would overrule a machine
    on the precise thing that relation asserts — and yields nothing.
    """

    if not verdicts:
        return None
    if verdicts == {"same"}:
        return "http://www.w3.org/2004/02/skos/core#exactMatch"
    if verdicts <= {"same", "near_same"}:
        return "http://www.w3.org/2004/02/skos/core#closeMatch"
    if verdicts == {"target_is_broader"}:
        return "http://www.w3.org/2004/02/skos/core#broadMatch"
    if verdicts == {"target_is_narrower"}:
        return "http://www.w3.org/2004/02/skos/core#narrowMatch"
    if verdicts == {"related"}:
        return _RELATED_MATCH
    return None


_ARTIFACT_ROLES = frozenset({"evidence", "inputContext", "validationRequest", "validationResponse"})
_CORE_RELEASE_STATUSES = frozenset({"fixture", "candidate", "published"})
_CORE_ARTIFACT_MANIFESTS = (
    "conformance_fixture_artifacts",
    "schema_artifacts",
    "validator_artifacts",
)
_CORE_ARTIFACT_FIELDS = frozenset({"artifact_digest", "media_type", "name"})
_CORE_RELEASE_FIELDS = frozenset(
    {
        "record_type",
        "release_digest",
        "release_id",
        "release_status",
        "version",
        *_CORE_ARTIFACT_MANIFESTS,
    }
)
_FEEDBACK_DISPOSITIONS = frozenset({"supports", "challenges", "comment"})
_POLICIES = MappingProxyType(
    {
        "graphPartition": "releaseFactsAndCrossReleaseRecords",
        "recordEncoding": "canonicalRefJsonV1",
        "recordIndexing": "derivedExactEqualityV1",
        "labelEquality": "discoveryOnly",
        "permission": "externalProductPolicyOnly",
    }
)
# This is the import-closed Atlas 2.0 build path: scope resolution, exact
# release snapshots, relation records, and the codecs that determine output
# bytes. It deliberately excludes source-specific producers, queries,
# projections, product policy, publication UI, and package facades.
_IMPLEMENTATION_SOURCE_PATHS = (
    "atlas/atlas_scope.py",
    "atlas/concept_release.py",
    "atlas/model.py",
    "atlas/relation_assertion.py",
    "atlas/relation_proof.py",
    "atlas/release_snapshot.py",
    "atlas_index.py",
    "binding.py",
    "generated_rulespec_dependency.py",
    "immutable.py",
    "managed_release.py",
    "registry/infrastructure/artifact_serialization.py",
    "registry/infrastructure/identifier_validation.py",
    "registry/infrastructure/semantic_foundation.py",
    "registry/infrastructure/source_concept_release.py",
    "registry/infrastructure/source_controlled_resource.py",
    "registry/infrastructure/source_identity.py",
    "release_graph.py",
    "storage.py",
    "vocabulary.py",
)


class VocabularyAtlasError(ValueError):
    """The atlas or one of its exact inputs is invalid."""


class AtlasReleaseFactsView(Protocol):
    """Small verified view needed to project one release into an atlas."""

    @property
    def release_id(self) -> str: ...

    @property
    def rulespec_graph_id(self) -> str: ...

    @property
    def rulespec_graph(self) -> Mapping[str, Any]: ...

    def iter_members(self) -> Iterable[ManagedReleaseMember]: ...

    def lookup_member(self, member_iri: str) -> ManagedReleaseMember | None: ...

    def iter_expressions(self) -> Iterable[ManagedReleaseExpression]: ...

    def iter_relations(self) -> Iterable[ManagedReleaseRelation]: ...


class VerifiedManagedReleaseSource(Protocol):
    """Producer-neutral source of exact release facts and its publication pin."""

    def verified_view(self) -> AtlasReleaseFactsView: ...

    def pin(self) -> dict[str, Any]: ...


@dataclass(frozen=True, slots=True)
class _ResolvedManagedRelease:
    """One verified view bound to the exact pin checked for this build."""

    view: AtlasReleaseFactsView
    pin: Mapping[str, Any]


def _plain(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _plain(child) for key, child in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return [_plain(child) for child in value]
    return value


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({str(key): _freeze(child) for key, child in value.items()})
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return tuple(_freeze(child) for child in value)
    return value


def _canonical_bytes(value: object) -> bytes:
    try:
        binding.validate_canonical_value(value)
    except (TypeError, ValueError) as error:
        raise VocabularyAtlasError(str(error)) from error
    return (canonical_json(value) + "\n").encode("utf-8")


def _digest_bytes(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def _digest_value(value: object) -> str:
    return _digest_bytes(_canonical_bytes(value).removesuffix(b"\n"))


def _require_digest(value: object, label: str) -> str:
    result = str(value or "")
    if _SHA256.fullmatch(result) is None:
        raise VocabularyAtlasError(f"{label} must be sha256:<64 lowercase hex>")
    return result


def _require_iri(value: object, label: str) -> str:
    result = str(value or "")
    if _ABSOLUTE_IRI.fullmatch(result) is None:
        raise VocabularyAtlasError(f"{label} must be an absolute IRI")
    return result


def _require_text(value: object, label: str) -> str:
    result = str(value).strip() if isinstance(value, str) else ""
    if not result:
        raise VocabularyAtlasError(f"{label} is required")
    return result


def _reference(value: object, label: str) -> dict[str, str]:
    if not isinstance(value, Mapping) or set(value) != {"id", "digest"}:
        raise VocabularyAtlasError(f"{label} must contain exactly id and digest")
    return {
        "id": _require_iri(value.get("id"), f"{label} id"),
        "digest": _require_digest(value.get("digest"), f"{label} digest"),
    }


def _seal_record(
    *,
    record_type: str,
    id_prefix: str,
    payload: Mapping[str, Any],
) -> dict[str, Any]:
    if set(payload) & {"id", "type", "canonicalPayloadDigest"}:
        raise VocabularyAtlasError("sealed payload contains reserved fields")
    basis = {"type": record_type, **_plain(payload)}
    identity_digest = binding.canonical_payload_digest(basis)
    record = {
        "id": id_prefix + identity_digest.removeprefix("sha256:"),
        **basis,
    }
    record["canonicalPayloadDigest"] = binding.canonical_payload_digest(record)
    return record


def _verify_sealed_record(
    record: Mapping[str, Any],
    *,
    record_type: str,
    id_prefix: str,
) -> None:
    plain = _plain(record)
    if plain.get("type") != record_type:
        raise VocabularyAtlasError(f"record type must be {record_type}")
    actual = plain.get("canonicalPayloadDigest")
    expected = binding.canonical_payload_digest(plain)
    if actual != expected:
        raise VocabularyAtlasError("record canonicalPayloadDigest differs")
    basis = {key: value for key, value in plain.items() if key not in {"id", "canonicalPayloadDigest"}}
    identity_digest = binding.canonical_payload_digest(basis)
    if plain.get("id") != id_prefix + identity_digest.removeprefix("sha256:"):
        raise VocabularyAtlasError("record content-derived id differs")


def _load_json_object(raw: bytes, label: str) -> dict[str, Any]:
    try:
        value = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=binding.reject_duplicate_keys,
            parse_constant=binding.reject_nonfinite_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
        raise VocabularyAtlasError(f"{label} is not strict UTF-8 JSON") from error
    if not isinstance(value, dict):
        raise VocabularyAtlasError(f"{label} root must be a JSON object")
    try:
        binding.validate_canonical_value(value)
    except (TypeError, ValueError) as error:
        raise VocabularyAtlasError(str(error)) from error
    return value


def _read_exact_file(path: Path | str, label: str) -> tuple[Path, bytes]:
    selected = Path(path)
    if selected.is_symlink():
        raise VocabularyAtlasError(f"{label} must not be a symlink")
    try:
        selected = selected.resolve(strict=True)
    except FileNotFoundError as error:
        raise VocabularyAtlasError(f"{label} does not exist") from error
    if not selected.is_file():
        raise VocabularyAtlasError(f"{label} must be a regular file")
    return selected, selected.read_bytes()


def _normalize_label(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    return " ".join(normalized.split())


#: ``dcat:version`` is absent from rdflib's closed DCAT namespace, so it is
#: spelled out rather than fetched as an attribute that warns.
_DCAT_VERSION = URIRef("http://www.w3.org/ns/dcat#version")
_CLOSED_RELEASE_PREDICATES = frozenset(
    {
        RDF.type,
        DCTERMS.isVersionOf,
        _DCAT_VERSION,
        DCTERMS.type,
        RKAF.membershipMode,
        PROV.hadMember,
        DCAT.distribution,
        RKAF.versionBasis,
        DCTERMS.issued,
        RKAF.hasEffectivePeriod,
    }
)
_CLOSED_DISTRIBUTION_PREDICATES = frozenset(
    {
        RKAF.hasArtifactIdentifier,
        DCTERMS.format,
        RKAF.hasContentDigest,
    }
)


def _rdfc_term(term: Any) -> Any:
    """Use the RDFC-1.0 spelling for an explicit ``xsd:string`` literal."""

    if isinstance(term, RdfLiteral) and term.datatype == XSD.string:
        return RdfLiteral(str(term))
    return term


def closed_reference_release_digest(
    graph_value: Mapping[str, Any],
    *,
    release_iri: str,
    label: str,
) -> str:
    """Compute the Rulespec Core closed-manifest digest without a source checkout.

    The closed ``ReferenceResourceRelease`` preimage contains named nodes only.
    With no blank nodes to relabel, RDFC-1.0 is the lexicographically sorted
    canonical N-Quads serialization.  RefSpec owns this small implementation,
    pins its source and rdflib runtime in the atlas manifest, and fails closed
    if a future Core shape introduces a blank node.

    Every specialized producer that packages a vocabulary Rulespec never sealed
    calls exactly this function, so two adapters cannot drift into two
    different answers for the same closed shape.
    """

    release = URIRef(_require_iri(release_iri, f"{label} reference release IRI"))
    parsed = Graph()
    try:
        parsed.parse(data=canonical_json(_plain(graph_value)), format="json-ld")
    except Exception as error:  # rdflib exposes parser-specific exception types
        raise VocabularyAtlasError(f"{label} release graph is not valid JSON-LD") from error
    if (release, RDF.type, RKAF.ReferenceResourceRelease) not in parsed:
        raise VocabularyAtlasError(f"{label} release is not a ReferenceResourceRelease")

    triples: list[tuple[URIRef, URIRef, Any]] = []
    for predicate in _CLOSED_RELEASE_PREDICATES:
        triples.extend((release, predicate, _rdfc_term(value)) for value in parsed.objects(release, predicate))
    distributions = tuple(parsed.objects(release, DCAT.distribution))
    if not distributions:
        raise VocabularyAtlasError(f"{label} release has no distribution")
    for distribution in distributions:
        if not isinstance(distribution, URIRef):
            raise VocabularyAtlasError(f"{label} release distribution must be an IRI")
        for predicate in _CLOSED_DISTRIBUTION_PREDICATES:
            values = tuple(parsed.objects(distribution, predicate))
            if not values:
                raise VocabularyAtlasError(f"{label} distribution lacks digest input {predicate}")
            triples.extend((distribution, predicate, _rdfc_term(value)) for value in values)

    if any(isinstance(term, BNode) for triple in triples for term in triple):
        raise VocabularyAtlasError(f"{label} release digest preimage must not contain blank nodes")
    lines = sorted(f"{subject.n3()} {predicate.n3()} {object_.n3()} ." for subject, predicate, object_ in triples)
    preimage = ("\n".join(lines) + "\n").encode("utf-8")
    return "sha256:" + hashlib.sha256(preimage).hexdigest()


def _implementation_pin() -> dict[str, Any]:
    package_root = Path(__file__).parents[1]
    sources = [
        {
            "path": f"refspec/{relative}",
            "digest": _digest_bytes((package_root / relative).read_bytes()),
        }
        for relative in _IMPLEMENTATION_SOURCE_PATHS
    ]
    return {
        "id": "urn:ref:implementation:vocabulary-atlas:1.0",
        "version": "1.0",
        "sourceModules": sources,
        "runtime": {
            "jsonschemaVersion": importlib.metadata.version("jsonschema"),
            "pyarrowVersion": importlib.metadata.version("pyarrow"),
            "pythonRequirement": ">=3.10",
            "pythonVersion": platform.python_version(),
            "rdflibVersion": importlib.metadata.version("rdflib"),
        },
    }


@dataclass(frozen=True, slots=True)
class PinnedManagedRelease:
    """One exact managed-bundle manifest and its verified read view."""

    manifest_path: Path
    manifest_digest: str
    view: ManagedReleaseView

    @classmethod
    def open(
        cls,
        manifest_path: Path | str,
        *,
        expected_manifest_digest: str,
    ) -> Self:
        digest = _require_digest(expected_manifest_digest, "managed release manifest digest")
        view = ManagedReleaseView.open(
            manifest_path,
            expected_manifest_digest=digest,
        )
        return cls(Path(manifest_path).resolve(strict=True), digest, view)

    def verified_view(self) -> ManagedReleaseView:
        """Reopen the manifest so later file changes fail closed."""

        return ManagedReleaseView.open(
            self.manifest_path,
            expected_manifest_digest=self.manifest_digest,
        )

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


def _require_core_release_contract(record: Mapping[str, Any]) -> None:
    """Reject a pinned file that is not a complete Rulespec Core release.

    Matching digests prove only that the bytes are the pinned bytes.  This
    check proves the bytes are a Core release: without it a file containing
    just ``{"record_type": "RulespecCoreRelease"}`` pins cleanly and publishes
    an atlas that claims Rulespec Core conformance it cannot support.

    RefSpec reimplements the required-field contract published in Rulespec's
    ``release-records/schemas/rulespec-core-release.schema.json`` rather than
    importing Rulespec, so the atlas keeps its file-only dependency.
    """

    missing = sorted(_CORE_RELEASE_FIELDS - set(record))
    if missing:
        raise VocabularyAtlasError(f"Rulespec Core release omits required fields {missing!r}")
    unsupported = sorted(set(record) - _CORE_RELEASE_FIELDS)
    if unsupported:
        raise VocabularyAtlasError(f"Rulespec Core release contains unsupported fields {unsupported!r}")
    if record["release_status"] not in _CORE_RELEASE_STATUSES:
        raise VocabularyAtlasError("Rulespec Core release_status must be fixture, candidate, or published")
    _require_text(record["version"], "Rulespec Core version")
    for field in _CORE_ARTIFACT_MANIFESTS:
        entries = record[field]
        if not isinstance(entries, list) or not entries:
            raise VocabularyAtlasError(f"Rulespec Core {field} must list at least one artifact")
        for index, entry in enumerate(entries):
            label = f"Rulespec Core {field}[{index}]"
            if not isinstance(entry, Mapping) or set(entry) != _CORE_ARTIFACT_FIELDS:
                raise VocabularyAtlasError(f"{label} must contain exactly name, media_type, and artifact_digest")
            _require_text(entry["name"], f"{label} name")
            _require_text(entry["media_type"], f"{label} media_type")
            _require_digest(entry["artifact_digest"], f"{label} artifact_digest")


@dataclass(frozen=True, slots=True)
class PinnedRulespecCoreRelease:
    """Exact external Rulespec Core release bytes used by the atlas."""

    path: Path
    file_digest: str
    release_id: str
    release_digest: str

    @classmethod
    def open(
        cls,
        path: Path | str,
        *,
        expected_file_digest: str,
        expected_release_id: str,
        expected_release_digest: str,
    ) -> Self:
        expected_file_digest = _require_digest(expected_file_digest, "Rulespec Core file digest")
        expected_release_id = _require_iri(expected_release_id, "Rulespec Core release id")
        expected_release_digest = _require_digest(expected_release_digest, "Rulespec Core release digest")
        resolved, raw = _read_exact_file(path, "Rulespec Core release")
        if _digest_bytes(raw) != expected_file_digest:
            raise VocabularyAtlasError("Rulespec Core file digest differs")
        record = _load_json_object(raw, "Rulespec Core release")
        if record.get("record_type") != "RulespecCoreRelease":
            raise VocabularyAtlasError("Rulespec Core record_type differs")
        _require_core_release_contract(record)
        if record.get("release_id") != expected_release_id:
            raise VocabularyAtlasError("Rulespec Core release id differs")
        if record.get("release_digest") != expected_release_digest:
            raise VocabularyAtlasError("Rulespec Core release digest differs")
        preimage = {key: value for key, value in record.items() if key not in {"release_id", "release_digest"}}
        if _digest_value(preimage) != expected_release_digest:
            raise VocabularyAtlasError("Rulespec Core content-derived release digest differs")
        expected_id = "urn:rulespec:core:" + expected_release_digest.removeprefix("sha256:")
        if expected_release_id != expected_id:
            raise VocabularyAtlasError("Rulespec Core content-derived id differs")
        return cls(
            path=resolved,
            file_digest=expected_file_digest,
            release_id=expected_release_id,
            release_digest=expected_release_digest,
        )

    def verify(self) -> None:
        self.open(
            self.path,
            expected_file_digest=self.file_digest,
            expected_release_id=self.release_id,
            expected_release_digest=self.release_digest,
        )

    def pin(self) -> dict[str, str]:
        self.verify()
        return {
            "role": "RulespecCoreRelease",
            "fileDigest": self.file_digest,
            "releaseId": self.release_id,
            "releaseDigest": self.release_digest,
        }


@dataclass(frozen=True, slots=True)
class CrosswalkArtifact:
    """A sealed evidence, request, or response artifact in a crosswalk bundle."""

    _record: Mapping[str, Any]

    @classmethod
    def create(
        cls,
        *,
        role: Literal[
            "evidence",
            "inputContext",
            "validationRequest",
            "validationResponse",
        ],
        media_type: str,
        content: Mapping[str, Any],
    ) -> Self:
        if role not in _ARTIFACT_ROLES:
            raise VocabularyAtlasError("crosswalk artifact role is unsupported")
        payload = {
            "role": role,
            "mediaType": _require_text(media_type, "artifact media type"),
            "content": _plain(content),
        }
        return cls(
            cast(
                Mapping[str, Any],
                _freeze(
                    _seal_record(
                        record_type="urn:ref:type:VocabularyAtlasCrosswalkArtifact",
                        id_prefix="urn:ref:vocabulary-atlas-artifact:",
                        payload=payload,
                    )
                ),
            )
        )

    @property
    def identifier(self) -> str:
        return str(self._record["id"])

    @property
    def digest(self) -> str:
        return str(self._record["canonicalPayloadDigest"])

    @property
    def role(self) -> str:
        return str(self._record["role"])

    @property
    def content_digest(self) -> str:
        """Digest the sealed content alone, which is what a candidate cites.

        ``canonicalPayloadDigest`` also covers the role and media type, so it
        cannot be what ``inputContextDigest`` names.
        """

        return _artifact_content_digest(self._record)

    def reference(self) -> dict[str, str]:
        return {"id": self.identifier, "digest": self.digest}

    def to_dict(self) -> dict[str, Any]:
        return cast(dict[str, Any], _plain(self._record))


def _artifact_content_digest(record: Mapping[str, Any]) -> str:
    return binding.canonical_sha256(_plain(record["content"]))


@dataclass(frozen=True, slots=True)
class MappingCandidate:
    """One model- or agent-generated cross-release mapping proposal."""

    _record: Mapping[str, Any]

    @classmethod
    def create(
        cls,
        *,
        source_member: str,
        source_release: str,
        target_member: str,
        target_release: str,
        proposed_relation: str,
        generator_kind: Literal["aiModel", "aiAgent"],
        generator_actor: str,
        generator_provider: str,
        model_id: str,
        model_version: str,
        prompt_template: str,
        input_context_digest: str,
        temperature: str,
        evidence: Sequence[Mapping[str, str]],
        generated_at: str,
        seed: int | None = None,
    ) -> Self:
        source_member = _require_iri(source_member, "candidate source member")
        source_release = _require_iri(source_release, "candidate source release")
        target_member = _require_iri(target_member, "candidate target member")
        target_release = _require_iri(target_release, "candidate target release")
        proposed_relation = _require_iri(proposed_relation, "candidate proposed relation")
        if source_release == target_release:
            raise VocabularyAtlasError("a crosswalk candidate must cross releases")
        if source_member == target_member:
            raise VocabularyAtlasError("a crosswalk candidate needs distinct members")
        if proposed_relation not in _MAPPING_RELATIONS:
            raise VocabularyAtlasError("candidate mapping relation is unsupported")
        if generator_kind not in {"aiModel", "aiAgent"}:
            raise VocabularyAtlasError("candidate generator kind is unsupported")
        if not isinstance(temperature, str) or _DECIMAL.fullmatch(temperature) is None:
            raise VocabularyAtlasError("candidate temperature must be a canonical decimal string")
        try:
            parsed_temperature = Decimal(temperature)
        except InvalidOperation as error:
            raise VocabularyAtlasError("candidate temperature is invalid") from error
        if parsed_temperature < 0 or parsed_temperature > 2:
            raise VocabularyAtlasError("candidate temperature must be between 0 and 2")
        if seed is not None and (isinstance(seed, bool) or not isinstance(seed, int)):
            raise VocabularyAtlasError("candidate seed must be an integer")
        evidence_refs = [_reference(item, "candidate evidence") for item in evidence]
        if not evidence_refs:
            raise VocabularyAtlasError("candidate evidence must not be empty")
        payload: dict[str, Any] = {
            "sourceMember": source_member,
            "sourceRelease": source_release,
            "targetMember": target_member,
            "targetRelease": target_release,
            "proposedRelation": proposed_relation,
            "generatorKind": generator_kind,
            "generatorActor": _require_iri(generator_actor, "candidate generator actor"),
            "generatorProvider": _require_iri(generator_provider, "candidate generator provider"),
            "modelId": _require_text(model_id, "candidate model id"),
            "modelVersion": _require_text(model_version, "candidate model version"),
            "promptTemplate": _require_iri(prompt_template, "candidate prompt template"),
            "inputContextDigest": _require_digest(input_context_digest, "candidate input context digest"),
            "temperature": temperature,
            "evidence": evidence_refs,
            "generatedAt": _require_text(generated_at, "candidate generated timestamp"),
        }
        if seed is not None:
            payload["seed"] = seed
        return cls(
            cast(
                Mapping[str, Any],
                _freeze(
                    _seal_record(
                        record_type="urn:ref:type:VocabularyAtlasMappingCandidate",
                        id_prefix="urn:ref:vocabulary-atlas-mapping-candidate:",
                        payload=payload,
                    )
                ),
            )
        )

    @property
    def identifier(self) -> str:
        return str(self._record["id"])

    @property
    def digest(self) -> str:
        return str(self._record["canonicalPayloadDigest"])

    def reference(self) -> dict[str, str]:
        return {"id": self.identifier, "digest": self.digest}

    def to_dict(self) -> dict[str, Any]:
        return cast(dict[str, Any], _plain(self._record))


@dataclass(frozen=True, slots=True)
class MachineValidation:
    """A sealed machine result; qualification still requires an independent pair."""

    _record: Mapping[str, Any]

    @classmethod
    def create(
        cls,
        *,
        candidate: Mapping[str, str],
        validator_kind: Literal["aiModel", "aiAgent"],
        validator_actor: str,
        independence_group: str,
        provider: str,
        provider_model_id: str,
        sealed_input_digest: str,
        request_artifact: Mapping[str, str],
        response_artifact: Mapping[str, str],
        deterministic_checks_passed: bool,
        outcome: Literal["supports", "rejects", "abstains"],
        completed_at: str,
        verdict_relation: str | None = None,
    ) -> Self:
        if validator_kind not in {"aiModel", "aiAgent"}:
            raise VocabularyAtlasError("validator kind is unsupported")
        if outcome not in {"supports", "rejects", "abstains"}:
            raise VocabularyAtlasError("machine validation outcome is unsupported")
        if not isinstance(deterministic_checks_passed, bool):
            raise VocabularyAtlasError("deterministicChecksPassed must be boolean")
        if verdict_relation is not None:
            if verdict_relation not in _V2_VERDICTS:
                raise VocabularyAtlasError("machine validation verdictRelation is unsupported")
            if _V2_VERDICT_OUTCOMES[verdict_relation] != outcome:
                raise VocabularyAtlasError("machine validation outcome disagrees with its verdictRelation")
        payload = {
            "candidate": _reference(candidate, "machine candidate"),
            "validatorKind": validator_kind,
            "validatorActor": _require_iri(validator_actor, "machine validator actor"),
            "independenceGroup": _require_iri(independence_group, "machine independence group"),
            "provider": _require_iri(provider, "machine provider"),
            "providerModelId": _require_text(provider_model_id, "machine provider model id"),
            "sealedInputDigest": _require_digest(sealed_input_digest, "machine sealed input digest"),
            "requestArtifact": _reference(request_artifact, "machine request artifact"),
            "responseArtifact": _reference(response_artifact, "machine response artifact"),
            "deterministicChecksPassed": deterministic_checks_passed,
            "outcome": outcome,
            "completedAt": _require_text(completed_at, "machine completed timestamp"),
        }
        if verdict_relation is not None:
            payload["verdictRelation"] = verdict_relation
        return cls(
            cast(
                Mapping[str, Any],
                _freeze(
                    _seal_record(
                        record_type="urn:ref:type:VocabularyAtlasMachineValidation",
                        id_prefix="urn:ref:vocabulary-atlas-machine-validation:",
                        payload=payload,
                    )
                ),
            )
        )

    @property
    def identifier(self) -> str:
        return str(self._record["id"])

    @property
    def digest(self) -> str:
        return str(self._record["canonicalPayloadDigest"])

    def reference(self) -> dict[str, str]:
        return {"id": self.identifier, "digest": self.digest}

    def to_dict(self) -> dict[str, Any]:
        return cast(dict[str, Any], _plain(self._record))


@dataclass(frozen=True, slots=True)
class MappingFeedback:
    """Optional human feedback that never changes current eligibility."""

    _record: Mapping[str, Any]

    @classmethod
    def create(
        cls,
        *,
        candidate: Mapping[str, str],
        actor: str,
        disposition: Literal["supports", "challenges", "comment"],
        comment: str,
        recorded_at: str,
    ) -> Self:
        if disposition not in _FEEDBACK_DISPOSITIONS:
            raise VocabularyAtlasError("mapping feedback disposition is unsupported")
        payload = {
            "candidate": _reference(candidate, "feedback candidate"),
            "actor": _require_iri(actor, "feedback actor"),
            "disposition": disposition,
            "comment": _require_text(comment, "feedback comment"),
            "recordedAt": _require_text(recorded_at, "feedback timestamp"),
        }
        return cls(
            cast(
                Mapping[str, Any],
                _freeze(
                    _seal_record(
                        record_type="urn:ref:type:VocabularyAtlasMappingFeedback",
                        id_prefix="urn:ref:vocabulary-atlas-mapping-feedback:",
                        payload=payload,
                    )
                ),
            )
        )

    @property
    def identifier(self) -> str:
        return str(self._record["id"])

    @property
    def digest(self) -> str:
        return str(self._record["canonicalPayloadDigest"])

    def to_dict(self) -> dict[str, Any]:
        return cast(dict[str, Any], _plain(self._record))


@dataclass(frozen=True, slots=True)
class CrosswalkBundle:
    """Closed crosswalk input with machine validation and optional feedback."""

    _record: Mapping[str, Any]

    @classmethod
    def open(
        cls,
        path: Path | str,
        *,
        expected_file_digest: str,
        expected_bundle_digest: str,
    ) -> Self:
        """Open one exact canonical crosswalk bundle file and close every reference."""

        expected_file_digest = _require_digest(expected_file_digest, "crosswalk file digest")
        expected_bundle_digest = _require_digest(expected_bundle_digest, "crosswalk bundle digest")
        _, raw = _read_exact_file(path, "crosswalk bundle")
        if _digest_bytes(raw) != expected_file_digest:
            raise VocabularyAtlasError("crosswalk file digest differs")
        record = _load_json_object(raw, "crosswalk bundle")
        if _canonical_bytes(record) != raw:
            raise VocabularyAtlasError("crosswalk bundle bytes are not canonical")
        bundle = cls(cast(Mapping[str, Any], _freeze(record)))
        bundle.verify()
        if bundle.digest != expected_bundle_digest:
            raise VocabularyAtlasError("crosswalk bundle digest differs")
        return bundle

    @classmethod
    def create(
        cls,
        *,
        artifacts: Sequence[CrosswalkArtifact],
        mapping_candidates: Sequence[MappingCandidate],
        machine_validations: Sequence[MachineValidation] = (),
        feedback: Sequence[MappingFeedback] = (),
    ) -> Self:
        artifact_records = _unique_records(artifacts, "crosswalk artifact")
        candidate_records = _unique_records(mapping_candidates, "mapping candidate")
        validation_records = _unique_records(machine_validations, "machine validation")
        feedback_records = _unique_records(feedback, "mapping feedback")
        _validate_crosswalk_closure(
            artifacts=artifact_records,
            candidates=candidate_records,
            validations=validation_records,
            feedback=feedback_records,
        )
        # A bundle is protocol-homogeneous: every validation carries a
        # verdictRelation (v2) or none does (v1).  A mix would make the
        # agreement rule ambiguous for the exact candidates it matters for.
        with_relation = sum(1 for value in validation_records.values() if "verdictRelation" in value)
        if with_relation not in (0, len(validation_records)):
            raise VocabularyAtlasError("crosswalk bundle mixes v1 and v2 machine validations")
        schema_version = _CROSSWALK_SCHEMA_V2 if with_relation and validation_records else SCHEMA_VERSION
        record = _seal_record(
            record_type="urn:ref:type:VocabularyAtlasCrosswalkBundle",
            id_prefix="urn:ref:vocabulary-atlas-crosswalk-bundle:",
            payload={
                "schemaVersion": schema_version,
                "artifacts": [artifact_records[key] for key in sorted(artifact_records)],
                "mappingCandidates": [candidate_records[key] for key in sorted(candidate_records)],
                "machineValidations": [validation_records[key] for key in sorted(validation_records)],
                "feedback": [feedback_records[key] for key in sorted(feedback_records)],
            },
        )
        return cls(cast(Mapping[str, Any], _freeze(record)))

    @property
    def identifier(self) -> str:
        return str(self._record["id"])

    @property
    def digest(self) -> str:
        return str(self._record["canonicalPayloadDigest"])

    def pin(self) -> dict[str, str]:
        self.verify()
        return {
            "role": "CrosswalkBundle",
            "id": self.identifier,
            "digest": self.digest,
            "fileDigest": _digest_bytes(self.canonical_bytes()),
            "mediaType": CROSSWALK_MEDIA_TYPE,
        }

    def to_dict(self) -> dict[str, Any]:
        return cast(dict[str, Any], _plain(self._record))

    def canonical_bytes(self) -> bytes:
        self.verify()
        return _canonical_bytes(self.to_dict())

    def write(self, path: Path | str) -> Path:
        """Write one immutable canonical bundle file without overwriting bytes."""

        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            with target.open("xb") as stream:
                stream.write(self.canonical_bytes())
        except FileExistsError as error:
            raise VocabularyAtlasError("crosswalk bundle destination already exists") from error
        return target

    def verify(self) -> None:
        record = self.to_dict()
        expected_fields = {
            "id",
            "type",
            "schemaVersion",
            "artifacts",
            "mappingCandidates",
            "machineValidations",
            "feedback",
            "canonicalPayloadDigest",
        }
        if set(record) != expected_fields:
            raise VocabularyAtlasError("crosswalk bundle fields differ from v1")
        _verify_sealed_record(
            record,
            record_type="urn:ref:type:VocabularyAtlasCrosswalkBundle",
            id_prefix="urn:ref:vocabulary-atlas-crosswalk-bundle:",
        )
        if record["schemaVersion"] not in (SCHEMA_VERSION, _CROSSWALK_SCHEMA_V2):
            raise VocabularyAtlasError("crosswalk bundle schemaVersion differs")
        artifacts = _index_serialized_records(record["artifacts"], "crosswalk artifact")
        candidates = _index_serialized_records(record["mappingCandidates"], "mapping candidate")
        validations = _index_serialized_records(record["machineValidations"], "machine validation")
        expects_relation = record["schemaVersion"] == _CROSSWALK_SCHEMA_V2
        for value in validations.values():
            if ("verdictRelation" in value) != expects_relation:
                raise VocabularyAtlasError("crosswalk bundle validations disagree with its schemaVersion")
        feedback = _index_serialized_records(record["feedback"], "mapping feedback")
        _validate_crosswalk_closure(
            artifacts=artifacts,
            candidates=candidates,
            validations=validations,
            feedback=feedback,
        )

    def with_feedback(self, *items: MappingFeedback) -> Self:
        """Return a new bundle that retains every existing feedback record."""

        self.verify()
        record = self.to_dict()
        existing = {str(item["id"]): item for item in cast(list[dict[str, Any]], record["feedback"])}
        for item in items:
            if item.identifier in existing:
                raise VocabularyAtlasError("mapping feedback is already present")
            existing[item.identifier] = item.to_dict()
        artifacts = [_artifact_from_record(item) for item in record["artifacts"]]
        candidates = [_candidate_from_record(item) for item in record["mappingCandidates"]]
        validations = [_validation_from_record(item) for item in record["machineValidations"]]
        feedback = [_feedback_from_record(item) for item in existing.values()]
        return type(self).create(
            artifacts=artifacts,
            mapping_candidates=candidates,
            machine_validations=validations,
            feedback=feedback,
        )

    def qualified(self) -> dict[str, tuple[dict[str, Any], ...]]:
        """Return every supporting validation in each qualifying question.

        The returned validation set is the complete same-question set whose
        unanimous relation determined qualification, not only the first pair
        that demonstrated machine independence.
        """

        self.verify()
        record = self.to_dict()
        candidates = {item["id"]: item for item in record["mappingCandidates"]}
        validations = {item["id"]: item for item in record["machineValidations"]}
        return _qualified_candidates(candidates, validations)

    def adjudicated_relations(self) -> dict[str, str]:
        """Every candidate's agreed relation IRI, adjudicated-``related`` included.

        Read through the same lattice the atlas builder uses, so a report that
        counts relations can never drift from the gate that emitted them. v1
        candidates are absent: their agreement carries no relation of its own.
        """

        self.verify()
        record = self.to_dict()
        candidates = {item["id"]: item for item in record["mappingCandidates"]}
        validations = {item["id"]: item for item in record["machineValidations"]}
        return {
            candidate_id: relation
            for candidate_id, (_, relation) in _independent_agreements(candidates, validations).items()
            if relation != _PROPOSED_TAG
        }


def _unique_records(values: Sequence[Any], label: str) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for value in values:
        record = value.to_dict()
        identifier = str(record["id"])
        if identifier in result:
            raise VocabularyAtlasError(f"duplicate {label}: {identifier}")
        result[identifier] = record
    return result


def _index_serialized_records(value: object, label: str) -> dict[str, dict[str, Any]]:
    if not isinstance(value, list):
        raise VocabularyAtlasError(f"{label} collection must be a JSON array")
    result: dict[str, dict[str, Any]] = {}
    for item in value:
        if not isinstance(item, dict) or not isinstance(item.get("id"), str):
            raise VocabularyAtlasError(f"{label} must be a JSON object with an id")
        identifier = item["id"]
        if identifier in result:
            raise VocabularyAtlasError(f"duplicate {label}: {identifier}")
        result[identifier] = item
    return result


def _resolve_reference(
    reference: object,
    records: Mapping[str, Mapping[str, Any]],
    label: str,
) -> Mapping[str, Any]:
    exact = _reference(reference, label)
    record = records.get(exact["id"])
    if record is None or record.get("canonicalPayloadDigest") != exact["digest"]:
        raise VocabularyAtlasError(f"{label} does not close against the bundle")
    return record


def _resolve_input_context(
    input_context_digest: object,
    artifacts: Mapping[str, Mapping[str, Any]],
) -> Mapping[str, Any]:
    """Return the one bundled artifact whose bytes produce the cited digest.

    Machine validations agreeing on a digest proves nothing about the model
    input unless those bytes are in the closure a consumer receives, so the
    digest MUST name an ``inputContext`` artifact present in this bundle.
    """

    digest = _require_digest(input_context_digest, "candidate input context digest")
    matches = sorted(
        record["id"]
        for record in artifacts.values()
        if record["role"] == "inputContext" and _artifact_content_digest(record) == digest
    )
    if not matches:
        raise VocabularyAtlasError("candidate input context does not close against the bundle")
    if len(matches) > 1:
        raise VocabularyAtlasError("candidate input context resolves to several artifacts")
    return artifacts[matches[0]]


def _validate_crosswalk_closure(
    *,
    artifacts: Mapping[str, Mapping[str, Any]],
    candidates: Mapping[str, Mapping[str, Any]],
    validations: Mapping[str, Mapping[str, Any]],
    feedback: Mapping[str, Mapping[str, Any]],
) -> None:
    for record in artifacts.values():
        _artifact_from_record(record)
    for record in candidates.values():
        _candidate_from_record(record)
        for evidence in record["evidence"]:
            artifact = _resolve_reference(evidence, artifacts, "candidate evidence")
            if artifact["role"] != "evidence":
                raise VocabularyAtlasError("candidate evidence has the wrong role")
        _resolve_input_context(record["inputContextDigest"], artifacts)
    for record in validations.values():
        _validation_from_record(record)
        candidate = _resolve_reference(record["candidate"], candidates, "machine candidate")
        request = _resolve_reference(record["requestArtifact"], artifacts, "machine request artifact")
        response = _resolve_reference(record["responseArtifact"], artifacts, "machine response artifact")
        if request["role"] != "validationRequest":
            raise VocabularyAtlasError("machine request artifact has the wrong role")
        if response["role"] != "validationResponse":
            raise VocabularyAtlasError("machine response artifact has the wrong role")
        if record["sealedInputDigest"] != candidate["inputContextDigest"]:
            raise VocabularyAtlasError("machine validation uses another sealed input")
        request_content = request["content"]
        if (
            not isinstance(request_content, Mapping)
            or request_content.get("inputDigest") != candidate["inputContextDigest"]
            or request_content.get("candidate") != record["candidate"]
        ):
            raise VocabularyAtlasError("machine request does not seal the candidate and input")
        response_content = response["content"]
        if (
            not isinstance(response_content, Mapping)
            or response_content.get("candidate") != record["candidate"]
            or response_content.get("inputDigest") != candidate["inputContextDigest"]
            or response_content.get("requestArtifact") != record["requestArtifact"]
            or response_content.get("validatorActor") != record["validatorActor"]
            or response_content.get("provider") != record["provider"]
            or response_content.get("providerModelId") != record["providerModelId"]
            or response_content.get("outcome") != record["outcome"]
            or response_content.get("deterministicChecksPassed") is not record["deterministicChecksPassed"]
        ):
            raise VocabularyAtlasError("machine response does not seal its validator result")
    for record in feedback.values():
        _feedback_from_record(record)
        _resolve_reference(record["candidate"], candidates, "feedback candidate")


def _agreement_relation_tag(values: Sequence[Mapping[str, Any]]) -> str | None:
    """The relation every supporting validation on one question agrees on.

    v1 validations carry no ``verdictRelation``; their agreement is the v1
    yes/no, tagged ``proposed`` so emission uses the candidate's proposed
    relation exactly as before.  A mixture of v1 and v2 validations cannot be
    adjudicated at all — the bundle already refuses to seal one, and this is the
    same refusal stated where the rule is applied.
    """

    relations = [value.get("verdictRelation") for value in values]
    if not relations:
        return None
    if all(relation is None for relation in relations):
        return _PROPOSED_TAG
    if any(relation is None for relation in relations):
        return None
    return _agreed_relation_for(frozenset(str(relation) for relation in relations))


def _independent_agreements(
    candidates: Mapping[str, Mapping[str, Any]],
    validations: Mapping[str, Mapping[str, Any]],
) -> dict[str, tuple[tuple[dict[str, Any], ...], str]]:
    """Every candidate whose supporting validations agree on one relation.

    Two gates, in order.  The relation gate is universal — *every* supporting
    validation asked the same question must be compatible with every other, so a
    third machine can never outvote a direction disagreement.  The independence
    gate then requires two of them to be genuinely different machines.
    """

    by_candidate: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in validations.values():
        if record["outcome"] == "supports" and record["deterministicChecksPassed"] is True:
            by_candidate[record["candidate"]["id"]].append(dict(record))
    agreements: dict[str, tuple[tuple[dict[str, Any], ...], str]] = {}
    for candidate_id, candidate in candidates.items():
        grouped: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
        for validation in by_candidate.get(candidate_id, []):
            if validation["sealedInputDigest"] != candidate["inputContextDigest"]:
                continue
            request = validation["requestArtifact"]
            key = (
                validation["sealedInputDigest"],
                request["id"],
                request["digest"],
            )
            grouped[key].append(validation)
        for key in sorted(grouped):
            values = sorted(grouped[key], key=lambda item: item["id"])
            relation = _agreement_relation_tag(values)
            if relation is None:
                # These machines did not answer one question with one relation.
                # A different sealed question may still have agreement.
                continue
            independent_witness = next(
                (
                    pair
                    for pair in itertools.combinations(values, 2)
                    if pair[0]["validatorActor"] != pair[1]["validatorActor"]
                    and pair[0]["independenceGroup"] != pair[1]["independenceGroup"]
                    and pair[0]["provider"] != pair[1]["provider"]
                    and pair[0]["providerModelId"] != pair[1]["providerModelId"]
                    and pair[0]["responseArtifact"] != pair[1]["responseArtifact"]
                ),
                None,
            )
            if independent_witness is not None:
                # Every value above affected the unanimous relation gate.  Keep
                # the full set in the proof; the witness pair establishes only
                # that the set contains two independent machines.
                agreements[candidate_id] = (tuple(values), relation)
                break
    return agreements


def _qualified_candidates(
    candidates: Mapping[str, Mapping[str, Any]],
    validations: Mapping[str, Mapping[str, Any]],
) -> dict[str, tuple[dict[str, Any], ...]]:
    """Candidates that earn a mapping: adjudicated-``related`` is excluded."""

    return {
        candidate_id: supporting
        for candidate_id, (supporting, relation) in _independent_agreements(candidates, validations).items()
        if relation != _RELATED_MATCH
    }


def _artifact_from_record(record: Mapping[str, Any]) -> CrosswalkArtifact:
    _verify_sealed_record(
        record,
        record_type="urn:ref:type:VocabularyAtlasCrosswalkArtifact",
        id_prefix="urn:ref:vocabulary-atlas-artifact:",
    )
    if set(record) != {
        "id",
        "type",
        "role",
        "mediaType",
        "content",
        "canonicalPayloadDigest",
    }:
        raise VocabularyAtlasError("crosswalk artifact fields differ from v1")
    rebuilt = CrosswalkArtifact.create(
        role=record["role"],  # type: ignore[arg-type]
        media_type=record["mediaType"],
        content=record["content"],
    )
    if rebuilt.to_dict() != _plain(record):
        raise VocabularyAtlasError("crosswalk artifact content differs")
    return rebuilt


def _candidate_from_record(record: Mapping[str, Any]) -> MappingCandidate:
    _verify_sealed_record(
        record,
        record_type="urn:ref:type:VocabularyAtlasMappingCandidate",
        id_prefix="urn:ref:vocabulary-atlas-mapping-candidate:",
    )
    required = {
        "id",
        "type",
        "sourceMember",
        "sourceRelease",
        "targetMember",
        "targetRelease",
        "proposedRelation",
        "generatorKind",
        "generatorActor",
        "generatorProvider",
        "modelId",
        "modelVersion",
        "promptTemplate",
        "inputContextDigest",
        "temperature",
        "evidence",
        "generatedAt",
        "canonicalPayloadDigest",
    }
    if not required <= set(record) or set(record) - required != ({"seed"} if "seed" in record else set()):
        raise VocabularyAtlasError("mapping candidate fields differ from v1")
    rebuilt = MappingCandidate.create(
        source_member=record["sourceMember"],
        source_release=record["sourceRelease"],
        target_member=record["targetMember"],
        target_release=record["targetRelease"],
        proposed_relation=record["proposedRelation"],
        generator_kind=record["generatorKind"],  # type: ignore[arg-type]
        generator_actor=record["generatorActor"],
        generator_provider=record["generatorProvider"],
        model_id=record["modelId"],
        model_version=record["modelVersion"],
        prompt_template=record["promptTemplate"],
        input_context_digest=record["inputContextDigest"],
        temperature=record["temperature"],
        evidence=record["evidence"],
        generated_at=record["generatedAt"],
        seed=record.get("seed"),
    )
    if rebuilt.to_dict() != _plain(record):
        raise VocabularyAtlasError("mapping candidate content differs")
    return rebuilt


def _validation_from_record(record: Mapping[str, Any]) -> MachineValidation:
    _verify_sealed_record(
        record,
        record_type="urn:ref:type:VocabularyAtlasMachineValidation",
        id_prefix="urn:ref:vocabulary-atlas-machine-validation:",
    )
    base_fields = {
        "id",
        "type",
        "candidate",
        "validatorKind",
        "validatorActor",
        "independenceGroup",
        "provider",
        "providerModelId",
        "sealedInputDigest",
        "requestArtifact",
        "responseArtifact",
        "deterministicChecksPassed",
        "outcome",
        "completedAt",
        "canonicalPayloadDigest",
    }
    if set(record) not in (base_fields, base_fields | {"verdictRelation"}):
        raise VocabularyAtlasError("machine validation fields differ from v1")
    rebuilt = MachineValidation.create(
        candidate=record["candidate"],
        validator_kind=record["validatorKind"],  # type: ignore[arg-type]
        validator_actor=record["validatorActor"],
        independence_group=record["independenceGroup"],
        provider=record["provider"],
        provider_model_id=record["providerModelId"],
        sealed_input_digest=record["sealedInputDigest"],
        request_artifact=record["requestArtifact"],
        response_artifact=record["responseArtifact"],
        deterministic_checks_passed=record["deterministicChecksPassed"],
        outcome=record["outcome"],  # type: ignore[arg-type]
        completed_at=record["completedAt"],
        verdict_relation=record.get("verdictRelation"),
    )
    if rebuilt.to_dict() != _plain(record):
        raise VocabularyAtlasError("machine validation content differs")
    return rebuilt


def _feedback_from_record(record: Mapping[str, Any]) -> MappingFeedback:
    _verify_sealed_record(
        record,
        record_type="urn:ref:type:VocabularyAtlasMappingFeedback",
        id_prefix="urn:ref:vocabulary-atlas-mapping-feedback:",
    )
    if set(record) != {
        "id",
        "type",
        "candidate",
        "actor",
        "disposition",
        "comment",
        "recordedAt",
        "canonicalPayloadDigest",
    }:
        raise VocabularyAtlasError("mapping feedback fields differ from v1")
    rebuilt = MappingFeedback.create(
        candidate=record["candidate"],
        actor=record["actor"],
        disposition=record["disposition"],  # type: ignore[arg-type]
        comment=record["comment"],
        recorded_at=record["recordedAt"],
    )
    if rebuilt.to_dict() != _plain(record):
        raise VocabularyAtlasError("mapping feedback content differs")
    return rebuilt


def _canonical_nquads(dataset: Dataset) -> bytes:
    if any(isinstance(term, BNode) for context in dataset.graphs() for triple in context for term in triple):
        raise VocabularyAtlasError("atlas must not contain blank nodes")
    serialized = dataset.serialize(format="nquads")
    text = serialized.decode("utf-8") if isinstance(serialized, bytes) else serialized
    lines = sorted(line.strip() for line in text.splitlines() if line.strip())
    return (("\n".join(lines) + "\n") if lines else "").encode("utf-8")


def _release_members(release_graph: Graph) -> Mapping[URIRef, frozenset[URIRef]]:
    """Return each member's authoritative releases from ``prov:hadMember``."""

    memberships: dict[URIRef, set[URIRef]] = defaultdict(set)
    for release, member in release_graph.subject_objects(PROV.hadMember):
        if isinstance(release, URIRef) and isinstance(member, URIRef):
            memberships[member].add(release)
    return {member: frozenset(releases) for member, releases in memberships.items()}


def _refuse_hierarchy_cycles(parents: Mapping[URIRef, tuple[URIRef, ...]]) -> None:
    """Refuse a hierarchy cycle instead of admitting and marking it.

    SKOS permits cycles in the wild, but a source thesaurus that emits one has
    a defect rather than a meaning: nothing is genuinely broader than itself.
    The published ELSST releases settle it from the data — R5 (3,361 edges)
    and R6 (3,393 edges) are both strictly acyclic — so refusing costs no real
    vocabulary and makes every transitive read finite by construction.
    """

    settled: set[URIRef] = set()
    for start in sorted(parents):
        if start in settled:
            continue
        active = {start}
        stack: list[tuple[URIRef, Iterator[URIRef]]] = [(start, iter(parents.get(start, ())))]
        while stack:
            node, walk = stack[-1]
            following = next(walk, None)
            if following is None:
                stack.pop()
                active.discard(node)
                settled.add(node)
                continue
            if following in active:
                raise VocabularyAtlasError("atlas hierarchy contains a cycle")
            if following in settled:
                continue
            active.add(following)
            stack.append((following, iter(parents.get(following, ()))))


def _stated_edges(release_graph: Graph, predicate: URIRef) -> set[tuple[URIRef, URIRef]]:
    """Return one direction's statements, refused unless they connect IRIs."""

    edges: set[tuple[URIRef, URIRef]] = set()
    for subject, value in release_graph.subject_objects(predicate):
        if not isinstance(subject, URIRef) or not isinstance(value, URIRef):
            raise VocabularyAtlasError("atlas hierarchy must connect two concept IRIs")
        edges.add((subject, value))
    return edges


def _hierarchy_edges(release_graph: Graph) -> tuple[tuple[URIRef, URIRef], ...]:
    """Return the intra-scheme hierarchy as ``(narrower, broader)`` pairs.

    Hierarchy comes from the source vocabulary's own structure, so it is a
    layer-1 release fact copied verbatim like any other — including its
    ``skos:narrower`` statements, which are kept exactly as the release made
    them.  Thesauri assert both directions deliberately: ISO 25964 treats BT
    and NT as first-class, and SKOS declares them ``owl:inverseOf`` rather
    than asking a reader to infer one from the other.

    An edge is projected from the broader direction only, so a consumer's
    ``broader``/``narrower`` reads still cannot disagree with one another.
    When the release states both directions they must agree exactly, and the
    refusal below names the disagreement rather than the existence of NT.
    That is what makes the one-direction projection sound: the property is
    proven against the source instead of bought by refusing real data.  ELSST
    is the case that matters — 6,754 broader and 6,754 narrower statements,
    perfectly reciprocal, zero asymmetric edges in either edition.

    A cross-release edge is refused because that claim is what a qualified
    ``searchOnly`` mapping exists to carry, and it must earn its two
    independent machine validations rather than ride in as a copied fact.
    """

    broader = _stated_edges(release_graph, SKOS.broader)
    narrower = {(child, parent) for parent, child in _stated_edges(release_graph, SKOS.narrower)}
    if narrower and narrower != broader:
        # Named for the disagreement, because a source that states only the
        # agreeing half of a pair is the defect. A reader that merged
        # ``broader`` with the inverse of ``narrower`` without this guard
        # would silently absorb whichever half the other direction denies.
        raise VocabularyAtlasError("atlas hierarchy directions disagree")

    memberships = _release_members(release_graph)
    grouped: dict[URIRef, list[URIRef]] = defaultdict(list)
    for child, parent in sorted(broader):
        if child == parent:
            raise VocabularyAtlasError("atlas hierarchy edge repeats one concept")
        child_releases = memberships.get(child, frozenset())
        parent_releases = memberships.get(parent, frozenset())
        if not child_releases or not parent_releases:
            raise VocabularyAtlasError("atlas hierarchy endpoint is not a release member")
        if not child_releases & parent_releases:
            raise VocabularyAtlasError("atlas hierarchy must stay inside one release")
        grouped[child].append(parent)
    _refuse_hierarchy_cycles({child: tuple(sorted(values)) for child, values in grouped.items()})
    return tuple(sorted(broader))


def _stable_iri(prefix: str, *parts: str) -> URIRef:
    digest = _digest_value({"prefix": prefix, "parts": list(parts)})
    return URIRef(f"urn:ref:vocabulary-atlas-{prefix}:{digest.removeprefix('sha256:')}")


def _build_dataset(
    releases: Sequence[_ResolvedManagedRelease],
    *,
    asset_id: str,
    crosswalks: Sequence[CrosswalkBundle],
) -> tuple[bytes, dict[str, int], str, str]:
    release_graph_id = asset_id + ":release-facts"
    analysis_graph_id = asset_id + ":analysis"
    dataset = Dataset(default_union=False)
    release_graph = dataset.graph(URIRef(release_graph_id))
    analysis = dataset.graph(URIRef(analysis_graph_id))

    source_union = Graph()
    views = [item.view for item in releases]
    for view in views:
        source_union.parse(
            data=canonical_json(_plain(view.rulespec_graph)),
            format="json-ld",
        )
    for triple in to_canonical_graph(source_union):
        release_graph.add(
            cast(
                tuple[Any, Any, Any],
                tuple(URIRef(f"{asset_id}:bnode:{term}") if isinstance(term, BNode) else term for term in triple),
            )
        )
    # Some historical managed graphs use a compact JSON-LD context that leaves
    # ``prov:hadMember`` values as literals when parsed generically.  The
    # verified view has already checked these exact release/member pairs, so the
    # portable RDF distribution writes their required resource-valued form.
    for view in views:
        for member in view.iter_members():
            release = URIRef(member.release_iri)
            member_iri = URIRef(member.member_iri)
            release_graph.remove((release, PROV.hadMember, RdfLiteral(member.member_iri)))
            release_graph.add((release, PROV.hadMember, member_iri))
    # ``skos:broader`` and ``skos:narrower`` reach the same generic parse the
    # same way, and the release's normalized `concept_relations` rows are the
    # verified, byte-pinned form of exactly these edges. A row therefore
    # repairs the value type of a statement the graph already makes; it never
    # authorizes one. Release facts are copied, so an edge no statement makes
    # is an assertion rather than a copy, and it is refused. A literal value
    # that no verified row covers survives untouched and is refused below.
    # Admission is not decided here: the release graph is the authority, and a
    # resource-valued edge it states is admitted by the rules in
    # ``_hierarchy_edges`` whether or not a normalized row also covers it.
    for view in views:
        for relation in view.iter_relations():
            if relation.predicate_iri not in (str(SKOS.broader), str(SKOS.narrower)):
                continue
            predicate = URIRef(relation.predicate_iri)
            subject = URIRef(relation.subject_member_iri)
            resource = URIRef(relation.object_member_iri)
            if (subject, predicate, resource) in release_graph:
                continue
            stale = [
                value
                for value in release_graph.objects(subject, predicate)
                if isinstance(value, RdfLiteral) and str(value) == relation.object_member_iri
            ]
            if not stale:
                raise VocabularyAtlasError("atlas hierarchy relation row states an edge the release graph does not")
            for value in stale:
                release_graph.remove((subject, predicate, value))
            release_graph.add((subject, predicate, resource))

    hierarchy = _hierarchy_edges(release_graph)

    analysis_root = URIRef(analysis_graph_id)
    analysis.add((analysis_root, RDF.type, ATLAS.ReplaceableAnalysis))
    for view in views:
        analysis.add((analysis_root, PROV.wasDerivedFrom, URIRef(view.release_id)))

    endpoint_releases: dict[str, set[str]] = defaultdict(set)
    labels: dict[str, set[tuple[str, str]]] = defaultdict(set)
    for view in views:
        for member in view.iter_members():
            endpoint_releases[member.member_iri].add(member.release_iri)
            analysis.add(
                (
                    URIRef(member.member_iri),
                    ATLAS.memberOfRelease,
                    URIRef(member.release_iri),
                )
            )
        for expression in view.iter_expressions():
            member = view.lookup_member(expression.member_iri)
            if member is None:
                raise VocabularyAtlasError("release expression has no exact member")
            normalized = _normalize_label(expression.original_literal)
            if normalized:
                labels[normalized].add((expression.member_iri, member.release_iri))

    cluster_count = 0
    for normalized, members in sorted(labels.items()):
        if len(members) < 2 or len({release for _, release in members}) < 2:
            continue
        cluster = _stable_iri("label-cluster", normalized)
        analysis.add((cluster, RDF.type, ATLAS.LabelCluster))
        analysis.add((cluster, ATLAS.normalizedLabel, RdfLiteral(normalized)))
        for member_iri, release_iri in sorted(members):
            analysis.add((cluster, ATLAS.member, URIRef(member_iri)))
            analysis.add((cluster, ATLAS.memberRelease, URIRef(release_iri)))
        cluster_count += 1

    candidate_count = 0
    validation_count = 0
    feedback_count = 0
    search_mapping_count = 0
    seen_sealed_ids: set[str] = set()
    for crosswalk in sorted(crosswalks, key=lambda item: item.identifier):
        bundle = crosswalk.to_dict()
        candidates = {item["id"]: item for item in bundle["mappingCandidates"]}
        validations = {item["id"]: item for item in bundle["machineValidations"]}
        bundle_artifacts = {item["id"]: item for item in bundle["artifacts"]}
        # Artifacts are content-addressed: an identical id is identical bytes,
        # so a shared artifact re-states the same triples and needs no refusal.
        # A candidate or validation appearing twice is double-counted evidence.
        bundle_ids = set(candidates) | set(validations)
        if bundle_ids & seen_sealed_ids:
            raise VocabularyAtlasError("crosswalk bundles repeat a sealed record id")
        seen_sealed_ids |= bundle_ids
        agreements = _independent_agreements(candidates, validations)
        qualified = {
            candidate_id: pair for candidate_id, (pair, relation) in agreements.items() if relation != _RELATED_MATCH
        }
        for artifact in bundle["artifacts"]:
            node = URIRef(artifact["id"])
            analysis.add((node, RDF.type, ATLAS.CrosswalkArtifact))
            analysis.add(
                (
                    node,
                    ATLAS.artifactDigest,
                    RdfLiteral(artifact["canonicalPayloadDigest"]),
                )
            )
            analysis.add((node, ATLAS.artifactRole, RdfLiteral(artifact["role"])))
            if artifact["role"] == "inputContext":
                # Only this role is cited by digest, so only this role needs the
                # content digest published for a consumer to resolve the citation.
                analysis.add(
                    (
                        node,
                        ATLAS.contentDigest,
                        RdfLiteral(_artifact_content_digest(artifact)),
                    )
                )
        for candidate_id, candidate in sorted(candidates.items()):
            source = candidate["sourceMember"]
            target = candidate["targetMember"]
            if candidate["sourceRelease"] not in endpoint_releases.get(source, set()):
                raise VocabularyAtlasError(f"candidate {candidate_id} source is outside its exact release")
            if candidate["targetRelease"] not in endpoint_releases.get(target, set()):
                raise VocabularyAtlasError(f"candidate {candidate_id} target is outside its exact release")
            for release_iri, endpoint_role in (
                (candidate["sourceRelease"], "source"),
                (candidate["targetRelease"], "target"),
            ):
                release_digests = tuple(
                    release_graph.objects(
                        URIRef(release_iri),
                        RKAF.referenceReleaseDigest,
                    )
                )
                if len(release_digests) != 1 or not isinstance(
                    release_digests[0],
                    RdfLiteral,
                ):
                    raise VocabularyAtlasError(
                        f"candidate {candidate_id} {endpoint_role} release lacks one exact digest"
                    )
                _require_digest(
                    str(release_digests[0]),
                    f"candidate {candidate_id} {endpoint_role} release digest",
                )
            node = URIRef(candidate_id)
            analysis.add((node, RDF.type, ATLAS.MappingCandidate))
            analysis.add(
                (
                    node,
                    ATLAS.candidateDigest,
                    RdfLiteral(candidate["canonicalPayloadDigest"]),
                )
            )
            for predicate, field in (
                (ATLAS.sourceMember, "sourceMember"),
                (ATLAS.sourceRelease, "sourceRelease"),
                (ATLAS.targetMember, "targetMember"),
                (ATLAS.targetRelease, "targetRelease"),
                (ATLAS.proposedRelation, "proposedRelation"),
            ):
                analysis.add((node, predicate, URIRef(candidate[field])))
            analysis.add(
                (
                    node,
                    ATLAS.inputContextDigest,
                    RdfLiteral(candidate["inputContextDigest"]),
                )
            )
            analysis.add(
                (
                    node,
                    ATLAS.inputContextArtifact,
                    URIRef(
                        _resolve_input_context(
                            candidate["inputContextDigest"],
                            bundle_artifacts,
                        )["id"]
                    ),
                )
            )
            for evidence in candidate["evidence"]:
                analysis.add((node, ATLAS.evidence, URIRef(evidence["id"])))
            candidate_count += 1

            agreement = agreements.get(candidate_id)
            # The adjudicated relation is the candidate's own fact under v2, and
            # it is what anchors the mapping's predicate.  `proposedRelation` is
            # the hypothesis the judge was tested against and stays untouched;
            # under v1 there is no adjudicated relation and the proposal is
            # still the anchor, exactly as before.
            if agreement is not None and agreement[1] != _PROPOSED_TAG:
                analysis.add((node, ATLAS.adjudicatedRelation, URIRef(agreement[1])))
            if agreement is not None and agreement[1] == _RELATED_MATCH:
                # Independent machines agreed the pair is associated but not
                # substitutable.  The relation is stated on the candidate so the
                # refusal is typed rather than blank, and no mapping is emitted.
                analysis.add((node, RKAF.usageEligibility, RKAF.notEligible))
                continue
            selected = qualified.get(candidate_id)
            if selected is None:
                analysis.add((node, RKAF.usageEligibility, RKAF.notEligible))
                continue
            relation_iri = (
                agreement[1]
                if agreement is not None and agreement[1] != _PROPOSED_TAG
                else str(candidate["proposedRelation"])
            )
            analysis.add((node, RKAF.usageEligibility, RKAF.searchOnly))
            mapping = _stable_iri(
                "search-only-mapping",
                candidate_id,
                *(validation["id"] for validation in selected),
            )
            analysis.add((mapping, RDF.type, RKAF.ConceptMapping))
            analysis.add((mapping, RKAF.assertsSubject, URIRef(source)))
            analysis.add((mapping, RKAF.assertsPredicate, URIRef(relation_iri)))
            analysis.add((mapping, RKAF.assertsObject, URIRef(target)))
            analysis.add(
                (
                    mapping,
                    RKAF.sourceConceptRelease,
                    URIRef(candidate["sourceRelease"]),
                )
            )
            analysis.add(
                (
                    mapping,
                    RKAF.targetConceptRelease,
                    URIRef(candidate["targetRelease"]),
                )
            )
            analysis.add((mapping, RKAF.usageEligibility, RKAF.searchOnly))
            analysis.add((mapping, RKAF.assertionOrigin, RKAF.aiSuggested))
            analysis.add((mapping, RKAF.epistemicBasis, RKAF.statisticalInference))
            analysis.add((mapping, ATLAS.qualifiedFrom, node))
            analysis.add(
                (
                    mapping,
                    ATLAS.selectionPolicy,
                    RdfLiteral(_POLICIES["mappingEligibility"]),
                )
            )
            analysis.add(
                (
                    mapping,
                    ATLAS.verificationStatus,
                    ATLAS.machineQualifiedForSearch,
                )
            )
            for validation in selected:
                analysis.add((mapping, ATLAS.qualifiedBy, URIRef(validation["id"])))
            search_mapping_count += 1

        for validation in sorted(validations.values(), key=lambda item: item["id"]):
            node = URIRef(validation["id"])
            analysis.add((node, RDF.type, ATLAS.MachineValidation))
            analysis.add(
                (
                    node,
                    ATLAS.validationDigest,
                    RdfLiteral(validation["canonicalPayloadDigest"]),
                )
            )
            analysis.add((node, ATLAS.validates, URIRef(validation["candidate"]["id"])))
            for predicate, field in (
                (ATLAS.validatorActor, "validatorActor"),
                (ATLAS.independenceGroup, "independenceGroup"),
                (ATLAS.provider, "provider"),
                (ATLAS.requestArtifact, "requestArtifact"),
                (ATLAS.responseArtifact, "responseArtifact"),
            ):
                value = validation[field]
                analysis.add((node, predicate, URIRef(value["id"] if isinstance(value, dict) else value)))
            analysis.add(
                (
                    node,
                    ATLAS.providerModelId,
                    RdfLiteral(validation["providerModelId"]),
                )
            )
            analysis.add(
                (
                    node,
                    ATLAS.sealedInputDigest,
                    RdfLiteral(validation["sealedInputDigest"]),
                )
            )
            analysis.add((node, ATLAS.outcome, RdfLiteral(validation["outcome"])))
            # What the machine said, not just what it decided. The reason is
            # already sealed in the response artifact and already bounded there,
            # so projecting it makes every qualified mapping and every refusal
            # answerable from the atlas instead of only from the bundle. Absent
            # when the response stated none: silence is not an empty string.
            reason = _sealed_reason(validation, bundle_artifacts)
            if reason:
                analysis.add((node, ATLAS.reason, RdfLiteral(reason)))
            if "verdictRelation" in validation:
                # Published so the agreement lattice is checkable from the atlas
                # bytes alone.  Without it a reader can see *that* a relation was
                # adjudicated but never that it follows from the verdicts.
                analysis.add(
                    (
                        node,
                        ATLAS.verdictRelation,
                        RdfLiteral(validation["verdictRelation"]),
                    )
                )
            analysis.add(
                (
                    node,
                    ATLAS.deterministicChecksPassed,
                    RdfLiteral(
                        validation["deterministicChecksPassed"],
                        datatype=XSD.boolean,
                    ),
                )
            )
            validation_count += 1
        for feedback in sorted(bundle["feedback"], key=lambda item: item["id"]):
            node = URIRef(feedback["id"])
            analysis.add((node, RDF.type, ATLAS.MappingFeedback))
            analysis.add(
                (
                    node,
                    ATLAS.feedbackDigest,
                    RdfLiteral(feedback["canonicalPayloadDigest"]),
                )
            )
            analysis.add((node, ATLAS.feedbackOn, URIRef(feedback["candidate"]["id"])))
            analysis.add((node, ATLAS.feedbackActor, URIRef(feedback["actor"])))
            analysis.add(
                (
                    node,
                    ATLAS.feedbackDisposition,
                    RdfLiteral(feedback["disposition"]),
                )
            )
            analysis.add((node, RDFS.comment, RdfLiteral(feedback["comment"])))
            analysis.add((node, PROV.generatedAtTime, RdfLiteral(feedback["recordedAt"])))
            feedback_count += 1

    payload = _canonical_nquads(dataset)
    counts = {
        "managedReleases": len(releases),
        "releaseFacts": len(release_graph),
        "analysisFacts": len(analysis),
        "labelClusters": cluster_count,
        "mappingCandidates": candidate_count,
        "searchOnlyMappings": search_mapping_count,
        "machineValidations": validation_count,
        "feedback": feedback_count,
    }
    if hierarchy:
        # Absent means zero, so an atlas over a vocabulary without hierarchy —
        # the Federal Register thesaurus, every earlier fixture — keeps the
        # exact bytes its consumers already pinned.
        counts["hierarchyEdges"] = len(hierarchy)
    return payload, counts, release_graph_id, analysis_graph_id


def _manifest_digest(manifest: Mapping[str, Any]) -> str:
    return binding.canonical_payload_digest(_plain(manifest))


def _as_mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise VocabularyAtlasError(f"{label} must be a JSON object")
    return cast(Mapping[str, Any], value)


def _as_sequence(value: object, label: str) -> Sequence[Any]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise VocabularyAtlasError(f"{label} must be a JSON array")
    return cast(Sequence[Any], value)


def _require_count(value: object, label: str, *, positive: bool = False) -> int:
    minimum = 1 if positive else 0
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        qualifier = "positive" if positive else "nonnegative"
        raise VocabularyAtlasError(f"{label} must be a {qualifier} integer")
    return value


def _one_resource(graph: Graph, subject: URIRef, predicate: URIRef, label: str) -> URIRef:
    values = tuple(graph.objects(subject, predicate))
    if len(values) != 1 or not isinstance(values[0], URIRef):
        raise VocabularyAtlasError(f"{label} must have exactly one IRI")
    return values[0]


def _one_literal(graph: Graph, subject: URIRef, predicate: URIRef, label: str) -> RdfLiteral:
    values = tuple(graph.objects(subject, predicate))
    if len(values) != 1 or not isinstance(values[0], RdfLiteral):
        raise VocabularyAtlasError(f"{label} must have exactly one literal")
    return values[0]


def _search_only_mapping_nodes(analysis: Graph) -> tuple[URIRef, ...]:
    """Return every concept mapping in the analysis graph, in id order.

    An atlas only ever carries ``searchOnly`` mappings, so a mapping with any
    other eligibility is a defect rather than a row to skip.  This is the one
    place that decides which nodes are mappings; :mod:`refspec.atlas.queries`
    reads the same answer instead of re-deriving a laxer one.
    """

    nodes: list[URIRef] = []
    for subject in sorted(set(analysis.subjects(RDF.type, RKAF.ConceptMapping)), key=str):
        if not isinstance(subject, URIRef):
            raise VocabularyAtlasError("searchOnly mapping id must be an IRI")
        if _one_resource(analysis, subject, RKAF.usageEligibility, "mapping eligibility") != RKAF.searchOnly:
            raise VocabularyAtlasError("searchOnly mapping has contradictory eligibility")
        nodes.append(subject)
    return tuple(nodes)


def _search_only_mapping_validations(analysis: Graph, mapping: URIRef) -> tuple[URIRef, ...]:
    """Return the complete supporting set that qualifies one mapping."""

    validations = tuple(sorted(set(analysis.objects(mapping, ATLAS.qualifiedBy)), key=str))
    if len(validations) < 2 or any(not isinstance(value, URIRef) for value in validations):
        raise VocabularyAtlasError("searchOnly mapping needs at least two machine validations")
    if any((value, RDF.type, ATLAS.MachineValidation) not in analysis for value in validations):
        raise VocabularyAtlasError("searchOnly mapping validation is missing")
    return cast(tuple[URIRef, ...], validations)


def _label_cluster_nodes(analysis: Graph) -> tuple[URIRef, ...]:
    """Return every label cluster in the analysis graph, in id order.

    A cluster only means anything if it crosses releases, so the cross-release
    and membership checks belong to reading a cluster, not to one caller.
    """

    clusters: list[URIRef] = []
    for cluster in sorted(set(analysis.subjects(RDF.type, ATLAS.LabelCluster)), key=str):
        if not isinstance(cluster, URIRef):
            raise VocabularyAtlasError("label cluster id must be an IRI")
        _one_literal(analysis, cluster, ATLAS.normalizedLabel, "label cluster normalized label")
        members = tuple(analysis.objects(cluster, ATLAS.member))
        releases = tuple(analysis.objects(cluster, ATLAS.memberRelease))
        if len(members) < 2 or not releases:
            raise VocabularyAtlasError("label cluster must contain members from releases")
        if any(not isinstance(value, URIRef) for value in (*members, *releases)):
            raise VocabularyAtlasError("label cluster members and releases must be IRIs")
        if len(set(releases)) < 2:
            raise VocabularyAtlasError("label cluster must cross releases")
        if any(
            not any((member, ATLAS.memberOfRelease, release) in analysis for release in releases) for member in members
        ):
            raise VocabularyAtlasError("label cluster member is outside its declared releases")
        clusters.append(cluster)
    return tuple(clusters)


def _validate_input_pin(value: object) -> str:
    pin = _as_mapping(value, "atlas input")
    role = pin.get("role")
    if role == "ManagedReleaseView":
        if set(pin) != {
            "role",
            "manifestDigest",
            "publicationReleaseId",
            "rulespecGraph",
        }:
            raise VocabularyAtlasError("managed release input fields differ from v1")
        _require_digest(pin.get("manifestDigest"), "managed release manifest digest")
        _require_iri(pin.get("publicationReleaseId"), "managed publication release id")
        graph = _as_mapping(pin.get("rulespecGraph"), "managed Rulespec graph pin")
        if set(graph) != {"id", "digest"}:
            raise VocabularyAtlasError("managed Rulespec graph pin fields differ from v1")
        _require_iri(graph.get("id"), "managed Rulespec graph id")
        _require_digest(graph.get("digest"), "managed Rulespec graph digest")
        return role
    if role == "RulespecCoreRelease":
        if set(pin) != {"role", "fileDigest", "releaseId", "releaseDigest"}:
            raise VocabularyAtlasError("Rulespec Core input fields differ from v1")
        _require_digest(pin.get("fileDigest"), "Rulespec Core file digest")
        release_id = _require_iri(pin.get("releaseId"), "Rulespec Core release id")
        release_digest = _require_digest(pin.get("releaseDigest"), "Rulespec Core release digest")
        if release_id != "urn:rulespec:core:" + release_digest.removeprefix("sha256:"):
            raise VocabularyAtlasError("Rulespec Core release id differs from its digest")
        return role
    if role == "CrosswalkBundle":
        if set(pin) != {"role", "id", "digest", "fileDigest", "mediaType"}:
            raise VocabularyAtlasError("crosswalk input fields differ from v1")
        _require_iri(pin.get("id"), "crosswalk bundle id")
        _require_digest(pin.get("digest"), "crosswalk bundle digest")
        _require_digest(pin.get("fileDigest"), "crosswalk file digest")
        if pin.get("mediaType") != CROSSWALK_MEDIA_TYPE:
            raise VocabularyAtlasError("crosswalk media type differs")
        return role
    raise VocabularyAtlasError("atlas input role is unsupported")


def _validate_implementation_pin(value: object) -> Mapping[str, Any]:
    implementation = _as_mapping(value, "atlas implementation")
    if set(implementation) != {"id", "version", "sourceModules", "runtime"}:
        raise VocabularyAtlasError("atlas implementation fields differ from v1")
    _require_iri(implementation.get("id"), "atlas implementation id")
    _require_text(implementation.get("version"), "atlas implementation version")
    modules = _as_sequence(implementation.get("sourceModules"), "atlas implementation source modules")
    if not modules:
        raise VocabularyAtlasError("atlas implementation needs at least one source module")
    seen_paths: set[str] = set()
    for item in modules:
        module = _as_mapping(item, "atlas implementation source module")
        if set(module) != {"path", "digest"}:
            raise VocabularyAtlasError("atlas implementation source module fields differ from v1")
        path = _require_text(module.get("path"), "atlas implementation source module path")
        if path in seen_paths:
            raise VocabularyAtlasError("atlas implementation repeats a source module")
        seen_paths.add(path)
        _require_digest(module.get("digest"), f"atlas implementation module {path} digest")
    runtime = _as_mapping(implementation.get("runtime"), "atlas implementation runtime")
    if not runtime:
        raise VocabularyAtlasError("atlas implementation runtime must not be empty")
    for field, runtime_value in runtime.items():
        _require_text(field, "atlas implementation runtime name")
        _require_text(runtime_value, f"atlas implementation runtime {field}")
    return implementation


def _validate_projected_artifact(graph: Graph, artifact: URIRef, *, role: str) -> None:
    if (artifact, RDF.type, ATLAS.CrosswalkArtifact) not in graph:
        raise VocabularyAtlasError("searchOnly mapping references a missing crosswalk artifact")
    observed_role = _one_literal(graph, artifact, ATLAS.artifactRole, "crosswalk artifact role")
    if str(observed_role) != role:
        raise VocabularyAtlasError("searchOnly mapping references a crosswalk artifact with the wrong role")
    _require_digest(
        str(_one_literal(graph, artifact, ATLAS.artifactDigest, "crosswalk artifact digest")),
        "crosswalk artifact digest",
    )


def _sealed_reason(
    validation: Mapping[str, Any],
    artifacts: Mapping[str, Mapping[str, Any]],
) -> str:
    """The free text this validation's sealed response carried, if any.

    Read from the response artifact rather than the validation record because
    that is where the producer sealed it, and it is already bounded there.
    """

    record = artifacts.get(str(validation["responseArtifact"]["id"]))
    if record is None:
        return ""
    content = record.get("content")
    if not isinstance(content, Mapping):
        return ""
    reason = content.get("reason")
    if not isinstance(reason, str):
        return ""
    return reason.strip()


def _verify_adjudicated_relation(
    graph: Graph,
    *,
    candidate: URIRef,
    anchor: URIRef | None,
    has_mapping: bool,
) -> None:
    """The agreement lattice, re-derived from the published verdicts.

    Checking only that a mapping matches its candidate's adjudicated relation
    would accept a distribution whose adjudication contradicts the very verdicts
    it cites. The rule is universal: every supporting validation that answered
    this candidate's sealed question must be relation-compatible with every
    other, and the adjudicated relation is the weakest claim any of them made.

    Driven by the *verdicts*, never by whether the producer volunteered an
    adjudication. Keying it off the adjudication would make the whole check
    opt-in for exactly the party with a motive to skip it: omit one triple and a
    pair two machines typed ``target_is_broader`` falls back to the uniform
    proposal and publishes as ``closeMatch``. So verdicts present and no
    adjudication is a refusal, not a v1 distribution.
    """

    input_digest = str(_one_literal(graph, candidate, ATLAS.inputContextDigest, "mapping input digest"))
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    carriers = 0
    supporters = 0
    for validation in graph.subjects(ATLAS.validates, candidate):
        if not isinstance(validation, URIRef):
            raise VocabularyAtlasError("machine validation must be an IRI")
        if (validation, RDF.type, ATLAS.MachineValidation) not in graph:
            raise VocabularyAtlasError("machine validation is untyped")
        sealed = _one_literal(graph, validation, ATLAS.sealedInputDigest, "machine sealed input digest")
        if str(sealed) != input_digest:
            continue
        if str(_one_literal(graph, validation, ATLAS.outcome, "machine validation outcome")) != "supports":
            continue
        deterministic = _one_literal(
            graph,
            validation,
            ATLAS.deterministicChecksPassed,
            "machine deterministic check",
        )
        if deterministic.toPython() is not True:
            continue
        supporters += 1
        stated = tuple(graph.objects(validation, ATLAS.verdictRelation))
        if len(stated) > 1:
            raise VocabularyAtlasError("machine validation verdictRelation must have exactly one value")
        if stated:
            carriers += 1
        request = _one_resource(graph, validation, ATLAS.requestArtifact, "machine request artifact")
        grouped[str(request)].append(
            {
                "id": str(validation),
                "verdictRelation": str(stated[0]) if stated else None,
                # The five identity fields the gate requires to differ. Read
                # here so the graph applies the same independence predicate the
                # writer applied to the sealed records.
                "identity": (
                    str(_one_resource(graph, validation, ATLAS.validatorActor, "machine validator actor")),
                    str(_one_resource(graph, validation, ATLAS.independenceGroup, "machine independence group")),
                    str(_one_resource(graph, validation, ATLAS.provider, "machine provider")),
                    str(_one_literal(graph, validation, ATLAS.providerModelId, "machine provider model id")),
                    str(_one_resource(graph, validation, ATLAS.responseArtifact, "machine response artifact")),
                ),
            }
        )
    if carriers not in (0, supporters):
        raise VocabularyAtlasError("machine validations mix adjudicated and unadjudicated verdicts")
    if carriers == 0:
        # The v1 shape states no adjudication and needs none.
        if anchor is not None:
            raise VocabularyAtlasError("mapping candidate states an adjudicated relation with no verdicts")
        return
    for values in grouped.values():
        for value in values:
            if value["verdictRelation"] not in _V2_VERDICTS:
                raise VocabularyAtlasError("machine validation verdictRelation is unsupported")

    # Mirror the writer exactly: an adjudication is owed precisely when the gate
    # would have emitted one, which needs BOTH a relation every supporting
    # validation on one question agrees with AND an independent pair among them.
    # Deriving "the verdicts state a relation" from anything wider — a lone
    # support, or a pair from one machine — refuses the ordinary shape where the
    # second machine abstained or answered no.
    agreed: str | None = None
    for key in sorted(grouped):
        values = sorted(grouped[key], key=lambda item: str(item["id"]))
        relation = _agreed_relation_for(frozenset(str(value["verdictRelation"]) for value in values))
        if relation is None:
            continue
        if any(
            all(left != right for left, right in zip(first["identity"], second["identity"], strict=True))
            for first, second in itertools.combinations(values, 2)
        ):
            agreed = relation
            break

    if agreed is None:
        # Nothing was adjudicated, so nothing is owed — but nothing may be
        # claimed either, and no mapping may rest on it.
        if anchor is not None:
            raise VocabularyAtlasError("mapping candidate adjudicated relation does not follow from its verdicts")
        if has_mapping:
            raise VocabularyAtlasError("qualifying validations disagree about the relation")
        return
    if anchor is None:
        raise VocabularyAtlasError("mapping candidate omits the adjudicated relation its verdicts state")
    if agreed != str(anchor):
        raise VocabularyAtlasError("mapping candidate adjudicated relation does not follow from its verdicts")


def _reference_release_digest(graph: Graph, release: URIRef) -> str:
    if (release, RDF.type, RKAF.ReferenceResourceRelease) not in graph:
        raise VocabularyAtlasError("searchOnly mapping release is not a ReferenceResourceRelease")
    return _require_digest(
        str(_one_literal(graph, release, RKAF.referenceReleaseDigest, "reference release digest")),
        "reference release digest",
    )


def _validate_query_graph_semantics(
    dataset: Dataset,
    *,
    release_graph_id: str,
    analysis_graph_id: str,
) -> None:
    """Validate the graph facts exposed by :mod:`refspec.atlas.queries`.

    This is intentionally a distribution check.  Producer-only reconstruction
    additionally reopens the crosswalk bundle and recomputes every projected
    fact from its exact inputs.
    """

    release_graph = dataset.graph(URIRef(release_graph_id))
    analysis = dataset.graph(URIRef(analysis_graph_id))

    _hierarchy_edges(release_graph)

    for member, release in analysis.subject_objects(ATLAS.memberOfRelease):
        if not isinstance(member, URIRef) or not isinstance(release, URIRef):
            raise VocabularyAtlasError("atlas membership must connect two IRIs")
        _reference_release_digest(release_graph, release)
        if (release, PROV.hadMember, member) not in release_graph:
            raise VocabularyAtlasError("atlas analysis membership is absent from authoritative release facts")

    _label_cluster_nodes(analysis)

    # Every adjudication is checked here, on the candidate that states it,
    # whether or not it went on to earn a mapping. Checking only the ones that
    # qualified would leave adjudicated-`related` — the single agreed relation
    # that emits no mapping — unverifiable, and that is exactly the claim a
    # producer would have the most reason to overstate.
    #
    # Mapping subjects are collected without cardinality checks on purpose: the
    # mapping loop below owns those, and preempting them here would change which
    # refusal a forged distribution gets.
    qualified_candidates = {
        value
        for mapping in _search_only_mapping_nodes(analysis)
        for value in analysis.objects(mapping, ATLAS.qualifiedFrom)
    }
    for candidate in sorted(analysis.subjects(RDF.type, ATLAS.MappingCandidate), key=str):
        if not isinstance(candidate, URIRef):
            raise VocabularyAtlasError("mapping candidate must be an IRI")
        stated = tuple(analysis.objects(candidate, ATLAS.adjudicatedRelation))
        if len(stated) > 1 or (stated and not isinstance(stated[0], URIRef)):
            raise VocabularyAtlasError("mapping candidate adjudicated relation must have exactly one IRI")
        if stated and str(stated[0]) not in _MAPPING_RELATIONS:
            raise VocabularyAtlasError("mapping candidate adjudicated relation is unsupported")
        # Every candidate, not only the ones that state an adjudication: the
        # verdicts decide whether one is owed.
        _verify_adjudicated_relation(
            analysis,
            candidate=candidate,
            anchor=stated[0] if stated else None,
            has_mapping=candidate in qualified_candidates,
        )
        if not stated or str(stated[0]) != _RELATED_MATCH:
            continue
        if candidate in qualified_candidates:
            raise VocabularyAtlasError("adjudicated related must not qualify a searchOnly mapping")
        if _one_resource(analysis, candidate, RKAF.usageEligibility, "candidate eligibility") != RKAF.notEligible:
            raise VocabularyAtlasError("adjudicated related candidate must not be eligible")

    for mapping in _search_only_mapping_nodes(analysis):
        validations = _search_only_mapping_validations(analysis, mapping)
        source = _one_resource(analysis, mapping, RKAF.assertsSubject, "mapping source")
        relation = _one_resource(analysis, mapping, RKAF.assertsPredicate, "mapping relation")
        target = _one_resource(analysis, mapping, RKAF.assertsObject, "mapping target")
        source_release = _one_resource(
            analysis,
            mapping,
            RKAF.sourceConceptRelease,
            "mapping source release",
        )
        target_release = _one_resource(
            analysis,
            mapping,
            RKAF.targetConceptRelease,
            "mapping target release",
        )
        if str(relation) not in _MAPPING_RELATIONS:
            raise VocabularyAtlasError("searchOnly mapping relation is unsupported")
        if _one_resource(analysis, mapping, RKAF.assertionOrigin, "mapping origin") != RKAF.aiSuggested:
            raise VocabularyAtlasError("searchOnly mapping origin differs")
        if (
            _one_resource(analysis, mapping, RKAF.epistemicBasis, "mapping epistemic basis")
            != RKAF.statisticalInference
        ):
            raise VocabularyAtlasError("searchOnly mapping epistemic basis differs")
        if (
            str(_one_literal(analysis, mapping, ATLAS.selectionPolicy, "mapping selection policy"))
            != _POLICIES["mappingEligibility"]
        ):
            raise VocabularyAtlasError("searchOnly mapping selection policy differs")
        if (
            _one_resource(analysis, mapping, ATLAS.verificationStatus, "mapping verification status")
            != ATLAS.machineQualifiedForSearch
        ):
            raise VocabularyAtlasError("searchOnly mapping verification status differs")

        candidate = _one_resource(analysis, mapping, ATLAS.qualifiedFrom, "mapping candidate")
        if (candidate, RDF.type, ATLAS.MappingCandidate) not in analysis:
            raise VocabularyAtlasError("searchOnly mapping candidate is missing")
        if _one_resource(analysis, candidate, RKAF.usageEligibility, "candidate eligibility") != RKAF.searchOnly:
            raise VocabularyAtlasError("searchOnly mapping candidate is not searchOnly")
        # The relation anchor. Under v1 the candidate's proposal *is* the
        # adjudicated answer, so the proposal anchors the mapping. Under v2 the
        # judge answers a richer question than the one proposed, so the
        # adjudicated relation anchors it and the proposal stays the untouched
        # record of what was tested. Anchoring v2 to the proposal would forbid
        # every relation except the one hypothesis it holds.
        adjudicated = tuple(analysis.objects(candidate, ATLAS.adjudicatedRelation))
        if len(adjudicated) > 1:
            raise VocabularyAtlasError("mapping candidate adjudicated relation must have exactly one IRI")
        if adjudicated and not isinstance(adjudicated[0], URIRef):
            raise VocabularyAtlasError("mapping candidate adjudicated relation must be an IRI")
        if adjudicated and str(adjudicated[0]) not in _MAPPING_RELATIONS:
            raise VocabularyAtlasError("mapping candidate adjudicated relation is unsupported")
        anchor = adjudicated[0] if adjudicated else None
        proposed = _one_resource(analysis, candidate, ATLAS.proposedRelation, "mapping candidate proposal")
        expected_candidate_values = (
            (ATLAS.sourceMember, source),
            (ATLAS.targetMember, target),
            (ATLAS.sourceRelease, source_release),
            (ATLAS.targetRelease, target_release),
        )
        if any(
            _one_resource(analysis, candidate, predicate, "mapping candidate endpoint") != expected
            for predicate, expected in expected_candidate_values
        ):
            raise VocabularyAtlasError("searchOnly mapping differs from its candidate")
        if (anchor if anchor is not None else proposed) != relation:
            raise VocabularyAtlasError("searchOnly mapping differs from its candidate")
        _require_digest(
            str(_one_literal(analysis, candidate, ATLAS.candidateDigest, "mapping candidate digest")),
            "mapping candidate digest",
        )
        input_digest = _require_digest(
            str(_one_literal(analysis, candidate, ATLAS.inputContextDigest, "mapping input digest")),
            "mapping input digest",
        )
        input_context = _one_resource(
            analysis,
            candidate,
            ATLAS.inputContextArtifact,
            "mapping input context artifact",
        )
        _validate_projected_artifact(analysis, input_context, role="inputContext")
        if (
            str(
                _one_literal(
                    analysis,
                    input_context,
                    ATLAS.contentDigest,
                    "input context content digest",
                )
            )
            != input_digest
        ):
            raise VocabularyAtlasError("searchOnly mapping input context does not carry the sealed input digest")
        evidence = tuple(analysis.objects(candidate, ATLAS.evidence))
        if not evidence or any(not isinstance(item, URIRef) for item in evidence):
            raise VocabularyAtlasError("searchOnly mapping candidate needs IRI evidence")
        for artifact in cast(tuple[URIRef, ...], evidence):
            _validate_projected_artifact(analysis, artifact, role="evidence")

        independence: list[tuple[URIRef, URIRef, URIRef, str, URIRef]] = []
        requests: set[URIRef] = set()
        for validation in validations:
            if (validation, RDF.type, ATLAS.MachineValidation) not in analysis:
                raise VocabularyAtlasError("searchOnly mapping validation is missing")
            if _one_resource(analysis, validation, ATLAS.validates, "machine validation candidate") != candidate:
                raise VocabularyAtlasError("machine validation applies to another candidate")
            _require_digest(
                str(_one_literal(analysis, validation, ATLAS.validationDigest, "machine validation digest")),
                "machine validation digest",
            )
            if (
                str(_one_literal(analysis, validation, ATLAS.sealedInputDigest, "machine sealed input digest"))
                != input_digest
            ):
                raise VocabularyAtlasError("machine validation uses another sealed input")
            outcome = _one_literal(analysis, validation, ATLAS.outcome, "machine validation outcome")
            deterministic = _one_literal(
                analysis,
                validation,
                ATLAS.deterministicChecksPassed,
                "machine deterministic check",
            )
            if (
                str(outcome) != "supports"
                or deterministic.datatype != XSD.boolean
                or deterministic.toPython() is not True
            ):
                raise VocabularyAtlasError("machine validation does not support deterministic search use")
            actor = _one_resource(analysis, validation, ATLAS.validatorActor, "machine validator actor")
            group = _one_resource(analysis, validation, ATLAS.independenceGroup, "machine independence group")
            provider = _one_resource(analysis, validation, ATLAS.provider, "machine provider")
            provider_model_id = _require_text(
                str(
                    _one_literal(
                        analysis,
                        validation,
                        ATLAS.providerModelId,
                        "machine provider model id",
                    )
                ),
                "machine provider model id",
            )
            request = _one_resource(analysis, validation, ATLAS.requestArtifact, "machine request artifact")
            response = _one_resource(analysis, validation, ATLAS.responseArtifact, "machine response artifact")
            _validate_projected_artifact(analysis, request, role="validationRequest")
            _validate_projected_artifact(analysis, response, role="validationResponse")
            requests.add(request)
            independence.append((actor, group, provider, provider_model_id, response))
        if not any(
            all(left != right for left, right in zip(first, second, strict=True))
            for first, second in itertools.combinations(independence, 2)
        ):
            raise VocabularyAtlasError("searchOnly mapping validations are not independent")
        if len(requests) != 1:
            # Two machines that answered different requests are two answers to
            # two questions, not a corroboration.
            raise VocabularyAtlasError("searchOnly mapping validations answered different requests")
        selected_request = next(iter(requests))
        complete_support = {
            validation
            for validation in analysis.subjects(ATLAS.validates, candidate)
            if isinstance(validation, URIRef)
            and str(_one_literal(analysis, validation, ATLAS.sealedInputDigest, "machine sealed input digest"))
            == input_digest
            and str(_one_literal(analysis, validation, ATLAS.outcome, "machine validation outcome")) == "supports"
            and _one_literal(
                analysis,
                validation,
                ATLAS.deterministicChecksPassed,
                "machine deterministic check",
            ).toPython()
            is True
            and _one_resource(analysis, validation, ATLAS.requestArtifact, "machine request artifact")
            == selected_request
        }
        if set(validations) != complete_support:
            raise VocabularyAtlasError("searchOnly mapping does not cite its complete supporting validation set")
        expected_mapping = _stable_iri(
            "search-only-mapping",
            str(candidate),
            *(str(value) for value in validations),
        )
        if mapping != expected_mapping:
            raise VocabularyAtlasError("searchOnly mapping id differs from its proof")
        if (source, ATLAS.memberOfRelease, source_release) not in analysis or (
            target,
            ATLAS.memberOfRelease,
            target_release,
        ) not in analysis:
            raise VocabularyAtlasError("searchOnly mapping endpoints are outside their releases")
        _reference_release_digest(release_graph, source_release)
        _reference_release_digest(release_graph, target_release)
        if (source_release, PROV.hadMember, source) not in release_graph or (
            target_release,
            PROV.hadMember,
            target,
        ) not in release_graph:
            raise VocabularyAtlasError("searchOnly mapping endpoint is absent from its release facts")


# ---------------------------------------------------------------------------
# Canonical Atlas 2.0 distribution
# ---------------------------------------------------------------------------
#
# The classes above remain useful to the evidence and source adapters while
# they move onto the shared semantic foundation.  The publication boundary
# below intentionally does not accept those adapter-specific objects.  One
# pinned scope is the complete and only public build input.

from refspec.atlas_index import AtlasIndexError
from refspec.registry.infrastructure.semantic_foundation import SemanticRing

from .atlas_scope import (
    AtlasScopeError,
    PinnedVocabularyAtlasScope,
    validate_atlas_scope_record,
)
from .relation_assertion import (
    EmbeddedRelationAssertionBundle,
    RelationAssertionError,
)
from .release_snapshot import (
    AtlasReleaseSnapshot,
    AtlasReleaseSnapshotError,
)

_RING_ORDER: tuple[SemanticRing, ...] = (
    "subject",
    "entity",
    "value",
    "legalIdentity",
)
_RELEASE_GRAPH_ROLES = frozenset({"conceptRelease", "concept", "releaseRecord"})
_CROSS_RELEASE_GRAPH_ROLES = frozenset(
    {
        "relationBundle",
        "evidenceAssertion",
        "mappingAssertion",
        "machineProof",
    }
)
_CHILD_ROLE_CONTAINMENT = MappingProxyType(
    {
        "concept": "release",
        "releaseRecord": "release",
        "evidenceAssertion": "relationBundle",
        "mappingAssertion": "relationBundle",
        "machineProof": "relationBundle",
    }
)
_MANIFEST_FIELDS_V2 = frozenset(
    {
        "id",
        "type",
        "schemaVersion",
        "format",
        "generationDigest",
        "scope",
        "implementation",
        "policies",
        "graphs",
        "output",
        "counts",
        "rings",
        "canonicalPayloadDigest",
    }
)
_COUNT_FIELDS_V2 = frozenset(
    {
        "conceptReleases",
        "concepts",
        "releaseRecords",
        "relationBundles",
        "evidenceAssertions",
        "mappingAssertions",
        "machineProofs",
    }
)
_ROLE_COUNT_FIELD = MappingProxyType(
    {
        "conceptRelease": "conceptReleases",
        "concept": "concepts",
        "releaseRecord": "releaseRecords",
        "relationBundle": "relationBundles",
        "evidenceAssertion": "evidenceAssertions",
        "mappingAssertion": "mappingAssertions",
        "machineProof": "machineProofs",
    }
)
_SCOPE_MEDIA_TYPE = "application/vnd.refspec.vocabulary-atlas-scope+json"
_RECORD_PREDICATES = frozenset(
    {
        RDF.type,
        ATLAS.recordRole,
        ATLAS.recordDigest,
        ATLAS.canonicalJson,
        ATLAS.recordId,
        ATLAS.inRelease,
        ATLAS.inRelationBundle,
    }
)


@dataclass(frozen=True, slots=True)
class _CanonicalAtlasRecord:
    record: Mapping[str, Any]
    role: str
    release_containers: frozenset[str] = frozenset()
    relation_containers: frozenset[str] = frozenset()

    @property
    def record_bytes(self) -> bytes:
        return _atlas_record_bytes(self.record)

    @property
    def digest(self) -> str:
        return _digest_bytes(self.record_bytes)

    @property
    def identifier(self) -> str:
        return "urn:ref:vocabulary-atlas-record:" + self.digest.removeprefix("sha256:")


class _CanonicalRecordSet:
    """Deduplicate only byte-identical records and merge exact containment."""

    def __init__(self) -> None:
        self._records: dict[str, _CanonicalAtlasRecord] = {}

    def add(
        self,
        value: Mapping[str, Any],
        *,
        role: str,
        in_release: str | None = None,
        in_relation_bundle: str | None = None,
    ) -> None:
        if role not in _ROLE_COUNT_FIELD:
            raise VocabularyAtlasError(f"unsupported canonical record role {role!r}")
        if in_release is not None and in_relation_bundle is not None:
            raise VocabularyAtlasError("one atlas record cannot cross container kinds")
        expected_container = _CHILD_ROLE_CONTAINMENT.get(role)
        actual_container = (
            "release" if in_release is not None else "relationBundle" if in_relation_bundle is not None else None
        )
        if expected_container != actual_container:
            raise VocabularyAtlasError(f"atlas {role} record containment differs from its role")
        plain = cast(Mapping[str, Any], _plain(value))
        record = _CanonicalAtlasRecord(
            record=cast(Mapping[str, Any], _freeze(plain)),
            role=role,
            release_containers=(
                frozenset({_require_iri(in_release, "atlas release container")})
                if in_release is not None
                else frozenset()
            ),
            relation_containers=(
                frozenset(
                    {
                        _require_iri(
                            in_relation_bundle,
                            "atlas relation-bundle container",
                        )
                    }
                )
                if in_relation_bundle is not None
                else frozenset()
            ),
        )
        identifier = record.identifier
        current = self._records.get(identifier)
        if current is None:
            self._records[identifier] = record
            return
        if current.record != record.record or current.role != role:
            raise VocabularyAtlasError("one canonical atlas record digest has conflicting content or roles")
        self._records[identifier] = _CanonicalAtlasRecord(
            record=current.record,
            role=current.role,
            release_containers=(current.release_containers | record.release_containers),
            relation_containers=(current.relation_containers | record.relation_containers),
        )

    def values(self) -> tuple[_CanonicalAtlasRecord, ...]:
        return tuple(self._records[key] for key in sorted(self._records))


@dataclass(frozen=True, slots=True)
class _ResolvedAtlasScope:
    record: Mapping[str, Any]
    payload: bytes
    snapshots: tuple[AtlasReleaseSnapshot, ...]
    index_rows: Mapping[str, tuple[Mapping[str, Any], ...]]
    relations: tuple[EmbeddedRelationAssertionBundle, ...]


def _atlas_record_bytes(value: Mapping[str, Any]) -> bytes:
    plain = _plain(value)
    _validate_atlas_record_value(plain, path="$")
    return canonical_json(plain).encode("utf-8")


def _validate_atlas_record_value(value: Any, *, path: str) -> None:
    """Validate native record JSON, retaining captured null values exactly."""

    if value is None or isinstance(value, (str, bool)):
        return
    if isinstance(value, int):
        if abs(value) > binding.SAFE_INTEGER:
            raise VocabularyAtlasError(f"{path}: integer exceeds the interoperable JSON range")
        return
    if isinstance(value, float):
        raise VocabularyAtlasError(f"{path}: floating-point numbers are not canonical REF JSON")
    if isinstance(value, Mapping):
        for key, child in value.items():
            if not isinstance(key, str):
                raise VocabularyAtlasError(f"{path}: object keys must be strings")
            _validate_atlas_record_value(child, path=f"{path}.{key}")
        return
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        for index, child in enumerate(value):
            _validate_atlas_record_value(child, path=f"{path}[{index}]")
        return
    raise VocabularyAtlasError(f"{path}: unsupported canonical record value {type(value).__name__}")


def _atlas_record_identifier(value: Mapping[str, Any]) -> str:
    digest = _digest_bytes(_atlas_record_bytes(value))
    return "urn:ref:vocabulary-atlas-record:" + digest.removeprefix("sha256:")


def _native_record_id(value: Mapping[str, Any]) -> str | None:
    native_id = value.get("id")
    jsonld_id = value.get("@id")
    if isinstance(native_id, str) and isinstance(jsonld_id, str) and native_id != jsonld_id:
        raise VocabularyAtlasError("atlas native record carries conflicting id and @id identities")
    if "id" in value:
        if isinstance(native_id, str) and _ABSOLUTE_IRI.fullmatch(native_id):
            return native_id
        return None
    if isinstance(jsonld_id, str) and _ABSOLUTE_IRI.fullmatch(jsonld_id):
        return jsonld_id
    return None


def _snapshot_release_records(
    snapshot: AtlasReleaseSnapshot,
) -> tuple[Mapping[str, Any], ...]:
    """Return non-concept native records carried by one release snapshot."""

    excluded = {
        "type",
        "schemaVersion",
        "id",
        "contentDigest",
        "releasePin",
        "concepts",
        "members",
    }
    rows: list[Mapping[str, Any]] = []
    for key, value in snapshot.record.items():
        if key in excluded:
            continue
        if isinstance(value, Mapping):
            rows.append(value)
            continue
        if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
            if not all(isinstance(item, Mapping) for item in value):
                raise VocabularyAtlasError(f"atlas release snapshot {key} must contain native records")
            rows.extend(cast(Sequence[Mapping[str, Any]], value))
            continue
        raise VocabularyAtlasError(f"atlas release snapshot {key} is not a native record or record array")
    return tuple(rows)


def _resolved_index_rows(
    *,
    scope_record: Mapping[str, Any],
    index: Mapping[str, Any],
) -> Mapping[str, tuple[Mapping[str, Any], ...]]:
    raw_rows = index.get("rows")
    if not isinstance(raw_rows, Sequence) or isinstance(raw_rows, (str, bytes)):
        raise VocabularyAtlasError("pinned atlas index rows must be an array")
    rows: dict[str, Mapping[str, Any]] = {}
    for position, value in enumerate(raw_rows):
        if not isinstance(value, Mapping):
            raise VocabularyAtlasError(f"pinned atlas index rows[{position}] must be an object")
        row_id = _require_iri(value.get("rowId"), f"pinned atlas index rows[{position}].rowId")
        if row_id in rows:
            raise VocabularyAtlasError("pinned atlas index repeats a rowId")
        row_digest = _require_digest(
            value.get("rowDigest"),
            f"pinned atlas index rows[{position}].rowDigest",
        )
        basis = {key: _plain(item) for key, item in value.items() if key not in {"rowId", "rowDigest"}}
        if binding.canonical_sha256(basis) != row_digest:
            raise VocabularyAtlasError("pinned atlas index rowDigest is stale")
        if row_id != "urn:ref:atlas-index-row:" + row_digest.removeprefix("sha256:"):
            raise VocabularyAtlasError("pinned atlas index rowId is stale")
        rows[row_id] = cast(Mapping[str, Any], _freeze(_plain(value)))

    resolved: dict[str, tuple[Mapping[str, Any], ...]] = {}
    used: set[str] = set()
    for position, release in enumerate(cast(Sequence[Mapping[str, Any]], scope_record["releases"])):
        release_id = cast(str, release["releaseId"])
        values: list[Mapping[str, Any]] = []
        for reference in cast(Sequence[Mapping[str, Any]], release["atlasIndexRows"]):
            row_id = cast(str, reference["rowId"])
            row = rows.get(row_id)
            if row is None:
                raise VocabularyAtlasError("atlas scope index-row reference is absent from the pinned index")
            if row.get("rowDigest") != reference.get("rowDigest"):
                raise VocabularyAtlasError("atlas scope index-row digest differs from the pinned index")
            release_pin = row.get("release")
            if (
                not isinstance(release_pin, Mapping)
                or release_pin.get("releaseId") != release_id
                or release_pin.get("manifestDigest") != release.get("manifestDigest")
                or row.get("semanticRing") != release.get("semanticRing")
            ):
                raise VocabularyAtlasError("resolved atlas index row differs from its exact scope release")
            if row_id in used:
                raise VocabularyAtlasError("one atlas index row cannot classify two scoped releases")
            used.add(row_id)
            values.append(row)
        if not values:
            raise VocabularyAtlasError(f"atlas scope releases[{position}] has no resolved index row")
        resolved[release_id] = tuple(values)
    return cast(Mapping[str, tuple[Mapping[str, Any], ...]], _freeze(resolved))


def _resolve_atlas_scope(scope: PinnedVocabularyAtlasScope) -> _ResolvedAtlasScope:
    if not isinstance(scope, PinnedVocabularyAtlasScope):
        raise VocabularyAtlasError("build_vocabulary_atlas requires one PinnedVocabularyAtlasScope")
    try:
        verified = scope.verified_scope()
        scope_record = verified.as_record()
        scope_payload = verified.artifact_bytes()
        if _digest_bytes(scope_payload) != scope.file_digest:
            raise VocabularyAtlasError("atlas scope canonical bytes differ from the pinned file")
        index = verified.atlas_index.verified_index()
        index_rows = _resolved_index_rows(
            scope_record=scope_record,
            index=index,
        )
        snapshots = tuple(AtlasReleaseSnapshot.create(release) for release in verified.releases)
        memberships = {snapshot.release_id: snapshot.member_ids for snapshot in snapshots}
        relations: list[EmbeddedRelationAssertionBundle] = []
        for pinned in verified.relation_bundles:
            bundle = pinned.verified_bundle()
            relations.append(
                EmbeddedRelationAssertionBundle.from_record(
                    bundle.as_record(),
                    release_memberships={
                        cast(str, release_pin["releaseId"]): memberships[cast(str, release_pin["releaseId"])]
                        for release_pin in bundle.release_pins
                    },
                )
            )
    except (
        AtlasIndexError,
        AtlasReleaseSnapshotError,
        AtlasScopeError,
        KeyError,
        RelationAssertionError,
    ) as error:
        if isinstance(error, VocabularyAtlasError):
            raise
        raise VocabularyAtlasError(str(error)) from error
    return _ResolvedAtlasScope(
        record=cast(Mapping[str, Any], _freeze(scope_record)),
        payload=scope_payload,
        snapshots=snapshots,
        index_rows=index_rows,
        relations=tuple(relations),
    )


def _concept_identity(value: Mapping[str, Any]) -> str:
    identifier = value.get("id", value.get("@id"))
    return _require_iri(identifier, "atlas concept identity")


def _scope_record_set(resolved: _ResolvedAtlasScope) -> _CanonicalRecordSet:
    records = _CanonicalRecordSet()
    concept_rings: dict[str, SemanticRing] = {}
    for snapshot in resolved.snapshots:
        records.add(snapshot.as_record(), role="conceptRelease")
        for concept in snapshot.concept_records:
            identity = _concept_identity(concept)
            previous = concept_rings.setdefault(identity, snapshot.semantic_ring)
            if previous != snapshot.semantic_ring:
                raise VocabularyAtlasError("one concept identity cannot belong to two semantic rings")
            records.add(
                concept,
                role="concept",
                in_release=snapshot.release_id,
            )
        for row in _snapshot_release_records(snapshot):
            records.add(
                row,
                role="releaseRecord",
                in_release=snapshot.release_id,
            )
        for row in resolved.index_rows[snapshot.release_id]:
            records.add(
                row,
                role="releaseRecord",
                in_release=snapshot.release_id,
            )

    for bundle in resolved.relations:
        records.add(bundle.as_record(), role="relationBundle")
        for evidence in bundle.evidence_assertions:
            records.add(
                evidence.as_record(),
                role="evidenceAssertion",
                in_relation_bundle=bundle.identifier,
            )
        for mapping in bundle.mapping_assertions:
            records.add(
                mapping.as_record(),
                role="mappingAssertion",
                in_relation_bundle=bundle.identifier,
            )
        for proof in bundle.machine_proof_pins:
            records.add(
                proof,
                role="machineProof",
                in_relation_bundle=bundle.identifier,
            )
    return records


def _record_dataset(
    records: Sequence[_CanonicalAtlasRecord],
    *,
    asset_id: str,
) -> tuple[bytes, Mapping[str, int]]:
    release_graph_id = asset_id + ":release-facts"
    cross_graph_id = asset_id + ":cross-release"
    dataset = Dataset(default_union=False)
    release_graph = dataset.graph(URIRef(release_graph_id))
    cross_graph = dataset.graph(URIRef(cross_graph_id))
    counts = {field: 0 for field in _COUNT_FIELDS_V2}
    for record in records:
        graph = release_graph if record.role in _RELEASE_GRAPH_ROLES else cross_graph
        node = URIRef(record.identifier)
        graph.add((node, RDF.type, ATLAS.CanonicalRecord))
        graph.add((node, ATLAS.recordRole, ATLAS[record.role]))
        graph.add((node, ATLAS.recordDigest, RdfLiteral(record.digest)))
        graph.add(
            (
                node,
                ATLAS.canonicalJson,
                RdfLiteral(
                    record.record_bytes.decode("utf-8"),
                    datatype=RDF.JSON,
                ),
            )
        )
        native_id = _native_record_id(record.record)
        if native_id is not None:
            graph.add((node, ATLAS.recordId, URIRef(native_id)))
        for release in sorted(record.release_containers):
            graph.add((node, ATLAS.inRelease, URIRef(release)))
        for bundle in sorted(record.relation_containers):
            graph.add((node, ATLAS.inRelationBundle, URIRef(bundle)))
        counts[_ROLE_COUNT_FIELD[record.role]] += 1
    payload = _canonical_nquads(dataset)
    graph_counts = {
        "releaseFacts": len(release_graph),
        "crossRelease": len(cross_graph),
    }
    return payload, cast(Mapping[str, int], {**counts, **graph_counts})


def _implementation_pin_v2() -> dict[str, Any]:
    package_root = Path(__file__).parents[1]
    sources = [
        {
            "path": f"refspec/{relative}",
            "digest": _digest_bytes((package_root / relative).read_bytes()),
        }
        for relative in _IMPLEMENTATION_SOURCE_PATHS
    ]
    return {
        "id": "urn:ref:implementation:vocabulary-atlas:2.0",
        "version": "2.0",
        "sourceModules": sources,
        "runtime": {
            "jsonschemaVersion": importlib.metadata.version("jsonschema"),
            "pyarrowVersion": importlib.metadata.version("pyarrow"),
            "pythonRequirement": ">=3.10",
            "pythonVersion": platform.python_version(),
            "rdflibVersion": importlib.metadata.version("rdflib"),
        },
    }


def _scope_descriptor(resolved: _ResolvedAtlasScope) -> dict[str, Any]:
    return {
        "role": "VocabularyAtlasScope",
        "path": SCOPE_FILE,
        "mediaType": _SCOPE_MEDIA_TYPE,
        "id": cast(str, resolved.record["id"]),
        "contentDigest": cast(str, resolved.record["contentDigest"]),
        "fileDigest": _digest_bytes(resolved.payload),
        "byteLength": len(resolved.payload),
    }


def _ring_summaries(
    records: Sequence[_CanonicalAtlasRecord],
    *,
    snapshots: Sequence[AtlasReleaseSnapshot],
    relations: Sequence[EmbeddedRelationAssertionBundle],
) -> list[dict[str, Any]]:
    release_rings = {snapshot.release_id: snapshot.semantic_ring for snapshot in snapshots}
    bundle_rings = {bundle.identifier: bundle.semantic_ring for bundle in relations}
    values: dict[SemanticRing, dict[str, set[str]]] = {
        ring: {
            "release": set(),
            "concept": set(),
            "bundle": set(),
            "mapping": set(),
        }
        for ring in _RING_ORDER
    }
    for record in records:
        if record.role == "conceptRelease":
            snapshot = AtlasReleaseSnapshot.from_record(record.record)
            values[snapshot.semantic_ring]["release"].add(record.identifier)
        elif record.role == "concept":
            rings = {release_rings[value] for value in record.release_containers}
            if len(rings) != 1:
                raise VocabularyAtlasError("one canonical concept record cannot cross semantic rings")
            values[rings.pop()]["concept"].add(record.identifier)
        elif record.role == "relationBundle":
            bundle = EmbeddedRelationAssertionBundle.from_record(record.record)
            values[bundle.semantic_ring]["bundle"].add(record.identifier)
        elif record.role == "mappingAssertion":
            rings = {bundle_rings[value] for value in record.relation_containers}
            if len(rings) != 1:
                raise VocabularyAtlasError("one mapping assertion record cannot cross semantic rings")
            values[rings.pop()]["mapping"].add(record.identifier)
    return [
        {
            "semanticRing": ring,
            "releaseCount": len(values[ring]["release"]),
            "conceptCount": len(values[ring]["concept"]),
            "relationBundleCount": len(values[ring]["bundle"]),
            "mappingAssertionCount": len(values[ring]["mapping"]),
        }
        for ring in _RING_ORDER
    ]


def _build_resolved_atlas_v2(resolved: _ResolvedAtlasScope) -> VocabularyAtlasAsset:
    implementation = _implementation_pin_v2()
    scope_descriptor = _scope_descriptor(resolved)
    generation_basis = {
        "format": FORMAT_ID,
        "scope": scope_descriptor,
        "implementation": implementation,
        "policies": dict(_POLICIES),
    }
    generation_digest = _digest_value(generation_basis)
    asset_id = "urn:ref:vocabulary-atlas:" + generation_digest.removeprefix("sha256:")
    record_set = _scope_record_set(resolved)
    records = record_set.values()
    payload, observed = _record_dataset(records, asset_id=asset_id)
    counts = {field: observed[field] for field in _COUNT_FIELDS_V2}
    graphs = [
        {
            "role": "releaseFacts",
            "id": asset_id + ":release-facts",
            "quadCount": observed["releaseFacts"],
        },
        {
            "role": "crossRelease",
            "id": asset_id + ":cross-release",
            "quadCount": observed["crossRelease"],
        },
    ]
    manifest: dict[str, Any] = {
        "id": asset_id,
        "type": "urn:ref:type:VocabularyAtlasManifest",
        "schemaVersion": SCHEMA_VERSION,
        "format": FORMAT_ID,
        "generationDigest": generation_digest,
        "scope": scope_descriptor,
        "implementation": implementation,
        "policies": dict(_POLICIES),
        "graphs": graphs,
        "output": {
            "path": ATLAS_FILE,
            "mediaType": "application/n-quads",
            "digest": _digest_bytes(payload),
            "byteLength": len(payload),
            "quadCount": observed["releaseFacts"] + observed["crossRelease"],
        },
        "counts": counts,
        "rings": _ring_summaries(
            records,
            snapshots=resolved.snapshots,
            relations=resolved.relations,
        ),
    }
    manifest["canonicalPayloadDigest"] = _manifest_digest(manifest)
    return VocabularyAtlasAsset._verified(
        payload=payload,
        scope_payload=resolved.payload,
        manifest=cast(Mapping[str, Any], _freeze(manifest)),
    )


def _read_distribution(directory: Path | str) -> tuple[Path, dict[str, bytes]]:
    root = Path(directory)
    if root.is_symlink():
        raise VocabularyAtlasError("atlas directory must not be a symlink")
    try:
        root = root.resolve(strict=True)
    except FileNotFoundError as error:
        raise VocabularyAtlasError("atlas directory does not exist") from error
    if not root.is_dir():
        raise VocabularyAtlasError("atlas path must be a directory")
    expected = {ATLAS_FILE, MANIFEST_FILE, SCOPE_FILE}
    entries = {item.name: item for item in root.iterdir()}
    if set(entries) != expected:
        raise VocabularyAtlasError("atlas distribution file set differs from 2.0")
    if any(item.is_symlink() or not item.is_file() for item in entries.values()):
        raise VocabularyAtlasError("atlas distribution must contain three regular files and no symlinks")
    payloads = {name: entries[name].read_bytes() for name in expected}
    final_entries = {item.name: item for item in root.iterdir()}
    if (
        set(final_entries) != expected
        or any(item.is_symlink() or not item.is_file() for item in final_entries.values())
        or any(final_entries[name].read_bytes() != payloads[name] for name in expected)
    ):
        raise VocabularyAtlasError("atlas distribution changed while opening")
    return root, payloads


def _require_v2_count(value: object, label: str, *, positive: bool = False) -> int:
    if (
        not isinstance(value, int)
        or isinstance(value, bool)
        or value < (1 if positive else 0)
        or value > binding.SAFE_INTEGER
    ):
        qualifier = "positive" if positive else "non-negative"
        raise VocabularyAtlasError(f"{label} must be a {qualifier} safe integer")
    return value


def _validate_implementation_v2(candidate: object) -> Mapping[str, Any]:
    row = _as_mapping(candidate, "atlas implementation")
    if set(row) != {"id", "version", "sourceModules", "runtime"}:
        raise VocabularyAtlasError("atlas implementation fields differ from 2.0")
    _require_iri(row.get("id"), "atlas implementation id")
    _require_text(row.get("version"), "atlas implementation version")
    sources = _as_sequence(row.get("sourceModules"), "atlas implementation sourceModules")
    if not sources:
        raise VocabularyAtlasError("atlas implementation sourceModules must not be empty")
    paths: list[str] = []
    for position, value in enumerate(sources):
        source = _as_mapping(value, f"atlas implementation sourceModules[{position}]")
        if set(source) != {"path", "digest"}:
            raise VocabularyAtlasError("atlas implementation source-module fields differ")
        path = _require_text(source.get("path"), "atlas implementation source-module path")
        if Path(path).is_absolute() or ".." in Path(path).parts:
            raise VocabularyAtlasError("atlas implementation source-module path is unsafe")
        _require_digest(source.get("digest"), "atlas implementation source-module digest")
        paths.append(path)
    if paths != sorted(paths) or len(set(paths)) != len(paths):
        raise VocabularyAtlasError("atlas implementation sourceModules are not unique and ordered")
    runtime = _as_mapping(row.get("runtime"), "atlas implementation runtime")
    if not runtime or any(
        not isinstance(key, str) or not key or not isinstance(item, str) or not item for key, item in runtime.items()
    ):
        raise VocabularyAtlasError("atlas implementation runtime is invalid")
    return row


def _parse_canonical_record(value: str) -> Mapping[str, Any]:
    try:
        decoded = json.loads(
            value,
            object_pairs_hook=binding.reject_duplicate_keys,
            parse_constant=binding.reject_nonfinite_constant,
        )
    except (json.JSONDecodeError, ValueError) as error:
        raise VocabularyAtlasError("atlas canonicalJson is not valid canonical REF JSON") from error
    if not isinstance(decoded, Mapping):
        raise VocabularyAtlasError("atlas canonicalJson record must be an object")
    if _atlas_record_bytes(decoded) != value.encode("utf-8"):
        raise VocabularyAtlasError("atlas canonicalJson bytes are not canonical")
    return cast(Mapping[str, Any], decoded)


def _one_object(values: Mapping[URIRef, Sequence[Any]], predicate: URIRef, label: str) -> Any:
    found = tuple(values.get(predicate, ()))
    if len(found) != 1:
        raise VocabularyAtlasError(f"atlas record must have exactly one {label}")
    return found[0]


def _decode_record_dataset(
    payload: bytes,
    *,
    asset_id: str,
) -> tuple[_CanonicalAtlasRecord, ...]:
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as error:
        raise VocabularyAtlasError("atlas N-Quads is not valid UTF-8") from error
    dataset = Dataset(default_union=False)
    try:
        dataset.parse(data=text, format="nquads")
    except Exception as error:  # rdflib exposes parser-specific subclasses
        raise VocabularyAtlasError("atlas output is not valid N-Quads") from error
    if any(
        isinstance(term, BNode)
        for subject, predicate, object_, context in dataset.quads((None, None, None, None))
        for term in (subject, predicate, object_, context)
    ):
        raise VocabularyAtlasError("atlas output contains a blank node")
    if _canonical_nquads(dataset) != payload:
        raise VocabularyAtlasError("atlas N-Quads bytes are not canonical")

    graph_roles = {
        asset_id + ":release-facts": _RELEASE_GRAPH_ROLES,
        asset_id + ":cross-release": _CROSS_RELEASE_GRAPH_ROLES,
    }
    grouped: dict[tuple[str, URIRef], dict[URIRef, list[Any]]] = defaultdict(lambda: defaultdict(list))
    for subject, predicate, object_, context in dataset.quads((None, None, None, None)):
        graph_id = str(context)
        if graph_id not in graph_roles:
            raise VocabularyAtlasError("atlas N-Quads named graphs differ")
        if not isinstance(subject, URIRef) or not isinstance(predicate, URIRef):
            raise VocabularyAtlasError("atlas exact index requires IRI subjects and predicates")
        grouped[(graph_id, subject)][predicate].append(object_)

    records = _CanonicalRecordSet()
    for (graph_id, node), values in grouped.items():
        if not set(values) <= _RECORD_PREDICATES:
            raise VocabularyAtlasError("atlas exact record index has an extra predicate")
        type_value = _one_object(values, RDF.type, "rdf:type")
        if type_value != ATLAS.CanonicalRecord:
            raise VocabularyAtlasError("atlas record rdf:type differs")
        role_value = _one_object(values, ATLAS.recordRole, "recordRole")
        if not isinstance(role_value, URIRef) or not str(role_value).startswith(str(ATLAS)):
            raise VocabularyAtlasError("atlas recordRole is invalid")
        role = str(role_value).removeprefix(str(ATLAS))
        if role not in graph_roles[graph_id]:
            raise VocabularyAtlasError("atlas record role is in the wrong named graph")
        digest_value = _one_object(values, ATLAS.recordDigest, "recordDigest")
        if (
            not isinstance(digest_value, RdfLiteral)
            or digest_value.datatype is not None
            or digest_value.language is not None
        ):
            raise VocabularyAtlasError("atlas recordDigest must be a plain literal")
        digest = _require_digest(str(digest_value), "atlas recordDigest")
        json_value = _one_object(values, ATLAS.canonicalJson, "canonicalJson")
        if not isinstance(json_value, RdfLiteral) or json_value.datatype != RDF.JSON:
            raise VocabularyAtlasError("atlas canonicalJson must be an rdf:JSON literal")
        record = _parse_canonical_record(str(json_value))
        if _digest_bytes(_atlas_record_bytes(record)) != digest:
            raise VocabularyAtlasError("atlas recordDigest differs from canonicalJson")
        if str(node) != "urn:ref:vocabulary-atlas-record:" + digest.removeprefix("sha256:"):
            raise VocabularyAtlasError("atlas record IRI differs from recordDigest")

        record_ids = tuple(values.get(ATLAS.recordId, ()))
        expected_record_id = _native_record_id(record)
        if expected_record_id is None:
            if record_ids:
                raise VocabularyAtlasError("atlas recordId is not derived from native id")
        elif record_ids != (URIRef(expected_record_id),):
            raise VocabularyAtlasError("atlas recordId differs from native id")

        release_containers = tuple(values.get(ATLAS.inRelease, ()))
        relation_containers = tuple(values.get(ATLAS.inRelationBundle, ()))
        if any(not isinstance(value, URIRef) for value in (*release_containers, *relation_containers)):
            raise VocabularyAtlasError("atlas record containment must use IRIs")
        expected = _CHILD_ROLE_CONTAINMENT.get(role)
        if expected == "release" and (not release_containers or relation_containers):
            raise VocabularyAtlasError("atlas release child containment differs")
        if expected == "relationBundle" and (not relation_containers or release_containers):
            raise VocabularyAtlasError("atlas relation child containment differs")
        if expected is None and (release_containers or relation_containers):
            raise VocabularyAtlasError("atlas top-level record points to itself or a container")
        for value in release_containers:
            records.add(record, role=role, in_release=str(value))
        for value in relation_containers:
            records.add(record, role=role, in_relation_bundle=str(value))
        if not release_containers and not relation_containers:
            records.add(record, role=role)

    result = records.values()
    rebuilt, _ = _record_dataset(result, asset_id=asset_id)
    if rebuilt != payload:
        raise VocabularyAtlasError("atlas derived exact-equality index is incomplete")
    return result


def _record_ids_for_container(
    records: Sequence[_CanonicalAtlasRecord],
    *,
    role: str,
    release: str | None = None,
    relation_bundle: str | None = None,
) -> frozenset[str]:
    return frozenset(
        record.identifier
        for record in records
        if record.role == role
        and (release is None or release in record.release_containers)
        and (relation_bundle is None or relation_bundle in record.relation_containers)
    )


def _validate_embedded_scope_records(
    records: Sequence[_CanonicalAtlasRecord],
    *,
    scope_record: Mapping[str, Any],
) -> tuple[
    tuple[AtlasReleaseSnapshot, ...],
    tuple[EmbeddedRelationAssertionBundle, ...],
]:
    release_records = [record for record in records if record.role == "conceptRelease"]
    snapshots = tuple(AtlasReleaseSnapshot.from_record(record.record) for record in release_records)
    snapshots_by_release = {snapshot.release_id: snapshot for snapshot in snapshots}
    if len(snapshots_by_release) != len(snapshots):
        raise VocabularyAtlasError("atlas repeats a concept release")
    scope_releases = {
        cast(str, row["releaseId"]): row for row in cast(Sequence[Mapping[str, Any]], scope_record["releases"])
    }
    if set(snapshots_by_release) != set(scope_releases):
        raise VocabularyAtlasError("atlas concept releases differ from its exact scope")

    memberships: dict[str, frozenset[str]] = {}
    for release_id, snapshot in snapshots_by_release.items():
        scope_pin = {key: _plain(value) for key, value in scope_releases[release_id].items() if key != "atlasIndexRows"}
        if _plain(snapshot.release_pin) != scope_pin:
            raise VocabularyAtlasError("atlas concept release pin differs from its exact scope")
        memberships[release_id] = snapshot.member_ids
        expected_concepts = {_atlas_record_identifier(value) for value in snapshot.concept_records}
        if _record_ids_for_container(records, role="concept", release=release_id) != expected_concepts:
            raise VocabularyAtlasError("atlas release-scoped concept records differ from its snapshot")

        refs = {
            cast(str, value["rowId"]): cast(str, value["rowDigest"])
            for value in cast(
                Sequence[Mapping[str, Any]],
                scope_releases[release_id]["atlasIndexRows"],
            )
        }
        resolved_index_rows: list[Mapping[str, Any]] = []
        for record in records:
            if record.role != "releaseRecord" or release_id not in record.release_containers:
                continue
            row_id = record.record.get("rowId")
            if not isinstance(row_id, str) or row_id not in refs:
                continue
            row_digest = refs[row_id]
            if record.record.get("rowDigest") != row_digest:
                raise VocabularyAtlasError("atlas resolved index row differs from the scope reference")
            basis = {key: _plain(value) for key, value in record.record.items() if key not in {"rowId", "rowDigest"}}
            if binding.canonical_sha256(
                basis
            ) != row_digest or row_id != "urn:ref:atlas-index-row:" + row_digest.removeprefix("sha256:"):
                raise VocabularyAtlasError("atlas resolved index-row identity is stale")
            indexed_release = record.record.get("release")
            if (
                not isinstance(indexed_release, Mapping)
                or indexed_release.get("releaseId") != release_id
                or indexed_release.get("manifestDigest") != scope_pin.get("manifestDigest")
                or record.record.get("semanticRing") != scope_pin.get("semanticRing")
            ):
                raise VocabularyAtlasError("atlas resolved index row differs from its scope release")
            resolved_index_rows.append(record.record)
        if {cast(str, value["rowId"]) for value in resolved_index_rows} != set(refs):
            raise VocabularyAtlasError("atlas does not resolve every selected index-row fact")
        classifications = {
            (
                value.get("semanticRing"),
                value.get("atlasParticipation"),
                value.get("sourceModule"),
                value.get("resourceId"),
            )
            for value in resolved_index_rows
        }
        if len(classifications) != 1:
            raise VocabularyAtlasError("atlas selected index rows conflict on release classification")
        expected_release_records = {
            _atlas_record_identifier(value)
            for value in (
                *_snapshot_release_records(snapshot),
                *resolved_index_rows,
            )
        }
        if _record_ids_for_container(records, role="releaseRecord", release=release_id) != expected_release_records:
            raise VocabularyAtlasError("atlas release records differ from its snapshot and selected index rows")

    relation_records = [record for record in records if record.role == "relationBundle"]
    relations = tuple(
        EmbeddedRelationAssertionBundle.from_record(
            record.record,
            release_memberships={
                cast(str, pin["releaseId"]): memberships[cast(str, pin["releaseId"])]
                for pin in cast(Sequence[Mapping[str, Any]], record.record["releasePins"])
            },
        )
        for record in relation_records
    )
    relations_by_id = {relation.identifier: relation for relation in relations}
    if len(relations_by_id) != len(relations):
        raise VocabularyAtlasError("atlas repeats a relation bundle")
    scope_relations = {
        cast(str, row["id"]): row for row in cast(Sequence[Mapping[str, Any]], scope_record["relationBundles"])
    }
    if set(relations_by_id) != set(scope_relations):
        raise VocabularyAtlasError("atlas relation bundles differ from its exact scope")
    for bundle_id, relation in relations_by_id.items():
        pin = scope_relations[bundle_id]
        if pin.get("semanticRing") != relation.semantic_ring or pin.get("contentDigest") != relation.content_digest:
            raise VocabularyAtlasError("atlas relation bundle differs from its exact scope pin")
        expected_by_role = {
            "evidenceAssertion": {
                _atlas_record_identifier(value.as_record()) for value in relation.evidence_assertions
            },
            "mappingAssertion": {_atlas_record_identifier(value.as_record()) for value in relation.mapping_assertions},
            "machineProof": {_atlas_record_identifier(value) for value in relation.machine_proof_pins},
        }
        for role, expected in expected_by_role.items():
            if _record_ids_for_container(records, role=role, relation_bundle=bundle_id) != expected:
                raise VocabularyAtlasError(f"atlas {role} records differ from their relation bundle")
    return snapshots, relations


def _validate_manifest_v2(
    manifest: Mapping[str, Any],
    *,
    scope_payload: bytes,
    payload: bytes,
) -> tuple[tuple[AtlasReleaseSnapshot, ...], tuple[EmbeddedRelationAssertionBundle, ...]]:
    if set(manifest) != _MANIFEST_FIELDS_V2:
        raise VocabularyAtlasError("atlas manifest fields differ from 2.0")
    if (
        manifest.get("type") != "urn:ref:type:VocabularyAtlasManifest"
        or manifest.get("schemaVersion") != SCHEMA_VERSION
        or manifest.get("format") != FORMAT_ID
    ):
        raise VocabularyAtlasError("atlas manifest version or format differs")
    generation_digest = _require_digest(manifest.get("generationDigest"), "atlas generationDigest")
    asset_id = _require_iri(manifest.get("id"), "atlas id")
    if asset_id != "urn:ref:vocabulary-atlas:" + generation_digest.removeprefix("sha256:"):
        raise VocabularyAtlasError("atlas id differs from generationDigest")
    if manifest.get("canonicalPayloadDigest") != _manifest_digest(manifest):
        raise VocabularyAtlasError("atlas manifest canonicalPayloadDigest differs")
    if manifest.get("policies") != dict(_POLICIES):
        raise VocabularyAtlasError("atlas policies differ from 2.0")
    implementation = _validate_implementation_v2(manifest.get("implementation"))

    scope = _as_mapping(manifest.get("scope"), "atlas scope descriptor")
    if set(scope) != {
        "role",
        "path",
        "mediaType",
        "id",
        "contentDigest",
        "fileDigest",
        "byteLength",
    }:
        raise VocabularyAtlasError("atlas scope descriptor fields differ")
    if (
        scope.get("role") != "VocabularyAtlasScope"
        or scope.get("path") != SCOPE_FILE
        or scope.get("mediaType") != _SCOPE_MEDIA_TYPE
    ):
        raise VocabularyAtlasError("atlas scope descriptor differs")
    _require_iri(scope.get("id"), "atlas scope id")
    _require_digest(scope.get("contentDigest"), "atlas scope contentDigest")
    if scope.get("fileDigest") != _digest_bytes(scope_payload):
        raise VocabularyAtlasError("atlas scope file digest differs")
    if scope.get("byteLength") != len(scope_payload):
        raise VocabularyAtlasError("atlas scope byteLength differs")
    try:
        scope_record = _load_json_object(scope_payload, "atlas scope")
        if _canonical_bytes(scope_record) != scope_payload:
            raise VocabularyAtlasError("atlas scope bytes are not canonical")
        scope_record = validate_atlas_scope_record(scope_record)
    except AtlasScopeError as error:
        raise VocabularyAtlasError(str(error)) from error
    if scope.get("id") != scope_record.get("id") or scope.get("contentDigest") != scope_record.get("contentDigest"):
        raise VocabularyAtlasError("atlas scope identity differs from its file")

    generation_basis = {
        "format": FORMAT_ID,
        "scope": _plain(scope),
        "implementation": _plain(implementation),
        "policies": dict(_POLICIES),
    }
    if _digest_value(generation_basis) != generation_digest:
        raise VocabularyAtlasError("atlas generationDigest differs")

    graph_rows = _as_sequence(manifest.get("graphs"), "atlas graphs")
    expected_graphs = (
        ("releaseFacts", asset_id + ":release-facts", True),
        ("crossRelease", asset_id + ":cross-release", False),
    )
    if len(graph_rows) != len(expected_graphs):
        raise VocabularyAtlasError("atlas must declare exactly two named graphs")
    for position, (role, identifier, positive) in enumerate(expected_graphs):
        row = _as_mapping(graph_rows[position], f"atlas graphs[{position}]")
        if set(row) != {"role", "id", "quadCount"}:
            raise VocabularyAtlasError("atlas graph fields differ from 2.0")
        if row.get("role") != role or row.get("id") != identifier:
            raise VocabularyAtlasError("atlas graph role or id differs")
        _require_v2_count(row.get("quadCount"), f"atlas {role} quadCount", positive=positive)

    output = _as_mapping(manifest.get("output"), "atlas output")
    if set(output) != {"path", "mediaType", "digest", "byteLength", "quadCount"}:
        raise VocabularyAtlasError("atlas output fields differ from 2.0")
    if output.get("path") != ATLAS_FILE or output.get("mediaType") != "application/n-quads":
        raise VocabularyAtlasError("atlas output descriptor differs")
    if output.get("digest") != _digest_bytes(payload):
        raise VocabularyAtlasError("atlas output digest differs")
    if output.get("byteLength") != len(payload):
        raise VocabularyAtlasError("atlas output byteLength differs")
    _require_v2_count(output.get("quadCount"), "atlas output quadCount", positive=True)

    records = _decode_record_dataset(payload, asset_id=asset_id)
    observed_role_counts = {
        count_field: sum(record.role == role for record in records) for role, count_field in _ROLE_COUNT_FIELD.items()
    }
    counts = _as_mapping(manifest.get("counts"), "atlas counts")
    if set(counts) != _COUNT_FIELDS_V2:
        raise VocabularyAtlasError("atlas count fields differ from 2.0")
    for field in _COUNT_FIELDS_V2:
        _require_v2_count(
            counts.get(field),
            f"atlas counts.{field}",
            positive=field in {"conceptReleases", "concepts", "releaseRecords"},
        )
    if dict(counts) != observed_role_counts:
        raise VocabularyAtlasError("atlas record counts differ")

    dataset = Dataset(default_union=False)
    dataset.parse(data=payload.decode("utf-8"), format="nquads")
    graph_counts = {role: len(dataset.graph(URIRef(identifier))) for role, identifier, _ in expected_graphs}
    for position, (role, _, _) in enumerate(expected_graphs):
        if cast(Mapping[str, Any], graph_rows[position]).get("quadCount") != graph_counts[role]:
            raise VocabularyAtlasError("atlas graph quadCount differs")
    if output.get("quadCount") != sum(graph_counts.values()):
        raise VocabularyAtlasError("atlas output quadCount differs")

    snapshots, relations = _validate_embedded_scope_records(
        records,
        scope_record=scope_record,
    )
    expected_rings = _ring_summaries(
        records,
        snapshots=snapshots,
        relations=relations,
    )
    if manifest.get("rings") != expected_rings:
        raise VocabularyAtlasError("atlas ring summaries differ")
    return snapshots, relations


_ASSET_CONSTRUCTION_TOKEN_V2 = object()


@dataclass(frozen=True, slots=True, init=False)
class VocabularyAtlasAsset:
    """A file-only verified canonical Atlas 2.0 distribution."""

    payload: bytes
    scope_payload: bytes
    manifest: Mapping[str, Any]
    _verification_token: object

    def __init__(
        self,
        payload: bytes,
        scope_payload: bytes,
        manifest: Mapping[str, Any],
        *,
        _construction_token: object | None = None,
    ) -> None:
        if _construction_token is not _ASSET_CONSTRUCTION_TOKEN_V2:
            raise TypeError(
                "VocabularyAtlasAsset must come from build_vocabulary_atlas() or VocabularyAtlasAsset.open()"
            )
        object.__setattr__(self, "payload", payload)
        object.__setattr__(self, "scope_payload", scope_payload)
        object.__setattr__(self, "manifest", manifest)
        object.__setattr__(self, "_verification_token", _ASSET_CONSTRUCTION_TOKEN_V2)

    @classmethod
    def _verified(
        cls,
        *,
        payload: bytes,
        scope_payload: bytes,
        manifest: Mapping[str, Any],
    ) -> Self:
        return cls(
            payload,
            scope_payload,
            manifest,
            _construction_token=_ASSET_CONSTRUCTION_TOKEN_V2,
        )

    def _require_verified(self) -> None:
        if (
            getattr(self, "_verification_token", None) is not _ASSET_CONSTRUCTION_TOKEN_V2
            or not isinstance(self.payload, bytes)
            or not isinstance(self.scope_payload, bytes)
            or not isinstance(self.manifest, Mapping)
        ):
            raise VocabularyAtlasError("atlas asset is not a verified 2.0 distribution")

    def manifest_bytes(self) -> bytes:
        self._require_verified()
        return _canonical_bytes(_plain(self.manifest))

    @property
    def manifest_digest(self) -> str:
        return _digest_bytes(self.manifest_bytes())

    @property
    def output_digest(self) -> str:
        self._require_verified()
        return _digest_bytes(self.payload)

    @property
    def scope_digest(self) -> str:
        self._require_verified()
        return _digest_bytes(self.scope_payload)

    def write(self, directory: Path | str) -> Path:
        self._require_verified()
        target = Path(directory)
        target.mkdir(parents=True, exist_ok=False)
        (target / ATLAS_FILE).write_bytes(self.payload)
        (target / SCOPE_FILE).write_bytes(self.scope_payload)
        (target / MANIFEST_FILE).write_bytes(self.manifest_bytes())
        return target

    @classmethod
    def open(
        cls,
        directory: Path | str,
        *,
        expected_manifest_digest: str,
    ) -> Self:
        """Verify all three files from one independently trusted manifest pin."""

        _, payloads = _read_distribution(directory)
        digest = _require_digest(expected_manifest_digest, "expected atlas manifest digest")
        manifest_payload = payloads[MANIFEST_FILE]
        if _digest_bytes(manifest_payload) != digest:
            raise VocabularyAtlasError("atlas external manifest digest differs")
        manifest = _load_json_object(manifest_payload, "atlas manifest")
        if _canonical_bytes(manifest) != manifest_payload:
            raise VocabularyAtlasError("atlas manifest bytes are not canonical")
        _validate_manifest_v2(
            manifest,
            scope_payload=payloads[SCOPE_FILE],
            payload=payloads[ATLAS_FILE],
        )
        return cls._verified(
            payload=payloads[ATLAS_FILE],
            scope_payload=payloads[SCOPE_FILE],
            manifest=cast(Mapping[str, Any], _freeze(manifest)),
        )

    @classmethod
    def reproduce_from_scope(
        cls,
        directory: Path | str,
        *,
        scope: PinnedVocabularyAtlasScope,
        expected_manifest_digest: str,
    ) -> Self:
        """Reopen the exact producer scope and rebuild all three files."""

        opened = cls.open(
            directory,
            expected_manifest_digest=expected_manifest_digest,
        )
        resolved = _resolve_atlas_scope(scope)
        if opened.scope_payload != resolved.payload:
            raise VocabularyAtlasError("atlas distribution scope differs from the exact producer scope")
        rebuilt = _build_resolved_atlas_v2(resolved)
        if (
            rebuilt.payload != opened.payload
            or rebuilt.scope_payload != opened.scope_payload
            or rebuilt.manifest != opened.manifest
        ):
            raise VocabularyAtlasError("atlas files do not reproduce from the exact pinned scope")
        return opened


def build_vocabulary_atlas(
    scope: PinnedVocabularyAtlasScope,
) -> VocabularyAtlasAsset:
    """Build Atlas 2.0 from one exact, index-bound, non-authorizing scope."""

    return _build_resolved_atlas_v2(_resolve_atlas_scope(scope))


__all__ = [
    "ATLAS",
    "ATLAS_FILE",
    "FORMAT_ID",
    "MANIFEST_FILE",
    "RKAF",
    "SCHEMA_VERSION",
    "SCOPE_FILE",
    "VocabularyAtlasAsset",
    "VocabularyAtlasError",
    "build_vocabulary_atlas",
    "closed_reference_release_digest",
]
