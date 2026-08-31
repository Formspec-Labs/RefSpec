# Read-only investigations of 2026-08-23

Evidence behind tasks #29, #31, #42, #44, #45 and the #30 unit (whose own
roster is committed at unified-agenda-fr-document-roster-2026-08-23).
Every directory was produced by a read-only subagent against the faithful
baseline of rebuild #7 (receipt sha256 17e61179…) and the pinned editions;
nothing here was an input to any build. The reports themselves are in the
task descriptions (TaskList #29/#31/#42/#44/#45) and the ledger.

- `inv-29/` — the 67 "LEGAL AUTHORITY CONT" continuation records verbatim
  (records.json: ADDITIONAL_INFO, box texts, extracted continuation, the
  grammar's rows, a restates-box flag per row) and the scan scripts.
- `inv-31/` — H1 join runs (Tier A 546 / Tier B 46), H2 title-carry
  candidates (438), H4 edit-distance candidates (176), the seeded specimen
  files, and the measurement scripts under scratch/.
- `inv-acts/` — act-name carry candidates (62 rows) and the initialism
  population (752 rows / 118 tokens) with per-token and per-row evidence.
- `inv-frvol/` — the Federal Register per-volume last-page roster
  (fr_volume_last_pages_1_90.csv; volumes.csv from the FR API for 1995–2025;
  govinfo_volumes_1_58_raw.csv from govinfo's per-issue MODS for 1936–1994)
  with every fetched response under raw/ and SHA256SUMS.txt.
- `inv-initialisms/` — initialisms.csv (118 tokens with evidence tier and
  status) and the fetched publisher evidence under raw/ with SHA256SUMS.txt.

Left out of the commit (large scratch derivations or bytes already pinned
elsewhere), with the digests of the copies in the job directory:
- `inv-acts/rows_sorted.pkl` — 96674384 bytes, sha256 a2bc019a7381fb9bf07707cfb00db545e13c6ec4ffbe5fb430245ba5ec9a1303
- `inv-frvol/analysis.duckdb` — 49819648 bytes, sha256 cd2b9420c5c237185949e3f0615558e02f55e53f3e2f45546c152d2c334a1e89
- `inv-31/scratch/boxes.jsonl` — 26536367 bytes, sha256 6c2ae38b407b06c641650f4e306f074cda3fe347270873f445d2152cc0f05155
- `inv-initialisms/raw/popularnames.htm` — 11101687 bytes, sha256 7cbacdbcea8834be6591226dfc8c0f1714bbf7006a0b2dff300f3112f1c26489
- `inv-frvol/raw/govinfo_fr_2020-12-31.pdf` — 7742607 bytes, sha256 1c29e8c098bc182c825946f8a845e59ee471f60b67cd3b53f587207d8a1e75ea
`popularnames.htm` is the OLRC Popular Name Table already carried
byte-identical inside output/usc-act-index-2026-08-22; the PDF is the
2020-12-31 issue of the Federal Register from govinfo, used only to
confirm a page range the MODS record states.
