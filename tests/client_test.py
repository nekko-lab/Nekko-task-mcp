import asyncio, sys
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client
URL = sys.argv[1]
async def main():
    async with streamablehttp_client(URL) as (r, w, _):
        async with ClientSession(r, w) as s:
            await s.initialize()
            tools = await s.list_tools()
            print("TOOLS:", [t.name for t in tools.tools])
            for name, args in [("list_channels", {}), ("recent_messages", {"hours": 48}),
                               ("get_my_mentions", {"hours": 48}), ("list_scheduled_events", {}),
                               ("read_channel", {"channel_id": "204"}), ("get_pinned_messages", {"channel_id": "201"}),
                               ("list_channels", {"guild_id": "999"})]:
                res = await s.call_tool(name, args)
                print(f"\n=== {name} {args} (error={res.isError})\n" + "\n".join(c.text for c in res.content))
asyncio.run(main())
