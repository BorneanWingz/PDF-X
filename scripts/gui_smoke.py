"""GUI construction smoke check (not part of pytest: needs a desktop session)."""

from __future__ import annotations

import sys
import tempfile
import tkinter as tk
from pathlib import Path
from types import SimpleNamespace
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

    # NOTE: the warning popups must not block an automated run, so they are
    # recorded instead of shown
    warnings: list[str] = []
    real_warn = gui_module.messagebox.showwarning
    gui_module.messagebox.showwarning = lambda title, message, **kw: warnings.append(message)

    try:
        _check(root, app, scratch, warnings)
    finally:
        gui_module.save_config = real_save
        gui_module.load_config = real_load
        gui_module.messagebox.showwarning = real_warn
        root.destroy()
    print("GUI smoke: OK")
    return 0


def _reportlab_canvas(path: Path):
    """A one-page ReportLab canvas, for a PDF that really has a text layer."""
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    return canvas.Canvas(str(path), pagesize=A4)


def _check(root: tk.Tk, app: App, scratch: Path, warnings: list[str]) -> None:
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

    # merge now lives on its own tab: the Convert File target list must no
    # longer offer it, and the Merge PDF tab carries numbered files
    from pathlib import Path as _Path

    fake_pdfs = [_Path("a.pdf"), _Path("b.pdf")]
    app.files = list(fake_pdfs)
    app._refresh_targets()
    assert "merge" not in app.target_box["values"], "merge moved off Convert File"
    assert str(app.pages_entry["state"]) == "normal", "pages live for PDF input"

    assert app._pages["merge"] is not None, "merge page present"
    app.merge_files = list(fake_pdfs) + [_Path("notes.docx")]
    app._refresh_merge_list()
    assert app.merge_list.get(0, "end") == (
        "1. a.pdf",
        "2. b.pdf",
        "3. notes.docx",
    ), "merge list is numbered in order"
    assert App.numbered_names([_Path("x.pdf"), _Path("y.png")]) == [
        "1. x.pdf",
        "2. y.png",
    ], "numbering helper"

    # merge Processing Log starts collapsed and takes no space
    assert app.merge_log_open is False, "merge log starts collapsed"
    assert not app.merge_log_frame.winfo_manager(), "no merge log container"
    assert str(app.merge_log_button["text"]).startswith("\u25b8"), "closed marker"
    app._toggle_merge_log()
    root.update_idletasks()
    assert app.merge_log_open is True and app.merge_log_frame.winfo_manager() == "pack"
    app._toggle_merge_log()
    root.update_idletasks()
    assert app.merge_log_open is False
    assert not app.merge_log_frame.winfo_manager(), "collapsed log takes no space"

    # the sidebar drives the navigation, and only one page is shown at a time
    assert sorted(app._sidebar_rows) == ["about", "convert", "edit", "merge"]
    app._show_page("merge")
    root.update_idletasks()
    assert app.current_page == "merge"
    assert app.merge_tab.winfo_manager() == "pack", "merge page is shown"
    assert not app.convert_tab.winfo_manager(), "other pages are hidden"

    # Edit PDF groups secondary operations after the visual editor.
    assert [app.edit_notebook.tab(i, "text") for i in range(3)] == [
        "Organise Pages",
        "Edit Text",
        "PDF Tools",
    ], "edit sub-tabs"
    def button_labels(widget):
        labels = []
        for child in widget.winfo_children():
            if child.winfo_class() in ("TButton", "Button"):
                labels.append(child.cget("text"))
            labels.extend(button_labels(child))
        return labels

    assert "Add Text Box" in button_labels(app.visual_text_tab)
    assert not any("add text" in label.lower() for label in button_labels(app.tools_tab))
    assert {
        "Split PDF", "Extract", "Add Watermark", "Add Numbers", "Find", "Replace All"
    } <= set(button_labels(app.tools_tab))

    # the Edit PDF tab opens on its empty state, showing the drop zone
    app._show_page("edit")
    root.update_idletasks()
    assert app.organise_drop.winfo_manager() == "pack", "drop zone shows when empty"
    assert not app.organise_pages.winfo_manager(), "page list waits for a file"

    root.geometry("1180x800")
    root.deiconify()
    app._show_page("edit")
    app.edit_notebook.select(app.tools_tab)
    root.update()

    def check_visible_buttons(widget):
        for child in widget.winfo_children():
            if child.winfo_class() in ("TButton", "Button"):
                assert child.winfo_ismapped(), child.cget("text")
                assert child.winfo_rootx() >= app.tools_tab.winfo_rootx()
                assert child.winfo_rooty() >= app.tools_tab.winfo_rooty()
                assert child.winfo_rootx() + child.winfo_width() <= (
                    app.tools_tab.winfo_rootx() + app.tools_tab.winfo_width()
                ), child.cget("text")
                assert child.winfo_rooty() + child.winfo_height() <= (
                    app.tools_tab.winfo_rooty() + app.tools_tab.winfo_height()
                ), child.cget("text")
            check_visible_buttons(child)

    check_visible_buttons(app.tools_tab)
    root.withdraw()

    visual_pdf = scratch / "visual-edit.pdf"
    visual = _reportlab_canvas(visual_pdf)
    # NOTE: the text must clear the 20-character threshold that marks a PDF as
    # carrying a text layer, otherwise the OCR reminder would fire
    visual.drawString(72, 720, "Select this line of text")
    visual.save()
    real_open_dialog = gui_module.filedialog.askopenfilenames
    gui_module.filedialog.askopenfilenames = lambda **_kwargs: [str(visual_pdf)]
    try:
        app.open_edit_pdf()
    finally:
        gui_module.filedialog.askopenfilenames = real_open_dialog
    assert app.visual_text_lines, "selectable PDF text should appear in the viewer"
    # a PDF with a text layer needs no OCR reminder
    assert not warnings, "searchable PDF should not warn"
    # the drop zone makes way for the page list once a file is loaded
    assert not app.organise_drop.winfo_manager(), "drop zone hides when loaded"
    assert app.organise_pages.winfo_manager() == "pack", "page list shows"
    line = app.visual_text_lines[0]
    app._select_visual_text(
        SimpleNamespace(x=int(line.x0 + 1), y=int(line.top + 1))
    )
    assert app.visual_text_var.get() == "Select this line of text", "clicked line selected"
    app.visual_text_var.set("Updated line")
    app._queue_visual_text_change()
    assert len(app.visual_text_edits) == 1, "line replacement queued"
    # NOTE: there is no separate save button; the Apply button writes the
    # page changes and the text edits together
    assert app.visual_text_fonts[app._visual_text_key(line)] == app.system_fonts[app.text_font_var.get()]

    app._add_text_box()
    assert len(app.placed_text) == 1
    # NOTE: the on-canvas box is a tk.Text, so it uses text indices rather
    # than the character offsets of an Entry. Typing in it updates the item
    # through the <<Modified>> event, which Tk fires on the next idle cycle.
    app.placed_text_entry.delete("1.0", "end")
    app.placed_text_entry.insert("1.0", "Dragged note")
    app.placed_text_entry.update()
    root.update()
    assert app.placed_text[0].text == "Dragged note", app.placed_text[0].text
    assert app.visual_text_canvas.find_withtag("box-0"), "on-page entry is visible"
    item = app.placed_text[0]
    # NOTE: the click lands in CANVAS pixels, so the item position (in PDF
    # points) is scaled up before it is used
    canvas_scale = app._viewer_scale
    app._visual_text_click(SimpleNamespace(
        x=int(item.x * canvas_scale + 5), y=int(item.top * canvas_scale + 5)
    ))
    app._drag_placed_text(SimpleNamespace(
        x=int(item.x * canvas_scale + 45), y=int(item.top * canvas_scale + 65)
    ))
    app._end_text_drag(None)
    item = app.placed_text[0]
    assert item.x == 60 and item.top == 80, (item.x, item.top)
    assert item.text == "Dragged note", f"text={item.text!r} box={app.placed_text_entry.get('1.0','end-1c')!r} var={app.visual_text_var.get()!r}"
    real_runner = app._run_edit_task_custom
    results = []
    app._run_edit_task_custom = lambda work, _done, _message: results.append(work())
    try:
        # NOTE: the Apply button writes the page changes AND the text edits
        app.run_organise()
    finally:
        app._run_edit_task_custom = real_runner
    from pypdf import PdfReader
    saved = PdfReader(str(results[0])).pages[0].extract_text()
    assert "Updated line" in saved and "Dragged note" in saved
    app._remove_text_box()
    assert not app.placed_text

    # Clear drops the imported file and leaves the tab at its empty state
    assert str(app.edit_clear_button["text"]) == "Clear"
    app.edit_clear_button.invoke()
    assert app.edit_source is None, "Clear drops the imported source"
    assert app.edit_source_var.get() == "No PDF loaded"
    assert not app.edit_pages and not app.visual_text_lines
    assert not hasattr(app, "visual_text_save_button")
    assert str(app.visual_text_next["state"]) == "disabled"

    assert App.page_labels([3, 1, 2], {1: 90, 3: 180}) == [
        "1. Page 3  [rotated 180\u00b0]",
        "2. Page 1  [rotated 90\u00b0 \u21bb]",
        "3. Page 2",
    ], "page label helper"

    # rotation actually mutates state: a left turn lands on 270, a right on 90
    app.edit_source = _Path("fake.pdf")
    app.edit_pages = [1, 2, 3]
    app.edit_rotations = {}
    app._refresh_page_list()
    app.page_list.selection_set(1)  # page 2
    app.rotate_page_cw()
    assert app.edit_rotations == {2: 90}, "right turn applied to page 2"
    app.rotate_page_ccw()
    assert app.edit_rotations.get(2) == 0, "left cancels the right turn back to 0"
    app.rotate_page_ccw()
    assert app.edit_rotations.get(2) == 270, "further left turn reaches 270"
    assert app.page_list.curselection() == (1,), "selection kept after rotating"
    assert "[rotated" in app.page_list.get(1), "label shows the rotation"

    # Edit PDF "Output in same folder" checkbox mirrors the other tabs: ticking
    # it disables the folder field and Browse button
    app.edit_same_folder_var.set(False)
    app._update_edit_output_state()
    assert str(app.edit_out_entry["state"]) == "normal", "edit entry enabled"
    app.edit_same_folder_var.set(True)
    app._update_edit_output_state()
    assert str(app.edit_out_entry["state"]) == "disabled", "edit entry disabled"
    assert str(app.edit_browse_button["state"]) == "disabled", "edit browse disabled"
    assert app.edit_out_folder() is None, "checkbox wins over a stale path"

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

    # ---------- page names and the folded Advanced Options block ----------
    assert sorted(app._pages) == ["about", "convert", "edit", "merge"]
    app._show_page("convert")
    root.update_idletasks()
    assert app.convert_tab.winfo_manager() == "pack", "convert page is shown"

    assert app.advanced_open is False, "advanced block starts closed"
    assert not app.advanced_frame.winfo_manager(), "no container while closed"
    assert "\u25b8" in app.advanced_button["text"], "closed marker shown"

    app._toggle_advanced()
    root.update_idletasks()
    assert app.advanced_open is True, "opens on click"
    assert app.advanced_frame.winfo_manager() == "grid", "container is shown"
    assert app.dpi_var.get() and app.ocr_dpi_var.get(), "DPI fields live there"
    # opening Advanced must not disturb the Pages field's own state (live for
    # PDF input, since merge no longer borrows it)
    assert str(app.pages_entry["state"]) == "normal", "pages state survives toggle"

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
