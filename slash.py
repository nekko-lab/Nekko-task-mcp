"""Discord のスラッシュコマンド /タスク（HTTP Interactions 方式）

Developer Portal の「Interactions Endpoint URL」に https://<公開URL>/discord/interactions を設定する。
- Discord からのリクエストは Ed25519 署名を必ず検証し、不正なものは 401 で拒否
- 返事は打った本人にだけ見える（ephemeral）。メンションは飛ばさない
- 読み取りだけ。タスクの追加・変更・削除はできない

  DISCORD_APP_ID      アプリケーションID（General Information → Application ID）
  DISCORD_PUBLIC_KEY  公開鍵（General Information → Public Key）
"""

from __future__ import annotations

import json
import os
import sys

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

import people
import tasks

EPHEMERAL = 64
COMMAND = {
    "name": "タスク",
    "description": "ネッコ研のタスク台帳を見る（自分にだけ表示されます）",
    "type": 1,
    "contexts": [0],
    "options": [
        {"type": 1, "name": "自分", "description": "自分の担当タスク（ロール宛ての「MO全員」なども含む）"},
        {"type": 1, "name": "一覧", "description": "未完了タスクの一覧",
         "options": [{"type": 3, "name": "チーム", "description": "MO / NC / 全体（省略で全部）", "required": False,
                      "choices": [{"name": t, "value": t} for t in tasks.TEAMS]}]},
        {"type": 1, "name": "締切", "description": "近い締切（期限切れを含む）",
         "options": [{"type": 4, "name": "日数", "description": "何日以内か（既定 7）", "required": False,
                      "min_value": 1, "max_value": 60}]},
    ],
}


def _srv():
    return sys.modules["server"]


def enabled() -> bool:
    return bool(os.environ.get("DISCORD_APP_ID") and os.environ.get("DISCORD_PUBLIC_KEY"))


def _verify(public_key: str, sig: str, ts: str, body: bytes) -> bool:
    try:
        Ed25519PublicKey.from_public_bytes(bytes.fromhex(public_key)).verify(bytes.fromhex(sig), ts.encode() + body)
        return True
    except (InvalidSignature, ValueError):
        return False


def _reply(text: str) -> JSONResponse:
    if len(text) > 1990:
        text = text[:1950] + "\n…（多いので途中まで。続きは Claude で聞いてください）"
    return JSONResponse({"type": 4, "data": {"content": text, "flags": EPHEMERAL, "allowed_mentions": {"parse": []}}})


async def _mine(gid: str, member: dict) -> str:
    user = member.get("user") or {}
    uid = user.get("id", "")
    people.remember([user], {uid: member.get("nick") or ""})
    names = {tasks._norm(x) for x in (member.get("nick"), user.get("global_name"), user.get("username")) if x}
    roles = await _srv().guild_roles(gid)
    role_names = {tasks._norm(roles.get(r, "")) for r in member.get("roles", [])} - {""}
    rows = [r for r in tasks._query("open") if people.matches_member(r["assignee_name"], r["assignee_id"], uid, names, role_names)]
    disp = member.get("nick") or user.get("global_name") or user.get("username") or "あなた"
    return f"**{disp}** さんの担当タスク（{len(rows)}件）\n" + tasks._render(rows, with_id=False)


async def interactions(request: Request) -> Response:
    body = await request.body()
    key = os.environ.get("DISCORD_PUBLIC_KEY", "")
    if not _verify(key, request.headers.get("x-signature-ed25519", ""),
                   request.headers.get("x-signature-timestamp", ""), body):
        return Response("invalid request signature", status_code=401)
    data = json.loads(body)
    if data.get("type") == 1:  # PING
        return JSONResponse({"type": 1})
    if data.get("type") != 2:
        return _reply("対応していない操作です。")
    gid = data.get("guild_id", "")
    if gid not in _srv().ALLOWED_GUILD_IDS:
        return _reply("このサーバーでは使えません。")
    cmd = data.get("data") or {}
    if cmd.get("name") != COMMAND["name"]:
        return _reply("不明なコマンドです。")
    sub = (cmd.get("options") or [{}])[0]
    opts = {o["name"]: o.get("value") for o in sub.get("options") or []}
    try:
        if sub.get("name") == "自分":
            return _reply(await _mine(gid, data.get("member") or {}))
        if sub.get("name") == "一覧":
            team = opts.get("チーム")
            rows = tasks._query("open", team=team)
            return _reply(f"未完了タスク{f'（{team}）' if team else ''}（{len(rows)}件）\n" + tasks._render(rows, with_id=False))
        if sub.get("name") == "締切":
            days = int(opts.get("日数") or 7)
            rows = tasks._query("open", due_within_days=days)
            return _reply(f"{days}日以内の締切（{len(rows)}件）\n" + tasks._render(rows, with_id=False))
    except Exception as e:
        return _reply(f"エラーが起きました: {e}")
    return _reply("不明なサブコマンドです。")


async def register_commands() -> str:
    """ギルドコマンドとして /タスク を登録（起動時に毎回上書き）"""
    app_id = os.environ["DISCORD_APP_ID"].strip()
    srv = _srv()
    out = []
    for gid in srv.ALLOWED_GUILD_IDS:
        r = await srv.discord()._client.put(f"/applications/{app_id}/guilds/{gid}/commands", json=[COMMAND])
        if r.status_code == 403 or r.status_code == 401:
            out.append(f"{gid}: 登録できません（{r.status_code}）。Bot を applications.commands 付きで招待し直してください: "
                       f"https://discord.com/oauth2/authorize?client_id={app_id}&scope=bot+applications.commands&permissions=66560")
        elif r.status_code >= 300:
            out.append(f"{gid}: 登録失敗 {r.status_code} {r.text[:200]}")
        else:
            out.append(f"{gid}: /タスク を登録しました")
    return " / ".join(out)


routes = [Route("/discord/interactions", interactions, methods=["POST"])]
