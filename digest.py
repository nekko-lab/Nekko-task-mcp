"""毎朝のまとめ投稿（Claude なしでサーバーだけで作る）

- 期限切れ・今日まで・明日まで の担当者にはメンション（1人1回）。「◯◯全員」は @◯◯ ロール
- 2〜7日以内・新しく増えた・完了は名前だけ（通知なし）
- @everyone / @here は絶対に飛ばさない（allowed_mentions で users / roles だけ許可）
- DIGEST_TIME（既定 08:00）を過ぎたら1日1回投稿。Mac がスリープしていたら起きたときに投稿（21時まで）
"""

from __future__ import annotations

import asyncio
import os
import re
import sys
from contextlib import closing
from datetime import date, datetime, timedelta

import httpx

import people
import tasks
from tasks import JST

DIGEST_TIME = os.environ.get("DIGEST_TIME", "09:00")
CALENDAR_URL = os.environ.get("DIGEST_CALENDAR_URL", "").strip()  # まとめの最後に付けるカレンダー追加リンク
EVENT_NAME = os.environ.get("EVENT_NAME", "津田沼祭")
EVENT_DATE = os.environ.get("EVENT_DATE", "2026-11-21")
LATEST_HOUR = 21


def _srv():
    return sys.modules["server"]


def _meta_get(key: str) -> str | None:
    with closing(tasks._db()) as con:
        r = con.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
    return r["value"] if r else None


def _meta_set(key: str, value: str) -> None:
    with closing(tasks._db()) as con:
        con.execute("INSERT INTO meta(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                    (key, value))
        con.commit()


def _short_due(due: str | None) -> str:
    if not due:
        return "期日なし"
    d = date.fromisoformat(due[:10])
    return f"{d.month}/{d.day}({'月火水木金土日'[d.weekday()]})" + (f" {due[11:16]}" if len(due) > 10 else "")


async def build(now: datetime | None = None, mention: bool = True) -> tuple[str, bool]:
    """(本文, 投稿する価値があるか) を返す"""
    now = now or datetime.now(JST)
    today = now.date()
    gid = _srv().check_guild(None)
    since = _meta_get("last_digest_at") or (now - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%S")

    open_rows = tasks._query("open")
    overdue, due_today, due_tomorrow, week = [], [], [], []
    for r in open_rows:
        if not r["due"]:
            continue
        d = date.fromisoformat(r["due"][:10])
        delta = (d - today).days
        (overdue if delta < 0 else due_today if delta == 0 else due_tomorrow if delta == 1
         else week if delta <= 7 else []).append(r)
    with closing(tasks._db()) as con:
        new = con.execute("SELECT * FROM tasks WHERE created_at > ? ORDER BY id", (since,)).fetchall()
        done = con.execute("SELECT * FROM tasks WHERE status='done' AND updated_at > ? ORDER BY id", (since,)).fetchall()

    mentioned: set[str] = set()

    async def who(r, ping: bool) -> str:
        parts = []
        for kind, xid, disp in await people.resolve(gid, r["assignee_name"], r["assignee_id"]):
            key = f"{kind}:{xid}"
            if ping and mention and kind in ("user", "role") and key not in mentioned:
                mentioned.add(key)
                parts.append(f"<@{xid}>" if kind == "user" else f"<@&{xid}>")
            else:
                parts.append(disp)
        return "・".join(parts) or r["assignee_name"]

    # Discord の Markdown で整形（## 見出し・- 箇条書き・-# 小さい注記・[文字](<URL>) リンク）
    lines = [f"## 📋 ネッコ研タスク（{today.month}/{today.day}・{'月火水木金土日'[today.weekday()]}）"]
    cd = _countdown(today)
    if cd:
        lines.append(f"-# {cd.strip()}")

    async def section(title: str, rows, ping: bool, with_due: bool = True, team: bool = False, strike: bool = False):
        if not rows:
            return
        lines.append(f"### {title}（{len(rows)}）")
        for r in rows:
            head = f"**{_short_due(r['due'])}** " if with_due and r["due"] else ""
            tm = f"`{r['team']}` " if team else ""
            body = f"~~{r['title']}~~" if strike else r["title"]
            lines.append(f"- {head}{tm}{body} — {await who(r, ping)}")

    await section("🔥 期限切れ", overdue, ping=True)
    await section("📌 今日まで", due_today, ping=True, with_due=False)
    await section("🔔 明日まで", due_tomorrow, ping=True)
    await section("⏳ 7日以内", week, ping=False)
    await section("🆕 新しく増えたタスク", new, ping=False, team=True)
    await section("✅ 完了になったタスク", done, ping=False, with_due=False, strike=True)
    lines.append("")
    if CALENDAR_URL:
        lines.append(f"📅 [締切カレンダーを追加する](<{CALENDAR_URL}>)")
    lines.append("-# 自分の担当は `/タスク 自分`、近い締切は `/タスク 締切`（自分にだけ表示）。間違いはこのチャンネルで代表へ")
    worth = any((overdue, due_today, due_tomorrow, week, new, done))
    return "\n".join(lines), worth


def _countdown(today: date) -> str:
    try:
        ev = date.fromisoformat(EVENT_DATE)
    except ValueError:
        return ""
    n = (ev - today).days
    if n > 0:
        return f" 🎪 {EVENT_NAME}まであと{n}日"
    if n == 0:
        return f" 🎪 今日は{EVENT_NAME}！"
    return ""


def _chunks(text: str, size: int = 1900) -> list[str]:
    out, buf = [], ""
    for line in text.splitlines(keepends=True):
        if len(buf) + len(line) > size:
            out.append(buf)
            buf = ""
        buf += line
    if buf.strip():
        out.append(buf)
    return out


async def post(text: str, allow_mentions: bool) -> str:
    url = tasks.WEBHOOK_URL
    if not url:
        return "DIGEST_WEBHOOK_URL が設定されていないので投稿できません。"
    async with httpx.AsyncClient(timeout=20) as c:
        chunks = _chunks(text)
        for ch in chunks:
            allowed = {"parse": []}  # @everyone / @here は常に無効
            if allow_mentions:
                allowed["users"] = sorted(set(re.findall(r"<@!?(\d+)>", ch)))[:100]
                allowed["roles"] = sorted(set(re.findall(r"<@&(\d+)>", ch)))[:100]
            r = await c.post(url, json={"content": ch, "username": "ネッコ研タスク係", "allowed_mentions": allowed})
            if r.status_code >= 300:
                return f"投稿に失敗しました（HTTP {r.status_code}）: {r.text[:200]}"
    return f"投稿しました（{len(chunks)}件のメッセージ）"


async def run_daily(force: bool = False) -> str:
    now = datetime.now(JST)
    text, worth = await build(now)
    if not worth and not force:
        result = "期限切れ・締切・増減がないので投稿しませんでした。"
    else:
        result = await post(text, allow_mentions=True)
    if result.startswith("投稿しました"):
        _meta_set("last_digest_at", now.strftime("%Y-%m-%dT%H:%M:%S"))  # 「新しく増えた／完了」の基準時刻
    if not result.startswith("投稿に失敗") and not result.startswith("DIGEST_WEBHOOK_URL"):
        _meta_set("last_digest_date", now.date().isoformat())
    return result


async def scheduler() -> None:
    """1分ごとに見て、DIGEST_TIME を過ぎていて今日まだ投稿していなければ投稿する"""
    hh, mm = (int(x) for x in DIGEST_TIME.split(":"))
    while True:
        try:
            now = datetime.now(JST)
            due = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
            if due <= now and now.hour < LATEST_HOUR and _meta_get("last_digest_date") != now.date().isoformat():
                print(f"[digest] {now:%m/%d %H:%M} {await run_daily()}", flush=True)
        except Exception as e:  # 失敗しても次の周期で再試行
            print(f"[digest] error: {e}", flush=True)
        await asyncio.sleep(60)
