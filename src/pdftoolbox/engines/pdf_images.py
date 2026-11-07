"""Crop the illustrations out of a PDF page (pypdfium2 + pdfplumber, permissive).

Why this exists: an illustration inside a converted spreadsheet or document is
real content and must survive the conversion. The catch is that "an image" in a
PDF container is not the same as "a picture the reader sees":

* a rasterised scan is ONE image that covers the whole page;
* pdf2docx rasterises page furniture (backgrounds, ruled boxes) into full-page
  PNGs as well.

Embedding those would drown the result in a picture of the page - which is
exactly the complaint that used to be "solved" by deleting every image in the
DOCX. The real fix is to keep the genuinely small, page-independent images and
skip the page-sized rasters. That is what :func:`page_illustrations` decides,
using the page's own dimensions and (when available) its table boxes.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pdfplumber
import pypdfium2 as pdfium

# An image this large relative to the page is a scan or page furniture, never an
# illustration: an illustration shares the page with text and a table.
_MAX_PAGE_COVERAGE = 0.6
# Nor does an illustration span essentially the full page width or height.
_MAX_STRIP_FRACTION = 0.95

# pdfplumber reports an image box as a 4-point polygon in PDF user space. Points
# are (x, y) pairs read in reading order, so the top-left is the min and the
# bottom-right the max of x and y.
_MIN_POINTS = 4


@dataclass
class Illustration:
    """One kept image: where it sits on the page and how big it is.

    The geometry is in PDF points (72/inch) - the unit openpyxl and python-docx
    are both happy to convert from.
    """

    page: int
    x0: float
    x1: float
    top: float
    bottom: float
    width_pt: float
    height_pt: float


def _bbox(box: dict) -> tuple[float, float, float, float] | None:
    """``(x0, x1, top, bottom)`` in top-down PDF user space for a pdfplumber box."""
    points = box.get("points") or []
    if len(points) < _MIN_POINTS:
        return None
    xs = [float(x) for x, _y in points]
    ys = [float(y) for _x, y in points]
    # pdfplumber's y grows downward already, so top < bottom holds as-is
    return min(xs), max(xs), min(ys), max(ys)


def _image_box(image: dict) -> tuple[float, float, float, float] | None:
    """Image box as ``(x0, x1, top, bottom)``, from any pdfplumber image shape."""
    if image.get("points"):
        return _bbox(image)
    if image.get("x0") is None:
        return None
    # NOTE: image vertices carry x0/y0/x1/y1 AND top/bottom (y measured from the
    # page top). top/bottom are preferred when present because they already have
    # the page origin applied, which is what the crop maths needs.
    x0, x1 = float(image["x0"]), float(image["x1"])
    top = float(image.get("top", image["y0"]))
    bottom = float(image.get("bottom", image["y1"]))
    return min(x0, x1), max(x0, x1), min(top, bottom), max(top, bottom)



def _rect_points(bbox) -> list[tuple[float, float]]:
    """Turn pdfplumber's (x0, top, x1, bottom) into the polygon shape _bbox wants."""
    x0, top, x1, bottom = [float(value) for value in bbox]
    return [(x0, top), (x1, top), (x1, bottom), (x0, bottom)]


def _overlaps_table(bbox: tuple[float, float, float, float], table_boxes: list) -> bool:
    """True when an image box sits mostly inside any detected table box."""
    x0, x1, top, bottom = bbox
    image_area = (x1 - x0) * (bottom - top) or 1.0
    for tx0, tx1, ttop, tbottom in table_boxes:
        overlap_w = max(0.0, min(x1, tx1) - max(x0, tx0))
        overlap_h = max(0.0, min(bottom, tbottom) - max(top, ttop))
        overlap = overlap_w * overlap_h
        if overlap <= 0:
            continue
        table_area = (tx1 - tx0) * (tbottom - ttop) or 1.0
        # NOTE: a picture that shares most of a table's box is that table's own
        # content, already captured in the cells - it must not be duplicated as
        # a floating image on top of them
        if overlap / image_area > 0.5 or overlap / table_area > 0.5:
            return True
    return False


def _mostly_overlaps(a: Illustration, b: Illustration) -> bool:
    overlap_w = max(0.0, min(a.x1, b.x1) - max(a.x0, b.x0))
    overlap_h = max(0.0, min(a.bottom, b.bottom) - max(a.top, b.top))
    overlap = overlap_w * overlap_h
    if overlap <= 0:
        return False
    smallest = min(
        (a.x1 - a.x0) * (a.bottom - a.top),
        (b.x1 - b.x0) * (b.bottom - b.top),
    )
    return smallest > 0 and overlap / smallest > 0.8


def _drop_duplicates(illustrations: list[Illustration]) -> list[Illustration]:
    # NOTE: a decorative background drawn as several tiles arrives as several
    # overlapping boxes; stacking them would repeat the same picture, so only
    # boxes that do not fight with an already-kept one survive
    unique: list[Illustration] = []
    for candidate in illustrations:
        if any(_mostly_overlaps(candidate, kept) for kept in unique):
            continue
        unique.append(candidate)
    return unique


def _page_illustrations(page, page_number: int) -> list[Illustration]:
    width = float(page.width)
    height = float(page.height)
    page_area = width * height or 1.0

    table_boxes = []
    for table in page.find_tables():
        box = _bbox({"points": _rect_points(table.bbox)})
        if box:
            table_boxes.append(box)

    kept: list[Illustration] = []
    for image in page.images:
        bbox = _image_box(image)
        if bbox is None:
            continue
        x0, x1, top, bottom = bbox
        image_area = (x1 - x0) * (bottom - top)
        if image_area <= 0:
            continue
        # a scan, a background or a full-width rule is not an illustration
        if image_area / page_area > _MAX_PAGE_COVERAGE:
            continue
        if (x1 - x0) >= width * _MAX_STRIP_FRACTION:
            continue
        if (bottom - top) >= height * _MAX_STRIP_FRACTION:
            continue
        if _overlaps_table(bbox, table_boxes):
            continue
        kept.append(
            Illustration(
                page=page_number,
                x0=x0,
                x1=x1,
                top=top,
                bottom=bottom,
                width_pt=x1 - x0,
                height_pt=bottom - top,
            )
        )
    return _drop_duplicates(kept)


def page_illustrations(
    src: Path,
    page_numbers: list[int] | None = None,
) -> dict[int, list[Illustration]]:
    """Illustrations per 1-based page number, filtered to real pictures.

    A box is kept when it is small enough to be an illustration (see the module
    constants) and does not overlap the page's tables. Never raises on a page it
    cannot read: illustrations are a bonus, and losing them must not fail a
    conversion whose real job is text and tables.
    """
    illustrations: dict[int, list[Illustration]] = {}
    try:
        with pdfplumber.open(str(src)) as pdf:
            for page_number, page in enumerate(pdf.pages, start=1):
                if page_numbers and page_number not in page_numbers:
                    continue
                found = _page_illustrations(page, page_number)
                if found:
                    illustrations[page_number] = found
    except Exception:  # noqa: BLE001 - illustrations are best-effort
        return illustrations
    return illustrations


def crop_illustration(src: Path, illustration: Illustration, dpi: int = 200):
    """Render just the illustration's box to a PIL image (RGB).

    NOTE: cropping from a rendered page (rather than pulling the raw XObject)
    keeps transparency flattening and colour conversion in one place, and works
    for vector \"images\" that have no embedded bitmap at all.
    """
    scale = dpi / 72.0
    doc = pdfium.PdfDocument(str(src))
    try:
        page = doc[illustration.page - 1]
        bitmap = page.render(scale=scale)
        image = bitmap.to_pil().convert("RGB")
    finally:
        doc.close()

    left = max(0, min(round(illustration.x0 * scale), image.width - 1))
    upper = max(0, min(round(illustration.top * scale), image.height - 1))
    right = max(left + 1, min(round(illustration.x1 * scale), image.width))
    lower = max(upper + 1, min(round(illustration.bottom * scale), image.height))
    return image.crop((left, upper, right, lower))

