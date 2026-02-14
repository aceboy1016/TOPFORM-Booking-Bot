# ✅ TOPFORM LINE Bot 起動前チェックリスト

このBotを動かすために必要な準備リストです。すべてチェックできたら本番運用可能です！

## 1. LINE Developers設定
- [ ] Messaging APIチャネルを作成した
- [ ] `LINE_CHANNEL_ACCESS_TOKEN` を取得した
- [ ] `LINE_CHANNEL_SECRET` を取得した
- [ ] Webhook URLを設定した（RenderのURL + `/webhook`）
- [ ] Webhook利用を「ON」にした
- [ ] 自動応答メッセージを「OFF」にした
- [ ] 友達追加時あいさつメッセージを「OFF」にした（Botが処理するため）

## 2. Google Calendar API設定
- [ ] Google Cloud Consoleでプロジェクトを作成した
- [ ] Google Calendar APIを有効にした
- [ ] サービスアカウントを作成し、JSONキーをダウンロードした
- [ ] 石原トレーナーのカレンダー（`j.ishihara@topform.jp` 等）に、サービスアカウントの閲覧権限を追加した
- [ ] JSONキーをBase64エンコードし、環境変数 `GOOGLE_CREDENTIALS_JSON` に設定した
  - コマンド: `python scripts/encode_creds.py <your_json_file>`

## 3. Renderデプロイ
- [ ] GitHubにリポジトリをPushした
- [ ] Renderで「New Web Service」を作成した
- [ ] Environment Variablesを設定した
  - `LINE_CHANNEL_ACCESS_TOKEN`
  - `LINE_CHANNEL_SECRET`
  - `GOOGLE_CREDENTIALS_JSON`
  - `ADMIN_USER_ID` (通知を受け取りたいLINE User ID)
- [ ] デプロイが成功し、「Live」になった

## 4. リッチメニュー設定
- [ ] `assets/rich_menu.jpg` (2500x1686推奨) を用意した
- [ ] ローカルで `python scripts/setup_rich_menu.py` を実行した
  - ※環境変数が正しく設定されている必要があります

## 5. 動作確認
- [ ] LINEで「2/20空いてる？」と聞いて、候補が返ってくるか
- [ ] 「予約する」ボタンを押して、予約フローが進むか
- [ ] Adminへの通知が届くか
- [ ] 「予約確認」で自分の予約が表示されるか
