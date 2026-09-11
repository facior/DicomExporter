"""Okna dialogowe: „O programie” oraz wybór pacjentów, badań i serii z płyty (DICOMDIR)."""

from __future__ import annotations

import os
import tkinter as tk
import webbrowser
from pathlib import Path
from tkinter import ttk
from typing import TYPE_CHECKING

from PIL import ImageTk

from . import COPYRIGHT_YEAR, GITHUB_URL, __author__, __email__, __version__
from .about import capabilities, medical_note, privacy_note, shortcuts
from .converter import natural_key
from .dicominfo import DirPatient
from .i18n import plural, t
from .widgets import APP_TITLE, link_label, set_enabled, set_title_bar_theme, style_name

if TYPE_CHECKING:
    from .gui import App


def show_dialog(window: tk.Toplevel, app: App, focus_widget: tk.Widget) -> None:
    """Wyśrodkowuje okno nad aplikacją, dopasowuje pasek tytułu do motywu i czyni je modalnym."""
    root = app.root
    window.update_idletasks()
    x = root.winfo_rootx() + (root.winfo_width() - window.winfo_reqwidth()) // 2
    y = root.winfo_rooty() + (root.winfo_height() - window.winfo_reqheight()) // 3
    window.geometry(f"+{max(0, x)}+{max(0, y)}")
    window.deiconify()
    set_title_bar_theme(window, app.dark_var.get(), refresh=True)
    focus_widget.focus_set()
    window.grab_set()


class AboutDialog:
    """Okno „O programie”: autor, możliwości programu i skróty klawiszowe."""

    def __init__(self, app: App) -> None:
        self.app = app
        root = app.root
        px = app.px
        self.window = window = tk.Toplevel(root)
        window.withdraw()
        window.title(t("about_title", app=APP_TITLE))
        window.resizable(False, False)
        window.transient(root)
        self.wrap = px(460)

        frame = ttk.Frame(window, padding=(px(24), px(22), px(24), px(18)))
        frame.pack(fill="both", expand=True)
        frame.columnconfigure(1, weight=1)

        self.badge = ImageTk.PhotoImage(app.icons.badge(px(64)), master=root)
        ttk.Label(frame, image=self.badge).grid(row=0, column=0, rowspan=3, sticky="nw", padx=(0, px(18)))
        ttk.Label(frame, text=APP_TITLE, style="Title.TLabel").grid(row=0, column=1, sticky="w")
        ttk.Label(
            frame, text=f"{t('version', version=__version__)} · © {COPYRIGHT_YEAR} {__author__}", style="Caption.TLabel"
        ).grid(row=1, column=1, sticky="w")
        ttk.Label(
            frame, text=t("about_description"), style="Value.TLabel", wraplength=px(370), justify="left"
        ).grid(row=2, column=1, sticky="w", pady=(px(6), 0))

        self.notebook = ttk.Notebook(frame)
        self.notebook.grid(row=3, column=0, columnspan=2, sticky="nsew", pady=(px(18), 0))
        self.notebook.enable_traversal()  # Ctrl+Tab przełącza karty
        for title, build in (
            (t("tab_general"), self._general_tab),
            (t("tab_features"), self._features_tab),
            (t("tab_shortcuts"), self._shortcuts_tab),
        ):
            tab = ttk.Frame(self.notebook, padding=(px(16), px(14)))
            tab.columnconfigure(1, weight=1)
            build(tab)
            self.notebook.add(tab, text=title)

        close_button = ttk.Button(frame, text=t("btn_close"), style=style_name("Accent.TButton"), command=self.close)
        close_button.grid(row=4, column=0, columnspan=2, sticky="e", pady=(px(16), 0), ipadx=px(14))

        window.bind("<Escape>", lambda _event: self.close())
        window.bind("<Return>", lambda _event: self.close())
        window.protocol("WM_DELETE_WINDOW", self.close)
        show_dialog(window, app, close_button)

    def _rows(self, tab: ttk.Frame, rows, start: int = 0, key_style: str = "Caption.TLabel") -> int:
        """Wiersze „etykieta – wartość”; wartością może być tekst albo gotowy widżet."""
        px = self.app.px
        for offset, (key, value) in enumerate(rows):
            row = start + offset
            ttk.Label(tab, text=key, style=key_style).grid(row=row, column=0, sticky="nw", padx=(0, px(16)), pady=px(4))
            if not isinstance(value, tk.Widget):
                value = ttk.Label(tab, text=value, style="Value.TLabel", wraplength=self.wrap - px(170), justify="left")
            value.grid(row=row, column=1, sticky="w", pady=px(4))
        return start + len(rows)

    def _general_tab(self, tab: ttk.Frame) -> None:
        px = self.app.px
        rows: list[tuple[str, tk.Widget]] = [
            (t("about_author"), ttk.Label(tab, text=__author__, style="Section.TLabel")),
            (t("about_email"), link_label(tab, __email__, lambda: webbrowser.open(f"mailto:{__email__}"))),
        ]
        if GITHUB_URL:
            rows.append(("GitHub", link_label(tab, GITHUB_URL.removeprefix("https://"), lambda: webbrowser.open(GITHUB_URL))))
        row = self._rows(tab, rows)
        ttk.Checkbutton(
            tab,
            text=t("switch_check_updates"),
            variable=self.app.check_updates_var,
            style=style_name("Switch.TCheckbutton"),
            command=self.app._save_settings,
        ).grid(row=row, column=0, columnspan=2, sticky="w", pady=(px(10), 0))
        row += 1
        for title, text in ((t("about_privacy"), privacy_note()), (t("about_disclaimer"), medical_note())):
            ttk.Label(tab, text=title, style="Section.TLabel").grid(
                row=row, column=0, columnspan=2, sticky="w", pady=(px(14), px(2))
            )
            ttk.Label(tab, text=text, style="Caption.TLabel", wraplength=self.wrap, justify="left").grid(
                row=row + 1, column=0, columnspan=2, sticky="w"
            )
            row += 2

    def _features_tab(self, tab: ttk.Frame) -> None:
        self._rows(tab, capabilities())

    def _shortcuts_tab(self, tab: ttk.Frame) -> None:
        self._rows(tab, shortcuts(), key_style="Section.TLabel")

    def close(self) -> None:
        self.window.grab_release()
        self.window.destroy()


def _format_date(value: str) -> str:
    value = value.strip()
    return f"{value[:4]}-{value[4:6]}-{value[6:8]}" if len(value) == 8 and value.isdigit() else value


class DicomdirDialog:
    """Wybór pacjentów, badań lub serii z płyty z plikiem DICOMDIR."""

    def __init__(self, app: App, path: Path, patients: list[DirPatient], on_add) -> None:
        self.app = app
        self.on_add = on_add
        root = app.root
        px = app.px
        self.window = window = tk.Toplevel(root)
        window.withdraw()
        window.title(t("dicomdir_title"))
        window.transient(root)
        window.minsize(px(660), px(440))

        frame = ttk.Frame(window, padding=px(20))
        frame.pack(fill="both", expand=True)
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(2, weight=1)
        ttk.Label(frame, text=t("dicomdir_heading"), style="Title.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(
            frame, text=t("dicomdir_subtitle", path=path), style="Caption.TLabel", wraplength=px(620), justify="left"
        ).grid(row=1, column=0, sticky="w", pady=(px(2), px(12)))

        tree_frame = ttk.Frame(frame)
        tree_frame.grid(row=2, column=0, sticky="nsew")
        tree_frame.columnconfigure(0, weight=1)
        tree_frame.rowconfigure(0, weight=1)
        self.tree = ttk.Treeview(
            tree_frame, columns=("modality", "images", "date"), show="tree headings", selectmode="extended", height=14
        )
        self.tree.heading("#0", text=t("dicomdir_col_item"), anchor="w")
        self.tree.column("#0", width=px(340), stretch=True)
        for column, label, width in (
            ("modality", t("col_modality"), 100),
            ("images", t("dicomdir_col_images"), 80),
            ("date", t("dicomdir_col_date"), 100),
        ):
            self.tree.heading(column, text=label)
            self.tree.column(column, width=px(width), anchor="center", stretch=False)
        scrollbar = ttk.Scrollbar(tree_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns", padx=(px(4), 0))

        self.files: dict[str, list[Path]] = {}
        patient_ids = []
        for patient in patients:
            studies = list(patient.studies.values())
            patient_files = [file for study in studies for series in study.series.values() for file in series.files]
            name = patient.name.replace("^", " ").strip() or t("dicomdir_unknown_patient")
            label = f"{name}  ({patient.patient_id})" if patient.patient_id else name
            patient_iid = self.tree.insert("", "end", text=label, values=("", len(patient_files), ""), open=True)
            self.files[patient_iid] = patient_files
            patient_ids.append(patient_iid)
            for study in studies:
                study_files = [file for series in study.series.values() for file in series.files]
                modalities = ", ".join(sorted({series.modality for series in study.series.values() if series.modality}))
                study_iid = self.tree.insert(
                    patient_iid,
                    "end",
                    text=study.description or t("dicomdir_study"),
                    values=(modalities, len(study_files), _format_date(study.date)),
                    open=True,
                )
                self.files[study_iid] = study_files
                for series in sorted(study.series.values(), key=lambda item: natural_key(item.number)):
                    title = f"{t('dicomdir_series')} {series.number}".strip()
                    if series.description:
                        title = f"{title} · {series.description}"
                    series_iid = self.tree.insert(study_iid, "end", text=title, values=(series.modality, len(series.files), ""))
                    self.files[series_iid] = series.files

        buttons = ttk.Frame(frame)
        buttons.grid(row=3, column=0, sticky="ew", pady=(px(14), 0))
        ttk.Button(buttons, text=t("btn_select_all"), command=lambda: self.tree.selection_set(patient_ids)).pack(side="left")
        ttk.Button(buttons, text=t("btn_select_none"), command=lambda: self.tree.selection_set([])).pack(
            side="left", padx=(px(8), 0)
        )
        self.selection_label = ttk.Label(buttons, style="Caption.TLabel")
        self.selection_label.pack(side="left", padx=(px(14), 0))
        self.add_button = ttk.Button(
            buttons, text=t("btn_add_selected"), style=style_name("Accent.TButton"), command=self._add
        )
        self.add_button.pack(side="right", ipadx=px(10))
        ttk.Button(buttons, text=t("btn_cancel"), command=self.close).pack(side="right", padx=(0, px(8)))

        self.tree.bind("<<TreeviewSelect>>", lambda _event: self._update_count())
        window.bind("<Escape>", lambda _event: self.close())
        window.bind("<Return>", lambda _event: self._add())
        window.protocol("WM_DELETE_WINDOW", self.close)
        self.tree.selection_set(patient_ids)
        self._update_count()
        show_dialog(window, app, self.tree)

    def _selected_files(self) -> list[Path]:
        unique: dict[str, Path] = {}
        for iid in self.tree.selection():
            for path in self.files.get(iid, []):
                unique.setdefault(os.path.normcase(str(path)), path)
        return list(unique.values())

    def _update_count(self) -> None:
        count = len(self._selected_files())
        self.selection_label.configure(text=t("dicomdir_selected", files=plural(count, "file")))
        set_enabled(self.add_button, count > 0)

    def _add(self) -> None:
        files = self._selected_files()
        if not files:
            return
        self.close()
        self.on_add(files)

    def close(self) -> None:
        self.window.grab_release()
        self.window.destroy()
