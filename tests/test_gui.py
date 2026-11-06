"""GUI rules that need no display (pure helpers from pdftoolbox.gui).

NOTE: importing pdftoolbox.gui pulls in tkinter but creates no Tk root, so
these tests run anywhere; the interactive checks live in scripts/gui_smoke.py.
"""

from __future__ import annotations

import pytest

pytest.importorskip("tkinter")

from pdftoolbox.gui import output_undecided  # noqa: E402


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
