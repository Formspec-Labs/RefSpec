import duckdb, re, json, collections

ART = "output/registry-real-data-sources/unified-agenda-parquet"
con = duckdb.connect(":memory:")

cols = """rin, publication_id, ordinal, citation_ordinal, authority_text, authority_type,
parse_status, usc_title, usc_section, usc_section_end, usc_chapter, usc_chapter_end,
usc_section_verdict, usc_section_verdict_reason, usc_section_attested_at_edition,
usc_section_corrected, usc_section_corrected_section, usc_section_corrected_pinpoint,
authority_in_own_cfr_note, cfr_note_part, cfr_title, cfr_part, cfr_section,
act_key, act_section, act_resolution_reason, corroboration_rule, usc_title_is_possible"""

df = con.execute(f"select {cols} from '{ART}/unified_agenda_legal_authorities.parquet'").df()
print("total rows:", len(df))
print("usc rows:", (df.authority_type=='usc').sum())
print(df.columns.tolist())
df.to_parquet("/Users/mikewolfd/.claude/jobs/9dfc0c64/tmp/inv-universe/scratch/legal_authorities_slim.parquet")
