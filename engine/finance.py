"""
利息計上モジュール（§2.3、§5.1 ステップ7）

強制返済は仕様書になく実装しない（§2.4）。任意返済（repay アクション）は
engine/player.py:repay_debt() と engine/player.py:can_repay_now() が担う。
"""

from engine import player as player_ops
from engine.config import GameConfig
from engine.events import EventLogger
from engine.models import PlayerState


def is_interest_turn(turn: int, config: GameConfig) -> bool:
    """このターンが利息計上ターンか（§2.3: interest_interval_turns ごと）"""
    if config.interest_interval_turns <= 0:
        return False
    return turn % config.interest_interval_turns == 0


def apply_interest_to_all(
    players: dict[str, PlayerState], turn: int, config: GameConfig, logger: EventLogger,
) -> dict[str, PlayerState]:
    """
    利息計上ターンなら、場に残る（is_alive）全員の借金に利息を付ける（§5.1 ステップ7）

    退出済み（has_exited）プレイヤーには計上しない（§2.3「退出した時点で止まる」）。
    is_alive も False になっているため、対象からは自然に外れる。

    Args:
        players: 全プレイヤーの状態辞書
        turn: 現在のターン番号
        config: ゲーム設定
        logger: イベントロガー

    Returns:
        更新されたplayers辞書
    """
    if not is_interest_turn(turn, config):
        return players
    updated = dict(players)
    for pid, p in players.items():
        if not p.is_alive or p.debt <= 0:
            continue
        old_debt = p.debt
        new_p = player_ops.apply_interest(p, config.interest_rate)
        updated[pid] = new_p
        if new_p.debt != old_debt:
            logger.log("INTEREST", turn, "finance", data={
                "player_id": pid,
                "old_debt": old_debt,
                "interest": new_p.debt - old_debt,
                "new_debt": new_p.debt,
            })
    return updated
