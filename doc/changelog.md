# Changelog

## 2026-09-26: サイクル1.8: LLM対戦を成立させる基盤整備（★可視化・memory配線）

ユーザーから「ゲーム開始できるのかな」と聞かれ調査したところ、既存LLM戦の実測が
pass率70.8%・対戦0〜5件（4本中3本が対戦0件・全員TIMEOUT）と、ゲームとして
機能していないことが判明した。原因を「①他プレイヤーの★がプロンプトに無い
（`build_opponents_section`がID羅列のみ）②毎ターン記憶を失う（`memory`フィールドが
定義されながら参照ゼロ）」の2点と特定し、DM・取引の通電（Stage 1/2）に進む前に
まずこれを解消した。

- **`engine/game.py`**: `_build_visible_state`に`opponents`
  （★・初期借入額・対戦成績、§8.2公開情報）を追加。`_record_match_result()`で
  対戦成績を通算積算（`MatchOffer`には結果が残らないため）。既存の
  `alive_player_ids`はbots/aggressor_bot.py・draw_alliance_bot.pyが参照するため
  そのまま温存し、`opponents`は追加のみ。
- **`llm/prompt_builder.py`**: `build_opponents_section`を★降順・勝敗数付きテーブル
  表示に書き換え。`build_personal_notice`に「カードを使い切るのに最低限必要な
  ターン数（残り{X}ターン → 余裕{Y}ターン）」を追加、余裕がマイナスなら
  「生還は不可能」と明記。`say`（ターンを消費しない一言）を入れる代わりの設計判断
  （§5.1「1ターン1アクション」の逐語を守りつつ、pass の機会費用を可視化する）。
- **`llm/response_parser.py`**: `extract_memory()`を新設。`llm/llm_agent.py`に
  `self._memory`を持たせ、LLM応答の`memory`フィールドを次ターンのプロンプト冒頭
  「## 前ターンまでのあなたのメモ」として再注入する。reasoning/emotionと同じ
  抽出経路だが扱いは正反対（reasoningは永久に秘匿、memoryは意図的に本人へ差し戻す）。
- **`scripts/analyze_actions.py`**（新規）: `*_llm_calls.jsonl`のresponse_textから
  action_type分布・pass率を、`*_events.jsonl`からイベント種別件数を集計する。
  以降のStage 1/2の受け入れ基準判定に使う。
- **テスト**: 19件新規（`test_game_loop.py`のopponents検証、`test_prompt_builder.py`
  の★テーブル・余裕表示、`test_response_parser.py`のextract_memory、新規
  `test_llm_agent_memory.py`のプロンプト再注入検証）。全243件PASS。
- **実課金トライアル3本**（`L6,L6,L6,L6,L6,L6`・20ターン・$0.072）で実測:
  pass率が70.8%→**5.9%（中央値、12分の1）**、MATCH_RESOLVEDが5件→**19件
  （中央値、3.8倍）**。memoryは120回中116回（97%）で使用され、利息ターンや
  借金返済計画を含む具体的な申し送りが次ターンに引き継がれることを確認した。
  （20ターン設定では手札12枚を使い切るのに最低24ターン必要なため生還0人は
  想定どおり。120ターンの本番では問題にならない）

## 2026-09-26: サイクル1.7: Viewerの盤面UI化（dangou-card相当へ）

サイクル1.6で公開したViewerは98行のJSON羅列スタブだった。dangou-card相当の
盤面UI（20席グリッド・★・掲示板・対戦の可視化・ターン送り）に作り直した。

- **`viewer/log_parser.py`**: `_fold_events()`を新設。public/godいずれの表示でも
  イベント列は自己完結していない（`MATCH_ACCEPTED`にchallenger_idが無い等）ため、
  畳み込みは常にgod完全体のイベント列に対して行い、結果を`_project_seat()`/
  `_project_offer()`/`_project_turn()`でpublic/godへ投影する構成にした
  （フロントに秘匿判定ロジックを持たせない）。`PUBLIC_SEAT_KEYS`/`PUBLIC_OFFER_KEYS`/
  `PUBLIC_TURN_SEAT_KEYS`を新設し、`matches_resolved`/`hand_total`等は意図的に
  publicの席オブジェクトから除外（§8.2の手札枚数秘匿を守るため。既知の一方向漏れは
  `doc/issues.md`に記録）。`derivation`オブジェクトで畳み込みの自己検証
  （★ゼロサム・engine記録値との突き合わせ）をレスポンス自体に埋め込んだ。
  `load_identities()`でseat_map v1/v2両対応、`board_fingerprint()`でETag用の
  mtime+sizeフィンガープリントを追加。
- **`viewer/server.py`**: `GET /api/games/{game_id}/board`を新設
  （`?view=public|god&from_turn=N`、`If-None-Match`で304対応）。
  `VIEWER_REVEAL_IDENTITY`環境変数（never/after_game_end既定/always）でプレイヤーの
  正体を出す条件を制御。既存`/state`/`/turns`は凍結・存続（監査用）。
- **`viewer/static/index.html`**（98行→900行弱）: 全面書き直し。20席グリッド
  （★メダリオン・戦績・生死バッジ・対戦中インジケータ）、対戦3列レーン
  （申込→受諾→開示のパイプライン表示）、残数掲示板（バー+SVGスパークライン）、
  ★勢力図、トランスポート（◀▶/スライダー/再生/無風スキップ/ドラマ目盛り）、
  選手詳細モーダル、godトークンのsessionStorage化を実装。円形配置は却下し既存の
  CSS Grid（`repeat(auto-fit, minmax(300px,1fr))`）を踏襲、密度トグルで
  `minmax(230px,1fr)`にも切替可能にした。感情アイコンは枠のみ用意（データが
  常にnullのため描画しない。「平静を捏造しない」方針を踏襲）。
- **`viewer/static/style.css`**: 529行目以降に追記のみ（先頭529行はdangou-cardと
  バイト一致のままsha256でテスト固定、`tests/test_viewer_frontend.py`）。
- **フロントエンドで発見・修正したバグ**: `matches_resolved`/`wins`/`losses`/`draws`が
  serverのpublic投影から意図的に除外されているため、これらをそのままpanel表示に
  使うと戦績が常に0のまま更新されなかった。`board.offers`（申込id→当事者・勝敗の
  索引、§8.2により public でも全件配信）から都度計算する方式に変更して解消
  （既に公開されている情報の集計であり、隠す意味が無い）。GODモード切替時に
  ターン位置がリセットされる不具合もPlaywright実機検証で発見し修正。
- **テスト**: `tests/test_viewer_fold.py`（bots混成の実ゲームをtmp_pathで実行し
  ★/現金/借金/手札枚数がengine記録値と全件一致することを複数シードで検証。
  `logs/`がgitignoreでもskipif不要、20人×120ターンが実測約数十msで完走）、
  `tests/test_viewer_board.py`（public/god投影境界・identity開示ポリシー・ETag・
  from_turn）、`tests/test_viewer_frontend.py`（HTML内`getElementById`とid属性の
  突合、外部CDN不使用、静的アセット参照の実在確認、style.css先頭529行のsha256固定）
  を新規67件追加。全224件PASS。
- **実機検証**: Playwright（headless Chromium）で実際にレンダリングし、
  コンソールエラー0件、public/godでの手の開示境界（`🔒封`⇔`✊グー`等）を実測、
  375px幅でも崩れないことを確認。本番反映後、実URLで5試合ぶんcash/debt/
  hand_*/card_idパターンが0件であることを再確認。

## 2026-09-26: サイクル1.6.1: 秘匿情報漏れの緊急修正（reasonへのcard_id混入）

盤面UI化（サイクル1.7）の調査中に、**本番公開中のViewerで秘匿情報が漏れている**ことを発見し、
他の作業から切り離して単独で即修正・デプロイした。

`MATCH_ACCEPT_REJECTED`/`MATCH_OFFER_REJECTED` の `reason` に `str(ValueError)` が
そのまま入っており（`engine/matches.py`/`engine/player.py` の `reserve_card()` 等が
card_id入りのメッセージを送出）、実ログに
`"reason": "P18 already has card P18_PAPER_1 reserved"` が**42件**存在した。
card_idから手の種類（PAPER）が読め、§8.2秘匿「手札の中身」「封をした提出中の手」を
直接侵害していた。`reason` は複数イベント種別で**キーとしては**public許可されているが、
**値が自由文字列**という、ホワイトリスト方式の穴だった。

- **`viewer/log_parser.py`**: `PUBLIC_REASON_CODES`（定数コード文字列の集合）を新設し、
  `_sanitize_reason()` で `reason` の値がこの集合に無ければ**キー自体を削除**する
  （空文字上書きではなくキー欠落。`rules/project.md`「DM本文はキーごと削除」と同じ方式を
  値単位に拡張）。`_redact_event()` に組み込み。
- **`tests/test_viewer_secrecy.py`**（新規18件）: 本番実害の実例をそのまま再現して
  card_idパターンが0件になることを直接ガード。既知コードは通ることも確認。
- **本番反映**: 修正前は実ログ`dry_run_seed42_20p`で42件漏洩していたことを`git stash`で
  再現確認 → 修正適用後は同ログで0件 → `systemctl --user restart gentei-viewer.service`で
  即時反映 → `https://gentei-janken-viewer.devrelay.io/`のpublic viewで実測0件、
  god viewでは正しく14件見えることを確認。
- **`scripts/resize_emotions.py`**（新規）: 感情画像42枚（1254×1254、合計55.1MB）を
  128px版に縮小し`viewer/static/emotions/128/`に生成（合計0.7MB、約78分の1）。
  公開済みViewerのegress対策。原寸は削除しない。

テスト: 178件PASS（既存160件＋新規18件）。

## 2026-09-26: サイクル1.6: Viewerのweb公開（systemd + Caddy）

観戦Viewer（FastAPI）をdangou-cardと同じ構成（uso8m常駐systemd + Caddyリバースプロキシ）
でweb公開した。既定ポート9024が`chrome-bookmark.devrelay.io`と衝突していたため9027へ
変更し、トップページ（`/`）が存在せず404になる欠落も修正した。

- **`viewer/server.py`**: `DEFAULT_HOST`/`DEFAULT_PORT`定数を新設し既定値の単一ソース化
  （`127.0.0.1`/`9027`。dangou-cardの「code既定9025/本番9023のズレ」の教訓を踏まえ、
  unitの`Environment=`では上書きしない）。`GET /`を追加（従来`/watch`のみで公開直後の
  トップページが404だった）。`game_id`パスパラメータに`^[A-Za-z0-9_.\-]+$`の
  パターン制約を追加（パストラバーサル対策の明示的な塞ぎ込み）。
- **`tests/test_viewer.py`**: 7件追加（`/`疎通、既定値ドリフト検知、未知イベント種別の
  deny-by-default、god専用ログ非露出、staticトラバーサル拒否、game_idパストラバーサル404）。
- **常駐・公開**: `~/.config/systemd/user/gentei-viewer.service`（uso8mユーザー、
  `127.0.0.1:9027`、Restart=always）を新規作成しenable。神視点トークンは
  dangou-card同様drop-in（`gentei-viewer.service.d/god-token.conf` →
  `~/.config/gentei-viewer/god.env`、repo外・0600）で注入。Caddy側
  （`/etc/caddy/sites.d/gentei-janken-viewer.devrelay.io` → `reverse_proxy localhost:9027`）
  は`devrelay`プロジェクトへ依頼。dangou-cardと異なり`log_skip`/`handle_errors`は
  付けない（現行UIにポーリングが無くアクセスログが肥大しないため、placeholder用の
  devrelayユーザー領域も未整備のため）。
- **リーク検証**: 実ログ5試合（`logs/llm/*_events.jsonl`）に対し`view=public`で
  `challenger_hand`/`old_debt`/`final_assets`（試合未終了分）等の秘匿キーが
  一切出力されないことを実測確認。`final_assets`はGAME_END後のみ公開キーとして
  現れることを確認（設計どおり）。`*_llm_calls.jsonl`/`*_seat_map.json`は
  `/api/games`一覧に一切出ないことを確認。

## 2026-09-26: サイクル1.5: LLM対戦の通電・秘匿の穴閉じ

サイクル1.0の歩く骨格はBot対戦は完動していたが、LLM対戦は構造的に1試合も成立しない
状態だった（プロンプトがcard_id/offer_id/対戦相手候補を件数だけで渡し、JSON契約を
明示していなかったため）。実際に有料APIで1試合が成立するところまで通電し、課金
トライアルが1回の不正応答で落ちないようにし、Viewerの秘匿情報漏れを閉じた。

- **`llm/prompt_builder.py`**: 手札card_id・届いている/出している申込のoffer_id・
  対戦相手候補（alive_player_ids）・清算後順位見込みを実際の識別子として渡すように
  書き直した。`build_action_prompt()`は`llm/phase2_schema.py`に新設した
  `IMPLEMENTED_ACTION_TYPES`（本サイクルでengineが実処理する9種のみ）から
  `action_type`キー・必須フィールド・例JSONを動的生成する構成に変更。
- **`engine/game.py`**: `_apply_action`にrepay/transfer/waitの3ハンドラを追加
  （§7.5送金・任意返済、§5.2待機）。waitは`self._waiting`辞書で管理し、起床条件
  （until_turn到達 or 対戦申込の到着）を満たさない限りLLMを呼ばずにターンを飛ばす。
  毎ターン末に`BOARD_UPDATED`イベントを追加（§8.1掲示板がviewerに一度も反映されて
  いなかった穴を閉じた）。清算後資産の順位（§5.3 7項目目）を`_projected_rank()`で算出。
- **`llm/response_parser.py`**: `_convert_action`のディスパッチをtry/exceptで包み、
  int()/dict()/list()の型変換失敗やpydantic ValidationErrorをParseError（リトライ対象）
  に変換。`extract_reasoning_and_emotion()`を新設し、god専用ログにのみ渡す配線を追加
  （Actionオブジェクト自体には型として存在しないため構造的に混入しない）。
- **`llm/llm_agent.py`**: リトライ時に元プロンプト（状態・アクション一覧）を保持した
  まま是正指示を追記する方式に変更（従来は是正メッセージだけの単発送信で2回目以降の
  リトライがほぼ確実に失敗していた）。予約コストを固定0.05ドルから
  `worst_case_cost()`経由に変更、実ターン番号をログに渡すようにした。
- **`viewer/log_parser.py`**: `_redact_event`をブラックリストからホワイトリスト方式
  （`PUBLIC_EVENT_DATA_KEYS`）に反転。`challenger_hand`/`opponent_hand`/`old_debt`/
  `new_debt`/`cash_before`等の秘匿情報をpublic viewから排除し、退出者の`final_assets`
  はGAME_END後にのみ公開する分岐を追加。`viewer/server.py`の`/api/games/{id}/state`
  にも`view`引数を追加。
- **`scripts/llm_trial.py`**: コスト上限を引数化（`--per-player-cap-usd`/
  `--game-cap-usd`）。20人×120ターンの場合は`GameConfig.default_20()`を使う分岐を
  追加（`dev_small()`固定だと将来default_20()のパラメータ変更が伝播しない事故を
  `scripts/dry_run.py`と同じパターンで防止）。
- **`tests/`**: 5ファイル新規63件（`test_game_loop.py` `test_prompt_builder.py`
  `test_response_parser.py` `test_cot.py` `test_viewer.py`）。

### 実機検証で発見・修正した新規バグ

LLM（deepseek-v4-flash）が`{"action_type": "wait"}`とだけ返す（until_turn/
wake_on_eventのどちらも省略）応答を実際に返し、`_should_wake()`が永久にFalseを
返すため以後一切行動できなくなる実害が発生した（そのプレイヤー宛の対戦申込3件が
誰にも受諾されず終わった）。`llm/response_parser.py`でwaitの両条件省略をParseError
化してリトライさせ、`engine/game.py::_handle_wait`でuntil_turnがtotal_turnsを
超える場合にクランプする二重の安全策を追加した。

### 実機検証結果

`uv run pytest tests/ -v`で153/153 PASS（既存90 + 新規63）。`scripts/dry_run.py
--bots`で20人×120ターン完走、`ACTION_UNHANDLED`が10件→0件に（repay/transfer/wait
が実処理されるようになったため）。実際に課金APIで検証: 6人×20ターンで
**MATCH_RESOLVED 5件**（draw 1件を含む）を実際のLLM応答で確認（費用$0.0149。
修正前は構造上0件）。Viewerを別ポートで起動し、`view=public`のレスポンスに
秘匿キーが一切現れないこと、`view=god`のトークン検証（403/200）を実機確認。

### スコープ外（次サイクル）

契約（型A〜D）・即時取引・DM・全体発言・匿名通信・報奨は型とイベントの定義のみで、
実処理は次サイクル。`tests/test_dm_secrecy.py`もDM本実装と同時に書く
（実装が無い状態で書くと「実装が無いから通る」テストになるため）。

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
