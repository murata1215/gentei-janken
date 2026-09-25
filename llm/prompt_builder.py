"""
プロンプト構築モジュール

仕様書§10（目的文）・§5.3（個別通知）・§8.1（残数掲示板）・§5.2（アクション一覧）
に対応する最小限のプロンプト生成関数を提供する。本サイクルでは3つの主要関数の
足場のみを実装し、DM秘匿・契約可視化ブロック等の完全な可視状態組み立ては次サイクルで
拡張する（engine/game.py::_build_visible_state の TODO と対応）。
"""

from engine.config import GameConfig
from engine.models import PlayerState

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
    - 手札の種類別枚数（予約中のカードを含む）
    - ★の数
    - カードを使い切るのに最低限必要なターン数（手札枚数×2）
    - 届いている対戦申込と取引提案、自分が出している申込
    - 自分の現在の順位の見込み（清算後の資産で計算） — TODO: 次サイクルで実装
    """
    config: GameConfig = visible_state["config"]
    remaining = config.total_turns - turn
    next_interest_turn = _next_interest_turn(turn, config)
    hand_counts: dict[str, int] = {}
    for c in player.cards:
        hand_counts[c.hand.value] = hand_counts.get(c.hand.value, 0) + 1

    incoming = visible_state.get("offers_incoming", [])
    outgoing = visible_state.get("offers_outgoing", [])

    lines = [
        "## あなたの状況",
        f"- 現在ターン: {turn} / {config.total_turns}（残り{remaining}ターン）",
        f"- 現金: {player.cash}円",
        f"- 借金残高: {player.debt}円",
        f"- 次の利息計上ターン: {next_interest_turn if next_interest_turn else 'なし'}"
        f"（見込み利息: {_estimate_interest(player, config)}円）",
        f"- 手札: {hand_counts}（計{len(player.cards)}枚、予約中を含む）",
        f"- ★: {player.stars}個",
        f"- カードを使い切るのに最低限必要なターン数: {len(player.cards) * 2}",
        f"- 届いている対戦申込: {len(incoming)}件",
        f"- 自分が出している申込: {len(outgoing)}件",
    ]
    return "\n".join(lines)


def build_board_section(board: dict[str, int]) -> str:
    """残数掲示板セクションを構築する（§8.1）"""
    return (
        "## 場の残数掲示板\n"
        f"- グー(ROCK): {board.get('ROCK', 0)}枚\n"
        f"- チョキ(SCISSORS): {board.get('SCISSORS', 0)}枚\n"
        f"- パー(PAPER): {board.get('PAPER', 0)}枚"
    )


def build_action_prompt() -> str:
    """行動選択の指示セクションを構築する（§5.2 アクション一覧）"""
    return (
        "## 行動選択\n"
        "次のいずれか1つをJSONで選択してください: "
        "DM、全体発言、匿名通信、送金、任意返済、対戦の申込・受諾・拒否・取り下げ、"
        "カードと★の取引の提案・受諾・拒否・取り下げ、正式契約の提案・署名・解除、"
        "報奨の掲示・取り下げ、退出、待機、パス。\n"
        f"{build_objective_reminder()}"
    )


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
