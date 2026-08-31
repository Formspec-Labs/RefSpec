## ASSETS AT RISK

1. **Exact historical datasets and the surviving SpicySearch commands that depend on them**

   - Paths: [spicy-regs/output](/Users/mikewolfd/Work/spicy-regs/output), [spicy-regs-landing/output](/Users/mikewolfd/Work/spicy-regs-landing/output)
   - These contain roughly 23.1 GB and 9.3 GB respectively. No surviving repository contains byte-identical copies.
   - SpicySearch still hard-codes these locations in current scripts and fixtures, including:
     - `rulespec-stabilization-candidate-final/{federal_register,documents}.parquet`
     - `date-event-artifact-2026-08-01`
     - `court-data-2026-08-22`
     - `mixed-real-data-corpus-v2`
   - [date-events-full-pin.json](/Users/mikewolfd/Work/spicysearch/fixtures/releases/date-events-full-pin.json), multiple derived-tag fixtures, and more than fifteen research scripts become unresolvable when the directory disappears.
   - This is the highest-risk loss because the algorithms survived, but the exact populations used to justify thresholds, rankings, and coverage claims did not.

2. **The metadata-complete Regulations.gov catalog and its closed input universe**

   - Paths: [metadata-complete release](/Users/mikewolfd/Work/spicy-regs-landing/output/source-catalog-release-regulations-gov-2021-2025-metadata-complete), [input locks](/Users/mikewolfd/Work/spicy-regs-landing/output/source-catalog-release-regulations-gov-2021-2025-metadata-complete-inputs/inputs.json), [composition census](/Users/mikewolfd/Work/spicy-regs-landing/output/source-catalog-release-regulations-gov-2021-2025-metadata-complete-composition.json), [mirror index](/Users/mikewolfd/Work/spicy-regs-landing/output/mirrulations-mirror-index)
   - Unique pins:
     - documents: `sha256:5b9a502…`, 1,993,040 rows
     - dockets: `sha256:b14cd488…`, 276,326 rows
     - Federal Register: `sha256:e03c2f99…`, 801,541 rows
     - composite source version: `4782ff…`
     - requested-universe digest: `90532b…`
     - selected-set digest: `1506995…`
     - 83,064-document mirror index with 88,645 fetched renditions
   - The final release records 83,929 selected, 1,667,133 excluded, 238,574 unavailable, 3,279 failed, 125 deleted, and zero unaccounted items. Its 3.95 GB `source-items.json` is the only exact membership and per-item disposition record.
   - DocSpec recreated the catalog model and policy, but cannot reproduce this release from mutable upstream URLs without these source bytes and mirror records. SpicySearch’s own history says the candidate was neither published nor assigned another durable home.

3. **Receipt-only run evidence**

   The following exact combinations of population, input digest, output digest, and run policy do not exist in the four surviving repositories. Some conclusions are summarized elsewhere, but not the complete evidence tuple.

   - [agency crosswalk receipt](/Users/mikewolfd/Work/spicy-regs/output/agency-crosswalk-2026-08-02/receipt.json):

     ```text
     crosswalk_rows=914
     tier_histogram={confident:124, probable:29, ambiguous:23, unmapped:140}
     fr_docket_links_rows=715080
     joined_raw=47338
     joined_after_normalization=88073
     foreign_identifier=579669
     quarantine_rows=35662
     ```

     It uniquely records the hard-won rule that “most-citing” is not ownership, decorated docket identifiers may be normalized, foreign identifiers remain coverage rather than quarantine, and collisions must never be guessed. The output Parquet digests are not preserved elsewhere.

   - [date-event receipt](/Users/mikewolfd/Work/spicy-regs/output/date-event-artifact-2026-08-01/receipt.json):

     ```text
     events_total=845784
     comment_open=298360
     comment_close=452360
     effective=95064
     quarantine_total=3966
     date-events.parquet=sha256:98d31c7…
     ```

     It also records that ECFS ingestion began on 2026-06-30 and that zero of 21,054 FCC proceedings had a usable window. SpicySearch preserves a 75-row slice, not this full artifact.

   - [citation detection receipt](/Users/mikewolfd/Work/spicy-regs/output/citation-bakeoff-2026-08-02/detection-receipt.json) and [adjudication receipt](/Users/mikewolfd/Work/spicy-regs/output/citation-bakeoff-2026-08-02/adjudication-receipt.json):

     ```text
     authority strings=4777, digest=sha256:e880ea83…
     extended comparison={both:4227, citeurl_only:38, current_only:257, neither:255}
     adjudicated=620
     model=gemini-3.6-flash
     spend=$0.2448583
     tokens={input:448836, output:44083}
     adjudication.jsonl=sha256:0af1ef8…
     ```

     The receipt also freezes CiteURL `12.0.3`, Markdown `3.10.3`, Python `3.12.9`, and the otherwise undocumented fact that CiteURL imported an undeclared Markdown dependency.

   - Retrieval receipts uniquely record the evaluated run sizes:
     - deterministic: 300 artifacts, 25 queries, 1,500 candidates
     - BGE: 184 artifacts, 35 queries, 5,510 candidates, 46 truncated inputs

4. **Frozen sample captures not copied to a surviving repository**

   - Path: [sample-data](/Users/mikewolfd/Work/spicy-regs/sample-data)
   - Unique bytes include the bill HTML/CFR XML document-file pair, the ACF Regulations.gov JSON/PDF pair, the CBO DataDome refusal, and GovInfo summary/PREMIS captures.
   - The domain snapshot also preserves a dated census not recreated elsewhere: 1,990,136 Regulations.gov documents, 276,326 dockets, and 3,954 Unified Agenda entries, with exact type, priority, and stage distributions.
   - The CBO RSS, FCC ECFS, Regulations.gov OpenAPI, and Reginfo XSD captures are not at risk: RefSpec holds exact pinned copies.

5. **Operational knowledge that exists only in added workflows**

   - Paths: [.github/workflows](/Users/mikewolfd/Work/spicy-regs/.github/workflows)
   - Unique scheduling and ordering:
     - bill subjects: daily `21:15 UTC`, one hour after bill ingestion
     - CourtListener clusters: Monday `04:20 UTC`, because bulk dumps change monthly to quarterly
     - court opinion bodies: Monday `05:40 UTC`, after clusters, using bounded slices
     - Supreme Court opinions: weekdays `19:30 UTC`, based on morning publication practice
     - ontology: identity refresh Monday–Saturday and full convergence Sunday at `02:00 UTC`; 90-minute budget; serialized publication; seven-day failure artifacts
   - [deploy-mcp.yml](/Users/mikewolfd/Work/spicy-regs/.github/workflows/deploy-mcp.yml) uniquely captures the production lesson that a Vercel deployment may report ready while every request returns 500. It therefore performs a real MCP initialization, retries five times with 15-second alias-propagation waits, and requires `serverInfo`, not merely HTTP 200.
   - The twelve modified workflows mostly add submodule checkout and a package-build gate. Those changes are superseded by the installed-package/file-exchange decisions. Existing upstream schedules remain on `origin/main`.

6. **Source-specific operating limits in the data dictionary**

   - Path: [descriptions.yaml](/Users/mikewolfd/Work/spicy-regs/data_dictionary/descriptions.yaml)
   - Unique rules include:
     - failed bill-subject fetches write no row; a null subject means a successful answer with no assignment
     - a RIN is evidence, never action or proceeding identity
     - Unified Agenda CFR values never fan out through RIN equality
     - failed authority parses and ranges remain searchable evidence
     - CourtListener `/clusters/` returns 401 without credentials, making the bulk path necessary
     - the 2026-06-30 opinions dump was measured at 50.8 GiB compressed, about 422 GiB expanded, roughly 1.8 MiB/s, and about 8.6 hours for a full pass; the production rollup therefore deliberately takes a bounded partial slice
   - DocSpec recreates generic bounded processing and now has a pinned CourtListener listing fixture. It does not preserve these source-specific measurements or scheduling rationale.

7. **Historical schema and conformance pins**

   - Paths: [conformance/rulespec-l0.yaml](/Users/mikewolfd/Work/spicy-regs/conformance/rulespec-l0.yaml), [document-release fixtures](/Users/mikewolfd/Work/spicy-regs/fixtures), [landing Rulespec pin](/Users/mikewolfd/Work/spicy-regs-landing/src/spicy_regs/fixtures/rulespec)
   - Unique historical identities include:
     - Rulespec version `sha256:6e5506…`
     - L0 corpus snapshot `0e4b…`
     - evidence digest `3a609…`
     - candidate release `urn:rulespec:core:2de89ad…`
     - schema-set digest `cffb8f62…`
   - Rulespec and DocSpec preserve the behaviors—closed membership, incremental equivalence, evidence resolution, and negative cases—but not these exact old release and schema identities. They matter only for replaying the abandoned candidate.

8. **Experimental applicability policy**

   - Paths: [source-profile-catalog-v0.json](/Users/mikewolfd/Work/spicy-regs/policies/source-profile-catalog-v0.json), [profile-resource-applicability-v0.json](/Users/mikewolfd/Work/spicy-regs/policies/profile-resource-applicability-v0.json)
   - These uniquely preserve the historical mapping of 19 source tables to extraction modes and 26 resource applications.
   - They should be archived as lineage, not restored as authority: their RefSpec catalog digest is stale, several referenced resources were retired, and REF-022/024/048 replaced the ownership model.

### Migration manifest: all 16 dispositions

Path: [spicysearch-product-migration-manifest.json](/Users/mikewolfd/Work/spicy-regs-landing/docs/migration/spicysearch-product-migration-manifest.json)

- **Still directionally accurate:** 1, 2, 4, 5, 9, 11, 13, 14.
- **Accurate only in the dirty August 27 version:** 6 and 16. The committed August 1 version left capture and the predecessor document release in SpicyRegs; REF-048 moved both to DocSpec.
- **Partly superseded:**
  - **3:** semantic retrieval remains SpicySearch-owned, but comments cannot enter candidate generation or ranking under the current search decision.
  - **7:** processing-segment construction belongs to DocSpec under REF-048, not Rulespec Extrapolator.
  - **8:** the mixed runtime must split: DocSpec constructs segments, Rulespec Extrapolator performs evidence-bound logical structuring, and REF-022 assigns snapshot topic tagging to SpicySearch. Baseline approval remains parked.
  - **10:** portable shapes remain Rulespec Core, but source representations and fragments now belong to DocSpec rather than SpicyRegs.
  - **12:** RefSpec ownership remains correct; the named `bindings/atlas/1.0` destination is obsolete after Atlas 1.0/2.0 retirement and Atlas 3.1 adoption.
  - **15:** the 1995 thesaurus survives only as historical/evidence-only material. Its 1995→2025 crosswalk is not authorized as an active mapping or managed-vocabulary output.
- **Status fields are stale even where disposition is correct:** DocSpec and the other surviving repositories have implemented substantially more than the August 1 “not yet moved” wording states.

## REPRODUCIBLE

- **Notebooks:** all 13 tracked `.ipynb` files and their README already exist on `origin/main`; neither abandoned branch added or changed them. Their methods—substring search, BM25/vector/RRF experiments, campaign detection, sentiment heuristics—remain available. Exact notebook outputs are not reproducible because they read mutable public Parquet URLs without input digests.
- **Catalog and document behavior:** DocSpec now owns and implements `SourceCatalog`, `SourceItem`, sampling, joins, source-state accounting, capture, segmentation, and `DocumentRelease`. Behavior can be regenerated from new sealed source-native inputs, but not with the archived release’s exact membership.
- **Rulespec behavior:** Rulespec preserves generic artifact validation and current Core/Extrapolator release fixtures. The archived v3 fixture pair is replaceable for conformance testing, though not byte-for-byte replay.
- **Vocabulary behavior:** RefSpec preserves the authoritative publisher captures, current Atlas 3.1 machinery, the CBO/FCC/OpenAPI/XSD pins, and the 1995 thesaurus as explicitly historical evidence. The fused registry and old applicability outputs are not needed as current authority.
- **Search behavior:** SpicySearch contains current lexical, dense, hybrid, replay, tagging, and evaluation implementations. Reproducing the archived measurements requires first replacing its absolute `spicy-regs/output/` dependencies with copied sealed inputs.
- **Upstream workflows:** workflows unchanged from `origin/main`, plus their existing schedules, remain upstream. Only the new operational timings, MCP smoke-test budget, ontology schedule, and documentation-publication exception need separate preservation.

No files or repository state were changed during this analysis.


