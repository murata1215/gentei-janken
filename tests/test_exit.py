"""退出モジュールのテスト（§6.1/§6.2）"""

from engine.config import GameConfig
from engine.exit_rules import buyback_amount, can_exit, settle_exit, surplus_stars
from tests.conftest import make_player


def test_can_exit_requires_no_cards():
    config = GameConfig.default_20()
    p = make_player("P01", stars=3, cash=2_000_000, debt=1_000_000)  # cards はデフォルトで1枚
    ok, reason = can_exit(p, config, has_unfulfilled_obligation=False)
    assert not ok and reason == "cards_remaining"


def test_can_exit_requires_min_stars():
    config = GameConfig.default_20()
    p = make_player("P01", stars=2, cash=2_000_000, debt=0, cards=[])
    ok, reason = can_exit(p, config, has_unfulfilled_obligation=False)
    assert not ok and reason == "insufficient_stars"


def test_can_exit_requires_debt_clearable():
    config = GameConfig.default_20()
    p = make_player("P01", stars=3, cash=100_000, debt=5_000_000, cards=[])
    ok, reason = can_exit(p, config, has_unfulfilled_obligation=False)
    assert not ok and reason == "cannot_clear_debt"


def test_can_exit_true_when_all_conditions_met():
    config = GameConfig.default_20()
    p = make_player("P01", stars=3, cash=2_000_000, debt=1_000_000, cards=[])
    ok, reason = can_exit(p, config, has_unfulfilled_obligation=False)
    assert ok and reason is None


def test_can_exit_false_with_unfulfilled_obligation():
    config = GameConfig.default_20()
    p = make_player("P01", stars=3, cash=2_000_000, debt=0, cards=[])
    ok, reason = can_exit(p, config, has_unfulfilled_obligation=True)
    assert not ok and reason == "unfulfilled_obligation"


def test_surplus_stars_and_buyback():
    config = GameConfig.default_20()
    p = make_player("P01", stars=5, cards=[])
    assert surplus_stars(p, config) == 2
    assert buyback_amount(p, config) == 2 * config.surplus_star_buyback


def test_settle_exit_order_buyback_then_debt_then_final_assets():
    """§6.2 処理順: 余剰★買取 → 借金完済 → 最終資産確定 → 退場"""
    config = GameConfig.default_20()
    p = make_player("P01", stars=4, cash=500_000, debt=1_200_000, cards=[])
    # buyback = 1 * 1,000,000 = 1,000,000
    # final_assets = 500,000 + 1,000,000 - 1,200,000 = 300,000
    updated = settle_exit(p, config, turn=77)
    assert updated.final_assets == 300_000
    assert updated.cash == 300_000
    assert updated.debt == 0
    assert updated.stars == 0
    assert updated.has_exited is True
    assert updated.is_alive is False
    assert updated.exit_turn == 77


def test_survival_cash_min_flag_when_enabled():
    """§9.3案1: survival_cash_min を設定すると現金ライン未満は不成立になる"""
    config = GameConfig.default_20().model_copy(update={"survival_cash_min": 1_000_000})
    p = make_player("P01", stars=3, cash=500_000, debt=0, cards=[])  # 清算後500,000 < 1,000,000
    ok, reason = can_exit(p, config, has_unfulfilled_obligation=False)
    assert not ok and reason == "cannot_clear_debt"


def test_survival_cash_min_default_allows_zero_final_assets():
    """既定（survival_cash_min=0）では最終資産0円でも退出できる（§9.3の抜け穴、仕様書どおり）"""
    config = GameConfig.default_20()
    p = make_player("P01", stars=3, cash=0, debt=0, cards=[])
    ok, reason = can_exit(p, config, has_unfulfilled_obligation=False)
    assert ok and reason is None
