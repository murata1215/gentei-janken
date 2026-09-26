"""
ゲーム進行モジュール（§5）

120ターンのターンループを実行する。サイクル1.5までに実装する範囲:

    初期配布 → 借入 → 120ターンループ
      （対戦の申込/受諾/拒否/取り下げ・開示、★移動、掲示板更新、
       任意返済、送金、待機（LLM呼び出しスキップ）、
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
from engine.exit_rules import buyback_amount, can_exit, settle_exit
from engine.finance import apply_interest_to_all
from engine.matches import (
    accept_match, decline_match, expire_match, has_active_offer,
    make_offer_id, offer_match, resolve_match, withdraw_match,
)
from engine.messages import can_send_anonymous, format_message_body, make_message_id, visible_messages
from engine.models import (
    Action, AnonymousBroadcastAction, BroadcastAction, Contract, DmAction, ExitAction,
    MatchAcceptAction, MatchDeclineAction, MatchOffer, MatchOfferAction, MatchOutcome,
    MatchWithdrawAction, Message, PassAction, PlayerState, RepayAction, TradeAcceptAction,
    TradeProposal, TradeProposeAction, TradeRejectAction, TradeWithdrawAction, TransferAction,
    WaitAction,
)
from engine.negotiation import PlayerAgent
from engine.player import can_pay, can_repay_now, create_player, pay, receive, repay_debt
from engine.rng import GameRng
from engine.trades import can_settle_trade, make_trade_id, settle_trade


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
        self._match_record: dict[str, dict[str, int]] = {}
        """player_id -> {"wins","losses","draws"}（§8.2「対戦の組み合わせと勝敗」は
        公開情報のため、他プレイヤーへの表示にも使う。MatchOfferには結果が残らない
        （resolve_match()はMatchResultを都度生成するだけ）ため、ここに積算する。"""
        self._offer_counter = 0
        self._waiting: dict[str, dict[str, Any]] = {}
        """player_id -> {"until_turn": int|None, "wake_on_event": bool}（§5.2 待機）"""
        self.messages: list[Message] = []
        """全ターン全件保持（削除しない。§5.2 waitの「DMが届いたら起こして」と
        起床トリガの寿命を一致させるため）。表示件数の絞り込みはプロンプト側で行う"""
        self._anon_message_owners: dict[str, str] = {}
        """message_id -> 実送信者（§8.2秘匿。messagesオブジェクト自体には乗せない）"""
        self._message_counter = 0
        self._anon_sent_this_turn: dict[str, int] = {}
        """player_id -> このターンに送った匿名通信の数（§7.5: 1ターン1通まで、毎ターン先頭でクリア）"""
        self._message_seen_turn: dict[str, int] = {}
        """player_id -> 最後にact()が呼ばれたターン（プロンプト表示窓の外でも
        自分宛未読DMを出すための判定に使う。待機中は更新されず、寝ている間の
        DMは全て「未読」のまま蓄積する）"""
        self.trades: dict[str, TradeProposal] = {}
        """即時取引の提案（§7.1）。engine/trades.pyの決済コアはサイクル1.5から
        実装済みで、Game側は提案ライフサイクル（提案・受諾・拒否・取消・失効）
        の管理のみを担う"""
        self._trade_counter = 0
        self._trade_notices: dict[str, list[dict[str, Any]]] = {}
        """player_id -> 個別通知（不成立等）。§7.1「受諾時点で資産不足なら不成立、
        脱落はしない」を通知する経路（契約のnotice機構と同じ思想だが契約自体は未実装）"""

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
        self._anon_sent_this_turn.clear()

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
        # 取引提案の失効判定（§7.1）
        self._expire_trades(turn)

        # 残数掲示板の更新（§8.1: 毎ターンの処理が終わった時点で更新する。公開情報）
        alive = [p for p in self.players.values() if p.is_alive]
        self.logger.log("BOARD_UPDATED", turn, "resolve", data=board_counts(alive))

    # --- ステップ1/2: 個別通知・行動収集 ---

    def _alive_player_ids(self) -> list[str]:
        return [pid for pid, p in self.players.items() if p.is_alive]

    def _collect_actions(self, turn: int) -> dict[str, Action]:
        actions: dict[str, Action] = {}
        for player_id in self._alive_player_ids():
            player = self.players[player_id]
            visible_state = self._build_visible_state(player_id, turn)
            wait_state = self._waiting.get(player_id)
            if wait_state is not None:
                if not self._should_wake(turn, wait_state, visible_state):
                    continue  # 待機中: LLMを呼ばずにこのターンを飛ばす（§5.2）
                del self._waiting[player_id]
            actions[player_id] = self.agents[player_id].act(player, turn, visible_state)
            self._message_seen_turn[player_id] = turn
        return actions

    def _should_wake(self, turn: int, wait_state: dict[str, Any], visible_state: dict[str, Any]) -> bool:
        """待機中のプレイヤーを起こすべきか判定する（§5.2）

        DM・対戦申込・取引提案のいずれかが届いたら起こす。全体発言・匿名通信は
        意図的に起床条件から除外する——1人がbroadcastしただけで待機中の全員が
        起きると、待機機構（LLM呼び出し削減）の目的が真逆になる（§5.2は
        「DM・対戦申込・取引提案」とだけ列挙しており全体発言は含まれない）。
        """
        until_turn = wait_state.get("until_turn")
        if until_turn is not None and turn >= until_turn:
            return True
        if wait_state.get("wake_on_event"):
            if visible_state.get("offers_incoming"):
                return True
            if visible_state.get("dms_unread"):
                return True
            if visible_state.get("trades_incoming"):
                return True
        return False

    def _projected_assets(self, player: PlayerState) -> int:
        """清算後の資産見込み（§5.3 7項目目）。退出済み/脱落済みでも同じ式で正しい値になる"""
        return player.cash + buyback_amount(player, self.config) - player.debt

    def _projected_rank(self, player_id: str) -> tuple[int, int]:
        """清算後資産の見込みで順位付けする（タイブレークはplayer_id昇順で決定的に）"""
        ranked = sorted(
            self.players.values(),
            key=lambda p: (-self._projected_assets(p), p.player_id),
        )
        total = len(ranked)
        for idx, p in enumerate(ranked, start=1):
            if p.player_id == player_id:
                return idx, total
        return total, total

    def _build_visible_state(self, player_id: str, turn: int) -> dict[str, Any]:
        """個別通知（§5.3）+ 公開情報（§8.1）を構築する"""
        player = self.players[player_id]
        alive = [p for p in self.players.values() if p.is_alive]
        incoming = [o for o in self.offers.values()
                    if o.opponent_id == player_id and o.status == "pending"]
        outgoing = [o for o in self.offers.values()
                    if o.challenger_id == player_id and o.status in ("pending", "accepted")]
        rank, rank_total = self._projected_rank(player_id)
        messages, dms_unread = self._visible_messages_for(player_id, turn)
        trades_incoming = [t for t in self.trades.values()
                           if t.target_id == player_id and t.status == "pending"]
        trades_outgoing = [t for t in self.trades.values()
                           if t.proposer_id == player_id and t.status == "pending"]
        # messagesと同じ「削除しない・窓で絞る」方式。act()を呼ばずに_build_visible_state
        # だけ呼ばれるケース（_should_wakeの判定時）でも消費されない（pop方式だと
        # 待機中に読まれないまま消えてしまう）。
        window_start = turn - self.config.message_prompt_window_turns
        trade_notices = [n for n in self._trade_notices.get(player_id, []) if n["turn"] >= window_start]
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
            # alive_player_idsはbots/（aggressor_bot.py・draw_alliance_bot.py）が
            # 参照しているため残す。opponentsはLLM向けの★・成績付き詳細版。
            "alive_player_ids": [p.player_id for p in alive if p.player_id != player_id],
            "opponents": self._opponent_public_stats(player_id),
            "projected_rank": rank,
            "projected_rank_total": rank_total,
            "messages": messages,
            "dms_unread": dms_unread,
            "trades_incoming": trades_incoming,
            "trades_outgoing": trades_outgoing,
            "trade_notices": trade_notices,
        }

    def _visible_messages_for(self, player_id: str, turn: int) -> tuple[list[dict[str, Any]], bool]:
        """
        プロンプトに載せるメッセージを組み立てる（§5.2）

        2段フィルタ: ①visible_messages()による可視性の投影（秘匿境界）
        ②直近message_prompt_window_turns・最大message_prompt_limit件に絞る。
        自分宛の未読DM（前回act()が呼ばれたターンより後のもの）は窓の外でも
        必ず全件含める——寝ていたプレイヤーが起きた時に起床理由のDMが
        表示から漏れることを防ぐ。
        """
        all_visible = visible_messages(self.messages, self._anon_message_owners, player_id)
        last_seen = self._message_seen_turn.get(player_id, -1)
        unread_dms = [
            m for m in all_visible
            if m["type"] == "dm" and m.get("to") == player_id and m["turn"] > last_seen
        ]
        window_start = turn - self.config.message_prompt_window_turns
        recent = [m for m in all_visible if m["turn"] >= window_start]
        recent = recent[-self.config.message_prompt_limit:]
        combined: dict[str, dict[str, Any]] = {m["message_id"]: m for m in recent}
        for m in unread_dms:
            combined[m["message_id"]] = m
        ordered = sorted(combined.values(), key=lambda m: (m["turn"], m["message_id"]))
        return ordered, bool(unread_dms)

    def _opponent_public_stats(self, player_id: str) -> list[dict[str, Any]]:
        """
        他プレイヤーの公開情報を★降順で返す（§8.2: ★の数・初期借入額は公開情報）

        対戦の組み合わせと勝敗も§8.2で公開情報だが、個々の対戦ではなく
        通算成績（wins/losses/draws）として渡す。手札の中身・現金・借金は含めない。
        """
        alive = [p for p in self.players.values() if p.is_alive and p.player_id != player_id]
        ordered = sorted(alive, key=lambda p: (-p.stars, p.player_id))
        stats = []
        for p in ordered:
            record = self._match_record.get(p.player_id, {"wins": 0, "losses": 0, "draws": 0})
            stats.append({
                "player_id": p.player_id,
                "stars": p.stars,
                "initial_loan": p.initial_loan,
                "wins": record["wins"], "losses": record["losses"], "draws": record["draws"],
            })
        return stats

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
        if isinstance(action, RepayAction):
            self._handle_repay(turn, player, action)
            return
        if isinstance(action, TransferAction):
            self._handle_transfer(turn, player, action)
            return
        if isinstance(action, WaitAction):
            self._handle_wait(turn, player, action)
            return
        if isinstance(action, DmAction):
            self._handle_dm(turn, player, action)
            return
        if isinstance(action, BroadcastAction):
            self._handle_broadcast(turn, player, action)
            return
        if isinstance(action, AnonymousBroadcastAction):
            self._handle_anonymous_broadcast(turn, player, action)
            return
        if isinstance(action, TradeProposeAction):
            self._handle_trade_propose(turn, player, action)
            return
        if isinstance(action, TradeAcceptAction):
            self._handle_trade_accept(turn, player, action)
            return
        if isinstance(action, TradeRejectAction):
            self._handle_trade_reject(turn, player, action)
            return
        if isinstance(action, TradeWithdrawAction):
            self._handle_trade_withdraw(turn, player, action)
            return
        # TODO（次サイクル）: contract_* / bounty_* はまだ処理しない。
        self.logger.log("ACTION_UNHANDLED", turn, "resolve", data={
            "player_id": player_id, "action_type": action.type,
        })

    def _handle_dm(self, turn: int, player: PlayerState, action: DmAction) -> None:
        """DM送信（§5.2）。行動枠を1つ消費する"""
        target = self.players.get(action.to)
        if target is None or target.player_id == player.player_id or not target.is_alive:
            self.logger.log("DM_REJECTED", turn, "resolve", data={
                "player_id": player.player_id, "reason": "invalid_target",
            })
            return
        body = action.message.strip()
        if not body:
            self.logger.log("DM_REJECTED", turn, "resolve", data={
                "player_id": player.player_id, "reason": "empty_message",
            })
            return
        body = format_message_body(body, self.config.message_max_length)
        self._message_counter += 1
        message_id = make_message_id(turn, self._message_counter)
        self.messages.append(Message(
            message_id=message_id, sender=player.player_id, type="dm",
            to=action.to, message=body, turn=turn,
        ))
        # dataには本文(god専用)も入れる。public投影はviewer/log_parser.pyの
        # PUBLIC_EVENT_DATA_KEYSがmessageキーを落とす（§8.2 DM本文は秘匿）。
        self.logger.log("DM_SENT", turn, "resolve", data={
            "sender": player.player_id, "to": action.to, "message": body, "turn": turn,
        })

    def _handle_broadcast(self, turn: int, player: PlayerState, action: BroadcastAction) -> None:
        """全体発言（§5.2）。本文・発信者ともに公開情報（§8.2）"""
        body = action.message.strip()
        if not body:
            self.logger.log("BROADCAST_REJECTED", turn, "resolve", data={
                "player_id": player.player_id, "reason": "empty_message",
            })
            return
        body = format_message_body(body, self.config.message_max_length)
        self._message_counter += 1
        message_id = make_message_id(turn, self._message_counter)
        self.messages.append(Message(
            message_id=message_id, sender=player.player_id, type="broadcast",
            to=None, message=body, turn=turn,
        ))
        self.logger.log("BROADCAST_SENT", turn, "resolve", data={
            "sender": player.player_id, "message": body, "turn": turn,
        })

    def _handle_anonymous_broadcast(self, turn: int, player: PlayerState, action: AnonymousBroadcastAction) -> None:
        """匿名通信（§7.5: 10万円で1メッセージ、1ターン1通まで。発信者は秘匿）"""
        body = action.message.strip()
        if not body:
            self.logger.log("ANON_BROADCAST_REJECTED", turn, "resolve", data={
                "player_id": player.player_id, "reason": "empty_message",
            })
            return
        sent_this_turn = self._anon_sent_this_turn.get(player.player_id, 0)
        ok, reason = can_send_anonymous(player, self.config, sent_this_turn)
        if not ok:
            self.logger.log("ANON_BROADCAST_REJECTED", turn, "resolve", data={
                "player_id": player.player_id, "reason": reason,
            })
            return
        self.players[player.player_id] = pay(player, self.config.anonymous_message_fee)
        self._anon_sent_this_turn[player.player_id] = sent_this_turn + 1
        body = format_message_body(body, self.config.message_max_length)
        self._message_counter += 1
        message_id = make_message_id(turn, self._message_counter)
        # senderは常にNone（Messageオブジェクト自体に実送信者を乗せない）。
        # 実送信者は_anon_message_ownersにのみ保持する（§8.2秘匿の構造的担保）。
        self.messages.append(Message(
            message_id=message_id, sender=None, type="anonymous_broadcast",
            to=None, message=body, turn=turn,
        ))
        self._anon_message_owners[message_id] = player.player_id
        # dataのsenderはgod専用（viewer/log_parser.pyのホワイトリストで落ちる）。
        self.logger.log("ANONYMOUS_BROADCAST_SENT", turn, "resolve", data={
            "message": body, "turn": turn, "sender": player.player_id,
        })

    # --- 即時取引（§7.1、サイクル2.0） ---

    def _handle_trade_propose(self, turn: int, player: PlayerState, action: TradeProposeAction) -> None:
        """
        取引を提案する（§7.1）

        受諾時点での資産確認が本来の判定タイミングだが（§7.1「受諾の時点でどちらか
        が出す資産を持っていなければ不成立」）、明らかに出せない提案が相手の
        アクション枠を無駄に食うのを防ぐため、提案時点でも自分の分だけ早期チェックする
        （これは受諾時の再検証の代替ではなく、追加の親切）。
        """
        target = self.players.get(action.target_id)
        if target is None or target.player_id == player.player_id or not target.is_alive:
            self.logger.log("TRADE_PROPOSE_REJECTED", turn, "resolve", data={
                "player_id": player.player_id, "reason": "invalid_target",
            })
            return
        if not action.give.card_ids and not action.give.stars and not action.give.cash \
                and not action.receive.card_ids and not action.receive.stars and not action.receive.cash:
            self.logger.log("TRADE_PROPOSE_REJECTED", turn, "resolve", data={
                "player_id": player.player_id, "reason": "empty_trade",
            })
            return
        if not can_settle_trade(player, player, action.give, action.give):
            # 自分がgiveを出せるかだけを軽く確認する（receiveは相手の持ち物なので
            # ここでは判定不能。厳密な検証はaccept時にcan_settle_trade()で行う）
            self.logger.log("TRADE_PROPOSE_REJECTED", turn, "resolve", data={
                "player_id": player.player_id, "reason": "cannot_afford_give",
            })
            return
        if any(t.proposer_id == player.player_id and t.target_id == action.target_id and t.status == "pending"
               for t in self.trades.values()):
            self.logger.log("TRADE_PROPOSE_REJECTED", turn, "resolve", data={
                "player_id": player.player_id, "reason": "duplicate_trade",
            })
            return
        self._trade_counter += 1
        trade_id = make_trade_id(turn, player.player_id, self._trade_counter)
        self.trades[trade_id] = TradeProposal(
            trade_id=trade_id, proposer_id=player.player_id, target_id=action.target_id,
            turn_proposed=turn, give=action.give, receive=action.receive,
        )
        # §8.2: 取引の「提案」は§8.2公開区分に明記が無く「観戦者のみ」区分に落ちる
        # （公開区分は「取引の成立（当事者2人）」のみ。対戦のMATCH_OFFEREDとは
        # 非対称になるが、仕様書の列挙に忠実に従った結果——rules/project.md冒頭
        # 「実装より仕様書が優先する」）。当事者IDもpublicには出さない。
        self.logger.log("TRADE_PROPOSED", turn, "resolve", data={
            "trade_id": trade_id, "proposer_id": player.player_id, "target_id": action.target_id,
        })

    def _handle_trade_accept(self, turn: int, player: PlayerState, action: TradeAcceptAction) -> None:
        trade = self.trades.get(action.trade_id)
        if trade is None or trade.status != "pending" or trade.target_id != player.player_id:
            self.logger.log("TRADE_ACCEPT_REJECTED", turn, "resolve", data={
                "player_id": player.player_id, "trade_id": action.trade_id, "reason": "not_found",
            })
            return
        proposer = self.players.get(trade.proposer_id)
        if proposer is None or not proposer.is_alive:
            self.trades[trade.trade_id] = trade.model_copy(update={"status": "expired"})
            self.logger.log("TRADE_EXPIRED", turn, "resolve", data={"trade_id": trade.trade_id})
            return
        if not can_settle_trade(proposer, player, trade.give, trade.receive):
            # §7.1: 受諾時点でどちらかが資産不足なら不成立とし、脱落はさせない
            self.trades[trade.trade_id] = trade.model_copy(update={"status": "expired"})
            self._trade_notices.setdefault(proposer.player_id, []).append(
                {"turn": turn, "trade_id": trade.trade_id, "reason": "assets_unavailable"})
            self._trade_notices.setdefault(player.player_id, []).append(
                {"turn": turn, "trade_id": trade.trade_id, "reason": "assets_unavailable"})
            self.logger.log("TRADE_FAILED", turn, "resolve", data={
                "trade_id": trade.trade_id, "reason": "assets_unavailable",
            })
            return
        new_proposer, new_target = settle_trade(proposer, player, trade.give, trade.receive)
        self.players[proposer.player_id] = new_proposer
        self.players[player.player_id] = new_target
        self.trades[trade.trade_id] = trade.model_copy(update={"status": "accepted"})
        stars_delta = trade.receive.stars - trade.give.stars  # proposer視点の★純増減
        # public: 取引の成立（当事者2人）は公開情報（§8.2）。★の移動も★の数自体が
        # 公開情報なので結果として見える（§7.1）。cards_moved/cash_movedはgod専用
        # （viewer/log_parser.pyのホワイトリストに列挙しないことで自動的に落ちる）。
        self.logger.log("TRADE_ACCEPTED", turn, "resolve", data={
            "trade_id": trade.trade_id, "proposer_id": proposer.player_id, "target_id": player.player_id,
            "stars_moved": {proposer.player_id: stars_delta, player.player_id: -stars_delta},
            "cards_moved": {
                proposer.player_id: len(trade.receive.card_ids) - len(trade.give.card_ids),
                player.player_id: len(trade.give.card_ids) - len(trade.receive.card_ids),
            },
            "cash_moved": {
                proposer.player_id: trade.receive.cash - trade.give.cash,
                player.player_id: trade.give.cash - trade.receive.cash,
            },
            "give": trade.give.model_dump(), "receive": trade.receive.model_dump(),
        })

    def _handle_trade_reject(self, turn: int, player: PlayerState, action: TradeRejectAction) -> None:
        trade = self.trades.get(action.trade_id)
        if trade is None or trade.status != "pending" or trade.target_id != player.player_id:
            return
        self.trades[trade.trade_id] = trade.model_copy(update={"status": "rejected"})
        self.logger.log("TRADE_REJECTED", turn, "resolve", data={"trade_id": trade.trade_id})

    def _handle_trade_withdraw(self, turn: int, player: PlayerState, action: TradeWithdrawAction) -> None:
        trade = self.trades.get(action.trade_id)
        if trade is None or trade.status != "pending" or trade.proposer_id != player.player_id:
            return
        self.trades[trade.trade_id] = trade.model_copy(update={"status": "withdrawn"})
        self.logger.log("TRADE_WITHDRAWN", turn, "resolve", data={"trade_id": trade.trade_id})

    def _expire_trades(self, turn: int) -> None:
        """取引提案の失効判定（§7.1: 提案した翌ターンの終わりまで）

        資産移動は一切発生しない（取引は対戦のような予約をしないため、
        engine/trades.pyのdocstring参照）。statusの更新とログのみ。
        """
        for trade_id, trade in list(self.trades.items()):
            if trade.status != "pending":
                continue
            if turn < trade.turn_proposed + self.config.trade_ttl_turns:
                continue
            self.trades[trade_id] = trade.model_copy(update={"status": "expired"})
            self.logger.log("TRADE_EXPIRED", turn, "resolve", data={"trade_id": trade_id})

    def _handle_repay(self, turn: int, player: PlayerState, action: RepayAction) -> None:
        """任意返済（§2.4/§7.5）。その場で決済する"""
        if action.amount <= 0:
            self.logger.log("REPAY_REJECTED", turn, "resolve", data={
                "player_id": player.player_id, "reason": "non_positive_amount",
            })
            return
        if not can_repay_now(player, turn, self.config):
            self.logger.log("REPAY_REJECTED", turn, "resolve", data={
                "player_id": player.player_id, "reason": "repay_locked",
            })
            return
        updated = repay_debt(player, action.amount)
        actual = player.debt - updated.debt
        self.players[player.player_id] = updated
        self.logger.log("REPAID", turn, "resolve", data={
            "player_id": player.player_id, "amount": actual, "new_debt": updated.debt,
        })

    def _handle_transfer(self, turn: int, player: PlayerState, action: TransferAction) -> None:
        """送金（§7.5）。その場で決済する"""
        target = self.players.get(action.to)
        if action.amount <= 0 or target is None or target.player_id == player.player_id \
                or not target.is_alive:
            self.logger.log("TRANSFER_REJECTED", turn, "resolve", data={
                "player_id": player.player_id, "to": action.to,
                "reason": "invalid_target_or_amount",
            })
            return
        if not can_pay(player, action.amount):
            self.logger.log("TRANSFER_REJECTED", turn, "resolve", data={
                "player_id": player.player_id, "to": action.to, "reason": "insufficient_cash",
            })
            return
        self.players[player.player_id] = pay(player, action.amount)
        self.players[target.player_id] = receive(target, action.amount)
        self.logger.log("TRANSFERRED", turn, "resolve", data={
            "from": player.player_id, "to": target.player_id, "amount": action.amount,
        })

    def _handle_wait(self, turn: int, player: PlayerState, action: WaitAction) -> None:
        """
        待機（§5.2）。次に起こされるまでLLMを呼ばない

        until_turn が total_turns を超える値の場合は total_turns にクランプする
        （llm/response_parser.py 側でwake_on_event/until_turn未指定は既に拒否して
        いるが、「T500まで待つ」のような値が来た場合の二重の安全策。これが無いと
        wake_on_event=Falseのまま最終ターンを過ぎてもLLMが二度と呼ばれない）。
        """
        until_turn = action.until_turn
        if until_turn is not None and until_turn > self.config.total_turns:
            until_turn = self.config.total_turns
        self._waiting[player.player_id] = {
            "until_turn": until_turn, "wake_on_event": action.wake_on_event,
        }
        self.logger.log("WAIT_STARTED", turn, "resolve", data={
            "player_id": player.player_id,
            "until_turn": until_turn, "wake_on_event": action.wake_on_event,
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
        self._waiting.pop(player.player_id, None)
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
            self._record_match_result(result.challenger_id, result.opponent_id, result.outcome)
            self.logger.log("MATCH_RESOLVED", turn, "reveal", data=result.model_dump())

    def _record_match_result(self, challenger_id: str, opponent_id: str, outcome: MatchOutcome) -> None:
        """対戦成績を積算する（§8.2の公開情報。opponents一覧の表示に使う）"""
        c_record = self._match_record.setdefault(challenger_id, {"wins": 0, "losses": 0, "draws": 0})
        o_record = self._match_record.setdefault(opponent_id, {"wins": 0, "losses": 0, "draws": 0})
        if outcome == "challenger_win":
            c_record["wins"] += 1
            o_record["losses"] += 1
        elif outcome == "opponent_win":
            o_record["wins"] += 1
            c_record["losses"] += 1
        else:
            c_record["draws"] += 1
            o_record["draws"] += 1

    # --- ステップ6: 強制退場 ---

    def _process_forced_exits(self, turn: int) -> None:
        for pid in players_to_force_exit(list(self.players.values())):
            player, self.contracts, record = forced_liquidation(
                self.players[pid], "FORCED_EXIT", turn, self.contracts,
            )
            self.players[pid] = player
            self._waiting.pop(pid, None)
            self.logger.log("FORCED_EXIT", turn, "eliminate", data=record)

    # --- ステップ8: 時間切れ（T120のみ） ---

    def _process_timeouts(self, turn: int) -> None:
        for pid in players_to_timeout(list(self.players.values())):
            player, self.contracts, record = forced_liquidation(
                self.players[pid], "TIMEOUT", turn, self.contracts,
            )
            self.players[pid] = player
            self._waiting.pop(pid, None)
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
