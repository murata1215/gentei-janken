"""
通信モジュール（§5.2/§7.5: DM・全体発言・匿名通信）

Message自体は全ターン全件保持する（削除しない）。§5.2のwaitは「DMが届いたら
起こして」を要求しており、起床トリガと本文の寿命を一致させる必要がある
（途中で削除すると、寝ていたプレイヤーが起きた時に起床理由の本文が消えている
事故が起きる）。プロンプトへの表示件数は engine/config.py の
message_prompt_limit/message_prompt_window_turns で別途絞る
（engine/game.py::_build_visible_state が担当）。

可視性の投影（誰に何を見せるか）は本モジュールの純関数 visible_messages() に
一本化する。Game本体のメソッドにしないことで、tests/test_dm_secrecy.py が
Gameインスタンスを組まずに直接検証できる。
"""

from typing import Any

from engine.config import GameConfig
from engine.models import Message, PlayerState


def make_message_id(turn: int, counter: int) -> str:
    """メッセージIDを決定的に生成する（engine/matches.py::make_offer_idと同形式）"""
    return f"MSG_{turn}_{counter}"


def format_message_body(text: str, max_length: int) -> str:
    """本文を上限文字数で切り詰める（§7.5 匿名通信を含む全メッセージ種に適用）"""
    return text[:max_length]


def can_send_anonymous(player: PlayerState, config: GameConfig, sent_this_turn: int) -> tuple[bool, str | None]:
    """
    匿名通信を送れるか判定する（§7.5: 10万円で1メッセージ、1ターン1通まで）

    Returns:
        (送れるか, 送れない場合の理由コード。送れるならNone)
    """
    if sent_this_turn >= config.anonymous_message_limit_per_turn:
        return False, "anon_limit_reached"
    if player.cash < config.anonymous_message_fee:
        return False, "insufficient_cash"
    return True, None


def visible_messages(
    messages: list[Message], anon_owners: dict[str, str], for_player_id: str | None,
) -> list[dict[str, Any]]:
    """
    for_player_id視点で見える形にメッセージ列を投影する（§8.2の秘匿境界）

    - DM: 当事者（sender/to）以外に対しては"message"キー自体を辞書から削除する
      （空文字上書きではなくキー欠落。rules/project.md「DM本文はキーごと削除」）。
      代わりに"redacted": Trueを立てる。
    - 匿名通信: Message.senderは常にNoneなので値としては元々秘匿されている。
      本人（anon_owners[message_id] == for_player_id）にだけ"is_mine": True
      を追加する（真のときだけキーを足す。dangou-cardの慣習を踏襲）。
    - 全体発言: 誰にでも全文を見せる（§8.2「全体発言」は公開情報）。
    - for_player_id=None は安全側に倒れる（全DMがredacted、is_mineは一切付かない）。
    """
    out: list[dict[str, Any]] = []
    for m in messages:
        d = m.model_dump()
        if d["type"] == "dm" and for_player_id not in (d["sender"], d["to"]):
            d.pop("message", None)
            d["redacted"] = True
        elif d["type"] == "anonymous_broadcast":
            if for_player_id is not None and anon_owners.get(d["message_id"]) == for_player_id:
                d["is_mine"] = True
        out.append(d)
    return out
