"""
engine/game.py の即時取引ハンドラのテスト（サイクル2.0: DM・全体発言の次に即時取引を通電）

決済コア（engine/trades.py::can_settle_trade/settle_trade）はサイクル1.5から
実装済みで検証済みのため、ここではGame側の提案ライフサイクル管理
（提案・受諾・拒否・取消・失効・通知）を検証する。
"""

from engine.config import GameConfig
from engine.events import EventLogger
from engine.game import Game
from engine.models import AssetOffer, TradeAcceptAction, TradeProposeAction, TradeRejectAction, TradeWithdrawAction
from engine.negotiation import StubAgent
from tests.conftest import make_player


def make_game(num_players: int = 3, total_turns: int = 20) -> Game:
    config = GameConfig.dev_small(num_players=num_players, total_turns=total_turns)
    agents = {f"P{i:02d}": StubAgent() for i in range(1, num_players + 1)}
    logger = EventLogger(fixed_timestamp="t")
    game = Game(config, agents, seed=1, logger=logger)
    game.players = {}
    return game


def _offer(**kwargs) -> AssetOffer:
    return AssetOffer(**kwargs)


# --- 提案（propose） ---

def test_trade_propose_creates_pending_trade():
    game = make_game()
    game.players["P01"] = make_player("P01", cards=[])
    game.players["P02"] = make_player("P02", cards=[])
    action = TradeProposeAction(
        player_id="P01", target_id="P02",
        give=_offer(cash=100_000), receive=_offer(stars=1),
    )
    game._handle_trade_propose(1, game.players["P01"], action)
    assert len(game.trades) == 1
    trade = next(iter(game.trades.values()))
    assert trade.status == "pending"
    assert trade.proposer_id == "P01"
    assert trade.target_id == "P02"
    events = [e for e in game.logger.events if e.event_type == "TRADE_PROPOSED"]
    assert len(events) == 1


def test_trade_propose_rejects_self_target():
    game = make_game()
    game.players["P01"] = make_player("P01", cards=[])
    action = TradeProposeAction(player_id="P01", target_id="P01", give=_offer(cash=1), receive=_offer())
    game._handle_trade_propose(1, game.players["P01"], action)
    assert len(game.trades) == 0


def test_trade_propose_rejects_empty_trade():
    game = make_game()
    game.players["P01"] = make_player("P01", cards=[])
    game.players["P02"] = make_player("P02", cards=[])
    action = TradeProposeAction(player_id="P01", target_id="P02", give=_offer(), receive=_offer())
    game._handle_trade_propose(1, game.players["P01"], action)
    assert len(game.trades) == 0
    events = [e for e in game.logger.events if e.event_type == "TRADE_PROPOSE_REJECTED"]
    assert events[0].data["reason"] == "empty_trade"


def test_trade_propose_rejects_when_cannot_afford_give():
    game = make_game()
    game.players["P01"] = make_player("P01", cards=[], stars=0)
    game.players["P02"] = make_player("P02", cards=[])
    action = TradeProposeAction(player_id="P01", target_id="P02", give=_offer(stars=1), receive=_offer(cash=1))
    game._handle_trade_propose(1, game.players["P01"], action)
    assert len(game.trades) == 0
    events = [e for e in game.logger.events if e.event_type == "TRADE_PROPOSE_REJECTED"]
    assert events[0].data["reason"] == "cannot_afford_give"


def test_trade_propose_rejects_duplicate_pending_trade():
    game = make_game()
    game.players["P01"] = make_player("P01", cards=[], cash=10_000_000)
    game.players["P02"] = make_player("P02", cards=[])
    action = TradeProposeAction(player_id="P01", target_id="P02", give=_offer(cash=1), receive=_offer())
    game._handle_trade_propose(1, game.players["P01"], action)
    game._handle_trade_propose(2, game.players["P01"], action)
    assert len(game.trades) == 1
    events = [e for e in game.logger.events if e.event_type == "TRADE_PROPOSE_REJECTED"]
    assert events[0].data["reason"] == "duplicate_trade"


# --- 受諾（accept）: 原子的決済 ---

def test_trade_accept_settles_cards_stars_cash_atomically():
    game = make_game()
    game.players["P01"] = make_player("P01", cards=[], stars=3, cash=2_000_000)
    game.players["P02"] = make_player("P02", cards=[], stars=3, cash=1_000_000)
    from engine.cards import create_deck
    p01_cards = create_deck("P01")[:1]  # 1枚だけ持たせる
    game.players["P01"] = game.players["P01"].model_copy(update={"cards": p01_cards})

    # P01がカード1枚+★1個をP02へ渡し、P02が80万円をP01へ渡す
    action = TradeProposeAction(
        player_id="P01", target_id="P02",
        give=_offer(card_ids=[p01_cards[0].card_id], stars=1),
        receive=_offer(cash=800_000),
    )
    game._handle_trade_propose(1, game.players["P01"], action)
    trade_id = next(iter(game.trades.keys()))

    game._handle_trade_accept(2, game.players["P02"], TradeAcceptAction(player_id="P02", trade_id=trade_id))

    assert game.trades[trade_id].status == "accepted"
    assert len(game.players["P01"].cards) == 0
    assert len(game.players["P02"].cards) == 1
    assert game.players["P01"].stars == 2
    assert game.players["P02"].stars == 4
    assert game.players["P01"].cash == 2_000_000 + 800_000
    assert game.players["P02"].cash == 1_000_000 - 800_000
    events = [e for e in game.logger.events if e.event_type == "TRADE_ACCEPTED"]
    assert len(events) == 1
    assert events[0].data["give"]["stars"] == 1


def test_trade_accept_only_by_target():
    game = make_game()
    game.players["P01"] = make_player("P01", cards=[], cash=10_000_000)
    game.players["P02"] = make_player("P02", cards=[])
    game.players["P03"] = make_player("P03", cards=[])
    action = TradeProposeAction(player_id="P01", target_id="P02", give=_offer(cash=1), receive=_offer())
    game._handle_trade_propose(1, game.players["P01"], action)
    trade_id = next(iter(game.trades.keys()))

    # P03（無関係な第三者）が受諾を試みても不成立
    game._handle_trade_accept(2, game.players["P03"], TradeAcceptAction(player_id="P03", trade_id=trade_id))
    assert game.trades[trade_id].status == "pending"


def test_trade_accept_fails_gracefully_when_assets_unavailable():
    """§7.1: 受諾時点で資産不足なら不成立とし、脱落はしない"""
    game = make_game()
    game.players["P01"] = make_player("P01", cards=[], cash=1_000_000)
    game.players["P02"] = make_player("P02", cards=[], cash=0)
    action = TradeProposeAction(player_id="P01", target_id="P02", give=_offer(cash=500_000), receive=_offer(cash=100_000))
    game._handle_trade_propose(1, game.players["P01"], action)
    trade_id = next(iter(game.trades.keys()))

    # P02は現金0なので100,000円を出せない
    game._handle_trade_accept(2, game.players["P02"], TradeAcceptAction(player_id="P02", trade_id=trade_id))

    assert game.trades[trade_id].status == "expired"
    assert game.players["P01"].cash == 1_000_000  # 1円も動いていない
    assert game.players["P02"].cash == 0
    assert game.players["P01"].is_alive  # 脱落していない
    events = [e for e in game.logger.events if e.event_type == "TRADE_FAILED"]
    assert events[0].data["reason"] == "assets_unavailable"


def test_trade_accept_does_not_touch_reserved_cards():
    """予約中のカードは取引に出せない（対戦申込中のカードの二重使用防止）"""
    game = make_game()
    from engine.cards import create_deck
    p01_cards = create_deck("P01")[:1]
    game.players["P01"] = make_player("P01", cards=p01_cards, reserved_card_ids=[p01_cards[0].card_id])
    game.players["P02"] = make_player("P02", cards=[])
    action = TradeProposeAction(
        player_id="P01", target_id="P02",
        give=_offer(card_ids=[p01_cards[0].card_id]), receive=_offer(),
    )
    game._handle_trade_propose(1, game.players["P01"], action)
    assert len(game.trades) == 0  # 予約中カードなのでpropose時点で拒否される


# --- 拒否（reject）・取消（withdraw） ---

def test_trade_reject_only_by_target():
    game = make_game()
    game.players["P01"] = make_player("P01", cards=[], cash=1)
    game.players["P02"] = make_player("P02", cards=[])
    action = TradeProposeAction(player_id="P01", target_id="P02", give=_offer(cash=1), receive=_offer())
    game._handle_trade_propose(1, game.players["P01"], action)
    trade_id = next(iter(game.trades.keys()))
    game._handle_trade_reject(2, game.players["P02"], TradeRejectAction(player_id="P02", trade_id=trade_id))
    assert game.trades[trade_id].status == "rejected"


def test_trade_withdraw_only_by_proposer():
    game = make_game()
    game.players["P01"] = make_player("P01", cards=[], cash=1)
    game.players["P02"] = make_player("P02", cards=[])
    action = TradeProposeAction(player_id="P01", target_id="P02", give=_offer(cash=1), receive=_offer())
    game._handle_trade_propose(1, game.players["P01"], action)
    trade_id = next(iter(game.trades.keys()))
    game._handle_trade_withdraw(2, game.players["P01"], TradeWithdrawAction(player_id="P01", trade_id=trade_id))
    assert game.trades[trade_id].status == "withdrawn"


# --- 失効（§7.1: 提案した翌ターンの終わりまで） ---

def test_trade_expires_after_ttl():
    game = make_game(total_turns=10)
    game.players["P01"] = make_player("P01", cards=[], cash=1)
    game.players["P02"] = make_player("P02", cards=[])
    action = TradeProposeAction(player_id="P01", target_id="P02", give=_offer(cash=1), receive=_offer())
    game._handle_trade_propose(1, game.players["P01"], action)
    trade_id = next(iter(game.trades.keys()))

    game._expire_trades(1)  # trade_ttl_turns=1なのでT1ではまだ失効しない
    assert game.trades[trade_id].status == "pending"

    game._expire_trades(2)  # T1+1=T2で失効
    assert game.trades[trade_id].status == "expired"
    assert game.players["P01"].cash == 1  # 資産は一切動いていない


# --- 可視状態（trades_incoming/trades_outgoing） ---

def test_visible_state_includes_trades_incoming_and_outgoing():
    game = make_game()
    game.players["P01"] = make_player("P01", cards=[], cash=1)
    game.players["P02"] = make_player("P02", cards=[])
    action = TradeProposeAction(player_id="P01", target_id="P02", give=_offer(cash=1), receive=_offer())
    game._handle_trade_propose(1, game.players["P01"], action)

    state_p01 = game._build_visible_state("P01", 2)
    state_p02 = game._build_visible_state("P02", 2)
    assert len(state_p01["trades_outgoing"]) == 1
    assert len(state_p01["trades_incoming"]) == 0
    assert len(state_p02["trades_incoming"]) == 1
    assert len(state_p02["trades_outgoing"]) == 0


def test_wait_wakes_on_incoming_trade():
    game = make_game()
    game.players["P01"] = make_player("P01", cards=[], cash=1)
    game.players["P02"] = make_player("P02", cards=[])
    action = TradeProposeAction(player_id="P01", target_id="P02", give=_offer(cash=1), receive=_offer())
    game._handle_trade_propose(1, game.players["P01"], action)

    visible_state = game._build_visible_state("P02", 2)
    assert game._should_wake(2, {"until_turn": None, "wake_on_event": True}, visible_state) is True
