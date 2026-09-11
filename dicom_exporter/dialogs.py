"""Okna dialogowe: „O programie”, podsumowanie konwersji, aktualizacja oraz wybór serii z płyty (DICOMDIR)."""

from __future__ import annotations

import os
import threading
import tkinter as tk
import webbrowser
from pathlib import Path
from tkinter import messagebox, ttk
from typing import TYPE_CHECKING

from PIL import ImageTk

from . import COPYRIGHT_YEAR, GITHUB_URL, PROJECT_URL, __author__, __email__, __version__
from . import shellmenu, updates
from .about import capabilities, medical_note, privacy_note, shortcuts
from .converter import FileResult, natural_key
from .dicominfo import DirPatient, format_size
from .i18n import plural, t
from .widgets import APP_TITLE, link_label, set_enabled, set_title_bar_theme, style_name
from .winshell import open_path, reveal_in_explorer

if TYPE_CHECKING:
    from .gui import App


def show_dialog(window: tk.Toplevel, app: App, focus_widget: tk.Widget) -> tk.Misc | None:
    """Wyśrodkowuje okno nad aplikacją, dopasowuje pasek tytułu do motywu i czyni je modalnym.

    Zwraca okno, które było modalne wcześniej (np. „O programie”) – `close_dialog` przywraca mu tę rolę."""
    root = app.root
    previous = root.grab_current()
    window.update_idletasks()
    x = root.winfo_rootx() + (root.winfo_width() - window.winfo_reqwidth()) // 2
    y = root.winfo_rooty() + (root.winfo_height() - window.winfo_reqheight()) // 3
    window.geometry(f"+{max(0, x)}+{max(0, y)}")
    window.deiconify()
    set_title_bar_theme(window, app.dark_var.get(), refresh=True)
    focus_widget.focus_set()
    window.grab_set()
    return previous


def close_dialog(window: tk.Toplevel, previous: tk.Misc | None) -> None:
    window.grab_release()
    window.destroy()
    try:
        if previous is not None and previous.winfo_exists():
            previous.grab_set()
            previous.focus_set()
    except tk.TclError:
        pass


def icon_button(app: App, parent, text: str, icon: str, command, style: str = "TButton", color: str = "fg") -> ttk.Button:
    button = ttk.Button(parent, text=text, command=command, style=style_name(style), compound="left")
    normal = app.icons.get(icon, app.palette[color], 16, gap=6)
    disabled = app.icons.get(icon, app.palette["disabled"], 16, gap=6)
    if normal is not None and disabled is not None:
        button.configure(image=(str(normal), "disabled", str(disabled)))
    return button


def format_duration(seconds: float) -> str:
    total = max(0, round(seconds))
    if total < 60:
        return t("duration_seconds", seconds=total)
    minutes, secs = divmod(total, 60)
    if minutes < 60:
        return t("duration_minutes", minutes=minutes, seconds=secs)
    hours, minutes = divmod(minutes, 60)
    return t("duration_hours", hours=hours, minutes=minutes)


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
        self.check_link: ttk.Label | None = None

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
        self.previous_grab = show_dialog(window, app, close_button)

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
        if PROJECT_URL:
            rows.append(
                (t("about_project"), link_label(tab, PROJECT_URL.removeprefix("https://"), lambda: webbrowser.open(PROJECT_URL)))
            )
        row = self._rows(tab, rows)
        link_label(tab, t("about_tour"), self._start_tour).grid(row=row, column=0, columnspan=2, sticky="w", pady=(px(10), 0))
        row += 1
        updates_row = ttk.Frame(tab)
        updates_row.grid(row=row, column=0, columnspan=2, sticky="ew", pady=(px(10), 0))
        ttk.Checkbutton(
            updates_row,
            text=t("switch_check_updates"),
            variable=self.app.check_updates_var,
            style=style_name("Switch.TCheckbutton"),
            command=self.app._save_settings,
        ).pack(side="left")
        self.check_link = link_label(updates_row, t("update_check_now"), self._check_now, small=True)
        self.check_link.pack(side="left", padx=(px(12), 0))
        row += 1
        if shellmenu.IS_WINDOWS:
            self.context_menu_var = tk.BooleanVar(value=shellmenu.is_registered())
            ttk.Checkbutton(
                tab,
                text=t("switch_context_menu"),
                variable=self.context_menu_var,
                style=style_name("Switch.TCheckbutton"),
                command=self._toggle_context_menu,
            ).grid(row=row, column=0, columnspan=2, sticky="w", pady=(px(6), 0))
            ttk.Label(tab, text=t("context_menu_hint"), style="Caption.TLabel", wraplength=self.wrap, justify="left").grid(
                row=row + 1, column=0, columnspan=2, sticky="w", padx=(px(48), 0)
            )
            row += 2
        for title, text in ((t("about_privacy"), privacy_note()), (t("about_disclaimer"), medical_note())):
            ttk.Label(tab, text=title, style="Section.TLabel").grid(
                row=row, column=0, columnspan=2, sticky="w", pady=(px(14), px(2))
            )
            ttk.Label(tab, text=text, style="Caption.TLabel", wraplength=self.wrap, justify="left").grid(
                row=row + 1, column=0, columnspan=2, sticky="w"
            )
            row += 2

    def _start_tour(self) -> None:
        self.close()
        self.app.root.after(200, self.app.start_tour)  # po zamknięciu okna, żeby nie trafiło do obrazu przewodnika

    def _check_now(self) -> None:
        if self.check_link is None or str(self.check_link.cget("text")) == t("update_checking"):
            return
        self.check_link.configure(text=t("update_checking"))
        self.app.check_updates_now()

    def check_finished(self) -> None:
        if self.check_link is not None and self.check_link.winfo_exists():
            self.check_link.configure(text=t("update_check_now"))

    def _toggle_context_menu(self) -> None:
        try:
            if self.context_menu_var.get():
                shellmenu.register()
            else:
                shellmenu.unregister()
        except OSError as exc:
            self.context_menu_var.set(shellmenu.is_registered())
            messagebox.showerror(APP_TITLE, t("context_menu_error", error=exc), parent=self.window)

    def _features_tab(self, tab: ttk.Frame) -> None:
        self._rows(tab, capabilities())

    def _shortcuts_tab(self, tab: ttk.Frame) -> None:
        self._rows(tab, shortcuts(), key_style="Section.TLabel")

    def close(self) -> None:
        close_dialog(self.window, self.previous_grab)


class SummaryDialog:
    """Podsumowanie po konwersji: ile plików się udało i które mają błędy (z opisem błędu)."""

    MAX_VISIBLE_ROWS = 8

    def __init__(
        self,
        app: App,
        results: list[FileResult],
        total: int,
        images: int,
        elapsed: float,
        output_dir: Path | None,
        cancelled: bool,
    ) -> None:
        self.app = app
        root, px, palette = app.root, app.px, app.palette
        self.failed = sorted((result for result in results if not result.ok), key=lambda r: natural_key(str(r.item.path)))
        self.output_dir = output_dir
        converted = len(results) - len(self.failed)
        not_converted = max(0, total - len(results))

        if cancelled:
            title, icon, color = t("summary_title_cancelled"), "info", "muted"
        elif self.failed:
            title, icon, color = t("summary_title_errors"), "warning", "error"
        else:
            title, icon, color = t("summary_title_ok"), "success", "success"

        self.window = window = tk.Toplevel(root)
        window.withdraw()
        window.title(title)
        window.transient(root)
        window.resizable(bool(self.failed), bool(self.failed))

        frame = ttk.Frame(window, padding=(px(24), px(22), px(24), px(18)))
        frame.pack(fill="both", expand=True)
        frame.columnconfigure(1, weight=1)

        self.icon = app.icons.get(icon, palette[color], 40)
        if self.icon is not None:
            ttk.Label(frame, image=self.icon).grid(row=0, column=0, rowspan=2, sticky="nw", padx=(0, px(16)))
        ttk.Label(frame, text=title, style="Title.TLabel").grid(row=0, column=1, sticky="sw")
        ttk.Label(
            frame,
            text=t("summary_saved", images=plural(images, "image"), time=format_duration(elapsed)),
            style="Caption.TLabel",
        ).grid(row=1, column=1, sticky="nw")

        tiles = ttk.Frame(frame)
        tiles.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(px(18), 0))
        stats = [
            (converted, "summary_ok", "StatOk.TLabel" if converted else "StatMuted.TLabel"),
            (len(self.failed), "summary_failed", "StatError.TLabel" if self.failed else "StatMuted.TLabel"),
        ]
        if not_converted:
            stats.append((not_converted, "summary_cancelled", "StatMuted.TLabel"))
        for column, (count, label, style) in enumerate(stats):
            tiles.columnconfigure(column, weight=1, uniform="tile", minsize=px(150))
            tile = ttk.Frame(tiles, style=style_name("Card.TFrame"), padding=(px(16), px(10), px(16), px(12)))
            tile.grid(row=0, column=column, sticky="ew", padx=(0 if column == 0 else px(10), 0))
            ttk.Label(tile, text=str(count), style=style).pack(anchor="w")
            ttk.Label(tile, text=t(label), style="Caption.TLabel").pack(anchor="w")

        self.detail_var = tk.StringVar(value=t("summary_hint"))
        self.tree: ttk.Treeview | None = None
        if self.failed:
            frame.rowconfigure(4, weight=1)
            ttk.Label(frame, text=t("summary_errors_title"), style="Section.TLabel").grid(
                row=3, column=0, columnspan=2, sticky="w", pady=(px(20), px(6))
            )
            tree_frame = ttk.Frame(frame)
            tree_frame.grid(row=4, column=0, columnspan=2, sticky="nsew")
            tree_frame.columnconfigure(0, weight=1)
            tree_frame.rowconfigure(0, weight=1)
            self.tree = ttk.Treeview(
                tree_frame,
                columns=("file", "error"),
                show="headings",
                selectmode="browse",
                height=min(self.MAX_VISIBLE_ROWS, max(3, len(self.failed))),
            )
            self.tree.heading("file", text=t("col_name"), anchor="w")
            self.tree.heading("error", text=t("col_error"), anchor="w")
            self.tree.column("file", width=px(210), stretch=False)
            self.tree.column("error", width=px(400), stretch=True)
            self.tree.grid(row=0, column=0, sticky="nsew")
            if len(self.failed) > self.MAX_VISIBLE_ROWS:
                scrollbar = ttk.Scrollbar(tree_frame, orient="vertical", command=self.tree.yview)
                self.tree.configure(yscrollcommand=scrollbar.set)
                scrollbar.grid(row=0, column=1, sticky="ns", padx=(px(4), 0))
            self.paths: dict[str, FileResult] = {}
            for result in self.failed:
                iid = self.tree.insert("", "end", values=(result.item.path.name, result.error or ""))
                self.paths[iid] = result
            self.tree.bind("<<TreeviewSelect>>", self._on_select)
            self.tree.bind("<Double-1>", self._reveal)
            ttk.Label(
                frame, textvariable=self.detail_var, style="Caption.TLabel", wraplength=px(620), justify="left"
            ).grid(row=5, column=0, columnspan=2, sticky="w", pady=(px(6), 0))
        elif not cancelled:
            ttk.Label(frame, text=t("summary_all_ok"), style="Value.TLabel").grid(
                row=3, column=0, columnspan=2, sticky="w", pady=(px(18), 0)
            )

        buttons = ttk.Frame(frame)
        buttons.grid(row=6, column=0, columnspan=2, sticky="ew", pady=(px(18), 0))
        if self.failed:
            icon_button(app, buttons, t("btn_copy_errors"), "copy", self.copy_errors).pack(side="left")
        close_button = ttk.Button(buttons, text=t("btn_close"), style=style_name("Accent.TButton"), command=self.close)
        close_button.pack(side="right", ipadx=px(14))
        if output_dir is not None and images:
            icon_button(app, buttons, t("btn_open_output"), "open", self.open_output).pack(side="right", padx=(0, px(8)))

        window.bind("<Escape>", lambda _event: self.close())
        window.bind("<Return>", lambda _event: self.close())
        if self.failed:
            window.bind("<Control-c>", lambda _event: self.copy_errors())
        window.protocol("WM_DELETE_WINDOW", self.close)
        self.previous_grab = show_dialog(window, app, close_button)
        if self.failed:
            window.minsize(window.winfo_reqwidth(), window.winfo_reqheight())

    def _selected(self) -> FileResult | None:
        if self.tree is None:
            return None
        selection = self.tree.selection()
        return self.paths.get(selection[0]) if selection else None

    def _on_select(self, _event=None) -> None:
        result = self._selected()
        if result is not None:
            self.detail_var.set(f"{result.item.path}\n{result.error or ''}")

    def _reveal(self, _event=None) -> None:
        result = self._selected()
        if result is not None and result.item.path.exists():
            reveal_in_explorer(result.item.path)

    def copy_errors(self) -> None:
        lines = [f"{result.item.path}\t{result.error or ''}" for result in self.failed]
        self.window.clipboard_clear()
        self.window.clipboard_append("\n".join(lines))
        self.detail_var.set(t("summary_copied"))

    def open_output(self) -> None:
        if self.output_dir is not None and self.output_dir.is_dir():
            open_path(self.output_dir)

    def close(self) -> None:
        close_dialog(self.window, self.previous_grab)


class UpdateDialog:
    """Nowa wersja z GitHuba: opis zmian i aktualizacja jednym kliknięciem (pojedynczy plik .exe)."""

    def __init__(self, app: App, release: updates.Release) -> None:
        self.app = app
        self.release = release
        self.executable = updates.running_executable()
        self.self_update = updates.can_self_update(release)
        self.cancel_event = threading.Event()
        self.progress_state = (0, release.asset_size)
        self.outcome: tuple | None = None
        self.busy = False
        self.was_registered = False
        root, px, palette = app.root, app.px, app.palette

        self.window = window = tk.Toplevel(root)
        window.withdraw()
        window.title(t("update_title"))
        window.resizable(False, False)
        window.transient(root)

        frame = ttk.Frame(window, padding=(px(24), px(22), px(24), px(18)))
        frame.pack(fill="both", expand=True)
        frame.columnconfigure(1, weight=1)

        self.badge = ImageTk.PhotoImage(app.icons.badge(px(56)), master=root)
        ttk.Label(frame, image=self.badge).grid(row=0, column=0, rowspan=2, sticky="nw", padx=(0, px(16)))
        ttk.Label(frame, text=t("update_heading", version=release.version), style="Title.TLabel").grid(
            row=0, column=1, sticky="sw"
        )
        ttk.Label(frame, text=t("update_current", version=__version__), style="Caption.TLabel").grid(
            row=1, column=1, sticky="nw"
        )

        notes = updates.release_notes_text(release.notes)
        if notes:
            ttk.Label(frame, text=t("update_notes"), style="Section.TLabel").grid(
                row=2, column=0, columnspan=2, sticky="w", pady=(px(18), px(6))
            )
            text = tk.Text(
                frame,
                height=min(10, max(3, notes.count("\n") + 1)),
                width=58,
                wrap="word",
                font="SunValleyBodyFont",
                relief="flat",
                borderwidth=0,
                highlightthickness=1,
                padx=px(10),
                pady=px(8),
                background=palette["bg"],
                foreground=palette["fg"],
                highlightbackground=palette["border"],
                highlightcolor=palette["border"],
                cursor="arrow",
            )
            text.insert("1.0", notes)
            text.configure(state="disabled")
            text.grid(row=3, column=0, columnspan=2, sticky="ew")
        link_label(frame, t("update_release_page"), lambda: webbrowser.open(release.url), small=True).grid(
            row=4, column=0, columnspan=2, sticky="w", pady=(px(8), 0)
        )

        self.message = ttk.Label(frame, style="Caption.TLabel", wraplength=px(480), justify="left")
        self.message.grid(row=5, column=0, columnspan=2, sticky="w", pady=(px(14), 0))
        self.progress = ttk.Progressbar(frame, mode="determinate", maximum=1000)
        self.progress.grid(row=6, column=0, columnspan=2, sticky="ew", pady=(px(10), 0))
        self.progress.grid_remove()

        buttons = ttk.Frame(frame)
        buttons.grid(row=7, column=0, columnspan=2, sticky="ew", pady=(px(18), 0))
        self.primary = icon_button(
            app, buttons, "", "download", self._primary, style="Accent.TButton", color="on_accent"
        )
        self.primary.pack(side="right", ipadx=px(10))
        self.secondary = ttk.Button(buttons, command=self._secondary)
        self.secondary.pack(side="right", padx=(0, px(8)))
        self._set_idle()

        window.bind("<Escape>", lambda _event: self._secondary())
        window.protocol("WM_DELETE_WINDOW", self._secondary)
        self.previous_grab = show_dialog(window, app, self.primary)

    def _set_message(self, text: str, error: bool = False) -> None:
        self.message.configure(text=text, style="Error.TLabel" if error else "Caption.TLabel")

    def _set_idle(self, retry: bool = False) -> None:
        self.busy = False
        self.progress.grid_remove()
        if self.self_update:
            self.primary.configure(text=t("btn_update_retry") if retry else t("btn_update_now"))
            set_enabled(self.primary, not self.app.converting)
            self._set_message(t("update_wait_conversion") if self.app.converting else t("update_explain"))
        else:
            self.primary.configure(text=t("btn_download_page"))
            self._set_message(t("update_manual"))
        self.secondary.configure(text=t("btn_update_later"))
        set_enabled(self.secondary, True)

    def _primary(self) -> None:
        if self.busy:
            return
        if not self.self_update or self.executable is None:
            webbrowser.open(self.release.url)
            self.close()
            return
        if self.app.converting:
            self._set_message(t("update_wait_conversion"))
            return
        self.busy = True
        self.outcome = None
        self.cancel_event.clear()
        self.progress_state = (0, self.release.asset_size)
        self.was_registered = shellmenu.is_registered()
        set_enabled(self.primary, False)
        self.secondary.configure(text=t("btn_cancel"))
        self.progress.configure(value=0)
        self.progress.grid()
        threading.Thread(target=self._worker, daemon=True).start()
        self._poll()

    def _worker(self) -> None:
        assert self.executable is not None
        try:
            downloaded = updates.download(
                self.release, self.executable.parent, progress=self._on_progress, cancel=self.cancel_event
            )
            if self.cancel_event.is_set():
                downloaded.unlink(missing_ok=True)
                raise updates.UpdateCancelled
            self.outcome = ("installed", *updates.install(downloaded, self.executable, self.release.version))
        except updates.UpdateCancelled:
            self.outcome = ("cancelled",)
        except Exception as exc:  # błąd pokazujemy w oknie – program działa dalej w dotychczasowej wersji
            self.outcome = ("error", str(exc))

    def _on_progress(self, done: int, total: int) -> None:
        self.progress_state = (done, total)

    def _poll(self) -> None:
        if not self.window.winfo_exists():
            return
        outcome = self.outcome
        if outcome is None:
            done, total = self.progress_state
            if total:
                self.progress.configure(value=min(1000, done * 1000 // total))
                text = t("update_downloading", done=format_size(done), total=format_size(total))
            else:
                text = t("update_downloading_unknown", done=format_size(done))
            if not self.cancel_event.is_set():
                self._set_message(text)
            self.window.after(100, self._poll)
            return
        kind = outcome[0]
        if kind == "installed":
            self._restart(outcome[1], outcome[2])
        elif kind == "cancelled":
            self._set_idle()
            self._set_message(t("update_cancelled"))
        else:
            self._set_idle(retry=True)
            self._set_message(t("update_failed", error=outcome[1]), error=True)

    def _restart(self, executable: Path, leftover: Path) -> None:
        self.progress.configure(value=1000)
        self._set_message(t("update_restarting"))
        set_enabled(self.secondary, False)
        if self.was_registered:  # polecenia w menu Eksploratora mają wskazywać nowy plik programu
            try:
                shellmenu.register(executable)
            except OSError:
                pass
        self.app._save_settings()  # nowa wersja wczyta ustawienia zaraz po starcie
        try:
            updates.restart(executable, leftover)
        except updates.UpdateError as exc:
            self.busy = False
            self.secondary.configure(text=t("btn_close"))
            set_enabled(self.secondary, True)
            self._set_message(t("update_failed", error=exc), error=True)
            return
        self.window.after(300, self.app.shutdown)

    def _secondary(self) -> None:
        if self.busy:
            if self.outcome is None:
                self.cancel_event.set()
                set_enabled(self.secondary, False)
            return
        self.close()

    def close(self) -> None:
        self.cancel_event.set()
        close_dialog(self.window, self.previous_grab)


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
        self.previous_grab = show_dialog(window, app, self.tree)

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
        close_dialog(self.window, self.previous_grab)
