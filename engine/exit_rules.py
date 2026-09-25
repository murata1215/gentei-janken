"""
退出モジュール（§6.1/§6.2）

退出は生還するための唯一の手段。条件判定と清算処理を提供する。
"""

from typing import Literal

from engine.config import GameConfig
from engine.models import PlayerState
from engine.player import mark_exited

ExitDenyReason = Literal[
    "cards_remaining", "insufficient_stars", "cannot_clear_debt", "unfulfilled_obligation",
]


def surplus_stars(player: PlayerState, config: GameConfig) -> int:
    """生還ライン（survival_stars_min）を超える★の個数（§6.2 ステップ1）"""
    return max(0, player.stars - config.survival_stars_min)


def buyback_amount(player: PlayerState, config: GameConfig) -> int:
    """余剰★の買取総額（§6.2 ステップ1: 1個 surplus_star_buyback 円）"""
    return surplus_stars(player, config) * config.surplus_star_buyback


def can_exit(
    player: PlayerState, config: GameConfig, *, has_unfulfilled_obligation: bool,
) -> tuple[bool, ExitDenyReason | None]:
    """
    退出条件（§6.1）を判定する

    4条件すべてを満たすときだけ成立する。満たさない場合は不成立で、脱落はしない
    （呼び出し側は False を返してアクションを無視・却下するだけでよい）。

    Args:
        player: プレイヤー状態
        config: ゲーム設定（survival_stars_min / survival_cash_min を参照）
        has_unfulfilled_obligation: 自分が義務者である未履行の正式契約があるか（§6.1条件4）

    Returns:
        (成立するか, 不成立理由。成立時はNone)
    """
    if len(player.cards) > 0 or player.reserved_card_ids:
        return False, "cards_remaining"
    if player.stars < config.survival_stars_min:
        return False, "insufficient_stars"
    projected_cash = player.cash + buyback_amount(player, config) - player.debt
    if projected_cash < 0:
        return False, "cannot_clear_debt"
    if projected_cash < config.survival_cash_min:
        # §9.3案1（未決事項）。config.survival_cash_min=0（既定）なら常に通過する。
        return False, "cannot_clear_debt"
    if has_unfulfilled_obligation:
        return False, "unfulfilled_obligation"
    return True, None


def settle_exit(player: PlayerState, config: GameConfig, turn: int) -> PlayerState:
    """
    退出時の清算（§6.2、処理順）

    1. 余剰★の買い取り（survival_stars_min を超える分を1個 surplus_star_buyback 円で買取）
    2. 借金の完済（現金から借金残高を全額返済）
    3. 最終資産の確定（残った現金を記録）
    4. 退場（手元の★は場から取り除く＝0にする。申込・提案の取り消しは呼び出し側の責務）

    事前に can_exit() で True を確認済みであること（本関数はそれ自体を検証しない）。
    """
    buyback = buyback_amount(player, config)
    final_assets = player.cash + buyback - player.debt
    updated = player.model_copy(update={"cash": final_assets, "debt": 0, "stars": 0})
    return mark_exited(updated, turn, final_assets)
