"""Konwersja z wiersza poleceń: python -m dicom_exporter WEJŚCIE... -o FOLDER."""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

from . import __author__, __email__, __version__
from .converter import (
    CT_PRESETS,
    EXPORT_IMAGES,
    EXPORT_MODES,
    IMAGE_FORMATS,
    LAYOUT_FLAT,
    LAYOUT_SOURCE,
    LAYOUTS,
    RESIZE_FIT,
    RESIZE_NONE,
    RESIZE_SCALE,
    WINDOW_CUSTOM,
    WINDOW_DICOM,
    WINDOW_MODES,
    ConvertOptions,
    collect_inputs,
    convert_batch,
)
from .dicominfo import is_dicomdir, read_dicomdir
from .i18n import LANGUAGES, plural, set_language, t
from .naming import DEFAULT_FOLDER_TEMPLATE, DEFAULT_NAME_TEMPLATE
from .profiles import BUILTIN_PROFILES
from .report import write_report


def _ranged(low: int, high: int):
    def parse(value: str) -> int:
        number = int(value)
        if not low <= number <= high:
            raise argparse.ArgumentTypeError(t("cli_bad_range", low=low, high=high))
        return number

    return parse


def _size(value: str) -> tuple[int, int]:
    try:
        width, height = (int(part) for part in value.lower().split("x"))
    except ValueError:
        raise argparse.ArgumentTypeError(t("cli_bad_size")) from None
    if width < 1 or height < 1:
        raise argparse.ArgumentTypeError(t("cli_bad_size"))
    return width, height


def _mask(value: str) -> tuple[float, float, float, float]:
    try:
        x0, y0, x1, y1 = (float(part) for part in value.split(","))
    except ValueError:
        raise argparse.ArgumentTypeError(t("cli_bad_mask")) from None
    if not (0 <= x0 < x1 <= 1 and 0 <= y0 < y1 <= 1):
        raise argparse.ArgumentTypeError(t("cli_bad_mask"))
    return x0, y0, x1, y1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="dicom_exporter", description=t("cli_description"))
    parser.add_argument(
        "--version", action="version", version=f"DICOM Exporter {__version__} – {__author__} <{__email__}>"
    )
    parser.add_argument("inputs", nargs="+", type=Path, help=t("cli_inputs"))
    parser.add_argument("-o", "--output", required=True, type=Path, help=t("cli_output"))
    parser.add_argument("--profile", choices=list(BUILTIN_PROFILES), help=t("cli_profile"))
    parser.add_argument("-f", "--format", type=str.upper, choices=list(IMAGE_FORMATS), default="PNG", help=t("cli_format"))
    parser.add_argument("--bit-depth", type=int, choices=(8, 16), default=8, help=t("cli_bit_depth"))
    parser.add_argument("-q", "--quality", type=_ranged(1, 100), default=95, help=t("cli_quality"))
    parser.add_argument("--window", choices=WINDOW_MODES, default=WINDOW_DICOM, help=t("cli_window"))
    parser.add_argument("--preset", choices=list(CT_PRESETS), help=t("cli_preset"))
    parser.add_argument("--center", type=float, default=40.0, help=t("cli_center"))
    parser.add_argument("--width", type=float, default=400.0, help=t("cli_width"))
    resize = parser.add_mutually_exclusive_group()
    resize.add_argument("--max-size", type=_size, help=t("cli_max_size"))
    resize.add_argument("--scale", type=_ranged(1, 400), help=t("cli_scale"))
    parser.add_argument("--name-template", default=DEFAULT_NAME_TEMPLATE, help=t("cli_name"))
    parser.add_argument("--layout", choices=LAYOUTS, default=LAYOUT_SOURCE, help=t("cli_layout"))
    parser.add_argument("--folder-template", default=DEFAULT_FOLDER_TEMPLATE, help=t("cli_folder_template"))
    parser.add_argument("--flat", action="store_const", dest="layout", const=LAYOUT_FLAT, help=argparse.SUPPRESS)
    parser.add_argument("--export", choices=EXPORT_MODES, default=EXPORT_IMAGES, help=t("cli_export"))
    parser.add_argument("--fps", type=_ranged(1, 60), default=10, help=t("cli_fps"))
    parser.add_argument("--mask", action="append", type=_mask, default=[], metavar="X0,Y0,X1,Y1", help=t("cli_mask"))
    parser.add_argument("--mask-top", type=_ranged(1, 100), metavar="PCT", help=t("cli_mask_top"))
    parser.add_argument("--mask-bottom", type=_ranged(1, 100), metavar="PCT", help=t("cli_mask_bottom"))
    parser.add_argument("--overlay-scale", action="store_true", help=t("cli_overlay_scale"))
    parser.add_argument("--overlay-info", action="store_true", help=t("cli_overlay_info"))
    parser.add_argument("--overlay-patient", action="store_true", help=t("cli_overlay_patient"))
    parser.add_argument("--anon-name", default="ANONIM", help=t("cli_anon_name"))
    parser.add_argument("--keep-dates", action="store_true", help=t("cli_keep_dates"))
    parser.add_argument("--first-frame", action="store_true", help=t("cli_first_frame"))
    parser.add_argument("--overwrite", action="store_true", help=t("cli_overwrite"))
    parser.add_argument("--report", action="store_true", help=t("cli_report"))
    parser.add_argument("-j", "--workers", type=int, default=None, help=t("cli_workers"))
    parser.add_argument("--lang", choices=list(LANGUAGES), default="pl", help=t("cli_lang"))
    return parser


def _expand_dicomdirs(paths: list[Path]) -> list[Path]:
    expanded: list[Path] = []
    for path in paths:
        if is_dicomdir(path):
            for patient in read_dicomdir(path):
                for study in patient.studies.values():
                    for series in study.series.values():
                        expanded.extend(series.files)
        else:
            expanded.append(path)
    return expanded


def _options(parser: argparse.ArgumentParser, args: argparse.Namespace) -> ConvertOptions:
    profile = BUILTIN_PROFILES[args.profile] if args.profile else {}

    def value(dest: str, key: str | None = None):
        """Wartość z profilu, chyba że opcję podano jawnie (różni się od domyślnej)."""
        current = getattr(args, dest)
        key = key or dest
        return profile[key] if key in profile and current == parser.get_default(dest) else current

    windowing, center, width = value("window", "windowing"), args.center, args.width
    if args.preset:
        windowing, (center, width) = WINDOW_CUSTOM, CT_PRESETS[args.preset]

    if args.max_size:
        resize_mode, (max_width, max_height), scale = RESIZE_FIT, args.max_size, 50
    elif args.scale:
        resize_mode, max_width, max_height, scale = RESIZE_SCALE, 1024, 1024, args.scale
    else:
        resize_mode = profile.get("resize_mode", RESIZE_NONE)
        max_width, max_height = profile.get("max_width", 1024), profile.get("max_height", 1024)
        scale = profile.get("scale_percent", 50)

    masks = list(args.mask)
    if args.mask_top:
        masks.append((0.0, 0.0, 1.0, args.mask_top / 100))
    if args.mask_bottom:
        masks.append((0.0, 1.0 - args.mask_bottom / 100, 1.0, 1.0))

    return ConvertOptions(
        fmt=value("format"),
        bit_depth=value("bit_depth"),
        quality=value("quality"),
        windowing=windowing,
        window_center=center,
        window_width=width,
        resize_mode=resize_mode,
        max_width=max_width,
        max_height=max_height,
        scale_percent=scale,
        name_template=args.name_template,
        layout=args.layout,
        folder_template=args.folder_template,
        export_mode=value("export", "export_mode"),
        fps=value("fps"),
        all_frames=False if args.first_frame else profile.get("all_frames", True),
        overwrite=args.overwrite,
        masks=tuple(masks),
        overlay_scale=args.overlay_scale or profile.get("overlay_scale", False),
        overlay_info=args.overlay_info or profile.get("overlay_info", False),
        overlay_patient=args.overlay_patient or profile.get("overlay_patient", False),
        anonymize_name=args.anon_name,
        anonymize_keep_dates=args.keep_dates or profile.get("anonymize_keep_dates", False),
    )


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):  # przekierowane wyjście zawsze w UTF-8 (polskie znaki w plikach i potokach)
        if stream is not None and hasattr(stream, "reconfigure") and not stream.isatty():
            stream.reconfigure(encoding="utf-8", errors="replace")
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--lang" in argv[:-1]:  # język musi być znany przed zbudowaniem opisów opcji
        set_language(argv[argv.index("--lang") + 1])
    parser = build_parser()
    args = parser.parse_args(argv)
    set_language(args.lang)

    try:
        options = _options(parser, args)
        inputs = _expand_dicomdirs(args.inputs)
    except Exception as exc:
        print(exc, file=sys.stderr)
        return 1

    skipped: list[Path] = []
    items = list(collect_inputs(inputs, skipped=skipped))
    for path in skipped:
        print(t("cli_skipped", path=path), file=sys.stderr)
    if not items:
        print(t("cli_no_files"), file=sys.stderr)
        return 1

    started = datetime.now()
    total = len(items)
    results = []
    outputs: set[Path] = set()
    for done, result in enumerate(convert_batch(items, args.output, options, workers=args.workers), start=1):
        results.append(result)
        outputs.update(result.outputs)
        if result.ok:
            print(t("cli_ok_line", done=done, total=total, path=result.item.path, images=plural(len(result.outputs), "image")))
        else:
            print(t("cli_error_line", done=done, total=total, path=result.item.path, error=result.error), file=sys.stderr)

    failed = sum(not result.ok for result in results)
    summary = t("summary", files=plural(total - failed, "file"), images=plural(len(outputs), "image"))
    if failed:
        summary += t("summary_errors", count=failed)
    print(summary)
    if args.report:
        print(t("cli_report_saved", path=write_report(results, args.output, started)))
    return 0 if failed == 0 else 2


if __name__ == "__main__":
    sys.exit(main())
