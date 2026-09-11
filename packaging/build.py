"""Budowanie wersji do dystrybucji.

    python packaging/build.py                 # folder dist/DicomExporter + wersja przenośna ZIP
    python packaging/build.py --installer     # dodatkowo instalator (wymaga Inno Setup 6)
    python packaging/build.py --expect-version v1.2.0   # sprawdza zgodność z tagiem wydania
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dicom_exporter import COPYRIGHT_YEAR, __author__, __version__  # noqa: E402

VERSION_TEMPLATE = """VSVersionInfo(
  ffi=FixedFileInfo(
    filevers=({major}, {minor}, {patch}, 0),
    prodvers=({major}, {minor}, {patch}, 0),
    mask=0x3f, flags=0x0, OS=0x40004, fileType=0x1, subtype=0x0, date=(0, 0)
  ),
  kids=[
    StringFileInfo([
      StringTable('041504B0', [
        StringStruct('CompanyName', '{author}'),
        StringStruct('FileDescription', 'DICOM Exporter'),
        StringStruct('FileVersion', '{version}'),
        StringStruct('InternalName', 'DicomExporter'),
        StringStruct('LegalCopyright', '(c) {year} {author}'),
        StringStruct('OriginalFilename', 'DicomExporter.exe'),
        StringStruct('ProductName', 'DICOM Exporter'),
        StringStruct('ProductVersion', '{version}')
      ])
    ]),
    VarFileInfo([VarStruct('Translation', [0x0415, 1200])])
  ]
)
"""


def write_version_file() -> Path:
    major, minor, patch = (int(part) for part in __version__.split(".")[:3])
    path = ROOT / "build" / "version_info.txt"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        VERSION_TEMPLATE.format(
            major=major, minor=minor, patch=patch, version=__version__, author=__author__, year=COPYRIGHT_YEAR
        ),
        encoding="utf-8",
    )
    return path


def find_iscc() -> Path | None:
    candidates = [os.environ.get("ISCC"), shutil.which("iscc")]
    for base in (os.environ.get("ProgramFiles(x86)"), os.environ.get("ProgramFiles"), os.environ.get("LOCALAPPDATA")):
        if base:
            candidates += [str(Path(base) / "Inno Setup 6" / "ISCC.exe"), str(Path(base) / "Programs" / "Inno Setup 6" / "ISCC.exe")]
    return next((Path(candidate) for candidate in candidates if candidate and Path(candidate).is_file()), None)


def main() -> int:
    parser = argparse.ArgumentParser(description="Budowanie DICOM Exporter do dystrybucji")
    parser.add_argument("--installer", action="store_true", help="zbuduj także instalator Inno Setup")
    parser.add_argument("--expect-version", help="tag wydania (np. v1.2.0), który musi zgadzać się z wersją programu")
    args = parser.parse_args()

    if args.expect_version and args.expect_version.lstrip("vV") != __version__:
        print(f"Tag {args.expect_version} nie zgadza się z wersją programu {__version__} (dicom_exporter/__init__.py).")
        return 1

    write_version_file()
    subprocess.run(
        [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", str(ROOT / "packaging" / "DicomExporter.spec")],
        check=True,
        cwd=ROOT,
    )
    archive = shutil.make_archive(
        str(ROOT / "dist" / f"DicomExporter-{__version__}-portable"), "zip", ROOT / "dist", "DicomExporter"
    )
    print(f"Wersja przenośna: {archive}")

    if args.installer:
        iscc = find_iscc()
        if iscc is None:
            print("Nie znaleziono Inno Setup 6 (ISCC.exe). Zainstaluj go albo ustaw zmienną ISCC.")
            return 1
        subprocess.run([str(iscc), f"/DAppVersion={__version__}", str(ROOT / "packaging" / "installer.iss")], check=True)
        print(f"Instalator: {ROOT / 'dist' / f'DicomExporter-{__version__}-setup.exe'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
