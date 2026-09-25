"""
BotAgent基底クラス

全ルールベースBotの共通基底。PlayerAgentを継承し、Bot用RNG・退出判定・
返済ポリシーの共通処理を提供する。
"""

import random

from engine.config import GameConfig
from engine.exit_rules import can_exit
from engine.models import Action, ExitAction, RepayAction
from engine.negotiation import PlayerAgent
from engine.player import can_repay_now


class BotAgent(PlayerAgent):
    """
    全Botの共通基底クラス

    Args:
        bot_type: Bot種別名（例: "DrawAlliance", "Aggressor"）
        seed: Bot固有の乱数シード
    """

    def __init__(self, bot_type: str, seed: int = 0) -> None:
        self.bot_type = bot_type
        self.rng = random.Random(seed)
        self._config: GameConfig | None = None

    def choose_loan(self, config: GameConfig) -> int:
        """既定は最低借入額。サブクラスでオーバーライド可能"""
        self._config = config
        return config.loan_min

    def _try_exit(self, player_state, config: GameConfig) -> Action | None:
        """退出条件（§6.1）が揃っていればExitActionを返す。揃っていなければNone"""
        ok, _ = can_exit(player_state, config, has_unfulfilled_obligation=False)
        if ok:
            return ExitAction(player_id=player_state.player_id)
        return None

    def _try_full_repay(self, player_state, turn: int, config: GameConfig) -> Action | None:
        """
        利息を止めるための全額任意返済（§2.4/§9.3）

        repay_unlock_turn（§12.1未決事項）が設定されている場合、そのターン
        以前は返済できない（can_repay_now()が判定）。
        """
        if player_state.debt <= 0:
            return None
        if not can_repay_now(player_state, turn, config):
            return None
        repay_amount = min(player_state.debt, player_state.cash)
        if repay_amount <= 0:
            return None
        return RepayAction(player_id=player_state.player_id, amount=repay_amount)
