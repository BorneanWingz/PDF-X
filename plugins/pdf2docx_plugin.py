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
) -> Path:
    from pdf2docx import Converter

    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{src.stem}.docx"

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

    # NOTE: pdf2docx rasterises decorative page furniture (backgrounds, ruled
    # boxes) into full-page PNGs, which makes the DOCX an image with text on
    # top instead of an editable document. Those carry no selectable
    # information, so they are removed - the extracted text stays untouched.
    _strip_images(out_path)
    return out_path


def _strip_images(out_path: Path) -> int:
    """Remove every embedded image from a DOCX. Returns the number removed.

    NOTE: works straight on the OPC package, so body text, headers, footers and
    tables are all covered by one pass. The <w:drawing>/<w:pict> references go
    first, then the now-orphaned media parts (and the thumbnail) are pruned from
    the package, along with the content types and relationships that named them.
    """
    from docx import Document
    from docx.oxml.ns import qn

    document = Document(str(out_path))
    # NOTE: collect first, remove after - deleting nodes while .iter() walks the
    # tree makes lxml skip the next sibling, so one image would survive
    targets = [
        element
        for element in document.element.body.iter()
        if element.tag in (qn("w:drawing"), qn("w:pict"))
    ]
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
    _drop_media(out_path)
    return removed


_IMAGE_EXTENSIONS = (".png", ".jpeg", ".jpg", ".gif", ".bmp", ".tif", ".tiff", ".emf", ".wmf")
# [Content_Types].xml stores extensions without the leading dot
_IMAGE_TYPE_NAMES = {extension.lstrip(".") for extension in _IMAGE_EXTENSIONS}


def _drop_media(out_path: Path) -> None:
    """Rewrite the DOCX package without any image part.

    NOTE: covers more than word/media/* - a thumbnail under docProps/ is an image
    too. [Content_Types].xml and every .rels are rewritten to match, otherwise
    Word calls the package corrupt.
    """
    with zipfile.ZipFile(str(out_path)) as archive:
        entries = [(item, archive.read(item.filename)) for item in archive.infolist()]

    kept = [
        (item, data)
        for item, data in entries
        if not item.filename.lower().endswith(_IMAGE_EXTENSIONS)
    ]
    dropped = {
        item.filename
        for item, _data in entries
        if item.filename.lower().endswith(_IMAGE_EXTENSIONS)
    }
    if not dropped:
        return

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
