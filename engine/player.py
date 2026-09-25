"""
プレイヤー状態管理モジュール

§2〜§6 に基づくプレイヤーの資金管理（現金・借金）、手札・★管理、
生存/退出状態管理を提供する。PlayerState はイミュータブルに扱い、
すべての関数は model_copy() で更新後の新しいインスタンスを返す。
"""

import math

from engine.cards import create_deck
from engine.config import GameConfig
from engine.models import Card, PlayerState


def create_player(player_id: str, loan_amount: int) -> PlayerState:
    """
    新規プレイヤーを作成する（§2.1/§2.2）

    初期配布:
    - 現金 = 借入額
    - 借金残高 = 借入額
    - 手札 = 12枚のデッキ（グー・チョキ・パー各4枚）
    - ★ = 3個（PlayerStateの既定値）

    Args:
        player_id: プレイヤーID（例: "P01"）
        loan_amount: 借入額（100万〜1000万、§2.2）

    Returns:
        初期化されたPlayerState
    """
    return PlayerState(
        player_id=player_id,
        cash=loan_amount,
        debt=loan_amount,
        initial_loan=loan_amount,
        cards=create_deck(player_id),
    )


# --- 現金 ---

def pay(player: PlayerState, amount: int) -> PlayerState:
    """現金を支払う（Cashを減少）。事前に残高検証済みであること"""
    return player.model_copy(update={"cash": player.cash - amount})


def receive(player: PlayerState, amount: int) -> PlayerState:
    """現金を受け取る（Cashを増加）"""
    return player.model_copy(update={"cash": player.cash + amount})


def can_pay(player: PlayerState, amount: int) -> bool:
    """現金が足りるか判定（Cash ≥ amount）"""
    return player.cash >= amount


# --- 利息・返済（§2.3/§2.4） ---

def apply_interest(player: PlayerState, rate: float) -> PlayerState:
    """
    利息を計上する（§2.3: 1.5%複利）

    端数は切り上げ（保守的解釈: 借り手に不利な方向。dangou-cardと同じ解釈）。
    退出済み（has_exited=True）のプレイヤーには計上しない（§2.3「退出した時点で止まる」）。

    Args:
        player: プレイヤー状態
        rate: 利率（例: 0.015 = 1.5%）
    """
    if player.has_exited or player.debt <= 0:
        return player
    interest = math.ceil(player.debt * rate)
    return player.model_copy(update={"debt": player.debt + interest})


def repay_debt(player: PlayerState, amount: int) -> PlayerState:
    """
    借金を任意返済する（§2.4: いつでも可能）

    返済額はmin(指定額, 現金残高, 借金残高)に調整される。

    Args:
        player: プレイヤー状態
        amount: 返済希望額
    """
    actual = min(max(0, amount), player.cash, player.debt)
    return player.model_copy(update={
        "cash": player.cash - actual,
        "debt": player.debt - actual,
    })


def can_repay_now(player: PlayerState, turn: int, config: GameConfig) -> bool:
    """
    現在ターンで任意返済が可能か判定する（§9.3案2/未決事項）

    config.repay_unlock_turn が0（既定）なら常にTrue（仕様書どおり）。
    正の値が設定されている場合、そのターンまでrepayアクションを不成立にする。
    """
    return turn >= config.repay_unlock_turn


# --- 手札・カード（§3.1、§4.1の予約含む） ---

def use_card(player: PlayerState, card_id: str) -> PlayerState:
    """
    手札からカードを1枚使用（消滅）する（§3.1: 対戦で使ったカードは勝敗に関係なく消える）

    card_idが同一のカードが複数存在する状況は本ゲームの設計上想定しない
    （create_deck()がプレイヤー内で一意なcard_idを払い出すため）が、
    万一の重複に備え1枚だけ除去する（dangou-cardのuse_card()と同じ安全策）。

    Args:
        player: プレイヤー状態
        card_id: 使用するカードのID

    Returns:
        更新されたPlayerState（予約中だった場合はreserved_card_idsからも除去）

    Raises:
        ValueError: 指定カードが手札にない場合
    """
    found = False
    new_cards: list[Card] = []
    for c in player.cards:
        if c.card_id == card_id and not found:
            found = True
            continue
        new_cards.append(c)
    if not found:
        raise ValueError(f"{player.player_id} does not have card {card_id}")
    new_reserved = [cid for cid in player.reserved_card_ids if cid != card_id]
    return player.model_copy(update={"cards": new_cards, "reserved_card_ids": new_reserved})


def reserve_card(player: PlayerState, card_id: str) -> PlayerState:
    """
    対戦申込・受諾で手札のカードを予約する（§4.1）

    予約中のカードは他の用途（別の対戦・取引）に使えない。1人が同時に持てる
    予約は複数ありうる（自分が出している申込1件 + 受諾した対戦1件が同ターンに
    重なる場合など。§4.3は"出せる"申込を1件までに制限するのみ）。

    Raises:
        ValueError: 指定カードが手札にない、または既にそのカードが予約中の場合
    """
    if not any(c.card_id == card_id for c in player.cards):
        raise ValueError(f"{player.player_id} does not have card {card_id}")
    if card_id in player.reserved_card_ids:
        raise ValueError(f"{player.player_id} already has card {card_id} reserved")
    return player.model_copy(update={"reserved_card_ids": player.reserved_card_ids + [card_id]})


def release_reserved_card(player: PlayerState, card_id: str) -> PlayerState:
    """
    指定カードの予約を解除し手札に戻す（§4.3: 申込が失効・取り下げられた場合）

    カード自体はもともと手札から除去していない（予約はマーカーのみ）ため、
    reserved_card_ids から該当card_idを取り除くだけでよい。
    """
    new_reserved = [cid for cid in player.reserved_card_ids if cid != card_id]
    return player.model_copy(update={"reserved_card_ids": new_reserved})


def add_card(player: PlayerState, card: Card) -> PlayerState:
    """
    トレード・譲渡で受け取ったカードを手札に加える（§3.1/§7.1）

    card_id が手札内で衝突する場合はサフィックスで一意化する
    （dangou-card の swap_card() と同じ安全策。rules/project.md参照）。
    """
    actual_card = card
    if any(c.card_id == card.card_id for c in player.cards):
        new_id = f"{card.card_id}_t"
        counter = 2
        while any(c.card_id == new_id for c in player.cards):
            new_id = f"{card.card_id}_t{counter}"
            counter += 1
        actual_card = Card(hand=card.hand, card_id=new_id)
    return player.model_copy(update={"cards": list(player.cards) + [actual_card]})


def remove_card(player: PlayerState, card_id: str) -> tuple[PlayerState, Card]:
    """
    トレード・譲渡で差し出すカードを手札から取り除く（§3.1/§7.1）

    use_card() と異なり「消滅」ではなく「移転」なので、除去したCardオブジェクト
    自体を返す（呼び出し側が相手のadd_card()へそのまま渡す）。

    Raises:
        ValueError: 指定カードが手札にない場合
    """
    for c in player.cards:
        if c.card_id == card_id:
            new_cards = [x for x in player.cards if x.card_id != card_id]
            return player.model_copy(update={"cards": new_cards}), c
    raise ValueError(f"{player.player_id} does not have card {card_id}")


def min_turns_to_clear_hand(player: PlayerState) -> int:
    """
    カードを使い切るのに最低限必要なターン数（§5.3: 手札枚数×2）

    対戦1回に最短2ターンかかる（§4.1）ため、1枚使うのに最短2ターン。
    """
    return len(player.cards) * 2


# --- ★（§3.2） ---

def add_stars(player: PlayerState, n: int) -> PlayerState:
    """★を加える（対戦の勝ち・譲渡・取引での受取）"""
    return player.model_copy(update={"stars": player.stars + n})


def remove_stars(player: PlayerState, n: int) -> PlayerState:
    """
    ★を減らす（対戦の負け・譲渡・取引での譲渡）

    Raises:
        ValueError: 保有数を超える場合
    """
    if n > player.stars:
        raise ValueError(f"{player.player_id} has only {player.stars} stars, cannot remove {n}")
    return player.model_copy(update={"stars": player.stars - n})


# --- 脱落・退出（§1.2/§6） ---

def eliminate(player: PlayerState, elimination_type: str, turn: int) -> PlayerState:
    """
    プレイヤーを脱落させる（§1.2: 強制退場 / 契約違反 / 時間切れ）

    Args:
        player: プレイヤー状態
        elimination_type: "FORCED_EXIT" / "CONTRACT_VIOLATION" / "TIMEOUT"
        turn: 脱落が確定したターン番号
    """
    return player.model_copy(update={
        "is_alive": False,
        "elimination_type": elimination_type,
        "elimination_turn": turn,
    })


def mark_exited(player: PlayerState, turn: int, final_assets: int) -> PlayerState:
    """
    プレイヤーを生還（退出）させる（§6.2 清算完了）

    is_alive は場からの離脱を表すため False にするが、elimination_type は
    None のまま（脱落ではないことを区別する）。
    """
    return player.model_copy(update={
        "is_alive": False,
        "has_exited": True,
        "exit_turn": turn,
        "final_assets": final_assets,
    })
