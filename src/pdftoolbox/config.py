"""User configuration kept in config.json beside the executable.

Never raises on load: a missing or corrupt file falls back to defaults so
the tool always starts, even on a locked-down machine.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .paths import config_path

DEFAULTS: dict[str, Any] = {
    "version": 1,
    "dpi": 150,
    "ocr_dpi": 200,
    # same_folder: when True the GUI ignores out_dir and writes beside each
    # input file (convert() interprets out_dir=None that way)
    "same_folder": False,
    "promo": {
        "enabled": True,
        "url": "https://example.invalid/pdf-toolbox/promo.json",
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
        return _merge(DEFAULTS, data)
    except (OSError, ValueError):
        return dict(DEFAULTS)


def save_config(config: dict[str, Any], path: Path | None = None) -> Path:
    target = path or config_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(config, indent=2), encoding="utf-8")
    return target
