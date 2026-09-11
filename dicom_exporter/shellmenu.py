"""Polecenia DICOM Exporter w menu kontekstowym Eksploratora – bez instalatora, tylko dla bieżącego użytkownika."""

from __future__ import annotations

import sys
from pathlib import Path

from .i18n import t

IS_WINDOWS = sys.platform == "win32"

# Pliki .dcm i .dicom oraz foldery (np. płyty z badaniami); wpisy w HKEY_CURRENT_USER nie wymagają administratora
MENU_ROOTS = (
    r"Software\Classes\SystemFileAssociations\.dcm\shell",
    r"Software\Classes\SystemFileAssociations\.dicom\shell",
    r"Software\Classes\Directory\shell",
)
# (nazwa polecenia, etykieta, dodatkowy argument)
VERBS = (
    ("DicomExporter.Open", "shell_open", ""),
    ("DicomExporter.Convert", "shell_convert", "--quick-png"),
)


def launcher(program: Path | None = None) -> tuple[str, str]:
    """(program, argumenty przed ścieżką): exe z PyInstallera albo pythonw z main.py przy uruchomieniu ze źródeł.

    `program` wskazuje inny plik .exe – np. nową wersję po aktualizacji."""
    if program is not None:
        return str(program), ""
    if getattr(sys, "frozen", False):
        return sys.executable, ""
    python = Path(sys.executable)
    pythonw = python.with_name("pythonw.exe")
    main = Path(__file__).resolve().parent.parent / "main.py"
    return str(pythonw if pythonw.exists() else python), f'"{main}"'


def command_line(flag: str = "", program: Path | None = None) -> str:
    executable, prefix = launcher(program)
    return " ".join(part for part in (f'"{executable}"', prefix, flag, '"%1"') if part)


def is_registered() -> bool:
    """Czy polecenia są dodane i wskazują na bieżące położenie programu."""
    if not IS_WINDOWS:
        return False
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, rf"{MENU_ROOTS[0]}\{VERBS[0][0]}\command") as key:
            value, _kind = winreg.QueryValueEx(key, "")
    except OSError:
        return False
    return value == command_line()


def register(program: Path | None = None) -> None:
    import winreg

    executable, _prefix = launcher(program)
    for root in MENU_ROOTS:
        for verb, label, flag in VERBS:
            with winreg.CreateKey(winreg.HKEY_CURRENT_USER, rf"{root}\{verb}") as key:
                winreg.SetValueEx(key, "", 0, winreg.REG_SZ, t(label))
                winreg.SetValueEx(key, "Icon", 0, winreg.REG_SZ, executable)
            with winreg.CreateKey(winreg.HKEY_CURRENT_USER, rf"{root}\{verb}\command") as key:
                winreg.SetValueEx(key, "", 0, winreg.REG_SZ, command_line(flag, program))
    _notify_shell()


def unregister() -> None:
    import winreg

    for root in MENU_ROOTS:
        for verb, _label, _flag in VERBS:
            for subkey in (rf"{root}\{verb}\command", rf"{root}\{verb}"):
                try:
                    winreg.DeleteKey(winreg.HKEY_CURRENT_USER, subkey)
                except FileNotFoundError:
                    pass
    _notify_shell()


def _notify_shell() -> None:
    """Informuje Eksplorator o zmianie, żeby menu odświeżyło się bez ponownego logowania."""
    try:
        import ctypes

        ctypes.windll.shell32.SHChangeNotify(0x08000000, 0, None, None)  # SHCNE_ASSOCCHANGED
    except (AttributeError, OSError):
        pass
