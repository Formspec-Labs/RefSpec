<!-- markdownlint-disable MD013 -->

# RefSpec Core Enrichment Profile

## Editor's Draft, 29 July 2026

> **Profile identifier:** `urn:ref:enrichment-profile:core:v1`
>
> **RefSpec specification:** [RefSpec 1.0](../spec/refspec.md)
>
> **Rulespec binding:** [RefSpec Rulespec Application Profile](rulespec-application-profile.md)
>
> **Status:** Normative profile under development

## 1. Purpose

This profile defines the twelve core REF enrichment facets. A facet states
what kind of result a candidate or accepted output represents. It does not
define a vocabulary, merge source vocabularies, or authorize a result for
candidate or accepted-output use.

The exact permission to use a reference-resource release, mapping, or open
label comes from one complete row in an immutable REF `OutputProfile`.
Rulespec owns the portable concept, assignment, value assertion, evidence,
provenance, review, and authorization records.

## 2. Facet and route model

Core route names in this profile identify how REF routes a target before
enrichment:

- `document`, `participation`, `container`, `entity`, `observation`, and
  `event` are the corresponding REF coverage routes; and
- `externalReference` is the REF operational record kind for a resource that
  remains outside the captured corpus.

The portable target still uses the Rulespec type required by the application
profile. Route compatibility does not make an REF processing record a
Rulespec assertion target and does not transfer an assignment from a rendition
artifact or source fragment to its parent resource.

The compatible assignment-role set is:

- `rkaf:assignmentPrimary`;
- `rkaf:assignmentSubstantive`;
- `rkaf:assignmentMention`; and
- `rkaf:assignmentContextual`.

Those roles are orthogonal to facets. Listing all four as compatible means the
core profile does not forbid the combination. An `OutputProfile` still has to
authorize the exact facet and role together.

## 3. Core facets

| Facet IRI | Label and definition | Inclusion cues | Exclusion cues | Compatible routes | Compatible assignment roles |
| --- | --- | --- | --- | --- | --- |
| `urn:ref:facet:general-subject` | **General subject.** A cross-domain policy, social, economic, legal, environmental, or administrative matter that describes what the target is substantively about. | Central policy issue; regulated activity; public problem; broadly reusable navigation topic. | Named referent; legal citation; industry code; affected group; document form; action; process stage; source status; ontology type; quantity. | `document`, `participation`, `container`, `externalReference` | All four core roles |
| `urn:ref:facet:specialist-subject` | **Specialist subject.** A domain-specific matter whose useful meaning depends on a specialist vocabulary or expert practice. | Clinical procedure; chemical process; aerospace technology; specialist scientific, engineering, or professional topic. | A named chemical, organism, person, organization, facility, or program; a general policy topic adequately carried by the general-subject facet; another structural facet. | `document`, `participation`, `container`, `externalReference` | All four core roles |
| `urn:ref:facet:entity` | **Entity.** A particular or resolvable person, organization, place, facility, program, chemical, organism, product, or other referent. | Stable identifier or resolvable name; registry member; evidence supports identity or entity type. | A subject class, unnamed affected population, industry class, legal location, or document genre. | `document`, `participation`, `container`, `entity`, `observation`, `event`, `externalReference` | All four core roles |
| `urn:ref:facet:legal-location` | **Legal location.** A governed location or citation in a legal authority or legal record. | USC, Public Law, CFR, Executive Order, court, docket, or provision citation with enough information to resolve its legal location. | A general topic about law; an unparsed title; a source artifact identifier; a claim about legal effect. | `document`, `participation`, `container`, `event`, `externalReference` | All four core roles |
| `urn:ref:facet:industry-classification` | **Industry classification.** Membership in a governed economic-activity or industry classification. | NAICS or another identified classification release; evidence that the classification describes an industry relevant to the target. | A named company or facility; a product code; a general subject; a population described without a classification identifier. | `document`, `participation`, `entity`, `observation`, `externalReference` | All four core roles |
| `urn:ref:facet:affected-population` | **Affected population.** A class of people, organizations, facilities, products, or other members materially regulated, protected, eligible, burdened, or otherwise affected. | Scope or applicability language; regulated class; beneficiary or burden-bearing group. | A named entity; an incidental audience mention; an industry classification used without evidence of affected status; a general subject. | `document`, `participation`, `observation`, `externalReference` | All four core roles |
| `urn:ref:facet:genre` | **Genre.** The communicative form or source kind of the target. | Rule, proposed rule, guidance, complaint, report, testimony, decision, or another governed document or communication form. | What the target discusses; what an authority does; where the target sits in an administrative workflow; a publisher's ungoverned display label. | `document`, `participation`, `externalReference` | All four core roles |
| `urn:ref:facet:regulatory-action` | **Regulatory action.** An action proposed, performed, or decided by a regulatory or legal actor. | Propose, amend, repeal, withdraw, delay, approve, deny, or decide when the evidence supports the action relation. | Document genre; administrative stage; a verb appearing without support that the target performs or addresses the action. | `document`, `participation`, `event`, `externalReference` | All four core roles |
| `urn:ref:facet:administrative-process-stage` | **Administrative process stage.** A governed phase or status in an administrative workflow. | Unified Agenda stage; OIRA review stage; comment-period state; adjudication or publication phase. | Regulatory action; date alone; genre; informal progress wording not mapped to the named process scheme. | `document`, `container`, `event`, `externalReference` | All four core roles |
| `urn:ref:facet:code-list-value` | **Code-list value.** A member of a governed operational value set whose primary meaning is the source-defined code or status. | Source-native status, priority, category, flag, or enumerated value with an exact code-list release. | Free text; an identifier for a real-world entity; an industry classification; a concept promoted solely from a readable label. | `document`, `participation`, `container`, `entity`, `observation`, `event`, `externalReference` | All four core roles |
| `urn:ref:facet:ontology-class` | **Ontology class.** Class membership in an identified ontology when no more specific REF facet carries the intended distinction. | Exact ontology class IRI and release; evidence supports class membership. | Treating every RDF type as an enrichment result; a value that fits a more specific core facet; an ontology label used as a general subject without evidence. | `document`, `participation`, `container`, `entity`, `observation`, `event`, `externalReference` | All four core roles |
| `urn:ref:facet:observation-measure` | **Observation and measure.** A measured, counted, estimated, modeled, or otherwise observed value with its necessary type and context. | Amount, count, rate, burden, threshold, modeled estimate, unit-bearing quantity, or governed qualitative measure. | A code-list status with no measurement meaning; a topic about measurement; a number without its unit, measure type, or scope when those are required. | `document`, `participation`, `observation`, `event`, `externalReference` | All four core roles |

**REF-ENR-PROFILE-001:** A producer using this profile MUST use the facet IRIs
in the table exactly. A local label, database column, or vocabulary identifier
MUST NOT replace a facet IRI in an exchange record.

**REF-ENR-PROFILE-002:** Every candidate, decision, permission row, gold
expectation, evaluation measure, and accepted enrichment result MUST identify
exactly one facet for the role being evaluated. A target MAY have separate
results in several facets when each result has independent evidence and
permission.

**REF-ENR-PROFILE-003:** A producer MUST check the target's route and the exact
facet-and-role pair against this profile and its `OutputProfile`. Route
compatibility, facet compatibility, and role compatibility do not imply one
another.

## 4. Open-label modes

This profile defines two open-label modes:

| Mode | Required behavior |
| --- | --- |
| `explicitLanguage` | The candidate supplies a valid BCP 47 language tag, including its script subtag when material, and the accepted Rulespec value preserves that complete tag without copying script into a parallel authored field. |
| `declaredDefaultLanguage` | The permission row declares one BCP 47 default language. If the accepted candidate lacks a tag, the producer materializes that declared tag into the final Rulespec value before validation. |

Both modes produce a language-tagged Rulespec value. Neither mode permits an
untagged or `@none` value. The tag `und` is permitted only when the language is
genuinely unknown; it is not a substitute for an omitted default or failed
language detection.

**REF-ENR-PROFILE-004:** An accepted open label MUST use one authorized mode
and MUST satisfy the `rkaf:openLabel`, `rkaf:openLabelFacet`, and
`rkaf:openLabelRole` rules in the RefSpec Rulespec Application Profile.

## 5. Extension and ontology behavior

These facets are operational partitions for candidate generation, evaluation,
and output authorization. They are not OWL classes.

**REF-ENR-PROFILE-005:** An implementation MUST NOT publish global OWL
disjointness axioms between the twelve facet IRIs. A resource can participate
in more than one facet through separate, evidence-bound assertions, and
external ontologies can have different class boundaries.

**REF-ENR-PROFILE-006:** An extension profile MAY define another facet only
when none of the twelve core definitions preserves a material distinction. The
new facet MUST use an absolute IRI, state its boundary from every overlapping
core facet, list inclusion and exclusion cues, list compatible routes and
assignment roles, and provide wrong-facet and round-trip fixtures. It MUST NOT
weaken an applicable core or Rulespec requirement.
