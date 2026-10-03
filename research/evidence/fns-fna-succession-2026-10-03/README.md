# FNS → FNA succession: the public records (2026-10-03)

The evidence behind `event:fr200` in
[the succession batch](../../../plans/agency-registry-succession-batch-adjudication.md):
the Food and Nutrition Service (Federal Register agency 200, regulations.gov
`FNS`) renamed the Food and Nutrition Administration (Federal Register agency
625, regulations.gov `FNA`). This is a candidate for the owner's adjudication,
not an assertion.

`scripts/fetch.py` fetched every file under `raw/` on 2026-10-03 between
12:11:51Z and 12:12:06Z. It made one keyless GET per URL, in sequence, with
one User-Agent. `manifest.json` records each URL, file, HTTP status, size and
SHA-256. One request was refused and nothing was kept for it: the USDA
reorganization plan PDF (`sm-1078-015.pdf`) returned HTTP 403.

## What each record says, read in context

- **The rename in the CFR.** 91 FR 37779 is FR Doc 2026-12700, a WIC final
  rule making technical corrections; it is effective on its publication date,
  2026-06-24. Lines 388–398 of `raw/fr-document-2026-12700.txt`:

  ```text
      Accordingly, the Food and Nutrition Administration amends 7 CFR
  chapter II by making the following technical corrections:

  CHAPTER II--FOOD AND NUTRITION ADMINISTRATION, DEPARTMENT OF
  AGRICULTURE

  1. Under the authority of the Reorganization Plan No. 2 of 1953 (5
  U.S.C. app.; 7 U.S.C. 2201 note) and the Department of Agriculture
  Reorganization Act of 1994 (Pub. L. 103-354), revise the heading for
  chapter II to read as set forth above.
  ```

  Amendment 1 is the rule's only name change: amendment 2 restates part 246's
  authority, and amendment 3 revises a WIC table. The rule carries docket `FNS-2022-0007` and RIN `0584-AE82`, both
  also on the 2024 rule it corrects. That rule is 89 FR 28488, FR Doc
  2024-07437 (`raw/fr-document-2024-07437.json`), and the Register files it
  under the Food and Nutrition Service. The 2026 rule's summary nevertheless
  says "On April 18, 2024, the Food and Nutrition Administration (FNA)
  published a final rule". That is the new name written back over the old
  one, and it is why the event must carry a date.

- **eCFR confirms the day.** The point-in-time API heads Title 7 chapter II
  "Food and Nutrition Service" on 2026-06-23 and "Food and Nutrition
  Administration" on 2026-06-24 (`raw/ecfr-title-7-chapter-II-ancestry-*.json`).
  RefSpec's retained eCFR title XML of 2026-08-24 (`output/ecfr-title-xml-2026-08-24/title-7.xml`,
  `sha256:fa121dee…`, line 127736) reads
  `CHAPTER II—FOOD AND NUTRITION ADMINISTRATION, DEPARTMENT OF AGRICULTURE`.
  It sits directly above subchapter A, Child Nutrition Programs, and part
  210, the National School Lunch Program, so the heading belongs to the same
  chapter.

- **The Register switched records in June.** As of the fetch, nothing was
  filed under FR 200 after FR Doc 2026-10828 (91 FR 32372, 2026-06-01)
  (`raw/fr-fns-documents-since-2026-05-15.json`, 5 documents since
  2026-05-15). The first document filed under FR 625 is FR Doc 2026-11917
  (91 FR 35951, 2026-06-15), with 37 in all (`raw/fr-fna-documents-oldest.json`).
  That first document's agency line reads "AGENCY: Food and Nutrition
  Administration (FNA), USDA". Its form, `FNA-775`, is "a revision of a
  currently approved collection" under OMB number `0584-0686`, FNS's OMB
  prefix.

- **The Register's own record of 625.** `raw/fr-agency-625.json` gives parent
  12 (Agriculture) and `agency_url` https://www.fns.usda.gov/about/reorganization.
  Its description restates FR 200's role ("administers the USDA food
  assistance programs"). The record is in the held roster
  `federal-register-agencies-roster-2026-08-15`; FR 200 is in it too, still
  under parent 12, and Agriculture's `child_ids` list both.

- **USDA's own pages.**
  - `raw/fns-about-reorganization.html` says: "As part of the USDA
    reorganization plan (.pdf), the Food and Nutrition Service and the Food,
    Nutrition, and Consumer Services mission area are now the Food and
    Nutrition Administration." It gives no date. The plan it links,
    SM 1078-015, refused the fetch.
  - `raw/usda-press-release-0062.26.html` (Washington, D.C., April 30, 2026)
    says the mission area "announced its intention to introduce the Food and
    Nutrition Administration", under the subtitle "The Food and Nutrition
    Administration, formerly the Food and Nutrition Service".
  - Neither page is a record kind the release admits as dated
    (`DATED_PUBLIC_RECORD_KINDS`). The candidate cites them only for the
    alternative date and the owner note.

## Publisher discrepancies

- **regulations.gov files FNA under DOI.** In the retained roster
  (`tests/fixtures/regulations_gov_agencies/regulations-gov-agencies-2026-08-16.json`),
  the `FNA` entry reads `"parent": "DOI"`. Its name is all capitals ("FOOD AND
  NUTRITION ADMINISTRATION"), the only one of 331 so written, and its
  `postingGuidelines` is `""`, where 318 entries have `null`. `FNS` reads
  `"parent": "USDA"`.
  - The Federal Register (625, parent 12) and the eCFR (Title 7 chapter II,
    Agriculture) both place FNA in Agriculture. The regulations.gov parent
    therefore looks like a publisher entry error. RefSpec carries it as
    published: the roster release emits each publisher `parent` as a native
    relation.
  - REF-038 maps `FNA` to FR 625 by exact acronym equality, so spicy-regs'
    `lookup_agency` reports FR 625's parent, 12. The live record could not be
    rechecked: `api.regulations.gov` answered 429 to `DEMO_KEY` on
    2026-10-03, for the round-5 auditor and again for this pass. The roster
    release's recapture-and-diff obligation will show whether regulations.gov
    has corrected it.
- **eCFR's agency roster lags its own text.** The held eCFR agencies roster
  (`tests/fixtures/cfr_list_of_subjects/ecfr-agencies-2026-08-15.json`) still
  names Title 7 chapter II's agency "Food and Nutrition Service" (slug
  `food-and-nutrition-service`), seven weeks after the chapter heading
  changed.
