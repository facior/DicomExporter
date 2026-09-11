"""Przewodnik po programie (pokazywany przy pierwszym uruchomieniu).

Okno jest przyciemniane, omawiany element podświetlony, a obok pojawia się dymek z opisem i strzałką.
Przyciemnienie to obraz okna narysowany na płótnie nad całym interfejsem – dzięki temu przewodnik
blokuje przypadkowe kliknięcia, a przejścia między krokami płynnie się przenikają."""

from __future__ import annotations

import math
import tkinter as tk
from collections.abc import Callable
from dataclasses import dataclass
from tkinter import ttk
from typing import TYPE_CHECKING

from PIL import Image, ImageDraw, ImageFilter, ImageGrab, ImageTk

from .i18n import t
from .widgets import crossfade, style_name
from .winshell import capture_client, is_foreground

if TYPE_CHECKING:
    from .gui import App

Rect = tuple[int, int, int, int]
Point = tuple[float, float]

ACCENT = "#60cdff"  # jasny akcent Windows – czytelny na przyciemnionym tle w obu motywach
DIM = {False: 0.55, True: 0.62}  # siła przyciemnienia: motyw jasny / ciemny
SUPERSAMPLE = 3  # krawędzie, obwódka i strzałka rysowane w większej skali dla wygładzenia


@dataclass(frozen=True)
class TourStep:
    key: str  # teksty: tour_<key>_title, tour_<key>_text
    targets: Callable[[App], list] | None = None  # elementy do podświetlenia
    tab: int | None = None  # karta panelu bocznego, która ma być widoczna


def _attributes(*names: str) -> Callable[[App], list]:
    return lambda app: [getattr(app, name, None) for name in names]


STEPS: tuple[TourStep, ...] = (
    TourStep("welcome"),
    TourStep("files", lambda app: [app.drop_zone if app.drop_zone.winfo_ismapped() else app.tree]),
    TourStep("sources", _attributes("add_files_btn", "add_folder_btn", "disc_btn")),
    TourStep("preview", lambda app: [app.zoom.canvas], tab=0),
    TourStep("contrast", _attributes("contrast_frame"), tab=0),
    TourStep("export", lambda app: [app.export_sections.get(key) for key in ("profile", "mode", "format")], tab=2),
    TourStep("output", _attributes("output_entry", "choose_output_btn", "open_output_btn")),
    TourStep("header", _attributes("language_frame", "about_btn", "theme_switch")),
    TourStep("convert", _attributes("convert_btn")),
)


# ---------------------------------------------------------------------- geometria


def union(rects: list[Rect]) -> Rect:
    return min(r[0] for r in rects), min(r[1] for r in rects), max(r[2] for r in rects), max(r[3] for r in rects)


def inflate(rect: Rect, amount: int) -> Rect:
    return rect[0] - amount, rect[1] - amount, rect[2] + amount, rect[3] + amount


def intersect(rect: Rect, other: Rect) -> Rect | None:
    x1, y1 = max(rect[0], other[0]), max(rect[1], other[1])
    x2, y2 = min(rect[2], other[2]), min(rect[3], other[3])
    return (x1, y1, x2, y2) if x2 > x1 and y2 > y1 else None


def widget_rect(widget: tk.Misc, root: tk.Misc) -> Rect:
    x, y = widget.winfo_rootx() - root.winfo_rootx(), widget.winfo_rooty() - root.winfo_rooty()
    return x, y, x + widget.winfo_width(), y + widget.winfo_height()


def place_bubble(target: Rect | None, size: tuple[int, int], area: Rect, gap: int, margin: int) -> tuple[int, int, str]:
    """Lewy górny róg dymka i strona celu, po której stoi („below”, „above”, „right”, „left” albo „center”).

    Wybierana jest strona z największym zapasem miejsca; dymek nie wychodzi poza okno."""
    width, height = size
    ax1, ay1, ax2, ay2 = area
    if target is None:
        return (ax1 + ax2 - width) // 2, (ay1 + ay2 - height) // 2, "center"
    x1, y1, x2, y2 = target
    spare = {
        "below": ay2 - y2 - height - gap - margin,
        "above": y1 - ay1 - height - gap - margin,
        "right": ax2 - x2 - width - gap - margin,
        "left": x1 - ax1 - width - gap - margin,
    }
    side = max(spare, key=spare.get)
    cx, cy = (x1 + x2) // 2, (y1 + y2) // 2
    x, y = {
        "below": (cx - width // 2, y2 + gap),
        "above": (cx - width // 2, y1 - gap - height),
        "right": (x2 + gap, cy - height // 2),
        "left": (x1 - gap - width, cy - height // 2),
    }[side]
    x = min(max(x, ax1 + margin), ax2 - margin - width)
    y = min(max(y, ay1 + margin), ay2 - margin - height)
    return x, y, side


def arrow_path(panel: Rect, target: Rect, side: str, gap: int) -> tuple[Point, Point, Point] | None:
    """Początek (przy dymku), punkt kontrolny łuku i koniec (przy celu) strzałki; None, gdy nie ma na nią miejsca."""
    bx1, by1, bx2, by2 = panel
    tx1, ty1, tx2, ty2 = target
    corner = gap * 3

    def clamp(value: float, low: float, high: float) -> float:
        return (low + high) / 2 if low > high else max(low, min(high, value))

    tcx, tcy, bcx, bcy = (tx1 + tx2) / 2, (ty1 + ty2) / 2, (bx1 + bx2) / 2, (by1 + by2) / 2
    if side == "below":
        start, end = (clamp(tcx, bx1 + corner, bx2 - corner), by1 - gap), (clamp(bcx, tx1 + corner, tx2 - corner), ty2 + gap)
    elif side == "above":
        start, end = (clamp(tcx, bx1 + corner, bx2 - corner), by2 + gap), (clamp(bcx, tx1 + corner, tx2 - corner), ty1 - gap)
    elif side == "right":
        start, end = (bx1 - gap, clamp(tcy, by1 + corner, by2 - corner)), (tx2 + gap, clamp(bcy, ty1 + corner, ty2 - corner))
    elif side == "left":
        start, end = (bx2 + gap, clamp(tcy, by1 + corner, by2 - corner)), (tx1 - gap, clamp(bcy, ty1 + corner, ty2 - corner))
    else:
        return None
    dx, dy = end[0] - start[0], end[1] - start[1]
    length = math.hypot(dx, dy)
    if length < gap * 4:
        return None
    bend = length * 0.22  # łagodny łuk zamiast prostej kreski
    control = ((start[0] + end[0]) / 2 - dy / length * bend, (start[1] + end[1]) / 2 + dx / length * bend)
    return start, control, end


# ---------------------------------------------------------------------- rysowanie


def _composite(base: Image.Image, layer: Image.Image, x: int, y: int) -> None:
    """Nakłada warstwę RGBA w punkcie (x, y), przycinając ją do rozmiaru obrazu."""
    left, top = max(0, -x), max(0, -y)
    right, bottom = min(layer.width, base.width - x), min(layer.height, base.height - y)
    if right > left and bottom > top:
        base.alpha_composite(layer.crop((left, top, right, bottom)), dest=(x + left, y + top))


def _rounded(size: tuple[int, int], radius: int, fill=None, outline=None, width: int = 0) -> Image.Image:
    w, h = size
    big = Image.new("RGBA", (w * SUPERSAMPLE, h * SUPERSAMPLE), (0, 0, 0, 0))
    ImageDraw.Draw(big).rounded_rectangle(
        (0, 0, w * SUPERSAMPLE - 1, h * SUPERSAMPLE - 1),
        radius=radius * SUPERSAMPLE,
        fill=fill,
        outline=outline,
        width=width * SUPERSAMPLE,
    )
    return big.resize((w, h), Image.Resampling.LANCZOS)


def _bezier(start: Point, control: Point, end: Point, steps: int = 48) -> list[Point]:
    return [
        (
            (1 - s) ** 2 * start[0] + 2 * (1 - s) * s * control[0] + s * s * end[0],
            (1 - s) ** 2 * start[1] + 2 * (1 - s) * s * control[1] + s * s * end[1],
        )
        for s in (index / steps for index in range(steps + 1))
    ]


def _draw_arrow(scene: Image.Image, arrow: tuple[Point, Point, Point], scale: float) -> None:
    start, control, end = arrow
    width = max(2.0, 3 * scale)
    head_length, head_half = 15 * scale, 8 * scale
    points = _bezier(start, control, end)
    tail = points[-6]
    length = math.hypot(end[0] - tail[0], end[1] - tail[1]) or 1.0
    ux, uy = (end[0] - tail[0]) / length, (end[1] - tail[1]) / length
    base = (end[0] - ux * head_length, end[1] - uy * head_length)
    shaft = [p for p in points if math.hypot(p[0] - end[0], p[1] - end[1]) > head_length] + [base]
    head = [end, (base[0] - uy * head_half, base[1] + ux * head_half), (base[0] + uy * head_half, base[1] - ux * head_half)]

    xs, ys = [p[0] for p in shaft + head], [p[1] for p in shaft + head]
    pad = int(width * 2) + 4
    left, top, right, bottom = int(min(xs)) - pad, int(min(ys)) - pad, int(max(xs)) + pad, int(max(ys)) + pad
    layer = Image.new("RGBA", ((right - left) * SUPERSAMPLE, (bottom - top) * SUPERSAMPLE), (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)

    def local(point: Point) -> Point:
        return (point[0] - left) * SUPERSAMPLE, (point[1] - top) * SUPERSAMPLE

    draw.line([local(p) for p in shaft], fill=ACCENT, width=round(width * SUPERSAMPLE), joint="curve")
    radius = width * SUPERSAMPLE / 2
    sx, sy = local(shaft[0])
    draw.ellipse((sx - radius, sy - radius, sx + radius, sy + radius), fill=ACCENT)
    draw.polygon([local(p) for p in head], fill=ACCENT)
    _composite(scene, layer.resize((right - left, bottom - top), Image.Resampling.LANCZOS), left, top)


def render_scene(
    snapshot: Image.Image,
    spot: Rect | None,
    panel: Rect | None,
    arrow: tuple[Point, Point, Point] | None,
    *,
    dark: bool,
    panel_color: str,
    border_color: str,
    scale: float,
) -> Image.Image:
    """Przyciemniony obraz okna z podświetlonym obszarem, tłem dymka (z cieniem) i strzałką."""
    base = snapshot.convert("RGB")
    scene = Image.blend(base, Image.new("RGB", base.size, "#000000"), DIM[dark]).convert("RGBA")
    radius = max(4, round(8 * scale))

    if spot is not None:
        x1, y1, x2, y2 = spot
        highlight = base.crop(spot).convert("RGBA")
        highlight.putalpha(_rounded((x2 - x1, y2 - y1), radius, fill="#ffffff").getchannel("A"))
        _composite(scene, highlight, x1, y1)
        ring = max(2, round(2 * scale))
        _composite(scene, _rounded((x2 - x1 + 2 * ring, y2 - y1 + 2 * ring), radius + ring, outline=ACCENT, width=ring), x1 - ring, y1 - ring)

    if panel is not None:
        x1, y1, x2, y2 = panel
        w, h = x2 - x1, y2 - y1
        blur = max(6, round(14 * scale))
        shadow = Image.new("RGBA", (w + 4 * blur, h + 4 * blur), (0, 0, 0, 0))
        offset = round(4 * scale)
        ImageDraw.Draw(shadow).rounded_rectangle(
            (2 * blur, 2 * blur + offset, 2 * blur + w, 2 * blur + h + offset), radius=radius * 2, fill=(0, 0, 0, 140)
        )
        _composite(scene, shadow.filter(ImageFilter.GaussianBlur(blur / 2)), x1 - 2 * blur, y1 - 2 * blur)
        _composite(scene, _rounded((w, h), radius * 2 // 1, fill=panel_color, outline=border_color, width=1), x1, y1)

    if arrow is not None:
        _draw_arrow(scene, arrow, scale)
    return scene.convert("RGB")


# ---------------------------------------------------------------------- przewodnik


class Tour:
    def __init__(self, app: App, on_finish: Callable[[bool], None]) -> None:
        self.app = app
        self.root = app.root
        self.on_finish = on_finish
        self.index = 0
        self.canvas: tk.Canvas | None = None
        self.photo: ImageTk.PhotoImage | None = None
        self.badge: ImageTk.PhotoImage | None = None
        self.primary: ttk.Button | None = None
        self.rendered_size: tuple[int, int] | None = None
        self.resize_after: str | None = None
        self.closed = False
        self.initial_tab = app.side_tabs.index("current")
        self.bindings: list[tuple[str, str]] = []

    def start(self) -> None:
        for sequence, handler in (("<Right>", self.next), ("<Return>", self.next), ("<Left>", self.back), ("<Escape>", self.finish)):
            funcid = self.root.bind(sequence, lambda _event, action=handler: (action(), "break")[1], add="+")
            self.bindings.append((sequence, funcid))
        self._transition(lambda: self._show(0))

    def next(self) -> None:
        if self.closed:
            return
        if self.index >= len(STEPS) - 1:
            self.finish()
        else:
            self._transition(lambda: self._show(self.index + 1))

    def back(self) -> None:
        if not self.closed and self.index > 0:
            self._transition(lambda: self._show(self.index - 1))

    def finish(self) -> None:
        if self.closed:
            return
        self.closed = True
        for sequence, funcid in self.bindings:
            try:
                self.root.unbind(sequence, funcid)
            except tk.TclError:
                pass
        if self.resize_after is not None:
            self.root.after_cancel(self.resize_after)
        completed = self.index == len(STEPS) - 1

        def remove() -> None:
            if self.canvas is not None:
                self.canvas.destroy()
                self.canvas = None
            self.app.side_tabs.select(self.initial_tab)

        self._transition(remove)
        self.on_finish(completed)

    def _transition(self, change: Callable[[], None]) -> None:
        # Przenikanie wymaga zrzutu ekranu – gdy okno nie jest na wierzchu, zmiana jest natychmiastowa.
        if is_foreground(self.root):
            crossfade(self.root, change)
        else:
            change()

    def _show(self, index: int) -> None:
        self.index = index
        step = STEPS[index]
        if step.tab is not None:
            self.app.side_tabs.select(step.tab)
            if step.tab == 2:
                self.app.export_scroll.canvas.yview_moveto(0)
        self._render()

    def _render(self) -> None:
        if self.closed:
            return
        app, root, px = self.app, self.root, self.app.px
        if self.canvas is not None:
            self.canvas.place_forget()
        root.update()  # interfejs bez przewodnika (np. po zmianie karty) musi być narysowany przed pobraniem obrazu
        snapshot = capture_client(root)
        if snapshot is None:
            x, y = root.winfo_rootx(), root.winfo_rooty()
            snapshot = ImageGrab.grab((x, y, x + root.winfo_width(), y + root.winfo_height()), all_screens=True)
        width, height = snapshot.size

        if self.canvas is None:
            self.canvas = tk.Canvas(root, highlightthickness=0, borderwidth=0, background="#000000")
            self.canvas.bind("<Configure>", self._on_resize)
        canvas = self.canvas
        canvas.delete("all")
        for child in canvas.winfo_children():
            child.destroy()

        step = STEPS[self.index]
        bubble = self._build_bubble(step)
        bubble.update_idletasks()
        pad = px(12)
        size = (bubble.winfo_reqwidth() + 2 * pad, bubble.winfo_reqheight() + 2 * pad)
        area = (0, 0, width, height)
        spot = None
        if step.targets is not None:
            rects = [widget_rect(widget, root) for widget in step.targets(app) if widget is not None and widget.winfo_ismapped()]
            if rects:
                spot = intersect(inflate(union(rects), px(6)), inflate(area, -px(2)))
        x, y, side = place_bubble(spot, size, area, gap=px(88), margin=px(16))
        panel = (x, y, x + size[0], y + size[1])
        arrow = arrow_path(panel, spot, side, gap=px(8)) if spot is not None else None
        image = render_scene(
            snapshot,
            spot,
            panel,
            arrow,
            dark=app.dark_var.get(),
            panel_color=self._panel_color(),
            border_color=app.palette["border"],
            scale=app.scale,
        )
        self.photo = ImageTk.PhotoImage(image, master=root)
        canvas.create_image(0, 0, image=self.photo, anchor="nw")
        canvas.create_window(x + pad, y + pad, window=bubble, anchor="nw")
        self.rendered_size = (width, height)
        canvas.place(x=0, y=0, relwidth=1, relheight=1)
        tk.Misc.lift(canvas)
        if self.primary is not None:
            self.primary.focus_set()

    def _panel_color(self) -> str:
        try:
            color = str(self.root.tk.call("ttk::style", "lookup", "TFrame", "-background"))
        except tk.TclError:
            color = ""
        return color or self.app.palette["bg"]

    def _build_bubble(self, step: TourStep) -> ttk.Frame:
        px = self.app.px
        assert self.canvas is not None
        frame = ttk.Frame(self.canvas)
        frame.columnconfigure(0, weight=1)
        last = self.index == len(STEPS) - 1
        row = 0
        if self.index == 0:
            self.badge = ImageTk.PhotoImage(self.app.icons.badge(px(52)), master=self.root)
            ttk.Label(frame, image=self.badge).grid(row=row, column=0, sticky="w", pady=(0, px(10)))
        else:
            ttk.Label(frame, text=t("tour_step", current=self.index, total=len(STEPS) - 1), style="Caption.TLabel").grid(
                row=row, column=0, sticky="w"
            )
        ttk.Label(frame, text=t(f"tour_{step.key}_title"), style="Title.TLabel").grid(
            row=row + 1, column=0, sticky="w", pady=(px(2), px(6))
        )
        ttk.Label(frame, text=t(f"tour_{step.key}_text"), style="Value.TLabel", wraplength=px(340), justify="left").grid(
            row=row + 2, column=0, sticky="w"
        )

        buttons = ttk.Frame(frame)
        buttons.grid(row=row + 3, column=0, sticky="ew", pady=(px(16), 0))
        if not last:
            ttk.Button(buttons, text=t("tour_skip"), style="Toolbutton", command=self.finish).pack(side="left")
        text = t("tour_start") if self.index == 0 else t("tour_finish") if last else t("tour_next")
        self.primary = ttk.Button(buttons, text=text, style=style_name("Accent.TButton"), command=self.next)
        self.primary.pack(side="right", ipadx=px(8))
        if self.index > 0:
            ttk.Button(buttons, text=t("tour_back"), command=self.back).pack(side="right", padx=(0, px(8)))
        return frame

    def _on_resize(self, event: tk.Event) -> None:
        if self.closed or (event.width, event.height) == self.rendered_size:
            return
        if self.resize_after is not None:
            self.root.after_cancel(self.resize_after)
        self.resize_after = self.root.after(250, self._render_after_resize)

    def _render_after_resize(self) -> None:
        self.resize_after = None
        self._render()
