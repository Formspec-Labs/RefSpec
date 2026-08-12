"""Differential proof for the canonical N-Quads byte grammar.

`canonical_line_issue` replaced a per-term render-and-compare that lived inside
an rdflib parser subclass (`_LexicalNQuadsParser.parseline` did
``original != nquads_line(subject, predicate, obj, context)``). The replacement
was measured on real data -- 29,283,283 lines, zero rejections -- but a proof
that a checker accepts everything valid says nothing about what it rejects.

So the old check is reconstructed here as an ORACLE and the two are asked the
same question over a battery of mutations applied to real canonical lines. The
oracle is deliberately a copy: it is the thing being replaced, so importing it
would make the comparison circular, and keeping it here is what lets the
production copy be deleted.

Three mutation classes are EXPECTED to disagree, because the profile changed on
purpose in this wave:

* `bracket-iri` -- an IRI carrying raw `[`/`]`. The oracle accepts it (rdflib
  and the old renderer both passed brackets through); the grammar refuses it.
  Findings item (h).
* `typed-string-literal` -- `"x"^^xsd:string`. The oracle accepts it (it was
  the form 1,519,235 wire literals used); the grammar refuses it. Item (i).
* `escaped-angle-bracket-in-iri` / `escaped-del-in-iri` -- a `\\uXXXX` UCHAR
  standing for a character RFC 3987 excludes from an IRI. The oracle accepted
  these because it re-escaped them and the bytes round-tripped; the profile now
  admits no escape inside an IRI at all, since a UCHAR that decodes to a
  non-IRI character is still not an IRI. Item (h), same class as the brackets.

Everything else must agree, verdict for verdict. Two classes were expected to
diverge and did not, which is worth recording: raw DEL and raw C1 bytes inside
`<...>` are already refused by rdflib's own IRIREF production, so only their
escaped spellings were ever reachable.
"""

from __future__ import annotations

import importlib.util
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
BINDING_TOOLS = ROOT / "bindings" / "atlas" / "3.1" / "tools"
FIXTURE_ROOT = ROOT / "bindings" / "atlas" / "3.1" / "fixtures"


def _load_rdf_canonical():
    if str(BINDING_TOOLS) not in sys.path:
        sys.path.insert(0, str(BINDING_TOOLS))
    spec = importlib.util.spec_from_file_location(
        "atlas_rdf_canonical", BINDING_TOOLS / "rdf_canonical.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


RDF_CANONICAL = _load_rdf_canonical()


# --------------------------------------------------------------------------
# The oracle: the deleted render-and-compare, restated over one line
# --------------------------------------------------------------------------


def old_check_accepts(content: bytes) -> bool:
    """Return what `_LexicalNQuadsParser.parseline` would have concluded.

    Reject means "this line would not have reached the sink": a parse error, a
    blank node, a non-IRI/literal term, a term the renderer refuses, or a
    rendering that differs from the original bytes.
    """

    from rdflib import BNode, Literal, URIRef
    from rdflib.plugins.parsers.ntriples import (
        URI,
        ParseError,
        W3CNTriplesParser,
        r_literal,
        r_tail,
        r_wspace,
        unquote,
        uriquote,
    )

    class _Reader(W3CNTriplesParser):
        def literal(self):
            if not self.peek('"'):
                return False
            lexical, language, datatype = self.eat(r_literal).groups()
            if language and datatype:
                raise ParseError("Can't have both a language and a datatype")
            datatype_node = URI(uriquote(unquote(datatype))) if datatype else None
            return Literal(
                unquote(lexical),
                lang=language or None,
                datatype=datatype_node,
                normalize=False,
            )

    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError:
        return False
    reader = _Reader()
    reader.line = text
    try:
        reader.eat(r_wspace)
        if not reader.line or reader.line.startswith("#"):
            return False
        subject = reader.subject(None)
        reader.eat(r_wspace)
        predicate = reader.predicate()
        reader.eat(r_wspace)
        obj = reader.object(None)
        reader.eat(r_wspace)
        context = reader.uriref() or reader.nodeid(None)
        reader.eat(r_tail)
        if reader.line:
            return False
    except (ParseError, Exception):  # noqa: BLE001 - any parse failure is a reject
        return False
    terms = (subject, predicate, obj, context)
    if any(isinstance(term, BNode) for term in terms):
        return False
    if not all(isinstance(term, URIRef) for term in (subject, predicate, context)):
        return False
    if not isinstance(obj, (URIRef, Literal)):
        return False
    try:
        rendered = " ".join(
            (*(_old_ntriples_term(term) for term in terms), ".")
        )
    except _OldRenderError:
        return False
    return text == rendered


class _OldRenderError(ValueError):
    """The pre-wave renderer's refusal."""


def _old_ntriples_term(term) -> str:
    """`rdf_canonical.ntriples_term` exactly as it stood before this wave."""

    import re
    import urllib.parse

    from rdflib import BNode, Literal, URIRef

    absolute = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:[^\s]+$")

    def unicode_escape(character: str) -> str:
        codepoint = ord(character)
        return (
            f"\\u{codepoint:04X}" if codepoint <= 0xFFFF else f"\\U{codepoint:08X}"
        )

    if isinstance(term, URIRef):
        value = str(term)
        if not absolute.fullmatch(value):
            raise _OldRenderError(value)
        try:
            parsed = urllib.parse.urlsplit(value)
        except ValueError as exc:
            raise _OldRenderError(value) from exc
        if parsed.username is not None or parsed.password is not None:
            raise _OldRenderError(value)
        escaped = "".join(
            unicode_escape(character)
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
                unicode_escape(character)
                if ord(character) < 0x20 or 0x7F <= ord(character) <= 0x9F
                else character
            )
            for character in str(term)
        )
        rendered = f'"{lexical}"'
        if term.language:
            return f"{rendered}@{term.language}"
        if term.datatype:
            return f"{rendered}^^{_old_ntriples_term(URIRef(term.datatype))}"
        return rendered
    if isinstance(term, BNode):
        raise _OldRenderError(str(term))
    raise _OldRenderError(repr(term))


def new_check_accepts(content: bytes) -> bool:
    return RDF_CANONICAL.canonical_line_issue(content) is None


# --------------------------------------------------------------------------
# The mutation battery
# --------------------------------------------------------------------------

XSD_STRING = b"^^<http://www.w3.org/2001/XMLSchema#string>"

# Each entry: (class name, mutate, expected disagreement reason or None).
#
# `mutate` returns None when the sample line cannot carry that mutation (a
# line with no literal object cannot get a bad escape), and the sample is
# skipped for that class.


def _split(content: bytes) -> tuple[bytes, bytes, bytes, bytes] | None:
    """Split a canonical line into its four terms, or None if it will not."""

    match = RDF_CANONICAL.CANONICAL_LINE_RE.match(content)
    if match is None:
        return None
    return (match.group(1), match.group(2), match.group(3), match.group(4))


def _object_is_literal(content: bytes) -> bool:
    terms = _split(content)
    return terms is not None and terms[2].startswith(b'"')


def _rebuild(terms: tuple[bytes, bytes, bytes, bytes]) -> bytes:
    return b" ".join(terms) + b" ."


def m_identity(content: bytes) -> bytes | None:
    return content


def m_bracket_iri(content: bytes) -> bytes | None:
    terms = _split(content)
    if terms is None:
        return None
    subject, predicate, obj, graph = terms
    return _rebuild((subject, predicate, obj, graph[:-1] + b"[7]>"))


def m_bracket_iri_object(content: bytes) -> bytes | None:
    terms = _split(content)
    if terms is None or terms[2].startswith(b'"'):
        return None
    subject, predicate, obj, graph = terms
    return _rebuild((subject, predicate, obj[:-1] + b"#a[1]>", graph))


def m_typed_string_literal(content: bytes) -> bytes | None:
    terms = _split(content)
    if terms is None or not terms[2].startswith(b'"') or not terms[2].endswith(b'"'):
        return None
    subject, predicate, obj, graph = terms
    return _rebuild((subject, predicate, obj + XSD_STRING, graph))


def m_del_in_iri(content: bytes) -> bytes | None:
    terms = _split(content)
    if terms is None:
        return None
    subject, predicate, obj, graph = terms
    return _rebuild((subject, predicate, obj, graph[:-1] + b"\x7f>"))


def m_c1_in_iri(content: bytes) -> bytes | None:
    terms = _split(content)
    if terms is None:
        return None
    subject, predicate, obj, graph = terms
    return _rebuild((subject, predicate, obj, graph[:-1] + b"\xc2\x85>"))


def m_escaped_a(content: bytes) -> bytes | None:
    if not _object_is_literal(content):
        return None
    return content.replace(b'"', b'"\\u0041', 1)


def m_lowercase_hex_escape(content: bytes) -> bytes | None:
    if not _object_is_literal(content):
        return None
    return content.replace(b'"', b'"\\u00e9', 1)


def m_long_escape(content: bytes) -> bytes | None:
    if not _object_is_literal(content):
        return None
    return content.replace(b'"', b'"\\U0001F600', 1)


def m_solidus_escape(content: bytes) -> bytes | None:
    if not _object_is_literal(content):
        return None
    return content.replace(b'"', b'"\\/', 1)


def m_single_quoted_object(content: bytes) -> bytes | None:
    terms = _split(content)
    if terms is None or not terms[2].startswith(b'"'):
        return None
    subject, predicate, obj, graph = terms
    return _rebuild((subject, predicate, b"'" + obj[1:-1] + b"'", graph))


def m_extra_space(content: bytes) -> bytes | None:
    return content.replace(b"> <", b">  <", 1)


def m_no_space_before_dot(content: bytes) -> bytes | None:
    return content[:-2] + b"."


def m_trailing_space(content: bytes) -> bytes | None:
    return content + b" "


def m_tab_separator(content: bytes) -> bytes | None:
    return content.replace(b"> <", b">\t<", 1)


def m_blank_node_subject(content: bytes) -> bytes | None:
    terms = _split(content)
    if terms is None:
        return None
    _subject, predicate, obj, graph = terms
    return _rebuild((b"_:b0", predicate, obj, graph))


def m_blank_node_object(content: bytes) -> bytes | None:
    terms = _split(content)
    if terms is None:
        return None
    subject, predicate, _obj, graph = terms
    return _rebuild((subject, predicate, b"_:b0", graph))


def m_credentialed_iri(content: bytes) -> bytes | None:
    terms = _split(content)
    if terms is None:
        return None
    _subject, predicate, obj, graph = terms
    return _rebuild((b"<https://user:pass@example.org/x>", predicate, obj, graph))


def m_relative_iri(content: bytes) -> bytes | None:
    terms = _split(content)
    if terms is None:
        return None
    _subject, predicate, obj, graph = terms
    return _rebuild((b"<relative/path>", predicate, obj, graph))


def m_missing_graph(content: bytes) -> bytes | None:
    terms = _split(content)
    if terms is None:
        return None
    subject, predicate, obj, _graph = terms
    return b" ".join((subject, predicate, obj)) + b" ."


def m_escaped_angle_bracket_in_iri(content: bytes) -> bytes | None:
    terms = _split(content)
    if terms is None:
        return None
    subject, predicate, obj, graph = terms
    return _rebuild((subject, predicate, obj, graph[:-1] + b"\\u003C>"))


def m_escaped_del_in_iri(content: bytes) -> bytes | None:
    terms = _split(content)
    if terms is None:
        return None
    subject, predicate, obj, graph = terms
    return _rebuild((subject, predicate, obj, graph[:-1] + b"\\u007F>"))


def m_unescaped_quote(content: bytes) -> bytes | None:
    terms = _split(content)
    if terms is None or not terms[2].startswith(b'"'):
        return None
    subject, predicate, obj, graph = terms
    return _rebuild((subject, predicate, b'"' + obj + b'"', graph))


def m_raw_control(content: bytes) -> bytes | None:
    if not _object_is_literal(content):
        return None
    return content.replace(b'"', b'"\x01', 1)


def m_comment_line(content: bytes) -> bytes | None:
    return b"# " + content


def m_empty(content: bytes) -> bytes | None:
    return b""


def m_uppercase_language_tag(content: bytes) -> bytes | None:
    terms = _split(content)
    if terms is None or b'"@' not in terms[2]:
        return None
    subject, predicate, obj, graph = terms
    body, _, tag = obj.rpartition(b"@")
    return _rebuild((subject, predicate, body + b"@" + tag.upper(), graph))


def m_typed_dateime_literal(content: bytes) -> bytes | None:
    terms = _split(content)
    if terms is None or not terms[2].startswith(b'"') or not terms[2].endswith(b'"'):
        return None
    subject, predicate, obj, graph = terms
    return _rebuild(
        (
            subject,
            predicate,
            obj + b"^^<http://www.w3.org/2001/XMLSchema#dateTime>",
            graph,
        )
    )


# name -> (mutate, deliberate profile change?)
MUTATIONS: dict[str, tuple[object, str | None]] = {
    "identity": (m_identity, None),
    "bracket-iri-graph": (m_bracket_iri, "(h) RFC 3987 excludes [ and ] from an IRI"),
    "bracket-iri-object": (
        m_bracket_iri_object,
        "(h) RFC 3987 excludes [ and ] from an IRI",
    ),
    "typed-string-literal": (
        m_typed_string_literal,
        "(i) the simple form is the only spelling of an xsd:string term",
    ),
    # Raw DEL / C1 bytes inside `<...>`: rdflib's own IRIREF production already
    # refuses them, so the two checks agree without any profile change.
    "raw-del-in-iri": (m_del_in_iri, None),
    "raw-c1-in-iri": (m_c1_in_iri, None),
    # The ESCAPED spellings are the divergence: the old renderer round-tripped
    # `\uXXXX` UCHARs for characters RFC 3987 excludes, so a decoded `<` or DEL
    # inside an IRI was accepted as long as it came back escaped. The profile
    # now admits no escape at all inside an IRI, because a UCHAR that decodes
    # to a non-IRI character is still not an IRI.
    "escaped-angle-bracket-in-iri": (
        m_escaped_angle_bracket_in_iri,
        "(h) no UCHAR may stand for a character RFC 3987 excludes from an IRI",
    ),
    "escaped-del-in-iri": (
        m_escaped_del_in_iri,
        "(h) no UCHAR may stand for a character RFC 3987 excludes from an IRI",
    ),
    "escaped-ascii-letter": (m_escaped_a, None),
    "lowercase-hex-escape": (m_lowercase_hex_escape, None),
    "long-form-escape": (m_long_escape, None),
    "solidus-escape": (m_solidus_escape, None),
    "single-quoted-object": (m_single_quoted_object, None),
    "extra-space": (m_extra_space, None),
    "no-space-before-terminator": (m_no_space_before_dot, None),
    "trailing-space": (m_trailing_space, None),
    "tab-separator": (m_tab_separator, None),
    "blank-node-subject": (m_blank_node_subject, None),
    "blank-node-object": (m_blank_node_object, None),
    "credentialed-iri": (m_credentialed_iri, None),
    "relative-iri": (m_relative_iri, None),
    "missing-graph-term": (m_missing_graph, None),
    "unescaped-quote-in-literal": (m_unescaped_quote, None),
    "raw-control-in-literal": (m_raw_control, None),
    "comment-line": (m_comment_line, None),
    "empty-line": (m_empty, None),
    "uppercase-language-tag": (
        m_uppercase_language_tag,
        (
            "BCP 47 tags are case-insensitive, so the lowercase spelling is "
            "the only one the profile admits"
        ),
    ),
    "typed-datetime-literal": (m_typed_dateime_literal, None),
}


def _real_canonical_lines(limit: int = 400) -> list[bytes]:
    """Sample real canonical lines from the committed conformance fixtures."""

    packs = sorted((FIXTURE_ROOT / "valid" / "all-resource-profiles").rglob("*.nq"))
    if not packs:  # pragma: no cover - the fixtures are generated
        pytest.skip("Atlas 3.1 fixtures are not materialized; run make atlas-v3-fixtures")
    lines: list[bytes] = []
    seen_shapes: set[tuple[bool, bool, bool]] = set()
    for pack in packs:
        for raw in pack.read_bytes().splitlines():
            terms = _split(raw)
            if terms is None:
                continue
            shape = (
                terms[2].startswith(b'"'),
                b'"@' in terms[2],
                b"^^" in terms[2],
            )
            # Keep every distinct object shape, then fill up to `limit`.
            if shape not in seen_shapes or len(lines) < limit:
                seen_shapes.add(shape)
                lines.append(raw)
    assert lines, "no canonical lines found in the valid fixture packs"
    return lines[:limit]


def _samples() -> Iterator[bytes]:
    yield from _real_canonical_lines()


def test_every_sampled_fixture_line_is_canonical() -> None:
    """The grammar must not reject anything the producer actually writes."""

    for line in _samples():
        assert RDF_CANONICAL.canonical_line_issue(line) is None, line


@pytest.mark.parametrize("mutation", sorted(MUTATIONS))
def test_byte_grammar_agrees_with_the_render_and_compare_it_replaced(
    mutation: str,
) -> None:
    mutate, deliberate = MUTATIONS[mutation]
    applied = 0
    for line in _samples():
        mutated = mutate(line)  # type: ignore[operator]
        if mutated is None:
            continue
        applied += 1
        old = old_check_accepts(mutated)
        new = new_check_accepts(mutated)
        if deliberate is None:
            assert old == new, (
                f"{mutation}: the byte grammar and the render-and-compare "
                f"disagree (old={old}, new={new}) on {mutated!r}"
            )
        else:
            assert old is True and new is False, (
                f"{mutation} is recorded as a deliberate profile change "
                f"({deliberate}), so the old check must accept and the new "
                f"one refuse; got old={old}, new={new} on {mutated!r}"
            )
    assert applied, f"{mutation} applied to no sample line"


def test_the_deliberate_divergences_are_exactly_the_wave_decisions() -> None:
    """Nothing may silently join the enumerated list of profile changes."""

    assert {name for name, (_, why) in MUTATIONS.items() if why is not None} == {
        "bracket-iri-graph",
        "bracket-iri-object",
        "typed-string-literal",
        "escaped-angle-bracket-in-iri",
        "escaped-del-in-iri",
        "uppercase-language-tag",
    }


def test_refusal_codes_survive_the_move_to_the_byte_layer() -> None:
    """The two codes the conformance corpus pins are still reachable."""

    issue = RDF_CANONICAL.canonical_line_issue(
        b"_:b0 <https://example.org/p> <urn:x:1> <urn:g:1> ."
    )
    assert issue is not None and issue[0] == "rdf.blank-node"
    issue = RDF_CANONICAL.canonical_line_issue(
        b"<https://user:pass@example.org/x> <https://example.org/p> "
        b"<urn:x:1> <urn:g:1> ."
    )
    assert issue is not None and issue[0] == "rdf.term"
    issue = RDF_CANONICAL.canonical_line_issue(
        b"<urn:x:1> <https://example.org/p> <urn:x:2[7]> <urn:g:1> ."
    )
    assert issue is not None and issue[0] == "rdf.canonical"


def test_the_renderer_refuses_what_the_grammar_refuses() -> None:
    """Emission and acceptance are one profile, so they must refuse together."""

    from rdflib import XSD, Literal, URIRef

    with pytest.raises(RDF_CANONICAL.RdfCanonicalError):
        RDF_CANONICAL.ntriples_term(URIRef("https://example.org/a[1]"))
    with pytest.raises(RDF_CANONICAL.RdfCanonicalError):
        RDF_CANONICAL.ntriples_term(Literal("x", datatype=XSD.string))
    with pytest.raises(RDF_CANONICAL.RdfCanonicalError):
        RDF_CANONICAL.ntriples_term(URIRef("https://example.org/a"))
    with pytest.raises(RDF_CANONICAL.RdfCanonicalError):
        RDF_CANONICAL.ntriples_term(URIRef("https://user:pass@example.org/x"))
    # Refused, not lowercased: coercing here would rewrite a publisher's tag
    # behind its back, and both spellings are one term.
    with pytest.raises(RDF_CANONICAL.RdfCanonicalError, match="lowercase"):
        RDF_CANONICAL.ntriples_term(Literal("x", lang="EN"))
    with pytest.raises(RDF_CANONICAL.RdfCanonicalError, match="lowercase"):
        RDF_CANONICAL.ntriples_term(Literal("x", lang="en-GB"))
    assert RDF_CANONICAL.ntriples_term(Literal("x", lang="en-gb")) == '"x"@en-gb'
    assert RDF_CANONICAL.ntriples_term(Literal("x")) == '"x"'
    assert (
        RDF_CANONICAL.ntriples_term(URIRef("https://example.org/a%5B1%5D"))
        == "<https://example.org/a%5B1%5D>"
    )
