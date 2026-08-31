# Seven delegated decisions

**2026-08-20.** These were raised as owner calls. The owner delegated them back
with "do everything that increases Atlas's usefulness, and helps us achieve our
goals," explicitly covering both the engineering queue and the decisions.

They are recorded here rather than as REF entries because minting a REF number is
an act of the decision ledger and these are delegated judgements, not ratified
policy. Each states its basis and how to reverse it. Any of them can be promoted
to a REF entry, or overturned, without unpicking work — that is why they were
made in this order.

---

## 1. May a tagger emit into `federal-register-api-topics`? → **Both, tiered**

**Decision.** A tagger may emit into that scheme, but its output is a *distinct
tier* from a tag reaching the same topic through an independent vocabulary. The
two are never pooled into one accuracy number.

**Basis.** Atlas carries the Federal Register's own 1,044-term topic list in
full. Emitting into it reproduces a publisher index — real utility, especially
for regulations.gov documents that carry no FR topics, but no semantic claim.
Reaching the same topic through MeSH/LCSH/EuroVoc *is* a semantic claim. REF-035's
three-state discipline already distinguishes source-assigned from
machine-assigned, so the machinery to keep them apart exists.

Pooling them would make the headline coverage number meaningless: 100% against
the answer key's own vocabulary, 93.6% against everything else.

**Reversal.** Drop one tier. No data migration; the tiers are labels on emitted
tags, not separate stores.

## 2. What vocabulary does the product serve? → **Scheme-scoped now, induction as research**

**Decision.** Serve a named, small set of schemes per use case rather than all
1.5M concepts. Do not pool schemes into one lookup. Keep vocabulary induction as
a research track, not a dependency.

**Basis.** Measured: pooled across schemes, an abstain-on-ambiguity matcher
discards 42.7% of label strings, and 92% of those discards fire because two
related authorities *agree* (LCSH↔FAST). Scoped, abstention costs 0–1.2% on the
big schemes. The project's own record argues an unauditable vocabulary is a
defect in a product whose value is the join surface.

**Reversal.** Adding a scheme is configuration. Induction stays available.

## 3. TSCA / EPA chemicals → **Keep the capability; add TSCA to Atlas as a scheme**

**Decision.** Do not accept the 70,736-substance regression that a swap to Atlas
would cause. Add TSCA as an Atlas scheme. Queued behind tagger work — it blocks
nothing today.

**Basis.** EPA is among the largest agencies in the labelled corpus (19,285
documents). Atlas has no chemical inventory at all: zero TSCA schemes, zero CAS
identifiers, verified without the `s-chem-e` substring trap. Chemical-substance
tagging is not a nice-to-have for EPA rulemaking; it is the subject matter.

**Reversal.** Cheap — a new scheme is additive and does not touch existing ones.
If EPA turns out not to be a served market, the scheme costs storage and nothing
else.

## 4. The lifecycle hold → **Keep the hold; write down why, and stop rebuilding**

**Decision.** Do not build the concept-lifecycle detector now. Do record that the
decision was made, so the idea stops being independently rediscovered.

**Basis.** Four repos hold four implementations of "absent ≠ checked-and-found-
nothing"; none runs. Two of the four are *deliberate* — spicy-regs' `ClosureClaim`
is disabled by an executed decision with four enforcement mechanisms, and
RefSpec's build raises if `lifecycleEvents != 0`. The missing piece is a
source-side detector that diffs two editions of a vocabulary, which is weeks per
source and blocked on nothing else being ready to consume it.

The cost of the current state is not the missing feature. It is that this has now
been rediscovered four times, at real expense each time.

**Reversal.** The machinery is built and tested on all four sides. Removing the
`lifecycleEvents == 0` guard is the switch.

## 5. Commit the survey and evidence artifacts → **Yes**

**Decision.** Commit them.

**Basis.** Twelve subagent sweeps and five adversarial validators, single copy,
untracked, in a repo that has been actively pruned this week. A parallel session
building a branch-delete list from topology nearly caught two spike branches that
were protected only by a line in a plan document; untracked files have less
protection than that.

**Reversal.** `git rm`.

## 6. "The Unclaimed Ledger" artifact → **Leave it**

**Decision.** Leave it published. Do not delete.

**Basis.** It is private, owned by the account, carries no credentials or personal
data, and its content is a sound rendering of the RefSpec written-record survey.
It was published by a subagent without being asked, which is a process finding
worth recording — but the artifact itself is not the problem, and deleting a
useful private page to make a point about process is the wrong trade.

**Reversal.** Delete at any time; nothing links to it.

## 7. DocSpec's lost Office formats → **Out of scope here; flagged, not fixed**

**Decision.** Do not act from this repo.

**Basis.** DocSpec lost DOCX/PPTX/XLSX extraction in its 2026-08-05 rewrite
without a tracked follow-up; the dispatch now raises `ExtractionError` for
anything Office-typed. It is latent — no Office files exist in any local corpus —
so nothing is currently failing. It is also another repo's capability, and
reaching into it from here would violate the product topology this project
enforces everywhere else.

**Reversal.** Not applicable; this is a referral, not a change.

---

## What was NOT decided

Whether SpicySearch reuses the 0004 semantic verdict for tagging. That gate
belongs to the session that owns it, and it ruled: fresh sealed holdout, because
0004 is a ranking verdict (query→document, nDCG) and tagging is multi-label
classification (document→label set, P/R/F1). Reusing it would be a category
error. That call stands and is not revisited here.
