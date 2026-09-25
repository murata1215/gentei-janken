"""
正式契約モジュール（§7.2〜§7.4）

型A（指定ターンの金銭支払い）・型B（行動の指定、§7.3）・型C（条件付き金銭支払い、
§7.4）・型D（指定ターンのカード/★の引き渡し、新設）を扱う。

本サイクル（歩く骨格）では契約の「作成」までを実装し、執行・監査
（型Aの自動執行、型Bの照合、型Cの条件評価、型Dの引き渡し）は次サイクルに回す。
engine/game.py のターンループも本サイクルでは §5.1 ステップ5（契約の執行と監査）
を素通りする（TODO コメント参照）。
"""

from typing import Any

from engine.models import Contract, Obligation, ObligationType

VALID_TYPE_B_KINDS = {"specified_hand", "match_prohibition", "exit_prohibition"}
"""型Bの内容3種（§7.3: 1.手の指定 2.対戦の禁止 3.退出の禁止）"""

VALID_TYPE_C_CONDITIONS = {"match_result", "player_status", "star_threshold"}
"""型Cの条件3種（§7.4: 対戦結果 / 強制退場・時間切れ・退出 / ★の閾値）"""


def normalize_obligation(obligor_id: str, obligation_type: str, details: dict[str, Any],
                          obligation_id: str) -> Obligation:
    """
    義務1件を正規化して Obligation を組み立てる

    LLMが送る details のキー表記ゆれをここで一箇所に集約して吸収する
    （dangou-cardの normalize_type_b_card_details() と同じ設計思想。
    TODO: 型B/C/D それぞれの details キー正規化・検証は次サイクルで実装する）。

    Args:
        obligor_id: 義務者のプレイヤーID
        obligation_type: "TYPE_A" / "TYPE_B" / "TYPE_C" / "TYPE_D"
        details: 型ごとの詳細（未検証のまま格納。検証は次サイクル）
        obligation_id: 契約内で一意な義務ID

    Returns:
        正規化されたObligation（status="pending"）

    Raises:
        ValueError: obligation_type が不正な場合
    """
    if obligation_type not in ObligationType.__members__:
        raise ValueError(
            f"Invalid obligation_type: {obligation_type!r} "
            f"(valid: {', '.join(ObligationType.__members__)})"
        )
    return Obligation(
        obligation_id=obligation_id,
        obligor_id=obligor_id,
        obligation_type=ObligationType[obligation_type],
        details=dict(details),
        status="pending",
    )


def create_contract(
    contract_id: str, proposer_id: str, party_ids: list[str],
    raw_obligations: list[dict[str, Any]], turn: int,
) -> Contract:
    """
    契約を作成する（§7.2）

    発行料（config.contract_fee）の徴収は呼び出し側（engine/game.py）の責務
    （§7.2: 提案者負担。他の即時決済と同じ扱いにするため）。

    Args:
        contract_id: 契約ID
        proposer_id: 提案者（発行料の負担者）
        party_ids: 当事者プレイヤーIDのリスト（proposer_idを含む）
        raw_obligations: [{"obligor_id": ..., "obligation_type": ..., "details": {...}}, ...]
        turn: 提案されたターン番号

    Returns:
        status="pending"（署名待ち）のContract

    Raises:
        ValueError: obligation_type が不正な場合
    """
    obligations = [
        normalize_obligation(
            obligor_id=raw["obligor_id"],
            obligation_type=raw["obligation_type"],
            details=raw.get("details", {}),
            obligation_id=f"{contract_id}_OB{i + 1}",
        )
        for i, raw in enumerate(raw_obligations)
    ]
    return Contract(
        contract_id=contract_id,
        proposer_id=proposer_id,
        party_ids=list(party_ids),
        obligations=obligations,
        status="pending",
        turn_created=turn,
    )


# TODO（次サイクル）:
# - sign_contract(): 全当事者の署名が揃ったら status を "active" に遷移
# - audit_type_a() / audit_type_b() / evaluate_type_c() / audit_type_d(): §5.1 ステップ5の
#   「期限が来た型A・型C・型Dを執行し、型Bを照合する」を実装する
# - cancel_contract(): 全当事者合意による解除（ContractCancelAction）
