path = r'C:\Users\rafae\OneDrive\Claude\skybox-mcp\skybox_mcp\server.py'
with open(path, 'r', encoding='utf-8') as f:
    content = f.read()

old = """async def _post(path: str, body: dict) -> dict:
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.post(f\"{BASE_URL}{path}\", headers=_headers(), json=body)
        r.raise_for_status()
        return r.json()

async def _put(path: str, body: dict) -> dict:
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.put(f\"{BASE_URL}{path}\", headers=_headers(), json=body)
        r.raise_for_status()
        return r.json()

async def _delete(path: str) -> dict:
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.delete(f\"{BASE_URL}{path}\", headers=_headers())
        r.raise_for_status()
        try:
            return r.json()
        except Exception:
            return {\"status\": \"deleted\", \"statusCode\": r.status_code}"""

new = """def _check_read_only(method: str) -> None:
    if os.environ.get("SKYBOX_READ_ONLY", "").lower() == "true":
        raise PermissionError(
            f"Skybox MCP is in READ-ONLY mode. "
            f"{method.upper()} calls are disabled. "
            f"Set SKYBOX_READ_ONLY=false in your .env to enable writes."
        )

async def _post(path: str, body: dict) -> dict:
    _check_read_only("POST")
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.post(f\"{BASE_URL}{path}\", headers=_headers(), json=body)
        r.raise_for_status()
        return r.json()

async def _put(path: str, body: dict) -> dict:
    _check_read_only("PUT")
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.put(f\"{BASE_URL}{path}\", headers=_headers(), json=body)
        r.raise_for_status()
        return r.json()

async def _delete(path: str) -> dict:
    _check_read_only("DELETE")
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.delete(f\"{BASE_URL}{path}\", headers=_headers())
        r.raise_for_status()
        try:
            return r.json()
        except Exception:
            return {"status": "deleted", "statusCode": r.status_code}"""

if old in content:
    content = content.replace(old, new)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(content)
    print('SUCCESS - read-only guard added')
else:
    print('ERROR - target block not found')
    # Debug: show what's actually in the file around _post
    idx = content.find('async def _post')
    print(repr(content[idx:idx+200]))
