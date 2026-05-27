import asyncio
import os
from datetime import date
from servicenow_mcp.servicenow.client import ServiceNowClient
from servicenow_mcp.servicenow.types import ServiceNowConfig, BasicAuthConfig, BearerTokenConfig, QueryRecordsParams
from dotenv import load_dotenv

load_dotenv()


async def main():
    auth_method = os.environ.get("SERVICENOW_AUTH_METHOD", "basic")
    basic = None
    bearer = None

    if auth_method == "basic":
        basic = BasicAuthConfig(
            username=os.environ.get("SERVICENOW_BASIC_USERNAME", ""),
            password=os.environ.get("SERVICENOW_BASIC_PASSWORD", ""),
        )
    elif auth_method == "bearer":
        bearer = BearerTokenConfig(token=os.environ.get("SERVICENOW_BEARER_TOKEN", ""))

    config = ServiceNowConfig(
        instance_url=os.environ["SERVICENOW_INSTANCE_URL"],
        auth_method=auth_method,
        basic=basic,
        bearer=bearer,
    )
    client = ServiceNowClient(config)

    today = date.today()
    month_start = today.replace(day=1)
    # Last day of month
    if today.month == 12:
        month_end = today.replace(day=31)
    else:
        month_end = today.replace(month=today.month + 1, day=1).replace(day=1)
        import calendar
        month_end = today.replace(day=calendar.monthrange(today.year, today.month)[1])

    query = (
        f"sys_created_on>={month_start} 00:00:00"
        f"^sys_created_on<={month_end} 23:59:59"
    )

    print(f"\nFetching incidents created from {month_start} to {month_end} ...\n")

    result = await client.query_records(QueryRecordsParams(
        table="incident",
        query=query,
        fields="number,short_description,state,priority,urgency,impact,caller_id,assigned_to,sys_created_on",
        limit=1000,
        order_by="-sys_created_on",
    ))

    await client.close()

    STATE_MAP = {"1": "New", "2": "In Progress", "3": "On Hold", "4": "Resolved", "5": "Closed", "6": "Cancelled"}
    PRIORITY_MAP = {"1": "Critical", "2": "High", "3": "Moderate", "4": "Low", "5": "Planning"}

    print(f"Total incidents this month: {result.count}\n")

    if result.count == 0:
        print("No incidents found.")
        return

    print(f"{'Number':<15} {'State':<14} {'Priority':<12} {'Created On':<22} {'Short Description':<45} {'Assigned To'}")
    print("-" * 130)

    for rec in result.records:
        number = rec.get("number", "")
        short_desc = rec.get("short_description", "")[:44]
        state_code = str(rec.get("state", ""))
        state = STATE_MAP.get(state_code, state_code)
        pri_code = str(rec.get("priority", ""))
        priority = PRIORITY_MAP.get(pri_code, pri_code)
        created = rec.get("sys_created_on", "")
        assigned = rec.get("assigned_to", {})
        if isinstance(assigned, dict):
            assigned = assigned.get("display_value", "")
        print(f"{number:<15} {state:<14} {priority:<12} {created:<22} {short_desc:<45} {assigned}")


asyncio.run(main())
