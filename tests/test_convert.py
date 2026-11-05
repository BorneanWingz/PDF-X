"""Conversion path tests: every permissive target is exercised end to end."""

from __future__ import annotations

from pathlib import Path

import pypdfium2 as pdfium
import pytest
from openpyxl import load_workbook
from PIL import Image
from pptx import Presentation

from pdftoolbox.convert import convert, list_targets, normalize_target, parse_pages
from pdftoolbox.engines import ConversionError


def _assert_pdf(path: Path) -> None:
    doc = pdfium.PdfDocument(str(path))
    try:
        assert len(doc) >= 1
    finally:
        doc.close()


class TestTargetsAndParsing:
    def test_aliases(self) -> None:
        assert normalize_target("jpeg") == "jpg"
        assert normalize_target("TIFF") == "tif"
        assert normalize_target(".png") == "png"
        assert normalize_target("ocr") == "searchable-pdf"

    def test_parse_pages(self) -> None:
        assert parse_pages("1-3,5") == [1, 2, 3, 5]
        assert parse_pages("2,2,1") == [1, 2]
        assert parse_pages(None) is None
        with pytest.raises(ValueError):
            parse_pages("5-2")

    def test_list_targets_pdf(self, text_pdf: Path) -> None:
        keys = {option.key for option in list_targets(text_pdf)}
        assert {"png", "jpg", "tif", "txt", "html", "xlsx", "pptx", "searchable-pdf"} <= keys

    def test_list_targets_image(self, image_file: Path) -> None:
        options = list_targets(image_file)
        assert [option.key for option in options] == ["pdf"]
        assert options[0].available

    def test_list_targets_unknown(self, tmp_path: Path) -> None:
        weird = tmp_path / "file.xyz"
        weird.write_bytes(b"data")
        assert list_targets(weird) == []


class TestPdfToImages:
    @pytest.mark.parametrize("target", ["png", "jpg", "tif"])
    def test_raster_targets(self, text_pdf: Path, tmp_path: Path, target: str) -> None:
        out = tmp_path / f"out_{target}"
        outputs = convert(text_pdf, target, out_dir=out, dpi=72)
        assert len(outputs) == 2  # two pages
        for path in outputs:
            assert path.exists() and path.suffix == f".{target}"
        with Image.open(outputs[0]) as image:
            assert image.width > 100 and image.height > 100

    def test_page_subset(self, text_pdf: Path, tmp_path: Path) -> None:
        outputs = convert(text_pdf, "png", out_dir=tmp_path / "sel", pages=[2])
        assert len(outputs) == 1
        assert "0002" in outputs[0].name

    def test_page_out_of_range(self, text_pdf: Path, tmp_path: Path) -> None:
        with pytest.raises(ConversionError):
            convert(text_pdf, "png", out_dir=tmp_path / "bad", pages=[99])


class TestTextAndHtml:
    def test_pdf_to_text(self, text_pdf: Path, tmp_path: Path) -> None:
        outputs = convert(text_pdf, "txt", out_dir=tmp_path / "txt")
        content = outputs[0].read_text(encoding="utf-8")
        assert "Hello PDF Toolbox" in content
        assert "Page two content" in content

    def test_pdf_to_html(self, text_pdf: Path, tmp_path: Path) -> None:
        outputs = convert(text_pdf, "html", out_dir=tmp_path / "html")
        content = outputs[0].read_text(encoding="utf-8")
        assert "<html>" in content and "Hello PDF Toolbox" in content


class TestTables:
    def test_pdf_to_xlsx(self, table_pdf: Path, tmp_path: Path) -> None:
        outputs = convert(table_pdf, "xlsx", out_dir=tmp_path / "xlsx")
        workbook = load_workbook(outputs[0])
        sheet = workbook.worksheets[0]
        values = [str(cell.value) for row in sheet.iter_rows() for cell in row if cell.value]
        assert "Item" in values and "Widget" in values and "24.50" in values

    def test_tableless_pdf_raises(self, text_pdf: Path, tmp_path: Path) -> None:
        with pytest.raises(ConversionError, match="no tables"):
            convert(text_pdf, "xlsx", out_dir=tmp_path / "none")


class TestPptx:
    def test_pdf_to_pptx(self, text_pdf: Path, tmp_path: Path) -> None:
        outputs = convert(text_pdf, "pptx", out_dir=tmp_path / "pptx", dpi=72)
        presentation = Presentation(str(outputs[0]))
        assert len(presentation.slides) == 2


class TestToPdf:
    def test_image_to_pdf(self, image_file: Path, tmp_path: Path) -> None:
        outputs = convert(image_file, "pdf", out_dir=tmp_path / "img")
        _assert_pdf(outputs[0])

    def test_markdown_to_pdf(self, markdown_file: Path, tmp_path: Path) -> None:
        outputs = convert(markdown_file, "pdf", out_dir=tmp_path / "md")
        _assert_pdf(outputs[0])

    def test_text_to_pdf(self, plain_text: Path, tmp_path: Path) -> None:
        outputs = convert(plain_text, "pdf", out_dir=tmp_path / "txt")
        _assert_pdf(outputs[0])

    def test_non_pdf_rejects_other_targets(self, image_file: Path) -> None:
        with pytest.raises(ConversionError, match="only supported for PDF inputs"):
            convert(image_file, "png")


class TestErrors:
    def test_missing_input(self, tmp_path: Path) -> None:
        with pytest.raises(ConversionError, match="not found"):
            convert(tmp_path / "nope.pdf", "png")

    def test_unknown_target(self, text_pdf: Path) -> None:
        with pytest.raises(ConversionError, match="unsupported target"):
            convert(text_pdf, "epub")

    def test_unknown_input_type(self, tmp_path: Path) -> None:
        weird = tmp_path / "file.xyz"
        weird.write_bytes(b"data")
        with pytest.raises(ConversionError, match="unsupported type"):
            convert(weird, "pdf")
