# ServiceNow Dev Project

This repository contains local ServiceNow artifacts and helper scripts for testing and deployment.

## What is included

- Incident business rule source:
  - `src/scripts/business-rules/incident_set_priority.js`
- Scripted REST API artifacts for incident creation:
  - `src/rest-apis/servicedesk-incident-api.json`
  - `src/rest-apis/servicedesk-incident-api-resource.js`
  - `src/rest-apis/servicedesk-incident-api-oauth-client.json`
  - `src/rest-apis/servicedesk-incident-api-manual-values.md`
- Business rule deploy script (upsert to `sys_script`):
  - `scripts/deploy-business-rule.js`
- ATF runner:
  - `scripts/run-atf.js`
- Unit tests:
  - `tests/unit/`
- ATF tests:
  - `tests/atf/`

## Prerequisites

- Node.js 18+
- Access to a ServiceNow instance
- Credentials or bearer token with permission to read/write business rules

## Setup

1. Install dependencies:

```bash
npm install
```

2. Create your environment file:

```bash
cp .env.example .env
```

3. Edit `.env` values:

- `SN_INSTANCE_URL`
- `SN_USERNAME` and `SN_PASSWORD`, or
- `SN_TOKEN`

## Available commands

- Run unit tests:

```bash
npm test
```

- Run ATF suite:

```bash
npm run test:atf -- <suite_sys_id>
```

- Deploy default incident business rule:

```bash
npm run deploy:br
```

- Deploy a specific local business rule file:

```bash
npm run deploy:br -- src/scripts/business-rules/incident_set_priority.js
```

## Incident business rule

Name: Incident - Set Priority on Insert/Update

- Table: `incident`
- Timing: `before`
- Actions: `insert`, `update`
- Behavior: recalculates priority based on urgency and impact using the standard 3x3 matrix.

The deployment script performs an upsert by `name + collection` in `sys_script`, so re-running updates the existing rule instead of creating duplicates.

## Notes

- Keep secrets only in `.env` (never commit credentials).
- `.env.example` is intentionally placeholder-only.

### Change Log

| Timestamp | Table | Action | Summary |
|-----------|-------|--------|---------|
| 2026-04-05T07:37:20.840Z | sc_cat_item | Created | Created "Laptop Services" Catalog Item under the Hardware category with variables for Laptop Model, Reason for Request, Preferred OS, and Urgency, plus the required Requested For and Watch List variable sets. |
| 2026-04-05T10:51:14.757Z | sc_cat_item | Synced | Deployed "Laptop Services" Catalog Item to dev214316.service-now.com via basic auth (sys_id: ed699e7d830003106c085a96feaad354); 4 variables and 2 variable sets linked successfully. |
| 2026-04-05T10:53:32.765Z | sys_script | Created | Deployed "Laptop Services - Request Manager Approval" Business Rule on sc_req_item (after insert) that creates a sysapproval_approver record routing approval to the requester's direct manager (sys_id: 2ef1ee3d834003106c085a96feaad3d4). |
| 2026-04-05T11:36:49.013Z | sys_hub_flow | Deleted | Removed partial "Laptop Services - Manager Approval Flow" shell from ServiceNow — full flow deployment via REST is not possible; create manually in Flow Designer UI. |
| 2026-04-05T13:42:42.384Z | sys_hub_flow | Deleted | Removed partial "Incident High Priority - Send Email Notification" flow shell from ServiceNow — full flow deployment via REST is not possible; create manually in Flow Designer UI. |
| 2026-04-05T14:36:44.173Z | sc_service_fulfillment_stage, sc_service_fulfillment_step | Created | Added Manager Approval fulfillment step to "Laptop Services" catalog item via REST (stage sys_id: 857d4fbd838403106c085a96feaad380, step sys_id: 588d0bbd838403106c085a96feaad325) using OOTB Manager approval configuration. |
| 2026-05-13T00:00:00.000Z | sys_db_object, sc_cat_item, item_option_new, sys_script | Created & Reverted | Deployed custom table `u_green_ideas` (4 fields: u_idea_summary, u_estimated_savings, u_department, u_requested_item), catalog item "Submit Green Idea" (Sustainability / Environmental, 3 variables, Requested For variable set), and a business rule on sc_req_item that auto-creates a u_green_ideas record on submission; all records verified then reverted cleanly. |
| 2026-04-05T14:50:47.812Z | sc_cat_item, sc_service_fulfillment_stage, sc_service_fulfillment_step | Created | Created "Calendly Access Request" catalog item (sys_id: 61405b3583c403106c085a96feaad3cf) under Security and Access with 4 variables (Username, Access Type, Group, Business Justification), linked to Step based request fulfillment flow, with 2-level approval: Custom approval (order 100) → Manager approval (order 200). |
| 2026-04-05T15:27:36Z | item_option_new | Created | Added "Requested For" Reference variable (type 8, sys_user lookup) to Requested For variable set (sys_id: 6488dfb1830803106c085a96feaad368), mandatory, order 100. |
| 2026-04-05T15:30:01Z | item_option_new | Created | Added "Watch List (CC)" Glide List variable (type 21, sys_user reference) to Watch List variable set (sys_id: ca899fb5830803106c085a96feaad3d0), allowing multiple user/email selection as CC recipients. |
| 2026-04-06T03:45:32Z | sysevent_email_action | Created | Created "Laptop Request Notification" email notification on incident table (insert), subject "Laptop Request", body "xyz", recipient ssampada@akamai.com (sys_id: 4d910a0e83c843106c085a96feaad3db). |
| 2026-05-13T00:01:00.000Z | sys_db_object, sc_cat_item, item_option_new, sc_service_fulfillment_stage, sc_service_fulfillment_step, sys_script | Created & Reverted | Deployed "Submit Green Idea" catalog item (Sustainability / Environmental) with custom table `u_green_ideas`, 3 variables, OOTB Step-based fulfillment flow, Manager Approval step (order 100) + Task step (order 200) via `sc_service_fulfillment_step`, and business rule creating u_green_ideas records on submission; all 9 records verified then fully reverted. |
| 2026-04-06T03:49:52Z | sc_cat_item, sc_service_fulfillment_stage, sc_service_fulfillment_step | Created | Created "CI Jenkins Request" catalog item (sys_id: ba63c202830c43106c085a96feaad3ca) under Software with 4 variables, linked to Step based request fulfillment flow, with 2-level approval: Custom approval (100) → Manager approval (200). |
| 2026-04-06T05:43:00Z | sys_ws_definition, sys_ws_version, sys_ws_operation, oauth_entity, sys_properties | Created | Deployed native Scripted REST API "Service Desk Incident API" (sys_id: d3a8de86838c43106c085a96feaad376) at POST /api/global/v1/servicedesk_incident_api/incident protected by OAuth 2.0 client credentials (client sys_id: 34b81ec6838c43106c085a96feaad361); enabled glide.oauth.inbound.client.credential.grant_type.enabled system property. |
| 2026-04-06T07:09:13Z | sc_cat_item | Updated | Set assignment group to "Service Desk" (sys_id: d625dccec0a8016700a222a0f7900d06) on "Calendly Access Request" catalog item for request routing. |
| 2026-04-06T07:21:04Z | sc_cat_item, sys_db_object, sys_dictionary, sys_script_include | Created | Created "Request GPT-5 Access" catalog item (sys_id: 90723a8a834083106c085a96feaad355) under AI Services with 2 variables; custom table "u_ai_access_logs" (sys_id: d7b23e8a834083106c085a96feaad362) with 5 columns (User, Model Name, Business Case, Status, Request Date); Script Include "AIAccessUtils" (sys_id: 4303720a834083106c085a96feaad3d6) validating Business Case ≥ 200 chars. |
| 2026-04-06T10:09:14Z | sys_db_object, sys_dictionary, sc_cat_item_producer, item_option_new, io_set_item | Created | Created custom table "u_green_ideas" (sys_id: 83b857c2838483106c085a96feaad32d) with 3 columns (Idea Summary, Estimated Savings (currency), Department (ref cmn_department)); Record Producer "Submit Green Idea" (sys_id: 91e89bc2838483106c085a96feaad37e) under Sustainability category linked to u_green_ideas with map_to_field variables; variable sets Requested For@100, Watch List@500. |
| 2026-04-09T11:36:29Z | sc_cat_item, sys_user_group, item_option_new, io_set_item, sc_service_fulfillment_stage, sc_service_fulfillment_step | Updated/Created | Set up AWA for "3M Privacy Filter - Lenovo X1 Carbon" (sys_id: 6d0f8e1c81df2500772e95d75e286264): created new assignment group "Hardware Peripherals" (sys_id: f03cc30b930c4310e927f27cdd03d6d8), added 3 variables (Quantity mandatory, Reason for Request, Asset Tag), linked Requested For@100/Watch List@500 variable sets, created fulfillment stage with Manager approval (100) → Task (200) steps using Step based request fulfillment flow. |
| 2026-04-09T11:48:07Z | awa_queue, awa_assignment_rule, awa_group_queue_priority | Updated/Created | Configured Advanced Work Assignment for "Service Request" service channel (sc_req_item): named queue "Service Request Queue" (QUE00001) and linked to channel, enabled auto-assign by most_capacity on assignment rule "Assigment Category", linked "Hardware Peripherals" group as eligible queue handler (group_queue_priority sys_id: aced8bcb930c4310e927f27cdd03d64f); queue trigger must be created manually via AWA > Queue Triggers (REST restricted by platform BR). |
| 2026-04-14T16:12:45Z | sc_cat_item, item_option_new, io_set_item, sc_service_fulfillment_stage, sc_service_fulfillment_step | Created | Created "Submit Green Idea" catalog item (sys_id: 9a48d36093104710e927f27cdd03d6d9) under Sustainability category with 3 variables—Idea Type (dropdown: Product Feature/Process Improvement/Cost Savings/Environmental Initiative/Other) mandatory order 200, Idea Description (multiline text) mandatory order 300, Expected Impact (dropdown: High/Medium/Low/To Be Determined) optional order 400; linked Requested For@100 and Watch List@500 variable sets, configured Step based request fulfillment flow with Manager approval step (sys_id: af885f6093104710e927f27cdd03d652) order 100 for automatic manager routing. |
| 2026-04-14T16:18:32Z | sys_ui_policy | Created | Deployed 4 UI Policies for u_green_ideas table: (1) Make Expected Impact mandatory when Idea Type = 'Cost Savings'; (2) Show cost estimate hint on Description for Cost Savings; (3) Lock Idea Type as read-only after record creation; (4) Show hint if Idea Description < 50 characters — all policies active on-change and applied via REST API. |
| 2026-04-16T10:30:00Z | sys_dictionary | Created | Deployed 3 custom fields for Dynamic Round Robin assignment on akamaisddevup instance: sys_user_group.u_enable_round_robin (boolean, default false — sys_id: 936f6e992b50c750ed28f85ab891bfb0), sys_user.u_last_assigned_ticket (glide_date_time — sys_id: f36f665d2b94c710ef3ff275d891bff6), sys_user.u_on_shift (boolean — sys_id: 187fee5d2b94c710ef3ff275d891bf69). Flow definition saved locally; must be created manually in Flow Designer UI due to data pill binding limitations. |
| 2026-04-16T11:15:00Z | sys_hub_flow, sys_hub_trigger_instance, sys_hub_action_instance | Created | Created "Dynamic Round Robin Assignment" flow shell (sys_id: 2644fe552bd4c710ef3ff275d891bfce) on task table with trigger (sys_id: 724472d92b908f5008e5f23bc891bfd9) and 6 action stubs: Look Up Record (check u_enable_round_robin), If (group enabled), Look Up Records (find next agent by oldest u_last_assigned_ticket), If (member found), Update Record (assign task), Update Record (stamp timestamp). Data pill bindings must be wired manually in Flow Designer UI. |
