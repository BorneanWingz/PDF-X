"""Tkinter GUI: zero extra dependencies, fully offline.

Threading rule: all conversions run on a worker thread; results are pushed
back through a queue and rendered from an ``after`` poll, so the window
never freezes and Tk is only touched from the main thread.
"""

from __future__ import annotations

import queue
import threading
import tkinter as tk
import webbrowser
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


class App:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.config = load_config()
        self.files: list[Path] = []
        self.merge_files: list[Path] = []
        self.edit_source: Path | None = None
        self.edit_pages: list[int] = []
        self.edit_rotations: dict[int, int] = {}
        self.events: queue.Queue[tuple] = queue.Queue()
        self.worker: threading.Thread | None = None

        root.title(f"PDF-X {__version__}")
        root.geometry("760x560")
        root.minsize(680, 480)
        self._apply_window_icon(root)

        # Notebook: Convert File, Merge PDF, Edit PDF, and About
        self.notebook = ttk.Notebook(root)
        self.notebook.pack(fill="both", expand=True)

        self.convert_tab = ttk.Frame(self.notebook)
        self.merge_tab = ttk.Frame(self.notebook)
        self.edit_tab = ttk.Frame(self.notebook)
        self.about_tab = ttk.Frame(self.notebook)
        self.notebook.add(self.convert_tab, text="Convert File")
        self.notebook.add(self.merge_tab, text="Merge PDF")
        self.notebook.add(self.edit_tab, text="Edit PDF")
        self.notebook.add(self.about_tab, text="About")

        self._build_file_area()
        self._build_options_area()
        self._build_action_area()
        self._build_log_area()
        self._build_promo_area()
        self._build_merge_area()
        self._build_edit_area()
        self._build_about_area()

        self._refresh_targets()
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

    def _build_file_area(self) -> None:
        frame = ttk.LabelFrame(self.convert_tab, text="Files (drop files here)")
        frame.pack(fill="x", padx=8, pady=(8, 4))

        self.file_list = tk.Listbox(frame, height=6, selectmode="extended")
        self.file_list.pack(side="left", fill="both", expand=True, padx=(6, 0), pady=6)
        self.file_list.drop_target_register(DND_FILES)
        self.file_list.dnd_bind("<<Drop>>", self._on_file_drop)
        scroll = ttk.Scrollbar(frame, command=self.file_list.yview)
        scroll.pack(side="left", fill="y", pady=6)
        self.file_list.configure(yscrollcommand=scroll.set)

        side = ttk.Frame(frame)
        side.pack(side="left", fill="y", padx=6)
        ttk.Button(side, text="Add files", command=self.add_files).pack(fill="x", pady=(4, 2))
        ttk.Button(side, text="Add folder", command=self.add_folder).pack(fill="x", pady=2)
        ttk.Button(side, text="Remove", command=self.remove_selected).pack(fill="x", pady=2)
        ttk.Button(side, text="Clear", command=self.clear_files).pack(fill="x", pady=(2, 4))

    def _build_options_area(self) -> None:
        frame = ttk.LabelFrame(self.convert_tab, text="Conversion options")
        frame.pack(fill="x", padx=8, pady=4)
        frame.columnconfigure(3, weight=1)

        ttk.Label(frame, text="Convert to:").grid(row=0, column=0, sticky="w", padx=6, pady=4)
        self.target_var = tk.StringVar()
        self.target_box = ttk.Combobox(
            frame, textvariable=self.target_var, state="readonly", width=22
        )
        self.target_box.grid(row=0, column=1, sticky="w", padx=6, pady=4)
        self.target_box.bind("<<ComboboxSelected>>", lambda _e: self._update_option_state())

        # ---------- pages ----------
        ttk.Label(frame, text="Pages:").grid(row=1, column=0, sticky="w", padx=6, pady=4)
        pages_row = ttk.Frame(frame)
        pages_row.grid(row=1, column=1, columnspan=3, sticky="ew", pady=4)
        self.pages_var = tk.StringVar()
        self.pages_entry = ttk.Entry(pages_row, textvariable=self.pages_var, width=18)
        self.pages_entry.pack(side="left")
        # NOTE: the help text sits next to the field so the syntax is obvious
        # without leaving the window (blank = every page)
        ttk.Label(
            pages_row,
            text="  Blank = all pages \u00b7 Example ranges: 1-3,5 \u00b7 Only for PDF input",
            foreground="#555",
        ).pack(side="left")

        # ---------- output ----------
        ttk.Label(frame, text="Output folder:").grid(row=2, column=0, sticky="w", padx=6, pady=4)
        self.out_var = tk.StringVar(value=str(self.config.get("out_dir", "")))
        # NOTE: entry and button are kept as attributes so the "Output in same
        # folder" checkbox can disable both together
        self.out_entry = ttk.Entry(frame, textvariable=self.out_var)
        self.out_entry.grid(row=2, column=1, columnspan=2, sticky="ew", pady=4)
        self.browse_button = ttk.Button(frame, text="Browse", command=self.pick_output)
        self.browse_button.grid(row=2, column=3, sticky="e", padx=6, pady=4)

        self.same_folder_var = tk.BooleanVar(
            value=bool(self.config.get("same_folder", False))
        )
        ttk.Checkbutton(
            frame,
            text="Output in same folder",
            variable=self.same_folder_var,
            command=self._toggle_same_folder,
        ).grid(row=3, column=1, columnspan=3, sticky="w", padx=6, pady=(0, 4))
        self._update_output_state()

        # ---------- advanced (collapsed by default) ----------
        self._build_advanced_area(frame, row=4)

        self.target_note = ttk.Label(frame, text="", foreground="#555")
        self.target_note.grid(row=6, column=0, columnspan=4, sticky="w", padx=6, pady=(0, 6))

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
        )
        self.advanced_button.grid(row=row, column=0, columnspan=2, sticky="w", padx=6, pady=(2, 4))

        # NOTE: never gridded until opened - grid_remove() alone still reserves
        # the row, which would leave an empty gap in the collapsed state
        self.advanced_frame = ttk.Frame(parent)
        self.advanced_frame.columnconfigure(5, weight=1)

        ttk.Label(self.advanced_frame, text="Image DPI:").grid(
            row=0, column=0, sticky="w", pady=2
        )
        self.dpi_var = tk.StringVar(value=str(self.config.get("dpi", 150)))
        ttk.Spinbox(
            self.advanced_frame, from_=72, to=600, width=6, textvariable=self.dpi_var
        ).grid(row=0, column=1, sticky="w", padx=(4, 0), pady=2)
        ttk.Label(
            self.advanced_frame,
            text="  Resolution for PNG / JPG / TIF / PPTX output",
            foreground="#555",
        ).grid(row=0, column=2, sticky="w", pady=2)

        ttk.Label(self.advanced_frame, text="OCR DPI:").grid(
            row=1, column=0, sticky="w", pady=2
        )
        self.ocr_dpi_var = tk.StringVar(value=str(self.config.get("ocr_dpi", 200)))
        ttk.Spinbox(
            self.advanced_frame, from_=100, to=600, width=6, textvariable=self.ocr_dpi_var
        ).grid(row=1, column=1, sticky="w", padx=(4, 0), pady=2)
        ttk.Label(
            self.advanced_frame,
            text="  Resolution used when OCR reads a scanned page",
            foreground="#555",
        ).grid(row=1, column=2, sticky="w", pady=2)

    def _toggle_advanced(self) -> None:
        if self.advanced_open:
            self.advanced_frame.grid_remove()
            self.advanced_button.configure(text="\u25b8 Advanced Options")
        else:
            self.advanced_frame.grid(row=5, column=0, columnspan=4, sticky="ew", padx=6, pady=(0, 4))
            self.advanced_button.configure(text="\u25be Advanced Options")
        self.advanced_open = not self.advanced_open

    def _build_action_area(self) -> None:
        frame = ttk.Frame(self.convert_tab)
        frame.pack(fill="x", padx=8, pady=4)
        self.convert_button = ttk.Button(frame, text="Convert", command=self.start_convert)
        self.convert_button.pack(side="left")
        self.progress = ttk.Progressbar(frame, mode="determinate")
        self.progress.pack(side="left", fill="x", expand=True, padx=8)
        self.status_var = tk.StringVar(value="Ready")
        ttk.Label(frame, textvariable=self.status_var).pack(side="left")

    def _build_log_area(self) -> None:
        self.log_open = False
        self.log_button = ttk.Button(
            self.convert_tab,
            text="\u25b8 Processing Log",
            command=self._toggle_log,
        )
        self.log_button.pack(anchor="w", padx=8, pady=(4, 0))
        frame = ttk.LabelFrame(self.convert_tab, text="Processing Log")
        self.log_frame = frame
        self.log = tk.Text(frame, height=10, wrap="word", state="disabled")
        self.log.pack(side="left", fill="both", expand=True, padx=(6, 0), pady=6)
        scroll = ttk.Scrollbar(frame, command=self.log.yview)
        scroll.pack(side="left", fill="y", pady=6)
        self.log.configure(yscrollcommand=scroll.set)

    def _toggle_log(self) -> None:
        if self.log_open:
            self.log_frame.pack_forget()
            self.log_button.configure(text="\u25b8 Processing Log")
        else:
            self.log_frame.pack(fill="both", expand=True, padx=8, pady=(2, 8))
            self.log_button.configure(text="\u25be Processing Log")
        self.log_open = not self.log_open

    def _build_promo_area(self) -> None:
        self.promo_label = tk.Label(self.convert_tab, text="", anchor="w", fg="#0a58ca", cursor="hand2")
        self.promo_label.bind("<Button-1>", self._open_promo_url)
        self._promo_url = ""
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
        intro = ttk.Label(
            self.merge_tab,
            text=(
                "Combine any files into one PDF. Each file is converted to PDF "
                "first, then merged in the order shown below."
            ),
            foreground="#555",
            wraplength=700,
            justify="left",
        )
        intro.pack(anchor="w", padx=8, pady=(8, 4))

        frame = ttk.LabelFrame(self.merge_tab, text="Files to merge (drag to reorder)")
        frame.pack(fill="both", expand=True, padx=8, pady=4)

        self.merge_list = tk.Listbox(frame, height=8, selectmode="extended")
        self.merge_list.pack(side="left", fill="both", expand=True, padx=(6, 0), pady=6)
        self.merge_list.drop_target_register(DND_FILES)
        self.merge_list.dnd_bind("<<Drop>>", self._on_merge_drop)
        # NOTE: click-and-drag inside the list reorders it; numbering is redrawn
        # on release so "1." always sits on the first item
        self.merge_list.bind("<Button-1>", self._on_merge_drag_start, add="+")
        self.merge_list.bind("<B1-Motion>", self._on_merge_drag_motion)
        self.merge_list.bind("<ButtonRelease-1>", self._on_merge_drag_drop)
        scroll = ttk.Scrollbar(frame, command=self.merge_list.yview)
        scroll.pack(side="left", fill="y", pady=6)
        self.merge_list.configure(yscrollcommand=scroll.set)

        side = ttk.Frame(frame)
        side.pack(side="left", fill="y", padx=6)
        ttk.Button(side, text="Add files", command=self.add_merge_files).pack(fill="x", pady=(4, 2))
        ttk.Button(side, text="Remove", command=self.remove_merge_selected).pack(fill="x", pady=2)
        ttk.Button(side, text="Clear", command=self.clear_merge_files).pack(fill="x", pady=2)
        ttk.Separator(side, orient="horizontal").pack(fill="x", pady=4)
        ttk.Button(side, text="Move Up", command=self.move_merge_up).pack(fill="x", pady=2)
        ttk.Button(side, text="Move Down", command=self.move_merge_down).pack(fill="x", pady=(2, 4))

        self._build_merge_output_area()

    def _build_merge_output_area(self) -> None:
        frame = ttk.LabelFrame(self.merge_tab, text="Merge options")
        frame.pack(fill="x", padx=8, pady=4)
        frame.columnconfigure(3, weight=1)

        ttk.Label(frame, text="Output folder:").grid(row=0, column=0, sticky="w", padx=6, pady=4)
        self.merge_out_var = tk.StringVar(value=str(self.config.get("merge_out_dir", "")))
        self.merge_out_entry = ttk.Entry(frame, textvariable=self.merge_out_var)
        self.merge_out_entry.grid(row=0, column=1, columnspan=2, sticky="ew", pady=4)
        self.merge_browse_button = ttk.Button(
            frame, text="Browse", command=self.pick_merge_output
        )
        self.merge_browse_button.grid(row=0, column=3, sticky="e", padx=6, pady=4)

        self.merge_same_folder_var = tk.BooleanVar(
            value=bool(self.config.get("merge_same_folder", True))
        )
        ttk.Checkbutton(
            frame,
            text="Output in same folder as the first file",
            variable=self.merge_same_folder_var,
            command=self._toggle_merge_same_folder,
        ).grid(row=1, column=1, columnspan=3, sticky="w", padx=6, pady=(0, 4))
        self._update_merge_output_state()

        action = ttk.Frame(self.merge_tab)
        action.pack(fill="x", padx=8, pady=4)
        self.merge_button = ttk.Button(
            action, text="Merge to PDF", command=self.start_merge
        )
        self.merge_button.pack(side="left")
        self.merge_progress = ttk.Progressbar(action, mode="determinate")
        self.merge_progress.pack(side="left", fill="x", expand=True, padx=8)
        self.merge_status_var = tk.StringVar(value="Ready")
        ttk.Label(action, textvariable=self.merge_status_var).pack(side="left")

        # NOTE: same disclosure pattern as the Convert File log - the frame is
        # pack_forget() when collapsed so it reserves NO vertical space at all
        self.merge_log_open = False
        self.merge_log_button = ttk.Button(
            self.merge_tab,
            text="\u25b8 Processing Log",
            command=self._toggle_merge_log,
        )
        self.merge_log_button.pack(anchor="w", padx=8, pady=(4, 0))
        log_frame = ttk.LabelFrame(self.merge_tab, text="Processing Log")
        self.merge_log_frame = log_frame
        self.merge_log = tk.Text(log_frame, height=8, wrap="word", state="disabled")
        self.merge_log.pack(side="left", fill="both", expand=True, padx=(6, 0), pady=6)
        log_scroll = ttk.Scrollbar(log_frame, command=self.merge_log.yview)
        log_scroll.pack(side="left", fill="y", pady=6)
        self.merge_log.configure(yscrollcommand=log_scroll.set)

    def _toggle_merge_log(self) -> None:
        if self.merge_log_open:
            self.merge_log_frame.pack_forget()
            self.merge_log_button.configure(text="\u25b8 Processing Log")
        else:
            self.merge_log_frame.pack(fill="both", expand=True, padx=8, pady=(2, 8))
            self.merge_log_button.configure(text="\u25be Processing Log")
        self.merge_log_open = not self.merge_log_open
    # ---------- edit tab ----------

    def _build_edit_area(self) -> None:
        """Edit PDF tab: page organise, split/extract, and stamps.

        Page operations (reorder, rotate, delete) are the core of both editors
        this tab is modelled on; split/extract and the watermark/page-number
        stamps are the two most-used extras they share.
        """
        source_row = ttk.Frame(self.edit_tab)
        source_row.pack(fill="x", padx=8, pady=(8, 4))
        self.edit_source_var = tk.StringVar(value="No PDF loaded")
        ttk.Button(source_row, text="Open PDF", command=self.open_edit_pdf).pack(side="left")
        ttk.Label(source_row, textvariable=self.edit_source_var, foreground="#555").pack(
            side="left", padx=8
        )

        self.edit_notebook = ttk.Notebook(self.edit_tab)
        self.edit_notebook.pack(fill="both", expand=True, padx=8, pady=4)
        self.organize_tab = ttk.Frame(self.edit_notebook)
        self.split_tab = ttk.Frame(self.edit_notebook)
        self.stamp_tab = ttk.Frame(self.edit_notebook)
        self.edit_notebook.add(self.organize_tab, text="Organize Pages")
        self.edit_notebook.add(self.split_tab, text="Split / Extract")
        self.edit_notebook.add(self.stamp_tab, text="Watermark / Numbers")

        self._build_organize_area()
        self._build_split_area()
        self._build_stamp_area()
        self._build_edit_output_area()

    def _build_organize_area(self) -> None:
        frame = ttk.LabelFrame(self.organize_tab, text="Pages (drag to reorder)")
        frame.pack(fill="both", expand=True, padx=6, pady=6)

        self.page_list = tk.Listbox(frame, height=10, selectmode="extended")
        self.page_list.pack(side="left", fill="both", expand=True, padx=(6, 0), pady=6)
        self.page_list.bind("<Button-1>", self._on_page_drag_start, add="+")
        self.page_list.bind("<B1-Motion>", self._on_page_drag_motion)
        self.page_list.bind("<ButtonRelease-1>", self._on_page_drag_drop)
        scroll = ttk.Scrollbar(frame, command=self.page_list.yview)
        scroll.pack(side="left", fill="y", pady=6)
        self.page_list.configure(yscrollcommand=scroll.set)

        side = ttk.Frame(frame)
        side.pack(side="left", fill="y", padx=6)
        ttk.Button(side, text="Move Up", command=self.move_page_up).pack(fill="x", pady=(4, 2))
        ttk.Button(side, text="Move Down", command=self.move_page_down).pack(fill="x", pady=2)
        ttk.Button(side, text="Rotate 90\u00b0", command=self.rotate_page_cw).pack(fill="x", pady=2)
        ttk.Button(side, text="Rotate 180\u00b0", command=self.rotate_page_180).pack(fill="x", pady=2)
        ttk.Button(side, text="Delete Page", command=self.delete_page).pack(fill="x", pady=2)
        ttk.Button(side, text="Reset", command=self.reset_pages).pack(fill="x", pady=(2, 4))

    def _build_edit_output_area(self) -> None:
        out_row = ttk.Frame(self.edit_tab)
        out_row.pack(fill="x", padx=8, pady=(0, 4))
        ttk.Label(out_row, text="Output folder:").pack(side="left")
        self.edit_out_var = tk.StringVar(value=str(self.config.get("edit_out_dir", "")))
        ttk.Entry(out_row, textvariable=self.edit_out_var).pack(
            side="left", fill="x", expand=True, padx=6
        )
        ttk.Button(out_row, text="Browse", command=self.pick_edit_output).pack(side="left")
        ttk.Label(
            out_row, text="  blank = beside the PDF", foreground="#555"
        ).pack(side="left")

        action = ttk.Frame(self.edit_tab)
        action.pack(fill="x", padx=8, pady=4)
        self.edit_apply_button = ttk.Button(
            action, text="Apply Page Changes", command=self.run_organize
        )
        self.edit_apply_button.pack(side="left")
        ttk.Label(
            action,
            text="  Saves the reordered / rotated / trimmed pages as a new PDF.",
            foreground="#555",
        ).pack(side="left")
        self.edit_progress = ttk.Progressbar(action, mode="determinate")
        self.edit_progress.pack(side="left", fill="x", expand=True, padx=8)
        self.edit_status_var = tk.StringVar(value="Ready")
        ttk.Label(action, textvariable=self.edit_status_var).pack(side="left")

        self.edit_log_open = False
        self.edit_log_button = ttk.Button(
            self.edit_tab,
            text="\u25b8 Processing Log",
            command=self._toggle_edit_log,
        )
        self.edit_log_button.pack(anchor="w", padx=8, pady=(4, 0))
        log_frame = ttk.LabelFrame(self.edit_tab, text="Processing Log")
        self.edit_log_frame = log_frame
        self.edit_log = tk.Text(log_frame, height=8, wrap="word", state="disabled")
        self.edit_log.pack(side="left", fill="both", expand=True, padx=(6, 0), pady=6)
        log_scroll = ttk.Scrollbar(log_frame, command=self.edit_log.yview)
        log_scroll.pack(side="left", fill="y", pady=6)
        self.edit_log.configure(yscrollcommand=log_scroll.set)

    def _toggle_edit_log(self) -> None:
        if self.edit_log_open:
            self.edit_log_frame.pack_forget()
            self.edit_log_button.configure(text="\u25b8 Processing Log")
        else:
            self.edit_log_frame.pack(fill="both", expand=True, padx=8, pady=(2, 8))
            self.edit_log_button.configure(text="\u25be Processing Log")
        self.edit_log_open = not self.edit_log_open

    def _build_split_area(self) -> None:
        frame = ttk.LabelFrame(self.split_tab, text="Split every N pages")
        frame.pack(fill="x", padx=6, pady=6)
        ttk.Label(frame, text="Pages per file:").grid(row=0, column=0, sticky="w", padx=6, pady=6)
        self.split_every_var = tk.StringVar(value="1")
        ttk.Spinbox(
            frame, from_=1, to=1000, width=6, textvariable=self.split_every_var
        ).grid(row=0, column=1, sticky="w", padx=(4, 0), pady=6)
        ttk.Button(frame, text="Split PDF", command=self.run_split).grid(
            row=0, column=2, sticky="w", padx=8, pady=6
        )
        ttk.Label(
            frame,
            text="  One output file per chunk (a 10-page PDF in 3s -> 4 files).",
            foreground="#555",
        ).grid(row=0, column=3, sticky="w", pady=6)

        extract = ttk.LabelFrame(self.split_tab, text="Extract a page range")
        extract.pack(fill="x", padx=6, pady=6)
        ttk.Label(extract, text="Pages:").grid(row=0, column=0, sticky="w", padx=6, pady=6)
        self.extract_pages_var = tk.StringVar(value="")
        ttk.Entry(extract, textvariable=self.extract_pages_var, width=24).grid(
            row=0, column=1, sticky="w", padx=(4, 0), pady=6
        )
        ttk.Button(extract, text="Extract", command=self.run_extract).grid(
            row=0, column=2, sticky="w", padx=8, pady=6
        )
        ttk.Label(
            extract,
            text="  1-based, e.g. 1-3,5. Kept in the order given, into one PDF.",
            foreground="#555",
        ).grid(row=0, column=3, sticky="w", pady=6)

    def _build_stamp_area(self) -> None:
        mark = ttk.LabelFrame(self.stamp_tab, text="Watermark")
        mark.pack(fill="x", padx=6, pady=6)
        ttk.Label(mark, text="Text:").grid(row=0, column=0, sticky="w", padx=6, pady=6)
        self.watermark_var = tk.StringVar(value="CONFIDENTIAL")
        ttk.Entry(mark, textvariable=self.watermark_var, width=30).grid(
            row=0, column=1, columnspan=2, sticky="w", padx=(4, 0), pady=6
        )
        self.watermark_diagonal_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            mark, text="Diagonal", variable=self.watermark_diagonal_var
        ).grid(row=1, column=1, sticky="w", padx=(4, 0), pady=(0, 6))
        ttk.Button(mark, text="Add Watermark", command=self.run_watermark).grid(
            row=0, column=3, sticky="w", padx=8, pady=6
        )

        numbers = ttk.LabelFrame(self.stamp_tab, text="Page numbers")
        numbers.pack(fill="x", padx=6, pady=6)
        ttk.Label(numbers, text="Pattern:").grid(row=0, column=0, sticky="w", padx=6, pady=6)
        self.number_pattern_var = tk.StringVar(value="Page {page} of {total}")
        ttk.Entry(numbers, textvariable=self.number_pattern_var, width=30).grid(
            row=0, column=1, sticky="w", padx=(4, 0), pady=6
        )
        ttk.Label(numbers, text="Position:").grid(row=1, column=0, sticky="w", padx=6, pady=6)
        self.number_position_var = tk.StringVar(value="bottom-center")
        ttk.Combobox(
            numbers,
            textvariable=self.number_position_var,
            state="readonly",
            width=16,
            values=["bottom-center", "bottom-right", "bottom-left", "top-right", "top-center"],
        ).grid(row=1, column=1, sticky="w", padx=(4, 0), pady=6)
        ttk.Button(numbers, text="Add Numbers", command=self.run_page_numbers).grid(
            row=0, column=3, rowspan=2, sticky="w", padx=8, pady=6
        )
        ttk.Label(
            numbers,
            text="  {page} = number, {total} = page count.",
            foreground="#555",
        ).grid(row=2, column=0, columnspan=4, sticky="w", padx=6, pady=(0, 6))

    def _build_about_area(self) -> None:
        ttk.Label(
            self.about_tab, text="PDF-X", font=("TkDefaultFont", 16, "bold")
        ).pack(anchor="w", padx=16, pady=(16, 2))
        ttk.Label(
            self.about_tab, text="Portable offline PDF converter and OCR toolbox."
        ).pack(anchor="w", padx=16, pady=(0, 12))

        info = ttk.Frame(self.about_tab)
        info.pack(anchor="w", padx=16, fill="x")
        ttk.Label(info, text="Author:", font=("TkDefaultFont", 10, "bold")).grid(
            row=0, column=0, sticky="w", pady=2
        )
        ttk.Label(info, text=__author__).grid(row=0, column=1, sticky="w", padx=(8, 0), pady=2)
        ttk.Label(info, text="Version:", font=("TkDefaultFont", 10, "bold")).grid(
            row=1, column=0, sticky="w", pady=2
        )
        ttk.Label(info, text=__version__).grid(row=1, column=1, sticky="w", padx=(8, 0), pady=2)

        coffee = ttk.Frame(self.about_tab)
        coffee.pack(side="bottom", anchor="w", padx=16, pady=16)
        ttk.Label(coffee, text="Like what I built? Consider ").pack(side="left")
        coffee_link = tk.Label(
            coffee,
            text="buying me a cuppa",
            fg="#0a58ca",
            cursor="hand2",
            font=("TkDefaultFont", 9, "underline"),
        )
        coffee_link.pack(side="left")
        coffee_link.bind("<Button-1>", self._open_coffee_link)
        ttk.Label(coffee, text="!").pack(side="left")

    # ---------- file selection ----------

    def _on_file_drop(self, event) -> None:
        paths = self.root.tk.splitlist(event.data)
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
        """The Organize list as shown: "1. Page 3 (90\u00b0)".

        NOTE: the leading number is the POSITION in the new document; the page
        number and rotation follow it. Pure so the rule is unit-testable.
        """
        labels: list[str] = []
        for position, source_page in enumerate(pages, start=1):
            angle = rotations.get(source_page, 0) % 360
            suffix = f" ({angle}\u00b0)" if angle else ""
            labels.append(f"{position}. Page {source_page}{suffix}")
        return labels

    def open_edit_pdf(self) -> None:
        paths = filedialog.askopenfilenames(
            title="Open a PDF to edit",
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
        self.edit_source = source
        self.edit_pages = list(range(1, count + 1))
        self.edit_rotations = {}
        self.edit_source_var.set(f"{source.name}  ({count} pages)")
        self._remember_dir(source.resolve().parent)
        self._refresh_page_list()
        self.edit_status_var.set("Ready")

    def _refresh_page_list(self) -> None:
        self.page_list.delete(0, "end")
        for label in self.page_labels(self.edit_pages, self.edit_rotations):
            self.page_list.insert("end", label)

    def _edit_ready(self) -> bool:
        if self.edit_source is None:
            messagebox.showinfo("PDF-X", "Open a PDF first.")
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
        self._rotate_pages(90)

    def rotate_page_180(self) -> None:
        self._rotate_pages(180)

    def _rotate_pages(self, angle: int) -> None:
        for position in self._selected_page_positions():
            source_page = self.edit_pages[position]
            # NOTE: rotation is keyed by SOURCE page, so a turn sticks to the
            # page even after it is moved elsewhere in the list
            self.edit_rotations[source_page] = (
                self.edit_rotations.get(source_page, 0) + angle
            ) % 360
        self._refresh_page_list()

    def delete_page(self) -> None:
        selection = self._selected_page_positions()
        if not selection:
            return
        for index in reversed(selection):
            del self.edit_pages[index]
        if not self.edit_pages:
            messagebox.showwarning("PDF-X", "Every page was deleted; resetting.")
            self.reset_pages()
            return
        self._refresh_page_list()

    def reset_pages(self) -> None:
        if self.edit_source is None:
            return
        count = pdf_edit.page_count(self.edit_source)
        self.edit_pages = list(range(1, count + 1))
        self.edit_rotations = {}
        self._refresh_page_list()

    def _on_page_drag_start(self, event) -> None:
        self._page_drag_index = self.page_list.nearest(event.y)

    def _on_page_drag_motion(self, event) -> None:
        index = self.page_list.nearest(event.y)
        current = getattr(self, "_page_drag_index", None)
        if current is None or current == index or index < 0:
            return
        if index >= len(self.edit_pages):
            return
        item = self.edit_pages.pop(current)
        self.edit_pages.insert(index, item)
        self._page_drag_index = index
        self._refresh_page_list()

    def _on_page_drag_drop(self, _event) -> None:
        self._page_drag_index = None
        self._refresh_page_list()


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
        text = self.edit_out_var.get().strip()
        return Path(text) if text else None

    def pick_edit_output(self) -> None:
        current = self.edit_out_var.get().strip()
        start = current if current and Path(current).is_dir() else self._dialog_dir()
        folder = filedialog.askdirectory(title="Select output folder", initialdir=start)
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

    def _edit_log_write(self, message: str) -> None:
        self.edit_log.configure(state="normal")
        self.edit_log.insert("end", message + "\n")
        self.edit_log.see("end")
        self.edit_log.configure(state="disabled")

    def _report_edit_result(self, result, note: str) -> None:
        """Log one path or a list of paths from an edit operation."""
        if isinstance(result, (list, tuple)):
            for path in result:
                self._edit_log_write(f"ok      {path}")
            self.edit_status_var.set(f"{note}: {len(result)} file(s)")
        else:
            self._edit_log_write(f"ok      {result}")
            self.edit_status_var.set(note)
        self._set_edit_busy(False)

    def run_organize(self) -> None:
        if not self.edit_pages:
            messagebox.showinfo("PDF-X", "No pages to save.")
            return
        src = self.edit_source
        order = list(self.edit_pages)
        rotations = dict(self.edit_rotations)
        target = self._edit_output_target(src)

        def work():
            return pdf_edit.organize(src, target, order=order, rotations=rotations)

        self._run_edit_task(work, "Saved reordered PDF")

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
            self._remember_dir(Path(added).expanduser().resolve().parent)
        self._refresh_targets()

    def remove_selected(self) -> None:
        for index in sorted(self.file_list.curselection(), reverse=True):
            self.file_list.delete(index)
            del self.files[index]
        self._refresh_targets()

    def clear_files(self) -> None:
        self.file_list.delete(0, "end")
        self.files.clear()
        self._refresh_targets()
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
        self._refresh_merge_list()

    def _on_merge_drag_drop(self, _event) -> None:
        self._merge_drag_index = None
        self._refresh_merge_list()

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
        self.merge_log.configure(state="normal")
        self.merge_log.insert("end", message + "\n")
        self.merge_log.see("end")
        self.merge_log.configure(state="disabled")

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
        # NOTE: merge lives on its own tab now, so the file list here no longer
        # affects the target list - pdf_count stays 0 to keep "merge" out
        for src in self.files:
            for option in list_targets(src, 0):
                if option.key in seen:
                    continue
                seen.add(option.key)
                label = self._label_for(option)
                options.append((option.key, label))
                if not option.available and option.note:
                    notes.append(f"{option.label}: {option.note}")

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
                elif kind == "edit-failed":
                    self._edit_log_write(f"FAILED  edit: {payload}")
                    self.edit_status_var.set("Edit failed")
                    self._set_edit_busy(False)
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
        self.log.configure(state="normal")
        self.log.insert("end", message + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    # ---------- promo ----------

    def _fetch_promo(self, promo_conf: dict) -> None:
        data = promo.fetch_promo(
            str(promo_conf.get("url", "")),
            float(promo_conf.get("timeout_seconds", 2.0)),
        )
        self.events.put(("promo", data))

    def _show_promo(self, data) -> None:
        if not data or not data.get("active"):
            return
        message = str(data.get("message", ""))[:140]
        url = str(data.get("url", ""))
        if message and url:
            self._promo_url = url
            self.promo_label.configure(text=message)
            self.promo_label.pack(fill="x", padx=8, pady=(0, 6))

    def _open_promo_url(self, _event) -> None:
        if self._promo_url:
            webbrowser.open(self._promo_url)

    @staticmethod
    def _open_coffee_link(_event) -> None:
        webbrowser.open("https://buymeacoffee.com/DrLwSii")


def run_gui() -> int:
    root = TkinterDnD.Tk()
    App(root)
    root.mainloop()
    return 0
