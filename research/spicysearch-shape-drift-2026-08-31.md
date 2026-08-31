# The shape drift, measured: spicysearch's `identifiers.py` vs `identifier_shapes.py`

`identifier_shapes.py` was ported from SpicySearch's `identifiers.py`, both
copies stayed live, and the module's own header calls the two spellings
drifting apart "the defect this module keeps producing." Intake ledger §3.1
(`plans/2026-08-31-refspec-intake-ledger.md`) rules that the shapes should be
read from RefSpec once. This note records what the drift actually is — both
modules imported and run side by side on 2026-08-31 — so the retirement, when
it lands, adopts each difference on purpose instead of silently.

## The two gates, and where they stand

Both were discovered by attempting the retirement on 2026-08-31; both moved
the same day:

1. **The spicysearch worktree was dirty** — six files of unrelated
   in-progress work — and the submodule repoint (REF-051's executing step)
   refuses to land on a dirty tree. **Cleared and executed later that day**:
   once the worktree's owner committed their milestone, spicysearch `5ee3d34`
   moved the pin `141fd671 → 99167ca1`, flipped the submodule URL to GitHub,
   and its full fast tier passed against the new pin (1,319 green).
2. **There is no import wiring to swap.** The assumed topology ("submodule +
   editable path dep") is stale: spicysearch's `pyproject.toml` declares no
   `refspec` dependency at all — only `docspec` and `rulespec-artifacts` as
   vendored wheel path deps — and its venv has no `refspec` install. Every
   live reference is a filesystem path (`REFSPEC_CHECKOUT` pointing at a
   build's `output/`) or a schema string literal. **The packaging path is now
   proven, not just proposed**: `uv build --wheel` produces
   `refspec-0.1.0.dev0-py3-none-any.whl` (1.6 MB), which installs only
   beside the vendored `rulespec_conformance-0.2.0rc15` wheel (refspec's
   dependency on it is index-less by design) — so the pattern is TWO wheels
   into spicysearch's existing `vendor/` + `[tool.uv.sources]` scheme, whose
   pyarrow ceiling was already widened to `<24` for exactly this. Verified in
   an isolated env: the divert's imports work, including
   `mint_federal_register_document_iri("09-19806", column_licensed=True)` →
   `urn:rkaf:partner:refspec:frdoc:09-19806`. What remains is the
   spicysearch-side change itself: vendor the two wheels, declare the dep,
   swap `identifiers.py`'s shape definitions for the refspec imports (query
   policy stays), and add the drift table below to its tests so each
   adoption is loud. The four `document_number` consumers
   (`identifiers.py`, `date_events.py`, `metadata_snapshot.py`,
   `source_catalog_metadata.py`) are where minting plugs in after that.

## The drift, reproduced

Identical in both (no drift): the RIN shape
(`\d{4}-[A-Za-z]{2}[A-Za-z0-9]{2}`), the FR legacy and correction shapes, the
bare docket organization grammar (no office segment), and the
regulations.gov document/docket tie case (`EPA-HQ-OAR-2021-0317-0001`).

Divergent — every case below was run through both modules:

| Case | spicysearch `identifiers.py` | RefSpec `identifier_shapes.py` |
| --- | --- | --- |
| `2011-237`, `2010-5997` (3–4 digit FR tail) | not detected | detected |
| `R1-2010-13257` (republication form) | no republication kind at all | detected as a shape (still refused for minting) |
| `FDA-2026-N-0008`, `EERE-2022-BT-OT-0004` (docket office segment) | not detected | detected as docket |
| `Docket Nos. FDA-2025-E-0162` (label + office segment) | not detected | detected |
| `Docket #: AMS-SC-24-0046` (doubled label punctuation `#:`) | not detected | detected |

Root causes, each already documented and paid for in
`identifier_shapes.py`'s header: spicysearch still carries the old
five-digit-only FR shape (`\d{4}-\d{5}`) that RefSpec widened away from
(28,862 real values recovered); its docket and regulations.gov grammars have
no office-segment group; its docket label punctuation is a single optional
`[:#]?` against RefSpec's `[:#\-]*`. The drift is one-directional:
spicysearch's copy predates measured fixes, and no case was found where it
reads something RefSpec refuses.

Two smaller findings from the same pass:

- **A latent landmine spicysearch inherited-around:** RefSpec's
  `IdentifierCandidate` carries a hand-written `__hash__` because the frozen
  dataclass's generated one raises `TypeError` on the `components` mapping;
  spicysearch's identically shaped dataclass has no override. Nothing
  triggers it today; the first caller to put candidates in a set does.
- **A test that would pass the drift silently:** spicysearch's
  `test_one_federal_register_grammar_answers_for_the_whole_repository` pins
  the current five-digit-exact behavior but never exercises a 3–4 digit
  tail, so adopting RefSpec's widened shape would pass it rather than fail
  it. When the divert lands, that test needs cases from the table above so
  each adoption is loud.

The citation grammars are a separate and much larger duplication surface:
RefSpec's `citation_grammar.py` has grown to ~3,900 lines (case reporters,
chapters, appendices, proclamations) with no spicysearch analogue. That is
outside §3.1's stated scope and is flagged here only so a future widening of
the port prices it correctly.
