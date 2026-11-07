"""Discover embeddable Windows fonts and match PDF font names."""

from __future__ import annotations

import difflib
import os
import re
import struct
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class FontFace:
    path: Path
    index: int = 0


def installed_fonts() -> dict[str, FontFace]:
    """Return installed TrueType and OpenType faces from the Windows registry."""
    if sys.platform != "win32":
        return {}
    import winreg

    from PIL import ImageFont

    fonts: dict[str, FontFace] = {}
    collections: set[Path] = set()
    roots = (
        (winreg.HKEY_LOCAL_MACHINE, Path(os.environ["WINDIR"]) / "Fonts"),
        (winreg.HKEY_CURRENT_USER, Path(os.environ["LOCALAPPDATA"]) / "Microsoft" / "Windows" / "Fonts"),
    )
    for hive, directory in roots:
        try:
            key = winreg.OpenKey(hive, r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Fonts")
        except FileNotFoundError:
            continue
        with key:
            for index in range(winreg.QueryInfoKey(key)[1]):
                name, value, _ = winreg.EnumValue(key, index)
                if not isinstance(value, str):
                    continue
                path = Path(os.path.expandvars(value))
                if not path.is_absolute():
                    path = directory / path
                if path.suffix.lower() not in {".ttf", ".ttc", ".otf"} or not path.is_file():
                    continue
                if path.suffix.lower() == ".ttc":
                    if path in collections:
                        continue
                    collections.add(path)
                    with path.open("rb") as handle:
                        header = handle.read(12)
                    if len(header) != 12 or header[:4] != b"ttcf":
                        continue
                    count = struct.unpack(">I", header[8:12])[0]
                    for face_index in range(count):
                        try:
                            family, style = ImageFont.truetype(str(path), 12, index=face_index).getname()
                        except OSError:
                            continue
                        label = family if style.casefold() == "regular" else f"{family} {style}"
                        fonts[label] = FontFace(path, face_index)
                else:
                    label = re.sub(r"\s*\((?:TrueType|OpenType)\)$", "", name, flags=re.IGNORECASE)
                    fonts[label] = FontFace(path)
    return dict(sorted(fonts.items(), key=lambda item: item[0].casefold()))


def _normalized(name: str) -> str:
    name = re.sub(r"^[A-Z]{6}\+", "", name)
    return re.sub(r"[^a-z0-9]", "", name.casefold()).replace("regular", "")


def suggest_font(name: str, fonts: dict[str, FontFace]) -> tuple[str | None, bool]:
    """Return the closest installed face and whether it is an exact name match."""
    if not name or not fonts:
        return None, False
    wanted = _normalized(name)
    normalized = {_normalized(label): label for label in fonts}
    if wanted in normalized:
        return normalized[wanted], True
    aliases = {
        "helvetica": "arial",
        "helveticabold": "arialbold",
        "helveticaoblique": "arialitalic",
        "helveticaboldoblique": "arialbolditalic",
        "timesroman": "timesnewroman",
        "timesbold": "timesnewromanbold",
        "timesitalic": "timesnewromanitalic",
        "timesbolditalic": "timesnewromanbolditalic",
        "courier": "couriernew",
    }
    if aliases.get(wanted) in normalized:
        return normalized[aliases[wanted]], False
    closest = difflib.get_close_matches(wanted, list(normalized), n=1, cutoff=0.5)
    return (normalized[closest[0]], False) if closest else (None, False)
