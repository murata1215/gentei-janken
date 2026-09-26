# Viewer運用マニュアル

限定ジャンケンの**公開Viewer**（`https://gentei-janken-viewer.devrelay.io/`）の再起動・確認手順です。公開運用の正本はこの文書です。dangou-cardの同名文書（`/home/uso8m/dangou-card/doc/viewer_operations.md`）とは独立して管理する（値が異なるため相互参照ではなく複製）。

## 現行構成

| 項目 | 現行値 |
|---|---|
| 常駐方式 | `uso8m` ユーザーのsystemd user service |
| service名 | `gentei-viewer.service` |
| unit | `~/.config/systemd/user/gentei-viewer.service` |
| working directory | `/home/uso8m/gentei-janken` |
| ExecStart | `/home/uso8m/gentei-janken/.venv/bin/python -c "from viewer.server import main; main()"` |
| Viewer bind | `127.0.0.1:9027` |
| 公開経路 | Caddy: `gentei-janken-viewer.devrelay.io` → `localhost:9027` |
| Caddy設定 | `/etc/caddy/sites.d/gentei-janken-viewer.devrelay.io`（root管理・変更にはsudoが必要） |

unitは`Restart=always`、`RestartSec=3`で動作する。通常は手動Python起動や`viewer.pid`の管理は不要である。

## 既定値は`viewer/server.py`が単一ソース

`VIEWER_HOST`/`VIEWER_PORT`の既定値（`127.0.0.1`/`9027`）は`viewer/server.py`の
`DEFAULT_HOST`/`DEFAULT_PORT`定数が唯一の正。systemd unitには`Environment=`を
書かない（dangou-cardで「code既定9025/本番9023がズレていた」教訓を踏まえた設計）。

**ポートを変更する場合**は、次の3箇所を同時に直すこと。1つでも忘れるとCaddyの
upstreamが無言で壊れる:
1. `viewer/server.py`の`DEFAULT_PORT`
2. `/etc/caddy/sites.d/gentei-janken-viewer.devrelay.io`の`reverse_proxy`先（sudo必要）
3. `tests/test_viewer.py::test_default_port_matches_caddy_upstream`

## 通常の再起動と確認

`uso8m` ユーザーでSSHログインして実行する。

```bash
# 1. 現在の状態
systemctl --user status gentei-viewer.service --no-pager

# 2. 再起動
systemctl --user restart gentei-viewer.service

# 3. 再起動後の状態
systemctl --user status gentei-viewer.service --no-pager

# 4. Viewer自身へのローカル疎通
curl -fsS http://127.0.0.1:9027/api/games
```

直近ログの確認:

```bash
journalctl --user -u gentei-viewer.service -n 100 --no-pager
```

ログの追尾:

```bash
journalctl --user -u gentei-viewer.service -f
```

別ユーザーから操作する必要がある場合は、対象ユーザーのuser systemd busへ接続できる正規のSSH／sudo運用を使う。root向けの`systemctl restart gentei-viewer.service`ではなく、`uso8m`の`systemctl --user`を使う。

## 神視点トークン

| 項目 | 値 |
|---|---|
| drop-in | `~/.config/systemd/user/gentei-viewer.service.d/god-token.conf`（0600） |
| トークンファイル | `~/.config/gentei-viewer/god.env`（0700ディレクトリ内、0600） |

いずれもリポジトリ外（`~/.config/`配下）に置き、repoにも公開ドキュメントにも
実際のトークン値を書かない。ローテーションする場合:

```bash
( umask 077; printf 'VIEWER_GOD_TOKEN=%s\n' "$(openssl rand -hex 24)" > ~/.config/gentei-viewer/god.env )
systemctl --user restart gentei-viewer.service
```

検証（トークン値を出力に含めない）:

```bash
curl -sS -o /dev/null -w 'no-token:%{http_code}\n'  'http://127.0.0.1:9027/api/games/<game_id>/turns?view=god'   # 403
curl -sS -o /dev/null -w 'bad-token:%{http_code}\n' -H 'X-Viewer-God-Token: wrong' \
     'http://127.0.0.1:9027/api/games/<game_id>/turns?view=god'                                                  # 403
curl -sS -o /dev/null -w 'good-token:%{http_code}\n' \
     -H "X-Viewer-God-Token: $(sed -n 's/^VIEWER_GOD_TOKEN=//p' ~/.config/gentei-viewer/god.env)" \
     'http://127.0.0.1:9027/api/games/<game_id>/turns?view=god'                                                  # 200
```

`VIEWER_GOD_PUBLIC=1`は公開サイトでは使わない（トークン検査自体がスキップされ全秘匿情報が公開される）。

## ログとViewerの関係

`VIEWER_LOG_ROOT`既定は`<repo>/logs/llm`。Viewerが配信するのは`*_events.jsonl`
のみで、`*_llm_calls.jsonl`（生プロンプト・応答・CoT reasoningを含む）と
`*_seat_map.json`は`list_games()`がglobしないため配信対象に一切入らない
（`viewer/log_parser.py`）。秘匿判定はホワイトリスト方式
（`PUBLIC_EVENT_DATA_KEYS`）で、未列挙のイベント種別・キーは既定でpublic viewから
落ちる（`rules/project.md`「Viewerの公開表示と神視点を分離する」参照）。

公開したくない試行ログがある場合は`logs/llm/`から退避してからViewerを再起動する
（`LogCache`はmtime+sizeキャッシュなのでファイル削除後は再起動不要で一覧から消える）。

## Caddyとの関係

通常のViewer再起動、Viewerコード更新、静的ファイル更新ではCaddy reloadは不要である。Caddyは`localhost:9027`へ転送するだけで、Viewer serviceの再起動後に同じupstreamへ接続する。

次の場合だけ、Caddy設定の確認・変更と、その変更に対する別途承認のうえでreloadを検討する。

- ドメイン、TLS、site設定を変更した。
- `reverse_proxy`のupstreamやポートを変更した。
- Caddy service自体が停止・異常となった。

Caddy側の変更はsudoが必要でuso8mでは直接実行できない。DevRelayの`devrelay`
プロジェクト（またはけいすけ側）へ依頼する。dangou-card-viewer.devrelay.ioと
異なり、`log_skip`・`handle_errors`は付与していない:

- `log_skip`: 現行`viewer/static/index.html`にポーリング（`setInterval`等）が
  無く、アクセスログが肥大しないため不要。将来ポーリングを追加する場合、
  gentei-jankenのAPIパスは`/api/games/{game_id}/(state|turns|board)`の1セグメントで
  あり、dangou-cardの2セグメント用正規表現（`^/api/games/[^/]+/[^/]+/state/?$`）
  をコピペしても一切マッチしない点に注意。
- `handle_errors` + placeholder: `/home/devrelay/testflight/...`はdevrelay
  ユーザー所有の別資産で、gentei-janken用は未整備。付けない方がViewer障害時に
  素の502で明確に分かる。

## DevRelay Agent経由の操作

Agent経由で再起動する場合も、対象環境でuser systemd busへアクセスできる権限がある場合に限る。安全な順序は次のとおり。

1. `systemctl --user status gentei-viewer.service --no-pager`
2. `systemctl --user restart gentei-viewer.service`
3. 再度statusを確認する。
4. `curl -fsS http://127.0.0.1:9027/api/games`でローカル疎通を確認する。

## 盤面API（`GET /api/games/{id}/board`）

サイクル1.7で新設。盤面UI（`viewer/static/index.html`）はこのエンドポイントのみを使う
（`/state`/`/turns`は監査・デバッグ用として存続、UIからは呼ばない）。

- **畳み込みはサーバ側で行う**: publicイベント列は自己完結していない
  （`MATCH_ACCEPTED`にchallenger_idが無い等）ため、`viewer/log_parser.py::_fold_events`が
  常にgod完全体のイベント列から席（★・生死・現金・借金・手札内訳）・申込索引・
  掲示板の時系列を構築し、その後public/godへ投影する。フロントに秘匿判定ロジックを
  持たせない設計（`rules/project.md`「ホワイトリスト方式に統一」）。
- **`?from_turn=N`**: N超のターンのみ`turns`配列に含める（差分ポーリング用。フェーズ1では
  フロントは常に`from_turn=0`で全件取得）。`seats`（最新状態）は常に全件返る。
- **`If-None-Match`**: ログのfingerprint（mtime+size）と一致すれば304。完走試合は
  fingerprintが恒久的に一致するため、以後のリクエストは実質304のみになる。
- **`derivation`**: 畳み込みの自己検証結果（★ゼロサム・engine記録値との突き合わせ）。
  `stars_zero_sum_ok: false`が出たら畳み込みロジックにバグがある。
- **`VIEWER_REVEAL_IDENTITY`**（既定`after_game_end`）: publicでプレイヤーの正体
  （モデル名等）を出す条件。`never`/`after_game_end`/`always`。godは常に出す。
  `*_seat_map.json`はv1（`{pid: model_id}`フラットdict）/v2
  （`{"version":2,"seats":{...}}`）の両対応。Bot戦（`scripts/dry_run.py`）は
  seat_mapを書き出さないため、identityキー自体が欠落する（`null`ではなくキー欠落）。

秘匿検証の実施例（本番URLに対して、値は表示しない）:

```bash
curl -fsS "https://gentei-janken-viewer.devrelay.io/api/games/<game_id>/board?view=public" \
  | grep -oE '"(cash|debt|hand_counts|hand_total|challenger_hand|opponent_hand)"'
# → 出力が空であること
```

## 既知の制約（`doc/issues.md`参照）

- ライブポーリング未実装（サイクル1.7時点ではフロントは手動更新ボタンのみ）
- ★移動の演出・ペア強調の視覚効果は簡易版（Phase 4で拡充予定）
- 感情アイコンの枠は用意済みだが、`prompt_builder`がemotionを要求していないため
  実データは常に空（`?demo_emotion=1`のような開発者向け検証手段は未実装）
- コストモーダル・実況席（dangou-card相当）は未移植（データ生成元が無い）
