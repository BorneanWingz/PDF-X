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
