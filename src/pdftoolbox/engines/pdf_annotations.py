"""Add real PDF annotations with pypdf (BSD-3-Clause).

An annotation is an object a reader can act on: a highlight, a sticky note,
a drawn rectangle. Unlike the overlay approach used by the text editor (which
draws pixels onto the page), these are stored IN the file, so a reader can
select, search and remove them again.

Design rules shared with the rest of the app:
  * the original file is never overwritten (:func:`pdf_edit.unique_path`),
  * every failure is reported as a :class:`ConversionError`,
  * only permissive dependencies are used, so the clean build stays AGPL-free.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from pypdf import PdfReader, PdfWriter
from pypdf.annotations import Highlight, Rectangle, Text
from pypdf.errors import PdfReadError
from pypdf.generic import ArrayObject, FloatObject

from . import ConversionError
from .pdf_edit import unique_path

#: The kinds of annotation the app can write.
HIGHLIGHT = "highlight"
NOTE = "note"
RECTANGLE = "rectangle"

#: The highlight colours offered in the GUI, as PDF colour strings.
HIGHLIGHT_COLOURS = {
    "yellow": "ffff00",
    "green": "00ff00",
    "cyan": "00ffff",
    "magenta": "ff00ff",
    "red": "ff0000",
}


@dataclass
class Annotation:
    """One annotation to write onto a page."""

    kind: str
    #: The 1-based page the annotation belongs on.
    page: int
    #: The box in PDF points, measured from the BOTTOM-LEFT of the page.
    rect: tuple[float, float, float, float]
    #: The note text (only used by a sticky note).
    text: str = ""
    #: The highlight colour name (only used by a highlight).
    colour: str = "yellow"


def _open_reader(src: Path) -> PdfReader:
    """Read ``src``, trying the empty password for edit-protected files."""
    try:
        reader = PdfReader(str(src))
    except (PdfReadError, OSError) as exc:
        raise ConversionError(f"cannot read {Path(src).name}: {exc}") from exc
    if reader.is_encrypted:
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


def _normalise(rect: tuple[float, float, float, float]) -> tuple[float, ...]:
    """Order the corners and reject a box that has no area."""
    try:
        x0, y0, x1, y1 = (float(value) for value in rect)
    except (TypeError, ValueError) as exc:
        raise ConversionError("the annotation box has no usable position") from exc
    left, right = sorted((x0, x1))
    bottom, top = sorted((y0, y1))
    if right - left < 1 or top - bottom < 1:
        raise ConversionError("the annotation box is too small to draw")
    return left, bottom, right, top


def _quad_points(rect: tuple[float, ...]) -> ArrayObject:
    """The four corners of a highlight, in the order the PDF expects.

    NOTE: /QuadPoints runs counter-clockwise from the bottom-left, and a
    highlight with fewer than four points is rejected by many readers.
    """
    left, bottom, right, top = rect
    return ArrayObject(
        [
            FloatObject(left),
            FloatObject(bottom),
            FloatObject(right),
            FloatObject(bottom),
            FloatObject(right),
            FloatObject(top),
            FloatObject(left),
            FloatObject(top),
        ]
    )


def build_annotation(item: Annotation) -> dict:
    """Turn one request into the annotation object pypdf writes.

    NOTE: the box is measured from the bottom-left of the page, like every
    other PDF coordinate, so the GUI must convert from its top-left pixels.
    """
    rect = _normalise(item.rect)
    if item.kind == HIGHLIGHT:
        colour = HIGHLIGHT_COLOURS.get(item.colour, HIGHLIGHT_COLOURS["yellow"])
        return Highlight(rect=rect, quad_points=_quad_points(rect), highlight_color=colour)
    if item.kind == NOTE:
        if not item.text.strip():
            raise ConversionError("a sticky note needs some text")
        return Text(rect=rect, text=item.text)
    if item.kind == RECTANGLE:
        return Rectangle(rect=rect, interior_color=None)
    raise ConversionError(f"unknown annotation kind '{item.kind}'")


def add_annotations(
    src: Path,
    out_path: Path,
    annotations: list[Annotation],
) -> Path:
    """Write a copy of ``src`` carrying the given annotations."""
    if not annotations:
        raise ConversionError("there are no annotations to add")

    reader = _open_reader(Path(src))
    count = len(reader.pages)
    if count == 0:
        raise ConversionError(f"{Path(src).name} has no pages")

    writer = PdfWriter(clone_from=reader)
    for item in annotations:
        if not 1 <= item.page <= count:
            raise ConversionError(
                f"page {item.page} is out of range (the document has {count} pages)"
            )
        try:
            annotation = build_annotation(item)
        except ConversionError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise ConversionError(f"cannot build the annotation: {exc}") from exc
        try:
            writer.add_annotation(page_number=item.page - 1, annotation=annotation)
        except Exception as exc:  # noqa: BLE001
            raise ConversionError(f"cannot add the annotation: {exc}") from exc

    target = unique_path(Path(out_path))
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        with target.open("wb") as handle:
            writer.write(handle)
    except OSError as exc:
        raise ConversionError(f"cannot write {target.name}: {exc}") from exc
    return target


def list_annotations(src: Path) -> list[dict]:
    """Every annotation already in the document, for the GUI to show.

    NOTE: the page is 1-based and the box is reported from the BOTTOM-LEFT,
    the same convention :func:`add_annotations` writes.
    """
    reader = _open_reader(Path(src))
    found: list[dict] = []
    for index, page in enumerate(reader.pages, start=1):
        for annot in page.get("/Annots") or []:
            try:
                obj = annot.get_object()
            except Exception:  # noqa: BLE001 - a broken annotation is skipped
                continue
            subtype = str(obj.get("/Subtype") or "")
            if subtype == "/Widget":
                # form fields are widgets, not user annotations
                continue
            rect = [float(value) for value in (obj.get("/Rect") or (0, 0, 0, 0))]
            found.append(
                {
                    "page": index,
                    "subtype": subtype.lstrip("/"),
                    "rect": tuple(rect),
                    "text": str(obj.get("/Contents") or ""),
                }
            )
    return found


def count_annotations(src: Path) -> int:
    """How many annotations the document carries."""
    return len(list_annotations(src))

