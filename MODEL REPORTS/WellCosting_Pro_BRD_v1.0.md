# WellCosting Pro
## Business and Functional Requirement Document
Version 1.0 • 26 October 2026 • Draft for business review

BUSINESS REQUIREMENT DOCUMENT

The purpose of this document is to define the business, functional, technical and operational requirements for implementing WellCosting Pro as the central platform for well cost planning, daily cost capture, cost control, consolidation and management reporting across drilling and completion operations.

Document owner: Business sponsor / Well Costing function — to be nominated.
Approval status: Draft; no stakeholder approval is implied.

## Document History

| Version | Date modified | Officer / owner | Content / summary of updates |
| --- | --- | --- | --- |
| 1.0 | 26 October 2026 | Business owner to confirm | Initial BRD based on the supplied business context, reference BRD and repository review. |

## Supporting History

| Document / source | Author / owner | Location / purpose |
| --- | --- | --- |
| BRD - Oil Terminal Management - Hydrocarbon Accounting v2.docx | Supplied by business stakeholder | GitHub main / MODEL REPORTS; structure and presentation reference. |
| WellCosting Pro application source | Repository contributors | praveen-christuraj/WellCostingPro; local revision d9ce4c05c2b27a4e5160e715862e45cfdef9e335. |
| Model cost and AFE reports | Business stakeholder | MODEL REPORTS / MODEL REPORT.pdf, afe.pdf, Daily cost register · WellCosting Pro.pdf and REVISED DAILY REPORT TABLE PLACEMENTS.jpg. |
| Product memory and design notes | Repository contributors | .agent/memory/project.md; docs/daily-cost-management.md; docs/daily-cost-allocations.md; docs/afe-plan.md; docs/deployment.md. |
| Current process and business outcome | Requesting stakeholder | Excel and SharePoint process described in the request; approximately 80% manual-process reduction is a target. |

## Content

1.0 Introduction
2.0 Scope and Limitations
3.0 Risk and Mitigation
4.0 Benefit of the Implementation
5.0 Business and Functional Requirements
6.0 Reporting and Monthly MIS Requirements
7.0 Data, Calculation and Control Requirements
8.0 Technical, Security and Operational Requirements
9.0 Migration, Implementation and Acceptance
10.0 Open Decisions and Approval
Appendix A — Repository Traceability
Appendix B — Glossary

## Reading this document

The first four sections follow the supplied BRD's structure. Additional sections make the requirements testable and distinguish repository evidence from the desired operating model. Terminal-specific requirements in the sample, such as tank calibration and hydrocarbon accounting, have been replaced with well-costing requirements.

Status terms: “Evidenced” means routes, screens, business logic or tests exist in the reviewed source; it does not establish production readiness or business acceptance. “Partial” means part of the intended business outcome exists but further definition or verification is required. “Proposed” means a requirement for agreement or delivery, without a claim that the repository implements it. Unless stated otherwise, detailed requirements below are Must-have; named future integrations are outside the initial scope.

# 1.0 Introduction

## 1.1 Overview

WellCosting Pro is a workspace-based application for managing the cost lifecycle of wells, from rig and well configuration through AFE estimation, daily actuals, material reconciliation, variance analysis and consolidated reporting. It provides a common record for drilling and completion costs and replaces repetitive handling of individual well spreadsheets with structured workflows and reusable reference data.

The application is intended to support cost engineers, drilling and completion teams, finance, management, administrators and auditors. A transaction entered and validated against the correct well, AFE, date and operating scope becomes available to applicable dashboards, cost comparisons and reports without retyping it into each output.

## 1.2 Background and Current Method

The current process uses Excel and SharePoint. Each well has a separate cost sheet, with a large number of formulas—approximately 1,000 as described by the stakeholder. Sheets are updated and circulated through email, printouts and SharePoint. Staff must identify the latest version, verify formulas, resolve corrections and repeat the exercise across wells.

Weekly, monthly and yearly reporting requires manual reference to individual well sheets. Consolidated costs and supporting details are then entered into separate summaries. Monthly MIS preparation, including NPT and UPA costs and days, comparisons and analysis, is also performed manually. The same operational facts are therefore handled repeatedly at capture, consolidation, reporting and review stages.

The process consumes staff hours and creates exposure to formula changes, copy-and-paste mistakes, omitted wells, duplicate costs, inconsistent classifications and conflicting versions. The scale of these problems increases as more wells, vendors, currencies and reporting periods are added.

## 1.3 Problem Statement

The organisation lacks a single controlled source for well cost plans, daily actuals, NPT/UPA attribution and consolidated reporting. Spreadsheet-driven working practices make management information dependent on manual compilation and individual knowledge. This delays visibility of budget consumption and makes it difficult to trace a reported figure quickly to its originating record and approval history.

WellCosting Pro shall address this problem by centralising reference data and well cost transactions, applying consistent calculations, controlling changes and generating reports from the same stored records. Reporting shall not require a separate round of data entry for facts already captured in the platform.

## 1.4 Business Objectives

| ID | Objective | Intended measure |
| --- | --- | --- |
| BO-01 | Reduce repetitive manual work in the agreed costing and reporting process by approximately 80%. | Compare baseline staff hours with equivalent post-go-live staff hours for the same work and well coverage. |
| BO-02 | Capture each transaction once and reuse it throughout applicable reporting. | No rekeying of an already captured transaction into standard weekly, monthly or annual summaries. |
| BO-03 | Standardise well cost calculations and classifications. | Approved calculation examples reconcile to source lines and agreed rules. |
| BO-04 | Improve visibility of AFE consumption and cost exceptions. | Users can inspect plan, actual, balance and contributing details for selected wells and periods. |
| BO-05 | Reduce Monthly MIS compilation effort. | Agreed MIS measures can be reproduced from source records with documented filters and treatment of drafts. |
| BO-06 | Improve accountability and traceability. | Authorised reviewers can identify the actor, date, transaction and relevant change history. |
| BO-07 | Support consistent working across drilling and completion. | Scope-specific plans, costs and reports remain identifiable and independently controlled. |

The 80% figure is a business target, not a measured saving or a promise that 80% of every task disappears. Data collection, entry of new daily events, validation, approvals, exceptions and management judgement remain necessary. “One-time entry” means entering each fact once for reuse across wells' applicable reports; it does not mean entering all wells' future operational data in one initial exercise.

## 1.5 Intended Audience and Stakeholders

| Stakeholder | Business responsibility |
| --- | --- |
| Executive sponsor / asset management | Sponsor the change, agree outcomes and accept business benefits. |
| Drilling and completion management | Own operational scope, plans, activity definitions and cost accountability. |
| Cost engineers / well costing team | Maintain estimates, capture actuals, validate attribution and prepare cost information. |
| Rig / well operations personnel | Supply reliable daily activities, quantities, depths, milestones and supporting details. |
| Finance / MIS team | Agree financial definitions, currency policy, cut-off rules, reconciliations and management outputs. |
| Procurement / commercial team | Maintain vendor and order reference quality and supporting commercial documents. |
| Reviewers / approvers | Review estimates and controlled changes under assigned permissions. |
| IT applications / infrastructure / security | Operate the application, manage access, backups, support and deployment controls. |
| Internal audit / compliance | Review access, evidence, amendments, retention and reporting traceability. |

Role names in this table are business personas. The application uses configurable permissions; these personas are not a claim that fixed roles or maker-checker segregation are automatically enforced.

## 1.6 Current and Proposed Process

| Stage | Current method | Proposed WellCosting Pro method |
| --- | --- | --- |
| Reference data | Repeated vendor, service and rate details across spreadsheets. | Maintain workspace reference registers and reusable catalogue items. |
| Planning | Well plans and estimates maintained in individual files. | Configure drilling/completion sections and phases; estimate through AFE workflows. |
| Daily capture | Enter daily values and manipulate formulas in well sheets. | Enter structured service, consumable, tangible and other-expense records against well, AFE and date. |
| Classification | Manually group planned, NPT and UPA values for summaries. | Derive classifications from activities and retain required scope and responsibility. |
| Review / correction | Circulate versions and resolve edits through email. | Apply controlled workflow actions, reopen reasons and audited amendments. |
| Consolidation | Refer to every sheet and retype totals into consolidated files. | Query the shared ledger using well, rig, block, period, scope and currency filters. |
| MIS and analysis | Compile and analyse manually for each reporting period. | Reuse stored records for cost comparisons, usage, NPT/UPA and variance views; agree remaining MIS gaps. |
| Distribution | Email, print and SharePoint copies become working versions. | Use the application as the operational record; generate authorised exports and prints for distribution. |

# 2.0 Scope and Limitations

## 2.1 In-Scope Business Capabilities

| Capability | Business coverage | Repository status |
| --- | --- | --- |
| Workspace and access management | Sign-in, users, roles, permissions and assignments. | Evidenced |
| Master data and catalogues | UOM, currencies, phases, sections, activities, services, vendors, PO/SO documents, tangibles and consumables. | Evidenced |
| Rig and well management | Blocks, rigs, wells, scoped configurations, sub-activities and lifecycle controls. | Evidenced |
| AFE estimation | Services, consumables, tangibles, rate bases, currency conversion, scope rollups and approval stages. | Evidenced |
| Controlled adjustments | Well plan revisions, AFE scope-of-work adjustments and historical daily amendments. | Evidenced |
| Daily cost management | Sheets, line items, activity allocations, previews, submission, reopen and historical baselines. | Evidenced |
| Specialist registers | Mud cost and losses, fuel quantities, LIH costs and NDT inspection quantities. | Evidenced |
| Analysis and reports | Well cost analysis, business dashboard, comparison and usage reports, NPT/UPA cost-date counts. | Evidenced |
| Weekly / monthly / annual reporting | Date-filtered source analysis and exports. | Partial: period views exist; a certified complete MIS pack and close process require agreement. |
| Audit and controlled data access | Audit log, soft deletion/recovery and read-only database browser. | Evidenced; coverage and operational governance require acceptance. |
| Migration and adoption | Convert agreed legacy data, train users and transition from spreadsheets. | Proposed implementation work |
| Operational readiness | Backup/restore evidence, service monitoring, load validation and support procedures. | Proposed acceptance work; not established by source presence. |

## 2.2 Out of Scope for the Initial Implementation

The initial scope excludes ERP general-ledger posting, accounts payable, invoice settlement, payment processing, a full procurement system, warehouse inventory management, live bank/FX feeds, automatic email or SharePoint synchronisation, offline mobile synchronisation, predictive forecasting, regulatory submission integrations and integrations with rig sensors or drilling data acquisition systems.

MFA/SSO, password-reset delivery, scheduled report distribution and a configurable MIS report designer are not established implemented features. If required for launch, they must be explicitly added to the delivery scope with acceptance criteria. The current database browser's CSV output can support downstream analysis, but does not constitute an automatic Power BI connector or a live refresh integration.

## 2.3 Assumptions

1. Management will nominate business owners for reference data, costing rules, report definitions and approvals.
2. Operations will provide accurate and timely activities, quantities, depths and milestone timestamps.
3. Finance will approve currency conversion, financial cut-off, draft inclusion and reconciliation policies.
4. Users will receive training before becoming accountable for live entries.
5. Historical spreadsheets and SharePoint copies will be made available for the agreed migration period and reconciled by their owners.
6. Users will have supported browsers and reliable connectivity; offline capture is not evidenced.
7. The agreed implementation will use a supported relational database and an appropriately secured hosting environment.
8. The reported 80% automation opportunity will be validated with measured baseline and pilot data.
9. Legal, contractual and internal reporting obligations will be confirmed by the organisation; this document does not certify compliance with any named regime.

## 2.4 Dependencies

| Dependency group | Required inputs or services | Responsible function |
| --- | --- | --- |
| Infrastructure | Application hosting, PostgreSQL, HTTPS, domain and reverse proxy configuration. | IT infrastructure |
| Security | Workspace provisioning, approved permission matrix, credential policy and access review procedures. | IT security / application owner |
| Reference data | Approved services, providers, vendors, catalogue items, units, currencies, sections, phases and activities. | Master data custodians |
| Well planning | Block/rig/well structure, drilling and completion plans, section depths and planned days. | Engineering / operations |
| Commercial inputs | Valid rates, charging bases, PO/SO references and correct document revisions. | Procurement / costing |
| Cost data | Daily quantities, hours, responsibility and supporting operational records. | Operations / cost engineers |
| Reporting policy | Week definition, fiscal year, cost-date cut-off, drafts, adjustments and NPT/UPA duration basis. | Finance / MIS |
| Continuity | Backup storage, restoration procedures, recovery objectives and monitoring. | IT operations |
| Delivery and change | UAT participants, approved migration mappings, training and support arrangements. | Sponsor / implementation team |

## 2.5 Limitations and Gaps Requiring Business Treatment

The source supports substantial costing workflows, although some older README and planning text still describes the project as a foundation or says daily costing is unbuilt. This BRD uses executable code and regression coverage to establish the current functional baseline. Such evidence is not confirmation that a live deployment is current, fully configured or production-ready.

The following limitations materially affect interpretation and acceptance:

- The dedicated NPT/UPA report counts distinct cost dates containing each classification. One date can count in both NPT and UPA; these figures are not equivalent to hours divided by 24 and must not be added as elapsed time.
- Some reports include drafts by default. Certified MIS requires an agreed inclusion rule and clear identification of draft records. Submitted does not imply a separate daily-sheet approval stage.
- Currency handling differs by view: usage reports can use stored USD values; other selected currencies may include only matching sheets and disclose exclusions. AFE and dashboard comparisons must be reconciled on an explicitly consistent basis.
- The recorded actual and the mud-reconciled comparison actual are different measures. LIH is recorded separately and included in designated well summary measures; it must not be posted twice.
- Fuel stock and company-consumption records support operational material balance. Automatic posting of those quantities as monetary daily fuel costs is not assumed.
- NDT entries have no operational inspection-date field. Creation dates must not be presented as inspection dates or used to certify period inspection performance.
- A date-range view is not a closed accounting period. Formal period locking, frozen MIS versions and automated distribution are proposed controls, not evidenced end-to-end features.
- Shared grid pagination may operate on fetched records. Large-volume server pagination, response times, multi-user concurrency and print capacity require testing at the intended scale.

# 3.0 Risk and Mitigation

The following risk register is an initial business assessment. Likelihood, impact and proposed owners require stakeholder confirmation.

| ID | Risk / cause | Category | Likelihood / impact | Mitigation | Proposed owner |
| --- | --- | --- | --- | --- | --- |
| R01 | Inaccurate or duplicate legacy spreadsheet records. | Data | High / High | Map stable business keys; deduplicate; reconcile source-to-target by well, period and currency; retain signed exceptions. | Costing / finance |
| R02 | Incorrect rates, units or FX factors produce misleading totals. | Financial | Medium / High | Validate units and rates; test worked examples; retain snapshots; require explicit FX completeness. | Costing / finance |
| R03 | NPT/UPA date counts are interpreted as fractional duration. | Reporting | High / High | Label the current measure; agree hours-based MIS rules and implement/test any required gap. | Operations / MIS |
| R04 | Drafts, late costs or deleted sheets change previously issued totals. | Governance | High / High | Agree cut-off and inclusion rules; control reopen/amend rights; define frozen reporting evidence. | Finance / application owner |
| R05 | Double counting between mud reconciliation, fuel, LIH and daily ledger. | Financial | Medium / High | Document authoritative sources; reconcile each measure; prohibit repeat posting of the same cost. | Costing / finance |
| R06 | Over-broad permissions or workspace mistakes expose data. | Security | Medium / High | Least-privilege matrix; tenant-isolation tests; review powerful database-browser access; periodic access review. | IT security |
| R07 | User resistance causes continued use of conflicting spreadsheets. | Adoption | Medium / High | Pilot with operators; training; named support; retire editable legacy templates after accepted cutover. | Sponsor / operations |
| R08 | Poor site connectivity delays capture. | Technical | Medium / Medium | Verify site network access; maintain an agreed contingency capture process and controlled later entry. | IT infrastructure |
| R09 | Backup or restoration capability is not proven. | Continuity | Medium / High | Configure protected backups and execute witnessed restoration drills before go-live. | IT operations |
| R10 | Large data volumes slow reports or exceed export/print capacity. | Performance | Medium / High | Size representative datasets; load-test; test worst-case reports; address pagination and print overflow. | Application team |
| R11 | Unsupported integration assumptions expand delivery scope. | Scope | Medium / Medium | Specify interfaces separately; prohibit claims of SharePoint, ERP or automatic BI integration without acceptance evidence. | Sponsor / IT |
| R12 | Unclear responsibility or coding reduces analytical quality. | Operational | High / Medium | Define activity/sub-activity taxonomy; assign custodians; monitor incomplete responsibility fields. | Operations |
| R13 | Plan/rate revisions overwrite historical meaning. | Financial | Medium / High | Preserve original baselines and explicit revisions; test historical reports after changes. | Costing / application team |
| R14 | Audit and retention policies are not operationalised. | Governance | Medium / High | Review event coverage; monitor storage; agree retention and legal hold before activating cleanup. | Audit / IT operations |
| R15 | Claimed 80% benefit cannot be demonstrated. | Benefits | Medium / Medium | Measure baseline and pilot hours using the same activities; track adoption and exceptions. | Sponsor / finance |

# 4.0 Benefit of the Implementation

## 4.1 Operational Benefits

WellCosting Pro is expected to reduce repetitive spreadsheet updates, copy-and-paste work and manual consolidation. Reusing well plans, reference items and stored transactions should allow staff to spend more time validating exceptions and understanding performance. Common scope and classification rules should make working practices more consistent between wells and between drilling and completion teams.

A shared operational record also reduces the need to establish which emailed or printed file is the latest version. Authorised users can inspect current saved information and generate outputs from an identified scope and reporting period. Visibility depends on the completeness and timeliness of captured data.

## 4.2 Financial Benefits

Consistent calculation of service charges, quantities, budget consumption and balances should improve cost control. Earlier visibility of over-budget positions and NPT/UPA attribution should support timely investigation and commercial discussion. Reduced compilation and reconciliation work is expected to lower administrative effort and printing costs.

No quantified reduction in drilling expenditure, recoverable vendor costs or financial losses is asserted. These outcomes depend on operational decisions and should be measured separately from staff-time savings.

## 4.3 Governance and Audit Benefits

Permission-controlled workflows and recorded actions improve accountability for estimates, changes and corrections. Document revision chains help identify the PO/SO copy relevant to a commercial reference. Source-level drill-down and reconciled exports should make reviews faster and reduce dependence on spreadsheet formula inspection.

Auditability supports internal governance; it does not by itself establish statutory compliance, tamper-proof records or mandatory separation between preparer and approver.

## 4.4 Security Benefits

Workspace isolation, server-side permissions, rotating refresh sessions and controlled password changes provide an access-control foundation. Deliberate permission assignment and review can reduce unauthorised access to business records and exports. Additional authentication requirements such as SSO or MFA need a separate decision if mandatory for deployment.

## 4.5 Strategic Benefits

A common structured dataset provides a stronger basis for comparing well performance, analysing service and vendor costs and evaluating consumption trends. It creates an input for future BI and forecasting initiatives once reporting definitions and data quality are established.

## 4.6 User Experience and Process Discipline

Search, filters, imports, reusable sets and shared working scope reduce repetitive selection work. Unsaved-change protection reduces accidental loss of typed values. Consistent register patterns and visible field-level validation should improve training and everyday use. Formal adoption and support remain essential.

## 4.7 Benefit Measurement

| Measure | Baseline | Target / acceptance approach |
| --- | --- | --- |
| Manual effort | Measure current entry, checking, consolidation, MIS and distribution staff hours. | Approximately 80% reduction across agreed included tasks after stabilisation. |
| Repeat entry | Count rekeying steps for a representative daily transaction. | No rekeying into standard supported reports. |
| Monthly MIS lead time | Measure time from approved cut-off to issue. | Target to be agreed after baseline; report preparation must use the accepted ledger. |
| Reconciliation quality | Count unresolved source-to-report differences. | All material differences explained and signed off under agreed tolerances. |
| Adoption | Record wells and users using the controlled process. | All in-scope active wells transitioned before legacy working sheets are retired. |
| Exception resolution | Track incomplete classifications and disputed costs. | Named owners and agreed response times; targets to be confirmed. |

Manual effort reduction (%) = (baseline hours − comparable post-go-live hours) / baseline hours × 100. Compare equivalent well coverage, transaction volumes and reporting obligations. Separate implementation/training effort from steady-state operating effort. Do not convert saved hours into monetary ROI without agreed staffing rates, implementation cost and operating cost.

# 5.0 Business and Functional Requirements

## 5.1 Workspace, Users and Permissions

| ID | Requirement | Status |
| --- | --- | --- |
| FR-001 | Require workspace, email and password sign-in; expose business records only within the authenticated workspace. | Evidenced |
| FR-002 | Manage users, roles, permissions and assignments; enforce permissions on API actions as well as visible controls. | Evidenced |
| FR-003 | Protect the owner role against ordinary editing or deletion and restrict users from delegating grants beyond their own authority. | Evidenced |
| FR-004 | Support password change, session revocation and rotating refresh sessions. | Evidenced |
| FR-005 | Agree a least-privilege persona-to-permission matrix, including estimate approval, daily reopen, amendment, export and purge rights. | Proposed governance |
| FR-006 | If policy requires different people to prepare, review and approve, enforce and test that rule explicitly. Permission stages alone shall not be accepted as maker-checker enforcement. | Proposed |

## 5.2 Reference Data and Commercial Registers

| ID | Requirement | Status |
| --- | --- | --- |
| FR-007 | Maintain units, currencies, phases, hole sections and activities using workspace-specific codes and controlled lifecycle operations. | Evidenced |
| FR-008 | Maintain one active default currency per workspace and preload it in applicable entry forms. | Evidenced |
| FR-009 | Maintain services with manually entered unique code, category, reporting group, provider type and vendor reference. | Evidenced |
| FR-010 | Group services under Rig Operations, Formation Evaluation, Well Services, Land Facilities and Preparation, Miscellaneous Services and Supervisions for reporting. | Evidenced |
| FR-011 | Maintain vendor identity, contacts, commercial classification and active/inactive/blocked state; prevent disallowed orders and protected-reference deletion. | Evidenced |
| FR-012 | Maintain PO/SO registers and amendment chains with revision reason and current-version indication. Store supporting copies separately from costing rates; the order register carries no price/value ledger. | Evidenced |
| FR-013 | Attach multiple documents per order revision, identify duplicates, preserve document metadata and separately control upload/download/delete permissions. | Evidenced |
| FR-014 | Maintain tangible and consumable catalogue records, including applicable mud chemicals, cement additives, fuel and drill bits; preserve applicable rate revision history. | Evidenced |
| FR-015 | Provide reference imports with preview and errors and authorised exports where supported; use documented templates and migration mappings. | Evidenced; rollout mapping proposed |

## 5.3 Rig, Well and Configuration Management

| ID | Requirement | Status |
| --- | --- | --- |
| FR-016 | Maintain blocks, rigs and wells with validated workspace relationships. | Evidenced |
| FR-017 | Maintain independent drilling and completion configurations, sections, ordered depths, phases and planned days. | Evidenced |
| FR-018 | Control configuration and operational lifecycle, including draft/configured planning and applicable active/final-review/completed states. | Evidenced |
| FR-019 | Maintain scope-specific well sub-activities linked to master activities, including hierarchy and NPT/UPA responsibility. | Evidenced |
| FR-020 | Record operational milestone timestamps and section progress; derive scope-specific progress without using a transaction creation date as an operational event. | Evidenced |
| FR-021 | Revise well plans through explicit adjustments with reasons and before/after values while preserving the original plan's meaning. | Evidenced |

## 5.4 AFE Management and Estimation

| ID | Requirement | Status |
| --- | --- | --- |
| FR-022 | Create well-scoped drilling/completion AFEs with unique code, description and matching configured well/rig scope. | Evidenced |
| FR-023 | Estimate service costs using Day Rate, Per Section Rate and Per Service Rate bases and configured charge categories. | Evidenced |
| FR-024 | Support operating/standby/personnel charges, mobilisation/demobilisation, fixed charge and other defined categories; treat designated one-time charges as whole amounts. | Evidenced |
| FR-025 | Estimate consumables using category allowances or drill-bit quantities/rates, and tangibles using quantities and effective rates. | Evidenced |
| FR-026 | Preview calculations and validation before saving; provide scope and section rollups and complete currency conversion. | Evidenced |
| FR-027 | Control AFE progression through Draft → Submitted → Review → Approval; permit authorised reopen with reason. | Evidenced |
| FR-028 | Prevent ordinary header/estimate edits outside Draft; expose stage-specific permissions and recorded workflow history. | Evidenced |
| FR-029 | Produce the AFE print report with service grouping, supporting item detail and recorded submission/review/approval identities. | Evidenced |
| FR-030 | Maintain controlled scope-of-work revisions, deriving revised totals from changed estimate lines and applying approved effective adjustments in supported comparisons. | Evidenced |

## 5.5 Daily Cost Management

| ID | Requirement | Status |
| --- | --- | --- |
| FR-031 | Create a daily sheet against well, AFE and cost date; prevent duplicate sheets for the same well/AFE/date combination. | Evidenced |
| FR-032 | Establish locked budget, rate and catalogue references so subsequent reference changes do not silently rewrite history. | Evidenced |
| FR-033 | Capture service, consumable, tangible and other-expense lines with applicable activity, sub-activity, section, phase, vendor and depth details. | Evidenced |
| FR-034 | Derive Planned/UPA/NPT classification from the approved activity setup and require applicable justification/responsibility. | Evidenced |
| FR-035 | Allocate a time-based service across activities using hours, with a maximum of 24 allocated hours for the service entry; retain scope-specific ledger rows. | Evidenced |
| FR-036 | Charge one-time categories once against the defined allocation and keep per-service/per-section charges whole as defined by the costing rules. | Evidenced |
| FR-037 | Offer manual amount/rate overrides where supported, without duplicating a manually entered total across allocations. | Evidenced |
| FR-038 | Preview sheet totals and budget impact; save actuals once for reuse by supported reports. | Evidenced |
| FR-039 | Support Draft → Submitted and authorised Submitted → Draft reopen with reason. Submitted sheets shall be reopened before ordinary edit/delete. | Evidenced |
| FR-040 | Require the amendment capability for reopening sheets older than the implemented 30-day threshold and record historical changes. | Evidenced |
| FR-041 | Permit explicit application of current AFE service rate versions without silently repricing saved historical costs or replacing the original budget. | Evidenced |
| FR-042 | Support well/date/AFE filters, cumulative values, imports, controlled deletion/recovery and daily or well-period print outputs. | Evidenced |
| FR-043 | Retain shared rig/well selection across supported daily, mud, LIH and NDT register navigation. | Evidenced |

## 5.6 Reusable Costing Sets

| ID | Requirement | Status |
| --- | --- | --- |
| FR-044 | Save reusable selections of services, tangibles and consumables to reduce repeated item picking. | Evidenced |
| FR-045 | Offer private and workspace-global visibility; global sets remain within the workspace and creator-controlled for mutation. | Evidenced |
| FR-046 | Reuse item references without treating the set as a shared fixed price book; apply relevant rates and enter transaction quantities at use. | Evidenced |

## 5.7 Mud, Fuel, LIH and NDT

| ID | Requirement | Status |
| --- | --- | --- |
| FR-047 | Maintain section-specific mud systems (WBM, OBM, SOBM and Others), base cost inputs, receipts, additions, losses and calculated stock. | Evidenced |
| FR-048 | Carry mud opening/closing balances using defined rules; require dedicated permission for applicable opening-stock correction. | Evidenced |
| FR-049 | Reconcile mud chemical cost from daily actuals and section inputs, using the correct locked AFE mud allowance rather than the entire section budget. | Evidenced |
| FR-050 | Separate surface and other losses and provide applicable cumulative quantities and loss-per-metre calculations. | Evidenced |
| FR-051 | Maintain fuel receipts, rig-engine and company consumption, actual/book closing stock, carry-forward, variance and separately identified rig-saving litres. | Evidenced |
| FR-052 | Control fuel opening-stock overrides and classify company consumption without assuming automatic financial posting. | Evidenced |
| FR-053 | Maintain LIH items by well/date with dimensions, identifying details, units and unit cost; save multiple lines and derive totals. | Evidenced |
| FR-054 | Include LIH once in designated well-level actual/balance comparisons and show its contribution separately. | Evidenced |
| FR-055 | Maintain line-wise NDT descriptions, quantity received/consumed, backloaded good/bad and remarks under the selected well and operating scope. | Evidenced |
| FR-056 | Print NDT details conditionally in applicable daily reports; do not imply an inspection-date field or a monetary NDT posting that is not defined. | Evidenced |

## 5.8 Analysis, Lifecycle and Audit

| ID | Requirement | Status |
| --- | --- | --- |
| FR-057 | Provide business and module dashboards showing permitted plan, budget, actual, variance, progress and exceptions. | Evidenced |
| FR-058 | Analyse costs by applicable date, well, rig, AFE, service/item, vendor, section, phase, activity and classification. | Evidenced |
| FR-059 | Provide well comparison, usage, consumption/loss and NPT/UPA reports with drill-down and supported exports. | Evidenced |
| FR-060 | Soft-delete ordinary business/master records first; provide authorised restore and confirmed purge with dependency checks. Security-account exceptions remain separately controlled. | Evidenced |
| FR-061 | Record relevant mutation, workflow, import/export and security events with actor, action, entity, summary and time; verify event coverage in UAT. | Evidenced; coverage acceptance required |
| FR-062 | Provide read-only workspace database browsing and controlled extracts with credential/session data excluded. Treat the capability as broad workspace access. | Evidenced |
| FR-063 | Preserve typed input through Save / Discard / Continue editing decisions in supported dialogs and navigation guards in full-page editors. | Evidenced |

# 6.0 Reporting and Monthly MIS Requirements

## 6.1 Reporting Principles

Reports shall derive from authoritative records instead of a separately typed consolidation workbook. Every issued output shall identify its business scope, reporting dates, currency basis and treatment of drafts, amendments and exclusions. Where a measure uses a locked baseline, current estimate or approved adjustment, that basis must be apparent to the reviewer.

Weekly, monthly and yearly reporting shall reuse date-filtered data. A selected range alone does not imply automatic weekly buckets, month-end closure, year-to-date comparison or a frozen certified MIS version. Those outputs must be agreed and accepted separately where required.

## 6.2 Report Catalogue

| ID | Report | Main business content | Status / limitation |
| --- | --- | --- | --- |
| RP-01 | AFE estimate | Scope, grouped services, consumables, tangibles, totals and workflow identities. | Evidenced; validate print at expected line counts. |
| RP-02 | Daily well cost report | Previous/current/cumulative costs, plan/balance and supporting operational panels. | Evidenced; validate measure basis and dense print cases. |
| RP-03 | Well cost analysis | Budget/actual, classifications, factor cuts, mud reconciliation and LIH contribution. | Evidenced; distinguish recorded and comparison actual. |
| RP-04 | Well cost comparison | Comparable well/rig/AFE plan, cost and performance positions. | Evidenced; align filters and currencies before comparison. |
| RP-05 | Business dashboard | Plan, budget, actuals, cost trends, progress and exceptions. | Evidenced; sections are permission-scoped. |
| RP-06 | Mud chemicals usage | Item quantities/costs by well and section. | Evidenced; uses ledger actuals, not reconciled mud valuation. |
| RP-07 | Drill bits usage | Bit identity/specification, quantity/cost and well/section use. | Evidenced |
| RP-08 | Tangibles usage | Item/category quantities and cost by well/section. | Evidenced |
| RP-09 | Service-wise cost | Service costs across wells and sections. | Evidenced; monetary report, not a universal hours measure. |
| RP-10 | Vendor/company-wise cost | Ledger-attributed costs across services, consumables and tangibles as available. | Evidenced; not an accounts-payable or paid-invoice statement. |
| RP-11 | NPT/UPA report | Classification costs and distinct classified cost-date counts by well. | Evidenced; hours-derived MIS duration remains a decision. |
| RP-12 | Consumption and losses | Section/well surface and other mud losses with supporting detail. | Evidenced |
| RP-13 | Fuel register analysis | Receipts, consumption, carry-forward, book/actual balance, variance and rig-saving quantities. | Evidenced; do not infer monetary posting. |
| RP-14 | LIH register report | Item/day detail, quantities and monetary totals. | Evidenced; reconcile designated summary inclusion. |
| RP-15 | Monthly MIS pack | Agreed executive tables, consolidated cost, NPT/UPA duration/cost, variances and commentary. | Partial / proposed certification and packaging. |
| RP-16 | Audit / controlled data extracts | Change evidence and workspace-scoped CSV/XLSX/PDF outputs where available. | Evidenced; access/export controls apply. |

## 6.3 MIS Requirements for Agreement

| ID | Requirement | Acceptance expectation |
| --- | --- | --- |
| MIS-01 | Define the reporting calendar, financial year, time zone and inclusive start/end dates. | Finance signs off representative weekly, monthly and annual examples. |
| MIS-02 | Consolidate selected wells by agreed rig/block and drilling/completion scope without rekeying. | Totals reconcile to included source records for the chosen period. |
| MIS-03 | Show original AFE, approved changes, effective budget, actual, remaining balance and utilisation on an explicit basis. | Reviewers can explain any difference between live estimate and historical baseline. |
| MIS-04 | Separate period cost from cumulative-to-date cost. | Opening cumulative + period movement equals closing cumulative after defined corrections. |
| MIS-05 | Show NPT and UPA costs and an agreed duration measure. | Labels distinguish affected dates, fractional allocated days and elapsed operation time. |
| MIS-06 | Identify drafts, excluded currencies, incomplete conversions and unresolved data exceptions. | No unexplained omission or misleading zero in certified outputs. |
| MIS-07 | Provide source detail for material variances and responsibility-based review. | Sample reported exceptions can be traced to well/date/line and responsible party. |
| MIS-08 | Define treatment of late entries, reopening, amendments and reissued reports. | A correction example retains the reason and allows reconciliation to the previously issued report. |
| MIS-09 | Establish certification, version naming, issue authority and archive location. | One accepted MIS version can be reproduced from retained evidence. |
| MIS-10 | Export required tables without manual compilation of figures already available in the platform. | Finance can complete the accepted MIS process using generated values and separate management commentary. |

## 6.4 NPT / UPA Duration Decision

Current report behaviour: for each well and classification, count distinct cost dates containing that classification. Repeated charge lines on the same date do not increase that classification's count. However, a date containing both NPT and UPA contributes to both counts. Portfolio totals are sums of well-classification date counts, not a unique calendar duration across the portfolio.

Example: a service has 10 planned hours, 11 NPT hours and 3 UPA hours on one date. Fractional allocated durations are 10/24, 11/24 and 3/24 days respectively. The current classification-date report can instead show one affected date in each category. Neither label may be substituted for the other.

For an hours-derived MIS duration, operations and finance must define how to identify the authoritative time record and avoid counting the same operational hours repeatedly across simultaneous services, charge categories and cost lines. An implemented per-service 24-hour validation is not proof that whole-well elapsed time is deduplicated. This is a reporting-definition and potential delivery gap requiring explicit UAT before claiming automated MIS duration.

# 7.0 Data, Calculation and Control Requirements

## 7.1 Authoritative Data and Relationships

| Data group | Authoritative record | Key controls |
| --- | --- | --- |
| Reference | Workspace master and catalogue registers. | Unique codes, valid references, lifecycle and assigned custodians. |
| Well plan | Scoped well configuration and approved plan adjustments. | Drilling/completion separation, valid depths and phase days. |
| Budget | Saved AFE and approved SOW revisions; locked daily baselines for historical comparisons. | Identify original, revised and frozen values explicitly. |
| Actual | Saved daily service/consumable/tangible/other-expense rows. | Well/AFE/date uniqueness, valid scope and applicable FX. |
| Mud quantities | Section mud register and configuration. | Carry-forward and defined receipt/addition/loss categories. |
| Mud comparison cost | Shared reconciliation logic using section actuals and mud inputs. | Replace designated mud component; do not add it a second time. |
| Fuel quantities | Fuel day and company-consumption lines. | Book/actual stock, carry-forward and authorised correction. |
| LIH cost | LIH day/item register. | Currency-aware inclusion once in designated summaries. |
| NDT quantities | NDT inspection lines. | Scope and quantity validation; no assumed inspection date. |
| Change evidence | Audit and explicit workflow/revision records. | Controlled access, retention and agreed coverage checks. |

Persist business attributes in typed relational columns rather than JSON/JSONB payload columns. API JSON interchange is permitted. Supporting order documents are binary attachments with typed metadata. This data-design principle supports traceable relationships and predictable extracts.

## 7.2 Calculation Rules

| ID | Calculation / rule | Required interpretation |
| --- | --- | --- |
| CAL-01 | Time charge = rate per day × allocated hours / 24, or rate × entered days as applicable. | Respect configured charge category and scope; designated one-time charges are not repeated across allocations. |
| CAL-02 | Quantity-based line = quantity × effective rate. | Preserve item, unit, currency and applicable captured/override rate. |
| CAL-03 | Mixed-currency AFE conversion = entered amount × units of standard currency per foreign unit. | Require all relevant positive FX factors; do not combine unconverted amounts. |
| CAL-04 | Recorded daily total = services + consumables + tangibles + other expenses. | LIH remains separately identifiable and enters designated well measures. |
| CAL-05 | Comparison consumables = recorded consumables − recorded mud chemicals + comparison mud cost. | Reconciled value replaces the designated component. |
| CAL-06 | Comparison actual = recorded actual − recorded mud chemicals + comparison mud cost. | Designated comparison including LIH adds LIH once. |
| CAL-07 | Remaining budget = selected effective/baseline budget − corresponding actual measure. | Specify original versus adjusted budget and recorded versus reconciled actual; preserve negative balances. |
| CAL-08 | Utilisation (%) = corresponding actual / corresponding budget × 100. | A zero/missing denominator produces a labelled unavailable result, not a division error. |
| CAL-09 | Mud closing = opening + receipts + additions − consumption/losses − other deductions. | Calculated closing carries forward under the register's rules. |
| CAL-10 | WBM cost per barrel = actual mud chemical cost / additions; comparison mud cost remains actual cost. | Zero additions make the unit rate unavailable. |
| CAL-11 | Non-WBM total mud = opening + extra OBM received + additions. Alpha = (opening + extra OBM) × base rate; beta = alpha + actual mud chemical cost. | Comparison unit rate = beta / total mud; reconciled cost = consumption/losses × unit rate. Zero denominator remains unavailable. |
| CAL-12 | Mud planned cost = the section/scope's locked AFE Mud Chemicals allowance. | Do not substitute the total section budget, which includes other cost categories. |
| CAL-13 | LIH line cost = number of units × unit cost. | Reconcile per currency and retain item identity. |
| CAL-14 | Surface loss rate = applicable cumulative surface loss / latest applicable section depth. | State bbl/m and date/scope; missing or zero depth is unavailable. |
| CAL-15 | NPT/UPA days in the current report = count of distinct classified cost dates per well. | Not hours-derived duration; see section 6.4. |

Input decimal precision supports up to ten fractional places in the shared contract, subject to field-specific limits. Financial presentation generally uses two decimals, while underlying reconciliation and quantity calculations retain their defined precision. UAT shall confirm rounding at line, group and report levels with worked examples, including fractional hours and FX.

## 7.3 Financial and Operational Controls

1. Validate that all referenced records belong to the workspace and selected business scope.
2. Require configured plans and saved, fully priced estimates where the costing workflow needs them. Do not equate a saved AFE with final approval; confirm whether a stricter approval gate is required for daily costing.
3. Preserve historical baselines and explicitly version service rate changes; do not silently revise saved actual amounts.
4. Control estimate transitions, daily submission and reopening with distinct permissions and reasons.
5. Require the additional historical amendment permission for sheets beyond the implemented threshold.
6. Protect active dependencies from deletion; restore and purge only through permitted recovery workflows.
7. Ensure exports are permission controlled and that spreadsheet formula-injection protection is tested in relevant outputs.
8. Define and test concurrent-edit behaviour; prevent silent overwriting and duplicate posting in representative multi-user scenarios. LIH already exposes an expected-revision contract, but uniform conflict protection is not assumed for every module.
9. Keep reports reproducible through clear filters, source references and agreed issue evidence. Formal month-close locking remains a proposed requirement.

# 8.0 Technical, Security and Operational Requirements

## 8.1 Technical Baseline

The reviewed application uses React 19 and TypeScript with Material UI, AG Grid and ECharts in the browser; FastAPI and SQLAlchemy in the API; Alembic for schema migrations; and PostgreSQL for the intended deployed database. SQLite supports local development and lightweight tests and does not establish PostgreSQL locking or concurrency behaviour.

Repository deployment guidance describes a Vercel frontend, Render API and Supabase PostgreSQL arrangement. Docker Compose and local execution are also documented. These are deployment options, not confirmation of the organisation's selected hosting or any live service state.

## 8.2 Non-Functional Requirements

| ID | Requirement | Evidence / acceptance position |
| --- | --- | --- |
| NFR-01 | Enforce workspace isolation and server-side permission checks across records, references, reports and exports. | Evidenced; negative-access UAT required. |
| NFR-02 | Use HTTPS in the deployment, secure cookies and controlled secrets; prevent secret values appearing in user extracts. | Deployment control to verify. |
| NFR-03 | Keep access tokens short-lived and refresh sessions revocable; invalidate sessions on password change. | Evidenced foundation. |
| NFR-04 | Provide read-only audit access and define retention, monitoring and recovery arrangements. | Audit exists; operational policy and completeness verification required. |
| NFR-05 | Provide light/dark operation, clear validation, keyboard-usable controls and standard register interactions. | Shared UI patterns evidenced; accessibility acceptance required. |
| NFR-06 | Offer quick/advanced filters and separate date controls; use 20/50/100 list page sizes. | Standing product convention; check each in-scope screen. |
| NFR-07 | Protect unsaved entries and give useful local error messages. | Shared guards evidenced; verify representative dialogs/editors. |
| NFR-08 | Support agreed data volumes and concurrent users within agreed response times. | Proposed measurable performance acceptance; values not yet supplied. |
| NFR-09 | Back up database and stored order documents and demonstrate restoration. | Proposed operating requirement; no backup guarantee inferred. |
| NFR-10 | Set availability, RPO, RTO, support hours and escalation responsibilities. | Values and service owner to be agreed. |
| NFR-11 | Use controlled migrations and release validation before deployment. | Alembic and test/build workflows evidenced. |
| NFR-12 | Render exports and printouts completely at agreed worst-case sizes. | Existing print structures evidenced; stress/physical output acceptance required. |
| NFR-13 | Protect business data through infrastructure access controls and agreed encryption-at-rest/retention policies. | Hosting/security configuration to verify. |
| NFR-14 | Monitor application failures, capacity, database availability and backup outcomes. | Proposed readiness requirement; health endpoint alone is insufficient. |

No numerical performance or service-level commitment is invented here. Before go-live, IT and the sponsor must approve volumes, concurrency, response-time percentiles, availability and recovery objectives and supply evidence against those values.

## 8.3 Access and Export Governance

The permission model shall distinguish read, create, update, delete, restore, permanent delete, import, export and workflow actions where provided. Document custody permissions are separately grantable. Database-browser access is intentionally broad within a workspace and shall be restricted to approved users; it must not be assumed to follow every individual module's narrower access grant.

Users responsible for preparing costs should receive only the capabilities needed for that work. Approvers, reopen/amend operators and administrators shall be reviewed periodically. If independent approval is required by policy, acceptance must demonstrate enforced separation rather than relying on role names.

## 8.4 Business Continuity and Support

Before launch, the operator shall document backup scope and frequency, restoration steps, loss/recovery objectives, account recovery, database capacity monitoring, incident escalation and ownership of failed imports or reports. Order attachments are held in the database in the reviewed implementation and must be included in backup/restore verification.

A network outage contingency shall define temporary capture, unique references and later entry/reconciliation. It shall not be described as application offline synchronisation. The support team shall distinguish operational data errors from software faults and route each to a named owner.

# 9.0 Migration, Implementation and Acceptance

## 9.1 Legacy Data Migration

Migration shall be a controlled business exercise rather than a bulk copy of spreadsheet formulas. The agreed authoritative values and their source evidence shall be mapped to typed application records. Legacy workbook formulas shall be translated into approved business calculation cases where necessary; formulas are not imported as a replacement costing engine.

| Stage | Activity | Required evidence |
| --- | --- | --- |
| Inventory | List wells, workbook versions, SharePoint sources, dates, currencies, owners and reports. | Approved source inventory and authoritative-version decisions. |
| Scope | Agree historical period, active/completed wells and balances versus transaction-level detail. | Migration scope and cut-off sign-off. |
| Cleanse | Resolve duplicate codes, vendor names, units, activity classifications, missing dates and disputed values. | Mapping workbook and exception register. |
| Map | Define master, well/plan, AFE, daily line, mud, fuel and LIH mappings. | Field mapping and business key specification. |
| Trial load | Use supported imports and approved scripts for gaps; validate references and row errors. | Trial logs and rejected-row resolution. |
| Reconcile | Compare counts, quantities, budgets and costs by well/period/currency; check NPT/UPA rules. | Source-to-target reconciliation signed by owners. |
| Cutover | Freeze agreed legacy entry, load final changes and retain source archives. | Cutover checklist and approved opening position. |
| Stabilise | Monitor completeness, duplicate entries, corrections and reporting differences. | Hypercare issue log and closure approval. |

Do not invent historical approval actions, transaction dates or audit provenance. If historical costs cannot be reconstructed to line detail, agree a separately identified opening/history treatment and its reporting limitations before loading them.

## 9.2 Implementation Approach

1. Confirm business rules, MIS definitions, permissions, source data owners and open decisions.
2. Configure infrastructure, workspaces, reference data and role grants.
3. Configure representative drilling and completion wells and validate AFE and daily workflows.
4. Run trial migration and reconcile representative legacy records.
5. Pilot capture and reporting for selected wells covering key costing and reconciliation cases.
6. Complete functional, reporting, security, performance and continuity acceptance.
7. Train users, complete cutover, activate support and retire superseded editable working sheets after acceptance.
8. Measure benefits after an agreed stabilisation period and address residual manual work.

No implementation dates, staffing commitments or project cost are implied. The project owner shall establish them after data scope and remaining delivery gaps are approved.

## 9.3 UAT and Business Acceptance Criteria

| ID | Acceptance scenario | Expected result / related requirements |
| --- | --- | --- |
| AC-01 | Attempt cross-workspace record, attachment and report access and actions without grants. | Access denied; no cross-tenant leakage. FR-001–006, NFR-01. |
| AC-02 | Load reference data with duplicates, invalid references and mixed unit/currency inputs. | Valid rows behave as documented; errors are traceable; no unauthorised change. FR-007–015. |
| AC-03 | Configure drilling and completion with different sections, days and sub-activities. | Plans and transactions remain correctly scoped and independently controlled. FR-016–021. |
| AC-04 | Price day/hour, section, service, fixed and quantity-based AFE lines. | Results match approved worked examples and currency conversion. FR-022–026, CAL-01–03. |
| AC-05 | Submit/review/approve/reopen an AFE with permitted and unpermitted users. | Valid transitions succeed; edits in protected states fail; reasons/history remain visible. FR-027–030. |
| AC-06 | Save the same well/AFE/date twice and allocate services 10/11/3 hours plus mobilisation. | Duplicate sheet prevented; allocation and one-time costs match the agreed rules. FR-031–038. |
| AC-07 | Change catalogue/AFE rates after saved daily costs; explicitly select updated rates. | History stays unchanged until authorised explicit action; original budget remains identifiable. FR-032, FR-041. |
| AC-08 | Submit a sheet; reopen recent and more-than-30-day-old sheets. | State controls and amendment permission apply; reasons and changes are traceable. FR-039–040. |
| AC-09 | Enter and correct mud balances for WBM and non-WBM; include zero denominators. | Stock and costing reconcile; unavailable values are clear; section mud plan uses its own allowance. FR-047–050, CAL-09–12. |
| AC-10 | Record fuel receipts/consumption, rig savings, closing variance and opening override. | Carry-forward and quantities reconcile; no undocumented double financial posting. FR-051–052. |
| AC-11 | Save multiple LIH lines, change a stale revision and report well totals. | Totals reconcile, conflicts are handled, LIH included once in designated outputs. FR-053–054. |
| AC-12 | Add NDT lines under one well/scope and print with/without entries. | Quantities persist separately and conditional print works; no invented inspection date. FR-055–056. |
| AC-13 | Use private/global sets and try another user's edits. | Visibility and creator-only mutation follow workspace boundaries. FR-044–046. |
| AC-14 | Compare well summary, dashboard, usage matrix and exported data for identical scope. | Differences are explained by documented currency, draft, LIH and reconciliation bases. FR-057–059, MIS-02–06. |
| AC-15 | Prepare an agreed weekly, monthly and annual output using multiple wells. | No rekeying of captured figures; period/cumulative totals reconcile; exclusions are explicit. BO-02, MIS-01–10. |
| AC-16 | Report NPT/UPA on a date shared by multiple services/classifications. | Current affected-date measure matches its label; any required fractional-duration solution avoids duplicate operational time. MIS-05, CAL-15. |
| AC-17 | Delete, restore and purge records with dependent data. | Lifecycle rules and permissions apply; dependencies are protected and audit evidence remains as designed. FR-060–062. |
| AC-18 | Cancel/navigation with unsaved values; inspect import/export and dense print outputs. | Values are protected; generated outputs are usable and complete. FR-063, NFR-05–07, NFR-12. |
| AC-19 | Restore a protected backup including attachments and test representative production load. | Approved recovery and performance objectives are met with retained evidence. NFR-08–10. |
| AC-20 | Measure pilot staff hours for the same agreed tasks as the Excel baseline. | Report actual benefit against the approximately 80% target and residual manual activities. BO-01, section 4.7. |

## 9.4 Go-Live Readiness and Exit Conditions

Go-live acceptance requires nominated business signatories; approved rules and unresolved-gap treatment; reconciled migration; passing critical UAT cases; no unresolved critical security/data-integrity defects; configured backup and demonstrated restore; accepted capacity/print evidence; trained users; and a named support owner.

A certified Monthly MIS claim additionally requires agreement on fractional versus affected-date durations, draft inclusion, currency and adjustment bases, cut-off, certification and reissue controls. Existing automated reports alone do not close these decisions.

## 9.5 Review and Verification Boundary

The review considered routed frontend modules, API contracts, domain/services, typed models, migration history, regression tests, repository conventions, deployment guidance and supplied report examples. The source inventory covers 288 application, test and migration files, totalling approximately 97,620 lines. Inventorying establishes coverage of the repository structure, not line-by-line proof of correctness.

Source evidence was prioritised over stale narrative planning notes. Technical verification results accompanying this document are recorded in a separate review note. No live deployment inspection, production data audit, penetration test, load benchmark or business UAT is represented as completed.

# 10.0 Open Decisions and Approval

## 10.1 Decisions Required

| ID | Decision | Why it matters | Proposed owner |
| --- | --- | --- | --- |
| OD-01 | Confirm business sponsor, document owner, module custodians and signatories. | Establish accountability and approval authority. | Sponsor |
| OD-02 | Define NPT/UPA duration for MIS and authoritative time attribution/deduplication. | Current date counts do not meet every duration-based reporting need. | Operations / MIS |
| OD-03 | Define reporting week, fiscal year, time zone and period cut-off. | Ensure consistent weekly/monthly/yearly results. | Finance |
| OD-04 | Choose draft/submitted inclusion and whether daily entry requires an approved AFE. | Avoid implying stronger approval gates than implemented. | Finance / operations |
| OD-05 | Agree reported actual basis: recorded, mud-reconciled and LIH-inclusive; align dashboard/report reconciliation. | Prevent contradictory totals and double counting. | Finance / costing |
| OD-06 | Agree reporting currency, FX direction/source, rounding and excluded-record treatment. | Permit comparable consolidated figures. | Finance |
| OD-07 | Define complete Monthly MIS layout, commentary, certification, archival and reissue process. | Determine remaining MIS delivery scope. | MIS / management |
| OD-08 | Agree historical migration period, authoritative files, acceptable tolerances and opening/history treatment. | Control data quality and cost of migration. | Costing / finance |
| OD-09 | Confirm separation of duties and whether MFA/SSO or additional account recovery is mandatory. | Resolve security delivery requirements. | IT security / audit |
| OD-10 | Set retention, recovery, availability, response-time and user/data-volume objectives. | Make operational readiness measurable. | IT / sponsor |
| OD-11 | Confirm any automatic financial relationship between fuel quantities and daily fuel costs, and whether NDT needs an inspection date. | Avoid unapproved posting and period-report assumptions. | Operations / costing |
| OD-12 | Agree baseline/pilot measurement and assessment date for the 80% target. | Establish credible benefit evidence. | Sponsor / finance |

## 10.2 Approval Record

| Role | Name | Approval / comments | Date |
| --- | --- | --- | --- |
| Business sponsor | To be nominated | Pending | Pending |
| Drilling / completion owner | To be nominated | Pending | Pending |
| Costing / finance / MIS owner | To be nominated | Pending | Pending |
| IT applications / security owner | To be nominated | Pending | Pending |
| Audit / governance representative | To be nominated | Pending | Pending |

Approval confirms the agreed scope, rules, delivery gaps and acceptance basis. It shall not be interpreted as evidence that every proposed requirement is already delivered.

# Appendix A — Repository Traceability

The following paths are relative to the reviewed repository. These references support the evidence classification and enable reviewers to inspect the underlying workflows.

| Requirement group | Principal source evidence | Relevant regression coverage |
| --- | --- | --- |
| Routing and capability coverage | frontend/src/App.tsx; frontend/src/components/Layout.tsx; backend/app/main.py. | backend/tests/test_rbac.py; test_business_dashboard.py. |
| Workspace/authentication/RBAC | backend/app/api/auth.py; api/rbac.py; core/security.py; services/dependencies.py; services/provisioning.py. | test_rbac.py; test_bootstrap.py. |
| Master / services / vendors / documents | backend/app/api/master_data.py; api/service_master.py; api/vendor_master.py; corresponding models/schemas; frontend/src/pages/Services.tsx, Vendors.tsx, PoSoOrders.tsx. | test_master_data.py; test_service_master.py; test_vendor_master.py; migration tests. |
| Catalogue and rate history | backend/app/services/catalogue.py; services/catalogue_specs.py; models/catalogue.py; frontend/src/components/catalogue/. | test_catalogue.py; test_decimal_precision.py. |
| Rig/well/scope/configuration | backend/app/api/rig_well.py; models/rig_well.py; models/well_sub_activity.py; frontend/src/pages/Wells.tsx; components/WellConfigurationDialog.tsx. | test_rig_well.py; test_scoped_sub_activities_and_well_deletion.py; scoped migration tests. |
| AFE pricing/workflow/print | backend/app/domain/afe_costing.py; services/afe.py; api/afe.py; frontend/src/pages/AfeEstimate.tsx; components/afe/AfePrintSheet.tsx. | test_afe.py; test_service_groups_migration.py. |
| Revisions and amendments | backend/app/services/sow_adjustment.py; schemas/sow_adjustment.py; api/sow_adjustment.py; frontend/src/components/PlanAdjustmentDialog.tsx; components/afe/SowAdjustmentDialog.tsx. | test_sow_adjustment.py. |
| Daily ledger and baselines | backend/app/services/daily_cost.py; schemas/daily_cost.py; models/daily_cost.py; frontend/src/pages/DailyCostSheet.tsx; lib/dailyAllocations.ts. | test_daily_cost.py; test_depth_and_usd_standardization.py; frontend daily-cost checks. |
| Progress and depth | backend/app/services/daily_cost.py; core/units.py; frontend/src/components/daily-cost/WellProgressPanel.tsx. | test_well_progress.py; depth standardisation tests. |
| Costing sets | backend/app/api/costing_sets.py; models/costing_set.py; frontend/src/pages/CostingSets.tsx. | test_costing_sets.py. |
| Mud stock and reconciliation | backend/app/domain/mud_cost.py; services/mud_cost.py; frontend/src/pages/MudCostAnalysis.tsx. | test_mud_cost.py; test_mud_cost_reconciliation.py; test_mud_cost_migration.py. |
| Fuel operational register | backend/app/services/fuel_cost.py; schemas/fuel_cost.py; frontend/src/pages/FuelCostRegister.tsx; components/fuel-cost/. | test_fuel_cost.py; frontend fuel-cost checks. |
| LIH day/item totals | backend/app/services/lih_cost.py; schemas/lih_cost.py; frontend/src/components/lih-cost/LihWorksheet.tsx. | test_lih_cost.py; frontend LIH worksheet checks. |
| NDT quantities | backend/app/services/ndt_inspection.py; api/ndt_inspection.py; models/ndt_inspection.py; frontend/src/pages/NdtInspectionRegister.tsx. | NDT endpoint scenario in test_daily_cost.py. |
| Dashboard and comparisons | backend/app/services/business_dashboard.py; schemas/business_dashboard.py; frontend/src/pages/BusinessDashboard.tsx; WellCostComparisonReport.tsx; DailyCostAnalysis.tsx. | test_business_dashboard.py; test_daily_cost.py. |
| Usage and NPT/UPA reports | backend/app/services/usage_reports.py; api/usage_reports.py; frontend/src/pages/reports/; components/reports/. | test_usage_reports.py; frontend usage-reports checks. |
| Audit and database browser | backend/app/services/audit.py; api/audit.py; services/database_browser.py; frontend/src/pages/AuditLog.tsx and DatabaseBrowser.tsx. | test_audit.py; test_database_browser.py. |
| UI safeguards and exports | frontend/src/components/Common.tsx, DataTable.tsx, ImportDialog.tsx; lib/export.ts; lib/activeScope.ts. | .agent/tools/ui-check.jsx; daily-cost-scope-check.jsx and focused module checks. |
| Precision / schema / deployment | backend/app/core/precision.py; backend/alembic/versions/; docker-compose.yml; render.yaml; frontend/vercel.json; docs/deployment.md. | test_decimal_precision.py; migration tests; frontend production build. |

# Appendix B — Glossary

| Term | Meaning |
| --- | --- |
| AFE | Authorisation for Expenditure; well-scoped planned cost estimate and its workflow. |
| Actual cost | Cost recorded in the source ledger; distinguish from reconciled comparison and LIH-inclusive measures. |
| Baseline | Captured budget, plan or price reference retained for historical costing/comparison. |
| BRD | Business Requirements Document. |
| Completion scope | Separately configured completion plan, activities and costs for a well. |
| Cost date | Business date assigned to a cost record; distinct from creation/update timestamp. |
| LIH | Lost in Hole; separately registered item costs. |
| MIS | Management Information System reporting / management information pack. |
| NDT | Non-Destructive Testing; inspection quantity register in this application. |
| NPT | Non-Productive Time; activity classification and associated cost/reporting measures. |
| UPA | Unplanned Activity; confirm the organisation's preferred expansion and inclusion rules. |
| WBM / OBM / SOBM | Water Based Mud / Oil Based Mud / Synthetic Oil Based Mud. |
| PO / SO | Purchase Order / Service Order; reference and supporting-document register here. |
| RBAC | Role-Based Access Control. |
| SOW | Scope of Work; controlled estimate/plan changes as applicable. |
| UOM | Unit of Measure. |
| Workspace / tenant | Organisation-scoped access and business-data boundary. |
| RPO / RTO | Recovery Point Objective / Recovery Time Objective. |
| UAT | User Acceptance Testing. |
