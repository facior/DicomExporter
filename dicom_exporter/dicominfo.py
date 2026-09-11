"""Informacje o plikach DICOM: kolumny listy, drzewo tagów i struktura płyt (DICOMDIR)."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pydicom
from pydicom.dataset import Dataset
from pydicom.fileset import FileSet
from pydicom.multival import MultiValue

from .converter import DicomConversionError
from .i18n import plural, t

_HEADER_TAGS = ["Modality", "SeriesNumber", "SeriesInstanceUID", "InstanceNumber", "NumberOfFrames", "Rows", "Columns"]
_BINARY_VRS = {"OB", "OW", "OF", "OD", "OL", "OV", "UN"}
MAX_SEQUENCE_ITEMS = 50
MAX_VALUE_LENGTH = 200


def _int(value) -> int | None:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


@dataclass(frozen=True)
class FileInfo:
    """Dane do kolumn listy plików (odczytane z nagłówka, bez dekodowania obrazu)."""

    modality: str = ""
    series_number: int | None = None
    series_uid: str = ""
    instance_number: int | None = None
    frames: int | None = None
    rows: int | None = None
    columns: int | None = None
    file_size: int = 0


def read_file_info(path: Path) -> FileInfo:
    try:
        size = path.stat().st_size
    except OSError:
        size = 0
    try:
        ds = pydicom.dcmread(path, stop_before_pixels=True, force=True, specific_tags=_HEADER_TAGS)
    except Exception:
        return FileInfo(file_size=size)
    rows = _int(ds.get("Rows"))
    return FileInfo(
        modality=str(ds.get("Modality") or ""),
        series_number=_int(ds.get("SeriesNumber")),
        series_uid=str(ds.get("SeriesInstanceUID") or ""),
        instance_number=_int(ds.get("InstanceNumber")),
        frames=_int(ds.get("NumberOfFrames")) or (1 if rows else None),
        rows=rows,
        columns=_int(ds.get("Columns")),
        file_size=size,
    )


def format_size(size: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} GB"


# --------------------------------------------------------------------------- tagi


@dataclass
class TagRow:
    tag: str
    name: str
    vr: str
    value: str
    children: list[TagRow] = field(default_factory=list)


def _value_text(element) -> str:
    value = element.value
    if element.VR in _BINARY_VRS or isinstance(value, (bytes, bytearray)):
        return f"<{plural(len(value) if value is not None else 0, 'byte')}>"
    if isinstance(value, MultiValue):
        text = "\\".join(str(item) for item in value)
    else:
        text = "" if value is None else str(value)
    text = " ".join(text.split())
    return text if len(text) <= MAX_VALUE_LENGTH else f"{text[:MAX_VALUE_LENGTH]}…"


def dataset_tags(ds: Dataset) -> list[TagRow]:
    """Elementy zbioru danych jako drzewo (sekwencje mają elementy potomne)."""
    rows: list[TagRow] = []
    for element in ds:
        try:
            tag = f"({element.tag.group:04X},{element.tag.element:04X})"
            if element.VR == "SQ":
                items = element.value or []
                row = TagRow(tag, element.name, "SQ", plural(len(items), "item"))
                for index, item in enumerate(items[:MAX_SEQUENCE_ITEMS], start=1):
                    row.children.append(TagRow("", t("tag_item", index=index), "", "", dataset_tags(item)))
                if len(items) > MAX_SEQUENCE_ITEMS:
                    row.children.append(TagRow("", t("tag_more_items", count=len(items) - MAX_SEQUENCE_ITEMS), "", ""))
            else:
                row = TagRow(tag, element.name, str(element.VR), _value_text(element))
        except Exception:  # uszkodzony element nie blokuje wyświetlenia pozostałych
            continue
        rows.append(row)
    return rows


# --------------------------------------------------------------------------- DICOMDIR


@dataclass
class DirSeries:
    uid: str
    number: str
    modality: str
    description: str
    files: list[Path] = field(default_factory=list)


@dataclass
class DirStudy:
    uid: str
    date: str
    description: str
    series: dict[str, DirSeries] = field(default_factory=dict)


@dataclass
class DirPatient:
    patient_id: str
    name: str
    studies: dict[str, DirStudy] = field(default_factory=dict)


def is_dicomdir(path: Path) -> bool:
    return path.name.upper() == "DICOMDIR" and path.is_file()


def find_dicomdir(folder: Path) -> Path | None:
    candidate = folder / "DICOMDIR"
    return candidate if candidate.is_file() else None


def _attribute(instance, keyword: str) -> str:
    try:
        value = getattr(instance, keyword)
    except AttributeError:
        return ""
    return "" if value is None else str(value)


def read_dicomdir(path: Path) -> list[DirPatient]:
    """Struktura płyty: pacjent → badanie → seria → pliki."""
    try:
        file_set = FileSet(pydicom.dcmread(path))
        instances = list(file_set)
    except Exception as exc:
        raise DicomConversionError(t("err_dicomdir", error=" ".join(str(exc).split()))) from exc
    images = [instance for instance in instances if instance.node.record_type == "IMAGE"] or instances

    patients: dict[str, DirPatient] = {}
    for instance in images:
        patient_id = _attribute(instance, "PatientID")
        patient = patients.setdefault(patient_id, DirPatient(patient_id, _attribute(instance, "PatientName")))
        study_uid = _attribute(instance, "StudyInstanceUID")
        study = patient.studies.setdefault(
            study_uid,
            DirStudy(study_uid, _attribute(instance, "StudyDate"), _attribute(instance, "StudyDescription")),
        )
        series_uid = _attribute(instance, "SeriesInstanceUID")
        series = study.series.setdefault(
            series_uid,
            DirSeries(
                series_uid,
                _attribute(instance, "SeriesNumber"),
                _attribute(instance, "Modality"),
                _attribute(instance, "SeriesDescription"),
            ),
        )
        series.files.append(Path(instance.path))
    return list(patients.values())
