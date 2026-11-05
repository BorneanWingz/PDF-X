"""Images to PDF using Pillow (MIT-CMU). Supports multipage TIFF."""

from __future__ import annotations

from pathlib import Path

from PIL import Image

from . import ConversionError

_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".bmp", ".webp", ".tif", ".tiff", ".gif"}


def is_image(path: Path) -> bool:
    return path.suffix.lower() in _IMAGE_SUFFIXES


def _load_frames(path: Path) -> list[Image.Image]:
    # NOTE: every frame of a multi-page TIFF becomes its own PDF page -
    # a common scanner output format, so this is intentional not incidental
    try:
        with Image.open(path) as img:
            frames = []
            for frame_index in range(getattr(img, "n_frames", 1)):
                img.seek(frame_index)
                frames.append(img.convert("RGB"))
            return frames
    except Exception as exc:  # noqa: BLE001
        raise ConversionError(f"cannot read image {path.name}: {exc}") from exc


def images_to_pdf(paths: list[Path], out_path: Path) -> Path:
    if not paths:
        raise ConversionError("no input images given")
    pages: list[Image.Image] = []
    for path in paths:
        if not is_image(path):
            raise ConversionError(f"not a supported image: {path.name}")
        pages.extend(_load_frames(path))
    if not pages:
        raise ConversionError("no images could be read")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    first, rest = pages[0], pages[1:]
    first.save(out_path, format="PDF", save_all=True, append_images=rest)
    return out_path
