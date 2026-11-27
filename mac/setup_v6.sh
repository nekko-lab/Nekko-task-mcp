#!/bin/bash
# v6 の設定：スラッシュコマンド /タスク・Google カレンダー・毎朝の自動まとめ
# 何度実行しても OK（空 Enter の項目は今の設定のまま）
set -euo pipefail
cd "$(dirname "$0")/.."
[ -f .env ] || { echo ".env がありません。先に mac/setup_server.sh を実行してください"; exit 1; }
./.venv/bin/pip install -q -r requirements.txt

setv() {  # .env の KEY を置き換える（値は %q でクォート）
  grep -v "^$1=" .env > .env.tmp || true
  { cat .env.tmp; printf '%s=%q\n' "$1" "$2"; } > .env; rm -f .env.tmp; chmod 600 .env
}

echo "== 1. Discord のスラッシュコマンド /タスク"
echo "   Developer Portal → あなたのアプリ → General Information を開いてください"
read -r -p "   APPLICATION ID（空Enterでスキップ）: " APP
if [ -n "$APP" ]; then
  read -r -p "   PUBLIC KEY: " PK
  [[ "$PK" =~ ^[0-9a-fA-F]{64}$ ]] || { echo "   PUBLIC KEY は64文字の16進数です"; exit 1; }
  setv DISCORD_APP_ID "$APP"; setv DISCORD_PUBLIC_KEY "$PK"
  INVITE="https://discord.com/oauth2/authorize?client_id=$APP&scope=bot+applications.commands&permissions=66560"
fi

echo; echo "== 2. Google カレンダー（サービスアカウント）"
read -r -p "   ダウンロードした鍵JSONのパス（Finderからドラッグでも可。空Enterでスキップ）: " SA
SA="${SA%\"}"; SA="${SA#\"}"; SA="${SA%\'}"; SA="${SA#\'}"; SA="${SA% }"
if [ -n "$SA" ]; then
  [ -f "$SA" ] || { echo "   ファイルが見つかりません: $SA"; exit 1; }
  mkdir -p secrets && chmod 700 secrets && cp "$SA" secrets/gcal.json && chmod 600 secrets/gcal.json
  setv GCAL_SERVICE_ACCOUNT_FILE "$PWD/secrets/gcal.json"
  EMAIL=$(python3 -c 'import json;print(json.load(open("secrets/gcal.json"))["client_email"])')
  echo "   サービスアカウント: $EMAIL"
  echo "   → 研究会の Google カレンダーの「設定と共有 → 特定のユーザーと共有」にこのアドレスを"
  echo "     「予定の変更」権限で追加してください（タスク用・予定用の両方）"
  read -r -p "   タスク用カレンダーのID（設定 → カレンダーの統合 → カレンダーID）: " TC
  [ -n "$TC" ] && setv GCAL_TASK_CALENDAR_ID "$TC"
  read -r -p "   予定用カレンダーのID（任意・空Enterでなし）: " EC
  [ -n "$EC" ] && setv GCAL_EVENT_CALENDAR_ID "$EC"
  echo "   ※元の鍵ファイル（${SA}）は消して大丈夫です（コピー済み）"
fi

echo; echo "== 3. 毎朝の自動まとめ"
read -r -p "   投稿時刻 [09:00]: " DT; DT=${DT:-09:00}
[[ "$DT" =~ ^[0-2][0-9]:[0-5][0-9]$ ]] || { echo "   HH:MM で入力してください"; exit 1; }
setv DIGEST_TIME "$DT"
read -r -p "   まとめに付けるカレンダー追加リンク（空Enterでなし）: " CU
[ -n "$CU" ] && setv DIGEST_CALENDAR_URL "$CU"

launchctl kickstart -k "gui/$(id -u)/dev.nekko.discord-mcp"
sleep 4
echo; echo "再起動しました。"
TS=$(command -v tailscale || echo /Applications/Tailscale.app/Contents/MacOS/Tailscale)
HOST=$("$TS" status --json 2>/dev/null | python3 -c 'import json,sys;print(json.load(sys.stdin)["Self"]["DNSName"].rstrip("."))' 2>/dev/null || echo "<あなたのFunnelのホスト名>")
if [ -n "${APP:-}" ]; then
  echo
  echo "★ 残りの手順（Discord）"
  echo "  1) Bot をコマンド権限つきで招待し直す（チャンネル権限は今のまま）:"
  echo "     $INVITE"
  echo "  2) Developer Portal → General Information → INTERACTIONS ENDPOINT URL に貼って保存:"
  echo "     https://$HOST/discord/interactions"
  echo "  3) サーバーを再起動して /タスク を登録: launchctl kickstart -k gui/$(id -u)/dev.nekko.discord-mcp"
fi
LOG=$(ls -t logs/*.log 2>/dev/null | head -1 || true)
[ -n "$LOG" ] && { echo; echo "== 最近のログ"; grep -E "\[(digest|slash)\]" "$LOG" | tail -5 || true; }
