# TOPFORM Booking Bot — 作業ルール

本番稼働中のLINE仮予約受付システムです。Python 3.12 / FastAPI / LINE SDK v3 / Google Calendar（readonly）/ Sheets / SQLAlchemyを使用します。

## 変更原則

- 最小限・段階的に変更し、既存受付を失わないこと。ユーザーの明示指示を優先します。
- 2026-09-14にユーザー確認済み：仮予約は枠を確保しない、2か月先の同日まで、30分刻み開始・60分枠、店舗○×と部屋は希望として扱う。
- 平日8–23時、土日祝9–20時。終了時刻まで営業時間内。店舗移動60分。
- 未登録利用者はID確認以外の予約操作を拒否。12時間以内の取消は1回消化、3時間以内は直前通知。
- CalendarとSheetsの取得失敗を空データに変換しない。日時は常にJSTへ正規化。
- APIキーや認証JSONは作業ツリー・ログに保存しない。
- Cloud Run本番は共有PostgreSQL必須。SQLiteはローカル専用。
- 受付と通知Outboxを同一トランザクションで保存。LINE再送には同じretry keyを使う。
- 応答後の裸のasyncio.create_taskで業務処理を続けない。同期Google呼び出しはasync_services.google_callをawaitする。
- 変更前予約は承認まで保持する。Calendarの変更・取消反映はスタッフの作業。

## 検証・運用

`venv/bin/python -m pytest -q`を実行。既存の実API確認スクリプトと`tests/`のオフライン回帰テストを混同しないこと。PostgreSQLテストは`TEST_DATABASE_URL`を専用`topform_test` DBへ指定します。

Flexボタンは本人に紐付いたサーバー側操作トークンを使い、300バイト以内に収めます。reply tokenは1回のみ使用します。

`README.md`、`OPERATIONS.md`、`docs/ROLLOUT.md`、`docs/AUDIT-REMEDIATION.md`が現行文書です。デプロイ前に永続DB、旧仮予約の引継ぎ、認証、Schedulerを準備してください。`deploy.sh`は自動commit/pushせず、レビュー用リビジョンを無トラフィックで作成します。
