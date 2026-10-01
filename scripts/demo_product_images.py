"""WS 商品图片转换与严格校验；通过 uv run --with pillow 运行。"""

from __future__ import annotations

import argparse
import re
from io import BytesIO
from pathlib import Path

DESTINATION = Path(__file__).resolve().parents[1] / "shop/public/demo/products"
EXPECTED = {f"{number:02d}.webp" for number in range(1, 25) if number != 6}
MAX_BYTES = 200 * 1024


def check(directory: Path = DESTINATION) -> None:
    from PIL import Image

    actual = {path.name for path in directory.glob("*.webp")}
    if actual != EXPECTED:
        raise ValueError(
            f"图片清单不符：缺少 {sorted(EXPECTED - actual)}；"
            f"多余 {sorted(actual - EXPECTED)}"
        )
    for name in sorted(EXPECTED):
        path = directory / name
        if path.stat().st_size > MAX_BYTES:
            raise ValueError(f"图片超过 200KB：{name}")
        with Image.open(path) as picture:
            if picture.format != "WEBP" or picture.size != (800, 800):
                raise ValueError(f"图片必须为 800×800 WebP：{name}")
            picture.load()


def convert(source: Path, destination: Path = DESTINATION) -> None:
    from PIL import Image, ImageOps

    if not source.is_dir():
        raise ValueError(f"原图目录不存在：{source}")
    inputs: dict[str, Path] = {}
    for path in source.iterdir():
        if not path.is_file() or path.suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp"}:
            continue
        match = re.match(r"^(\d{2})(?!\d)", path.name)
        if not match:
            continue
        name = f"{match[1]}.webp"
        if name not in EXPECTED:
            raise ValueError(f"不应提供该编号（06 刻意无图）：{path.name}")
        if name in inputs:
            raise ValueError(f"同一编号存在多张原图：{name}")
        inputs[name] = path
    if set(inputs) != EXPECTED:
        raise ValueError(f"原图缺少：{sorted(EXPECTED - set(inputs))}")
    existing = [name for name in EXPECTED if (destination / name).exists()]
    if existing:
        raise ValueError(f"拒绝覆盖已有图片：{sorted(existing)}")
    unexpected = {path.name for path in destination.glob("*.webp")} - EXPECTED
    if unexpected:
        raise ValueError(f"目标目录存在多余图片：{sorted(unexpected)}")
    # 全部成功编码后再写入，坏图或过大的图片不会留下半套资源。
    encoded: dict[str, bytes] = {}
    for name, path in sorted(inputs.items()):
        with Image.open(path) as picture:
            square = ImageOps.fit(
                ImageOps.exif_transpose(picture).convert("RGB"),
                (800, 800), method=Image.Resampling.LANCZOS,
            )
            for quality in range(80, 0, -5):
                buffer = BytesIO()
                square.save(buffer, format="WEBP", quality=quality)
                if buffer.tell() <= MAX_BYTES:
                    encoded[name] = buffer.getvalue()
                    break
            else:
                raise ValueError(f"无法压缩到 200KB：{path.name}")
    destination.mkdir(parents=True, exist_ok=True)
    for name, content in encoded.items():
        with (destination / name).open("xb") as output:
            output.write(content)
    check(destination)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    conversion = commands.add_parser("convert", help="转换完整的 23 张原图，不覆盖已有资源")
    conversion.add_argument("source", type=Path)
    commands.add_parser("check", help="检查入库图片")
    args = parser.parse_args()
    try:
        if args.command == "convert":
            convert(args.source)
        else:
            check()
    except (ValueError, OSError) as error:
        parser.exit(1, f"校验失败：{error}\n")
    print("23 张商品图片校验通过。")


if __name__ == "__main__":
    main()
