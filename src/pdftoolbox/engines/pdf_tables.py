"""Extract tables from PDFs into XLSX using pdfplumber + openpyxl (MIT)."""

from __future__ import annotations

from pathlib import Path

import pdfplumber
from openpyxl import Workbook
from openpyxl.styles import Font

from . import ConversionError

_ALL_STRATEGIES: tuple[str, dict | None] = [
    ("lines", {"vertical_strategy": "lines", "horizontal_strategy": "lines"}),
    ("text", {"vertical_strategy": "text", "horizontal_strategy": "text"}),
    ("mixed", None),  # pdfplumber defaults handle most ruled documents
]


def _first_table(page):
    for _, settings in _ALL_STRATEGIES:
        try:
            tables = (
                page.extract_tables(settings) if settings else page.extract_tables()
            )
        except Exception:  # noqa: BLE001 - try the next strategy
            continue
        for table in tables:
            if table and any(any(cell for cell in row) for row in table):
                return table
    return None


def pdf_to_xlsx(src: Path, out_path: Path) -> tuple[Path, int]:
    """Write every extracted table to its own sheet. Returns (path, table count)."""
    tables: list[tuple[int, int, list]] = []
    try:
        with pdfplumber.open(str(src)) as pdf:
            for page_number, page in enumerate(pdf.pages, start=1):
                for table_index, table in enumerate(page.extract_tables() or [], start=1):
                    clean = [
                        [("" if cell is None else str(cell)) for cell in row]
                        for row in table
                    ]
                    if any(any(cell for cell in row) for row in clean):
                        tables.append((page_number, table_index, clean))
                if not tables:
                    fallback = _first_table(page)
                    if fallback:
                        clean = [
                            [("" if cell is None else str(cell)) for cell in row]
                            for row in fallback
                        ]
                        tables.append((page_number, 1, clean))
    except ConversionError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise ConversionError(f"table extraction failed: {exc}") from exc

    if not tables:
        raise ConversionError(
            "no tables found in this PDF (scanned documents need OCR first)"
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
    workbook.save(out_path)
    return out_path, len(tables)
