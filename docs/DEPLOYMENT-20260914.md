# 2026-09-14 本番移行記録

状態：本番トラフィックを `topform-booking-bot-reliable-b58f99b` へ100%切り替え済み。旧リビジョン `topform-booking-bot-00106-m54` は削除せず保持。

## インフラ

- Cloud SQL PostgreSQL 16：`topform-booking-db`、東京、Enterprise `db-f1-micro`、単一ゾーン。
- SSD初期10GB、自動バックアップ7世代、PITR、削除保護。DBは常時稼働の追加課金対象です。[公式料金](https://cloud.google.com/sql/pricing)。共有CPU構成はCloud SQL SLA対象外で、負荷増加時は増強が必要です。
- アプリは1インスタンス最大5接続、最大3インスタンスで計15接続に制限（DB上限25）。
- アプリ用DBロールは対象DBの所有者に限定し、DB作成・ロール作成権限を付与しません。
- 実行アカウント：`topform-booking-runtime@topform-booking-bot.iam.gserviceaccount.com`。
- 新規シークレット：`topform-database-url`、`topform-admin-api-token`。値は文書やGitに保存しません。
- 新版イメージ：`asia-northeast1-docker.pkg.dev/topform-booking-bot/cloud-run-source-deploy/topform-booking-bot/verified:b58f99b`。

## 旧データの確認範囲

顧客タブの39行にはLINE未登録行が含まれていました。未登録行を除外し、登録済み20名を検証しました。名前が空欄の登録済み行と重複IDは引き続きエラーにします。顧客シート自体は変更していません。

登録済み利用者の旧予約APIを3巡して取得件数は各0件。過去30日のID出力ログから見つかった追加の利用者IDは0件でした。旧APIは利用者ごとに最大20件しか返さないため、20件に達した場合は移行を停止する検査を入れています。

これは取得可能な現行APIの確認であり、全インスタンスのSQLiteの完全バックアップではありません。旧サービスは揮発性SQLiteを使用しており、すでに消えた履歴は復元できません。切り替え直前・直後にも旧リビジョンを指定して確認し、いずれも取得0件でした。

キャンセル待ちシートは6件すべて通知済み。既存行への通知をテスト送信しません。

## 検証・切り替え

- 本番マスタ・Calendarの読み取り接続を確認。
- SQLiteで72件成功、PostgreSQL専用1件対象外。GitHub CIでSQLite/PostgreSQL検証成功。
- Cloud BuildでLinuxコンテナのビルド成功。
- 無トラフィック新版と本番URLの両方で、ヘルス200、管理APIの未認証401・認証済み200、公開OpenAPI404、不正署名400、署名付き空Webhook200を確認。LINEの読み取りAPIも200。
- `main`対象の重複Cloud Buildトリガーは移行中に一時停止。移行後は一方を無トラフィック配備に統一し、他方を停止のまま残す構成。
- キャンセル待ちを15分ごとの認証付きPOSTへ変更。通知Outbox再送は1分ごと。本番切り替え後に有効化済み。
