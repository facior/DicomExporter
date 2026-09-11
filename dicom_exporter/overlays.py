"""Nakładki wpalane w eksportowane obrazy: podziałka w milimetrach i informacje o obrazie."""

from __future__ import annotations

import math
from functools import lru_cache

import numpy as np
from PIL import Image, ImageDraw, ImageFont
from pydicom.dataset import Dataset

from .i18n import t


def _pair(value) -> tuple[float, float] | None:
    try:
        row, column = float(value[0]), float(value[1])
    except (TypeError, ValueError, IndexError, KeyError):
        return None
    return (row, column) if row > 0 and column > 0 else None


def pixel_spacing(ds: Dataset, frame_index: int = 0) -> tuple[float, float] | None:
    """Rozmiar piksela w mm (wiersz, kolumna): PixelSpacing, grupy funkcyjne, ImagerPixelSpacing lub regiony USG."""
    candidates = [ds.get("PixelSpacing")]
    groups = []
    per_frame = ds.get("PerFrameFunctionalGroupsSequence")
    if per_frame and frame_index < len(per_frame):
        groups.append(per_frame[frame_index])
    shared = ds.get("SharedFunctionalGroupsSequence")
    if shared:
        groups.append(shared[0])
    for group in groups:
        measures = group.get("PixelMeasuresSequence")
        if measures:
            candidates.append(measures[0].get("PixelSpacing"))
    candidates += [ds.get("ImagerPixelSpacing"), ds.get("NominalScannedPixelSpacing")]
    for candidate in candidates:
        spacing = _pair(candidate) if candidate is not None else None
        if spacing:
            return spacing
    for region in ds.get("SequenceOfUltrasoundRegions") or []:
        if region.get("PhysicalUnitsXDirection") == 3 and region.get("PhysicalUnitsYDirection") == 3:  # centymetry
            spacing = _pair(
                [abs(float(region.get("PhysicalDeltaY") or 0)) * 10, abs(float(region.get("PhysicalDeltaX") or 0)) * 10]
            )
            if spacing:
                return spacing
    return None


def nice_length(max_mm: float) -> float | None:
    """Największa „okrągła” długość (1, 2 lub 5 × 10ⁿ mm) nie większa niż `max_mm`."""
    if not math.isfinite(max_mm) or max_mm <= 0:
        return None
    exponent = math.floor(math.log10(max_mm))
    for power in (exponent, exponent - 1):
        for step in (5, 2, 1):
            value = step * 10.0**power
            if value <= max_mm:
                return value
    return None


def format_length(mm: float) -> str:
    if mm >= 10 and round(mm) % 10 == 0:
        return f"{mm / 10:g} cm"
    return f"{mm:g} mm"


def _format_date(value) -> str:
    text = str(value or "").strip()
    return f"{text[:4]}-{text[4:6]}-{text[6:8]}" if len(text) == 8 and text.isdigit() else text


def info_lines(ds: Dataset, frame_index: int, total_frames: int, options) -> list[str]:
    lines: list[str] = []
    if options.overlay_patient:
        name = str(ds.get("PatientName") or "").replace("^", " ").strip()
        patient_id = str(ds.get("PatientID") or "").strip()
        lines.append(" · ".join(part for part in (name, patient_id) if part))
    if options.overlay_info:
        parts = [str(ds.get("Modality") or "")]
        if ds.get("SeriesNumber") not in (None, ""):
            parts.append(t("overlay_series", number=ds.get("SeriesNumber")))
        if ds.get("InstanceNumber") not in (None, ""):
            parts.append(t("overlay_image", number=ds.get("InstanceNumber")))
        if total_frames > 1:
            parts.append(t("overlay_frame", current=frame_index + 1, total=total_frames))
        try:
            parts.append(t("overlay_slice", value=f"{float(ds.get('SliceLocation')):.1f}"))
        except (TypeError, ValueError):
            pass
        lines.append(" · ".join(part for part in parts if part))
        lines.append(str(ds.get("SeriesDescription") or ds.get("StudyDescription") or ""))
        lines.append(_format_date(ds.get("StudyDate") or ds.get("SeriesDate") or ds.get("AcquisitionDate")))
    return [line for line in lines if line]


@lru_cache(maxsize=32)
def _font(size: int):
    for name in ("segoeui.ttf", "arial.ttf", "DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default(size=size)


def draw_overlays(
    image: Image.Image, ds: Dataset, frame_index: int, total_frames: int, options, spacing_scale: float = 1.0
) -> Image.Image:
    """Rysuje biały tekst i podziałkę z czarnym obrysem; działa dla obrazów L, I;16 i RGB."""
    width, height = image.size
    size = max(11, round(min(width, height) * 0.035))
    font = _font(size)
    stroke = max(1, round(size / 7))
    margin = max(4, round(size * 0.6))
    outline_layer = Image.new("L", image.size, 0)
    fill_layer = Image.new("L", image.size, 0)
    outline, fill = ImageDraw.Draw(outline_layer), ImageDraw.Draw(fill_layer)
    drawn = False

    def text(position: tuple[int, int], value: str) -> None:
        outline.text(position, value, font=font, fill=255, stroke_width=stroke, stroke_fill=255)
        fill.text(position, value, font=font, fill=255)

    y = margin
    for line in info_lines(ds, frame_index, total_frames, options):
        text((margin, y), line)
        y += round(size * 1.3)
        drawn = True

    spacing = pixel_spacing(ds, frame_index) if options.overlay_scale else None
    if spacing:
        mm_per_pixel = spacing[1] * spacing_scale
        length = nice_length(width * 0.25 * mm_per_pixel)
        bar = round(length / mm_per_pixel) if length else 0
        if bar >= 8:
            thickness = max(2, round(size / 4))
            left, bottom = margin, height - margin
            boxes = [
                (left, bottom - thickness, left + bar, bottom),
                (left, bottom - thickness * 3, left + thickness, bottom),
                (left + bar - thickness, bottom - thickness * 3, left + bar, bottom),
            ]
            for box in boxes:
                outline.rectangle((box[0] - stroke, box[1] - stroke, box[2] + stroke, box[3] + stroke), fill=255)
                fill.rectangle(box, fill=255)
            text((left, bottom - thickness * 3 - round(size * 1.4)), format_length(length))
            drawn = True

    return _composite(image, outline_layer, fill_layer) if drawn else image


def _composite(image: Image.Image, outline_layer: Image.Image, fill_layer: Image.Image) -> Image.Image:
    high = 65535.0 if image.mode == "I;16" else 255.0
    source = np.asarray(image)
    array = source.astype(np.float32)
    outline = np.asarray(outline_layer, dtype=np.float32) / 255.0
    fill = np.asarray(fill_layer, dtype=np.float32) / 255.0
    if array.ndim == 3:
        outline, fill = outline[..., np.newaxis], fill[..., np.newaxis]
    array = array * (1.0 - outline)
    array = array * (1.0 - fill) + high * fill
    return Image.fromarray(np.clip(np.rint(array), 0, high).astype(source.dtype))
