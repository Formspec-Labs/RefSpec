# Federal Register vocabulary policy

The April 1, 2025 Federal Register Thesaurus is the default managed candidate
vocabulary for Federal Register documents. It has strong source-native
priority in that profile. Other Spicy Regs profiles keep their own primary
resources and use the balanced cross-domain path.

## What goes in

- The exact NARA PDF, pinned by URL, issue date, byte length, page count, and
  SHA-256 digest.
- The 1995 text edition, used only to build historical comparisons.
- Current FederalRegister.gov Topics, captured separately with their source
  records and capture time.
- Lists of Subjects literals with the exact source record and field location.

## What happens

The styled-PDF reader treats bold entries as official terms, styled variants
as variants, `See` as a redirect, and `See also` as an associative reference.
It records ambiguous redirects, bracketed open-term suggestions, unresolved
references, and index anomalies rather than guessing.

The 1995 reader preserves `xx` statements as historical document groupings.
It never converts them to `skos:broader`. The 2025 publication contains no
semantic hierarchy.

The crosswalk compares each 1995 preferred and alternate label with 2025
official terms and publisher-authored variants. It classifies historical rows
as unchanged, renamed, redirected, ambiguous, or removed, and identifies 2025
terms with no incoming evidence as added. The crosswalk is analysis evidence;
it does not assert concept identity or authorize candidate selection.

## What comes out

- 705 managed 2025 concepts.
- Recognized variants attached only when the complete publication resolves the
  literal to one official concept.
- Associative relations, open-term suggestions, unresolved references, and
  source anomalies as separate records.
- An evidence-backed 1995 to 2025 crosswalk.
- Current API Topics as mutable source-assigned metadata, never merged into the
  managed thesaurus.

Lists of Subjects receive one explicit result:

1. `officialTerm`
2. `recognizedVariant`
3. `sourceLocalOpenTerm`
4. `unresolved`

A source-local open term requires explicit authorization, a source record ID,
and a source path. None of the four outcomes silently mints a concept.

## How to check it

The package manifest binds every artifact by byte length and SHA-256 digest.
Offline tests lock source counts, crosswalk coverage, Lists of Subjects
behavior, the absence of `skos:broader`, active-profile boundaries, and the
Federal Register-specific candidate priority. Optional gates regenerate the
checked extract from the exact PDF and reopen the complete managed release.
