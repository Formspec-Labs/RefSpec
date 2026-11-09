<!-- markdownlint-disable MD013 -->

# Agency registry: one pinnable agency list with free-text aliases

> **Status:** Decided 2026-11-08 and built (REF-075). The owner chose D1, D2,
> D3 and D6 as recommended, D4 "decide each alias" (no rule-wide derivation),
> and D5 "read citations, then adopt". Section 8 is what was built; sections
> 1-7 are the proposal as the owner read it. Per-item answers live in
> [the decisions file](agency-registry-alias-batch-decisions.json), rendered in
> [the adjudication sheet](agency-registry-alias-batch-adjudication.md).

## 1. Bottom line

- **Batch 1 does not block this.** It was decided on 2026-09-26 (26
  decisions) and released as `agency-registry-2026-09-26` (REF-072), with the
  succession batch (FNS -> FNA) riding in the same release. The design note's
  header still said "awaiting owner review"; this branch corrects it.
- **The artifact already exists.** `output/agency-registry-view/`, sealed by
  `tools/build_agency_registry_view.py`, is the digest-pinned view SpicyRegs
  already vendors (manifest `sha256:0b39812d…`). The plainest path is a
  schema bump of that same view, not a new artifact: add an organizations
  table (all 472 pinned FR agencies with names, abbreviations, parents,
  successors and REF-038 codes) and an aliases table.
- **Aliases go through the existing owner loop.** A third batch,
  `tools/assemble_agency_registry_alias_batch.py`, writes candidates and an
  adjudication sheet from the pinned rosters plus congressional-tech's
  measured demand, under the same decision contract (`load_decisions`,
  content digests, stale-not-dropped). It proposes 70 aliases: 12 mechanical,
  58 judgment (51 recommended yes or a part-of option, 7 recommended no).

## 2. What exists, and the correction to the brief

| Piece | Where | State |
| --- | --- | --- |
| REF-038 projection (331 regulations.gov codes: 321 resolved, 10 abstentions) | `agency_projection.build_agency_projection()`; served in the Atlas parquet-view | Shipped; SpicyRegs vendors it from the full view |
| Registry release: 13 bridges, 10 successions, 4 non-emissions | `load_agency_registry_mapping_release()`; batch files read by digest in `agency_registry_batches()` | Shipped (REF-072) |
| Registry view (bridges, events, non-emissions, current successors) | `seal_agency_registry_view()` in `parquet_view.py`; pin in `tools/build_agency_registry_view.py` | Shipped, schema 1.2; `--check` passes on this branch |
| FR roster: 472 agencies, name, short name, slug, parent | `federal-register-agencies-roster-2026-08-15` | Pinned; the live API now has 473 (new: FR 627, Marine Minerals Administration) |
| Free-text resolution | design note section 1 ("later, a free-text agency name") | Not started until this branch |

## 3. (a) The release: agency-registry view schema 1.3

One directory, one manifest pin, read the way SpicySearch and SpicyRegs read
RefSpec views today (closed membership, member sha256, schema digests, row
counts, logical digest recomputed from rows). Changes, all inside existing
modules:

1. **`agency-registry-organizations.parquet`, 472 rows**, one per pinned FR
   record: `fr_id`, `resource_iri`, `slug`, `name`, `short_name`,
   `parent_fr_id`, `regulations_gov_codes` (REF-038 rows selecting it),
   `current_successors` (from `current_successor_rows()`), plus the derived
   keys of D4. Built from the pinned roster release; asserts nothing new.
   Its roster release digest joins the view's release identity.
2. **`agency-registry-aliases.parquet`**, one row per adopted alias:
   `alias_id`, `name_key`, `target` (the organization named, any held roster,
   or null), `fr_id` and `fr_relation` (`same` or `partOf`), `basis`, `records`,
   and the owner's decision (answer, date, channel, content digest), as the
   bridges table carries it.
3. **REF-038 folded in (D1):** the projection and unresolved tables copied
   into the view, so a consumer pins one manifest instead of two.
4. **Release:** `agency_registry_batches()` gains the alias batch (candidates
   and decisions pinned by digest, as the succession batch is); the release
   emits each adopted alias as a decided item in its metadata, beside the
   non-emissions (D2). The key stays `agency-registry-2026-09-26`;
   `sourceReleaseDigest` and `candidatesDigests` move, as they did for the
   succession batch. Answers map through `_ANSWER_OUTCOMES`/`_OPTION_OUTCOMES`
   exactly as today; an answer with no rule refuses the release.
5. **Seal and verify:** `seal_agency_registry_view()` and
   `verify_agency_registry_view()` take the two tables; `VIEW_MANIFEST_SHA256`
   in `tools/build_agency_registry_view.py` moves once, in the same commit
   as a decision record (REF-075) stating why the contract moved.

Files: `src/refspec/atlas/agency_projection.py` (view rows),
`src/refspec/atlas/parquet_view.py` (members),
`src/refspec/atlas/v3_registry_alignments_entity.py` (batch pin, outcomes),
`tools/build_agency_registry_view.py` (pin), `docs/decisions.md`, the design
note section 8 table, and tests.

**Negative cases the release must refuse** (structure earns its keep): an
alias whose `fr_id` is not a pinned FR record; an alias key adopted twice with
different FR ids; an adopted judgment alias with an unread record (D5); a
stale alias decision; a part-of alias whose FR record is not the target's
roster ancestor where the roster states one.

## 4. (b) The alias set

**Match key.** Every alias is published under `name_key()` (in the batch
tool; it moves to `agency_projection.py` when the view ships): NFKC
case-fold, "&" as "and", parentheticals dropped, punctuation runs to one
space, then "the", "u s", "us", "united states", "of america" dropped. It is
congressional-tech's own normalizer with one repair: it collapses runs first,
so "U. S. Fish and Wildlife Service" keys to the FR name (the one key the
batch finds already resolvable). Publishing the key is what lets both
consumers match the same way (D6).

**Classes.**

- *Mechanical* (12): derived from pinned data with no hand input, each
  refusing a key that reaches more than one FR record:
  `frShortNameEquality`, `frNameWordOrder` ("Land Management Bureau" -> "bureau
  of land management"), `reviewedIdentityPublisherName` (a regulations.gov
  name whose REF-038 row maps to exactly that FR record). The last two agree
  on all 10 keys both reach, which is an independent check of the word-order
  rule against reviewed identities.
- *Judgment* (58): hand rows in `JUDGMENT`, each stating what it names, the FR
  id an FR-keyed consumer gets and how (`same` or `partOf`), a basis
  (`unitWithinFrAgency`, `militaryServiceOfDepartment`, `publisherNameVariant`,
  `statutoryRename`, `secondaryTitle`, `noFrRecord`, `misspelling`), the
  public records, and a recommendation with its reason.
- *Already resolvable* (1) and *excluded* (59: private organizations, tribes,
  places, chambers and courts, titles and fragments, compounds, segmentation
  artifacts), listed with reasons so nothing is dropped silently.

**Warrant and evidence.** Mechanical rows rest on the pinned roster records.
Judgment rows cite statutes, one public law and one executive order; these are
the agent's citations, **not yet retained or read** (`read: false`). D5
proposes that the release refuses an adopted judgment row until its records
are retained under `research/evidence/` and read, as the succession batch did
for FNS -> FNA.

**Demand evidence.**
`research/evidence/agency-alias-demand-2026-11-08/measure.py` re-runs
congressional-tech's `em-fedagency.py` match rule verbatim against the pinned
472-agency roster (it reproduces 2,193 of 3,662 federal-typed appearances
matched, as congressional-tech measured against the live 473) and keys every
unmatched comma segment. 130 keys pass the thresholds (3 federal-typed
appearances, or 25 of any witness type); the input parquet's sha256 is
recorded. The tool refuses an unaccounted demand key, a hand row for a key
outside the demand, and a hand row for a key a rule already derives.

**Scope note.** The three rules reach far beyond this demand: 321 FR records
have a word-order key (no collisions) and 419 have a short name (10 keys
collide, among them `loc`, `doe`, `fs`, `prc`, and the rule leaves those
unresolved). D4 decides whether those become rows for all 472 now.

## 5. Owner decisions

| | Question | Options | Recommendation and why |
| --- | --- | --- | --- |
| D1 | What is the one artifact? | **A** schema 1.3 of the agency-registry view, REF-038 folded in. **B** schema 1.3 without REF-038 (consumers keep vendoring it from the 5 GB parquet-view build). **C** a new "agency names" view beside it. | **A.** One pin for both consumers; REF-038 is 331 small rows; SpicyRegs today pins two artifacts built by two different tools. Con: the view now reads two releases, and REF-038's bytes must be shown row-equal to the vendored copy (logical digest) before SpicyRegs drops it. |
| D2 | How is an adopted alias carried? | **A** a decided item in the release metadata and a view table, as non-emissions are. **B** an owner-reviewed `skosxl:hiddenLabel` on the roster resource. **C** mint a name resource per string and assert `atlas:sameEntityAs`. | **A.** No binding, SHACL or fixture change. B breaks "source-faithful labels" (`RegistryLabel`) and needs a shape amendment and re-seal; C calls a string an entity and mints resources the spine says it never mints. Con of A: aliases are not RDF statements on the Atlas wire; revisit only if a graph consumer appears. |
| D3 | What does an alias resolve to? | **A** the organization it names (any held roster, or none) plus the FR id an FR-keyed consumer gets, as `same` or `partOf`. **B** identity only: drop part-of; VHA, the Marine Corps, CRS and the commands stay unresolved. **C** the held record only, no FR id. | **A.** 39 of the 58 judgment rows are part-of, carrying 405 of the 590 federal-typed appearances in the batch. Part-of claims no identity, and the consumer can ignore it. Con: consumers must read `fr_relation`. |
| D4 | Mechanical aliases: per item, or rule once? | **A** per item, as in this batch. **B** adopt the three rules once (a decision record plus negative tests) and derive keys for all 472 FR records into the organizations table, outside the logical digest like current successors; batches then hold judgment rows only. | **B.** It is what (a)'s "aliases and abbreviations for every agency" needs, and per-item review of a deterministic rule is ceremony. Answer the 12 mechanical rows "yes" either way. Con: a rule bug touches 300+ rows at once, so the collision refusal must be tested. |
| D5 | Does a judgment alias need its records read before release? | **A** yes: retain each cited record under `research/evidence/` and mark it read; the release refuses an unread one. **B** the owner's answer suffices. | **A.** The citations are unread, and the repo's raw-source rule applies (the EO number for "Department of War" in particular). Cost: one capture pass of 33 cited records. |
| D6 | Is `name_key` part of the contract? | **A** publish it (name and doc in the manifest; consumers apply it). **B** publish exact spellings only. | **A.** Without a shared key, the consumer re-derives matching and drifts (congressional-tech's double-space miss). Con: changing the key later moves the contract. |

Not a decision for now: the live FR roster gained FR 627 (Marine Minerals
Administration) after the pinned capture. Refresh as its own capture; the
release ships on the pinned 472 (design note section 10: no new captures in
this work).

## 6. Consumption (sketch; neither repository is edited here)

**SpicyRegs.**

- `src/spicy_regs/reference/refspec/`: replace `agency-projection.parquet`,
  `agency-projection-unresolved.parquet`, the top-level `view-manifest.json`
  and `agency-registry-view/` with one `agency-registry-view/` copy (schema
  1.3), and update the README's provenance table.
- `src/spicy_regs/ontology/agencies.py`: the five `AGENCY_*_SHA256` constants
  and `VIEW_MANIFEST_SHA256` become one `AGENCY_REGISTRY_MANIFEST_SHA256` plus
  `_REGISTRY_TABLE_SHA256` with the new tables. `projection_rows()` and
  `unresolved_rows()` read `registry_rows("projection")` and
  `registry_rows("projection-unresolved")`. `_build_projection` and
  `agency_code_for_fr_agencies` keep their rule.
- `src/spicy_regs/vocabulary_mapping.py` `lookup_agency()`: it stops reading
  the separate parquet-view manifest. It gains a third namespace, `name`
  (free text): key the string with the published `name_key`, look it up in
  the aliases table and the organizations table's names and derived keys,
  and return the FR record with `fr_relation`, the basis, the records and
  the owner decision, or `unmatched`. `federal_register_agency` replies gain
  the organization row (names, short name, parent, successors, codes).
  `mcp_server.py`'s `lookup_agency` docstring drops "Labels are not
  identifiers" for the `name` namespace and says a name match is a reviewed
  alias, never fuzzy.

**congressional-tech.**

- It pins SpicyRegs today in `model/jobs/spicy-regs/spicy-regs.json` (table
  path, sha256, size, source URL), referenced by sha256 from
  `model/jobs/publish-model.json`'s `spicy_regs` entry, and fetched and
  verified by `packages/viewer_publication/src/viewer_publication/spicy_regs_inputs.py`.
- Same shape for RefSpec: `model/jobs/refspec/agency-registry-view.json`
  holding the manifest sha256 and each member's path, sha256 and size; a
  `refspec` entry in `publish-model.json` pinning that file by sha256; and a
  loader beside `spicy_regs_inputs.py` that refuses other bytes and checks the
  manifest's members.
- RefSpec has no public byte host (its R2 buckets have no public access), so
  the bytes are vendored into the repository, as SpicyRegs vendors them. The
  view is about 100 KB. A later public mirror changes only the loader's source.
- The witness matcher (org-entities plan, epic ct-lwxs) keys each comma
  segment with the published `name_key` (dropping its own `n()`), looks it up
  in organization names and keys, then aliases, and records the alias id,
  basis and `fr_relation` on the match.

## 7. Gates run on this branch

- `uv run --frozen python tools/assemble_agency_registry_alias_batch.py`
  (re-derives the JSON and the sheet; passes).
- `uv run --frozen python tools/build_agency_registry_view.py --check` (the
  shipped view is unchanged; passes).
- `uv run --frozen python tools/assemble_agency_registry_batch_1.py --check-committed`
  and the succession batch's check (pass).
- `uv run --frozen pytest tests/test_assemble_agency_registry_alias_batch.py tests/test_assemble_agency_registry_succession_batch.py`
  and `ruff check` on the changed files.

## 8. As built (2026-11-08)

- **Records read.** 47 retained files under
  `research/evidence/agency-alias-records-2026-11-08/` (38 U.S. Code sections
  from govinfo's 2024 edition, Pub. L. 108-271, and Executive Order 14347 with
  its Federal Register search answer), fetched by its `scripts/fetch.py` with a
  fixed anonymous User-Agent; 41 are cited (six of them, Federal Register
  notices, a hearing record and a Forest Service page, from the second
  reading). The other six were read and set aside: 42 U.S.C. 285f and 1863
  (superseded by 281 and 1861, which state the parent), 10 U.S.C. 1073c (does
  not place DHA), 10 U.S.C. 205 (repealed), 16 U.S.C. 1609 (makes the National
  Forest System lands), and the EO search answer (it located the order). Every judgment row quotes the passage it rests on, and
  the tool and the release refuse a passage that is not in the retained bytes.
  The first-pass citations pointed at uscode.house.gov, which answered 404 to
  the probe; govinfo serves the same sections. Where a first-pass citation did not
  itself state the parent, a section that does was added: 42 U.S.C. 281 (NIAID
  in NIH), 42 U.S.C. 1861 (the Board in NSF), 10 U.S.C. 111(b) (the Joint Staff
  and the combatant commands in DOD), and 10 U.S.C. 167/167b; rows that cited
  nothing gained 10 U.S.C. 4127, 8031, 8041, 6 U.S.C. 652, 18 U.S.C. 4041,
  2 U.S.C. 1381 and 1901, and 22 U.S.C. 6431.
- **Decided, all 70.** The owner approved all 12 mechanical aliases one by
  one (D4). 50 of 58 judgment aliases took the owner's recommendation as the
  statutes confirm it: 43 adopted, 7 answered no. The other 8 took it after a
  second reading of the agencies' own records (below): 63 adopted in all.
- **Returned, then confirmed (8).** No statute confirmed these (16 U.S.C. 1609
  even defines the National Forest System as lands). The owner chose "find
  agency pages, then adopt"; defense.gov, af.mil, spaceforce.mil,
  marines.mil, africom.mil, usfk.mil and state.gov answered 403 (a bot
  challenge, not bypassed), so the agencies' own records came from the
  Federal Register, govinfo and fs.usda.gov:
  - Africa and Transportation Command: DoD's FOIA rule, 82 FR 1192 (32 CFR
    286), lists both among the DoD Components, beside the other combatant
    commands.
  - U.S. Forces Korea: USPACOM's answer for the record to the House Armed
    Services Committee (CHRG-113hhrg79955) counts it among USPACOM's
    subordinate unified commands; with the FOIA rule and 10 U.S.C. 111(b)(11),
    part of DOD.
  - Headquarters Air Force: an Air Force Privacy Act notice, 74 FR 6591, names
    "Headquarters United States Air Force", which keys to the same alias.
  - Air Force Space Command: Pub. L. 116-92 sec. 952(a) (10 U.S.C. 9081 note)
    redesignated it the Space Force, within the Department of the Air Force.
    The alias names the Space Force (OPM AF4G), part of FR 13.
  - Bureau of Near Eastern Affairs: a State notice, 88 FR 14438, signed from
    the bureau, "Department of State".
  - "USMC": a Navy notice, 91 FR 60950, "AGENCY: Department of the Navy" and
    "the United States Marine Corps (USMC) announces".
  - National Forest System: the Forest Service's organization page lists it as
    a headquarters program unit; the alias cites the page, not 16 U.S.C. 1609.
- **View 1.3.** `tools/build_agency_registry_view.py` pins manifest
  `sha256:7a806ea0…`: 13 bridges, 15 event rows, 11 non-emissions (4 + 7
  rejected aliases), 15 current successors, 63 aliases, 472 organizations, and
  REF-038's 321 + 10 rows. The REF-038 rows equal SpicyRegs' vendored copy row
  for row, schemas equal; the bytes differ only by pyarrow version (SpicyRegs'
  README records the same two rebuild digests). Every alias in the batch is
  decided.
- **Release pins.** `.github/workflows/release.yml` pins the 1.3 view and a
  review receipt and evidence manifest extended to the alias batch;
  `tools/atlas_independent_agency.py` derives and compares all eight tables
  independently and reads every cited record.
