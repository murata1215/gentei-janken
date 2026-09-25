"""
乱数管理モジュール

全ゲームの乱数を単一seedから導出し、同一seedで完全再現可能にする。
用途別にサブRNGを生成して独立性を保つ。
"""

import random


class GameRng:
    """
    ゲーム用乱数ジェネレータ

    単一のseedから全ゲーム内乱数を再現可能に生成する。
    用途ごとに独立したRNGインスタンスを返す。

    Args:
        seed: ゲームのマスターシード
    """

    def __init__(self, seed: int) -> None:
        self.seed = seed
        self._master = random.Random(seed)
        # 用途別にサブシードを生成して独立性を確保
        self._action_rng = random.Random(self._master.randint(0, 2**63))
        self._general_rng = random.Random(self._master.randint(0, 2**63))

    def shuffle_action_order(self, player_ids: list[str]) -> list[str]:
        """
        1ターン内のアクション処理順をランダムシャッフルする（§5.1 ステップ3）

        「ランダムな順番で処理する」に対応。毎ターンランダム順。
        同一seedなら同じ順序が再現される。

        Args:
            player_ids: シャッフル対象のプレイヤーIDリスト

        Returns:
            シャッフルされたプレイヤーIDリスト（元リストは変更しない）
        """
        shuffled = list(player_ids)
        self._action_rng.shuffle(shuffled)
        return shuffled
