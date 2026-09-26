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

from engine.config import GameConfig
from llm.models import get_model

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
    # DM本文は当事者以外に秘匿（§8.2）。senderは常に公開情報として残す
    # （「誰と誰がDMしているか」は§8.2が明示的に禁じていない場のドラマの材料）。
    # message（本文）はここに列挙しないことで自動的に落とす。
    "DM_SENT": {"sender", "to", "turn"},
    "DM_REJECTED": {"player_id", "reason"},
    # 全体発言は本文・発信者ともに公開情報（§8.2「全体発言」）。
    "BROADCAST_SENT": {"sender", "message", "turn"},
    "BROADCAST_REJECTED": {"player_id", "reason"},
    # 匿名通信は本文のみ公開、発信者は秘匿（§8.2「匿名通信…の発信者」）。
    # senderをここに列挙しないことで自動的に落とす（実送信者はgod専用）。
    "ANONYMOUS_BROADCAST_SENT": {"message", "turn"},
    "ANON_BROADCAST_REJECTED": {"player_id", "reason"},
}

_PLAYER_EXITED_POST_GAME_KEYS = PUBLIC_EVENT_DATA_KEYS["PLAYER_EXITED"] | {"final_assets"}
"""GAME_END後はfinal_assetsも公開してよい（§8.2「試合終了まで」秘匿の期限が切れる）"""

# `reason` はキーとしては複数イベント種別でpublic許可されているが、値は
# engine側で自由文字列（str(ValueError)）を入れている箇所があり、そこにcard_id
# （＝手の種類）やplayer_idの詳細が埋め込まれる（例:
# "P18 already has card P18_PAPER_1 reserved"）。§8.2「手札の中身」「封をした
# 提出中の手」の直接侵害になるため、値のホワイトリストで塞ぐ（deny-by-default）。
# ここに列挙されている「定数コード文字列」のみpublicで許可し、それ以外（動的な
# 自由文字列）は`reason`キーごと削除する（空文字での上書きではなくキー欠落。
# rules/project.md「DM本文はキーごと削除」と同じ方式）。
# 新しいreasonコードをengine側に追加したら、ここにも追記すること
# （追記漏れは自動的に秘匿側に倒れる＝deny-by-default）。
PUBLIC_REASON_CODES: set[str] = {
    "already_has_active_offer",  # engine/game.py: MATCH_OFFER_REJECTED
    "not_found",                  # engine/game.py: MATCH_ACCEPT_REJECTED（offer未検出）
    "non_positive_amount",        # engine/game.py: REPAY_REJECTED/TRANSFER_REJECTED
    "repay_locked",               # engine/game.py: REPAY_REJECTED
    "invalid_target_or_amount",   # engine/game.py: TRANSFER_REJECTED
    "insufficient_cash",          # engine/game.py: TRANSFER_REJECTED
    "cards_remaining",            # engine/exit_rules.py: can_exit
    "insufficient_stars",         # engine/exit_rules.py: can_exit
    "cannot_clear_debt",          # engine/exit_rules.py: can_exit
    "unfulfilled_obligation",     # engine/exit_rules.py: can_exit
    "invalid_target",             # engine/game.py: DM_REJECTED
    "empty_message",              # engine/game.py: DM_REJECTED/BROADCAST_REJECTED/ANON_BROADCAST_REJECTED
    "anon_limit_reached",         # engine/game.py: ANON_BROADCAST_REJECTED
}

# 注意: `message`（DM本文・全体発言・匿名通信の本文）は`reason`と違って値の
# ホワイトリストが不要である。broadcast/anonymous_broadcastのmessageはLLMの
# 自由記述だが§8.2でそもそも公開情報と定められているため、値を問わず公開してよい。
# DM_SENTの`message`はキーそのものをPUBLIC_EVENT_DATA_KEYSに列挙していない
# （＝deny-by-defaultで自動的に落ちる）ため、こちらも値検査は不要。
# `reason`だけが特別なのは、キーはpublic許可なのに値がengine内部のstr(ValueError)
# 由来で秘匿情報（card_id等）を埋め込みうる、という設計ミスが原因だった
# （サイクル1.6.1）。同じ穴が`message`系で開くことは構造上ない。


def _sanitize_reason(data: dict[str, Any]) -> dict[str, Any]:
    """
    `reason`キーの値がPUBLIC_REASON_CODESに無い（＝engine側のstr(ValueError)由来の
    自由文字列である）場合、`reason`キー自体をdataから削除する。

    MATCH_OFFER_REJECTED/MATCH_ACCEPT_REJECTEDのreasonにcard_idが混入する実害
    （サイクル1.6.1で発見）への対処。値の自由文字列はホワイトリスト不可能な
    秘匿の穴であり、キーが許可されていても値まで無条件に通してはならない。
    """
    if "reason" not in data or data["reason"] in PUBLIC_REASON_CODES:
        return data
    return {k: v for k, v in data.items() if k != "reason"}


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

    def fingerprint(self, path: Path) -> str | None:
        """
        現在のファイル状態（mtime+size）を表す文字列を返す（ETag用）。
        ファイルが存在しなければNone。read_jsonl()と同じ差分検知基準を使うため、
        「フィンガープリントが変わっていない」＝「read_jsonl()の結果も変わっていない」
        が保証される。
        """
        try:
            stat = path.stat()
        except FileNotFoundError:
            return None
        return f"{stat.st_mtime}-{stat.st_size}"


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
    redacted_data = _sanitize_reason(redacted_data)
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


# =============================================================================
# 盤面畳み込み（GET /api/games/{id}/board）
#
# public イベント列は自己完結していない（MATCH_ACCEPTEDにchallenger_idが無い等）ため、
# 畳み込みは常に「god完全体」の生イベント列に対して行い、結果をpublic/godへ
# 投影する（deny-by-default）。JS側には状態機械を持たせない
# （rules/project.md「ホワイトリスト方式に統一」参照）。
# =============================================================================

PUBLIC_SEAT_KEYS: set[str] = {
    "player_id", "seat_index", "initial_loan", "stars",
    "status", "exited_turn", "elimination_type",
}
"""畳み込み結果の「席」オブジェクトのうちpublicで許可するキー（§8.2準拠）"""

_PUBLIC_SEAT_POST_GAME_KEYS = PUBLIC_SEAT_KEYS | {"final_assets"}
"""GAME_END後はfinal_assetsも公開してよい（_PLAYER_EXITED_POST_GAME_KEYSと同じ期限付きゲート）"""

PUBLIC_OFFER_KEYS: set[str] = {
    "offer_id", "challenger_id", "opponent_id",
    "offered_turn", "accepted_turn", "resolved_turn", "closed_turn", "status", "outcome",
}
"""畳み込み結果の「申込」オブジェクトのうちpublicで許可するキー（出した手は含めない）"""

PUBLIC_TURN_SEAT_KEYS: set[str] = {"stars", "status", "exited_turn", "elimination_type"}
"""turns[].seats_changed の差分に許可するキー（cash/debt/hand_*はgod専用）"""

_PUBLIC_TURN_SEAT_POST_GAME_KEYS = PUBLIC_TURN_SEAT_KEYS | {"final_assets"}

_INITIAL_HAND_TYPES = ("ROCK", "SCISSORS", "PAPER")


def _resolve_rules(game_start_data: dict[str, Any]) -> GameConfig:
    """
    GAME_STARTのdataからGameConfigを復元する。

    rules/project.md「設定の単一ソース化ルール」に従い、Viewer側で独自の
    定数（initial_stars=3等）を持たない。scripts/dry_run.py・scripts/llm_trial.py
    と同じ分岐（20人×120ターンはdefault_20()、それ以外はdev_small()）で
    GameConfigプリセットを再現する。
    """
    num_players = game_start_data.get("num_players") or 4
    total_turns = game_start_data.get("total_turns") or 20
    if num_players == 20 and total_turns == 120:
        return GameConfig.default_20()
    return GameConfig.dev_small(num_players=num_players, total_turns=total_turns)


def _rules_dict(config: GameConfig, total_turns_actual: int) -> dict[str, Any]:
    """§8.1/§8.2に照らして全部公開してよいルールパラメータの辞書を返す（public/god共通）"""
    r, s, p = config.cards_per_hand
    return {
        "num_players": config.num_players,
        "total_turns": total_turns_actual,
        "initial_stars": config.initial_stars,
        "initial_cards_total": r + s + p,
        "survival_stars_min": config.survival_stars_min,
        "surplus_star_buyback": config.surplus_star_buyback,
        "interest_rate": config.interest_rate,
        "interest_interval_turns": config.interest_interval_turns,
        "reveal_hands_publicly": config.reveal_hands_publicly,
        "reveal_hand_count": config.reveal_hand_count,
    }


def load_identities(logs_dir: Path, game_id: str) -> dict[str, dict[str, Any]] | None:
    """
    `{game_id}_seat_map.json` からプレイヤーの正体情報を読み込む。

    v2（`{"version": 2, "seats": {pid: {...}}}`）とv1（`{pid: model_id}`の
    フラットdict、scripts/llm_trial.py現行形式）の両方に対応する。v1は
    `llm.models.get_model()`（先勝ちルール）でprovider/name/vendor/tierを補完する。
    ファイルが無い・壊れている場合はNoneを返す（呼び出し側が`identity`キー自体を
    欠落させる判断に使う）。Bot戦（scripts/dry_run.py）はseat_mapを書き出さないため
    常にNoneになる。
    """
    path = logs_dir / f"{game_id}_seat_map.json"
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None
    if not isinstance(raw, dict):
        return None

    if raw.get("version") == 2 and isinstance(raw.get("seats"), dict):
        return raw["seats"]

    identities: dict[str, dict[str, Any]] = {}
    for pid, model_id in raw.items():
        if not isinstance(model_id, str):
            continue
        try:
            info = get_model(model_id)
        except ValueError:
            identities[pid] = {"model_id": model_id, "vendor": None}
            continue
        identities[pid] = {
            "model_id": info.model_id, "provider": info.provider,
            "name": info.name, "vendor": info.vendor, "tier": info.tier,
        }
    return identities or None


def _new_seat(pid: str, seat_index: int, initial_loan: int, config: GameConfig) -> dict[str, Any]:
    r, s, p = config.cards_per_hand
    return {
        "player_id": pid,
        "seat_index": seat_index,
        "initial_loan": initial_loan,
        "stars": config.initial_stars,
        "cash": initial_loan,
        "debt": initial_loan,
        "hand_total": r + s + p,
        "hand_counts": {"ROCK": r, "SCISSORS": s, "PAPER": p},
        "reserved_count": 0,
        "wins": 0, "losses": 0, "draws": 0,
        "matches_resolved": 0,
        "status": "alive",
        "exited_turn": None,
        "elimination_type": None,
        "final_assets": None,
    }


def _fold_events(events: list[dict[str, Any]]) -> dict[str, Any]:
    """
    イベント列を発行順に畳み込み、席（プレイヤー）・申込・掲示板のgod完全体を構築する。

    `_FOLD_HANDLERS` に無い未知のイベント種別は無視する（engine/trades.py等が将来
    有線化されカードが席間を移動しても、畳み込みが例外で落ちない構造にするため。
    その場合`derivation`の各cross_checkが不一致を検出する）。
    """
    seats: dict[str, dict[str, Any]] = {}
    seat_order: list[str] = []
    offers: dict[str, dict[str, Any]] = {}
    board = {"ROCK": 0, "SCISSORS": 0, "PAPER": 0}
    board_history: list[dict[str, Any]] = []
    turns_out: list[dict[str, Any]] = []
    completed = False
    current_turn = 0
    config: GameConfig | None = None

    stars_removed_total = 0
    stars_checked = 0
    stars_mismatches = 0
    hand_checked = 0
    hand_mismatches = 0
    board_checked = 0
    board_mismatches = 0

    by_turn: dict[int, list[dict[str, Any]]] = {}
    for e in events:
        t = e.get("round_num")
        if isinstance(t, int):
            by_turn.setdefault(t, []).append(e)
        elif e.get("event_type") == "GAME_START":
            by_turn.setdefault(0, []).append(e)

    def as_event_record(etype: str, data: dict[str, Any]) -> dict[str, Any]:
        return {"event_type": etype, **data}

    for turn in sorted(by_turn.keys()):
        changed: dict[str, dict[str, Any]] = {}
        delta: dict[str, list[Any]] = {
            "offered": [], "accepted": [], "withdrawn": [], "declined": [], "expired": [],
            "resolved": [], "exited": [], "eliminated": [], "rejections": [],
            "messages": [],
        }

        def mark_changed(pid: str, **kv: Any) -> None:
            changed.setdefault(pid, {}).update(kv)

        for e in by_turn[turn]:
            etype = e.get("event_type")
            data = e.get("data", {}) or {}

            if etype == "GAME_START":
                config = _resolve_rules(data)
                for idx, (pid, loan) in enumerate(data.get("initial_loans", {}).items(), start=1):
                    seat_order.append(pid)
                    seats[pid] = _new_seat(pid, idx, loan, config)

            elif etype == "MATCH_OFFERED":
                oid, challenger_id, opponent_id = data["offer_id"], data["challenger_id"], data["opponent_id"]
                offers[oid] = {
                    "offer_id": oid, "challenger_id": challenger_id, "opponent_id": opponent_id,
                    "offered_turn": turn, "accepted_turn": None, "resolved_turn": None,
                    "closed_turn": None, "status": "pending", "outcome": None,
                    "challenger_hand": None, "opponent_hand": None,
                }
                seat = seats[challenger_id]
                seat["reserved_count"] += 1
                mark_changed(challenger_id, reserved_count=seat["reserved_count"])
                delta["offered"].append(oid)

            elif etype == "MATCH_ACCEPTED":
                oid = data["offer_id"]
                offer = offers.get(oid)
                if offer is None:
                    continue
                offer["status"] = "accepted"
                offer["accepted_turn"] = turn
                seat = seats[data["opponent_id"]]
                seat["reserved_count"] += 1
                mark_changed(data["opponent_id"], reserved_count=seat["reserved_count"])
                delta["accepted"].append(oid)

            elif etype in ("MATCH_DECLINED", "MATCH_WITHDRAWN", "MATCH_EXPIRED"):
                oid = data["offer_id"]
                offer = offers.get(oid)
                if offer is None:
                    continue
                status_map = {
                    "MATCH_DECLINED": "declined", "MATCH_WITHDRAWN": "withdrawn", "MATCH_EXPIRED": "expired",
                }
                offer["status"] = status_map[etype]
                offer["closed_turn"] = turn
                seat = seats[offer["challenger_id"]]
                seat["reserved_count"] = max(0, seat["reserved_count"] - 1)
                mark_changed(offer["challenger_id"], reserved_count=seat["reserved_count"])
                delta_key = {"MATCH_DECLINED": "declined", "MATCH_WITHDRAWN": "withdrawn", "MATCH_EXPIRED": "expired"}[etype]
                delta[delta_key].append(oid)

            elif etype == "MATCH_RESOLVED":
                oid = data["offer_id"]
                offer = offers.get(oid)
                if offer is not None:
                    offer.update({
                        "status": "resolved", "resolved_turn": turn, "closed_turn": turn,
                        "outcome": data["outcome"],
                        "challenger_hand": data["challenger_hand"], "opponent_hand": data["opponent_hand"],
                    })
                challenger_id, opponent_id = data["challenger_id"], data["opponent_id"]
                c_seat, o_seat = seats[challenger_id], seats[opponent_id]
                for seat, hand in ((c_seat, data["challenger_hand"]), (o_seat, data["opponent_hand"])):
                    seat["reserved_count"] = max(0, seat["reserved_count"] - 1)
                    seat["hand_total"] = max(0, seat["hand_total"] - 1)
                    if seat["hand_counts"].get(hand, 0) > 0:
                        seat["hand_counts"][hand] -= 1
                    seat["matches_resolved"] += 1
                outcome = data["outcome"]
                if outcome == "challenger_win":
                    c_seat["stars"] += 1
                    o_seat["stars"] -= 1
                    c_seat["wins"] += 1
                    o_seat["losses"] += 1
                elif outcome == "opponent_win":
                    o_seat["stars"] += 1
                    c_seat["stars"] -= 1
                    o_seat["wins"] += 1
                    c_seat["losses"] += 1
                else:
                    c_seat["draws"] += 1
                    o_seat["draws"] += 1
                for pid, seat in ((challenger_id, c_seat), (opponent_id, o_seat)):
                    mark_changed(
                        pid, stars=seat["stars"], reserved_count=seat["reserved_count"],
                        hand_total=seat["hand_total"], matches_resolved=seat["matches_resolved"],
                    )
                delta["resolved"].append(as_event_record("MATCH_RESOLVED", data))

            elif etype in ("MATCH_OFFER_REJECTED", "MATCH_ACCEPT_REJECTED", "EXIT_REJECTED",
                           "REPAY_REJECTED", "TRANSFER_REJECTED",
                           "DM_REJECTED", "BROADCAST_REJECTED", "ANON_BROADCAST_REJECTED"):
                delta["rejections"].append(as_event_record(etype, data))

            elif etype in ("DM_SENT", "BROADCAST_SENT", "ANONYMOUS_BROADCAST_SENT"):
                # 資産・盤面状態には触れない（メッセージは席のstateを変えない）。
                # 投影は_project_delta_record経由でPUBLIC_EVENT_DATA_KEYSに従う
                # （DM本文・匿名senderはそこで自動的に落ちる）。
                delta["messages"].append(as_event_record(etype, data))

            elif etype == "PLAYER_EXITED":
                pid = data["player_id"]
                seat = seats[pid]
                stars_removed_total += seat["stars"]
                seat["status"] = "exited"
                seat["exited_turn"] = turn
                seat["final_assets"] = data.get("final_assets")
                mark_changed(pid, status="exited", exited_turn=turn, final_assets=seat["final_assets"])
                delta["exited"].append(as_event_record("PLAYER_EXITED", data))

            elif etype in ("FORCED_EXIT", "TIMEOUT"):
                pid = data["player_id"]
                seat = seats[pid]
                stars_before = data.get("stars_before")
                stars_checked += 1
                if stars_before is not None and stars_before != seat["stars"]:
                    stars_mismatches += 1
                cards_destroyed = data.get("cards_destroyed")
                hand_checked += 1
                if cards_destroyed is not None and cards_destroyed != seat["hand_total"]:
                    hand_mismatches += 1
                stars_removed_total += data.get("stars_confiscated", seat["stars"])
                seat["status"] = "eliminated"
                seat["exited_turn"] = turn
                seat["elimination_type"] = data.get("elimination_type", etype)
                seat["stars"] = 0
                seat["hand_total"] = 0
                seat["hand_counts"] = {"ROCK": 0, "SCISSORS": 0, "PAPER": 0}
                mark_changed(
                    pid, status="eliminated", exited_turn=turn,
                    elimination_type=seat["elimination_type"], stars=0,
                )
                delta["eliminated"].append(as_event_record(etype, data))

            elif etype == "INTEREST":
                pid = data["player_id"]
                seat = seats[pid]
                seat["debt"] = data.get("new_debt", seat["debt"])
                mark_changed(pid, debt=seat["debt"])

            elif etype == "REPAID":
                pid = data["player_id"]
                seat = seats[pid]
                seat["cash"] = max(0, seat["cash"] - data.get("amount", 0))
                seat["debt"] = data.get("new_debt", seat["debt"])
                mark_changed(pid, cash=seat["cash"], debt=seat["debt"])

            elif etype == "TRANSFERRED":
                amount = data.get("amount", 0)
                src, dst = seats.get(data["from"]), seats.get(data["to"])
                if src is not None:
                    src["cash"] = max(0, src["cash"] - amount)
                    mark_changed(data["from"], cash=src["cash"])
                if dst is not None:
                    dst["cash"] = dst["cash"] + amount
                    mark_changed(data["to"], cash=dst["cash"])

            elif etype == "BOARD_UPDATED":
                board = {k: data.get(k, 0) for k in _INITIAL_HAND_TYPES}
                board_checked += 1
                computed = {k: 0 for k in _INITIAL_HAND_TYPES}
                for seat in seats.values():
                    if seat["status"] != "alive":
                        continue
                    for k in _INITIAL_HAND_TYPES:
                        computed[k] += seat["hand_counts"].get(k, 0)
                if computed != board:
                    board_mismatches += 1

            elif etype == "GAME_END":
                completed = True

            # 未知のイベント種別（LLM_BUDGET_BLOCKED/WAIT_STARTED/ACTION_UNHANDLED等）は
            # 盤面状態に影響しないため無視する（deny-by-defaultで安全側に倒れる）。

        current_turn = turn
        board_history.append({"turn": turn, **board})
        turns_out.append({
            "turn": turn,
            "board": dict(board),
            "alive_count": sum(1 for s in seats.values() if s["status"] == "alive"),
            "seats_changed": changed,
            "delta": delta,
        })

    if config is None:
        config = GameConfig.dev_small()

    stars_in_play = sum(s["stars"] for s in seats.values() if s["status"] == "alive")
    stars_exited_frozen = sum(
        s["stars"] for s in seats.values() if s["status"] == "exited"
    )
    # 退出者は退出時点の★を保持表示するため、ゼロサム計算にはstars_removed_totalの
    # 記録（退出時点の値）を使う。stars_exited_frozenと理論上一致するはずだが、
    # 別経路で算出しているので突き合わせにも使える。
    stars_total_expected = config.num_players * config.initial_stars

    return {
        "seats": [seats[pid] for pid in seat_order],
        "offers": offers,
        "board": board,
        "board_history": board_history,
        "turns": turns_out,
        "current_turn": current_turn,
        "completed": completed,
        "config": config,
        "derivation": {
            "method": "event_fold",
            "stars_total": stars_total_expected,
            "stars_in_play": stars_in_play,
            "stars_removed": stars_removed_total,
            "stars_zero_sum_ok": (stars_in_play + stars_removed_total) == stars_total_expected,
            "stars_cross_check": {"checked": stars_checked, "mismatches": stars_mismatches},
            "hand_cross_check": {"checked": hand_checked, "mismatches": hand_mismatches},
            "board_cross_check": {"checked": board_checked, "mismatches": board_mismatches},
        },
    }


def _project_seat(seat: dict[str, Any], *, view: str, game_ended: bool, reveal_identity: bool) -> dict[str, Any]:
    if view == "god":
        projected = dict(seat)
    else:
        allowed = _PUBLIC_SEAT_POST_GAME_KEYS if game_ended else PUBLIC_SEAT_KEYS
        projected = {k: v for k, v in seat.items() if k in allowed}
    if reveal_identity and "identity" in seat:
        projected["identity"] = seat["identity"]
    return projected


def _project_offer(offer: dict[str, Any], view: str) -> dict[str, Any]:
    if view == "god":
        return dict(offer)
    return {k: v for k, v in offer.items() if k in PUBLIC_OFFER_KEYS}


def _project_turn(turn_entry: dict[str, Any], view: str, game_ended: bool) -> dict[str, Any]:
    if view == "god":
        return {
            "turn": turn_entry["turn"],
            "board": dict(turn_entry["board"]),
            "alive_count": turn_entry["alive_count"],
            "seats_changed": {pid: dict(c) for pid, c in turn_entry["seats_changed"].items()},
            "delta": {k: (list(v) if not isinstance(v, list) else list(v)) for k, v in turn_entry["delta"].items()},
        }

    seat_keys = _PUBLIC_TURN_SEAT_POST_GAME_KEYS if game_ended else PUBLIC_TURN_SEAT_KEYS
    seats_changed = {}
    for pid, changes in turn_entry["seats_changed"].items():
        projected = {k: v for k, v in changes.items() if k in seat_keys}
        if projected:
            seats_changed[pid] = projected

    delta = turn_entry["delta"]
    return {
        "turn": turn_entry["turn"],
        "board": dict(turn_entry["board"]),
        "alive_count": turn_entry["alive_count"],
        "seats_changed": seats_changed,
        "delta": {
            "offered": list(delta["offered"]),
            "accepted": list(delta["accepted"]),
            "withdrawn": list(delta["withdrawn"]),
            "declined": list(delta["declined"]),
            "expired": list(delta["expired"]),
            "resolved": [_project_delta_record(r, view, game_ended) for r in delta["resolved"]],
            "exited": [_project_delta_record(r, view, game_ended) for r in delta["exited"]],
            "eliminated": [_project_delta_record(r, view, game_ended) for r in delta["eliminated"]],
            "rejections": [_project_delta_record(r, view, game_ended) for r in delta["rejections"]],
            "messages": [_project_delta_record(r, view, game_ended) for r in delta["messages"]],
        },
    }


def _project_delta_record(record: dict[str, Any], view: str, game_ended: bool) -> dict[str, Any]:
    """
    turns[].delta 内の各レコード（MATCH_RESOLVED/PLAYER_EXITED/FORCED_EXIT/TIMEOUT/
    *_REJECTED由来）を、既存の`_redact_event`（イベント種別ごとのホワイトリスト）に
    そのまま通して投影する。新しい秘匿ルールを二重管理しないための再利用。
    """
    etype = record.get("event_type")
    data = {k: v for k, v in record.items() if k != "event_type"}
    redacted = _redact_event({"event_type": etype, "data": data}, view, game_ended)
    return {"event_type": etype, **redacted["data"]}


def board_fingerprint(logs_dir: Path, game_id: str) -> str | None:
    """
    `{game_id}_events.jsonl` の現在の状態を表すETag用文字列を返す。
    ファイルが存在しなければNone。同じ値が返る限り`get_board()`の結果も
    変わらない（LogCache.fingerprint()と同じmtime+size基準）。
    """
    return _cache.fingerprint(logs_dir / f"{game_id}_events.jsonl")


def get_board(
    logs_dir: Path, game_id: str, view: str = "public",
    from_turn: int = 0, reveal_identity: bool = False,
) -> dict[str, Any]:
    """
    盤面UI向けの畳み込み済み状態を返す（§8.2の公開/秘匿境界に従う）

    Args:
        view: "public"（既定） または "god"
        from_turn: この値より大きいturnのみ`turns`に含める（差分ポーリング用。0なら全件）
        reveal_identity: publicでもseats[].identityを出すか
            （呼び出し元のviewer/server.pyがVIEWER_REVEAL_IDENTITY環境変数と
            completedの状態から判断する。view="god"では常に出す）
    """
    events = _cache.read_jsonl(logs_dir / f"{game_id}_events.jsonl")
    if not events:
        return {"game_id": game_id, "found": False}

    fold = _fold_events(events)
    game_ended = fold["completed"]

    identities = load_identities(logs_dir, game_id) or {}
    for seat in fold["seats"]:
        identity = identities.get(seat["player_id"])
        if identity is not None:
            seat["identity"] = identity

    total_turns = fold["config"].total_turns
    turns_remaining = 0 if game_ended else max(0, total_turns - fold["current_turn"])

    reveal = reveal_identity or view == "god"
    seats = [
        _project_seat(s, view=view, game_ended=game_ended, reveal_identity=reveal)
        for s in fold["seats"]
    ]
    offers = {oid: _project_offer(o, view) for oid, o in fold["offers"].items()}
    turns = [
        _project_turn(t, view, game_ended)
        for t in fold["turns"] if t["turn"] > from_turn
    ]

    return {
        "game_id": game_id,
        "found": True,
        "view": view,
        "completed": game_ended,
        "current_turn": fold["current_turn"],
        "total_turns": total_turns,
        "turns_remaining": turns_remaining,
        "rules": _rules_dict(fold["config"], total_turns),
        "seats": seats,
        "offers": offers,
        "board": dict(fold["board"]),
        "board_history": fold["board_history"],
        "turns": turns,
        "derivation": fold["derivation"],
    }
