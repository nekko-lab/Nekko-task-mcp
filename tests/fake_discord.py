"""テスト用の偽 Discord API（本物には接続しない）"""
from datetime import datetime, timedelta, timezone
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route
import uvicorn

EPOCH = 1420070400000
def sf(dt): return str((int(dt.timestamp()*1000)-EPOCH) << 22)
now = datetime.now(timezone.utc)
G = "111"; ME = "900"; ROLE = "777"
t1, t2, t3 = now-timedelta(hours=30), now-timedelta(hours=5), now-timedelta(hours=1)
msgs = {
  "201": [
    {"id": sf(t1), "channel_id": "201", "timestamp": t1.isoformat(), "content": "11/5までに照明の発注お願いします <@900>",
     "author": {"id": "500", "username": "sumyka", "global_name": "すみか"}, "mentions": [{"id": "900", "username": "fortelight", "global_name": "フォルテライト"}], "mention_roles": []},
    {"id": sf(t2), "channel_id": "201", "timestamp": t2.isoformat(), "content": "<@&777> 次回MO会議は水曜21時です",
     "author": {"id": "501", "username": "miranop"}, "mentions": [], "mention_roles": ["777"]},
  ],
  "301": [
    {"id": sf(t3), "channel_id": "301", "timestamp": t3.isoformat(), "content": "スレッド内: セトリ確定版です",
     "author": {"id": "502", "username": "x"}, "mentions": [], "mention_roles": [], "attachments": [{"filename": "setlist.pdf"}]},
  ],
}
chans = [
  {"id": "201", "type": 0, "name": "全体連絡", "last_message_id": sf(t2)},
  {"id": "202", "type": 0, "name": "雑談", "last_message_id": sf(now-timedelta(days=20))},
  {"id": "203", "type": 4, "name": "カテゴリ"},
  {"id": "204", "type": 0, "name": "秘密", "last_message_id": sf(t3)},
]
threads = {"threads": [{"id": "301", "type": 11, "name": "セトリ", "parent_id": "201", "last_message_id": sf(t3)}]}

async def channels(r): return JSONResponse(chans)
async def active(r): return JSONResponse(threads)
async def member(r): return JSONResponse({"roles": [ROLE]})
async def messages(r):
    cid = r.path_params["cid"]
    if cid == "204": return JSONResponse({"message": "Missing Access"}, status_code=403)
    after = int(r.query_params.get("after", "0"))
    out = [m for m in msgs.get(cid, []) if int(m["id"]) > after]
    return JSONResponse(list(reversed(out)))
async def events(r): return JSONResponse([{"name": "Prelude 通しリハ", "scheduled_start_time": (now+timedelta(days=3)).isoformat(),
    "scheduled_end_time": (now+timedelta(days=3, hours=3)).isoformat(), "entity_metadata": {"location": "615教室"}, "user_count": 12, "description": "全員参加"}])
async def roles(r): return JSONResponse([{"id": "777", "name": "MO制作"}, {"id": "778", "name": "MO"}, {"id": "779", "name": "NC"}, {"id": "111", "name": "@everyone"}])
async def search(r):
    q = r.query_params["query"]
    db = [{"user": {"id": "503", "username": "kushi", "global_name": "くしもち"}, "nick": None}]
    return JSONResponse([m for m in db if q in (m["user"]["global_name"] or "")])
commands = {}
async def put_commands(r):
    commands[r.path_params["gid"]] = await r.json(); print("COMMANDS:", [c["name"] for c in commands[r.path_params["gid"]]], flush=True)
    return JSONResponse(commands[r.path_params["gid"]])
posted = []
async def webhook(r):
    posted.append(await r.json()); print("WEBHOOK:", posted[-1]["content"].replace("\n"," | "), "|| allowed_mentions:", posted[-1]["allowed_mentions"], flush=True)
    from starlette.responses import Response
    return Response(status_code=204)
async def pins(r): return JSONResponse(msgs["201"][:1])

app = Starlette(routes=[
  Route(f"/guilds/{G}/channels", channels), Route(f"/guilds/{G}/threads/active", active),
  Route(f"/guilds/{G}/members/search", search), Route(f"/guilds/{G}/members/{{uid}}", member),
  Route("/applications/{app}/guilds/{gid}/commands", put_commands, methods=["PUT"]), Route("/channels/{cid}/messages", messages),
  Route(f"/guilds/{G}/scheduled-events", events), Route("/channels/{cid}/pins", pins), Route(f"/guilds/{G}/roles", roles), Route("/webhook", webhook, methods=["POST"]),
])
if __name__ == "__main__": uvicorn.run(app, port=8901, log_level="warning")
