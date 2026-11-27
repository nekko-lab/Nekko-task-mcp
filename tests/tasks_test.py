import asyncio, sys
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client
ADMIN, MEMBER = sys.argv[1], sys.argv[2]
async def call(url, calls):
    async with streamablehttp_client(url) as (r, w, _):
        async with ClientSession(r, w) as s:
            await s.initialize()
            print("TOOLS:", [t.name for t in (await s.list_tools()).tools])
            for name, args in calls:
                res = await s.call_tool(name, args)
                print(f"--- {name} {args} err={res.isError}\n" + "\n".join(c.text for c in res.content))
asyncio.run(call(ADMIN, [
  ("task_add", {"title": "借用機材の決定", "assignee_name": "くしもち・鈴木 椋大", "team": "MO", "due": "2026-11-05T18:00", "source_url": "https://discord.com/x/1"}),
  ("task_add", {"title": "借用機材の決定", "assignee_name": "くしもち・鈴木 椋大", "team": "MO", "due": "2026-11-05T18:00", "source_url": "https://discord.com/x/1"}),
  ("task_add", {"title": "グッズ一覧画像を作る", "assignee_name": "べすめと", "team": "MO", "due": "2026-11-04"}),
  ("task_add", {"title": "期限切れテスト", "assignee_name": "フォルテライト", "team": "全体", "due": "2026-10-01"}),
  ("task_add", {"title": "bad", "assignee_name": "x", "due": "11/5"}),
  ("task_update", {"task_id": 3, "status": "done"}),
  ("task_list", {"status": "all"}),
  ("post_digest", {"text": "📋 今日のタスク\n- テスト <@123> @everyone"}),
]))
asyncio.run(call(MEMBER, [
  ("my_tasks", {"name": "くしもちさん"}),
  ("list_tasks", {"team": "MO"}),
  ("upcoming_deadlines", {"days": 30}),
]))
