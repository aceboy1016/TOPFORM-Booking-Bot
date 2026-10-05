# TOPFORM ちょこっと運動通知

予約Botとは独立したGoogle Apps Script。1人の友だちへ、月〜金の日本時間9:00〜17:00に1日1回、画像付きFlexカードを配信します。祝日は曜日どおり（月〜金なら配信）。実行時にAIは呼びません。

## 運用状態

初期状態は無効です。コードをアップロードしただけではトリガーも配信も開始されません。送信先の明示確認後に設定し、`validateExerciseReminder`、`startExerciseReminder`の順に実行します。初回はGoogle側の権限承認が必要です。既存の予約BotのWebhook、予約・会員データ、カレンダーには触れません。

## スクリプトプロパティ（ソースへ秘密情報を書かない）

| キー | 値 |
|---|---|
| LINE_CHANNEL_ACCESS_TOKEN | 送信元Botのアクセストークン |
| RECIPIENT_USER_ID | 明示的に確認した1人のLINEユーザーID |
| EXPECTED_RECIPIENT_NAME | profile APIで照合する表示名 |
| EXPECTED_BOT_NAME | info APIで照合する送信元表示名 |
| IMAGE_BASE_URL | 公開HTTPSのassetsディレクトリ。GitHub rawのコミットSHA固定URLを推奨 |
| RESERVE_MESSAGES | 予約等に残す通数。既定50 |
| ENABLED | 初期はfalse。start/stop関数で切り替える |

画像URL例: `https://raw.githubusercontent.com/aceboy1016/TOPFORM-Booking-Bot/<COMMIT_SHA>/integrations/exercise-reminder/assets`

`validateExerciseReminder` は送信元・送信先、画像5枚の取得、LINEのFlex検証APIを確認します。メッセージは送りません。
`startExerciseReminder` は5分おきのトリガーを1つだけ登録します。
`stopExerciseReminder` は無効化してこの機能のトリガーのみ削除します。送信履歴は残すため同日再開で重複しません。
`exerciseReminderStatus` は有効状態・当月受付数・当日の予定分（0時からの分数）・状態を返します。宛先や秘密情報は返しません。

## 配信と費用

- その日の予定とカードを永続化。予定時刻は9:00〜16:55から分単位でランダム。5分おきに予定時刻を過ぎたか確認し、17:00以降は送らない。GASの遅延で時間内に動かなかった日は配信を省略し、翌日へ繰り越さない。
- 開始当日は現在時刻から5分以上先を選ぶ。16:50を過ぎて開始した場合は当日の配信を省略。
- 前回成功した画像以外の4種類からランダムに選ぶ。必ず5種類を一巡する仕様ではない。
- 1回1人1カード、通常月20〜23通。機能単独で月25通を上限とする。LINEアカウント全体の残数が50通以下なら送信を見送る。予約側の同時送信との完全な割当保証ではない。
- トークン消費・AI実行費用は0。GASとGitHub rawを使用し、追加の有料サーバーは作らない。無料枠・外部サービスの可用性は各サービスに依存。
- 画像はAIで生成したイメージ。医療・運動指導の正確性を保証する教材ではない。

## 重複防止・再試行

ScriptLockで並行処理を排他。送信前に本文・宛先・retry keyをScript Propertiesへ保存し、タイムアウト/429/5xx後も同じペイロードとキーを使用。LINEの200、またはaccepted request IDを伴う409を受付成功として記録します。その他4xxはその日の送信を停止。日付が変われば前日の未送信を破棄します。受付成功は端末での閲覧・通知表示を保証しません。

送信先を変更する場合は停止し、設定を確認してから開始してください。当日既存ジョブの宛先とは異なる場合は送信せずエラーにします。送信済み記録を削除しないでください。

## 検証

`node --test integrations/exercise-reminder/test.cjs`

時刻・土日・有効/無効・同日再開・通信結果不明後の再試行・残通数・宛先変更・翌日への繰越防止を外部送信なしで検証します。
