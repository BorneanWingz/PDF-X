"""Tkinter GUI: zero extra dependencies, fully offline.

Threading rule: all conversions run on a worker thread; results are pushed
back through a queue and rendered from an ``after`` poll, so the window
never freezes and Tk is only touched from the main thread.
"""

from __future__ import annotations

import logging
import queue
import threading
import tkinter as tk
import webbrowser
from dataclasses import dataclass, replace
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from tkinterdnd2 import DND_FILES, TkinterDnD

from . import __author__, __version__, promo
from .config import load_config, save_config
from .convert import (
    can_convert_to_pdf,
    convert_many,
    list_targets,
    merge_to_pdf,
    normalize_target,
    parse_pages,
    OCR_FIRST_TARGETS,
)
from .engines import ConversionError, EngineUnavailable
from .engines import pdf_edit, pdf_text
from .paths import icon_path
from .system_fonts import FontFace, installed_fonts, suggest_font
from . import theme


images_suffixes = [".png", ".jpg", ".jpeg", ".bmp", ".webp", ".tif", ".tiff", ".gif"]
office_suffixes = [
    ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
    ".odt", ".ods", ".odp", ".rtf", ".csv",
]


def output_undecided(same_folder: bool, out_dir_text: str) -> bool:
    """True when the user chose neither an output folder nor 'same folder'.

    NOTE: pure function, so the GUI rule stays unit-testable without a display.
    The checkbox - not the (possibly disabled) entry widget - is the source of
    truth for the 'same folder' intent.
    """
    return not same_folder and not out_dir_text.strip()


def drop_paths(event) -> list[str]:
    """The file paths carried by a drag-and-drop event.

    NOTE: a module-level function, so the parsing stays unit-testable without
    a window and can be shared by every drop target.
    """
    if not event.data:
        return []
    return list(tk.Tcl().splitlist(event.data))


TextKey = tuple[int, float, float, float, float, str]


@dataclass
class TextEditState:
    edits: dict[TextKey, tuple[pdf_edit.TextMatch, str]]
    redacted: dict[TextKey, pdf_edit.TextMatch]
    fonts: dict[TextKey, FontFace]
    sizes: dict[TextKey, int]
    boxes: list[pdf_edit.PlacedText]
    page: int
    selected_line: pdf_edit.TextMatch | None
    selected_box: int | None
    text: str
    font: str
    size: str


class App:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.config = load_config()
        self.files: list[Path] = []
        self._office_ocr_warning_shown = False
        self.merge_files: list[Path] = []
        self.edit_source: Path | None = None
        self.edit_pages: list[int] = []
        self.edit_rotations: dict[int, int] = {}
        self.visual_text_page = 1
        self.visual_text_total_pages = 0
        self._text_resizing = False
        self._text_resize_origin = (0.0, 0.0)
        self.visual_text_lines: list[pdf_edit.TextMatch] = []
        self.visual_text_edits: dict[
            tuple[int, float, float, float, float, str],
            tuple[pdf_edit.TextMatch, str],
        ] = {}
        self.selected_visual_text: pdf_edit.TextMatch | None = None
        # NOTE: lines queued for real removal. They are kept apart from
        # visual_text_edits, because a redacted line has no replacement text
        # and must not be drawn back onto the preview.
        self.redacted_visual_text: dict[
            tuple[int, float, float, float, float, str], pdf_edit.TextMatch
        ] = {}
        self.visual_text_image = None
        self._visual_text_ocr_warning_shown = False
        self.system_fonts = installed_fonts()
        self.visual_text_fonts: dict[tuple[int, float, float, float, float, str], FontFace] = {}
        self.visual_text_sizes: dict[TextKey, int] = {}
        self.placed_text: list[pdf_edit.PlacedText] = []
        self.selected_placed_text: int | None = None
        self._text_drag_offset: tuple[float, float] | None = None
        self._updating_text_controls = False
        self._placed_images: list = []
        # NOTE: the page is rendered at 72 dpi, so 100% is its natural size.
        # Zooming re-renders at a higher dpi, which keeps the text crisp.
        self._viewer_zoom = 100
        self._text_undo: list[TextEditState] = []
        self._text_redo: list[TextEditState] = []
        self._text_history_current: TextEditState | None = None
        self._editor_window_open = False
        self.events: queue.Queue[tuple] = queue.Queue()
        self.worker: threading.Thread | None = None

        root.title(f"PDF-X {__version__}")
        # NOTE: sized for the tallest tab, not for the eye. The Edit PDF tab
        # stacks 639 px of content (intro 34 + source row 25 + sub-tab strip 399,
        # which follows the tallest "Edit Text" pane + "Edit options" 77 + Apply
        # row 25 + log button 25 + 54 of padding), and the window spends 26 px on
        # the title bar and notebook strip. At the old 760x560 the tab only had
        # 534 px, so "Edit options" was cut in half and the Apply row plus the log
        # button were pushed completely off the bottom of the tab.
        # minsize keeps 680 px, the smallest height whose tab (654 px) still
        # clears that content, so resizing cannot bring the clipping back.
        root.geometry("1180x800")
        root.minsize(980, 680)
        self._apply_window_icon(root)
        self._configure_styles(root)

        # Shell: a dark header with the brand mark, a left sidebar with the
        # navigation and the recent files, and a content area holding the
        # pages. The pages are stacked and swapped with pack_forget() rather
        # than a ttk.Notebook, because the mockup's design has no tab strip.
        self.shell = tk.Frame(root, background=theme.CANVAS)
        self.shell.pack(fill="both", expand=True)
        self.shell.rowconfigure(1, weight=1)
        self.shell.columnconfigure(1, weight=1)

        self._build_header()
        self._build_sidebar()

        self.content = tk.Frame(self.shell, background=theme.CANVAS)
        self.content.grid(row=1, column=1, sticky="nsew", padx=14, pady=14)

        self.convert_tab = ttk.Frame(self.content)
        self.merge_tab = ttk.Frame(self.content)
        self.edit_tab = ttk.Frame(self.content)
        self.organise_tab = ttk.Frame(self.content)
        self.utilities_tab = ttk.Frame(self.content)
        self.about_tab = ttk.Frame(self.content)
        self._pages = {
            "convert": self.convert_tab,
            "merge": self.merge_tab,
            "organise": self.organise_tab,
            "edit": self.edit_tab,
            "utilities": self.utilities_tab,
            "about": self.about_tab,
        }

        self._build_file_area()
        self._build_options_area()
        self._build_action_area()
        self._build_promo_area()
        self._build_merge_area()
        self._build_organise_tab_area()
        self._build_edit_area()
        self._build_utilities_tab_area()
        self._build_about_area()

        self._sync_text_history()
        self._refresh_targets()
        self._show_page("convert")
        # NOTE: the Edit PDF tab opens on its empty state, so the drop zone is
        # showing until a PDF is imported
        self._show_drop_zone(True)
        # NOTE: the queue + after() poll is the ONLY bridge from worker
        # threads back to Tk - Tk widgets must never be touched off-thread
        self._poll_events()

    # ---------- settings ----------

    def _apply_window_icon(self, root: tk.Tk) -> None:
        """Put the app icon in the title bar / taskbar.

        NOTE: PyInstaller's ``icon=`` only stamps the EXE resource, which is what
        Explorer shows. A Tk window does NOT inherit it - without this call the
        title bar keeps Tk's default feather, which is why the window icon did
        not match assets/pdf-x.ico. ``iconphoto`` is used rather than
        ``iconbitmap`` because it also works from a bundled temp dir, and the
        sizes are set explicitly so Windows picks the right one for the title
        bar (16/24 px) and taskbar (32 px) instead of scaling a single frame.
        """
        icon = icon_path()
        if icon is None:
            return
        try:
            from PIL import Image, ImageTk

            with Image.open(icon) as source:
                # NOTE: the ICO holds 16..256 px frames; keep a copy of each
                # size Tk should offer, and hold references so Tk does not
                # garbage-collect the images out from under the window
                self._icon_images = []
                for size in (16, 24, 32, 48, 64, 128, 256):
                    frame = source.copy()
                    frame.thumbnail((size, size), Image.LANCZOS)
                    photo = ImageTk.PhotoImage(frame.convert("RGBA"))
                    self._icon_images.append(photo)
                if self._icon_images:
                    root.iconphoto(True, *self._icon_images)
                    return
        except Exception:  # noqa: BLE001 - a missing icon must never block startup
            pass
        # fallback without Pillow: Tk can read .ico directly on Windows
        try:
            root.iconbitmap(default=str(icon))
        except tk.TclError:
            pass  # non-Windows or unreadable file: keep the default icon


    def _save_settings(self) -> None:
        """Write user settings to config.json beside the executable.

        NOTE: a read-only install location must never break a conversion, so
        persistence failures are swallowed and the run simply goes on.
        """
        try:
            save_config(self.config)
        except OSError:
            pass  # read-only location: run without persisting

    def _remember_dir(self, folder: Path) -> None:
        """Store the folder of the last imported file for the next session."""
        text = str(folder)
        if text and text != self.config.get("last_dir"):
            self.config["last_dir"] = text
            self._save_settings()

    def _dialog_dir(self) -> str | None:
        """initialdir for the file dialogs: where the user last imported."""
        folder = str(self.config.get("last_dir", "") or "")
        return folder if folder and Path(folder).is_dir() else None

    # ---------- layout ----------

    def _build_header(self) -> None:
        """The dark header bar: brand mark, name, and the tagline."""
        header = tk.Frame(self.shell, background=theme.HEADER, height=68)
        header.grid(row=0, column=0, columnspan=2, sticky="ew")
        header.grid_propagate(False)
        header.grid_columnconfigure(3, weight=1)

        logo = tk.Label(header, background=theme.HEADER, bd=0)
        mark = self._brand_mark(34)
        if mark is not None:
            logo.configure(image=mark)
        logo.image = mark
        logo.grid(row=0, column=0, padx=(18, 12), pady=14)

        tk.Label(
            header,
            text="PDF-X",
            background=theme.HEADER,
            foreground=theme.SURFACE,
            font=("TkDefaultFont", 18, "bold"),
        ).grid(row=0, column=1, sticky="w")

        tk.Label(
            header,
            text="Portable PDF conversion and OCR",
            background=theme.HEADER,
            foreground=theme.HEADER_MUTED,
            font=("TkDefaultFont", 9),
        ).grid(row=0, column=2, sticky="w", padx=(18, 0))

        self.promo_label = tk.Label(
            header,
            text="",
            anchor="e",
            justify="right",
            wraplength=360,
            fg=theme.ACCENT,
            background=theme.HEADER,
            cursor="hand2",
        )
        self.promo_label.grid(row=0, column=3, sticky="e", padx=18)
        self.promo_label.bind("<Button-1>", self._open_promo_url)
        self._promo_url = ""

    def _brand_mark(self, size: int):
        """The app icon as a header logo, or None when it cannot be loaded."""
        icon = icon_path()
        if icon is None:
            return None
        try:
            from PIL import Image, ImageTk

            with Image.open(icon) as source:
                frame = source.convert("RGBA")
                frame.thumbnail((size, size), Image.LANCZOS)
                return theme._keep(
                    ImageTk.PhotoImage(frame, master=self.root)
                )
        except Exception:  # noqa: BLE001 - a missing logo must not block startup
            return None

    def _build_sidebar(self) -> None:
        """The left rail: navigation entries plus the recent documents."""
        self._glyphs = {
            name: theme.draw_glyph(name, 20, master=self.root)
            for name in (
                "convert", "merge", "organise", "edit", "tools", "about",
                "up", "down", "rotate_left", "rotate_right",
                "rotate_180", "delete", "reset", "pdf",
                "folder", "add",
            )
        }

        sidebar = tk.Frame(self.shell, background=theme.SIDEBAR, width=232)
        sidebar.grid(row=1, column=0, sticky="nsw", padx=(14, 0), pady=14)
        sidebar.grid_propagate(False)
        sidebar.grid_rowconfigure(1, weight=1)

        nav = tk.Frame(sidebar, background=theme.SIDEBAR)
        nav.grid(row=0, column=0, sticky="ew")

        self._sidebar_rows = {}
        entries = (
            ("convert", "Convert File", "convert"),
            ("merge", "Merge PDF", "merge"),
            ("organise", "Organise PDF", "organise"),
            ("edit", "Edit PDF", "edit"),
            ("utilities", "Utilities", "tools"),
            ("about", "About", "about"),
        )
        for key, text, glyph in entries:
            row = theme.sidebar_row(nav, text, glyph, self._glyphs)
            row.pack(fill="x")
            theme.bind_click(row, lambda k=key: self._show_page(k))
            self._sidebar_rows[key] = row

        # the recent-files block sits at the bottom of the rail
        recent = tk.Frame(sidebar, background=theme.SIDEBAR)
        recent.grid(row=1, column=0, sticky="sew")
        tk.Label(
            recent,
            text="RECENT FILES",
            background=theme.SIDEBAR,
            foreground=theme.MUTED,
            font=("TkDefaultFont", 8, "bold"),
        ).pack(anchor="w", padx=16, pady=(10, 6))
        self.recent_list = tk.Frame(recent, background=theme.SIDEBAR)
        self.recent_list.pack(fill="both", expand=True)
        self._refresh_recent_files()

    def _show_page(self, key: str) -> None:
        """Swap the content area to the named page."""
        for name, page in self._pages.items():
            if name == key:
                page.pack(fill="both", expand=True)
            else:
                page.pack_forget()
        for name, row in self._sidebar_rows.items():
            theme.set_sidebar_active(row, name == key)
        self.current_page = key

    # ---------- recent files ----------

    def _remember_recent(self, path: Path) -> None:
        """Record a document in the recent-files list (newest first)."""
        try:
            resolved = str(path.resolve())
        except OSError:
            resolved = str(path)
        # NOTE: entries are compared by their resolved path, so the same file
        # cannot appear twice under two spellings of its location
        kept = []
        for item in self.config.get("recent_files", []):
            try:
                key = str(Path(item).resolve())
            except OSError:
                key = str(item)
            if key != resolved:
                kept.append(item)
        kept.insert(0, resolved)
        self.config["recent_files"] = kept[:8]
        self._save_settings()
        self._refresh_recent_files()

    def _refresh_recent_files(self) -> None:
        """Redraw the recent-files list, hiding entries that vanished."""
        listing = getattr(self, "recent_list", None)
        if listing is None:
            # NOTE: a headless harness may build the editor without the
            # sidebar, so there is nothing to redraw
            return
        for child in listing.winfo_children():
            child.destroy()

        entries = []
        seen = set()
        for item in self.config.get("recent_files", []):
            candidate = Path(item)
            if not candidate.is_file():
                continue
            # NOTE: the same file can be stored under two spellings (a relative
            # and a resolved path), so the list is keyed on the resolved path
            try:
                key = str(candidate.resolve())
            except OSError:
                key = str(candidate)
            if key in seen:
                continue
            seen.add(key)
            entries.append(candidate)
        # NOTE: the stored list keeps files that were deleted meanwhile, so the
        # sidebar hides them without losing the user's other shortcuts
        self.config["recent_files"] = [str(item) for item in entries]

        if not entries:
            tk.Label(
                listing,
                text="No files yet",
                background=theme.SIDEBAR,
                foreground=theme.MUTED,
                font=("TkDefaultFont", 9),
            ).pack(anchor="w", padx=16)
            return

        for candidate in entries:
            row = tk.Frame(listing, background=theme.SIDEBAR, cursor="hand2")
            icon = tk.Label(
                row,
                image=self._glyphs.get("pdf"),
                background=theme.SIDEBAR,
                width=16,
                height=16,
            )
            icon.image = self._glyphs.get("pdf")
            icon.pack(side="left", padx=(16, 0))
            label = tk.Label(
                row,
                text=candidate.name,
                background=theme.SIDEBAR,
                foreground=theme.INK,
                font=("TkDefaultFont", 9),
                anchor="w",
            )
            label.pack(side="left", fill="x", expand=True, padx=(8, 12), pady=4)
            theme.bind_click(row, lambda p=candidate: self._open_recent(p))
            row.pack(fill="x")

    def _open_recent(self, path: Path) -> None:
        """Load a document from the recent list into the Edit PDF tab."""
        self._show_page("edit")
        try:
            count = pdf_edit.page_count(path)
        except ConversionError as exc:
            messagebox.showerror("PDF-X", str(exc))
            return
        self._reset_edit_session(path, count)
        self._load_visual_text_page()
        self._warn_if_not_searchable()

    def _configure_styles(self, root: tk.Tk) -> None:
        """Apply the brand palette (see the theme module) to the whole tree."""
        theme.apply_theme(root)

    def _build_file_area(self) -> None:
        theme.page_header(
            self.convert_tab,
            "Convert File",
            "Convert documents and images between supported formats.",
        ).pack(anchor="w", pady=(0, 10))

        frame = theme.card(self.convert_tab)
        # NOTE: fill="both" + expand so the file box is the row that absorbs the
        # window's spare height, exactly like the Merge PDF list. With fill="x"
        # only, nothing in this tab could grow, so the old taller-than-needed
        # window left a dead strip under the Processing Log button, and opening
        # the log squeezed the log down to 89 px instead of taking room from the
        # list.
        frame.pack(fill="both", expand=True, pady=(0, 10))

        ttk.Label(
            frame,
            text="Files (drop files here)",
            style="Card.TLabel",
            font=("TkDefaultFont", 10, "bold"),
        ).pack(anchor="w", padx=14, pady=(10, 4))

        self.convert_body = ttk.Frame(frame, style="Card.TFrame")
        self.convert_body.pack(fill="both", expand=True, padx=14, pady=(0, 12))

        # NOTE: the empty state is the SAME dashed drop target the Organise PDF
        # page uses, so all three file tabs open the same way
        self.convert_drop = theme.dashed_drop_zone(
            self.convert_body,
            height=190,
            on_drop=self._on_file_drop,
        )
        content = self.convert_drop.content
        self.convert_drop_badge = theme.draw_pdf_badge(64, master=self.root)
        tk.Label(
            content, image=self.convert_drop_badge, background=theme.SURFACE
        ).pack(pady=(8, 2))
        tk.Label(
            content,
            text="Drop files here or",
            background=theme.SURFACE,
            foreground=theme.INK,
            font=("TkDefaultFont", 11),
        ).pack()
        ttk.Button(
            content,
            text="Add files",
            command=self.add_files,
            style="Accent.TButton",
        ).pack(pady=6)
        self.convert_drop_hint = tk.Label(
            content,
            text="No files added yet.",
            background=theme.SURFACE,
            foreground=theme.MUTED,
            font=("TkDefaultFont", 9),
        )
        self.convert_drop_hint.pack()

        body = ttk.Frame(self.convert_body, style="Card.TFrame")
        self.convert_list_host = body

        self.file_list = tk.Listbox(body, height=6, selectmode="extended")
        self.file_list.pack(side="left", fill="both", expand=True, pady=(0, 2))
        self.file_list.drop_target_register(DND_FILES)
        self.file_list.dnd_bind("<<Drop>>", self._on_file_drop)
        scroll = ttk.Scrollbar(body, command=self.file_list.yview)
        scroll.pack(side="left", fill="y", pady=(0, 2))
        self.file_list.configure(yscrollcommand=scroll.set)

        # NOTE: the action buttons sit in an icon toolbar under the list, the
        # same way the Organise PDF page does it, so the three file lists
        # read the same way
        toolbar = tk.Frame(frame, background=theme.SURFACE)
        toolbar.pack(fill="x", padx=14, pady=(0, 12))
        actions = (
            ("Add files", "add", self.add_files),
            ("Add folder", "folder", self.add_folder),
            ("Remove", "delete", self.remove_selected),
            ("Clear", "reset", self.clear_files),
        )
        for text, glyph, command in actions:
            button = theme.toolbar_button(toolbar, text, glyph, self._glyphs)
            button.pack(side="left", padx=(0, 18))
            theme.bind_click(button, command)
        self._sync_file_drop_zone()

    def _sync_file_drop_zone(self) -> None:
        """Show the dashed drop target when Convert File is empty, list when not."""
        drop = getattr(self, "convert_drop", None)
        host = getattr(self, "convert_list_host", None)
        if drop is None or host is None:
            return
        if self.files:
            drop.pack_forget()
            host.pack(fill="both", expand=True)
        else:
            host.pack_forget()
            drop.pack(fill="both", expand=True)

    def _sync_merge_drop_zone(self) -> None:
        """Show the dashed drop target when Merge PDF is empty, list when not."""
        drop = getattr(self, "merge_drop", None)
        host = getattr(self, "merge_list_host", None)
        if drop is None or host is None:
            return
        if self.merge_files:
            drop.pack_forget()
            host.pack(fill="both", expand=True)
        else:
            host.pack_forget()
            drop.pack(fill="both", expand=True)

    def _build_options_area(self) -> None:
        frame = theme.card(self.convert_tab)
        frame.pack(fill="x", pady=(0, 10))
        frame.columnconfigure(3, weight=1)

        ttk.Label(
            frame,
            text="Conversion options",
            style="Card.TLabel",
            font=("TkDefaultFont", 10, "bold"),
        ).grid(row=0, column=0, columnspan=4, sticky="w", padx=14, pady=(10, 6))

        ttk.Label(frame, text="Convert to:", style="Card.TLabel").grid(
            row=1, column=0, sticky="w", padx=12, pady=2
        )
        self.target_var = tk.StringVar()
        self.target_box = ttk.Combobox(
            frame, textvariable=self.target_var, state="readonly", width=22
        )
        self.target_box.grid(row=1, column=1, sticky="w", pady=4)
        self.target_box.bind("<<ComboboxSelected>>", self._on_target_selected)

        # ---------- pages ----------
        ttk.Label(frame, text="Pages:", style="Card.TLabel").grid(
            row=2, column=0, sticky="w", padx=12, pady=2
        )
        pages_row = ttk.Frame(frame, style="Card.TFrame")
        pages_row.grid(row=2, column=1, columnspan=3, sticky="ew", pady=4)
        self.pages_var = tk.StringVar()
        self.pages_entry = ttk.Entry(pages_row, textvariable=self.pages_var, width=18)
        self.pages_entry.pack(side="left")
        # NOTE: the help text sits next to the field so the syntax is obvious
        # without leaving the window (blank = every page)
        ttk.Label(
            pages_row,
            text="  Blank = All pages \u00b7 Example ranges: 1-3,5 \u00b7 Only for PDF input",
            style="CardMuted.TLabel",
        ).pack(side="left")

        # ---------- output ----------
        ttk.Label(frame, text="Output folder:", style="Card.TLabel").grid(
            row=3, column=0, sticky="w", padx=12, pady=2
        )
        self.out_var = tk.StringVar(value=str(self.config.get("out_dir", "")))
        # NOTE: entry and button are kept as attributes so the "Output in same
        # folder" checkbox can disable both together
        self.out_entry = ttk.Entry(frame, textvariable=self.out_var)
        self.out_entry.grid(row=3, column=1, columnspan=2, sticky="ew", pady=4)
        self.browse_button = ttk.Button(
            frame, text="Browse", command=self.pick_output, style="Card.TButton"
        )
        self.browse_button.grid(row=3, column=3, sticky="e", padx=(6, 14), pady=4)

        self.same_folder_var = tk.BooleanVar(
            value=bool(self.config.get("same_folder", False))
        )
        ttk.Checkbutton(
            frame,
            text="Output in same folder",
            variable=self.same_folder_var,
            command=self._toggle_same_folder,
            style="Card.TCheckbutton",
        ).grid(row=4, column=1, columnspan=3, sticky="w", pady=(0, 4))
        self._update_output_state()

        # ---------- advanced (collapsed by default) ----------
        self._build_advanced_area(frame, row=5)

        self.target_note = ttk.Label(frame, text="", style="CardMuted.TLabel")
        self.target_note.grid(row=7, column=0, columnspan=4, sticky="w", padx=12, pady=(0, 8))

    def _build_advanced_area(self, parent, row: int) -> None:
        """DPI settings, hidden behind a disclosure toggle until needed.

        NOTE: these are tuning knobs, not everyday choices - folding them away
        keeps the main block down to the four decisions a user actually makes.
        """
        self.advanced_open = False
        self.advanced_button = ttk.Button(
            parent,
            text="\u25b8 Advanced Options",
            width=20,
            command=self._toggle_advanced,
            style="Card.TButton",
        )
        self.advanced_button.grid(row=row, column=0, columnspan=2, sticky="w", padx=14, pady=(2, 8))

        # NOTE: never gridded until opened - grid_remove() alone still reserves
        # the row, which would leave an empty gap in the collapsed state
        self.advanced_frame = ttk.Frame(parent, style="Card.TFrame")
        self.advanced_frame.columnconfigure(5, weight=1)

        ttk.Label(self.advanced_frame, text="Image DPI:", style="Card.TLabel").grid(
            row=0, column=0, sticky="w", pady=2
        )
        self.dpi_var = tk.StringVar(value=str(self.config.get("dpi", 150)))
        ttk.Spinbox(
            self.advanced_frame, from_=72, to=600, width=6, textvariable=self.dpi_var
        ).grid(row=0, column=1, sticky="w", padx=(4, 0), pady=2)
        ttk.Label(
            self.advanced_frame,
            text="  Resolution for PNG / JPG / TIF / PPTX output",
            style="CardMuted.TLabel",
        ).grid(row=0, column=2, sticky="w", pady=2)

        ttk.Label(self.advanced_frame, text="OCR DPI:", style="Card.TLabel").grid(
            row=1, column=0, sticky="w", pady=2
        )
        self.ocr_dpi_var = tk.StringVar(value=str(self.config.get("ocr_dpi", 200)))
        ttk.Spinbox(
            self.advanced_frame, from_=100, to=600, width=6, textvariable=self.ocr_dpi_var
        ).grid(row=1, column=1, sticky="w", padx=(4, 0), pady=1)
        ttk.Label(
            self.advanced_frame,
            text="  Resolution used when OCR reads a scanned page",
            style="CardMuted.TLabel",
        ).grid(row=1, column=2, sticky="w", pady=2)

    def _toggle_advanced(self) -> None:
        if self.advanced_open:
            self.advanced_frame.grid_remove()
            self.advanced_button.configure(text="\u25b8 Advanced Options")
        else:
            self.advanced_frame.grid(row=6, column=0, columnspan=4, sticky="ew", padx=14, pady=(0, 4))
            self.advanced_button.configure(text="\u25be Advanced Options")
        self.advanced_open = not self.advanced_open

    def _build_action_area(self) -> None:
        frame = theme.card(self.convert_tab)
        frame.pack(fill="x", pady=(0, 10))
        self.convert_button = ttk.Button(
            frame, text="Convert", command=self.start_convert, style="Accent.TButton"
        )
        self.convert_button.pack(side="left", padx=14, pady=12)
        self.progress = ttk.Progressbar(frame, mode="determinate")
        self.progress.pack(side="left", fill="x", expand=True, padx=8)
        self.status_var = tk.StringVar(value="Ready")
        ttk.Label(frame, textvariable=self.status_var, style="Card.TLabel").pack(
            side="left", padx=(0, 14)
        )

    def _build_promo_area(self) -> None:
        promo_conf = self.config.get("promo", {})
        if promo_conf.get("enabled", True) and promo_conf.get("url"):
            # NOTE: daemon=True so a hung network call can never keep the
            # app alive after the window closes
            thread = threading.Thread(target=self._fetch_promo, args=(promo_conf,), daemon=True)
            thread.start()

    # ---------- merge tab ----------

    def _build_merge_area(self) -> None:
        """Merge PDF tab: an ordered, numbered list merged into one PDF.

        Every input is converted to PDF first (unless it already is one), then
        the parts are concatenated in list order - so the sequence shown in the
        box IS the page order of the result.
        """
        theme.page_header(
            self.merge_tab,
            "Merge PDF",
            "Combine any files into one PDF. Each file is converted to PDF "
            "first, then merged in the order shown below.",
        ).pack(anchor="w", pady=(0, 10))

        frame = theme.card(self.merge_tab)
        frame.pack(fill="both", expand=True, pady=(0, 10))

        ttk.Label(
            frame,
            text="Files to merge (drag to reorder)",
            style="Card.TLabel",
            font=("TkDefaultFont", 10, "bold"),
        ).pack(anchor="w", padx=14, pady=(10, 4))

        body = ttk.Frame(frame, style="Card.TFrame")
        self.merge_body = body
        body.pack(fill="both", expand=True, padx=14, pady=(0, 12))

        # NOTE: same dashed empty state as the Organise PDF page
        self.merge_drop = theme.dashed_drop_zone(
            body,
            height=190,
            on_drop=self._on_merge_drop,
        )
        content = self.merge_drop.content
        self.merge_drop_badge = theme.draw_pdf_badge(64, master=self.root)
        tk.Label(
            content, image=self.merge_drop_badge, background=theme.SURFACE
        ).pack(pady=(8, 2))
        tk.Label(
            content,
            text="Drop files here or",
            background=theme.SURFACE,
            foreground=theme.INK,
            font=("TkDefaultFont", 11),
        ).pack()
        ttk.Button(
            content,
            text="Add files",
            command=self.add_merge_files,
            style="Accent.TButton",
        ).pack(pady=6)
        self.merge_drop_hint = tk.Label(
            content,
            text="No files added yet.",
            background=theme.SURFACE,
            foreground=theme.MUTED,
            font=("TkDefaultFont", 9),
        )
        self.merge_drop_hint.pack()

        self.merge_list_host = ttk.Frame(body, style="Card.TFrame")
        list_host = self.merge_list_host
        list_host.pack(fill="both", expand=True)

        self.merge_list = tk.Listbox(list_host, height=8, selectmode="extended")
        self.merge_list.pack(side="left", fill="both", expand=True, pady=(0, 2))
        self.merge_list.drop_target_register(DND_FILES)
        self.merge_list.dnd_bind("<<Drop>>", self._on_merge_drop)
        # NOTE: click-and-drag inside the list reorders it; numbering is redrawn
        # on release so "1." always sits on the first item
        self.merge_list.bind("<Button-1>", self._on_merge_drag_start, add="+")
        self.merge_list.bind("<B1-Motion>", self._on_merge_drag_motion)
        self.merge_list.bind("<ButtonRelease-1>", self._on_merge_drag_drop)
        scroll = ttk.Scrollbar(list_host, command=self.merge_list.yview)
        scroll.pack(side="left", fill="y", pady=(0, 2))
        self.merge_list.configure(yscrollcommand=scroll.set)

        # NOTE: the action buttons sit in an icon toolbar under the list, the
        # same way the Organise PDF page does it, so the three file lists
        # read the same way
        toolbar = tk.Frame(frame, background=theme.SURFACE)
        toolbar.pack(fill="x", padx=14, pady=(0, 12))
        actions = (
            ("Add files", "add", self.add_merge_files),
            ("Remove", "delete", self.remove_merge_selected),
            ("Clear", "reset", self.clear_merge_files),
            ("Move Up", "up", self.move_merge_up),
            ("Move Down", "down", self.move_merge_down),
        )
        for text, glyph, command in actions:
            button = theme.toolbar_button(toolbar, text, glyph, self._glyphs)
            button.pack(side="left", padx=(0, 18))
            theme.bind_click(button, command)

        self._build_merge_output_area()
        self._sync_merge_drop_zone()

    def _build_merge_output_area(self) -> None:
        frame = theme.card(self.merge_tab)
        frame.pack(fill="x", pady=(0, 10))
        frame.columnconfigure(3, weight=1)

        ttk.Label(
            frame,
            text="Merge options",
            style="Card.TLabel",
            font=("TkDefaultFont", 10, "bold"),
        ).grid(row=0, column=0, columnspan=4, sticky="w", padx=14, pady=(8, 2))

        ttk.Label(frame, text="Output folder:", style="Card.TLabel").grid(
            row=1, column=0, sticky="w", padx=12, pady=2
        )
        # NOTE: the same-folder checkbox sits next to the folder field, so the
        # card needs one row less
        self.merge_out_var = tk.StringVar(value=str(self.config.get("merge_out_dir", "")))
        self.merge_out_entry = ttk.Entry(frame, textvariable=self.merge_out_var)
        self.merge_out_entry.grid(row=1, column=1, columnspan=2, sticky="ew", pady=4)
        self.merge_browse_button = ttk.Button(
            frame, text="Browse", command=self.pick_merge_output, style="Card.TButton"
        )
        self.merge_browse_button.grid(row=1, column=3, sticky="e", padx=(6, 14), pady=4)

        self.merge_same_folder_var = tk.BooleanVar(
            value=bool(self.config.get("merge_same_folder", True))
        )
        ttk.Checkbutton(
            frame,
            text="Output in same folder as the first file",
            variable=self.merge_same_folder_var,
            command=self._toggle_merge_same_folder,
            style="Card.TCheckbutton",
        ).grid(row=2, column=1, columnspan=3, sticky="w", pady=(0, 12))
        self._update_merge_output_state()

        action = theme.card(self.merge_tab)
        action.pack(fill="x", pady=(0, 6))
        self.merge_button = ttk.Button(
            action, text="Merge to PDF", command=self.start_merge, style="Accent.TButton"
        )
        self.merge_button.pack(side="left", padx=14, pady=12)
        self.merge_progress = ttk.Progressbar(action, mode="determinate")
        self.merge_progress.pack(side="left", fill="x", expand=True, padx=8)
        self.merge_status_var = tk.StringVar(value="Ready")
        ttk.Label(action, textvariable=self.merge_status_var, style="Card.TLabel").pack(
            side="left", padx=(0, 14)
        )

    # ---------- edit tab ----------
    def _build_organise_tab_area(self) -> None:
        """Build the standalone Organise PDF page."""
        header = theme.page_header(
            self.organise_tab,
            "Organise PDF",
            "Reorder, rotate, delete, split, or extract pages from a PDF. "
            "The original file is never overwritten.",
        )
        header.pack(anchor="w", pady=(0, 10))

        source_row = ttk.Frame(self.organise_tab, style="Card.TFrame")
        source_row.pack(fill="x", pady=(0, 10))
        self.organise_source_var = tk.StringVar(value="No PDF loaded")
        ttk.Button(
            source_row,
            text="Import PDF",
            command=self.open_edit_pdf,
            style="Accent.TButton",
        ).pack(side="left", padx=14, pady=10)
        self.organise_source_label = ttk.Label(
            source_row, textvariable=self.organise_source_var, style="Card.TLabel"
        )
        self.organise_source_label.pack(side="left", padx=14)
        self.organise_clear_button = ttk.Button(
            source_row, text="Clear", command=self.clear_edit_pdf, style="Card.TButton"
        )
        self.organise_clear_button.pack(side="right", padx=14)

        body = ttk.Frame(self.organise_tab, style="Card.TFrame")
        body.pack(fill="both", expand=True, pady=(0, 6))
        self.organise_drop_host = body
        self._build_organise_area()
        self._build_organise_split_extract_area()

    def _build_organise_split_extract_area(self) -> None:
        """Build split, extract, and the Apply row below the page organiser."""
        tools = ttk.Frame(self.organise_tab, style="Card.TFrame")
        tools.pack(fill="x")
        self._build_split_area(tools)

        # NOTE: the page list changes are only in memory until they are written.
        # Apply writes them with the same run_organise job the Edit PDF page
        # uses, so one document has one save path whichever page it came from.
        row = theme.card(self.organise_tab)
        row.pack(fill="x", pady=(2, 0))
        ttk.Button(
            row,
            text="Apply Changes",
            command=self.run_organise,
            style="Accent.TButton",
        ).pack(side="left", padx=14, pady=8)
        ttk.Label(
            row,
            text="Saves the page order, rotations and deletions as a new PDF.",
            style="CardMuted.TLabel",
        ).pack(side="left")
        self.organise_status_var = tk.StringVar(value="Ready")
        ttk.Label(
            row, textvariable=self.organise_status_var, style="Card.TLabel"
        ).pack(side="right", padx=14)



    def _build_edit_area(self) -> None:
        """Build the page organiser, visual text editor, and PDF tools."""
        header = theme.page_header(
            self.edit_tab,
            "Edit PDF",
            "Edit the text of an existing PDF: correct a line, add a text box, "
            "or redact it. Changes are saved as a new file; the original "
            "is untouched.",
        )
        header.pack(anchor="w", pady=(0, 10))

        source_row = ttk.Frame(self.edit_tab, style="Card.TFrame")
        source_row.pack(fill="x", pady=(0, 10))
        self.edit_source_var = tk.StringVar(value="No PDF loaded")
        ttk.Button(source_row, text="Import PDF", command=self.open_edit_pdf,
                   style="Accent.TButton").pack(side="left", padx=14, pady=10)
        self.edit_source_label = ttk.Label(source_row, textvariable=self.edit_source_var,
                                           style="Card.TLabel")
        self.edit_source_label.pack(side="left", padx=14)
        self.edit_window_button = ttk.Button(
            source_row, text="Open a new window", command=self._open_editor_window,
            style="Card.TButton", state="disabled",
        )
        self.edit_window_button.pack(side="right", padx=(0, 14))
        self.edit_clear_button = ttk.Button(source_row, text="Clear",
                                            command=self.clear_edit_pdf,
                                            style="Card.TButton")
        self.edit_clear_button.pack(side="right", padx=14)

        self.edit_drop = theme.dashed_drop_zone(
            self.edit_tab, height=230, on_drop=self._on_edit_drop
        )
        content = self.edit_drop.content
        self.edit_drop_badge = theme.draw_pdf_badge(64, master=self.root)
        tk.Label(content, image=self.edit_drop_badge, background=theme.SURFACE).pack(
            pady=(8, 2)
        )
        tk.Label(
            content, text="Drop PDF here or", background=theme.SURFACE,
            foreground=theme.INK, font=("TkDefaultFont", 11),
        ).pack()
        ttk.Button(
            content, text="Import PDF", command=self.open_edit_pdf,
            style="Accent.TButton",
        ).pack(pady=6)
        tk.Label(
            content, text="No PDF loaded yet.", background=theme.SURFACE,
            foreground=theme.MUTED, font=("TkDefaultFont", 9),
        ).pack()
        for widget in (self.edit_drop, content, *content.winfo_children()):
            widget.drop_target_register(DND_FILES)
            widget.dnd_bind("<<Drop>>", self._on_edit_drop)

        # NOTE: the text editor gets its own frame so it can keep its grid
        # layout (a single row that takes the spare height) while the page
        # itself is packed. Mixing pack and grid in one container is an error.
        self.visual_text_tab = tk.Frame(self.edit_tab, background=theme.CANVAS)
        self.visual_text_tab.pack(fill="both", expand=True)
        self._build_visual_text_area()
        self._build_edit_output_area()

    def _build_utilities_tab_area(self) -> None:
        """Build the standalone Utilities page using the shared edit source."""
        header = theme.page_header(
            self.utilities_tab,
            "Utilities",
            "Add watermarks or page numbers, find and replace text, or compress a PDF.",
        )
        header.pack(anchor="w", pady=(0, 10))
        source_row = ttk.Frame(self.utilities_tab, style="Card.TFrame")
        source_row.pack(fill="x", pady=(0, 10))
        self.utilities_source_var = tk.StringVar(value="No PDF loaded")
        ttk.Button(source_row, text="Import PDF", command=self.open_edit_pdf,
                   style="Accent.TButton").pack(side="left", padx=14, pady=10)
        ttk.Label(source_row, textvariable=self.utilities_source_var,
                  style="Card.TLabel").pack(side="left", padx=14)
        ttk.Button(source_row, text="Clear", command=self.clear_edit_pdf,
                   style="Card.TButton").pack(side="right", padx=14)
        self.tools_tab = ttk.Frame(self.utilities_tab)
        self.tools_tab.pack(fill="both", expand=True)
        self._build_pdf_tools_area()

    def _build_organise_area(self) -> None:
        """The drop zone, the page list, and the icon toolbar."""
        host = getattr(self, "organise_drop_host", None) or self.organise_tab
        # ---- the drop zone shown when no PDF is loaded ----
        self.organise_drop = theme.card(host)
        zone = theme.dashed_drop_zone(
            self.organise_drop,
            height=260,
            on_drop=self._on_edit_drop,
        )
        zone.pack(fill="both", expand=True)
        # the badge and the button live in the overlay frame, so they sit
        # inside the dashed outline
        content = zone.content
        badge = theme.draw_pdf_badge(78, master=self.root)
        self.organise_badge = badge
        tk.Label(content, image=badge, background=theme.SURFACE).pack(pady=(12, 4))
        tk.Label(
            content,
            text="Drop PDF here or",
            background=theme.SURFACE,
            foreground=theme.INK,
            font=("TkDefaultFont", 11),
        ).pack()
        ttk.Button(
            content,
            text="Import PDF",
            command=self.open_edit_pdf,
            style="Accent.TButton",
        ).pack(pady=8)
        self.organise_drop_hint = tk.Label(
            content,
            text="No PDF loaded yet.",
            background=theme.SURFACE,
            foreground=theme.MUTED,
            font=("TkDefaultFont", 9),
        )
        self.organise_drop_hint.pack()

        # ---- the page list ----
        self.organise_pages = theme.card(host)
        frame = self.organise_pages
        ttk.Label(
            frame,
            text="Pages (drag to reorder)",
            style="Card.TLabel",
            font=("TkDefaultFont", 10, "bold"),
        ).pack(anchor="w", padx=14, pady=(12, 4))

        body = ttk.Frame(frame, style="Card.TFrame")
        body.pack(fill="both", expand=True, padx=14, pady=(0, 10))

        # NOTE: the list takes a fixed share of the card rather than every spare
        # pixel. With expand=True it grew until the Apply row and the log button
        # were pushed off the bottom of the tab, which is what the old grid
        # layout was guarding against.
        self.page_list = tk.Listbox(body, height=5, selectmode="extended")
        self.page_list.pack(side="left", fill="both", expand=True, pady=(0, 2))
        self.page_list.bind("<Button-1>", self._on_page_drag_start, add="+")
        self.page_list.bind("<B1-Motion>", self._on_page_drag_motion)
        self.page_list.bind("<ButtonRelease-1>", self._on_page_drag_drop)
        scroll = ttk.Scrollbar(body, command=self.page_list.yview)
        scroll.pack(side="left", fill="y", pady=(0, 2))
        self.page_list.configure(yscrollcommand=scroll.set)

        # ---- the icon toolbar ----
        toolbar = tk.Frame(frame, background=theme.SURFACE)
        toolbar.pack(fill="x", padx=14, pady=(0, 12))
        actions = (
            ("Move Up", "up", self.move_page_up),
            ("Move Down", "down", self.move_page_down),
            ("Rotate Left", "rotate_left", self.rotate_page_ccw),
            ("Rotate Right", "rotate_right", self.rotate_page_cw),
            ("Rotate 180", "rotate_180", self.rotate_page_180),
            ("Delete Page", "delete", self.delete_page),
            ("Reset", "reset", self.reset_pages),
        )
        for text, glyph, command in actions:
            button = theme.toolbar_button(toolbar, text, glyph, self._glyphs)
            button.pack(side="left", padx=(0, 18))
            theme.bind_click(button, command)

        # NOTE: rotate/delete act on the SELECTED rows, so an empty selection
        # must say so instead of looking like a dead button
        self.page_hint_var = tk.StringVar(
            value="Select a page, then use the buttons."
        )
        ttk.Label(
            host, textvariable=self.page_hint_var, style="CardMuted.TLabel"
        ).pack(anchor="w", pady=(0, 8))

    def _build_edit_output_area(self) -> None:
        frame = theme.card(self.edit_tab)
        self.edit_output_frame = frame
        # NOTE: expand=True hands the window's spare height to the text editor,
        # which is packed above; a plain fill="x" row would swallow it instead
        # and the page viewer would never grow on a taller window.
        frame.pack(fill="x", expand=True, pady=(0, 10))
        frame.columnconfigure(3, weight=1)

        ttk.Label(
            frame,
            text="Edit options",
            style="Card.TLabel",
            font=("TkDefaultFont", 10, "bold"),
        ).grid(row=0, column=0, columnspan=4, sticky="w", padx=14, pady=(10, 6))

        ttk.Label(frame, text="Output folder:", style="Card.TLabel").grid(
            row=1, column=0, sticky="w", padx=12, pady=2
        )
        self.edit_out_var = tk.StringVar(value=str(self.config.get("edit_out_dir", "")))
        # NOTE: entry and button are kept as attributes so the "Output in same
        # folder" checkbox can disable both together (same pattern as the
        # Convert File and Merge PDF tabs)
        self.edit_out_entry = ttk.Entry(frame, textvariable=self.edit_out_var)
        self.edit_out_entry.grid(row=1, column=1, columnspan=2, sticky="ew", pady=4)
        self.edit_browse_button = ttk.Button(
            frame, text="Browse", command=self.pick_edit_output, style="Card.TButton"
        )
        self.edit_browse_button.grid(row=1, column=3, sticky="e", padx=(6, 14), pady=4)

        self.edit_same_folder_var = tk.BooleanVar(
            value=bool(self.config.get("edit_same_folder", True))
        )
        ttk.Checkbutton(
            frame,
            text="Output in same folder",
            variable=self.edit_same_folder_var,
            command=self._toggle_edit_same_folder,
            style="Card.TCheckbutton",
        ).grid(row=1, column=3, sticky="w", pady=(0, 8))
        self._update_edit_output_state()

        # NOTE: the Apply row lives inside the Edit options card, so the tab
        # has one row fewer and the document editor gets the height back
        action = frame
        self.edit_apply_button = ttk.Button(
            action,
            text="Apply Changes",
            command=self.run_organise,
            style="Accent.TButton",
        )
        self.edit_apply_button.grid(row=3, column=0, sticky="w", padx=14, pady=(8, 10))
        ttk.Label(
            action,
            text="  Saves the page changes and the text edits as one new PDF.",
            style="CardMuted.TLabel",
        ).grid(row=3, column=1, sticky="w", pady=(8, 10))
        self.edit_progress = ttk.Progressbar(action, mode="determinate")
        self.edit_progress.grid(row=3, column=2, sticky="ew", padx=8, pady=(8, 10))
        self.edit_status_var = tk.StringVar(value="Ready")
        ttk.Label(action, textvariable=self.edit_status_var, style="Card.TLabel").grid(
            row=3, column=3, sticky="e", padx=(8, 14), pady=(8, 10)
        )

    def _build_pdf_tools_area(self) -> None:
        self.tools_tab.columnconfigure(0, weight=1, uniform="tools")
        self.tools_tab.columnconfigure(1, weight=1, uniform="tools")
        left = ttk.Frame(self.tools_tab)
        left.grid(row=0, column=0, sticky="nsew", padx=(6, 3))
        right = ttk.Frame(self.tools_tab)
        right.grid(row=0, column=1, sticky="nsew", padx=(3, 6))
        # NOTE: split and extract moved to the Organise PDF page, which owns the
        # page list they act on
        self._build_replace_area(left)
        self._build_stamp_area(right)
        self._build_compress_area(right)

    def _build_split_area(self, parent: ttk.Frame) -> None:
        """Split and extract, side by side in one card.

        NOTE: they are two halves of one job - take pages out of the document -
        so they share a card and a row. Stacking them vertically cost ~110 px
        that the page list needs on a short window.
        """
        frame = theme.card(parent)
        frame.pack(fill="x", pady=(0, 4))
        frame.columnconfigure(0, weight=1, uniform="split")
        frame.columnconfigure(1, weight=1, uniform="split")

        split = ttk.Frame(frame, style="Card.TFrame")
        split.grid(row=0, column=0, sticky="nsew", padx=(14, 8), pady=(6, 6))
        ttk.Label(
            split,
            text="Split every N pages",
            style="Card.TLabel",
            font=("TkDefaultFont", 10, "bold"),
        ).grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 4))
        ttk.Label(split, text="Pages per file:", style="Card.TLabel").grid(
            row=1, column=0, sticky="w"
        )
        self.split_every_var = tk.StringVar(value="1")
        ttk.Spinbox(
            split, from_=1, to=1000, width=6, textvariable=self.split_every_var
        ).grid(row=1, column=1, sticky="w", padx=(4, 0))
        ttk.Button(
            split, text="Split PDF", command=self.run_split, style="Card.TButton"
        ).grid(row=1, column=2, sticky="w", padx=(8, 0))
        ttk.Label(
            split,
            text="One output file per chunk.",
            style="CardMuted.TLabel",
        ).grid(row=2, column=0, columnspan=3, sticky="w", pady=(2, 0))

        extract = ttk.Frame(frame, style="Card.TFrame")
        extract.grid(row=0, column=1, sticky="nsew", padx=(8, 14), pady=(6, 6))
        ttk.Label(
            extract,
            text="Extract a page range",
            style="Card.TLabel",
            font=("TkDefaultFont", 10, "bold"),
        ).grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 4))
        ttk.Label(extract, text="Pages:", style="Card.TLabel").grid(
            row=1, column=0, sticky="w"
        )
        self.extract_pages_var = tk.StringVar(value="")
        ttk.Entry(extract, textvariable=self.extract_pages_var, width=12).grid(
            row=1, column=1, sticky="w", padx=(4, 0)
        )
        ttk.Button(
            extract, text="Extract", command=self.run_extract, style="Card.TButton"
        ).grid(row=1, column=2, sticky="w", padx=(8, 0))
        ttk.Label(
            extract,
            text="1-based, e.g. 1-3,5; kept in the given order.",
            style="CardMuted.TLabel",
        ).grid(row=2, column=0, columnspan=3, sticky="w", pady=(2, 0))

    def _build_stamp_area(self, parent: ttk.Frame) -> None:
        mark = theme.card(parent)
        mark.pack(fill="x", pady=(0, 6))
        ttk.Label(
            mark,
            text="Watermark",
            style="Card.TLabel",
            font=("TkDefaultFont", 10, "bold"),
        ).grid(row=0, column=0, columnspan=4, sticky="w", padx=12, pady=(8, 3))
        ttk.Label(mark, text="Text:", style="Card.TLabel").grid(
            row=1, column=0, sticky="w", padx=12, pady=2
        )
        self.watermark_var = tk.StringVar(value="CONFIDENTIAL")
        ttk.Entry(mark, textvariable=self.watermark_var, width=18).grid(
            row=1, column=1, columnspan=2, sticky="w", padx=(4, 0), pady=2
        )
        self.watermark_diagonal_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            mark,
            text="Diagonal",
            variable=self.watermark_diagonal_var,
            style="Card.TCheckbutton",
        ).grid(row=2, column=1, sticky="w", padx=(4, 0), pady=(0, 10))
        ttk.Button(
            mark, text="Add Watermark", command=self.run_watermark, style="Card.TButton"
        ).grid(row=1, column=3, sticky="w", padx=8, pady=2)

        numbers = theme.card(parent)
        numbers.pack(fill="x", pady=(0, 6))
        ttk.Label(
            numbers,
            text="Page numbers",
            style="Card.TLabel",
            font=("TkDefaultFont", 10, "bold"),
        ).grid(row=0, column=0, columnspan=4, sticky="w", padx=12, pady=(8, 3))
        ttk.Label(numbers, text="Pattern:", style="Card.TLabel").grid(
            row=1, column=0, sticky="w", padx=12, pady=2
        )
        self.number_pattern_var = tk.StringVar(value="Page {page} of {total}")
        ttk.Entry(numbers, textvariable=self.number_pattern_var, width=18).grid(
            row=1, column=1, columnspan=2, sticky="w", padx=(4, 0), pady=2
        )
        ttk.Label(numbers, text="Position:", style="Card.TLabel").grid(
            row=2, column=0, sticky="w", padx=12, pady=2
        )
        self.number_position_var = tk.StringVar(value="bottom-centre")
        ttk.Combobox(
            numbers,
            textvariable=self.number_position_var,
            state="readonly",
            width=16,
            values=["bottom-centre", "bottom-right", "bottom-left", "top-right", "top-centre"],
        ).grid(row=2, column=1, sticky="w", padx=(4, 0), pady=2)
        ttk.Button(
            numbers, text="Add Numbers", command=self.run_page_numbers, style="Card.TButton"
        ).grid(row=1, column=3, rowspan=2, sticky="w", padx=8, pady=2)
        ttk.Label(
            numbers,
            text="  {page} = number, {total} = page count.",
            style="CardMuted.TLabel",
        ).grid(row=3, column=0, columnspan=4, sticky="w", padx=12, pady=(2, 8))

    def _build_compress_area(self, parent: ttk.Frame) -> None:
        """The Compress PDF card: quality, optional downsampling, and grayscale."""
        frame = theme.card(parent)
        frame.pack(fill="x", pady=(0, 6))
        ttk.Label(
            frame,
            text="Compress PDF",
            style="Card.TLabel",
            font=("TkDefaultFont", 10, "bold"),
        ).grid(row=0, column=0, columnspan=3, sticky="w", padx=12, pady=(8, 3))
        ttk.Label(frame, text="Image quality:", style="Card.TLabel").grid(
            row=1, column=0, sticky="w", padx=12, pady=2
        )
        self.compress_quality_var = tk.StringVar(value="75")
        ttk.Spinbox(
            frame, from_=10, to=95, width=6, textvariable=self.compress_quality_var
        ).grid(row=1, column=1, sticky="w", padx=(4, 0), pady=2)
        ttk.Label(frame, text="Downsample:", style="Card.TLabel").grid(
            row=2, column=0, sticky="w", padx=12, pady=2
        )
        # NOTE: "Off" keeps the original pixels and only re-encodes the images,
        # which is the safe choice for a document that is mostly text
        self.compress_dpi_var = tk.StringVar(value="Off")
        ttk.Combobox(
            frame,
            textvariable=self.compress_dpi_var,
            state="readonly",
            width=10,
            values=["Off", "72 dpi", "96 dpi", "150 dpi", "200 dpi", "300 dpi"],
        ).grid(row=2, column=1, sticky="w", padx=(4, 0), pady=2)
        self.compress_grayscale_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            frame,
            text="Grayscale images",
            variable=self.compress_grayscale_var,
            style="Card.TCheckbutton",
        ).grid(row=3, column=1, sticky="w", padx=(4, 0), pady=(0, 2))
        ttk.Button(
            frame, text="Compress PDF", command=self.run_compress, style="Card.TButton"
        ).grid(row=1, column=2, rowspan=3, sticky="n", padx=8, pady=2)
        ttk.Label(
            frame,
            text="  Re-packs the page streams and re-encodes images; the result is a new file.",
            style="CardMuted.TLabel",
        ).grid(row=4, column=0, columnspan=3, sticky="w", padx=12, pady=(2, 8))

    def _build_visual_text_area(self) -> None:
        # NOTE: the tab is laid out with GRID, not pack, so the viewer row can
        # take every spare pixel. With pack the canvas kept its requested
        # height and the document was squeezed into a short strip.
        self.visual_text_tab.columnconfigure(0, weight=1)
        self.visual_text_tab.rowconfigure(2, weight=1)

        viewer = ttk.Frame(self.visual_text_tab)
        viewer.grid(row=2, column=0, sticky="nsew", padx=6, pady=2)
        viewer.rowconfigure(0, weight=1)
        viewer.columnconfigure(0, weight=1)

        nav = ttk.Frame(self.visual_text_tab)
        nav.grid(row=0, column=0, sticky="ew", padx=6, pady=(4, 2))
        font_row = ttk.Frame(self.visual_text_tab)
        font_row.grid(row=1, column=0, sticky="ew", padx=6, pady=(0, 2))
        self.visual_text_page_var = tk.StringVar(value="Page 0 of 0")
        self.visual_text_prev = ttk.Button(
            nav, text="◀", width=3, command=lambda: self._navigate_visual_text(-1)
        )
        self.visual_text_prev.grid(row=0, column=0)
        ttk.Label(nav, textvariable=self.visual_text_page_var).grid(row=0, column=1, padx=8)
        self.visual_text_next = ttk.Button(
            nav, text="▶", width=3, command=lambda: self._navigate_visual_text(1)
        )
        self.visual_text_next.grid(row=0, column=2, padx=(0, 8))
        self.text_undo_button = ttk.Button(
            nav, text="↶", width=3, command=self._undo_text_edit, state="disabled"
        )
        self.text_undo_button.grid(row=0, column=3, padx=(4, 0), sticky="ew")
        self.text_redo_button = ttk.Button(
            nav, text="↷", width=3, command=self._redo_text_edit, state="disabled"
        )
        self.text_redo_button.grid(row=0, column=4, padx=(4, 0), sticky="ew")

        ttk.Label(nav, text="Zoom:").grid(row=0, column=5, padx=(12, 0))
        ttk.Button(
            nav, text="−", width=3, command=lambda: self._zoom_viewer(-1)
        ).grid(row=0, column=6, padx=(4, 0), sticky="ew")
        self.viewer_zoom_var = tk.StringVar(value="100%")
        ttk.Label(nav, textvariable=self.viewer_zoom_var, width=6, anchor="center").grid(
            row=0, column=7, padx=4
        )
        ttk.Button(
            nav, text="+", width=3, command=lambda: self._zoom_viewer(1)
        ).grid(row=0, column=8, padx=(4, 0), sticky="ew")
        ttk.Button(nav, text="Fit", command=self._zoom_fit_viewer).grid(
            row=0, column=9, padx=(8, 0)
        )
        ttk.Label(nav, text="Ctrl+wheel zooms", foreground="#555").grid(
            row=0, column=10, padx=(10, 0)
        )
        for column in (3, 4, 6, 8):
            nav.columnconfigure(column, uniform="edit-icons")

        # NOTE: the canvas asks for a good chunk of height, so the notebook
        # (which is as tall as its tallest tab) grows to give the document the
        # room it needs, and the Edit tab's grid hands the slack to it.
        self.visual_text_canvas = tk.Canvas(
            viewer, background="#e2e7ee", highlightthickness=0, height=200
        )
        self.visual_text_canvas.grid(row=0, column=0, sticky="nsew")
        horizontal = ttk.Scrollbar(
            viewer, orient="horizontal", command=self.visual_text_canvas.xview
        )
        horizontal.grid(row=1, column=0, sticky="ew")
        vertical = ttk.Scrollbar(
            viewer, orient="vertical", command=self.visual_text_canvas.yview
        )
        vertical.grid(row=0, column=1, sticky="ns")
        self.visual_text_canvas.configure(
            xscrollcommand=horizontal.set, yscrollcommand=vertical.set
        )
        self.visual_text_canvas.bind("<Configure>", lambda _event: self._center_viewer())
        self.visual_text_canvas.bind("<Button-1>", self._visual_text_click)
        self.visual_text_canvas.bind("<B1-Motion>", self._drag_placed_text)
        self.visual_text_canvas.bind("<ButtonRelease-1>", self._end_text_drag)
        self.visual_text_canvas.drop_target_register(DND_FILES)
        self.visual_text_canvas.dnd_bind("<<Drop>>", self._on_edit_drop)
        # NOTE: the wheel scrolls the page, and Ctrl+wheel zooms, so a long
        # document can be read without reaching for the scrollbar
        self.visual_text_canvas.bind("<MouseWheel>", self._on_viewer_wheel)
        self.visual_text_canvas.bind("<Button-4>", self._on_viewer_wheel)
        self.visual_text_canvas.bind("<Button-5>", self._on_viewer_wheel)
        self.visual_text_canvas.tag_bind(
            "placed-text-border", "<Enter>", self._on_text_box_border_enter
        )
        self.visual_text_canvas.tag_bind(
            "placed-text-border", "<Leave>", self._on_text_box_border_leave
        )

        # NOTE: the box tools and the font share one row, so the page viewer
        # keeps the space that two separate rows would have taken from it
        ttk.Button(font_row, text="Add Text Box", command=self._add_text_box).pack(
            side="left"
        )
        ttk.Button(font_row, text="Remove Box", command=self._remove_text_box).pack(
            side="left", padx=4
        )
        ttk.Label(font_row, text="Font:").pack(side="left", padx=(6, 2))
        default_font = next((name for name in self.system_fonts if name.casefold() == "arial"), "")
        self.text_font_var = tk.StringVar(value=default_font or next(iter(self.system_fonts), ""))
        self.text_font_box = ttk.Combobox(
            font_row, textvariable=self.text_font_var, values=list(self.system_fonts), width=14
        )
        self.text_font_box.pack(side="left")
        ttk.Label(font_row, text="Size:").pack(side="left", padx=(6, 2))
        self.add_text_size_var = tk.StringVar(value="14")
        self.text_size_box = ttk.Spinbox(
            font_row, from_=4, to=200, width=5, textvariable=self.add_text_size_var
        )
        self.text_size_box.pack(side="left")
        self.text_font_hint_var = tk.StringVar(value="Choose an installed font.")
        ttk.Label(
            font_row, textvariable=self.text_font_hint_var, foreground="#555"
        ).pack(side="left", padx=(10, 0))

        editor = ttk.Frame(self.visual_text_tab)
        editor.grid(row=3, column=0, sticky="ew", padx=6, pady=(2, 2))
        ttk.Label(editor, text="Text:").pack(side="left")
        self.visual_text_var = tk.StringVar()
        # NOTE: a scrollable multi-line text box, so a long replacement can be
        # typed and reviewed without the one-line entry hiding the rest.
        # tk.Text has no textvariable, so the variable and the box are kept in
        # step by the trace below.
        self.visual_text_entry = tk.Text(
            editor,
            height=3,
            wrap="word",
            relief="solid",
            borderwidth=1,
            highlightthickness=0,
            background=theme.SURFACE,
            foreground=theme.INK,
        )
        self.visual_text_entry.pack(side="left", fill="x", expand=True, padx=6)
        entry_scroll = ttk.Scrollbar(
            editor, orient="vertical", command=self.visual_text_entry.yview
        )
        entry_scroll.pack(side="left", fill="y")
        self.visual_text_entry.configure(yscrollcommand=entry_scroll.set)
        # the on-canvas box is a separate widget, so it carries its own text
        self.placed_text_entry = tk.Text(
            self.visual_text_canvas,
            height=1,
            wrap="word",
            relief="flat",
            borderwidth=0,
            background=theme.SURFACE,
            foreground=theme.INK,
        )
        self.placed_text_entry.drop_target_register(DND_FILES)
        self.placed_text_entry.dnd_bind("<<Drop>>", self._on_edit_drop)
        # NOTE: typing in the on-canvas box updates the item straight away, and
        # the box scrolls when the text is longer than the box on the page
        self.placed_text_entry.bind("<<Modified>>", self._on_placed_text_change)
        self.placed_text_entry.bind(
            "<MouseWheel>",
            lambda event: self._scroll_placed_text(event),
            add="+",
        )
        self.placed_text_entry.bind(
            "<Button-4>",
            lambda event: self._scroll_placed_text(event),
            add="+",
        )
        self.placed_text_entry.bind(
            "<Button-5>",
            lambda event: self._scroll_placed_text(event),
            add="+",
        )
        # NOTE: the Text widget covers the box on the page, so a press on it
        # must also start a move; otherwise the box could not be dragged by its
        # middle, only by the dashed border.
        self.placed_text_entry.bind(
            "<B1-Motion>", lambda event: self._drag_from_widget(event), add="+"
        )
        self.placed_text_entry.bind(
            "<ButtonRelease-1>", lambda event: self._end_text_drag(event), add="+"
        )
        # NOTE: a press inside the Text widget (the box's own middle) selects
        # the box and arms a move. Without this the canvas never saw the click
        # - the widget swallows it - which is why Remove Box appeared dead.
        self.placed_text_entry.bind("<Button-1>", self._on_box_text_press, add="+")
        self.visual_text_entry.configure(state="disabled")
        line_actions = ttk.Frame(editor)
        line_actions.pack(side="left", padx=(6, 0))
        self.visual_text_queue_button = ttk.Button(
            line_actions,
            text="Queue Change",
            command=self._queue_visual_text_change,
            state="disabled",
        )
        self.visual_text_queue_button.pack(fill="x")
        self.visual_text_redact_button = ttk.Button(
            line_actions,
            text="Redact Line",
            command=self._queue_visual_text_redact,
            state="disabled",
        )
        self.visual_text_redact_button.pack(fill="x", pady=(2, 0))
        # NOTE: the box and the variable are kept in step both ways: typing in
        # the box updates the variable, and setting the variable (for a
        # selected line or box) rewrites the box
        self.visual_text_entry.bind("<<Modified>>", self._on_editor_text_change)
        self.visual_text_var.trace_add("write", self._on_text_var_change)
        for variable in (self.text_font_var, self.add_text_size_var):
            variable.trace_add("write", self._on_style_change)
        for widget in (
            self.visual_text_canvas, self.visual_text_entry, self.placed_text_entry,
            self.text_font_box, self.text_size_box,
        ):
            widget.bind("<Control-z>", self._undo_text_edit)
            widget.bind("<Control-y>", self._redo_text_edit)
            widget.bind("<Control-Shift-Z>", self._redo_text_edit)

        footer = ttk.Frame(self.visual_text_tab)
        footer.grid(row=4, column=0, sticky="ew", padx=6, pady=(0, 6))
        self.visual_text_status_var = tk.StringVar(
            value="Open a PDF, then click a text line to select it."
        )
        ttk.Label(
            footer,
            textvariable=self.visual_text_status_var,
            foreground="#555",
        ).pack(side="left", fill="x", expand=True)
        # NOTE: there is no separate save button here. The Apply button in the
        # Edit options block writes the page changes AND the text corrections
        # into one new file, so a second save button would only duplicate it.

    def _build_replace_area(self, parent: ttk.Frame) -> None:
        repl = theme.card(parent)
        repl.pack(fill="x", pady=(0, 6))
        ttk.Label(
            repl,
            text="Find and replace",
            style="Card.TLabel",
            font=("TkDefaultFont", 10, "bold"),
        ).grid(row=0, column=0, columnspan=3, sticky="w", padx=12, pady=(8, 3))
        ttk.Label(repl, text="Find:", style="Card.TLabel").grid(
            row=1, column=0, sticky="w", padx=12, pady=2
        )
        self.find_var = tk.StringVar(value="")
        ttk.Entry(repl, textvariable=self.find_var, width=18).grid(
            row=1, column=1, sticky="ew", pady=4
        )
        ttk.Label(repl, text="Replace:", style="Card.TLabel").grid(
            row=2, column=0, sticky="w", padx=12, pady=2
        )
        self.replace_var = tk.StringVar(value="")
        ttk.Entry(repl, textvariable=self.replace_var, width=18).grid(
            row=2, column=1, sticky="ew", pady=4
        )
        self.find_case_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            repl,
            text="Match case",
            variable=self.find_case_var,
            style="Card.TCheckbutton",
        ).grid(row=3, column=1, sticky="w", padx=(4, 0), pady=(0, 4))
        ttk.Button(
            repl, text="Find", command=self.run_find_text, style="Card.TButton"
        ).grid(row=1, column=2, sticky="w", padx=8, pady=1)
        ttk.Button(
            repl, text="Replace All", command=self.run_replace_text, style="Card.TButton"
        ).grid(row=2, column=2, sticky="w", padx=8, pady=2)
        self.find_result_var = tk.StringVar(value="")
        ttk.Label(repl, textvariable=self.find_result_var, style="CardMuted.TLabel").grid(
            row=4, column=0, columnspan=3, sticky="w", padx=12, pady=(0, 8)
        )

    def _build_about_area(self) -> None:
        theme.page_header(
            self.about_tab,
            "About",
            "Portable PDF converter and OCR toolbox.",
        ).pack(anchor="w", pady=(0, 10))

        card = theme.card(self.about_tab)
        card.pack(fill="x", pady=(0, 10))

        info = ttk.Frame(card, style="Card.TFrame")
        info.pack(anchor="w", padx=14, pady=(14, 10))
        ttk.Label(
            info, text="Author:", style="Card.TLabel", font=("TkDefaultFont", 10, "bold")
        ).grid(row=0, column=0, sticky="w", pady=2)
        ttk.Label(info, text=__author__, style="Card.TLabel").grid(
            row=0, column=1, sticky="w", padx=(8, 0), pady=2
        )
        ttk.Label(
            info, text="Version:", style="Card.TLabel", font=("TkDefaultFont", 10, "bold")
        ).grid(row=1, column=0, sticky="w", pady=2)
        ttk.Label(info, text=__version__, style="Card.TLabel").grid(
            row=1, column=1, sticky="w", padx=(8, 0), pady=2
        )
        # NOTE: the README link sits directly under the version line so the
        # release notes for this build are one click away
        readme_link = tk.Label(
            info,
            text="Readme",
            fg=theme.ACCENT,
            background=theme.SURFACE,
            cursor="hand2",
            font=("TkDefaultFont", 9, "underline"),
        )
        readme_link.grid(row=2, column=0, columnspan=2, sticky="w", pady=(2, 2))
        readme_link.bind("<Button-1>", self._open_readme_link)
        ttk.Label(
            info,
            text="No upload, no network, no admin rights: everything runs offline.",
            style="CardMuted.TLabel",
        ).grid(row=3, column=0, columnspan=2, sticky="w", pady=(8, 2))

        coffee = ttk.Frame(self.about_tab)
        coffee.pack(side="bottom", anchor="w", pady=(0, 10))
        ttk.Label(coffee, text="Like what I built? Consider ").pack(side="left")
        coffee_link = tk.Label(
            coffee,
            text="buying me a cuppa",
            fg=theme.ACCENT,
            background=theme.CANVAS,
            cursor="hand2",
            font=("TkDefaultFont", 9, "underline"),
        )
        coffee_link.pack(side="left")
        coffee_link.bind("<Button-1>", self._open_coffee_link)
        ttk.Label(coffee, text="!").pack(side="left")

    # ---------- file selection ----------

    def _drop_paths(self, event) -> list[str]:
        """The file paths carried by a drag-and-drop event."""
        return drop_paths(event)

    def _on_file_drop(self, event) -> None:
        paths = self._drop_paths(event)
        self._add_paths([Path(path) for path in paths])
    def add_files(self) -> None:
        paths = filedialog.askopenfilenames(
            title="Select files",
            # NOTE: reopen where the user last imported from
            initialdir=self._dialog_dir(),
            filetypes=[
                ("Supported files",
                 "*.pdf *.png *.jpg *.jpeg *.bmp *.webp *.tif *.tiff *.gif "
                 "*.md *.markdown *.txt *.doc *.docx *.xls *.xlsx *.ppt *.pptx "
                 "*.odt *.ods *.odp *.rtf *.csv"),
                ("PDF", "*.pdf"),
                ("Images", "*.png *.jpg *.jpeg *.bmp *.webp *.tif *.tiff *.gif"),
                ("Text", "*.md *.markdown *.txt"),
                ("Office", "*.doc *.docx *.xls *.xlsx *.ppt *.pptx *.odt *.ods *.odp *.rtf *.csv"),
                ("All files", "*.*"),
            ],
        )
        self._add_paths([Path(p) for p in paths])

    # ---------- edit tab logic ----------

    @staticmethod
    def page_labels(pages: list[int], rotations: dict[int, int]) -> list[str]:
        """The Organise list as shown: "1. Page 3  [rotated 90\u00b0 \u21bb]".

        NOTE: the leading number is the POSITION in the new document; the page
        number and an explicit rotation tag follow it. The tag names the
        direction so a turned page is obvious at a glance. Pure, so the rule is
        unit-testable without a display.
        """
        labels: list[str] = []
        for position, source_page in enumerate(pages, start=1):
            angle = rotations.get(source_page, 0) % 360
            if angle == 0:
                tag = ""
            elif angle == 90:
                tag = "  [rotated 90\u00b0 \u21bb]"
            elif angle == 180:
                tag = "  [rotated 180\u00b0]"
            else:  # 270
                tag = "  [rotated 90\u00b0 \u21ba]"
            labels.append(f"{position}. Page {source_page}{tag}")
        return labels

    def open_edit_pdf(self) -> None:
        paths = filedialog.askopenfilenames(
            title="Import a PDF to edit",
            initialdir=self._dialog_dir(),
            filetypes=[("PDF", "*.pdf"), ("All files", "*.*")],
        )
        if not paths:
            return
        source = Path(paths[0])
        try:
            count = pdf_edit.page_count(source)
        except ConversionError as exc:
            messagebox.showerror("PDF-X", str(exc))
            return
        self._reset_edit_session(source, count)
        self._load_visual_text_page()
        self._warn_if_not_searchable()

    def _on_edit_drop(self, event) -> None:
        """Load a PDF dropped onto the Edit PDF drop zone."""
        paths = self._drop_paths(event)
        if not paths:
            return
        source = Path(paths[0])
        try:
            count = pdf_edit.page_count(source)
        except ConversionError as exc:
            messagebox.showerror("PDF-X", str(exc), parent=self._edit_dialog_parent())
            return
        self._reset_edit_session(source, count)
        self._load_visual_text_page()
        self._warn_if_not_searchable()

    def _reset_edit_session(self, source: Path | None, count: int) -> None:
        """Point the tab at ``source`` (or at nothing when it is None).

        NOTE: every piece of per-file text-editing state is dropped here, so a
        fresh import and Clear cannot leave edits, undo history, or a stale
        preview pointing at a different file.
        """
        if source is None and getattr(self, "_editor_window_open", False):
            self._close_editor_window()
        self.edit_source = source
        window_button = getattr(self, "edit_window_button", None)
        if window_button is not None:
            window_button.configure(state="normal" if source is not None else "disabled")
        self.edit_pages = list(range(1, count + 1))
        self.edit_rotations = {}
        self.visual_text_page = 1
        self.visual_text_total_pages = count
        self._visual_text_ocr_warning_shown = False
        self.visual_text_edits.clear()
        getattr(self, "redacted_visual_text", {}).clear()
        self.visual_text_fonts.clear()
        self.visual_text_sizes.clear()
        self.placed_text.clear()
        self.selected_placed_text = None
        self.selected_visual_text = None
        if source is None:
            self.edit_source_var.set("No PDF loaded")
            self._set_organise_source("No PDF loaded")
            self._set_organise_status("No PDF loaded")
            self.visual_text_lines = []
            # NOTE: dropping the PhotoImage reference frees the preview; the
            # canvas is emptied first so nothing can be drawn from the old page
            self.visual_text_image = None
            self.visual_text_canvas.delete("all")
            self.visual_text_canvas.configure(scrollregion=(0, 0, 0, 0))
            self.visual_text_status_var.set(
                "No PDF loaded. Use Import PDF to choose a file."
            )
            self.edit_status_var.set("No PDF loaded")
            self._show_drop_zone(True)
        else:
            self.edit_source_var.set(f"{source.name}  ({count} pages)")
            if getattr(self, "_editor_window_open", False):
                self.root.tk.call(
                    "wm", "title", self.visual_text_tab._w, f"PDF-X - Edit PDF - {source.name}"
                )
            self._set_organise_source(f"{source.name}  ({count} pages)")
            self._set_organise_status("Ready")
            self._remember_dir(source.resolve().parent)
            self._remember_recent(source)
            self.edit_status_var.set("Ready")
            self._show_drop_zone(False)
        self._refresh_page_list()
        self.visual_text_var.set("")
        self.visual_text_entry.configure(state="disabled")
        self.visual_text_queue_button.configure(state="disabled")
        self._text_undo.clear()
        self._text_redo.clear()
        self._sync_text_history()
        self._update_visual_text_nav()

    def _set_organise_source(self, text: str) -> None:
        for attr in ("organise_source_var", "utilities_source_var"):
            var = getattr(self, attr, None)
            if var is not None:
                var.set(text)

    def _set_organise_status(self, text: str) -> None:
        var = getattr(self, "organise_status_var", None)
        if var is not None:
            var.set(text)

    def _show_drop_zone(self, visible: bool) -> None:
        """Show the drop zone when no PDF is loaded, the page list once one is.

        NOTE: the drop zone is the mockup's empty state, so it is only useful
        while there is nothing to edit. Once a file is open the page list and
        the toolbar take the space instead.
        """
        edit_drop = getattr(self, "edit_drop", None)
        editor = getattr(self, "visual_text_tab", None)
        if edit_drop is not None and editor is not None:
            if visible:
                editor.pack_forget()
                edit_drop.pack(fill="both", expand=True, before=self.edit_output_frame)
            else:
                edit_drop.pack_forget()
                if not getattr(self, "_editor_window_open", False):
                    editor.pack(fill="both", expand=True, before=self.edit_output_frame)
        zone = getattr(self, "organise_drop", None)
        pages = getattr(self, "organise_pages", None)
        if zone is None or pages is None:
            return
        if visible:
            # the page list is packed first so it keeps the place in the
            # packing order, then the drop zone takes its slot
            pages.pack(fill="both", expand=True)
            zone.pack(fill="both", expand=True, before=pages)
            pages.pack_forget()
            self.organise_drop_hint.configure(text="No PDF loaded yet.")
        else:
            zone.pack_forget()
            pages.pack(fill="both", expand=True)

    def _open_editor_window(self) -> None:
        """Move the existing editor into a larger, separate window."""
        if self.edit_source is None:
            return
        if getattr(self, "_editor_window_open", False):
            self.root.tk.call("raise", self.visual_text_tab._w)
            return
        self._on_editor_text_change()
        if self.selected_placed_text is not None:
            self._on_placed_text_change()
        editor = self.visual_text_tab
        try:
            self.root.tk.call("wm", "manage", editor._w)
        except tk.TclError as exc:
            messagebox.showerror("PDF-X", f"Cannot open editor window: {exc}")
            return
        self._editor_window_open = True
        self.root.tk.call("wm", "title", editor._w, f"PDF-X - Edit PDF - {self.edit_source.name}")
        self.root.tk.call("wm", "minsize", editor._w, 800, 600)
        self._editor_window_close_command = self.root.register(self._close_editor_window)
        self.root.tk.call(
            "wm", "protocol", editor._w, "WM_DELETE_WINDOW",
            self._editor_window_close_command,
        )

        actions = ttk.Frame(editor)
        self._expanded_editor_actions = actions
        actions.grid(row=5, column=0, sticky="ew", padx=6, pady=(0, 8))
        actions.columnconfigure(1, weight=1)
        ttk.Label(actions, text="Output folder:").grid(row=0, column=0, sticky="w")
        self._expanded_output_entry = ttk.Entry(actions, textvariable=self.edit_out_var)
        self._expanded_output_entry.grid(row=0, column=1, sticky="ew", padx=6)
        self._expanded_browse_button = ttk.Button(
            actions, text="Browse", command=self.pick_edit_output
        )
        self._expanded_browse_button.grid(row=0, column=2, padx=(0, 6))
        ttk.Checkbutton(
            actions, text="Output in same folder", variable=self.edit_same_folder_var,
            command=self._toggle_edit_same_folder,
        ).grid(row=0, column=3, sticky="w")
        self.expanded_edit_apply_button = ttk.Button(
            actions, text="Apply Changes", command=self.run_organise,
            style="Accent.TButton",
        )
        self.expanded_edit_apply_button.grid(row=1, column=0, pady=(6, 0), sticky="w")
        self._expanded_edit_progress = ttk.Progressbar(actions, mode="determinate")
        self._expanded_edit_progress.grid(row=1, column=1, padx=6, pady=(6, 0), sticky="ew")
        ttk.Label(actions, textvariable=self.edit_status_var).grid(
            row=1, column=2, pady=(6, 0), sticky="w"
        )
        ttk.Button(actions, text="Close Window", command=self._close_editor_window).grid(
            row=1, column=3, pady=(6, 0), sticky="e"
        )
        self._update_edit_output_state()
        self.expanded_edit_apply_button.configure(state=self.edit_apply_button.cget("state"))
        try:
            self.root.tk.call("wm", "state", editor._w, "zoomed")
        except tk.TclError:
            self.root.tk.call(
                "wm", "geometry", editor._w,
                f"{self.root.winfo_screenwidth()}x{self.root.winfo_screenheight()}+0+0",
            )

    def _edit_dialog_parent(self) -> tk.Misc:
        if getattr(self, "_editor_window_open", False):
            return self.visual_text_tab
        return self.root

    def _close_editor_window(self) -> None:
        if not getattr(self, "_editor_window_open", False):
            return
        self._on_editor_text_change()
        if self.selected_placed_text is not None:
            self._on_placed_text_change()
        editor = self.visual_text_tab
        self._expanded_editor_actions.destroy()
        del self._expanded_output_entry
        del self._expanded_browse_button
        del self.expanded_edit_apply_button
        del self._expanded_edit_progress
        self.root.tk.call("wm", "protocol", editor._w, "WM_DELETE_WINDOW", "")
        self.root.tk.call("wm", "forget", editor._w)
        self.root.deletecommand(self._editor_window_close_command)
        self._editor_window_open = False
        editor.pack(fill="both", expand=True, before=self.edit_output_frame)

    def clear_edit_pdf(self) -> None:
        """Drop the imported PDF and everything the editor was holding for it."""
        self._reset_edit_session(None, 0)

    def _warn_if_not_searchable(self) -> None:
        """Remind once per imported file when it carries no text layer.

        NOTE: a scan has no selectable text, so line editing is impossible until
        the PDF is OCR'd. Any other PDF that simply happens to hold under
        ``MIN_TEXT_CHARS`` characters would only produce noise in the editor, so
        both cases get the same pointer to Convert File: searchable-pdf. The
        flag is reset by every import, so the reminder is once per file, not
        once per page.
        """
        if self.edit_source is None or self._visual_text_ocr_warning_shown:
            return
        try:
            searchable = pdf_text.has_text_layer(self.edit_source)
        except (ConversionError, OSError):
            return
        if searchable:
            return
        self._visual_text_ocr_warning_shown = True
        messagebox.showwarning(
            "PDF-X",
            "This PDF has no OCR text layer, so its text cannot be selected or "
            "edited as lines.\n\n"
            "Use the Convert File tab first: choose SEARCHABLE-PDF as the "
            "target, then import the converted copy here. You can still add "
            "text boxes to this PDF.",
            parent=self._edit_dialog_parent(),
        )

    def _text_edit_state(self) -> TextEditState:
        return TextEditState(
            edits=self.visual_text_edits.copy(),
            redacted=getattr(self, "redacted_visual_text", {}).copy(),
            fonts=self.visual_text_fonts.copy(),
            sizes=self.visual_text_sizes.copy(),
            boxes=self.placed_text.copy(),
            page=self.visual_text_page,
            selected_line=self.selected_visual_text,
            selected_box=self.selected_placed_text,
            text=self.visual_text_var.get(),
            font=self.text_font_var.get(),
            size=self.add_text_size_var.get(),
        )

    def _sync_text_history(self) -> None:
        self._text_history_current = self._text_edit_state()
        self._update_history_buttons()

    def _record_text_edit(self) -> None:
        current = self._text_edit_state()
        if self._text_history_current is not None and current != self._text_history_current:
            self._text_undo.append(self._text_history_current)
            self._text_redo.clear()
        self._sync_text_history()

    def _restore_text_edit(self, state: TextEditState) -> None:
        self.visual_text_edits = state.edits.copy()
        self.redacted_visual_text = getattr(state, "redacted", {}).copy()
        self.visual_text_fonts = state.fonts.copy()
        self.visual_text_sizes = state.sizes.copy()
        self.placed_text = state.boxes.copy()
        self.visual_text_page = state.page
        self.selected_visual_text = state.selected_line
        self.selected_placed_text = state.selected_box
        self._text_drag_offset = None
        self._updating_text_controls = True
        try:
            self.visual_text_var.set(state.text)
            self.text_font_var.set(state.font)
            self.add_text_size_var.set(state.size)
        finally:
            self._updating_text_controls = False
        # NOTE: the editor box is a Text widget with no textvariable, so it is
        # rewritten here; the trace that normally keeps it in step is muted
        # while the state is being restored
        self._set_editor_text(state.text)
        selected_line = state.selected_line is not None
        selected = selected_line or state.selected_box is not None
        self.visual_text_entry.configure(state="normal" if selected else "disabled")
        self.visual_text_queue_button.configure(
            state="normal" if selected_line else "disabled"
        )
        self.visual_text_redact_button.configure(
            state="normal" if selected_line else "disabled"
        )
        self._load_visual_text_page()
        # NOTE: the restored state becomes the current one, so the next edit
        # pushes it onto the undo stack. Without this the stack kept the state
        # from before the restore, which pushed a duplicate on the next edit.
        self._text_history_current = self._text_edit_state()
        self._update_history_buttons()

    def _update_history_buttons(self) -> None:
        """Enable the Undo and Redo buttons to match the stacks."""
        self.text_undo_button.configure(state="normal" if self._text_undo else "disabled")
        self.text_redo_button.configure(state="normal" if self._text_redo else "disabled")

    def _undo_text_edit(self, _event=None) -> str:
        """Step back to the previous state.

        NOTE: the state being left behind is pushed onto the redo stack
        BEFORE the previous state is restored. Doing it the other way round
        restored the wrong state, because the restore overwrites the current
        state - which left redo bringing back a near-identical copy instead
        of the change the user had just undone.
        """
        if self._text_undo:
            self._text_redo.append(self._text_edit_state())
            self._restore_text_edit(self._text_undo.pop())
        return "break"

    def _redo_text_edit(self, _event=None) -> str:
        """Step forward to the state that was undone."""
        if self._text_redo:
            self._text_undo.append(self._text_edit_state())
            self._restore_text_edit(self._text_redo.pop())
        return "break"

    @staticmethod
    def _visual_text_key(
        match: pdf_edit.TextMatch,
    ) -> tuple[int, float, float, float, float, str]:
        return (
            match.page,
            round(match.x0, 2),
            round(match.top, 2),
            round(match.x1, 2),
            round(match.bottom, 2),
            match.text,
        )

    @property
    def _viewer_scale(self) -> float:
        """The canvas-to-PDF scale factor, e.g. 1.0 at 100% zoom."""
        return getattr(self, "_viewer_zoom", 100) / 100.0
    def _draw_visual_text_replacement(self, draw, match, replacement, scale, image_font) -> None:
        """Paint a line draft, expanding its white cover past the original box.

        NOTE: the baseline maths mirror the engine (baseline = top + size), so
        the preview and the saved PDF line up. A replacement longer than the
        original line is not clipped: the cover grows with the text.
        """
        key = self._visual_text_key(match)
        face = self.visual_text_fonts.get(key)
        try:
            size = int(self.visual_text_sizes.get(key, max(4, round(match.height * 0.82))))
        except (TypeError, ValueError):
            size = max(4, round(match.height * 0.82))
        size_px = max(1, round(size * scale))
        font = image_font.truetype(str(face.path), size_px, index=face.index) if face else image_font.load_default()
        text = replacement or ""
        baseline = (match.x0 * scale, (match.top + size) * scale)
        if text:
            box = draw.textbbox(baseline, text, font=font, anchor="ls")
            right = max(match.x1 * scale + 2, box[2])
            bottom = max(match.bottom * scale + 2, box[3])
        else:
            right = match.x1 * scale + 2
            bottom = match.bottom * scale + 2
        draw.rectangle(
            (match.x0 * scale - 1, match.top * scale - 1, right, bottom), fill="white"
        )
        if text:
            draw.text(baseline, text, fill="black", font=font, anchor="ls")



    def _center_viewer(self, keep_x: float | None = None, keep_y: float | None = None) -> None:
        """Centre the page in the viewer, padding the scroll region if needed.

        NOTE: the page image always sits at canvas (0, 0), so ``canvasx()`` and
        ``canvasy()`` stay page-relative and every click, drag and resize keeps
        using plain PDF-point maths. Centring is done by extending the scroll
        region past the page on each side by the spare space, which leaves the
        page in the middle of the viewport when it is smaller than the canvas
        and simply scrolls as before when it is larger.
        """
        image = getattr(self, "visual_text_image", None)
        if image is None:
            return
        canvas = self.visual_text_canvas
        canvas_width = canvas.winfo_width()
        canvas_height = canvas.winfo_height()
        if canvas_width <= 1 or canvas_height <= 1:
            return
        if keep_x is None:
            keep_x = canvas.xview()[0]
        if keep_y is None:
            keep_y = canvas.yview()[0]
        margin_x = max(0, (canvas_width - image.width()) // 2)
        margin_y = max(0, (canvas_height - image.height()) // 2)
        canvas.configure(
            scrollregion=(
                -margin_x,
                -margin_y,
                image.width() + margin_x,
                image.height() + margin_y,
            )
        )
        # NOTE: when the page is smaller than the viewer there is nothing to
        # scroll to, so the (0, 0) view already shows it centred; a larger page
        # keeps the scroll fraction it had before the resize.
        canvas.xview_moveto(keep_x)
        canvas.yview_moveto(keep_y)

    def _load_visual_text_page(self, preserve_view: bool = True) -> None:
        if self.edit_source is None:
            return
        old_x = self.visual_text_canvas.xview()[0] if preserve_view else 0.0
        old_y = self.visual_text_canvas.yview()[0] if preserve_view else 0.0
        from PIL import ImageDraw, ImageFont, ImageTk
        from .engines import pdf_render

        self.visual_text_lines = []
        self.visual_text_image = None
        self.visual_text_canvas.delete("all")
        self.visual_text_status_var.set("Loading page...")
        # NOTE: the text coordinates come from the PDF at 72 dpi, so a zoomed
        # page needs them scaled to the rendered size
        scale = self._viewer_scale
        dpi = max(36, int(round(72 * scale)))
        try:
            self.visual_text_lines = pdf_edit.text_lines(
                self.edit_source, self.visual_text_page
            )
            image = pdf_render.render_page_pil(
                self.edit_source, self.visual_text_page - 1, dpi=dpi
            )
        except (ConversionError, EngineUnavailable) as exc:
            self.visual_text_status_var.set(str(exc))
            return

        rendered_keys: set[tuple[int, float, float, float, float, str]] = set()
        draw = ImageDraw.Draw(image)
        for match in getattr(self, "redacted_visual_text", {}).values():
            if match.page != self.visual_text_page:
                continue
            rendered_keys.add(self._visual_text_key(match))
            draw.rectangle(
                (
                    match.x0 * scale - 1,
                    match.top * scale - 1,
                    match.x1 * scale + 1,
                    match.bottom * scale + 1,
                ),
                fill="black",
            )
        for match, replacement in self.visual_text_edits.values():
            if match.page != self.visual_text_page:
                continue
            rendered_keys.add(self._visual_text_key(match))
            self._draw_visual_text_replacement(draw, match, replacement, scale, ImageFont)

        # A selected line is a live draft even before Queue Change is pressed.
        # Render it with the current font and size so the controls work on first
        # selection and long edits are visible beyond the original bounds.
        selected = self.selected_visual_text
        if selected is not None and self._visual_text_key(selected) not in rendered_keys:
            self._draw_visual_text_replacement(
                draw,
                selected,
                self.visual_text_var.get(),
                scale,
                ImageFont,
            )

        if self.selected_visual_text is not None:
            selected = self.selected_visual_text
            draw.rectangle(
                (
                    selected.x0 * scale - 1,
                    selected.top * scale - 1,
                    selected.x1 * scale + 1,
                    selected.bottom * scale + 1,
                ),
                outline="#d00000",
                width=2,
            )

        self.visual_text_image = ImageTk.PhotoImage(image)
        self.visual_text_canvas.delete("all")
        self.visual_text_canvas.create_image(
            0, 0, anchor="nw", image=self.visual_text_image
        )
        # NOTE: the view is restored to where it was, so selecting a line or
        # changing its font does not throw the page back to the top. Only a
        # new page or a new document starts at the top.
        self._center_viewer(old_x if preserve_view else 0.0, old_y if preserve_view else 0.0)
        self._draw_placed_text()
        self._update_visual_text_nav()

        if self.visual_text_lines:
            self.visual_text_status_var.set(
                f"{len(self.visual_text_lines)} selectable text line(s) on this page."
            )
        else:
            self.visual_text_status_var.set(
                "No selectable text on this page. Scanned text needs OCR first; "
                "you can still add a text box."
            )
            # NOTE: importing a PDF with no text layer already showed the
            # Convert File reminder (see _warn_if_not_searchable), so the flag
            # stays up and this page-level warning never stacks on top of it
            self._warn_if_not_searchable()

    def _update_visual_text_nav(self) -> None:
        """Show the page counter and enable Previous/Next from the loaded file."""
        self.visual_text_page_var.set(
            f"Page {self.visual_text_page} of {self.visual_text_total_pages}"
        )
        self.visual_text_prev.configure(
            state="normal" if self.visual_text_page > 1 else "disabled"
        )
        self.visual_text_next.configure(
            state=(
                "normal"
                if self.visual_text_page < self.visual_text_total_pages
                else "disabled"
            )
        )

    def _navigate_visual_text(self, step: int) -> None:
        if self.edit_source is None:
            return
        page = self.visual_text_page + step
        if not 1 <= page <= self.visual_text_total_pages:
            return
        if self.selected_placed_text is not None:
            self._finish_text_editing()
        self.visual_text_page = page
        self.selected_visual_text = None
        self.selected_placed_text = None
        # NOTE: moving to another page is not an edit, so the history is left
        # alone. Clearing the text through the variable would otherwise record
        # a step and push the real edits down the undo stack.
        self._updating_text_controls = True
        try:
            self.visual_text_var.set("")
        finally:
            self._updating_text_controls = False
        self.visual_text_entry.configure(state="disabled")
        self.visual_text_queue_button.configure(state="disabled")
        self.visual_text_redact_button.configure(state="disabled")
        self._load_visual_text_page(preserve_view=False)
        self._sync_text_history()

    def _add_text_box(self) -> None:
        if not self._edit_ready() or self.edit_source is None:
            return
        if self.visual_text_image is None:
            messagebox.showerror("PDF-X", "The page preview is unavailable.",
                                 parent=self._edit_dialog_parent())
            return
        font = self.system_fonts.get(self.text_font_var.get())
        if font is None:
            messagebox.showerror("PDF-X", "Select an installed font first.",
                                 parent=self._edit_dialog_parent())
            return
        try:
            size = int(self.add_text_size_var.get())
            if not 4 <= size <= 200:
                raise ValueError
        except ValueError:
            messagebox.showerror("PDF-X", "Font size must be between 4 and 200.",
                                 parent=self._edit_dialog_parent())
            return
        # NOTE: the new box is positioned in PDF points, so the canvas position
        # is scaled back before it is stored
        scale = self._viewer_scale
        width, height = self.visual_text_image.width(), self.visual_text_image.height()
        page_width = width / scale
        page_height = height / scale
        x = max(0, min(page_width - 1, self.visual_text_canvas.canvasx(20) / scale))
        top = max(0, min(page_height - 1, self.visual_text_canvas.canvasy(20) / scale))
        # NOTE: the box starts with a sensible frame the user can resize freely
        # from its corner; the text wraps inside it
        from PIL import ImageFont as _IF

        try:
            probe = _IF.truetype(str(font.path), size, index=font.index)
            box_w = max(60.0, probe.getlength("Text") + 16)
        except OSError:
            box_w = 80.0
        box_h = size * 1.6
        self.placed_text.append(pdf_edit.PlacedText(
            page=self.visual_text_page, text="Text", x=x, top=top,
            font_size=size, font_path=font.path, font_index=font.index,
            width=box_w, height=box_h,
        ))
        self._select_placed_text(len(self.placed_text) - 1)
        self._record_text_edit()
        self._draw_placed_text()
        self.placed_text_entry.focus_set()
        # NOTE: the caret goes to the END; select-all would wipe the starter
        # text on the first keypress
        self.placed_text_entry.mark_set("insert", "end-1c")
        self.placed_text_entry.see("insert")

    def _select_placed_text(self, index: int) -> None:
        item = self.placed_text[index]
        self.selected_visual_text = None
        self.selected_placed_text = index
        self._updating_text_controls = True
        try:
            self.visual_text_var.set(item.text)
            self.add_text_size_var.set(str(item.font_size))
            self.text_font_var.set(next(
                (name for name, face in self.system_fonts.items()
                 if item.font_path is not None
                 and face == FontFace(item.font_path, item.font_index)), ""
            ))
        finally:
            self._updating_text_controls = False
        # NOTE: the on-canvas box mirrors the item, so it shows the item's text
        # as soon as the box is selected
        self._sync_placed_text_entry(item.text)
        self.visual_text_entry.configure(state="normal")
        self.visual_text_queue_button.configure(state="disabled")
        self.visual_text_redact_button.configure(state="disabled")
        self.text_font_hint_var.set("Type in the box and drag its border; choose a font above.")

    def _on_placed_text_change(self, _event=None) -> None:
        """Copy the on-canvas box's text back to the master, then redraw.

        NOTE: the on-canvas box is edited in place, so its content is the
        source of truth while it has the focus. The change is pushed into the
        master's variable, which updates the item and the editor box.
        """
        if not self.placed_text_entry.edit_modified():
            return
        self.placed_text_entry.edit_modified(False)
        if self._updating_text_controls:
            return
        if self.selected_placed_text is None:
            return
        text = self.placed_text_entry.get("1.0", "end-1c")
        if text == self.visual_text_var.get():
            return
        self.visual_text_var.set(text)
        # NOTE: the item is updated here, because the box change does not go
        # through the variable's trace any more
        self._update_placed_text()

    def _placed_text_content(self) -> str:
        """The on-canvas box's text, which is the master while it is edited."""
        return self.placed_text_entry.get("1.0", "end-1c")

    def _update_placed_text(self, *_args) -> None:
        """Apply the current controls to the selected line or box.

        NOTE: this does NOT record a history step. It runs on every keystroke
        and on every font or size change, so recording here filled the undo
        stack with near-duplicate states and left redo restoring only a
        fragment. The history step is taken by the action that started the
        change instead.
        """
        index = self.selected_placed_text
        if self._updating_text_controls:
            return
        if index is None:
            if self.selected_visual_text is not None:
                # NOTE: the font and size also drive the SELECTED PDF line, so
                # changing either re-renders that line straight away instead of
                # waiting for the change to be queued
                self._apply_font_to_selected_line()
            else:
                self._sync_text_history()
            return
        try:
            size = int(self.add_text_size_var.get())
        except ValueError:
            size = 0
        font = self.system_fonts.get(self.text_font_var.get())
        # NOTE: the on-canvas box is edited in place, so its content wins when
        # it holds the focus; otherwise the editor box is the master and its
        # variable is used. Either way the item ends up with what the user
        # sees.
        text = self._placed_text_content()
        if self.root.focus_get() != self.placed_text_entry:
            text = self.visual_text_var.get()
        self.placed_text[index] = replace(
            self.placed_text[index],
            text=text,
            font_path=font.path if font else None,
            font_index=font.index if font else 0,
            font_size=size,
        )
        self._draw_placed_text()

    def _apply_font_to_selected_line(self) -> None:
        """Give the selected PDF line the font and size currently chosen.

        NOTE: the font and the size boxes used to apply only to a NEW text box,
        so a selected line kept the suggested font until the change was queued.
        Now both drive the line at once, which is what "the font controls the
        recognised line" means.
        """
        match = self.selected_visual_text
        if match is None:
            return
        key = self._visual_text_key(match)
        font = self.system_fonts.get(self.text_font_var.get())
        if font is not None:
            self.visual_text_fonts[key] = font
        try:
            size = int(self.add_text_size_var.get())
        except ValueError:
            size = self.visual_text_sizes.get(key, 0)
        if size:
            self.visual_text_sizes[key] = size
        self._load_visual_text_page()

    def _on_viewer_wheel(self, event) -> str:
        """Scroll the page, or zoom it when Ctrl is held."""
        if event.state & 0x0004:  # Ctrl
            self._zoom_viewer(1 if event.delta > 0 else -1)
            return "break"
        self.visual_text_canvas.yview_scroll(-1 * (event.delta // 120 or 1), "units")
        return "break"

    def _zoom_viewer(self, step: int) -> None:
        """Step the zoom up or down."""
        self._set_viewer_zoom(getattr(self, "_viewer_zoom", 100) + step * 25)

    def _set_viewer_zoom(self, percent: int) -> None:
        """Render the page at the given zoom percentage."""
        percent = max(50, min(400, int(percent)))
        if percent == self._viewer_zoom:
            return
        self._viewer_zoom = percent
        self.viewer_zoom_var.set(f"{percent}%")
        self._load_visual_text_page()

    def _zoom_fit_viewer(self) -> None:
        """Zoom so the whole page fits the viewer.

        NOTE: a page is rendered at 72 dpi, so 100% shows it at its natural
        size. The fit percentage is the ratio between the viewer's size and
        the page's, which keeps the whole page on screen without scrolling.
        """
        if self.edit_source is None or self.visual_text_image is None:
            return
        canvas_width = self.visual_text_canvas.winfo_width()
        canvas_height = self.visual_text_canvas.winfo_height()
        if canvas_width <= 1 or canvas_height <= 1:
            return
        image_width = self.visual_text_image.width()
        image_height = self.visual_text_image.height()
        if image_width <= 1 or image_height <= 1:
            return
        scale = min(canvas_width / image_width, canvas_height / image_height)
        self._set_viewer_zoom(round(scale * self._viewer_zoom))

    def _draw_placed_text(self) -> None:
        from PIL import Image, ImageDraw, ImageFont, ImageTk

        canvas = self.visual_text_canvas
        focus_in_box = self.root.focus_get() == self.placed_text_entry
        cursor = self.placed_text_entry.index("insert") if focus_in_box else "1.0"
        canvas.delete("placed-text")
        self._placed_images = []
        # NOTE: the item position is in PDF points, but the canvas holds the
        # zoomed page, so the drawing is scaled up to canvas pixels
        scale = self._viewer_scale
        for index, item in enumerate(self.placed_text):
            if item.page != self.visual_text_page:
                continue
            left = item.x * scale
            top = item.top * scale
            font_size = max(4, int(round(item.font_size * scale)))
            if item.font_path is None or not 4 <= item.font_size <= 200:
                canvas.create_rectangle(left, top, left + 80, top + 20,
                                        outline="red", tags=("placed-text", f"box-{index}"))
                continue
            try:
                font = ImageFont.truetype(str(item.font_path), font_size, index=item.font_index)
            except OSError as exc:
                self.text_font_hint_var.set(f"Cannot load font: {exc}")
                continue
            source_lines = item.text.split("\n")
            width = max(20, int(item.width * scale) if item.width else
                        int(max(font.getlength(line) for line in source_lines)) + 4)
            height = max(20, int(item.height * scale) if item.height else int(font_size * 1.5))
            lines: list[str] = []
            for line in source_lines:
                if item.width:
                    lines.extend(pdf_edit._wrap_line(line, item.width * scale, font.getlength))
                else:
                    lines.append(line)
            leading = font_size * 1.2
            image = Image.new("RGBA", (width, max(height, int(font_size + len(lines) * leading))))
            draw = ImageDraw.Draw(image)
            for offset, line in enumerate(lines):
                draw.text((0, font_size + offset * leading), line,
                          font=font, fill="black", anchor="ls")
            photo = ImageTk.PhotoImage(image)
            self._placed_images.append(photo)
            tags = ("placed-text", f"box-{index}")
            if index == self.selected_placed_text:
                label = next((name for name, face in self.system_fonts.items()
                              if face == FontFace(item.font_path, item.font_index)), "")
                self.placed_text_entry.configure(font=(label, -font_size))
                # NOTE: the on-canvas box is a separate Text widget, so its
                # content is kept in step by _select_placed_text and by the
                # <<Modified>> handler; it is NOT rewritten here, or a redraw
                # would throw away what the user is typing
                canvas.create_window(
                    left + 4, top + 4, window=self.placed_text_entry,
                    anchor="nw", width=width, height=height, tags=tags,
                )
            else:
                canvas.create_image(left, top, image=photo, anchor="nw", tags=tags)
            canvas.create_rectangle(
                left, top, left + width + 8, top + height + 8,
                outline="#d00000" if index == self.selected_placed_text else "#5555cc",
                dash=(3, 2), tags=(*tags, "placed-text-border"),
            )
            if index == self.selected_placed_text:
                # NOTE: the corner grip is the resize handle; dragging anywhere
                # else on the box moves it
                grip_x = left + width + 8
                grip_y = top + height + 8
                canvas.create_rectangle(
                    grip_x - 5, grip_y - 5, grip_x + 5, grip_y + 5,
                    fill="#d00000", outline="#d00000",
                    tags=("placed-text", "box-grip"),
                )
        if focus_in_box and self.selected_placed_text is not None:
            self.placed_text_entry.focus_set()
            self.placed_text_entry.mark_set("insert", cursor)

    def _scroll_placed_text(self, event) -> str:
        """Scroll the on-canvas text box with the mouse wheel."""
        try:
            self.placed_text_entry.yview_scroll(-1 * (event.delta // 120 or 1), "units")
        except tk.TclError:
            pass
        return "break"

    def _sync_placed_text_entry(self, text: str) -> None:
        """Copy the master's text into the on-canvas box.

        NOTE: the on-canvas box is its own Text widget, so it cannot share the
        editor's textvariable without fighting over the same content. The
        editor box is the master; this one mirrors it.
        """
        if self.placed_text_entry.get("1.0", "end-1c") == text:
            return
        self.placed_text_entry.delete("1.0", "end")
        self.placed_text_entry.insert("1.0", text)
        self.placed_text_entry.edit_modified(False)

    def _on_text_box_border_enter(self, _event) -> None:
        self.visual_text_canvas.configure(cursor="fleur")

    def _on_text_box_border_leave(self, _event) -> None:
        self.visual_text_canvas.configure(cursor="")

    def _viewer_point(self, event) -> tuple[float, float]:
        """The canvas position of an event, in PDF points (72 dpi).

        NOTE: the canvas holds the ZOOMED page image, so its pixels are larger
        than the PDF's points. Dividing by the zoom factor gives coordinates
        that can be compared with the text matches, which are in points.
        """
        scale = self._viewer_scale
        x = self.visual_text_canvas.canvasx(event.x) / scale
        y = self.visual_text_canvas.canvasy(event.y) / scale
        return x, y

    def _visual_text_click(self, event) -> None:
        canvas_x = self.visual_text_canvas.canvasx(event.x)
        canvas_y = self.visual_text_canvas.canvasy(event.y)
        for canvas_id in reversed(self.visual_text_canvas.find_overlapping(canvas_x, canvas_y, canvas_x, canvas_y)):
            for tag in self.visual_text_canvas.gettags(canvas_id):
                if tag == "box-grip":
                    # NOTE: the corner grip RESIZES the box instead of moving it
                    index = self.selected_placed_text
                    if index is not None:
                        item = self.placed_text[index]
                        scale = self._viewer_scale
                        self._text_resize_origin = (
                            canvas_x - item.x * scale,
                            canvas_y - item.top * scale,
                        )
                        self._text_drag_offset = (0.0, 0.0)
                        self._text_resizing = True
                        self._finish_text_editing()
                    return
                if tag.startswith("box-"):
                    index = int(tag[4:])
                    if self.selected_placed_text is not None and self.selected_placed_text != index:
                        self._finish_text_editing()
                    self._select_placed_text(index)
                    item = self.placed_text[index]
                    # NOTE: the drag offset is in canvas pixels, while the item
                    # is stored in PDF points, so the item is scaled up here
                    scale = self._viewer_scale
                    self._text_drag_offset = (
                        canvas_x - item.x * scale,
                        canvas_y - item.top * scale,
                    )
                    self._text_resizing = False
                    self._load_visual_text_page()
                    self._sync_text_history()
                    return
        # a click anywhere else ends the box edit, as the user asked
        self._finish_text_editing()
        self.selected_placed_text = None
        had_selected_line = self.selected_visual_text is not None
        self.selected_visual_text = None
        self.visual_text_entry.configure(state="disabled")
        self.visual_text_queue_button.configure(state="disabled")
        self.visual_text_redact_button.configure(state="disabled")
        self._draw_placed_text()
        self._select_visual_text(event)
        if had_selected_line and self.selected_visual_text is None:
            self._load_visual_text_page()
        self._sync_text_history()

    def _on_box_text_press(self, event) -> None:
        """A click inside the Text widget selects the box and arms dragging."""
        index = self.selected_placed_text
        if index is None:
            return
        item = self.placed_text[index]
        scale = self._viewer_scale
        canvas_x = self.visual_text_canvas.canvasx(
            self.placed_text_entry.winfo_x() + event.x
        )
        canvas_y = self.visual_text_canvas.canvasy(
            self.placed_text_entry.winfo_y() + event.y
        )
        self._text_drag_offset = (
            canvas_x - item.x * scale,
            canvas_y - item.top * scale,
        )
        self._text_resizing = False

    def _drag_from_widget(self, event) -> None:
        """Translate a press-drag inside the on-canvas Text widget to canvas coords."""
        if self.selected_placed_text is None or self._text_drag_offset is None:
            return
        canvas_x = self.visual_text_canvas.canvasx(
            self.placed_text_entry.winfo_x() + event.x
        )
        canvas_y = self.visual_text_canvas.canvasy(
            self.placed_text_entry.winfo_y() + event.y
        )
        scale = self._viewer_scale
        item = self.placed_text[self.selected_placed_text]
        self.placed_text[self.selected_placed_text] = replace(
            item,
            x=max(0, (canvas_x - self._text_drag_offset[0]) / scale),
            top=max(0, (canvas_y - self._text_drag_offset[1]) / scale),
        )
        self._draw_placed_text()

    def _finish_text_editing(self) -> None:
        """Commit the on-canvas box and drop its focus.

        NOTE: this is what a click OUTSIDE the box does: the edit is complete,
        so the box stops taking keystrokes and Remove Box becomes the way to
        get rid of it. The text already lives in the item, so nothing is lost.
        """
        if self.selected_placed_text is None:
            return
        self._on_placed_text_change()
        if self.root.focus_get() == self.placed_text_entry:
            self.visual_text_canvas.focus_set()
        self._update_placed_text()
        self._record_text_edit()

    def _drag_placed_text(self, event) -> None:
        index = self.selected_placed_text
        if index is None or self._text_drag_offset is None or self.visual_text_image is None:
            return
        # NOTE: the item position is stored in PDF points, so the drag works
        # in canvas pixels and is scaled back before it is stored
        scale = self._viewer_scale
        canvas_x = self.visual_text_canvas.canvasx(event.x)
        canvas_y = self.visual_text_canvas.canvasy(event.y)
        page_width = self.visual_text_image.width() / scale
        page_height = self.visual_text_image.height() / scale
        item = self.placed_text[index]
        if getattr(self, "_text_resizing", False):
            origin_x, origin_y = getattr(self, "_text_resize_origin", (0.0, 0.0))
            self.placed_text[index] = replace(
                item,
                width=max(30.0, (canvas_x - origin_x) / scale),
                height=max(item.font_size * 1.2, (canvas_y - origin_y) / scale),
            )
        else:
            x = (canvas_x - self._text_drag_offset[0]) / scale
            y = (canvas_y - self._text_drag_offset[1]) / scale
            self.placed_text[index] = replace(
                item,
                x=max(0, min(page_width - 1, x)),
                top=max(0, min(page_height - 1, y)),
            )
        self._draw_placed_text()

    def _end_text_drag(self, _event) -> None:
        if self._text_drag_offset is not None:
            self._record_text_edit()
        self._text_drag_offset = None
        self._text_resizing = False
        self._text_resize_origin = (0.0, 0.0)

    def _remove_text_box(self) -> None:
        if self.selected_placed_text is None:
            messagebox.showinfo("PDF-X", "Select a text box to remove.",
                                parent=self._edit_dialog_parent())
            return
        self.placed_text.pop(self.selected_placed_text)
        self.selected_placed_text = None
        self._text_resizing = False
        self._text_drag_offset = None
        self.visual_text_entry.configure(state="disabled")
        self._record_text_edit()
        self._draw_placed_text()

    def _set_editor_text(self, text: str) -> None:
        """Put text into the editor box without firing the change handlers.

        NOTE: a disabled Text widget ignores an insert, so the box is enabled
        for the write and its state is restored afterwards.
        """
        state = str(self.visual_text_entry["state"])
        self._updating_text_controls = True
        try:
            self.visual_text_entry.configure(state="normal")
            self.visual_text_entry.delete("1.0", "end")
            self.visual_text_entry.insert("1.0", text)
            # NOTE: the <<Modified>> event is cleared here too, or it fires on
            # the next idle cycle and would push the box's text back
            self.visual_text_entry.edit_modified(False)
            if state != "normal":
                self.visual_text_entry.configure(state=state)
        finally:
            self._updating_text_controls = False

    def _on_style_change(self, *_args) -> None:
        """Apply a font or size change to the selection and record it.

        NOTE: the history step is taken here, BEFORE the change is applied, so
        undo has the previous font and size to restore and redo has the new
        ones to bring back.
        """
        if self._updating_text_controls:
            return
        self._record_text_edit()
        self._update_placed_text()

    def _on_editor_text_change(self, _event=None) -> None:
        """Copy the editor box's text into the master variable.

        NOTE: the box is NOT rewritten from the variable here. Doing so would
        destroy the user's selection, so typing over a Ctrl+A selection would
        insert at the caret instead of replacing the selected text.
        """
        if not self.visual_text_entry.edit_modified():
            return
        self.visual_text_entry.edit_modified(False)
        if self._updating_text_controls:
            return
        text = self.visual_text_entry.get("1.0", "end-1c")
        if text == self.visual_text_var.get():
            return
        # NOTE: the history step is taken BEFORE the change, so undo has the
        # previous text to restore and redo has the new one to bring back
        self._record_text_edit()
        # NOTE: the variable is the master, but the change came FROM the box,
        # so the box must not be written back
        self._updating_text_controls = True
        try:
            self.visual_text_var.set(text)
        finally:
            self._updating_text_controls = False
        self._update_placed_text()

    def _on_text_var_change(self, *_args) -> None:
        """Rewrite the editor box when the master variable changes.

        NOTE: this is the path taken by a selected line, a selected box and an
        undo, so the box has to follow the variable here.

        The history step is taken BEFORE the change is applied. Recording it
        afterwards would compare the new state against itself, see no
        difference and record nothing - which left undo with nothing to undo
        and redo with nothing to restore.
        """
        if self._updating_text_controls:
            return
        text = self.visual_text_var.get()
        if self.visual_text_entry.get("1.0", "end-1c") == text:
            return
        self._record_text_edit()
        self._set_editor_text(text)

    def _select_all_in_entry(self, widget) -> None:
        """Select the whole content of a text widget.

        NOTE: tk.Text has no selection_range(); it uses a tag instead. The
        helper keeps the call sites readable and works for both the editor box
        and the on-canvas box.
        """
        try:
            widget.tag_add("sel", "1.0", "end")
        except tk.TclError:
            pass

    def _select_visual_text(self, event) -> None:
        if not self.visual_text_lines:
            return
        # NOTE: the matches are in PDF points, so the click must be scaled back
        x, y = self._viewer_point(event)

        def distance(match: pdf_edit.TextMatch) -> float:
            dx = max(match.x0 - x, 0, x - match.x1)
            dy = max(match.top - y, 0, y - match.bottom)
            return (dx * dx + dy * dy) ** 0.5

        match = min(self.visual_text_lines, key=distance)
        if distance(match) > max(8.0, match.height):
            return
        self.selected_visual_text = match
        self.selected_placed_text = None
        key = self._visual_text_key(match)
        replacement = self.visual_text_edits.get(key, (match, match.text))[1]
        suggestion, exact = suggest_font(match.font_name, self.system_fonts)
        saved_font = self.visual_text_fonts.get(key)
        if saved_font:
            suggestion = next((name for name, face in self.system_fonts.items() if face == saved_font), suggestion)
        if suggestion:
            self.text_font_hint_var.set(
                f"PDF font: {match.font_name or 'unknown'}; {'exact match' if exact else 'closest match'}: {suggestion}."
            )
        else:
            self.text_font_hint_var.set(f"PDF font: {match.font_name or 'unknown'}; select an installed font.")
        self._updating_text_controls = True
        try:
            if suggestion:
                self.text_font_var.set(suggestion)
            self.add_text_size_var.set(str(
                self.visual_text_sizes.get(key, max(4, min(200, round(match.height * 0.82))))
            ))
            self.visual_text_var.set(replacement)
        finally:
            self._updating_text_controls = False
        self.visual_text_entry.configure(state="normal")
        # NOTE: the editor box is a Text widget with no textvariable, so it is
        # filled here; the trace that keeps it in step is muted while the
        # controls are being set. The box must be enabled first, or a disabled
        # Text widget ignores the insert.
        self._set_editor_text(replacement)
        self.visual_text_entry.configure(state="normal")
        self.visual_text_queue_button.configure(state="normal")
        self.visual_text_redact_button.configure(state="normal")
        self.visual_text_entry.focus_set()
        # NOTE: the whole line is NOT highlighted. A selection would replace the
        # wording on the next keystroke, which is not what clicking a line means;
        # the caret goes to the end so typing appends to the line.
        self.visual_text_entry.tag_remove("sel", "1.0", "end")
        self.visual_text_entry.mark_set("insert", "end-1c")
        self.visual_text_entry.see("insert")
        self._load_visual_text_page()
        self._sync_text_history()

    def _queue_visual_text_redact(self) -> None:
        """Queue the selected line to have its text object removed on save."""
        match = self.selected_visual_text
        if match is None:
            return
        key = self._visual_text_key(match)
        # dropping any queued text replacement so the black bar wins
        self.visual_text_edits.pop(key, None)
        self.redacted_visual_text[key] = match
        self.selected_visual_text = None
        self.visual_text_entry.configure(state="disabled")
        self.visual_text_queue_button.configure(state="disabled")
        self.visual_text_redact_button.configure(state="disabled")
        self._record_text_edit()
        self._load_visual_text_page()
        count = len(self.redacted_visual_text)
        self.visual_text_status_var.set(
            f"{count} line(s) marked for pixel redaction. Affected pages will be "
            "rebuilt and OCR'd when saved."
        )

    def _queue_visual_text_change(self) -> None:
        match = self.selected_visual_text
        if match is None:
            return
        replacement = self.visual_text_var.get()
        key = self._visual_text_key(match)
        font = self.system_fonts.get(self.text_font_var.get())
        if font is None:
            messagebox.showerror("PDF-X", "Select an installed font.",
                                 parent=self._edit_dialog_parent())
            return
        try:
            size = int(self.add_text_size_var.get())
            if not 4 <= size <= 200:
                raise ValueError
        except ValueError:
            messagebox.showerror("PDF-X", "Font size must be between 4 and 200.",
                                 parent=self._edit_dialog_parent())
            return
        self.visual_text_edits[key] = (match, replacement)
        self.visual_text_fonts[key] = font
        self.visual_text_sizes[key] = size
        self._record_text_edit()
        count = len(self.visual_text_edits)
        self._load_visual_text_page()
        self.visual_text_status_var.set(
            f"{count} pending change(s). Apply Changes writes them to a new PDF."
        )

    def _refresh_page_list(self, keep_selection: bool = False) -> None:
        selection = self.page_list.curselection() if keep_selection else ()
        self.page_list.delete(0, "end")
        for label in self.page_labels(self.edit_pages, self.edit_rotations):
            self.page_list.insert("end", label)
        for index in selection:
            if index < self.page_list.size():
                self.page_list.selection_set(index)

    def _edit_ready(self) -> bool:
        if self.edit_source is None:
            messagebox.showinfo("PDF-X", "Open a PDF first.", parent=self._edit_dialog_parent())
            return False
        return True

    def _selected_page_positions(self) -> list[int]:
        return sorted(self.page_list.curselection())

    def move_page_up(self) -> None:
        self._move_pages(-1)

    def move_page_down(self) -> None:
        self._move_pages(1)

    def _move_pages(self, step: int) -> None:
        selection = self._selected_page_positions()
        if not selection:
            return
        order = selection if step < 0 else list(reversed(selection))
        for index in order:
            target = index + step
            if target < 0 or target >= len(self.edit_pages):
                continue
            self.edit_pages[index], self.edit_pages[target] = (
                self.edit_pages[target],
                self.edit_pages[index],
            )
        moved = sorted(index + step for index in selection)
        self._refresh_page_list()
        for index in moved:
            if 0 <= index < self.page_list.size():
                self.page_list.selection_set(index)

    def rotate_page_cw(self) -> None:
        # clockwise (right): PDF /Rotate is clockwise-positive
        self._rotate_pages(90)

    def rotate_page_ccw(self) -> None:
        # counter-clockwise (left): -90 stored as 270 so /Rotate stays 0/90/180/270
        self._rotate_pages(-90)

    def rotate_page_180(self) -> None:
        self._rotate_pages(180)

    def _rotate_pages(self, angle: int) -> None:
        selection = self._selected_page_positions()
        if not selection and not self._warn_no_selection("rotate"):
            return
        for position in selection:
            source_page = self.edit_pages[position]
            # NOTE: rotation is keyed by SOURCE page, so a turn sticks to the
            # page even after it is moved elsewhere in the list
            self.edit_rotations[source_page] = (
                self.edit_rotations.get(source_page, 0) + angle
            ) % 360
        self._refresh_page_list(keep_selection=True)
        self.page_hint_var.set(
            f"Rotated {len(selection)} page(s). "
            f"Rotation shows in the list; press Apply to save."
        )

    def _warn_no_selection(self, action: str) -> bool:
        """Tell the user to pick a row first; returns False when there is none.

        NOTE: the buttons act on the selection, so without this an unselected
        click did nothing at all and looked broken.
        """
        if self.edit_source is None:
            return False
        messagebox.showinfo("PDF-X", f"Select a page to {action} first.")
        self.page_hint_var.set(f"Select a page to {action} first.")
        return False

    def delete_page(self) -> None:
        selection = self._selected_page_positions()
        if not selection and not self._warn_no_selection("delete"):
            return
        for index in reversed(selection):
            del self.edit_pages[index]
        if not self.edit_pages:
            messagebox.showwarning("PDF-X", "Every page was deleted; resetting.")
            self.reset_pages()
            return
        self._refresh_page_list(keep_selection=True)
        self.page_hint_var.set(
            f"Deleted {len(selection)} page(s). Press Apply to save."
        )

    def reset_pages(self) -> None:
        if self.edit_source is None:
            return
        count = pdf_edit.page_count(self.edit_source)
        self.edit_pages = list(range(1, count + 1))
        self.edit_rotations = {}
        self._refresh_page_list()

    def _on_page_drag_start(self, event) -> None:
        # NOTE: only remember a candidate index - the Listbox must keep its own
        # click-to-select behaviour, so nothing is moved until the pointer
        # actually drags onto a different row
        self._page_drag_index = self.page_list.nearest(event.y)

    def _on_page_drag_motion(self, event) -> None:
        current = getattr(self, "_page_drag_index", None)
        if current is None:
            return
        index = self.page_list.nearest(event.y)
        if index == current or index < 0 or index >= len(self.edit_pages):
            return
        item = self.edit_pages.pop(current)
        self.edit_pages.insert(index, item)
        self._page_drag_index = index
        self._refresh_page_list(keep_selection=True)

    def _on_page_drag_drop(self, _event) -> None:
        self._page_drag_index = None
        self._refresh_page_list(keep_selection=True)


    # ---------- edit output ----------

    def _edit_output_target(self, src: Path, tag: str = "") -> Path:
        """Output path for an edit: "<stem>_pdfx[tag].pdf" beside the input.

        NOTE: reuses convert.output_path so Edit results follow the app's naming
        rule and land beside the source unless the user picked a folder.
        """
        from .convert import output_path

        folder = self.edit_out_folder() or src.parent
        return output_path(src, folder, ".pdf", tag)

    def edit_out_folder(self) -> Path | None:
        """The chosen folder, or None when writing beside the PDF.

        NOTE: mirrors start_convert - the checkbox, not the (possibly disabled)
        entry, decides intent, so a stale path in the disabled field is ignored.
        """
        if self.edit_same_folder_var.get():
            return None
        text = self.edit_out_var.get().strip()
        return Path(text) if text else None

    def _toggle_edit_same_folder(self) -> None:
        self._update_edit_output_state()
        self.config["edit_same_folder"] = self.edit_same_folder_var.get()
        self._save_settings()

    def _update_edit_output_state(self) -> None:
        state = "disabled" if self.edit_same_folder_var.get() else "normal"
        self.edit_out_entry.configure(state=state)
        self.edit_browse_button.configure(state=state)
        if getattr(self, "_editor_window_open", False):
            self._expanded_output_entry.configure(state=state)
            self._expanded_browse_button.configure(state=state)

    def pick_edit_output(self) -> None:
        current = self.edit_out_var.get().strip()
        start = current if current and Path(current).is_dir() else self._dialog_dir()
        folder = filedialog.askdirectory(
            title="Select output folder", initialdir=start, parent=self._edit_dialog_parent()
        )
        if folder:
            self.edit_out_var.set(folder)
            self.config["edit_out_dir"] = folder
            self._save_settings()

    def _run_edit_task(self, work, done_message: str) -> None:
        """Run a blocking edit on the worker thread and report through the queue."""

        def _worker() -> None:
            try:
                result = work()
                self.events.put(("edit-done", (result, done_message)))
            except (ConversionError, EngineUnavailable) as exc:
                self.events.put(("edit-failed", str(exc)))
            except Exception as exc:  # noqa: BLE001 - last-resort UI guard
                self.events.put(("edit-failed", str(exc)))

        if self.worker and self.worker.is_alive():
            return
        if not self._edit_ready():
            return
        self._set_edit_busy(True)
        self.edit_status_var.set("Working...")
        self.worker = threading.Thread(target=_worker, daemon=True)
        self.worker.start()

    def _set_edit_busy(self, busy: bool) -> None:
        state = "disabled" if busy else "normal"
        self.edit_apply_button.configure(state=state)
        if not busy:
            self.edit_progress.configure(value=self.edit_progress["maximum"])
        if getattr(self, "_editor_window_open", False):
            self.expanded_edit_apply_button.configure(state=state)
            if not busy:
                self._expanded_edit_progress.configure(
                    value=self._expanded_edit_progress["maximum"]
                )

    def _edit_log_write(self, message: str) -> None:
        """Write an edit line to the internal log.

        NOTE: the on-screen Processing Log was removed; the call sites remain,
        so the message is recorded on the ``pdftoolbox`` logger instead.
        """
        logging.getLogger("pdftoolbox").info("edit: %s", message)

    def _report_edit_result(self, result, note: str) -> None:
        """Log the path(s) an edit produced and set the status line.

        NOTE: a job may return a tuple mixing a path with a count (e.g. the
        replace result); only the Path items are logged, and the note carries
        the human summary.
        """
        if isinstance(result, (list, tuple)):
            paths = [item for item in result if isinstance(item, Path)]
            for path in paths:
                self._edit_log_write(f"ok      {path}")
        else:
            self._edit_log_write(f"ok      {result}")
        self.edit_status_var.set(note)
        self._set_edit_busy(False)

    def run_organise(self) -> None:
        """Apply every change and write ONE new PDF copy.

        NOTE: this covers the page changes (reorder, rotate, delete) AND the
        text corrections and added boxes, so the Apply button is the only save
        the user needs. The text changes follow the SOURCE page numbers, so a
        correction stays with its page when the page is moved or turned.
        """
        if not self.edit_pages:
            messagebox.showinfo("PDF-X", "No pages to save.", parent=self._edit_dialog_parent())
            return
        if self.edit_source is None:
            return
        if self.selected_placed_text is not None:
            self._on_placed_text_change()
        src = self.edit_source
        order = list(self.edit_pages)
        rotations = dict(self.edit_rotations)
        edits = list(self.visual_text_edits.values())
        additions = list(self.placed_text)
        fonts: list[FontFace | None] = [
            self.visual_text_fonts[key] for key in self.visual_text_edits
        ]
        sizes = [self.visual_text_sizes[key] for key in self.visual_text_edits]
        redactions = list(getattr(self, "redacted_visual_text", {}).values())
        if any(
            not item.text.strip() or item.font_path is None or not 4 <= item.font_size <= 200
            for item in additions
        ):
            messagebox.showerror(
                "PDF-X",
                "Every text box needs text, an installed font, and a size from 4 to 200.",
                parent=self._edit_dialog_parent(),
            )
            return
        # NOTE: redaction is content removal, unlike the visual overlay edits.
        # When both are pending, the overlay is written to a scratch file first
        # (page order untouched, so the line page numbers stay valid) and the
        # redaction then carries BOTH plus the page order and rotations into
        # the final file.
        if redactions:
            try:
                redaction_dpi = int(self.config.get("ocr_dpi", 200))
            except (TypeError, ValueError):
                messagebox.showerror("PDF-X", "The OCR DPI setting is invalid.")
                return
            tag = "_redacted"
            target = self._edit_output_target(src, tag)

            def redact_work():
                if edits or additions:
                    import tempfile

                    with tempfile.TemporaryDirectory() as tmp:
                        scratch = Path(tmp) / "overlay.pdf"
                        pdf_edit.apply_edits(
                            src,
                            scratch,
                            edits=edits,
                            font_paths=fonts,
                            additions=additions,
                            font_sizes=sizes,
                        )
                        return pdf_edit.redact_lines(
                            scratch, target, redactions,
                            order=order, rotations=rotations, dpi=redaction_dpi,
                        )
                return pdf_edit.redact_lines(
                    src, target, redactions, order=order, rotations=rotations,
                    dpi=redaction_dpi,
                )

            def _redact_done(path: Path) -> None:
                self.visual_text_status_var.set(
                    f"Redacted copy saved: {path.name}. Redacted pages were rebuilt "
                    "and OCR'd; verify before sharing."
                )

            self._run_edit_task_custom(redact_work, _redact_done, "Redacted PDF copy saved")
            return
        # NOTE: the tag says an edited copy, because the text corrections are
        # drawn on top of the original text rather than replacing it
        tag = "_textedited" if (edits or additions) else ""
        target = self._edit_output_target(src, tag)

        def work():
            return pdf_edit.apply_edits(
                src,
                target,
                order=order,
                rotations=rotations,
                edits=edits,
                font_paths=fonts,
                additions=additions,
                font_sizes=sizes,
            )

        def _done(path: Path) -> None:
            self.visual_text_status_var.set(
                f"Edited copy saved: {path.name}. The original PDF text remains "
                "beneath the visual corrections."
            )

        self._run_edit_task_custom(work, _done, "Edited PDF copy saved")

    def run_split(self) -> None:
        src = self.edit_source
        try:
            every = int(self.split_every_var.get())
        except ValueError:
            messagebox.showerror("PDF-X", "Pages per file must be a number.")
            return
        folder = self.edit_out_folder() or src.parent
        from .convert import output_name

        base = output_name(src, "", "_part")
        # NOTE: drop the trailing "_part"; split_pdf appends its own numbering
        base = base[: -len("_part")] if base.endswith("_part") else base

        def work():
            return pdf_edit.split_pdf(src, folder, every=every, base_name=base)

        self._run_edit_task(work, "Split complete")

    def run_extract(self) -> None:
        from .convert import parse_pages

        src = self.edit_source
        try:
            pages = parse_pages(self.extract_pages_var.get().strip() or None)
        except ValueError as exc:
            messagebox.showerror("PDF-X", f"Bad page range: {exc}")
            return
        if not pages:
            messagebox.showinfo("PDF-X", "Give a page range, e.g. 1-3,5.")
            return
        target = self._edit_output_target(src, "_extract")

        def work():
            return pdf_edit.extract_pages(src, target, pages)

        self._run_edit_task(work, "Extracted pages")

    def run_compress(self) -> None:
        src = self.edit_source
        if not self._edit_ready():
            return
        try:
            quality = int(self.compress_quality_var.get())
        except ValueError:
            messagebox.showerror("PDF-X", "Image quality must be a number from 10 to 95.")
            return
        if not 10 <= quality <= 95:
            messagebox.showerror("PDF-X", "Image quality must be from 10 to 95.")
            return
        dpi_text = self.compress_dpi_var.get()
        dpi = None if dpi_text == "Off" or not dpi_text else int(dpi_text.split()[0])
        grayscale = self.compress_grayscale_var.get()
        target = self._edit_output_target(src, "_compressed")

        def work():
            return pdf_edit.compress_pdf(
                src,
                target,
                image_quality=quality,
                downsample_dpi=dpi,
                grayscale=grayscale,
            )

        def _done(path: Path) -> None:
            saved = src.stat().st_size - path.stat().st_size
            self.edit_status_var.set(
                f"Compressed copy saved ({saved:+,} bytes): {path.name}"
            )

        self._run_edit_task_custom(work, _done, "Compressed PDF copy saved")

    def run_watermark(self) -> None:
        src = self.edit_source
        text = self.watermark_var.get().strip()
        if not text:
            messagebox.showinfo("PDF-X", "Enter watermark text.")
            return
        diagonal = bool(self.watermark_diagonal_var.get())
        target = self._edit_output_target(src, "_watermark")

        def work():
            return pdf_edit.add_watermark(src, target, text, diagonal=diagonal)

        self._run_edit_task(work, "Watermark added")

    def run_page_numbers(self) -> None:
        src = self.edit_source
        pattern = self.number_pattern_var.get()
        position = self.number_position_var.get()
        target = self._edit_output_target(src, "_numbered")

        def work():
            return pdf_edit.add_page_numbers(src, target, pattern=pattern, position=position)

        self._run_edit_task(work, "Page numbers added")

    def run_find_text(self) -> None:
        src = self.edit_source
        if not self._edit_ready():
            return
        needle = self.find_var.get()
        if not needle:
            messagebox.showinfo("PDF-X", "Enter text to find.")
            return
        case = self.find_case_var.get()

        def work():
            return pdf_edit.find_text(src, needle, case_sensitive=case)

        def _report(matches):
            if not matches:
                self.find_result_var.set(f"No matches for {needle!r}.")
                return
            pages = sorted({m.page for m in matches})
            self.find_result_var.set(
                f"{len(matches)} match(es) on page(s): "
                + ", ".join(str(p) for p in pages)
            )

        try:
            matches = work()
        except ConversionError as exc:
            messagebox.showerror("PDF-X", str(exc))
            return
        _report(matches)

    def run_replace_text(self) -> None:
        src = self.edit_source
        if not self._edit_ready():
            return
        needle = self.find_var.get()
        replacement = self.replace_var.get()
        if not needle:
            messagebox.showinfo("PDF-X", "Enter text to find.")
            return
        case = self.find_case_var.get()
        target = self._edit_output_target(src, "_replaced")
        self.find_result_var.set(f"Replacing {needle!r} ...")

        def work():
            path, count = pdf_edit.replace_text(
                src, target, needle, replacement, case_sensitive=case
            )
            return path, count

        def _done(result):
            path, count = result
            self.find_result_var.set(f"Replaced {count} occurrence(s) -> {path.name}")

        self._run_edit_task_custom(work, _done, "Replaced text")

    def _run_edit_task_custom(self, work, on_success, done_message: str) -> None:
        """Like _run_edit_task, but lets a job report its own success detail."""
        if self.worker and self.worker.is_alive():
            return
        self._set_edit_busy(True)
        self.edit_status_var.set("Working...")

        def _worker() -> None:
            try:
                self.events.put(("edit-custom", (work(), on_success, done_message)))
            except (ConversionError, EngineUnavailable) as exc:
                self.events.put(("edit-failed", str(exc)))
            except Exception as exc:  # noqa: BLE001 - last-resort UI guard
                self.events.put(("edit-failed", str(exc)))

        self.worker = threading.Thread(target=_worker, daemon=True)
        self.worker.start()

    def add_folder(self) -> None:
        folder = filedialog.askdirectory(
            title="Select folder", initialdir=self._dialog_dir()
        )
        if not folder:
            return
        supported = {".pdf", *images_suffixes, ".md", ".markdown", ".txt", *office_suffixes}
        found = [
            path for path in Path(folder).iterdir()
            if path.is_file() and path.suffix.lower() in supported
        ]
        self._add_paths(found)

    def _add_paths(self, paths: list[Path]) -> None:
        added: Path | None = None
        for path in paths:
            if path.is_file() and path not in self.files:
                self.files.append(path)
                self.file_list.insert("end", str(path))
                added = path
        # NOTE: remember the folder of the most recent import so the next
        # session's file dialogs reopen where the user last worked
        if added is not None:
            self._office_ocr_warning_shown = False
            self._remember_dir(Path(added).expanduser().resolve().parent)
        self._refresh_targets()
        self._sync_file_drop_zone()

    def remove_selected(self) -> None:
        for index in sorted(self.file_list.curselection(), reverse=True):
            self.file_list.delete(index)
            del self.files[index]
        self._office_ocr_warning_shown = False
        self._refresh_targets()
        self._sync_file_drop_zone()

    def clear_files(self) -> None:
        self.file_list.delete(0, "end")
        self.files.clear()
        self._office_ocr_warning_shown = False
        self._refresh_targets()
        self._sync_file_drop_zone()
    # ---------- merge file list ----------

    @staticmethod
    def numbered_names(paths: list[Path]) -> list[str]:
        """The merge list as shown: "1. name", "2. name", ... in list order.

        NOTE: a pure helper so the numbering rule is unit-testable without a
        display; the page order of the result follows this exact sequence.
        """
        return [f"{index}. {path.name}" for index, path in enumerate(paths, start=1)]

    def _refresh_merge_list(self, keep_selection: bool = False) -> None:
        selection = self.merge_list.curselection() if keep_selection else ()
        self.merge_list.delete(0, "end")
        for label in self.numbered_names(self.merge_files):
            self.merge_list.insert("end", label)
        for index in selection:
            if index < self.merge_list.size():
                self.merge_list.selection_set(index)
        self._sync_merge_drop_zone()

    def add_merge_files(self) -> None:
        paths = filedialog.askopenfilenames(
            title="Select files to merge",
            initialdir=self._dialog_dir(),
            filetypes=[
                ("Supported files", "*.pdf *.png *.jpg *.jpeg *.bmp *.webp *.tif *.tiff *.gif "
                 "*.md *.markdown *.txt *.doc *.docx *.xls *.xlsx *.ppt *.pptx "
                 "*.odt *.ods *.odp *.rtf *.csv"),
                ("PDF", "*.pdf"),
                ("Images", "*.png *.jpg *.jpeg *.bmp *.webp *.tif *.tiff *.gif"),
                ("Text", "*.md *.markdown *.txt"),
                ("Office", "*.doc *.docx *.xls *.xlsx *.ppt *.pptx *.odt *.ods *.odp *.rtf *.csv"),
                ("All files", "*.*"),
            ],
        )
        self._add_merge_paths([Path(p) for p in paths])

    def _on_merge_drop(self, event) -> None:
        paths = self.root.tk.splitlist(event.data)
        self._add_merge_paths([Path(path) for path in paths])

    def _add_merge_paths(self, paths: list[Path]) -> None:
        added: Path | None = None
        for path in paths:
            if path.is_file() and path not in self.merge_files:
                self.merge_files.append(path)
                added = path
        if added is not None:
            self._remember_dir(Path(added).expanduser().resolve().parent)
        self._refresh_merge_list()

    def remove_merge_selected(self) -> None:
        for index in sorted(self.merge_list.curselection(), reverse=True):
            del self.merge_files[index]
        self._refresh_merge_list()

    def clear_merge_files(self) -> None:
        self.merge_files.clear()
        self._refresh_merge_list()

    def move_merge_up(self) -> None:
        self._move_merge_selected(-1)

    def move_merge_down(self) -> None:
        self._move_merge_selected(1)

    def _move_merge_selected(self, step: int) -> None:
        selection = sorted(self.merge_list.curselection())
        if not selection:
            return
        # NOTE: walking in the direction of travel keeps a multi-selection
        # contiguous instead of colliding items with each other
        order = selection if step < 0 else list(reversed(selection))
        for index in order:
            target = index + step
            if target < 0 or target >= len(self.merge_files):
                continue
            self.merge_files[index], self.merge_files[target] = (
                self.merge_files[target],
                self.merge_files[index],
            )
        moved = sorted(index + step for index in selection)
        self._refresh_merge_list()
        for index in moved:
            if 0 <= index < self.merge_list.size():
                self.merge_list.selection_set(index)

    def _on_merge_drag_start(self, event) -> None:
        self._merge_drag_index = self.merge_list.nearest(event.y)

    def _on_merge_drag_motion(self, event) -> None:
        index = self.merge_list.nearest(event.y)
        current = getattr(self, "_merge_drag_index", None)
        if current is None or current == index or index < 0:
            return
        if index >= len(self.merge_files):
            return
        item = self.merge_files.pop(current)
        self.merge_files.insert(index, item)
        self._merge_drag_index = index
        self._refresh_merge_list(keep_selection=True)

    def _on_merge_drag_drop(self, _event) -> None:
        self._merge_drag_index = None
        self._refresh_merge_list(keep_selection=True)

    def _toggle_merge_same_folder(self) -> None:
        self._update_merge_output_state()
        self.config["merge_same_folder"] = self.merge_same_folder_var.get()
        self._save_settings()

    def _update_merge_output_state(self) -> None:
        state = "disabled" if self.merge_same_folder_var.get() else "normal"
        self.merge_out_entry.configure(state=state)
        self.merge_browse_button.configure(state=state)

    def pick_merge_output(self) -> None:
        current = self.merge_out_var.get().strip()
        start = current if current and Path(current).is_dir() else self._dialog_dir()
        folder = filedialog.askdirectory(title="Select output folder", initialdir=start)
        if folder:
            self.merge_out_var.set(folder)


    def _confirm_merge_output_folder(self) -> bool:
        if not output_undecided(
            self.merge_same_folder_var.get(), self.merge_out_var.get()
        ):
            return True
        answer = messagebox.askyesnocancel(
            "PDF-X",
            "No output folder selected.\n\n"
            "Write the merged PDF next to the first input file?\n\n"
            "Yes    = same folder as the first file\n"
            "No     = choose an output folder\n"
            "Cancel = stop",
        )
        if answer is None:
            return False
        if answer:
            self.merge_same_folder_var.set(True)
            self._toggle_merge_same_folder()
        else:
            self.pick_merge_output()
            if not self.merge_out_var.get().strip():
                return False
        return True

    def _set_merge_busy(self, busy: bool) -> None:
        state = "disabled" if busy else "normal"
        self.merge_button.configure(state=state)
        if not busy:
            self.merge_progress.configure(value=self.merge_progress["maximum"])

    def _merge_log(self, message: str) -> None:
        """Write a merge line to the internal log.

        NOTE: the on-screen Processing Log was removed, but the call sites stay
        so nothing has to be restructured. A line is still recorded for anyone
        running the app from a console or attaching a handler.
        """
        logging.getLogger("pdftoolbox").info("merge: %s", message)

    def start_merge(self) -> None:
        if self.worker and self.worker.is_alive():
            return
        if not self.merge_files:
            messagebox.showinfo("PDF-X", "Add at least one file to merge.")
            return
        if len(self.merge_files) < 2:
            messagebox.showinfo("PDF-X", "Merging needs at least two files.")
            return
        unsupported = [src for src in self.merge_files if not can_convert_to_pdf(src)]
        if unsupported:
            names = ", ".join(src.name for src in unsupported[:3])
            messagebox.showerror(
                "PDF-X", f"These files cannot be converted to PDF: {names}"
            )
            return
        if not self._confirm_merge_output_folder():
            return

        out_dir = (
            Path(self.merge_out_var.get()) if self.merge_out_var.get().strip() else None
        )
        if self.merge_same_folder_var.get():
            # NOTE: None lets merge_to_pdf() write beside the first input
            out_dir = None

        self.config["merge_same_folder"] = self.merge_same_folder_var.get()
        self.config["merge_out_dir"] = self.merge_out_var.get().strip()
        self._save_settings()

        self._set_merge_busy(True)
        self.merge_progress.configure(value=0, maximum=len(self.merge_files))
        self.merge_status_var.set("Working...")

        inputs = list(self.merge_files)
        self.worker = threading.Thread(
            target=self._run_merge, args=(inputs, out_dir), daemon=True
        )
        self.worker.start()

    def _run_merge(self, inputs, out_dir) -> None:
        def on_progress(done, total) -> None:
            self.events.put(("merge-progress", (done, total)))

        try:
            result = merge_to_pdf(inputs, out_dir=out_dir, on_progress=on_progress)
            self.events.put(("merge-done", (result, len(inputs))))
        except (ConversionError, EngineUnavailable) as exc:
            self.events.put(("merge-failed", str(exc)))
        except Exception as exc:  # noqa: BLE001 - last-resort guard for the UI thread
            self.events.put(("merge-failed", str(exc)))




    # ---------- options ----------

    def _refresh_targets(self) -> None:
        options: list[tuple[str, str]] = []
        notes: list[str] = []
        seen: set[str] = set()
        source_targets: list[set[str]] = []
        # NOTE: merge lives on its own tab now, so the file list here no longer
        # affects the target list - pdf_count stays 0 to keep "merge" out
        for src in self.files:
            source_options = list_targets(src, 0)
            source_targets.append({option.key for option in source_options})
            for option in source_options:
                if option.key in seen:
                    continue
                seen.add(option.key)
                label = self._label_for(option)
                options.append((option.key, label))
                if not option.available and option.note:
                    notes.append(f"{option.label}: {option.note}")

        if len(source_targets) > 1:
            direct_targets = {"docx", "xlsx", "pptx"}
            options = [
                (key, label)
                for key, label in options
                if key not in direct_targets
                or all(key in targets for targets in source_targets)
            ]

        if not options and self.files:
            self.target_box["values"] = ["pdf"]
            self.target_var.set("pdf")
            self.target_note.configure(text="No known conversion for these file types.")
            return

        labels = [label for _key, label in options]
        self.target_box["values"] = labels
        if labels and self.target_var.get() not in labels:
            self.target_var.set(labels[0])
        self.target_note.configure(text=" | ".join(notes[:3]))
        self._update_option_state()
        self._warn_scanned_pdf_for_office()

    def _on_target_selected(self, _event=None) -> None:
        self._update_option_state()
        self._warn_scanned_pdf_for_office()

    def _warn_scanned_pdf_for_office(self) -> None:
        if self._office_ocr_warning_shown:
            return
        if self._current_target_key() not in {"docx", "xlsx", "pptx"}:
            return
        scanned_pdfs = [
            path for path in self.files
            if path.suffix.lower() == ".pdf"
        ]
        for path in scanned_pdfs:
            try:
                searchable = pdf_text.has_text_layer(path)
            except (ConversionError, OSError):
                continue
            if searchable:
                continue
            self._office_ocr_warning_shown = True
            messagebox.showwarning(
                "PDF-X",
                "One or more imported PDFs appear to be scans without an OCR "
                "text layer.\n\nFor better Office conversion results, first "
                "convert the scanned PDF to SEARCHABLE-PDF, then import that "
                "copy and choose the Office format. This lets you verify the "
                "OCR text before converting it.",
                parent=self.root,
            )
            return

    @staticmethod
    def _label_for(option) -> str:
        if option.available:
            return option.label
        return f"{option.label} (unavailable)"

    def _current_target_key(self) -> str:
        selection = self.target_var.get()
        for src in self.files:
            for option in list_targets(src, 0):
                if self._label_for(option) == selection:
                    return option.key
        return selection.split(" ")[0].lower()

    def _update_option_state(self) -> None:
        # NOTE: page selection applies to per-file PDF conversions, so the field
        # is live only when a PDF is in the list
        has_pdf = any(src.suffix.lower() == ".pdf" for src in self.files)
        state = "normal" if has_pdf else "disabled"
        self.pages_entry.configure(state=state)

    def _toggle_same_folder(self) -> None:
        """React to the checkbox: sync the widgets, then persist the choice.

        NOTE: saving here (not only in start_convert) means a ticked box
        survives a restart even when the user never presses Convert.
        """
        self._update_output_state()
        self.config["same_folder"] = self.same_folder_var.get()
        self._save_settings()

    def _update_output_state(self) -> None:
        """Disable the folder field and Browse when writing beside inputs.

        NOTE: disabled ttk entries still return their old text via
        out_var.get(), so start_convert must consult same_folder_var - never
        infer intent from the widget state.
        """
        state = "disabled" if self.same_folder_var.get() else "normal"
        self.out_entry.configure(state=state)
        self.browse_button.configure(state=state)

    def pick_output(self) -> None:
        # NOTE: start on the folder currently in the field, else on the last
        # folder the user imported from
        current = self.out_var.get().strip()
        start = current if current and Path(current).is_dir() else self._dialog_dir()
        folder = filedialog.askdirectory(
            title="Select output folder", initialdir=start
        )
        if folder:
            self.out_var.set(folder)

    def _confirm_output_folder(self) -> bool:
        """Ask where the output goes when the user chose neither option.

        Returns False when the user cancelled, so the caller must not start a
        conversion whose destination is still undecided.
        """
        if not output_undecided(self.same_folder_var.get(), self.out_var.get()):
            return True
        answer = messagebox.askyesnocancel(
            "PDF-X",
            "No output folder selected.\n\n"
            "Write the output next to each input file?\n\n"
            "Yes    = same folder as the input\n"
            "No     = choose an output folder\n"
            "Cancel = stop",
        )
        if answer is None:  # Cancel
            return False
        if answer:  # Yes -> write beside the inputs
            self.same_folder_var.set(True)
            self._toggle_same_folder()
        else:  # No -> open the folder picker
            self.pick_output()
            if not self.out_var.get().strip():
                return False
        return True

    # ---------- conversion ----------

    def start_convert(self) -> None:
        if self.worker and self.worker.is_alive():
            return
        if not self.files:
            messagebox.showinfo("PDF-X", "Add at least one file first.")
            return

        target = self._current_target_key()
        try:
            pages = parse_pages(self.pages_var.get().strip() or None)
            dpi = int(self.dpi_var.get())
            ocr_dpi = int(self.ocr_dpi_var.get())
        except ValueError:
            messagebox.showerror("PDF-X", "Check the DPI and pages values.")
            return

        # NOTE: when neither an output folder nor "same folder" was chosen the
        # user must decide where the results land before anything is written
        if not self._confirm_output_folder():
            return

        out_dir = Path(self.out_var.get()) if self.out_var.get().strip() else None
        if self.same_folder_var.get():
            # NOTE: None makes convert() write straight beside each input file;
            # the folder field is disabled while this is ticked
            out_dir = None

        self.config["dpi"] = dpi
        self.config["ocr_dpi"] = ocr_dpi
        self.config["same_folder"] = self.same_folder_var.get()
        # NOTE: persist the raw field text (not the resolved out_dir) so the
        # folder path survives while "Output in same folder" is ticked
        self.config["out_dir"] = self.out_var.get().strip()
        self._save_settings()

        self.convert_button.configure(state="disabled")
        self.progress.configure(value=0, maximum=len(self.files))
        self.status_var.set("Working...")
        inputs = list(self.files)
        self.worker = threading.Thread(
            target=self._run_batch,
            args=(inputs, target, out_dir, dpi, ocr_dpi, pages),
            daemon=True,
        )
        self.worker.start()

    def _run_batch(self, inputs, target, out_dir, dpi, ocr_dpi, pages) -> None:
        def on_progress(done, total) -> None:
            self.events.put(("progress", (done, total)))

        try:
            if self._ocr_first_needed(inputs, target):
                # NOTE: OCR is slow, so say why the run is taking its time
                self.events.put(
                    ("log", "note    scanned input: running OCR first")
                )
            results = convert_many(
                inputs, target, out_dir, dpi, ocr_dpi, pages, on_progress=on_progress
            )
            self.events.put(("done", results))
        except (ConversionError, EngineUnavailable) as exc:
            self.events.put(("fatal", str(exc)))
        except Exception as exc:  # noqa: BLE001 - last-resort guard for the UI thread
            self.events.put(("fatal", str(exc)))

    @staticmethod
    def _ocr_first_needed(inputs, target: str) -> bool:
        """True when the batch will OCR a scan before converting it.

        NOTE: mirrors the rule in convert._convert_from_pdf so the log can warn
        about the extra pass; the decision itself stays in the conversion layer.
        An unreadable file is skipped here - the conversion reports it properly.
        """
        if normalize_target(target) not in OCR_FIRST_TARGETS:
            return False
        for src in inputs:
            if src.suffix.lower() != ".pdf":
                continue
            try:
                if not pdf_text.has_text_layer(src):
                    return True
            except ConversionError:
                continue
        return False

    def _poll_events(self) -> None:
        try:
            while True:
                kind, payload = self.events.get_nowait()
                if kind == "log":
                    self._log(payload)
                elif kind == "progress":
                    done, total = payload
                    self.progress.configure(maximum=total, value=done)
                    self.status_var.set(f"Page {done}/{total}")
                elif kind == "done":
                    self._render_results(payload)
                elif kind == "merge-progress":
                    done, total = payload
                    self.merge_progress.configure(maximum=total, value=done)
                    self.merge_status_var.set(f"Converting {done}/{total}")
                elif kind == "merge-done":
                    result, count = payload
                    self._merge_log(f"ok      merged {count} file(s) -> {result}")
                    self.merge_status_var.set("Merge complete")
                    self._set_merge_busy(False)
                elif kind == "merge-failed":
                    self._merge_log(f"FAILED  merge: {payload}")
                    self.merge_status_var.set("Merge failed")
                    self._set_merge_busy(False)
                elif kind == "edit-done":
                    result, note = payload
                    self._report_edit_result(result, note)
                elif kind == "edit-custom":
                    result, on_success, note = payload
                    self._report_edit_result(result, note)
                    try:
                        on_success(result)
                    except Exception as exc:  # noqa: BLE001 - a report bug must not crash Tk
                        self._edit_log_write(f"note    {exc}")
                elif kind == "edit-failed":
                    self._edit_log_write(f"FAILED  edit: {payload}")
                    self.edit_status_var.set("Edit failed")
                    self._set_edit_busy(False)
                    messagebox.showerror("PDF-X", str(payload), parent=self._edit_dialog_parent())
                elif kind == "fatal":
                    self._log(f"FATAL: {payload}")
                    self.status_var.set("Failed")
                    self.convert_button.configure(state="normal")
                elif kind == "promo":
                    self._show_promo(payload)
        except queue.Empty:
            pass
        self.root.after(120, self._poll_events)

    def _render_results(self, results) -> None:
        ok = 0
        failed = 0
        for src, outcome in results:
            if isinstance(outcome, str):
                failed += 1
                self._log(f"FAILED  {src.name}: {outcome}")
            else:
                ok += 1
                for path in outcome:
                    self._log(f"ok      {src.name} -> {path}")
        self.status_var.set(f"Done: {ok} succeeded, {failed} failed")
        self.convert_button.configure(state="normal")
        self.progress.configure(value=self.progress["maximum"])

    def _log(self, message: str) -> None:
        """Write a conversion line to the internal log.

        NOTE: the on-screen Processing Log was removed, so the message goes to
        the ``pdftoolbox`` logger. Keeping the method means every existing call
        site still works and the run stays traceable from a console.
        """
        logging.getLogger("pdftoolbox").info("%s", message)

    # ---------- promo ----------

    def _fetch_promo(self, promo_conf: dict) -> None:
        data = promo.fetch_promo(
            str(promo_conf.get("url", "")),
            float(promo_conf.get("timeout_seconds", 2.0)),
        )
        self.events.put(("promo", data))

    def _show_promo(self, data) -> None:
        if not data:
            return
        latest_version = str(data.get("latest_version", ""))
        minimum_version = str(data.get("minimum_version", ""))
        download_url = str(data.get("download_url", ""))
        if (
            promo.is_below_minimum(
                __version__, minimum_version, latest_version
            )
            and promo.is_https_url(download_url)
        ):
            messagebox.showinfo(
                "Update required",
                f"PDF-X {__version__} is no longer supported. Version "
                f"{latest_version} or newer is required. PDF-X will close.\n\n"
                f"The download page will open automatically:\n{download_url}",
                parent=self.root,
            )
            webbrowser.open(download_url)
            self.root.after_idle(self.root.destroy)
            return
        if (
            promo.is_newer_version(latest_version, __version__)
            and promo.is_https_url(download_url)
        ):
            self._promo_url = download_url
            self.promo_label.configure(
                text=f"PDF-X {latest_version} is available - click to download"
            )
            return
        if not data.get("active"):
            return
        message = str(data.get("message", ""))[:140]
        url = str(data.get("url", ""))
        if message and url:
            self._promo_url = url
            self.promo_label.configure(text=message)

    def _open_promo_url(self, _event) -> None:
        if self._promo_url:
            webbrowser.open(self._promo_url)

    @staticmethod
    def _open_coffee_link(_event) -> None:
        webbrowser.open("https://buymeacoffee.com/DrLwSii")

    @staticmethod
    def _open_readme_link(_event) -> None:
        webbrowser.open("https://github.com/BorneanWingz/PDF-X/blob/main/README.md")


def run_gui() -> int:
    root = TkinterDnD.Tk()
    App(root)
    root.mainloop()
    return 0
