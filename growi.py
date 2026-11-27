"""Growi（研究会の wiki）の MCP ツール

権限の方針（研究会の決定）:
- 読み取り … 許可（readOnlyHint=True）
- 書き込み … 承認制（ページの作成・追記・更新。readOnlyHint=False）
              → Claude の「コネクタ設定 → ツールの権限」で「承認が必要」にして使う
- 削除     … 拒否（削除・移動・リネームのツールはそもそも実装していない。
              本文を空にする更新、本文の大半を消す更新もサーバー側で拒否する）

必要な環境変数:
  GROWI_URL            例 https://growi.maruru.me
  GROWI_API_TOKEN      Growi の「ユーザー設定 → API設定」で発行したアクセストークン
任意:
  GROWI_WRITE_PREFIXES 書き込みを許すページパスの接頭辞（カンマ区切り、既定 "/"＝全体）
                       例 "/Miku's Origin/,/Nekko Cloud/,/議事録/"
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

import httpx
from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

JST = timezone(timedelta(hours=9))
READ = ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=False)
WRITE = ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False)
OVERWRITE = ToolAnnotations(readOnlyHint=False, destructiveHint=True, idempotentHint=False, openWorldHint=False)

MAX_BODY_CHARS = 30000  # 1ページあたり Claude に返す本文の上限


def _cfg() -> tuple[str, str]:
    url = os.environ.get("GROWI_URL", "").rstrip("/")
    token = os.environ.get("GROWI_API_TOKEN", "").strip()
    if not url or not token:
        raise RuntimeError("GROWI_URL / GROWI_API_TOKEN が設定されていません")
    return url, token


def enabled() -> bool:
    return bool(os.environ.get("GROWI_URL") and os.environ.get("GROWI_API_TOKEN"))


def _write_prefixes() -> list[str]:
    raw = os.environ.get("GROWI_WRITE_PREFIXES", "/")
    return [p.strip() for p in raw.split(",") if p.strip()] or ["/"]


def _check_writable(path: str) -> str:
    path = "/" + path.strip().lstrip("/")
    if ".." in path.split("/"):
        raise ValueError("パスに .. は使えません")
    if not any(path.startswith(p) for p in _write_prefixes()):
        raise ValueError(f"このパスへの書き込みは許可されていません（許可: {', '.join(_write_prefixes())}）")
    return path


async def _req(method: str, endpoint: str, *, params: dict | None = None, json: dict | None = None):
    url, token = _cfg()
    # トークンはアクセスログに残らないよう、クエリではなくヘッダで送る（研究会サイトの実装と同じ）
    async with httpx.AsyncClient(timeout=20, headers={"Authorization": f"Bearer {token}"}) as c:
        r = await c.request(method, f"{url}{endpoint}", params=params, json=json)
    if r.status_code in (401, 403):
        raise RuntimeError(f"Growi に拒否されました（{r.status_code}）。トークンの権限を確認してください")
    if r.status_code == 404:
        return None
    if r.status_code >= 400:
        raise RuntimeError(f"Growi エラー（{r.status_code}）: {r.text[:300]}")
    return r.json()


def _page_url(path_or_id: str) -> str:
    url, _ = _cfg()
    return f"{url}{path_or_id if path_or_id.startswith('/') else '/' + path_or_id}"


def _when(iso: str | None) -> str:
    if not iso:
        return ""
    try:
        return datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone(JST).strftime("%Y/%m/%d %H:%M")
    except ValueError:
        return iso


def _fmt_list(pages: list[dict]) -> str:
    if not pages:
        return "ページはありません。"
    return "\n".join(f"- {p.get('path')}（更新 {_when(p.get('updatedAt'))}）\n  {_page_url(p.get('_id', ''))}" for p in pages)


async def _get_page(path: str | None = None, page_id: str | None = None) -> dict | None:
    params = {"pageId": page_id} if page_id else {"path": "/" + (path or "").lstrip("/")}
    data = await _req("GET", "/_api/v3/page", params=params)
    return (data or {}).get("page")


def register_growi_tools(mcp: FastMCP, allow_write: bool) -> None:
    """Growi のツールを mcp に登録する。allow_write=False なら読み取りだけ。"""

    @mcp.tool(annotations=READ)
    async def growi_search(query: str, limit: int = 10) -> str:
        """Growi を全文検索する（ページパスと、一致した箇所の抜粋を返す）。"""
        data = await _req("GET", "/_api/search", params={"q": query, "limit": max(1, min(limit, 30))}) or {}
        items = data.get("data") or []
        if not items:
            return f"「{query}」に一致するページはありません。"
        out = []
        for it in items:
            p = it.get("data", it)
            meta = it.get("meta") or {}
            snippet = ""
            hl = (meta.get("elasticSearchResult") or {}).get("snippet") or (meta.get("elasticSearchResult") or {}).get("highlightedPath")
            if hl:
                snippet = "\n  …" + str(hl).replace("<em class='highlighted-keyword'>", "【").replace("</em>", "】")[:200]
            out.append(f"- {p.get('path')}（更新 {_when(p.get('updatedAt'))}）{snippet}\n  {_page_url(p.get('_id', ''))}")
        total = (data.get("meta") or {}).get("total")
        return (f"{total}件中 {len(items)}件:\n" if total else "") + "\n".join(out)

    @mcp.tool(annotations=READ)
    async def growi_read_page(path: str | None = None, page_id: str | None = None) -> str:
        """Growi のページ本文（Markdown）を読む。path（例 "/Miku's Origin/MO17/MO会議/20261028 第24回"）か page_id を指定。"""
        if not path and not page_id:
            return "path か page_id を指定してください。"
        page = await _get_page(path, page_id)
        if not page:
            return "ページが見つかりません（パスの綴り、または閲覧権限を確認してください）。"
        body = (page.get("revision") or {}).get("body", "")
        cut = "\n\n…（長いので途中まで）" if len(body) > MAX_BODY_CHARS else ""
        return (f"# {page.get('path')}\n更新: {_when(page.get('updatedAt'))}　{_page_url(page.get('_id', ''))}\n\n"
                f"{body[:MAX_BODY_CHARS]}{cut}")

    @mcp.tool(annotations=READ)
    async def growi_list_pages(path: str = "/", limit: int = 50) -> str:
        """指定したパスの配下にあるページ一覧を返す（例 "/Miku's Origin/MO17/MO会議"）。"""
        data = await _req("GET", "/_api/v3/pages/list",
                          params={"path": "/" + path.lstrip("/"), "page": 1, "limit": max(1, min(limit, 100))}) or {}
        pages = data.get("pages") or []
        total = data.get("totalCount")
        return (f"{path} の配下（{total}件中 {len(pages)}件）:\n" if total else "") + _fmt_list(pages)

    @mcp.tool(annotations=READ)
    async def growi_recent_pages(limit: int = 20) -> str:
        """最近更新された Growi のページを新しい順に返す。"""
        data = await _req("GET", "/_api/v3/pages/recent", params={"limit": max(1, min(limit, 50)), "offset": 0}) or {}
        return _fmt_list(data.get("pages") or [])

    if not allow_write:
        return

    @mcp.tool(annotations=WRITE)
    async def growi_create_page(path: str, body: str) -> str:
        """【書き込み・要承認】Growi に新しいページを作る。同じパスのページが既にあれば作らない。"""
        path = _check_writable(path)
        if not body.strip():
            raise ValueError("本文が空のページは作れません")
        if await _get_page(path):
            return f"既に同じパスのページがあります: {_page_url(path)}（追記は growi_append_to_page を使う）"
        data = await _req("POST", "/_api/v3/page", json={"path": path, "body": body}) or {}
        page = data.get("page") or {}
        return f"作成しました: {page.get('path', path)}\n{_page_url(page.get('_id') or path)}"

    @mcp.tool(annotations=WRITE)
    async def growi_append_to_page(path: str, text: str) -> str:
        """【書き込み・要承認】既存ページの末尾に追記する（既存の本文は消さない）。"""
        path = _check_writable(path)
        if not text.strip():
            raise ValueError("追記する内容が空です")
        page = await _get_page(path)
        if not page:
            return "ページが見つかりません。新しく作るなら growi_create_page を使ってください。"
        rev = page.get("revision") or {}
        new_body = rev.get("body", "").rstrip("\n") + "\n\n" + text.strip("\n") + "\n"
        await _req("PUT", "/_api/v3/page", json={"pageId": page["_id"], "revisionId": rev.get("_id"), "body": new_body})
        return f"追記しました: {page.get('path')}\n{_page_url(page['_id'])}"

    @mcp.tool(annotations=OVERWRITE)
    async def growi_update_page(path: str, body: str) -> str:
        """【書き込み・要承認】既存ページの本文を書き換える（変更履歴は Growi に残る）。
        削除に当たる操作は拒否：本文を空にする更新、元の本文の半分以上を消す更新はできない。"""
        path = _check_writable(path)
        page = await _get_page(path)
        if not page:
            return "ページが見つかりません。"
        rev = page.get("revision") or {}
        old = rev.get("body", "")
        if not body.strip():
            raise ValueError("本文を空にする更新はできません（削除は許可されていません）")
        if len(old) > 200 and len(body) < len(old) * 0.5:
            raise ValueError("元の本文の半分以上を消す更新はできません（削除は許可されていません）。必要なら Growi で直接編集してください")
        await _req("PUT", "/_api/v3/page", json={"pageId": page["_id"], "revisionId": rev.get("_id"), "body": body})
        return f"更新しました: {page.get('path')}（{len(old)}字 → {len(body)}字）\n{_page_url(page['_id'])}"
