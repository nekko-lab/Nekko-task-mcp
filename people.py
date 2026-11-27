"""担当者名 ↔ Discord ユーザーID / ロールID の対応づけ

- Discord のメッセージを読むたびに、発言者・メンションされた人を people テーブルに覚えておく
- 担当者名「くしもち・鈴木 椋大」「MO全員」などを分解して、ユーザー or ロールに解決する
  「◯◯全員」は ◯◯ という名前のロールとして扱う（例: MO全員 → @MO）
"""

from __future__ import annotations

import re
import sys
from contextlib import closing
from typing import Iterable

import tasks


def _srv():
    return sys.modules["server"]


def split_assignees(name: str) -> list[str]:
    return [t.strip() for t in re.split(r"[・、,，/／]", name or "") if t.strip()]


def remember(users: Iterable[dict], nick_of: dict[str, str] | None = None) -> None:
    rows = []
    for u in users:
        if not u or not u.get("id") or u.get("bot"):
            continue
        rows.append((u["id"], u.get("username") or "", u.get("global_name") or "",
                     (nick_of or {}).get(u["id"]) or ""))
    if not rows:
        return
    with closing(tasks._db()) as con:
        con.executemany(
            "INSERT INTO people(user_id, username, global_name, nick, updated_at) VALUES (?,?,?,?,datetime('now'))"
            " ON CONFLICT(user_id) DO UPDATE SET username=excluded.username,"
            " global_name=CASE WHEN excluded.global_name<>'' THEN excluded.global_name ELSE people.global_name END,"
            " nick=CASE WHEN excluded.nick<>'' THEN excluded.nick ELSE people.nick END,"
            " updated_at=excluded.updated_at", rows)
        con.commit()


def _names(row) -> set[str]:
    return {tasks._norm(x) for x in (row["username"], row["global_name"], row["nick"]) if x}


def lookup_cached(token: str) -> str | None:
    key = tasks._norm(token)
    if not key:
        return None
    with closing(tasks._db()) as con:
        rows = con.execute("SELECT * FROM people").fetchall()
    exact = [r["user_id"] for r in rows if key in _names(r)]
    if len(exact) == 1:
        return exact[0]
    # 「鈴木」→「鈴木 椋大」のような部分一致は、1人に絞れるときだけ
    if len(key) < 3:
        return None
    part = [r["user_id"] for r in rows if any(key in n or n in key for n in _names(r) if len(n) >= 3)]
    return part[0] if len(set(part)) == 1 else None


async def lookup(gid: str, token: str) -> str | None:
    uid = lookup_cached(token)
    if uid:
        return uid
    srv = _srv()
    try:
        found = await srv.discord().get(f"/guilds/{gid}/members/search", {"query": token[:32], "limit": 5}) or []
    except Exception:
        return None
    if found:
        remember([m["user"] for m in found], {m["user"]["id"]: m.get("nick") or "" for m in found})
        key = tasks._norm(token)
        hits = [m["user"]["id"] for m in found
                if key in {tasks._norm(x) for x in (m.get("nick"), m["user"].get("global_name"), m["user"].get("username")) if x}]
        if len(hits) == 1:
            return hits[0]
        if len(found) == 1:
            return found[0]["user"]["id"]
    return None


async def role_ids_by_name(gid: str) -> dict[str, str]:
    roles = await _srv().guild_roles(gid)
    return {tasks._norm(name): rid for rid, name in roles.items() if name != "@everyone"}


async def resolve(gid: str, assignee_name: str, assignee_id: str | None = None) -> list[tuple[str, str, str]]:
    """担当者名を [(kind, id, 表示名)] に。kind は user / role / text"""
    ids = [x.strip() for x in (assignee_id or "").split(",") if x.strip().isdigit()]
    roles = None
    out = []
    for i, tok in enumerate(split_assignees(assignee_name)):
        if tok.endswith("全員") and len(tok) > 2:
            roles = roles if roles is not None else await role_ids_by_name(gid)
            rid = roles.get(tasks._norm(tok[:-2]))
            out.append(("role", rid, tok) if rid else ("text", "", tok))
            continue
        uid = ids[i] if i < len(ids) else await lookup(gid, tok)
        out.append(("user", uid, tok) if uid else ("text", "", tok))
    return out


def matches_member(assignee_name: str, assignee_id: str | None, uid: str, member_names: set[str],
                   member_role_names: set[str]) -> bool:
    """/タスク 自分 用：このタスクがこの人の担当か"""
    if uid in [x.strip() for x in (assignee_id or "").split(",")]:
        return True
    for tok in split_assignees(assignee_name):
        if tok.endswith("全員") and tasks._norm(tok[:-2]) in member_role_names:
            return True
        key = tasks._norm(tok)
        if key and (key in member_names or lookup_cached(tok) == uid):
            return True
    return False
