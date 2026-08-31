import duckdb, pandas as pd

ART = "output/registry-real-data-sources/unified-agenda-parquet"
con = duckdb.connect(":memory:")

cols = """rin, publication_id, ordinal, citation_ordinal, authority_text, authority_type,
parse_status, usc_title, usc_section, usc_section_end, usc_section_span_rule,
usc_section_verdict, usc_section_verdict_reason, usc_section_attested_at_edition,
usc_section_corrected, usc_section_corrected_section,
authority_in_own_cfr_note, cfr_note_part, cfr_title, cfr_part, cfr_section,
usc_title_is_possible, usc_section_magnitude_is_plausible"""

df = con.execute(f"""
select {cols} from '{ART}/unified_agenda_legal_authorities.parquet'
where authority_type = 'usc' and usc_section similar to '[0-9]+-[0-9]+'
""").df()
print("all-digit hyphenated usc_section rows:", len(df))
print(df["usc_section_span_rule"].value_counts(dropna=False))
df.to_parquet("/Users/mikewolfd/.claude/jobs/9dfc0c64/tmp/inv-universe/scratch/hyphen_usc_rows.parquet")

# also grab cfr_references for join-key context (rule's own CFR_LIST)
cfr = con.execute(f"select rin, publication_id, cfr_title, cfr_part, cfr_section from '{ART}/unified_agenda_cfr_references.parquet'").df()
cfr.to_parquet("/Users/mikewolfd/.claude/jobs/9dfc0c64/tmp/inv-universe/scratch/cfr_references_slim.parquet")
print("cfr_references rows:", len(cfr))
