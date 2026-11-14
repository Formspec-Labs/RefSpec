# Original-source visual review: Congress.gov legislative glossary

The selected official glossary was read as original HTML and as rendered pixels
before implementing the reader. It supports a page-local reference with literal
terms and definitions. Its body does not establish CRS authorship, stable
concept identifiers, or a publisher edition date.

Original: `https://www.congress.gov/help/legislative-glossary`, observed
`2026-11-14T18:34:36.547332Z`, SHA-256
`501fab7f243c13cd402a5fa7c30a5e8e53f9f524b019cdf47c40774fa32d631e`,
418,089 bytes. The exact source remains at
`/Users/mikewolfd/Work/corpora/spicyregs/raw/objects/sha256/50/501fab7f243c13cd402a5fa7c30a5e8e53f9f524b019cdf47c40774fa32d631e`.

The bounded local inventory checked the selected catalog's CRS metadata and
relevant retained RefSpec capture manifests. The existing official pages held
navigation links to the glossary, not its body. A historical portfolio row
mistakenly called this URL Legislative Subject Terms; the actual original
resolves the distinction. One bounded official HTTP-body capture through the
maintained Zyte transport supplied the missing original. The request admitted
at most 2 MiB, with a 30-second timeout, no retries, and no crawl. Exact bytes and
the acquisition receipt entered central raw custody through `CaptureEvidence`.

The acquisition record and source-evidence artifact are retained under
[/Users/mikewolfd/Work/corpora/supply-2026-09-02/receipts/crs-operations-20261114/glossary/acquisition.json](/Users/mikewolfd/Work/corpora/supply-2026-09-02/receipts/crs-operations-20261114/glossary/acquisition.json).
That record links the immutable source-evidence artifact and central receipt.

## Viewed specimens

The images render bounded, exact term/definition HTML slices with the original
introduction where applicable. A local wrapper adds typography and a source-pin
caption, blocks network assets with a Content Security Policy, and does not
execute publisher scripts. It preserves source content and links, while omitting
the publisher's navigation, search widgets, footer, and stylesheet. These are
source-review images, not a claim about the live site's appearance.

| Viewed image | Original entry locators | Finding and disposition |
| --- | --- | --- |
| [A/B image](/Users/mikewolfd/Work/corpora/supply-2026-09-02/receipts/crs-operations-20261114/glossary/visual/a-b.png) | `#glossary_majoraction`, `#glossary_adjourn`, `#glossary_adjournmentsinedie`, `#glossary_amendment`, `#glossary_bill` | Terms pair with complete definitions; inline references and separate paragraphs carry meaning. Preserve both original HTML and readable paragraph text. `action codes` uses the actual `majoraction` anchor rather than a generated slug. |
| [C/L image](/Users/mikewolfd/Work/corpora/supply-2026-09-02/receipts/crs-operations-20261114/glossary/visual/c-l.png) | `#glossary_crs`, `#glossary_legislativeindexingvocabulary` | CRS is itself defined; the LIV entry discusses a distinct historical thesaurus and subject terms. Preserve these entries without treating their subject as glossary authorship or merging the resources. |
| [Congressional Record image](/Users/mikewolfd/Work/corpora/supply-2026-09-02/receipts/crs-operations-20261114/glossary/visual/c-record.png) | `#glossary_congressionalrecord` | The term and parts of the definition use italics. Preserve term HTML as well as definition HTML; the readable term is `Congressional Record`. |
| [T/V image](/Users/mikewolfd/Work/corpora/supply-2026-09-02/receipts/crs-operations-20261114/glossary/visual/t-v.png) | `#glossary_title`, `#glossary_veto` | A see-only definition is still an entry; the veto definition contains a qualified 10-day period. Retain the literal definition and links without inferring relations or modifying the qualification. |

All four screenshots were opened and inspected. The sample covers ten distinct
entries, including the final alphabetic section; it does not visually attest
every entry. The full-source test separately compares all 117 terms, exact
definition HTML, and 143 authored definition links with an independent source
slice oracle. There are no measurement columns or aggregation levels; the veto
specimen checks the literal qualified time period.
Missing authorship and publisher edition are explicit nulls. There are no empty
definitions or unresolved definition-fragment links in this capture.

The full original, rather than the test derivatives, establishes the source
identity. The small committed fixtures select entries and change the wrapper
and section coverage; their README records that limit. The negative fixture
deliberately removes one definition and must refuse.
