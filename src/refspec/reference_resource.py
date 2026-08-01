"""Rulespec Core ReferenceResourceRelease projection and digest support."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from typing import Any

from .canonical import CanonicalValueError, canonical_digest
from .rulespec_core import (
    load_reference_resource_release_digest_fixture,
    load_reference_resource_release_schema,
)


NAMESPACES = {
    "rdf": "http://www.w3.org/1999/02/22-rdf-syntax-ns#",
    "dcterms": "http://purl.org/dc/terms/",
    "dcat": "http://www.w3.org/ns/dcat#",
    "prov": "http://www.w3.org/ns/prov#",
    "rkaf": "https://rulespec.org/ns/v1#",
    "skos": "http://www.w3.org/2004/02/skos/core#",
    "xsd": "http://www.w3.org/2001/XMLSchema#",
}
REFERENCE_RELEASE_CONTEXT: dict[str, Any] = {
    "rkaf": NAMESPACES["rkaf"],
    "prov": NAMESPACES["prov"],
    "dcat": NAMESPACES["dcat"],
    "dcterms": NAMESPACES["dcterms"],
    "skos": NAMESPACES["skos"],
    "xsd": NAMESPACES["xsd"],
    "rkaf:hasArtifactIdentifier": {"@type": "@id"},
    "rkaf:artifactIdentifierScheme": {"@type": "@vocab"},
    "rkaf:hasContentDigest": {"@type": "xsd:string"},
    "rkaf:referenceReleaseDigest": {"@type": "xsd:string"},
    "rkaf:versionBasis": {"@type": "@vocab"},
    "rkaf:membershipMode": {"@type": "@vocab"},
    "dcterms:isVersionOf": {"@type": "@id", "@container": "@set"},
    "dcterms:type": {"@type": "@id"},
    "dcterms:format": {"@type": "xsd:string"},
    "dcat:version": {"@type": "xsd:string"},
    "dcat:distribution": {"@type": "@id", "@container": "@set"},
    "prov:hadMember": {"@type": "@id", "@container": "@set"},
}
RELEASE_FIELDS = {
    "@id",
    "@type",
    "dcterms:isVersionOf",
    "dcat:version",
    "dcterms:type",
    "rkaf:membershipMode",
    "prov:hadMember",
    "dcat:distribution",
    "rkaf:referenceReleaseDigest",
    "rkaf:versionBasis",
}
DISTRIBUTION_FIELDS = {
    "@id",
    "@type",
    "rkaf:hasArtifactIdentifier",
    "rkaf:artifactIdentifierScheme",
    "dcterms:format",
    "rkaf:hasContentDigest",
}


def _values(value: Any) -> list[Any]:
    return list(value) if isinstance(value, list) else [value]


def _expand_iri(value: str) -> str:
    if value.startswith("urn:") or "://" in value:
        return value
    prefix, local = value.split(":", 1)
    try:
        return NAMESPACES[prefix] + local
    except KeyError as error:
        raise CanonicalValueError(
            f"unsupported compact IRI prefix: {prefix}"
        ) from error


def _iri(value: str) -> str:
    return f"<{_expand_iri(value)}>"


def _literal(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def _triple(subject: str, predicate: str, object_: str) -> str:
    return f"{_iri(subject)} {_iri(predicate)} {object_} .\n"


def reference_release_node(document: Mapping[str, Any]) -> Mapping[str, Any]:
    graph = document.get("@graph")
    if not isinstance(graph, list):
        raise CanonicalValueError("ReferenceResourceRelease projection needs @graph")
    releases = [
        node
        for node in graph
        if isinstance(node, Mapping)
        and node.get("@type") == "rkaf:ReferenceResourceRelease"
    ]
    if len(releases) != 1:
        raise CanonicalValueError(
            "ReferenceResourceRelease projection needs exactly one release node"
        )
    return releases[0]


def reference_release_distribution_nodes(
    document: Mapping[str, Any],
) -> dict[str, Mapping[str, Any]]:
    graph = document.get("@graph")
    if not isinstance(graph, list):
        raise CanonicalValueError("ReferenceResourceRelease projection needs @graph")
    return {
        str(node["@id"]): node
        for node in graph
        if isinstance(node, Mapping) and node.get("@type") == "rkaf:Artifact"
    }


def reference_release_canonical_preimage(
    document: Mapping[str, Any],
) -> str:
    """Return Rulespec's closed RDFC-1.0 N-Quads preimage.

    This projection contains no blank nodes. RDFC-1.0 therefore reduces to
    canonical RDF term serialization and lexical N-Quads sorting. The bundled
    Rulespec positive vector checks this narrow implementation.
    """

    release = reference_release_node(document)
    release_id = str(release["@id"])
    rows = [
        _triple(release_id, "rdf:type", _iri(str(release["@type"]))),
    ]
    field_rules = (
        ("dcterms:isVersionOf", "dcterms:isVersionOf", "iri"),
        ("dcat:version", "dcat:version", "literal"),
        ("dcterms:type", "dcterms:type", "iri"),
        ("rkaf:membershipMode", "rkaf:membershipMode", "iri"),
        ("prov:hadMember", "prov:hadMember", "iri"),
        ("dcat:distribution", "dcat:distribution", "iri"),
        ("rkaf:versionBasis", "rkaf:versionBasis", "iri"),
        ("dcterms:issued", "dcterms:issued", "dateTime"),
        ("rkaf:hasEffectivePeriod", "rkaf:hasEffectivePeriod", "iri"),
    )
    for field, predicate, value_kind in field_rules:
        if field not in release:
            continue
        for value in _values(release[field]):
            if not isinstance(value, str):
                raise CanonicalValueError(f"{field} must contain strings")
            if value_kind == "iri":
                object_ = _iri(value)
            elif value_kind == "dateTime":
                normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
                object_ = (
                    _literal(normalized)
                    + "^^<http://www.w3.org/2001/XMLSchema#dateTime>"
                )
            else:
                object_ = _literal(value)
            rows.append(_triple(release_id, predicate, object_))

    distributions = reference_release_distribution_nodes(document)
    for distribution_id in _values(release["dcat:distribution"]):
        distribution = distributions.get(distribution_id)
        if distribution is None:
            raise CanonicalValueError(
                f"distribution does not resolve: {distribution_id}"
            )
        for field, predicate, value_kind in (
            ("rkaf:hasArtifactIdentifier", "rkaf:hasArtifactIdentifier", "iri"),
            ("dcterms:format", "dcterms:format", "literal"),
            ("rkaf:hasContentDigest", "rkaf:hasContentDigest", "literal"),
        ):
            if field not in distribution:
                raise CanonicalValueError(
                    f"distribution {distribution_id} lacks {field}"
                )
            for value in _values(distribution[field]):
                if not isinstance(value, str):
                    raise CanonicalValueError(f"{field} must contain strings")
                object_ = _iri(value) if value_kind == "iri" else _literal(value)
                rows.append(_triple(distribution_id, predicate, object_))
    return "".join(sorted(rows))


def reference_release_digest(document: Mapping[str, Any]) -> str:
    preimage = reference_release_canonical_preimage(document).encode("utf-8")
    return "sha256:" + hashlib.sha256(preimage).hexdigest()


def validate_digest_implementation_against_rulespec_fixture() -> None:
    """Prove the local narrow digest implementation against Rulespec's vector."""

    fixture = load_reference_resource_release_digest_fixture()
    release = reference_release_node(fixture)
    if reference_release_digest(fixture) != release["rkaf:referenceReleaseDigest"]:
        raise CanonicalValueError(
            "local reference release digest code fails the Rulespec Core vector"
        )


def build_reference_resource_release(
    *,
    scheme_id: str,
    release_version: str,
    concept_ids: Sequence[str],
    distribution_payload: Mapping[str, Any],
) -> dict[str, Any]:
    """Build one exact complete Rulespec ReferenceResourceRelease graph."""

    validate_digest_implementation_against_rulespec_fixture()
    load_reference_resource_release_schema()
    members = sorted(concept_ids)
    if not members or len(members) != len(set(members)):
        raise ValueError(
            "complete reference release membership must be nonempty and unique"
        )
    distribution_digest = canonical_digest(distribution_payload)
    distribution_id = (
        "urn:refspec:vocabulary-distribution:"
        + distribution_digest.removeprefix("sha256:")
    )
    release_id = scheme_id + ":reference-resource-release"
    release = {
        "@id": release_id,
        "@type": "rkaf:ReferenceResourceRelease",
        "dcterms:isVersionOf": scheme_id,
        "dcat:version": release_version,
        "dcterms:type": "skos:ConceptScheme",
        "rkaf:membershipMode": "rkaf:completeMembership",
        "prov:hadMember": members,
        "dcat:distribution": [distribution_id],
        "rkaf:versionBasis": "rkaf:contentDerived",
    }
    distribution = {
        "@id": distribution_id,
        "@type": "rkaf:Artifact",
        "rkaf:hasArtifactIdentifier": [distribution_id],
        "rkaf:artifactIdentifierScheme": ["rkaf:partner-defined"],
        "dcterms:format": "application/vnd.refspec.vocabulary-membership+json",
        "rkaf:hasContentDigest": distribution_digest,
    }
    document: dict[str, Any] = {
        "@context": REFERENCE_RELEASE_CONTEXT,
        "@graph": [release, distribution],
    }
    release["rkaf:referenceReleaseDigest"] = reference_release_digest(document)
    return document


def validate_reference_resource_release(
    document: Mapping[str, Any],
    *,
    scheme_id: str,
    release_version: str,
    concept_ids: Sequence[str],
    distribution_payload: Mapping[str, Any],
) -> None:
    """Validate Rulespec shape, membership, distribution, and RDFC digest."""

    validate_digest_implementation_against_rulespec_fixture()
    schema = load_reference_resource_release_schema()
    definition = schema["$defs"]["ReferenceResourceRelease"]
    release = reference_release_node(document)
    required = set(definition["required"]) | {"@id", "prov:hadMember"}
    if not required <= set(release) or set(release) != RELEASE_FIELDS:
        raise CanonicalValueError(
            "ReferenceResourceRelease fields do not match the Rulespec shape"
        )
    if release["@type"] != "rkaf:ReferenceResourceRelease":
        raise CanonicalValueError("ReferenceResourceRelease has the wrong type")
    if release["@id"] != scheme_id + ":reference-resource-release":
        raise CanonicalValueError(
            "ReferenceResourceRelease has the wrong managed-release identifier"
        )
    if release["dcterms:isVersionOf"] != scheme_id:
        raise CanonicalValueError("ReferenceResourceRelease uses the wrong resource")
    if release["dcat:version"] != release_version:
        raise CanonicalValueError("ReferenceResourceRelease uses the wrong version")
    if release["dcterms:type"] != "skos:ConceptScheme":
        raise CanonicalValueError(
            "ReferenceResourceRelease has the wrong resource kind"
        )
    if release["rkaf:membershipMode"] != "rkaf:completeMembership":
        raise CanonicalValueError("ReferenceResourceRelease is not complete")
    if release["prov:hadMember"] != sorted(concept_ids):
        raise CanonicalValueError(
            "ReferenceResourceRelease membership is not the exact concept set"
        )
    if release["rkaf:versionBasis"] != "rkaf:contentDerived":
        raise CanonicalValueError(
            "ReferenceResourceRelease has the wrong version basis"
        )
    distributions = reference_release_distribution_nodes(document)
    if (
        set(document) != {"@context", "@graph"}
        or document["@context"] != REFERENCE_RELEASE_CONTEXT
    ):
        raise CanonicalValueError(
            "ReferenceResourceRelease projection has extra fields"
        )
    if len(distributions) != 1 or len(document["@graph"]) != 2:
        raise CanonicalValueError(
            "ReferenceResourceRelease needs one exact distribution"
        )
    distribution_id = release["dcat:distribution"]
    if not isinstance(distribution_id, list) or len(distribution_id) != 1:
        raise CanonicalValueError("ReferenceResourceRelease distribution is invalid")
    distribution = distributions.get(distribution_id[0])
    if distribution is None or set(distribution) != DISTRIBUTION_FIELDS:
        raise CanonicalValueError(
            "ReferenceResourceRelease distribution does not resolve"
        )
    expected_distribution_digest = canonical_digest(distribution_payload)
    expected_distribution_id = (
        "urn:refspec:vocabulary-distribution:"
        + expected_distribution_digest.removeprefix("sha256:")
    )
    if distribution != {
        "@id": expected_distribution_id,
        "@type": "rkaf:Artifact",
        "rkaf:hasArtifactIdentifier": [expected_distribution_id],
        "rkaf:artifactIdentifierScheme": ["rkaf:partner-defined"],
        "dcterms:format": "application/vnd.refspec.vocabulary-membership+json",
        "rkaf:hasContentDigest": expected_distribution_digest,
    }:
        raise CanonicalValueError(
            "ReferenceResourceRelease distribution does not match release content"
        )
    if release["rkaf:referenceReleaseDigest"] != reference_release_digest(document):
        raise CanonicalValueError(
            "ReferenceResourceRelease digest does not match its RDFC-1.0 manifest"
        )
