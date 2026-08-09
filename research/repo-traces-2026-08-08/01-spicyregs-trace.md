# SpicyRegs — code trace

**Agent brief:** determine what SpicyRegs actually does by tracing code. **Ignore
every `.md` file** — READMEs, plans, specs and decision ledgers are claims about
intent; report observed behaviour. Read-only.

**Scope:** `/Users/mikewolfd/Work/spicy-regs` (~968 source files, `.venv` /
`node_modules` / `__pycache__` excluded). The nested `RefSpec/` submodule was
excluded and assigned to a separate agent.

**Date:** 2026-08-08 · **Status:** verbatim agent output

---

# What SpicyRegs actually does

**In a paragraph, from code.** SpicyRegs is a **capture-and-seal layer for US
federal regulatory documents**. Sixteen per-publisher readers
(`src/spicy_regs/sources/*.py`) pull from regulations.gov (via the anonymous
Mirrulations S3 mirror), Federal Register, govinfo/eCFR, reginfo.gov,
uscode.house.gov, congress.gov, CourtListener, FCC ECFS, SAM, FEC, LDA,
USAspending, GAO, CRS and supremecourt.gov. Records land as staging Parquet, merge
into an Iceberg catalog on Cloudflare R2 (`sources/iceberg.py` — DuckDB `ATTACH`,
expressed as DELETE+INSERT because R2's catalog rejects `MERGE INTO`,
`iceberg.py:137-139`), and 22 independently-cronned rollups (`pipelines/rollups/`)
publish **32 logical tables** (`data_dictionary/descriptions.yaml`), served
read-only through a DuckDB-backed MCP server. On top of that sits a much larger
second body of work: a 4,000-line sealed `DocumentRelease` v3 protocol, a 993-line
canonical citation/IRI layer, a 513k-row concept registry, and ~51k lines of
document-processing and evaluation machinery (`docpipeline/` 27.7k, `corpora/`
23.7k) that draws corpora, runs model bake-offs, and receipts everything. **The
centre of gravity is not acquisition — it is provenance.** Acquisition is 5.4k
lines; the release/identity/evaluation apparatus is roughly ten times that.

## What it owns

| Capability | Where in code | Produces | Identity |
|---|---|---|---|
| Bulk regulations.gov capture | `sources/mirrulations.py`, `pipelines/regulations.py` | dockets / documents / comments → Iceberg on R2 | **Retained** (`docket_id`, `document_id`, `comment_id`) |
| 15 API source readers | `sources/*.py` | per-source staging Parquet | **Retained** |
| 22 rollup pipelines | `pipelines/rollups/*.py` | 32 published Parquet tables | Retained + derived |
| Citation / identifier layer | `ontology/citations.py` (993 lines) | canonical `urn:rkaf:us:{cfr,usc,rin,frdoc,regsgov,pl}` IRIs | **Minted** — deterministic string composition, no hash (`:362-421`) |
| Identifier edge tables | `transforms/build_{rule_targets,authority_edges,fr_docket_links}.py` | 3 edge tables | Endpoints retained; `evidence_id` minted |
| Agency crosswalk | `tools/build_agency_crosswalk_artifact.py` | 5 Parquet + digest receipt | **Minted** (`agency_code_id`, `crosswalk_id`, `cfr_agency_id`) |
| USC act index / source credits | `sources/uscode_olrc.py`, `uscode_uslm.py` + 2 tools | 5 Parquet | **Retained only** — nothing minted is persisted |
| DocumentRelease v1/v2 | `document_release.py` (2,337 lines) | canonical-JSON release | **Minted** `urn:spicyregs:<type>:<sha256>` (`:96-105`) |
| DocumentRelease v3 | `document_release_v3*.py` (~4,000 lines) | sealed manifest + 11 Arrow tables | `document_id` **retained**; `document_version_id`, `passage_id`, `releaseId` **minted** (`_writer.py:890-902`) |
| Concept registry | `ontology/concepts.py`, `transforms/build_concepts.py` | concepts / assignments / events | **Minted** `concept_<sha256[:24]>`; publisher ids retained in `external_ids_json` |
| Doc processing + evaluation | `docpipeline/`, `corpora/` (51k lines) | corpora draws, bake-offs, receipts | Minted run/artifact ids |
| RKAF projection | `docpipeline/rkaf_projection.py` | Rulespec JSON-LD | Minted carrier-local URNs |
| Serving | `mcp_server.py`, `mcp-server/api/index.py` | MCP `list_sources` / `describe_table` / `query_sql` | — |

**Where document identity lives.** Both generations are real. v3
(`document_release_v3.py`) is the live one: a closed-key manifest with
`releaseId = urn:spicyregs:document-release:v3:<sha256>` over
`{format, formatVersion, content}` — `annotations` (buildRunId, createdAt) sits
deliberately **outside** the identity payload (`:322-337`), so identical content
yields an identical id regardless of build time. It carries 11 Arrow schemas, 14
registered verification codes, and 8 separately-versioned policy ids. A complete
25-member sealed instance exists at
`fixtures/releases/document-release-v3/release.json`.

## The USC verdict: **document-shaped**, decisively

- `usc-act-sections.parquet`: 10,976 rows, only 9,916 distinct
  `(table3_key, act_section)` pairs; 471 pairs repeat, up to 26×; **two rows are
  byte-identical across all 7 columns**. A row's only identity is "the *n*-th
  `<tr>` on page X.htm". The consuming code says so — `ontology/act_index.py:216-219`
  records that a single-valued mapping "silently discarded 1,060 of the sealed
  artifact's 10,976 rows."
- `usc-source-credits.parquet`: **3,702 of 3,721 `usc_identifier` values are
  distinct** — one row per document location. 1,844 rows (49.6%) are stamped
  `refusal='multi_target'`.
- `usc-popular-names.parquet`: 20,865 rows over 13,626 name keys; 48 names map to
  more than one act, 1,398 acts serve more than one name. Many-to-many observations.
- **Zero lifecycle.** No deprecat/supersed/replaced_by/broader/narrower/preferred_label
  anywhere in the path. Versioning is per-directory (`usc-act-index-2026-08-02`), not
  per-term.
- The giveaway: it covers **24 of the 8,400 acts** OLRC lists, because the act set
  comes from `acts_cited_by()` (`tools/build_usc_act_index_artifact.py:151-155`) over
  whatever one corpus cited.

Contrast the repo's own genuinely vocabulary-shaped artifact: `CONCEPT_COLUMNS`
(`ontology/concepts.py:49-62`) has `pref_label`/`definition`/`broader_id`/`status`/
`replaced_by` and lifecycle `EVENT_TYPES`. It is what a controlled vocabulary looks
like here — and the USC tables have none of it. (Though even there, all 513,236 rows
of `output/fused-concept-registry-v1/registry.parquet` have **null `broader_id` and
null `replaced_by`** — FAST's hierarchy was dropped on ingest.)

**Quarantine** is a typed failure sink, not a validation gate: failures land in a
receipted table rather than vanishing. Two independent, non-interoperating mechanisms
in the USC path total **1 quarantined row**; one branch (`entry_without_name`) is
unreachable dead code, and the 665 `also-known-as` rows whose alias target was
silently dropped are not quarantined at all.

## Question 4, figure by figure

| Claim | Verdict | Real |
|---|---|---|
| `rule_targets` ~39,516 | **Verified** | 39,516 — and identifiably the live build: its `source` values match the current `SOURCES` frozenset (`build_rule_targets.py:43-51`). Five other snapshots exist (57 / 28,038 / 40,546 / 334,991 / 335,008) carrying a retired `ua_cfr_ref` source. |
| `authority_edges` ~10,618 | **Refuted — stale** | **11,793**. The 10,618 artifact has 13 columns; current `COLUMNS` and the data dictionary both specify 16 (adds `usc_section_end`, `statute_at_large`, `executive_order`). Same input bytes, newer parser. |
| `fr_docket_links` ~715,080 | **Refuted — dangling** | **893,766**. Two receipts pin `output/rin-ontology-revision-candidate/fr_docket_links.parquet` at 715,080 rows / `sha256:b3409f0ada…`. I hashed that exact path: **`sha256:e55cc0ab…`, 893,766 rows**. The file was rebuilt Aug 2 13:55, *after* both receipts were written. They fail their own digest check. |
| CFR refs across ~205,255 docs | **Verified**, noun wrong | 205,255 — independently recounted. But these are **Federal Register** documents (of 1,004,233), not the 1,987,880-row `documents.parquet`, which has no CFR column at all. |
| ~34,612 CFR-part↔agency rows | **Verified**, semantics wrong | 34,612 exactly. But only 9,284 are rank-1, and the receipt's own `cfr_primary_note` warns `is_most_citing` is "most-citing, then deepest" — *not* the owning agency. Its quarantine (35,662 rows) is **larger than its output**. |
| 1 FP in 4,777 | **Refuted as stated** | **1 in 620**. 4,777 is the detection population; only the three *disagreement* cells (108+233+279=620) were adjudicated. The 4,157-string agreement cell was never checked. The judge was `gemini-3.6-flash` k=1, and the receipt states `"determinism": "NOT deterministic."` Quoting this under a *deterministic* edge budget is a category error. |

**The order of magnitude survives**: **1,137,296** rows across 10 edge tables. But the
claim missed `agenda_item_proceedings` (120,685 rows — a first-class table in
`published.py`'s `MATERIALIZED_TABLES`), the three USC tables, and the two
agency-graph tables. The pattern is stark: **every figure that survived was
recomputable from a file whose digest still matched; every figure that failed was read
out of a receipt whose input had been rebuilt underneath it.**

## Duplication

**Real, and already diverging:**

1. **Three encodings of the same identifiers.**
   `spicysearch/src/spicysearch/identifiers.py` ↔
   `spicy-regs/src/spicy_regs/ontology/citations.py` ↔
   `rulespec/constraints/profiles/us-rulemaking/*.cue`. RIN: spicy-regs
   `citations.py:398` requires `\d{4}-[A-Z]{2}\d{2}`, spicysearch `identifiers.py:89`
   allows `[A-Za-z0-9]{2}` trailing. Docket IDs: spicy-regs accepts 2-digit years
   bare, spicysearch only behind a label. Some fragments are character-identical
   (`_USC_SECTION_ATOM`), so this was copied, not co-derived. spicy-regs' comment at
   `citations.py:396` — *"The one definition of the shape"* — is true in-repo, false
   across the workspace.
2. **Two RefSpec atlas readers, 262 identical lines**: `rulespec/tools/refspec_atlas.py`
   and `spicysearch/src/spicysearch/vocabulary_atlas.py`, differing only in exception
   type — while `refspec.atlas` is provably importable from rulespec. spicysearch has
   a third variant, `vocabulary_atlas_v2.py`.
3. **Six copies of `canonical_json_bytes`** across the four repos.
4. **`DocSpec/archive/legacy-2026-08-05/` is a git-tracked verbatim fork of
   spicy-regs** — 588 files; of 101 Python files, 13 byte-identical and 47 more
   identical after `spicy_regs`→`docspec` rename, including the whole 993-line
   `citations.py`. It still reads `SPICY_REGS_LOCAL_LLM_BASE_URL`.
5. **Intra-repo:** `mcp-server/api/_published.py` and `index.py` are hand-vendored
   near-copies of `src/spicy_regs/published.py` and `mcp_server.py`;
   `congress_bills.py:35` and `crs_reports.py:40` each hardcode the Congress API;
   three CFR-part matchers; two FR-doc patterns of differing strictness. And
   spicy-regs and its own RefSpec submodule *each* fetch `uscode.house.gov` and
   `api.usaspending.gov` separately.

**Not duplication:** the agency crosswalk and date-event artifacts are clean
producer/consumer splits with digest verification. spicysearch makes **no** network
calls to any government host.

## The RefSpec boundary

**Dependency flows one way: spicy_regs → refspec**, as a live editable install
(`.venv/.../refspec.pth` → `RefSpec/src`; `pyproject.toml:147`). ~85% of the surface
is `refspec/vocabulary.py`; the rest is `managed_release`, `accepted_output`,
`release_graph`, `registry/*`. The boundary is **deliberately firewalled** — the two
heaviest consumers import refspec *inside functions*, and seven tests install an
`__import__` hook that raises on any `refspec*` name to prove certain paths stay
clean. The rdflib "file-only atlas reader" is `candidate_release.py:447`, opening
exactly two files (a manifest + `atlas.nq`) with byte-canonical re-serialization
checks.

**Reverse:** no `import spicy_regs` anywhere in RefSpec. But
`RefSpec/tools/generate_atlas_v3_full.py:114` sets `SPICY_REGS_ROOT = ROOT.parent` and
reads two pinned managed-release files from the parent's `output/` — **which is
gitignored, and no committed parent code produces them**. That is the one soft spot: a
reverse dependency on artifacts with no reproducible producer on either side.

**Live defect found and reproduced:** four imports in the parent's test-support modules
reference refspec modules that no longer exist (RefSpec reorganized `registry/` into
`registry/adapters/`). `tests/test_connected_concept_search.py` and
`tests/test_accepted_output_real_boundary.py` **fail at collection**. An editable
install has no version boundary to trip on this.

## Where prose contradicts code

- `docs/evidence/agency-crosswalk-2026-08-02.md` and four other `.md` files quote
  715,080 for `fr_docket_links`; the file they describe no longer exists at that digest
  and now holds 893,766 rows.
- `data_dictionary.py:165-179` declares a 13-column `fr_docket_links` with `subtype`
  **duplicated** and a phantom `modify_date`, omitting six real columns. The actual
  table has 17.
- `pyproject.toml`'s own dependency comments cite `docs/evidence/*.md` measurements as
  the justification for version pins — the pins are load-bearing on prose I was asked
  not to trust.

## What I could not determine

- **Production row counts.** The canonical tables live in the R2 Iceberg catalog. I
  made no network calls. Every count above is from local Parquet — vendored snapshots,
  not the live catalog. The receipt's `federal_register_documents: 1,004,233` and
  `documents_rows: 1,987,880` are *asserted* production scale, not verified.
- **Whether the 893,766 fr_docket_links snapshot is newer or older than the 715,080
  one.** Both carry `publication_date` max 2026-07-23, and `output/` mtimes were
  mass-touched on Aug 2. Content alone doesn't order them.
- **Whether the 8× `rule_targets` gap (40,546 vs 335,008) is dedup or scope.** I
  identified `ua_cfr_ref` as the differing source but did not trace the change that
  retired it.
- **Whether any sealed v3 release exists at scale.** `output/scale-dr-10k-2026-08-05/`
  holds 6,408 captured documents of a 10,000-document draw, with receipts and
  checkpoints but **no sealed release members**. The only complete sealed release on
  disk is the 4-document fixture.
- **Whether the concept registry's empty `broader_id`/`replaced_by`** is deliberate
  policy or unimplemented — the columns and `EVENT_TYPES` exist in code; no
  materialization uses them.
