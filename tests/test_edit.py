"""Edit PDF engine tests: organise, split/extract, watermark, page numbers."""

from __future__ import annotations

from pathlib import Path

import pypdfium2 as pdfium
import pytest
from pypdf import PdfReader

from pdftoolbox.engines import ConversionError
from pdftoolbox.engines import pdf_edit


def _make_pdf(path: Path, labels: list[str]) -> Path:
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    pdf = canvas.Canvas(str(path), pagesize=A4)
    for label in labels:
        pdf.drawString(72, 720, label)
        pdf.showPage()
    pdf.save()
    return path


def _page_texts(path: Path) -> list[str]:
    reader = PdfReader(str(path))
    return [(page.extract_text() or "").strip() for page in reader.pages]


def _page_count(path: Path) -> int:
    doc = pdfium.PdfDocument(str(path))
    try:
        return len(doc)
    finally:
        doc.close()


class TestOrganize:
    def test_reorders_pages(self, tmp_path: Path) -> None:
        source = _make_pdf(tmp_path / "book.pdf", ["ONE", "TWO", "THREE"])
        out = pdf_edit.organize(source, tmp_path / "out.pdf", order=[3, 1, 2])
        assert _page_texts(out)[0].startswith("THREE")
        assert _page_texts(out)[1].startswith("ONE")
        assert _page_texts(out)[2].startswith("TWO")

    def test_delete_is_leaving_pages_out(self, tmp_path: Path) -> None:
        source = _make_pdf(tmp_path / "book.pdf", ["A", "B", "C", "D"])
        out = pdf_edit.organize(source, tmp_path / "out.pdf", order=[1, 4])
        assert _page_count(out) == 2
        assert _page_texts(out)[0].startswith("A")
        assert _page_texts(out)[1].startswith("D")

    def test_duplicate_page_appears_twice(self, tmp_path: Path) -> None:
        source = _make_pdf(tmp_path / "book.pdf", ["A", "B"])
        out = pdf_edit.organize(source, tmp_path / "out.pdf", order=[1, 1, 2])
        assert _page_count(out) == 3

    def test_rotation_is_baked_in(self, tmp_path: Path) -> None:
        source = _make_pdf(tmp_path / "book.pdf", ["A", "B"])
        out = pdf_edit.organize(source, tmp_path / "out.pdf", rotations={1: 90})
        reader = PdfReader(str(out))
        assert (reader.pages[0].get("/Rotate") or 0) == 90
        # the untouched page keeps its original orientation
        assert (reader.pages[1].get("/Rotate") or 0) in (0, None)

    def test_default_order_keeps_everything(self, tmp_path: Path) -> None:
        source = _make_pdf(tmp_path / "book.pdf", ["A", "B", "C"])
        out = pdf_edit.organize(source, tmp_path / "out.pdf")
        assert _page_texts(out) == ["A", "B", "C"]

    def test_never_overwrites_existing(self, tmp_path: Path) -> None:
        source = _make_pdf(tmp_path / "book.pdf", ["A"])
        target = tmp_path / "out.pdf"
        first = pdf_edit.organize(source, target)
        assert first == target
        second = pdf_edit.organize(source, target)
        assert second != target and second.name == "out (1).pdf"

    def test_empty_selection_is_rejected(self, tmp_path: Path) -> None:
        source = _make_pdf(tmp_path / "book.pdf", ["A"])
        with pytest.raises(ConversionError):
            pdf_edit.organize(source, tmp_path / "out.pdf", order=[9])


class TestSplitExtract:
    def test_split_every_n(self, tmp_path: Path) -> None:
        source = _make_pdf(tmp_path / "book.pdf", ["1", "2", "3", "4", "5"])
        parts = pdf_edit.split_pdf(source, tmp_path / "out", every=2, base_name="bk")
        assert [p.name for p in parts] == [
            "bk_part1.pdf",
            "bk_part2.pdf",
            "bk_part3.pdf",
        ]
        assert [_page_count(p) for p in parts] == [2, 2, 1]

    def test_split_bad_size(self, tmp_path: Path) -> None:
        source = _make_pdf(tmp_path / "book.pdf", ["1"])
        with pytest.raises(ConversionError, match="at least 1"):
            pdf_edit.split_pdf(source, tmp_path / "out", every=0)

    def test_extract_keeps_order(self, tmp_path: Path) -> None:
        source = _make_pdf(tmp_path / "book.pdf", ["1", "2", "3", "4"])
        out = pdf_edit.extract_pages(source, tmp_path / "ex.pdf", [2, 4])
        assert _page_texts(out) == ["2", "4"]

    def test_extract_ignores_out_of_range(self, tmp_path: Path) -> None:
        source = _make_pdf(tmp_path / "book.pdf", ["1", "2"])
        out = pdf_edit.extract_pages(source, tmp_path / "ex.pdf", [2, 99])
        assert _page_texts(out) == ["2"]


class TestStamps:
    def test_watermark_is_selectable(self, tmp_path: Path) -> None:
        source = _make_pdf(tmp_path / "book.pdf", ["BODY TEXT"])
        out = pdf_edit.add_watermark(source, tmp_path / "wm.pdf", "CONFIDENTIAL")
        text = " ".join(_page_texts(out)).upper()
        assert "CONFIDENTIAL" in text and "BODY" in text

    def test_watermark_needs_text(self, tmp_path: Path) -> None:
        source = _make_pdf(tmp_path / "book.pdf", ["X"])
        with pytest.raises(ConversionError, match="empty"):
            pdf_edit.add_watermark(source, tmp_path / "wm.pdf", "   ")

    def test_page_numbers_pattern(self, tmp_path: Path) -> None:
        source = _make_pdf(tmp_path / "book.pdf", ["A", "B", "C"])
        out = pdf_edit.add_page_numbers(
            source, tmp_path / "num.pdf", pattern="Page {page} of {total}"
        )
        texts = _page_texts(out)
        assert "Page 1 of 3" in texts[0]
        assert "Page 3 of 3" in texts[2]

    def test_page_numbers_keep_content(self, tmp_path: Path) -> None:
        source = _make_pdf(tmp_path / "book.pdf", ["HELLO"])
        out = pdf_edit.add_page_numbers(source, tmp_path / "num.pdf")
        assert "HELLO" in _page_texts(out)[0]


class TestHelpers:
    def test_page_count(self, tmp_path: Path) -> None:
        source = _make_pdf(tmp_path / "book.pdf", ["A", "B", "C"])
        assert pdf_edit.page_count(source) == 3

    def test_missing_file_raises(self, tmp_path: Path) -> None:
        with pytest.raises(ConversionError, match="cannot read"):
            pdf_edit.page_count(tmp_path / "nope.pdf")

    def test_password_protected_is_rejected(self, tmp_path: Path) -> None:
        from pypdf import PdfWriter

        source = _make_pdf(tmp_path / "plain.pdf", ["SECRET"])
        locked = tmp_path / "locked.pdf"
        writer = PdfWriter()
        writer.append(PdfReader(str(source)))
        writer.encrypt("hunter2")
        with locked.open("wb") as handle:
            writer.write(handle)
        with pytest.raises(ConversionError, match="password-protected"):
            pdf_edit.page_count(locked)


class TestTextEditing:
    def test_page_height(self, tmp_path: Path) -> None:
        source = _make_pdf(tmp_path / "book.pdf", ["A", "B"])
        # A4 is 842 points tall; allow the odd fraction
        assert 800 < pdf_edit.page_height(source, 1) < 900

    def test_add_text_is_selectable(self, tmp_path: Path) -> None:
        source = _make_pdf(tmp_path / "book.pdf", ["ORIGINAL BODY"])
        out = pdf_edit.add_text(
            source,
            tmp_path / "added.pdf",
            [pdf_edit.PlacedText(page=1, text="APPROVED", x=72, top=60, font_size=18)],
        )
        text = " ".join(_page_texts(out)).upper()
        assert "APPROVED" in text and "ORIGINAL" in text

    def test_selected_font_and_position_are_written_with_line_edit(self, tmp_path: Path) -> None:
        from pdftoolbox.system_fonts import installed_fonts

        fonts = installed_fonts()
        if not fonts:
            pytest.skip("no installed TrueType fonts")
        font = fonts.get("Arial", next(iter(fonts.values())))
        source = _make_pdf(tmp_path / "book.pdf", ["Original line", "Second page"])
        match = pdf_edit.text_lines(source, 1)[0]
        assert match.font_name
        out = pdf_edit.edit_text_lines(
            source, tmp_path / "edited.pdf", [(match, "Corrected")], [font],
            [pdf_edit.PlacedText(2, "Caf\u00e9 note", 100, 120, 18,
                                 font_path=font.path, font_index=font.index)],
        )
        assert "Corrected" in _page_texts(out)[0]
        assert "Caf\u00e9 note" in _page_texts(out)[1]
        note = pdf_edit.find_text(out, "Caf\u00e9")[0]
        assert note.page == 2
        assert 99 <= note.x0 <= 103
        assert 115 <= note.top <= 140
        fonts_in_pdf = PdfReader(str(out)).pages[1]["/Resources"]["/Font"]
        assert any("/FontDescriptor" in font_ref.get_object().get("/DescendantFonts", [font_ref])[0].get_object()
                   or "/FontDescriptor" in font_ref.get_object()
                   for font_ref in fonts_in_pdf.values())

    def test_added_text_rejects_missing_font_file(self, tmp_path: Path) -> None:
        source = _make_pdf(tmp_path / "book.pdf", ["A"])
        with pytest.raises(ConversionError, match="cannot use font"):
            pdf_edit.edit_text_lines(
                source, tmp_path / "out.pdf", [], additions=[
                    pdf_edit.PlacedText(1, "Text", 20, 20, font_path=tmp_path / "missing.ttf")
                ],
            )

    def test_collection_face_is_embedded(self, tmp_path: Path) -> None:
        from pdftoolbox.system_fonts import installed_fonts

        font = next((face for face in installed_fonts().values() if face.index > 0), None)
        if font is None:
            pytest.skip("no multi-face TrueType collection installed")
        source = _make_pdf(tmp_path / "book.pdf", ["A"])
        out = pdf_edit.edit_text_lines(
            source, tmp_path / "out.pdf", [], additions=[
                pdf_edit.PlacedText(1, "Collection", 20, 20,
                                    font_path=font.path, font_index=font.index)
            ],
        )
        assert "Collection" in _page_texts(out)[0]

    def test_collection_can_embed_cjk_text(self, tmp_path: Path) -> None:
        from pdftoolbox.system_fonts import installed_fonts

        font = installed_fonts().get("Microsoft YaHei UI")
        if font is None:
            pytest.skip("Microsoft YaHei UI is not installed")
        source = _make_pdf(tmp_path / "book.pdf", ["A"])
        out = pdf_edit.edit_text_lines(
            source, tmp_path / "out.pdf", [], additions=[
                pdf_edit.PlacedText(1, "\u4e2d\u6587", 20, 20, font_path=font.path,
                                    font_index=font.index)
            ],
        )
        assert "\u4e2d\u6587" in _page_texts(out)[0]

    def test_font_suggestions_distinguish_exact_and_fallback(self) -> None:
        from pdftoolbox.system_fonts import FontFace, suggest_font

        fonts = {"Arial": FontFace(Path("arial.ttf")), "Arial Bold": FontFace(Path("arialbd.ttf"))}
        assert suggest_font("ABCDEF+Arial-Bold", fonts) == ("Arial Bold", True)
        assert suggest_font("Helvetica", fonts) == ("Arial", False)
        assert suggest_font("", fonts) == (None, False)

    def test_find_text_reports_pages_and_boxes(self, tmp_path: Path) -> None:
        source = _make_pdf(tmp_path / "book.pdf", ["Total 100 USD", "Again 100 here"])
        matches = pdf_edit.find_text(source, "100")
        assert [m.page for m in matches] == [1, 2]
        for match in matches:
            assert match.width > 0 and match.height > 0

    def test_find_text_case_sensitivity(self, tmp_path: Path) -> None:
        source = _make_pdf(tmp_path / "book.pdf", ["Hello World"])
        assert pdf_edit.find_text(source, "hello") != []
        assert pdf_edit.find_text(source, "hello", case_sensitive=True) == []
        assert pdf_edit.find_text(source, "Hello", case_sensitive=True) != []

    def test_find_text_missing_returns_empty(self, tmp_path: Path) -> None:
        source = _make_pdf(tmp_path / "book.pdf", ["nothing here"])
        assert pdf_edit.find_text(source, "absent") == []

    def test_text_lines_return_page_ordered_boxes(self, tmp_path: Path) -> None:
        source = _make_pdf(tmp_path / "book.pdf", ["First line", "Second line"])
        lines = pdf_edit.text_lines(source, 1)
        assert len(lines) == 1
        assert lines[0].text == "First line"
        assert lines[0].page == 1
        assert lines[0].width > 0 and lines[0].height > 0

    def test_text_lines_reject_out_of_range_page(self, tmp_path: Path) -> None:
        source = _make_pdf(tmp_path / "book.pdf", ["Only page"])
        with pytest.raises(ConversionError, match="out of range"):
            pdf_edit.text_lines(source, 2)

    def test_text_lines_reject_rotated_pages(self, tmp_path: Path) -> None:
        from pypdf import PdfWriter

        source = _make_pdf(tmp_path / "upright.pdf", ["Rotated text"])
        reader = PdfReader(str(source))
        reader.pages[0].rotate(90)
        writer = PdfWriter()
        writer.add_page(reader.pages[0])
        rotated = tmp_path / "rotated.pdf"
        with rotated.open("wb") as handle:
            writer.write(handle)
        with pytest.raises(ConversionError, match="upright pages"):
            pdf_edit.text_lines(rotated, 1)

    def test_text_lines_group_lines_from_top_to_bottom(
        self, tmp_path: Path
    ) -> None:
        from reportlab.pdfgen import canvas

        source = tmp_path / "lines.pdf"
        pdf = canvas.Canvas(str(source))
        pdf.drawString(72, 720, "Top line")
        pdf.drawString(72, 690, "Bottom line")
        pdf.save()
        lines = pdf_edit.text_lines(source, 1)
        assert [line.text for line in lines] == ["Top line", "Bottom line"]
        assert lines[0].top < lines[1].top

    def test_edit_text_lines_writes_replacement_to_pdf_copy(
        self, tmp_path: Path
    ) -> None:
        source = _make_pdf(tmp_path / "book.pdf", ["Original line"])
        match = pdf_edit.text_lines(source, 1)[0]
        out = pdf_edit.edit_text_lines(
            source, tmp_path / "edited.pdf", [(match, "Corrected")]
        )
        text = _page_texts(out)[0]
        assert "Original line" in text
        assert "Corrected" in text
        assert _page_count(out) == _page_count(source)

    def test_edit_text_lines_rejects_replacement_that_will_not_fit(
        self, tmp_path: Path
    ) -> None:
        source = _make_pdf(tmp_path / "book.pdf", ["A"])
        match = pdf_edit.text_lines(source, 1)[0]
        with pytest.raises(ConversionError, match="does not fit"):
            pdf_edit.edit_text_lines(
                source, tmp_path / "edited.pdf", [(match, "Much too long " * 20)]
            )

    def test_edit_text_lines_rejects_multiline_replacement(
        self, tmp_path: Path
    ) -> None:
        source = _make_pdf(tmp_path / "book.pdf", ["A"])
        match = pdf_edit.text_lines(source, 1)[0]
        with pytest.raises(ConversionError, match="one line"):
            pdf_edit.edit_text_lines(
                source, tmp_path / "edited.pdf", [(match, "two\nlines")]
            )

    def test_edit_text_lines_rejects_empty_changes(
        self, tmp_path: Path
    ) -> None:
        source = _make_pdf(tmp_path / "book.pdf", ["Original line"])
        with pytest.raises(ConversionError, match="no text changes"):
            pdf_edit.edit_text_lines(source, tmp_path / "edited.pdf", [])

    def test_replace_text_covers_and_writes_new(self, tmp_path: Path) -> None:
        source = _make_pdf(tmp_path / "book.pdf", ["Amount: 100 USD"])
        out, count = pdf_edit.replace_text(source, tmp_path / "rep.pdf", "100", "250")
        assert count == 1
        text = " ".join(_page_texts(out))
        # the replacement is written on top; the original text layer stays beneath
        assert "250" in text

    def test_replace_text_not_found_raises(self, tmp_path: Path) -> None:
        source = _make_pdf(tmp_path / "book.pdf", ["Amount: 100"])
        with pytest.raises(ConversionError, match="not found"):
            pdf_edit.replace_text(source, tmp_path / "rep.pdf", "nope", "x")

    def test_replace_text_all_occurrences(self, tmp_path: Path) -> None:
        source = _make_pdf(tmp_path / "book.pdf", ["100 and 100", "100 only"])
        out, count = pdf_edit.replace_text(source, tmp_path / "rep.pdf", "100", "7")
        assert count == 3

    def test_add_text_requires_content(self, tmp_path: Path) -> None:
        source = _make_pdf(tmp_path / "book.pdf", ["A"])
        with pytest.raises(ConversionError, match="no text"):
            pdf_edit.add_text(source, tmp_path / "x.pdf", [])
