<!-- markdownlint-disable MD013 -->

# Agency registry alias batch — owner adjudication sheet

Generated from [agency-registry-alias-batch-candidates.json](agency-registry-alias-batch-candidates.json) and [agency-registry-alias-batch-decisions.json](agency-registry-alias-batch-decisions.json) by `tools/assemble_agency_registry_alias_batch.py`; its default run fails if this sheet disagrees with either. **Do not edit this sheet.** You (reviewer `urn:ref:reviewer:refspec-owner`) answer through the question tool or by editing the decisions file, exactly as for batch 1: each decision is keyed by the alias id and records the answer, the date, the channel and the item's `content_digest` (the Decision keys table). Every row is `candidate-pending-owner-adjudication`. The plan this batch serves is [agency-registry-alias-plan.md](agency-registry-alias-plan.md).

Decisions recorded: 70 current, 0 stale, 0 of 70 undecided. Candidates digest `sha256:f27a8b66b414ed8c75153340997623b589c5fe1820d75e60ec73953d361c0b82`; demand evidence `research/evidence/agency-alias-demand-2026-11-08/federal-misses.json` (`sha256:48d323915e517163e05166167eebce089043a3b4e65f13ea65b218f0a5eb2676`).

**Demand.** congressional-tech's 3,662 federal-typed witness appearances: 2,193 already match a pinned FR name or short name, 327 name no organization, and the rest split into 573 distinct unmatched keys. 130 keys pass the thresholds (3 federal appearances, or 25 of any witness type), and each is below exactly once: 12 mechanical, 58 judgment, 1 already resolvable, 59 excluded. Counts read federal / all.

**How to answer fast.** Every row carries a recommended answer and its reason. Answering every row with its recommendation is one instruction ("accept the recommendations"), and any row can be answered otherwise by id. A part-of row resolves an FR-keyed consumer to the FR record the unit sits in and claims no identity; where same-or-part-of is unclear the sheet recommends part-of, because the FR id is the same and nothing is claimed.

## Mechanical (12) — recommended: yes to all

Each follows from the pinned rosters by a stated rule and needs no hand input: `frShortNameEquality` (the FR record's short name), `frNameWordOrder` (its name with the trailing organization word moved to the front), `reviewedIdentityPublisherName` (the name of a regulations.gov record REF-038's reviewed identity maps to exactly this FR record).

| Id | Spellings seen | Demand | Resolves to | Basis | Decision |
| --- | --- | --- | --- | --- | --- |
| `alias:bureau-of-land-management` | Bureau of Land Management (18); U.S. Bureau of Land Management (1); United States Bureau of Land Management (1) | 20 / 50 | FR 275 Land Management Bureau | `frNameWordOrder`, `reviewedIdentityPublisherName` | **yes** (2026-11-08, questionTool) |
| `alias:bureau-of-reclamation` | U.S. Bureau of Reclamation (11); Bureau of Reclamation (4) | 15 / 49 | FR 446 Reclamation Bureau | `frNameWordOrder`, `reviewedIdentityPublisherName` | **yes** (2026-11-08, questionTool) |
| `alias:office-of-director-of-national-intelligence` | Office of the Director of National Intelligence (13) | 13 / 93 | FR 354 National Intelligence, Office of the National Director | `reviewedIdentityPublisherName` | **yes** (2026-11-08, questionTool) |
| `alias:office-of-management-and-budget` | Office of Management and Budget (8); U.S. Office of Management and Budget (2); The Office of Management and Budget (1) | 11 / 252 | FR 280 Management and Budget Office | `frNameWordOrder`, `reviewedIdentityPublisherName` | **yes** (2026-11-08, questionTool) |
| `alias:bureau-of-ocean-energy-management` | Bureau of Ocean Energy Management (10) | 10 / 19 | FR 575 Ocean Energy Management Bureau | `frNameWordOrder`, `reviewedIdentityPublisherName` | **yes** (2026-11-08, questionTool) |
| `alias:bureau-of-safety-and-environmental-enforcement` | Bureau of Safety and Environmental Enforcement (9) | 9 / 11 | FR 576 Safety and Environmental Enforcement Bureau | `frNameWordOrder`, `reviewedIdentityPublisherName` | **yes** (2026-11-08, questionTool) |
| `alias:office-of-special-counsel` | Office of Special Counsel (3); U.S. Office of Special Counsel (3) | 6 / 31 | FR 473 Special Counsel Office | `frNameWordOrder`, `reviewedIdentityPublisherName` | **yes** (2026-11-08, questionTool) |
| `alias:bureau-of-indian-affairs` | Bureau of Indian Affairs (4) | 4 / 14 | FR 234 Indian Affairs Bureau | `frNameWordOrder`, `reviewedIdentityPublisherName` | **yes** (2026-11-08, questionTool) |
| `alias:office-of-personnel-management` | U.S. Office of Personnel Management (3) | 3 / 138 | FR 406 Personnel Management Office | `frNameWordOrder`, `reviewedIdentityPublisherName` | **yes** (2026-11-08, questionTool) |
| `alias:office-of-surface-mining-reclamation-and-enforcement` | Office of Surface Mining Reclamation and Enforcement (3) | 3 / 8 | FR 480 Surface Mining Reclamation and Enforcement Office | `frNameWordOrder`, `reviewedIdentityPublisherName` | **yes** (2026-11-08, questionTool) |
| `alias:office-of-science-and-technology-policy` | Office of Science and Technology Policy (2) | 2 / 35 | FR 464 Science and Technology Policy Office | `frNameWordOrder`, `reviewedIdentityPublisherName` | **yes** (2026-11-08, questionTool) |
| `alias:copyright-office` | U.S. Copyright Office (1); United States Copyright Office (1) | 2 / 27 | FR 87 Copyright Office, Library of Congress | `reviewedIdentityPublisherName` | **yes** (2026-11-08, questionTool) |

## Judgment (58)

Every cited record is retained under `research/evidence/agency-alias-records-2026-11-08/` (fetched 2026-11-08 from govinfo and the Federal Register) and read: the tool refuses a row whose quoted passage is not in the retained bytes, and the release refuses an adopted alias whose record no longer is. A row whose source check is not `confirmed` went back to the owner on 2026-11-08 instead of being adopted.

### `alias:veterans-health-administration` — Veterans Health Administration (49); (VISN 17) Veterans Health Administration (1); Veterans Health Administration (VHA) (1)

| Field | Value |
| --- | --- |
| Demand (federal / all) | 51 / 238 |
| Names | OPM `VATA` VETERANS HEALTH ADMINISTRATION |
| FR-keyed consumers get | FR 520 Veterans Affairs Department (part of) |
| Basis | `unitWithinFrAgency` |
| Reasoning | VHA is an administration of the Department of Veterans Affairs; OPM holds it as VATA, the FR does not. |
| Records read | [38 U.S.C. 7301](https://www.govinfo.gov/content/pkg/USCODE-2024-title38/html/USCODE-2024-title38-partV-chap73-subchapI-sec7301.htm): "There is in the Department of Veterans Affairs a Veterans Health Administration." |
| Source check | confirmed |
| Answers | `yes` / `no` |
| Recommended | **yes** — The unit has no FR record; a part-of row gives the FR id of the organization it sits in, and claims no identity. |
| Owner decision / date | **yes** (2026-11-08, questionTool) |

### `alias:army` — U.S. Army (23); United States Army (20)

| Field | Value |
| --- | --- |
| Demand (federal / all) | 43 / 348 |
| Names | none held |
| FR-keyed consumers get | FR 32 Army Department (part of) |
| Basis | `militaryServiceOfDepartment` |
| Reasoning | The Army is the service the Department of the Army (FR 32, 'Army Department') organizes; OPM's AR is the department, not the service. |
| Records read | [10 U.S.C. 7062](https://www.govinfo.gov/content/pkg/USCODE-2024-title10/html/USCODE-2024-title10-subtitleB-partI-chap707-sec7062.htm): "the Army, within the Department of the Army, includes land combat and service forces" |
| Source check | confirmed |
| Answers | `1` Yes, as the same organization: the alias resolves to the FR department record with no qualifier. / `2` Yes, as part of it: the alias resolves to the FR department record, marked part-of (the service is the department's uniformed component). / `3` No alias. |
| Recommended | **2** — Option 2 gives the consumer the same FR id as option 1 without claiming the service and the department are one organization; the department also holds civilian offices the service is not. |
| Owner decision / date | **2** (2026-11-08, questionTool) |

### `alias:navy` — United States Navy (25); U.S. Navy (18)

| Field | Value |
| --- | --- |
| Demand (federal / all) | 43 / 293 |
| Names | none held |
| FR-keyed consumers get | FR 378 Navy Department (part of) |
| Basis | `militaryServiceOfDepartment` |
| Reasoning | The Navy is a service of the Department of the Navy (FR 378, 'Navy Department'), which also holds the Marine Corps. |
| Records read | [10 U.S.C. 8062](https://www.govinfo.gov/content/pkg/USCODE-2024-title10/html/USCODE-2024-title10-subtitleC-partI-chap807-sec8062.htm): "The Navy, within the Department of the Navy, includes, in general, naval combat and service forces" |
| Source check | confirmed |
| Answers | `1` Yes, as the same organization: the alias resolves to the FR department record with no qualifier. / `2` Yes, as part of it: the alias resolves to the FR department record, marked part-of (the service is the department's uniformed component). / `3` No alias. |
| Recommended | **2** — Option 2 gives the consumer the same FR id as option 1 without claiming the service and the department are one organization; the department also holds civilian offices the service is not. |
| Owner decision / date | **2** (2026-11-08, questionTool) |

### `alias:veterans-benefits-administration` — Veterans Benefits Administration (34)

| Field | Value |
| --- | --- |
| Demand (federal / all) | 34 / 165 |
| Names | OPM `VALA` VETERANS BENEFITS ADMINISTRATION |
| FR-keyed consumers get | FR 520 Veterans Affairs Department (part of) |
| Basis | `unitWithinFrAgency` |
| Reasoning | VBA is an administration of the Department of Veterans Affairs; OPM holds it as VALA. |
| Records read | [38 U.S.C. 7701](https://www.govinfo.gov/content/pkg/USCODE-2024-title38/html/USCODE-2024-title38-partV-chap77-subchapI-sec7701.htm): "There is in the Department of Veterans Affairs a Veterans Benefits Administration." |
| Source check | confirmed |
| Answers | `yes` / `no` |
| Recommended | **yes** — The unit has no FR record; a part-of row gives the FR id of the organization it sits in, and claims no identity. |
| Owner decision / date | **yes** (2026-11-08, questionTool) |

### `alias:air-force` — United States Air Force (18); U.S. Air Force (14)

| Field | Value |
| --- | --- |
| Demand (federal / all) | 32 / 298 |
| Names | none held |
| FR-keyed consumers get | FR 13 Air Force Department (part of) |
| Basis | `militaryServiceOfDepartment` |
| Reasoning | The Air Force is a service of the Department of the Air Force (FR 13), which also holds the Space Force. |
| Records read | [10 U.S.C. 9062](https://www.govinfo.gov/content/pkg/USCODE-2024-title10/html/USCODE-2024-title10-subtitleD-partI-chap907-sec9062.htm): "There is a United States Air Force within the Department of the Air Force." |
| Source check | confirmed |
| Answers | `1` Yes, as the same organization: the alias resolves to the FR department record with no qualifier. / `2` Yes, as part of it: the alias resolves to the FR department record, marked part-of (the service is the department's uniformed component). / `3` No alias. |
| Recommended | **2** — Option 2 gives the consumer the same FR id as option 1 without claiming the service and the department are one organization; the department also holds civilian offices the service is not. |
| Owner decision / date | **2** (2026-11-08, questionTool) |

### `alias:marine-corps` — United States Marine Corps (19); U.S. Marine Corps (11); Marine Corps (1)

| Field | Value |
| --- | --- |
| Demand (federal / all) | 32 / 253 |
| Names | OPM `NV27` U.S. MARINE CORPS |
| FR-keyed consumers get | FR 378 Navy Department (part of) |
| Basis | `militaryServiceOfDepartment` |
| Reasoning | The Marine Corps is a service within the Department of the Navy (FR 378); OPM holds it as NV27. |
| Records read | [10 U.S.C. 8063](https://www.govinfo.gov/content/pkg/USCODE-2024-title10/html/USCODE-2024-title10-subtitleC-partI-chap807-sec8063.htm): "The Marine Corps, within the Department of the Navy, shall be so organized" |
| Source check | confirmed |
| Answers | `yes` / `no` |
| Recommended | **yes** — The unit has no FR record; a part-of row gives the FR id of the organization it sits in, and claims no identity. |
| Owner decision / date | **yes** (2026-11-08, questionTool) |

### `alias:congressional-research-service` — Congressional Research Service (27)

| Field | Value |
| --- | --- |
| Demand (federal / all) | 27 / 233 |
| Names | none held |
| FR-keyed consumers get | FR 277 Library of Congress (part of) |
| Basis | `unitWithinFrAgency` |
| Reasoning | CRS is a department of the Library of Congress (FR 277); no held roster holds it. |
| Records read | [2 U.S.C. 166](https://www.govinfo.gov/content/pkg/USCODE-2024-title2/html/USCODE-2024-title2-chap5-sec166.htm): "is hereby continued as a separate department in the Library of Congress and is redesignated the" |
| Source check | confirmed |
| Answers | `yes` / `no` |
| Recommended | **yes** — The unit has no FR record; a part-of row gives the FR id of the organization it sits in, and claims no identity. |
| Owner decision / date | **yes** (2026-11-08, questionTool) |

### `alias:office-of-secretary-of-defense` — Office of the Secretary of Defense (22)

| Field | Value |
| --- | --- |
| Demand (federal / all) | 22 / 107 |
| Names | OPM `DD01` OFFICE OF THE SECRETARY OF DEFENSE |
| FR-keyed consumers get | FR 103 Defense Department (part of) |
| Basis | `unitWithinFrAgency` |
| Reasoning | OSD is the Secretary's principal staff element in the Department of Defense (FR 103); OPM holds it as DD01. |
| Records read | [10 U.S.C. 131](https://www.govinfo.gov/content/pkg/USCODE-2024-title10/html/USCODE-2024-title10-subtitleA-partI-chap4-sec131.htm): "There is in the Department of Defense an Office of the Secretary of Defense." |
| Source check | confirmed |
| Answers | `yes` / `no` |
| Recommended | **yes** — The unit has no FR record; a part-of row gives the FR id of the organization it sits in, and claims no identity. |
| Owner decision / date | **yes** (2026-11-08, questionTool) |

### `alias:national-security-agency` — National Security Agency (15)

| Field | Value |
| --- | --- |
| Demand (federal / all) | 15 / 47 |
| Names | none held |
| FR-keyed consumers get | FR 367 National Security Agency/Central Security Service |
| Basis | `publisherNameVariant` |
| Reasoning | FR 367 is 'National Security Agency/Central Security Service'; the Federal Hierarchy names the same agency 'NATIONAL SECURITY AGENCY (NSA)' (300000420). |
| Records read | the held roster records named |
| Source check | confirmed |
| Answers | `yes` / `no` |
| Recommended | **yes** — Dropping the Central Security Service half of a dual-named agency names the same agency, as the Federal Hierarchy does. |
| Owner decision / date | **yes** (2026-11-08, questionTool) |

### `alias:army-corps-of-engineers` — U.S. Army Corps of Engineers (11); Army Corps of Engineers (1)

| Field | Value |
| --- | --- |
| Demand (federal / all) | 12 / 159 |
| Names | none held |
| FR-keyed consumers get | FR 142 Engineers Corps |
| Basis | `publisherNameVariant` |
| Reasoning | FR 142 is 'Engineers Corps'; eCFR's short name for the same corps is 'Army Corps of Engineers'. |
| Records read | the held roster records named |
| Source check | confirmed |
| Answers | `yes` / `no` |
| Recommended | **yes** — Another publisher's name for the FR record's organization. |
| Owner decision / date | **yes** (2026-11-08, questionTool) |

### `alias:board-of-governors-of-federal-reserve-system` — Board of Governors of the Federal Reserve System (9)

| Field | Value |
| --- | --- |
| Demand (federal / all) | 9 / 300 |
| Names | none held |
| FR-keyed consumers get | FR 188 Federal Reserve System (part of) |
| Basis | `unitWithinFrAgency` |
| Reasoning | FR 188 is 'Federal Reserve System'; eCFR holds the Board of Governors and the System as two records. |
| Records read | [12 U.S.C. 241](https://www.govinfo.gov/content/pkg/USCODE-2024-title12/html/USCODE-2024-title12-chap3-subchapII-sec241.htm): "The Board of Governors of the Federal Reserve System (hereinafter referred to as the" |
| Source check | confirmed |
| Answers | `1` Yes, as the same organization as FR 188. / `2` Yes, as part of FR 188 (the System's governing board). / `3` No alias. |
| Recommended | **2** — Option 2 gives the same FR id without claiming the Board is the whole System, which eCFR keeps apart. |
| Owner decision / date | **2** (2026-11-08, questionTool) |

### `alias:space-force` — United States Space Force (7); Space Force (1); U.S. Space Force (1)

| Field | Value |
| --- | --- |
| Demand (federal / all) | 9 / 41 |
| Names | OPM `AF4G` UNITED STATES SPACE FORCE |
| FR-keyed consumers get | FR 13 Air Force Department (part of) |
| Basis | `militaryServiceOfDepartment` |
| Reasoning | The Space Force is a service within the Department of the Air Force (FR 13); OPM holds it as AF4G. |
| Records read | [10 U.S.C. 9081](https://www.govinfo.gov/content/pkg/USCODE-2024-title10/html/USCODE-2024-title10-subtitleD-partI-chap908-sec9081.htm): "There is established a United States Space Force as an armed force within the Department of the Air Force." |
| Source check | confirmed |
| Answers | `yes` / `no` |
| Recommended | **yes** — The unit has no FR record; a part-of row gives the FR id of the organization it sits in, and claims no identity. |
| Owner decision / date | **yes** (2026-11-08, questionTool) |

### `alias:national-reconnaissance-office` — National Reconnaissance Office (7)

| Field | Value |
| --- | --- |
| Demand (federal / all) | 7 / 27 |
| Names | Federal Hierarchy `500019037` NATIONAL RECONNAISSANCE OFFICE (NRO) |
| FR-keyed consumers get | FR 103 Defense Department (part of) |
| Basis | `unitWithinFrAgency` |
| Reasoning | NRO is a Department of Defense agency; the Federal Hierarchy holds it as 500019037 ('NATIONAL RECONNAISSANCE OFFICE (NRO)') under DEPT OF DEFENSE. |
| Records read | the held roster records named |
| Source check | confirmed |
| Answers | `yes` / `no` |
| Recommended | **yes** — The unit has no FR record; a part-of row gives the FR id of the organization it sits in, and claims no identity. |
| Owner decision / date | **yes** (2026-11-08, questionTool) |

### `alias:veterans-benefit-administration` — Veterans Benefit Administration (7)

| Field | Value |
| --- | --- |
| Demand (federal / all) | 7 / 8 |
| Names | none held |
| FR-keyed consumers get | FR 520 Veterans Affairs Department |
| Basis | `misspelling` |
| Reasoning | A misspelling of the Veterans Benefits Administration. |
| Records read | the held roster records named |
| Source check | confirmed |
| Answers | `yes` / `no` |
| Recommended | **no** — No publisher spells it so; a misspelling is the consumer's fuzzy matcher's job, not a reviewed alias. |
| Owner decision / date | **no** (2026-11-08, questionTool) |

### `alias:export-import-bank-of` — Export-Import Bank of the United States (6)

| Field | Value |
| --- | --- |
| Demand (federal / all) | 6 / 51 |
| Names | none held |
| FR-keyed consumers get | FR 151 Export-Import Bank |
| Basis | `publisherNameVariant` |
| Reasoning | 'Export-Import Bank of the United States' is the statutory name of FR 151 ('Export-Import Bank'). |
| Records read | [12 U.S.C. 635](https://www.govinfo.gov/content/pkg/USCODE-2024-title12/html/USCODE-2024-title12-chap6A-subchapI-sec635.htm): "There is created a corporation with the name Export-Import Bank of the United States, which shall be an agency of the United States of America." |
| Source check | confirmed |
| Answers | `yes` / `no` |
| Recommended | **yes** — The statutory name of the FR record's organization. Batch 1's EIB/USEIB non-emission concerns an eCFR bridge, not this. |
| Owner decision / date | **yes** (2026-11-08, questionTool) |

### `alias:capitol-police` — United States Capitol Police (5); U.S. Capitol Police (1)

| Field | Value |
| --- | --- |
| Demand (federal / all) | 6 / 49 |
| Names | Federal Hierarchy `500193110` UNITED STATES CAPITOL POLICE |
| FR-keyed consumers get | no FR id |
| Basis | `noFrRecord` |
| Reasoning | The United States Capitol Police, a legislative-branch agency; the Federal Hierarchy holds it (500193110) under THE LEGISLATIVE BRANCH, the FR does not. |
| Records read | [2 U.S.C. 1901](https://www.govinfo.gov/content/pkg/USCODE-2024-title2/html/USCODE-2024-title2-chap29-subchapI-partA-sec1901.htm): "There shall be a Capitol police." |
| Source check | confirmed |
| Answers | `yes` / `no` |
| Recommended | **yes** — Names the Federal Hierarchy record; an FR-keyed consumer gets no FR id, which is the truth. |
| Owner decision / date | **yes** (2026-11-08, questionTool) |

### `alias:strategic-command` — U.S. Strategic Command (4); United States Strategic Command (2)

| Field | Value |
| --- | --- |
| Demand (federal / all) | 6 / 39 |
| Names | none held |
| FR-keyed consumers get | FR 103 Defense Department (part of) |
| Basis | `unitWithinFrAgency` |
| Reasoning | U.S. Strategic Command; no held roster holds the command itself. |
| Records read | [10 U.S.C. 111](https://www.govinfo.gov/content/pkg/USCODE-2024-title10/html/USCODE-2024-title10-subtitleA-partI-chap2-sec111.htm): "(9) The unified and specified combatant commands."; [10 U.S.C. 161](https://www.govinfo.gov/content/pkg/USCODE-2024-title10/html/USCODE-2024-title10-subtitleA-partI-chap6-sec161.htm): "the space-related responsibilities previously assigned to the Commander, United States Strategic Command" |
| Source check | confirmed |
| Answers | `yes` / `no` |
| Recommended | **yes** — The unified and specified combatant commands are part of the Department of Defense (10 U.S.C. 111(b)(9)) and have no FR record; part-of DOD is the only FR resolution, and it claims no identity. |
| Owner decision / date | **yes** (2026-11-08, questionTool) |

### `alias:joint-staff` — The Joint Staff (4); Joint Staff (2)

| Field | Value |
| --- | --- |
| Demand (federal / all) | 6 / 33 |
| Names | none held |
| FR-keyed consumers get | FR 103 Defense Department (part of) |
| Basis | `unitWithinFrAgency` |
| Reasoning | The Joint Staff serves the Chairman of the Joint Chiefs of Staff in the Department of Defense; no held roster holds it alone. |
| Records read | [10 U.S.C. 155](https://www.govinfo.gov/content/pkg/USCODE-2024-title10/html/USCODE-2024-title10-subtitleA-partI-chap5-sec155.htm): "There is a Joint Staff under the Chairman of the Joint Chiefs of Staff."; [10 U.S.C. 111](https://www.govinfo.gov/content/pkg/USCODE-2024-title10/html/USCODE-2024-title10-subtitleA-partI-chap2-sec111.htm): "(2) The Joint Chiefs of Staff. (3) The Joint Staff." |
| Source check | confirmed |
| Answers | `yes` / `no` |
| Recommended | **yes** — The unit has no FR record; a part-of row gives the FR id of the organization it sits in, and claims no identity. |
| Owner decision / date | **yes** (2026-11-08, questionTool) |

### `alias:missile-defense-agency` — Missile Defense Agency (6)

| Field | Value |
| --- | --- |
| Demand (federal / all) | 6 / 29 |
| Names | Federal Hierarchy `300000429` MISSILE DEFENSE AGENCY (MDA) |
| FR-keyed consumers get | FR 103 Defense Department (part of) |
| Basis | `unitWithinFrAgency` |
| Reasoning | MDA is a Department of Defense agency; the Federal Hierarchy holds it as 300000429 under DEPT OF DEFENSE. |
| Records read | the held roster records named |
| Source check | confirmed |
| Answers | `yes` / `no` |
| Recommended | **yes** — The unit has no FR record; a part-of row gives the FR id of the organization it sits in, and claims no identity. |
| Owner decision / date | **yes** (2026-11-08, questionTool) |

### `alias:cyber-command` — Cyber Command (2); U.S. Cyber Command (2); United States Cyber Command (2)

| Field | Value |
| --- | --- |
| Demand (federal / all) | 6 / 20 |
| Names | Federal Hierarchy `300000421` U.S. CYBER COMMAND |
| FR-keyed consumers get | FR 103 Defense Department (part of) |
| Basis | `unitWithinFrAgency` |
| Reasoning | U.S. Cyber Command; the Federal Hierarchy holds it as 300000421 under DEPT OF DEFENSE. |
| Records read | [10 U.S.C. 111](https://www.govinfo.gov/content/pkg/USCODE-2024-title10/html/USCODE-2024-title10-subtitleA-partI-chap2-sec111.htm): "(9) The unified and specified combatant commands."; [10 U.S.C. 167b](https://www.govinfo.gov/content/pkg/USCODE-2024-title10/html/USCODE-2024-title10-subtitleA-partI-chap6-sec167b.htm): "I assign to U.S. Cyber Command: (1) all the general responsibilities of a Unified Combatant Command" |
| Source check | confirmed |
| Answers | `yes` / `no` |
| Recommended | **yes** — The unified and specified combatant commands are part of the Department of Defense (10 U.S.C. 111(b)(9)) and have no FR record; part-of DOD is the only FR resolution, and it claims no identity. |
| Owner decision / date | **yes** (2026-11-08, questionTool) |

### `alias:special-operations-command` — U.S. Special Operations Command (3); United States Special Operations Command (2)

| Field | Value |
| --- | --- |
| Demand (federal / all) | 5 / 44 |
| Names | Federal Hierarchy `300000430` U.S. SPECIAL OPERATIONS COMMAND (USSOCOM) |
| FR-keyed consumers get | FR 103 Defense Department (part of) |
| Basis | `unitWithinFrAgency` |
| Reasoning | U.S. Special Operations Command; the Federal Hierarchy holds it as 300000430 under DEPT OF DEFENSE. |
| Records read | [10 U.S.C. 111](https://www.govinfo.gov/content/pkg/USCODE-2024-title10/html/USCODE-2024-title10-subtitleA-partI-chap2-sec111.htm): "(9) The unified and specified combatant commands."; [10 U.S.C. 167](https://www.govinfo.gov/content/pkg/USCODE-2024-title10/html/USCODE-2024-title10-subtitleA-partI-chap6-sec167.htm): "shall establish under section 161 of this title a unified combatant command for special operations forces" |
| Source check | confirmed |
| Answers | `yes` / `no` |
| Recommended | **yes** — The unified and specified combatant commands are part of the Department of Defense (10 U.S.C. 111(b)(9)) and have no FR record; part-of DOD is the only FR resolution, and it claims no identity. |
| Owner decision / date | **yes** (2026-11-08, questionTool) |

### `alias:africa-command` — United States Africa Command (3); U.S. Africa Command (2)

| Field | Value |
| --- | --- |
| Demand (federal / all) | 5 / 26 |
| Names | none held |
| FR-keyed consumers get | FR 103 Defense Department (part of) |
| Basis | `unitWithinFrAgency` |
| Reasoning | U.S. Africa Command; OPM's AF1R is an Air Force code, so not taken as the command. DoD's FOIA rule names it among the DoD Components, beside the other combatant commands. |
| Records read | [10 U.S.C. 111](https://www.govinfo.gov/content/pkg/USCODE-2024-title10/html/USCODE-2024-title10-subtitleA-partI-chap2-sec111.htm): "(9) The unified and specified combatant commands."; [82 FR 1192 (2017-01-05), FR Doc 2016-31686, DoD Freedom of Information Act (FOIA) Program (32 CFR part 286)](https://www.federalregister.gov/documents/full_text/text/2017/01/05/2016-31686.txt): "United States Africa Command, United States Central Command, United States European Command, United States Northern Command, United States Pacific Command, United States Special Operations Command, United States Strategic Command, and United States Transportation Command."; [82 FR 1192 (2017-01-05), FR Doc 2016-31686, 32 CFR 286.2](https://www.federalregister.gov/documents/full_text/text/2017/01/05/2016-31686.txt): "the Combatant Commands, the Office of the Inspector General of the Department of Defense, the Defense Agencies, the DoD Field Activities, and all other organizational entities within the DoD" |
| Source check | confirmed |
| Answers | `yes` / `no` |
| Recommended | **yes** — The unified and specified combatant commands are part of the Department of Defense (10 U.S.C. 111(b)(9)) and have no FR record; part-of DOD is the only FR resolution, and it claims no identity. |
| Owner decision / date | **yes** (2026-11-08, questionTool) |

### `alias:federal-bureau-of-investigations` — Federal Bureau of Investigations (5)

| Field | Value |
| --- | --- |
| Demand (federal / all) | 5 / 17 |
| Names | none held |
| FR-keyed consumers get | FR 160 Federal Bureau of Investigation |
| Basis | `misspelling` |
| Reasoning | A misspelling of the Federal Bureau of Investigation (FR 160). |
| Records read | the held roster records named |
| Source check | confirmed |
| Answers | `yes` / `no` |
| Recommended | **no** — No publisher spells it so; a misspelling is the consumer's fuzzy matcher's job, not a reviewed alias. |
| Owner decision / date | **no** (2026-11-08, questionTool) |

### `alias:national-cemetery-administration` — National Cemetery Administration (5)

| Field | Value |
| --- | --- |
| Demand (federal / all) | 5 / 15 |
| Names | OPM `VAPA` NATIONAL CEMETERY ADMINISTRATION |
| FR-keyed consumers get | FR 520 Veterans Affairs Department (part of) |
| Basis | `unitWithinFrAgency` |
| Reasoning | NCA is an administration of the Department of Veterans Affairs; OPM holds it as VAPA. |
| Records read | [38 U.S.C. 2400](https://www.govinfo.gov/content/pkg/USCODE-2024-title38/html/USCODE-2024-title38-partII-chap24-sec2400.htm): "There shall be within the Department a National Cemetery Administration" |
| Source check | confirmed |
| Answers | `yes` / `no` |
| Recommended | **yes** — The unit has no FR record; a part-of row gives the FR id of the organization it sits in, and claims no identity. |
| Owner decision / date | **yes** (2026-11-08, questionTool) |

### `alias:office-of-comptroller-of-currency` — Office of the Comptroller of the Currency (3); Office of the Comptroller of Currency (1)

| Field | Value |
| --- | --- |
| Demand (federal / all) | 4 / 141 |
| Names | none held |
| FR-keyed consumers get | FR 80 Comptroller of the Currency |
| Basis | `publisherNameVariant` |
| Reasoning | FR 80 is 'Comptroller of the Currency'; the statute names the agency the Office of the Comptroller of the Currency, as the Federal Hierarchy and OPM do. |
| Records read | [12 U.S.C. 1](https://www.govinfo.gov/content/pkg/USCODE-2024-title12/html/USCODE-2024-title12-chap1-sec1.htm): "There is established in the Department of the Treasury a bureau to be known as the" |
| Source check | confirmed |
| Answers | `yes` / `no` |
| Recommended | **yes** — The FR names the office by its head; the statutory name is the same agency. |
| Owner decision / date | **yes** (2026-11-08, questionTool) |

### `alias:defense-health-agency` — Defense Health Agency (4)

| Field | Value |
| --- | --- |
| Demand (federal / all) | 4 / 16 |
| Names | Federal Hierarchy `300000422` DEFENSE HEALTH AGENCY (DHA) |
| FR-keyed consumers get | FR 103 Defense Department (part of) |
| Basis | `unitWithinFrAgency` |
| Reasoning | DHA is a Department of Defense agency; the Federal Hierarchy holds it as 300000422 under DEPT OF DEFENSE. |
| Records read | the held roster records named |
| Source check | confirmed |
| Answers | `yes` / `no` |
| Recommended | **yes** — The unit has no FR record; a part-of row gives the FR id of the organization it sits in, and claims no identity. |
| Owner decision / date | **yes** (2026-11-08, questionTool) |

### `alias:space-command` — U.S. Space Command (4)

| Field | Value |
| --- | --- |
| Demand (federal / all) | 4 / 15 |
| Names | none held |
| FR-keyed consumers get | FR 103 Defense Department (part of) |
| Basis | `unitWithinFrAgency` |
| Reasoning | U.S. Space Command; no held roster holds the command itself. |
| Records read | [10 U.S.C. 111](https://www.govinfo.gov/content/pkg/USCODE-2024-title10/html/USCODE-2024-title10-subtitleA-partI-chap2-sec111.htm): "(9) The unified and specified combatant commands."; [10 U.S.C. 161](https://www.govinfo.gov/content/pkg/USCODE-2024-title10/html/USCODE-2024-title10-subtitleA-partI-chap6-sec161.htm): "I assign to United States Space Command: (1) all the general responsibilities of a Unified Combatant Command" |
| Source check | confirmed |
| Answers | `yes` / `no` |
| Recommended | **yes** — The unified and specified combatant commands are part of the Department of Defense (10 U.S.C. 111(b)(9)) and have no FR record; part-of DOD is the only FR resolution, and it claims no identity. |
| Owner decision / date | **yes** (2026-11-08, questionTool) |

### `alias:usda-office-of-inspector-general` — USDA Office of Inspector General (4)

| Field | Value |
| --- | --- |
| Demand (federal / all) | 4 / 11 |
| Names | none held |
| FR-keyed consumers get | FR 244 Inspector General Office, Agriculture Department |
| Basis | `publisherNameVariant` |
| Reasoning | FR 244 is 'Inspector General Office, Agriculture Department'; this is its name in natural order with the parent's acronym. |
| Records read | the held roster records named |
| Source check | confirmed |
| Answers | `yes` / `no` |
| Recommended | **yes** — The parent acronym makes an otherwise ambiguous 'Office of Inspector General' name exactly one FR record. |
| Owner decision / date | **yes** (2026-11-08, questionTool) |

### `alias:national-forest-system` — National Forest System (4)

| Field | Value |
| --- | --- |
| Demand (federal / all) | 4 / 9 |
| Names | none held |
| FR-keyed consumers get | FR 209 Forest Service (part of) |
| Basis | `unitWithinFrAgency` |
| Reasoning | The National Forest System is the lands the Forest Service (FR 209) administers; as a witness's organization it names the Forest Service's National Forest System deputy area. |
| Records read | [USDA Forest Service, About the Agency: Organization (fs.usda.gov, read 2026-11-08)](https://www.fs.usda.gov/about-agency/organization): "Agency headquarters has the following program units: National Forest System: We manage public lands, known collectively as the National Forest System" |
| Source check | confirmed |
| Answers | `yes` / `no` |
| Recommended | **yes** — The unit has no FR record; a part-of row gives the FR id of the organization it sits in, and claims no identity. |
| Owner decision / date | **yes** (2026-11-08, questionTool) |

### `alias:national-institute-of-health` — National Institute of Health (3); U.S. National Institute of Health (1)

| Field | Value |
| --- | --- |
| Demand (federal / all) | 4 / 6 |
| Names | none held |
| FR-keyed consumers get | FR 353 National Institutes of Health |
| Basis | `misspelling` |
| Reasoning | A misspelling of the National Institutes of Health (FR 353). |
| Records read | the held roster records named |
| Source check | confirmed |
| Answers | `yes` / `no` |
| Recommended | **no** — No publisher spells it so; a misspelling is the consumer's fuzzy matcher's job, not a reviewed alias. |
| Owner decision / date | **no** (2026-11-08, questionTool) |

### `alias:joint-chiefs-of-staff` — Joint Chiefs of Staff (3)

| Field | Value |
| --- | --- |
| Demand (federal / all) | 3 / 56 |
| Names | OPM `DD02` ORGANIZATION OF THE JOINT CHIEFS OF STAFF |
| FR-keyed consumers get | FR 103 Defense Department (part of) |
| Basis | `unitWithinFrAgency` |
| Reasoning | The Joint Chiefs of Staff sit in the Department of Defense; OPM holds their organization as DD02. |
| Records read | [10 U.S.C. 151](https://www.govinfo.gov/content/pkg/USCODE-2024-title10/html/USCODE-2024-title10-subtitleA-partI-chap5-sec151.htm): "There are in the Department of Defense the Joint Chiefs of Staff, headed by the Chairman of the Joint Chiefs of Staff." |
| Source check | confirmed |
| Answers | `yes` / `no` |
| Recommended | **yes** — The unit has no FR record; a part-of row gives the FR id of the organization it sits in, and claims no identity. |
| Owner decision / date | **yes** (2026-11-08, questionTool) |

### `alias:central-command` — U.S. Central Command (2); United States Central Command (1)

| Field | Value |
| --- | --- |
| Demand (federal / all) | 3 / 26 |
| Names | none held |
| FR-keyed consumers get | FR 103 Defense Department (part of) |
| Basis | `unitWithinFrAgency` |
| Reasoning | U.S. Central Command; no held roster holds the command itself. |
| Records read | [10 U.S.C. 111](https://www.govinfo.gov/content/pkg/USCODE-2024-title10/html/USCODE-2024-title10-subtitleA-partI-chap2-sec111.htm): "(9) The unified and specified combatant commands."; [10 U.S.C. 161](https://www.govinfo.gov/content/pkg/USCODE-2024-title10/html/USCODE-2024-title10-subtitleA-partI-chap6-sec161.htm): "whether the boundary between the United States Central and European Commands could create command conflicts" |
| Source check | confirmed |
| Answers | `yes` / `no` |
| Recommended | **yes** — The unified and specified combatant commands are part of the Department of Defense (10 U.S.C. 111(b)(9)) and have no FR record; part-of DOD is the only FR resolution, and it claims no identity. |
| Owner decision / date | **yes** (2026-11-08, questionTool) |

### `alias:european-command` — U.S. European Command (2); United States European Command (1)

| Field | Value |
| --- | --- |
| Demand (federal / all) | 3 / 25 |
| Names | none held |
| FR-keyed consumers get | FR 103 Defense Department (part of) |
| Basis | `unitWithinFrAgency` |
| Reasoning | U.S. European Command; no held roster holds the command itself. |
| Records read | [10 U.S.C. 111](https://www.govinfo.gov/content/pkg/USCODE-2024-title10/html/USCODE-2024-title10-subtitleA-partI-chap2-sec111.htm): "(9) The unified and specified combatant commands."; [10 U.S.C. 161](https://www.govinfo.gov/content/pkg/USCODE-2024-title10/html/USCODE-2024-title10-subtitleA-partI-chap6-sec161.htm): "whether the boundary between the United States Central and European Commands could create command conflicts" |
| Source check | confirmed |
| Answers | `yes` / `no` |
| Recommended | **yes** — The unified and specified combatant commands are part of the Department of Defense (10 U.S.C. 111(b)(9)) and have no FR record; part-of DOD is the only FR resolution, and it claims no identity. |
| Owner decision / date | **yes** (2026-11-08, questionTool) |

### `alias:cybersecurity-and-infrastructure-security-agency` — Cybersecurity and Infrastructure Security Agency (3)

| Field | Value |
| --- | --- |
| Demand (federal / all) | 3 / 22 |
| Names | Federal Hierarchy `500044551` Cybersecurity and Infrastructure Security Agency |
| FR-keyed consumers get | FR 227 Homeland Security Department (part of) |
| Basis | `unitWithinFrAgency` |
| Reasoning | CISA is a Department of Homeland Security agency. REF-038 already maps regulations.gov 'CISA' to Federal Hierarchy 500044551, and batch 1 recorded that the held FR roster has no CISA record (noCounterpartInHeldFRRoster). |
| Records read | [6 U.S.C. 652](https://www.govinfo.gov/content/pkg/USCODE-2024-title6/html/USCODE-2024-title6-chap1-subchapXVIII-partA-sec652.htm): "The National Protection and Programs Directorate of the Department shall, on and after November 16, 2018, be known as the" |
| Source check | confirmed |
| Answers | `yes` / `no` |
| Recommended | **yes** — The unit has no FR record; a part-of row gives the FR id of the organization it sits in, and claims no identity. |
| Owner decision / date | **yes** (2026-11-08, questionTool) |

### `alias:air-force-space-command` — Air Force Space Command (2); U.S. Air Force Space Command (1)

| Field | Value |
| --- | --- |
| Demand (federal / all) | 3 / 19 |
| Names | OPM `AF4G` UNITED STATES SPACE FORCE |
| FR-keyed consumers get | FR 13 Air Force Department (part of) |
| Basis | `statutoryRename` |
| Reasoning | The Space Force's name before 2019-12-20: Pub. L. 116-92 sec. 952(a) redesignated Air Force Space Command the United States Space Force, which 10 U.S.C. 9081 places within the Department of the Air Force (FR 13). A witness's 'Air Force Space Command' therefore names the organization OPM now holds as AF4G (the Space Force), part of the Department of the Air Force. Before 2019 the command was an Air Force major command; no record read states that, and the row does not rest on it. |
| Records read | [10 U.S.C. 9081](https://www.govinfo.gov/content/pkg/USCODE-2024-title10/html/USCODE-2024-title10-subtitleD-partI-chap908-sec9081.htm): "The Air Force Space Command is hereby redesignated as the United States Space Force (USSF)."; [10 U.S.C. 9081](https://www.govinfo.gov/content/pkg/USCODE-2024-title10/html/USCODE-2024-title10-subtitleD-partI-chap908-sec9081.htm): "There is established a United States Space Force as an armed force within the Department of the Air Force." |
| Source check | confirmed |
| Answers | `yes` / `no` |
| Recommended | **yes** — One organization renamed by statute, part of the same department under either name. |
| Owner decision / date | **yes** (2026-11-08, questionTool) |

### `alias:national-institute-of-allergy-and-infectious-diseases` — National Institute of Allergy and Infectious Diseases (3)

| Field | Value |
| --- | --- |
| Demand (federal / all) | 3 / 19 |
| Names | none held |
| FR-keyed consumers get | FR 353 National Institutes of Health (part of) |
| Basis | `unitWithinFrAgency` |
| Reasoning | NIAID is an institute of the National Institutes of Health (FR 353). |
| Records read | [42 U.S.C. 281](https://www.govinfo.gov/content/pkg/USCODE-2024-title42/html/USCODE-2024-title42-chap6A-subchapIII-partA-sec281.htm): "The following agencies of the National Institutes of Health are national research institutes or national centers:"; [42 U.S.C. 281](https://www.govinfo.gov/content/pkg/USCODE-2024-title42/html/USCODE-2024-title42-chap6A-subchapIII-partA-sec281.htm): "(6) The National Institute of Allergy and Infectious Diseases." |
| Source check | confirmed |
| Answers | `yes` / `no` |
| Recommended | **yes** — The unit has no FR record; a part-of row gives the FR id of the organization it sits in, and claims no identity. |
| Owner decision / date | **yes** (2026-11-08, questionTool) |

### `alias:office-of-congressional-workplace-rights` — Office of Congressional Workplace Rights (3)

| Field | Value |
| --- | --- |
| Demand (federal / all) | 3 / 14 |
| Names | OPM `ZG00` OFFICE OF CONGRESSIONAL WORKPLACE RIGHTS. NOTE: ORGANIZATION DOES NOT MAKE HR SUBMISSIONS TO OPM. CODE MAY BE USED FOR OTHER DOCUMENTATION PURPOSES. |
| FR-keyed consumers get | no FR id |
| Basis | `noFrRecord` |
| Reasoning | A legislative-branch office (the Office of Compliance until 2018); OPM holds it as ZG00, the FR does not. |
| Records read | [2 U.S.C. 1381](https://www.govinfo.gov/content/pkg/USCODE-2024-title2/html/USCODE-2024-title2-chap24-subchapIII-sec1381.htm): "There is established, as an independent office within the legislative branch of the Federal Government, the Office of Congressional Workplace Rights." |
| Source check | confirmed |
| Answers | `yes` / `no` |
| Recommended | **yes** — Names the OPM record; no FR id. |
| Owner decision / date | **yes** (2026-11-08, questionTool) |

### `alias:forces-korea` — U.S. Forces Korea (2); United States Forces Korea (1)

| Field | Value |
| --- | --- |
| Demand (federal / all) | 3 / 11 |
| Names | none held |
| FR-keyed consumers get | FR 103 Defense Department (part of) |
| Basis | `unitWithinFrAgency` |
| Reasoning | U.S. Forces Korea, a subordinate unified command of U.S. Pacific (now Indo-Pacific) Command: USPACOM's own answer for the record to the House Armed Services Committee counts its positions among USPACOM's subordinate unified commands. USPACOM is a DoD Component (DoD's FOIA rule), and 10 U.S.C. 111(b)(11) puts every command under a combatant command's control in the Department. |
| Records read | [H.A.S.C. No. 113-14 (2013), Hearing on National Defense Authorization Act for Fiscal Year 2014, U.S. Pacific Command answers for the record (CHRG-113hhrg79955)](https://www.govinfo.gov/content/pkg/CHRG-113hhrg79955/html/CHRG-113hhrg79955.htm): "A total of 686 positions support subordinate unified commands; US Forces Korea (468), US Alaskan Command (66), US Forces Japan (152)."; [82 FR 1192 (2017-01-05), FR Doc 2016-31686, DoD Freedom of Information Act (FOIA) Program (32 CFR part 286)](https://www.federalregister.gov/documents/full_text/text/2017/01/05/2016-31686.txt): "United States Africa Command, United States Central Command, United States European Command, United States Northern Command, United States Pacific Command, United States Special Operations Command, United States Strategic Command, and United States Transportation Command."; [10 U.S.C. 111](https://www.govinfo.gov/content/pkg/USCODE-2024-title10/html/USCODE-2024-title10-subtitleA-partI-chap2-sec111.htm): "(11) All offices, agencies, activities, and commands under the control or supervision of any element named in paragraphs (1) through (10)." |
| Source check | confirmed |
| Answers | `yes` / `no` |
| Recommended | **yes** — Part-of DOD through USPACOM; no record read makes it an organization of its own with an FR record. |
| Owner decision / date | **yes** (2026-11-08, questionTool) |

### `alias:labor` — Labor (3)

| Field | Value |
| --- | --- |
| Demand (federal / all) | 3 / 11 |
| Names | none held |
| FR-keyed consumers get | FR 271 Labor Department |
| Basis | `publisherNameVariant` |
| Reasoning | 'Labor' as a whole organization string; FR 271 is 'Labor Department'. |
| Records read | the held roster records named |
| Source check | confirmed |
| Answers | `yes` / `no` |
| Recommended | **no** — A single common word: in witness titles it is as often a portfolio ('Assistant Secretary for Labor') as the department. |
| Owner decision / date | **no** (2026-11-08, questionTool) |

### `alias:office-of-chief-of-naval-operations` — Office of the Chief of Naval Operations (3)

| Field | Value |
| --- | --- |
| Demand (federal / all) | 3 / 11 |
| Names | none held |
| FR-keyed consumers get | FR 378 Navy Department (part of) |
| Basis | `unitWithinFrAgency` |
| Reasoning | The Office of the Chief of Naval Operations is the Navy's headquarters staff in the Department of the Navy. |
| Records read | [10 U.S.C. 8031](https://www.govinfo.gov/content/pkg/USCODE-2024-title10/html/USCODE-2024-title10-subtitleC-partI-chap805-sec8031.htm): "There is in the executive part of the Department of the Navy an Office of the Chief of Naval Operations." |
| Source check | confirmed |
| Answers | `yes` / `no` |
| Recommended | **yes** — The unit has no FR record; a part-of row gives the FR id of the organization it sits in, and claims no identity. |
| Owner decision / date | **yes** (2026-11-08, questionTool) |

### `alias:headquarters-air-force` — Headquarters U.S. Air Force (3)

| Field | Value |
| --- | --- |
| Demand (federal / all) | 3 / 10 |
| Names | none held |
| FR-keyed consumers get | FR 13 Air Force Department (part of) |
| Basis | `unitWithinFrAgency` |
| Reasoning | Headquarters Air Force (the Secretariat and Air Staff) sits in the Department of the Air Force. |
| Records read | [10 U.S.C. 9031](https://www.govinfo.gov/content/pkg/USCODE-2024-title10/html/USCODE-2024-title10-subtitleD-partI-chap905-sec9031.htm): "There is in the executive part of the Department of the Air Force an Air Staff."; [74 FR 6591 (2009-02-10), FR Doc E9-2782, Department of the Air Force, Privacy Act of 1974; System of Records](https://www.federalregister.gov/documents/full_text/text/2009/02/10/E9-2782.txt): "Deputy Chief of Staff for Personnel, Headquarters United States Air Force, 1040 Air Force Pentagon" |
| Source check | confirmed |
| Answers | `yes` / `no` |
| Recommended | **yes** — The unit has no FR record; a part-of row gives the FR id of the organization it sits in, and claims no identity. |
| Owner decision / date | **yes** (2026-11-08, questionTool) |

### `alias:headquarters-marine-corps` — Headquarters U.S. Marine Corps (2); Headquarters Marine Corps (1)

| Field | Value |
| --- | --- |
| Demand (federal / all) | 3 / 10 |
| Names | none held |
| FR-keyed consumers get | FR 378 Navy Department (part of) |
| Basis | `unitWithinFrAgency` |
| Reasoning | Headquarters, Marine Corps sits in the Department of the Navy. |
| Records read | [10 U.S.C. 8041](https://www.govinfo.gov/content/pkg/USCODE-2024-title10/html/USCODE-2024-title10-subtitleC-partI-chap806-sec8041.htm): "There is in the executive part of the Department of the Navy a Headquarters, Marine Corps." |
| Source check | confirmed |
| Answers | `yes` / `no` |
| Recommended | **yes** — The unit has no FR record; a part-of row gives the FR id of the organization it sits in, and claims no identity. |
| Owner decision / date | **yes** (2026-11-08, questionTool) |

### `alias:health-and-human-services` — Health and Human Services (3)

| Field | Value |
| --- | --- |
| Demand (federal / all) | 3 / 9 |
| Names | none held |
| FR-keyed consumers get | FR 221 Health and Human Services Department |
| Basis | `publisherNameVariant` |
| Reasoning | FR 221 is 'Health and Human Services Department'; the name without 'Department'. |
| Records read | the held roster records named |
| Source check | confirmed |
| Answers | `yes` / `no` |
| Recommended | **yes** — Unambiguous: no other held organization is named Health and Human Services. |
| Owner decision / date | **yes** (2026-11-08, questionTool) |

### `alias:bureau-of-near-eastern-affairs` — Bureau of Near Eastern Affairs (3)

| Field | Value |
| --- | --- |
| Demand (federal / all) | 3 / 6 |
| Names | none held |
| FR-keyed consumers get | FR 476 State Department (part of) |
| Basis | `unitWithinFrAgency` |
| Reasoning | A regional bureau of the Department of State (FR 476); State signs Federal Register documents from it. |
| Records read | [88 FR 14438 (2023-03-08), FR Doc 2023-04723, Department of State, Certification Pursuant to Section 7041(a)(1)](https://www.federalregister.gov/documents/full_text/text/2023/03/08/2023-04723.txt): "Office Director, Office of Assistance Coordination, Bureau of Near Eastern Affairs, Department of State." |
| Source check | confirmed |
| Answers | `yes` / `no` |
| Recommended | **yes** — The unit has no FR record; a part-of row gives the FR id of the organization it sits in, and claims no identity. |
| Owner decision / date | **yes** (2026-11-08, questionTool) |

### `alias:department-of-war` — U.S. Department of War (3)

| Field | Value |
| --- | --- |
| Demand (federal / all) | 3 / 6 |
| Names | none held |
| FR-keyed consumers get | FR 103 Defense Department |
| Basis | `secondaryTitle` |
| Reasoning | The secondary title Executive Order 14347 authorizes for the Department of Defense (FR 103), in official correspondence, public communications, ceremonial contexts and non-statutory documents. |
| Records read | [Executive Order 14347 of September 5, 2025, 90 FR 43893, Restoring the United States Department of War](https://www.federalregister.gov/documents/full_text/text/2025/09/10/2025-17508.txt): "The Department of Defense and the Office of the Secretary of Defense may be referred to as the Department of War" |
| Source check | confirmed |
| Answers | `yes` / `no` |
| Recommended | **yes** — An official secondary title of the same department. |
| Owner decision / date | **yes** (2026-11-08, questionTool) |

### `alias:defense-innovation-unit` — Defense Innovation Unit (3)

| Field | Value |
| --- | --- |
| Demand (federal / all) | 3 / 3 |
| Names | none held |
| FR-keyed consumers get | FR 103 Defense Department (part of) |
| Basis | `unitWithinFrAgency` |
| Reasoning | DIU is a Department of Defense organization no held roster holds. |
| Records read | [10 U.S.C. 4127](https://www.govinfo.gov/content/pkg/USCODE-2024-title10/html/USCODE-2024-title10-subtitleA-partV-subpartE-chap303-subchapIII-sec4127.htm): "There is established in the Department of Defense a Defense Innovation Unit" |
| Source check | confirmed |
| Answers | `yes` / `no` |
| Recommended | **yes** — The unit has no FR record; a part-of row gives the FR id of the organization it sits in, and claims no identity. |
| Owner decision / date | **yes** (2026-11-08, questionTool) |

### `alias:federal-energy-regulatory-commision` — Federal Energy Regulatory Commision (3)

| Field | Value |
| --- | --- |
| Demand (federal / all) | 3 / 3 |
| Names | none held |
| FR-keyed consumers get | FR 167 Federal Energy Regulatory Commission |
| Basis | `misspelling` |
| Reasoning | A misspelling of the Federal Energy Regulatory Commission (FR 167). |
| Records read | the held roster records named |
| Source check | confirmed |
| Answers | `yes` / `no` |
| Recommended | **no** — No publisher spells it so; a misspelling is the consumer's fuzzy matcher's job, not a reviewed alias. |
| Owner decision / date | **no** (2026-11-08, questionTool) |

### `alias:general-accounting-office` — General Accounting Office (GAO) (2)

| Field | Value |
| --- | --- |
| Demand (federal / all) | 2 / 214 |
| Names | none held |
| FR-keyed consumers get | FR 213 Government Accountability Office |
| Basis | `statutoryRename` |
| Reasoning | The Government Accountability Office's name before 2004-07-07. OPM's pinned roster states it: LG00, 'WHOSE NAME, PRIOR TO JULY 7, 2004, HAD BEEN THE GENERAL ACCOUNTING OFFICE'. The FR holds one record, FR 213, so there is no succession to state (the rename rule: a stale name no roster holds as its own record is identity evidence). |
| Records read | [Pub. L. 108-271, sec. 8(a), 118 Stat. 814 (2004-07-07), GAO Human Capital Reform Act of 2004](https://www.govinfo.gov/content/pkg/PLAW-108publ271/html/PLAW-108publ271.htm): "The General Accounting Office is hereby redesignated the Government Accountability Office." |
| Source check | confirmed |
| Answers | `yes` / `no` |
| Recommended | **yes** — One organization renamed by statute; the old name appears in 214 unmatched appearances. |
| Owner decision / date | **yes** (2026-11-08, questionTool) |

### `alias:national-counterterrorism-center` — National Counterterrorism Center (2)

| Field | Value |
| --- | --- |
| Demand (federal / all) | 2 / 45 |
| Names | none held |
| FR-keyed consumers get | FR 354 National Intelligence, Office of the National Director (part of) |
| Basis | `unitWithinFrAgency` |
| Reasoning | NCTC is a center of the Office of the Director of National Intelligence (FR 354). FR 334, the National Counterintelligence Center, carries the short name 'NCTC': an acronym collision, so the acronym is never an alias here. |
| Records read | [50 U.S.C. 3056](https://www.govinfo.gov/content/pkg/USCODE-2024-title50/html/USCODE-2024-title50-chap44-subchapI-sec3056.htm): "There is within the Office of the Director of National Intelligence a National Counterterrorism Center." |
| Source check | confirmed |
| Answers | `yes` / `no` |
| Recommended | **yes** — The unit has no FR record; a part-of row gives the FR id of the organization it sits in, and claims no identity. |
| Owner decision / date | **yes** (2026-11-08, questionTool) |

### `alias:energy` — Energy (2)

| Field | Value |
| --- | --- |
| Demand (federal / all) | 2 / 43 |
| Names | none held |
| FR-keyed consumers get | FR 136 Energy Department |
| Basis | `publisherNameVariant` |
| Reasoning | 'Energy' as a whole organization string; FR 136 is 'Energy Department'. |
| Records read | the held roster records named |
| Source check | confirmed |
| Answers | `yes` / `no` |
| Recommended | **no** — A single common word; 'Energy and Commerce' and 'Energy and Environment' split to it. |
| Owner decision / date | **no** (2026-11-08, questionTool) |

### `alias:commission-on-international-religious-freedom` — U.S. Commission on International Religious Freedom (2)

| Field | Value |
| --- | --- |
| Demand (federal / all) | 2 / 33 |
| Names | OPM `ZP00` U.S. COMMISSION ON INTERNATIONAL RELIGIOUS FREEDOM |
| FR-keyed consumers get | no FR id |
| Basis | `noFrRecord` |
| Reasoning | USCIRF; OPM holds it as ZP00. The Federal Hierarchy holds two records of the same name (300000724, 300000894), so neither is taken. |
| Records read | [22 U.S.C. 6431](https://www.govinfo.gov/content/pkg/USCODE-2024-title22/html/USCODE-2024-title22-chap73-subchapII-sec6431.htm): "There is established the United States Commission on International Religious Freedom." |
| Source check | confirmed |
| Answers | `yes` / `no` |
| Recommended | **yes** — Names the one OPM record; no FR id. |
| Owner decision / date | **yes** (2026-11-08, questionTool) |

### `alias:office-of-information-and-regulatory-affairs` — Office of Information and Regulatory Affairs (2)

| Field | Value |
| --- | --- |
| Demand (federal / all) | 2 / 29 |
| Names | none held |
| FR-keyed consumers get | FR 280 Management and Budget Office (part of) |
| Basis | `unitWithinFrAgency` |
| Reasoning | OIRA is an office within the Office of Management and Budget (FR 280); regulations.gov lists it as its own agency code, but no reviewed REF-038 row maps that code to an FR record. |
| Records read | [44 U.S.C. 3503](https://www.govinfo.gov/content/pkg/USCODE-2024-title44/html/USCODE-2024-title44-chap35-subchapI-sec3503.htm): "There is established in the Office of Management and Budget an office to be known as the Office of Information and Regulatory Affairs." |
| Source check | confirmed |
| Answers | `yes` / `no` |
| Recommended | **yes** — The unit has no FR record; a part-of row gives the FR id of the organization it sits in, and claims no identity. |
| Owner decision / date | **yes** (2026-11-08, questionTool) |

### `alias:federal-bureau-of-prisons` — Federal Bureau of Prisons (2)

| Field | Value |
| --- | --- |
| Demand (federal / all) | 2 / 25 |
| Names | none held |
| FR-keyed consumers get | FR 437 Prisons Bureau |
| Basis | `publisherNameVariant` |
| Reasoning | FR 437 is 'Prisons Bureau'; the bureau calls itself the Federal Bureau of Prisons, and the Federal Hierarchy names it 'FEDERAL PRISON SYSTEM / BUREAU OF PRISONS'. |
| Records read | [18 U.S.C. 4041](https://www.govinfo.gov/content/pkg/USCODE-2024-title18/html/USCODE-2024-title18-partIII-chap303-sec4041.htm): "The Bureau of Prisons shall be in charge of a director appointed by and serving directly under the Attorney General." |
| Source check | confirmed |
| Answers | `yes` / `no` |
| Recommended | **yes** — A qualifier variant of the statutory name of the FR record's organization. |
| Owner decision / date | **yes** (2026-11-08, questionTool) |

### `alias:transportation-command` — U.S. Transportation Command (TRANSCOM) (1); U.S. Transportation Command (USTRANSCOM) (1)

| Field | Value |
| --- | --- |
| Demand (federal / all) | 2 / 25 |
| Names | OPM `DD76` U.S. TRANSPORTATION COMMAND.  NOTE: ORGANIZATION DOES NOT MAKE HR SUBMISSIONS TO OPM. CODE MAY BE USED FOR OTHER DOCUMENTATION PURPOSES. |
| FR-keyed consumers get | FR 103 Defense Department (part of) |
| Basis | `unitWithinFrAgency` |
| Reasoning | U.S. Transportation Command; OPM holds it as DD76. DoD's FOIA rule names it among the DoD Components its OSD/Joint Staff center serves, beside the other combatant commands. |
| Records read | [10 U.S.C. 111](https://www.govinfo.gov/content/pkg/USCODE-2024-title10/html/USCODE-2024-title10-subtitleA-partI-chap2-sec111.htm): "(9) The unified and specified combatant commands."; [82 FR 1192 (2017-01-05), FR Doc 2016-31686, DoD Freedom of Information Act (FOIA) Program (32 CFR part 286)](https://www.federalregister.gov/documents/full_text/text/2017/01/05/2016-31686.txt): "United States Africa Command, United States Central Command, United States European Command, United States Northern Command, United States Pacific Command, United States Special Operations Command, United States Strategic Command, and United States Transportation Command."; [82 FR 1192 (2017-01-05), FR Doc 2016-31686, 32 CFR 286.2](https://www.federalregister.gov/documents/full_text/text/2017/01/05/2016-31686.txt): "the Combatant Commands, the Office of the Inspector General of the Department of Defense, the Defense Agencies, the DoD Field Activities, and all other organizational entities within the DoD" |
| Source check | confirmed |
| Answers | `yes` / `no` |
| Recommended | **yes** — The unified and specified combatant commands are part of the Department of Defense (10 U.S.C. 111(b)(9)) and have no FR record; part-of DOD is the only FR resolution, and it claims no identity. |
| Owner decision / date | **yes** (2026-11-08, questionTool) |

### `alias:education` — Education (1)

| Field | Value |
| --- | --- |
| Demand (federal / all) | 1 / 71 |
| Names | none held |
| FR-keyed consumers get | FR 126 Education Department |
| Basis | `publisherNameVariant` |
| Reasoning | 'Education' as a whole organization string; FR 126 is 'Education Department'. |
| Records read | the held roster records named |
| Source check | confirmed |
| Answers | `yes` / `no` |
| Recommended | **no** — A single common word, as often a portfolio or a state agency as the department. |
| Owner decision / date | **no** (2026-11-08, questionTool) |

### `alias:usmc` — USMC (1)

| Field | Value |
| --- | --- |
| Demand (federal / all) | 1 / 43 |
| Names | OPM `NV27` U.S. MARINE CORPS |
| FR-keyed consumers get | FR 378 Navy Department (part of) |
| Basis | `militaryServiceOfDepartment` |
| Reasoning | USMC, the Marine Corps' acronym; the same row as 'marine corps'. |
| Records read | [10 U.S.C. 8063](https://www.govinfo.gov/content/pkg/USCODE-2024-title10/html/USCODE-2024-title10-subtitleC-partI-chap807-sec8063.htm): "The Marine Corps, within the Department of the Navy, shall be so organized"; [91 FR 60950 (2026-09-25), FR Doc 2026-19609, Department of the Navy, Proposed Collection](https://www.federalregister.gov/documents/full_text/text/2026/09/25/2026-19609.txt): "AGENCY: Department of the Navy, Department of Defense (DoD)."; [91 FR 60950 (2026-09-25), FR Doc 2026-19609, Department of the Navy, Proposed Collection](https://www.federalregister.gov/documents/full_text/text/2026/09/25/2026-19609.txt): "the United States Marine Corps (USMC) announces a proposed public information collection" |
| Source check | confirmed |
| Answers | `yes` / `no` |
| Recommended | **yes** — The unit has no FR record; a part-of row gives the FR id of the organization it sits in, and claims no identity. |
| Owner decision / date | **yes** (2026-11-08, questionTool) |

### `alias:national-guard-bureau` — National Guard Bureau (1)

| Field | Value |
| --- | --- |
| Demand (federal / all) | 1 / 36 |
| Names | none held |
| FR-keyed consumers get | FR 103 Defense Department (part of) |
| Basis | `unitWithinFrAgency` |
| Reasoning | The National Guard Bureau is a joint activity of the Department of Defense; OPM holds only its chief's office (ARGB). |
| Records read | [10 U.S.C. 10501](https://www.govinfo.gov/content/pkg/USCODE-2024-title10/html/USCODE-2024-title10-subtitleE-partI-chap1011-sec10501.htm): "There is in the Department of Defense the National Guard Bureau, which is a joint activity of the Department of Defense." |
| Source check | confirmed |
| Answers | `yes` / `no` |
| Recommended | **yes** — The unit has no FR record; a part-of row gives the FR id of the organization it sits in, and claims no identity. |
| Owner decision / date | **yes** (2026-11-08, questionTool) |

### `alias:national-science-board` — National Science Board (1)

| Field | Value |
| --- | --- |
| Demand (federal / all) | 1 / 26 |
| Names | none held |
| FR-keyed consumers get | FR 366 National Science Foundation (part of) |
| Basis | `unitWithinFrAgency` |
| Reasoning | The National Science Board is the governing board of the National Science Foundation (FR 366). |
| Records read | [42 U.S.C. 1861](https://www.govinfo.gov/content/pkg/USCODE-2024-title42/html/USCODE-2024-title42-chap16-sec1861.htm): "The Foundation shall consist of a National Science Board" |
| Source check | confirmed |
| Answers | `yes` / `no` |
| Recommended | **yes** — The unit has no FR record; a part-of row gives the FR id of the organization it sits in, and claims no identity. |
| Owner decision / date | **yes** (2026-11-08, questionTool) |

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
| `alias:veterans-health-administration` | `yes` / `no` | `yes` | `sha256:71e177ee80e0617007badb9154b24cb7501aaf179519daaac17ec8e0e97c2349` |
| `alias:army` | `1` / `2` / `3` | `2` | `sha256:64f7eeb627c894bd960aa0b21647b7de52bf7ee714fbc045744c41cad08f86cd` |
| `alias:navy` | `1` / `2` / `3` | `2` | `sha256:47868d4825d0595a2c7ab13ff505868191e8629b61deb106143a11f8eda48f98` |
| `alias:veterans-benefits-administration` | `yes` / `no` | `yes` | `sha256:a51f51e6c8e31579f0b068b2e7b7fca28ce94ad547380a4f617bb738600eb781` |
| `alias:air-force` | `1` / `2` / `3` | `2` | `sha256:7a2af7cb470b8f49ac962d45bb3a21d66f028b5d6f07791705dc8ee85298d3b5` |
| `alias:marine-corps` | `yes` / `no` | `yes` | `sha256:b4ed13ab90c75689839b30f57fbd219c80123d35e506340536dd275ea465e343` |
| `alias:congressional-research-service` | `yes` / `no` | `yes` | `sha256:66d7bdbade1b0b0789bb7791c503d18ea2fb32b7c33a0680399079c851ee9034` |
| `alias:office-of-secretary-of-defense` | `yes` / `no` | `yes` | `sha256:1df660b2e52cfeff835fe6592f247e93aaaab5e54f9f3a43963b27f466e6cd8a` |
| `alias:bureau-of-land-management` | `yes` / `no` | `yes` | `sha256:173563bd52d49d7bffcef4ec8411242f0ba93b5e6322bd65e11f576bb34fd368` |
| `alias:bureau-of-reclamation` | `yes` / `no` | `yes` | `sha256:519aaac9259a4fe4beaf43cbded4210600e7ccf3672bb9644cdfd0c0d21c7c11` |
| `alias:national-security-agency` | `yes` / `no` | `yes` | `sha256:ae4644409ac474952e14f3e6e0ad4c0bd3b84be6f0cb9ae0f7bd720ea7a0fdd9` |
| `alias:office-of-director-of-national-intelligence` | `yes` / `no` | `yes` | `sha256:2c91425e7901787db37ef3659c1af03dde5dbcde1de91f5053334a8de2f01baf` |
| `alias:army-corps-of-engineers` | `yes` / `no` | `yes` | `sha256:090d38a95fdf6375b97b2687468555e55c437b9b032fa1b4edbf4edf30cd058a` |
| `alias:office-of-management-and-budget` | `yes` / `no` | `yes` | `sha256:3d3f05f78242d66a59cdd0fbf80cee5e32fc2ac4e66e04c40d2db3bd22af28e0` |
| `alias:bureau-of-ocean-energy-management` | `yes` / `no` | `yes` | `sha256:877db7bea0c9c873fb798810338f3a4fd52dc039a445eeb2a99bad21bc50fc74` |
| `alias:board-of-governors-of-federal-reserve-system` | `1` / `2` / `3` | `2` | `sha256:eb62bdf8c833d3b42b86d9bab73fec202beeb55371d6e9f26753f6d12931f9d8` |
| `alias:space-force` | `yes` / `no` | `yes` | `sha256:e700bbc1e83d0ad198efb05e04c222fce8d32f479739bdfccd206af01043ba93` |
| `alias:bureau-of-safety-and-environmental-enforcement` | `yes` / `no` | `yes` | `sha256:954a9f7f73b240e7f7d0b6a941b0ae6fab90275cff0b59ed609c147604b4f824` |
| `alias:national-reconnaissance-office` | `yes` / `no` | `yes` | `sha256:4fea1d86654fffb69212057d30df210ac38be85e707112840edcf7a5f6ac2857` |
| `alias:veterans-benefit-administration` | `yes` / `no` | `no` | `sha256:9914066faa24a1c7ac377730a7f08916202d7d252e5dc0ade4d850bbf46b6adf` |
| `alias:export-import-bank-of` | `yes` / `no` | `yes` | `sha256:1979a7517c918ef7ca8ad5d4374f40565b227323df79cb1dd8fb8849f74e780a` |
| `alias:capitol-police` | `yes` / `no` | `yes` | `sha256:9eacb6b821af684cf6e05b9467ac93ea750cead4bdd5022dbe7299bb9cc616a2` |
| `alias:strategic-command` | `yes` / `no` | `yes` | `sha256:a7b06447c50313dc7b7d2f74ae66597f4e35df6ee5bc5471c12ca9be3a08a918` |
| `alias:joint-staff` | `yes` / `no` | `yes` | `sha256:5da1125e41ad3adbca0eee15d1a5b880ee7b9f1bc5c2a65e419ab84eb7c07376` |
| `alias:office-of-special-counsel` | `yes` / `no` | `yes` | `sha256:080fbc252605ef8638d76b30f4777e8f9b8203605a6fc06816fbf4a6bb452742` |
| `alias:missile-defense-agency` | `yes` / `no` | `yes` | `sha256:a5b24092303ec8aa01c9f262814efaf918a346dd8f8bd9f138c1909e2819e151` |
| `alias:cyber-command` | `yes` / `no` | `yes` | `sha256:7bd7c1d62e32137c36e8e79c9de4190688fc3ef0c7107e840e7a33b840da7aca` |
| `alias:special-operations-command` | `yes` / `no` | `yes` | `sha256:5a8cb0c7a7ef3f457e98bbb34d2402771db8816cbfec80f75bffa5f567e96f13` |
| `alias:africa-command` | `yes` / `no` | `yes` | `sha256:fb7822fd127e70b8e9c55bf5a6918b1bfca19585a4c04d85329c02cd39a65bdb` |
| `alias:federal-bureau-of-investigations` | `yes` / `no` | `no` | `sha256:8bda774338306c27e1f738b2532daa1ebea62777a1f19f122e05aa85fbf7f28b` |
| `alias:national-cemetery-administration` | `yes` / `no` | `yes` | `sha256:bec7df0e22794121888e476a9a592b70b774a2fb8826e427dd60415bb7e29d21` |
| `alias:office-of-comptroller-of-currency` | `yes` / `no` | `yes` | `sha256:fcca0e3691aff777ce824dede5740d38f348c45dd5ba7e71e56ea47d46897fea` |
| `alias:defense-health-agency` | `yes` / `no` | `yes` | `sha256:38201b20556eb55a6488fb0a832fe71922059b39ca67e00c10f18b5b1f879f4e` |
| `alias:space-command` | `yes` / `no` | `yes` | `sha256:18764e117ae36713aa8ff0f1823a66f474dab87183d1e3029f85cfedc06b7d27` |
| `alias:bureau-of-indian-affairs` | `yes` / `no` | `yes` | `sha256:0ebb185ea084f9386aaaac1fc3064daeaa2f98fd5b00474780110404ace14a3f` |
| `alias:usda-office-of-inspector-general` | `yes` / `no` | `yes` | `sha256:fc77b056c7a4cbc84ea5439d169409bf104c2ea39855d6c554498900bb81e187` |
| `alias:national-forest-system` | `yes` / `no` | `yes` | `sha256:b7de260037331636132c60abe8d523153121071c9100b813f4083ac73e4d40c6` |
| `alias:national-institute-of-health` | `yes` / `no` | `no` | `sha256:04ec974eeac69b5478536f3ea5306eb1cf0efb6027327e231cde56b19b574e53` |
| `alias:office-of-personnel-management` | `yes` / `no` | `yes` | `sha256:9d939b41e4f954762d2f1a02fb0a4d909796d316d65268027babf6badadb6295` |
| `alias:joint-chiefs-of-staff` | `yes` / `no` | `yes` | `sha256:8489389062f9653245100000d2381e3bceee601342900f767e4d08dda98bedcc` |
| `alias:central-command` | `yes` / `no` | `yes` | `sha256:cdd2078332d9b748d69f454c85ed045cf03f136ec1e751b653602494d817d6bb` |
| `alias:european-command` | `yes` / `no` | `yes` | `sha256:df9cc8508d3ef050b1df77ec195052cdc03761805ceb04104d9270d19e06dba1` |
| `alias:cybersecurity-and-infrastructure-security-agency` | `yes` / `no` | `yes` | `sha256:d4456dab7cac54d79beed4689a7b33ca401ee493c5417f06bd700493703afadd` |
| `alias:air-force-space-command` | `yes` / `no` | `yes` | `sha256:e55287aeaccffd4e63c4ee9dd77241dfee86f90da4db8b945fe6d6b8d75b0b33` |
| `alias:national-institute-of-allergy-and-infectious-diseases` | `yes` / `no` | `yes` | `sha256:aad036525eea5bcb20d1bf7f58276042c46c8c2659651055de42eddb1a4e258a` |
| `alias:office-of-congressional-workplace-rights` | `yes` / `no` | `yes` | `sha256:cfb5d0f1711eb2d2d8ebada0b50275ee8e4b42f4ea6154a1e29ffcc8d6316773` |
| `alias:forces-korea` | `yes` / `no` | `yes` | `sha256:cf9094c16a6946868b92dcf320580fbcc030cf95ea04cd36500f6fae8b5ca72c` |
| `alias:labor` | `yes` / `no` | `no` | `sha256:0d48c10db5fc6949b3e35776f5859ad8eeab220c444519d30aa939ea0f86baed` |
| `alias:office-of-chief-of-naval-operations` | `yes` / `no` | `yes` | `sha256:342a1642bf6b348cbdfdf9d68731abc449312fcb9585760f05784b701be2ad71` |
| `alias:headquarters-air-force` | `yes` / `no` | `yes` | `sha256:f72ec1cc02c646c9594ad73e04875e453c8cdc3da02822d2bdc259b9c005a173` |
| `alias:headquarters-marine-corps` | `yes` / `no` | `yes` | `sha256:da4c74600e5b81fd4d9eb44a4d60f4f3eeee9fba2be80f205b6cfab12cb4006d` |
| `alias:health-and-human-services` | `yes` / `no` | `yes` | `sha256:761accb2eb34dcee6df34b9352e0f631949eef8965fa1e2a8d2011f5637f7be7` |
| `alias:office-of-surface-mining-reclamation-and-enforcement` | `yes` / `no` | `yes` | `sha256:eb71e90da1467bc49683ea0b45d20241de3ee9c6bc76727609c9d691e0155b3e` |
| `alias:bureau-of-near-eastern-affairs` | `yes` / `no` | `yes` | `sha256:6db9e09c76942c780936d75c6356bedf7682312a4f266dc1db1dc88baed207bc` |
| `alias:department-of-war` | `yes` / `no` | `yes` | `sha256:cd294ba7c7226ecceac699c44a3d8a5856ee62a6800c33d2a3ac4a2723eba576` |
| `alias:defense-innovation-unit` | `yes` / `no` | `yes` | `sha256:cf8623f92fca07e72b1f9c9d5f669b15475c7ba9939551a44da10301f5e31e28` |
| `alias:federal-energy-regulatory-commision` | `yes` / `no` | `no` | `sha256:3d81378005443008d0f077beb4d7632312eb1426f9595ca8fcb8e52cc9d6894b` |
| `alias:general-accounting-office` | `yes` / `no` | `yes` | `sha256:6bf24dcfee3236e4710ddcc0196fe345216c15cedfea482942acbfff2ced5bad` |
| `alias:national-counterterrorism-center` | `yes` / `no` | `yes` | `sha256:8c50660b679e1f7b3663f203e3ba1efa460bbb4f15857419a29fa0a24351af8d` |
| `alias:energy` | `yes` / `no` | `no` | `sha256:40373e8c4498e0883cd0ab9ad08aab747ae399c9931e81aa5abdf46f2723ee4f` |
| `alias:office-of-science-and-technology-policy` | `yes` / `no` | `yes` | `sha256:6d8f4ee2f0cc61dee693cc5e6133b7f77fd819d1514179611bf1877ef6d07dcc` |
| `alias:commission-on-international-religious-freedom` | `yes` / `no` | `yes` | `sha256:4414961ba931cca30cda38a44def86fd0302c28aa8b4efe03e9ec889b237782a` |
| `alias:office-of-information-and-regulatory-affairs` | `yes` / `no` | `yes` | `sha256:a4f01d79d496fd769aba2be1bf70126b4ccafa44e83c668289a1b2d409d792c3` |
| `alias:copyright-office` | `yes` / `no` | `yes` | `sha256:b6176b42a312c0b47ee04a84de8d33bd0feb1c66eb481dbefc84b465df53a257` |
| `alias:federal-bureau-of-prisons` | `yes` / `no` | `yes` | `sha256:3ca143ecd639d843dda6451b99a395fe951cda9bc932744ca854527ed51fa8dc` |
| `alias:transportation-command` | `yes` / `no` | `yes` | `sha256:3f6d9bfbe9ef0790da9c52e019994579cf75a72b609092ae10d4b5a439f71a17` |
| `alias:education` | `yes` / `no` | `no` | `sha256:be91de0fcef3a7b5cb97e4baaa23613c0ed8fcdd69ffaa24de956d74385bb7ae` |
| `alias:usmc` | `yes` / `no` | `yes` | `sha256:17aaf63f62615cf3313a6c0796afc19802eb1cbb673e5a43dc6093580a64c7e6` |
| `alias:national-guard-bureau` | `yes` / `no` | `yes` | `sha256:d2965653755ece80303057c4ebbbd984ead82f058fb0afd9d1a34c81dff5e308` |
| `alias:national-science-board` | `yes` / `no` | `yes` | `sha256:db657df1a1f1435c6148a9b53d510f46361440782d138a134a138754389d5cbb` |
