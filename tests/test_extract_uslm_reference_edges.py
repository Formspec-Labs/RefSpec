"""Tests for the USLM statutory reference-edge extractor.

The extractor's value is that it transcribes rather than infers, so the tests
that matter are the ones proving it cannot quietly start inferring:

* every fail-closed gate actually fires -- an unrecognised citator, an
  unrecognised USC level, a payload that is not a zip, and an ``operative`` edge
  with no enclosing unit.  Each of those is a case where emitting *something*
  would be worse than stopping;
* ``context`` precedence is innermost-first, because a ``<sourceCredit>`` nested
  in a ``<note>`` is a source credit and folding it into the note would put
  amendment history back into the reference population;
* ``st`` is tested against ``s``.  Subtitle and section share a prefix, and
  getting that order wrong misreads every subtitle reference as a section one;
* the deduplication key keeps ``context``.  This is the single most consequential
  line in the policy: dropping it merges a citation the publisher put in enacted
  text with the same citation in an editorial note, which is exactly the
  conflation the ``context`` field exists to prevent; and
* identifiers survive byte-for-byte, U+2013 EN DASH included.  A "tidied" dash
  produces an identifier that looks right and joins to nothing.

Fixtures are synthetic USLM documents.  Binding these to the 431 MB extraction
would couple the suite to one release point, would not run offline, and would
exercise none of the failure paths.
"""

from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

import pytest

from tools import extract_uslm_reference_edges as uslm

NS = uslm.USLM_NS


def _document(body: str) -> bytes:
    """Wrap a fragment in the namespaced root every OLRC title carries."""
    return f'<?xml version="1.0" encoding="UTF-8"?><uscDoc xmlns="{NS}">{body}</uscDoc>'.encode()


#: One section that cites another section, a public law, a Statutes at Large
#: page and a named act, spread across operative text, a source credit, a note
#: and a table of contents -- the four contexts, in one document.
SAMPLE = _document(
    """
    <toc><tocItem><ref href="/us/usc/t26/stA">Subtitle A</ref></tocItem></toc>
    <section identifier="/us/usc/t26/s1">
      <content>
        <p>See <ref href="/us/usc/t26/s61">section 61</ref> and
           <ref href="/us/act/1954-08-16/ch736">the 1954 Act</ref>.</p>
        <p>Also <ref href="/us/usc/t26/s61">section 61 again</ref>.</p>
      </content>
      <sourceCredit>(<ref href="/us/pl/99/514/s2">Pub. L. 99-514</ref>,
        <ref href="/us/stat/100/2095">100 Stat. 2095</ref>)</sourceCredit>
      <notes>
        <note topic="amendments"><p><ref href="/us/pl/99/514/s2">1986</ref></p></note>
        <note topic="amendments"><p>
          <sourceCredit><ref href="/us/pl/100/647/s1">Pub. L. 100-647</ref></sourceCredit>
        </p></note>
      </notes>
    </section>
    """
)


def _edges(xml: bytes, title: str = "26") -> list[dict]:
    from collections import Counter

    return list(uslm.iter_edges(xml, title, Counter()))


# --------------------------------------------------------------------------- #
# href classification
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("href", "edge_type", "level"),
    [
        ("/us/pl/99/514/s2", "enactingPublicLaw", None),
        ("/us/stat/100/2095", "statutesAtLarge", None),
        ("/us/act/1954-08-16/ch736", "actName", None),
        ("/us/usc/t26/s61", "uscCrossReference", "section"),
        ("/us/usc/t26", "uscCrossReference", "title"),
        # ``st`` must beat ``s``; a subtitle read as a section is silent corruption.
        ("/us/usc/t26/stA", "uscCrossReference", "subtitle"),
        ("/us/usc/t26/sch1", "uscCrossReference", "subchapter"),
        ("/us/usc/t26/spt2", "uscCrossReference", "subpart"),
        ("/us/usc/t26/ch1", "uscCrossReference", "chapter"),
        ("/us/usc/t26/pt3", "uscCrossReference", "part"),
        ("/us/usc/t26/d1", "uscCrossReference", "division"),
    ],
)
def test_classify_href_names_the_citator_and_the_usc_level(href: str, edge_type: str, level: str | None) -> None:
    assert uslm.classify_href(href) == (edge_type, level)


def test_classify_href_fails_closed_on_an_unmodelled_citator() -> None:
    """A new citator means the corpus grew a relation this tool has no meaning for."""
    with pytest.raises(uslm.ExtractionError, match="unrecognised href prefix"):
        uslm.classify_href("/us/cfr/t40/s60")


def test_classify_href_fails_closed_on_a_relative_href() -> None:
    with pytest.raises(uslm.ExtractionError, match="not an absolute identifier"):
        uslm.classify_href("s61")


def test_classify_href_fails_closed_on_an_unmodelled_usc_level() -> None:
    with pytest.raises(uslm.ExtractionError, match="unrecognised USC level"):
        uslm.classify_href("/us/usc/t26/zz9")


# --------------------------------------------------------------------------- #
# context and anchoring
# --------------------------------------------------------------------------- #


def test_each_edge_is_labelled_with_the_kind_of_text_it_sits_in() -> None:
    by_href = {(edge["href"], edge["context"]) for edge in _edges(SAMPLE)}
    assert ("/us/usc/t26/s61", "operative") in by_href
    assert ("/us/act/1954-08-16/ch736", "operative") in by_href
    assert ("/us/pl/99/514/s2", "sourceCredit") in by_href
    assert ("/us/stat/100/2095", "sourceCredit") in by_href
    assert ("/us/pl/99/514/s2", "note") in by_href
    assert ("/us/usc/t26/stA", "toc") in by_href


def test_a_source_credit_nested_in_a_note_is_still_a_source_credit() -> None:
    """Precedence is innermost-first; the other order would hide amendment history in notes."""
    edge = next(edge for edge in _edges(SAMPLE) if edge["href"] == "/us/pl/100/647/s1")
    assert edge["context"] == "sourceCredit"
    assert edge["historical"] is True


def test_amendment_note_topics_are_marked_historical_without_being_filtered() -> None:
    note_edge = next(
        edge for edge in _edges(SAMPLE) if edge["href"] == "/us/pl/99/514/s2" and edge["context"] == "note"
    )
    assert note_edge["noteTopic"] == "amendments"
    assert note_edge["historical"] is True


def test_a_toc_reference_has_no_citing_section() -> None:
    """The bug this guards: TOC entries once passed for section-to-section references."""
    edge = next(edge for edge in _edges(SAMPLE) if edge["context"] == "toc")
    assert edge["sourceSection"] is None
    assert edge["sourceUnitKind"] is None


def test_operative_edges_are_anchored_to_their_section() -> None:
    edge = next(edge for edge in _edges(SAMPLE) if edge["context"] == "operative")
    assert edge["sourceSection"] == "/us/usc/t26/s1"
    assert edge["sourceUnit"] == "/us/usc/t26/s1"
    assert edge["sourceUnitKind"] == "section"


def test_the_finest_enclosing_identifier_wins_as_the_anchor() -> None:
    xml = _document(
        """
        <section identifier="/us/usc/t26/s1">
          <subsection identifier="/us/usc/t26/s1/a">
            <p><ref href="/us/usc/t26/s61">x</ref></p>
          </subsection>
        </section>
        """
    )
    edge = _edges(xml)[0]
    assert edge["sourceAnchor"] == "/us/usc/t26/s1/a"
    assert edge["sourceSection"] == "/us/usc/t26/s1"


def test_an_a_element_carrying_an_href_is_read_like_a_ref() -> None:
    """3.1% of the corpus rides on <a>; a <ref>-only reader drops 8,343 edges from Title 49 alone."""
    xml = _document(
        """
        <section identifier="/us/usc/t49/s1">
          <notes><note topic="historicalAndRevision">
            <p><a href="/us/pl/103/272/s1">Pub. L. 103-272</a></p>
          </note></notes>
        </section>
        """
    )
    edge = _edges(xml, "49")[0]
    assert edge["element"] == "a"
    assert edge["edgeType"] == "enactingPublicLaw"


def test_a_footnote_ref_without_an_href_is_counted_not_emitted() -> None:
    from collections import Counter

    skipped: Counter[str] = Counter()
    xml = _document('<section identifier="/us/usc/t26/s1"><ref class="footnoteRef" idref="FN1"/></section>')
    assert list(uslm.iter_edges(xml, "26", skipped)) == []
    assert skipped["refWithoutHref"] == 1
    assert skipped["refElementsSeen"] == 1


def test_an_in_document_fragment_is_navigation_not_a_citation() -> None:
    from collections import Counter

    skipped: Counter[str] = Counter()
    xml = _document('<section identifier="/us/usc/t26/s1"><ref href="#TAB_231_0">table</ref></section>')
    assert list(uslm.iter_edges(xml, "26", skipped)) == []
    assert skipped["inDocumentFragment"] == 1
    assert skipped["inDocumentFragmentOnRef"] == 1


def test_identifiers_are_copied_byte_for_byte_including_the_en_dash() -> None:
    """U+2013 is what joins an href to its section; an ASCII hyphen matches nothing."""
    xml = _document(
        '<section identifier="/us/usc/t26/s1400Z–1">'
        '<p><ref href="/us/usc/t26/s1400Z–2">x</ref></p></section>'
    )
    edge = _edges(xml)[0]
    assert edge["sourceAnchor"] == "/us/usc/t26/s1400Z–1"
    assert edge["href"] == "/us/usc/t26/s1400Z–2"
    assert "-" not in edge["href"]


def test_a_reorganization_plan_anchors_an_edge_just_as_a_section_does() -> None:
    """Title 5 Appendix has no sections; a <section>-only invariant calls 1,420 edges orphaned."""
    xml = _document(
        """
        <reorganizationPlan identifier="/us/usc/t5a/rp1">
          <p><ref href="/us/pl/91/375/s6">Pub. L. 91-375</ref></p>
        </reorganizationPlan>
        """
    )
    edge = _edges(xml, "05a")[0]
    assert edge["sourceUnitKind"] == "reorganizationPlan"
    assert edge["sourceSection"] is None


def test_a_withdrawn_unit_keeps_its_citations_with_a_status_explaining_the_missing_identifier() -> None:
    xml = _document(
        '<section status="repealed"><heading>Repealed by '
        '<ref href="/us/pl/115/97/s1">Pub. L. 115-97</ref></heading></section>'
    )
    edge = _edges(xml)[0]
    assert edge["sourceUnit"] is None
    assert edge["sourceUnitStatus"] == "repealed"


def test_an_unbalanced_document_fails_closed() -> None:
    from collections import Counter

    with pytest.raises(Exception):  # noqa: B017 - ET raises its own ParseError before our guard
        list(uslm.iter_edges(b"<uscDoc><section>", "26", Counter()))


# --------------------------------------------------------------------------- #
# deduplication policy
# --------------------------------------------------------------------------- #


def _edge(**overrides: object) -> dict:
    base = {
        "title": "26",
        "sourceSection": "/us/usc/t26/s1",
        "sourceUnit": "/us/usc/t26/s1",
        "sourceUnitKind": "section",
        "sourceUnitStatus": None,
        "sourceAnchor": "/us/usc/t26/s1",
        "href": "/us/usc/t26/s61",
        "edgeType": "uscCrossReference",
        "uscTargetLevel": "section",
        "element": "ref",
        "context": "operative",
        "noteTopic": None,
        "historical": False,
    }
    base.update(overrides)
    return base


def test_repeating_a_citation_in_one_section_states_one_claim() -> None:
    kept, accounting = uslm.dedupe([_edge(), _edge(), _edge()])
    assert len(kept) == 1
    assert accounting["occurrenceRows"] == 3
    assert accounting["distinctClaims"] == 1
    assert accounting["redundantOccurrences"] == 2
    assert accounting["exactDuplicateRows"] == 2


def test_context_is_part_of_the_key_so_a_note_citation_never_merges_with_an_operative_one() -> None:
    """The load-bearing line of the policy.

    Over the full corpus 22,295 (anchor, href, type) triples appear in more than
    one context.  A context-free key silently merges them, which reintroduces at
    the assertion layer exactly the amendment-versus-reference conflation the
    ``context`` field exists to prevent.
    """
    kept, accounting = uslm.dedupe([_edge(context="operative"), _edge(context="note")])
    assert len(kept) == 2
    assert accounting["distinctClaims"] == 2
    assert accounting["redundantOccurrences"] == 0
    assert accounting["distinctClaimsByContext"] == {"note": 1, "operative": 1}
    assert "context" in uslm.ASSERTION_KEY


def test_the_element_a_citation_was_marked_up_with_does_not_make_it_a_different_claim() -> None:
    kept, _ = uslm.dedupe([_edge(element="ref"), _edge(element="a")])
    assert len(kept) == 1


def test_a_row_with_no_source_anchor_states_no_claim_and_is_counted_separately() -> None:
    """2,641 corpus rows sit in a unit that lost its identifier; 1,422 are operative."""
    kept, accounting = uslm.dedupe([_edge(sourceAnchor=None), _edge()])
    assert uslm.assertion_key(_edge(sourceAnchor=None)) is None
    assert len(kept) == 1
    assert accounting["anchorlessRows"] == 1
    # Excluded from claims, not silently folded into the redundant count.
    assert accounting["redundantOccurrences"] == 0


def test_the_dedup_accounting_closes_over_every_row() -> None:
    rows = [_edge(), _edge(), _edge(context="note"), _edge(sourceAnchor=None), _edge(href="/us/usc/t26/s62")]
    _, accounting = uslm.dedupe(rows)
    assert (
        accounting["occurrenceRows"]
        == accounting["distinctClaims"] + accounting["redundantOccurrences"] + accounting["anchorlessRows"]
    )


def test_the_operative_cross_reference_count_is_the_graph_admissible_population() -> None:
    rows = [
        _edge(),
        _edge(context="note"),
        _edge(context="sourceCredit", edgeType="enactingPublicLaw", href="/us/pl/99/514/s2"),
        _edge(href="/us/usc/t26/s62"),
    ]
    _, accounting = uslm.dedupe(rows)
    assert accounting["operativeUscCrossReferences"] == 2


def test_dedup_keeps_the_first_occurrence_so_the_representative_is_deterministic() -> None:
    first = _edge(noteTopic="alpha")
    second = _edge(noteTopic="beta")
    kept, _ = uslm.dedupe([first, second])
    assert kept[0]["noteTopic"] == "alpha"


def test_corpus_rollup_refuses_to_sum_when_title_is_no_longer_the_leading_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """Summing per-title counts is valid only while no claim can span two titles."""
    monkeypatch.setattr(uslm, "ASSERTION_KEY", ("sourceAnchor", "edgeType", "href", "context"))
    with pytest.raises(uslm.ExtractionError, match="leads ASSERTION_KEY"):
        uslm.corpus_deduplication([])


def test_corpus_rollup_adds_disjoint_per_title_partitions() -> None:
    _, first = uslm.dedupe([_edge(), _edge()])
    _, second = uslm.dedupe([_edge(title="42", sourceAnchor="/us/usc/t42/s1")])
    rolled = uslm.corpus_deduplication(
        [{"deduplication": first, "skipped": {}}, {"deduplication": second, "skipped": {}}]
    )
    assert rolled["occurrenceRows"] == 3
    assert rolled["distinctClaims"] == 2
    assert rolled["redundantOccurrences"] == 1


# --------------------------------------------------------------------------- #
# whole-title extraction and its gates
# --------------------------------------------------------------------------- #


def _cache_with(tmp_path: Path, title: str, xml: bytes) -> Path:
    cache = tmp_path / "cache"
    cache.mkdir(exist_ok=True)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(f"usc{title}.xml", xml)
    (cache / f"xml_usc{title}.zip").write_bytes(buffer.getvalue())
    return cache


def test_extract_title_reports_the_source_pin_and_both_unit_counts(tmp_path: Path) -> None:
    cache = _cache_with(tmp_path, "26", SAMPLE)
    edges, report = uslm.extract_title("26", uslm.RELEASE_POINT, cache)
    assert report["title"] == "26"
    assert report["source"]["zipSha256"] and report["source"]["xmlSha256"]
    assert report["source"]["member"] == "usc26.xml"
    assert report["edges"] == len(edges)
    # Two operative mark-ups of section 61 collapse to one claim; the act stays.
    assert report["deduplication"]["operativeUscCrossReferences"] == 1
    assert report["byContext"]["operative"] == 3


def test_a_dangling_same_title_target_is_flagged_rather_than_dropped(tmp_path: Path) -> None:
    """~1% of same-title references point at repealed sections; the text still says so."""
    xml = _document(
        '<section identifier="/us/usc/t26/s1"><p><ref href="/us/usc/t26/s9999">gone</ref></p></section>'
    )
    edges, report = uslm.extract_title("26", uslm.RELEASE_POINT, _cache_with(tmp_path, "26", xml))
    assert edges[0]["targetResolved"] is False
    assert report["sameTitleSectionTargets"] == {"resolved": 0, "dangling": 1}


def test_a_cross_title_target_is_unknown_rather_than_guessed(tmp_path: Path) -> None:
    xml = _document('<section identifier="/us/usc/t26/s1"><p><ref href="/us/usc/t42/s1">x</ref></p></section>')
    edges, report = uslm.extract_title("26", uslm.RELEASE_POINT, _cache_with(tmp_path, "26", xml))
    assert edges[0]["targetResolved"] is None
    assert report["crossTitleSectionTargets"] == 1


def test_an_operative_edge_outside_any_unit_stops_the_run(tmp_path: Path) -> None:
    """The exact defect that once turned 2,992 TOC entries into cross-references."""
    xml = _document('<p><ref href="/us/usc/t26/s61">loose</ref></p>')
    with pytest.raises(uslm.ExtractionError, match="operative edges sit in no"):
        uslm.extract_title("26", uslm.RELEASE_POINT, _cache_with(tmp_path, "26", xml))


def test_an_unidentified_unit_with_no_status_stops_the_run(tmp_path: Path) -> None:
    xml = _document('<section><p><ref href="/us/usc/t26/s61">x</ref></p></section>')
    with pytest.raises(uslm.ExtractionError, match="with no status explaining why"):
        uslm.extract_title("26", uslm.RELEASE_POINT, _cache_with(tmp_path, "26", xml))


def test_a_cached_payload_that_is_not_a_zip_is_refused(tmp_path: Path) -> None:
    """The publisher answers a withdrawn title with an HTML error page and HTTP 200."""
    cache = tmp_path / "cache"
    cache.mkdir()
    (cache / "xml_usc53.zip").write_bytes(b"<html>Error</html>")
    with pytest.raises(uslm.ExtractionError, match="did not return a zip archive"):
        uslm.fetch_title("53", uslm.RELEASE_POINT, cache)


def test_an_archive_with_more_than_one_xml_member_is_refused(tmp_path: Path) -> None:
    cache = tmp_path / "cache"
    cache.mkdir()
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("a.xml", SAMPLE)
        archive.writestr("b.xml", SAMPLE)
    (cache / "xml_usc26.zip").write_bytes(buffer.getvalue())
    with pytest.raises(uslm.ExtractionError, match="expected exactly one XML member"):
        uslm.fetch_title("26", uslm.RELEASE_POINT, cache)


def test_a_reserved_title_is_explained_rather_than_fetched() -> None:
    assert "53" in uslm.RESERVED_TITLES
    assert "53" not in uslm.TITLES


# --------------------------------------------------------------------------- #
# manifests
# --------------------------------------------------------------------------- #


def test_the_manifest_states_what_the_edge_set_is_not_usable_for(tmp_path: Path) -> None:
    _, report = uslm.extract_title("26", uslm.RELEASE_POINT, _cache_with(tmp_path, "26", SAMPLE))
    manifest = uslm.build_manifest([report], uslm.RELEASE_POINT, 1.0)
    joined = " ".join(manifest["notUsableFor"])
    # The two claims a consumer is most likely to make and least entitled to.
    assert "a row is a markup occurrence" in joined
    assert "not what" in joined and "the citation asserts" in joined
    assert manifest["deduplication"]["distinctClaims"] <= manifest["edges"]


def test_the_evidence_manifest_pins_every_input_without_carrying_the_extraction(tmp_path: Path) -> None:
    """What gets committed is the pins and the counts, never the hundreds of megabytes."""
    _, report = uslm.extract_title("26", uslm.RELEASE_POINT, _cache_with(tmp_path, "26", SAMPLE))
    report["file"] = "edges-t26.jsonl"
    report["fileSha256"] = "0" * 64
    evidence = uslm.build_evidence_manifest(uslm.build_manifest([report], uslm.RELEASE_POINT, 1.0))
    assert evidence["type"] == "UslmReferenceEdgeEvidence"
    entry = evidence["inputs"][0]
    assert entry["url"].startswith("https://uscode.house.gov/")
    assert entry["zipBytes"] > 0 and len(entry["zipSha256"]) == 64
    assert entry["xmlBytes"] > 0 and len(entry["xmlSha256"]) == 64
    assert entry["outputSha256"] == "0" * 64
    # No edge rows anywhere in the committed payload.  The check is structural
    # rather than textual: field *names* legitimately appear in the published
    # dedup key, and `/us/pl` legitimately appears inside the OLRC release-point
    # URL, so only the shape of what is carried can distinguish pins from rows.
    assert set(evidence) == {
        "type", "releasePoint", "publisher", "rights", "sourceBaseUrl", "titles",
        "occurrenceRows", "byEdgeType", "byContext", "deduplication", "skipped",
        "notUsableFor", "inputs",
    }
    assert set(entry) == {
        "title", "url", "zipBytes", "zipSha256", "member", "xmlBytes", "xmlSha256",
        "sections", "occurrenceRows", "distinctClaims", "operativeUscCrossReferences",
        "outputFile", "outputSha256",
    }
    assert "/us/usc/" not in json.dumps(evidence)
