# TOPFORM Booking Bot

TOPFORMのLINE仮予約受付システム。FastAPI / Python 3.12 / LINE Messaging API / Google Calendar・Sheetsを使用します。

## 予約ルール

- Botは仮予約を受け付け、スタッフがカレンダーへ登録後に承認します。仮予約では枠を確保しません。
- 2か月先の同日まで（月末に同日がなければその月の末日）。開始は30分刻み、1枠60分。
- 店舗間の移動は60分。平日8–23時、土日祝9–20時。終了時刻まで営業時間内である必要があります。
- 店舗○×・個室A/Bは希望です。登録されていない利用者の予約操作は拒否します。
- 12時間以内の変更は取消申請（1回分消化）、3時間以内は直前取消申請です。

## 開発

```sh
python3.12 -m venv venv
venv/bin/pip install --require-hashes -r requirements.lock
venv/bin/pip install -r requirements-dev.txt
venv/bin/python -m pytest -q
```

テストはLINE・Googleへの送信を行いません。実動作には`.env.example`にある環境変数を設定してください。資格情報JSONを作業ツリーへ置かないでください。

```sh
venv/bin/python -m uvicorn main:app --reload --port 8002
```

SQLiteはローカル開発専用です。本番Cloud Runでは`DATABASE_URL=postgresql+asyncpg://...`の共有PostgreSQLが必須です。

## 主要ファイル

| ファイル | 役割 |
|---|---|
| main.py | 署名検証・再配信制御・認証付き管理API |
| booking_rules.py / date_parser.py | 共通予約ルール・日付解析 |
| calendar_service.py | 全カレンダー取得、部屋・移動・休業の判定 |
| line_service.py / booking_actions.py | 対話と本人に紐付いた期限付きボタン |
| booking_view.py | DBとカレンダーの一覧・集計 |
| database.py | 永続予約要求、セッション、操作ID、通知Outbox |
| notifications.py / waitlist_service.py | 再送・キャンセル待ち |

運用方法は[OPERATIONS.md](OPERATIONS.md)、移行手順は[docs/ROLLOUT.md](docs/ROLLOUT.md)、監査40項目の対応状況は[docs/AUDIT-REMEDIATION.md](docs/AUDIT-REMEDIATION.md)を参照してください。
