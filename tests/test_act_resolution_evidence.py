"""Pin that exposing competing source readings changed no act-resolution policy.

Compares the frozen oracle in act_resolution_evidence_oracle against production
resolve_act_relative_citation, failing on any divergence except enumerated fields.
"""
from dataclasses import asdict

import pytest
from act_resolution_evidence_oracle import resolve_act_relative_citation as original
from refspec.registry.act_resolution import (
    ActIndex, ActResolution, Classification, SourceCreditIndex, resolve_act_relative_citation,
)
from refspec.registry.citation_grammar import ActRelativeCitation


@pytest.mark.parametrize('rows, classifications', [
    ([], ()),
    ([('26','1')], (Classification('26','1',None,1),)),
    ([('26','2')], (Classification('26','1',None,1),)),
    ([('26','2'),('26','3')], ()),
    ([('26','2'),('26','3')], (Classification('26','1',None,1),)),
])
def test_source_targets_survive_and_policy_changes_are_explicit(rows, classifications):
    """Fail on policy drift from the oracle beyond the enumerated new fields; an
    ambiguous multi-row case must keep the old oracle IRI as table3_candidate_iri."""

    citation = ActRelativeCitation('An Act','an act','101','A')
    index = ActIndex(table3_key_by_name={'an act':'99-514'}, classifications={'99-514':{'101':classifications}})
    credits = SourceCreditIndex.from_rows([('99-514','A','101',title,section,None,None) for title,section in rows])
    before = original(citation,index=index,source_credits=credits)
    after = resolve_act_relative_citation(citation,index=index,source_credits=credits)
    old_fields = asdict(before); new_fields = asdict(after)
    assert after.act_division == 'A'  # Newly exposed source/citation context.
    old_fields.pop('act_division'); new_fields.pop('act_division')
    for key in ('source_credit_targets','conflicting_targets','table3_candidate_iri'):
        old_fields.pop(key, None); new_fields.pop(key, None)
    if len(rows) > 1 and classifications:
        # The later policy comparison proved that this singular answer loses
        # known targets. Retain the old oracle and enumerate the changed fields.
        assert before.iri == after.table3_candidate_iri == 'urn:rkaf:us:usc:26:1'
        old_fields.update(iri=None,usc_title=None,usc_section=None,answered_by=None,
                          statutes_at_large_page=None,unresolved_reason='act_section_ambiguous')
    assert old_fields == new_fields
    if len(rows) > 1:
        assert [(r.usc_title,r.usc_section) for r in after.source_credit_targets] == rows
    else:
        assert after.source_credit_targets == ()
    if after.unresolved_reason == 'sources_disagree':
        assert after.conflicting_targets == {'table3':'urn:rkaf:us:usc:26:1','source_credits':'urn:rkaf:us:usc:26:2'}
        assert after.iri is None
    else:
        assert after.conflicting_targets == {}


@pytest.mark.parametrize('targets', [
    {'table3':'urn:x','source_credits':'urn:x'}, {'table3':'urn:x','unknown':'urn:y'},
])
def test_conflict_evidence_requires_distinct_targets_from_the_named_sources(targets):
    """Refuse conflicting_targets whose sources repeat a target or are not named sources."""

    with pytest.raises(ValueError,match='conflicting targets'):
        ActResolution(ActRelativeCitation('An Act','an act','101'),
                      unresolved_reason='sources_disagree', conflicting_targets=targets)


def test_conflict_evidence_cannot_accompany_an_accepted_answer():
    """Refuse conflict evidence when the resolution already carries an accepted answer."""

    with pytest.raises(ValueError,match='conflicting targets'):
        ActResolution(ActRelativeCitation('An Act','an act','101'), iri='urn:x',answered_by='table3',
                      conflicting_targets={'table3':'urn:x','source_credits':'urn:y'})
