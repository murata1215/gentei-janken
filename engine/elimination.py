"""
脱落・強制清算モジュール（§6.3/§6.4）

★0による強制退場（§6.3）とT120時間切れ（§6.4）は同じ清算処理を使う。
清算処理は仕様書上「清算は談合カードv0.5 §1.6の強制清算と同じとする」と
指定されており、本モジュールはそのロジックを移植する。
"""

from typing import Any

from engine import player as player_ops
from engine.models import Contract, EliminationType, PlayerState


def forced_liquidation(
    player: PlayerState, elimination_type: EliminationType, turn: int,
    contracts: list[Contract],
) -> tuple[PlayerState, list[Contract], dict[str, Any]]:
    """
    脱落時強制清算を実行する（§6.3、dangou-card v0.5 §1.6を移植）

    処理順:
    1. 現金を借金返済へ自動充当: 返済額 = min(現金, 借金残高)
    2. 残債は貸倒れとして記録（帳簿上は消滅。誰かに請求されない）
    3. 返済後に残った現金はシステムへ没収（他プレイヤーへは分配しない、§6.3）
    4. 未使用カードは消滅（掲示板の残数からも差し引かれる。board_counts()は
       is_alive=Falseのプレイヤーを合計しないため自動的に反映される）
    5. 残っている★も没収する（時間切れ脱落者は★>0の可能性があるため。
       「他プレイヤーへは分配しない」の原則を★にも適用し、ゼロサム台帳の
       整合性を保つ。rules/project.md「★はゼロサム資産」参照）
    6. 脱落状態にする
    7. 未履行義務を義務単位で失効させる

    Args:
        player: 脱落するプレイヤーの状態
        elimination_type: "FORCED_EXIT"（★0） または "TIMEOUT"（§6.4）
        turn: 脱落が確定したターン番号
        contracts: 全契約リスト（義務失効を反映するため）

    Returns:
        (更新されたPlayerState, 更新された契約リスト, 清算記録dict)
    """
    record: dict[str, Any] = {
        "player_id": player.player_id,
        "elimination_type": elimination_type,
        "turn": turn,
        "cash_before": player.cash,
        "debt_before": player.debt,
        "stars_before": player.stars,
    }

    # --- Step 1: 借金返済 ---
    repayment = min(player.cash, player.debt)
    p = player.model_copy(update={
        "cash": player.cash - repayment,
        "debt": player.debt - repayment,
    })
    record["debt_repaid"] = repayment

    # --- Step 2: 貸倒れ ---
    record["bad_debt"] = p.debt

    # --- Step 3: 残金没収、Step 4: カード消滅、Step 5: ★没収 ---
    record["cash_confiscated"] = p.cash
    record["cards_destroyed"] = len(p.cards)
    record["stars_confiscated"] = p.stars
    p = p.model_copy(update={
        "cash": 0, "debt": 0, "cards": [], "reserved_card_ids": [], "stars": 0,
    })

    # --- Step 6: 脱落状態にする ---
    p = player_ops.eliminate(p, elimination_type, turn)

    # --- Step 7: 義務失効 ---
    updated_contracts = expire_obligations_for_player(p.player_id, contracts)

    return p, updated_contracts, record


def expire_obligations_for_player(player_id: str, contracts: list[Contract]) -> list[Contract]:
    """
    脱落者に関連する未履行義務を失効させる

    - 脱落者が義務者(obligor_id)である未履行義務のみ失効させる
    - 脱落者を当事者に含む署名待ち(pending)契約は cancelled へ遷移する
      （署名が永久に揃わない状態を防ぐ）
    """
    updated: list[Contract] = []
    for contract in contracts:
        if contract.status == "pending" and player_id in contract.party_ids:
            updated.append(contract.model_copy(update={"status": "cancelled"}))
            continue
        new_obligations = [
            ob.model_copy(update={"status": "expired"})
            if ob.status == "pending" and ob.obligor_id == player_id
            else ob
            for ob in contract.obligations
        ]
        updated.append(contract.model_copy(update={"obligations": new_obligations}))
    return updated


def players_to_force_exit(players: list[PlayerState]) -> list[str]:
    """★が0個になった生存プレイヤーのIDを返す（§6.3の判定対象）"""
    return [p.player_id for p in players if p.is_alive and p.stars <= 0]


def players_to_timeout(players: list[PlayerState]) -> list[str]:
    """T120終了時に場に残っている（is_alive=True）プレイヤーのIDを返す（§6.4）"""
    return [p.player_id for p in players if p.is_alive]
