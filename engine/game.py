"""
ゲーム進行モジュール（§5）

120ターンのターンループを実行する。「歩く骨格」（本サイクル）が実装する範囲:

    初期配布 → 借入 → 120ターンループ
      （対戦の申込/受諾/拒否/取り下げ・開示、★移動、掲示板更新、
       ★0強制退場、利息計上、退出判定と清算、T120時間切れ）
    → GAME_END

契約（型A〜D）・即時取引・匿名通信・報奨・DM は Action として受け取っても
処理を素通りする（ACTION_UNHANDLED イベントを記録するのみ）。実処理は次サイクル。
"""

from typing import Any

from engine.cards import board_counts
from engine.config import GameConfig
from engine.elimination import forced_liquidation, players_to_force_exit, players_to_timeout
from engine.events import EventLogger
from engine.exit_rules import can_exit, settle_exit
from engine.finance import apply_interest_to_all
from engine.matches import (
    accept_match, decline_match, expire_match, has_active_offer,
    make_offer_id, offer_match, resolve_match, withdraw_match,
)
from engine.models import (
    Action, Contract, ExitAction, MatchAcceptAction, MatchDeclineAction, MatchOffer,
    MatchOfferAction, MatchWithdrawAction, PassAction, PlayerState,
)
from engine.negotiation import PlayerAgent
from engine.player import create_player
from engine.rng import GameRng


class Game:
    """限定ジャンケンの1ゲームを実行する（§5のターンループ本体）"""

    def __init__(
        self, config: GameConfig, agents: dict[str, PlayerAgent], seed: int,
        logger: EventLogger,
    ) -> None:
        self.config = config
        self.agents = agents
        """player_id -> PlayerAgent"""
        self.rng = GameRng(seed)
        self.logger = logger
        self.players: dict[str, PlayerState] = {}
        self.offers: dict[str, MatchOffer] = {}
        self.contracts: list[Contract] = []
        """TODO（次サイクル）: 型A〜Dの実処理が入るまでは常に空リスト"""
        self._offer_counter = 0

    # --- セットアップ（§2.1/§2.2） ---

    def setup(self) -> None:
        """初期配布・借入を行う"""
        for player_id, agent in self.agents.items():
            loan = agent.choose_loan(self.config)
            loan = max(self.config.loan_min, min(self.config.loan_max, loan))
            self.players[player_id] = create_player(player_id, loan)
        self.logger.log("GAME_START", 0, "setup", data={
            "num_players": len(self.players),
            "total_turns": self.config.total_turns,
            "initial_loans": {pid: p.initial_loan for pid, p in self.players.items()},
        })

    # --- メインループ ---

    def run(self) -> dict[str, Any]:
        """ゲームを最後まで実行し、最終結果を返す"""
        self.setup()
        for turn in range(1, self.config.total_turns + 1):
            self._run_turn(turn)
            if not self._alive_player_ids():
                break  # 全員退場/退出済みなら早期終了
        result = self._finalize()
        self.logger.log("GAME_END", self.config.total_turns, "end", data=result)
        return result

    def _run_turn(self, turn: int) -> None:
        """1ターンの処理（§5.1 ステップ1〜8）"""
        # ステップ1（個別通知）+ ステップ2（行動の収集）
        actions = self._collect_actions(turn)

        # ステップ3: 行動の処理（ランダムな順番で処理）
        self._process_actions(turn, actions)

        # ステップ4: 対戦の開示
        self._reveal_matches(turn)

        # ステップ5: 契約の執行と監査 — TODO（次サイクル）: engine/contracts.py 参照

        # ステップ6: 強制退場の判定（★0）
        self._process_forced_exits(turn)

        # ステップ7: Finance（利息計上ターンなら計上）
        self.players = apply_interest_to_all(self.players, turn, self.config, self.logger)

        # ステップ8: 退出の処理
        # ExitAction はステップ3（_process_actions）内で即時清算しているため、
        # ここでは T120 時間切れのみを扱う。
        if turn == self.config.total_turns:
            self._process_timeouts(turn)

        # 申込の失効判定（§4.3）は毎ターン末に行う
        self._expire_offers(turn)

    # --- ステップ1/2: 個別通知・行動収集 ---

    def _alive_player_ids(self) -> list[str]:
        return [pid for pid, p in self.players.items() if p.is_alive]

    def _collect_actions(self, turn: int) -> dict[str, Action]:
        actions: dict[str, Action] = {}
        for player_id in self._alive_player_ids():
            player = self.players[player_id]
            visible_state = self._build_visible_state(player_id, turn)
            actions[player_id] = self.agents[player_id].act(player, turn, visible_state)
        return actions

    def _build_visible_state(self, player_id: str, turn: int) -> dict[str, Any]:
        """
        個別通知（§5.3）+ 公開情報（§8.1）を構築する

        TODO（次サイクル）: llm/prompt_builder.py 側の本実装とあわせて、DM秘匿
        （§8.2）・契約内容秘匿などの完全な可視状態構築に置き換える。
        本サイクルは StubAgent 専用の最小構成。
        """
        player = self.players[player_id]
        alive = [p for p in self.players.values() if p.is_alive]
        incoming = [o for o in self.offers.values()
                    if o.opponent_id == player_id and o.status == "pending"]
        outgoing = [o for o in self.offers.values()
                    if o.challenger_id == player_id and o.status in ("pending", "accepted")]
        return {
            "config": self.config,
            "turn": turn,
            "remaining_turns": self.config.total_turns - turn,
            "board": board_counts(alive),
            "my_stars": player.stars,
            "my_card_count": len(player.cards),
            "min_turns_to_clear_hand": len(player.cards) * 2,
            "offers_incoming": incoming,
            "offers_outgoing": outgoing,
            "alive_player_ids": [p.player_id for p in alive if p.player_id != player_id],
        }

    # --- ステップ3: 行動の処理 ---

    def _process_actions(self, turn: int, actions: dict[str, Action]) -> None:
        order = self.rng.shuffle_action_order(list(actions.keys()))
        for player_id in order:
            self._apply_action(turn, player_id, actions[player_id])

    def _apply_action(self, turn: int, player_id: str, action: Action) -> None:
        player = self.players[player_id]
        if isinstance(action, PassAction):
            return
        if isinstance(action, MatchOfferAction):
            self._handle_match_offer(turn, player, action)
            return
        if isinstance(action, MatchAcceptAction):
            self._handle_match_accept(turn, player, action)
            return
        if isinstance(action, MatchDeclineAction):
            self._handle_match_decline(turn, player, action)
            return
        if isinstance(action, MatchWithdrawAction):
            self._handle_match_withdraw(turn, player, action)
            return
        if isinstance(action, ExitAction):
            self._handle_exit(turn, player)
            return
        # TODO（次サイクル）: dm / broadcast / anonymous_broadcast / transfer / repay /
        # trade_* / contract_* / bounty_* はまだ処理しない。
        self.logger.log("ACTION_UNHANDLED", turn, "resolve", data={
            "player_id": player_id, "action_type": action.type,
        })

    def _handle_match_offer(self, turn: int, player: PlayerState, action: MatchOfferAction) -> None:
        if has_active_offer(player.player_id, list(self.offers.values())):
            self.logger.log("MATCH_OFFER_REJECTED", turn, "resolve", data={
                "player_id": player.player_id, "reason": "already_has_active_offer",
            })
            return
        self._offer_counter += 1
        offer_id = make_offer_id(turn, player.player_id, self._offer_counter)
        try:
            updated, offer = offer_match(
                offer_id, player, action.opponent_id, action.hand, action.card_id, turn,
            )
        except ValueError as e:
            self.logger.log("MATCH_OFFER_REJECTED", turn, "resolve", data={
                "player_id": player.player_id, "reason": str(e),
            })
            return
        self.players[player.player_id] = updated
        self.offers[offer_id] = offer
        self.logger.log("MATCH_OFFERED", turn, "resolve", data={
            "offer_id": offer_id, "challenger_id": player.player_id,
            "opponent_id": action.opponent_id,
        })

    def _handle_match_accept(self, turn: int, player: PlayerState, action: MatchAcceptAction) -> None:
        offer = self.offers.get(action.offer_id)
        if offer is None:
            self.logger.log("MATCH_ACCEPT_REJECTED", turn, "resolve", data={
                "player_id": player.player_id, "offer_id": action.offer_id, "reason": "not_found",
            })
            return
        try:
            updated, new_offer = accept_match(offer, player, action.hand, action.card_id)
        except ValueError as e:
            self.logger.log("MATCH_ACCEPT_REJECTED", turn, "resolve", data={
                "player_id": player.player_id, "offer_id": action.offer_id, "reason": str(e),
            })
            return
        self.players[player.player_id] = updated
        self.offers[action.offer_id] = new_offer
        self.logger.log("MATCH_ACCEPTED", turn, "resolve", data={
            "offer_id": action.offer_id, "opponent_id": player.player_id,
        })

    def _handle_match_decline(self, turn: int, player: PlayerState, action: MatchDeclineAction) -> None:
        offer = self.offers.get(action.offer_id)
        if offer is None or offer.opponent_id != player.player_id or offer.status != "pending":
            return
        challenger = self.players[offer.challenger_id]
        updated_challenger, new_offer = decline_match(offer, challenger)
        self.players[offer.challenger_id] = updated_challenger
        self.offers[action.offer_id] = new_offer
        self.logger.log("MATCH_DECLINED", turn, "resolve", data={"offer_id": action.offer_id})

    def _handle_match_withdraw(self, turn: int, player: PlayerState, action: MatchWithdrawAction) -> None:
        offer = self.offers.get(action.offer_id)
        if offer is None or offer.challenger_id != player.player_id:
            return
        try:
            updated, new_offer = withdraw_match(offer, player)
        except ValueError:
            return
        self.players[player.player_id] = updated
        self.offers[action.offer_id] = new_offer
        self.logger.log("MATCH_WITHDRAWN", turn, "resolve", data={"offer_id": action.offer_id})

    def _handle_exit(self, turn: int, player: PlayerState) -> None:
        # TODO（次サイクル）: has_unfulfilled_obligation の実判定（契約実装後）
        ok, reason = can_exit(player, self.config, has_unfulfilled_obligation=False)
        if not ok:
            self.logger.log("EXIT_REJECTED", turn, "resolve", data={
                "player_id": player.player_id, "reason": reason,
            })
            return
        updated = settle_exit(player, self.config, turn)
        self.players[player.player_id] = updated
        self.logger.log("PLAYER_EXITED", turn, "resolve", data={
            "player_id": player.player_id, "final_assets": updated.final_assets,
        })

    # --- ステップ4: 対戦の開示 ---

    def _reveal_matches(self, turn: int) -> None:
        for offer_id, offer in list(self.offers.items()):
            if offer.status != "accepted":
                continue
            challenger = self.players[offer.challenger_id]
            opponent = self.players[offer.opponent_id]
            new_challenger, new_opponent, result, new_offer = resolve_match(
                offer, challenger, opponent, turn,
            )
            self.players[offer.challenger_id] = new_challenger
            self.players[offer.opponent_id] = new_opponent
            self.offers[offer_id] = new_offer
            self.logger.log("MATCH_RESOLVED", turn, "reveal", data=result.model_dump())

    # --- ステップ6: 強制退場 ---

    def _process_forced_exits(self, turn: int) -> None:
        for pid in players_to_force_exit(list(self.players.values())):
            player, self.contracts, record = forced_liquidation(
                self.players[pid], "FORCED_EXIT", turn, self.contracts,
            )
            self.players[pid] = player
            self.logger.log("FORCED_EXIT", turn, "eliminate", data=record)

    # --- ステップ8: 時間切れ（T120のみ） ---

    def _process_timeouts(self, turn: int) -> None:
        for pid in players_to_timeout(list(self.players.values())):
            player, self.contracts, record = forced_liquidation(
                self.players[pid], "TIMEOUT", turn, self.contracts,
            )
            self.players[pid] = player
            self.logger.log("TIMEOUT", turn, "exit", data=record)

    # --- 申込の失効（§4.3） ---

    def _expire_offers(self, turn: int) -> None:
        for offer_id, offer in list(self.offers.items()):
            if offer.status != "pending":
                continue
            if turn < offer.turn_offered + self.config.offer_ttl_turns:
                continue
            challenger = self.players[offer.challenger_id]
            updated, new_offer = expire_match(offer, challenger)
            self.players[offer.challenger_id] = updated
            self.offers[offer_id] = new_offer
            self.logger.log("MATCH_EXPIRED", turn, "resolve", data={"offer_id": offer_id})

    # --- 終了処理 ---

    def _finalize(self) -> dict[str, Any]:
        survivors = [p for p in self.players.values() if p.has_exited]
        eliminated = [p for p in self.players.values() if p.elimination_type is not None]
        return {
            "survivors": [p.player_id for p in survivors],
            "final_assets": {p.player_id: p.final_assets for p in survivors},
            "eliminated": {
                p.player_id: p.elimination_type for p in eliminated
            },
        }
