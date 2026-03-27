# TOPFORM LINE Bot - Project Overview

## 📍 プロジェクト概要
TOPFORM（石原淳哉トレーナー）の公式LINE予約管理システム。
LINE Messaging APIを通じて、クライアントからの予約・変更・キャンセル・空き状況確認を自動化する。

## 🎯 主な機能
- **チャット予約**: 対話型フローによる仮予約受付。
- **予約確認**: 自分の今後の予定を表示（DB + Calendar）。
- **早見表連携**: Web版早見表（ishihara-booking）へのリンク。
- **キャンセル待ち自動チェック**: スプレッドシートと連携し、空きが出たらプッシュ通知。
- **管理者通知**: 予約・キャンセル・見送り発生時に石原トレーナーへ通知。

## 🏗️ 技術スタック
- **Backend**: FastAPI (Python 3.9+)
- **LINE API**: line-bot-sdk v3
- **Infrastructure**: Google Cloud (Cloud Run)
- **External API**: Google Calendar API, Google Sheets API
- **Database**: SQLite (topform_line.db)
- **Tooling**: venv, deploy.sh

## 📁 重要なファイル
- `main.py`: エントリーポイント、FastAPIアプリ定義。
- `config.py`: 設定管理、定数（営業時間等）。
- `line_service.py`: LINEメッセージ処理ロジック。
- `calendar_service.py`: Google Calendar連携・空き判定ロジック。
- `sheets_service.py`: Google Sheets（顧客・キャンセル待ち）連携。
- `database.py`: SQLite操作、セッション管理。
- `deploy.sh`: Cloud Runへのデプロイ・プッシュスクリプト。

## 🛠️ 開発・運用ルール
- **デプロイ**: `deploy.sh` を使用。自動的に `git push` と `gcloud run deploy` が行われる。
- **キャッシュ**: `line_service` 内でカレンダー情報を1分間キャッシュ。
- **2ヶ月ルール**: 2ヶ月先までの予約のみ受付。
- **3時間デッドライン**: 3時間以内のキャンセルは管理者通知。
- **12時間デッドライン**: 12時間以内のキャンセルは「1回消化」扱い。

---
*このファイルは Claude Code がプロジェクトの文脈を即座に理解するためのものです。内容を更新した際は、適宜同期してください。*
