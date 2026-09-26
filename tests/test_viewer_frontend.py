"""
viewer/static/index.html・style.css の静的検証（サイクル1.7: 盤面UI化）

JSテスト基盤を新設しない方針（ライブラリ・ビルド工程を増やさない）のため、
Pythonから静的にHTMLを検査することで「クリックしても何も起きない」
「参照している画像が存在しない」「外部CDNを読み込んでいる」といった
リネーム漏れ・参照切れ・方針違反を機械的に検出する。
"""

import hashlib
import re
from pathlib import Path

STATIC_DIR = Path(__file__).resolve().parent.parent / "viewer" / "static"

# dangou-cardから移植したCSS本体（1〜529行目）のsha256。追記のみルールの担保。
# 変更する場合はdangou-card側との同一性が崩れることを理解した上で意図的に更新すること。
_STYLE_CSS_PREFIX_SHA256 = "c5109e6a1f5205899c56018eb3a936a71b60d67db6347117d5d8b55ecf33f283"
_STYLE_CSS_PREFIX_LINES = 529


def _index_html() -> str:
    return (STATIC_DIR / "index.html").read_text(encoding="utf-8")


def test_all_getelementbyid_targets_exist_in_html():
    """JS内のgetElementById('X')とHTML内のid="X"を突き合わせる（リネーム漏れ検出）"""
    html = _index_html()
    used = set(re.findall(r"getElementById\(\s*[\"']([\w-]+)[\"']\s*\)", html))
    defined = set(re.findall(r'\bid="([\w-]+)"', html))
    missing = used - defined
    assert not missing, f"参照されているが存在しないID: {missing}"


def test_no_external_resources():
    """CDN・外部URLを一切読み込まない（ライブラリ・ビルド工程を増やさない方針の機械的担保）"""
    html = _index_html()
    assert "http://" not in html
    assert "https://" not in html
    assert not re.search(r'<script[^>]+src=', html), "外部scriptタグは禁止"


def test_static_asset_references_resolve():
    """index.html内のhref=/src=の相対パスがviewer/static/配下に実在する"""
    html = _index_html()
    refs = re.findall(r'(?:href|src)="(/static/[^"]+)"', html)
    assert refs, "静的アセット参照が1件も無い（テスト自体が意味を失っていないか確認）"
    for ref in refs:
        rel = ref[len("/static/"):]
        assert (STATIC_DIR / rel).exists(), f"参照先が存在しない: {ref}"


def test_style_css_prefix_unchanged():
    """style.cssの先頭529行（dangou-card移植分）が無改変であることを保証する"""
    lines = (STATIC_DIR / "style.css").read_text(encoding="utf-8").splitlines(keepends=True)
    prefix = "".join(lines[:_STYLE_CSS_PREFIX_LINES])
    digest = hashlib.sha256(prefix.encode("utf-8")).hexdigest()
    assert digest == _STYLE_CSS_PREFIX_SHA256, (
        "style.cssの先頭529行が変更されている。dangou-card由来部分は追記のみで、"
        "既存行を書き換えない設計（rules/project.md参照）。意図的な変更なら"
        "このテストのハッシュ値を更新すること。"
    )


def test_single_inline_script():
    """<script>はhead(FOUC防止テーマ)1本+body(本体)1本=2本であること"""
    html = _index_html()
    scripts = re.findall(r"<script>", html)
    assert len(scripts) == 2


def test_hand_glyph_table_covers_all_hand_types():
    """HAND_GLYPH/HAND_JAがengine.models.Hand enum(ROCK/SCISSORS/PAPER)を過不足なく網羅する"""
    from engine.models import Hand
    html = _index_html()
    hand_glyph_line = re.search(r"const HAND_GLYPH = \{([^}]+)\}", html).group(1)
    for hand in Hand:
        assert hand.value in hand_glyph_line, f"{hand.value}がHAND_GLYPHに無い"


def test_emotion_tables_cover_all_valid_emotions():
    """EMOTION_EN/EMOTION_EMOJIがllm.response_parser.VALID_EMOTIONSの7種と一致する"""
    from llm.response_parser import VALID_EMOTIONS
    html = _index_html()
    for emotion in VALID_EMOTIONS:
        assert emotion in html, f"感情語彙{emotion}がEMOTION_EN/EMOTION_EMOJIテーブルに無い"
