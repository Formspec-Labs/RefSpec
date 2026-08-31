import pandas as pd, re
df = pd.read_parquet("/Users/mikewolfd/.claude/jobs/9dfc0c64/tmp/inv-universe/scratch/legal_authorities_slim.parquet")
usc_name = r"U\.?\s*S\.?\s*(?:Code\b|C\.?(?:\s*[AS]\.?)?)"
pat_a = re.compile(
    rf"(?P<title>\d+)\.?\s*{usc_name}(?:\s*subtitles?\s+[IVXLC]+\s*,?)?\s*(?:§+\s*)?"
    rf"(?P<part>\d+)\.(?P<section>\d+[A-Za-z]?(?:-\d+[A-Za-z]?)?)",
    re.IGNORECASE,
)
mask_candidates = df["authority_text"].fillna("").str.contains(r"\d\.\d", regex=True)
sub = df[mask_candidates]
hits=[]
for idx,row in sub.iterrows():
    for m in pat_a.finditer(row["authority_text"]):
        hits.append((idx, m.group("title"), m.group("part"), m.group("section"), row["authority_type"], row["usc_title"], row["usc_section"], row["authority_text"]))
hitdf = pd.DataFrame(hits, columns=["idx","title","part","section","authority_type","usc_title","usc_section","authority_text"])
usc_only = hitdf[hitdf.authority_type=="usc"]
unconfirmed = usc_only[~((usc_only.usc_title.astype("Int64").astype(str)==usc_only.title) & (usc_only.usc_section==usc_only.part))]
pd.set_option("display.max_colwidth",200)
print(unconfirmed[["idx","title","part","section","usc_title","usc_section","authority_text"]])
