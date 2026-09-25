"""ジャンケン判定（§4.2）のテスト"""

from engine.judge import judge
from engine.models import Hand


def test_rock_beats_scissors():
    assert judge(Hand.ROCK, Hand.SCISSORS) == "challenger_win"
    assert judge(Hand.SCISSORS, Hand.ROCK) == "opponent_win"


def test_scissors_beats_paper():
    assert judge(Hand.SCISSORS, Hand.PAPER) == "challenger_win"
    assert judge(Hand.PAPER, Hand.SCISSORS) == "opponent_win"


def test_paper_beats_rock():
    assert judge(Hand.PAPER, Hand.ROCK) == "challenger_win"
    assert judge(Hand.ROCK, Hand.PAPER) == "opponent_win"


def test_draws():
    for h in (Hand.ROCK, Hand.SCISSORS, Hand.PAPER):
        assert judge(h, h) == "draw"


def test_all_nine_combinations_covered():
    """9通りの組み合わせすべてが有効な結果を返すことを確認する"""
    hands = list(Hand)
    outcomes = {judge(a, b) for a in hands for b in hands}
    assert outcomes == {"challenger_win", "opponent_win", "draw"}
