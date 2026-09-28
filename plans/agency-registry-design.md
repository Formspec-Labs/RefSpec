<!-- markdownlint-disable MD013 -->

# Agency registry design — one join-through for every Spicy source

> **Status:** Proposed, awaiting owner review. Batch 1's candidates sit beside
> this note as
> [agency-registry-batch-1-candidates.md](agency-registry-batch-1-candidates.md)
> and its JSON, and the owner decides from the generated
> [adjudication sheet](agency-registry-batch-1-adjudication.md); all three are
> written by `tools/assemble_agency_registry_batch_1.py` and verified by its
> `--check`, and the owner's answers live in
> [agency-registry-batch-1-decisions.json](agency-registry-batch-1-decisions.json)
> (empty until the owner decides). Nothing in them is an assertion. Extends REF-038 (decision
> ledger), whose projection and `reverse_agency_projection()` in
> `src/refspec/atlas/agency_projection.py` remain the authority until an
> adjudicated registry release replaces them.
>
> **Evidence base:** the five pinned rosters and the REF-038 identity mapping
> release (digests inside the candidate JSON), read-only; the 2026-09-26
> rulemaking replay (`federal_register.parquet`
> `sha256:7c42aec8…`, `proceedings.parquet` `sha256:6874466c…`); and spicy-regs'
> own resolution rule at 680009a for section 9.

## 1. Goal and consumers

One agency registry that every source in the Spicy stack joins through.
REF-038 mapped 331 regulations.gov codes one way to organizations; this design
finishes the other directions and the time dimension so that a Federal
Register agency id, an eCFR slug, a Federal Hierarchy organization, and (later)
a free-text agency name all resolve to the same registry row. Consumers:

- **spicy-regs** picks up each registry release by digest bump, as it does the
  projection view today (its decision 56 already consumes
  `reverse_agency_projection()`).
- **SpicySearch and DocSpec** already pin the projection view inside the
  compact search view; the registry view rides the same sealed path (§8).

Every adopted row is a consumer-visible change, not only a gain in coverage:
under spicy-regs' current rule, bridges and renames re-route documents that
already resolve — mostly from a parent department's code to the successor's
(HCFA's documents from HHS to CMS, 1,577 rows; §9). Whether spicy-regs applies
forward successor lookups to historical documents at all is spicy-regs' own
decision; the registry states the events and leaves that reading to the
consumer.

## 2. Spine

Organizations drawn from the union of the held rosters — exactly the five
releases REF-038 pins, no new captures:

| Roster | Release | Resources |
| --- | --- | ---: |
| Federal Register agencies | `federal-register-agencies-roster-2026-08-15` | 472 |
| Federal Hierarchy organizations | `federal-hierarchy-orgs-complete-2026-08-15` | 907 |
| OPM EHRI agency subelements | `opm-ehri-agency-subelement-2026-08-04` | 798 |
| eCFR agencies | `ecfr-agencies-roster-2026-08-15` | 316 |
| regulations.gov agencies | `regulations-gov-agencies-roster-2026-08-16` | 331 |

The spine mints no organization; every row is a roster resource under its
publisher IRI (`urn:ref:federal-register-agency:<id>`,
`urn:ref:ecfr-agency:<slug>`, `urn:ref:federal-hierarchy-org:<id>`). OPM sits
in the spine for later batches. Later rosters (lobbying filings, court dockets)
join as new source *values* against this spine, never as parallel
organizations.

## 3. Relations

- **`sameEntityAs`** (identity): two roster rows name the same organization,
  asserted one way with REF-038's shape — two E4 `humanReview` evidence
  records from the owner, a basis from the closed `AgencyDecisionBasis`
  vocabulary, both publishers' sealed names (the field REF-038's
  `publisher_name` seals: FR `name`, eCFR `name`, Federal Hierarchy
  `fhorgname`, never a display label), and both structured parents. Each
  candidate carries the proposed basis, the sealed names and the parents, so
  the owner approves text a release can reproduce; the evidence records exist
  only once the owner decides. How a candidate is *found* is never its basis: REF-038 refuses
  equal strings from different identifier authorities (Federal Register slug
  versus eCFR slug among them), so the eCFR bridges were located by slug
  equality and are submitted on publisher evidence. A shared short name is an
  acronym collision, not identity.
- **Succession** (time), as a dated change event: one defunct *original*
  organization, one or more *resulting* organizations, one effective date, and
  the public records behind them (statute, reorganization plan, or FR notice,
  with URL); a split names the functions each result took. The event is one
  decision: its rows are accepted together or not at all. The **rename
  rule:** a succession links two records the *same* roster holds (batch 1's
  are all Federal Register pairs); a stale name held by *another* roster is
  identity evidence — the Federal Hierarchy still publishes the Udall
  Foundation's pre-2009 name.
- **`partOf`** (structure): publisher-asserted parentage, already carried as
  `atlas:parentEntity` inside each roster and exposed as-is. No cross-roster
  `partOf` is minted yet; the first candidate for one — the eCFR's United
  States Section of the International Boundary and Water Commission as part of
  the binational commission FR 255 names — is recorded as the closest
  alternative to a withdrawn identity row (§5), for a later batch.

**Why succession never folds into identity.** Every batch-1 event has a date a
public record states, and four are splits. `sameEntityAs` is symmetric and
timeless: folding a rename or a split into it would equate two records that
the Register mostly files apart, misroute every pre-2003 INS document to
entities that never published it, and destroy the date the record states.
The periods are rarely clean, which is why the date must be carried rather than
inferred from where the Register files documents (candidate JSON,
`measured.event_periods`, which lists each printed heading): 24 of HCFA's
1,621 mentions fall on or after the 2001-06-29 order — 23 printed under the old
heading through 2002-04-26, and one 2013 document headed "Agency for
Healthcare Research and Quality Agency" that the Register maps to HCFA's
record. All 342 of the Postal Regulatory Commission's mentions before its
2006-12-20 redesignation are printed "POSTAL RATE COMMISSION" (from 1994),
while the Postal Rate Commission's own record, FR 564, holds one 2003 document
headed "POSTAL RATE COMMISSION 39 U.S.C. 3623". The sheet flags both as not
period-disjoint. FR 564's own roster description is the Postal Regulatory
Commission's post-PAEA text, so it may be a duplicate record of the same
commission rather than a predecessor; the sheet asks: succession, duplicate
record (`sameEntityAs` FR 409), or leave its one mention unreached.

## 4. Reverse lookups

One per source-value kind: regulations.gov code (exists today), Federal
Register agency id/slug, eCFR slug, Federal Hierarchy organization code. All
are derived readings of adjudicated rows, following
`reverse_agency_projection()` exactly: a value resolves only where exactly one
adjudicated row selects the organization; where several select it, all are
returned as ambiguous and nothing resolves; unresolved values contribute
nothing. No inverse is ever minted.

**Reverse lookups follow identity bridges.** A bridge merges the two bridged
records, so every code selecting either selects the merged organization and
the exactly-one rule applies to the union. That can turn a resolved value
ambiguous: `same:fr151:ecfr:export-import-bank` would leave FR 151 (1,118
mentions) selected by both EIB and USEIB, where today USEIB alone reaches it;
under spicy-regs' rule 1,116 rows and 12 docket-less proceedings would lose
their code (§9). The sheet asks the owner without presupposing an answer: not
the same organization, the same but the cost refused, or accept.
`same:fr186:ecfr:federal-register-office` joins an organization that is
already ambiguous (FR, OFR), so it gains no code.

**Successors are looked up forward, never asserted.** "Current successors of
X" walks forward through adjudicated events and returns a set; a consumer that
needs one code applies the same exactly-one rule, so a split (INS, Customs,
ICC, and now USIA with the Broadcasting Board of Governors) yields no single
code by design. Whether a consumer applies that forward lookup to historical
documents — which re-routes them from the code they resolve to today — is the
consumer's decision (for spicy-regs, spicy-regs'); the sheet shows each
row's effect under spicy-regs' current rule so the owner sees the change.

## 5. Unresolved values are kept

Every source value that reaches no organization stays with a reason, as
REF-038's ten abstentions do, and every withdrawn candidate is recorded as a
non-emission with its closest alternative. Batch 1 proposes one withdrawal and
records one code with no FR bridge: `CISA` stays resolved to its Federal
Hierarchy organization, but the held FR roster has no CISA record, so no FR
bridge can be proposed. Its reason, `noCounterpartInHeldFRRoster`, is a new
value outside REF-038's `AbstentionReason` vocabulary (CISA is not an
abstention). The IBWC row
(`same:fr255:ecfr:international-boundary-and-water-commission-united-states-and-mexico`)
is withdrawn — it rested on slug equality and the names differ in scope, so
its closest alternative is `partOf`, and FR 255's mentions stay unreached until
batch 2 keys it. The owner confirms or overrules both.

## 6. The owner-adjudication loop

An agent is never the reviewer. Exactly:

1. Tooling assembles a candidate table per batch, every row
   `candidate-pending-owner-adjudication` with no reviewer, evidence tier or
   decision field, and **generates** the adjudication sheet from it under the
   same `--check`. Candidate ids are content-derived
   (`same:<source>:<target>`, `succ:<original>:<result>`), so adding a row
   moves no other id; an event's id runs over its sorted original ids
   (`event:fr232`, and for a merger such as the later batch's PPRC and ProPAC
   into MedPAC, `event:fr407+fr440`). The candidate JSON carries the map from
   the previous round's positional ids. The sheet cites `candidates_digest`,
   which covers only roster-derived content, as the set's digest. Each
   decidable item (identity row, event, non-emission, no-bridge code) also
   carries its own `content_digest` over what the owner decides on — the
   question and options, both sides' sealed names and ids, the relation or
   basis, dates and records — with replay counts and effects left out, so a
   refresh stales nothing. Each row's effect under spicy-regs' rule is read
   from the measurement in §9 (`--rule-effects`), and the tool refuses a
   measurement taken against another candidate set, replay, or spicy-regs
   commit.
2. The owner adjudicates the batch through the question tool or by editing
   `plans/agency-registry-batch-1-decisions.json` — never the sheet. Each
   decision is keyed by a candidate or event id and records the answer the
   sheet offers, the date, the channel, and the `content_digest` of that item
   as decided (the sheet's Decision keys table lists them). The tool only
   reads that file and re-renders the sheet's decision cells from it, so a
   `--write` after a replay refresh keeps every decision. A decision stales
   only when its own item's digest changes — an edit to another row leaves
   it current; an event's digest covers its rows, so a change to any of them
   stales the event. A stale decision is shown and listed until the owner
   re-confirms it, never dropped. An unknown id is refused (a removed or
   re-keyed row is reconciled by hand), and so is a row id inside an event: a
   succession event is one decision. The tool's `--check-committed`, run by the fast-tier test, is
   the check CI can run without the replay or the rule effects: the committed
   candidates still follow from the rosters, the rule effects carry the pinned
   spicy-regs side, the decisions file matches its schema and binding, and the
   table and sheet are exactly what the committed JSON and decisions render.
   It re-derives no replay count or rule effect, so it cannot see a hand-edited
   count whose report digest, table and sheet were re-rendered to match; only
   `--check`, with the replay and the rule-effects file, re-derives them.
3. Only adjudicated rows become assertions, carrying the owner's reviewer IRI
   `urn:ref:reviewer:refspec-owner` and the decision date. The release step
   refuses a batch while any of its decisions is stale.
4. Rejected and abstained candidates are recorded as non-emissions, as
   REF-038's `candidateDecisions` account for all 331 values.
5. Batches stay small enough to adjudicate honestly: batch 1 is 15 identity
   rows, 9 events (14 result rows), one proposed non-emission and one code
   with no FR bridge.

## 7. Batch plan

- **Batch 1 (this note):** the 18 non-FR-mapped codes — 15 FR↔eCFR/FH
  identity candidates, the IBWC row withdrawn, `CISA` with no FR bridge — plus the defunct
  agencies as events: five renames (EAB→BIS, IIO→ISO, PWBA→EBSA, HCFA→CMS,
  Postal Rate→Postal Regulatory Commission) and four splits (INS three ways,
  Customs two, ICC two, USIA to State and the Broadcasting Board of Governors,
  since FARRA sec. 1311 carves broadcasting out of the abolition).
- **Batch 2: register-only agencies.** FR ids with no path after batch 1 that
  are not defunct-with-successor: 110 ids, 3,792 mentions, led by the National
  Endowment for the Arts (476 mentions), Interior's Hearings and Appeals Office
  (307), the Bureau of the Fiscal Service (306), and IMLS (297). FR 255 (IBWC)
  joins it with the withdrawal. Rows keyed from the FR side; defunct agencies
  with no successor (expired commissions) stay here.
- **Later succession batch:** defunct register-only agencies with successors,
  moved out of batch 2 — 21 ids, 800 mentions, among them the Food and
  Consumer Service (→ Food and Nutrition Service), BOEMRE (→ BOEM and BSEE, a
  split), ACTION, IDCA and the Arms Control and Disarmament Agency. The
  candidate JSON lists each with its proposed successors and what this pass
  read (the FR roster's own description, a statute in hand, or no record yet);
  that batch reads every record before proposing anything. Renames between
  records already reached (Broadcasting Board of Governors → U.S. Agency for
  Global Media) belong there too.
- **Later batches:** the Federal Hierarchy as a first-class dimension, then
  lobbying filing names, then court-docket names. Designed for here, not built.
- **Known limit (REF-072): events cannot stand alone.** A mapping release must
  carry at least one mapping, and the producer writes a release's change
  events with its first mapping batch, so the later succession batch, if it
  holds only events, cannot be a release of its own as built. It either rides
  in a release with bridges or needs that limit lifted first.

## 8. Release and artifact

Adjudicated rows land in a mapping release; the registry view is sealed in
its own digest-pinned Parquet directory, `output/agency-registry-view/`, on
the Atlas view's writer contract but apart from any distribution's
`parquet-view/`; spicy-regs consumes it by its manifest digest. Candidates never
enter a release, so the boundary between candidates and assertions stays
physical. Three existing constraints must be amended first (lines verified
against 739a3b3c):

- **The projection builder hard-codes REF-038.** `build_agency_projection()`
  refuses any release but `regulations-gov-agency-identity-2026-08-16`
  (`agency_projection.py:628-632`), requires every subject to be a
  regulations.gov resource (`agency_projection.py:671-674`), and
  `AgencyProjectionRow` refuses any relation but `atlas:sameEntityAs`
  (`agency_projection.py:332-333`). Bridges with FR subjects therefore cannot
  "fold into" the projection: the builder must be generalized to the batch
  releases, or a registry builder added beside it.
- **Entity-ring records refuse a date.** The ring-period `sh:xone` in
  `bindings/atlas/3.1/shapes/atlas.shacl.ttl:770-789` gives entity-ring
  mappings `rkaf:hasEffectivePeriod` `sh:maxCount 0` (line 787), and
  `_validated_relation_context` refuses context for the subject and entity
  rings (`src/refspec/registry/infrastructure/semantic_foundation.py:291-293`).
  The event's date lives on the event node, so the amendment admits a dated
  event node beside mapping assertions without relaxing the rule for
  `atlas:sameEntityAs`.
- **Outside the subject ring only `atlas:` predicates are admitted**
  (`bindings/atlas/3.1/tools/validate.py:4500-4504`; the SKOS carve-out
  chosen at 4493-4499 applies only where the ring is `atlas:subject`, line
  4502), so raw W3C ORG terms cannot appear on the wire.

**The owner's event design** (decided, and built after batch 1's adjudication;
see REF-072):

- **Atlas terms** subclassing W3C ORG: an event class under `org:ChangeEvent`
  and two properties under `org:originalOrganization` and
  `org:resultingOrganization`, in `bindings/atlas/3.1/ontology/atlas.ttl`;
  raw `org:` predicates stay refused. One `changeEventPolicies` entry -- a
  list of its own in `registry-resource-profiles.json`, beside
  `relationPolicies`, not an entry in it -- admits the event class, its two
  properties, the entity ring and the resource class the links reach (the
  `profileDigest` re-seals).
- **A SHACL shape:** exactly one date; at least one original and at least one
  result; the original not among its results; at least one dated public
  record; E4 human review by the owner (`urn:ref:reviewer:refspec-owner`).
- **Validator checks** in `validate.py` over the whole distribution: no cycle
  through events, no inverse pair (A→B and B→A), and no `atlas:sameEntityAs`
  between an event's original and any of its results -- read through
  identity's closure, so A→X and B→X refuse an event A→B too.
- **A negative fixture per check** (each shape clause and each validator
  check), a fixtures re-seal (`fixtures-receipt.json` `fixturesDigest`
  moves), and a decision record amending REF-038.
- **The consumer lookup** "current successors of X" is derived: it walks
  forward, returns a set, and is never asserted — the same standing as
  `reverse_agency_projection()`. `dcterms:isReplacedBy` stays release-level
  (`src/refspec/managed_release.py:149`) and is not reused for organizations.

**As built (REF-072).** The builder stays REF-038-only:
`build_agency_projection()` still refuses every release but REF-038's. The
owner's decisions land in their own release, `agency-registry-2026-09-26`
(13 bridges, 9 events, 4 recorded non-emissions), and the release has its own
view: `tools/build_agency_registry_view.py` seals
`output/agency-registry-view/` with `seal_agency_registry_view()` on the
Atlas view's writer contract, and `--check` rebuilds it against the pin.

| Member | Rows | sha256 |
| --- | ---: | --- |
| `view-manifest.json` (the pin) | | `c7dc9310f9c11cd346245d7cf882f9eaf69b70b25f59841ae6004dca4944866e` |
| `tables/agency-registry-bridges.parquet` | 13 | `2e33905b475c6a1adf27960ecf170a1b4c82df2baf20ac13df9307bb687dd898` |
| `tables/agency-registry-events.parquet` (one row per event and result) | 14 | `72f35636f9b5c93d708a364352122fb724e872f619a518c5e49ebb19518322b7` |
| `tables/agency-registry-non-emissions.parquet` | 4 | `da863e467f00f16a6b7a9ff1a3e1182fb8e7488f8b7d33f0d7f0c403a0663e24` |

Its logical-content digest is
`sha256:777c610051c9fdcbab8e9cdb7d382dce20c4565a484b241ed784247efefc46a4`. The
events table states each original's roster parent (`original_parents`, in the
order of `originals`, null for a top-level organization), as the bridges table
states `subject_parent`; that column is `schemaVersion` 1.1 and moved the
view from the dev21 release's 1.0 `77b357cc…` (events `09e35a12…`, logical
`9bc9eb03…`), which stays verifiable against the release; the bridges and
non-emissions tables did not move. The lookup is `current_agency_successors()`,
beside `reverse_agency_projection()`, over the view's event rows.

## 9. Measured gaps (re-measured 2026-09-26)

Two sources, each named with its output:

- **Tool-emitted** — `plans/agency-registry-batch-1-candidates.json`,
  `measured` and `inputs.replay`. A *row* is one replay row, a *document* one
  distinct document number, a *mention* one non-null `agencies_json` id.
- **spicy-regs' rule** — `agency_code_for_fr_agencies` at spicy-regs 680009a
  (`680009a5b761bc07c955d0c23fe56fd0799fa4ec`) over its vendored projection
  (`sha256:c9ec0fde…`), measured by spicy-regs'
  `scripts/measure_agency_registry_effects.py` (`sha256:0c31ebff…`, committed in
  680009a), run in spicy-regs' own environment
  (`uv run --frozen --project <spicy-regs>`). Its deterministic JSON output stays outside the repo like the replay and is
  embedded in the candidate JSON's `measured.rule_effects`. Each candidate is "adopted" by
  feeding the module the projection rows adoption would add (bridge: the FR id
  gains every code selecting its counterpart; event: the originals gain every
  code selecting a result); the module decides. RefSpec's tool never imports
  spicy-regs: it reads that output by digest and refuses one recording another
  spicy-regs commit, projection, `agencies.py` digest, or script digest than
  the ones cited here. The script never lives in RefSpec (REF-024).

Tool-emitted:

- 1,009,313 rows over 1,008,830 documents (474 numbers on more than one row);
  1,556,271 mentions over 448 FR agency ids.
- REF-038 reaches 299 FR ids covering 91.3% of mentions; 4 of them (369, 382,
  462, 536) never appear in the data, so 295 are reached and present — the
  first brief's 295 is that definition, not drift.
- The 15 identity candidates newly reach 14 FR ids (151 is reached already):
  coverage 99.2%; rows naming no reached agency fall 34,507 → 2,828 and
  documents 34,424 → 2,819 (the previous round's 2,716 / 2,707 included the
  withdrawn IBWC row).
- Event originals carry 7,109 mentions; batch 2 holds 110 ids / 3,792
  mentions and the later succession batch 21 ids / 800 mentions.

Under spicy-regs' rule, today: FR rows **948,647 resolved / 41,937 unresolved /
18,417 ambiguous / 312 joint**; of 182,824 docket-less proceedings (one FR
document each), **9,878** get no code (2,742 unresolved, 7,021 ambiguous, 115
joint) — not the previous round's 1,845, which counted only proceedings naming
no reached id. With all of batch 1 adopted: 978,934 resolved / 11,381
unresolved / 18,554 ambiguous / 444 joint (31,403 rows gain a code, 1,116
lose one, 3,636 move to a different one); docket-less without a code fall
to 8,252 (1,638 gain, 12 lose, and 964 more move to a different code). The
re-routes, all adopted: HHS→CMS 1,577 rows (472 proceedings), HHS→ACL 484
(15), HHS→HHSIG 8 (8), DOC→BIS 676 (167), DOC→EAB 528 (270), DHS→ICEB 323 (1),
TREAS→IIO 40 (31); PWBA's 757 rows move DOL→EBSA once the Labor bridge lands. Per candidate — rows and docket-less
proceedings that gain a code, `−` those that lose one, and in parentheses
those re-routed to a different code; "on top" is the marginal effect when
every other batch-1 candidate is adopted too:

| Candidate | FR rows alone | FR rows on top | Docket-less alone | Docket-less on top |
| --- | ---: | ---: | ---: | ---: |
| `same:fr118:ecfr:economic-analysis-bureau` | +0 (528) | +0 (528) | +0 (270) | +0 (270) |
| `same:fr136:ecfr:energy-department` | +19,240 | +19,240 | +667 | +667 |
| `same:fr151:ecfr:export-import-bank` | −1,116 | −1,116 | −12 | −12 |
| `same:fr186:ecfr:federal-register-office` | +0 | +0 | +0 | +0 |
| `same:fr244:fh:100006936` | +0 | +0 | +0 | +0 |
| `same:fr245:fh:100004455` | +0 (8) | +0 (8) | +0 (8) | +0 (8) |
| `same:fr271:ecfr:labor-department` | +7,648 | +6,891 | +266 | +187 |
| `same:fr277:ecfr:library-of-congress` | +435 | +46 | +219 | +21 |
| `same:fr296:fh:300000070` | +120 | +120 | +2 | +2 |
| `same:fr409:ecfr:postal-regulatory-commission` | +3,833 | +3,834 | +481 | +481 |
| `same:fr4:ecfr:african-development-foundation` | +111 | +111 | +3 | +3 |
| `same:fr503:fh:100012075` | +0 (323) | −1 (1,472) | +0 (1) | −1 (410) |
| `same:fr587:fh:100525875` | +0 (484) | +0 (484) | +0 (15) | +0 (15) |
| `same:fr603:ecfr:investment-security-office` | +0 (34) | +0 (40) | +0 (27) | +0 (31) |
| `same:fr88:ecfr:copyright-royalty-board` | +389 | +0 (389) | +198 | +0 (198) |
| `event:fr96` (Customs, split) | +1 (1,149) | +0 | +1 (409) | +0 |
| `event:fr150` (EAB→BIS) | +0 (676) | +0 (676) | +0 (167) | +0 (167) |
| `event:fr232` (INS, split) | +0 | +0 | +0 | +0 |
| `event:fr259` (IIO→ISO) | +0 | +0 (6) | +0 | +0 (4) |
| `event:fr404` (PWBA→EBSA) | +764 | +7 (757) | +79 | +0 (79) |
| `event:fr510` (USIA, split) | +0 | +0 | +0 | +0 |
| `event:fr543` (ICC, split) | +0 | +0 | +0 | +0 |
| `event:fr559` (HCFA→CMS) | +8 (1,577) | +8 (1,577) | +0 (472) | +0 (472) |
| `event:fr564` (Postal Rate→Regulatory) | +0 | +1 | +0 | +0 |

What the table says: nearly all the gain is three bridges (Energy, Labor,
the Postal Regulatory Commission); renames mostly re-route documents a department already resolved
through the parent rule (HCFA under HHS, EAB under Commerce) to the successor;
splits resolve nothing under an exactly-one rule, and Customs resolves alone
only because ICE has no code until `same:fr503:fh:100012075` lands; the IIO and
Postal Rate events need their successor's bridge first. Adding the
Broadcasting Board of Governors to USIA makes USIA a split: for a consumer
that needs exactly one code, the split codes none of USIA's 690 rows and 37
docket-less proceedings, where a State-only or a Board-only event would code
all of them (`split_variants` in the output; the sheet shows the same per
result for every split). The withdrawn IBWC row would have gained 112 rows and 2 proceedings.

The first brief's "31,648 of 41,937 unresolved FR rows": 41,937 is exactly
spicy-regs' unresolved-row count under this rule; the numerator matches no
definition exactly — of those rows, 31,671 name an FR id found by eCFR slug
equality, and 31,379 would gain a code if all eleven slug-found eCFR orgs
(including the withdrawn IBWC row) were bridged (`first_brief_31648_of_41937`
in the output).

## 10. Out of scope and risks

- **Out of scope now:** Federal-Hierarchy-wide joins, OPM joins, lobbying and
  court names; any new roster capture; changing the sealed identities or
  directions REF-038 already asserted; minting any organization; building the
  §8 amendments before the owner adjudicates batch 1.
- **Risks.** The FH pairings rest on reviewed name evidence, not a mechanical
  rule. `same:fr296:fh:300000070` (Udall) is held: REF-038 uses
  `obviousPublisherNameVariant` only for case, word-order or qualifier
  differences and its evidence has no field for a statute, so the default
  proposal is a vocabulary amendment (a statutory-rename basis carrying the
  public record), with `obviousPublisherNameVariant` as the alternative.
  `event:fr564` may be a duplicate record, not a succession.
  `event:fr259` offers the roster's 2008-11-21 against the CFR-heading date
  2008-12-22, the kind of date set aside for PWBA and HCFA. The later
  succession batch's list includes seven agencies whose successor this pass has
  not read a record for. Splits yield no single code in an exactly-one
  consumer, so their value lies in the forward lookup and the functions each
  row names, not in resolution counts. The replay moves; counts are pinned by
  the recorded digests, and the candidates digest excludes them.
