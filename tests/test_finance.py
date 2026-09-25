"""利息計上モジュールのテスト（§2.3）"""

from engine.config import GameConfig
from engine.events import EventLogger
from engine.finance import apply_interest_to_all, is_interest_turn
from engine.player import apply_interest
from tests.conftest import make_player


def test_is_interest_turn_default_every_10():
    config = GameConfig.default_20()
    assert is_interest_turn(10, config)
    assert is_interest_turn(120, config)
    assert not is_interest_turn(1, config)
    assert not is_interest_turn(15, config)


def test_is_interest_turn_5_turn_variant():
    """§12.1未決事項: interest_interval_turns=5にすれば計24回案に切り替わる"""
    config = GameConfig.default_20().model_copy(update={"interest_interval_turns": 5})
    assert is_interest_turn(5, config)
    assert is_interest_turn(10, config)
    assert not is_interest_turn(7, config)


def test_apply_interest_is_1_5_percent_compound_ceil():
    p = make_player("P01", debt=1_000_000)
    updated = apply_interest(p, 0.015)
    assert updated.debt == 1_000_000 + 15_000  # ちょうど割り切れる例


def test_apply_interest_rounds_up():
    p = make_player("P01", debt=1_000_001)
    updated = apply_interest(p, 0.015)
    # 1,000,001 * 0.015 = 15000.015 -> ceil = 15001
    assert updated.debt == 1_000_001 + 15_001


def test_interest_stops_after_exit():
    p = make_player("P01", debt=1_000_000)
    p = p.model_copy(update={"has_exited": True})
    updated = apply_interest(p, 0.015)
    assert updated.debt == 1_000_000  # 退出後は計上されない


def test_apply_interest_to_all_only_fires_on_interval_turn():
    config = GameConfig.default_20()
    players = {"P01": make_player("P01", debt=1_000_000)}
    logger = EventLogger()
    unchanged = apply_interest_to_all(players, turn=3, config=config, logger=logger)
    assert unchanged["P01"].debt == 1_000_000
    changed = apply_interest_to_all(players, turn=10, config=config, logger=logger)
    assert changed["P01"].debt == 1_015_000
    assert len(logger.events) == 1
    assert logger.events[0].event_type == "INTEREST"


def test_apply_interest_to_all_skips_dead_and_zero_debt():
    config = GameConfig.default_20()
    players = {
        "P01": make_player("P01", debt=0),
        "P02": make_player("P02", debt=1_000_000, is_alive=False),
    }
    logger = EventLogger()
    result = apply_interest_to_all(players, turn=10, config=config, logger=logger)
    assert result["P01"].debt == 0
    assert result["P02"].debt == 1_000_000
    assert len(logger.events) == 0


def test_twelve_intervals_over_120_turns_default_config():
    """§2.3: 初期値10ターンごと・計12回"""
    config = GameConfig.default_20()
    interest_turns = [t for t in range(1, config.total_turns + 1) if is_interest_turn(t, config)]
    assert len(interest_turns) == 12
