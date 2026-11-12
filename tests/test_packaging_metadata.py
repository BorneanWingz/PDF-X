"""Packaging metadata: the built exe must carry the version the app reports.

NOTE: these checks read the PyInstaller version resource with PyInstaller's own
parser, so a typo in the resource file fails here rather than in Explorer after
a 10-minute build.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from pdftoolbox import __author__, __version__

pytest.importorskip("PyInstaller")

from PyInstaller.utils.win32 import versioninfo  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
SPEC = ROOT / "packaging" / "pdf_toolbox.spec"
VERSION_FILE = ROOT / "packaging" / "version_info.txt"


def _strings() -> dict[str, str]:
    info = versioninfo.load_version_info_from_text_file(str(VERSION_FILE))
    table = next(kid for kid in info.kids if isinstance(kid, versioninfo.StringFileInfo))
    return {entry.name: entry.val for entry in table.kids[0].kids}


def test_version_resource_is_a_parseable_vsversioninfo() -> None:
    info = versioninfo.load_version_info_from_text_file(str(VERSION_FILE))
    assert isinstance(info, versioninfo.VSVersionInfo)


def test_version_resource_matches_the_reported_version() -> None:
    expected = tuple(int(part) for part in __version__.split("."))
    fixed = versioninfo.load_version_info_from_text_file(str(VERSION_FILE)).ffi

    def decode(ms: int, ls: int) -> tuple[int, ...]:
        return (ms >> 16, ms & 0xFFFF, ls >> 16, ls & 0xFFFF)

    assert decode(fixed.fileVersionMS, fixed.fileVersionLS) == (*expected, 0)
    assert decode(fixed.productVersionMS, fixed.productVersionLS) == (*expected, 0)


def test_version_resource_names_the_product_and_copyright() -> None:
    strings = _strings()
    assert strings["ProductName"] == "PDF-X"
    assert strings["FileVersion"] == f"{__version__}.0"
    assert strings["ProductVersion"] == f"{__version__}.0"
    assert __author__ in strings["CompanyName"]
    assert "Copyright" in strings["LegalCopyright"]
    assert __author__ in strings["LegalCopyright"]


def test_spec_stamps_both_executables_with_the_version_resource() -> None:
    spec = SPEC.read_text(encoding="utf-8")
    assert "version_info.txt" in spec
    # both executables share the product version, each with its own file name
    assert 'version=version_file_for("PDF-X.exe")' in spec
    assert 'version=version_file_for("PDF-X-CLI.exe")' in spec
    assert spec.count("version=version_file_for(") == 2
    assert spec.count('name="PDF-X"') >= 1 and 'name="PDF-X-CLI"' in spec


def test_each_executable_gets_its_own_original_filename() -> None:
    # the shared resource must be patched per exe, or Explorer shows PDF-X.exe
    # on the CLI build as well
    spec = SPEC.read_text(encoding="utf-8")
    namespace = {"SPECPATH": str(SPEC.parent)}
    exec(compile(spec.split("a_gui = Analysis")[0], str(SPEC), "exec"), namespace)
    for exe_name in ("PDF-X.exe", "PDF-X-CLI.exe"):
        path = Path(namespace["version_file_for"](exe_name))
        try:
            # version= takes a PATH: the file must exist and parse
            info = versioninfo.load_version_info_from_text_file(str(path))
            assert isinstance(info, versioninfo.VSVersionInfo)
            table = next(
                kid for kid in info.kids if isinstance(kid, versioninfo.StringFileInfo)
            )
            strings = {entry.name: entry.val for entry in table.kids[0].kids}
            assert strings["OriginalFilename"] == exe_name
            assert strings["FileVersion"] == f"{__version__}.0"
        finally:
            path.unlink(missing_ok=True)
