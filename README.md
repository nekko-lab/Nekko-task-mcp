# Discord 読み取り専用 MCP サーバー

ネットワークコンテンツ研究会の Discord を Claude から読むためのサーバーです。

- **読み取り専用**：メッセージ送信・削除・リアクションなどの機能はありません。
- **読めるのは許可したサーバーだけ**（`ALLOWED_GUILD_IDS`）。さらに `EXCLUDED_CHANNEL_IDS` で個別に除外できます。Bot に見えないチャンネルはそもそも読めません。
- **接続URLに秘密文字列を含める方式**：`https://<ドメイン>/<MCP_SECRET>/mcp`。このURLを知っている人だけが使えます。URLはパスワードと同じ扱いにしてください。アクセスログは出しません。

## Claude から使えるツール

| ツール | 内容 |
|---|---|
| `list_channels` | 読めるチャンネル・スレッドの一覧 |
| `recent_messages` | サーバー全体の直近 N 時間のメッセージ（キーワード絞り込み可） |
| `read_channel` | 指定チャンネル／スレッドの直近 N 時間 |
| `get_my_mentions` | 自分宛て・自分のロール宛て・@everyone・自分への返信 |
| `list_scheduled_events` | サーバーの「イベント」に登録された予定 |
| `get_pinned_messages` | ピン留め（決定事項・締切がまとまりがち） |
| `task_add` / `task_update` / `task_list` / `post_digest` | 研究会タスク台帳と Discord へのまとめ投稿（管理用URLのみ） |
| `growi_search` / `growi_read_page` / `growi_list_pages` / `growi_recent_pages` | Growi の検索・閲覧（読み取り） |
| `growi_create_page` / `growi_append_to_page` / `growi_update_page` | Growi への書き込み（管理用URLのみ・要承認） |

| `preview_daily_digest` / `post_daily_digest` | 毎朝の自動まとめの確認／今すぐ投稿 |
| `calendar_list_events` / `calendar_create_event` / `calendar_update_event` / `calendar_sync_tasks` | 研究会の Google カレンダー（削除なし） |

### v6 で増えたもの
- **毎朝の自動まとめ**（digest.py）：サーバーが DIGEST_TIME（既定 9:00）に台帳から作って投稿。期限切れ・今日・明日までの担当者にメンション（1人1回、「MO全員」は @MO ロール）。@everyone/@here は常に無効。
- **カレンダー自動反映**（gcal.py）：task_add / task_update のたびに「ネッコ研 タスク」カレンダーへ作成・更新。完了は ✅、取消は ❌ を件名に付け、削除はしない。サービスアカウントで動くので個人アカウント不要。
- **/タスク コマンド**（slash.py）：自分 / 一覧 / 締切。本人にだけ表示、署名検証つき、読み取りのみ。
- 設定は `mac/setup_v6.sh`。

### 権限の方針（読み取り＝許可／書き込み＝承認／削除＝拒否）
- 読み取りツールには `readOnlyHint`、書き込みツールには付けていないので、Claude のコネクタ設定で
  読み取り＝「常に許可」、書き込み＝「承認が必要」に分けて設定する。
- 削除・移動・リネームのツールは実装していない。Growi の更新でも「本文を空にする」「本文の半分以上を消す」はサーバー側で拒否。
- Discord は Bot に閲覧権限しか与えていないので書き込み不可。投稿は Webhook の1チャンネルだけ（メンション無効）。
- メンバー用URLは読み取りツールだけ（`GROWI_MEMBER_WRITE=true` にしない限り）。
- Growi の設定は `mac/setup_growi.sh`。トークンは専用の bot ユーザーで発行し、書き込める範囲は `GROWI_WRITE_PREFIXES` で絞る。

## セットアップ

### 1. Discord で Bot を作る（5分）
1. https://discord.com/developers/applications → **New Application**（名前は例：`NC Reader`）
2. 左の **Bot** → **Reset Token** でトークンを発行して控える（`DISCORD_BOT_TOKEN`）
3. 同じ画面の **Privileged Gateway Intents** で
   - **Message Content Intent** を ON（必須。OFFだと本文が空になります）
   - **Server Members Intent** を ON（任意。ロール宛てメンションの判定に使います）
4. 左の **OAuth2** → Client ID を控え、次のURLを開いてサーバーに招待：
   ```
   https://discord.com/oauth2/authorize?client_id=<Client ID>&scope=bot&permissions=66560
   ```
   権限は「チャンネルを見る」＋「メッセージ履歴を読む」だけです（66560）。

### 2. ID を調べる
Discord の **設定 → 詳細設定 → 開発者モード** を ON にすると、右クリックで「IDをコピー」できます。
- サーバーアイコンを右クリック → サーバーID → `ALLOWED_GUILD_IDS`
- 自分のアイコンを右クリック → ユーザーID → `OWNER_USER_ID`

### 3a. Mac で動かす場合
```bash
bash ~/work/discord-mcp/mac/setup_server.sh   # トークン・ID を聞かれるので入力 → 常駐起動
bash ~/work/discord-mcp/mac/setup_funnel.sh   # Tailscale Funnel で HTTPS 公開（ドメイン不要）
# Cloudflare に自分のドメインがある場合は代わりに: bash ~/work/discord-mcp/mac/setup_tunnel.sh
```
最後に表示される URL を 4. でコネクタに登録します。Mac がスリープ中は Discord を読めません（朝のブリーフでは「Discord未確認」と表示されます）。
止めるときは `bash ~/work/discord-mcp/mac/uninstall.sh`。ログは `~/work/discord-mcp/logs/`。

### 3b. Linux サーバーで動かす場合（Docker）
```bash
cp .env.example .env    # 値を埋める
python3 -c "import secrets;print(secrets.token_urlsafe(32))"   # MCP_SECRET 用
docker compose up -d --build
```
`127.0.0.1:8000` で待ち受けるので、既存のリバースプロキシ（Caddy / nginx / Traefik）や Cloudflare Tunnel で **HTTPS** で公開してください。claude.ai のサーバーから届く必要があるので、学内限定・VPN内だと繋がりません。

Caddy の例：
```
discord-mcp.example.com {
    reverse_proxy 127.0.0.1:8000
}
```

### 4. Claude に追加
claude.ai の **設定 → コネクタ → カスタムコネクタを追加** で、URL に
```
https://discord-mcp.example.com/<MCP_SECRET>/mcp
```
を入れて追加（認証設定は空欄でOK）。

## 動作確認（ローカル）
```bash
pip install -r requirements.txt
python3 tests/fake_discord.py &       # 偽の Discord API
DISCORD_API_BASE=http://127.0.0.1:8901 DISCORD_BOT_TOKEN=dummy ALLOWED_GUILD_IDS=111 \
  OWNER_USER_ID=900 MCP_SECRET=testsecret_0123456789abcdefghijklmnop PORT=8902 python3 server.py &
python3 tests/client_test.py http://127.0.0.1:8902/testsecret_0123456789abcdefghijklmnop/mcp
```

## メモ
- 1回の読み取りは最大14日・1チャンネル300件まで。最終発言が期間より古いチャンネルは読みに行きません。
- アーカイブ済みスレッドは対象外です（アクティブなスレッドとフォーラム投稿は読みます）。
- トークンが漏れたら Developer Portal で Reset Token、URL が漏れたら `MCP_SECRET` を変えて再起動 → コネクタのURLを更新。
