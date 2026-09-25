#!/usr/bin/env bash
# トライアル進行確認: logs/llm/*_events.jsonl のターン・完了状態を表示する。
#
# 使用例:
#   bash scripts/check_trial.sh                              # 最新のイベントファイル
#   bash scripts/check_trial.sh logs/llm/trial_20260101_events.jsonl  # 指定ファイル
set -euo pipefail
cd "$(dirname "$0")/.."

if [ $# -ge 1 ]; then
    EVENTS="$1"
else
    EVENTS=$(ls -t logs/llm/*_events.jsonl 2>/dev/null | head -1 || true)
fi

if [ -z "$EVENTS" ] || [ ! -f "$EVENTS" ]; then
    echo "No events file found."
    exit 1
fi

echo "Events: $EVENTS"

# PID チェック（最新の run_*.pid）
PID_FILE=$(ls -t logs/llm/run_*.pid 2>/dev/null | head -1 || true)
if [ -n "$PID_FILE" ]; then
    PID=$(cat "$PID_FILE")
    if kill -0 "$PID" 2>/dev/null; then
        echo "Process: RUNNING (PID=$PID, file=$PID_FILE)"
    else
        echo "Process: FINISHED (PID=$PID was, file=$PID_FILE)"
    fi
else
    echo "Process: No PID file found"
fi

python3 -c "
import json
with open('$EVENTS') as f:
    lt = 0; ge = False; cnt = 0; last_ts = ''
    for line in f:
        cnt += 1
        ev = json.loads(line)
        t = ev.get('round_num', 0)
        if isinstance(t, int) and t > lt:
            lt = t
        if ev.get('event_type') == 'GAME_END':
            ge = True
            data = ev.get('data', {})
            survivors = data.get('survivors', [])
            final_assets = data.get('final_assets', {})
            eliminated = data.get('eliminated', {})
            print(f'Turn: {lt}/120, Events: {cnt}, Completed: YES')
            print(f'Survivors: {len(survivors)}, Eliminated: {len(eliminated)}')
            for pid in survivors:
                print(f'  {pid}: final_assets={final_assets.get(pid, 0):,}')
        last_ts = ev.get('timestamp', '')
    if not ge:
        print(f'Turn: {lt}/120, Events: {cnt}, Completed: NO (in progress or stopped)')
    print(f'Last event: {last_ts[:19]}')
"

LOG_FILE=$(ls -t logs/llm/run_*.log 2>/dev/null | head -1 || true)
if [ -n "$LOG_FILE" ]; then
    echo ""
    echo "Latest log tail ($LOG_FILE):"
    tail -5 "$LOG_FILE"
fi
