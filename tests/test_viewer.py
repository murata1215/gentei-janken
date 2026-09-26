"""
viewer/server.py・viewer/log_parser.py のテスト（rules/project.md「Viewerの
公開表示と神視点を分離する」）

サイクル1.0の実害（_redact_eventのブラックリストが実在しないキーを指しており
challenger_hand/old_debt/final_assets等の秘匿情報がview=publicで素通りしていた）
の再発防止線。
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
    return TestClient(server.app)


def _write_events(tmp_path, game_id: str, events: list[dict], round_num_key: str = "round_num") -> None:
    path = tmp_path / f"{game_id}_events.jsonl"
    with open(path, "w", encoding="utf-8") as f:
        for e in events:
            e.setdefault("timestamp", "t")
            e.setdefault("phase", "resolve")
            e.setdefault("step", None)
            f.write(json.dumps(e, ensure_ascii=False) + "\n")


_SAMPLE_EVENTS = [
    {"event_type": "GAME_START", "round_num": 0,
     "data": {"num_players": 2, "total_turns": 10, "initial_loans": {"P01": 1_000_000, "P02": 1_000_000}}},
    {"event_type": "MATCH_RESOLVED", "round_num": 3,
     "data": {"offer_id": "M_1_P01_1", "challenger_id": "P01", "opponent_id": "P02",
              "challenger_hand": "ROCK", "opponent_hand": "SCISSORS",
              "outcome": "challenger_win", "turn": 3}},
    {"event_type": "INTEREST", "round_num": 10,
     "data": {"player_id": "P01", "old_debt": 1_000_000, "interest": 15_000, "new_debt": 1_015_000}},
    {"event_type": "FORCED_EXIT", "round_num": 12,
     "data": {"player_id": "P02", "elimination_type": "FORCED_EXIT", "turn": 12,
              "cash_before": 200_000, "debt_before": 900_000, "stars_before": 0,
              "debt_repaid": 200_000, "bad_debt": 700_000, "cash_confiscated": 0,
              "cards_destroyed": 3, "stars_confiscated": 0}},
    {"event_type": "PLAYER_EXITED", "round_num": 15,
     "data": {"player_id": "P01", "final_assets": 2_000_000}},
    {"event_type": "BOARD_UPDATED", "round_num": 15, "data": {"ROCK": 1, "SCISSORS": 0, "PAPER": 2}},
]


def test_public_turns_hides_hands_and_financial_secrets(client, tmp_path):
    _write_events(tmp_path, "g1", _SAMPLE_EVENTS)
    resp = client.get("/api/games/g1/turns?view=public")
    assert resp.status_code == 200
    body = resp.text
    for secret in (
        "challenger_hand", "opponent_hand",
        "old_debt", "new_debt", "interest",
        "cash_before", "debt_before", "debt_repaid", "bad_debt",
        "cash_confiscated", "cards_destroyed",
        "final_assets",  # ゲーム未終了なので秘匿のまま
    ):
        assert secret not in body, f"{secret} leaked in public view"


def test_public_turns_keeps_public_fields(client, tmp_path):
    _write_events(tmp_path, "g1", _SAMPLE_EVENTS)
    resp = client.get("/api/games/g1/turns?view=public")
    body = resp.text
    assert "outcome" in body
    assert "challenger_win" in body
    assert "stars_before" in body  # ★の数は公開情報
    assert "ROCK" in body  # 掲示板は公開


def test_god_view_requires_token(client, tmp_path):
    _write_events(tmp_path, "g1", _SAMPLE_EVENTS)
    resp = client.get("/api/games/g1/turns?view=god")
    assert resp.status_code == 403


def test_god_view_wrong_token_is_403(client, tmp_path):
    _write_events(tmp_path, "g1", _SAMPLE_EVENTS)
    resp = client.get("/api/games/g1/turns?view=god", headers={"X-Viewer-God-Token": "wrong"})
    assert resp.status_code == 403


def test_god_view_with_correct_token_shows_everything(client, tmp_path):
    _write_events(tmp_path, "g1", _SAMPLE_EVENTS)
    resp = client.get(
        "/api/games/g1/turns?view=god", headers={"X-Viewer-God-Token": "secret-god-token"},
    )
    assert resp.status_code == 200
    assert "challenger_hand" in resp.text
    assert "old_debt" in resp.text


def test_god_public_env_bypasses_token(client, tmp_path, monkeypatch):
    monkeypatch.setattr(server, "GOD_PUBLIC", True)
    _write_events(tmp_path, "g1", _SAMPLE_EVENTS)
    resp = client.get("/api/games/g1/turns?view=god")
    assert resp.status_code == 200
    assert "challenger_hand" in resp.text


def test_invalid_view_is_400(client, tmp_path):
    _write_events(tmp_path, "g1", _SAMPLE_EVENTS)
    resp = client.get("/api/games/g1/turns?view=bogus")
    assert resp.status_code == 400


def test_state_endpoint_hides_final_assets_before_game_end(client, tmp_path):
    _write_events(tmp_path, "g1", _SAMPLE_EVENTS)
    resp = client.get("/api/games/g1/state")
    assert resp.status_code == 200
    body = resp.json()
    assert body["completed"] is False
    assert body["survivors"]["P01"] is None


def test_state_endpoint_reveals_final_assets_after_game_end(client, tmp_path):
    events = _SAMPLE_EVENTS + [{"event_type": "GAME_END", "round_num": 15, "data": {}}]
    _write_events(tmp_path, "g1", events)
    resp = client.get("/api/games/g1/state")
    body = resp.json()
    assert body["completed"] is True
    assert body["survivors"]["P01"] == 2_000_000


def test_state_endpoint_god_view_always_reveals(client, tmp_path):
    _write_events(tmp_path, "g1", _SAMPLE_EVENTS)
    resp = client.get(
        "/api/games/g1/state?view=god", headers={"X-Viewer-God-Token": "secret-god-token"},
    )
    body = resp.json()
    assert body["survivors"]["P01"] == 2_000_000


def test_state_endpoint_god_view_without_token_403(client, tmp_path):
    _write_events(tmp_path, "g1", _SAMPLE_EVENTS)
    resp = client.get("/api/games/g1/state?view=god")
    assert resp.status_code == 403


def test_state_endpoint_reports_board(client, tmp_path):
    _write_events(tmp_path, "g1", _SAMPLE_EVENTS)
    resp = client.get("/api/games/g1/state")
    body = resp.json()
    assert body["board"] == {"ROCK": 1, "SCISSORS": 0, "PAPER": 2}


def test_action_unhandled_only_exposes_player_id_and_action_type(client, tmp_path):
    events = [
        {"event_type": "GAME_START", "round_num": 0, "data": {"num_players": 1, "total_turns": 5, "initial_loans": {}}},
        {"event_type": "ACTION_UNHANDLED", "round_num": 2,
         "data": {"player_id": "P01", "action_type": "dm"}},
    ]
    _write_events(tmp_path, "g1", events)
    resp = client.get("/api/games/g1/turns?view=public")
    body = resp.json()
    unhandled = next(
        ev for turn in body for ev in turn["events"] if ev["event_type"] == "ACTION_UNHANDLED"
    )
    assert set(unhandled["data"].keys()) == {"player_id", "action_type"}


def test_root_serves_viewer(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]


def test_default_bind_is_loopback():
    """公開運用の既定は127.0.0.1（Caddy経由のみ）。0.0.0.0への回帰を検知する。"""
    assert server.DEFAULT_HOST == "127.0.0.1"


def test_default_port_matches_caddy_upstream():
    """Caddy sites.dのreverse_proxy先とのドリフト検知。変更時はdoc/viewer_operations.mdも直すこと。"""
    assert server.DEFAULT_PORT == 9027


def test_unknown_event_type_data_is_emptied(client, tmp_path):
    """deny-by-default: ホワイトリスト未列挙のイベント種別はdataを丸ごと落とす"""
    events = [
        {"event_type": "GAME_START", "round_num": 0, "data": {"num_players": 1, "total_turns": 5, "initial_loans": {}}},
        {"event_type": "SOME_NEW_EVENT_TYPE", "round_num": 2,
         "data": {"secret_field": "should-not-leak"}},
    ]
    _write_events(tmp_path, "g1", events)
    resp = client.get("/api/games/g1/turns?view=public")
    assert "secret_field" not in resp.text
    assert "should-not-leak" not in resp.text


def test_llm_calls_log_is_not_listed(client, tmp_path):
    """神視点専用ログ（llm_calls/seat_map）は/api/gamesの一覧に出ない"""
    _write_events(tmp_path, "g1", _SAMPLE_EVENTS)
    (tmp_path / "g1_llm_calls.jsonl").write_text('{"prompt": "secret"}\n', encoding="utf-8")
    (tmp_path / "g1_seat_map.json").write_text('{"P01": "gpt-4"}', encoding="utf-8")
    resp = client.get("/api/games")
    body = resp.json()
    assert [g["game_id"] for g in body] == ["g1"]
    assert "llm_calls" not in resp.text
    assert "seat_map" not in resp.text


def test_static_mount_rejects_traversal(client):
    resp = client.get("/static/../../.env")
    assert resp.status_code in (403, 404)


def test_encoded_slash_game_id_is_404(client, tmp_path):
    _write_events(tmp_path, "g1", _SAMPLE_EVENTS)
    resp = client.get("/api/games/..%2F..%2Fetc%2Fpasswd/turns")
    assert resp.status_code == 404
