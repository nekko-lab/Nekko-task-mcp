#!/bin/bash
# 研究会タスク台帳を有効にする：メンバー用URLの発行と、Discord まとめ投稿用 Webhook の設定
# 使い方: bash ~/work/discord-mcp/mac/setup_tasks.sh
set -euo pipefail
DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$DIR"
[ -f .env ] || { echo ".env がありません。先に setup_server.sh を実行してください"; exit 1; }
PY=.venv/bin/python

echo "== 1/3 メンバー用URLの秘密文字列"
if grep -q '^MEMBER_SECRET=.\+' .env; then
  echo "   既に設定済み（作り直すなら .env の MEMBER_SECRET 行を消して再実行）"
else
  MS="$($PY -c 'import secrets; print(secrets.token_urlsafe(32))')"
  sed -i '' '/^MEMBER_SECRET=/d' .env; echo "MEMBER_SECRET=$MS" >> .env
  echo "   発行しました"
fi

echo "== 2/3 まとめ投稿用の Discord Webhook"
if grep -q '^DIGEST_WEBHOOK_URL=.\+' .env; then
  echo "   既に設定済み"
else
  echo "   投稿したいチャンネルの「チャンネルの編集 → 連携サービス → ウェブフック → 新しいウェブフック」で作り、"
  echo "   「ウェブフックURLをコピー」したものを貼ってください（表示はされません。後で設定するなら Enter）"
  read -r -s -p "   Webhook URL: " WH; echo
  if [ -n "$WH" ]; then
    case "$WH" in https://discord.com/api/webhooks/*|https://discordapp.com/api/webhooks/*) ;; *) echo "   Discord の Webhook URL ではないようです"; exit 1;; esac
    sed -i '' '/^DIGEST_WEBHOOK_URL=/d' .env; echo "DIGEST_WEBHOOK_URL=$WH" >> .env
    echo "   設定しました"
  fi
fi
chmod 600 .env
mkdir -p data

echo "== 3/3 再起動して確認"
launchctl kickstart -k "gui/$(id -u)/dev.nekko.discord-mcp"
MS="$(grep '^MEMBER_SECRET=' .env | cut -d= -f2-)"
NAME="$(/Applications/Tailscale.app/Contents/MacOS/Tailscale status --json 2>/dev/null | /usr/bin/python3 -c 'import json,sys; print(json.load(sys.stdin)["Self"]["DNSName"].rstrip("."))' 2>/dev/null || true)"
CODE=""
for i in $(seq 1 15); do
  CODE="$(curl -s -o /dev/null -w '%{http_code}' -X POST "http://127.0.0.1:8000/$MS/mcp" \
    -H 'Content-Type: application/json' -H 'Accept: application/json, text/event-stream' \
    -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"setup-check","version":"1"}}}' || true)"
  [ "$CODE" = "200" ] && break; sleep 1
done
if [ "$CODE" != "200" ]; then echo "❌ 起動を確認できませんでした（HTTP $CODE）"; tail -20 logs/server.log; exit 1; fi
echo
echo "✅ タスク台帳が有効になりました"
if [ -n "$NAME" ]; then
  URL="https://$NAME/$MS/mcp"
  printf '%s' "$URL" | pbcopy
  echo "   メンバー用URL（クリップボードにコピー済み）。Discord のメンバー向け案内に貼って共有してください:"
  echo "   $URL"
  echo "   ※このURLでできるのは研究会タスクの閲覧だけです（Discordのメッセージは読めません）"
fi
