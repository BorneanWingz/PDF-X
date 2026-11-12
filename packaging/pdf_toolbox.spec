# PyInstaller spec: one onedir bundle, two executables sharing _internal.
# Build mode comes from PDFTOOLBOX_BUILD_MODE:
#   internal -> bundles pdf2docx/PyMuPDF for the AGPL plugin
#   clean    -> excludes all AGPL components (safe for app-store distribution)
#
# Paths are anchored to SPECPATH because PyInstaller resolves relative paths
# against this spec file's directory, not the working directory.
import os

SPEC_DIR = SPECPATH  # noqa: F821 - provided by PyInstaller
ROOT = os.path.abspath(os.path.join(SPEC_DIR, os.pardir))
ENTRY_GUI = os.path.join(SPEC_DIR, "entry_gui.py")
ENTRY_CLI = os.path.join(SPEC_DIR, "entry_cli.py")
SRC_DIR = os.path.join(ROOT, "src")
# NOTE: multi-resolution icon built from assets/pdf-x.png by scripts/make_icon.py
ICON = os.path.join(ROOT, "assets", "pdf-x.ico")
# NOTE: the Windows version resource (file/product version, product name,
# copyright) lives beside this spec as a VSVersionInfo text file, so Explorer's
# Properties > Details shows the same version the About page shows
VERSION_FILE = os.path.join(SPEC_DIR, "version_info.txt")


def version_file_for(exe_name):
    """Write the shared version resource with this exe's OriginalFilename.

    NOTE: PyInstaller's ``version=`` argument takes a PATH, not the resource
    text, so the patched copy is written beside the source file (git-ignored)
    and that path is returned. Both executables ship one product version, so
    they share a single source file; only OriginalFilename differs.
    """
    with open(VERSION_FILE, encoding="utf-8") as handle:
        text = handle.read()
    text = text.replace(
        "OriginalFilename', 'PDF-X.exe'", f"OriginalFilename', '{exe_name}'"
    )
    # NOTE: the patched copies are scratch input for PyInstaller, not sources
    target = os.path.join(SPEC_DIR, f"version_info_{exe_name}.txt")
    with open(target, "w", encoding="utf-8") as handle:
        handle.write(text)
    return target


mode = os.environ.get("PDFTOOLBOX_BUILD_MODE", "internal")
is_internal = mode == "internal"

common_hidden = [
    "pdftoolbox",
    "pdftoolbox.cli",
    "pdftoolbox.gui",
    # NOTE: the design system is imported by the GUI for its palette and its
    # Pillow-drawn glyphs, so it must be pulled in explicitly
    "pdftoolbox.theme",
    # NOTE: the GUI sets the window icon via ImageTk, which is imported lazily
    # inside _apply_window_icon(), so PyInstaller cannot see it on its own
    "PIL.ImageTk",
    "rapidocr_onnxruntime",
    "onnxruntime",
    "pypdfium2_raw",
]

if is_internal:
    hidden_imports = common_hidden + ["pdf2docx", "fitz", "pymupdf"]
    excludes = []
else:
    hidden_imports = common_hidden
    excludes = ["pdf2docx", "fitz", "pymupdf", "docx"]

# NOTE: the icon is ALSO shipped as data. icon= only stamps the exe resource
# (what Explorer shows); the Tk title bar reads the file at runtime through
# pdftoolbox.paths.icon_path(), which looks in the bundle first.
datas = [(ICON, "assets")]
binaries = []

try:
    from PyInstaller.utils.hooks import collect_all

    # NOTE: collect_all pulls RapidOCR's bundled ONNX models + data files into
    # the bundle; without it the frozen exe starts but OCR finds no models
    for package in ("rapidocr_onnxruntime", "tkinterdnd2"):
        pkg_datas, pkg_binaries, pkg_hidden = collect_all(package)
        datas += pkg_datas
        binaries += pkg_binaries
        hidden_imports += pkg_hidden

    if is_internal:
        for package in ("pdf2docx",):
            pkg_datas, pkg_binaries, pkg_hidden = collect_all(package)
            datas += pkg_datas
            binaries += pkg_binaries
            hidden_imports += pkg_hidden
except ImportError:
    pass

a_gui = Analysis(
    [ENTRY_GUI],
    pathex=[SRC_DIR],
    binaries=binaries,
    datas=datas,
    hiddenimports=hidden_imports,
    excludes=excludes,
    noarchive=False,
)
a_cli = Analysis(
    [ENTRY_CLI],
    pathex=[SRC_DIR],
    binaries=binaries,
    datas=datas,
    hiddenimports=hidden_imports,
    excludes=excludes,
    noarchive=False,
)

pyz_gui = PYZ(a_gui.pure)
pyz_cli = PYZ(a_cli.pure)

exe_gui = EXE(
    pyz_gui,
    a_gui.scripts,
    [],
    exclude_binaries=True,
    name="PDF-X",
    console=False,
    disable_windowed_traceback=False,
    icon=ICON,
    version=version_file_for("PDF-X.exe"),
)
exe_cli = EXE(
    pyz_cli,
    a_cli.scripts,
    [],
    exclude_binaries=True,
    name="PDF-X-CLI",
    console=True,
    icon=ICON,
    version=version_file_for("PDF-X-CLI.exe"),
)

coll = COLLECT(
    exe_gui,
    a_gui.binaries,
    a_gui.datas,
    exe_cli,
    a_cli.binaries,
    a_cli.datas,
    strip=False,
    # NOTE: UPX stays OFF - packed executables trip corporate antivirus and
    # get colleagues' downloads quarantined (a hard requirement of this tool)
    upx=False,
    name="PDF-X",
)
