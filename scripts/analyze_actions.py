"""
アクション分析スクリプト（サイクル1.8）

logs/llm/{game_id}_llm_calls.jsonl から実際に選ばれたaction_typeの分布
（pass率を含む）を、logs/llm/{game_id}_events.jsonl からイベント種別ごとの
件数を集計する。DM・取引通電（Stage 1/2）の受け入れ基準（pass率・
MATCH_RESOLVED件数・BROADCAST_SENT件数等）を数値で判定するために使う。

action_typeはengine側イベントには残らない（PassActionはログを一切残さず、
その他のアクションも「結果」のイベントしか記録しない）ため、必ず
llm_calls.jsonlのresponse_text（LLMの生応答）から抽出する。抽出ロジックは
llm/response_parser.extract_json() をそのまま再利用し、二重管理を避ける。

使用方法:
    uv run python scripts/analyze_actions.py logs/llm/s0_seed1_events.jsonl
    uv run python scripts/analyze_actions.py s0_seed1
    uv run python scripts/analyze_actions.py s0_seed1 s0_seed2 s0_seed3  # 複数game_idの中央値も出す
"""

import json
import statistics
import sys
from collections import Counter
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from llm.response_parser import extract_json  # noqa: E402

LOG_DIR = Path("logs/llm")


def _resolve_game_id(arg: str) -> str:
    """"logs/llm/foo_events.jsonl" でも "foo" でもgame_idを取り出せるようにする"""
    name = Path(arg).name
    if name.endswith("_events.jsonl"):
        return name[: -len("_events.jsonl")]
    return name


def _extract_action_type(response_text: str) -> str | None:
    data = extract_json(response_text or "")
    if not data:
        return None
    action_type = data.get("action_type")
    return action_type if isinstance(action_type, str) else None


def analyze(game_id: str, log_dir: Path = LOG_DIR) -> dict[str, Any]:
    events_path = log_dir / f"{game_id}_events.jsonl"
    calls_path = log_dir / f"{game_id}_llm_calls.jsonl"

    action_counts: Counter[str] = Counter()
    total_calls = 0
    parse_failed = 0
    if calls_path.exists():
        with open(calls_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                entry = json.loads(line)
                if entry.get("phase") != "act":
                    continue  # choose_loan呼び出しは行動選択ではないため除外
                total_calls += 1
                action_type = _extract_action_type(entry.get("response_text", ""))
                if action_type is None:
                    parse_failed += 1
                    action_counts["(parse_failed)"] += 1
                else:
                    action_counts[action_type] += 1

    event_counts: Counter[str] = Counter()
    if events_path.exists():
        with open(events_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                event = json.loads(line)
                event_counts[event.get("event_type", "?")] += 1

    pass_count = action_counts.get("pass", 0)
    return {
        "game_id": game_id,
        "total_act_calls": total_calls,
        "pass_count": pass_count,
        "pass_rate": (pass_count / total_calls) if total_calls else None,
        "parse_failed": parse_failed,
        "action_counts": dict(action_counts.most_common()),
        "event_counts": dict(event_counts.most_common()),
        "match_resolved": event_counts.get("MATCH_RESOLVED", 0),
        "match_accept_rejected": event_counts.get("MATCH_ACCEPT_REJECTED", 0),
    }


def _print_single(result: dict[str, Any]) -> None:
    print(json.dumps(result, ensure_ascii=False, indent=2))


def _print_summary(results: list[dict[str, Any]]) -> None:
    print(f"\n=== {len(results)}試合の中央値 ===")
    pass_rates = [r["pass_rate"] for r in results if r["pass_rate"] is not None]
    resolved = [r["match_resolved"] for r in results]
    print(f"pass率 中央値: {statistics.median(pass_rates):.1%}" if pass_rates else "pass率: データなし")
    print(f"MATCH_RESOLVED 中央値: {statistics.median(resolved)}" if resolved else "MATCH_RESOLVED: データなし")


def main() -> None:
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    game_ids = [_resolve_game_id(arg) for arg in sys.argv[1:]]
    results = [analyze(game_id) for game_id in game_ids]
    for result in results:
        _print_single(result)
    if len(results) > 1:
        _print_summary(results)


if __name__ == "__main__":
    main()
