"""Szablony nazw plików i folderów, np. "{Modality}_{SeriesNumber:03}_{InstanceNumber:04}".

Pola to słowa kluczowe DICOM (np. {StudyDate}) lub przyjazne aliasy ({Modalność}, {Seria}, {NrObrazu}),
a także {file} – nazwa pliku źródłowego i {frame} – numer klatki. Po dwukropku można podać
format liczby, np. {InstanceNumber:04} daje 0007.
"""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

from pydicom.datadict import keyword_dict
from pydicom.dataset import Dataset
from pydicom.multival import MultiValue

FILE = "file"
FRAME = "frame"
MISSING = "NA"
DEFAULT_NAME_TEMPLATE = "{file}"
DEFAULT_FOLDER_TEMPLATE = "{StudyDate}_{StudyDescription}/S{SeriesNumber}_{SeriesDescription}"

TOKEN = re.compile(r"\{([^{}:]+)(?::([^{}]*))?\}")
_FORBIDDEN = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_RESERVED = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}
_DIACRITICS = str.maketrans("ąćęłńóśźż", "acelnoszz")

# Aliasy w postaci znormalizowanej (małe litery, bez polskich znaków, spacji, "_" i "-")
ALIASES = {
    "file": FILE,
    "plik": FILE,
    "frame": FRAME,
    "klatka": FRAME,
    "modality": "Modality",
    "modalnosc": "Modality",
    "series": "SeriesNumber",
    "seria": "SeriesNumber",
    "instance": "InstanceNumber",
    "nrobrazu": "InstanceNumber",
    "obraz": "InstanceNumber",
    "databadania": "StudyDate",
    "opisbadania": "StudyDescription",
    "opisserii": "SeriesDescription",
    "pacjent": "PatientName",
    "idpacjenta": "PatientID",
    "czesciala": "BodyPartExamined",
}

# Pola podpowiadane w interfejsie
SUGGESTED_FIELDS = (
    "file",
    "frame",
    "Modality",
    "SeriesNumber",
    "InstanceNumber",
    "SeriesDescription",
    "StudyDate",
    "StudyDescription",
    "BodyPartExamined",
    "PatientID",
)


def _normalize(name: str) -> str:
    return re.sub(r"[\s_\-]", "", name.strip().lower().translate(_DIACRITICS))


@lru_cache(maxsize=1)
def _keywords_lower() -> dict[str, str]:
    return {keyword.lower(): keyword for keyword in keyword_dict}


def resolve_field(name: str) -> str | None:
    """Zamienia nazwę pola na słowo kluczowe DICOM, FILE lub FRAME (None = nieznane pole)."""
    alias = ALIASES.get(_normalize(name))
    if alias is not None:
        return alias
    stripped = name.strip()
    if stripped in keyword_dict:
        return stripped
    return _keywords_lower().get(stripped.lower())


def template_fields(template: str) -> list[str]:
    return [match.group(1) for match in TOKEN.finditer(template or "")]


def unknown_fields(template: str) -> list[str]:
    return [name for name in template_fields(template) if resolve_field(name) is None]


def has_frame_field(template: str) -> bool:
    return any(resolve_field(name) == FRAME for name in template_fields(template))


def sanitize(part: str, limit: int = 120) -> str:
    """Bezpieczny fragment nazwy pliku/folderu w Windows."""
    part = _FORBIDDEN.sub("_", str(part))
    part = re.sub(r"\s+", " ", part).strip().rstrip(". ")
    if part.split(".")[0].upper() in _RESERVED:
        part = f"_{part}"
    return part[:limit].rstrip(". ")


def _value(field: str, ds: Dataset | None, file_stem: str, frame: int):
    if field == FILE:
        return file_stem
    if field == FRAME:
        return frame
    value = ds.get(field) if ds is not None else None
    if value is None or value == "":
        return None
    if isinstance(value, (MultiValue, list, tuple)):
        return "-".join(str(item) for item in value)
    return value


def _format(value, spec: str | None) -> str:
    if spec:
        try:
            if re.fullmatch(r"0?\d*d?", spec):
                return format(int(float(value)), spec if spec.endswith("d") else f"{spec}d")
            return format(value, spec)
        except (TypeError, ValueError):
            pass
    return str(value)


def render(template: str, ds: Dataset | None, *, file_stem: str, frame: int = 1, frame_digits: int = 3) -> str:
    def replace(match: re.Match) -> str:
        field = resolve_field(match.group(1))
        if field is None:
            return MISSING
        value = _value(field, ds, file_stem, frame)
        if value is None:
            return MISSING
        spec = match.group(2) or (f"0{frame_digits}d" if field == FRAME else None)
        return _format(value, spec).replace("/", "_").replace("\\", "_")

    return TOKEN.sub(replace, template)


def render_filename(
    template: str, ds: Dataset | None, *, file_stem: str, frame: int = 1, total_frames: int = 1
) -> str:
    """Nazwa pliku bez rozszerzenia. Przy wielu klatkach dopisuje numer klatki, jeśli szablon go nie ma."""
    template = template or DEFAULT_NAME_TEMPLATE
    digits = max(3, len(str(total_frames)))
    name = sanitize(render(template, ds, file_stem=file_stem, frame=frame, frame_digits=digits)) or MISSING
    if total_frames > 1 and not has_frame_field(template):
        name = f"{name}_frame{frame:0{digits}d}"
    return name


def render_folder(template: str, ds: Dataset | None, *, file_stem: str) -> Path:
    """Ścieżka względna z szablonu; "/" lub "\\" oddziela kolejne poziomy folderów."""
    parts = [sanitize(render(part, ds, file_stem=file_stem)) for part in re.split(r"[\\/]+", template or "")]
    parts = [part for part in parts if part]
    return Path(*parts) if parts else Path()
