"""Filesystem helpers: the icon must be findable from wherever the app runs."""

from __future__ import annotations

from pathlib import Path

from pdftoolbox import paths


class TestIconPath:
    def test_finds_the_repo_icon_in_dev(self) -> None:
        icon = paths.icon_path()
        assert icon is not None, "assets/pdf-x.ico should be found in the repo"
        assert icon.is_file()
        assert icon.suffix == ".ico"

    def test_icon_is_a_valid_multires_ico(self) -> None:
        from PIL import Image

        icon = paths.icon_path()
        assert icon is not None
        with Image.open(icon) as image:
            assert image.format == "ICO"
            sizes = image.info.get("sizes") or set()
            assert image.convert("RGBA").getchannel("A").getextrema() == (0, 255)
        # Windows needs at least a small title-bar frame and a large one
        assert (16, 16) in sizes
        assert (256, 256) in sizes

    def test_missing_icon_returns_none(self, tmp_path: Path, monkeypatch) -> None:
        # a relocated app with no assets folder must not crash the GUI
        monkeypatch.setattr(paths, "bundle_dir", lambda: tmp_path)
        monkeypatch.setattr(paths, "app_dir", lambda: tmp_path)
        assert paths.icon_path() is None

    def test_frozen_layout_prefers_bundled_copy(self, tmp_path: Path, monkeypatch) -> None:
        # onedir puts datas under _internal; that copy must win over app_dir
        bundled = tmp_path / "_internal" / "assets"
        bundled.mkdir(parents=True)
        (bundled / "pdf-x.ico").write_bytes(b"\x00")
        monkeypatch.setattr(paths, "bundle_dir", lambda: tmp_path / "_internal")
        monkeypatch.setattr(paths, "app_dir", lambda: tmp_path)
        icon = paths.icon_path()
        assert icon is not None
        assert icon.parent == bundled
