#!/usr/bin/env python3
"""
Deploy / Verify / Revert — Submit Green Idea
Deploys: custom table u_green_ideas, catalog item, variables, variable sets, business rule.
Usage:
  python scripts/deploy-green-idea.py deploy
  python scripts/deploy-green-idea.py verify
  python scripts/deploy-green-idea.py revert
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

import httpx
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

INSTANCE_URL = os.environ["SERVICENOW_INSTANCE_URL"].rstrip("/")
BEARER_TOKEN  = os.environ.get("SERVICENOW_BEARER_TOKEN", "")
USERNAME      = os.environ.get("SERVICENOW_BASIC_USERNAME", "")
PASSWORD      = os.environ.get("SERVICENOW_BASIC_PASSWORD", "")
AUTH_METHOD   = os.environ.get("SERVICENOW_AUTH_METHOD", "bearer")

ARTIFACTS = Path(__file__).parent.parent / "src" / "artifacts"
STATE_FILE = Path(__file__).parent / ".green-idea-state.json"

# ── HTTP helpers ────────────────────────────────────────────────────────

def _headers() -> dict:
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if AUTH_METHOD == "bearer":
        headers["Authorization"] = f"Bearer {BEARER_TOKEN}"
    return headers

def _auth():
    if AUTH_METHOD == "basic":
        return (USERNAME, PASSWORD)
    return None

async def _post(client: httpx.AsyncClient, table: str, payload: dict) -> dict:
    url = f"{INSTANCE_URL}/api/now/table/{table}"
    resp = await client.post(url, json=payload, headers=_headers(), auth=_auth())
    _raise(resp, f"POST {table}")
    return resp.json()["result"]

async def _get_query(client: httpx.AsyncClient, table: str, query: str, fields: str = "sys_id,name") -> list[dict]:
    url = f"{INSTANCE_URL}/api/now/table/{table}"
    params = {"sysparm_query": query, "sysparm_fields": fields, "sysparm_limit": "5"}
    resp = await client.get(url, params=params, headers=_headers(), auth=_auth())
    _raise(resp, f"GET {table}")
    return resp.json().get("result", [])

async def _delete(client: httpx.AsyncClient, table: str, sys_id: str) -> None:
    url = f"{INSTANCE_URL}/api/now/table/{table}/{sys_id}"
    resp = await client.delete(url, headers=_headers(), auth=_auth())
    if resp.status_code not in (200, 204):
        print(f"  WARN: DELETE {table}/{sys_id} → {resp.status_code}: {resp.text[:200]}")

def _raise(resp: httpx.Response, ctx: str) -> None:
    if resp.status_code not in (200, 201):
        raise RuntimeError(f"{ctx} failed [{resp.status_code}]: {resp.text[:400]}")

def _save_state(state: dict) -> None:
    STATE_FILE.write_text(json.dumps(state, indent=2))
    print(f"  State saved → {STATE_FILE}")

def _load_state() -> dict:
    if not STATE_FILE.exists():
        sys.exit("No state file found. Run deploy first.")
    return json.loads(STATE_FILE.read_text())

# ── Variable type mapping ──────────────────────────────────────────────

VARIABLE_TYPE_MAP = {
    "single_line_text": "6",
    "multi_line_text": "2",
    "reference": "8",
    "select_box": "3",
    "checkbox": "7",
    "date": "9",
}

# ── Deploy ──────────────────────────────────────────────────────────────

async def deploy():
    print("=== DEPLOY: Submit Green Idea ===\n")
    state: dict = {"table_sys_id": None, "field_sys_ids": [], "cat_item_sys_id": None,
                   "variable_set_links": [], "variable_sys_ids": [], "br_sys_id": None,
                   "fulfillment_stage_sys_id": None, "fulfillment_step_sys_ids": [],
                   "ui_policy_sys_id": None, "ui_policy_action_sys_ids": []}

    async with httpx.AsyncClient(timeout=30) as client:

        # ── 1. Create custom table u_green_ideas ──────────────────────
        print("[1/5] Creating custom table u_green_ideas …")
        tdef = json.loads((ARTIFACTS / "table-u_green_ideas.json").read_text())

        # Check if table already exists
        existing = await _get_query(client, "sys_db_object", "name=u_green_ideas", "sys_id,name")
        if existing:
            state["table_sys_id"] = existing[0]["sys_id"]
            print(f"  Table already exists: {state['table_sys_id']}")
        else:
            result = await _post(client, "sys_db_object", tdef["table"]["payload"])
            state["table_sys_id"] = result["sys_id"]
            print(f"  Table created: {state['table_sys_id']}")

        # ── 2. Create dictionary fields ───────────────────────────────
        print("[2/5] Creating dictionary fields …")
        for field in tdef["fields"]:
            element = field["payload"]["element"]
            existing_f = await _get_query(client, "sys_dictionary",
                                          f"name=u_green_ideas^element={element}", "sys_id,element")
            if existing_f:
                print(f"  Field '{element}' already exists — skipping")
                state["field_sys_ids"].append({"element": element, "sys_id": existing_f[0]["sys_id"], "pre_existing": True})
            else:
                r = await _post(client, "sys_dictionary", field["payload"])
                state["field_sys_ids"].append({"element": element, "sys_id": r["sys_id"], "pre_existing": False})
                print(f"  Field '{element}' created: {r['sys_id']}")

        # ── 3. Create catalog item ─────────────────────────────────────
        print("[3/5] Creating catalog item 'Submit Green Idea' …")
        cdef = json.loads((ARTIFACTS / "catalog-submit-green-idea.json").read_text())

        existing_ci = await _get_query(client, "sc_cat_item", "name=Submit Green Idea", "sys_id,name")
        if existing_ci:
            state["cat_item_sys_id"] = existing_ci[0]["sys_id"]
            print(f"  Catalog item already exists: {state['cat_item_sys_id']}")
        else:
            r = await _post(client, "sc_cat_item", cdef["catalog_item"]["payload"])
            state["cat_item_sys_id"] = r["sys_id"]
            print(f"  Catalog item created: {state['cat_item_sys_id']}")

        cat_item_sys_id = state["cat_item_sys_id"]

        # ── 4. Attach variable sets (Requested For + Watch List) ───────
        print("[4/5] Attaching variable sets …")
        for vs in cdef["variable_sets"]:
            vs_name = vs["lookup_name"]
            vs_records = await _get_query(client, "item_option_new_set", f"title={vs_name}", "sys_id,title")
            if not vs_records:
                print(f"  WARN: Variable set '{vs_name}' not found on this instance — skipping")
                continue
            vs_sys_id = vs_records[0]["sys_id"]

            # Check if already linked
            link_existing = await _get_query(client, "io_set_item",
                                             f"sc_cat_item={cat_item_sys_id}^variable_set={vs_sys_id}", "sys_id")
            if link_existing:
                print(f"  Variable set '{vs_name}' already linked — skipping")
                state["variable_set_links"].append({"name": vs_name, "sys_id": link_existing[0]["sys_id"], "pre_existing": True})
            else:
                r = await _post(client, "io_set_item", {
                    "sc_cat_item": cat_item_sys_id,
                    "variable_set": vs_sys_id,
                    "order": vs["payload"]["order"]
                })
                state["variable_set_links"].append({"name": vs_name, "sys_id": r["sys_id"], "pre_existing": False})
                print(f"  Variable set '{vs_name}' linked: {r['sys_id']}")

        # ── 5. Create catalog item variables ───────────────────────────
        print("[5/5] Creating catalog item variables …")
        for var in cdef["variables"]:
            vname = var["payload"]["name"]
            existing_v = await _get_query(client, "item_option_new",
                                          f"cat_item={cat_item_sys_id}^name={vname}", "sys_id,name")
            if existing_v:
                print(f"  Variable '{vname}' already exists — skipping")
                state["variable_sys_ids"].append({"name": vname, "sys_id": existing_v[0]["sys_id"], "pre_existing": True})
            else:
                payload = dict(var["payload"])
                payload["cat_item"] = cat_item_sys_id
                # Map friendly type to ServiceNow type integer
                friendly_type = payload.pop("type", "single_line_text")
                payload["type"] = VARIABLE_TYPE_MAP.get(friendly_type, "6")
                payload.pop("lookup_table", None)
                payload.pop("lookup_value", None)
                r = await _post(client, "item_option_new", payload)
                state["variable_sys_ids"].append({"name": vname, "sys_id": r["sys_id"], "pre_existing": False})
                print(f"  Variable '{vname}' created: {r['sys_id']}")

        # ── 6. Link OOTB flow + create fulfillment stage & steps (manager approval) ──
        print("[6/8] Linking step-based fulfillment flow to catalog item …")
        fdef = json.loads((ARTIFACTS / "fulfillment-green-idea.json").read_text())
        flow_id = cdef["catalog_item"]["payload"]["flow_designer_flow"]
        url = f"{INSTANCE_URL}/api/now/table/sc_cat_item/{cat_item_sys_id}"
        patch_resp = await client.patch(url, json={"flow_designer_flow": flow_id},
                                        headers=_headers(), auth=_auth())
        if patch_resp.status_code == 200:
            print(f"  Flow linked: {flow_id}")
        else:
            print(f"  WARN: Flow link failed [{patch_resp.status_code}]: {patch_resp.text[:200]}")

        print("[7/8] Creating fulfillment stage …")
        existing_stage = await _get_query(client, "sc_service_fulfillment_stage",
                                          f"cat_item={cat_item_sys_id}", "sys_id")
        if existing_stage:
            state["fulfillment_stage_sys_id"] = existing_stage[0]["sys_id"]
            print(f"  Stage already exists: {state['fulfillment_stage_sys_id']}")
        else:
            stage_payload = dict(fdef["stage"]["payload"])
            stage_payload["cat_item"] = cat_item_sys_id
            r = await _post(client, "sc_service_fulfillment_stage", stage_payload)
            state["fulfillment_stage_sys_id"] = r["sys_id"]
            print(f"  Stage created: {state['fulfillment_stage_sys_id']}")

        stage_sys_id = state["fulfillment_stage_sys_id"]

        print("[8/8] Creating fulfillment steps (manager approval + task) …")
        for step in fdef["steps"]:
            cfg_id = step["payload"]["service_fulfillment_step_configuration"]
            existing_step = await _get_query(client, "sc_service_fulfillment_step",
                                             f"service_fulfillment_stage={stage_sys_id}^service_fulfillment_step_configuration={cfg_id}",
                                             "sys_id")
            if existing_step:
                print(f"  Step (cfg {cfg_id}) already exists — skipping")
                state["fulfillment_step_sys_ids"].append({"sys_id": existing_step[0]["sys_id"], "pre_existing": True})
            else:
                step_payload = dict(step["payload"])
                step_payload["service_fulfillment_stage"] = stage_sys_id
                r = await _post(client, "sc_service_fulfillment_step", step_payload)
                state["fulfillment_step_sys_ids"].append({"sys_id": r["sys_id"], "pre_existing": False})
                label = "Manager Approval" if step["payload"]["order"] == 100 else "Task"
                print(f"  Step '{label}' created: {r['sys_id']}")

        # ── 9. Create UI policy + actions ─────────────────────────────
        print("[9/10] Creating catalog UI policy …")
        updef = json.loads((ARTIFACTS / "ui-policy-green-idea.json").read_text())
        up_payload = dict(updef["ui_policy"]["payload"])
        up_payload["catalog_item"] = cat_item_sys_id

        existing_up = await _get_query(client, "catalog_ui_policy",
                                       f"catalog_item={cat_item_sys_id}^short_description={up_payload['short_description']}",
                                       "sys_id")
        if existing_up:
            state["ui_policy_sys_id"] = existing_up[0]["sys_id"]
            print(f"  UI policy already exists: {state['ui_policy_sys_id']}")
        else:
            r = await _post(client, "catalog_ui_policy", up_payload)
            state["ui_policy_sys_id"] = r["sys_id"]
            print(f"  UI policy created: {state['ui_policy_sys_id']}")

        ui_policy_sys_id = state["ui_policy_sys_id"]

        print("[10/10] Creating UI policy actions …")
        # Resolve estimated_savings variable sys_id from state
        es_var = next((v for v in state["variable_sys_ids"] if v["name"] == "estimated_savings"), None)
        if not es_var:
            print("  WARN: estimated_savings variable not in state — skipping actions")
        else:
            for action in updef["actions"]:
                action_payload = dict(action["payload"])
                action_payload["ui_policy"] = ui_policy_sys_id
                action_payload["catalog_variable"] = es_var["sys_id"]
                existing_act = await _get_query(client, "catalog_ui_policy_action",
                                               f"ui_policy={ui_policy_sys_id}^catalog_variable={es_var['sys_id']}",
                                               "sys_id")
                if existing_act:
                    print(f"  UI policy action already exists — skipping")
                    state["ui_policy_action_sys_ids"].append({"sys_id": existing_act[0]["sys_id"], "pre_existing": True})
                else:
                    r = await _post(client, "catalog_ui_policy_action", action_payload)
                    state["ui_policy_action_sys_ids"].append({"sys_id": r["sys_id"], "pre_existing": False})
                    print(f"  UI policy action created: {r['sys_id']} (estimated_savings → mandatory)")

        # ── 10. Create business rule ───────────────────────────────────
        print("[11/11] Creating business rule …")
        brdef = json.loads((ARTIFACTS / "br-green-idea-submission.json").read_text())
        br_payload = dict(brdef["business_rule"]["payload"])
        # Inject the real cat_item sys_id into the filter condition
        br_payload["filter_condition"] = f"cat_item={cat_item_sys_id}"

        existing_br = await _get_query(client, "sys_script",
                                       "name=Create Green Idea Record on Submission", "sys_id,name")
        if existing_br:
            state["br_sys_id"] = existing_br[0]["sys_id"]
            print(f"  Business rule already exists: {state['br_sys_id']}")
        else:
            r = await _post(client, "sys_script", br_payload)
            state["br_sys_id"] = r["sys_id"]
            print(f"  Business rule created: {state['br_sys_id']}")

    _save_state(state)
    print("\nDeploy complete.")


# ── Verify ──────────────────────────────────────────────────────────────

async def verify():
    print("=== VERIFY: Submit Green Idea ===\n")
    state = _load_state()
    all_ok = True

    async with httpx.AsyncClient(timeout=30) as client:
        checks = [
            ("sys_db_object",              state.get("table_sys_id"),            "Custom table u_green_ideas"),
            ("sc_cat_item",                state.get("cat_item_sys_id"),          "Catalog item Submit Green Idea"),
            ("sys_script",                 state.get("br_sys_id"),               "Business rule"),
            ("sc_service_fulfillment_stage", state.get("fulfillment_stage_sys_id"), "Fulfillment stage"),
            ("catalog_ui_policy",          state.get("ui_policy_sys_id"),        "UI policy"),
        ]
        for table, sys_id, label in checks:
            if not sys_id:
                print(f"  SKIP  {label} (no sys_id in state)")
                continue
            resp = await client.get(f"{INSTANCE_URL}/api/now/table/{table}/{sys_id}",
                                    headers=_headers(), auth=_auth())
            if resp.status_code == 200:
                print(f"  OK    {label} [{sys_id}]")
            else:
                print(f"  FAIL  {label} [{sys_id}] → {resp.status_code}")
                all_ok = False

        for v in state.get("variable_sys_ids", []):
            resp = await client.get(f"{INSTANCE_URL}/api/now/table/item_option_new/{v['sys_id']}",
                                    headers=_headers(), auth=_auth())
            if resp.status_code == 200:
                print(f"  OK    Variable '{v['name']}' [{v['sys_id']}]")
            else:
                print(f"  FAIL  Variable '{v['name']}' [{v['sys_id']}] → {resp.status_code}")
                all_ok = False

        for i, s in enumerate(state.get("fulfillment_step_sys_ids", [])):
            resp = await client.get(f"{INSTANCE_URL}/api/now/table/sc_service_fulfillment_step/{s['sys_id']}",
                                    headers=_headers(), auth=_auth())
            label = "Manager Approval" if i == 0 else "Task"
            if resp.status_code == 200:
                print(f"  OK    Fulfillment step '{label}' [{s['sys_id']}]")
            else:
                print(f"  FAIL  Fulfillment step '{label}' [{s['sys_id']}] → {resp.status_code}")
                all_ok = False

        for a in state.get("ui_policy_action_sys_ids", []):
            resp = await client.get(f"{INSTANCE_URL}/api/now/table/catalog_ui_policy_action/{a['sys_id']}",
                                    headers=_headers(), auth=_auth())
            if resp.status_code == 200:
                print(f"  OK    UI policy action [{a['sys_id']}]")
            else:
                print(f"  FAIL  UI policy action [{a['sys_id']}] → {resp.status_code}")
                all_ok = False

    print(f"\nVerify {'PASSED' if all_ok else 'FAILED'}.")


# ── Revert ──────────────────────────────────────────────────────────────

async def revert():
    print("=== REVERT: Submit Green Idea ===\n")
    state = _load_state()

    async with httpx.AsyncClient(timeout=30) as client:

        # UI policy actions (delete before policy)
        for a in state.get("ui_policy_action_sys_ids", []):
            if not a.get("pre_existing"):
                print(f"Deleting UI policy action {a['sys_id']} …")
                await _delete(client, "catalog_ui_policy_action", a["sys_id"])

        # UI policy
        if up := state.get("ui_policy_sys_id"):
            print(f"Deleting UI policy {up} …")
            await _delete(client, "catalog_ui_policy", up)

        # Fulfillment steps (delete steps before stage)
        for s in state.get("fulfillment_step_sys_ids", []):
            if not s.get("pre_existing"):
                print(f"Deleting fulfillment step {s['sys_id']} …")
                await _delete(client, "sc_service_fulfillment_step", s["sys_id"])

        # Fulfillment stage
        if stage := state.get("fulfillment_stage_sys_id"):
            print(f"Deleting fulfillment stage {stage} …")
            await _delete(client, "sc_service_fulfillment_stage", stage)

        # Business rule
        if br := state.get("br_sys_id"):
            print(f"Deleting business rule {br} …")
            await _delete(client, "sys_script", br)

        # Variable set links (io_set_item)
        for vs in state.get("variable_set_links", []):
            if not vs.get("pre_existing"):
                print(f"Deleting variable set link '{vs['name']}' {vs['sys_id']} …")
                await _delete(client, "io_set_item", vs["sys_id"])

        # Variables
        for v in state.get("variable_sys_ids", []):
            if not v.get("pre_existing"):
                print(f"Deleting variable '{v['name']}' {v['sys_id']} …")
                await _delete(client, "item_option_new", v["sys_id"])

        # Catalog item
        if ci := state.get("cat_item_sys_id"):
            print(f"Deleting catalog item {ci} …")
            await _delete(client, "sc_cat_item", ci)

        # Dictionary fields (only ones we created)
        for f in state.get("field_sys_ids", []):
            if not f.get("pre_existing"):
                print(f"Deleting dictionary field '{f['element']}' {f['sys_id']} …")
                await _delete(client, "sys_dictionary", f["sys_id"])

        # Table (only if we created it)
        if tbl := state.get("table_sys_id"):
            print(f"Deleting table u_green_ideas {tbl} …")
            await _delete(client, "sys_db_object", tbl)

    STATE_FILE.unlink(missing_ok=True)
    print("\nRevert complete. State file removed.")


# ── Entry point ─────────────────────────────────────────────────────────

if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "deploy"
    if cmd == "deploy":
        asyncio.run(deploy())
    elif cmd == "verify":
        asyncio.run(verify())
    elif cmd == "revert":
        asyncio.run(revert())
    else:
        sys.exit(f"Unknown command: {cmd}. Use deploy | verify | revert")
