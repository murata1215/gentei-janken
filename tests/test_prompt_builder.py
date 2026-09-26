"""
llm/prompt_builder.py のテスト

サイクル1.0の実害（LLMに渡すプロンプトにcard_id/offer_id/対戦相手候補が無く、
1試合も成立しなかった）の再発防止線。build_personal_notice()・
build_opponents_section()・build_action_prompt() が実際に識別子を出力する
ことを機械的に検証する。
"""

import json

from engine.config import GameConfig
from engine.models import Card, Hand, MatchOffer
from llm.phase2_schema import IMPLEMENTED_ACTION_TYPES, REQUIRED_FIELDS_BY_ACTION_TYPE
from llm.prompt_builder import (
    build_action_prompt, build_board_section, build_opponents_section, build_personal_notice,
)
from tests.conftest import make_player


def _visible_state(**overrides) -> dict:
    base = {
        "config": GameConfig.dev_small(num_players=4, total_turns=20),
        "board": {"ROCK": 4, "SCISSORS": 4, "PAPER": 4},
        "offers_incoming": [],
        "offers_outgoing": [],
        "alive_player_ids": ["P02", "P03", "P04"],
        "projected_rank": 1,
        "projected_rank_total": 4,
    }
    base.update(overrides)
    return base


def test_personal_notice_includes_card_ids_per_hand():
    cards = [
        Card(hand=Hand.ROCK, card_id="P01_ROCK_1"),
        Card(hand=Hand.SCISSORS, card_id="P01_SCISSORS_1"),
    ]
    player = make_player("P01", cards=cards)
    notice = build_personal_notice(player, 5, _visible_state())
    assert "P01_ROCK_1" in notice
    assert "P01_SCISSORS_1" in notice


def test_personal_notice_includes_incoming_offer_id_and_challenger():
    player = make_player("P01")
    offer = MatchOffer(
        offer_id="M_3_P02_1", challenger_id="P02", opponent_id="P01",
        turn_offered=3, challenger_hand=Hand.ROCK, challenger_card_id="P02_ROCK_1",
        status="pending",
    )
    notice = build_personal_notice(player, 4, _visible_state(offers_incoming=[offer]))
    assert "M_3_P02_1" in notice
    assert "P02" in notice


def test_personal_notice_includes_outgoing_offer_id_and_opponent():
    player = make_player("P01")
    offer = MatchOffer(
        offer_id="M_2_P01_1", challenger_id="P01", opponent_id="P03",
        turn_offered=2, challenger_hand=Hand.PAPER, challenger_card_id="P01_PAPER_1",
        status="pending",
    )
    notice = build_personal_notice(player, 3, _visible_state(offers_outgoing=[offer]))
    assert "M_2_P01_1" in notice
    assert "P03" in notice
    assert "PAPER" in notice  # 自分が出した手は自分には秘匿する必要がない


def test_personal_notice_includes_projected_rank():
    player = make_player("P01")
    notice = build_personal_notice(player, 3, _visible_state(projected_rank=2, projected_rank_total=4))
    assert "2位" in notice
    assert "4人" in notice


def test_opponents_section_lists_alive_player_ids():
    section = build_opponents_section(_visible_state(alive_player_ids=["P02", "P05", "P09"]))
    assert "P02" in section
    assert "P05" in section
    assert "P09" in section


def test_opponents_section_handles_empty():
    section = build_opponents_section(_visible_state(alive_player_ids=[]))
    assert "P0" not in section


def test_action_prompt_declares_action_type_key_and_examples():
    prompt = build_action_prompt()
    assert "action_type" in prompt
    for action_type in IMPLEMENTED_ACTION_TYPES:
        assert f'"{action_type}"' in prompt
    # 未実装のアクション種はプロンプトに出さない（課金・ターンの無駄になるため）
    for unimplemented in ("dm", "broadcast", "trade_propose", "contract_propose", "bounty_post"):
        assert f'"{unimplemented}"' not in prompt


def test_action_prompt_example_is_valid_json_with_required_fields():
    prompt = build_action_prompt()
    example_line = next(line for line in prompt.splitlines() if line.startswith("例（"))
    example_json = example_line.split(": ", 1)[1]
    data = json.loads(example_json)
    action_type = data["action_type"]
    for field in REQUIRED_FIELDS_BY_ACTION_TYPE[action_type]:
        assert field in data


def test_board_section_shows_all_three_hands():
    section = build_board_section({"ROCK": 3, "SCISSORS": 1, "PAPER": 2})
    assert "3枚" in section
    assert "1枚" in section
    assert "2枚" in section
