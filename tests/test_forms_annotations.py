"""Form field, annotation, and word-level OCR tests (no display needed)."""

from __future__ import annotations

from pathlib import Path

import pytest
from pypdf import PdfReader
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

from pdftoolbox.engines import ConversionError
from pdftoolbox.engines import pdf_annotations, pdf_forms
from pdftoolbox.engines import searchable_pdf


def _plain_pdf(path: Path, text: str = "Hello forms") -> Path:
    pdf = canvas.Canvas(str(path), pagesize=A4)
    pdf.drawString(72, 720, text)
    pdf.showPage()
    pdf.save()
    return path


def _form_pdf(path: Path) -> Path:
    """A one-page document carrying a text field, a checkbox and a choice."""
    pdf = canvas.Canvas(str(path), pagesize=A4)
    form = pdf.acroForm
    form.textfield(name="fullname", tooltip="Full name", x=72, y=700, width=200, height=20)
    form.checkbox(name="agree", tooltip="I agree", x=72, y=650, size=20)
    form.choice(
        name="colour",
        tooltip="Colour",
        x=72,
        y=600,
        width=140,
        height=20,
        value="red",
        options=["red", "green", "blue"],
    )
    pdf.showPage()
    pdf.save()
    return path


class TestFormListing:
    def test_lists_every_field_with_its_kind(self, tmp_path: Path) -> None:
        src = _form_pdf(tmp_path / "form.pdf")
        fields = {field.name: field for field in pdf_forms.list_fields(src)}
        assert set(fields) == {"fullname", "agree", "colour"}
        assert fields["fullname"].kind == pdf_forms.TEXT_FIELD
        assert fields["agree"].kind == pdf_forms.BUTTON_FIELD
        assert fields["colour"].kind == pdf_forms.CHOICE_FIELD
        assert fields["colour"].options == ["red", "green", "blue"]

    def test_buttons_report_their_on_state(self, tmp_path: Path) -> None:
        src = _form_pdf(tmp_path / "form.pdf")
        agree = next(f for f in pdf_forms.list_fields(src) if f.name == "agree")
        assert "/Off" in agree.states
        assert agree.on_state != "/Off"

    def test_every_field_reports_its_page(self, tmp_path: Path) -> None:
        src = _form_pdf(tmp_path / "form.pdf")
        assert all(field.page == 1 for field in pdf_forms.list_fields(src))

    def test_plain_pdf_has_no_fields(self, tmp_path: Path) -> None:
        assert pdf_forms.list_fields(_plain_pdf(tmp_path / "plain.pdf")) == []

    def test_field_without_tooltip_uses_its_name(self, tmp_path: Path) -> None:
        src = tmp_path / "unnamed.pdf"
        pdf = canvas.Canvas(str(src), pagesize=A4)
        pdf.drawString(72, 760, "form")
        pdf.acroForm.textfield(name="plain", x=72, y=700, width=100, height=18)
        pdf.showPage()
        pdf.save()
        fields = pdf_forms.list_fields(src)
        assert fields[0].label == "plain"


class TestFormFilling:
    def test_fill_writes_text_and_toggles_the_checkbox(self, tmp_path: Path) -> None:
        src = _form_pdf(tmp_path / "form.pdf")
        target = pdf_forms.fill_fields(
            src, tmp_path / "out.pdf", {"fullname": "Ada Lovelace", "agree": True}
        )
        values = pdf_forms.field_values(target)
        assert values["fullname"] == "Ada Lovelace"
        assert values["agree"] is True

    def test_unlisted_fields_keep_their_value(self, tmp_path: Path) -> None:
        src = _form_pdf(tmp_path / "form.pdf")
        target = pdf_forms.fill_fields(src, tmp_path / "out.pdf", {"fullname": "Name"})
        values = pdf_forms.field_values(target)
        assert values["fullname"] == "Name"
        assert values["agree"] is False

    def test_choice_field_accepts_one_of_its_options(self, tmp_path: Path) -> None:
        src = _form_pdf(tmp_path / "form.pdf")
        target = pdf_forms.fill_fields(src, tmp_path / "out.pdf", {"colour": "green"})
        assert pdf_forms.field_values(target)["colour"] == "green"

    def test_choice_field_rejects_an_unknown_option(self, tmp_path: Path) -> None:
        src = _form_pdf(tmp_path / "form.pdf")
        with pytest.raises(ConversionError, match="not one of the choices"):
            pdf_forms.fill_fields(src, tmp_path / "out.pdf", {"colour": "mauve"})

    def test_unknown_field_is_rejected(self, tmp_path: Path) -> None:
        src = _form_pdf(tmp_path / "form.pdf")
        with pytest.raises(ConversionError, match="no field called"):
            pdf_forms.fill_fields(src, tmp_path / "out.pdf", {"nope": "x"})

    def test_never_overwrites_an_existing_file(self, tmp_path: Path) -> None:
        src = _form_pdf(tmp_path / "form.pdf")
        target = tmp_path / "out.pdf"
        first = pdf_forms.fill_fields(src, target, {"fullname": "one"})
        second = pdf_forms.fill_fields(src, target, {"fullname": "two"})
        assert first == target
        assert second != target and second.name == "out (1).pdf"

    def test_plain_pdf_is_rejected(self, tmp_path: Path) -> None:
        src = _plain_pdf(tmp_path / "plain.pdf")
        with pytest.raises(ConversionError, match="no fillable form fields"):
            pdf_forms.fill_fields(src, tmp_path / "out.pdf", {"name": "x"})

    def test_empty_values_are_rejected(self, tmp_path: Path) -> None:
        src = _form_pdf(tmp_path / "form.pdf")
        with pytest.raises(ConversionError, match="no field values"):
            pdf_forms.fill_fields(src, tmp_path / "out.pdf", {})


class TestAnnotations:
    def test_adds_a_highlight_a_note_and_a_box(self, tmp_path: Path) -> None:
        src = _plain_pdf(tmp_path / "doc.pdf")
        target = pdf_annotations.add_annotations(
            src,
            tmp_path / "out.pdf",
            [
                pdf_annotations.Annotation(
                    kind=pdf_annotations.HIGHLIGHT,
                    page=1,
                    rect=(72, 700, 300, 725),
                    colour="green",
                ),
                pdf_annotations.Annotation(
                    kind=pdf_annotations.NOTE,
                    page=1,
                    rect=(72, 650, 90, 670),
                    text="check this",
                ),
                pdf_annotations.Annotation(
                    kind=pdf_annotations.RECTANGLE, page=1, rect=(72, 600, 300, 640)
                ),
            ],
        )
        found = pdf_annotations.list_annotations(target)
        kinds = {item["subtype"] for item in found}
        assert {"Highlight", "Text", "Square"} <= kinds
        note = next(item for item in found if item["subtype"] == "Text")
        assert note["text"] == "check this"

    def test_annotations_are_stored_per_page(self, tmp_path: Path) -> None:
        src = tmp_path / "two.pdf"
        pdf = canvas.Canvas(str(src), pagesize=A4)
        pdf.drawString(72, 720, "one")
        pdf.showPage()
        pdf.drawString(72, 720, "two")
        pdf.save()
        target = pdf_annotations.add_annotations(
            src,
            tmp_path / "out.pdf",
            [pdf_annotations.Annotation(pdf_annotations.NOTE, 2, (10, 10, 40, 30), "p2")],
        )
        found = pdf_annotations.list_annotations(target)
        assert [item["page"] for item in found] == [2]

    def test_never_overwrites_an_existing_file(self, tmp_path: Path) -> None:
        src = _plain_pdf(tmp_path / "doc.pdf")
        target = tmp_path / "out.pdf"
        note = lambda text: pdf_annotations.Annotation(  # noqa: E731
            pdf_annotations.NOTE, 1, (10, 10, 40, 30), text
        )
        first = pdf_annotations.add_annotations(src, target, [note("a")])
        second = pdf_annotations.add_annotations(src, target, [note("b")])
        assert first == target
        assert second.name == "out (1).pdf"

    def test_out_of_range_page_is_rejected(self, tmp_path: Path) -> None:
        src = _plain_pdf(tmp_path / "doc.pdf")
        with pytest.raises(ConversionError, match="out of range"):
            pdf_annotations.add_annotations(
                src,
                tmp_path / "out.pdf",
                [pdf_annotations.Annotation(pdf_annotations.NOTE, 9, (0, 0, 10, 10), "x")],
            )

    def test_note_without_text_is_rejected(self, tmp_path: Path) -> None:
        src = _plain_pdf(tmp_path / "doc.pdf")
        with pytest.raises(ConversionError, match="needs some text"):
            pdf_annotations.build_annotation(
                pdf_annotations.Annotation(pdf_annotations.NOTE, 1, (0, 0, 10, 10))
            )

    def test_empty_queue_is_rejected(self, tmp_path: Path) -> None:
        src = _plain_pdf(tmp_path / "doc.pdf")
        with pytest.raises(ConversionError, match="no annotations"):
            pdf_annotations.add_annotations(src, tmp_path / "out.pdf", [])

    def test_list_annotations_skips_form_widgets(self, tmp_path: Path) -> None:
        src = _form_pdf(tmp_path / "form.pdf")
        # a form carries widget annotations, which are not user annotations
        assert pdf_annotations.list_annotations(src) == []

    def test_highlight_colours_are_documented(self) -> None:
        assert "yellow" in pdf_annotations.HIGHLIGHT_COLOURS


class TestWordLevelOverlay:
    """The invisible OCR layer should align to words, not whole lines."""

    def test_multiword_lines_become_one_text_run_per_word(self, tmp_path: Path) -> None:
        from pdftoolbox.engines.ocr import OcrLine, OcrPage

        page = OcrPage(
            number=1,
            width=1400,
            height=400,
            lines=[
                OcrLine(
                    text="hello wide world",
                    confidence=0.9,
                    box=(60, 150, 900, 260),
                )
            ],
        )
        path = tmp_path / "overlay.pdf"
        path.write_bytes(searchable_pdf._build_overlay([page], dpi=150))
        # NOTE: the drawn text is invisible, so the words are checked through
        # the produced PDF's text layer rather than the raw bytes
        text = (PdfReader(str(path)).pages[0].extract_text() or "").split()
        assert text == ["hello", "wide", "world"]

    def test_single_word_lines_still_draw_one_run(self, tmp_path: Path) -> None:
        from pdftoolbox.engines.ocr import OcrLine, OcrPage

        page = OcrPage(
            number=1,
            width=1400,
            height=400,
            lines=[OcrLine(text="solo", confidence=0.9, box=(60, 150, 400, 260))],
        )
        path = tmp_path / "overlay.pdf"
        path.write_bytes(searchable_pdf._build_overlay([page], dpi=150))
        assert (PdfReader(str(path)).pages[0].extract_text() or "").split() == ["solo"]

    def test_words_are_spaced_across_the_detected_box(self) -> None:
        # the slack is distributed between the words, so the LAST word lands
        # near the box's right edge rather than bunching at the left
        placements = searchable_pdf._word_placements(
            "aaa bbb ccc", box_w=120.0, font_size=10.0
        )
        assert [word for word, _x, _w in placements] == ["aaa", "bbb", "ccc"]
        gaps = [
            placements[i + 1][1] - (placements[i][1] + placements[i][2])
            for i in range(len(placements) - 1)
        ]
        assert len(set(round(g, 6) for g in gaps)) == 1
        assert gaps[0] > 0

    def test_a_single_word_gets_no_placements(self) -> None:
        assert searchable_pdf._word_placements("solo", 100.0, 10.0) == []

    def test_text_without_spaces_gets_no_placements(self) -> None:
        # CJK text carries no word boundaries to align to
        assert searchable_pdf._word_placements("你好世界", 100.0, 10.0) == []
