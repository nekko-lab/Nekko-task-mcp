import asyncio, sys
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client
async def run(url, calls, show_annot=False):
    async with streamablehttp_client(url) as (r, w, _):
        async with ClientSession(r, w) as s:
            await s.initialize()
            tools = (await s.list_tools()).tools
            print("TOOLS:", ", ".join(f"{t.name}[{'RO' if t.annotations and t.annotations.readOnlyHint else 'W'}{'!' if t.annotations and t.annotations.destructiveHint else ''}]" for t in tools))
            for n, a in calls:
                res = await s.call_tool(n, a)
                print(f"--- {n} err={res.isError}: " + " / ".join(c.text for c in res.content)[:260].replace("\n", " | "))
P = "/Miku's Origin/MO17/MO会議/20261028 第24回"
asyncio.run(run(sys.argv[1], [
  ("growi_search", {"query": "配線図"}),
  ("growi_list_pages", {"path": "/Miku's Origin/MO17"}),
  ("growi_read_page", {"path": P}),
  ("growi_append_to_page", {"path": P, "text": "- 追記テスト"}),
  ("growi_update_page", {"path": P, "body": "短い"}),
  ("growi_update_page", {"path": P, "body": ""}),
  ("growi_create_page", {"path": "/Miku's Origin/MO17/タスク/test", "body": "hello"}),
  ("growi_create_page", {"path": "/Secret/x", "body": "hello"}),
  ("growi_recent_pages", {}),
]))
print("====== MEMBER")
asyncio.run(run(sys.argv[2], [("growi_read_page", {"path": P}), ("growi_create_page", {"path": "/Miku's Origin/x", "body": "y"})]))
