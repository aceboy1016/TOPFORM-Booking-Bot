#!/bin/bash
# TOPFORM Booking Bot - Deploy Script
# Usage: ./deploy.sh "コミットメッセージ"
# Usage: ./deploy.sh (メッセージなしの場合はデフォルトメッセージ)

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

SERVICE_NAME="topform-booking-bot"
REGION="asia-northeast1"
SERVICE_URL="https://topform-booking-bot-622073906655.asia-northeast1.run.app"

echo -e "${YELLOW}🚀 TOPFORM Booking Bot デプロイ開始${NC}"
echo "================================================"

# 1. Git commit & push
COMMIT_MSG="${1:-auto: deploy $(date '+%Y-%m-%d %H:%M')}"
echo -e "\n${YELLOW}📦 Git: コミット & プッシュ${NC}"
git add -A
git commit -m "$COMMIT_MSG" || echo "No changes to commit"
git push

# 2. Deploy to Cloud Run
echo -e "\n${YELLOW}☁️  Cloud Run: デプロイ中...${NC}"
gcloud run deploy $SERVICE_NAME --source . --region $REGION --quiet

# 3. Health check
echo -e "\n${YELLOW}🏥 ヘルスチェック...${NC}"
sleep 5  # Wait for container startup

HEALTH=$(curl -s "$SERVICE_URL/health" 2>/dev/null)

if echo "$HEALTH" | grep -q '"healthy"'; then
    echo -e "${GREEN}✅ デプロイ成功！サーバーは正常に稼働中${NC}"
    echo "$HEALTH" | python3 -m json.tool 2>/dev/null || echo "$HEALTH"
else
    echo -e "${RED}❌ ヘルスチェック失敗！ログを確認してください${NC}"
    echo "Response: $HEALTH"
    echo ""
    echo "ログ確認: gcloud run services logs read $SERVICE_NAME --region $REGION --limit 20"
    exit 1
fi

echo ""
echo "================================================"
echo -e "${GREEN}🎉 完了！${NC}"
echo "Service URL: $SERVICE_URL"
