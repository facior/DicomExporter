"""Główne okno aplikacji DICOM Exporter."""

from __future__ import annotations

import importlib.util
import json
import os
import queue
import sys
import threading
import tkinter as tk
import webbrowser
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk
from tkinter import font as tkfont

from PIL import ImageTk

from . import COPYRIGHT_YEAR, GITHUB_URL, __author__, __email__, __version__, naming
from .converter import (
    CT_PRESETS,
    DICOM_EXTENSIONS,
    EXPORT_DICOM,
    EXPORT_GIF,
    EXPORT_IMAGES,
    EXPORT_MODES,
    EXPORT_MONTAGE,
    EXPORT_MP4,
    HIGH_BIT_DEPTH_FORMATS,
    IMAGE_FORMATS,
    LAYOUT_FLAT,
    LAYOUT_SOURCE,
    LAYOUT_TEMPLATE,
    LAYOUTS,
    OVERLAY_EXPORT_MODES,
    QUALITY_FORMATS,
    RESIZE_FIT,
    RESIZE_MODES,
    RESIZE_NONE,
    RESIZE_SCALE,
    WINDOW_CUSTOM,
    WINDOW_DICOM,
    WINDOW_MINMAX,
    WINDOW_MODES,
    ConvertOptions,
    FileResult,
    InputFile,
    collect_inputs,
    convert_batch,
    natural_key,
    output_stem,
)
from .dialogs import AboutDialog, DicomdirDialog, SummaryDialog, UpdateDialog
from .dicominfo import FileInfo, find_dicomdir, format_size, is_dicomdir, read_dicomdir, read_file_info
from .i18n import LANGUAGES, get_language, plural, set_language, t
from .preview import PreviewWorker, ZoomCanvas
from .profiles import BUILTIN_PROFILES, builtin_label
from .updates import (
    AFTER_UPDATE_FLAG,
    Release,
    UpdateError,
    check_for_update,
    is_newer,
    latest_release,
    remove_leftover,
)
from .widgets import (
    APP_TITLE,
    DND_FILES,
    PALETTES,
    PREVIEW_BG,
    PREVIEW_ERROR,
    Choice,
    IconFactory,
    ScrollableFrame,
    Tooltip,
    create_root,
    ellipsize,
    enable_high_dpi,
    link_label,
    reset_label_colors,
    rounded_rect,
    set_enabled,
    set_title_bar_theme,
    setup_fonts,
    style_name,
    sv_ttk,
    system_prefers_dark,
    work_area,
)
from .winshell import TaskbarProgress, TrayNotifier, flash_taskbar, open_path, reveal_in_explorer

SETTINGS_FILE = Path(os.environ.get("APPDATA") or Path.home()) / "DicomExporter" / "settings.json"
ICON_FILE = Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "DicomExporter" / "app.ico"
DEFAULT_OUTPUT = Path.home() / "Pictures" / "DICOM eksport"
DICOM_PATTERNS = " ".join(f"*{extension}" for extension in sorted(DICOM_EXTENSIONS))
SCAN_BATCH = 100

STATUS_PENDING = "pending"
STATUS_QUEUED = "queued"
STATUS_OK = "ok"
STATUS_ERROR = "error"
STATUS_CANCELLED = "cancelled"
STATUS_ORDER = {STATUS_ERROR: 0, STATUS_CANCELLED: 1, STATUS_PENDING: 2, STATUS_QUEUED: 3, STATUS_OK: 4}

# (klucz, etykieta, szerokość, wyrównanie, rozciąganie)
COLUMNS = (
    ("name", "col_name", 200, "w", False),
    ("status", "col_status", 230, "w", False),
    ("modality", "col_modality", 84, "center", False),
    ("series", "col_series", 56, "center", False),
    ("frames", "col_frames", 60, "center", False),
    ("dims", "col_dims", 92, "center", False),
    ("size", "col_size", 78, "e", False),
    ("location", "col_location", 320, "w", True),
)

PRESET_ORDER = ("brain", "soft_tissue", "lung", "bone", "mediastinum", "liver")
FORMAT_LABELS = {"PNG": "PNG", "JPG": "JPG", "JPEG": "JPEG", "TIFF": "TIFF", "WEBP": "WebP", "BMP": "BMP"}
BAND_HEIGHT = 0.1  # wysokość gotowych pasków maskowania (10% obrazu)


@dataclass
class Row:
    item: InputFile
    info: FileInfo
    status: str = STATUS_PENDING
    error: str = ""
    outputs: list[Path] = field(default_factory=list)

    @property
    def key(self) -> str:
        return _path_key(self.item.path)


def _path_key(path: Path) -> str:
    return os.path.normcase(os.path.abspath(path))


SORT_KEYS = {
    "name": lambda row: natural_key(row.item.path.name),
    "modality": lambda row: row.info.modality.lower(),
    "series": lambda row: (row.info.series_number is None, row.info.series_number or 0),
    "frames": lambda row: row.info.frames or 0,
    "dims": lambda row: (row.info.columns or 0) * (row.info.rows or 0),
    "size": lambda row: row.info.file_size,
    "status": lambda row: STATUS_ORDER[row.status],
    "location": lambda row: natural_key(str(row.item.path.parent)),
}


def load_settings() -> dict:
    try:
        data = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _number(variable: tk.Variable, default):
    try:
        return variable.get()
    except (tk.TclError, ValueError):
        return default


def _valid_mask(mask) -> tuple[float, float, float, float] | None:
    try:
        values = tuple(float(value) for value in mask)
    except (TypeError, ValueError):
        return None
    if len(values) == 4 and 0 <= values[0] < values[2] <= 1 and 0 <= values[1] < values[3] <= 1:
        return values
    return None


class App:
    def __init__(self, root: tk.Tk, dnd_enabled: bool) -> None:
        self.root = root
        self.dnd_enabled = dnd_enabled
        self.scale = max(1.0, root.winfo_fpixels("1i") / 96.0)
        self.events: queue.Queue[tuple] = queue.Queue()
        self.rows: dict[str, Row] = {}
        self.iid_by_key: dict[str, str] = {}
        self.next_row_id = 0
        self.cancel_event = threading.Event()
        self.converting = False
        self.scan_counts: dict[int, int] = {}
        self.next_scan_id = 0
        self.stats = {"total": 0, "ok": 0, "error": 0}
        self.output_paths: set[Path] = set()
        self.results: list[FileResult] = []
        self.started_at = datetime.now()
        self.used_output_dir: Path | None = None
        self.sort_column: str | None = None
        self.sort_reverse = False
        self.icon_widgets: dict[tk.Widget, tuple[str, str, int, int, str | None]] = {}
        self.setting_widgets: list[tk.Widget] = []
        self.export_sections: dict[str, ttk.Frame] = {}
        self.about_dialog: AboutDialog | None = None
        self.update_dialog: UpdateDialog | None = None
        self.update_prompted = ""
        self.drop_hover = False
        self.masks: list[tuple[float, float, float, float]] = []
        self.user_profiles: dict[str, dict] = {}
        self.playing = False
        self.play_after: str | None = None
        self._ui_ready = False
        self._syncing = False
        self._navigating = False
        self._keep_view = False
        self._applying_profile = False
        self._window_drag_origin: tuple[float, float, float] | None = None
        self.available_release: Release | None = None

        self.preview_worker = PreviewWorker(self.events.put)
        self.preview_worker.start()
        self.preview_token = 0
        self.preview_path: Path | None = None
        self.preview_image_path: Path | None = None
        self.preview_frame = 0
        self.preview_frames = 1
        self.preview_ds = None
        self.preview_tags: list = []
        self.preview_window: tuple[float, float] | None = None
        self.preview_range: tuple[float, float] | None = None
        self.preview_after: str | None = None
        self.tags_after: str | None = None

        settings = load_settings()
        set_language(settings.get("language", "pl"))
        self._init_variables(settings)
        self.palette = PALETTES["dark" if self.dark_var.get() else "light"]
        if sv_ttk is not None:
            sv_ttk.set_theme("dark" if self.dark_var.get() else "light", root)
        self.fonts = setup_fonts(root, self.scale)
        self.icons = IconFactory(root, self.scale)
        self._set_app_icon()
        self.taskbar = TaskbarProgress(root)
        self.notifier = TrayNotifier(root, self.icons.write_ico(ICON_FILE))
        self._configure_root()
        self._build_ui()
        self._bind_root_events()
        self._bind_widget_events()
        self._ui_ready = True
        self._apply_theme(refresh_title_bar=False)
        self.root.after(50, self._process_events)
        self.root.after(150, lambda: set_title_bar_theme(self.root, self.dark_var.get(), refresh=True))
        if self.check_updates_var.get():
            threading.Thread(target=self._check_updates_worker, daemon=True).start()

    # ------------------------------------------------------------------ zmienne i ustawienia

    def px(self, value: float) -> int:
        return round(value * self.scale)

    def _init_variables(self, settings: dict) -> None:
        def choice(key, default, allowed):
            value = settings.get(key, default)
            return value if value in allowed else default

        def number(key, default, low, high, kind=int):
            try:
                return min(high, max(low, kind(settings.get(key, default))))
            except (TypeError, ValueError):
                return default

        self.masks = [mask for mask in map(_valid_mask, settings.get("masks") or []) if mask]
        profiles = settings.get("user_profiles")
        if isinstance(profiles, dict):
            self.user_profiles = {str(name): dict(values) for name, values in profiles.items() if isinstance(values, dict)}

        layout_default = LAYOUT_SOURCE if settings.get("keep_structure", True) else LAYOUT_FLAT
        self.format_var = tk.StringVar(value=choice("format", "PNG", IMAGE_FORMATS))
        self.bit_depth_var = tk.IntVar(value=choice("bit_depth", 8, (8, 16)))
        self.quality_var = tk.DoubleVar(value=number("quality", 95, 1, 100))
        self.window_mode_var = tk.StringVar(value=choice("windowing", WINDOW_DICOM, WINDOW_MODES))
        self.center_var = tk.IntVar(value=number("window_center", 40, -100000, 100000))
        self.width_var = tk.IntVar(value=number("window_width", 400, 1, 200000))
        self.resize_mode_var = tk.StringVar(value=choice("resize_mode", RESIZE_NONE, RESIZE_MODES))
        self.max_width_var = tk.IntVar(value=number("max_width", 1024, 1, 100000))
        self.max_height_var = tk.IntVar(value=number("max_height", 1024, 1, 100000))
        self.scale_var = tk.IntVar(value=number("scale_percent", 50, 1, 400))
        self.name_template_var = tk.StringVar(value=str(settings.get("name_template") or naming.DEFAULT_NAME_TEMPLATE))
        self.layout_var = tk.StringVar(value=choice("layout", layout_default, LAYOUTS))
        self.folder_template_var = tk.StringVar(
            value=str(settings.get("folder_template") or naming.DEFAULT_FOLDER_TEMPLATE)
        )
        self.export_mode_var = tk.StringVar(value=choice("export_mode", EXPORT_IMAGES, EXPORT_MODES))
        self.fps_var = tk.IntVar(value=number("fps", 10, 1, 60))
        self.all_frames_var = tk.BooleanVar(value=bool(settings.get("all_frames", True)))
        self.overwrite_var = tk.BooleanVar(value=bool(settings.get("overwrite", False)))
        self.overlay_scale_var = tk.BooleanVar(value=bool(settings.get("overlay_scale", False)))
        self.overlay_info_var = tk.BooleanVar(value=bool(settings.get("overlay_info", False)))
        self.overlay_patient_var = tk.BooleanVar(value=bool(settings.get("overlay_patient", False)))
        self.anonymize_name_var = tk.StringVar(value=str(settings.get("anonymize_name") or "ANONIM"))
        self.keep_dates_var = tk.BooleanVar(value=bool(settings.get("anonymize_keep_dates", False)))
        self.check_updates_var = tk.BooleanVar(value=bool(settings.get("check_updates", True)))
        self.update_prompted = str(settings.get("update_prompted") or "")
        self.output_var = tk.StringVar(value=settings.get("output_dir") or str(DEFAULT_OUTPUT))
        theme = settings.get("theme")
        self.dark_var = tk.BooleanVar(value=theme == "dark" if theme in ("dark", "light") else system_prefers_dark())
        self.language_var = tk.StringVar(value=get_language())
        profile = str(settings.get("profile") or "")
        known = profile.removeprefix("builtin:") in BUILTIN_PROFILES or profile.removeprefix("user:") in self.user_profiles
        self.profile_var = tk.StringVar(value=profile if known else "")
        self.draw_mask_var = tk.BooleanVar(value=False)
        self.mask_count_var = tk.StringVar()
        self.count_var = tk.StringVar()
        self.status_var = tk.StringVar(value=t("status_ready"))
        self.zoom_var = tk.StringVar(value="—")
        self.frame_label_var = tk.StringVar()
        self.tag_search_var = tk.StringVar()
        self.example_var = tk.StringVar()

        for variable in (
            self.format_var,
            self.bit_depth_var,
            self.export_mode_var,
            self.resize_mode_var,
            self.layout_var,
            self.name_template_var,
            self.folder_template_var,
            self.all_frames_var,
        ):
            variable.trace_add("write", lambda *_: self._on_settings_changed())
        for variable in (self.overlay_scale_var, self.overlay_info_var, self.overlay_patient_var, self.export_mode_var):
            variable.trace_add("write", lambda *_: self._schedule_preview(60))
        for variable in self._profile_variables().values():
            variable.trace_add("write", lambda *_: self._on_profile_value_changed())
        self.quality_var.trace_add("write", lambda *_: self._on_quality_change())
        self.center_var.trace_add("write", lambda *_: self._on_window_values_changed())
        self.width_var.trace_add("write", lambda *_: self._on_window_values_changed())
        self.window_mode_var.trace_add("write", lambda *_: self._on_window_mode_changed())
        self.tag_search_var.trace_add("write", lambda *_: self._schedule_tags())

    def _profile_variables(self) -> dict[str, tk.Variable]:
        return {
            "format": self.format_var,
            "bit_depth": self.bit_depth_var,
            "quality": self.quality_var,
            "windowing": self.window_mode_var,
            "resize_mode": self.resize_mode_var,
            "max_width": self.max_width_var,
            "max_height": self.max_height_var,
            "scale_percent": self.scale_var,
            "export_mode": self.export_mode_var,
            "fps": self.fps_var,
            "all_frames": self.all_frames_var,
            "overlay_scale": self.overlay_scale_var,
            "overlay_info": self.overlay_info_var,
            "overlay_patient": self.overlay_patient_var,
            "anonymize_keep_dates": self.keep_dates_var,
        }

    def _save_settings(self) -> None:
        settings = {
            "language": get_language(),
            "theme": "dark" if self.dark_var.get() else "light",
            "format": self.format_var.get(),
            "bit_depth": _number(self.bit_depth_var, 8),
            "quality": self._quality(),
            "windowing": self.window_mode_var.get(),
            "window_center": _number(self.center_var, 40),
            "window_width": _number(self.width_var, 400),
            "resize_mode": self.resize_mode_var.get(),
            "max_width": _number(self.max_width_var, 1024),
            "max_height": _number(self.max_height_var, 1024),
            "scale_percent": _number(self.scale_var, 50),
            "name_template": self.name_template_var.get(),
            "layout": self.layout_var.get(),
            "folder_template": self.folder_template_var.get(),
            "export_mode": self.export_mode_var.get(),
            "fps": _number(self.fps_var, 10),
            "all_frames": self.all_frames_var.get(),
            "overwrite": self.overwrite_var.get(),
            "overlay_scale": self.overlay_scale_var.get(),
            "overlay_info": self.overlay_info_var.get(),
            "overlay_patient": self.overlay_patient_var.get(),
            "anonymize_name": self.anonymize_name_var.get(),
            "anonymize_keep_dates": self.keep_dates_var.get(),
            "check_updates": self.check_updates_var.get(),
            "update_prompted": self.update_prompted,
            "masks": [list(mask) for mask in self.masks],
            "profile": self.profile_var.get(),
            "user_profiles": self.user_profiles,
            "output_dir": self.output_var.get().strip(),
        }
        try:
            SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
            SETTINGS_FILE.write_text(json.dumps(settings, indent=2, ensure_ascii=False), encoding="utf-8")
        except OSError:
            pass

    # ------------------------------------------------------------------ budowa interfejsu

    def _configure_root(self) -> None:
        root = self.root
        root.title(APP_TITLE)
        # Okno mieści się w obszarze roboczym (bez paska zadań) i startuje wyśrodkowane;
        # wysokość nie obejmuje paska tytułu, dlatego zostawiamy na niego zapas.
        left, top, right, bottom = work_area(root)
        width = min(self.px(1360), right - left - self.px(16))
        height = min(self.px(900), bottom - top - self.px(48))
        x = left + (right - left - width) // 2
        y = top + max(0, (bottom - top - height - self.px(32)) // 2)
        root.geometry(f"{width}x{height}+{x}+{y}")
        root.minsize(min(self.px(1120), width), min(self.px(700), height))
        # Kółko myszy nad listą rozwijaną nie zmienia wartości - przewija panel ustawień.
        for widget_class in ("TCombobox", "TSpinbox"):
            root.bind_class(widget_class, "<MouseWheel>", "")

    def _set_app_icon(self) -> None:
        self.badge_photo = ImageTk.PhotoImage(self.icons.badge(self.px(40)), master=self.root)
        self.window_icons = [ImageTk.PhotoImage(self.icons.badge(size), master=self.root) for size in (64, 48, 32, 16)]
        self.root.iconphoto(True, *self.window_icons)

    def _icon_button(self, parent, text: str, icon: str, command, style: str = "TButton", color: str = "fg") -> ttk.Button:
        button = ttk.Button(parent, text=text, command=command, style=style_name(style), compound="left")
        self.icon_widgets[button] = (icon, color, 6, 16, None)
        return button

    def _tool_button(self, parent, icon: str, command, tooltip: str, fallback: str) -> ttk.Button:
        button = ttk.Button(parent, command=command, style="Toolbutton")
        self.icon_widgets[button] = (icon, "fg", 0, 16, fallback)
        Tooltip(button, tooltip)
        return button

    def _build_ui(self) -> None:
        px = self.px
        self.icon_widgets.clear()
        self.setting_widgets = []
        self.export_sections = {}
        self.container = container = ttk.Frame(self.root, padding=(px(20), px(14), px(20), px(10)))
        container.pack(fill="both", expand=True)
        # Stały podział szerokości 3:2 - panel boczny nie zabiera miejsca liście plików.
        container.columnconfigure(0, weight=3, uniform="main")
        container.columnconfigure(1, weight=2, uniform="main")
        container.rowconfigure(1, weight=1)

        self._build_header(container)
        left = ttk.Frame(container)
        left.grid(row=1, column=0, sticky="nsew")
        left.columnconfigure(0, weight=1)
        left.rowconfigure(0, weight=1)
        self._build_files_card(left)
        self._build_action_card(left)
        self._build_side_tabs(container)
        self._build_footer(container)

    def _build_header(self, parent) -> None:
        px = self.px
        header = ttk.Frame(parent)
        header.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, px(12)))
        ttk.Label(header, image=self.badge_photo).pack(side="left")
        titles = ttk.Frame(header)
        titles.pack(side="left", padx=(px(12), 0))
        ttk.Label(titles, text=APP_TITLE, style="Title.TLabel").pack(anchor="w")
        ttk.Label(titles, text=t("app_subtitle"), style="Caption.TLabel").pack(anchor="w")

        if sv_ttk is not None:
            ttk.Checkbutton(
                header, text=t("theme_dark"), style="Switch.TCheckbutton", variable=self.dark_var, command=self._toggle_theme
            ).pack(side="right")
        self.about_btn = self._icon_button(header, t("btn_about"), "info", self.show_about, style="Toolbutton")
        self.about_btn.pack(side="right", padx=(0, px(20)))

        language = ttk.Frame(header)
        language.pack(side="right", padx=(0, px(16)))
        language_icon = ttk.Label(language)
        language_icon.pack(side="left", padx=(0, px(6)))
        self.icon_widgets[language_icon] = ("language", "muted", 0, 16, None)
        self.language_choice = Choice(
            language, self.language_var, list(LANGUAGES.items()), command=self._change_language, width=9
        )
        self.language_choice.widget.pack(side="left")
        Tooltip(self.language_choice.widget, t("language"))

    def _build_files_card(self, parent) -> None:
        px = self.px
        card = ttk.Frame(parent, style=style_name("Card.TFrame"), padding=px(16))
        card.grid(row=0, column=0, sticky="nsew")
        card.columnconfigure(0, weight=1)
        card.rowconfigure(2, weight=1)

        title_row = ttk.Frame(card)
        title_row.grid(row=0, column=0, sticky="ew")
        ttk.Label(title_row, text=t("files_title"), style="Section.TLabel").pack(side="left")
        ttk.Label(title_row, textvariable=self.count_var, style="Caption.TLabel").pack(side="right")

        toolbar = ttk.Frame(card)
        toolbar.grid(row=1, column=0, sticky="ew", pady=(px(10), px(12)))
        self.add_files_btn = self._icon_button(toolbar, t("btn_add_files"), "add_file", self.add_files)
        self.add_folder_btn = self._icon_button(toolbar, t("btn_add_folder"), "add_folder", self.add_folder)
        self.disc_btn = self._icon_button(toolbar, t("btn_open_disc"), "disc", self.open_disc)
        self.remove_btn = self._icon_button(toolbar, t("btn_remove"), "remove", self.remove_selected)
        self.clear_btn = self._icon_button(toolbar, t("btn_clear"), "clear", self.clear_list)
        for button in (self.add_files_btn, self.add_folder_btn, self.disc_btn, self.remove_btn, self.clear_btn):
            button.pack(side="left", padx=(0, px(8)))

        list_area = ttk.Frame(card)
        list_area.grid(row=2, column=0, sticky="nsew")
        list_area.columnconfigure(0, weight=1)
        list_area.rowconfigure(0, weight=1)
        self.tree = ttk.Treeview(list_area, columns=[column[0] for column in COLUMNS], show="headings", selectmode="extended")
        for key, _label, width, anchor, stretch in COLUMNS:
            self.tree.heading(key, anchor=anchor, command=lambda column=key: self._sort_by(column))
            self.tree.column(key, width=px(width), minwidth=px(48), anchor=anchor, stretch=stretch)
        vertical = ttk.Scrollbar(list_area, orient="vertical", command=self.tree.yview)
        horizontal = ttk.Scrollbar(list_area, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        vertical.grid(row=0, column=1, sticky="ns", padx=(px(4), 0))
        horizontal.grid(row=1, column=0, sticky="ew", pady=(px(4), 0))
        self._update_sort_headings()
        self.drop_zone = tk.Canvas(list_area, highlightthickness=0, borderwidth=0, cursor="hand2")

        self.row_menu = tk.Menu(self.root, tearoff=0)
        self.row_menu.add_command(label=t("menu_convert_selected"), command=lambda: self.start_conversion(True))
        self.row_menu.add_command(label=t("menu_show_result"), command=self.show_result)
        self.row_menu.add_command(label=t("menu_open_location"), command=self.open_source_location)
        self.row_menu.add_separator()
        self.row_menu.add_command(label=t("menu_remove"), command=self.remove_selected)

    def _build_action_card(self, parent) -> None:
        px = self.px
        card = ttk.Frame(parent, style=style_name("Card.TFrame"), padding=px(16))
        card.grid(row=1, column=0, sticky="ew", pady=(px(12), 0))
        card.columnconfigure(1, weight=1)
        ttk.Label(card, text=t("output_folder"), style="Section.TLabel").grid(row=0, column=0, sticky="w", padx=(0, px(12)))
        self.output_entry = ttk.Entry(card, textvariable=self.output_var)
        self.output_entry.grid(row=0, column=1, sticky="ew")
        self.choose_output_btn = self._icon_button(card, t("btn_choose"), "folder", self.choose_output)
        self.choose_output_btn.grid(row=0, column=2, padx=(px(8), 0))
        self.open_output_btn = self._icon_button(card, t("btn_open"), "open", self.open_output)
        self.open_output_btn.grid(row=0, column=3, padx=(px(8), 0))
        self.setting_widgets.extend((self.output_entry, self.choose_output_btn))

        ttk.Separator(card).grid(row=1, column=0, columnspan=4, sticky="ew", pady=px(14))
        progress_box = ttk.Frame(card)
        progress_box.grid(row=2, column=0, columnspan=2, sticky="ew")
        self.progress = ttk.Progressbar(progress_box, mode="determinate")
        self.progress.pack(fill="x", pady=(px(2), 0))
        status_row = ttk.Frame(progress_box)
        status_row.pack(fill="x", pady=(px(6), 0))
        ttk.Label(status_row, textvariable=self.status_var, style="Caption.TLabel").pack(side="left")
        self.cancel_btn = self._icon_button(card, t("btn_cancel"), "cancel", self.cancel)
        self.cancel_btn.grid(row=2, column=2, padx=(px(16), 0))
        self.convert_btn = self._icon_button(
            card, t("btn_convert"), "convert", self.start_conversion, style="Accent.TButton", color="on_accent"
        )
        self.convert_btn.grid(row=2, column=3, padx=(px(8), 0), ipadx=px(10))

    def _build_side_tabs(self, parent) -> None:
        px = self.px
        self.side_tabs = ttk.Notebook(parent)
        self.side_tabs.grid(row=1, column=1, sticky="nsew", padx=(px(12), 0))
        self.side_tabs.enable_traversal()

        preview_tab = ttk.Frame(self.side_tabs, padding=px(14))
        self._build_preview_tab(preview_tab)
        self.side_tabs.add(preview_tab, text=t("tab_preview"))

        tags_tab = ttk.Frame(self.side_tabs, padding=px(14))
        self._build_tags_tab(tags_tab)
        self.side_tabs.add(tags_tab, text=t("tab_tags"))

        self.export_scroll = ScrollableFrame(self.side_tabs, padding=(px(14), px(14), px(18), px(14)))
        self._build_export_tab(self.export_scroll.inner)
        self.side_tabs.add(self.export_scroll, text=t("tab_export"))

    def _build_preview_tab(self, tab) -> None:
        px = self.px
        tab.columnconfigure(0, weight=1)
        tab.rowconfigure(0, weight=1)
        self.zoom = ZoomCanvas(tab, self.icons, self._on_zoom_changed)
        self.zoom.on_window_drag = self._on_window_drag
        self.zoom.on_mask_drawn = self._add_mask
        self.zoom.masks = tuple(self.masks)
        self.zoom.canvas.grid(row=0, column=0, sticky="nsew")
        self.zoom.show_message(t("preview_select"))

        tools = ttk.Frame(tab)
        tools.grid(row=1, column=0, sticky="ew", pady=(px(8), 0))
        self.zoom_out_btn = self._tool_button(tools, "zoom_out", lambda: self.zoom.zoom_by(1 / 1.25), t("tip_zoom_out"), "−")
        self.zoom_out_btn.pack(side="left")
        ttk.Label(tools, textvariable=self.zoom_var, width=6, anchor="center", style="Caption.TLabel").pack(side="left")
        self.zoom_in_btn = self._tool_button(tools, "zoom_in", lambda: self.zoom.zoom_by(1.25), t("tip_zoom_in"), "+")
        self.zoom_in_btn.pack(side="left")
        self.fit_btn = self._tool_button(tools, "fit", self.zoom.fit_view, t("tip_fit"), "⤢")
        self.fit_btn.pack(side="left", padx=(px(4), 0))
        self.next_frame_btn = self._tool_button(tools, "next", lambda: self._step_frame(1), t("tip_next_frame"), "▶")
        self.next_frame_btn.pack(side="right")
        self.play_btn = self._tool_button(tools, "play", self.toggle_playback, t("tip_play"), "⏵")
        self.play_btn.pack(side="right")
        self.prev_frame_btn = self._tool_button(tools, "previous", lambda: self._step_frame(-1), t("tip_prev_frame"), "◀")
        self.prev_frame_btn.pack(side="right")
        ttk.Label(tools, textvariable=self.frame_label_var, style="Caption.TLabel").pack(side="right", padx=px(6))
        self.frame_scale = ttk.Scale(tab, from_=0, to=1, command=self._on_frame_scale)
        self.frame_scale.grid(row=2, column=0, sticky="ew", pady=(px(4), 0))

        self.preview_name = ttk.Label(tab, text=" ", style="Value.TLabel")
        self.preview_name.grid(row=3, column=0, sticky="w", pady=(px(8), 0))
        self.preview_meta = ttk.Label(tab, text=" \n ", style="Caption.TLabel", justify="left")
        self.preview_meta.grid(row=4, column=0, sticky="w")
        ttk.Separator(tab).grid(row=5, column=0, sticky="ew", pady=px(10))

        contrast = ttk.Frame(tab)
        contrast.grid(row=6, column=0, sticky="ew")
        contrast.columnconfigure(1, weight=1)
        head = ttk.Frame(contrast)
        head.grid(row=0, column=0, columnspan=3, sticky="ew", pady=(0, px(6)))
        contrast_title = ttk.Label(head, text=t("contrast_title"), style="Section.TLabel")
        contrast_title.pack(side="left")
        Tooltip(contrast_title, t("window_hint"))
        self.window_file_btn = self._icon_button(
            head, t("btn_window_from_file"), "reset", self._window_from_file, style="Toolbutton"
        )
        self.window_file_btn.pack(side="right")
        Tooltip(self.window_file_btn, t("tip_window_from_file"))
        self.window_choice = Choice(
            contrast,
            self.window_mode_var,
            [(WINDOW_DICOM, t("window_dicom")), (WINDOW_MINMAX, t("window_minmax")), (WINDOW_CUSTOM, t("window_custom"))],
            command=self._on_window_mode_selected,
        )
        self.window_choice.widget.grid(row=1, column=0, columnspan=3, sticky="ew")

        presets = ttk.Frame(contrast)
        presets.grid(row=2, column=0, columnspan=3, sticky="ew", pady=(px(8), px(2)))
        for index, key in enumerate(PRESET_ORDER):
            presets.columnconfigure(index % 3, weight=1, uniform="preset")
            button = ttk.Button(presets, text=t(f"preset_{key}"), command=lambda preset=key: self._apply_preset(preset))
            button.grid(
                row=index // 3, column=index % 3, sticky="ew", padx=(0 if index % 3 == 0 else px(6), 0), pady=(0, px(6))
            )
            center, width = CT_PRESETS[key]
            Tooltip(button, f"C {center:g} / W {width:g}")

        self.center_scale = ttk.Scale(
            contrast, from_=-1024, to=3071, command=lambda value: self._on_window_scale(self.center_var, value)
        )
        self.width_scale = ttk.Scale(
            contrast, from_=1, to=4096, command=lambda value: self._on_window_scale(self.width_var, value)
        )
        for row, (label, scale, variable) in enumerate(
            ((t("window_center"), self.center_scale, self.center_var), (t("window_width"), self.width_scale, self.width_var)),
            start=3,
        ):
            caption = ttk.Label(contrast, text=label, style="Caption.TLabel")
            caption.grid(row=row, column=0, sticky="w", padx=(0, px(10)))
            Tooltip(caption, t("window_hint"))
            scale.grid(row=row, column=1, sticky="ew", pady=px(2))
            spin = ttk.Spinbox(contrast, from_=-100000, to=200000, increment=10, textvariable=variable, width=7)
            spin.grid(row=row, column=2, sticky="e", padx=(px(10), 0))
        self._sync_window_scales()

        masks = ttk.Frame(tab)
        masks.grid(row=7, column=0, sticky="ew", pady=(px(10), 0))
        head = ttk.Frame(masks)
        head.grid(row=0, column=0, columnspan=4, sticky="ew", pady=(0, px(6)))
        masks_title = ttk.Label(head, text=t("masks_title"), style="Section.TLabel")
        masks_title.pack(side="left")
        Tooltip(masks_title, t("masks_hint"))
        ttk.Label(head, textvariable=self.mask_count_var, style="Caption.TLabel").pack(side="right")
        mask_buttons = (
            (ttk.Button(masks, text=t("btn_mask_top"), command=lambda: self._add_band(top=True)), t("tip_mask_top")),
            (ttk.Button(masks, text=t("btn_mask_bottom"), command=lambda: self._add_band(top=False)), t("tip_mask_bottom")),
            (
                ttk.Checkbutton(
                    masks,
                    text=t("btn_mask_draw"),
                    variable=self.draw_mask_var,
                    style=style_name("Toggle.TButton"),
                    command=self._on_draw_mode,
                ),
                t("tip_mask_draw"),
            ),
            (ttk.Button(masks, text=t("btn_mask_clear"), command=self._clear_masks), t("tip_mask_clear")),
        )
        for index, (button, tip) in enumerate(mask_buttons):
            masks.columnconfigure(index, weight=1, uniform="mask")
            button.grid(row=1, column=index, sticky="ew", padx=(0 if index == 0 else px(6), 0))
            Tooltip(button, tip)
        self.mask_clear_btn = mask_buttons[3][0]
        self._on_draw_mode()
        self._update_mask_count()

    def _build_tags_tab(self, tab) -> None:
        px = self.px
        tab.columnconfigure(0, weight=1)
        tab.rowconfigure(1, weight=1)
        search = ttk.Frame(tab)
        search.grid(row=0, column=0, sticky="ew", pady=(0, px(8)))
        search_icon = ttk.Label(search)
        search_icon.pack(side="left", padx=(0, px(8)))
        self.icon_widgets[search_icon] = ("search", "muted", 0, 16, None)
        self.tag_search_entry = ttk.Entry(search, textvariable=self.tag_search_var)
        self.tag_search_entry.pack(side="left", fill="x", expand=True)
        Tooltip(self.tag_search_entry, t("tags_search"))

        tree_frame = ttk.Frame(tab)
        tree_frame.grid(row=1, column=0, sticky="nsew")
        tree_frame.columnconfigure(0, weight=1)
        tree_frame.rowconfigure(0, weight=1)
        self.tags_tree = ttk.Treeview(tree_frame, columns=("name", "vr", "value"), show="tree headings", selectmode="browse")
        self.tags_tree.heading("#0", text=t("tag_col_tag"), anchor="w")
        self.tags_tree.heading("name", text=t("tag_col_name"), anchor="w")
        self.tags_tree.heading("vr", text="VR")
        self.tags_tree.heading("value", text=t("tag_col_value"), anchor="w")
        self.tags_tree.column("#0", width=px(118), stretch=False)
        self.tags_tree.column("name", width=px(170), stretch=False)
        self.tags_tree.column("vr", width=px(40), anchor="center", stretch=False)
        self.tags_tree.column("value", width=px(220), stretch=True)
        vertical = ttk.Scrollbar(tree_frame, orient="vertical", command=self.tags_tree.yview)
        horizontal = ttk.Scrollbar(tree_frame, orient="horizontal", command=self.tags_tree.xview)
        self.tags_tree.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
        self.tags_tree.grid(row=0, column=0, sticky="nsew")
        vertical.grid(row=0, column=1, sticky="ns", padx=(px(4), 0))
        horizontal.grid(row=1, column=0, sticky="ew", pady=(px(4), 0))
        self.tags_hint = ttk.Label(tab, text=t("tags_no_file"), style="Caption.TLabel")
        self.tags_hint.grid(row=2, column=0, sticky="w", pady=(px(8), 0))

    def _build_export_tab(self, tab) -> None:
        px = self.px
        tab.columnconfigure(0, weight=1)
        wrap = px(420)
        counter = iter(range(1000))

        def section(key: str, title: str) -> tuple[ttk.Frame, ttk.Label]:
            index = next(counter)
            frame = ttk.Frame(tab)
            frame.grid(row=index, column=0, sticky="ew", pady=(0 if index == 0 else px(16), 0))
            frame.columnconfigure(0, weight=1)
            label = ttk.Label(frame, text=title, style="Section.TLabel")
            label.grid(row=0, column=0, sticky="w", pady=(0, px(6)))
            self.export_sections[key] = frame
            return frame, label

        def switch(parent, row: int, text: str, variable: tk.BooleanVar) -> ttk.Checkbutton:
            widget = ttk.Checkbutton(parent, text=text, variable=variable, style=style_name("Switch.TCheckbutton"))
            widget.grid(row=row, column=0, columnspan=3, sticky="w", pady=(0, px(6)))
            self.setting_widgets.append(widget)
            return widget

        # Profil
        frame, _ = section("profile", t("profile"))
        self.profile_choice = Choice(frame, self.profile_var, self._profile_options(), command=self._apply_profile)
        self.profile_choice.widget.grid(row=1, column=0, sticky="ew")
        self.save_profile_btn = self._tool_button(frame, "save", self.save_profile, t("tip_save_profile"), "+")
        self.save_profile_btn.grid(row=1, column=1, padx=(px(6), 0))
        self.delete_profile_btn = self._tool_button(frame, "remove", self.delete_profile, t("tip_delete_profile"), "✕")
        self.delete_profile_btn.grid(row=1, column=2, padx=(px(2), 0))
        self.setting_widgets.extend((self.profile_choice.widget, self.save_profile_btn))

        # Tryb eksportu
        frame, _ = section("mode", t("export_mode"))
        self.export_choice = Choice(
            frame,
            self.export_mode_var,
            [
                (EXPORT_IMAGES, t("export_images")),
                (EXPORT_GIF, t("export_gif")),
                (EXPORT_MP4, t("export_mp4")),
                (EXPORT_MONTAGE, t("export_montage")),
                (EXPORT_DICOM, t("export_dicom")),
            ],
        )
        self.export_choice.widget.grid(row=1, column=0, sticky="ew")
        self.export_hint = ttk.Label(frame, style="Caption.TLabel", wraplength=wrap, justify="left")
        self.export_hint.grid(row=2, column=0, sticky="w", pady=(px(4), 0))
        self.fps_row = ttk.Frame(frame)
        self.fps_row.grid(row=3, column=0, sticky="w", pady=(px(8), 0))
        ttk.Label(self.fps_row, text=t("fps"), style="Caption.TLabel").pack(side="left", padx=(0, px(10)))
        self.fps_spin = ttk.Spinbox(self.fps_row, from_=1, to=60, textvariable=self.fps_var, width=5)
        self.fps_spin.pack(side="left")
        self.setting_widgets.append(self.export_choice.widget)

        # Format i głębia bitowa
        frame, _ = section("format", t("image_format"))
        formats = ttk.Frame(frame)
        formats.grid(row=1, column=0, sticky="ew")
        self.format_radios = []
        for index, fmt in enumerate(IMAGE_FORMATS):
            formats.columnconfigure(index % 3, weight=1, uniform="format")
            radio = ttk.Radiobutton(
                formats, text=FORMAT_LABELS[fmt], value=fmt, variable=self.format_var, style=style_name("Toggle.TButton")
            )
            radio.grid(row=index // 3, column=index % 3, sticky="ew", padx=(0 if index % 3 == 0 else px(6), 0), pady=(0, px(6)))
            self.format_radios.append(radio)

        frame, _ = section("depth", t("bit_depth"))
        depth = ttk.Frame(frame)
        depth.grid(row=1, column=0, sticky="ew")
        self.depth_radios = []
        for index, bits in enumerate((8, 16)):
            depth.columnconfigure(index, weight=1, uniform="depth")
            radio = ttk.Radiobutton(
                depth, text=f"{bits} bit", value=bits, variable=self.bit_depth_var, style=style_name("Toggle.TButton")
            )
            radio.grid(row=0, column=index, sticky="ew", padx=(0 if index == 0 else px(6), 0))
            self.depth_radios.append(radio)
        ttk.Label(frame, text=t("bit_depth_hint"), style="Caption.TLabel", wraplength=wrap, justify="left").grid(
            row=2, column=0, sticky="w", pady=(px(6), 0)
        )

        frame, self.quality_caption = section("quality", t("quality"))
        self.quality_value = ttk.Label(frame, style="Caption.TLabel")
        self.quality_value.grid(row=0, column=1, sticky="e")
        self.quality_scale = ttk.Scale(frame, from_=1, to=100, variable=self.quality_var)
        self.quality_scale.grid(row=1, column=0, columnspan=2, sticky="ew")
        self._on_quality_change()

        # Rozmiar
        frame, _ = section("resize", t("resize"))
        self.resize_choice = Choice(
            frame,
            self.resize_mode_var,
            [(RESIZE_NONE, t("resize_none")), (RESIZE_FIT, t("resize_fit")), (RESIZE_SCALE, t("resize_scale"))],
        )
        self.resize_choice.widget.grid(row=1, column=0, sticky="ew")
        self.setting_widgets.append(self.resize_choice.widget)
        self.size_row = ttk.Frame(frame)
        self.size_row.grid(row=2, column=0, sticky="w", pady=(px(8), 0))
        self.fit_frame = ttk.Frame(self.size_row)
        self.max_width_spin = ttk.Spinbox(
            self.fit_frame, from_=1, to=20000, increment=64, textvariable=self.max_width_var, width=6
        )
        self.max_width_spin.pack(side="left")
        ttk.Label(self.fit_frame, text="×", style="Caption.TLabel").pack(side="left", padx=px(6))
        self.max_height_spin = ttk.Spinbox(
            self.fit_frame, from_=1, to=20000, increment=64, textvariable=self.max_height_var, width=6
        )
        self.max_height_spin.pack(side="left")
        ttk.Label(self.fit_frame, text="px", style="Caption.TLabel").pack(side="left", padx=(px(6), 0))
        self.scale_frame = ttk.Frame(self.size_row)
        self.scale_spin = ttk.Spinbox(self.scale_frame, from_=1, to=400, increment=5, textvariable=self.scale_var, width=5)
        self.scale_spin.pack(side="left")
        ttk.Label(self.scale_frame, text="%", style="Caption.TLabel").pack(side="left", padx=(px(6), 0))

        # Nakładki
        frame, _ = section("overlays", t("overlays"))
        switch(frame, 1, t("switch_overlay_scale"), self.overlay_scale_var)
        switch(frame, 2, t("switch_overlay_info"), self.overlay_info_var)
        switch(frame, 3, t("switch_overlay_patient"), self.overlay_patient_var)
        ttk.Label(frame, text=t("overlay_hint"), style="Caption.TLabel", wraplength=wrap, justify="left").grid(
            row=4, column=0, sticky="w"
        )

        # Anonimizacja
        frame, _ = section("anonymize", t("anonymization"))
        ttk.Label(frame, text=t("anonymize_hint"), style="Caption.TLabel", wraplength=wrap, justify="left").grid(
            row=1, column=0, sticky="w", pady=(0, px(8))
        )
        name_row = ttk.Frame(frame)
        name_row.grid(row=2, column=0, sticky="ew")
        name_row.columnconfigure(1, weight=1)
        ttk.Label(name_row, text=t("anonymize_name"), style="Caption.TLabel").grid(row=0, column=0, sticky="w", padx=(0, px(10)))
        self.anonymize_entry = ttk.Entry(name_row, textvariable=self.anonymize_name_var)
        self.anonymize_entry.grid(row=0, column=1, sticky="ew")
        self.setting_widgets.append(self.anonymize_entry)
        keep_dates = ttk.Frame(frame)
        keep_dates.grid(row=3, column=0, sticky="ew", pady=(px(8), 0))
        switch(keep_dates, 0, t("switch_keep_dates"), self.keep_dates_var)

        # Nazwy i foldery
        frame, _ = section("names", t("names"))
        self.name_entry, self.name_fields_btn = self._template_row(frame, 1, self.name_template_var)
        self.setting_widgets.extend((self.name_entry, self.name_fields_btn))

        frame, _ = section("folders", t("folders"))
        self.layout_choice = Choice(
            frame,
            self.layout_var,
            [(LAYOUT_FLAT, t("layout_flat")), (LAYOUT_SOURCE, t("layout_source")), (LAYOUT_TEMPLATE, t("layout_template"))],
        )
        self.layout_choice.widget.grid(row=1, column=0, sticky="ew")
        self.setting_widgets.append(self.layout_choice.widget)
        self.folder_entry, self.folder_fields_btn = self._template_row(frame, 2, self.folder_template_var, top=px(8))
        self.example_label = ttk.Label(frame, textvariable=self.example_var, style="Caption.TLabel", wraplength=wrap, justify="left")
        self.example_label.grid(row=3, column=0, sticky="w", pady=(px(8), 0))

        # Opcje
        frame, _ = section("options", t("options"))
        switch(frame, 1, t("switch_all_frames"), self.all_frames_var)
        switch(frame, 2, t("switch_overwrite"), self.overwrite_var)

    def _template_row(self, parent, row: int, variable: tk.StringVar, top: int = 0) -> tuple[ttk.Entry, ttk.Menubutton]:
        frame = ttk.Frame(parent)
        frame.grid(row=row, column=0, sticky="ew", pady=(top, 0))
        frame.columnconfigure(0, weight=1)
        entry = ttk.Entry(frame, textvariable=variable)
        entry.grid(row=0, column=0, sticky="ew")
        button = ttk.Menubutton(frame, text=t("btn_fields"))
        button.grid(row=0, column=1, padx=(self.px(8), 0))
        menu = tk.Menu(button, tearoff=0)
        for name in naming.SUGGESTED_FIELDS:
            menu.add_command(
                label=f"{{{name}}}  –  {t(f'field_{name}')}",
                command=lambda token=f"{{{name}}}": (entry.insert("insert", token), entry.focus_set()),
            )
        button["menu"] = menu
        return entry, button

    def _build_footer(self, parent) -> None:
        px = self.px
        footer = ttk.Frame(parent)
        footer.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(px(8), 0))
        ttk.Label(footer, text=f"© {COPYRIGHT_YEAR} {__author__}", style="Caption.TLabel").pack(side="left")
        links = [(__email__, f"mailto:{__email__}")]
        if GITHUB_URL:
            links.append(("GitHub", GITHUB_URL))
        for text, target in links:
            ttk.Label(footer, text="·", style="Caption.TLabel").pack(side="left", padx=px(8))
            link_label(footer, text, lambda url=target: webbrowser.open(url), small=True).pack(side="left")
        ttk.Label(footer, text=t("version", version=__version__), style="Caption.TLabel").pack(side="right")
        self.update_link = link_label(footer, "", self.open_update_dialog, small=True)
        if self.available_release is not None:
            self._show_update(self.available_release)

    # ------------------------------------------------------------------ zdarzenia

    def _bind_root_events(self) -> None:
        self.root.bind("<Control-o>", lambda _event: self.add_files())
        self.root.bind("<F1>", lambda _event: self.show_about())
        self.root.bind_all("<MouseWheel>", self._on_mousewheel)
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        if self.dnd_enabled:
            self.root.drop_target_register(DND_FILES)
            self.root.dnd_bind("<<Drop>>", self._on_drop)

    def _bind_widget_events(self) -> None:
        tree = self.tree
        tree.bind("<<TreeviewSelect>>", self._on_select)
        tree.bind("<Delete>", lambda _event: self.remove_selected())
        tree.bind("<Control-a>", self._select_all)
        tree.bind("<Button-3>", self._on_tree_right_click)
        tree.bind("<Double-1>", self._on_tree_double_click)
        for widget in (tree, self.zoom.canvas):
            widget.bind("<Left>", lambda _event: self._step_frame(-1))
            widget.bind("<Right>", lambda _event: self._step_frame(1))
            widget.bind("<space>", lambda _event: (self.toggle_playback(), "break")[1])
        self.tags_tree.bind("<Double-1>", self._copy_tag_value)
        self.drop_zone.bind("<Configure>", self._draw_drop_zone)
        self.drop_zone.bind("<Button-1>", lambda _event: self.add_files())
        self.drop_zone.bind("<Enter>", lambda _event: self._set_drop_hover(True))
        self.drop_zone.bind("<Leave>", lambda _event: self._set_drop_hover(False))
        if self.dnd_enabled:
            for widget in (tree, self.drop_zone):
                widget.drop_target_register(DND_FILES)
                widget.dnd_bind("<<Drop>>", self._on_drop)
            self.drop_zone.dnd_bind("<<DropEnter>>", lambda event: (self._set_drop_hover(True), event.action)[1])
            self.drop_zone.dnd_bind("<<DropLeave>>", lambda event: (self._set_drop_hover(False), event.action)[1])

    def _on_mousewheel(self, event):
        try:
            widget = self.root.winfo_containing(event.x_root, event.y_root)
        except (KeyError, tk.TclError):
            return None
        if widget is None or not self._ui_ready:
            return None
        if widget is self.zoom.canvas:
            if event.state & 0x0004:  # Ctrl + kółko: poprzedni / następny obraz
                self._step_frame(-1 if event.delta > 0 else 1)
            else:
                self.zoom.zoom_by(
                    1.25 ** (event.delta / 120), event.x_root - widget.winfo_rootx(), event.y_root - widget.winfo_rooty()
                )
            return "break"
        if self.export_scroll.contains(widget) or widget is self.export_scroll:
            self.export_scroll.scroll(-round(event.delta / 120) * 3)
            return "break"
        return None

    def _process_events(self) -> None:
        try:
            for _ in range(400):
                event = self.events.get_nowait()
                kind = event[0]
                if kind == "add":
                    self._add_rows(event[1], event[2])
                elif kind == "scan_done":
                    self._finish_scan(event[1], event[2])
                elif kind == "dicomdir":
                    self._show_dicomdir(*event[1:])
                elif kind == "preview_loaded":
                    self._on_preview_loaded(*event[1:])
                elif kind == "preview_image":
                    self._on_preview_image(*event[1:])
                elif kind == "preview_error":
                    self._on_preview_error(*event[1:])
                elif kind == "result":
                    self._handle_result(event[1])
                elif kind == "fatal":
                    messagebox.showerror(APP_TITLE, t("msg_fatal", error=event[1]), parent=self.root)
                elif kind == "done":
                    self._finish_conversion()
                elif kind == "update":
                    self._on_update_found(event[1])
                elif kind == "update_check":
                    self._on_update_check(event[1], event[2])
        except queue.Empty:
            pass
        self.root.after(50, self._process_events)

    # ------------------------------------------------------------------ motyw i język

    def _toggle_theme(self) -> None:
        self._apply_theme()
        self._save_settings()

    def _apply_theme(self, refresh_title_bar: bool = True) -> None:
        dark = self.dark_var.get()
        self.palette = PALETTES["dark" if dark else "light"]
        if sv_ttk is not None:
            sv_ttk.set_theme("dark" if dark else "light", self.root)
        self._configure_styles()
        self._apply_custom_colors()
        # Motyw przemalowuje klasyczne widżety Tk po zmianie - kolory własne nakładamy ponownie.
        self.root.after(60, self._apply_custom_colors)
        if refresh_title_bar:
            set_title_bar_theme(self.root, dark, refresh=True)

    def _configure_styles(self) -> None:
        palette = self.palette
        style = ttk.Style(self.root)
        body = tkfont.Font(root=self.root, name="SunValleyBodyFont", exists=True)
        style.configure("Treeview", rowheight=body.metrics("linespace") + self.px(12))
        style.configure("Title.TLabel", font="SunValleySubtitleFont", foreground=palette["fg"])
        style.configure("Section.TLabel", font="SunValleyBodyStrongFont", foreground=palette["fg"])
        style.configure("Value.TLabel", font="SunValleyBodyFont", foreground=palette["fg"])
        style.configure("Caption.TLabel", font="SunValleyCaptionFont", foreground=palette["muted"])
        style.configure("Link.TLabel", font="SunValleyBodyFont", foreground=palette["accent"])
        style.configure("CaptionLink.TLabel", font="SunValleyCaptionFont", foreground=palette["accent"])
        style.configure("Error.TLabel", font="SunValleyCaptionFont", foreground=palette["error"])
        style.configure("StatOk.TLabel", font="DicomExporterStatFont", foreground=palette["success"])
        style.configure("StatError.TLabel", font="DicomExporterStatFont", foreground=palette["error"])
        style.configure("StatMuted.TLabel", font="DicomExporterStatFont", foreground=palette["muted"])

    def _apply_custom_colors(self) -> None:
        if not self._ui_ready:
            return
        palette = self.palette
        reset_label_colors(self.root)
        self.drop_zone.configure(background=palette["bg"])
        self.zoom.canvas.configure(background=PREVIEW_BG)
        self.export_scroll.canvas.configure(background=palette["bg"])
        self.tree.tag_configure("ok", foreground=palette["success"])
        self.tree.tag_configure("error", foreground=palette["error"])
        self.tree.tag_configure("muted", foreground=palette["muted"])
        self._apply_icons()
        self._draw_drop_zone()
        self._update_controls()
        self._update_examples()

    def _apply_icons(self) -> None:
        for widget, (icon, color, gap, size, fallback) in list(self.icon_widgets.items()):
            if not widget.winfo_exists():
                continue
            normal = self.icons.get(icon, self.palette[color], size, gap=gap)
            disabled = self.icons.get(icon, self.palette["disabled"], size, gap=gap)
            if normal is None or disabled is None:
                if fallback:
                    widget.configure(text=fallback)
                continue
            # Osobny obrazek dla stanu "disabled" - inaczej Tk nakłada na ikonę szachownicę.
            widget.configure(image=(str(normal), "disabled", str(disabled)))

    def _change_language(self) -> None:
        code = self.language_var.get()
        if code == get_language():
            return
        if self.converting:
            self.language_var.set(get_language())
            return
        set_language(code)
        self._save_settings()
        self._rebuild_ui()

    def _rebuild_ui(self) -> None:
        self._stop_playback()
        rows = [self.rows[iid] for iid in self.tree.get_children()]
        selected = {self.rows[iid].key for iid in self.tree.selection()}
        tab_index = self.side_tabs.index("current")
        self._ui_ready = False
        self.row_menu.destroy()
        self.container.destroy()
        self.rows.clear()
        self.iid_by_key.clear()
        self.preview_path = None
        self._build_ui()
        self._bind_widget_events()
        for row in rows:
            self._insert_row(row)
        self._ui_ready = True
        self.side_tabs.select(tab_index)
        self.status_var.set(t("status_ready"))
        self._apply_theme(refresh_title_bar=False)
        selection = [iid for iid, row in self.rows.items() if row.key in selected]
        if selection:
            self.tree.selection_set(selection)
            self.tree.focus(selection[0])

    # ------------------------------------------------------------------ stan kontrolek

    def _update_controls(self) -> None:
        if not self._ui_ready:
            return
        count = len(self.rows)
        self.count_var.set(plural(count, "file") if count else t("no_files"))
        if count:
            self.drop_zone.place_forget()
        else:
            self.drop_zone.place(x=0, y=0, relwidth=1, relheight=1)
            tk.Misc.lift(self.drop_zone)  # Canvas.lift() przesuwa elementy rysunku, nie sam widżet

        idle = not self.converting
        for widget in (self.add_files_btn, self.add_folder_btn, self.disc_btn, *self.setting_widgets):
            set_enabled(widget, idle)
        set_enabled(self.language_choice.widget, idle)
        set_enabled(self.remove_btn, idle and bool(self.tree.selection()))
        set_enabled(self.clear_btn, idle and count > 0)
        set_enabled(self.convert_btn, idle and count > 0 and not self.scan_counts)
        set_enabled(self.cancel_btn, self.converting and not self.cancel_event.is_set())
        set_enabled(self.delete_profile_btn, idle and self.profile_var.get().startswith("user:"))

        export = self.export_mode_var.get()
        fmt = self.format_var.get()
        # Sekcje, które nie dotyczą wybranego trybu eksportu, są ukrywane.
        visible_sections = {
            "format": export not in (EXPORT_GIF, EXPORT_MP4, EXPORT_DICOM),
            "depth": export == EXPORT_IMAGES,
            "quality": export in (EXPORT_IMAGES, EXPORT_MONTAGE),
            "resize": export != EXPORT_DICOM,
            "overlays": export in OVERLAY_EXPORT_MODES,
            "anonymize": export == EXPORT_DICOM,
        }
        for key, visible in visible_sections.items():
            if visible:
                self.export_sections[key].grid()
            else:
                self.export_sections[key].grid_remove()
        for radio in self.format_radios:
            set_enabled(radio, idle)
        for radio in self.depth_radios:
            set_enabled(radio, idle and fmt in HIGH_BIT_DEPTH_FORMATS)
        quality = idle and fmt in QUALITY_FORMATS
        set_enabled(self.quality_scale, quality)
        for label in (self.quality_caption, self.quality_value):
            label.configure(foreground="" if quality else self.palette["disabled"])
        if export in (EXPORT_GIF, EXPORT_MP4):
            self.fps_row.grid()
        else:
            self.fps_row.grid_remove()
        resize = self.resize_mode_var.get()
        if resize == RESIZE_NONE:
            self.size_row.grid_remove()
        else:
            self.size_row.grid()
            visible, hidden = (self.fit_frame, self.scale_frame) if resize == RESIZE_FIT else (self.scale_frame, self.fit_frame)
            hidden.pack_forget()
            visible.pack(side="left")
        for spin in (self.fps_spin, self.max_width_spin, self.max_height_spin, self.scale_spin):
            set_enabled(spin, idle)
        template = idle and self.layout_var.get() == LAYOUT_TEMPLATE
        set_enabled(self.folder_entry, template)
        set_enabled(self.folder_fields_btn, template)
        self.export_hint.configure(text=t(f"export_hint_{export}"))

        has_image = self.zoom.image is not None
        for button in (self.zoom_out_btn, self.zoom_in_btn, self.fit_btn):
            set_enabled(button, has_image)
        _position, total, _kind = self._slice_state()
        for widget in (self.prev_frame_btn, self.next_frame_btn, self.play_btn, self.frame_scale):
            set_enabled(widget, total > 1)
        set_enabled(self.window_file_btn, self.preview_window is not None)
        set_enabled(self.mask_clear_btn, bool(self.masks))

    def _on_settings_changed(self) -> None:
        self._update_controls()
        self._update_examples()

    def _on_quality_change(self) -> None:
        if hasattr(self, "quality_value") and self.quality_value.winfo_exists():
            self.quality_value.configure(text=f"{self._quality()}%")

    def _quality(self) -> int:
        return min(100, max(1, round(_number(self.quality_var, 95))))

    def _update_examples(self) -> None:
        if not self._ui_ready:
            return
        row = self._focused_row()
        ds = self.preview_ds
        template = self.name_template_var.get().strip() or naming.DEFAULT_NAME_TEMPLATE
        layout = self.layout_var.get()
        folder_template = self.folder_template_var.get()
        unknown = naming.unknown_fields(template) + (naming.unknown_fields(folder_template) if layout == LAYOUT_TEMPLATE else [])
        error = bool(unknown)
        if unknown:
            text = t("err_template", fields=", ".join(unknown))
        elif ds is None or row is None or row.item.path != self.preview_path:
            text = t("example_none")
        else:
            export = self.export_mode_var.get()
            frames = self.preview_frames if self.all_frames_var.get() and export == EXPORT_IMAGES else 1
            stem = output_stem(row.item.path)
            name = naming.render_filename(template, ds, file_stem=stem, frame=1, total_frames=frames)
            extensions = {EXPORT_GIF: ".gif", EXPORT_MP4: ".mp4", EXPORT_DICOM: ".dcm"}
            extension = extensions.get(export, IMAGE_FORMATS[self.format_var.get()])
            if layout == LAYOUT_TEMPLATE:
                folder = naming.render_folder(folder_template, ds, file_stem=stem)
            elif layout == LAYOUT_SOURCE:
                folder = row.item.output_subdir()
            else:
                folder = Path()
            text = t("example", path=folder / f"{name}{extension}")
        self.example_var.set(text)
        self.example_label.configure(foreground=self.palette["error"] if error else "")

    # ------------------------------------------------------------------ profile eksportu

    def _profile_options(self) -> list[tuple[str, str]]:
        options = [("", t("profile_custom"))]
        options += [(f"builtin:{key}", builtin_label(key)) for key in BUILTIN_PROFILES]
        options += [(f"user:{name}", f"★ {name}") for name in sorted(self.user_profiles, key=str.lower)]
        return options

    def _profile_values(self, key: str) -> dict | None:
        if key.startswith("builtin:"):
            return BUILTIN_PROFILES.get(key.removeprefix("builtin:"))
        if key.startswith("user:"):
            return self.user_profiles.get(key.removeprefix("user:"))
        return None

    def _apply_profile(self) -> None:
        values = self._profile_values(self.profile_var.get())
        if not values:
            self._update_controls()
            return
        self._applying_profile = True
        try:
            for key, variable in self._profile_variables().items():
                if key in values:
                    variable.set(values[key])
        finally:
            self._applying_profile = False
        self._update_controls()
        self._update_examples()
        self._schedule_preview(30)

    def _on_profile_value_changed(self) -> None:
        if not self._applying_profile and self.profile_var.get():
            self.profile_var.set("")  # ręczna zmiana ustawień = własne ustawienia
            if self._ui_ready:
                self._update_controls()

    def save_profile(self) -> None:
        name = simpledialog.askstring(APP_TITLE, t("profile_name_prompt"), parent=self.root)
        name = (name or "").strip()[:40]
        if not name:
            return
        values = {key: _number(variable, None) for key, variable in self._profile_variables().items()}
        values["quality"] = self._quality()
        self.user_profiles[name] = {key: value for key, value in values.items() if value is not None}
        self.profile_choice.set_options(self._profile_options())
        self.profile_var.set(f"user:{name}")
        self._save_settings()
        self._update_controls()

    def delete_profile(self) -> None:
        key = self.profile_var.get()
        name = key.removeprefix("user:")
        if not key.startswith("user:") or name not in self.user_profiles:
            return
        if messagebox.askyesno(APP_TITLE, t("profile_delete_confirm", name=name), parent=self.root):
            del self.user_profiles[name]
            self.profile_var.set("")
            self.profile_choice.set_options(self._profile_options())
            self._save_settings()
            self._update_controls()

    # ------------------------------------------------------------------ strefa upuszczania

    def _set_drop_hover(self, hover: bool) -> None:
        hover = hover and not self.converting
        if hover != self.drop_hover:
            self.drop_hover = hover
            self._draw_drop_zone()

    def _draw_drop_zone(self, _event=None) -> None:
        canvas = self.drop_zone
        canvas.delete("all")
        width, height = canvas.winfo_width(), canvas.winfo_height()
        if width < 80 or height < 80:
            return
        palette, px = self.palette, self.px
        highlight = self.drop_hover
        rounded_rect(
            canvas,
            px(2),
            px(2),
            width - px(2),
            height - px(2),
            px(10),
            outline=palette["accent"] if highlight else palette["border"],
            fill=palette["accent_soft"] if highlight else palette["bg"],
            dash=(6, 4),
            width=max(1, px(1)),
        )
        center_x, center_y = width / 2, height / 2 - px(10)
        radius, icon_y = px(36), center_y - px(46)
        canvas.create_oval(
            center_x - radius,
            icon_y - radius,
            center_x + radius,
            icon_y + radius,
            fill=palette["bg"] if highlight else palette["accent_soft"],
            outline="",
        )
        icon = self.icons.get("upload", palette["accent"], 30)
        if icon is not None:
            canvas.create_image(center_x, icon_y, image=icon)
        title = t("drop_title") if self.dnd_enabled else t("drop_title_no_dnd")
        canvas.create_text(center_x, center_y + px(10), text=title, font="SunValleySubtitleFont", fill=palette["fg"])
        canvas.create_text(center_x, center_y + px(40), text=t("drop_subtitle"), font="SunValleyBodyFont", fill=palette["muted"])
        canvas.create_text(
            center_x,
            center_y + px(72),
            text=t("drop_supported"),
            font="SunValleyCaptionFont",
            fill=palette["muted"],
            width=width - px(60),
            justify="center",
        )

    # ------------------------------------------------------------------ dodawanie plików

    def add_files(self) -> None:
        if self.converting:
            return
        paths = filedialog.askopenfilenames(
            parent=self.root,
            title=t("dialog_choose_files"),
            filetypes=[(t("dialog_dicom_files"), DICOM_PATTERNS), (t("dialog_all_files"), "*.*")],
        )
        if paths:
            self.add_paths(paths)

    def add_folder(self) -> None:
        if self.converting:
            return
        folder = filedialog.askdirectory(parent=self.root, title=t("dialog_choose_folder"), mustexist=True)
        if folder:
            self.add_paths([folder])

    def open_disc(self) -> None:
        if self.converting:
            return
        path = filedialog.askopenfilename(
            parent=self.root, title=t("dialog_open_disc"), filetypes=[("DICOMDIR", "DICOMDIR"), (t("dialog_all_files"), "*.*")]
        )
        if path:
            self.add_paths([path])

    def _on_drop(self, event) -> str:
        self._set_drop_hover(False)
        if self.converting:
            self.root.bell()
        else:
            self.add_paths(self.root.tk.splitlist(event.data))
        return event.action

    def add_paths(self, paths) -> None:
        regular: list[Path] = []
        for path in (Path(raw) for raw in paths):
            dicomdir = path if is_dicomdir(path) else find_dicomdir(path) if path.is_dir() else None
            if dicomdir is not None and (
                dicomdir == path
                or messagebox.askyesno(APP_TITLE, t("ask_open_dicomdir", folder=path), parent=self.root)
            ):
                self._load_dicomdir(dicomdir)
            else:
                regular.append(path)
        if regular:
            self._start_scan(lambda skipped: collect_inputs(regular, skipped=skipped))

    def add_input_files(self, items: list[InputFile]) -> None:
        self._start_scan(lambda _skipped: iter(items))

    def _start_scan(self, producer) -> None:
        scan_id = self.next_scan_id
        self.next_scan_id += 1
        self.scan_counts[scan_id] = 0
        self.status_var.set(t("status_scanning"))
        self._update_controls()
        threading.Thread(target=self._scan_worker, args=(scan_id, producer), daemon=True).start()

    def _scan_worker(self, scan_id: int, producer) -> None:
        skipped: list[Path] = []
        batch: list[tuple[InputFile, FileInfo]] = []
        try:
            for item in producer(skipped):
                batch.append((item, read_file_info(item.path)))
                if len(batch) >= SCAN_BATCH:
                    self.events.put(("add", scan_id, batch))
                    batch = []
        finally:
            if batch:
                self.events.put(("add", scan_id, batch))
            self.events.put(("scan_done", scan_id, len(skipped)))

    def _add_rows(self, scan_id: int, batch: list[tuple[InputFile, FileInfo]]) -> None:
        added = 0
        for item, info in batch:
            if _path_key(item.path) in self.iid_by_key:
                continue
            self._insert_row(Row(item, info))
            added += 1
        self.scan_counts[scan_id] = self.scan_counts.get(scan_id, 0) + added
        self._update_controls()

    def _finish_scan(self, scan_id: int, skipped: int) -> None:
        added = self.scan_counts.pop(scan_id, 0)
        message = t("status_added", files=plural(added, "file")) if added else t("status_nothing_added")
        if skipped:
            message += t("status_skipped", files=plural(skipped, "file"))
        self.status_var.set(message)
        self._apply_sort()
        self._update_controls()

    def _load_dicomdir(self, path: Path) -> None:
        self.status_var.set(t("status_reading_disc"))

        def worker() -> None:
            try:
                self.events.put(("dicomdir", path, read_dicomdir(path), None))
            except Exception as exc:
                self.events.put(("dicomdir", path, None, str(exc)))

        threading.Thread(target=worker, daemon=True).start()

    def _show_dicomdir(self, path: Path, patients, error: str | None) -> None:
        self.status_var.set(t("status_ready"))
        if error:
            messagebox.showerror(APP_TITLE, error, parent=self.root)
        elif not patients:
            messagebox.showinfo(APP_TITLE, t("dicomdir_empty"), parent=self.root)
        else:
            DicomdirDialog(
                self, path, patients, lambda files: self.add_input_files([InputFile(file, root=path.parent) for file in files])
            )

    # ------------------------------------------------------------------ lista plików

    def _insert_row(self, row: Row) -> str:
        iid = f"r{self.next_row_id}"
        self.next_row_id += 1
        self.rows[iid] = row
        self.iid_by_key[row.key] = iid
        self.tree.insert("", "end", iid=iid, values=self._row_values(row), tags=self._row_tags(row))
        return iid

    def _refresh_row(self, iid: str) -> None:
        row = self.rows[iid]
        self.tree.item(iid, values=self._row_values(row), tags=self._row_tags(row))

    def _row_values(self, row: Row) -> tuple:
        info = row.info
        return (
            row.item.path.name,
            self._status_text(row),
            info.modality,
            "" if info.series_number is None else info.series_number,
            info.frames or "",
            f"{info.columns}×{info.rows}" if info.columns and info.rows else "",
            format_size(info.file_size) if info.file_size else "",
            str(row.item.path.parent),
        )

    @staticmethod
    def _row_tags(row: Row) -> tuple:
        return {STATUS_OK: ("ok",), STATUS_ERROR: ("error",), STATUS_QUEUED: ("muted",), STATUS_CANCELLED: ("muted",)}.get(
            row.status, ()
        )

    @staticmethod
    def _status_text(row: Row) -> str:
        if row.status == STATUS_OK:
            count = len(row.outputs)
            return f"✓  {t('status_ok')}" if count == 1 else f"✓  {t('status_ok_count', images=plural(count, 'image'))}"
        if row.status == STATUS_ERROR:
            return f"✕  {t('status_error', error=row.error)}"
        if row.status == STATUS_QUEUED:
            return f"…  {t('status_queued')}"
        if row.status == STATUS_CANCELLED:
            return f"–  {t('status_cancelled')}"
        return f"•  {t('status_pending')}"

    def _sort_by(self, column: str) -> None:
        if self.sort_column == column:
            self.sort_reverse = not self.sort_reverse
        else:
            self.sort_column, self.sort_reverse = column, False
        self._apply_sort()
        self._update_sort_headings()

    def _apply_sort(self) -> None:
        if self.sort_column is None:
            return
        key = SORT_KEYS[self.sort_column]
        ordered = sorted(self.rows.items(), key=lambda pair: key(pair[1]), reverse=self.sort_reverse)
        for index, (iid, _row) in enumerate(ordered):
            self.tree.move(iid, "", index)

    def _update_sort_headings(self) -> None:
        for key, label, *_rest in COLUMNS:
            arrow = (" ▼" if self.sort_reverse else " ▲") if key == self.sort_column else ""
            self.tree.heading(key, text=f"{t(label)}{arrow}")

    def _selected_rows(self) -> list[Row]:
        return [self.rows[iid] for iid in self.tree.selection() if iid in self.rows]

    def _focused_row(self) -> Row | None:
        selection = self.tree.selection()
        if not selection:
            return None
        focus = self.tree.focus()
        return self.rows.get(focus if focus in selection else selection[0])

    def _on_select(self, _event=None) -> None:
        if self._navigating:  # zmiana obrazu serii z podglądu (strzałki, kółko, odtwarzanie)
            self._navigating = False
            delay = 0
        else:
            self._stop_playback()
            delay = 120
        self._update_controls()
        self._schedule_preview(delay)

    def _select_all(self, _event=None) -> str:
        self.tree.selection_set(self.tree.get_children())
        return "break"

    def _on_tree_right_click(self, event) -> None:
        iid = self.tree.identify_row(event.y)
        if not iid:
            return
        if iid not in self.tree.selection():
            self.tree.selection_set(iid)
            self.tree.focus(iid)
        idle = not self.converting
        has_results = any(row.outputs for row in self._selected_rows())
        self.row_menu.entryconfigure(0, state="normal" if idle else "disabled")
        self.row_menu.entryconfigure(1, state="normal" if has_results else "disabled")
        self.row_menu.entryconfigure(4, state="normal" if idle else "disabled")
        try:
            self.row_menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.row_menu.grab_release()

    def _on_tree_double_click(self, event) -> None:
        iid = self.tree.identify_row(event.y)
        row = self.rows.get(iid)
        if row is not None:
            existing = [path for path in row.outputs if path.exists()]
            if existing:
                open_path(existing[0])

    def show_result(self) -> None:
        outputs = [path for row in self._selected_rows() for path in row.outputs if path.exists()]
        if outputs:
            reveal_in_explorer(outputs[0])
        else:
            messagebox.showinfo(APP_TITLE, t("msg_no_result"), parent=self.root)

    def open_source_location(self) -> None:
        rows = self._selected_rows()
        if rows:
            reveal_in_explorer(rows[0].item.path)

    def remove_selected(self) -> None:
        if self.converting:
            return
        self._stop_playback()
        for iid in self.tree.selection():
            row = self.rows.pop(iid, None)
            if row is not None:
                self.iid_by_key.pop(row.key, None)
                if row.item.path == self.preview_path:
                    self._clear_preview()
            self.tree.delete(iid)
        self._update_controls()

    def clear_list(self) -> None:
        if self.converting:
            return
        self._stop_playback()
        self.tree.delete(*self.tree.get_children())
        self.rows.clear()
        self.iid_by_key.clear()
        self._clear_preview()
        self.progress.configure(value=0)
        self.status_var.set(t("status_ready"))
        self._update_controls()

    # ------------------------------------------------------------------ podgląd

    def _schedule_preview(self, delay: int = 120) -> None:
        if not self._ui_ready:
            return
        if self.preview_after is not None:
            self.root.after_cancel(self.preview_after)
        self.preview_after = self.root.after(delay, self._request_preview)

    def _preview_options(self) -> ConvertOptions:
        return ConvertOptions(
            windowing=self.window_mode_var.get(),
            window_center=float(_number(self.center_var, 40)),
            window_width=float(max(1, _number(self.width_var, 400))),
            masks=tuple(self.masks),
            export_mode=self.export_mode_var.get(),
            overlay_scale=self.overlay_scale_var.get(),
            overlay_info=self.overlay_info_var.get(),
            overlay_patient=self.overlay_patient_var.get(),
        )

    def _request_preview(self) -> None:
        self.preview_after = None
        if not self._ui_ready:
            return
        row = self._focused_row()
        if row is None:
            return
        path = row.item.path
        include_info = path != self.preview_path
        if include_info:
            self.preview_path, self.preview_image_path = path, None
            self.preview_frame, self.preview_frames = 0, 1
            self.preview_ds, self.preview_tags, self.preview_window, self.preview_range = None, [], None, None
            if not self._keep_view:  # przy przewijaniu serii zostaje poprzedni obraz, aż wczyta się następny
                self.zoom.show_message(t("preview_loading"))
            self._set_preview_text(path.name)
            self._update_frame_controls()
            self._populate_tags()
            self._update_examples()
        self.preview_token += 1
        self.preview_worker.submit(self.preview_token, path, self.preview_frame, self._preview_options(), include_info)

    def _on_preview_loaded(self, path: Path, info: dict) -> None:
        if path != self.preview_path or not self._ui_ready:
            return
        self.preview_ds = info["dataset"]
        self.preview_frames = info["frames"]
        self.preview_tags = info["tags"]
        self.preview_window = info["window"]
        self.preview_range = info["range"]
        details = info["details"]
        first = [details.get(key) for key in ("size", "frames", "modality")]
        second = [details.get(key) for key in ("compression", "photometric", "bits")]
        self._set_preview_text(path.name, " · ".join(v for v in first if v), " · ".join(v for v in second if v))
        self._sync_window_scales()
        self._update_frame_controls()
        self._populate_tags()
        self._update_examples()
        self._update_controls()

    def _on_preview_image(self, token: int, path: Path, frame: int, image) -> None:
        if path != self.preview_path or token != self.preview_token or not self._ui_ready:
            return
        self.zoom.set_image(image, keep_view=self.preview_image_path == path or self._keep_view)
        self._keep_view = False
        self.preview_image_path = path

    def _on_preview_error(self, token: int, path: Path, message: str) -> None:
        if path != self.preview_path or token != self.preview_token or not self._ui_ready:
            return
        self._keep_view = False
        self.zoom.show_message(t("preview_error", error=ellipsize(message, 220)), icon="error", color=PREVIEW_ERROR)
        self.preview_image_path = None
        self._update_controls()

    def _on_zoom_changed(self) -> None:
        percent = self.zoom.zoom_percent()
        self.zoom_var.set(f"{percent}%" if percent is not None else "—")
        if self._ui_ready:
            self._update_controls()

    def _set_preview_text(self, name: str = "", first_line: str = "", second_line: str = "") -> None:
        self.preview_name.configure(text=ellipsize(name, 52) or " ")
        self.preview_meta.configure(text=f"{first_line or ' '}\n{second_line or ' '}")

    def _clear_preview(self) -> None:
        self.preview_token += 1
        self.preview_path = self.preview_image_path = None
        self.preview_ds, self.preview_tags, self.preview_window, self.preview_range = None, [], None, None
        self.preview_frame, self.preview_frames = 0, 1
        self.preview_worker.forget()
        self.zoom.show_message(t("preview_select"))
        self._set_preview_text()
        self._update_frame_controls()
        self._populate_tags()
        self._update_examples()

    # --- klatki, serie i odtwarzanie

    def _series_iids(self, row: Row | None) -> list[str]:
        """Pliki tej samej serii na liście, posortowane według numeru obrazu."""
        if row is None or not row.info.series_uid:
            return []
        iids = [iid for iid, other in self.rows.items() if other.info.series_uid == row.info.series_uid]

        def order(iid: str):
            info = self.rows[iid].info
            return info.instance_number is None, info.instance_number or 0, natural_key(self.rows[iid].item.path.name)

        return sorted(iids, key=order)

    def _slice_state(self) -> tuple[int, int, str]:
        """(pozycja, liczba, rodzaj): klatki pliku wieloklatkowego albo obrazy serii."""
        if self.preview_path is None:
            return 0, 1, "frame"
        if self.preview_frames > 1:
            return self.preview_frame, self.preview_frames, "frame"
        row = self._focused_row()
        iids = self._series_iids(row)
        current = self.iid_by_key.get(row.key) if row is not None else None
        if len(iids) > 1 and current in iids:
            return iids.index(current), len(iids), "series"
        return 0, 1, "frame"

    def _go_to_slice(self, index: int, wrap: bool = False) -> None:
        position, total, kind = self._slice_state()
        if total <= 1:
            return
        index = index % total if wrap else min(max(index, 0), total - 1)
        if index == position:
            return
        if kind == "frame":
            self.preview_frame = index
            self._update_frame_controls()
            self._request_preview()
            return
        iid = self._series_iids(self._focused_row())[index]
        self._navigating = True
        self._keep_view = True
        self.tree.selection_set(iid)
        self.tree.focus(iid)
        self.tree.see(iid)

    def _step_frame(self, delta: int) -> str:
        position, _total, _kind = self._slice_state()
        self._go_to_slice(position + delta)
        return "break"

    def _update_frame_controls(self) -> None:
        position, total, kind = self._slice_state()
        self.frame_scale.configure(to=max(total - 1, 1))
        self._syncing = True
        disabled = self.frame_scale.instate(["disabled"])
        try:
            self.frame_scale.state(["!disabled"])  # wyłączony ttk.Scale ignoruje set()
            self.frame_scale.set(position)
        finally:
            if disabled:
                self.frame_scale.state(["disabled"])
            self._syncing = False
        label = "series_counter" if kind == "series" else "frame_counter"
        self.frame_label_var.set(t(label, current=position + 1, total=total))

    def _on_frame_scale(self, value: str) -> None:
        if not self._syncing:
            self._go_to_slice(round(float(value)))

    def toggle_playback(self) -> None:
        if self.playing:
            self._stop_playback()
            return
        if self._slice_state()[1] <= 1:
            return
        self.playing = True
        self._set_play_icon()
        self._play_step()

    def _play_step(self) -> None:
        self.play_after = None
        if not self.playing:
            return
        position, total, _kind = self._slice_state()
        if total <= 1:
            self._stop_playback()
            return
        self._go_to_slice(position + 1, wrap=True)
        fps = min(60, max(1, _number(self.fps_var, 10)))
        self.play_after = self.root.after(round(1000 / fps), self._play_step)

    def _stop_playback(self) -> None:
        if self.play_after is not None:
            self.root.after_cancel(self.play_after)
            self.play_after = None
        if self.playing:
            self.playing = False
            self._set_play_icon()

    def _set_play_icon(self) -> None:
        if self._ui_ready and self.play_btn.winfo_exists():
            self.icon_widgets[self.play_btn] = ("pause" if self.playing else "play", "fg", 0, 16, "⏸" if self.playing else "⏵")
            self._apply_icons()

    # --- jasność i kontrast

    def _on_window_mode_selected(self) -> None:
        if self.window_mode_var.get() == WINDOW_CUSTOM and self.preview_window is not None:
            self._window_from_file()

    def _on_window_mode_changed(self) -> None:
        if self._ui_ready:
            self._update_controls()
            self._schedule_preview(30)

    def _window_from_file(self) -> None:
        if self.preview_window is None:
            return
        center, width = self.preview_window
        self.center_var.set(round(center))
        self.width_var.set(max(1, round(width)))

    def _apply_preset(self, key: str) -> None:
        center, width = CT_PRESETS[key]
        self.center_var.set(round(center))
        self.width_var.set(round(width))

    def _on_window_drag(self, phase: str, dx: int, dy: int) -> None:
        """Prawy przycisk w podglądzie: w pionie jasność (środek okna), w poziomie kontrast (szerokość)."""
        if phase == "start":
            low, high = self.preview_range or (0.0, 255.0)
            span = max(high - low, 1.0)
            mode = self.window_mode_var.get()
            if mode == WINDOW_CUSTOM:
                center, width = float(_number(self.center_var, 40)), float(_number(self.width_var, 400))
            elif mode == WINDOW_DICOM and self.preview_window is not None:
                center, width = self.preview_window
            else:
                center, width = (low + high) / 2, span
            self._window_drag_origin = (center, width, span)
        elif phase == "move" and self._window_drag_origin is not None:
            center, width, span = self._window_drag_origin
            factor = span / max(300, self.zoom.canvas.winfo_width())
            self.center_var.set(round(center + dy * factor))
            self.width_var.set(max(1, round(width + dx * factor)))
        else:
            self._window_drag_origin = None

    def _on_window_scale(self, variable: tk.IntVar, value: str) -> None:
        if self._syncing:
            return
        number = round(float(value))
        if variable is self.width_var:
            number = max(1, number)
        if _number(variable, None) != number:
            variable.set(number)

    def _on_window_values_changed(self) -> None:
        center, width = _number(self.center_var, None), _number(self.width_var, None)
        if center is None or width is None or width < 1 or not self._ui_ready:
            return
        self._sync_window_scales()
        if self.window_mode_var.get() != WINDOW_CUSTOM:
            self.window_mode_var.set(WINDOW_CUSTOM)
        else:
            self._schedule_preview(30)

    def _sync_window_scales(self) -> None:
        """Dopasowuje zakres suwaków do wartości obrazu i ustawia ich położenie."""
        low, high = self.preview_range or (-1024.0, 3071.0)
        center, width = _number(self.center_var, 40), max(1, _number(self.width_var, 400))
        span = max(high - low, 1.0)
        self._syncing = True
        try:
            self.center_scale.configure(from_=min(low, center), to=max(high, center))
            self.width_scale.configure(from_=1, to=max(span * 2, width))
            self.center_scale.set(center)
            self.width_scale.set(width)
        finally:
            self._syncing = False

    # --- maskowanie

    def _add_mask(self, rect: tuple[float, float, float, float]) -> None:
        mask = _valid_mask(round(value, 4) for value in rect)
        if mask is not None and mask not in self.masks:
            self.masks.append(mask)
            self._on_masks_changed()

    def _add_band(self, top: bool) -> None:
        self._add_mask((0.0, 0.0, 1.0, BAND_HEIGHT) if top else (0.0, 1.0 - BAND_HEIGHT, 1.0, 1.0))

    def _clear_masks(self) -> None:
        self.masks.clear()
        self.draw_mask_var.set(False)
        self._on_draw_mode()
        self._on_masks_changed()

    def _on_draw_mode(self) -> None:
        self.zoom.set_draw_mode(self.draw_mask_var.get())

    def _on_masks_changed(self) -> None:
        self.zoom.set_masks(self.masks)
        self._update_mask_count()
        self._save_settings()
        self._update_controls()
        self._schedule_preview(0)

    def _update_mask_count(self) -> None:
        self.mask_count_var.set(plural(len(self.masks), "area") if self.masks else t("masks_none"))

    # --- tagi DICOM

    def _schedule_tags(self) -> None:
        if self.tags_after is not None:
            self.root.after_cancel(self.tags_after)
        self.tags_after = self.root.after(200, self._populate_tags)

    def _populate_tags(self) -> None:
        self.tags_after = None
        if not self._ui_ready:
            return
        tree = self.tags_tree
        tree.delete(*tree.get_children())
        if not self.preview_tags:
            self.tags_hint.configure(text=t("tags_no_file"))
            return
        query = self.tag_search_var.get().strip().lower()
        matches = self._insert_tag_rows("", self.preview_tags, query)
        self.tags_hint.configure(text=t("tags_no_match") if query and not matches else t("tags_hint"))

    def _insert_tag_rows(self, parent: str, rows, query: str) -> int:
        matches = 0
        for row in rows:
            iid = self.tags_tree.insert(parent, "end", text=row.tag, values=(row.name, row.vr, row.value))
            own = not query or query in row.tag.lower() or query in row.name.lower() or query in row.value.lower()
            child_matches = self._insert_tag_rows(iid, row.children, "" if own else query)
            if own or child_matches:
                matches += 1
                if query and child_matches and not own:
                    self.tags_tree.item(iid, open=True)
            else:
                self.tags_tree.delete(iid)
        return matches

    def _copy_tag_value(self, event) -> None:
        iid = self.tags_tree.identify_row(event.y)
        value = self.tags_tree.set(iid, "value") if iid else ""
        if value:
            self.root.clipboard_clear()
            self.root.clipboard_append(value)
            self.tags_hint.configure(text=t("tag_copied"))

    # ------------------------------------------------------------------ konwersja

    def choose_output(self) -> None:
        current = self.output_var.get().strip()
        folder = filedialog.askdirectory(
            parent=self.root,
            title=t("dialog_choose_output"),
            initialdir=current if current and Path(current).is_dir() else str(Path.home()),
        )
        if folder:
            self.output_var.set(str(Path(folder)))

    def open_output(self) -> None:
        folder = Path(self.output_var.get().strip() or DEFAULT_OUTPUT)
        if folder.is_dir():
            open_path(folder)
        else:
            messagebox.showinfo(APP_TITLE, t("msg_output_missing"), parent=self.root)

    def _export_options(self) -> ConvertOptions:
        export = self.export_mode_var.get()
        fmt = self.format_var.get()
        bit_depth = _number(self.bit_depth_var, 8) if export == EXPORT_IMAGES and fmt in HIGH_BIT_DEPTH_FORMATS else 8
        return ConvertOptions(
            fmt=fmt,
            bit_depth=bit_depth,
            quality=self._quality(),
            windowing=self.window_mode_var.get(),
            window_center=float(_number(self.center_var, 40)),
            window_width=float(_number(self.width_var, 0)),
            resize_mode=self.resize_mode_var.get(),
            max_width=int(_number(self.max_width_var, 0)),
            max_height=int(_number(self.max_height_var, 0)),
            scale_percent=int(_number(self.scale_var, 0)),
            name_template=self.name_template_var.get().strip() or naming.DEFAULT_NAME_TEMPLATE,
            layout=self.layout_var.get(),
            folder_template=self.folder_template_var.get().strip(),
            export_mode=export,
            fps=int(_number(self.fps_var, 0)),
            all_frames=self.all_frames_var.get(),
            overwrite=self.overwrite_var.get(),
            masks=tuple(self.masks),
            overlay_scale=self.overlay_scale_var.get(),
            overlay_info=self.overlay_info_var.get(),
            overlay_patient=self.overlay_patient_var.get(),
            anonymize_name=self.anonymize_name_var.get(),
            anonymize_keep_dates=self.keep_dates_var.get(),
        )

    def start_conversion(self, selected_only: bool = False) -> None:
        if self.converting or not self.rows:
            return
        selection = set(self.tree.selection())
        iids = [iid for iid in self.tree.get_children() if not selected_only or iid in selection]
        if not iids:
            return
        output = self.output_var.get().strip()
        if not output:
            messagebox.showwarning(APP_TITLE, t("msg_choose_output"), parent=self.root)
            return
        try:
            options = self._export_options()
        except ValueError as exc:
            messagebox.showerror(APP_TITLE, t("msg_invalid_options", error=exc), parent=self.root)
            return
        if options.export_mode == EXPORT_MP4 and importlib.util.find_spec("imageio_ffmpeg") is None:
            messagebox.showerror(APP_TITLE, t("err_mp4"), parent=self.root)
            return
        output_dir = Path(output).expanduser()
        try:
            output_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            messagebox.showerror(APP_TITLE, t("msg_output_error", error=exc), parent=self.root)
            return
        self._save_settings()

        for iid in iids:
            row = self.rows[iid]
            row.status, row.error, row.outputs = STATUS_QUEUED, "", []
            self._refresh_row(iid)
        self.stats = {"total": len(iids), "ok": 0, "error": 0}
        self.output_paths = set()
        self.results = []
        self.started_at = datetime.now()
        self.used_output_dir = output_dir
        self.progress.configure(maximum=len(iids), value=0)
        self.status_var.set(t("status_converting", done=0, total=len(iids)))
        self.cancel_event.clear()
        self.converting = True
        self.taskbar.set(0, len(iids))
        self._set_drop_hover(False)
        self._update_controls()

        items = [self.rows[iid].item for iid in iids]
        threading.Thread(target=self._convert_worker, args=(items, output_dir, options), daemon=True).start()

    def _convert_worker(self, items: list[InputFile], output_dir: Path, options: ConvertOptions) -> None:
        try:
            for result in convert_batch(items, output_dir, options, cancel_event=self.cancel_event):
                self.events.put(("result", result))
        except Exception as exc:
            self.events.put(("fatal", str(exc)))
        finally:
            self.events.put(("done",))

    def _handle_result(self, result: FileResult) -> None:
        self.results.append(result)
        self.stats["ok" if result.ok else "error"] += 1
        self.output_paths.update(result.outputs)
        iid = self.iid_by_key.get(_path_key(result.item.path))
        if iid is not None:
            row = self.rows[iid]
            row.status = STATUS_OK if result.ok else STATUS_ERROR
            row.error = result.error or ""
            row.outputs = list(result.outputs)
            self._refresh_row(iid)
        done = self.stats["ok"] + self.stats["error"]
        self.progress.configure(value=done)
        self.taskbar.set(done, self.stats["total"])
        if not self.cancel_event.is_set():
            self.status_var.set(t("status_converting", done=done, total=self.stats["total"]))

    def _finish_conversion(self) -> None:
        cancelled = self.cancel_event.is_set()
        self.converting = False
        for iid, row in self.rows.items():
            if row.status == STATUS_QUEUED:
                row.status = STATUS_CANCELLED
                self._refresh_row(iid)

        stats = self.stats
        summary = t("summary", files=plural(stats["ok"], "file"), images=plural(len(self.output_paths), "image"))
        if stats["error"]:
            summary += t("summary_errors", count=stats["error"])
        if cancelled:
            summary = t("status_cancelled_prefix", summary=summary)
        self.status_var.set(summary)

        if stats["error"]:
            self.taskbar.set(stats["total"], stats["total"], TaskbarProgress.ERROR)
            self.root.after(4000, self.taskbar.clear)
        else:
            self.taskbar.clear()
        if not cancelled:
            message = summary + (f"\n{t('notify_errors')}" if stats["error"] else "")
            self.notifier.notify(t("notify_title"), message, warning=bool(stats["error"]))
            flash_taskbar(self.root)
        self._apply_sort()
        self._update_controls()
        if self.results:
            SummaryDialog(
                self,
                self.results,
                total=stats["total"],
                images=len(self.output_paths),
                elapsed=(datetime.now() - self.started_at).total_seconds(),
                output_dir=self.used_output_dir,
                cancelled=cancelled,
            )

    def cancel(self) -> None:
        if self.converting:
            self.cancel_event.set()
            self.status_var.set(t("status_cancelling"))
            self._update_controls()

    # ------------------------------------------------------------------ okna

    def _check_updates_worker(self) -> None:
        release = check_for_update()
        if release is not None:
            self.events.put(("update", release))

    def check_updates_now(self) -> None:
        """Ręczne sprawdzenie z okna „O programie” – w przeciwieństwie do startowego zgłasza też brak sieci."""

        def worker() -> None:
            try:
                release, error = latest_release(), None
            except UpdateError as exc:
                release, error = None, str(exc)
            self.events.put(("update_check", release, error))

        threading.Thread(target=worker, daemon=True).start()

    def _on_update_check(self, release: Release | None, error: str | None) -> None:
        about = self.about_dialog if self.about_dialog is not None and self.about_dialog.window.winfo_exists() else None
        if about is not None:
            about.check_finished()
        parent = about.window if about is not None else self.root
        if error is not None:
            messagebox.showerror(APP_TITLE, t("update_check_failed", error=error), parent=parent)
        elif release is not None and is_newer(release.version):
            self._show_update(release)
            self.open_update_dialog()
        else:
            messagebox.showinfo(APP_TITLE, t("update_latest", version=__version__), parent=parent)

    def _on_update_found(self, release: Release) -> None:
        """Wynik sprawdzenia przy starcie: link w stopce, a o każdej nowej wersji jednorazowo okno aktualizacji."""
        self._show_update(release)
        if release.version != self.update_prompted and not self.converting and self.root.grab_current() is None:
            self.update_prompted = release.version
            self._save_settings()
            self.open_update_dialog()

    def _show_update(self, release: Release) -> None:
        self.available_release = release
        self.update_link.configure(text=t("update_available", version=release.version))
        self.update_link.pack(side="right", padx=(0, self.px(16)))

    def open_update_dialog(self) -> None:
        if self.available_release is None:
            return
        if self.update_dialog is not None and self.update_dialog.window.winfo_exists():
            self.update_dialog.window.lift()
            self.update_dialog.window.focus_set()
            return
        self.update_dialog = UpdateDialog(self, self.available_release)

    def show_about(self) -> None:
        if self.about_dialog is not None and self.about_dialog.window.winfo_exists():
            self.about_dialog.window.lift()
            self.about_dialog.window.focus_set()
            return
        self.about_dialog = AboutDialog(self)

    def on_close(self) -> None:
        if self.converting and not messagebox.askyesno(APP_TITLE, t("msg_close_converting"), parent=self.root):
            return
        self.shutdown()

    def shutdown(self) -> None:
        self._stop_playback()
        self.cancel_event.set()
        self._save_settings()
        self.notifier.remove()
        self.taskbar.clear()
        self.root.destroy()


def main() -> None:
    args = sys.argv[1:]
    updated = len(args) >= 2 and args[0] == AFTER_UPDATE_FLAG
    if updated:  # start po aktualizacji: stary plik programu usuwamy, gdy tylko poprzedni proces się zakończy
        threading.Thread(target=remove_leftover, args=(Path(args[1]),), daemon=True).start()
        args = args[2:]
    enable_high_dpi()
    root, dnd_enabled = create_root()
    app = App(root, dnd_enabled)
    if updated:
        app.status_var.set(t("status_updated", version=__version__))
    if args:  # np. pliki upuszczone na run.bat
        app.add_paths(args)
    root.mainloop()
