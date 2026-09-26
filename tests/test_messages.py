"""
engine/game.py の通信ハンドラのテスト（サイクル1.9: DM・全体発言・匿名通信の実処理化）

§5.2（通信）・§7.5（匿名通信の料金・上限）の実装を検証する。
秘匿境界そのものは tests/test_dm_secrecy.py が担当し、ここでは配送・拒否理由・
料金徴収・待機の起床条件・メッセージの保持期間を検証する。
"""

from engine.config import GameConfig
from engine.events import EventLogger
from engine.game import Game
from engine.models import AnonymousBroadcastAction, BroadcastAction, DmAction, WaitAction
from engine.negotiation import StubAgent
from tests.conftest import make_player


def make_game(num_players: int = 3, total_turns: int = 20) -> Game:
    config = GameConfig.dev_small(num_players=num_players, total_turns=total_turns)
    agents = {f"P{i:02d}": StubAgent() for i in range(1, num_players + 1)}
    logger = EventLogger(fixed_timestamp="t")
    game = Game(config, agents, seed=1, logger=logger)
    game.players = {}
    return game


# --- DM（§5.2） ---

def test_dm_delivered_and_logged():
    game = make_game()
    game.players["P01"] = make_player("P01")
    game.players["P02"] = make_player("P02")
    game._handle_dm(1, game.players["P01"], DmAction(player_id="P01", to="P02", message="よろしく"))
    assert len(game.messages) == 1
    assert game.messages[0].sender == "P01"
    assert game.messages[0].to == "P02"
    events = [e for e in game.logger.events if e.event_type == "DM_SENT"]
    assert len(events) == 1


def test_dm_rejects_self_target():
    game = make_game()
    game.players["P01"] = make_player("P01")
    game._handle_dm(1, game.players["P01"], DmAction(player_id="P01", to="P01", message="自分へ"))
    assert len(game.messages) == 0
    events = [e for e in game.logger.events if e.event_type == "DM_REJECTED"]
    assert events[0].data["reason"] == "invalid_target"


def test_dm_rejects_unknown_target():
    game = make_game()
    game.players["P01"] = make_player("P01")
    game._handle_dm(1, game.players["P01"], DmAction(player_id="P01", to="P99", message="存在しない相手"))
    assert len(game.messages) == 0


def test_dm_rejects_dead_target():
    game = make_game()
    game.players["P01"] = make_player("P01")
    game.players["P02"] = make_player("P02", is_alive=False)
    game._handle_dm(1, game.players["P01"], DmAction(player_id="P01", to="P02", message="退場済みへ"))
    assert len(game.messages) == 0


def test_dm_rejects_empty_message():
    game = make_game()
    game.players["P01"] = make_player("P01")
    game.players["P02"] = make_player("P02")
    game._handle_dm(1, game.players["P01"], DmAction(player_id="P01", to="P02", message="   "))
    assert len(game.messages) == 0
    events = [e for e in game.logger.events if e.event_type == "DM_REJECTED"]
    assert events[0].data["reason"] == "empty_message"


def test_dm_body_truncated_to_max_length():
    game = make_game()
    game.players["P01"] = make_player("P01")
    game.players["P02"] = make_player("P02")
    long_text = "あ" * 500
    game._handle_dm(1, game.players["P01"], DmAction(player_id="P01", to="P02", message=long_text))
    assert len(game.messages[0].message) == game.config.message_max_length


# --- 全体発言（§5.2） ---

def test_broadcast_delivered_and_logged():
    game = make_game()
    game.players["P01"] = make_player("P01")
    game._handle_broadcast(1, game.players["P01"], BroadcastAction(player_id="P01", message="同盟を組もう"))
    assert len(game.messages) == 1
    assert game.messages[0].type == "broadcast"
    assert game.messages[0].sender == "P01"
    events = [e for e in game.logger.events if e.event_type == "BROADCAST_SENT"]
    assert events[0].data["message"] == "同盟を組もう"


def test_broadcast_rejects_empty_message():
    game = make_game()
    game.players["P01"] = make_player("P01")
    game._handle_broadcast(1, game.players["P01"], BroadcastAction(player_id="P01", message=""))
    assert len(game.messages) == 0


# --- 匿名通信（§7.5: 10万円で1メッセージ、1ターン1通まで） ---

def test_anonymous_broadcast_charges_fee_and_hides_sender():
    game = make_game()
    game.players["P01"] = make_player("P01", cash=1_000_000)
    game._handle_anonymous_broadcast(1, game.players["P01"], AnonymousBroadcastAction(player_id="P01", message="密告"))
    assert len(game.messages) == 1
    assert game.messages[0].sender is None
    assert game.players["P01"].cash == 1_000_000 - game.config.anonymous_message_fee
    assert game._anon_message_owners[game.messages[0].message_id] == "P01"
    events = [e for e in game.logger.events if e.event_type == "ANONYMOUS_BROADCAST_SENT"]
    assert events[0].data["sender"] == "P01"  # god専用データ（viewer側でホワイトリストにより落ちる）


def test_anonymous_broadcast_rejects_insufficient_cash():
    game = make_game()
    game.players["P01"] = make_player("P01", cash=0)
    game._handle_anonymous_broadcast(1, game.players["P01"], AnonymousBroadcastAction(player_id="P01", message="密告"))
    assert len(game.messages) == 0
    assert game.players["P01"].cash == 0  # 料金は引かれていない
    events = [e for e in game.logger.events if e.event_type == "ANON_BROADCAST_REJECTED"]
    assert events[0].data["reason"] == "insufficient_cash"


def test_anonymous_broadcast_rejects_over_limit_per_turn():
    game = make_game()
    game.players["P01"] = make_player("P01", cash=10_000_000)
    action = AnonymousBroadcastAction(player_id="P01", message="密告")
    game._handle_anonymous_broadcast(1, game.players["P01"], action)
    game._handle_anonymous_broadcast(1, game.players["P01"], action)  # 同じターンに2通目
    assert len(game.messages) == 1
    events = [e for e in game.logger.events if e.event_type == "ANON_BROADCAST_REJECTED"]
    assert events[0].data["reason"] == "anon_limit_reached"


def test_anon_limit_resets_next_turn():
    game = make_game(total_turns=5)
    game.players["P01"] = make_player("P01", cash=10_000_000)
    action = AnonymousBroadcastAction(player_id="P01", message="密告")
    game._handle_anonymous_broadcast(1, game.players["P01"], action)
    game._run_turn(2)  # ターン境界で_anon_sent_this_turnがクリアされる
    game._handle_anonymous_broadcast(2, game.players["P01"], action)
    anon_messages = [m for m in game.messages if m.type == "anonymous_broadcast"]
    assert len(anon_messages) == 2


def test_rejected_anonymous_does_not_register_owner():
    game = make_game()
    game.players["P01"] = make_player("P01", cash=0)
    game._handle_anonymous_broadcast(1, game.players["P01"], AnonymousBroadcastAction(player_id="P01", message="密告"))
    assert game._anon_message_owners == {}


# --- 待機の起床条件（§5.2: DM到着で起こす、全体発言では起こさない） ---

def test_wait_wakes_on_unread_dm():
    game = make_game(num_players=2)
    game.players["P01"] = make_player("P01")
    game.players["P02"] = make_player("P02")
    game._handle_dm(1, game.players["P02"], DmAction(player_id="P02", to="P01", message="起きて"))
    visible_state = game._build_visible_state("P01", 2)
    assert game._should_wake(2, {"until_turn": None, "wake_on_event": True}, visible_state) is True


def test_wait_does_not_wake_on_broadcast_alone():
    """全体発言だけでは起こさない（1人がbroadcastしただけで全員が起きるとLLM呼び出しが激増するため）"""
    game = make_game(num_players=2)
    game.players["P01"] = make_player("P01")
    game.players["P02"] = make_player("P02")
    game._handle_broadcast(1, game.players["P02"], BroadcastAction(player_id="P02", message="宣言"))
    visible_state = game._build_visible_state("P01", 2)
    assert game._should_wake(2, {"until_turn": None, "wake_on_event": True}, visible_state) is False


# --- メッセージの保持（全ターン全件保持、削除しない） ---

def test_messages_are_never_deleted_across_many_turns():
    game = make_game(num_players=2, total_turns=30)
    game.players["P01"] = make_player("P01")
    game.players["P02"] = make_player("P02")
    game._handle_dm(1, game.players["P01"], DmAction(player_id="P01", to="P02", message="最初のメッセージ"))
    for t in range(2, 25):
        game._run_turn(t)
    assert len(game.messages) == 1
    assert game.messages[0].message == "最初のメッセージ"


def test_prompt_window_excludes_old_broadcast_but_keeps_unread_dm():
    """窓の外の古いbroadcastはプロンプトから外れるが、自分宛の未読DMは窓の外でも出る"""
    game = make_game(num_players=2, total_turns=30)
    game.players["P01"] = make_player("P01")
    game.players["P02"] = make_player("P02")
    game._handle_broadcast(1, game.players["P02"], BroadcastAction(player_id="P02", message="古い宣言"))
    game._handle_dm(1, game.players["P02"], DmAction(player_id="P02", to="P01", message="古いが未読のDM"))
    # P01がT2でact()を呼ばれた体にする（seen_turn更新）が、その後何もしないまま
    # window_turns(既定10)を超えて進む
    far_turn = 1 + game.config.message_prompt_window_turns + 5
    state = game._build_visible_state("P01", far_turn)
    bodies = [m.get("message") for m in state["messages"]]
    assert "古いが未読のDM" in bodies
    assert "古い宣言" not in bodies


def test_message_seen_turn_updates_only_when_act_is_called():
    """待機中（act()が呼ばれない）はmessage_seen_turnが更新されない"""
    game = make_game(num_players=2, total_turns=10)
    game.players["P01"] = make_player("P01")
    game.players["P02"] = make_player("P02")
    game._waiting["P01"] = {"until_turn": 5, "wake_on_event": False}
    game._collect_actions(2)
    assert "P01" not in game._message_seen_turn
