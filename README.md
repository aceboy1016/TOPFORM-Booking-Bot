# 🏋️ TOPFORM LINE Bot（石原トレーナー予約Bot）

TOPFORMパーソナルトレーニングジムの公式LINE予約Botです。
石原トレーナーの予約管理を自動化します。

---

## 📍 プロジェクトの場所

```
/Users/junya/.gemini/antigravity/scratch/TOPFORM_LINE_Bot
```

---

## 🎯 機能

### 1. 📅 チャット予約（対話型）
LINEのトーク画面で自然に予約ができます。

```
👤「2/20空いてる？」
🤖 → 空き状況をFlex Messageで表示（恵比寿/半蔵門）

👤「予約する」
🤖 → 店舗選択 → 日にち → 時間 → 確認 → 確定
```

**対応する自然言語:**
- `「2/20空いてる？」` `「2月20日は？」`
- `「明日空き」` `「明後日」` `「今日」`
- `「来週水曜」` `「土曜」`

### 2. 📖 予約確認（マイ予約）
自分の予約だけを一覧表示。
- ローカルDB + Google Calendarの両方から検索
- 過去の予約・今後の予約を表示

### 3. 📋 石原早見表
既存の [ishihara-booking](https://ishihara-booking.vercel.app) WebページをLINE内ブラウザで開きます。

### 4. 🔔 管理者通知
予約が入ると、管理者（石原トレーナー）のLINEに自動で通知が届きます。

---

## 🏗️ 技術スタック

| 項目 | 技術 |
|---|---|
| サーバー | FastAPI (Python) |
| LINE連携 | LINE Messaging API (line-bot-sdk v3) |
| 予約データ | Google Calendar API |
| DB | SQLite (ユーザー・予約履歴・セッション) |
| デプロイ | Render |

---

## 📁 ファイル構成

```
TOPFORM_LINE_Bot/
├── main.py              # FastAPIエントリーポイント
├── config.py            # 設定・定数の定義
├── calendar_service.py  # Google Calendar API連携 & 空き判定ロジック
├── line_service.py      # LINEメッセージ処理 & 予約フロー
├── database.py          # SQLiteデータベース
├── .env.example         # 環境変数テンプレート
├── requirements.txt     # Pythonライブラリ
├── Procfile             # Render起動コマンド
├── render.yaml          # Renderインフラ設定
└── runtime.txt          # Pythonバージョン
```

---

## 🚀 セットアップ

### 1. 環境変数の設定

```bash
cd /Users/junya/.gemini/antigravity/scratch/TOPFORM_LINE_Bot
cp .env.example .env
# .env を編集して各値を設定
```

### 2. LINE公式アカウントの設定

1. [LINE Developers](https://developers.line.biz/) でMessaging APIチャネルを作成
2. チャネルアクセストークンとチャネルシークレットを `.env` に設定
3. Webhook URLを `https://your-domain/webhook` に設定
4. Webhook利用をONにする

### 3. Google Calendar API

既存の `ishihara-booking` と同じサービスアカウントを使用可能。
`GOOGLE_CREDENTIALS_JSON` に同じ認証情報を設定。

### 4. ローカル開発

```bash
cd /Users/junya/.gemini/antigravity/scratch/TOPFORM_LINE_Bot
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python -m uvicorn main:app --reload --port 8002
```

別ターミナルでngrok:
```bash
ngrok http 8002
```

ngrokのURLをLINE DevelopersのWebhook URLに設定。

### 5. Renderデプロイ

```bash
git init
git add .
git commit -m "Initial commit"
# GitHubリポジトリを作成してpush
git remote add origin https://github.com/aceboy1016/TOPFORM-LINE-Bot.git
git push -u origin main
```

Renderダッシュボードでリポジトリを接続し、環境変数を設定。

---

## 🔑 環境変数

| 変数名 | 説明 |
|---|---|
| `LINE_CHANNEL_ACCESS_TOKEN` | LINE Botのアクセストークン |
| `LINE_CHANNEL_SECRET` | LINE Botのチャネルシークレット |
| `ADMIN_USER_ID` | 管理者のLINE User ID（通知先） |
| `GOOGLE_CREDENTIALS_JSON` | Google Calendar APIの認証JSON |
| `HAYAMIHYO_URL` | 石原早見表のURL |

---

## 📊 データフロー

```
ユーザー → LINE → Webhook → FastAPI → process_event
                                         ↓
                                   handle_text_message
                                         ↓
                    ┌────────────────────────────────────┐
                    │ 「2/20空いてる？」                     │
                    │ → parse_date_query → handle_date_query │
                    │ → Google Calendar API → 空き計算        │
                    │ → Flex Message で返信                  │
                    ├────────────────────────────────────┤
                    │ 「予約する」                           │
                    │ → booking flow (session管理)           │
                    │ → 店舗選択 → 日付 → 時間 → 確認 → 確定    │
                    │ → SQLite保存 → 管理者通知               │
                    ├────────────────────────────────────┤
                    │ 「予約確認」                           │
                    │ → SQLite + Calendar検索               │
                    │ → 予約一覧を表示                       │
                    └────────────────────────────────────┘
```

---

## 🔗 関連プロジェクト

| プロジェクト | 内容 | 場所 |
|---|---|---|
| ishihara-booking | 早見表Web (Next.js) | [Vercel](https://ishihara-booking.vercel.app) |
| TOPFORM_Personal_Bot_v1 | 分子栄養学Bot (別物) | `/scratch/TOPFORM_Personal_Bot_v1` |

---

## 📞 困ったら

Claudeに「TOPFORM LINE Botの〇〇を修正したい」と伝えてください。
