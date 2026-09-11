"""Szybka konwersja do PNG obok plików źródłowych – uruchamiana z menu kontekstowego Eksploratora."""

from __future__ import annotations

import queue
import threading
import tkinter as tk
from collections.abc import Iterable, Iterator
from pathlib import Path
from tkinter import ttk

from PIL import ImageTk

from .converter import LAYOUT_FLAT, ConvertOptions, FileResult, InputFile, collect_inputs, convert_batch
from .i18n import plural, set_language, t
from .widgets import (
    IconFactory,
    enable_high_dpi,
    set_title_bar_theme,
    setup_fonts,
    style_name,
    sv_ttk,
    system_prefers_dark,
)
from .winshell import flash_taskbar, reveal_in_explorer

AUTO_CLOSE_MS = 6000


def convert_in_place(
    items: Iterable[InputFile], options: ConvertOptions | None = None, cancel_event: threading.Event | None = None
) -> Iterator[FileResult]:
    """Konwertuje pliki do PNG w tych samych folderach, w których leżą (istniejące pliki nie są nadpisywane)."""
    options = options or ConvertOptions(layout=LAYOUT_FLAT)
    groups: dict[Path, list[InputFile]] = {}
    for item in items:
        groups.setdefault(item.path.parent, []).append(item)
    for folder, group in groups.items():
        if cancel_event is not None and cancel_event.is_set():
            return
        yield from convert_batch(group, folder, options, cancel_event=cancel_event)


def quick_convert(paths: list[str]) -> int:
    from .gui import load_settings  # język i motyw jak w głównym oknie

    settings = load_settings()
    set_language(settings.get("language", "pl"))
    theme = settings.get("theme")
    dark = theme == "dark" if theme in ("dark", "light") else system_prefers_dark()

    enable_high_dpi()
    root = tk.Tk()
    scale = max(1.0, root.winfo_fpixels("1i") / 96.0)

    def px(value: float) -> int:
        return round(value * scale)

    if sv_ttk is not None:
        sv_ttk.set_theme("dark" if dark else "light", root)
    fonts = setup_fonts(root, scale)  # noqa: F841 - referencja utrzymuje czcionki przy życiu
    icons = IconFactory(root, scale)
    photos = [ImageTk.PhotoImage(icons.badge(size), master=root) for size in (48, 32, 16)]
    root.iconphoto(True, *photos)
    root.title(t("quick_title"))
    root.resizable(False, False)

    frame = ttk.Frame(root, padding=px(20))
    frame.pack(fill="both", expand=True)
    ttk.Label(frame, text=t("quick_title"), font="SunValleyBodyStrongFont").pack(anchor="w")
    status = tk.StringVar(value=t("status_scanning"))
    ttk.Label(frame, textvariable=status, font="SunValleyCaptionFont", wraplength=px(440), justify="left").pack(
        anchor="w", pady=(px(4), px(12))
    )
    progress = ttk.Progressbar(frame, mode="indeterminate", length=px(440))
    progress.pack(fill="x")
    progress.start(12)
    buttons = ttk.Frame(frame)
    buttons.pack(fill="x", pady=(px(16), 0))
    close_button = ttk.Button(buttons, text=t("btn_close"), command=root.destroy)
    close_button.pack(side="right")
    show_button = ttk.Button(buttons, text=t("btn_show_files"), style=style_name("Accent.TButton"))

    events: queue.Queue[tuple] = queue.Queue()
    cancel_event = threading.Event()
    state = {"total": 0, "ok": 0, "error": 0, "first_output": None, "errors": []}

    def worker() -> None:
        try:
            items = list(collect_inputs(paths))
            events.put(("total", len(items)))
            for result in convert_in_place(items, cancel_event=cancel_event):
                events.put(("result", result))
        except Exception as exc:
            events.put(("result", FileResult(InputFile(Path(paths[0])), error=t("err_unexpected", error=exc))))
        finally:
            events.put(("done",))

    def process() -> None:
        try:
            while True:
                event = events.get_nowait()
                if event[0] == "total":
                    state["total"] = event[1]
                    progress.stop()
                    progress.configure(mode="determinate", maximum=max(1, event[1]), value=0)
                elif event[0] == "result":
                    result: FileResult = event[1]
                    if result.ok:
                        state["ok"] += 1
                        state["first_output"] = state["first_output"] or (result.outputs[0] if result.outputs else None)
                    else:
                        state["error"] += 1
                        state["errors"].append(f"{result.item.path.name}: {result.error}")
                    done = state["ok"] + state["error"]
                    progress.configure(value=done)
                    status.set(t("status_converting", done=done, total=state["total"]))
                elif event[0] == "done":
                    finish()
                    return
        except queue.Empty:
            pass
        root.after(80, process)

    def finish() -> None:
        progress.stop()
        progress.configure(mode="determinate", maximum=1, value=1)
        if state["total"] == 0:
            status.set(t("cli_no_files"))
            return
        summary = t("summary", files=plural(state["ok"], "file"), images=plural(state["ok"], "image"))
        if state["error"]:
            summary += t("summary_errors", count=state["error"]) + "\n" + "\n".join(state["errors"][:3])
        else:
            summary += "\n" + t("quick_done")
        status.set(summary)
        if state["first_output"] is not None:
            show_button.configure(command=lambda: reveal_in_explorer(state["first_output"]))
            show_button.pack(side="right", padx=(0, px(8)))
        flash_taskbar(root)
        if not state["error"]:
            root.after(AUTO_CLOSE_MS, root.destroy)

    def close() -> None:
        cancel_event.set()
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", close)
    root.update_idletasks()
    root.geometry(f"+{(root.winfo_screenwidth() - root.winfo_reqwidth()) // 2}+{(root.winfo_screenheight() - root.winfo_reqheight()) // 3}")
    set_title_bar_theme(root, dark)
    threading.Thread(target=worker, daemon=True).start()
    root.after(80, process)
    root.mainloop()
    return 0 if state["error"] == 0 else 2
