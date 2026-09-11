"""Podgląd obrazu: płótno z powiększaniem, przesuwaniem i rysowaniem masek oraz wczytywanie plików w tle."""

from __future__ import annotations

import math
import threading
import tkinter as tk
from pathlib import Path

from PIL import Image, ImageTk

from .converter import ConvertOptions, DicomConversionError, PreviewSource, dataset_details, file_window, is_color
from .dicominfo import dataset_tags
from .i18n import t
from .widgets import PREVIEW_BG, PREVIEW_FG, IconFactory

MASK_OUTLINE = "#f7b500"


class PreviewWorker(threading.Thread):
    """Wątek podglądu: realizuje zawsze tylko najnowsze żądanie (starsze są pomijane)."""

    def __init__(self, post) -> None:
        super().__init__(name="dicom-preview", daemon=True)
        self._post = post
        self._condition = threading.Condition()
        self._request: tuple | None = None
        self._forget = False
        self._source: PreviewSource | None = None

    def submit(self, token: int, path: Path, frame: int, options: ConvertOptions, include_info: bool) -> None:
        with self._condition:
            self._request = (token, Path(path), frame, options, include_info)
            self._condition.notify()

    def forget(self) -> None:
        """Zwalnia wczytany plik (np. po wyczyszczeniu listy)."""
        with self._condition:
            self._request = None
            self._forget = True
            self._condition.notify()

    def run(self) -> None:
        while True:
            with self._condition:
                while self._request is None and not self._forget:
                    self._condition.wait()
                if self._forget:
                    self._source, self._forget = None, False
                request, self._request = self._request, None
            if request is not None:
                self._process(*request)

    def _process(self, token: int, path: Path, frame: int, options: ConvertOptions, include_info: bool) -> None:
        try:
            if self._source is None or self._source.path != path:
                self._source = None
                self._source = PreviewSource(path)
                include_info = True
            source = self._source
            if include_info:
                ds = source.ds
                info = {
                    "details": dataset_details(ds),
                    "tags": dataset_tags(ds.file_meta) + dataset_tags(ds),
                    "frames": source.frame_count,
                    "window": file_window(ds, 0),
                    "range": source.value_range(0),
                    "color": is_color(ds),
                    "dataset": ds,
                }
                self._post(("preview_loaded", path, info))
            image = source.render(frame, options)
        except DicomConversionError as exc:
            self._post(("preview_error", token, path, str(exc)))
        except Exception as exc:
            self._post(("preview_error", token, path, t("err_unexpected", error=exc)))
        else:
            self._post(("preview_image", token, path, frame, image))


class ZoomCanvas:
    """Płótno podglądu.

    Lewy przycisk: przesuwanie (lub rysowanie maski w trybie rysowania), prawy przycisk: zmiana okna,
    dwuklik: dopasowanie do okna. Maski są zapisywane jako ułamki wymiarów obrazu.
    """

    MIN_ZOOM = 0.02
    MAX_ZOOM = 32.0

    def __init__(self, parent, icons: IconFactory, on_change) -> None:
        self.icons = icons
        self.on_change = on_change
        self.on_window_drag = None  # (etap, dx, dy)
        self.on_mask_drawn = None  # ((x0, y0, x1, y1) jako ułamki)
        self.canvas = tk.Canvas(parent, highlightthickness=0, borderwidth=0, background=PREVIEW_BG, takefocus=True)
        self.image: Image.Image | None = None
        self.photo: ImageTk.PhotoImage | None = None
        self.zoom = 1.0
        self.fit = True
        self.center_x = self.center_y = 0.0
        self.masks: tuple[tuple[float, float, float, float], ...] = ()
        self.draw_mode = False
        self.message = ("", "image", PREVIEW_FG)
        self._drag: tuple[int, int, float, float] | None = None
        self._mask_start: tuple[int, int] | None = None
        self._window_start: tuple[int, int] | None = None
        canvas = self.canvas
        canvas.bind("<Configure>", lambda _event: self.redraw())
        canvas.bind("<ButtonPress-1>", self._press_left)
        canvas.bind("<B1-Motion>", self._move_left)
        canvas.bind("<ButtonRelease-1>", self._release_left)
        canvas.bind("<Double-Button-1>", lambda _event: self.fit_view())
        canvas.bind("<ButtonPress-3>", self._press_right)
        canvas.bind("<B3-Motion>", self._move_right)
        canvas.bind("<ButtonRelease-3>", self._release_right)

    # ------------------------------------------------------------------ stan

    def zoom_percent(self) -> int | None:
        return round(self.zoom * 100) if self.image is not None else None

    def show_message(self, text: str, icon: str = "image", color: str = PREVIEW_FG) -> None:
        self.image = None
        self.photo = None
        self.message = (text, icon, color)
        self._update_cursor()
        self.redraw()
        self.on_change()

    def set_image(self, image: Image.Image, keep_view: bool = False) -> None:
        if not (keep_view and self.image is not None and self.image.size == image.size):
            self.fit = True
        self.image = image
        self._update_cursor()
        self.redraw()
        self.on_change()

    def set_masks(self, masks) -> None:
        self.masks = tuple(masks)
        self.redraw()

    def set_draw_mode(self, enabled: bool) -> None:
        self.draw_mode = enabled
        self._update_cursor()

    def fit_view(self) -> None:
        if self.image is not None:
            self.fit = True
            self.redraw()
            self.on_change()

    def zoom_by(self, factor: float, x: float | None = None, y: float | None = None) -> None:
        """Powiększa, zachowując punkt pod kursorem (lub środek płótna) w tym samym miejscu."""
        if self.image is None:
            return
        width, height = self._size()
        x = width / 2 if x is None else x
        y = height / 2 if y is None else y
        old = self.zoom
        new = min(self.MAX_ZOOM, max(self.MIN_ZOOM, old * factor))
        if new == old:
            return
        image_x = self.center_x + (x - width / 2) / old
        image_y = self.center_y + (y - height / 2) / old
        self.zoom, self.fit = new, False
        self.center_x = image_x - (x - width / 2) / new
        self.center_y = image_y - (y - height / 2) / new
        self._clamp()
        self.redraw()
        self.on_change()

    # ------------------------------------------------------------------ współrzędne

    def _size(self) -> tuple[int, int]:
        return max(1, self.canvas.winfo_width()), max(1, self.canvas.winfo_height())

    def _view(self) -> tuple[float, float, float]:
        """(powiększenie, lewy, górny) – lewy górny róg płótna we współrzędnych obrazu."""
        width, height = self._size()
        return self.zoom, self.center_x - width / (2 * self.zoom), self.center_y - height / (2 * self.zoom)

    def canvas_to_image(self, x: float, y: float) -> tuple[float, float]:
        zoom, left, top = self._view()
        return left + x / zoom, top + y / zoom

    def image_to_canvas(self, x: float, y: float) -> tuple[float, float]:
        zoom, left, top = self._view()
        return (x - left) * zoom, (y - top) * zoom

    def _clamp(self) -> None:
        width, height = self.image.size
        self.center_x = min(max(self.center_x, 0.0), float(width))
        self.center_y = min(max(self.center_y, 0.0), float(height))

    def _update_cursor(self) -> None:
        if self.image is None:
            cursor = ""
        elif self.draw_mode:
            cursor = "crosshair"
        else:
            cursor = "fleur"
        self.canvas.configure(cursor=cursor)

    # ------------------------------------------------------------------ mysz

    def _press_left(self, event) -> None:
        self.canvas.focus_set()
        if self.image is None:
            return
        if self.draw_mode:
            self._mask_start = (event.x, event.y)
        else:
            self._drag = (event.x, event.y, self.center_x, self.center_y)

    def _move_left(self, event) -> None:
        if self._mask_start is not None:
            self.canvas.delete("mask-draft")
            self.canvas.create_rectangle(
                *self._mask_start, event.x, event.y, outline=MASK_OUTLINE, width=2, dash=(6, 3), tags="mask-draft"
            )
            return
        if self._drag is None or self.image is None:
            return
        start_x, start_y, center_x, center_y = self._drag
        self.fit = False
        self.center_x = center_x - (event.x - start_x) / self.zoom
        self.center_y = center_y - (event.y - start_y) / self.zoom
        self._clamp()
        self.redraw()

    def _release_left(self, event) -> None:
        self._drag = None
        if self._mask_start is None:
            return
        start_x, start_y = self._mask_start
        self._mask_start = None
        self.canvas.delete("mask-draft")
        if self.image is None or abs(event.x - start_x) < 4 or abs(event.y - start_y) < 4:
            return
        width, height = self.image.size
        (ax, ay), (bx, by) = self.canvas_to_image(start_x, start_y), self.canvas_to_image(event.x, event.y)
        x0, x1 = sorted(min(max(value / width, 0.0), 1.0) for value in (ax, bx))
        y0, y1 = sorted(min(max(value / height, 0.0), 1.0) for value in (ay, by))
        if x1 - x0 > 0.002 and y1 - y0 > 0.002 and self.on_mask_drawn is not None:
            self.on_mask_drawn((x0, y0, x1, y1))

    def _press_right(self, event) -> None:
        if self.image is not None and self.on_window_drag is not None:
            self._window_start = (event.x, event.y)
            self.canvas.configure(cursor="sizing")
            self.on_window_drag("start", 0, 0)

    def _move_right(self, event) -> None:
        if self._window_start is not None and self.on_window_drag is not None:
            self.on_window_drag("move", event.x - self._window_start[0], event.y - self._window_start[1])

    def _release_right(self, _event) -> None:
        if self._window_start is not None:
            self._window_start = None
            self._update_cursor()
            if self.on_window_drag is not None:
                self.on_window_drag("end", 0, 0)

    # ------------------------------------------------------------------ rysowanie

    def redraw(self) -> None:
        canvas = self.canvas
        canvas.delete("all")
        width, height = self._size()
        scale = self.icons.scale
        if self.image is None:
            text, icon, color = self.message
            photo = self.icons.get(icon, color, 36)
            if photo is not None:
                canvas.create_image(width / 2, height / 2 - 26 * scale, image=photo)
            canvas.create_text(
                width / 2,
                height / 2 + 4 * scale,
                text=text,
                fill=color,
                font="SunValleyCaptionFont",
                width=max(60, width - 40 * scale),
                justify="center",
                anchor="n",
            )
            return

        image_width, image_height = self.image.size
        if self.fit:
            zoom = min(self.MAX_ZOOM, max(self.MIN_ZOOM, min(width / image_width, height / image_height)))
            self.center_x, self.center_y = image_width / 2, image_height / 2
            if zoom != self.zoom:  # np. po zmianie rozmiaru okna - odświeża wskaźnik powiększenia
                self.zoom = zoom
                self.canvas.after_idle(self.on_change)
        zoom, left, top = self._view()
        box = (
            max(0, math.floor(left)),
            max(0, math.floor(top)),
            min(image_width, math.ceil(left + width / zoom)),
            min(image_height, math.ceil(top + height / zoom)),
        )
        if box[2] > box[0] and box[3] > box[1]:
            size = (max(1, round((box[2] - box[0]) * zoom)), max(1, round((box[3] - box[1]) * zoom)))
            if zoom >= 2:
                resample = Image.Resampling.NEAREST  # przy dużym powiększeniu widać pojedyncze piksele
            elif zoom >= 1:
                resample = Image.Resampling.BILINEAR
            else:
                resample = Image.Resampling.LANCZOS
            region = self.image.crop(box).resize(size, resample)
            self.photo = ImageTk.PhotoImage(region, master=canvas)
            canvas.create_image(round((box[0] - left) * zoom), round((box[1] - top) * zoom), image=self.photo, anchor="nw")
        for x0, y0, x1, y1 in self.masks:  # obrys masek (same maski są już zaczernione w obrazie)
            canvas.create_rectangle(
                *self.image_to_canvas(x0 * image_width, y0 * image_height),
                *self.image_to_canvas(x1 * image_width, y1 * image_height),
                outline=MASK_OUTLINE,
                dash=(4, 3),
            )
