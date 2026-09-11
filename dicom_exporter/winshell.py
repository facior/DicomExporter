"""Integracja z Windows: postęp na pasku zadań, powiadomienia i Eksplorator plików."""

from __future__ import annotations

import ctypes
import os
import subprocess
import sys
from ctypes import wintypes
from pathlib import Path

IS_WINDOWS = sys.platform == "win32"


def open_path(path: Path) -> None:
    if IS_WINDOWS:
        os.startfile(path)
    else:
        subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", str(path)])


def reveal_in_explorer(path: Path) -> None:
    """Otwiera folder z zaznaczonym plikiem."""
    if IS_WINDOWS:
        subprocess.Popen(f'explorer /select,"{path}"')
    else:
        open_path(path.parent)


def _top_level_hwnd(widget) -> int:
    user32 = ctypes.windll.user32
    user32.GetParent.restype = wintypes.HWND
    user32.GetParent.argtypes = (wintypes.HWND,)
    return user32.GetParent(widget.winfo_id()) or widget.winfo_id()


def is_foreground(widget) -> bool:
    """Czy okno programu jest aktywne (na wierzchu)."""
    if not IS_WINDOWS:
        return True
    try:
        user32 = ctypes.WinDLL("user32")
        user32.GetForegroundWindow.restype = wintypes.HWND
        return user32.GetForegroundWindow() == _top_level_hwnd(widget)
    except (AttributeError, OSError):
        return False


class _BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", wintypes.DWORD),
        ("biWidth", wintypes.LONG),
        ("biHeight", wintypes.LONG),
        ("biPlanes", wintypes.WORD),
        ("biBitCount", wintypes.WORD),
        ("biCompression", wintypes.DWORD),
        ("biSizeImage", wintypes.DWORD),
        ("biXPelsPerMeter", wintypes.LONG),
        ("biYPelsPerMeter", wintypes.LONG),
        ("biClrUsed", wintypes.DWORD),
        ("biClrImportant", wintypes.DWORD),
    ]


def capture_client(widget):
    """Obraz zawartości okna (bez paska tytułu) – również wtedy, gdy zasłania je inne okno. None, gdy się nie da."""
    if not IS_WINDOWS:
        return None
    try:
        from PIL import Image

        user32, gdi32 = ctypes.WinDLL("user32"), ctypes.WinDLL("gdi32")
        handle = ctypes.c_void_p
        user32.GetClientRect.argtypes = (handle, ctypes.POINTER(wintypes.RECT))
        user32.GetDC.argtypes, user32.GetDC.restype = (handle,), handle
        user32.ReleaseDC.argtypes = (handle, handle)
        user32.PrintWindow.argtypes = (handle, handle, wintypes.UINT)
        gdi32.CreateCompatibleDC.argtypes, gdi32.CreateCompatibleDC.restype = (handle,), handle
        gdi32.CreateCompatibleBitmap.argtypes = (handle, ctypes.c_int, ctypes.c_int)
        gdi32.CreateCompatibleBitmap.restype = handle
        gdi32.SelectObject.argtypes, gdi32.SelectObject.restype = (handle, handle), handle
        gdi32.DeleteObject.argtypes = (handle,)
        gdi32.DeleteDC.argtypes = (handle,)
        gdi32.GetDIBits.argtypes = (
            handle, handle, wintypes.UINT, wintypes.UINT, ctypes.c_void_p, ctypes.POINTER(_BITMAPINFOHEADER), wintypes.UINT
        )

        hwnd = _top_level_hwnd(widget)
        rect = wintypes.RECT()
        if not user32.GetClientRect(hwnd, ctypes.byref(rect)) or rect.right <= 0 or rect.bottom <= 0:
            return None
        width, height = rect.right, rect.bottom
        window_dc = user32.GetDC(hwnd)
        memory_dc = gdi32.CreateCompatibleDC(window_dc)
        bitmap = gdi32.CreateCompatibleBitmap(window_dc, width, height)
        previous = gdi32.SelectObject(memory_dc, bitmap)
        buffer = ctypes.create_string_buffer(width * height * 4)
        try:
            # PW_CLIENTONLY | PW_RENDERFULLCONTENT – obraz okna z kompozytora, niezależnie od okien nad nim
            captured = user32.PrintWindow(hwnd, memory_dc, 3)
            if captured:
                header = _BITMAPINFOHEADER(ctypes.sizeof(_BITMAPINFOHEADER), width, -height, 1, 32, 0, 0, 0, 0, 0, 0)
                captured = gdi32.GetDIBits(memory_dc, bitmap, 0, height, buffer, ctypes.byref(header), 0)
        finally:
            gdi32.SelectObject(memory_dc, previous)
            gdi32.DeleteObject(bitmap)
            gdi32.DeleteDC(memory_dc)
            user32.ReleaseDC(hwnd, window_dc)
        if not captured:
            return None
        return Image.frombuffer("RGB", (width, height), buffer, "raw", "BGRX", 0, 1)
    except (AttributeError, OSError):
        return None


class _FLASHWINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.UINT),
        ("hwnd", wintypes.HWND),
        ("dwFlags", wintypes.DWORD),
        ("uCount", wintypes.UINT),
        ("dwTimeout", wintypes.DWORD),
    ]


def flash_taskbar(widget) -> None:
    """Miga przyciskiem aplikacji na pasku zadań, dopóki użytkownik do niej nie wróci.

    Działa także wtedy, gdy powiadomienia systemowe są wyłączone.
    """
    if not IS_WINDOWS:
        return
    try:
        flags = 0x2 | 0xC  # FLASHW_TRAY | FLASHW_TIMERNOFG
        info = _FLASHWINFO(ctypes.sizeof(_FLASHWINFO), _top_level_hwnd(widget), flags, 0, 0)
        ctypes.windll.user32.FlashWindowEx(ctypes.byref(info))
    except OSError:
        pass


class _GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", ctypes.c_ulong),
        ("Data2", ctypes.c_ushort),
        ("Data3", ctypes.c_ushort),
        ("Data4", ctypes.c_ubyte * 8),
    ]


class TaskbarProgress:
    """Pasek postępu na przycisku aplikacji na pasku zadań (ITaskbarList3)."""

    NO_PROGRESS = 0
    NORMAL = 2
    ERROR = 4

    _CLSID_TASKBAR_LIST = "{56FDF344-FD6D-11d0-958A-006097C9A090}"
    _IID_TASKBAR_LIST3 = "{EA1AFB91-9E28-4B86-90E9-9E9F8A5EEFAF}"

    def __init__(self, widget) -> None:
        self._widget = widget
        self._pointer = None
        if not IS_WINDOWS:
            return
        try:
            ole32 = ctypes.windll.ole32
            ole32.CoInitialize(None)
            clsid, iid = _GUID(), _GUID()
            ole32.CLSIDFromString(self._CLSID_TASKBAR_LIST, ctypes.byref(clsid))
            ole32.CLSIDFromString(self._IID_TASKBAR_LIST3, ctypes.byref(iid))
            pointer = ctypes.c_void_p()
            if ole32.CoCreateInstance(ctypes.byref(clsid), None, 1, ctypes.byref(iid), ctypes.byref(pointer)) != 0:
                return
            self._pointer = pointer
            self._call(3)  # HrInit
        except (OSError, AttributeError):
            self._pointer = None

    def _call(self, index: int, *args, argtypes=()) -> int:
        vtable = ctypes.cast(self._pointer, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
        method = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, *argtypes)(vtable[index])
        return method(self._pointer, *args)

    def set(self, value: int, total: int, state: int = NORMAL) -> None:
        if self._pointer is None:
            return
        try:
            hwnd = _top_level_hwnd(self._widget)
            self._call(10, hwnd, state, argtypes=(wintypes.HWND, ctypes.c_int))  # SetProgressState
            if state != self.NO_PROGRESS:
                self._call(  # SetProgressValue
                    9, hwnd, max(0, value), max(1, total), argtypes=(wintypes.HWND, ctypes.c_ulonglong, ctypes.c_ulonglong)
                )
        except (OSError, tk_errors()):
            pass

    def clear(self) -> None:
        self.set(0, 1, self.NO_PROGRESS)


def tk_errors() -> type[Exception]:
    import tkinter

    return tkinter.TclError


class _NOTIFYICONDATAW(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("hWnd", wintypes.HWND),
        ("uID", wintypes.UINT),
        ("uFlags", wintypes.UINT),
        ("uCallbackMessage", wintypes.UINT),
        ("hIcon", wintypes.HICON),
        ("szTip", ctypes.c_wchar * 128),
        ("dwState", wintypes.DWORD),
        ("dwStateMask", wintypes.DWORD),
        ("szInfo", ctypes.c_wchar * 256),
        ("uTimeoutOrVersion", wintypes.UINT),
        ("szInfoTitle", ctypes.c_wchar * 64),
        ("dwInfoFlags", wintypes.DWORD),
        ("guidItem", _GUID),
        ("hBalloonIcon", wintypes.HICON),
    ]


class TrayNotifier:
    """Powiadomienie systemowe Windows (dymek z obszaru powiadomień, w Windows 10/11 wyświetlany jako toast)."""

    _NIM_ADD, _NIM_DELETE = 0, 2
    _NIF_ICON, _NIF_TIP, _NIF_INFO = 0x2, 0x4, 0x10
    _NIIF_WARNING, _NIIF_USER, _NIIF_LARGE_ICON = 0x2, 0x4, 0x20

    def __init__(self, widget, icon_path: Path | None) -> None:
        self._widget = widget
        self._icon_path = icon_path
        self._data: _NOTIFYICONDATAW | None = None
        self._after: str | None = None

    def _load_icon(self):
        user32 = ctypes.windll.user32
        user32.LoadImageW.restype = wintypes.HANDLE
        user32.LoadImageW.argtypes = (wintypes.HINSTANCE, wintypes.LPCWSTR, wintypes.UINT, ctypes.c_int, ctypes.c_int, wintypes.UINT)
        user32.LoadIconW.restype = wintypes.HICON
        user32.LoadIconW.argtypes = (wintypes.HINSTANCE, wintypes.LPVOID)
        if self._icon_path is not None and self._icon_path.is_file():
            icon = user32.LoadImageW(None, str(self._icon_path), 1, 0, 0, 0x10 | 0x40)  # IMAGE_ICON, LR_LOADFROMFILE | LR_DEFAULTSIZE
            if icon:
                return icon
        return user32.LoadIconW(None, ctypes.c_void_p(32512))  # IDI_APPLICATION

    def notify(self, title: str, message: str, warning: bool = False) -> bool:
        if not IS_WINDOWS:
            return False
        try:
            self.remove()
            shell32 = ctypes.windll.shell32
            shell32.Shell_NotifyIconW.argtypes = (wintypes.DWORD, ctypes.POINTER(_NOTIFYICONDATAW))
            shell32.Shell_NotifyIconW.restype = wintypes.BOOL
            data = _NOTIFYICONDATAW()
            data.cbSize = ctypes.sizeof(_NOTIFYICONDATAW)
            data.hWnd = _top_level_hwnd(self._widget)
            data.uID = 0x4443
            data.uFlags = self._NIF_ICON | self._NIF_TIP | self._NIF_INFO
            data.hIcon = self._load_icon()
            data.hBalloonIcon = data.hIcon
            data.szTip = title[:127]
            data.szInfoTitle = title[:63]
            data.szInfo = message[:255]
            data.dwInfoFlags = self._NIIF_WARNING if warning else self._NIIF_USER | self._NIIF_LARGE_ICON
            if not shell32.Shell_NotifyIconW(self._NIM_ADD, ctypes.byref(data)):
                return False
            self._data = data
            self._after = self._widget.after(15000, self.remove)  # ikona w obszarze powiadomień znika po chwili
            return True
        except (OSError, AttributeError):
            return False

    def remove(self) -> None:
        if self._after is not None:
            try:
                self._widget.after_cancel(self._after)
            except tk_errors():
                pass
            self._after = None
        if self._data is not None:
            try:
                ctypes.windll.shell32.Shell_NotifyIconW(self._NIM_DELETE, ctypes.byref(self._data))
            except OSError:
                pass
            self._data = None
