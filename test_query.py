import asyncio
import os
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

    tables = [
        ("cmdb_ci_server", "Parent - All Servers"),
        ("cmdb_ci_linux_server", "Linux Server"),
        ("cmdb_ci_win_server", "Windows Server"),
        ("cmdb_ci_netgear", "Network Device"),
        ("cmdb_ci_database", "Database"),
        ("cmdb_ci_appl", "Application"),
        ("cmdb_ci_aix_server", "AIX Server"),
        ("cmdb_ci_hpux_server", "HPUX Server"),
        ("cmdb_ci_solaris_server", "Solaris Server"),
    ]

    print(f"{'Table':<30} {'Description':<20} {'Count':<10}")
    print("-" * 65)

    total = 0
    for table, desc in tables:
        try:
            # Use stats API to get count
            import httpx
            url = f"{config.instance_url.rstrip('/')}/api/now/stats/{table}"
            headers = {"Accept": "application/json"}
            if auth_method == "bearer":
                headers["Authorization"] = f"Bearer {bearer.token}"
            async with httpx.AsyncClient(timeout=30) as http:
                resp = await http.get(url, headers=headers, params={"sysparm_count": "true"})
                if resp.status_code == 200:
                    data = resp.json()
                    count = data.get("result", {}).get("stats", {}).get("count", "N/A")
                    print(f"{table:<30} {desc:<20} {count:<10}")
                    try:
                        total += int(count)
                    except (ValueError, TypeError):
                        pass
                else:
                    # Fallback: query with limit=1 to check if table exists
                    resp2 = await client.query_records(
                        QueryRecordsParams(table=table, fields="sys_id", limit=1)
                    )
                    print(f"{table:<30} {desc:<20} {'exists (count unknown)':<10}")
        except Exception as e:
            print(f"{table:<30} {desc:<20} ERROR: {e}")

    print("-" * 65)
    print(f"{'TOTAL':<30} {'':<20} {total:<10}")

asyncio.run(main())
