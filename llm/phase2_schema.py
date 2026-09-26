"""
LLM応答のStructured Outputスキーマと静的検証（§5.2のアクション空間）

dangou-cardのphase2_schema.pyと同じ設計思想: 各providerのstructured output
モードはネストした判別可能union（Pydanticの discriminator）をそのまま渡せない
ことが多いため、フラットな1オブジェクト＋action_typeキーで表現し、
response_parser.py 側で engine.models.Action の各サブクラスへ再構成する。
"""

from __future__ import annotations

from typing import Any

EMOTIONS = ["喜", "怒", "哀", "楽", "焦", "疑", "奸"]
"""dangou-cardと同じ7感情セット（表情画像アセットを流用するため語彙を揃える）"""

ACTION_TYPES = [
    "pass", "wait", "dm", "broadcast", "anonymous_broadcast", "transfer", "repay",
    "match_offer", "match_accept", "match_decline", "match_withdraw",
    "trade_propose", "trade_accept", "trade_reject", "trade_withdraw",
    "contract_propose", "contract_sign", "contract_cancel",
    "bounty_post", "bounty_cancel", "exit",
]
"""§5.2 のアクション一覧（engine.models.Action の各Literal["type"]と1対1対応）"""

HAND_VALUES = ["ROCK", "SCISSORS", "PAPER"]

OBLIGATION_TYPES = ["TYPE_A", "TYPE_B", "TYPE_C", "TYPE_D"]
"""§7.2の契約4型"""

TYPE_B_KINDS = ["specified_hand", "match_prohibition", "exit_prohibition"]
"""§7.3の型B内容3種"""

TYPE_C_CONDITIONS = ["match_result", "player_status", "star_threshold"]
"""§7.4の型C条件3種"""


def build_phase2_response_schema() -> dict[str, Any]:
    """
    provider非依存の正準スキーマを返す

    フラットな1オブジェクト。action_typeで意味が変わるフィールドは全てoptional
    にし、response_parser.py側でaction_typeごとに必須項目を検証する
    （providerのJSON Schema機能だけでは判別可能unionを表現しきれないため）。
    """
    asset_offer = {
        "type": "object",
        "properties": {
            "card_ids": {"type": "array", "items": {"type": "string"}},
            "stars": {"type": "integer"},
            "cash": {"type": "integer"},
        },
        "additionalProperties": False,
    }
    obligation = {
        "type": "object",
        "properties": {
            "obligor_id": {"type": "string"},
            "obligation_type": {"type": "string", "enum": OBLIGATION_TYPES},
            "details": {"type": "object"},
        },
        "required": ["obligor_id", "obligation_type", "details"],
        "additionalProperties": False,
    }
    return {
        "type": "object",
        "properties": {
            "emotion": {"type": "string", "enum": EMOTIONS},
            "reasoning": {"type": "string"},
            "memory": {"type": "string"},
            "action_type": {"type": "string", "enum": ACTION_TYPES},
            "to": {"type": "string"},
            "message": {"type": "string"},
            "amount": {"type": "integer"},
            "opponent_id": {"type": "string"},
            "hand": {"type": "string", "enum": HAND_VALUES},
            "card_id": {"type": "string"},
            "offer_id": {"type": "string"},
            "target_id": {"type": "string"},
            "give": asset_offer,
            "receive": asset_offer,
            "trade_id": {"type": "string"},
            "party_ids": {"type": "array", "items": {"type": "string"}},
            "obligations": {"type": "array", "items": obligation},
            "contract_id": {"type": "string"},
            "condition": {"type": "object"},
            "reward": {"type": "integer"},
            "anonymous": {"type": "boolean"},
            "bounty_id": {"type": "string"},
            "until_turn": {"type": "integer"},
            "wake_on_event": {"type": "boolean"},
        },
        "required": ["action_type"],
        "additionalProperties": False,
    }


IMPLEMENTED_ACTION_TYPES = (
    "pass", "wait", "repay", "transfer",
    "match_offer", "match_accept", "match_decline", "match_withdraw",
    "exit",
    "dm", "broadcast", "anonymous_broadcast",
    "trade_propose", "trade_accept", "trade_reject", "trade_withdraw",
)
"""
engine/game.py::_apply_actionが実処理するアクション種のみ。

contract_*/bounty_* はまだACTION_UNHANDLED（素通り）なので、LLMに選ばせても
課金とターンの無駄になるだけである。llm/prompt_builder.py::build_action_prompt()
はこの集合だけを提示する（契約の本実装が入るサイクルでここを拡張する）。

dm/broadcast/anonymous_broadcast はサイクル1.9、trade_*はサイクル2.0で追加。
"""

# --- action_type ごとの必須フィールド（response_parser.py が参照する） ---
REQUIRED_FIELDS_BY_ACTION_TYPE: dict[str, tuple[str, ...]] = {
    "pass": (),
    "wait": (),
    "dm": ("to", "message"),
    "broadcast": ("message",),
    "anonymous_broadcast": ("message",),
    "transfer": ("to", "amount"),
    "repay": ("amount",),
    "match_offer": ("opponent_id", "hand", "card_id"),
    "match_accept": ("offer_id", "hand", "card_id"),
    "match_decline": ("offer_id",),
    "match_withdraw": ("offer_id",),
    "trade_propose": ("target_id", "give", "receive"),
    "trade_accept": ("trade_id",),
    "trade_reject": ("trade_id",),
    "trade_withdraw": ("trade_id",),
    "contract_propose": ("party_ids", "obligations"),
    "contract_sign": ("contract_id",),
    "contract_cancel": ("contract_id",),
    "bounty_post": ("condition", "reward"),
    "bounty_cancel": ("bounty_id",),
    "exit": (),
}
