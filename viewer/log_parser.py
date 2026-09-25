"""
ログパーサ — JSONL→構造化データ、差分キャッシュ付き

engine.events.EventLogger が書き出す `{game_id}_events.jsonl` を読み取り、
ビューア用の構造化データに変換する。読み取り専用。

差分キャッシュ: mtime+sizeで変更検知、変更なしなら即返し（dangou-cardの
LogCacheパターンを移植）。DM本文・契約内容などの秘匿情報（§8.2）はview="public"
時に必ず除去する。
"""

import json
import time
from pathlib import Path
from typing import Any

# §8.2: 秘匿情報を含みうるイベント種別（public viewでは message/data の
# 一部キーを落とす）。本サイクルはDM/契約まわりの実処理が未実装のため、
# 実際に発生するのは主に ACTION_UNHANDLED（dm/contract_propose等の生アクションを
# そのままログしている可能性がある）程度。将来の型拡張に備えて列挙しておく。
SECRET_EVENT_TYPES = {"ACTION_UNHANDLED"}
SECRET_DATA_KEYS = {"message", "details", "condition"}


class LogCache:
    """ファイル差分キャッシュ（mtime+sizeベース）"""

    def __init__(self) -> None:
        self._cache: dict[str, tuple[float, int, list[dict[str, Any]]]] = {}

    def read_jsonl(self, path: Path) -> list[dict[str, Any]]:
        """JSONLファイルを読み、mtime+sizeが変わっていなければキャッシュを返す"""
        key = str(path)
        try:
            stat = path.stat()
        except FileNotFoundError:
            return []
        cached = self._cache.get(key)
        if cached and cached[0] == stat.st_mtime and cached[1] == stat.st_size:
            return cached[2]

        events: list[dict[str, Any]] = []
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    events.append(json.loads(line))
                except json.JSONDecodeError:
                    continue  # 書きかけの最終行はスキップ
        self._cache[key] = (stat.st_mtime, stat.st_size, events)
        return events


_cache = LogCache()


def list_games(logs_dir: Path) -> list[dict[str, Any]]:
    """試合一覧を返す（新しい順）"""
    if not logs_dir.exists():
        return []
    games = []
    for path in logs_dir.glob("*_events.jsonl"):
        game_id = path.name[: -len("_events.jsonl")]
        try:
            mtime = path.stat().st_mtime
        except FileNotFoundError:
            continue
        events = _cache.read_jsonl(path)
        last_turn = 0
        completed = False
        for e in events:
            if isinstance(e.get("round_num"), int):
                last_turn = max(last_turn, e["round_num"])
            if e.get("event_type") == "GAME_END":
                completed = True
        games.append({
            "game_id": game_id,
            "last_turn": last_turn,
            "completed": completed,
            "event_count": len(events),
            "mtime": mtime,
        })
    games.sort(key=lambda g: g["mtime"], reverse=True)
    return games


def get_game_state(logs_dir: Path, game_id: str) -> dict[str, Any]:
    """試合の現在状態サマリを返す"""
    events = _cache.read_jsonl(logs_dir / f"{game_id}_events.jsonl")
    if not events:
        return {"game_id": game_id, "found": False}

    current_turn = 0
    alive: set[str] = set()
    survivors: dict[str, str | None] = {}
    eliminated: dict[str, str] = {}
    board: dict[str, int] = {}

    for e in events:
        etype = e.get("event_type")
        data = e.get("data", {})
        if isinstance(e.get("round_num"), int):
            current_turn = max(current_turn, e["round_num"])
        if etype == "GAME_START":
            alive = set(data.get("initial_loans", {}).keys())
        elif etype == "PLAYER_EXITED":
            pid = data.get("player_id")
            if pid:
                alive.discard(pid)
                survivors[pid] = data.get("final_assets")
        elif etype in ("FORCED_EXIT", "TIMEOUT"):
            pid = data.get("player_id")
            if pid:
                alive.discard(pid)
                eliminated[pid] = etype

    return {
        "game_id": game_id,
        "found": True,
        "current_turn": current_turn,
        "alive_count": len(alive),
        "survivors": survivors,
        "eliminated": eliminated,
        "board": board,
    }


def _redact_event(event: dict[str, Any], view: str) -> dict[str, Any]:
    """view="public" の場合、秘匿情報（§8.2）を含みうるキーを除去する"""
    if view == "god":
        return event
    if event.get("event_type") not in SECRET_EVENT_TYPES:
        return event
    data = dict(event.get("data", {}))
    for key in SECRET_DATA_KEYS:
        if key in data:
            data[key] = None
            data[f"{key}_redacted"] = True
    return {**event, "data": data}


def get_round_states(logs_dir: Path, game_id: str, view: str = "public") -> list[dict[str, Any]]:
    """
    ターン別の盤面状況を返す（§8.2の公開/秘匿境界に従う）

    Args:
        view: "public"（既定） または "god"（呼び出し元がトークン検証済みであること）
    """
    events = _cache.read_jsonl(logs_dir / f"{game_id}_events.jsonl")
    by_turn: dict[int, list[dict[str, Any]]] = {}
    for e in events:
        turn = e.get("round_num", 0)
        if not isinstance(turn, int):
            continue
        by_turn.setdefault(turn, []).append(_redact_event(e, view))
    return [
        {"turn": turn, "events": by_turn[turn]}
        for turn in sorted(by_turn.keys())
    ]
