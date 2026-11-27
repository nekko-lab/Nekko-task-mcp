#!/bin/bash
# Tailscale Funnel で Mac の MCP サーバーを HTTPS 公開する（ドメイン不要）
# 公開URL: https://<このMacの名前>.<tailnet名>.ts.net/<MCP_SECRET>/mcp
# 使い方: bash ~/work/discord-mcp/mac/setup_funnel.sh
set -euo pipefail

DIR="$(cd "$(dirname "$0")/.." && pwd)"

echo "== 1/4 Tailscale を確認"
TS=""
for c in tailscale /Applications/Tailscale.app/Contents/MacOS/Tailscale; do
  if command -v "$c" >/dev/null 2>&1 || [ -x "$c" ]; then TS="$c"; break; fi
done
if [ -z "$TS" ]; then
  echo "   Tailscale が入っていません。インストールします（パスワードを聞かれたら Mac のログインパスワード）。"
  brew install --cask tailscale-app || brew install --cask tailscale
  TS=/Applications/Tailscale.app/Contents/MacOS/Tailscale
fi
echo "   使用: $TS"

echo "== 2/4 ログイン状態を確認"
if ! "$TS" status >/dev/null 2>&1; then
  echo "   Tailscale アプリを開きます。メニューバーのアイコンから Log in して（Google アカウント等でOK）、"
  echo "   ログインが終わったら Enter を押してください。"
  open -a Tailscale || true
  read -r -p "   ログインできたら Enter: " _
  "$TS" status >/dev/null 2>&1 || { echo "   まだログインできていないようです。ログイン後にもう一度実行してください。"; exit 1; }
fi
NAME="$("$TS" status --json | /usr/bin/python3 -c 'import json,sys; print(json.load(sys.stdin)["Self"]["DNSName"].rstrip("."))')"
echo "   このMacの公開名: $NAME"

echo "== 3/4 Funnel で公開（初回は有効化の確認画面が出ます）"
echo "   『Funnel is not enabled…』と URL が出たら、その URL を開いて Enable を押してください。押すと自動で先に進みます。"
"$TS" funnel --bg 8000

echo "== 4/4 外から届くか確認しています（初回は HTTPS 証明書の発行に1〜2分かかります）…"
SECRET="$(grep '^MCP_SECRET=' "$DIR/.env" | cut -d= -f2-)"
URL="https://$NAME/$SECRET/mcp"
CODE=""
for i in $(seq 1 30); do
  CODE="$(curl -s -o /dev/null -w '%{http_code}' -X POST "$URL" \
    -H 'Content-Type: application/json' -H 'Accept: application/json, text/event-stream' \
    -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"setup-check","version":"1"}}}' || true)"
  [ "$CODE" = "200" ] && break
  sleep 5
done
echo
if [ "$CODE" = "200" ]; then
  echo "✅ HTTPS で公開できました。claude.ai の「設定 → コネクタ → カスタムコネクタを追加」に次の URL を貼ってください:"
  echo
  echo "   $URL"
  echo
  echo "   ※この URL はパスワードと同じです。チャットや Slack に貼らないでください。"
  printf '%s' "$URL" | pbcopy && echo "   （クリップボードにコピー済み）"
  echo "   公開をやめるとき: $TS funnel reset"
else
  echo "❌ まだ外から届きません（HTTP ${CODE}）。"
  echo "   ・000 → 証明書の発行待ちか Funnel が無効。数分後にもう一度このスクリプトを実行"
  echo "   ・502 → MCP サーバーが止まっている。bash $DIR/mac/setup_server.sh を実行"
  "$TS" funnel status || true
  exit 1
fi
