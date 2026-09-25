"""強制清算のテスト（§6.3/§6.4）"""

from engine.elimination import (
    expire_obligations_for_player, forced_liquidation,
    players_to_force_exit, players_to_timeout,
)
from engine.models import Contract, Obligation
from tests.conftest import make_player


def test_forced_liquidation_repays_debt_from_cash():
    p = make_player("P01", cash=300_000, debt=1_000_000, stars=0)
    updated, contracts, record = forced_liquidation(p, "FORCED_EXIT", turn=10, contracts=[])
    assert record["debt_repaid"] == 300_000
    assert record["bad_debt"] == 700_000
    assert updated.cash == 0
    assert updated.debt == 0


def test_forced_liquidation_confiscates_remaining_cash():
    p = make_player("P01", cash=2_000_000, debt=500_000, stars=0)
    updated, contracts, record = forced_liquidation(p, "FORCED_EXIT", turn=10, contracts=[])
    assert record["cash_confiscated"] == 1_500_000  # 返済後の残り
    assert updated.cash == 0


def test_forced_liquidation_destroys_cards():
    p = make_player("P01", stars=0)
    assert len(p.cards) > 0
    updated, contracts, record = forced_liquidation(p, "FORCED_EXIT", turn=10, contracts=[])
    assert updated.cards == []
    assert updated.reserved_card_ids == []


def test_forced_liquidation_marks_eliminated():
    p = make_player("P01", stars=0)
    updated, contracts, record = forced_liquidation(p, "FORCED_EXIT", turn=10, contracts=[])
    assert updated.is_alive is False
    assert updated.elimination_type == "FORCED_EXIT"
    assert updated.elimination_turn == 10
    assert updated.has_exited is False  # 脱落は生還(退出)ではない


def test_players_to_force_exit_detects_zero_stars():
    alive_zero = make_player("P01", stars=0)
    alive_positive = make_player("P02", stars=1)
    dead = make_player("P03", stars=0, is_alive=False)
    ids = players_to_force_exit([alive_zero, alive_positive, dead])
    assert ids == ["P01"]


def test_players_to_timeout_returns_all_alive():
    alive1 = make_player("P01")
    alive2 = make_player("P02")
    exited = make_player("P03", is_alive=False)
    ids = players_to_timeout([alive1, alive2, exited])
    assert set(ids) == {"P01", "P02"}


def test_expire_obligations_for_player_marks_pending_expired():
    ob = Obligation(obligation_id="C1_OB1", obligor_id="P01",
                     obligation_type="TYPE_A", details={}, status="pending")
    contract = Contract(contract_id="C1", proposer_id="P02", party_ids=["P01", "P02"],
                         obligations=[ob], status="active", turn_created=1)
    updated = expire_obligations_for_player("P01", [contract])
    assert updated[0].obligations[0].status == "expired"


def test_expire_obligations_cancels_pending_contract_with_eliminated_party():
    contract = Contract(contract_id="C1", proposer_id="P01", party_ids=["P01", "P02"],
                         obligations=[], status="pending", turn_created=1)
    updated = expire_obligations_for_player("P01", [contract])
    assert updated[0].status == "cancelled"
