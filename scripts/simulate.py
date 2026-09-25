"""
シミュレーションスクリプト（Botのみ、LLM不使用・コスト0）

指定ロスターで複数試合を並列実行し、生還率・平均順位などをCSV/レポートに
まとめる。§12.2のBotシミュレーション用の最小足場。

使用方法:
    uv run python scripts/simulate.py --games 100
    uv run python scripts/simulate.py --roster "DrawAlliance:10,Aggressor:10" --games 1000 --seed 42
"""

import argparse
import csv
import sys
from multiprocessing import Pool
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bots import BOT_REGISTRY, DEFAULT_ROSTER
from engine.config import GameConfig
from engine.events import EventLogger
from engine.game import Game


def parse_roster(roster_str: str | None) -> list[str]:
    """
    "DrawAlliance:10,Aggressor:10" 形式のロスター指定を展開する

    未指定ならDEFAULT_ROSTERを10体ずつ均等展開して20人に合わせる。
    """
    if not roster_str:
        names = DEFAULT_ROSTER
        return [names[i % len(names)] for i in range(20)]
    result: list[str] = []
    for part in roster_str.split(","):
        name, _, count_str = part.partition(":")
        name = name.strip()
        count = int(count_str) if count_str else 1
        if name not in BOT_REGISTRY:
            raise ValueError(f"Unknown bot: {name} (valid: {', '.join(BOT_REGISTRY)})")
        result.extend([name] * count)
    return result


def run_single_game(args: tuple[list[str], int]) -> dict:
    """1試合を実行する（multiprocessing.Pool向けに引数をタプルで受け取る）"""
    bot_names, seed = args
    config = GameConfig.dev_small(num_players=len(bot_names), total_turns=120)
    agents = {
        f"P{i:02d}": BOT_REGISTRY[name](seed=seed * 1000 + i)
        for i, name in enumerate(bot_names, start=1)
    }
    logger = EventLogger()
    game = Game(config=config, agents=agents, seed=seed, logger=logger)
    result = game.run()
    return {
        "seed": seed,
        "num_players": len(bot_names),
        "num_survivors": len(result["survivors"]),
        "num_eliminated": len(result["eliminated"]),
        "total_final_assets": sum(result["final_assets"].values()),
    }


def generate_report(rows: list[dict]) -> str:
    """簡易サマリレポート（Markdown）を生成する"""
    n = len(rows)
    if n == 0:
        return "# シミュレーション結果\n\n試合数0"
    avg_survivors = sum(r["num_survivors"] for r in rows) / n
    all_survive = sum(1 for r in rows if r["num_survivors"] == r["num_players"])
    none_survive = sum(1 for r in rows if r["num_survivors"] == 0)
    lines = [
        "# シミュレーション結果",
        "",
        f"- 試合数: {n}",
        f"- 平均生還者数: {avg_survivors:.2f}",
        f"- 全員生還: {all_survive}/{n}（§9.3の抜け穴が実際に発生した割合）",
        f"- 生存者0: {none_survive}/{n}",
    ]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="限定ジャンケン Botシミュレーション")
    parser.add_argument("--games", type=int, default=100)
    parser.add_argument("--roster", type=str, default=None,
                         help='例: "DrawAlliance:10,Aggressor:10"')
    parser.add_argument("--seed", type=int, default=0, help="開始シード")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--output", type=str, default="logs/simulate_report.csv")
    args = parser.parse_args()

    bot_names = parse_roster(args.roster)
    print(f"ロスター: {bot_names}")
    print(f"試合数: {args.games}")

    tasks = [(bot_names, args.seed + i) for i in range(args.games)]
    with Pool(args.workers) as pool:
        rows = pool.map(run_single_game, tasks)

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    report = generate_report(rows)
    print("\n" + report)
    print(f"\nCSV出力: {output_path}")


if __name__ == "__main__":
    main()
