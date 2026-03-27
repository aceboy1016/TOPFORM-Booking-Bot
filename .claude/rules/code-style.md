# Code Style Rules

## 🐍 Python / FastAPI Coding Style

### 一般原則
- **型ヒント (Type Hints)**: 可能な限り引数と戻り値に型ヒントを記述すること。
- **非同期処理 (Async)**: FastAPIの性質を活かし、DBアクセスや外部API連携には `async/await` を使用すること。
- **例外処理**: 重要な外部連携（GCal, Sheets）には適切な `try-except` を入れ、エラーログを出力すること。

### ファイル構成の役割
- `calendar_service.py`: カレンダーの読み取り専用。書き込みロジックを追加する場合は慎重に行う。
- `line_service.py`: LINE API特有のFlex Message定義などはこの中の private メソッドにまとめる。
- `config.py`: ハードコーディングを避け、定数はすべてここに集約する。

### LINE Bot固有のルール
- Flex Messageの `altText` は必ず設定すること（通知プレビュー用）。
- 返信が必要なイベントには必ず `reply_token` を使用すること。
