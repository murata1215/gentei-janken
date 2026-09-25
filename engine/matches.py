"""
対戦モジュール（§4）

申込→受諾/拒否/取り下げ→開示 の1対1ジャンケンを扱う。
PlayerState/MatchOffer を直接更新する関数群で構成し、実際の呼び出しは
engine/game.py のターンループから行う。
"""

from engine.judge import judge
from engine.models import MatchOffer, MatchResult, PlayerState
from engine.player import reserve_card, release_reserved_card, use_card


def has_active_offer(player_id: str, offers: list[MatchOffer]) -> bool:
    """
    このプレイヤーが申込者として持つ「未決着」の申込があるか（§4.3: 同時に1件まで）

    pending/accepted は未決着。resolved/expired/withdrawn/declined は対象外。
    """
    return any(
        o.challenger_id == player_id and o.status in ("pending", "accepted")
        for o in offers
    )


def offer_match(
    offer_id: str, challenger: PlayerState, opponent_id: str,
    hand, card_id: str, turn: int,
) -> tuple[PlayerState, MatchOffer]:
    """
    対戦を申込む（§4.1 ステップ1）

    challenger の手を封じて提出し、指定カードを予約する。

    Raises:
        ValueError: 手札にカードがない、既に予約中、★が0の場合
    """
    if challenger.stars < 1:
        raise ValueError(f"{challenger.player_id} has no stars, cannot offer a match")
    updated = reserve_card(challenger, card_id)
    offer = MatchOffer(
        offer_id=offer_id,
        challenger_id=challenger.player_id,
        opponent_id=opponent_id,
        turn_offered=turn,
        challenger_hand=hand,
        challenger_card_id=card_id,
        status="pending",
    )
    return updated, offer


def accept_match(
    offer: MatchOffer, opponent: PlayerState, hand, card_id: str,
) -> tuple[PlayerState, MatchOffer]:
    """
    対戦を受諾する（§4.1 ステップ2）

    opponent の手を封じて提出し、指定カードを予約する。

    Raises:
        ValueError: offer が pending でない、opponent_id が一致しない、★が0の場合
    """
    if offer.status != "pending":
        raise ValueError(f"offer {offer.offer_id} is not pending (status={offer.status})")
    if offer.opponent_id != opponent.player_id:
        raise ValueError(f"offer {offer.offer_id} is not addressed to {opponent.player_id}")
    if opponent.stars < 1:
        raise ValueError(f"{opponent.player_id} has no stars, cannot accept a match")
    updated = reserve_card(opponent, card_id)
    new_offer = offer.model_copy(update={
        "status": "accepted",
        "opponent_hand": hand,
        "opponent_card_id": card_id,
    })
    return updated, new_offer


def decline_match(offer: MatchOffer, challenger: PlayerState) -> tuple[PlayerState, MatchOffer]:
    """対戦を拒否する。challenger の予約カードを解放する"""
    updated = release_reserved_card(challenger, offer.challenger_card_id)
    new_offer = offer.model_copy(update={"status": "declined"})
    return updated, new_offer


def withdraw_match(offer: MatchOffer, challenger: PlayerState) -> tuple[PlayerState, MatchOffer]:
    """申込者が受諾前に取り下げる（§4.3）。challenger の予約カードを解放する"""
    if offer.status != "pending":
        raise ValueError(f"offer {offer.offer_id} cannot be withdrawn (status={offer.status})")
    updated = release_reserved_card(challenger, offer.challenger_card_id)
    new_offer = offer.model_copy(update={"status": "withdrawn"})
    return updated, new_offer


def expire_match(offer: MatchOffer, challenger: PlayerState) -> tuple[PlayerState, MatchOffer]:
    """
    申込を失効させる（§4.3: 受諾されずに次のターンが終わると失効）

    challenger の予約カードを手札に戻す。
    """
    updated = release_reserved_card(challenger, offer.challenger_card_id)
    new_offer = offer.model_copy(update={"status": "expired"})
    return updated, new_offer


def resolve_match(
    offer: MatchOffer, challenger: PlayerState, opponent: PlayerState, turn: int,
) -> tuple[PlayerState, PlayerState, MatchResult, MatchOffer]:
    """
    対戦を開示する（§4.1 ステップ3、§4.2 勝敗表）

    両者の予約カードを消滅させ（use_card）、勝者に★を1個移動する。
    あいこの場合は★は移動しない。

    Raises:
        ValueError: offer が accepted でない場合
    """
    if offer.status != "accepted":
        raise ValueError(f"offer {offer.offer_id} is not accepted (status={offer.status})")
    assert offer.opponent_hand is not None and offer.opponent_card_id is not None

    outcome = judge(offer.challenger_hand, offer.opponent_hand)

    new_challenger = use_card(challenger, offer.challenger_card_id)
    new_opponent = use_card(opponent, offer.opponent_card_id)

    if outcome == "challenger_win":
        new_opponent = new_opponent.model_copy(update={"stars": new_opponent.stars - 1})
        new_challenger = new_challenger.model_copy(update={"stars": new_challenger.stars + 1})
    elif outcome == "opponent_win":
        new_challenger = new_challenger.model_copy(update={"stars": new_challenger.stars - 1})
        new_opponent = new_opponent.model_copy(update={"stars": new_opponent.stars + 1})
    # "draw": ★は移動しない（§4.2）

    result = MatchResult(
        offer_id=offer.offer_id,
        challenger_id=offer.challenger_id,
        opponent_id=offer.opponent_id,
        challenger_hand=offer.challenger_hand,
        opponent_hand=offer.opponent_hand,
        outcome=outcome,
        turn=turn,
    )
    new_offer = offer.model_copy(update={"status": "resolved", "turn_resolved": turn})
    return new_challenger, new_opponent, result, new_offer


def make_offer_id(turn: int, challenger_id: str, counter: int) -> str:
    """申込IDを決定的に生成する（ターン・当事者・連番から合成）"""
    return f"M_{turn}_{challenger_id}_{counter}"
