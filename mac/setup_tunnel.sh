#!/bin/bash
# Cloudflare Tunnel で Mac の MCP サーバーを HTTPS 公開する（ログイン中は常駐）
# 前提: Cloudflare に自分のドメインが登録済み（DNS を Cloudflare で管理している）
# 使い方: bash ~/work/discord-mcp/mac/setup_tunnel.sh
set -euo pipefail

reload_agent() {  # 既に読み込み済みでも確実に入れ直す（bootout 直後の bootstrap は error 5 になりがち）
  local label="$1" plist="$2" dom="gui/$(id -u)"
  plutil -lint "$plist" >/dev/null || { echo "plist が不正です: $plist"; return 1; }
  launchctl bootout "$dom/$label" 2>/dev/null || true
  for _ in $(seq 1 20); do launchctl print "$dom/$label" >/dev/null 2>&1 || break; sleep 0.5; done
  launchctl enable "$dom/$label" 2>/dev/null || true
  launchctl bootstrap "$dom" "$plist" 2>/dev/null || { sleep 2; launchctl bootstrap "$dom" "$plist" 2>/dev/null; } \
    || launchctl kickstart -k "$dom/$label"
}

DIR="$(cd "$(dirname "$0")/.." && pwd)"
NAME="discord-mcp"
LABEL="dev.nekko.discord-mcp-tunnel"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
CF="$HOME/.cloudflared"
CONF="$CF/$NAME.yml"   # 既存の config.yml には触らない

echo "== 1/5 cloudflared を確認"
if ! command -v cloudflared >/dev/null 2>&1; then
  if command -v brew >/dev/null 2>&1; then brew install cloudflared
  else echo "Homebrew がありません。https://brew.sh を入れてから再実行してください。"; exit 1; fi
fi
CFBIN="$(command -v cloudflared)"

echo "== 2/5 Cloudflare にログイン"
if [ ! -f "$CF/cert.pem" ]; then
  echo "   ブラウザが開くので、使うドメインを選んで Authorize を押してください。"
  cloudflared tunnel login
else
  echo "   ログイン済み"
fi

read -r -p "== 3/5 公開に使うホスト名（例: discord-mcp.nekko-lab.dev）: " HOST
[ -n "$HOST" ] || { echo "ホスト名が空です"; exit 1; }

echo "== 4/5 トンネルを作成して DNS を設定"
if ! cloudflared tunnel info "$NAME" >/dev/null 2>&1; then
  cloudflared tunnel create "$NAME"
fi
TID="$(cloudflared tunnel list --name "$NAME" --output json | /usr/bin/python3 -c 'import json,sys; print(json.load(sys.stdin)[0]["id"])')"
cloudflared tunnel route dns --overwrite-dns "$NAME" "$HOST"
cat > "$CONF" <<EOF
tunnel: $TID
credentials-file: $CF/$TID.json
ingress:
  - hostname: $HOST
    service: http://127.0.0.1:8000
  - service: http_status:404
EOF

echo "== 5/5 常駐サービスとして登録"
mkdir -p "$DIR/logs"
cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key><array>
    <string>$CFBIN</string><string>tunnel</string><string>--config</string><string>$CONF</string><string>run</string>
  </array>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>ThrottleInterval</key><integer>10</integer>
  <key>StandardOutPath</key><string>$DIR/logs/tunnel.log</string>
  <key>StandardErrorPath</key><string>$DIR/logs/tunnel.log</string>
</dict></plist>
EOF
reload_agent "$LABEL" "$PLIST"

echo "   外から届くか確認しています（DNS 反映に1〜2分かかることがあります）…"
SECRET="$(grep '^MCP_SECRET=' "$DIR/.env" | cut -d= -f2-)"
URL="https://$HOST/$SECRET/mcp"
CODE=""
for i in $(seq 1 24); do
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
else
  echo "❌ まだ外から届きません（HTTP $CODE）。数分待ってからもう一度このスクリプトを実行するか、ログを確認してください:"
  tail -20 "$DIR/logs/tunnel.log"
  exit 1
fi
