"""
GET /api/games/{id}/board のテスト（サイクル1.7: 盤面UI化のためのサーバ側畳み込みAPI）

public/godの投影境界（§8.2）、identity開示ポリシー（VIEWER_REVEAL_IDENTITY）、
ETag/304、from_turn差分取得を検証する。
"""

import json

import pytest
from fastapi.testclient import TestClient

import viewer.server as server


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setattr(server, "LOGS_DIR", tmp_path)
    monkeypatch.setattr(server, "TOKEN", "")
    monkeypatch.setattr(server, "GOD_TOKEN", "secret-god-token")
    monkeypatch.setattr(server, "GOD_PUBLIC", False)
    monkeypatch.setattr(server, "REVEAL_IDENTITY", "after_game_end")
    return TestClient(server.app)


def _write_events(tmp_path, game_id: str, events: list[dict]) -> None:
    path = tmp_path / f"{game_id}_events.jsonl"
    with open(path, "w", encoding="utf-8") as f:
        for e in events:
            e.setdefault("timestamp", "t")
            e.setdefault("phase", "resolve")
            e.setdefault("step", None)
            f.write(json.dumps(e, ensure_ascii=False) + "\n")


_BASE_EVENTS = [
    {"event_type": "GAME_START", "round_num": 0,
     "data": {"num_players": 2, "total_turns": 10, "initial_loans": {"P01": 1_000_000, "P02": 1_000_000}}},
    {"event_type": "MATCH_OFFERED", "round_num": 1,
     "data": {"offer_id": "M_1_P01_1", "challenger_id": "P01", "opponent_id": "P02"}},
    {"event_type": "BOARD_UPDATED", "round_num": 1, "data": {"ROCK": 4, "SCISSORS": 3, "PAPER": 4}},
    {"event_type": "MATCH_ACCEPTED", "round_num": 2,
     "data": {"offer_id": "M_1_P01_1", "opponent_id": "P02"}},
    {"event_type": "BOARD_UPDATED", "round_num": 2, "data": {"ROCK": 3, "SCISSORS": 3, "PAPER": 3}},
    {"event_type": "MATCH_RESOLVED", "round_num": 3,
     "data": {"offer_id": "M_1_P01_1", "challenger_id": "P01", "opponent_id": "P02",
              "challenger_hand": "ROCK", "opponent_hand": "SCISSORS",
              "outcome": "challenger_win", "turn": 3}},
    {"event_type": "BOARD_UPDATED", "round_num": 3, "data": {"ROCK": 3, "SCISSORS": 3, "PAPER": 4}},
]


def test_board_public_omits_cash_debt_and_hands(client, tmp_path):
    _write_events(tmp_path, "g1", _BASE_EVENTS)
    resp = client.get("/api/games/g1/board?view=public")
    assert resp.status_code == 200
    body = resp.text
    for secret in ("cash", "debt", "hand_counts", "hand_total", "challenger_hand", "opponent_hand"):
        assert secret not in body, f"{secret} leaked in public board"


def test_board_public_exposes_stars_and_initial_loan(client, tmp_path):
    _write_events(tmp_path, "g1", _BASE_EVENTS)
    body = client.get("/api/games/g1/board?view=public").json()
    seat = next(s for s in body["seats"] if s["player_id"] == "P01")
    assert seat["stars"] == 4  # 3 + 1(win)
    assert seat["initial_loan"] == 1_000_000


def test_board_god_requires_token(client, tmp_path):
    _write_events(tmp_path, "g1", _BASE_EVENTS)
    resp = client.get("/api/games/g1/board?view=god")
    assert resp.status_code == 403


def test_board_god_exposes_cash_debt_hands(client, tmp_path):
    _write_events(tmp_path, "g1", _BASE_EVENTS)
    resp = client.get("/api/games/g1/board?view=god", headers={"X-Viewer-God-Token": "secret-god-token"})
    assert resp.status_code == 200
    body = resp.json()
    seat = next(s for s in body["seats"] if s["player_id"] == "P01")
    assert "cash" in seat and "debt" in seat and "hand_counts" in seat


def test_board_offer_index_resolves_participants(client, tmp_path):
    """public のMATCH_ACCEPTEDにはchallenger_idが無いが、offers索引経由で引ける"""
    _write_events(tmp_path, "g1", _BASE_EVENTS)
    body = client.get("/api/games/g1/board?view=public").json()
    offer = body["offers"]["M_1_P01_1"]
    assert offer["challenger_id"] == "P01"
    assert offer["opponent_id"] == "P02"
    assert "challenger_hand" not in offer


def test_board_final_assets_hidden_before_game_end(client, tmp_path):
    events = _BASE_EVENTS + [
        {"event_type": "PLAYER_EXITED", "round_num": 5, "data": {"player_id": "P02", "final_assets": 500000}},
    ]
    _write_events(tmp_path, "g1", events)
    body = client.get("/api/games/g1/board?view=public").json()
    assert body["completed"] is False
    seat = next(s for s in body["seats"] if s["player_id"] == "P02")
    assert "final_assets" not in seat


def test_board_final_assets_shown_after_game_end(client, tmp_path):
    events = _BASE_EVENTS + [
        {"event_type": "PLAYER_EXITED", "round_num": 5, "data": {"player_id": "P02", "final_assets": 500000}},
        {"event_type": "GAME_END", "round_num": 10, "data": {"survivors": ["P02"], "final_assets": {"P02": 500000}, "eliminated": {}}},
    ]
    _write_events(tmp_path, "g1", events)
    body = client.get("/api/games/g1/board?view=public").json()
    assert body["completed"] is True
    seat = next(s for s in body["seats"] if s["player_id"] == "P02")
    assert seat["final_assets"] == 500000


def test_board_identity_hidden_while_in_progress(client, tmp_path):
    _write_events(tmp_path, "g1", _BASE_EVENTS)
    (tmp_path / "g1_seat_map.json").write_text(
        json.dumps({"P01": "claude-sonnet-5", "P02": "gpt-4.1"}), encoding="utf-8",
    )
    body = client.get("/api/games/g1/board?view=public").json()
    for seat in body["seats"]:
        assert "identity" not in seat


def test_board_identity_revealed_after_game_end(client, tmp_path):
    events = _BASE_EVENTS + [
        {"event_type": "GAME_END", "round_num": 10, "data": {"survivors": [], "final_assets": {}, "eliminated": {}}},
    ]
    _write_events(tmp_path, "g1", events)
    (tmp_path / "g1_seat_map.json").write_text(
        json.dumps({"P01": "claude-sonnet-5", "P02": "gpt-4.1"}), encoding="utf-8",
    )
    body = client.get("/api/games/g1/board?view=public").json()
    seat = next(s for s in body["seats"] if s["player_id"] == "P01")
    assert seat["identity"]["vendor"] == "anthropic"


def test_board_identity_always_visible_in_god(client, tmp_path):
    _write_events(tmp_path, "g1", _BASE_EVENTS)
    (tmp_path / "g1_seat_map.json").write_text(
        json.dumps({"P01": "claude-sonnet-5", "P02": "gpt-4.1"}), encoding="utf-8",
    )
    body = client.get(
        "/api/games/g1/board?view=god", headers={"X-Viewer-God-Token": "secret-god-token"},
    ).json()
    seat = next(s for s in body["seats"] if s["player_id"] == "P01")
    assert seat["identity"]["vendor"] == "anthropic"


def test_board_reveal_identity_never_blocks_even_after_end(client, tmp_path, monkeypatch):
    monkeypatch.setattr(server, "REVEAL_IDENTITY", "never")
    events = _BASE_EVENTS + [
        {"event_type": "GAME_END", "round_num": 10, "data": {"survivors": [], "final_assets": {}, "eliminated": {}}},
    ]
    _write_events(tmp_path, "g1", events)
    (tmp_path / "g1_seat_map.json").write_text(json.dumps({"P01": "claude-sonnet-5"}), encoding="utf-8")
    body = client.get("/api/games/g1/board?view=public").json()
    seat = next(s for s in body["seats"] if s["player_id"] == "P01")
    assert "identity" not in seat


def test_board_without_seat_map_omits_identity(client, tmp_path):
    events = _BASE_EVENTS + [
        {"event_type": "GAME_END", "round_num": 10, "data": {"survivors": [], "final_assets": {}, "eliminated": {}}},
    ]
    _write_events(tmp_path, "g1", events)
    body = client.get(
        "/api/games/g1/board?view=god", headers={"X-Viewer-God-Token": "secret-god-token"},
    ).json()
    for seat in body["seats"]:
        assert "identity" not in seat


def test_board_accepts_seat_map_v1_flat_dict(client, tmp_path):
    _write_events(tmp_path, "g1", _BASE_EVENTS)
    (tmp_path / "g1_seat_map.json").write_text(json.dumps({"P01": "claude-sonnet-5"}), encoding="utf-8")
    body = client.get(
        "/api/games/g1/board?view=god", headers={"X-Viewer-God-Token": "secret-god-token"},
    ).json()
    seat = next(s for s in body["seats"] if s["player_id"] == "P01")
    assert seat["identity"]["name"] == "Claude Sonnet 5"


def test_board_from_turn_returns_only_newer_turns(client, tmp_path):
    _write_events(tmp_path, "g1", _BASE_EVENTS)
    body = client.get("/api/games/g1/board?view=public&from_turn=2").json()
    assert all(t["turn"] > 2 for t in body["turns"])
    assert len(body["seats"]) == 2  # seatsは常に全件


def test_board_etag_returns_304_on_match(client, tmp_path):
    _write_events(tmp_path, "g1", _BASE_EVENTS)
    first = client.get("/api/games/g1/board?view=public")
    etag = first.headers["etag"]
    second = client.get("/api/games/g1/board?view=public", headers={"If-None-Match": etag})
    assert second.status_code == 304


def test_board_etag_changes_when_log_grows(client, tmp_path):
    _write_events(tmp_path, "g1", _BASE_EVENTS)
    first = client.get("/api/games/g1/board?view=public")
    etag = first.headers["etag"]
    _write_events(tmp_path, "g1", _BASE_EVENTS + [
        {"event_type": "BOARD_UPDATED", "round_num": 4, "data": {"ROCK": 3, "SCISSORS": 3, "PAPER": 4}},
    ])
    second = client.get("/api/games/g1/board?view=public", headers={"If-None-Match": etag})
    assert second.status_code == 200


def test_board_unknown_event_type_does_not_break_fold(client, tmp_path):
    events = _BASE_EVENTS + [
        {"event_type": "SOME_FUTURE_EVENT", "round_num": 4, "data": {"whatever": "value"}},
    ]
    _write_events(tmp_path, "g1", events)
    resp = client.get("/api/games/g1/board?view=public")
    assert resp.status_code == 200


def test_board_missing_game_returns_found_false(client, tmp_path):
    resp = client.get("/api/games/does-not-exist/board?view=public")
    assert resp.status_code == 200
    assert resp.json()["found"] is False


def test_board_game_id_traversal_is_404(client, tmp_path):
    resp = client.get("/api/games/..%2F..%2Fetc%2Fpasswd/board")
    assert resp.status_code == 404


def test_board_response_never_contains_seat_map_literal(client, tmp_path):
    _write_events(tmp_path, "g1", _BASE_EVENTS)
    (tmp_path / "g1_seat_map.json").write_text(json.dumps({"P01": "claude-sonnet-5"}), encoding="utf-8")
    resp = client.get(
        "/api/games/g1/board?view=god", headers={"X-Viewer-God-Token": "secret-god-token"},
    )
    assert "seat_map" not in resp.text


def test_board_derivation_reports_zero_sum_ok(client, tmp_path):
    _write_events(tmp_path, "g1", _BASE_EVENTS)
    body = client.get("/api/games/g1/board?view=public").json()
    assert body["derivation"]["stars_zero_sum_ok"] is True


def test_board_rules_reflects_num_players_and_total_turns(client, tmp_path):
    _write_events(tmp_path, "g1", _BASE_EVENTS)
    body = client.get("/api/games/g1/board?view=public").json()
    assert body["rules"]["num_players"] == 2
    assert body["rules"]["total_turns"] == 10
    assert body["rules"]["initial_cards_total"] == 12
