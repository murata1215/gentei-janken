"""
テスト用共通フィクスチャ

ゲーム状態・プレイヤーの生成ヘルパーを提供する。
"""

import pytest

from engine.config import GameConfig
from engine.events import EventLogger
from engine.models import Card, Hand, PlayerState


@pytest.fixture
def config_small() -> GameConfig:
    """開発用の小規模設定（4人×20ターン）"""
    return GameConfig.dev_small(num_players=4, total_turns=20)


@pytest.fixture
def config_20() -> GameConfig:
    """20人版デフォルト設定（仕様書§11）"""
    return GameConfig.default_20()


@pytest.fixture
def logger() -> EventLogger:
    """固定タイムスタンプのイベントロガー"""
    return EventLogger(fixed_timestamp="2026-01-01T00:00:00+00:00")


def make_player(
    player_id: str = "P01",
    *,
    cards: list[Card] | None = None,
    stars: int = 3,
    cash: int = 1_000_000,
    debt: int = 1_000_000,
    initial_loan: int = 1_000_000,
    reserved_card_ids: list[str] | None = None,
    is_alive: bool = True,
) -> PlayerState:
    """任意の状態のPlayerStateを組み立てるヘルパー"""
    if cards is None:
        cards = [Card(hand=Hand.ROCK, card_id=f"{player_id}_ROCK_1")]
    return PlayerState(
        player_id=player_id,
        cards=cards,
        stars=stars,
        cash=cash,
        debt=debt,
        initial_loan=initial_loan,
        reserved_card_ids=reserved_card_ids or [],
        is_alive=is_alive,
    )


def make_full_hand(player_id: str) -> list[Card]:
    """グー・チョキ・パー各4枚の初期手札を組み立てるヘルパー（create_deck相当）"""
    from engine.cards import create_deck
    return create_deck(player_id)
