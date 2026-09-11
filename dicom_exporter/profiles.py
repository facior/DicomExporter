"""Profile eksportu: gotowe zestawy ustawień oraz profile zapisane przez użytkownika."""

from __future__ import annotations

from .i18n import t

# Ustawienia zapisywane w profilu (nazwy jak w pliku ustawień aplikacji)
PROFILE_KEYS = (
    "format",
    "bit_depth",
    "quality",
    "windowing",
    "resize_mode",
    "max_width",
    "max_height",
    "scale_percent",
    "export_mode",
    "fps",
    "all_frames",
    "overlay_scale",
    "overlay_info",
    "overlay_patient",
    "anonymize_keep_dates",
)

_NO_OVERLAYS = {"overlay_scale": False, "overlay_info": False, "overlay_patient": False}

BUILTIN_PROFILES: dict[str, dict] = {
    "presentation": {
        "format": "JPG",
        "bit_depth": 8,
        "quality": 92,
        "windowing": "dicom",
        "resize_mode": "fit",
        "max_width": 1920,
        "max_height": 1080,
        "export_mode": "images",
        "all_frames": True,
        "overlay_scale": True,
        "overlay_info": True,
        "overlay_patient": False,
    },
    "analysis16": {
        "format": "PNG",
        "bit_depth": 16,
        "windowing": "minmax",
        "resize_mode": "none",
        "export_mode": "images",
        "all_frames": True,
        **_NO_OVERLAYS,
    },
    "email": {
        "format": "JPG",
        "bit_depth": 8,
        "quality": 80,
        "windowing": "dicom",
        "resize_mode": "fit",
        "max_width": 1024,
        "max_height": 1024,
        "export_mode": "images",
        "all_frames": False,
        **_NO_OVERLAYS,
    },
    "anonymized_dicom": {
        "export_mode": "dicom",
        "all_frames": True,
        "anonymize_keep_dates": False,
    },
    "cine_mp4": {
        "export_mode": "mp4",
        "fps": 15,
        "windowing": "dicom",
        "resize_mode": "none",
        "all_frames": True,
        "overlay_scale": True,
        "overlay_info": True,
        "overlay_patient": False,
    },
}


def builtin_label(key: str) -> str:
    return t(f"profile_{key}")


def convert_kwargs(values: dict) -> dict:
    """Zamienia wartości profilu na argumenty ConvertOptions."""
    return {("fmt" if key == "format" else key): value for key, value in values.items() if key in PROFILE_KEYS}
