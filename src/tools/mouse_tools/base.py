"""
Mouse Tools - Base Interface
============================
Abstract base class and unified interface for mouse interactions:
- click
- double_click
- select (drag and select)
- move
"""

from __future__ import annotations

import platform
from abc import ABC, abstractmethod

# Optional needle integration
try:
    import needle
    _HAS_NEEDLE = True
except ImportError:
    _HAS_NEEDLE = False


class MouseNavigator(ABC):
    """Abstract base class defining mouse interaction interfaces."""

    @abstractmethod
    def move(self, x: int, y: int) -> dict:
        """Move mouse cursor to coordinates (x, y)."""
        pass

    @abstractmethod
    def click(self, x: int | None = None, y: int | None = None, button: str = "left") -> dict:
        """Click at optional coordinates (x, y) with specified button (left, right, middle)."""
        pass

    @abstractmethod
    def double_click(self, x: int | None = None, y: int | None = None, button: str = "left") -> dict:
        """Double click at optional coordinates (x, y)."""
        pass

    @abstractmethod
    def select(self, start_x: int, start_y: int, end_x: int, end_y: int) -> dict:
        """Drag-select from (start_x, start_y) to (end_x, end_y)."""
        pass


# Platform-specific implementations
try:
    from tools.mouse_tools.windows import WindowsMouseNavigator
    from tools.mouse_tools.linux import LinuxMouseNavigator
except ImportError:
    from src.tools.mouse_tools.windows import WindowsMouseNavigator
    from src.tools.mouse_tools.linux import LinuxMouseNavigator


_mouse_navigator_instance: MouseNavigator | None = None


def get_mouse_navigator() -> MouseNavigator:
    """Return the MouseNavigator instance appropriate for the current OS."""
    global _mouse_navigator_instance
    if _mouse_navigator_instance is None:
        if platform.system().lower() == "windows":
            _mouse_navigator_instance = WindowsMouseNavigator()
        else:
            _mouse_navigator_instance = LinuxMouseNavigator()
    return _mouse_navigator_instance


# Exported tool functions
def mouse_move(x: int, y: int) -> dict:
    """Move mouse pointer to coordinates (x, y)."""
    return get_mouse_navigator().move(x, y)


def mouse_click(x: int | None = None, y: int | None = None, button: str = "left") -> dict:
    """Click mouse button at current position or specified coordinates (x, y)."""
    return get_mouse_navigator().click(x, y, button=button)


def mouse_double_click(x: int | None = None, y: int | None = None, button: str = "left") -> dict:
    """Double-click mouse button at current position or specified coordinates (x, y)."""
    return get_mouse_navigator().double_click(x, y, button=button)


def mouse_select(start_x: int, start_y: int, end_x: int, end_y: int) -> dict:
    """Click and drag to select an area from (start_x, start_y) to (end_x, end_y)."""
    return get_mouse_navigator().select(start_x, start_y, end_x, end_y)


# Apply needle decorators if needle is available
if _HAS_NEEDLE:
    mouse_move = needle.tool(mouse_move)
    mouse_click = needle.tool(mouse_click)
    mouse_double_click = needle.tool(mouse_double_click)
    mouse_select = needle.tool(mouse_select)
