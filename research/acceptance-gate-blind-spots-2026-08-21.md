# Two things the acceptance gates said were fine

**Date:** 2026-08-21
**Artifacts:** `atlas-3.1-full-2026-08-21c`, `atlas-3.1-full-2026-08-21d`
(both recorded `verdict: passed`, 13 of 13 gates)

A 32-second smoke check found what 13 passing gates did not. Both findings
below are in 21c as well as 21d, so neither is new to today's contract work,
and both trace to `6535f570` (2026-08-16, the mapping-era seal).

## 1. 1,831 resources carry two preferred labels

`atlas:AtlasResourceShape` fixes `skosxl:prefLabel` to **exactly one value
per resource**. UMTHES resources violate it 1,831 times out of 3,365.
`<https://sns.uba.de/umthes/_00000013>` carries both `"degradation"@en` and
`"Abbau"@de` as preferred labels — verified in the pack bytes, not inferred
from a report.

The cause is in `_umthes_registry_labels`
(`src/refspec/atlas/v3_registry_alignments_subject.py`): it dedupes by
`(value, language)` and keeps the best role per key, but never enforces one
preferred label per *resource*. A record with a German and an English
preferred label emits both.

This is the same rule the EuroVoc module documents and obeys, in a docstring
written this morning: "`SkosXlPrefLabelShape` fixes `skosxl:prefLabel` to
exactly one value per resource." One module learned the constraint; its
sibling, added in the same commit, did not.

**Unresolved and more important than the defect:** the producer's acceptance
recorded `shacl-data: passed` with an evidence digest, over a graph the
binding's own SHACL path refuses. Two readers, same bytes, opposite verdicts.
Either the gate is not equivalent to the normative shapes for this constraint,
or it validates something other than what ships. Until that is answered,
"13/13 passed" cannot be read as independent confirmation.

## 2. No full distribution can be independently validated at all

`validate.py --distribution` never reaches SHACL. It stops at
`rdf.resource-limit`: `packs/mappings/lcsh-external-links-mappings-2026-08-15.nq.zst`
holds **6.13 GiB of content against a hard 4 GiB per-pack limit**. Exactly one
pack of 192 exceeds; transport (0.35 GiB of 1 GiB) and dataset total
(23.3 GiB of 32 GiB) are both comfortable.

The producer already has the remedy and declines to apply it here — 179 of 192
packs are bucketed. `_release_pack_partition` states the reasoning:

> A mapping release is packed whole … Bucketing is a source-release device for
> large member sets, and a large mapping release is large in assertions, not
> members.

The premise is sound and the conclusion does not follow: pack *size* tracks
assertions, not members, so a release that is "large in assertions" is exactly
the one that overruns a byte limit. The comment reasoned about why mappings
need no *member* bucketing and concluded they need no bucketing at all.

**Consequence:** the independent verifier — the artifact's whole trust
argument, the thing a consumer copies to check RefSpec's work without running
RefSpec's code — cannot load a full development distribution. Every gate
verdict for these builds is producer self-attestation.

## What each needs

| finding | fix | cost |
|---|---|---|
| duplicate preferred labels | enforce one preferred label per resource in the UMTHES adapter, the way the EuroVoc module does; decide which language wins (English, to match every sibling) | small producer change + rebuild |
| gate/validator disagreement | diagnose which graph the producer's `shacl-data` gate validates and why it passes; this is the load-bearing one | investigation first |
| oversized mapping pack | bucket large mapping releases with the existing device; touches pack paths, the partition refusal, and validator path expectations | producer change + rebuild |

None was fixed today: the first two want a decision about which reader is
authoritative, and the third changes the pack layout consumers pin.
