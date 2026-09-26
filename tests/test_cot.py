"""
CoT reasoning秘匿のテスト（rules/project.md「CoT reasoningフィールドは秘匿情報」）

dangou-cardのtests/test_cot.py::TestCoTNoLeak相当。LLM応答のreasoning/emotionが
- engine.models.Action の各サブクラスに一切乗らないこと
- engine/game.py::_build_visible_state()（他プレイヤー向けプロンプトの元）に
  現れないこと
- llm/response_parser.py::extract_reasoning_and_emotion() 経由でのみ取り出され、
  そこから先はllm/llm_agent.py -> llm/llm_logger.py（神視点専用ログ）にしか
  渡らないこと
を機械的に検証する。
"""

import typing

from engine.config import GameConfig
from engine.events import EventLogger
from engine.game import Game
from engine.models import Action
from engine.negotiation import StubAgent
from llm.response_parser import parse_action


def _action_field_names() -> set[str]:
    """Action判別union（21種）の全フィールド名を集める"""
    union_type = typing.get_args(Action)[0]  # Annotated[Union[...], Field(...)] -> Union[...]
    names: set[str] = set()
    for cls in typing.get_args(union_type):
        names |= set(cls.model_fields.keys())
    return names


def test_action_models_never_declare_a_reasoning_or_emotion_field():
    """
    型レベルの保証: 21種のAction ProfileSubclassのどれも"reasoning"/"emotion"を
    フィールドとして持たない。これがCoT秘匿の構造的な土台になっている
    （response_parser側でどう頑張って抜き出しても、Actionインスタンスには乗せられない）。
    """
    fields = _action_field_names()
    assert "reasoning" not in fields
    assert "_reasoning" not in fields
    assert "emotion" not in fields


def _contains_key(obj: object, banned: set[str]) -> bool:
    if isinstance(obj, dict):
        if any(k in banned for k in obj.keys()):
            return True
        return any(_contains_key(v, banned) for v in obj.values())
    if isinstance(obj, (list, tuple, set)):
        return any(_contains_key(v, banned) for v in obj)
    return False


BANNED_KEYS = {"reasoning", "_reasoning", "emotion"}


def test_parse_action_output_has_no_reasoning_leak():
    text = (
        '{"action_type": "match_offer", "opponent_id": "P02", "hand": "ROCK", '
        '"card_id": "P01_ROCK_1", "reasoning": "本音はブラフ", "emotion": "奸"}'
    )
    action = parse_action(text, "P01")
    dumped = action.model_dump()
    assert not _contains_key(dumped, BANNED_KEYS)
    assert "本音はブラフ" not in str(dumped)


def test_visible_state_never_contains_reasoning_keys():
    """
    engine/game.py::_build_visible_state() が返す辞書（他プレイヤーには渡らない
    本人向け個別通知の元データだが、将来DM/契約実装時に他者へ渡す可視状態の
    土台にもなる）にreasoning/emotionが一切無いことを、実際にゲームを走らせて
    確認する（StubAgentはreasoningを生成しないが、visible_state構築ロジック
    自体がそうしたキーを混入させていないことを保証する回帰テスト）。
    """
    config = GameConfig.dev_small(num_players=3, total_turns=5)
    agents = {f"P{i:02d}": StubAgent() for i in range(1, 4)}
    logger = EventLogger(fixed_timestamp="t")
    game = Game(config, agents, seed=1, logger=logger)
    game.setup()
    for turn in range(1, 4):
        for pid in game._alive_player_ids():
            visible_state = game._build_visible_state(pid, turn)
            assert not _contains_key(visible_state, BANNED_KEYS)


def test_event_log_never_contains_reasoning_keys():
    """イベントログ（観戦者ではなく神視点でも今回はreasoningを載せない設計）にも現れない"""
    config = GameConfig.dev_small(num_players=4, total_turns=10)
    agents = {f"P{i:02d}": StubAgent() for i in range(1, 5)}
    logger = EventLogger(fixed_timestamp="t")
    game = Game(config, agents, seed=1, logger=logger)
    game.run()
    for event in game.logger.events:
        assert not _contains_key(event.model_dump(), BANNED_KEYS)
