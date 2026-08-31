# What 68 Supreme Court opinions actually cite

**2026-08-21.** The SCOTUS pipeline had never run anywhere; fetched locally
today (term 2025, 68 opinions, all with extracted text, pdf_sha256-pinned at
`output/court-opinions-2026-08-21/`). Read with the unified citation grammars
and the pinned OLRC act index — every number below is one afternoon's tooling
applied to one term.

| kind | citations | opinions carrying it |
|---|---:|---|
| U.S.C. | **6,797** | 58/68 |
| case reporters (F.3d, U.S., S. Ct.) | **2,336** | **68/68** |
| Statutes at Large | 184 | 31/68 |
| CFR (in body text) | 64 | 13/68 |
| executive orders | 22 | 5/68 |
| act-relative names (OLRC-resolvable) | — | 8/68 |

**The court route is a U.S.C. route by 106:1** (6,797 vs 64) — the regulatory
metadata corpus measured 5:1 the other day; a term of actual opinions is
twenty times more lopsided. Top titles: 28 (judiciary and procedure — the
Court talks about its own jurisdiction constantly), 18 (criminal), 8
(immigration), 42, 15, 52 (a voting-rights term).

**Case citations are the second-densest signal and appear in every single
opinion** — the reporter family added to the grammar this afternoon (72 rows
in the Agenda) is 2,336 rows in one Court term. Any future opinion-tagging or
opinion-linking route will run on (U.S.C. section, case citation) pairs, not
on CFR parts.

Act names resolve through the pinned index where they appear (ERISA, Voting
Rights Act of 1965, Tariff Act of 1930), but at 8/68 opinions they are a
garnish, not a route.

Caveats: one term, slip opinions only, extraction via the pipeline's own text
layer; per-curiam and order-list texts skew short. The corpus and this
profile are both re-derivable from pinned bytes.
