# Annual section context

`annual-2012-title40-322-323.htm` is an exact byte slice from retained OLRC
`2012.zip`, member `2012/2012USC40.htm`. `provenance.json` records its half-open
byte span and archive/member/fixture digests.

The excerpt keeps bracketed repealed section 322, its zeroed `usckey`, and the
following section 323 with its own document comment and heading. SpicyDocs
retains both observations; RefSpec's existing attestation policy excludes the
bracketed stub. Tests mutate this retained source to exercise ranges, invalid
tokens, missing keys and Unicode handling.

`structural-prefixes.xml` contains exact opening/number/heading slices from
retained release-point 119-102 title 10, 14 and 41 files. Only the enclosing
`uscDoc` and closing unit tags are constructed. The provenance file pins the
source member and each slice. The source tags and headings identify a part,
chapter and division under a subtitle; the old subsection regex treated the
initial `s` of `st` as a section marker.

`structural-prefix-corrections.json` freezes all 364 false subsection tuples
from those longer-prefix paths in the retained 58-title corpus, with source
identifier, element kind, member and opening-tag byte span for each. It records
285 chapters, 70 parts and 9 divisions. It is test evidence for the intentional
source-parser correction, not a production compatibility table.
