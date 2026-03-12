# skybox-mcp

MCP server wrapping the [Skybox by Vivid Seats](https://skybox.vividseats.com) REST API for use with Claude Code and Claude.ai connectors.

## What it does

Exposes 20 tools covering the core Skybox API surface:

| Category | Tools |
|----------|-------|
| Inventory | `get_inventory`, `get_inventory_by_id`, `update_inventory`, `update_inventory_price` |
| Invoices (sell side) | `get_invoices`, `get_invoice_by_id`, `update_invoice` |
| Purchases (buy side) | `get_purchases`, `get_purchase_by_id` |
| Events | `get_events`, `get_event_by_id` |
| Vendors / Customers | `get_vendors`, `get_customers` |
| Holds | `get_holds`, `get_hold_by_id` |
| Tags | `get_tags` |
| Webhooks | `get_webhooks`, `create_webhook`, `delete_webhook` |
| Reports | `get_purchased_inventory_report` |

## Setup

### 1. Install dependencies

```bash
pip install mcp httpx python-dotenv
pip install -e .
```

### 2. Configure credentials

Copy `.env.example` to `.env` and fill in your Skybox API credentials:

```bash
cp .env.example .env
```

```env
SKYBOX_APPLICATION_TOKEN=your_application_token
SKYBOX_API_TOKEN=your_api_token
SKYBOX_ACCOUNT_ID=your_account_id
SKYBOX_READ_ONLY=false
```

Get your tokens from Skybox → Settings → API.

### 3. Register with Claude Code

Add to your `.claude.json` under `mcpServers`:

```json
"skybox": {
  "type": "stdio",
  "command": "python",
  "args": ["-m", "skybox_mcp.server", "stdio"],
  "cwd": "/path/to/skybox-mcp",
  "env": {
    "SKYBOX_APPLICATION_TOKEN": "your_token",
    "SKYBOX_API_TOKEN": "your_token",
    "SKYBOX_ACCOUNT_ID": "your_account_id",
    "SKYBOX_READ_ONLY": "false"
  }
}
```

## Read-only mode

Set `SKYBOX_READ_ONLY=true` in `.env` to block all write operations (PUT, POST, DELETE). Useful for browsing/research sessions where you don't want Claude making changes.

```env
SKYBOX_READ_ONLY=true
```

Restart Claude Code after changing this value.

## Security

- Never commit `.env` — it is listed in `.gitignore`
- Rotate your API tokens in Skybox → Settings → API if they are ever exposed
- All write tools (`update_*`, `create_*`, `delete_*`) respect the `SKYBOX_READ_ONLY` flag
