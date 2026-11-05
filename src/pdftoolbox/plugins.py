"""Plugin loader for optional converters stored in the plugins/ folder.

Plugins are plain .py files beside the executable, so a permissive build
can be shipped without them and the AGPL ones enabled later by dropping a
single file in place. A broken plugin is reported, never fatal.

Plugin contract (see plugins/README.md):
    NAME: str
    TARGETS: list[str]                # conversion targets it provides
    def available() -> bool           # optional, default True
    def convert(src: Path, out_dir: Path) -> Path
"""

from __future__ import annotations

import importlib.util
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from .paths import plugins_dir


@dataclass
class PluginInfo:
    """State of one plugin. NOTE: load_error and hint are deliberately
    separate - a malformed plugin is an ERROR (bug), while available()==False
    is merely "unavailable" (missing optional dependency, normal)."""

    name: str
    targets: list[str]
    convert: Callable[[Path, Path], Path] | None = None
    available: bool = False
    load_error: str = ""
    hint: str = ""
    meta: dict = field(default_factory=dict)

    @property
    def status(self) -> str:
        if self.load_error:
            return "error"
        if not self.available:
            return "unavailable"
        return "ready"


def _load_plugin_file(path: Path) -> PluginInfo:
    # NOTE: plugins load from a path at runtime (they sit next to the exe,
    # not on sys.path), so importlib's file-location loader is used here
    module_name = f"pdftoolbox_plugin_{path.stem}"
    try:
        spec = importlib.util.spec_from_file_location(module_name, path)
        if spec is None or spec.loader is None:
            return PluginInfo(path.stem, [], load_error="cannot create import spec")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    except Exception as exc:  # noqa: BLE001 - any plugin failure is contained
        return PluginInfo(path.stem, [], load_error=f"{exc}")

    name = getattr(module, "NAME", path.stem)
    targets = list(getattr(module, "TARGETS", []))
    if not targets or not callable(getattr(module, "convert", None)):
        return PluginInfo(name, targets, load_error="missing TARGETS or convert()")

    try:
        available = bool(module.available()) if callable(
            getattr(module, "available", None)
        ) else True
    except Exception as exc:  # noqa: BLE001
        return PluginInfo(name, targets, load_error=f"available() raised: {exc}")

    if available:
        return PluginInfo(
            name=name,
            targets=targets,
            convert=module.convert,
            available=True,
            meta={"file": path.name, "version": getattr(module, "VERSION", "")},
        )
    return PluginInfo(
        name=name,
        targets=targets,
        convert=module.convert,
        available=False,
        hint=getattr(module, "AVAILABILITY_HINT", "dependencies missing"),
        meta={"file": path.name, "version": getattr(module, "VERSION", "")},
    )


def load_plugins() -> dict[str, PluginInfo]:
    """Scan plugins/ and return name -> PluginInfo."""
    folder = plugins_dir()
    found: dict[str, PluginInfo] = {}
    if not folder.is_dir():
        return found
    for file in sorted(folder.glob("*.py")):
        # NOTE: files starting with "_" are ignored - that convention keeps
        # scratch/disabled plugins in the folder without loading them
        if file.name.startswith("_"):
            continue
        info = _load_plugin_file(file)
        found[info.name] = info
    return found


def plugin_for_target(target: str) -> PluginInfo | None:
    target = target.lower()
    for info in load_plugins().values():
        if target in [t.lower() for t in info.targets]:
            return info
    return None


def plugin_error_summary() -> str:
    lines = []
    for info in load_plugins().values():
        if info.status == "error":
            lines.append(f"{info.name}: {info.load_error}")
    return "; ".join(lines)
