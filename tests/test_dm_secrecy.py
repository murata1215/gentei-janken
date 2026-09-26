"""
DM本文・匿名通信の発信者の秘匿テスト
（rules/project.md「DM本文は当事者以外に対しキーごと削除する」担保テスト）

engine/messages.py::visible_messages() の純関数テストと、engine/game.pyを
通した機械的な全走査（他人宛DM本文が一切現れないこと）を検証する。
viewer側の投影テストは tests/test_viewer_secrecy.py に追加する
（同じ秘匿方針を別レイヤーで担保する二重チェック）。
"""

import json

from engine.config import GameConfig
from engine.events import EventLogger
from engine.game import Game
from engine.messages import visible_messages
from engine.models import DmAction, Message
from engine.negotiation import StubAgent
from tests.conftest import make_player


def _dm(mid: str, sender: str, to: str, turn: int, message: str = "秘密の本文") -> Message:
    return Message(message_id=mid, sender=sender, type="dm", to=to, message=message, turn=turn)


# --- visible_messages() 純関数テスト ---

def test_dm_hidden_from_third_party():
    messages = [_dm("MSG_1_1", "P01", "P02", 1, "P02だけへの秘密")]
    projected = visible_messages(messages, {}, "P03")
    assert "message" not in projected[0]
    assert projected[0]["redacted"] is True
    assert projected[0]["sender"] == "P01"
    assert projected[0]["to"] == "P02"


def test_dm_visible_to_sender_and_recipient():
    messages = [_dm("MSG_1_1", "P01", "P02", 1, "秘密")]
    for viewer in ("P01", "P02"):
        projected = visible_messages(messages, {}, viewer)
        assert projected[0]["message"] == "秘密"
        assert "redacted" not in projected[0]


def test_dm_hidden_when_viewer_is_none():
    """for_player_id=Noneは安全側に倒れる（全DM redacted）"""
    messages = [_dm("MSG_1_1", "P01", "P02", 1)]
    projected = visible_messages(messages, {}, None)
    assert "message" not in projected[0]
    assert projected[0]["redacted"] is True


def test_broadcast_visible_to_everyone():
    messages = [Message(message_id="MSG_1_1", sender="P01", type="broadcast", to=None, message="宣言", turn=1)]
    for viewer in ("P01", "P02", None):
        projected = visible_messages(messages, {}, viewer)
        assert projected[0]["message"] == "宣言"


def test_anonymous_sender_never_exposed():
    messages = [Message(message_id="MSG_1_1", sender=None, type="anonymous_broadcast", to=None, message="密告", turn=1)]
    owners = {"MSG_1_1": "P01"}
    for viewer in ("P01", "P02", None):
        projected = visible_messages(messages, owners, viewer)
        assert projected[0]["sender"] is None
        assert projected[0]["message"] == "密告"


def test_anonymous_is_mine_flag_only_for_sender():
    messages = [Message(message_id="MSG_1_1", sender=None, type="anonymous_broadcast", to=None, message="密告", turn=1)]
    owners = {"MSG_1_1": "P01"}
    assert visible_messages(messages, owners, "P01")[0]["is_mine"] is True
    assert "is_mine" not in visible_messages(messages, owners, "P02")[0]
    assert "is_mine" not in visible_messages(messages, owners, None)[0]


def test_multiple_dms_each_filtered_independently():
    messages = [
        _dm("MSG_1_1", "P01", "P02", 1, "P01からP02へ"),
        _dm("MSG_1_2", "P03", "P01", 1, "P03からP01へ"),
    ]
    projected = visible_messages(messages, {}, "P01")
    # 自分が当事者の1件目は見える、当事者ではない2件目...ではなくP01は宛先なので見える
    assert projected[0]["message"] == "P01からP02へ"  # 送信者だから見える
    assert projected[1]["message"] == "P03からP01へ"  # 宛先だから見える

    projected_p02 = visible_messages(messages, {}, "P02")
    assert projected_p02[0]["message"] == "P01からP02へ"  # 宛先だから見える
    assert "message" not in projected_p02[1]  # 無関係のDMは見えない


# --- engineを通した全走査（可視状態に本文が漏れないこと） ---

def _make_game(num_players: int = 3, total_turns: int = 10) -> Game:
    config = GameConfig.dev_small(num_players=num_players, total_turns=total_turns)
    agents = {f"P{i:02d}": StubAgent() for i in range(1, num_players + 1)}
    logger = EventLogger(fixed_timestamp="t")
    game = Game(config, agents, seed=1, logger=logger)
    game.players = {}
    for i in range(1, num_players + 1):
        pid = f"P{i:02d}"
        game.players[pid] = make_player(pid)
    return game


def test_no_leak_by_string_scan_across_all_players():
    """他人宛DMの本文マーカーが、当事者以外の可視状態には一切現れないことを機械的に検証する"""
    game = _make_game(num_players=3)
    game._handle_dm(1, game.players["P01"], DmAction(player_id="P01", to="P02", message="SECRET_MARKER_7f3a"))

    for viewer_pid in ("P01", "P02", "P03"):
        state = game._build_visible_state(viewer_pid, 2)
        dumped = json.dumps(state["messages"], default=str, ensure_ascii=False)
        if viewer_pid in ("P01", "P02"):
            assert "SECRET_MARKER_7f3a" in dumped, f"{viewer_pid}は当事者なので見えるべき"
        else:
            assert "SECRET_MARKER_7f3a" not in dumped, f"{viewer_pid}は当事者ではないので見えてはいけない"


def test_no_leak_in_prompt_output():
    """プロンプト文字列（llm/prompt_builder経由）にも他人宛DM本文が現れないことを確認する"""
    from llm.prompt_builder import build_messages_section

    game = _make_game(num_players=3)
    game._handle_dm(1, game.players["P01"], DmAction(player_id="P01", to="P02", message="SECRET_MARKER_9k2m"))

    state_p03 = game._build_visible_state("P03", 2)
    prompt_p03 = build_messages_section(state_p03)
    assert "SECRET_MARKER_9k2m" not in prompt_p03

    state_p02 = game._build_visible_state("P02", 2)
    prompt_p02 = build_messages_section(state_p02)
    assert "SECRET_MARKER_9k2m" in prompt_p02
