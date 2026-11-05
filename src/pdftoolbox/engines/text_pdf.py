"""Plain text to PDF using ReportLab (BSD)."""

from __future__ import annotations

from pathlib import Path

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

from . import ConversionError

_CANDIDATE_FONTS = [
    Path("C:/Windows/Fonts/arial.ttf"),
    Path("C:/Windows/Fonts/segoeui.ttf"),
    Path("C:/Windows/Fonts/calibri.ttf"),
]

_FONT_NAME = "Helvetica"
_FONT_SIZE = 10.5
_LEADING = _FONT_SIZE * 1.35
_MARGIN = 18 * mm
_MAX_CHARS = 120


def _register_unicode_font() -> None:
    global _FONT_NAME
    for candidate in _CANDIDATE_FONTS:
        if candidate.exists():
            try:
                pdfmetrics.registerFont(TTFont("ToolboxFont", str(candidate)))
                _FONT_NAME = "ToolboxFont"
                return
            except Exception:  # noqa: BLE001 - fall back to the next candidate
                continue


def _wrap(text: str, font: str, size: float, max_width: float) -> list[str]:
    lines: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        if not line:
            lines.append("")
            continue
        current = ""
        for word in line.split(" "):
            candidate = f"{current} {word}".strip()
            if pdfmetrics.stringWidth(candidate, font, size) <= max_width:
                current = candidate
            else:
                if current:
                    lines.append(current)
                while pdfmetrics.stringWidth(word, font, size) > max_width:
                    cut = len(word)
                    while cut > 1 and pdfmetrics.stringWidth(
                        word[:cut], font, size
                    ) > max_width:
                        cut -= 1
                    lines.append(word[:cut])
                    word = word[cut:]
                current = word
        lines.append(current)
    return lines


def text_to_pdf(src: Path, out_path: Path) -> Path:
    try:
        text = src.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        text = src.read_text(encoding="latin-1")
    except OSError as exc:
        raise ConversionError(f"cannot read text file: {exc}") from exc

    _register_unicode_font()
    usable_width = A4[0] - 2 * _MARGIN
    lines = _wrap(text, _FONT_NAME, _FONT_SIZE, usable_width)
    if len(lines) > _MAX_CHARS * 200:
        raise ConversionError("text file is too large to convert (over ~40k lines)")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    pdf = canvas.Canvas(str(out_path), pagesize=A4)
    pdf.setTitle(src.stem)
    pdf.setFont(_FONT_NAME, _FONT_SIZE)
    y = A4[1] - _MARGIN
    for line in lines:
        if y < _MARGIN:
            pdf.showPage()
            pdf.setFont(_FONT_NAME, _FONT_SIZE)
            y = A4[1] - _MARGIN
        pdf.drawString(_MARGIN, y, line)
        y -= _LEADING
    pdf.save()
    return out_path
