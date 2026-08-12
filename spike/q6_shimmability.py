"""Q6 -- can the two oxigraph incompatibilities be shimmed or ETL'd?

  census    how many terms of each affected form the real distributions carry
  etl       a streaming byte ETL that percent-encodes the IRI characters
            oxigraph refuses, measured, and then loaded into oxigraph in full
  converter what remains wrong after patching oxrdflib's `from_ox` with
            normalize=False (the cheap half of the shim)

    .venv/bin/python spike/q6_shimmability.py <census|etl|converter> [full]
"""

from __future__ import annotations

import gc
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import common  # noqa: E402

FULL_ROOT = Path("/Users/mikewolfd/Work/spicy-regs/RefSpec/output/atlas-3.1-full-2026-08-12")
STAGING = common.STAGING

XSD_STRING = b"^^<http://www.w3.org/2001/XMLSchema#string>"
# An N-Quads object literal that ends the line with neither @lang nor ^^<dt>.
PLAIN_LITERAL = re.compile(rb'" <[^>]*> \.\n?$')
TYPED_TAIL = re.compile(rb'\^\^<([^>]*)> <[^>]*> \.\n?$')


def _zstd():
    try:
        from compression import zstd
    except ImportError:
        from backports import zstd
    return zstd


def _root(argv: list[str]) -> Path:
    return FULL_ROOT if "full" in argv[2:] else STAGING


def census(root: Path) -> None:
    zstd = _zstd()
    packs = json.loads((root / "atlas-manifest.json").read_bytes())["packs"]
    plain = typed_string = other_typed = lang = 0
    datatypes: dict[bytes, int] = {}
    with common.Timer("census") as t:
        for pack in packs:
            with zstd.open(root / pack["path"], "rb") as fh:
                for line in fh:
                    if PLAIN_LITERAL.search(line):
                        plain += 1
                    elif XSD_STRING in line:
                        typed_string += 1
                    else:
                        m = TYPED_TAIL.search(line)
                        if m:
                            other_typed += 1
                            datatypes[m.group(1)] = datatypes.get(m.group(1), 0) + 1
                        elif re.search(rb'"@[A-Za-z-]+ <[^>]*> \.\n?$', line):
                            lang += 1
    common.emit(
        {
            "q": 6,
            "probe": "census",
            "root": root.name if root is FULL_ROOT else "staging",
            "plain_literals": plain,
            "xsd_string_typed_literals": typed_string,
            "other_typed_literals": other_typed,
            "lang_tagged_literals": lang,
            "datatypes": {k.decode(): v for k, v in sorted(datatypes.items(), key=lambda kv: -kv[1])[:12]},
            "wall_s": round(t.wall, 2),
        }
    )


# --------------------------------------------------------------------------- ETL

# Characters RFC 3987 forbids in an IRI that appear in real Atlas sourceLocators.
_ESCAPE = {ord("["): b"%5B", ord("]"): b"%5D"}
_IRI = re.compile(rb"<[^<>\"]*>")


def _escape_iris(line: bytes) -> bytes:
    """Percent-encode `[`/`]` inside IRI positions only, leaving literals alone."""

    if b"[" not in line and b"]" not in line:
        return line
    out = bytearray()
    i = 0
    in_literal = False
    while i < len(line):
        c = line[i]
        if c == 0x22:  # '"'
            in_literal = not in_literal
            out.append(c)
        elif c == 0x5C and in_literal:  # backslash inside a literal
            out.append(c)
            i += 1
            if i < len(line):
                out.append(line[i])
        elif c == 0x3C and not in_literal:  # '<' opens an IRI
            j = line.index(b">", i)
            iri = line[i : j + 1]
            for bad, repl in _ESCAPE.items():
                iri = iri.replace(bytes([bad]), repl)
            out.extend(iri)
            i = j
        elif c in _ESCAPE and not in_literal:
            out.extend(_ESCAPE[c])
        else:
            out.append(c)
        i += 1
    return bytes(out)


def etl(root: Path) -> None:
    """Stream every pack through the escaper straight into an oxigraph Store."""

    import pyoxigraph as ox

    zstd = _zstd()
    packs = json.loads((root / "atlas-manifest.json").read_bytes())["packs"]
    store = ox.Store()
    rewritten = 0
    quads = 0
    gc.collect()
    with common.Timer("etl") as t:
        for pack in packs:
            buf = bytearray()
            with zstd.open(root / pack["path"], "rb") as fh:
                for line in fh:
                    fixed = _escape_iris(line)
                    rewritten += fixed is not line and fixed != line
                    buf += fixed
                    if len(buf) > (32 << 20):
                        store.load(bytes(buf), format=ox.RdfFormat.N_QUADS)
                        buf.clear()
            if buf:
                store.load(bytes(buf), format=ox.RdfFormat.N_QUADS)
        quads = len(store)
    common.emit(
        {
            "q": 6,
            "probe": "etl",
            "root": root.name if root is FULL_ROOT else "staging",
            "lines_rewritten": rewritten,
            "quads_in_store": quads,
            "wall_s": round(t.wall, 2),
            "cpu_s": round(t.cpu, 2),
            "peak_rss_gb": round(common.peak_rss_gb(), 3),
        }
    )


# --------------------------------------------------------------------- converter


def converter(_root: Path) -> None:
    """Patch oxrdflib's from_ox the cheap way and see which losses survive."""

    import oxrdflib._converter as C
    import pyoxigraph as ox
    from rdflib import BNode, Literal, URIRef, XSD

    def patched_from_ox(term):
        if isinstance(term, ox.Literal):
            if term.language:
                return Literal(term.value, lang=term.language, normalize=False)
            dt = term.datatype.value
            if dt == str(XSD.string):
                return Literal(term.value, normalize=False)  # guess: simple form
            return Literal(term.value, datatype=URIRef(dt), normalize=False)
        if isinstance(term, ox.NamedNode):
            return URIRef(term.value)
        if isinstance(term, ox.BlankNode):
            return BNode(term.value)
        return None

    cases = [
        Literal("04", normalize=False),
        Literal("04", datatype=XSD.string, normalize=False),
        Literal("1.00", datatype=XSD.decimal, normalize=False),
        Literal("+1", datatype=XSD.integer, normalize=False),
        Literal("2026-08-12T00:00:00Z", datatype=XSD.dateTime, normalize=False),
        Literal("TRUE", datatype=XSD.boolean, normalize=False),
        Literal("hello", lang="en", normalize=False),
    ]
    bad = 0
    for term in cases:
        back = patched_from_ox(C.to_ox(term))
        same = str(term) == str(back) and term.datatype == back.datatype and term.language == back.language
        bad += not same
        print(f"  {term.n3()[:66]:<68} -> {back.n3()[:66]:<68} {'OK' if same else 'CHANGED'}")
    common.emit({"q": 6, "probe": "converter", "still_changed": bad, "cases": len(cases)})


def etl_count(root: Path) -> None:
    """The same ETL, but parse-count instead of store -- constant memory.

    This is the decisive question at full scale: after escaping, does oxigraph
    accept every one of the 29,283,283 quads it refused before?
    """

    import pyoxigraph as ox

    zstd = _zstd()
    packs = json.loads((root / "atlas-manifest.json").read_bytes())["packs"]
    rewritten = 0
    quads = 0
    refused: list[str] = []
    gc.collect()
    with common.Timer("etl-count") as t:
        for pack in packs:
            buf = bytearray()
            n = 0
            with zstd.open(root / pack["path"], "rb") as fh:
                for line in fh:
                    fixed = _escape_iris(line)
                    rewritten += fixed != line
                    buf += fixed
                    if len(buf) > (32 << 20):
                        try:
                            n += sum(1 for _ in ox.parse(bytes(buf), format=ox.RdfFormat.N_QUADS))
                        except SyntaxError as exc:
                            refused.append(f"{pack['path']}: {exc}")
                            break
                        buf.clear()
            if buf:
                try:
                    n += sum(1 for _ in ox.parse(bytes(buf), format=ox.RdfFormat.N_QUADS))
                except SyntaxError as exc:
                    refused.append(f"{pack['path']}: {exc}")
            quads += n
    common.emit(
        {
            "q": 6,
            "probe": "etl-count",
            "root": root.name if root is FULL_ROOT else "staging",
            "lines_rewritten": rewritten,
            "quads_accepted": quads,
            "packs_still_refused": refused[:5],
            "wall_s": round(t.wall, 2),
            "cpu_s": round(t.cpu, 2),
            "peak_rss_gb": round(common.peak_rss_gb(), 3),
        }
    )


PROBES = {"census": census, "etl": etl, "etl-count": etl_count, "converter": converter}


def main() -> None:
    PROBES[sys.argv[1]](_root(sys.argv))


if __name__ == "__main__":
    main()
