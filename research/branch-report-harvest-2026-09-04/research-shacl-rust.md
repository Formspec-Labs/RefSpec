<!-- markdownlint-disable MD013 -->

> Harvested 2026-09-04 from branch `research/shacl-rust` at `6f9a3260`,
> file `REPORT.md`, committed 2026-08-13. Verbatim; nothing edited.

# Rust SHACL engine decision for Atlas 3.1

**Decision date:** 2026-08-13

**Binding tested:** RefSpec commit `b2b36bee80be7d2918e419ab63975ca680a3f9d6`

**Decision:** Do not replace pySHACL with Rudof 0.3.8.

Rudof passes Atlas's executable SHACL feature floor and returns the correct
invalid verdict for all 48 SHACL-owned corpus refusals. It reproduces the exact
`shaclComponents` set for 45 of 48, however. In the other three cases, pySHACL
includes the inner result below `sh:node` while Rudof reports only the outer
`NodeConstraintComponent`. Both reports comply with SHACL Core, but only
pySHACL matches Atlas's contractual component lists. The exact-parity gate
therefore fails, and the ordered study stops before staging cost.

## Candidate verdicts

| Candidate | Version and date | Status | Reason |
| --- | --- | --- | --- |
| [Rudof](https://github.com/rudof-project/rudof/releases/tag/0.3.8) | 0.3.8, released 2026-08-13, commit `cad3840` | **Tested; rejected for cutover** | It passes the runtime feature floor, all 48 SHACL-owned cases receive the correct invalid verdict, and all 13 valid controls pass. Exact component parity is 45/48. |
| [`shacl-rust`](https://docs.rs/crate/shacl-rust/0.2.11/source/Cargo.toml) | 0.2.11, dated 2026-07-31, source commit `590a9aa40d4d6f66fca58f707715d15a760d707e` | **Documented-only** | Published source covers the feature families and includes a native `IndexedGraph`; no executable was available for this study. |
| [`oxirs-shacl`](https://docs.rs/crate/oxirs-shacl/0.3.1) | Published crate 0.3.1, 2026-06-06; repository tag [0.4.1](https://github.com/cool-japan/oxirs/releases/tag/v0.4.1), 2026-07-28, commit `8a32274` | **Documented-only** | Source covers the feature families, but no artifact was available to run. The 0.4.1 W3C integration test does not fail when suite cases fail, skip, or error. |
| [`oxigraph-cloud` Rudof pairing](https://github.com/chapeaux/oxigraph-cloud/blob/95d0613a9467d810b5d615930968d757b36669a8/crates/oxigraph-shacl/src/validator.rs) | Commit `95d0613a9467d810b5d615930968d757b36669a8`, 2026-04-06 | **Rejected** | It serializes every Oxigraph quad into one in-memory N-Triples `String`, drops graph names, and reparses the text into Rudof `RdfData`. It is not a direct engine-over-store path. |

The tested Rudof executable is a 36,393,184-byte macOS arm64 binary built from
`rudof_cli` 0.3.8 with `--locked`. Its SHA-256 is
`a1ebe0120fd7b270e4cb452678394fbfa69f0ed8c8be50e7872599875ae6d3be`.
The previous dated source audit remains in
[`candidate-source-audit.json`](research/shacl-rust/raw/candidate-source-audit.json).

## Gate 1: executable feature floor passes

The supplied acquisition run already established that Rudof parses the real
Atlas shapes into 376 shape entries and recognizes the sequence-path
`sh:equals` and `sh:class` components. The resumed run tested evaluation, not
only parsing. Every positive case conformed, and every one-mutation negative
case failed with the required component.

| Component | Positive case | Negative mutation and observed result | Result |
| --- | --- | --- | --- |
| `sh:xone` | Exactly one branch holds. | Both branches hold; `XoneConstraintComponent`. | **Pass** |
| `sh:closed` | Focus node uses only the declared property. | Add one undeclared property; `ClosedConstraintComponent`. | **Pass** |
| `sh:class` at scale | 590,000 `sh:targetClass` focus nodes each point to an instance of the required class. The 90,860,324-byte input conformed in 8.890 s. | The last focus node points to an untyped value; `ClassConstraintComponent` in 8.700 s. | **Pass** |
| `sh:in` | Value is a member of the allowed RDF list. | Replace it with a nonmember; `InConstraintComponent`. | **Pass** |
| `sh:node` | The value conforms to the nested node shape. | Remove the nested shape's required property; `NodeConstraintComponent`. | **Pass** |
| sequence path plus `sh:equals` | `(ex:p / ex:q)` and `ex:r` reach the same value. | Make the two value sets differ; `EqualsConstraintComponent`. | **Pass** |

The large `sh:class` timing is a feature stress check, not a staging benchmark:
it uses synthetic N-Triples and a standalone process. The 48-case run also
exercised Atlas's datatype, pattern, cardinality, value-range, and property-pair
families against real binding shapes.

Rudof lists JSON as a result format, but `-r json` panics in 0.3.8 because the
serializer contains an unimplemented branch. The probes and parity run use
Turtle reports, parsed as RDF, so this interface defect does not weaken the
feature result. The feature harness and raw reports are
[`probe_rudof_feature_floor.py`](research/shacl-rust/probe_rudof_feature_floor.py)
and
[`rudof-feature-floor.json`](research/shacl-rust/raw/rudof-feature-floor.json).

## Gate 2: verdict parity passes, exact component parity fails

### Correct Atlas input graph

The production validator does not concatenate every pack or validate the
projection. For each fixture, the probe:

1. reads the manifest's named graph IDs and verifies each role's declared quad
   count;
2. constructs the same 367-triple ontology view as
   `pyshacl.rdfutil.inoculate(Graph(), ontology)`;
3. validates `asserted` plus that ontology view;
4. if `asserted` conforms, validates `derived` plus the ontology view; and
5. excludes `projection` and stops at the first nonconforming role, matching
   Atlas's role order.

The harness also compares its parsed `asserted`, `projection`, and `derived`
triple sets with Atlas's lexical-preserving production parser. All 183 role
comparisons across the 48 refusals and 13 valid controls are exact.

Rudof receives the full normative shapes and resolves all focus nodes itself;
the probe applies no shape or focus-node filter. This matches the production
validator's normative audit meaning, without copying its pySHACL-only batching
optimization. As a control, the corrected view passes all 13 valid fixtures.
`all-resource-profiles`, which appeared to fail under the earlier raw-pack
concatenation, now conforms for its 836-triple asserted graph and its 13-triple
derived graph.

### Case-by-case result

All 48 cases receive the correct invalid verdict. Exact sorted component sets
agree for 45.

| Case | pySHACL components | Rudof components | Result |
| --- | --- | --- | --- |
| `adjudication-artifact-scheme-unknown` | `InConstraintComponent` | `InConstraintComponent` | **Exact** |
| `adjudication-comparison-incomplete` | `MinCountConstraintComponent` | `MinCountConstraintComponent` | **Exact** |
| `adjudication-evaluated-at-not-datetime` | `DatatypeConstraintComponent` | `DatatypeConstraintComponent` | **Exact** |
| `adjudication-issuer-incomplete` | `MinCountConstraintComponent` | `MinCountConstraintComponent` | **Exact** |
| `adjudication-lineage-incomplete` | `MinCountConstraintComponent` | `MinCountConstraintComponent` | **Exact** |
| `adjudication-proof-rationale-empty` | `MinLengthConstraintComponent` | `MinLengthConstraintComponent` | **Exact** |
| `adjudication-proof-type-not-machine` | `HasValueConstraintComponent` | `HasValueConstraintComponent` | **Exact** |
| `adjudication-response-artifact-cardinality` | `MaxCountConstraintComponent` | `MaxCountConstraintComponent` | **Exact** |
| `adoption-without-referent` | `ClassConstraintComponent` | `ClassConstraintComponent` | **Exact** |
| `asserted-naked-mapping` | `ClosedConstraintComponent` | `ClosedConstraintComponent` | **Exact** |
| `assertion-asserted-at-not-datetime` | `DatatypeConstraintComponent` | `DatatypeConstraintComponent` | **Exact** |
| `assertion-extra-property` | `ClosedConstraintComponent` | `ClosedConstraintComponent` | **Exact** |
| `cross-ring-endpoint-ring-reversal` | `EqualsConstraintComponent` | `EqualsConstraintComponent` | **Exact** |
| `cross-ring-missing-evidence` | `MinCountConstraintComponent` | `MinCountConstraintComponent` | **Exact** |
| `derived-asserted-scheme-collision` | `ClosedConstraintComponent` | `ClosedConstraintComponent` | **Exact** |
| `derived-is-authoritative` | `ClosedConstraintComponent`<br>`EqualsConstraintComponent`<br>`MinCountConstraintComponent` | `ClosedConstraintComponent`<br>`EqualsConstraintComponent`<br>`MinCountConstraintComponent` | **Exact** |
| `duplicate-preferred-language` | `MaxCountConstraintComponent` | `MaxCountConstraintComponent` | **Exact** |
| `evidence-attested-at-not-datetime` | `DatatypeConstraintComponent` | `DatatypeConstraintComponent` | **Exact** |
| `evidence-attestor-kind-unknown` | `InConstraintComponent` | `InConstraintComponent` | **Exact** |
| `evidence-decision-not-approved` | `HasValueConstraintComponent` | `HasValueConstraintComponent` | **Exact** |
| `evidence-function-unknown` | `InConstraintComponent` | `InConstraintComponent` | **Exact** |
| `evidence-warrant-unsanctioned` | `XoneConstraintComponent` | `XoneConstraintComponent` | **Exact** |
| `identifier-missing-value` | `MinCountConstraintComponent` | `MinCountConstraintComponent` | **Exact** |
| `label-missing-literal` | `MinCountConstraintComponent` | `MinCountConstraintComponent` | **Exact** |
| `lifecycle-applies-to-nonassertion` | `ClassConstraintComponent` | `ClassConstraintComponent` | **Exact** |
| `lifecycle-effective-date-not-datetime` | `DatatypeConstraintComponent` | `DatatypeConstraintComponent` | **Exact** |
| `lifecycle-event-kind-unknown` | `XoneConstraintComponent` | `XoneConstraintComponent` | **Exact** |
| `lifecycle-rescission-names-target-release` | `XoneConstraintComponent` | `XoneConstraintComponent` | **Exact** |
| `mapping-missing-evidence` | `ClassConstraintComponent`<br>`MinCountConstraintComponent` | `ClassConstraintComponent`<br>`MinCountConstraintComponent` | **Exact** |
| `mapping-period-end-before-start` | `LessThanOrEqualsConstraintComponent` | `LessThanOrEqualsConstraintComponent` | **Exact** |
| `mapping-period-end-not-utc-day-end` | `PatternConstraintComponent` | `PatternConstraintComponent` | **Exact** |
| `mapping-period-start-not-datetime` | `DatatypeConstraintComponent`<br>`NodeConstraintComponent` | `NodeConstraintComponent` | **Divergence** |
| `mapping-period-start-not-utc-midnight` | `PatternConstraintComponent` | `PatternConstraintComponent` | **Exact** |
| `mapping-subject-ring-dated` | `XoneConstraintComponent` | `XoneConstraintComponent` | **Exact** |
| `mapping-undated-legal-identity` | `XoneConstraintComponent` | `XoneConstraintComponent` | **Exact** |
| `mapping-undated-value-crosswalk` | `XoneConstraintComponent` | `XoneConstraintComponent` | **Exact** |
| `mapping-wrong-endpoint-release` | `EqualsConstraintComponent` | `EqualsConstraintComponent` | **Exact** |
| `non-english-definition` | `LanguageInConstraintComponent`<br>`NodeConstraintComponent` | `NodeConstraintComponent` | **Divergence** |
| `non-english-label` | `LanguageInConstraintComponent` | `LanguageInConstraintComponent` | **Exact** |
| `registry-conflict-detected-at-not-datetime` | `DatatypeConstraintComponent`<br>`NodeConstraintComponent` | `NodeConstraintComponent` | **Divergence** |
| `registry-conflict-publication-blocking` | `InConstraintComponent` | `InConstraintComponent` | **Exact** |
| `registry-conflict-severity-unknown` | `InConstraintComponent` | `InConstraintComponent` | **Exact** |
| `registry-conflict-single-entry` | `MinCountConstraintComponent` | `MinCountConstraintComponent` | **Exact** |
| `release-membership-mode-unknown` | `InConstraintComponent`<br>`XoneConstraintComponent` | `InConstraintComponent`<br>`XoneConstraintComponent` | **Exact** |
| `scheme-assertion-property` | `ClosedConstraintComponent` | `ClosedConstraintComponent` | **Exact** |
| `skosxl-label-role-overlap` | `DisjointConstraintComponent` | `DisjointConstraintComponent` | **Exact** |
| `subject-scheme-disagreement` | `EqualsConstraintComponent` | `EqualsConstraintComponent` | **Exact** |
| `supersession-dangling-predecessor` | `ClassConstraintComponent` | `ClassConstraintComponent` | **Exact** |

The reproducible runner and complete RDF reports are
[`probe_rudof_corpus.py`](research/shacl-rust/probe_rudof_corpus.py) and
[`rudof-corpus-parity.json`](research/shacl-rust/raw/rudof-corpus-parity.json).

### Divergence verdicts

The three differences have one cause. In every case, pySHACL emits one
top-level `NodeConstraintComponent` result and attaches one inner result with
`sh:detail`. Atlas collects every `sh:ValidationResult` in the report graph, so
its component list also includes the detail's component. Rudof emits the outer
node result without `sh:detail`.

| Case | Inner pySHACL detail omitted by Rudof | Standards verdict | Atlas verdict |
| --- | --- | --- | --- |
| `mapping-period-start-not-datetime` | `DatatypeConstraintComponent` from `atlas:DateTimeValueShape` | Both conform. | Rudof is incompatible. |
| `non-english-definition` | `LanguageInConstraintComponent` from `atlas:EnglishTextLiteralValueShape` | Both conform. | Rudof is incompatible. |
| `registry-conflict-detected-at-not-datetime` | `DatatypeConstraintComponent` from `atlas:DateTimeValueShape` | Both conform. | Rudof is incompatible. |

The [SHACL Core `sh:node` definition](https://www.w3.org/TR/shacl/#NodeConstraintComponent)
requires one outer node result when the nested conformance check fails. The
[validation-report rules](https://www.w3.org/TR/shacl/#details) say `sh:detail`
*may* provide the nested violations; they do not require it. Rudof is not wrong
under SHACL Core, and pySHACL's richer report is also allowed. Atlas deliberately
makes the full sorted component set contractual, so standards conformance does
not erase the mismatch.

## Gate 3: cost not run

The study orders cost after executable features and exact corpus parity. Rudof
passes the first gate but fails the second, so no staging validation or RSS
measurement ran. The supplied 13.097 s residual-SHACL baseline, 11.652 s indexed
baseline, and roughly 598 MiB whole-path peak remain comparison values, not
measurements reproduced here.

The earlier integrity check also found that the staging artifact records shapes
digest `724aefcf349c51b74af75387c638365502db2f4638e27aa16e5f241090c8d48c`,
while the tested shapes digest is
`af85315e9f6918d166ed24a0cef6d98820c4430c936178842382a3a1279c1abf`.
Even after report parity is solved, a like-for-like cost result needs an artifact
pinned to the tested binding.

## Honest cutover price

Rudof needs report compatibility before performance matters. The acceptable
paths are either:

- Rudof preserves nested validation results as `sh:detail`, and the Atlas
  adapter flattens all result nodes exactly as the current validator does; or
- Atlas makes an explicit product decision to redefine `shaclComponents` as
  top-level components only, then reissues the corpus and every affected proof
  identity.

The first path preserves behavior. The second deletes supported diagnostic
behavior and is not an engine migration.

Before production deletion, the current pySHACL behavior must survive as copied
test-only oracle code, not an import of the path being replaced. A candidate
adapter must prove the full 132-case end-to-end corpus, including the 48 SHACL
component lists and 13 valid controls, plus a current-binding real distribution
and a mutation battery for every constraint and property-path family. The
battery must include nested `sh:node` details, sequence paths, positive and
negative large-class cases, and a frozen list of any deliberate divergence.
Only then can the production pySHACL path be deleted.

The compiled dependency also changes the binding's operating promise. The
tested binary is a 36.4 MB Mach-O arm64 executable. Requiring consumers to have
that binary, a Rust toolchain, or network access destroys the current
copy-`bindings/atlas/3.1/`, install `requirements.txt`, and validate-offline
workflow. Preserving that workflow requires trusted, digest-pinned artifacts
for every supported operating system and CPU, copied with the binding or
embedded in platform-specific wheels. That adds platform builds, signatures,
software-bill-of-materials and license review, security updates, unsupported-
platform policy, subprocess or extension failure rules, and release testing for
every artifact. One macOS arm64 binary cannot meet that obligation.

## What would change the decision

The decision changes only when one native candidate does all four:

1. keeps the passed runtime feature floor;
2. reproduces all 48 SHACL-owned component lists exactly and accepts all 13
   valid controls;
3. demonstrates time and peak RSS consistent with native storage on a staging
   artifact pinned to the same binding, including load, shape compilation,
   validation, report construction, and teardown; and
4. ships verified offline artifacts without weakening the binding's
   copy-and-run consumer promise.

**Rudof proves that a Rust SHACL engine can evaluate Atlas, but it does not break the wall because exact report parity fails before native-storage cost can be credited.**
