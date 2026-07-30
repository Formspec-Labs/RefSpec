# Development concept-domain bridges

These files are small, reviewed lookup experiments. They are not publisher
crosswalks, accepted-output authorization, or a merged concept registry.

`icpsr-federal-register-concept-bridge-v1.json` connects seven ICPSR Subject
Thesaurus concepts to distinct members of the Federal Register Thesaurus
development release. Every edge is `skos:closeMatch`; preferred-label equality
alone does not justify `skos:exactMatch`.

The selected artifact is pinned as
`sha256:41b08a28a4bd13de7cd0dbd7929adf780768c2f394d44db50a9ea6f280011c52`.
The offline bridge reader verifies this artifact and every target member. It
retains the ICPSR source URL, revision, and digest as review evidence but does
not download those source bytes on every lookup. A later import or promotion
must reacquire and verify the upstream snapshot independently.

Six ICPSR aliases add query paths that the Federal Register release does not
author: `constitutional rights`, `hazardous materials`,
`medical professions`, `housing projects`, `asylum seekers`, and
`vocational training`. `trade unions` is a no-regression control because the
Federal Register release already authors that alias.

The experiment omits `warrants` even though ICPSR exposes it as a
non-preferred term for `search warrants`. The captured source also assigns the
same alternate label to `arrest warrants`, so a single-answer shortcut would
hide real ambiguity.

The bridge also omits ICPSR's `low income housing` alias from the selected
`public housing` anchor. In the real release comparison it displaced the more
specific Federal Register `Low and moderate income housing` result. The source
snapshot remains pinned; this lookup bridge records only the reviewed query
paths selected for the experiment.

ICPSR publishes the thesaurus under CC BY-NC 4.0. RefSpec records that fact as
source metadata and accepted playground risk; it does not remove concepts,
disable indexing, or limit their use in this experiment. Other access,
privacy, security, and quality controls remain independent.
