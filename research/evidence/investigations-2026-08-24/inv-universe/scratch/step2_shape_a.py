import pandas as pd, re, json

df = pd.read_parquet("/Users/mikewolfd/.claude/jobs/9dfc0c64/tmp/inv-universe/scratch/legal_authorities_slim.parquet")

usc_name = r"U\.?\s*S\.?\s*(?:Code\b|C\.?(?:\s*[AS]\.?)?)"
# reg-shaped: title USC part.section  (part.section = \d+\.\d+ with optional -digit / letters / (pinpoint))
pat_a = re.compile(
    rf"(?P<title>\d+)\.?\s*{usc_name}(?:\s*subtitles?\s+[IVXLC]+\s*,?)?\s*(?:§+\s*)?"
    rf"(?P<part>\d+)\.(?P<section>\d+[A-Za-z]?(?:-\d+[A-Za-z]?)?)",
    re.IGNORECASE,
)

def find_a(text):
    if not isinstance(text, str):
        return []
    return [(m.group("title"), m.group("part"), m.group("section"), m.start()) for m in pat_a.finditer(text)]

mask_candidates = df["authority_text"].fillna("").str.contains(r"\d\.\d", regex=True)
sub = df[mask_candidates].copy()
print("rows with a dotted-digit anywhere in authority_text (usc slot broad):", len(sub))

hits = []
for idx, row in sub.iterrows():
    matches = find_a(row["authority_text"])
    for (title, part, section, pos) in matches:
        hits.append({
            "idx": idx, "title": title, "part": part, "section": section, "pos": pos,
            "usc_title": row["usc_title"], "usc_section": row["usc_section"], "authority_type": row["authority_type"],
        })

hitdf = pd.DataFrame(hits)
print("total pattern-A matches (any row, any authority_type):", len(hitdf))
print(hitdf.groupby("authority_type").size() if len(hitdf) else "none")

# Restrict to rows where the grammar's usc_title/usc_section actually correspond
# to a truncated read of this dotted token (title matches, section == part).
if len(hitdf):
    hitdf["usc_title_str"] = hitdf["usc_title"].astype("Int64").astype(str)
    confirmed = hitdf[(hitdf["authority_type"]=="usc") &
                       (hitdf["usc_title_str"]==hitdf["title"]) &
                       (hitdf["usc_section"]==hitdf["part"])]
    print("confirmed truncated-to-part rows:", len(confirmed))
    print("distinct authority_text idx confirmed:", confirmed["idx"].nunique())
    confirmed.to_json("/Users/mikewolfd/.claude/jobs/9dfc0c64/tmp/inv-universe/scratch/shape_a_hits.json", orient="records", indent=2)
