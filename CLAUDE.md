See `rules/devrelay.md` for DevRelay rules.

---

# 嘘八百万 —限定ジャンケン—

AI 20体が120ターンの1対1ジャンケンでカードと★を奪い合い、借金を清算して生還を目指す対戦ゲーム。
嘘八百万シリーズ第2ゲーム（第1ゲームは `dangou-card`）。

See `rules/project.md` for project-specific rules.
See `doc/spec/gentei_janken_v0_1.md` for the game specification (single source of truth).

## 技術スタック

| 項目 | 値 |
|---|---|
| 言語 | Python 3.12 |
| パッケージ管理 | uv |
| スキーマ | pydantic v2 |
| テスト | pytest |

## ビルド & テスト

```bash
uv sync                          # 依存インストール
uv run pytest tests/ -v          # テスト実行
uv run python scripts/dry_run.py # ドライラン（20人版）
uv run python scripts/simulate.py --games 1000  # 1000試合シミュレーション
```

## 主要ディレクトリ

| パス | 内容 |
|---|---|
| `engine/` | ルールエンジン本体 |
| `bots/` | ルールベースBot |
| `llm/` | LLMアダプタ・エージェント（6社対応） |
| `tests/` | 受け入れテスト + Bot/シミュレーション/LLMテスト |
| `scripts/` | ドライラン・シミュレーション・LLM試験スクリプト |
| `viewer/` | 観戦WebUI（FastAPI, 127.0.0.1:9024） |
| `doc/` | 仕様書 |
| `logs/` | JSONLイベントログ・シミュレーション結果出力先 |
