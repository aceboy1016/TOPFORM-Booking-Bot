# TOPFORM Booking Bot - 運用ガイド
> テスト運用期間：2026年2月〜3月（1ヶ月）

---

## 📋 目次
1. [デプロイ手順（ワンコマンド）](#1-デプロイ手順)
2. [日常メンテナンス](#2-日常メンテナンス)
3. [セキュリティ評価](#3-セキュリティ評価)
4. [想定トラブルと対処法](#4-想定トラブルと対処法)
5. [モニタリング](#5-モニタリング)
6. [テスト運用チェックリスト](#6-テスト運用チェックリスト)

---

## 1. デプロイ手順

### ワンコマンドデプロイ
```bash
cd /Users/junya/projects/TOPFORM-Booking-Bot
git add -A && git commit -m "変更内容" && git push && \
gcloud run deploy topform-booking-bot --source . --region asia-northeast1
```

### ヘルスチェック確認
```bash
curl https://topform-booking-bot-622073906655.asia-northeast1.run.app/health
```
期待するレスポンス：
```json
{"status":"healthy","services":{"database":"connected","line":"initialized","calendar":"ready"}}
```

### ロールバック（問題が起きた場合）
```bash
# 直前のリビジョンに戻す
gcloud run services update-traffic topform-booking-bot \
  --to-revisions=topform-booking-bot-00033-xxx=100 \
  --region asia-northeast1

# リビジョン一覧を見る
gcloud run revisions list --service topform-booking-bot --region asia-northeast1
```

---

## 2. 日常メンテナンス

### 祝日・休業日の更新（年1回 or 必要時）
`config.py` の以下を編集：
```python
HOLIDAYS = {
    2026: ["2026-01-01", ...],  # ← ここに追加
    2027: ["2027-01-01", ...],  # ← 新年度分を追加
}

FORCED_CLOSED_DAYS = ["2026-02-24"]  # ← 臨時休業日を追加
```

### 顧客マスタの更新
Google Spreadsheet（顧客マスタ）を直接編集するだけでOK。
- シートID: `17jOb7Jh8xIlsmG9RJjdc0GUKykBVxEVkxpyw92sWkjk`
- 形式：A列=名前, B列=LINE ID, C列=恵比寿○✖️, D列=半蔵門○✖️, E列=個室(A/B)
- **5分キャッシュ** のため、更新後5分以内に反映

### 営業時間の変更
```python
# config.py
BUSINESS_HOURS = {
    "weekday": {"start": 9, "end": 22},  # 平日
    "weekend": {"start": 9, "end": 20},  # 土日祝
}
```

### ログの確認
```bash
# Cloud Run のログをリアルタイム表示
gcloud run services logs read topform-booking-bot \
  --region asia-northeast1 --limit 100

# エラーだけフィルタ
gcloud run services logs read topform-booking-bot \
  --region asia-northeast1 --limit 50 | grep -E "❌|ERROR|Error"
```

---

## 3. セキュリティ評価

### 🟢 良い点（現状で安全な部分）

| 項目 | 状況 |
|------|------|
| LINE Webhook署名検証 | ✅ `InvalidSignatureError` でリジェクト |
| 環境変数で秘匿情報管理 | ✅ LINE Token, Google Credentialsは環境変数 |
| HTTPS通信 | ✅ Cloud Run は自動HTTPS |
| Google API は ReadOnly | ✅ Calendar/Sheets ともに `readonly` スコープ |
| 認証なしAPIの制限 | ✅ `/api/` エンドポイントは情報閲覧のみ |
| `.gitignore` | ✅ `.env` は除外されている |

### 🟡 注意点（改善推奨）

| リスク | 詳細 | 対策 |
|--------|------|------|
| **DB がコンテナ内SQLite** | Cloud Run はステートレス。再デプロイ時にDBが初期化される | 現状、DBには予約リクエストの履歴のみ。Calendarが正（Source of Truth）なので実害は少ないが、長期的にはCloud SQLかFirestoreへの移行を検討 |
| **APIエンドポイントが未認証** | `/api/bookings/{user_id}` が誰でもアクセス可能 | テスト期間中はline_user_idを知らない限りアクセス不可（推測困難）。本番化時にAPI Key or IAM認証を追加 |
| **LINE User IDがログに出力** | デバッグログに `user_id[:8]` が表示される | テスト期間はOK。本番化時にログレベルを調整 |
| **管理者通知の宛先** | `ADMIN_USER_ID` 1名のみ | テスト運用では十分。複数管理者が必要になれば配列化 |

### 🔴 要対応（テスト前に確認）

| リスク | 詳細 | 必要なアクション |
|--------|------|-----------------|
| **Google Credentials の権限範囲** | サービスアカウントが他のリソースにアクセスできないか | GCP Console でサービスアカウントの権限を確認。Calendar API と Sheets API のみに制限されているか確認 |
| **LINE Bot の公開範囲** | 友だち追加すれば誰でも使える | LINE Official Account Manager で「友だち追加」を制限（QRコードのみ等）。テスト期間中はテスト顧客のみに共有 |

---

## 4. 想定トラブルと対処法

### 🔥 致命度：高

#### T1. サーバーが応答しない（ボタンが反応しない）
- **原因**: コード変更によるImportError、環境変数の欠損
- **症状**: LINEのボタン・メッセージに一切反応しない
- **対処**:
  ```bash
  # 1. ヘルスチェック
  curl https://topform-booking-bot-622073906655.asia-northeast1.run.app/health
  
  # 2. ログ確認
  gcloud run services logs read topform-booking-bot --region asia-northeast1 --limit 20
  
  # 3. 直前のリビジョンにロールバック
  gcloud run revisions list --service topform-booking-bot --region asia-northeast1
  gcloud run services update-traffic topform-booking-bot \
    --to-revisions=<前のリビジョン名>=100 --region asia-northeast1
  ```

#### T2. Google Calendar API のクォータ超過
- **原因**: 短時間に大量のリクエスト（1分あたり60件が目安）
- **症状**: 空き枠が表示されない、予約確認ができない
- **対処**: 現在5分キャッシュがあるので通常は問題ない。多数の顧客が同時に使う場合はキャッシュTTLを延長
  ```python
  # line_service.py
  self._cache_ttl = timedelta(minutes=10)  # 5→10分に
  ```

#### T3. DB が消える（デプロイ時）
- **原因**: Cloud Run のコンテナ再作成時にSQLiteファイルがリセットされる
- **影響**: セッション情報（予約フローの途中状態）がリセットされる。ただしCalendarの予約データは影響なし
- **対処**: ユーザーには「もう一度最初から選び直してください」と表示される。致命的ではない

### ⚠️ 致命度：中

#### T4. 予約時間の計算ずれ（タイムゾーン）
- **原因**: JSTの扱いミス（サーバーがUTCで動作）
- **症状**: 「12時間前ルール」の判定がずれる
- **対処**: 現在 `pytz.timezone("Asia/Tokyo")` で明示的にJST変換しているので OK。ただし定期的にログで時刻を確認

#### T5. 予約変更ボタンのデータサイズ超過（300バイト制限）
- **原因**: Google Calendar のイベントIDが長い場合
- **症状**: ボタンが表示されない、またはタップしても無反応
- **対処**: 現在は短縮キー(`a`, `bid`, `t`, `d`)を使用。問題発生時はIDをハッシュ化

#### T6. 二重予約
- **原因**: 2人が同時刻に予約確認→2人とも確定
- **影響**: 定員オーバーの予約が入る可能性
- **対処**: 現状、予約は「リクエスト」で石原さんが最終確認する運用のため、実害はない。Calendar上で衝突をチェックして最終判断

#### T7. 顧客が予約フローの途中で離脱
- **原因**: LINEを閉じた、別の操作をした
- **症状**: 次にBot を開いた時に途中のフローが残っている
- **対処**: セッションには有効期限がないため、古いセッションが残る可能性。「⬅️ 戻る」ボタンで解消できる。将来的にはセッションTTL（30分等）を追加

### 💡 致命度：低

#### T8. 予想外のメッセージへの対応
- **原因**: 顧客がスタンプ、画像、動画を送信
- **症状**: 未対応メッセージは無視される（エラーにはならない）
- **対処**: 問題なし。必要に応じてデフォルトレスポンスを追加

#### T9. LINE API の一時的なエラー
- **原因**: LINE Platform のメンテナンス等
- **症状**: メッセージが送信できない
- **対処**: 自動復旧を待つ。Cloud Run のリトライ機構が対応

#### T10. 祝日判定漏れ
- **原因**: `HOLIDAYS` リストに含まれていない祝日
- **症状**: 祝日なのに平日の営業時間で表示
- **対処**: 年初に翌年の祝日を `config.py` に追加

---

## 5. モニタリング

### 日次チェック（推奨）
```bash
# ヘルスチェック
curl -s https://topform-booking-bot-622073906655.asia-northeast1.run.app/health | python3 -m json.tool

# エラーログ確認
gcloud run services logs read topform-booking-bot \
  --region asia-northeast1 --limit 50 2>/dev/null | grep -E "❌|ERROR|Traceback"
```

### Google Cloud Console での確認
- **URL**: https://console.cloud.google.com/run/detail/asia-northeast1/topform-booking-bot/metrics?project=topform-booking-bot
- 確認項目：
  - リクエスト数
  - レスポンス時間（p50, p99）
  - エラー率（5xx）
  - コンテナ起動数

### LINE Official Account Manager
- **URL**: https://manager.line.biz/
- 確認項目：
  - 友だち数
  - メッセージ配信数（月間上限あり）
  - ブロック数

---

## 6. テスト運用チェックリスト

### 運用開始前 ✅
- [ ] ヘルスチェックが通ること
- [ ] テスト顧客（自分）で全フローを通す
  - [ ] 新規予約（恵比寿）
  - [ ] 新規予約（半蔵門）
  - [ ] 予約確認
  - [ ] 予約変更（ボタン）
  - [ ] 予約キャンセル（12時間以上前）
- [ ] 管理者通知が届くこと
- [ ] Google Calendar に予約が反映されること
- [ ] LINE Official Account の公開範囲を制限

### 1週間後 🔍
- [ ] エラーログにクリティカルな問題がないか
- [ ] 顧客からのフィードバック収集
- [ ] 予約変更・キャンセルフローが正常か
- [ ] Cloud Run の請求額を確認

### 2週間後 📊
- [ ] よく使われる機能・使われない機能の把握
- [ ] UX改善点の洗い出し
- [ ] セキュリティインシデントの有無

### 1ヶ月後 📋
- [ ] テスト結果のまとめ
- [ ] 本番化の判断（GoまたはNo-Go）
- [ ] 改善項目のリストアップ
- [ ] DB移行の要否判断

---

## 📝 緊急連絡先・リソース

| リソース | URL/コマンド |
|---------|-------------|
| Service URL | `https://topform-booking-bot-622073906655.asia-northeast1.run.app` |
| Health Check | `curl <Service URL>/health` |
| GCP Console | `https://console.cloud.google.com/run?project=topform-booking-bot` |
| GitHub Repo | `https://github.com/aceboy1016/TOPFORM-Booking-Bot` |
| LINE Manager | `https://manager.line.biz/` |
| ログ確認 | `gcloud run services logs read topform-booking-bot --region asia-northeast1` |
| ロールバック | `gcloud run services update-traffic topform-booking-bot --to-revisions=<rev>=100 --region asia-northeast1` |
