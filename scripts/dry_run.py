"""
ドライランスクリプト

20人×120ターンのゲームを1試合実行し、JSONLログを logs/llm/ に出力する
（viewer/server.pyの既定VIEWER_LOG_ROOTと一致させる）。
既定エージェントはStubAgent（常にpass、退出条件が揃えば退出）。
--bots を指定するとbots/のBOT_REGISTRYからロスターを組む。

使用方法:
    uv run python scripts/dry_run.py
    uv run python scripts/dry_run.py --seed 12345
    uv run python scripts/dry_run.py --bots
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine.config import GameConfig
from engine.events import EventLogger
from engine.game import Game
from engine.negotiation import StubAgent


def build_agents(config: GameConfig, use_bots: bool) -> dict:
    if not use_bots:
        return {f"P{i:02d}": StubAgent() for i in range(1, config.num_players + 1)}

    from bots import BOT_REGISTRY, DEFAULT_ROSTER
    agents = {}
    names = DEFAULT_ROSTER
    for i in range(1, config.num_players + 1):
        pid = f"P{i:02d}"
        bot_name = names[(i - 1) % len(names)]
        agents[pid] = BOT_REGISTRY[bot_name](seed=i)
    return agents


def main() -> None:
    parser = argparse.ArgumentParser(description="限定ジャンケン ドライラン")
    parser.add_argument("--seed", type=int, default=42, help="乱数シード（デフォルト: 42）")
    parser.add_argument("--players", type=int, default=20, help="プレイヤー数（デフォルト: 20）")
    parser.add_argument("--turns", type=int, default=120, help="ターン数（デフォルト: 120）")
    parser.add_argument("--bots", action="store_true", help="StubAgentの代わりにbots/のロスターを使う")
    parser.add_argument("--output", type=str, default=None, help="JSONLログ出力先パス")
    args = parser.parse_args()

    if args.players == 20 and args.turns == 120:
        config = GameConfig.default_20()
    else:
        config = GameConfig.dev_small(num_players=args.players, total_turns=args.turns)

    agents = build_agents(config, args.bots)
    logger = EventLogger()

    print("=== 限定ジャンケン ドライラン ===")
    print(f"プレイヤー数: {config.num_players}")
    print(f"ターン数: {config.total_turns}")
    print(f"借入範囲: {config.loan_min:,}〜{config.loan_max:,}円")
    print(f"エージェント: {'bots ロスター' if args.bots else 'StubAgent'}")
    print(f"シード: {args.seed}")
    print("---")

    game = Game(config=config, agents=agents, seed=args.seed, logger=logger)
    result = game.run()

    print("\n=== 結果 ===")
    print(f"生還者: {len(result['survivors'])}人")
    for pid in result["survivors"]:
        print(f"  {pid}: 最終資産={result['final_assets'][pid]:,}円")

    print(f"\n脱落者: {len(result['eliminated'])}人")
    for pid, reason in result["eliminated"].items():
        print(f"  {pid}: {reason}")

    game_id = f"dry_run_seed{args.seed}_{config.num_players}p"
    output_path = Path(args.output) if args.output else Path("logs/llm") / f"{game_id}_events.jsonl"
    logger.save_jsonl(output_path)
    print(f"\nJSONLログ出力: {output_path}")
    print(f"イベント数: {len(logger.events)}")


if __name__ == "__main__":
    main()
