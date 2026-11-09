<!-- markdownlint-disable MD013 -->

# Agency registry alias batch — owner adjudication sheet

Generated from [agency-registry-alias-batch-candidates.json](agency-registry-alias-batch-candidates.json) and [agency-registry-alias-batch-decisions.json](agency-registry-alias-batch-decisions.json) by `tools/assemble_agency_registry_alias_batch.py`; its default run fails if this sheet disagrees with either. **Do not edit this sheet.** You (reviewer `urn:ref:reviewer:refspec-owner`) answer through the question tool or by editing the decisions file, exactly as for batch 1: each decision is keyed by the alias id and records the answer, the date, the channel and the item's `content_digest` (the Decision keys table). Every row is `candidate-pending-owner-adjudication`. The plan this batch serves is [agency-registry-alias-plan.md](agency-registry-alias-plan.md).

Decisions recorded: 0 current, 0 stale, 70 of 70 undecided. Candidates digest `sha256:50accf3794b1a0fdc1a27753af3ecba44052a893f3ad8de261df34e54290cd1b`; demand evidence `research/evidence/agency-alias-demand-2026-11-08/federal-misses.json` (`sha256:48d323915e517163e05166167eebce089043a3b4e65f13ea65b218f0a5eb2676`).

**Demand.** congressional-tech's 3,662 federal-typed witness appearances: 2,193 already match a pinned FR name or short name, 327 name no organization, and the rest split into 573 distinct unmatched keys. 130 keys pass the thresholds (3 federal appearances, or 25 of any witness type), and each is below exactly once: 12 mechanical, 58 judgment, 1 already resolvable, 59 excluded. Counts read federal / all.

**How to answer fast.** Every row carries a recommended answer and its reason. Answering every row with its recommendation is one instruction ("accept the recommendations"), and any row can be answered otherwise by id. A part-of row resolves an FR-keyed consumer to the FR record the unit sits in and claims no identity; where same-or-part-of is unclear the sheet recommends part-of, because the FR id is the same and nothing is claimed.

## Mechanical (12) — recommended: yes to all

Each follows from the pinned rosters by a stated rule and needs no hand input: `frShortNameEquality` (the FR record's short name), `frNameWordOrder` (its name with the trailing organization word moved to the front), `reviewedIdentityPublisherName` (the name of a regulations.gov record REF-038's reviewed identity maps to exactly this FR record).

| Id | Spellings seen | Demand | Resolves to | Basis | Decision |
| --- | --- | --- | --- | --- | --- |
| `alias:bureau-of-land-management` | Bureau of Land Management (18); U.S. Bureau of Land Management (1); United States Bureau of Land Management (1) | 20 / 50 | FR 275 Land Management Bureau | `frNameWordOrder`, `reviewedIdentityPublisherName` | undecided |
| `alias:bureau-of-reclamation` | U.S. Bureau of Reclamation (11); Bureau of Reclamation (4) | 15 / 49 | FR 446 Reclamation Bureau | `frNameWordOrder`, `reviewedIdentityPublisherName` | undecided |
| `alias:office-of-director-of-national-intelligence` | Office of the Director of National Intelligence (13) | 13 / 93 | FR 354 National Intelligence, Office of the National Director | `reviewedIdentityPublisherName` | undecided |
| `alias:office-of-management-and-budget` | Office of Management and Budget (8); U.S. Office of Management and Budget (2); The Office of Management and Budget (1) | 11 / 252 | FR 280 Management and Budget Office | `frNameWordOrder`, `reviewedIdentityPublisherName` | undecided |
| `alias:bureau-of-ocean-energy-management` | Bureau of Ocean Energy Management (10) | 10 / 19 | FR 575 Ocean Energy Management Bureau | `frNameWordOrder`, `reviewedIdentityPublisherName` | undecided |
| `alias:bureau-of-safety-and-environmental-enforcement` | Bureau of Safety and Environmental Enforcement (9) | 9 / 11 | FR 576 Safety and Environmental Enforcement Bureau | `frNameWordOrder`, `reviewedIdentityPublisherName` | undecided |
| `alias:office-of-special-counsel` | Office of Special Counsel (3); U.S. Office of Special Counsel (3) | 6 / 31 | FR 473 Special Counsel Office | `frNameWordOrder`, `reviewedIdentityPublisherName` | undecided |
| `alias:bureau-of-indian-affairs` | Bureau of Indian Affairs (4) | 4 / 14 | FR 234 Indian Affairs Bureau | `frNameWordOrder`, `reviewedIdentityPublisherName` | undecided |
| `alias:office-of-personnel-management` | U.S. Office of Personnel Management (3) | 3 / 138 | FR 406 Personnel Management Office | `frNameWordOrder`, `reviewedIdentityPublisherName` | undecided |
| `alias:office-of-surface-mining-reclamation-and-enforcement` | Office of Surface Mining Reclamation and Enforcement (3) | 3 / 8 | FR 480 Surface Mining Reclamation and Enforcement Office | `frNameWordOrder`, `reviewedIdentityPublisherName` | undecided |
| `alias:office-of-science-and-technology-policy` | Office of Science and Technology Policy (2) | 2 / 35 | FR 464 Science and Technology Policy Office | `frNameWordOrder`, `reviewedIdentityPublisherName` | undecided |
| `alias:copyright-office` | U.S. Copyright Office (1); United States Copyright Office (1) | 2 / 27 | FR 87 Copyright Office, Library of Congress | `reviewedIdentityPublisherName` | undecided |

## Judgment (58)

Records marked unread are cited, not yet retained; the release step refuses an adopted row until its records are read (plan section 4).

### `alias:veterans-health-administration` — Veterans Health Administration (49); (VISN 17) Veterans Health Administration (1); Veterans Health Administration (VHA) (1)

| Field | Value |
| --- | --- |
| Demand (federal / all) | 51 / 238 |
| Names | OPM `VATA` VETERANS HEALTH ADMINISTRATION |
| FR-keyed consumers get | FR 520 Veterans Affairs Department (part of) |
| Basis | `unitWithinFrAgency` |
| Reasoning | VHA is an administration of the Department of Veterans Affairs; OPM holds it as VATA, the FR does not. |
| Records | [38 U.S.C. 7301](https://uscode.house.gov/view.xhtml?req=granuleid:USC-prelim-title38-section7301&num=0&edition=prelim) (unread) |
| Answers | `yes` / `no` |
| Recommended | **yes** — The unit has no FR record; a part-of row gives the FR id of the organization it sits in, and claims no identity. |
| Owner decision / date | undecided |

### `alias:army` — U.S. Army (23); United States Army (20)

| Field | Value |
| --- | --- |
| Demand (federal / all) | 43 / 348 |
| Names | none held |
| FR-keyed consumers get | FR 32 Army Department (part of) |
| Basis | `militaryServiceOfDepartment` |
| Reasoning | The Army is the service the Department of the Army (FR 32, 'Army Department') organizes; OPM's AR is the department, not the service. |
| Records | [10 U.S.C. 7062](https://uscode.house.gov/view.xhtml?req=granuleid:USC-prelim-title10-section7062&num=0&edition=prelim) (unread) |
| Answers | `1` Yes, as the same organization: the alias resolves to the FR department record with no qualifier. / `2` Yes, as part of it: the alias resolves to the FR department record, marked part-of (the service is the department's uniformed component). / `3` No alias. |
| Recommended | **2** — Option 2 gives the consumer the same FR id as option 1 without claiming the service and the department are one organization; the department also holds civilian offices the service is not. |
| Owner decision / date | undecided |

### `alias:navy` — United States Navy (25); U.S. Navy (18)

| Field | Value |
| --- | --- |
| Demand (federal / all) | 43 / 293 |
| Names | none held |
| FR-keyed consumers get | FR 378 Navy Department (part of) |
| Basis | `militaryServiceOfDepartment` |
| Reasoning | The Navy is a service of the Department of the Navy (FR 378, 'Navy Department'), which also holds the Marine Corps. |
| Records | [10 U.S.C. 8062](https://uscode.house.gov/view.xhtml?req=granuleid:USC-prelim-title10-section8062&num=0&edition=prelim) (unread) |
| Answers | `1` Yes, as the same organization: the alias resolves to the FR department record with no qualifier. / `2` Yes, as part of it: the alias resolves to the FR department record, marked part-of (the service is the department's uniformed component). / `3` No alias. |
| Recommended | **2** — Option 2 gives the consumer the same FR id as option 1 without claiming the service and the department are one organization; the department also holds civilian offices the service is not. |
| Owner decision / date | undecided |

### `alias:veterans-benefits-administration` — Veterans Benefits Administration (34)

| Field | Value |
| --- | --- |
| Demand (federal / all) | 34 / 165 |
| Names | OPM `VALA` VETERANS BENEFITS ADMINISTRATION |
| FR-keyed consumers get | FR 520 Veterans Affairs Department (part of) |
| Basis | `unitWithinFrAgency` |
| Reasoning | VBA is an administration of the Department of Veterans Affairs; OPM holds it as VALA. |
| Records | [38 U.S.C. 7701](https://uscode.house.gov/view.xhtml?req=granuleid:USC-prelim-title38-section7701&num=0&edition=prelim) (unread) |
| Answers | `yes` / `no` |
| Recommended | **yes** — The unit has no FR record; a part-of row gives the FR id of the organization it sits in, and claims no identity. |
| Owner decision / date | undecided |

### `alias:air-force` — United States Air Force (18); U.S. Air Force (14)

| Field | Value |
| --- | --- |
| Demand (federal / all) | 32 / 298 |
| Names | none held |
| FR-keyed consumers get | FR 13 Air Force Department (part of) |
| Basis | `militaryServiceOfDepartment` |
| Reasoning | The Air Force is a service of the Department of the Air Force (FR 13), which also holds the Space Force. |
| Records | [10 U.S.C. 9062](https://uscode.house.gov/view.xhtml?req=granuleid:USC-prelim-title10-section9062&num=0&edition=prelim) (unread) |
| Answers | `1` Yes, as the same organization: the alias resolves to the FR department record with no qualifier. / `2` Yes, as part of it: the alias resolves to the FR department record, marked part-of (the service is the department's uniformed component). / `3` No alias. |
| Recommended | **2** — Option 2 gives the consumer the same FR id as option 1 without claiming the service and the department are one organization; the department also holds civilian offices the service is not. |
| Owner decision / date | undecided |

### `alias:marine-corps` — United States Marine Corps (19); U.S. Marine Corps (11); Marine Corps (1)

| Field | Value |
| --- | --- |
| Demand (federal / all) | 32 / 253 |
| Names | OPM `NV27` U.S. MARINE CORPS |
| FR-keyed consumers get | FR 378 Navy Department (part of) |
| Basis | `militaryServiceOfDepartment` |
| Reasoning | The Marine Corps is a service within the Department of the Navy (FR 378); OPM holds it as NV27. |
| Records | [10 U.S.C. 8063](https://uscode.house.gov/view.xhtml?req=granuleid:USC-prelim-title10-section8063&num=0&edition=prelim) (unread) |
| Answers | `yes` / `no` |
| Recommended | **yes** — The unit has no FR record; a part-of row gives the FR id of the organization it sits in, and claims no identity. |
| Owner decision / date | undecided |

### `alias:congressional-research-service` — Congressional Research Service (27)

| Field | Value |
| --- | --- |
| Demand (federal / all) | 27 / 233 |
| Names | none held |
| FR-keyed consumers get | FR 277 Library of Congress (part of) |
| Basis | `unitWithinFrAgency` |
| Reasoning | CRS is a department of the Library of Congress (FR 277); no held roster holds it. |
| Records | [2 U.S.C. 166](https://uscode.house.gov/view.xhtml?req=granuleid:USC-prelim-title2-section166&num=0&edition=prelim) (unread) |
| Answers | `yes` / `no` |
| Recommended | **yes** — The unit has no FR record; a part-of row gives the FR id of the organization it sits in, and claims no identity. |
| Owner decision / date | undecided |

### `alias:office-of-secretary-of-defense` — Office of the Secretary of Defense (22)

| Field | Value |
| --- | --- |
| Demand (federal / all) | 22 / 107 |
| Names | OPM `DD01` OFFICE OF THE SECRETARY OF DEFENSE |
| FR-keyed consumers get | FR 103 Defense Department (part of) |
| Basis | `unitWithinFrAgency` |
| Reasoning | OSD is the Secretary's principal staff element in the Department of Defense (FR 103); OPM holds it as DD01. |
| Records | [10 U.S.C. 131](https://uscode.house.gov/view.xhtml?req=granuleid:USC-prelim-title10-section131&num=0&edition=prelim) (unread) |
| Answers | `yes` / `no` |
| Recommended | **yes** — The unit has no FR record; a part-of row gives the FR id of the organization it sits in, and claims no identity. |
| Owner decision / date | undecided |

### `alias:national-security-agency` — National Security Agency (15)

| Field | Value |
| --- | --- |
| Demand (federal / all) | 15 / 47 |
| Names | none held |
| FR-keyed consumers get | FR 367 National Security Agency/Central Security Service |
| Basis | `publisherNameVariant` |
| Reasoning | FR 367 is 'National Security Agency/Central Security Service'; the Federal Hierarchy names the same agency 'NATIONAL SECURITY AGENCY (NSA)' (300000420). |
| Records | the held roster records named |
| Answers | `yes` / `no` |
| Recommended | **yes** — Dropping the Central Security Service half of a dual-named agency names the same agency, as the Federal Hierarchy does. |
| Owner decision / date | undecided |

### `alias:army-corps-of-engineers` — U.S. Army Corps of Engineers (11); Army Corps of Engineers (1)

| Field | Value |
| --- | --- |
| Demand (federal / all) | 12 / 159 |
| Names | none held |
| FR-keyed consumers get | FR 142 Engineers Corps |
| Basis | `publisherNameVariant` |
| Reasoning | FR 142 is 'Engineers Corps'; eCFR's short name for the same corps is 'Army Corps of Engineers'. |
| Records | the held roster records named |
| Answers | `yes` / `no` |
| Recommended | **yes** — Another publisher's name for the FR record's organization. |
| Owner decision / date | undecided |

### `alias:board-of-governors-of-federal-reserve-system` — Board of Governors of the Federal Reserve System (9)

| Field | Value |
| --- | --- |
| Demand (federal / all) | 9 / 300 |
| Names | none held |
| FR-keyed consumers get | FR 188 Federal Reserve System (part of) |
| Basis | `unitWithinFrAgency` |
| Reasoning | FR 188 is 'Federal Reserve System'; eCFR holds the Board of Governors and the System as two records. |
| Records | [12 U.S.C. 241](https://uscode.house.gov/view.xhtml?req=granuleid:USC-prelim-title12-section241&num=0&edition=prelim) (unread) |
| Answers | `1` Yes, as the same organization as FR 188. / `2` Yes, as part of FR 188 (the System's governing board). / `3` No alias. |
| Recommended | **2** — Option 2 gives the same FR id without claiming the Board is the whole System, which eCFR keeps apart. |
| Owner decision / date | undecided |

### `alias:space-force` — United States Space Force (7); Space Force (1); U.S. Space Force (1)

| Field | Value |
| --- | --- |
| Demand (federal / all) | 9 / 41 |
| Names | OPM `AF4G` UNITED STATES SPACE FORCE |
| FR-keyed consumers get | FR 13 Air Force Department (part of) |
| Basis | `militaryServiceOfDepartment` |
| Reasoning | The Space Force is a service within the Department of the Air Force (FR 13); OPM holds it as AF4G. |
| Records | [10 U.S.C. 9081](https://uscode.house.gov/view.xhtml?req=granuleid:USC-prelim-title10-section9081&num=0&edition=prelim) (unread) |
| Answers | `yes` / `no` |
| Recommended | **yes** — The unit has no FR record; a part-of row gives the FR id of the organization it sits in, and claims no identity. |
| Owner decision / date | undecided |

### `alias:national-reconnaissance-office` — National Reconnaissance Office (7)

| Field | Value |
| --- | --- |
| Demand (federal / all) | 7 / 27 |
| Names | Federal Hierarchy `500019037` NATIONAL RECONNAISSANCE OFFICE (NRO) |
| FR-keyed consumers get | FR 103 Defense Department (part of) |
| Basis | `unitWithinFrAgency` |
| Reasoning | NRO is a Department of Defense agency; the Federal Hierarchy holds it as 500019037 ('NATIONAL RECONNAISSANCE OFFICE (NRO)'). |
| Records | the held roster records named |
| Answers | `yes` / `no` |
| Recommended | **yes** — The unit has no FR record; a part-of row gives the FR id of the organization it sits in, and claims no identity. |
| Owner decision / date | undecided |

### `alias:veterans-benefit-administration` — Veterans Benefit Administration (7)

| Field | Value |
| --- | --- |
| Demand (federal / all) | 7 / 8 |
| Names | none held |
| FR-keyed consumers get | FR 520 Veterans Affairs Department |
| Basis | `misspelling` |
| Reasoning | A misspelling of the Veterans Benefits Administration. |
| Records | the held roster records named |
| Answers | `yes` / `no` |
| Recommended | **no** — No publisher spells it so; a misspelling is the consumer's fuzzy matcher's job, not a reviewed alias. |
| Owner decision / date | undecided |

### `alias:export-import-bank-of` — Export-Import Bank of the United States (6)

| Field | Value |
| --- | --- |
| Demand (federal / all) | 6 / 51 |
| Names | none held |
| FR-keyed consumers get | FR 151 Export-Import Bank |
| Basis | `publisherNameVariant` |
| Reasoning | 'Export-Import Bank of the United States' is the statutory name of FR 151 ('Export-Import Bank'). |
| Records | [12 U.S.C. 635](https://uscode.house.gov/view.xhtml?req=granuleid:USC-prelim-title12-section635&num=0&edition=prelim) (unread) |
| Answers | `yes` / `no` |
| Recommended | **yes** — The statutory name of the FR record's organization. Batch 1's EIB/USEIB non-emission concerns an eCFR bridge, not this. |
| Owner decision / date | undecided |

### `alias:capitol-police` — United States Capitol Police (5); U.S. Capitol Police (1)

| Field | Value |
| --- | --- |
| Demand (federal / all) | 6 / 49 |
| Names | Federal Hierarchy `500193110` UNITED STATES CAPITOL POLICE |
| FR-keyed consumers get | no FR id |
| Basis | `noFrRecord` |
| Reasoning | The United States Capitol Police, a legislative-branch agency; the Federal Hierarchy holds it (500193110), the FR does not. |
| Records | the held roster records named |
| Answers | `yes` / `no` |
| Recommended | **yes** — Names the Federal Hierarchy record; an FR-keyed consumer gets no FR id, which is the truth. |
| Owner decision / date | undecided |

### `alias:strategic-command` — U.S. Strategic Command (4); United States Strategic Command (2)

| Field | Value |
| --- | --- |
| Demand (federal / all) | 6 / 39 |
| Names | none held |
| FR-keyed consumers get | FR 103 Defense Department (part of) |
| Basis | `unitWithinFrAgency` |
| Reasoning | U.S. Strategic Command; no held roster holds the command itself. |
| Records | [10 U.S.C. 161](https://uscode.house.gov/view.xhtml?req=granuleid:USC-prelim-title10-section161&num=0&edition=prelim) (unread) |
| Answers | `yes` / `no` |
| Recommended | **yes** — A combatant command is a Department of Defense component (10 U.S.C. 161) with no FR record; part-of DOD is the only FR resolution, and it claims no identity. |
| Owner decision / date | undecided |

### `alias:joint-staff` — The Joint Staff (4); Joint Staff (2)

| Field | Value |
| --- | --- |
| Demand (federal / all) | 6 / 33 |
| Names | none held |
| FR-keyed consumers get | FR 103 Defense Department (part of) |
| Basis | `unitWithinFrAgency` |
| Reasoning | The Joint Staff serves the Chairman of the Joint Chiefs of Staff in the Department of Defense; no held roster holds it alone. |
| Records | [10 U.S.C. 155](https://uscode.house.gov/view.xhtml?req=granuleid:USC-prelim-title10-section155&num=0&edition=prelim) (unread) |
| Answers | `yes` / `no` |
| Recommended | **yes** — The unit has no FR record; a part-of row gives the FR id of the organization it sits in, and claims no identity. |
| Owner decision / date | undecided |

### `alias:missile-defense-agency` — Missile Defense Agency (6)

| Field | Value |
| --- | --- |
| Demand (federal / all) | 6 / 29 |
| Names | Federal Hierarchy `300000429` MISSILE DEFENSE AGENCY (MDA) |
| FR-keyed consumers get | FR 103 Defense Department (part of) |
| Basis | `unitWithinFrAgency` |
| Reasoning | MDA is a Department of Defense agency; the Federal Hierarchy holds it as 300000429. |
| Records | the held roster records named |
| Answers | `yes` / `no` |
| Recommended | **yes** — The unit has no FR record; a part-of row gives the FR id of the organization it sits in, and claims no identity. |
| Owner decision / date | undecided |

### `alias:cyber-command` — Cyber Command (2); U.S. Cyber Command (2); United States Cyber Command (2)

| Field | Value |
| --- | --- |
| Demand (federal / all) | 6 / 20 |
| Names | Federal Hierarchy `300000421` U.S. CYBER COMMAND |
| FR-keyed consumers get | FR 103 Defense Department (part of) |
| Basis | `unitWithinFrAgency` |
| Reasoning | U.S. Cyber Command; the Federal Hierarchy holds it as 300000421. |
| Records | [10 U.S.C. 161](https://uscode.house.gov/view.xhtml?req=granuleid:USC-prelim-title10-section161&num=0&edition=prelim) (unread) |
| Answers | `yes` / `no` |
| Recommended | **yes** — A combatant command is a Department of Defense component (10 U.S.C. 161) with no FR record; part-of DOD is the only FR resolution, and it claims no identity. |
| Owner decision / date | undecided |

### `alias:special-operations-command` — U.S. Special Operations Command (3); United States Special Operations Command (2)

| Field | Value |
| --- | --- |
| Demand (federal / all) | 5 / 44 |
| Names | Federal Hierarchy `300000430` U.S. SPECIAL OPERATIONS COMMAND (USSOCOM) |
| FR-keyed consumers get | FR 103 Defense Department (part of) |
| Basis | `unitWithinFrAgency` |
| Reasoning | U.S. Special Operations Command; the Federal Hierarchy holds it as 300000430. |
| Records | [10 U.S.C. 161](https://uscode.house.gov/view.xhtml?req=granuleid:USC-prelim-title10-section161&num=0&edition=prelim) (unread) |
| Answers | `yes` / `no` |
| Recommended | **yes** — A combatant command is a Department of Defense component (10 U.S.C. 161) with no FR record; part-of DOD is the only FR resolution, and it claims no identity. |
| Owner decision / date | undecided |

### `alias:africa-command` — United States Africa Command (3); U.S. Africa Command (2)

| Field | Value |
| --- | --- |
| Demand (federal / all) | 5 / 26 |
| Names | none held |
| FR-keyed consumers get | FR 103 Defense Department (part of) |
| Basis | `unitWithinFrAgency` |
| Reasoning | U.S. Africa Command; OPM's AF1R is an Air Force code, so not taken as the command. |
| Records | [10 U.S.C. 161](https://uscode.house.gov/view.xhtml?req=granuleid:USC-prelim-title10-section161&num=0&edition=prelim) (unread) |
| Answers | `yes` / `no` |
| Recommended | **yes** — A combatant command is a Department of Defense component (10 U.S.C. 161) with no FR record; part-of DOD is the only FR resolution, and it claims no identity. |
| Owner decision / date | undecided |

### `alias:federal-bureau-of-investigations` — Federal Bureau of Investigations (5)

| Field | Value |
| --- | --- |
| Demand (federal / all) | 5 / 17 |
| Names | none held |
| FR-keyed consumers get | FR 160 Federal Bureau of Investigation |
| Basis | `misspelling` |
| Reasoning | A misspelling of the Federal Bureau of Investigation (FR 160). |
| Records | the held roster records named |
| Answers | `yes` / `no` |
| Recommended | **no** — No publisher spells it so; a misspelling is the consumer's fuzzy matcher's job, not a reviewed alias. |
| Owner decision / date | undecided |

### `alias:national-cemetery-administration` — National Cemetery Administration (5)

| Field | Value |
| --- | --- |
| Demand (federal / all) | 5 / 15 |
| Names | OPM `VAPA` NATIONAL CEMETERY ADMINISTRATION |
| FR-keyed consumers get | FR 520 Veterans Affairs Department (part of) |
| Basis | `unitWithinFrAgency` |
| Reasoning | NCA is an administration of the Department of Veterans Affairs; OPM holds it as VAPA. |
| Records | [38 U.S.C. 2400](https://uscode.house.gov/view.xhtml?req=granuleid:USC-prelim-title38-section2400&num=0&edition=prelim) (unread) |
| Answers | `yes` / `no` |
| Recommended | **yes** — The unit has no FR record; a part-of row gives the FR id of the organization it sits in, and claims no identity. |
| Owner decision / date | undecided |

### `alias:office-of-comptroller-of-currency` — Office of the Comptroller of the Currency (3); Office of the Comptroller of Currency (1)

| Field | Value |
| --- | --- |
| Demand (federal / all) | 4 / 141 |
| Names | none held |
| FR-keyed consumers get | FR 80 Comptroller of the Currency |
| Basis | `publisherNameVariant` |
| Reasoning | FR 80 is 'Comptroller of the Currency'; the statute names the agency the Office of the Comptroller of the Currency, as the Federal Hierarchy and OPM do. |
| Records | [12 U.S.C. 1](https://uscode.house.gov/view.xhtml?req=granuleid:USC-prelim-title12-section1&num=0&edition=prelim) (unread) |
| Answers | `yes` / `no` |
| Recommended | **yes** — The FR names the office by its head; the statutory name is the same agency. |
| Owner decision / date | undecided |

### `alias:defense-health-agency` — Defense Health Agency (4)

| Field | Value |
| --- | --- |
| Demand (federal / all) | 4 / 16 |
| Names | Federal Hierarchy `300000422` DEFENSE HEALTH AGENCY (DHA) |
| FR-keyed consumers get | FR 103 Defense Department (part of) |
| Basis | `unitWithinFrAgency` |
| Reasoning | DHA is a Department of Defense agency; the Federal Hierarchy holds it as 300000422. |
| Records | the held roster records named |
| Answers | `yes` / `no` |
| Recommended | **yes** — The unit has no FR record; a part-of row gives the FR id of the organization it sits in, and claims no identity. |
| Owner decision / date | undecided |

### `alias:space-command` — U.S. Space Command (4)

| Field | Value |
| --- | --- |
| Demand (federal / all) | 4 / 15 |
| Names | none held |
| FR-keyed consumers get | FR 103 Defense Department (part of) |
| Basis | `unitWithinFrAgency` |
| Reasoning | U.S. Space Command; no held roster holds the command itself. |
| Records | [10 U.S.C. 161](https://uscode.house.gov/view.xhtml?req=granuleid:USC-prelim-title10-section161&num=0&edition=prelim) (unread) |
| Answers | `yes` / `no` |
| Recommended | **yes** — A combatant command is a Department of Defense component (10 U.S.C. 161) with no FR record; part-of DOD is the only FR resolution, and it claims no identity. |
| Owner decision / date | undecided |

### `alias:usda-office-of-inspector-general` — USDA Office of Inspector General (4)

| Field | Value |
| --- | --- |
| Demand (federal / all) | 4 / 11 |
| Names | none held |
| FR-keyed consumers get | FR 244 Inspector General Office, Agriculture Department |
| Basis | `publisherNameVariant` |
| Reasoning | FR 244 is 'Inspector General Office, Agriculture Department'; this is its name in natural order with the parent's acronym. |
| Records | the held roster records named |
| Answers | `yes` / `no` |
| Recommended | **yes** — The parent acronym makes an otherwise ambiguous 'Office of Inspector General' name exactly one FR record. |
| Owner decision / date | undecided |

### `alias:national-forest-system` — National Forest System (4)

| Field | Value |
| --- | --- |
| Demand (federal / all) | 4 / 9 |
| Names | none held |
| FR-keyed consumers get | FR 209 Forest Service (part of) |
| Basis | `unitWithinFrAgency` |
| Reasoning | The National Forest System is the lands the Forest Service (FR 209) administers; as a witness's organization it names the Forest Service's National Forest System deputy area. |
| Records | [16 U.S.C. 1609](https://uscode.house.gov/view.xhtml?req=granuleid:USC-prelim-title16-section1609&num=0&edition=prelim) (unread) |
| Answers | `yes` / `no` |
| Recommended | **yes** — The unit has no FR record; a part-of row gives the FR id of the organization it sits in, and claims no identity. |
| Owner decision / date | undecided |

### `alias:national-institute-of-health` — National Institute of Health (3); U.S. National Institute of Health (1)

| Field | Value |
| --- | --- |
| Demand (federal / all) | 4 / 6 |
| Names | none held |
| FR-keyed consumers get | FR 353 National Institutes of Health |
| Basis | `misspelling` |
| Reasoning | A misspelling of the National Institutes of Health (FR 353). |
| Records | the held roster records named |
| Answers | `yes` / `no` |
| Recommended | **no** — No publisher spells it so; a misspelling is the consumer's fuzzy matcher's job, not a reviewed alias. |
| Owner decision / date | undecided |

### `alias:joint-chiefs-of-staff` — Joint Chiefs of Staff (3)

| Field | Value |
| --- | --- |
| Demand (federal / all) | 3 / 56 |
| Names | OPM `DD02` ORGANIZATION OF THE JOINT CHIEFS OF STAFF |
| FR-keyed consumers get | FR 103 Defense Department (part of) |
| Basis | `unitWithinFrAgency` |
| Reasoning | The Joint Chiefs of Staff sit in the Department of Defense; OPM holds their organization as DD02. |
| Records | [10 U.S.C. 151](https://uscode.house.gov/view.xhtml?req=granuleid:USC-prelim-title10-section151&num=0&edition=prelim) (unread) |
| Answers | `yes` / `no` |
| Recommended | **yes** — The unit has no FR record; a part-of row gives the FR id of the organization it sits in, and claims no identity. |
| Owner decision / date | undecided |

### `alias:central-command` — U.S. Central Command (2); United States Central Command (1)

| Field | Value |
| --- | --- |
| Demand (federal / all) | 3 / 26 |
| Names | none held |
| FR-keyed consumers get | FR 103 Defense Department (part of) |
| Basis | `unitWithinFrAgency` |
| Reasoning | U.S. Central Command; no held roster holds the command itself. |
| Records | [10 U.S.C. 161](https://uscode.house.gov/view.xhtml?req=granuleid:USC-prelim-title10-section161&num=0&edition=prelim) (unread) |
| Answers | `yes` / `no` |
| Recommended | **yes** — A combatant command is a Department of Defense component (10 U.S.C. 161) with no FR record; part-of DOD is the only FR resolution, and it claims no identity. |
| Owner decision / date | undecided |

### `alias:european-command` — U.S. European Command (2); United States European Command (1)

| Field | Value |
| --- | --- |
| Demand (federal / all) | 3 / 25 |
| Names | none held |
| FR-keyed consumers get | FR 103 Defense Department (part of) |
| Basis | `unitWithinFrAgency` |
| Reasoning | U.S. European Command; no held roster holds the command itself. |
| Records | [10 U.S.C. 161](https://uscode.house.gov/view.xhtml?req=granuleid:USC-prelim-title10-section161&num=0&edition=prelim) (unread) |
| Answers | `yes` / `no` |
| Recommended | **yes** — A combatant command is a Department of Defense component (10 U.S.C. 161) with no FR record; part-of DOD is the only FR resolution, and it claims no identity. |
| Owner decision / date | undecided |

### `alias:cybersecurity-and-infrastructure-security-agency` — Cybersecurity and Infrastructure Security Agency (3)

| Field | Value |
| --- | --- |
| Demand (federal / all) | 3 / 22 |
| Names | Federal Hierarchy `500044551` Cybersecurity and Infrastructure Security Agency |
| FR-keyed consumers get | FR 227 Homeland Security Department (part of) |
| Basis | `unitWithinFrAgency` |
| Reasoning | CISA is a Department of Homeland Security agency. REF-038 already maps regulations.gov 'CISA' to Federal Hierarchy 500044551, and batch 1 recorded that the held FR roster has no CISA record (noCounterpartInHeldFRRoster). |
| Records | the held roster records named |
| Answers | `yes` / `no` |
| Recommended | **yes** — The unit has no FR record; a part-of row gives the FR id of the organization it sits in, and claims no identity. |
| Owner decision / date | undecided |

### `alias:air-force-space-command` — Air Force Space Command (2); U.S. Air Force Space Command (1)

| Field | Value |
| --- | --- |
| Demand (federal / all) | 3 / 19 |
| Names | none held |
| FR-keyed consumers get | FR 13 Air Force Department (part of) |
| Basis | `unitWithinFrAgency` |
| Reasoning | Air Force Space Command, an Air Force major command until the Space Force took it in 2019-2020. |
| Records | the held roster records named |
| Answers | `yes` / `no` |
| Recommended | **yes** — Part-of the Department of the Air Force is true for the command's whole life, before and after the Space Force. |
| Owner decision / date | undecided |

### `alias:national-institute-of-allergy-and-infectious-diseases` — National Institute of Allergy and Infectious Diseases (3)

| Field | Value |
| --- | --- |
| Demand (federal / all) | 3 / 19 |
| Names | none held |
| FR-keyed consumers get | FR 353 National Institutes of Health (part of) |
| Basis | `unitWithinFrAgency` |
| Reasoning | NIAID is an institute of the National Institutes of Health (FR 353). |
| Records | [42 U.S.C. 285f](https://uscode.house.gov/view.xhtml?req=granuleid:USC-prelim-title42-section285f&num=0&edition=prelim) (unread) |
| Answers | `yes` / `no` |
| Recommended | **yes** — The unit has no FR record; a part-of row gives the FR id of the organization it sits in, and claims no identity. |
| Owner decision / date | undecided |

### `alias:office-of-congressional-workplace-rights` — Office of Congressional Workplace Rights (3)

| Field | Value |
| --- | --- |
| Demand (federal / all) | 3 / 14 |
| Names | OPM `ZG00` OFFICE OF CONGRESSIONAL WORKPLACE RIGHTS. NOTE: ORGANIZATION DOES NOT MAKE HR SUBMISSIONS TO OPM. CODE MAY BE USED FOR OTHER DOCUMENTATION PURPOSES. |
| FR-keyed consumers get | no FR id |
| Basis | `noFrRecord` |
| Reasoning | A legislative-branch office (the Office of Compliance until 2018); OPM holds it as ZG00, the FR does not. |
| Records | the held roster records named |
| Answers | `yes` / `no` |
| Recommended | **yes** — Names the OPM record; no FR id. |
| Owner decision / date | undecided |

### `alias:forces-korea` — U.S. Forces Korea (2); United States Forces Korea (1)

| Field | Value |
| --- | --- |
| Demand (federal / all) | 3 / 11 |
| Names | none held |
| FR-keyed consumers get | FR 103 Defense Department (part of) |
| Basis | `unitWithinFrAgency` |
| Reasoning | U.S. Forces Korea, a subordinate unified command; no held roster holds it. |
| Records | [10 U.S.C. 161](https://uscode.house.gov/view.xhtml?req=granuleid:USC-prelim-title10-section161&num=0&edition=prelim) (unread) |
| Answers | `yes` / `no` |
| Recommended | **yes** — A combatant command is a Department of Defense component (10 U.S.C. 161) with no FR record; part-of DOD is the only FR resolution, and it claims no identity. |
| Owner decision / date | undecided |

### `alias:labor` — Labor (3)

| Field | Value |
| --- | --- |
| Demand (federal / all) | 3 / 11 |
| Names | none held |
| FR-keyed consumers get | FR 271 Labor Department |
| Basis | `publisherNameVariant` |
| Reasoning | 'Labor' as a whole organization string; FR 271 is 'Labor Department'. |
| Records | the held roster records named |
| Answers | `yes` / `no` |
| Recommended | **no** — A single common word: in witness titles it is as often a portfolio ('Assistant Secretary for Labor') as the department. |
| Owner decision / date | undecided |

### `alias:office-of-chief-of-naval-operations` — Office of the Chief of Naval Operations (3)

| Field | Value |
| --- | --- |
| Demand (federal / all) | 3 / 11 |
| Names | none held |
| FR-keyed consumers get | FR 378 Navy Department (part of) |
| Basis | `unitWithinFrAgency` |
| Reasoning | The Office of the Chief of Naval Operations is the Navy's headquarters staff in the Department of the Navy. |
| Records | the held roster records named |
| Answers | `yes` / `no` |
| Recommended | **yes** — The unit has no FR record; a part-of row gives the FR id of the organization it sits in, and claims no identity. |
| Owner decision / date | undecided |

### `alias:headquarters-air-force` — Headquarters U.S. Air Force (3)

| Field | Value |
| --- | --- |
| Demand (federal / all) | 3 / 10 |
| Names | none held |
| FR-keyed consumers get | FR 13 Air Force Department (part of) |
| Basis | `unitWithinFrAgency` |
| Reasoning | Headquarters Air Force (the Secretariat and Air Staff) sits in the Department of the Air Force. |
| Records | the held roster records named |
| Answers | `yes` / `no` |
| Recommended | **yes** — The unit has no FR record; a part-of row gives the FR id of the organization it sits in, and claims no identity. |
| Owner decision / date | undecided |

### `alias:headquarters-marine-corps` — Headquarters U.S. Marine Corps (2); Headquarters Marine Corps (1)

| Field | Value |
| --- | --- |
| Demand (federal / all) | 3 / 10 |
| Names | none held |
| FR-keyed consumers get | FR 378 Navy Department (part of) |
| Basis | `unitWithinFrAgency` |
| Reasoning | Headquarters, Marine Corps sits in the Department of the Navy. |
| Records | the held roster records named |
| Answers | `yes` / `no` |
| Recommended | **yes** — The unit has no FR record; a part-of row gives the FR id of the organization it sits in, and claims no identity. |
| Owner decision / date | undecided |

### `alias:health-and-human-services` — Health and Human Services (3)

| Field | Value |
| --- | --- |
| Demand (federal / all) | 3 / 9 |
| Names | none held |
| FR-keyed consumers get | FR 221 Health and Human Services Department |
| Basis | `publisherNameVariant` |
| Reasoning | FR 221 is 'Health and Human Services Department'; the name without 'Department'. |
| Records | the held roster records named |
| Answers | `yes` / `no` |
| Recommended | **yes** — Unambiguous: no other held organization is named Health and Human Services. |
| Owner decision / date | undecided |

### `alias:bureau-of-near-eastern-affairs` — Bureau of Near Eastern Affairs (3)

| Field | Value |
| --- | --- |
| Demand (federal / all) | 3 / 6 |
| Names | none held |
| FR-keyed consumers get | FR 476 State Department (part of) |
| Basis | `unitWithinFrAgency` |
| Reasoning | A regional bureau of the Department of State (FR 476). |
| Records | the held roster records named |
| Answers | `yes` / `no` |
| Recommended | **yes** — The unit has no FR record; a part-of row gives the FR id of the organization it sits in, and claims no identity. |
| Owner decision / date | undecided |

### `alias:department-of-war` — U.S. Department of War (3)

| Field | Value |
| --- | --- |
| Demand (federal / all) | 3 / 6 |
| Names | none held |
| FR-keyed consumers get | FR 103 Defense Department |
| Basis | `secondaryTitle` |
| Reasoning | The secondary title the President authorized for the Department of Defense (FR 103) in September 2025. |
| Records | Executive Order 14347 (2025-09-05), Restoring the United States Department of War (unread) |
| Answers | `yes` / `no` |
| Recommended | **yes** — An official title of the same department; adopt once the order is read. |
| Owner decision / date | undecided |

### `alias:defense-innovation-unit` — Defense Innovation Unit (3)

| Field | Value |
| --- | --- |
| Demand (federal / all) | 3 / 3 |
| Names | none held |
| FR-keyed consumers get | FR 103 Defense Department (part of) |
| Basis | `unitWithinFrAgency` |
| Reasoning | DIU is a Department of Defense organization no held roster holds. |
| Records | the held roster records named |
| Answers | `yes` / `no` |
| Recommended | **yes** — The unit has no FR record; a part-of row gives the FR id of the organization it sits in, and claims no identity. |
| Owner decision / date | undecided |

### `alias:federal-energy-regulatory-commision` — Federal Energy Regulatory Commision (3)

| Field | Value |
| --- | --- |
| Demand (federal / all) | 3 / 3 |
| Names | none held |
| FR-keyed consumers get | FR 167 Federal Energy Regulatory Commission |
| Basis | `misspelling` |
| Reasoning | A misspelling of the Federal Energy Regulatory Commission (FR 167). |
| Records | the held roster records named |
| Answers | `yes` / `no` |
| Recommended | **no** — No publisher spells it so; a misspelling is the consumer's fuzzy matcher's job, not a reviewed alias. |
| Owner decision / date | undecided |

### `alias:general-accounting-office` — General Accounting Office (GAO) (2)

| Field | Value |
| --- | --- |
| Demand (federal / all) | 2 / 214 |
| Names | none held |
| FR-keyed consumers get | FR 213 Government Accountability Office |
| Basis | `statutoryRename` |
| Reasoning | The Government Accountability Office's name before 2004-07-07. OPM's pinned roster states it: LG00, 'WHOSE NAME, PRIOR TO JULY 7, 2004, HAD BEEN THE GENERAL ACCOUNTING OFFICE'. The FR holds one record, FR 213, so there is no succession to state (the rename rule: a stale name no roster holds as its own record is identity evidence). |
| Records | [Pub. L. 108-271, sec. 8(a), 118 Stat. 811 (2004-07-07), GAO Human Capital Reform Act of 2004](https://www.congress.gov/108/plaws/publ271/PLAW-108publ271.pdf) (unread) |
| Answers | `yes` / `no` |
| Recommended | **yes** — One organization renamed by statute; the old name appears in 214 unmatched appearances. |
| Owner decision / date | undecided |

### `alias:national-counterterrorism-center` — National Counterterrorism Center (2)

| Field | Value |
| --- | --- |
| Demand (federal / all) | 2 / 45 |
| Names | none held |
| FR-keyed consumers get | FR 354 National Intelligence, Office of the National Director (part of) |
| Basis | `unitWithinFrAgency` |
| Reasoning | NCTC is a center of the Office of the Director of National Intelligence (FR 354). FR 334, the National Counterintelligence Center, carries the short name 'NCTC': an acronym collision, so the acronym is never an alias here. |
| Records | [50 U.S.C. 3056](https://uscode.house.gov/view.xhtml?req=granuleid:USC-prelim-title50-section3056&num=0&edition=prelim) (unread) |
| Answers | `yes` / `no` |
| Recommended | **yes** — The unit has no FR record; a part-of row gives the FR id of the organization it sits in, and claims no identity. |
| Owner decision / date | undecided |

### `alias:energy` — Energy (2)

| Field | Value |
| --- | --- |
| Demand (federal / all) | 2 / 43 |
| Names | none held |
| FR-keyed consumers get | FR 136 Energy Department |
| Basis | `publisherNameVariant` |
| Reasoning | 'Energy' as a whole organization string; FR 136 is 'Energy Department'. |
| Records | the held roster records named |
| Answers | `yes` / `no` |
| Recommended | **no** — A single common word; 'Energy and Commerce' and 'Energy and Environment' split to it. |
| Owner decision / date | undecided |

### `alias:commission-on-international-religious-freedom` — U.S. Commission on International Religious Freedom (2)

| Field | Value |
| --- | --- |
| Demand (federal / all) | 2 / 33 |
| Names | OPM `ZP00` U.S. COMMISSION ON INTERNATIONAL RELIGIOUS FREEDOM |
| FR-keyed consumers get | no FR id |
| Basis | `noFrRecord` |
| Reasoning | USCIRF; OPM holds it as ZP00. The Federal Hierarchy holds two records of the same name (300000724, 300000894), so neither is taken. |
| Records | the held roster records named |
| Answers | `yes` / `no` |
| Recommended | **yes** — Names the one OPM record; no FR id. |
| Owner decision / date | undecided |

### `alias:office-of-information-and-regulatory-affairs` — Office of Information and Regulatory Affairs (2)

| Field | Value |
| --- | --- |
| Demand (federal / all) | 2 / 29 |
| Names | none held |
| FR-keyed consumers get | FR 280 Management and Budget Office (part of) |
| Basis | `unitWithinFrAgency` |
| Reasoning | OIRA is an office within the Office of Management and Budget (FR 280); regulations.gov lists it as its own agency code, but no reviewed REF-038 row maps that code to an FR record. |
| Records | [44 U.S.C. 3503](https://uscode.house.gov/view.xhtml?req=granuleid:USC-prelim-title44-section3503&num=0&edition=prelim) (unread) |
| Answers | `yes` / `no` |
| Recommended | **yes** — The unit has no FR record; a part-of row gives the FR id of the organization it sits in, and claims no identity. |
| Owner decision / date | undecided |

### `alias:federal-bureau-of-prisons` — Federal Bureau of Prisons (2)

| Field | Value |
| --- | --- |
| Demand (federal / all) | 2 / 25 |
| Names | none held |
| FR-keyed consumers get | FR 437 Prisons Bureau |
| Basis | `publisherNameVariant` |
| Reasoning | FR 437 is 'Prisons Bureau'; the bureau calls itself the Federal Bureau of Prisons, and the Federal Hierarchy names it 'FEDERAL PRISON SYSTEM / BUREAU OF PRISONS'. |
| Records | the held roster records named |
| Answers | `yes` / `no` |
| Recommended | **yes** — The bureau's own name for the FR record's organization. |
| Owner decision / date | undecided |

### `alias:transportation-command` — U.S. Transportation Command (TRANSCOM) (1); U.S. Transportation Command (USTRANSCOM) (1)

| Field | Value |
| --- | --- |
| Demand (federal / all) | 2 / 25 |
| Names | OPM `DD76` U.S. TRANSPORTATION COMMAND.  NOTE: ORGANIZATION DOES NOT MAKE HR SUBMISSIONS TO OPM. CODE MAY BE USED FOR OTHER DOCUMENTATION PURPOSES. |
| FR-keyed consumers get | FR 103 Defense Department (part of) |
| Basis | `unitWithinFrAgency` |
| Reasoning | U.S. Transportation Command; OPM holds it as DD76. |
| Records | [10 U.S.C. 161](https://uscode.house.gov/view.xhtml?req=granuleid:USC-prelim-title10-section161&num=0&edition=prelim) (unread) |
| Answers | `yes` / `no` |
| Recommended | **yes** — A combatant command is a Department of Defense component (10 U.S.C. 161) with no FR record; part-of DOD is the only FR resolution, and it claims no identity. |
| Owner decision / date | undecided |

### `alias:education` — Education (1)

| Field | Value |
| --- | --- |
| Demand (federal / all) | 1 / 71 |
| Names | none held |
| FR-keyed consumers get | FR 126 Education Department |
| Basis | `publisherNameVariant` |
| Reasoning | 'Education' as a whole organization string; FR 126 is 'Education Department'. |
| Records | the held roster records named |
| Answers | `yes` / `no` |
| Recommended | **no** — A single common word, as often a portfolio or a state agency as the department. |
| Owner decision / date | undecided |

### `alias:usmc` — USMC (1)

| Field | Value |
| --- | --- |
| Demand (federal / all) | 1 / 43 |
| Names | OPM `NV27` U.S. MARINE CORPS |
| FR-keyed consumers get | FR 378 Navy Department (part of) |
| Basis | `militaryServiceOfDepartment` |
| Reasoning | USMC, the Marine Corps' own acronym; the same row as 'marine corps'. |
| Records | [10 U.S.C. 8063](https://uscode.house.gov/view.xhtml?req=granuleid:USC-prelim-title10-section8063&num=0&edition=prelim) (unread) |
| Answers | `yes` / `no` |
| Recommended | **yes** — The unit has no FR record; a part-of row gives the FR id of the organization it sits in, and claims no identity. |
| Owner decision / date | undecided |

### `alias:national-guard-bureau` — National Guard Bureau (1)

| Field | Value |
| --- | --- |
| Demand (federal / all) | 1 / 36 |
| Names | none held |
| FR-keyed consumers get | FR 103 Defense Department (part of) |
| Basis | `unitWithinFrAgency` |
| Reasoning | The National Guard Bureau is a joint activity of the Department of Defense; OPM holds only its chief's office (ARGB). |
| Records | [10 U.S.C. 10501](https://uscode.house.gov/view.xhtml?req=granuleid:USC-prelim-title10-section10501&num=0&edition=prelim) (unread) |
| Answers | `yes` / `no` |
| Recommended | **yes** — The unit has no FR record; a part-of row gives the FR id of the organization it sits in, and claims no identity. |
| Owner decision / date | undecided |

### `alias:national-science-board` — National Science Board (1)

| Field | Value |
| --- | --- |
| Demand (federal / all) | 1 / 26 |
| Names | none held |
| FR-keyed consumers get | FR 366 National Science Foundation (part of) |
| Basis | `unitWithinFrAgency` |
| Reasoning | The National Science Board is the governing board of the National Science Foundation (FR 366). |
| Records | [42 U.S.C. 1863](https://uscode.house.gov/view.xhtml?req=granuleid:USC-prelim-title42-section1863&num=0&edition=prelim) (unread) |
| Answers | `yes` / `no` |
| Recommended | **yes** — The unit has no FR record; a part-of row gives the FR id of the organization it sits in, and claims no identity. |
| Owner decision / date | undecided |

## Already resolvable (1) — no alias needed

The key equals an FR name under the published `name_key`; the consumer's own normalizer missed it.

| Key | Spellings seen | FR record |
| --- | --- | --- |
| `fish and wildlife service` | U. S. Fish and Wildlife Service (6) | FR 197 Fish and Wildlife Service |

## Excluded (59) — not federal agency names

Listed so nothing is dropped silently; say so to move any into a later batch.

| Key | Demand | Reason | Note |
| --- | --- | --- | --- |
| `office of inspector general` | 17 / 94 | `genericTitleOrFragment` | a title or a fragment naming no one organization |
| `veterans health administration department of veterans affairs` | 11 / 20 | `compoundWithParentName` | an alias followed or led by its parent's name; the consumer splits it off |
| `senate` | 8 / 60 | `congressOrCourt` | a chamber, committee or court, not an agency |
| `veterans benefits administration department of veterans affairs` | 7 / 10 | `compoundWithParentName` | an alias followed or led by its parent's name; the consumer splits it off |
| `chamber of commerce` | 5 / 220 | `notAFederalAgency` | a private organization or union |
| `navajo nation` | 5 / 90 | `notAFederalAgency` | a tribal government |
| `northern command and north american aerospace defense command` | 5 / 13 | `compoundOfTwoOrganizations` | two commands under one commander (NORTHCOM and the binational NORAD) |
| `office of general counsel` | 5 / 12 | `genericTitleOrFragment` | a title or a fragment naming no one organization |
| `supreme court of` | 4 / 9 | `congressOrCourt` | a chamber, committee or court, not an agency |
| `committee on ethics` | 4 / 6 | `congressOrCourt` | a chamber, committee or court, not an agency |
| `director` | 3 / 556 | `genericTitleOrFragment` | a title or a fragment naming no one organization |
| `disabled american veterans` | 3 / 329 | `notAFederalAgency` | a private organization or union |
| `veterans of foreign wars` | 3 / 162 | `notAFederalAgency` | a private organization or union |
| `american federation of government employees` | 3 / 123 | `notAFederalAgency` | a private organization or union |
| `national congress of american indians` | 3 / 110 | `notAFederalAgency` | a private organization or union |
| `national indian health board` | 3 / 56 | `notAFederalAgency` | a private organization or union |
| `confederated tribes of colville reservation` | 3 / 44 | `notAFederalAgency` | a tribal government |
| `cherokee nation` | 3 / 28 | `notAFederalAgency` | a tribal government |
| `installations and environment` | 3 / 17 | `genericTitleOrFragment` | a title or a fragment naming no one organization |
| `joint committee on taxation` | 3 / 13 | `congressOrCourt` | a chamber, committee or court, not an agency |
| `eastern band of cherokee indians` | 3 / 12 | `notAFederalAgency` | a tribal government |
| `united nations command` | 3 / 10 | `notAFederalAgency` | a multinational command under a UN mandate |
| `energy and environment` | 3 / 8 | `genericTitleOrFragment` | a title or a fragment naming no one organization |
| `quapaw nation` | 3 / 7 | `notAFederalAgency` | a tribal government |
| `miami tribe of oklahoma` | 3 / 6 | `notAFederalAgency` | a tribal government |
| `and public service` | 3 / 5 | `segmentationArtifact` | a piece of 'National Commission on Military, National, and Public Service' (FR 594), which the consumer's comma split broke |
| `national` | 3 / 5 | `segmentationArtifact` | a piece of 'National Commission on Military, National, and Public Service' (FR 594), which the consumer's comma split broke |
| `national commission on military` | 3 / 5 | `segmentationArtifact` | a piece of 'National Commission on Military, National, and Public Service' (FR 594), which the consumer's comma split broke |
| `department of veterans` | 3 / 4 | `truncated` | a truncated 'Department of Veterans Affairs' |
| `afl cio` | 2 / 226 | `notAFederalAgency` | a private organization or union |
| `headquarters` | 2 / 42 | `genericTitleOrFragment` | a title or a fragment naming no one organization |
| `usda forest service` | 2 / 34 | `compoundWithParentName` | an alias followed or led by its parent's name; the consumer splits it off |
| `engineering` | 2 / 32 | `genericTitleOrFragment` | a title or a fragment naming no one organization |
| `national council of urban indian health` | 2 / 26 | `notAFederalAgency` | a private organization or union |
| `new york` | 1 / 823 | `notAFederalAgency` | a state, city or place |
| `heritage foundation` | 1 / 453 | `notAFederalAgency` | a private organization or union |
| `florida` | 1 / 174 | `notAFederalAgency` | a state, city or place |
| `foundation for defense of democracies` | 1 / 167 | `notAFederalAgency` | a private organization or union |
| `council on foreign relations` | 1 / 133 | `notAFederalAgency` | a private organization or union |
| `chair` | 1 / 108 | `genericTitleOrFragment` | a title or a fragment naming no one organization |
| `new jersey` | 1 / 102 | `notAFederalAgency` | a state, city or place |
| `az` | 1 / 86 | `notAFederalAgency` | a state, city or place |
| `american civil liberties union` | 1 / 77 | `notAFederalAgency` | a private organization or union |
| `wounded warrior project` | 1 / 77 | `notAFederalAgency` | a private organization or union |
| `partner` | 1 / 61 | `genericTitleOrFragment` | a title or a fragment naming no one organization |
| `district of columbia` | 1 / 60 | `notAFederalAgency` | a state, city or place |
| `commander` | 1 / 50 | `genericTitleOrFragment` | a title or a fragment naming no one organization |
| `information technology and innovation foundation` | 1 / 50 | `notAFederalAgency` | a private organization or union |
| `environment` | 1 / 36 | `genericTitleOrFragment` | a title or a fragment naming no one organization |
| `tucson` | 1 / 36 | `notAFederalAgency` | a state, city or place |
| `airlines for america` | 1 / 34 | `notAFederalAgency` | a private organization or union |
| `idaho national laboratory` | 1 / 34 | `notAFederalAgency` | a contractor-operated national laboratory, not an agency |
| `national center for missing and exploited children` | 1 / 34 | `notAFederalAgency` | a private organization or union |
| `german marshall fund of` | 1 / 32 | `notAFederalAgency` | a private organization or union |
| `state of florida` | 1 / 27 | `notAFederalAgency` | a state, city or place |
| `ms` | 1 / 26 | `genericTitleOrFragment` | a title or a fragment naming no one organization |
| `oak ridge national laboratory` | 1 / 26 | `notAFederalAgency` | a contractor-operated national laboratory, not an agency |
| `southern ute indian tribe` | 1 / 26 | `notAFederalAgency` | a tribal government |
| `pacific northwest national laboratory` | 1 / 25 | `notAFederalAgency` | a contractor-operated national laboratory, not an agency |

## Decision keys

| Id | Answers | Recommended | Content digest |
| --- | --- | --- | --- |
| `alias:veterans-health-administration` | `yes` / `no` | `yes` | `sha256:8ee5eb8016504ad8075fd9bf24719bcedf55e0ab3c8675ea952a290cfe6ece8f` |
| `alias:army` | `1` / `2` / `3` | `2` | `sha256:f1625287017b0d59cb3b720bc04b107fc408831627598f9d2163d41921689b12` |
| `alias:navy` | `1` / `2` / `3` | `2` | `sha256:19ca05578793266b10ed36ae112d05a3e97619d65ae73dcd6be52f41c6bedca6` |
| `alias:veterans-benefits-administration` | `yes` / `no` | `yes` | `sha256:dc3cd95c989a663ea89a15fa014faa2b999a0e2bc8ea6677b0bc9173a65fc424` |
| `alias:air-force` | `1` / `2` / `3` | `2` | `sha256:b3ca95b1d667d65415d4f7fd15d431ee2e639cd12cd1278e47c36011ed85ef4f` |
| `alias:marine-corps` | `yes` / `no` | `yes` | `sha256:3406554791150df766d73b8396fae5ab994142759f4dbd4929093ebf555e296c` |
| `alias:congressional-research-service` | `yes` / `no` | `yes` | `sha256:1c844fa501ed073fad0abe425f7fe5eb8ba519554e3c42eb95f6aa79bf645960` |
| `alias:office-of-secretary-of-defense` | `yes` / `no` | `yes` | `sha256:06a5b9df31d4660d03f66b21b4aac269e52d68a5c3eb6c35284294890e888f94` |
| `alias:bureau-of-land-management` | `yes` / `no` | `yes` | `sha256:d155e90c9f8a9f51068080808df57c32c79213255637c1f27f6a1e24e9c146e1` |
| `alias:bureau-of-reclamation` | `yes` / `no` | `yes` | `sha256:8b0ee546477e5cadbcc490ae1365e59cd52712e86e4280e54965b709728abe4d` |
| `alias:national-security-agency` | `yes` / `no` | `yes` | `sha256:99a45f7e4eb0cad7eae57affce344ca554fbe5d17aa1f81ec9a8f47d00085506` |
| `alias:office-of-director-of-national-intelligence` | `yes` / `no` | `yes` | `sha256:dbc6549dc2de7e28b766537214627c1dd73a3bbbb097114dfb1b5e59d90b3421` |
| `alias:army-corps-of-engineers` | `yes` / `no` | `yes` | `sha256:27a71b41d9688c9afa7c659583cccfeb3d302c8c214264e462fdbddbd8368a09` |
| `alias:office-of-management-and-budget` | `yes` / `no` | `yes` | `sha256:83d48efd17c6ffe51368ac5b59e60f9b9ea6d589dcdf03328aff29b5b7424658` |
| `alias:bureau-of-ocean-energy-management` | `yes` / `no` | `yes` | `sha256:0826ffff6f37a39ef8a16482810f94dacbbb7b4ce395aac9d0ff554f81900e3f` |
| `alias:board-of-governors-of-federal-reserve-system` | `1` / `2` / `3` | `2` | `sha256:923c8f5fb2ed53c21c211716630c0ff568c0d7c8480e093971dcfc2ec9fc3f36` |
| `alias:space-force` | `yes` / `no` | `yes` | `sha256:fcf74f38648e1bf967083c4e0ee6707bef6307cac35de120a11b1a960a084e15` |
| `alias:bureau-of-safety-and-environmental-enforcement` | `yes` / `no` | `yes` | `sha256:51329f7ac0b32198d520d4523c039aa9430c485193bea0a47a066c1b356c6b10` |
| `alias:national-reconnaissance-office` | `yes` / `no` | `yes` | `sha256:6a67138b7df4b4159475dfaf7cf9e36dfe65cff4d32072213f138fced2d54e09` |
| `alias:veterans-benefit-administration` | `yes` / `no` | `no` | `sha256:fdd61f607936971266781733d482bfa5fc5bc3423bb62ed945ad983f36532def` |
| `alias:export-import-bank-of` | `yes` / `no` | `yes` | `sha256:d7b1d03a4c5e177405eb0a3abd423e36bb079ebbc006044faa8d03e61a3833a3` |
| `alias:capitol-police` | `yes` / `no` | `yes` | `sha256:76e7ad914cf158661e1d0c2c18b45d71966a76dff6429556bd8ebbe6957941d2` |
| `alias:strategic-command` | `yes` / `no` | `yes` | `sha256:8eb3bd5c6a17d5bade140f243e8be4692976d9671a2d3180d2a93ddcf66e8a8e` |
| `alias:joint-staff` | `yes` / `no` | `yes` | `sha256:0b58cccf690d4d26a37d6a1a99deab3c122415c92c244ae5f715994a17d66f98` |
| `alias:office-of-special-counsel` | `yes` / `no` | `yes` | `sha256:f9f9534a48f5c645f8078b555207630e45306dd6a9c2430f30396ee60af65a8f` |
| `alias:missile-defense-agency` | `yes` / `no` | `yes` | `sha256:271155109669bfd36cdeb9d916d3e5f741973a496978e79d53dc4b68e69f393d` |
| `alias:cyber-command` | `yes` / `no` | `yes` | `sha256:91d84d8ac6942a131fed922c346a9161b46fd58b7baff11e4aff2f49a2c4d3de` |
| `alias:special-operations-command` | `yes` / `no` | `yes` | `sha256:9b03ba4ffcd2ee113f06b0509ae50347bd65efe4e21a83252042850686feeb4b` |
| `alias:africa-command` | `yes` / `no` | `yes` | `sha256:ab3276a746ba7d2999d89f67e49a42976c8519fd9c62668f5b2f3b8a2207463e` |
| `alias:federal-bureau-of-investigations` | `yes` / `no` | `no` | `sha256:23ef9b82c730c532973d3f3c2638075f38dfd720d2479e554547917c65e90c26` |
| `alias:national-cemetery-administration` | `yes` / `no` | `yes` | `sha256:e8dae9b38352601e8e6dacfede2ba988e2c42cc40762fb17377a621494b2efa5` |
| `alias:office-of-comptroller-of-currency` | `yes` / `no` | `yes` | `sha256:b9160a479b0e82bae2400f4340a8d28ebcb40ab11d90c011937b5c080f44621a` |
| `alias:defense-health-agency` | `yes` / `no` | `yes` | `sha256:6f15e062e5500d5b0ce1c563f480f84c4a43d01f0595d92863ca3b0d5042b0f2` |
| `alias:space-command` | `yes` / `no` | `yes` | `sha256:1af9f5f38489fe162fbfc1d1051b75b303f2f79f6d1840240e45a5ae61041deb` |
| `alias:bureau-of-indian-affairs` | `yes` / `no` | `yes` | `sha256:5e35b2820cd465393ed58d022c6a6d7720455b5e089df98384b84663d95c896e` |
| `alias:usda-office-of-inspector-general` | `yes` / `no` | `yes` | `sha256:362e63e8f4affa2cbcd43aa84ce7388130865ec82d9db6bbaefe9e2c41df3282` |
| `alias:national-forest-system` | `yes` / `no` | `yes` | `sha256:69eb7966416e430cd1d1dc97baa4d3cb72e3e5e793f392b0bca5e19fe077d275` |
| `alias:national-institute-of-health` | `yes` / `no` | `no` | `sha256:33c16269ab8f7bf0b9699b92cbbee1d3f1b37b413092f0a571150f20bbb91d46` |
| `alias:office-of-personnel-management` | `yes` / `no` | `yes` | `sha256:0863d759110530fc9155d1ed79761ba82516f316c997de589daa13f501965046` |
| `alias:joint-chiefs-of-staff` | `yes` / `no` | `yes` | `sha256:211fbc4cf587f15d61714a59b6d71dc474f48c8773510c1b188ed23085ba4613` |
| `alias:central-command` | `yes` / `no` | `yes` | `sha256:16babe2a3fc9bd5e0e2ac45e6c4b21f7f4d33f36d3289d12985fca4a46794c3a` |
| `alias:european-command` | `yes` / `no` | `yes` | `sha256:74fdede3f87f8b09b3ebd8bc8044a12528bdfb6fde55aa64a24833da95ccc7d9` |
| `alias:cybersecurity-and-infrastructure-security-agency` | `yes` / `no` | `yes` | `sha256:be6227dfe13d7046830c6ee34b26eb9a3a9ea27328ed7efb935a88a7d23d1aca` |
| `alias:air-force-space-command` | `yes` / `no` | `yes` | `sha256:eef82f5225698d66d0608d9f158f8ead070fa3e6285d5d91b047e48a2be3c4c4` |
| `alias:national-institute-of-allergy-and-infectious-diseases` | `yes` / `no` | `yes` | `sha256:9707189da97736f165bad29dfaa6782d94bdb36f9f44e31cf33c8d8dde3ed581` |
| `alias:office-of-congressional-workplace-rights` | `yes` / `no` | `yes` | `sha256:2ae15383568be2a41684e16768e9c1cfb021cb2d3201048581e55a7abbc3d775` |
| `alias:forces-korea` | `yes` / `no` | `yes` | `sha256:cadee6ecd2fbe6950cc3af70255ddd0f24d005f5c9d81c121c0d253eb46239f4` |
| `alias:labor` | `yes` / `no` | `no` | `sha256:3775405dd00a67787baa612a912cfa94bdc6e306a476999af087d989f265788b` |
| `alias:office-of-chief-of-naval-operations` | `yes` / `no` | `yes` | `sha256:022d84210d217991f15e8b60787d59e898b68fa0a0da57119db77c52d1d23a6c` |
| `alias:headquarters-air-force` | `yes` / `no` | `yes` | `sha256:d0cfae896f4a5602276f8e1422ce68dc1728489c1c6aaf337ae0559d916829a2` |
| `alias:headquarters-marine-corps` | `yes` / `no` | `yes` | `sha256:36780b5b163ec567a7494bcca60538e95f0af8a90bdddd4777cf29f9bef8a74f` |
| `alias:health-and-human-services` | `yes` / `no` | `yes` | `sha256:d43714382801c00af5662b7c9e401a483f00fc4ed0a23eb906cc4b564b0033c0` |
| `alias:office-of-surface-mining-reclamation-and-enforcement` | `yes` / `no` | `yes` | `sha256:143c6d32a07f87f1b9ac274b20e0248b79ffa222140bbfac85433247662c1f27` |
| `alias:bureau-of-near-eastern-affairs` | `yes` / `no` | `yes` | `sha256:ef6b9c64ebbf9abb31035f71e0ff807ebe178606ee19ff634d754a1c6ab7f9df` |
| `alias:department-of-war` | `yes` / `no` | `yes` | `sha256:6667088e282f00469e551604f0f4fbb43a6f4243e3693c42183f459fedbfd327` |
| `alias:defense-innovation-unit` | `yes` / `no` | `yes` | `sha256:406f34443038ed62fd76de54c2e5e6eb04a03755f95e86ea8504e6ba61c97258` |
| `alias:federal-energy-regulatory-commision` | `yes` / `no` | `no` | `sha256:205b93126f69537211be22566162610037bf2f82d1c62d9c7e5aa80620cddbb0` |
| `alias:general-accounting-office` | `yes` / `no` | `yes` | `sha256:e4d1051b94bca78a2cef659ec6a60b0ed934abd2a7b43ffe507ba09a088341ad` |
| `alias:national-counterterrorism-center` | `yes` / `no` | `yes` | `sha256:ffc1805a362dbb61dbf86e633c8dbbf97d15c1827ce4d1b112cb487ba67aad43` |
| `alias:energy` | `yes` / `no` | `no` | `sha256:70054786c33120a3009588fae9a146566bf7392d006abbb8f18cf5006e8ab9e1` |
| `alias:office-of-science-and-technology-policy` | `yes` / `no` | `yes` | `sha256:48f1a7085f8947bc729a7311429b11eb57082c46d8f25f77cef00db2115868d7` |
| `alias:commission-on-international-religious-freedom` | `yes` / `no` | `yes` | `sha256:e7c65cd01e9fc86c73b1e73fa11f112e289fe9e9516b5da98931ba61ef93cdd5` |
| `alias:office-of-information-and-regulatory-affairs` | `yes` / `no` | `yes` | `sha256:0c9bb1691cd38cde1a29cc6b5602e8f34e31559b3e043c0a65004a07988d44f5` |
| `alias:copyright-office` | `yes` / `no` | `yes` | `sha256:d44eae5dfe22c64b54fd7cf796698d6ac7c73bcebc8da40232c8f3866dff50a0` |
| `alias:federal-bureau-of-prisons` | `yes` / `no` | `yes` | `sha256:59d1a84a5781b7b8db27e904e1f862cda243affef45d90b7474b1e3e73792d79` |
| `alias:transportation-command` | `yes` / `no` | `yes` | `sha256:57c75184c441cdab20f0b2064ef829f3bc2878721576e44a460d707d05f351b5` |
| `alias:education` | `yes` / `no` | `no` | `sha256:8ae78724327999d174e7106afb96bf610e17b6af3529f48d1dd20fc179841d90` |
| `alias:usmc` | `yes` / `no` | `yes` | `sha256:6c65859a9ae642f785eb95da5acaac0a1ab2241a35e26d47148f328a8778852a` |
| `alias:national-guard-bureau` | `yes` / `no` | `yes` | `sha256:b8d0616898d2464affb496c68e0cca4e30a032cd6443a90b2a119ec62c6a7c04` |
| `alias:national-science-board` | `yes` / `no` | `yes` | `sha256:8b79af731666d7906924f5d8242884c626675edb28d1ae51c3f5e6ee2b01f8e3` |
