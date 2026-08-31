import pandas as pd, json

SC = "scratch"

# shape (a): full 36-key table already built
shape_a = json.load(open(f"{SC}/shape_a_witness_table.json"))
with open("shape_a_reg_shaped_all36.json","w") as f:
    json.dump(shape_a, f, indent=2, default=str)

# shape (a) direct-witness subset detail
ra = pd.read_json(f"{SC}/shape_a_direct_witness.json")
hits = pd.read_json(f"{SC}/shape_a_hits.json")
df = pd.read_parquet(f"{SC}/legal_authorities_slim.parquet")
sub = df.loc[hits["idx"]].reset_index().rename(columns={"index":"idx"})
sub["reg_part"] = hits["part"].values
sub["reg_section"] = hits["section"].values
sub = sub.merge(ra, on="idx")
exact = sub[sub.cfr_list_exact_match][["rin","publication_id","authority_text","usc_title","usc_section",
    "reg_part","reg_section","usc_section_verdict","authority_in_own_cfr_note","cfr_note_part"]]
exact.to_json("shape_a_direct_witnessed_19rows.json", orient="records", indent=2)

# shape (b): full witnessed 19-key / 190-row table
witnessed_b = pd.read_json(f"{SC}/shape_b_witnessed_final.json")
witnessed_b[["rin","publication_id","authority_text","usc_title","usc_section",
    "usc_section_verdict","authority_in_own_cfr_note","cfr_note_part"]].to_json(
    "shape_b_reg_suffix_witnessed_190rows.json", orient="records", indent=2)

# shape (b) full 820-row candidate pool (unwitnessed + witnessed) for completeness
dfb = pd.read_parquet(f"{SC}/hyphen_usc_rows2.parquet")
dfb[["rin","publication_id","authority_text","usc_title","usc_section","usc_section_verdict",
     "authority_in_own_cfr_note","cfr_note_part"]].to_json("shape_b_all_820_candidate_pool.json", orient="records", indent=2)

# shape (c): narrow pool + seeded 20 detail
narrow = pd.read_json(f"{SC}/shape_c_narrow.json")
narrow[["rin","publication_id","authority_text","usc_title","usc_section","usc_section_verdict",
        "authority_in_own_cfr_note","cfr_note_part","is_chapter_number","is_real_section"]].to_json(
    "shape_c_chapter_in_slot_narrow_2370rows.json", orient="records", indent=2)

sample_keys_c = json.load(open(f"{SC}/shape_c_sample_keys.json"))
with open("shape_c_seeded20_keys.json","w") as f:
    json.dump(sample_keys_c, f, indent=2)

sample_keys_b = json.load(open(f"{SC}/shape_b_sample_keys.json"))  # pre-witness naive seed, kept for record
with open("shape_b_seeded20_keys_PRE_witness_refinement.json","w") as f:
    json.dump(sample_keys_b, f, indent=2)

# shape (d)
shape_d = pd.read_json(f"{SC}/shape_d_no_marker.json")
shape_d.to_json("shape_d_osha_bare_no_title_pool_250rows.json", orient="records", indent=2)

print("done")
import os
for fn in sorted(os.listdir(".")):
    if fn.endswith(".json"):
        print(fn, os.path.getsize(fn))
