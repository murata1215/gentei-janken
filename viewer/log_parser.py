"""
ログパーサ — JSONL→構造化データ、差分キャッシュ付き

engine.events.EventLogger が書き出す `{game_id}_events.jsonl` を読み取り、
ビューア用の構造化データに変換する。読み取り専用。

差分キャッシュ: mtime+sizeで変更検知、変更なしなら即返し（dangou-cardの
LogCacheパターンを移植）。DM本文・契約内容などの秘匿情報（§8.2）はview="public"
時に必ず除去する。

秘匿方式はホワイトリスト（rules/project.md「DM本文はキーごと削除」と同じ発想:
空文字/Noneでの上書きではなくキー自体を欠落させる）。イベント種別ごとに
「公開してよいキー」だけを列挙し、未列挙のイベント種別・未列挙のキーは
existing dataから丸ごと落とす。新規イベント種別を追加した開発者がここに
追記し忘れても、既定で秘匿側に倒れる（deny-by-default）。
"""

import json
import time
from pathlib import Path
from typing import Any

# §8.2の「公開」区分に基づくイベント種別ごとの公開キー一覧。
# ここに無いキーはpublic viewから削除する（god viewはそのまま全部通す）。
PUBLIC_EVENT_DATA_KEYS: dict[str, set[str]] = {
    "GAME_START": {"num_players", "total_turns", "initial_loans"},
    "GAME_END": {"survivors", "final_assets", "eliminated"},
    "MATCH_OFFERED": {"offer_id", "challenger_id", "opponent_id"},
    "MATCH_OFFER_REJECTED": {"player_id", "reason"},
    "MATCH_ACCEPTED": {"offer_id", "opponent_id"},
    "MATCH_ACCEPT_REJECTED": {"player_id", "offer_id", "reason"},
    "MATCH_DECLINED": {"offer_id"},
    "MATCH_WITHDRAWN": {"offer_id"},
    "MATCH_EXPIRED": {"offer_id"},
    # challenger_hand/opponent_hand（出した手）は当事者だけが知る秘匿情報（§8.2）。
    # 対戦の組み合わせと勝敗（outcome）だけを公開する。
    "MATCH_RESOLVED": {"offer_id", "challenger_id", "opponent_id", "outcome", "turn"},
    "EXIT_REJECTED": {"player_id", "reason"},
    # final_assetsは「退出者の最終資産（試合終了まで）」秘匿（§8.2）。
    # GAME_END後は_redact_eventが個別に許可する（_PLAYER_EXITED_POST_GAME_KEYS）。
    "PLAYER_EXITED": {"player_id"},
    # cash_before/debt_before/debt_repaid/bad_debt/cash_confiscated/cards_destroyed
    # は現金・借金・手札枚数（いずれも秘匿）を含むため落とす。★の数は公開情報。
    "FORCED_EXIT": {"player_id", "elimination_type", "turn", "stars_before", "stars_confiscated"},
    "TIMEOUT": {"player_id", "elimination_type", "turn", "stars_before", "stars_confiscated"},
    # old_debt/interest/new_debtは借金残高（秘匿）を含むため落とす。
    "INTEREST": {"player_id"},
    "REPAID": {"player_id"},
    "REPAY_REJECTED": {"player_id", "reason"},
    # 取引の成立は当事者2人までが公開（§8.2「取引の成立（当事者2人）」）。金額は秘匿。
    "TRANSFERRED": {"from", "to"},
    "TRANSFER_REJECTED": {"player_id", "to", "reason"},
    "WAIT_STARTED": {"player_id", "until_turn", "wake_on_event"},
    "BOARD_UPDATED": {"ROCK", "SCISSORS", "PAPER"},
    "ACTION_UNHANDLED": {"player_id", "action_type"},
}

_PLAYER_EXITED_POST_GAME_KEYS = PUBLIC_EVENT_DATA_KEYS["PLAYER_EXITED"] | {"final_assets"}
"""GAME_END後はfinal_assetsも公開してよい（§8.2「試合終了まで」秘匿の期限が切れる）"""


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


def get_game_state(logs_dir: Path, game_id: str, view: str = "public") -> dict[str, Any]:
    """
    試合の現在状態サマリを返す（§8.2の公開/秘匿境界に従う）

    Args:
        view: "public"（既定） または "god"（呼び出し元がトークン検証済みであること）
    """
    events = _cache.read_jsonl(logs_dir / f"{game_id}_events.jsonl")
    if not events:
        return {"game_id": game_id, "found": False}

    current_turn = 0
    alive: set[str] = set()
    survivors: dict[str, int | None] = {}
    eliminated: dict[str, str] = {}
    board: dict[str, int] = {}
    completed = False

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
        elif etype == "BOARD_UPDATED":
            board = {k: data.get(k, 0) for k in ("ROCK", "SCISSORS", "PAPER")}
        elif etype == "GAME_END":
            completed = True

    if view != "god" and not completed:
        # 退出者の最終資産は試合終了まで秘匿（§8.2）。player_idのキー自体は
        # 「退出者」として公開情報なので残し、値だけ隠す。
        survivors = {pid: None for pid in survivors}

    return {
        "game_id": game_id,
        "found": True,
        "completed": completed,
        "current_turn": current_turn,
        "alive_count": len(alive),
        "survivors": survivors,
        "eliminated": eliminated,
        "board": board,
    }


def _redact_event(event: dict[str, Any], view: str, game_ended: bool) -> dict[str, Any]:
    """
    view="public" の場合、§8.2の公開キー一覧に無いキーをその場から削除する

    空文字/Noneで上書きするのではなくキー自体を欠落させる（rules/project.md
    「DM本文はキーごと削除」と同じ方式。`str(event)` に秘匿値が一切現れないことを
    テストで機械的に検証できるようにするため）。未列挙のイベント種別はdataを
    空にする（deny-by-default）。
    """
    if view == "god":
        return event
    etype = event.get("event_type")
    if etype == "PLAYER_EXITED" and game_ended:
        allowed = _PLAYER_EXITED_POST_GAME_KEYS
    else:
        allowed = PUBLIC_EVENT_DATA_KEYS.get(etype, set())
    data = event.get("data", {})
    redacted_data = {k: v for k, v in data.items() if k in allowed}
    return {**event, "data": redacted_data}


def get_round_states(logs_dir: Path, game_id: str, view: str = "public") -> list[dict[str, Any]]:
    """
    ターン別の盤面状況を返す（§8.2の公開/秘匿境界に従う）

    Args:
        view: "public"（既定） または "god"（呼び出し元がトークン検証済みであること）
    """
    events = _cache.read_jsonl(logs_dir / f"{game_id}_events.jsonl")
    game_ended = any(e.get("event_type") == "GAME_END" for e in events)
    by_turn: dict[int, list[dict[str, Any]]] = {}
    for e in events:
        turn = e.get("round_num", 0)
        if not isinstance(turn, int):
            continue
        by_turn.setdefault(turn, []).append(_redact_event(e, view, game_ended))
    return [
        {"turn": turn, "events": by_turn[turn]}
        for turn in sorted(by_turn.keys())
    ]
