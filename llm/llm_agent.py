"""
LLMAgent — PlayerAgentの実装

LLM APIを使ってゲームに参加するエージェント。
プロンプト構築 → APIコール → レスポンス解析 → Action変換を行う。
コスト上限ガード・リトライ・ログ記録を管理する。

dangou-cardのllm_agent.pyの足場（リトライ・予算予約・ログ連携）を移植し、
呼び出すプロンプト関数を限定ジャンケンの3関数（build_system_prompt /
build_personal_notice / build_board_section / build_action_prompt）に絞った版。
"""

import logging
from typing import Any

from engine.config import GameConfig
from engine.models import Action, PassAction, PlayerState
from engine.negotiation import PlayerAgent
from llm.adapters import AdapterError
from llm.constants import DEFAULT_MAX_TOKENS, DEFAULT_TEMPERATURE, MAX_RETRIES
from llm.costing import usage_cost
from llm.game_cost_budget import BudgetBlockedError, GameCostBudget
from llm.llm_logger import LLMLogger
from llm.models import ModelInfo
from llm.prompt_builder import (
    build_action_prompt, build_board_section, build_personal_notice, build_system_prompt,
)
from llm.response_parser import ParseError, make_correction_message, parse_action

logger = logging.getLogger(__name__)


class LLMAgent(PlayerAgent):
    """LLM APIを使用するプレイヤーエージェント"""

    def __init__(
        self,
        player_id: str,
        model_info: ModelInfo,
        adapter: Any,
        llm_logger: LLMLogger,
        config: GameConfig | None = None,
        game_cost_budget: GameCostBudget | None = None,
    ) -> None:
        self.player_id = player_id
        self.model_info = model_info
        self.adapter = adapter
        bind_seat = getattr(adapter, "bind_seat", None)
        if callable(bind_seat):
            bind_seat(player_id)
        self.llm_logger = llm_logger
        self._config = config
        self._game_cost_budget = game_cost_budget
        self._system_prompt = build_system_prompt(player_id)
        self.total_calls = 0
        self.valid_json_count = 0
        self.action_correction_count = 0

    def choose_loan(self, config: GameConfig) -> int:
        """
        借入額を選択する（§2.1/§2.2）

        LLM呼び出しに失敗した場合は安全側（loan_min）にフォールバックする。
        """
        self._config = config
        prompt = (
            f"借入額を{config.loan_min}〜{config.loan_max}円の範囲で選んでください。"
            '{"amount": <整数>} のJSONのみで応答してください。'
        )
        text, usage = self._call(self._system_prompt, prompt, max_tokens=200)
        if text is None:
            return config.loan_min
        try:
            import json
            data = json.loads(text.strip().strip("`"))
            amount = int(data["amount"])
        except Exception:
            return config.loan_min
        return max(config.loan_min, min(config.loan_max, amount))

    def act(self, player_state: PlayerState, turn: int, visible_state: dict) -> Action:
        """1ターンのアクションを選択する（§5.1 ステップ2）"""
        config: GameConfig = visible_state.get("config", self._config)
        prompt = "\n\n".join([
            build_personal_notice(player_state, turn, visible_state),
            build_board_section(visible_state.get("board", {})),
            build_action_prompt(),
        ])

        for attempt in range(MAX_RETRIES + 1):
            text, usage = self._call(self._system_prompt, prompt, max_tokens=DEFAULT_MAX_TOKENS)
            self.total_calls += 1
            if text is None:
                # API呼び出し自体が失敗（予算ブロック・アダプタエラー）→安全側にpass
                return PassAction(player_id=player_state.player_id)
            try:
                action = parse_action(text, player_state.player_id)
                self.valid_json_count += 1
                return action
            except ParseError as e:
                self.action_correction_count += 1
                logger.warning("parse error for %s at turn %d: %s", player_state.player_id, turn, e)
                prompt = make_correction_message(e)
                continue

        # リトライを使い切った場合の安全側フォールバック
        return PassAction(player_id=player_state.player_id)

    def _call(self, system: str, user_message: str, max_tokens: int) -> tuple[str | None, dict[str, Any] | None]:
        """
        APIを1回呼び出す。予算ブロック・アダプタエラー時は (None, None) を返す。

        呼び出しはllm_loggerへ記録する。game_cost_budgetが注入されている場合は
        呼び出し前に予約し、成功時に実コストで精算する
        （rules/project.md「LLMコストは常にusage_cost()経由」）。
        """
        reservation = None
        if self._game_cost_budget is not None:
            try:
                reservation = self._game_cost_budget.reserve(
                    self.player_id, amount_usd=0.05, round_num=0, phase="act",
                )
            except BudgetBlockedError:
                return None, None

        import time
        started = time.monotonic()
        try:
            text, usage = self.adapter.complete(
                system=system,
                messages=[{"role": "user", "content": user_message}],
                max_tokens=max_tokens,
                temperature=DEFAULT_TEMPERATURE,
            )
        except AdapterError as e:
            logger.warning("adapter error for %s: %s", self.player_id, e)
            if reservation is not None and self._game_cost_budget is not None:
                self._game_cost_budget.release(reservation)
            return None, None
        elapsed_ms = (time.monotonic() - started) * 1000

        cost = usage_cost(self.model_info, usage)
        if reservation is not None and self._game_cost_budget is not None:
            self._game_cost_budget.settle(reservation, cost)

        self.llm_logger.log_call(
            player_id=self.player_id, model_id=self.model_info.model_id,
            phase="act", round_num=0, turn=0,
            system_prompt=system, user_prompt=user_message, response_text=text,
            usage=usage, cost=cost, elapsed_ms=elapsed_ms,
        )
        return text, usage
