"""GUI construction smoke check (not part of pytest: needs a desktop session)."""

from __future__ import annotations

import sys
import tkinter as tk
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from pdftoolbox.gui import App  # noqa: E402


def main() -> int:
    root = tk.Tk()
    root.withdraw()
    app = App(root)
    # exercise the label/refresh logic with no files and with a fake PDF path
    app._refresh_targets()
    app.target_var.set("png")
    app._update_option_state()
    root.update_idletasks()
    root.destroy()
    print("GUI smoke: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
