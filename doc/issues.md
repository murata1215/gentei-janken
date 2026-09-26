# Issues

## 仕様書 v0.1 未決事項（§12.1）

- [ ] §9.3: 全員生還の抜け穴を残すか塞ぐか（塞ぐなら現金ラインか序盤返済禁止か）。config: `survival_cash_min` / `repay_unlock_turn`
- [ ] 利息の計上間隔: 10ターンごと（計12回）か、原作寄りの5ターンごと（計24回）か。config: `interest_interval_turns`
- [ ] 対戦で出した手を公開するか、当事者だけにするか（初期値は当事者だけ）。config: `reveal_hands_publicly`
- [ ] 各プレイヤーの手札枚数を公開するか（初期値は秘匿）。config: `reveal_hand_count`
      ※既知の一方向漏れ: `MATCH_RESOLVED`が当事者両名の勝敗と共にpublicである限り、
      観戦者が全試合分の当事者を集計すれば手札残数を算術的に完全復元できる
      （実ログ`dry_run_seed42_20p`で`cards_destroyed`と全件一致を確認済み、
      サイクル1.7調査時点）。§8.2 L276「掲示板の減り方から手が分かる」と同種の、
      公開情報の組み合わせによる構造的漏れであり、§8.2「対戦の組み合わせと勝敗」の
      公開を維持する限りAPI側では塞げない。Viewer UIは`.god-only`に隔離する運用で
      対応するが、これは秘匿の保証ではなく表示上の配慮に留まる
- [ ] 型Dという名前でよいか
- [ ] 20人のロスター構成（6社×何モデルか）

## ガワ作成（サイクル1.0・完了）

- [x] engine/ 歩く骨格の実装（対戦・利息・退出清算・強制退場・時間切れ）
- [x] llm/ 移植（prompt_builder・response_parser・phase2_schema の新規部分）
- [x] bots/ 最小2種（あいこ連合型・攻撃型）
- [x] viewer/ ログパーサ書き直し + 最小フロント
- [x] tests/ 一式（★ゼロサム・掲示板導出・退出清算・利息のテストを含む、90件PASS）
- [x] dry_run.py で20人×120ターン完走の確認（bots混成で6人生還を確認）
- [x] GitHub push

## LLM対戦の通電・秘匿の穴閉じ（サイクル1.5・完了）

- [x] prompt_builderにcard_id/offer_id/対戦相手候補（alive_player_ids）を実装
      （サイクル1.0は件数だけで、LLMは対戦を1件も成立させられなかった）
- [x] build_action_prompt()をIMPLEMENTED_ACTION_TYPESから動的生成（JSON契約明示）
- [x] engine/game.pyにrepay/transfer/wait処理を追加（ACTION_UNHANDLEDから実処理へ）
- [x] response_parserの型変換異常系（ValueError/TypeError/ValidationError）をParseError化
- [x] llm_agentのリトライで元プロンプトを保持、予約コストをworst_case_cost()経由に変更
- [x] CoT reasoning/emotionの取り出し配線（extract_reasoning_and_emotion → god専用ログ）
- [x] viewerの秘匿情報漏れ修正（_redact_eventをホワイトリスト方式に反転）
- [x] BOARD_UPDATEDイベント追加（掲示板がgetGameState/viewerに反映されない穴を閉じた）
- [x] 実LLM課金トライアルでMATCH_RESOLVED実測確認（$0.0149、6人×20ターンで5件）
- [x] テスト5ファイル新規63件（game_loop/prompt_builder/response_parser/cot/viewer）

## Viewerのweb公開（サイクル1.6・完了）

- [x] server.pyにDEFAULT_HOST/DEFAULT_PORT定数を新設（既定値の単一ソース化、9024→9027）
- [x] `GET /`ルート追加（従来`/watch`のみでトップページが404だった穴を閉じた）
- [x] game_idパスパラメータにパストラバーサル対策の明示的パターン制約を追加
- [x] tests/test_viewer.py 7件追加（20件PASS）
- [x] systemd（`~/.config/systemd/user/gentei-viewer.service`）常駐・enable済み
- [x] 神視点トークンのdrop-in注入（`god-token.conf` + repo外`god.env`）
- [x] 実ログ5試合でview=publicの秘匿情報リーク検証（クリーン確認済み）
- [x] Caddy公開（`gentei-janken-viewer.devrelay.io` → `localhost:9027`）— devrelayプロジェクトへ依頼、reload完了。
      `https://gentei-janken-viewer.devrelay.io/` 200・god view無トークン403を実測確認
- [x] doc/viewer_operations.md（公開運用の正本）を新規作成

## 秘匿情報漏れの緊急修正（サイクル1.6.1・完了）

- [x] `PUBLIC_REASON_CODES`ホワイトリストで`reason`へのcard_id混入（本番42件漏洩）を修正、本番反映
- [x] tests/test_viewer_secrecy.py 18件新規（178件PASS）
- [x] 感情画像42枚を128px化（55.1MB→0.7MB、`scripts/resize_emotions.py`）
- [ ] engine側の恒久対応: `ValueError`をコード化した例外クラス（`engine/errors.py`等）へ
      置き換え、`str(e)`がcard_id等を含まない安定コードのみを返すようにする（次サイクル）

## Step 2以降（次サイクル）

- [ ] 契約型A〜Dの本実装（発行料・状態機械・違反判定）
- [ ] 即時取引の本実装（engine/trades.pyは実装済みだが呼び出し元が無い）
- [ ] DM・全体発言・匿名通信の配送と`_visible_messages()`（tests/test_dm_secrecy.pyも同時に書く）
- [ ] 報奨（Bounty）の実処理
- [ ] Bot残り4種（買い占め型・★仲買型・早期退出型・様子見型）
- [ ] §12.2 Botシミュレーションで未決事項を検証・決定
- [ ] build_action_prompt()にreasoning/emotionの要求を追加するか判断
      （配線済みだが現状プロンプトが要求していないため実測では常に空）

## Viewerの盤面UI化（サイクル1.7・完了）

- [x] `GET /api/games/{id}/board`新設（server側でイベント畳み込み→席・申込索引・
      掲示板時系列を構築、public/god投影も内部で確定）。既存`/state`/`/turns`は凍結・存続
- [x] `viewer/log_parser.py::_fold_events`: 20人×120ターン(1062件)を実測で
      ★/現金/借金/手札枚数がengine記録値と全件一致、★ゼロサム毎ターン検証
- [x] `viewer/static/index.html`全面書き直し（98行→900行弱）: 20席グリッド・
      ★メダリオン・対戦3列レーン・掲示板バー+スパークライン・ドラマ目盛り付き
      トランスポート（スライダー/再生/無風スキップ）・選手詳細モーダル
- [x] `viewer/static/style.css`は529行目以降に追記のみ（先頭529行はdangou-cardと
      バイト一致のままsha256でテスト固定）
- [x] godトークンをsessionStorage化、`403`時に一元downgrade（`forceGodLogout`）。
      旧`prompt()`＋変数保持（リロードで消える）バグを解消
- [x] `VIEWER_REVEAL_IDENTITY`環境変数（never/after_game_end既定/always）でモデル正体の
      public開示ポリシーを制御。seat_map v1/v2両対応ローダ、Bot戦（seat_map無し）は
      identityキー自体を欠落させる
- [x] Playwrightでheadless実ブラウザ検証（コンソールエラー0件、public/godの手の
      開示境界を実測、375px幅でも崩れないことを確認）
- [x] テスト67件新規（fold/board/frontend静的検証）、全224件PASS
- [x] 本番反映・実URLでリーク検証（5試合でcash/debt/hand_*/card_idパターン0件）
- [ ] Phase 4（別サイクル）: ライブポーリング、★移動演出、ペア強調、コストモーダル、
      感情の本配線、実況席の復活

## LLM対戦を成立させる基盤整備（サイクル1.8・完了、Stage 0）

実測でLLM戦がpass率70.8%・対戦0〜5件と機能していなかった原因（★不可視・履歴ゼロ）を
解消する準備段階。DM・取引の通電（Stage 1/2、後続サイクル）の前提。

- [x] `engine/game.py::_build_visible_state`に`opponents`（★・初期借入額・対戦成績、
      §8.2公開情報）を追加。`_record_match_result`で通算成績を積算。既存の
      `alive_player_ids`はbots/が参照するため温存
- [x] `llm/prompt_builder.py::build_opponents_section`を★降順・成績付きテーブル表示に
      書き換え（opponents未提供時はID羅列にフォールバック、後方互換）
- [x] `build_personal_notice`に「余裕ターン数」表示を追加（余裕マイナス時は
      「生還は不可能」と明記）。`say`（ターン非消費の発言）を入れない代わりの設計
- [x] `llm/response_parser.py::extract_memory()`新設、`llm/llm_agent.py`に
      `self._memory`を持たせ次ターン冒頭へ再注入（`llm/phase2_schema.py`の`memory`
      フィールドが定義されながら全リポジトリで参照ゼロだった穴を解消）
- [x] `scripts/analyze_actions.py`新規（`*_llm_calls.jsonl`からaction_type分布・
      pass率、`*_events.jsonl`からイベント件数を集計。各Stageの受け入れ基準を
      数値判定するために使う）
- [x] テスト19件新規、全243件PASS
- [x] 実課金トライアル3本（L6×6・20ターン、$0.072）で実測: **pass率70.8%→5.9%
      （12分の1）、MATCH_RESOLVED 5件→19件中央値（3.8倍）**。memoryは120回中116回
      （97%）で使用され、具体的な計画（利息ターン・借金返済時期等）を記憶し続けた

## DM・全体発言・匿名通信の通電（サイクル1.9・完了、Stage 1）

パーサ・モデル層（21アクション）は既に完成済みで、engine処理本体だけが
ACTION_UNHANDLEDで空だった穴を埋めた。dangou-cardのメッセージ実装（約190行、
ドメイン依存ゼロ）を参考に、gentei側のターン制（120ターンのフラット制＋
wait/wake_on_eventの非同期起床）に合わせて設計し直した。

- [x] `engine/models.py`に`Message`（pydantic）新設。保管は型安全、投影
      （誰に何を見せるか）は`engine/messages.py::visible_messages()`の純関数に分離
- [x] `engine/messages.py`新規: `visible_messages()`はDM本文を当事者以外から
      キーごと削除（空文字上書きではない）、匿名通信の実送信者は`Message`自体に
      一切乗せず`Game._anon_message_owners`（message_idキー。dangou-cardの
      indexキー方式より安全）で別管理
- [x] メッセージは**全ターン全件保持**（削除しない。§5.2「DMが届いたら起こして」と
      起床トリガの寿命を一致させるため）。プロンプト表示は2段フィルタ
      （直近`message_prompt_window_turns`・`message_prompt_limit`件＋自分宛
      未読DMは窓の外でも全件）
- [x] `engine/game.py`: `_handle_dm`/`_handle_broadcast`/`_handle_anonymous_broadcast`
      追加。`_should_wake`にDM到着条件を追加（**全体発言は起床条件に含めない**
      ——1人がbroadcastしただけで待機中の全員が起きるとLLM呼び出しが激増するため、
      §5.2の逐語「DM・対戦申込・取引提案」に忠実に従った）
- [x] `llm/prompt_builder.py::build_messages_section`新規、`build_action_prompt`に
      `config`引数を追加（匿名通信の料金・上限をハードコードせず表示）
- [x] `viewer/log_parser.py`: `DM_SENT`(message除外)/`BROADCAST_SENT`(全公開)/
      `ANONYMOUS_BROADCAST_SENT`(sender除外)のホワイトリスト追加。`_fold_events`の
      turn delta に`messages`を追加
- [x] `viewer/static/index.html`: 席カードに発言の吹き出しを追加、フッタに
      メッセージティッカー。Playwrightで実機確認（public: DM本文非表示・全体発言
      表示、god: DM本文も表示、コンソールエラー0件）
- [x] テスト36件新規（`test_dm_secrecy.py`・`test_messages.py`新規、
      `test_viewer_secrecy.py`に6件追加）、全279件PASS
- [x] 実課金トライアル3本（L6×6・20ターン、$0.093）で実測: **pass率0.9%
      （中央値）、MATCH_RESOLVED 23件（中央値、Stage 0の19件から減っていない
      ＝「喋ると殴れない」問題は発生せず）、発言6件（中央値）**。broadcastで
      「全員に提案。カード12枚に対し残り19ターンでは全員生還不可能。同時多発
      対戦をしないか」という具体的な協調の呼びかけが自発的に発生した。
      DM・匿名通信は0件（20ターンでは全員が同じ危機に直面するため全体呼びかけが
      優先された可能性。120ターンの本番で変化するか要観察）
