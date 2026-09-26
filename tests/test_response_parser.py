"""
llm/response_parser.py のテスト

サイクル1.0の実害（response_parser内のint()/dict()/list()やpydanticの
ValidationErrorがParseError以外の形で漏れ、1回の不正応答で試合全体が落ちる）
の再発防止線。extract_json()の4分岐と_convert_action()の異常系を検証する。
"""

import pytest

from engine.models import DmAction, MatchOfferAction, PassAction, RepayAction, TransferAction
from llm.response_parser import ParseError, extract_json, extract_reasoning_and_emotion, parse_action


# --- extract_json(): dangou-cardから移植した4分岐 ---

def test_extract_json_from_closed_code_fence():
    text = '前置きの説明\n```json\n{"action_type": "pass"}\n```\n後書き'
    assert extract_json(text) == {"action_type": "pass"}


def test_extract_json_from_unclosed_code_fence_truncated():
    text = '```json\n{"action_type": "pass", "note": "truncated'
    # 閉じフェンスがない（トークン上限で切断された）場合は抽出できないのが正しい
    # （JSONとして不完全なので、無理にパースしてはいけない）
    assert extract_json(text) is None


def test_extract_json_from_raw_json_start():
    text = '{"action_type": "pass"}'
    assert extract_json(text) == {"action_type": "pass"}


def test_extract_json_from_embedded_braces():
    text = 'こう考えました。{"action_type": "pass"} 以上です。'
    assert extract_json(text) == {"action_type": "pass"}


def test_extract_json_returns_none_for_no_json():
    assert extract_json("何もありません") is None


# --- parse_action(): 正常系 ---

def test_parse_action_pass():
    action = parse_action('{"action_type": "pass"}', "P01")
    assert isinstance(action, PassAction)
    assert action.player_id == "P01"


def test_parse_action_match_offer():
    text = '{"action_type": "match_offer", "opponent_id": "P02", "hand": "ROCK", "card_id": "P01_ROCK_1"}'
    action = parse_action(text, "P01")
    assert isinstance(action, MatchOfferAction)
    assert action.opponent_id == "P02"
    assert action.card_id == "P01_ROCK_1"


# --- parse_action(): 異常系（ParseErrorに正しく変換されること） ---

def test_unknown_action_type_raises_parse_error():
    with pytest.raises(ParseError):
        parse_action('{"action_type": "fly_to_moon"}', "P01")


def test_missing_required_field_raises_parse_error():
    with pytest.raises(ParseError):
        parse_action('{"action_type": "match_offer", "opponent_id": "P02"}', "P01")


def test_string_amount_raises_parse_error_not_value_error():
    """amountが数値化できない文字列でもParseErrorに変換される（int()の生ValueErrorが漏れない）"""
    text = '{"action_type": "repay", "amount": "たくさん"}'
    with pytest.raises(ParseError):
        parse_action(text, "P01")


def test_list_to_field_raises_parse_error_not_validation_error():
    """toがlistでもParseErrorに変換される（pydanticの生ValidationErrorが漏れない）"""
    text = '{"action_type": "dm", "to": ["P02", "P03"], "message": "hi"}'
    with pytest.raises(ParseError):
        parse_action(text, "P01")


def test_invalid_hand_raises_parse_error():
    text = '{"action_type": "match_offer", "opponent_id": "P02", "hand": "LIZARD", "card_id": "c1"}'
    with pytest.raises(ParseError):
        parse_action(text, "P01")


def test_wait_without_any_wake_condition_raises_parse_error():
    """
    実測で発見した実害の再発防止線: LLMがuntil_turn/wake_on_eventのどちらも
    指定しない"wait"を返すと、そのプレイヤーはT120まで二度と行動できなくなる
    （engine/game.py::_should_wake()が永久にFalseを返すため）。§5.2はwaitを
    「T45まで待つ」または「イベントが届いたら起こして」のどちらかを宣言する
    行動と定義しているため、どちらも無い場合はParseErrorでリトライさせる。
    """
    with pytest.raises(ParseError):
        parse_action('{"action_type": "wait"}', "P01")
    with pytest.raises(ParseError):
        parse_action('{"action_type": "wait", "wake_on_event": false}', "P01")


def test_wait_with_until_turn_only_is_valid():
    from engine.models import WaitAction
    action = parse_action('{"action_type": "wait", "until_turn": 45}', "P01")
    assert isinstance(action, WaitAction)
    assert action.until_turn == 45


def test_wait_with_wake_on_event_only_is_valid():
    from engine.models import WaitAction
    action = parse_action('{"action_type": "wait", "wake_on_event": true}', "P01")
    assert isinstance(action, WaitAction)
    assert action.wake_on_event is True


def test_non_dict_give_raises_parse_error():
    text = '{"action_type": "trade_propose", "target_id": "P02", "give": "全部", "receive": {}}'
    with pytest.raises(ParseError):
        parse_action(text, "P01")


def test_transfer_with_string_amount_raises_parse_error():
    text = '{"action_type": "transfer", "to": "P02", "amount": "300000円"}'
    with pytest.raises(ParseError):
        parse_action(text, "P01")


def test_valid_transfer_still_parses_after_defensive_wrapping():
    """異常系の防御を追加しても正常系のtransferは壊れていないことの確認"""
    text = '{"action_type": "transfer", "to": "P02", "amount": 300000}'
    action = parse_action(text, "P01")
    assert isinstance(action, TransferAction)
    assert action.amount == 300000


# --- extract_reasoning_and_emotion(): CoT秘匿の入口（god専用ログにのみ渡す） ---

def test_extract_reasoning_and_emotion_returns_both():
    text = '{"action_type": "pass", "reasoning": "様子を見る", "emotion": "疑"}'
    reasoning, emotion = extract_reasoning_and_emotion(text)
    assert reasoning == "様子を見る"
    assert emotion == "疑"


def test_extract_reasoning_and_emotion_none_when_absent():
    text = '{"action_type": "pass"}'
    reasoning, emotion = extract_reasoning_and_emotion(text)
    assert reasoning is None
    assert emotion is None


def test_extract_reasoning_and_emotion_invalid_emotion_dropped():
    text = '{"action_type": "pass", "emotion": "不明な感情"}'
    _, emotion = extract_reasoning_and_emotion(text)
    assert emotion is None


def test_extract_reasoning_and_emotion_handles_unparsable_text():
    reasoning, emotion = extract_reasoning_and_emotion("JSONではない文章")
    assert reasoning is None
    assert emotion is None


def test_reasoning_never_reaches_the_action_object():
    """reasoning/emotionはAction本体には一切乗らない（CoT秘匿、rules/project.md）"""
    text = '{"action_type": "repay", "amount": 100000, "reasoning": "内心の理由", "emotion": "焦"}'
    action = parse_action(text, "P01")
    assert isinstance(action, RepayAction)
    dumped = action.model_dump()
    assert "reasoning" not in dumped
    assert "emotion" not in dumped
    assert "内心の理由" not in str(dumped)
