"""Keep distinct law/scope readings; source-row order is not identity evidence."""
from dataclasses import asdict, replace
import json

import pytest
import act_name_multiplicity_oracle as old
from refspec.registry import act_resolution as a
from refspec.registry.citation_grammar import ActRelativeCitation


def row(law, division=None, *, name='Example Act of 2000', page='100'):
    """One synthetic usc-popular-names cite row, normalized on its name key."""

    return dict(name=name, name_key=a.normalize_popular_name(name), content_type='cite',
                table3_key=law, usc_title=None, usc_section=None, see_also=None,
                see_also_key=None, release_point='test', division=division,
                statutes_at_large_volume='100', statutes_at_large_page=page)


@pytest.fixture
def load(tmp_path, monkeypatch):
    """Build an index from synthetic parquet rows, with the oracle and the current reader seeing the same tables."""

    (tmp_path/'receipt.json').write_text(json.dumps({'source_incomplete': []}))
    monkeypatch.setattr(a, '_artifacts_stating', lambda path: frozenset({'constructed'}))
    monkeypatch.setattr(old, '_artifacts_stating', lambda path: frozenset({'constructed'}))

    def build(rows, *, oracle=False):
        tables = {
            'usc-popular-names.parquet': rows,
            'usc-act-sections.parquet': [
                dict(table3_key=law, act_section='101', usc_title='42', usc_section=target,
                     status=None, statutes_at_large_page=100)
                for law, target in [('100-1', '1'), ('100-2', '2')]],
            'quarantine.parquet': [],
        }
        monkeypatch.setattr(a, '_read_pinned_parquet', lambda directory, name: tables[name])
        monkeypatch.setattr(old, '_read_pinned_parquet', lambda directory, name: tables[name])
        return (old.ActIndex if oracle else a.ActIndex).from_artifact(tmp_path)
    return build


def query(index, division=None, name='Example Act of 2000'):
    """Resolve the example citation against an index, with an optional stated division."""

    return a.resolve_act_relative_citation(ActRelativeCitation(name, a.normalize_popular_name(name), '101', division), index=index)


def test_real_failure_shape_retains_both_lookups_and_original_name_rows(load):
    """Two laws under one name and division must publish both candidates and
    refuse as act_name_ambiguous, independent of source-row order.
    """

    rows = [row('100-1', 'A'), row('100-2', 'A', page='200')]
    before = old.resolve_act_relative_citation(ActRelativeCitation('Example Act of 2000','example act of 2000','101'), index=load(rows, oracle=True))
    assert before.table3_key == '100-1' and before.iri
    after = query(load(rows))
    assert after.unresolved_reason == 'act_name_ambiguous' and after.iri is None
    assert after.table3_key is None
    assert [(r.table3_key, r.division, r.statutes_at_large_page) for r in after.name_sources] == [('100-1','A','100'),('100-2','A','200')]
    assert [(c.table3_key,c.act_division) for c in after.candidate_resolutions] == [('100-1','A'),('100-2','A')]
    assert after.candidate_resolutions[0].iri == before.iri
    assert asdict(query(load(list(reversed(rows))))) == asdict(after)


@pytest.mark.parametrize('division', [None, 'A'])
def test_duplicate_rows_are_one_identity(load, division):
    """Repeated identical source rows collapse to one identity, so name_candidates stays empty."""

    r=row('100-1', division)
    index=load([r,r,r])
    answer=query(index)
    assert index.name_candidates == {}
    assert answer.iri == 'urn:rkaf:us:usc:42:1'
    assert answer.candidate_resolutions == () and answer.name_sources == ()


@pytest.mark.parametrize('first, second, stated, selected, reason', [
    ('A','B','A','100-1',None),
    ('A','B','C',None,'act_division_conflict'),
    (None,'A','A',None,'act_name_ambiguous'),
    (None,'B','A','100-1',None),
    ('A','A',None,None,'act_name_ambiguous'),
])
def test_stated_division_narrows_only_compatible_source_identities(load, first, second, stated, selected, reason):
    """A stated division selects the compatible law, conflicts as
    act_division_conflict, and never hides either source row.
    """

    rows=[row('100-1',first),row('100-2',second)]
    answer=query(load(rows),stated)
    assert answer.unresolved_reason == reason
    assert answer.table3_key == selected
    assert len(answer.name_sources)==2
    assert asdict(query(load(rows[::-1]),stated))==asdict(answer)


def test_same_law_with_unstated_and_stated_division_needs_citation_context(load):
    """One law stated both with and without a division is ambiguous until the citation names the division."""

    rows=[row('100-1'), row('100-1','A')]
    answer=query(load(rows))
    assert answer.unresolved_reason=='act_name_ambiguous'
    assert answer.table3_key=='100-1'
    assert {c.act_division for c in answer.candidate_resolutions}=={None,'A'}
    explicit=query(load(rows),'A')
    assert explicit.iri=='urn:rkaf:us:usc:42:1'
    assert explicit.act_division=='A' and len(explicit.name_sources)==2


def test_different_pages_alone_do_not_invent_different_law_scope(load):
    """Different Statutes at Large pages for one law are one identity, not two candidates."""

    index=load([row('100-1',page='100'),row('100-1',page='200')])
    assert query(index).iri=='urn:rkaf:us:usc:42:1'
    assert not index.name_candidates


@pytest.mark.parametrize('name', ['Example Act', 'Alias'])
def test_year_and_alias_lookup_keep_all_laws(load, name):
    """The year-stem and see-also alias lookups keep every matching law and refuse as ambiguous."""

    index=load([row('100-1'),row('100-2')])
    index=replace(index, alias_by_name={'alias':'example act of 2000'})
    answer=query(index,name=name)
    assert answer.unresolved_reason=='act_name_ambiguous'
    assert len(answer.candidate_resolutions)==2
    assert all(c.citation==answer.citation for c in answer.candidate_resolutions)


def test_candidate_lookups_cannot_accompany_a_selected_answer(load):
    """A selected answer may not also carry candidate resolutions, so the record type raises ValueError."""

    answer=query(load([row('100-1'),row('100-2')]))
    with pytest.raises(ValueError,match='name candidates'):
        replace(answer,iri='urn:rkaf:us:usc:42:1',answered_by='table3',unresolved_reason=None)


def test_current_record_type_is_shared_by_builder():
    """The builder imports the reader's PopularNameRecord rather than defining a second one."""

    from tools.build_usc_popular_names import PopularNameRecord
    assert PopularNameRecord is a.PopularNameRecord


@pytest.mark.parametrize('dates, expected', [
    ({(100,1):'01/01/2000',(100,2):'02/02/2000'}, {'example act':'2000'}),
    ({(100,1):'01/01/2000',(100,2):'02/02/2001'}, {}),
    ({(100,1):'01/01/2000'}, {}),
])
def test_calendar_consumer_requires_all_laws_to_supply_the_same_year(load, dates, expected):
    """The unified-agenda calendar publishes an enactment year only when every ambiguity candidate agrees."""

    from refspec.registry.unified_agenda_parquet import _act_enactment_years
    from act_enactment_year_oracle import _act_enactment_years as prior_years
    rows=[row('100-1',name='Example Act'),row('100-2',name='Example Act')]
    assert prior_years(load(rows,oracle=True),(dates,{}))=={'example act':'2000'}
    assert _act_enactment_years(load(rows),(dates,{}))==expected
    assert _act_enactment_years(load(rows[::-1]),(dates,{}))==expected


def test_publication_consumer_preserves_the_new_native_refusal(load):
    """The unified-agenda consumer reports act_name_ambiguous and lists the reason as a known resolution outcome."""

    from refspec.registry.unified_agenda_parquet import _resolve_one_act_citation, ACT_RESOLUTION_REASONS
    index=load([row('100-1'),row('100-2')])
    assert _resolve_one_act_citation('example act of 2000','101',index,None)==(None,None,None,'act_name_ambiguous')
    assert _resolve_one_act_citation('example act of 2000',None,index,None)==(None,None,None,'no_section_stated')
    assert 'act_name_ambiguous' in ACT_RESOLUTION_REASONS
