"""Google カレンダー連携（サービスアカウント）

研究会の Google アカウントで作ったカレンダーを、サービスアカウントのメールアドレスに
「予定の変更」権限で共有して使う。個人のアカウントは使わない。

  GCAL_SERVICE_ACCOUNT_FILE  サービスアカウントの鍵（JSON）のパス
  GCAL_TASK_CALENDAR_ID      タスクの締切を入れるカレンダー（「ネッコ研 タスク」）のID
  GCAL_EVENT_CALENDAR_ID     （任意）研究会の予定カレンダーのID

権限の方針: 読み取り＝許可 / 作成・更新＝承認 / 削除＝なし（削除のAPIは呼ばない）。
タスクが完了・取り消しになっても予定は消さず、件名の頭に ✅ / ❌ を付ける。
"""

from __future__ import annotations

import json
import os
import time
from contextlib import closing
from datetime import date, datetime, timedelta
from urllib.parse import quote

import httpx
import jwt
from mcp.server.fastmcp import FastMCP

import tasks
from tasks import JST, READ, WRITE

API = os.environ.get("GCAL_API_BASE", "https://www.googleapis.com/calendar/v3")
SCOPE = "https://www.googleapis.com/auth/calendar.events"
_token: tuple[float, str] | None = None


def enabled() -> bool:
    return bool(os.environ.get("GCAL_SERVICE_ACCOUNT_FILE") and os.environ.get("GCAL_TASK_CALENDAR_ID"))


def calendars() -> dict[str, str]:
    out = {"tasks": os.environ.get("GCAL_TASK_CALENDAR_ID", "").strip()}
    ev = os.environ.get("GCAL_EVENT_CALENDAR_ID", "").strip()
    if ev:
        out["events"] = ev
    return {k: v for k, v in out.items() if v}


def _cal(name: str) -> str:
    cals = calendars()
    if name not in cals:
        raise ValueError(f"calendar は {' / '.join(cals)} のどれか")
    return cals[name]


async def _access_token() -> str:
    global _token
    if _token and _token[0] > time.time() + 60:
        return _token[1]
    with open(os.environ["GCAL_SERVICE_ACCOUNT_FILE"]) as f:
        sa = json.load(f)
    now = int(time.time())
    token_uri = sa.get("token_uri", "https://oauth2.googleapis.com/token")
    assertion = jwt.encode({"iss": sa["client_email"], "scope": SCOPE, "aud": token_uri, "iat": now, "exp": now + 3600},
                           sa["private_key"], algorithm="RS256")
    async with httpx.AsyncClient(timeout=20) as c:
        r = await c.post(token_uri, data={"grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
                                          "assertion": assertion})
    if r.status_code != 200:
        raise RuntimeError(f"Google の認証に失敗しました（{r.status_code}）: {r.text[:200]}")
    j = r.json()
    _token = (time.time() + int(j.get("expires_in", 3600)), j["access_token"])
    return _token[1]


async def _req(method: str, path: str, *, params: dict | None = None, body: dict | None = None):
    if method == "DELETE":
        raise PermissionError("削除は許可されていません")
    tok = await _access_token()
    async with httpx.AsyncClient(timeout=20, headers={"Authorization": f"Bearer {tok}"}) as c:
        r = await c.request(method, f"{API}{path}", params=params, json=body)
    if r.status_code in (403, 404):
        raise RuntimeError(f"カレンダーにアクセスできません（{r.status_code}）。サービスアカウントに「予定の変更」権限で共有されているか確認してください")
    if r.status_code >= 400:
        raise RuntimeError(f"Google カレンダーのエラー（{r.status_code}）: {r.text[:200]}")
    return r.json()


def _events_path(cal_id: str) -> str:
    return f"/calendars/{quote(cal_id, safe='')}/events"


# ---------------------------------------------------------------- タスク → カレンダー


def _task_event(r) -> dict:
    prefix = {"done": "✅", "cancelled": "❌"}.get(r["status"], "")
    desc = []
    if r["note"]:
        desc.append(r["note"])
    if r["source_url"]:
        desc.append(r["source_url"])
    desc.append(f"nekko-task:#{r['id']}")
    ev = {"summary": f"{prefix}⏰［{r['assignee_name']}］{r['title']}", "description": "\n".join(desc),
          "transparency": "transparent"}
    due = r["due"]
    if len(due) > 10:
        end = datetime.strptime(due, "%Y-%m-%dT%H:%M")
        start = end - timedelta(minutes=30)
        ev["start"] = {"dateTime": start.strftime("%Y-%m-%dT%H:%M:00"), "timeZone": "Asia/Tokyo"}
        ev["end"] = {"dateTime": end.strftime("%Y-%m-%dT%H:%M:00"), "timeZone": "Asia/Tokyo"}
    else:
        d = date.fromisoformat(due)
        ev["start"] = {"date": d.isoformat()}
        ev["end"] = {"date": (d + timedelta(days=1)).isoformat()}
    return ev


async def sync_task(task_id: int) -> str:
    """タスク1件をカレンダーに反映（作成 or 更新）。結果を短い文で返す。"""
    if not enabled():
        return ""
    with closing(tasks._db()) as con:
        r = con.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
    if not r:
        return ""
    cal = _cal("tasks")
    eid = r["gcal_event_id"]
    if not r["due"]:
        if eid:  # 期日が消えたら予定は残して件名で知らせる（削除はしない）
            await _req("PATCH", f"{_events_path(cal)}/{eid}", body={"summary": f"（期日取消）［{r['assignee_name']}］{r['title']}"})
            return "カレンダー：期日取消を反映"
        return ""
    body = _task_event(r)
    if eid:
        await _req("PATCH", f"{_events_path(cal)}/{eid}", body=body)
        return "カレンダー：更新"
    ev = await _req("POST", _events_path(cal), body=body)
    with closing(tasks._db()) as con:
        con.execute("UPDATE tasks SET gcal_event_id=? WHERE id=?", (ev["id"], task_id))
        con.commit()
    return "カレンダー：追加"


async def try_sync(task_id: int) -> str:
    try:
        s = await sync_task(task_id)
        return f"（{s}）" if s else ""
    except Exception as e:
        return f"（カレンダー反映に失敗: {e}）"


# ---------------------------------------------------------------- MCP ツール


def _fmt_event(e: dict) -> str:
    s = e.get("start", {})
    if "dateTime" in s:
        when = datetime.fromisoformat(s["dateTime"].replace("Z", "+00:00")).astimezone(JST)
        t = f"{when.month}/{when.day}({'月火水木金土日'[when.weekday()]}) {when:%H:%M}"
    else:
        d = date.fromisoformat(s.get("date", "1970-01-01"))
        t = f"{d.month}/{d.day}({'月火水木金土日'[d.weekday()]}) 終日"
    loc = f" @{e['location']}" if e.get("location") else ""
    return f"- {t} {e.get('summary', '(無題)')}{loc}\n  id: {e['id']}"


def register_calendar_tools(mcp: FastMCP, allow_write: bool) -> None:
    names = " / ".join(calendars())

    @mcp.tool(annotations=READ, description=f"研究会の Google カレンダーの予定を今日から days 日分返す。calendar: {names}（tasks＝タスクの締切）。query で絞り込み可。")
    async def calendar_list_events(days: int = 14, calendar: str = "tasks", query: str | None = None) -> str:
        cal = _cal(calendar)
        now = datetime.now(JST).replace(hour=0, minute=0, second=0, microsecond=0)
        params = {"timeMin": now.isoformat(), "timeMax": (now + timedelta(days=max(1, min(days, 120)))).isoformat(),
                  "singleEvents": "true", "orderBy": "startTime", "maxResults": 100}
        if query:
            params["q"] = query
        data = await _req("GET", _events_path(cal), params=params)
        items = data.get("items") or []
        return "\n".join(_fmt_event(e) for e in items) if items else "予定はありません。"

    if not allow_write:
        return

    @mcp.tool(annotations=WRITE)
    async def calendar_create_event(title: str, start: str, end: str | None = None, calendar: str = "events",
                                    location: str | None = None, description: str | None = None) -> str:
        """【書き込み・要承認】研究会のカレンダーに予定を作る。
        start/end: 'YYYY-MM-DD'（終日）または 'YYYY-MM-DDTHH:MM'（JST）。end 省略時は終日なら1日、時刻ありなら1時間。"""
        if not title.strip():
            raise ValueError("タイトルが空です")
        body: dict = {"summary": title.strip()}
        if location:
            body["location"] = location
        if description:
            body["description"] = description
        body.update(_times(start, end))
        e = await _req("POST", _events_path(_cal(calendar)), body=body)
        return "作成しました:\n" + _fmt_event(e)

    @mcp.tool(annotations=WRITE)
    async def calendar_update_event(event_id: str, calendar: str = "events", title: str | None = None,
                                    start: str | None = None, end: str | None = None,
                                    location: str | None = None, description: str | None = None) -> str:
        """【書き込み・要承認】予定を変更する（指定した項目だけ）。予定の削除はできない。"""
        body: dict = {}
        if title is not None:
            if not title.strip():
                raise ValueError("タイトルを空にはできません")
            body["summary"] = title.strip()
        if start:
            body.update(_times(start, end))
        if location is not None:
            body["location"] = location
        if description is not None:
            body["description"] = description
        if not body:
            return "変更する項目がありません。"
        e = await _req("PATCH", f"{_events_path(_cal(calendar))}/{quote(event_id, safe='')}", body=body)
        return "更新しました:\n" + _fmt_event(e)

    @mcp.tool(annotations=WRITE)
    async def calendar_sync_tasks() -> str:
        """【書き込み・要承認】期日のあるタスクを全部「タスク」カレンダーに反映し直す（作成 or 更新、削除はしない）。"""
        with closing(tasks._db()) as con:
            ids = [r["id"] for r in con.execute("SELECT id FROM tasks WHERE due IS NOT NULL OR gcal_event_id IS NOT NULL")]
        ok, ng = 0, []
        for i in ids:
            try:
                await sync_task(i)
                ok += 1
            except Exception as e:
                ng.append(f"#{i}: {e}")
        return f"{ok}件を反映しました。" + ("\n失敗:\n" + "\n".join(ng) if ng else "")


def _times(start: str, end: str | None) -> dict:
    if len(start) == 10:
        d = date.fromisoformat(start)
        e = date.fromisoformat(end) + timedelta(days=1) if end else d + timedelta(days=1)
        return {"start": {"date": d.isoformat()}, "end": {"date": e.isoformat()}}
    s = datetime.strptime(start, "%Y-%m-%dT%H:%M")
    e = datetime.strptime(end, "%Y-%m-%dT%H:%M") if end else s + timedelta(hours=1)
    if e <= s:
        raise ValueError("end は start より後にしてください")
    return {"start": {"dateTime": s.strftime("%Y-%m-%dT%H:%M:00"), "timeZone": "Asia/Tokyo"},
            "end": {"dateTime": e.strftime("%Y-%m-%dT%H:%M:00"), "timeZone": "Asia/Tokyo"}}
