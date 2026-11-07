"""PDF -> DOCX converter plugin (AGPL component, isolated on purpose).

This plugin uses pdf2docx / PyMuPDF, which are AGPL-3.0. It lives outside
the core package so permissive builds can exclude this single file.

AGPL NOTICE: if you bundle or redistribute this file together with its
dependencies, the combined work falls under AGPL-3.0 terms.

Copy the whole plugins/ folder next to PDFToolbox.exe to enable it.
"""

from __future__ import annotations

import posixpath
import re
import shutil
import tempfile
import zipfile
from pathlib import Path

NAME = "pdf2docx"
VERSION = "0.5.13"
LICENSE = "AGPL-3.0"
TARGETS = ["docx"]
AVAILABILITY_HINT = "install with: uv pip install pdf2docx (AGPL-3.0)"


def available() -> bool:
    import importlib.util

    return importlib.util.find_spec("pdf2docx") is not None


def convert(
    src: Path,
    out_dir: Path,
    pages: "list[int] | None" = None,
    ocr_layer: bool = False,
    out_name: "str | None" = None,
) -> Path:
    from pdf2docx import Converter

    out_dir.mkdir(parents=True, exist_ok=True)
    # NOTE: out_name is the tagged name the app wants ("report_pdfx.docx"); it is
    # only a file name, so it must never carry a folder of its own
    out_path = out_dir / (Path(out_name).name if out_name else f"{src.stem}.docx")

    # pdf2docx converts one contiguous range; a page list uses its span.
    # NOTE: pdf2docx (Converter.convert) accepts start/end indexes only, so
    # --pages 2-3 maps exactly; non-contiguous lists (e.g. 1,5) widen to 1-5.
    # The CLI contract remains "pages", this is just how the engine handles it.
    start = 0
    end = None
    if pages:
        start = max(0, min(pages) - 1)
        end = max(pages)

    # NOTE: pdf2docx drops text drawn in render mode 3 (an invisible OCR layer)
    # unless it is told the source is an OCR-ed PDF. convert() sets ocr_layer
    # when it staged such a copy, so a scan must not come out empty.
    settings = {"ocr": 2} if ocr_layer else {}

    converter = Converter(str(src))
    try:
        converter.convert(str(out_path), start=start, end=end, **settings)
    finally:
        converter.close()

    # NOTE: illustrations are content and must stay. pdf2docx keeps a real
    # picture at its OWN resolution, so a small figure in the middle of a page
    # survives untouched. The one image that must NOT survive is a whole-page
    # raster (a scan): it would turn the document into a picture with an
    # invisible text layer over it. Only those are removed - see _strip_page_rasters.
    _strip_page_rasters(out_path)
    return out_path


def _strip_page_rasters(out_path: Path) -> int:
    """Remove only whole-page rasters from a DOCX. Returns the number removed.

    An illustration is kept: pdf2docx writes a real picture at its own pixel
    size, so a figure occupying part of a page is far smaller than the page
    raster. A scan, however, arrives as ONE media part the size of the entire
    page - embedding that makes the DOCX a picture with an invisible text layer,
    which is the case this strips.

    NOTE: the drawing references go first, then the now-orphaned media parts
    (and the thumbnail) are pruned from the package, along with the content
    types and relationships that named them.
    """
    from docx import Document
    from docx.oxml.ns import qn

    document = Document(str(out_path))
    # NOTE: collect first, remove after - deleting nodes while .iter() walks the
    # tree makes lxml skip the next sibling, so one image would survive
    targets = _page_raster_drawings(document, qn)
    for element in targets:
        # NOTE: a drawing can sit inside a hyperlink run, so the parent
        # (never the drawing itself) is what gets removed
        parent = element.getparent()
        if parent is not None:
            parent.remove(element)
    removed = len(targets)

    if removed:
        document.save(str(out_path))

    # NOTE: always prune, not only when drawings were removed - pdf2docx also
    # attaches a docProps/thumbnail.jpeg that no <w:drawing> points at
    _drop_raster_parts(out_path, page_parts=removed)
    return removed


def _page_raster_drawings(document, qn) -> list:
    """Body drawings whose embedded image is as large as a whole page."""
    page_width, page_height = _page_size(document)
    page_area = page_width * page_height or 1.0
    found = []
    for element in document.element.body.iter():
        if element.tag not in (qn("w:drawing"), qn("w:pict")):
            continue
        extent = element.find(".//" + qn("wp:extent"))
        if extent is None:
            continue
        cx = int(extent.get("cx", "0"))
        cy = int(extent.get("cy", "0"))
        if page_area and (cx * cy) / page_area >= _PAGE_RASTER_COVERAGE:
            found.append(element)
    return found


def _page_size(document) -> tuple[float, float]:
    """Page size in EMU, falling back to US Letter when the section is unset."""
    try:
        section = document.sections[0]
        return float(section.page_width), float(section.page_height)
    except (IndexError, AttributeError):
        return _LETTER_EMU


# A4 / Letter sit around 7.5 x 10.5 M EMU; a page-sized raster covers nearly all
# of it while an illustration covers a fraction.
_LETTER_EMU = (7_771_800.0, 10_058_400.0)
_PAGE_RASTER_COVERAGE = 0.85


_IMAGE_EXTENSIONS = (".png", ".jpeg", ".jpg", ".gif", ".bmp", ".tif", ".tiff", ".emf", ".wmf")
# [Content_Types].xml stores extensions without the leading dot
_IMAGE_TYPE_NAMES = {extension.lstrip(".") for extension in _IMAGE_EXTENSIONS}


def _drop_raster_parts(out_path: Path, page_parts: int) -> None:
    """Rewrite the package without its page-sized image parts.

    NOTE: keeps every smaller image, so illustrations survive. The thumbnail
    under docProps/ is always dropped - pdf2docx attaches one that no drawing
    points at, and it is a crop of the page, not content. [Content_Types].xml and
    every .rels are rewritten to match, otherwise Word calls the package corrupt.
    """
    with zipfile.ZipFile(str(out_path)) as archive:
        entries = [(item, archive.read(item.filename)) for item in archive.infolist()]

    dropped = _page_raster_names(entries, page_parts)
    if not dropped:
        return

    kept = [
        (item, data)
        for item, data in entries
        if posixpath.basename(item.filename) not in dropped
    ]
    # image file names are unique inside the package, so a basename is enough to
    # spot a relationship that points at a part which is being removed
    dropped_names = {posixpath.basename(name) for name in dropped}
    kept_extensions = {
        posixpath.splitext(item.filename)[1].lstrip(".").lower()
        for item, _data in kept
    }

    stripped = Path(tempfile.mkdtemp()) / "stripped.docx"
    with zipfile.ZipFile(str(stripped), "w", zipfile.ZIP_DEFLATED) as target:
        for item, data in kept:
            if item.filename == "[Content_Types].xml":
                data = _without_unused_image_types(data, kept_extensions)
            elif item.filename.endswith(".rels"):
                data = _without_relationships_to(data, dropped_names)
            target.writestr(item, data)
    shutil.move(str(stripped), str(out_path))


def _page_raster_names(entries: list, page_parts: int) -> set:
    """Basenames of image parts to remove: the thumbnail, plus page rasters.

    NOTE: the thumbnail is always removed. A page raster is identified by pixel
    area - it is far larger than any illustration - so only the number of
    stripped drawings decides how many of the biggest media parts go.
    """
    dropped: set = set()
    media: list[tuple[str, int]] = []
    for item, data in entries:
        name = item.filename
        lower = name.lower()
        basename = posixpath.basename(name)
        if not lower.endswith(_IMAGE_EXTENSIONS):
            continue
        if lower.startswith("docprops/"):
            # the thumbnail is a crop of the whole page, never content
            dropped.add(basename)
            continue
        media.append((basename, _pixel_area(data)))

    if page_parts > 0 and media:
        media.sort(key=lambda pair: pair[1], reverse=True)
        for basename, _area in media[:page_parts]:
            dropped.add(basename)
    return dropped


def _pixel_area(data: bytes) -> int:
    """Width x height of an image part, or 0 when it cannot be read."""
    try:
        from PIL import Image
        from io import BytesIO

        with Image.open(BytesIO(data)) as image:
            return image.width * image.height
    except Exception:  # noqa: BLE001 - an unreadable part is simply not a raster
        return 0




def _without_unused_image_types(data: bytes, kept_extensions: set) -> bytes:
    """Drop image Defaults no remaining part needs."""

    def _keep(match: "re.Match") -> str:
        extension = match.group(1).lower()
        stale = extension in _IMAGE_TYPE_NAMES and extension not in kept_extensions
        return "" if stale else match.group(0)

    text = data.decode("utf-8")
    text = re.sub(r'<Default[^>]*Extension="([^"]+)"[^>]*/>', _keep, text)
    return text.encode("utf-8")


def _without_relationships_to(data: bytes, dropped_names: set) -> bytes:
    """Drop relationships whose Target names a part that was removed."""

    def _keep(match: "re.Match") -> str:
        target = match.group(1)
        name = posixpath.basename(target.split("?", 1)[0])
        return "" if name in dropped_names else match.group(0)

    text = data.decode("utf-8")
    text = re.sub(r'<Relationship[^>]*Target="([^"]+)"[^>]*/>', _keep, text)
    return text.encode("utf-8")
