"""GUI rules that need no display (pure helpers from pdftoolbox.gui).

NOTE: importing pdftoolbox.gui pulls in tkinter but creates no Tk root, so
these tests run anywhere; the interactive checks live in scripts/gui_smoke.py.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

tk = pytest.importorskip("tkinter")

from pdftoolbox.gui import App  # noqa: E402
from pdftoolbox.gui import output_undecided  # noqa: E402
from pdftoolbox import gui as gui_module  # noqa: E402
from pdftoolbox.engines import pdf_edit  # noqa: E402
from pdftoolbox.system_fonts import FontFace  # noqa: E402


class TestOutputUndecided:
    def test_chosen_folder_needs_no_prompt(self) -> None:
        assert not output_undecided(False, "C:\\out")

    def test_same_folder_needs_no_prompt(self) -> None:
        assert not output_undecided(True, "")

    def test_same_folder_wins_over_empty_field(self) -> None:
        # a disabled entry still reports its old text, so the checkbox decides
        assert not output_undecided(True, "C:\\stale")

    def test_blank_field_without_checkbox_prompts(self) -> None:
        assert output_undecided(False, "")

    def test_whitespace_field_without_checkbox_prompts(self) -> None:
        assert output_undecided(False, "   ")


def test_drop_splits_multiple_paths_with_spaces() -> None:
    class DropHarness:
        root = SimpleNamespace(tk=tk.Tcl())

        def _add_paths(self, paths: list[Path]) -> None:
            self.paths = paths

    harness = DropHarness()
    App._on_file_drop(
        harness,
        SimpleNamespace(data="{C:/My Files/report.pdf} {D:/other file.pdf}"),
    )

    assert harness.paths == [
        Path("C:/My Files/report.pdf"),
        Path("D:/other file.pdf"),
    ]


def test_processing_log_toggle_opens_and_closes() -> None:
    class Widget:
        def __init__(self) -> None:
            self.options = {}
            self.forgot = False

        def pack(self, **options) -> None:
            self.options = options

        def pack_forget(self) -> None:
            self.forgot = True

        def configure(self, **options) -> None:
            self.options = options

    harness = SimpleNamespace(
        log_open=False,
        log_button=Widget(),
        log_frame=Widget(),
    )

    App._toggle_log(harness)
    assert harness.log_open
    assert harness.log_frame.options == {
        "fill": "both",
        "expand": True,
        "padx": 8,
        "pady": (2, 8),
    }
    assert harness.log_button.options["text"] == "\u25be Processing Log"

    App._toggle_log(harness)
    assert not harness.log_open
    assert harness.log_frame.forgot
    assert harness.log_button.options["text"] == "\u25b8 Processing Log"


def test_merge_list_is_numbered_in_order() -> None:
    # the number shown IS the page order of the merged result
    assert App.numbered_names(
        [Path("a.pdf"), Path("b.docx"), Path("c.png")]
    ) == ["1. a.pdf", "2. b.docx", "3. c.png"]


def test_merge_list_numbering_ignores_extension_case() -> None:
    assert App.numbered_names([Path("Report.PDF")]) == ["1. Report.PDF"]


def test_page_labels_show_position_number_and_rotation() -> None:
    # position in the new document, source page number, and an explicit
    # clockwise/counter-clockwise rotation tag
    labels = App.page_labels([3, 1, 2], {1: 90, 3: 180})
    assert labels == [
        "1. Page 3  [rotated 180\u00b0]",
        "2. Page 1  [rotated 90\u00b0 \u21bb]",
        "3. Page 2",
    ]


def test_page_labels_distinguish_left_and_right_rotation() -> None:
    # 90 is a clockwise (right) turn, 270 a counter-clockwise (left) one
    labels = App.page_labels([1, 2], {1: 90, 2: 270})
    assert labels == [
        "1. Page 1  [rotated 90\u00b0 \u21bb]",
        "2. Page 2  [rotated 90\u00b0 \u21ba]",
    ]


def test_page_labels_without_rotation() -> None:
    assert App.page_labels([1, 2], {}) == ["1. Page 1", "2. Page 2"]


def test_coffee_link_opens_donation_page(monkeypatch) -> None:
    opened = []
    monkeypatch.setattr(gui_module.webbrowser, "open", opened.append)

    App._open_coffee_link(None)

    assert opened == ["https://buymeacoffee.com/DrLwSii"]


@pytest.fixture(scope="module")
def tk_root():
    try:
        root = tk.Tk()
    except tk.TclError as exc:
        pytest.skip(f"Tk display unavailable: {exc}")
    try:
        yield root
    finally:
        root.destroy()


def test_pdf_tools_buttons_invoke_original_actions(tk_root, monkeypatch) -> None:
    from tkinter import ttk

    app = App.__new__(App)
    app.tools_tab = ttk.Frame(tk_root)
    calls = []
    actions = {
        "Split PDF": "run_split",
        "Extract": "run_extract",
        "Add Watermark": "run_watermark",
        "Add Numbers": "run_page_numbers",
        "Find": "run_find_text",
        "Replace All": "run_replace_text",
    }
    for action in actions.values():
        monkeypatch.setattr(app, action, lambda name=action: calls.append(name))
    try:
        app._build_pdf_tools_area()

        def buttons(widget):
            for child in widget.winfo_children():
                if isinstance(child, ttk.Button):
                    yield child
                yield from buttons(child)

        for button in buttons(app.tools_tab):
            button.invoke()
        assert sorted(calls) == sorted(actions.values())
    finally:
        app.tools_tab.destroy()


@pytest.fixture
def text_editor(tmp_path, tk_root):
    from PIL import ImageFont
    from reportlab.pdfgen import canvas

    root = tk_root
    try:
        try:
            font_path = Path(ImageFont.truetype("DejaVuSans.ttf", 14).path)
            bold_path = Path(ImageFont.truetype("DejaVuSans-Bold.ttf", 14).path)
        except OSError as exc:
            pytest.skip(f"Test font unavailable: {exc}")
        source = tmp_path / "source.pdf"
        pdf = canvas.Canvas(str(source))
        pdf.drawString(72, 720, "First line")
        pdf.showPage()
        pdf.drawString(72, 720, "Second line")
        pdf.save()

        app = App.__new__(App)
        app.root = root
        app.visual_text_tab = tk.Frame(root)
        app.visual_text_tab.pack()
        app.edit_source = source
        app.visual_text_page = 1
        app.visual_text_total_pages = 2
        app.visual_text_lines = []
        app.visual_text_image = None
        app._visual_text_ocr_warning_shown = False
        app.visual_text_edits = {}
        app.visual_text_fonts = {}
        app.visual_text_sizes = {}
        app.placed_text = []
        app.selected_visual_text = None
        app.selected_placed_text = None
        app._text_drag_offset = None
        app._updating_text_controls = False
        app._placed_images = []
        app._text_undo = []
        app._text_redo = []
        app._text_history_current = None
        app.system_fonts = {
            "Test Font": FontFace(font_path),
            "Test Bold": FontFace(bold_path),
        }
        app._build_visual_text_area()
        root.update()
        app._sync_text_history()
        app._load_visual_text_page()
        yield app
    finally:
        if "app" in locals():
            app.visual_text_tab.destroy()


def _canvas_event(app, x: float, y: float):
    return SimpleNamespace(
        x=x - app.visual_text_canvas.canvasx(0),
        y=y - app.visual_text_canvas.canvasy(0),
    )


def test_line_controls_queue_and_undo_redo(text_editor) -> None:
    app = text_editor
    line = app.visual_text_lines[0]
    app._select_visual_text(_canvas_event(app, line.x0, line.top))
    assert app.add_text_size_var.get() == str(max(4, round(line.height * 0.82)))

    app.add_text_size_var.set("24")
    app._queue_visual_text_change()
    key = app._visual_text_key(line)
    assert app.visual_text_edits[key][1] == line.text
    assert app.visual_text_sizes[key] == 24
    assert app.visual_text_fonts[key] == app.system_fonts["Test Font"]

    app._undo_text_edit()
    assert key not in app.visual_text_edits
    assert app.add_text_size_var.get() == "24"
    app._undo_text_edit()
    assert app.add_text_size_var.get() != "24"
    app._redo_text_edit()
    app._redo_text_edit()
    assert app.visual_text_sizes[key] == 24

    app.visual_text_var.set("Changed line")
    app._queue_visual_text_change()
    app._undo_text_edit()
    assert app.visual_text_edits[key][1] == line.text
    assert app.visual_text_var.get() == "Changed line"
    app._undo_text_edit()
    assert app.visual_text_var.get() == line.text
    app.visual_text_var.set("Different draft")
    assert not app._text_redo


def test_text_editor_shortcuts_dispatch_undo_and_redo(text_editor) -> None:
    app = text_editor
    line = app.visual_text_lines[0]
    app._select_visual_text(_canvas_event(app, line.x0, line.top))
    app.visual_text_var.set("Changed")
    app.root.update()
    app.visual_text_entry.focus_force()
    app.root.update()
    app.visual_text_entry.event_generate("<Control-z>")
    app.root.update()
    assert app.visual_text_var.get() == line.text
    app.visual_text_entry.event_generate("<Control-y>")
    app.root.update()
    assert app.visual_text_var.get() == "Changed"


def test_line_font_change_is_queued_and_restored(text_editor) -> None:
    app = text_editor
    line = app.visual_text_lines[0]
    app._select_visual_text(_canvas_event(app, line.x0, line.top))
    app.text_font_var.set("Test Bold")
    app._queue_visual_text_change()
    key = app._visual_text_key(line)
    assert app.visual_text_fonts[key] == app.system_fonts["Test Bold"]
    app._undo_text_edit()
    assert key not in app.visual_text_fonts
    app._undo_text_edit()
    assert app.text_font_var.get() == "Test Font"
    app._redo_text_edit()
    app._redo_text_edit()
    assert app.visual_text_fonts[key] == app.system_fonts["Test Bold"]


def test_line_controls_are_saved_in_pdf(text_editor, tmp_path, monkeypatch) -> None:
    from pypdf import PdfReader
    from pypdf.generic import ContentStream

    app = text_editor
    line = app.visual_text_lines[0]
    app._select_visual_text(_canvas_event(app, line.x0, line.top))
    app.visual_text_var.set("Updated")
    app.text_font_var.set("Test Bold")
    app.add_text_size_var.set("23")
    app._queue_visual_text_change()
    target = tmp_path / "saved.pdf"
    monkeypatch.setattr(app, "_edit_output_target", lambda source, suffix: target)
    monkeypatch.setattr(
        app, "_run_edit_task_custom", lambda work, done, title: done(work())
    )
    app._save_visual_text_changes()
    reader = PdfReader(str(target))
    operations = ContentStream(reader.pages[0].get_contents(), reader).operations
    assert any(op == b"Tf" and float(args[1]) == 23 for args, op in operations)
    assert "Updated" in reader.pages[0].extract_text()
    font_resources = reader.pages[0]["/Resources"]["/Font"].get_object()
    assert any(
        "/FontDescriptor" in font.get_object()
        and "/FontFile2" in font.get_object()["/FontDescriptor"].get_object()
        and "DejaVuSans-Bold" in str(font.get_object()["/BaseFont"])
        for font in font_resources.values()
    )


def test_opening_pdf_resets_text_edit_history(text_editor, monkeypatch) -> None:
    app = text_editor
    app._add_text_box()
    assert app._text_undo
    app.edit_source_var = tk.StringVar()
    app.edit_status_var = tk.StringVar()
    monkeypatch.setattr(gui_module.filedialog, "askopenfilenames", lambda **kwargs: [str(app.edit_source)])
    monkeypatch.setattr(app, "_dialog_dir", lambda: "")
    monkeypatch.setattr(app, "_remember_dir", lambda path: None)
    monkeypatch.setattr(app, "_refresh_page_list", lambda: None)
    app.open_edit_pdf()
    assert not app.placed_text
    assert not app._text_undo
    assert not app._text_redo
    assert str(app.text_undo_button["state"]) == "disabled"


def test_scanned_pages_warn_once_and_allow_text_boxes(
    text_editor, scanned_pdf_pages, monkeypatch
) -> None:
    app = text_editor
    warnings = []
    monkeypatch.setattr(
        gui_module.messagebox, "showwarning",
        lambda title, message, **kwargs: warnings.append((title, message)),
    )
    app.edit_source = scanned_pdf_pages
    app._load_visual_text_page()
    assert len(warnings) == 1
    assert "Convert File" in warnings[0][1]
    assert "SEARCHABLE-PDF" in warnings[0][1]
    assert "text boxes" in warnings[0][1]
    assert not app.visual_text_lines
    assert app.visual_text_image is not None
    app._add_text_box()
    assert len(app.placed_text) == 1
    app._navigate_visual_text(1)
    app._navigate_visual_text(-1)
    app._undo_text_edit()
    app._redo_text_edit()
    assert len(warnings) == 1
    assert len(app.placed_text) == 1


def test_ocr_warning_resets_on_open_and_handles_mixed_pages(
    text_editor, scanned_pdf, tmp_path, monkeypatch
) -> None:
    from pypdf import PdfReader, PdfWriter

    app = text_editor
    mixed = tmp_path / "mixed.pdf"
    writer = PdfWriter()
    writer.add_page(PdfReader(str(app.edit_source)).pages[0])
    writer.add_page(PdfReader(str(scanned_pdf)).pages[0])
    with mixed.open("wb") as stream:
        writer.write(stream)

    warnings = []
    monkeypatch.setattr(
        gui_module.messagebox, "showwarning",
        lambda title, message, **kwargs: warnings.append(message),
    )
    app.edit_source_var = tk.StringVar()
    app.edit_status_var = tk.StringVar()
    monkeypatch.setattr(gui_module.filedialog, "askopenfilenames", lambda **kwargs: [str(mixed)])
    monkeypatch.setattr(app, "_dialog_dir", lambda: "")
    monkeypatch.setattr(app, "_remember_dir", lambda path: None)
    monkeypatch.setattr(app, "_refresh_page_list", lambda: None)

    app.open_edit_pdf()
    # the import itself raises the Convert File reminder - exactly once
    assert len(warnings) == 1
    assert "Convert File" in warnings[0]
    assert "SEARCHABLE-PDF" in warnings[0]
    assert "text boxes" in warnings[0]
    app._navigate_visual_text(1)
    assert len(warnings) == 1
    app.open_edit_pdf()
    assert len(warnings) == 2
    app._navigate_visual_text(1)
    assert len(warnings) == 2


def test_import_reminder_is_shown_once_per_pdf(
    text_editor, text_pdf, scanned_pdf, monkeypatch
) -> None:
    app = text_editor
    warnings = []
    monkeypatch.setattr(
        gui_module.messagebox, "showwarning",
        lambda title, message, **kwargs: warnings.append(message),
    )

    # a PDF with a text layer is fine, so importing it says nothing
    app.edit_source = text_pdf
    app._warn_if_not_searchable()
    assert not warnings

    # a PDF without one gets the Convert File reminder exactly once
    app.edit_source = scanned_pdf
    app._warn_if_not_searchable()
    assert len(warnings) == 1
    assert "Convert File" in warnings[0]
    assert "SEARCHABLE-PDF" in warnings[0]
    app._warn_if_not_searchable()
    assert len(warnings) == 1

    # a new import starts a new file, so an unsearchable one warns again
    app._visual_text_ocr_warning_shown = False
    app.edit_source = text_pdf
    app._warn_if_not_searchable()
    assert len(warnings) == 1
    app.edit_source = scanned_pdf
    app._warn_if_not_searchable()
    assert len(warnings) == 2


def test_import_and_clear_buttons_close_the_source_row(tk_root, monkeypatch) -> None:
    from tkinter import ttk

    app = App.__new__(App)
    app.edit_tab = ttk.Frame(tk_root)
    app.edit_tab.pack()
    app.config = {}
    calls = []
    monkeypatch.setattr(app, "open_edit_pdf", lambda: calls.append("import"))
    monkeypatch.setattr(app, "clear_edit_pdf", lambda: calls.append("clear"))
    # only the source row is under test, so the heavier panes are stubbed out
    monkeypatch.setattr(app, "_build_organize_area", lambda: None)
    monkeypatch.setattr(app, "_build_visual_text_area", lambda: None)
    monkeypatch.setattr(app, "_build_pdf_tools_area", lambda: None)
    monkeypatch.setattr(app, "_build_edit_output_area", lambda: None)
    try:
        app._build_edit_area()
        tk_root.update()

        def buttons(widget):
            for child in widget.winfo_children():
                if isinstance(child, ttk.Button):
                    yield child
                yield from buttons(child)

        labels = {str(button["text"]): button for button in buttons(app.edit_tab)}
        assert set(labels) == {"Import PDF", "Clear"}
        # Clear is packed to the right, so it closes the row
        assert labels["Clear"].pack_info()["side"] == "right"
        assert labels["Import PDF"].pack_info()["side"] == "left"
        # ...and both sit in the row that shows the imported file name
        assert labels["Clear"].master is labels["Import PDF"].master
        assert labels["Clear"].master is app.edit_source_label.master

        labels["Import PDF"].invoke()
        labels["Clear"].invoke()
        assert calls == ["import", "clear"]
    finally:
        app.edit_tab.destroy()


def test_clear_drops_the_imported_file(text_editor) -> None:
    app = text_editor
    app.edit_source_var = tk.StringVar()
    app.edit_status_var = tk.StringVar()
    app.edit_pages = [1, 2]
    app.edit_rotations = {2: 90}
    app.visual_text_page = 2
    app.visual_text_total_pages = 2
    app._visual_text_ocr_warning_shown = True
    app._refresh_page_list = lambda keep_selection=False: None
    app._text_undo.append(app._text_edit_state())

    app.clear_edit_pdf()

    assert app.edit_source is None
    assert app.edit_pages == []
    assert app.edit_rotations == {}
    assert app.visual_text_page == 1
    assert app.visual_text_total_pages == 0
    assert app.visual_text_lines == []
    assert app.visual_text_image is None
    assert app.edit_source_var.get() == "No PDF loaded"
    assert app.edit_status_var.get() == "No PDF loaded"
    assert "Import PDF" in app.visual_text_status_var.get()
    assert str(app.visual_text_entry["state"]) == "disabled"
    assert str(app.visual_text_queue_button["state"]) == "disabled"
    assert str(app.visual_text_save_button["state"]) == "disabled"
    assert str(app.text_undo_button["state"]) == "disabled"
    assert str(app.text_redo_button["state"]) == "disabled"
    assert str(app.visual_text_prev["state"]) == "disabled"
    assert str(app.visual_text_next["state"]) == "disabled"
    assert app.visual_text_page_var.get() == "Page 1 of 0"
    # the reminder belongs to the dropped file, so a later import warns again
    assert not app._visual_text_ocr_warning_shown


def test_box_history_drag_remove_and_cross_page(text_editor) -> None:
    app = text_editor
    app._add_text_box()
    assert len(app.placed_text) == 1
    app.visual_text_var.set("A note")
    app.add_text_size_var.set("30")
    assert app.placed_text[0].text == "A note"
    assert app.placed_text[0].font_size == 30

    start = app.placed_text[0]
    app._visual_text_click(_canvas_event(app, start.x, start.top))
    assert app._text_drag_offset == (0, 0)
    undo_count = len(app._text_undo)
    app._drag_placed_text(_canvas_event(app, 80, 90))
    app._drag_placed_text(_canvas_event(app, 100, 110))
    app._end_text_drag(None)
    assert len(app._text_undo) == undo_count + 1
    moved = app.placed_text[0]
    assert (moved.x, moved.top) == (100, 110)
    app._undo_text_edit()
    assert app.placed_text[0] == start
    app._redo_text_edit()
    assert app.placed_text[0] == moved

    app._remove_text_box()
    assert not app.placed_text
    app._navigate_visual_text(1)
    app._undo_text_edit()
    assert app.visual_text_page == 1
    assert app.placed_text == [moved]
    app._redo_text_edit()
    assert not app.placed_text
    app._undo_text_edit()
    app._undo_text_edit()
    app._undo_text_edit()
    assert app.placed_text[0].font_size == 14
    app._undo_text_edit()
    assert app.placed_text[0].text == "Text"
    app._undo_text_edit()
    assert not app.placed_text
    app._redo_text_edit()
    assert app.placed_text[0].text == "Text"
