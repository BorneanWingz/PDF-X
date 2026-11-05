"""Filesystem layout helpers.

Everything the toolbox reads or writes lives beside the executable:
config.json, engines/, models/, plugins/, logs/. No registry, no
system directories, no admin rights.
"""

from __future__ import annotations

import sys
from pathlib import Path


def app_dir() -> Path:
    """Directory that holds the app: exe folder when frozen, repo root in dev."""
    # NOTE: sys.frozen is set by PyInstaller; this branch is what keeps the
    # portable promise - config/engines/models live beside the exe
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    # src/pdftoolbox/paths.py -> repo root is three levels up
    return Path(__file__).resolve().parents[2]


def config_path() -> Path:
    return app_dir() / "config.json"


def engines_dir() -> Path:
    return app_dir() / "engines"


def models_dir() -> Path:
    return app_dir() / "models"


def plugins_dir() -> Path:
    return app_dir() / "plugins"


def plugin_lib_dir() -> Path:
    return plugins_dir() / "lib"


def output_dir_for(src: Path, tag: str) -> Path:
    """Default output folder next to the source file."""
    return src.parent / f"{src.stem}_{tag}"
