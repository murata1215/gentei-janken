"""正式契約モジュールのテスト（§7.2、骨格部分のみ）"""

import pytest

from engine.contracts import create_contract, normalize_obligation


def test_normalize_obligation_builds_pending_obligation():
    ob = normalize_obligation("P01", "TYPE_A", {"amount": 100_000, "turn": 30}, "C1_OB1")
    assert ob.obligor_id == "P01"
    assert ob.obligation_type.value == "TYPE_A"
    assert ob.status == "pending"
    assert ob.details == {"amount": 100_000, "turn": 30}


def test_normalize_obligation_rejects_invalid_type():
    with pytest.raises(ValueError):
        normalize_obligation("P01", "TYPE_Z", {}, "C1_OB1")


def test_create_contract_assigns_obligation_ids():
    raw = [
        {"obligor_id": "P01", "obligation_type": "TYPE_B", "details": {"kind": "specified_hand"}},
        {"obligor_id": "P02", "obligation_type": "TYPE_D", "details": {"turn": 40}},
    ]
    contract = create_contract("C1", "P01", ["P01", "P02"], raw, turn=5)
    assert contract.status == "pending"
    assert contract.turn_created == 5
    assert [ob.obligation_id for ob in contract.obligations] == ["C1_OB1", "C1_OB2"]
    assert contract.obligations[0].obligor_id == "P01"
    assert contract.obligations[1].obligor_id == "P02"
