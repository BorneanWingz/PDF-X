"""Unified conversion facade used by both the CLI and the GUI."""

from __future__ import annotations

import inspect
import tempfile
from dataclasses import dataclass
from pathlib import Path

from . import plugins
from .config import load_config
from .engines import ConversionError, EngineUnavailable
from .engines import images_pdf, markdown_pdf, office, pdf_merge, pdf_pptx, pdf_render
from .engines import pdf_tables, pdf_text, searchable_pdf, text_pdf
from .engines import ocr as ocr_engine

PDF_TARGETS = ["png", "jpg", "tif", "txt", "html", "xlsx", "pptx", "searchable-pdf", "docx"]
TO_PDF_IMAGE_TARGET = "pdf"
MERGE_TARGET = "merge"
# Targets whose engines read the PDF text layer instead of rendering the page
# as a picture. A scanned input is OCR'd first so these engines have something
# to read - see _convert_from_pdf().
# NOTE: png/jpg/tif/searchable-pdf are excluded on purpose: they either render
# the page pixels or already run OCR themselves.
OCR_FIRST_TARGETS = {"txt", "html", "xlsx", "pptx", "docx"}
_ALIASES = {
    "jpeg": "jpg",
    "tiff": "tif",
    "xls": "xlsx",
    "ppt": "pptx",
    "searchable": "searchable-pdf",
    "ocr": "searchable-pdf",
    "ocr-pdf": "searchable-pdf",
    "markdown": "md",
    # merging is an operation over MULTIPLE inputs, not a file conversion;
    # these aliases all mean "combine the listed PDFs into one"
    "combine": "merge",
    "concat": "merge",
    "merge-pdf": "merge",
}


@dataclass
class TargetOption:
    key: str
    label: str
    available: bool
    note: str = ""


def normalize_target(target: str) -> str:
    key = target.strip().lower().lstrip(".")
    return _ALIASES.get(key, key)


def is_merge_target(target: str) -> bool:
    """True for merge/combine requests (an operation over several PDFs)."""
    return normalize_target(target) == MERGE_TARGET


def merge_pdfs(
    sources: list[Path],
    out_path: Path | None = None,
    out_dir: Path | None = None,
) -> Path:
    """Merge the PDF inputs into one file, in the given order.

    NOTE: out_path names the exact target file (CLI --out x.pdf) and wins
    over out_dir; with neither, "<first_stem>_merged.pdf" lands beside the
    first input. Non-PDF inputs are ignored - the GUI passes the whole list.
    """
    pdfs = [
        Path(src).resolve()
        for src in sources
        if Path(src).suffix.lower() == ".pdf"
    ]
    if len(pdfs) < 2:
        raise ConversionError("merging needs at least two PDF files")
    if out_path is None:
        folder = Path(out_dir) if out_dir else pdfs[0].parent
        out_path = folder / f"{pdfs[0].stem}_merged.pdf"
    return pdf_merge.merge_pdf_files(pdfs, Path(out_path))


def _plugin_targets() -> dict[str, plugins.PluginInfo]:
    mapping: dict[str, plugins.PluginInfo] = {}
    for info in plugins.load_plugins().values():
        for target in info.targets:
            mapping.setdefault(normalize_target(target), info)
    return mapping


def _plugin_kwargs(convert_fn, pages: list[int] | None, ocr_layer: bool) -> dict:
    """Keyword arguments a plugin's ``convert()`` understands.

    NOTE: page selection and the OCR-layer flag joined the plugin contract
    later, so older plugins declaring ``convert(src, out_dir)`` keep working.
    """
    try:
        parameters = inspect.signature(convert_fn).parameters
    except (TypeError, ValueError):
        return {}
    kwargs: dict = {}
    if pages and "pages" in parameters:
        kwargs["pages"] = pages
    if ocr_layer and "ocr_layer" in parameters:
        kwargs["ocr_layer"] = True
    return kwargs


def list_targets(src: Path, pdf_inputs: int = 0) -> list[TargetOption]:
    """Targets offered for one input file, with availability notes.

    NOTE: pdf_inputs is the number of PDFs in the whole selection; merging
    only makes sense with two or more, which is why it is a parameter and
    not derived from src alone.
    """
    suffix = src.suffix.lower()
    plugin_map = _plugin_targets()

    if suffix == ".pdf":
        options: list[TargetOption] = []
        if pdf_inputs >= 2:
            # listed first so a multi-PDF selection defaults to merging
            options.append(TargetOption(MERGE_TARGET, "PDF (merge all inputs)", True))
        options.extend(
            TargetOption(key, key.upper(), True)
            for key in ["png", "jpg", "tif", "txt", "html", "xlsx", "pptx", "searchable-pdf"]
        )
        if "docx" in plugin_map:
            info = plugin_map["docx"]
            note = "AGPL plugin."
            if info.hint:
                note += " " + info.hint
            options.append(
                TargetOption("docx", "DOCX", info.available, note.strip())
            )
        else:
            options.append(
                TargetOption(
                    "docx",
                    "DOCX",
                    False,
                    "plugin not installed (see plugins/README.md)",
                )
            )
        return options

    if images_pdf.is_image(src):
        return [TargetOption(TO_PDF_IMAGE_TARGET, "PDF", True)]

    if suffix in {".md", ".markdown"}:
        return [TargetOption("pdf", "PDF (formatted)", True)]

    if suffix == ".txt":
        return [TargetOption("pdf", "PDF (plain text)", True)]

    if office.is_office_document(src):
        available = office.is_available()
        note = "" if available else "LibreOffice engine not installed"
        return [TargetOption("pdf", "PDF", available, note)]

    return []


def parse_pages(spec: str | None) -> list[int] | None:
    """Parse '1-3,5' into [1, 2, 3, 5]."""
    if not spec:
        return None
    pages: list[int] = []
    for chunk in spec.split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        if "-" in chunk:
            start_text, _, end_text = chunk.partition("-")
            start, end = int(start_text), int(end_text)
            if end < start:
                raise ValueError(f"bad page range: {chunk}")
            pages.extend(range(start, end + 1))
        else:
            pages.append(int(chunk))
    return sorted(set(pages)) or None


def convert(
    src: Path,
    target: str,
    out_dir: Path | None = None,
    dpi: int | None = None,
    ocr_dpi: int | None = None,
    pages: list[int] | None = None,
    on_progress=None,
) -> list[Path]:
    """Convert one file. Returns the list of created files."""
    src = Path(src).resolve()
    if not src.is_file():
        raise ConversionError(f"input file not found: {src}")
    key = normalize_target(target)
    if key == MERGE_TARGET:
        # NOTE: merging needs the whole input set at once, so the single-file
        # convert() path rejects it - callers use merge_pdfs() instead
        raise ConversionError(
            "merging combines several PDFs at once; use merge_pdfs() with all "
            "inputs (CLI: pass every file with --to merge)"
        )
    config = load_config()
    dpi = dpi or int(config.get("dpi", 150))
    ocr_dpi = ocr_dpi or int(config.get("ocr_dpi", 200))

    if src.suffix.lower() == ".pdf":
        return _convert_from_pdf(src, key, out_dir, dpi, ocr_dpi, pages, on_progress)

    if key != "pdf":
        raise ConversionError(
            f"target '{key}' is only supported for PDF inputs; "
            f"{src.name} can only be converted to PDF"
        )
    return _convert_to_pdf(src, out_dir)


def _searchable_copy(
    src: Path,
    scratch: Path,
    ocr_dpi: int,
    pages: list[int] | None,
    on_progress,
) -> tuple[Path, list]:
    """OCR ``src`` into a searchable PDF inside ``scratch``.

    Returns ``(staged_pdf, ocr_pages)``.

    NOTE: the copy is a throwaway: it only gives the text-reading engines a
    layer to work with, and it is deleted with its temp folder as soon as the
    conversion finishes - never written next to the user's files. The OCR pages
    come back too because the spreadsheet writer rebuilds scanned tables from
    those boxes (the text layer alone has no cell geometry).
    """
    ocr_pages = ocr_engine.ocr_pdf(
        src, dpi=ocr_dpi, pages=pages, on_progress=on_progress
    )
    # NOTE: keep the original stem so every output name stays identical to the
    # no-OCR path (a "scanned_searchable.txt" would surprise the user)
    staged = scratch / f"{src.stem}.pdf"
    return searchable_pdf.make_searchable_pdf(src, staged, ocr_pages, ocr_dpi), ocr_pages


def _convert_from_pdf(
    src: Path,
    key: str,
    out_dir: Path | None,
    dpi: int,
    ocr_dpi: int,
    pages: list[int] | None,
    on_progress,
) -> list[Path]:
    # NOTE: with no output folder the results are written straight beside the
    # source file - no "<name>_output" subfolder is created, because scattering
    # one folder per converted file is exactly what users asked to avoid
    tag_dir = out_dir if out_dir is not None else src.parent

    if key in OCR_FIRST_TARGETS and not pdf_text.has_text_layer(src):
        # NOTE: a pure scan has no text layer, so txt/html/xlsx/pptx/docx would
        # come out empty (or fail with "no tables"). OCR runs first and the
        # searchable copy stands in for the original.
        with tempfile.TemporaryDirectory(prefix="pdftoolbox-ocr-") as scratch:
            staged, ocr_pages = _searchable_copy(
                src, Path(scratch), ocr_dpi, pages, on_progress
            )
            # NOTE: the copy already holds ONLY the selected pages, so the page
            # filter must not be applied to it a second time (it would be out
            # of range as soon as a subset was requested)
            return _dispatch_from_pdf(
                staged,
                key,
                tag_dir,
                dpi,
                ocr_dpi,
                None,
                on_progress,
                ocr_layer=True,
                ocr_pages=ocr_pages,
            )

    return _dispatch_from_pdf(src, key, tag_dir, dpi, ocr_dpi, pages, on_progress)


def _dispatch_from_pdf(
    src: Path,
    key: str,
    tag_dir: Path,
    dpi: int,
    ocr_dpi: int,
    pages: list[int] | None,
    on_progress,
    ocr_layer: bool = False,
    ocr_pages: list | None = None,
) -> list[Path]:
    if key in {"png", "jpg", "tif"}:
        return pdf_render.pdf_to_images(src, tag_dir, fmt=key, dpi=dpi, pages=pages)

    if key == "txt":
        return [pdf_text.pdf_to_text(src, tag_dir / f"{src.stem}.txt")]

    if key == "html":
        return [pdf_text.pdf_to_html(src, tag_dir / f"{src.stem}.html")]

    if key == "xlsx":
        path, _ = pdf_tables.pdf_to_xlsx(
            src, tag_dir / f"{src.stem}.xlsx", ocr_pages=ocr_pages
        )
        return [path]

    if key == "pptx":
        return [
            pdf_pptx.pdf_to_pptx(
                src, tag_dir / f"{src.stem}.pptx", dpi=dpi, pages=pages
            )
        ]

    if key == "searchable-pdf":
        ocr_pages = ocr_engine.ocr_pdf(
            src, dpi=ocr_dpi, pages=pages, on_progress=on_progress
        )
        out_path = tag_dir / f"{src.stem}_searchable.pdf"
        return [searchable_pdf.make_searchable_pdf(src, out_path, ocr_pages, ocr_dpi)]

    # any target provided by an optional plugin (e.g. docx via pdf2docx).
    # NOTE: unavailable plugins raise EngineUnavailable so callers can explain
    # which component is missing instead of failing silently.
    plugin_info = _plugin_targets().get(key)
    if plugin_info is not None:
        if not plugin_info.available or plugin_info.convert is None:
            detail = plugin_info.load_error or plugin_info.hint or "dependencies missing"
            raise EngineUnavailable(
                f"plugin '{plugin_info.name}' is unavailable: {detail}"
            )
        kwargs = _plugin_kwargs(plugin_info.convert, pages, ocr_layer)
        return [plugin_info.convert(src, tag_dir, **kwargs)]

    raise ConversionError(f"unsupported target for PDF input: {key}")


def _convert_to_pdf(src: Path, out_dir: Path | None) -> list[Path]:
    suffix = src.suffix.lower()
    # NOTE: same rule as _convert_from_pdf - no "<name>_output" subfolder, the
    # result simply lands beside the input
    tag_dir = out_dir if out_dir is not None else src.parent
    tag_dir.mkdir(parents=True, exist_ok=True)

    if images_pdf.is_image(src):
        return [images_pdf.images_to_pdf([src], tag_dir / f"{src.stem}.pdf")]

    if suffix in {".md", ".markdown"}:
        return [markdown_pdf.markdown_to_pdf(src, tag_dir / f"{src.stem}.pdf")]

    if suffix == ".txt":
        return [text_pdf.text_to_pdf(src, tag_dir / f"{src.stem}.pdf")]

    if office.is_office_document(src):
        return [office.office_to_pdf(src, tag_dir)]

    raise ConversionError(f"cannot convert {src.name} to PDF (unsupported type)")


def convert_many(
    sources: list[Path],
    target: str,
    out_dir: Path | None = None,
    dpi: int | None = None,
    ocr_dpi: int | None = None,
    pages: list[int] | None = None,
    on_progress=None,
) -> list[tuple[Path, "list[Path] | str"]]:
    """Convert several files; returns (source, outputs-or-error) pairs."""
    # NOTE: per-file errors become strings instead of exceptions - one bad
    # file must not abort a whole batch (the GUI renders them as FAILED lines).
    # The catch is deliberately Exception-wide: a library bug such as openpyxl's
    # IllegalCharacterError, raised while writing one spreadsheet, previously
    # escaped here and killed every remaining file in the selection.
    results: list[tuple[Path, list[Path] | str]] = []
    for src in sources:
        try:
            outputs = convert(src, target, out_dir, dpi, ocr_dpi, pages, on_progress)
            results.append((src, outputs))
        except (ConversionError, EngineUnavailable, ValueError) as exc:
            results.append((src, str(exc)))
        except Exception as exc:  # noqa: BLE001 - never lose the rest of the batch
            results.append((src, f"{type(exc).__name__}: {exc}"))
    return results

