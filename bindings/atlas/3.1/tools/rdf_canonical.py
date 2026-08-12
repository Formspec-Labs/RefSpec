"""Deterministic RDF 1.1 N-Triples and N-Quads term rendering."""

from __future__ import annotations

import re
import urllib.parse
from typing import Any

from rdflib import BNode, Literal, URIRef

ABSOLUTE_IRI_RE = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:[^\s]+$")

# `src/refspec/registry/infrastructure/identifier_validation.py` already
# implements this exact credentials check as `absolute_uri_issue`. It is not
# imported here: the Atlas binding tools are deliberately independent of the
# RefSpec package (see validate.py's module docstring) so a consumer can copy
# the `bindings/atlas/3.1` directory and validate a distribution offline
# without the rest of this repository. There is no import cycle to break --
# just a self-containment boundary this module must not cross -- so the
# equivalent check is inlined below instead of reusing the helper directly. It
# uses the same `urlsplit` username/password test, so the two agree term for
# term; `test_the_binding_and_the_package_reject_the_same_credentialed_iris`
# is the running check that they still do.


class RdfCanonicalError(ValueError):
    """Raised when a term cannot occur in the Atlas canonical RDF profile."""


def _unicode_escape(character: str) -> str:
    codepoint = ord(character)
    return f"\\u{codepoint:04X}" if codepoint <= 0xFFFF else f"\\U{codepoint:08X}"


def ntriples_term(term: Any) -> str:
    """Render one RDF term in one deterministic RDF 1.1 N-Triples form."""

    if isinstance(term, URIRef):
        value = str(term)
        if not ABSOLUTE_IRI_RE.fullmatch(value):
            raise RdfCanonicalError(f"RDF term is not an absolute IRI: {value!r}")
        try:
            parsed = urllib.parse.urlsplit(value)
        except ValueError as exc:
            raise RdfCanonicalError(f"RDF term IRI is not parseable: {value!r}") from exc
        if parsed.username is not None or parsed.password is not None:
            raise RdfCanonicalError(f"RDF term IRI carries embedded credentials: {value!r}")
        escaped = "".join(
            _unicode_escape(character)
            if ord(character) <= 0x20
            or 0x7F <= ord(character) <= 0x9F
            or character in '<>"{}|^`\\'
            else character
            for character in value
        )
        return f"<{escaped}>"
    if isinstance(term, Literal):
        escapes = {
            "\\": "\\\\",
            '"': '\\"',
            "\t": "\\t",
            "\b": "\\b",
            "\n": "\\n",
            "\r": "\\r",
            "\f": "\\f",
        }
        lexical = "".join(
            escapes.get(character)
            or (
                _unicode_escape(character)
                if ord(character) < 0x20 or 0x7F <= ord(character) <= 0x9F
                else character
            )
            for character in str(term)
        )
        rendered = f'"{lexical}"'
        if term.language:
            return f"{rendered}@{term.language}"
        if term.datatype:
            return f"{rendered}^^{ntriples_term(URIRef(term.datatype))}"
        return rendered
    if isinstance(term, BNode):
        raise RdfCanonicalError(f"blank node {term} is forbidden")
    raise RdfCanonicalError(f"unsupported RDF term {term!r}")


def nquads_line(
    subject: URIRef,
    predicate: URIRef,
    obj: URIRef | Literal,
    graph_id: URIRef,
) -> str:
    """Render one canonical named-graph RDF 1.1 N-Quads statement."""

    return " ".join(
        (
            ntriples_term(subject),
            ntriples_term(predicate),
            ntriples_term(obj),
            ntriples_term(graph_id),
            ".",
        )
    )
