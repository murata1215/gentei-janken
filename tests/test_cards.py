"""
カード・掲示板のテスト（§3.1/§8.1）

rules/project.md「残数掲示板は独立カウンタを持たない」の担保テスト。
"""

from engine.cards import board_counts, create_deck, total_cards_in_play
from engine.models import Hand
from tests.conftest import make_player


def test_create_deck_has_12_cards_4_each():
    deck = create_deck("P01")
    assert len(deck) == 12
    counts = {h: 0 for h in Hand}
    for c in deck:
        counts[c.hand] += 1
    assert counts == {Hand.ROCK: 4, Hand.SCISSORS: 4, Hand.PAPER: 4}


def test_card_ids_unique_within_player():
    deck = create_deck("P01")
    ids = [c.card_id for c in deck]
    assert len(ids) == len(set(ids))


def test_board_counts_sums_hands_of_alive_players_only():
    p1 = make_player("P01", cards=create_deck("P01"))
    p2 = make_player("P02", cards=create_deck("P02"), is_alive=False)  # 脱落済みは除外
    counts = board_counts([p1, p2])
    assert counts == {"ROCK": 4, "SCISSORS": 4, "PAPER": 4}
    assert total_cards_in_play([p1, p2]) == 12


def test_board_counts_includes_reserved_cards():
    """予約中のカードも掲示板の残数に含まれる（§8.1: 予約中を含む）"""
    deck = create_deck("P01")
    p1 = make_player("P01", cards=deck, reserved_card_ids=[deck[0].card_id])
    counts = board_counts([p1])
    assert sum(counts.values()) == 12  # 予約中でも減らない


def test_board_counts_decreases_after_match_uses_card():
    from engine.player import use_card
    deck = create_deck("P01")
    p1 = make_player("P01", cards=deck)
    used_id = deck[0].card_id
    p1_after = use_card(p1, used_id)
    counts_before = board_counts([p1])
    counts_after = board_counts([p1_after])
    assert sum(counts_before.values()) == 12
    assert sum(counts_after.values()) == 11


def test_trade_moves_cards_without_changing_total():
    """取引ではカードが移るだけで総数は変わらない（§8.1）"""
    from engine.models import AssetOffer
    from engine.trades import settle_trade

    deck1 = create_deck("P01")
    deck2 = create_deck("P02")
    p1 = make_player("P01", cards=deck1)
    p2 = make_player("P02", cards=deck2)

    give = AssetOffer(card_ids=[deck1[0].card_id])
    receive = AssetOffer(cash=100_000)
    new_p1, new_p2 = settle_trade(p1, p2, give, receive)

    total_before = total_cards_in_play([p1, p2])
    total_after = total_cards_in_play([new_p1, new_p2])
    assert total_before == total_after == 24
    assert len(new_p1.cards) == 11
    assert len(new_p2.cards) == 13
