"""
カード管理モジュール

§3.1 に基づくカードのデッキ生成・残数集計を提供する。
各AIに同一構成の12枚（グー・チョキ・パー各4枚）が配布される。
"""

from engine.models import Card, Hand, PlayerState


def create_deck(player_id: str) -> list[Card]:
    """
    §2.1/§3.1 に基づく12枚デッキを生成する（グー・チョキ・パー各4枚）

    card_id はプレイヤー内で一意（例: "P01_ROCK_1"）。トレードで他プレイヤーの
    カードを受け取り card_id が衝突する場合は、受け取った側でリネームすること
    （rules/project.md「残数掲示板は独立カウンタを持たない」参照）。

    Args:
        player_id: 配布先のプレイヤーID（card_id の接頭辞に使う）

    Returns:
        12枚のカードリスト
    """
    deck: list[Card] = []
    for hand in (Hand.ROCK, Hand.SCISSORS, Hand.PAPER):
        for i in range(1, 5):
            deck.append(Card(hand=hand, card_id=f"{player_id}_{hand.value}_{i}"))
    return deck


def board_counts(players: list[PlayerState]) -> dict[str, int]:
    """
    残数掲示板（§8.1）を導出する

    場に残っている（is_alive=True）プレイヤー全員の手札（予約中のカードを含む）を
    種類別に合計する。独立カウンタを持たず、この関数を毎ターン呼んで導出すること
    （rules/project.md 参照）。

    Args:
        players: 全プレイヤー状態のリスト

    Returns:
        {"ROCK": n, "SCISSORS": n, "PAPER": n}
    """
    counts = {Hand.ROCK.value: 0, Hand.SCISSORS.value: 0, Hand.PAPER.value: 0}
    for p in players:
        if not p.is_alive:
            continue
        for card in p.cards:
            counts[card.hand.value] += 1
    return counts


def total_cards_in_play(players: list[PlayerState]) -> int:
    """場に残る全カード枚数（board_counts の合計と一致するはずのテスト用ヘルパ）"""
    return sum(board_counts(players).values())
