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

mode = os.environ.get("PDFTOOLBOX_BUILD_MODE", "internal")
is_internal = mode == "internal"

common_hidden = [
    "pdftoolbox",
    "pdftoolbox.cli",
    "pdftoolbox.gui",
    "rapidocr_onnxruntime",
    "onnxruntime",
    "pypdfium2_raw",
]

if is_internal:
    hidden_imports = common_hidden + ["pdf2docx", "fitz", "pymupdf"]
    excludes = []
else:
    hidden_imports = common_hidden
    excludes = ["pdf2docx", "fitz", "pymupdf", "cv2", "docx"]

datas = []
binaries = []

try:
    from PyInstaller.utils.hooks import collect_all

    for package in ("rapidocr_onnxruntime",):
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
    name="PDFToolbox",
    console=False,
    disable_windowed_traceback=False,
)
exe_cli = EXE(
    pyz_cli,
    a_cli.scripts,
    [],
    exclude_binaries=True,
    name="PDFToolboxCLI",
    console=True,
)

coll = COLLECT(
    exe_gui,
    a_gui.binaries,
    a_gui.datas,
    exe_cli,
    a_cli.binaries,
    a_cli.datas,
    strip=False,
    upx=False,  # packers trigger antivirus false positives; never use UPX here
    name="PDFToolbox",
)
