"""Plugin loader tests: availability, error containment, and the docx contract."""

from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from pdftoolbox import plugins
from pdftoolbox.paths import plugins_dir


_IMAGE_SUFFIXES = (".png", ".jpeg", ".jpg", ".gif", ".bmp", ".tif", ".tiff", ".emf", ".wmf")


def _media_entries(docx_path: Path) -> list[str]:
    """Every image part inside a DOCX package (word/media/*, thumbnail, ...)."""
    with zipfile.ZipFile(str(docx_path)) as archive:
        return [
            name
            for name in archive.namelist()
            if name.lower().endswith(_IMAGE_SUFFIXES)
        ]


def _drawing_count(docx_path: Path) -> int:
    """<w:drawing>/<w:pict> references in the document body."""
    with zipfile.ZipFile(str(docx_path)) as archive:
        xml = archive.read("word/document.xml").decode("utf-8")
    return xml.count("<w:drawing>") + xml.count("<w:pict>")


@pytest.fixture
def sandbox_plugin(tmp_path: Path):
    """Write a temporary plugin into the real plugins/ folder, then clean up."""
    created: list[Path] = []

    def _write(name: str, source: str) -> Path:
        target = plugins_dir() / name
        target.write_text(source, encoding="utf-8")
        created.append(target)
        return target

    yield _write

    for path in created:
        path.unlink(missing_ok=True)


class TestPdf2DocxPlugin:
    """Real AGPL plugin test; skipped when the agpl extra is not installed."""

    def _plugin_ready(self) -> bool:
        info = plugins.plugin_for_target("docx")
        return bool(info and info.available)

    def test_docx_conversion_and_page_selection(self, text_pdf: Path, tmp_path: Path) -> None:
        if not self._plugin_ready():
            import pytest

            pytest.skip("pdf2docx not installed (uv sync --extra agpl)")
        from docx import Document

        from pdftoolbox.convert import convert

        outputs = convert(text_pdf, "docx", out_dir=tmp_path / "docx", pages=[2])
        document = Document(str(outputs[0]))
        text = "\n".join(paragraph.text for paragraph in document.paragraphs)
        assert "Page two content" in text
        assert "Hello PDF Toolbox" not in text

    def test_docx_keeps_no_media_for_text_only_pdf(
        self, text_pdf: Path, tmp_path: Path
    ) -> None:
        # a text-only sample has no picture, so nothing is kept and nothing is
        # duplicated - this is the baseline the illustration test builds on
        if not self._plugin_ready():
            import pytest

            pytest.skip("pdf2docx not installed (uv sync --extra agpl)")

        from pdftoolbox.convert import convert

        outputs = convert(text_pdf, "docx", out_dir=tmp_path / "docx")
        assert _media_entries(outputs[0]) == []
        assert _drawing_count(outputs[0]) == 0

    def test_docx_keeps_real_illustrations(
        self, illustration_pdf: Path, tmp_path: Path
    ) -> None:
        # a real picture is content: it must reach the DOCX, while a whole-page
        # scan raster (not present here) is the only thing stripped
        if not self._plugin_ready():
            import pytest

            pytest.skip("pdf2docx not installed (uv sync --extra agpl)")
        from pdftoolbox.convert import convert

        outputs = convert(illustration_pdf, "docx", out_dir=tmp_path / "docx")
        media = _media_entries(outputs[0])
        assert len(media) == 1, f"the illustration should survive, got {media}"
        assert _drawing_count(outputs[0]) >= 1

    def test_docx_strips_whole_page_scan_raster(
        self, scanned_pdf: Path, tmp_path: Path
    ) -> None:
        # a scan is one page-sized image; keeping it would make the DOCX a
        # picture of the page with an invisible text layer over it
        if not self._plugin_ready():
            import pytest

            pytest.skip("pdf2docx not installed (uv sync --extra agpl)")
        from pdftoolbox.convert import convert

        outputs = convert(scanned_pdf, "docx", out_dir=tmp_path / "docx", ocr_dpi=200)
        assert _media_entries(outputs[0]) == []
        assert _drawing_count(outputs[0]) == 0

    def test_docx_keeps_text_after_image_removal(self, text_pdf: Path, tmp_path: Path) -> None:
        if not self._plugin_ready():
            import pytest

            pytest.skip("pdf2docx not installed (uv sync --extra agpl)")
        from docx import Document

        from pdftoolbox.convert import convert

        outputs = convert(text_pdf, "docx", out_dir=tmp_path / "docx")
        document = Document(str(outputs[0]))
        text = "\n".join(paragraph.text for paragraph in document.paragraphs)
        assert "Hello PDF Toolbox" in text
        assert "Page two content" in text

    def test_docx_package_stays_valid(self, text_pdf: Path, tmp_path: Path) -> None:
        # a stripped package must still open: no dangling content types or rels
        if not self._plugin_ready():
            import pytest

            pytest.skip("pdf2docx not installed (uv sync --extra agpl)")
        from docx import Document

        from pdftoolbox.convert import convert

        outputs = convert(text_pdf, "docx", out_dir=tmp_path / "docx")
        with zipfile.ZipFile(str(outputs[0])) as archive:
            assert archive.testzip() is None
            content_types = archive.read("[Content_Types].xml").decode("utf-8")
            # no image part survives for this text-only sample, so no image
            # content-type default may outlive the parts that needed it
            for name in archive.namelist():
                if name.endswith(".rels"):
                    assert "image" not in archive.read(name).decode("utf-8")
        assert 'Extension="png"' not in content_types
        assert 'Extension="jpeg"' not in content_types
        Document(str(outputs[0]))  # must not raise


ECHO_PLUGIN = """
from pathlib import Path

NAME = "echo"
VERSION = "0.0.1"
LICENSE = "MIT"
TARGETS = ["echo"]

def available() -> bool:
    return True

def convert(src: Path, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / (src.stem + ".echo")
    out.write_text("converted " + src.name, encoding="utf-8")
    return out
"""

BROKEN_PLUGIN = """
this is not valid python((
"""

UNAVAILABLE_PLUGIN = """
from pathlib import Path

NAME = "needs-magic"
TARGETS = ["magic"]
AVAILABILITY_HINT = "magic library missing"

def available() -> bool:
    return False

def convert(src: Path, out_dir: Path) -> Path:
    raise RuntimeError("never reachable while unavailable")
"""


class TestPluginDiscovery:
    def test_real_pdf2docx_plugin_loads(self) -> None:
        found = plugins.load_plugins()
        docx = [info for info in found.values() if "docx" in info.targets]
        assert docx, "pdf2docx_plugin.py should be discovered from plugins/"
        info = docx[0]
        assert info.name == "pdf2docx"
        # available() depends on whether pdf2docx is installed in this venv
        assert info.status in {"ready", "unavailable"}
        if info.status == "unavailable":
            assert "pdf2docx" in info.hint

    def test_echo_plugin_roundtrip(self, sandbox_plugin, text_pdf: Path, tmp_path: Path) -> None:
        sandbox_plugin("sandbox_echo.py", ECHO_PLUGIN)

        from pdftoolbox.convert import convert

        outputs = convert(text_pdf, "echo", out_dir=tmp_path / "echo")
        assert outputs[0].read_text(encoding="utf-8") == f"converted {text_pdf.name}"

    def test_broken_plugin_is_contained(self, sandbox_plugin) -> None:
        sandbox_plugin("sandbox_broken.py", BROKEN_PLUGIN)
        found = plugins.load_plugins()
        broken = [info for info in found.values() if info.name == "sandbox_broken"]
        assert broken and broken[0].status == "error"

    def test_unavailable_plugin_reports_hint(self, sandbox_plugin) -> None:
        sandbox_plugin("sandbox_unavailable.py", UNAVAILABLE_PLUGIN)
        found = plugins.load_plugins()
        info = found.get("needs-magic")
        assert info is not None
        assert info.status == "unavailable"
        assert "magic library missing" in info.hint
