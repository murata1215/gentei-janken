"""
llm/llm_agent.py のmemory配線テスト（サイクル1.8）

LLM応答のmemoryフィールドが次ターンのプロンプト冒頭に再注入されること、
Action本体には一切乗らないことを機械的に検証する。reasoning/emotionと同じ
抽出経路（extract_json）を使うが扱いは正反対（memoryは意図的に本人へ差し戻す）
なので、混同していないことも確認する。
"""

from engine.config import GameConfig
from engine.models import PassAction
from llm.llm_agent import LLMAgent
from llm.llm_logger import LLMLogger
from llm.models import ModelInfo
from tests.conftest import make_player


class _FakeAdapter:
    """LLM API呼び出しを模擬する。complete()は事前に積んだ応答を順番に返す"""

    def __init__(self, responses: list[str]) -> None:
        self._responses = list(responses)
        self.sent_user_messages: list[str] = []

    def complete(self, system, messages, max_tokens=1000, temperature=0.7, request_options=None):
        self.sent_user_messages.append(messages[0]["content"])
        text = self._responses.pop(0)
        usage = {"input_tokens": 10, "output_tokens": 10, "total_tokens": 20}
        return text, usage


def _make_model_info() -> ModelInfo:
    return ModelInfo(
        model_id="test-model", provider="Anthropic", name="Test",
        adapter_type="anthropic", input_price=0.0, output_price=0.0,
        env_key="TEST_API_KEY", base_url=None,
    )


def _make_agent(tmp_path, responses: list[str]) -> tuple[LLMAgent, _FakeAdapter]:
    adapter = _FakeAdapter(responses)
    llm_logger = LLMLogger(tmp_path, game_id="test")
    agent = LLMAgent("P01", _make_model_info(), adapter, llm_logger)
    return agent, adapter


def _visible_state() -> dict:
    return {
        "config": GameConfig.dev_small(num_players=2, total_turns=20),
        "board": {"ROCK": 4, "SCISSORS": 4, "PAPER": 4},
        "offers_incoming": [], "offers_outgoing": [],
        "alive_player_ids": ["P02"], "opponents": [],
        "projected_rank": 1, "projected_rank_total": 2,
    }


def test_memory_is_carried_into_next_prompt(tmp_path):
    player = make_player("P01")
    agent, adapter = _make_agent(tmp_path, [
        '{"action_type": "pass", "memory": "P02は約束を破った"}',
        '{"action_type": "pass"}',
    ])
    agent.act(player, 1, _visible_state())
    assert agent._memory == "P02は約束を破った"
    assert "## 前ターンまでのあなたのメモ" not in adapter.sent_user_messages[0]

    agent.act(player, 2, _visible_state())
    assert "P02は約束を破った" in adapter.sent_user_messages[1]
    assert "## 前ターンまでのあなたのメモ" in adapter.sent_user_messages[1]


def test_memory_persists_when_not_repeated(tmp_path):
    """memoryを省略した応答が来ても、前回のメモを保持し続ける（毎ターン再送不要）"""
    player = make_player("P01")
    agent, _ = _make_agent(tmp_path, [
        '{"action_type": "pass", "memory": "覚えておくこと"}',
        '{"action_type": "pass"}',
    ])
    agent.act(player, 1, _visible_state())
    agent.act(player, 2, _visible_state())
    assert agent._memory == "覚えておくこと"


def test_memory_never_appears_in_action_object(tmp_path):
    """memoryはAction本体には乗らない（LLMAgentの内部状態にのみ保持する設計）"""
    player = make_player("P01")
    agent, _ = _make_agent(tmp_path, ['{"action_type": "pass", "memory": "秘密のメモ"}'])
    action = agent.act(player, 1, _visible_state())
    assert isinstance(action, PassAction)
    assert "memory" not in action.model_dump()
