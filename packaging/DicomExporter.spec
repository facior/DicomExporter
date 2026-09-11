# -*- mode: python ; coding: utf-8 -*-
"""Budowa DICOM Exporter (uruchamiaj przez `python packaging/build.py`):

- dist/DicomExporter-onefile.exe – jeden plik do uruchomienia bez instalacji (z ekranem startowym),
- dist/DicomExporter/ – folder z DicomExporter.exe i konsolowym dicom-exporter-cli.exe (szybszy start).
"""

from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules, copy_metadata

ROOT = Path(SPECPATH).parent
ICON = str(ROOT / "packaging" / "app.ico")
VERSION_FILE = str(ROOT / "build" / "version_info.txt")

# Dekodery pylibjpeg są wykrywane przez „entry points” – potrzebne są ich moduły i metadane pakietów.
hiddenimports = ["libjpeg", "openjpeg", "rle", *collect_submodules("pydicom.pixels"), *collect_submodules("pylibjpeg")]
datas = []
for distribution in ("pydicom", "pylibjpeg", "pylibjpeg-libjpeg", "pylibjpeg-openjpeg", "pylibjpeg-rle", "imageio-ffmpeg"):
    datas += copy_metadata(distribution)

common = dict(
    pathex=[str(ROOT)],
    hiddenimports=hiddenimports,
    datas=datas,
    excludes=["pytest", "PyInstaller", "matplotlib", "IPython"],
)
gui = Analysis([str(ROOT / "main.py")], **common)
cli = Analysis([str(ROOT / "cli_main.py")], **common)


def without_test_data(toc):
    """Pomija przykładowe pliki testowe pydicom (kilkadziesiąt MB zbędnych w programie)."""
    return [entry for entry in toc if "test_files" not in entry[0].replace("\\", "/")]


gui.datas = without_test_data(gui.datas)
cli.datas = without_test_data(cli.datas)
gui_pyz = PYZ(gui.pure)

# --- Jeden plik .exe
splash = Splash(
    str(ROOT / "packaging" / "splash.png"),
    binaries=gui.binaries,
    datas=gui.datas,
    text_pos=None,
    minify_script=True,
)
EXE(
    gui_pyz,
    gui.scripts,
    splash,
    splash.binaries,
    gui.binaries,
    gui.datas,
    [],
    name="DicomExporter-onefile",
    console=False,
    icon=ICON,
    version=VERSION_FILE,
    upx=False,
)

# --- Folder (wersja przenośna ZIP)
gui_exe = EXE(
    gui_pyz,
    gui.scripts,
    [],
    exclude_binaries=True,
    name="DicomExporter",
    console=False,
    icon=ICON,
    version=VERSION_FILE,
)
cli_exe = EXE(
    PYZ(cli.pure),
    cli.scripts,
    [],
    exclude_binaries=True,
    name="dicom-exporter-cli",
    console=True,
    icon=ICON,
    version=VERSION_FILE,
)
COLLECT(gui_exe, gui.binaries, gui.datas, cli_exe, cli.binaries, cli.datas, name="DicomExporter")
