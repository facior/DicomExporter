"""Wspólne elementy interfejsu: motyw, czcionki, ikony i pomocnicze widżety."""

from __future__ import annotations

import os
import sys
import time
import tkinter as tk
from pathlib import Path
from tkinter import ttk
from tkinter import font as tkfont

from PIL import Image, ImageDraw, ImageFont, ImageGrab, ImageTk

try:
    import sv_ttk
except ImportError:  # bez motywu aplikacja działa na standardowym wyglądzie ttk
    sv_ttk = None

try:
    from tkinterdnd2 import DND_FILES, TkinterDnD
except ImportError:  # przeciąganie plików jest opcjonalne
    DND_FILES = TkinterDnD = None

APP_TITLE = "DICOM Exporter"
BRAND = "#005fb8"
PREVIEW_BG = "#0f1114"
PREVIEW_FG = "#9aa0a6"
PREVIEW_ERROR = "#ff99a4"

# Kolory uzupełniające motyw Sun Valley (kontrast tekstu >= 4.5:1 w obu wariantach).
PALETTES = {
    "light": {
        "bg": "#fafafa",
        "fg": "#1c1c1c",
        "muted": "#5c5c5c",
        "disabled": "#a0a0a0",
        "border": "#b9c0ca",
        "accent": "#005fb8",
        "accent_soft": "#e5effa",
        "on_accent": "#ffffff",
        "success": "#0f7b0f",
        "error": "#c42b1c",
    },
    "dark": {
        "bg": "#1c1c1c",
        "fg": "#fafafa",
        "muted": "#ababab",
        "disabled": "#5d5d5d",
        "border": "#4c4c4c",
        "accent": "#57c8ff",
        "accent_soft": "#1d2f3b",
        "on_accent": "#000000",
        "success": "#6ccb5f",
        "error": "#ff99a4",
    },
}

# Znaki z czcionki Segoe MDL2 Assets / Segoe Fluent Icons
GLYPHS = {
    "app": "\uEB9F",
    "add_file": "\uE8E5",
    "add_folder": "\uE8F4",
    "disc": "\uE8CE",
    "remove": "\uE74D",
    "clear": "\uE894",
    "folder": "\uE838",
    "open": "\uE8A7",
    "convert": "\uE768",
    "cancel": "\uE711",
    "upload": "\uE898",
    "image": "\uEB9F",
    "error": "\uE783",
    "info": "\uE946",
    "zoom_in": "\uE8A3",
    "zoom_out": "\uE71F",
    "fit": "\uE740",
    "previous": "\uE76B",
    "next": "\uE76C",
    "search": "\uE721",
    "language": "\uE774",
    "reset": "\uE72C",
    "play": "\uE768",
    "pause": "\uE769",
    "save": "\uE74E",
    "success": "\uE930",
    "warning": "\uE7BA",
    "copy": "\uE8C8",
    "download": "\uE896",
}

# Nazwane czcionki: (rozmiar w pikselach przy 100%, pogrubienie, podkreślenie)
FONT_SPECS = {
    "SunValleyCaptionFont": (-12, False, False),
    "SunValleyBodyFont": (-14, False, False),
    "SunValleyBodyStrongFont": (-14, True, False),
    "SunValleySubtitleFont": (-20, True, False),
    "DicomExporterStatFont": (-30, True, False),
    "DicomExporterLinkFont": (-14, False, True),
    "DicomExporterCaptionLinkFont": (-12, False, True),
}

FALLBACK_STYLES = {
    "Card.TFrame": "TFrame",
    "Accent.TButton": "TButton",
    "Switch.TCheckbutton": "TCheckbutton",
    "Toggle.TButton": "Toolbutton",
}


def style_name(name: str) -> str:
    return name if sv_ttk is not None else FALLBACK_STYLES.get(name, name)


def set_enabled(widget: ttk.Widget, enabled: bool) -> None:
    widget.state(["!disabled"] if enabled else ["disabled"])


def ellipsize(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    head = (limit - 1) * 2 // 3
    return f"{text[:head]}…{text[-(limit - 1 - head):]}"


def system_prefers_dark() -> bool:
    if sys.platform != "win32":
        return False
    try:
        import winreg

        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize"
        ) as key:
            return winreg.QueryValueEx(key, "AppsUseLightTheme")[0] == 0
    except OSError:
        return False


def find_icon_font() -> Path | None:
    fonts = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
    for name in ("SegoeIcons.ttf", "segmdl2.ttf"):
        if (fonts / name).is_file():
            return fonts / name
    return None


def draw_centered_glyph(draw: ImageDraw.ImageDraw, glyph: str, font, width: int, height: int, fill: str) -> None:
    left, top, right, bottom = draw.textbbox((0, 0), glyph, font=font)
    draw.text(((width - (right - left)) / 2 - left, (height - (bottom - top)) / 2 - top), glyph, font=font, fill=fill)


def setup_fonts(root: tk.Tk, scale: float) -> list[tkfont.Font]:
    """Czcionki motywu: Segoe UI Variable (Windows 11) lub Segoe UI (Windows 10), skalowane z DPI."""
    families = set(tkfont.families(root))
    if "Segoe UI Variable Text" in families:
        regular, strong = "Segoe UI Variable Text", "Segoe UI Variable Text Semibold"
    elif "Segoe UI" in families:
        regular = "Segoe UI"
        strong = "Segoe UI Semibold" if "Segoe UI Semibold" in families else regular
    else:
        regular = strong = tkfont.nametofont("TkDefaultFont", root=root).actual("family")
    existing = set(tkfont.names(root))
    fonts = []
    for name, (size, is_strong, underline) in FONT_SPECS.items():
        options = {
            "family": strong if is_strong else regular,
            "size": round(size * scale),
            "weight": "bold" if is_strong and strong == regular else "normal",
            "underline": underline,
        }
        if name in existing:
            font = tkfont.Font(root=root, name=name, exists=True)
            font.configure(**options)
        else:
            font = tkfont.Font(root=root, name=name, **options)
        fonts.append(font)  # referencje są potrzebne: tkinter usuwa czcionkę po zwolnieniu obiektu
    return fonts


def set_title_bar_theme(window: tk.Tk | tk.Toplevel, dark: bool, refresh: bool = False) -> None:
    """Ciemny/jasny pasek tytułu okna w Windows 10/11."""
    if sys.platform != "win32":
        return
    try:
        import ctypes
        from ctypes import wintypes

        window.update_idletasks()
        user32 = ctypes.windll.user32
        hwnd = wintypes.HWND(user32.GetParent(window.winfo_id()))
        value = ctypes.c_int(1 if dark else 0)
        for attribute in (20, 19):  # DWMWA_USE_IMMERSIVE_DARK_MODE (nowsze i starsze kompilacje)
            if ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, attribute, ctypes.byref(value), ctypes.sizeof(value)) == 0:
                break
        if refresh:
            # Windows 10 przerysowuje pasek tytułu dopiero przy zmianie aktywności okna – symulujemy ją
            # (dawniej: chwilowa zmiana rozmiaru okna, która przeliczała cały układ i powodowała mignięcie).
            active = user32.GetForegroundWindow() == hwnd.value
            user32.SendMessageW(hwnd, 0x0086, int(not active), 0)  # WM_NCACTIVATE
            user32.SendMessageW(hwnd, 0x0086, int(active), 0)
    except (AttributeError, OSError):
        return


# Szybsza zmiana motywu Sun Valley. Oryginalna procedura `configure_colors` przy każdej zmianie ponownie
# konfiguruje styl bazowy „.”, a w Tk każda zmiana stylu przelicza wszystkie widżety (ok. 2,5 ms na widżet).
# Styl bazowy ustawiamy raz dla obu wariantów, a przy zmianie zostaje tylko paleta klasycznych widżetów Tk.
_FAST_THEME_SWITCH_TCL = r"""
namespace eval ::dicom_exporter {}

proc ::dicom_exporter::preset_base_style {theme ns} {
  upvar #0 ${ns}::colors colors
  ttk::style theme settings $theme {
    ttk::style configure . \
      -background $colors(-bg) \
      -foreground $colors(-fg) \
      -troughcolor $colors(-bg) \
      -focuscolor $colors(-selbg) \
      -selectbackground $colors(-selbg) \
      -selectforeground $colors(-selfg) \
      -insertwidth 1 \
      -insertcolor $colors(-fg) \
      -fieldbackground $colors(-bg) \
      -font SunValleyBodyFont \
      -borderwidth 0 \
      -relief flat
    ttk::style map . -foreground [list disabled $colors(-disfg)]
  }
}

::dicom_exporter::preset_base_style sun-valley-light ttk::theme::sv_light
::dicom_exporter::preset_base_style sun-valley-dark ttk::theme::sv_dark

proc configure_colors {} {
  switch -- [ttk::style theme use] {
    sun-valley-dark {set ns ttk::theme::sv_dark}
    sun-valley-light {set ns ttk::theme::sv_light}
    default {return}
  }
  upvar #0 ${ns}::colors colors
  tk_setPalette \
    background $colors(-bg) \
    foreground $colors(-fg) \
    highlightColor $colors(-selbg) \
    selectBackground $colors(-selbg) \
    selectForeground $colors(-selfg) \
    activeBackground $colors(-selbg) \
    activeForeground $colors(-selfg)
}
"""


def optimize_theme_switch(root: tk.Tk) -> None:
    """Zmiana motywu z jednym przeliczeniem układu okna zamiast kilku (patrz _FAST_THEME_SWITCH_TCL)."""
    if sv_ttk is None:
        return
    try:
        if root.tk.call("info", "procs", "configure_colors"):
            root.tk.eval(_FAST_THEME_SWITCH_TCL)
    except tk.TclError:
        pass  # inna wersja motywu – zostaje jego oryginalne, wolniejsze przełączanie


def window_bounds(window: tk.Misc) -> tuple[int, int, int, int] | None:
    """Widoczny prostokąt okna razem z paskiem tytułu (bez niewidocznych ramek do zmiany rozmiaru)."""
    if sys.platform != "win32":
        return None
    try:
        import ctypes
        from ctypes import wintypes

        hwnd = wintypes.HWND(ctypes.windll.user32.GetParent(window.winfo_id()))
        rect = wintypes.RECT()
        # DWMWA_EXTENDED_FRAME_BOUNDS; bez kompozycji DWM – zwykły prostokąt okna
        if ctypes.windll.dwmapi.DwmGetWindowAttribute(hwnd, 9, ctypes.byref(rect), ctypes.sizeof(rect)) != 0:
            if not ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(rect)):
                return None
    except (AttributeError, OSError):
        return None
    if rect.right <= rect.left or rect.bottom <= rect.top:
        return None
    return rect.left, rect.top, rect.right, rect.bottom


def animations_enabled() -> bool:
    """Ustawienie Windows „Pokaż animacje w systemie Windows”; gdy wyłączone, przejścia są natychmiastowe."""
    if sys.platform != "win32":
        return True
    try:
        import ctypes
        from ctypes import wintypes

        value = wintypes.BOOL(True)
        if ctypes.windll.user32.SystemParametersInfoW(0x1042, 0, ctypes.byref(value), 0):  # SPI_GETCLIENTAREAANIMATION
            return bool(value.value)
    except (AttributeError, OSError):
        pass
    return True


def crossfade(root: tk.Tk, change, duration: float = 0.22, hold_ms: int = 30) -> None:
    """Wykonuje `change` pod zrzutem okna, który potem płynnie znika.

    Zmiana motywu przemalowuje okno etapami (widżety ttk, klasyczne widżety Tk, pasek tytułu) – zrzut zasłania
    te etapy, więc widać jedno płynne przejście zamiast migotania. `hold_ms` daje systemowi chwilę na
    narysowanie nowego wyglądu pod zrzutem."""
    previous = getattr(root, "_crossfade_overlay", None)
    if previous is not None and previous.winfo_exists():
        previous.destroy()
    bounds = window_bounds(root) if root.state() in ("normal", "zoomed") else None
    try:
        snapshot = ImageGrab.grab(bounds, all_screens=True) if bounds is not None else None
    except OSError:
        snapshot = None
    if snapshot is None:
        change()
        return

    left, top, right, bottom = bounds
    overlay = tk.Toplevel(root)
    overlay.withdraw()
    overlay.overrideredirect(True)
    overlay.transient(root)
    # Nowo pokazane okno bez aktywacji Windows potrafi umieścić pod oknem programu – zasłona istnieje ułamek
    # sekundy, więc może być „na wierzchu” i jest jawnie podnoszona.
    overlay.attributes("-topmost", True)
    photo = ImageTk.PhotoImage(snapshot, master=root)
    label = tk.Label(overlay, image=photo, borderwidth=0, highlightthickness=0)
    label.image = photo
    label.pack()
    overlay.geometry(f"{right - left}x{bottom - top}+{left}+{top}")
    overlay.deiconify()
    overlay.lift()
    overlay.update()
    root._crossfade_overlay = overlay
    try:
        change()
    finally:
        root.update_idletasks()

    animate = animations_enabled()
    started: list[float] = []

    def step() -> None:
        if not overlay.winfo_exists():
            return
        now = time.perf_counter()
        if not started:
            started.append(now)
        progress = (now - started[0]) / duration
        if not animate or progress >= 1:
            overlay.destroy()
            return
        overlay.attributes("-alpha", 1 - progress * progress * (3 - 2 * progress))  # łagodny start i koniec
        overlay.after(12, step)

    overlay.after(hold_ms, step)


def rounded_rect(canvas: tk.Canvas, x1: float, y1: float, x2: float, y2: float, radius: float, **options) -> int:
    points = [
        x1 + radius, y1, x2 - radius, y1, x2, y1, x2, y1 + radius,
        x2, y2 - radius, x2, y2, x2 - radius, y2, x1 + radius, y2,
        x1, y2, x1, y2 - radius, x1, y1 + radius, x1, y1,
    ]  # fmt: skip
    return canvas.create_polygon(points, smooth=True, **options)


def reset_label_colors(widget: tk.Misc) -> None:
    """tk_setPalette (wywoływane przez motyw) wpisuje kolor tekstu wprost do etykiet ttk,
    przez co ignorowałyby kolory ze stylów - czyścimy to ustawienie."""
    for child in widget.winfo_children():
        if child.winfo_class() == "TLabel":
            child.configure(foreground="")
        reset_label_colors(child)


def link_label(parent, text: str, command, small: bool = False) -> ttk.Label:
    """Klikalny tekst w kolorze akcentu, podkreślany po najechaniu."""
    style, hover_font = (
        ("CaptionLink.TLabel", "DicomExporterCaptionLinkFont") if small else ("Link.TLabel", "DicomExporterLinkFont")
    )
    label = ttk.Label(parent, text=text, style=style, cursor="hand2")
    label.bind("<Button-1>", lambda _event: command())
    label.bind("<Enter>", lambda _event: label.configure(font=hover_font))
    label.bind("<Leave>", lambda _event: label.configure(font=""))
    return label


class IconFactory:
    """Renderuje ikony z systemowej czcionki ikon do obrazków Tk (z pamięcią podręczną)."""

    def __init__(self, root: tk.Tk, scale: float) -> None:
        self.root = root
        self.scale = scale
        self.font_path = find_icon_font()
        self._cache: dict[tuple, ImageTk.PhotoImage] = {}

    def get(self, name: str, color: str, size: int, gap: int = 0) -> ImageTk.PhotoImage | None:
        if self.font_path is None:
            return None
        pixels = max(8, round(size * self.scale))
        gap_pixels = round(gap * self.scale)
        key = (name, color, pixels, gap_pixels)
        if key not in self._cache:
            font = ImageFont.truetype(str(self.font_path), pixels)
            image = Image.new("RGBA", (pixels + gap_pixels, pixels), (0, 0, 0, 0))
            draw_centered_glyph(ImageDraw.Draw(image), GLYPHS[name], font, pixels, pixels, color)
            self._cache[key] = ImageTk.PhotoImage(image, master=self.root)
        return self._cache[key]

    def badge(self, size: int) -> Image.Image:
        """Ikona aplikacji: zaokrócony kwadrat w kolorze marki z symbolem obrazu."""
        big = size * 4
        image = Image.new("RGBA", (big, big), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)
        draw.rounded_rectangle((0, 0, big - 1, big - 1), radius=int(big * 0.24), fill=BRAND)
        if self.font_path is not None:
            font = ImageFont.truetype(str(self.font_path), int(big * 0.54))
            draw_centered_glyph(draw, GLYPHS["app"], font, big, big, "#ffffff")
        return image.resize((size, size), Image.Resampling.LANCZOS)

    def write_ico(self, path: Path) -> Path | None:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            sizes = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (256, 256)]
            self.badge(256).save(path, format="ICO", sizes=sizes)
            return path
        except OSError:
            return None


class Tooltip:
    """Podpowiedź wyświetlana po najechaniu na widżet (np. przyciski z samą ikoną)."""

    def __init__(self, widget: tk.Widget, text: str, delay: int = 500) -> None:
        self.widget = widget
        self.text = text
        self.delay = delay
        self.window: tk.Toplevel | None = None
        self._after: str | None = None
        widget.bind("<Enter>", self._schedule, add="+")
        widget.bind("<Leave>", self._hide, add="+")
        widget.bind("<ButtonPress>", self._hide, add="+")

    def _schedule(self, _event=None) -> None:
        self._cancel()
        self._after = self.widget.after(self.delay, self._show)

    def _cancel(self) -> None:
        if self._after is not None:
            self.widget.after_cancel(self._after)
            self._after = None

    def _show(self) -> None:
        self._after = None
        if self.window is not None or not self.widget.winfo_exists():
            return
        self.window = window = tk.Toplevel(self.widget)
        window.wm_overrideredirect(True)
        window.attributes("-topmost", True)
        tk.Label(
            window, text=self.text, background="#2b2b2b", foreground="#ffffff", padx=8, pady=4, font="SunValleyCaptionFont"
        ).pack()
        window.update_idletasks()
        x = self.widget.winfo_rootx() + (self.widget.winfo_width() - window.winfo_width()) // 2
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 6
        window.geometry(f"+{max(0, x)}+{y}")

    def _hide(self, _event=None) -> None:
        self._cancel()
        if self.window is not None:
            self.window.destroy()
            self.window = None


class ScrollableFrame(ttk.Frame):
    """Ramka z pionowym przewijaniem; pasek przewijania pojawia się tylko wtedy, gdy jest potrzebny."""

    def __init__(self, parent, padding=0) -> None:
        super().__init__(parent)
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)
        self.canvas = tk.Canvas(self, highlightthickness=0, borderwidth=0, yscrollincrement=20)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        self.scrollbar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.inner = ttk.Frame(self.canvas, padding=padding)
        self._window = self.canvas.create_window(0, 0, window=self.inner, anchor="nw")
        self.canvas.configure(yscrollcommand=self._on_scroll)
        self.inner.bind("<Configure>", lambda _event: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", lambda event: self.canvas.itemconfigure(self._window, width=event.width))

    def _on_scroll(self, first: str, last: str) -> None:
        if float(first) <= 0.0 and float(last) >= 1.0:
            self.scrollbar.grid_remove()
        else:
            self.scrollbar.grid(row=0, column=1, sticky="ns")
        self.scrollbar.set(first, last)

    def contains(self, widget: tk.Misc) -> bool:
        return str(widget).startswith(f"{self}.")

    def scroll(self, units: int) -> None:
        first, last = self.canvas.yview()
        if first > 0.0 or last < 1.0:
            self.canvas.yview_scroll(units, "units")


class Choice:
    """Lista rozwijana: pokazuje etykiety w bieżącym języku, a w zmiennej przechowuje klucze."""

    def __init__(self, parent, variable: tk.StringVar, options: list[tuple[str, str]], command=None, width=None) -> None:
        self.variable = variable
        self.options = options
        self.command = command
        self.widget = ttk.Combobox(parent, state="readonly", values=[label for _, label in options], width=width)
        self._sync()
        self.widget.bind("<<ComboboxSelected>>", self._on_selected)
        self._trace = variable.trace_add("write", lambda *_: self._sync())
        self.widget.bind("<Destroy>", self._on_destroy)

    def set_options(self, options: list[tuple[str, str]]) -> None:
        self.options = options
        self.widget.configure(values=[label for _, label in options])
        self._sync()

    def _sync(self) -> None:
        if not self.widget.winfo_exists():
            return
        keys = [key for key, _ in self.options]
        value = self.variable.get()
        if value in keys:
            self.widget.current(keys.index(value))
        else:
            self.widget.set("")

    def _on_selected(self, _event) -> None:
        index = self.widget.current()
        self.widget.selection_clear()
        if index >= 0 and self.variable.get() != self.options[index][0]:
            self.variable.set(self.options[index][0])
            if self.command is not None:
                self.command()

    def _on_destroy(self, _event) -> None:
        try:
            self.variable.trace_remove("write", self._trace)
        except (tk.TclError, ValueError):
            pass


def work_area(root: tk.Misc) -> tuple[int, int, int, int]:
    """Obszar roboczy ekranu bez paska zadań: (lewo, góra, prawo, dół) w pikselach."""
    if sys.platform == "win32":
        try:
            import ctypes
            from ctypes import wintypes

            rect = wintypes.RECT()
            if ctypes.windll.user32.SystemParametersInfoW(0x0030, 0, ctypes.byref(rect), 0):  # SPI_GETWORKAREA
                return rect.left, rect.top, rect.right, rect.bottom
        except (AttributeError, OSError):
            pass
    return 0, 0, root.winfo_screenwidth(), root.winfo_screenheight()


def enable_high_dpi() -> None:
    if sys.platform != "win32":
        return
    try:
        import ctypes

        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except (AttributeError, OSError):
        pass


def create_root() -> tuple[tk.Tk, bool]:
    if TkinterDnD is not None:
        try:
            return TkinterDnD.Tk(), True
        except (tk.TclError, RuntimeError):
            pass
    return tk.Tk(), False
