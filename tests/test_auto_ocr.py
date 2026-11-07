"""Auto-OCR: a scan is OCR'd before any text-reading conversion runs.

NOTE: like test_ocr.py these tests drive the real RapidOCR engine, so they are
among the slow ones in the suite.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

from pdftoolbox import convert as convert_module
from pdftoolbox import plugins
from pdftoolbox.convert import convert, convert_many
from pdftoolbox.engines import ConversionError
from pdftoolbox.engines import ocr as ocr_engine
from pdftoolbox.engines import pdf_text


@pytest.fixture(autouse=True)
def _reset_engine():
    ocr_engine.reset_engine()
    yield
    ocr_engine.reset_engine()


def _boom(*_args, **_kwargs):
    raise AssertionError("OCR must not run for this conversion")


def _ocr_spy(seen: list[str]):
    """Wrap ocr_pdf so a test can prove OCR ran, and on which file."""
    real = ocr_engine.ocr_pdf

    def _spy(src, *args, **kwargs):
        seen.append(Path(src).name)
        return real(src, *args, **kwargs)

    return _spy


class TestTextLayerDetection:
    def test_searchable_pdf_has_layer(self, text_pdf: Path) -> None:
        assert pdf_text.has_text_layer(text_pdf)

    def test_scanned_pdf_has_no_layer(self, scanned_pdf: Path) -> None:
        assert not pdf_text.has_text_layer(scanned_pdf)

    def test_threshold_is_configurable(self, tmp_path: Path) -> None:
        path = tmp_path / "tiny.pdf"
        pdf = canvas.Canvas(str(path), pagesize=A4)
        pdf.drawString(72, 720, "12345")
        pdf.showPage()
        pdf.save()
        assert not pdf_text.has_text_layer(path)  # 5 chars < default 20
        assert pdf_text.has_text_layer(path, min_chars=5)


class TestOcrFirstTargets:
    def test_target_set_is_the_documented_one(self) -> None:
        assert convert_module.OCR_FIRST_TARGETS == {
            "txt",
            "html",
            "xlsx",
            "pptx",
            "docx",
        }

    def test_image_and_ocr_targets_are_excluded(self) -> None:
        assert not convert_module.OCR_FIRST_TARGETS & {"png", "jpg", "tif"}
        assert "searchable-pdf" not in convert_module.OCR_FIRST_TARGETS
class TestSearchablePdfSkipsOcr:
    def test_txt_does_not_ocr(self, text_pdf: Path, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.setattr(ocr_engine, "ocr_pdf", _boom)
        outputs = convert(text_pdf, "txt", out_dir=tmp_path / "txt")
        assert "Hello PDF Toolbox" in outputs[0].read_text(encoding="utf-8")

    def test_xlsx_does_not_ocr(self, table_pdf: Path, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.setattr(ocr_engine, "ocr_pdf", _boom)
        outputs = convert(table_pdf, "xlsx", out_dir=tmp_path / "xlsx")
        assert outputs[0].suffix == ".xlsx"

    def test_png_does_not_ocr(self, scanned_pdf: Path, tmp_path: Path, monkeypatch) -> None:
        # rendering page pixels never needs a text layer
        monkeypatch.setattr(ocr_engine, "ocr_pdf", _boom)
        outputs = convert(scanned_pdf, "png", out_dir=tmp_path / "png", dpi=72)
        assert len(outputs) == 1
        with Image.open(outputs[0]) as image:
            assert image.width > 100


class TestScannedPdfOcrsFirst:
    def test_txt(self, scanned_pdf: Path, tmp_path: Path, monkeypatch) -> None:
        seen: list[str] = []
        monkeypatch.setattr(ocr_engine, "ocr_pdf", _ocr_spy(seen))
        outputs = convert(scanned_pdf, "txt", out_dir=tmp_path / "txt", ocr_dpi=200)
        assert seen == ["scanned.pdf"]  # OCR ran, and it ran on the original
        assert "HELLO" in outputs[0].read_text(encoding="utf-8").upper()

    def test_html(self, scanned_pdf: Path, tmp_path: Path, monkeypatch) -> None:
        seen: list[str] = []
        monkeypatch.setattr(ocr_engine, "ocr_pdf", _ocr_spy(seen))
        outputs = convert(scanned_pdf, "html", out_dir=tmp_path / "html", ocr_dpi=200)
        assert seen == ["scanned.pdf"]
        assert "HELLO" in outputs[0].read_text(encoding="utf-8").upper()

    def test_pptx(self, scanned_pdf: Path, tmp_path: Path, monkeypatch) -> None:
        from pptx import Presentation

        seen: list[str] = []
        monkeypatch.setattr(ocr_engine, "ocr_pdf", _ocr_spy(seen))
        outputs = convert(
            scanned_pdf, "pptx", out_dir=tmp_path / "pptx", dpi=72, ocr_dpi=200
        )
        assert seen == ["scanned.pdf"]
        assert len(Presentation(str(outputs[0])).slides) == 1

    def test_xlsx(self, scanned_table_pdf: Path, tmp_path: Path, monkeypatch) -> None:
        from openpyxl import load_workbook

        seen: list[str] = []
        monkeypatch.setattr(ocr_engine, "ocr_pdf", _ocr_spy(seen))
        outputs = convert(
            scanned_table_pdf, "xlsx", out_dir=tmp_path / "xlsx", ocr_dpi=200
        )
        assert seen == ["scanned_table.pdf"]
        workbook = load_workbook(outputs[0])
        values = [
            str(cell.value)
            for row in workbook.worksheets[0].iter_rows()
            for cell in row
            if cell.value
        ]
        assert "Item" in values and "Widget" in values and "24.50" in values

    def test_xlsx_holds_no_images(self, table_pdf: Path, tmp_path: Path) -> None:
        # the sheet must be real cells, never a screenshot of the page
        from openpyxl import load_workbook

        outputs = convert(table_pdf, "xlsx", out_dir=tmp_path / "xlsx")
        workbook = load_workbook(outputs[0])
        assert all(not worksheet._images for worksheet in workbook.worksheets)


class TestMultipleTables:
    """A scanned page with several tables must export all of them."""

    def test_every_table_reaches_its_own_sheet(
        self, scanned_two_tables_pdf: Path, tmp_path: Path
    ) -> None:
        from openpyxl import load_workbook

        outputs = convert(
            scanned_two_tables_pdf, "xlsx", out_dir=tmp_path / "xlsx", ocr_dpi=200
        )
        workbook = load_workbook(outputs[0])
        assert len(workbook.worksheets) == 2, "both tables should get a sheet"

        first = [
            [cell for cell in row if cell is not None]
            for row in workbook.worksheets[0].iter_rows(values_only=True)
        ]
        second = [
            [cell for cell in row if cell is not None]
            for row in workbook.worksheets[1].iter_rows(values_only=True)
        ]

        # each table keeps its own header row
        assert first[0][0] == "Sample"
        assert "Moisture" in first[0]
        assert second[0][0] == "Sample"
        assert "Potassium" in second[0]

        # and its data rows
        flat_first = " ".join(str(v) for row in first for v in row)
        flat_second = " ".join(str(v) for row in second for v in row)
        assert "FWR1" in flat_first and "73.30" in flat_first
        assert "AK4R1" in flat_second and "32.22" in flat_second

    def test_header_row_is_not_dropped(
        self, scanned_two_tables_pdf: Path, tmp_path: Path
    ) -> None:
        # regression: a header OCR groups as its own band used to be discarded
        from openpyxl import load_workbook

        outputs = convert(
            scanned_two_tables_pdf, "xlsx", out_dir=tmp_path / "xlsx", ocr_dpi=200
        )
        workbook = load_workbook(outputs[0])
        for worksheet in workbook.worksheets:
            rows = [
                row for row in worksheet.iter_rows(values_only=True)
                if any(value is not None for value in row)
            ]
            assert len(rows) >= 3, "header + at least two data rows"
            assert "Sample" in rows[0], "header must be the first row"

    def test_address_block_is_not_exported_as_a_table(self, tmp_path: Path) -> None:
        # a two-column "Ref No : ..." block is narrow; it must not become a sheet
        from pdftoolbox.engines import pdf_tables

        class FakeLine:
            def __init__(self, text: str, box: tuple[float, float, float, float]):
                self.text = text
                self.box = box

        lines = [
            # page frame reference, so the width ratio has a denominator
            FakeLine("", (0.0, 0.0, 2000.0, 10.0)),
            # narrow address block
            FakeLine("Ref No", (200.0, 100.0, 300.0, 130.0)),
            FakeLine(":02/LAB/2026", (420.0, 100.0, 640.0, 130.0)),
            FakeLine("From", (200.0, 160.0, 290.0, 190.0)),
            FakeLine(":SOP Laboratory", (420.0, 160.0, 830.0, 190.0)),
            # real table, spanning the page
            FakeLine("Sample", (200.0, 400.0, 420.0, 430.0)),
            FakeLine("Moisture", (700.0, 400.0, 900.0, 430.0)),
            FakeLine("N", (1500.0, 400.0, 1600.0, 430.0)),
            FakeLine("FWR1", (200.0, 460.0, 400.0, 490.0)),
            FakeLine("73.30", (700.0, 460.0, 900.0, 490.0)),
            FakeLine("0.64", (1500.0, 460.0, 1600.0, 490.0)),
        ]
        tables = pdf_tables._rebuild_tables_from_ocr_lines(lines)
        assert len(tables) == 1, "only the wide table should survive"
        flat = " ".join(cell for row in tables[0] for cell in row)
        assert "Sample" in flat
        assert "Ref No" not in flat


class TestScanWithImageHeader:
    """An image/logo header must not hijack the table, and must not crash."""

    def test_letterhead_is_skipped_and_real_table_kept(
        self, scanned_letterhead_pdf: Path, tmp_path: Path
    ) -> None:
        from openpyxl import load_workbook

        outputs = convert(
            scanned_letterhead_pdf, "xlsx", out_dir=tmp_path / "xlsx", ocr_dpi=200
        )
        workbook = load_workbook(outputs[0])
        rows = [
            [cell for cell in row if cell is not None]
            for row in workbook.worksheets[0].iter_rows(values_only=True)
        ]
        rows = [row for row in rows if any(value for value in row)]
        flat = " ".join(str(value) for row in rows for value in row)
        # the real table survives whole
        assert "Deskripsi" in flat and "Jasa konsultasi" in flat and "5.000.000" in flat
        # the letterhead does not leak into the sheet
        assert "ACME" not in flat
        assert "Sudirman" not in flat
        assert "NPWP" not in flat

    def test_letterhead_without_table_raises_conversion_error(
        self, scanned_letterhead_only_pdf: Path, tmp_path: Path
    ) -> None:
        # the header alone must be reported as "no tables", never as a sheet
        with pytest.raises(ConversionError, match="no tables"):
            convert(
                scanned_letterhead_only_pdf,
                "xlsx",
                out_dir=tmp_path / "xlsx",
                ocr_dpi=200,
            )

    def test_letterhead_failure_does_not_abort_batch(
        self, scanned_letterhead_only_pdf: Path, scanned_table_pdf: Path, tmp_path: Path
    ) -> None:
        # regression: an openpyxl IllegalCharacterError used to escape
        # convert_many and kill every remaining file in the selection
        results = convert_many(
            [scanned_letterhead_only_pdf, scanned_table_pdf],
            "xlsx",
            out_dir=tmp_path / "xlsx",
            ocr_dpi=200,
        )
        assert len(results) == 2
        first, second = results
        assert isinstance(first[1], str)          # reported as a failed file
        assert not isinstance(second[1], str)     # the good one still converted

    def test_docx(self, scanned_pdf: Path, tmp_path: Path) -> None:
        info = plugins.plugin_for_target("docx")
        if not (info and info.available):
            pytest.skip("pdf2docx not installed (uv sync --extra agpl)")
        from docx import Document

        outputs = convert(scanned_pdf, "docx", out_dir=tmp_path / "docx", ocr_dpi=200)
        text = "\n".join(p.text for p in Document(str(outputs[0])).paragraphs)
        assert "HELLO" in text.upper()

    def test_only_the_requested_output_is_kept(
        self, scanned_pdf: Path, tmp_path: Path
    ) -> None:
        # the staged searchable copy is a temp file: it must never be written
        # next to the user's files
        out = tmp_path / "txt"
        convert(scanned_pdf, "txt", out_dir=out, ocr_dpi=200)
        assert [path.name for path in out.iterdir()] == ["scanned_pdfx.txt"]

    def test_page_subset_survives_ocr(
        self, scanned_pdf_pages: Path, tmp_path: Path
    ) -> None:
        # regression: the staged copy holds only the selected pages, so the
        # page filter must not be applied to it a second time
        outputs = convert(
            scanned_pdf_pages, "txt", out_dir=tmp_path / "txt", pages=[2], ocr_dpi=200
        )
        content = outputs[0].read_text(encoding="utf-8").upper()
        assert "SECOND" in content
        assert "FIRST" not in content

    def test_progress_is_reported_during_ocr(
        self, scanned_pdf: Path, tmp_path: Path
    ) -> None:
        seen: list[tuple[int, int]] = []
        convert(
            scanned_pdf,
            "txt",
            out_dir=tmp_path / "txt",
            ocr_dpi=200,
            on_progress=lambda done, total: seen.append((done, total)),
        )
        assert seen == [(1, 1)]

