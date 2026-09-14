#!/bin/bash
# Deploy only an already committed, tested checkout. Does not commit or push.
set -euo pipefail
PROJECT_ID="topform-booking-bot"
SERVICE_NAME="topform-booking-bot"
REGION="asia-northeast1"
cd "$(dirname "$0")"
if [[ -n "$(git status --porcelain)" ]]; then
  echo "Commit or stash changes before deployment." >&2
  exit 1
fi
if [[ "${TOPFORM_DEPLOY_READY:-}" != "yes" ]]; then
  echo "Complete docs/ROLLOUT.md, then explicitly set TOPFORM_DEPLOY_READY=yes." >&2
  exit 1
fi
PYTHON_BIN="${TOPFORM_PYTHON:-venv/bin/python}"
"$PYTHON_BIN" -m pytest -q
gcloud run services describe "$SERVICE_NAME" --project "$PROJECT_ID" --region "$REGION" \
  --format=json | "$PYTHON_BIN" scripts/check_deploy_config.py
gcloud run deploy "$SERVICE_NAME" --project "$PROJECT_ID" --region "$REGION" \
  --source . --no-traffic --tag review --quiet
echo "Review revision deployed with no default traffic. Verify docs/ROLLOUT.md before promoting."
