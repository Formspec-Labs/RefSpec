"""Bare local clauses observed in IEP law, with constructed refusal controls."""

import pytest

from refspec.registry.citation_grammar import find_local_clause_occurrences


def test_writing_requirement_preserves_two_exact_occurrences():
    # Actual 20 USC 1414(d)(1)(C)(iii) content: these are ordinary text, not
    # <ref> elements. Surrounding wording names two different parental acts.
    text = "A parent’s agreement under clause (i) and consent under clause (ii) shall be in writing."
    found = find_local_clause_occurrences(text)
    assert [(r.label, r.text, r.refusal) for r in found] == [
        ("i", "clause (i)", None), ("ii", "clause (ii)", None),
    ]
    assert all(text[r.start:r.end] == r.text for r in found)
    repeated = find_local_clause_occurrences(text + " " + text)
    assert len(repeated) == 4
    assert len({r.start for r in repeated}) == 4


@pytest.mark.parametrize("text", [
    "clause (i)(A)", "clause (i) of subparagraph (D)",
    "clause (i) in section 2", "clause (i) through (iii)",
    "clause (i)–(iii)", "clause (i) and (ii)", "clauses (i) and (ii)",
    "clause (i), (ii), or (iii)", "clause (I)", "clause (1)",
    "clause\n\n(i)", "subparagraph (D), clause (i)",
    "clause (i) and clause (ii) of subparagraph (D)",
])
def test_unsupported_forms_do_not_become_bare_local_targets(text):
    found = find_local_clause_occurrences(text)
    assert found
    assert all(r.refusal for r in found)
    assert all(text[r.start:r.end] == r.text for r in found)


def test_no_subclause_or_unlabelled_prose_and_no_inferred_semantics():
    assert not find_local_clause_occurrences("subclause (i); a clause is text; (i).")
    found = find_local_clause_occurrences('The example says “clause (i)”.')
    assert found[0].text == "clause (i)"  # Recognition alone makes no operative assertion.


def test_next_paragraph_label_is_not_a_citation_continuation():
    found = find_local_clause_occurrences("See clause (i)\n\n(i) Another provision.")
    assert found[0].refusal is None
    found = find_local_clause_occurrences("subparagraph (D),\nclause (i)")
    assert found[0].refusal == "local_clause_container_unsupported"
