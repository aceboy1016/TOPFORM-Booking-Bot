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

### 4. 🔔 管理者通知 (Admin Notifications)
予約やキャンセル待ちのステータスが動いた際、登録された管理者（石原トレーナー等）に以下の内容が即座に通知されます。
- **キャンセル待ち登録完了**: Web画面から新しく登録があったとき。
- **予約受付**: お客様が空き枠提案を「承諾」したとき。
- **予約確定**: 管理者が予約を確定させた際（運用フローによる）。
- **スルー（見送り）**: お客様が空き枠提案を「辞退」したとき。

### 5. ⏳ キャンセル待ち自動チェック (Waitlist Automation)
1時間おき（または手動リクエスト）に、スプレッドシートの待機リストとカレンダーの空き状況を照合します。
- 空きが出た場合、該当ユーザーに Flex Message で「空き枠のお知らせ」を送信。
- ユーザーのボタン操作（承諾/辞退）に応じて管理者に通知が飛び、スプレッドシートのステータスが自動更新されます。

---

## 🏗️ 技術スタック

| 項目 | 技術 |
|---|---|
| サーバー | FastAPI (Python) |
| LINE連携 | LINE Messaging API (line-bot-sdk v3) |
| 予約データ | Google Calendar API |
| 待機リスト | Google Sheets API (キャンセル待ちシート) |
| DB | SQLite (ユーザー・予約履歴・セッション) |
| **デプロイ** | **Google Cloud (Cloud Run)** |

> [!IMPORTANT]
> **デプロイ先について**: 以前は Render を使用していましたが、現在は **Google Cloud (Cloud Run)** で稼働しています。`Procfile` は残っていますが、実際のデプロイは Google Cloud Console または CI/CD 経由で行われます。

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
ユーザー → LINE → Webhook → FastAPI (Cloud Run) → process_event
                                         ↓
                                   handle_text_message
                                         ↓
                    ┌────────────────────────────────────┐
                    │ 「2/20空いてる？」                     │
                    │ → handle_date_query (Google Calendar)  │
                    │ → Flex Message で返信                  │
                    ├────────────────────────────────────┤
                    │ 「予約する」                           │
                    │ → booking flow (session管理)           │
                    │ → SQLite保存 → 管理者通知               │
                    ├────────────────────────────────────┤
                    │ キャンセル待ち (Automation)             │
                    │ → fetch_waitlist (Google Sheets)      │
                    │ → check_availability (Calendar)       │
                    │ → push_flex (LINE) → ユーザー承諾       │
                    │ → 管理者通知 (LINE)                    │
                    └────────────────────────────────────┘
```

---

## 📋 キャンセル待ち連携 (Spreadsheet)
スプレッドシート ID: `17jOb7Jh8xllsmG9RJjdc0GUKykBVxEVkxpyw92sWkjk`
シート名: `キャンセル待ち`

**カラム構成:**
- A: 登録日時
- B: 希望日
- C: 希望時間
- D: 店舗
- E: お名前
- F: **LINE User ID (必須)**
- G: ステータス (待機中 / 通知済み / ...)

> [!WARNING]
> LINE User ID が空のデータは通知システムが動作しません。Webフロントエンド側で LIFF ログインを強制することで、ID の欠落を防止しています。

---

## 🔗 関連プロジェクト

| プロジェクト | 内容 | 場所 |
|---|---|---|
| ishihara-booking | 早見表Web (Next.js) | [Vercel](https://ishihara-booking.vercel.app) |
| TOPFORM_Personal_Bot_v1 | 分子栄養学Bot (別物) | `/scratch/TOPFORM_Personal_Bot_v1` |

---

## 📞 困ったら

Claudeに「TOPFORM LINE Botの〇〇を修正したい」と伝えてください。
