"""Aktualizacje z GitHuba: sprawdzanie nowej wersji oraz samoczynna podmiana pojedynczego pliku .exe.

Przebieg aktualizacji (bez instalatora i bez skryptów pomocniczych):
1. nowy plik .exe jest pobierany do folderu programu i sprawdzany (rozmiar, SHA-256, nagłówek pliku wykonywalnego),
2. trafia na miejsce programu – jako DicomExporter-X.Y.Z.exe albo pod dotychczasową nazwą,
3. nowa wersja startuje z argumentem --after-update i po zamknięciu starej usuwa jej plik.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import threading
import time
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from . import __version__
from .i18n import t

GITHUB_REPO = "facior/DicomExporter"
LATEST_RELEASE_API = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
RELEASES_PAGE = f"https://github.com/{GITHUB_REPO}/releases"

AFTER_UPDATE_FLAG = "--after-update"
VERSIONED_EXE = re.compile(r"^DicomExporter-\d+(?:\.\d+)*\.exe$", re.IGNORECASE)
DOWNLOAD_SUFFIX = ".download"
CHUNK_SIZE = 256 * 1024


class UpdateError(Exception):
    """Nieudane sprawdzenie, pobranie lub instalacja aktualizacji (komunikat dla użytkownika)."""


class UpdateCancelled(Exception):
    """Użytkownik przerwał pobieranie."""


@dataclass(frozen=True)
class Release:
    version: str
    url: str
    notes: str = ""
    asset_url: str = ""
    asset_size: int = 0
    asset_sha256: str = ""


def parse_version(text: str) -> tuple[int, ...]:
    """„v1.10.2” → (1, 10, 2); brakujące części traktowane są jak zero."""
    numbers = [int(part) for part in re.findall(r"\d+", text)[:3]]
    return tuple(numbers + [0] * (3 - len(numbers)))


def is_newer(candidate: str, current: str | None = None) -> bool:
    return parse_version(candidate) > parse_version(__version__ if current is None else current)


def _request(url: str, accept: str) -> urllib.request.Request:
    return urllib.request.Request(url, headers={"Accept": accept, "User-Agent": f"DicomExporter/{__version__}"})


def latest_release(timeout: float = 5.0, opener=urllib.request.urlopen) -> Release | None:
    """Najnowsze stabilne wydanie z GitHuba; brak sieci zgłaszany jest jako UpdateError."""
    try:
        with opener(_request(LATEST_RELEASE_API, "application/vnd.github+json"), timeout=timeout) as response:
            data = json.load(response)
    except (OSError, ValueError) as exc:
        raise UpdateError(str(exc)) from exc
    if not isinstance(data, dict) or data.get("draft") or data.get("prerelease"):
        return None
    tag = str(data.get("tag_name") or "")
    if not tag:
        return None
    assets = [asset for asset in data.get("assets") or [] if isinstance(asset, dict)]
    asset = next((asset for asset in assets if VERSIONED_EXE.match(str(asset.get("name") or ""))), {})
    digest = str(asset.get("digest") or "")
    try:
        size = max(0, int(asset.get("size") or 0))
    except (TypeError, ValueError):
        size = 0
    return Release(
        version=tag.lstrip("vV"),
        url=str(data.get("html_url") or RELEASES_PAGE),
        notes=str(data.get("body") or ""),
        asset_url=str(asset.get("browser_download_url") or ""),
        asset_size=size,
        asset_sha256=digest.removeprefix("sha256:").lower() if digest.startswith("sha256:") else "",
    )


def check_for_update(timeout: float = 5.0, opener=urllib.request.urlopen, current: str | None = None) -> Release | None:
    """Zwraca najnowsze wydanie, jeśli jest nowsze od uruchomionej wersji; przy braku sieci – None."""
    try:
        release = latest_release(timeout, opener)
    except UpdateError:
        return None
    return release if release is not None and is_newer(release.version, current) else None


def release_notes_text(markdown: str) -> str:
    """Opis wydania z GitHuba (Markdown) jako zwykły tekst do okna aktualizacji."""
    lines = []
    for line in re.sub(r"<!--.*?-->", "", markdown, flags=re.DOTALL).splitlines():
        line = line.strip()
        if line.lower().startswith(("**full changelog**", "full changelog")):
            continue
        line = re.sub(r"^#+\s*", "", line)
        line = re.sub(r"^[*-]\s+", "• ", line)
        line = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", line)
        line = line.replace("**", "").replace("`", "")
        if line or (lines and lines[-1]):
            lines.append(line)
    return "\n".join(lines).strip()


# ---------------------------------------------------------------------- samoczynna aktualizacja


def running_executable() -> Path | None:
    """Plik programu, jeśli to pojedynczy .exe; None dla wersji ZIP (biblioteki obok programu) i źródeł."""
    if sys.platform != "win32" or not getattr(sys, "frozen", False):
        return None
    executable = Path(sys.executable).resolve()
    bundle = Path(getattr(sys, "_MEIPASS", executable.parent)).resolve()
    if bundle == executable.parent or bundle.is_relative_to(executable.parent):
        return None
    return executable


def can_self_update(release: Release) -> bool:
    return bool(release.asset_url) and running_executable() is not None


def target_path(current: Path, version: str) -> Path:
    """DicomExporter-1.0.0.exe → DicomExporter-1.1.0.exe; plik o innej nazwie zachowuje swoją nazwę."""
    return current.with_name(f"DicomExporter-{version}.exe") if VERSIONED_EXE.match(current.name) else current


def _is_windows_program(path: Path) -> bool:
    with path.open("rb") as handle:
        return handle.read(2) == b"MZ"


def download(
    release: Release,
    folder: Path,
    progress: Callable[[int, int], None] | None = None,
    cancel: threading.Event | None = None,
    opener=urllib.request.urlopen,
    timeout: float = 30.0,
) -> Path:
    """Pobiera plik .exe wydania do `folder` i sprawdza go; zwraca ścieżkę pliku tymczasowego."""
    if not release.asset_url:
        raise UpdateError(t("update_err_no_asset"))
    partial = folder / f"DicomExporter-{release.version}.exe{DOWNLOAD_SUFFIX}"
    try:
        handle = partial.open("wb")
    except OSError as exc:
        raise UpdateError(t("update_err_folder", folder=folder)) from exc

    digest = hashlib.sha256()
    received = 0
    try:
        with handle, opener(_request(release.asset_url, "application/octet-stream"), timeout=timeout) as response:
            total = release.asset_size
            if not total and getattr(response, "headers", None) is not None:
                total = int(response.headers.get("Content-Length") or 0)
            while chunk := response.read(CHUNK_SIZE):
                if cancel is not None and cancel.is_set():
                    raise UpdateCancelled
                handle.write(chunk)
                digest.update(chunk)
                received += len(chunk)
                if progress is not None:
                    progress(received, total)
    except UpdateCancelled:
        partial.unlink(missing_ok=True)
        raise
    except (OSError, ValueError) as exc:
        partial.unlink(missing_ok=True)
        raise UpdateError(t("update_err_download", error=exc)) from exc

    if release.asset_size and received != release.asset_size:
        problem = t("update_err_size")
    elif release.asset_sha256 and digest.hexdigest() != release.asset_sha256:
        problem = t("update_err_checksum")
    elif not _is_windows_program(partial):
        problem = t("update_err_invalid")
    else:
        return partial
    partial.unlink(missing_ok=True)
    raise UpdateError(problem)


def install(downloaded: Path, current: Path, version: str) -> tuple[Path, Path]:
    """Umieszcza pobrany plik na miejscu programu; zwraca (nowy program, stary plik do usunięcia)."""
    versioned = current.with_name(f"DicomExporter-{version}.exe")
    try:
        target = target_path(current, version)
        if target != current:
            os.replace(downloaded, target)
            return target, current
        # Działający program można przemianować (ale nie usunąć), więc zwalniamy jego nazwę dla nowej wersji.
        old = current.with_name(current.name + ".old")
        old.unlink(missing_ok=True)
        try:
            os.replace(current, old)
        except OSError:
            os.replace(downloaded, versioned)
            return versioned, current
        try:
            os.replace(downloaded, current)
        except OSError:
            os.replace(old, current)
            raise
        return current, old
    except OSError as exc:
        downloaded.unlink(missing_ok=True)
        raise UpdateError(t("update_err_install", error=exc)) from exc


def restart(executable: Path, leftover: Path) -> None:
    """Uruchamia nową wersję, która usunie `leftover` po zamknięciu bieżącego procesu."""
    env = dict(os.environ)
    # Nowy .exe ma rozpakować własne biblioteki, a nie korzystać z tymczasowych plików kończącego się procesu.
    env["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
    flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    try:
        subprocess.Popen(
            [str(executable), AFTER_UPDATE_FLAG, str(leftover)],
            cwd=str(executable.parent),
            env=env,
            close_fds=True,
            creationflags=flags,
        )
    except OSError as exc:
        raise UpdateError(t("update_err_start", error=exc)) from exc


def is_leftover(path: Path, current: Path) -> bool:
    """Chroni przed usunięciem czegokolwiek poza starą kopią programu z tego samego folderu."""
    try:
        path, current = Path(path).resolve(), Path(current).resolve()
    except OSError:
        return False
    if path == current or path.parent != current.parent:
        return False
    name = path.name.lower()
    if name == current.name.lower() + ".old" or VERSIONED_EXE.match(path.name):
        return True
    return name.startswith("dicomexporter") and name.endswith((".exe", ".exe.old"))


def remove_leftover(path: Path, current: Path | None = None, timeout: float = 60.0, sleep=time.sleep) -> bool:
    """Usuwa stary plik programu, gdy tylko zakończy się jego proces (plik jest do tego czasu zablokowany)."""
    current = current or running_executable()
    if current is None or not is_leftover(path, current):
        return False
    for partial in current.parent.glob(f"DicomExporter-*.exe{DOWNLOAD_SUFFIX}"):
        try:
            partial.unlink()
        except OSError:
            pass
    deadline = time.monotonic() + timeout
    while True:
        try:
            Path(path).unlink(missing_ok=True)
            return True
        except OSError:
            if time.monotonic() >= deadline:
                return False
            sleep(0.5)
