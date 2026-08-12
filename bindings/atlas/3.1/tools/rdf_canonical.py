"""Deterministic RDF 1.1 N-Triples and N-Quads term rendering.

This module owns the Atlas canonical RDF profile in both directions:

* ``ntriples_term`` / ``nquads_line`` RENDER a term or statement in the one
  form the profile admits, and refuse anything the profile cannot carry.
* ``canonical_line_issue`` READS one serialized line and answers whether it is
  in that form, working on raw bytes before any RDF parser sees them.

The two halves are one grammar stated twice, and
``tests/test_atlas_v3_canonical_line_grammar.py`` is the running check that
they still agree: it mutates real canonical lines and requires the byte
grammar and the render-and-compare it replaced to reach the same verdict.
"""

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
# is the running check that they still do, and it now covers the forbidden-IRI
# character class the same way.

# RDF 1.1 gives a simple literal and an explicit `xsd:string` literal the same
# term identity, so a wire that carries both spells one term two ways: two
# node digests for one set of facts, and a SHACL `sh:in` list that matches only
# the spelling its shapes file happens to use. The profile therefore admits
# only the simple form, which is also what W3C canonical N-Triples mandates.
XSD_STRING_IRI = "http://www.w3.org/2001/XMLSchema#string"

# The same argument, one axis over: BCP 47 language tags are case-insensitive,
# so `@en` and `@EN` name one term and would carry two node digests. W3C
# canonical N-Triples mandates the lowercase spelling, so the profile admits
# only that one.
#
# Refuse, never coerce. Lowercasing at the mint would silently rewrite a
# publisher's tag, and the whole point of the canonical profile is that the
# bytes a producer wrote are the bytes it meant; a producer holding `en-GB`
# spelled `en-GB` gets a refusal naming the tag, not a quiet `en-gb`.
_MINTABLE_LANGUAGE_TAG_RE = re.compile(r"^[a-z]+(?:-[a-z0-9]+)*$")

# The ASCII characters RFC 3987 excludes from an IRI, plus `[` and `]`.
#
# `[` and `]` are RFC 3986/3987 gen-delims reserved for an IP-literal host
# (`http://[::1]/`) and are illegal anywhere else in an IRI. Atlas mints no
# IP-literal authority, so the profile refuses them outright rather than
# tracking which component it is in. Every strict parser (oxigraph, Jena, and
# most Java/Rust tooling) already refuses them; rdflib did not, which is how
# 7,770 `atlas:sourceLocator` IRIs built from JSON-pointer-ish fragments
# reached a published pack.
#
# Control characters (U+0000-U+0020), DEL and the C1 block (U+007F-U+009F) are
# excluded for the same reason: RFC 3987's `ucschar` production does not
# contain them. The renderer used to percent-free-escape these into `\uXXXX`
# UCHARs; the profile now refuses them, because a UCHAR that decodes to a
# character RFC 3987 forbids is still not an IRI, and admitting the escape
# would make the serialized form of an IRI ambiguous.
FORBIDDEN_IRI_CHARACTERS = frozenset('<>"{}|^`\\[]')
_FORBIDDEN_IRI_RE = re.compile(r'[\x00-\x20\x7f-\x9f<>"{}|^`\\\[\]]')


class RdfCanonicalError(ValueError):
    """Raised when a term cannot occur in the Atlas canonical RDF profile."""


def _unicode_escape(character: str) -> str:
    codepoint = ord(character)
    return f"\\u{codepoint:04X}" if codepoint <= 0xFFFF else f"\\U{codepoint:08X}"


def _iri_text(term: URIRef) -> str:
    """Return the IRI text of ``term``, or raise if the profile refuses it."""

    value = str(term)
    if not ABSOLUTE_IRI_RE.fullmatch(value):
        raise RdfCanonicalError(f"RDF term is not an absolute IRI: {value!r}")
    try:
        parsed = urllib.parse.urlsplit(value)
    except ValueError as exc:
        raise RdfCanonicalError(f"RDF term IRI is not parseable: {value!r}") from exc
    # Credentials before the character class, in the same order as
    # `absolute_uri_issue`: the two copies must not only agree on WHETHER an
    # IRI is refused but on WHICH refusal it earns.
    if parsed.username is not None or parsed.password is not None:
        raise RdfCanonicalError(f"RDF term IRI carries embedded credentials: {value!r}")
    forbidden = _FORBIDDEN_IRI_RE.search(value)
    if forbidden is not None:
        raise RdfCanonicalError(
            f"RDF term IRI contains {forbidden.group()!r}, which RFC 3987 "
            f"excludes from an IRI: {value!r}"
        )
    return value


def ntriples_term(term: Any) -> str:
    """Render one RDF term in one deterministic RDF 1.1 N-Triples form."""

    if isinstance(term, URIRef):
        return f"<{_iri_text(term)}>"
    if isinstance(term, Literal):
        if term.datatype is not None and str(term.datatype) == XSD_STRING_IRI:
            raise RdfCanonicalError(
                "RDF literal MUST use the simple form; an explicit xsd:string "
                f"datatype names the same term twice: {str(term)!r}"
            )
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
            if _MINTABLE_LANGUAGE_TAG_RE.fullmatch(term.language) is None:
                raise RdfCanonicalError(
                    "RDF literal language tag MUST be the lowercase BCP 47 "
                    "spelling W3C canonical N-Triples mandates; "
                    f"{term.language!r} names the same term a second way"
                )
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


# --------------------------------------------------------------------------
# The same profile, read off the bytes
# --------------------------------------------------------------------------
#
# The productions below accept exactly what `nquads_line` emits and nothing
# else, so a pack can be proved canonical without building RDF terms at all.
# Doing it here rather than in a parser subclass moves the proof to the layer
# that already owns the bytes, and drops the per-term render-and-compare that
# cost ~30% of the parse phase.

# One IRI: `<` scheme `:` one-or-more admitted characters `>`. No escape is
# admitted anywhere inside an IRI (see FORBIDDEN_IRI_CHARACTERS), so a
# backslash is refused by the character class rather than opening one.
_IRI_EXCLUDED = rb'\x00-\x20"<>\\\^`{|}\[\]\x7f'
_IRI = rb"<[A-Za-z][A-Za-z0-9+.\-]*:[^" + _IRI_EXCLUDED + rb"]+>"

# One canonical literal body. `ntriples_term` writes the seven short escapes
# and `\u00XX` (UPPERCASE hex) for the remaining C0/C1 controls, and leaves
# every other character raw -- so `é` for a character that needs no
# escape, a lowercase hex digit, a `\U0001F600` long escape, and `\/` are all
# non-canonical spellings the grammar must refuse.
_ESCAPED_CONTROL = rb"\\u00(?:0[0-7]|0B|0[EF]|1[0-9A-F]|7F|[89][0-9A-F])"
_LITERAL_BODY = rb'(?:[^\x00-\x1f"\\\x7f]|\\[tbnrf"\\]|' + _ESCAPED_CONTROL + rb")*"
# Lowercase only, matching `_MINTABLE_LANGUAGE_TAG_RE` and the renderer's
# refusal above: `@en` and `@EN` are one term, and the profile spells it once.
_LANGUAGE_TAG = rb"@[a-z]+(?:-[a-z0-9]+)*"
# The datatype IRI, minus the one datatype the simple form already spells.
_DATATYPE = rb"\^\^(?!<http://www\.w3\.org/2001/XMLSchema\#string>)" + _IRI
_LITERAL = rb'"' + _LITERAL_BODY + rb'"(?:' + _LANGUAGE_TAG + rb"|" + _DATATYPE + rb")?"

CANONICAL_LINE_RE = re.compile(
    rb"^("
    + _IRI
    + rb") ("
    + _IRI
    + rb") ("
    + _IRI
    + rb"|"
    + _LITERAL
    + rb") ("
    + _IRI
    + rb") \.$"
)

# U+007F and the C1 block are the two ranges the grammar cannot exclude with a
# byte class alone: U+0080-U+009F are two UTF-8 bytes. One extra search per
# line covers both positions (IRI and literal) at once.
_RAW_C1_RE = re.compile(rb"\xc2[\x80-\x9f]")

# Diagnosis only, on the rejection path: a line that is canonical except for a
# blank-node term keeps reporting `rdf.blank-node`, the code the conformance
# corpus pins for it, rather than collapsing into `rdf.canonical`.
_BLANK_NODE = rb"_:[A-Za-z0-9_](?:[A-Za-z0-9_.\-]*[A-Za-z0-9_\-])?"
_SUBJECT_OR_NODE = rb"(?:" + _IRI + rb"|" + _BLANK_NODE + rb")"
_BLANK_NODE_LINE_RE = re.compile(
    rb"^"
    + _SUBJECT_OR_NODE
    + rb" "
    + _IRI
    + rb" (?:"
    + _SUBJECT_OR_NODE
    + rb"|"
    + _LITERAL
    + rb") "
    + _SUBJECT_OR_NODE
    + rb" \.$"
)


def canonical_line_issue_and_terms(
    content: bytes,
) -> tuple[tuple[str, str] | None, tuple[bytes, bytes, bytes, bytes] | None]:
    """Read one line: its refusal if any, and its four terms if it is canonical.

    ``content`` is one serialized statement WITHOUT its terminating LF. The
    codes are the validator's own: ``rdf.blank-node`` for a line whose only
    fault is a blank-node term, ``rdf.term`` for a credential-bearing IRI, and
    ``rdf.canonical`` for every other departure from the profile.

    The terms come back from the same match that decided the verdict, so a
    caller that needs both -- the node-digest pass, which reads subject,
    predicate and object off the bytes -- pays for one regex, and can only ever
    be handed terms of a line already proved canonical. Splitting a canonical
    line by hand is exactly the ambiguity this grammar exists to remove.
    """

    match = CANONICAL_LINE_RE.match(content)
    if match is None or _RAW_C1_RE.search(content) is not None:
        if match is None and _BLANK_NODE_LINE_RE.match(content) is not None:
            return (("rdf.blank-node", "contains a blank node term"), None)
        return (("rdf.canonical", "is not in the canonical N-Quads term form"), None)
    # An `@` outside a language tag can only be in an IRI, and the only IRI
    # form the grammar admits but the profile refuses is one with userinfo.
    if b"@" in content:
        for group in (1, 2, 3, 4):
            start, end = match.span(group)
            if content[start] != 0x3C or content.find(b"@", start, end) < 0:
                continue
            try:
                text = content[start + 1 : end - 1].decode("utf-8")
                parsed = urllib.parse.urlsplit(text)
            except (UnicodeDecodeError, ValueError):
                return (("rdf.canonical", "contains an unparseable IRI"), None)
            if parsed.username is not None or parsed.password is not None:
                return (("rdf.term", f"IRI carries embedded credentials: {text!r}"), None)
    return (None, match.groups())  # type: ignore[return-value]


def canonical_line_issue(content: bytes) -> tuple[str, str] | None:
    """Return ``(code, reason)`` when ``content`` is not one canonical quad."""

    return canonical_line_issue_and_terms(content)[0]


__all__ = [
    "ABSOLUTE_IRI_RE",
    "CANONICAL_LINE_RE",
    "FORBIDDEN_IRI_CHARACTERS",
    "XSD_STRING_IRI",
    "RdfCanonicalError",
    "canonical_line_issue",
    "canonical_line_issue_and_terms",
    "nquads_line",
    "ntriples_term",
]
