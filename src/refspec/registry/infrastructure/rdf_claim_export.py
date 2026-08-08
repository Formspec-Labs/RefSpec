"""Source-side conversion from one parsed RDF graph to registry claim rows."""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from typing import Literal as LiteralType

from rdflib import BNode, Graph, Literal, URIRef

from refspec.registry.infrastructure.artifact_serialization import canonical_json_bytes
from refspec.registry.infrastructure.registry_claim_release import RegistryClaim


@dataclass(frozen=True, slots=True)
class RdfClaimExtraction:
    """Claim rows plus explicit counts for source shapes outside the release."""

    claims: tuple[RegistryClaim, ...]
    source_triple_count: int
    omitted_non_english_literal_count: int
    omitted_blank_node_claim_count: int
    omitted_unsupported_term_count: int


def parse_rdf_graph(payload: bytes, *, rdf_format: str, public_id: str) -> Graph:
    """Parse RDF while suppressing RDFLib's expected ill-typed-literal noise."""

    graph = Graph()
    term_logger = logging.getLogger("rdflib.term")
    previous_level = term_logger.level
    term_logger.setLevel(logging.ERROR)
    try:
        graph.parse(data=payload, format=rdf_format, publicID=public_id)
    finally:
        term_logger.setLevel(previous_level)
    return graph


def _is_english(language: str) -> bool:
    normalized = language.casefold()
    return normalized == "en" or normalized.startswith("en-")


def _source_path(
    logical_path: str,
    *,
    subject: str,
    predicate: str,
    object_kind: LiteralType["iri", "literal"],
    object_iri: str | None,
    lexical_value: str | None,
    language: str | None,
    datatype: str | None,
) -> str:
    identity = {
        "datatype": datatype,
        "language": language,
        "lexicalValue": lexical_value,
        "objectIri": object_iri,
        "objectKind": object_kind,
        "predicate": predicate,
        "subject": subject,
    }
    digest = hashlib.sha256(canonical_json_bytes(identity)).hexdigest()
    return f"{logical_path}#claim=sha256:{digest}"


def extract_rdf_claims(
    graph: Graph,
    *,
    release_id: str,
    source_locator: str,
    source_digest: str,
    logical_path: str,
    recipe_id: str,
) -> RdfClaimExtraction:
    """Retain all IRI claims and English or untagged literal claims.

    Blank-node shapes and non-English literals stay in the closed raw input and
    are counted for the release manifest.  No lexical value, language tag,
    datatype, predicate, or direction is normalized here.
    """

    claims: list[RegistryClaim] = []
    omitted_non_english = 0
    omitted_blank = 0
    omitted_unsupported = 0
    for subject_term, predicate_term, object_term in graph:
        if any(
            isinstance(term, BNode)
            for term in (subject_term, predicate_term, object_term)
        ):
            omitted_blank += 1
            continue
        if not isinstance(subject_term, URIRef) or not isinstance(
            predicate_term, URIRef
        ):
            omitted_unsupported += 1
            continue
        subject = str(subject_term)
        predicate = str(predicate_term)
        object_iri: str | None = None
        lexical_value: str | None = None
        language: str | None = None
        datatype: str | None = None
        if isinstance(object_term, URIRef):
            object_kind: LiteralType["iri", "literal"] = "iri"
            object_iri = str(object_term)
        elif isinstance(object_term, Literal):
            object_kind = "literal"
            language = (
                str(object_term.language)
                if object_term.language is not None
                else None
            )
            if language is not None and not _is_english(language):
                omitted_non_english += 1
                continue
            lexical_value = str(object_term)
            datatype = (
                str(object_term.datatype)
                if language is None and object_term.datatype is not None
                else None
            )
        else:
            omitted_unsupported += 1
            continue
        claims.append(
            RegistryClaim(
                release_id=release_id,
                subject=subject,
                predicate=predicate,
                object_kind=object_kind,
                object_iri=object_iri,
                lexical_value=lexical_value,
                language=language,
                datatype=datatype,
                source_record_id=subject,
                source_locator=source_locator,
                source_path=_source_path(
                    logical_path,
                    subject=subject,
                    predicate=predicate,
                    object_kind=object_kind,
                    object_iri=object_iri,
                    lexical_value=lexical_value,
                    language=language,
                    datatype=datatype,
                ),
                source_digest=source_digest,
                origin="observed",
                recipe_id=recipe_id,
            )
        )
    return RdfClaimExtraction(
        claims=tuple(sorted(claims, key=RegistryClaim.sort_key)),
        source_triple_count=len(graph),
        omitted_non_english_literal_count=omitted_non_english,
        omitted_blank_node_claim_count=omitted_blank,
        omitted_unsupported_term_count=omitted_unsupported,
    )


__all__ = ["RdfClaimExtraction", "extract_rdf_claims", "parse_rdf_graph"]
