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
from pathlib import Path

import pdfplumber
from openpyxl import Workbook
from openpyxl.drawing.image import Image as XLImage
from openpyxl.styles import Font
from openpyxl.utils import get_column_letter

from . import ConversionError
from . import pdf_images

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
# NOTE: a real table spans most of the page width. A label/value block such as
# "Ref No : ..." covers far less, which is how an address block is told apart
# from a data table once OCR has given both the same two-column shape.
_MIN_TABLE_WIDTH_RATIO = 0.5
# NOTE: rows of one table sit about one glyph-height apart. A bigger blank band
# means the table ended and another one starts below (measured on a two-table
# lab report: rows ~1.2x apart, the gap between tables ~3.5x).
_TABLE_GAP_FACTOR = 2.0


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


def _row_height(band: list) -> float:
    """Median glyph height of one row band."""
    heights = sorted(line.box[3] - line.box[1] for line in band)
    return heights[len(heights) // 2]


def _row_gap(upper: list, lower: list) -> float:
    """Vertical white space between two consecutive row bands."""
    upper_bottom = max(line.box[3] for line in upper)
    lower_top = min(line.box[1] for line in lower)
    return max(0.0, lower_top - upper_bottom)


def _rows_to_table(blocks: list[list]) -> list[list[str]]:
    """Turn consecutive row bands into a rectangular table of strings."""
    columns = sorted(block.box[0] for block in blocks[0])
    table: list[list[str]] = []
    for band in blocks:
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


def _rebuild_tables_from_ocr_lines(lines: list) -> list[list[list[str]]]:
    """Rebuild EVERY table on a page from OCR lines, oldest first.

    NOTE: one page often carries two stacked tables (the Decanter report has a
    per-sample block and a second one below it). Keeping only the longest run of
    rows exported the first table and silently dropped the second, which is what
    "OCR did not recognise all tables" looked like to the user. Each run of rows
    sharing a column layout now becomes its own sheet.
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

    # column starts of one band: the x of each of its cells, left to right
    def starts(band: list) -> list[float]:
        return sorted(line.box[0] for line in band)

    def same_layout(a: list[float], b: list[float]) -> bool:
        if len(a) != len(b):
            return False
        return all(abs(left - right) < 25 for left, right in zip(a, b))

    # NOTE: only multi-cell rows can form a table. A letterhead line is a single
    # run of text (or, when OCR splits it, a stray one-letter cell plus the
    # rest), so single-cell and prose bands are dropped before grouping.
    def is_row(band: list) -> bool:
        cells = sorted(band, key=lambda item: item.box[0])
        if len(cells) < _MIN_TABLE_COLUMNS:
            return False
        return len(cells[0].text.strip()) > 1

    rows = [band for band in bands if is_row(band)]

    # split the rows into runs that each share one column layout, and that sit
    # close enough vertically to belong to the same table
    groups: list[list[list]] = []
    current: list[list] = []
    for band in rows:
        if current and same_layout(starts(current[-1]), starts(band)):
            # NOTE: stacked tables on one page often share a column layout, so
            # layout alone merged them into one sheet. A visible horizontal gap
            # between rows marks where one table ends and the next begins.
            if _row_gap(current[-1], band) > _TABLE_GAP_FACTOR * _row_height(current[-1]):
                groups.append(current)
                current = [band]
                continue
            current.append(band)
        else:
            if current:
                groups.append(current)
            current = [band]
    if current:
        groups.append(current)

    # NOTE: an address block ("Ref No: ...", "From: ...") also has two cells and
    # two rows, so structure alone cannot tell it from a table. What it lacks is
    # WIDTH: a label/value pair ends a third of the way across the page, while a
    # real table spreads over most of it. Requiring the widest row to reach half
    # the page keeps the data tables and drops the letterhead block.
    page_width = max((line.box[2] for line in lines), default=0.0)

    def wide_enough(group: list[list]) -> bool:
        if not page_width:
            return True
        right = max(line.box[2] for band in group for line in band)
        left = min(line.box[0] for band in group for line in band)
        return (right - left) >= page_width * _MIN_TABLE_WIDTH_RATIO

    tables: list[list[list[str]]] = []
    # NOTE: a header line is sometimes split by OCR into its own band, because
    # its wording sits a little higher than the data rows. It is held here and
    # prepended to the next group, but only when the column count matches, so an
    # unrelated heading cannot hijack a table below it.
    pending: list[list] = []
    for group in groups:
        if len(group) < _MIN_TABLE_ROWS:
            pending = group
            continue
        if not wide_enough(group):
            # a narrow label/value block: an address or letterhead, not a table
            pending = []
            continue
        blocks = group
        if pending and len(pending[0]) == len(group[0]):
            blocks = [*pending, *group]
        pending = []
        table = _rows_to_table(blocks)
        if len(table) >= _MIN_TABLE_ROWS:
            tables.append(table)
    return tables


def _rebuild_from_ocr_lines(lines: list) -> list[list[str]] | None:
    """First table only (kept for callers that expect a single result)."""
    tables = _rebuild_tables_from_ocr_lines(lines)
    return tables[0] if tables else None



def pdf_to_xlsx(
    src: Path,
    out_path: Path,
    ocr_pages: list | None = None,
    dpi: int = 200,
) -> tuple[Path, int]:
    """Write every extracted table to its own sheet. Returns (path, table count).

    NOTE: ocr_pages is the OcrPage list for the same pages, passed in when the
    source was a scan. A scan's text layer has no cell geometry, so its tables
    are rebuilt from those boxes (see _rebuild_from_ocr_lines) rather than left
    to pdfplumber's heuristics, which read a letterhead as the table.

    Illustrations are a separate concern: every real picture on a page goes onto
    an extra ``p<n>_images`` sheet, so the cells stay pure table data and a
    picture never lands on top of a header row.
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
                # NOTE: a scanned page is rebuilt from the OCR boxes, and EVERY
                # table found there gets its own sheet. Taking only the first
                # one silently dropped the lower table on reports that stack two
                # blocks, which read as "OCR missed the tables".
                rebuilt: list[list[list[str]]] = []
                if ocr_pages:
                    page_lines = [
                        line
                        for ocr_page in ocr_pages
                        if ocr_page.number == page_number
                        for line in ocr_page.lines
                    ]
                    rebuilt = _rebuild_tables_from_ocr_lines(page_lines)
                if rebuilt:
                    for index, table in enumerate(rebuilt, start=1):
                        tables.append((page_number, index, table))
                    continue
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

    # NOTE: illustrations go onto their own sheets so no table cell is moved.
    # A source without any real picture simply gains no extra sheet.
    illustrations = pdf_images.page_illustrations(src)
    if illustrations:
        _add_illustration_sheets(workbook, src, illustrations, dpi)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        workbook.save(out_path)
    except Exception as exc:  # noqa: BLE001
        # NOTE: openpyxl raises IllegalCharacterError on any control byte left in
        # a cell. Cleaning should prevent it, but a workbook-level rejection must
        # still become a per-file error instead of aborting the whole batch.
        raise ConversionError(f"cannot write spreadsheet: {exc}") from exc
    return out_path, len(tables)


# openpyxl anchors an image by its TOP-LEFT pixel; images are laid out in a
# single column, one blank pixel row apart, and each image is scaled to its
# original print size (points -> inches) so the sheet shows it as the PDF does.
_IMAGE_COLUMN_PX = 6
_IMAGE_ROW_GAP_PX = 8
# a picture wider than this is scaled down: Excel columns are not the place for a
# metre-wide scan, and one oversized image would push every later one off-sheet
_MAX_IMAGE_HEIGHT_PX = 720


def _add_illustration_sheets(workbook: Workbook, src: Path, illustrations, dpi: int) -> None:
    """One ``p<n>_images`` sheet per page that carries a real picture."""
    for page_number in sorted(illustrations):
        sheet = workbook.create_sheet(title=f"p{page_number}_images"[:31])
        sheet["A1"] = f"Page {page_number} illustrations"
        sheet["A1"].font = Font(bold=True)
        offset_px = 0
        for index, illustration in enumerate(illustrations[page_number], start=1):
            try:
                image = pdf_images.crop_illustration(src, illustration, dpi=dpi)
            except Exception:  # noqa: BLE001 - one bad crop must not lose the rest
                continue
            offset_px = _place_image(sheet, image, index, offset_px)


def _place_image(sheet, image, index: int, offset_px: int) -> int:
    """Anchor one image on ``sheet`` and return the next free pixel row."""
    # keep the aspect ratio while capping the on-sheet size
    width_px, height_px = image.size
    scale = min(1.0, _MAX_IMAGE_HEIGHT_PX / height_px) if height_px else 1.0
    target = XLImage(_image_stream(image))
    target.width = width_px * scale
    target.height = height_px * scale
    anchor = f"{get_column_letter(_IMAGE_COLUMN_PX)}{_row_for_offset(sheet, offset_px)}"
    target.anchor = anchor
    sheet.add_image(target)
    sheet.cell(row=_row_for_offset(sheet, offset_px), column=_IMAGE_COLUMN_PX + 1).value = (
        f"image {index}"
    )
    return offset_px + target.height + _IMAGE_ROW_GAP_PX


def _row_for_offset(sheet, offset_px: int) -> int:
    """First sheet row whose implied pixel offset is >= offset_px (row 2 start)."""
    if offset_px <= 0:
        return 2
    return 2 + int(offset_px / 20)  # Excel default row height ~20 px


def _image_stream(image):
    """A seekable buffer openpyxl can read; PIL images are otherwise lazy."""
    from io import BytesIO

    buffer = BytesIO()
    image.save(buffer, format="PNG")
    buffer.seek(0)
    return buffer
