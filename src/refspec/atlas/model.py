"""Release-side primitives an atlas reader pins against.

``PinnedManagedRelease`` is an exact managed release manifest and its verified
read view, reopened on every use so a later file change fails closed.
``closed_reference_release_digest`` derives a checkout-free digest of one
closed Rulespec ``ReferenceResourceRelease`` over a fixed predicate set, so
two readers agree on a release's identity without agreeing on a serialization.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, Self

from rdflib import BNode, Graph, Namespace, URIRef
from rdflib import Literal as RdfLiteral
from rdflib.namespace import DCAT, DCTERMS, PROV, RDF, XSD

from refspec.managed_release import (
    ManagedReleaseExpression,
    ManagedReleaseMember,
    ManagedReleaseRelation,
    ManagedReleaseView,
)
from refspec.release_graph import rulespec_graph_digest
from refspec.storage import canonical_json

ATLAS = Namespace("https://refspec.org/ns/vocabulary-atlas/v2#")
RKAF = Namespace("https://rulespec.org/ns/v1#")

_SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")
_ABSOLUTE_IRI = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:[^\s<>]+$")
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


def _plain(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _plain(child) for key, child in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return [_plain(child) for child in value]
    return value


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


__all__ = [
    "ATLAS",
    "RKAF",
    "AtlasReleaseFactsView",
    "PinnedManagedRelease",
    "VerifiedManagedReleaseSource",
    "VocabularyAtlasError",
    "closed_reference_release_digest",
]
