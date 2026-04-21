import ctypes
from ctypes import wintypes
from dataclasses import dataclass
from pathlib import Path


user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32


SW_SHOWMINIMIZED = 2


@dataclass(slots=True)
class BoundWindowState:
    found: bool
    is_foreground: bool
    is_minimized: bool
    rect: tuple[int, int, int, int] | None
    hwnd: int | None = None
    title: str = ""
    process_name: str = ""


class RECT(ctypes.Structure):
    _fields_ = [
        ("left", ctypes.c_long),
        ("top", ctypes.c_long),
        ("right", ctypes.c_long),
        ("bottom", ctypes.c_long),
    ]


class POINT(ctypes.Structure):
    _fields_ = [
        ("x", ctypes.c_long),
        ("y", ctypes.c_long),
    ]


class WINDOWPLACEMENT(ctypes.Structure):
    _fields_ = [
        ("length", ctypes.c_uint),
        ("flags", ctypes.c_uint),
        ("showCmd", ctypes.c_uint),
        ("ptMinPosition", POINT),
        ("ptMaxPosition", POINT),
        ("rcNormalPosition", RECT),
    ]


@dataclass(slots=True)
class WindowBinding:
    """
    Lightweight polling-based window binding for Windows.

    Matching:
    - process_name must match exactly if provided
    - title_contains must be contained in title if provided
    """

    enabled: bool = False
    process_name: str = ""
    title_contains: str = ""
    hide_when_unfocused: bool = True
    hide_when_minimized: bool = True

    def poll_state(self) -> BoundWindowState:
        """
        Poll current target window state.
        """
        if not self.enabled:
            return BoundWindowState(
                found=True,
                is_foreground=True,
                is_minimized=False,
                rect=None,
            )

        hwnd = self._find_target_window()
        if not hwnd:
            return BoundWindowState(
                found=False,
                is_foreground=False,
                is_minimized=False,
                rect=None,
            )

        title = self._get_window_title(hwnd)
        process_name = self._get_process_name(hwnd)
        rect = self._get_window_rect(hwnd)

        foreground_hwnd = user32.GetForegroundWindow()
        is_foreground = hwnd == foreground_hwnd
        is_minimized = self._is_minimized(hwnd)

        return BoundWindowState(
            found=True,
            is_foreground=is_foreground,
            is_minimized=is_minimized,
            rect=rect,
            hwnd=hwnd,
            title=title,
            process_name=process_name,
        )

    def _find_target_window(self) -> int | None:
        matches: list[int] = []

        @ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
        def enum_proc(hwnd, lparam):
            if not user32.IsWindowVisible(hwnd):
                return True

            title = self._get_window_title(hwnd)
            if not title:
                return True

            process_name = self._get_process_name(hwnd)
            if not process_name:
                return True

            if self.process_name and process_name.lower() != self.process_name:
                return True

            if self.title_contains and self.title_contains not in title.lower():
                return True

            matches.append(hwnd)
            return True

        user32.EnumWindows(enum_proc, 0)

        if not matches:
            return None

        foreground = user32.GetForegroundWindow()
        for hwnd in matches:
            if hwnd == foreground:
                return hwnd

        return matches[0]

    def _get_window_title(self, hwnd: int) -> str:
        length = user32.GetWindowTextLengthW(hwnd)
        if length <= 0:
            return ""

        buffer = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buffer, length + 1)
        return buffer.value.strip()

    def _get_process_name(self, hwnd: int) -> str:
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if not pid.value:
            return ""

        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000

        handle = kernel32.OpenProcess(
            PROCESS_QUERY_LIMITED_INFORMATION,
            False,
            pid.value,
        )
        if not handle:
            return ""

        try:
            size = wintypes.DWORD(260)
            buffer = ctypes.create_unicode_buffer(size.value)

            if kernel32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
                return Path(buffer.value).name.lower()
        except Exception:
            pass
        finally:
            kernel32.CloseHandle(handle)

        return ""

    def _get_window_rect(self, hwnd: int) -> tuple[int, int, int, int] | None:
        rect = RECT()
        if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
            return None
        return (rect.left, rect.top, rect.right, rect.bottom)

    def _is_minimized(self, hwnd: int) -> bool:
        placement = WINDOWPLACEMENT()
        placement.length = ctypes.sizeof(WINDOWPLACEMENT)

        if not user32.GetWindowPlacement(hwnd, ctypes.byref(placement)):
            return False

        return placement.showCmd == SW_SHOWMINIMIZED