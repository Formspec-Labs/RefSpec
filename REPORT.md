# Language-tag bug-class report

## Result

The fix admits the full English BCP-47 family at source boundaries and emits
the Atlas 3.1 wire form as exact `@en`. It recovers 231 new GEMET search labels
and 86 LCSH alignment-endpoint labels. Every pre-existing label identifier is
unchanged.

The GEMET number needs one reconciliation. The complete publisher RDF contains
5,244 `en-US` preferred labels: 5,000 are byte-identical to an `en` preferred
label and 244 use a different spelling. The Atlas GEMET release includes
concepts, not GEMET groups. Within that scope:

- 5,212 `en-US` label rows are eligible;
- 4,981 collapse into an existing exact-`en` label;
- 12 of the differently spelled values already exist as exact-`en` alternate
  labels;
- 231 values therefore require new Atlas label nodes; and
- one of the publisher's 244 differences labels a `gemet:group`, so it remains
  outside the established concept-release scope.

Thus all 243 concept-scoped spelling variants flow after this change: 12 were
already present and 231 are newly emitted. The change does not expand GEMET
membership to the out-of-scope group.

## Survey

The survey covered every language decision under `src/refspec/registry/`, every
Atlas registry adapter, and the builder's selection and audit paths. Exact
`en` checks that validate already-normalized Atlas output remain exact by
design.

| Reader | Previous language test | What the old test lost | Result of this change |
| --- | --- | --- | --- |
| `v3_registry_vocabularies.py` | Local case-insensitive equality with `en` | Variant-tagged labels, notes, notations, and metadata for DOE, ELSST, EuroVoc, GEMET, and NASA | Imports the shared family predicate; GEMET also collapses twins and converts a distinct regional preferred label to alternate when an exact-`en` preferred label exists |
| `v3_registry_alignments.py` | Exact `en` for the LCSH preferred and variant labels | 86 `en-Latn` LCSH variants | Imports the predicate; all 86 become alternate `@en` labels |
| `registry_claim_input.py` | `claim.language == "en"` | Variant-tagged labels preserved by RDF claim export, including GEMET `en-US` | Imports the predicate, prefers exact `en`, collapses twins, and demotes distinct regional preferred labels to alternate |
| `v3_registry_nonemitters.py` | Membership in `{None, "en"}` | Variant-tagged AGROVOC or NALT labels | Uses one normalization helper for both bounded adapters; no affected English variant exists in the current fixtures |
| `v3_registry_codes.py` | Exact `en` preferred-label selection | A variant-only preferred label; an exact/variant twin could look like two preferred labels | Accepts the family and deduplicates by lexical value; current code bundles contain no English variants |
| `rdf_claim_export.py` | A private family predicate | Nothing in this bug class; this path already preserved `en-*` | Deletes the private copy and imports the shared predicate |
| `generate_atlas_v3_full.py` source normalization | Exact `en` for explicit tags and language-map keys | `en-*` tagged objects and language-map values | Uses the shared predicate, merges English-family map values under `en`, collapses twins, and demotes distinct regional preferred labels |
| Builder output checks, `v3_source_data.py`, compact packs, and explorer readers | Exact `en` | Nothing: these consume the canonical Atlas wire form | Remain exact and catch any variant tag that escapes normalization |

### Publisher measurements

The only English variants in the scoped real sources are GEMET `en-US` and
LCSH `en-Latn`. No scoped source contains `en-GB` or `en-CA`.

| Publisher source and adapter scope | Label rows checked | Exact `en` or established untagged-English rows | English-family variant rows | Affected output |
| --- | ---: | ---: | ---: | ---: |
| DOE OSTI thesaurus | 23,627 | 23,627 `en` | 0 | 0 |
| ELSST R6, all publisher languages | 88,928 | 6,235 `en` | 0 | 0 |
| EuroVoc 4.24, all publisher languages | 421,936 | 17,581 `en` | 0 | 0 |
| NASA thesaurus | 27,125 | 27,125 untagged under its explicit source policy | 0 | 0 |
| GEMET complete RDF, preferred-label comparison | 5,244 `en-US` rows | 5,000 have an identical `en` preferred twin | 5,244 `en-US`; 244 differ from the `en` preferred spelling | 243 concept-scoped values flow; 231 new label nodes |
| GEMET Atlas concept scope, all label roles | 201,013 | 5,647 exact `en` | 5,212 `en-US` | 4,981 twins collapse; 231 new label nodes |
| LCSH alignment endpoint subset | 7,608 | 1,966 preferred plus 5,556 alternate `en` labels | 86 `en-Latn` alternates | 86 new label nodes |
| Bounded AGROVOC and NALT fixtures | Fixture scope | Existing `en` or policy-approved untagged rows | 0 English variants | 0 |
| Supported registry code bundles | All adapter inputs | Source-controlled `en` labels | 0 | 0 |

The AGROVOC fixture contains a non-English regional tag (`pt-br`), which
remains non-English because its primary subtag is `pt`.

## Design decision

`is_english_language_tag()` is the single source-boundary predicate. It first
requires a valid BCP-47 tag, then matches the primary subtag: case-folded `en`
or a value beginning with `en-`. Sources with an explicit policy that treats
untagged text as English must opt into that behavior.

The wire form is exact lowercase `en`, not the publisher variant. The Atlas
N-Quads grammar can represent subtags, but the Atlas 3.1 label rule requires
every emitted label to use `@en`. Normalizing at the source boundary keeps the
wire valid and avoids two label identities for the same text.

The deduplication order is deterministic:

1. Process exact `en` before regional variants.
2. Normalize every accepted language tag to `en`.
3. If a regional row has the same lexical value as an exact-`en` row, retain
   the exact-`en` row only.
4. If a regional preferred value differs and the resource already has an
   exact-`en` preferred label, emit the regional value as alternate.
5. Collapse a repeated normalized value and role. Preserve the existing SKOS
   role-precedence receipt when the same value appears in different roles.

The generation report now records English-family duplicates separately. This
keeps `sourceLabelCountBeforeLanguageFilter` exact: retained labels plus
foreign-language drops plus English-family twins plus role conflicts.

## Measured artifacts

Only two bounded distributions were rebuilt.

| Release | Labels before | Labels after | Preferred | Alternate before -> after | Hidden | Resources | Relations |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `gemet-4.2.3` | 5,645 | 5,876 | 5,573 | 60 -> 291 | 12 | 5,573 | 14,764 |
| `lcsh-eurovoc-alignment-endpoints-2026-08-06` | 7,522 | 7,608 | 1,966 | 5,556 -> 5,642 | 0 | 1,966 | 933 |

GEMET's post-fix generation report records 5,212 variant rows, 4,981 collapsed
twins, 231 new synonyms, 190,154 foreign-language drops, and 2 existing role
conflicts. Its source-label accounting reconciles to 201,013 rows. LCSH drops
fall from 86 to zero.

### Identity and digest consequences

| Release | Existing IDs preserved | Removed or re-minted | New IDs | Source-pack content digest before | Source-pack content digest after |
| --- | ---: | ---: | ---: | --- | --- |
| GEMET | 5,645 | 0 | 231 | `sha256:99033523d582fdf5b75a63b205dcaad7059cff85fec564479c9c0ff213ba559c` | `sha256:b23d2f33fe26b0ebfa145ab9e385fa1b600bba4c513fe9373cfcbd6a50efc80c` |
| LCSH | 7,522 | 0 | 86 | `sha256:5f083a193547ee86e29ab857870e285752438c0cf5b694a57f352ad4d0c11e41` | `sha256:e1e790cc8f4782bea1df819d5607566711591026fe9827671cb0b86f73ff4b70` |

The canonical distribution payload digest changes, as expected: GEMET changes
from `sha256:3358fc793333fb45bf92bdf16e9ed36a5b82b8c156e3bb3f0664e862c44c57d3`
to `sha256:0c9da2359ea7761c962b1643de88fcef7bd3a8fdfc4336d9fd83a22f8b813392`;
LCSH changes from
`sha256:0d0f5398cbebc992ba4d2fb1adc53f1f1048810c04f0786e3aecf0077bb6f556`
to `sha256:5ff7cc9e035b1f7632afa1c42315311665ef5da5d969185596c2d544ddaeefe5`.
The bounded `distributionId` remains stable because it identifies the same
pinned input accounting, not the generated payload.

## Verification

The focused suite passed with 20 tests. It covers the shared predicate and one
variant-flow/twin-deduplication case for each changed adapter family, plus the
builder language-map path and RDF claim export. Ruff and `git diff --check`
also passed.

Both final bounded builds passed their compiled producer checks and the
independent Atlas 3.1 file-consumer validator:

| Build | Final quad count | Independent validator | Peak resident memory |
| --- | ---: | --- | ---: |
| GEMET | 483,054 | passed | 953,319,424 bytes (0.89 GiB) |
| LCSH endpoints | 96,822 | passed | 348,651,520 bytes (0.32 GiB) |

The memory figures come from `resource.getrusage(RUSAGE_CHILDREN).ru_maxrss`
around each cold bounded build. Both are far below the 6 GB limit. No full
distribution build ran.

### Read-only fidelity auditor

The final command used the worktree code and the main repository's source
artifacts read-only:

```text
PYTHONPATH=src /Users/mikewolfd/Work/spicy-regs/RefSpec/.venv/bin/python \
  tools/verify_atlas_source_fidelity.py \
  --distribution output/fidelity-langbugs-release-gemet/distribution \
  --source-root /Users/mikewolfd/Work/spicy-regs/RefSpec/output/registry-real-data-sources \
  --only gemet-4.2.3 \
  --output output/fidelity-langbugs-release-gemet/fidelity.json
```

`uv run --no-sync` could not read the sandboxed user UV cache, so the command
used the existing repository virtual environment without syncing or changing
it.

The auditor exited 1 both before and after, with 14 of 24 broad fidelity checks
passing. This is not a regression signal for the language fix: verifier version
11 compares every publisher language and several unrelated source claim
families against an English-only Atlas release. It does not yet model the
intentional `en-US` to `en` normalization or preferred-to-alternate role
change.

The scoped evidence in that receipt still shows the fix:

| Auditor field | Before | After |
| --- | ---: | ---: |
| Atlas alternate-label claims | 60 | 291 |
| Atlas labels compared | 5,647 | 5,878 |
| Overall checks | 14/24 | 14/24 |
| Label-fidelity status | differences found | differences found |

The alternate-label increase is exactly 231. The auditor reports 5,878 rather
than the validated wire count of 5,876 because it also reconstructs the two
existing role-conflict source claims. The independent Atlas validator confirms
the canonical wire count of 5,876.

## Main-tree merge needs

Merge this branch's shared language helper, adapters, builder, tests, and this
report. Do not take any change to `tools/verify_atlas_source_fidelity.py`; this
worktree made none. The concurrently edited main-tree auditor can later model
the explicit English-family normalization and role-demotion rule if a green
label-fidelity verdict is required.

After merge, rebuild only the releases needed for review. A full distribution
rebuild, publication, deployment, and auditor-policy change remain outside this
branch's delivery boundary.
