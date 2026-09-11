"""Raport z konwersji w formacie CSV (otwiera się poprawnie w polskim Excelu)."""

from __future__ import annotations

import csv
import os
from collections.abc import Iterable
from datetime import datetime
from pathlib import Path

from .converter import FileResult, natural_key
from .i18n import t


def _display_path(path: Path, base: Path) -> str:
    try:
        return str(path.relative_to(base))
    except ValueError:
        return str(path)


def write_report(results: Iterable[FileResult], output_dir: str | os.PathLike, started: datetime) -> Path:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    destination = output_dir / f"{t('report_prefix')}_{started:%Y%m%d_%H%M%S}.csv"
    with destination.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.writer(handle, delimiter=";")
        writer.writerow([t("report_source"), t("report_status"), t("report_outputs"), t("report_error")])
        for result in sorted(results, key=lambda result: natural_key(str(result.item.path))):
            writer.writerow(
                [
                    str(result.item.path),
                    t("report_ok") if result.ok else t("report_failed"),
                    " | ".join(_display_path(path, output_dir) for path in result.outputs),
                    result.error or "",
                ]
            )
    return destination
