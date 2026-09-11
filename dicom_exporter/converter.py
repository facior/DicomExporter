"""Rdzeń konwersji DICOM -> obrazy, animacje i kolaże (niezależny od interfejsu)."""

from __future__ import annotations

import itertools
import math
import os
import re
import threading
from collections.abc import Iterable, Iterator
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from functools import partial
from pathlib import Path

import numpy as np
import pydicom
from PIL import Image, ImageDraw, ImageFont
from pydicom.dataset import Dataset, FileMetaDataset
from pydicom.multival import MultiValue
from pydicom.pixels import apply_color_lut, apply_modality_lut, apply_voi_lut, iter_pixels, pixel_array
from pydicom.uid import ExplicitVRBigEndian, ExplicitVRLittleEndian, ImplicitVRLittleEndian

from . import naming
from .anonymize import Anonymizer
from .i18n import plural, t
from .overlays import draw_overlays

IMAGE_FORMATS: dict[str, str] = {
    "PNG": ".png",
    "JPG": ".jpg",
    "JPEG": ".jpeg",
    "TIFF": ".tiff",
    "WEBP": ".webp",
    "BMP": ".bmp",
}
OUTPUT_FORMATS = IMAGE_FORMATS
HIGH_BIT_DEPTH_FORMATS = frozenset({"PNG", "TIFF"})
QUALITY_FORMATS = frozenset({"JPG", "JPEG", "WEBP"})
DICOM_EXTENSIONS = frozenset({".dcm", ".dicom", ".dic", ".ima"})

WINDOW_DICOM = "dicom"  # okno (Window Center/Width lub VOI LUT) zapisane w pliku
WINDOW_MINMAX = "minmax"  # rozciągnięcie pełnego zakresu wartości pikseli
WINDOW_CUSTOM = "custom"  # własny środek i szerokość okna
WINDOW_MODES = (WINDOW_DICOM, WINDOW_MINMAX, WINDOW_CUSTOM)

# Typowe okna CT: (środek, szerokość) w jednostkach Hounsfielda
CT_PRESETS: dict[str, tuple[float, float]] = {
    "brain": (40, 80),
    "soft_tissue": (50, 400),
    "lung": (-600, 1500),
    "bone": (400, 1800),
    "mediastinum": (50, 350),
    "liver": (30, 150),
}

RESIZE_NONE = "none"
RESIZE_FIT = "fit"  # zmniejsz do maksymalnych wymiarów
RESIZE_SCALE = "scale"  # skaluj o procent
RESIZE_MODES = (RESIZE_NONE, RESIZE_FIT, RESIZE_SCALE)

LAYOUT_FLAT = "flat"
LAYOUT_SOURCE = "source"
LAYOUT_TEMPLATE = "template"
LAYOUTS = (LAYOUT_FLAT, LAYOUT_SOURCE, LAYOUT_TEMPLATE)

EXPORT_IMAGES = "images"
EXPORT_GIF = "gif"
EXPORT_MP4 = "mp4"
EXPORT_MONTAGE = "montage"
EXPORT_DICOM = "dicom"  # anonimizowane kopie plików DICOM
EXPORT_MODES = (EXPORT_IMAGES, EXPORT_GIF, EXPORT_MP4, EXPORT_MONTAGE, EXPORT_DICOM)
SERIES_EXPORT_MODES = (EXPORT_GIF, EXPORT_MP4, EXPORT_MONTAGE)
OVERLAY_EXPORT_MODES = (EXPORT_IMAGES, EXPORT_GIF, EXPORT_MP4)

MAX_WORKERS = 8
MAX_SERIES_WORKERS = 4
MONTAGE_TILE = 256
MONTAGE_MAX_TILES = 100

_PIXEL_DATA_KEYWORDS = ("PixelData", "FloatPixelData", "DoubleFloatPixelData")


class DicomConversionError(Exception):
    """Błąd konwersji z komunikatem przeznaczonym dla użytkownika."""


@dataclass(frozen=True)
class ConvertOptions:
    fmt: str = "PNG"
    bit_depth: int = 8
    quality: int = 95
    windowing: str = WINDOW_DICOM
    window_center: float = 40.0
    window_width: float = 400.0
    resize_mode: str = RESIZE_NONE
    max_width: int = 1024
    max_height: int = 1024
    scale_percent: int = 50
    name_template: str = naming.DEFAULT_NAME_TEMPLATE
    layout: str = LAYOUT_SOURCE
    folder_template: str = naming.DEFAULT_FOLDER_TEMPLATE
    export_mode: str = EXPORT_IMAGES
    fps: int = 10
    all_frames: bool = True
    overwrite: bool = False
    masks: tuple[tuple[float, float, float, float], ...] = ()  # prostokąty (x0, y0, x1, y1) jako ułamki wymiarów
    overlay_scale: bool = False
    overlay_info: bool = False
    overlay_patient: bool = False
    anonymize_name: str = "ANONIM"
    anonymize_keep_dates: bool = False

    def __post_init__(self) -> None:
        try:
            masks = tuple(tuple(float(value) for value in mask) for mask in self.masks)
        except (TypeError, ValueError):
            raise ValueError(t("err_opt_mask")) from None
        object.__setattr__(self, "masks", masks)
        for mask in masks:
            if len(mask) != 4 or not (0 <= mask[0] < mask[2] <= 1 and 0 <= mask[1] < mask[3] <= 1):
                raise ValueError(t("err_opt_mask"))
        if self.fmt not in IMAGE_FORMATS:
            raise ValueError(t("err_opt_format", value=self.fmt))
        if self.bit_depth not in (8, 16):
            raise ValueError(t("err_opt_bit_depth"))
        if self.bit_depth == 16 and self.export_mode == EXPORT_IMAGES and self.fmt not in HIGH_BIT_DEPTH_FORMATS:
            raise ValueError(t("err_opt_bit_depth_format"))
        if not 1 <= self.quality <= 100:
            raise ValueError(t("err_opt_quality"))
        if self.windowing not in WINDOW_MODES:
            raise ValueError(t("err_opt_window", value=self.windowing))
        if self.window_width <= 0:
            raise ValueError(t("err_opt_window_width"))
        if (
            self.resize_mode not in RESIZE_MODES
            or self.max_width < 1
            or self.max_height < 1
            or not 1 <= self.scale_percent <= 400
        ):
            raise ValueError(t("err_opt_resize"))
        if self.layout not in LAYOUTS:
            raise ValueError(t("err_opt_layout", value=self.layout))
        if self.export_mode not in EXPORT_MODES:
            raise ValueError(t("err_opt_export", value=self.export_mode))
        if not 1 <= self.fps <= 60:
            raise ValueError(t("err_opt_fps"))
        if self.export_mode == EXPORT_DICOM and not self.anonymize_name.strip():
            raise ValueError(t("err_opt_anonymize_name"))
        templates = [self.name_template]
        if self.layout == LAYOUT_TEMPLATE:
            templates.append(self.folder_template)
        unknown = [name for template in templates for name in naming.unknown_fields(template)]
        if unknown:
            raise ValueError(t("err_template", fields=", ".join(unknown)))

    @property
    def overlays_enabled(self) -> bool:
        return self.export_mode in OVERLAY_EXPORT_MODES and (
            self.overlay_scale or self.overlay_info or self.overlay_patient
        )

    @property
    def output_bit_depth(self) -> int:
        high = self.bit_depth == 16 and self.export_mode == EXPORT_IMAGES and self.fmt in HIGH_BIT_DEPTH_FORMATS
        return 16 if high else 8


@dataclass(frozen=True)
class InputFile:
    """Plik do konwersji; `root` to folder, z którego go dodano (jeśli dotyczy)."""

    path: Path
    root: Path | None = None

    def output_subdir(self) -> Path:
        """Podfolder wyjściowy odtwarzający strukturę dodanego folderu."""
        if self.root is None:
            return Path()
        try:
            relative = self.path.parent.relative_to(self.root)
        except ValueError:
            return Path()
        return Path(self.root.name) / relative


@dataclass
class FileResult:
    item: InputFile
    outputs: list[Path] = field(default_factory=list)
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None


class OutputNamer:
    """Przydziela nazwy plików wynikowych tak, by pliki z jednej partii się nie nadpisywały."""

    def __init__(self, overwrite: bool) -> None:
        self.overwrite = overwrite
        self._taken: set[str] = set()
        self._lock = threading.Lock()

    def reserve(self, desired: Path) -> Path:
        with self._lock:
            candidate, counter = desired, 1
            while self._key(candidate) in self._taken or (not self.overwrite and candidate.exists()):
                candidate = desired.with_name(f"{desired.stem}_{counter}{desired.suffix}")
                counter += 1
            self._taken.add(self._key(candidate))
            return candidate

    @staticmethod
    def _key(path: Path) -> str:
        return os.path.normcase(os.path.abspath(path))


# --------------------------------------------------------------------------- wyszukiwanie plików


def natural_key(name: str) -> list:
    return [int(part) if part.isdigit() else part.lower() for part in re.split(r"(\d+)", name)]


def is_probably_dicom(path: Path) -> bool:
    """Szybki test: rozszerzenie DICOM, znacznik 'DICM' na pozycji 128 albo nagłówek starego ACR-NEMA."""
    if path.name.upper() == "DICOMDIR":
        return False
    if path.suffix.lower() in DICOM_EXTENSIONS:
        return True
    try:
        with path.open("rb") as fh:
            header = fh.read(132)
    except OSError:
        return False
    if header[128:132] == b"DICM":
        return True
    # Pliki bez preambuły zaczynają się zwykle od elementu z grupy 0x0002 lub 0x0008 (little endian).
    return len(header) >= 8 and header[0:2] in (b"\x02\x00", b"\x08\x00") and header[3] == 0


def collect_inputs(
    paths: Iterable[str | os.PathLike], skipped: list[Path] | None = None
) -> Iterator[InputFile]:
    """Rozwija listę plików i folderów (rekurencyjnie) do plików DICOM.

    Pliki spoza formatu DICOM są pomijane; jeśli podano `skipped`, trafiają tam
    jawnie wskazane pliki, które odrzucono (pliki z przeszukiwanych folderów są pomijane po cichu).
    """
    for raw in paths:
        path = Path(raw)
        if path.is_dir():
            for dirpath, dirnames, filenames in os.walk(path):
                dirnames.sort(key=natural_key)
                for name in sorted(filenames, key=natural_key):
                    candidate = Path(dirpath, name)
                    if is_probably_dicom(candidate):
                        yield InputFile(candidate, root=path)
        elif path.is_file():
            if is_probably_dicom(path):
                yield InputFile(path)
            elif skipped is not None and path.name.upper() != "DICOMDIR":
                skipped.append(path)


# --------------------------------------------------------------------------- odczyt i dekodowanie


def read_dataset(path: str | os.PathLike) -> Dataset:
    try:
        ds = pydicom.dcmread(path, force=True)
        has_pixels = any(keyword in ds for keyword in _PIXEL_DATA_KEYWORDS)
    except FileNotFoundError:
        raise DicomConversionError(t("err_not_found")) from None
    except PermissionError:
        raise DicomConversionError(t("err_access")) from None
    except Exception as exc:
        raise DicomConversionError(t("err_not_dicom", error=exc)) from exc
    if not has_pixels:
        raise DicomConversionError(t("err_no_pixels"))
    _ensure_transfer_syntax(ds)
    return ds


def _ensure_transfer_syntax(ds: Dataset) -> None:
    """Pliki bez nagłówka meta (np. stare ACR-NEMA) nie mają Transfer Syntax - odtwarzamy go."""
    meta = getattr(ds, "file_meta", None)
    if meta is not None and "TransferSyntaxUID" in meta:
        return
    if meta is None:
        meta = ds.file_meta = FileMetaDataset()
    implicit, little = getattr(ds, "original_encoding", (None, None))
    if little is False:
        meta.TransferSyntaxUID = ExplicitVRBigEndian
    elif implicit is False:
        meta.TransferSyntaxUID = ExplicitVRLittleEndian
    else:
        meta.TransferSyntaxUID = ImplicitVRLittleEndian


def number_of_frames(ds: Dataset) -> int:
    try:
        return max(1, int(ds.get("NumberOfFrames") or 1))
    except (TypeError, ValueError):
        return 1


def _decode_error(ds: Dataset, exc: Exception) -> DicomConversionError:
    transfer_syntax = ds.file_meta.get("TransferSyntaxUID")
    name = getattr(transfer_syntax, "name", transfer_syntax)
    details = " ".join(str(exc).split())  # komunikaty pydicom bywają wielolinijkowe
    return DicomConversionError(t("err_decode", syntax=name, error=details))


def decode_frames(ds: Dataset, first_only: bool = False) -> Iterator[np.ndarray]:
    """Zwraca kolejne klatki obrazu (YBR jest od razu konwertowane do RGB)."""
    try:
        if number_of_frames(ds) == 1:
            yield pixel_array(ds)
        elif first_only:
            yield pixel_array(ds, index=0)
        else:
            yield from iter_pixels(ds)
    except Exception as exc:
        raise _decode_error(ds, exc) from exc


def decode_frame(ds: Dataset, index: int) -> np.ndarray:
    try:
        return pixel_array(ds) if number_of_frames(ds) == 1 else pixel_array(ds, index=index)
    except Exception as exc:
        raise _decode_error(ds, exc) from exc


# --------------------------------------------------------------------------- przetwarzanie pikseli


@dataclass
class _FrameLut:
    slope: float = 1.0
    intercept: float = 0.0
    center: float | None = None
    width: float | None = None
    function: str = "LINEAR"


def _first_number(value) -> float | None:
    if isinstance(value, (MultiValue, list, tuple)):
        if not value:
            return None
        value = value[0]
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _frame_lut(ds: Dataset, frame_index: int) -> _FrameLut:
    """Rescale i okno dla klatki - także z grup funkcyjnych plików Enhanced CT/MR."""
    sources: list[Dataset] = [ds]
    groups = []
    shared = ds.get("SharedFunctionalGroupsSequence")
    if shared:
        groups.append(shared[0])
    per_frame = ds.get("PerFrameFunctionalGroupsSequence")
    if per_frame and frame_index < len(per_frame):
        groups.append(per_frame[frame_index])
    for group in groups:
        for keyword in ("PixelValueTransformationSequence", "FrameVOILUTSequence"):
            sequence = group.get(keyword)
            if sequence:
                sources.append(sequence[0])

    lut = _FrameLut()
    for source in sources:  # późniejsze źródła (per-frame) nadpisują wcześniejsze
        slope = _first_number(source.get("RescaleSlope"))
        if slope:
            lut.slope = slope
        intercept = _first_number(source.get("RescaleIntercept"))
        if intercept is not None:
            lut.intercept = intercept
        center = _first_number(source.get("WindowCenter"))
        width = _first_number(source.get("WindowWidth"))
        if center is not None and width is not None and width > 0:
            lut.center, lut.width = center, width
            lut.function = str(source.get("VOILUTFunction") or "LINEAR").strip().upper()
    return lut


def file_window(ds: Dataset, frame_index: int = 0) -> tuple[float, float] | None:
    """Okno (środek, szerokość) zapisane w pliku, jeśli istnieje."""
    lut = _frame_lut(ds, frame_index)
    return (lut.center, lut.width) if lut.center is not None and lut.width is not None else None


def modality_values(frame: np.ndarray, ds: Dataset, frame_index: int = 0) -> np.ndarray:
    """Wartości po transformacji modalności (np. jednostki Hounsfielda dla CT)."""
    if "ModalityLUTSequence" in ds:
        return apply_modality_lut(frame, ds).astype(np.float32)
    lut = _frame_lut(ds, frame_index)
    data = frame.astype(np.float32)
    if lut.slope != 1.0 or lut.intercept != 0.0:
        data = data * lut.slope + lut.intercept
    return data


def _normalize_minmax(data: np.ndarray) -> np.ndarray:
    finite = data[np.isfinite(data)]
    if finite.size == 0:
        return np.zeros(data.shape, dtype=np.float32)
    low, high = float(finite.min()), float(finite.max())
    if high <= low:
        return np.zeros(data.shape, dtype=np.float32)
    data = np.nan_to_num(data, nan=low, posinf=high, neginf=low)
    return (data - low) / (high - low)


def _apply_window(data: np.ndarray, center: float, width: float, function: str) -> np.ndarray:
    """Funkcje VOI LUT wg DICOM PS3.3 C.11.2.1.2; wynik w zakresie 0-1."""
    if function == "SIGMOID":
        with np.errstate(over="ignore"):
            out = 1.0 / (1.0 + np.exp(-4.0 * (data - center) / width))
    elif function == "LINEAR_EXACT":
        out = (data - center) / width + 0.5
    elif width <= 1:
        out = np.where(data > center - 0.5, 1.0, 0.0)
    else:
        out = (data - (center - 0.5)) / (width - 1) + 0.5
    return np.clip(out, 0.0, 1.0)


def _apply_voi_lut_sequence(data: np.ndarray, ds: Dataset) -> np.ndarray | None:
    try:
        mapped = apply_voi_lut(np.rint(data).astype(np.int64), ds, index=0, prefer_lut=True).astype(np.float32)
        bits = int(ds.VOILUTSequence[0].LUTDescriptor[2])
    except Exception:
        return None
    max_value = (1 << bits) - 1 if 1 <= bits <= 16 else 0
    if max_value <= 0 or mapped.max() > max_value:
        return _normalize_minmax(mapped)
    return np.clip(mapped / max_value, 0.0, 1.0)


def grayscale_levels(frame: np.ndarray, ds: Dataset, frame_index: int, options: ConvertOptions) -> np.ndarray:
    """Jasność pikseli w zakresie 0-1 według wybranego trybu kontrastu."""
    data = modality_values(frame, ds, frame_index)
    if options.windowing == WINDOW_CUSTOM:
        return _apply_window(data, options.window_center, options.window_width, "LINEAR")
    if options.windowing == WINDOW_DICOM:
        lut = _frame_lut(ds, frame_index)
        if lut.center is not None and lut.width is not None:
            return _apply_window(data, lut.center, lut.width, lut.function)
        if ds.get("VOILUTSequence"):
            mapped = _apply_voi_lut_sequence(data, ds)
            if mapped is not None:
                return mapped
    return _normalize_minmax(data)


def _levels_to_array(levels: np.ndarray, bits: int) -> np.ndarray:
    max_value, dtype = (65535, np.uint16) if bits == 16 else (255, np.uint8)
    return np.rint(np.clip(levels, 0.0, 1.0) * max_value).astype(dtype)


def _scale_color(rgb: np.ndarray, max_value: int) -> np.ndarray:
    if rgb.dtype == np.uint8:
        return rgb
    return np.clip(np.rint(rgb.astype(np.float32) * (255.0 / max_value)), 0, 255).astype(np.uint8)


def is_color(ds: Dataset) -> bool:
    photometric = str(ds.get("PhotometricInterpretation") or "").strip().upper()
    return photometric == "PALETTE COLOR" or int(ds.get("SamplesPerPixel") or 1) > 1


def frame_to_image(
    frame: np.ndarray,
    ds: Dataset,
    frame_index: int = 0,
    options: ConvertOptions | None = None,
    *,
    bit_depth: int | None = None,
) -> Image.Image:
    """Zamienia zdekodowaną klatkę na obraz PIL: L lub I;16 (skala szarości) albo RGB."""
    options = options or ConvertOptions()
    bits = bit_depth or options.output_bit_depth
    photometric = str(ds.get("PhotometricInterpretation") or "").strip().upper()
    if frame.ndim == 3 and frame.shape[-1] == 1:
        frame = frame[..., 0]

    if frame.ndim == 2 and photometric == "PALETTE COLOR":
        rgb = apply_color_lut(frame, ds)
        # Część plików deklaruje 16-bitowe LUT-y, ale zapisuje w nich wartości 8-bitowe.
        return Image.fromarray(_scale_color(rgb, 255 if rgb.max() <= 255 else 65535))

    if frame.ndim == 2:
        levels = grayscale_levels(frame, ds, frame_index, options)
        if photometric == "MONOCHROME1":
            levels = 1.0 - levels
        return Image.fromarray(_levels_to_array(levels, bits))

    if frame.ndim == 3 and frame.shape[-1] == 3:
        stored = int(ds.get("BitsStored") or frame.dtype.itemsize * 8)
        return Image.fromarray(np.ascontiguousarray(_scale_color(frame, (1 << stored) - 1)))

    raise DicomConversionError(t("err_layout", shape=frame.shape, photometric=photometric or "?"))


def target_size(width: int, height: int, options: ConvertOptions) -> tuple[int, int]:
    if options.resize_mode == RESIZE_FIT:
        factor = min(options.max_width / width, options.max_height / height, 1.0)
    elif options.resize_mode == RESIZE_SCALE:
        factor = options.scale_percent / 100
    else:
        return width, height
    return max(1, round(width * factor)), max(1, round(height * factor))


def resize_image(image: Image.Image, options: ConvertOptions) -> Image.Image:
    size = target_size(*image.size, options)
    if size == image.size:
        return image
    if image.mode == "I;16":  # Pillow skaluje obrazy 16-bitowe przez tryb zmiennoprzecinkowy
        resized = Image.fromarray(np.asarray(image, dtype=np.float32)).resize(size, Image.Resampling.LANCZOS)
        return Image.fromarray(np.clip(np.rint(np.asarray(resized)), 0, 65535).astype(np.uint16))
    return image.resize(size, Image.Resampling.LANCZOS)


def mask_boxes(masks, width: int, height: int) -> list[tuple[int, int, int, int]]:
    """Prostokąty maskowania w pikselach (lewo, góra, prawo, dół)."""
    boxes = []
    for x0, y0, x1, y1 in masks:
        box = (math.floor(x0 * width), math.floor(y0 * height), math.ceil(x1 * width), math.ceil(y1 * height))
        if box[2] > box[0] and box[3] > box[1]:
            boxes.append(box)
    return boxes


def apply_masks(image: Image.Image, masks) -> Image.Image:
    """Zaczernia wskazane obszary (np. napisy z danymi pacjenta wpalone w obraz)."""
    if not masks:
        return image
    array = np.array(image)
    for left, top, right, bottom in mask_boxes(masks, image.width, image.height):
        array[top:bottom, left:right] = 0
    return Image.fromarray(array)


def render_frame(
    frame: np.ndarray,
    ds: Dataset,
    frame_index: int,
    options: ConvertOptions,
    *,
    bit_depth: int | None = None,
    total_frames: int = 1,
    resize: bool = True,
    overlays: bool = True,
) -> Image.Image:
    """Pełny potok obrazu: kontrast → maski → zmiana rozmiaru → nakładki."""
    image = apply_masks(frame_to_image(frame, ds, frame_index, options, bit_depth=bit_depth), options.masks)
    original_width = image.width
    if resize:
        image = resize_image(image, options)
    if overlays and options.overlays_enabled:
        image = draw_overlays(image, ds, frame_index, total_frames, options, spacing_scale=original_width / image.width)
    return image


# --------------------------------------------------------------------------- zapis obrazów


def output_stem(path: Path) -> str:
    """Nazwa bazowa pliku wynikowego (nazwy typu 1.2.840.113619 nie tracą końcówki)."""
    return path.stem if path.suffix.lower() in DICOM_EXTENSIONS else path.name


def series_stem(ds: Dataset) -> str:
    parts = [str(ds.get("Modality") or "")]
    if ds.get("SeriesNumber") not in (None, ""):
        parts.append(f"S{ds.get('SeriesNumber')}")
    parts.append(str(ds.get("SeriesDescription") or ""))
    return naming.sanitize("_".join(part for part in parts if part)) or t("series_fallback")


def save_image(image: Image.Image, destination: Path, options: ConvertOptions) -> None:
    fmt = options.fmt
    if fmt == "PNG":
        image.save(destination, format="PNG")
    elif fmt in ("JPG", "JPEG"):
        subsampling = 0 if options.quality >= 90 else 2  # 4:4:4 dla wysokiej jakości
        image.save(destination, format="JPEG", quality=options.quality, subsampling=subsampling)
    elif fmt == "TIFF":
        image.save(destination, format="TIFF", compression="tiff_deflate")
    elif fmt == "WEBP":
        if image.mode not in ("RGB", "RGBA"):
            image = image.convert("RGB")
        image.save(destination, format="WEBP", quality=options.quality, lossless=options.quality >= 100, method=4)
    else:
        image.save(destination, format="BMP")


def output_directory(item: InputFile, ds: Dataset, output_dir: str | os.PathLike, options: ConvertOptions) -> Path:
    base = Path(output_dir)
    if options.layout == LAYOUT_SOURCE:
        return base / item.output_subdir()
    if options.layout == LAYOUT_TEMPLATE:
        return base / naming.render_folder(options.folder_template, ds, file_stem=output_stem(item.path))
    return base


def convert_file(
    item: InputFile,
    output_dir: str | os.PathLike,
    options: ConvertOptions,
    namer: OutputNamer | None = None,
) -> list[Path]:
    """Konwertuje jeden plik DICOM na osobne obrazy i zwraca listę zapisanych plików."""
    namer = namer or OutputNamer(options.overwrite)
    ds = read_dataset(item.path)
    total_frames = number_of_frames(ds) if options.all_frames else 1
    target_dir = output_directory(item, ds, output_dir, options)
    extension = IMAGE_FORMATS[options.fmt]
    stem = output_stem(item.path)

    written: list[Path] = []
    for index, frame in enumerate(decode_frames(ds, first_only=not options.all_frames)):
        image = render_frame(frame, ds, index, options, total_frames=number_of_frames(ds))
        name = naming.render_filename(
            options.name_template, ds, file_stem=stem, frame=index + 1, total_frames=total_frames
        )
        try:
            target_dir.mkdir(parents=True, exist_ok=True)
            destination = namer.reserve(target_dir / f"{name}{extension}")
            save_image(image, destination, options)
        except OSError as exc:
            raise DicomConversionError(t("err_save", error=exc)) from exc
        written.append(destination)
    return written


# --------------------------------------------------------------------------- serie: GIF, MP4, kolaż


@dataclass
class SeriesGroup:
    items: list[InputFile]


_SERIES_TAGS = ["SeriesInstanceUID", "InstanceNumber"]


def group_series(items: Iterable[InputFile], cancel_event: threading.Event | None = None) -> list[SeriesGroup]:
    """Grupuje pliki według SeriesInstanceUID i sortuje je według numeru obrazu."""
    groups: dict[str, list[tuple[tuple, InputFile]]] = {}
    for item in items:
        if cancel_event is not None and cancel_event.is_set():
            break
        try:
            header = pydicom.dcmread(item.path, stop_before_pixels=True, force=True, specific_tags=_SERIES_TAGS)
            uid = str(header.get("SeriesInstanceUID") or "")
            instance = _first_number(header.get("InstanceNumber"))
        except Exception:
            uid, instance = "", None
        key = uid or f"file:{item.path}"
        sort_key = (instance if instance is not None else math.inf, natural_key(item.path.name))
        groups.setdefault(key, []).append((sort_key, item))
    return [SeriesGroup([item for _, item in sorted(entries, key=lambda entry: entry[0])]) for entries in groups.values()]


def _fit_canvas(image: Image.Image, size: tuple[int, int]) -> Image.Image:
    if image.size == size:
        return image
    fitted = image.copy()
    fitted.thumbnail(size, Image.Resampling.LANCZOS)
    canvas = Image.new(image.mode, size, 0)
    canvas.paste(fitted, ((size[0] - fitted.width) // 2, (size[1] - fitted.height) // 2))
    return canvas


def _write_gif(images: Iterator[Image.Image], destination: Path, options: ConvertOptions) -> None:
    frames = [image.convert("RGB") if image.mode == "RGB" else image.convert("L") for image in images]
    if not frames:
        raise DicomConversionError(t("err_series_empty"))
    mode = "RGB" if any(frame.mode == "RGB" for frame in frames) else "L"
    size = frames[0].size
    frames = [_fit_canvas(frame.convert(mode), size) for frame in frames]
    frames[0].save(
        destination,
        format="GIF",
        save_all=True,
        append_images=frames[1:],
        duration=max(20, round(1000 / options.fps)),
        loop=0,
    )


def _write_mp4(images: Iterator[Image.Image], destination: Path, options: ConvertOptions) -> None:
    try:
        import imageio_ffmpeg
    except ImportError:
        raise DicomConversionError(t("err_mp4")) from None
    first = next(images, None)
    if first is None:
        raise DicomConversionError(t("err_series_empty"))
    size = (first.width + first.width % 2, first.height + first.height % 2)  # yuv420p wymaga parzystych wymiarów
    writer = imageio_ffmpeg.write_frames(
        str(destination), size, fps=options.fps, quality=8, macro_block_size=1, pix_fmt_in="rgb24"
    )
    try:
        writer.send(None)
        for image in itertools.chain([first], images):
            writer.send(_fit_canvas(image.convert("RGB"), size).tobytes())
        writer.close()
    except Exception as exc:
        writer.close()
        raise DicomConversionError(t("err_video", error=" ".join(str(exc).split()))) from exc


def _write_montage(images: Iterator[Image.Image], destination: Path, options: ConvertOptions) -> None:
    thumbnails = []
    for image in images:
        thumbnail = image.convert("RGB") if image.mode == "RGB" else image.convert("L")
        thumbnail.thumbnail((MONTAGE_TILE, MONTAGE_TILE), Image.Resampling.LANCZOS)
        thumbnails.append(thumbnail)
    if not thumbnails:
        raise DicomConversionError(t("err_series_empty"))
    indices = list(range(len(thumbnails)))
    if len(indices) > MONTAGE_MAX_TILES:  # równomierny wybór klatek z długich serii
        indices = sorted({round(value) for value in np.linspace(0, len(thumbnails) - 1, MONTAGE_MAX_TILES)})

    mode = "RGB" if any(thumbnail.mode == "RGB" for thumbnail in thumbnails) else "L"
    white, black = ((255, 255, 255), (0, 0, 0)) if mode == "RGB" else (255, 0)
    columns = math.ceil(math.sqrt(len(indices)))
    rows = math.ceil(len(indices) / columns)
    gap = 4
    sheet = Image.new(mode, (columns * (MONTAGE_TILE + gap) + gap, rows * (MONTAGE_TILE + gap) + gap), black)
    draw = ImageDraw.Draw(sheet)
    font = ImageFont.load_default(size=16)
    for position, index in enumerate(indices):
        thumbnail = thumbnails[index].convert(mode)
        left = gap + (position % columns) * (MONTAGE_TILE + gap)
        top = gap + (position // columns) * (MONTAGE_TILE + gap)
        sheet.paste(thumbnail, (left + (MONTAGE_TILE - thumbnail.width) // 2, top + (MONTAGE_TILE - thumbnail.height) // 2))
        draw.text((left + 6, top + 4), str(index + 1), fill=white, font=font, stroke_width=2, stroke_fill=black)
    save_image(resize_image(sheet, options), destination, options)


_SERIES_WRITERS = {
    EXPORT_GIF: (".gif", _write_gif),
    EXPORT_MP4: (".mp4", _write_mp4),
}


def export_series(
    group: SeriesGroup,
    output_dir: str | os.PathLike,
    options: ConvertOptions,
    namer: OutputNamer | None = None,
    cancel_event: threading.Event | None = None,
) -> list[FileResult]:
    """Zapisuje całą serię jako jeden plik (GIF, MP4 lub kolaż); wynik dla każdego pliku serii."""
    namer = namer or OutputNamer(options.overwrite)
    errors: dict[InputFile, str] = {}
    used: set[InputFile] = set()
    montage = options.export_mode == EXPORT_MONTAGE  # kolaż: bez zmiany rozmiaru i nakładek na miniaturach

    def frames() -> Iterator[tuple[Dataset, Image.Image]]:
        for item in group.items:
            if cancel_event is not None and cancel_event.is_set():
                return
            try:
                ds = read_dataset(item.path)
                total = number_of_frames(ds)
                for index, frame in enumerate(decode_frames(ds, first_only=not options.all_frames)):
                    used.add(item)
                    yield ds, render_frame(
                        frame, ds, index, options, bit_depth=8, total_frames=total, resize=not montage, overlays=not montage
                    )
            except DicomConversionError as exc:
                errors[item] = str(exc)
            except Exception as exc:
                errors[item] = t("err_unexpected", error=exc)

    stream = frames()
    first = next(stream, None)
    if first is None:
        return [FileResult(item, error=errors.get(item, t("err_series_empty"))) for item in group.items]

    ds = first[0]
    stem = output_stem(group.items[0].path) if len(group.items) == 1 else series_stem(ds)
    target_dir = output_directory(group.items[0], ds, output_dir, options)
    name = naming.render_filename(options.name_template, ds, file_stem=stem)
    images = (image for _, image in itertools.chain([first], stream))
    if montage:
        extension, writer = IMAGE_FORMATS[options.fmt], _write_montage
    else:
        extension, writer = _SERIES_WRITERS[options.export_mode]

    destination = None
    try:
        target_dir.mkdir(parents=True, exist_ok=True)
        destination = namer.reserve(target_dir / f"{name}{extension}")
        writer(images, destination, options)
    except (OSError, DicomConversionError) as exc:
        message = str(exc) if isinstance(exc, DicomConversionError) else t("err_save", error=exc)
        if destination is not None:
            destination.unlink(missing_ok=True)
        return [FileResult(item, error=errors.get(item, message)) for item in group.items]

    if cancel_event is not None and cancel_event.is_set():
        destination.unlink(missing_ok=True)  # niepełna animacja/kolaż nie zostaje na dysku
        return []
    return [
        FileResult(item, outputs=[destination] if item in used and item not in errors else [], error=errors.get(item))
        if item in used or item in errors
        else FileResult(item, error=t("err_series_empty"))
        for item in group.items
    ]


# --------------------------------------------------------------------------- anonimizowane kopie DICOM


def _mask_pixel_data(ds: Dataset, masks) -> None:
    """Zamaskowuje prostokąty w danych pikseli; plik zostanie zapisany bez kompresji."""
    frames = number_of_frames(ds)
    try:
        array = np.array(pixel_array(ds))
    except Exception as exc:
        raise _decode_error(ds, exc) from exc
    stack = array if frames > 1 else array[np.newaxis, ...]
    height, width = stack.shape[1], stack.shape[2]
    photometric = str(ds.get("PhotometricInterpretation") or "").strip().upper()
    if stack.ndim == 4:
        fill = 0
    else:  # czarny niezależnie od interpretacji jasności
        fill = stack.max() if photometric == "MONOCHROME1" else stack.min()
    for left, top, right, bottom in mask_boxes(masks, width, height):
        stack[:, top:bottom, left:right, ...] = fill
    if photometric.startswith("YBR"):  # dekoder zwrócił już RGB
        photometric = "RGB"
    ds.file_meta.TransferSyntaxUID = ExplicitVRLittleEndian
    bits = int(ds.get("BitsStored") or array.dtype.itemsize * 8)
    ds.set_pixel_data(stack if frames > 1 else stack[0], photometric, bits, generate_instance_uid=False)


def export_anonymized(
    item: InputFile,
    output_dir: str | os.PathLike,
    options: ConvertOptions,
    namer: OutputNamer | None = None,
    anonymizer: Anonymizer | None = None,
) -> list[Path]:
    """Zapisuje kopię pliku DICOM bez danych osobowych (z opcjonalnym maskowaniem obszarów obrazu)."""
    namer = namer or OutputNamer(options.overwrite)
    anonymizer = anonymizer or Anonymizer(options.anonymize_name, options.anonymize_keep_dates)
    ds = read_dataset(item.path)
    if options.masks:
        _mask_pixel_data(ds, options.masks)
    anonymizer.apply(ds)
    target_dir = output_directory(item, ds, output_dir, options)
    name = naming.render_filename(options.name_template, ds, file_stem=output_stem(item.path))
    try:
        target_dir.mkdir(parents=True, exist_ok=True)
        destination = namer.reserve(target_dir / f"{name}.dcm")
        try:
            ds.save_as(destination, enforce_file_format=True)
        except (ValueError, AttributeError):  # np. stare pliki bez klasy SOP
            ds.save_as(destination, enforce_file_format=False)
    except OSError as exc:
        raise DicomConversionError(t("err_save", error=exc)) from exc
    return [destination]


def _anonymize_one(
    item: InputFile,
    output_dir: Path,
    options: ConvertOptions,
    namer: OutputNamer,
    anonymizer: Anonymizer,
    cancel_event: threading.Event | None,
) -> list[FileResult]:
    if cancel_event is not None and cancel_event.is_set():
        return []
    try:
        return [FileResult(item, export_anonymized(item, output_dir, options, namer, anonymizer))]
    except DicomConversionError as exc:
        return [FileResult(item, error=str(exc))]
    except Exception as exc:
        return [FileResult(item, error=t("err_unexpected", error=exc))]


# --------------------------------------------------------------------------- konwersja wsadowa


def _convert_one(
    item: InputFile,
    output_dir: Path,
    options: ConvertOptions,
    namer: OutputNamer,
    cancel_event: threading.Event | None,
) -> list[FileResult]:
    if cancel_event is not None and cancel_event.is_set():
        return []
    try:
        return [FileResult(item, convert_file(item, output_dir, options, namer))]
    except DicomConversionError as exc:
        return [FileResult(item, error=str(exc))]
    except Exception as exc:  # nie przerywamy całej partii przez jeden nietypowy plik
        return [FileResult(item, error=t("err_unexpected", error=exc))]


def _export_group(
    group: SeriesGroup,
    output_dir: Path,
    options: ConvertOptions,
    namer: OutputNamer,
    cancel_event: threading.Event | None,
) -> list[FileResult]:
    if cancel_event is not None and cancel_event.is_set():
        return []
    try:
        return export_series(group, output_dir, options, namer, cancel_event)
    except Exception as exc:
        return [FileResult(item, error=t("err_unexpected", error=exc)) for item in group.items]


def convert_batch(
    items: Iterable[InputFile],
    output_dir: str | os.PathLike,
    options: ConvertOptions,
    *,
    workers: int | None = None,
    cancel_event: threading.Event | None = None,
) -> Iterator[FileResult]:
    """Konwertuje pliki równolegle; wyniki zwraca w kolejności ukończenia.

    Po ustawieniu `cancel_event` nierozpoczęte pliki są pomijane (nie pojawiają się w wynikach).
    """
    items = list(items)
    if not items:
        return
    namer = OutputNamer(options.overwrite)
    output_dir = Path(output_dir)
    if options.export_mode == EXPORT_DICOM:
        anonymizer = Anonymizer(options.anonymize_name, options.anonymize_keep_dates)
        tasks = [partial(_anonymize_one, item, output_dir, options, namer, anonymizer, cancel_event) for item in items]
        limit = MAX_WORKERS
    elif options.export_mode == EXPORT_IMAGES:
        tasks = [partial(_convert_one, item, output_dir, options, namer, cancel_event) for item in items]
        limit = MAX_WORKERS
    else:
        groups = group_series(items, cancel_event)
        tasks = [partial(_export_group, group, output_dir, options, namer, cancel_event) for group in groups]
        limit = MAX_SERIES_WORKERS
    if not tasks:
        return
    workers = workers or min(limit, os.cpu_count() or 1, len(tasks))
    pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="dicom-export")
    try:
        futures = [pool.submit(task) for task in tasks]
        for future in as_completed(futures):
            yield from future.result()
    finally:
        pool.shutdown(wait=True, cancel_futures=True)


# --------------------------------------------------------------------------- podgląd


_COMPRESSION_LABELS = (
    ("JPEG 2000", "JPEG 2000"),
    ("JPEG-LS", "JPEG-LS"),
    ("JPEG Lossless", "JPEG Lossless"),
    ("RLE", "RLE"),
    ("JPEG", "JPEG"),
)


def compression_label(ds: Dataset) -> str:
    """Krótka nazwa kompresji pikseli, np. 'JPEG 2000' albo 'bez kompresji'."""
    uid = ds.file_meta.get("TransferSyntaxUID")
    if uid is None:
        return ""
    name = getattr(uid, "name", str(uid))
    try:
        compressed = uid.is_compressed
    except (AttributeError, ValueError):
        return name
    if not compressed:
        return t("uncompressed")
    return next((label for fragment, label in _COMPRESSION_LABELS if fragment in name), name)


def dataset_details(ds: Dataset) -> dict[str, str]:
    """Podstawowe informacje o obrazie (bez danych pacjenta)."""
    details: dict[str, str] = {}
    rows, columns = ds.get("Rows"), ds.get("Columns")
    if rows and columns:
        details["size"] = f"{columns} × {rows} px"
    details["frames"] = plural(number_of_frames(ds), "frame")
    for key, keyword in (("modality", "Modality"), ("photometric", "PhotometricInterpretation")):
        value = ds.get(keyword)
        if value:
            details[key] = str(value)
    bits = ds.get("BitsStored")
    if bits:
        details["bits"] = f"{bits}-bit"
    compression = compression_label(ds)
    if compression:
        details["compression"] = compression
    return details


class PreviewSource:
    """Plik wczytany do podglądu: klatki dekodowane na żądanie z niewielką pamięcią podręczną."""

    CACHE_SIZE = 16

    def __init__(self, path: str | os.PathLike) -> None:
        self.path = Path(path)
        self.ds = read_dataset(path)
        self.frame_count = number_of_frames(self.ds)
        self._frames: dict[int, np.ndarray] = {}

    def frame(self, index: int) -> np.ndarray:
        index = min(max(index, 0), self.frame_count - 1)
        if index not in self._frames:
            if len(self._frames) >= self.CACHE_SIZE:
                self._frames.pop(next(iter(self._frames)))
            self._frames[index] = decode_frame(self.ds, index)
        return self._frames[index]

    def render(self, index: int, options: ConvertOptions) -> Image.Image:
        return render_frame(
            self.frame(index), self.ds, index, options, bit_depth=8, total_frames=self.frame_count, resize=False
        )

    def value_range(self, index: int = 0) -> tuple[float, float]:
        """Zakres wartości po transformacji modalności - do ustawienia suwaków okna."""
        frame = self.frame(index)
        if is_color(self.ds) or frame.ndim != 2:
            return 0.0, 255.0
        data = modality_values(frame, self.ds, index)
        finite = data[np.isfinite(data)]
        if finite.size == 0:
            return 0.0, 1.0
        return float(finite.min()), float(finite.max())


def render_preview(
    path: str | os.PathLike,
    windowing: str = WINDOW_DICOM,
    max_size: tuple[int, int] = (320, 320),
) -> tuple[Image.Image, dict[str, str]]:
    """Miniatura pierwszej klatki oraz podstawowe informacje o obrazie."""
    source = PreviewSource(path)
    image = source.render(0, ConvertOptions(windowing=windowing))
    image.thumbnail(max_size, Image.Resampling.LANCZOS)
    return image, dataset_details(source.ds)
