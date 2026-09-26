# プロジェクト固有ルール

本プロジェクトは `dangou-card`（嘘八百万—談合カード—）の設計規律を踏襲する。
仕様の正本は `doc/spec/gentei_janken_v0_1.md`。実装より仕様書が優先する。

## devlog追記ルール

タスク(ビルド)完了時、**1サイクル＝1ファイル**で開発記録を新規作成すること。
既存 devlog への追記・全文読み込みは禁止（コンテキスト肥大の原因になるため）。

- 保存先: `doc/devlog/` 配下
- ファイル名: `doc/devlog/YYYY-MM-DD_HHMMSS.md`
  （`TZ=Asia/Tokyo date '+%Y-%m-%d_%H%M%S'` を使う。コロン `:` はファイル名に使わない）
- 中身の形式: 冒頭に `# YYYY-MM-DD HH:MM JST ｜ サイクルX.X: タスク名`、
  本文に 要求 / 実行 / 検証 / 発見 を平文3〜10行。数値は具体値で記す。
- 索引の更新: 作成のたび `doc/devlog/INDEX.md` の末尾に1行だけ追記する。
- 過去ログの参照: 経緯が必要なときのみ、まず `doc/devlog/INDEX.md` を読み、
  該当する個別ファイルだけを読む。`doc/devlog/` を一括 cat / 全読みすることは禁止。

## 設定の単一ソース化ルール

ゲーム設定は `engine/config.py` の `GameConfig` プリセット関数（`default_20()` 等）を**唯一の正**とする。
スクリプト側（`scripts/*.py`）で個別に `GameConfig(...)` を組み立てて設定を再現するのは禁止。
`doc/spec/gentei_janken_v0_1.md` §12.1 の未決事項（生還の現金ライン・利息間隔・手の公開範囲等）は
config フラグとして両案を持ち、値の変更のみで挙動を切り替えられるようにする
（dangou-card で過去にプリセット更新が各スクリプトへ伝播せず、シミュレーション結果が古い設定のまま
出続けるバグを起こした教訓を踏襲）。

## ★（星）はゼロサム資産である

`doc/spec/gentei_janken_v0_1.md` §3.2 により、★は場全体で60個（20人×3）に固定され、システムが新たに
発行することはない。対戦の勝敗・退出時の買取・強制退場・時間切れのいずれの経路でも、★は「移動」または
「場からの除去（買取・没収）」のみで、新規発行は一切起きない。新しいコード（対戦解決・退出清算・
強制退場処理）を書く際は、必ず `sum(全プレイヤーの★) + 退場済みプレイヤーの最終★ == 60` が
毎ターン成立することを確認すること。担保テスト: `tests/test_stars.py`。

## 残数掲示板は独立カウンタを持たない（手札合計から毎ターン導出する）

`doc/spec/gentei_janken_v0_1.md` §8.1 の残数掲示板（グー・チョキ・パーの場全体の残数）は、
「場に残っているプレイヤー全員の手札（予約中を含む）を種類別に合計した枚数」として**毎ターン導出**する。
別カウンタ（増減を都度加減算する変数）として持つと、対戦消費・強制退場によるカード消滅・
取引によるカード移動（総数不変）の3経路のいずれかで数え漏れ・二重計上が起きうる
（dangou-card の `card_rank` キー不一致による全滅バグと同型のリスク）。
掲示板の値は常に `engine/cards.py` の集計関数から導出し、状態として保持しないこと。
担保テスト: `tests/test_cards.py`（取引前後で総数不変、対戦・強制退場で正しく減ることを確認）。

## CoT reasoningフィールドは秘匿情報（情報リーク厳禁）

LLM応答JSONの `reasoning` フィールドは `llm/response_parser.py` で `strategy["_reasoning"]` に格納され、
`llm/llm_agent.py` 経由で `llm/llm_logger.py`（神視点のみ閲覧可能なJSONLログ）にのみ記録される。
**`engine/game.py` の可視状態構築・イベント・他プレイヤー向けプロンプトのいずれにも
`reasoning`/`_reasoning` を含めてはならない**。dangou-card の同名ルール・担保テスト
（`tests/test_cot.py::TestCoTNoLeak` 相当）をそのまま踏襲する。

## DM本文は当事者以外に対しキーごと削除する

`doc/spec/gentei_janken_v0_1.md` §8.2 により、DM は秘匿情報である。可視状態を構築する関数は、
DM（`type == "dm"`）について送信者・宛先以外に対し **`message` キー自体を辞書から削除**して返す
（空文字での上書きではなくキー欠落にする。`str(state)` に本文が一切現れないことをテストで機械的に
検証できるようにするため）。dangou-card の `_visible_messages()` パターンを踏襲する。
担保テスト: `tests/test_dm_secrecy.py`。

## Viewerの公開表示と神視点を分離する

Viewer APIは既定で `view=public` とし、DM本文・宛先、匿名発言の実発信者、契約条項・義務、
手札の中身・対戦で出した手（§8.2 秘匿情報）を返してはならない。ゲーム内の秘匿情報を確認する
必要がある場合だけ `view=god` を使用できる。God viewは `VIEWER_GOD_TOKEN` と
`X-Viewer-God-Token` の一致を必須とし、未設定・不一致は403にする。`VIEWER_GOD_PUBLIC=1`
（repo外のEnvironmentFile）を立てた間だけトークン検査をスキップしてよい（dangou-card と同じ設計）。

イベントデータの秘匿判定は**ホワイトリスト方式**（イベント種別ごとに公開してよいキーだけを
列挙し、未列挙のキー・イベント種別は既定でdataを落とす）に統一すること。ブラックリスト方式
（秘匿キーを列挙して消す）は、新規イベント種別・新規キーの追加時に列挙漏れがあると秘匿情報が
そのまま素通りする（サイクル1.5の実害: `SECRET_EVENT_TYPES`/`SECRET_DATA_KEYS` が実在しない
キー名を指しており、`challenger_hand`/`old_debt`/`cash_before`等が`view=public`で丸見えだった）。
`viewer/log_parser.py::PUBLIC_EVENT_DATA_KEYS` を参照。

## Viewerの公開bind/portは`viewer/server.py`の定数を単一ソースとする

`viewer/server.py` の `DEFAULT_HOST`（`127.0.0.1`）・`DEFAULT_PORT`（`9027`）が既定値の唯一の正。
systemd unit（`~/.config/systemd/user/gentei-viewer.service`）には `Environment=VIEWER_HOST` /
`Environment=VIEWER_PORT` を書かないこと。dangou-card で「code既定9025 / 本番unit上書き9023」が
ズレて設定の実体が2箇所に分散した教訓を踏まえる（`engine/config.py` の `GameConfig` 単一ソース化
ルールと同じ思想）。ポートを変更する場合は次の3箇所を同時に直す:
`viewer/server.py` の `DEFAULT_PORT` → Caddy `sites.d/gentei-janken-viewer.devrelay.io` の
`reverse_proxy` 先（root権限、devrelayプロジェクト経由） → `tests/test_viewer.py::test_default_port_matches_caddy_upstream`。
公開運用の手順は `doc/viewer_operations.md` を正本とする。

## LLMコストは常に `usage_cost()` 経由で算出する

`llm/costing.py` の `usage_cost()` / `worst_case_cost()` はキャッシュ割引・thinking差分課金に
対応している。usageから課金額を求める箇所は必ずこれらを経由すること。`estimate_cost()` を
素朴にinput/outputだけで呼ばないこと（dangou-card `scripts/model_matrix.py:_usage_cost()` と同じ設計）。

## 長時間トライアルはデタッチ起動する

Claude/DevRelayセッションはSIGALRMタイムアウトを持ち、フォアグラウンド/子プロセスとして起動した
長時間の `llm_trial.py` はセッションタイムアウトに巻き込まれてkillされる。20人×120ターンのフル試合や
コスト$1を超えるような長時間トライアルは、必ず `bash scripts/run_trial.sh --roster ... --seed ...`
（`llm_trial.py` の引数をそのまま渡す。`setsid nohup` で親プロセスから完全に切り離す）で起動し、
`bash scripts/check_trial.sh` で進行確認すること。
