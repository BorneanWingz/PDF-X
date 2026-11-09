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


class TestDetectionTuning:
    """Detection defaults are measured, not guessed - see scripts/ocr_benchmark.py.

    Stock RapidOCR downscales an A4 page at 200 DPI and merged table cells; the
    shipped values were chosen because they recover all of them.
    """

    def test_defaults_match_the_benchmarked_values(self) -> None:
        assert ocr_engine.tuning_from_config({}) == {
            "max_side_len": 3000,
            "det_unclip_ratio": 1.8,
        }

    def test_config_overrides_are_used(self) -> None:
        tuning = ocr_engine.tuning_from_config(
            {"ocr_max_side_len": 4000, "ocr_unclip_ratio": 2.0}
        )
        assert tuning == {"max_side_len": 4000, "det_unclip_ratio": 2.0}

    def test_string_numbers_are_coerced(self) -> None:
        # a hand-edited config.json often carries numbers as strings
        tuning = ocr_engine.tuning_from_config(
            {"ocr_max_side_len": "3500", "ocr_unclip_ratio": "1.5"}
        )
        assert tuning == {"max_side_len": 3500, "det_unclip_ratio": 1.5}

    def test_junk_values_fall_back_to_defaults(self) -> None:
        tuning = ocr_engine.tuning_from_config(
            {"ocr_max_side_len": "wide", "ocr_unclip_ratio": None}
        )
        assert tuning == {"max_side_len": 3000, "det_unclip_ratio": 1.8}

    def test_missing_config_is_tolerated(self) -> None:
        assert ocr_engine.tuning_from_config(None) == {
            "max_side_len": 3000,
            "det_unclip_ratio": 1.8,
        }

    def test_engine_receives_the_settings(self) -> None:
        # the pure helper is not enough: the values must reach the detector
        engine = ocr_engine._get_engine()
        assert engine.max_side_len == 3000
        assert engine.text_det.postprocess_op.unclip_ratio == 1.8


class TestDetachedModelSet:
    """models/rapidocr may hold a larger model set beside the exe."""

    def test_absent_by_default(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.setattr(ocr_engine, "models_dir", lambda: tmp_path / "models")
        assert ocr_engine._configured_model_dir() is None

    def test_complete_set_is_detected(self, tmp_path: Path, monkeypatch) -> None:
        root = tmp_path / "models" / "rapidocr"
        root.mkdir(parents=True)
        (root / "det_custom.onnx").write_bytes(b"x")
        (root / "rec_custom.onnx").write_bytes(b"x")
        monkeypatch.setattr(ocr_engine, "models_dir", lambda: tmp_path / "models")
        assert ocr_engine._configured_model_dir() == str(root)

    def test_half_copied_set_is_ignored(self, tmp_path: Path, monkeypatch) -> None:
        # a det without a rec is not a usable pair: fall back to the bundled models
        root = tmp_path / "models" / "rapidocr"
        root.mkdir(parents=True)
        (root / "det_custom.onnx").write_bytes(b"x")
        monkeypatch.setattr(ocr_engine, "models_dir", lambda: tmp_path / "models")
        assert ocr_engine._configured_model_dir() is None

    def test_broken_set_falls_back_instead_of_failing(self, tmp_path: Path, monkeypatch) -> None:
        # a corrupt ONNX file must not take OCR down with it
        root = tmp_path / "models" / "rapidocr"
        root.mkdir(parents=True)
        (root / "det_custom.onnx").write_bytes(b"not an onnx file")
        (root / "rec_custom.onnx").write_bytes(b"not an onnx file")
        monkeypatch.setattr(ocr_engine, "models_dir", lambda: tmp_path / "models")

        engine = ocr_engine._get_engine()

        assert engine is not None
        assert ocr_engine.last_fallback_reason() is not None
        # and the fallback engine still carries the measured tuning
        assert engine.max_side_len == 3000


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
        assert result.name == "scanned_pdfx_searchable.pdf"

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
