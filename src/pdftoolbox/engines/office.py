"""Office document conversion via a bundled LibreOffice (MPL-2.0).

Resolves the soffice binary from engines/libreoffice next to the app, or
from the SOFFICE_PATH environment variable / PATH. Runs fully headless,
with the user profile stored beside the app so nothing touches the system.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

from ..paths import engines_dir
from . import ConversionError, EngineUnavailable

_SOFFICE_NAMES = ("soffice.exe", "soffice")
_OFFICE_SUFFIXES = {
    ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
    ".odt", ".ods", ".odp", ".rtf", ".csv", ".txt",
}
_MODERN_FORMATS = {
    ".doc": "docx",
    ".docx": "docx",
    ".odt": "docx",
    ".rtf": "docx",
    ".xls": "xlsx",
    ".xlsx": "xlsx",
    ".ods": "xlsx",
    ".csv": "xlsx",
    ".ppt": "pptx",
    ".pptx": "pptx",
    ".odp": "pptx",
}
_TIMEOUT_SECONDS = 300


def find_soffice() -> Path | None:
    env = os.environ.get("SOFFICE_PATH")
    if env:
        candidate = Path(env)
        if candidate.is_file():
            return candidate
    bundled_root = engines_dir() / "libreoffice"
    if bundled_root.is_dir():
        for pattern in (
            "program/soffice.exe",
            "LibreOfficePortable/App/libreoffice/program/soffice.exe",
            "**/soffice.exe",
        ):
            for candidate in bundled_root.glob(pattern):
                return candidate
    on_path = shutil.which("soffice")
    if on_path:
        return Path(on_path)
    if sys.platform == "darwin":
        mac = Path("/Applications/LibreOffice.app/Contents/MacOS/soffice")
        if mac.is_file():
            return mac
    return None


def is_available() -> bool:
    return find_soffice() is not None


def is_office_document(path: Path) -> bool:
    return path.suffix.lower() in _OFFICE_SUFFIXES


def modern_office_format(path: Path) -> str | None:
    """Modern Office output format for this document's family, if supported."""
    return _MODERN_FORMATS.get(path.suffix.lower())


def office_to_pdf(src: Path, out_dir: Path) -> Path:
    return _office_convert(src, "pdf", out_dir)


def office_to_format(src: Path, target: str, out_dir: Path) -> Path:
    if target != modern_office_format(src):
        raise ConversionError(
            f"cannot convert {src.name} directly to {target.upper()}"
        )
    return _office_convert(src, target, out_dir)


def _office_convert(src: Path, target: str, out_dir: Path) -> Path:
    soffice = find_soffice()
    if soffice is None:
        raise EngineUnavailable(
            "LibreOffice engine not found. Run scripts/download-engines.ps1 "
            "or set SOFFICE_PATH. Office documents need this engine."
        )
    out_dir.mkdir(parents=True, exist_ok=True)
    profile = engines_dir() / "lo-profile"
    profile.mkdir(parents=True, exist_ok=True)

    cmd = [
        str(soffice),
        # NOTE: a private user profile beside the app keeps LibreOffice from
        # writing to %APPDATA% and colliding with an installed LibreOffice
        f"-env:UserInstallation={profile.resolve().as_uri()}",
        "--headless",
        "--norestore",
        "--convert-to",
        target,
        "--outdir",
        str(out_dir),
        str(src),
    ]
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=_TIMEOUT_SECONDS,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise ConversionError(
            f"LibreOffice timed out after {_TIMEOUT_SECONDS}s on {src.name}"
        ) from exc

    # NOTE: check the output file FIRST - soffice can exit 0 without
    # producing a PDF (e.g. locked profile), so return code alone lies
    expected = out_dir / f"{src.stem}.{target}"
    if expected.exists():
        return expected
    if result.returncode != 0:
        tail = (result.stderr or result.stdout or "").strip()[-400:]
        raise ConversionError(f"LibreOffice failed on {src.name}: {tail}")
    raise ConversionError(
        f"LibreOffice produced no {target.upper()} file for {src.name}"
    )
