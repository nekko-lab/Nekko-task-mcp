"""研究会のタスク台帳（SQLite）と、その MCP ツール

- 管理用（代表の Claude・定期実行タスク用）: タスクの追加・更新・一覧、Discord へのまとめ投稿
- メンバー用（読み取り専用）: タスク一覧・自分の担当・近い締切

Discord への投稿は DIGEST_WEBHOOK_URL に設定した Webhook（＝決まった1チャンネル）にだけ行う。
Bot 自体には書き込み権限を持たせない。
"""

from __future__ import annotations

import os
import sqlite3
import unicodedata
from contextlib import closing
from datetime import date, datetime, timedelta, timezone

import httpx
from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

READ = ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=False)
WRITE = ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False)
POST = ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=True)

JST = timezone(timedelta(hours=9))
DB_PATH = os.environ.get("TASK_DB", os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "tasks.db"))
WEBHOOK_URL = os.environ.get("DIGEST_WEBHOOK_URL", "").strip()
TEAMS = ("MO", "NC", "全体")
STATUSES = ("open", "done", "cancelled")

SCHEMA = """
CREATE TABLE IF NOT EXISTS tasks (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  title         TEXT NOT NULL,
  assignee_name TEXT NOT NULL,
  assignee_id   TEXT,
  team          TEXT NOT NULL DEFAULT '全体',
  due           TEXT,              -- 'YYYY-MM-DD' または 'YYYY-MM-DDTHH:MM'（JST）
  status        TEXT NOT NULL DEFAULT 'open',
  source_url    TEXT,
  note          TEXT,
  created_at    TEXT NOT NULL,
  updated_at    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);
CREATE UNIQUE INDEX IF NOT EXISTS idx_tasks_source ON tasks(source_url, title) WHERE source_url IS NOT NULL;
CREATE TABLE IF NOT EXISTS people (      -- Discord で見かけた人（担当者名 → ユーザーID の解決用）
  user_id     TEXT PRIMARY KEY,
  username    TEXT, global_name TEXT, nick TEXT,
  updated_at  TEXT
);
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
"""


def _now() -> str:
    return datetime.now(JST).strftime("%Y-%m-%dT%H:%M:%S")


def _db() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)
    cols = {r[1] for r in con.execute("PRAGMA table_info(tasks)")}
    if "gcal_event_id" not in cols:  # v6 で追加した列
        con.execute("ALTER TABLE tasks ADD COLUMN gcal_event_id TEXT")
        con.commit()
    return con


def _norm(s: str) -> str:
    """名前照合用：全角半角・大小文字・空白・敬称の揺れを吸収"""
    s = unicodedata.normalize("NFKC", s or "").lower()
    for suffix in ("さん", "くん", "君", "ちゃん", "先輩"):
        if s.endswith(suffix):
            s = s[: -len(suffix)]
    return "".join(s.split())


def _check_due(due: str | None) -> str | None:
    if not due:
        return None
    due = due.strip()
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M"):
        try:
            datetime.strptime(due, fmt)
            return due
        except ValueError:
            pass
    raise ValueError("due は 'YYYY-MM-DD' か 'YYYY-MM-DDTHH:MM'（JST）で指定してください")


def _fmt_due(due: str | None) -> str:
    if not due:
        return "期日なし"
    d = datetime.strptime(due[:10], "%Y-%m-%d").date()
    wd = "月火水木金土日"[d.weekday()]
    t = f" {due[11:16]}" if len(due) > 10 else ""
    return f"{d.month}/{d.day}({wd}){t}"


def _render(rows: list[sqlite3.Row], with_id: bool = True) -> str:
    if not rows:
        return "該当するタスクはありません。"
    today = datetime.now(JST).date()
    out = []
    for r in rows:
        mark = ""
        if r["status"] == "open" and r["due"]:
            d = datetime.strptime(r["due"][:10], "%Y-%m-%d").date()
            if d < today:
                mark = "🔥期限切れ "
            elif d == today:
                mark = "📌今日 "
        status = "" if r["status"] == "open" else f"［{'完了' if r['status'] == 'done' else '取り消し'}］"
        head = f"#{r['id']} " if with_id else ""
        line = f"- {head}{mark}{status}【{r['team']}】{r['title']}（担当: {r['assignee_name']}／{_fmt_due(r['due'])}）"
        if r["note"]:
            line += f"\n  メモ: {r['note']}"
        if r["source_url"]:
            line += f"\n  {r['source_url']}"
        out.append(line)
    return "\n".join(out)


def _query(status: str = "open", assignee: str | None = None, team: str | None = None,
           due_within_days: int | None = None) -> list[sqlite3.Row]:
    sql, args = "SELECT * FROM tasks WHERE 1=1", []
    if status != "all":
        sql += " AND status = ?"
        args.append(status)
    if team:
        sql += " AND team = ?"
        args.append(team)
    if due_within_days is not None:
        limit = (datetime.now(JST).date() + timedelta(days=due_within_days)).isoformat()
        sql += " AND due IS NOT NULL AND substr(due,1,10) <= ?"
        args.append(limit)
    sql += " ORDER BY due IS NULL, due, id"
    with closing(_db()) as con:
        rows = con.execute(sql, args).fetchall()
    if assignee:
        key = _norm(assignee)
        rows = [r for r in rows if (r["assignee_id"] and r["assignee_id"] == assignee.strip())
                or key in _norm(r["assignee_name"]) or _norm(r["assignee_name"]) in key]
    return rows


# ---------------------------------------------------------------- 管理用ツール


def register_admin_tools(mcp: FastMCP) -> None:
    @mcp.tool(annotations=WRITE)
    async def task_add(title: str, assignee_name: str, team: str = "全体", due: str | None = None,
                       assignee_id: str | None = None, source_url: str | None = None,
                       note: str | None = None) -> str:
        """研究会のタスク台帳にタスクを追加する。
        assignee_name: 担当者の表示名（Discord の表示名。複数人なら「くしもち・鈴木」のように）
        team: MO / NC / 全体
        due: 'YYYY-MM-DD' または 'YYYY-MM-DDTHH:MM'（JST）
        assignee_id: 担当者の Discord ユーザーID（分かれば。複数人はカンマ区切りで assignee_name と同じ順）。
                     省略しても、まとめ投稿のメンション時に表示名から自動で探す。「MO全員」は @MO ロールになる
        source_url: 根拠となる Discord メッセージのリンク（同じリンク＋同じタイトルの重複登録は自動で防ぐ）"""
        if team not in TEAMS:
            raise ValueError(f"team は {' / '.join(TEAMS)} のどれか")
        due = _check_due(due)
        now = _now()
        with closing(_db()) as con:
            if source_url:
                dup = con.execute("SELECT id FROM tasks WHERE source_url=? AND title=?", (source_url, title)).fetchone()
                if dup:
                    return f"既に登録済みです（#{dup['id']}）"
            cur = con.execute(
                "INSERT INTO tasks(title, assignee_name, assignee_id, team, due, source_url, note, created_at, updated_at)"
                " VALUES (?,?,?,?,?,?,?,?,?)",
                (title.strip(), assignee_name.strip(), assignee_id, team, due, source_url, note, now, now))
            con.commit()
            new_id = cur.lastrowid
        import gcal
        return f"登録しました: #{new_id} 【{team}】{title}（担当: {assignee_name}／{_fmt_due(due)}）" + await gcal.try_sync(new_id)

    @mcp.tool(annotations=WRITE)
    async def task_update(task_id: int, status: str | None = None, due: str | None = None,
                          assignee_name: str | None = None, assignee_id: str | None = None,
                          title: str | None = None, note: str | None = None, team: str | None = None) -> str:
        """タスクを更新する。status は open / done / cancelled。指定した項目だけ変わる。
        due を消したいときは due に 'none' を渡す。"""
        fields: dict[str, object] = {}
        if status is not None:
            if status not in STATUSES:
                raise ValueError("status は open / done / cancelled")
            fields["status"] = status
        if due is not None:
            fields["due"] = None if due.lower() == "none" else _check_due(due)
        if team is not None:
            if team not in TEAMS:
                raise ValueError(f"team は {' / '.join(TEAMS)} のどれか")
            fields["team"] = team
        for k, v in (("assignee_name", assignee_name), ("assignee_id", assignee_id), ("title", title), ("note", note)):
            if v is not None:
                fields[k] = v
        if not fields:
            return "変更する項目がありません。"
        fields["updated_at"] = _now()
        with closing(_db()) as con:
            cur = con.execute(f"UPDATE tasks SET {', '.join(f'{k}=?' for k in fields)} WHERE id=?",
                              (*fields.values(), task_id))
            con.commit()
            if cur.rowcount == 0:
                return f"#{task_id} は見つかりません。"
            row = con.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
        import gcal
        return "更新しました:\n" + _render([row]) + await gcal.try_sync(task_id)

    @mcp.tool(annotations=READ)
    async def task_list(status: str = "open", assignee: str | None = None, team: str | None = None,
                        due_within_days: int | None = None) -> str:
        """タスク台帳を一覧する（ID付き）。status: open / done / cancelled / all。
        assignee は表示名の一部でも可。due_within_days を指定すると、その日数以内が期日のもの（期限切れ含む）だけ。"""
        return _render(_query(status, assignee, team, due_within_days))

    @mcp.tool(annotations=POST)
    async def post_digest(text: str) -> str:
        """研究会の Discord の決まったチャンネル（Webhook で設定済み）にまとめを投稿する。
        メンション（@everyone や <@id>）は送られても通知が飛ばない設定で投稿する。2000文字を超える場合は分割する。"""
        if not WEBHOOK_URL:
            return "DIGEST_WEBHOOK_URL が設定されていないので投稿できません。"
        chunks, buf = [], ""
        for line in text.splitlines(keepends=True):
            if len(buf) + len(line) > 1900:
                chunks.append(buf)
                buf = ""
            buf += line
        if buf.strip():
            chunks.append(buf)
        async with httpx.AsyncClient(timeout=20) as c:
            for ch in chunks:
                r = await c.post(WEBHOOK_URL, json={
                    "content": ch,
                    "username": "ネッコ研タスク係",
                    "allowed_mentions": {"parse": []},  # 誰にも通知を飛ばさない
                })
                if r.status_code >= 300:
                    return f"投稿に失敗しました（HTTP {r.status_code}）: {r.text[:200]}"
        return f"投稿しました（{len(chunks)}件のメッセージ）"


    @mcp.tool(annotations=READ)
    async def preview_daily_digest() -> str:
        """毎朝サーバーが自動投稿するまとめ（台帳から作る）を、投稿せずに見る。メンションは <@ID> の形で表示される。"""
        import digest
        text, worth = await digest.build()
        last = digest._meta_get("last_digest_at") or "まだなし"
        return (f"（前回の自動投稿: {last}／毎朝 {digest.DIGEST_TIME} に自動投稿）\n"
                + ("" if worth else "※いま投稿しても内容がないので、自動投稿ではスキップされます\n") + "\n" + text)

    @mcp.tool(annotations=POST)
    async def post_daily_digest() -> str:
        """【書き込み・要承認】毎朝の自動まとめを今すぐ投稿する（期限切れ・今日・明日までの担当者にメンションが飛ぶ）。
        普段はサーバーが毎朝自動で投稿するので呼ばなくてよい。"""
        import digest
        return await digest.run_daily(force=True)


# ---------------------------------------------------------------- メンバー用（読み取り専用）

member_mcp = FastMCP(
    "nekko-tasks",
    instructions=(
        "ネットワークコンテンツ研究会（ネッコ研）のタスク台帳を読み取り専用で見るツール。"
        "タスクの追加・変更はできない。変更したいときは Discord で代表に伝えること。"
        "Growi（研究会wiki）の検索・閲覧もできる。"
    ),
    host="0.0.0.0",
    stateless_http=True,
)


@member_mcp.tool(annotations=READ)
async def my_tasks(name: str, include_done: bool = False) -> str:
    """自分（name：Discord の表示名。一部でも可）が担当の研究会タスクを、期日の近い順に返す。"""
    rows = _query("all" if include_done else "open", assignee=name)
    return f"{name} の担当タスク:\n" + _render(rows, with_id=False)


@member_mcp.tool(annotations=READ)
async def list_tasks(team: str | None = None, assignee: str | None = None) -> str:
    """研究会の未完了タスクを一覧する。team: MO / NC / 全体（省略で全部）、assignee: 担当者名（一部でも可）。"""
    return _render(_query("open", assignee, team), with_id=False)


@member_mcp.tool(annotations=READ)
async def upcoming_deadlines(days: int = 7) -> str:
    """今日から days 日以内が期日の未完了タスク（期限切れを含む）を返す。"""
    rows = _query("open", due_within_days=max(0, min(days, 60)))
    return f"{days}日以内の締切:\n" + _render(rows, with_id=False)
