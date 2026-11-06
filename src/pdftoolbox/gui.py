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

from . import __author__, __version__, promo
from .config import load_config, save_config
from .convert import (
    convert_many,
    is_merge_target,
    list_targets,
    merge_pdfs,
    normalize_target,
    parse_pages,
    OCR_FIRST_TARGETS,
)
from .engines import ConversionError, EngineUnavailable
from .engines import pdf_text
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
        self.events: queue.Queue[tuple] = queue.Queue()
        self.worker: threading.Thread | None = None

        root.title(f"PDF-X {__version__}")
        root.geometry("760x560")
        root.minsize(680, 480)
        self._apply_window_icon(root)

        # Notebook with two tabs: the conversion UI and an About/credentials tab
        self.notebook = ttk.Notebook(root)
        self.notebook.pack(fill="both", expand=True)

        self.convert_tab = ttk.Frame(self.notebook)
        self.about_tab = ttk.Frame(self.notebook)
        self.notebook.add(self.convert_tab, text="Convert File")
        self.notebook.add(self.about_tab, text="About")

        self._build_file_area()
        self._build_options_area()
        self._build_action_area()
        self._build_log_area()
        self._build_promo_area()
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
        frame = ttk.LabelFrame(self.convert_tab, text="Files")
        frame.pack(fill="x", padx=8, pady=(8, 4))

        self.file_list = tk.Listbox(frame, height=6, selectmode="extended")
        self.file_list.pack(side="left", fill="both", expand=True, padx=(6, 0), pady=6)
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
            text="  blank = all pages \u00b7 ranges: 1-3,5 \u00b7 only for PDF input",
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
            text="  resolution for PNG / JPG / TIF / PPTX output",
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
            text="  resolution used when OCR reads a scanned page",
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
        frame = ttk.LabelFrame(self.convert_tab, text="Log")
        frame.pack(fill="both", expand=True, padx=8, pady=(4, 8))
        self.log = tk.Text(frame, height=10, wrap="word", state="disabled")
        self.log.pack(side="left", fill="both", expand=True, padx=(6, 0), pady=6)
        scroll = ttk.Scrollbar(frame, command=self.log.yview)
        scroll.pack(side="left", fill="y", pady=6)
        self.log.configure(yscrollcommand=scroll.set)

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

    def _build_about_area(self) -> None:
        # Credentials/About tab: author, version and a one-line description
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

    # ---------- file selection ----------

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

    # ---------- options ----------

    def _refresh_targets(self) -> None:
        options: list[tuple[str, str]] = []
        notes: list[str] = []
        seen: set[str] = set()
        # NOTE: "PDF (merge all inputs)" appears only when the current file
        # list holds two or more PDFs; merge operates on the list, not a file
        pdf_count = sum(1 for src in self.files if src.suffix.lower() == ".pdf")
        for src in self.files:
            for option in list_targets(src, pdf_count):
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
        pdf_count = sum(1 for src in self.files if src.suffix.lower() == ".pdf")
        for src in self.files:
            for option in list_targets(src, pdf_count):
                if self._label_for(option) == selection:
                    return option.key
        return selection.split(" ")[0].lower()

    def _update_option_state(self) -> None:
        # NOTE: page selection applies to per-file conversions only - a merge
        # takes whole documents, so the field is disabled for that target
        has_pdf = any(src.suffix.lower() == ".pdf" for src in self.files)
        merge_selected = is_merge_target(self._current_target_key())
        state = "normal" if (has_pdf and not merge_selected) else "disabled"
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
            if is_merge_target(target):
                # NOTE: merge is its own event type because it returns ONE
                # file for the whole selection, unlike the per-source results
                # convert_many() produces
                result = merge_pdfs(inputs, out_dir=out_dir)
                pdfs = [src for src in inputs if src.suffix.lower() == ".pdf"]
                self.events.put(
                    ("merge-done", (result, len(pdfs)))
                )
                return
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
            self.events.put(("merge-failed", str(exc)))
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
                elif kind == "merge-done":
                    result, pdf_count = payload
                    self._log(f"ok      merged {pdf_count} PDF(s) -> {result}")
                    self.status_var.set("Merge complete")
                    self.convert_button.configure(state="normal")
                    self.progress.configure(value=self.progress["maximum"])
                elif kind == "merge-failed":
                    self._log(f"FAILED  merge: {payload}")
                    self.status_var.set("Merge failed")
                    self.convert_button.configure(state="normal")
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


def run_gui() -> int:
    root = tk.Tk()
    App(root)
    root.mainloop()
    return 0
