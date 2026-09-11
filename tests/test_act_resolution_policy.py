"""Exclusion needs complete page evidence; known plural targets stay plural."""
from dataclasses import asdict, replace
from pathlib import Path
import shutil

import pytest

from act_resolution_evidence_oracle import resolve_act_relative_citation as original
from refspec.registry.act_resolution import ActIndex, ActResolution, Classification, SourceCreditIndex, resolve_act_relative_citation
from refspec.registry.citation_grammar import ActRelativeCitation


def fixture(pages):
    return ActIndex(table3_key_by_name={'an act':'93-406'},
                    classifications={'93-406':{'101':tuple(Classification('26',str(n+1),None,page) for n,page in enumerate(pages))}},
                    division_by_name={'an act':('A',200)},
                    division_starts={'93-406':(('A',200),('B',300))})


def resolve(index, credits=None):
    return resolve_act_relative_citation(ActRelativeCitation('An Act','an act','101'),index=index,source_credits=credits)


@pytest.mark.parametrize('pages,outcome', [
    ([100],'act_section_outside_act'),([100,101],'act_section_outside_act'),
    ([None],'table3'),([None,100],'act_section_ambiguous'),([None,None],'act_section_ambiguous'),
    ([200],'table3'),([299],'table3'),([300],'table3'),([301],'act_section_outside_act'),
    ([100,210],'act_section_ambiguous'),([200,250],'act_section_ambiguous'),
])
def test_page_exclusion_is_independent_of_row_count_and_requires_known_pages(pages,outcome):
    answer=resolve(fixture(pages))
    assert answer.answered_by or answer.unresolved_reason
    assert (answer.answered_by or answer.unresolved_reason)==outcome


@pytest.mark.parametrize('pages,outcome',[([100],'table3'),([100,101],'act_section_ambiguous')])
def test_narrowed_page_spellings_cannot_prove_outside_scope(pages,outcome):
    index=replace(fixture(pages),narrowed_page_sections=frozenset({('93-406','101')}))
    answer=resolve(index)
    assert (answer.answered_by or answer.unresolved_reason)==outcome


@pytest.mark.parametrize('pages', [[100],[100,101]])
def test_no_declared_division_range_does_not_invent_one(pages):
    index=replace(fixture(pages),division_starts={})
    before=original(ActRelativeCitation('An Act','an act','101'),index=index)
    after=resolve(index)
    assert (after.iri,after.unresolved_reason)==(before.iri,before.unresolved_reason)


@pytest.mark.parametrize('targets',[['1','2'],['2','3']])
def test_one_table_answer_does_not_override_multiple_credit_targets(targets):
    credits=SourceCreditIndex.from_rows([('93-406','A','101','26',s,'88','205') for s in targets])
    answer=resolve(fixture([205]),credits)
    assert answer.iri is None and answer.answered_by is None
    assert answer.unresolved_reason=='act_section_ambiguous'
    assert answer.table3_candidate_iri=='urn:rkaf:us:usc:26:1'
    assert [t.usc_section for t in answer.source_credit_targets]==targets
    assert answer.table3_reason is None
    assert not answer.conflicting_targets


@pytest.mark.parametrize('targets',[[],['1'],['1','1'],['2']])
def test_absence_agreement_duplicate_rows_and_disagreement_keep_their_verdicts(targets):
    index=fixture([205])
    credits=SourceCreditIndex.from_rows([('93-406','A','101','26',s,'88','205') for s in targets])
    before=asdict(original(ActRelativeCitation('An Act','an act','101'),index=index,source_credits=credits))
    after=asdict(resolve(index,credits))
    for key in ('source_credit_targets','conflicting_targets','table3_candidate_iri'):
        before.pop(key,None);after.pop(key,None)
    assert after.pop('act_division') == 'A'
    before.pop('act_division')
    assert before==after


def test_table_candidate_requires_a_plural_refusal():
    with pytest.raises(ValueError,match='Table III candidate'):
        ActResolution(ActRelativeCitation('An Act','an act','101'),
                      iri='urn:rkaf:us:usc:26:1',answered_by='table3',
                      table3_candidate_iri='urn:rkaf:us:usc:26:1')


ROOT=Path(__file__).resolve().parents[1]
BULK=ROOT/'output/usc-act-index-2026-08-22'
OLD=ROOT/'output/usc-act-index-2026-08-02'
CREDITS=ROOT/'output/usc-source-credit-index-2026-08-02'
artifact=pytest.mark.skipif(not all(p.is_dir() for p in (BULK,OLD,CREDITS)),reason='Pinned artifacts unavailable')


@artifact
def test_real_source_rows_expose_both_policy_failures():
    index=ActIndex.from_artifact(BULK)
    credits=SourceCreditIndex.from_artifact(CREDITS)
    for name,section in [('secure 2.0 act of 2022','127'),('defense against weapons of mass destruction act of 1996','1416')]:
        answer=resolve_act_relative_citation(ActRelativeCitation(name,name,section),index=index,source_credits=credits)
        assert answer.iri is None
        if section=='127':
            assert answer.table3_reason=='act_section_outside_act'
            assert len(answer.source_credit_targets)==4
        else:
            assert answer.table3_candidate_iri=='urn:rkaf:us:usc:50:2316'
            assert answer.unresolved_reason=='act_section_ambiguous'
            assert [(t.usc_title,t.usc_section) for t in answer.source_credit_targets]==[('10','282'),('18','175a')]
    assert ('104-208','2451') in index.narrowed_page_sections


@artifact
def test_classifications_cannot_use_another_artifacts_quarantine(tmp_path):
    for name in ('receipt.json','usc-popular-names.parquet','usc-act-sections.parquet'):
        shutil.copyfile(BULK/name,tmp_path/name)
    shutil.copyfile(OLD/'quarantine.parquet',tmp_path/'quarantine.parquet')
    with pytest.raises(ValueError,match='same act artifact'):
        ActIndex.from_artifact(tmp_path)
