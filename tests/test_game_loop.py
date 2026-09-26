"""
engine/game.py の行動ディスパッチのテスト（repay / transfer / wait / 待機の起床判定）

サイクル1.5で追加した3種（§7.5送金・任意返済、§5.2待機）が実際に処理され、
ACTION_UNHANDLEDに落ちないことを保証する回帰テスト。
"""

from engine.config import GameConfig
from engine.events import EventLogger
from engine.game import Game
from engine.models import RepayAction, TransferAction, WaitAction
from engine.negotiation import StubAgent
from tests.conftest import make_player


def make_game(num_players: int = 2, total_turns: int = 10) -> Game:
    """setup()を経由せず、players辞書を手動で組み立てるための最小Game"""
    config = GameConfig.dev_small(num_players=num_players, total_turns=total_turns)
    agents = {f"P{i:02d}": StubAgent() for i in range(1, num_players + 1)}
    logger = EventLogger(fixed_timestamp="t")
    game = Game(config, agents, seed=1, logger=logger)
    game.players = {}
    return game


# --- repay（§2.4/§7.5） ---

def test_repay_settles_immediately():
    game = make_game()
    game.players["P01"] = make_player("P01", cash=1_000_000, debt=1_000_000)
    game._handle_repay(1, game.players["P01"], RepayAction(player_id="P01", amount=400_000))
    assert game.players["P01"].cash == 600_000
    assert game.players["P01"].debt == 600_000
    assert any(e.event_type == "REPAID" for e in game.logger.events)
    assert not any(e.event_type == "ACTION_UNHANDLED" for e in game.logger.events)


def test_repay_rejects_non_positive_amount():
    game = make_game()
    game.players["P01"] = make_player("P01", cash=1_000_000, debt=1_000_000)
    game._handle_repay(1, game.players["P01"], RepayAction(player_id="P01", amount=0))
    assert game.players["P01"].debt == 1_000_000  # 変化なし
    reasons = [e.data.get("reason") for e in game.logger.events if e.event_type == "REPAY_REJECTED"]
    assert "non_positive_amount" in reasons


def test_repay_locked_before_unlock_turn():
    config = GameConfig.default_20().model_copy(update={"repay_unlock_turn": 5})
    logger = EventLogger(fixed_timestamp="t")
    game = Game(config, {"P01": StubAgent()}, seed=1, logger=logger)
    game.players = {"P01": make_player("P01", cash=1_000_000, debt=1_000_000)}
    game._handle_repay(3, game.players["P01"], RepayAction(player_id="P01", amount=1_000_000))
    assert game.players["P01"].debt == 1_000_000  # T3はロック中なので変化なし
    reasons = [e.data.get("reason") for e in game.logger.events if e.event_type == "REPAY_REJECTED"]
    assert "repay_locked" in reasons


def test_repay_caps_at_cash_and_debt():
    """repay_debt()自体がmin(amount, cash, debt)に調整する（engine/player.py）ことの確認"""
    game = make_game()
    game.players["P01"] = make_player("P01", cash=300_000, debt=1_000_000)
    game._handle_repay(1, game.players["P01"], RepayAction(player_id="P01", amount=1_000_000))
    assert game.players["P01"].cash == 0
    assert game.players["P01"].debt == 700_000


# --- transfer（§7.5） ---

def test_transfer_moves_cash_between_players():
    game = make_game()
    game.players["P01"] = make_player("P01", cash=1_000_000)
    game.players["P02"] = make_player("P02", cash=500_000)
    game._handle_transfer(1, game.players["P01"], TransferAction(player_id="P01", to="P02", amount=300_000))
    assert game.players["P01"].cash == 700_000
    assert game.players["P02"].cash == 800_000
    assert any(e.event_type == "TRANSFERRED" for e in game.logger.events)


def test_transfer_rejects_insufficient_cash():
    game = make_game()
    game.players["P01"] = make_player("P01", cash=100_000)
    game.players["P02"] = make_player("P02", cash=500_000)
    game._handle_transfer(1, game.players["P01"], TransferAction(player_id="P01", to="P02", amount=300_000))
    assert game.players["P01"].cash == 100_000  # 変化なし
    assert game.players["P02"].cash == 500_000
    reasons = [e.data.get("reason") for e in game.logger.events if e.event_type == "TRANSFER_REJECTED"]
    assert "insufficient_cash" in reasons


def test_transfer_rejects_self_and_unknown_target():
    game = make_game()
    game.players["P01"] = make_player("P01", cash=1_000_000)
    game._handle_transfer(1, game.players["P01"], TransferAction(player_id="P01", to="P01", amount=100))
    game._handle_transfer(1, game.players["P01"], TransferAction(player_id="P01", to="P99", amount=100))
    assert game.players["P01"].cash == 1_000_000
    assert sum(1 for e in game.logger.events if e.event_type == "TRANSFER_REJECTED") == 2


def test_transfer_rejects_dead_target():
    game = make_game()
    game.players["P01"] = make_player("P01", cash=1_000_000)
    game.players["P02"] = make_player("P02", cash=500_000, is_alive=False)
    game._handle_transfer(1, game.players["P01"], TransferAction(player_id="P01", to="P02", amount=100_000))
    assert game.players["P01"].cash == 1_000_000
    assert game.players["P02"].cash == 500_000


# --- wait（§5.2: 待機中はLLMを呼ばない） ---

def test_wait_registers_and_skips_next_collect(monkeypatch):
    game = make_game(num_players=1, total_turns=10)
    game.players["P01"] = make_player("P01", cash=1_000_000)
    game._handle_wait(1, game.players["P01"], WaitAction(player_id="P01", until_turn=5, wake_on_event=False))
    assert "P01" in game._waiting
    assert any(e.event_type == "WAIT_STARTED" for e in game.logger.events)

    called = {"n": 0}
    original_act = StubAgent.act

    def counting_act(self, *args, **kwargs):
        called["n"] += 1
        return original_act(self, *args, **kwargs)

    monkeypatch.setattr(StubAgent, "act", counting_act)
    game._collect_actions(2)  # まだuntil_turn未満なのでagent.act()を呼ばない
    assert called["n"] == 0
    assert "P01" in game._waiting  # 起きていない


def test_wait_wakes_on_until_turn():
    game = make_game(num_players=1, total_turns=10)
    game.players["P01"] = make_player("P01", cash=1_000_000)
    game._waiting["P01"] = {"until_turn": 5, "wake_on_event": False}
    visible_state = game._build_visible_state("P01", 5)
    assert game._should_wake(5, game._waiting["P01"], visible_state) is True
    assert game._should_wake(4, game._waiting["P01"], visible_state) is False


def test_wait_wakes_on_incoming_offer_when_wake_on_event():
    game = make_game(num_players=2, total_turns=10)
    game.players["P01"] = make_player("P01", cash=1_000_000)
    game.players["P02"] = make_player("P02", cash=1_000_000)
    wait_state = {"until_turn": None, "wake_on_event": True}
    visible_state_no_offer = game._build_visible_state("P01", 1)
    assert game._should_wake(1, wait_state, visible_state_no_offer) is False

    from engine.matches import offer_match
    from engine.models import Hand
    updated, offer = offer_match("M1", game.players["P02"], "P01", Hand.ROCK, game.players["P02"].cards[0].card_id, turn=1)
    game.players["P02"] = updated
    game.offers["M1"] = offer
    visible_state_with_offer = game._build_visible_state("P01", 2)
    assert game._should_wake(2, wait_state, visible_state_with_offer) is True


def test_wait_clamps_until_turn_beyond_total_turns():
    """
    実測で発見した実害の二重防止線: LLMが "until_turn": 500 のような
    total_turnsを超える値を返しても、そのターンで確実に起床できるようにする
    （llm/response_parser.py側の必須化と合わせた二重の安全策）。
    """
    game = make_game(num_players=1, total_turns=10)
    game.players["P01"] = make_player("P01", cash=1_000_000)
    game._handle_wait(1, game.players["P01"], WaitAction(player_id="P01", until_turn=500, wake_on_event=False))
    assert game._waiting["P01"]["until_turn"] == 10


def test_forced_exit_clears_waiting_state():
    game = make_game(num_players=1, total_turns=10)
    game.players["P01"] = make_player("P01", cash=1_000_000, stars=0)
    game._waiting["P01"] = {"until_turn": None, "wake_on_event": True}
    game._process_forced_exits(1)
    assert "P01" not in game._waiting


# --- 残数掲示板イベント（§8.1: 毎ターン更新） ---

def test_board_updated_event_logged_every_turn():
    config = GameConfig.dev_small(num_players=2, total_turns=3)
    agents = {f"P{i:02d}": StubAgent() for i in range(1, 3)}
    logger = EventLogger(fixed_timestamp="t")
    game = Game(config, agents, seed=1, logger=logger)
    game.run()
    board_events = [e for e in game.logger.events if e.event_type == "BOARD_UPDATED"]
    assert len(board_events) == 3  # total_turns=3
    for e in board_events:
        assert set(e.data.keys()) == {"ROCK", "SCISSORS", "PAPER"}
