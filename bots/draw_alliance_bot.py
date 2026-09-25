"""
Bot: あいこ連合型（§9.3/§12.2）

仕様書§9.3で指摘された「あいこ作戦」を実装する。T1に全額任意返済して利息を
止め、対戦では常に相手の手をミラーして受諾する（あいこを保証）ことで★を
一切失わずにカードだけを消化する。申込む側は自分の手札から任意の手を選ぶ
（ミラー役の相手がいれば結果は常にあいこになる）。
"""

from engine.config import GameConfig
from engine.models import Action, MatchAcceptAction, MatchOfferAction, PassAction, PlayerState
from bots.base import BotAgent


class DrawAllianceBot(BotAgent):
    """常にあいこを狙う連合戦略Bot（§12.2「あいこ連合型」）"""

    def __init__(self, seed: int = 0) -> None:
        super().__init__("DrawAlliance", seed)

    def act(self, player_state: PlayerState, turn: int, visible_state: dict) -> Action:
        config: GameConfig = visible_state["config"]
        self._config = self._config or config

        exit_action = self._try_exit(player_state, config)
        if exit_action:
            return exit_action

        if turn == 1:
            repay_action = self._try_full_repay(player_state, turn, config)
            if repay_action:
                return repay_action

        # 届いている申込を相手の手とミラーして受諾する（あいこを保証）
        for offer in visible_state.get("offers_incoming", []):
            matching = [c for c in player_state.cards if c.hand == offer.challenger_hand]
            if matching:
                return MatchAcceptAction(
                    player_id=player_state.player_id,
                    offer_id=offer.offer_id,
                    hand=offer.challenger_hand,
                    card_id=matching[0].card_id,
                )

        # 自分から申込む（既に出している申込があれば新規には出さない、§4.3）
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
