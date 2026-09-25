# devlog INDEX

devlog本文は `doc/devlog/YYYY-MM-DD_HHMMSS.md` に1サイクル1ファイルで保存する。
このINDEXには1行だけ追記し、`doc/devlog/` の一括catは禁止（詳細は `rules/project.md` 参照）。

## 索引

- 2026-09-25_231347 | サイクル1.0 | プロジェクト新設・ガワ作成 | dangou-card基盤（llm/約2,400行をほぼ逐語移植）+ 仕様書v0.1に沿ったengine/新規実装（歩く骨格）でdry_run 20人×120ターン完走・bots混成で6人生還を確認、テスト90件PASS。reserved_card_id設計バグ（1人が「自分の申込」と「相手の申込受諾」を同時に持てない）とhttpx2依存バグを発見・修正
