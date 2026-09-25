"""
抽象プレイヤーインターフェース・スタブモジュール

各AIエージェント（LLM, Bot, スタブ）が実装するプレイヤーインターフェースを
定義する。本ステップの「歩く骨格」では StubAgent（常にpass、条件が揃ったら
即退出）のみで dry_run が完走することを確認する。
"""

from abc import ABC, abstractmethod

from engine.config import GameConfig
from engine.exit_rules import can_exit
from engine.models import Action, ExitAction, PassAction, PlayerState


class PlayerAgent(ABC):
    """
    プレイヤーエージェントの抽象基底クラス

    各AIエージェント（LLM, Bot, スタブ）はこのクラスを継承し、
    借入額選択・1ターンのアクション選択の2メソッドを実装する。
    """

    @abstractmethod
    def choose_loan(self, config: GameConfig) -> int:
        """
        ゲーム開始前の借入額を選択する（§2.1/§2.2）

        Args:
            config: ゲーム設定（loan_min〜loan_maxの範囲内で選択）

        Returns:
            借入額（整数）
        """
        ...

    @abstractmethod
    def act(
        self,
        player_state: PlayerState,
        turn: int,
        visible_state: dict,
    ) -> Action:
        """
        1ターンに1アクションを選択する（§5.1 ステップ2、§5.2）

        Args:
            player_state: 自分のプレイヤー状態
            turn: 現在のターン番号（1〜config.total_turns）
            visible_state: 公開情報 + 自分向け個別通知（§5.3）の辞書

        Returns:
            選択したAction
        """
        ...

    def reflect(self, player_state: PlayerState, turn: int, visible_state: dict) -> None:
        """
        引き継ぎメモリ（Handover Memory）用のフック。デフォルトは何もしない。

        LLMAgentのみオーバーライドしてmemoryを更新する（dangou-cardと同じ設計）。
        """
        return None


class StubAgent(PlayerAgent):
    """
    固定行動スタブエージェント（ドライラン用）

    - 借入: 最低額（config.loan_min）
    - 行動: 退出条件（§6.1）が揃っていれば退出、それ以外は常にpass
      （対戦・取引・契約などは一切行わない。歩く骨格の完走確認専用）
    """

    def choose_loan(self, config: GameConfig) -> int:
        """最低借入額を選択"""
        return config.loan_min

    def act(self, player_state: PlayerState, turn: int, visible_state: dict) -> Action:
        """退出できるなら退出、できなければpass"""
        config: GameConfig = visible_state["config"]
        ok, _ = can_exit(player_state, config, has_unfulfilled_obligation=False)
        if ok:
            return ExitAction(player_id=player_state.player_id)
        return PassAction(player_id=player_state.player_id)
