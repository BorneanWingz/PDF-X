"""CLI tests: exit codes, target listing, doctor output, batch conversion."""

from __future__ import annotations

from pathlib import Path

from pdftoolbox.cli import main


class TestDoctor:
    def test_doctor_exit_zero(self, capsys) -> None:
        code = main(["--doctor"])
        out = capsys.readouterr().out
        assert code == 0
        assert "pypdfium2" in out
        assert "rapidocr" in out
        assert "plugins" in out


class TestListTargets:
    def test_pdf_targets(self, text_pdf: Path, capsys) -> None:
        code = main(["--list-targets", str(text_pdf)])
        out = capsys.readouterr().out
        assert code == 0
        assert "png" in out and "searchable-pdf" in out

    def test_missing_files_error(self, capsys) -> None:
        code = main(["--list-targets"])
        assert code == 2


class TestConvert:
    def test_batch_png(self, text_pdf: Path, tmp_path: Path, capsys) -> None:
        code = main([str(text_pdf), "--to", "png", "--out", str(tmp_path / "cli")])
        out = capsys.readouterr().out
        assert code == 0
        assert "ok" in out
        assert len(list((tmp_path / "cli").glob("*.png"))) == 2

    def test_unknown_target_fails(self, text_pdf: Path, tmp_path: Path, capsys) -> None:
        code = main([str(text_pdf), "--to", "epub", "--out", str(tmp_path / "bad")])
        captured = capsys.readouterr()
        assert code == 1
        assert "unsupported target" in captured.out + captured.err

    def test_bad_pages_returns_two(self, text_pdf: Path, capsys) -> None:
        code = main([str(text_pdf), "--to", "png", "--pages", "5-2"])
        assert code == 2

    def test_missing_input_returns_two(self, tmp_path: Path, capsys) -> None:
        code = main([str(tmp_path / "nope.pdf"), "--to", "png"])
        assert code == 2

    def test_no_target_returns_two(self, text_pdf: Path, capsys) -> None:
        code = main([str(text_pdf)])
        assert code == 2
