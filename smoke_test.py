import asyncio, sys
sys.path.insert(0, r'C:\Users\rafae\OneDrive\Claude\skybox-mcp')
from skybox_mcp.server import get_inventory, get_events, get_vendors

async def test():
    print('--- get_inventory (3 available listings) ---')
    r = await get_inventory(status='AVAILABLE', page_size=3)
    print(f'Total inventory: {r["rowCount"]}')
    for row in r['rows'][:2]:
        print(f'  id={row["id"]} event={row["eventId"]} {row["section"]} row={row["row"]} seats={row["lowSeat"]}-{row["highSeat"]} qty={row["quantity"]} price={row["listPrice"]} broadcast={row["broadcast"]}')

    print()
    print('--- get_events (keywords=symphony) ---')
    r2 = await get_events(keywords='symphony', page_size=3)
    print(f'Total matching events: {r2["rowCount"]}')
    for ev in r2['rows'][:2]:
        print(f'  id={ev["id"]} {ev["name"]} @ {ev["venue"]["name"]} on {ev["date"]}')

    print()
    print('--- get_vendors (first 3) ---')
    r3 = await get_vendors(page_size=3)
    print(f'Total vendors: {r3["rowCount"]}')

    print()
    print('ALL TESTS PASSED')

asyncio.run(test())
