"""
ジャンケン判定モジュール

§4.2 の勝敗表を提供する。
"""

from engine.models import Hand, MatchOutcome

# 「a が b に勝つ」組み合わせの集合（グー>チョキ、チョキ>パー、パー>グー）
_BEATS: dict[Hand, Hand] = {
    Hand.ROCK: Hand.SCISSORS,
    Hand.SCISSORS: Hand.PAPER,
    Hand.PAPER: Hand.ROCK,
}


def judge(challenger_hand: Hand, opponent_hand: Hand) -> MatchOutcome:
    """
    ジャンケンの勝敗を判定する（§4.2）

    Args:
        challenger_hand: 申込者の手
        opponent_hand: 受諾者の手

    Returns:
        "challenger_win" / "opponent_win" / "draw"
    """
    if challenger_hand == opponent_hand:
        return "draw"
    if _BEATS[challenger_hand] == opponent_hand:
        return "challenger_win"
    return "opponent_win"
