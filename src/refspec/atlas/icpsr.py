"""Atlas adapter for the development-only URI-verified ICPSR subject thesaurus.

ICPSR's reader is mature: it joins the public term-URI index to the pinned
``subject.xml`` snapshot, keeps only labels both sources agree on, and records
every source-version gap.  What it never had was a projection into the shape
the atlas consumes, so 3,760 verified concepts sat one door short of a build
while ELSST — which got exactly this bridge — went through.

This module is that bridge and nothing more.  It reopens the sealed bundle,
copies the facts it states, and refuses anything it does not.

Two facts about the source shape decide most of what follows.

**The release is development-only and says so.**  Its manifest and coverage
both carry ``operationalState: developmentOnly`` with ``acceptedOutputAllowed``
false, because the public index and the XML snapshot are two source versions
joined by label rather than one publisher-versioned release.  This adapter does
not launder that away and does not refuse it either: it *requires* the marker
at the door and republishes it on the release node, so a consumer reading the
atlas sees the same declaration the bundle made.  Refusal was considered and
rejected — the whole atlas is ``candidateUseOnly`` and every input to it,
including the source-complete Federal Register package, is already barred from
accepted output.  A development marker is a fact to carry, not a reason to drop
3,760 concepts on the floor.  The atlas manifest's field set is closed at
schema 1.0, so the marker rides in ``releaseFacts`` where the release itself
lives.

**Non-preferred terms are concepts here, not labels.**  ICPSR mints a public
term URI for every DESCRIPTOR *and* NON-DESCRIPTOR record and links them with
the ISO 25964 USE/UF pair.  SKOS has no predicate for that: its answer to a
non-preferred term is ``skos:altLabel`` on the preferred concept, which would
fuse two published identities into one and discard a URI ICPSR assigned.  So
USE and UF are carried as stated, between the two concept URIs, under
RefSpec-owned predicates.  They are deliberately *not* collapsed into
``skos:altLabel``: release facts are copied, and the two directions do not even
agree in the source (479 USE against 394 UF in the 2026-07-30 capture), so
either collapse would invent one side of the pair.
"""

from __future__ import annotations

import hashlib
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, cast

from typing_extensions import Self

from refspec.immutable import deep_freeze_json
from refspec.managed_release import (
    ManagedReleaseExpression,
    ManagedReleaseMember,
    ManagedReleaseRelation,
)
from refspec.registry.icpsr_managed_release import (
    ALTERNATE_LABEL_IRI,
    MANAGED_RELEASE_VERSION,
    PREFERRED_LABEL_IRI,
    SCOPE_NOTE_IRI,
    IcpsrManagedReleaseError,
    IcpsrManagedReleaseView,
)
from refspec.registry.icpsr_subject import (
    ICPSR_SUBJECT_SCHEME_IRI,
    ICPSR_SUBJECT_XML_URL,
)
from refspec.release_graph import rulespec_graph_digest
from refspec.storage import canonical_json

from .model import ATLAS, VocabularyAtlasError, closed_reference_release_digest

ICPSR_MANAGED_RELEASE_MANIFEST_TYPE = "urn:ref:type:IcpsrManagedReleaseManifest"
ICPSR_RELEASE_IRI_PREFIX = "urn:ref:icpsr:release:development:"
ICPSR_RULESPEC_GRAPH_IRI_PREFIX = "urn:ref:icpsr:rulespec-graph:development:"
ICPSR_XML_DISTRIBUTION_IRI_PREFIX = "urn:ref:icpsr:distribution:subject-xml:"
ICPSR_INDEX_DISTRIBUTION_IRI_PREFIX = "urn:ref:icpsr:distribution:public-index:"
ICPSR_CONCEPT_RELATION_IRI_PREFIX = "urn:ref:icpsr:concept-relation:"

#: The ICPSR scheme carries no publisher-stated label of its own in either
#: source view, so the atlas states the publisher's own name for the resource.
ICPSR_SUBJECT_SCHEME_LABEL = "ICPSR Subject Thesaurus"

#: ISO 25964 USE/UF between two published term URIs. SKOS cannot express it
#: without fusing the two identities, so RefSpec owns the spelling and says so.
ICPSR_USE_PROPERTY_IRI = str(ATLAS.thesaurusUse)
ICPSR_USED_FOR_PROPERTY_IRI = str(ATLAS.thesaurusUsedFor)

_RKAF = "https://rulespec.org/ns/v1#"
_RDF_TYPE = "@type"
_SKOS = "http://www.w3.org/2004/02/skos/core#"
_SKOS_IN_SCHEME = _SKOS + "inScheme"
_SKOS_CONCEPT_SCHEME = _SKOS + "ConceptScheme"
_SKOS_BROADER = _SKOS + "broader"
_SKOS_NARROWER = _SKOS + "narrower"
_SKOS_RELATED = _SKOS + "related"
_SKOS_NOTATION = _SKOS + "notation"
_PROV_HAD_MEMBER = "http://www.w3.org/ns/prov#hadMember"
_DCAT_DISTRIBUTION = "http://www.w3.org/ns/dcat#distribution"
_DCAT_VERSION = "http://www.w3.org/ns/dcat#version"
_DCTERMS_FORMAT = "http://purl.org/dc/terms/format"
_DCTERMS_IS_VERSION_OF = "http://purl.org/dc/terms/isVersionOf"
_DCTERMS_TYPE = "http://purl.org/dc/terms/type"
_REFERENCE_RELEASE_DIGEST = _RKAF + "referenceReleaseDigest"
_MEMBERSHIP_MODE = _RKAF + "membershipMode"
_PARTIAL_MEMBERSHIP = _RKAF + "partialMembership"
_VERSION_BASIS = _RKAF + "versionBasis"
_CONTENT_DERIVED = _RKAF + "contentDerived"
_ARTIFACT_IDENTIFIER = _RKAF + "hasArtifactIdentifier"
_CONTENT_DIGEST = _RKAF + "hasContentDigest"

_OPERATIONAL_STATE = str(ATLAS.operationalState)
_CANDIDATE_LOOKUP_ALLOWED = str(ATLAS.candidateLookupAllowed)
_ACCEPTED_OUTPUT_ALLOWED = str(ATLAS.acceptedOutputAllowed)
_XSD_BOOLEAN = "http://www.w3.org/2001/XMLSchema#boolean"

_DEVELOPMENT_ONLY = "developmentOnly"

#: Relations the release states between two verified members. ``use`` and
#: ``usedFor`` keep RefSpec-owned predicates; the rest are exactly SKOS.
_RELATION_PROPERTY_IRIS = MappingProxyType(
    {
        "broader": _SKOS_BROADER,
        "narrower": _SKOS_NARROWER,
        "related": _SKOS_RELATED,
        "use": ICPSR_USE_PROPERTY_IRI,
        "usedFor": ICPSR_USED_FOR_PROPERTY_IRI,
    }
)
_LABEL_PROPERTY_IRIS = MappingProxyType(
    {
        "preferred": PREFERRED_LABEL_IRI,
        "alternate": ALTERNATE_LABEL_IRI,
    }
)
_HIERARCHY_PROPERTY_IRIS = frozenset({_SKOS_BROADER, _SKOS_NARROWER})


def _sha256_file(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _plain(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _plain(child) for key, child in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return [_plain(child) for child in value]
    return value


def _iri(value: str) -> dict[str, str]:
    return {"@id": value}


def _language_literal(value: str) -> dict[str, str]:
    return {"@language": "en", "@value": value}


def _require_text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise VocabularyAtlasError(f"{label} is required")
    return value


def _require_mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise VocabularyAtlasError(f"{label} must be an object")
    return cast(Mapping[str, Any], value)


def _relation_id(subject_iri: str, predicate_iri: str, object_iri: str) -> str:
    identity = canonical_json(
        {
            "object": object_iri,
            "predicate": predicate_iri,
            "subject": subject_iri,
        }
    ).encode("utf-8")
    return ICPSR_CONCEPT_RELATION_IRI_PREFIX + hashlib.sha256(identity).hexdigest()


@dataclass(frozen=True, slots=True)
class IcpsrSubjectAtlasView:
    """Verified ICPSR facts exposed through the atlas's release-view seam."""

    _publication_id: str
    _reference_release_iri: str
    _rulespec_graph_id: str
    _graph: Mapping[str, Any]
    _members: Mapping[str, ManagedReleaseMember]
    _expressions: tuple[ManagedReleaseExpression, ...]
    _relations: tuple[ManagedReleaseRelation, ...]

    @property
    def release_id(self) -> str:
        return self._publication_id

    @property
    def reference_release_iri(self) -> str:
        """The ``rkaf:ReferenceResourceRelease`` every member belongs to."""

        return self._reference_release_iri

    @property
    def rulespec_graph_id(self) -> str:
        return self._rulespec_graph_id

    @property
    def rulespec_graph(self) -> Mapping[str, Any]:
        return self._graph

    def iter_members(self) -> Iterable[ManagedReleaseMember]:
        return self._members.values()

    def lookup_member(self, member_iri: str) -> ManagedReleaseMember | None:
        return self._members.get(member_iri)

    def iter_expressions(self) -> Iterable[ManagedReleaseExpression]:
        return iter(self._expressions)

    def iter_relations(self) -> Iterable[ManagedReleaseRelation]:
        """Return the hierarchy rows behind the graph's own broader/narrower.

        The atlas uses these only to repair a literal-valued edge a compact
        source context left behind. This graph already writes both directions
        as IRIs, so the rows change nothing; they are supplied because they are
        the verified, byte-pinned form of exactly the edges the graph states,
        and a producer that withheld them would leave the atlas unable to tell
        a stated edge from a mistyped one.
        """

        return iter(self._relations)


def _verified_package(
    manifest_path: Path,
    *,
    expected_manifest_digest: str,
) -> IcpsrManagedReleaseView:
    """Reopen the sealed bundle and refuse anything but a development release."""

    if manifest_path.is_symlink() or not manifest_path.is_file():
        raise VocabularyAtlasError("ICPSR managed-release manifest must be a regular file")
    if _sha256_file(manifest_path) != expected_manifest_digest:
        raise VocabularyAtlasError("ICPSR managed-release manifest digest differs")
    try:
        view = IcpsrManagedReleaseView.open(manifest_path)
    except IcpsrManagedReleaseError as error:
        raise VocabularyAtlasError(str(error)) from error
    if _sha256_file(manifest_path) != expected_manifest_digest:
        raise VocabularyAtlasError("ICPSR managed-release manifest changed while opening")

    manifest = view.manifest
    coverage = view.coverage
    release = _require_mapping(manifest.get("release"), "ICPSR release pin")
    counts = _require_mapping(manifest.get("counts"), "ICPSR release counts")
    if (
        manifest.get("type") != ICPSR_MANAGED_RELEASE_MANIFEST_TYPE
        or manifest.get("version") != MANAGED_RELEASE_VERSION
        or release.get("schemeIri") != ICPSR_SUBJECT_SCHEME_IRI
    ):
        raise VocabularyAtlasError("ICPSR managed-release identity differs from the URI-verified package")
    # The bundle declares itself development-only. Requiring the declaration
    # here is what stops a differently-marked bundle from riding in on this
    # reader; the projection then republishes it rather than dropping it.
    if (
        manifest.get("operationalState") != _DEVELOPMENT_ONLY
        or coverage.get("operationalState") != _DEVELOPMENT_ONLY
        or manifest.get("acceptedOutputAllowed") is not False
        or coverage.get("acceptedOutputAllowed") is not False
        or manifest.get("candidateLookupAllowed") is not True
        or coverage.get("candidateLookupAllowed") is not True
    ):
        raise VocabularyAtlasError("ICPSR managed release must declare development-only candidate lookup")
    if coverage.get("membershipCompleteForVerifiedSubset") is not True:
        raise VocabularyAtlasError("ICPSR managed release does not enumerate its verified subset completely")
    if counts.get("concepts") != len(view.concepts) or counts.get("indexedExpressions") != len(
        view.indexed_expressions
    ):
        raise VocabularyAtlasError("ICPSR managed-release counts differ from its records")
    if not view.concepts:
        raise VocabularyAtlasError("ICPSR managed release has no members")
    return view


def _release_scope(view: IcpsrManagedReleaseView) -> str:
    """Return the content-derived scope shared by every identifier it minted."""

    release = _require_mapping(view.manifest.get("release"), "ICPSR release pin")
    release_iri = _require_text(release.get("id"), "ICPSR reference release IRI")
    if not release_iri.startswith(ICPSR_RELEASE_IRI_PREFIX):
        raise VocabularyAtlasError("ICPSR reference release IRI is not a development release")
    scope = release_iri.removeprefix(ICPSR_RELEASE_IRI_PREFIX)
    if len(scope) != 64 or any(character not in "0123456789abcdef" for character in scope):
        raise VocabularyAtlasError("ICPSR reference release IRI lacks its content-derived scope")
    return scope


def _distribution_nodes(view: IcpsrManagedReleaseView, *, scope: str) -> tuple[list[dict[str, Any]], list[str]]:
    """Describe the two exact byte sources the release was built from."""

    sources = _require_mapping(view.manifest.get("sources"), "ICPSR sources")
    xml_iri = ICPSR_XML_DISTRIBUTION_IRI_PREFIX + scope
    index_iri = ICPSR_INDEX_DISTRIBUTION_IRI_PREFIX + scope
    nodes = [
        {
            "@id": index_iri,
            _RDF_TYPE: _RKAF + "Artifact",
            _ARTIFACT_IDENTIFIER: ICPSR_SUBJECT_SCHEME_IRI,
            _DCTERMS_FORMAT: "text/html",
            _CONTENT_DIGEST: _require_text(
                sources.get("indexCaptureDigest"),
                "ICPSR index capture digest",
            ),
        },
        {
            "@id": xml_iri,
            _RDF_TYPE: _RKAF + "Artifact",
            _ARTIFACT_IDENTIFIER: ICPSR_SUBJECT_XML_URL,
            _DCTERMS_FORMAT: "application/xml",
            _CONTENT_DIGEST: _require_text(sources.get("xmlDigest"), "ICPSR subject.xml digest"),
        },
    ]
    return nodes, sorted((index_iri, xml_iri))


def _concept_projection(
    view: IcpsrManagedReleaseView,
    *,
    release_iri: str,
) -> tuple[
    list[dict[str, Any]],
    dict[str, ManagedReleaseMember],
    list[ManagedReleaseRelation],
]:
    """Copy every stated fact the atlas format can carry, and only those."""

    concept_by_iri: dict[str, Mapping[str, Any]] = {}
    for row in view.concepts:
        concept_iri = _require_text(row.get("conceptIri"), "ICPSR concept IRI")
        if concept_iri in concept_by_iri:
            raise VocabularyAtlasError("ICPSR managed release repeats a concept")
        concept_by_iri[concept_iri] = row

    nodes: list[dict[str, Any]] = []
    members: dict[str, ManagedReleaseMember] = {}
    relations: list[ManagedReleaseRelation] = []
    for concept_iri, row in sorted(concept_by_iri.items()):
        label = _require_text(row.get("officialLabel"), "ICPSR official label")
        role = row.get("officialLabelRole")
        if role not in _LABEL_PROPERTY_IRIS:
            raise VocabularyAtlasError("ICPSR concept label role is not preferred or alternate")
        node: dict[str, Any] = {
            "@id": concept_iri,
            _RDF_TYPE: _RKAF + "RegisteredConcept",
            _SKOS_IN_SCHEME: _iri(ICPSR_SUBJECT_SCHEME_IRI),
            _LABEL_PROPERTY_IRIS[cast(str, role)]: _language_literal(label),
            _SKOS_NOTATION: _require_text(row.get("publisherCode"), "ICPSR publisher code"),
        }
        scope_notes = row.get("scopeNotes")
        if not isinstance(scope_notes, Sequence) or isinstance(scope_notes, (str, bytes)):
            raise VocabularyAtlasError("ICPSR concept scope notes must be an array")
        if scope_notes:
            node[SCOPE_NOTE_IRI] = [_language_literal(_require_text(note, "ICPSR scope note")) for note in scope_notes]

        stated: dict[str, dict[str, str]] = defaultdict(dict)
        source_relations = row.get("relations")
        if not isinstance(source_relations, Sequence) or isinstance(source_relations, (str, bytes)):
            raise VocabularyAtlasError("ICPSR concept relations must be an array")
        for relation in source_relations:
            entry = _require_mapping(relation, "ICPSR concept relation")
            kind = entry.get("relation")
            if kind not in _RELATION_PROPERTY_IRIS:
                raise VocabularyAtlasError("ICPSR concept states an unsupported relation")
            if entry.get("resolutionStatus") != "uriVerified":
                # An unresolved relation names a label the verified subset does
                # not contain, so it has no endpoint to point at. The bundle
                # already records every one of them as an explicit gap.
                continue
            target = _require_text(entry.get("targetConceptIri"), "ICPSR relation target")
            if target not in concept_by_iri:
                raise VocabularyAtlasError("ICPSR relation endpoint is outside the release")
            stated[_RELATION_PROPERTY_IRIS[cast(str, kind)]][target] = _require_text(
                entry.get("targetLabel"),
                "ICPSR relation target label",
            )
        source_path = f"subject.xml#record={row.get('sourceLocalRecordNumber')}"
        for predicate_iri, targets in sorted(stated.items()):
            node[predicate_iri] = [_iri(target) for target in sorted(targets)]
            if predicate_iri not in _HIERARCHY_PROPERTY_IRIS:
                continue
            relations.extend(
                ManagedReleaseRelation(
                    relation_id=_relation_id(concept_iri, predicate_iri, target),
                    subject_member_iri=concept_iri,
                    predicate_iri=predicate_iri,
                    object_member_iri=target,
                    release_iri=release_iri,
                    record=cast(
                        Mapping[str, Any],
                        deep_freeze_json(
                            {
                                "sourcePath": source_path,
                                "targetLabel": target_label,
                            }
                        ),
                    ),
                )
                for target, target_label in sorted(targets.items())
            )

        nodes.append(node)
        members[concept_iri] = ManagedReleaseMember(
            member_iri=concept_iri,
            release_iri=release_iri,
            scheme_iri=ICPSR_SUBJECT_SCHEME_IRI,
            record=cast(Mapping[str, Any], deep_freeze_json(node)),
        )
    return nodes, members, relations


def _expressions(
    view: IcpsrManagedReleaseView,
    *,
    members: Mapping[str, ManagedReleaseMember],
) -> tuple[ManagedReleaseExpression, ...]:
    """Copy the release's own indexed expressions without adding any."""

    label_role_by_property = {
        PREFERRED_LABEL_IRI: "preferred",
        ALTERNATE_LABEL_IRI: "alternate",
    }
    result: list[ManagedReleaseExpression] = []
    seen: set[str] = set()
    for row in view.indexed_expressions:
        expression_id = _require_text(row.get("id"), "ICPSR indexed expression id")
        member_iri = _require_text(row.get("memberIri"), "ICPSR indexed expression member")
        if expression_id in seen:
            raise VocabularyAtlasError("ICPSR managed release repeats an indexed expression")
        if member_iri not in members:
            raise VocabularyAtlasError("ICPSR indexed expression has no exact member")
        seen.add(expression_id)
        property_iri = _require_text(row.get("semanticPropertyIri"), "ICPSR indexed expression property")
        if property_iri not in {PREFERRED_LABEL_IRI, ALTERNATE_LABEL_IRI, SCOPE_NOTE_IRI}:
            raise VocabularyAtlasError("ICPSR indexed expression uses an unsupported property")
        result.append(
            ManagedReleaseExpression(
                expression_id=expression_id,
                member_iri=member_iri,
                indexed_text=_require_text(row.get("indexedText"), "ICPSR indexed text"),
                original_literal=_require_text(row.get("originalLiteral"), "ICPSR original literal"),
                language_tag=_require_text(row.get("language"), "ICPSR expression language"),
                semantic_property_iri=property_iri,
                source_property_or_path=_require_text(row.get("sourcePath"), "ICPSR expression source path"),
                record=cast(
                    Mapping[str, Any],
                    deep_freeze_json(
                        {
                            "role": row.get("role"),
                            "sourcePath": row.get("sourcePath"),
                        }
                    ),
                ),
                label_role=label_role_by_property.get(property_iri),
                source_status="active",
            )
        )
    return tuple(sorted(result, key=lambda item: item.expression_id))


def _project_view(view: IcpsrManagedReleaseView) -> IcpsrSubjectAtlasView:
    scope = _release_scope(view)
    manifest = view.manifest
    release_iri = ICPSR_RELEASE_IRI_PREFIX + scope
    graph_iri = ICPSR_RULESPEC_GRAPH_IRI_PREFIX + scope
    distribution_nodes, distribution_iris = _distribution_nodes(view, scope=scope)
    concept_nodes, members, relations = _concept_projection(view, release_iri=release_iri)

    release_node: dict[str, Any] = {
        "@id": release_iri,
        _RDF_TYPE: _RKAF + "ReferenceResourceRelease",
        _DCTERMS_IS_VERSION_OF: _iri(ICPSR_SUBJECT_SCHEME_IRI),
        _DCAT_VERSION: MANAGED_RELEASE_VERSION,
        _DCTERMS_TYPE: _iri(_SKOS_CONCEPT_SCHEME),
        # Partial, not complete: `dcterms:isVersionOf` names the whole ICPSR
        # thesaurus, and this release deliberately omits every label the two
        # source views disagree about. Claiming complete membership of the
        # thesaurus would be the one overstatement the bundle avoided.
        _MEMBERSHIP_MODE: _iri(_PARTIAL_MEMBERSHIP),
        _PROV_HAD_MEMBER: [_iri(value) for value in sorted(members)],
        _DCAT_DISTRIBUTION: [_iri(value) for value in distribution_iris],
        # ICPSR publishes no version string or issue date for the thesaurus,
        # so the release is identified by the digests of the bytes it read.
        _VERSION_BASIS: _iri(_CONTENT_DERIVED),
        _OPERATIONAL_STATE: _DEVELOPMENT_ONLY,
        _CANDIDATE_LOOKUP_ALLOWED: {"@type": _XSD_BOOLEAN, "@value": "true"},
        _ACCEPTED_OUTPUT_ALLOWED: {"@type": _XSD_BOOLEAN, "@value": "false"},
    }
    graph: dict[str, Any] = {
        "@graph": [
            {
                "@id": ICPSR_SUBJECT_SCHEME_IRI,
                _RDF_TYPE: _RKAF + "ConceptScheme",
                PREFERRED_LABEL_IRI: _language_literal(ICPSR_SUBJECT_SCHEME_LABEL),
            },
            *distribution_nodes,
            *concept_nodes,
            release_node,
        ]
    }
    release_node[_REFERENCE_RELEASE_DIGEST] = closed_reference_release_digest(
        graph,
        release_iri=release_iri,
        label="ICPSR",
    )
    return IcpsrSubjectAtlasView(
        _publication_id=_require_text(manifest.get("id"), "ICPSR publication release id"),
        _reference_release_iri=release_iri,
        _rulespec_graph_id=graph_iri,
        _graph=cast(Mapping[str, Any], deep_freeze_json(graph)),
        _members=MappingProxyType(dict(members)),
        _expressions=_expressions(view, members=members),
        _relations=tuple(sorted(relations, key=lambda item: item.relation_id)),
    )


@dataclass(frozen=True, slots=True)
class PinnedIcpsrSubjectAtlasRelease:
    """Exact ICPSR development package adapted to the atlas producer seam.

    Release-digest computation is part of the source-pinned RefSpec producer,
    exactly as it is for the Federal Register package, so no Rulespec checkout
    or unrecorded validator can change this release's facts.
    """

    manifest_path: Path
    manifest_digest: str

    @classmethod
    def open(
        cls,
        manifest_path: Path | str,
        *,
        expected_manifest_digest: str,
    ) -> Self:
        selected = Path(manifest_path)
        _verified_package(
            selected,
            expected_manifest_digest=expected_manifest_digest,
        )
        return cls(
            manifest_path=selected.resolve(strict=True),
            manifest_digest=expected_manifest_digest,
        )

    def verified_view(self) -> IcpsrSubjectAtlasView:
        package = _verified_package(
            self.manifest_path,
            expected_manifest_digest=self.manifest_digest,
        )
        return _project_view(package)

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


__all__ = [
    "ICPSR_CONCEPT_RELATION_IRI_PREFIX",
    "ICPSR_INDEX_DISTRIBUTION_IRI_PREFIX",
    "ICPSR_MANAGED_RELEASE_MANIFEST_TYPE",
    "ICPSR_RELEASE_IRI_PREFIX",
    "ICPSR_RULESPEC_GRAPH_IRI_PREFIX",
    "ICPSR_SUBJECT_SCHEME_LABEL",
    "ICPSR_USED_FOR_PROPERTY_IRI",
    "ICPSR_USE_PROPERTY_IRI",
    "ICPSR_XML_DISTRIBUTION_IRI_PREFIX",
    "IcpsrSubjectAtlasView",
    "PinnedIcpsrSubjectAtlasRelease",
]
