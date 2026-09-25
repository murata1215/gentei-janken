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

## Step 2以降（次サイクル）

- [ ] 契約型A〜Dの本実装（発行料・状態機械・違反判定）
- [ ] 即時取引の本実装
- [ ] Bot残り4種（買い占め型・★仲買型・早期退出型・様子見型）
- [ ] §12.2 Botシミュレーションで未決事項を検証・決定
- [ ] systemd（gentei-viewer.service）・Caddy公開
