# Atlas source-fidelity auditor: NASA note kinds and English language scope

## Result

This branch delivers both requested auditor changes.

1. The auditor no longer treats NASA `zthes:termNote` kind markers as note
   text. The NASA annotation check falls from 19,312 emitted failure rows for
   9,656 marker claims to zero.
2. The auditor now applies a separate, checked language-scope declaration to
   the eight vocabulary sources. It itemises 871,823 publisher semantic claim
   entries by source, language tag, and predicate family. It excludes only the
   declared non-English literal claims from comparison and proves that Atlas
   asserts no non-English tagged literal anywhere in the distribution.

The full audit against the existing
`atlas-3.1-full-2026-08-13` artifact remains red by design. That artifact
predates the producer change and has no construction `languageScope` statement.
The new gate reports this omission even though its whole-distribution scan finds
zero non-English Atlas literals and zero label, definition, or note literals
without exact `@en`.

The implementation is committed on `research/auditor-language-scope`:

- `5e833c18` — `fix(audit): stop treating NASA note kinds as annotation text`
- `36dcd45c` — `feat(audit): declare checked English language scope`

## Task 1: NASA `zthes:termNote` markers

`src/refspec/registry/nasa_thesaurus.py` treats `zthes:termNote` values as note
kind markers such as `Definition` and `Definition Source`. The detached blocks
hold the real text, and the reader deliberately does not join them. The auditor
already assesses those source statements in `reification-fidelity`.

The change removes `zthes:termNote` from the annotation-literal predicate set.
The scoped real-data result is:

| NASA annotation-fidelity result | Before | After |
| --- | ---: | ---: |
| Emitted failure rows | 19,312 | 0 |
| Marker claims reported twice | 9,656 | 0 |
| Check verdict | Fail | Pass |

Each marker had produced two annotation failures: one for missing note text and
one for missing predicate-preservation evidence. `reification-fidelity` still
reports the 9,656 detached statements as one counted summary failure. This
change removes only the double count; it does not claim that Atlas reconstructs
the detached source statements.

The saved receipts are:

- `/private/tmp/auditor-lang-task1-before.json`, SHA-256
  `3fd5fb6a76836e0fa3c98671d9e17b099f9bad1fde02c579928dbf6ee92d8329`
- `/private/tmp/auditor-lang-task1-after.json`, SHA-256
  `7d386fcef3fb2c5c5d2a5c536080820c4ddbaa25c33993f5d8d6faa231324622`

## Task 2: checked English language scope

### Input and selection

The auditor authenticates `language-scope-exclusions.json` by the producer's
specified SHA-256:
`8c7ffd458cef9b182d86b1b3e9626cc0d38d5db6eb0d8ba1ef59e63e024082bb`.
Its bytes match producer commit `b079de13` exactly. The payload fixes:

- schema version and exclusion type;
- the BCP 47 English-family selection rule;
- allowed semantic families and source predicates;
- every source, language-tag, and family count; and
- the total of 871,823 excluded semantic claim entries.

The auditor first applies each `SourceSpec` subset. It then resolves the
existing semantic comparison families: preferred, alternate, and hidden labels;
definitions; notes; member metadata; source-scheme literals; and declared
source-wide literals. It selects a row only when the literal has a valid BCP 47
tag whose primary subtag is not `en`.

The count unit matches the producer payload: one unique semantic literal claim
in one auditor comparison family after subset selection. A publisher triple can
belong to two existing comparison families when the publisher uses a semantic
predicate on a source scheme. The real payload contains no duplicate selected
triple across those family entries; its 871,823 family entries also represent
871,823 distinct publisher literal claims.

### Fail-closed behavior

The language mechanism is separate from `DeclaredClaimExclusion`.
`DeclaredClaimExclusion` continues to select whole publisher subject layers and
continues to reject overlap with compared subjects. The new mechanism selects
individual literal claims on compared concepts and schemes. It never relaxes
the entity-layer safeguards.

The mechanism proves the four required properties:

1. **Literal claims only.** It selects only explicitly tagged non-English
   literals. Untagged literals, English-family literals, IRI claims, and the
   subjects themselves remain in their existing checks.
2. **Atlas must contain zero excluded content.** A manifest-wide pack scan
   fails on any non-English or invalid language-tagged Atlas literal. It also
   requires every Atlas label, definition, and note literal to use exact `@en`.
   The scan examines all manifest packs, not only the eight source packs.
3. **Exact itemisation.** The receipt records the payload digest, selection
   rule, allowed predicates, expected and actual source/language/family cells,
   selected claim count, selected-claim digest, Atlas count, and any failure.
   New languages, new families, undeclared predicates, and count drift prevent
   the exclusion from applying.
4. **English remains bidirectional.** English claims stay in both publisher-to-
   Atlas and Atlas-to-publisher comparisons. Tests inject missing publisher
   English and manufactured Atlas English labels and require both failures.

The negative tests also cover a missing construction statement and a
non-English literal on an Atlas-only release. The focused test file now has 221
tests, up from 211 at task assignment.

### Scoped real-data audits

Each row comes from an independent `--only <spec>` receipt against:

- distribution:
  `/Users/mikewolfd/Work/spicy-regs/RefSpec/output/atlas-3.1-full-2026-08-13`
- publisher sources:
  `/Users/mikewolfd/Work/spicy-regs/RefSpec/output/registry-real-data-sources`

The before runs disable only the new language declaration. The after runs use
the committed mechanism. “Differing rows” sums the existing comparison and
reconciliation checks but omits `distribution-coverage` and the new
`language-scope` gate; the latter contributes one expected failure because this
legacy artifact lacks the construction statement. These diagnostic rows can
count one claim in more than one check, so they are not a unique-claim total.

| Source | Uncovered before | Uncovered after | Differing rows before | Differing rows after | Declared entries |
| --- | ---: | ---: | ---: | ---: | ---: |
| AGROVOC bounded | 0 | 0 | 63 | 20 | 40 |
| DOE OSTI | 0 | 0 | 23,658 | 23,658 | 0 |
| ELSST R6 | 0 | 0 | 212,230 | 15,038 | 192,292 |
| EuroVoc 4.24 | 0 | 0 | 468,797 | 10,608 | 445,531 |
| EuroVoc domains | 0 | 0 | 585 | 37 | 546 |
| GEMET 4.2.3 | 0 | 0 | 262,915 | 27,477 | 233,407 |
| NALT bounded | 0 | 0 | 57 | 45 | 7 |
| NASA thesaurus | 0 | 0 | 41,989 | 41,989 | 0 |

All eight receipts report the language family as `declared-out-of-scope`, with
exact expected-versus-actual cells. Each reports one `language-scope` failure:
the missing construction statement. The scoped Atlas-wide zero-content result
was computed against the manifest and all packs once, then reused across the
remaining receipts for the same immutable distribution.

## Full audit

I ran one full audit after the implementation commit. It completed in 923.91
seconds and wrote `/private/tmp/auditor-lang-full.json`, SHA-256
`19c55899ced629acbb0776fb8f2feee042cd0522d5e8bb5ff7549ce06bd376fd`.
The preflight reported 48 GiB installed and 71% memory free. `/usr/bin/time -l`
ran with the audit, but this sandbox denied its `sysctl kern.clockrate` query
and omitted the extended peak-RSS fields. The run completed without an
out-of-memory error; I cannot honestly report a measured peak RSS.

The headline results are:

- `source-claim-coverage`: pass; **0 uncovered claims**;
- language declaration: **871,823** itemised semantic claim entries;
- Atlas-wide scope scan: **0** non-English tagged literals, **0** noncanonical
  label/definition/note literals, and **0** scan failures;
- check verdicts: **7 pass, 19 fail**; and
- overall verdict: fail, including the expected missing construction statement
  and pre-existing fidelity or coverage findings outside this task.

| Check | Verdict | Failure rows |
| --- | --- | ---: |
| load-errors | Fail | 14 |
| configuration | Fail | 1 |
| language-scope | Fail | 1 |
| claim-scope | Fail | 70 |
| distribution-coverage | Fail | 101 |
| publisher-input-pins | Fail | 28 |
| graph-structure | Pass | 0 |
| rdf-provenance-fidelity | Fail | 65,102 |
| native-control-fidelity | Fail | 1 |
| source-extract-fidelity | Pass | 0 |
| concept-traceability | Pass | 0 |
| identifier-retention | Pass | 0 |
| label-fidelity | Fail | 5,230 |
| notation-fidelity | Fail | 40 |
| annotation-fidelity | Fail | 7,341 |
| member-iri-fidelity | Fail | 9,891 |
| member-literal-fidelity | Fail | 22,971 |
| top-concept-fidelity | Fail | 113 |
| relation-fidelity | Fail | 9,667 |
| no-manufactured-relations | Pass | 0 |
| reification-fidelity | Fail | 1 |
| count-reconciliation | Fail | 41 |
| scheme-organisation | Fail | 406 |
| source-release-metadata | Fail | 29 |
| source-claim-coverage | Pass | 0 |
| source-defects | Pass | 0 |

### Declared scope versus genuine loss

The owner supplied the baseline classification of 889,115 differences. Of
those, the language decision reclassifies 868,444, or 97.68%, as declared scope
rather than loss. That leaves **20,671 baseline differences** as genuine
fidelity findings. This claim count differs from the payload's 871,823 semantic
family entries because the prior diagnostic did not emit one difference for
every declared entry. The report keeps these two units separate.

The current full receipt still contains 121,048 emitted failure rows across all
checks. That number is not the 20,671 unique baseline difference count: it also
contains configuration, input, construction-unit coverage, provenance,
reconciliation, and other summary rows, and some claims appear in more than one
check. The remaining substantive source-fidelity findings include provenance,
English-content labels and annotations, member metadata, relations, scheme
organization, release metadata, and the deliberate NASA reification finding.

## Verification gates

- `make lint` — passed: `All checks passed!`
- `uv run --no-sync pytest tests/test_verify_atlas_source_fidelity.py -q` —
  passed: `221 passed in 1.11s`
- eight scoped before/after real-data audits — completed; all after receipts
  matched their exact declaration cells
- one full real-data audit — completed once; 7/26 checks passed, zero uncovered
  claims, and 871,823 declared entries

## Main-tree merge requirements

1. Merge producer commit `b079de13` from `research/fidelity-langbugs`. It owns
   the construction schema, English-family predicate, exact `@en` wire
   normalization, and producer tests.
2. Merge `5e833c18` and `36dcd45c`. Keep
   `language-scope-exclusions.json` byte-identical or update the hard-coded
   digest together with an owner-approved replacement payload.
3. Rebuild the full Atlas distribution. The current 2026-08-13 artifact cannot
   pass `language-scope` because its construction summary lacks the new field.
4. Rerun the binding validator and the full source-fidelity audit against the
   rebuilt artifact. Confirm the exact construction statement, zero Atlas
   exclusions, and all eight source-cell reconciliations.
5. Merge other agents' `SourceSpec` additions around this change. This branch
   deliberately avoids editing the eight source declarations; the new mechanism
   is localized in the auditor and its declaration payload.

This work is committed only on the disposable research branch. It does not
push, publish, deploy, or replace the main-tree output artifact.
