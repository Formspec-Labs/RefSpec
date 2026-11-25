# Agency alias records, retained 2026-11-25

The public records that agency alias batch 2 cites
(`tools/assemble_agency_registry_alias_batch_2.py`), retained locally so every
cited passage can be checked verbatim against the retained bytes via
`refspec.atlas.v3_registry_alignments_entity.alias_record_is_read()` (REF-075).

`scripts/fetch.py` fetched U.S. Code sections from govinfo's link service,
Congressional hearing records from govinfo, Federal Register documents from
federalregister.gov, and agency pages from official `.gov` hosts using the fixed
anonymous User-Agent `refspec-agency-aliases/0.1 (research probe)`.
`manifest.json` records each URL, final URL, HTTP status, byte size, sha256,
and fetch timestamp.
