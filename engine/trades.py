"""
即時取引モジュール（§7.1）

カード・★・現金を任意に組み合わせて交換する。決済は原子的（全部成立するか、
何も起きないか）で、相手の信用を必要としない。提案翌ターンの終わりまでに
受諾されなければ失効する（失効処理は engine/game.py 側で TradeProposal.status
を"expired"にするだけでよく、資産の移動は一切発生しないため本モジュールでは
扱わない）。
"""

from engine.models import AssetOffer, PlayerState
from engine.player import add_card, add_stars, pay, receive, remove_card, remove_stars


def _has_offer(player: PlayerState, offer: AssetOffer) -> bool:
    """
    player が offer の資産を実際に差し出せるか判定する（§7.1: 受諾の時点で判定）

    予約中のカード（対戦申込・受諾で封をしたもの）は取引に使えない。
    """
    if player.cash < offer.cash:
        return False
    if player.stars < offer.stars:
        return False
    if any(cid in player.reserved_card_ids for cid in offer.card_ids):
        return False
    held_ids = {c.card_id for c in player.cards}
    return all(cid in held_ids for cid in offer.card_ids)


def can_settle_trade(proposer: PlayerState, target: PlayerState, give: AssetOffer, receive_: AssetOffer) -> bool:
    """
    双方が実際に資産を持っているか判定する（§7.1: 「受諾の時点でどちらかが出す
    資産を持っていなければ不成立とし、脱落はさせない」）
    """
    return _has_offer(proposer, give) and _has_offer(target, receive_)


def settle_trade(
    proposer: PlayerState, target: PlayerState, give: AssetOffer, receive_: AssetOffer,
) -> tuple[PlayerState, PlayerState]:
    """
    取引を原子的に決済する（§7.1）

    事前に can_settle_trade() で True を確認済みであること（本関数はそれ自体を
    検証しない）。give は proposer→target、receive_ は target→proposer への移動。

    Args:
        proposer: 提案者の状態
        target: 相手の状態
        give: proposer が差し出す資産
        receive_: target が差し出す資産（proposer が受け取る）

    Returns:
        (更新されたproposer, 更新されたtarget)
    """
    new_proposer, new_target = proposer, target

    for card_id in give.card_ids:
        new_proposer, card = remove_card(new_proposer, card_id)
        new_target = add_card(new_target, card)
    for card_id in receive_.card_ids:
        new_target, card = remove_card(new_target, card_id)
        new_proposer = add_card(new_proposer, card)

    if give.stars:
        new_proposer = remove_stars(new_proposer, give.stars)
        new_target = add_stars(new_target, give.stars)
    if receive_.stars:
        new_target = remove_stars(new_target, receive_.stars)
        new_proposer = add_stars(new_proposer, receive_.stars)

    if give.cash:
        new_proposer = pay(new_proposer, give.cash)
        new_target = receive(new_target, give.cash)
    if receive_.cash:
        new_target = pay(new_target, receive_.cash)
        new_proposer = receive(new_proposer, receive_.cash)

    return new_proposer, new_target
