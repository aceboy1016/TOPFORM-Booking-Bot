---
description: TOPFORM Booking Bot をデプロイする手順
---

## デプロイ方法

### ワンコマンドデプロイ
// turbo-all

1. デプロイスクリプトを実行
```bash
cd /Users/junya/projects/TOPFORM-Booking-Bot && chmod +x deploy.sh && ./deploy.sh "変更内容のメッセージ"
```

### 手動デプロイ（ステップバイステップ）

1. コードをコミット＆プッシュ
```bash
cd /Users/junya/projects/TOPFORM-Booking-Bot && git add -A && git commit -m "変更内容" && git push
```

2. Cloud Run にデプロイ
```bash
cd /Users/junya/projects/TOPFORM-Booking-Bot && gcloud run deploy topform-booking-bot --source . --region asia-northeast1
```

3. ヘルスチェック
```bash
curl https://topform-booking-bot-622073906655.asia-northeast1.run.app/health
```

### ロールバック

1. リビジョン一覧を確認
```bash
gcloud run revisions list --service topform-booking-bot --region asia-northeast1
```

2. 特定のリビジョンに戻す
```bash
gcloud run services update-traffic topform-booking-bot --to-revisions=<リビジョン名>=100 --region asia-northeast1
```

### ログ確認
```bash
gcloud run services logs read topform-booking-bot --region asia-northeast1 --limit 50
```
