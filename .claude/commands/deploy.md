# Deploy Command

## 🚀 デプロイ手順
このプロジェクトのデプロイは `deploy.sh` を通じて行われます。

### 1. デプロイの実行
以下のコマンドで、Gitコミット・プッシュ・Cloud Runへのデプロイを一括実行します。

```bash
./deploy.sh "コミットメッセージ"
```

### 2. デプロイ後の確認
デプロイ完了後、自動的にヘルスチェックが行われます。以下のレスポンスが返れば成功です。
```json
{
    "status": "healthy",
    "services": {
        "database": "connected",
        "line": "initialized",
        "calendar": "ready"
    }
}
```

### 3. 注意事項
- デプロイ前にローカルで `python3 main.py` を実行し、起動エラーがないか確認すること。
- 環境変数を変更した場合は、Google Cloud Console の Cloud Run 画面でも設定を確認すること。
