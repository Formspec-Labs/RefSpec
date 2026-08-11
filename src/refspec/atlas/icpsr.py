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
from typing import Any, Self, cast

from refspec.immutable import deep_freeze_json
from refspec.managed_release import (
    ManagedReleaseExpression,
    ManagedReleaseMember,
    ManagedReleaseRelation,
)
from refspec.registry.icpsr_subject import (
    ICPSR_SUBJECT_SCHEME_IRI,
    ICPSR_SUBJECT_XML_URL,
)
from refspec.registry.managed_releases.icpsr_managed_release import (
    ALTERNATE_LABEL_IRI,
    MANAGED_RELEASE_VERSION,
    PARSER_VERSION,
    PREFERRED_LABEL_IRI,
    SCOPE_NOTE_IRI,
    IcpsrManagedReleaseError,
    IcpsrManagedReleaseView,
)
from refspec.release_graph import rulespec_graph_digest
from refspec.storage import canonical_json

from .concept_release import (
    ConceptReleaseError,
    ManagedReleaseRingAssignment,
    PinnedManagedConceptRelease,
    PinnedManagedReleaseRingAssignment,
)
from .model import (
    ATLAS,
    VocabularyAtlasError,
    _require_digest,
    _require_iri,
    closed_reference_release_digest,
)

ICPSR_MANAGED_RELEASE_MANIFEST_TYPE = "urn:ref:type:IcpsrManagedReleaseManifest"
ICPSR_MANAGED_RELEASE_IRI_PREFIX = "urn:ref:icpsr:managed-release:"
ICPSR_RELEASE_IRI_PREFIX = "urn:ref:icpsr:release:development:"
ICPSR_RULESPEC_GRAPH_IRI_PREFIX = "urn:ref:icpsr:rulespec-graph:development:"
ICPSR_XML_DISTRIBUTION_IRI_PREFIX = "urn:ref:icpsr:distribution:subject-xml:"
ICPSR_INDEX_DISTRIBUTION_IRI_PREFIX = "urn:ref:icpsr:distribution:public-index:"
ICPSR_CONCEPT_RELATION_IRI_PREFIX = "urn:ref:icpsr:concept-relation:"

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
_REFERENCE_RELEASE_DIGEST = "rkaf:referenceReleaseDigest"
_MEMBERSHIP_MODE = "rkaf:membershipMode"
_COMPLETE_MEMBERSHIP = "rkaf:completeMembership"
_VERSION_BASIS = "rkaf:versionBasis"
_CONTENT_DERIVED = "rkaf:contentDerived"
_ARTIFACT_IDENTIFIER = _RKAF + "hasArtifactIdentifier"
_CONTENT_DIGEST = _RKAF + "hasContentDigest"

_OPERATIONAL_STATE = "atlas:operationalState"

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
_LABEL_ROLE_BY_PROPERTY = MappingProxyType({value: key for key, value in _LABEL_PROPERTY_IRIS.items()})
#: The release states a role on every indexed expression alongside its semantic
#: property. Both are copied only after they are checked against each other, so
#: two readers of one bundle cannot disagree about what a literal is.
_EXPRESSION_PROPERTY_BY_ROLE = MappingProxyType(
    {
        "preferredLabel": PREFERRED_LABEL_IRI,
        "alternateLabel": ALTERNATE_LABEL_IRI,
        "scopeNote": SCOPE_NOTE_IRI,
    }
)
_EXPRESSION_IRI_PREFIX = "urn:ref:icpsr:indexed-expression:"
_LANGUAGE_TAG = "en"
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

    def iter_members(
        self,
        *,
        release_iri: str | None = None,
    ) -> Iterable[ManagedReleaseMember]:
        return (
            member
            for member in self._members.values()
            if release_iri is None or member.release_iri == release_iri
        )

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
    sources = _require_mapping(manifest.get("sources"), "ICPSR sources")
    if (
        manifest.get("type") != ICPSR_MANAGED_RELEASE_MANIFEST_TYPE
        or manifest.get("version") != MANAGED_RELEASE_VERSION
        or manifest.get("parserVersion") != PARSER_VERSION
        or release.get("schemeIri") != ICPSR_SUBJECT_SCHEME_IRI
    ):
        raise VocabularyAtlasError("ICPSR managed-release identity differs from the URI-verified package")
    # The Federal Register adapter pins one constant source digest, because
    # that package is one published edition. ICPSR is not: it is a development
    # release over a capture that will be taken again, and its release IRI is
    # derived from the digests of the bytes it actually read. So the binding
    # here is per-bundle rather than to a constant — `_require_release_scope`
    # proves the identifier came from these exact sources, which is what stops
    # a bundle from claiming one capture's identity while packaging another.
    _require_digest(sources.get("xmlDigest"), "ICPSR subject.xml digest")
    _require_digest(sources.get("indexCaptureDigest"), "ICPSR index capture digest")
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
    if (
        coverage.get("membershipCompleteForVerifiedSubset") is not True
        or coverage.get("sourceVocabularyComplete") is not False
    ):
        raise VocabularyAtlasError("ICPSR managed release does not enumerate its verified subset completely")
    if not view.concepts:
        raise VocabularyAtlasError("ICPSR managed release has no members")
    _require_release_scope(manifest)
    _require_coverage_agrees(view)
    return view


def _require_release_scope(manifest: Mapping[str, Any]) -> str:
    """Prove the release identifier was derived from the sources it names.

    The builder mints the scope from the two source digests and the policy
    version, and every one of those is in the manifest this reader already
    verified. Without recomputing it, a bundle could mint a release IRI — and
    through it both distribution IRIs — from a scope unrelated to its own
    bytes, and the projection would publish that as identity.
    """

    release = _require_mapping(manifest.get("release"), "ICPSR release pin")
    sources = _require_mapping(manifest.get("sources"), "ICPSR sources")
    expected = hashlib.sha256(
        canonical_json(
            {
                "indexCapture": sources.get("indexCaptureDigest"),
                "policy": MANAGED_RELEASE_VERSION,
                "xml": sources.get("xmlDigest"),
            }
        ).encode("utf-8")
    ).hexdigest()
    release_iri = _require_iri(release.get("id"), "ICPSR reference release IRI")
    if release_iri != ICPSR_RELEASE_IRI_PREFIX + expected:
        raise VocabularyAtlasError("ICPSR release identifier is not derived from its own source digests")
    if manifest.get("id") != ICPSR_MANAGED_RELEASE_IRI_PREFIX + expected:
        raise VocabularyAtlasError("ICPSR publication release identifier is not derived from its own source digests")
    return expected


def _require_coverage_agrees(view: IcpsrManagedReleaseView) -> None:
    """Reconcile the records against the sealed coverage report they claim.

    ``IcpsrManagedReleaseView`` already ties the manifest counts to the record
    files, so repeating that adds nothing. What it never checks is whether the
    records agree with the coverage report the same manifest pins by digest —
    so a bundle whose ``concepts.jsonl`` silently omitted half its resolved
    relations would still pass while its coverage still reported all of them.
    """

    coverage = view.coverage
    source_counts = _require_mapping(coverage.get("sourceCounts"), "ICPSR coverage source counts")
    relation_coverage = _require_mapping(coverage.get("relationCoverage"), "ICPSR relation coverage")
    gaps = _require_mapping(coverage.get("gaps"), "ICPSR coverage gaps")
    if source_counts.get("uriVerifiedJoins") != len(view.concepts):
        raise VocabularyAtlasError("ICPSR coverage reports a different verified member count")
    if relation_coverage.get("failedCount") != 0:
        raise VocabularyAtlasError("ICPSR coverage reports a failed relation")

    observed = 0
    resolved = 0
    for concept in view.concepts:
        relations = concept.get("relations")
        if not isinstance(relations, Sequence) or isinstance(relations, (str, bytes)):
            raise VocabularyAtlasError("ICPSR concept relations must be an array")
        observed += len(relations)
        resolved += sum(
            1
            for relation in relations
            if isinstance(relation, Mapping) and relation.get("resolutionStatus") == "uriVerified"
        )
    if relation_coverage.get("sourceObservedCount") != observed or relation_coverage.get("uriResolvedCount") != resolved:
        raise VocabularyAtlasError("ICPSR coverage relation counts differ from the packaged concept records")
    if (
        relation_coverage.get("explicitlyExcludedCount") != observed - resolved
        or gaps.get("unresolvedRelationCount") != observed - resolved
    ):
        raise VocabularyAtlasError("ICPSR coverage does not account for every unresolved relation")


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
            # Digest shape is required, not merely non-blank: these two values
            # are hashed into the closed release digest, so free text would
            # become identity.
            _CONTENT_DIGEST: _require_digest(
                sources.get("indexCaptureDigest"),
                "ICPSR index capture digest",
            ),
        },
        {
            "@id": xml_iri,
            _RDF_TYPE: _RKAF + "Artifact",
            _ARTIFACT_IDENTIFIER: ICPSR_SUBJECT_XML_URL,
            _DCTERMS_FORMAT: "application/xml",
            _CONTENT_DIGEST: _require_digest(sources.get("xmlDigest"), "ICPSR subject.xml digest"),
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
            "skos:inScheme": _iri(ICPSR_SUBJECT_SCHEME_IRI),
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
            target_label = _require_text(entry.get("targetLabel"), "ICPSR relation target label")
            predicate_iri = _RELATION_PROPERTY_IRIS[cast(str, kind)]
            if stated[predicate_iri].setdefault(target, target_label) != target_label:
                raise VocabularyAtlasError("ICPSR states one relation through two different target labels")
        source_path = "subject.xml#record=" + _require_text(
            row.get("sourceLocalRecordNumber"),
            "ICPSR source record number",
        )
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


def _stated_texts(view: IcpsrManagedReleaseView) -> set[tuple[str, str, str]]:
    """Return every ``(member, property, literal)`` the concept records state.

    The bundle carries concepts and indexed expressions as two files, and
    nothing in the reader ties one to the other. Without this set the atlas
    could publish a graph saying one thing while its label clusters and
    crosswalk candidates — both built from expressions — indexed another.
    """

    stated: set[tuple[str, str, str]] = set()
    for row in view.concepts:
        member_iri = cast(str, row["conceptIri"])
        role = cast(str, row["officialLabelRole"])
        stated.add((member_iri, _LABEL_PROPERTY_IRIS[role], cast(str, row["officialLabel"])))
        for note in cast(Sequence[str], row["scopeNotes"]):
            stated.add((member_iri, SCOPE_NOTE_IRI, note))
    return stated


def _expressions(
    view: IcpsrManagedReleaseView,
    *,
    release_iri: str,
    members: Mapping[str, ManagedReleaseMember],
) -> tuple[ManagedReleaseExpression, ...]:
    """Copy the release's own indexed expressions without adding any."""

    result: list[ManagedReleaseExpression] = []
    seen: set[str] = set()
    observed: set[tuple[str, str, str]] = set()
    for row in view.indexed_expressions:
        expression_id = _require_text(row.get("id"), "ICPSR indexed expression id")
        member_iri = _require_text(row.get("memberIri"), "ICPSR indexed expression member")
        if expression_id in seen:
            raise VocabularyAtlasError("ICPSR managed release repeats an indexed expression")
        if member_iri not in members:
            raise VocabularyAtlasError("ICPSR indexed expression has no exact member")
        seen.add(expression_id)
        property_iri = _require_text(row.get("semanticPropertyIri"), "ICPSR indexed expression property")
        role = row.get("role")
        if _EXPRESSION_PROPERTY_BY_ROLE.get(cast(str, role)) != property_iri:
            raise VocabularyAtlasError("ICPSR indexed expression role and semantic property disagree")
        literal = _require_text(row.get("originalLiteral"), "ICPSR original literal")
        source_path = _require_text(row.get("sourcePath"), "ICPSR expression source path")
        language = _require_text(row.get("language"), "ICPSR expression language")
        if language != _LANGUAGE_TAG:
            raise VocabularyAtlasError("ICPSR indexed expression is not in the language the release projects")
        # The release derives the identifier from exactly these fields, so
        # recomputing it binds the expression to the member, property, and
        # literal it claims instead of taking its word for them.
        identity = canonical_json(
            {
                "language": language,
                "literal": literal,
                "member": member_iri,
                "release": release_iri,
                "semanticProperty": property_iri,
                "sourcePath": source_path,
            }
        ).encode("utf-8")
        if expression_id != _EXPRESSION_IRI_PREFIX + hashlib.sha256(identity).hexdigest():
            raise VocabularyAtlasError("ICPSR indexed expression identifier is not derived from its own facts")
        observed.add((member_iri, property_iri, literal))
        result.append(
            ManagedReleaseExpression(
                expression_id=expression_id,
                member_iri=member_iri,
                indexed_text=_require_text(row.get("indexedText"), "ICPSR indexed text"),
                original_literal=literal,
                language_tag=language,
                semantic_property_iri=property_iri,
                source_property_or_path=source_path,
                record=cast(
                    Mapping[str, Any],
                    deep_freeze_json({"role": role, "sourcePath": source_path}),
                ),
                label_role=_LABEL_ROLE_BY_PROPERTY.get(property_iri),
                # ICPSR states no lifecycle status for any term, so the honest
                # value is that none was declared. It is not a retired status,
                # so a consumer filtering retired terms keeps every one.
                source_status="notDeclared",
            )
        )
    if observed != _stated_texts(view):
        raise VocabularyAtlasError("ICPSR indexed expressions and concept records state different text")
    return tuple(sorted(result, key=lambda item: item.expression_id))


def _project_view(view: IcpsrManagedReleaseView) -> IcpsrSubjectAtlasView:
    manifest = view.manifest
    scope = _require_release_scope(manifest)
    release_iri = ICPSR_RELEASE_IRI_PREFIX + scope
    graph_iri = ICPSR_RULESPEC_GRAPH_IRI_PREFIX + scope
    distribution_nodes, distribution_iris = _distribution_nodes(view, scope=scope)
    concept_nodes, members, relations = _concept_projection(view, release_iri=release_iri)

    release_node: dict[str, Any] = {
        "@id": release_iri,
        _RDF_TYPE: "rkaf:ReferenceResourceRelease",
        "dcterms:isVersionOf": _iri(ICPSR_SUBJECT_SCHEME_IRI),
        "dcat:version": MANAGED_RELEASE_VERSION,
        "dcterms:type": _iri("skos:ConceptScheme"),
        # This release's declared scope is the URI-verified subset. The source
        # bundle proves that every member of that scope is present while it
        # records the wider publisher-vocabulary gaps separately.
        _MEMBERSHIP_MODE: _COMPLETE_MEMBERSHIP,
        "prov:hadMember": [_iri(value) for value in sorted(members)],
        "dcat:distribution": [_iri(value) for value in distribution_iris],
        # ICPSR publishes no version string or issue date for the thesaurus,
        # so the release is identified by the digests of the bytes it read.
        _VERSION_BASIS: _iri(_CONTENT_DERIVED),
        _OPERATIONAL_STATE: _DEVELOPMENT_ONLY,
    }
    graph: dict[str, Any] = {
        "@context": {
            "atlas": str(ATLAS),
            "dcat": "http://www.w3.org/ns/dcat#",
            "dcterms": "http://purl.org/dc/terms/",
            "prov": "http://www.w3.org/ns/prov#",
            "rkaf": _RKAF,
            "skos": _SKOS,
        },
        "@graph": [
            # The scheme node carries a type and nothing else. Neither source
            # view states a label for the scheme itself, and `releaseFacts` is
            # `copiedManagedReleaseFactsOnly`, so naming the thesaurus here
            # would be this projection's own assertion rather than ICPSR's.
            {
                "@id": ICPSR_SUBJECT_SCHEME_IRI,
                _RDF_TYPE: "rkaf:ConceptScheme",
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
        _publication_id=_require_iri(manifest.get("id"), "ICPSR publication release id"),
        _reference_release_iri=release_iri,
        _rulespec_graph_id=graph_iri,
        _graph=cast(Mapping[str, Any], deep_freeze_json(graph)),
        _members=MappingProxyType(dict(members)),
        _expressions=_expressions(view, release_iri=release_iri, members=members),
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


class PinnedIcpsrManagedConceptRelease(PinnedManagedConceptRelease):
    """Select the complete URI-verified ICPSR subset for Atlas 2.0.

    The source-specific reader verifies the custom ICPSR package, then this
    class presents its content-derived Rulespec graph through the same exact
    managed-release pin used by every Atlas 2.0 scope.
    """

    @classmethod
    def open(
        cls,
        manifest_path: Path | str,
        *,
        expected_manifest_digest: str,
        release_id: str,
        ring_assignment: PinnedManagedReleaseRingAssignment,
    ) -> Self:
        try:
            digest = _require_digest(
                expected_manifest_digest,
                "ICPSR managed release manifest digest",
            )
            selected_release = _require_iri(
                release_id,
                "ICPSR managed concept release id",
            )
            if not isinstance(
                ring_assignment,
                PinnedManagedReleaseRingAssignment,
            ):
                raise ConceptReleaseError(
                    "ICPSR managed concept release requires a pinned ring assignment"
                )
            assignment = ring_assignment.verified_assignment()
            package = _verified_package(
                Path(manifest_path),
                expected_manifest_digest=digest,
            )
            view = _project_view(package)
        except VocabularyAtlasError as error:
            raise ConceptReleaseError(str(error)) from error
        if (
            assignment.managed_manifest_digest != digest
            or assignment.release_id != selected_release
            or assignment.semantic_ring != "subject"
        ):
            raise ConceptReleaseError(
                "ICPSR ring assignment names another exact subject release"
            )
        if view.reference_release_iri != selected_release or not tuple(
            view.iter_members(release_iri=selected_release)
        ):
            raise ConceptReleaseError(
                "ICPSR verified subset is absent from the selected release"
            )
        return cls(
            manifest_path=Path(manifest_path).resolve(strict=True),
            manifest_digest=digest,
            release_id=selected_release,
            ring_assignment=ring_assignment,
        )

    def _open_verified_view_and_assignment(
        self,
    ) -> tuple[IcpsrSubjectAtlasView, ManagedReleaseRingAssignment]:
        try:
            package = _verified_package(
                self.manifest_path,
                expected_manifest_digest=self.manifest_digest,
            )
            view = _project_view(package)
        except VocabularyAtlasError as error:
            raise ConceptReleaseError(str(error)) from error
        assignment = self.ring_assignment.verified_assignment()
        if (
            assignment.managed_manifest_digest != self.manifest_digest
            or assignment.release_id != self.release_id
            or assignment.semantic_ring != "subject"
        ):
            raise ConceptReleaseError(
                "ICPSR ring assignment names another exact subject release"
            )
        if view.reference_release_iri != self.release_id or not tuple(
            view.iter_members(release_iri=self.release_id)
        ):
            raise ConceptReleaseError(
                "ICPSR verified subset is no longer present or complete"
            )
        return view, assignment

    def verified_view(self) -> IcpsrSubjectAtlasView:
        """Reopen the custom package and re-cut the same complete subset."""

        view, _ = self._open_verified_view_and_assignment()
        return view

    def verified_view_and_pin(
        self,
    ) -> tuple[IcpsrSubjectAtlasView, dict[str, Any]]:
        """Derive the Atlas pin and graph from one fresh verification boundary."""

        view, assignment = self._open_verified_view_and_assignment()
        return view, self._pin_from_verified_view(view, assignment)  # type: ignore[arg-type]


__all__ = [
    "ICPSR_CONCEPT_RELATION_IRI_PREFIX",
    "ICPSR_INDEX_DISTRIBUTION_IRI_PREFIX",
    "ICPSR_MANAGED_RELEASE_IRI_PREFIX",
    "ICPSR_MANAGED_RELEASE_MANIFEST_TYPE",
    "ICPSR_RELEASE_IRI_PREFIX",
    "ICPSR_RULESPEC_GRAPH_IRI_PREFIX",
    "ICPSR_USED_FOR_PROPERTY_IRI",
    "ICPSR_USE_PROPERTY_IRI",
    "ICPSR_XML_DISTRIBUTION_IRI_PREFIX",
    "IcpsrSubjectAtlasView",
    "PinnedIcpsrManagedConceptRelease",
    "PinnedIcpsrSubjectAtlasRelease",
]
