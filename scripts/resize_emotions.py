"""
感情画像アセットのリサイズスクリプト（サイクル1.6.1）

viewer/static/emotions/ の42枚（1254x1254、合計56MB）は観戦ビューアで
20〜44px程度でしか表示しないため、最大63倍の過剰解像度になっている。
公開済みViewer（Caddy経由）なのでegressに直撃するため、128px版を
別ディレクトリに生成する。原寸は記事・ブログ用途に残すため削除しない。

使い方:
    uv run python scripts/resize_emotions.py
"""

from pathlib import Path

from PIL import Image

SRC_DIR = Path(__file__).resolve().parent.parent / "viewer" / "static" / "emotions"
DST_DIR = SRC_DIR / "128"
TARGET_SIZE = 128


def main() -> None:
    if not SRC_DIR.exists():
        print(f"元ディレクトリが見つかりません: {SRC_DIR}")
        return

    DST_DIR.mkdir(parents=True, exist_ok=True)

    src_files = sorted(p for p in SRC_DIR.glob("*.png") if p.parent == SRC_DIR)
    if not src_files:
        print(f"元画像が見つかりません: {SRC_DIR}/*.png")
        return

    total_src_bytes = 0
    total_dst_bytes = 0

    for src_path in src_files:
        dst_path = DST_DIR / src_path.name
        with Image.open(src_path) as img:
            img = img.convert("RGB")
            img = img.resize((TARGET_SIZE, TARGET_SIZE), Image.LANCZOS)
            img.save(dst_path, "PNG", optimize=True)

        src_size = src_path.stat().st_size
        dst_size = dst_path.stat().st_size
        total_src_bytes += src_size
        total_dst_bytes += dst_size
        print(f"{src_path.name}: {src_size/1024:.0f}KB -> {dst_size/1024:.0f}KB")

    print("---")
    print(f"生成枚数: {len(src_files)}")
    print(f"元合計: {total_src_bytes/1024/1024:.1f}MB -> 128px合計: {total_dst_bytes/1024/1024:.1f}MB")
    print(f"出力先: {DST_DIR}")


if __name__ == "__main__":
    main()
