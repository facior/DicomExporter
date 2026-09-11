"""Sprawdzanie, czy na GitHubie jest nowsza wersja programu (bez wysyłania żadnych danych o plikach)."""

from __future__ import annotations

import json
import re
import urllib.request
from dataclasses import dataclass

from . import __version__

GITHUB_REPO = "facior/DicomExporter"
LATEST_RELEASE_API = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
RELEASES_PAGE = f"https://github.com/{GITHUB_REPO}/releases"


@dataclass(frozen=True)
class Release:
    version: str
    url: str


def parse_version(text: str) -> tuple[int, ...]:
    """„v1.10.2” → (1, 10, 2); brakujące części traktowane są jak zero."""
    numbers = [int(part) for part in re.findall(r"\d+", text)[:3]]
    return tuple(numbers + [0] * (3 - len(numbers)))


def is_newer(candidate: str, current: str = __version__) -> bool:
    return parse_version(candidate) > parse_version(current)


def check_for_update(timeout: float = 5.0, opener=urllib.request.urlopen) -> Release | None:
    """Zwraca najnowsze wydanie, jeśli jest nowsze od uruchomionej wersji; przy braku sieci – None."""
    request = urllib.request.Request(
        LATEST_RELEASE_API,
        headers={"Accept": "application/vnd.github+json", "User-Agent": f"DicomExporter/{__version__}"},
    )
    try:
        with opener(request, timeout=timeout) as response:
            data = json.load(response)
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or data.get("draft") or data.get("prerelease"):
        return None
    tag = str(data.get("tag_name") or "")
    if not tag or not is_newer(tag):
        return None
    return Release(tag.lstrip("vV"), str(data.get("html_url") or RELEASES_PAGE))
