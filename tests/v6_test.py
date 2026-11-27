import asyncio, sys, json, time, httpx
from datetime import datetime, timedelta, timezone
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client
ADMIN, MEMBER, BASE, EDKEY = sys.argv[1:5]
JST = timezone(timedelta(hours=9)); today = datetime.now(JST).date()
d = lambda n: (today + timedelta(days=n)).isoformat()
async def call(s, n, a=None):
    r = await s.call_tool(n, a or {})
    print(f"--- {n} err={r.isError}: " + " / ".join(c.text for c in r.content)[:700].replace("\n", " | "))
async def admin():
    async with streamablehttp_client(ADMIN) as (r, w, _):
        async with ClientSession(r, w) as s:
            await s.initialize()
            names = [t.name for t in (await s.list_tools()).tools]
            print("ADMIN TOOLS:", names)
            assert not [n for n in names if "delete" in n]
            await call(s, "recent_messages", {"hours": 48})  # people キャッシュに すみか(500) 等が入る
            await call(s, "task_add", {"title": "照明を発注する", "assignee_name": "すみか", "team": "MO", "due": d(0)})
            await call(s, "task_add", {"title": "Tシャツアンケートに回答する", "assignee_name": "MO全員", "team": "MO", "due": d(1) + "T23:59"})
            await call(s, "task_add", {"title": "配線図を送る", "assignee_name": "フォルテライト・すみか", "team": "MO", "due": d(-1)})
            await call(s, "task_add", {"title": "機材を決める", "assignee_name": "くしもち", "team": "MO", "due": d(5)})
            await call(s, "task_add", {"title": "謎の人の作業", "assignee_name": "だれか", "team": "NC", "due": d(1)})
            await call(s, "task_update", {"task_id": 4, "status": "done"})
            await call(s, "task_update", {"task_id": 5, "due": "none"})
            await call(s, "calendar_list_events", {"days": 30, "calendar": "tasks"})
            await call(s, "calendar_create_event", {"title": "ポリッドスクリーン設置会", "start": d(4) + "T18:00", "calendar": "events", "location": "フォル邸"})
            await call(s, "calendar_update_event", {"event_id": "ev6", "calendar": "events", "title": ""})
            await call(s, "calendar_create_event", {"title": "x", "start": d(1), "calendar": "secret"})
            await call(s, "preview_daily_digest")
            await call(s, "post_daily_digest")
            await call(s, "post_digest", {"text": "手動投稿 <@500> @everyone"})
async def member():
    async with streamablehttp_client(MEMBER) as (r, w, _):
        async with ClientSession(r, w) as s:
            await s.initialize()
            print("MEMBER TOOLS:", [t.name for t in (await s.list_tools()).tools])
            await call(s, "calendar_list_events", {"calendar": "tasks", "days": 10})
def interact(body, good=True):
    key = Ed25519PrivateKey.from_private_bytes(open(EDKEY, "rb").read())
    raw = json.dumps(body).encode(); ts = str(int(time.time()))
    sig = key.sign(ts.encode() + raw).hex() if good else "00" * 64
    r = httpx.post(BASE + "/discord/interactions", content=raw, headers={"x-signature-ed25519": sig, "x-signature-timestamp": ts, "content-type": "application/json"})
    out = r.json()["data"]["content"].replace("\n", " | ")[:400] if r.status_code == 200 and r.json().get("data") else r.text
    print(f"SLASH {r.status_code}: {out}")
asyncio.run(admin()); asyncio.run(member())
interact({"type": 1}); interact({"type": 1}, good=False)
mem = {"user": {"id": "500", "username": "sumyka", "global_name": "すみか"}, "roles": ["778"], "nick": None}
interact({"type": 2, "guild_id": "111", "member": mem, "data": {"name": "タスク", "options": [{"type": 1, "name": "自分"}]}})
interact({"type": 2, "guild_id": "111", "member": {"user": {"id": "999", "username": "nc"}, "roles": ["779"]}, "data": {"name": "タスク", "options": [{"type": 1, "name": "自分"}]}})
interact({"type": 2, "guild_id": "111", "member": mem, "data": {"name": "タスク", "options": [{"type": 1, "name": "一覧", "options": [{"name": "チーム", "value": "NC"}]}]}})
interact({"type": 2, "guild_id": "111", "member": mem, "data": {"name": "タスク", "options": [{"type": 1, "name": "締切", "options": [{"name": "日数", "value": 3}]}]}})
interact({"type": 2, "guild_id": "222", "member": mem, "data": {"name": "タスク", "options": [{"type": 1, "name": "自分"}]}})
