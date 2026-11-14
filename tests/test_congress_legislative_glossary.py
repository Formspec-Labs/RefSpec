"""The glossary's exact source, literal definitions, page locators, and drift refusals."""

from __future__ import annotations

import hashlib
import html
import json
import os
import re
from dataclasses import replace
from pathlib import Path

import pytest

from conftest import missing_pinned_input
from refspec.registry import congress_legislative_glossary as glossary
from tools.read_congress_legislative_glossary import main

FIXTURES = Path(__file__).parent / "fixtures" / "congress_glossary"


def _pin(payload: bytes, **changes) -> glossary.GlossaryPin:
    return replace(
        glossary.GLOSSARY_2026_11_14,
        expected_sha256="sha256:" + hashlib.sha256(payload).hexdigest(),
        expected_byte_length=len(payload), expected_records=5, expected_sections=("a", "c", "v"),
        **changes,
    )


def test_literal_text_html_links_and_real_anchors_stay_page_local() -> None:
    payload = (FIXTURES / "reviewed-excerpt.html").read_bytes()
    snapshot = glossary.parse_legislative_glossary(payload, pin=_pin(payload))
    action, adjourn, amendment, record, veto = snapshot.entries
    assert snapshot.publisher == "Library of Congress"
    assert snapshot.author is None and snapshot.publisher_edition is None
    assert [item.ordinal for item in snapshot.entries] == [1, 2, 3, 4, 5]
    assert action.term == "action codes"
    assert action.anchor == "glossary_majoraction"  # Literal publisher spelling, not a label-derived slug.
    assert action.links[0].href == "/help/field-values/action-codes"
    assert action.links[1].href == "#glossary_legislativeaction"
    assert adjourn.definition_text == "Formally end a meeting of a chamber or committee."
    assert adjourn.source_locator == "#glossary_adjourn"
    assert adjourn.source_url == glossary.GLOSSARY_URL + "#glossary_adjourn"
    assert "\n\nSee also Proposed/offered Senate amendment" in amendment.definition_text
    assert '<p>See also <a href="#glossary_proposedofferedsenateamendment">' in amendment.definition_html
    assert record.term == "Congressional Record" and record.term_html == "<em>Congressional Record</em>"
    assert "10-day (excluding Sundays)" in veto.definition_text
    assert "#glossary_legislativeaction" in snapshot.unresolved_fragment_links


@pytest.mark.parametrize(("old", "new", "reason"), [
    ("glossary_adjourn\"", "glossary_majoraction\"", "duplicate glossary anchors"),
    ("glossary_adjourn\"", "invented_adjourn\"", "fragment anchor"),
    ("<dd>Formally end a meeting of a chamber or committee.</dd>", "<dd> </dd>", "missing its definition"),
    ("<dd>Formally", "<dd><span>Formally</span>", "unreviewed glossary HTML"),
    ("</dl>", "stray text</dl>", "unhandled text"),
    ("<dt id=\"glossary_adjourn\">adjourn</dt>", "<dd>extra definition</dd>", "fragment anchor"),
    ("<h2 id=\"v\">V</h2>", "<h2 id=\"z\">Z</h2>", "alphabetical heading"),
    ("cdg-dl-alpha", "new-list-shape", "definition list structure"),
    ("<div id=\"help-content\">", "<div id=\"other-content\">", "complete content region"),
    ("</div>", "", "complete content region|unbalanced"),
    ("<title>Glossary", "<title>Changed glossary", "title"),
    ("rel=\"canonical\"", "rel=\"other\"", "canonical"),
    ("<p>See also", "<p data-new=\"unknown\">See also", "definition markup"),
])
def test_re_pinned_shape_mutations_refuse(old: str, new: str, reason: str) -> None:
    original = (FIXTURES / "reviewed-excerpt.html").read_text()
    assert old in original
    changed = original.replace(old, new, 1).encode()
    with pytest.raises(glossary.LegislativeGlossaryError, match=reason):
        glossary.parse_legislative_glossary(changed, pin=_pin(changed))


def test_negative_fixture_cannot_shift_definitions_onto_the_next_term() -> None:
    payload = (FIXTURES / "missing-definition.html").read_bytes()
    with pytest.raises(glossary.LegislativeGlossaryError, match="definition list structure"):
        glossary.parse_legislative_glossary(payload, pin=_pin(payload))


def test_digest_length_count_encoding_and_byte_bound_refuse(tmp_path: Path) -> None:
    payload = (FIXTURES / "reviewed-excerpt.html").read_bytes()
    pin = _pin(payload)
    with pytest.raises(glossary.LegislativeGlossaryError, match="digest"):
        glossary.parse_legislative_glossary(payload.replace(b"adjourn", b"adjourx", 1), pin=pin)
    with pytest.raises(glossary.LegislativeGlossaryError, match="byte length"):
        glossary.parse_legislative_glossary(payload + b" ", pin=pin)
    with pytest.raises(glossary.LegislativeGlossaryError, match="record count"):
        glossary.parse_legislative_glossary(payload, pin=replace(pin, expected_records=6))
    changed = payload.replace(b"veto</dt>", b"veto\xff</dt>")
    with pytest.raises(glossary.LegislativeGlossaryError, match="utf-8"):
        glossary.parse_legislative_glossary(changed, pin=_pin(changed))
    path = tmp_path / "oversized.html"
    path.write_bytes(b"x" * (glossary.MAX_SOURCE_BYTES + 20))
    with pytest.raises(glossary.LegislativeGlossaryError, match="source byte bound"):
        glossary.read_legislative_glossary(path)


def test_challenge_or_unrelated_page_cannot_become_a_glossary() -> None:
    payload = b"<!doctype html><html><title>Just a moment...</title><body>Challenge</body></html>"
    with pytest.raises(glossary.LegislativeGlossaryError, match="title"):
        glossary.parse_legislative_glossary(payload, pin=_pin(payload))


@pytest.mark.slow
def test_pinned_original_matches_every_term_definition_and_href_with_an_independent_slice_oracle(
    tmp_path: Path, monkeypatch,
) -> None:
    source_path = os.environ.get("REFSPEC_CONGRESS_LEGISLATIVE_GLOSSARY_PATH")
    if source_path is None or not Path(source_path).is_file():
        missing_pinned_input("retained official Congress.gov glossary original is unavailable")
    source = Path(source_path).read_bytes()
    snapshot = glossary.read_legislative_glossary(Path(source_path))
    # Frozen oracle for this reviewed source: independent literal slices, not the production tokenizer/tree.
    pairs = re.findall(r'<dt id="([^"]+)">(.*?)</dt>\s*<dd>(.*?)</dd>', source.decode(), re.DOTALL)
    assert len(pairs) == len(snapshot.entries) == 117
    for entry, (anchor, term_html, definition_html) in zip(snapshot.entries, pairs, strict=True):
        assert entry.anchor == anchor
        assert entry.term_html == term_html
        assert entry.term == " ".join(html.unescape(re.sub(r"<[^>]+>", "", term_html)).split())
        assert entry.definition_html == definition_html
        text = html.unescape(re.sub(r"<[^>]+>", "", definition_html.replace("<p>", "\n\n")))
        assert entry.definition_text == "\n\n".join(
            " ".join(paragraph.split()) for paragraph in text.split("\n\n")
        ).strip()
        assert [link.href for link in entry.links] == [
            html.unescape(href) for href in re.findall(r'<a\s+href="([^"]+)"', definition_html)
        ]
    assert snapshot.entries[0].anchor == "glossary_majoraction"
    assert snapshot.entries[-1].anchor == "glossary_veto"
    assert next(item for item in snapshot.entries if item.term == "partitioned nomination").anchor == (
        "glossary_partionednomination"
    )
    assert snapshot.unresolved_fragment_links == ()
    output = tmp_path / "reference.json"
    monkeypatch.setattr("sys.argv", ["read-glossary", "--source", source_path, "--output", str(output)])
    assert main() == 0
    reference = json.loads(output.read_bytes())
    assert len(reference["entries"]) == 117
    assert reference["author"] is None and reference["publisher_edition"] is None
    assert reference["entries"][0]["source_url"] == glossary.GLOSSARY_URL + "#glossary_majoraction"
    assert reference["entries"][-1]["source_locator"] == "#glossary_veto"
    assert reference["pin"]["expected_sha256"] == glossary.GLOSSARY_2026_11_14.expected_sha256
    with pytest.raises(FileExistsError):
        main()


def test_command_refuses_source_drift_before_creating_output(tmp_path: Path, monkeypatch) -> None:
    target = tmp_path / "reference.json"
    monkeypatch.setattr("sys.argv", ["read-glossary", "--source", str(FIXTURES / "reviewed-excerpt.html"),
                                    "--output", str(target)])
    with pytest.raises(glossary.LegislativeGlossaryError, match="byte length"):
        main()
    assert not target.exists()
