"""Frozen generation-2 byte-regex kernels, copied here as independent test oracles.

Source: research/evidence/usc-section-oracle-2026-08-24/scripts/extract_*.py.
Only archive/file I/O and table writes are replaced by return values. Production
must not import this module. Keep parser improvements in the named divergence
tests instead of changing this baseline.
"""

import re

_DASHES = str.maketrans(dict.fromkeys("‐‑‒–—―−\x96\x97", "-"))


def release(data, *, appendix=False):
    """Frozen release-XML kernel: section/range/subsection/chapter identifiers into lowercased key sets.

    ``appendix=True`` skips subsections and chapters, matching the generation-2
    reader's treatment of appendix files.
    """

    exact, ranges, subsections, chapters = set(), set(), set(), set()
    for match in re.finditer(rb"<section\b[^>]*>", data):
        tag = match.group()
        identifier = re.search(rb'identifier="([^"]*)"', tag)
        if identifier is None:
            continue
        stated_status = re.search(rb'status="([^"]*)"', tag)
        status = stated_status[1].decode() if stated_status else "current"
        for piece in identifier[1].decode().translate(_DASHES).split():
            found = re.match(r"^/us/usc/t(\d+)/s(.+)$", piece)
            if found is None:
                continue
            title, section = int(found[1]), found[2]
            if "..." in section:
                low, _, high = section.partition("...")
                ranges.add((title, low.lower(), high.lower(), status, piece))
            else:
                exact.add((title, section.lower(), status))
    if not appendix:
        for match in re.finditer(rb'identifier="/us/usc/t(\d+)/s([^"/]+)/([a-zA-Z0-9]+)"', data):
            subsections.add((int(match[1]), match[2].decode().translate(_DASHES).lower(), match[3].decode().lower()))
        for match in re.finditer(rb"<chapter\b[^>]*>", data):
            identifier = re.search(rb'identifier="([^"]*)"', match.group())
            if identifier is None:
                continue
            for piece in identifier[1].decode().translate(_DASHES).split():
                found = re.match(r"^/us/usc/t(\d+)(?:/[a-zA-Z]+[A-Za-z0-9]*)*?/ch([^/]+)$", piece)
                if found and "..." not in found[2]:
                    chapters.add((int(found[1]), found[2].lower()))
    return {"sections": exact, "ranges": ranges, "subsections": subsections, "chapters": chapters}


def annual(data, *, year, title, appendix=False):
    """Frozen annual-archive kernel: ``Secs.`` itempath comments into exact and ``X to Y`` range keys."""

    exact, ranges = set(), set()
    token = re.compile(r"^[0-9][0-9A-Za-z.\-]*$")
    for match in re.finditer(rb"<!-- itempath:([^>]*?) -->", data):
        tail = match[1].decode("utf-8", "replace").rsplit("/", 1)[-1]
        found = re.match(r"Secs?\.\s+(.*)$", tail)
        if found is None:
            continue
        body = found[1].strip().translate(_DASHES)
        for chunk in body.split(","):
            chunk = chunk.strip()
            span = re.fullmatch(r"(\S+)\s+to\s+(\S+)", chunk)
            if span and token.match(span[1]) and token.match(span[2]):
                ranges.add((year, title, appendix, span[1].lower(), span[2].lower()))
            elif token.match(chunk):
                exact.add((year, title, appendix, chunk.lower()))
    return {"annual_sections": exact, "annual_ranges": ranges}
