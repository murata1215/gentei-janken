# 嘘八百万 —限定ジャンケン—

AI 20体が120ターンの1対1ジャンケンでカードと★を奪い合い、借金を清算して生還を目指す対戦ゲーム。
嘘八百万シリーズ第2ゲーム（第1ゲームは [dangou-card](../dangou-card)）。

原作『賭博黙示録カイジ』の「限定ジャンケン」をLLM対戦用に再現する。
仕様の正本は [`doc/spec/gentei_janken_v0_1.md`](doc/spec/gentei_janken_v0_1.md)。

## 現在のステータス

本リポジトリは dangou-card のエンジン基盤を移植した「ガワ」段階（歩く骨格）。
実装済みなのは初期配布・借入・120ターンループ・対戦の申込〜開示・★の移動・
残数掲示板・利息計上・退出清算・強制退場・時間切れのみ。契約（型A〜D）・
即時取引・匿名通信・報奨・DMは型とイベントの定義のみで、実処理は次サイクル。
未決事項は [`doc/issues.md`](doc/issues.md) を参照。

## セットアップ

```bash
uv sync
```

## テスト実行

```bash
uv run pytest tests/ -v
```

## ドライラン

```bash
uv run python scripts/dry_run.py --seed 42          # StubAgent（何もしない）
uv run python scripts/dry_run.py --seed 42 --bots   # bots/のロスターで対戦
```

## Botシミュレーション（LLM不使用、コスト0）

```bash
uv run python scripts/simulate.py --games 1000 --seed 42
```

## LLMトライアル（本番API使用）

```bash
bash scripts/run_trial.sh --roster "L1,L1,M3,M3,H1,H1" --seed 504
bash scripts/check_trial.sh
```

## 観戦ビューア

```bash
VIEWER_PORT=9024 uv run python -m viewer
curl http://127.0.0.1:9024/api/games
```

## プロジェクト構成

| パス | 内容 |
|---|---|
| `engine/` | ルールエンジン本体 |
| `bots/` | ルールベースBot（DrawAlliance / Aggressor の2種） |
| `llm/` | LLMアダプタ・エージェント（6社対応、dangou-cardから移植） |
| `tests/` | ユニットテスト一式 |
| `scripts/` | ドライラン・シミュレーション・LLM試験スクリプト |
| `viewer/` | 観戦WebUI（FastAPI） |
| `doc/spec/` | 仕様書（正本） |
