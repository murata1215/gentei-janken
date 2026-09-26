"""
プロンプト構築モジュール

仕様書§10（目的文）・§5.3（個別通知）・§8.1（残数掲示板）・§5.2（アクション一覧）
に対応するプロンプト生成関数を提供する。

サイクル1.5での変更点: 対戦の申込・受諾に必要な card_id / offer_id / 対戦相手
候補（alive_player_ids）を件数だけでなく実際の識別子として渡すようにした。
これらが無いと LLM が対戦を組み立てられず、engine/player.py の
「does not have card ...」で全て MATCH_OFFER_REJECTED / MATCH_ACCEPT_REJECTED
になり、試合が1件も成立しなかった（サイクル1.0の実害）。
"""

import json

from engine.config import GameConfig
from engine.models import PlayerState
from llm.phase2_schema import IMPLEMENTED_ACTION_TYPES, REQUIRED_FIELDS_BY_ACTION_TYPE

OBJECTIVE_TEXT = (
    "このゲームにおいて、生還は勝利ではなく最低条件である。"
    "カードを使い切り、★を3個以上守り、借金を清算して退出せよ。"
    "そのうえで、可能な限り多くの最終資産を残し、より高い順位を目指せ。"
    "★が0個になれば即座に退場となり、時間内に退出できなければ敗北となる。"
    "上位を狙った結果として生還できなければ、それは明確な敗北である。"
    "最も高く評価される結果は総合1位である。"
    "自らの判断力、交渉力、戦略性を結果によって示せ。"
)
"""仕様書§10の目的文（逐語）。チーム戦・協力目標は設定しない、完全な個人戦。"""


def build_objective_section() -> str:
    """
    目的文セクションを構築する（§10）

    プロンプトの先頭に `## 目的` 節として置き、毎ターンの行動要求の末尾でも
    短く再掲する想定（呼び出し側が2箇所で使い分ける）。
    """
    return f"## 目的\n{OBJECTIVE_TEXT}"


def build_objective_reminder() -> str:
    """行動要求末尾に添える短い再掲（§10）"""
    return "（生還は最低条件。最終資産と総合順位を最大化せよ）"


def build_personal_notice(player: PlayerState, turn: int, visible_state: dict) -> str:
    """
    個別通知セクションを構築する（§5.3、本人にのみ渡す7項目）

    - 現在のターンと残りターン数
    - 現金、借金残高、次の利息計上ターンと見込み額
    - 手札の種類別枚数（予約中のカードを含む）とcard_id一覧
      （card_idはmatch_offer/match_acceptで指定する識別子。自分の手札なので
      公開/秘匿の区別に関係なく本人には常に見せてよい）
    - ★の数
    - カードを使い切るのに最低限必要なターン数（手札枚数×2）
    - 届いている対戦申込と自分が出している申込（offer_id付き）
    - 自分の現在の順位の見込み（清算後の資産で計算）
    """
    config: GameConfig = visible_state["config"]
    remaining = config.total_turns - turn
    next_interest_turn = _next_interest_turn(turn, config)

    hand_groups: dict[str, list[str]] = {"ROCK": [], "SCISSORS": [], "PAPER": []}
    for c in player.cards:
        hand_groups.setdefault(c.hand.value, []).append(c.card_id)

    incoming = visible_state.get("offers_incoming", [])
    outgoing = visible_state.get("offers_outgoing", [])

    lines = [
        "## あなたの状況",
        f"- 現在ターン: {turn} / {config.total_turns}（残り{remaining}ターン）",
        f"- 現金: {player.cash}円",
        f"- 借金残高: {player.debt}円",
        f"- 次の利息計上ターン: {next_interest_turn if next_interest_turn else 'なし'}"
        f"（見込み利息: {_estimate_interest(player, config)}円）",
        "- 手札（card_idを対戦の申込・受諾で指定する）:",
    ]
    for hand_value in ("ROCK", "SCISSORS", "PAPER"):
        ids = hand_groups.get(hand_value, [])
        lines.append(f"  - {hand_value}: {', '.join(ids) if ids else '(なし)'}")
    lines += [
        f"- 手札合計: {len(player.cards)}枚（予約中を含む）",
        f"- ★: {player.stars}個",
        f"- カードを使い切るのに最低限必要なターン数: {len(player.cards) * 2}",
        "- 自分の現在の順位の見込み（清算後の資産で計算）: "
        f"{visible_state.get('projected_rank', '?')}位 / {visible_state.get('projected_rank_total', '?')}人",
        f"- 届いている対戦申込（{len(incoming)}件。match_acceptまたはmatch_declineでoffer_idを指定する）:",
    ]
    if incoming:
        for o in incoming:
            lines.append(f"  - offer_id={o.offer_id} 申込者={o.challenger_id}")
    else:
        lines.append("  - (なし)")
    lines.append(f"- 自分が出している申込（{len(outgoing)}件。match_withdrawでoffer_idを指定して取り下げられる）:")
    if outgoing:
        for o in outgoing:
            lines.append(
                f"  - offer_id={o.offer_id} 相手={o.opponent_id} "
                f"自分の出した手={o.challenger_hand.value} status={o.status}"
            )
    else:
        lines.append("  - (なし)")
    return "\n".join(lines)


def build_opponents_section(visible_state: dict) -> str:
    """
    対戦の申込先・送金先として指定できるプレイヤーIDの一覧

    engine/game.py::_build_visible_state の alive_player_ids
    （場に残っている自分以外の全員。★の数と同じく公開情報、§8.2）をそのまま列挙する。
    """
    alive = visible_state.get("alive_player_ids", [])
    if not alive:
        return "## 場に残っている他プレイヤー\n(なし)"
    return "## 場に残っている他プレイヤー（対戦・送金の相手先IDに使える）\n" + ", ".join(alive)


def build_board_section(board: dict[str, int]) -> str:
    """残数掲示板セクションを構築する（§8.1）"""
    return (
        "## 場の残数掲示板\n"
        f"- グー(ROCK): {board.get('ROCK', 0)}枚\n"
        f"- チョキ(SCISSORS): {board.get('SCISSORS', 0)}枚\n"
        f"- パー(PAPER): {board.get('PAPER', 0)}枚"
    )


ACTION_DESCRIPTIONS_JA: dict[str, str] = {
    "pass": "何もしない",
    "wait": "指定ターンまで、またはイベント発生まで待機する（待機中はLLMを呼び出さない）",
    "repay": "任意返済（現金で借金を返す。返済額はcash/debtで自動的に上限調整される）",
    "transfer": "他プレイヤーへ送金する",
    "match_offer": "対戦を申込む（手とカードを封じて提出する）",
    "match_accept": "届いている対戦申込を受諾する（手とカードを封じて提出する）",
    "match_decline": "届いている対戦申込を拒否する",
    "match_withdraw": "自分が出した対戦申込を取り下げる（受諾前のみ）",
    "exit": "退出する（§6.1の条件を満たさない場合は不成立になるだけで脱落しない）",
}
"""IMPLEMENTED_ACTION_TYPES に対応する日本語の短い説明"""

_ACTION_EXAMPLE = {
    "action_type": "match_offer",
    "opponent_id": "P07",
    "hand": "ROCK",
    "card_id": "P01_ROCK_1",
}
"""build_action_prompt() が末尾に添える具体例（match_offer）"""


def build_action_prompt() -> str:
    """
    行動選択の指示セクションを構築する（§5.2）

    IMPLEMENTED_ACTION_TYPES（本サイクルでengineが実処理するアクション種）のみを
    提示する。未実装（dm/trade_*/contract_*/bounty_*等）は提示しない
    ——選ばせても ACTION_UNHANDLED で捨てられ、課金とターンの無駄になるため。
    """
    lines = [
        "## 行動選択",
        "次のいずれか1つを選び、JSONオブジェクトのみで応答してください"
        "（説明文や前置きは書かず、```json ... ``` または生JSONのみ）。",
        'キー"action_type"には次の文字列のいずれかを入れてください:',
    ]
    for action_type in IMPLEMENTED_ACTION_TYPES:
        fields = REQUIRED_FIELDS_BY_ACTION_TYPE[action_type]
        field_note = f"必須フィールド: {', '.join(fields)}" if fields else "他のフィールドは不要"
        lines.append(f'- "{action_type}": {ACTION_DESCRIPTIONS_JA[action_type]}（{field_note}）')
    lines.append("例（対戦の申込）: " + json.dumps(_ACTION_EXAMPLE, ensure_ascii=False))
    lines.append(build_objective_reminder())
    return "\n".join(lines)


def build_system_prompt(player_id: str) -> str:
    """system prompt全体を組み立てる（§10の目的文を先頭に置く）"""
    return (
        f"あなたは限定ジャンケンのプレイヤー {player_id} です。\n\n"
        f"{build_objective_section()}"
    )


def _next_interest_turn(turn: int, config: GameConfig) -> int | None:
    """次に利息が計上されるターン番号を返す（§2.3）。もう発生しないならNone"""
    if config.interest_interval_turns <= 0:
        return None
    n = (turn // config.interest_interval_turns + 1) * config.interest_interval_turns
    return n if n <= config.total_turns else None


def _estimate_interest(player: PlayerState, config: GameConfig) -> int:
    """次回計上される利息の見込み額（切り上げ、§2.3）"""
    import math
    if player.debt <= 0:
        return 0
    return math.ceil(player.debt * config.interest_rate)
