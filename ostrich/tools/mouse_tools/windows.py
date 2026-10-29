"""
Windows Mouse Navigator
=======================
Implementation of MouseNavigator for Windows using Win32 API via ctypes/PowerShell.
"""

from __future__ import annotations

import ctypes
import time
from typing import ClassVar

try:
    from ostrich.tools.mouse_tools.base import MouseNavigator
except ImportError:
    from ostrich.tools.mouse_tools.base import MouseNavigator


class WindowsMouseNavigator(MouseNavigator):
    """Windows implementation of MouseNavigator using ctypes user32 calls."""

    # Mouse event flags
    MOUSEEVENTF_MOVE: ClassVar[int] = 0x0001
    MOUSEEVENTF_LEFTDOWN: ClassVar[int] = 0x0002
    MOUSEEVENTF_LEFTUP: ClassVar[int] = 0x0004
    MOUSEEVENTF_RIGHTDOWN: ClassVar[int] = 0x0008
    MOUSEEVENTF_RIGHTUP: ClassVar[int] = 0x0010
    MOUSEEVENTF_MIDDLEDOWN: ClassVar[int] = 0x0020
    MOUSEEVENTF_MIDDLEUP: ClassVar[int] = 0x0040

    def _set_pos(self, x: int, y: int) -> bool:
        try:
            return bool(ctypes.windll.user32.SetCursorPos(int(x), int(y)))
        except Exception:
            return False

    def _send_event(self, flags: int, data: int = 0) -> None:
        try:
            ctypes.windll.user32.mouse_event(flags, 0, 0, data, 0)
        except Exception:
            pass

    def move(self, x: int, y: int) -> dict:
        """Move cursor to (x, y) on Windows."""
        ok = self._set_pos(x, y)
        if ok:
            return {"success": True, "message": f"Moved mouse to ({x}, {y}).", "x": x, "y": y}
        return {"success": False, "message": f"Failed to move mouse to ({x}, {y}).", "x": x, "y": y}

    def click(self, x: int | None = None, y: int | None = None, button: str = "left") -> dict:
        """Perform a mouse click on Windows."""
        if x is not None and y is not None:
            self._set_pos(x, y)

        btn = button.lower()
        if btn == "right":
            down, up = self.MOUSEEVENTF_RIGHTDOWN, self.MOUSEEVENTF_RIGHTUP
        elif btn == "middle":
            down, up = self.MOUSEEVENTF_MIDDLEDOWN, self.MOUSEEVENTF_MIDDLEUP
        else:
            down, up = self.MOUSEEVENTF_LEFTDOWN, self.MOUSEEVENTF_LEFTUP

        self._send_event(down)
        time.sleep(0.05)
        self._send_event(up)

        pos_str = f" at ({x}, {y})" if x is not None and y is not None else ""
        return {"success": True, "message": f"Performed {btn} click{pos_str}."}

    def double_click(self, x: int | None = None, y: int | None = None, button: str = "left") -> dict:
        """Perform a double click on Windows."""
        self.click(x, y, button=button)
        time.sleep(0.1)
        self.click(x, y, button=button)

        pos_str = f" at ({x}, {y})" if x is not None and y is not None else ""
        return {"success": True, "message": f"Performed {button} double click{pos_str}."}

    def select(self, start_x: int, start_y: int, end_x: int, end_y: int) -> dict:
        """Drag-select from start to end coordinates on Windows."""
        self._set_pos(start_x, start_y)
        time.sleep(0.05)
        self._send_event(self.MOUSEEVENTF_LEFTDOWN)
        time.sleep(0.05)

        # Smooth drag steps
        steps = 10
        for i in range(1, steps + 1):
            curr_x = int(start_x + (end_x - start_x) * (i / steps))
            curr_y = int(start_y + (end_y - start_y) * (i / steps))
            self._set_pos(curr_x, curr_y)
            time.sleep(0.01)

        self._send_event(self.MOUSEEVENTF_LEFTUP)
        return {
            "success": True,
            "message": f"Selected area from ({start_x}, {start_y}) to ({end_x}, {end_y}).",
            "start": {"x": start_x, "y": start_y},
            "end": {"x": end_x, "y": end_y},
        }
