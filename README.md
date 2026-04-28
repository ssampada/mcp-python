# ServiceNow MCP Server (Python)

A Python implementation of the Model Context Protocol (MCP) server for ServiceNow.

## Overview

This MCP server provides 400+ tools that allow AI models (Claude, GPT, etc.) to interact with ServiceNow instances via the standard Table API, Aggregate API, Attachment API, and more.

## Quick Start

```bash
pip install -e .
cp .env.example .env
# Edit .env with your ServiceNow credentials
python -m servicenow_mcp.server
```