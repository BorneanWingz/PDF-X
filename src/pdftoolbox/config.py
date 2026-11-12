"""User configuration kept in config.json beside the executable.

Never raises on load: a missing or corrupt file falls back to defaults so
the tool always starts, even on a locked-down machine.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .paths import config_path

PROMO_MANIFEST_URL = "https://raw.githubusercontent.com/BorneanWingz/PDF-X/main/promo.json"
_PLACEHOLDER_PROMO_URL = "https://example.invalid/pdf-toolbox/promo.json"

DEFAULTS: dict[str, Any] = {
    "version": 1,
    "dpi": 150,
    "ocr_dpi": 200,
    # OCR detection tuning, kept at RapidOCR's own defaults. NOTE: raising
    # ocr_max_side_len above 2000 lets detection see more of a large page, but
    # measured with scripts/ocr_benchmark.py it starts dropping the spaces
    # between words on small text ("solids12.450mgperlitre"), and the table
    # rebuild reads those lines. The knobs are here for documents that need
    # them, not as a shipped speed/quality trade.
    "ocr_max_side_len": 2000,
    "ocr_unclip_ratio": 1.6,
    # same_folder: when True the GUI ignores out_dir and writes beside each
    # input file (convert() interprets out_dir=None that way)
    "same_folder": False,
    # last_dir: folder of the most recently imported file, so the file
    # dialogs reopen where the user last worked instead of at some default
    "last_dir": "",
    # recent_files: the last few documents opened, newest first, shown in the
    # sidebar. Kept short so the list stays a shortcut, not a history viewer.
    "recent_files": [],
    # merge_out_dir: folder chosen on the Merge PDF tab (blank = same folder)
    "merge_out_dir": "",
    # edit_out_dir: folder chosen on the Edit PDF tab (blank = beside the PDF)
    "edit_out_dir": "",
    # edit_same_folder: Edit PDF's "Output in same folder" checkbox (default on,
    # since editing a PDF most often writes the result back beside it)
    "edit_same_folder": True,
    "promo": {
        "enabled": True,
        "url": PROMO_MANIFEST_URL,
        "timeout_seconds": 2.0,
    },
}


def _merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    # NOTE: one-level-deep merge so a user config that only sets "dpi"
    # keeps every other default (e.g. promo settings) without manual upkeep
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def load_config(path: Path | None = None) -> dict[str, Any]:
    # NOTE: never raises - a missing/corrupt config falls back to defaults so
    # the tool always starts, even on a locked-down or read-only machine
    target = path or config_path()
    try:
        raw = target.read_text(encoding="utf-8")
        data = json.loads(raw)
        if not isinstance(data, dict):
            return dict(DEFAULTS)
        config = _merge(DEFAULTS, data)
        promo_config = config.get("promo")
        if (
            isinstance(promo_config, dict)
            and promo_config.get("url") == _PLACEHOLDER_PROMO_URL
        ):
            promo_config["url"] = PROMO_MANIFEST_URL
        return config
    except (OSError, ValueError):
        return dict(DEFAULTS)


def save_config(config: dict[str, Any], path: Path | None = None) -> Path:
    target = path or config_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(config, indent=2), encoding="utf-8")
    return target
