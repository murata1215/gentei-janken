#!/usr/bin/env bash
# Stage別トライアル一括実行スクリプト（サイクル1.9〜）
#
# 複数シードのトライアルをまとめてデタッチ起動し、全て完了するまで待ってから
# scripts/analyze_actions.py で結果をまとめて表示する。
# Claude（AI）ではなく人間が対話シェルから実行する想定
# （長時間の完了待ちループをAIセッション内で回すとタイムアウトに巻き込まれる
# 教訓——サイクル1.8/1.9で実際に2回発生した）。
#
# 使い方:
#   bash scripts/run_stage_trial.sh <prefix> <seed1> [seed2] [seed3] ...
#   例: bash scripts/run_stage_trial.sh s2 301 302 303
#
# ロスター・ターン数・コスト上限は環境変数で上書き可能（既定はStage 0/1と同じ
# L6×6・20ターン・比較可能性のため固定）:
#   ROSTER="L6,L6,L6,L6,L6,L6" TURNS=20 GAME_CAP=0.5 PLAYER_CAP=0.1 \
#     bash scripts/run_stage_trial.sh s2 301 302 303
#
# game_id は "{prefix}_seed{N}" になり、logs/llm/{game_id}_events.jsonl 等に出力される。
#
# 完了判定はイベントJSONLをPythonでJSONとしてパースしevent_type=="GAME_END"を
# 確認する（文字列grepでスペースの有無に依存すると誤判定して待ち続けるバグに
# なる。サイクル1.8/1.9で実際にこれで待機が永久に終わらなかった）。
set -euo pipefail
cd "$(dirname "$0")/.."

if [ $# -lt 2 ]; then
    echo "Usage: bash scripts/run_stage_trial.sh <prefix> <seed1> [seed2] [seed3] ..."
    echo "Example: bash scripts/run_stage_trial.sh s2 301 302 303"
    exit 1
fi

PREFIX="$1"
shift
SEEDS=("$@")
ROSTER="${ROSTER:-L6,L6,L6,L6,L6,L6}"
TURNS="${TURNS:-20}"
GAME_CAP="${GAME_CAP:-0.5}"
PLAYER_CAP="${PLAYER_CAP:-0.1}"

GAME_IDS=()
for seed in "${SEEDS[@]}"; do
    game_id="${PREFIX}_seed${seed}"
    GAME_IDS+=("$game_id")
    echo "[run_stage_trial] 起動: $game_id (seed=$seed, roster=$ROSTER, turns=$TURNS)"
    bash scripts/run_trial.sh --roster "$ROSTER" --turns "$TURNS" --seed "$seed" \
        --game-id "$game_id" --game-cap-usd "$GAME_CAP" --per-player-cap-usd "$PLAYER_CAP"
done

echo ""
echo "[run_stage_trial] 全${#GAME_IDS[@]}件を起動しました。完了を待機します（10秒間隔でポーリング）..."
echo "[run_stage_trial] game_ids: ${GAME_IDS[*]}"
echo "[run_stage_trial] 別ターミナルで進行確認する場合: bash scripts/check_trial.sh logs/llm/<game_id>_events.jsonl"
echo ""

python3 - "${GAME_IDS[@]}" << 'PYEOF'
import json
import sys
import time

game_ids = sys.argv[1:]


def is_done(game_id: str) -> bool:
    path = f"logs/llm/{game_id}_events.jsonl"
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    e = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if e.get("event_type") == "GAME_END":
                    return True
    except FileNotFoundError:
        return False
    return False


start = time.time()
while True:
    done = [g for g in game_ids if is_done(g)]
    elapsed = int(time.time() - start)
    remaining = [g for g in game_ids if g not in done]
    print(f"  [{elapsed}s] 完了 {len(done)}/{len(game_ids)}"
          + (f" / 未完了: {', '.join(remaining)}" if remaining else ""))
    if len(done) == len(game_ids):
        print("全試合が完了しました。")
        break
    time.sleep(10)
PYEOF

echo ""
echo "=== 分析結果（scripts/analyze_actions.py） ==="
uv run python scripts/analyze_actions.py "${GAME_IDS[@]}"
