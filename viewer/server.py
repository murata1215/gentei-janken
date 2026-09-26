"""
観戦ビューア FastAPI サーバー

環境変数で設定可能:
  VIEWER_HOST        バインドアドレス（既定: 127.0.0.1）
  VIEWER_PORT        ポート（既定: 9027）
  VIEWER_ROOT_PATH   サブパス配信用（既定: 空）
  VIEWER_LOG_ROOT    ログディレクトリ（既定: logs/llm）
  VIEWER_TOKEN       簡易認証トークン（未設定: 認証なし）
  VIEWER_GOD_TOKEN   神視点トークン（未設定: 神視点は無効）
  VIEWER_GOD_PUBLIC  神視点をトークン無しで全員に公開する（1/true/yes/on で有効。既定: 無効）
  VIEWER_REVEAL_IDENTITY
                     public viewでプレイヤーの正体（モデル名等）を出す条件。
                     never（常に出さない） / after_game_end（GAME_END後のみ、既定）
                     / always（進行中も出す）。god viewは常に出す。

dangou-card の public/god 2段認証パターン（check_token / check_view）をそのまま
流用する（rules/project.md「Viewerの公開表示と神視点を分離する」参照）。
"""

import os
import secrets
from pathlib import Path
from typing import Optional

from fastapi import Depends, FastAPI, HTTPException, Path as PathParam, Query, Request, Response
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from viewer.log_parser import board_fingerprint, get_board, get_game_state, get_round_states, list_games

# --- 既定値の単一ソース ---
# 変更する場合は Caddy sites.d の reverse_proxy 先と doc/viewer_operations.md も
# 必ず同時に更新すること（tests/test_viewer.py でドリフトを検知する）。
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 9027

# game_id はログファイル名の一部として使われるため、パストラバーサル対策として
# 英数字・アンダースコア・ドット・ハイフンのみを許可する。
GAME_ID_PATTERN = r"^[A-Za-z0-9_.\-]+$"

# --- 環境変数による設定 ---
DEFAULT_LOGS_DIR = Path(__file__).resolve().parent.parent / "logs" / "llm"
STATIC_DIR = Path(__file__).resolve().parent / "static"

HOST = os.environ.get("VIEWER_HOST", DEFAULT_HOST)
PORT = int(os.environ.get("VIEWER_PORT", str(DEFAULT_PORT)))
ROOT_PATH = os.environ.get("VIEWER_ROOT_PATH", "")
LOGS_DIR = Path(os.environ.get("VIEWER_LOG_ROOT", str(DEFAULT_LOGS_DIR)))
TOKEN = os.environ.get("VIEWER_TOKEN", "")
GOD_TOKEN = os.environ.get("VIEWER_GOD_TOKEN", "")
GOD_PUBLIC = os.environ.get("VIEWER_GOD_PUBLIC", "0").strip().lower() in {"1", "true", "yes", "on"}
REVEAL_IDENTITY = os.environ.get("VIEWER_REVEAL_IDENTITY", "after_game_end").strip().lower()
if REVEAL_IDENTITY not in {"never", "after_game_end", "always"}:
    REVEAL_IDENTITY = "after_game_end"

# --- FastAPIアプリ ---
app = FastAPI(
    title="限定ジャンケン 観戦ビューア",
    version="0.1",
    root_path=ROOT_PATH,
)

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


async def check_token(request: Request, token: Optional[str] = Query(None)):
    """VIEWER_TOKEN設定時のみ ?token= またはX-Viewer-Tokenヘッダで照合する"""
    if not TOKEN:
        return
    provided = token or request.headers.get("X-Viewer-Token", "")
    if provided != TOKEN:
        raise HTTPException(status_code=401, detail="Unauthorized")


def check_view(request: Request, view: str) -> str:
    """
    神視点は通常Viewer認証とは別の明示的トークンで保護する（§8.2の秘匿境界）。

    VIEWER_GOD_PUBLIC が真の間はトークン検査自体をスキップする。
    """
    if view not in {"public", "god"}:
        raise HTTPException(status_code=400, detail="view must be public or god")
    if view == "god" and not GOD_PUBLIC:
        provided = request.headers.get("X-Viewer-God-Token", "")
        if not GOD_TOKEN or not secrets.compare_digest(provided, GOD_TOKEN):
            raise HTTPException(status_code=403, detail="God view is unavailable or unauthorized")
    return view


@app.get("/")
async def index(_=Depends(check_token)):
    """観戦ビューア本体（トップページ）"""
    return FileResponse(str(STATIC_DIR / "index.html"))


@app.get("/watch")
async def watch(_=Depends(check_token)):
    """観戦ビューア本体"""
    return FileResponse(str(STATIC_DIR / "index.html"))


@app.get("/api/config")
async def api_config(_=Depends(check_token)):
    """フロントエンドが神視点の利用可否を判断するための公開設定を返す"""
    return {"god_public": GOD_PUBLIC, "god_available": GOD_PUBLIC or bool(GOD_TOKEN)}


@app.get("/api/games")
async def api_games(_=Depends(check_token)):
    """試合一覧を返す"""
    return list_games(LOGS_DIR)


@app.get("/api/games/{game_id}/state")
async def api_game_state(
    request: Request,
    game_id: str = PathParam(..., pattern=GAME_ID_PATTERN),
    view: str = Query("public"),
    _=Depends(check_token),
):
    """試合の現在状態サマリを返す（§8.2の公開/秘匿境界に従う）"""
    return get_game_state(LOGS_DIR, game_id, view=check_view(request, view))


@app.get("/api/games/{game_id}/turns")
async def api_turns(
    request: Request,
    game_id: str = PathParam(..., pattern=GAME_ID_PATTERN),
    view: str = Query("public"),
    _=Depends(check_token),
):
    """
    ターン別の盤面状況を返す（§8.2の公開/秘匿境界に従う）

    このエンドポイントは生イベントのredact済みダンプ（監査・デバッグ用）。
    盤面UIは `/api/games/{game_id}/board` を使う。
    """
    return get_round_states(LOGS_DIR, game_id, view=check_view(request, view))


def _should_reveal_identity(view: str, completed: bool) -> bool:
    """VIEWER_REVEAL_IDENTITYの設定に基づき、publicでプレイヤーの正体を出すか判定する"""
    if view == "god":
        return True
    if REVEAL_IDENTITY == "always":
        return True
    if REVEAL_IDENTITY == "after_game_end":
        return completed
    return False  # "never"


@app.get("/api/games/{game_id}/board")
async def api_board(
    request: Request,
    response: Response,
    game_id: str = PathParam(..., pattern=GAME_ID_PATTERN),
    view: str = Query("public"),
    from_turn: int = Query(0, ge=0),
    _=Depends(check_token),
):
    """
    盤面UI向けの畳み込み済み状態を返す（§8.2の公開/秘匿境界に従う）

    サーバ側でイベント列を畳み込み、席（★・生死・初期借入額等）・申込索引・
    掲示板の時系列を構築する。public/godの投影も本エンドポイント内で確定する
    （フロントに秘匿判定ロジックを持たせない）。

    `If-None-Match` が現在のログのfingerprintと一致すれば304を返す
    （2秒ポーリング時の帯域対策。完走試合はfingerprintが恒久的に一致するため
    実質304のみになる）。
    """
    view = check_view(request, view)
    fp = board_fingerprint(LOGS_DIR, game_id)
    etag = f'"{fp}"' if fp is not None else None
    if etag is not None and request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers={"ETag": etag})

    # reveal_identity判定にはcompletedが要るが、フルの畳み込みを2回行うのは
    # 無駄なので、軽量なget_game_state()でcompletedだけ先に確認する
    # （get_game_stateは1パス走査のみで、席別状態を組み立てる畳み込みより軽い）。
    state = get_game_state(LOGS_DIR, game_id, view="god")
    if not state.get("found"):
        return {"game_id": game_id, "found": False}
    reveal_identity = _should_reveal_identity(view, state["completed"])
    result = get_board(LOGS_DIR, game_id, view=view, from_turn=from_turn, reveal_identity=reveal_identity)
    if etag is not None:
        response.headers["ETag"] = etag
    return result


def main():
    """サーバー起動"""
    import uvicorn
    print("=== 限定ジャンケン 観戦ビューア ===")
    print(f"URL: http://{HOST}:{PORT}")
    if ROOT_PATH:
        print(f"Root path: {ROOT_PATH}")
    print("認証: 有効（VIEWER_TOKEN設定済み）" if TOKEN else "認証: なし（公開アクセス可）")
    if GOD_PUBLIC:
        print("神視点: フリー公開（VIEWER_GOD_PUBLIC=1、トークン不要）")
    else:
        print("神視点: 有効" if GOD_TOKEN else "神視点: 無効（VIEWER_GOD_TOKEN未設定）")
    print(f"ログ: {LOGS_DIR}")
    print("---")
    uvicorn.run(app, host=HOST, port=PORT)
