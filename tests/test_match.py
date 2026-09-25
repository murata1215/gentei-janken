"""対戦モジュールのテスト（§4）"""

import pytest

from engine.matches import (
    accept_match, decline_match, expire_match, has_active_offer,
    offer_match, resolve_match, withdraw_match,
)
from engine.models import Hand
from tests.conftest import make_player


def test_offer_reserves_card():
    p1 = make_player("P01")
    card_id = p1.cards[0].card_id
    updated, offer = offer_match("M1", p1, "P02", Hand.ROCK, card_id, turn=1)
    assert updated.reserved_card_ids == [card_id]
    assert len(updated.cards) == 1  # 予約はマーカーのみ、手札から除去しない
    assert offer.status == "pending"


def test_offer_requires_star():
    p1 = make_player("P01", stars=0)
    with pytest.raises(ValueError):
        offer_match("M1", p1, "P02", Hand.ROCK, p1.cards[0].card_id, turn=1)


def test_accept_requires_pending_status():
    p1 = make_player("P01")
    p2 = make_player("P02")
    _, offer = offer_match("M1", p1, "P02", Hand.ROCK, p1.cards[0].card_id, turn=1)
    accepted, offer = accept_match(offer, p2, Hand.SCISSORS, p2.cards[0].card_id)
    with pytest.raises(ValueError):
        accept_match(offer, p2, Hand.SCISSORS, p2.cards[0].card_id)  # 二重受諾


def test_resolve_consumes_both_cards():
    p1 = make_player("P01")
    p2 = make_player("P02")
    p1, offer = offer_match("M1", p1, "P02", Hand.ROCK, p1.cards[0].card_id, turn=1)
    p2, offer = accept_match(offer, p2, Hand.SCISSORS, p2.cards[0].card_id)
    new_p1, new_p2, result, offer = resolve_match(offer, p1, p2, turn=2)
    assert len(new_p1.cards) == 0
    assert len(new_p2.cards) == 0
    assert new_p1.reserved_card_ids == []
    assert new_p2.reserved_card_ids == []
    assert offer.status == "resolved"


def test_decline_releases_challenger_card():
    p1 = make_player("P01")
    p2 = make_player("P02")
    p1, offer = offer_match("M1", p1, "P02", Hand.ROCK, p1.cards[0].card_id, turn=1)
    assert p1.reserved_card_ids != []
    released_p1, offer = decline_match(offer, p1)
    assert released_p1.reserved_card_ids == []
    assert offer.status == "declined"


def test_withdraw_before_acceptance():
    p1 = make_player("P01")
    p1, offer = offer_match("M1", p1, "P02", Hand.ROCK, p1.cards[0].card_id, turn=1)
    released, offer = withdraw_match(offer, p1)
    assert released.reserved_card_ids == []
    assert offer.status == "withdrawn"


def test_withdraw_fails_after_acceptance():
    p1 = make_player("P01")
    p2 = make_player("P02")
    p1, offer = offer_match("M1", p1, "P02", Hand.ROCK, p1.cards[0].card_id, turn=1)
    p2, offer = accept_match(offer, p2, Hand.SCISSORS, p2.cards[0].card_id)
    with pytest.raises(ValueError):
        withdraw_match(offer, p1)


def test_expire_releases_card_and_returns_to_hand():
    p1 = make_player("P01")
    card_id = p1.cards[0].card_id
    p1, offer = offer_match("M1", p1, "P02", Hand.ROCK, card_id, turn=1)
    released, offer = expire_match(offer, p1)
    assert released.reserved_card_ids == []
    assert any(c.card_id == card_id for c in released.cards)  # 手札に戻る
    assert offer.status == "expired"


def test_has_active_offer_true_while_pending_or_accepted():
    p1 = make_player("P01")
    p2 = make_player("P02")
    p1, offer = offer_match("M1", p1, "P02", Hand.ROCK, p1.cards[0].card_id, turn=1)
    assert has_active_offer("P01", [offer])
    p2, accepted_offer = accept_match(offer, p2, Hand.SCISSORS, p2.cards[0].card_id)
    assert has_active_offer("P01", [accepted_offer])


def test_has_active_offer_false_after_resolution():
    p1 = make_player("P01")
    p2 = make_player("P02")
    p1, offer = offer_match("M1", p1, "P02", Hand.ROCK, p1.cards[0].card_id, turn=1)
    p2, offer = accept_match(offer, p2, Hand.SCISSORS, p2.cards[0].card_id)
    _, _, _, offer = resolve_match(offer, p1, p2, turn=2)
    assert not has_active_offer("P01", [offer])


def test_matches_per_turn_limit_is_one_per_spec_11():
    """§11: 1ターンの対戦上限は1人1回。config値で表現されていることを確認する"""
    from engine.config import GameConfig
    assert GameConfig.default_20().matches_per_turn == 1
