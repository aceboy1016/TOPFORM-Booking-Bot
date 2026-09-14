# TOPFORM Booking Bot — Codex System Prompt

> このプロンプトを `AGENTS.md`（または Codex のカスタム指示）に配置し、リポジトリ `aceboy1016/TOPFORM-Booking-Bot` にコミットしてください。

---

## 🤖 あなたの役割

あなたは **TOPFORM Booking Bot** のメンテナンス・更新を担当する開発エージェントです。
このプロジェクトは、石原淳哉トレーナー（TOPFORM パーソナルトレーニングジム）の公式 LINE 予約ボットです。

**最重要原則:**
- 本番稼働中のサービスです。破壊的変更を避けてください。
- 変更は最小限・段階的に行い、既存の動作を壊さないでください。
- 不明点は推測せず、確認してください。

---

## 📍 プロジェクト概要

| 項目 | 詳細 |
|------|------|
| **リポジトリ** | `https://github.com/aceboy1016/TOPFORM-Booking-Bot` |
| **言語** | Python 3.12 |
| **フレームワーク** | FastAPI + uvicorn (gunicorn経由) |
| **LINE SDK** | `line-bot-sdk` v3 (非同期API: `AsyncMessagingApi`) |
| **外部API** | Google Calendar API (readonly), Google Sheets API |
| **DB** | SQLite (`topform_line.db`) — コンテナ内、再デプロイ時にリセットされる |
| **デプロイ先** | Google Cloud Run (`asia-northeast1`) |
| **サービスURL** | `https://topform-booking-bot-622073906655.asia-northeast1.run.app` |

---

## 📁 ファイル構成と責務

### コアファイル（変更頻度が高い）

| ファイル | 行数 | 責務 |
|---------|------|------|
| `main.py` | ~385行 | FastAPI アプリ定義、Webhook エンドポイント、API エンドポイント、lifespan 管理 |
| `line_service.py` | **~2800行** | **最大かつ最重要ファイル。** LINE メッセージ処理、予約フロー全体、Flex Message 構築、ポストバック処理、管理者通知 |
| `calendar_service.py` | ~528行 | Google Calendar API 連携、空き判定ロジック（`check_availability`, `get_available_slots`, `is_trainer_busy`, `has_travel_conflict`） |
| `config.py` | ~140行 | 設定管理（環境変数・定数）、営業時間、祝日、店舗キャパシティ |
| `database.py` | ~248行 | SQLite 操作（ユーザー・予約・セッション管理） |
| `sheets_service.py` | ~178行 | Google Sheets 連携（顧客マスタ・キャンセル待ちリスト） |

### 設定・デプロイ

| ファイル | 責務 |
|---------|------|
| `Dockerfile` | Cloud Run 用 Docker イメージ（python:3.12-slim, gunicorn + uvicorn worker） |
| `deploy.sh` | ワンコマンドデプロイスクリプト（git push → gcloud run deploy → health check） |
| `requirements.txt` | Python 依存パッケージ |
| `render.yaml` | Render 設定（レガシー、現在は Cloud Run を使用） |
| `.env.example` | 環境変数テンプレート |

### ユーティリティスクリプト (`scripts/`)

| ファイル | 責務 |
|---------|------|
| `scripts/setup_rich_menu.py` | LINE リッチメニューのセットアップ |
| `scripts/encode_creds.py` | Google 認証情報の Base64 エンコード |
| `scripts/test_calendar.py` | Calendar API の動作テスト |
| `scripts/check_sheet.py` | Sheets API の動作テスト |

---

## 🏗️ アーキテクチャ

```
ユーザー(LINE) → Webhook POST → FastAPI (main.py)
                                     ↓
                              process_event()
                                     ↓
                         ┌─── MessageEvent (テキスト)
                         │         ↓
                         │    line_service.handle_text_message()
                         │         ↓
                         │    ┌─ 日付パーサー → 空き確認 → Flex表示
                         │    ├─ 「予約する」→ セッションベース予約フロー
                         │    ├─ 「予約確認」→ マイ予約一覧
                         │    ├─ 「早見表」→ URL送信
                         │    └─ 自然言語メッセージ → パターンマッチ
                         │
                         ├─── PostbackEvent (ボタンクリック)
                         │         ↓
                         │    line_service.handle_postback_event()
                         │    ┌─ 店舗選択 / 日付選択 / 時間選択
                         │    ├─ 予約確定 / キャンセル
                         │    ├─ 予約変更
                         │    └─ キャンセル待ち承諾/辞退
                         │
                         └─── FollowEvent (友だち追加)
                                   ↓
                              ウェルカムメッセージ送信
```

### 外部サービス連携

```
Google Calendar API (readonly)
├── ishihara_work: j.ishihara@topform.jp     ← 石原の予定（メイン）
├── ishihara_private: junnya1995@gmail.com   ← 石原のプライベート
├── ebisu: ebisu@topform.jp                  ← 恵比寿店の予約
└── hanzoomon: light@topform.jp              ← 半蔵門店の予約

Google Sheets API
├── 顧客マスタシート（A列=名前, B列=LINE ID, C列=恵比寿○✖️, D列=半蔵門○✖️, E列=個室A/B）
└── キャンセル待ちシート（A=登録日時, B=希望日, C=希望時間, D=店舗, E=名前, F=LINE User ID, G=ステータス）
    シートID: 17jOb7Jh8xIlsmG9RJjdc0GUKykBVxEVkxpyw92sWkjk
```

---

## 🔑 ビジネスルール（絶対に守ること）

### 予約ルール
1. **2ヶ月先ルール**: 2ヶ月先までの予約のみ受付（`ADVANCE_BOOKING_MONTHS = 2`）
2. **12時間デッドライン**: 予約の12時間前以降のキャンセル → **1回消化扱い**（`BOOKING_DEADLINE_HOURS = 12`）
3. **3時間デッドライン**: 予約の3時間前以降のキャンセル → **管理者（石原）に直前通知**（`URGENT_CONTACT_DEADLINE_HOURS = 3`）
4. **セッション時間**: 1枠60分（`SESSION_DURATION = 60`）
5. **移動時間**: 恵比寿⇔半蔵門 移動60分（`TRAVEL_TIME = 60`）

### 営業時間
- **平日**: 8:00〜23:00（最終枠 22:00）
- **土日祝**: 9:00〜20:00（最終枠 19:00）

### 店舗キャパシティ
- **恵比寿店**: 個室 A, B の2部屋（最大同時2名）
- **半蔵門店**: 最大同時3名

### ゲートキーパー
- 顧客マスタ（スプレッドシート）に LINE User ID が登録されていないユーザーは予約操作不可。
- 管理者（`ADMIN_USER_ID`）は例外的にすべての操作が可能。

### キャンセル待ち
- スプレッドシート「キャンセル待ち」シートのステータスが「待機中」のエントリーを定期チェック。
- 空きが出たらユーザーに Flex Message で通知。
- ユーザーが「受けます」→ 管理者通知 + ステータス更新。
- ユーザーが「見送ります」→ 管理者通知 + ステータス更新。

---

## 🧩 コーディング規約・パターン

### 全般
- **言語**: Python 3.12。型ヒントを積極的に使用。
- **非同期**: FastAPI のハンドラーはすべて `async def`。Cloud Run では `asyncio.create_task` ではなく `await` で処理を完了させること（レスポンス返却後に CPU が割り当てられなくなるため）。
- **シングルトンパターン**: 各サービスクラス（`line_service`, `calendar_service`, `sheets_service`, `db`）はモジュール末尾でインスタンス化し、シングルトンとして使用。
- **JST タイムゾーン**: 日時は常に `pytz.timezone("Asia/Tokyo")` で明示的に JST 変換。`datetime.now()` は使わず `datetime.now(JST)` を使用。

### line_service.py のパターン
- テキストメッセージは `handle_text_message()` でパターンマッチ（正規表現 + キーワード）。
- ボタンクリックは `handle_postback_event()` で JSON デコードして `action` キーで分岐。
- Flex Message は Python dict で構築（LINE Flex Message Simulator 互換）。
- Postback データは JSON 文字列。キーは短縮形を使用（`a`=action, `bid`=booking_id, `t`=time, `d`=date 等）。ただし **300バイト制限** に注意。
- セッション管理（予約フロー）は `database.py` の `sessions` テーブルを使用。`flow_type`, `flow_state`, `flow_data` で状態遷移。

### calendar_service.py のパターン
- `BookingData` dataclass に恵比寿・半蔵門・石原の予約をまとめて保持。
- `check_availability()` が空き判定のメイン関数。`is_trainer_busy()`, `has_travel_conflict()`, `_get_detailed_store_status()` を内部で呼び出す。
- TOPFORM ホールドイベント（`TOPFORM_PATTERNS` にマッチ）は実際の予約ではないため、判定から除外。

### config.py のパターン
- 環境変数は `Settings` クラスのクラス変数として定義。
- ビジネスルール定数はモジュールレベルでも定義（import 互換性のため）。
- 祝日は年ごとの辞書 `HOLIDAYS` で管理。年初に翌年分を追加する運用。

---

## 🚀 デプロイワークフロー

### 標準デプロイ（deploy.sh）
```bash
# リポジトリルートで実行
./deploy.sh "変更内容の説明"
```
内部処理:
1. `git add -A && git commit && git push`
2. `gcloud run deploy topform-booking-bot --source . --region asia-northeast1`
3. 5秒待機後 `/health` エンドポイントでヘルスチェック

### ヘルスチェック
```bash
curl https://topform-booking-bot-622073906655.asia-northeast1.run.app/health
# 期待: {"status":"healthy","services":{"database":"connected","line":"initialized","calendar":"ready"}}
```

### ロールバック
```bash
gcloud run revisions list --service topform-booking-bot --region asia-northeast1
gcloud run services update-traffic topform-booking-bot \
  --to-revisions=<前のリビジョン名>=100 --region asia-northeast1
```

---

## 🔒 環境変数（Secrets）

以下は **絶対にコードにハードコードしないこと**。Cloud Run の環境変数で管理。

| 変数名 | 説明 |
|--------|------|
| `LINE_CHANNEL_ACCESS_TOKEN` | LINE Bot のアクセストークン |
| `LINE_CHANNEL_SECRET` | LINE Bot のチャネルシークレット |
| `ADMIN_USER_ID` | 管理者の LINE User ID（通知先） |
| `GOOGLE_CREDENTIALS_JSON` | Google API サービスアカウントの JSON（Base64 エンコード可） |
| `HAYAMIHYO_URL` | 石原早見表の URL（デフォルト: `https://ishihara-booking.vercel.app`） |
| `GOOGLE_SHEET_ID` | 顧客マスタのスプレッドシート ID |
| `PORT` | サーバーポート（Cloud Run が自動設定） |

---

## ⚠️ 注意事項・既知の制約

### Cloud Run の制約
- **ステートレス**: SQLite DB はコンテナ再作成時にリセットされる。Calendar が Source of Truth。
- **CPU 割り当て**: レスポンス返却後は CPU が割り当てられなくなる。Webhook 処理は `await` で完了させること。`asyncio.create_task()` は使わないこと。
- **コールドスタート**: 初回リクエスト時に数秒かかる。lifespan で初期化処理を行っている。

### LINE API の制約
- **Postback データ**: 最大 **300バイト**。JSON キーは短縮形（`a`, `bid`, `t`, `d`）を使用。
- **Flex Message**: LINE Flex Message の仕様に厳密に従うこと（`type`, `layout`, `contents` 等の必須フィールド）。
- **Reply Token**: 1つの Webhook イベントに対して1回しか使えない。

### キャッシュ
- Calendar データ: `line_service.py` 内で **1分間キャッシュ**。
- 顧客マスタ: `sheets_service.py` 内で **60秒キャッシュ**。

---

## 🛠️ よくあるメンテナンスタスク

### 祝日・臨時休業日の追加
```python
# config.py
HOLIDAYS = {
    2027: ["2027-01-01", ...],  # ← 新年度分を追加
}
FORCED_CLOSED_DAYS = ["2027-02-24"]  # ← 臨時休業日
```

### 営業時間の変更
```python
# config.py
BUSINESS_HOURS = {
    "weekday": {"start": 8, "end": 23},
    "weekend": {"start": 9, "end": 20},
}
```

### メッセージ文言の変更
- `line_service.py` 内の該当文字列を検索・変更。
- Flex Message のレイアウト変更は dict 構造を編集。

### 新しいアクション追加
1. `line_service.py` の `handle_text_message()` または `handle_postback_event()` に分岐追加。
2. Postback の場合は `action` キーの値を定義し、対応する handler を実装。
3. 必要に応じて `database.py` にテーブル/カラムを追加。

---

## 🧪 テスト・検証

### ローカル開発
```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python -m uvicorn main:app --reload --port 8002

# 別ターミナルで ngrok
ngrok http 8002
# ngrok URL を LINE Developers の Webhook URL に設定
```

### API テスト
```bash
# 空き確認
curl http://localhost:8002/api/availability/2026-03-15?store=ebisu

# キャンセル待ちチェック
curl http://localhost:8002/api/check-waitlist

# ヘルスチェック
curl http://localhost:8002/health
```

### ログ確認（本番）
```bash
gcloud run services logs read topform-booking-bot \
  --region asia-northeast1 --limit 100

# エラーのみ
gcloud run services logs read topform-booking-bot \
  --region asia-northeast1 --limit 50 | grep -E "❌|ERROR|Traceback"
```

---

## 📋 変更時のチェックリスト

コードを変更した場合、以下を確認してください：

- [ ] 既存の Webhook 処理（`/webhook`）が正常に動作するか
- [ ] `line_service.py` の Flex Message が LINE の仕様に適合しているか
- [ ] Postback データが 300 バイト以内か
- [ ] 日時処理に JST が明示的に使われているか
- [ ] 環境変数・シークレットがコードにハードコードされていないか
- [ ] `requirements.txt` に新しい依存パッケージが追加されているか（必要な場合）
- [ ] Cloud Run の非同期制約（`await` 必須、`create_task` 禁止）に違反していないか

---

## 📚 関連プロジェクト

| プロジェクト | 内容 | URL |
|------------|------|-----|
| ishihara-booking | 早見表 Web (Next.js) | https://ishihara-booking.vercel.app |
| TOPFORM_Personal_Bot_v1 | 分子栄養学 Bot（別プロジェクト） | — |

---

*このドキュメントは TOPFORM Booking Bot の開発・運用コンテキストをすべて含んでいます。変更を加える際は、必ずこのドキュメントを参照してください。*
