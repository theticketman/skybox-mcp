"""
Skybox (Vivid Seats) MCP Server
Wraps the Skybox REST API as MCP tools for use with Claude Code / Cowork.

Auth is baked in via environment variables (with defaults for account 4767).
Override by setting:
  SKYBOX_APPLICATION_TOKEN
  SKYBOX_API_TOKEN
  SKYBOX_ACCOUNT_ID
"""

import os
from typing import Optional
from datetime import date, timedelta, datetime
import httpx
from mcp.server.fastmcp import FastMCP
from dotenv import load_dotenv

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), '..', '.env'))

mcp = FastMCP("skybox")
BASE_URL = "https://skybox.vividseats.com/services"

# Chunking config
DATE_CHUNK_DAYS   = 30    # split date ranges wider than this into windows
MAX_ROWS_PER_CALL = 100   # page size for paginated fetches
MAX_TOTAL_ROWS    = 5000  # safety cap - stop fetching after this many rows


def _headers() -> dict:
    app_token = os.environ.get("SKYBOX_APPLICATION_TOKEN")
    api_token = os.environ.get("SKYBOX_API_TOKEN")
    account   = os.environ.get("SKYBOX_ACCOUNT_ID")
    if not all([app_token, api_token, account]):
        raise ValueError(
            "Missing Skybox credentials. "
            "Set SKYBOX_APPLICATION_TOKEN, SKYBOX_API_TOKEN, and SKYBOX_ACCOUNT_ID "
            "in your .env file or environment."
        )
    return {
        "X-Application-Token": app_token,
        "X-Api-Token":         api_token,
        "X-Account":           account,
        "Accept":              "application/json",
        "Content-Type":        "application/json",
    }

async def _get(path: str, params: dict = None) -> dict:
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.get(f"{BASE_URL}{path}", headers=_headers(), params=params)
        r.raise_for_status()
        return r.json()

def _check_read_only(method: str) -> None:
    if os.environ.get("SKYBOX_READ_ONLY", "").lower() == "true":
        raise PermissionError(
            f"Skybox MCP is in READ-ONLY mode. "
            f"{method.upper()} calls are disabled. "
            f"Set SKYBOX_READ_ONLY=false in your .env to enable writes."
        )

async def _post(path: str, body: dict) -> dict:
    _check_read_only("POST")
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.post(f"{BASE_URL}{path}", headers=_headers(), json=body)
        r.raise_for_status()
        return r.json()

async def _put(path: str, body: dict) -> dict:
    _check_read_only("PUT")
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.put(f"{BASE_URL}{path}", headers=_headers(), json=body)
        r.raise_for_status()
        return r.json()

async def _delete(path: str) -> dict:
    _check_read_only("DELETE")
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.delete(f"{BASE_URL}{path}", headers=_headers())
        r.raise_for_status()
        try:
            return r.json()
        except Exception:
            return {"status": "deleted", "statusCode": r.status_code}


# ---------------------------------------------------------------------------
# Chunking helpers
# ---------------------------------------------------------------------------

def _parse_date(s: str) -> date:
    """Parse YYYY-MM-DD string to date object."""
    return datetime.strptime(s, "%Y-%m-%d").date()

def _date_chunks(from_str: str, to_str: str, chunk_days: int = DATE_CHUNK_DAYS):
    """
    Yield (chunk_from, chunk_to) string pairs splitting a date range into
    windows of at most chunk_days days. Returns a single window if the range
    is already within the limit.
    """
    start = _parse_date(from_str)
    end   = _parse_date(to_str)
    if (end - start).days <= chunk_days:
        yield from_str, to_str
        return
    cursor = start
    while cursor <= end:
        chunk_end = min(cursor + timedelta(days=chunk_days - 1), end)
        yield cursor.strftime("%Y-%m-%d"), chunk_end.strftime("%Y-%m-%d")
        cursor = chunk_end + timedelta(days=1)

async def _get_all_pages(path: str, params: dict) -> dict:
    """
    Auto-paginate a Skybox endpoint that returns {rows, rowCount, totals}.
    Fetches pages sequentially until all rows are retrieved or MAX_TOTAL_ROWS
    is reached. Returns a merged result with all rows and the original totals.
    """
    page_params = {**params, "pageSize": MAX_ROWS_PER_CALL, "pageNumber": 0}
    first = await _get(path, page_params)

    all_rows  = list(first.get("rows", []))
    row_count = first.get("rowCount", len(all_rows))
    totals    = first.get("totals", {})
    extra     = {k: v for k, v in first.items() if k not in ("rows", "rowCount", "totals")}

    page = 1
    while len(all_rows) < row_count and len(all_rows) < MAX_TOTAL_ROWS:
        page_params = {**params, "pageSize": MAX_ROWS_PER_CALL, "pageNumber": page}
        data = await _get(path, page_params)
        batch = data.get("rows", [])
        if not batch:
            break
        all_rows.extend(batch)
        page += 1

    truncated = len(all_rows) >= MAX_TOTAL_ROWS and len(all_rows) < row_count
    result = {**extra, "rows": all_rows, "rowCount": row_count, "totals": totals,
              "fetchedRows": len(all_rows)}
    if truncated:
        result["_warning"] = (
            f"Result truncated at {MAX_TOTAL_ROWS} rows (total available: {row_count}). "
            "Narrow your date range or add more filters to get all records."
        )
    return result

async def _get_chunked(
    path: str,
    params: dict,
    from_key: str,
    to_key: str,
    from_val: Optional[str],
    to_val: Optional[str],
) -> dict:
    """
    Fetch a date-filtered endpoint with automatic date-range chunking +
    full pagination within each chunk. Merges all rows across chunks.

    If no date range is provided, falls back to a single paginated fetch.
    """
    # No date range - just paginate
    if not from_val and not to_val:
        return await _get_all_pages(path, params)

    # Single date with no end - use same date for both
    if from_val and not to_val:
        to_val = from_val

    # Check if chunking is needed
    if from_val and to_val:
        span = (_parse_date(to_val) - _parse_date(from_val)).days
    else:
        span = 0

    if span <= DATE_CHUNK_DAYS:
        return await _get_all_pages(path, params)

    # Chunk the date range and merge results
    all_rows   = []
    total_rows = 0
    merged_totals = {}
    first_extra = {}

    for chunk_from, chunk_to in _date_chunks(from_val, to_val):
        if len(all_rows) >= MAX_TOTAL_ROWS:
            break
        chunk_params = {**params, from_key: chunk_from, to_key: chunk_to}
        data = await _get_all_pages(path, chunk_params)
        all_rows.extend(data.get("rows", []))
        total_rows += data.get("rowCount", 0)
        # Merge numeric totals
        for k, v in data.get("totals", {}).items():
            if isinstance(v, (int, float)):
                merged_totals[k] = merged_totals.get(k, 0) + v
            else:
                merged_totals[k] = v
        if not first_extra:
            first_extra = {k: v for k, v in data.items()
                           if k not in ("rows", "rowCount", "totals", "fetchedRows", "_warning")}

    truncated = len(all_rows) >= MAX_TOTAL_ROWS and len(all_rows) < total_rows
    result = {**first_extra, "rows": all_rows, "rowCount": total_rows,
              "totals": merged_totals, "fetchedRows": len(all_rows)}
    if truncated:
        result["_warning"] = (
            f"Result truncated at {MAX_TOTAL_ROWS} rows (total available: {total_rows}). "
            "Narrow your date range or add more filters to get all records."
        )
    return result


# ── INVENTORY ────────────────────────────────────────────────────────────────

@mcp.tool()
async def get_inventory(
    keywords: Optional[str] = None,
    event_id: Optional[int] = None,
    section: Optional[str] = None,
    status: Optional[str] = None,
    broadcast: Optional[bool] = None,
    page_number: int = 0,
    page_size: int = 50,
) -> dict:
    """
    Search/list inventory (ticket listings) in Skybox.
    Args:
        keywords:    Free-text search (event name, performer, venue)
        event_id:    Filter by Skybox event ID
        section:     Filter by section
        status:      AVAILABLE, SOLD, PENDING
        broadcast:   True = broadcast only; False = unbroadcast only
        page_number: Zero-based page number (ignored when auto-paginating)
        page_size:   Results per page (max 100; auto-pagination fetches all)
    """
    params = {"pageNumber": page_number, "pageSize": page_size}
    if keywords:          params["keywords"]  = keywords
    if event_id:          params["eventId"]   = event_id
    if section:           params["section"]   = section
    if status:            params["status"]    = status
    if broadcast is not None: params["broadcast"] = str(broadcast).lower()
    return await _get_all_pages("/inventory", params)

@mcp.tool()
async def get_inventory_by_id(inventory_id: int) -> dict:
    """Get full details for a single inventory listing by its Skybox ID."""
    return await _get(f"/inventory/{inventory_id}")

@mcp.tool()
async def update_inventory_price(inventory_id: int, unit_price: float) -> dict:
    """
    Update the list price of an existing inventory listing.
    Args:
        inventory_id: Skybox inventory ID
        unit_price:   New price per ticket (USD)
    """
    return await _put(f"/inventory/{inventory_id}", {"unitPrice": unit_price})

@mcp.tool()
async def update_inventory(
    inventory_id: int,
    unit_price: Optional[float] = None,
    quantity: Optional[int] = None,
    in_hand_date: Optional[str] = None,
    broadcast: Optional[bool] = None,
    public_notes: Optional[str] = None,
    internal_notes: Optional[str] = None,
    tags: Optional[str] = None,
    hide_seat_numbers: Optional[bool] = None,
    shown_quantity: Optional[int] = None,
) -> dict:
    """
    Update one or more fields on an inventory listing.
    Args:
        inventory_id:      Skybox inventory ID
        unit_price:        New price per ticket
        quantity:          New quantity
        in_hand_date:      Date tickets in hand (YYYY-MM-DD)
        broadcast:         Whether listing is broadcast to marketplaces
        public_notes:      Buyer-visible notes
        internal_notes:    Internal-only notes
        tags:              Comma-separated tags
        hide_seat_numbers: Hide seat numbers on marketplaces
        shown_quantity:    Override shown quantity
    """
    body = {}
    if unit_price        is not None: body["unitPrice"]       = unit_price
    if quantity          is not None: body["quantity"]        = quantity
    if in_hand_date      is not None: body["inHandDate"]      = in_hand_date
    if broadcast         is not None: body["broadcast"]       = broadcast
    if public_notes      is not None: body["publicNotes"]     = public_notes
    if internal_notes    is not None: body["internalNotes"]   = internal_notes
    if tags              is not None: body["tags"]            = tags
    if hide_seat_numbers is not None: body["hideSeatNumbers"] = hide_seat_numbers
    if shown_quantity    is not None: body["shownQuantity"]   = shown_quantity
    return await _put(f"/inventory/{inventory_id}", body)


# ── INVOICES (Sell Side) ──────────────────────────────────────────────────────

@mcp.tool()
async def get_invoices(
    event_id: Optional[int] = None,
    fulfillment_status: Optional[str] = None,
    payment_status: Optional[str] = None,
    created_date_from: Optional[str] = None,
    created_date_to: Optional[str] = None,
    event_date_from: Optional[str] = None,
    event_date_to: Optional[str] = None,
) -> dict:
    """
    List sales invoices. At least one filter required by the Skybox API.
    Auto-paginates all results. Date ranges >30 days are chunked automatically.
    For aggregate revenue totals, use get_quick_report_sales instead.
    Args:
        event_id:           Skybox event ID
        fulfillment_status: FULFILLED or UNFULFILLED
        payment_status:     PAID or UNPAID
        created_date_from:  Invoice created date start (YYYY-MM-DD)
        created_date_to:    Invoice created date end (YYYY-MM-DD)
        event_date_from:    Event date range start (YYYY-MM-DD)
        event_date_to:      Event date range end (YYYY-MM-DD)
    """
    params = {}
    if event_id:           params["eventId"]           = event_id
    if fulfillment_status: params["fulfillmentStatus"] = fulfillment_status
    if payment_status:     params["paymentStatus"]     = payment_status
    if created_date_from:  params["createdDateFrom"]   = created_date_from
    if created_date_to:    params["createdDateTo"]     = created_date_to
    if event_date_from:    params["eventDateFrom"]     = event_date_from
    if event_date_to:      params["eventDateTo"]       = event_date_to
    # Prefer chunking on createdDate; fall back to eventDate
    if created_date_from or created_date_to:
        return await _get_chunked("/invoices", params,
                                  "createdDateFrom", "createdDateTo",
                                  created_date_from, created_date_to)
    return await _get_chunked("/invoices", params,
                              "eventDateFrom", "eventDateTo",
                              event_date_from, event_date_to)

@mcp.tool()
async def get_invoice_by_id(invoice_id: int) -> dict:
    """Get full details for a single invoice by its Skybox ID."""
    return await _get(f"/invoices/{invoice_id}")

@mcp.tool()
async def update_invoice(
    invoice_id: int,
    fulfillment_status: Optional[str] = None,
    payment_status: Optional[str] = None,
    internal_notes: Optional[str] = None,
    tags: Optional[str] = None,
) -> dict:
    """Update fields on a sales invoice."""
    body = {}
    if fulfillment_status: body["fulfillmentStatus"] = fulfillment_status
    if payment_status:     body["paymentStatus"]     = payment_status
    if internal_notes:     body["internalNotes"]     = internal_notes
    if tags:               body["tags"]              = tags
    return await _put(f"/invoices/{invoice_id}", body)


# ── PURCHASES (Buy Side) ──────────────────────────────────────────────────────

@mcp.tool()
async def get_purchases(
    event_id: Optional[int] = None,
    payment_status: Optional[str] = None,
    vendor_id: Optional[int] = None,
    created_date_from: Optional[str] = None,
    created_date_to: Optional[str] = None,
    event_name: Optional[str] = None,
) -> dict:
    """
    List purchase orders. At least one filter required by the Skybox API.
    Auto-paginates all results. Date ranges >30 days are chunked automatically.
    For aggregate purchase totals, use get_quick_report_purchases instead.
    Args:
        event_id:          Skybox event ID
        payment_status:    PAID or UNPAID
        vendor_id:         Filter by vendor/supplier ID
        created_date_from: Purchase created date start (YYYY-MM-DD)
        created_date_to:   Purchase created date end (YYYY-MM-DD)
        event_name:        Filter by event name (partial match)
    """
    params = {}
    if event_id:          params["eventId"]         = event_id
    if payment_status:    params["paymentStatus"]   = payment_status
    if vendor_id:         params["vendorId"]        = vendor_id
    if created_date_from: params["createdDateFrom"] = created_date_from
    if created_date_to:   params["createdDateTo"]   = created_date_to
    if event_name:        params["eventName"]       = event_name
    return await _get_chunked("/purchases", params,
                              "createdDateFrom", "createdDateTo",
                              created_date_from, created_date_to)

@mcp.tool()
async def get_purchase_by_id(purchase_id: int) -> dict:
    """Get full details for a single purchase order by its Skybox ID."""
    return await _get(f"/purchases/{purchase_id}")


# ── EVENTS ────────────────────────────────────────────────────────────────────

@mcp.tool()
async def get_events(
    keywords: str,
    performer: Optional[str] = None,
    venue: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    page_number: int = 0,
    page_size: int = 50,
) -> dict:
    """
    Search for events in Skybox. keywords is required.
    Args:
        keywords:    Performer, venue, or event name (required)
        performer:   Filter by performer name
        venue:       Filter by venue name
        date_from:   Start of date range (YYYY-MM-DD)
        date_to:     End of date range (YYYY-MM-DD)
        page_number: Zero-based page
        page_size:   Results per page
    """
    params = {"pageNumber": page_number, "pageSize": page_size, "keywords": keywords}
    if performer: params["performer"] = performer
    if venue:     params["venue"]     = venue
    if date_from: params["dateFrom"]  = date_from
    if date_to:   params["dateTo"]    = date_to
    return await _get("/events", params)

@mcp.tool()
async def get_event_by_id(event_id: int) -> dict:
    """Get full details for a single event by its Skybox event ID."""
    return await _get(f"/events/{event_id}")

# ── SOLD / PURCHASED INVENTORY ────────────────────────────────────────────────

@mcp.tool()
async def get_sold_inventory(
    keywords: Optional[str] = None,
    event_id: Optional[int] = None,
    section: Optional[str] = None,
    invoice_date_from: Optional[str] = None,
    invoice_date_to: Optional[str] = None,
    event_date_from: Optional[str] = None,
    event_date_to: Optional[str] = None,
) -> dict:
    """
    List sold inventory with line-item detail. At least one filter required.
    Auto-paginates all results. Date ranges >30 days are chunked automatically.
    For summary totals, use get_quick_report_sales instead.
    Args:
        keywords:          Free-text search
        event_id:          Filter by Skybox event ID
        section:           Filter by section
        invoice_date_from: Invoice date range start (YYYY-MM-DD)
        invoice_date_to:   Invoice date range end (YYYY-MM-DD)
        event_date_from:   Event date range start (YYYY-MM-DD)
        event_date_to:     Event date range end (YYYY-MM-DD)
    """
    params = {}
    if keywords:          params["eventKeywords"]   = keywords
    if event_id:          params["eventId"]         = event_id
    if section:           params["section"]         = section
    if invoice_date_from: params["invoiceDateFrom"] = invoice_date_from
    if invoice_date_to:   params["invoiceDateTo"]   = invoice_date_to
    if event_date_from:   params["eventDateFrom"]   = event_date_from
    if event_date_to:     params["eventDateTo"]     = event_date_to
    if invoice_date_from or invoice_date_to:
        return await _get_chunked("/inventory/sold", params,
                                  "invoiceDateFrom", "invoiceDateTo",
                                  invoice_date_from, invoice_date_to)
    return await _get_chunked("/inventory/sold", params,
                              "eventDateFrom", "eventDateTo",
                              event_date_from, event_date_to)


@mcp.tool()
async def get_purchased_inventory(
    keywords: Optional[str] = None,
    event_id: Optional[int] = None,
    vendor_id: Optional[int] = None,
    purchase_date_from: Optional[str] = None,
    purchase_date_to: Optional[str] = None,
    event_date_from: Optional[str] = None,
    event_date_to: Optional[str] = None,
    payment_status: Optional[str] = None,
) -> dict:
    """
    List purchased inventory with line-item detail. At least one filter required.
    Auto-paginates all results. Date ranges >30 days are chunked automatically.
    For summary totals, use get_quick_report_purchases instead.
    Args:
        keywords:           Free-text search (event name)
        event_id:           Filter by Skybox event ID
        vendor_id:          Filter by vendor ID
        purchase_date_from: Purchase date range start (YYYY-MM-DD)
        purchase_date_to:   Purchase date range end (YYYY-MM-DD)
        event_date_from:    Event date range start (YYYY-MM-DD)
        event_date_to:      Event date range end (YYYY-MM-DD)
        payment_status:     PAID or UNPAID
    """
    params = {}
    if keywords:           params["event"]            = keywords
    if event_id:           params["eventId"]          = event_id
    if vendor_id:          params["vendorId"]         = vendor_id
    if purchase_date_from: params["purchaseDateFrom"] = purchase_date_from
    if purchase_date_to:   params["purchaseDateTo"]   = purchase_date_to
    if event_date_from:    params["eventDateFrom"]    = event_date_from
    if event_date_to:      params["eventDateTo"]      = event_date_to
    if payment_status:     params["paymentStatus"]    = payment_status
    if purchase_date_from or purchase_date_to:
        return await _get_chunked("/inventory/purchased", params,
                                  "purchaseDateFrom", "purchaseDateTo",
                                  purchase_date_from, purchase_date_to)
    return await _get_chunked("/inventory/purchased", params,
                              "eventDateFrom", "eventDateTo",
                              event_date_from, event_date_to)


# ── QUICK REPORTS ─────────────────────────────────────────────────────────────

@mcp.tool()
async def get_quick_report_sales(
    invoice_date_from: Optional[str] = None,
    invoice_date_to: Optional[str] = None,
    event_date_from: Optional[str] = None,
    event_date_to: Optional[str] = None,
    event: Optional[str] = None,
    venue: Optional[str] = None,
    payment_status: Optional[str] = None,
    fulfillment_status: Optional[str] = None,
) -> dict:
    """
    Get aggregate sales revenue summary for a date range. Returns totals for:
    quantity, invoices, ticketCost, ticketSales, profit, profitPercentage, roi.
    Best tool for 'how much revenue did I make today/this week/this month'.
    Note: returns a single aggregate object, not row-level data.
    Args:
        invoice_date_from:  Sale date range start (YYYY-MM-DD)
        invoice_date_to:    Sale date range end (YYYY-MM-DD)
        event_date_from:    Event date range start (YYYY-MM-DD)
        event_date_to:      Event date range end (YYYY-MM-DD)
        event:              Filter by event name
        venue:              Filter by venue name
        payment_status:     Filter by payment status
        fulfillment_status: Filter by fulfillment status
    """
    params = {}
    if invoice_date_from:   params["invoiceDateFrom"]   = invoice_date_from
    if invoice_date_to:     params["invoiceDateTo"]     = invoice_date_to
    if event_date_from:     params["eventDateFrom"]     = event_date_from
    if event_date_to:       params["eventDateTo"]       = event_date_to
    if event:               params["event"]             = event
    if venue:               params["venue"]             = venue
    if payment_status:      params["paymentStatus"]     = payment_status
    if fulfillment_status:  params["fulfillmentStatus"] = fulfillment_status
    return await _get("/quick-report/sales", params)

@mcp.tool()
async def get_quick_report_purchases(
    purchase_date_from: Optional[str] = None,
    purchase_date_to: Optional[str] = None,
    event_date_from: Optional[str] = None,
    event_date_to: Optional[str] = None,
    event: Optional[str] = None,
    venue: Optional[str] = None,
    payment_status: Optional[str] = None,
) -> dict:
    """
    Get aggregate purchase cost summary for a date range. Returns totals for:
    purchases, quantity, ticketCost, outstandingBalance, availableQuantity, soldQuantity.
    Best tool for 'how much did I spend buying tickets this week/month'.
    Note: returns a single aggregate object, not row-level data.
    Args:
        purchase_date_from: Purchase date range start (YYYY-MM-DD)
        purchase_date_to:   Purchase date range end (YYYY-MM-DD)
        event_date_from:    Event date range start (YYYY-MM-DD)
        event_date_to:      Event date range end (YYYY-MM-DD)
        event:              Filter by event name
        venue:              Filter by venue name
        payment_status:     Filter by payment status
    """
    params = {}
    if purchase_date_from:  params["purchaseDateFrom"]  = purchase_date_from
    if purchase_date_to:    params["purchaseDateTo"]    = purchase_date_to
    if event_date_from:     params["eventDateFrom"]     = event_date_from
    if event_date_to:       params["eventDateTo"]       = event_date_to
    if event:               params["event"]             = event
    if venue:               params["venue"]             = venue
    if payment_status:      params["paymentStatus"]     = payment_status
    return await _get("/quick-report/purchases", params)


# ── VENDORS / CUSTOMERS / HOLDS / TAGS / WEBHOOKS ────────────────────────────

@mcp.tool()
async def get_vendors(keywords: Optional[str] = None, page_number: int = 0, page_size: int = 50) -> dict:
    """List vendors (ticket suppliers / box offices) in Skybox."""
    params = {"pageNumber": page_number, "pageSize": page_size}
    if keywords: params["keywords"] = keywords
    return await _get("/vendors", params)

@mcp.tool()
async def get_customers(keywords: Optional[str] = None, page_number: int = 0, page_size: int = 50) -> dict:
    """List customers (buyers) in Skybox."""
    params = {"pageNumber": page_number, "pageSize": page_size}
    if keywords: params["keywords"] = keywords
    return await _get("/customers", params)

@mcp.tool()
async def get_holds(page_number: int = 0, page_size: int = 50) -> dict:
    """List active holds on inventory in Skybox."""
    return await _get("/holds", {"pageNumber": page_number, "pageSize": page_size})

@mcp.tool()
async def get_hold_by_id(hold_id: int) -> dict:
    """Get details for a specific hold by ID."""
    return await _get(f"/holds/{hold_id}")

@mcp.tool()
async def get_tags() -> dict:
    """List all tags configured in the Skybox account."""
    return await _get("/tags")

@mcp.tool()
async def get_webhooks() -> dict:
    """List all webhook subscriptions configured on this Skybox account."""
    return await _get("/webhooks")

@mcp.tool()
async def create_webhook(topic: str, url: str, headers: Optional[str] = None, secret: Optional[str] = None) -> dict:
    """
    Create a webhook subscription for real-time Skybox notifications.
    Args:
        topic:   INVENTORY, PURCHASE, INVOICE, LINE, or HOLD
        url:     HTTPS endpoint to receive POST notifications
        headers: Optional auth headers string
        secret:  Optional HMAC secret for payload signature
    """
    body: dict = {"topic": topic, "url": url}
    if headers: body["headers"] = headers
    if secret:  body["secret"]  = secret
    return await _post("/webhooks", body)

@mcp.tool()
async def delete_webhook(webhook_id: int) -> dict:
    """Delete a webhook subscription by ID."""
    return await _delete(f"/webhooks/{webhook_id}")


# ── ENTRYPOINT ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    transport = sys.argv[1] if len(sys.argv) > 1 else "stdio"
    if transport == "sse":
        import uvicorn, time, secrets
        from starlette.applications import Starlette
        from starlette.routing import Route, Mount
        from starlette.responses import Response, JSONResponse, RedirectResponse
        from starlette.middleware.base import BaseHTTPMiddleware
        from mcp.server.sse import SseServerTransport

        CLIENT_ID     = os.environ.get("OAUTH_CLIENT_ID", "")
        CLIENT_SECRET = os.environ.get("OAUTH_CLIENT_SECRET", "")

        auth_codes    = {}
        access_tokens = {}

        async def oauth_metadata(request):
            base = str(request.base_url).rstrip("/")
            return JSONResponse({
                "issuer": base,
                "authorization_endpoint": f"{base}/oauth/authorize",
                "token_endpoint": f"{base}/oauth/token",
                "response_types_supported": ["code"],
                "grant_types_supported": ["authorization_code"],
            })

        async def oauth_authorize(request):
            params       = dict(request.query_params)
            client_id    = params.get("client_id", "")
            redirect_uri = params.get("redirect_uri", "")
            state        = params.get("state", "")
            if CLIENT_ID and client_id != CLIENT_ID:
                return Response("Invalid client_id", status_code=403)
            code = secrets.token_urlsafe(32)
            auth_codes[code] = {
                "client_id": client_id,
                "redirect_uri": redirect_uri,
                "expires": time.time() + 300,
            }
            sep = "&" if "?" in redirect_uri else "?"
            return RedirectResponse(
                url=f"{redirect_uri}{sep}code={code}&state={state}",
                status_code=302,
            )

        async def oauth_token(request):
            try:
                body = await request.json()
            except Exception:
                form = await request.form()
                body = dict(form)
            grant_type    = body.get("grant_type", "")
            code          = body.get("code", "")
            client_id     = body.get("client_id", "")
            client_secret = body.get("client_secret", "")
            if grant_type != "authorization_code":
                return JSONResponse({"error": "unsupported_grant_type"}, status_code=400)
            if CLIENT_SECRET and client_secret != CLIENT_SECRET:
                return JSONResponse({"error": "invalid_client"}, status_code=401)
            entry = auth_codes.pop(code, None)
            if not entry or time.time() > entry["expires"]:
                return JSONResponse({"error": "invalid_grant"}, status_code=400)
            token = secrets.token_urlsafe(32)
            access_tokens[token] = {"client_id": client_id, "expires": time.time() + 86400}
            return JSONResponse({
                "access_token": token,
                "token_type": "Bearer",
                "expires_in": 86400,
            })

        class BearerAuthMiddleware(BaseHTTPMiddleware):
            async def dispatch(self, request, call_next):
                return await call_next(request)

        sse_transport = SseServerTransport("/messages/")

        async def handle_sse(request):
            async with sse_transport.connect_sse(
                request.scope, request.receive, request._send
            ) as streams:
                await mcp._mcp_server.run(
                    streams[0], streams[1],
                    mcp._mcp_server.create_initialization_options()
                )

        async def health(request):
            return JSONResponse({"status": "ok"})

        app = Starlette(routes=[
            Route("/.well-known/oauth-authorization-server", oauth_metadata),
            Route("/oauth/authorize", oauth_authorize),
            Route("/oauth/token", oauth_token, methods=["POST"]),
            Route("/health", health),
            Route("/sse", handle_sse),
            Mount("/messages/", app=sse_transport.handle_post_message),
        ])
        app.add_middleware(BearerAuthMiddleware)

        port = int(os.environ.get("PORT", 8080))
        uvicorn.run(app, host="0.0.0.0", port=port)
    else:
        mcp.run(transport="stdio")
