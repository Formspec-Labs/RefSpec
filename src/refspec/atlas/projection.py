"""Consumer-shaped projections of a vocabulary atlas, as their own kind.

A projection is a **subset of one generated atlas**, chosen by a named policy.
It is not an atlas, and this module exists because binding 1.0 could not say
so.  An atlas manifest's identity is a digest of ``{format, inputs,
implementation, policies}``, and a subset has the same inputs, the same
implementation and the same policies as the generation it came from — so a
projection and its parent carried **one asset identifier**, both opened under
``VocabularyAtlasAsset.open``, and ``reproduce_from_inputs`` refused the
projection with the message reserved for a corrupted atlas.

The fix is a sibling distribution kind rather than an amendment to the atlas
manifest, for three reasons.

*The reproduction contract differs.*  An atlas reproduces from its managed
releases; a projection reproduces from its parent and its keep rule.  Two
incompatible answers to "prove these bytes are what the producer made" cannot
live under one ``type`` without one of them being wrong.

*The atlas manifest field set is closed on both sides.*  Producer and consumer
both compare the key set for exact equality, so there is no such thing as an
optional ``derivedFrom``.  An "amendment" would have to mean *one of two field
sets*, which is a second kind wearing the first kind's name.

*Amending in place would move published identifiers.*  ``atlas/model.py`` is
pinned inside every atlas's own ``implementation`` block, so editing it moves
the asset id of every generated conformance fixture.  A new kind in a new
module changes nothing that already exists — which is the strongest evidence
that the two really are different artifacts.

What a projection publishes that an atlas cannot:

1. ``derivedFrom`` names the parent's asset id **and** both of its digests, so
   the relationship is stated rather than inferred from a digest a consumer
   happened to pin;
2. ``projectionPolicy`` names the exact keep rule and its version, so "what
   was dropped" is a pinned, testable statement instead of a diff; and
3. the asset id is derived from all of it, so a projection can never collide
   with its parent or with a projection under another policy.

Every count a projection declares is re-derived from its own payload, so a
projection is fully checkable from its two files plus its parent's digests.
"""

from __future__ import annotations

import importlib.metadata
import platform
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, cast

from rdflib import Dataset, Graph, URIRef
from rdflib.namespace import PROV, RDF, SKOS
from typing_extensions import Self

# The projection reuses the atlas's own canonicalization, validation and
# identity helpers on purpose: a subset that canonicalized its bytes or
# validated its closure differently from the generation it came from would be
# comparing two things. These are imported rather than duplicated, and
# `atlas/model.py` is pinned by digest in the projection's implementation
# block below so the reuse is recorded rather than assumed.
from refspec import binding
from refspec.atlas.model import (
    ATLAS,
    ATLAS_FILE,
    MANIFEST_FILE,
    RKAF,
    VocabularyAtlasAsset,
    VocabularyAtlasError,
    _as_mapping,
    _canonical_bytes,
    _canonical_nquads,
    _digest_bytes,
    _digest_value,
    _freeze,
    _hierarchy_edges,
    _load_json_object,
    _plain,
    _read_exact_file,
    _require_count,
    _require_digest,
    _require_iri,
    _validate_implementation_pin,
    _validate_query_graph_semantics,
)

FORMAT_ID = "refspec-vocabulary-atlas-projection-nquads-1.0"
SCHEMA_VERSION = "1.0"
MANIFEST_TYPE = "urn:ref:type:VocabularyAtlasProjectionManifest"
ASSET_ID_PREFIX = "urn:ref:vocabulary-atlas-projection:"

# Every module that decides which quads survive, or how the surviving bytes
# are canonicalized and identified.
_IMPLEMENTATION_SOURCE_PATHS = (
    "atlas/model.py",
    "atlas/projection.py",
    "binding.py",
    "storage.py",
)

_MANIFEST_FIELDS = frozenset(
    {
        "id",
        "type",
        "schemaVersion",
        "format",
        "projectionDigest",
        "derivedFrom",
        "projectionPolicy",
        "implementation",
        "graphs",
        "output",
        "counts",
        "canonicalPayloadDigest",
    }
)
_COUNT_FIELDS = frozenset(
    {
        "referenceReleases",
        "releaseFacts",
        "analysisFacts",
        "labelClusters",
        "mappingCandidates",
        "searchOnlyMappings",
        "machineValidations",
        "feedback",
    }
)

# The keep rule, as data, because a policy a consumer cannot read is a promise
# rather than a pin. Every IRI below is a predicate the vendored SpicySearch
# reader actually reads; the enumeration and its file:line citations are in
# `docs/atlas-distribution-measurement.md`.
#
# `skos:broader` is kept even though no consumer accessor reads it yet.
# Hierarchy is a release fact that took two days to admit into the atlas, and
# a projection format that structurally could not carry it would strand that
# work behind a second format change. `skos:narrower` is dropped instead of
# kept: `_hierarchy_edges` projects an edge from the broader direction only
# and refuses a disagreement, so the surviving half is the whole fact.
CONSUMER_READ_CLOSURE_V1: Mapping[str, Any] = MappingProxyType(
    {
        "id": "urn:ref:policy:vocabulary-atlas-projection:consumer-read-closure",
        "version": "1",
        "keepRule": MappingProxyType(
            {
                "analysis": MappingProxyType(
                    {
                        "closureFollows": (
                            str(ATLAS.evidence),
                            str(ATLAS.inputContextArtifact),
                            str(ATLAS.qualifiedBy),
                            str(ATLAS.qualifiedFrom),
                            str(ATLAS.requestArtifact),
                            str(ATLAS.responseArtifact),
                        ),
                        "closureRoots": "searchOnlyConceptMappings",
                        "predicates": (str(ATLAS.memberOfRelease),),
                    }
                ),
                "releaseFacts": MappingProxyType(
                    {
                        "memberLabelPredicates": (
                            str(SKOS.altLabel),
                            str(SKOS.prefLabel),
                        ),
                        "predicates": (
                            str(PROV.hadMember),
                            str(RKAF.referenceReleaseDigest),
                            str(SKOS.broader),
                            str(SKOS.related),
                        ),
                        "typedSubjects": (str(RKAF.ReferenceResourceRelease),),
                    }
                ),
            }
        ),
    }
)

_POLICIES: Mapping[tuple[str, str], Mapping[str, Any]] = MappingProxyType(
    {
        (
            str(CONSUMER_READ_CLOSURE_V1["id"]),
            str(CONSUMER_READ_CLOSURE_V1["version"]),
        ): CONSUMER_READ_CLOSURE_V1
    }
)

_PROJECTION_CONSTRUCTION_TOKEN = object()


def _implementation_pin() -> dict[str, Any]:
    package_root = Path(__file__).parents[1]
    return {
        "id": "urn:ref:implementation:vocabulary-atlas-projection:1.0",
        "version": "1.0",
        "sourceModules": [
            {
                "path": f"refspec/{relative}",
                "digest": _digest_bytes((package_root / relative).read_bytes()),
            }
            for relative in _IMPLEMENTATION_SOURCE_PATHS
        ],
        "runtime": {
            "jsonschemaVersion": importlib.metadata.version("jsonschema"),
            "pythonRequirement": ">=3.10",
            "pythonVersion": platform.python_version(),
            "rdflibVersion": importlib.metadata.version("rdflib"),
        },
    }


def _registered_policy(value: object) -> Mapping[str, Any]:
    """Return the exact registered policy a manifest names, or refuse.

    A projection may not invent its own keep rule. If the policy is not one
    this producer implements, nothing can check what the file dropped.
    """

    policy = _as_mapping(value, "atlas projection policy")
    if set(policy) != {"id", "version", "keepRule"}:
        raise VocabularyAtlasError("atlas projection policy fields differ from v1")
    key = (
        _require_iri(policy.get("id"), "atlas projection policy id"),
        str(policy.get("version") or ""),
    )
    registered = _POLICIES.get(key)
    if registered is None:
        raise VocabularyAtlasError("atlas projection names an unregistered policy")
    if _plain(policy) != _plain(registered):
        raise VocabularyAtlasError("atlas projection policy body differs from its named version")
    return registered


def _validate_derived_from(value: object) -> Mapping[str, str]:
    pin = _as_mapping(value, "atlas projection parent pin")
    if set(pin) != {"assetId", "manifestDigest", "distributionDigest"}:
        raise VocabularyAtlasError("atlas projection derivedFrom fields differ from v1")
    return {
        "assetId": _require_iri(pin.get("assetId"), "atlas projection parent asset id"),
        "manifestDigest": _require_digest(
            pin.get("manifestDigest"), "atlas projection parent manifest digest"
        ),
        "distributionDigest": _require_digest(
            pin.get("distributionDigest"), "atlas projection parent distribution digest"
        ),
    }


def _graph_ids(parent_asset_id: str) -> dict[str, str]:
    return {
        "releaseFacts": parent_asset_id + ":release-facts",
        "analysis": parent_asset_id + ":analysis",
    }


def _search_only_mappings(analysis: Graph) -> set[URIRef]:
    return {
        subject
        for subject in analysis.subjects(RDF.type, RKAF.ConceptMapping)
        if isinstance(subject, URIRef)
        and (subject, RKAF.usageEligibility, RKAF.searchOnly) in analysis
    }


def _mapping_closure(analysis: Graph, policy: Mapping[str, Any]) -> set[URIRef]:
    """Every subject a qualified `searchOnly` mapping needs to stay readable."""

    follows = tuple(
        URIRef(value)
        for value in policy["keepRule"]["analysis"]["closureFollows"]
    )
    closure = _search_only_mappings(analysis)
    frontier = set(closure)
    while frontier:
        following: set[URIRef] = set()
        for subject in frontier:
            for predicate in follows:
                for value in analysis.objects(subject, predicate):
                    if isinstance(value, URIRef) and value not in closure:
                        closure.add(value)
                        following.add(value)
        frontier = following
    return closure


def _project(
    dataset: Dataset,
    *,
    parent_asset_id: str,
    policy: Mapping[str, Any],
) -> Dataset:
    graph_ids = _graph_ids(parent_asset_id)
    release_graph = dataset.graph(URIRef(graph_ids["releaseFacts"]))
    analysis_graph = dataset.graph(URIRef(graph_ids["analysis"]))
    rule = policy["keepRule"]

    release_predicates = {URIRef(value) for value in rule["releaseFacts"]["predicates"]}
    label_predicates = {
        URIRef(value) for value in rule["releaseFacts"]["memberLabelPredicates"]
    }
    typed_subjects = {URIRef(value) for value in rule["releaseFacts"]["typedSubjects"]}
    analysis_predicates = {URIRef(value) for value in rule["analysis"]["predicates"]}

    members = {
        value
        for value in release_graph.objects(None, PROV.hadMember)
        if isinstance(value, URIRef)
    }
    closure = _mapping_closure(analysis_graph, policy)

    projected = Dataset(default_union=False)
    kept_release = projected.graph(URIRef(graph_ids["releaseFacts"]))
    for subject, predicate, value in release_graph:
        if (
            predicate in release_predicates
            or (predicate == RDF.type and value in typed_subjects)
            or (predicate in label_predicates and subject in members)
        ):
            kept_release.add((subject, predicate, value))
    kept_analysis = projected.graph(URIRef(graph_ids["analysis"]))
    for subject, predicate, value in analysis_graph:
        if predicate in analysis_predicates or subject in closure:
            kept_analysis.add((subject, predicate, value))
    return projected


def _observed_counts(dataset: Dataset, *, parent_asset_id: str) -> dict[str, int]:
    graph_ids = _graph_ids(parent_asset_id)
    release_graph = dataset.graph(URIRef(graph_ids["releaseFacts"]))
    analysis = dataset.graph(URIRef(graph_ids["analysis"]))
    counts = {
        "referenceReleases": len(set(release_graph.subjects(RDF.type, RKAF.ReferenceResourceRelease))),
        "releaseFacts": len(release_graph),
        "analysisFacts": len(analysis),
        "labelClusters": len(set(analysis.subjects(RDF.type, ATLAS.LabelCluster))),
        "mappingCandidates": len(set(analysis.subjects(RDF.type, ATLAS.MappingCandidate))),
        "searchOnlyMappings": len(_search_only_mappings(analysis)),
        "machineValidations": len(set(analysis.subjects(RDF.type, ATLAS.MachineValidation))),
        "feedback": len(set(analysis.subjects(RDF.type, ATLAS.MappingFeedback))),
    }
    hierarchy = _hierarchy_edges(release_graph)
    if hierarchy:
        counts["hierarchyEdges"] = len(hierarchy)
    return counts


@dataclass(frozen=True, slots=True, init=False)
class VocabularyAtlasProjection:
    """Projected atlas bytes and the manifest that names what they came from."""

    payload: bytes
    manifest: Mapping[str, Any]
    _verification_token: object

    def __init__(
        self,
        payload: bytes,
        manifest: Mapping[str, Any],
        *,
        _construction_token: object | None = None,
    ) -> None:
        if _construction_token is not _PROJECTION_CONSTRUCTION_TOKEN:
            raise TypeError(
                "VocabularyAtlasProjection must come from build_atlas_projection() "
                "or VocabularyAtlasProjection.open()"
            )
        object.__setattr__(self, "payload", payload)
        object.__setattr__(self, "manifest", manifest)
        object.__setattr__(self, "_verification_token", _PROJECTION_CONSTRUCTION_TOKEN)

    @classmethod
    def _verified(cls, *, payload: bytes, manifest: Mapping[str, Any]) -> Self:
        return cls(payload, manifest, _construction_token=_PROJECTION_CONSTRUCTION_TOKEN)

    def manifest_bytes(self) -> bytes:
        return _canonical_bytes(_plain(self.manifest))

    @property
    def manifest_digest(self) -> str:
        return _digest_bytes(self.manifest_bytes())

    @property
    def output_digest(self) -> str:
        return _digest_bytes(self.payload)

    @property
    def parent_pin(self) -> dict[str, str]:
        """Return the exact parent identity and digests this file names."""

        return cast(dict[str, str], _plain(self.manifest["derivedFrom"]))

    def write(self, directory: Path | str) -> Path:
        target = Path(directory)
        target.mkdir(parents=True, exist_ok=False)
        (target / ATLAS_FILE).write_bytes(self.payload)
        (target / MANIFEST_FILE).write_bytes(self.manifest_bytes())
        return target

    @classmethod
    def open(
        cls,
        directory: Path | str,
        *,
        expected_manifest_digest: str,
        expected_output_digest: str,
    ) -> Self:
        """Verify a projection from its own two files and its parent's digests.

        This never opens the parent. It proves the bytes are the pinned bytes,
        that they are internally closed, that every declared count is true of
        them, and that the asset id is a function of the parent identity, the
        policy and the implementation. Proving the parent actually produced
        them is :meth:`reproduce_from_parent`.
        """

        root = Path(directory)
        if root.is_symlink():
            raise VocabularyAtlasError("atlas projection directory must not be a symlink")
        try:
            root = root.resolve(strict=True)
        except FileNotFoundError as error:
            raise VocabularyAtlasError("atlas projection directory does not exist") from error
        if not root.is_dir():
            raise VocabularyAtlasError("atlas projection path must be a directory")
        _manifest_path, manifest_bytes = _read_exact_file(
            root / MANIFEST_FILE, "atlas projection manifest"
        )
        expected_manifest_digest = _require_digest(
            expected_manifest_digest, "expected atlas projection manifest digest"
        )
        if _digest_bytes(manifest_bytes) != expected_manifest_digest:
            raise VocabularyAtlasError("atlas projection external manifest digest differs")
        manifest = _load_json_object(manifest_bytes, "atlas projection manifest")
        if _canonical_bytes(manifest) != manifest_bytes:
            raise VocabularyAtlasError("atlas projection manifest bytes are not canonical")
        if set(manifest) != set(_MANIFEST_FIELDS):
            raise VocabularyAtlasError("atlas projection manifest fields differ from v1")
        if manifest["type"] != MANIFEST_TYPE:
            raise VocabularyAtlasError("atlas projection manifest type differs")
        if manifest["schemaVersion"] != SCHEMA_VERSION:
            raise VocabularyAtlasError("atlas projection manifest schemaVersion differs")
        if manifest["format"] != FORMAT_ID:
            raise VocabularyAtlasError("atlas projection format differs")
        _require_iri(manifest["id"], "atlas projection id")
        _require_digest(manifest["projectionDigest"], "atlas projection digest")
        _require_digest(manifest["canonicalPayloadDigest"], "atlas projection canonical payload digest")
        if manifest["canonicalPayloadDigest"] != binding.canonical_payload_digest(_plain(manifest)):
            raise VocabularyAtlasError("atlas projection manifest digest differs")
        derived_from = _validate_derived_from(manifest["derivedFrom"])
        policy = _registered_policy(manifest["projectionPolicy"])
        implementation = _validate_implementation_pin(manifest["implementation"])
        projection_digest = _digest_value(
            {
                "format": FORMAT_ID,
                "derivedFrom": derived_from,
                "implementation": _plain(implementation),
                "projectionPolicy": _plain(policy),
            }
        )
        if manifest["projectionDigest"] != projection_digest:
            raise VocabularyAtlasError("atlas projection digest differs")
        asset_id = ASSET_ID_PREFIX + projection_digest.removeprefix("sha256:")
        if manifest["id"] != asset_id:
            raise VocabularyAtlasError("atlas projection id differs from its projection digest")
        if asset_id == derived_from["assetId"]:
            raise VocabularyAtlasError("atlas projection id collides with its parent")

        # The payload's named graphs belong to the generation it was cut from,
        # so they name the parent rather than the projection. That is the
        # relationship, stated in the bytes.
        expected_graphs = _graph_ids(derived_from["assetId"])
        graph_rows = manifest["graphs"]
        if not isinstance(graph_rows, list) or len(graph_rows) != 2:
            raise VocabularyAtlasError("atlas projection must declare exactly two named graphs")
        graph_by_role: dict[str, Mapping[str, Any]] = {}
        for value in graph_rows:
            row = _as_mapping(value, "atlas projection graph")
            if set(row) != {"role", "id", "quadCount"}:
                raise VocabularyAtlasError("atlas projection graph fields differ from v1")
            role = row.get("role")
            if role not in expected_graphs or role in graph_by_role:
                raise VocabularyAtlasError("atlas projection graph roles differ")
            _require_count(row.get("quadCount"), f"atlas projection {role} graph count", positive=True)
            graph_by_role[cast(str, role)] = row
        if set(graph_by_role) != set(expected_graphs):
            raise VocabularyAtlasError("atlas projection graph roles differ")
        for role, graph_id in expected_graphs.items():
            if graph_by_role[role].get("id") != graph_id:
                raise VocabularyAtlasError("atlas projection graph id does not name its parent")

        _payload_path, payload = _read_exact_file(root / ATLAS_FILE, "atlas projection N-Quads")
        expected_output_digest = _require_digest(
            expected_output_digest, "expected atlas projection output digest"
        )
        if _digest_bytes(payload) != expected_output_digest:
            raise VocabularyAtlasError("atlas projection external output digest differs")
        output = _as_mapping(manifest["output"], "atlas projection output")
        if set(output) != {"path", "mediaType", "digest", "byteLength", "quadCount"}:
            raise VocabularyAtlasError("atlas projection output fields differ from v1")
        if output.get("path") != ATLAS_FILE or output.get("mediaType") != "application/n-quads":
            raise VocabularyAtlasError("atlas projection output declaration differs")
        _require_digest(output.get("digest"), "atlas projection output digest")
        _require_count(output.get("byteLength"), "atlas projection output byte length", positive=True)
        _require_count(output.get("quadCount"), "atlas projection output quad count", positive=True)
        if output.get("byteLength") != len(payload):
            raise VocabularyAtlasError("atlas projection output byte length differs")
        if output.get("digest") != _digest_bytes(payload):
            raise VocabularyAtlasError("atlas projection output digest differs")

        dataset = Dataset(default_union=False)
        try:
            dataset.parse(data=payload.decode("utf-8"), format="nquads")
        except Exception as error:  # rdflib exposes parser-specific subclasses
            raise VocabularyAtlasError("atlas projection output is not valid N-Quads") from error
        if _canonical_nquads(dataset) != payload:
            raise VocabularyAtlasError("atlas projection N-Quads bytes are not canonical")
        named_ids = {str(context.identifier) for context in dataset.graphs() if len(context) > 0}
        if named_ids != set(expected_graphs.values()):
            raise VocabularyAtlasError("atlas projection N-Quads named graphs differ")
        graph_counts = {
            role: len(dataset.graph(URIRef(graph_id))) for role, graph_id in expected_graphs.items()
        }
        if any(graph_by_role[role].get("quadCount") != count for role, count in graph_counts.items()):
            raise VocabularyAtlasError("atlas projection graph counts differ")
        if output.get("quadCount") != sum(graph_counts.values()):
            raise VocabularyAtlasError("atlas projection output quad count differs")
        counts = _as_mapping(manifest["counts"], "atlas projection counts")
        if not set(_COUNT_FIELDS) <= set(counts) <= set(_COUNT_FIELDS) | {"hierarchyEdges"}:
            raise VocabularyAtlasError("atlas projection count fields differ from v1")
        for field, count_value in counts.items():
            _require_count(count_value, f"atlas projection count {field}", positive=field == "hierarchyEdges")
        if dict(counts) != _observed_counts(dataset, parent_asset_id=derived_from["assetId"]):
            raise VocabularyAtlasError("atlas projection declared counts differ")
        _validate_query_graph_semantics(
            dataset,
            release_graph_id=expected_graphs["releaseFacts"],
            analysis_graph_id=expected_graphs["analysis"],
        )
        return cls._verified(
            payload=payload,
            manifest=cast(Mapping[str, Any], _freeze(manifest)),
        )

    @classmethod
    def reproduce_from_parent(
        cls,
        directory: Path | str,
        *,
        parent_directory: Path | str,
        expected_manifest_digest: str,
        expected_output_digest: str,
    ) -> Self:
        """Verify the projection and rebuild it from its parent and its policy.

        This is the guarantee ``reproduce_from_inputs`` gives an atlas, stated
        for the artifact a projection actually is: the bytes are a pure
        function of the parent distribution named in ``derivedFrom`` and the
        keep rule named in ``projectionPolicy``.
        """

        opened = cls.open(
            directory,
            expected_manifest_digest=expected_manifest_digest,
            expected_output_digest=expected_output_digest,
        )
        parent_pin = opened.parent_pin
        rebuilt = build_atlas_projection(
            parent_directory,
            expected_manifest_digest=parent_pin["manifestDigest"],
            expected_output_digest=parent_pin["distributionDigest"],
            policy=_registered_policy(opened.manifest["projectionPolicy"]),
        )
        if rebuilt.parent_pin["assetId"] != parent_pin["assetId"]:
            raise VocabularyAtlasError("atlas projection names another parent generation")
        if rebuilt.manifest != opened.manifest or rebuilt.payload != opened.payload:
            raise VocabularyAtlasError(
                "atlas projection does not reproduce from its exact parent and policy"
            )
        return opened


def build_atlas_projection(
    atlas_directory: Path | str,
    *,
    expected_manifest_digest: str,
    expected_output_digest: str,
    policy: Mapping[str, Any] = CONSUMER_READ_CLOSURE_V1,
) -> VocabularyAtlasProjection:
    """Cut one verified atlas down to a named policy's keep rule."""

    registered = _registered_policy(policy)
    parent = VocabularyAtlasAsset.open(
        atlas_directory,
        expected_manifest_digest=expected_manifest_digest,
        expected_output_digest=expected_output_digest,
    )
    parent_asset_id = str(parent.manifest["id"])
    dataset = Dataset(default_union=False)
    dataset.parse(data=parent.payload.decode("utf-8"), format="nquads")
    projected = _project(dataset, parent_asset_id=parent_asset_id, policy=registered)
    del dataset

    payload = _canonical_nquads(projected)
    if not payload:
        raise VocabularyAtlasError("atlas projection kept no quads")
    counts = _observed_counts(projected, parent_asset_id=parent_asset_id)
    graph_ids = _graph_ids(parent_asset_id)
    derived_from = {
        "assetId": parent_asset_id,
        "manifestDigest": parent.manifest_digest,
        "distributionDigest": parent.output_digest,
    }
    implementation = _implementation_pin()
    projection_digest = _digest_value(
        {
            "format": FORMAT_ID,
            "derivedFrom": derived_from,
            "implementation": implementation,
            "projectionPolicy": _plain(registered),
        }
    )
    manifest: dict[str, Any] = {
        "id": ASSET_ID_PREFIX + projection_digest.removeprefix("sha256:"),
        "type": MANIFEST_TYPE,
        "schemaVersion": SCHEMA_VERSION,
        "format": FORMAT_ID,
        "projectionDigest": projection_digest,
        "derivedFrom": derived_from,
        "projectionPolicy": _plain(registered),
        "implementation": implementation,
        "graphs": [
            {
                "role": "releaseFacts",
                "id": graph_ids["releaseFacts"],
                "quadCount": counts["releaseFacts"],
            },
            {
                "role": "analysis",
                "id": graph_ids["analysis"],
                "quadCount": counts["analysisFacts"],
            },
        ],
        "output": {
            "path": ATLAS_FILE,
            "mediaType": "application/n-quads",
            "digest": _digest_bytes(payload),
            "byteLength": len(payload),
            "quadCount": counts["releaseFacts"] + counts["analysisFacts"],
        },
        "counts": counts,
    }
    manifest["canonicalPayloadDigest"] = binding.canonical_payload_digest(manifest)
    _validate_query_graph_semantics(
        projected,
        release_graph_id=graph_ids["releaseFacts"],
        analysis_graph_id=graph_ids["analysis"],
    )
    return VocabularyAtlasProjection._verified(
        payload=payload,
        manifest=cast(Mapping[str, Any], _freeze(manifest)),
    )


def distribution_kind(directory: Path | str) -> str:
    """Name what a distribution directory holds, without verifying it.

    A caller that has a directory and needs to pick a reader asks this rather
    than trying one reader and reading its refusal.
    """

    _path, manifest_bytes = _read_exact_file(Path(directory) / MANIFEST_FILE, "distribution manifest")
    manifest = _load_json_object(manifest_bytes, "distribution manifest")
    declared = manifest.get("type")
    if declared == MANIFEST_TYPE:
        return "vocabularyAtlasProjection"
    if declared == "urn:ref:type:VocabularyAtlasManifest":
        return "vocabularyAtlas"
    raise VocabularyAtlasError("distribution manifest type is neither an atlas nor a projection")


def reproduce_distribution(
    directory: Path | str,
    *,
    expected_manifest_digest: str,
    expected_output_digest: str,
    parent_directory: Path | str | None = None,
    releases: Sequence[Any] | None = None,
    rulespec_core: Any | None = None,
    crosswalks: Sequence[Any] = (),
) -> VocabularyAtlasAsset | VocabularyAtlasProjection:
    """Reproduce whichever kind the directory holds, from its own inputs.

    An atlas reproduces from its managed releases; a projection reproduces
    from its parent and its keep rule. Asking one to reproduce from the
    other's inputs is refused by name here, rather than deep inside a rebuild
    comparison whose failure message means "these bytes are corrupt".
    """

    kind = distribution_kind(directory)
    if kind == "vocabularyAtlasProjection":
        if parent_directory is None:
            raise VocabularyAtlasError(
                "a vocabulary atlas projection reproduces from its parent distribution, "
                "not from managed releases; pass parent_directory"
            )
        return VocabularyAtlasProjection.reproduce_from_parent(
            directory,
            parent_directory=parent_directory,
            expected_manifest_digest=expected_manifest_digest,
            expected_output_digest=expected_output_digest,
        )
    if releases is None or rulespec_core is None:
        raise VocabularyAtlasError(
            "a vocabulary atlas reproduces from its managed releases and Rulespec Core; "
            "pass releases and rulespec_core"
        )
    return VocabularyAtlasAsset.reproduce_from_inputs(
        directory,
        releases=releases,
        rulespec_core=rulespec_core,
        expected_manifest_digest=expected_manifest_digest,
        expected_output_digest=expected_output_digest,
        crosswalks=crosswalks,
    )


__all__ = [
    "ASSET_ID_PREFIX",
    "CONSUMER_READ_CLOSURE_V1",
    "FORMAT_ID",
    "MANIFEST_TYPE",
    "SCHEMA_VERSION",
    "VocabularyAtlasProjection",
    "build_atlas_projection",
    "distribution_kind",
    "reproduce_distribution",
]
