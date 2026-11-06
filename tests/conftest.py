"""Shared fixtures: generated sample documents for every conversion path."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from PIL import Image, ImageDraw, ImageFont
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
# NOTE: tests import the package from src/ directly (no install step needed)
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


@pytest.fixture
def text_pdf(tmp_path: Path) -> Path:
    """Two-page PDF with real text content."""
    path = tmp_path / "sample.pdf"
    pdf = canvas.Canvas(str(path), pagesize=A4)
    pdf.drawString(72, 720, "Hello PDF Toolbox")
    pdf.drawString(72, 700, "Second line of text")
    pdf.showPage()
    pdf.drawString(72, 720, "Page two content")
    pdf.save()
    return path


@pytest.fixture
def table_pdf(tmp_path: Path) -> Path:
    """PDF containing one ruled table (for XLSX extraction)."""
    from reportlab.lib import colors
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle

    path = tmp_path / "table.pdf"
    data = [
        ["Item", "Qty", "Price"],
        ["Widget", "3", "9.75"],
        ["Gadget", "1", "24.50"],
    ]
    table = Table(data, colWidths=[180, 60, 80])
    table.setStyle(
        TableStyle(
            [
                ("GRID", (0, 0), (-1, -1), 1, colors.black),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ]
        )
    )
    SimpleDocTemplate(str(path), pagesize=A4).build([table])
    return path


@pytest.fixture
def image_file(tmp_path: Path) -> Path:
    """Simple PNG image for image -> PDF."""
    image = Image.new("RGB", (400, 300), (200, 220, 255))
    draw = ImageDraw.Draw(image)
    draw.rectangle([50, 50, 350, 250], outline=(0, 0, 0), width=3)
    draw.line([50, 50, 350, 250], fill=(180, 0, 0), width=2)
    path = tmp_path / "picture.png"
    image.save(path)
    return path


@pytest.fixture
def scanned_pdf(tmp_path: Path) -> Path:
    """Image-only PDF with large text: exercises the real OCR path."""
    image = Image.new("RGB", (1400, 420), "white")
    draw = ImageDraw.Draw(image)
    try:
        font = ImageFont.truetype("C:/Windows/Fonts/arial.ttf", 96)
    except OSError:
        font = ImageFont.load_default()
    draw.text((60, 150), "HELLO OCR WORLD", fill="black", font=font)
    path = tmp_path / "scanned.pdf"
    image.save(path, "PDF", resolution=150)
    return path


@pytest.fixture
def scanned_pdf_pages(tmp_path: Path) -> Path:
    """Two-page image-only PDF, for OCR combined with a page subset."""
    pages = []
    for label in ("FIRST OCR PAGE", "SECOND OCR PAGE"):
        image = Image.new("RGB", (1400, 420), "white")
        draw = ImageDraw.Draw(image)
        try:
            font = ImageFont.truetype("C:/Windows/Fonts/arial.ttf", 96)
        except OSError:
            font = ImageFont.load_default()
        draw.text((60, 150), label, fill="black", font=font)
        pages.append(image)
    path = tmp_path / "scanned_multi.pdf"
    pages[0].save(
        path, "PDF", resolution=150, save_all=True, append_images=pages[1:]
    )
    return path


@pytest.fixture
def scanned_table_pdf(tmp_path: Path) -> Path:
    """Image-only PDF holding a ruled table, for OCR before XLSX extraction."""
    image = Image.new("RGB", (1600, 800), "white")
    draw = ImageDraw.Draw(image)
    try:
        font = ImageFont.truetype("C:/Windows/Fonts/arial.ttf", 40)
    except OSError:
        font = ImageFont.load_default()
    rows = [["Item", "Qty", "Price"], ["Widget", "3", "9.75"], ["Gadget", "1", "24.50"]]
    left, top, col_w, row_h = 100, 100, 300, 120
    for row_index, row in enumerate(rows):
        for col_index, cell in enumerate(row):
            x = left + col_index * col_w
            y = top + row_index * row_h
            draw.rectangle(
                [x, y, x + col_w, y + row_h], outline="black", width=3
            )
            draw.text((x + 20, y + 40), cell, fill="black", font=font)
    path = tmp_path / "scanned_table.pdf"
    image.save(path, "PDF", resolution=150)
    return path


@pytest.fixture
def scanned_letterhead_pdf(tmp_path: Path) -> Path:
    """Image-only page: a letterhead/logo band above a real ruled table.

    The band is the case that used to break -- an image header that OCR turns
    into a dense block of text, which pdfplumber reported as the page's table.
    """
    image = Image.new("RGB", (1240, 1754), "white")
    draw = ImageDraw.Draw(image)
    try:
        big = ImageFont.truetype("C:/Windows/Fonts/arialbd.ttf", 44)
        mid = ImageFont.truetype("C:/Windows/Fonts/arial.ttf", 30)
    except OSError:
        big = mid = ImageFont.load_default()
    # letterhead / logo band
    draw.rectangle([60, 60, 1180, 300], outline=(0, 0, 0), width=4)
    draw.text((90, 80), "ACME CORPORATION", fill="black", font=big)
    draw.text((90, 140), "Jl. Sudirman No. 52", fill="black", font=mid)
    draw.text((90, 175), "Jakarta 12190", fill="black", font=mid)
    draw.text((90, 210), "Tel: 021-555-0100", fill="black", font=mid)
    draw.text((90, 245), "NPWP: 01.234.567.8", fill="black", font=mid)
    # the real table, further down
    rows = [["Deskripsi", "Jumlah"], ["Jasa konsultasi", "5.000.000"], ["Total", "5.000.000"]]
    col_w, row_h, left, top = 400, 70, 90, 700
    for row_index, row in enumerate(rows):
        for col_index, cell in enumerate(row):
            x = left + col_index * col_w
            y = top + row_index * row_h
            draw.rectangle([x, y, x + col_w, y + row_h], outline="black", width=3)
            draw.text((x + 15, y + 18), cell, fill="black", font=mid)
    path = tmp_path / "letterhead.pdf"
    image.save(path, "PDF", resolution=150)
    return path


@pytest.fixture
def scanned_letterhead_only_pdf(tmp_path: Path) -> Path:
    """Image-only page with a letterhead and NO table at all."""
    image = Image.new("RGB", (1240, 1754), "white")
    draw = ImageDraw.Draw(image)
    try:
        big = ImageFont.truetype("C:/Windows/Fonts/arialbd.ttf", 44)
        mid = ImageFont.truetype("C:/Windows/Fonts/arial.ttf", 30)
    except OSError:
        big = mid = ImageFont.load_default()
    draw.rectangle([60, 60, 1180, 300], outline=(0, 0, 0), width=4)
    draw.text((90, 80), "ACME CORPORATION", fill="black", font=big)
    draw.text((90, 140), "Jl. Sudirman No. 52", fill="black", font=mid)
    draw.text((90, 175), "Jakarta 12190", fill="black", font=mid)
    draw.text((90, 210), "Tel: 021-555-0100", fill="black", font=mid)
    draw.text((90, 245), "NPWP: 01.234.567.8", fill="black", font=mid)
    path = tmp_path / "letterhead_only.pdf"
    image.save(path, "PDF", resolution=150)
    return path


@pytest.fixture
def markdown_file(tmp_path: Path) -> Path:
    path = tmp_path / "notes.md"
    path.write_text(
        "# Project notes\n\nIntro paragraph with enough words to wrap at least once.\n\n"
        "- first bullet\n- second bullet\n\n## Details\n\n```\ncode block line\n```\n",
        encoding="utf-8",
    )
    return path


@pytest.fixture
def plain_text(tmp_path: Path) -> Path:
    path = tmp_path / "notes.txt"
    path.write_text("Plain text file.\nSecond line.\n", encoding="utf-8")
    return path
