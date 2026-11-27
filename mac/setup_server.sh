#!/bin/bash
# Discord MCP サーバーを Mac に常駐させる（ログイン中は自動起動・落ちても再起動）
# 使い方: bash ~/work/discord-mcp/mac/setup_server.sh
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
LABEL="dev.nekko.discord-mcp"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
cd "$DIR"

echo "== 1/4 Python を確認"
PY=""
for c in python3.13 python3.12 python3.11 python3.10 python3 "$HOME/.pyenv/shims/python3"; do
  if command -v "$c" >/dev/null 2>&1 && "$c" -c 'import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)' 2>/dev/null; then
    PY="$(command -v "$c")"; break
  fi
done
if [ -z "$PY" ]; then
  echo "Python 3.10 以上が見つかりません。'brew install python@3.12' を実行してから、もう一度このスクリプトを実行してください。"
  exit 1
fi
echo "   使用: $PY ($("$PY" --version))"

echo "== 2/4 依存パッケージをインストール"
[ -d .venv ] || "$PY" -m venv .venv
.venv/bin/pip install -q --upgrade pip
.venv/bin/pip install -q -r requirements.txt

echo "== 3/4 設定（.env）"
if [ -f .env ]; then
  echo "   既存の .env を使います（作り直すなら .env を消してから再実行）"
else
  echo "   Discord Developer Portal で控えた値を入力してください。"
  read -r -s -p "   Bot トークン（入力は表示されません）: " TOKEN; echo
  read -r -p "   サーバーID（ネットワークコンテンツ研究会）: " GUILD
  read -r -p "   自分のユーザーID: " ME
  read -r -p "   読ませたくないチャンネルID（任意・カンマ区切り、なければ Enter）: " EXCL
  SECRET="$("$PY" -c 'import secrets; print(secrets.token_urlsafe(32))')"
  umask 077
  cat > .env <<EOF
DISCORD_BOT_TOKEN=$TOKEN
ALLOWED_GUILD_IDS=$GUILD
OWNER_USER_ID=$ME
EXCLUDED_CHANNEL_IDS=$EXCL
MCP_SECRET=$SECRET
BIND_HOST=127.0.0.1
PORT=8000
EOF
  chmod 600 .env
  echo "   .env を作成しました（自分だけが読める権限）"
fi

echo "== 4/4 常駐サービスとして登録"
mkdir -p logs "$HOME/Library/LaunchAgents"
cat > run.sh <<'EOF'
#!/bin/bash
cd "$(dirname "$0")"
set -a; source .env; set +a
exec .venv/bin/python server.py
EOF
chmod 700 run.sh
cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key><array><string>/bin/bash</string><string>$DIR/run.sh</string></array>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>ThrottleInterval</key><integer>10</integer>
  <key>StandardOutPath</key><string>$DIR/logs/server.log</string>
  <key>StandardErrorPath</key><string>$DIR/logs/server.log</string>
</dict></plist>
EOF
reload_agent "$LABEL" "$PLIST"

echo "   起動を確認しています…"
SECRET="$(grep '^MCP_SECRET=' .env | cut -d= -f2-)"
for i in $(seq 1 15); do
  CODE="$(curl -s -o /dev/null -w '%{http_code}' -X POST "http://127.0.0.1:8000/$SECRET/mcp" \
    -H 'Content-Type: application/json' -H 'Accept: application/json, text/event-stream' \
    -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"setup-check","version":"1"}}}' || true)"
  [ "$CODE" = "200" ] && break
  sleep 1
done
if [ "$CODE" = "200" ]; then
  echo
  echo "✅ MCP サーバーが起動しました（http://127.0.0.1:8000、Mac の中からだけ接続可）"
  echo "   次は: bash $DIR/mac/setup_tunnel.sh"
else
  echo
  echo "❌ 起動を確認できませんでした（HTTP $CODE）。ログの末尾:"
  tail -20 logs/server.log
  exit 1
fi
