"""Command line interface for PDF Toolbox."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__, plugins
from .convert import (
    convert,
    convert_many,
    is_merge_target,
    list_targets,
    merge_pdfs,
    parse_pages,
)
from .engines import ConversionError, EngineUnavailable
from .engines import office
from .paths import config_path, plugins_dir


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pdftoolbox",
        description="Portable offline PDF converter and OCR toolbox.",
    )
    parser.add_argument("files", nargs="*", type=Path, help="input files")
    parser.add_argument(
        "--to",
        metavar="TARGET",
        help="conversion target: png, jpg, tif, txt, html, xlsx, pptx, "
        "searchable-pdf, docx, pdf, or merge (combine two or more PDFs)",
    )
    parser.add_argument(
        "--out",
        type=Path,
        help="output folder (default: beside input); for merge, a .pdf path "
        "names the exact merged file instead",
    )
    parser.add_argument("--dpi", type=int, help="render DPI for images and PPTX (default 150)")
    parser.add_argument("--ocr-dpi", type=int, help="render DPI for OCR (default 200)")
    parser.add_argument("--pages", help="page selection, e.g. 1-3,5 (PDF only)")
    parser.add_argument("--gui", action="store_true", help="open the graphical interface")
    parser.add_argument("--list-targets", action="store_true", help="show targets for the inputs")
    parser.add_argument("--doctor", action="store_true", help="check engines and plugins")
    parser.add_argument("--version", action="version", version=f"PDF Toolbox {__version__}")
    return parser


def _cmd_doctor() -> int:
    print(f"PDF Toolbox {__version__}")
    print(f"config:  {config_path()}")
    print(f"plugins: {plugins_dir()}")
    print()

    print("[core] permissive components")
    for label, module_name in [
        ("pypdfium2 (PDF render)", "pypdfium2"),
        ("pypdf (text)", "pypdf"),
        ("pdfplumber (tables)", "pdfplumber"),
        ("Pillow (images)", "PIL"),
        ("python-pptx", "pptx"),
        ("openpyxl", "openpyxl"),
        ("reportlab", "reportlab"),
    ]:
        try:
            __import__(module_name)
            print(f"  ok       {label}")
        except ImportError as exc:
            print(f"  MISSING  {label} ({exc})")

    print()
    print("[ocr] RapidOCR (offline)")
    try:
        import rapidocr_onnxruntime  # noqa: F401

        print("  ok       rapidocr-onnxruntime")
    except ImportError as exc:
        print(f"  MISSING  rapidocr-onnxruntime ({exc})")

    print()
    print("[engine] LibreOffice (office -> PDF, MPL-2.0)")
    soffice = office.find_soffice()
    if soffice:
        print(f"  ok       {soffice}")
    else:
        print("  MISSING  run scripts/download-engines.ps1 or set SOFFICE_PATH")

    print()
    print("[plugins] optional converters")
    found = plugins.load_plugins()
    if not found:
        print("  none installed (this is fine for a clean build)")
    for info in found.values():
        mark = {"ready": "ok      ", "unavailable": "disabled", "error": "ERROR   "}[
            info.status
        ]
        detail = ""
        if info.status == "error":
            detail = f" - {info.load_error}"
        elif info.status == "unavailable" and info.hint:
            detail = f" - {info.hint}"
        print(f"  {mark} {info.name} -> {', '.join(info.targets)}{detail}")
    return 0


def _cmd_list_targets(files: list[Path]) -> int:
    # NOTE: merge appears in the listing only when the selection has 2+ PDFs
    pdf_count = sum(1 for path in files if path.suffix.lower() == ".pdf")
    for src in files:
        print(f"{src.name}:")
        options = list_targets(src, pdf_count)
        if not options:
            print("  (no conversions available for this file type)")
            continue
        for option in options:
            state = "ok" if option.available else "unavailable"
            note = f"  [{option.note}]" if option.note else ""
            print(f"  {option.key:<16} {state}{note}")
    return 0


def _cmd_convert(args) -> int:
    # NOTE: exit codes are part of the CLI contract used by scripts:
    #   0 = all files converted, 1 = one or more failed, 2 = usage error
    if not args.files:
        print("error: no input files given (use --gui for the interface)", file=sys.stderr)
        return 2
    if not args.to:
        print("error: --to TARGET is required", file=sys.stderr)
        return 2
    try:
        pages = parse_pages(args.pages)
    except ValueError as exc:
        print(f"error: bad --pages value: {exc}", file=sys.stderr)
        return 2

    missing = [str(path) for path in args.files if not path.is_file()]
    if missing:
        print(f"error: input not found: {', '.join(missing)}", file=sys.stderr)
        return 2

    if is_merge_target(args.to):
        # NOTE: merge is one operation over MANY files, so it bypasses the
        # per-file loop below; --out is either the exact .pdf target or the
        # folder, depending on its suffix
        pdf_inputs = [
            path.resolve() for path in args.files if path.suffix.lower() == ".pdf"
        ]
        out_path = None
        out_dir = None
        if args.out is not None:
            if args.out.suffix.lower() == ".pdf":
                out_path = args.out
            else:
                out_dir = args.out
        try:
            result = merge_pdfs(pdf_inputs, out_path=out_path, out_dir=out_dir)
        except (ConversionError, EngineUnavailable) as exc:
            print(f"FAILED  merge: {exc}", file=sys.stderr)
            return 1
        print(f"ok      merged {len(pdf_inputs)} PDF(s) -> {result}")
        return 0

    results = convert_many(
        [path.resolve() for path in args.files],
        args.to,
        out_dir=args.out,
        dpi=args.dpi,
        ocr_dpi=args.ocr_dpi,
        pages=pages,
    )
    failures = 0
    for src, outcome in results:
        if isinstance(outcome, str):
            failures += 1
            print(f"FAILED  {src.name}: {outcome}")
        else:
            for path in outcome:
                print(f"ok      {src.name} -> {path}")
    if failures:
        print(f"{failures} of {len(results)} file(s) failed", file=sys.stderr)
    return 1 if failures else 0


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)

    if args.gui or (
        not args.files
        and not args.doctor
        # NOTE: --list-targets without files must print an ERROR, not open
        # the GUI - forgetting this check once made the CLI hang in tests
        and not args.list_targets
    ):
        from .gui import run_gui

        return run_gui()

    if args.doctor:
        return _cmd_doctor()

    if args.list_targets:
        if not args.files:
            print("error: --list-targets needs input files", file=sys.stderr)
            return 2
        return _cmd_list_targets([path.resolve() for path in args.files])

    try:
        return _cmd_convert(args)
    except (ConversionError, EngineUnavailable) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
