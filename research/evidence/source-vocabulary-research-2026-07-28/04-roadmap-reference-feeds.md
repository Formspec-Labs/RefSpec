<!-- markdownlint-disable MD013 MD060 -->

# Roadmap Feed and Reference-Spine Research

> **Status:** External research; proposed decisions, not adopted dependencies
>
> **Checked:** 2026-07-28
>
> **Scope:** Named feeds and reference spines in the
> [source and document type matrix](../../source-document-type-matrix-2026-07-28.md)

## Why this report exists

The original vocabulary research produced three domain reports: regulatory and
legal; legislative and fiscal; and health, social services, and specialist
domains. During an independent review of the combined catalog, the
`catalog_validation` agent found a separate gap. The source matrix named seven
provider feeds and reference spines, but the catalog did not state who
maintained them, whether they were authoritative, how an implementation could
access them, or what licensing and verification gates applied.

The primary Codex agent asked `catalog_validation` to research those seven
providers as a follow-up. The agent returned its findings in the conversation;
the primary agent edited and saved them here as report 04. This report is
therefore a later validation artifact, not one of the three original domain
reports and not a recovered Claude research report.

The report remains separate because these providers support discovery, gap
filling, or identity matching. They do not supply the vocabularies, ontologies,
or thesauri evaluated in reports 01–03. This file preserves the provider-level
evidence behind the catalog's roadmap-feed decisions without confusing those
services with subject authorities.

## Decision

OpenFEC is the only authoritative government source in this group. Use the
other services for discovery, coverage gaps, or identity hints, then verify
material facts against the responsible government publisher. None of these
providers supplies a canonical RefSpec subject vocabulary.

## Provider findings

| Provider | Maintainer, authority, and maintenance | Access and rights | Implementation role | Required gate or uncertainty |
| --- | --- | --- | --- | --- |
| [America's Data Index](https://dataindex.us/about-us) | Collaborative project with a named core team, but no legal owner was identified. It aggregates Office of Management and Budget Information Collection Requests; [2026 records and news](https://dataindex.us/newsletter/article/03771180-a973-4f2c-8f6b-a73ba52896b2) showed active maintenance. RegInfo.gov remains authoritative. | Filtered website and [CSV download](https://www.dataindex.us/icr/concluded). Code is GPLv3; site content is CC BY-SA 4.0. The research did not verify that the content license clearly covers every exported record. | `T2-03` monitoring and discovery for information collections | Use for alerts and retrieval only. Verify accepted records against RegInfo.gov; retain the official Information Collection Request identifier and URL; pin each CSV capture and schema. Legal maintainer, stable API, documented schema, and export rights remain unverified. |
| [EveryCRSReport](https://www.everycrsreport.com/about.html) | Managed by the American Governance Institute; originally created by the Congressional Data Coalition, with technical maintenance credited to Josh Tauberer. It is not the Congressional Research Service or Library of Congress. The inventory included reports through 2026-07-24. | [CSV inventory, per-report JSON, PDF, HTML, RSS, historical versions, and SHA-1 digests](https://www.everycrsreport.com/download.html). Congressional Research Service government works may generally be reproduced, but embedded third-party material can require separate permission. | `T2-10` historical and full-text gap fill for Congressional Research Service reports | Verify current edition and status against Congress.gov or the official Congressional Research Service portal. Preserve report version, retrieval source, and digest. Do not treat site topics as official Congressional Research Service assignments. No formal service level or update schedule was verified. |
| [`unitedstates/congress-legislators`](https://github.com/unitedstates/congress-legislators) | Community-maintained volunteer project, not Congress. It reconciles GovTrack, BioGuide, and official sources. The repository had active July 2026 commits and was not archived. | YAML sources with generated JSON and CSV for current and historical legislators, terms, committees, and memberships; [CC0 1.0](https://raw.githubusercontent.com/unitedstates/congress-legislators/main/LICENSE). | `T2-11` identifier and historical-term reference spine | Pin the repository commit and retrieval date; load current and historical files; verify active office, term, and committee membership against BioGuide, Congress.gov, or chamber sources. Never resolve identity from a name or third-party identifier alone. |
| [Open States people](https://github.com/openstates/people) | Maintained by Plural Open and contributors, not by state legislatures. Active automated and manual updates continued in July 2026. | Jurisdiction-organized YAML under CC0, plus keyed JSON through the [API](https://docs.openstates.org/api-v3/) and bulk downloads. API use also follows [Plural's terms](https://open.pluralpolicy.com/tos/). | `T1-05`, `T2-11`, and `T3-04` state-person and organization reference data | Prefer a pinned repository snapshot. Retain provider ID, jurisdiction, role dates, and upstream URLs. Verify active memberships and committee assignments against state sites. No published refresh service level or exact bulk refresh cadence was verified. |
| [ProPublica Nonprofit Explorer](https://projects.propublica.org/nonprofits/api/) | ProPublica aggregates Internal Revenue Service organization and Form 990 data plus Federal Audit Clearinghouse records; those agencies remain authoritative. The service says it [updates monthly](https://projects.propublica.org/nonprofits/contact). | Unauthenticated REST JSON/JSONP search and Employer Identification Number endpoints, filing links, and rate-limited PDFs. [Data terms](https://projects.propublica.org/datastore/terms/) require attribution and prohibit republishing the raw dataset in whole or part as a standalone product. | `T3-04` external nonprofit identity and filing reference keyed by Employer Identification Number | Retain identifier, API version, retrieval date, match evidence, and provider URL. Verify legal status and filing facts against Internal Revenue Service or Federal Audit Clearinghouse data. Do not mirror the corpus or treat name-search rank as identity proof. |
| [OpenFEC](https://api.open.fec.gov/developers/) | Federal Election Commission service and the authoritative source in this group for federal campaign-finance filings and identifiers. Data update nightly; the [official repository](https://github.com/fecgov/openFEC) was active through 2026-07-27. | API-keyed REST JSON, Swagger schema, and [bulk downloads](https://www.fec.gov/data/browse-data/?tab=bulk-data). Government code and data are generally public domain or CC0, subject to third-party components and statutory data restrictions. | `C10` and `T3-04` authoritative candidate, committee, filing, and cycle-specific classifications | Key records by Federal Election Commission identifier plus cycle or effective dates; keep candidates, committees, and connected organizations separate; pin response and schema metadata. Enforce the [sale-and-use restriction](https://www.fec.gov/updates/sale-or-use-contributor-information/) on individual contributor information. |
| [LegiScan](https://legiscan.com/legiscan/) | LegiScan LLC is a commercial aggregator for Congress and all states, not a legislative authority. [Weekly datasets](https://legiscan.com/datasets) reached 2026-07-26; paid services update more often. | API-keyed JSON and weekly JSON/CSV datasets. Public API and public datasets are [CC BY 4.0](https://legiscan.com/services/); paid tiers can use other licenses and all access follows the [service terms](https://legiscan.com/terms-of-service/). | `T1-05` and `T2-11` state-bill gap fill when primary feeds or Open States lack coverage | Preserve LegiScan ID, official source URL, session, status, retrieval time, and dataset version. Verify status and text against the legislature before user-facing claims. Do not treat provider subjects as a national authority. Confirm redistribution terms for the exact service tier. |

## Boundary

These services can point to a source, add an identifier, or fill a documented
coverage gap. They do not turn a provider's search result, normalized label, or
modeled relationship into source-assigned evidence. The acquisition receipt
must record both the provider record and the official verification source.
