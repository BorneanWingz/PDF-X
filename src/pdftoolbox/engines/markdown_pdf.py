"""Markdown or plain text to PDF with lightweight formatting.

Handles headings, bullets and code blocks. Uses ReportLab only.
"""

from __future__ import annotations

import re
from pathlib import Path

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

from . import ConversionError

_MARGIN = 18 * mm
_BODY = 10.5
_HEADING1 = 16
_HEADING2 = 13.5
_HEADING3 = 12
_LEADING = _BODY * 1.35

_CANDIDATE_FONTS = [
    Path("C:/Windows/Fonts/arial.ttf"),
    Path("C:/Windows/Fonts/segoeui.ttf"),
]
_MONO_FONTS = [
    Path("C:/Windows/Fonts/consola.ttf"),
    Path("C:/Windows/Fonts/cour.ttf"),
]

_HEADING_RE = re.compile(r"^(#{1,3})\s+(.*)$")
_BULLET_RE = re.compile(r"^\s*[-*+]\s+(.*)$")
_CODE_FENCE_RE = re.compile(r"^```")


def _register(font_paths: list[Path], name: str, fallback: str) -> str:
    for candidate in font_paths:
        if candidate.exists():
            try:
                pdfmetrics.registerFont(TTFont(name, str(candidate)))
                return name
            except Exception:  # noqa: BLE001
                continue
    return fallback


def _draw_wrapped(pdf, text, font, size, x, y, max_width, fill):
    pdf.setFont(font, size)
    pdf.setFillColorRGB(*fill)
    words = text.split(" ")
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if pdfmetrics.stringWidth(candidate, font, size) <= max_width:
            current = candidate
        else:
            if current:
                pdf.drawString(x, y, current)
                y -= size * 1.35
            current = word
    if current:
        pdf.drawString(x, y, current)
        y -= size * 1.35
    return y


def markdown_to_pdf(src: Path, out_path: Path) -> Path:
    try:
        text = src.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        text = src.read_text(encoding="latin-1")
    except OSError as exc:
        raise ConversionError(f"cannot read markdown file: {exc}") from exc

    body_font = _register(_CANDIDATE_FONTS, "ToolboxBody", "Helvetica")
    mono_font = _register(_MONO_FONTS, "ToolboxMono", "Courier")
    usable_width = A4[0] - 2 * _MARGIN

    out_path.parent.mkdir(parents=True, exist_ok=True)
    pdf = canvas.Canvas(str(out_path), pagesize=A4)
    pdf.setTitle(src.stem)
    y = A4[1] - _MARGIN
    in_code = False

    def new_page_if_needed(y_pos: float) -> float:
        if y_pos < _MARGIN:
            pdf.showPage()
            return A4[1] - _MARGIN
        return y_pos

    for raw_line in text.splitlines():
        if _CODE_FENCE_RE.match(raw_line.strip()):
            in_code = not in_code
            y -= _LEADING * 0.4
            continue

        if in_code:
            y = new_page_if_needed(y)
            pdf.setFont(mono_font, _BODY - 1)
            pdf.setFillColorRGB(0.15, 0.15, 0.15)
            pdf.drawString(_MARGIN, y, raw_line[:160])
            y -= (_BODY - 1) * 1.3
            continue

        heading = _HEADING_RE.match(raw_line)
        if heading:
            level = len(heading.group(1))
            size = {1: _HEADING1, 2: _HEADING2, 3: _HEADING3}[level]
            y = new_page_if_needed(y - size)
            y -= size * 0.4
            y = _draw_wrapped(
                pdf, heading.group(2), body_font, size, _MARGIN, y,
                usable_width, (0.08, 0.08, 0.2),
            )
            y -= size * 0.2
            continue

        bullet = _BULLET_RE.match(raw_line)
        if bullet:
            y = new_page_if_needed(y)
            pdf.setFont(body_font, _BODY)
            pdf.setFillColorRGB(0, 0, 0)
            pdf.drawString(_MARGIN, y, "\u2022")
            y = _draw_wrapped(
                pdf, bullet.group(1), body_font, _BODY, _MARGIN + 12, y,
                usable_width - 12, (0, 0, 0),
            )
            continue

        if not raw_line.strip():
            y -= _LEADING * 0.5
            continue

        y = new_page_if_needed(y)
        y = _draw_wrapped(
            pdf, raw_line, body_font, _BODY, _MARGIN, y, usable_width, (0, 0, 0)
        )

    pdf.save()
    return out_path
