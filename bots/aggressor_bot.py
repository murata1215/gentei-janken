"""
Bot: 攻撃型（§12.2）

勝負を挑み続ける。届いている申込はランダムな手で積極的に受諾し、申込がなければ
生存者からランダムに相手を選んで自分から仕掛ける。早期返済はせず、退出条件が
揃った時点で退出する。
"""

from engine.config import GameConfig
from engine.models import Action, MatchAcceptAction, MatchOfferAction, PassAction, PlayerState
from bots.base import BotAgent


class AggressorBot(BotAgent):
    """積極的に対戦を仕掛けるBot（§12.2「攻撃型」）"""

    def __init__(self, seed: int = 0) -> None:
        super().__init__("Aggressor", seed)

    def act(self, player_state: PlayerState, turn: int, visible_state: dict) -> Action:
        config: GameConfig = visible_state["config"]
        self._config = self._config or config

        exit_action = self._try_exit(player_state, config)
        if exit_action:
            return exit_action

        incoming = visible_state.get("offers_incoming", [])
        if incoming and player_state.cards:
            offer = self.rng.choice(incoming)
            card = self.rng.choice(player_state.cards)
            return MatchAcceptAction(
                player_id=player_state.player_id,
                offer_id=offer.offer_id,
                hand=card.hand,
                card_id=card.card_id,
            )

        if player_state.cards and not visible_state.get("offers_outgoing"):
            candidates = visible_state.get("alive_player_ids", [])
            if candidates:
                opponent_id = self.rng.choice(candidates)
                card = self.rng.choice(player_state.cards)
                return MatchOfferAction(
                    player_id=player_state.player_id,
                    opponent_id=opponent_id,
                    hand=card.hand,
                    card_id=card.card_id,
                )

        return PassAction(player_id=player_state.player_id)
