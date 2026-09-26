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
