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

from . import __version__, promo
from .config import load_config, save_config
from .convert import convert_many, list_targets, parse_pages
from .engines import ConversionError, EngineUnavailable


images_suffixes = [".png", ".jpg", ".jpeg", ".bmp", ".webp", ".tif", ".tiff", ".gif"]
office_suffixes = [
    ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
    ".odt", ".ods", ".odp", ".rtf", ".csv",
]


class App:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.config = load_config()
        self.files: list[Path] = []
        self.events: queue.Queue[tuple] = queue.Queue()
        self.worker: threading.Thread | None = None

        root.title(f"PDF Toolbox {__version__}")
        root.geometry("760x560")
        root.minsize(680, 480)

        self._build_file_area()
        self._build_options_area()
        self._build_action_area()
        self._build_log_area()
        self._build_promo_area()

        self._refresh_targets()
        # NOTE: the queue + after() poll is the ONLY bridge from worker
        # threads back to Tk - Tk widgets must never be touched off-thread
        self._poll_events()

    # ---------- layout ----------

    def _build_file_area(self) -> None:
        frame = ttk.LabelFrame(self.root, text="Files")
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
        frame = ttk.LabelFrame(self.root, text="Conversion options")
        frame.pack(fill="x", padx=8, pady=4)
        frame.columnconfigure(5, weight=1)

        ttk.Label(frame, text="Convert to:").grid(row=0, column=0, sticky="w", padx=6, pady=4)
        self.target_var = tk.StringVar()
        self.target_box = ttk.Combobox(frame, textvariable=self.target_var, state="readonly", width=22)
        self.target_box.grid(row=0, column=1, sticky="w", padx=6, pady=4)
        self.target_box.bind("<<ComboboxSelected>>", lambda _e: self._update_option_state())

        ttk.Label(frame, text="Image DPI:").grid(row=0, column=2, sticky="e", padx=(12, 4))
        self.dpi_var = tk.StringVar(value=str(self.config.get("dpi", 150)))
        ttk.Spinbox(frame, from_=72, to=600, width=6, textvariable=self.dpi_var).grid(
            row=0, column=3, sticky="w", pady=4
        )

        ttk.Label(frame, text="OCR DPI:").grid(row=0, column=4, sticky="e", padx=(12, 4))
        self.ocr_dpi_var = tk.StringVar(value=str(self.config.get("ocr_dpi", 200)))
        ttk.Spinbox(frame, from_=100, to=600, width=6, textvariable=self.ocr_dpi_var).grid(
            row=0, column=5, sticky="w", pady=4
        )

        ttk.Label(frame, text="Pages (e.g. 1-3,5):").grid(
            row=1, column=0, sticky="w", padx=6, pady=4
        )
        self.pages_var = tk.StringVar()
        self.pages_entry = ttk.Entry(frame, textvariable=self.pages_var, width=18)
        self.pages_entry.grid(row=1, column=1, sticky="w", padx=6, pady=4)

        ttk.Label(frame, text="Output folder:").grid(row=1, column=2, sticky="e", padx=(12, 4))
        self.out_var = tk.StringVar(value=str(self.config.get("out_dir", "")))
        ttk.Entry(frame, textvariable=self.out_var).grid(
            row=1, column=3, columnspan=2, sticky="ew", pady=4
        )
        ttk.Button(frame, text="Browse", command=self.pick_output).grid(
            row=1, column=5, sticky="e", padx=6, pady=4
        )

        self.target_note = ttk.Label(frame, text="", foreground="#555")
        self.target_note.grid(row=2, column=0, columnspan=6, sticky="w", padx=6, pady=(0, 6))

    def _build_action_area(self) -> None:
        frame = ttk.Frame(self.root)
        frame.pack(fill="x", padx=8, pady=4)
        self.convert_button = ttk.Button(frame, text="Convert", command=self.start_convert)
        self.convert_button.pack(side="left")
        self.progress = ttk.Progressbar(frame, mode="determinate")
        self.progress.pack(side="left", fill="x", expand=True, padx=8)
        self.status_var = tk.StringVar(value="Ready")
        ttk.Label(frame, textvariable=self.status_var).pack(side="left")

    def _build_log_area(self) -> None:
        frame = ttk.LabelFrame(self.root, text="Log")
        frame.pack(fill="both", expand=True, padx=8, pady=(4, 8))
        self.log = tk.Text(frame, height=10, wrap="word", state="disabled")
        self.log.pack(side="left", fill="both", expand=True, padx=(6, 0), pady=6)
        scroll = ttk.Scrollbar(frame, command=self.log.yview)
        scroll.pack(side="left", fill="y", pady=6)
        self.log.configure(yscrollcommand=scroll.set)

    def _build_promo_area(self) -> None:
        self.promo_label = tk.Label(self.root, text="", anchor="w", fg="#0a58ca", cursor="hand2")
        self.promo_label.bind("<Button-1>", self._open_promo_url)
        self._promo_url = ""
        promo_conf = self.config.get("promo", {})
        if promo_conf.get("enabled", True) and promo_conf.get("url"):
            # NOTE: daemon=True so a hung network call can never keep the
            # app alive after the window closes
            thread = threading.Thread(target=self._fetch_promo, args=(promo_conf,), daemon=True)
            thread.start()

    # ---------- file selection ----------

    def add_files(self) -> None:
        paths = filedialog.askopenfilenames(
            title="Select files",
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
        folder = filedialog.askdirectory(title="Select folder")
        if not folder:
            return
        supported = {".pdf", *images_suffixes, ".md", ".markdown", ".txt", *office_suffixes}
        found = [
            path for path in Path(folder).iterdir()
            if path.is_file() and path.suffix.lower() in supported
        ]
        self._add_paths(found)

    def _add_paths(self, paths: list[Path]) -> None:
        for path in paths:
            if path.is_file() and path not in self.files:
                self.files.append(path)
                self.file_list.insert("end", str(path))
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
        for src in self.files:
            for option in list_targets(src):
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
            for option in list_targets(src):
                if self._label_for(option) == selection:
                    return option.key
        return selection.split(" ")[0].lower()

    def _update_option_state(self) -> None:
        has_pdf = any(src.suffix.lower() == ".pdf" for src in self.files)
        self.pages_entry.configure(state="normal" if has_pdf else "disabled")

    def pick_output(self) -> None:
        folder = filedialog.askdirectory(title="Select output folder")
        if folder:
            self.out_var.set(folder)

    # ---------- conversion ----------

    def start_convert(self) -> None:
        if self.worker and self.worker.is_alive():
            return
        if not self.files:
            messagebox.showinfo("PDF Toolbox", "Add at least one file first.")
            return

        target = self._current_target_key()
        try:
            pages = parse_pages(self.pages_var.get().strip() or None)
            dpi = int(self.dpi_var.get())
            ocr_dpi = int(self.ocr_dpi_var.get())
        except ValueError:
            messagebox.showerror("PDF Toolbox", "Check the DPI and pages values.")
            return

        out_dir = Path(self.out_var.get()) if self.out_var.get().strip() else None

        self.config["dpi"] = dpi
        self.config["ocr_dpi"] = ocr_dpi
        self.config["out_dir"] = str(out_dir) if out_dir else ""
        try:
            save_config(self.config)
        except OSError:
            pass  # read-only location: run without persisting

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
            results = convert_many(
                inputs, target, out_dir, dpi, ocr_dpi, pages, on_progress=on_progress
            )
            self.events.put(("done", results))
        except Exception as exc:  # noqa: BLE001 - last-resort guard for the UI thread
            self.events.put(("fatal", str(exc)))

    def _poll_events(self) -> None:
        try:
            while True:
                kind, payload = self.events.get_nowait()
                if kind == "progress":
                    done, total = payload
                    self.progress.configure(maximum=total, value=done)
                    self.status_var.set(f"Page {done}/{total}")
                elif kind == "done":
                    self._render_results(payload)
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
