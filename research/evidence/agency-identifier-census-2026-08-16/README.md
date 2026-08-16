# Agency identifier census — 2026-08-16

REF-038 first measures exact publisher-identifier equality across five agency rosters without name similarity or identifier normalization. It then layers per-value E4 review over the 52-value residue. The adjacent `census.json` contains both passes.

## Roster and identifier census

| Roster | Resources | Relations | Parent relations | Distinct parents | Other relations | Cross-ring |
| --- | --- | --- | --- | --- | --- | --- |
| federal-register-agencies | 472 | 225 | 225 | 24 | 0 | 0 |
| federal-hierarchy-organizations | 907 | 86200 | 738 | 166 | 85462 | 0 |
| opm-ehri-agency-subelement | 798 | 0 | 0 | 0 | 0 | 0 |
| ecfr-agencies | 316 | 163 | 163 | 21 | 0 | 446 |
| regulations-gov-agencies | 331 | 160 | 160 | 17 | 0 | 0 |

### Identifier kinds

| Roster | Identifier kind | Resources | Claims | Distinct | Collision values |
| --- | --- | --- | --- | --- | --- |
| federal-register-agencies | federalRegisterNumericId | 472 | 472 | 472 | 0 |
| federal-register-agencies | federalRegisterSlug | 472 | 472 | 472 | 0 |
| federal-register-agencies | federalRegisterShortName | 472 | 419 | 409 | 10 |
| federal-hierarchy-organizations | federalHierarchyOrganizationId | 907 | 907 | 907 | 0 |
| federal-hierarchy-organizations | fpdsAgencyCode | 907 | 906 | 743 | 162 |
| federal-hierarchy-organizations | cgacAgencyIdentifier | 907 | 908 | 143 | 141 |
| federal-hierarchy-organizations | legacyFpdsOfficeCode | 907 | 472 | 463 | 9 |
| opm-ehri-agency-subelement | opmEhriAgencySubelementCode | 798 | 798 | 798 | 0 |
| ecfr-agencies | ecfrAgencySlug | 316 | 316 | 316 | 0 |
| ecfr-agencies | ecfrAgencyShortName | 316 | 242 | 241 | 1 |
| regulations-gov-agencies | regulationsGovAgencyId | 331 | 331 | 331 | 0 |

## Cross-roster exact equality

| Left kind | Right kind | Disposition | Shared values | Edges | Unambiguous | Ambiguous |
| --- | --- | --- | --- | --- | --- | --- |
| federalRegisterNumericId | cgacAgencyIdentifier | refusedDifferentIdentifierAuthorities | 52 | 126 | 1 | 51 |
| federalRegisterSlug | ecfrAgencySlug | refusedDifferentIdentifierAuthorities | 252 | 252 | 252 | 0 |
| federalRegisterShortName | opmEhriAgencySubelementCode | refusedDifferentIdentifierAuthorities | 3 | 3 | 3 | 0 |
| federalRegisterShortName | ecfrAgencyShortName | admissibleE4AcronymAdjudication | 238 | 249 | 229 | 9 |
| federalRegisterShortName | regulationsGovAgencyId | admissibleE4AcronymAdjudication | 279 | 287 | 271 | 8 |
| opmEhriAgencySubelementCode | ecfrAgencyShortName | refusedDifferentIdentifierAuthorities | 3 | 3 | 3 | 0 |
| opmEhriAgencySubelementCode | regulationsGovAgencyId | refusedDifferentIdentifierAuthorities | 3 | 3 | 3 | 0 |
| ecfrAgencyShortName | regulationsGovAgencyId | admissibleE4AcronymAdjudication | 200 | 201 | 199 | 1 |

### Ambiguities

- `federalRegisterNumericId` = `cgacAgencyIdentifier`: `164` (1×2), `235` (1×2), `290` (1×2), `292` (1×2), `302` (1×2), `306` (1×2), `309` (1×2), `321` (1×2), `326` (1×2), `345` (1×2), `347` (1×2), `349` (1×2), `352` (1×10), `362` (1×4), `364` (1×3), `368` (1×2), `372` (1×2), `373` (1×2), `376` (1×6), `381` (1×2), `382` (1×2), `387` (1×2), `389` (1×2), `394` (1×2), `413` (1×2), `431` (1×2), `456` (1×2), `458` (1×2), `465` (1×2), `467` (1×5), `471` (1×2), `472` (1×2), `473` (1×2), `474` (1×2), `476` (1×2), `487` (1×2), `510` (1×2), `511` (1×7), `512` (1×2), `513` (1×2), `519` (1×2), `524` (1×2), `525` (1×2), `539` (1×2), `542` (1×2), `573` (1×2), `574` (1×2), `575` (1×2), `576` (1×2), `581` (1×2), `584` (1×2)
- `federalRegisterShortName` = `ecfrAgencyShortName`: `ARC` (2×1), `DOE` (2×1), `DOL` (2×1), `EAB` (2×1), `FS` (2×2), `IIO` (2×1), `LOC` (2×1), `OFR` (2×1), `PRC` (2×1)
- `federalRegisterShortName` = `regulationsGovAgencyId`: `DOE` (2×1), `DOL` (2×1), `EAB` (2×1), `FS` (2×1), `IIO` (2×1), `LOC` (2×1), `OFR` (2×1), `PRC` (2×1)
- `ecfrAgencyShortName` = `regulationsGovAgencyId`: `FS` (2×1)

## regulations.gov first-pass coverage and residue

- Total agency ids: 331
- At least one unambiguous admitted identifier path: 279
- Values requiring per-value review: 52
- Residue values: `ACL`, `ADF`, `AID`, `ARCTICGAS`, `ASC`, `ATR`, `BSC`, `CDFIF`, `CISA`, `CNCS`, `COFA`, `CORP`, `CROMFS`, `DBCRC`, `DEPO`, `EERE`, `EIB`, `EOA`, `ESA`, `FINCEN`, `FIRSTNET`, `FISCAL`, `FPAC`, `FPPO`, `FR`, `FS`, `GAPFAC`, `GCERC`, `GEO`, `HHSIG`, `HPAC`, `ICEB`, `MCRMC`, `MEXICO`, `MKU`, `MMA`, `MPAC`, `NCC`, `NCRIRS`, `NEO`, `NRPC`, `NSPC`, `OIRA`, `PCSCOTUS`, `PRES`, `RUF`, `SS`, `TRADE`, `USC`, `USDAIG`, `USEIB`, `WCPO`

An equality marked `admissibleE4AcronymAdjudication` is evidence input, not a publisher assertion. REF-038 requires the asserted mapping release to retain the E4 tier, adjudication warrant, basis, and source records. All other equal strings remain refused coincidences between different identifier authorities.

The identifier census above is unchanged. The next section is a second pass over its 52-value residue and does not alter the exact-equality measurements.

## Per-value residue adjudication

The owner ruling adopts 42 obvious identities and abstains on 10 values for which no held roster contains the same entity. The final split is 321 resolved and 10 abstained.

| regulations.gov id | Publisher name | Decision | Basis or reason | Counterpart |
| --- | --- | --- | --- | --- |
| ACL | Administration for Community Living | adopted | obviousPublisherNameVariant | ADMINISTRATION FOR COMMUNITY LIVING (ACL) (`urn:ref:federal-hierarchy-org:100525875`) |
| ADF | African Development Foundation | adopted | exactPublisherNameEquality | African Development Foundation (`urn:ref:ecfr-agency:african-development-foundation`) |
| AID | U.S. Agency for International Development | adopted | obviousPublisherNameVariant | Agency for International Development (`urn:ref:federal-register-agency:6`) |
| ARCTICGAS | Office of the Federal Coordinator for Alaska Natural Gas Transportation Projects | abstained | noCounterpartInHeldRosters | ABSTAIN; closest: OFF OF THE FED INSPECTOR FOR THE AK NATURAL GAS TRANSPORT (`urn:ref:federal-hierarchy-org:300000035`) |
| ASC | Appraisal Subcommittee | adopted | obviousPublisherNameVariant | Appraisal Subcommittee of the Federal Financial Institutions Examination Council (`urn:ref:federal-register-agency:621`) |
| ATR | Antitrust Division | adopted | exactPublisherNameEquality | Antitrust Division (`urn:ref:federal-register-agency:23`) |
| BSC | Business Standards Council | abstained | noCounterpartInHeldRosters | ABSTAIN; no candidate |
| CDFIF | Community Development Financial Institutions Fund Np | adopted | obviousPublisherNameVariant | Community Development Financial Institutions Fund (`urn:ref:federal-register-agency:78`) |
| CISA | Cybersecurity and Infrastructure Security Agency | adopted | exactPublisherNameEquality | Cybersecurity and Infrastructure Security Agency (`urn:ref:federal-hierarchy-org:500044551`) |
| CNCS | Corporation for National and Community Service | adopted | exactPublisherNameEquality | Corporation for National and Community Service (`urn:ref:federal-register-agency:91`) |
| COFA | Commission of Fine Arts | adopted | exactPublisherNameEquality | Commission of Fine Arts (`urn:ref:federal-register-agency:57`) |
| CORP | Corporation for National and Community Service | adopted | exactPublisherNameEquality | Corporation for National and Community Service (`urn:ref:federal-register-agency:91`) |
| CROMFS | Commission on Review of Overseas Military Facility Structure of the United States | adopted | exactPublisherNameEquality | Commission on Review of Overseas Military Facility Structure of the United States (`urn:ref:federal-register-agency:67`) |
| DBCRC | Defense Base Closure and Realignment Commission | adopted | exactPublisherNameEquality | Defense Base Closure and Realignment Commission (`urn:ref:federal-register-agency:99`) |
| DEPO | Disability Employment Policy Office | adopted | exactPublisherNameEquality | Disability Employment Policy Office (`urn:ref:federal-register-agency:115`) |
| EERE | Energy Efficiency and Renewable Energy Office | adopted | exactPublisherNameEquality | Energy Efficiency and Renewable Energy Office (`urn:ref:federal-register-agency:137`) |
| EIB | Export Import Bank of the United States | adopted | obviousPublisherNameVariant | Export-Import Bank of the United States (`urn:ref:ecfr-agency:export-import-bank`) |
| EOA | Energy Office, Agriculture Department | abstained | noCounterpartInHeldRosters | ABSTAIN; closest: Energy Policy and New Uses Office (`urn:ref:federal-register-agency:536`) |
| ESA | Employment Standards Administration | adopted | exactPublisherNameEquality | Employment Standards Administration (`urn:ref:federal-register-agency:134`) |
| FINCEN | Financial Crimes Enforcement Network | adopted | exactPublisherNameEquality | Financial Crimes Enforcement Network (`urn:ref:federal-register-agency:194`) |
| FIRSTNET | First Responder Network Authority | adopted | exactPublisherNameEquality | First Responder Network Authority (`urn:ref:federal-register-agency:584`) |
| FISCAL | Fiscal Service | adopted | exactPublisherNameEquality | Fiscal Service (`urn:ref:federal-register-agency:585`) |
| FPAC | Farm Production and Conservation Business Center | adopted | exactPublisherNameEquality | Farm Production and Conservation Business Center (`urn:ref:federal-register-agency:619`) |
| FPPO | Federal Procurement Policy Office | adopted | exactPublisherNameEquality | Federal Procurement Policy Office (`urn:ref:federal-register-agency:184`) |
| FR | Office of Federal Register | adopted | exactPublisherNameEquality | Office of Federal Register (`urn:ref:ecfr-agency:federal-register-office`) |
| FS | Forest Service | adopted | publisherNameWithParentContext | Forest Service (`urn:ref:federal-register-agency:209`) |
| GAPFAC | Gsa Acquisition Policy Federal Advisory Committee | abstained | noCounterpartInHeldRosters | ABSTAIN; no candidate |
| GCERC | Gulf Coast Ecosystem Restoration Council | adopted | exactPublisherNameEquality | Gulf Coast Ecosystem Restoration Council (`urn:ref:federal-register-agency:583`) |
| GEO | Government Ethics Office | adopted | exactPublisherNameEquality | Government Ethics Office (`urn:ref:federal-register-agency:215`) |
| HHSIG | Inspector General Office, Health and Human Services Department | adopted | acronymExpansionWithNameAndParentContext | OFFICE OF THE INSPECTOR GENERAL (`urn:ref:federal-hierarchy-org:100004455`) |
| HPAC | Historic Preservation, Advisory Council | adopted | obviousPublisherNameVariant | Advisory Council on Historic Preservation (`urn:ref:federal-register-agency:225`) |
| ICEB | Immigration and Customs Enforcement Bureau | adopted | acronymExpansionWithNameAndParentContext | U.S. IMMIGRATION AND CUSTOMS ENFORCEMENT (`urn:ref:federal-hierarchy-org:100012075`) |
| MCRMC | Military Compensation and Retirement Modernization Commission | adopted | exactPublisherNameEquality | Military Compensation and Retirement Modernization Commission (`urn:ref:federal-register-agency:582`) |
| MEXICO | U.S. International Boundary and Water Commission | adopted | obviousPublisherNameVariant | United States Section United States and Mexico International Boundary and Water Commission (`urn:ref:ecfr-agency:international-boundary-and-water-commission-united-states-and-mexico`) |
| MKU | Morris K. Udall Scholarship and Excellence in National Environmental Policy Foundation | adopted | obviousPublisherNameVariant | MORRIS K. UDALL SCHOLARSHIP AND EXCELLENCE IN NATIONAL ENVIRONMENTAL POLICY FOUNDATION (`urn:ref:federal-hierarchy-org:300000070`) |
| MMA | Marine Minerals Administration | abstained | noCounterpartInHeldRosters | ABSTAIN; closest: Minerals Management Service (`urn:ref:federal-register-agency:289`) |
| MPAC | Medicare Payment Advisory Commission | adopted | exactPublisherNameEquality | Medicare Payment Advisory Commission (`urn:ref:federal-register-agency:284`) |
| NCC | National Counterintelligence Center | adopted | exactPublisherNameEquality | National Counterintelligence Center (`urn:ref:federal-register-agency:334`) |
| NCRIRS | National Commission on Restructuring the Internal Revenue Service | abstained | noCounterpartInHeldRosters | ABSTAIN; closest: Internal Revenue Service (`urn:ref:federal-register-agency:254`) |
| NEO | Nuclear Energy Office | adopted | exactPublisherNameEquality | Nuclear Energy Office (`urn:ref:federal-register-agency:382`) |
| NRPC | National Railroad Passenger Corporation | adopted | exactPublisherNameEquality | National Railroad Passenger Corporation (`urn:ref:federal-register-agency:365`) |
| NSPC | National Space Council | adopted | exactPublisherNameEquality | National Space Council (`urn:ref:federal-register-agency:612`) |
| OIRA | Office of Information and Regulatory Affairs | abstained | noCounterpartInHeldRosters | ABSTAIN; closest: Management and Budget Office (`urn:ref:federal-register-agency:391`) |
| PCSCOTUS | Presidential Commission on the Supreme Court of the United States | abstained | noCounterpartInHeldRosters | ABSTAIN; closest: SUPREME COURT OF THE UNITED STATES (`urn:ref:federal-hierarchy-org:300000011`) |
| PRES | Presidential Documents | abstained | noCounterpartInHeldRosters | ABSTAIN; closest: PRESIDENT OF THE UNITED STATES (`urn:ref:federal-hierarchy-org:100525435`) |
| RUF | Reagan Udall Foundation | adopted | obviousPublisherNameVariant | Reagan-Udall Foundation for the Food and Drug Administration (`urn:ref:federal-register-agency:445`) |
| SS | Secret Service | adopted | exactPublisherNameEquality | Secret Service (`urn:ref:federal-register-agency:465`) |
| TRADE | Trade and Development Agency | adopted | exactPublisherNameEquality | Trade and Development Agency (`urn:ref:federal-register-agency:490`) |
| USC | United States Courts | abstained | noCounterpartInHeldRosters | ABSTAIN; closest: Administrative Office of United States Courts (`urn:ref:federal-register-agency:3`) |
| USDAIG | Inspector General Office, Agriculture Department | adopted | acronymExpansionWithNameAndParentContext | OFFICE OF INSPECTOR GENERAL (`urn:ref:federal-hierarchy-org:100006936`) |
| USEIB | Export-import Bank | adopted | obviousPublisherNameVariant | Export-Import Bank (`urn:ref:federal-register-agency:151`) |
| WCPO | Workers Compensation Programs Office | adopted | obviousPublisherNameVariant | Workers' Compensation Programs Office (`urn:ref:federal-register-agency:530`) |

Each adoption records both publisher names, its closed-vocabulary basis, reviewer, decision time, and a specific reasoning sentence in `census.json` and the mapping release. Abstentions use `noCounterpartInHeldRosters` and record the closest rejected candidate when one exists.

Identifier census digest: `sha256:98ee78e352f019a4b33090f0397fdf145c6876d7f6033508172db144912d9420`
Adjudication digest: `sha256:96251493ee0d98d5f7b450148e6cb95ca94cd757d588a5bf99acc3b6c10ad128`

Reproduce with `uv run python tools/analyze_agency_roster_identifiers.py --check`.
