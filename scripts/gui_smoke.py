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

    # targets/labels with no files and with a selected target
    app._refresh_targets()
    app.target_var.set("png")
    app._update_option_state()
    root.update_idletasks()

    # "Output in same folder" checkbox must disable field + Browse when ticked
    app.same_folder_var.set(False)
    app._update_output_state()
    assert str(app.out_entry["state"]) == "normal", "entry should be enabled"
    assert str(app.browse_button["state"]) == "normal", "browse should be enabled"

    app.same_folder_var.set(True)
    app._update_output_state()
    assert str(app.out_entry["state"]) == "disabled", "entry should be disabled"
    assert str(app.browse_button["state"]) == "disabled", "browse should be disabled"

    root.update_idletasks()
    root.destroy()
    print("GUI smoke: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
