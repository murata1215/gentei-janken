"""
ルールベースBotパッケージ

LLMを使わない決定論的Botを提供する。全BotはPlayerAgentを継承する。
本サイクルは§12.2の6種のうち2種のみ実装（残り4種は次サイクル: 買い占め型・
★仲買型・早期退出型・様子見型）。
"""

from bots.aggressor_bot import AggressorBot
from bots.draw_alliance_bot import DrawAllianceBot

# Bot名 → クラスのレジストリ（simulate.pyのrosterオプション用）
BOT_REGISTRY: dict[str, type] = {
    "DrawAlliance": DrawAllianceBot,
    "Aggressor": AggressorBot,
}

# デフォルトロスター
DEFAULT_ROSTER: list[str] = list(BOT_REGISTRY.keys())
