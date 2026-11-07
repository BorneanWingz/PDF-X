"""Merge tests: order, page counts, guards, and naming."""

from __future__ import annotations

from pathlib import Path

import pypdfium2 as pdfium
import pytest
from pypdf import PdfReader, PdfWriter

from pdftoolbox.convert import (
    ConversionError,
    can_convert_to_pdf,
    list_targets,
    merge_pdfs,
    merge_to_pdf,
)
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
        assert result.name == "report_pdfx_merged.pdf"
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


class TestMergeMixedFormats:
    """The Merge PDF tab: any input becomes PDF, then merges in list order."""

    def test_mixed_inputs_merge_in_order(self, image_file: Path, tmp_path: Path) -> None:
        first = _make_pdf(tmp_path / "first.pdf", ["ALPHA"])
        note = tmp_path / "note.txt"
        note.write_text("beta from plain text", encoding="utf-8")

        result = merge_to_pdf([first, image_file, note], out_dir=tmp_path / "out")
        assert result.exists() and result.suffix == ".pdf"
        assert result.name == "first_pdfx_merged.pdf"

        doc = pdfium.PdfDocument(str(result))
        try:
            # 1 (first) + 1 (image) + 1 (text) pages, in that order
            assert len(doc) == 3
        finally:
            doc.close()
        texts = _page_texts(result)
        assert "ALPHA" in texts[0]

    def test_list_order_decides_page_order(self, tmp_path: Path) -> None:
        a = _make_pdf(tmp_path / "a.pdf", ["ONE"])
        b = _make_pdf(tmp_path / "b.pdf", ["TWO"])
        result = merge_to_pdf([b, a], out_dir=tmp_path)
        texts = _page_texts(result)
        assert "TWO" in texts[0] and "ONE" in texts[1]

    def test_non_pdf_parts_leave_no_leftovers(self, tmp_path: Path) -> None:
        # conversions happen in a temp dir: no "<name>_pdfx.pdf" beside the input
        note = tmp_path / "note.md"
        note.write_text("# Heading\n\nSome body text.\n", encoding="utf-8")
        other = _make_pdf(tmp_path / "report.pdf", ["REPORT"])

        result = merge_to_pdf([note, other], out_dir=tmp_path / "out")
        assert result.parent == tmp_path / "out"
        assert not (tmp_path / "note_pdfx.pdf").exists(), "temp output leaked"

    def test_can_convert_to_pdf_reports_supported_formats(self, tmp_path: Path) -> None:
        assert can_convert_to_pdf(_make_pdf(tmp_path / "x.pdf", ["X"]))
        assert can_convert_to_pdf(tmp_path / "y.txt")
        assert can_convert_to_pdf(tmp_path / "z.png")
        assert can_convert_to_pdf(tmp_path / "w.docx")
        assert not can_convert_to_pdf(tmp_path / "unknown.xyz")

    def test_unsupported_input_is_rejected(self, tmp_path: Path) -> None:
        good = _make_pdf(tmp_path / "good.pdf", ["OK"])
        bad = tmp_path / "file.xyz"
        bad.write_bytes(b"data")
        with pytest.raises(ConversionError, match="cannot merge"):
            merge_to_pdf([good, bad], out_dir=tmp_path)

    def test_single_input_needs_two(self, tmp_path: Path) -> None:
        only = _make_pdf(tmp_path / "only.pdf", ["ONE"])
        with pytest.raises(ConversionError, match="at least two"):
            merge_to_pdf([only], out_dir=tmp_path)

    def test_empty_list_is_rejected(self, tmp_path: Path) -> None:
        with pytest.raises(ConversionError, match="no input files"):
            merge_to_pdf([], out_dir=tmp_path)

    def test_progress_reports_each_input(self, tmp_path: Path) -> None:
        a = _make_pdf(tmp_path / "a.pdf", ["A"])
        b = _make_pdf(tmp_path / "b.pdf", ["B"])
        seen: list[tuple[int, int]] = []
        merge_to_pdf([a, b], out_dir=tmp_path, on_progress=lambda d, t: seen.append((d, t)))
        assert seen == [(1, 2), (2, 2)]

