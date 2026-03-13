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
import httpx
from mcp.server.fastmcp import FastMCP
from dotenv import load_dotenv

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), '..', '.env'))

mcp = FastMCP("skybox")
BASE_URL = "https://skybox.vividseats.com/services"

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


# ── INVENTORY ─────────────────────────────────────────────────────────────────

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
        page_number: Zero-based page number
        page_size:   Results per page (max 100)
    """
    params = {"pageNumber": page_number, "pageSize": page_size}
    if keywords:  params["keywords"]  = keywords
    if event_id:  params["eventId"]   = event_id
    if section:   params["section"]   = section
    if status:    params["status"]    = status
    if broadcast is not None: params["broadcast"] = str(broadcast).lower()
    return await _get("/inventory", params)

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

# ── INVOICES (Sell Side) ───────────────────────────────────────────────────────

@mcp.tool()
async def get_invoices(
    event_id: int,
    fulfillment_status: Optional[str] = None,
    payment_status: Optional[str] = None,
    page_number: int = 0,
    page_size: int = 50,
) -> dict:
    """
    List sales invoices for a specific event. event_id is required.
    Args:
        event_id:           Skybox event ID (required)
        fulfillment_status: FULFILLED or UNFULFILLED
        payment_status:     PAID or UNPAID
    """
    params = {"pageNumber": page_number, "pageSize": page_size, "eventId": event_id}
    if fulfillment_status: params["fulfillmentStatus"] = fulfillment_status
    if payment_status:     params["paymentStatus"]     = payment_status
    return await _get("/invoices", params)


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

# ── PURCHASES (Buy Side) ───────────────────────────────────────────────────────

@mcp.tool()
async def get_purchases(
    event_id: int,
    payment_status: Optional[str] = None,
    vendor_id: Optional[int] = None,
    page_number: int = 0,
    page_size: int = 50,
) -> dict:
    """
    List purchase orders for a specific event. event_id is required.
    Args:
        event_id:       Skybox event ID (required)
        payment_status: PAID or UNPAID
        vendor_id:      Filter by vendor/supplier ID
    """
    params = {"pageNumber": page_number, "pageSize": page_size, "eventId": event_id}
    if payment_status: params["paymentStatus"] = payment_status
    if vendor_id:      params["vendorId"]      = vendor_id
    return await _get("/purchases", params)

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

# ── VENDORS / CUSTOMERS ───────────────────────────────────────────────────────

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


# ── HOLDS ─────────────────────────────────────────────────────────────────────

@mcp.tool()
async def get_holds(page_number: int = 0, page_size: int = 50) -> dict:
    """List active holds on inventory in Skybox."""
    return await _get("/holds", {"pageNumber": page_number, "pageSize": page_size})

@mcp.tool()
async def get_hold_by_id(hold_id: int) -> dict:
    """Get details for a specific hold by ID."""
    return await _get(f"/holds/{hold_id}")

# ── TAGS ──────────────────────────────────────────────────────────────────────

@mcp.tool()
async def get_tags() -> dict:
    """List all tags configured in the Skybox account."""
    return await _get("/tags")

# ── WEBHOOKS ──────────────────────────────────────────────────────────────────

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

# ── REPORTS ───────────────────────────────────────────────────────────────────

@mcp.tool()
async def get_purchased_inventory_report(
    purchase_date_from: Optional[str] = None,
    purchase_date_to: Optional[str] = None,
    event_date_from: Optional[str] = None,
    event_date_to: Optional[str] = None,
    page_number: int = 0,
    page_size: int = 100,
) -> dict:
    """
    Pull the Purchased Inventory P&L report from Skybox.
    Args:
        purchase_date_from: Start of purchase date range (YYYY-MM-DD)
        purchase_date_to:   End of purchase date range (YYYY-MM-DD)
        event_date_from:    Start of event date range (YYYY-MM-DD)
        event_date_to:      End of event date range (YYYY-MM-DD)
    """
    params = {"pageNumber": page_number, "pageSize": page_size}
    if purchase_date_from: params["purchaseDateFrom"] = purchase_date_from
    if purchase_date_to:   params["purchaseDateTo"]   = purchase_date_to
    if event_date_from:    params["eventDateFrom"]    = event_date_from
    if event_date_to:      params["eventDateTo"]      = event_date_to
    return await _get("/reports/purchases", params)





# -- ENTRYPOINT --------------------------------------------------------------

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

        # In-memory stores
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
            access_tokens[token] = {
                "client_id": client_id,
                "expires": time.time() + 86400,
            }
            return JSONResponse({
                "access_token": token,
                "token_type": "Bearer",
                "expires_in": 86400,
            })

        class BearerAuthMiddleware(BaseHTTPMiddleware):
            async def dispatch(self, request, call_next):
                p = request.url.path
                if p.startswith("/oauth") or p in ("/.well-known/oauth-authorization-server", "/health"):
                    return await call_next(request)
                if access_tokens:
                    auth = request.headers.get("Authorization", "")
                    if not auth.startswith("Bearer "):
                        return Response("Unauthorized", status_code=401)
                    token = auth[len("Bearer "):]
                    entry = access_tokens.get(token)
                    if not entry or time.time() > entry["expires"]:
                        return Response("Unauthorized", status_code=401)
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
