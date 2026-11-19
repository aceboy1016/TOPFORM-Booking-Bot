# GitHub Actionsからの配備

> **未完了（2026-11-19時点）。`deploy`ジョブはスキップされ、配備は従来どおり
> Cloud Buildトリガーが行っています。** 下記のうち残っているのは、
> サービスアカウントへの`roles/iam.serviceAccountTokenCreator`の付与だけです。
> サービスアカウント、各種ロール、Workload Identityプールとプロバイダ、
> GitHubのVariables 2件はすべて設定済みです。
>
> 完了させる場合は「3. 残りの設定」のコマンドを実行してください。
> この設定はbotの動作とは無関係です。未完了でも支障はありません。

テストとデプロイの結果を1か所で確認できるようにするための設定手順です。
Workload Identity連携を使い、サービスアカウントキーをGitHubへ保存しません。

配備の方針は変えていません。`main`へのpushは`--no-traffic --tag=review`で
レビュー用リビジョンを作るだけで、**本番トラフィックは切り替わりません**。
昇格は従来どおり、リビジョンを明示した意図的な操作です
（[本番移行・復旧手順](ROLLOUT.md)の「自動配備の運用」を参照）。

変わるのは次の2点です。

- デプロイが**テスト成功後にしか走らない**。現在のCloud Buildトリガーはテスト結果を見ていない。
- 失敗・成功とリビジョン一覧がGitHubの同じ画面で追える。

## 1. GCP側の設定（初回のみ）

`PROJECT_NUMBER`は`gcloud projects describe`か、Cloud RunのURL
（`topform-booking-bot-622073906655...`）の数字部分です。

```sh
PROJECT_ID=topform-booking-bot
PROJECT_NUMBER=622073906655
REPO=aceboy1016/TOPFORM-Booking-Bot
SA=github-deploy
SA_EMAIL="$SA@$PROJECT_ID.iam.gserviceaccount.com"

gcloud iam service-accounts create "$SA" --project="$PROJECT_ID" \
  --display-name="GitHub Actions deployer"

# --source 配備に必要な権限。ビルド成果物の保存先が未作成なら storage.admin が要る。
for role in roles/run.admin roles/cloudbuild.builds.editor \
            roles/artifactregistry.writer roles/storage.admin \
            roles/iam.serviceAccountUser; do
  gcloud projects add-iam-policy-binding "$PROJECT_ID" \
    --member="serviceAccount:$SA_EMAIL" --role="$role" --condition=None
done

gcloud iam workload-identity-pools create github \
  --project="$PROJECT_ID" --location=global --display-name="GitHub"

# attribute-condition は必須。これが無いと「どのリポジトリからでも」
# このサービスアカウントを借りられてしまう。
gcloud iam workload-identity-pools providers create-oidc github \
  --project="$PROJECT_ID" --location=global --workload-identity-pool=github \
  --display-name="GitHub Actions" \
  --issuer-uri="https://token.actions.githubusercontent.com" \
  --attribute-mapping="google.subject=assertion.sub,attribute.repository=assertion.repository" \
  --attribute-condition="assertion.repository == '$REPO'"

gcloud iam service-accounts add-iam-policy-binding "$SA_EMAIL" \
  --project="$PROJECT_ID" --role=roles/iam.workloadIdentityUser \
  --member="principalSet://iam.googleapis.com/projects/$PROJECT_NUMBER/locations/global/workloadIdentityPools/github/attribute.repository/$REPO"

echo "GCP_WORKLOAD_IDENTITY_PROVIDER=projects/$PROJECT_NUMBER/locations/global/workloadIdentityPools/github/providers/github"
echo "GCP_DEPLOY_SERVICE_ACCOUNT=$SA_EMAIL"
```

## 2. GitHub側の設定

Settings → Secrets and variables → Actions → **Variables**（Secretsではなく
Variables）に、上のechoが出力した2つを登録します。秘密情報ではないため
Variablesで構いません。

| 名前 | 値 |
| --- | --- |
| `GCP_WORKLOAD_IDENTITY_PROVIDER` | `projects/.../providers/github` |
| `GCP_DEPLOY_SERVICE_ACCOUNT` | `github-deploy@topform-booking-bot.iam.gserviceaccount.com` |

`GCP_WORKLOAD_IDENTITY_PROVIDER`が未設定のうちは`deploy`ジョブは
スキップされます。設定前にこのワークフローを取り込んでも配備は起きません。

## 3. 残りの設定

`roles/iam.workloadIdentityUser`だけではトークンを発行できず、
`Permission 'iam.serviceAccounts.getAccessToken' denied`で止まります。
Cloud Shellで次を実行してください。

```sh
gcloud iam service-accounts add-iam-policy-binding github-deploy@topform-booking-bot.iam.gserviceaccount.com --project=topform-booking-bot --role=roles/iam.serviceAccountTokenCreator --member="principalSet://iam.googleapis.com/projects/622073906655/locations/global/workloadIdentityPools/github/attribute.repository/aceboy1016/TOPFORM-Booking-Bot"
```

`gcloud`はローカルに入っていないため、[Cloud Shell](https://console.cloud.google.com/?cloudshell=true&project=topform-booking-bot)で実行します。

## 4. 動作確認

1. `main`へ何かpushする（またはActionsから再実行する）。
2. `Booking regression tests`の`deploy`ジョブが成功することを確認する。
3. ジョブのSummaryに現在のトラフィック配分が出る。`review`タグのリビジョンが
   新しく増え、トラフィックは旧リビジョンのままであることを確認する。

## 5. Cloud Buildトリガーの停止

**4が成功してから**行ってください。先に止めると配備手段が無くなり、
両方動かしたままだと同じpushで2回ビルドされます。

Cloud Buildのトリガー一覧から、`main`への
pushで起動しているトリガー（`rmgpgab-topform-booking-bot-...`）を無効化します。

https://console.cloud.google.com/cloud-build/triggers?project=topform-booking-bot

## 昇格（本番へ反映）

Actionsの`Promote Cloud Run revision`を手動実行します。

- `revision`を空で実行 → 現在のトラフィック配分を表示するだけ
- `revision`にリビジョン名を入れて実行 → そのリビジョンへ100%切り替え

存在しないリビジョン名を渡した場合は、切り替える前に失敗します。

`deploy.sh`は引き続きローカルからの配備手段として残しています。
`TOPFORM_DEPLOY_READY=yes`とクリーンなチェックアウトを要求する点も同じです。
