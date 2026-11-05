"""Merge PDFs using pypdf (BSD-3-Clause).

Output page order follows the INPUT ORDER exactly: CLI argument order for
the command line, listbox order in the GUI. No sorting, no page interleave.
"""

from __future__ import annotations

from pathlib import Path

from pypdf import PdfReader, PdfWriter
from pypdf.errors import PdfReadError

from . import ConversionError


def _unique_path(path: Path) -> Path:
    """Never overwrite an existing file; append (1), (2), ... before .pdf."""
    # NOTE: merging is repetitive (weekly report + appendix), and silently
    # clobbering yesterday's merged file would lose work - hence the suffix
    if not path.exists():
        return path
    stem, suffix = path.stem, path.suffix or ".pdf"
    for counter in range(1, 1000):
        candidate = path.with_name(f"{stem} ({counter}){suffix}")
        if not candidate.exists():
            return candidate
    raise ConversionError(f"cannot find a free filename near {path.name}")


def _open_reader(path: Path) -> PdfReader:
    try:
        reader = PdfReader(str(path))
    except (PdfReadError, OSError) as exc:
        raise ConversionError(f"cannot read {path.name}: {exc}") from exc
    if reader.is_encrypted:
        # NOTE: try the empty password first - many "protected" PDFs from
        # banks/government only restrict editing; a real password still fails
        try:
            if not reader.decrypt(""):
                raise ConversionError(
                    f"{path.name} is password-protected; unlock it first"
                )
        except ConversionError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise ConversionError(
                f"{path.name} is password-protected; unlock it first"
            ) from exc
    return reader


def merge_pdf_files(inputs: list[Path], out_path: Path) -> Path:
    """Concatenate inputs in order into out_path (never overwrites)."""
    if not inputs:
        raise ConversionError("nothing to merge: no input files")

    writer = PdfWriter()
    total_pages = 0
    for path in inputs:
        reader = _open_reader(path)
        # NOTE: append (not add_page) carries bookmarks/outline entries along
        writer.append(reader)
        total_pages += len(reader.pages)

    if total_pages == 0:
        raise ConversionError("inputs contain no pages to merge")

    target = _unique_path(out_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        with target.open("wb") as handle:
            writer.write(handle)
    except OSError as exc:
        raise ConversionError(f"cannot write merged PDF: {exc}") from exc
    return target
