# Visual attestation: the RISC Preamble's abbreviations glossary

**2026-08-21.** `unified-agenda-legal-authority-citation-types` had no
independent publisher adapter. Rather than write a second PDF extractor, pages
18–19 of `risc-preamble-202210.pdf` were read as rendered images and the
producer's output compared against what they show.

## What Section V contains

The section is headed *V. Abbreviations*, introduced by "The following
abbreviations appear throughout this publication:". Read off the pages, it
defines **twelve** terms, in this order:

    ANPRM   CFR   E.O.   FR   FY   NPRM        (page 18)
    Legal Authority   Pub. L.   RFA   RIN   Seq. No.   U.S.C.   (page 19)

The Atlas release carries **three** of them — `U.S.C.`, `Pub. L.`, `E.O.` — and
is declared `scope="captureSubset"`, which is the honest label: it is 3 of 12,
not the glossary.

## The three definitions are verbatim

Each was compared character for character against the rendered page. All three
match exactly, including punctuation and the example in the `Pub. L.` entry:

- **U.S.C.** — "The United States Code is a consolidation and codification of all general and permanent laws of the United States. The USC is divided into 50 titles, each title covering a broad area of Federal law."
- **Pub. L.** — "A public law is a law passed by Congress and signed by the President or enacted over his veto. It has general applicability, unlike a private law that applies only to those persons or entities specifically designated. Public laws are numbered in sequence throughout the 2-year life of each Congress; for example, Public Law 112-4 is the fourth public law of the 112th Congress."
- **E.O.** — "An Executive order is a directive from the President to Executive agencies, issued under constitutional or statutory authority. Executive orders are published in the Federal Register and in title 3 of the Code of Federal Regulations."

## The trap in this document, and it is a close one

`CFR` is defined in the same glossary, four entries above `E.O.`, and its
wording overlaps `U.S.C.`'s almost completely:

    U.S.C.  ... divided into 50 titles, each title covering a broad area of Federal law.
    CFR     ... divided into 50 titles, each title covering a broad area subject to Federal regulation.

The two differ only in the final three or four words. An extractor keyed on
"divided into 50 titles" would have an even chance of transcribing the CFR
sentence into the U.S.C. record, and the result would read plausibly — a
consumer would have no way to notice. The producer carries the U.S.C. wording,
ending "of Federal law". Checked deliberately, because this is the failure that
would not look like one.

## Why three and not twelve

The other nine are not legal-authority citation types. `ANPRM`, `NPRM`, `FR`,
`FY`, `RIN`, `Seq. No.` and `RFA` name document kinds, dates, identifiers or an
analysis. `Legal Authority` names the Agenda *field* these three appear in, not
a citation type within it. `CFR` is the one arguable exclusion — a CFR cite is a
regulation rather than the authority for one, which is the distinction the field
draws — and it is the one whose absence a reader should be able to see stated
rather than infer. It is stated here.

## What this attestation is not

It is not a `SourceSpec`. It does not re-read the PDF and proves nothing about a
later Preamble; `risc-preamble-202210` is the Fall 2022 edition and RISC issues a
new Preamble with each agenda. The producer already re-reads these three
definitions out of the pinned bytes at parse time
(`_verify_citation_type_definitions`), so a source revision fails loudly — that
check, not this file, is what protects the next edition.
