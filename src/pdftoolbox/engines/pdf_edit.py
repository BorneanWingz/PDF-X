"""Page-level PDF editing with pypdf + reportlab (both permissive).

This is the engine behind the Edit PDF tab. It covers the page operations every
PDF editor offers - reorganise (reorder/rotate/delete), split and extract - plus
the reportlab-backed stamps (watermark and page numbers) and text editing
(add text over a page, and find-and-replace by white-out + overlay).

Text editing here is OVERLAY-based: the original text stays in the file and new
text is drawn on top (find-and-replace covers the old words with a filled box
first). This is deliberate - rewriting existing PDF text streams needs a full
content-stream engine, which the permissive stack does not have.
Everything works on the pages of an existing PDF: no rendering pass, no AGPL
dependency.

Design rule shared with pdf_merge: a result is never written over an existing
file. Every writer here goes through :func:`unique_path`.
"""

from __future__ import annotations

import io
from dataclasses import dataclass
from pathlib import Path

import pypdfium2 as pdfium
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


def page_height(src: Path, page: int) -> float:
    """Height of one 1-based page in points (raises on an out-of-range page)."""
    reader = _open_reader(Path(src))
    count = len(reader.pages)
    if not 1 <= page <= count:
        raise ConversionError(f"page {page} out of range (1-{count})")
    return float(reader.pages[page - 1].mediabox.height)


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


# ---------- text editing (overlay-based) ----------


@dataclass
class TextMatch:
    """One occurrence of a search term: its page and box (PDF points, top-down).

    ``top``/``bottom`` are measured from the page TOP, so they line up with the
    reportlab overlay maths used everywhere else in this module.
    """

    page: int
    x0: float
    x1: float
    top: float
    bottom: float
    text: str

    @property
    def width(self) -> float:
        return self.x1 - self.x0

    @property
    def height(self) -> float:
        return self.bottom - self.top


def find_text(
    src: Path,
    needle: str,
    pages: list[int] | None = None,
    case_sensitive: bool = False,
) -> list[TextMatch]:
    """Every place ``needle`` appears, as boxes the caller can draw over.

    NOTE: search runs on pypdfium2's text page, which needs a real text layer -
    a scanned page has none, so it simply returns no matches (the caller can
    tell the user to OCR or use "add text" instead).
    """
    if not needle:
        return []

    matches: list[TextMatch] = []
    doc = pdfium.PdfDocument(str(src))
    try:
        for index in range(len(doc)):
            page_number = index + 1
            if pages and page_number not in pages:
                continue
            page = doc[index]
            textpage = page.get_textpage()
            try:
                matches.extend(
                    _page_matches(page, textpage, needle, page_number, case_sensitive)
                )
            finally:
                textpage.close()
    finally:
        doc.close()
    return matches


def _page_matches(
    page,
    textpage,
    term: str,
    page_number: int,
    case_sensitive: bool,
) -> list[TextMatch]:
    page_height = float(page.get_height())
    found: list[TextMatch] = []
    searcher = textpage.search(term, match_case=case_sensitive)
    try:
        while True:
            hit = searcher.get_next()
            if hit is None:
                break
            start, count = hit
            box = _match_box(textpage, start, count, page_height)
            if box is None:
                continue
            x0, x1, top, bottom = box
            found.append(
                TextMatch(
                    page=page_number,
                    x0=x0,
                    x1=x1,
                    top=top,
                    bottom=bottom,
                    text=textpage.get_text_range(start, count),
                )
            )
    finally:
        searcher.close()
    return found


def _match_box(textpage, start: int, count: int, page_height: float):
    """Union of the character boxes for a match, flipped to top-down coords."""
    if count <= 0:
        return None
    left = right = top = bottom = None
    for offset in range(start, start + count):
        charbox = textpage.get_charbox(offset)
        if charbox is None:
            continue
        x0, y0, x1, y1 = charbox
        left = x0 if left is None else min(left, x0)
        right = x1 if right is None else max(right, x1)
        # pypdfium2 y grows upward from the page bottom; flip to top-down
        char_top = page_height - y1
        char_bottom = page_height - y0
        top = char_top if top is None else min(top, char_top)
        bottom = char_bottom if bottom is None else max(bottom, char_bottom)
    if left is None:
        return None
    return left, right, top, bottom


@dataclass
class PlacedText:
    """Text to draw on one page, positioned in PDF points from the page TOP."""

    page: int
    text: str
    x: float
    top: float
    font_size: int = 12
    color: tuple[float, float, float] = (0.0, 0.0, 0.0)




def add_text(src: Path, out_path: Path, items: list[PlacedText]) -> Path:
    """Draw one or more pieces of text onto a copy of ``src``.

    Each item names a page and a top-left anchor (x, top) in points. The text is
    merged over that page, so the page's own content is untouched - this is the
    "add a note / correction" operation, not a rewrite of existing words.
    """
    if not [item for item in items if item.text.strip()]:
        raise ConversionError("no text to add")

    per_page: dict[int, list[PlacedText]] = {}
    for item in items:
        if item.text.strip():
            per_page.setdefault(item.page, []).append(item)

    reader = _open_reader(src)
    writer = PdfWriter()
    for index, source_page in enumerate(reader.pages, start=1):
        page = writer.add_page(source_page)
        if index not in per_page:
            continue
        width = float(page.mediabox.width)
        height = float(page.mediabox.height)
        page.merge_page(_text_reader(width, height, per_page[index]).pages[0])

    _copy_metadata(reader, writer)
    return _write(writer, out_path)


def replace_text(
    src: Path,
    out_path: Path,
    needle: str,
    replacement: str,
    pages: list[int] | None = None,
    case_sensitive: bool = False,
    font_size: int = 12,
    cover_color: tuple[float, float, float] = (1.0, 1.0, 1.0),
) -> tuple[Path, int]:
    """Find ``needle`` and draw ``replacement`` over each hit.

    Returns ``(path, match_count)``. NOTE: the old text is covered with a filled
    box, not removed - so it is hidden, but still present in the file's text
    layer. That is the honest limit of overlay editing without a content-stream
    engine.
    """
    matches = find_text(src, needle, pages=pages, case_sensitive=case_sensitive)
    if not matches:
        raise ConversionError(f"text not found: {needle!r}")

    replacements: dict[int, list[PlacedText]] = {}
    for match in matches:
        # keep the original size but never overflow the box the words occupied
        size = max(6, min(font_size, int(round(match.height * 0.85)) or font_size))
        replacements.setdefault(match.page, []).append(
            PlacedText(
                page=match.page,
                text=replacement,
                x=match.x0,
                top=match.top,
                font_size=size,
            )
        )

    reader = _open_reader(src)
    writer = PdfWriter()
    for index, source_page in enumerate(reader.pages, start=1):
        page = writer.add_page(source_page)
        page_matches = [m for m in matches if m.page == index]
        if not page_matches:
            continue
        width = float(page.mediabox.width)
        height = float(page.mediabox.height)
        overlay = _replace_reader(
            width, height, page_matches, replacements.get(index, []), cover_color
        )
        page.merge_page(overlay.pages[0])

    _copy_metadata(reader, writer)
    return _write(writer, out_path), len(matches)


def _text_reader(width: float, height: float, items: list[PlacedText]) -> PdfReader:
    """A one-page reportlab PDF drawing each placed text at its anchor."""
    from reportlab.lib.colors import Color
    from reportlab.pdfgen import canvas

    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=(width, height))
    for item in items:
        # reportlab's origin is bottom-left; convert the top-down anchor
        y = height - item.top - item.font_size
        pdf.setFillColor(Color(*item.color))
        pdf.setFont("Helvetica", item.font_size)
        pdf.drawString(item.x, y, item.text)
    pdf.showPage()
    pdf.save()
    buffer.seek(0)
    return PdfReader(buffer)


def _replace_reader(
    width: float,
    height: float,
    matches: list[TextMatch],
    replacements: list[PlacedText],
    cover_color: tuple[float, float, float],
) -> PdfReader:
    """One overlay that paints a cover box over each match, then the new text."""
    from reportlab.lib.colors import Color
    from reportlab.pdfgen import canvas

    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=(width, height))
    pdf.setFillColor(Color(*cover_color))
    for match in matches:
        # a hair of padding hides the original glyph edges
        x = match.x0 - 1
        y = height - match.bottom - 1
        pdf.rect(x, y, match.width + 2, match.height + 2, stroke=0, fill=1)

    pdf.setFillColor(Color(0, 0, 0))
    for item in replacements:
        y = height - item.top - item.font_size
        pdf.setFont("Helvetica", item.font_size)
        pdf.drawString(item.x, y, item.text)
    pdf.showPage()
    pdf.save()
    buffer.seek(0)
    return PdfReader(buffer)

