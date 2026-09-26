# Issues

## 仕様書 v0.1 未決事項（§12.1）

- [ ] §9.3: 全員生還の抜け穴を残すか塞ぐか（塞ぐなら現金ラインか序盤返済禁止か）。config: `survival_cash_min` / `repay_unlock_turn`
- [ ] 利息の計上間隔: 10ターンごと（計12回）か、原作寄りの5ターンごと（計24回）か。config: `interest_interval_turns`
- [ ] 対戦で出した手を公開するか、当事者だけにするか（初期値は当事者だけ）。config: `reveal_hands_publicly`
- [ ] 各プレイヤーの手札枚数を公開するか（初期値は秘匿）。config: `reveal_hand_count`
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

## Step 2以降（次サイクル）

- [ ] 契約型A〜Dの本実装（発行料・状態機械・違反判定）
- [ ] 即時取引の本実装（engine/trades.pyは実装済みだが呼び出し元が無い）
- [ ] DM・全体発言・匿名通信の配送と`_visible_messages()`（tests/test_dm_secrecy.pyも同時に書く）
- [ ] 報奨（Bounty）の実処理
- [ ] Bot残り4種（買い占め型・★仲買型・早期退出型・様子見型）
- [ ] §12.2 Botシミュレーションで未決事項を検証・決定
- [ ] build_action_prompt()にreasoning/emotionの要求を追加するか判断
      （配線済みだが現状プロンプトが要求していないため実測では常に空）
- [ ] systemd（gentei-viewer.service）・Caddy公開
