import hashlib
import io
import json
import re
import threading
from pathlib import Path

import pytest
from PIL import Image
from pydicom.data import get_testdata_file

import dicom_exporter
from dicom_exporter import __version__, shellmenu, updates
from dicom_exporter.converter import collect_inputs
from dicom_exporter.i18n import STRINGS, set_language
from dicom_exporter.quick import convert_in_place


def opener_returning(payload):
    return lambda request, timeout: io.BytesIO(json.dumps(payload).encode())


def bytes_opener(data: bytes):
    return lambda request, timeout: io.BytesIO(data)


def exe_release(data: bytes, **changes) -> updates.Release:
    values = dict(
        version="2.0.0",
        url="https://example/r",
        asset_url="https://example/exe",
        asset_size=len(data),
        asset_sha256=hashlib.sha256(data).hexdigest(),
    )
    values.update(changes)
    return updates.Release(**values)


EXE_DATA = b"MZ" + bytes(range(256)) * 2000


def test_newer_release_is_detected():
    payload = {
        "tag_name": "v99.0.0",
        "html_url": "https://example/r",
        "body": "## Zmiany",
        "assets": [
            {"name": "DicomExporter-99.0.0-portable.zip", "browser_download_url": "https://example/zip", "size": 5},
            {"name": "DicomExporter-99.0.0.exe", "browser_download_url": "https://example/exe", "size": 3, "digest": "sha256:ABC"},
        ],
    }
    release = updates.check_for_update(opener=opener_returning(payload))
    assert release == updates.Release("99.0.0", "https://example/r", "## Zmiany", "https://example/exe", 3, "abc")


def test_current_prerelease_and_draft_are_ignored():
    assert updates.check_for_update(opener=opener_returning({"tag_name": f"v{__version__}"})) is None
    assert updates.check_for_update(opener=opener_returning({"tag_name": "v99.0.0", "prerelease": True})) is None
    assert updates.check_for_update(opener=opener_returning({"tag_name": "v99.0.0", "draft": True})) is None


def test_network_errors_are_silent_at_startup_but_reported_on_demand():
    def failing(request, timeout):
        raise OSError("brak sieci")

    assert updates.check_for_update(opener=failing) is None
    with pytest.raises(updates.UpdateError):
        updates.latest_release(opener=failing)


def test_version_comparison():
    assert updates.is_newer("v1.10.0", "1.9.9")
    assert not updates.is_newer("1.0", "1.0.0")
    assert updates.parse_version("v2") == (2, 0, 0)


def test_release_notes_are_shown_as_plain_text():
    body = (
        "<!-- komentarz -->\n## Co nowego\n* Okno podsumowania **po konwersji**\n- [Opis](https://example)\n\n"
        "**Full Changelog**: https://github.com/a/b/compare/v1.0.0...v1.1.0"
    )
    assert updates.release_notes_text(body) == "Co nowego\n• Okno podsumowania po konwersji\n• Opis"


def test_download_verifies_the_file(tmp_path):
    progress = []
    path = updates.download(
        exe_release(EXE_DATA), tmp_path, progress=lambda done, total: progress.append((done, total)), opener=bytes_opener(EXE_DATA)
    )
    assert path.read_bytes() == EXE_DATA
    assert progress[-1] == (len(EXE_DATA), len(EXE_DATA))

    broken = {
        "size": (exe_release(EXE_DATA, asset_size=len(EXE_DATA) + 1), EXE_DATA),
        "checksum": (exe_release(EXE_DATA, asset_sha256="0" * 64), EXE_DATA),
        "not_exe": (exe_release(b"<html>", asset_size=0, asset_sha256=""), b"<html>"),
    }
    for name, (release, data) in broken.items():
        folder = tmp_path / name
        folder.mkdir()
        with pytest.raises(updates.UpdateError):
            updates.download(release, folder, opener=bytes_opener(data))
        assert not any(folder.iterdir()), name


def test_download_cancel_and_network_error_leave_no_files(tmp_path):
    cancel = threading.Event()
    cancel.set()
    with pytest.raises(updates.UpdateCancelled):
        updates.download(exe_release(EXE_DATA), tmp_path, cancel=cancel, opener=bytes_opener(EXE_DATA))

    def failing(request, timeout):
        raise OSError("przerwane połączenie")

    with pytest.raises(updates.UpdateError):
        updates.download(exe_release(EXE_DATA), tmp_path, opener=failing)
    with pytest.raises(updates.UpdateError):
        updates.download(exe_release(EXE_DATA, asset_url=""), tmp_path, opener=bytes_opener(EXE_DATA))
    assert not any(tmp_path.iterdir())


def test_install_uses_the_new_version_name(tmp_path):
    current = tmp_path / "DicomExporter-1.0.0.exe"
    current.write_bytes(b"MZ old")
    downloaded = tmp_path / "DicomExporter-2.0.0.exe.download"
    downloaded.write_bytes(b"MZ new")
    new, leftover = updates.install(downloaded, current, "2.0.0")
    assert new == tmp_path / "DicomExporter-2.0.0.exe" and new.read_bytes() == b"MZ new"
    assert leftover == current and not downloaded.exists()


def test_install_keeps_a_custom_program_name(tmp_path):
    current = tmp_path / "DICOM.exe"
    current.write_bytes(b"MZ old")
    downloaded = tmp_path / "DicomExporter-2.0.0.exe.download"
    downloaded.write_bytes(b"MZ new")
    new, leftover = updates.install(downloaded, current, "2.0.0")
    assert new == current and current.read_bytes() == b"MZ new"
    assert leftover == tmp_path / "DICOM.exe.old" and leftover.read_bytes() == b"MZ old"
    assert updates.is_leftover(leftover, new)


def test_only_old_program_files_are_removed(tmp_path):
    current = tmp_path / "DicomExporter-2.0.0.exe"
    current.write_bytes(b"MZ")
    assert updates.is_leftover(tmp_path / "DicomExporter-1.0.0.exe", current)
    assert updates.is_leftover(tmp_path / "DicomExporter-2.0.0.exe.old", current)
    assert not updates.is_leftover(current, current)
    assert not updates.is_leftover(tmp_path / "wyniki.png", current)
    assert not updates.is_leftover(tmp_path / "inny" / "DicomExporter-1.0.0.exe", current)
    assert not updates.remove_leftover(tmp_path / "wyniki.png", current, timeout=0)

    old = tmp_path / "DicomExporter-1.0.0.exe"
    old.write_bytes(b"MZ")
    partial = tmp_path / "DicomExporter-3.0.0.exe.download"
    partial.write_bytes(b"MZ")
    assert updates.remove_leftover(old, current, timeout=0)
    assert not old.exists() and not partial.exists() and current.exists()


def test_self_update_only_for_single_exe(monkeypatch, tmp_path):
    assert updates.running_executable() is None  # testy działają ze źródeł
    executable = tmp_path / "DicomExporter-1.0.0.exe"
    monkeypatch.setattr(updates.sys, "platform", "win32")
    monkeypatch.setattr(updates.sys, "frozen", True, raising=False)
    monkeypatch.setattr(updates.sys, "executable", str(executable))
    monkeypatch.setattr(updates.sys, "_MEIPASS", str(tmp_path / "_internal"), raising=False)
    assert updates.running_executable() is None  # wersja ZIP
    monkeypatch.setattr(updates.sys, "_MEIPASS", str(tmp_path.parent / "_MEI12345"))
    assert updates.running_executable() == executable.resolve()
    assert updates.target_path(executable, "1.2.0") == tmp_path / "DicomExporter-1.2.0.exe"
    assert updates.target_path(tmp_path / "DICOM.exe", "1.2.0") == tmp_path / "DICOM.exe"


def test_context_menu_command_for_source_and_exe(monkeypatch):
    source_command = shellmenu.command_line("--quick-png")
    assert "main.py" in source_command and source_command.endswith('--quick-png "%1"')
    updated = Path(r"C:\Programy\DicomExporter-2.0.0.exe")
    assert shellmenu.command_line("--quick-png", updated) == r'"C:\Programy\DicomExporter-2.0.0.exe" --quick-png "%1"'

    monkeypatch.setattr(shellmenu.sys, "frozen", True, raising=False)
    monkeypatch.setattr(shellmenu.sys, "executable", r"C:\Programy\DicomExporter.exe")
    assert shellmenu.command_line() == r'"C:\Programy\DicomExporter.exe" "%1"'
    assert shellmenu.command_line("--quick-png") == r'"C:\Programy\DicomExporter.exe" --quick-png "%1"'


def test_duration_in_summary():
    from dicom_exporter.dialogs import format_duration

    set_language("pl")
    assert format_duration(12.4) == "12 s"
    assert format_duration(185) == "3 min 05 s"
    assert format_duration(3725) == "1 h 02 min"


def test_every_translation_key_used_in_code_exists():
    used = set()
    for source in Path(dicom_exporter.__file__).parent.glob("*.py"):
        used.update(re.findall(r'\bt\(\s*"([A-Za-z0-9_]+)"', source.read_text(encoding="utf-8")))
    assert used and not used - set(STRINGS)


def test_quick_convert_saves_png_next_to_sources(tmp_path):
    data = Path(get_testdata_file("CT_small.dcm")).read_bytes()
    for folder in ("a", "b"):
        (tmp_path / folder).mkdir()
        (tmp_path / folder / "obraz.dcm").write_bytes(data)
    results = list(convert_in_place(collect_inputs([tmp_path])))
    assert all(result.ok for result in results)
    for folder in ("a", "b"):
        with Image.open(tmp_path / folder / "obraz.png") as image:
            assert image.format == "PNG"
