"""Visual design system for the PDF-X interface.

The palette is derived from the app icon (a deep crimson document mark), so the
window, the sidebar and the buttons all share one brand colour instead of a
generic blue. Widgets here are deliberately plain Tk/ttk: the app must stay
dependency-free and run offline.

Naming and wording follow British English (``organise``, ``colour``,
``centre``) to match the rest of the project.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from tkinterdnd2 import DND_FILES

# --------------------------------------------------------------------------
# palette
# --------------------------------------------------------------------------

#: The brand crimson, sampled from assets/pdf-x.png.
ACCENT = "#a40a1e"
ACCENT_DARK = "#7d0616"
ACCENT_HOVER = "#8c0818"
ACCENT_SOFT = "#fbe9ec"

INK = "#1f2430"
MUTED = "#6b7280"
BORDER = "#e2e5ea"
SURFACE = "#ffffff"
CANVAS = "#f2f3f5"
HEADER = "#15171c"
HEADER_MUTED = "#9aa1ad"
SIDEBAR = "#ffffff"
SIDEBAR_ACTIVE = "#f7e9eb"

#: Colour for the small line glyphs drawn in the sidebar and the toolbar.
GLYPH = "#3f4653"

#: Every PhotoImage handed out is kept here.
#:
#: NOTE: Tk deletes an image when its last Python reference goes, so a glyph
#: that is only referenced by a widget would vanish and leave the widget
#: pointing at a name that no longer exists ("pyimage67 doesn't exist").
#: Holding them for the lifetime of the process keeps them alive.
_IMAGES: list[tk.PhotoImage] = []


def apply_theme(root: tk.Tk) -> None:
    """Apply the brand palette to every standard widget in the tree."""
    root.configure(background=CANVAS)
    root.option_add("*Listbox.background", SURFACE)
    root.option_add("*Listbox.foreground", INK)
    root.option_add("*Listbox.selectBackground", ACCENT_SOFT)
    root.option_add("*Listbox.selectForeground", INK)
    root.option_add("*Listbox.highlightBackground", BORDER)
    root.option_add("*Listbox.highlightColor", ACCENT)
    root.option_add("*Listbox.highlightThickness", 1)
    root.option_add("*Listbox.borderWidth", 0)
    root.option_add("*Text.background", SURFACE)
    root.option_add("*Text.foreground", INK)
    root.option_add("*Text.insertBackground", INK)
    root.option_add("*Text.selectBackground", ACCENT_SOFT)
    root.option_add("*Text.selectForeground", INK)
    root.option_add("*Text.borderWidth", 0)

    style = ttk.Style(root)
    if "clam" in style.theme_names():
        style.theme_use("clam")

    style.configure(".", font="TkDefaultFont", foreground=INK)
    style.configure("TFrame", background=CANVAS)
    style.configure("TLabel", background=CANVAS, foreground=INK)
    style.configure("TLabelframe", background=CANVAS, bordercolor=BORDER)
    style.configure(
        "TLabelframe.Label", background=CANVAS, foreground=INK, font="TkDefaultFont"
    )
    style.configure("TNotebook", background=CANVAS, borderwidth=0)
    style.configure(
        "TNotebook.Tab",
        padding=(12, 5),
        background="#e6e8ec",
        foreground=MUTED,
        borderwidth=0,
    )
    style.map(
        "TNotebook.Tab",
        background=[("selected", SURFACE), ("active", "#dfe2e7")],
        foreground=[("selected", ACCENT)],
    )

    style.configure(
        "TButton",
        padding=(9, 4),
        background="#e9ebef",
        foreground=INK,
        bordercolor=BORDER,
        borderwidth=1,
        relief="flat",
    )
    style.map(
        "TButton",
        background=[
            ("disabled", "#f1f2f4"),
            ("pressed", "#d8dce2"),
            ("active", "#e0e3e8"),
        ],
        foreground=[("disabled", "#9aa1ad")],
    )

    style.configure(
        "Accent.TButton",
        background=ACCENT,
        foreground=SURFACE,
        bordercolor=ACCENT,
        borderwidth=1,
        relief="flat",
        padding=(12, 5),
    )
    style.map(
        "Accent.TButton",
        background=[
            ("disabled", "#d8a8b0"),
            ("pressed", ACCENT_DARK),
            ("active", ACCENT_HOVER),
        ],
        foreground=[("disabled", SURFACE)],
    )

    style.configure(
        "Ghost.TButton",
        background=CANVAS,
        foreground=INK,
        bordercolor=BORDER,
        relief="flat",
    )
    style.map(
        "Ghost.TButton",
        background=[("pressed", "#e4e6ea"), ("active", "#eceef1")],
    )

    style.configure(
        "TEntry",
        fieldbackground=SURFACE,
        foreground=INK,
        bordercolor=BORDER,
        insertcolor=INK,
        borderwidth=1,
    )
    style.configure(
        "TCombobox",
        fieldbackground=SURFACE,
        foreground=INK,
        bordercolor=BORDER,
        arrowcolor=MUTED,
        borderwidth=1,
    )
    style.map(
        "TCombobox",
        fieldbackground=[("readonly", SURFACE)],
        foreground=[("readonly", INK)],
    )
    style.configure(
        "TSpinbox",
        fieldbackground=SURFACE,
        foreground=INK,
        bordercolor=BORDER,
        borderwidth=1,
    )
    style.configure(
        "TProgressbar",
        background=ACCENT,
        troughcolor="#e6e8ec",
        bordercolor="#e6e8ec",
    )
    style.configure("TCheckbutton", background=CANVAS, foreground=INK)
    style.configure("TRadiobutton", background=CANVAS, foreground=INK)
    style.configure("TSeparator", background=BORDER)

    # The sidebar, header and cards are plain Tk/ttk mixes, so their children
    # need styles that do not inherit the canvas colour.
    style.configure("Sidebar.TFrame", background=SIDEBAR)
    style.configure("Sidebar.TLabel", background=SIDEBAR, foreground=INK)
    style.configure("Header.TFrame", background=HEADER)
    style.configure("Header.TLabel", background=HEADER, foreground=SURFACE)
    style.configure("Card.TFrame", background=SURFACE)
    style.configure("Card.TLabel", background=SURFACE, foreground=INK)
    style.configure(
        "CardTitle.TLabel",
        background=SURFACE,
        foreground=INK,
        font=("TkDefaultFont", 15, "bold"),
    )
    style.configure("CardMuted.TLabel", background=SURFACE, foreground=MUTED)
    style.configure("Card.TLabelframe", background=SURFACE, bordercolor=BORDER)
    style.configure("Card.TLabelframe.Label", background=SURFACE, foreground=INK)
    style.configure("Card.TButton", background="#f0f1f4")
    style.map("Card.TButton", background=[("active", "#e6e8ec")])
    style.configure("Card.TEntry", fieldbackground=SURFACE)
    style.configure("Card.TCombobox", fieldbackground=SURFACE, arrowcolor=MUTED)
    style.configure("Card.TSpinbox", fieldbackground=SURFACE)
    style.configure("Card.TCheckbutton", background=SURFACE, foreground=INK)
    style.configure("Card.TSeparator", background=BORDER)


# --------------------------------------------------------------------------
# iconography
# --------------------------------------------------------------------------

# Each glyph is a list of drawing commands in a 20x20 grid:
#   ("line", x1, y1, x2, y2)  a straight stroke
#   ("poly", (x, y), ...)     a closed outline
#   ("arc", x, y, w, h, start, end)  a partial ellipse
#   ("dot", x, y, r)          a filled circle
def _glyph_commands() -> dict[str, list[tuple]]:
    return {
        "convert": [
            ("line", 4, 10, 16, 10),
            ("poly", [(12, 4), (17, 10), (12, 16)]),
        ],
        "merge": [
            ("poly", [(3, 3), (9, 3), (9, 17), (3, 17)]),
            ("poly", [(11, 3), (17, 3), (17, 17), (11, 17)]),
        ],
        "edit": [
            ("poly", [(4, 16), (4, 13), (12, 5), (15, 8), (7, 16)]),
            ("line", 11, 6, 14, 9),
        ],
        "organise": [
            ("poly", [(3, 4), (17, 4), (17, 16), (3, 16)]),
            ("line", 7, 8, 13, 8),
            ("line", 7, 12, 13, 12),
        ],
        "tools": [
            # a wrench: a diagonal shaft with an open jaw at the top right
            ("line", 5, 15, 13, 7),
            ("arc", 9, 1, 9, 9, 120, 330),
            ("poly", [(12, 3), (17, 3), (17, 8), (14, 6)]),
        ],
        "about": [
            ("dot", 10, 6, 1.2),
            ("line", 10, 9, 10, 15),
        ],
        "up": [("poly", [(10, 4), (15, 11), (5, 11)])],
        "down": [("poly", [(10, 16), (5, 9), (15, 9)])],
        "rotate_left": [
            ("arc", 4, 4, 12, 12, 200, 520),
            ("poly", [(12, 2), (12, 7), (7, 7)]),
        ],
        "rotate_right": [
            ("arc", 4, 4, 12, 12, 20, 340),
            ("poly", [(8, 2), (8, 7), (13, 7)]),
        ],
        "rotate_180": [
            # a full turn: two half arcs with an arrowhead at each end
            ("arc", 4, 4, 12, 12, 190, 350),
            ("poly", [(12, 2), (12, 7), (7, 7)]),
            ("arc", 4, 4, 12, 12, 10, 170),
            ("poly", [(8, 18), (8, 13), (13, 13)]),
        ],
        "delete": [
            ("line", 4, 6, 16, 6),
            ("poly", [(8, 6), (8, 3), (12, 3), (12, 6)]),
            ("poly", [(6, 6), (7, 17), (13, 17), (14, 6)]),
        ],
        "reset": [
            # an almost-closed circle with one arrowhead, unlike the rotations
            ("arc", 4, 4, 12, 12, 40, 340),
            ("poly", [(16, 3), (16, 8), (11, 8)]),
        ],
        "pdf": [
            ("poly", [(5, 2), (11, 2), (15, 6), (15, 18), (5, 18)]),
            ("poly", [(11, 2), (11, 6), (15, 6)]),
        ],
        "folder": [
            ("poly", [(3, 6), (8, 6), (9.5, 8), (17, 8), (17, 16), (3, 16)]),
        ],
        "add": [
            ("line", 4, 10, 16, 10),
            ("line", 10, 4, 10, 16),
        ],
        "search": [
            ("arc", 3, 3, 11, 11, 0, 360),
            ("line", 13, 13, 17, 17),
        ],
    }


def _keep(image: tk.PhotoImage) -> tk.PhotoImage:
    """Hold a reference to a PhotoImage so Tk never deletes it."""
    _IMAGES.append(image)
    return image


def draw_glyph(
    name: str,
    size: int = 20,
    colour: str = GLYPH,
    width: float = 1.7,
    master: tk.Misc | None = None,
) -> tk.PhotoImage:
    """Render a small line glyph to a PhotoImage.

    NOTE: Pillow is used instead of an icon font so the app keeps its
    zero-extra-dependencies promise (Pillow is already required for the page
    previews). Unknown names fall back to a neutral square, so a missing
    glyph can never break the layout.

    The ``master`` argument names the Tk interpreter the image belongs to.
    Without it the image would bind to whichever root was created first,
    which is wrong as soon as a second window exists.
    """
    from PIL import Image, ImageDraw
    from PIL import ImageTk

    scale = 4  # draw large, then downscale for smooth edges
    edge = size * scale
    image = Image.new("RGBA", (edge, edge), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    stroke = max(1, int(width * scale))

    commands = _glyph_commands().get(name)
    if commands is None:
        draw.rectangle(
            [edge * 0.2, edge * 0.2, edge * 0.8, edge * 0.8],
            outline=colour,
            width=stroke,
        )
    else:
        for command in commands:
            kind = command[0]
            if kind == "line":
                _, x1, y1, x2, y2 = command
                draw.line(
                    [x1 * scale, y1 * scale, x2 * scale, y2 * scale],
                    fill=colour,
                    width=stroke,
                )
            elif kind == "poly":
                points = [(x * scale, y * scale) for x, y in command[1]]
                draw.line(points + [points[0]], fill=colour, width=stroke, joint="curve")
            elif kind == "arc":
                _, x, y, w, h, start, end = command
                draw.arc(
                    [x * scale, y * scale, (x + w) * scale, (y + h) * scale],
                    start=start,
                    end=end,
                    fill=colour,
                    width=stroke,
                )
            elif kind == "dot":
                _, x, y, radius = command
                draw.ellipse(
                    [
                        (x - radius) * scale,
                        (y - radius) * scale,
                        (x + radius) * scale,
                        (y + radius) * scale,
                    ],
                    fill=colour,
                )

    image = image.resize((size, size), Image.LANCZOS)
    return _keep(ImageTk.PhotoImage(image, master=master))


def draw_pdf_badge(
    size: int = 72,
    colour: str = ACCENT,
    master: tk.Misc | None = None,
) -> tk.PhotoImage:
    """The drop-zone mark: a document outline with 'PDF' inside."""
    from PIL import Image, ImageDraw, ImageFont
    from PIL import ImageTk

    scale = 4
    edge = size * scale
    image = Image.new("RGBA", (edge, edge), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)

    fold = edge * 0.26
    left, top = edge * 0.18, edge * 0.08
    right, bottom = edge * 0.82, edge * 0.92
    line = max(2, int(edge * 0.032))

    # document body with a folded top-right corner
    draw.line([left, top, right - fold, top], fill=colour, width=line)
    draw.line([right - fold, top, right, top + fold], fill=colour, width=line)
    draw.line([right, top + fold, right, bottom], fill=colour, width=line)
    draw.line([left, bottom, right, bottom], fill=colour, width=line)
    draw.line([left, top, left, bottom], fill=colour, width=line)

    try:
        font = ImageFont.truetype("C:/Windows/Fonts/arialbd.ttf", int(edge * 0.21))
    except OSError:
        font = ImageFont.load_default(size=int(edge * 0.21))
    text = "PDF"
    box = draw.textbbox((0, 0), text, font=font)
    draw.text(
        ((edge - (box[2] - box[0])) / 2, (edge - (box[3] - box[1])) / 2 - box[1]),
        text,
        font=font,
        fill=colour,
    )

    image = image.resize((size, size), Image.LANCZOS)
    return _keep(ImageTk.PhotoImage(image, master=master))


# --------------------------------------------------------------------------
# reusable pieces
# --------------------------------------------------------------------------


def card(parent: tk.Misc, **kwargs) -> ttk.Frame:
    """A white panel, the mockup's content card."""
    return ttk.Frame(parent, style="Card.TFrame", **kwargs)


def sidebar_row(
    parent: tk.Misc,
    text: str,
    glyph: str,
    images: dict[str, tk.PhotoImage],
) -> tk.Frame:
    """One sidebar entry: a glyph beside a label, highlighted when active.

    NOTE: the row is a plain Tk frame (not ttk) so the highlight colour can be
    changed per row by reconfiguring the background of every child.
    """
    row = tk.Frame(parent, background=SIDEBAR, cursor="hand2")
    icon = tk.Label(row, image=images.get(glyph), background=SIDEBAR, width=20, height=20)
    icon.image = images.get(glyph)
    icon.pack(side="left", padx=(12, 0))
    label = tk.Label(
        row,
        text=text,
        background=SIDEBAR,
        foreground=INK,
        font=("TkDefaultFont", 10),
        anchor="w",
    )
    label.pack(side="left", fill="x", expand=True, padx=(10, 12), pady=8)

    row.icon = icon
    row.label = label
    return row


def set_sidebar_active(row: tk.Frame, active: bool) -> None:
    """Highlight (or unhighlight) a sidebar row."""
    background = SIDEBAR_ACTIVE if active else SIDEBAR
    foreground = ACCENT if active else INK
    row.configure(background=background)
    row.icon.configure(background=background)
    row.label.configure(background=background, foreground=foreground)


def toolbar_button(
    parent: tk.Misc,
    text: str,
    glyph: str,
    images: dict[str, tk.PhotoImage],
) -> tk.Frame:
    """An icon-over-caption button, like the mockup's action toolbar."""
    column = tk.Frame(parent, background=SURFACE, cursor="hand2")
    icon = tk.Label(
        column, image=images.get(glyph), background=SURFACE, width=20, height=20
    )
    icon.image = images.get(glyph)
    icon.pack()
    caption = tk.Label(
        column,
        text=text,
        background=SURFACE,
        foreground=INK,
        font=("TkDefaultFont", 9),
    )
    caption.pack(pady=(3, 0))

    column.icon = icon
    column.caption = caption
    return column


def bind_click(widget: tk.Misc, command) -> None:
    """Make a widget and its children respond to a click with ``command``."""
    for child in widget.winfo_children():
        bind_click(child, command)
    widget.bind("<Button-1>", lambda _event: command())


def page_header(parent: tk.Misc, title: str, subtitle: str = "") -> ttk.Frame:
    """The big heading and its one-line description at the top of a page."""
    header = ttk.Frame(parent, style="Card.TFrame")
    ttk.Label(header, text=title, style="CardTitle.TLabel").pack(anchor="w")
    if subtitle:
        ttk.Label(
            header,
            text=subtitle,
            style="CardMuted.TLabel",
            wraplength=820,
            justify="left",
        ).pack(anchor="w", pady=(2, 0))
    return header


def dashed_drop_zone(
    parent: tk.Misc,
    height: int = 230,
    on_drop=None,
) -> tk.Frame:
    """The mockup's dashed drop target, with a PDF badge in the middle.

    NOTE: the dashed border is drawn on a Canvas rather than with a ttk
    style, because Tk has no dashed frame. The badge and the button sit in a
    separate frame placed ON TOP of the canvas, so they appear inside the
    dashed outline rather than under it.
    """
    zone = tk.Frame(parent, background=SURFACE)
    canvas = tk.Canvas(
        zone,
        height=height,
        background=SURFACE,
        highlightthickness=0,
        bd=0,
    )
    canvas.pack(fill="both", expand=True)

    def redraw(_event=None) -> None:
        canvas.delete("border")
        width = canvas.winfo_width()
        box_height = canvas.winfo_height()
        if width <= 1:
            return
        # a dashed rectangle, drawn as a run of short segments
        inset = 6
        x0, y0 = inset, inset
        x1, y1 = width - inset, box_height - inset
        dash, gap = 9, 7
        for start in range(int(x0), int(x1), dash + gap):
            stop = min(start + dash, int(x1))
            canvas.create_line(start, y0, stop, y0, fill=MUTED, dash=(4, 3), tags="border")
            canvas.create_line(start, y1, stop, y1, fill=MUTED, dash=(4, 3), tags="border")
        for start in range(int(y0), int(y1), dash + gap):
            stop = min(start + dash, int(y1))
            canvas.create_line(x0, start, x0, stop, fill=MUTED, dash=(4, 3), tags="border")
            canvas.create_line(x1, start, x1, stop, fill=MUTED, dash=(4, 3), tags="border")

    # the content is a canvas item, so it sits INSIDE the dashed outline and the
    # border stays visible around it
    content = tk.Frame(canvas, background=SURFACE)
    holder = canvas.create_window(
        0, 0, window=content, anchor="center", tags="content"
    )

    def place_content(_event=None) -> None:
        width = canvas.winfo_width()
        box_height = canvas.winfo_height()
        if width <= 1:
            return
        canvas.coords(holder, width // 2, box_height // 2)

    canvas.bind("<Configure>", lambda event: (redraw(event), place_content(event)))

    canvas.drop_target_register(DND_FILES)
    canvas.dnd_bind("<<Drop>>", on_drop or (lambda _event: None))
    zone.canvas = canvas
    zone.content = content
    zone.redraw = redraw
    return zone
