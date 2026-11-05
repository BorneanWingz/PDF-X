"""Merge tests: order, page counts, guards, and naming."""

from __future__ import annotations

from pathlib import Path

import pypdfium2 as pdfium
import pytest
from pypdf import PdfReader, PdfWriter

from pdftoolbox.convert import ConversionError, list_targets, merge_pdfs
from pdftoolbox.engines import pdf_merge


def _make_pdf(path: Path, labels: list[str]) -> Path:
    """One page per label, each page carrying its label as text."""
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


class TestMergeEngine:
    def test_merges_in_input_order(self, tmp_path: Path) -> None:
        first = _make_pdf(tmp_path / "first.pdf", ["ALPHA", "BETA"])
        second = _make_pdf(tmp_path / "second.pdf", ["GAMMA"])
        out = pdf_merge.merge_pdf_files([first, second], tmp_path / "out.pdf")
        texts = _page_texts(out)
        assert len(texts) == 3
        assert "ALPHA" in texts[0]
        assert "BETA" in texts[1]
        assert "GAMMA" in texts[2]

    def test_order_follows_argument_order(self, tmp_path: Path) -> None:
        first = _make_pdf(tmp_path / "a.pdf", ["ONE"])
        second = _make_pdf(tmp_path / "b.pdf", ["TWO"])
        out = pdf_merge.merge_pdf_files([second, first], tmp_path / "reversed.pdf")
        texts = _page_texts(out)
        assert "TWO" in texts[0] and "ONE" in texts[1]

    def test_never_overwrites_existing(self, tmp_path: Path) -> None:
        first = _make_pdf(tmp_path / "a.pdf", ["ONE"])
        second = _make_pdf(tmp_path / "b.pdf", ["TWO"])
        target = tmp_path / "merged.pdf"
        first_written = pdf_merge.merge_pdf_files([first, second], target)
        assert first_written == target
        second_written = pdf_merge.merge_pdf_files([first, second], target)
        assert second_written != target
        assert second_written.name == "merged (1).pdf"
        assert target.exists(), "original merged file must be untouched"

    def test_bad_input_reports_filename(self, tmp_path: Path) -> None:
        good = _make_pdf(tmp_path / "good.pdf", ["OK"])
        bad = tmp_path / "bad.pdf"
        bad.write_bytes(b"this is not a pdf at all")
        with pytest.raises(ConversionError, match="bad.pdf"):
            pdf_merge.merge_pdf_files([good, bad], tmp_path / "x.pdf")

    def test_empty_input_list(self, tmp_path: Path) -> None:
        with pytest.raises(ConversionError, match="no input files"):
            pdf_merge.merge_pdf_files([], tmp_path / "x.pdf")

    def test_encrypted_with_empty_password_is_accepted(self, tmp_path: Path) -> None:
        source = _make_pdf(tmp_path / "plain.pdf", ["SECRET"])
        encrypted = tmp_path / "encrypted.pdf"
        writer = PdfWriter()
        writer.append(PdfReader(str(source)))
        writer.encrypt("")  # protects against edits, opens with no password
        with encrypted.open("wb") as handle:
            writer.write(handle)

        out = pdf_merge.merge_pdf_files([encrypted, source], tmp_path / "enc-merged.pdf")
        assert len(_page_texts(out)) == 2

    def test_password_protected_is_rejected(self, tmp_path: Path) -> None:
        source = _make_pdf(tmp_path / "plain.pdf", ["SECRET"])
        locked = tmp_path / "locked.pdf"
        writer = PdfWriter()
        writer.append(PdfReader(str(source)))
        writer.encrypt("hunter2")
        with locked.open("wb") as handle:
            writer.write(handle)

        with pytest.raises(ConversionError, match="password-protected"):
            pdf_merge.merge_pdf_files([locked, source], tmp_path / "x.pdf")


class TestMergeFacade:
    def test_merge_pdfs_default_name(self, tmp_path: Path) -> None:
        first = _make_pdf(tmp_path / "report.pdf", ["ONE"])
        second = _make_pdf(tmp_path / "appendix.pdf", ["TWO"])
        result = merge_pdfs([first, second])
        assert result.name == "report_merged.pdf"
        assert result.parent == tmp_path

    def test_merge_pdfs_explicit_out_path(self, tmp_path: Path) -> None:
        first = _make_pdf(tmp_path / "a.pdf", ["ONE"])
        second = _make_pdf(tmp_path / "b.pdf", ["TWO"])
        target = tmp_path / "sub" / "combined.pdf"
        result = merge_pdfs([first, second], out_path=target)
        assert result == target and result.exists()

    def test_out_dir(self, tmp_path: Path) -> None:
        first = _make_pdf(tmp_path / "a.pdf", ["ONE"])
        second = _make_pdf(tmp_path / "b.pdf", ["TWO"])
        destination = tmp_path / "exports"
        result = merge_pdfs([first, second], out_dir=destination)
        assert result.parent == destination

    def test_needs_two_pdfs(self, tmp_path: Path) -> None:
        only = _make_pdf(tmp_path / "a.pdf", ["ONE"])
        with pytest.raises(ConversionError, match="at least two"):
            merge_pdfs([only])

    def test_non_pdf_inputs_are_ignored(self, tmp_path: Path) -> None:
        first = _make_pdf(tmp_path / "a.pdf", ["ONE"])
        second = _make_pdf(tmp_path / "b.pdf", ["TWO"])
        notes = tmp_path / "notes.txt"
        notes.write_text("not a pdf", encoding="utf-8")
        result = merge_pdfs([first, notes, second])
        assert len(_page_texts(result)) == 2

    def test_convert_rejects_merge_target(self, tmp_path: Path) -> None:
        from pdftoolbox.convert import convert

        only = _make_pdf(tmp_path / "a.pdf", ["ONE"])
        with pytest.raises(ConversionError, match="merging combines"):
            convert(only, "merge")


class TestMergeTargetListing:
    def test_merge_hidden_for_single_pdf(self, tmp_path: Path) -> None:
        only = _make_pdf(tmp_path / "a.pdf", ["ONE"])
        keys = [option.key for option in list_targets(only, pdf_inputs=1)]
        assert "merge" not in keys

    def test_merge_listed_first_for_multiple_pdfs(self, tmp_path: Path) -> None:
        only = _make_pdf(tmp_path / "a.pdf", ["ONE"])
        options = list_targets(only, pdf_inputs=2)
        assert options[0].key == "merge"
        assert options[0].label == "PDF (merge all inputs)"

    def test_aliases(self) -> None:
        from pdftoolbox.convert import is_merge_target, normalize_target

        assert normalize_target("combine") == "merge"
        assert normalize_target("concat") == "merge"
        assert normalize_target("merge-pdf") == "merge"
        assert is_merge_target("COMBINE")
        assert not is_merge_target("png")


class TestPageCountPreserved:
    def test_two_plus_three_pages(self, tmp_path: Path) -> None:
        first = _make_pdf(tmp_path / "a.pdf", ["1", "2"])
        second = _make_pdf(tmp_path / "b.pdf", ["3", "4", "5"])
        out = merge_pdfs([first, second])
        doc = pdfium.PdfDocument(str(out))
        try:
            assert len(doc) == 5
        finally:
            doc.close()
