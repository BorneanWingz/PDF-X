"""Extract tables from PDFs into XLSX using pdfplumber + openpyxl (MIT).

Scan handling: the conversion layer OCRs a scan into a searchable PDF first, so
this module only ever sees a PDF with a text layer. What that layer does NOT
tell apart is a data table and an image logo/letterhead - OCR turns a letterhead
into a dense block of short fragments that pdfplumber happily reports as the
page's "table", hiding the real one further down. Font size is what separates
them: letterhead text is set noticeably larger than body text, so table rows
outside the page's body type size are ignored (see _body_font_size).
"""

from __future__ import annotations

import re
from collections import Counter
from pathlib import Path

import pdfplumber
from openpyxl import Workbook
from openpyxl.styles import Font

from . import ConversionError

# openpyxl refuses any control character inside a cell, and a mistaken read of a
# logo/letterhead is exactly where such bytes come from. Excel itself stores only
# tab and newline, so everything else below 0x20 (plus DEL) is dropped.
_ILLEGAL_CHARACTERS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")

# Extraction strategies, best first. "lines" trusts real rulings; a rasterised
# page has none, so the text heuristics follow. The loose pass exists because
# OCR boxes land a few points apart, so a column needs only two aligned words
# before pdfplumber draws an edge for it.
_ALL_STRATEGIES: tuple[tuple[str, dict | None], ...] = (
    ("lines", {"vertical_strategy": "lines", "horizontal_strategy": "lines"}),
    ("text", {"vertical_strategy": "text", "horizontal_strategy": "text"}),
    (
        "text-loose",
        {
            "vertical_strategy": "text",
            "horizontal_strategy": "text",
            "min_words_vertical": 2,
        },
    ),
    # NOTE: None = pdfplumber defaults; tried LAST because explicit line
    # detection beats heuristics on ruled tables
    ("mixed", None),
)

# NOTE: header/logo type runs about twice the body size (measured on a real
# letterhead: 12-15 pt header vs 6.5-7 pt table). 1.4 leaves room for a bold
# table heading while still rejecting the letterhead.
_HEADER_SIZE_RATIO = 1.4
# a table needs at least two columns and two rows to be worth a sheet
_MIN_TABLE_COLUMNS = 2
_MIN_TABLE_ROWS = 2


def _clean_cell(value) -> str:
    return _ILLEGAL_CHARACTERS.sub("", "" if value is None else str(value))


def _clean_table(table) -> list[list[str]]:
    return [[_clean_cell(cell) for cell in row] for row in table]


def _body_font_size(page) -> float | None:
    """Typical size of the page's running text: the upper quartile.

    NOTE: letterhead and heading text is a small minority of a page's glyphs, so
    the upper quartile sits at the body size instead of being dragged up by the
    few large words. A plain mode over character sizes is not enough here - a
    short table heading repeated on every row can outvote the cell text (11 pt
    vs 7 pt on a real letterhead, which defeated the first version of this).
    """
    sizes = sorted(
        float(char["size"]) for char in page.chars if char.get("size")
    )
    if not sizes:
        return None
    return sizes[int(len(sizes) * 0.75)]


def _in_body_type(page, bbox, body_size: float | None) -> bool:
    """True when the text inside bbox is set in body type, not letterhead type.

    NOTE: decided by the majority of glyphs in the box, not by any single one.
    Heuristic detection often stretches a "table" bbox over the whole page, so a
    lone body-size glyph cannot be allowed to vouch for a letterhead. A box with
    no glyphs (an empty ruled grid) is kept - there is nothing to judge.
    """
    if body_size is None:
        return True
    limit = body_size * _HEADER_SIZE_RATIO
    inside = body_ish = 0
    for char in page.chars:
        size = char.get("size")
        if not size:
            continue
        if not (
            bbox[0] <= char.get("x0", 0) <= bbox[2]
            and bbox[1] <= char.get("top", 0) <= bbox[3]
        ):
            continue
        inside += 1
        if float(size) <= limit:
            body_ish += 1
    if not inside:
        return True
    return body_ish / inside >= 0.5


def _looks_like_table(table: list[list[str]], *, from_text: bool) -> bool:
    """Reject the degenerate 'table' an image header produces.

    NOTE: text-based detection is only trusted when the result has at least two
    columns and two rows - a single short row, or one column of fragments, is a
    letterhead, and writing it hides the real table further down the page.
    """
    rows = [row for row in table if any(cell.strip() for cell in row)]
    if not rows:
        return False
    if max(len(row) for row in rows) < _MIN_TABLE_COLUMNS:
        return False
    if from_text and len(rows) < _MIN_TABLE_ROWS:
        return False
    return True


def _first_table(page, body_size: float | None = None):
    """Best table on a page when the default (ruled) extraction finds none."""
    for _name, settings in _ALL_STRATEGIES:
        try:
            found = page.find_tables(settings) if settings else page.find_tables()
        except Exception:  # noqa: BLE001 - try the next strategy
            continue
        from_text = bool(settings) and settings.get("vertical_strategy") == "text"
        for found_table in found:
            # NOTE: filter by the table's own bbox, so a letterhead block that
            # heuristic detection turned into a "table" never reaches the sheet
            if not _in_body_type(page, found_table.bbox, body_size):
                continue
            clean = _clean_table(found_table.extract())
            if _looks_like_table(clean, from_text=from_text):
                return clean
    return None


def _rebuild_from_ocr_lines(lines: list) -> list[list[str]] | None:
    """Rebuild a table from OCR lines, ignoring letterhead bands.

    NOTE: OCR of a ruled table yields one line per cell, so the cells get their
    own boxes and a real grid can be recovered. A letterhead instead yields a
    few wide lines whose left edges match nothing below them. Grouping by row
    bands first, then keeping only consecutive bands that share a column layout,
    drops the letterhead and keeps the table - something pdfplumber cannot do on
    a text layer, because that layer has no cell geometry at all.
    """
    bands: list[list] = []
    for line in sorted(lines, key=lambda item: item.box[1]):
        x0, y0, _x1, y1 = line.box
        for band in bands:
            first = band[0]
            # same visual row when the vertical centres overlap
            if abs((y0 + y1) / 2 - (first.box[1] + first.box[3]) / 2) < (y1 - y0) * 0.6:
                band.append(line)
                break
        else:
            bands.append([line])

    if len(bands) < _MIN_TABLE_ROWS:
        return None

    # column starts of one band: the x of each of its cells, left to right
    def starts(band: list) -> list[float]:
        return sorted(line.box[0] for line in band)

    def same_layout(a: list[float], b: list[float]) -> bool:
        if len(a) != len(b):
            return False
        return all(abs(left - right) < 25 for left, right in zip(a, b))

    # NOTE: only multi-cell rows can form a table. A letterhead line is a single
    # run of text (or, when OCR splits it, a stray one-letter cell plus the
    # rest), so dropping single-cell bands first stops the header from forming
    # its own long "run" that could outvote the real table below.
    def is_row(band: list) -> bool:
        cells = sorted(band, key=lambda item: item.box[0])
        if len(cells) < _MIN_TABLE_COLUMNS:
            return False
        return len(cells[0].text.strip()) > 1

    rows = [band for band in bands if is_row(band)]
    if len(rows) < _MIN_TABLE_ROWS:
        return None

    best: list[list] = []
    run: list[list] = []
    for band in rows:
        if run and same_layout(starts(run[-1]), starts(band)):
            run.append(band)
        else:
            run = [band]
        if len(run) > len(best):
            best = list(run)

    if len(best) < _MIN_TABLE_ROWS:
        return None
    columns = starts(best[0])
    if len(columns) < _MIN_TABLE_COLUMNS:
        return None

    table: list[list[str]] = []
    for band in best:
        row = [""] * len(columns)
        for line in sorted(band, key=lambda item: item.box[0]):
            # place each cell under the column its left edge belongs to
            index = min(
                range(len(columns)),
                key=lambda i: abs(columns[i] - line.box[0]),
            )
            row[index] = (row[index] + " " + line.text).strip()
        table.append(row)
    return _clean_table(table)


def pdf_to_xlsx(
    src: Path,
    out_path: Path,
    ocr_pages: list | None = None,
) -> tuple[Path, int]:
    """Write every extracted table to its own sheet. Returns (path, table count).

    NOTE: ocr_pages is the OcrPage list for the same pages, passed in when the
    source was a scan. A scan's text layer has no cell geometry, so its tables
    are rebuilt from those boxes (see _rebuild_from_ocr_lines) rather than left
    to pdfplumber's heuristics, which read a letterhead as the table.
    """
    tables: list[tuple[int, int, list]] = []
    try:
        with pdfplumber.open(str(src)) as pdf:
            for page_number, page in enumerate(pdf.pages, start=1):
                body_size = _body_font_size(page)
                found_on_page = 0
                for found_table in page.find_tables():
                    bbox = found_table.bbox
                    if not _in_body_type(page, bbox, body_size):
                        continue
                    clean = _clean_table(found_table.extract())
                    if not _looks_like_table(clean, from_text=False):
                        continue
                    found_on_page += 1
                    tables.append((page_number, found_on_page, clean))
                if found_on_page:
                    continue
                fallback = None
                if ocr_pages:
                    page_lines = [
                        line
                        for ocr_page in ocr_pages
                        if ocr_page.number == page_number
                        for line in ocr_page.lines
                    ]
                    fallback = _rebuild_from_ocr_lines(page_lines)
                if fallback is None:
                    fallback = _first_table(page, body_size)
                if fallback:
                    tables.append((page_number, 1, fallback))
    except ConversionError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise ConversionError(f"table extraction failed: {exc}") from exc

    if not tables:
        raise ConversionError(
            "no tables found in this PDF (only ruled or column-aligned pages "
            "can be read as tables)"
        )

    workbook = Workbook()
    workbook.remove(workbook.active)
    for page_number, table_index, table in tables:
        name = f"p{page_number}_t{table_index}"[:31]
        sheet = workbook.create_sheet(title=name)
        for row in table:
            sheet.append(row)
        for cell in sheet[1]:
            cell.font = Font(bold=True)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        workbook.save(out_path)
    except Exception as exc:  # noqa: BLE001
        # NOTE: openpyxl raises IllegalCharacterError on any control byte left in
        # a cell. Cleaning should prevent it, but a workbook-level rejection must
        # still become a per-file error instead of aborting the whole batch.
        raise ConversionError(f"cannot write spreadsheet: {exc}") from exc
    return out_path, len(tables)
