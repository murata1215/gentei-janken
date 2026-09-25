"""
LLM試験スクリプト（本番API使用）

座席マップ（roster）に従いLLMAgentを組み立て、1試合を実行する。
長時間トライアルは scripts/run_trial.sh でデタッチ起動すること
（rules/project.md「長時間トライアルはデタッチ起動する」参照）。

使用方法:
    uv run python scripts/llm_trial.py --roster "L1,L1,M3,M3,H1,H1" --seed 504
    bash scripts/run_trial.sh --roster "L1,L1,M3,M3,H1,H1" --seed 504
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv

load_dotenv()

from engine.config import GameConfig
from engine.events import EventLogger
from engine.game import Game
from llm.adapters import create_adapter
from llm.game_cost_budget import GameCostBudget
from llm.llm_agent import LLMAgent
from llm.llm_logger import LLMLogger
from llm.models import get_model


def parse_roster(roster_str: str) -> list[str]:
    """"L1,L1,M3,M3" のようなカンマ区切りのモデルキー列を解釈する"""
    return [k.strip() for k in roster_str.split(",") if k.strip()]


def main() -> None:
    parser = argparse.ArgumentParser(description="限定ジャンケン LLMトライアル")
    parser.add_argument("--roster", type=str, required=True,
                         help='モデルキーのカンマ区切り（例: "L1,L1,M3,M3,H1,H1"）')
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--turns", type=int, default=120)
    parser.add_argument("--game-id", type=str, default=None)
    args = parser.parse_args()

    model_keys = parse_roster(args.roster)
    config = GameConfig.dev_small(num_players=len(model_keys), total_turns=args.turns)

    game_id = args.game_id or f"trial_seed{args.seed}_{len(model_keys)}p"
    log_dir = Path("logs/llm")
    log_dir.mkdir(parents=True, exist_ok=True)

    logger = EventLogger(output_path=log_dir / f"{game_id}_events.jsonl")
    llm_logger = LLMLogger(log_dir, game_id=game_id)
    game_cost_budget = GameCostBudget(per_player_cap_usd=5.0, game_cap_usd=40.0, event_logger=logger)

    seat_map: dict[str, str] = {}
    agents: dict[str, LLMAgent] = {}
    for i, model_key in enumerate(model_keys, start=1):
        pid = f"P{i:02d}"
        model_info = get_model(model_key)
        adapter = create_adapter(model_info)
        agents[pid] = LLMAgent(pid, model_info, adapter, llm_logger, config, game_cost_budget)
        seat_map[pid] = model_info.model_id

    seat_map_path = log_dir / f"{game_id}_seat_map.json"
    seat_map_path.write_text(json.dumps(seat_map, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"=== 限定ジャンケン LLMトライアル: {game_id} ===")
    print(f"座席: {seat_map}")
    print(f"シード: {args.seed}")
    print("---")

    game = Game(config=config, agents=agents, seed=args.seed, logger=logger)
    result = game.run()

    # llm_loggerは全エージェントで共有インスタンスのため1回だけsave()する
    # （逐次書き込み中に後付けされたemotion/reasoning等をファイルへ確定反映する）
    llm_logger.save()

    print("\n=== 結果 ===")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    print(f"\nJSONLログ: {log_dir / f'{game_id}_events.jsonl'}")
    print(f"座席マップ: {seat_map_path}")


if __name__ == "__main__":
    main()
