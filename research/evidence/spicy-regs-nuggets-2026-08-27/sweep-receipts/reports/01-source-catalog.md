## NUGGETS AT RISK

1. **Policy-defined universe scope and distinct exclusion reasons**

   - Landing: [universe.py:130](/Users/mikewolfd/Work/spicy-regs-landing/src/spicy_regs/source_catalog/universe.py:130), [universe.py:175](/Users/mikewolfd/Work/spicy-regs-landing/src/spicy_regs/source_catalog/universe.py:175)
   - Behavior: Conjunctive filtering by location prefix, agency, docket, document type, publication window, and selected-item budget. An unreadable publication date gets `policy.publication-date-unusable`, distinct from a valid date outside the window.
   - DocSpec gap: `RegulationsGovCatalogPolicy.configuration` has sampling and budget settings but no equivalent value-level scope predicates ([regulations_gov_catalog.py:446](/Users/mikewolfd/Work/DocSpec/src/docspec/application/regulations_gov_catalog.py:446)). Its sampler admits every non-withdrawn document and places bad dates in an `unknown` stratum ([regulations_gov_catalog.py:703](/Users/mikewolfd/Work/DocSpec/src/docspec/application/regulations_gov_catalog.py:703)); the item later fails required metadata instead of receiving the landing scope verdict.
   - Rediscovery cost: **High.** The predicates are simple; recovering the intended frame, reason taxonomy, and sampling order requires corpus and policy validation.

2. **Independent read-back recomputation of semantic claims**

   - Landing: [verify.py:35](/Users/mikewolfd/Work/spicy-regs-landing/src/spicy_regs/source_catalog/verify.py:35), [validate.py:224](/Users/mikewolfd/Work/spicy-regs-landing/src/spicy_regs/source_catalog/validate.py:224)
   - Behavior: A reader reparses canonical bytes and independently re-derives release identity, requested and selected set digests, disposition counts, coverage, schema membership, and member sizes.
   - DocSpec gap: The full recomputation exists only in the producer’s `SourceCatalogBuildGateVerifier` ([source_catalog_artifact.py:1230](/Users/mikewolfd/Work/DocSpec/src/docspec/adapters/source_catalog_artifact.py:1230)). `SourceCatalogArtifactReader.verify_snapshot` uses the lighter receipt verifier and merely consumes rows ([source_catalog_artifact.py:1291](/Users/mikewolfd/Work/DocSpec/src/docspec/adapters/source_catalog_artifact.py:1291)). The CLI then compares receipt claims with the same admitted summary rather than re-deriving them ([source_catalog_cli.py:442](/Users/mikewolfd/Work/DocSpec/src/docspec/source_catalog_cli.py:442)).
   - Rediscovery cost: **Low to medium.** Most computation already exists, but safely moving it into consumer verification requires bounded-stream and performance decisions.

3. **Incomplete Mirrulations draws remain accounted for**

   - Landing: [mirrulations.py:205](/Users/mikewolfd/Work/spicy-regs-landing/src/spicy_regs/source_catalog/mirrulations.py:205), [mirrulations.py:256](/Users/mikewolfd/Work/spicy-regs-landing/src/spicy_regs/source_catalog/mirrulations.py:256), [mirrulations.py:277](/Users/mikewolfd/Work/spicy-regs-landing/src/spicy_regs/source_catalog/mirrulations.py:277)
   - Behavior: Every drawn item becomes a row. Missing cache receipts become `unavailable`; unreadable cached metadata becomes `failed`; missing source dates may fall back to the mirror object’s source-stated `last_modified`.
   - DocSpec gap: DocSpec delegates acquisition to an installed SpicyRegs package ([spicyregs_source_native.py:14](/Users/mikewolfd/Work/DocSpec/src/docspec/adapters/spicyregs_source_native.py:14)); none of the four surviving repositories contains this draw-to-failure-row behavior. Once admitted, the DocSpec policy aborts a document with no modify or posted version ([regulations_gov_catalog.py:1726](/Users/mikewolfd/Work/DocSpec/src/docspec/application/regulations_gov_catalog.py:1726)).
   - Rediscovery cost: **High.** The important knowledge is which acquisition defects should remain catalog rows rather than abort or disappear.

4. **Verified-byte-first rendition preference**

   - Landing: [published_catalog.py:477](/Users/mikewolfd/Work/spicy-regs-landing/src/spicy_regs/source_catalog/published_catalog.py:477), [build_source_catalog_universe.py:93](/Users/mikewolfd/Work/spicy-regs-landing/tools/build_source_catalog_universe.py:93)
   - Behavior: Select exactly one family in this order: verified Mirrulations bytes, source file URL, exact Federal Register fallback. Lower-ranked families disappear, and an undeclared family is disabled.
   - DocSpec gap: DocSpec recognizes immutable candidates, but groups them with ordinary source URLs under one `regulations-gov-file` family ([regulations_gov_catalog.py:1743](/Users/mikewolfd/Work/DocSpec/src/docspec/application/regulations_gov_catalog.py:1743)). It can therefore return both verified and unverified candidates from that family; `locatorKind` does not influence ranking.
   - Rediscovery cost: **Medium-high.** The algorithm is small, but the rationale—known bytes outrank unverified locators—is easy to erase during source-native refactoring.

5. **Source-observed topics cannot impersonate RefSpec concepts**

   - Landing: [validate.py:214](/Users/mikewolfd/Work/spicy-regs-landing/src/spicy_regs/source_catalog/validate.py:214)
   - Behavior: Reject `observedTopicId` or `observedTopicScheme` beginning with `urn:ref:` or `urn:refspec:`. This mechanically separates publisher vocabulary from normalized RefSpec concepts.
   - DocSpec gap: `observed_topics` accepts any nonempty source identity and label ([catalog_policy.py:140](/Users/mikewolfd/Work/DocSpec/src/docspec/application/catalog_policy.py:140)); its schema requires only nonempty text.
   - Rediscovery cost: **Medium.** The implementation is trivial; the ownership boundary and reason for it are the knowledge at risk.

6. **Closed lexical refusal rules**

   - Landing: [discovery.py:101](/Users/mikewolfd/Work/spicy-regs-landing/src/spicy_regs/source_catalog/discovery.py:101), [discovery.py:220](/Users/mikewolfd/Work/spicy-regs-landing/src/spicy_regs/source_catalog/discovery.py:220), [universe.py:497](/Users/mikewolfd/Work/spicy-regs-landing/src/spicy_regs/source_catalog/universe.py:497)
   - Behavior: Enforces dotted machine-readable reason codes, BCP 47 language syntax, HTTP(S) rendition locators, media-type syntax, lowercase SHA-256, JSON-safe sizes, and absolute policy/source identifiers.
   - DocSpec gap: Selection reasons and policy language require only nonempty text ([source_catalog.py:110](/Users/mikewolfd/Work/DocSpec/src/docspec/domain/source_catalog.py:110), [regulations_gov_catalog.py:420](/Users/mikewolfd/Work/DocSpec/src/docspec/application/regulations_gov_catalog.py:420)). Candidate validation is stronger about immutable locators but looser about media types, language, and reason-code grammar.
   - Rediscovery cost: **Medium.** Easy rules to reimplement, but likely to be rediscovered one malformed artifact at a time.

7. **Source-item identity stays distinct from document identity**

   - Landing: [published_catalog.py:98](/Users/mikewolfd/Work/spicy-regs-landing/src/spicy_regs/source_catalog/published_catalog.py:98), [release.py:101](/Users/mikewolfd/Work/spicy-regs-landing/src/spicy_regs/source_catalog/release.py:101)
   - Behavior: A source item is namespaced as `regulations.gov/<documentId>`, while `documentId` retains the source identifier. Two selected source items may not claim one document.
   - DocSpec gap: The Regulations.gov policy assigns the raw `sourceRecordId` to both fields ([regulations_gov_catalog.py:1729](/Users/mikewolfd/Work/DocSpec/src/docspec/application/regulations_gov_catalog.py:1729)). Generic catalog validation enforces unique source-item IDs but not unique selected document IDs.
   - Rediscovery cost: **Medium.** The immediate corpus may avoid collisions, but recovering identity continuity after downstream digests and references exist is expensive.

8. **Bundles carry their exact validation schemas**

   - Landing: [schema_pins.py:55](/Users/mikewolfd/Work/spicy-regs-landing/src/spicy_regs/source_catalog/schema_pins.py:55), [validate.py:147](/Users/mikewolfd/Work/spicy-regs-landing/src/spicy_regs/source_catalog/validate.py:147)
   - Behavior: Verifies `pins.json`, byte size, SHA-256, `$id`, schema-set identity, and then publishes the exact three schema files as bundle members.
   - DocSpec gap: DocSpec pins `catalogSchemaDigest` and refuses a digest different from its installed schema family ([source_catalog_artifact.py:1095](/Users/mikewolfd/Work/DocSpec/src/docspec/adapters/source_catalog_artifact.py:1095)), but the catalog does not carry those schema bytes. Verification therefore depends on a matching installed implementation.
   - Rediscovery cost: **Low to medium.** Digest pinning survives; self-contained/offline validation does not.

## SAFELY SUPERSEDED

These are behaviorally reproduced in the current DocSpec working tree, subject to committing and preserving that worktree first.

- **Deterministic stratified sampling mechanics:** Landing’s MD5 ordering, agency/year strata, `rank / sqrt(stratumSize)`, per-document-type cap, and explicit undrawn rows ([universe.py:343](/Users/mikewolfd/Work/spicy-regs-landing/src/spicy_regs/source_catalog/universe.py:343)) are reproduced by DocSpec ([regulations_gov_catalog.py:703](/Users/mikewolfd/Work/DocSpec/src/docspec/application/regulations_gov_catalog.py:703)). The missing part is landing’s scope-filtered frame.

- **Sample-before-rendition selection order:** Landing samples before checking required metadata or renditions ([release.py:88](/Users/mikewolfd/Work/spicy-regs-landing/src/spicy_regs/source_catalog/release.py:88)); DocSpec does the same at [regulations_gov_catalog.py:1525](/Users/mikewolfd/Work/DocSpec/src/docspec/application/regulations_gov_catalog.py:1525).

- **Complete-universe accounting:** Landing emits one row per discovered item. DocSpec additionally compares the policy’s output stream with the complete universe stream and refuses omissions ([source_catalog_artifact.py:739](/Users/mikewolfd/Work/DocSpec/src/docspec/adapters/source_catalog_artifact.py:739)).

- **Exact docket and Federal Register joins:** Landing joins only identifiers stated by the document and rejects mismatched indexed rows ([published_catalog.py:413](/Users/mikewolfd/Work/spicy-regs-landing/src/spicy_regs/source_catalog/published_catalog.py:413)). DocSpec reproduces this and records matched/no-match evidence ([regulations_gov_catalog.py:1395](/Users/mikewolfd/Work/DocSpec/src/docspec/application/regulations_gov_catalog.py:1395)).

- **Complete source-native metadata preservation:** Landing’s new, currently uncommitted profile retains complete document, docket, and Federal Register records ([published_catalog.py:435](/Users/mikewolfd/Work/spicy-regs-landing/src/spicy_regs/source_catalog/published_catalog.py:435)). DocSpec’s `sourceNativeFacts` retains the full pinned source records rather than selecting known fields ([regulations_gov_catalog.py:127](/Users/mikewolfd/Work/DocSpec/src/docspec/application/regulations_gov_catalog.py:127)). Because DocSpec does not drop unknown nested fields, landing’s “unclassified column” refusal is not needed for loss prevention.

- **Explicit dispositions and reasons:** Selected, excluded, deleted, unavailable, and failed survive. Non-selected rows require a reason; selected rows forbid one; selected rows require a rendition ([source_catalog.py:104](/Users/mikewolfd/Work/DocSpec/src/docspec/domain/source_catalog.py:104), [source_catalog.py:289](/Users/mikewolfd/Work/DocSpec/src/docspec/domain/source_catalog.py:289)).

- **Pinned source inputs and policy bytes:** Landing hashes every supplied file against the declared source role and version ([publish_source_catalog_release.py:52](/Users/mikewolfd/Work/spicy-regs-landing/tools/publish_source_catalog_release.py:52)). DocSpec pins immutable source-native artifact identities, source state, source schema sets, and canonical policy bytes in its root and receipt ([source_catalog_artifact.py:1398](/Users/mikewolfd/Work/DocSpec/src/docspec/adapters/source_catalog_artifact.py:1398)).

- **Canonical bytes, member hashing, and undeclared-file refusal:** DocSpec delegates this generic artifact behavior to surviving Rulespec code, which explicitly rejects missing and extra materialized files ([rulespec `_artifact.py`:2952](/Users/mikewolfd/Work/rulespec/packages/rulespec-artifacts/src/rulespec_artifacts/_artifact.py:2952)).

- **Atomic, no-overwrite publication:** Landing’s private staging directory and atomic rename are superseded by DocSpec’s staged immutable store and post-build admission gate ([source_catalog_artifact.py:1357](/Users/mikewolfd/Work/DocSpec/src/docspec/adapters/source_catalog_artifact.py:1357), [source_catalog_artifact.py:1524](/Users/mikewolfd/Work/DocSpec/src/docspec/adapters/source_catalog_artifact.py:1524)).

Bottom line: preserve the eight nuggets above, and commit or otherwise secure the DocSpec successor work before removing this worktree. Current source equivalence is not yet durable repository equivalence.


