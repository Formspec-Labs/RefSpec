# LDA controlled-list development packages

This evidence directory contains two separate source-controlled-resource
packages built from the official Lobbying Disclosure Act (LDA) constants API
on 30 July 2026.

| Package | Product role | Members | Source SHA-256 | Logical package SHA-256 |
| --- | --- | ---: | --- | --- |
| `general-issue-codes` | Source-assigned filing evidence | 79 | `e1820ef17f3e63048ae50e526c2f56e507b2cf60d720fc227c76ee7c3610d5bf` | `8a1c3e4db6fcec803463dd96a6d5231022841c291315ff624827db798cfdf40a` |
| `filing-types` | Deterministic filing metadata | 50 | `49fbd39383b0be63fb474878aa229d4e397880a30c2e0dac1a0905bc660a3149` | `6b05bd1ce95fcf2f62a9e627fb69233eb2fce48176bdd08011247c7384009ecc` |

Each package retains the exact official JSON bytes, one observation for every
published code and label, structured publisher identifiers, source paths,
source digests, and complete source-to-package counts. The closed package
manifest pins every artifact.

The packages state factual intended uses and claim no concept identity. Exact
product policy governs operational use. The filing-type package does not
invent a separate filing status from status-like wording in a type label.

Known publisher gaps remain explicit in `coverage-report.json`: neither
constants endpoint publishes a named code-list release or revision; the API
publishes no standalone filing-status list; and filing periods are an OpenAPI
enum rather than an independent constants list.
