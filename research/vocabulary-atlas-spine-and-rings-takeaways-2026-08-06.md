# Atlas spine and rings — product takeaways

**Date:** 2026-08-06
**Last reviewed:** 2026-08-08
**Status:** Research synthesis, revised through three external review rounds. It
records measured evidence and proposals; it does not change the Atlas binding or
decision ledger.
**The spine question is open**: FAST asserts `schema:sameAs` to LCSH, LC
reciprocates as `closeMatch`, and neither overrides the other. USC extraction
produced 1,342,167 rows (1,172,307 unique). Several statistics have been withdrawn
— see §10.

⚠️ **Known limitation of this document, stated by its third reviewer and not yet
fixed:** it *"mixes publisher facts, model judgments, structural heuristics,
implementation readiness, and unresolved decisions as if they had equal
authority."* The ✅/⚠️/*(agent)* marks are a partial remedy. A claim-to-evidence
register — artifact, digest, denominator, sampling frame, and whether the result is
publisher fact, model opinion or Atlas decision — is the real fix and does not
exist yet.
**Companions:** [Native-relation results](vocabulary-atlas-native-relation-experiments-2026-08-06.md),
[experiment designs](vocabulary-atlas-native-relation-experiment-designs-2026-08-06.md),
and the follow-up [safe agentic graph-search plan](atlas-agentic-graph-search-next-steps-2026-08-07.md)

This is the product-facing synthesis. It records what we can build, what we should
stop building, and what is still unknown — with the measurement behind each claim
so nothing here has to be taken on trust.

**Provenance convention.** A 2026-08-06 external review found the document's
defining weakness was that it *"preserves conclusions and discards the evidence
that qualifies them."* To make that visible rather than invisible:

| Mark | Means |
| --- | --- |
| ✅ | re-derived from bytes on disk in this session |
| ⚠️ | disputed between sources, or resting on a single unreplicated measurement |
| *(agent)* | reported by a subagent and not independently re-derived |
| **superseded** | the claim was made, then refuted; both are kept |

Where a finding has a cost, a scope limit or a dissent attached, **that travels with
it.** A conclusion recorded without its caveat is treated here as an error, not a
simplification.

**Release boundary.** A publisher mapping can become a source-preserving release
artifact once Atlas pins the source bytes and version, records redistribution
terms and provenance, preserves predicate and direction, reproduces the
transformation, and passes the binding's validation gates. This validation makes
the artifact release-ready as a faithful record of the publisher's assertion; it
does not prove that Atlas should reinterpret the relation. Generated links,
entailed links, R4-eligible rows, and model judgments remain candidates until
their separate semantic and release gates pass.

---

## Where this landed — read this first

**No universal spine is established. The evidence supports a bounded comparison
of direct source concepts, publisher organization, external hubs, and sparse
reviewed junctions.**

### 1 · Node shape limits FAST and LCSH as universal navigation layers

✅ Measured across every subject-ring vocabulary on disk:

| Vocabulary | Labels | **Atomic** | Compound (`--`) |
| --- | ---: | ---: | ---: |
| **FAST Topical** | 400,000 | **25.1%** | **60.1%** |
| **LCSH** | 521,055 | **54.1%** | **45.9%** |
| EuroVoc (en) | 7,665 | 98.3% | 0.0% |
| ICPSR | 3,287 | 98.1% | 0.0% |
| TheSoz | 8,224 | 97.1% | 0.0% |
| ELSST R6 | 3,471 | 96.8% | 0.0% |
| GEMET | 196,542 | 95.2% | 0.0% |
| NASA STI | 22,622 | 94.0% | 0.0% |
| DOE OSTI | 23,627 | 100.0% | 0.0% |

```text
FAST      African American teenagers--Education
          Enthusiasm--Religious aspects--Christianity
LCSH      Oregon--Trail Creek Watershed (Jackson County)
EuroVoc   carcase · animal product
ICPSR     abandoned buildings · ability
```

**No compound headings appeared in the measured sample outside the two library
vocabularies**, and FAST had the larger compound share. A pre-coordinated heading
can be an authoritative source concept, but it is a poor atomic navigation node
when its internal facets exist only as punctuation. You cannot traverse from
`Oregon--Trail Creek Watershed` to `Oregon` unless the publisher asserts or a
separate qualified process derives that relation.

This is a **third axis** alongside coverage and composability. It limits both
sources as universal navigation layers. It does not override either publisher's
identity or mapping assertions.

### 2 · The junction set is tiny

✅ Union-find over the 582 admitted cross-vocabulary mappings:

| | |
| --- | ---: |
| Source terms involved | 962 (**12.0%** of the 7,985-concept corpus) |
| **Identity clusters** (merged on `exactMatch`/`closeMatch` only) | **297** over 647 terms |
| Cluster sizes | 245 pairs · 51 triples · 1 quad |
| Hierarchy pairs that must **not** merge | 194 → inter-cluster edges |
| Associative pairs | 35 → inter-cluster edges |
| Terms in no identity cluster | 315 → singletons |

⚠️ **A first pass reported 384.** That merged on *every* admitted relation,
collapsing 194 `narrowMatch`/`broadMatch` pairs into identity — asserting that a
narrower concept *is* its broader one. Identity clusters merge on equivalence only;
hierarchy becomes an edge **between** clusters.

Every cross-vocabulary relation ever admitted between FR, ELSST and ICPSR is
expressible as **297 identity clusters + 315 singletons + 229 inter-cluster edges**.
Vocabularies mostly do not need to meet; they need to meet at *junctions*, and
junctions are rare. EuroVoc at 7,536 is not small — it is
**20× the junction set for three vocabularies**.

### 3 · Therefore: test sparse junctions without replacing source concepts

A sparse **junction registry** is one experiment candidate, not an adopted
taxonomy. Source concepts remain first-class publisher resources. A junction may
represent shared Atlas identity only after independent semantic and product gates;
until then, published alignments and generated similarities remain evidence.

This shape avoids chained `closeMatch` and preserves the FAST/LCSH disagreement.
It does not make source terms mere lexicalizations of an Atlas concept. GEMET,
EuroVoc, NALT, FAST, LCSH, and TheSoz alignments can nominate junctions while
retaining their exact predicates, directions, releases, and publishers.

⚠️ **The honest catch, and it is severe: this is currently a string join.**
✅ Of the 353 equivalence pairs behind those clusters, **299 (84.7%) have
prefLabels that normalise to the identical string**. The other 54 are **alias
equality** — `CANNABIS`→`marijuana`, `NATIONAL SOCIALISM`→`nazism`,
`MOTHER TONGUE`→`native language` — matched against a synonym the publisher wrote
down. **Zero were found by anything other than character comparison.**

If junctions reduce to normalised string equality, a registry is not required; a
normalisation function and a join would do. Three things would earn the structure,
and only one concerns clustering: **stable identity across versions** (a minted IRI
survives a publisher rename; a string join silently rebreaks), **curated
correction** where the string misleads (`Foreign trade`/`sanctions`), and **the
rings where labels cannot work at all** — *EPA* / *Environmental Protection Agency*
/ *United States. Environmental Protection Agency* / CGAC `068` join by no
normalisation.

The measurement that decides whether this adds value beyond a fuzzy join is:
**how many
true cross-vocabulary equivalences have dissimilar labels?** The string-derived
population cannot answer by construction. `E-S4a` — exhaustive judging of CRS
Policy Areas × Federal Register, 22,560 pairs, no generator in the loop — is the
only design that can, and it was demoted this afternoon for not scaling. **That
demotion looks wrong.** This is where
dense retrieval and generate-then-verify stop being incremental arm-tuning and
become load-bearing — they are the only signals that can propose a cluster member
no string match would find.

**Next measurement:** determine what fraction of the 297 observed clusters is already
implied by a published alignment versus needing judgment. A join against GEMET,
EuroVoc, and NALT sizes the judging budget for this three-vocabulary sample. E-S4a
must then test dissimilar-label equivalences before the result can generalize.

---

## The one-liner

The subject graph is the most developed ring. The `legalIdentity` experiment now
has **1,342,167 USC occurrences** (1,172,307 unique keys), but relation semantics,
deduplication, and release admission remain open. The next step is comparison,
not selection of a universal spine.

---

## 1 · Where the product actually is

RefSpec is the knowledge graph powering four other components:

| Component | Role | Needs from RefSpec |
| --- | --- | --- |
| **SpicyRegs** | metadata source | stable concept and entity identifiers |
| **DocSpec** | document management, segmentation, ~~tagging~~ | a taggable concept set with reliable identity |
| **SpicySearch** | indexing and querying | traversable relations with a *known* precision at depth |
| **RuleSpec** | rule extraction, core ontology | entities and legal identifiers to hang rules on |

⚠️ **Roles above are as stated by the user, not as traced.** A code trace on
2026-08-08 (`.md` files excluded by instruction) found two of them overstated —
see [§ Ownership, traced](#ownership-traced). **DocSpec does no tagging**: grepping
`tag|classif|taxonom|ontolog|label` across `DocSpec/src/docspec/` returns only
`label=` error-message kwargs, and its one processor's docstring says it works
"without assigning document meaning". **RuleSpec extracts nothing**: it has no
HTML/XML/PDF parser, no network client, and exactly one non-JSON text file on
disk (`requirements.txt`).

**Current phase: knowledge-graph relations. Documents come after.** Everything
that reads document text or topic assignments is deferred.

### Relations by semantic ring

| Ring | Concepts | Relations | Exportable |
| --- | ---: | ---: | :---: |
| `subject` | 441k FAST + 7,985 measured corpus | **526,182** | yes |
| `entity` | 478 *(only `crs-legislative-entities`; the ring also holds `federal-hierarchy-orgs` and `sam-cage`)* | **3** | **no** |
| `value` | — | **1** | yes |
| `legalIdentity` | 3,732 | **0** | **no** |

*Provenance:* the per-ring relation split is an agent tabulation re-derived from the
build's per-source counts (subject 526,178 against a 526,182 total), not read off a
field. An earlier draft took `value = 1` from that decomposition while reporting
`entity = 0`; it cannot have one without the other. **These are against the 526,182
build; the current `generation-report.json` shows 553,540 native relations, so
re-derive before quoting.**

One named blocker remains: `relation_sssom.py:86` restricts export to
`{"subject", "value"}`, and a non-subject proof adapter is missing.

**A second blocker has dissolved since this was written.** `generate_atlas_v3_full.py`
used to raise on any `MappingAssertion`; that guard is **gone** from the working
tree, and the current build reports `"mode": "publisherSourcesAndPinnedMappings"`
with **2,003 mapping assertions**, 553,540 native relations and 588,409 resources.
The refactor was logged below purely as a lint nuisance; it is a capability change.

**The rings that carry "trace back to identifiers, entities and other objects"
remain sparse.** Both now have a candidate source:

| Empty ring | Source found today | Volume |
| --- | --- | ---: |
| `legalIdentity` | USC/USLM extraction, all 58 titles | **1,342,167 edges** |
| `entity` | **FAST Corporate Names** — 396,201 records, 100% carrying a `(DLC)` LC authority link | **~11,914 US federal bodies** |

`fst00534882` is *United States. Environmental Protection Agency*, with LCNAF
`n79079597`, a VIAF link and 14 cross-references. `fst00529490` is *United States.
Congress.* Against a ring holding 478 concepts and no edges, that is decisive —
and it is one facet download, not a research programme.

---

## 2 · The spine question

An early inventory counted 108 construction units, not 108 subject vocabularies.
If all 108 needed crosswalking, the upper bound would be **5,778 pairs**. Many
units are code lists, identifiers, document resources, or other non-subject
inputs, so a governed subject-vocabulary inventory must set the real denominator.

⚠️ **An earlier version of this section also got the judgment unit wrong.** 582 is the number
**admitted**, not judged. The archive holds **1,095 candidates, each judged by two
model families**. Extrapolated under the same quota: 5,778 × 365 = **2,108,970
candidate pairs**, ×2 = **4,217,940 individual judge verdicts**. ~1.12M is the
projected *admitted* count under that deliberately broad upper-bound scenario.
These figures illustrate scaling; they do not define an approved work plan.

A hub needs one spoke per governed source other than itself. The count follows the
inventory rather than the construction-unit total.

### The metric that decides it

Not concept overlap — **relation overlap weighted by composability**. A hub
sharing 70% of concepts via `closeMatch` is a retrieval aid; one sharing 30% via
qualified `exactMatch` is a stronger traversal candidate. `skos:closeMatch` is
**not transitive**; chaining two hops licenses nothing.

### Hub candidates, measured

| Hub | Concepts | Composability | Notes |
| --- | ---: | --- | --- |
| **EuroVoc** | 7,536 | **84.6% of concepts carry ≥1 external `exactMatch`**; **18 alignments, 24,713 mappings, 93.75% exact** | small but policy-native |
| **LCSH** | **513,210** | 1.56% exact *on its own outbound links*; but reached 1:1 from FAST | major authority source; 2.83M alignments in `externallinks` need qualification |
| ⚠️ **FAST** | 441,127 | 259,401 `sameAs` at 95.8% 1:1 — **but LC calls the same links `closeMatch`, 0 exact** | **contested**; see below |
| **Wikidata** | huge | EuroVoc→WD **100% exact**; FAST→WD **63.9% strictly 1:1**; ELSST via `P12107` | external-identifier candidate, **three independent signals** |

**Wikidata keeps arriving from unrelated directions.** EuroVoc publishes 5,650
links to it at 100% `exactMatch`. FAST carries 75,375 links over **61,198 distinct
concepts**, of which **39,087 (63.9% of linked concepts)** are strictly 1:1. And ELSST, which publishes
nothing at all, is nonetheless reachable inbound through Wikidata property
`P12107` (231 items, v4-pinned, ~6.7% coverage). Three vocabularies, three
mechanisms, none of them coordinated. That is what an identity-hub candidate
looks like from the outside, and it remains unscored.

### FAST uses two predicates for two different jobs

This is the finding an earlier scan missed, and it changes the architecture.

| Predicate | Links to LCSH | FAST side 1:1 | **Strictly 1:1 both ways** |
| --- | ---: | ---: | ---: |
| `skos:relatedMatch` | 356,356 | 4.5% | **994–995 (0.6%)** ⚠️ two counts differ by one |
| **`schema:sameAs`** | **259,401** | **100.0%** | **248,521 (95.8%)** |

They do different work. `relatedMatch` carries the **pre-coordination
decomposition** — one LCSH string like `United States--History--Civil
War--Photography` fuses topic, place, period and form, and FAST represents
separate facets, so 92% of FAST concepts map to exactly 2 LCSH headings.
`schema:sameAs` carries **OCLC's identity assertion**, matching MARC `$4 EQ`.

Targets verified: **259,397 of 259,401 point into `authorities/subjects` with `sh`
prefixes** — genuine subject headings, only 4 name authorities.

OCLC's **2020** predicate profile lists exactly these two external-linking
predicates and `exactMatch` appears nowhere in it. An earlier note asserting OCLC
"overstates its own data" was wrong and is withdrawn — but so is the absolute that
replaced it. **"No OCLC document ever claimed `exactMatch`" is too strong:** two
agents found otherwise — a 2012 OCLC dataset description (`swj296.pdf`, p. 5) shows
a FAST record display with a **"HAS EXACT MATCH"** row, and the **2011 release used
`skos:exactMatch`**. The defensible claim is about the 2020 profile, not about
every OCLC document ever published.

### ⚠️ The two publishers disagree, and this is unresolved

**The spine claim is contested and should not be acted on.** ✅ Verified against
LC's own `externallinks.nt`:

| Direction | Predicate | Count |
| --- | --- | ---: |
| FAST → LCSH *(OCLC)* | `schema:sameAs` | 259,401 |
| LCSH → FAST *(LC)* | `mads:hasCloseExternalAuthority` | **353,767** |
| LCSH → FAST *(LC)* | `mads:hasBroaderExternalAuthority` | 181,605 |
| LCSH → FAST *(LC)* | **anything meaning exact** | **0** |

LC reciprocates essentially the same links OCLC calls identity, and classifies
**all** of them as close — `hasCloseExternalAuthority` corresponds to
`skos:closeMatch` in LC's MADS/RDF documentation. **Neither publisher's assertion
overrides the other's.** This is a decision to make, not a fact to adopt.

**The inferential error that produced the earlier claim:** 1:1 cardinality is
*topology, not semantics*. A clean one-to-one join says the two vocabularies are
structurally alignable; it does not say the aligned concepts are the same. This is
the same class of mistake as inferring a mapping from a shared label — which this
document warns about two sections later.

**It also cannot ship "with no judgment."** `semantic_foundation.py` permits five
SKOS subject predicates, `schema:sameAs` is not among them, and unrecognised ring
relations **fail closed**. Admitting these links requires an explicit decision
about how to treat a predicate the two publishers disagree on.

**The two-tier design still holds; the size of the traversal tier is unknown.**
EuroVoc really is 7,536 concepts — that was never an artifact. What is now open is
whether *any* candidate offers both coverage and composability.

⚠️ **Three positions have been taken on this question in one day** — "FAST cannot
be the spine" (missed `sameAs`), "FAST is the spine" (missed LC's reciprocal), and
now contested. Do not take a fourth without the reciprocal bytes in hand.

*Evidence base:* the reversal rests on **two** on-disk sources — the bulk
N-Triples and OCLC's MARC authority records — not three. The FAST-validation agent
initially wrote that a per-record agent had independently confirmed it and then
retracted: *"that was wrong, and I should not have said it."*

---

## 3 · What source material is already on disk and unused

A scan of `output/registry-real-data-sources/` (845 MB) found more publisher
mapping material than the Atlas build currently uses:

| Source | Outbound mappings held | Status |
| --- | --- | --- |
| **GEMET** (`gemet.rdf`, 32 MB) | **2,903 `exactMatch`** — EuroVoc 1,683, AGROVOC 1,188, EIONET 31 — plus 5,522 `closeMatch` (mostly UBA/DBpedia). Per-predicate host split verified with a real RDF parser | **unused; a survey agent wrongly reported GEMET publishes none** |
| ⚠️ *(agent)* **EuroVoc** | core 60 MB RDF + **1 of 18** alignment files | **17 missing (~22,700)**. Totals are from one agent's live SPARQL census and could not be reproduced by a later reviewer — only the 18-alignment inventory is independently confirmed |
| **LCSH** (`lcsh-subjects-madsrdf-2026-08-06.jsonld.gz`, 134 MB) | **ZERO** — verified over all 521,055 records | `externallinks.nt.zip` is now on disk with **2,827,929 mapping triples**, but the Atlas build does not consume it |
| **FAST** | **259,401 `schema:sameAs`** + 468,479 `relatedMatch` + 155,173 `rdfs:seeAlso` | **on disk, unused** — marked `reviewWithheld` |
| ✅ **TheSoz** (`thesoz-1.0.0-zenodo-curl.ttl`, 19 MB) | **5,874 `exactMatch`** + 628 `relatedMatch` → DBpedia, STW | **recovered today** from the dead-end list |
| ✅ **ESIP COR** (`esip-cor-ontologies-zyte.json`) | 324 ontologies, all public; includes GCMD keywords and ENVO | **recovered today** |
| ✅ **Table III** (`fulldump@119-73.xml`, 126 MB) | act → section → USC classification → Statutes at Large page, 1789–2026 | **recovered today** |
| ✅ ELSST | **zero** mapping predicates | genuinely empty, exhaustively verified |
| ⚠️ OSTI, ICPSR, NASA STI | zero *(single probe each)* | unconfirmed — see §11 |

### The systematic gap — two distinct failures

**Separate and not consumed** (LCSH, EuroVoc): concepts and alignments are
different distributions. The LCSH alignment archive is now on disk; 17 EuroVoc
alignment distributions remain absent.

**Fetched and unused** (FAST, GEMET): the alignments are on disk and the Atlas
build does not read them — FAST's are marked `reviewWithheld`.

| File | Triples | Mapping triples |
| --- | ---: | ---: |
| `subjects.skosrdf.nt.gz` (101 MB) | 12,347,667 | **0** |
| `subjects.madsrdf.nt.gz` (230 MB) | 25,931,474 | **0** |
| **`externallinks.nt.zip` (239 MB)** | 13,986,877 | **2,827,929** |

⚠️ **`externallinks.nt` was separately shown to be *lossy*** — it is the only bulk
source of LC alignments, not a complete record of them. A related claim that it is
"the output of MARC 7XX conversion at scale" was **retracted by the agent that made
it**: LCSH authority records contain **no 7XX fields at all**, and LC's alignments
come from a separate process.

The LC download page labels `externallinks.nt.zip` as **150 KB**. It is 239 MB.
Two independent agents reasoned from that label to "nothing there", and one
explicitly challenged the other before testing it. **Never trust a stated byte
count over a HEAD request.**

`externallinks` also carries **LCNAF** — the Name Authority File, i.e. persons and
**corporate bodies**. That is agency identity, and the `entity` ring holds 478
concepts and zero relations.

**The 17 missing EuroVoc alignments are a bounded acquisition task** —
a few hundred KB each from one SPARQL endpoint. The **full enumerated inventory is
18 alignments, 24,713 mappings, 23,168 `exactMatch` (93.75%)** — we hold one
(LCSH, 2,003 mappings at 95.06%), so **~22,700 are missing**. The seven largest:

| Alignment | Mappings | exact % |
| --- | ---: | ---: |
| Wikidata | 5,650 | **100%** |
| Eclas | 4,002 | 90.5% |
| UNBIS | 2,790 | 85.3% |
| STW | 2,648 | 86.0% |
| GEMET | 2,036 | 94.3% |
| AGROVOC | 1,814 | 98.3% |
| UNESCO | 1,370 | **99.6%** |

The table above is not the whole inventory — it omits RAMEAU (316), GND (215),
Digital Europa Thesaurus (1,499), Country authority (246), EIGE (75) and five
near-empty targets totalling 53. An earlier "23 alignment sets / ~20,000 mappings"
figure came from an agent that enumerated only 10; **18 / 24,713 is the enumerated
count from live SPARQL** and is the one to use.

*Engineering trap:* the obvious `publications.europa.eu/mdr/resource/thesaurus/...`
paths are **soft-404s — HTTP 200 serving HTML, not RDF**. Use the Cellar SPARQL
endpoint or a pinned-bytes pipeline will silently poison itself.

---

## 4 · Candidate work, ranked by evidence

1. ✅ **USC statutory references — extracted and verified as experiment evidence.**
   **1,342,167 occurrences across all 58 published titles**, 25 seconds, stdlib
   only, for a ring holding **zero integrated relations**:

   | Edge type | Count |
   | --- | ---: |
   | `enactingPublicLaw` | **611,771** |
   | `statutesAtLarge` | 340,040 |
   | `uscCrossReference` | 330,508 |
   | `actName` | 59,848 |

   ⚠️ **1,342,167 is an occurrence count, not a graph.** ✅ Verified:
   **1,172,307 unique** `(title, sourceAnchor, href, edgeType)` keys · **105,742
   exact duplicate JSON rows** · **2,641 rows with `sourceAnchor: null`** (no usable
   source endpoint). The extractor's own docstring says *"a single total is a lie"*
   and warns that `/us/pl` and `/us/stat` frequently describe the same amendment
   event; its manifest states the output is **not usable for pooled reference or
   amendment counts**. A dedup policy is required before any integration.

   **`context` partitions the same 1,342,167 rows** — it is not a fifth type:
   `note` 871,613 · `sourceCredit` **299,642** · `toc` 64,026 · **`operative`
   106,886 (8.0%)**. The `sourceCredit` slice is amendment history with no extra
   fetch. An earlier draft wrote "Plus 299,642", implying 1,641,809; that was a
   double-count. The four types map almost
   one-to-one onto `LEGAL_CITES` / `LEGAL_AMENDS` / `LEGAL_AUTHORIZES` /
   `LEGAL_IMPLEMENTS`, defined at `semantic_foundation.py:93-96` and admitted into `RING_RELATIONS` at
   line 126, carrying no data. ⚠️ **But "map almost one-to-one" is wrong** — the
   extractor maps **URL prefixes to descriptive labels** and establishes neither
   the legal predicate nor the edge direction. `relation_sssom.py` states
   legal-identity edges need their own interchange profile. Predicate and direction
   are open decisions, not a rename.

   *Survey first, stated precisely:* **seven maintained USLM projects exist**, but
   there is **no pip-installable parser and no published US Code edge dataset** —
   every PyPI name (`uslm`, `uscode`, `pyuslm`) 404s. Only
   `TheAxiomFoundation/axiom-corpus` emits an edge list, and it reads `<ref href>`
   only, inheriting the same blind spot ours has. Nothing is *adoptable* (~1 GB
   repo, Postgres-schema-coupled, no published counts) — which is different from
   nothing existing. An earlier draft also said "every live library recognises
   citation strings in prose"; axiom-corpus explicitly does not.
2. **Define non-subject relation semantics and interchange.** The binding already
   separates semantic rings, but USC references still need deduplication,
   predicate and direction decisions, a release shape, and an independent proof
   path. This is not only an allowlist change.

**1b. ✅ OLRC Table III — downloaded, the one additive statutory dataset found.**
   Still published, current through **PL 119-73 (Jan 2026)**, covering
   **1789–2026**. **✅ Bulk XML confirmed and downloaded** —
   `fulldump@119-73.xml`, **126,260,704 bytes** (15 MB zipped), dated 2026-08-05,
   fetched by plain `curl`. Real structured XML:
   `<act congress date statutes-at-large-volume>` → `<record usckey>` →
   `<act-section>`, `<statutes-at-large-page>`, `<united-states-code-status>`,
   with a stable UUID per record. The earlier "HTML only, no machine-readable
   download" verdict was a **wrong-URL probe, not a block**. It answers the
   *inverse* of our `sourceCredit` edges at finer granularity: for every section
   **and subsection** of every public law, where was it classified and at which
   Statutes at Large page. Critically it also covers provisions **never classified
   to the Code** and classifications **later superseded** — neither of which
   appears in source credits at all. A different relation from a different
   publisher table, not a re-derivation of USLM hrefs. Volume unsized; acquisition
   cost looks low.
3. ⚠️ **Qualify what is already on disk.** GEMET's **2,871 `exactMatch`** to
   EuroVoc and AGROVOC are direct publisher evidence, but Atlas must still pin
   exact endpoint releases and validate the mapping artifact. FAST's **259,401
   `schema:sameAs`** are **contested** — LC classifies the
   same links as `closeMatch` — and `schema:sameAs` is not an admitted RefSpec
   predicate, so the system fails closed. That is a decision, not a load.
4. ⚠️ **Complete and qualify the alignment inputs.** LCSH
   `externallinks.nt.zip` is now on disk but unused. The **17 missing EuroVoc
   alignments** remain absent. FAST Corporate Names is candidate entity evidence,
   but the measured figures came from a **2021 Wayback dump** and cover only
   LCNAF corporate names used as subjects in WorldCat.
5. **Score Wikidata as another external hub.** It is a general knowledge graph,
not a subject vocabulary, and appears through three unrelated sources. Compare
it with direct mappings, EuroVoc, FAST, and LCSH; do not adopt it by default.
6. **Evaluate the 4,991 entailed hierarchy edges as non-authoritative derived
   relations** (ELSST 4,215 + ICPSR 776). They are deterministic consequences,
   not publisher assertions. Measure product value and path safety before any
   consumer enables them.
7. **Admission fixes — contested; read the objection before acting.** R4 recovers
   +39 with zero added controls, but the adversarial peer review said **do not ship
   it**, on three grounds this document previously omitted:

   **First, R1–R4 decide admission and assign no SKOS relation.** The replay
   harness contains no relation names at all, and R4's 39 rows sit on four verdict
   pairs the archive never resolved (22 `near_same`+narrower, 7
   `near_same`+broader, 5 `same`+narrower, 5 `same`+broader). **"+6.7% of the
   graph" describes a graph that cannot currently be emitted.**

   **Second, shipping R4 consumes 45% of the only adjudication benchmark** — 39
   of the 86 `disputed` rows, whose entire value is that they are unresolved.

   **Third, R2 weakly dominates R4 on every column** and needs no orthographic
   classifier. If a relaxation ships at all, the peer review's answer was R2.

   The edit-distance variant restriction is separable and stands on its own.
8. **Measure per-edge precision (E-S1b / E-V6), ~$2.** Ranked top-two by *both*
   the peer review and the product review and absent from every earlier version of
   this list. Their argument: **nothing else here can be costed until `p` exists**,
   because traversal error compounds as `1-(1-p)^n` and no depth decision is
   defensible without it. 92.8% of retrieved pairs at K100 are unexplained, and `p`
   has never been measured on the population production will actually use.
9. **Compare two bounded mapping slices** — ELSST→EuroVoc and Federal Register
   Thesaurus→one named hub. Preserve direct-source baselines so a hub must show
   value rather than merely reduce an illustrative pair count.

## Avoid

- **A global pairwise-crosswalk program.** First enumerate the governed subject
  vocabularies and use publisher alignments where they exist.
- **Declaring FAST, LCSH, EuroVoc, or Wikidata the universal spine.** Evaluate
  each as an external hub while preserving source concepts and disagreement.
- **Subject-layer refinement.** Closure-scored retrieval is **76.1–86.4%** (the
  85–100% figure is asserted-gold and E-S5 showed it over-states by 10–15 points);
  remaining yield is single rows.
- **Forcing the whole FR vocabulary onto a subject hub.** `Grant programs-*`,
  `Loan programs-*`, `Authority delegations`, `Reporting and recordkeeping
  requirements` are **regulatory action types, not topics**. No subject vocabulary
  models that facet. They belong in the `value` ring — independent evidence the
  four-ring split is right.
- **Treating label admission as semantic identity.** The 91.5% admission rate is
  machine-opinion evidence from a string-derived population, not an error rate or
  identity guarantee.

---

## 5 · Measurements worth keeping

### Label equality is strong evidence, weak typing

330 same-string candidates → **302 admitted (91.5%)**. When admitted:
`closeMatch` **63.9%**, `exactMatch` 35.1%, `narrowMatch` 1.0%.

⚠️ **This figure switches denominators and has no adjudicated numerator; treat it
as withdrawn.** 330 − 302 = **28**, not 20; the 20 silently pools failures from the
330 `normalizedLabelEquality` *and* 165 `alternateLabelEquality` candidates, which
is where 495 comes from. Worse, the two "genuine wrong pairs" are not ground truth:
on both `Government employees`/`TELEWORK` and `Public assistance
programs`/`caregivers` the independent reviewer said `target_is_narrower`, i.e. a
real relation. And `HOLIDAYS`/`holidays` drew `insufficient_evidence` **from the
independent reviewer**, so the other 18 cannot all be relabelled abstentions.

The benchmark README states its relation types are *"majority machine opinion"*,
not an answer key, and that its rates are properties of a fixed string generator.
**0.40% is not a measured error rate.** What remains defensible: label equality
admits at 91.5%, and the failures are dominated by abstention rather than
contradiction.

### The admission rule, reconstructed

**Control-class exclusion, then lattice** — reproduces 582/582 with zero
mismatches. 69 controls cleared the lattice on judge verdicts alone and were
excluded by class. Order-independent: the rule carries no cross-row state.

| Rule | Admitted | Δ | Controls added |
| --- | ---: | ---: | ---: |
| R0 production v2 | 582 | — | — |
| R1 granularity, label-equality only | 619 | +37 | +0 |
| R2 granularity, any class | 622 | +40 | +0 |
| R3 `related` absorbs direction | 667 | +85 | **+4** |
| **R4 = R1 + principled variants** | 621 | **+39** | **+0** |

R4 ⊂ R2, differing by one row. The choice is principle, not yield.

### `relatedMatch` is a sink, with one owner

Base rate 6.0%. `normalizedLabelEquality` **0.0%** [0.0–1.3%];
`editDistanceNearMiss` **43.3%** [27.4–60.8%], **7.2×**, Fisher **p = 7.6 × 10⁻¹⁰**.

Split by variant class: principled 13/16 admitted (**81.2%**) vs unprincipled
17/149 (**11.4%**), Fisher **p = 7.3 × 10⁻⁹**, non-overlapping intervals.
Per-variant rows (n=11, n=5) are too small to quote alone.

### Blind review of the 35 `relatedMatch` admissions

| Stratum | n | Neutral | Adversarial | Both |
| --- | ---: | ---: | ---: | ---: |
| `relatedMatch` admissions | 35 | 85.7% | 71.4% | **71.4%** |
| Other admissions | 36 | **100%** | **100%** | **100%** |

Fisher p = 0.025 / 0.0004. **8 of the 10 failures are unprincipled edit distance;
zero are principled variants.**

⚠️ **The comparator is confounded with crosswalk.** The builder selects
`others[:distractors_per_class]` off a sorted key, yielding **34 `elsst-icpsr`, 2
`fr-elsst`, 0 `fr-icpsr`**, while the `relatedMatch` census is spread 13/11/11
across all three. Relation type and crosswalk vary together. The result supports
"these selected rows differed"; it does not support a general claim about where
mapping noise lives. Both framings also used the same model family on the same
rows — sensitivity checks, not independent replications.

### Judging reliability

**Prompt framing moves ~10% of verdicts** on identical bytes, same model family:
89.5% agreement on existence, 86.3% on relation, 74.7% on basis. No earlier
single-pass figure was reported with that slack.

Control calibration — all three Opus reviewers sit **below both sealed judges**:

| Class | gemini | openai | prior reviewer | neutral | adversarial |
| --- | ---: | ---: | ---: | ---: | ---: |
| random negatives | 5.2% | 5.2% | 3.7% | **0%** | **0%** |
| sibling distractors | 55.6% | 57.0% | 48.1% | 25.0% | **8.3%** |

⚠️ **The Fisher test was the wrong design and its conclusion is withdrawn.** The
observations are **paired** — every reviewer and judge scored the same rows — and
Fisher's exact test assumes independence. Exact **McNemar** on the paired data:

| Comparison | Discordant pairs | p |
| --- | :---: | ---: |
| Random controls, reviewer vs either judge | 1 vs 3 | 0.625 |
| Siblings vs `google-gemini` | 5 vs 15 | **0.0414** |
| Siblings vs `openai` | 5 vs 17 | **0.0169** |

Unadjusted, the sibling results point **toward** a difference — the opposite
direction from the Fisher figures previously reported here. Holm or Bonferroni over
the four paired comparisons removes significance at 0.05, and **this document never
defined its comparison family** despite reporting roughly a dozen p-values over one
1,095-row archive.

**"No worse" is a noninferiority claim and was never tested as one.** Failure to
reject equality is not evidence of equivalence; that requires a declared margin.
What survives is the *mechanism* finding — the 100% baseline was a control-class
exclusion — which needs no statistics at all.

⚠️ **Denominator switch in the table above.** "Prior reviewer" is 135 controls per
class; neutral and adversarial are **12**. On those same 12 sibling rows, Gemini,
OpenAI and the neutral reviewer are all **3/12** — so "all three reviewers below
both judges" does not hold on the matched subset.

### Variant classifier, blind-audited

165 pairs, independent linguistic reading: **98.8% agreement, 16/16 precision on
the principled class, zero false promotions** [80.6–100%]. Two misses are
punctuation not morphology (`CYBERSECURITY`/`cyber security`,
`STILL-BIRTH`/`stillbirths`), both already `exactMatch` positives, so the fix
changes **zero** admissions.

### Graph structure

- Genuinely edgeless concepts: **ICPSR 79 (2.1%)**, FR 139 (19.7%) — *not* the
  15–48% earlier claimed, which were per-predicate orphan rates.
- Precision decays 61.4% at K1 → **7.2% at K100**; 92.8% of retrieved ELSST pairs
  at K100 are unexplained by gold, entailment or shared parent.
- ICPSR hierarchy alone: 242 components, largest 9%, 47.9% orphan. The union
  fixes it (7 components, 99.6%) — but 7,180 of 8,943 union rows are `related`.
- FAST's own density: **0.518** edges/concept (`broader`+`related`) against
  ELSST's **1.80** on the same basis. An earlier draft said 0.93 — that was
  3,221/3,471, both of them the superseded `grep -c` figures this document
  corrects elsewhere. A derived statistic had survived the correction of its own
  inputs.

---

## 6 · What the product review found

- **Tagging is measured, and bad**: micro F1 **0.085** (P 0.068, R 0.114) on a
  35-row pilot; `novel_tag_rate` 0.487, `empty_tag_rate` 0.303.
- **The thesis has a direct counter-example**: dense-only retrieval hits
  **nDCG@10 0.661** with no graph at all; a cross-encoder adds 0.001; **BM25 lost
  its ablation**. No measurement anywhere shows a tag improving a retrieval result.
- **Coverage**: only **962 of 7,985 concepts (12.0%)** are touched by any admitted
  mapping — and that is the *unshipped* set.
- **Scope**: the research covers three source vocabularies and 7,985 concepts,
  about 1.4% of the dated build's resources. FAST
  alone is 76% of the graph and has never been measured.
- **PFAS is in the shipped build** via FAST. The query
  `"EPA rules on PFAS since 2024"` fails for a different reason: it needs entity +
  subject + value + date, and only one of those rings carries any relation.
- **~10⁶ deterministic identifier edges already exist in the sibling workspace** —
  `rule_targets`, `authority_edges`, `fr_docket_links`, CFR references, agency
  crosswalks, with provenance columns and a citation parser at 1 FP in 4,777.

---

## 7 · Vocabulary-by-vocabulary status

| Vocabulary | Publishes mappings? | Action |
| --- | --- | --- |
| *(agent)* **EuroVoc** | **18 alignments, 24,713 mappings, 93.75% exact**; 84.6% concept coverage | **policy overlay** — fetch the 17 we lack |
| ✅ **GEMET** | **2,903 exact** to EuroVoc + AGROVOC | qualify for a source-preserving release; already on disk |
| **AGROVOC** | →LCSH 99.2%, →NALT 98.0%, →EuroVoc 95.8%, →GEMET 99.1% | acquire, pin, and qualify its publisher mappings before assigning a hub role |
| **NALT** | ↔LCSH **10,481 reciprocal exact** | acquire, pin, and qualify this strong US-federal candidate |
| **LCSH** | 803,437 mappings, **1.56% exact** on its own outbound; reached 1:1 from FAST under OCLC's predicate | preserve as an authority source; qualify `externallinks.nt.zip` now that it is on disk |
| ✅ **FAST** | **248,521 strictly 1:1 `sameAs`** (of 259,401) + 468,479 `relatedMatch` | preserve as a separate faceted source and evaluate as an external hub. ⚠️ Corporate Names figures are unreplicated: "396,201 records, 100% DLC-linked" came from a **2021 Wayback dump**; the current archive gives **405,827 labelled subjects, 395,911 LCNAF-linked (97.56%)**. Also an **LCNAF subset** (LCNAF has ~51,248 "United States." headings) |
| ✅ **TheSoz** | **5,874 `exactMatch`** over 8,224 concepts (71%) → DBpedia, STW; 628 `relatedMatch` | qualify for a source-preserving release — 19 MB, DOI 10.7802/2912, CC-BY-4.0. Was in the dead-end list |
| ✅ **ELSST** | **zero — exhaustively validated** (all 4 formats, the complete 28-object CESSDA bucket, and the Skosmos API returning `{"mappings":[]}` on 190 concepts) | preserve the verified absence; treat generated EuroVoc mappings or Wikidata `P12107` links as separately qualified candidates |
| ⚠️ **ICPSR** | zero *(single probe)* | generate — but re-probe first |
| ⚠️ **FR Thesaurus** | no mapping found *(single probe)* | generate (~900 judgments, 60.6% label-anchored) |
| CFR List of Subjects | same vocabulary as FR Thesaurus (1 CFR 18.20) | — |
| ⚠️ OSTI, NASA STI, USGS, EPA, MeSH, LCC, GCMD | zero *(single probe each; OSTI already refuted)* | re-probe before writing off — GCMD is reachable via ESIP COR |
| HASSET | **retired**, 301s to ELSST | drop from the candidate inventory |

---

## 8 · USC extraction — caveats a consumer must know

**The corpus is usable. Title 26 is the exception, not the warning.** An earlier
draft said "Title 26 is a markup outlier; do not generalise from it", which reads
as *assume the corpus is this bad*. Measured corpus-wide, operative
`uscCrossReference` edges split **65,599 same-title / 25,093 cross-title** — the
inverse of Title 26. Most titles mark up same-title operative references at
**65–88%**:

| Title | Same-title | Cross-title | Same-title share |
| --- | ---: | ---: | ---: |
| **t26** | **6** | 533 | **1.1%** |
| t42 | 17,929 | 3,904 | **82.1%** |
| t16 | 3,866 | 1,113 | 77.6% |
| t12 | 3,302 | 1,031 | 76.2% |
| t7 | 3,331 | 1,058 | 75.9% |

Title 26 alone is the anomaly: its 17,604 "cross-references" are **14,079 notes +
2,986 TOC + 539 operative**, of which **six** point at Title 26 itself, against
~16,400 unmarked prose mentions — **8.7% markup density**. Quoting 17,604 as
operative statutory links overstated it ~33×. Quoting Title 26 as representative
of the corpus was the larger error.

**A `<ref>`-only extractor looks correct on Title 26 and silently loses 3.1%.**
There are **42,065 `<a href>` elements across 33 titles** (8,343 in Title 49
alone). On Title 26 the gap is 8 edges — invisible. The validation table only
reproduces if *every* href-bearing element is counted.

**Section→section references are not stable across editions.** 4.50% dangle
corpus-wide; 1.07% in Title 26; **26.7% in Title 14** after its 2018
recodification. Dangling edges are retained and flagged `targetResolved: false`,
never dropped.

**Identifiers contain U+2013 EN DASH** (`/us/usc/t26/s1400Z–1`). ASCII-normalising
severs the join to `<section identifier>`.

**Skipped deliberately:** 10,725 href-less `<ref class="footnoteRef">` (internal
footnote pointers), 190 `#fragment` anchors. Title 53 is reserved and its URL
302s to an HTML error page **served with a success status** — the tool validates
the payload is a zip rather than trusting the response code.

**Independently corroborated.** `publicdocs/uscode` extracted the same `href` set
from the same publisher in 2016 with a different tool: **1,079,318 links**, same
four types, same rank order — `/us/pl` 515,952 · `/us/stat` 286,489 · `/us/usc`
223,658 · `/us/act` 53,219. Ours is a superset (1,342,167) a decade newer. Two
independent extractions agreeing on structure is the best validation available
short of OLRC publishing an edge list themselves.

**A free list of known-bad OLRC inputs**, from that project's generator: `usc16.xml`
at release point 113-46 and `usc31.xml` at 113-65 are corrupt, and some titles ship
missing a closing `</appendix>`. Worth carrying as regression fixtures if we ever
backfill early release points.

---

## 9 · Open questions

- **Does any hub preserve structure?** Project the 16,449 publisher-asserted
  relations into a candidate hub, measure what fraction it reproduces as its own
  edge. Never run for anything. Runnable for FAST today.
- **What fraction of true cross-vocabulary relations has dissimilar labels?**
  The string-derived archive cannot answer. E-S4a supplies the complete small-pair
  denominator needed to compare direct mappings, external hubs, and sparse
  junctions.
- ~~Is our LCSH reader pointed at a hub with no spokes?~~ **Answered: yes.**
  Zero alignments across all 521,055 records of the 134 MB file we hold.
- **Can the sibling workspace's identifier edges type into the four-ring model
  without semantic loss?** Unverified, and the whole ring-join recommendation
  rests on it. A day of work to check.

---

## 10 · Corrections made today

Recorded because several were repeated before being caught.

| Claimed | Actual |
| --- | --- |
| 85 recoverable mappings, +14.6% | **37–39, +6.4–6.7%** — 85 is what a reviewer keeps, not what a rule recovers |
| Reviewer "flunked control calibration" | 100% baseline was a class exclusion. Paired tests do not establish noninferiority; the comparative calibration claim is unresolved |
| R2 admits "a substring row and two coincidences" | R4 ⊂ R2, differ by **one** row; R2's edit-distance rows *are* R4's principled variants |
| `Statistics`/`STATISTICS` recovered | It is a **hard negative** — one judge returned `insufficient_evidence` |
| 234 real hard negatives | **243** non-control rejections = 157 hard negatives + 86 disputed. The original 234 was 243 − 9, silently counting 77 disputed rows as hard negatives; **the "~9 lost true positives" has no derivation anywhere** |
| 589 ICPSR concepts with no edge | **79 (2.1%)** — 510 carry equivalence edges |
| 15–48% of concepts have no edge at all | per-predicate orphan rates, not coverage |
| FAST misses are near-misses, 98.4% recoverable | fuzzy-matching artifact; real headroom **0.1–0.5 points** |
| FAST reaches LCSH "by derivation, not judgment" | published as `relatedMatch`, **0.6%** strictly 1:1 |
| ~8.5% or 0.40% label-matching error | **Withdrawn.** The population and denominators do not supply adjudicated error gold |
| `Foreign trade`/`sanctions` proves labels mislead | it is in `positives`, admitted `relatedMatch` — a **judging** error caught by 3 blind reviewers |
| Slice-scoping answers the `closeMatch` problem | **does not transfer** — their slice has a publisher uniqueness guarantee; ours is trivially unique by SKOS |
| "Aliases never drive identity" worth adopting | **24:1 bad trade** — forgoes 120 good mappings to avoid 5 bad |
| GEMET publishes no external alignments *(agent claim)* | **2,903 `exactMatch` on our own disk** |
| E-S5's ELSST figures unverifiable *(peer review)* | **stale evidence file**; regenerated, every figure reproduces exactly |
| ELSST `prefLabel` 3,471 / `broader` 3,221 / `related` 2,210 | **51,863 / 3,393 / 5,696** — `grep -c` counts *lines*, and ELSST puts many objects per line. The zeros survived only because zero lines and zero triples coincide |
| LCSH mappings "may ship separately" | **Confirmed.** Our 134 MB LCSH file has **zero** alignments across 521,055 records |
| **FAST asserts zero equivalence to LCSH** | **REFUTED.** **259,397 `schema:sameAs` links at 95.8% strictly 1:1.** I regexed for `skos:*Match` only, so `schema:sameAs` (311,890 triples) and `rdfs:seeAlso` (155,173) were invisible — after writing the method note warning against exactly this |
| "OCLC's documentation overstates its own data" | **Withdrawn.** OCLC's 2020 predicate profile lists `sameAs` and `relatedMatch`; earlier OCLC material used `exactMatch`, so the claim must remain release-specific |
| Title 26 has 17,604 section→section cross-references | **539 operative** — the rest are 14,079 notes + 2,986 TOC. Overstated ~33× |
| The composable core is small (EuroVoc 7,536) | Artifact of missing `sameAs`. **FAST has 259k concepts with 1:1 LCSH identity** |
| **"TheSoz recovered — 484 KB of real Turtle"** *(mine)* | **The decoy.** That file has **1 `skos:Concept`, 0 `broader`, 0 `altLabel`, 0 `exactMatch`** — the ConceptScheme node plus ~8,000 bare `topConceptOf` stubs. The real file is **19,333,985 B with 8,224 concepts**. I made the error the document warns about — content that parses cleanly and isn't what it claims — about an hour after writing that lesson |
| "Verified dead ends" | **5 of 5 checked were false.** Renamed to *unconfirmed negatives*; only ELSST is exhaustively verified |
| **"FAST is the composable spine"** | **Contested.** ✅ LC's own bytes classify the same 259,399 links as `hasCloseExternalAuthority` — **0 exact**. 1:1 cardinality is topology, not semantics. Third position taken on this question in one day |
| "1,342,167 deterministic edges ready to integrate" | ✅ **1,172,307 unique keys**, 105,742 exact duplicate rows, 2,641 null source anchors. The extractor's own docstring says *"a single total is a lie"* |
| Four USC types "map almost one-to-one" onto `LEGAL_*` | **No.** URL prefixes → descriptive labels; neither predicate nor direction established |
| "582 judged mappings → ~1.1M judgments" | **Wrong unit and ungoverned denominator.** Under the 108-unit upper bound: 1,095 candidates × 2 judges extrapolates to **4,217,940 verdicts**, ~1.12M admitted. The real subject-vocabulary scope is smaller and must be enumerated |
| Control calibration "not significant, Fisher p = 0.77/0.27/0.18" | **Wrong test.** Observations are paired; exact McNemar gives **0.0414 / 0.0169** on siblings, pointing *toward* a difference. "No worse" is an untested noninferiority claim |
| "Genuine wrong pairs: 2 of 495 = 0.40%" | **Withdrawn.** 330−302 = 28 not 20; 495 pools two classes; and both "wrong" pairs were called `target_is_narrower` by the independent reviewer |
| Blind `relatedMatch` comparator | **Confounded** — 34 `elsst-icpsr` / 2 `fr-elsst` / 0 `fr-icpsr` vs a 13/11/11 census |

---

## 11 · Source register

Every source discovered today, with the access route that actually works.

### Vocabulary distributions

| Source | Route | Note |
| --- | --- | --- |
| **LCSH mappings** | `id.loc.gov/download/externallinks.nt.zip` | **239 MB**, page says 150 KB. **2,827,929 mapping triples.** On disk but not consumed by the Atlas build; includes LCNAF |
| LCSH concepts | `id.loc.gov/download/authorities/subjects.madsrdf.jsonld.gz` (134 MB) · `subjects.skosrdf.nt.gz` (101 MB) | **Zero mapping predicates in either.** We hold the MADS one |
| **FAST Topical** | `researchworks.oclc.org/researchdata/fast/FASTTopical.nt.zip` | Cloudflare-blocks CLI (403); on disk. 259,401 `schema:sameAs` + 468,479 `relatedMatch` + 155,173 `rdfs:seeAlso` |
| **FAST Corporate Names** | same host, ~76 MB (page states 67) | Current archive: **405,827 labelled subjects, 395,911 LCNAF-linked (97.56%)**. The earlier 396,201 / 100% figure came from a 2021 Wayback dump; the federal-body estimate remains unreplicated |
| FAST changes / per-record | `fast.oclc.org/fastChanges/` · `id.worldcat.org/fast/{id}.rdf.xml` | MARC authority files; 4 on disk |
| **EuroVoc alignments** | `publications.europa.eu/webapi/rdf/sparql`, graph `eurovoc.europa.eu/alignment/eurovoc_alignment_<target>` | **18 confirmed sets.** The `mdr/resource/thesaurus/...` paths are **soft-404s** |
| EuroVoc core | `eurovoc-4.24-skos-core.zip` (60 MB RDF) | on disk |
| STW / ZBW | `zbw.eu/stw/version/latest/download/stw_<target>_mapping.ttl.zip` | bidirectional; dedupe |
| GND / DNB | `data.dnb.de/opendata/mapping-authorities-gnd-<X>_lds.ttl.gz` | asserts `broadMatch` **both directions** — trust only symmetric relations |
| AGROVOC | `agrovoc.fao.org/sparql` · `agrovoc.fao.org/latestAgrovoc/agrovoc_lod.nt.zip` · VoID at `aims.fao.org/aos/agrovoc/void.ttl` | secondary hub, 90–99% exact |
| NALT | `lod.nal.usda.gov/downloads/nalt-full_dwn.nt.zip` | ↔LCSH 10,481 reciprocal exact |
| GEMET | `gemet.rdf`, on disk | 2,903 exact — EuroVoc 1,683, AGROVOC 1,188 |
| ELSST | GCS bucket `cessda-elsst-datadump` (28 objects) · Skosmos `thesauri.cessda.eu` · **no SPARQL** | zero mappings, exhaustively |
| Wikidata | `P244` LCSH · `P214` VIAF · **`P12107` ELSST v4** (231 items) | `P244` formatter omits `names/`; `P214` VIAF formatter changed |

### Statutory and regulatory

| Source | Route | Status |
| --- | --- | --- |
| **USC USLM** | `uscode.house.gov`, `xml_uscAll@<rp>.zip` | **extracted — 1,342,167 edges, 58 titles** |
| **OLRC Table III** | bulk XML, through **PL 119-73**, covers **1789–2026** | **the one additive dataset found** — unsized |
| GPO PTAR | live GPO publication (USC↔CFR) | 2011 snapshot in `crosslaws`; fetch current instead |
| Historical USC | OLRC Annual Historical Archives · govinfo `USCODE` | 1994–2024, PCC + XHTML + PDF |
| eCFR agencies | `ecfr.gov/api/admin/v1/agencies.json` | carries `cfr_references[{title, chapter}]` — the only published agency↔CFR binding |

### Unconfirmed negatives — 5 of 5 checked have been false

⚠️ **This section is unreliable and should be treated as a list of leads, not
findings.** Five entries have been checked against source. **All five were wrong.**
The category error is that these were produced by **single-URL probes**, and a
single-URL probe cannot establish a publisher-wide negative. Three agents also
disclosed exhausted WebSearch budgets and worked by direct fetch only.

#### Checked and refuted — 5 of 5

| Recorded as | Actually | Evidence |
| --- | --- | --- |
| **GEMET** — publishes no external alignments | **2,903 `exactMatch`** — EuroVoc 1,683, AGROVOC 1,188 | ✅ on our own disk, RDF-parsed |
| **Table III** — HTML only, no bulk download | **126,260,704 B bulk XML**, 1789–2026 | ✅ downloaded |
| **TheSoz** — no bulk download | **19,333,985 B**, 8,224 concepts, **5,874 `exactMatch`** | ✅ downloaded, DOI 10.7802/2912 |
| **ESIP COR** — dead end | **324 ontologies**, all public | ✅ `esip-cor-ontologies-zyte.json` |
| **DOE OSTI** — publishes nothing | Unpublished descriptor thesaurus (`readOnly: true`) + undocumented endpoint `osti.gov/elink2api/authority/subjects` | *(agent)* found via the E-Link 2 OpenAPI spec |

**Why three of them failed, and it was never absence:** `lod.gesis.org` presents an
**internal certificate** — `subject=CN=svko-data.gesis.intra`,
`issuer=CN=Gesis-Enterprise-CA`, expired April 2026 — and 301s to
`data.gesis.org/cvbrowser/`. ESIP failed the same way. `www.gesis.org` and
`search.gesis.org` return 403 to curl and WebFetch and 520 to Zyte. **A TLS failure
is not a negative result.**

#### Checked by one probe only — treat as unverified

⚠️ ICPSR (no SKOS, no bulk download *found*) · Federal Register Thesaurus · CFR
List of Subjects (*is* the FR Thesaurus, per 1 CFR 18.20 — that part is
documentary, not a probe) · EPA · USGS · NASA GCMD *(but GCMD keywords are
reachable through ESIP COR — see above)* · NASA STI · MeSH RDF · LCC · NARA ·
Data.gov · HASSET (retired, 301s to ELSST).

#### Verified exhaustively — 1 of 15

✅ **ELSST.** All four distributions (ttl/rdf/jsonld/nt), the complete 28-object
CESSDA bucket (`IsTruncated=false`), and the Skosmos REST API returning
`{"mappings":[]}` across 190 concepts. Every IRI object in the graph resolves to
one of four hosts, three of them schema-only. This is what "verified" should mean.

**Repos with nothing we lack:** `statute-graph` (no edge list) · `divegeek/uscode`
(6 editions, all still published by OLRC) · `publicdocs/uscode` (1,079,318 links —
the same href set, staler, a subset of ours) · `sunlightlabs/crosslaws` (no data) ·
`unitedstates/uscode` (archived 2014, TOC only) · `usgpo/uslm` (schema only).

**Libraries that solve a different problem:** `eyecite`, `citeurl`, `lexnlp` all
recognise citation *strings in prose*. We have resolved identifiers in `href`
attributes; an NLP recogniser would replace a publisher's editorial decision with
a guess.

*(EuroVoc alignment-set counts of 23 appear in earlier agent reports; **18** is the figure confirmed against the official catalogue.)*

**Aggregators that don't help:** `coli-conc` (1,094,930 mappings, **2.8% exact**;
EuroVoc/FAST/ELSST/ICPSR all absent) · SSSOM mapping-commons (70 specs, all
biomedical) · VIAF (excludes topical subjects by policy) · LOV (wrong meta-level) ·
`bartoc-fast` (DNS dead).

---

## 12 · Method notes worth keeping

**`grep` on RDF is unreliable and failed here in both directions.** `grep -c`
counts lines, not triples — it produced three wrong ELSST figures. `grep -o | wc -l`
counts occurrences and happened to match a real parser exactly on GEMET, but only
because no mapping predicate appeared in a comment or namespace declaration. **Use
a real parser and emit a complete predicate histogram**, not a filtered lookup for
predicates you already thought of.

**Enumerate IRI objects, not predicate names.** The strongest test for "does this
vocabulary link out" is: what hosts do its IRI objects resolve to? ELSST's resolve
to four, three of them schema-only. That closes the question regardless of which
mapping vocabulary a publisher might have chosen — including the Alignment API
namespace, which contains the string `exactMatch` nowhere.

**Verify a distribution list, not a distribution.** ELSST was settled by
enumerating the entire public GCS bucket (`IsTruncated=false`, 28 objects) and the
Skosmos REST API, not by reading one file well.

### Traps that cost time today, each verified

**Never trust a stated byte count.** LC's download page labels
`externallinks.nt.zip` as **150 KB**; it is **239 MB** holding 2.83M mapping
triples. Two independent agents reasoned from the label to "nothing there". HEAD
the URL.

**HTTP 200 does not mean you got the thing you asked for — four instances now.** EU
`publications.europa.eu/mdr/resource/thesaurus/...` paths return **200 serving
HTML**, not RDF. USC Title 53 **302s to an error page with a success status** —
the extractor validates the payload is a zip rather than trusting the code. Both
silently poison a pinned-bytes pipeline. Two more found today, both status 200:
`cor.esipfed.org/ont/api/v0/ont?format=json` returns `[]` — **2 bytes** — while the
*bare* URL returns 96 KB of real JSON; and a Skosmos
`?uri=…&format=text/turtle` call returns **494,249 bytes of valid Turtle that is
not the vocabulary** (1 concept, 0 hierarchy). **Check the content, not the code.**

**Never validate on one sample of a corpus.** Title 26 has **8.7% markup density**;
Title 42 has 83%. A `<ref>`-only extractor loses 8 edges on Title 26 — invisible —
and 42,065 across the corpus. Title 14 dangles at 26.7% where the corpus averages
4.5%.

**Verify a distribution *list*, not a distribution.** ELSST was settled by
enumerating the whole GCS bucket (`IsTruncated=false`, 28 objects) plus the REST
API — not by reading one file well. LCSH proves the inverse case: reading one file
well gave exactly the wrong answer.

**Agent findings need checking against your own bytes.** A survey agent reported
GEMET publishes no external alignments; we hold 2,903 `exactMatch` from it on disk.
Another reported an "authority ontology already published"; it was 95 records
across 1.1% of files. Both self-corrected only when challenged.

**Identifiers are bytes, not text.** USC section numbers contain **U+2013 EN DASH**
(`/us/usc/t26/s1400Z–1`); ASCII-normalising severs the join. Wikidata `P244` stores
`names/n79008243`, not a bare LCCN.

### Zyte transport — real limits, and what they are not

**HTTP 520 is a *temporary* download error**, documented by Zyte as "usually a ban
that could not be avoided in a timely fashion", with recommended handling of retry
with exponential backoff (20–40 s initially). 521 is nominally permanent but bans
get misflagged, so treat it the same. 429 is rate limiting — retry 30–630 s, **not
charged**. Zyte documents **no size-related error code at all**; a 520 is not
evidence of a size ceiling.

**Our own size constraint is arithmetic.** The body arrives base64-encoded inside a
JSON envelope (+33%); `provider_max_bytes = max(1 MB, max_bytes × 2)` bounds the
read; a post-decode check raises if `len(body) > max_bytes`; and
`fetch_registry_source_via_zyte.py` defaults `--max-bytes` to **25,000,000**. The
binding rule is simply **`--max-bytes` ≥ true file size** — the 2× headroom covers
base64 automatically. A default-flag failure on a 76 MB file looks like a hard
block and is not.

**Two things the transport cannot currently do:** fetch from Zenodo — 5.8 MB raises
`ZyteTransportError: Zyte target response repeats Content-Type` at
`zyte_transport.py:81`, and 19 MB returns 520 — and reach `www.gesis.org` or
`search.gesis.org`, which 403 every transport and 520 Zyte. The TheSoz bytes were
taken with curl and the artifact is named **`-curl` not `-zyte`** so provenance
stays honest.

### Data-quality defects found in passing

- **ELSST R6** uses `dcat:CatalogRecord` — an RDF *class* — as a **predicate** on
  51,848 triples carrying HTML `<a href>` literals. That is 22% of the graph.
- ELSST's published `.rdf` declares `xmlns:terms="http://purl.org/dc/terms/ #"` —
  a literal space in a namespace URI. It **fails strict RDF/XML parsers**.
- **MARC 788** encodes an n-ary AND (one LCSH heading ↔ two MeSH headings used
  together). SKOS cannot express it; a converter that flattens it to `relatedMatch`
  manufactures false edges.
- **Wikidata `P244`**'s formatter URL has no `names/` segment, so stored values are
  `names/n79008243` — a naive LCCN join fails silently. `P214`'s VIAF formatter
  also changed.
- **USAspending SUBTIER** is 4-char alphanumeric (`12C2`); typing it as an integer
  corrupts it, and Forest Service appears twice under CGAC `012`.
- `ecfr.gov/api/admin/v1/agencies.json` carries `cfr_references[{title, chapter}]`
  — the only published agency↔CFR-structure binding.

---

## 13 · Validated, not assumed

- **Our ELSST test set is set-identical to source** — not merely count-equal.
  3,393 hierarchy + 2,848 associative, 6,241 rows, 3,427 endpoints, zero missing
  in either direction. `skos:narrower` is the exact inverse of `skos:broader` and
  `skos:related` is perfectly symmetric, so the folding is correct rather than
  double-counting. The builder is sound.
- **The v2 admission rule** reproduces 582/582 with zero mismatches.
- **The variant classifier**: 16/16 precision, zero false promotions.
- **E-S5's ELSST closure figures** reproduce exactly after regenerating the
  evidence file.

---

## 14 · Artifact state

- The native-relation, crosswalk, blind-review, and replay evidence named by the
  companion documents is tracked in Git.
- Large rank artifacts remain ignored under `output/` and are authenticated by
  the tracked promotion manifest.
- The USC reference-edge extraction remains local experiment evidence; it is not
  an admitted Atlas release.
- `wave1-evidence.json` and `pareto-closure.json` were regenerated. Every cited
  E-S5 figure reproduces exactly.
- Current code, binding, and the decision ledger supersede this research document
  for implementation authority.

---

## Outstanding

**Three USC repos assessed on merit (licence ignored):** `divegeek/uscode` —
nothing; its 6 distinct editions are a strict subset of what OLRC and govinfo still
publish in the same PCC format, with worse integrity (no checksums, and 9 snapshots
committed with 4–5 titles missing). `publicdocs/uscode` — no data we lack, but see
the corroboration and known-bad-input list above. `sunlightlabs/crosslaws` — ships
no data, but points at **Table III**, the one genuinely additive dataset found in
any of today's surveys.

**None of the three addresses the unmarked-prose gap** — Title 26's ~16,400
unlinked `section 501`-style mentions. All three either inherit the publisher's
markup or predate markup entirely.

---

<a id="ownership-traced"></a>

## Ownership, traced

Three blind agents traced SpicyRegs, RuleSpec, DocSpec, SpicySearch and RefSpec on
2026-08-08 under one instruction: **ignore every `.md` file, follow entry points,
imports, schemas and tests instead.** The ownership split proposed earlier in this
document rested on `docs/product-boundary-and-api-disposition.md` and an unapproved
plan — prose on both sides.

📁 **Full verbatim agent reports:
[`research/repo-traces-2026-08-08/`](repo-traces-2026-08-08/00-synthesis.md)** —
synthesis plus one file per trace. The section below is the condensed version.

What the code says:

| Piece | Claimed owner | Traced verdict |
| --- | --- | --- |
| USC identifier scheme, popular names, Table III | RefSpec | ❌ **document-shaped — stays in SpicyRegs** |
| 88,000 sections, marked-up `<ref href>` citations | SpicyRegs | ⚠️ **nothing reads `<ref>` at all** |
| ~16,400 unmarked prose citations | RuleSpec | ❌ **no repo attempts them; refusal is deliberate** |
| Traversal at query time | SpicySearch | ✅ **already implemented and live** — one hop, unmeasured on real data |
| DocSpec as infrastructure, not an owner | — | ✅ **confirmed, more strongly than claimed** |

**The USC output is document-shaped, not vocabulary-shaped.** `usc-act-sections.parquet`
holds 10,976 rows over 9,916 distinct `(table3_key, act_section)` pairs — 471 repeat,
up to 26×, and two rows are byte-identical across all seven columns. A row's identity
is "the *n*-th `<tr>` on page X.htm". 3,702 of 3,721 `usc_identifier` values in
`usc-source-credits.parquet` are distinct: one row per document location. There is
**no lifecycle anywhere in the path** — no deprecation, supersession, `replaced_by`,
`broader`, or preferred-label column — and versioning is per-directory
(`usc-act-index-2026-08-02`), not per-term. Coverage is **24 of the ~8,400 acts**
OLRC lists, because the act set comes from `acts_cited_by()` over whichever corpus
happened to cite them. Compare SpicyRegs' own genuinely vocabulary-shaped artifact,
`ontology/concepts.py:49-62`: `pref_label`, `definition`, `broader_id`, `status`,
`replaced_by`, plus lifecycle `EVENT_TYPES`. **Captured observations, not a
controlled vocabulary. It belongs where it already is.**

**Nobody consumes USC cross-references, in either direction.**
`spicy_regs/sources/uscode_uslm.py:205-207` parses only `<section>` identifiers and
`<sourceCredit>` elements — it never opens a `<ref>` element and never reads section
body prose. So the 539 marked-up operative cross-references are unconsumed and the
~16,400 unmarked mentions are unattempted. **Both figures appear in no code in any
of the four repos** — they are measurements made in this research programme, not
implemented behaviour.

**The unmarked-prose gap is a documented refusal, not an oversight.**
`spicy_regs/ontology/citations.py:724` `find_act_relative_citations()` resolves only
the act-relative subclass: it finds a `sec. 111` token, then requires a *known* OLRC
popular name adjacent. Its docstring — "**The index is the grammar** […] inferring
which acts those abbreviate is precisely the guess the identity fence exists to
stop." The shape-based alternative was measured and rejected: matching "capitalized
words ending in Act" hit `U.S.C.` 108 times across 4,777 sealed authority strings.
`spicysearch/src/spicysearch/identifiers.py:186-190` states the same rule for the
other spelling — a bare "section 553" with no "of title" tail "**stays undetected
rather than guessed**". Assigning this to RuleSpec would overturn a decision two
repos took deliberately and wrote down in code.

**RuleSpec's evidence vocabulary is fully specified and entirely inert.**
`crates/rkaf-core/src/generated/source_fragment.rs:113-132` defines
`TextPositionSelector` with `oa:start`/`oa:end`/`rkaf:coordinateSystem`; `:86-105`
defines `TextQuoteSelector`; `extraction_activity.rs:31-77` records
`rkaf:extractionMethod`, `rkaf:extractorVersion`, `rkaf:inputDigest`. **No code
produces or dereferences any of it.** Every reference outside `src/generated/` is
schema-shape validation. It is a provenance receipt for an extractor that lives in
another repo — `spicy_regs/docpipeline/rkaf_projection.py`, which emits
`rkaf:ConceptAssignment` bound by `rkaf:bindsSourceFragment` and verifies every
offset by re-slicing stored text and SHA-256-comparing the region.

**Three incompatible evidence-coordinate vocabularies — differing on the *unit*.**

| Repo | Shape | Value | Unit |
| --- | --- | --- | --- |
| RuleSpec `source_fragment.rs:50-69` | closed Rust enum | `rkaf:utf8-byte`, `rkaf:unicode-codepoint` | either |
| DocSpec `domain/content.py:384-390` | free-form `str` | `utf8-byte-range` | UTF-8 bytes |
| SpicyRegs `docpipeline/source.py:132-133` | 2 fields, validated `:423-426` | `unicode-codepoints` + `half-open` | codepoints |

DocSpec has already emitted **8,232,356 records** carrying a `coordinateSystem`
string absent from RuleSpec's closed enum — RuleSpec's validator would reject every
one. And because DocSpec counts bytes where SpicyRegs counts codepoints, **the same
span in non-ASCII text yields different integers.** Only `rkaf_projection.py:202`
speaks RuleSpec's vocabulary correctly. This is the concrete cost of the identifier
divergence, and it is already in the data.

**RefSpec's own consumer contract is stale with its drift gate switched off.**
RuleSpec pins RefSpec's Atlas conformance corpus at **7 of 21 cases** — missing all
hierarchy and relation-adjudication cases plus 4 amendments — and hard-codes format
`1.0` at all five call sites (`refspec_atlas.py:28-29`,
`vendor_refspec_atlas_conformance.py:27`, `test_refspec_atlas_cross_repository.py:33,49`)
while RefSpec ships 2.0 and 3.0. The test that would catch it is
`skipUnless(REFSPEC_CHECKOUT)`, and `REFSPEC_CHECKOUT` is set **nowhere** — not in
the Makefile, not in CI. It silently skips every run. **Publishing ring 3 or 4 today
would not reach the one repo that consumes rings at all.**

### Corrections to earlier claims in this document

- **`tools/test_refspec_atlas.py` is RuleSpec's, not DocSpec's.** DocSpec never reads
  Atlas: a case-insensitive grep for `refspec|atlas` across its live `src/` and
  `tools/` returns **zero files**. Every hit is inside quarantined `archive/`.
  RuleSpec's file is a hermetic tempdir unit test, but the reader it exercises
  (`tools/refspec_atlas.py`) is production, imported by three release tools.
- **`rulespec`/`RuleSpec` and `DocSpec`/`docspec` are one repo each** — inodes
  `257555276` and `280359625` on a case-insensitive filesystem. `Formspec-Labs/rulespec`
  and `Formspec-Labs/DocSpec`. Note SpicyRegs is a **different org**
  (`civictechdc/spicy-regs`) from RefSpec (`Formspec-Labs/RefSpec`).
- **DocSpec is not isolated.** `tools/fr_mirrulations_qualification.py:55-58` hard-codes
  `Path("/Users/mikewolfd/Work/spicy-regs")` and shells into it, calling the *private*
  `_draw_documents`. Its `src/` is genuinely clean (`dependencies = []`, no
  cross-repo reference); the coupling lives entirely in `tools/` and `conformance/`.
- **Both repos execute** — RuleSpec 157 Rust tests pass, DocSpec 264 pytest pass
  against a sealed gate receipt. Neither is scaffolding. DocSpec's "353 source files"
  is 67 live `src` + 34 tests + 4 tools + **248 quarantined archive**, with the
  quarantine enforced by `tests/test_package_boundary.py:110,134,217`.

### Receipts that no longer match their inputs

Three of six identifier-edge figures previously quoted here were read out of
receipts whose inputs had since been rebuilt:

| Figure | Quoted | Actual |
| --- | ---: | ---: |
| `authority_edges` | 10,618 | **11,793** (13-column artifact vs 16-column current schema) |
| `fr_docket_links` | 715,080 | **893,766** (file rebuilt *after* two receipts pinned its digest) |
| citation parser false positives | 1 in 4,777 | **1 in 620** (only disagreement cells adjudicated) |

Verified unchanged: `rule_targets` 39,516; CFR references across 205,255 documents
(*Federal Register* documents, not the 1.99M `documents.parquet`); 34,612
CFR-part↔agency rows (only 9,284 rank-1, and its quarantine of 35,662 is larger
than its output). The citation figure additionally came from `gemini-3.6-flash` at
k=1 whose own receipt records `"determinism": "NOT deterministic"` — quoting it
under a *deterministic* edge budget is a category error.

**The pattern is the finding.** Every figure that survived was recomputable from a
file whose digest still matched. Every figure that failed was read from a receipt
whose input had been rebuilt underneath it. This is the same failure mode as the
[eleven Atlas acceptance gates](#) that read only the built artifact: **a receipt
proves what was computed, never that its inputs still exist in that form.**

### The consumer seam, traced

Both consuming repos are **two majors behind**. SpicySearch reads Atlas **1.0**
(`vocabulary_atlas.py:25`, `ATLAS_FORMAT = "refspec-vocabulary-atlas-nquads-1.0"`);
every `atlas-manifest.json` on its disk declares `schemaVersion: 1.0`, and there are
zero non-`.md` references to `atlas-2.0` or `atlas-3.0` anywhere in the repo. An
Atlas 2.0 reader exists (`vocabulary_atlas_v2.py:24`) and the whole snapshot
subsystem imports it — but it requires `atlas-scope.json`, **which exists nowhere in
SpicySearch**, so `VocabularyAtlasV2.open()` has never run against real data. RefSpec
never published a 2.0 example: `bindings/atlas/2.0/` holds schemas and a README.

**Nothing reads `output/atlas-3.0-full-2026-08-06/`.** It exists, at 2.6 GB, written
by `tools/generate_atlas_v3_full.py:113`. Neither SpicySearch reader would accept it.

Everything crossing the boundary is **vendored as byte-copies and digest-pinned,
never read live** — the atlas (twice) and `portfolio/resource-catalog-v0.json`. The
RefSpec checkout is consulted only when `REFSPEC_CHECKOUT` is exported. **That is the
same unset variable that disables RuleSpec's drift gate** — one environment variable
gates every cross-repo freshness check in the workspace, and it is set nowhere.

**The catalog seam is already torn and failing silently.** RefSpec's catalog grew
**33 → 89 resources** (56 added, none removed). The drift test does not fail — it
*skips*, because `spicy-regs/policies/profile-resource-applicability-v0.json` still
pins the old digest and the test classifies that state as "UPSTREAM TORN"
(`test_policy_inputs_cross_repository.py:38-64`). Policy pins `sha256:c0bcce73…`;
RefSpec now states `sha256:a731fef9…`.

### `_SUPPORTED_RINGS` is not a blocker

Traced to consumers, the two-ring restriction at `relation_sssom.py:86` gates
**nothing that ships**:

- **Zero production callers.** The only importers are `refspec/atlas/__init__.py`
  (a re-export) and two test files. `generate_atlas_v3_full.py` never invokes it —
  it loads the module as a side effect of importing `compact_pack`.
- **It has never produced an artifact.** No `mappings.sssom.tsv` exists under any of
  49 `output/` directories. The nine `.sssom.tsv` files on disk came from external
  SEMRA/OAK spikes.
- **No consumer exists.** `grep -ri sssom` across all of SpicySearch: **zero hits.**
  Its reader wants `{atlas-manifest.json, atlas-scope.json, atlas.nq}`.

The sharpest detail: RefSpec's shipped `statements.parquet` (560,429 rows) holds
**481 `entity`-ring statements and zero `value`-ring statements**. *The allowlist
permits a ring with no data and forbids one with data.* Adding `entity` and
`legalIdentity` would break nothing downstream — the module below the gate is
ring-agnostic. The real risks are semantic, not structural: RefSpec-minted
predicates like `cites`/`amends` have no SSSOM meaning, and CURIE compaction would
degrade to opaque `ns1:`/`ns2:` prefixes. Meanwhile the actual crosswalk (2,003
EuroVoc→LCSH mappings) ships through an entirely separate pipeline. **Earlier drafts
of this document treated this constant as the thing standing between us and a
four-ring graph. It is a design assertion guarding an exporter nobody calls.**

SpicySearch already supports all four rings end-to-end
(`vocabulary_atlas_v2.py:26`, `search_snapshot_runtime.py:726-730` maps each ring to
a filter field) — exercised only by fabricated fixtures, because no four-ring data
has ever crossed the boundary.

### Traversal already exists, and has never been measured on real data

Three paths, one live:

1. **`expand_within_vocabulary` — live on every concept query.**
   `concept_resolution.py:114`, called at `engine.py:2060`. One hop over
   `skos:related`, non-recursive, 1,451 edges over 705 concepts, results admitted at
   a deliberately weaker precedence (`engine.py:2078-2093`).
   `test_within_vocabulary_expansion.py:102-119` proves a document reachable *only*
   via the related hop is returned. **No hop cap, no predicate allowlist, no fan-out
   cap** — boundedness comes only from the shape of the code.
2. **`ConceptExpander.expand` — a real BFS with depth, predicate allowlist,
   `maximum_hops`, `maximum_fan_out` (`concept_policy.py:361-416`) — structurally
   dead.** The only production constructor is `ConceptPolicy.without_expansion`
   (`cli.py:333`), hardcoding `expansion_policy_id="not_used"` and
   `admitted_predicates=()`; `concept_policy.py:169-170` raises on any snapshot whose
   policy differs. Called only from tests.
3. **Build-time cross-vocabulary expansion** (`snapshot.py:1754`) — moot: the
   vendored atlas has `searchOnlyMappings: 0`.

Transitive closure and multi-hop are absent, and multi-hop *document* traversal is
explicitly refused (`relation_scope="two_hop_any"` raises `invalid_relation_controls`).

**The caveat that governs everything downstream:** the concept-lane measurements ran
over a **synthesised** atlas whose edges mean "two concepts are co-assigned to one
document". The benchmark says so itself at `search_quality_benchmark.py:543-547` —
*"It is not, and cannot stand in for, a RefSpec-generated managed-vocabulary
atlas"* — and at `:112-116`, *"a measurement over these derived edges says nothing
about that vocabulary's own relatedness."* **Graph expansion has never been measured
against a real RefSpec thesaurus.** That is the single largest open question for
this programme, and it is answerable with data that already exists on both sides.

### Retrieval figures, re-derived

Every figure previously quoted here for SpicySearch was wrong, and they failed in one
direction — understating the machinery, overstating the measurement.

| Claim | Verdict | Actual |
| --- | --- | --- |
| 35 gold queries | ❌ | **78 queries / 114 scored variants / 867 qrels**, plus 657 holdout queries and 37 capability cases |
| dense-only nDCG@10 = 0.661 | ❌ | `0.661` appears in **zero files**. Dense-only = **0.5002** |
| cross-encoder adds +0.001 | ❌ | **No cross-encoder or neural reranker exists** |
| BM25 loses its ablation | ❌ **inverted** | BM25 is the **largest single win**: 0.5002 dense-only → 0.7644 with BM25 spine → **0.8592** fused. Removing it costs **−0.359** |
| tagging micro F1 = 0.085 | ❌ | **No F1 is implemented anywhere.** The only `0.085` on disk is `"assumed_cost_usd": 0.085608` — a dollar figure |
| `services/search/` has 0 files | ❌ | No `services/` in either repo. It existed on a git lineage that **is not an ancestor of HEAD** |

**The number that matters more than any of them:** the headline 0.7644 is the
`harness` arm, which hand-feeds structured identifiers and relation controls that no
typed question carries. The real product path is `front_door` — **nDCG@10 0.3589,
9 of 114 passing**. Less than half the headline.

Scope, from the data rather than the docs: the only real corpus is **722 Federal
Register documents**, indexed as **title + abstract only**
(`extraction_method_and_version = "title-abstract-concatenation:1"`, ~626
chars/document). **No document bodies exist in any indexed corpus.** And the only
real-corpus snapshot **no longer opens** — `open_published_snapshot(snapshots/holdout-exam-2026-08-01)`
raises `IntegrityError`, because three schema fields were added after it was built.
No test catches this, because no test reads `snapshots/`.

### Duplication across the seam

Four capabilities exist twice, invented independently on both sides:

| Capability | SpicySearch | RefSpec |
| --- | --- | --- |
| Label normalisation | `concept_resolution.py:26-30` | `atlas/model.py:320-322`, `binding.py:341`, `vocabulary.py:478`, + `registry/federal_register_thesaurus_2025.py:288-291` — *normalising the same vocabulary* |
| Sparse retrieval | `lexical_postings.py` (BM25 + trigram, DuckDB) | `atlas/candidate_retrieval.py` — a full independent sparse engine with its own character-ngram features |
| Graph expansion | `expand_within_vocabulary` | `candidate_retrieval.graph_neighborhood_neighbors:335`, `queries.ConceptNeighborhood` |
| The ring set | `vocabulary_atlas_v2.py:26`, + hardcoded in SQL at `concept_index.py:323` | **duplicated 14 times inside RefSpec alone** — canonical at `registry/infrastructure/semantic_foundation.py:26,55`, re-declared rather than imported in 13 others |

Both sides independently invented character-gram matching. **Sixteen copies of the
ring set exist across the workspace**, which is the mechanical reason a ring change
is believed to be expensive.

### One build-identity defect worth fixing now

`generate_atlas_v3_full.py:116` hardcodes
`DISTRIBUTION_ID = "urn:ref:atlas:distribution:3.0-full-development:2026-08-06"`.
**Every on-disk build carries that identity, including the `…-2026-08-08` directory.**
Directory naming is human convention, unenforced by code. Packs are otherwise
rigorous — dual content/transport digests computed in one pass
(`:5662-5682`), atomic publication by candidate-dir rename.

*(Note: `tools/generate_atlas_v3_full.py` is under active refactor by another
session; recorded here, not edited.)*

**Open and load-bearing:**

| Question | Why it blocks |
| --- | --- |
| **Can FAST↔LCSH support a qualified identity view?** | Two publishers disagree; the answer governs this mapping family, not the entire architecture |
| **Per-edge precision `p`** | Both prior reviewers ranked it first; no traversal depth is defensible without it; ~$2 |
| **Structural fidelity** — does any hub reproduce the source's relations? | The companion design calls it *"the one that should decide this"*; never run |
| **USC dedup and predicate/direction policy** | 1,342,167 occurrences reduce to 1,172,307 unique keys; no legal-edge profile exists |
| **Can sibling-workspace edges type into four rings without loss?** | The whole ring-join recommendation rests on it |

**Resolved today:** USC/USLM extraction (1,342,167 occurrences) · external-hub landscape
(LCSH bulk dumps carry zero mappings) · ELSST validation (zero mappings,
exhaustively) · FAST validation (**259,397 `sameAs` — reversed the verdict**) ·
social-science and US-federal crosswalk surveys · PolicyEngine review.
