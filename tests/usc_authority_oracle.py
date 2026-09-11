"""Frozen authority reader from 48617754; unchanged helpers shared, matcher copied."""
from refspec.registry.citation_grammar import (
    _ADMINISTRATIVE_ORDER,
    _ADMINISTRATIVE_ORDER_LIST_TAIL,
    _BARE_USC_TITLE,
    _BARE_USC_TITLE_LONGHAND,
    _CASE_REPORTER,
    _CASE_US_PERIODLESS,
    _CFR_TITLE_IMPOSSIBLE_IS_FR,
    _COMPILATION_FRAGMENT,
    _CONSTITUTION,
    _DC_CODE_ANCHOR,
    _DC_CODE_BARE_SECTION,
    _DC_CODE_SECTION,
    _DEPARTMENTAL_MANUAL,
    _DFARS_SELF_CITATION,
    _DIRECTIVE_SYSTEMS,
    _EO_COMPILATION,
    _EXECUTIVE_ORDER_ABBREVIATED,
    _EXECUTIVE_ORDER_LIST_TAIL,
    _EXECUTIVE_ORDER_SPELLED,
    _FAR_SELF_CITATION,
    _OMB_INSTRUMENT,
    _PRESIDENTIAL_DOCUMENT_KINDS,
    _PROCLAMATION,
    _PUBLIC_LAW,
    _PUBLIC_LAW_DOT,
    _REORGANIZATION_PLAN,
    _REVISED_STATUTES,
    _RIN_TOKEN,
    _STATUTE_AT_LARGE,
    _STATUTE_LETTERED_PAGE,
    _STATUTE_LETTERED_VOLUME,
    _TREATY_INSTRUMENT_NAME,
    _TREATY_SERIES,
    _USC_APPENDIX,
    _USC_CHAPTER,
    _USC_CODE_FORMS,
    _USC_LIST_TAIL,
    _USC_STANDARD,
    _USC_TITLE_FORM,
    _USC_TITLE_FORM_ITEM,
    _USC_TITLE_WITH_DESIGNATOR,
    _USC_TRANSPOSED_LABEL,
    FR_PAGE_HIGHEST_KNOWN,
    FR_VOLUME_HIGHEST_KNOWN,
    USC_SPAN_ABBREVIATED,
    Any,
    AuthorityCitation,
    Callable,
    _cfr_title_is_possible,
    _congress_beside,
    _lies_inside,
    _normalize_dashes,
    _part_is_plausible,
    _repair_whole_value_label,
    _spans_owning_their_comma,
    _status_for_span,
    _statute_lettered_page,
    _usc_leading_section_is_untruncated,
    _usc_section,
    _usc_section_fields,
    parse_cfr_citations,
    parse_eo_compilation_locators,
    parse_federal_register_citations,
    re,
    replace,
    stated_act_name,
    stated_section,
    states_nothing,
    statutes_volume_matches_congress,
)

_USC_NOTE_TAIL = re.compile(r"\s+notes?\b")


def parse_authority_citation(text: str) -> tuple[AuthorityCitation, ...]:
    """Read every legal authority in one string, with a status instead of silence.

    Every input yields at least one result: unreadable text is retained as an
    ``other``/``failed`` row, and a citation embedded in extra prose is
    ``partial`` rather than discarded. The Unified Agenda's
    ``LEGAL_AUTHORITY_LIST`` carries 755,727 of these.

    The families are read in a fixed order, and three places in that order are
    load-bearing rather than incidental: the U.S.C. appendix form is read
    before the plain one, the unnamed-instrument treaty read follows the
    series ones it defers to, and the whole-value fallbacks run only after
    everything else has read nothing. Every other family is independent of
    every other, and the order it happens to sit in is the order its rows are
    published in — which the Agenda tables carry as ``ordinal``, so it is not
    free to change.
    """

    normalized = _repair_whole_value_label(_normalize_dashes(text.strip()))
    if states_nothing(normalized):
        # A placeholder is not a failed parse: the publisher said nothing.
        return (AuthorityCitation(authority_type="unstated", parse_status="failed"),)

    citations: list[AuthorityCitation] = []

    def _add(citation: AuthorityCitation) -> None:
        # An EXPANDED span is never "ok", and the rule saying so is here rather
        # than at each of the six places a section citation is constructed.
        # "ok" means this module accounts for the whole string, and for an
        # abbreviation it would also be claiming the sections BETWEEN the two
        # endpoints — a claim the grammar cannot check, because the
        # section-existence oracle imports this module and so cannot be
        # imported by it. Five of the 68 abbreviated tokens in the pinned
        # corpus expand to spans that are mostly not law; the status is what a
        # consumer filtering on "ok" sees without reading this file.
        if citation.usc_section_span_rule == USC_SPAN_ABBREVIATED and citation.parse_status == "ok":
            citation = replace(citation, parse_status="partial")
        if citation not in citations:
            citations.append(citation)

    def _read(
        pattern: re.Pattern[str],
        fields: Callable[[re.Match[str]], dict[str, Any]],
        *,
        status: str | None = None,
        covered_end: Callable[[re.Match[str]], int] | None = None,
    ) -> list[re.Match[str]]:
        """Emit one row per match of ``pattern``, statused by what it covered.

        One sentence, written once: a match is a row, and a row is "ok" only
        when its own span leaves nothing behind but an ignorable tail. Twenty
        families restated that sentence by hand before this, which is twenty
        chances for one restatement to drift from the other nineteen.

        ``covered_end`` is for a family that CONSUMES more than it carries — a
        range tail the ordering rule declines, a dropped end leaf — where the
        uncovered characters must still count against "ok". ``status`` is for
        a family that can never cover a whole value whatever it matched.
        """

        matches = list(pattern.finditer(normalized))
        for match in matches:
            end = match.end() if covered_end is None else covered_end(match)
            _add(
                AuthorityCitation(
                    parse_status=status or _status_for_span(normalized, match.start(), end),
                    **fields(match),
                )
            )
        return matches

    # The appendix form is read FIRST and its spans fence the plain form off:
    # "50 U.S.C. app. 2401" must not also read as plain 50 U.S.C. 2401, which
    # is a different place. Measured over the 42,642 distinct authority values
    # the Agenda carries, the fence never fires — "app" is not a section
    # marker, so _USC_STANDARD reads nothing inside an appendix citation. The
    # fence stays anyway: what makes it inert is a property of the marker set,
    # and the marker set is exactly the kind of thing a later reader widens.
    appendix_matches = _read(
        _USC_APPENDIX,
        lambda m: {
            "authority_type": "usc",
            "usc_title": int(m.group("title")),
            "usc_appendix": True,
            **_usc_section_fields(m.group("section")),
        },
    )
    appendix_spans = [match.span() for match in appendix_matches]

    # A U.S.C. match may consume more or less text than it carries, and both
    # move where its coverage ends: a range tail the ordering rule declines is
    # consumed and dropped, and a statutory note is law printed under the
    # section — carried as a flag, and therefore covered rather than left as
    # an uncovered tail. This is the one family whose span is not its match.
    usc_matches: list[re.Match[str]] = []
    for pattern, named_title in _USC_CODE_FORMS:
        matches = list(pattern.finditer(normalized))
        if pattern is _USC_STANDARD:
            usc_matches = matches
        for match in matches:
            if any(start <= match.start() and match.end() <= end for start, end in appendix_spans):
                continue
            # The match still stands (it seeds :data:`_USC_LIST_TAIL`'s scan
            # from wherever it ends) even when the section it carries is a
            # CFR regulation number truncated at the dot rather than a real
            # Code section — see ``_usc_leading_section_is_untruncated`` and
            # :data:`_A_DOTTED_NUMBER_IS_A_CFR_SECTION`. Only the fabricated
            # row is withheld.
            if not _usc_leading_section_is_untruncated(normalized, match):
                continue
            fields = _usc_section_fields(match.group("section"), match.groupdict().get("range_end"))
            covered_end = (
                match.end("section")
                if match.groupdict().get("range_end") is not None and fields["usc_section_end"] is None
                else match.end()
            )
            note = _USC_NOTE_TAIL.match(normalized, covered_end)
            if note is not None:
                covered_end = note.end()
            title = match.groupdict().get("title")
            _add(
                AuthorityCitation(
                    authority_type="usc",
                    parse_status=_status_for_span(normalized, match.start(), covered_end),
                    usc_title=int(title) if title else named_title,
                    usc_note=note is not None,
                    **fields,
                )
            )

    # The transposed label: "21 UCS 374" is 21 U.S.C. 374 (uppercase only;
    # adjacent transposition is the named operator). "UCS" is unreachable by
    # _USC_CODE_NAME, so this family shadows no true spelling whatever order
    # it is read in.
    _read(
        _USC_TRANSPOSED_LABEL,
        lambda m: {
            "authority_type": "usc",
            "usc_title": int(m.group("title")),
            **_usc_section_fields(m.group("section")),
        },
    )

    for match in _USC_TITLE_FORM.finditer(normalized):
        title = int(match.group("title"))
        _add(
            AuthorityCitation(
                authority_type="usc",
                parse_status=_status_for_span(normalized, match.start(), match.end()),
                usc_title=title,
                **_usc_section_fields(match.group("first")),
            )
        )
        # A listed member is never covered by the head's span, so it is
        # partial whatever the head was.
        for item in _USC_TITLE_FORM_ITEM.finditer(match.group("items") or ""):
            _add(
                AuthorityCitation(
                    authority_type="usc",
                    parse_status="partial",
                    usc_title=title,
                    usc_section=_usc_section(item.group("section")),
                )
            )

    # A deviation from citations.py, which kept chapters out of the authority
    # parse entirely: the Agenda's authority field does cite chapters, and a
    # typed row beats an "other/failed" one.
    _read(
        _USC_CHAPTER,
        lambda m: {
            "authority_type": "usc_chapter",
            "usc_title": int(m.group("title")),
            "usc_chapter": m.group("chapter").lower(),
            "usc_chapter_end": (m.group("chapter_end") or "").lower() or None,
        },
    )

    public_law_matches: list[re.Match[str]] = []
    for pattern in (_PUBLIC_LAW, _PUBLIC_LAW_DOT):
        public_law_matches += _read(
            pattern,
            lambda m: {
                "authority_type": "public_law",
                "public_law": f"{int(m.group('congress'))}-{int(m.group('number'))}",
            },
        )

    # The one verdict that reads a NEIGHBOUR rather than its own match: a
    # Statutes volume is judged against the Public Law standing beside it,
    # because neither half is checkable alone.
    #
    # It is written HERE, once, because TWO readers below mint the
    # ``statute_volume`` column and the verdict lived inside one of them. The
    # lettered-page reader minted a volume with a permanently NULL verdict —
    # 30 distinct values / 369 rows of the pinned table, of which 24 values /
    # 328 rows state exactly one Public Law in the same string (measured
    # 2026-08-22). Whether a citation is judged now depends on the citation
    # and not on which reader happened to match it.
    #
    # The lettered-VOLUME reader is deliberately not a third caller: "70A
    # Stat." leaves ``statute_volume`` NULL because 70A is not volume 70, and
    # this relation judges the integer series.
    def _volume_verdict(match: re.Match[str]) -> bool | None:
        return statutes_volume_matches_congress(
            _congress_beside(normalized, public_law_matches, match), int(match.group("volume"))
        )

    # Lettered pages are read before the integer grammar, which cannot reach
    # them at all ("2763A" fails its boundary guard) — so the order is for the
    # reader, not for correctness. A range tail's end leaf is carried in the
    # page text and therefore covered; a tail the ordering rule declines is
    # consumed, uncarried and uncovered, which keeps that row partial.
    _read(
        _STATUTE_LETTERED_PAGE,
        lambda m: {
            "authority_type": "statute_at_large",
            "statute_volume": int(m.group("volume")),
            "statute_page_text": _statute_lettered_page(m)[0],
            "statute_volume_matches_public_law": _volume_verdict(m),
        },
        covered_end=lambda m: _statute_lettered_page(m)[1],
    )
    _read(
        _STATUTE_LETTERED_VOLUME,
        lambda m: {
            "authority_type": "statute_at_large",
            "statute_volume_text": m.group("volume").upper(),
            "statute_page": int(m.group("page")),
        },
    )
    _read(
        _STATUTE_AT_LARGE,
        lambda m: {
            "authority_type": "statute_at_large",
            "statute_volume": int(m.group("volume")),
            "statute_page": int(m.group("page")),
            "statute_volume_matches_public_law": _volume_verdict(m),
        },
    )

    for pattern in (_EXECUTIVE_ORDER_SPELLED, _EXECUTIVE_ORDER_ABBREVIATED):
        for match in pattern.finditer(normalized):
            _add(
                AuthorityCitation(
                    authority_type="executive_order",
                    parse_status=_status_for_span(normalized, match.start(), match.end()),
                    executive_order=str(int(match.group("number"))),
                )
            )
            # A number list continues the citation: "Executive Orders 13990
            # and 14008" names two orders, and reading one is dropping one.
            # No plural label is demanded, and the corpus is why — "E.O.
            # 11302, 13520" and "EO 10577, 11222, 11478, and 12106" write the
            # label singular and list anyway (3 distinct values, measured
            # 2026-08-22). This is the Agenda's structured field, where the
            # whole value is the citation, so it takes the same "always"
            # policy parse_cfr_citations offers that field.
            position = match.end()
            while (item := _EXECUTIVE_ORDER_LIST_TAIL.match(normalized, position)) is not None:
                _add(
                    AuthorityCitation(
                        authority_type="executive_order",
                        parse_status="partial",
                        executive_order=str(int(item.group("number"))),
                    )
                )
                position = item.end()

    _read(
        _CASE_REPORTER,
        lambda m: {
            "authority_type": "case_citation",
            "case_reporter": re.sub(r"\s+", " ", m.group("reporter")).strip(),
            "case_volume": int(m.group("volume")),
            "case_page": int(m.group("page")),
        },
    )
    _read(
        _CASE_US_PERIODLESS,
        lambda m: {
            "authority_type": "case_citation",
            "case_reporter": "U. S.",
            "case_volume": int(m.group("volume")),
            "case_page": int(m.group("page")),
        },
    )

    _read(
        _PROCLAMATION,
        lambda m: {
            "authority_type": "presidential_document",
            "presidential_doc_kind": "proclamation",
            "proclamation": str(int(m.group("number"))),
        },
    )
    for pattern, kind in _PRESIDENTIAL_DOCUMENT_KINDS:
        # Date-identified documents carry a kind and no number, so the match
        # never covers the value that states the date: partial always.
        _read(
            pattern,
            lambda _m, kind=kind: {"authority_type": "presidential_document", "presidential_doc_kind": kind},
            status="partial",
        )

    _read(
        _OMB_INSTRUMENT,
        lambda m: {
            "authority_type": "administrative_order",
            # "Memoranda" is the plural of one instrument, not a second one.
            "admin_order_kind": "OMB " + (
                "Memorandum" if m.group("kind").startswith("Memorand") else m.group("kind")
            ),
            "admin_order_number": m.group("number"),
        },
    )
    _read(
        _DEPARTMENTAL_MANUAL,
        lambda m: {
            "authority_type": "administrative_order",
            "admin_order_kind": "Departmental Manual",
            "admin_order_number": f"{m.group('part')} DM {m.group('chapter')}",
        },
    )
    for pattern, directive_kind in _DIRECTIVE_SYSTEMS:
        _read(
            pattern,
            lambda m, kind=directive_kind: {
                "authority_type": "administrative_order",
                "admin_order_kind": kind,
                "admin_order_number": m.group("number"),
            },
        )
    for match in _read(
        _ADMINISTRATIVE_ORDER,
        lambda m: {
            "authority_type": "administrative_order",
            "admin_order_kind": re.sub(r"\s+", " ", m.group("kind")).replace("’", "'").rstrip("s"),
            "admin_order_number": re.sub(r"\s", "", m.group("number")),
        },
    ):
        # A listed order is never covered by the head's span, so it is partial
        # whatever the head was — the Executive Order list's own posture.
        kind = re.sub(r"\s+", " ", match.group("kind")).replace("’", "'").rstrip("s")
        position = match.end()
        while (item := _ADMINISTRATIVE_ORDER_LIST_TAIL.match(normalized, position)) is not None:
            _add(
                AuthorityCitation(
                    authority_type="administrative_order",
                    parse_status="partial",
                    admin_order_kind=kind,
                    admin_order_number=re.sub(r"\s", "", item.group("number")),
                )
            )
            position = item.end()

    series_read = False
    for pattern, series in _TREATY_SERIES:
        matched = _read(
            pattern,
            lambda m, series=series: {
                "authority_type": "treaty",
                "treaty_series": series,
                "treaty_volume": int(m["volume"]) if m.groupdict().get("volume") else None,
                "treaty_number": (
                    f"{m['congress']}-{m['number']}"
                    if m.groupdict().get("congress")
                    else m.groupdict().get("number")
                ),
                "treaty_page": int(m["page"]) if m.groupdict().get("page") else None,
            },
        )
        series_read = series_read or bool(matched)

    # An instrument named without a series token — CITES, the Chicago
    # Convention, the Compacts of Free Association — is typed by kind alone,
    # the presidential-memoranda convention: partial always, the name in the
    # original text, no series identifier minted. It defers to a series token
    # in the same value (3 distinct values carry both, measured 2026-08-22),
    # which is why it is read after them and not before.
    if not series_read:
        _read(_TREATY_INSTRUMENT_NAME, lambda _m: {"authority_type": "treaty"}, status="partial")

    _read(
        _REVISED_STATUTES,
        lambda m: {"authority_type": "revised_statute", "revised_statute_section": m.group("section")},
    )

    for match in _DC_CODE_ANCHOR.finditer(normalized):
        position = match.end()
        sections: list[str] = []
        if match.group("title") is not None:
            # The older title-first spelling: "26 DC Code 102" is title 26,
            # section 102 — the same compound the modern form writes "26-102",
            # read to it the way the inverted U.S.C. appendix order is.
            bare = _DC_CODE_BARE_SECTION.match(normalized, position)
            if bare is not None:
                sections.append(f"{int(match.group('title'))}-{bare.group('section')}")
                position = bare.end()
        else:
            while (item := _DC_CODE_SECTION.match(normalized, position)) is not None:
                sections.append(item.group("section"))
                position = item.end()
        if sections:
            status = _status_for_span(normalized, match.start(), position)
            for section in sections:
                _add(
                    AuthorityCitation(
                        authority_type="dc_code",
                        parse_status=status,
                        dc_code_section=section,
                    )
                )
        else:
            # Naming the Code without a readable section still types the row.
            _add(AuthorityCitation(authority_type="dc_code", parse_status="partial"))

    _read(
        _CONSTITUTION,
        lambda m: {
            "authority_type": "constitution",
            "constitution_article": m.group("article"),
            "constitution_section": m.group("section"),
        },
    )

    # A Title 3 compilation locator cited AS the authority — the grammar for
    # it predates this loop and was simply never wired here.
    for locator in parse_eo_compilation_locators(normalized):
        _add(
            AuthorityCitation(
                authority_type="eo_compilation",
                parse_status="partial",
                eo_compilation_start=locator.compilation_start,
                eo_compilation_page=locator.page,
            )
        )
    # A compilation fragment that lost its "3 CFR" head: "1991 Comp p 351".
    # Whole-value only; the year may be gone too ("Comp., p. 193"), and a
    # locator missing its volume is partial like every other.
    _read(
        _COMPILATION_FRAGMENT,
        lambda m: {
            "authority_type": "eo_compilation",
            "eo_compilation_start": m.group("year"),
            "eo_compilation_page": m.group("page"),
        },
        status="partial",
    )

    _read(
        _REORGANIZATION_PLAN,
        lambda m: {
            "authority_type": "reorganization_plan",
            "reorganization_plan": f"{int(m.group('number'))}-of-{m.group('year')}",
        },
    )

    # A CFR citation in the authority field is a real citation in the wrong
    # column — 7,092 of them, "delegation of authority at 49 CFR 1.95" the
    # commonest. Typed as what it is rather than left "failed"; the field's
    # semantics stay the consumer's question. A part-less citation still names
    # its title: "3 CFR" and "48 CFR ch 1" are 63 Agenda authority values, and
    # the title is what they state.
    for cfr in parse_cfr_citations(normalized):
        if not cfr.title_is_possible:
            continue
        _add(
            AuthorityCitation(
                authority_type="cfr",
                parse_status="partial",
                cfr_title=cfr.cfr_title,
                cfr_part=cfr.cfr_part,
                cfr_section=cfr.cfr_section,
                cfr_part_is_plausible=cfr.part_is_plausible,
            )
        )

    # A regulation that cites itself by its own name, where the instrument
    # publishes the equivalence to a CFR part: FAR 1.105-2 declares "(FAR) 48
    # CFR 1.301" the parallel form, and the OFR prints "DFARS Part 201" in the
    # heading of 48 CFR 201. Both are whole-value only, so the English word
    # "far" can never donate one, and both are the same claim — a self-named
    # part IS the title 48 part — so they are one table rather than two blocks.
    for pattern in (_FAR_SELF_CITATION, _DFARS_SELF_CITATION):
        _read(
            pattern,
            lambda m: {
                "authority_type": "cfr",
                "cfr_title": 48,
                "cfr_part": m.group("part"),
                # Both self-citations read the section after the dot, and both
                # threw it away for want of a column: "FAR 1.105-2" is not
                # part 1 wholesale, and neither is "DFARS 201.3".
                "cfr_section": m.group("section"),
                "cfr_part_is_plausible": _part_is_plausible(m.group("part")),
            },
            status="partial",
        )

    # A Federal Register citation in the authority field is, like the CFR
    # family above, a real citation in the wrong column: "44 FR 56673" is a
    # published document's address. 101 distinct unreadable values carried
    # at least one (measured 2026-08-21); always partial, because locating a
    # document is not covering an authority string.
    for fr_citation in parse_federal_register_citations(normalized):
        _add(
            AuthorityCitation(
                authority_type="federal_register",
                parse_status="partial",
                fr_volume=fr_citation.volume,
                fr_page=fr_citation.page,
            )
        )

    # A section list is never covered by a single citation, so every listed
    # member is partial. A listed member may itself be a range
    # ("42 U.S.C. 7401, 7671a-7671q"), split by the same ordering rule. The
    # window stops at the next citation's head so one title's list cannot run
    # into another's.
    #
    # A comma inside a DATE or inside an ACT'S NAME is not a list separator,
    # and this walk is the only one in the module that ever reaches one:
    # measured over all 42,642 distinct authority values, no CFR part list,
    # Executive Order list, D.C. Code list or "of title" list crosses either
    # shape, because each of those is walked anchored and stops at the word.
    # So the fence lives here, where the casualties are, rather than in the
    # shared separator.
    #
    # An APPENDIX citation seeds a list on exactly the same terms as a plain
    # one. It did not before, because only _USC_STANDARD matches were seeds,
    # and the omission dropped real citations: "46 app USC 808, 839" published
    # 808 alone, where both are sections of the Shipping Act, 1916 as it stood
    # in 46 App. U.S.C. 16 distinct values, 38 source rows, measured
    # 2026-08-22. A listed member inherits the appendix flag, because a
    # title's appendix is a different body of law from the title proper and
    # half a list must not land in the other one.
    named = _spans_owning_their_comma(normalized)
    # And the third thing a bare number behind a comma can be: the agency half
    # of a RIN the filer is naming. See :data:`_RIN_TOKEN` for the measurement
    # and for the Register-document shape that was measured and NOT fenced.
    rins = tuple(match.span() for match in _RIN_TOKEN.finditer(normalized))
    # And the fourth: a YEAR or a PAGE inside a Title 3 compilation locator.
    # "31 USC 9701; 3 CFR, 1982 Comp., p. 166" cites the fee statute and the
    # page E.O. 12356 was printed on, and this walk read the volume's year as
    # a listed section of title 31 (13 rows of 31 U.S.C. 1982) and, in the
    # sibling value that writes the page bare, the page too (7 rows of 31
    # U.S.C. 166). Neither number is a section of anything: the locator names
    # a VOLUME and a PAGE, the family beside this one already types it as
    # such, and this module's own compilation grammar has read that span since
    # the CFR reader needed it — the list walk was simply never told.
    #
    # The fence is the locator's whole span, not its year: "E.O. 10577, 3 CFR,
    # 1954-58 Comp., p. 218" hands the walk "1954-58", which the ordering rule
    # then expands into an abbreviated SPAN of five sections. One rule covers
    # the year, the abbreviated closing year, the span between them and the
    # page, because all four are numbers the locator owns.
    compilations = tuple(match.span() for match in _EO_COMPILATION.finditer(normalized))
    # A FIFTH thing a bare number behind a comma can be, and the one this
    # walk cannot settle by itself: the SAME Statutes-at-Large citation's own
    # pinpoint page. "12 U.S.C. 2013, ...; sec. 301(a), Pub. L. 100-233, 101
    # Stat. 1568, 1608, as amended by ..., 102 Stat 989, 993" (12 CFR 615's
    # own authority note) publishes 12 U.S.C. 1608 and 12 U.S.C. 993 — both
    # are the Act's own second page (Bluebook "volume Stat. start, pinpoint"),
    # not sections of anything, and :data:`_STATUTE_AT_LARGE` has no tail of
    # its own to claim them the way :data:`_STATUTE_LETTERED_PAGE` does for
    # the lettered volumes. Measured 2026-09-01: 3 fabrications in this ONE
    # note alone (research/investigations-mined-2026-08-31.md item 4).
    #
    # UNLIKE the other four, this is not skipped outright: the trap is real.
    # 14 CFR 121's own note is IDENTICAL in shape — "... preceding note added
    # by Pub. L. 112-95, sec. 412, 126 Stat. 89, 44101, 44701-44702, 44705,
    # 44709-44711, 44713, ..." — and genuinely resumes a real 49 U.S.C. list
    # (44101, 44701, 44702, ... are all real aviation-safety sections) after
    # the Stat. citation. This module cannot tell the two apart by shape: it
    # has no section-existence oracle to ask (the oracle imports this module,
    # so the reverse is circular) and no way to know a Bluebook pinpoint page
    # from a resumed list item. So the fact is MARKED
    # (:attr:`AuthorityCitation.usc_section_after_statute`) rather than
    # decided, and a consumer that CAN reach the oracle gates admission on
    # it — see :func:`refspec.registry.cfr_authority_notes.read_note_citations`.
    statutes = tuple(
        match.span()
        for pattern in (_STATUTE_LETTERED_PAGE, _STATUTE_LETTERED_VOLUME, _STATUTE_AT_LARGE)
        for match in pattern.finditer(normalized)
    )
    seeds = sorted(
        [(match, False) for match in usc_matches] + [(match, True) for match in appendix_matches],
        key=lambda seed: seed[0].start(),
    )
    for index, (match, in_appendix) in enumerate(seeds):
        stop = seeds[index + 1][0].start() if index + 1 < len(seeds) else len(normalized)
        window = match.end()
        for tail in _USC_LIST_TAIL.finditer(normalized[window:stop]):
            start, end = window + tail.start("section"), window + tail.end("section")
            if (
                _lies_inside(named, start, end)
                or _lies_inside(rins, start, end)
                or _lies_inside(compilations, start, end)
            ):
                continue
            fields = _usc_section_fields(tail.group("section"), tail.group("range_end"))
            if fields["usc_section"] is not None:
                after_statute = any(
                    statute_start >= window and statute_end <= window + tail.start()
                    for statute_start, statute_end in statutes
                )
                _add(
                    AuthorityCitation(
                        authority_type="usc",
                        parse_status="partial",
                        usc_title=int(match.group("title")),
                        usc_appendix=in_appendix,
                        usc_section_after_statute=after_statute,
                        **fields,
                    )
                )

    if not citations:
        # A CFR-shaped whole value whose title is outside the CFR's series but
        # whose numbers are a real Register volume and page reads as the FR
        # citation it is: the text's own numbers refute its claimed scheme.
        # Whole-value only, and only where the CFR reading is IMPOSSIBLE — a
        # title the CFR actually has is never second-guessed.
        relabel = _CFR_TITLE_IMPOSSIBLE_IS_FR.match(normalized)
        if relabel is not None:
            volume, page = int(relabel.group("volume")), int(relabel.group("page"))
            if (
                not _cfr_title_is_possible(volume)
                and 1 <= volume <= FR_VOLUME_HIGHEST_KNOWN
                and 1 <= page <= FR_PAGE_HIGHEST_KNOWN
            ):
                return (
                    AuthorityCitation(
                        authority_type="federal_register",
                        parse_status="partial",
                        fr_volume=volume,
                        fr_page=page,
                    ),
                )
        bare_usc = (
            _BARE_USC_TITLE.match(normalized)
            or _BARE_USC_TITLE_LONGHAND.match(normalized)
            or _USC_TITLE_WITH_DESIGNATOR.match(normalized)
        )
        if bare_usc is not None:
            # "16 USC et seq" names a title wholesale. Partial, never "ok":
            # a title without a section identifies a body of law, not a
            # provision — the same posture as the part-less CFR read.
            return (
                AuthorityCitation(
                    authority_type="usc",
                    parse_status="partial",
                    usc_title=int(bare_usc.group("title")),
                ),
            )
        # A row nothing could resolve still carries what it states. Partial
        # information is worth keeping: a consumer looking for section 326 of
        # an NDAA can find the row even where no reader can say which year's
        # NDAA it is. These are statements, never resolutions -- act_key stays
        # NULL, and nothing downstream may treat a stated name as an identity.
        # The ORIGINAL text is read, not the repaired one: a value states what
        # its publisher wrote.
        return (
            AuthorityCitation(
                authority_type="other",
                parse_status="failed",
                stated_act_name=stated_act_name(text),
                stated_section=stated_section(text),
            ),
        )
    if len(citations) > 1:
        # Several citations can each cover the whole string only vacuously;
        # one string, several authorities means none of them is the whole.
        citations = [replace(item, parse_status="partial") for item in citations]
    return tuple(citations)
