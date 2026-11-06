"""GUI construction smoke check (not part of pytest: needs a desktop session)."""

from __future__ import annotations

import sys
import tempfile
import tkinter as tk
from pathlib import Path
from tkinterdnd2 import TkinterDnD

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import pdftoolbox.gui as gui_module  # noqa: E402
from pdftoolbox.gui import App  # noqa: E402


class _Stub:
    """Records a modal dialog call and returns a canned answer."""

    def __init__(self, answer):
        self.answer = answer
        self.calls: list[tuple] = []

    def __call__(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return self.answer


def main() -> int:
    root = TkinterDnD.Tk()
    root.withdraw()
    app = App(root)

    # NOTE: a smoke run must not rewrite the developer's own config.json
    scratch = Path(tempfile.mkdtemp())
    real_save = gui_module.save_config
    real_load = gui_module.load_config
    gui_module.save_config = lambda config, path=None: real_save(
        config, scratch / "config.json"
    )
    gui_module.load_config = lambda path=None: real_load(scratch / "config.json")

    try:
        _check(root, app, scratch)
    finally:
        gui_module.save_config = real_save
        gui_module.load_config = real_load
        root.destroy()
    print("GUI smoke: OK")
    return 0


def _reportlab_canvas(path: Path):
    """A one-page ReportLab canvas, for a PDF that really has a text layer."""
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    return canvas.Canvas(str(path), pagesize=A4)


def _check(root: tk.Tk, app: App, scratch: Path) -> None:
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

    # merge target must disable the Pages field (whole-document operation)
    from pathlib import Path as _Path

    fake_pdfs = [_Path("a.pdf"), _Path("b.pdf")]
    app.files = list(fake_pdfs)
    app._refresh_targets()
    assert app.target_var.get() == "PDF (merge all inputs)", "merge should default first"
    assert str(app.pages_entry["state"]) == "disabled", "pages disabled for merge"

    # ---------- window icon (title bar / taskbar) ----------
    # NOTE: PyInstaller's icon= only brands the exe; the Tk window needs this
    # explicitly, and it was silently missing before
    from pdftoolbox.paths import icon_path

    assert icon_path() is not None, "icon file should resolve"
    photos = getattr(app, "_icon_images", [])
    assert photos, "window icon was never applied"
    sizes = {(photo.width(), photo.height()) for photo in photos}
    assert (16, 16) in sizes, "title-bar size missing"
    assert (32, 32) in sizes, "taskbar size missing"

    # ---------- tab name and the folded Advanced Options block ----------
    assert app.notebook.tab(0, "text") == "Convert File", "tab renamed"

    assert app.advanced_open is False, "advanced block starts closed"
    assert not app.advanced_frame.winfo_manager(), "no container while closed"
    assert "\u25b8" in app.advanced_button["text"], "closed marker shown"

    app._toggle_advanced()
    root.update_idletasks()
    assert app.advanced_open is True, "opens on click"
    assert app.advanced_frame.winfo_manager() == "grid", "container is shown"
    assert app.dpi_var.get() and app.ocr_dpi_var.get(), "DPI fields live there"
    assert str(app.pages_entry["state"]) == "disabled", "pages state survives toggle"

    app._toggle_advanced()
    root.update_idletasks()
    assert app.advanced_open is False, "closes again"
    assert not app.advanced_frame.winfo_manager(), "container is removed"
    assert "\u25b8" in app.advanced_button["text"], "closed marker restored"

    # ---------- last known import folder ----------
    sample_dir = scratch / "scans"
    sample_dir.mkdir(parents=True, exist_ok=True)
    sample = sample_dir / "a.pdf"
    sample.write_bytes(b"%PDF-1.4")

    app.files.clear()
    app._add_paths([sample])
    assert app.config["last_dir"] == str(sample_dir), "import folder remembered"
    assert app._dialog_dir() == str(sample_dir), "dialog reopens there"

    # a folder that disappeared must fall back to the OS default
    app.config["last_dir"] = str(scratch / "gone")
    assert app._dialog_dir() is None, "missing folder is not offered"

    # the output picker starts on the remembered folder
    app.config["last_dir"] = str(sample_dir)
    asked: dict = {}
    real_askdirectory = gui_module.filedialog.askdirectory
    gui_module.filedialog.askdirectory = lambda **kwargs: asked.update(kwargs) or ""
    try:
        app.pick_output()
    finally:
        gui_module.filedialog.askdirectory = real_askdirectory
    assert asked.get("initialdir") == str(sample_dir), "browse starts on last folder"

    # ---------- same-folder persistence ----------
    app.same_folder_var.set(True)
    app._toggle_same_folder()
    assert gui_module.load_config()["same_folder"] is True, "checkbox persisted"

    # ---------- OCR-first notice ----------
    from PIL import Image

    text_pdf = scratch / "digital.pdf"
    canvas = _reportlab_canvas(text_pdf)
    canvas.drawString(72, 720, "Hello PDF Toolbox")
    canvas.drawString(72, 700, "Second line of text")
    canvas.showPage()
    canvas.save()

    scan = scratch / "scan.pdf"
    Image.new("RGB", (600, 200), "white").save(scan, "PDF", resolution=150)

    assert App._ocr_first_needed([text_pdf], "txt") is False, "no OCR when searchable"
    assert App._ocr_first_needed([scan], "txt") is True, "scan triggers the notice"
    assert App._ocr_first_needed([scan], "html") is True, "html reads the text layer"
    assert App._ocr_first_needed([scan], "png") is False, "rendering needs no OCR"
    assert App._ocr_first_needed([sample], "txt") is False, "only PDF inputs count"

    # ---------- prompt when no destination was chosen ----------
    app.out_var.set(str(sample_dir))
    app.same_folder_var.set(False)
    assert app._confirm_output_folder() is True, "chosen folder needs no prompt"

    app.out_var.set("")
    app.same_folder_var.set(True)
    assert app._confirm_output_folder() is True, "same-folder needs no prompt"

    real_ask = gui_module.messagebox.askyesnocancel
    try:
        app.same_folder_var.set(False)
        app.out_var.set("")
        cancel = _Stub(None)
        gui_module.messagebox.askyesnocancel = cancel
        assert app._confirm_output_folder() is False, "cancel must stop the run"
        assert cancel.calls, "the user must be asked"

        app.same_folder_var.set(False)
        app.out_var.set("")
        yes = _Stub(True)
        gui_module.messagebox.askyesnocancel = yes
        assert app._confirm_output_folder() is True, "yes means same folder"
        assert app.same_folder_var.get() is True, "yes ticks the checkbox"

        app.same_folder_var.set(False)
        app.out_var.set("")
        no = _Stub(False)
        gui_module.messagebox.askyesnocancel = no
        gui_module.filedialog.askdirectory = _Stub("")
        assert app._confirm_output_folder() is False, "no folder picked: stop"
        app.out_var.set(str(sample_dir))
        assert app._confirm_output_folder() is True, "picked folder is enough"
    finally:
        gui_module.messagebox.askyesnocancel = real_ask
        gui_module.filedialog.askdirectory = real_askdirectory

    root.update_idletasks()


if __name__ == "__main__":
    raise SystemExit(main())
