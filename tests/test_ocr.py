"""OCR and searchable-PDF tests. Require the bundled RapidOCR models."""

from __future__ import annotations

from pathlib import Path

import pypdfium2 as pdfium
import pytest
from PIL import Image, ImageDraw, ImageFont

from pdftoolbox.convert import convert
from pdftoolbox.engines import ocr as ocr_engine


def _text_image() -> Image.Image:
    image = Image.new("RGB", (1200, 360), "white")
    draw = ImageDraw.Draw(image)
    try:
        font = ImageFont.truetype("C:/Windows/Fonts/arial.ttf", 90)
    except OSError:
        font = ImageFont.load_default()
    draw.text((50, 130), "HELLO OCR", fill="black", font=font)
    return image


@pytest.fixture(autouse=True)
def _reset_engine():
    ocr_engine.reset_engine()
    yield
    ocr_engine.reset_engine()


class TestOcrImage:
    def test_recognizes_text(self) -> None:
        lines, average = ocr_engine.ocr_image(_text_image())
        joined = " ".join(line.text.upper() for line in lines)
        assert "HELLO" in joined
        assert average > 0.5


class TestOcrPdf:
    def test_ocr_scanned_pdf(self, scanned_pdf: Path) -> None:
        pages = ocr_engine.ocr_pdf(scanned_pdf, dpi=200)
        assert len(pages) == 1
        assert "HELLO" in pages[0].text.upper()

    def test_progress_callback(self, scanned_pdf: Path) -> None:
        seen: list[tuple[int, int]] = []
        ocr_engine.ocr_pdf(scanned_pdf, dpi=150, on_progress=lambda d, t: seen.append((d, t)))
        assert seen == [(1, 1)]


class TestSearchablePdf:
    def test_output_contains_text_layer(self, scanned_pdf: Path, tmp_path: Path) -> None:
        outputs = convert(scanned_pdf, "searchable-pdf", out_dir=tmp_path / "ocr", ocr_dpi=200)
        result = outputs[0]
        assert result.name == "scanned_searchable.pdf"

        from pypdf import PdfReader

        reader = PdfReader(str(result))
        text = reader.pages[0].extract_text() or ""
        assert "HELLO" in text.upper()
        assert len(reader.pages) == 1

    def test_original_page_count_preserved(self, text_pdf: Path, tmp_path: Path) -> None:
        outputs = convert(text_pdf, "searchable-pdf", out_dir=tmp_path / "ocr2", ocr_dpi=150)
        doc = pdfium.PdfDocument(str(outputs[0]))
        try:
            assert len(doc) == 2
        finally:
            doc.close()

    def test_page_selection_limits_output(self, text_pdf: Path, tmp_path: Path) -> None:
        outputs = convert(
            text_pdf, "searchable-pdf", out_dir=tmp_path / "ocr3", ocr_dpi=150, pages=[2]
        )
        doc = pdfium.PdfDocument(str(outputs[0]))
        try:
            assert len(doc) == 1
        finally:
            doc.close()
