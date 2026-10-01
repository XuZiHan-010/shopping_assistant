"""图片工具的失败边界与转换结果；合成图片只写入 pytest 临时目录。"""

import importlib.util
from pathlib import Path
from uuid import UUID

import pytest

from app.analytics.demo_data import build_demo_catalog

SCRIPT = Path(__file__).resolve().parents[4] / "scripts/demo_product_images.py"
spec = importlib.util.spec_from_file_location("demo_product_images", SCRIPT)
assert spec is not None and spec.loader is not None
images = importlib.util.module_from_spec(spec)
spec.loader.exec_module(images)


def test_expected_files_match_catalog() -> None:
    catalog = build_demo_catalog(merchant_id=UUID(int=1), seed=1)
    assert {
        Path(str(row["image_url"])).name for row in catalog if row["image_url"]
    } == images.EXPECTED
    assert "06.webp" not in images.EXPECTED


def test_missing_assets_fail_check(tmp_path: Path) -> None:
    pytest.importorskip("PIL")
    with pytest.raises(ValueError, match="图片清单不符"):
        images.check(tmp_path)


def test_delivered_catalog_assets() -> None:
    # 全套未交付时明确挂起；一旦开始交付，缺图、多图、超限均失败。
    directory = images.DESTINATION
    if not directory.exists():
        pytest.skip("WS Task 12：用户尚未交付 23 张原图；CLI check 仍严格失败")
    actual = {path.name for path in directory.glob("*.webp")}
    assert actual == images.EXPECTED
    for name in actual:
        path = directory / name
        assert 0 < path.stat().st_size <= images.MAX_BYTES


def test_conversion_and_validation(tmp_path: Path) -> None:
    image = pytest.importorskip("PIL.Image")
    source = tmp_path / "source"
    output = tmp_path / "output"
    source.mkdir()
    for name in images.EXPECTED:
        image.new("RGB", (100, 150), "red").save(source / f"{Path(name).stem}-product.png")
    images.convert(source, output)
    images.check(output)
    assert len(list(output.glob("*.webp"))) == 23
    with pytest.raises(ValueError, match="拒绝覆盖"):
        images.convert(source, output)
    image.new("RGB", (10, 10)).save(output / "01.webp")
    with pytest.raises(ValueError, match="800×800"):
        images.check(output)


def test_duplicate_and_forbidden_numbers_rejected(tmp_path: Path) -> None:
    image = pytest.importorskip("PIL.Image")
    image.new("RGB", (10, 10)).save(tmp_path / "06.png")
    with pytest.raises(ValueError, match="06 刻意无图"):
        images.convert(tmp_path, tmp_path / "out")
    (tmp_path / "06.png").unlink()
    for name in ("01-a.png", "01-b.png"):
        image.new("RGB", (10, 10)).save(tmp_path / name)
    with pytest.raises(ValueError, match="多张原图"):
        images.convert(tmp_path, tmp_path / "out")


def test_incomplete_source_does_not_create_destination(tmp_path: Path) -> None:
    pytest.importorskip("PIL")
    with pytest.raises(ValueError, match="原图缺少"):
        images.convert(tmp_path, tmp_path / "out")
    assert not (tmp_path / "out").exists()


@pytest.mark.parametrize("problem", ["corrupt", "extra_destination"])
def test_invalid_batch_leaves_destination_untouched(tmp_path: Path, problem: str) -> None:
    image = pytest.importorskip("PIL.Image")
    source = tmp_path / "source"
    output = tmp_path / "output"
    source.mkdir()
    output.mkdir()
    for name in images.EXPECTED:
        image.new("RGB", (20, 30)).save(source / f"{Path(name).stem}.png")
    if problem == "corrupt":
        (source / "24.png").write_bytes(b"broken image")
    else:
        (output / "06.webp").write_bytes(b"existing")
    before = {path.name: path.read_bytes() for path in output.iterdir()}
    with pytest.raises((ValueError, OSError)):
        images.convert(source, output)
    assert {path.name: path.read_bytes() for path in output.iterdir()} == before


@pytest.mark.parametrize("problem", ["oversize", "wrong_format"])
def test_check_rejects_invalid_encoding(tmp_path: Path, problem: str) -> None:
    image = pytest.importorskip("PIL.Image")
    for name in images.EXPECTED:
        image.new("RGB", (800, 800)).save(tmp_path / name)
    if problem == "oversize":
        (tmp_path / "01.webp").write_bytes(b"x" * (images.MAX_BYTES + 1))
        message = "超过 200KB"
    else:
        image.new("RGB", (800, 800)).save(tmp_path / "01.webp", format="PNG")
        message = "800×800 WebP"
    with pytest.raises(ValueError, match=message):
        images.check(tmp_path)
