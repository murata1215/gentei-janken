"""
★（星）のゼロサム性のテスト（§3.2）

rules/project.md「★はゼロサム資産である」の担保テスト。
"""

from engine.config import GameConfig
from engine.elimination import forced_liquidation
from engine.matches import accept_match, offer_match, resolve_match
from engine.models import Hand
from tests.conftest import make_player


def test_total_stars_fixed_at_setup():
    config = GameConfig.default_20()
    assert config.num_players * config.initial_stars == 60


def test_match_conserves_star_sum_on_win():
    p1 = make_player("P01", stars=3)
    p2 = make_player("P02", stars=3)
    p1, offer = offer_match("M1", p1, "P02", Hand.ROCK, p1.cards[0].card_id, turn=1)
    p2, offer = accept_match(offer, p2, Hand.SCISSORS, p2.cards[0].card_id)
    new_p1, new_p2, result, offer = resolve_match(offer, p1, p2, turn=2)
    assert result.outcome == "challenger_win"
    assert new_p1.stars + new_p2.stars == 6  # 総和不変
    assert new_p1.stars == 4 and new_p2.stars == 2


def test_match_conserves_star_sum_on_draw():
    p1 = make_player("P01", stars=3)
    p2 = make_player("P02", stars=3)
    p1, offer = offer_match("M1", p1, "P02", Hand.ROCK, p1.cards[0].card_id, turn=1)
    p2, offer = accept_match(offer, p2, Hand.ROCK, p2.cards[0].card_id)
    new_p1, new_p2, result, offer = resolve_match(offer, p1, p2, turn=2)
    assert result.outcome == "draw"
    assert new_p1.stars == 3 and new_p2.stars == 3  # あいこでは移動しない


def test_forced_exit_removes_stars_from_play():
    """
    ★0で強制退場する時点で既に0個なので没収による純減はない。
    時間切れ脱落で★が残っている場合は没収される（システムが没収、他者へ分配しない）。
    """
    p = make_player("P01", stars=2, cash=100, debt=0)  # 時間切れ想定で★が残っている状態
    updated, contracts, record = forced_liquidation(p, "TIMEOUT", turn=120, contracts=[])
    assert updated.stars == 0
    assert record["stars_confiscated"] == 2


def test_exit_removes_floor_stars_from_play():
    from engine.exit_rules import settle_exit
    config = GameConfig.default_20()
    p = make_player("P01", stars=3, cash=1_000_000, debt=0, cards=[])
    updated = settle_exit(p, config, turn=50)
    assert updated.stars == 0  # 生還時も手元の★は場から取り除かれる（§6.2ステップ4）


def test_trade_conserves_star_sum():
    """
    即時取引（サイクル2.0）で★が動いても総和は不変（rules/project.md「★はゼロサム資産」）。

    viewer/log_parser.py::_fold_events もTRADE_ACCEPTEDのstars_movedを反映して
    derivation.stars_zero_sum_okを維持する（tests/test_viewer_fold.pyで別途検証）。
    """
    from engine.models import AssetOffer
    from engine.trades import settle_trade

    p1 = make_player("P01", stars=3)
    p2 = make_player("P02", stars=3)
    give = AssetOffer(stars=1)
    receive = AssetOffer(cash=100_000)
    new_p1, new_p2 = settle_trade(p1, p2, give, receive)
    assert new_p1.stars + new_p2.stars == 6
    assert new_p1.stars == 2 and new_p2.stars == 4
