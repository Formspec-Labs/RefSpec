"""Copied compilation checks from 53c0f387; only unchanged helpers are shared."""
import re
from refspec.registry.citation_grammar import (
    EoCompilationLocator, _ANOTHER_CITATION_AHEAD, _normalize_dashes,
)

_COMPILATION_YEAR = r"(?:1[789]|20)\d{2}"


_COMPILATION_WORD = r"(?:Comp|Supp)\.?"


_EO_COMPILATION = re.compile(
    r"\b3\s*C\.?\s*F\.?\s*R\.?\s*[,;:]?\s*"
    # The publisher may write the volume year TWICE, once as the year and once
    # as the volume: 5 CFR 10000's note reads "E.O. 12600, 52 FR 23781, 3 CFR
    # 1987, 1987 Comp., p. 235", and the first 1987 was minted as CFR part
    # 1987. Only where the SECOND number is a year the compilation word
    # follows, so an ordinary part list can never lose its head.
    rf"(?:{_COMPILATION_YEAR}\s*,\s*(?={_COMPILATION_YEAR}\s*,?\s*{_COMPILATION_WORD}))?"
    rf"(?P<start>{_COMPILATION_YEAR})"
    r"(?:"
    r"(?:\s*(?:(?:-\s*){1,2}|/|to|thru|through|and)\s*"
    # A closing year is written three ways: in full, abbreviated to its last
    # two digits, or — where the word "Comp." itself proves the shape — as
    # whatever four digits the publisher typed. "3 CFR, 1971-1075 Comp., p.
    # 793" is the 1971-1975 volume with a mis-keyed digit (2 rows), and
    # refusing it left the volume's FIRST year minted as CFR part 1971. The
    # typo is carried, not corrected: the end reads "1075".
    rf"(?P<end>{_COMPILATION_YEAR}|\d{{4}}(?=\s*,?\s*{_COMPILATION_WORD})|\d{{2}}(?!\d)))"
    rf"\s*,?\s*(?:{_COMPILATION_WORD})?"
    rf"|\s*,?\s*{_COMPILATION_WORD}"
    # A PAGE LABEL proves the shape where the compilation word is missing, on
    # the same terms a year range does: no CFR part is ever cited "p. 235".
    # 12 CFR 602's note writes "52 FR 23781, 3 CFR 1987, p. 235" and minted
    # part 1987. A bare number after the year still proves nothing and is
    # still refused -- the label is the whole evidence.
    r"|(?=\s*,?\s*(?:pp?\.?|pages?)\s*\d)"
    r")"
    rf"(?:\s*,?\s*(?:pp?\.?|pages?)?\s*(?P<page>\d+){_ANOTHER_CITATION_AHEAD})?",
    re.IGNORECASE,
)


def _compilation_end(match: re.Match[str]) -> str | None:
    """The volume's closing year, with an abbreviated one spelled out.

    "1949-53" names the 1949-1953 compilation, and the two digits are the
    same abbreviation :func:`_abbreviated_span` reads in a section span: the
    repeated leading digits are dropped. Here the endpoints are YEARS, so what
    is dropped is always the century — no ambiguity and no guard beyond
    ordering, which refuses a pair that does not ascend.
    """

    end = match.group("end")
    if end is None or len(end) == 4:
        return end
    spelled = f"{match.group('start')[:2]}{end}"
    return spelled if int(spelled) > int(match.group("start")) else end


def parse_eo_compilation_locators(text: str) -> tuple[EoCompilationLocator, ...]:
    """Read every Title 3 compilation locator, identifying nothing."""

    normalized = _normalize_dashes(text)
    return tuple(
        EoCompilationLocator(
            compilation_start=match.group("start"),
            compilation_end=_compilation_end(match),
            page=match.group("page"),
        )
        for match in _EO_COMPILATION.finditer(normalized)
    )


def _excise_compilations(text: str) -> str:
    """Blank out compilation locators so the CFR grammar cannot read them.

    "3 CFR, 1977 Comp., p. 123" is not a CFR citation, and left in place it
    parses as title 3, part 1977 — plausible on every axis and entirely
    fabricated. Spans are replaced with spaces so every other citation keeps
    its offsets.
    """

    def _blank(match: re.Match[str]) -> str:
        return " " * (match.end() - match.start())

    return _EO_COMPILATION.sub(_blank, text)
