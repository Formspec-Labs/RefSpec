# EuroVoc's scheme self-description: what the publisher intends

**Date:** 2026-08-21
**Question:** `eurovoc-domains-4.24` and `eurovoc-4.24` report their publisher
scheme subjects unrepresented. Is that a real gap, an export artifact, or a
modelling choice Atlas is entitled to make differently?

## What the publisher actually publishes

Verified in the pinned bytes (`eurovoc-4.24-skos-core.zip`), not inferred:
**129 subjects are typed `skos:ConceptScheme`** — the 127 microthesauri, the
EuroVoc thesaurus itself (`100141`), and a grouping scheme
`<http://eurovoc.europa.eu/domains>`. The 21 domains are typed
`skos:Concept` and carry `skos:inScheme <…/domains>`; domain `100145` is
`"12 LAW"@en`, and so on.

The two subjects Atlas represents nothing at are small and exact:

| subject | what it carries |
|---|---|
| `<http://eurovoc.europa.eu/domains>` | 2 triples: the type, and `"Eurovoc domains"@en` — English only |
| `<http://eurovoc.europa.eu/100141>` | 28 triples: the type, and `"EuroVoc"` in 27 languages |

Under the English-only language scope, that is **one type claim and one
English label per subject** — four triples in total that the Atlas could
represent and currently does not.

## Is the domains scheme real, or an export artifact?

Real, and publisher-intended. The Publications Office's own 2025 paper on
EuroVoc prints the domains scheme as a first-class node: Figure 2 is captioned
"A glimpse of the 21 *EuroVoc* domains (**all links are `skos:inScheme`
relationships**)", showing the 21 domains attached to a central EUROVOC
DOMAINS node. Their editorial tool shows it too — VocBench's scheme list in
Figure 4 carries "Eurovoc domains (en)" beside "EuroVoc (en)" and
"Candidates (en)". The paper's Future Work section proposes modular
extensions, federated models, and thematic hubs, but **no change to this
structure**, so it is not a transitional artifact either.

Our own pinned bytes agree with the paper exactly, which is the reassuring
part: the publisher's documentation and the publisher's data say the same
thing.

## The one place Atlas is genuinely entitled to differ

Typing microthesauri as `skos:ConceptScheme` is a documented **workaround**,
not an intrinsic claim. SKOS has no native construct for a thesaurus's
domain/microthesaurus super-structure; ISO 25964's SKOS extension models it
as `ConceptGroup`, and EuroVoc instead "redeclar[ed] MicroThesauri as
ConceptSchemes, Domains as Concepts, and MicroThesauri 'classified' on the
domains" to work within plain SKOS. Atlas modelling a microthesaurus as a
concept of its own microthesauri scheme is therefore a defensible reading of
the same structure — which is exactly what `member_type_inverse` now declares
and reverses, and why that check can pass honestly.

That reasoning does **not** extend to the two scheme subjects above. Nobody
worked around anything there: the publisher asserts a type and a name, and
the Atlas asserts nothing at those IRIs at all.

## Recommendation

Anchor, don't waive. The minted scheme should carry
`atlas:representsResource <publisher IRI>` plus the retained English label,
for `<…/domains>` and `<…/100141>` alike. That is four triples, it makes the
publisher's own naming reversible, and it lets a declared inverse close the
comparison the way `member_type_inverse` closed the typing one — evidence
rather than exemption.

The alternative — declaring grouping-scheme self-description out of scope —
would be defensible only if Atlas asserted nothing about those schemes. But
it *does*: it mints a scheme per unit and places resources in it. Claiming the
structure while refusing to name its source is the asymmetry worth avoiding.

**Owner decision required** — this is a producer change and a modelling call,
not a verifier fix.

## Note on eurovoc-4.24's 128

Most of `eurovoc-4.24`'s reported gap is a partitioning effect, not a hole:
127 of its 128 scheme subjects are the microthesauri, which the Atlas *does*
represent — in the `eurovoc-microthesauri-4.24` unit. The verifier compares
per pair, so a claim represented by a sibling unit reads as unrepresented
here. Only `100141` is genuinely unrepresented. Worth stating in the receipt
rather than "fixing", so a future reader does not go looking for 127 missing
resources that are one unit away.

## Sources

- Walhain, Albouze, Gerencsér, Paunescu, Tzouvaras, Palma (Publications
  Office of the EU / infeurope / EC), *The EuroVoc Thesaurus: Management,
  Applications, and Future Directions*, LDK 2025, pp. 340–350 —
  https://aclanthology.org/2025.ldk-1.34.pdf (Figures 2 and 4; Table 1;
  Section 5)
- ISO 25964 SKOS extension (`iso-thes`), `ConceptGroup` —
  http://pub.tenforce.com/schemas/iso25964/skos-thes/iso-thes-25964.xhtml
- Skosmos issue #634, "Display hierarchy of domains and micro-thesaurus" —
  https://github.com/NatLibFi/Skosmos/issues/634
- EU Vocabularies, EuroVoc —
  https://op.europa.eu/en/web/eu-vocabularies/eurovoc
- Pinned publisher bytes: `eurovoc-4.24-skos-core.zip`
  (sha256:91bdb24e…), read directly
