"""Optional system-wide hotkey for the quick entry window.

Qt has no portable global shortcut.  On Windows this uses RegisterHotKey and a
native event filter; on other platforms MainWindow falls back to an in-app
QShortcut.  Keeping this optional is important: global shortcuts are a nice
convenience but must never prevent the app from starting.
"""

from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes

from PySide6.QtCore import QAbstractNativeEventFilter, QObject, Signal


MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_NOREPEAT = 0x4000
WM_HOTKEY = 0x0312


class _MSG(ctypes.Structure):
    _fields_ = [
        ("hwnd", wintypes.HWND),
        ("message", wintypes.UINT),
        ("wParam", wintypes.WPARAM),
        ("lParam", wintypes.LPARAM),
        ("time", wintypes.DWORD),
        ("pt_x", wintypes.LONG),
        ("pt_y", wintypes.LONG),
    ]


class GlobalHotkey(QObject, QAbstractNativeEventFilter):
    """Emit ``activated`` when the registered hotkey is pressed."""

    activated = Signal()

    def __init__(self, app, hotkey_id: int = 0xB0F1, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._app = app
        self._id = int(hotkey_id)
        self._registered = False

    @property
    def is_registered(self) -> bool:
        return self._registered

    def register(self, modifiers: int = MOD_CONTROL | MOD_ALT, key: int = ord("N")) -> bool:
        if sys.platform != "win32" or self._registered:
            return False
        user32 = ctypes.windll.user32
        if not user32.RegisterHotKey(None, self._id, modifiers | MOD_NOREPEAT, key):
            return False
        self._app.installNativeEventFilter(self)
        self._registered = True
        return True

    def unregister(self) -> None:
        if not self._registered:
            return
        try:
            ctypes.windll.user32.UnregisterHotKey(None, self._id)
        except Exception:
            pass
        try:
            self._app.removeNativeEventFilter(self)
        except Exception:
            pass
        self._registered = False

    def nativeEventFilter(self, event_type, message):  # noqa: N802
        if not self._registered:
            return False, 0
        if bytes(event_type) != b"windows_generic_MSG":
            return False, 0
        try:
            msg = ctypes.cast(int(message), ctypes.POINTER(_MSG)).contents
        except (TypeError, ValueError):
            return False, 0
        if msg.message == WM_HOTKEY and int(msg.wParam) == self._id:
            self.activated.emit()
            return True, 0
        return False, 0
