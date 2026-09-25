# Changelog

## 2026-09-25: サイクル1.0: プロジェクト新設・ガワ作成

嘘八百万シリーズ第2ゲーム「限定ジャンケン」を新規プロジェクトとして立ち上げ、
dangou-cardの完成済み基盤を移植し、仕様書v0.1（ドラフト）に沿った歩く骨格を実装した。

- **DevRelay登録**: scaffold APIで`gentei-janken`を`empty`テンプレートで新規登録（マシン`ubuntu-prod/uso8m`）。
- **`llm/`**: `adapters.py` `models.py` `costing.py` `constants.py` `llm_logger.py`
  `game_cost_budget.py` `providers/devrelay_http.py`（計約2,400行）を、`engine/`に依存しない
  自己完結したLLMクライアント層としてほぼ逐語コピー。ゲーム固有だった`CODEX_SOLO_PLAYER_LINE`
  周辺のコメントのみ「談合カード」→「限定ジャンケン」に差し替え。
- **`engine/`**: 仕様書§1〜§8に基づき新規実装。`models.py`（Hand/Card/PlayerState/
  MatchOffer/MatchResult/TradeProposal/Contract/Obligation/Bounty/21種のAction判別union）、
  `config.py`（§11の確定パラメータ+§12.1未決事項をconfigフラグとして両論併記）、
  `judge.py`（勝敗表）、`cards.py`（掲示板は独立カウンタを持たず手札合計から導出）、
  `player.py`（カード/★/現金操作、利息1.5%複利切り上げ）、`matches.py`（申込→受諾→開示の
  2ターン制対戦）、`exit_rules.py`（§6.1退出条件4つ・§6.2清算4ステップ）、
  `elimination.py`（§6.3強制退場・§6.4時間切れの強制清算、dangou-card v0.5§1.6を移植）、
  `finance.py`（利息計上ターン判定）、`trades.py`（即時取引の原子的決済）、
  `contracts.py`（契約作成の骨格。型A〜Dの執行・監査は次サイクル）、`game.py`（120ターンの
  ターンループ本体、§5.1の8ステップ）、`events.py`/`rng.py`（dangou-cardから移植）。
- **`bots/`**: `DrawAllianceBot`（あいこ連合型、§9.3の抜け穴を実装）・`AggressorBot`
  （攻撃型）の2種を新規実装。§12.2の残り4種（買い占め型・★仲買型・早期退出型・様子見型）は次サイクル。
- **`llm/prompt_builder.py`**: §10の目的文（逐語）・§5.3の個別通知7項目・§8.1の残数掲示板・
  §5.2のアクション選択指示の4関数を新規実装。
- **`llm/response_parser.py`**: `extract_json()`等の汎用部分をdangou-cardから移植し、
  §5.2の21アクション種への変換（`_convert_action`）を新規実装。
- **`llm/phase2_schema.py`**: フラットなStructured Outputスキーマを新規実装
  （action_typeで意味が変わるフィールドを全てoptionalにし、response_parser側で検証）。
- **`llm/llm_agent.py`**: dangou-cardのリトライ・予算予約・ログ連携の足場を移植し、
  呼び出すプロンプト関数をprompt_builderの4関数に絞った新規実装。
- **`viewer/`**: `server.py`はdangou-cardのpublic/god 2段認証パターンをそのまま流用
  （既定ポートを9024に統一。dangou-cardは code既定9025/本番9023がズレていた教訓を踏まえる）。
  `log_parser.py`はmtime差分キャッシュのLogCacheパターンを踏襲した新規実装。
  `static/index.html`は最小新規（試合セレクタ・ターン別イベント表示）。
  `static/emotions/`42枚（56MB）をコピー。
- **`scripts/`**: `dry_run.py`（StubAgent/botsロスター切替）・`run_trial.sh`（デタッチ起動、逐語）・
  `check_trial.sh`（新イベント形式対応）・`simulate.py`（multiprocessing Pool、CSV出力）・
  `llm_trial.py`（座席マップ生成・本番API実行）を新規整備。
- **`tests/`**: 90件新規作成（`test_judge.py` `test_cards.py` `test_stars.py` `test_match.py`
  `test_exit.py` `test_finance.py` `test_elimination.py` `test_contracts.py` `test_smoke.py`
  はゲーム固有ロジック、`test_devrelay_http.py`はdangou-cardから移植し実API 0コールで31件PASS）。

### 開発中に見つけた2件のバグ

1. **`PlayerState.reserved_card_id`（単一フィールド）の設計不備**: 仕様書§4.3が制限するのは
   「自分が出せる申込は1件まで」のみで「受け取れる申込の数」に上限はないため、1人が
   「自分の申込（カードA予約）」と「相手の申込を受諾する（カードB予約）」を同時に持てる必要が
   あった。単一フィールドではこれが不可能で、DrawAllianceBot20体のみのシミュレーションで
   対戦が0件しか発生しない現象として発覚。`reserved_card_ids: list[str]`に変更して解消
   （修正後は117試合中matches=117件、全てdraw、★総和不変を確認）。
2. **`httpx` vs `httpx2` 依存の潜在バグ**: 新規`uv sync`で解決されたanthropic/openai SDKの
   最新バージョンが、実際の`httpx`パッケージではなく`httpx2`という別名パッケージを依存に
   含めていたため、`llm/providers/devrelay_http.py`が実行時（DevRelay実API呼び出し時）に
   `ModuleNotFoundError: No module named 'httpx'`で落ちる状態だった。`pyproject.toml`に
   `httpx>=0.28.1`を直接依存として追加して解消。

### 未決事項（§12.1、`doc/issues.md`で管理）

生還の抜け穴（§9.3）・利息計上間隔・手の公開範囲・手札枚数の公開・型Dの命名・
20人ロスター構成の6件は、いずれもconfigフラグとして両論併記に留め、
§12.2のBotシミュレーションで検証してから次サイクルで確定する。

テスト: `uv run pytest tests/ -v` で90/90 PASS。`scripts/dry_run.py --bots`で
20人×120ターン完走、6人生還を確認。
