"""
viewer/log_parser.py の reason サニタイズのテスト（サイクル1.6.1の実害の再発防止線）

サイクル1.6.1の実害: `MATCH_ACCEPT_REJECTED`/`MATCH_OFFER_REJECTED` の `reason` に
`str(ValueError)` がそのまま入っており、本番ログに
`"reason": "P18 already has card P18_PAPER_1 reserved"` が42件存在した。
card_id（＝手の種類）が§8.2秘匿情報として view=public から漏れていた。

`reason` は複数イベント種別でキーとしてはpublic許可だが、値は自由文字列を
許してはならない（PUBLIC_REASON_CODESホワイトリストで塞ぐ）。
"""

import json
import re

import pytest
from fastapi.testclient import TestClient

import viewer.server as server
from viewer.log_parser import PUBLIC_REASON_CODES, _sanitize_reason

CARD_ID_PATTERN = re.compile(r"P\d\d_(ROCK|SCISSORS|PAPER)_\d")


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setattr(server, "LOGS_DIR", tmp_path)
    monkeypatch.setattr(server, "TOKEN", "")
    monkeypatch.setattr(server, "GOD_TOKEN", "secret-god-token")
    monkeypatch.setattr(server, "GOD_PUBLIC", False)
    return TestClient(server.app)


def _write_events(tmp_path, game_id: str, events: list[dict]) -> None:
    path = tmp_path / f"{game_id}_events.jsonl"
    with open(path, "w", encoding="utf-8") as f:
        for e in events:
            e.setdefault("timestamp", "t")
            e.setdefault("phase", "resolve")
            e.setdefault("step", None)
            f.write(json.dumps(e, ensure_ascii=False) + "\n")


# サイクル1.6.1で実ログに存在した実例をそのまま使う
_LEAKY_EVENTS = [
    {"event_type": "GAME_START", "round_num": 0,
     "data": {"num_players": 2, "total_turns": 10, "initial_loans": {"P07": 1_000_000, "P18": 1_000_000}}},
    {"event_type": "MATCH_ACCEPT_REJECTED", "round_num": 20,
     "data": {"player_id": "P18", "offer_id": "M_19_P13_142",
              "reason": "P18 already has card P18_PAPER_1 reserved"}},
    {"event_type": "MATCH_OFFER_REJECTED", "round_num": 5,
     "data": {"player_id": "P07", "reason": "P07 does not have card P07_ROCK_2"}},
    {"event_type": "MATCH_OFFER_REJECTED", "round_num": 6,
     "data": {"player_id": "P07", "reason": "already_has_active_offer"}},
    {"event_type": "MATCH_ACCEPT_REJECTED", "round_num": 7,
     "data": {"player_id": "P18", "offer_id": "M_1_P07_1", "reason": "not_found"}},
    {"event_type": "EXIT_REJECTED", "round_num": 8,
     "data": {"player_id": "P18", "reason": "cards_remaining"}},
]


def test_public_response_has_no_card_id_pattern(client, tmp_path):
    """本番実害の直接ガード: public全文にcard_idパターンが一度も現れない"""
    _write_events(tmp_path, "g1", _LEAKY_EVENTS)
    resp = client.get("/api/games/g1/turns?view=public")
    assert resp.status_code == 200
    assert CARD_ID_PATTERN.search(resp.text) is None


def test_public_reason_drops_unknown_free_text(client, tmp_path):
    _write_events(tmp_path, "g1", _LEAKY_EVENTS)
    body = client.get("/api/games/g1/turns?view=public").json()
    events = [ev for turn in body for ev in turn["events"] if ev["event_type"] == "MATCH_ACCEPT_REJECTED"]
    leaky = next(ev for ev in events if ev["data"].get("offer_id") == "M_19_P13_142")
    assert "reason" not in leaky["data"]


def test_public_reason_drops_unknown_free_text_offer_rejected(client, tmp_path):
    _write_events(tmp_path, "g1", _LEAKY_EVENTS)
    body = client.get("/api/games/g1/turns?view=public").json()
    events = [ev for turn in body for ev in turn["events"] if ev["event_type"] == "MATCH_OFFER_REJECTED"]
    leaky = next(ev for ev in events if ev["round_num"] == 5)  # 自由文字列reasonを持つケース
    assert "reason" not in leaky["data"]


def test_public_reason_keeps_known_code(client, tmp_path):
    _write_events(tmp_path, "g1", _LEAKY_EVENTS)
    body = client.get("/api/games/g1/turns?view=public").json()
    events = [ev for turn in body for ev in turn["events"] if ev["event_type"] == "MATCH_OFFER_REJECTED"]
    coded = next(ev for ev in events if ev["data"].get("reason") == "already_has_active_offer")
    assert coded["data"]["reason"] == "already_has_active_offer"

    accept_events = [ev for turn in body for ev in turn["events"] if ev["event_type"] == "MATCH_ACCEPT_REJECTED"]
    not_found = next(ev for ev in accept_events if ev["data"].get("offer_id") == "M_1_P07_1")
    assert not_found["data"]["reason"] == "not_found"

    exit_events = [ev for turn in body for ev in turn["events"] if ev["event_type"] == "EXIT_REJECTED"]
    assert exit_events[0]["data"]["reason"] == "cards_remaining"


def test_god_view_keeps_free_text_reason(client, tmp_path):
    """god viewでは調査のためreasonの自由文字列も見える（秘匿対象外）"""
    _write_events(tmp_path, "g1", _LEAKY_EVENTS)
    resp = client.get(
        "/api/games/g1/turns?view=god", headers={"X-Viewer-God-Token": "secret-god-token"},
    )
    assert "P18_PAPER_1" in resp.text


def test_sanitize_reason_unit_drops_unknown_value():
    data = {"player_id": "P18", "reason": "P18 already has card P18_PAPER_1 reserved"}
    result = _sanitize_reason(data)
    assert "reason" not in result
    assert result["player_id"] == "P18"


def test_sanitize_reason_unit_keeps_known_code():
    data = {"player_id": "P18", "reason": "not_found"}
    result = _sanitize_reason(data)
    assert result["reason"] == "not_found"


def test_sanitize_reason_unit_noop_without_reason_key():
    data = {"player_id": "P18"}
    assert _sanitize_reason(data) == data


@pytest.mark.parametrize("code", sorted(PUBLIC_REASON_CODES))
def test_all_whitelisted_codes_are_plain_strings_without_ids(code):
    """ホワイトリストの値自体がplayer_id/card_idを含む動的文字列でないことを保証する"""
    assert not re.search(r"P\d\d", code)


# --- サイクル1.9: DM・全体発言・匿名通信のpublic投影テスト ---

_MESSAGE_EVENTS = [
    {"event_type": "GAME_START", "round_num": 0,
     "data": {"num_players": 2, "total_turns": 10, "initial_loans": {"P01": 1_000_000, "P02": 1_000_000}}},
    {"event_type": "DM_SENT", "round_num": 1,
     "data": {"sender": "P01", "to": "P02", "message": "SECRET_DM_BODY_7f3a", "turn": 1}},
    {"event_type": "BROADCAST_SENT", "round_num": 2,
     "data": {"sender": "P01", "message": "PUBLIC_BROADCAST_BODY", "turn": 2}},
    {"event_type": "ANONYMOUS_BROADCAST_SENT", "round_num": 3,
     "data": {"message": "PUBLIC_ANON_BODY", "turn": 3, "sender": "P02"}},
    {"event_type": "DM_REJECTED", "round_num": 4, "data": {"player_id": "P01", "reason": "empty_message"}},
]


def test_dm_sent_public_omits_message_body(client, tmp_path):
    _write_events(tmp_path, "g1", _MESSAGE_EVENTS)
    resp = client.get("/api/games/g1/turns?view=public")
    assert resp.status_code == 200
    assert "SECRET_DM_BODY_7f3a" not in resp.text


def test_dm_sent_public_keeps_sender_and_to(client, tmp_path):
    _write_events(tmp_path, "g1", _MESSAGE_EVENTS)
    body = client.get("/api/games/g1/turns?view=public").json()
    dm = next(ev for turn in body for ev in turn["events"] if ev["event_type"] == "DM_SENT")
    assert dm["data"] == {"sender": "P01", "to": "P02", "turn": 1}


def test_dm_sent_god_view_shows_message_body(client, tmp_path):
    _write_events(tmp_path, "g1", _MESSAGE_EVENTS)
    resp = client.get("/api/games/g1/turns?view=god", headers={"X-Viewer-God-Token": "secret-god-token"})
    assert "SECRET_DM_BODY_7f3a" in resp.text


def test_broadcast_sent_public_shows_message_and_sender(client, tmp_path):
    """全体発言は本文・発信者ともに公開情報（§8.2）"""
    _write_events(tmp_path, "g1", _MESSAGE_EVENTS)
    body = client.get("/api/games/g1/turns?view=public").json()
    bc = next(ev for turn in body for ev in turn["events"] if ev["event_type"] == "BROADCAST_SENT")
    assert bc["data"] == {"sender": "P01", "message": "PUBLIC_BROADCAST_BODY", "turn": 2}


def test_anonymous_broadcast_public_shows_message_but_hides_sender(client, tmp_path):
    """匿名通信は本文は公開・発信者は秘匿（§8.2）"""
    _write_events(tmp_path, "g1", _MESSAGE_EVENTS)
    body = client.get("/api/games/g1/turns?view=public").json()
    anon = next(ev for turn in body for ev in turn["events"] if ev["event_type"] == "ANONYMOUS_BROADCAST_SENT")
    assert anon["data"] == {"message": "PUBLIC_ANON_BODY", "turn": 3}
    assert "sender" not in anon["data"]


def test_anonymous_broadcast_god_view_reveals_sender(client, tmp_path):
    _write_events(tmp_path, "g1", _MESSAGE_EVENTS)
    resp = client.get("/api/games/g1/turns?view=god", headers={"X-Viewer-God-Token": "secret-god-token"})
    body = resp.json()
    anon = next(ev for turn in body for ev in turn["events"] if ev["event_type"] == "ANONYMOUS_BROADCAST_SENT")
    assert anon["data"]["sender"] == "P02"


# --- サイクル2.0: 即時取引のpublic投影テスト ---

_TRADE_EVENTS = [
    {"event_type": "GAME_START", "round_num": 0,
     "data": {"num_players": 2, "total_turns": 10, "initial_loans": {"P01": 1_000_000, "P02": 1_000_000}}},
    {"event_type": "TRADE_PROPOSED", "round_num": 1,
     "data": {"trade_id": "T_1_P01_1", "proposer_id": "P01", "target_id": "P02"}},
    {"event_type": "TRADE_ACCEPTED", "round_num": 2,
     "data": {
         "trade_id": "T_1_P01_1", "proposer_id": "P01", "target_id": "P02",
         "stars_moved": {"P01": -1, "P02": 1},
         "cards_moved": {"P01": 1, "P02": -1},
         "cash_moved": {"P01": -800000, "P02": 800000},
         "give": {"card_ids": [], "stars": 1, "cash": 0},
         "receive": {"card_ids": ["P02_ROCK_1"], "stars": 0, "cash": 800000},
     }},
]


def test_trade_proposed_public_omits_proposer_and_target(client, tmp_path):
    """§8.2は「取引の成立（当事者2人）」のみ公開区分に列挙。提案自体の当事者は出さない"""
    _write_events(tmp_path, "g1", _TRADE_EVENTS)
    body = client.get("/api/games/g1/turns?view=public").json()
    proposed = next(ev for turn in body for ev in turn["events"] if ev["event_type"] == "TRADE_PROPOSED")
    assert proposed["data"] == {"trade_id": "T_1_P01_1"}


def test_trade_accepted_public_shows_parties_and_stars_only(client, tmp_path):
    """成立は当事者2人が公開（§8.2）。★の移動も結果として見える（§7.1）。中身は秘匿"""
    _write_events(tmp_path, "g1", _TRADE_EVENTS)
    body = client.get("/api/games/g1/turns?view=public").json()
    accepted = next(ev for turn in body for ev in turn["events"] if ev["event_type"] == "TRADE_ACCEPTED")
    assert accepted["data"] == {
        "trade_id": "T_1_P01_1", "proposer_id": "P01", "target_id": "P02",
        "stars_moved": {"P01": -1, "P02": 1},
    }
    assert "cards_moved" not in accepted["data"]
    assert "cash_moved" not in accepted["data"]
    assert "give" not in accepted["data"]
    assert "receive" not in accepted["data"]


def test_trade_accepted_god_view_shows_full_contents(client, tmp_path):
    _write_events(tmp_path, "g1", _TRADE_EVENTS)
    resp = client.get("/api/games/g1/turns?view=god", headers={"X-Viewer-God-Token": "secret-god-token"})
    body = resp.json()
    accepted = next(ev for turn in body for ev in turn["events"] if ev["event_type"] == "TRADE_ACCEPTED")
    assert accepted["data"]["cards_moved"] == {"P01": 1, "P02": -1}
    assert "P02_ROCK_1" in str(accepted["data"]["receive"])
