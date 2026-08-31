import duckdb, json, random
con=duckdb.connect('/tmp/silent/work.db')
random.seed(20260822)
# Frame: rows that produced a citation (exclude unstated sentinels and hard refusals)
FRAME="parse_status IN ('ok','partial','corroborated')"
print("frame rows:", con.execute(f"SELECT count(*) FROM la WHERE {FRAME}").fetchone())
print("frame texts:", con.execute(f"SELECT count(DISTINCT authority_text) FROM la WHERE {FRAME}").fetchone())

# Sample A: uniform over DISTINCT TEXTS
A=con.execute(f"""
SELECT authority_text, count(*) nrows, string_agg(DISTINCT authority_type,',') atypes,
       string_agg(DISTINCT parse_status,',') astatuses
FROM la WHERE {FRAME} GROUP BY 1 ORDER BY hash(authority_text || 'saltA') LIMIT 150
""").fetchall()
# Sample B: probability proportional to rows  == uniform over ROWS
B=con.execute(f"""
WITH r AS (SELECT authority_text, ordinal, citation_ordinal, rin, publication_id,
             row_number() OVER (ORDER BY hash(rin||publication_id||ordinal::VARCHAR||citation_ordinal::VARCHAR||'saltB')) rn
           FROM la WHERE {FRAME})
SELECT authority_text, count(*) FROM r WHERE rn<=150 GROUP BY 1
""").fetchall()
print("sample A texts:",len(A), " sample B distinct texts:",len(B))

def dump(name, rows):
    out=[]
    for rec in rows:
        t=rec[0]
        cits=con.execute("""SELECT DISTINCT citation_ordinal, authority_type, parse_status, usc_title, usc_section,
            usc_section_end, usc_chapter, cfr_title, cfr_part, public_law, executive_order, statute_volume, statute_page,
            act_key, act_section, case_reporter, case_volume, case_page, fr_volume, fr_page, reorganization_plan,
            revised_statute_section, dc_code_section, usc_appendix, usc_note, corroboration_rule
            FROM la WHERE authority_text = ? ORDER BY citation_ordinal""",[t]).fetchall()
        cols=['citation_ordinal','type','status','usc_title','usc_section','usc_section_end','usc_chapter','cfr_title',
              'cfr_part','public_law','executive_order','stat_vol','stat_page','act_key','act_section','case_reporter',
              'case_vol','case_page','fr_vol','fr_page','reorg','rev_stat','dc_code','usc_app','usc_note','corrob']
        agencies=con.execute("SELECT DISTINCT substr(rin,1,4) FROM la WHERE authority_text=? LIMIT 5",[t]).fetchall()
        eds=con.execute("SELECT min(publication_id), max(publication_id) FROM la WHERE authority_text=?",[t]).fetchone()
        out.append({"text":t,"rows":rec[1],"rin_prefixes":[a[0] for a in agencies],"editions":list(eds),
                    "citations":[{k:v for k,v in zip(cols,c) if v is not None} for c in cits]})
    open(f"/tmp/silent/{name}.json","w").write(json.dumps(out,indent=1,default=str))
    print(name,"->",len(out))
dump("sampleA",A); dump("sampleB",B)
