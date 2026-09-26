# devlog INDEX

devlog本文は `doc/devlog/YYYY-MM-DD_HHMMSS.md` に1サイクル1ファイルで保存する。
このINDEXには1行だけ追記し、`doc/devlog/` の一括catは禁止（詳細は `rules/project.md` 参照）。

## 索引

- 2026-09-25_231347 | サイクル1.0 | プロジェクト新設・ガワ作成 | dangou-card基盤（llm/約2,400行をほぼ逐語移植）+ 仕様書v0.1に沿ったengine/新規実装（歩く骨格）でdry_run 20人×120ターン完走・bots混成で6人生還を確認、テスト90件PASS。reserved_card_id設計バグ（1人が「自分の申込」と「相手の申込受諾」を同時に持てない）とhttpx2依存バグを発見・修正
- 2026-09-26_112438 | サイクル1.5 | LLM対戦の通電・秘匿の穴閉じ | prompt_builderにcard_id/offer_id/対戦相手候補を実装し、engine/game.pyにrepay/transfer/wait処理とBOARD_UPDATEDイベントを追加、response_parserの型変換異常系をParseError化、viewerの秘匿情報漏れ（challenger_hand等）をホワイトリスト方式で閉じた。テスト153件PASS（新規63件）、実LLM課金トライアルでMATCH_RESOLVED 5件を実測確認（修正前は構造上0件）。wait両条件省略で永久停止する新規バグを実測で発見・修正
- 2026-09-26_120532 | サイクル1.6 | Viewerのweb公開（systemd + Caddy） | 既定ポートを9024→9027に変更（chrome-bookmark.devrelay.ioと衝突していたため）しDEFAULT_HOST/DEFAULT_PORT定数で単一ソース化、GET /ルート追加（従来404だった穴）、gentei-viewer.service常駐+Caddy公開（devrelayへ依頼・reload完了）でhttps://gentei-janken-viewer.devrelay.io/を実測200確認。テスト20件追加で160件PASS、実ログ5試合でview=publicの秘匿情報リークなしを実測確認
- 2026-09-26_123834 | サイクル1.6.1 | 秘匿情報漏れの緊急修正（reasonへのcard_id混入） | MATCH_ACCEPT_REJECTED/MATCH_OFFER_REJECTEDのreasonにstr(ValueError)がそのまま入りcard_id（手の種類）が本番public viewで42件漏洩していたのをPUBLIC_REASON_CODESホワイトリストで即修正、systemctl restartで本番反映しpublic0件/god14件を実測確認。感情画像42枚を128px化（55.1MB→0.7MB）。テスト18件追加で178件PASS
- 2026-09-26_130450 | サイクル1.7 | Viewerの盤面UI化（dangou-card相当へ） | サーバ側でイベント畳み込み(_fold_events)を新設しGET /api/games/{id}/boardを新設、index.htmlを98行→900行弱に全面書き直しで20席グリッド・★メダリオン・対戦3列レーン・掲示板スパークライン・トランスポートを実装。matches_resolved等をpublic投影から意図的に除外する設計とboard.offersからのフロント側再集計、GODモード切替でターン位置がリセットされる不具合をPlaywright実機検証で発見・修正。テスト67件追加で224件PASS、本番反映後に5試合でリーク0件を実測確認
- 2026-09-26_143114 | サイクル1.8 | LLM対戦を成立させる基盤整備（★可視化・memory配線） | build_opponents_sectionが★を渡していなかった穴とmemoryフィールド参照ゼロの穴を解消。_build_visible_stateにopponents追加、extract_memory()新設でllm_agentが次ターンへ記憶を再注入、余裕ターン数表示でsay無しの設計とした。scripts/analyze_actions.py新規。テスト19件追加で243件PASS、実課金トライアル3本($0.072)でpass率70.8%→5.9%・MATCH_RESOLVED5件→19件（中央値）を実測確認
