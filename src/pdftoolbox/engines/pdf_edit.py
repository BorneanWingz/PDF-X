"""Page-level PDF editing with pypdf + reportlab (both permissive).

This is the engine behind the Edit PDF tab. It covers the page operations every
PDF editor offers - reorganise (reorder/rotate/delete), split and extract - plus
the reportlab-backed stamps (watermark and page numbers). Everything works on the
pages of an existing PDF: no rendering pass, no AGPL dependency.

Design rule shared with pdf_merge: a result is never written over an existing
file. Every writer here goes through :func:`unique_path`.
"""

from __future__ import annotations

import io
from pathlib import Path

from pypdf import PdfReader, PdfWriter
from pypdf.errors import PdfReadError

from . import ConversionError


def _open_reader(src: Path) -> PdfReader:
    """Read ``src``, trying the empty password for edit-protected files."""
    try:
        reader = PdfReader(str(src))
    except (PdfReadError, OSError) as exc:
        raise ConversionError(f"cannot read {Path(src).name}: {exc}") from exc
    if reader.is_encrypted:
        # NOTE: same rule as pdf_merge - many bank/government PDFs only restrict
        # editing and open with a blank password; a real password still fails
        try:
            if not reader.decrypt(""):
                raise ConversionError(
                    f"{Path(src).name} is password-protected; unlock it first"
                )
        except ConversionError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise ConversionError(
                f"{Path(src).name} is password-protected; unlock it first"
            ) from exc
    return reader


def unique_path(path: Path) -> Path:
    """Never overwrite an existing file; append (1), (2), ... before the suffix."""
    path = Path(path)
    if not path.exists():
        return path
    stem, suffix = path.stem, path.suffix or ".pdf"
    for counter in range(1, 1000):
        candidate = path.with_name(f"{stem} ({counter}){suffix}")
        if not candidate.exists():
            return candidate
    raise ConversionError(f"cannot find a free filename near {path.name}")


def page_count(src: Path) -> int:
    """Number of pages in ``src`` (0 for a file with none)."""
    return len(_open_reader(Path(src)).pages)


def _write(writer: PdfWriter, out_path: Path) -> Path:
    target = unique_path(out_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        with target.open("wb") as handle:
            writer.write(handle)
    except OSError as exc:
        raise ConversionError(f"cannot write {target.name}: {exc}") from exc
    return target


def _validate_pages(pages: list[int], count: int) -> list[int]:
    """Clamp away out-of-range 1-based page numbers, keeping the order given."""
    kept = [number for number in pages if 1 <= number <= count]
    if not kept:
        raise ConversionError(f"no valid pages selected (document has {count})")
    return kept


def organize(
    src: Path,
    out_path: Path,
    order: list[int] | None = None,
    rotations: dict[int, int] | None = None,
) -> Path:
    """Write a reordered / rotated copy of ``src``.

    ``order`` is the new 1-based page sequence (source order when None), so the
    same call also handles delete (leave pages out) and duplicate (list twice).
    ``rotations`` maps a 1-based SOURCE page number to degrees clockwise; the
    rotation follows the page wherever it lands in the new order.
    """
    reader = _open_reader(src)
    count = len(reader.pages)
    if count == 0:
        raise ConversionError(f"{src.name} has no pages")

    sequence = _validate_pages(order, count) if order else list(range(1, count + 1))
    rotations = rotations or {}

    writer = PdfWriter()
    for number in sequence:
        page = reader.pages[number - 1]
        angle = rotations.get(number, 0) % 360
        # NOTE: '/Rotate' is set on the page object so the turn is baked into the
        # output - a viewer without the original context still shows it upright
        if angle:
            page.rotate(angle)
        writer.add_page(page)

    _copy_metadata(reader, writer)
    return _write(writer, out_path)


def _copy_metadata(reader: PdfReader, writer: PdfWriter) -> None:
    """Carry the title/author across, so an edited copy stays recognisable."""
    try:
        source_meta = reader.metadata or {}
        writer.add_metadata(
            {key: value for key, value in source_meta.items() if value is not None}
        )
    except Exception:  # noqa: BLE001 - metadata is a nicety, never a reason to fail
        pass


def split_pdf(
    src: Path,
    out_dir: Path,
    every: int = 1,
    base_name: str | None = None,
) -> list[Path]:
    """Split ``src`` into chunks of ``every`` pages, written into ``out_dir``.

    Returns the list of created files in page order. ``base_name`` names the
    parts ("<stem>_part1.pdf" by default); the caller passes the tagged name so
    the results follow the app's naming rule.
    """
    reader = _open_reader(src)
    count = len(reader.pages)
    if count == 0:
        raise ConversionError(f"{src.name} has no pages")
    if every < 1:
        raise ConversionError("split size must be at least 1 page")

    base = base_name or src.stem
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    outputs: list[Path] = []
    width = len(str((count + every - 1) // every))  # pad so parts sort correctly
    for start in range(0, count, every):
        writer = PdfWriter()
        for number in range(start, min(start + every, count)):
            writer.add_page(reader.pages[number])
        index = start // every + 1
        target = out_dir / f"{base}_part{index:0{width}d}.pdf"
        outputs.append(_write(writer, target))
    return outputs


def extract_pages(
    src: Path,
    out_path: Path,
    pages: list[int],
) -> Path:
    """Write only the listed 1-based pages, in the order given, to ``out_path``."""
    reader = _open_reader(src)
    count = len(reader.pages)
    sequence = _validate_pages(pages, count)
    writer = PdfWriter()
    for number in sequence:
        writer.add_page(reader.pages[number - 1])
    return _write(writer, out_path)


def add_watermark(
    src: Path,
    out_path: Path,
    text: str,
    opacity: float = 0.25,
    font_size: int = 48,
    diagonal: bool = True,
) -> Path:
    """Stamp ``text`` over every page as a translucent watermark.

    NOTE: reportlab draws the text into a one-page overlay that is merged onto
    each source page with pypdf, so the original content stays selectable. The
    overlay page is transparent except for the text, hence the low default
    opacity.
    """
    text = text.strip()
    if not text:
        raise ConversionError("watermark text is empty")

    reader = _open_reader(src)
    writer = PdfWriter()
    for source_page in reader.pages:
        # NOTE: clone the page into the writer BEFORE merging the overlay -
        # pypdf 6 warns that replace_contents() on an unattached page is
        # unreliable (and removes it in 7.0). add_page() returns the page now
        # owned by the writer, which is the object safe to merge onto.
        page = writer.add_page(source_page)
        width = float(page.mediabox.width)
        height = float(page.mediabox.height)
        overlay = _overlay_reader(width, height, text, opacity, font_size, diagonal)
        page.merge_page(overlay.pages[0])
    _copy_metadata(reader, writer)
    return _write(writer, out_path)


def add_page_numbers(
    src: Path,
    out_path: Path,
    pattern: str = "Page {page} of {total}",
    position: str = "bottom-center",
    font_size: int = 10,
) -> Path:
    """Stamp a page number on every page; ``pattern`` may use {page} and {total}."""
    reader = _open_reader(src)
    total = len(reader.pages)
    if total == 0:
        raise ConversionError(f"{src.name} has no pages")

    writer = PdfWriter()
    for index, source_page in enumerate(reader.pages, start=1):
        # clone into the writer first, then merge (see add_watermark's note)
        page = writer.add_page(source_page)
        label = pattern.replace("{page}", str(index)).replace("{total}", str(total))
        width = float(page.mediabox.width)
        height = float(page.mediabox.height)
        overlay = _number_reader(width, height, label, position, font_size)
        page.merge_page(overlay.pages[0])
    _copy_metadata(reader, writer)
    return _write(writer, out_path)


def _overlay_reader(
    width: float,
    height: float,
    text: str,
    opacity: float,
    font_size: int,
    diagonal: bool,
) -> PdfReader:
    """A one-page reportlab PDF holding just the watermark text."""
    from reportlab.lib.colors import Color
    from reportlab.pdfgen import canvas

    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=(width, height))
    pdf.saveState()
    pdf.setFillColor(Color(0.5, 0.5, 0.5, alpha=max(0.02, min(1.0, opacity))))
    pdf.setFont("Helvetica-Bold", font_size)
    if diagonal:
        # centre the text, then rotate it so it runs corner to corner
        pdf.translate(width / 2.0, height / 2.0)
        pdf.rotate(45)
        pdf.drawCentredString(0, 0, text)
    else:
        pdf.drawCentredString(width / 2.0, height / 2.0, text)
    pdf.restoreState()
    pdf.showPage()
    pdf.save()
    buffer.seek(0)
    return PdfReader(buffer)


def _number_reader(
    width: float,
    height: float,
    label: str,
    position: str,
    font_size: int,
) -> PdfReader:
    """A one-page reportlab PDF holding just the page number."""
    from reportlab.pdfgen import canvas

    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=(width, height))
    pdf.setFont("Helvetica", font_size)
    margin = 24
    x = _number_x(position, width)
    y = margin if "bottom" in position else height - margin - font_size
    if x == "center":
        pdf.drawCentredString(width / 2.0, y, label)
    else:
        pdf.drawString(x, y, label)
    pdf.showPage()
    pdf.save()
    buffer.seek(0)
    return PdfReader(buffer)


def _number_x(position: str, width: float):
    if "left" in position:
        return 24
    if "right" in position:
        return width - 24
    return "center"


