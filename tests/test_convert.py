"""Conversion path tests: every permissive target is exercised end to end."""

from __future__ import annotations

from pathlib import Path

import pypdfium2 as pdfium
import pytest
from openpyxl import load_workbook
from PIL import Image
from pptx import Presentation

from pdftoolbox.convert import convert, list_targets, normalize_target, parse_pages
from pdftoolbox.convert import output_name, output_path
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

    def test_illustration_gets_its_own_sheet(
        self, illustration_pdf: Path, tmp_path: Path
    ) -> None:
        # a picture is content: it must survive, but never on top of table cells
        outputs = convert(illustration_pdf, "xlsx", out_dir=tmp_path / "xlsx")
        workbook = load_workbook(outputs[0])
        image_sheets = [name for name in workbook.sheetnames if name.endswith("_images")]
        assert image_sheets == ["p1_images"]

        table_sheet = workbook[workbook.sheetnames[0]]
        values = [str(cell.value) for row in table_sheet.iter_rows() for cell in row if cell.value]
        assert "Item" in values and "Widget" in values
        # the table sheet holds only text - the picture never lands on its cells
        assert workbook[workbook.sheetnames[0]]._images == []

        image_sheet = workbook["p1_images"]
        assert image_sheet["A1"].value == "Page 1 illustrations"
        assert len(image_sheet._images) == 1

    def test_table_only_pdf_gets_no_image_sheet(
        self, table_pdf: Path, tmp_path: Path
    ) -> None:
        outputs = convert(table_pdf, "xlsx", out_dir=tmp_path / "xlsx")
        workbook = load_workbook(outputs[0])
        assert not [name for name in workbook.sheetnames if name.endswith("_images")]


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


class TestDefaultOutputLocation:
    """No output folder given: results land beside the input, no subfolder."""

    def test_pdf_conversion_writes_beside_input(self, text_pdf: Path) -> None:
        before = {path.name for path in text_pdf.parent.iterdir()}
        convert(text_pdf, "txt")
        new = {path.name for path in text_pdf.parent.iterdir()} - before
        # the file itself, and nothing else - especially no "<name>_output" dir
        assert new == {"sample_pdfx.txt"}
        assert not (text_pdf.parent / f"{text_pdf.stem}_output").exists()

    def test_to_pdf_conversion_writes_beside_input(self, image_file: Path) -> None:
        before = {path.name for path in image_file.parent.iterdir()}
        convert(image_file, "pdf")
        new = {path.name for path in image_file.parent.iterdir()} - before
        assert new == {"picture_pdfx.pdf"}
        assert not (image_file.parent / f"{image_file.stem}_output").exists()

    def test_explicit_folder_is_still_honoured(self, text_pdf: Path, tmp_path: Path) -> None:
        out = tmp_path / "chosen"
        outputs = convert(text_pdf, "txt", out_dir=out)
        assert outputs[0].parent == out


class TestOutputNaming:
    """Every result is named "<original stem>_pdfx<tag>.<ext>"."""

    def test_helper_names(self) -> None:
        source = Path("Report final.pdf")
        assert output_name(source, ".txt") == "Report final_pdfx.txt"
        assert output_name(source, ".png", "_page0001") == (
            "Report final_pdfx_page0001.png"
        )
        assert output_name(Path("notes.md"), ".pdf") == "notes_pdfx.pdf"

    def test_helper_path_uses_folder(self, tmp_path: Path) -> None:
        assert output_path(Path("a.pdf"), tmp_path, ".xlsx") == tmp_path / "a_pdfx.xlsx"

    def test_pdf_to_text_is_tagged(self, text_pdf: Path, tmp_path: Path) -> None:
        outputs = convert(text_pdf, "txt", out_dir=tmp_path / "txt")
        assert [path.name for path in outputs] == ["sample_pdfx.txt"]

    def test_pdf_to_html_is_tagged(self, text_pdf: Path, tmp_path: Path) -> None:
        outputs = convert(text_pdf, "html", out_dir=tmp_path / "html")
        assert [path.name for path in outputs] == ["sample_pdfx.html"]

    def test_images_keep_page_number_after_tag(self, text_pdf: Path, tmp_path: Path) -> None:
        outputs = convert(text_pdf, "png", out_dir=tmp_path / "png", dpi=72)
        assert [path.name for path in outputs] == [
            "sample_pdfx_page0001.png",
            "sample_pdfx_page0002.png",
        ]

    def test_image_files_do_not_collide_between_inputs(
        self, text_pdf: Path, tmp_path: Path
    ) -> None:
        # two inputs converted into one folder keep their own page sets
        from reportlab.lib.pagesizes import A4
        from reportlab.pdfgen import canvas

        other = tmp_path / "other.pdf"
        pdf = canvas.Canvas(str(other), pagesize=A4)
        pdf.drawString(72, 720, "OTHER")
        pdf.save()

        out = tmp_path / "both"
        convert(text_pdf, "png", out_dir=out, dpi=72)
        convert(other, "png", out_dir=out, dpi=72)
        names = sorted(path.name for path in out.iterdir())
        assert names == [
            "other_pdfx_page0001.png",
            "sample_pdfx_page0001.png",
            "sample_pdfx_page0002.png",
        ]

    def test_pptx_is_tagged(self, text_pdf: Path, tmp_path: Path) -> None:
        outputs = convert(text_pdf, "pptx", out_dir=tmp_path / "pptx", dpi=72)
        assert [path.name for path in outputs] == ["sample_pdfx.pptx"]

    def test_table_extraction_is_tagged(self, table_pdf: Path, tmp_path: Path) -> None:
        outputs = convert(table_pdf, "xlsx", out_dir=tmp_path / "xlsx")
        assert [path.name for path in outputs] == ["table_pdfx.xlsx"]

    def test_to_pdf_is_tagged(self, markdown_file: Path, tmp_path: Path) -> None:
        outputs = convert(markdown_file, "pdf", out_dir=tmp_path / "md")
        assert [path.name for path in outputs] == ["notes_pdfx.pdf"]

    def test_result_never_clobbers_an_original(self, tmp_path: Path) -> None:
        # "paper.md" -> "paper_pdfx.pdf" must not touch an existing paper.pdf
        original = tmp_path / "paper.pdf"
        original.write_bytes(b"original bytes, not produced by this app")
        source = tmp_path / "paper.md"
        source.write_text("# Title\n\nSome text.\n", encoding="utf-8")

        outputs = convert(source, "pdf", out_dir=tmp_path)

        assert outputs[0].name == "paper_pdfx.pdf"
        assert original.read_bytes() == b"original bytes, not produced by this app"

    def test_ocr_first_path_keeps_original_name(
        self, scanned_pdf: Path, tmp_path: Path
    ) -> None:
        # a scan is OCR'd into a temp copy first; the result must still be
        # named after the user's file, with exactly one "_pdfx"
        out = tmp_path / "ocr"
        outputs = convert(scanned_pdf, "txt", out_dir=out, ocr_dpi=200)
        assert [path.name for path in outputs] == ["scanned_pdfx.txt"]

    def test_searchable_pdf_is_tagged(self, text_pdf: Path, tmp_path: Path) -> None:
        outputs = convert(text_pdf, "searchable-pdf", out_dir=tmp_path / "s", ocr_dpi=150)
        assert [path.name for path in outputs] == ["sample_pdfx_searchable.pdf"]


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
