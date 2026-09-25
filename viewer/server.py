"""
観戦ビューア FastAPI サーバー

環境変数で設定可能:
  VIEWER_HOST        バインドアドレス（既定: 0.0.0.0）
  VIEWER_PORT        ポート（既定: 9024）
  VIEWER_ROOT_PATH   サブパス配信用（既定: 空）
  VIEWER_LOG_ROOT    ログディレクトリ（既定: logs/llm）
  VIEWER_TOKEN       簡易認証トークン（未設定: 認証なし）
  VIEWER_GOD_TOKEN   神視点トークン（未設定: 神視点は無効）
  VIEWER_GOD_PUBLIC  神視点をトークン無しで全員に公開する（1/true/yes/on で有効。既定: 無効）

dangou-card の public/god 2段認証パターン（check_token / check_view）をそのまま
流用する（rules/project.md「Viewerの公開表示と神視点を分離する」参照）。
"""

import os
import secrets
from pathlib import Path
from typing import Optional

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from viewer.log_parser import get_game_state, get_round_states, list_games

# --- 環境変数による設定 ---
DEFAULT_LOGS_DIR = Path(__file__).resolve().parent.parent / "logs" / "llm"
STATIC_DIR = Path(__file__).resolve().parent / "static"

HOST = os.environ.get("VIEWER_HOST", "0.0.0.0")
PORT = int(os.environ.get("VIEWER_PORT", "9024"))
ROOT_PATH = os.environ.get("VIEWER_ROOT_PATH", "")
LOGS_DIR = Path(os.environ.get("VIEWER_LOG_ROOT", str(DEFAULT_LOGS_DIR)))
TOKEN = os.environ.get("VIEWER_TOKEN", "")
GOD_TOKEN = os.environ.get("VIEWER_GOD_TOKEN", "")
GOD_PUBLIC = os.environ.get("VIEWER_GOD_PUBLIC", "0").strip().lower() in {"1", "true", "yes", "on"}

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
async def api_game_state(game_id: str, _=Depends(check_token)):
    """試合の現在状態サマリを返す"""
    return get_game_state(LOGS_DIR, game_id)


@app.get("/api/games/{game_id}/turns")
async def api_turns(game_id: str, request: Request, view: str = Query("public"), _=Depends(check_token)):
    """ターン別の盤面状況を返す（§8.2の公開/秘匿境界に従う）"""
    return get_round_states(LOGS_DIR, game_id, view=check_view(request, view))


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
