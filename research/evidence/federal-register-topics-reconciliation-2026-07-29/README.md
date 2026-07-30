# Federal Register topics: unresolved reconciliation proof

## Result

The exact 1995 Federal Register thesaurus and the captured
`/api/v1/topics.json` response do not support a defensible source selection,
cross-source concept mapping, or synthesized union. The conforming
`RegistryReconciliationReport` therefore records `outcome: unresolved`,
`conceptMappings: []`, and `synthesizedUnionAuthorized: false`.

The report digest is
`sha256:c8546297b73ff237a0e9437da551b6cc068237f3c74ff4989d4b4eb87845bb08`.
The full report, exact input references, counts, and stage digests are in
[evidence.json](evidence.json).

## Exact inputs

| Input | SHA-256 | Bytes |
| --- | --- | ---: |
| 1995 `thesaurus-alpha.txt` | `d5e013336d4179790e8d6574d4dc9d8cfcb10ce76af202ff4db068617eb8fd30` | 99,349 |
| Captured `topics.json` | `aba80a4dcacbffc7c9ec29eb88ea385ec313510fc8331d0f69078d940d1da35b` | 920,705 |

The local reproducibility test reads these files from their content-addressed
Spicy Regs source stores:

- `output/managed-vocabulary-experiment/source-store/sha256/d5e013.../thesaurus-alpha.txt`
- `output/federal-register-topics-source-store/sha256/aba80a.../topics.json`

The checked evidence never treats those paths as identity. It binds the exact
artifact digest, source URL, parser profile, and each parsed-stage digest.

## Observations

| Observation | Count |
| --- | ---: |
| Current `thesaurus` records | 1,044 |
| Current `ad_hoc` records | 6,723 |
| `thesaurus` slug-collision groups | 8 |
| `ad_hoc` slug-collision groups | 68 |
| Empty current slugs | 3 |
| Preferred-label overlap | 619 |
| Historical preferred labels only | 10 |
| Current thesaurus names only | 425 |
| Current names matching any historical label | 629 |
| Historical relation assertions | 1,496 |
| Current thesaurus `see_also` assertions | 1,428 |
| Historical unresolved source references | 20 |

These are literal-evidence comparisons, not identity assertions. The 6,723
`ad_hoc` records remain a separate source collection.

## Identity and authority boundary

A current API source record uses only:

`capture SHA-256 + collection + zero-based source ordinal`

Its name and slug are preserved as evidence but never used as identity. The
collision and empty-slug counts make that rule testable rather than advisory.

`RegistryReconciliationReport` requires release, import, and governance
references even for an unresolved result. This proof labels them as
development snapshot references derived from the exact captures. They are not
authoritative concept releases, and no Rulespec release-graph validation
receipt promotes them. They authorize neither candidate use nor accepted
output.

The focused regression suite also proves three negative cases:

1. The unresolved report cannot name a synthesized release.
2. The unresolved report cannot select either input.
3. A selected `RegistryDeploymentDecision` cannot cite this report.

Run:

```text
uv run pytest -q tests/test_federal_register_topics_reconciliation.py
```
