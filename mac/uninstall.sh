#!/bin/bash
# 常駐を止めて登録を外す（ファイルとトンネル自体は残す）
for L in dev.nekko.discord-mcp dev.nekko.discord-mcp-tunnel; do
  launchctl bootout "gui/$(id -u)/$L" 2>/dev/null && echo "停止: $L"
  rm -f "$HOME/Library/LaunchAgents/$L.plist"
done
echo "完了。Cloudflare 側のトンネルも消すなら: cloudflared tunnel delete discord-mcp"
