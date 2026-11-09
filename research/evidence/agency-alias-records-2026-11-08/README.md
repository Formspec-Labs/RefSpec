# Agency alias records, retained 2026-11-08

The public records the agency alias batch's judgment rows cite
(`tools/assemble_agency_registry_alias_batch.py`, `JUDGMENT`), retained so the
passage each row quotes can be checked against the bytes. `scripts/fetch.py`
fetched them from govinfo (U.S. Code, 2024 edition, through its link service;
Pub. L. 108-271) and the Federal Register (Executive Order 14347) with the
fixed User-Agent `refspec-agency-aliases/0.1 (research probe)`; `manifest.json`
records each URL, final URL, status, size, sha256 and time.

`refspec.atlas.v3_registry_alignments_entity.alias_record_is_read()` holds a
record read only while its file hashes as recorded and contains the quoted
passage; the release refuses an adopted alias otherwise (REF-075).
uscode.house.gov answered 404 to this probe for every section, so govinfo is
the host of record.
