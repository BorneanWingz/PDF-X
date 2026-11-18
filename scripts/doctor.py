"""PDF-X Doctor — Textual TUI audit dashboard for the pdf-toolbox codebase.

Scans the source tree and reports per-module metrics: line counts, function
counts, oversized functions and broad exception handlers, with review
suggestions. Suggestions are review prompts, not confirmed defects.

Run from the repo root inside VS Code's terminal:
    .venv\\Scripts\\python.exe scripts\\doctor.py
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, field
from pathlib import Path

from textual.app import App, ComposeResult
from textual.widgets import DataTable, Footer, Header, Label

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src" / "pdftoolbox"


@dataclass
class FileStats:
    path: Path
    lines: int
    functions: int
    classes: int
    long_functions: list[tuple[str, int]] = field(default_factory=list)
    broad_excepts: int = 0
    max_depth: int = 0



# --------------------------------------------------------------------------
# Static analysis helpers
# --------------------------------------------------------------------------

def analyse_file(path: Path) -> FileStats:
    text = path.read_text(encoding="utf-8-sig")
    tree = ast.parse(text, filename=str(path))
    stats = FileStats(path=path, lines=text.count("\n") + 1,
                      functions=0, classes=0)

    def walk(node, depth=0):
        stats.max_depth = max(stats.max_depth, depth)
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                stats.functions += 1
                length = (child.end_lineno or child.lineno) - child.lineno + 1
                if length > 80:
                    stats.long_functions.append((child.name, length))
            elif isinstance(child, ast.ClassDef):
                stats.classes += 1
            elif isinstance(child, ast.ExceptHandler) and (
                child.type is None
                or (isinstance(child.type, ast.Name) and child.type.id == "Exception")
            ):
                stats.broad_excepts += 1
            walk(child, depth + 1)

    walk(tree)
    return stats


def collect_stats() -> list[FileStats]:
    return [analyse_file(path) for path in sorted(SRC.rglob("*.py"))]


class DoctorApp(App):
    TITLE = "PDF-X Doctor"
    BINDINGS = [("q", "quit", "Quit"), ("r", "rescan", "Rescan")]

    def compose(self) -> ComposeResult:
        yield Header()
        yield Label("Review suggestions: metrics alone do not prove defects.")
        yield DataTable()
        yield Footer()

    def on_mount(self) -> None:
        self.query_one(DataTable).add_columns(
            "Module", "Lines", "Functions", "Functions >80 lines",
            "Broad handlers", "Review suggestion",
        )
        self.action_rescan()

    def action_rescan(self) -> None:
        table = self.query_one(DataTable)
        table.clear()
        for stats in sorted(collect_stats(), key=lambda item: -item.lines):
            suggestion = "Review module responsibilities" if stats.lines > 500 else ""
            if not suggestion and stats.long_functions:
                suggestion = "Consider extracting helpers"
            table.add_row(str(stats.path.relative_to(SRC)), str(stats.lines),
                          str(stats.functions), str(len(stats.long_functions)),
                          str(stats.broad_excepts), suggestion)


if __name__ == "__main__":
    DoctorApp().run()

