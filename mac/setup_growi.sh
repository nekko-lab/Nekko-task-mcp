#!/bin/bash
# Growi の設定を .env に追加して再起動する
set -euo pipefail
cd "$(dirname "$0")/.."
[ -f .env ] || { echo ".env がありません。先に mac/setup_server.sh を実行してください"; exit 1; }
read -r -p "Growi の URL [https://growi.maruru.me]: " GU; GU=${GU:-https://growi.maruru.me}
read -r -s -p "Growi の APIトークン（表示されません）: " GT; echo
[ -n "$GT" ] || { echo "トークンが空です"; exit 1; }
read -r -p "書き込みを許すパス（カンマ区切り、Enterで全体 /）: " GP; GP=${GP:-/}
code=$(curl -s -o /dev/null -w '%{http_code}' -H "Authorization: Bearer $GT" "$GU/_api/v3/pages/recent?limit=1" || true)
echo "Growi 接続テスト: HTTP $code"
[ "$code" = "200" ] || { echo "→ 200 以外です。URL とトークンを確認してください（.env は変更していません）"; exit 1; }
grep -v '^GROWI_' .env > .env.tmp || true
# 値に空白や ' が入っても source できるよう %q でクォートする
{ cat .env.tmp; printf 'GROWI_URL=%q\nGROWI_API_TOKEN=%q\nGROWI_WRITE_PREFIXES=%q\n' "$GU" "$GT" "$GP"; } > .env
rm -f .env.tmp; chmod 600 .env
launchctl kickstart -k "gui/$(id -u)/dev.nekko.discord-mcp"
sleep 3; echo "再起動しました。Claude のコネクタで growi_ ツールが増えていれば成功です。"
