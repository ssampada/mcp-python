- When creating ServiceNow Catalog Items, always enforce the presence of: Name, Short Description, Category, Taxonomy, and Variables.
- Never create a Catalog Item without attaching the 'Requested For' and 'Watch List' variable sets.
- **Variable Set Ordering:**
  - 'Requested For' must always have **order 100** (first variable set displayed)
  - Item-specific variables must start from **order 200** (200, 300, 400, ...)
  - 'Watch List' must always be the **last** variable set — its order should be higher than all item variables
  - This ensures a consistent form layout: Requested For (100) → item variables (200+) → Watch List (last)
- **Mandatory fields:** Always ask the user which variables should be mandatory before setting `mandatory: true`. Do not assume mandatory status for any variable.
- **Taxonomy:** Every catalog item MUST have a `taxonomy_topic` field. Ask the user for the taxonomy topic if not provided. This maps to `sc_cat_item.taxonomy_topic` (reference to `sc_cat_item_taxonomy_topic`).
- If a user prompt is vague (e.g., "Make a laptop item"), respond by asking for the specific variables, category, and taxonomy first.
- When handling ServiceNow Business Rules, never assume the 'When' or 'Table' values. If a user says 'Create a BR to log a message', you must interrupt and ask: 'On which table, and should it run before, after, or async?'
- After every successful ServiceNow MCP tool execution, you must immediately update the README.md file in the root directory.Append a new entry under a '### Change Log' section.Include the Timestamp, the ServiceNow Table, the Action (Created/Updated), and a 1-sentence technical summary of the logic.
- Always create local files first then ask the user 'whether they can sync the file with ServiceNow Instance'. Do not directly create or update records in ServiceNow without first creating a local file and confirming with the user.
- Once the file is in sync with the instance, you must update the README.md and then ask the user whether the changes should be pushed to the Git repository.

## ServiceNow Flow Designer — REST API Limitations (confirmed on dev instances)

- The following Flow Designer components CAN be created/updated via Table REST API:
  - `sys_hub_flow` — flow shell (label, internal_name, description, run_as, access, active, status)
  - `sys_hub_trigger_instance` — trigger binding (trigger_type, trigger_definition, flow)
  - `sys_hub_action_instance` — action step records (action_type, flow, order, display_text)
  - `sc_cat_item.flow_designer_flow` — linking the flow to a catalog item

- The following CANNOT be set via REST API (read-only / server-compiled):
  - `action_inputs` on `sys_hub_action_instance` — data pill bindings are compiled by Flow Designer's internal engine and the field is always empty/ignored when written via REST
  - `sys_hub_step_ext_input` values — step input variable bindings cannot be set externally
  - Compiled snapshots — `compiled_snapshot` is server-managed

- As a result, **Flow Designer flows with data pill bindings (e.g., "Ask For Approval" with manager data pill) cannot be fully deployed via REST API alone**. The workaround options are:
  1. Deploy the flow shell + trigger + action instance stubs via REST, then complete data pill wiring manually in the Flow Designer UI
  2. Import a complete flow via Update Set XML

- **IMPORTANT: Never create a partial flow in ServiceNow.** If the full flow (including data pill bindings) cannot be deployed programmatically, do NOT deploy any partial shell, trigger, or action stubs. Instead:
  - Inform the user clearly that Flow Designer flows cannot be fully automated via REST API
  - Provide step-by-step instructions for the user to create the flow manually in the Flow Designer UI
  - Only create the local JSON definition file for documentation purposes

- When a user asks to deploy a Flow Designer flow with approval steps, always:
  1. Inform the user upfront that full deployment is not possible via REST
  2. Provide the local JSON definition for reference
  3. Give detailed manual instructions for Flow Designer UI
  4. Do NOT create any partial records in ServiceNow

## ServiceNow Approval Patterns

- **Recommended approach — Fulfillment Steps (fully deployable via REST):**
  - When a catalog item needs an approval process, follow these steps in order:
    1. **Link the "Step based request fulfillment" flow** to the catalog item:
       - PATCH `sc_cat_item/<sys_id>` with `flow_designer_flow: "21ea92dd53622010fca7ddeeff7b12b1"` (OOTB "Step based request fulfillment" flow)
    2. **Create a service fulfillment stage** linked to the catalog item:
       - POST `sc_service_fulfillment_stage` with `cat_item` (catalog item sys_id), `order` (e.g. 100)
       - A stage groups fulfillment steps; one stage per catalog item is typically sufficient
    3. **Create fulfillment step(s)** linked to the stage with the appropriate OOTB config:
       - POST `sc_service_fulfillment_step` with `service_fulfillment_stage` (stage sys_id), `service_fulfillment_step_configuration` (OOTB config sys_id), `order`
  - **This is the standard ServiceNow approach AND is fully automatable via REST API**
  - OOTB step configurations (sys_ids and ordering):
    - `2b7d9a7e87022010c84e4561d5cb0b21` — Custom approval (order: 100)
    - `38ee146053162010fca7ddeeff7b1221` — Manager approval (order: 200)
    - `dc0f364873122010ae42d31ee2f6a7f3` — Task (order: 300) — always last, after all approvals
    - When combining multiple steps, use increments of 100 (100, 200, 300...) to allow inserting steps later
    - Steps execute in ascending `order` — lower order runs first
    - Approvals should always come before Tasks in the order
  - OOTB flow:
    - `21ea92dd53622010fca7ddeeff7b12b1` — Step based request fulfillment (MUST be linked to `sc_cat_item.flow_designer_flow` before adding fulfillment steps)
  - When a user asks to add approvals to a catalog item, **use this approach by default**

- **Alternative — Business Rule approach (also fully deployable via REST):**
  - Business Rule on `sc_req_item` (after insert) that creates a `sysapproval_approver` record
  - Deploy using `scripts/deploy-approval.js`
  - Works but is non-standard; use only if fulfillment steps are not available

- **Flow Designer approach (NOT deployable via REST — manual only):**
  - Uses "Ask For Approval" action with manager data pill in Flow Designer
  - Only use if the user explicitly requests Flow Designer; provide manual UI steps

- For developer instances, always check if the instance is hibernating before attempting REST calls — HTML redirect response (HTTP 200 with `<html>` body) means the instance is asleep

## CRITICAL: Do NOT re-explore known API limitations

- **All Flow Designer components that involve data pill bindings, approvals, email recipients, or any dynamic field references CANNOT be deployed via REST API.** This includes:
  - Flow Designer flows (Ask For Approval, Send Email, etc.)
  - Fulfillment Steps (sc_cat_item_delivery_plan / sc_cat_item_delivery_task — approval tasks need data pill bindings)
  - Legacy Workflows (wf_workflow / wf_activity — approval activity `vars` field requires internal serialization)
- **When a user asks to create a flow, approval, or any artifact that requires data pill bindings: respond IMMEDIATELY with the manual UI instructions. Do NOT spend time exploring the REST API for workarounds — this has already been thoroughly investigated and confirmed impossible.**
- Save the local JSON definition file and provide step-by-step Flow Designer UI instructions. That's it. No API exploration needed.

## ServiceNow REST API — Key Table Mappings

| Artifact | Table | Deploy via REST? |
|---|---|---|
| Catalog Item | `sc_cat_item` | ✅ Yes |
| Catalog Item Variable | `item_option_new` | ✅ Yes |
| Variable Set link | `io_set_item` | ✅ Yes (with `order` field) |
| Business Rule | `sys_script` | ✅ Yes |
| Flow shell | `sys_hub_flow` | ✅ Partial |
| Flow trigger | `sys_hub_trigger_instance` | ✅ Yes (no table filter) |
| Flow action instance | `sys_hub_action_instance` | ✅ Partial (no data pills) |
| Flow action inputs (data pills) | `action_inputs` field | ❌ No (read-only) |
| Fulfillment Stage | `sc_service_fulfillment_stage` | ✅ Yes |
| Fulfillment Step | `sc_service_fulfillment_step` | ✅ Yes |
| Fulfillment Step Config (OOTB) | `sc_service_fulfillment_step_configuration` | ✅ Read (use OOTB sys_ids) |






