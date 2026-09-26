"""
レスポンス解析モジュール

LLMのレスポンスからJSONを抽出し、engine/models.pyのAction型に変換する。
不正時は是正指示メッセージを生成する（リトライ用）。

extract_json() / ParseError / make_correction_message() / 感情まわりは
dangou-card から汎用部分をそのまま移植（json抽出ロジック自体はゲーム非依存）。
Action変換（_convert_action）は限定ジャンケンの§5.2アクション空間に対応する
新規実装。
"""

import json
import logging
import re
from typing import Any

from pydantic import ValidationError

from engine.models import (
    Action, AnonymousBroadcastAction, AssetOffer, BountyCancelAction, BountyPostAction,
    BroadcastAction, ContractCancelAction, ContractProposeAction, ContractSignAction,
    DmAction, ExitAction, Hand, MatchAcceptAction, MatchDeclineAction, MatchOfferAction,
    MatchWithdrawAction, PassAction, RepayAction, TradeAcceptAction, TradeProposeAction,
    TradeRejectAction, TradeWithdrawAction, TransferAction, WaitAction,
)
from llm.phase2_schema import REQUIRED_FIELDS_BY_ACTION_TYPE

logger = logging.getLogger(__name__)

VALID_EMOTIONS = {"喜", "怒", "哀", "楽", "焦", "疑", "奸"}


class ParseError(Exception):
    """JSON解析エラー（是正メッセージ付き）"""

    def __init__(self, message: str, correction_hint: str):
        super().__init__(message)
        self.correction_hint = correction_hint


def extract_json(text: str) -> dict[str, Any] | None:
    """
    レスポンスからJSONオブジェクトを抽出する（dangou-cardから移植、ゲーム非依存）

    対応パターン:
    1. ```json ... ``` 完全なコードブロック
    1b. ```json ... （閉じフェンスなし=truncated response）
    2. { で始まる生JSON
    3. テキスト中の最初の { ... } ペア
    """
    m = re.search(r'```(?:json)?\s*\n?(.*?)\n?```', text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1).strip())
        except json.JSONDecodeError:
            pass

    m = re.search(r'```(?:json)?\s*\n?(.+)', text, re.DOTALL)
    if m:
        candidate = m.group(1).strip()
        depth = 0
        last_close = -1
        for i, ch in enumerate(candidate):
            if ch == '{':
                depth += 1
            elif ch == '}':
                depth -= 1
                if depth == 0:
                    last_close = i
        if last_close >= 0:
            try:
                return json.loads(candidate[:last_close + 1])
            except json.JSONDecodeError:
                pass

    stripped = text.strip()
    if stripped.startswith("{"):
        try:
            return json.loads(stripped)
        except json.JSONDecodeError:
            pass

    start = text.find("{")
    if start >= 0:
        depth = 0
        for i in range(start, len(text)):
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(text[start:i + 1])
                    except json.JSONDecodeError:
                        break

    return None


def normalize_emotion(strategy: dict[str, Any]) -> dict[str, Any]:
    """emotionフィールドが未指定/不正なら削除する（dangou-cardと同じ寛容な扱い）"""
    emotion = strategy.get("emotion")
    if emotion not in VALID_EMOTIONS:
        strategy.pop("emotion", None)
    return strategy


def extract_reasoning_and_emotion(text: str) -> tuple[str | None, str | None]:
    """
    LLM応答からreasoning/emotionだけを取り出す（god専用ログ用、CoT秘匿）

    rules/project.md「CoT reasoningフィールドは秘匿情報」に基づき、この関数の
    戻り値は llm/llm_agent.py 経由で llm/llm_logger.py（神視点のみ閲覧可能な
    JSONLログ）にのみ渡すこと。engine.models.Action にはreasoning/emotion用の
    フィールドが存在しないため、parse_action() が返すActionには決して混入しない
    （可視状態・イベント・他プレイヤー向けプロンプトに現れないことは構造的に保証される）。
    """
    data = extract_json(text)
    if data is None:
        return None, None
    reasoning = data.get("reasoning")
    if not isinstance(reasoning, str) or not reasoning.strip():
        reasoning = None
    normalized = normalize_emotion(dict(data))
    emotion = normalized.get("emotion")
    return reasoning, emotion


def make_correction_message(error: ParseError) -> str:
    """リトライ用の是正指示メッセージを生成する"""
    return (
        f"前回の回答にエラーがありました: {error}\n"
        f"修正してください: {error.correction_hint}"
    )


LENGTH_TRUNCATION_HINT = (
    "【重要】前回の回答は出力トークン上限に達し途中で切断されました。"
    "思考・分析を大幅に短縮し、必ずJSON出力を最後まで完了してください。"
    "長い説明は不要です。JSONのみ返してください。"
)


def parse_action(text: str, player_id: str) -> Action:
    """
    LLM応答テキストから1つのActionを構成する（§5.2）

    Args:
        text: LLMの生応答テキスト
        player_id: 応答したプレイヤーのID（Actionのplayer_idに補う）

    Returns:
        engine.models.Action のいずれか

    Raises:
        ParseError: JSON抽出失敗、action_type不正、必須フィールド欠落の場合
    """
    data = extract_json(text)
    if data is None:
        raise ParseError(
            "レスポンスからJSONを抽出できませんでした",
            "JSON形式で応答してください（```json ... ``` または生JSON）。",
        )
    return _convert_action(data, player_id)


def _convert_action(data: dict[str, Any], player_id: str) -> Action:
    action_type = data.get("action_type")
    if action_type not in REQUIRED_FIELDS_BY_ACTION_TYPE:
        raise ParseError(
            f"不明なaction_type: {action_type!r}",
            f"action_typeは次のいずれかにしてください: {', '.join(REQUIRED_FIELDS_BY_ACTION_TYPE)}",
        )
    missing = [f for f in REQUIRED_FIELDS_BY_ACTION_TYPE[action_type] if data.get(f) is None]
    if missing:
        raise ParseError(
            f"action_type={action_type!r} に必須のフィールドが不足: {missing}",
            f"次のフィールドを含めてください: {missing}",
        )

    try:
        return _dispatch_action(action_type, data, player_id)
    except ParseError:
        raise
    except (ValueError, TypeError, KeyError, ValidationError) as e:
        # int()/dict()/list()の型変換失敗やpydanticのValidationErrorはここで
        # ParseErrorに変換し、呼び出し元（llm_agent.py）のリトライに乗せる。
        # ここを通さずに素通りすると1回の不正な応答で試合全体が落ちる
        # （dry_run未検出だった実害: amountが文字列、toがlist等）。
        raise ParseError(
            f"action_type={action_type!r} のフィールド値が不正です: {e}",
            "各フィールドの型・値を仕様に合わせて修正してください"
            "（例: amountは整数、to/card_id/offer_idは文字列）。",
        ) from e


def _dispatch_action(action_type: str, data: dict[str, Any], player_id: str) -> Action:
    if action_type == "pass":
        return PassAction(player_id=player_id)
    if action_type == "wait":
        until_turn = data.get("until_turn")
        wake_on_event = bool(data.get("wake_on_event", False))
        if until_turn is None and not wake_on_event:
            # 実測で発見した実害: どちらも指定しない待機はengine/game.py::_should_wake()
            # がT120まで一度も真にならず、そのプレイヤーが以後一切行動できなくなる
            # （dry_run/LLMスモークで実際に発生: P01が"wait"だけ返し、以後届いた
            # 対戦申込3件すべてを一度も受け取れなかった）。§5.2は「T45まで待つ」
            # または「イベントが届いたら起こして」のどちらかを宣言する行動として
            # 定義しているため、どちらも無い場合は不正な入力としてリトライさせる。
            raise ValueError(
                "waitはuntil_turn（整数）またはwake_on_event=trueのどちらかを"
                "指定する必要があります（両方省略すると二度と行動できなくなります）"
            )
        return WaitAction(player_id=player_id, until_turn=until_turn, wake_on_event=wake_on_event)
    if action_type == "dm":
        return DmAction(player_id=player_id, to=data["to"], message=data["message"])
    if action_type == "broadcast":
        return BroadcastAction(player_id=player_id, message=data["message"])
    if action_type == "anonymous_broadcast":
        return AnonymousBroadcastAction(player_id=player_id, message=data["message"])
    if action_type == "transfer":
        return TransferAction(player_id=player_id, to=data["to"], amount=int(data["amount"]))
    if action_type == "repay":
        return RepayAction(player_id=player_id, amount=int(data["amount"]))
    if action_type == "match_offer":
        return MatchOfferAction(
            player_id=player_id, opponent_id=data["opponent_id"],
            hand=_parse_hand(data["hand"]), card_id=data["card_id"],
        )
    if action_type == "match_accept":
        return MatchAcceptAction(
            player_id=player_id, offer_id=data["offer_id"],
            hand=_parse_hand(data["hand"]), card_id=data["card_id"],
        )
    if action_type == "match_decline":
        return MatchDeclineAction(player_id=player_id, offer_id=data["offer_id"])
    if action_type == "match_withdraw":
        return MatchWithdrawAction(player_id=player_id, offer_id=data["offer_id"])
    if action_type == "trade_propose":
        return TradeProposeAction(
            player_id=player_id, target_id=data["target_id"],
            give=_parse_asset_offer(data["give"]), receive=_parse_asset_offer(data["receive"]),
        )
    if action_type == "trade_accept":
        return TradeAcceptAction(player_id=player_id, trade_id=data["trade_id"])
    if action_type == "trade_reject":
        return TradeRejectAction(player_id=player_id, trade_id=data["trade_id"])
    if action_type == "trade_withdraw":
        return TradeWithdrawAction(player_id=player_id, trade_id=data["trade_id"])
    if action_type == "contract_propose":
        return ContractProposeAction(
            player_id=player_id, party_ids=list(data["party_ids"]),
            obligations=list(data["obligations"]),
        )
    if action_type == "contract_sign":
        return ContractSignAction(player_id=player_id, contract_id=data["contract_id"])
    if action_type == "contract_cancel":
        return ContractCancelAction(player_id=player_id, contract_id=data["contract_id"])
    if action_type == "bounty_post":
        return BountyPostAction(
            player_id=player_id, condition=dict(data["condition"]),
            reward=int(data["reward"]), anonymous=bool(data.get("anonymous", False)),
        )
    if action_type == "bounty_cancel":
        return BountyCancelAction(player_id=player_id, bounty_id=data["bounty_id"])
    if action_type == "exit":
        return ExitAction(player_id=player_id)

    # REQUIRED_FIELDS_BY_ACTION_TYPE に登録済みなのにここに到達するのはコードの不整合
    raise ParseError(f"action_type={action_type!r} の変換が未実装です", "サポート外のaction_typeです。")


def _parse_hand(value: Any) -> Hand:
    try:
        return Hand(value)
    except ValueError:
        raise ParseError(
            f"不正なhand: {value!r}",
            "handはROCK/SCISSORS/PAPERのいずれかにしてください。",
        )


def _parse_asset_offer(value: Any) -> AssetOffer:
    if not isinstance(value, dict):
        raise ParseError("give/receiveはオブジェクトである必要があります", "give/receiveはオブジェクト形式にしてください。")
    return AssetOffer(
        card_ids=list(value.get("card_ids", [])),
        stars=int(value.get("stars", 0)),
        cash=int(value.get("cash", 0)),
    )
